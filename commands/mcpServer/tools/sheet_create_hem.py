# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Hem a sheet body's rim edge: flat, open, rolled, rope, teardrop or double."""

import math
import adsk.core
import adsk.fusion
from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _inputs, _assert, _geom, _sheet_common
from ._common import error, ok, safe
from ._sheet_common import _KIND_SPEC, _POSITIONS

_EDGE = _inputs.GeometryHandle("edge", require="edge", required=True)
_KIND = _inputs.Choice("kind", ["flat", "open", "rolled", "rope", "teardrop", "double"], required=True)
_LENGTH = _inputs.Distance("length", allow_zero=False, allow_negative=False, required=False)
_GAP = _inputs.Distance("gap", allow_zero=False, allow_negative=False, required=False)
_RADIUS = _inputs.Distance("radius", allow_zero=False, allow_negative=False, required=False)
_SETBACK = _inputs.Distance("setback", allow_zero=False, allow_negative=False, required=False)
_POSITION = _inputs.Choice("position", ["start_edge", "tangent_to_side"], default="start_edge")
_DIMS = {"length": _LENGTH, "gap": _GAP, "radius": _RADIUS, "setback": _SETBACK}


def _joined(names):
    """The names of a set, worded as an English list."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def handler(edge="", kind="", length=None, gap=None, radius=None, setback=None, angle_deg=None,
            flip=False, position="start_edge", units="mm"):
    """Create a hem feature on a sheet-metal rim edge and verify the landed kind and topology."""
    scale_factor, uerr = _inputs.UNITS.resolve(units)
    if uerr:
        return error(uerr)
    kind, kerr = _KIND.resolve(kind)
    if kerr:
        return error(kerr)
    pos, perr = _POSITION.resolve(position)
    if perr:
        return error(perr)
    edge_ent, eerr = _EDGE.resolve(edge)
    if eerr:
        return error(eerr)
    edge_ent = _common._native_of(edge_ent)

    dims, def_class = _KIND_SPEC[kind]
    raw = {"length": length, "gap": gap, "radius": radius, "setback": setback, "angle_deg": angle_deg}
    missing = [n for n in dims if raw[n] is None]
    if missing:
        return error(f"kind='{kind}' needs {_joined(dims)}; {missing[0]} is missing.")
    extra = [n for n, v in raw.items() if v is not None and n not in dims]
    if extra:
        return error(f"kind='{kind}' takes {_joined(dims)} only; drop {extra[0]}.")

    values = {}
    for name in dims:
        if name == "angle_deg":
            continue
        v_cm, derr = _DIMS[name].resolve_scaled(raw[name], scale_factor)
        if derr:
            return error(derr)
        values[name] = v_cm
    angle_rad = None
    if "angle_deg" in dims:
        a = raw["angle_deg"]
        if isinstance(a, bool) or not isinstance(a, (int, float)) or not math.isfinite(a) or not 0 < a <= 360:
            return error(f"angle_deg={a!r} must be finite and between 0 (exclusive) and 360 (inclusive).")
        angle_rad = math.radians(a)

    body = safe(lambda: edge_ent.body)
    if body is None:
        return error("edge's body could not be read.")
    if safe(lambda: body.isSheetMetal) is not True:
        return error("edge belongs to an ordinary body. Use sheet_convert first.")
    _sheet_face, _rim_face, why = _sheet_common.sheet_edge_faces(edge_ent)
    if why:
        return error(f"edge {why}")
    comp = safe(lambda: body.parentComponent)
    if comp is None:
        return error("edge's owning component could not be read.")
    if _common.same_component(safe(lambda: comp.parentDesign.rootComponent),
                              safe(lambda: _common.design().rootComponent)) is not True:
        return error("edge must belong to the active design; edit the source document first.")

    body_name = safe(lambda: body.name)
    faces_before = safe(lambda: body.faces.count)
    bend_faces_before = _sheet_common.bend_face_count(body)
    volume_before = _common.measured(lambda: _geom.signed_volume(body), places=9)
    if faces_before is None or body_name is None:
        return error("body topology could not be read before the hem; re-read its geometry.")

    pos_type = getattr(adsk.fusion.BendPositionTypes, _POSITIONS[pos])
    flip = bool(flip)
    hem_count = _common.counted(lambda: comp.features.hemFeatures.count)
    try:
        hems = comp.features.hemFeatures
        inp = hems.createHemFeatureInput()
        if kind == "flat":
            set_ok = inp.setFlatHem(edge_ent, adsk.core.ValueInput.createByReal(values["length"]),
                                    flip, pos_type)
        elif kind == "open":
            set_ok = inp.setOpenHem(edge_ent, adsk.core.ValueInput.createByReal(values["length"]),
                                    adsk.core.ValueInput.createByReal(values["gap"]), flip, pos_type)
        elif kind == "rolled":
            set_ok = inp.setRolledHem(edge_ent, adsk.core.ValueInput.createByReal(values["radius"]),
                                      adsk.core.ValueInput.createByReal(angle_rad), flip, pos_type)
        elif kind == "rope":
            set_ok = inp.setRopeHem(edge_ent, adsk.core.ValueInput.createByReal(values["length"]),
                                    adsk.core.ValueInput.createByReal(values["gap"]),
                                    adsk.core.ValueInput.createByReal(values["radius"]), flip, pos_type)
        elif kind == "teardrop":
            set_ok = inp.setTeardropHem(edge_ent, adsk.core.ValueInput.createByReal(values["radius"]),
                                        adsk.core.ValueInput.createByReal(values["length"]),
                                        adsk.core.ValueInput.createByReal(values["gap"]), flip, pos_type)
        else:
            set_ok = inp.setDoubleHem(edge_ent, adsk.core.ValueInput.createByReal(values["gap"]),
                                      adsk.core.ValueInput.createByReal(values["length"]),
                                      adsk.core.ValueInput.createByReal(values["setback"]), flip, pos_type)
        if not set_ok:
            return error(f"kind='{kind}' dimensions were not accepted; check them against the edge's "
                         "own length.")
        feat = hems.add(inp)
    except Exception as exc:
        text = " ".join(str(exc).split())
        if len(text) > _assert._MESSAGE_LIMIT:
            text = text[:_assert._MESSAGE_LIMIT].rstrip() + " ..."
        after = _common.counted(lambda: comp.features.hemFeatures.count)
        added = " No hem was added." if hem_count is not None and after == hem_count else ""
        return error(f"Hem failed: {text}{added}")
    if feat is None:
        return error("Hem returned no feature; inspect the body before retrying.")

    body_after = safe(lambda: comp.bRepBodies.itemByName(body_name))
    faces_after = safe(lambda: body_after.faces.count) if body_after is not None else None
    bend_faces_after = _sheet_common.bend_face_count(body_after) if body_after is not None else None
    volume_after = (_common.measured(lambda: _geom.signed_volume(body_after), places=9)
                    if body_after is not None else None)
    def_type = safe(lambda: feat.definition.objectType) or ""
    landed_kind_ok = def_type.endswith(def_class)

    if (not landed_kind_ok or body_after is None or faces_after is None or faces_after <= faces_before
            or volume_after is None or volume_before is None or volume_after <= volume_before):
        return error(f"Hem '{feat.name}' remains, but its kind or changed geometry was not verified. "
                     "Inspect it before retrying.")

    return ok({"created": True, "feature": feat.name, "body": body_after.name, "kind": kind,
               "faces_before": faces_before, "faces_after": faces_after,
               "bend_faces_before": bend_faces_before, "bend_faces_after": bend_faces_after,
               "volume_before_cm3": volume_before, "volume_after_cm3": volume_after,
               "flat_pattern": _sheet_common.flat_pattern_row(comp),
               "note": "Hem landed. Next: sheet_create_flat_pattern, or another edge."})


TOOL_DESCRIPTION = ("Hem a sheet body's rim edge: flat, open, rolled, rope, teardrop or double, each "
                    "with its own dimensions. Then sheet_create_flat_pattern.")
tool = (Tool.create_simple(name="sheet_create_hem", description=TOOL_DESCRIPTION)
        .add_input_property(*_EDGE.as_property()).add_input_property(*_KIND.as_property())
        .add_input_property("length", _LENGTH.schema()).add_input_property("gap", _GAP.schema())
        .add_input_property("radius", _RADIUS.schema()).add_input_property("setback", _SETBACK.schema())
        .add_input_property("angle_deg", {"type": "number",
            "description": "Rolled hem angle in degrees, 0 (exclusive) to 360 (inclusive)."})
        .add_input_property("flip", {"type": "boolean"})
        .add_input_property(*_POSITION.as_property())
        .add_input_property(*_inputs.UNITS.as_property())
        .add_required_input("edge").add_required_input("kind").strict_schema())
item = Item.create_tool_item(tool=tool, handler=handler, write="write", run_on_main_thread=True,
    postconditions=[_assert.FeatureHealthy()], verification=Verification(kind="inline", rung="geometry",
        evidence_test="tests/unit/test_sheet_create_hem.py::test_unchanged_body_is_not_success"))


def register_tool():
    register(item)
