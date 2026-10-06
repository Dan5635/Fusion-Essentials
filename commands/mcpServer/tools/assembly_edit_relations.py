# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Lifecycle for the three assembly relations - rigid group, motion link, assembly constraint:
suppress/unsuppress, delete, reverse or re-value a motion link, and replace a rigid group's members
with the timeline marker rolled to before the group and put back.
"""

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import counted, error, ok, safe, timeline_health
from . import _assert
from . import _common
from . import _inputs
from . import _joints
from . import _relations

# Which actions each relation kind supports. Only a motion link carries a direction and a pair of
# coupled values; all three carry isSuppressed and deleteMe.
_KIND_ACTIONS = {
    "rigid_group": ("suppress", "unsuppress", "delete", "set_occurrences"),
    "motion_link": ("suppress", "unsuppress", "delete", "reverse", "set_values"),
    "constraint": ("suppress", "unsuppress", "delete"),
}
_ACTIONS = ("suppress", "unsuppress", "delete", "set_occurrences", "reverse", "set_values")

_KIND = _inputs.Choice("kind", list(_relations.KINDS), required=True)
_ACTION = _inputs.Choice("action", list(_ACTIONS), required=True)
_OCCURRENCES = _inputs.OccurrenceRefList("occurrences")


def _flag(obj, prop):
    """A boolean flag read off `obj`, or None when it is unknown - `_common.read_flag` is the ONE
    unreadable-flag read; this only names the property."""
    return _common.read_flag(lambda: getattr(obj, prop))

_UNREAD = object()      # an assemblyContext read that RAISED - None there means "placed in root"
_ROLL_END = "(action='roll', to='end')"

# What suppression/deletion OBSERVABLY did, per kind - the flag this call read back, plus the tool
# that re-creates the kind. What a suppressed relation does to the parts it relates is not measured.
_CREATE_TOOL = {"rigid_group": "assembly_rigid_group", "motion_link": "joint_motion_link",
                "constraint": "assembly_constrain"}


def _health_delta(before, design):
    """Timeline features newly in error since `before` - a suppress/delete can break a downstream
    feature that consumed what this relation held."""
    after, warnings, _total = timeline_health(design)
    return [n for n in after if n not in before], warnings


def _suppress_note(kind, state):
    """What the suppress call OBSERVED, per kind - the flag read back, and where to look for the
    effect. What suppression does to the members/coupling is not measured, so it is not claimed."""
    if kind == "motion_link":
        return (f"isSuppressed now reads {state} on the motion link, which couples two joints' "
                "motion. Drive one member (joint_drive) and read the partner back to see what "
                "changed.")
    if kind == "constraint":
        return (f"isSuppressed now reads {state} on the assembly constraint - the flag is what this "
                "call confirmed; what suppression does to its geometric relationships is not "
                "measured here.")
    return (f"isSuppressed now reads {state} on the rigid group; it stays in the timeline until "
            "action='delete'. Re-read positions with assembly_get to see the effect.")


def _do_suppress(design, obj, kind, name, suppressed):
    label = _relations.kind_label(kind)
    was = _flag(obj, "isSuppressed")
    errors_before, _w, _t = timeline_health(design)
    try:
        obj.isSuppressed = bool(suppressed)
    except Exception as e:
        return error(f"Could not set isSuppressed on {label} '{name}': {e}")
    now = _flag(obj, "isSuppressed")
    if now is None:
        return error(f"isSuppressed cannot be read on {label} '{name}' after setting it to "
                     f"{bool(suppressed)}, so the change is UNCONFIRMED. Re-read the relation with "
                     "assembly_get(include=['relations']).")
    if now != bool(suppressed):
        return error(f"Setting isSuppressed={bool(suppressed)} on {label} '{name}' did not take - "
                     f"it reads {now}.")
    new_errors, warnings = _health_delta(errors_before, design)
    out = {"kind": kind, "name": name, "is_suppressed": now,
           # null, not False, when the prior flag could not be read - an unreadable state is not "off".
           "was_suppressed": was,
           "note": _suppress_note(kind, now)}
    if new_errors:
        out["timeline_errors_after"] = new_errors
        out["note"] = (f"The change left {len(new_errors)} feature(s) in error: "
                       + ", ".join(new_errors) + ". Set the opposite action to restore it.")
    elif warnings:
        out["timeline_warnings"] = warnings
    return ok(out)


def _do_delete(design, obj, kind, name):
    label = _relations.kind_label(kind)
    errors_before, _w, _t = timeline_health(design)
    try:
        did = obj.deleteMe()
    except Exception as e:
        return error(f"Deleting {label} '{name}' failed: {e}")
    if not did:
        return error(f"Fusion declined to delete {label} '{name}' (deleteMe returned false) - it is "
                     "still in the design.")
    # Re-list the kind: a deleted relation must be GONE from the collection, not merely reported so.
    # relation_names drops an unreadable name, so `remaining` is the READABLE count of this kind.
    remaining = _relations.relation_names(design, kind)
    if any((n or "").lower() == name.lower() for n in remaining):
        return error(f"deleteMe reported success but {label} '{name}' is still listed - it was not "
                     "deleted.")
    new_errors, warnings = _health_delta(errors_before, design)
    out = {"deleted": True, "kind": kind, "name": name, "remaining": len(remaining),
           "note": (f"The {label} is no longer listed (re-read to confirm); 'remaining' counts the "
                    f"readable {label}s left. Undo in Fusion if unintended - the API cannot restore "
                    f"it. Re-create one with {_CREATE_TOOL[kind]}.")}
    if new_errors:
        out["timeline_errors_after"] = new_errors
        out["note"] += (f" WARNING: {len(new_errors)} feature(s) are now in error: "
                        + ", ".join(new_errors) + ".")
    elif warnings:
        out["timeline_warnings"] = warnings
    return ok(out)


def _path(occ):
    """An occurrence's fullPathName, else its name, for a message."""
    return safe(lambda: occ.fullPathName) or safe(lambda: occ.name) or "?"


def _token(occ):
    """An occurrence's own entityToken as read, or None."""
    return (safe(lambda: occ.entityToken) or None) if occ is not None else None


def _parent(occ, root):
    """The component `occ` reads as placed directly in, or None when its context did not read."""
    ctx = safe(lambda: occ.assemblyContext, _UNREAD)
    return root if ctx is None else None if ctx is _UNREAD else safe(lambda: ctx.component)


def _anchor(rg, owner, root):
    """(found, the ONE assembly context the group's direct members read in - None in the root)."""
    seen = {}
    for o in _common.iter_collection(safe(lambda: rg.occurrences)):
        if _common.same_component(_parent(o, root), owner) is True:
            ctx = safe(lambda o=o: o.assemblyContext)
            seen[None if ctx is None else _token(ctx) or _UNREAD] = ctx
    if len(seen) != 1 or _UNREAD in seen:
        return False, None
    return True, next(iter(seen.values()))


def _canon(occ, scope):
    """`occ` as the group's own context places it (itself in the root), or None when unread."""
    anchor, owner, root = scope
    if anchor is None or _common.same_component(_parent(occ, root), owner) is not True:
        return occ
    # A nested component's own occurrences raise on entityToken ("Tokens can only be created for
    # proxies whose top-level parent is the root component"); createForAssemblyContext(the members'
    # context) answers the root proxy carrying the token the group's own member reads.
    native = safe(lambda: occ.nativeObject)
    return None if native is None else safe(lambda: native.createForAssemblyContext(anchor))


def _members(rg, scope):
    """[(group-context token, path)] per distinct member read, or None when any did not read."""
    occs = safe(lambda: rg.occurrences)
    n = counted(lambda: occs.count) if occs is not None else None
    if n is None:
        return None
    out = []
    for i in range(n):
        o = safe(lambda i=i: occs.item(i))
        key = _token(_canon(o, scope)) if o is not None else None
        if key is None:
            return None
        if all(k != key for k, _p in out):
            out.append((key, _path(o)))
    return out


def _listed(members):
    """The member paths as one message fragment."""
    return ", ".join(p for _k, p in members) or "(none)"


def _same_members(a, b):
    """Whether two member lists hold the same occurrences, by count and group-context token."""
    return len(a) == len(b) and {k for k, _p in a} == {k for k, _p in b}


def _reread(before, after):
    """What a re-read of the members showed after a failed edit."""
    if after is None:
        return "Its members could not be re-read"
    if _same_members(before, after):
        return f"Its members re-read unchanged: {_listed(after)}"
    return f"Its members now read {_listed(after)} (were {_listed(before)})"


def _requested_members(design, rg, owner, name, occurrences):
    """([(group-context token, path)], the occurrences to hand over, scope, error)."""
    occs, oerr = _OCCURRENCES.resolve(occurrences)
    if oerr:
        return None, None, None, f"{oerr} Nothing was changed."
    root = safe(lambda: design.rootComponent)
    owner_name = safe(lambda: owner.name) or "?"
    found, anchor = _anchor(rg, owner, root)
    if not found:
        return None, None, None, (
            f"The members of rigid group '{name}' do not read in one placement of component "
            f"'{owner_name}', so a requested occurrence has no one context to be compared in. "
            "Nothing was changed.")
    scope = (anchor, owner, root)
    where = "" if anchor is None else f" in placement '{_path(anchor)}'"
    wanted, handed, asked = [], [], []
    for o in occs or []:
        path = _path(o)
        valid = safe(lambda o=o: o.isValid)
        if valid is not True:
            return None, None, None, (
                f"Occurrence '{path}' reads isValid={valid}. Re-read the tree with "
                "design_get(include=['tree']). Nothing was changed.")
        if _common.same_component(_parent(o, root), owner) is not True:
            return None, None, None, (
                f"Occurrence '{path}' does not read as placed directly in component "
                f"'{owner_name}', which owns rigid group '{name}'. Pass occurrences of that "
                "component, or action='delete' and re-create the group with "
                "assembly_rigid_group. Nothing was changed.")
        canon = _canon(o, scope)
        key = _token(canon)
        if key is None:
            return None, None, None, (
                f"Occurrence '{path}' has no readable identity{where}, so a read-back could not "
                "tell it from another. Nothing was changed.")
        twin = [a for (k, _p), a in zip(wanted, asked) if k == key]
        if twin:
            return None, None, None, (
                f"'occurrences' lists '{twin[0]}' and '{path}', which are one occurrence of "
                f"component '{owner_name}'. List each member once. Nothing was changed.")
        wanted.append((key, _path(canon)))
        handed.append(canon)
        asked.append(path)
    if len(wanted) < 2:
        return None, None, None, (
            f"A rigid group needs at least two occurrences; 'occurrences' names "
            f"{len(wanted)} ({_listed(wanted)}). Nothing was changed.")
    return wanted, handed, scope, None


def _do_set_occurrences(design, rg, owner, name, occurrences, include_children):
    wanted, handed, scope, werr = _requested_members(design, rg, owner, name, occurrences)
    if werr:
        return error(werr)
    timeline = safe(lambda: design.timeline)
    end = counted(lambda: timeline.count) if timeline is not None else None
    marker = counted(lambda: timeline.markerPosition) if timeline is not None else None
    if end is None or marker is None:
        return error("set_occurrences needs a parametric design: this design's timeline count and "
                     "marker do not read. Nothing was changed.")
    if marker != end:
        return error(f"The timeline marker is at {marker} of {end}; set_occurrences starts with "
                     f"it at the end. Call design_edit_timeline{_ROLL_END} and retry. Nothing was "
                     "changed.")
    index = counted(lambda: rg.timelineObject.index)
    if index is None:
        return error(f"Rigid group '{name}' has no readable timeline row, so the marker cannot be "
                     "rolled to before it. Nothing was changed.")
    was_suppressed = _flag(rg, "isSuppressed")
    if was_suppressed is not False:
        return error(f"Rigid group '{name}' reads isSuppressed={was_suppressed}; set_occurrences "
                     "edits an unsuppressed group (action='unsuppress' first). Nothing was changed.")
    before = _members(rg, scope)
    if before is None:
        return error(f"The members of rigid group '{name}' could not be read, so an edit could not "
                     "be confirmed against them. Nothing was changed.")
    include = bool(include_children)
    if not include and _same_members(before, wanted):
        return ok({"kind": "rigid_group", "name": name, "changed": False,
                   "members": [p for _k, p in before],
                   "note": "The group already holds exactly these members; nothing was changed."})
    errors_before, _w, _t = timeline_health(design)
    coll = adsk.core.ObjectCollection.create()
    for o in handed:
        coll.add(o)
    attempt = {}

    # Fusion 2706.0.116: setOccurrences raises "3 : Cannot be edited before rolling back" with the
    # marker at the end, and returns true with the marker just before the group's own row.
    def write():
        at = counted(lambda: timeline.markerPosition)
        if at != index:
            attempt["marker"] = at
            return
        try:
            attempt["returned"] = rg.setOccurrences(coll, include)
        except Exception as e:
            attempt["raised"] = str(e)

    _common.rolled_to(design, rg, write, f"rigid group '{name}'")
    if counted(lambda: timeline.markerPosition) != end:
        safe(lambda: setattr(timeline, "markerPosition", end))
    now = counted(lambda: timeline.markerPosition)
    after = _members(rg, scope)
    stuck = ("" if now == end else
             " Also, " + _common.marker_clause(end, now, "the edit") + _ROLL_END + ".")
    if attempt.get("returned") is not True:
        if "raised" in attempt:
            what = f"setOccurrences raised: {attempt['raised']}"
        elif "returned" in attempt:
            what = f"setOccurrences returned {attempt['returned']!r}"
        elif "marker" in attempt:
            what = (f"after rollTo the marker read {attempt['marker']}, not the group's row "
                    f"{index}, so setOccurrences was not called")
        else:
            what = ("the marker did not roll to before the group (rollTo did not return true), so "
                    "setOccurrences was not called")
        return error(f"Editing rigid group '{name}' failed: {what}. {_reread(before, after)}."
                     + stuck)
    if now != end:
        return error(f"setOccurrences returned true on rigid group '{name}', but "
                     + _common.marker_clause(end, now, "the edit") + _ROLL_END
                     + f". {_reread(before, after)} at that marker; re-read them with "
                     "assembly_get(include=['relations']) once it is back.")
    if after is None:
        return error(f"setOccurrences returned true on rigid group '{name}' but its members could "
                     "not be read back, so the edit is UNCONFIRMED. Re-read it with "
                     "assembly_get(include=['relations']).")
    want_keys, got_keys = {k for k, _p in wanted}, {k for k, _p in after}
    if not (want_keys <= got_keys if include else _same_members(after, wanted)):
        return error(f"setOccurrences returned true but rigid group '{name}' reads members "
                     f"{_listed(after)}, not the requested {_listed(wanted)}.")
    suppressed = _flag(rg, "isSuppressed")
    state, _failure = _assert.compute_state(rg)
    if suppressed is not False or state != "healthy":
        return error(f"Rigid group '{name}' now holds {_listed(after)} with the marker back at "
                     f"{end}, but it reads isSuppressed="
                     f"{'unread' if suppressed is None else suppressed} and health "
                     f"{'unread' if state == 'unknown' else state}. Inspect it with "
                     "assembly_get(include=['relations']).")
    new_errors, warnings = _health_delta(errors_before, design)
    out = {"kind": "rigid_group", "name": name, "changed": True,
           "component": safe(lambda: owner.name) or None,
           "members": [p for _k, p in after], "member_count": len(after),
           "members_before": [p for _k, p in before],
           "include_children": include, "is_suppressed": suppressed, "health": state,
           "marker_position": now, "timeline_count": end,
           "note": "Members re-read as requested with the timeline marker back at the end. "
                   "Re-read positions with assembly_get."}
    if new_errors:
        out["timeline_errors_after"] = new_errors
        out["note"] = (f"Members re-read as requested, but {len(new_errors)} feature(s) are now "
                       "in error: " + ", ".join(new_errors) + ". Set the previous members to "
                       "restore them.")
    elif warnings:
        out["timeline_warnings"] = warnings
    return ok(out)


def _do_reverse(ml, name):
    was = _flag(ml, "isReversed")
    if was is None:
        return error(f"Motion link '{name}' does not report isReversed, so there is no direction to "
                     "flip.")
    want = not was
    try:
        ml.isReversed = want
    except Exception as e:
        return error(f"Could not set isReversed on motion link '{name}': {e}")
    now = _flag(ml, "isReversed")
    if now is None:
        return error(f"isReversed cannot be read on motion link '{name}' after setting it to "
                     f"{want}, so the flip is UNCONFIRMED. Re-read the link with "
                     "assembly_get(include=['relations']).")
    if now != want:
        return error(f"Setting isReversed={want} on motion link '{name}' did not take - it reads "
                     f"{now}.")
    return ok({"kind": "motion_link", "name": name, "reversed": now,
               "was_reversed": was,
               "note": "The linked joints now move in the opposite sense relative to each other. "
                       "Drive ONE member (joint_drive) and read the partner back."})


def _do_set_values(ml, name, ratio):
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return error(f"'ratio' must be a number (got {ratio!r}).")
    if r == 0:
        return error("'ratio' must be non-zero (a 0 ratio links no motion).")
    # setMotionData re-states WHICH degrees of freedom are coupled, so the link's existing
    # motionOne/motionTwo are read back and passed through - picking a DOF here would silently
    # re-couple a different pair.
    m1 = safe(lambda: ml.motionOne)
    m2 = safe(lambda: ml.motionTwo)
    if m1 is None or m2 is None:
        return error(f"Motion link '{name}' does not report both coupled motions (motionOne/"
                     "motionTwo), so its values cannot be re-set without guessing which degrees of "
                     "freedom it links.")
    # setMotionData carries isReversed, so the SIGN of ratio SETS the direction outright: a positive
    # ratio clears an existing reversal. was_reversed reports what that overwrote.
    was_rev = _flag(ml, "isReversed")
    reversed_link = r < 0
    # 'ratio' is stated in each DOF's DISPLAY unit; the shared codec (the same one joint_motion_link
    # creates through) turns it into the native pair the API takes, so a re-value and a create of one
    # coupling send the same two numbers.
    value_one, value_two, ratio_facts = _joints.link_ratio_values(m1, m2, r)
    v1 = adsk.core.ValueInput.createByReal(value_one)
    v2 = adsk.core.ValueInput.createByReal(value_two)
    try:
        did = ml.setMotionData(m1, v1, m2, v2, reversed_link)
    except Exception as e:
        return error(f"setMotionData on motion link '{name}' failed: {e}. (The platform refuses a "
                     "coupling it cannot solve; the link is unchanged.)")
    if not did:
        return error(f"Fusion declined to re-value motion link '{name}' (setMotionData returned "
                     "false) - its ratio is unchanged.")
    one = safe(lambda: ml.valueOne.value)
    two = safe(lambda: ml.valueTwo.value)
    now_rev = _flag(ml, "isReversed")
    if one is None or two is None:
        return error(f"setMotionData reported success on '{name}' but its valueOne/valueTwo "
                     "parameters cannot be read back, so nothing confirms the new ratio.")
    # value_one is 1, so the coupled pair's own ratio IS value_two - the NATIVE number this ratio
    # converts to, which is what the read-back has to express. The comparison is the codec's own
    # gate (_joints.link_ratio_mismatch), so the create path judges its read-back the same way.
    mismatch = _joints.link_ratio_mismatch(value_two, one, two)
    if mismatch:
        return error(f"setMotionData reported success on '{name}' but {mismatch}.")
    if now_rev is None:
        return error(f"setMotionData reported success on '{name}' and its parameters read "
                     f"{one}:{two}, but isReversed cannot be read back, so the direction the SIGN "
                     "of ratio sets is UNCONFIRMED. Re-read the link with "
                     "assembly_get(include=['relations']).")
    if now_rev != reversed_link:
        return error(f"setMotionData reported success on '{name}' but it reads isReversed="
                     f"{now_rev}, not {reversed_link} - the direction did not take.")
    out = {"kind": "motion_link", "name": name, "ratio": r, "value_one": one, "value_two": two,
           "reversed": now_rev,
           "was_reversed": was_rev,
           "note": "Coupling re-valued - 'interpreted' states how the ratio was read, and "
                   "value_one/value_two are the link's own parameters READ BACK after the set. The "
                   "SIGN of ratio SETS the direction, so a positive ratio CLEARS an existing "
                   "reversal (was_reversed reports what it overwrote); action='reverse' flips the "
                   "direction without re-valuing. Drive ONE member (joint_drive) and read the "
                   "partner back."}
    # The codec's three keys, published identically by the create path (joint_motion_link), so one
    # ratio reads the same whichever writer applied it.
    out.update(ratio_facts)
    return ok(out)


def handler(kind: str = "", name: str = "", action: str = "", occurrences=None,
            include_children: bool = False, ratio=None) -> dict:
    """See TOOL_DESCRIPTION."""
    values, verr = _inputs.resolve_inputs([_KIND, _ACTION], {"kind": kind, "action": action})
    if verr:
        return verr
    kind, action = values["kind"], values["action"]

    allowed = _KIND_ACTIONS[kind]
    if action not in allowed:
        return error(f"action='{action}' does not apply to a {_relations.kind_label(kind)} - it "
                     f"supports: {', '.join(allowed)}.")
    design = _common.design()
    if not design:
        return error("No active design with components.")

    obj, comp, rerr = _relations.find_relation(design, kind, name)
    if rerr:
        return error(rerr)
    nm = safe(lambda: obj.name) or (name or "").strip()

    if action in ("suppress", "unsuppress"):
        return _do_suppress(design, obj, kind, nm, action == "suppress")
    if action == "delete":
        return _do_delete(design, obj, kind, nm)
    if action == "set_occurrences":
        return _do_set_occurrences(design, obj, comp, nm, occurrences, include_children)
    if action == "reverse":
        return _do_reverse(obj, nm)
    return _do_set_values(obj, nm, ratio)


TOOL_DESCRIPTION = (
    "Edit or remove an existing assembly relation; create one with assembly_rigid_group / "
    "joint_motion_link / assembly_constrain."
)

tool = (
    Tool.create_simple(name="assembly_edit_relations", description=TOOL_DESCRIPTION)
    .add_input_property(*_KIND.as_property())
    .add_input_property("name", {"type": "string"})
    .add_input_property(*_ACTION.as_property())
    .add_input_property(*_OCCURRENCES.as_property())
    .add_input_property("include_children", {"type": "boolean"})
    .add_input_property("ratio", {"type": "number",
            "description": "set_values: joint_two per ONE unit of joint_one, in each joint's DISPLAY unit (deg or mm); the SIGN sets direction."})
    .strict_schema()
)
item = Item.create_tool_item(
    tool=tool, write="destructive", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline", rung="value",
        evidence_test="tests/unit/test_assembly_edit_relations.py::TestDelete"
                      "::test_a_survivor_after_a_true_delete_is_an_error"))


def register_tool():
    register(item)
