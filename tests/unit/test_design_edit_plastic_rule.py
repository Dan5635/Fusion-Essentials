"""Plastic-rule identity, bounded edits and truthful partial-effect checks."""
from conftest import install as _install_design

import json
from types import SimpleNamespace

import pytest
from conftest import load_tool
from tests.fakes.scaffold import _NamedCollection, entity_proxy

mod = load_tool("design_edit_plastic_rule")


@pytest.fixture
def rules(monkeypatch):
    library = SimpleNamespace(name="ABS (1.5mm)", minimumThickness=.1, maximumThickness=.4,
                              minimumDraftAngle=.01, isUsed=False)
    local = _NamedCollection(items=[])
    design = SimpleNamespace(designPlasticRules=local,
                             libraryPlasticRules=_NamedCollection(items=[library]))

    def copy(source, name):
        result = SimpleNamespace(name=name, minimumThickness=source.minimumThickness,
                                 maximumThickness=source.maximumThickness,
                                 minimumDraftAngle=source.minimumDraftAngle, isUsed=False)
        result.deleteMe = lambda: local._items.remove(result) is None
        local._items.append(result)
        return result

    local.addByCopy = copy
    _install_design(mod, design)
    return design, library


def payload(reply):
    return json.loads(reply["content"][0]["text"])


def copied(rules):
    reply = mod.handler(action="copy", rule="library:ABS (1.5mm)", name="Shop ABS")
    assert not reply["isError"], reply
    return rules[0].designPlasticRules._items[0]


def test_copy_edits_only_the_new_rule_and_returns_fresh_refs(rules):
    design, source = rules
    result = mod.handler(action="copy", rule="library:ABS (1.5mm)", name="Shop ABS",
                         minimum_thickness=1.2, maximum_thickness=4.5, minimum_draft_deg=.5)
    assert not result["isError"], result
    row = payload(result)
    assert row["before"]["ref"] == {"scope": "library", "index": 0, "name": source.name}
    assert row["rule"]["ref"] == {"scope": "design", "index": 0, "name": "Shop ABS"}
    assert row["rule"]["minimum_thickness"] == pytest.approx(1.2)
    assert row["rule"]["minimum_draft_angle_deg"] == pytest.approx(.5)
    assert (source.minimumThickness, source.maximumThickness, source.minimumDraftAngle) == (.1, .4, .01)
    assert design.designPlasticRules.count == 1


def test_stale_or_ambiguous_rule_cannot_edit_another_rule(rules):
    design, _ = rules
    first = copied(rules)
    second = SimpleNamespace(**vars(first))
    second.name = "shop abs"
    design.designPlasticRules._items.append(second)
    ambiguous = mod.handler(action="update", rule="design:SHOP ABS", minimum_thickness=1.4)
    stale = mod.handler(action="update", rule={"scope": "design", "index": 1, "name": "Old name"},
                        minimum_thickness=1.4)
    assert ambiguous["isError"] and stale["isError"]
    assert first.minimumThickness == second.minimumThickness == .1
    fresh = mod.handler(action="update", rule={"scope": "design", "index": 1, "name": "shop abs"},
                        minimum_thickness=1.4)
    assert not fresh["isError"] and second.minimumThickness == pytest.approx(.14)
    assert first.minimumThickness == .1


def test_noop_setter_is_a_failure(rules, monkeypatch):
    target = copied(rules)
    monkeypatch.setattr(mod, "setattr", lambda obj, field, value: None, raising=False)
    result = mod.handler(action="update", rule="design:Shop ABS", minimum_thickness=1.4)
    assert result["isError"] and "did not read back" in result["message"]
    assert "partial edits are retained" in result["message"]
    assert target.minimumThickness == .1


@pytest.mark.parametrize("fields", [{"minimum_thickness": 5}, {"maximum_thickness": .5},
                                     {"minimum_thickness": float("inf")},
                                     {"minimum_draft_deg": float("nan")},
                                     {"minimum_thickness": True}])
def test_invalid_range_or_nonfinite_input_cannot_create_a_rule(rules, fields):
    result = mod.handler(action="copy", rule="library:ABS (1.5mm)", name="Shop ABS", **fields)
    assert result["isError"]
    assert rules[0].designPlasticRules.count == 0


def test_library_edit_and_duplicate_copy_are_refused(rules):
    copied(rules)
    edit = mod.handler(action="update", rule="library:ABS (1.5mm)", minimum_thickness=1.4)
    duplicate = mod.handler(action="copy", rule="library:ABS (1.5mm)", name="SHOP ABS")
    assert edit["isError"] and duplicate["isError"]
    assert rules[0].designPlasticRules.count == 1


def test_delete_requires_unused_rule_and_confirmed_removal(rules):
    target = copied(rules)
    target.isUsed = True
    refused = mod.handler(action="delete", rule="design:Shop ABS")
    assert refused["isError"] and rules[0].designPlasticRules.count == 1
    target.isUsed = False
    target.deleteMe = lambda: True
    noop = mod.handler(action="delete", rule="design:Shop ABS")
    assert noop["isError"] and rules[0].designPlasticRules.count == 1
    target.deleteMe = lambda: rules[0].designPlasticRules._items.remove(target) is None
    removed = mod.handler(action="delete", rule="design:Shop ABS")
    assert not removed["isError"] and payload(removed)["deleted"] is True
    assert rules[0].designPlasticRules.count == 0


def test_range_expansion_and_rename_return_the_current_reference(rules):
    target = copied(rules)
    result = mod.handler(action="update", rule="design:Shop ABS", name="Wide ABS",
                         minimum_thickness=5, maximum_thickness=6)
    assert not result["isError"], result
    assert payload(result)["applied"] == ["name", "maximum_thickness", "minimum_thickness"]
    assert payload(result)["rule"]["ref"]["name"] == "Wide ABS"
    assert target.minimumThickness == .5 and target.maximumThickness == pytest.approx(.6)


def test_unread_collection_slot_refuses_before_copy(rules):
    rules[0].designPlasticRules._items.append(None)
    result = mod.handler(action="copy", rule="library:ABS (1.5mm)", name="Shop ABS")
    assert result["isError"]
    assert rules[0].designPlasticRules.count == 1


def test_fresh_wrappers_do_not_need_equality_to_copy_read_update_or_delete(rules, monkeypatch):
    design, _ = rules
    for collection in (design.designPlasticRules, design.libraryPlasticRules):
        monkeypatch.setattr(collection, "item", lambda index, collection=collection:
                            entity_proxy(collection._items[index]))
    target = copied(rules)
    assert not mod.handler(action="update", rule="design:Shop ABS", minimum_thickness=1.4)["isError"]
    assert target.minimumThickness == pytest.approx(.14)
    assert not mod.handler(action="delete", rule="design:Shop ABS")["isError"]
    assert design.designPlasticRules.count == 0
