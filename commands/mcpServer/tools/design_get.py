# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""RICH READ: design_get - the active design's structure by zoom level (see CLAUDE.md "Reads are
RICH"). Default: a cheap orientation slice (design type, feature count, timeline health, content
fingerprint). include=['tree'|'timeline'|'mode'|'configurations'|'materials'|'appearances'|
'attributes'|'definition'|'datums'] pulls one deeper slice at a time via _slice_*() helpers. Read-only.
"""

import json
from itertools import islice

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import ok, error, safe, terse
from . import _common
from . import _edit_feature_common
from . import _cam_common
from . import _inputs
from . import _joints
from . import _materials
from .design_configure import _CELL_FIELDS, _row_census
from .model_inspect import _MAX_PER_BODY_ROWS

app = adsk.core.Application.get()

# The deeper slices an agent can opt into (the default returns NONE of these in full - only summaries).
_SLICES = ("mode", "tree", "timeline", "configurations", "materials", "appearances", "attributes",
           "metadata", "definition", "datums")
_FEATURE = _inputs.FeatureRef("feature", description="Hole/Thread/Loft/Extrude/Sweep.")
_DEFINITION_UNREAD = object()

# The orientation slice's name in include=: any deep include omits that slice unless 'default' rides
# beside it, so a deep read carries what was asked for and not the default again.
_DEFAULT_NAMES = ("default",)


# ── slice helpers - each builds one slice's payload ────────────────────────────────────────────────
# mode/health delegate to get_mode_handler/health_handler; tree/timeline/configurations read
# directly. _unwrap decodes a handler's ok() result.

def _unwrap(result):
    """Decode a handler's result -> (payload_dict, None) on ok, or (None, error_result) on error
    so the caller can surface a slice's own guard (e.g. timeline raises in direct mode)."""
    if result.get("isError"):
        return None, result
    try:
        return json.loads(result["content"][0]["text"]), None
    except Exception:
        return None, result


def _slice_mode(design):
    """The modelling-mode + capability map (via _design_common.get_mode_handler)."""
    from . import _design_common
    return _unwrap(_design_common.get_mode_handler())


def _slice_health(design):
    """The timeline health rollup (_design_common.health_handler) - cheap; in the default slice."""
    from . import _design_common
    return _unwrap(_design_common.health_handler())


# ── component/occurrence tree ──────────────────────────────────────────────────────────────────────
_TREE_DEFAULT_DEPTH = 3
_TREE_MAX_DEPTH = 8
_TREE_MAX_NODES = 2000
_TREE_BODY_CAP = 25          # per-node body records when tree_bodies=true
_TREE_CHILDREN_DEFAULT = 30  # children listed per LEVEL; the rest ride on child_count

# The narrowings a capped level is answered with, plus the flag that restores the withheld address.
_TREE_NOTE = ("Light nodes: name, component, body_count, child_count. Narrow: name_filter, "
              "component=<name>, max_depth, max_results. tree_handles=true adds handle/full_path/"
              "source ids. children_truncated = a level cut; child_count = the true count.")


def _body_cut_note(cut):
    """The FIRST sentence when a node's bodies were cut: shown vs true count, and the remedy that
    reaches the rest - model_inspect's per_body list, itself capped at _MAX_PER_BODY_ROWS."""
    head = (f"'{cut['node']}' bodies: {cut['shown']} of {cut['true']} shown (cap {_TREE_BODY_CAP}). "
            f"model_inspect(target='{cut['node']}', include=['mass'], per_body=true) ")
    if isinstance(cut["true"], int) and cut["true"] <= _MAX_PER_BODY_ROWS:
        return head + "has all."
    return (head + f"lists at most {_MAX_PER_BODY_ROWS} (per_body_truncated past that); one "
            "component has no narrower scope, so read the rest with model_inspect(target='<body>').")


def _body_rows(bodies):
    """Per-body records for one tree node, capped at _TREE_BODY_CAP: name + entityToken handle (the
    exact identity BodyRef/TargetRef consumers accept - the counterpart of the node's occurrence
    handle) + solid/visible flags via read_flag (None = unreadable, never a coerced False). Returns
    (rows, truncated)."""
    items = list(islice(_common.iter_collection(bodies), _TREE_BODY_CAP + 1))
    truncated = len(items) > _TREE_BODY_CAP
    rows = [{
        "name": safe(lambda b=b: b.name),
        "handle": safe(lambda b=b: b.entityToken),
        "is_solid": _common.read_flag(lambda b=b: b.isSolid),
        "visible": _common.read_flag(lambda b=b: b.isVisible),
    } for b in items[:_TREE_BODY_CAP]]
    return rows, truncated


def _find_occurrence_by_name(root, want):
    """Resolve the occurrence to root the tree at: a COMPONENT name (root at its first instance - every
    instance of a component shows the same structure) or an occurrence name/fullPathName (via the
    shared ambiguity-refusing _inputs._resolve_occurrence). Returns (occurrence, error): an ambiguous
    occurrence name is refused with its candidates, not silently matched to the first. Bounded DFS."""
    want_lower = (want or "").strip().lower()
    # 1) A COMPONENT name (exact): all instances share one structure, so the first instance roots it.
    try:
        stack = list(root.occurrences)
    except Exception:
        stack = []
    seen = 0
    while stack and seen < _TREE_MAX_NODES:
        occ = stack.pop()
        seen += 1
        if (safe(lambda: occ.component.name, "") or "").lower() == want_lower:
            return occ, None
        try:
            stack.extend(list(occ.childOccurrences))
        except Exception:
            pass
    # 2) An OCCURRENCE name / fullPathName - the shared resolver refuses an ambiguous name instead of
    # returning whichever same-named instance came first.
    occ, occ_err = _inputs._resolve_occurrence("component", want)
    if occ is not None:
        return occ, None
    if occ_err and "ambiguous" in occ_err.lower():
        return None, occ_err
    return None, None


def _unresolved_node(occ, detail):
    """The tree row for an occurrence whose referenced component will not load: every other read on
    it RAISES, so the row carries the name - the one identity that still reads - and the detail."""
    name = safe(lambda: occ.name)
    return {"name": name if name else "(unreadable name)",
            "unresolved": True,
            "detail": detail}


def _unresolved_children(occ):
    """The unresolved children of `occ`, classified by the shared detector over the COMPONENT-LOCAL
    collection. childOccurrences - what this tree descends - silently DROPS an occurrence whose
    reference is broken (its assembly path is invalid), while component.occurrences holds it."""
    comp = safe(lambda: occ.component)
    rows = []
    for child in _common.iter_collection(safe(lambda: comp.occurrences) if comp else None):
        is_broken, detail = _common.broken_reference(child)
        if is_broken:
            rows.append(_unresolved_node(child, detail))
    return rows


def _walk_occurrence(occ, depth, max_depth, counter, with_bodies=False, with_handles=False,
                     child_cap=_TREE_CHILDREN_DEFAULT):
    counter["n"] += 1
    if counter["n"] >= _TREE_MAX_NODES:
        counter["truncated"] = True
    is_broken, broken_detail = _common.broken_reference(occ)
    if is_broken:
        return _unresolved_node(occ, broken_detail)
    node = {
        "name": safe(lambda: occ.name),
        "component": safe(lambda: occ.component.name),
        # counted, not safe(..., 0): a coerced 0 would say "no bodies / no children" about a
        # collection nothing was read from. null takes the same (do not descend) branch below
        # without claiming it.
        "body_count": _common.counted(lambda: occ.bRepBodies.count),
        "child_count": _common.counted(lambda: occ.childOccurrences.count),
    }
    if with_handles:
        # The entityToken is the EXACT instance identity: Fusion enforces no name uniqueness, so a
        # name repeats under every sub-assembly ("Bolt:1") and two siblings can even wear one
        # fullPathName. The path is the convenience form, which refuses when it collides.
        node["handle"] = safe(lambda: occ.entityToken)
        node["full_path"] = safe(lambda: occ.fullPathName)
    # read_flag, not safe(..., False): an unreadable flag is None here (the same honesty _body_rows
    # holds for is_solid/visible), and the freshness gate below treats None as "try it". A flag that
    # read FALSE is the boring case and stays off the row.
    is_reference = _common.read_flag(lambda: occ.isReferencedComponent)
    if is_reference is not False:
        node["is_reference"] = is_reference
    if with_bodies and node["body_count"]:
        rows, truncated = _body_rows(safe(lambda: occ.bRepBodies, None))
        if rows:
            node["bodies"] = rows
            if truncated:
                node["bodies_truncated"] = True
                if counter.get("body_cut") is None:
                    counter["body_cut"] = {"node": node.get("component") or node.get("name"),
                                           "shown": len(rows), "true": node["body_count"]}
    # None (the flag did not read) takes the SAME branch as True: a local occurrence simply has no
    # documentReference, so attempting the read costs one safe() read and publishes real freshness
    # for an xref whose own flag is unreadable - where the False branch would silently drop it.
    if is_reference is not False:
        try:
            dr = occ.documentReference
            if dr:
                node["source_version"] = safe(lambda: dr.version)
                node["is_out_of_date"] = safe(lambda: dr.isOutOfDate)
                df = safe(lambda: dr.dataFile)
                if df:
                    # source_name names the source FILE, which two sources can share; source_id is
                    # its unique address, and rides with the other addresses under tree_handles.
                    node["source_name"] = safe(lambda: df.name)
                    if with_handles:
                        node["source_id"] = safe(lambda: df.id)
                        node["source_url"] = safe(lambda: df.fusionWebURL)
        except Exception:
            pass
    # The unresolved children are found on the COMPONENT-LOCAL collection and counted here, so
    # child_count (read off childOccurrences, which drops them) is never the whole story on its own.
    unresolved_kids = _unresolved_children(occ)
    if unresolved_kids:
        node["children_unresolved"] = len(unresolved_kids)
    if depth + 1 < max_depth and (node["child_count"] or unresolved_kids) and counter["n"] < _TREE_MAX_NODES:
        kids, more = [], False
        try:
            for child in occ.childOccurrences:
                if len(kids) >= child_cap or counter["n"] >= _TREE_MAX_NODES:
                    counter["truncated"] = counter["truncated"] or counter["n"] >= _TREE_MAX_NODES
                    more = True
                    break
                kids.append(_walk_occurrence(child, depth + 1, max_depth, counter, with_bodies,
                                             with_handles, child_cap))
        except Exception:
            pass
        # The unresolved rows obey the SAME level cap - appended past it, a capped level hands back
        # more children than the caller paged for. children_unresolved keeps their true count.
        room = max(0, child_cap - len(kids))
        kids.extend(unresolved_kids[:room])
        if len(unresolved_kids) > room:
            more = True
        if kids:
            node["children"] = kids
        if more:
            node["children_truncated"] = True
    elif node["child_count"] or unresolved_kids:
        node["children_truncated"] = True
    return node


def _matches_filter(occ, wanted):
    """True when `wanted` (already lower-cased and non-empty) is contained in the entity's own name
    or in the name of the component it places."""
    for value in (safe(lambda: occ.name), safe(lambda: occ.component.name)):
        if isinstance(value, str) and wanted in value.lower():
            return True
    return False


def _slice_tree(design, max_depth, component, with_bodies=False, with_handles=False,
                max_children=0, name_filter=""):
    """The component/occurrence tree: light nodes, bounded by max_depth, the per-level max_children
    cap and the node cap. with_bodies adds per-body records; with_handles the entityToken/full_path
    addresses; name_filter keeps only the top-level nodes whose own or component name contains it."""
    try:
        depth = max(1, min(int(max_depth), _TREE_MAX_DEPTH))
    except Exception:
        depth = _TREE_DEFAULT_DEPTH
    try:
        cap = max(1, int(max_children)) if max_children else _TREE_CHILDREN_DEFAULT
    except Exception:
        cap = _TREE_CHILDREN_DEFAULT
    root = safe(lambda: design.rootComponent)
    if root is None:
        return None, error("No root component.")
    counter = {"n": 0, "truncated": False, "body_cut": None}
    if (component or "").strip():
        start, amb = _find_occurrence_by_name(root, component)
        if amb:
            return None, error(amb)
        if not start:
            return None, error(f"Component/occurrence not found: '{component}'.")
        # Walk FIRST, read the truncated flag AFTER: a dict literal evaluates its values in
        # order, so reading counter["truncated"] before the walk would pin the pre-walk False.
        scoped_tree = _walk_occurrence(start, 0, depth, counter, with_bodies, with_handles, cap)
        cut = counter["body_cut"]
        note = (_body_cut_note(cut) + " " + _TREE_NOTE) if cut else _TREE_NOTE
        return {"root": component, "max_depth": depth, "truncated": counter["truncated"],
                "tree": scoped_tree, "note": note}, None
    wanted = (name_filter or "").strip().lower()
    children, total, matched = [], 0, 0
    try:
        for occ in root.occurrences:
            total += 1
            if wanted and not _matches_filter(occ, wanted):
                continue
            matched += 1
            if len(children) >= cap or counter["n"] >= _TREE_MAX_NODES:
                counter["truncated"] = counter["truncated"] or counter["n"] >= _TREE_MAX_NODES
                continue
            children.append(_walk_occurrence(occ, 0, depth, counter, with_bodies, with_handles, cap))
    except Exception as e:
        return None, error(f"Could not read root occurrences: {e}")
    out = {"root": safe(lambda: root.name), "max_depth": depth, "node_count": counter["n"],
           "child_count": total, "children_truncated": matched > len(children),
           "truncated": counter["truncated"], "children": children}
    if wanted:
        out["name_filter"] = name_filter.strip()
        out["matched"] = matched
    # Bodies that live directly in the ROOT component (not in any occurrence). The occurrence walk above
    # never sees these, so without this an agent reading the tree can't tell they exist - and a root body
    # is NOT a jointable occurrence (promote it to a component to joint it).
    if with_bodies:
        root_rows, root_tr = _body_rows(safe(lambda: root.bRepBodies, None))
        if root_rows:
            out["root_bodies"] = root_rows
            if root_tr:
                out["root_bodies_truncated"] = True
                if counter["body_cut"] is None:
                    counter["body_cut"] = {"node": safe(lambda: root.name), "shown": len(root_rows),
                                           "true": _common.counted(lambda: root.bRepBodies.count)}
    else:
        root_bodies, root_names_tr = _root_body_names(root)
        if root_bodies:
            out["root_bodies"] = root_bodies
            if root_names_tr:
                out["root_bodies_truncated"] = True
    if out.get("root_bodies"):
        out["root_bodies_note"] = ("Bodies directly in the root component (not occurrences). A root body "
                                   "can't be jointed - model_create_component then move it in to joint it.")
    cut = counter["body_cut"]
    out["note"] = (_body_cut_note(cut) + " " + _TREE_NOTE) if cut else _TREE_NOTE
    return out, None


def _root_body_names(root):
    """(names, truncated) for the bodies directly in the root component, capped at _TREE_BODY_CAP -
    the same cap and the same disclosure the tree_bodies records get."""
    names, truncated = [], False
    try:
        items = list(islice(_common.iter_collection(root.bRepBodies), _TREE_BODY_CAP + 1))
        truncated = len(items) > _TREE_BODY_CAP
        for i, b in enumerate(items[:_TREE_BODY_CAP]):
            names.append(safe(lambda b=b: b.name) or f"Body{i+1}")
    except Exception:
        pass
    return names, truncated


# ── parametric timeline ────────────────────────────────────────────────────────────────────────────
_TIMELINE_MAX_ITEMS = 250
_HEALTH_LABELS = {0: "healthy", 1: "warning", 2: "error", 3: "suppressed", 4: "rolled_back", 5: "unknown"}

# Keep timeline rows readable (via _common.terse): a healthy row collapses to {index, name, type}; an
# abnormal row keeps (and pops with) its is_suppressed=true / health="error" / rolled_back. Keys -> the
# value that means "all normal". 'component' joins per call, keyed to the ROOT's name.
_TIMELINE_NOISE = {"is_group": False, "is_suppressed": False, "is_rolled_back": False,
                   "parent_group": None, "health": "healthy"}

_TIMELINE_CAP_NOTE = ("Rows past the cap are not listed. Raise max_results, or narrow with "
                      "group='<name>' or include_suppressed=false.")


def _owner_fields(obj):
    """A timeline row's owning component. A feature name is scoped to the component that owns it, so
    the name alone does not say which row it addresses."""
    # MEASURED: a timeline entity answers assemblyContext None - the timeline holds natives - so
    # there is no occurrence path to publish beside the owning component.
    name = _inputs._owner_component_name(obj)
    return {"component": name} if isinstance(name, str) and name else {}


def _entity_type(obj):
    """The timeline object's entity class name (ExtrudeFeature/Sketch/Joint/...); 'TimelineGroup' for a group."""
    if safe(lambda: obj.isGroup):
        return "TimelineGroup"
    ent = safe(lambda: obj.entity)
    return type(ent).__name__ if ent is not None else None


def _object_summary(obj):
    health = safe(lambda: obj.healthState)
    out = {
        "index": safe(lambda: obj.index),
        "name": safe(lambda: obj.name),
        "type": _entity_type(obj),
        # read_flag: an unreadable row flag publishes null, which does not equal the False in
        # _TIMELINE_NOISE, so terse KEEPS the row - and the include_suppressed filter keys on True
        # only, so a row whose is_suppressed did not read is listed rather than hidden.
        "is_group": _common.read_flag(lambda: obj.isGroup),
        "is_suppressed": _common.read_flag(lambda: obj.isSuppressed),
        "is_rolled_back": _common.read_flag(lambda: obj.isRolledBack),
        "parent_group": safe(lambda: obj.parentGroup.name if obj.parentGroup else None),
        "health": _HEALTH_LABELS.get(health, health),
        **_owner_fields(obj),
    }
    msg = _common.timeline_message(safe(lambda: obj.errorOrWarningMessage), out["name"])
    if msg:
        out["message"] = msg
    return out


# ── the model parameters a timeline feature owns (include=['timeline'], timeline_params=true) ──────
# A timeline row carries type+name only, so a fillet's radius comes from the feature's own
# ModelParameters: each carries .createdBy (the owner) and .role (its slot on that owner).
_PARAMS_PER_ROW = 16


def _token_key(entity):
    """("token", entityToken) when the owner's token reads, else None."""
    tok = safe(lambda: entity.entityToken)
    return ("token", tok) if isinstance(tok, str) and tok else None


def _timeline_key(tl_index):
    """("tl", index) for a readable timeline index, else None."""
    return ("tl", tl_index) if isinstance(tl_index, int) and not isinstance(tl_index, bool) else None


def _model_parameters_by_owner(design):
    """{owner identity -> rows} from ONE pass over design.allParameters, keyed by the owner's
    entityToken, else its timeline index. A feature name is per-component, so it is never a key; a
    UserParameter has no .createdBy and an owner with neither identity is skipped."""
    index = {}
    for p in _common.iter_collection(safe(lambda: design.allParameters)):
        owner = safe(lambda p=p: p.createdBy)
        if owner is None:
            continue
        key = _token_key(owner) or _timeline_key(safe(lambda: owner.timelineObject.index))
        if key is None:
            continue
        index.setdefault(key, []).append({"name": safe(lambda p=p: p.name),
                                          "role": safe(lambda p=p: p.role),
                                          "expression": safe(lambda p=p: p.expression),
                                          "value": _common.measured(lambda p=p: p.value)})
    return index


def _params_for(index, entity, tl_index):
    """(rows, truncated) - the model parameters this row's feature owns, looked up by its token, then
    its timeline index, capped; (None, False) when it owns none."""
    for key in (_token_key(entity), _timeline_key(tl_index)):
        rows = index.get(key) if key is not None else None
        if rows:
            return rows[:_PARAMS_PER_ROW], len(rows) > _PARAMS_PER_ROW
    return None, False


_PARAMS_NOTE = ("Each params[].value is in Fusion internal units (cm / radians) - params[].expression "
                "carries the authored unit. Full records: param_get(include_model_parameters=true).")


def _timeline_row(summ, obj, param_index, include_suppressed, noise=_TIMELINE_NOISE):
    """ONE published timeline row as (row, carried_params) - the suppressed filter and the params
    attachment, in one place so the walk and a group expansion cannot publish different shapes. A
    row the filter drops is (None, False)."""
    if not include_suppressed and summ["is_suppressed"] is True:
        return None, False
    row = terse(summ, noise)
    if param_index is None:
        return row, False
    entity = safe(lambda: obj.entity)
    prows, ptrunc = (_params_for(param_index, entity, summ.get("index")) if entity is not None
                     else (None, False))
    if not prows:
        return row, False
    row["params"] = prows
    if ptrunc:
        row["params_truncated"] = True
    return row, True


def _enrich_group(summ, obj):
    """The keys a GROUP row carries past a feature row: how many members it stands for, and whether
    the walk lists them. Every publisher of a group row goes through here, so the walk and a group=
    expansion cannot hand back two shapes for one container."""
    summ["member_count"] = _common.counted(lambda: obj.count)
    summ["is_collapsed"] = _common.read_flag(lambda: obj.isCollapsed)
    return summ


def _extend_with_members(items, group_obj, seen, truncated, param_index, include_suppressed,
                         noise=_TIMELINE_NOISE, cap=_TIMELINE_MAX_ITEMS):
    """Append a group's OWN members to `items` through _timeline_row, returning (truncated,
    carried_params) - a COLLAPSED group is ONE row in the timeline walk, so its members are
    reachable only by walking the group."""
    any_params = False
    for member in _common.iter_collection(group_obj):
        if len(items) >= cap:
            return True, any_params
        summ = _object_summary(member)
        if summ.get("is_group") is True:
            _enrich_group(summ, member)
        idx = summ.get("index")
        # One timeline index is published once: `seen` carries what the walk has already listed.
        if idx is not None and idx in seen:
            continue
        row, got_params = _timeline_row(summ, member, param_index, include_suppressed, noise)
        if row is None:
            continue
        seen.add(idx)
        any_params = any_params or got_params
        items.append(row)
    return truncated, any_params


def _tally(states, exceptions, tallied, summ):
    """Fold ONE feature's health into the states tally, and a failed one into exceptions - once per
    timeline index. A row whose index read null is tallied where it is found."""
    idx = summ.get("index")
    if idx is not None:
        if idx in tallied:
            return
        tallied.add(idx)
    health = summ.get("health", "healthy")
    states[health] = states.get(health, 0) + 1
    # exception = a feature that FAILED (error/warning health) - not just suppressed (intentional).
    if health in ("error", "warning"):
        exceptions.append({"name": summ.get("name"), "index": idx, "health": health})


def _tally_group(states, exceptions, tallied, group_obj, summ):
    """Fold ONE group's members into the tally - the only route to a collapsed group's suppressed or
    errored feature. The container itself is never scored; its index is marked, so a nested group
    already folded in from its parent is not folded again when the walk reaches its own row."""
    idx = summ.get("index")
    if idx is not None:
        if idx in tallied:
            return
        tallied.add(idx)
    for member in _common.iter_collection(group_obj):
        member_summ = _object_summary(member)
        if member_summ.get("is_group") is True:
            _tally_group(states, exceptions, tallied, member, member_summ)
        else:
            _tally(states, exceptions, tallied, member_summ)


# The pointer a reader needs when a group row stands for members this walk never listed.
_GROUP_NOTE = ("A group is ONE row here, carrying member_count and is_collapsed; a COLLAPSED "
               "group's members are not listed, though summary.states counts them (an exception "
               "from one carries index null - address it by name). "
               "design_get(include=['timeline'], group='<name>') lists them.")

# MEASURED (measure_api row timeline-group-collapse-shape): index RAISES on a member reached
# through a COLLAPSED group while name/isGroup/isSuppressed/healthState/parentGroup all read, so
# the row publishes index null and the name is the only address left on it.
_GROUP_MEMBER_NOTE = "index is null on these rows - address them by name."

# A group row inside a group= listing stands for members this listing did not descend into either.
_NESTED_GROUP_NOTE = "This listing holds group row(s); group='{0}' lists what one stands for."


def _slice_timeline(design, include_suppressed, group, with_params=False, max_rows=0):
    """The ordered parametric timeline, with healthy-row noise dropped (a normal row is
    {index,name,type}; a suppressed/errored row keeps its flags and stands out). with_params adds
    each row's own model parameters; max_rows pages it (0 = the default cap)."""
    try:
        timeline = design.timeline
    except Exception as e:
        from . import _design_common
        return None, error(_design_common.no_timeline_reason(
            f"This design has no timeline (direct-modeling, or no history): {e}"))
    try:
        cap = max(1, int(max_rows)) if max_rows else _TIMELINE_MAX_ITEMS
    except Exception:
        cap = _TIMELINE_MAX_ITEMS
    want_group = (group or "").strip()
    items, truncated = [], False
    states, exceptions, tallied = {}, [], set()   # exception-first rollup over the timeline
    param_index = _model_parameters_by_owner(design) if with_params else None
    any_params, seen = False, set()
    # A feature name is per-COMPONENT, so every row names its owner - except in the single-component
    # design where that owner is the root on every row and says nothing.
    noise = dict(_TIMELINE_NOISE, component=safe(lambda: design.rootComponent.name))
    try:
        total = timeline.count      # a timeline that cannot be counted is a refusal, not an empty read
        for obj in _common.iter_collection(timeline):
            if len(items) >= cap:
                truncated = True
                break
            summ = _object_summary(obj)
            is_group = summ["is_group"] is True
            # A group is a CONTAINER, not a feature: its own healthState reads 'unknown', which
            # tallied reads as a design nothing could be read from. Its MEMBERS are tallied
            # instead - a collapsed group's suppressed feature reaches the walk no other way.
            if is_group:
                _enrich_group(summ, obj)
                _tally_group(states, exceptions, tallied, obj, summ)
            else:
                _tally(states, exceptions, tallied, summ)
            if not include_suppressed and summ["is_suppressed"] is True:
                continue
            if want_group:
                if is_group and summ["name"] == want_group:
                    truncated, got_params = _extend_with_members(
                        items, obj, seen, truncated, param_index, include_suppressed, noise, cap)
                    any_params = any_params or got_params
                    continue
                if (summ["parent_group"] or "") != want_group:
                    continue
            idx = summ.get("index")
            if idx is not None and idx in seen:
                continue                     # already listed by the group expansion above
            row, got_params = _timeline_row(summ, obj, param_index, include_suppressed, noise)
            if row is None:
                continue
            seen.add(idx)
            any_params = any_params or got_params
            items.append(row)
    except Exception as e:
        return None, error(f"Could not read the timeline: {e}")
    groups = {}
    try:
        for tg in timeline.timelineGroups:
            gname = safe(lambda tg=tg: tg.name)
            if gname is not None:
                groups[gname] = safe(lambda tg=tg: tg.count, 0)
    except Exception:
        pass
    payload = {"marker_position": safe(lambda: timeline.markerPosition),
               "count": total, "returned": len(items),
               "summary": {"states": states, "exceptions": exceptions},
               "groups": groups, "timeline": items}
    if truncated:
        payload["truncated"] = True
        payload["truncated_note"] = _TIMELINE_CAP_NOTE
    if any_params:
        payload["params_note"] = _PARAMS_NOTE
    nested = [r.get("name") for r in items if r.get("is_group") is True and r.get("name")]
    group_notes = []
    if nested:
        # A group row means members this listing does not hold, whichever door published it.
        group_notes.append(_GROUP_NOTE if not want_group
                           else _NESTED_GROUP_NOTE.format(nested[0]))
    if want_group and any(r.get("index") is None for r in items):
        group_notes.append(_GROUP_MEMBER_NOTE)
    if group_notes:
        payload["groups_note"] = " ".join(group_notes)
    return payload, None


# ── configurations (read side) ──────────────────────────────────────────────────────────────────────
_CONFIG_MAX_ROWS = 1000


def _row_summary(row, active_id):
    rid = safe(lambda: row.id)
    return {"name": safe(lambda: row.name), "id": rid, "index": safe(lambda: row.index),
            "is_active": (rid is not None and rid == active_id)}


def _column_summary(col):
    # ConfigurationColumn exposes .title (readable label), NOT .name (.name raises).
    return {"title": safe(lambda: col.title), "id": safe(lambda: col.id),
            "index": safe(lambda: col.index), "type": safe(lambda: type(col).__name__)}


_CELL_DEFAULT, _CELL_CEILING = 200, 1000
_PARAMETER_CELL, _PROPERTY_CELL = "ConfigurationParameterCell", "ConfigurationPropertyCell"
_CELL_CAP_NOTE = (f"Cells past the cap are not listed. Raise max_results (max {_CELL_CEILING}); "
                  "cell_count is the whole table.")


def _cell_record(row, column_index):
    """One table cell: its kind and the fields that read, or why it is absent or unread."""
    if column_index is None:
        return {"kind": None, "value_unread": "the column's index did not read"}
    try:
        cell = row.getCellByColumnIndex(column_index)
    except Exception as exc:
        return {"kind": None, "raised": str(exc)}
    if cell is None:
        return {"absent": True}
    kind = safe(lambda: cell.objectType.rsplit("::", 1)[-1])
    if kind is None:
        return {"kind": None, "value_unread": "the cell's objectType did not read"}
    if kind == _PROPERTY_CELL:
        return {"kind": kind, "value_unread": "no value field of this cell kind is read here"}
    if kind == _PARAMETER_CELL:
        try:
            expression = cell.expression
        except Exception as exc:
            return {"kind": kind, "expression": None, "raised": str(exc)}
        record = {"kind": kind, "expression": expression}
        if expression is None:
            record["value_unread"] = "the cell's expression read nothing"
        return record
    record = {"kind": kind}
    for key, read in _CELL_FIELDS:
        value = safe(lambda read=read: read(cell))
        if value is not None:
            record[key] = value
    if len(record) == 1:
        record["value_unread"] = "none of the fields read here answered on this cell kind"
    return record


def _cell_table(table, max_results):
    """The slice's cell keys: one record per row x column, addressed by row id and column id."""
    records, rows, problem = _row_census(table)
    columns = safe(lambda: table.columns)
    column_count = _common.counted(lambda: columns.count)
    if problem or column_count is None:
        return {"cells": None, "cells_unread": problem or "the table's columns did not count"}
    cap = _cam_common.clamp_rows(max_results, _CELL_DEFAULT, _CELL_CEILING)
    total = len(rows) * column_count
    heads = []
    for i in range(min(column_count, cap)):
        column = safe(lambda i=i: columns.item(i))
        # A cell is fetched by the index its column reads, never by the column's list position.
        heads.append((safe(lambda: column.id), _common.counted(lambda: column.index)))
    cells = []
    for record, row in zip(records, rows):
        for column_id, column_index in heads:
            if len(cells) < cap:
                cells.append({"row_id": record["id"], "column_id": column_id,
                              **_cell_record(row, column_index)})
    out = {"cell_count": total, "cells": cells}
    if total > cap:
        out["cells_truncated"], out["cells_truncated_note"] = True, _CELL_CAP_NOTE
    return out


def _slice_configurations(design, max_results=0):
    """The configuration table, READ side. Returns (payload, error); a non-configured design errors
    (the router degrades that to a {configured: False} marker rather than failing the read)."""
    table = safe(lambda: design.configurationTopTable)
    if not table:
        return None, error("The active design is not a Configured Design (it has no configuration "
                           "table) - e.g. a design with Variant A/Variant B style options.")
    active_row = safe(lambda: table.activeRow)
    active_id = safe(lambda: active_row.id) if active_row else None
    rows, truncated = [], False
    try:
        for r in table.rows:
            if len(rows) >= _CONFIG_MAX_ROWS:
                truncated = True
                break
            rows.append(_row_summary(r, active_id))
    except Exception:
        pass
    columns = []
    try:
        for c in table.columns:
            columns.append(_column_summary(c))
    except Exception:
        pass
    out = {"table_name": safe(lambda: table.name), "table_id": safe(lambda: table.id),
           "active_configuration": safe(lambda: active_row.name) if active_row else None,
           "configuration_count": len(rows), "configurations": rows, "columns": columns}
    if truncated:
        out["truncated"] = True
    out.update(_cell_table(table, max_results))
    return out, None


# ── entity attributes (the tags design_edit_timeline's set_attribute writes) ───────────────────────
_ATTR_MAX_ROWS = 500


def _attribute_rows(design, group, key):
    """(rows, error_text) - every attribute in the design under `group` (and `key` when given),
    as {group, key, value, entity}. Design.findAttributes hands back an AttributeVector - len()/[i],
    never .count/.item(i) - so this walks it by index rather than through iter_collection. An
    Attribute exposes .name (the key), .value, and .parent (the entity it is attached to)."""
    found = safe(lambda: design.findAttributes(group, key))
    if found is None:
        return None, (f"Searching attributes for group '{group}' failed - Design.findAttributes "
                      "raised or returned nothing.")
    total = _common.counted(lambda: len(found))
    if total is None:
        return None, f"The attribute search for group '{group}' returned a result that has no length."
    rows = []
    for i in range(min(total, _ATTR_MAX_ROWS)):
        attr = safe(lambda i=i: found[i])
        if attr is None:
            continue
        parent = safe(lambda: attr.parent)
        entity = {"type": type(parent).__name__ if parent is not None else None}
        parent_name = safe(lambda: parent.name) if parent is not None else None
        if parent_name is not None:
            entity["name"] = parent_name
        # 'group' is the QUERIED group, not a read off the attribute: every row in the vector
        # matched it, so echoing the query says the same thing without a second property read.
        rows.append({"group": group, "key": safe(lambda: attr.name),
                     "value": safe(lambda: attr.value), "entity": entity})
    return {"total": total, "rows": rows}, None


def _slice_attributes(design, group, key):
    """The design's entity attributes under ONE group. The group is REQUIRED - without it this would
    dump every attribute in the design (Fusion itself stores internal ones), which is the flood a
    scoped read exists to avoid."""
    g = (group or "").strip()
    if not g:
        return None, error("include=['attributes'] needs 'attribute_group' - the group to read (the "
                           "same group design_edit_timeline(action='set_attribute') wrote with). "
                           "Leave 'attribute_key' empty to get every key in that group.")
    k = (key or "").strip()
    result, err = _attribute_rows(design, g, k)
    if err:
        return None, error(err)
    out = {"group": g, "key": k or None, "count": result["total"],
           "returned": len(result["rows"]), "attributes": result["rows"]}
    if result["total"] > len(result["rows"]):
        out["truncated"] = True
    return out, None


# ── component engineering metadata (part number, description, identity) ───────────────────────────
_METADATA_MAX_ROWS = 100
_METADATA_ROWS_CEILING = 500

_METADATA_NOTE = ("part_number and description are writable with design_set_metadata; id and "
                  "revision_id are reads only - no tool here writes them.")

_METADATA_KEYS = ("name", "part_number", "description", "id", "revision_id")


def _metadata_row(comp):
    """One component's engineering identity - each key omitted when its read declined."""
    reads = (lambda: comp.name, lambda: comp.partNumber, lambda: comp.description,
             lambda: comp.id, lambda: comp.revisionId)
    row = {}
    for key, read in zip(_METADATA_KEYS, reads):
        value = safe(read)
        if value is not None:
            row[key] = value
    return row


def _scoped_components(root, scope):
    """(components, walk, error) - the component `scope` names first, then each distinct component
    placed under it, with the occurrence walk that found them."""
    start, amb = _find_occurrence_by_name(root, scope)
    if amb:
        return None, None, error(amb)
    top = safe(lambda: start.component) if start is not None else None
    if top is None:
        return None, None, error(f"Component/occurrence not found: '{scope}'.")
    walk = _common.component_walk(top)
    out, seen = [top], {_common.native_identity(top) or id(top)}
    for occ in walk.occurrences:
        comp = safe(lambda occ=occ: occ.component)
        key = (_common.native_identity(comp) or id(comp)) if comp is not None else None
        if key is not None and key not in seen:
            seen.add(key)
            out.append(comp)
    return out, walk, None


def _slice_metadata(design, name_filter, max_results, component=""):
    """Per-component engineering identity, the ROOT first: part number, description, id, revision.
    component= scopes it to one component's subtree; name_filter keeps the components whose name
    carries it; the list is capped."""
    root = safe(lambda: design.rootComponent)
    if root is None:
        return None, error("No root component.")
    cap = _cam_common.clamp_rows(max_results, _METADATA_MAX_ROWS, _METADATA_ROWS_CEILING)
    wanted = (name_filter or "").strip().lower()
    scope = (component or "").strip()
    walk = None
    if scope:
        pool, walk, serr = _scoped_components(root, scope)
        if serr:
            return None, serr
    else:
        # same_component, never `is`: allComponents holds the root too, and a component wrapper is
        # never identity-stable, so an unproven match leaves the row in rather than dropping it.
        pool = [root] + [c for c in _common.iter_collection(safe(lambda: design.allComponents))
                         if _common.same_component(c, root) is not True]
    rows, matched = [], 0
    for comp in pool:
        if wanted and not _matches_filter(comp, wanted):
            continue
        matched += 1
        if len(rows) < cap:
            rows.append(_metadata_row(comp))
    out = {"component_count": matched, "returned": len(rows), "components": rows,
           "note": _METADATA_NOTE}
    if matched > len(rows):
        out["truncated"] = True
        out["note"] += (f" {matched - len(rows)} more component(s) not listed - narrow with "
                        "component='<name>' or name_filter, or raise max_results.")
    if wanted:
        out["name_filter"] = name_filter.strip()
    if scope:
        out["component"] = scope
    if walk is not None and (not walk.complete or walk.broken):
        out["incomplete"] = True
        names = ", ".join(walk.names()[:5])
        out["note"] += (f" The walk under '{scope}' did not enumerate every occurrence"
                        + (f" (unresolved: {names})" if names else "")
                        + ", so this list may not hold every component beneath it.")
    return out, None


_DATUM_COLLECTIONS = (("construction_axis", "constructionAxes"),
                      ("construction_plane", "constructionPlanes"),
                      ("construction_point", "constructionPoints"))
_DATUM_PLACEMENT_CAP = 4


def _slice_datums(design, component, name_filter, max_results):
    """Bounded definition inventory for construction axes, planes and points."""
    root = safe(lambda: design.rootComponent)
    if root is None:
        return None, error("No root component.")
    scope = (component or "").strip()
    all_count = _common.counted(lambda: design.allComponents.count)
    known_components = _common.all_components(design)
    definitions_complete = (all_count is not None and len(known_components) == all_count)
    if scope and (safe(lambda: root.name) or "").strip().lower() == scope.lower():
        pool, serr = known_components, None
    elif scope:
        pool, scope_walk, serr = _scoped_components(root, scope)
        if serr:
            return None, serr
        definitions_complete = (scope_walk.complete and not scope_walk.broken
                                and scope_walk.readable)
    else:
        pool, serr = known_components, None
    if serr:
        return None, serr
    cap = _cam_common.clamp_rows(max_results, 25, 200)
    wanted = (name_filter or "").strip().lower()
    walk = _common.occurrence_walk(design)
    placements_complete = walk.readable and walk.complete and not walk.broken
    definitions_complete = definitions_complete and placements_complete
    counts = {kind: 0 for kind, _attr in _DATUM_COLLECTIONS}
    rows = []
    for comp in pool:
        owner = safe(lambda comp=comp: comp.name)
        owner_matches = [(_common.same_component(safe(lambda occ=occ: occ.component), comp),
                          safe(lambda occ=occ: occ.fullPathName)) for occ in walk.occurrences]
        paths = [path for match, path in owner_matches if match is True and path is not None]
        owner_placements_complete = (placements_complete
                                     and all(match is not None for match, _path in owner_matches)
                                     and all(path is not None for match, path in owner_matches
                                             if match is True))
        for kind, attr in _DATUM_COLLECTIONS:
            coll = safe(lambda comp=comp, attr=attr: getattr(comp, attr))
            n = _common.counted(lambda coll=coll: coll.count) if coll is not None else None
            if n is None:
                counts[kind] = None
                continue
            for i in range(n):
                datum = safe(lambda coll=coll, i=i: coll.item(i))
                if datum is None:
                    counts[kind] = None
                    continue
                name = safe(lambda datum=datum: datum.name)
                if name is None and wanted:
                    counts[kind] = None
                    continue
                if wanted and (not isinstance(name, str) or wanted not in name.lower()):
                    continue
                if counts[kind] is not None:
                    counts[kind] += 1
                if len(rows) >= cap:
                    continue
                row = {"kind": kind, "name": name, "component": owner,
                       "light_bulb_on": _common.read_flag(lambda datum=datum: datum.isLightBulbOn),
                       "is_deletable": _common.read_flag(lambda datum=datum: datum.isDeletable),
                       "is_parametric": _common.read_flag(lambda datum=datum: datum.isParametric),
                       "timeline_index": _common.counted(lambda datum=datum: datum.timelineObject.index),
                       "placement_count": (len(paths) if owner_placements_complete else None),
                       "occurrences": paths[:_DATUM_PLACEMENT_CAP]}
                if len(paths) > _DATUM_PLACEMENT_CAP:
                    row["occurrences_truncated"] = True
                rows.append(row)
    if not definitions_complete:
        counts = {kind: None for kind in counts}
    match_count = (sum(counts.values()) if all(v is not None for v in counts.values()) else None)
    out = {"counts": counts, "match_count": match_count, "returned": len(rows),
           "truncated": (match_count > len(rows) if match_count is not None else None),
           "datums": rows,
           "occurrences_walk": walk.method,
           "note": ("Definition inventory only. Use find_geometry(kind=construction_axis/"
                    "construction_plane/construction_point, target=<occurrence>, name=<exact name>) "
                    "for world geometry and a placed handle. Narrow with component/name_filter or "
                    "raise max_results; null counts mean incomplete reads.")}
    if scope:
        out["component"] = scope
    if wanted:
        out["name_filter"] = name_filter.strip()
    if not definitions_complete or any(v is None for v in counts.values()):
        out["incomplete"] = True
    return out, None


# ── material / appearance catalog (both slices, one walk in _materials) ────────────────────────────

def _slice_materials(design, library, name_filter, max_results):
    """The PHYSICAL-material catalog: the document's own materials plus a census of every loaded
    library, or one named library's materials. The names model_set_material resolves."""
    return _materials.browse(design, "materials", library, name_filter, max_results)


def _slice_appearances(design, library, name_filter, max_results):
    """The APPEARANCE (cosmetic) catalog, same two levels as the materials slice. A document
    appearance name is what design_configure(action='set_appearance') resolves."""
    return _materials.browse(design, "appearances", library, name_filter, max_results)


def _fingerprint(design):
    """The cheap 'what IS this model' digest for the default: DESIGN-WIDE counts of bodies /
    sketches / components / occurrences / joints / parameters, so an agent learns the model's SHAPE
    without include=tree."""
    root = safe(lambda: design.rootComponent)
    if root is None:
        return None
    body_total, sketch_total = _common.design_wide_counts(design)
    walk = _common.occurrence_walk(design)
    fp = {
        "bodies": body_total,
        "sketches": sketch_total,
        # components = distinct component DEFINITIONS beyond the root (0 = single-component
        # design); occurrences = placed instances. The two differ in any multi-instance assembly,
        # and labeling the instance count "components" misstates the design's shape.
        "components": max(0, safe(lambda: design.allComponents.count, 0) - 1),
        # null, never 0, when neither walk enumerated: root.allOccurrences RAISES on a design holding
        # an unresolved external reference, and safe(read, 0) published that failure as "no
        # occurrences" on a multi-part assembly.
        "occurrences": walk.total,
        # Every component's joints AND asBuiltJoints - the walk assembly_get's joint_count reads, so
        # the two reads agree whichever component is active.
        "joints": len(_joints.all_joints(design)),
        # userParameters = the ones an agent can drive; modelParameters includes internal ones it can't.
        "parameters": _common.counted(lambda: design.userParameters.count),
    }
    out = {k: v for k, v in fp.items() if v}   # omit zero counts (single-component, no joints, ...)
    if fp["parameters"] is None:
        out["parameters"] = None                # the read raised (an open Form edit does): unknown
    # The truthy filter drops 'occurrences' both for a design holding no instance (0) and for one
    # whose census could not be taken (None), so the walk that answered is published beside them:
    # 'unreadable' means neither walk enumerated, and the count is UNKNOWN rather than zero.
    out["occurrences_walk"] = walk.method
    return out


# The action tools for each content class the fingerprint can report. Only classes that are PRESENT
# and not already-obvious get a pointer - bodies/sketches are omitted.
_CONTENT_TOOLS = {
    "parameters": "param_get (list/read), param_set / param_add (change or create)",
    "joints": "assembly_get (wiring + health), joint_drive (pose by value)",
    "components": "design_get(include=['tree']) for the full tree; assembly_get for positions",
}


def _content_pointers(contents):
    """Map the present content classes to the tools that act on them (present + non-obvious only), so a
    read that says 'parameters: 40' also says HOW to read/change them - the missing inbound breadcrumb."""
    if not contents:
        return {}
    return {k: _CONTENT_TOOLS[k] for k in _CONTENT_TOOLS if contents.get(k)}


def _has_cam(design):
    """True when the active document also has a CAM (Manufacture) product. A CAM document's whole point
    is its machining state, which design_get is blind to - so a cam pointer to cam_get is its inbound
    breadcrumb."""
    return _cam_common.get_cam()[0] is not None


# ── the router ─────────────────────────────────────────────────────────────────────────────────────

def _definition_identity(feature):
    """The definition's feature identity and owning component as read, without timeline movement."""
    return {"feature": safe(lambda: feature.name),
            "component": safe(lambda: (safe(lambda: feature.parentComponent)
                                       or _inputs.entity_component(feature)).name),
            "type": safe(lambda: feature.objectType.rsplit("::", 1)[-1]),
            "timeline_index": _common.counted(lambda: feature.timelineObject.index)}


def _definition_thread_info(info):
    """The actual thread standard, designation, class and internal flag, independently nullable."""
    return {"thread_type": safe(lambda: info.threadType),
            "designation": safe(lambda: info.threadDesignation),
            "thread_class": safe(lambda: info.threadClass),
            "internal": _common.read_flag(lambda: info.isInternal)}


def _definition_thread(feature, factor):
    """One thread's native definition, with full-length numeric extents marked inapplicable."""
    full = _common.read_flag(lambda: feature.isFullLength)
    applicable = None if full is None else not full
    return {**_definition_identity(feature),
            "thread_info": _definition_thread_info(safe(lambda: feature.threadInfo)),
            "modeled": _common.read_flag(lambda: feature.isModeled),
            "right_handed": _common.read_flag(lambda: feature.isRightHanded),
            "full_length": full, "length_applicable": applicable, "offset_applicable": applicable,
            "length": (_common.measured(lambda: feature.threadLength.value, factor)
                       if full is not True else None),
            "offset": (_common.measured(lambda: feature.threadOffset.value, factor)
                       if full is not True else None)}


def _definition_loft(feature):
    """A bounded ordered read of a Loft's current sections and controls."""
    def alignment(side):
        actual = safe(lambda: getattr(feature, side + "LoftEdgeAlignment"))
        family = safe(lambda: adsk.fusion.LoftEdgeAlignments)
        for key, name in _inputs.LOFT_EDGE_ALIGNMENT_MEMBERS.items():
            member = safe(lambda n=name: getattr(family, n))
            if member is not None and actual == member:
                return key
        return None

    collection = safe(lambda: feature.loftSections)
    count = _common.counted(lambda: collection.count)
    cap = 64
    rows = []
    for index in range(min(count or 0, cap)):
        section = safe(lambda i=index: collection.item(i))
        entity = safe(lambda s=section: s.entity)
        sketch = safe(lambda e=entity: e.parentSketch)
        rows.append({"index": index,
                     "kind": safe(lambda e=entity: e.objectType.rsplit("::", 1)[-1]),
                     "profile_handle": safe(lambda e=entity: e.entityToken),
                     "source_sketch": safe(lambda s=sketch: s.name),
                     "source_component": safe(lambda s=sketch: s.parentComponent.name),
                     "end_condition": safe(lambda s=section: s.endCondition.objectType)})
    return {**_definition_identity(feature), "section_count": count, "sections": rows,
            "truncated": count is None or count > cap,
            "operation": safe(lambda: feature.operation),
            "is_solid": _common.read_flag(lambda: feature.isSolid),
            "is_closed": _common.read_flag(lambda: feature.isClosed),
            "start_alignment": alignment("start"),
            "end_alignment": alignment("end"),
            "guide_count": _common.counted(lambda: feature.centerLineOrRails.count)}


def _slice_definition(feature, units):
    """Read one typed feature definition without moving the timeline."""
    values, refusal = _inputs.resolve_inputs([_FEATURE, _inputs.UNITS],
                                            {"feature": feature, "units": units})
    if refusal:
        return None, refusal
    if values["feature"] is None:
        return None, error("include=['definition'] requires 'feature'; use include=['timeline'] to find it.")
    entity, label = values["feature"]
    kind = safe(lambda: entity.objectType)
    if kind not in _edit_feature_common.FEATURE_EDIT_SUPPORT and kind not in (
                    "adsk::fusion::HoleFeature", "adsk::fusion::ThreadFeature",
                    "adsk::fusion::LoftFeature", "adsk::fusion::ExtrudeFeature",
                    "adsk::fusion::SweepFeature"):
        return None, error(f"'{label}' has unsupported definition type {kind!r}; use "
                           "include=['timeline'] or model_inspect.")
    factor = 1 / _common.scale(values["units"])
    if kind in _edit_feature_common.FEATURE_EDIT_SUPPORT:
        out = {**_definition_identity(entity), **_edit_feature_common.feature_definition(entity, factor)}
        if kind == "adsk::fusion::ThreadFeature":
            thread = _definition_thread(entity, factor)
            out.update({key: value for key, value in thread.items()
                        if key not in ("feature", "component", "type", "timeline_index")})
    elif kind in ("adsk::fusion::ExtrudeFeature", "adsk::fusion::SweepFeature"):
        out = {**_definition_identity(entity), **_edit_feature_common.feature_definition(entity, factor)}
    elif kind == "adsk::fusion::LoftFeature":
        out = _definition_loft(entity)
    elif kind == "adsk::fusion::ThreadFeature":
        out = _definition_thread(entity, factor)
    else:
        extent = safe(lambda: entity.extentDefinition)
        extent_type = safe(lambda: extent.objectType)
        extent_kind = {"adsk::fusion::AllExtentDefinition": "through",
                       "adsk::fusion::DistanceExtentDefinition": "blind"}.get(
                           extent_type, "unsupported" if extent_type is not None else None)
        tap = safe(lambda: entity.tappedHoleInfo, _DEFINITION_UNREAD)
        child = safe(lambda: entity.thread, _DEFINITION_UNREAD)
        out = {**_definition_identity(entity), "extent": extent_kind, "extent_type": extent_type,
               "depth_applicable": (extent_kind == "blind"
                                    if extent_kind in ("blind", "through") else None),
               "depth": (_common.measured(lambda: extent.distance.value, factor)
                         if extent_kind == "blind" else None),
               "diameter_parameter": (_common.measured(lambda: entity.holeDiameter.value, factor)
                                      if tap is None else None),
               "diameter_parameter_applicable": None if tap is _DEFINITION_UNREAD else tap is None,
               "tapped": None if tap is _DEFINITION_UNREAD else tap is not None,
               "tapped_hole_info": (_definition_thread_info(tap)
                                    if tap is not _DEFINITION_UNREAD and tap is not None else None),
               "thread_present": None if child is _DEFINITION_UNREAD else child is not None,
               "thread": (_definition_thread(child, factor)
                          if child is not _DEFINITION_UNREAD and child is not None else None)}
    out["units"] = (units or "mm").strip().lower()
    out["note"] = ("Read at the current marker without rolling. supported_edits gives qualified calls and usable operand handles; reacquire at edit time."
                   if kind in _edit_feature_common.FEATURE_EDIT_SUPPORT else
                   "Read at the current marker without rolling. Null is unknown unless applicable=false; "
                   "unavailable gives getter failures. Through-all extent_side_count is its native "
                   "one/two-side flag; extrude direction is unknown here. Sweep orientation_name gives the readable "
                   "enum. Use profile_handle as a profile input. Distances are signed; "
                   "symmetric_full_length=false means distance is per side."
                   if kind in ("adsk::fusion::ExtrudeFeature", "adsk::fusion::SweepFeature") else
                   "Loft sections are in order; null fields are unreadable. Use profile_handle "
                   "with model_edit_loft; model_inspect include=['mass'] reads mass, volume and "
                   "density, not the assigned material's name."
                   if kind == "adsk::fusion::LoftFeature" else
                   "tapped=false or thread_present=false means absent; applicable=false means "
                   "inapplicable. Other null fields are unknown. Measure tapped bore geometry "
                   "with find_geometry/model_inspect; full-length threads imply no numeric length.")
    if out.get("not_read"):
        out["note"] += " This Extrude definition is partial: not_read lists fields it omits."
    return out, None

def handler(include=None, max_depth: int = 3, component: str = "", tree_bodies: bool = False,
            tree_handles: bool = False,
            include_suppressed: bool = True, group: str = "", timeline_params: bool = False,
            library: str = "", name_filter: str = "", max_results: int = 0,
            attribute_group: str = "", attribute_key: str = "", feature: str = "",
            units: str = "mm") -> dict:
    """See TOOL_DESCRIPTION."""
    design = _common.design()
    if not design:
        return error("No active design. Open or create a document first (see doc_new).")

    inc = _normalize_include(include)
    bad = [s for s in inc if s not in _SLICES and s not in _DEFAULT_NAMES]
    if bad:
        return error(f"Unknown include {bad}. Valid: {', '.join(_SLICES + _DEFAULT_NAMES)}.")
    if feature not in (None, "") and "definition" not in inc:
        return error("'feature' scopes include=['definition']; include that slice to read its definition.")

    deep = [s for s in inc if s in _SLICES]
    want_default = not deep or any(s in _DEFAULT_NAMES for s in inc)
    # the mode read serves both the orientation headline and include=['mode'], so it runs when
    # either needs it - and not at all on a deep read that asks for neither.
    mode_full = None
    if want_default or "mode" in inc:
        mode_full, merr = _slice_mode(design)
        if merr:
            return merr

    # ── default ORIENTATION slice - BOUNDED + DENSE; omitted when include= asks past it ──
    out = {}
    if want_default:
        health, _herr = _slice_health(design)      # cheap rollup; degrades to None on a direct design
        has_timeline = safe(lambda: mode_full.get("has_timeline"))
        out = {
            # the headline: what kind of design, how big the build, what's in it. design_type lives
            # ONCE here (not restated in a sub-dict).
            "design_type": safe(lambda: mode_full.get("design_type")),
            "feature_count": safe(lambda: mode_full.get("timeline_feature_count")),
            # SCOPE: timeline-only (errored/warned features). Stale references show as is_out_of_date
            # on tree nodes, and the doc-wide verdict is workspace_orient's is_healthy. null (not
            # true) when the timeline itself did not read - an open Form/base-feature edit too.
            "timeline_healthy": (safe(lambda: (health or {}).get("healthy"))
                                 if has_timeline else None),
            "contents": _fingerprint(design),      # bodies/sketches/components/joints/parameters
        }
        # for each PRESENT + non-obvious content class, name the tool that acts on it - the inbound
        # breadcrumb to families (param_*, joint_*) a read-first agent would otherwise never find.
        ptrs = _content_pointers(out["contents"])
        # a CAM document's machining state is invisible to this design read - point at cam_get so an
        # agent drilling via design_get learns the Manufacture half exists.
        if _has_cam(design):
            ptrs["cam"] = "cam_get for the machining setups/operations (this document has CAM data)"
        if ptrs:
            out["pointers"] = ptrs
        # surface health DETAIL only when there's something wrong (else 'healthy' above says it all).
        if health and (health.get("error_count") or health.get("warning_count")):
            out["health"] = {k: v for k, v in health.items()
                             if k in ("errors", "warnings", "error_count", "warning_count") and v}

    # ── deeper slices (opt-in) ──
    if "mode" in inc:
        out["mode_detail"] = mode_full          # the full capability can{} map
    if "tree" in inc:
        out["tree"], terr = _slice_tree(design, max_depth, component, bool(tree_bodies),
                                        bool(tree_handles), max_results, name_filter)
        if terr:
            return terr
    if "timeline" in inc:
        out["timeline"], tlerr = _slice_timeline(design, include_suppressed, group,
                                                 bool(timeline_params), max_results)
        if tlerr:
            return tlerr
    if "configurations" in inc:
        # A non-configured design legitimately has no config table - that's not an error of design_get,
        # so degrade to a null + reason rather than failing the whole read.
        cfg, cerr = _slice_configurations(design, max_results)
        out["configurations"] = cfg if cfg is not None else {
            "configured": False,
            "reason": (cerr.get("message") if cerr else "no configuration table"),
        }
    if "materials" in inc:
        out["materials"], materr = _slice_materials(design, library, name_filter, max_results)
        if materr:
            return materr
    if "appearances" in inc:
        out["appearances"], apperr = _slice_appearances(design, library, name_filter, max_results)
        if apperr:
            return apperr
    if "attributes" in inc:
        out["attributes"], atterr = _slice_attributes(design, attribute_group, attribute_key)
        if atterr:
            return atterr
    if "metadata" in inc:
        out["metadata"], mderr = _slice_metadata(design, name_filter, max_results, component)
        if mderr:
            return mderr
    if "definition" in inc:
        out["definition"], derr = _slice_definition(feature, units)
        if derr:
            return derr
    if "datums" in inc:
        out["datums"], daterr = _slice_datums(design, component, name_filter, max_results)
        if daterr:
            return daterr

    # advertise the slices NOT yet pulled (load-bearing: an un-named flag is invisible to the agent).
    remaining = [s for s in _SLICES if s not in inc]
    if want_default and remaining:
        out["note"] = ("'default' keeps overview; include=" + str(remaining) +
                       ". 'max_depth'/'component'/'name_filter'/'max_results'/'tree_bodies'/"
                       "'tree_handles' scope the tree; "
                       "'group'/'include_suppressed'/'timeline_params' the timeline; "
                       "'library'/'name_filter'/'max_results' the catalog; 'attribute_group' "
                       "(required)/'attribute_key' the attributes; 'component'/'name_filter'/"
                       "'max_results' the metadata/datums; 'feature'/'units' the definition.")
    # A census nothing could be read from leaves 'occurrences' out of contents entirely, which reads
    # exactly like a design holding no placed instance. The marker beside it is what tells the two
    # apart, so the unreadable one is stated in words as well.
    if (out.get("contents") or {}).get("occurrences_walk") == _common.WALK_UNREADABLE:
        out["note"] = (out.get("note", "")
                       + " contents.occurrences_walk='unreadable': NEITHER root.allOccurrences nor "
                         "the component.occurrences fallback enumerated, so the occurrence count is "
                         "missing because it is UNKNOWN, not because the design holds none.").strip()
    # An open Form or base-feature edit reads direct too, so a direct-reading orientation carries the
    # same caveat design_set_mode's not-taken refusal and workspace_orient's verdict do.
    if want_default and safe(lambda: mode_full.get("design_type")) == _inputs.MODE_DIRECT:
        from . import _design_common
        out["note"] = (out.get("note", "") + _design_common.OPEN_EDIT_CAVEAT).strip()
    return ok(out)


def _normalize_include(include):
    """Accept include as a list, a comma-string, or a single slice name; -> a list of slice names."""
    if include in (None, "", []):
        return []
    if isinstance(include, str):
        return [s.strip().lower() for s in include.split(",") if s.strip()]
    return [str(s).strip().lower() for s in include]


TOOL_DESCRIPTION = (
    "Design summary and opt-in detail."
)

tool = (
    Tool.create_simple(name="design_get", description=TOOL_DESCRIPTION)
    .add_input_property("include", {"type": "array",
            "items": {"type": "string", "enum": list(_SLICES + _DEFAULT_NAMES)}})
    .add_input_property("max_depth", {"type": "integer",
            "description": f"Max {_TREE_MAX_DEPTH}."})
    .add_input_property("component", {"type": "string",
            "description": "Component/occurrence."})
    .add_input_property("tree_bodies", {"type": "boolean"})
    .add_input_property("tree_handles", {"type": "boolean"})
    .add_input_property("include_suppressed", {"type": "boolean"})
    .add_input_property("group", {"type": "string"})
    .add_input_property("timeline_params", {"type": "boolean"})
    .add_input_property("library", {"type": "string",
            "description": "Exact library name/id."})
    .add_input_property("name_filter", {"type": "string",
            "description": "Substring: top-level tree, metadata, datums, catalogs."})
    .add_input_property("max_results", {"type": "integer",
            "description": f"Catalog 50 (max 200); tree {_TREE_CHILDREN_DEFAULT}/level; "
                           f"timeline {_TIMELINE_MAX_ITEMS}; metadata {_METADATA_MAX_ROWS}."})
    .add_input_property("attribute_group", {"type": "string"})
    .add_input_property("attribute_key", {"type": "string"})
    .add_input_property(*_FEATURE.as_property())
    .add_input_property(*_inputs.UNITS.as_property())
    .strict_schema()
)
item = Item.create_tool_item(tool=tool, write="read", handler=handler, run_on_main_thread=True)


def register_tool():
    register(item)
