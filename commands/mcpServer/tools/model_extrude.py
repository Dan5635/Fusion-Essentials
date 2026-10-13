# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: extrude a sketch profile into a solid (the back half of the modelling flow).

  extrude -> turn a closed sketch profile into a 3D body by extruding it a distance, or up to a
             face. Choose the operation, distance/taper, and optional surface (no end caps). WRITES.
             Companion to sketch_create / sketch_add_geometry.
"""

import math

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe, scale, target_component, root_body_advisory
from . import _common
from . import _geom
from . import _inputs
from . import _sketch_detail
from . import _assert

app = adsk.core.Application.get()

# to_object: an existing face/body stop handle; faces keep the original route.
_TO_OBJECT = _inputs.GeometryHandle("to_object", require="any", required=False)
_START_OBJECT = _inputs.PlaneRef("start_object", required=False)
# target_bodies: scope a cut/join/intersect to these bodies so it doesn't bleed through others.
_TARGET_BODIES = _inputs.BodyRefList("target_bodies", required=False)

# extent: the depth STYLE. 'distance' is the legacy default (distance/symmetric/taper_deg); the other
# three map to measured ExtrudeFeatureInput setters, each reading its own inputs below.
_EXTENTS = ("distance", "through_all", "to_face", "two_side")
_EXTENT = _inputs.Choice("extent", _EXTENTS, default="distance")

# profile_index may carry a profile HANDLE (entityToken from sketch_get) - resolved via ProfileRef.
# _inputs.is_handle distinguishes a handle from an int/list/'all' selector.
_PROFILE = _inputs.ProfileRef("profile_index", scope_input="component")
_looks_like_handle = _inputs.is_handle

# profile_index may instead carry a sketch TEXT address ('text:<i>'). ExtrudeFeatures.createInput
# takes "a single SketchText object" as a profile, so a nameplate sketch holding no closed profile
# extrudes as itself. allow_text is on THIS resolution alone - the handle/index path refuses a text.
_TEXT_PROFILE = _inputs.ProfileRef("profile_index", allow_text=True, scope_input="component")
_is_text_ref = _inputs.is_text_ref


def _text_ref_in_multi(profile_index):
    """The sketch-TEXT address hiding inside a MULTI-region selector - a list entry, or one field of
    a comma string - or None. The multi forms address CLOSED profiles by index and a text carries no
    index in that space, so a mixed selector is refused rather than silently dropping the text."""
    if isinstance(profile_index, (list, tuple)):
        items = profile_index
    elif isinstance(profile_index, str) and "," in profile_index and not _is_text_ref(profile_index):
        items = profile_index.split(",")
    else:
        return None
    for x in items:
        if _is_text_ref(x):
            return x
    return None


def _is_all_selector(profile_index) -> bool:
    """True for the 'all' (or '*') profile selector - one spelling shared by the resolver below and
    the result note, so the two can never disagree about what 'all' was."""
    return isinstance(profile_index, str) and profile_index.strip().lower() in ("all", "*")


def _resolve_profile_indices(profile_index, pcount, profiles=None):
    """Normalise the profile_index selector (int, list, '0,2,3' or 'all') to a sorted list of
    in-range indices, or (None, error)."""
    sel = profile_index
    if isinstance(sel, str):
        s = sel.strip().lower()
        if _is_all_selector(sel):
            return list(range(pcount)), None
        try:
            sel = [int(x) for x in s.split(",") if x.strip() != ""]
        except Exception:
            return None, (f"profile_index '{profile_index}' is not an int, list, 'all', or '0,1,2'. "
                          "To target a specific region, pass a profile handle from sketch_get instead.")
    if isinstance(sel, (list, tuple)):
        idxs = []
        for x in sel:
            try:
                idxs.append(int(x))
            except Exception:
                if _looks_like_handle(x):
                    return None, (f"profile_index list holds the profile handle {x!r}: a list takes "
                                  "integer indices. Pass one handle alone, or the regions' indices "
                                  "from sketch_get.")
                return None, f"profile_index list has a non-integer entry: {x!r}."
    else:
        try:
            idxs = [int(sel)]
        except Exception:
            idxs = [0]
    idxs = sorted(set(idxs))
    bad = [i for i in idxs if i < 0 or i >= pcount]
    if bad:
        return None, (f"profile_index {bad} out of range - sketch has {pcount} profile(s) "
                      f"(0..{pcount-1}).")
    return (idxs or [0]), None


# A region 'all' selected is ENCLOSED when it fills a HOLE of another selected region: a frame and
# its bays come out of ONE sketch as a profile with an inner loop per bay PLUS a profile per bay. A
# ProfileLoop carries no bounding box, so a hole's extent is the union of its curves' boxes.
_ENCLOSED_TOL_CM = 1e-6


def _extent3(bbox):
    """(xmin, ymin, zmin, xmax, ymax, zmax) of a BoundingBox3D, or None unless all six read as real
    numbers. All THREE axes are kept: a sketch on a vertical plane holds one axis constant for every
    region in it, so dropping an axis would call a far-away region enclosed."""
    mn, mx = safe(lambda: bbox.minPoint), safe(lambda: bbox.maxPoint)
    if mn is None or mx is None:
        return None
    lo = (safe(lambda: mn.x), safe(lambda: mn.y), safe(lambda: mn.z))
    hi = (safe(lambda: mx.x), safe(lambda: mx.y), safe(lambda: mx.z))
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in lo + hi):
        return None
    return (tuple(min(a, b) for a, b in zip(lo, hi))
            + tuple(max(a, b) for a, b in zip(lo, hi)))


def _union(a, b):
    """The extent covering both - how a loop's curves add up to the loop's own extent."""
    return (tuple(min(a[k], b[k]) for k in range(3))
            + tuple(max(a[k], b[k]) for k in range(3, 6)))


def _hole_extents(profile):
    """The extent of each HOLE (a loop with isOuter false) of one profile - the openings another
    selected profile can fill. None when ANY read behind them fails, since a dropped hole would
    publish a false 'nothing is enclosed'."""
    loops = safe(lambda: profile.profileLoops)
    n = safe(lambda: loops.count) if loops is not None else None
    if not isinstance(n, int) or isinstance(n, bool):
        return None
    out = []
    # EVERY loop (and every curve of it below) must read or the verdict is withdrawn (None), so these
    # stay positional walks: iter_collection drops an unreadable member, which would answer with the
    # holes that happened to read instead of declining.
    for i in range(n):
        loop = safe(lambda i=i: loops.item(i))
        if loop is None:
            return None
        outer = safe(lambda loop=loop: loop.isOuter)
        if not isinstance(outer, bool):     # unreadable: neither 'a hole' nor 'not a hole'
            return None
        if outer:
            continue
        curves = safe(lambda loop=loop: loop.profileCurves)
        cn = safe(lambda: curves.count) if curves is not None else None
        if not isinstance(cn, int) or isinstance(cn, bool):
            return None
        box = None
        for j in range(cn):
            cb = _extent3(safe(lambda j=j: curves.item(j).boundingBox))
            if cb is None:
                return None
            box = cb if box is None else _union(box, cb)
        if box is None:                     # an inner loop no curve of which could be measured
            return None
        out.append(box)
    return out


def _within(inner, outer):
    """True when the `inner` extent sits inside `outer` on every axis (tolerance-inclusive, since a
    bay's own extent and the hole it fills are the same curves)."""
    return (all(inner[k] >= outer[k] - _ENCLOSED_TOL_CM for k in range(3))
            and all(inner[k] <= outer[k] + _ENCLOSED_TOL_CM for k in range(3, 6)))


def _enclosed_regions(profiles, indices):
    """The SELECTED profile indices that fill a hole of ANOTHER selected profile - the regions 'all'
    took sight-unseen. None (no verdict) when any selected profile's extent or loops cannot be read:
    the note then says what it could not rule out instead of claiming a count it did not measure."""
    extents, holes = {}, {}
    for i in indices:
        p = safe(lambda i=i: profiles.item(i))
        if p is None:
            return None
        extent, hole = _extent3(safe(lambda p=p: p.boundingBox)), _hole_extents(p)
        if extent is None or hole is None:
            return None
        extents[i], holes[i] = extent, hole
    return [i for i in indices
            if any(_within(extents[i], h) for j in indices if j != i for h in holes[j])]


def _through_all_direction_key(symmetric, distance):
    """'positive' | 'negative' | 'symmetric' - which way extent='through_all' cuts. The SIGN of
    'distance' (its magnitude is unused for through_all) picks a one-sided direction - the same
    'negative reverses' convention 'distance' already carries for a blind extrude; symmetric=true
    goes both ways. 0/positive 'distance' defaults to the profile-normal (positive) direction."""
    if symmetric:
        return "symmetric"
    try:
        if distance and float(distance) < 0:   # a non-numeric expression carries no sign hint
            return "negative"
    except (TypeError, ValueError):
        pass
    return "positive"


def _qualified_body_name(body):
    """The body's name qualified with its owning component or occurrence path, so two bodies sharing
    Fusion's default 'Body1' read distinctly in the 'scoped_to_bodies' echo."""
    if body is None:
        return None
    name = safe(lambda: body.name)
    ctx = _inputs._body_context(body)
    if name and ctx and ctx not in ("?", name):
        return f"{ctx}/{name}"
    return name


def _solo_solid_body(comp):
    """The SOLE solid body directly in `comp` - the implied through_all cut/intersect target when
    'target_bodies' wasn't given (never guessed when there are zero or several bodies; Fusion's own
    intersection search still runs regardless - this only backs the pre/post volume proof below)."""
    solids = [b for b in _common.iter_collection(safe(lambda: comp.bRepBodies))
              if safe(lambda b=b: b.isSolid)]
    return solids if len(solids) == 1 else []


def _solid_bodies_snapshot(design):
    """(body, name, component_name, volume) for EVERY solid body in the design - the pre-image a
    cut/intersect reads back against. feature.bodies returns only the feature's OWN-component result
    body, so it cannot reveal a cut that bled into a co-located component; this read can."""
    snap = []
    for comp in _common.all_components(design):
        cname = safe(lambda c=comp: c.name)
        for b in _common.iter_collection(safe(lambda c=comp: c.bRepBodies)):
            if safe(lambda b=b: b.isSolid):
                snap.append((b, safe(lambda b=b: b.name), cname, _geom.signed_volume(b)))
    return snap


def _affected_bodies(snap):
    """From a pre-cut snapshot, the (name, component_name, removed_cm3) rows whose solid volume DROPPED
    (or whose body was consumed whole) once the feature ran - the bodies a cut/intersect actually acted
    on. 'removed_cm3' is None for a consumed body (e.g. an intersect that kept no overlap)."""
    out = []
    for b, name, cname, v0 in snap:
        if v0 is None:
            continue
        v1 = safe(lambda b=b: b.volume)
        if v1 is None:
            out.append((name, cname, None))          # body consumed
        elif v0 - v1 > _common.NO_VOLUME_CHANGE_CM3:   # material removed
            out.append((name, cname, round(v0 - v1, 6)))
    return out


def _solid_count(design) -> int:
    """The design-wide SOLID body count - the census a cut/intersect is judged against beside the
    volume diff: it RISES when the cut disconnects the target into pieces and FALLS when a body is
    consumed whole, so an unmoved census PLUS no volume drop is what proves nothing happened."""
    n = 0
    for comp in _common.all_components(design):
        for b in _common.iter_collection(safe(lambda c=comp: c.bRepBodies)):
            if safe(lambda b=b: b.isSolid):
                n += 1
    return n


def _effect_rows(affected) -> str:
    """ASCII 'what actually changed' phrase over the affected-bodies rows - what a refusal states
    before it decides whether the feature may be removed at all."""
    rows = []
    for name, cname, removed in affected:
        where = f" in {cname}" if cname else ""
        rows.append(f"{name or '?'}{where}"
                    + (" (consumed)" if removed is None else f" (-{removed} cm3)"))
    return ", ".join(rows)


def _roll_back(design, feature, fname) -> str:
    """Remove a just-created extrude that failed or changed nothing, and return the ASCII sentence a
    RE-READ backs - deleteMe's own answer is not proof, the timeline count is. A rollback that did
    not take names what REMAINS, so the caller is never told the design is clean while it is not."""
    def _count(tl):
        c = safe(lambda: tl.count) if tl is not None else None
        return c if isinstance(c, int) and not isinstance(c, bool) else None

    tl = safe(lambda: design.timeline)
    before = _count(tl)
    try:
        did = feature.deleteMe()
    except Exception as e:
        return (f" '{fname}' could NOT be rolled back ({e}) - it REMAINS in the timeline; remove it "
                "with design_delete_feature.")
    after = _count(tl)
    if before is not None and after is not None:
        if after < before:
            return (f" The feature has been rolled back - the timeline re-reads {after} item(s), "
                    f"down from {before}.")
        return (f" '{fname}' REMAINS in the timeline ({after} item(s) after the rollback, deleteMe "
                f"returned {bool(did)}) - remove it with design_delete_feature.")
    return (f" A rollback of '{fname}' ran (deleteMe returned {bool(did)}) but the timeline could "
            "not be re-read to confirm it - check with design_get.")


def _distance_missing(distance) -> bool:
    """True when 'distance' supplies no extrude depth: None, blank, or a literal 0. A non-numeric string
    is an EXPRESSION (a real depth), and any non-zero number is a real depth."""
    if distance is None:
        return True
    if isinstance(distance, str):
        s = distance.strip()
        if not s:
            return True
        try:
            return float(s) == 0
        except ValueError:
            return False        # an expression string - a real depth
    try:
        return float(distance) == 0
    except (TypeError, ValueError):
        return True


def _feature_parameters(feature) -> dict:
    """The model parameters (dNN) this extrude created, keyed distance / distance2 / taper / taper2,
    so param_set can retarget it. A key is present only when that ModelParameter exists - a
    through_all / to_face extent has no distance parameter."""
    out = {}

    def pname(getter):
        p = safe(getter)
        return safe(lambda: p.name) if p is not None else None

    ext1 = safe(lambda: feature.extentOne)
    d1 = pname(lambda: ext1.distance) if ext1 is not None else None
    if d1:
        out["distance"] = d1
    if safe(lambda: feature.hasTwoExtents, False):
        ext2 = safe(lambda: feature.extentTwo)
        d2 = pname(lambda: ext2.distance) if ext2 is not None else None
        if d2:
            out["distance2"] = d2
    t1 = pname(lambda: feature.taperAngleOne)
    if t1:
        out["taper"] = t1
    t2 = pname(lambda: feature.taperAngleTwo)
    if t2:
        out["taper2"] = t2
    return out


def _to_face_depth_mm(sketch, bodies):
    """The ONE new body's length along the sketch normal in mm, or None when it does not read."""
    # Sketch x/yDirection and a native body both read in the owning component's space, which is
    # the space getOrientedBoundingBox reads its axis arguments in; a proxy on either side is left.
    if len(bodies) != 1 or safe(lambda: sketch.assemblyContext) is not None:
        return None
    body = bodies[0]
    if safe(lambda: body.assemblyContext) is not None:
        return None
    xd = safe(lambda: sketch.xDirection)
    n = _geom.cross(_geom.unit_vector(xd), _geom.unit_vector(safe(lambda: sketch.yDirection)))
    normal = safe(lambda: adsk.core.Vector3D.create(*n)) if n is not None else None
    mgr = safe(lambda: app.measureManager)
    if normal is None or mgr is None:
        return None
    obb = safe(lambda: mgr.getOrientedBoundingBox(body, normal, xd))
    return _common.measured(lambda: obb.length, 10.0, 4) if obb is not None else None


def _depth_mismatch(fname, what, got_cm, want_cm, raw, k, units) -> str:
    """The refusal for a landed depth that disagrees with the request. ONE wording for every side,
    so a two-sided extrude and a blind one cannot describe the same failure differently. `what`
    names WHICH depth read back; the feature has landed, so the sentence says what remains and how
    to remove it, and an expression request names itself beside the number it evaluated to."""
    asked = f"{round(want_cm / k, 6)} {units}"
    if _inputs.looks_like_expression(raw):
        asked += f" (what the expression '{str(raw).strip()}' evaluates to)"
    return (f"Extrude built '{fname}' but its {what} reads back {round(got_cm / k, 6)} {units}, "
            f"not the requested {asked}. '{fname}' REMAINS in the timeline - inspect it with "
            "design_get and remove it with design_delete_feature.")


def _no_target_body_hint(ext_key, distance, symmetric=False) -> str:
    """Return conditional direction guidance without diagnosing the native body-not-found refusal."""
    negative = None
    try:
        negative = float(distance) < 0
    except (TypeError, ValueError):
        pass
    flip_to = "POSITIVE" if negative else "NEGATIVE"
    inspect = " Read sketch_get for the profile and frame, and find_geometry for the target body geometry."
    qualification = " The native body-not-found reply does not establish why the target was missed."
    if ext_key == "through_all":
        remedy = (" If this is a placed component, try extent='distance' with a length spanning "
                  "the body, keeping the same 'component' and 'target_bodies'; read "
                  "model_inspect(include=['mass']) to confirm removal.")
        direction = (" This extent is requested BOTH ways from the sketch plane; changing the "
                     "'distance' sign cannot fix a symmetric extent." if symmetric else
                     " extent=through_all follows the sketch-plane normal. If an on-face sketch "
                     f"points AWAY from the material, try a {flip_to} 'distance' for the other side.")
        return qualification + remedy + direction + inspect
    if symmetric:
        return (qualification + " This extent is requested BOTH ways from the sketch plane; "
                "changing the 'distance' sign cannot fix a symmetric extent." + inspect)
    went = "" if negative is None else f" - 'distance' was {'negative' if negative else 'positive'}"
    return (f" The extrude reached no body the way it went{went}, and a sketch ON a body's face "
            f"points its normal AWAY from the material. Pass a {flip_to} 'distance' to go the "
            "other way, or check the profile overlaps the body at all.")


def _to_entity_extent(raw, minimum_solution, design, input_name):
    """Build a measured face/body to-entity definition from one typed geometry handle."""
    target, err = _TO_OBJECT.resolve(raw)
    if err:
        return None, None, err
    if isinstance(target, adsk.fusion.BRepFace):
        if minimum_solution is not None:
            return None, None, f"'{input_name}' is a face; 'minimum_solution' applies only to a BRepBody."
        try:
            return adsk.fusion.ToEntityExtentDefinition.create(target, False), target, None
        except Exception as exc:
            return None, None, f"Could not create the {input_name} face stop: {exc}"
    if isinstance(target, adsk.fusion.BRepBody):
        try:
            definition = adsk.fusion.ToEntityExtentDefinition.create(
                design.rootComponent.xYConstructionPlane, False)
            definition.entity = target
            if safe(lambda: definition.entity == target) is not True:
                return None, None, f"Fusion did not retain the '{input_name}' BRepBody stop entity."
            if minimum_solution is not None:
                definition.isMinimumSolution = minimum_solution
                if safe(lambda: definition.isMinimumSolution) is not minimum_solution:
                    return None, None, f"Fusion did not retain 'minimum_solution' for '{input_name}'."
            return definition, target, None
        except Exception as exc:
            return None, None, f"Could not assign the {input_name} body stop: {exc}"
    return None, None, f"'{input_name}' handle must point at a BRepFace or BRepBody, got {type(target).__name__}."


def _start_definition_readback(definition, expected_kind, expected_offset_cm, expected_entity=None,
                               design=None):
    """(kind, offset cm, error) for an assigned start definition or landed feature definition."""
    if definition is None:
        return None, None, "the assigned start definition did not read back"
    kind = safe(lambda: definition.objectType)
    if not kind or kind != expected_kind:
        return kind, None, f"the start definition read back as {kind!r}, expected {expected_kind!r}"
    offset = safe(lambda: definition.offset)
    unread = object()
    value_input = safe(lambda: adsk.core.ValueInput.cast(offset), unread)
    if value_input is unread:
        return kind, None, "the start offset value type did not read back"
    if value_input is not None:
        try:
            raw_offset_cm = value_input.realValue
        except Exception:
            expression = safe(lambda: value_input.stringValue)
            units_manager = safe(lambda: design.unitsManager) if design is not None else None
            default_units = safe(lambda: units_manager.defaultLengthUnits) if units_manager else None
            offset_cm = (_common.measured(
                lambda: units_manager.evaluateExpression(expression, default_units), 1.0)
                if isinstance(expression, str) and expression.strip() and default_units else None)
        else:
            offset_cm = _common.measured(lambda: raw_offset_cm, 1.0)
    else:
        parameter = safe(lambda: adsk.fusion.ModelParameter.cast(offset), unread)
        if parameter is unread:
            return kind, None, "the start offset parameter type did not read back"
        offset_cm = (_common.measured(lambda: parameter.value, 1.0)
                     if parameter is not None else None)
    if offset_cm is None:
        return kind, None, "the start offset value did not read back"
    if (expected_offset_cm is not None
            and abs(offset_cm - expected_offset_cm) > _common.EXTENT_MATCH_TOL_CM):
        return kind, offset_cm, f"the start offset read {offset_cm} cm, expected {expected_offset_cm} cm"
    if expected_entity is not None and safe(lambda: definition.entity == expected_entity) is not True:
        return kind, offset_cm, "the start entity did not read back as the selected face or plane"
    return kind, offset_cm, None


def handler(sketch_name: str = "", profile_index=0, distance: float = 0.0,
            units: str = "mm", operation: str = "new", symmetric: bool = False,
            taper_deg: float = 0.0, to_object: str = "", target_bodies=None,
            as_surface: bool = False, extent: str = "distance", distance2: float = 0.0,
            component: str = "", wall_thickness=None, wall_side: str = "",
            wall_thickness_two=None, wall_side_two: str = "", start_offset=None,
            start_object: str = "", extent_one: str = "", extent_two: str = "",
            to_object_two: str = "", taper_two_deg: float = 0.0,
            minimum_solution=None) -> dict:
    """See TOOL_DESCRIPTION."""
    k = scale(units)
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    ext_key = (extent or "distance").strip().lower()
    if ext_key not in _EXTENTS:
        return error(f"Unknown extent '{extent}'. Use: {', '.join(_EXTENTS)}.")
    has_to_object = bool((to_object or "").strip())
    has_to_object_two = bool((to_object_two or "").strip())
    # 'to_object' implies the to-face extent when 'extent' is left at its default ('distance' - the
    # original shorthand, kept back-compat) or when 'to_face' is explicitly requested.
    use_to_object = has_to_object and ext_key in ("distance", "to_face")
    if has_to_object and ext_key not in ("distance", "to_face", "two_side"):
        return error(f"'to_object' is not used with extent='{ext_key}'. Drop 'to_object', or use "
                     "extent='to_face' (or the default 'distance').")
    if ext_key == "to_face" and not use_to_object:
        return error("extent='to_face' needs 'to_object' (a find_geometry face handle).")
    if use_to_object and symmetric:
        return error(f"symmetric=true is not supported with extent={ext_key!a} and to_object. "
                     "Use symmetric=false for a one-sided to-face extrude, or omit to_object "
                     "and use extent='distance' with a non-zero distance for symmetry.")
    if ext_key == "distance" and _distance_missing(distance) and not use_to_object:
        return error("Provide a non-zero 'distance' to extrude, or 'to_object' to extrude up to a face.")
    if ext_key == "two_side":
        if symmetric:
            return error("extent='two_side' does not use 'symmetric' - pass equal 'distance' and "
                         "'distance2' for a symmetric two-sided extrude, or use extent='distance' "
                         "with symmetric=true.")
    elif extent_one or extent_two or has_to_object_two or taper_two_deg:
        return error("'extent_one', 'extent_two', 'to_object_two' and 'taper_two_deg' require "
                     "extent='two_side'.")
    if has_to_object_two and ext_key != "two_side":
        return error("'to_object_two' is used only with extent='two_side'.")
    side_one_mode = (extent_one or ("to_face" if has_to_object else "distance")).strip().lower()
    side_two_mode = (extent_two or ("to_face" if has_to_object_two else "distance")).strip().lower()
    if ext_key == "two_side":
        for label, mode in (("extent_one", side_one_mode), ("extent_two", side_two_mode)):
            if mode not in ("distance", "through_all", "to_face"):
                return error(f"Unknown {label} '{mode}'. Use: distance, through_all, to_face.")
        if has_to_object and side_one_mode != "to_face":
            return error("'to_object' requires extent_one='to_face'.")
        if has_to_object_two and side_two_mode != "to_face":
            return error("'to_object_two' requires extent_two='to_face'.")
        if side_one_mode == "to_face" and not has_to_object:
            return error("extent_one='to_face' needs 'to_object': find_geometry face handle or design_get(tree_bodies=true) body handle.")
        if side_two_mode == "to_face" and not has_to_object_two:
            return error("extent_two='to_face' needs 'to_object_two': find_geometry face handle or design_get(tree_bodies=true) body handle.")
        if side_one_mode == "distance" and _distance_missing(distance):
            return error("extent_one='distance' needs non-zero 'distance'.")
        if side_two_mode == "distance" and _distance_missing(distance2):
            return error("extent_two='distance' needs non-zero 'distance2'.")
    if minimum_solution is not None and not (has_to_object or has_to_object_two):
        return error("'minimum_solution' requires a BRepBody 'to_object' or 'to_object_two' stop.")
    if minimum_solution is not None and type(minimum_solution) is not bool:
        return error(f"'minimum_solution' must be a boolean, got {type(minimum_solution).__name__}.")
    wall_one = wall_thickness is not None or bool((wall_side or "").strip())
    wall_two = wall_thickness_two is not None or bool((wall_side_two or "").strip())
    if wall_one != (wall_thickness is not None and bool((wall_side or "").strip())):
        return error("'wall_thickness' and 'wall_side' must be supplied together.")
    if wall_two != (wall_thickness_two is not None and bool((wall_side_two or "").strip())):
        return error("'wall_thickness_two' and 'wall_side_two' must be supplied together.")
    if wall_two and not wall_one:
        return error("'wall_thickness_two' requires the first 'wall_thickness' and 'wall_side'.")
    if wall_two and ext_key != "two_side":
        return error("'wall_thickness_two' and 'wall_side_two' require extent='two_side'.")
    if start_object and start_offset is None:
        start_offset = 0
    op_key = (operation or "new").strip().lower()
    if op_key not in _common.OPERATIONS:
        return error(f"Unknown operation '{operation}'. Use: new, join, cut, intersect.")

    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")

    root = target_component(design)
    selected_profile = None
    if _looks_like_handle(profile_index):
        selected_profile, perr = _PROFILE.resolve(profile_index, component)
        if perr:
            return error(perr)
        sketch = safe(lambda: selected_profile.parentSketch)
        if sketch is None:
            return error("profile_index resolved a profile whose parent sketch could not be read.")
    else:
        sketch, requested, ambiguous = _sketch_detail.scoped_or_recent_sketch(
            design, sketch_name, component)
        if ambiguous:
            return error(ambiguous)
        if not sketch:
            if requested:
                names = _common.all_sketch_names(design)
                avail = f" Available: {', '.join(names)}." if names else ""
                return error(f"No sketch named '{requested}'.{avail} Use sketch_get or sketch_create.")
            return error("No sketch to extrude. Create one and draw a closed profile first.")

    profiles = safe(lambda: sketch.profiles)
    pcount = safe(lambda: profiles.count, 0) if profiles else 0

    # A sketch TEXT address selects the text itself, which is what a text-only sketch carries INSTEAD
    # of a closed profile - so it is read BEFORE the zero-profile routing below, which would
    # otherwise send a nameplate sketch down the open-curve surface path and dead-end there.
    mixed_text = _text_ref_in_multi(profile_index)
    if mixed_text:
        return error(f"profile_index mixes the sketch text '{mixed_text}' with other regions. A "
                     f"sketch text extrudes on its own - pass just '{mixed_text}', and a separate "
                     "call for the closed regions.")
    text_addr = profile_index.strip() if _is_text_ref(profile_index) else None
    if text_addr and as_surface:
        return error(f"as_surface is not used with the sketch text '{text_addr}' - a text extrudes "
                     "as a solid. Drop as_surface, or pass a closed profile / an open path.")

    # `pcount` is read off the sketch, so a DEFERRED one can read 0 while holding regions - the AUTO
    # clause below must not choose the feature type off that count. A forced as_surface still runs:
    # it builds from the sketch's curves, which are current under a deferral.
    stale = _inputs.deferred_sketch_refusal("profile_index", sketch)

    # SURFACE path: forced via as_surface, OR auto when there is no closed profile but the sketch has
    # open curves. A requested surface over a current closed region extrudes THAT region with
    # isSolid = False; otherwise an OPEN profile is built from the curves. Never a solid instead.
    want_surface = bool(as_surface) or (pcount == 0 and not text_addr and not stale)
    closed_surface = bool(as_surface) and (selected_profile is not None
                                           or (pcount > 0 and not stale))
    open_surface = False
    indices = [0]
    took_all = False
    if want_surface and not closed_surface:
        profile_arg, perr = _common.open_profile_from_sketch(
            safe(lambda: sketch.parentComponent) or root, sketch, "for a surface extrude",
            no_curves_error=(f"Sketch '{safe(lambda: sketch.name)}' has no curves to extrude as a "
                             "surface. Draw an open path (a line/arc) or a closed region first."))
        if perr:
            return error(perr)
        open_surface = True

    if not open_surface:
        # Three ways to name what is extruded: a TEXT address, a profile HANDLE (an entityToken from
        # sketch_get - the robust way to pick one of several regions, face ring vs the region you
        # drew), or an index/list/'all' selector. Each predicate says no to the other two's forms.
        if text_addr:
            # ProfileRef resolves the address's OWN sketch, so a bare 'text:<i>' is qualified with
            # the sketch this call already resolved by name - otherwise the two reads can land on
            # different sketches (the address alone falls back to the most recent one).
            addr = text_addr
            if "/" not in addr and (sketch_name or "").strip():
                addr = f"{sketch_name.strip()}/{addr}"
            prof, perr = _TEXT_PROFILE.resolve(addr, component)
            if perr:
                return error(perr)
            profile_arg, indices = prof, [None]
        elif selected_profile is not None:
            profile_arg, indices = selected_profile, [None]
        else:
            # BEFORE the count is trusted: an index reads straight off sketch.profiles here, never
            # through ProfileRef, so a deferred sketch's pcount and item(i) are both pre-deferral.
            if stale:
                return error(stale)
            if pcount == 0:
                return error(f"Sketch '{safe(lambda: sketch.name)}' has no closed profile to extrude. "
    "Draw a closed region (e.g. a rectangle or circle) first, or pass "
    "as_surface=true to extrude an open path into a surface.")
            indices, ierr = _resolve_profile_indices(profile_index, pcount, profiles)
            if ierr:
                return error(ierr)
            took_all = _is_all_selector(profile_index)
            # One profile -> pass it directly; several -> an ObjectCollection (extrudeFeatures.createInput
            # accepts either, so N profiles of one sketch extrude in ONE feature/call).
            if len(indices) == 1:
                profile_arg = profiles.item(indices[0])
            else:
                coll = adsk.core.ObjectCollection.create()
                for i in indices:
                    coll.add(profiles.item(i))
                profile_arg = coll

    if (wall_one or wall_two) and (open_surface or closed_surface or text_addr):
        return error("Thin wall controls require a closed solid profile; they cannot be used with "
                     "as_surface or sketch text.")

    op = getattr(adsk.fusion.FeatureOperations, _common.OPERATIONS[op_key])
    host = _inputs.profile_host_component(profile_arg, sketch, root)
    try:
        ext_input = host.features.extrudeFeatures.createInput(profile_arg, op)
        if open_surface:
            ext_input.isSolid = False   # surface: no end caps (confirmed-live ExtrudeFeatureInput.isSolid)
        elif closed_surface:
            serr = _common.set_verified(ext_input, "isSolid", False,
                                        "isSolid=false (as_surface extrudes the region as a surface)",
                                        "ExtrudeFeatureInput")
            if serr:
                return error(serr)
        elif text_addr:
            # as_surface is refused with a text, so the solid this call promises is STATED and read
            # back rather than inherited from a default the code never read.
            serr = _common.set_verified(ext_input, "isSolid", True,
                                        "isSolid=true (a sketch text extrudes as a solid)",
                                        "ExtrudeFeatureInput")
            if serr:
                return error(serr)
    except Exception as e:
        return error(f"Could not start extrude: {e}")

    expected_start = None
    if start_object or start_offset is not None:
        if start_object:
            start_ent, serr = _START_OBJECT.resolve(start_object)
            if serr:
                return error(serr)
            offset_value, offset_cm, oerr = _inputs.length_value_input(
                start_offset if start_offset is not None else 0, k, design, "start_offset")
            if oerr:
                return error(oerr)
            try:
                start_def = adsk.fusion.FromEntityStartDefinition.create(start_ent, offset_value)
                ext_input.startExtent = start_def
            except Exception as exc:
                return error(f"Could not set 'start_object' and 'start_offset': {exc}")
            expected_entity = start_ent
        else:
            offset_value, offset_cm, oerr = _inputs.length_value_input(
                start_offset, k, design, "start_offset")
            if oerr:
                return error(oerr)
            try:
                start_def = adsk.fusion.OffsetStartDefinition.create(offset_value)
                ext_input.startExtent = start_def
            except Exception as exc:
                return error(f"Could not set 'start_offset': {exc}")
            expected_entity = None
        expected_kind = safe(lambda: start_def.objectType)
        actual_start = safe(lambda: ext_input.startExtent)
        actual_kind, actual_offset_cm, start_err = _start_definition_readback(
            actual_start, expected_kind, offset_cm, expected_entity, design)
        if start_err:
            return error(f"Fusion did not retain the requested start definition before feature creation: {start_err}.")
        expected_start = (expected_kind, offset_cm, expected_entity)

    # extent: 'to_object'/'to_face' wins; then through_all/two_side; else a blind distance.
    taper = float(taper_deg or 0.0)
    through_all_dir = None
    # Each distance entry carries its native extent index; a to-entity/through-all side has none.
    # Empty for an extent with no distance parameter (through_all, to_face).
    depth_request = []
    stop_expectations = []
    thin_expectations = []
    taper_two_expected_deg = None
    taper_one_expected_deg = None
    try:
        if use_to_object:
            if taper:
                return error("taper_deg is not supported with extent=to_object/to_face - a to-entity "
                             "extrude takes no taper. Use a distance extent, or drop the taper.")
            to_extent, _stop, ferr = _to_entity_extent(to_object, minimum_solution, design, "to_object")
            if ferr:
                return error(ferr)
            stop_expectations.append((0, _stop, minimum_solution))
            # Every setter here documents "Returns true if successful". A false answer leaves the
            # input on its DEFAULT extent, and add() then builds a feature nobody asked for.
            if not ext_input.setOneSideExtent(to_extent,
                                              adsk.fusion.ExtentDirections.PositiveExtentDirection):
                return error("Fusion refused the to_object extent (setOneSideExtent returned false), "
                             "so nothing was extruded. Check the target face is reachable from the "
                             "profile in the extrude direction.")
        elif ext_key == "through_all":
            if taper:
                return error("taper_deg is not supported with extent=through_all (a through-all "
                             "extent carries no taper).")
            # A symmetric through-all takes one definition per side.
            through_all_dir = _through_all_direction_key(symmetric, distance)
            all_extent = adsk.fusion.ThroughAllExtentDefinition
            if through_all_dir == "symmetric":
                if not ext_input.setTwoSidesExtent(all_extent.create(), all_extent.create()):
                    return error("Fusion rejected a symmetric extent=through_all "
                                 "(setTwoSidesExtent returned false).")
            else:
                ext_dirs = adsk.fusion.ExtentDirections
                direction = {"positive": ext_dirs.PositiveExtentDirection,
                             "negative": ext_dirs.NegativeExtentDirection}[through_all_dir]
                through = all_extent.create()
                if through_all_dir == "negative":
                    # The direction argument alone leaves the extent on the positive side.
                    through.isPositiveDirection = False
                if not ext_input.setOneSideExtent(through, direction):
                    return error(f"Fusion rejected a {through_all_dir} extent=through_all "
                                 "(setOneSideExtent returned false).")
        elif ext_key == "two_side":
            taper_one_value = float(taper_deg or 0.0)
            taper_two_value = float(taper_two_deg or 0.0)
            taper_one_expected_deg = taper_one_value or None
            taper_two_expected_deg = taper_two_value or None
            if taper_one_value and side_one_mode != "distance":
                return error("'taper_deg' applies only when extent_one='distance'.")
            if taper_two_value and side_two_mode != "distance":
                return error("'taper_two_deg' applies only when extent_two='distance'.")

            def side_definition(mode, raw_distance, raw_stop, stop_name, minimum, side_index):
                if mode == "distance":
                    value, want_cm, err = _inputs.length_value_input(
                        raw_distance, k, design, "distance" if stop_name == "to_object" else "distance2")
                    if err:
                        return None, None, err
                    return adsk.fusion.DistanceExtentDefinition.create(value), want_cm, None
                if mode == "through_all":
                    return adsk.fusion.ThroughAllExtentDefinition.create(), None, None
                definition, _entity, err = _to_entity_extent(raw_stop, minimum, design, stop_name)
                if err is None:
                    stop_expectations.append((side_index, _entity, minimum))
                return definition, None, err

            one, cm_one, err_one = side_definition(
                side_one_mode, distance, to_object, "to_object", minimum_solution, 0)
            if err_one:
                return error(err_one)
            two, cm_two, err_two = side_definition(
                side_two_mode, distance2, to_object_two, "to_object_two", minimum_solution, 1)
            if err_two:
                return error(err_two)
            taper_one = (adsk.core.ValueInput.createByString(f"{taper_one_value} deg")
                         if taper_one_value else None)
            taper_two = (adsk.core.ValueInput.createByString(f"{taper_two_value} deg")
                         if taper_two_value else None)
            if not ext_input.setTwoSidesExtent(one, two, taper_one, taper_two):
                return error("Fusion rejected the independent two-sided extents (setTwoSidesExtent "
                             "returned false).")
            # A distance side is listed even when its request evaluated to no number, so it is disclosed.
            if side_one_mode == "distance":
                depth_request.append(("side-one distance", 0, cm_one, distance, True))
            if side_two_mode == "distance":
                depth_request.append(("side-two distance", 1, cm_two, distance2, True))
        else:
            dist_val, want_distance_cm, dverr = _inputs.length_value_input(
                distance, k, design, "distance")
            if dverr:
                return error(dverr)
            # One side, on extentOne. Its NEGATIVE case IS measured (the parameter keeps the
            # requested sign, -15 mm reads -1.5), so this side is judged whichever way it points.
            depth_request = [("distance", 0, want_distance_cm, distance, False)]
            if taper and symmetric:
                # isFullLength=False -> 'distance' is the per-side half-length (2x total).
                taper_val = adsk.core.ValueInput.createByString(f"{taper} deg")
                if not ext_input.setSymmetricExtent(dist_val, False, taper_val):
                    return error(f"Fusion refused a symmetric tapered extent ({distance} {units} per "
                                 f"side, {taper} deg), so nothing was extruded.")
            elif taper:
                # one-sided with taper: build a DistanceExtentDefinition + taper ValueInput
                extent_def = adsk.fusion.DistanceExtentDefinition.create(dist_val)
                taper_val = adsk.core.ValueInput.createByString(f"{taper} deg")
                if not ext_input.setOneSideExtent(
                        extent_def, adsk.fusion.ExtentDirections.PositiveExtentDirection, taper_val):
                    return error(f"Fusion refused a one-sided tapered extent ({distance} {units}, "
                                 f"{taper} deg), so nothing was extruded.")
            else:
                if symmetric:
                    landed = ext_input.setSymmetricExtent(dist_val, False)
                else:
                    # The signed distance carries the side, as on the tapered branch above.
                    landed = ext_input.setOneSideExtent(
                        adsk.fusion.DistanceExtentDefinition.create(dist_val),
                        adsk.fusion.ExtentDirections.PositiveExtentDirection)
                if not landed:
                    return error(f"Fusion refused a {'symmetric ' if symmetric else ''}distance "
                                 f"extent of {distance} {units}, so nothing was extruded.")
    except Exception as e:
        return error(f"Could not set extrude extent: {e}")

    if wall_one:
        wall_one_input, wall_one_cm, wall_err = _inputs.length_value_input(
            wall_thickness, k, design, "wall_thickness")
        if wall_err:
            return error(wall_err)
        if (isinstance(wall_one_cm, bool) or not isinstance(wall_one_cm, (int, float))
                or not math.isfinite(wall_one_cm) or wall_one_cm <= 0):
            return error("'wall_thickness' must evaluate to a finite positive length.")
        locations = adsk.fusion.ThinExtrudeWallLocation
        wall_one_location = {"center": locations.Center, "side_one": locations.Side1,
                             "side_two": locations.Side2}.get((wall_side or "").strip().lower())
        if wall_one_location is None:
            return error("Unknown 'wall_side'. Use: center, side_one, side_two.")
        if wall_two:
            wall_two_input, wall_two_cm, wall_err = _inputs.length_value_input(
                wall_thickness_two, k, design, "wall_thickness_two")
            if wall_err:
                return error(wall_err)
            if (isinstance(wall_two_cm, bool) or not isinstance(wall_two_cm, (int, float))
                    or not math.isfinite(wall_two_cm) or wall_two_cm <= 0):
                return error("'wall_thickness_two' must evaluate to a finite positive length.")
            wall_two_location = {"center": locations.Center, "side_one": locations.Side1,
                                 "side_two": locations.Side2}.get((wall_side_two or "").strip().lower())
            if wall_two_location is None:
                return error("Unknown 'wall_side_two'. Use: center, side_one, side_two.")
            thin_result = ext_input.setThinExtrude(
                wall_one_location, wall_one_input, wall_two_location, wall_two_input)
        else:
            thin_result = ext_input.setThinExtrude(wall_one_location, wall_one_input)
        if thin_result is not True:
            return error("Fusion refused the thin extrusion controls; setThinExtrude did not return true.")
        thin_expectations.append((1, wall_one_location, wall_one_cm))
        if wall_two:
            thin_expectations.append((2, wall_two_location, wall_two_cm))

    # target_bodies: scope a cut/join/intersect to specific bodies so it can't bleed through others.
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
            ext_input.participantBodies = list(bodies_ents)
            scoped_to = [_qualified_body_name(b) for b in bodies_ents]
        except Exception as e:
            return error(f"Could not scope to target_bodies: {e}")

    # through_all CUT/INTERSECT: pre-capture the volume of the bodies it will act on, so a silent
    # no-op is caught instead of a false ok. 'All' extends until it exits the geometry, so ANY volume
    # drop on a targeted body proves the cut went all the way through it.
    check_bodies = []
    if ext_key == "through_all" and op_key in ("cut", "intersect"):
        check_bodies = list(bodies_ents) if bodies_ents else _solo_solid_body(host)
    # check_bodies are HELD across the mutation and re-read afterwards, which is exactly the
    # id()-keying precondition _geom.volumes documents - so this is the shared sample, not a local one.
    vol_before = _geom.volumes(check_bodies)

    # cut/intersect read-back: capture every solid body's volume design-wide BEFORE the op, so we can
    # report which bodies (and whose components) actually changed - and warn when an UNSCOPED cut bled
    # into a co-located component (feature.bodies sees only the own-component result body; see helper).
    solid_snap = _solid_bodies_snapshot(design) if op_key in ("cut", "intersect") else []
    # A join is told "grew a body" from "made a second one" by the host's body NAMES before the add.
    bodies_before = _common.component_body_names(host) if op_key == "join" else None

    try:
        feature = host.features.extrudeFeatures.add(ext_input)
    except Exception as e:
        # A bad expression reference can slip past the pre-check and only fail here, so it is named.
        # The direction hint points the OTHER way from the distance that just failed.
        platform = str(e).lower()
        if _inputs.looks_like_expression(distance):
            hint = f" The distance expression '{distance.strip()}' may be unresolvable - check param_get."
        elif ((ext_key == "through_all" and "body not found" in platform)
              or (op_key in ("cut", "intersect") and "no target body found" in platform)):
            hint = _no_target_body_hint(ext_key, distance, bool(symmetric))
        else:
            hint = " (A 'cut'/'intersect' needs existing geometry to act on.)"
        return error(f"Extrude failed: {e}.{hint}")
    if not feature:
        return error(_common.no_feature_error(design, "Extrude"))
    feature_name = safe(lambda: feature.name)
    thin_unverified = []
    if thin_expectations:
        thin_flag = _common.read_flag(lambda: feature.isThinExtrude)
        if thin_flag is False:
            return error(f"Extrude built '{feature_name or 'a feature'}' but isThinExtrude reads false. "
                         "The feature remains in the timeline; inspect it with design_get and remove it "
                         "with design_delete_feature.")
        if thin_flag is None:
            thin_unverified.append("thin_extrude")
        for side_number, expected_location, expected_cm in thin_expectations:
            suffix = "One" if side_number == 1 else "Two"
            actual_location = safe(lambda suffix=suffix: getattr(feature, f"thinExtrudeWallLocation{suffix}"))
            if actual_location is None:
                thin_unverified.append(f"wall_side_{'one' if side_number == 1 else 'two'}")
            elif actual_location != expected_location:
                return error(f"Extrude built '{feature_name or 'a feature'}' but its side-{side_number} "
                             "thin-wall location did not retain the requested value. The feature remains "
                             "in the timeline; inspect it with design_get and remove it with "
                             "design_delete_feature.")
            actual_thickness = _common.measured(
                lambda suffix=suffix: getattr(feature, f"thinExtrudeWallThickness{suffix}").value, 1.0)
            if actual_thickness is None:
                thin_unverified.append(f"wall_thickness_{'one' if side_number == 1 else 'two'}")
            elif abs(actual_thickness - expected_cm) > _common.EXTENT_MATCH_TOL_CM:
                return error(f"Extrude built '{feature_name or 'a feature'}' but its side-{side_number} "
                             f"thin-wall thickness reads {actual_thickness} cm, not {expected_cm} cm. "
                             "The feature remains in the timeline; inspect it with design_get and remove "
                             "it with design_delete_feature.")
    taper_one_landed_deg = None
    if taper_one_expected_deg is not None:
        taper_one_landed_deg = _common.measured(lambda: feature.taperAngleOne.value, 180.0 / math.pi)
        if (taper_one_landed_deg is not None
                and abs(taper_one_landed_deg - taper_one_expected_deg) > 1e-4):
            return error(f"Extrude built '{feature_name or 'a feature'}' but taperAngleOne reads "
                         f"{taper_one_landed_deg} deg, not the requested {taper_one_expected_deg} deg. "
                         "The feature remains in the timeline; inspect it with design_get and remove it "
                         "with design_delete_feature.")
    taper_two_landed_deg = None
    if taper_two_expected_deg is not None:
        taper_two_landed_deg = _common.measured(lambda: feature.taperAngleTwo.value, 180.0 / math.pi)
        if (taper_two_landed_deg is not None
                and abs(taper_two_landed_deg - taper_two_expected_deg) > 1e-4):
            return error(f"Extrude built '{feature_name or 'a feature'}' but taperAngleTwo reads "
                         f"{taper_two_landed_deg} deg, not the requested {taper_two_expected_deg} deg. "
                         "The feature remains in the timeline; inspect it with design_get and remove it "
                         "with design_delete_feature.")
    for side_index, expected_entity, expected_minimum in stop_expectations:
        extent = safe(lambda side_index=side_index: feature.extentOne if side_index == 0 else feature.extentTwo)
        actual_entity = safe(lambda extent=extent: extent.entity) if extent is not None else None
        expected_identity = _common.native_identity(expected_entity)
        actual_identity = _common.native_identity(actual_entity) if actual_entity is not None else None
        same_stop = safe(lambda: actual_entity == expected_entity) is True
        if not same_stop and (expected_identity is None or actual_identity != expected_identity):
            return error(f"Extrude built '{feature_name or 'a feature'}' but its extent{side_index + 1} "
                         "did not retain the selected stop entity. The feature remains in the timeline; "
                         "inspect it with design_get and remove it with design_delete_feature.")
        if expected_minimum is not None:
            landed_minimum = safe(lambda extent=extent: extent.isMinimumSolution)
            if landed_minimum is not expected_minimum:
                return error(f"Extrude built '{feature_name or 'a feature'}' but its extent{side_index + 1} "
                             "did not retain the requested minimum_solution. The feature remains in the "
                             "timeline; inspect it with design_get and remove it with design_delete_feature.")
    landed_start = None
    if expected_start is not None:
        expected_kind, expected_offset_cm, expected_entity = expected_start
        actual_start = safe(lambda: feature.startExtent)
        start_kind, start_offset_cm, start_err = _start_definition_readback(
            actual_start, expected_kind, expected_offset_cm, expected_entity, design)
        if start_err:
            identity = feature_name or safe(lambda: feature.entityToken) or "new extrude feature"
            return error(f"Extrude built '{identity}' but its start definition did not verify: {start_err}. "
                         "The feature remains in the timeline; inspect it with design_get and remove it "
                         "with design_delete_feature.")
        landed_start = (start_kind, start_offset_cm, expected_entity)

    through_all_removed = None
    if check_bodies:
        deltas, vol_after = {}, _geom.volumes(check_bodies)
        for b in check_bodies:
            # The OCCURRENCE-QUALIFIED name, the same spelling 'scoped_to_bodies' echoes: Fusion
            # auto-names every component's first body 'Body1', so a bare-name key collapses a cut
            # scoped across two components into one entry and overwrites the first.
            nm = _qualified_body_name(b) or "?"
            before, after = vol_before.get(id(b)), vol_after.get(id(b))
            if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                deltas[nm] = round(before - after, 6)
        if deltas:
            through_all_removed = deltas
            if all(abs(d) < _common.NO_VOLUME_CHANGE_CM3 for d in deltas.values()):
                # The check reads only the bodies this cut was aimed at, so an effect elsewhere in
                # the design is not ruled out - the feature is DISCLOSED, never deleted from under
                # a caller whose evidence stops at those bodies.
                fname = safe(lambda: feature.name) or "the new extrude feature"
                return error("Extrude reported success but extent=through_all removed no material "
                             f"from {', '.join(deltas)}. through_all follows the sketch-plane "
                             "normal, which on an on-face sketch points away from the body - pass "
                             f"the opposite 'distance' sign. '{fname}' remains in the timeline (this "
                             "check read only those bodies); remove it with design_delete_feature.")

    # cut/intersect EFFECT evidence, read BEFORE any rollback below: which bodies lost material, and
    # whether the solid census moved at all. Both are needed to claim nothing happened - a consumed
    # body reports no volume drop, and a split adds a body.
    affected = _affected_bodies(solid_snap) if solid_snap else []
    solid_delta = (_solid_count(design) - len(solid_snap)) if solid_snap else 0
    nothing_changed = bool(solid_snap) and not affected and solid_delta == 0
    scoped_names = ", ".join(n for n in (scoped_to or []) if n)

    # add() hands back a truthy feature object for a FAILED compute, so the health state is the only
    # signal here - and a scoped cut reaching none of its bodies leaves a healthy FEATURE with a
    # WARNING timeline item, which is why compute_state asks both.
    _state, failed = _assert.compute_state(feature)
    if failed:
        state_label, detail = failed
        fname = safe(lambda: feature.name) or "the new extrude feature"
        parts = [f"Extrude built '{fname}' but Fusion reports it as a FAILED compute (health state: "
                 f"{state_label})" + (f": {detail}" if detail else " (it reports no message)") + "."]
        if nothing_changed:
            parts.append(f" No solid body lost material and none was consumed, so this {op_key} "
                         "removed nothing.")
        elif affected:
            parts.append(f" Material DID change: {_effect_rows(affected)}.")
        elif solid_delta:
            parts.append(f" The design-wide solid body count changed by {solid_delta:+d}.")
        else:
            parts.append(f" Whether anything landed is NOT read for a '{op_key}' extrude, so it is "
                         "not claimed either way.")
        if scoped_names:
            parts.append(f" Scoping to 'target_bodies' ({scoped_names}) makes Fusion build this "
                         "failed feature instead of refusing a profile that reaches none of them, so "
                         "check the profile overlaps those bodies in the extrude direction (a "
                         "negative 'distance' reverses it).")
        if nothing_changed:
            parts.append(_roll_back(design, feature, fname))
        else:
            parts.append(f" '{fname}' is LEFT in the timeline - nothing is rolled back while an "
                         "effect is unruled-out. Inspect it with design_get and remove it with "
                         "design_delete_feature if it is unwanted.")
        return error("".join(parts))

    # A SCOPED cut/intersect that changed nothing: the feature computed, but no body named in
    # 'target_bodies' lost material and the solid census is unmoved. Only named bodies can be
    # affected, so this is a no-op reported as success.
    if scoped_to and op_key in ("cut", "intersect") and nothing_changed:
        fname = safe(lambda: feature.name) or "the new extrude feature"
        return error(f"Extrude reported success but this {op_key} changed nothing: no solid body "
                     "lost material and none was consumed, so the scoped bodies "
                     f"({scoped_names}) are untouched. A cut/intersect can only affect bodies named "
                     "in 'target_bodies' - check the profile overlaps them in the extrude direction "
                     "(a negative 'distance' reverses it)."
                     + _roll_back(design, feature, fname))

    # A one-sided through_all publishes the side its extentOne.isPositiveDirection flag reads.
    side_read = through_all_dir
    if through_all_dir in ("positive", "negative"):
        flag = _common.read_flag(lambda: feature.extentOne.isPositiveDirection)
        side_read = None if flag is None else "positive" if flag else "negative"
        if side_read is not None and side_read != through_all_dir:
            fname = safe(lambda: feature.name) or "the new extrude feature"
            return error(f"Extrude built '{fname}' for a {through_all_dir} extent=through_all, but "
                         f"its extent reads back the {side_read} side. "
                         + _common.failed_effect_remedy(design, feature))

    # DEPTH read-back per side: the feature's own distance ModelParameter against the cm number the
    # units engine evaluated THAT side's request to. Side one lands on extentOne and side two on
    # extentTwo, so a side is judged against its own request. A side this cannot judge is disclosed.
    unverified = []
    landed_side = (_common.landed_extent_cm, _common.landed_extent2_cm)
    for what, side_index, want_cm, raw, two_sided in depth_request:
        got_cm = landed_side[side_index](feature)
        if want_cm is None:
            unverified.append((what, "the units engine answered no number for its request, so "
                                     "there was nothing to judge it against"))
        elif two_sided and want_cm <= 0:
            unverified.append((what, "the depth a NEGATIVE two-sided request stores is unmeasured, "
                                     "so its landed depth was read but not judged"))
        elif got_cm is None:
            unverified.append((what, "the feature reported no depth number for it"))
        elif abs(got_cm - want_cm) > _common.EXTENT_MATCH_TOL_CM:
            fname = safe(lambda: feature.name) or "the new extrude feature"
            return error(_depth_mismatch(fname, what, got_cm, want_cm, raw, k, units))

    body_names = [f["name"] for f in _common.body_facts(_common.result_bodies(feature))]

    # body-split: the extruded profile removes no bodies, so any NET increase in the design-wide
    # solid count is split-off pieces. Counting solids - not feature.bodies, which for a cut reports
    # only the own-component result - also catches a split in a co-located component.
    split_count = solid_delta if op_key in ("cut", "intersect") else 0

    # 'component' is the FEATURE's own parent - the timeline's answer - never inferred from which
    # body lost the most volume; a co-located cut can land the feature outside the sketch's own
    # component. affected-bodies still drives the footgun warning below.
    sketch_owner = safe(lambda: sketch.parentComponent.name)
    component_field = safe(lambda: feature.parentComponent.name)
    affected_comps = []
    for _n, _cn, _rem in affected:
        if _cn and _cn not in affected_comps:
            affected_comps.append(_cn)

    # Surface the result either way: read isSolid back off the feature (never assumed).
    is_solid = safe(lambda: feature.isSolid)
    if (open_surface or closed_surface) and is_solid is True:
        fname = safe(lambda: feature.name) or "the new extrude feature"
        return error(f"A surface was requested but '{fname}' reads back isSolid=true."
                     + _roll_back(design, feature, fname))
    if open_surface:
        note = ("Open profile extruded into a SURFACE (no end caps) - pair with model_stitch to "
    "close several surfaces into a solid.")
    elif closed_surface:
        note = ("Closed profile extruded into a SURFACE wall (no end caps) - pair with model_stitch "
                "to close several surfaces into a solid.")
    elif text_addr:
        note = ("Sketch text extruded into a solid. To stamp text onto an existing face instead, "
                "use model_emboss.")
    else:
        note = "Profile extruded into a solid. Pair with view_screenshot (iso) to view it."
    if op_key == "new":
        adv = root_body_advisory(design, host)          # advise on where the body actually landed
        if adv:
            note += " " + adv
    join_clause = _common.join_new_body_clause(op_key, bodies_before, body_names)
    if join_clause:
        note += " " + join_clause
    # 'all' takes every closed region, so a bay inside a frame extrudes into material and the payload
    # cannot show it - the enclosed regions are counted and named here instead, behind safe() so a
    # misbehaving containment read cannot sink an extrude that landed.
    enclosed = None
    if took_all and len(indices) > 1:
        enclosed = safe(lambda: _enclosed_regions(profiles, indices))
        note += f" 'all' selected every closed region in this sketch ({len(indices)})"
        if enclosed is not None and not enclosed:
            note += "; none of them sits inside another selected region."
        else:
            note += ((", INCLUDING any region enclosed by another selected one" if enclosed is None
                      else (f", INCLUDING {len(enclosed)} region(s) enclosed by another selected one "
                            f"(profile index {', '.join(str(i) for i in enclosed)})"))
                     + " - the openings inside a frame outline are closed regions too, so this "
                     f"{op_key} acted on them as well. To act on only the regions you mean, read "
                     "them with sketch_get (area/centroid per region) and pass a profile 'handle' "
                     "or an index list.")

    depth_mm = None
    if use_to_object:
        extent_report, distance_report = "to_object", None
        # A to-face extent carries no distance parameter, so the landed depth is read off the body.
        if op_key == "new":
            depth_mm = _to_face_depth_mm(sketch, _common.result_bodies(feature))
        if depth_mm is None:
            note += " The landed depth was not read."
    elif ext_key == "through_all":
        extent_report, distance_report = "through_all", None
        if side_read is None:
            note += " The landed through_all side was not read back."
    else:
        extent_report, distance_report = ext_key, _inputs.expression_report(distance)

    # Name the model parameters the feature created so the retarget path is discoverable without
    # fishing through param_get to guess which dNN is which (param_set '<dNN>' '<expression>').
    model_params = _feature_parameters(feature)
    if model_params:
        note += (" Distance/taper are model parameters (see 'model_parameters') - param_set one to an "
                 "expression to drive this feature parametrically.")

    # The one disclosure for every side the compare above could not judge, so a success that skipped
    # a depth check never reads as one that passed it.
    for what, why in unverified:
        note += f" {what[0].upper()}{what[1:]} was not depth-verified: {why}."

    result = {
        "extruded": True,
        "feature": safe(lambda: feature.name),
        "operation": op_key,
        "sketch": safe(lambda: sketch.name),
        "component": component_field,
        "profile_index": ("text" if text_addr
                          else "handle" if indices == [None]
                          else (indices[0] if len(indices) == 1 else indices)),
        "profiles_extruded": len(indices),
        "as_surface": bool(open_surface or closed_surface),
        "is_solid": is_solid,
        "distance": distance_report,
        "extent": extent_report,
        "units": units,
        "symmetric": bool(symmetric),
        "taper_deg": (taper_one_landed_deg if taper_one_landed_deg is not None
                      else float(taper_deg or 0.0)),
        "scoped_to_bodies": scoped_to,
        "result_bodies": body_names,
        "note": note,
    }
    if landed_start is not None:
        start_kind, start_offset_cm, start_entity = landed_start
        result["start_definition"] = start_kind.rsplit("::", 1)[-1]
        result["start_offset"] = round(start_offset_cm / k, 6)
        if start_entity is not None:
            result["start_entity"] = safe(lambda: start_entity.name)
    if sketch_owner and sketch_owner != component_field:
        result["sketch_component"] = sketch_owner
    if model_params:
        result["model_parameters"] = model_params
    if depth_mm is not None:
        result["depth_mm"] = depth_mm
    if enclosed:
        result["enclosed_profile_indices"] = enclosed
    if ext_key == "two_side":
        result["distance2"] = _inputs.expression_report(distance2)
        origin, normal = _inputs.placed_datum_frame(sketch, "sketch_plane")
        result["side_reference"] = {"frame": "world" if origin is not None and normal is not None else None,
                                     "origin_cm": origin,
                                     "normal_world": normal, "operand": safe(lambda: sketch.name)}
        result["note"] += (" Positive two-sided lengths: distance/taper_deg follow the sketch normal; "
                           "distance2/taper_two_deg oppose it.")
        if normal is None:
            result["note"] += " World sketch frame unavailable; inspect the placed sketch before choosing sides."
        if taper_one_expected_deg is not None and taper_one_landed_deg is None:
            result["unverified"] = sorted(set(result.get("unverified", []) + ["taper_deg"]))
        if float(taper_two_deg or 0.0):
            if taper_two_landed_deg is None:
                result["unverified"] = sorted(set(result.get("unverified", []) + ["taper_two_deg"]))
            else:
                result["taper_two_deg"] = taper_two_landed_deg
    if thin_unverified:
        result["unverified"] = sorted(set(result.get("unverified", []) + thin_unverified))
    if ext_key == "through_all":
        result["direction"] = side_read
    if through_all_removed is not None:
        result["through_all_volume_removed_cm3"] = through_all_removed
    if len(affected_comps) > 1:
        result["affected_components"] = affected_comps
    # An UNSCOPED cut/intersect takes every body that is BOTH coincident with the cut shape AND
    # visible; a hidden co-located body is spared. 'target_bodies' overrides visibility - a named
    # body is cut even while hidden - so the two levers are that input, or hiding what must survive.
    if scoped_to is None and op_key in ("cut", "intersect"):
        foreign = [c for c in affected_comps if c != sketch_owner]
        if foreign:
            result["cut_touched_other_components"] = foreign
            result["note"] += (f" WARNING: with no 'target_bodies' this {op_key} removed material from "
                               f"every VISIBLE body it intersects, including {', '.join(foreign)} "
                               "(hidden bodies are spared). Scope it by passing 'target_bodies' (a named "
                               "body is cut even if hidden), or hide the bodies that must be spared.")
    if split_count > 0:
        result["body_split"] = body_names
        result["note"] += (f" WARNING: this {op_key} DISCONNECTED the target - it created "
                           f"{split_count} additional disconnected body/bodies (the feature now yields "
                           f"{len(body_names)}: {', '.join(n for n in body_names if n)}). Reference "
                           "each piece by name; a later op assuming one body may hit the wrong piece.")
    return ok(result)


TOOL_DESCRIPTION = (
"Extrude sketch profiles/curves as solids or surfaces."
)

extrude_tool = (
    Tool.create_simple(name="model_extrude", description=TOOL_DESCRIPTION)
    .add_input_property("sketch_name", {"type": "string",
            "description": "Default: latest sketch."})
    .add_input_property("profile_index", {"type": ["integer", "string", "array"],
            "items": {"type": "integer"},
            "description": "Index/list, all, profile handle, or text:<i>."})
    .add_input_property("distance", {"type": ["number", "string"],
            "description": "Depth in units/expression; negative reverses; symmetric is per side."})
    .add_input_property("distance2", {"type": ["number", "string"]})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_input_property(*_inputs.boolean_op(default="new").as_property())
    .add_input_property(*_EXTENT.as_property())
    .add_input_property("symmetric", {"type": "boolean"})
    .add_input_property("taper_deg", {"type": "number"})
    .add_input_property("to_object", {"type": "string",
            "description": "Stop: find_geometry face or design_get(tree_bodies=true) body handle."})
    .add_input_property("target_bodies", _TARGET_BODIES.schema())
    .add_input_property(*_sketch_detail.COMPONENT_SCOPE)
    .add_input_property("as_surface", {"type": "boolean",
            "description": "SURFACE with no end caps: closed region or open curves."})
    .add_input_property("wall_thickness", {"type": ["number", "string"],
            "description": "Side-one wall thickness; requires wall_side."})
    .add_input_property("wall_side", {"type": "string", "enum": ["center", "side_one", "side_two"],
            "description": "Wall position; needs wall_thickness."})
    .add_input_property("wall_thickness_two", {"type": ["number", "string"],
            "description": "Side-two thickness; needs wall_side_two."})
    .add_input_property("wall_side_two", {"type": "string", "enum": ["center", "side_one", "side_two"],
            "description": "Side-two position; needs wall_thickness_two."})
    .add_input_property("start_offset", {"type": ["number", "string"],
            "description": "Sketch-plane start offset; units or expression."})
    .add_input_property("start_object", {"type": "string",
            "description": "Start BRepFace/plane handle."})
    .add_input_property("extent_one", {"type": "string", "enum": ["distance", "through_all", "to_face"],
            "description": "Side-one extent=two_side mode."})
    .add_input_property("extent_two", {"type": "string", "enum": ["distance", "through_all", "to_face"],
            "description": "Side-two extent=two_side mode."})
    .add_input_property("to_object_two", {"type": "string",
            "description": "Side-two BRepFace/BRepBody stop; to_face."})
    .add_input_property("taper_two_deg", {"type": "number", "description": "Side-two taper angle, degrees."})
    .add_input_property("minimum_solution", {"type": "boolean",
            "description": "BRepBody stop only: true=minimum; false=other."})
    .strict_schema()
)
extrude_item = Item.create_tool_item(tool=extrude_tool, write="write", handler=handler, run_on_main_thread=True,
                                     postconditions=[_assert.FeatureHealthy()],
                                     verification=Verification(
                                         kind="inline", rung="geometry",
                                         evidence_test="tests/unit/test_model_extrude.py"
                                         "::TestThroughAllVolumeCheck"
                                         "::test_no_volume_change_is_reported_as_error"))


def register_tool():
    register(extrude_item)
