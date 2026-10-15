# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Add a native edge or base flange to a sheet body (preview API)."""

import math

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _inputs, _assert, _geom, _sheet_common
from ._common import error, ok, safe

_KIND = _inputs.Choice("kind", ["edge", "base"], required=True)
_EDGES = _inputs.GeometryHandleList("edges", require="edge", required=True)
_DISTANCE = _inputs.Distance("distance", allow_zero=False, allow_negative=False, required=True)
_HEIGHT_DATUM = _inputs.Choice("height_datum", ["outer", "inner", "tangent_to_bend"], default="outer")
_HEIGHT_DATUMS = {"outer": "OuterFacesFlangeHeightDatumType", "inner": "InnerFacesFlangeHeightDatumType",
                  "tangent_to_bend": "TangentToBendFlangeHeightDatumType"}
_POSITION = _inputs.Choice("position", ["start_edge", "tangent_to_side"], default="start_edge")
_POSITIONS = {"start_edge": "StartEdgeBendPositionType", "tangent_to_side": "TangentToSideBendPositionType"}
_PROFILE = _inputs.ProfileRef("profile", required=True, scope_input="component")
_ORIENTATION = _inputs.Choice("orientation", ["side_one", "side_two", "centered"], default="side_one")
_ORIENTATIONS = {"side_one": "SideOneFlangeOrientation", "side_two": "SideTwoFlangeOrientation",
                 "centered": "CenteredFlangeOrientation"}

_NOTE = ("Flange landed (preview API). Next: sheet_create_hem, another edge, or "
         "sheet_create_flat_pattern.")


def _sketch_normal(sketch):
    """The unit normal of the sketch's plane in its component's space, or None when an axis will not read."""
    # Profile.plane reads in sketch space (its normal is sketch +Z on any plane); xDirection and
    # yDirection read in the component's space.
    x = _geom._coords(safe(lambda: sketch.xDirection))
    y = _geom._coords(safe(lambda: sketch.yDirection))
    n = _geom.cross(x, y) if x is not None and y is not None else None
    mag = math.sqrt(_geom.dot(n, n)) if n is not None else 0.0
    return None if mag < 1e-12 else tuple(c / mag for c in n)


def _slab_thickness_cm(body, normal):
    """Thickness along unit `normal` in cm: two parallel planar faces' gap, else the vertices' spread, else None."""
    planes = []
    for face in _common.iter_collection(safe(lambda: body.faces)):
        origin, n = _geom._face_plane(face)
        if origin is None:
            continue
        cosine = min(1.0, abs(_geom.dot(n, normal)))
        if math.degrees(math.acos(cosine)) <= _geom.PARALLEL_PLANE_TOL_DEG:
            planes.append((origin, n))
    if len(planes) == 2:
        (origin_a, n_a), (origin_b, _n_b) = planes
        return abs(_geom.dot([origin_b[i] - origin_a[i] for i in range(3)], n_a))
    verts = safe(lambda: body.vertices)
    count = safe(lambda: verts.count) if verts is not None else None
    points = [_geom._coords(safe(lambda v=v: v.geometry)) for v in _common.iter_collection(verts)]
    if not isinstance(count, int) or count < 2 or len(points) != count or None in points:
        return None
    heights = [_geom.dot(p, normal) for p in points]
    return max(heights) - min(heights)


def _edge_flange(design, edges_raw, distance, units, angle_deg, height_datum, position, flip,
                  mitered_corners):
    """Build an EdgeFlangeInput off one or more rim edges of one sheet body and verify its effect."""
    if isinstance(angle_deg, bool) or not isinstance(angle_deg, (int, float)) \
            or not math.isfinite(angle_deg) or not 0 < angle_deg < 180:
        return error(f"angle_deg={angle_deg!r} must be finite and between 0 and 180 (exclusive).")
    datum, derr = _HEIGHT_DATUM.resolve(height_datum)
    if derr:
        return error(derr)
    pos, perr = _POSITION.resolve(position)
    if perr:
        return error(perr)
    scale_factor, uerr = _inputs.UNITS.resolve(units)
    if uerr:
        return error(uerr)
    distance_cm, dierr = _DISTANCE.resolve_scaled(distance, scale_factor)
    if dierr:
        return error(dierr)
    edges, eerr = _EDGES.resolve(edges_raw)
    if eerr:
        return error(eerr)
    edges = [_common._native_of(e) for e in edges]

    bodies = []
    for i, e in enumerate(edges):
        _sf, _rf, why = _sheet_common.sheet_edge_faces(e)
        if why:
            return error(f"edges[{i}] {why}")
        b = safe(lambda e=e: e.body)
        if b is None:
            return error(f"edges[{i}]'s body could not be read.")
        bodies.append(b)
    body = bodies[0]
    if safe(lambda: body.isSheetMetal) is not True:
        return error("edges[0] belongs to an ordinary body. Use sheet_convert first.")
    body_key = _common.native_identity(body)
    if body_key is None or any(_common.native_identity(b) != body_key for b in bodies[1:]):
        return error("Every edge must belong to the same sheet body.")
    comp = safe(lambda: body.parentComponent)
    if comp is None:
        return error("edges' owning component could not be read.")
    if _common.same_component(safe(lambda: comp.parentDesign.rootComponent),
                              safe(lambda: design.rootComponent)) is not True:
        return error("edges must belong to the active design; edit the source document first.")

    body_name = safe(lambda: body.name)
    faces_before = safe(lambda: body.faces.count)
    bend_faces_before = _sheet_common.bend_face_count(body)
    volume_before = _common.measured(lambda: _geom.signed_volume(body), places=9)
    if body_name is None or faces_before is None or bend_faces_before is None:
        return error("body topology could not be read before the flange; re-read its geometry.")

    try:
        ff = comp.features.flangeFeatures
        # The ValueInput is read in the DOCUMENT unit, not centimeters - createByReal(cm) landed
        # a value equal to the number itself in mm (measured live), so it carries its own unit.
        inp = ff.createEdgeFlangeInput(
            edges, adsk.core.ValueInput.createByString(f"{distance_cm * 10.0:.9g} mm"))
        if inp is None:
            raise RuntimeError("createEdgeFlangeInput returned no input.")
        inp.heightDatumType = getattr(adsk.fusion.FlangeHeightDatumTypes, _HEIGHT_DATUMS[datum])
        inp.bendPositionType = getattr(adsk.fusion.BendPositionTypes, _POSITIONS[pos])
        inp.isMiteredCorners = bool(mitered_corners)
        inp.isFlipped = bool(flip)
        inp.angle = adsk.core.ValueInput.createByReal(math.radians(angle_deg))
        feat = ff.add(inp)
    except Exception as exc:
        return error(f"Flange failed: {_assert.compute_failure_message(str(exc))}")
    if feat is None:
        return error("Flange returned no feature; inspect the body before retrying.")

    body_after = safe(lambda: comp.bRepBodies.itemByName(body_name))
    faces_after = safe(lambda: body_after.faces.count) if body_after is not None else None
    bend_faces_after = _sheet_common.bend_face_count(body_after) if body_after is not None else None
    volume_after = (_common.measured(lambda: _geom.signed_volume(body_after), places=9)
                    if body_after is not None else None)
    definition = safe(lambda: feat.definition)
    def_type = safe(lambda: definition.objectType) or ""
    landed_class_ok = def_type.endswith("EdgeFlangeFeatureDefinition")
    expected_growth = 2 * len(edges)

    # FlangeFeature itself carries no angle/distance; its definition (a model-parameter pair) does.
    landed_distance_cm = safe(lambda: definition.distance.value)
    landed_angle_rad = safe(lambda: definition.angle.value)
    distance_ok = (isinstance(landed_distance_cm, (int, float))
                  and math.isclose(landed_distance_cm, distance_cm, rel_tol=1e-6))
    angle_ok = (isinstance(landed_angle_rad, (int, float))
               and math.isclose(landed_angle_rad, math.radians(angle_deg), rel_tol=1e-6))
    landed_datum = safe(lambda: definition.heightDatumType)
    landed_position = safe(lambda: definition.bendPositionType)
    landed_flip = safe(lambda: definition.isFlipped)
    datum_ok = landed_datum == getattr(adsk.fusion.FlangeHeightDatumTypes, _HEIGHT_DATUMS[datum])
    position_ok = landed_position == getattr(adsk.fusion.BendPositionTypes, _POSITIONS[pos])
    flip_ok = landed_flip == bool(flip)

    if (not landed_class_ok or body_after is None or faces_after is None or faces_after <= faces_before
            or bend_faces_after is None or bend_faces_after != bend_faces_before + expected_growth
            or volume_after is None or volume_before is None or volume_after <= volume_before
            or not distance_ok or not angle_ok or not datum_ok or not position_ok or not flip_ok):
        return error(f"Flange '{feat.name}' remains, but its effect was not verified: faces "
                     f"{faces_before}->{faces_after}, bend faces {bend_faces_before}->"
                     f"{bend_faces_after} (want +{expected_growth}), volume {volume_before}->"
                     f"{volume_after} cm3, distance {landed_distance_cm} cm (want {distance_cm}), "
                     f"angle {landed_angle_rad} rad (want {math.radians(angle_deg)}), datum "
                     f"{landed_datum} (want {getattr(adsk.fusion.FlangeHeightDatumTypes, _HEIGHT_DATUMS[datum])}), "
                     f"position {landed_position} (want {getattr(adsk.fusion.BendPositionTypes, _POSITIONS[pos])}), "
                     f"flip {landed_flip} (want {bool(flip)}). Inspect it before retrying.")

    return ok({
        "created": True, "feature": feat.name, "body": body_after.name, "kind": "edge",
        "faces_before": faces_before, "faces_after": faces_after,
        "bend_faces_before": bend_faces_before, "bend_faces_after": bend_faces_after,
        "volume_before_cm3": volume_before, "volume_after_cm3": volume_after,
        "height_datum": datum, "position": pos, "flip": bool(flip),
        "flat_pattern": _sheet_common.flat_pattern_row(comp),
        "note": _NOTE,
    })


def _base_flange(design, profile_raw, orientation, component):
    """Build a BaseFlangeInput off one closed profile in the active component and verify its effect."""
    orient, oerr = _ORIENTATION.resolve(orientation)
    if oerr:
        return error(oerr)
    prof, perr = _PROFILE.resolve(profile_raw, component)
    if perr:
        return error(perr)
    sketch = safe(lambda: prof.parentSketch)
    active = _common.target_component(design)
    host = _inputs.profile_host_component(prof, sketch, active)
    if _common.same_component(host, active) is not True:
        host_name = safe(lambda: host.name) or "(unreadable)"
        active_name = safe(lambda: active.name) or "(unreadable)"
        return error(f"profile's component '{host_name}' is not the active component "
                     f"'{active_name}' - the flange body lands wherever is active. Activate it "
                     "first with design_activate_component.")
    comp = active
    n_vec = _sketch_normal(sketch)

    bodies_before = safe(lambda: comp.bRepBodies.count)
    rule_before = safe(lambda: comp.activeSheetMetalRule)
    rule_existed_before = rule_before is not None
    if bodies_before is None:
        return error("component body count could not be read before the flange; re-read its geometry.")

    try:
        ff = comp.features.flangeFeatures
        inp = ff.createBaseFlangeInput([prof])
        if inp is None:
            raise RuntimeError("createBaseFlangeInput returned no input.")
        want_orientation = getattr(adsk.fusion.FlangeOrientations, _ORIENTATIONS[orient])
        inp.orientation = want_orientation
        feat = ff.add(inp)
    except Exception as exc:
        return error(f"Flange failed: {_assert.compute_failure_message(str(exc))}")
    if feat is None:
        return error("Flange returned no feature; inspect the component before retrying.")

    bodies_after = safe(lambda: comp.bRepBodies.count)
    result = _common.result_bodies(feat)
    new_body = result[0] if result else None
    definition = safe(lambda: feat.definition)
    def_type = safe(lambda: definition.objectType) or ""
    landed_class_ok = def_type.endswith("BaseFlangeFeatureDefinition")
    is_sheet = safe(lambda: new_body.isSheetMetal) if new_body is not None else None
    landed_orientation = safe(lambda: definition.orientation)
    orientation_ok = landed_orientation == want_orientation
    # The rule the factory itself made or adopted is only readable AFTER the add - the component may
    # have carried none before it.
    rule_after = safe(lambda: comp.activeSheetMetalRule)
    rule_after_name = safe(lambda: rule_after.name) if rule_after is not None else None
    rule_thickness_cm = safe(lambda: rule_after.thickness.value) if rule_after is not None else None
    thickness_cm = (_slab_thickness_cm(new_body, n_vec)
                    if n_vec is not None and new_body is not None else None)
    thickness_ok = (rule_thickness_cm is not None and thickness_cm is not None
                    and math.isclose(thickness_cm, rule_thickness_cm, rel_tol=1e-6, abs_tol=1e-9))

    if (not landed_class_ok or new_body is None or bodies_after is None
            or bodies_after != bodies_before + 1 or is_sheet is not True or not thickness_ok
            or not orientation_ok):
        return error(f"Flange '{feat.name}' remains, but its effect was not verified: bodies "
                     f"{bodies_before}->{bodies_after}, isSheetMetal={is_sheet}, thickness "
                     f"{thickness_cm} cm (rule '{rule_after_name}' {rule_thickness_cm} cm), "
                     f"orientation {landed_orientation} (want {want_orientation}). Inspect it "
                     "before retrying.")

    return ok({
        "created": True, "feature": feat.name, "body": safe(lambda: new_body.name), "kind": "base",
        "bodies_before": bodies_before, "bodies_after": bodies_after,
        "rule": rule_after_name, "rule_existed_before": rule_existed_before,
        "thickness_mm": round(thickness_cm * 10.0, 6), "orientation": orient,
        "flat_pattern": _sheet_common.flat_pattern_row(comp),
        "note": _NOTE,
    })


def handler(kind="", edges=None, distance=None, units="mm", angle_deg=90.0, height_datum="outer",
            position="start_edge", flip=False, mitered_corners=True, profile=None,
            orientation="side_one", component=""):
    """See TOOL_DESCRIPTION."""
    kind_v, kerr = _KIND.resolve(kind)
    if kerr:
        return error(kerr)
    design, design_refusal = _common.require_design()
    if design_refusal is not None:
        return design_refusal
    if kind_v == "edge":
        return _edge_flange(design, edges, distance, units, angle_deg, height_datum, position,
                            flip, mitered_corners)
    return _base_flange(design, profile, orientation, component)


TOOL_DESCRIPTION = ("Add a native flange to a sheet body: an edge flange along rim edges, or a "
                    "base flange from a closed profile. The API is preview. Then sheet_create_hem "
                    "or sheet_create_flat_pattern.")
tool = (Tool.create_simple(name="sheet_create_flange", description=TOOL_DESCRIPTION)
        .add_input_property(*_KIND.as_property())
        .add_input_property(*_EDGES.as_property())
        .add_input_property("distance", {**_DISTANCE.schema(), "description":
                            "Flange height, measured per 'height_datum'. kind='edge'."})
        .add_input_property(*_inputs.UNITS.as_property())
        .add_input_property("angle_deg", {"type": "number",
            "description": "Flange angle in degrees, 0 (exclusive) to 180 (exclusive). kind='edge'."})
        .add_input_property(*_HEIGHT_DATUM.as_property())
        .add_input_property(*_POSITION.as_property())
        .add_input_property("flip", {"type": "boolean",
            "description": "Flip the flange direction. kind='edge'."})
        .add_input_property("mitered_corners", {"type": "boolean",
            "description": "Miter adjacent flange corners. kind='edge'."})
        .add_input_property("profile", {**_PROFILE.schema(),
            "description": "A closed sketch profile. kind='base'."})
        .add_input_property(*_ORIENTATION.as_property())
        .add_input_property("component", {"type": "string",
            "description": "Scope for 'profile'. kind='base'."})
        .add_required_input("kind").strict_schema())
item = Item.create_tool_item(tool=tool, handler=handler, write="write", run_on_main_thread=True,
    postconditions=[_assert.FeatureHealthy()], verification=Verification(kind="inline", rung="geometry",
        evidence_test="tests/unit/test_sheet_create_flange.py::test_bend_faces_short_of_two_is_error"))


def register_tool():
    register(item)
