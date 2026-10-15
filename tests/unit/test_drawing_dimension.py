"""Unit tests for ``drawing_dimension.py`` - one view of the active drawing dimensioned.

Covers: the strategy/datum maps pinned against the measured member names and resolved BY NAME, the
view-index bounds refusal, the input-did-not-take read-backs, the census every action is judged by
(a manual add must grow Sheet.drawingDimensions by exactly one item of the kind asked, read off the
collection since the returned object reads Unknown; an auto run must raise the count), the curve
and point refusals made before any add, and - on a build whose sheet carries no
drawingDimensions - the modified-flag gate the auto route falls back to. No live Fusion.
"""

import inspect
import types

import pytest

import adsk  # the mock package conftest installed at import time
import live_api_facts
from conftest import (FakeSheet, FakeView, drawing_enum, load_tool, make_drawing,
                      make_drawing_session)

dim = load_tool("drawing_dimension")

# The API-declared members of the two families the manual route reads; live_api_facts carries
# each family once the enum sweep measures it.
_CURVE_TYPES = live_api_facts.ENUMS.get("drawing.ViewCurveTypes") or dict(zip(
    ("LineViewCurveType", "ArcViewCurveType", "CircleViewCurveType", "EllipseViewCurveType",
     "SplineViewCurveType", "PolylineViewCurveType", "UnknownViewCurveType"), range(7)))
_DIMENSION_TYPES = live_api_facts.ENUMS.get("drawing.DrawingDimensionTypes") or dict(zip(
    ("UnknownDrawingDimensionType", "LinearDrawingDimensionType", "AlignedDrawingDimensionType",
     "AngularDrawingDimensionType", "RadiusDrawingDimensionType", "DiameterDrawingDimensionType",
     "JoggedRadiusDrawingDimensionType", "OrdinateDrawingDimensionType",
     "ArcLengthDrawingDimensionType"), range(9)))


class _Point:
    """A DrawingPoint whose coordinate is the pair given; DrawingPoint carries no shape dump."""

    def __init__(self, x, y):
        self.coordinate = types.SimpleNamespace(x=x, y=y)


class _Curve:
    """A ViewCurve: a type and four point accessors, None where live reads null; no shape dump."""

    def __init__(self, member, start=None, end=None, mid=None, center=None):
        self.type = _CURVE_TYPES[member]
        self.startPoint, self.endPoint = _Point(*start), _Point(*end)
        self.midPoint = _Point(*mid) if mid else None
        self.centerPoint = _Point(*center) if center else None


def _curves():
    """Curve 0 a 60-long line, curve 1 the vertical line meeting it, curve 2 a circle, 3 an arc."""
    return [_Curve("LineViewCurveType", (0, 0), (60, 0), mid=(30, 0)),
            _Curve("LineViewCurveType", (60, 0), (60, 30), mid=(60, 15)),
            _Curve("CircleViewCurveType", (36, 20), (36, 20), center=(30, 20)),
            _Curve("ArcViewCurveType", (70, 20), (60, 30), mid=(67, 27), center=(60, 20))]


class _Dimension:
    """A DrawingDimension: isValid and type only, as measured; no shape dump."""

    def __init__(self, member, valid=True):
        self.isValid = valid
        self.type = _DIMENSION_TYPES[member]


class _Dimensions:
    """Sheet.drawingDimensions - count, item and the six add factories; no shape dump."""

    def __init__(self, count=0, existing="LinearDrawingDimensionType", grows=1,
                 returns="dimension", raises=None, valid=True, lands_last=True, lands_as=None,
                 sorts=False, also=None):
        kinds = [existing] * count if isinstance(existing, str) else list(existing)
        self._items = [_Dimension(member) for member in kinds]
        self._grows, self._returns, self._raises = grows, returns, raises
        self._valid, self._lands_last, self._lands_as, self._sorts = (valid, lands_last,
                                                                      lands_as, sorts)
        self._also = also          # a second item of another kind an add appends beside its own
        self._unreadable = False
        self.calls = []

    @property
    def count(self):
        if self._unreadable:
            raise RuntimeError("4 : An API Object refers to a deleted Object")
        return len(self._items)

    def item(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def _add(self, member, name, *args):
        # the new item reads its kind; the object handed back reads Unknown and is no item
        self.calls.append((name, args))
        if self._raises:
            raise RuntimeError(self._raises)
        for _ in range(self._grows):
            self._items.insert(len(self._items) if self._lands_last else 0,
                               _Dimension(self._lands_as or member))
        if self._also:
            self._items.append(_Dimension(self._also))
        if self._sorts:
            self._items.sort(key=lambda d: d.type)
        if self._returns == "null":
            return None
        return _Dimension("UnknownDrawingDimensionType", valid=self._valid)

    def addLinearDimension(self, start, end, placement, align):
        member = "AlignedDrawingDimensionType" if align else "LinearDrawingDimensionType"
        return self._add(member, "addLinearDimension", start, end, placement, align)

    def addRadialDimension(self, curve, placement):
        return self._add("RadiusDrawingDimensionType", "addRadialDimension", curve, placement)

    def addDiameterDimension(self, curve, placement):
        return self._add("DiameterDrawingDimensionType", "addDiameterDimension", curve, placement)

    def addAngularDimension(self, first, second, placement):
        return self._add("AngularDrawingDimensionType", "addAngularDimension", first, second,
                         placement)

    def addArcLengthDimension(self, curve, placement):
        return self._add("ArcLengthDrawingDimensionType", "addArcLengthDimension", curve,
                         placement)

    def addJoggedRadiusDimension(self, curve, center_override, placement, jog):
        return self._add("JoggedRadiusDrawingDimensionType", "addJoggedRadiusDimension", curve,
                         center_override, placement, jog)


def _counted(sheet, count=0, auto_adds=0, auto_unreadable=False, **knobs):
    """Give `sheet` a drawingDimensions collection; its autoDimension adds `auto_adds` to it."""
    dims = _Dimensions(count, **knobs)
    sheet.drawingDimensions = dims
    auto = sheet.autoDimension

    def _auto(dimension_input):
        dims._items.extend(_Dimension("LinearDrawingDimensionType") for _ in range(auto_adds))
        dims._unreadable = auto_unreadable
        return auto(dimension_input)

    sheet.autoDimension = _auto
    return dims

# The member names adsk.drawing carries on this Fusion build, written out here so the tool's own
# maps are checked against something independent of them - a typo in either map fails the pin below
# AND misses the measured enum, instead of quietly dimensioning with the input's default.
EXPECTED_STRATEGY_MEMBERS = {
    "overall": "OverallDimensionStrategyType",
    "automatic": "AutomaticDimensionStrategyType",
    "baseline": "BaselineDimensionStrategyType",
    "chain": "ChainDimensionStrategyType",
    "ordinate": "OrdinateDimensionStrategyType",
    "symmetric": "SymmetricDimensionStrategyType",
    "symmetric_with_baseline": "SymmetricWithBaselineDimensionStrategyType",
    "symmetric_with_ordinate": "SymmetricWithOrdinateDimensionStrategyType",
}
EXPECTED_DATUM_MEMBERS = {
    "bottom_left": "BottomLeftDatumPositionType",
    "bottom_right": "BottomRightDatumPositionType",
    "top_left": "TopLeftDatumPositionType",
    "top_right": "TopRightDatumPositionType",
}


class _ViewIgnoringInput:
    """An AutoDimensionInput whose view assignment silently does not take - the SWIG-proxy shape the
    handler's read-back guards against. AutoDimensionInput carries no shape dump."""

    view = property(lambda self: None, lambda self, value: None)

    def __init__(self):
        self.dimensionStrategy = None
        self.datumLocation = None


from conftest import payload as _payload


@pytest.fixture
def env(monkeypatch):
    """An active drawing document: one sheet, four views each holding _curves(), a recording
    AutoDimensionInput. The whole adsk.drawing surface goes in wholesale, so this file does not
    depend on what a sibling drawing test file left behind in either collection order."""
    state = types.SimpleNamespace()
    monkeypatch.setattr(adsk.core.Point2D, "create", lambda x, y: (x, y))
    families = {"ViewCurveTypes": types.SimpleNamespace(**_CURVE_TYPES),
                "DrawingDimensionTypes": types.SimpleNamespace(**_DIMENSION_TYPES),
                "DrawingPoint": types.SimpleNamespace(create=lambda xy: ("placed",) + tuple(xy))}

    def _install(views=4, **document_or_sheet):
        document_knobs = {k: document_or_sheet.pop(k) for k in ("modified_raises",)
                          if k in document_or_sheet}
        sheet = FakeSheet("Sheet1", views=[FakeView("view%d" % i, curves=_curves())
                                           for i in range(views)], **document_or_sheet)
        state.document = make_drawing(sheets=[sheet], **document_knobs)
        state.sheet = sheet
        make_drawing_session(monkeypatch, state.document, **families)
        return state.document

    _install()
    state.install = _install
    return state


class TestEnumMaps:
    def test_strategy_map_matches_the_measured_member_names(self):
        # the table is the shared _drawing_common one, so this pins what BOTH the creation-time
        # generator and this tool offer: all eight members the family carries
        assert dim._drawing_common.DIMENSION_STRATEGIES == EXPECTED_STRATEGY_MEMBERS

    def test_datum_map_matches_the_measured_member_names(self):
        assert dim._DATUM_MEMBERS == EXPECTED_DATUM_MEMBERS

    def test_choice_options_and_defaults_match_the_handler_signature(self):
        # the Choice and the handler signature each carry a default; they must be the SAME value, or
        # a caller who omits the argument gets a different strategy than the schema advertises.
        params = inspect.signature(dim.handler).parameters
        assert params["strategy"].default == dim._STRATEGY.default
        assert params["datum"].default == dim._DATUM.default
        assert dim._STRATEGY.default in EXPECTED_STRATEGY_MEMBERS
        assert dim._DATUM.default in EXPECTED_DATUM_MEMBERS
        assert list(dim._STRATEGY.options) == list(EXPECTED_STRATEGY_MEMBERS)
        assert list(dim._DATUM.options) == list(EXPECTED_DATUM_MEMBERS)


class TestHappyPath:
    def test_an_inactive_named_sheet_is_targeted(self, env, monkeypatch):
        front = FakeSheet("Front", views=[FakeView("front")])
        detail = FakeSheet("Detail", views=[FakeView("detail")])
        env.document = make_drawing(sheets=[front, detail], active=1)
        make_drawing_session(monkeypatch, env.document)
        _payload(dim.handler(view=0, sheet="Front"))
        assert front._auto_calls and not detail._auto_calls

    def test_a_missing_named_sheet_refuses_before_mutation(self, env):
        res = dim.handler(view=0, sheet="Missing")
        assert res["isError"] is True
        assert env.sheet._auto_calls == []

    def test_dimensions_the_requested_view_with_the_requested_strategy_and_datum(self, env):
        out = _payload(dim.handler(view=2, strategy="chain", datum="top_right"))
        assert out["dimensioned"] is True
        assert (out["view_index"], out["view_count"]) == (2, 4)
        assert (out["strategy"], out["datum"]) == ("chain", "top_right")
        assert out["sheet"] == "Sheet1"
        inp = env.sheet._auto_input
        assert inp.view is env.sheet.views.item(2)            # the INDEXED view, not the first
        strategies = adsk.drawing.DimensionStrategyTypes
        assert inp.dimensionStrategy == getattr(strategies,
                                                EXPECTED_STRATEGY_MEMBERS["chain"])
        datums = adsk.drawing.DatumPositionsTypes
        assert inp.datumLocation == getattr(datums, EXPECTED_DATUM_MEMBERS["top_right"])
        assert env.sheet._auto_calls == [inp]                 # the input built here is the one used

    def test_defaults_are_baseline_from_the_bottom_left(self, env):
        out = _payload(dim.handler(view=0))
        assert (out["strategy"], out["datum"]) == ("baseline", "bottom_left")
        strategies = adsk.drawing.DimensionStrategyTypes
        assert env.sheet._auto_input.dimensionStrategy == getattr(
            strategies, EXPECTED_STRATEGY_MEMBERS["baseline"])

    def test_each_strategy_lands_the_member_measured_for_it(self, env):
        for key, member in EXPECTED_STRATEGY_MEMBERS.items():
            _payload(dim.handler(view=0, strategy=key))
            assert env.sheet._auto_input.dimensionStrategy == getattr(
                adsk.drawing.DimensionStrategyTypes, member), key

    def test_each_datum_lands_the_member_measured_for_it(self, env):
        for key, member in EXPECTED_DATUM_MEMBERS.items():
            _payload(dim.handler(view=0, datum=key))
            assert env.sheet._auto_input.datumLocation == getattr(
                adsk.drawing.DatumPositionsTypes, member), key

    def test_declared_returns_are_present(self, env):
        _counted(env.sheet, auto_adds=1)
        out = _payload(dim.handler(view=0))
        for spec in dim.RETURNS:
            assert spec.assert_present(out) == "", spec.assert_present(out)


class TestViewSelection:
    def test_index_past_the_last_view_names_the_count_and_the_legal_range(self, env):
        res = dim.handler(view=4)
        assert res["isError"] is True
        assert "4 view(s)" in res["message"]
        assert "0 to 3" in res["message"]

    def test_negative_index_is_refused(self, env):
        res = dim.handler(view=-1)
        assert res["isError"] is True
        assert "-1" in res["message"]

    def test_omitted_view_names_the_range_rather_than_dimensioning_view_zero(self, env):
        res = dim.handler()
        assert res["isError"] is True
        assert "0 to 3" in res["message"]
        assert env.sheet._auto_calls == []

    def test_non_integer_view_is_refused(self, env):
        res = dim.handler(view="middle")
        assert res["isError"] is True
        assert "integer" in res["message"]

    @pytest.mark.parametrize("view", [True, 1.9])
    def test_a_bool_or_fractional_view_is_refused_naming_it(self, env, view):
        res = dim.handler(view=view)
        assert res["isError"] is True
        assert f"(got {view!r})" in res["message"]
        assert env.sheet._auto_calls == []

    def test_a_digit_string_view_is_read_as_its_index(self, env):
        assert _payload(dim.handler(view="2"))["view_index"] == 2

    def test_an_unreadable_view_count_is_refused_as_unread_not_as_no_views(self, env):
        class _UnreadViews:
            """A views collection whose count raises; no shape dump."""

            @property
            def count(self):
                raise RuntimeError("4 : An API Object refers to a deleted Object")

        env.sheet.views = _UnreadViews()
        res = dim.handler(view=0)
        assert res["isError"] is True and "did not read" in res["message"]
        assert env.sheet._auto_calls == []

    def test_sheet_without_views_is_refused_naming_the_sheet(self, env):
        env.install(views=0)
        res = dim.handler(view=0)
        assert res["isError"] is True
        assert "Sheet1" in res["message"]
        assert "no views" in res["message"]


class TestInputGuards:
    def test_unknown_strategy_is_refused_listing_the_legal_values(self, env):
        res = dim.handler(view=0, strategy="diagonal")
        assert res["isError"] is True
        assert "ordinate" in res["message"]
        assert env.sheet._auto_calls == []

    def test_enum_member_absent_on_this_fusion_version_is_refused(self, env, monkeypatch):
        # every member EXCEPT the baseline one - a version that lacks it must refuse, not silently
        # auto-dimension with the input's default strategy.
        kept = [n for k, n in EXPECTED_STRATEGY_MEMBERS.items() if k != "baseline"]
        monkeypatch.setattr(adsk.drawing, "DimensionStrategyTypes",
                            drawing_enum("DimensionStrategyTypes", keep=kept))
        res = dim.handler(view=0, strategy="baseline")
        assert res["isError"] is True
        assert "not available" in res["message"]
        assert env.sheet._auto_calls == []

    def test_view_assignment_that_does_not_take_is_refused(self, env):
        env.install(auto_dimension_input=_ViewIgnoringInput)
        res = dim.handler(view=1)
        assert res["isError"] is True
        assert "reads back null" in res["message"]
        assert env.sheet._auto_calls == []

    def test_active_document_that_is_not_a_drawing_is_refused(self, env, monkeypatch):
        make_drawing_session(monkeypatch, object())
        res = dim.handler(view=0)
        assert res["isError"] is True
        assert "not a drawing" in res["message"]


class TestEffectHonesty:
    def test_autodimension_false_is_a_failure(self, env):
        env.install(auto_dimension_ok=False)
        res = dim.handler(view=0)
        assert res["isError"] is True
        assert "returned false" in res["message"]

    def test_success_that_leaves_the_document_unmodified_is_a_failure(self, env):
        env.install(modifies=False)             # the API says true and changes nothing
        res = dim.handler(view=0)
        assert res["isError"] is True
        assert "still unmodified" in res["message"]

    def test_already_modified_document_is_reported_as_inconclusive(self, env):
        env.document.isModified = True
        out = _payload(dim.handler(view=0))
        assert out["document_modified_before"] is True
        assert out["document_modified"] is True
        assert "ALREADY modified" in out["note"]

    def test_unreadable_modified_flag_is_published_as_null_not_false(self, env):
        env.install(modified_raises="isModified unavailable")
        out = _payload(dim.handler(view=0))
        assert out["document_modified"] is None
        assert out["document_modified_before"] is None
        assert "could not be read" in out["note"]

    def test_note_states_the_dimensions_cannot_be_counted_without_the_collection(self, env):
        out = _payload(dim.handler(view=0))
        assert "cannot be counted" in out["note"]
        assert out["dimension_count_before"] is None and out["dimension_count_after"] is None


def _manual(**args):
    """The linear request on view 0 this file varies one input of at a time."""
    request = {"view": 0, "action": "linear", "from_point": "0:start", "to_point": "0:end",
               "placement": [30, -15]}
    request.update(args)
    return dim.handler(**{k: v for k, v in request.items() if v is not None})


class TestCountGate:
    def test_a_count_that_does_not_move_is_an_error(self, env):
        _counted(env.sheet, count=2, grows=0)
        res = _manual()
        assert res["isError"] is True
        assert "reads 2 (2 before)" in res["message"]

    def test_a_count_that_grows_by_two_is_an_error(self, env):
        # One linear plus one item of ANOTHER kind: only the total-count half of the gate sees it.
        _counted(env.sheet, also="AngularDrawingDimensionType")
        res = _manual()
        assert res["isError"] is True
        assert "reads 2 (0 before) and its linear count 1 (0 before)" in res["message"]

    @pytest.mark.parametrize("knobs,said", [({"returns": "null"}, "returned null"),
                                            ({"valid": False}, "isValid reads False"),
                                            ({"valid": None}, "isValid reads None")])
    def test_a_null_or_invalid_return_is_an_error_even_when_the_census_grew(self, env, knobs,
                                                                          said):
        _counted(env.sheet, **knobs)
        res = _manual()
        assert res["isError"] is True
        assert said in res["message"] and "reads 1 (0 before)" in res["message"]
        assert "linear count 1 (0 before)" in res["message"]

    def test_a_new_item_of_another_kind_is_an_error(self, env):
        _counted(env.sheet, lands_as="AlignedDrawingDimensionType")
        res = _manual()
        assert res["isError"] is True
        assert "reads 1 (0 before) and its linear count 0 (0 before)" in res["message"]

    def test_a_raise_from_fusion_surfaces_with_the_count_it_left(self, env):
        _counted(env.sheet, count=1, raises="3 : radial dimension creation failed")
        res = dim.handler(view=0, action="radial", curve=2, placement=[40, 40])
        assert res["isError"] is True
        assert "3 : radial dimension creation failed" in res["message"]
        assert "reads 1 (1 before)" in res["message"]
        assert "Retry with other points, or on a fresh drawing of the same source (drawing_create)" in res["message"]

    def test_auto_refuses_a_run_that_added_nothing(self, env):
        _counted(env.sheet, count=3, auto_adds=0)
        res = dim.handler(view=0)
        assert res["isError"] is True
        assert "reads 3 after the call (3 before)" in res["message"]

    def test_auto_whose_after_count_does_not_read_is_an_error(self, env):
        _counted(env.sheet, count=3, auto_adds=1, auto_unreadable=True)
        res = dim.handler(view=0)
        assert res["isError"] is True
        assert "reads None after the call (3 before)" in res["message"]

    def test_auto_that_raised_the_count_reports_both_counts(self, env):
        _counted(env.sheet, count=3, auto_adds=1)
        out = _payload(dim.handler(view=1, strategy="chain"))
        assert (out["dimension_count_before"], out["dimension_count_after"]) == (3, 4)
        assert (out["action"], out["view_index"], out["strategy"]) == ("auto", 1, "chain")
        # The note states the counts and names no view as the owner of an added dimension.
        assert out["note"] == (
            "The sheet's dimension count went from 3 to 4 (1 added); they may sit on views "
            "projected from view 1. A manual dimension already on the sheet may stop being drawn "
            "after an auto run: check it in drawing_export's PDF. Fusion has no API to delete a "
            "placed dimension or read its value. doc_save persists the drawing.")

    def test_manual_is_refused_where_the_sheet_has_no_dimension_collection(self, env):
        res = _manual()
        assert res["isError"] is True
        assert "drawingDimensions.count did not read" in res["message"]


class TestManualActions:
    @pytest.mark.parametrize("action,aligned", [("linear", False), ("aligned", True)])
    def test_linear_and_aligned_hand_the_named_points_and_the_align_flag(self, env, action,
                                                                        aligned):
        dims = _counted(env.sheet)
        out = _payload(_manual(action=action, from_point="0:start", to_point="1:end"))
        line0, line1 = (env.sheet.views.item(0).viewCurves.item(i) for i in (0, 1))
        assert dims.calls == [("addLinearDimension",
                               (line0.startPoint, line1.endPoint, ("placed", 30.0, -15.0),
                                aligned))]
        assert (out["dimension_count_before"], out["dimension_count_after"]) == (0, 1)
        assert (out["dimension_index"], out["action"], out["view_index"]) == (0, action, 0)
        assert (out["placement"], out["placement_unit"]) == ([30.0, -15.0], "mm")
        assert out["type_read"] == action

    @pytest.mark.parametrize("action,method", [("radial", "addRadialDimension"),
                                               ("diameter", "addDiameterDimension")])
    def test_radial_and_diameter_reach_their_own_factory_with_the_circle(self, env, action,
                                                                        method):
        dims = _counted(env.sheet)
        out = _payload(dim.handler(view=0, action=action, curve=2, placement=[40, 40]))
        circle = env.sheet.views.item(0).viewCurves.item(2)
        assert dims.calls == [(method, (circle, ("placed", 40.0, 40.0)))]
        assert out["type_read"] == action

    def test_radial_on_a_line_is_refused_before_the_add_naming_the_read_type(self, env):
        dims = _counted(env.sheet)
        res = dim.handler(view=0, action="radial", curve=0, placement=[40, 40])
        assert res["isError"] is True
        assert "reads as line" in res["message"] and "circle or arc" in res["message"]
        assert dims.calls == []

    def test_arc_length_reaches_its_factory_with_the_arc_and_reads_its_kind(self, env):
        dims = _counted(env.sheet)
        out = _payload(dim.handler(view=0, action="arc_length", curve=3, placement=[75, 35]))
        arc = env.sheet.views.item(0).viewCurves.item(3)
        assert dims.calls == [("addArcLengthDimension", (arc, ("placed", 75.0, 35.0)))]
        assert out["type_read"] == "arc_length"

    @pytest.mark.parametrize("action,curve,said", [
        ("arc_length", 0, "reads as line; action='arc_length' takes arc or spline"),
        ("arc_length", 2, "reads as circle; action='arc_length' takes arc or spline"),
        ("jogged_radius", 0, "reads as line; action='jogged_radius' takes circle or arc or spline"),
    ])
    def test_a_curve_outside_the_factorys_types_is_refused_before_the_add(self, env, action,
                                                                          curve, said):
        dims = _counted(env.sheet)
        res = dim.handler(view=0, action=action, curve=curve, placement=[75, 35],
                          **({"center_override": [70, 60], "jog": [77, 64]}
                             if action == "jogged_radius" else {}))
        assert res["isError"] is True and said in res["message"]
        assert dims.calls == []

    def test_jogged_radius_hands_center_override_placement_and_jog_in_that_order(self, env):
        dims = _counted(env.sheet)
        out = _payload(dim.handler(view=0, action="jogged_radius", curve=2, placement=[85, 60],
                                   center_override=[70, 60], jog=[77, 64]))
        circle = env.sheet.views.item(0).viewCurves.item(2)
        assert dims.calls == [("addJoggedRadiusDimension",
                               (circle, ("placed", 70.0, 60.0), ("placed", 85.0, 60.0),
                                ("placed", 77.0, 64.0)))]
        assert out["type_read"] == "jogged_radius"
        assert (out["placement"], out["center_override"], out["jog"], out["placement_unit"]) == (
            [85.0, 60.0], [70.0, 60.0], [77.0, 64.0], "mm")

    @pytest.mark.parametrize("missing", ["center_override", "jog"])
    def test_jogged_radius_without_a_point_is_refused_naming_it_and_the_unit(self, env, missing):
        dims = _counted(env.sheet)
        points = {"center_override": [70, 60], "jog": [77, 64], missing: None}
        res = dim.handler(view=0, action="jogged_radius", curve=2, placement=[85, 60], **points)
        assert res["isError"] is True
        assert f"needs '{missing}' as [x, y] in sheet mm" in res["message"]
        assert dims.calls == []

    def test_jog_on_radial_is_refused_as_an_input_it_does_not_read(self, env):
        dims = _counted(env.sheet)
        res = dim.handler(view=0, action="radial", curve=2, placement=[40, 40], jog=[77, 64])
        assert res["isError"] is True and "does not take jog" in res["message"]
        assert dims.calls == []

    def test_angular_takes_two_different_lines_and_refuses_a_circle(self, env):
        dims = _counted(env.sheet)
        for pair, said in (([0, 0], "two different line indices"), ([0, 2], "reads as circle")):
            res = dim.handler(view=0, action="angular", curves=pair, placement=[50, 5])
            assert res["isError"] is True and said in res["message"], pair
        assert dims.calls == []
        out = _payload(dim.handler(view=0, action="angular", curves=[0, 1], placement=[50, 5]))
        line0, line1 = (env.sheet.views.item(0).viewCurves.item(i) for i in (0, 1))
        assert dims.calls == [("addAngularDimension", (line0, line1, ("placed", 50.0, 5.0)))]
        assert out["type_read"] == "angular"

    def test_digit_string_curve_indices_resolve_and_others_are_refused_by_value(self, env):
        dims = _counted(env.sheet)
        _payload(dim.handler(view=0, action="radial", curve="2", placement=[40, 40]))
        _payload(dim.handler(view=0, action="angular", curves=["0", "1"], placement=[50, 5]))
        res = dim.handler(view=0, action="radial", curve="2x", placement=[40, 40])
        assert res["isError"] is True and "(got '2x')" in res["message"]
        assert [call[0] for call in dims.calls] == ["addRadialDimension", "addAngularDimension"]

    @pytest.mark.parametrize("ref,said", [
        ("2", "'<curve_index>:<start|end|mid|center>'"),
        ("0:corner", "'<curve_index>:<start|end|mid|center>'"),
        ("4:start", "(0 to 3)"),
        ("2:mid", "reads as circle, which has no mid point; it has start, end, center"),
    ])
    def test_a_point_ref_is_refused_before_the_add(self, env, ref, said):
        dims = _counted(env.sheet)
        res = _manual(from_point=ref)
        assert res["isError"] is True
        assert said in res["message"] and "from_point" in res["message"]
        assert dims.calls == []

    @pytest.mark.parametrize("placement", [None, [30, -15, 0]])
    def test_a_placement_that_is_not_one_pair_is_refused_naming_the_unit(self, env, placement):
        dims = _counted(env.sheet)
        res = _manual(placement=placement)
        assert res["isError"] is True
        assert "[x, y] in sheet mm" in res["message"]
        assert dims.calls == []

    def test_a_json_string_placement_or_curves_is_read_as_the_list_it_spells(self, env):
        # A client whose cached schema predates a reload sends a new array input as text.
        dims = _counted(env.sheet)
        out = _payload(_manual(placement="[30, -15]"))
        assert out["placement"] == [30.0, -15.0]
        _payload(dim.handler(view=0, action="angular", curves="[0, 1]", placement=[50, 5]))
        assert [call[0] for call in dims.calls] == ["addLinearDimension", "addAngularDimension"]
        res = _manual(placement="thirty by fifteen")
        assert res["isError"] is True and "(got 'thirty by fifteen')" in res["message"]

    def test_dimension_index_is_where_the_census_changed_not_the_old_count(self, env):
        _counted(env.sheet, count=2, existing="AngularDrawingDimensionType", lands_last=False)
        out = _payload(_manual())
        assert (out["dimension_count_after"], out["dimension_index"]) == (3, 0)
        assert out["type_read"] == "linear"

    def test_a_reordered_census_publishes_no_index_but_still_the_kind_read(self, env):
        _counted(env.sheet, existing=["AngularDrawingDimensionType", "LinearDrawingDimensionType"],
                 sorts=True)
        out = _payload(_manual())
        assert (out["dimension_count_after"], out["dimension_index"]) == (3, None)
        assert out["type_read"] == "linear"

    @pytest.mark.parametrize("args,stray", [({"curve": 1}, "curve"),
                                            ({"strategy": "chain"}, "strategy")])
    def test_an_input_the_action_does_not_read_is_refused(self, env, args, stray):
        dims = _counted(env.sheet)
        res = _manual(**args)
        assert res["isError"] is True
        assert f"does not take {stray}" in res["message"]
        assert dims.calls == []

    def test_auto_refuses_a_manual_input(self, env):
        res = dim.handler(view=0, placement=[1, 2])
        assert res["isError"] is True
        assert "does not take placement" in res["message"]
        assert env.sheet._auto_calls == []
