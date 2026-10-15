"""Focused conversion effect checks for a measured constant-thickness blank."""
from conftest import install as _install_design

import json
from types import SimpleNamespace

import pytest
from conftest import BRepBody, _NamedCollection, load_tool

mod = load_tool("sheet_convert")


def payload(result):
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


@pytest.fixture
def coupon(monkeypatch):
    active = SimpleNamespace(name="Shop gauge (Convert)", thickness=SimpleNamespace(value=0.15))
    root = SimpleNamespace(name="Root")
    design = SimpleNamespace(rootComponent=root)
    component = SimpleNamespace(name="Coupon", activeSheetMetalRule=None, parentDesign=design)
    body = BRepBody(name="Blank", volume=4.8, parent_component=component)
    body.isSheetMetal = False
    body.findThicknessAtFace = lambda face: (True, 0.15)
    def convert(face, rule):
        body.isSheetMetal = True
        component.activeSheetMetalRule = active
        design.designSheetMetalRules = _NamedCollection(items=[rule, active])
        return True
    body.convertToSheetMetal = convert
    face = SimpleNamespace(body=body)
    rule = SimpleNamespace(name="Shop gauge")
    _install_design(mod, design)
    monkeypatch.setattr(mod._BODY, "resolve", lambda raw: (body, None))
    monkeypatch.setattr(mod._FACE, "resolve", lambda raw: (face, None))
    monkeypatch.setattr(mod._RULE, "resolve", lambda raw: ((rule, "design"), None))
    monkeypatch.setattr(mod, "same_body", lambda a, b: a is b)
    monkeypatch.setattr(mod._sheet_common, "matching_rules",
                        lambda design, scope, name: [active] if name == active.name else [rule])
    return body, component


def test_success_reports_applied_rule_and_measured_thickness(coupon):
    body, component = coupon
    out = payload(mod.handler(body="Blank", base_face="face handle", rule="design:Shop gauge"))
    assert out["requested_rule"] == "design:Shop gauge"
    assert out["applied_rule"] == "Shop gauge (Convert)"
    assert out["applied_rule_ref"] == "design:Shop gauge (Convert)"
    assert out["requested_rule_still_present"] is True
    assert out["measured_blank_thickness_cm"] == 0.15
    assert out["applied_rule_thickness_cm"] == 0.15
    assert body.isSheetMetal is True
    assert "Use applied_rule_ref with sheet_edit_rule" in out["note"]
    assert "renamed or retained" not in out["note"]


def test_missing_applied_rule_ref_points_to_the_rule_read(coupon, monkeypatch):
    monkeypatch.setattr(mod._sheet_common, "rule_ref_and_index", lambda *_: (None, None))
    out = payload(mod.handler(body="Blank", base_face="face handle", rule="design:Shop gauge"))
    assert out["applied_rule_ref"] is None
    assert out["applied_rule"] == "Shop gauge (Convert)"
    assert "if absent, re-read sheet_get(include=['rules'])" in out["note"]


def test_false_conversion_does_not_report_success(coupon):
    body, component = coupon
    body.convertToSheetMetal = lambda face, rule: False
    result = mod.handler(body="Blank", base_face="face handle", rule="design:Shop gauge")
    assert result["isError"] is True
    assert "not verified" in result["message"]


def test_existing_component_rejects_different_rule_before_conversion(coupon):
    body, component = coupon
    component.activeSheetMetalRule = SimpleNamespace(name="Steel (mm)",
                                                       thickness=SimpleNamespace(value=0.25))
    result = mod.handler(body="Blank", base_face="face handle", rule="design:Shop gauge")
    assert result["isError"] is True
    assert "would be ignored" in result["message"]
    assert body.isSheetMetal is False


def test_active_rule_route_converts_under_the_component_rule_without_a_name_lookup(coupon, monkeypatch):
    body, component = coupon
    active = SimpleNamespace(name="Shop gauge (Convert)", thickness=SimpleNamespace(value=0.15))
    component.activeSheetMetalRule = active
    def no_lookup(raw):
        raise AssertionError("rule='active' must not resolve a design rule by name")
    monkeypatch.setattr(mod._RULE, "resolve", no_lookup)
    out = payload(mod.handler(body="Blank", base_face="face handle", rule="active"))
    assert out["requested_rule"] == "active"
    assert out["prior_active_rule"] == "Shop gauge (Convert)"
    assert out["applied_rule"] == "Shop gauge (Convert)"
    assert body.isSheetMetal is True


def test_active_rule_without_a_ruled_component_is_refused(coupon):
    body, component = coupon
    result = mod.handler(body="Blank", base_face="face handle", rule="active")
    assert result["isError"] is True
    assert "already carries a sheet-metal rule" in result["message"]
    assert body.isSheetMetal is False


def test_applied_rule_ref_carries_the_ordinal_when_the_name_repeats(monkeypatch):
    """Two design rules named alike, the applied one second: applied_rule_ref reads '...#2', not None."""
    design = SimpleNamespace()
    first = SimpleNamespace(name="Shop gauge (Convert)", parentDesign=design)
    active = SimpleNamespace(name="Shop gauge (Convert)", thickness=SimpleNamespace(value=0.15),
                             parentDesign=design)
    design.designSheetMetalRules = _NamedCollection(items=[first, active])
    design.rootComponent = SimpleNamespace(name="Root")
    component = SimpleNamespace(name="Coupon", activeSheetMetalRule=None, parentDesign=design)
    body = BRepBody(name="Blank", volume=4.8, parent_component=component)
    body.isSheetMetal = False
    body.findThicknessAtFace = lambda face: (True, 0.15)
    def convert(face, rule):
        body.isSheetMetal = True
        component.activeSheetMetalRule = active
        return True
    body.convertToSheetMetal = convert
    face = SimpleNamespace(body=body)
    rule = SimpleNamespace(name="Shop gauge")
    _install_design(mod, design)
    monkeypatch.setattr(mod._BODY, "resolve", lambda raw: (body, None))
    monkeypatch.setattr(mod._FACE, "resolve", lambda raw: (face, None))
    monkeypatch.setattr(mod._RULE, "resolve", lambda raw: ((rule, "design"), None))
    monkeypatch.setattr(mod, "same_body", lambda a, b: a is b)
    out = payload(mod.handler(body="Blank", base_face="face handle", rule="design:Shop gauge"))
    assert out["applied_rule_ref"] == "design:Shop gauge (Convert)#2"


def test_existing_matching_rule_with_wrong_thickness_is_refused(coupon):
    body, component = coupon
    component.activeSheetMetalRule = SimpleNamespace(name="Shop gauge",
                                                       thickness=SimpleNamespace(value=0.25))
    result = mod.handler(body="Blank", base_face="face handle", rule="design:Shop gauge")
    assert result["isError"] is True
    assert "could change that shared rule" in result["message"]
    assert body.isSheetMetal is False
