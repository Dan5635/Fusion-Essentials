# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: derive another saved document's design (whole, or a named subset) into a
component of the active design - a one-way linked COPY that updates FROM the source while edits here
never travel back. Requires a PARAMETRIC destination design and an ALREADY-OPEN source: Fusion opens
documents asynchronously, so createInput returns None for a source that is not open yet."""

import re
from collections import Counter

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common
from . import _edit_feature_common
from . import _inputs
from . import _outputs
from ._data_common import _resolve_data_file
from ._param_common import parameter_census

app = adsk.core.Application.get()

_INTO_COMPONENT = _inputs.OccurrenceRef("into_component",
        description="Default root.")

# Insert > Derive (Component.features.deriveFeatures) has no Direct-modeling equivalent - confirmed
# against the live API surface (deriveFeatures is a parametric feature collection).
_MODE_GUARD = _inputs.ModeGuard(
    _inputs.MODE_PARAMETRIC,
    why="Insert > Derive (Component.features.deriveFeatures) has no Direct-modeling equivalent.",
    fix_hint="Switch to parametric mode first (design_set_mode).")

_ERROR_HEALTH = 2  # adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState (see _common.timeline_health)

_UNREAD = object()      # an activeOccurrence read that RAISED - distinct from one that reads None


def _as_names(raw, field):
    """Return explicit names, refusing blank entries instead of widening the selection."""
    if raw is None or raw == [] or raw == ():
        return []
    names = raw.split(",") if isinstance(raw, str) else raw
    if not isinstance(names, (list, tuple)):
        raise ValueError(f"{field} {raw!r} must be names. Omit it or use [] for no selection.")
    for i, name in enumerate(names):
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{field}[{i}] {name!r} is not a nonblank name. Remove that entry; "
                             "omit the selector or use [] only when no selection is intended.")
    return [name.strip() for name in names]


def _names(values):
    """Comma-joined available-names list for a 'not found' message, or '(none)'."""
    return ", ".join(n for n in values if n) or "(none)"


def _find_open_document(data_file):
    """An already-open Document referencing the same DataFile LINEAGE, or None. Compared by
    DataFile.id (the lineage URN, version-independent) - Fusion never opens one lineage twice."""
    target_id = safe(lambda: data_file.id)
    if not target_id:
        return None
    for d in _common.iter_collection(safe(lambda: app.documents)):
        df = safe(lambda d=d: d.dataFile)
        if df is not None and safe(lambda df=df: df.id) == target_id:
            return d
    return None


# ── source-entity resolution (names in the SOURCE design - a CLOSED doc, so no active-design kind
# applies; resolve by case-insensitive EXACT match and REFUSE an ambiguous name per the constitution) ──

def _source_components(source_design):
    """Every component in the SOURCE design (root + sub-components), as a list."""
    return list(_common.iter_collection(safe(lambda: source_design.allComponents)))


def _owned_bodies(comp):
    """Every body (BRep + mesh) directly owned by a source component."""
    out = []
    for coll_name in ("bRepBodies", "meshBodies"):
        out.extend(_common.iter_collection(safe(lambda: getattr(comp, coll_name, None))))
    return out


def _resolve_source_components(source_design, names):
    """(components, error). Each name -> the source Component by case-INSENSITIVE EXACT match
    (the find_setup idiom - a source component name is scope-unique). An AMBIGUOUS name (2+ distinct
    components share it) is REFUSED, never first-match; a miss lists the available component names."""
    comps = _source_components(source_design)
    available = [safe(lambda c=c: c.name) for c in comps]
    out = []
    for want in names:
        w = want.strip().lower()
        matches = [c for c in comps if (safe(lambda c=c: c.name) or "").lower() == w]
        if len(matches) > 1:
            return None, (f"Source component name '{want}' is ambiguous - {len(matches)} distinct "
                          "components share it; refusing rather than deriving the wrong one. "
                          f"Available: {_names(available)}.")
        if not matches:
            return None, (f"Source component '{want}' not found in the source design. "
                          f"Available: {_names(available)}.")
        out.append(matches[0])
    return out, None


def _resolve_source_bodies(source_design, specs):
    """(bodies, error) for body names or 'Component/Body' specs; see _resolve_source_body_pairs."""
    pairs, err = _resolve_source_body_pairs(source_design, specs)
    return (None, err) if err else ([body for _owner, body in pairs], None)


def _sub_component_bodies(source_design, specs):
    """[(spec, owner name)] for resolved specs whose body a source sub-component owns."""
    pairs, err = _resolve_source_body_pairs(source_design, specs)
    root = safe(lambda: source_design.rootComponent)
    return [] if err else [(spec, safe(lambda owner=owner: owner.name) or "?")
                           for spec, (owner, _body) in zip(specs, pairs)
                           if _common.same_component(owner, root) is False]


def _resolve_source_body_pairs(source_design, specs):
    """(pairs, error). Each spec is a body NAME (resolved design-wide in the source) or
    'Component/Body' (scoped to that component's bodies); each pair is (owner, body). A NAME that
    matches bodies in 2+ components is REFUSED (names the holders, asks to qualify); a miss is named."""
    comps = _source_components(source_design)
    out = []
    for spec in specs:
        scope, sep, body_name = spec.rpartition("/")
        body_name = body_name.strip()
        scope = scope.strip()
        search = comps
        if sep and scope:
            search = [c for c in comps if (safe(lambda c=c: c.name) or "").lower() == scope.lower()]
            if not search:
                return None, (f"Source body '{spec}': no component '{scope}' in the source. "
                              f"Available components: {_names([safe(lambda c=c: c.name) for c in comps])}.")
        matches = [(c, b) for c in search for b in _owned_bodies(c)
                   if (safe(lambda b=b: b.name) or "").lower() == body_name.lower()]
        if len(matches) > 1:
            holders = _names(sorted({safe(lambda c=c: c.name) or "?" for c, _ in matches}))
            return None, (f"Source body '{spec}' is ambiguous - a body named '{body_name}' exists in "
                          f"{holders}. Qualify it as 'Component/Body'.")
        if not matches:
            return None, (f"Source body '{spec}' not found. Use a SOURCE body name or "
                          "'Component/Body', not a handle; doc_activate the source, then "
                          "design_get(include=['tree'], tree_bodies=true).")
        out.append(matches[0])
    return out, None


def _component_occurrences(source_root, comp):
    """Every occurrence (at any assembly level) of `comp` in the source - the browser-selection analog
    of picking that part for the derive. Occurrence is a first-class sourceEntity (live-verified)."""
    return list(_common.iter_collection(safe(lambda: source_root.allOccurrencesByComponent(comp))))


def _collect_source_entities(source_design, component_names, body_names):
    """Resolve component + body names to the entity list DeriveFeatureInput.sourceEntities takes.
    A named component contributes its occurrence(s) (the root component contributes ITSELF - the
    whole-design case); a named body contributes that BRepBody/MeshBody. Returns (entities, labels,
    error). Empty names -> ([], [], None) so the caller can fall back to the whole design."""
    entities, labels = [], []
    source_root = safe(lambda: source_design.rootComponent)
    comps, err = _resolve_source_components(source_design, component_names)
    if err:
        return None, None, err
    for want, comp in zip(component_names, comps):
        # same_component, not a NAME compare: the resolved component and source_design.rootComponent
        # are separate wrappers (component identity is never stable), and a name that will not read
        # on one of them would send the ROOT down the occurrence branch, where it has none.
        at_source_root = _common.same_component(comp, source_root)
        if at_source_root is True:
            entities.append(comp)                       # the whole source design (Component form)
            labels.append(f"{want} (whole design)")
            continue
        if at_source_root is None:
            # The two branches build DIFFERENT source entities (the Component itself vs its
            # occurrences), so an unproven answer picks the wrong sourceEntities half the time - and
            # the occurrence branch's own refusal would blame a missing instance instead.
            return None, None, (f"Whether source component '{want}' is the source design's ROOT "
                                "could not be read, and the root derives as itself while any other "
                                "component derives through its occurrences - so which entities to "
                                "derive is unknown. Name a sub-component, or omit 'components' to "
                                "derive the whole source design.")
        occs = _component_occurrences(source_root, comp)
        if not occs:
            return None, None, (f"Source component '{want}' has no occurrence in the assembly to "
                                "derive (it is defined but not instanced).")
        entities.extend(occs)
        labels.append(want if len(occs) == 1 else f"{want} (x{len(occs)})")
    bodies, err = _resolve_source_bodies(source_design, body_names)
    if err:
        return None, None, err
    entities.extend(bodies)
    labels.extend(body_names)
    return entities, labels, None


# ── read-back: what ACTUALLY landed. feature.bodies is EMPTY for an occurrence-tree derive (the
# content lands nested under a derived occurrence), so bodies are counted off those occurrences too ──

def _body_total(design):
    """Complete design BRep-body total, or None when any census read fails."""
    components = safe(lambda: design.allComponents)
    total = _common.counted(lambda: components.count) if components is not None else None
    if total is None or total < 0:
        return None
    body_total = 0
    for i in range(total):
        component = safe(lambda i=i: components.item(i))
        if component is None:
            return None
        count = _common.counted(lambda component=component: component.bRepBodies.count)
        if count is None or count < 0:
            return None
        body_total += count
    return body_total


def _occurrence_tokens(comp):
    """entityToken of every occurrence directly in `comp` right now - a before/after snapshot so a
    NEW derived occurrence can be told apart from one that was already there."""
    tokens = set()
    for o in _common.iter_collection(safe(lambda: comp.occurrences)):
        tok = safe(lambda o=o: o.entityToken)
        if tok:
            tokens.add(tok)
    return tokens


def _subtree_body_count(occ):
    """Bodies in an occurrence's whole subtree (its own component's bodies + every descendant's) -
    a whole-design derive lands ONE top occurrence whose bodies live in nested sub-components, so a
    top-level count reads 0 while 10 bodies are really there (live-verified)."""
    total = safe(lambda: occ.bRepBodies.count, 0) or 0
    for ch in _common.iter_collection(safe(lambda: occ.childOccurrences)):
        total += _subtree_body_count(ch)
    return total


def _new_derived(comp, before_tokens):
    """Occurrences now directly in `comp` that were not there before add() and read isDerived=true."""
    out = []
    for o in _common.iter_collection(safe(lambda: comp.occurrences)):
        tok = safe(lambda o=o: o.entityToken)
        if tok and tok in before_tokens:
            continue
        if safe(lambda o=o: o.isDerived, False):
            out.append(o)
    return out


def _occurrence_rows(occurrences):
    """[{name, body_count}] per occurrence, counting its whole subtree's bodies."""
    return [{"name": safe(lambda o=o: o.name), "body_count": _subtree_body_count(o)}
            for o in occurrences]


def _new_derived_occurrences(comp, before_tokens):
    """[{name, body_count}] for the new derived occurrences in `comp`."""
    return _occurrence_rows(_new_derived(comp, before_tokens))


_CENSUS_CAP = 2000


def _subtree_census(occurrences):
    """[(component name, [body names])] under the derived occurrences, or None when any read fails."""
    out, stack = [], list(occurrences)
    while stack:
        if len(out) >= _CENSUS_CAP:
            return None
        occ = stack.pop()
        name = safe(lambda: occ.component.name)
        bodies, children = safe(lambda: occ.bRepBodies), safe(lambda: occ.childOccurrences)
        body_count = _common.counted(lambda: bodies.count)
        child_count = _common.counted(lambda: children.count)
        if name is None or body_count is None or child_count is None:
            return None
        body_names = [safe(lambda i=i: bodies.item(i).name) for i in range(body_count)]
        kids = [safe(lambda i=i: children.item(i)) for i in range(child_count)]
        if any(n is None for n in body_names) or any(k is None for k in kids):
            return None
        out.append((name, [n.lower() for n in body_names]))
        stack.extend(kids)
    return out


def _absent(census, component, body=None):
    """True when no census component named `component` (holding `body`) landed; None if unread."""
    if census is None or not component:
        return None
    # A source component derived again into the same host lands renamed '<name> (N)'.
    pattern = re.escape(component) + r"( \(\d+\))?"
    key = None if body is None else body.lower()
    return not any(re.fullmatch(pattern, name, re.IGNORECASE)
                   and (key is None or key in bodies) for name, bodies in census)


def _excluded_readback(feature, derived, source_root, comp_names, body_rows):
    """(excluded, unverified, error): each requested exclusion judged from what landed."""
    census = _subtree_census(derived) if derived else None
    excluded, unverified = [], []
    for name in comp_names:
        (excluded if _absent(census, name) else unverified).append(name)
    for spec, owner, body in body_rows:
        at_root = _common.same_component(owner, source_root)
        if at_root is False:
            # getDerivedEntity raises 'invalid argument sourceEntity' on a sub-component body.
            gone = _absent(census, safe(lambda: owner.name), safe(lambda: body.name))
            (excluded if gone else unverified).append(spec)
            continue
        if at_root is None:
            unverified.append(spec)
            continue
        try:
            landed = feature.getDerivedEntity(body)
        except Exception as exc:
            # A source ROOT body left out of the derive raises 'derived entity not found'.
            if "derived entity not found" not in str(exc):
                unverified.append(spec)
                continue
            landed = None
        if landed is not None:
            return None, None, f"excluded source body '{spec}' has a derived result; exclusion did not take"
        excluded.append(spec)
    return excluded, unverified, None


def _mapped_bodies(feature, sources, excluded, comp):
    """Read selected source bodies through the feature's mapping into the requested owner."""
    bodies = safe(lambda: comp.bRepBodies)
    count = _common.counted(lambda: bodies.count)
    if count is None or not 0 <= count <= 1000 or len(sources) > 1000:
        return None, "selected-body target membership could not be read within 1000 bodies"
    members = [safe(lambda i=i: bodies.item(i)) for i in range(count)]
    if any(b is None for b in members):
        return None, "selected-body target membership did not read completely"
    rows = []
    for source in sources:
        name = safe(lambda: source.name)
        is_excluded = safe(lambda: any(source == skipped for skipped in excluded))
        if is_excluded is None:
            return None, f"exclusion membership for source body '{name}' could not be read"
        try:
            body = feature.getDerivedEntity(source)
            if body is not None and is_excluded:
                return None, f"excluded source body '{name}' has a derived result; exclusion did not take"
            if body is None or body.isDerived is not True:
                return None, f"the mapping for source body '{name}' did not confirm isDerived=true"
            if not any(body == member for member in members):
                return None, f"the mapped source body '{name}' was not found in the requested component"
        except Exception as exc:
            if is_excluded and "derived entity not found" in str(exc):
                continue
            return None, f"the mapping for source body '{name}' could not be verified: {exc}"
        rows.append({"name": safe(lambda: body.name), "is_derived": True})
    return rows, None


_NAMES_CAP = 50                             # names one reply lists


def imported_parameters(before, after):
    """(names, reason): the parameters new since `before` that read as derived; None with the reason."""
    if before is None or after is None:
        return None, "the design's parameters did not read on both sides of the derive"
    fresh = [n for n in after if n not in before]
    blind = [n for n in fresh if after[n]["derived"] is None]
    if blind:
        return None, f"{len(blind)} new parameter(s) did not read their type"
    return sorted(n for n in fresh if after[n]["derived"]), None


def _capped(details, key, rows):
    """Store rows under `key`, capped, flagging the reply when any list was cut."""
    details[key] = rows[:_NAMES_CAP]
    if len(rows) > _NAMES_CAP:
        details["lists_truncated"] = True


def _favorite_changes(details, before, after):
    """Fill the parameter lists a favourites toggle is judged by; returns the became-local rows."""
    _capped(details, "parameters_disappeared", sorted(n for n in before if n not in after))
    _capped(details, "parameters_appeared",
            [{"name": n, "derived": after[n]["derived"]} for n in sorted(after) if n not in before])
    local = []
    for name in sorted(n for n in after if n in before):
        if before[name]["derived"] is True and after[name]["derived"] is False:
            row = {"name": name, "dependents": after[name]["dependents"]}
            if row["dependents"] is None:
                row["dependents_unread"] = "dependentParameters did not read"
            local.append(row)
    _capped(details, "became_local", local)
    blind = sorted(n for n in after if n in before
                   and None in (before[n]["derived"], after[n]["derived"]))
    if blind:
        _capped(details, "type_unread", blind)
    _capped(details, "user_and_derived_parameters",
            [{"name": n, "kind": r["kind"], "in_user_parameters": r["user"],
              "dependents": r["dependents"]}
             for n, r in sorted(after.items()) if r["kind"] != "ModelParameter"])
    return local


def _recompute(design, details):
    """Recompute the design after a derive write; returns why it did not complete, else None."""
    # Setting isIncludeFavoriteParameters leaves bodies built after the derive without geometry
    # until computeAll runs.
    try:
        answered = design.computeAll()
    except Exception as exc:
        details["recomputed"] = False
        details["recompute_raised"] = _edit_feature_common.sentence(exc)
        return f"computeAll raised: {details['recompute_raised']}"
    details["recomputed"] = answered is True
    return None if answered is True else f"computeAll answered {answered!r}."


def _unverified_bodies(name, what, why, details):
    """The error for a derive write that landed while the recompute or the body re-read did not."""
    return _edit_feature_common.failed(
        f"{what} on derive '{name}', but the bodies are unverified: {why} A body built after "
        "the derive can read no geometry until the design recomputes. Run design_recompute, then "
        "read design_get(include=['tree','timeline'], tree_bodies=true).", details)


def _bodies_unread_refusal(name):
    """The refusal for a derive write whose body shapes did not read beforehand."""
    return error(f"Nothing was written to derive '{name}': the body shapes of the design did not "
                 "read, so the edit's effect on them could not be judged. Run design_recompute, "
                 "then retry.")


def set_favorite_parameters(design, derive_feature, include):
    """Set a DeriveFeature's isIncludeFavoriteParameters; the reply lists what the parameters show."""
    include = bool(include)
    name = safe(lambda: derive_feature.name) or "(name unreadable)"
    marker, count = _common.timeline_marker(design)
    if marker is None or marker != count:
        return error(f"The timeline marker reads {marker} of {count}; favorite parameters of "
                     f"derive '{name}' are edited with the marker at the end. Roll to the end "
                     "with design_edit_timeline, then retry.")
    was = _common.read_flag(lambda: derive_feature.isIncludeFavoriteParameters)
    if was is None:
        return error(f"Derive '{name}' did not read isIncludeFavoriteParameters; nothing was "
                     "written. Check the feature with design_get(include=['timeline']).")
    before, problem = parameter_census(design, deep=True)
    if problem:
        return error(f"Nothing was written to derive '{name}': {problem}, so the edit could not "
                     "be judged. Read param_get(include_model_parameters=true).")
    details = {"feature": name, "requested": include, "favorite_parameters_before": was,
               "favorite_parameters_after": was}
    if was is include:
        details["edited"] = False
        details["note"] = (f"Derive '{name}' already reads isIncludeFavoriteParameters "
                           f"{str(include).lower()}; nothing was written.")
        return ok(details)
    bodies_before = _body_snapshot(design)
    if bodies_before is None:
        return _bodies_unread_refusal(name)
    health_before = _edit_feature_common.health(design, marker)
    raised = None
    try:
        derive_feature.isIncludeFavoriteParameters = include        # MUTATION
    except Exception as exc:
        raised = _edit_feature_common.sentence(exc)
    now = _common.read_flag(lambda: derive_feature.isIncludeFavoriteParameters)
    stale = _recompute(design, details)
    after, problem = parameter_census(design, deep=True)
    details["favorite_parameters_after"] = now
    moved = _body_changes(details, bodies_before, _body_snapshot(design))
    new_errors = _health_changes(details, design, health_before)
    local = [] if after is None else _favorite_changes(details, before, after)
    if after is None:
        details["parameters_unread"] = problem
    if raised:
        details["raised"] = raised
    if raised and now is include:
        return _edit_feature_common.failed(
            f"Fusion raised while setting isIncludeFavoriteParameters {str(include).lower()} on "
            f"derive '{name}': {raised} The flag reads {str(now).lower()} now, and 'details' "
            "lists the parameters as re-read after the raise. Read "
            "param_get(include_model_parameters=true) before retrying.", details)
    if now is not include:
        return _edit_feature_common.failed(
            f"Derive '{name}' reads isIncludeFavoriteParameters "
            f"{'nothing' if now is None else str(now).lower()} after setting "
            f"{str(include).lower()}. " + (f"Fusion raised: {raised} " if raised else "")
            + "Read param_get(include_model_parameters=true) for the parameters as they are now.",
            details)
    unverified = (stale or ("the bodies did not re-read after the recompute." if moved is None
                            else f"the timeline has new errors: {_quoted(new_errors)}."
                            if new_errors else None))
    if unverified:
        return _unverified_bodies(
            name, f"isIncludeFavoriteParameters reads {str(now).lower()} now", unverified, details)
    details["edited"] = True
    note = (f"Derive '{name}' now reads isIncludeFavoriteParameters {str(include).lower()}. The "
            "design was recomputed." + _body_sentences(moved))
    if local:
        note += (" Still present but no longer derived: "
                 + _common.named_with_remainder(
                     [f"'{r['name']}'" + (f" (used by {', '.join(r['dependents'])})"
                                          if r["dependents"] else "") for r in local]) + ".")
    for key, label in (("parameters_disappeared", "Gone"), ("parameters_appeared", "New")):
        rows = [r["name"] if isinstance(r, dict) else r for r in details.get(key, [])]
        if rows:
            note += f" {label}: " + _common.named_with_remainder([f"'{n}'" for n in rows]) + "."
    if after is None:
        note += f" The parameters did not re-read ({problem})."
    details["note"] = note + " Confirm with param_get(include_model_parameters=true)."
    return ok(details)


_DERIVE_KIND = "DeriveFeature"              # the objectType suffix a derive's timeline entity reads
_SOURCE_BODY_CAP = 1000                     # source root bodies one resolve reads


def _end_marker(design, what):
    """(marker, refusal): the marker when it sits at the timeline end, else the roll-to-end error."""
    marker, count = _common.timeline_marker(design)
    if marker is None or marker != count:
        return None, error(f"The timeline marker reads {marker} of {count}; {what} with the marker "
                           "at the end. Roll to the end with design_edit_timeline, then retry.")
    return marker, None


def _quoted(names):
    """Names as a capped, quoted wire list; 'nothing readable' for an unread list."""
    if names is None:
        return "nothing readable"
    return _common.named_with_remainder([f"'{n}'" for n in names], _NAMES_CAP) or "(none)"


def _body_snapshot(design):
    """Sorted (component, body, shape) rows for every body of the design, or None when unread."""
    shapes = _edit_feature_common.all_shapes(design)
    if shapes is None:
        return None
    return sorted((str(r["component"]), str(r["body"]), repr(r["shape"])) for r in shapes.values())


def _body_changes(details, before, after):
    """Fill the body lists an edit is judged by; returns the arrived, left and changed labels."""
    label = lambda pairs: [{"component": c, "body": b} for c, b in pairs]
    for side, rows in (("before", before), ("after", after)):
        details["body_count_" + side] = None if rows is None else len(rows)
        details["bodies_" + side] = None
        if rows is not None:
            _capped(details, "bodies_" + side, label(r[:2] for r in rows))
    if before is None or after is None:
        details["bodies_unread"] = "the bodies did not read on both sides of the write"
        return None
    was, now = Counter(r[:2] for r in before), Counter(r[:2] for r in after)
    shapes = lambda rows, pair: sorted(r[2] for r in rows if r[:2] == pair)
    moved = (sorted((now - was).elements()), sorted((was - now).elements()),
             [p for p in sorted(was) if was[p] == now[p] and shapes(before, p) != shapes(after, p)])
    for key, pairs in zip(("bodies_arrived", "bodies_left", "bodies_changed"), moved):
        _capped(details, key, label(pairs))
    return [[f"'{b}'" for _c, b in pairs] for pairs in moved]


def _health_changes(details, design, before):
    """Fill health_after and the new timeline errors and warnings; returns the new errors."""
    marker, count = _common.timeline_marker(design)
    after = None if marker is None else _edit_feature_common.health(design, marker)
    details.update(health_before=before, health_after=after, marker_after=marker,
                   timeline_count_after=count, new_timeline_errors=None,
                   new_timeline_warnings=None)
    if before is None or after is None:
        details["health_unread"] = "the timeline health did not read on both sides of the write"
        return None
    for kind in ("errors", "warnings"):
        details["new_timeline_" + kind] = [n for n in after[kind] if n not in before[kind]]
    return details["new_timeline_errors"]


def _body_sentences(moved):
    """What the body lists say, as note sentences."""
    if moved is None:
        return " The bodies did not read on both sides of the write."
    text = "".join(f" {word}: {_common.named_with_remainder(names)}."
                   for word, names in zip(("Arrived", "Left", "Changed"), moved) if names)
    return text or " The bodies read the same before and after."


def _source_listing(derive_feature):
    """(entities, sorted names) of a derive's current source entities; each None when unread."""
    entities = safe(lambda: list(derive_feature.sourceEntities))
    if entities is None:
        return None, None
    names = [safe(lambda e=e: e.name) for e in entities]
    return entities, None if any(not isinstance(n, str) for n in names) else sorted(names)


def _same_entities(listed, wanted):
    """(TRI-STATE, reason): whether two entity lists hold the same entities by native identity."""
    if listed is None:
        return None, "sourceEntities did not read"
    sides = (("listed", listed), ("requested", wanted))
    keys = {side: [_common.native_identity(e) for e in entities] for side, entities in sides}
    blind = [f"{side} " + _quoted([safe(lambda e=e: e.name) or "(name unreadable)"
                                   for e, key in zip(entities, keys[side]) if key is None])
             for side, entities in sides if None in keys[side]]
    if blind:
        return None, "no identity read for " + " and ".join(blind)
    return Counter(keys["listed"]) == Counter(keys["requested"]), None


def _resolve_in_source(derive_feature, name, wanted):
    """(bodies, names, problem): each wanted name as the ONE root body of the derive's own source."""
    source = safe(lambda: derive_feature.sourceDesign)
    if source is None:
        return None, None, (f"derive '{name}' did not read its sourceDesign, and the active "
                            "design's bodies are not its source. Check the feature with "
                            "design_get(include=['timeline'])")
    bodies = safe(lambda: source.rootComponent.bRepBodies)
    count = _common.counted(lambda: bodies.count)
    if count is None or count > _SOURCE_BODY_CAP:
        return None, None, (f"the root bodies of derive '{name}' sourceDesign read a count of "
                            f"{count} (at most {_SOURCE_BODY_CAP} are read here)")
    rows = [(safe(lambda b=b: b.name), b)
            for b in (safe(lambda i=i: bodies.item(i)) for i in range(count))]
    if any(not isinstance(n, str) for n, _b in rows):
        return None, None, f"a root body of derive '{name}' sourceDesign did not read its name"
    offered = _quoted(sorted(n for n, _b in rows))
    found, names = [], []
    for want in wanted:
        hits = [(n, b) for n, b in rows if n.lower() == want.lower()]
        if len(hits) != 1:
            return None, None, (f"source body '{want}' matches {len(hits)} root bodies in the "
                                f"source design of derive '{name}', and exactly one is needed. "
                                f"The source offers: {offered}")
        names.append(hits[0][0])
        found.append(hits[0][1])
    return found, sorted(names), None


def set_source_entities(design, derive_feature, body_names):
    """Set a DeriveFeature's source entities to named SOURCE root bodies; the reply lists the effect."""
    name = safe(lambda: derive_feature.name) or "(name unreadable)"
    try:
        wanted = list(dict.fromkeys(_as_names(body_names, "body_names")))
    except ValueError as exc:
        return error(str(exc))
    if not wanted:
        return error(f"body_names {body_names!r} names no source body for derive '{name}'. Pass "
                     "the source design's root body names.")
    marker, refusal = _end_marker(design, f"the source entities of derive '{name}' are edited")
    if refusal:
        return refusal
    entities, requested, problem = _resolve_in_source(derive_feature, name, wanted)
    if problem:
        return error(f"Nothing was written: {problem}.")
    listed, was = _source_listing(derive_feature)
    before, _problem = parameter_census(design)
    bodies_before = _body_snapshot(design)
    health_before = _edit_feature_common.health(design, marker)
    details = {"feature": name, "requested": requested, "source_entities_before": was,
               "source_entities_after": was, "marker_before": marker}
    if _same_entities(listed, entities)[0] is True:
        details["edited"] = False
        details["note"] = (f"Derive '{name}' already reads source entities {_quoted(was)}; "
                           "nothing was written.")
        return ok(details)
    if bodies_before is None:
        return _bodies_unread_refusal(name)
    raised = answered = None
    try:
        answered = derive_feature.setSourceEntities(entities, [])       # MUTATION
    except Exception as exc:
        raised = _edit_feature_common.sentence(exc)
    stale = _recompute(design, details)
    listed, now = _source_listing(derive_feature)
    same, unread = _same_entities(listed, entities)
    details.update(source_entities_after=now, answered=answered, source_identity_verified=same)
    if same is None:
        details["source_identity_unread"] = unread
    moved = _body_changes(details, bodies_before, _body_snapshot(design))
    new_errors = _health_changes(details, design, health_before)
    after, _problem = parameter_census(design)
    if before is None or after is None:
        details["parameters_unread"] = "the parameters did not read on both sides of the write"
    else:
        _capped(details, "parameters_appeared", sorted(n for n in after if n not in before))
        _capped(details, "parameters_disappeared", sorted(n for n in before if n not in after))
    details["out_of_date"] = _common.read_flag(
        lambda: derive_feature.documentReference.isOutOfDate)
    if details["out_of_date"] is None:
        details["out_of_date_unread"] = "documentReference.isOutOfDate did not read"
    if raised:
        details["raised"] = raised
    why = (f"Fusion raised: {raised}" if raised
           else f"setSourceEntities answered {answered!r}." if answered is not True
           else "the re-read source entities are not the requested ones." if same is False
           else "their identities did not read, so the result is unverified." if same is None
           else stale if stale
           else "the bodies did not re-read after the recompute." if moved is None
           else f"the timeline has new errors: {_quoted(new_errors)}." if new_errors else None)
    if why:
        return _edit_feature_common.failed(
            f"Setting the source entities of derive '{name}' to {_quoted(requested)} did not "
            f"verify: {why} They read {_quoted(now)} now, and 'details' lists the bodies as "
            "re-read. Read design_get(include=['tree','timeline'], tree_bodies=true) before "
            "retrying.", details)
    details["edited"] = True
    details["note"] = (f"Derive '{name}' now reads source entities {_quoted(now)}. The design "
                       "was recomputed." + _body_sentences(moved)
                       + " Confirm with design_get(include=['tree'], tree_bodies=true).")
    return ok(details)


def _timeline_entry(design, index):
    """(kind, name) of the timeline item at `index`: its entity's objectType suffix and its name."""
    item = safe(lambda: design.timeline.item(index)) if index is not None else None
    return safe(lambda: item.entity.objectType.rsplit("::", 1)[-1]), safe(lambda: item.name)


def _lost_dependents(before, after):
    """One row per parameter that used a parameter gone from `after`, with both expressions."""
    rows = []
    for lost in sorted(n for n in before if n not in after):
        dependents = before[lost]["dependents"]
        if dependents is None:
            rows.append({"depended_on": lost, "name": None,
                         "dependents_unread": "dependentParameters did not read"})
        for dependent in dependents or []:
            now = after.get(dependent)
            row = {"name": dependent, "depended_on": lost, "present_after": now is not None,
                   "expression_before": before.get(dependent, {}).get("expression"),
                   "expression_after": None if now is None else now["expression"]}
            if now is not None and now["expression"] is None:
                row["expression_unread"] = "the expression did not read after the write"
            rows.append(row)
    return rows


def break_link(design, derive_feature):
    """Break a DeriveFeature's link; the reply names what replaced it and what went with the link."""
    name = safe(lambda: derive_feature.name) or "(name unreadable)"
    marker, refusal = _end_marker(design, f"the link of derive '{name}' is broken")
    if refusal:
        return refusal
    index = _common.counted(lambda: derive_feature.timelineObject.index)
    kind, _name = _timeline_entry(design, index)
    if kind != _DERIVE_KIND:
        return error(f"The timeline item of '{name}' at index {index} reads kind {kind!r}, not "
                     f"{_DERIVE_KIND}; nothing was written. Pass a derive feature listed by "
                     "design_get(include=['timeline']).")
    before, problem = parameter_census(design, deep=True)
    if problem:
        return error(f"Nothing was written to derive '{name}': {problem}, so what goes with the "
                     "link could not be judged. Read param_get(include_model_parameters=true).")
    bodies_before = _body_snapshot(design)
    if bodies_before is None:
        return _bodies_unread_refusal(name)
    health_before = _edit_feature_common.health(design, marker)
    details = {"feature": name, "timeline_index": index, "kind_before": kind,
               "marker_before": marker,
               "timeline_count_before": _common.counted(lambda: design.timeline.count)}
    raised = answered = None
    try:
        answered = derive_feature.breakLink()                           # MUTATION
    except Exception as exc:
        raised = _edit_feature_common.sentence(exc)
    stale = _recompute(design, details)
    kind_after, name_after = _timeline_entry(design, index)
    replaced = kind_after is not None and kind_after != _DERIVE_KIND
    details.update(answered=answered, kind_after=kind_after, name_after=name_after,
                   replaced=replaced, same_feature=False if replaced else None)
    moved = _body_changes(details, bodies_before, _body_snapshot(design))
    new_errors = _health_changes(details, design, health_before)
    after, problem = parameter_census(design, deep=True)
    dependents = []
    if after is None:
        details["parameters_unread"] = problem
    else:
        _favorite_changes(details, before, after)
        dependents = _lost_dependents(before, after)
        _capped(details, "dependents_of_disappeared", dependents)
    if raised:
        details["raised"] = raised
    state = (f"The timeline item at index {index} reads kind {kind_after!r}"
             + (f", named '{name_after}'," if name_after else "") + " now")
    why = (f"Fusion raised: {raised}" if raised
           else f"breakLink answered {answered!r}." if answered is not True
           else f"a {_DERIVE_KIND} still reads at its timeline index." if kind_after == _DERIVE_KIND
           else "the item at its timeline index did not re-read a kind." if not replaced
           else stale if stale
           else "the bodies did not re-read after the recompute." if moved is None
           else f"the timeline has new errors: {_quoted(new_errors)}." if new_errors else None)
    if why:
        return _edit_feature_common.failed(
            f"Breaking the link of derive '{name}' did not verify: {why} {state}"
            + ("; the derive was REPLACED and this function cannot restore the link" if replaced
               else "") + ". 'details' lists the bodies and parameters as re-read. Read "
            "design_get(include=['timeline']) and param_get(include_model_parameters=true) "
            "before retrying.", details)
    details["edited"] = True
    note = (f"Derive '{name}' was REPLACED: {state}. This function cannot restore the link. "
            "The design was recomputed." + _body_sentences(moved))
    gone = details.get("parameters_disappeared", [])
    if gone:
        note += " Parameters gone with the link: " + _quoted(gone) + "."
    used = [f"'{r['name']}' (used '{r['depended_on']}')" for r in dependents if r["name"]]
    if used:
        note += (" Their dependents, with expressions before and after in 'details': "
                 + _common.named_with_remainder(used) + ".")
    if after is None:
        note += f" The parameters did not re-read ({problem})."
    details["note"] = note + " Confirm with design_get(include=['timeline'])."
    return ok(details)


def _retained(design, feature, why):
    """The error for a derive whose feature stays in the timeline while `why` holds."""
    feature_name = _common.feature_address(feature) or "(name unreadable)"
    return error(f"Derive feature '{feature_name}' remains, but {why}. "
                 "Inspect design_get(include=['tree','timeline'], tree_bodies=true). "
                 + _common.failed_effect_remedy(design, feature))


def handler(document_id: str = "", into_component: str = "",
            source_components=None, source_bodies=None, exclude_components=None, exclude_bodies=None,
            include_parameters: bool = True, include_favorite_parameters: bool = True,
            place_at_origin: bool = True) -> dict:
    """See TOOL_DESCRIPTION."""
    raw = (document_id or "").strip()
    if not raw:
        return error("Provide 'document_id' - the lineage URN (or web URL) of the saved cloud "
    "document to derive.")

    try:
        comp_names = _as_names(source_components, "source_components")
        body_names = _as_names(source_bodies, "source_bodies")
        excl_comp_names = _as_names(exclude_components, "exclude_components")
        excl_body_names = _as_names(exclude_bodies, "exclude_bodies")
    except ValueError as exc:
        return error(str(exc))

    design = _common.design()
    if not design:
        return error("No active design. Open or create the host document first (see doc_new).")

    good, mode_err = _MODE_GUARD.check(design)
    if not good:
        return mode_err

    into_occ = None
    if (into_component or "").strip():
        into_occ, into_err = _INTO_COMPONENT.resolve(into_component)
        if into_err:
            return error(into_err)
        comp = safe(lambda: into_occ.component)
        if not comp:
            return error(f"Occurrence '{into_component}' has no component to derive into.")
        comp_desc = f"component '{safe(lambda: comp.name)}'"
    else:
        comp = design.rootComponent
        comp_desc = "root component"

    data_file, resolved, candidates = _resolve_data_file(raw)
    if not data_file:
        tried = ", ".join(candidates) if candidates else raw
        return error(f"Could not resolve '{raw}' to a saved document. Tried: {tried}. Pass a "
    "lineage URN or web URL (from data_get). The document must be SAVED to the cloud.")

    # Derive needs the source design LOADED. Fusion opens documents ASYNCHRONOUSLY and this handler
    # holds the main thread until it returns, so a source that is not already open cannot load
    # within the call - createInput returns None on the half-loaded design.
    source_doc = _find_open_document(data_file)
    if source_doc is None:
        return error(f"The source document '{safe(lambda: data_file.name) or resolved}' is not "
                     "open. This tool derives from an ALREADY-OPEN source (Fusion loads documents "
                     "asynchronously - it cannot load one within a single call). Open it first: "
                     f"doc_open(file_id='{resolved}', force_api_open=true), confirm it loaded with "
                     "workspace_orient, then retry - the derive reuses the loaded source.")
    # The source is caller-managed from here on (we never opened it), so a failure below just
    # returns error() and leaves the source document exactly as found.

    source_design = safe(lambda: adsk.fusion.Design.cast(
        source_doc.products.itemByProductType('DesignProductType')))
    if not source_design:
        return error(f"Source document '{safe(lambda: data_file.name) or resolved}' has no Design "
                      "product to derive from (not a Fusion design file?).")

    # Resolve the (optional) named subset in the SOURCE. Empty selectors -> the whole design.
    if comp_names or body_names:
        source_entities, scope_labels, sel_err = _collect_source_entities(
            source_design, comp_names, body_names)
        if sel_err:
            return error(sel_err)
        nested = _sub_component_bodies(source_design, body_names)
        if nested:
            spec, owner = nested[0]
            return error(f"Source body '{spec}' belongs to sub-component '{owner}'; a derive with a "
                         "sub-component body in source_bodies is refused at configure "
                         "('3 : invalid argument entities'). Nothing was derived. Derive its "
                         f"component: source_components=['{owner}'].")
        scope_desc = ", ".join(scope_labels)
    else:
        source_entities = [safe(lambda: source_design.rootComponent)]
        scope_desc = "whole design"
    excluded_entities, _excl_labels, excl_err = _collect_source_entities(
        source_design, excl_comp_names, excl_body_names)
    if excl_err:
        return error(excl_err)
    excl_pairs = _resolve_source_body_pairs(source_design, excl_body_names)[0] or []
    excl_body_rows = [(spec, owner, body)
                      for spec, (owner, body) in zip(excl_body_names, excl_pairs)]

    derive_feats = safe(lambda: comp.features.deriveFeatures)
    if derive_feats is None:
        return error(f"{comp_desc} has no deriveFeatures collection (unexpected).")

    di = safe(lambda: derive_feats.createInput(source_design))
    if di is None:
        return error("deriveFeatures.createInput returned nothing - the source design could not be "
                      "prepared for derive. The source may not be fully loaded yet; confirm it with "
                      "workspace_orient (re-open with doc_open if needed), then retry.")

    try:
        # sourceEntities/excludedEntities take a plain Python list (SWIG std::vector<Ptr<Base>>), NOT
        # an adsk.core.ObjectCollection - an ObjectCollection raises a SWIG type error (live-verified).
        di.sourceEntities = source_entities
        if excluded_entities:
            di.excludedEntities = excluded_entities
        di.isIncludeComponentParameters = bool(include_parameters)
        di.isIncludeFavoriteParameters = bool(include_favorite_parameters)
        di.isPlaceObjectsAtOrigin = bool(place_at_origin)
    except Exception as e:
        return error(f"Could not configure the derive: {e}")

    before_params = _common.counted(lambda: design.userParameters.count)
    # A favourite parameter lands as a DerivedParameter in design.allParameters, outside
    # userParameters, so the imported ones are the new derived names of a design-wide census.
    before_census, _problem = parameter_census(design)
    before_all_params = _common.counted(lambda: design.allParameters.count)
    before_bodies = _body_total(design)
    before_occ_tokens = _occurrence_tokens(comp)
    root = safe(lambda: design.rootComponent)
    # same_component, not `is`: component wrappers are never identity-stable, so `comp is not root`
    # reads True even at the root. The branch is an optimisation only, so an unproven answer takes
    # the walk, which is right whichever component `comp` turns out to be.
    target_is_root = _common.same_component(comp, root)
    before_root_tokens = (before_occ_tokens if target_is_root is True
                          else _occurrence_tokens(root))

    # The platform routes a derive into the ACTIVE component, IGNORING which component's
    # deriveFeatures collection built the input: without activation a derive "into" a non-active
    # component lands as a ROOT sibling. So nesting = activate the target, add, restore.
    prev_active = safe(lambda: design.activeComponent.name)
    active_after = _UNREAD
    if into_occ is not None:
        if not safe(lambda: into_occ.activate(), False):
            return error(f"Could not activate '{into_component}' to receive the derive "
                         "(Occurrence.activate() returned false). Nothing was derived.")
    try:
        try:
            feature = derive_feats.add(di)
        except Exception as e:
            return error(f"Derive failed: {e}.")
    finally:
        if into_occ is not None:
            # activateRootComponent() answers True even when the root is ALREADY active, so its
            # answer cannot separate "came back" from "was already there" - only the
            # activeOccurrence read-back can, and that is what the payload reports.
            safe(lambda: design.activateRootComponent())
            active_after = safe(lambda: design.activeOccurrence, _UNREAD)
    if not feature:
        return error(_common.no_feature_error(design, "Derive",
                                              "(deriveFeatures.add returned nothing.)"))

    # Force a full recompute so world-space reads (bounding box, joint-origin frames) taken right
    # after this call are FRESH - without it a bbox/center can read stale until an unrelated edit
    # recomputes the design. computeAll returns True only that it ran, not that every item is healthy.
    safe(lambda: design.computeAll())

    # --- verify the effect (rung 4: read the landed bodies back, inline: each check gates the return) ---
    health = safe(lambda: feature.healthState)
    if health == _ERROR_HEALTH:
        msg = safe(lambda: feature.errorOrWarningMessage) or "(no message)"
        return error(f"Derive was created but FAILED to compute: {msg}. "
                     + _common.failed_effect_remedy(design, feature))

    doc_ref = safe(lambda: feature.documentReference)
    out_of_date = safe(lambda: doc_ref.isOutOfDate) if doc_ref is not None else None
    if out_of_date:
        return error("Derive was created but its documentReference reads isOutOfDate=true "
                      "immediately at creation - the link did not land against the resolved version. "
                     + _common.failed_effect_remedy(design, feature))

    # A named-body derive can leave feature.bodies empty; its source mapping identifies the result.
    direct_bodies = [{"name": safe(lambda b=b: b.name),
                      "is_derived": safe(lambda b=b: b.isDerived)}
                     for b in _common.result_bodies(feature)]
    if not direct_bodies and body_names and not comp_names and not excl_comp_names:
        direct_bodies, mapping_error = _mapped_bodies(feature, source_entities, excluded_entities, comp)
        reference_id = safe(lambda: doc_ref.dataFile.id)
        source_id = safe(lambda: data_file.id)
        if not mapping_error and (out_of_date is not False or not reference_id or not source_id
                                  or reference_id != source_id):
            mapping_error = "the mapped bodies' current source document reference did not read"
        if mapping_error:
            return _retained(design, feature, mapping_error)
    derived = _new_derived(comp, before_occ_tokens)
    derived_components = _occurrence_rows(derived)
    # `is False` only: the net's error says the nesting FAILED, and run against a target that may
    # itself be the root a successful root derive would trip it. An unproven answer skips the net and
    # DISCLOSES that the landing was not checked.
    landing_note = None
    if not derived_components and target_is_root is None:
        landing_note = ("Whether the derive's target component is this design's root could not be "
                        "read, so the check for a derive that landed at ROOT instead of nested was "
                        "not run - the bodies reported below landed, but WHERE they nested is "
                        "unverified. Confirm with design_get(include=['tree']).")
    if not derived_components and target_is_root is False:
        # Landing net: nothing new in the TARGET component - if the derive surfaced at ROOT
        # instead, the nesting failed and saying so beats a silent root sibling.
        strays = _new_derived_occurrences(root, before_root_tokens)
        if strays:
            names = _names([s.get("name") for s in strays])
            return error(f"Derive landed at the ROOT component ({names}), not in {comp_desc} - "
                         "the target activation did not take, so the nesting failed. Retry after "
                         "removing it, or keep it and move on. "
                         + _common.failed_effect_remedy(design, feature))
    after_bodies = _body_total(design)
    bodies_landed = (None if before_bodies is None or after_bodies is None
                     else max(0, after_bodies - before_bodies))
    any_derived_marker = (any(b["is_derived"] is True for b in direct_bodies) or bool(derived_components))

    if bodies_landed is None and not direct_bodies and not derived_components:
        return error("Derive created a feature, but whether bodies appeared is unknown: a body "
                     "count did not read, and no new derived occurrence appeared. "
                     + _common.failed_effect_remedy(design, feature))
    if bodies_landed == 0 and not direct_bodies and not derived_components:
        return error("Derive created a feature but nothing landed - no bodies appeared and no new "
                      "derived occurrence. The link may not have resolved; check the source scope. "
                     + _common.failed_effect_remedy(design, feature))
    if not any_derived_marker:
        return error("Derive created a feature and geometry appeared, but nothing reports "
                      "isDerived=true - the one-way link may not have formed correctly. "
                     + _common.failed_effect_remedy(design, feature))

    excluded, unverified, excl_error = _excluded_readback(
        feature, derived, safe(lambda: source_design.rootComponent),
        excl_comp_names, excl_body_rows)
    if excl_error:
        return _retained(design, feature, excl_error)

    after_params = _common.counted(lambda: design.userParameters.count)
    user_parameters_added = (None if before_params is None or after_params is None
                             else after_params - before_params)
    imported_names, parameters_unread = imported_parameters(before_census,
                                                            parameter_census(design)[0])
    parameters_imported = None if imported_names is None else len(imported_names)
    after_all_params = _common.counted(lambda: design.allParameters.count)
    model_parameters_added = (None if before_all_params is None or after_all_params is None
                              else after_all_params - before_all_params)
    param_warning = None
    if ((include_parameters or include_favorite_parameters) and parameters_imported == 0
            and not user_parameters_added):
        param_warning = ("include_parameters/include_favorite_parameters was requested and no "
                         "new derived or user parameter reads in the design (the source may "
                         "define none). Source values can land as read-only model parameters - "
                         "read them with param_get(include_model_parameters=true).")

    representative = (derived_components[0]["name"] if derived_components
                      else (direct_bodies[0]["name"] if direct_bodies else None))

    result = {
    "derived": True,
    "feature_name": safe(lambda: feature.name),
    "into_component": comp_desc,
    "scope": scope_desc,
    "document_id": resolved,
    "document_name": safe(lambda: data_file.name),
    "source_version": safe(lambda: data_file.versionNumber),
    "is_parametric": bool(safe(lambda: feature.isParametric, False)),
    "derived_occurrence": representative,
    "derived_components": derived_components,
    "derived_bodies": direct_bodies,
    "bodies_landed": bodies_landed,
    "parameters_imported": parameters_imported,
    "note": ("One-way linked COPY of the source's last SAVED cloud version - unsaved in-session "
            "edits in the source are NOT derived (save the source, then doc_update_xref). Edits made "
            "here (a fillet, a patch, an offset) never travel back to the source, and the source "
            "itself was not modified. Build prep on top of the derived body/bodies."),
    }
    if landing_note:
        result["landing_unverified"] = landing_note
    if imported_names is None:
        result["parameters_unread"] = parameters_unread
    else:
        result["imported_parameter_names"] = imported_names[:_NAMES_CAP]
        if len(imported_names) > _NAMES_CAP:
            result["imported_parameter_names_truncated"] = True
    if user_parameters_added:
        result["user_parameters_added"] = user_parameters_added
    if model_parameters_added is not None:
        # The allParameters count delta, beside parameters_imported (the new DERIVED names): the
        # two count different things. Omitted rather than zeroed when either count was unreadable.
        result["model_parameters_added"] = model_parameters_added
    if excluded:
        result["excluded"] = ", ".join(excluded)
    if unverified:
        result["exclusion_unverified"] = (f"{', '.join(unverified)}; read design_get("
                                          "include=['tree'], tree_bodies=true)")
    if param_warning:
        result["parameter_warning"] = param_warning
    if into_occ is not None:
        if active_after is not _UNREAD:
            result["active_occurrence_after"] = (
                None if active_after is None
                else safe(lambda: active_after.fullPathName) or safe(lambda: active_after.name)
                or "(unnamed occurrence)")
        if active_after is not None:
            reads = ("activeOccurrence did not read" if active_after is _UNREAD
                     else f"activeOccurrence reads {result['active_occurrence_after']!r}")
            result["root_restore_note"] = (
                f"nesting activated {comp_desc} and the restore to root ran, but {reads} - the "
                "return to ROOT is not confirmed. Set the edit target with "
                "design_activate_component(occurrence='root').")
        elif prev_active and prev_active != (safe(lambda: root.name) or ""):
            result["edit_target_note"] = (f"the active edit target was '{prev_active}' before this "
                                          "call and reads ROOT now (nesting activates the target, "
                                          "then returns to root). Re-activate with "
                                          "design_activate_component if needed.")
    return ok(result)


RETURNS = [
    _outputs.ReturnsName("feature_name", of="derive feature", consumers=["design_delete_feature"]),
    _outputs.ReturnsUrn("document_id", consumers=["doc_open", "doc_update_xref"]),
    _outputs.ReturnsName("derived_occurrence", of="derived body or occurrence",
                          consumers=["model_fillet", "joint_create"]),
]


TOOL_DESCRIPTION = (
    "Derive OPEN source's last SAVED cloud version: one-way linked copy. Source/exclude: "
    "component names; body names or Component/Body; no handles.\n"
    + _outputs.produces_block(RETURNS)
)

tool = (
    Tool.create_with_string_input(
        name="doc_insert_derive",
        description=TOOL_DESCRIPTION,
        input_param_name="document_id",
        input_param_description="URN/URL.",
    )
    .add_input_property(*_INTO_COMPONENT.as_property())
    .add_input_property("source_components", {"type": "array", "items": {"type": "string"}})
    .add_input_property("source_bodies", {"type": "array", "items": {"type": "string"}})
    .add_input_property("exclude_components", {"type": "array", "items": {"type": "string"}})
    .add_input_property("exclude_bodies", {"type": "array", "items": {"type": "string"}})
    .add_input_property("include_parameters", {"type": "boolean"})
    .add_input_property("include_favorite_parameters", {"type": "boolean"})
    .add_input_property("place_at_origin", {"type": "boolean"})
    .strict_schema()
)

item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    # The landed occurrences are read off the REQUESTED target component, and a derive that surfaced
    # at root instead is an error naming what it left there.
    verification=Verification(
        kind="inline",
        evidence_test="tests/unit/test_doc_insert_derive.py::TestIntoComponent"
                      "::test_root_stray_landing_is_an_honest_error",
        rung="value"))


def register_tool():
    register(item)
