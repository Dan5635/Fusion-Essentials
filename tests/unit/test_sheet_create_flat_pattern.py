from conftest import install as _install_design
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from conftest import load_tool


@pytest.fixture
def flat(monkeypatch):
    mod = load_tool("sheet_create_flat_pattern")
    body = NS(name="Sheet", isSheetMetal=True)
    flat = NS(foldedBody=body, flatBody=NS(volume=4.8, isSolid=True))
    comp = NS(name="Part", flatPattern=None, parentDesign=NS(rootComponent=object()))
    body.parentComponent = comp
    def create(face):
        comp.flatPattern = flat
        return flat
    comp.createFlatPattern = Mock(side_effect=create)
    monkeypatch.setattr(mod._FACE, "resolve", lambda x: (NS(body=body), None))
    monkeypatch.setattr(mod._common, "_native_of", lambda x: x)
    monkeypatch.setattr(mod._common, "same_component", lambda a, b: True)
    monkeypatch.setattr(mod._common, "native_identity", lambda x: id(x) if x else None)
    _install_design(mod, comp.parentDesign)
    return mod, comp, flat


def test_wrong_source_is_not_success(flat):
    mod, comp, pattern = flat
    pattern.foldedBody = object()
    result = mod.handler("face")
    assert result["isError"] is True
    assert "association" in str(result)


def test_existing_pattern_is_never_recreated(flat):
    mod, comp, pattern = flat
    comp.flatPattern = pattern
    result = mod.handler("face")
    assert result["isError"] is True
    assert "already has a flat pattern" in str(result)
    assert "unverified" in str(result) and "sheet_get" in str(result)
    comp.createFlatPattern.assert_not_called()


def test_empty_flat_is_not_success(flat):
    mod, comp, pattern = flat
    pattern.flatBody.volume = 0
    result = mod.handler("face")
    assert result["isError"] is True
    assert "nonempty solid" in str(result)


def test_native_creation_does_not_certify_development(flat):
    mod, comp, pattern = flat
    result = mod.handler("face")
    assert result["isError"] is False
    out = json.loads(result["content"][0]["text"])
    assert out["created"] is True and out["flat_volume_cm3"] == 4.8
    assert out["development"] == "unverified"
    assert "sheet_get(include=['features'])" in out["note"]
