# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Join two sheet bodies into one with a bend between two rim edges."""

import math

import adsk.core
from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _inputs, _assert, _geom, _sheet_common
from ._common import error, ok, safe

_EDGE_ONE = _inputs.GeometryHandle("edge_one", require="edge", required=True)
_EDGE_TWO = _inputs.GeometryHandle("edge_two", require="edge", required=True)
_BEND_RADIUS = _inputs.Distance("bend_radius", allow_zero=False, allow_negative=False, required=False)


def handler(edge_one="", edge_two="", bend_radius=None, units="mm"):
    """Join two sheet bodies with a bend and verify the merge and the survivor's bend faces."""
    scale_factor, uerr = _inputs.UNITS.resolve(units)
    if uerr:
        return error(uerr)
    e1, e1err = _EDGE_ONE.resolve(edge_one)
    if e1err:
        return error(e1err)
    e2, e2err = _EDGE_TWO.resolve(edge_two)
    if e2err:
        return error(e2err)
    e1, e2 = _common._native_of(e1), _common._native_of(e2)
    bend_radius_cm = None
    if bend_radius is not None:
        bend_radius_cm, rerr = _BEND_RADIUS.resolve_scaled(bend_radius, scale_factor)
        if rerr:
            return error(rerr)

    _sf1, _rf1, why1 = _sheet_common.sheet_edge_faces(e1)
    if why1:
        return error(f"edge_one {why1}")
    _sf2, _rf2, why2 = _sheet_common.sheet_edge_faces(e2)
    if why2:
        return error(f"edge_two {why2}")

    body_one, body_two = safe(lambda: e1.body), safe(lambda: e2.body)
    if body_one is None or body_two is None:
        return error("edge_one/edge_two's body could not be read.")
    id_one, id_two = _common.native_identity(body_one), _common.native_identity(body_two)
    if id_one is None or id_two is None:
        return error("edge_one/edge_two's body identity could not be read.")
    if id_one == id_two:
        return error("edge_one and edge_two are on the same body; pick a rim edge from each of the "
                     "two sheets to join.")
    comp_one, comp_two = safe(lambda: body_one.parentComponent), safe(lambda: body_two.parentComponent)
    if _common.same_component(comp_one, comp_two) is not True:
        return error("edge_one and edge_two must belong to the same component.")
    if safe(lambda: body_one.isSheetMetal) is not True:
        return error("edge_one belongs to an ordinary body. Use sheet_convert first.")
    if safe(lambda: body_two.isSheetMetal) is not True:
        return error("edge_two belongs to an ordinary body. Use sheet_convert first.")
    comp = comp_one
    if _common.same_component(safe(lambda: comp.parentDesign.rootComponent),
                              safe(lambda: _common.design().rootComponent)) is not True:
        return error("edge_one/edge_two must belong to the active design; edit the source document "
                     "first.")

    body_one_name = safe(lambda: body_one.name)
    bodies_before = safe(lambda: comp.bRepBodies.count)
    bends_one = _sheet_common.bend_face_count(body_one)
    bends_two = _sheet_common.bend_face_count(body_two)
    bend_faces_before = (bends_one + bends_two) if bends_one is not None and bends_two is not None else None
    vol_one = _common.measured(lambda: _geom.signed_volume(body_one), places=9)
    vol_two = _common.measured(lambda: _geom.signed_volume(body_two), places=9)
    volume_before = round(vol_one + vol_two, 9) if vol_one is not None and vol_two is not None else None
    if body_one_name is None or bodies_before is None or bend_faces_before is None:
        return error("body topology could not be read before the join; re-read its geometry.")

    try:
        joins = comp.features.joinByBendFeatures
        inp = joins.createInput(e1, e2)
        if bend_radius_cm is not None:
            # The override ValueInput is read in the document's length unit, so it carries its unit.
            override_set = inp.bendRadiusOverride.setOverride(
                adsk.core.ValueInput.createByString(f"{bend_radius_cm * 10.0:.9g} mm"))
            if not override_set:
                return error(f"bend_radius override ({bend_radius_cm * 10.0:.9g} mm) was not accepted.")
        feat = joins.add(inp)
    except Exception as exc:
        return error(f"Join by bend failed: {_assert.compute_failure_message(str(exc))}")
    if feat is None:
        return error("Join by bend returned no feature; inspect the bodies before retrying.")

    survivor = safe(lambda: comp.bRepBodies.itemByName(body_one_name))
    bodies_after = safe(lambda: comp.bRepBodies.count)
    bend_faces_after = _sheet_common.bend_face_count(survivor) if survivor is not None else None
    volume_after = (_common.measured(lambda: _geom.signed_volume(survivor), places=9)
                    if survivor is not None else None)
    is_overridden = safe(lambda: feat.bendRadiusOverride.isOverridden)
    landed_radius_cm = safe(lambda: feat.bendRadiusOverride.bendRadius.value)

    if (survivor is None or bodies_after is None or bodies_after != bodies_before - 1
            or bend_faces_after is None or bend_faces_after != bend_faces_before + 2):
        return error(f"Join by bend '{feat.name}' remains, but the merge or its bend faces were not "
                     f"verified (bodies {bodies_before} -> {bodies_after}, bend faces "
                     f"{bend_faces_before} -> {bend_faces_after}). Inspect it before retrying.")
    if bend_radius_cm is not None and (is_overridden is not True
                                       or not isinstance(landed_radius_cm, (int, float))
                                       or not math.isclose(landed_radius_cm, bend_radius_cm, rel_tol=1e-6, abs_tol=1e-9)):
        return error(f"Join by bend '{feat.name}' remains, but its bend radius override read back "
                     f"isOverridden={is_overridden}, bendRadius={landed_radius_cm} cm, not the "
                     f"requested {bend_radius_cm} cm. Inspect it before retrying.")

    return ok({"created": True, "feature": feat.name, "body": survivor.name,
               "bodies_before": bodies_before, "bodies_after": bodies_after,
               "uses_rule_radius": None if is_overridden is None else not is_overridden,
               "bend_radius_mm": (round(landed_radius_cm * 10.0, 6)
                                  if isinstance(landed_radius_cm, (int, float)) else None),
               "bend_faces_before": bend_faces_before, "bend_faces_after": bend_faces_after,
               "volume_before_cm3": volume_before, "volume_after_cm3": volume_after,
               "flat_pattern": _sheet_common.flat_pattern_row(comp),
               "note": "Bodies joined by a bend. Next: sheet_create_flat_pattern."})


TOOL_DESCRIPTION = ("Join two sheet bodies with a bend between two rim edges (the preview API merges "
                    "them into one body). Then sheet_create_flat_pattern.")
tool = (Tool.create_simple(name="sheet_create_join_by_bend", description=TOOL_DESCRIPTION)
        .add_input_property(*_EDGE_ONE.as_property()).add_input_property(*_EDGE_TWO.as_property())
        .add_input_property("bend_radius", _BEND_RADIUS.schema())
        .add_input_property(*_inputs.UNITS.as_property())
        .add_required_input("edge_one").add_required_input("edge_two").strict_schema())
item = Item.create_tool_item(tool=tool, handler=handler, write="write", run_on_main_thread=True,
    postconditions=[_assert.FeatureHealthy()], verification=Verification(kind="inline", rung="geometry",
        evidence_test="tests/unit/test_sheet_create_join_by_bend.py::test_unmerged_bodies_is_not_success"))


def register_tool():
    register(item)
