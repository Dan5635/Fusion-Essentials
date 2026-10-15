# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""DESIGN MODE awareness: the mode read design_get's 'mode' slice returns, and the base-feature
scope runner every mutation that needs one goes through. Many adsk.* mutation methods are valid in
only ONE of Fusion's two design modes, or only inside an OPEN base-feature edit scope."""

from ._common import ok, error, safe
from . import _common
from . import _inputs
from ._common import timeline_health as _timeline_health

MAP_BLURB = (
    "MODE: get_mode_handler/health_handler - mode and health; "
    "run_in_base_feature/base_feature_run_wrapper - a mutation in an always-finished "
    "base-feature scope; "
    "timeline_census/timeline_item_key/census_caveat - an edit census; "
    "collapsed_group_hint(_for)/hidden_twin_hint - a grouped member's miss (by name or entity) "
    "or hidden twin; "
    "unfold_group_members - the group-state census; "
    "no_timeline_reason")

# A delete or suppress reply appends this when its before/after census could not be diffed.
CENSUS_UNREAD = ("The timeline could not be listed the same way before and after this call, so "
                 "what else it changed is not named - design_get(include=['timeline']) lists what "
                 "is there now.")
# An open Form or base-feature edit reads direct too and nothing else discriminates it, so the
# direct-mode remedy (delete bodies directly) is warned off: in a Form edit it deletes the Form.
OPEN_EDIT_CAVEAT = (" An open Form or base-feature edit also reads direct and nothing else "
                    "discriminates it: if a Form edit is open, ask the user to click Finish Form; "
                    "a base-feature scope closes with model_base_feature(action='finish').")


def no_timeline_reason(direct_text):
    """The no-timeline refusal text: direct_text plus the open-edit caveat."""
    return direct_text + OPEN_EDIT_CAVEAT


def health_handler() -> dict:
    """The active design's timeline health: feature error/warning rollup + a healthy flag."""
    design, design_refusal = _common.require_design()
    if design_refusal is not None:
        return design_refusal
    errors, warnings, total = _timeline_health(design)
    return ok({"timeline_features": total, "error_count": len(errors),
        "warning_count": len(warnings), "errors": errors, "warnings": warnings,
        "healthy": len(errors) == 0})


# ── the timeline census a delete or suppress diffs ──────────────────────────

def timeline_item_key(obj):
    """A timeline item's census key: its entity's entityToken, or None where none reads."""
    token = safe(lambda: obj.entity.entityToken)
    return token if isinstance(token, str) and token else None


def timeline_census(design):
    """{'items': [{key, name, index, suppressed, collapsed_group}], 'collapsed_groups': n} in
    timeline order, or None when the timeline cannot be counted."""
    timeline = safe(lambda: design.timeline)
    count = _common.counted(lambda: timeline.count) if timeline is not None else None
    if count is None:
        return None
    items = []
    for i in range(count):
        obj = safe(lambda i=i: timeline.item(i))
        # An EXPANDED group is absent from timeline.item() (its members are listed instead), so a
        # group row here hides its members; an unreadable isCollapsed counts as hiding them.
        group = (obj is not None and _common.read_flag(lambda: obj.isGroup) is True
                 and _common.read_flag(lambda: obj.isCollapsed) is not False)
        items.append({"key": timeline_item_key(obj) if obj is not None else None,
                      "name": safe(lambda: obj.name) if obj is not None else None,
                      "index": safe(lambda: obj.index) if obj is not None else None,
                      "suppressed": (_common.read_flag(lambda: obj.isSuppressed)
                                     if obj is not None else None),
                      "collapsed_group": group})
    return {"items": items, "collapsed_groups": sum(1 for it in items if it["collapsed_group"])}


def census_caveat(census):
    """The sentence a census reply carries when collapsed groups hide members from it, or None."""
    n = (census or {}).get("collapsed_groups") or 0
    if not n:
        return None
    return (f"{n} collapsed timeline group(s) hide their members from this check, so a member this "
            "call changed is not named - design_get(include=['timeline'], group='<name>') lists "
            "them.")


def _collapsed_groups(timeline):
    """Yield (name, members) for each collapsed timeline group."""
    for g in _common.iter_collection(safe(lambda: timeline.timelineGroups)):
        if safe(lambda g=g: g.isCollapsed) is True:
            yield safe(lambda g=g: g.name) or "(unnamed group)", list(_common.iter_collection(g))


def collapsed_group_holding(timeline, want):
    """The collapsed group holding a member matched by the shared timeline selector, or None."""
    for holder, members in _collapsed_groups(timeline):
        if _inputs._match_timeline_objects(members, want):
            return holder
    return None


def hidden_twin_hint(timeline, want, visible):
    """The refusal for an unindexed selector with visible hits and a collapsed member twin."""
    unfold_hint = _collapsed_unfold_hint(timeline, want)
    if unfold_hint:
        return f"'{want}' also matches {_inputs._candidates_listed(visible)}. " + unfold_hint
    holder = collapsed_group_holding(timeline, want)
    if not holder:
        return None
    return (f"'{want}' matches {_inputs._candidates_listed(visible)} and also names an item inside "
            f"the collapsed timeline group '{holder}' - name one exactly as listed, or run "
            f"design_edit_timeline(action='ungroup', feature='{holder}') and retry.")


def _inside_group(label, holder):
    """The sentence placing `label` (quoted by the caller) inside one collapsed group."""
    return (f"{label} is inside the collapsed timeline group '{holder}', which the timeline lists "
            "as one item.")


def _ungroup_remedy(holder):
    """The ungroup call that lists a collapsed group's members again."""
    return (f" Run design_edit_timeline(action='ungroup', feature='{holder}') - its items "
            "are kept - then retry.")


def collapsed_group_hint(timeline, want, roll=False):
    """The miss sentence for a collapsed group's member (target the group for a roll, else ungroup)."""
    if not roll:
        unfold_hint = _collapsed_unfold_hint(timeline, want)
        if unfold_hint:
            return unfold_hint
    holder = collapsed_group_holding(timeline, want)
    if not holder:
        return None
    if roll:
        return (_inside_group(f"'{want}'", holder)
                + f" Target '{holder}' itself - rolling to a collapsed group works.")
    return _inside_group(f"'{want}'", holder) + _ungroup_remedy(holder)


def collapsed_group_hint_for(timeline, entity, name):
    """The ungroup hint for the group holding `entity` by identity, else for each holding `name`."""
    want = _common.native_identity(entity)
    exact, unproven = [], []
    for holder, members in _collapsed_groups(timeline):
        keys = [_common.native_identity(safe(lambda m=m: m.entity)) for m in members]
        named = _inputs._match_timeline_objects(members, name) if name else []
        if want is not None and want in keys:
            exact.append(holder)
        elif any(want is None or key is None for m, key in zip(members, keys)
                 if any(m is hit for hit in named)):
            unproven.append(holder)
    label = f"'{name}'" if name else "The item"
    if len(exact) == 1:
        return _inside_group(label, exact[0]) + _ungroup_remedy(exact[0])
    holders = exact or unproven
    if len(holders) == 1:
        return (f"{label} names an item inside the collapsed timeline group '{holders[0]}', which "
                "the timeline lists as one item." + _ungroup_remedy(holders[0]))
    if not holders:
        return None
    listed = ", ".join(f"'{h}'" for h in holders)
    return (f"{label} names an item in each of the collapsed timeline groups {listed}, and which "
            "one holds it could not be told apart. design_get(include=['timeline'], "
            "group='<name>') lists a group's members; run design_edit_timeline(action='ungroup', "
            "feature='<name>') on the one holding it, then retry.")


def unfold_group_members(group):
    """Return a complete canonical owner/member census or its unread/unsupported-shape reason."""
    count = _common.counted(lambda: group.count)
    if count is None or count < 0:
        return None, "member count could not be read"
    if count not in (1, 2):
        return None, "group_state supports only one unfold and an optional refold"
    rows = []
    for i in range(count):
        item = safe(lambda i=i: group.item(i))
        entity = safe(lambda: item.entity)
        kind = safe(lambda: entity.objectType)
        name = safe(lambda: item.name)
        key = _common.native_identity(entity)
        owner = _common.native_identity(safe(lambda: entity.parentComponent))
        if key is None or owner is None or not isinstance(name, str) or not name or not isinstance(kind, str):
            return None, f"member {i} identity/type/name/owner could not be read"
        if kind.rsplit('::', 1)[-1] not in ('UnfoldFeature', 'RefoldFeature'):
            return None, "group_state supports only one unfold and an optional refold"
        rows.append((key, owner, name, kind))
    if (len({r[0] for r in rows}) != count or len({r[1] for r in rows}) != 1
            or sum(r[3].endswith('::UnfoldFeature') for r in rows) != 1):
        return None, "group_state needs one unfold, an optional refold and distinct members with one owner"
    return rows, None


def _collapsed_unfold_hint(timeline, want):
    """Return safe expansion and qualified retry advice for a matched hidden unfold-group member."""
    matches = []
    groups = safe(lambda: timeline.timelineGroups)
    count = _common.counted(lambda: groups.count)
    uncertain = ("Hidden feature/group identity could not be read completely. Read "
                 "design_get(include=['timeline']) to list groups; keep an unfold group intact.")
    if count is None or count < 0:
        return uncertain
    readable_groups = []
    for i in range(count):
        group = safe(lambda i=i: groups.item(i))
        group_name = safe(lambda: group.name)
        if isinstance(group_name, str) and group_name:
            readable_groups.append(group_name)
            reads = "; ".join(f"design_get(include=['timeline'], group={name!r})"
                              for name in readable_groups[:5])
            more = f"; {len(readable_groups) - 5} more groups not listed" if len(readable_groups) > 5 else ""
            uncertain = ("Hidden feature/group identity could not be read completely. Read "
                         + reads + more + "; keep an unfold group intact.")
        collapsed = _common.read_flag(lambda: group.isCollapsed)
        if group is None or collapsed is None:
            return uncertain
        if not collapsed:
            continue
        n = _common.counted(lambda: group.count)
        if n is None or n < 0:
            return uncertain
        members = [safe(lambda j=j: group.item(j)) for j in range(n)]
        if any(item is None or not isinstance(safe(lambda item=item: item.name), str)
               or not safe(lambda item=item: item.name) for item in members):
            return uncertain
        base, _index = _inputs._parse_address(want)
        scope, label = _inputs._split_qualified(base if base is not None else want)
        if scope is not None and any(safe(lambda item=item: item.name).lower() == label.lower()
                and not _inputs._owner_component_name(item) for item in members):
            return uncertain
        for item in _inputs._match_timeline_objects(members, want):
            entity = safe(lambda: item.entity)
            kind = safe(lambda: entity.objectType)
            if not isinstance(kind, str):
                return uncertain
            if kind != 'adsk::fusion::UnfoldFeature' and unfold_group_members(group)[0] is None:
                continue
            name = safe(lambda: item.name)
            owner = _inputs._owner_component_name(item)
            holder = safe(lambda: group.name)
            if name and owner and holder:
                members_read, reason = unfold_group_members(group)
                if members_read is None and 'could not be read' in reason:
                    return uncertain
                matches.append((holder, f"{owner}/{name}", members_read is not None))
            else:
                return uncertain
    if len(matches) > 1:
        steps = [(f"for '{target}' run design_edit_timeline(action='group_state', "
                  f"feature='{holder}', collapsed=false)") if supported else
                 (f"'{target}' sits in '{holder}', outside group_state support - inspect it with "
                  f"design_get(include=['timeline'], group='{holder}')")
                 for holder, target, supported in matches]
        more = f"; {len(steps) - 5} more not listed" if len(steps) > 5 else ""
        return (f"'{want}' names {len(steps)} hidden unfold-group features in collapsed groups: "
                + "; ".join(steps[:5]) + more + ". Then retry the original action with that "
                "qualified reference. Keep the unfold group intact.")
    if not matches:
        return None
    holder, target, supported = matches[0]
    if not supported:
        return (f"'{target}' is inside collapsed group '{holder}', whose member shape is outside "
                "group_state's one-unfold/optional-refold support. Inspect the group with "
                f"design_get(include=['timeline'], group='{holder}'), expand it in Fusion, then "
                f"retry the original action with '{target}'. Keep the unfold group intact.")
    return (f"'{target}' is inside collapsed group '{holder}'. Run design_edit_timeline("
            f"action='group_state', feature='{holder}', collapsed=false), then retry the original "
            f"action with qualified reference '{target}'. Keep the unfold group intact.")


# ── shared mode reads (all via the ONE true reader) ─────────────────────────

def _timeline_feature_count(design):
    """The parametric timeline's feature count, or None where there is no timeline (design.timeline
    raises in a direct design, which reads as None rather than as a broken timeline)."""
    tl = safe(lambda: design.timeline)
    if tl is None:
        return None
    return safe(lambda: tl.count, 0)


def _base_feature_count(design):
    """Count base features across the design (0 in a direct design, which has none)."""
    root = safe(lambda: design.rootComponent)
    if root is None:
        return 0
    total = 0
    counted_any = False
    for comp in _common.all_components(design):
        if comp is None:
            continue
        bf = safe(lambda c=comp: c.features.baseFeatures)
        if bf is None:
            continue
        counted_any = True
        total += safe(lambda b=bf: b.count, 0)
    return total if counted_any else 0


def _capability_map(mode):
    """The actionable `can{}` payload, derived purely from `mode` so it agrees with the ModeGuards."""
    parametric = mode == _inputs.MODE_PARAMETRIC
    direct = mode == _inputs.MODE_DIRECT
    return {
    "construction_point_by_coordinate": direct,   # setByPoint(Point3D) - direct-only
    "construction_axis_by_line": direct,          # setByLine(InfiniteLine3D) - direct-only
    "construction_plane_by_offset": parametric or direct,  # setByOffset - valid in both
    "timeline_ops": parametric,                   # a timeline exists only in parametric
    "base_feature_scope": parametric,             # base features are a parametric-only scope
    "convert_to_direct": parametric,              # parametric -> direct (destructive)
    "convert_to_parametric": direct,              # direct -> parametric
    }


# ── modelling-mode read (get_mode_handler - design_get's mode slice) ──────────────

def get_mode_handler() -> dict:
    """Report the active design's modelling mode and its capability map. Read-only."""
    design, design_refusal = _common.require_design()
    if design_refusal is not None:
        return design_refusal
    mode = _inputs.current_design_type(design)
    tl_count = _timeline_feature_count(design)
    can = _capability_map(mode)
    note = ("Capability map is keyed by mode requirement; call design_set_mode to convert, or "
            "model_base_feature to open a base-feature scope.")
    if mode == _inputs.MODE_DIRECT:
        note += OPEN_EDIT_CAVEAT
    return ok({
        "design_type": mode,
        "has_timeline": tl_count is not None,
        "timeline_feature_count": tl_count,
    "base_feature_count": _base_feature_count(design),
    "can": can,
    "note": note,
    })


# ── the base-feature scope runner every mutation that needs one goes through ─────

def base_feature_run_wrapper(open_scope, inner_op):
    """Run inner_op inside the scope open_scope() -> (base_feature, error or None) opens, ALWAYS
    finishing in a finally: (base_feature, inner_result), or (None, that error)."""
    bf, err = open_scope()
    if err is not None:
        return None, err
    name = safe(lambda: bf.name)
    try:
        started = bf.startEdit()
    except Exception as exc:
        started = f"raised: {str(exc)[:120]}"
    if started is False or isinstance(started, str):
        return bf, error(scope_left_clause(name, "startEdit", started))
    try:
        result = inner_op(bf)
    finally:
        # ALWAYS finish - a leaked open base-feature edit corrupts every later call this session -
        # and on the CAPTURED bf, since a lookup cannot find a scope while designType reads direct.
        try:
            done = bf.finishEdit()
        except Exception as exc:
            done = f"raised: {str(exc)[:120]}"
    if done is False or isinstance(done, str):
        text = scope_left_clause(name, "finishEdit", done)
        if isinstance(result, dict) and result.get("isError") is True:
            text = f"{result.get('message') or ''} {text}".strip()
        return bf, error(text)
    return bf, result


def scope_left_clause(name, call, outcome):
    """The error for a base-feature startEdit/finishEdit that returned false or raised."""
    what = "returned false" if outcome is False else outcome
    return (f"{call} on base feature '{name or '(name unreadable)'}' {what}; the edit scope was "
            "left as it is. Read design_get(include=['timeline']) before continuing.")


def run_in_base_feature(design, comp, inner_op):
    """The entry point for any mutation that may need a base-feature scope: inner_op runs inside one
    in a PARAMETRIC design (receiving the open BaseFeature) and directly in a DIRECT design
    (receiving None, the valid 'no scope' argument). Returns (inner_op's result, error or None)."""
    mode = _inputs.current_design_type(design)
    if mode != _inputs.MODE_PARAMETRIC:
        # Direct (or unknown): no base-feature scope - run the op directly. inner_op gets None.
        return inner_op(None), None

    if comp is None:
        return None, error("No component to open a base-feature scope in.")

    def open_scope():
        base_features = safe(lambda: comp.features.baseFeatures)
        if base_features is None:
            return None, error("This component has no baseFeatures collection - cannot open a "
    "base-feature scope for the parametric operation.")
        bf = base_features.add()
        if not bf:
            return None, error("BaseFeatures.add() returned nothing - could not open a "
    "base-feature scope.")
        return bf, None

    _bf, result = base_feature_run_wrapper(open_scope, inner_op)
    # base_feature_run_wrapper returns the inner result as `result`; an open/startEdit failure comes
    # back as a _common.error() dict in that slot. Normalise to (result, error).
    if isinstance(result, dict) and result.get("isError") is True:
        return None, result
    return result, None
