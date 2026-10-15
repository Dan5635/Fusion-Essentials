from conftest import install as _install_design
from types import SimpleNamespace as NS
from unittest.mock import Mock
import json
import pytest
from conftest import load_tool


class _FakeBodies:
    """A bRepBodies fake: count/item(i)/itemByName(name) over a live-shared list."""
    def __init__(self, items):
        self.items = items

    @property
    def count(self):
        return len(self.items)

    def item(self, i):
        return self.items[i]

    def itemByName(self, name):
        return next((b for b in self.items if b.name == name), None)


@pytest.fixture
def rip(monkeypatch):
    mod = load_tool("sheet_create_rip")
    comp = NS(parentDesign=NS(rootComponent=object()))
    body = NS(name="Sheet1", isSheetMetal=True, isSolid=True, faces=NS(count=6),
              parentComponent=comp, token="tok1")
    face = NS(body=body)
    edge = NS(body=body)
    vertex_one = NS(body=body)
    vertex_two = NS(body=body)
    feature = NS(name="Rip1")
    inp = NS(setByFace=Mock(return_value=True), setAlongEdge=Mock(return_value=True),
             setBetweenPoints=Mock(return_value=True))
    factory = NS(createRipFeatureInput=Mock(return_value=inp), add=Mock(return_value=feature))
    comp.features = NS(ripFeatures=factory)
    body_after = NS(name="Sheet1", isSolid=True, faces=NS(count=7), token="tok1")
    fake_bodies = _FakeBodies([body])
    comp.bRepBodies = fake_bodies

    def _add_replaces_body(inp):
        fake_bodies.items = [body_after]
        return feature
    factory.add.side_effect = _add_replaces_body

    comp.activeSheetMetalRule = NS(gap=NS(value=0.05))
    vol_map = {id(body): 10.0, id(body_after): 9.5}
    monkeypatch.setattr(mod._FACE, "resolve", lambda x: (face, None))
    monkeypatch.setattr(mod._EDGE, "resolve", lambda x: (edge, None))
    monkeypatch.setattr(mod._POINT_ONE, "resolve", lambda x: (vertex_one, None))
    monkeypatch.setattr(mod._POINT_TWO, "resolve", lambda x: (vertex_two, None))
    monkeypatch.setattr(mod._common, "_native_of", lambda x: x)
    monkeypatch.setattr(mod._common, "same_component", lambda a, b: True)
    _install_design(mod, comp.parentDesign)
    monkeypatch.setattr(mod._common, "native_identity", lambda b: getattr(b, "token", None))
    monkeypatch.setattr(mod._sheet_common, "bend_face_count", lambda b: 2)
    monkeypatch.setattr(mod._geom, "signed_volume", lambda b: vol_map.get(id(b)))
    return mod, body, body_after, inp, factory, feature, vol_map, fake_bodies


def test_face_mode_rejects_an_extra_edge_selector(rip):
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    result = mod.handler(mode="face", face="f", edge="e")
    assert result["isError"] is True
    assert "drop edge" in result["message"]
    factory.createRipFeatureInput.assert_not_called()


def test_along_edge_mode_missing_edge_is_refused(rip):
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    result = mod.handler(mode="along_edge")
    assert result["isError"] is True
    assert "edge" in result["message"] and "missing" in result["message"]
    factory.createRipFeatureInput.assert_not_called()


def test_between_points_mode_missing_point_two_is_refused(rip):
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    result = mod.handler(mode="between_points", point_one="p1")
    assert result["isError"] is True
    assert "point_two" in result["message"] and "missing" in result["message"]
    factory.createRipFeatureInput.assert_not_called()


def test_face_mode_with_an_explicit_gap_is_refused_before_the_rip(rip):
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    result = mod.handler(mode="face", face="f", gap=1.0)
    assert result["isError"] is True
    assert "gap=1.0" in result["message"] and "mode='along_edge'" in result["message"]
    factory.createRipFeatureInput.assert_not_called()


def test_face_mode_publishes_no_gap_and_reads_no_rule_gap(rip):
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    body.parentComponent.activeSheetMetalRule = None
    result = mod.handler(mode="face", face="f")
    assert result["isError"] is False, result
    out = json.loads(result["content"][0]["text"])
    assert "gap_mm" not in out and "gap_source" not in out
    assert out["volume_removed_cm3"] == 0.5


def test_gap_falls_back_to_the_rule_and_says_so(rip):
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    result = mod.handler(mode="along_edge", edge="e")
    assert result["isError"] is False
    out = json.loads(result["content"][0]["text"])
    assert out["gap_source"] == "rule"
    assert out["gap_mm"] == 0.5


def test_unchanged_volume_is_not_success(rip):
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    vol_map[id(body_after)] = 10.0            # no decrease from volume_before, no total delta
    result = mod.handler(mode="along_edge", edge="e")
    assert result["isError"] is True
    assert "10.0 cm3 before" in result["message"] and "10.0 cm3 after" in result["message"]


def test_the_raise_compute_text_reaches_the_error(rip):
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    factory.add.side_effect = RuntimeError(
        "RIP_NOT_TANGENT_CONTINUOUS - The input edge for rip is not tangent continuous "
        "Compute Failed: rip1 (RipFeature)")
    result = mod.handler(mode="along_edge", edge="e")
    assert result["isError"] is True
    assert result["message"] == ("Rip failed: RIP_NOT_TANGENT_CONTINUOUS - The input edge for rip "
                                 "is not tangent continuous")


def test_rip_that_splits_reports_the_new_body_and_the_total_delta(rip):
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    body_two = NS(name="Body2", isSolid=True, token="tok2")
    vol_map[id(body)] = 4.843
    vol_map[id(body_after)] = 3.606
    vol_map[id(body_two)] = 1.199

    def _split(inp):
        fake_bodies.items = [body_after, body_two]
        return feature
    factory.add.side_effect = _split

    result = mod.handler(mode="along_edge", edge="e")
    assert result["isError"] is False, result
    out = json.loads(result["content"][0]["text"])
    assert out["new_bodies"] == ["Body2"]
    assert out["total_volume_before_cm3"] == 4.843
    assert out["total_volume_after_cm3"] == pytest.approx(4.805)
    assert out["volume_removed_cm3"] == pytest.approx(0.038, abs=1e-3)
    assert "left 2 bodies in the component" in out["note"]


def test_face_mode_with_unchanged_body_count_reports_no_new_bodies(rip):
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    result = mod.handler(mode="face", face="f")
    assert result["isError"] is False, result
    out = json.loads(result["content"][0]["text"])
    assert out["new_bodies"] == []


def test_split_with_an_unreadable_new_body_name_does_not_raise(rip):
    # Two NEW bodies (neither token was in the before-census) so the sort must compare a None
    # name against a str name - a single new body never exercises that comparison.
    mod, body, body_after, inp, factory, feature, vol_map, fake_bodies = rip
    body_two = NS(name=None, isSolid=True, token="tok2")
    body_three = NS(name="Body3", isSolid=True, token="tok3")
    vol_map[id(body)] = 4.843
    vol_map[id(body_after)] = 3.606
    vol_map[id(body_two)] = 1.0
    vol_map[id(body_three)] = 0.199

    def _split(inp):
        fake_bodies.items = [body_after, body_two, body_three]
        return feature
    factory.add.side_effect = _split

    result = mod.handler(mode="along_edge", edge="e")
    assert result["isError"] is False, result
    out = json.loads(result["content"][0]["text"])
    assert out["new_bodies"] == [None, "Body3"]
    assert "unnamed" in out["note"]
