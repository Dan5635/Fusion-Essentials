from conftest import install as _install_design
from types import SimpleNamespace as NS
from unittest.mock import Mock
import json
import pytest
from conftest import load_tool


@pytest.fixture
def join(monkeypatch):
    mod = load_tool("sheet_create_join_by_bend")
    comp = NS(parentDesign=NS(rootComponent=object()))
    body_one = NS(name="SheetA", isSheetMetal=True, parentComponent=comp)
    body_two = NS(name="SheetB", isSheetMetal=True, parentComponent=comp)
    e1 = NS(body=body_one)
    e2 = NS(body=body_two)
    feature = NS(name="Join1", bendRadiusOverride=NS(isOverridden=False, bendRadius=None))
    inp = NS(bendRadiusOverride=NS(setOverride=Mock(return_value=True)))
    factory = NS(createInput=Mock(return_value=inp), add=Mock(return_value=feature))
    comp.features = NS(joinByBendFeatures=factory)
    survivor = NS(name="SheetA")
    comp.bRepBodies = NS(count=1, itemByName=Mock(return_value=survivor))

    def add(input_obj):
        comp.bRepBodies.count = 1
        return feature

    factory.add.side_effect = add
    monkeypatch.setattr(mod._EDGE_ONE, "resolve", lambda x: (e1, None))
    monkeypatch.setattr(mod._EDGE_TWO, "resolve", lambda x: (e2, None))
    monkeypatch.setattr(mod._common, "_native_of", lambda x: x)
    monkeypatch.setattr(mod._common, "same_component", lambda a, b: a is b)
    _install_design(mod, comp.parentDesign)
    monkeypatch.setattr(mod._common, "native_identity", lambda b: id(b))
    monkeypatch.setattr(mod._sheet_common, "sheet_edge_faces", lambda e: (object(), object(), None))
    bend_map = {id(body_one): 4, id(body_two): 0, id(survivor): 6}
    monkeypatch.setattr(mod._sheet_common, "bend_face_count", lambda b: bend_map.get(id(b)))
    monkeypatch.setattr(mod._geom, "signed_volume", lambda b: 10.0)
    comp.bRepBodies.count = 2
    return mod, comp, body_one, body_two, e1, e2, survivor, factory, feature, bend_map


def test_same_body_edges_are_refused(join):
    mod, comp, body_one, body_two, e1, e2, survivor, factory, feature, bend_map = join
    e2.body = body_one                        # both edges now name the same body
    result = mod.handler(edge_one="e1", edge_two="e2")
    assert result["isError"] is True
    assert "same body" in result["message"]
    factory.createInput.assert_not_called()


def test_different_components_are_refused(join):
    mod, comp, body_one, body_two, e1, e2, survivor, factory, feature, bend_map = join
    body_two.parentComponent = NS(rootComponent=object())    # a distinct component
    result = mod.handler(edge_one="e1", edge_two="e2")
    assert result["isError"] is True
    assert "same component" in result["message"]
    factory.createInput.assert_not_called()


def test_unmerged_bodies_is_not_success(join):
    mod, comp, body_one, body_two, e1, e2, survivor, factory, feature, bend_map = join
    factory.add.side_effect = lambda inp: feature     # count stays at 2 - no merge happened
    result = mod.handler(edge_one="e1", edge_two="e2")
    assert result["isError"] is True
    assert "verified" in result["message"]


def test_second_bodys_bends_count_toward_the_survivors_expected_bends(join):
    mod, comp, body_one, body_two, e1, e2, survivor, factory, feature, bend_map = join
    bend_map[id(body_two)] = 2                # plate B already carries one bend
    result = mod.handler(edge_one="e1", edge_two="e2")
    assert result["isError"] is True          # survivor still reads 6, not 4 + 2 + 2
    assert "bend faces 6 -> 6" in result["message"]
    bend_map[id(survivor)] = 8
    comp.bRepBodies.count = 2
    out = json.loads(mod.handler(edge_one="e1", edge_two="e2")["content"][0]["text"])
    assert out["bend_faces_before"] == 6 and out["bend_faces_after"] == 8


def test_explicit_radius_is_sent_with_its_unit_and_read_back(join, monkeypatch):
    mod, comp, body_one, body_two, e1, e2, survivor, factory, feature, bend_map = join
    sent = {}
    monkeypatch.setattr(mod.adsk.core.ValueInput, "createByString",
                        Mock(side_effect=lambda s: sent.setdefault("expr", s)))
    feature.bendRadiusOverride = NS(isOverridden=True, bendRadius=NS(value=0.05))  # 0.5 mm landed, not 5 mm
    result = mod.handler(edge_one="e1", edge_two="e2", bend_radius=5)
    assert result["isError"] is True
    assert "0.05 cm" in result["message"] and "0.5 cm" in result["message"]
    assert sent["expr"] == "5 mm"
    feature.bendRadiusOverride = NS(isOverridden=True, bendRadius=NS(value=0.5))
    comp.bRepBodies.count = 2
    out = json.loads(mod.handler(edge_one="e1", edge_two="e2", bend_radius=5)["content"][0]["text"])
    assert out["uses_rule_radius"] is False and out["bend_radius_mm"] == 5.0


def test_isOverridden_false_with_a_matching_radius_is_still_error(join):
    mod, comp, body_one, body_two, e1, e2, survivor, factory, feature, bend_map = join
    feature.bendRadiusOverride = NS(isOverridden=False, bendRadius=NS(value=0.5))  # value matches, but not applied
    result = mod.handler(edge_one="e1", edge_two="e2", bend_radius=5)
    assert result["isError"] is True
    assert "isOverridden=False" in result["message"]


def test_override_not_accepted_is_error(join):
    mod, comp, body_one, body_two, e1, e2, survivor, factory, feature, bend_map = join
    factory.createInput.return_value.bendRadiusOverride.setOverride = Mock(return_value=False)
    result = mod.handler(edge_one="e1", edge_two="e2", bend_radius=5)
    assert result["isError"] is True
    assert "not accepted" in result["message"]
    factory.add.assert_not_called()


def test_survivors_name_is_reported(join):
    mod, comp, body_one, body_two, e1, e2, survivor, factory, feature, bend_map = join
    result = mod.handler(edge_one="e1", edge_two="e2")
    assert result["isError"] is False
    out = json.loads(result["content"][0]["text"])
    assert out["body"] == "SheetA"
    assert out["bodies_before"] == 2 and out["bodies_after"] == 1
    assert out["uses_rule_radius"] is True
