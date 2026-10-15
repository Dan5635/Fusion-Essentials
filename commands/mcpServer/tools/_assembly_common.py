# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The occurrence WORLD-POSE sampler an assembly write is judged by: where every target part sat
before the mutation, and which of them moved across it - translation AND rotation."""

from ._common import safe
from . import _common

MAP_BLURB = (
    "the occurrence WORLD-POSE sampler an assembly write is judged by: _constraint_positions - "
    "every target's translation and basis BEFORE the mutation, an unread one ABSENT, not "
    "zeroed; _constraint_moves - which moved across it (translation plus _axes_rotation_deg, "
    "the flip a translation-only row hides), and whether ANY target was sampled on both "
    "sides; _occ_origin/_move_delta - one occurrence's shift")


def _occ_origin(occ):
    """A placed occurrence's world translation in cm, or None."""
    point = _common.occurrence_world_translation(occ)
    return tuple(point.values()) if point is not None else None


# Above this the reposition is reported as moved_by. 0.005 cm = 0.05 mm - below it the move is joint
# solver noise, not a teleport worth flagging.
_MOVE_TOL_CM = 0.005


def _move_delta(before, after):
    """{distance_mm, direction} if the moving occurrence shifted more than _MOVE_TOL_CM, else
    None."""
    # joint_at aligns the two picked KEYPOINTS (a planar face's centroid, an edge's midpoint), so
    # pairing a small feature with a large one repositions the part by the keypoint gap.
    if before is None or after is None:
        return None
    dx, dy, dz = after[0] - before[0], after[1] - before[1], after[2] - before[2]
    dist = (dx * dx + dy * dy + dz * dz) ** 0.5
    if dist <= _MOVE_TOL_CM:
        return None
    inv = 1.0 / dist
    return {"distance_mm": round(dist * 10.0, 3),
            "direction": [round(dx * inv, 4), round(dy * inv, 4), round(dz * inv, 4)]}


def _occ_axes(occ):
    """The occurrence's world basis axes as three unit tuples, or None when unreadable - the
    ROTATION half of the moved verdict (a flip=true relationship can rotate a part 180 deg while
    translating it barely at all; a translation-only row implied a placement that was not what
    happened - measured)."""
    cs = safe(lambda: occ.transform2.getAsCoordinateSystem())
    if not cs:
        return None
    axes = []
    for v in cs[1:4]:
        t = (safe(lambda v=v: v.x), safe(lambda v=v: v.y), safe(lambda v=v: v.z))
        if any(c is None for c in t):
            return None
        axes.append(t)
    return tuple(axes)


def _axes_rotation_deg(a, b):
    """The largest angle (deg) any basis axis swung between two _occ_axes reads; None if either is
    absent."""
    if not a or not b:
        return None
    import math as _m
    worst = 0.0
    for (ax, ay, az), (bx, by, bz) in zip(a, b):
        dot = max(-1.0, min(1.0, ax * bx + ay * by + az * bz))
        worst = max(worst, _m.degrees(_m.acos(dot)))
    return worst


def _constraint_positions(targets):
    """{label: ((x, y, z) cm, axes-or-None)} - the WORLD translation and basis of every target
    occurrence that reads one. An occurrence whose transform cannot be read is ABSENT from the map,
    never a zero: the moved verdict is only computed where both sides were actually sampled."""
    out = {}
    for label, occ in targets.items():
        if occ is None:
            continue
        pos = _occ_origin(occ)
        if pos is not None:
            out[label] = (pos, _occ_axes(occ))
    return out


def _constraint_moves(before, targets):
    """([{occurrence, distance_mm, direction, rotation_deg?}], measured) for the constrained
    occurrences. 'measured' is False when no target could be sampled on BOTH sides of the add, where
    the verdict is UNKNOWN rather than "nothing moved"."""
    rows, measured = [], False
    for label, occ in targets.items():
        if occ is None or label not in before:
            continue
        after = _occ_origin(occ)
        if after is None:
            continue
        measured = True
        was_pos, was_axes = before[label]
        delta = _move_delta(was_pos, after)
        rot = _axes_rotation_deg(was_axes, _occ_axes(occ))
        if delta or (rot is not None and rot > 0.1):
            row = dict(occurrence=label, **(delta or {"distance_mm": 0.0, "direction": None}))
            if rot is not None and rot > 0.1:
                row["rotation_deg"] = round(rot, 2)
            rows.append(row)
    return rows, measured
