# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Sweep a profile or solid tool body along a path."""

import math

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe, target_component, root_body_advisory, build_path
from . import _common
from . import _design_common
from . import _edit_feature_common
from . import _geom
from . import _inputs
from . import _outputs
from . import _sketch_detail
from . import _sweep_common
from . import _surface_common

app = adsk.core.Application.get()

# scope_input: the {sketch, profile_index} form addresses a sketch BY NAME, and Fusion numbers
# sketches per component from 1, so a name two components carry is refused, naming 'component'.
_TARGET_BODIES = _inputs.BodyRefList("target_bodies", required=False)
_SOLID_BODY = _inputs.BodyRef("solid_body", kind="solid")
_SOLID_ALIGNED_AXIS = _inputs.AxisRef("solid_aligned_axis", entity_only=True)

# orientation keyword -> adsk.fusion.SweepOrientationTypes attribute.
_ORIENTATIONS = {
    "perpendicular": "PerpendicularOrientationType",
    "parallel": "ParallelOrientationType",
}
_SOLID_ORIENTATIONS = {
    "perpendicular": "PerpendicularSolidOrientationType",
    "rigid": "RigidSolidOrientationType",
    "aligned": "AlignedSolidOrientationType",
}

RETURNS = [
    _outputs.ReturnsValue("result_bodies", "the names of the bodies the sweep created/modified"),
    _outputs.ReturnsValue("is_solid", "whether the sweep produced a SOLID (vs an open surface)"),
    _outputs.ReturnsValue("path_curves", "how many curves the built path actually holds"),
]


def _cut_check_bodies(comp):
    """The solid bodies an UNSCOPED cut/intersect sweep can act on: every solid directly in the
    feature's host component, resolved once so the same objects are re-read afterwards."""
    return [b for b in _common.iter_collection(safe(lambda: comp.bRepBodies))
            if safe(lambda b=b: b.isSolid)]


def _host_body_keys(host):
    """Return native body keys and fresh bodies, or None when the census is unreadable."""
    coll = safe(lambda: host.bRepBodies)
    count = _common.counted(lambda: coll.count)
    if count is None:
        return None
    found = {}
    for i in range(count):
        body = safe(lambda i=i: coll.item(i))
        key = _common.native_identity(body)
        if key is None or key in found:
            return None
        found[key] = body
    return found


def _solid_sweep(design, solid_body, path, op_key, orient_key, as_surface,
                 target_bodies, component, solid_aligned_axis):
    """Sweep one solid body on an owner-local path, retaining its source."""
    if op_key not in ("new", "new_body"):
        return error("'solid_body' supports operation='new' only.")
    if orient_key not in _SOLID_ORIENTATIONS:
        return error("'solid_body' orientation must be perpendicular, rigid, or aligned.")
    if orient_key == "aligned" and not solid_aligned_axis:
        return error("'solid_aligned_axis' is required when 'solid_body' uses orientation='aligned'.")
    if orient_key != "aligned" and solid_aligned_axis not in (None, "", []):
        return error("'solid_aligned_axis' applies only when 'solid_body' uses orientation='aligned'.")
    if as_surface:
        return error("'solid_body' makes a solid; omit as_surface or set it false.")
    if target_bodies not in (None, "", []):
        return error("'target_bodies' applies to profile cut/join/intersect, not solid_body new.")
    if not isinstance(path, str) or not path.strip().lower().startswith("sketch:"):
        return error("'solid_body' needs an owner-local 'sketch:<name>' path; draw the path "
                     "in the body's component.")
    path_name = path.split(":", 1)[1].strip()
    if not path_name:
        return error("'path' needs a sketch name after 'sketch:'.")

    scope = None
    if component:
        scope, serr = _inputs._body_scope(design, component, "component")
        if serr:
            return error(serr)
    body, berr = _SOLID_BODY.resolve(solid_body, scope=scope)
    if berr:
        return error(berr)
    unread = object()
    context = safe(lambda: body.assemblyContext, unread)
    if context is unread:
        return error("'solid_body' has no readable assembly context; reacquire its body handle.")
    if context is not None and safe(lambda: body.nativeObject) is None:
        return error("'solid_body' proxy has no native body; reacquire its body handle.")
    source = _common._native_of(body)
    host = safe(lambda: source.parentComponent)
    if (host is None or _common.same_component(
            safe(lambda: host.parentDesign.rootComponent), safe(lambda: design.rootComponent))
            is not True):
        return error("'solid_body' must belong to this design's native component, not a linked source.")
    if context is not None and _common.same_component(safe(lambda: context.component), host) is not True:
        return error("'solid_body' proxy context does not match its native owner or could not be "
                     "read; reacquire a body handle from that component.")
    if scope is not None:
        scoped_host = safe(lambda: scope[0].component) or scope[0]
        if _common.same_component(scoped_host, host) is not True:
            return error(f"'component' '{component}' does not own 'solid_body'. Use its owner "
                         "or omit component and pass a body handle.")
    if safe(lambda: source.isSolid) is not True:
        return error("'solid_body' is not a readable closed solid; choose a solid body handle.")
    aligned_axis = None
    aligned_axis_key = None
    if orient_key == "aligned":
        axis, aerr = _SOLID_ALIGNED_AXIS.resolve(solid_aligned_axis, component=host)
        if aerr:
            return error(aerr)
        if not isinstance(axis, tuple) or len(axis) != 2 or axis[0] != "edge":
            return error("'solid_aligned_axis' must resolve to a linear edge, sketch line, or construction axis.")
        aligned_axis = axis[1]
        axis_owner = _inputs.entity_component(aligned_axis)
        if _common.same_component(axis_owner, host) is not True:
            return error("'solid_aligned_axis' must belong to the solid body's owner component.")
        aligned_axis_key = _common.native_identity(aligned_axis)
        if aligned_axis_key is None:
            return error("'solid_aligned_axis' identity is unreadable; reacquire the axis handle.")
    source_key = _common.native_identity(source)
    source_shape = _geom.body_shape(source)
    source_name = safe(lambda: source.name)
    before = _host_body_keys(host)
    if source_key is None or source_shape is None or before is None or source_key not in before:
        return error("'solid_body' identity or shape is unreadable in its owner; no sweep was made.")
    named = [sk for sk in _common.iter_collection(safe(lambda: host.sketches))
             if safe(lambda sk=sk: sk.name) == path_name]
    if len(named) != 1:
        return error(f"'path' sketch '{path_name}' must name exactly one sketch in the "
                     f"solid body's component; found {len(named)}.")
    left = []
    sweep_path, path_label, patherr = build_path(host, path, left_out=left)
    if patherr:
        return error(patherr)
    path_curves = _common.counted(lambda: sweep_path.count)
    if path_curves is None or path_curves < 1:
        return error("The solid sweep path has no readable curves; draw one connected path.")
    sketch_curves = _common.path_sketch_curve_count(host, path)
    sweeps = host.features.sweepFeatures
    op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    try:
        sweep_input = sweeps.createInputForSolid(source, sweep_path, op)
    except Exception as exc:
        return error(f"Could not start solid-body sweep: {exc}")
    if sweep_input is None or _common.native_identity(safe(lambda: sweep_input.solidBody)) != source_key:
        return error("Solid sweep input did not retain the requested tool body; no sweep was made.")
    setter_results = {}
    want_orientation = safe(lambda: getattr(
        adsk.fusion.SweepSolidOrientationTypes, _SOLID_ORIENTATIONS[orient_key]))
    if want_orientation is None:
        return error(f"Solid orientation '{orient_key}' is unavailable in this build; no sweep was made.")
    if (orient_key == "perpendicular"
            and safe(lambda: sweep_input.solidOrientation) != want_orientation):
        return error("Solid sweep input did not retain perpendicular orientation; no sweep was made.")
    try:
        if orient_key == "aligned":
            setter_results["solidAlignedAxis"] = sweep_input._set_solidAlignedAxis(aligned_axis)
            if setter_results["solidAlignedAxis"] is not True:
                return error("Solid sweep input refused 'solid_aligned_axis'; no sweep was made.")
            if _common.native_identity(safe(lambda: sweep_input.solidAlignedAxis)) != aligned_axis_key:
                return error("Solid sweep input did not retain 'solid_aligned_axis'; no sweep was made.")
        setter_results["solidOrientation"] = sweep_input._set_solidOrientation(want_orientation)
        if setter_results["solidOrientation"] is not True:
            return error(f"Solid sweep input refused orientation='{orient_key}'; no sweep was made.")
    except Exception as exc:
        return error(f"Could not configure solid orientation '{orient_key}': {exc}")
    if safe(lambda: sweep_input.solidOrientation) != want_orientation:
        return error(f"Solid sweep input did not retain '{orient_key}' orientation; no sweep was made.")
    before_timeline = _design_common.timeline_census(design)
    before_marker, _ = _common.timeline_marker(design)
    before_shapes = _edit_feature_common.all_shapes(design, components=[host])
    path_visibility_restore = _edit_feature_common.path_sketch_visibility_restore(host, path)
    try:
        feature = sweeps.add(sweep_input)
    except Exception as exc:
        return error(f"Solid-body sweep failed: {exc}")
    if feature is None:
        return error(_common.no_feature_error(design, "Solid sweep"))

    after = _host_body_keys(host)
    created, face_count, readable = _surface_common._created_bodies(feature)
    created_keys = {_common.native_identity(b) for b in created}
    new_keys = set(after or ()) - set(before)
    if (after is None or not readable or face_count < 1 or None in created_keys
            or len(new_keys) != 1 or created_keys != new_keys):
        unchanged = (after is not None and set(after) == set(before)
                     and _common.counted(lambda: feature.faces.count) == 0)
        remedy = _edit_feature_common.retire_failed_create(
            design, feature, before_timeline, before_shapes if unchanged else None, [host], before_marker,
            restore_input_visibility=path_visibility_restore)
        return error("Solid sweep was built, but its new result body could not be identified "
                     "from created faces and the owner's body census. "
                     + remedy)
    key = next(iter(new_keys))
    feature_keys = {_common.native_identity(b) for b in _common.result_bodies(feature)}
    result = after[key]
    result_shape = _geom.body_shape(result)
    if key not in feature_keys or result_shape is None or result_shape["solid"] is not True \
            or result_shape["volume_cm3"] <= 0 or result_shape == source_shape:
        return error("Solid sweep was built, but its result is not a verified new solid body. "
                     + _common.failed_effect_remedy(design, feature))
    if source_key not in after or _geom.body_shape(after[source_key]) != source_shape:
        return error("Solid sweep was built, but its source tool body's geometry was not retained. "
                     + _common.failed_effect_remedy(design, feature))
    health = safe(lambda: feature.healthState)
    states = adsk.fusion.FeatureHealthStates
    if health not in (states.HealthyFeatureHealthState, states.WarningFeatureHealthState):
        return error("Solid sweep was built, but feature health is unreadable or failed. "
                     + _common.failed_effect_remedy(design, feature))
    if safe(lambda: feature.solidOrientation) != want_orientation:
        return error(f"Solid sweep was built, but its {orient_key} orientation did not persist. "
                     + _common.failed_effect_remedy(design, feature))
    if orient_key == "aligned":
        if _common.native_identity(safe(lambda: feature.solidAlignedAxis)) != aligned_axis_key:
            return error("Solid sweep was built, but its aligned axis did not persist. "
                         + _common.failed_effect_remedy(design, feature))
    result_name = safe(lambda: result.name)
    if not result_name:
        return error("Solid sweep was built, but the new result body has no readable name. "
                     + _common.failed_effect_remedy(design, feature))
    note = "Solid body swept into a new result; its source tool body retains its geometry."
    if health == states.WarningFeatureHealthState:
        note += " Feature warning: " + str(safe(lambda: feature.errorOrWarningMessage) or "details unreadable") + "."
    warning = _common.path_chain_warning(path_curves, sketch_curves, "sweep", left)
    if warning:
        note += " " + warning
    return ok({"swept": True, "feature": safe(lambda: feature.name),
               "operation": op_key, "component": safe(lambda: host.name),
               "path": path_label, "path_curves": path_curves,
               "path_sketch_curves": sketch_curves, "orientation": orient_key,
               "as_surface": False, "open_profile": False, "is_solid": True,
               "solid_body": source_name, "source_retained": True,
               "result_bodies": [result_name], "solid_input_setters": setter_results,
               "note": note})


def _finite_control(value, name):
    """(finite float or None, error) for an optional numeric sweep control."""
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None, f"'{name}' must be a finite number - got {value!r}."
    return float(value), None


def _sweep_value_matches(value, expected, *, string=False):
    """Whether a ValueInput readback retains the requested real or unit-bearing string."""
    if value is None:
        return False
    if string:
        return safe(lambda: value.stringValue) == expected
    got = safe(lambda: value.realValue)
    return isinstance(got, (int, float)) and not isinstance(got, bool) and abs(got - expected) <= 1e-12


def _sweep_path_identity(path):
    """Ordered native identities of a built Path's member entities, or None."""
    count = _common.counted(lambda: path.count)
    if count is None or count < 1:
        return None
    keys = [_common.native_identity(safe(lambda i=i: path.item(i).entity)) for i in range(count)]
    return tuple(keys) if all(keys) else None


def _feature_parameter_value(feature, name):
    """(ModelParameter value, expression) for one sweep definition parameter."""
    parameter = getattr(feature, name)
    if parameter is None:
        raise RuntimeError(f"the retained '{name}' parameter answered nothing")
    value = parameter.value
    expression = parameter.expression
    if value is None or expression is None:
        raise RuntimeError(f"the retained '{name}' value or expression answered nothing")
    return value, expression


def handler(profile=None, path=None, operation: str = "new", orientation: str = "perpendicular",
            as_surface: bool = False, target_bodies=None, component: str = "",
            solid_body=None, solid_aligned_axis=None, guide_path=None, twist_deg=None,
            taper_deg=None, path_fraction=None) -> dict:
    """See TOOL_DESCRIPTION."""
    op_key = (operation or "new").strip().lower()
    if op_key not in _common.OPERATIONS:
        return error(f"Unknown operation '{operation}'. Use: new, join, cut, intersect.")
    orient_key = (orientation or "perpendicular").strip().lower()
    if orient_key not in set(_ORIENTATIONS) | set(_SOLID_ORIENTATIONS):
        return error(f"Unknown orientation '{orientation}'. Use: perpendicular, parallel, rigid, aligned.")

    twist, err = _finite_control(twist_deg, "twist_deg")
    if err:
        return error(err)
    taper, err = _finite_control(taper_deg, "taper_deg")
    if err:
        return error(err)
    fraction, err = _finite_control(path_fraction, "path_fraction")
    if err:
        return error(err)
    if fraction is not None and not 0.0 <= fraction <= 1.0:
        return error(f"'path_fraction' must be from 0 through 1 - got {fraction}.")
    controls_requested = any(v is not None for v in (twist, taper, fraction))

    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")
    if solid_body not in (None, "", []):
        if profile not in (None, "", []):
            return error("Choose 'profile' or 'solid_body', not both.")
        if guide_path not in (None, "", []) or controls_requested:
            return error("'guide_path', 'twist_deg', 'taper_deg', and 'path_fraction' are profile controls; omit them with 'solid_body'.")
        return _solid_sweep(design, solid_body, path, op_key, orient_key, as_surface,
                            target_bodies, component, solid_aligned_axis)
    if orient_key not in _ORIENTATIONS:
        return error(f"Profile orientation must be perpendicular or parallel - got '{orientation}'.")
    if solid_aligned_axis not in (None, "", []):
        return error("'solid_aligned_axis' applies only to 'solid_body' with orientation='aligned'.")
    if guide_path not in (None, "", []) and controls_requested:
        return error("'twist_deg', 'taper_deg', and 'path_fraction' exclude 'guide_path'. Omit them or sweep without a guide rail.")
    comp = target_component(design)

    profile_arg, want_solid, open_profile, host, _source_sketch, perr = _sweep_common.resolve_profile(
        design, comp, profile, as_surface, component)
    if perr:
        return error(perr)

    # Build the path AND the feature on the profile's OWNING component (host) - a profile-consuming
    # feature created on the active component raises bSet when the profile is owned elsewhere.
    left = []
    sweep_path, path_label, patherr = build_path(host, path, left_out=left)
    if patherr:
        return error(patherr)
    # What the built Path HOLDS, beside what the request named: the profile is driven over these
    # curves and no others, so a chain that stopped short sweeps a stub of the intended run.
    path_curves = _common.counted(lambda: sweep_path.count)
    sketch_curves = _common.path_sketch_curve_count(host, path)
    guide_sweep_path = None
    guide_path_curves = None
    guide_label = None
    if guide_path not in (None, "", []):
        guide_left = []
        guide_sweep_path, guide_label, guide_err = build_path(host, guide_path, left_out=guide_left)
        if guide_err:
            return error(f"Could not build 'guide_path': {guide_err}")
        guide_path_curves = _common.counted(lambda: guide_sweep_path.count)
        if guide_path_curves is None or guide_path_curves < 1:
            return error("'guide_path' has no readable curves; pass a connected path in the profile's owner component.")
        if guide_left:
            return error("'guide_path' contains curves Fusion left out; pass the complete connected guide chain.")

    op = getattr(adsk.fusion.FeatureOperations, _common.OPERATIONS[op_key])
    try:
        sweep_input = host.features.sweepFeatures.createInput(profile_arg, sweep_path, op)
    except Exception as e:
        return error(f"Could not start sweep: {e}. (The path must geometrically connect and the "
                     "profile should sit on/near the path start.)")

    setter_results = {}
    try:
        setter_results["isSolid"] = sweep_input._set_isSolid(bool(want_solid))
        if setter_results["isSolid"] is not True:
            return error(f"Sweep input refused isSolid={bool(want_solid)}; no sweep was made.")
        orient_value = getattr(adsk.fusion.SweepOrientationTypes, _ORIENTATIONS[orient_key])
        setter_results["orientation"] = sweep_input._set_orientation(orient_value)
        if setter_results["orientation"] is not True:
            return error(f"Sweep input refused orientation='{orient_key}'; no sweep was made.")
        if safe(lambda: sweep_input.orientation) != orient_value:
            return error(f"Sweep input did not retain orientation='{orient_key}'; no sweep was made.")
        if guide_sweep_path is not None:
            setter_results["guideRail"] = sweep_input._set_guideRail(guide_sweep_path)
            if setter_results["guideRail"] is not True:
                return error("Sweep input refused 'guide_path'; no sweep was made.")
            if safe(lambda: sweep_input.guideRail) is None:
                return error("Sweep input did not retain 'guide_path'; no sweep was made.")
        for prop, value in (("twistAngle", twist), ("taperAngle", taper)):
            if value is None:
                continue
            expression = f"{value!r} deg"
            setter_results[prop] = getattr(sweep_input, "_set_" + prop)(
                adsk.core.ValueInput.createByString(expression))
            if setter_results[prop] is not True:
                return error(f"Sweep input refused '{prop}'={expression}; no sweep was made.")
            if not _sweep_value_matches(safe(lambda p=prop: getattr(sweep_input, p)), expression,
                                        string=True):
                return error(f"Sweep input did not retain '{prop}' as {expression}; no sweep was made.")
        if fraction is not None:
            setter_results["distanceOne"] = sweep_input._set_distanceOne(
                adsk.core.ValueInput.createByReal(fraction))
            if setter_results["distanceOne"] is not True:
                return error(f"Sweep input refused 'path_fraction'={fraction}; no sweep was made.")
            if not _sweep_value_matches(safe(lambda: sweep_input.distanceOne), fraction):
                return error(f"Sweep input did not retain 'path_fraction' as {fraction}; no sweep was made.")
    except Exception as e:
        return error(f"Could not configure the sweep: {e}")

    # target_bodies: scope a cut/intersect to specific bodies so it can't bleed through others.
    scoped_to = None
    bodies_ents = None
    if target_bodies not in (None, "", []):
        if op_key == "new":
            return error("'target_bodies' only applies to cut/join/intersect (a 'new' body has no "
                         "participants). Remove it, or change the operation.")
        bodies_ents, berr = _TARGET_BODIES.resolve(target_bodies)
        if berr:
            return error(berr)
        try:
            sweep_input.participantBodies = list(bodies_ents)
            scoped_to = [safe(lambda b=b: b.name) for b in bodies_ents]
        except Exception as e:
            return error(f"Could not scope to target_bodies: {e}")

    # cut/intersect MATERIAL evidence: the volumes the operation must move, sampled BEFORE the add.
    # A sweep along a path that misses the body reports a healthy feature and result bodies just the
    # same, so only this before/after pair can say material actually changed.
    check_bodies = []
    if op_key in ("cut", "intersect"):
        check_bodies = list(bodies_ents) if bodies_ents else _cut_check_bodies(host)
    vol_before = _geom.volumes(check_bodies)
    # A join is told "grew a body" from "made a second one" by the host's body NAMES before the add.
    bodies_before = _common.component_body_names(host) if op_key == "join" else None

    try:
        feature = host.features.sweepFeatures.add(sweep_input)
    except Exception as e:
        return error(f"Sweep failed: {e}. (A 'cut'/'intersect' needs existing geometry to act on; "
                     "the profile and path must form a valid sweep.)")
    if not feature:
        return error(_common.no_feature_error(design, "Sweep"))

    feature_identity = safe(lambda: feature.name) or safe(lambda: feature.entityToken)
    body_names = [f["name"] for f in _common.body_facts(_common.result_bodies(feature))]

    requested_parameters = [("twistAngle", twist, True), ("taperAngle", taper, True),
                            ("distanceOne", fraction, False)]
    requested_parameters = [row for row in requested_parameters if row[1] is not None]
    retained_parameters = {}
    if requested_parameters:
        parameter_read_error = []

        def read_requested_parameters():
            try:
                return {prop: _feature_parameter_value(feature, prop)
                        for prop, _, _ in requested_parameters}
            except Exception as exc:
                parameter_read_error.append(str(exc) or type(exc).__name__)
                return None

        try:
            retained_parameters, marker_clause = _common.rolled_to(
                design, feature, read_requested_parameters,
                f"sweep feature '{feature_identity}' parameters")
        except Exception as exc:
            return error(f"Sweep '{feature_identity}' was built, but its retained parameters could "
                         f"not be read: {exc}. "
                         + _common.failed_effect_remedy(design, feature))
        if marker_clause:
            return error(f"Sweep '{feature_identity}' was built, but its retained parameters could "
                         f"not be verified: {marker_clause}. "
                         + _common.failed_effect_remedy(design, feature))
        if parameter_read_error:
            return error(f"Sweep '{feature_identity}' was built, but a requested retained parameter "
                         f"could not be read: {parameter_read_error[0]}. "
                         + _common.failed_effect_remedy(design, feature))
        if retained_parameters is None:
            return error(f"Sweep '{feature_identity}' was built, but its timeline row could not be "
                         "read for parameter verification. "
                         + _common.failed_effect_remedy(design, feature))

    sweep_parameters = {}
    for prop, requested_value, angle in requested_parameters:
        got, expression = retained_parameters[prop]
        wanted = math.radians(requested_value) if angle else requested_value
        matches = (isinstance(got, (int, float)) and not isinstance(got, bool)
                   and math.isfinite(got) and abs(got - wanted) <= 1e-8)
        sweep_parameters[prop] = {"value": got, "value_units": "rad" if angle else "fraction",
                                  "expression": expression,
                                  "requested": requested_value,
                                  "matches": matches if got is not None else None}
        if got is not None and not matches:
            return error(f"Sweep was built, but its '{prop}' parameter reads {got!r}; "
                         f"requested {requested_value}. "
                         + _common.failed_effect_remedy(design, feature))
    guide_path_verified = None
    if guide_sweep_path is not None:
        got_path, marker_clause = _common.rolled_to(
            design, feature, lambda: safe(lambda: feature.guideRail), "sweep guide rail")
        want_members, got_members = (_sweep_path_identity(guide_sweep_path),
                                     _sweep_path_identity(got_path) if got_path is not None else None)
        if marker_clause:
            detail = marker_clause
            return error("Sweep was built, but its guideRail did not verify: " + detail + ". "
                         + _common.failed_effect_remedy(design, feature))
        if want_members is not None and got_members is not None:
            if got_members != want_members:
                return error("Sweep was built, but its guideRail member identities differ from the "
                             "requested path. " + _common.failed_effect_remedy(design, feature))
            guide_path_verified = True
        else:
            guide_path_verified = False

    # An operation that reports success but produced no body is a silent no-op - fail it honestly.
    if op_key == "new" and not body_names:
        made = _common.counted(lambda: feature.bodies.count)
        return error(("Sweep reported success but created no body." if made == 0 else
                      "Sweep reported success but its result bodies did not read.")
                     + " Check that the profile sits on the path and the path forms a valid, "
                     "connected sweep. " + _common.failed_effect_remedy(design, feature))

    volume_delta_cm3 = None
    if check_bodies:
        delta, readable = _geom.volume_delta(check_bodies, vol_before)
        # A body whose volume read BEFORE and reads unreadable now was consumed whole - a real effect
        # that contributes no delta, so it must not be counted as "nothing moved".
        consumed = [b for b in check_bodies
                    if vol_before.get(id(b)) is not None and _geom.signed_volume(b) is None]
        if readable:
            volume_delta_cm3 = round(delta, 6)
        if readable and not consumed and abs(delta) < _common.NO_VOLUME_CHANGE_CM3:
            if scoped_to:
                # SCOPED: only a participant body can be affected, and every one of them measures
                # what it did before - nothing landed anywhere, so the feature is safe to remove.
                named = ", ".join(n for n in scoped_to if n) or "the scoped bodies"
                return error(f"Sweep reported success but this {op_key} changed nothing - "
                             f"{named} measure the volumes they had before and none was consumed, so "
                             "the profile does not sweep through any of them. A cut/intersect can "
                             "only affect bodies named in 'target_bodies' - check the path runs "
                             "through them. " + _common.delete_failed_feature(design, feature)[1])
            where = safe(lambda: host.name) or "the host component"
            return error(f"Sweep reported success but this {op_key} changed nothing - every solid "
                         f"body in '{where}' measures the volume it had before and none was "
                         "consumed, so the swept profile does not overlap any of them. Check the "
                         "path runs through the target body (an 'intersect' whose target lies "
                         "entirely INSIDE the swept solid also reads this way). "
                         + _common.failed_effect_remedy(design, feature))

    # SOLID/SURFACE verdict read BACK off the feature - never assumed from the request.
    is_solid = safe(lambda: feature.isSolid)
    if open_profile or is_solid is False:
        note = ("Swept into a SURFACE (no end caps) - pair with model_stitch to close several "
                "surfaces into a solid.")
    else:
        note = "Profile swept into a solid along the path. Pair with view_screenshot (iso) to view it."
    if op_key == "new":
        adv = root_body_advisory(design, host)
        if adv:
            note += " " + adv
    join_clause = _common.join_new_body_clause(op_key, bodies_before, body_names)
    if join_clause:
        note += " " + join_clause
    warning = _common.path_chain_warning(path_curves, sketch_curves, "sweep", left)
    if warning:
        note += " " + warning

    payload = {
        "swept": True,
        "feature": safe(lambda: feature.name),
        "operation": op_key,
        "component": safe(lambda: feature.parentComponent.name),
        "path": path_label,
        "path_curves": path_curves,
        "guide_path": guide_label,
        "guide_path_curves": guide_path_curves,
        "sweep_input_setters": setter_results,
        "orientation": orient_key,
        "as_surface": bool(open_profile or is_solid is False),
        "open_profile": bool(open_profile),
        "is_solid": is_solid,
        "scoped_to_bodies": scoped_to,
        "result_bodies": body_names,
        "sweep_parameters": sweep_parameters,
        "note": note,
    }
    # Only a 'sketch:<name>' path has a source curve count; a null would read as an unreadable sketch.
    if sketch_curves is not None:
        payload["path_sketch_curves"] = sketch_curves
    if guide_sweep_path is not None:
        payload["guide_path_verified"] = guide_path_verified
    # Absent, never null: a null would read as "no material moved".
    if volume_delta_cm3 is not None:
        payload["volume_delta_cm3"] = volume_delta_cm3
    return ok(payload)


TOOL_DESCRIPTION = (
"Sweep. Solid rigid/aligned. Produces result_bodies, is_solid, path_curves."
)

sweep_tool = (
    Tool.create_simple(name="model_sweep", description=TOOL_DESCRIPTION)
    .add_input_property("profile", {"type": ["string", "object"]})
    .add_input_property("solid_body", {**_SOLID_BODY.schema(), "description": "SOLID body handle/name."})
    .add_input_property("path", {"type": ["string", "array"], "items": {"type": "string"},
            "description": "Edge handle: TANGENT connections only; 'path' count is the truth. Or 'sketch:<name>'."})
    .add_input_property(*_inputs.boolean_op(default="new", description="").as_property())
    .add_input_property("orientation", {"type": "string", "enum": ["perpendicular", "parallel", "rigid", "aligned"],
            "description": "Profile perpendicular/parallel; solid perpendicular/rigid/aligned.",
            "default": "perpendicular"})
    .add_input_property("as_surface", {"type": "boolean"})
    .add_input_property("target_bodies", {**_TARGET_BODIES.schema(), "description": "Body handles/names."})
    .add_input_property(*_sketch_detail.COMPONENT_SCOPE)
    .add_input_property("solid_aligned_axis", {**_SOLID_ALIGNED_AXIS.schema(),
            "description": "Aligned: linear edge, sketch line or construction axis handle."})
    .add_input_property("guide_path", {"type": ["string", "array"], "items": {"type": "string"},
            "description": "Connected edge handle/chain or sketch:<name>."})
    .add_input_property("twist_deg", {"type": "number", "description": "Profile twist (deg)."})
    .add_input_property("taper_deg", {"type": "number", "description": "Profile taper (deg): positive expands, negative contracts."})
    .add_input_property("path_fraction", {"type": "number", "minimum": 0, "maximum": 1,
            "description": "One-sided fraction; no guide/solid."})
    .strict_schema()
)
sweep_item = Item.create_tool_item(
    tool=sweep_tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline",
        rung="geometry",
        evidence_test="tests/unit/test_model_sweep.py::TestCutMovesMaterial"
                      "::test_unscoped_cut_that_moves_no_volume_is_an_error"))


def register_tool():
    register(sweep_item)
