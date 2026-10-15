# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Create one component's native sheet-metal flat pattern."""

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _inputs
from ._common import error, ok, safe

_FACE = _inputs.GeometryHandle("stationary_face", require="planar_face", required=True)


def handler(stationary_face=""):
    """Create a flat pattern and read its association and solid volume."""
    face, why = _FACE.resolve(stationary_face)
    if why:
        return error(why)
    face = _common._native_of(face)
    body = face.body
    comp = body.parentComponent
    if _common.same_component(safe(lambda: comp.parentDesign.rootComponent), safe(lambda: _common.design().rootComponent)) is not True:
        return error("stationary_face must belong to the active design; edit the source document first.")
    if safe(lambda: body.isSheetMetal) is not True:
        return error("stationary_face belongs to an ordinary body. Use sheet_convert first.")
    try:
        existing = comp.flatPattern
    except Exception as exc:
        return error(f"Could not check this component's existing flat pattern: {exc}")
    if existing is not None:
        return error("This component already has a flat pattern. Development is unverified; inspect sheet_get(include=['features']) before choosing design_export.")
    try:
        flat = comp.createFlatPattern(face)
    except Exception as exc:
        return error(f"Flat-pattern creation failed: {exc}. Select a broad top or bottom face of the sheet.")
    if flat is None:
        return error("Flat-pattern creation returned no pattern. Inspect the component before retrying.")
    source = safe(lambda: flat.foldedBody)
    key = _common.native_identity(body)
    volume = safe(lambda: flat.flatBody.volume)
    solid = safe(lambda: flat.flatBody.isSolid)
    installed = safe(lambda: comp.flatPattern)
    if key is None or _common.native_identity(source) != key or installed is None or solid is not True or not isinstance(volume, (int, float)) or volume <= 0:
        return error("A flat pattern may remain, but its source association and nonempty solid were not verified. Inspect the component before retrying.")
    return ok({"created": True, "component": comp.name, "folded_body": body.name,
               "flat_volume_cm3": volume, "is_solid": solid, "development": "unverified",
               "note": "Native flat pattern created. Inspect sheet_get(include=['features']) before choosing design_export with the folded body's dxf_flat_pattern reference."})


TOOL_DESCRIPTION = "Create a native flat pattern; inspect sheet_get features before export. One per component."
tool = (Tool.create_simple(name="sheet_create_flat_pattern", description=TOOL_DESCRIPTION)
        .add_input_property(*_FACE.as_property()).add_required_input("stationary_face").strict_schema())
item = Item.create_tool_item(tool=tool, handler=handler, write="write", run_on_main_thread=True,
    verification=Verification(kind="inline", rung="geometry",
        evidence_test="tests/unit/test_sheet_create_flat_pattern.py::test_wrong_source_is_not_success"))


def register_tool():
    register(item)
