# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: MOVE existing sketch entities by one transform in the sketch's own frame.
WRITES; the move is judged by the entities' coordinates, never by Sketch.move's own bool.
"""

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

# cm; a coordinate change below this is solver round-off, not a move.
_MOVE_EPS_CM = 1e-7


def _moved(before, after):
    """True when two position fingerprints differ by more than round-off, False when every readable
    sample matches, None when nothing comparable could be read (no verdict). A fingerprint is a
    tuple of (x, y, z) samples - box corners and endpoints - any of which is None for an entity that
    does not carry it, so only the samples present on BOTH sides are compared."""
    if before is None or after is None:
        return None
    pairs = [(b, a) for b, a in zip(before, after) if b is not None and a is not None]
    if not pairs:
        return None
    return any(abs(bv - av) > _MOVE_EPS_CM for b, a in pairs for bv, av in zip(b, a))


def _lifted(position):
    """True when any read sample of a position fingerprint sits off the sketch plane."""
    return any(mark is not None and abs(mark[2]) > _MOVE_EPS_CM for mark in position)


# This tool's own bound on the curves it re-reads for motion nobody asked for.
_FOLLOW_SCAN = 400


def _bystanders(sketch, ents):
    """([(curve, position)], complete) for the curves not asked to move; False on an unread one."""
    rows, complete = [], True
    count = _common.counted(lambda: sketch.sketchCurves.count)
    if count is None or count > _FOLLOW_SCAN:
        return rows, False
    for i in range(count):
        curve = safe(lambda i=i: sketch.sketchCurves.item(i))
        if curve is None:
            complete = False
            continue
        # Entity equality, never a token string: two tokens of one entity need not match.
        same = [safe(lambda e=e: e == curve) for e in ents]
        if any(s is True for s in same):
            continue
        if any(s is not False for s in same):
            complete = False
        rows.append((curve, _assert.entity_position(curve)))
    return rows, complete


def handler(sketch_name: str = "", entities: str = "", units: str = "mm", dx=None, dy=None,
            rotation_deg=None, center_x=None, center_y=None, scale_factor=None,
            component: str = "", dz=None) -> dict:
    """See TOOL_DESCRIPTION."""
    design, sketch, ents, refs, coll, matrix, unit, err = _prepare(
        sketch_name, entities, units, dx, dy, rotation_deg, center_x, center_y, scale_factor,
        component, dz=dz)
    if err:
        return err

    name = safe(lambda: sketch.name)
    profiles_before = _common.counted(lambda: sketch.profiles.count) if dz else None
    errors_before, _warn, _total = _common.timeline_health(design)
    before = [_assert.entity_position(e) for e in ents]
    others, others_read = _bystanders(sketch, ents)
    try:
        did = sketch.move(coll, matrix)
    except Exception as e:
        # A raise can still have landed the transform before failing later in the same call (a
        # stitch/thicken/fillet dependency downstream) - the re-read coordinates say which, not
        # the exception text alone.
        after = [_assert.entity_position(ent) for ent in ents]
        verdicts = [_moved(b, a) for b, a in zip(before, after)]
        if any(v is True for v in verdicts):
            errors_after, _warn_after, _total_after = _common.timeline_health(design)
            broke = [n for n in errors_after if n not in errors_before]
            outcome = (f"the coordinates changed - it landed, and {len(broke)} dependent "
                       "feature(s) now read error/warning")
        elif verdicts and all(v is False for v in verdicts):
            outcome = "the coordinates read the same as before the call - it rolled back"
        else:
            outcome = "the coordinates did not re-read, so whether it rolled back is not known"
        return error(f"Could not move {', '.join(refs)} in sketch '{name}': {e}. {outcome}.")
    # The bool cannot be the verdict: "Transform respects any constraints that would normally
    # prohibit the move", so a refused entity and a moved one share one true return. Coordinates
    # decide instead - and isFixed does NOT hold an entity still against an API move.
    after = [_assert.entity_position(e) for e in ents]
    verdicts = [_moved(b, a) for b, a in zip(before, after)]
    moved = [r for r, v in zip(refs, verdicts) if v is True]
    stayed = [r for r, v in zip(refs, verdicts) if v is False]
    unread = [r for r, v in zip(refs, verdicts) if v is None]

    if not did and not moved:
        return error(f"Fusion declined the move in sketch '{name}' (Sketch.move returned false) and "
                     f"none of {', '.join(refs)} changed position.")
    if not moved and not unread:
        return error(f"move returned {bool(did)} but {', '.join(refs)} read the same coordinates "
                     "afterwards, so nothing in the sketch changed. Either the transform is one "
                     "this geometry is symmetric under (a circle rotated about its own centre), or "
                     "a constraint refused it: sketch_get(include_entities=true) lists this "
                     "sketch's constraints and dimensions, and "
                     "sketch_delete_entity(target='constraint:<index>') removes one.")

    errors_after, _warn_after, _total_after = _common.timeline_health(design)
    broke = [n for n in errors_after if n not in errors_before]
    note = ("The entities keep their ids - a move adds and removes nothing, so no renumbering. "
            "Re-read sketch_get(include_entities=true) for the new coordinates.")
    if stayed:
        note = (f"Partial: {', '.join(stayed)} read the same coordinates afterwards - an existing "
                "constraint or dimension refused the move for those, or the transform leaves them "
                "where they were. " + note)
    if not did:
        note = ("Sketch.move returned false yet the coordinates changed - this reports what the "
                "geometry shows, not the return value. " + note)
    if unread:
        note += (f" {', '.join(unread)} could not be re-read, so its move is unconfirmed.")
    if broke:
        note += (" This edit put " + ", ".join(broke) + " into an error state - the feature(s) "
                 "downstream of this sketch no longer compute.")

    out = {"moved": True, "sketch": name, "entities": refs, "moved_entities": moved,
           "requested": _requested(unit, dx, dy, rotation_deg, scale_factor, dz), "note": note}
    # A shared point or a constraint carries the move to curves nobody named; they are told apart
    # from the request.
    verdicts_other = [(curve, _moved(was, _assert.entity_position(curve))) for curve, was in others]
    followed = [curve for curve, verdict in verdicts_other if verdict is True]
    if any(verdict is None for _curve, verdict in verdicts_other):
        others_read = False
    if followed:
        named = [_sketch_detail.curve_id(sketch, c) or "an unnamed curve" for c in followed]
        out["followed_entities"] = named
        out["note"] += (f" {len(named)} entit{'y' if len(named) == 1 else 'ies'} not asked for "
                        "moved too, through shared points or constraints.")
    if not others_read:
        out["followed_entities_read"] = False
    if dz:
        # A loop moved off its plane as a whole keeps its profile; one that stops being planar
        # loses it, so the count is published on both sides of the move.
        down = [pos is not None and not _lifted(pos) for pos in after]
        was_up = [pos is not None and _lifted(pos) for pos in before]
        flat = [r for r, d, u in zip(refs, down, was_up) if d and not u]
        back = [r for r, d, u in zip(refs, down, was_up) if d and u]
        profiles_after = _common.counted(lambda: sketch.profiles.count)
        out.update(profile_count_before=profiles_before, profile_count_after=profiles_after)
        if back:
            out["returned_to_plane"] = back
        if flat:
            out["note"] = (f"{', '.join(flat)} still read z = 0 on every point after a dz move. "
                           + out["note"])
            out["on_plane_entities"] = flat
        if None not in (profiles_before, profiles_after) and profiles_after < profiles_before:
            out["note"] += (f" The sketch went from {profiles_before} to {profiles_after} "
                            "profile(s): a loop that is no longer planar bounds none.")
    if stayed:
        out["unmoved_entities"] = stayed
    if unread:
        out["unverified_entities"] = unread
    if broke:
        out["downstream_broken"] = broke
    return ok(out)


TOOL_DESCRIPTION = (
    "MOVE existing sketch entities by one transform. Selected entities may propagate motion "
    "through constraints."
)

tool = _transform_wire(
    Tool.create_simple(name="sketch_move", description=TOOL_DESCRIPTION)
    .add_input_property("sketch_name", {"type": "string"})
    .add_input_property(*_sketch_detail.COMPONENT_SCOPE))

item = Item.create_tool_item(tool=tool, write="write", handler=handler,
                             run_on_main_thread=True,
                             postconditions=[_assert.SketchCurvesChanged(
                                 scope_keys=("component",))])


def register_tool():
    register(item)
