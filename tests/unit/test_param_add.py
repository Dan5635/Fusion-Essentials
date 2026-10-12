"""Unit tests for ``param_add.py`` - the single and batch adds, health-guarded.

add rolls back a parameter that introduces a NEW timeline error, and publishes the favorite flag
as the parameter reads it rather than as it was asked for. The fakes below model a tiny timeline
(items with healthState) and a userParameters collection that supports add/itemByName/deleteMe.
"""

from types import SimpleNamespace

import pytest

import adsk.core

import live_api_facts
from conftest import (FakeTimeline, FakeTimelineObject, FakeUserParameter, FakeUserParameters,
                      MakeDesign, load_tool, make_timeline, payload as _payload)

params = load_tool("param_add")

_HEALTH = live_api_facts.ENUMS["fusion.FeatureHealthStates"]
_ERROR = _HEALTH["ErrorFeatureHealthState"]
_WARNING = _HEALTH["WarningFeatureHealthState"]


class BreakingUserParameters(FakeUserParameters):
    """userParameters.add that ALSO lands a broken feature in `timeline` - the downstream error the
    add's rollback guard is judged on."""

    def __init__(self, parameters=(), timeline=None):
        super().__init__(parameters)
        self._timeline = timeline

    def add(self, name, value_input, unit="", comment=""):
        param = super().add(name, value_input, unit, comment)
        self._timeline._items.append(FakeTimelineObject(name="BrokenFeature", health=_ERROR))
        return param


def _design(user_params, timeline, all_params=()):
    """A design carrying the two collections the param write path walks."""
    return MakeDesign(user_parameters=user_params, timeline=timeline,
                      all_parameters=list(all_params))


def _stub_design(monkeypatch, design):
    monkeypatch.setattr(params._common, "design", lambda: design)
    # the add path uses adsk.core.ValueInput.createByString; the string it carries is what the new
    # parameter's expression reads back as.
    monkeypatch.setattr(adsk.core.ValueInput, "createByString",
                        staticmethod(lambda s: SimpleNamespace(stringValue=s)))


class TestTimelineHealth:
    # the shared _timeline_health walk the add/delete rollback guard runs
    def test_rolls_up_errors_and_warnings(self):
        tl = FakeTimeline([FakeTimelineObject(name="A"),
                           FakeTimelineObject(name="B", health=_ERROR),
                           FakeTimelineObject(name="C", health=_WARNING),
                           FakeTimelineObject(name="D", health=_ERROR)])
        design = _design(FakeUserParameters(), tl)
        errors, warnings, total = params._timeline_health(design)
        assert total == 4
        assert errors == ["B", "D"]
        assert warnings == ["C"]


class TestAddHandler:
    def test_add_rejects_duplicate(self, monkeypatch):
        up = FakeUserParameters([FakeUserParameter(name="PartX", expression="10 mm")])
        design = _design(up, make_timeline())
        _stub_design(monkeypatch, design)
        res = params.handler(name="PartX", expression="5 mm")
        assert res["isError"] is True and "already exists" in res["message"]

    def test_add_succeeds_when_timeline_stays_healthy(self, monkeypatch):
        up = FakeUserParameters([])
        design = _design(up, make_timeline("A"))
        _stub_design(monkeypatch, design)
        out = _payload(params.handler(name="NewP", expression="3 mm"))
        assert out["added"] is True
        assert up.itemByName("NewP") is not None      # it stuck

    def test_add_rolls_back_on_new_timeline_error(self, monkeypatch):
        tl = make_timeline("A")
        up = BreakingUserParameters([], timeline=tl)   # adding will inject an error
        design = _design(up, tl)
        _stub_design(monkeypatch, design)
        res = params.handler(name="BadP", expression="oops")
        assert res["isError"] is True
        assert "rolled back" in res["message"]
        assert up.itemByName("BadP") is None          # removed again

    @pytest.mark.parametrize("args,fragment", [
        ({"name": 5, "expression": "1 mm"}, "name must be a string; received 5."),
        ({"name": "W", "expression": 25}, "expression must be a string; received 25."),
        ({"name": "W", "expression": "1 mm", "unit": None}, "unit must be a string; received None."),
        ({"name": "W", "expression": "1 mm", "comment": 7}, "comment must be a string; received 7.")])
    def test_a_non_string_single_field_is_refused_naming_it(self, monkeypatch, args, fragment):
        up = FakeUserParameters([])
        _stub_design(monkeypatch, _design(up, make_timeline("A")))
        res = params.handler(**args)
        assert res["isError"] is True and fragment in res["message"]
        assert "No parameter added" in res["message"] and up._added == []

    def test_a_rollback_that_does_not_delete_says_the_parameter_may_remain(self, monkeypatch):
        tl = make_timeline("A")
        up = BreakingUserParameters([], timeline=tl)
        real_add = up.add

        def _undeletable_add(*a):
            param = real_add(*a)
            param.deleteMe = lambda: False
            return param
        monkeypatch.setattr(up, "add", _undeletable_add)
        _stub_design(monkeypatch, _design(up, tl))
        res = params.handler(name="BadP", expression="oops")
        assert res["isError"] is True
        assert "rolled back" not in res["message"]
        assert "'BadP' may remain" in res["message"] and "param_delete" in res["message"]

    def test_add_requires_name_and_expression(self, monkeypatch):
        design = _design(FakeUserParameters(), FakeTimeline([]))
        _stub_design(monkeypatch, design)
        res1 = params.handler(name="", expression="5")
        assert res1["isError"] is True
        assert "Missing 'name'" in res1["message"]
        res2 = params.handler(name="X", expression="")
        assert res2["isError"] is True
        assert "missing 'expression'" in res2["message"]


class TestAddBatch:
    @pytest.mark.parametrize("specs,fragment", [
        ([{"name": "Prefix", "expression": "1 mm"}, "oops"], "params[1] must be a dict"),
        ([{"name": "Prefix", "expression": "1 mm"},
          {"name": "Bad", "expression": 123}], "params[1].expression must be a string"),
        ([{"name": "Prefix", "expression": "1 mm"}, {"name": "Missing"}],
         "params[1] is missing 'expression'"),
    ])
    def test_malformed_batch_is_preflighted_before_any_add(self, monkeypatch, specs, fragment):
        up = FakeUserParameters([])
        _stub_design(monkeypatch, _design(up, make_timeline("A")))
        response = params.handler(params=specs)
        assert response["isError"] is True and fragment in response["message"]
        assert "No parameters added" in response["message"]
        assert up._added == [] and up.count == 0

    # Adding N parameters is ONE batch call, not N separate calls.
    def test_batch_adds_all(self, monkeypatch):
        up = FakeUserParameters([])
        design = _design(up, make_timeline("A"))
        _stub_design(monkeypatch, design)
        out = _payload(params.handler(params=[
            {"name": "WheelDia", "expression": "350 mm"},
            {"name": "AxleDia", "expression": "14 mm", "favorite": True},
            {"name": "CrankLen", "expression": "125 mm", "comment": "arm"},
        ]))
        assert out["added_count"] == 3
        assert {r["parameter"]["name"] for r in out["results"]} == {"WheelDia", "AxleDia", "CrankLen"}
        for nm in ("WheelDia", "AxleDia", "CrankLen"):
            assert up.itemByName(nm) is not None

    def test_batch_stops_and_reports_the_failing_entry(self, monkeypatch):
        up = FakeUserParameters([])
        design = _design(up, make_timeline("A"))
        _stub_design(monkeypatch, design)
        # A blank required value is known before the batch starts, so no prefix is added.
        res = params.handler(params=[
            {"name": "Good", "expression": "1 mm"},
            {"name": "Bad", "expression": ""},
        ])
        assert res["isError"] is True
        assert "params[1].expression is empty" in res["message"]
        assert "No parameters added" in res["message"]
        assert up.itemByName("Good") is None

    def test_native_duplicate_refusal_keeps_the_honest_completed_prefix_count(self, monkeypatch):
        up = FakeUserParameters([FakeUserParameter(name="Existing", expression="2 mm")])
        _stub_design(monkeypatch, _design(up, make_timeline("A")))
        response = params.handler(params=[
            {"name": "GoodPrefix", "expression": "1 mm"},
            {"name": "Existing", "expression": "3 mm"},
        ])
        assert response["isError"] is True
        assert "already exists" in response["message"] and "1 added before this" in response["message"]
        assert up.itemByName("GoodPrefix") is not None

    def test_single_param_path_still_works(self, monkeypatch):
        up = FakeUserParameters([])
        design = _design(up, make_timeline("A"))
        _stub_design(monkeypatch, design)
        out = _payload(params.handler(name="Solo", expression="9 mm"))
        assert out["added"] is True and up.itemByName("Solo") is not None

    @pytest.mark.parametrize("bad", ["false", "true", 0, 1, None])
    @pytest.mark.parametrize("prefix", [False, True])
    def test_malformed_favorite_refuses_entire_batch_before_any_add(self, monkeypatch, bad, prefix):
        up = FakeUserParameters([FakeUserParameter(name="Witness", expression="10 mm")])
        _stub_design(monkeypatch, _design(up, make_timeline("A")))
        specs = ([{"name": "Good", "expression": "1 mm"}] if prefix else [])
        specs.append({"name": "Bad", "expression": "2 mm", "favorite": bad})
        response = params.handler(params=specs)
        assert response["isError"] is True
        assert f"params[{int(prefix)}].favorite=" in response["message"]
        assert "JSON true or false" in response["message"] and "No parameters added" in response["message"]
        assert up._added == [] and up.count == 1 and up.itemByName("Witness").expression == "10 mm"

    def test_boolean_and_omitted_batch_favorites_keep_actual_readback(self, monkeypatch):
        up = FakeUserParameters([])
        _stub_design(monkeypatch, _design(up, make_timeline("A")))
        result = _payload(params.handler(params=[
            {"name": "Default", "expression": "2 mm"},
            {"name": "On", "expression": "2 mm", "favorite": True},
            {"name": "Off", "expression": "2 mm", "favorite": False}]))
        assert result["added_count"] == 3
        assert [r["favorite"] for r in result["results"]] == [False, True, False]
        assert [up.itemByName(name).isFavorite for name in ("Default", "On", "Off")] == [False, True, False]


class TextRefusingUserParameters(FakeUserParameters):
    """userParameters.add as a TEXT parameter measures (measure_api.py row parameter-favorite-maker-
    text-value-and-fresh-appearances): under units 'Text' the expression must be a QUOTED literal,
    and the same string unquoted is refused right at the add with "3 : Invalid expression". A name
    Fusion will not take is refused by the SAME call in its own words - "3 : param name is not
    valid" - which is what makes the two failures tellable apart only by the message."""

    def add(self, name, value_input, unit="", comment=""):
        if " " in name or "!" in name:
            raise RuntimeError("3 : param name is not valid")
        expression = getattr(value_input, "stringValue", "") or ""
        if unit == "Text" and "'" not in expression:
            raise RuntimeError("3 : Invalid expression")
        return super().add(name, value_input, unit, comment)


class UnitRefusingUserParameters(FakeUserParameters):
    """userParameters.add refusing outright whatever it was handed as a unit - the seam that decides
    what the tool's except path has to survive. Its wording stands for a refusal, not for Fusion's."""

    def add(self, name, value_input, unit="", comment=""):
        if not isinstance(unit, str):
            raise RuntimeError("3 : the unit was refused")
        return super().add(name, value_input, unit, comment)


class TestTextParameter:
    def test_an_unquoted_text_expression_is_refused_with_the_quoting_rule(self, monkeypatch):
        # Fusion's own refusal says "Invalid expression" and nothing else, which leaves a caller
        # guessing between the unit, the name and the expression - so the add carries the one
        # correction that fixes it, spelled with the quotes.
        up = TextRefusingUserParameters([])
        _stub_design(monkeypatch, _design(up, make_timeline("A")))
        res = params.handler(name="Strategy", expression="Roughing", unit="Text")
        assert res["isError"] is True
        assert "Invalid expression" in res["message"]        # what Fusion said
        assert "\"'Roughing'\"" in res["message"]            # the expression that would have worked
        assert up.itemByName("Strategy") is None

    def test_a_quoted_text_expression_lands_under_the_text_unit(self, monkeypatch):
        # The other half: 'Text' is not translated or defaulted away on the road to Fusion, so the
        # quoted literal the caller wrote is what the parameter ends up holding.
        up = TextRefusingUserParameters([])
        _stub_design(monkeypatch, _design(up, make_timeline("A")))
        out = _payload(params.handler(name="Strategy", expression="'Roughing'", unit="Text"))
        assert out["added"] is True
        assert up._added[0][2] == "Text"
        assert up.itemByName("Strategy").expression == "'Roughing'"

    def test_a_name_refusal_under_the_text_unit_carries_no_quoting_remedy(self, monkeypatch):
        # Same unit, same unquoted expression - and a DIFFERENT failure. The remedy answers the
        # refusal Fusion actually returned, so it reads that message rather than re-deriving a
        # cause from the inputs, which are equally consistent with the wrong explanation.
        up = TextRefusingUserParameters([])
        _stub_design(monkeypatch, _design(up, make_timeline("A")))
        res = params.handler(name="bad name!", expression="Roughing", unit="Text")
        assert res["isError"] is True
        assert "param name is not valid" in res["message"]
        assert "QUOTED" not in res["message"]

    def test_a_non_string_unit_in_a_batch_errors_instead_of_raising(self, monkeypatch):
        # Batch units are checked as pure request data before any earlier parameter can land.
        up = UnitRefusingUserParameters([])
        _stub_design(monkeypatch, _design(up, make_timeline("A")))
        res = params.handler(params=[{"name": "Loose", "expression": "1", "unit": 5}])
        assert res["isError"] is True
        assert "params[0].unit must be a string" in res["message"]
        assert up._added == []


class TestAddFavorite:
    def test_favorite_reported_from_param_state(self, monkeypatch):
        up = FakeUserParameters([])
        design = _design(up, make_timeline("A"))
        _stub_design(monkeypatch, design)
        out = _payload(params.handler(name="P", expression="5 mm", favorite=True))
        assert out["favorite"] is True
        assert up.itemByName("P").isFavorite is True

    def test_a_stuck_favorite_is_published_as_the_parameter_reads_it(self, monkeypatch):
        # The add payload is a READ of the parameter that landed, never an echo of the request: the
        # isFavorite assignment here is accepted and changes nothing, so both the flag and the
        # parameter row report the state the parameter actually carries. Echoing the request would
        # report favorite:true over a parameter nothing was set on.
        class StuckFavoriteParam(FakeUserParameter):
            @property
            def isFavorite(self):
                return False

            @isFavorite.setter
            def isFavorite(self, value):
                pass                                  # silently ignores the assignment

        class StuckFavoriteParams(FakeUserParameters):
            def add(self, name, value_input, unit="", comment=""):
                p = StuckFavoriteParam(name=name, unit=unit, comment=comment)
                self._parameters.append(p)
                return p

        up = StuckFavoriteParams([])
        design = _design(up, make_timeline("A"))
        _stub_design(monkeypatch, design)
        out = _payload(params.handler(name="NewP", expression="3 mm", favorite=True))
        assert out["added"] is True
        assert out["favorite"] is False                # as it READS, not as it was asked for
        assert out["parameter"]["favorite"] is False   # the same read, in the parameter row
        assert out["parameter"]["name"] == "NewP"
        assert up.itemByName("NewP").isFavorite is False
