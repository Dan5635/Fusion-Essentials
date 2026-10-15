"""Focused design-local sheet-metal rule edit checks."""
from conftest import install as _install_design

from types import SimpleNamespace

import pytest
from conftest import load_tool
from tests.fakes.scaffold import _NamedCollection

mod = load_tool("sheet_edit_rule")



@pytest.fixture
def rule_design(monkeypatch):
    source = SimpleNamespace(name="Steel (mm)")
    local = SimpleNamespace(count=0)
    design = SimpleNamespace(designSheetMetalRules=local)
    _install_design(mod, design)
    monkeypatch.setattr(mod._RULE, "resolve", lambda raw: ((source, "library"), None))
    monkeypatch.setattr(mod._sheet_common, "matching_rules", lambda *args: [])
    return design, source


def test_copy_requires_initialized_design_rules(rule_design):
    design, _source = rule_design
    result = mod.handler(action="copy", rule="library:Steel (mm)", name="Shop gauge")
    assert result["isError"] is True
    assert "model_create_component(sheet_metal=true)" in result["message"]
    assert design.designSheetMetalRules.count == 0


def test_update_refuses_library_rule(rule_design):
    result = mod.handler(action="update", rule="library:Steel (mm)", thickness="1.5 mm")
    assert result["isError"] is True
    assert "library rule" in result["message"]


@pytest.mark.parametrize("local", [None, _NamedCollection(items=[])])
def test_real_empty_rule_collection_path_names_initializer_before_copy(monkeypatch, local):
    design = SimpleNamespace(designSheetMetalRules=local)
    source = SimpleNamespace(name="Library source")
    _install_design(mod, design)
    monkeypatch.setattr(mod._RULE, "resolve", lambda raw: ((source, "library"), None))
    result = mod.handler(action="copy", rule="library:Library source", name="Unused copy")
    assert result["isError"] and "model_create_component(sheet_metal=true)" in result["message"]
    assert "no copy attempted" in result["message"]
    assert local is None or local.count == 0


def test_unread_slot_is_not_treated_as_an_empty_uninitialized_collection(monkeypatch):
    local = _NamedCollection(items=[None])
    writes = []
    local.addByCopy = lambda *args: writes.append(args)
    design = SimpleNamespace(designSheetMetalRules=local)
    _install_design(mod, design)
    monkeypatch.setattr(mod._RULE, "resolve", lambda raw: ((SimpleNamespace(name="Source"), "library"), None))
    result = mod.handler(action="copy", rule="library:Source", name="Copy")
    assert result["isError"] and "sheet_get" in result["message"]
    assert "model_create_component" not in result["message"] and writes == []


def test_unread_count_names_conditional_initializer_without_attempting_copy(monkeypatch):
    class UnreadCount(_NamedCollection):
        """A rule collection whose count raises before sheet-metal initialization."""

        @property
        def count(self):
            raise RuntimeError("2 : InternalValidationError : smDataRoot")

    local = UnreadCount(items=[])
    writes = []
    local.addByCopy = lambda *args: writes.append(args)
    _install_design(mod, SimpleNamespace(designSheetMetalRules=local))
    monkeypatch.setattr(mod._RULE, "resolve", lambda raw: ((SimpleNamespace(name="Source"), "library"), None))
    result = mod.handler(action="copy", rule="library:Source", name="Copy")
    assert result["isError"] and "If uninitialized" in result["message"]
    assert "model_create_component(sheet_metal=true)" in result["message"]
    assert "no copy attempted" in result["message"] and writes == []


def test_length_readback_checks_evaluated_centimeters(rule_design, monkeypatch):
    design, source = rule_design
    value = SimpleNamespace(expression="2 mm", value=0.2)
    source.thickness = value
    monkeypatch.setattr(mod._RULE, "resolve", lambda raw: ((source, "design"), None))
    result = mod.handler(action="update", rule="design:Steel (mm)", thickness="1.5 mm")
    assert result["isError"] is True
    assert "did not evaluate to" in result["message"]
    assert value.expression == "1.5 mm"


def test_literal_ordinal_collision_refuses_then_disclosed_refs_edit_only_each_intended_rule(monkeypatch):
    rules = [SimpleNamespace(name=name, kFactor=0.44, thickness=SimpleNamespace(expression=expr, value=cm))
             for name, expr, cm in [("Steel (mm)", "1.2 mm", .12),
                                   ("Steel (mm)", "2.50 mm", .25), ("Steel (mm)#1", "3 mm", .3)]]
    design = SimpleNamespace(designSheetMetalRules=_NamedCollection(items=rules))
    _install_design(mod, design)
    refs = [mod._sheet_common.rule_ref_and_index(design, r, "design")[0] for r in rules]
    assert refs == [{"scope": "design", "index": 0, "name": "Steel (mm)"}, "design:Steel (mm)#2",
                    {"scope": "design", "index": 2, "name": "Steel (mm)#1"}]
    for raw in ("design:Steel (mm)#1", "design:Steel (mm)"):
        result = mod.handler(action="update", rule=raw, thickness="4 mm")
        assert result["isError"] is True and "sheet_get" in result["message"]
        assert [r.thickness.expression for r in rules] == ["1.2 mm", "2.50 mm", "3 mm"]
    expected = [0.44] * 3
    for index, ref in enumerate(refs):
        expected[index] = .5 + index * .1
        result = mod.handler(action="update", rule=ref, k_factor=expected[index])
        assert result["isError"] is False, result
        assert [r.kFactor for r in rules] == expected


@pytest.mark.parametrize("raw", [{"scope": "design", "index": True}, {"scope": "design", "index": -1},
                                  {"scope": "design", "index": 0.5}, {"scope": "design", "index": 3},
                                  {"scope": "Design", "index": 0}, {"scope": "design", "index": 0, "extra": 1}])
def test_rule_index_ref_rejects_invalid_selectors_before_assignment(monkeypatch, raw):
    rule = SimpleNamespace(name="Steel (mm)", kFactor=.44)
    _install_design(mod, SimpleNamespace(designSheetMetalRules=_NamedCollection(items=[rule])))
    result = mod.handler(action="update", rule=raw, k_factor=.7)
    assert result["isError"] is True and "ref" in result["message"]
    assert rule.kFactor == .44


def test_unread_native_rule_slot_cannot_shift_a_disclosed_collision_index(monkeypatch):
    first = SimpleNamespace(name="Steel (mm)", kFactor=.44)
    literal = SimpleNamespace(name="Steel (mm)#1", kFactor=.44)
    design = SimpleNamespace(designSheetMetalRules=_NamedCollection(items=[first, None, literal]))
    _install_design(mod, design)
    assert mod._sheet_common.rule_ref_and_index(design, literal, "design") == (None, None)
    result = mod.handler(action="update", rule={"scope": "design", "index": 1, "name": "Steel (mm)#1"},
                         k_factor=.7)
    assert result["isError"] is True and "could not be read" in result["message"]
    assert first.kFactor == literal.kFactor == .44


def test_index_ref_whose_rule_name_changed_is_refused_and_edits_nothing(monkeypatch):
    # An earlier delete compacts the collection, so the ref's index now holds another rule.
    target = SimpleNamespace(name="FW2 Target", kFactor=.44)
    tail = SimpleNamespace(name="FW3 Tail", kFactor=.44)
    _install_design(mod, SimpleNamespace(designSheetMetalRules=_NamedCollection(items=[SimpleNamespace(name='Steel (mm)'), target, tail])))
    stale = mod.handler(action="update", rule={"scope": "design", "index": 2, "name": "FW2 Target"}, k_factor=.31)
    assert stale["isError"] is True
    assert "index 2 is now 'FW3 Tail', not 'FW2 Target'" in stale["message"]
    assert target.kFactor == tail.kFactor == .44
    fresh = mod.handler(action="update", rule={"scope": "design", "index": 2, "name": "fw3 tail"}, k_factor=.31)
    assert fresh["isError"] is False and tail.kFactor == .31 and target.kFactor == .44


@pytest.fixture
def relief_rule(monkeypatch):
    rule = SimpleNamespace(name="Shop", isUsed=False,
        twoBendReliefShape="two_bend_relief_shape:round",
        twoBendReliefPlacement="two_bend_relief_placement:intersection", kFactor=.44)
    for key, member in mod._FIELDS:
        setattr(rule, member, SimpleNamespace(expression="1 mm", value=.1))
    collection = _NamedCollection(items=[rule])
    rule.deleteMe = lambda: collection._items.remove(rule) is None
    design = SimpleNamespace(designSheetMetalRules=collection)
    _install_design(mod, design)
    monkeypatch.setattr(mod._sheet_common, "relief_enum", lambda field, label: field + ":" + label)
    return design, rule


@pytest.mark.parametrize("field,member", mod._FIELDS[3:])
def test_relief_expression_noop_is_not_success(relief_rule, field, member):
    design, rule = relief_rule
    reply = mod.handler(action="update", rule="design:Shop", **{field: "2 mm"})
    assert reply["isError"] and "did not evaluate to" in reply["message"]
    assert getattr(rule, member).expression == "2 mm"
    assert design.designSheetMetalRules.count == 1


def test_square_tangent_placement_refuses_before_any_rule_write(relief_rule):
    _, rule = relief_rule
    reply = mod.handler(action="update", rule="design:Shop", relief_width="2 mm",
                        two_bend_relief_shape="square", two_bend_relief_placement="tangent")
    assert reply["isError"] and "intersection/vertex" in reply["message"]
    assert rule.reliefWidth.expression == "1 mm"
    assert rule.twoBendReliefShape == "two_bend_relief_shape:round"


def test_round_and_square_valid_placements_read_back_as_named_choices(relief_rule):
    import json
    _, rule = relief_rule
    for shape, placement in (("round", "tangent"), ("square", "vertex"), ("square", "intersection")):
        reply = mod.handler(action="update", rule="design:Shop", two_bend_relief_shape=shape,
                            two_bend_relief_placement=placement, relief_shape="round",
                            three_bend_relief_shape="full_round")
        assert not reply["isError"], reply
        row = json.loads(reply["content"][0]["text"])
        assert row["after"]["two_bend_relief_shape"] == shape
        assert row["after"]["two_bend_relief_placement"] == placement
        assert row["after"]["relief_shape"] == "round"
        assert row["after"]["three_bend_relief_shape"] == "full_round"
        assert "geometry was not verified" in row["note"]


def test_used_and_noop_rule_delete_refuse_and_unused_delete_is_verified(relief_rule):
    design, rule = relief_rule
    rule.isUsed = True
    assert mod.handler(action="delete", rule="design:Shop")["isError"]
    rule.isUsed = False
    saved = rule.deleteMe
    rule.deleteMe = lambda: True
    assert mod.handler(action="delete", rule="design:Shop")["isError"]
    assert design.designSheetMetalRules.count == 1
    rule.deleteMe = saved
    assert not mod.handler(action="delete", rule="design:Shop")["isError"]
    assert design.designSheetMetalRules.count == 0


@pytest.mark.parametrize("reset", ["choice", "length", "k_factor"])
def test_later_relief_setter_cannot_undo_an_earlier_requested_value(relief_rule, monkeypatch, reset):
    _, rule = relief_rule

    def coupled_setter(target, member, value):
        setattr(target, member, value)
        if member == "threeBendReliefShape":
            if reset == "choice":
                target.reliefShape = "relief_shape:straight"
            elif reset == "length":
                target.reliefWidth.value = .2
            else:
                target.kFactor = .44

    monkeypatch.setattr(mod, "setattr", coupled_setter, raising=False)
    reply = mod.handler(action="update", rule="design:Shop", relief_width="1 mm", k_factor=.5,
                        relief_shape="round", three_bend_relief_shape="full_round")
    assert reply["isError"] and "final" in reply["message"] and "Read sheet_get" in reply["message"]


@pytest.mark.parametrize("initial_shape", ["square", "round"])
def test_square_shape_reset_cannot_lose_requested_vertex_placement(relief_rule, monkeypatch, initial_shape):
    import json
    _, rule = relief_rule
    rule.twoBendReliefShape = "two_bend_relief_shape:" + initial_shape
    writes = []

    def coupled_setter(target, member, value):
        setattr(target, member, value)
        writes.append(member)
        if member == "twoBendReliefShape":
            target.twoBendReliefPlacement = "two_bend_relief_placement:intersection"

    monkeypatch.setattr(mod, "setattr", coupled_setter, raising=False)
    reply = mod.handler(action="update", rule="design:Shop", two_bend_relief_shape="square",
                        two_bend_relief_placement="vertex")
    assert not reply["isError"], reply
    assert json.loads(reply["content"][0]["text"])["after"]["two_bend_relief_placement"] == "vertex"
    assert writes == (["twoBendReliefPlacement"] if initial_shape == "square" else
                      ["twoBendReliefPlacement", "twoBendReliefShape", "twoBendReliefPlacement"])


def test_shape_only_edit_preserves_prior_vertex_placement(relief_rule, monkeypatch):
    import json
    _, rule = relief_rule
    rule.twoBendReliefPlacement = "two_bend_relief_placement:vertex"

    def coupled_setter(target, member, value):
        setattr(target, member, value)
        if member == "twoBendReliefShape":
            target.twoBendReliefPlacement = "two_bend_relief_placement:intersection"

    monkeypatch.setattr(mod, "setattr", coupled_setter, raising=False)
    reply = mod.handler(action="update", rule="design:Shop", two_bend_relief_shape="square")
    assert not reply["isError"], reply
    row = json.loads(reply["content"][0]["text"])["after"]
    assert row["two_bend_relief_shape"] == "square" and row["two_bend_relief_placement"] == "vertex"


def test_unsupported_relief_choice_cannot_edit_a_length_first(relief_rule):
    _, rule = relief_rule
    reply = mod.handler(action="update", rule="design:Shop", relief_width="2 mm", relief_shape="unknown")
    assert reply["isError"] and rule.reliefWidth.expression == "1 mm"


def test_square_alone_on_tangent_refuses_before_touching_a_length(relief_rule):
    _, rule = relief_rule
    rule.twoBendReliefPlacement = "two_bend_relief_placement:tangent"
    reply = mod.handler(action="update", rule="design:Shop", relief_width="2 mm", two_bend_relief_shape="square")
    assert reply["isError"] and rule.reliefWidth.expression == "1 mm"


@pytest.mark.parametrize("start_shape,start_placement,shape,placement,first", [
    ("round", "tangent", "square", "intersection", "twoBendReliefPlacement"),
    ("square", "intersection", "round", "tangent", "twoBendReliefShape")])
def test_two_bend_transition_never_requests_an_invalid_intermediate_pair(
        relief_rule, monkeypatch, start_shape, start_placement, shape, placement, first):
    _, rule = relief_rule
    rule.twoBendReliefShape = "two_bend_relief_shape:" + start_shape
    rule.twoBendReliefPlacement = "two_bend_relief_placement:" + start_placement
    writes = []

    def set_shape(target, member, value):
        if member == "twoBendReliefShape" and value.endswith(":square"):
            assert target.twoBendReliefPlacement != "two_bend_relief_placement:tangent"
        if member == "twoBendReliefPlacement" and value.endswith(":tangent"):
            assert target.twoBendReliefShape != "two_bend_relief_shape:square"
        writes.append(member)
        setattr(target, member, value)

    monkeypatch.setattr(mod, "setattr", set_shape, raising=False)
    reply = mod.handler(action="update", rule="design:Shop", two_bend_relief_shape=shape,
                        two_bend_relief_placement=placement)
    assert not reply["isError"], reply
    assert writes[0] == first
