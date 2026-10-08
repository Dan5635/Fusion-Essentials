# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: COPY existing sketch entities through a transform, into this sketch or
another one. WRITES; the copy is proven by the TARGET's own curve-count delta.
"""

import math

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import ok, error, safe
from . import _assert
from . import _common
from . import _sketch_detail
from ._sketch_detail import _prepare, _requested, _transform_wire

app = adsk.core.Application.get()


def _curve_ref_by_token(sketch):
    """entityToken -> '<type>:<index>' for the sketch's curves, MINUS any token two curves share (the
    pieces a split returns carry one token, see _sketch_detail.curve_id) - a shared token names
    neither of them, so it is dropped rather than resolved to the first hit."""
    refs, shared = {}, set()
    # The index IS the published address ('<kind>:<index>' is what _common.resolve_entity_ref reads
    # back with coll.item(index)), so this stays a positional walk: iter_collection drops an
    # unreadable curve, which would mint refs pointing at the wrong entities.
    for kind, coll in _sketch_detail._curve_collections(sketch):
        for i in range(safe(lambda coll=coll: coll.count, 0) if coll else 0):
            tok = safe(lambda coll=coll, i=i: coll.item(i).entityToken)
            if not tok:
                continue
            if tok in refs:
                shared.add(tok)
            else:
                refs[tok] = f"{kind}:{i}"
    for tok in shared:
        refs.pop(tok, None)
    return refs


def _copied_refs(target, items):
    """The '<type>:<index>' refs of the copied curves, resolved through each returned entity's
    nativeObject; a copied endpoint resolves to none, being no curve of the target."""
    # For a sketch a COMPONENT owns, Sketch.copy hands back assembly-context PROXIES while the
    # sketch's collections hold the NATIVE curves, and neither identity nor entityToken crosses that
    # seam. `nativeObject` does, and reads None for an already-native entity.
    by_token = _curve_ref_by_token(target)
    refs = []
    for c in items:
        native = safe(lambda c=c: c.nativeObject) or c
        tok = safe(lambda native=native: native.entityToken)
        ref = by_token.get(tok) if tok else None
        if ref is None:
            ref = _sketch_detail.curve_id(target, native)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


# Two sketch positions closer than this (cm) are the same position to the mirror check.
_MIRROR_TOL_CM = 1e-6


def _key_points(curve):
    """(end points, centre or None) of a sketch curve as (x, y) cm; a part that does not read is absent."""
    ends = []
    for name in ("startSketchPoint", "endSketchPoint"):
        g = safe(lambda name=name: getattr(curve, name).geometry)
        if g is not None:
            ends.append((g.x, g.y))
    c = safe(lambda: curve.centerSketchPoint.geometry)
    return ends, ((c.x, c.y) if c is not None else None)


def _in_plane(curve, circle=False):
    """True when each end (a circle: its centre) reads z = 0, False when one does not, else None."""
    zs = [safe(lambda n=n: getattr(curve, n).geometry.z)
          for n in (("centerSketchPoint",) if circle else ("startSketchPoint", "endSketchPoint"))]
    if any(not isinstance(z, (int, float)) for z in zs):
        return None
    return all(abs(z) <= _MIRROR_TOL_CM for z in zs)


def _arc_middle(ends, centre):
    """The point halfway along an arc stored counter-clockwise from ends[0] to ends[1]."""
    start = math.atan2(ends[0][1] - centre[1], ends[0][0] - centre[0])
    sweep = (math.atan2(ends[1][1] - centre[1], ends[1][0] - centre[0]) - start) % (2 * math.pi)
    radius = math.hypot(ends[0][0] - centre[0], ends[0][1] - centre[1])
    return (centre[0] + radius * math.cos(start + sweep / 2),
            centre[1] + radius * math.sin(start + sweep / 2))


def _on_arc(point, ends, centre):
    """True when `point` lies on the counter-clockwise sweep from ends[0] to ends[1]."""
    start = math.atan2(ends[0][1] - centre[1], ends[0][0] - centre[0])
    sweep = (math.atan2(ends[1][1] - centre[1], ends[1][0] - centre[0]) - start) % (2 * math.pi)
    at = (math.atan2(point[1] - centre[1], point[0] - centre[0]) - start) % (2 * math.pi)
    radius = math.hypot(ends[0][0] - centre[0], ends[0][1] - centre[1])
    return (abs(math.hypot(point[0] - centre[0], point[1] - centre[1]) - radius) <= _MIRROR_TOL_CM
            and at <= sweep + 1e-9)


def _reflect(p, a, b):
    """`p` reflected about the line through `a` and `b`."""
    ux, uy = b[0] - a[0], b[1] - a[1]
    t = ((p[0] - a[0]) * ux + (p[1] - a[1]) * uy) / (ux * ux + uy * uy)
    return (2 * (a[0] + t * ux) - p[0], 2 * (a[1] + t * uy) - p[1])


def _same_points(got, want):
    """True when the two point lists hold the same positions, in any order."""
    left = list(want)
    for p in got:
        hit = next((q for q in left if math.hypot(p[0] - q[0], p[1] - q[1]) <= _MIRROR_TOL_CM), None)
        if hit is None:
            return False
        left.remove(hit)
    return not left


def _mirror(sketch_name, entities, mirror_line, component, others):
    """Mirror `entities` about `mirror_line` in their own sketch, checked point by point."""
    stray = [name for name, value in others.items() if value not in (None, "")]
    if stray:
        return error("mirror_line mirrors in place of a transform, in the same sketch. Drop: "
                     + ", ".join(stray) + ".")
    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")
    sketch, requested, refusal = _sketch_detail.scoped_or_recent_sketch(design, sketch_name,
                                                                        component)
    if refusal:
        return error(refusal)
    if not sketch:
        return error(f"No sketch named '{requested}'. Available: " + (
            ", ".join(n for n in _common.all_sketch_names(design) if n) or "(none)")
            if requested else "No sketch to mirror in. Draw one first with sketch_create.")
    name = safe(lambda: sketch.name)
    other = [r.strip() for r in (entities or "").split(",")
             if r.strip() and r.strip().lower().rpartition(":")[0] not in ("line", "arc", "circle")]
    if other:
        return error(f"mirror_line mirrors lines, arcs and circles; {', '.join(other)} is none of "
                     "them. Mirror those, and draw the rest.")
    ents, refs, rerr = _common.resolve_entity_refs(sketch, entities)
    if rerr:
        return error(rerr)
    if not refs:
        return error("'entities' is required - comma-separated '<type>:<index>' curve refs from "
                     "sketch_get(include_entities=true).")
    axis_ref = (mirror_line or "").strip().lower()
    axis = _common.resolve_entity_ref(sketch, axis_ref) if axis_ref.startswith("line:") else None
    if axis is None:
        return error(f"mirror_line must be a 'line:<index>' of sketch '{name}'. Got '{mirror_line}'.")
    if any(safe(lambda e=e: e == axis) is True for e in ents):
        return error(f"mirror_line '{mirror_line}' is also in 'entities'; a line cannot be mirrored "
                     "about itself.")
    axis_ends = _key_points(axis)[0]
    if len(axis_ends) != 2 or math.hypot(axis_ends[1][0] - axis_ends[0][0],
                                         axis_ends[1][1] - axis_ends[0][1]) <= _MIRROR_TOL_CM:
        return error(f"mirror_line '{mirror_line}' has no readable length.")
    a, b = axis_ends

    round_ = [ref.lower().startswith("circle:") for ref in refs]
    for ref, curve, is_circle in list(zip(refs, ents, round_)) + [(mirror_line, axis, False)]:
        flat = _in_plane(curve, is_circle)
        if flat is not True:
            return error(f"mirror_line works in the sketch plane; '{ref}' "
                         + (f"has {'its centre' if is_circle else 'an end'} off it (z is not 0)."
                            if flat is False else "did not read its points.")
                         + " Nothing was mirrored.")
    before = [_key_points(e) for e in ents]
    if any(len(ends) != (0 if is_circle else 2)
           for (ends, _centre), is_circle in zip(before, round_)):
        return error("An end point of one of the entities did not read; nothing was mirrored.")
    for ref, (_ends, centre) in zip(refs, before):
        if not ref.lower().startswith("line:") and centre is None:
            return error(f"The centre of '{ref}' did not read, so its mirror could not be "
                         "checked; nothing was mirrored.")
    radii = [_common.measured(lambda e=e: e.radius, 1.0, 9) if is_circle else None
             for e, is_circle in zip(ents, round_)]
    if any(is_circle and not r for r, is_circle in zip(radii, round_)):
        return error("The radius of a circle did not read, so its mirror could not be checked; "
                     "nothing was mirrored.")
    curves_before = safe(lambda: sketch.sketchCurves.count, 0) or 0
    constraints_before = safe(lambda: sketch.geometricConstraints.count)
    try:
        # Sketch.mirror takes a Python list; the first len(list) results are the mirrored curves in
        # input order, the auxiliary points follow.
        made = sketch.mirror(list(ents), axis)
    except Exception as e:
        return error(f"Could not mirror {', '.join(refs)} about '{mirror_line}' in sketch "
                     f"'{name}': {e}")
    count = safe(lambda: len(made), 0) if made is not None else 0
    curves_after = safe(lambda: sketch.sketchCurves.count, 0) or 0
    if count < len(ents) or curves_after - curves_before != len(ents):
        return error(f"mirror returned {count} entity(ies) and sketch '{name}' went from "
                     f"{curves_before} to {curves_after} curve(s) for {len(ents)} asked - re-read "
                     "sketch_get(include_entities=true) before going on.")
    copies = [made[i] for i in range(len(ents))]
    left = "They are in the sketch; sketch_delete_entity removes them."
    for ref, source, was, copy, radius in zip(refs, ents, before, copies, radii):
        now = _key_points(source)
        if not _same_points(now[0], was[0]) or not _same_points(
                [p for p in (now[1],) if p], [p for p in (was[1],) if p]):
            return error(f"mirror moved its source '{ref}'. {left}")
        ends, centre = _key_points(copy)
        want_ends = [_reflect(p, a, b) for p in was[0]]
        want_centre = _reflect(was[1], a, b) if was[1] is not None else None
        wrong = (not _same_points(ends, want_ends)
                 or _in_plane(copy, radius is not None) is not True
                 or (centre is None) != (want_centre is None))
        if radius is not None:
            # A circle: the reflected centre and the same radius are the whole curve.
            got = _common.measured(lambda copy=copy: copy.radius, 1.0, 9)
            wrong = (wrong or not _same_points([centre], [want_centre]) or got is None
                     or abs(got - radius) > _MIRROR_TOL_CM
                     or _common.measured(lambda source=source: source.radius, 1.0, 9) != radius)
        elif not wrong and want_centre is not None:
            # An arc: same centre and ends are shared by its complement, so the reflected middle
            # of the source has to lie on the copy's own sweep; that fixes the radius too.
            wrong = (not _same_points([centre], [want_centre])
                     or not _on_arc(_reflect(_arc_middle(was[0], was[1]), a, b), ends, centre))
        if wrong:
            return error(f"The curve built for '{ref}' is not its reflection about "
                         f"'{mirror_line}'. {left}")
    new_refs = _copied_refs(sketch, copies)
    constraints_after = safe(lambda: sketch.geometricConstraints.count)
    out = {"mirrored": True, "sketch": name, "mirror_line": mirror_line, "entities": refs,
           "new_curves": new_refs, "curve_count_before": curves_before,
           "curve_count_after": curves_after,
           "note": ("Each copy follows its original through symmetry constraints; "
                    "sketch_delete_entity on those constraints frees it.")}
    if constraints_before is not None and constraints_after is not None:
        out["constraints_added"] = constraints_after - constraints_before
    if len(new_refs) < len(ents):
        out["new_curves_complete"] = False
        out["note"] += " Re-read sketch_get(include_entities=true) for the copies not named here."
    return ok(out)


def handler(sketch_name: str = "", entities: str = "", target_sketch: str = "",
            units: str = "mm", dx=None, dy=None, rotation_deg=None, center_x=None,
            center_y=None, scale_factor=None, component: str = "",
            target_component: str = "", mirror_line: str = "", dz=None) -> dict:
    """See TOOL_DESCRIPTION."""
    if (mirror_line or "").strip():
        return _mirror(sketch_name, entities, mirror_line, component, {
            "dx": dx, "dy": dy, "rotation_deg": rotation_deg, "center_x": center_x,
            "center_y": center_y, "scale_factor": scale_factor, "target_sketch": target_sketch,
            "target_component": target_component, "dz": dz})
    design, sketch, ents, refs, coll, matrix, unit, err = _prepare(
        sketch_name, entities, units, dx, dy, rotation_deg, center_x, center_y, scale_factor,
        component, target_sketch, target_component, dz=dz)
    if err:
        return err

    name = safe(lambda: sketch.name)
    want_target = (target_sketch or "").strip()
    target = sketch
    if want_target:
        # The destination gets its own scope: it is a SECOND by-name sketch reference, and a copy
        # into a name two components carry has to be able to say which one without renaming either.
        target, refusal = _sketch_detail.scoped_sketch(design, want_target, target_component,
                                                       "target_component")
        if refusal:
            return error(refusal)
        if target is None:
            return error(f"No sketch named '{want_target}' for 'target_sketch'. Available: " + (
                ", ".join(n for n in _common.all_sketch_names(design) if n) or "(none)"))
    target_name = safe(lambda: target.name)

    before_n = safe(lambda: target.sketchCurves.count, 0) or 0
    try:
        # targetSketch is passed ONLY when one was asked for - a same-sketch copy is the measured
        # two-argument form.
        created = sketch.copy(coll, matrix, target) if want_target else sketch.copy(coll, matrix)
    except Exception as e:
        return error(f"Could not copy {', '.join(refs)} from sketch '{name}' into "
                     f"'{target_name}': {e}")
    if created is None:
        return error(f"copy returned no collection for {', '.join(refs)} in sketch '{name}' - "
                     "nothing was copied.")

    # The returned collection counts the copied curves' SKETCH POINTS too (measured: copying ONE
    # line returns 3), so the curve-count delta on the TARGET is the honest read-back, and the
    # nativeObject bridge (see _copied_refs) is what turns the returned entities into refs.
    n = safe(lambda: created.count, 0) or 0
    items = list(_common.iter_collection(created))
    new_curves = _copied_refs(target, items)
    after_n = safe(lambda: target.sketchCurves.count, 0) or 0
    if after_n <= before_n:
        return error(f"copy returned {n} entity(ies) but sketch '{target_name}' still holds "
                     f"{after_n} curve(s) - nothing landed in it.")

    landed = after_n - before_n
    note = ("The new curves' ids are in '" + (target_name or "the target sketch") + "', and an "
            "added curve APPENDS at the end of its kind, so the ids already in use keep their "
            "entities - re-read sketch_get(include_entities=true) for the new ones. "
            "'returned_entity_count' counts the copied endpoints as well as the curves.")
    # The count delta is what proves the copy landed; the refs are the convenience on top. When a
    # copied curve's token does not answer (or two curves share one), say which of the landed curves
    # went unnamed instead of returning a short list that reads as the whole truth.
    if len(new_curves) < landed:
        where = target_name or "the target sketch"
        note = ((f"{landed} curve(s) landed in '{where}' but NONE could be identified by "
                 "entityToken - re-read sketch_get(include_entities=true) for their ids. "
                 if not new_curves else
                 f"{landed} curve(s) landed in '{where}'; only {len(new_curves)} could be "
                 f"identified ({', '.join(new_curves)}) - re-read "
                 "sketch_get(include_entities=true) for the rest. ") + note)
    out = {"copied": True, "sketch": name, "target_sketch": target_name, "entities": refs,
           "new_curves": new_curves, "curve_count_before": before_n, "curve_count_after": after_n,
           "returned_entity_count": n,
           "requested": _requested(unit, dx, dy, rotation_deg, scale_factor, dz),
           "note": note}
    if len(new_curves) < landed:
        out["new_curves_complete"] = False
    return ok(out)


TOOL_DESCRIPTION = (
    "COPY sketch entities, transformed or mirrored."
)

tool = _transform_wire(
    Tool.create_simple(name="sketch_copy", description=TOOL_DESCRIPTION)
    .add_input_property("sketch_name", {"type": "string"})
    .add_input_property(*_sketch_detail.COMPONENT_SCOPE)
    .add_input_property("target_sketch", {"type": "string"})
    .add_input_property(*_sketch_detail.component_scope("target_component",
                                                        narrows="target_sketch"))
    .add_input_property("mirror_line", {"type": "string", "description": (
        "Mirror about this 'line:<index>'; no transform. Copies follow their originals.")}))

# A cross-sketch copy leaves the SOURCE untouched, so the effect is verified on the TARGET. Each
# name is paired with the scope that narrows THAT reference - 'target_sketch' with
# 'target_component' - so the fingerprint reads the sketch the copy wrote, never the source's.
item = Item.create_tool_item(tool=tool, write="write", handler=handler,
                             run_on_main_thread=True,
                             postconditions=[_assert.SketchCurvesChanged(
                                 keys=("target_sketch", "sketch_name"),
                                 scope_keys=("target_component", "component"))])


def register_tool():
    register(item)
