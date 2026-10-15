# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Unfold selected bends while retaining a refoldable timeline feature."""

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _inputs, _assert, _geom, _sheet_common
from ._common import error, ok, safe

_FACE = _inputs.GeometryHandle("stationary_face", require="planar_face", required=True)
_BENDS = _inputs.GeometryHandleList("bend_faces", require="face", json_array=True)


def handler(stationary_face="", bend_faces=None, all_bends=False):
    """Unfold one sheet body and verify changed geometry and the feature's mode."""
    if bool(bend_faces) == bool(all_bends):
        return error("Pass bend_faces or all_bends=true, exactly one. Use find_geometry for bend-face handles.")
    face, why = _FACE.resolve(stationary_face)
    if why:
        return error(why)
    bends, why = _BENDS.resolve(bend_faces)
    if why:
        return error(why)
    face = _common._native_of(face)
    body = face.body
    comp = body.parentComponent
    if _common.same_component(safe(lambda: comp.parentDesign.rootComponent), safe(lambda: _common.design().rootComponent)) is not True:
        return error("stationary_face must belong to the active design; edit the source document first.")
    key = _common.native_identity(body)
    if key is None or any(_common.native_identity(safe(lambda b=b: b.body)) != key for b in bends):
        return error("Every bend_face must belong to the stationary face's body.")
    if safe(lambda: body.isSheetMetal) is not True:
        return error("stationary_face must belong to a sheet-metal body. Use sheet_convert first.")
    pending, unread = _sheet_common.pending_unfolds(_common.design())
    if unread:
        return error(f"Unfold preflight: {unread}. Nothing unfolded. Read design_get(include=['timeline']) "
                     "and inspect existing unfold/refold features before retrying.")
    if pending:
        target = pending[0]
        return error(f"Serial unfold policy: pending unfold(s) {_common.named_with_remainder(pending)}. "
                     f"Nothing unfolded. Finish sheet_create_refold(unfold='{target}') before another unfold; "
                     "read design_get(include=['timeline']) for its group if hidden.")
    before = safe(lambda: body.faces.count)
    if before is None:
        return error("Body topology could not be read before unfolding; re-read its geometry.")
    body_name = safe(lambda: body.name)
    if all_bends:
        # Every paired bend wall goes in as an explicit face list: an unfold made with
        # isUnfoldAllBends refolds with a flange held stationary and the body rotated 90 deg,
        # an explicit list refolds exactly.
        groups = _sheet_common.bend_wall_groups(body)
        if groups is None:
            return error(f"'{body_name}' bend faces could not be read; re-read its geometry.")
        if not groups:
            return error(f"'{body_name}' has no bends to unfold.")
        bends = [wall for group in groups for wall in group]
    face_list = list(_common.iter_collection(body.faces))
    frames_before = _geom.face_frames(face_list)
    try:
        features = comp.features.unfoldFeatures
        inp = features.createInput(face)
        inp.bendFaces = [_common._native_of(b) for b in bends]
        feature = features.add(inp)
    except Exception as exc:
        remedy = ("Pass bend_faces explicitly - find_geometry(target='%s', kind='cylinder_face') "
                  "lists the walls; Fusion refuses a hole." % body_name) if all_bends else \
            "Select actual bend faces, not holes or fillets."
        return error(f"Unfold failed: {exc}. {remedy}")
    if feature is None:
        return error("Unfold returned no feature; inspect the body before retrying.")
    after = safe(lambda: body.faces.count)
    moved, compared = _geom.faces_moved(face_list, frames_before)
    if all_bends:
        remaining = _sheet_common.bend_wall_groups(body)
        changed = moved > 0 and remaining == []
    else:
        changed = (after is not None and after != before) or moved > 0
    if not changed:
        return error(f"Unfold '{feature.name}' remains, but its changed geometry was not verified. Inspect it before retrying.")
    bend_count_unfolded = len(groups) if all_bends else len(bends)
    return ok({"created": True, "feature": feature.name, "body": body.name,
               "all_bends": bool(all_bends), "bend_count_unfolded": bend_count_unfolded,
               "faces_before": before, "faces_after": after,
               "faces_moved": moved, "faces_compared": compared,
               "note": "Bends unfolded. Add cuts, then pass this feature to sheet_create_refold."})


TOOL_DESCRIPTION = "Unfold sheet-metal bends; cut, then sheet_create_refold."
tool = (Tool.create_simple(name="sheet_create_unfold", description=TOOL_DESCRIPTION)
        .add_input_property(*_FACE.as_property()).add_required_input("stationary_face")
        .add_input_property(*_BENDS.as_property())
        .add_input_property("all_bends", {"type": "boolean"}).strict_schema())
item = Item.create_tool_item(tool=tool, handler=handler, write="write", run_on_main_thread=True,
    postconditions=[_assert.FeatureHealthy()], verification=Verification(kind="inline", rung="geometry",
        evidence_test="tests/unit/test_sheet_unfold_refold.py::test_unfold_unchanged_body_refused"))


def register_tool():
    register(item)
