# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: revolve a sketch profile about an axis into a solid.

  model_revolve -> spin a closed sketch profile around an axis to make a solid of revolution
                   (shafts, pistons, pulleys, bottles, anything turned). Choose the feature
                   operation, the angle (full 360 or partial), and symmetry. WRITES.
"""

import math

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe, target_component, root_body_advisory
from . import _common
from . import _geom
from . import _inputs
from . import _sketch_detail
from . import _assert

app = adsk.core.Application.get()

# profile_index may carry a profile HANDLE (entityToken from sketch_get) - resolved via ProfileRef.
_PROFILE = _inputs.ProfileRef("profile_index", scope_input="component")

_VEC_TO_KEY = {(1, 0, 0): "x", (0, 1, 0): "y", (0, 0, 1): "z"}

# face_entity hands an axis-defining FACE through: createInput's axis takes the entity that DEFINES
# the axis, and a face resolved to a direction vector would drop the axis POSITION - a cylinder at
# x=30 would revolve about the world axis through the origin.
_AXIS = _inputs.AxisRef("axis", face_entity=True, default="z")
_TARGET_BODIES = _inputs.BodyRefList("target_bodies", required=False)
_TO_OBJECT = _inputs.PlaneRef("to_object", required=False)
_TO_OBJECT_TWO = _inputs.PlaneRef("to_object_two", required=False)


def _unit(v):
    """Normalize a coordinate sequence through the shared geometry vector reader."""
    if len(v) != 3 or not all(math.isfinite(x) for x in v):
        return None
    return _geom.unit_vector(adsk.core.Vector3D.create(*v), decimals=12)


def _stop_direction_hint(sketch, profile, axis_entity, stop_plane, design):
    """Build the measured one-side tangent hint from the actual profile, axis and stop plane."""
    root = safe(lambda: design.rootComponent)
    sketch_owner = safe(lambda: sketch.parentComponent)
    plane_owner = _inputs.entity_component(stop_plane)
    axis_owner = _inputs.entity_component(axis_entity)
    if (root is None or _common.same_component(sketch_owner, root) is not True
            or _common.same_component(plane_owner, root) is not True
            or _common.same_component(axis_owner, root) is not True
            or safe(lambda: sketch.assemblyContext) is not None
            or safe(lambda: stop_plane.assemblyContext) is not None
            or safe(lambda: axis_entity.assemblyContext) is not None):
        return None, "Construction-plane stops require native root-component geometry; use angle extents for placed component geometry."
    axis_line, axis_error = _inputs.axis_line_of("axis", axis_entity)
    if axis_error or axis_line is None:
        return None, axis_error or "The revolve axis direction could not be read."
    axis_origin, axis_vector = axis_line
    origin = _geom._coords(axis_origin)
    axis = _unit(_geom._coords(axis_vector) or ())
    if origin is None or axis is None:
        return None, "The revolve axis origin or direction could not be read."
    loops = safe(lambda: profile.profileLoops)
    loop_count = safe(lambda: loops.count) if loops else None
    if loop_count is None:
        return None, "The selected profile loops could not be read for a stop hint."
    points = []
    for i in range(loop_count):
        curves = safe(lambda i=i: loops.item(i).profileCurves)
        curve_count = safe(lambda curves=curves: curves.count) if curves else None
        if curve_count is None:
            return None, "The selected profile curve collection could not be read for a stop hint."
        for j in range(curve_count):
            entity = safe(lambda curves=curves, j=j: curves.item(j).sketchEntity)
            for endpoint in ("startSketchPoint", "endSketchPoint"):
                point = safe(lambda entity=entity, endpoint=endpoint:
                             getattr(entity, endpoint).worldGeometry)
                xyz = _geom._coords(point)
                if xyz is not None:
                    points.append(xyz)
    if len(points) < 2:
        return None, "The profile's actual sketch-line world corners could not be read for a stop hint."
    radial_points = []
    for point in points:
        offset = tuple(point[i] - origin[i] for i in range(3))
        radial = tuple(offset[i] - _geom.dot(offset, axis) * axis[i] for i in range(3))
        unit_radial = _unit(radial)
        if unit_radial is not None:
            radial_points.append((math.sqrt(_geom.dot(radial, radial)), unit_radial))
    if not radial_points:
        return None, "The profile does not establish a radial side around the selected axis."
    source_radial = min(radial_points, key=lambda item: item[0])[1]
    geometry = safe(lambda: stop_plane.geometry)
    plane_origin, normal = _geom._coords(safe(lambda: geometry.origin)), _unit(_geom._coords(safe(lambda: geometry.normal)) or ())
    if plane_origin is None or normal is None:
        return None, "The stop construction plane's origin or normal could not be read."
    if abs(_geom.dot(normal, axis)) > 1e-6 or abs(_geom.dot(tuple(origin[i] - plane_origin[i] for i in range(3)), normal)) > 1e-6:
        return None, "The stop plane must contain the selected revolve axis to establish a radial stop direction."
    target_ray = _unit(_geom.cross(normal, axis))
    if target_ray is None:
        return None, "The stop plane does not establish a radial ray around the selected axis."
    if _geom.dot(target_ray, source_radial) < 0:
        target_ray = tuple(-v for v in target_ray)
    tangent = _unit(_geom.cross(axis, source_radial))
    if tangent is None:
        return None, "The selected profile point is on the revolve axis and has no tangent direction."
    alignment = _geom.dot(tangent, target_ray)
    if abs(alignment) <= 1e-9:
        return None, "The stop plane does not distinguish a travel direction from the profile's radial side."
    direction = tangent if alignment > 0 else tuple(-v for v in tangent)
    return adsk.core.Vector3D.create(*direction), None


def _stop_plane_face_count(bodies, stop_plane):
    """Count planar result faces whose readable vertices lie on a construction-plane stop."""
    geometry = safe(lambda: stop_plane.geometry)
    origin, normal = _geom._coords(safe(lambda: geometry.origin)), _unit(_geom._coords(safe(lambda: geometry.normal)) or ())
    if origin is None or normal is None:
        return None
    found = 0
    for body in bodies:
        faces = safe(lambda body=body: body.faces)
        count = safe(lambda faces=faces: faces.count) if faces else None
        if count is None:
            return None
        for i in range(count):
            face = safe(lambda faces=faces, i=i: faces.item(i))
            if face is None:
                return None
            surface = safe(lambda face=face: face.geometry)
            if surface is None:
                return None
            if safe(lambda surface=surface: surface.surfaceType) != adsk.core.SurfaceTypes.PlaneSurfaceType:
                continue
            vertices = safe(lambda face=face: face.vertices)
            n_vertices = safe(lambda vertices=vertices: vertices.count) if vertices else None
            if n_vertices is None:
                return None
            if n_vertices < 3:
                continue
            residuals = []
            for j in range(n_vertices):
                point = _geom._coords(safe(lambda vertices=vertices, j=j: vertices.item(j).geometry))
                if point is None:
                    residuals = []
                    break
                residuals.append(abs(_geom.dot(tuple(point[k] - origin[k] for k in range(3)), normal)))
            if len(residuals) == n_vertices and max(residuals) <= 1e-6:
                found += 1
    return found


def _in_context(ent, comp, design):
    """(entity, error) - the axis entity in a form the revolve's component can consume."""
    # A NATIVE entity (assemblyContext None) owned by ANOTHER component takes the whole script host
    # down, not a catchable raise; the same entity proxied into the occurrence that carries it is
    # accepted. The refusal wording completes the caller's "Could not resolve axis '<x>': ..."
    occ, err = _inputs.single_placement("it", ent, comp, design)
    if err:
        return None, err
    if occ is None:
        return ent, None
    proxy = safe(lambda: ent.createForAssemblyContext(occ))
    if proxy is None:
        path = safe(lambda: occ.fullPathName) or "its one occurrence"
        return None, (f"it could not be brought into the revolve's assembly context ({path}). Pass "
                      "a handle at geometry in the sketch's own component, or a world axis (x/y/z).")
    return proxy, None


def _cut_check_bodies(comp):
    """The solid bodies a cut/intersect revolve can act on: every solid directly in the feature's
    host component, resolved once so the same objects are re-read afterwards."""
    return [b for b in _common.iter_collection(safe(lambda: comp.bRepBodies))
            if safe(lambda b=b: b.isSolid)]


def _axis_entity(design, comp, sketch, axis):
    """(axis entity, label), or (None, error detail): world x/y/z, a handle, or 'line:<index>' for
    a line by position in the profile's own sketch."""
    a = (axis or "z").strip().lower()
    if a.startswith("line:"):
        try:
            idx = int(a.split(":", 1)[1])
        except Exception:
            return None, f"'{axis}' is not a valid line selector (want 'line:<index>')."
        lines = safe(lambda: sketch.sketchCurves.sketchLines)
        n = safe(lambda: lines.count, 0) if lines else 0
        if lines is None or not (0 <= idx < n):
            return None, f"line index {idx} out of range - sketch has {n} line(s)."
        return safe(lambda: lines.item(idx)), f"sketch {a}"

    tagged, err = _AXIS.resolve(axis)
    if err:
        return None, err
    kind, val = tagged
    if kind == "world":
        key = _VEC_TO_KEY.get(val)
        ent = _inputs.world_construction_axis(comp, key) if key else None
        return ent, f"{key}-axis"
    # The label is the entity's own name where it has one (a construction axis does), else its type
    # - neither a BRepEdge nor a BRepFace carries a name.
    ent, cerr = _in_context(val, comp, design)
    if cerr:
        return None, cerr
    name = safe(lambda: ent.name)
    return ent, (name if isinstance(name, str) and name else type(ent).__name__)


def handler(sketch_name: str = "", profile_index=0, axis: str = "z",
            angle_deg: float = 360.0, operation: str = "new", symmetric: bool = False,
            second_angle_deg: float = 0.0, component: str = "", target_bodies=None,
            to_object: str = "", to_object_two: str = "") -> dict:
    """See TOOL_DESCRIPTION."""
    op_key = (operation or "new").strip().lower()
    if op_key not in _common.OPERATIONS:
        return error(f"Unknown operation '{operation}'. Use: new, join, cut, intersect.")
    try:
        ang = float(angle_deg)
    except Exception:
        return error("angle_deg must be a number (degrees).")
    if not math.isfinite(ang) or ang == 0:
        return error("Provide a non-zero 'angle_deg' to revolve (e.g. 360 for a full revolve).")
    try:
        second = float(second_angle_deg or 0.0)
    except Exception:
        return error("second_angle_deg must be a number (degrees).")
    if not math.isfinite(second):
        return error("second_angle_deg must be finite.")
    has_stop = bool((to_object or "").strip())
    has_stop_two = bool((to_object_two or "").strip())
    if has_stop_two and not has_stop:
        return error("'to_object_two' requires the first-side 'to_object' construction-plane stop.")
    if has_stop and (symmetric or second):
        return error("Construction-plane stops cannot be combined with symmetric or second_angle_deg.")
    if has_stop and op_key != "new":
        return error("Construction-plane stops currently require operation='new'; "
                     "use angle_deg without a stop for join, cut or intersect.")

    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")
    comp = target_component(design)

    sketch, requested, ambiguous = _sketch_detail.scoped_or_recent_sketch(
        design, sketch_name, component)
    if ambiguous:
        return error(ambiguous)
    if not sketch:
        if requested:
            names = _common.all_sketch_names(design)
            avail = f" Available: {', '.join(names)}." if names else ""
            return error(f"No sketch named '{requested}'.{avail} Use sketch_get or sketch_create.")
        return error("No sketch to revolve. Create one and draw a closed profile first.")

    profiles = safe(lambda: sketch.profiles)
    pcount = safe(lambda: profiles.count, 0) if profiles else 0
    # HANDLE path: a profile entityToken from sketch_get (a ProfileRef) targets the exact region -
    # the robust pick on a multi-profile / on-face sketch, where a blind index is ambiguous.
    if _inputs.is_handle(profile_index):
        profile, perr = _PROFILE.resolve(profile_index, component)
        if perr:
            return error(perr)
        idx = "handle"
    else:
        # The index path reads sketch.profiles directly, never through ProfileRef, so a deferred
        # sketch's pcount and item(idx) are both the pre-deferral ones.
        stale = _inputs.deferred_sketch_refusal("profile_index", sketch)
        if stale:
            return error(stale)
        if pcount == 0:
            return error(f"Sketch '{safe(lambda: sketch.name)}' has no closed profile to revolve.")
        try:
            if type(profile_index) is not int and not isinstance(profile_index, str):
                raise ValueError
            idx = int(profile_index)
        except (TypeError, ValueError):
            return error(f"profile_index {profile_index!r} is not an integer index. Use an index "
                         "from sketch_get or a profile handle.")
        if idx < 0 or idx >= pcount:
            return error(f"profile_index {idx} out of range - sketch has {pcount} profile(s).")
        profile = profiles.item(idx)

    # Host the feature on the sketch's OWNING component (see profile_host_component) and take origin
    # axes from that same component - a revolve input mixes contexts otherwise.
    host = _inputs.profile_host_component(profile, sketch, comp)
    axis_entity, axis_label = _axis_entity(design, host, sketch, axis)
    if not axis_entity:
        return error(f"Could not resolve axis '{axis}': {axis_label or 'use x | y | z, a straight-edge/sketch handle, or line:<index>.'}")

    stop_planes = []
    direction_hint = None
    if has_stop:
        plane_one, perr = _TO_OBJECT.resolve(to_object, host)
        if perr:
            return error(perr)
        if not isinstance(plane_one, adsk.fusion.ConstructionPlane):
            return error("'to_object' must resolve to a ConstructionPlane handle/name for revolve extent.")
        stop_planes.append(plane_one)
        if has_stop_two:
            plane_two, perr = _TO_OBJECT_TWO.resolve(to_object_two, host)
            if perr:
                return error(perr)
            if not isinstance(plane_two, adsk.fusion.ConstructionPlane):
                return error("'to_object_two' must resolve to a ConstructionPlane handle/name for revolve extent.")
            if plane_one == plane_two:
                return error("'to_object' and 'to_object_two' resolve to the same construction plane; provide two distinct stops.")
            stop_planes.append(plane_two)
            root = safe(lambda: design.rootComponent)
            operands = [axis_entity] + stop_planes
            if (root is None
                    or _common.same_component(safe(lambda: sketch.parentComponent), root) is not True
                    or safe(lambda: sketch.assemblyContext) is not None or any(
                    _common.same_component(_inputs.entity_component(entity), root) is not True
                    or safe(lambda entity=entity: entity.assemblyContext) is not None
                    for entity in operands)):
                return error("Construction-plane stops require native root-component geometry; "
                             "use angle extents for placed component geometry.")
        else:
            direction_hint, herr = _stop_direction_hint(sketch, profile, axis_entity, plane_one, design)
            if herr:
                return error(f"Could not establish the one-sided revolve direction hint: {herr}")
            if ang < 0:
                direction_hint = adsk.core.Vector3D.create(
                    -direction_hint.x, -direction_hint.y, -direction_hint.z)

    scoped_bodies = None
    if target_bodies not in (None, "", []):
        if op_key not in ("cut", "intersect"):
            return error("'target_bodies' only applies to cut/intersect operations.")
        scoped_bodies, berr = _TARGET_BODIES.resolve(target_bodies)
        if berr:
            return error(berr)

    op = getattr(adsk.fusion.FeatureOperations, _common.OPERATIONS[op_key])
    try:
        rev_input = host.features.revolveFeatures.createInput(profile, axis_entity, op)
    except Exception as e:
        return error(f"Could not start revolve: {e}. (The axis must not pass through the profile "
    "in a way that self-intersects.)")

    angle_val = adsk.core.ValueInput.createByReal(math.radians(ang))
    try:
        if has_stop_two:
            extent_result = rev_input.setTwoSideToExtent(stop_planes[0], stop_planes[1])
            if extent_result is not True:
                return error("Fusion refused the two construction-plane revolve stops; setTwoSideToExtent did not return true.")
        elif has_stop:
            extent_result = rev_input.setOneSideToExtent(stop_planes[0], direction_hint)
            if extent_result is not True:
                return error("Fusion refused the construction-plane revolve stop; setOneSideToExtent did not return true.")
        elif second and not symmetric:
            # asymmetric two-sided revolve: 'ang' one way, 'second' the other.
            second_val = adsk.core.ValueInput.createByReal(math.radians(second))
            if not rev_input.setTwoSideAngleExtent(angle_val, second_val):
                return error(f"Fusion refused a two-sided revolve extent ({angle_deg} / "
                             f"{second_angle_deg} deg), so nothing was revolved.")
        else:
            if not rev_input.setAngleExtent(bool(symmetric), angle_val):
                return error(f"Fusion refused a {'symmetric ' if symmetric else ''}revolve extent "
                             f"of {angle_deg} deg, so nothing was revolved.")
    except Exception as e:
        return error(f"Could not set revolve angle: {e}")

    if scoped_bodies is not None:
        try:
            rev_input.participantBodies = list(scoped_bodies)
        except Exception as e:
            return error(f"Could not set target_bodies before revolve: {e}")

    # cut/intersect MATERIAL evidence: the volumes the operation must move, sampled BEFORE the add.
    # A revolve reports a healthy feature for a profile that sweeps through empty air, so the feature
    # object alone cannot say material changed - only this before/after pair can.
    check_bodies = ((list(scoped_bodies) if scoped_bodies is not None else _cut_check_bodies(host))
                    if op_key in ("cut", "intersect") else [])
    vol_before = _geom.volumes(check_bodies)
    count_hosts = ([host] if check_bodies and scoped_bodies is None else
                   [safe(lambda b=b: b.parentComponent) for b in check_bodies])
    body_counts_before = [(c, _common.body_count(c)) for c in count_hosts if c is not None]
    # A join is told "grew a body" from "made a second one" by the host's body NAMES before the add.
    bodies_before = _common.component_body_names(host) if op_key == "join" else None

    try:
        feature = host.features.revolveFeatures.add(rev_input)
    except Exception as e:
        # No coplanarity claim: the API projects an axis that is not in the profile's plane ONTO that
        # plane, so out-of-plane is not itself a cause. A profile CROSSING the axis is.
        return error(f"Revolve failed: {e}. (A 'cut'/'intersect' needs existing geometry to act on. "
    "An axis outside the profile's plane is projected onto it, so that is not the cause; a profile "
    "that CROSSES the axis is refused.)")
    if not feature:
        return error(_common.no_feature_error(design, "Revolve"))
    feature_name = safe(lambda: feature.name)
    stop_face_counts = []
    if has_stop:
        result_bodies = _common.result_bodies(feature)
        if not result_bodies:
            return error(f"Revolve '{feature_name}' was created, but its result bodies could not be read; "
                         "the construction-plane stop effect is UNVERIFIED. "
                         + _common.failed_effect_remedy(design, feature))
        for stop_plane in stop_planes:
            face_count = _stop_plane_face_count(result_bodies, stop_plane)
            if face_count is None:
                return error(f"Revolve '{feature_name}' was created, but planar result faces could not be "
                             f"read against stop '{safe(lambda: stop_plane.name)}'; the stop-plane face "
                             "check is UNVERIFIED. " + _common.failed_effect_remedy(design, feature))
            if face_count == 0:
                return error(f"Revolve '{feature_name}' was created, but no planar result face lies on stop '{safe(lambda: stop_plane.name)}'; the requested stop effect is unverified. Retire it with design_delete_feature.")
            stop_face_counts.append(face_count)

    volume_delta_cm3 = None
    body_count_changed = False
    if check_bodies:
        delta, readable = _geom.volume_delta(check_bodies, vol_before)
        count_changes = [(before, _common.body_count(c)) for c, before in body_counts_before]
        body_count_changed = any(before is not None and after is not None and before != after
                                 for before, after in count_changes)
        # A body whose volume read BEFORE and reads unreadable now was consumed whole - a real effect
        # that contributes no delta, so it must not be counted as "nothing moved".
        consumed = [b for b in check_bodies
                    if vol_before.get(id(b)) is not None and _geom.signed_volume(b) is None]
        if readable and not body_count_changed:
            volume_delta_cm3 = round(delta, 6)
        if (readable and not consumed and not body_count_changed
                and abs(delta) < _common.NO_VOLUME_CHANGE_CM3):
            where = safe(lambda: host.name) or "the host component"
            return error(f"Revolve reported success but this {op_key} changed nothing - every solid "
                         f"body in '{where}' measures the volume it had before and none was "
                         "consumed, so the revolved shape does not overlap any of them. Check that "
                         "the profile and axis put the swept solid inside the target body (an "
                         "'intersect' whose target lies entirely INSIDE the swept solid also reads "
                         "this way). " + _common.failed_effect_remedy(design, feature))

    body_names = [f["name"] for f in _common.body_facts(_common.result_bodies(feature))]

    note = "Profile revolved into a solid. Pair with view_screenshot (iso) to view it."
    if scoped_bodies is not None:
        note += (" 'scoped_to_bodies' lists the configured participant bodies; Fusion does not "
                 "expose a readback for this input.")
    elif op_key in ("cut", "intersect"):
        note += " With no target_bodies, Fusion considers every intersected body."
    if body_count_changed:
        note += (" The body count changed, so volume_delta_cm3 is omitted; held-body volumes do "
                 "not describe the resulting body set.")
    if op_key == "new":
        adv = root_body_advisory(design, host)
        if adv:
            note += " " + adv
    join_clause = _common.join_new_body_clause(op_key, bodies_before, body_names)
    if join_clause:
        note += " " + join_clause

    # A symmetric angle extent spans its angle on EACH side (measured: a symmetric 89.4 deg
    # revolve adds the area of a one-sided 178.8 deg one). A two-sided extent has no single angle.
    one_extent = not has_stop and (symmetric or not second)
    extent = safe(lambda: feature.extentDefinition) if one_extent else None
    landed = _common.measured(lambda: extent.angle.value, 180.0 / math.pi) if one_extent else None
    landed_sym = _common.read_flag(lambda: extent.isSymmetric) if one_extent else None
    payload = {
        "revolved": True,
        "feature": feature_name,
        "operation": op_key,
        "sketch": safe(lambda: sketch.name),
        "component": safe(lambda: feature.parentComponent.name),
        "profile_index": idx,
        "axis": axis_label,
        "result_bodies": body_names,
        "note": note,
    }
    if not has_stop:
        payload["angle_deg"] = landed if landed is not None else round(ang, 6)
        payload["second_angle_deg"] = round(float(second_angle_deg or 0.0), 6)
        payload["symmetric"] = landed_sym if landed_sym is not None else bool(symmetric)
    else:
        payload["extent"] = "two_side_to_object" if has_stop_two else "to_object"
        payload["stops"] = [safe(lambda p=p: p.name) for p in stop_planes]
        payload["stop_plane_result_face_counts"] = stop_face_counts
    if landed_sym and landed is not None:
        payload["total_angle_deg"] = round(2 * landed, 6)
    unread = [k for k, v in (("angle_deg", landed), ("symmetric", landed_sym)) if one_extent and v is None]
    if unread:
        payload["unverified"] = unread
    if scoped_bodies is not None:
        payload["scoped_to_bodies"] = [_inputs.qualified_body_name(b) for b in scoped_bodies]
    # Absent, never null: a null would read as "no material moved".
    if volume_delta_cm3 is not None:
        payload["volume_delta_cm3"] = volume_delta_cm3
    return ok(payload)


TOOL_DESCRIPTION = (
"Revolve a sketch profile about an axis; it must not cross the axis."
)

revolve_tool = (
    Tool.create_simple(name="model_revolve", description=TOOL_DESCRIPTION)
    .add_input_property("sketch_name", {"type": "string"})
    .add_input_property("profile_index", {"type": ["integer", "string"],
            "description": "An index (default 0), or a profile 'handle'."})
    .add_input_property("axis", {"type": "string",
            "description": _AXIS.schema()["description"] + " Or 'line:<i>' for a line in the "
            "profile's sketch."})
    .add_input_property("angle_deg", {"type": "number", "default": 360.0,
            "description": "With a stop, only angle_deg's sign chooses travel direction."})
    .add_input_property("second_angle_deg", {"type": "number"})
    .add_input_property("target_bodies", _TARGET_BODIES.schema())
    .add_input_property(*_inputs.boolean_op(default="new", description="").as_property())
    .add_input_property(*_sketch_detail.COMPONENT_SCOPE)
    .add_input_property("symmetric", {"type": "boolean", "description": "angle_deg is per side."})
    .add_input_property("to_object", {"type": "string",
            "description": "Root new-body stop: construction-plane handle."})
    .add_input_property("to_object_two", {"type": "string",
            "description": "Side-two construction-plane stop handle; two-sided only."})
    .strict_schema()
)
revolve_item = Item.create_tool_item(tool=revolve_tool, write="write", handler=handler, run_on_main_thread=True,
                                     postconditions=[_assert.FeatureHealthy()],
                                     verification=Verification(
                                         kind="inline", rung="geometry",
                                         evidence_test="tests/unit/test_model_revolve.py"
                                         "::TestCutMovesMaterial"
                                         "::test_cut_that_moves_no_volume_is_an_error"))


def register_tool():
    register(revolve_item)
