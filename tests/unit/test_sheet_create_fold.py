from types import SimpleNamespace as NS
from unittest.mock import Mock
import math
import pytest
from conftest import load_tool


@pytest.fixture
def fold(monkeypatch):
    mod = load_tool("sheet_create_fold")
    body = NS(name="Sheet", isSheetMetal=True, faces=NS(count=6))
    comp = NS(parentDesign=NS(rootComponent=object()))
    body.parentComponent = comp
    face = NS(body=body)
    line = NS(parentSketch=NS(parentComponent=comp))
    feature = NS(name="Fold1", bendLines=NS(item=lambda i: NS(bendAngle=NS(value=math.pi / 2))))
    factory = NS(createInput=Mock(return_value=NS(bendLines=NS(add=Mock(return_value=object())))),
                 add=Mock(return_value=feature))
    comp.features = NS(foldFeatures=factory)
    monkeypatch.setattr(mod._FACE, "resolve", lambda x: (face, None))
    monkeypatch.setattr(mod._LINE, "resolve", lambda x, c: (line, None))
    monkeypatch.setattr(mod._common, "_native_of", lambda x: x)
    monkeypatch.setattr(mod._common, "same_component", lambda a, b: True)
    monkeypatch.setattr(mod._common, "design", lambda: comp.parentDesign)
    return mod, body, factory, feature


def test_unchanged_body_is_not_success(fold):
    mod, body, factory, feature = fold
    result = mod.handler(stationary_face="face", bend_line="Bend/line:4")
    assert result["isError"] is True
    assert "topology" in str(result)


def test_landed_angle_must_match_requested(fold):
    mod, body, factory, feature = fold
    feature.bendLines = NS(item=lambda i: NS(bendAngle=NS(value=math.pi / 3)))
    def add(inp):
        body.faces.count = 14
        return feature
    factory.add.side_effect = add
    result = mod.handler(stationary_face="face", bend_line="Bend/line:4")
    assert result["isError"] is True
    assert "angle" in str(result)


def test_success_discloses_that_interior_endpoints_do_not_bound_the_fold(fold):
    mod, body, factory, feature = fold
    def add(inp):
        body.faces.count = 14
        return feature
    factory.add.side_effect = add
    result = mod.handler(stationary_face="face", bend_line="Bend/line:4")
    assert result["isError"] is False
    assert "beyond its endpoints" in str(result)


@pytest.mark.parametrize("angle", [0, 180, -180, float("nan"), float("inf"), True])
def test_invalid_angle_does_not_mutate(fold, angle):
    mod, body, factory, feature = fold
    assert mod.handler(angle_deg=angle)["isError"] is True
    factory.add.assert_not_called()
