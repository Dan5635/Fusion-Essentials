# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Read solid overlap per placed body pair, aggregating volume by occurrence pair."""

import math
import time

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common
from . import _geom
from . import _outputs
from . import _inputs

app = adsk.core.Application.get()

# What this tool RETURNS: the verdict contract - relation/passed/measured/tolerance_used, enforced.
RETURNS = [_outputs.ReturnsVerdict(relations=("interference_free",))]

# Native FSAE: 1,903 pairs take about 23 s. Stop between calls after 20 s;
# a single native call can overrun this soft budget.
_PAIR_CAP = 5000
_TIME_BUDGET_S = 20.0
_BODY_PAGE_DEFAULT = 30
_BODY_PAGE_MAX = 100
_OCCURRENCES = _inputs.OccurrenceRefList("occurrences", required=False, default=None)
_INPUTS = (_OCCURRENCES,)


def _own_solid_bodies(entity):
    """Return the entity's direct solid bodies and whether the collection/read was complete."""
    coll = safe(lambda: entity.bRepBodies)
    count = _common.counted(lambda: coll.count) if coll is not None else None
    if count is None or count < 0:
        return [], False
    rows = list(_common.iter_collection(coll))
    complete = len(rows) == count
    solids = []
    for body in rows:
        is_solid = safe(lambda body=body: body.isSolid)
        if is_solid is None:
            complete = False
        elif is_solid:
            solids.append(body)
    return solids, complete


def _entity_box(bodies):
    """The world AABB spanning `bodies`' own boundingBox reads, or None. Each body here is already
    an occurrence PROXY or a root-owned NATIVE - both read in root/world space."""
    return _geom.union_box([safe(lambda b=b: b.boundingBox) for b in bodies])


def _touch(box_a, box_b):
    """True when two world boxes overlap or touch, or either did not read - a PRUNE keeps any pair
    it cannot prove apart, so a box that fails to read never drops a real interference."""
    if box_a is None or box_b is None:
        return True
    for axis in ("x", "y", "z"):
        lo_a, hi_a = getattr(box_a.minPoint, axis), getattr(box_a.maxPoint, axis)
        lo_b, hi_b = getattr(box_b.minPoint, axis), getattr(box_b.maxPoint, axis)
        if hi_a < lo_b or hi_b < lo_a:
            return False
    return True


def _comparable_entities(occurrences, root=None, include_root=True):
    """Return solid placements, root bodies, (bodyless occurrence, readable) pairs, completeness."""
    occ_entities, bodyless = [], []
    complete = True
    for occ in occurrences:
        bodies, readable = _own_solid_bodies(occ)
        complete = complete and readable
        if not bodies:
            bodyless.append((occ, readable))
            continue
        occ_entities.append({"label": _geom.address(occ), "bodies": bodies,
                             "occurrence": occ,
                             "occurrence_handle": safe(lambda occ=occ: occ.entityToken),
                             "occurrence_path": safe(lambda occ=occ: occ.fullPathName)})
    root_entities = []
    if include_root and root is not None:
        root_bodies, readable = _own_solid_bodies(root)
        complete = complete and readable
        for b in root_bodies:
            label = safe(lambda b=b: b.name) or "(unnamed body)"
            root_entities.append({"label": label, "bodies": [b], "occurrence": None,
                                  "occurrence_handle": None, "occurrence_path": "root"})
    return occ_entities, root_entities, bodyless, complete


def _plan_pairs(entities, body_by_id):
    """Return touching pairs and an integer count, retaining no pruned pair list."""
    bodies = []
    for i, entity in enumerate(entities):
        for body_index, body in enumerate(entity["bodies"]):
            bodies.append({"entity_index": i, "label": entity["label"], "body": body,
                           "body_index": body_index, "box": _entity_box([body])})
    pairs, pruned = [], 0
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            if _touch(a["box"], b["box"]):
                pairs.append((a, b))
            else:
                pruned += 1
                _count_pair(body_by_id, (a, b), "pairs_pruned")
    return pairs, pruned


def _body_rows(entities):
    """Build the deterministic census, identity-read status and pair-count lookup."""
    rows, by_id = [], {}
    identity_complete = True
    for entity in entities:
        for body_index, body in enumerate(entity["bodies"]):
            body_handle = safe(lambda body=body: body.entityToken)
            body_name = safe(lambda body=body: body.name)
            occurrence_handle = entity["occurrence_handle"]
            occurrence_path = entity["occurrence_path"]
            identity_complete = identity_complete and bool(body_handle or body_name) and bool(
                occurrence_handle or occurrence_path)
            row = {"occurrence_handle": occurrence_handle,
                   "occurrence_path": occurrence_path,
                   "body_handle": body_handle,
                   "body_name": body_name,
                   "body_index": body_index,
                   "occurrence_visible": safe(lambda entity=entity: entity["occurrence"].isVisible)
                       if entity["occurrence"] is not None else None,
                   "body_visible": safe(lambda body=body: body.isVisible),
                   "pairs_analyzed": 0, "pairs_pruned": 0, "pairs_omitted": 0}
            by_id[id(body)] = row
            rows.append((row, body))
    rows.sort(key=lambda pair: (pair[0]["occurrence_path"] or "",
                                pair[0]["body_name"] or "", pair[0]["body_handle"] or "",
                                pair[0]["body_index"]))
    return [row for row, _ in rows], by_id, identity_complete


def _count_pair(by_id, pair, key):
    """Increment one participation count on each placed body in a candidate pair."""
    for side in pair:
        row = by_id.get(id(side["body"]))
        if row is not None:
            row[key] += 1


def _bodyless_selection_error(bodyless):
    """The refusal naming each selected occurrence read with no direct solid body, or None."""
    empty = [occ for occ, readable in bodyless if readable]
    if not empty:
        return None
    rows = []
    for occ in empty:
        kids = [_geom.address(c) for c in
                _common.iter_collection(safe(lambda occ=occ: occ.childOccurrences))]
        rows.append(f"{_geom.address(occ)} (" + (
            f"child occurrences: {_common.named_with_remainder(kids, cap=6)})" if kids
            else "no child occurrence found)"))
    return (f"Cannot check interference: {len(empty)} selected occurrence(s) hold no direct solid "
            f"body, so the analysis would leave them out: {'; '.join(rows)}. Pass the child "
            "occurrences that hold the bodies instead, or remove these from 'occurrences'. "
            "Nothing was analysed.")


def _resolve_scope(raw):
    """Resolve a supplied occurrence list and refuse empties or duplicate placements."""
    if raw == [] or isinstance(raw, str) and not raw.strip():
        return None, "An explicit occurrences list must select at least one occurrence."
    values, err = _inputs.resolve_inputs(_INPUTS, {"occurrences": raw})
    if err:
        return None, err["message"]
    selected = values["occurrences"] or []
    seen = set()
    for occ in selected:
        token = safe(lambda occ=occ: occ.entityToken)
        path = safe(lambda occ=occ: occ.fullPathName)
        key = ("token", token) if token else ("path", path) if path else None
        if key is None:
            return None, "A selected occurrence has no readable handle or full path; scope is unknown."
        if key in seen:
            return None, f"The occurrences list repeats placement '{path or token}'. Remove the duplicate."
        seen.add(key)
    return selected, None


def _run_pair(design, include_coincident_faces, ent_a, ent_b):
    """Return result count and readable volume between two placed bodies."""
    # Results can return native bodies without placement context; two inputs make ownership exact.
    coll = adsk.core.ObjectCollection.create()
    for ent in (ent_a, ent_b):
        if not coll.add(ent["body"]):
            raise RuntimeError(f"Could not collect a body of '{ent['label']}' for interference.")
    inp = design.createInterferenceInput(coll)
    inp.areCoincidentFacesIncluded = bool(include_coincident_faces)
    results = design.analyzeInterference(inp)
    count = _common.counted(lambda: results.count)
    if count is None or count < 0:
        raise RuntimeError("Interference result count did not read.")
    vol = 0.0
    for i in range(count):
        r = results.item(i)
        if r is None:
            raise RuntimeError(f"Interference result {i} did not read.")
        ib = safe(lambda r=r: r.interferenceBody)
        v = safe(lambda ib=ib: ib.volume) if ib else None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            vol = None
        elif vol is not None:
            vol += float(v)
    return count, vol


def handler(include_coincident_faces: bool = False, occurrences=None,
            max_results: int = _BODY_PAGE_DEFAULT, offset: int = 0) -> dict:
    """See TOOL_DESCRIPTION."""
    started = time.monotonic()
    design, design_refusal = _common.require_design()
    if design_refusal is not None:
        return design_refusal
    root = safe(lambda: design.rootComponent)
    if not root:
        return error("No root component.")

    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= _BODY_PAGE_MAX:
        return error(f"max_results must be an integer from 1 to {_BODY_PAGE_MAX}.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return error("offset must be a nonnegative integer.")
    explicit_scope = occurrences is not None
    selected, scope_error = (_resolve_scope(occurrences) if explicit_scope else (None, None))
    if scope_error:
        return error(scope_error)
    walk = None if explicit_scope else _common.occurrence_walk(design)
    selected_occurrences = selected if explicit_scope else walk.occurrences
    occ_entities, root_entities, bodyless, bodies_complete = _comparable_entities(
        selected_occurrences, root if not explicit_scope else None, include_root=not explicit_scope)
    entities = occ_entities + root_entities
    n_occ, n_root_bodies = len(selected_occurrences), len(root_entities)
    refusal = _bodyless_selection_error(bodyless) if explicit_scope else None
    if refusal:
        return error(refusal)

    if sum(len(e["bodies"]) for e in entities) < 2:
        solid_count = sum(len(e["bodies"]) for e in entities)
        if not bodies_complete:
            return error("Cannot check interference: at least one selected solid-body collection "
                         "or isSolid flag did not read, so the analysis set is unknown. Re-read "
                         "the selected bodies before retrying; no verdict was formed.")
        # A body-less occurrence (a container, or one whose component holds no solid) is not a
        # comparable solid - two of them alone give nothing to compare, never a clean pass.
        labels = [_geom.address(occ) for occ, _readable in bodyless]
        bodyless_note = (f", {len(labels)} body-less occurrence(s) excluded "
                         f"({', '.join(labels[:8])}{', ...' if len(labels) > 8 else ''})"
                         if labels else "")
        return error(
            f"Cannot check interference: this scope exposes {solid_count} comparable solid "
            f"bod{'y' if solid_count == 1 else 'ies'} ({n_occ} occurrence(s), "
            f"{n_root_bodies} root-level solid body(ies){bodyless_note}), and interference needs "
            "at least two solid bodies. No verdict was formed - this is NOT a pass.")

    body_census, body_by_id, identity_complete = _body_rows(entities)
    census_complete = bodies_complete and identity_complete and (
        walk is None or walk.complete and not walk.broken)
    to_analyze, pairs_pruned = _plan_pairs(entities, body_by_id)
    total_planned = len(to_analyze)
    cap_hit = total_planned > _PAIR_CAP
    omitted = to_analyze[_PAIR_CAP:] if cap_hit else []
    if cap_hit:
        to_analyze = to_analyze[:_PAIR_CAP]

    volumes = {}
    analyzed = 0
    try:
        for ent_a, ent_b in to_analyze:
            if time.monotonic() - started >= _TIME_BUDGET_S:
                break
            count, vol = _run_pair(design, include_coincident_faces, ent_a, ent_b)
            analyzed += 1
            _count_pair(body_by_id, (ent_a, ent_b), "pairs_analyzed")
            if count:
                key = (ent_a["entity_index"], ent_b["entity_index"])
                prior = volumes.get(key, 0.0)
                volumes[key] = None if prior is None or vol is None else prior + vol
    except Exception as e:
        return error(f"Interference analysis failed: {e}")
    time_hit = analyzed < len(to_analyze)
    cap_hit = cap_hit and not time_hit
    omitted = to_analyze[analyzed:] + omitted
    for pair in omitted:
        _count_pair(body_by_id, pair, "pairs_omitted")
    limits = []
    if cap_hit:
        limits.append(f"{_PAIR_CAP} placed-body pair analysis cap")
    if time_hit:
        limits.append(f"{_TIME_BUDGET_S:g} s analysis budget")
    incomplete_pairs = {(a["entity_index"], b["entity_index"]) for a, b in omitted}
    items = []
    for (a, b), vol in volumes.items():
        row = {"occurrence_one": entities[a]["label"], "occurrence_two": entities[b]["label"],
               "overlap_volume_cm3": round(vol, 4) if vol is not None else None}
        if (a, b) in incomplete_pairs:
            row["partial"] = True
        items.append(row)
    items.sort(key=lambda it: (it["overlap_volume_cm3"] is None,
                               -(it["overlap_volume_cm3"] or 0)))
    unreadable_volumes = sum(r["overlap_volume_cm3"] is None for r in items)

    clear = len(items) == 0
    # A CLEAN verdict is a claim about everything; a positive finding is not. So an incomplete
    # analysis set (an unresolved reference, or the pair cap) refuses only when it would otherwise
    # report a pass - one interfering pair that WAS found stays true whatever else was skipped.
    walk_broken = walk.broken if walk is not None else []
    walk_complete = walk.complete if walk is not None else True
    walk_method = walk.method if walk is not None else "selected_occurrences"
    unresolved = walk.names() if walk is not None else []
    if clear and (walk_broken or not walk_complete or not bodies_complete or cap_hit or time_hit):
        reasons = []
        if walk_broken:
            reasons.append(f"{len(walk_broken)} occurrence(s) hold an unresolved external "
                           f"reference ({', '.join(sorted({b['name'] for b in walk_broken}))}) - "
                           "their component could not be read, so they carry no geometry this "
                           "analysis could compare")
        elif not walk_complete:
            reasons.append("the design-wide occurrence walk did not complete, so the analysis set "
                           "is a subset of the assembly")
        if not bodies_complete:
            reasons.append("one or more solid-body collections or solid flags did not read, so the "
                           "analysis set may be incomplete")
        if cap_hit or time_hit:
            sample = "; ".join(dict.fromkeys(
                f"{a['label']}/{safe(lambda a=a: a['body'].name) or '(unnamed body)'} / "
                f"{b['label']}/{safe(lambda b=b: b['body'].name) or '(unnamed body)'}"
                for a, b in omitted[:4]))
            reasons.append(f"the {' and '.join(limits)} was reached - "
                           f"{len(omitted)} placed-body pair(s) "
                           f"were not analysed ({sample})")
        remedies = []
        if walk_broken or not walk_complete:
            remedies.append("Inspect workspace_orient health.unresolved_references and repair "
                            "the unreadable references before re-running.")
        if not bodies_complete:
            remedies.append("Re-read the selected occurrence bodies in Fusion before relying on a clear result.")
        if cap_hit or time_hit:
            remedies.append("Check omitted body pairs with the Interference command in Fusion.")
        return error(
            f"Cannot certify interference-free: {'; '.join(reasons)}. "
            f"{analyzed} placed-body pair(s) WERE analysed and none interfere; "
            f"no pass was formed over this scope. {' '.join(remedies)}")
    note = ("No interference found among the compared solid bodies"
            + (" within the selected occurrences" if explicit_scope else " in the whole design")
            + "; coincident faces "
            + ("included" if include_coincident_faces else "excluded") + "." if clear else
            f"{len(items)} interfering occurrence pair(s) - bodies overlap or meet at coincident "
            "faces. Each lists the two occurrences and readable overlap volume from analysed body "
            "pairs; fix positioning/sizing/joints. (A "
            "self-pair compares bodies in one occurrence.)")
    if pairs_pruned:
        note += (f" {pairs_pruned} placed-body pair(s) were pruned - their world boxes cannot touch, so they "
                 "were not analysed.")
    if cap_hit or time_hit:
        note += (f" The {' and '.join(limits)} was reached; {len(omitted)} placed-body pair(s) "
                 "were not analysed. Rows marked partial have incomplete volumes.")
    if unreadable_volumes:
        note += f" {unreadable_volumes} pair(s) have unreadable overlap volume (null)."
    if walk_broken:
        note += (f" {len(walk_broken)} occurrence(s) with an unresolved external reference were NOT "
                 "compared - their component could not be read, so they carry no geometry for this "
                 "analysis; measured.unresolved_references names them.")
    if not bodies_complete:
        note += " Some body collection reads were incomplete; inspect the reported census before relying on a clear result."
    if not census_complete:
        note += " Body census enumeration is incomplete; inspect traversal health and null identity fields."
    page = body_census[offset:offset + max_results]
    next_offset = offset + len(page) if offset + len(page) < len(body_census) else None
    if offset > len(body_census):
        page = []
        next_offset = None
    if explicit_scope:
        note += " The scope includes only the selected occurrences' direct solid bodies."
    note += " Hidden bodies remain included. Body pages are separate reads, not a frozen snapshot."
    return ok({
        "relation": "interference_free",
        "passed": clear,
        "measured": {"interference_count": len(items), "occurrences_checked": len(occ_entities),
                     "root_bodies_checked": n_root_bodies,
                     # WHICH walk produced the analysis set, so a caller can tell a design-wide
                     # comparison from one rebuilt around an unreadable allOccurrences.
                     "occurrences_walk": walk_method,
                     "unresolved_references": unresolved,
                     "pair_unit": "placed_body",
                     "pairs_analyzed": analyzed, "pairs_pruned": pairs_pruned,
                     "pairs_omitted": len(omitted),
                     "analysis_complete": walk_complete and not walk_broken and bodies_complete
                     and not cap_hit and not time_hit,
                     "scope": {"kind": "selected_occurrences" if explicit_scope else "whole_design",
                               "occurrence_count": n_occ},
                     "body_census": {"count": len(body_census), "offset": offset,
                                     "returned_count": len(page), "truncated": next_offset is not None,
                                     "next_offset": next_offset,
                                     "enumeration_complete": census_complete, "bodies": page},
                     "interferences": items},
        "tolerance_used": {"coincident_faces_included": bool(include_coincident_faces)},
        "note": note,
    })


TOOL_DESCRIPTION = (
    "Solid overlap/contact; hidden bodies count. Occurrences: direct bodies only; page census.\n"
    + _outputs.produces_block(RETURNS)
)

interference_tool = (
    Tool.create_simple(name="assembly_inspect_interference", description=TOOL_DESCRIPTION)
    .add_input_property("include_coincident_faces", {"type": "boolean",
            "description": "Count flush contact."})
    .add_input_property("max_results", {"type": "integer", "minimum": 1,
            "maximum": _BODY_PAGE_MAX, "description": "Bodies per census page."})
    .add_input_property("offset", {"type": "integer", "minimum": 0,
            "description": "Body offset; each call re-analyzes."})
)
interference_tool = _inputs.apply_to_tool(interference_tool, _INPUTS).strict_schema()
interference_item = Item.create_tool_item(tool=interference_tool, write="read", handler=handler, run_on_main_thread=True)


def register_tool():
    register(interference_item)
