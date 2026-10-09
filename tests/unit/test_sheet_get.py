"""Focused rich-read routing checks for sheet_get."""

import json
from types import SimpleNamespace

import pytest
from conftest import load_tool
from tests.fakes.design import BRepBody, BRepFace
from tests.fakes.geometry import FakePoint, FakeVector3D, Plane, make_bbox
from tests.fakes.scaffold import _NamedCollection

mod = load_tool("sheet_get")


def payload(result):
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


@pytest.fixture
def sheet_design(monkeypatch):
    design = SimpleNamespace(designSheetMetalRules=SimpleNamespace(count=2),
                             librarySheetMetalRules=SimpleNamespace(count=6))
    monkeypatch.setattr(mod._common, "design", lambda: design)
    return design


def test_default_is_light_and_names_deeper_slices(sheet_design, monkeypatch):
    monkeypatch.setattr(mod, "_rules", lambda *args: pytest.fail("deep rules read on default"))
    out = payload(mod.handler())
    assert out["design_rule_count"] == 2
    assert out["library_rule_count"] == 6
    assert out["next"] == ["rules", "library_rules", "components", "features"]


def test_requested_rule_slice_does_not_repeat_default(sheet_design, monkeypatch):
    monkeypatch.setattr(mod, "_rules", lambda design, scope, cap: {"scope": scope, "cap": cap})
    out = payload(mod.handler(include=["rules"], max_results=3))
    assert out == {"rules": {"scope": "design", "cap": 3}}


@pytest.fixture
def unread_rule_count():
    class UnreadCount(_NamedCollection):
        @property
        def count(self):
            raise RuntimeError("2 : InternalValidationError : smDataRoot")
    return UnreadCount(items=[])


def test_unread_local_default_offers_conditional_initializer_without_deep_read(sheet_design, unread_rule_count, monkeypatch):
    monkeypatch.setattr(sheet_design, "designSheetMetalRules", unread_rule_count)
    monkeypatch.setattr(mod, "_rules", lambda *args: pytest.fail("deep rules read on default"))
    out = payload(mod.handler())
    assert out["design_rule_count"] is None and out["library_rule_count"] == 6
    assert "If uninitialized" in out["note"]
    assert "root sheet-metal component with model_create_component(sheet_metal=true)" in out["note"]


def test_unread_local_slice_offers_hint_but_unread_library_does_not(sheet_design, unread_rule_count, monkeypatch):
    monkeypatch.setattr(sheet_design, "designSheetMetalRules", unread_rule_count)
    monkeypatch.setattr(mod._sheet_common, "scoped_rules", lambda *_: None)
    out = payload(mod.handler(include=["rules", "library_rules"]))
    assert out["rules"]["readable"] is False and out["rules"]["rules"] is None
    assert "If uninitialized" in out["rules"]["note"]
    assert "model_create_component(sheet_metal=true)" in out["rules"]["note"]
    assert out["library_rules"] == {"readable": False, "rules": None}


def test_unread_slot_in_initialized_local_rules_does_not_suggest_initialization(sheet_design, monkeypatch):
    monkeypatch.setattr(sheet_design, "designSheetMetalRules", _NamedCollection([None]))
    out = payload(mod.handler(include=["rules"]))
    assert out["rules"] == {"readable": False, "rules": None}


def test_readable_local_rules_do_not_suggest_initialization(sheet_design, monkeypatch):
    monkeypatch.setattr(mod._sheet_common, "scoped_rules", lambda *_: [])
    out = payload(mod.handler(include=["default", "rules"]))
    assert out["rules"] == {"readable": True, "rules": [], "total": 0, "truncated": False}
    assert "note" not in out


def test_features_include_adds_exactly_that_slice(sheet_design, monkeypatch):
    monkeypatch.setattr(mod, "_features", lambda design, cap: {"cap": cap})
    out = payload(mod.handler(include=["features"], max_results=5))
    assert out == {"features": {"cap": 5}}
    assert "features" in mod.TOOL_DESCRIPTION


def test_hem_kind_strips_suffix_and_lowercases():
    hem = SimpleNamespace(definition=SimpleNamespace(objectType="adsk::fusion::FlatHemFeatureDefinition"))
    assert mod._hem_kind(hem) == "flat"


def test_feature_definition_cap_never_walks_past_the_bound_and_discloses_missing(monkeypatch):
    hem = SimpleNamespace(name="Hem", definition=SimpleNamespace(
        objectType="adsk::fusion::FlatHemFeatureDefinition"))
    reads = []

    def item(index):
        reads.append(index)
        return [hem, None][index]

    monkeypatch.setattr(mod._edit_feature_common, "feature_definition", lambda *_: {"available": True})
    out, state = mod._definition_rows(SimpleNamespace(count=100, item=item), 2, hem=True)
    assert reads == [0, 1] and len(out) == 1 and out[0]["kind"] == "flat"
    assert state == {"total": 100, "truncated": True, "unread_indices": [1]}
    out, state = mod._definition_rows(None, 2)
    assert out is None and state["total"] is None and state["truncated"] is None


@pytest.fixture
def flat_geometry(monkeypatch):
    plane = Plane(FakeVector3D(0, 0, 1), FakePoint(0, 0, -0.1))
    monkeypatch.setattr(plane, "objectType", "adsk::core::Plane", raising=False)
    sample, centroid = FakePoint(1, 1, -0.1), FakePoint(2, 1, -0.1)
    face = BRepFace(plane, area=17.279646, centroid=centroid, point_on_face=sample,
                   normal=FakeVector3D(0, 0, -1))
    calls = []
    monkeypatch.setattr(face.evaluator, "getNormalAtPoint",
                        lambda point: (calls.append(point) is None, FakeVector3D(0, 0, -1)))
    body = BRepBody(bbox=make_bbox((0, 0, -0.1), (8.639823, 2, 0)),
                    volume=1.7279646, faces=[face] * 35)
    comp = SimpleNamespace(flatPattern=SimpleNamespace(flatBody=body), features=None)
    monkeypatch.setattr(mod._sheet_common._assert, "compute_state", lambda flat: ("healthy", None))
    return comp, body, face, calls


@pytest.mark.parametrize("limit,expected", [(2, 2), (200, 32)])
def test_feature_geometry_is_bounded_and_normal_uses_actual_sample(flat_geometry, limit, expected):
    comp, body, face, calls = flat_geometry
    out = mod._feature_row(comp, min(32, limit))["flat_pattern"]["geometry"]
    assert out["face_count"] == 35 and out["returned"] == out["limit"] == expected
    assert out["truncated"] is True and out["partial"] is False
    assert out["bounds_cm"]["max"]["x"] == 8.639823
    assert out["faces"][0]["area_cm2"] == 17.279646
    assert out["faces"][0]["normal_at_sample"] == [0, 0, -1]
    assert out["faces"][0]["plane"]["normal"] == {"x": 0, "y": 0, "z": 1}
    assert out["faces"][0]["sample_point_cm"] != out["faces"][0]["centroid_cm"]
    assert calls == [face.pointOnFace] * expected
    assert out["development"] == "unverified" and "not folded-body world" in out["frame"]
    assert "geometry" not in mod._sheet_common.flat_pattern_row(comp)


@pytest.mark.parametrize("plane_normal,opposite", [((0, 0, 1), True), ((0, 0, -1), False),
                                                   ((1, 0, 0), False)])
def test_each_normal_is_labelled_and_a_sign_disagreement_is_said(flat_geometry, monkeypatch,
                                                                  plane_normal, opposite):
    comp, body, face, calls = flat_geometry
    monkeypatch.setattr(face.geometry, "normal", FakeVector3D(*plane_normal))
    out = mod._feature_row(comp, 1)["flat_pattern"]["geometry"]
    assert "evaluator's outward normal" in out["normals"]
    assert "supporting surface's parametric normal" in out["normals"]
    row = out["faces"][0]
    assert row["normal_at_sample"] == [0, 0, -1]
    assert ("note" in row["plane"]) is opposite
    if opposite:
        assert row["plane"]["note"] == "plane.normal points opposite normal_at_sample on this face."
    assert row["unread"] == []


def test_unread_flat_face_and_number_are_partial_not_zero(flat_geometry, monkeypatch):
    comp, body, face, calls = flat_geometry
    monkeypatch.setattr(body, "faces", _NamedCollection([face, None]))
    monkeypatch.setattr(face, "area", float("nan"))
    out = mod._feature_row(comp, 32)["flat_pattern"]["geometry"]
    assert out["face_count"] == 2 and out["returned"] == 1
    assert out["truncated"] is False and out["partial"] is True
    assert out["unread_face_indices"] == [1]
    assert out["faces"][0]["area_cm2"] is None and "area_cm2" in out["faces"][0]["unread"]
    monkeypatch.setattr(body, "faces", _NamedCollection([], raises=True))
    out = mod._feature_row(comp, 32)["flat_pattern"]["geometry"]
    assert out["face_count"] is None and out["truncated"] is None and out["partial"] is True
    assert out["returned"] == 0
