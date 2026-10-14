# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Convert one constant-thickness solid to native sheet metal."""

import math

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common, _inputs, _sheet_common
from ._view_common import same_body

_BODY = _inputs.BodyRef("body", kind="solid", required=True)
_FACE = _inputs.GeometryHandle("base_face", require="planar_face", required=True)
_RULE = _inputs.SheetMetalRuleRef("rule", required=True)


def handler(body: str = "", base_face: str = "", rule: str = "") -> dict:
    """See TOOL_DESCRIPTION."""
    design, design_refusal = _common.require_design(none_only=True)
    if design_refusal is not None:
        return design_refusal
    target, berr = _BODY.resolve(body)
    if berr:
        return error(berr)
    face, ferr = _FACE.resolve(base_face)
    if ferr:
        return error(ferr)
    # A convert renames the design rule '<name> (Convert)' (and copies it when the thickness differs),
    # so a SECOND body in the ruled component is converted under rule='active', its own rule object.
    active_route = isinstance(rule, str) and rule.strip().lower() == "active"
    selected_rule = None
    if not active_route:
        selected, rerr = _RULE.resolve(rule)
        if rerr:
            return error(rerr)
        selected_rule, scope = selected
        if scope != "design":
            return error(f"rule '{rule}' is in the library. Copy it with sheet_edit_rule first.")
    owner = safe(lambda: face.body)
    if owner is None or not same_body(owner, target):
        return error(f"base_face '{base_face}' does not belong to body '{body}'. Re-find its broad face.")
    target, face = _common._native_of(target), _common._native_of(face)
    before_flag = safe(lambda: target.isSheetMetal)
    if before_flag is not False:
        return error(f"body '{body}' is not verified as an ordinary solid (isSheetMetal={before_flag}).")
    measured = safe(lambda: target.findThicknessAtFace(face))
    if not isinstance(measured, (tuple, list)) or len(measured) < 2 or measured[0] is not True:
        return error(f"body '{body}' has no verified thickness at base_face '{base_face}' (read {measured}).")
    thickness_cm = measured[1]
    if not isinstance(thickness_cm, (int, float)) or not math.isfinite(thickness_cm) or thickness_cm <= 0:
        return error(f"body '{body}' thickness at base_face '{base_face}' is invalid: {thickness_cm} cm.")
    component = safe(lambda: target.parentComponent)
    if component is None:
        return error(f"body '{body}' owning component could not be read.")
    source_root = safe(lambda: component.parentDesign.rootComponent)
    current_root = safe(lambda: design.rootComponent)
    if _common.same_component(source_root, current_root) is not True:
        return error(f"body '{body}' is not verified as local to the active design; "
                     "convert a body owned by this design.")
    prior_rule = safe(lambda: component.activeSheetMetalRule)
    prior_name = safe(lambda: prior_rule.name) if prior_rule is not None else None
    prior_thickness = safe(lambda: prior_rule.thickness.value) if prior_rule is not None else None
    if active_route:
        if prior_rule is None:
            return error(f"rule 'active' needs a component that already carries a sheet-metal rule; "
                         f"'{safe(lambda: component.name)}' has none. Name one as 'design:<name>'.")
        selected_rule = prior_rule
    source_name = safe(lambda: selected_rule.name)
    if not source_name:
        return error(f"rule '{rule}' name could not be read.")
    if prior_rule is not None and (prior_name is None or prior_name.lower() != source_name.lower()):
        return error(f"body '{body}' belongs to an already ruled sheet-metal component with "
                     f"active rule '{prior_name}'; requested rule '{source_name}' would be ignored. "
                     "Use that active design rule or a different ordinary component.")
    if prior_rule is not None and (not isinstance(prior_thickness, (int, float))
                                   or not math.isfinite(prior_thickness)
                                   or not math.isclose(prior_thickness, thickness_cm,
                                                        rel_tol=1e-6, abs_tol=1e-6)):
        return error(f"body '{body}' measures {thickness_cm} cm but existing active rule "
                     f"'{prior_name}' reads {prior_thickness} cm. Conversion could change that "
                     "shared rule; use an ordinary component and a design-local rule instead.")
    before_volume = safe(lambda: target.volume)
    try:
        converted = target.convertToSheetMetal(face, selected_rule)
    except Exception as exc:
        return error(f"Conversion of body '{body}' with rule '{rule}' failed: {exc}. "
                     "Read sheet_get(include=['components','rules']) before retrying.")
    after_flag = safe(lambda: target.isSheetMetal)
    active = safe(lambda: component.activeSheetMetalRule)
    actual_name = safe(lambda: active.name) if active is not None else None
    actual_thickness = safe(lambda: active.thickness.value) if active is not None else None
    if converted is not True or after_flag is not True or actual_name is None:
        return error(f"Conversion of body '{body}' was not verified: API={converted}, "
                     f"isSheetMetal={after_flag}, active_rule='{actual_name}'. Inspect sheet_get.")
    if (not isinstance(actual_thickness, (int, float)) or not math.isfinite(actual_thickness)
            or actual_thickness <= 0 or not math.isclose(actual_thickness, thickness_cm, rel_tol=1e-6, abs_tol=1e-6)):
        return error(f"body '{body}' isSheetMetal=True but its active rule thickness is "
                     f"{actual_thickness} cm; measured blank was {thickness_cm} cm. Inspect sheet_get.")
    applied_ref, _applied_index = _sheet_common.rule_ref_and_index(design, active, "design")
    source_hits = _sheet_common.matching_rules(design, "design", source_name)
    source_present = (None if source_hits is None else len(source_hits) > 0)
    return ok({"converted": True, "body": safe(lambda: target.name),
               "component": safe(lambda: component.name),
               "requested_rule": rule, "prior_active_rule": prior_name,
               "prior_rule_thickness_cm": prior_thickness, "applied_rule": actual_name,
               "applied_rule_ref": applied_ref,
               "requested_rule_still_present": source_present,
               "measured_blank_thickness_cm": thickness_cm,
               "applied_rule_thickness_cm": actual_thickness,
               "volume_cm3_before": before_volume, "volume_cm3_after": safe(lambda: target.volume),
               "note": "Body isSheetMetal; applied_rule names the active rule. Use applied_rule_ref with sheet_edit_rule; if absent, re-read sheet_get(include=['rules'])."})


TOOL_DESCRIPTION = "Convert a uniform solid using a design rule or rule='active'."

tool = (Tool.create_simple(name="sheet_convert", description=TOOL_DESCRIPTION)
        .add_input_property(*_BODY.as_property())
        .add_required_input("body")
        .add_input_property(*_FACE.as_property())
        .add_required_input("base_face")
        .add_input_property(*_RULE.as_property())
        .add_required_input("rule")
        .strict_schema())
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(kind="effect", rung="geometry",
                              evidence_test="tests/unit/test_sheet_convert.py::test_success_reports_applied_rule_and_measured_thickness"))


def register_tool():
    register(item)
