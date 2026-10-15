# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Create a sheet-metal fold along one sketch line."""

import math
import adsk.core
import adsk.fusion
from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _inputs, _assert
from ._common import error, ok, safe

_FACE = _inputs.GeometryHandle("stationary_face", require="planar_face", required=True)
_LINE = _inputs.SketchLineRef("bend_line", scope_input="component", required=True)
_POSITION = _inputs.Choice("position", ["start", "center", "end"], default="center")
_POSITIONS = {"start": "StartFoldBendLinePositionType", "center": "CenterFoldBendLinePositionType",
              "end": "EndFoldBendLinePositionType"}


def handler(stationary_face="", bend_line="", angle_deg=90.0, position="center",
            allow_relief=True, component=""):
    """Fold the selected sheet body and report the landed angle and changed topology."""
    if isinstance(angle_deg, bool) or not isinstance(angle_deg, (int, float)) or not math.isfinite(angle_deg) or not 0 < abs(angle_deg) < 180:
        return error(f"angle_deg={angle_deg!r} must be finite, nonzero and between -180 and 180.")
    pos, why = _POSITION.resolve(position)
    if why:
        return error(why)
    face, why = _FACE.resolve(stationary_face)
    if why:
        return error(why)
    line, why = _LINE.resolve(bend_line, component)
    if why:
        return error(why)
    face, line = _common._native_of(face), _common._native_of(line)
    body = face.body
    comp = body.parentComponent
    if _common.same_component(comp, line.parentSketch.parentComponent) is not True:
        return error("bend_line and stationary_face must belong to the same local component.")
    if safe(lambda: body.isSheetMetal) is not True:
        return error("stationary_face belongs to an ordinary body. Use sheet_convert first.")
    if _common.same_component(safe(lambda: comp.parentDesign.rootComponent), safe(lambda: _common.design().rootComponent)) is not True:
        return error("stationary_face must belong to the active design; edit the source document first.")
    folds = safe(lambda: comp.features.foldFeatures)
    if folds is None or safe(lambda: folds.createInput) is None:
        return error("Fold creation is unavailable in this Fusion build.")
    before_faces = safe(lambda: body.faces.count)
    if before_faces is None:
        return error("The sheet body's face count could not be read; re-read its geometry before folding.")
    try:
        inp = folds.createInput(face)
        added = inp.bendLines.add(line, adsk.core.ValueInput.createByReal(math.radians(angle_deg)),
            getattr(adsk.fusion.FoldBendLinePositionTypes, _POSITIONS[pos]), allow_relief)
        if not added:
            return error("bend_line was not accepted; choose a line across the sheet face.")
        feature = folds.add(inp)
    except Exception as exc:
        return error(f"Fold failed for bend_line={bend_line!r}: {exc}")
    if feature is None:
        return error("Fold returned no feature; inspect the body before retrying.")
    angle = safe(lambda: feature.bendLines.item(0).bendAngle.value)
    after_faces = safe(lambda: body.faces.count)
    if angle is None or not math.isclose(angle, math.radians(angle_deg), abs_tol=1e-7):
        return error(f"Fold '{feature.name}' remains, but its angle did not read back as {angle_deg} deg. Inspect or remove it with design_delete_feature.")
    if after_faces is None or after_faces == before_faces:
        return error(f"Fold '{feature.name}' remains, but changed body topology was not verified. Inspect it before retrying.")
    return ok({"created": True, "feature": feature.name, "body": body.name,
               "angle_deg": math.degrees(angle), "faces_before": before_faces, "faces_after": after_faces,
               "note": "Fold created. An interior bend line can extend across the sheet beyond its endpoints. Inspect the stationary side with view_screenshot; sheet_create_flat_pattern creates a native flat whose development remains unverified."})


TOOL_DESCRIPTION = "Fold at a sketch line; an interior line can extend across the sheet. Preview API; inspect the stationary side."
tool = (Tool.create_simple(name="sheet_create_fold", description=TOOL_DESCRIPTION)
        .add_input_property(*_FACE.as_property()).add_input_property(*_LINE.as_property())
        .add_input_property("angle_deg", {"type": "number"})
        .add_input_property(*_POSITION.as_property())
        .add_input_property("allow_relief", {"type": "boolean"})
        .add_input_property("component", {"type": "string", "description": "Scope the bend-line sketch."})
        .add_required_input("stationary_face").add_required_input("bend_line").strict_schema())
item = Item.create_tool_item(tool=tool, handler=handler, write="write", run_on_main_thread=True,
    postconditions=[_assert.FeatureHealthy()], verification=Verification(kind="inline", rung="geometry",
        evidence_test="tests/unit/test_sheet_create_fold.py::test_unchanged_body_is_not_success"))


def register_tool():
    register(item)
