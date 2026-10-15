# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Rip a sheet body by a face, along an edge, or between two vertices."""

import adsk.core
from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _inputs, _assert, _geom, _sheet_common
from ._common import error, ok, safe

_MODE = _inputs.Choice("mode", ["face", "along_edge", "between_points"], required=True)
_FACE = _inputs.GeometryHandle("face", require="face")
_EDGE = _inputs.GeometryHandle("edge", require="edge")
_POINT_ONE = _inputs.GeometryHandle("point_one", require="vertex")
_POINT_TWO = _inputs.GeometryHandle("point_two", require="vertex")
_GAP = _inputs.Distance("gap", allow_zero=False, allow_negative=False, required=False)
_MODE_SELECTORS = {"face": ("face",), "along_edge": ("edge",),
                   "between_points": ("point_one", "point_two")}


def _joined(names):
    """The names of a set, worded as an English list."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _body_volume_census(comp):
    """{native_identity(body): {name, volume_cm3}} over comp's solid bodies, or None when a read fails."""
    coll = safe(lambda: comp.bRepBodies)
    if coll is None:
        return None
    out = {}
    for b in _common.iter_collection(coll):
        if safe(lambda b=b: b.isSolid) is not True:
            continue
        key = _common.native_identity(b)
        if key is None:
            return None
        out[key] = {"name": safe(lambda b=b: b.name),
                    "volume_cm3": _common.measured(lambda b=b: _geom.signed_volume(b), places=9)}
    return out


def _total_volume(census):
    """The summed volume_cm3 across a census's rows, or None when any row's volume will not read."""
    vols = [row["volume_cm3"] for row in census.values()]
    return round(sum(vols), 9) if vols and all(isinstance(v, (int, float)) for v in vols) else None


def handler(mode="", face="", edge="", point_one="", point_two="", gap=None, units="mm"):
    """Rip a sheet body along the requested selector and verify the topology and volume changed."""
    scale_factor, uerr = _inputs.UNITS.resolve(units)
    if uerr:
        return error(uerr)
    mode, merr = _MODE.resolve(mode)
    if merr:
        return error(merr)
    provided = {"face": face, "edge": edge, "point_one": point_one, "point_two": point_two}
    required = _MODE_SELECTORS[mode]
    missing = [n for n in required if not str(provided[n] or "").strip()]
    if missing:
        return error(f"mode='{mode}' needs {_joined(required)}; {missing[0]} is missing.")
    extra = [n for n, v in provided.items() if str(v or "").strip() and n not in required]
    if extra:
        return error(f"mode='{mode}' takes {_joined(required)} only; drop {extra[0]}.")
    if mode == "face" and gap is not None:
        return error(f"gap={gap!r} does not apply to mode='face': setByFace removes the bend face and "
                     "takes no gap. Drop gap, or pass mode='along_edge' or 'between_points' to rip at "
                     "a chosen gap.")

    body = None
    selector_label = required[0]
    point_one_ent = point_two_ent = None
    if mode == "face":
        ent, rerr = _FACE.resolve(face)
        if rerr:
            return error(rerr)
        ent = _common._native_of(ent)
        body = safe(lambda: ent.body)
    elif mode == "along_edge":
        ent, rerr = _EDGE.resolve(edge)
        if rerr:
            return error(rerr)
        ent = _common._native_of(ent)
        body = safe(lambda: ent.body)
    else:
        point_one_ent, r1 = _POINT_ONE.resolve(point_one)
        if r1:
            return error(r1)
        point_two_ent, r2 = _POINT_TWO.resolve(point_two)
        if r2:
            return error(r2)
        point_one_ent = _common._native_of(point_one_ent)
        point_two_ent = _common._native_of(point_two_ent)
        body_one, body_two = safe(lambda: point_one_ent.body), safe(lambda: point_two_ent.body)
        if body_one is None or body_two is None:
            return error("point_one/point_two's body could not be read.")
        id_one, id_two = _common.native_identity(body_one), _common.native_identity(body_two)
        if id_one is None or id_two is None or id_one != id_two:
            return error("point_one and point_two must lie on the same body.")
        body = body_one

    if body is None:
        return error(f"{selector_label}'s body could not be read.")
    if safe(lambda: body.isSheetMetal) is not True:
        return error(f"{selector_label} belongs to an ordinary body. Use sheet_convert first.")
    comp = safe(lambda: body.parentComponent)
    if comp is None:
        return error(f"{selector_label}'s owning component could not be read.")
    if _common.same_component(safe(lambda: comp.parentDesign.rootComponent),
                              safe(lambda: _common.design().rootComponent)) is not True:
        return error(f"{selector_label} must belong to the active design; edit the source document "
                     "first.")

    gap_fields = {}
    if mode != "face":
        if gap is not None:
            gap_cm, gerr = _GAP.resolve_scaled(gap, scale_factor)
            if gerr:
                return error(gerr)
            gap_source = "input"
        else:
            rule = safe(lambda: comp.activeSheetMetalRule)
            rule_gap = safe(lambda: rule.gap) if rule is not None else None
            gap_cm = safe(lambda: rule_gap.value) if rule_gap is not None else None
            if gap_cm is None:
                return error("gap is not given and the component's active sheet-metal rule has no "
                             "readable gap; pass 'gap' explicitly.")
            gap_source = "rule"
        gap_fields = {"gap_mm": round(gap_cm * 10.0, 6), "gap_source": gap_source}

    body_name = safe(lambda: body.name)
    faces_before = safe(lambda: body.faces.count)
    bend_faces_before = _sheet_common.bend_face_count(body)
    volume_before = _common.measured(lambda: _geom.signed_volume(body), places=9)
    bodies_before = _body_volume_census(comp)
    if faces_before is None or body_name is None or bodies_before is None:
        return error("body topology could not be read before the rip; re-read its geometry.")

    try:
        rips = comp.features.ripFeatures
        inp = rips.createRipFeatureInput()
        if mode == "face":
            set_ok = inp.setByFace(ent)
        elif mode == "along_edge":
            set_ok = inp.setAlongEdge(ent, adsk.core.ValueInput.createByReal(gap_cm))
        else:
            set_ok = inp.setBetweenPoints(point_one_ent, point_two_ent,
                                          adsk.core.ValueInput.createByReal(gap_cm))
        if not set_ok:
            return error(f"mode='{mode}' selector was not accepted; pick a rim {selector_label} of "
                         "the sheet body.")
        feat = rips.add(inp)
    except Exception as exc:
        return error(f"Rip failed: {_assert.compute_failure_message(str(exc))}")
    if feat is None:
        return error("Rip returned no feature; inspect the body before retrying.")

    body_after = safe(lambda: comp.bRepBodies.itemByName(body_name))
    faces_after = safe(lambda: body_after.faces.count) if body_after is not None else None
    bend_faces_after = _sheet_common.bend_face_count(body_after) if body_after is not None else None
    volume_after = (_common.measured(lambda: _geom.signed_volume(body_after), places=9)
                    if body_after is not None else None)
    bodies_after = _body_volume_census(comp)

    if body_after is None or faces_after is None or bodies_after is None:
        return error(f"Rip '{feat.name}' remains, but its changed geometry was not verified. Inspect "
                     "it before retrying.")

    total_before = _total_volume(bodies_before)
    total_after = _total_volume(bodies_after)
    if total_before is None or total_after is None:
        return error(f"Rip '{feat.name}' remains, but its changed geometry was not verified. Inspect "
                     "it before retrying.")
    volume_removed = round(total_before - total_after, 9)
    if volume_removed <= 0:
        return error(f"Rip '{feat.name}' remains, but the component's bodies read {total_before} "
                     f"cm3 before and {total_after} cm3 after; inspect it before retrying.")

    new_bodies = sorted((row["name"] for key, row in bodies_after.items() if key not in bodies_before),
                        key=lambda n: n or "")
    bodies_before_rows = sorted(bodies_before.values(), key=lambda r: r["name"] or "")
    bodies_after_rows = sorted(bodies_after.values(), key=lambda r: r["name"] or "")
    note = (f"The rip left {len(bodies_after_rows)} bodies in the component: "
            f"{_joined([r['name'] or 'unnamed' for r in bodies_after_rows])}. Next: sheet_create_flat_pattern."
            if new_bodies else
            "Rip landed. A converted box may still refuse to develop (blended corners); "
            "build boxes from sheet_create_flange. Next: sheet_create_flat_pattern.")

    return ok({"created": True, "feature": feat.name, "body": body_after.name, "mode": mode,
               **gap_fields,
               "faces_before": faces_before, "faces_after": faces_after,
               "bend_faces_before": bend_faces_before, "bend_faces_after": bend_faces_after,
               "volume_before_cm3": volume_before, "volume_after_cm3": volume_after,
               "bodies_before": bodies_before_rows, "bodies_after": bodies_after_rows,
               "new_bodies": new_bodies,
               "total_volume_before_cm3": total_before, "total_volume_after_cm3": total_after,
               "volume_removed_cm3": volume_removed,
               "flat_pattern": _sheet_common.flat_pattern_row(comp),
               "note": note})


TOOL_DESCRIPTION = ("Rip a sheet body by a face (takes no gap), along an edge or between two vertices "
                    "(gap from the rule unless given). Then sheet_create_flat_pattern.")
tool = (Tool.create_simple(name="sheet_create_rip", description=TOOL_DESCRIPTION)
        .add_input_property(*_MODE.as_property())
        .add_input_property("face", _FACE.schema()).add_input_property("edge", _EDGE.schema())
        .add_input_property("point_one", _POINT_ONE.schema())
        .add_input_property("point_two", _POINT_TWO.schema())
        .add_input_property("gap", _GAP.schema())
        .add_input_property(*_inputs.UNITS.as_property())
        .add_required_input("mode").strict_schema())
item = Item.create_tool_item(tool=tool, handler=handler, write="write", run_on_main_thread=True,
    postconditions=[_assert.FeatureHealthy()], verification=Verification(kind="inline", rung="geometry",
        evidence_test="tests/unit/test_sheet_create_rip.py::test_unchanged_volume_is_not_success"))


def register_tool():
    register(item)
