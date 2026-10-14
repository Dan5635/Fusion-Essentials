"""Rib/Web owner, extent and material-effect refusal checks."""
from conftest import install as _install_design

import json
from types import SimpleNamespace

import adsk.fusion
import pytest
from conftest import load_tool

mod = load_tool("model_create_rib")


@pytest.fixture
def rib(monkeypatch):
    root = SimpleNamespace(entityToken="root", nativeObject=None)
    host = SimpleNamespace(entityToken="host", nativeObject=None)
    design = SimpleNamespace(rootComponent=root)
    host.parentDesign = root.parentDesign = design
    body = SimpleNamespace(name="Target", entityToken="body", nativeObject=None, parentComponent=host)
    curve = SimpleNamespace(entityToken="curve", nativeObject=None,
                            parentSketch=SimpleNamespace(parentComponent=host))
    feature = SimpleNamespace(name="Rib1", healthState=adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,
                              errorOrWarningMessage="", thickness=SimpleNamespace(value=.2),
                              depth=SimpleNamespace(value=.6), parentComponent=host)
    before = {("body", None): {"volume_cm3": 2.88}, ("control", None): {"volume_cm3": 1}}
    after = {("body", None): {"volume_cm3": 3.049}, ("control", None): {"volume_cm3": 1}}
    state = SimpleNamespace(input=None, added=0, extent_calls=[], accepted=True, material=True,
                            before=before, after=after)

    def create_input(guides, thickness, target):
        state.input = SimpleNamespace(curves=guides, thickness=thickness, targetBody=target)
        state.input.setToNextExtent = lambda: state.extent_calls.append("next") is None and state.accepted
        state.input.setDistanceExtent = lambda value: state.extent_calls.append("distance") is None and state.accepted
        return state.input

    def add(inp):
        state.added += 1
        return feature

    coll = SimpleNamespace(createInput=create_input, add=add)
    host.features = SimpleNamespace(ribFeatures=coll, webFeatures=coll)
    _install_design(mod, design)
    monkeypatch.setattr(mod._BODY, "resolve", lambda raw, scope=None: (body, None))
    monkeypatch.setattr(mod._CURVES, "resolve", lambda raw: ([curve] if raw else [], None))
    monkeypatch.setattr(mod._rib_common, "body_census", lambda comp:
                        state.after if state.added and state.material else state.before)
    return state, host, body, curve, feature


def test_returned_feature_without_material_gain_is_error(rib):
    state, *_ = rib
    state.material = False
    result = mod.handler(kind="rib", curves=["curve"], target_body="body", thickness=2)
    assert result["isError"] and "did not verify healthy added material" in result["message"]
    assert state.added == 1 and "design_delete_feature" in result["message"]


@pytest.mark.parametrize("kind,depth,extent", [("rib", None, "next"), ("rib", 6, "distance"),
                                             ("web", None, "next"), ("web", 6, "distance")])
def test_effective_feature_uses_explicit_body_extent_and_options(rib, kind, depth, extent):
    state, _, body, curve, _ = rib
    result = mod.handler(kind=kind, curves=["curve"], target_body="body", thickness=2,
                         depth=depth, flip=True, symmetric=False, extend=kind == "web")
    assert not result["isError"], result
    out = json.loads(result["content"][0]["text"])
    assert out["geometry_before"]["volume_cm3"] == 2.88
    assert out["geometry_after"]["volume_cm3"] == 3.049
    assert state.input.targetBody is body and state.input.curves == [curve]
    assert state.input.isSymmetric is False and state.input.isFlipped is True
    assert state.extent_calls == [extent]
    if kind == "web":
        assert state.input.isExtended is True


def test_foreign_guide_refuses_before_starting_the_feature(rib):
    state, _, _, curve, _ = rib
    curve.parentSketch.parentComponent = SimpleNamespace(entityToken="other", nativeObject=None)
    result = mod.handler(kind="rib", curves=["curve"], target_body="body", thickness=2)
    assert result["isError"] and "must belong" in result["message"]
    assert state.input is None and state.added == 0


@pytest.mark.parametrize("readback", ["iterable", "other_curve", "unread"])
def test_input_curve_iterable_preserves_identity_before_add(rib, monkeypatch, readback):
    state, host, _, curve, _ = rib
    create_input = host.features.ribFeatures.createInput

    def unread():
        raise RuntimeError("curve getter failed")
        yield

    def with_readback(*args):
        inp = create_input(*args)
        other = SimpleNamespace(entityToken="other", nativeObject=None)
        inp.curves = unread() if readback == "unread" else iter([curve if readback == "iterable" else other])
        return inp

    monkeypatch.setattr(host.features.ribFeatures, "createInput", with_readback)
    result = mod.handler(kind="rib", curves=["curve"], target_body="body", thickness=2)
    assert result["isError"] is (readback != "iterable"), result
    assert state.added == (1 if readback == "iterable" else 0)


def test_passive_definition_reads_iterable_curves(rib):
    _, _, _, curve, feature = rib
    feature.curves = iter([curve])
    row = mod._rib_common.rib_definition(feature, 10)
    assert row["curve_count"] == 1 and len(row["curves"]) == 1
    assert row["curves_truncated"] is False and "curves" not in row["unavailable"]


def test_extent_false_does_not_add_a_feature(rib):
    state, *_ = rib
    state.accepted = False
    result = mod.handler(kind="rib", curves=["curve"], target_body="body", thickness=2)
    assert result["isError"] and state.added == 0


def test_sibling_change_or_warning_cannot_answer_success(rib):
    state, _, _, _, feature = rib
    state.after[("control", None)]["volume_cm3"] = 2
    result = mod.handler(kind="web", curves=["curve"], target_body="body", thickness=2)
    assert result["isError"] and "in only target_body" in result["message"]
    state.after[("control", None)]["volume_cm3"] = 1
    feature.healthState = adsk.fusion.FeatureHealthStates.WarningFeatureHealthState
    result = mod.handler(kind="rib", curves=["curve"], target_body="body", thickness=2)
    assert result["isError"] and "Health:" in result["message"]


@pytest.mark.parametrize("fields", [{"thickness": 0}, {"thickness": float("nan")},
                                     {"thickness": 2, "depth": -1}, {"thickness": 2, "extend": True}])
def test_invalid_rib_payload_cannot_start_creation(rib, fields):
    state, *_ = rib
    result = mod.handler(kind="rib", curves=["curve"], target_body="body", **fields)
    assert result["isError"] and state.input is None


def test_definition_units_and_operand_refusal_are_passive(rib):
    _, _, _, curve, feature = rib
    feature.objectType = "adsk::fusion::RibFeature"
    feature.thickness = SimpleNamespace(value=.2, expression="2 mm")
    feature.depth = None
    feature.extentType = 0
    feature.isSymmetric, feature.isFlipped = True, False
    row = mod._rib_common.rib_definition(feature, 10)
    assert row["thickness"] == 2 and row["depth"] is None
    assert row["curves"] is None and "curves" in row["unavailable"]
    assert "to='before'" in row["note"] and not hasattr(feature, "curves")
