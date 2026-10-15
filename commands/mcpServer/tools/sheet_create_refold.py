# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Refold the sheet associated with one explicit unfold feature."""

import adsk.fusion
from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _inputs, _assert, _geom
from ._common import error, ok, safe

_UNFOLD = _inputs.FeatureRef("unfold", required=True)


def handler(unfold=""):
    """Refold the selected unfold and verify its association and changed body geometry."""
    resolved, why = _UNFOLD.resolve(unfold)
    if why:
        return error(why)
    source, label = resolved
    if not isinstance(source, adsk.fusion.UnfoldFeature):
        return error(f"unfold={unfold!r} is not an UnfoldFeature. Read design_get(include=['timeline']).")
    source = _common._native_of(source)
    try:
        existing = source.refoldFeature
        body = source.stationaryFace.body
    except Exception as exc:
        return error(f"Cannot read unfold={unfold!r}: {exc}. Inspect the timeline before retrying.")
    if existing is not None:
        return error(f"unfold={unfold!r} already has refold '{existing.name}'; no duplicate was created.")
    before = safe(lambda: body.faces.count)
    if before is None:
        return error(f"unfold={unfold!r}: body topology could not be read before refolding.")
    face_list = list(_common.iter_collection(body.faces))
    frames_before = _geom.face_frames(face_list)
    try:
        features = source.parentComponent.features.refoldFeatures
        feature = features.add(features.createInput(source))
    except Exception as exc:
        return error(f"Refold failed for unfold={unfold!r}: {exc}")
    if feature is None:
        return error("Refold returned no feature; inspect the timeline before retrying.")
    after = safe(lambda: body.faces.count)
    moved, compared = _geom.faces_moved(face_list, frames_before)
    changed = (after is not None and after != before) or moved > 0
    key = _common.native_identity(source)
    if key is None or _common.native_identity(safe(lambda: feature.unfoldFeature)) != key or not changed:
        return error(f"Refold '{feature.name}' remains, but its unfold association or changed geometry was not verified. Inspect it before retrying.")
    return ok({"created": True, "feature": feature.name, "unfold": label, "body": body.name,
               "faces_before": before, "faces_after": after,
               "faces_moved": moved, "faces_compared": compared,
               "note": "Sheet refolded with the intervening edits. Inspect the bends with view_screenshot."})


TOOL_DESCRIPTION = "Refold one explicit unfold feature after adding flat-state edits. Preview API."
tool = (Tool.create_simple(name="sheet_create_refold", description=TOOL_DESCRIPTION)
        .add_input_property(*_UNFOLD.as_property()).add_required_input("unfold").strict_schema())
item = Item.create_tool_item(tool=tool, handler=handler, write="write", run_on_main_thread=True,
    postconditions=[_assert.FeatureHealthy()], verification=Verification(kind="inline", rung="geometry",
        evidence_test="tests/unit/test_sheet_unfold_refold.py::test_refold_wrong_association_refused"))


def register_tool():
    register(item)
