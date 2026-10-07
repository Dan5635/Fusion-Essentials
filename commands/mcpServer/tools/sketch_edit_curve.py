# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: edit an EXISTING sketch curve in place - trim, extend, break, split, fillet,
chamfer, offset - instead of deleting and redrawing it. Those actions are positional: a pick point
chooses the segment, end, quadrant or side, and sketch curve methods take that point in SKETCH space
(SketchPoint.geometry is sketch space; worldGeometry is the separate world read). construction,
centerline and break_link set a flag on the curve and take no point. WRITES.
"""

import math

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import ok, error, safe
from . import _assert
from . import _common
from . import _inputs
from . import _sketch_detail

app = adsk.core.Application.get()

_ACTIONS = ("trim", "extend", "break", "split", "fillet", "chamfer", "offset", "construction",
            "centerline", "break_link")
# The two actions that set a flag on entity_one from 'state' and take no pick point.
_STATE_ACTIONS = ("construction", "centerline")
_BREAK_LINK = "break_link"
# Every action that only assigns a flag on entity_one: no curve is added, removed, moved or resized.
_FLAG_ACTIONS = _STATE_ACTIONS + (_BREAK_LINK,)
_ACTION = _inputs.Choice("action", list(_ACTIONS), required=True,
                         description="What the pick point selects - trim: the nearest segment. "
                                     "extend: the nearest end. break: the crossings either side. "
                                     "split: the point itself. fillet/chamfer: the corner between "
                                     "the two. offset: the chain and the side.")

_TWO_CURVE = ("fillet", "chamfer")

# SketchArcs.addFillet requires both curves OPEN; a SketchCircle/SketchEllipse is closed by
# construction, and a fitted spline reports its own isClosed.
_ALWAYS_CLOSED_KINDS = ("circle", "ellipse")


def _ref_kind(ref) -> str:
    """The '<type>' half of a '<type>:<index>' reference."""
    return (ref or "").strip().lower().rpartition(":")[0]


def _pt(x, y, k):
    """A sketch-space Point3D at (x, y) scaled to cm."""
    return adsk.core.Point3D.create(x * k, y * k, 0.0)


def _curve_count(sketch) -> int:
    return safe(lambda: sketch.sketchCurves.count, 0) or 0


def _collection_items(coll):
    """The members of an ObjectCollection, as a list."""
    return list(_common.iter_collection(coll))


def _curve_records(sketch, curves, f):
    """[{id, length}] per curve, the id re-read off the EDITED sketch. f = cm -> display unit."""
    out = []
    for c in curves:
        rec = {"id": _sketch_detail.curve_id(sketch, c),
               "length": _common.measured(lambda c=c: c.length, f, 4)}
        if rec["id"] is None:
            rec["type"] = type(c).__name__
        out.append(rec)
    return out


def _resolve_curve(sketch, ref, label):
    """(curve, error) for a '<type>:<index>' reference."""
    if not (ref or "").strip():
        return None, (f"'{label}' is required - a curve reference '<type>:<index>' "
                      "(e.g. 'line:0'), read from sketch_get(include_entities=true).")
    ent = _common.resolve_entity_ref(sketch, ref)
    if ent is None:
        return None, (f"'{label}' did not resolve '{ref}'. Use '<type>:<index>', type = "
                      + "/".join(_common.ENTITY_REF_KINDS)
                      + " - ids come from sketch_get(include_entities=true).")
    return ent, None


def _refuse_closed(ref, curve, label):
    """The error naming a CLOSED curve handed to fillet, or ''."""
    if _ref_kind(ref) in _ALWAYS_CLOSED_KINDS or safe(lambda: curve.isClosed) is True:
        return (f"fillet needs OPEN curves; '{label}' = '{ref}' is closed. Split or trim it first, "
                "or fillet two open curves.")
    return ""


def _single_curve_edit(action, curve, p1):
    """trim / extend / break / split. trim/break/split return the resulting curves as an
    ObjectCollection; extend edits in place and returns an empty one."""
    if action == "trim":
        return curve.trim(p1)
    if action == "extend":
        return curve.extend(p1)
    if action == "break":
        return curve.breakCurve(p1)
    return curve.split(p1)


# trim and split report "nothing matched" with an EMPTY ObjectCollection; breakCurve instead RAISES
# "Break is not available for this segment point", and extend returns an empty collection either
# way since it lengthens the curve in place. What each action needs, appended after the observation.
_NEEDS = {
    "trim": "a pick point on a segment bounded by a crossing curve",
    "break": "a curve that crosses another curve in the sketch",
    "split": "an OPEN curve and a point on it",
}

# cm; a length gain smaller than this is noise, not an extension.
_LENGTH_EPS_CM = 1e-9
_RADIUS_TOL_CM = 1e-4  # 0.001 mm comparison tolerance.


def _refuse_non_line(refs):
    """The error naming a non-line chamfer input, or ''. addDistanceChamfer/addAngleChamfer take
    SketchLine arguments only, and a 'line:N' reference indexes sketchCurves.sketchLines."""
    for label, ref in zip(("entity_one", "entity_two"), refs):
        if _ref_kind(ref) != "line":
            return (f"chamfer joins two straight LINES; '{label}' = '{ref}' is a "
                    f"{_ref_kind(ref) or 'malformed reference'}. Use fillet for an arc between "
                    "curves.")
    return ""


def _set_state(sketch, act, ref, curve, state):
    """Assign entity_one's construction or centerline flag and publish the flag as re-read."""
    name = safe(lambda: sketch.name)
    center = act == "centerline"
    if center and _ref_kind(ref) != "line":
        return error(f"centerline applies to a straight LINE; 'entity_one' = '{ref}' is a "
                     f"{_ref_kind(ref)}.")
    flag = (lambda: curve.isCenterLine) if center else (lambda: curve.isConstruction)
    before = _common.read_flag(flag)
    profiles_before = _common.counted(lambda: sketch.profiles.count)
    out = {"action": act, "sketch": name, "entity_one": ref, "requested": state,
           "state_before": before, "profile_count_before": profiles_before}
    if before is state:
        out.update(changed=False, state_after=before, profile_count_after=profiles_before,
                   note=f"'{ref}' already reads {act}={state}; nothing was written.")
        return ok(out)
    try:
        if center:
            curve.isCenterLine = state
        else:
            curve.isConstruction = state
    except Exception as e:
        return error(f"Could not set {act}={state} on '{ref}' in sketch '{name}': {e}")
    after = _common.read_flag(flag)
    if after is None:
        return error(f"{act}={state} was assigned to '{ref}' in sketch '{name}' but the flag did "
                     "not read back, so the change is unverified. Read it with "
                     "sketch_get(include_entities=true).")
    if after is not state:
        return error(f"{act} did not take - '{ref}' in sketch '{name}' still reads {after} after "
                     f"{state} was assigned.")
    out.update(changed=True, state_after=after,
               profile_count_after=_common.counted(lambda: sketch.profiles.count),
               note=f"'{ref}' {act} {before} -> {after}.")
    return ok(out)


def _curve_geometry(curve):
    """(length in cm, position fingerprint) of one curve, either None where it did not read."""
    return _common.measured(lambda: curve.length, 1.0, 7), _assert.entity_position(curve)


def _break_link(sketch, ref, curve, f, unit):
    """Assign entity_one's isReference False and publish the link flags as re-read."""
    name = safe(lambda: sketch.name)
    reference = _common.read_flag(lambda: curve.isReference)
    linked = _common.read_flag(lambda: curve.isLinked)
    if reference is None:
        return error(f"'{ref}' in sketch '{name}' did not read its reference flag, so break_link "
                     "wrote nothing. Read it with sketch_get(include_entities=true).")
    geometry = _curve_geometry(curve)
    constrained = _common.read_flag(lambda: sketch.isFullyConstrained)
    profiles = _common.counted(lambda: sketch.profiles.count)
    out = {"action": _BREAK_LINK, "sketch": name, "entity_one": ref,
           "reference_before": reference, "linked_before": linked,
           "fully_constrained_before": constrained, "profile_count_before": profiles}
    if reference is False:
        out.update(changed=False, reference_after=reference, linked_after=linked,
                   fully_constrained_after=constrained, profile_count_after=profiles,
                   note=f"'{ref}' is not a reference curve (reference=False), so there is no "
                        "link to break; nothing was written.")
        return ok(out)
    # isReference takes False only: assigning True afterwards raises, so the write is one-way.
    try:
        curve.isReference = False
    except Exception as e:
        after = _common.read_flag(lambda: curve.isReference)
        if after is False:
            return error(f"Breaking the link of '{ref}' in sketch '{name}' raised: {e}. The link "
                         f"IS broken - '{ref}' re-reads reference=False - and this tool cannot "
                         "restore it.")
        if after is None:
            return error(f"Breaking the link of '{ref}' in sketch '{name}' raised: {e}. Its "
                         "reference flag did not read back, so whether the link broke is not "
                         "known. Read it with sketch_get(include_entities=true).")
        return error(f"Could not break the link of '{ref}' in sketch '{name}': {e}. '{ref}' "
                     "still links to its source (it re-reads reference=True).")
    after = _common.read_flag(lambda: curve.isReference)
    if after is None:
        return error(f"reference=False was assigned to '{ref}' in sketch '{name}' but the flag did "
                     "not read back, so the break is unverified. Read it with "
                     "sketch_get(include_entities=true).")
    if after is not False:
        return error(f"break_link did not take - '{ref}' in sketch '{name}' still reads "
                     "reference=True after False was assigned.")
    linked_after = _common.read_flag(lambda: curve.isLinked)
    geometry_after = _curve_geometry(curve)
    length_after = _common.measured(lambda: curve.length, f, 4)
    unread = None in geometry or None in geometry_after
    if not unread and geometry != geometry_after:
        length = round(geometry[0] * f, 4)
        moved = "changed" if geometry[1] != geometry_after[1] else "unchanged"
        return error(f"The link of '{ref}' in sketch '{name}' broke (reference True -> False) AND "
                     f"the curve's geometry changed: length {length} -> {length_after} {unit}, "
                     f"position {moved}. This tool cannot restore the link; read the curve with "
                     "sketch_get(include_entities=true).")
    note = f"'{ref}' reference True -> False. This tool cannot restore the link"
    note += (", and the curve no longer follows its source." if linked_after is False else
             f". 'linked' reads {linked_after} after the write, so whether the curve still "
             "follows its source was not read.")
    if unread:
        note += (" geometry_unchanged is null: the curve's length or position did not read on "
                 "both sides of the write.")
    out.update(changed=True, reference_after=after, linked_after=linked_after,
               geometry_unchanged=None if unread else True, length=length_after, units=unit,
               fully_constrained_after=_common.read_flag(lambda: sketch.isFullyConstrained),
               profile_count_after=_common.counted(lambda: sketch.profiles.count),
               reversible=False, note=note)
    return ok(out)


def handler(action: str = "", sketch_name: str = "", entity_one: str = "", entity_two: str = "",
            units: str = "mm", x1: float = None, y1: float = None, x2: float = None,
            y2: float = None, radius: float = None, distance: float = None,
            distance_two: float = None, angle_deg: float = None, component: str = "",
            state=None) -> dict:
    """See TOOL_DESCRIPTION."""
    act, aerr = _ACTION.resolve(action)
    if aerr:
        return error(aerr)
    if act in _STATE_ACTIONS and not isinstance(state, bool):
        return error(f"'{act}' needs 'state' (true or false); got {state!r}.")
    if act == _BREAK_LINK and state is not None and state is not False:
        return error("break_link only breaks a link - this tool cannot re-establish one, so "
                     f"'state' must be false or omitted (got {state!r}).")
    if act not in _FLAG_ACTIONS and state is not None:
        return error(f"'state' applies to construction/centerline only; '{act}' takes none "
                     f"(got {state!r}).")

    unit = (units or "mm").strip().lower()
    k = _common.scale(unit)
    if k is None:
        return error(f"Unknown units '{units}'. Valid: mm, cm, in.")
    f = _common.CM_TO_UNIT[unit]

    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")

    sketch, requested, refusal = _sketch_detail.scoped_or_recent_sketch(
        design, sketch_name, component)
    if refusal:
        return error(refusal)
    if not sketch:
        if requested:
            return error(f"No sketch named '{requested}'. Available: "
                         + (", ".join(n for n in _common.all_sketch_names(design) if n) or "(none)"))
        return error("No sketch to edit. Draw one first with sketch_create + sketch_add_geometry.")

    e1, rerr = _resolve_curve(sketch, entity_one, "entity_one")
    if rerr:
        return error(rerr)
    if act in _STATE_ACTIONS:
        return _set_state(sketch, act, entity_one, e1, state)
    if act == _BREAK_LINK:
        return _break_link(sketch, entity_one, e1, f, unit)
    if x1 is None or y1 is None:
        return error(f"'{act}' needs the pick point x1,y1 (in 'units') - it chooses which segment, "
                     "end, quadrant or side of the curve the edit applies to.")
    p1 = _pt(x1, y1, k)

    e2 = None
    p2 = None
    if act in _TWO_CURVE:
        e2, rerr = _resolve_curve(sketch, entity_two, "entity_two")
        if rerr:
            return error(rerr)
        if x2 is None or y2 is None:
            return error(f"'{act}' needs a pick point on EACH curve: x1,y1 on entity_one and x2,y2 "
                         "on entity_two - together they choose the quadrant to build in.")
        p2 = _pt(x2, y2, k)

    if act == "fillet":
        if radius is None or radius <= 0:
            return error(f"fillet needs 'radius' > 0 (in 'units'); got {radius}.")
        for label, ref, curve in (("entity_one", entity_one, e1), ("entity_two", entity_two, e2)):
            cerr = _refuse_closed(ref, curve, label)
            if cerr:
                return error(cerr)
    elif act == "chamfer":
        cerr = _refuse_non_line((entity_one, entity_two))
        if cerr:
            return error(cerr)
        if distance is None or distance <= 0:
            return error(f"chamfer needs 'distance' > 0 (in 'units') - the setback along "
                         f"entity_one; got {distance}.")
        if distance_two is not None and angle_deg is not None:
            return error("chamfer takes EITHER 'distance_two' (a second setback) OR 'angle_deg' "
                         "(the angle from entity_one), not both.")
        if distance_two is not None and distance_two <= 0:
            return error(f"'distance_two' must be > 0; got {distance_two}.")
        if angle_deg is not None and not 0 < angle_deg < 180:
            return error(f"'angle_deg' must be between 0 and 180 exclusive; got {angle_deg}.")
    elif act == "offset":
        if distance is None or distance <= 0:
            return error(f"offset needs 'distance' > 0 (in 'units'); the SIDE comes from the pick "
                         f"point x1,y1, so the distance is a magnitude. Got {distance}.")

    errors_before, _warn_before, _total = _common.timeline_health(design)
    before_n = _curve_count(sketch)
    length_before = safe(lambda: e1.length) if act == "extend" else None
    source_curve_count = None

    try:
        if act in ("trim", "extend", "break", "split"):
            result = _single_curve_edit(act, e1, p1)
            created = _collection_items(result)
        elif act == "fillet":
            arc = sketch.sketchCurves.sketchArcs.addFillet(e1, p1, e2, p2, radius * k)
            created = [arc] if arc is not None else []
        elif act == "chamfer":
            lines = sketch.sketchCurves.sketchLines
            if angle_deg is not None:
                # addAngleChamfer takes the distance in centimeters and the angle in RADIANS.
                chamfer = lines.addAngleChamfer(e1, p1, e2, p2, distance * k,
                                                math.radians(angle_deg))
            else:
                second = distance if distance_two is None else distance_two
                chamfer = lines.addDistanceChamfer(e1, p1, e2, p2, distance * k, second * k)
            created = [chamfer] if chamfer is not None else []
        else:
            # Sketch.offset takes a set of END-CONNECTED curves; findConnectedCurves returns exactly
            # that chain, in connected order, with the input curve among them.
            chain = safe(lambda: sketch.findConnectedCurves(e1))
            if chain is None or (safe(lambda: chain.count, 0) or 0) == 0:
                chain = adsk.core.ObjectCollection.create()
                chain.add(e1)
            source_curve_count = safe(lambda: chain.count, 0) or 0
            created = _collection_items(sketch.offset(chain, p1, distance * k))
    except Exception as e:
        needs = _NEEDS.get(act)
        return error(f"Could not {act} '{entity_one}' in sketch "
                     f"'{safe(lambda: sketch.name)}': {e}"
                     + (f" '{act}' needs {needs}." if needs else ""))

    after_n = _curve_count(sketch)
    if act == "extend":
        length_after = safe(lambda: e1.length)
        grew = (isinstance(length_before, float) and isinstance(length_after, float)
                and length_after - length_before > _LENGTH_EPS_CM)
        if not grew:
            return error("extend changed nothing - the end nearest the pick point could not be "
                         f"extended. The sketch still holds {after_n} curve(s). Re-read "
                         "sketch_get(include_entities=true) and pick a point ON the curve.")
        created = [e1]
    elif not created and after_n >= before_n:
        needs = _NEEDS.get(act)
        tail = f" '{act}' needs {needs}." if needs else ""
        return error(f"{act} returned no curves and the sketch still holds {after_n} curve(s), so "
                     f"nothing changed.{tail} Re-read sketch_get(include_entities=true) for the "
                     "current ids and pick a point ON the curve.")

    solved_radius = None
    if act == "fillet":
        arc = created[0] if created else None
        solved_radius = safe(lambda: arc.radius)
        readable = (isinstance(solved_radius, (int, float)) and not isinstance(solved_radius, bool)
                    and math.isfinite(solved_radius) and solved_radius > 0)
        if not readable or not math.isclose(solved_radius, radius * k, rel_tol=1e-6,
                                           abs_tol=_RADIUS_TOL_CM):
            retained = _curve_records(sketch, [arc, e1, e2], f)
            for row, curve in zip(retained, [arc, e1, e2]):
                row.update(safe(lambda c=curve: _sketch_detail._line_geo(c, f), {}))
            observed = round(solved_radius * f, 6) if readable else None
            return error(f"Fillet radius requested {radius!a} {unit}, solved {observed!a} {unit}. "
                         f"The edit REMAINS; retained sketch-local curves in {unit}: {retained!a}. "
                         "Read sketch_get(include_entities=true) to inspect the arc and neighbors; "
                         "the user can Undo this edit in Fusion's UI.")

    errors_after, _warn_after, _total_after = _common.timeline_health(design)
    broke = [n for n in errors_after if n not in errors_before]

    note = ("Curve ids are creation-order indexes per kind: removing a curve RENUMBERS the ones "
            "after it, while an added curve APPENDS at the end (both measured) - re-read "
            "sketch_get(include_entities=true) before the next edit.")
    if not created and after_n < before_n:
        note = ("The whole curve was consumed: a trim on a curve with no intersections deletes it "
                "outright. " + note)
    if broke:
        note += (" This edit put " + ", ".join(broke) + " into an error state - the feature(s) "
                 "downstream of this sketch no longer compute.")

    out = {
        "action": act,
        "sketch": safe(lambda: sketch.name),
        "entity_one": entity_one,
        "units": unit,
        "curve_count_before": before_n,
        "curve_count_after": after_n,
        "resulting": _curve_records(sketch, created, f),
        "note": note,
    }
    if act in _TWO_CURVE:
        out["entity_two"] = entity_two
    if solved_radius is not None:
        out["radius"] = round(solved_radius * f, 6)
    if source_curve_count is not None:
        out["source_curve_count"] = source_curve_count
    if broke:
        out["downstream_broken"] = broke
    return ok(out)


TOOL_DESCRIPTION = (
    "Edit an EXISTING sketch curve in place. x1,y1 (and x2,y2) is the pick point, in 'units' in "
    "the sketch's own frame."
)

tool = (
    Tool.create_simple(name="sketch_edit_curve", description=TOOL_DESCRIPTION)
    .add_input_property(*_ACTION.as_property())
    .add_required_input("action")
    .add_input_property("sketch_name", {"type": "string",
            "description": "Default: most recent."})
    .add_input_property(*_sketch_detail.COMPONENT_SCOPE)
    .add_input_property("entity_one", {"type": "string"})
    .add_input_property("entity_two", {"type": "string"})
    .add_input_property("x1", {"type": "number"})
    .add_input_property("y1", {"type": "number"})
    .add_input_property("x2", {"type": "number"})
    .add_input_property("y2", {"type": "number"})
    .add_input_property("radius", {"type": "number"})
    .add_input_property("distance", {"type": "number",
            "description": "Chamfer setback one; offset distance."})
    .add_input_property("distance_two", {"type": "number",
            "description": "Chamfer setback two (default: distance)."})
    .add_input_property("angle_deg", {"type": "number",
            "description": "Chamfer angle from entity_one."})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_input_property("state", {"type": "boolean"})
    .strict_schema()
)


class _CurvesChangedUnlessFlag(_assert.SketchCurvesChanged):
    """SketchCurvesChanged, not run for the flag actions: their handler re-reads the flag."""

    def verify(self, kwargs, payload, before):
        if payload.get("action") in _FLAG_ACTIONS:
            return "", {}
        return super().verify(kwargs, payload, before)


item = Item.create_tool_item(tool=tool, write="write", handler=handler, run_on_main_thread=True,
                             postconditions=[_CurvesChangedUnlessFlag(
                                 scope_keys=("component",))])


def register_tool():
    register(item)
