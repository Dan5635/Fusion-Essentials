# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Typed POSTCONDITION kinds: an Edit tool declares ``postconditions=[...]`` at registration and the
kernel runs capture -> handler -> verify, turning an ok() whose declared effect did not take into an
error. 'hard' fails the call (a capture/verify that RAISES fails CLOSED); 'soft' marks the payload
unconfirmed. A verification read that is merely UNAVAILABLE publishes a could-not-verify marker, so
an evidence key is absent only when the gate ran. capture/verify are safe() READS, never mutations."""

import json

import adsk.core
import adsk.fusion

from ._common import counted, measured, occurrence_world_translation, read_flag, safe

app = adsk.core.Application.get()

MAP_BLURB = ("POSTCONDITION kinds (VersionAdvanced/ReferencesFresh/FileLanded/...) - declare an Edit "
             "tool's verify-the-effect once; wired via Item.create_tool_item(postconditions=[...])")


# How much a verify-the-effect read proves, weakest first: a COUNT of things, that the effect
# EXISTS, the right VALUE read back, or the right GEOMETRY changed. A kind declares its rung; the
# declaration lint holds each write verb to a minimum.
RUNGS = ("count", "exists", "value", "geometry")


class Postcondition:
    """One declared 'this must be true after the mutation' - subclasses implement capture()/verify()."""

    name = "postcondition"
    severity = "hard"
    rung = "exists"
    input_keys = ()        # handler PARAMETER names this kind reads; wrap() checks them
    read_tool = None       # the MCP read that re-reads this ground truth, named in a failed verify

    def capture(self, kwargs):
        """Ground truth BEFORE the handler runs, handed back to verify()."""
        return None

    def verify(self, kwargs, payload, before):
        """(reason, evidence) after an ok(): '' confirms, a reason names the contradicting fact."""
        return "", {}

    def describe(self) -> str:
        """One line for generated docs / the lint inventory."""
        return self.name


class VersionAdvanced(Postcondition):
    """After a save: local completion and fresh cloud version advancement are reported separately."""

    name = "version_advanced"
    rung = "value"
    read_tool = "doc_get"

    _DEADLINE_S = 8.0
    _POLL_SLEEP = 0.5

    def capture(self, kwargs):
        from . import _doc_common
        doc = safe(lambda: app.activeDocument)
        lineage = safe(lambda: doc.dataFile.id) if doc is not None else None
        return {
            "was_modified": safe(lambda: doc.isModified) if doc is not None else None,
            "lineage": lineage,
            "version": _doc_common.fresh_version_read(app, lineage),
        }

    def verify(self, kwargs, payload, before):
        if payload.get("already_current"):
            return "", {}                    # clean-doc no-op: nothing was supposed to change
        from . import _doc_common
        doc = safe(lambda: app.activeDocument)
        still = safe(lambda: doc.isModified) if doc is not None else None
        before_version = before.get("version") if isinstance(before, dict) else None
        lineage_after = safe(lambda: doc.dataFile.id) if doc is not None else None
        if still is None:
            local_confirmed = False
        elif still:
            fresh = _doc_common.fresh_version_read(app, lineage_after)
            landed = _doc_common._version_advanced(before_version, fresh)
            tip = fresh.get("latest_version_number") or fresh.get("version_number")
            cloud = (f"A fresh read shows cloud version {tip} landed." if landed
                     else "A fresh read shows no new cloud version." if landed is False
                     else "Whether a cloud version landed is unknown: the fresh version reads were "
                          "not comparable.")
            return ("save reported success but the active document is STILL modified - local save "
                    f"completion was not confirmed. {cloud} Close any referencing or duplicate "
                    "document, reopen this one top-level, then inspect doc_get/data_get before "
                    "saving again."), {}
        else:
            local_confirmed = True

        evidence = {"local_save_confirmed": local_confirmed}
        # doc_save_milestone already performs the same bounded fresh comparison in its handler.
        if "cloud_tip_advanced" in payload:
            confirmed = payload.get("cloud_tip_advanced") is True
            evidence["version_confirmed"] = confirmed
            if not confirmed:
                evidence["pending"] = True
            return "", evidence

        verdict, after = _doc_common.wait_for_version_advance(
            app, lineage_after, before_version, self._DEADLINE_S, self._POLL_SLEEP)
        evidence.update({
            "version_confirmed": verdict is True,
            "cloud_tip_advanced": verdict is True,
            "version_id_before": before_version.get("version_id")
            if isinstance(before_version, dict) else None,
            "version_id_after": after.get("version_id"),
            "version_before": before_version.get("version_number")
            if isinstance(before_version, dict) else None,
            "version_after": after.get("version_number"),
            "latest_version_before": before_version.get("latest_version_number")
            if isinstance(before_version, dict) else None,
            "latest_version_after": after.get("latest_version_number"),
        })
        if verdict is not True:
            evidence["pending"] = True
            held = before.get("lineage") if isinstance(before, dict) else None
            if verdict is None and _doc_common._lineage_moved(held, lineage_after):
                evidence["version_status"] = (
                    f"The document's lineage read {held} before the save and {lineage_after} "
                    "after it. version_before was read on the first and version_after on the "
                    "second, so the two numbers are not compared and no advance is reported. "
                    + ("" if after.get("data_file") is not None else
                       "A fresh lookup of the second did not return a file in this call. ")
                    + f"Read data_get(file='{lineage_after}').")
            else:
                evidence["version_status"] = (
                    "Cloud version advancement was not observed in fresh comparable reads. Re-read "
                    "data_get for the document_id." if verdict is False else
                    "Cloud version advancement is unknown because fresh before/after lineage/version "
                    "reads were not comparable. Re-read data_get for the document_id.")
        return "", evidence


# The refresh settles asynchronously and only advances while the main thread runs, so the re-read is
# a clock-bounded doEvents pump rather than a single sample.
_REFERENCE_SETTLE_S = 8.0
_REFERENCE_SETTLE_POLL_SLEEP = 0.25


class ReferencesFresh(Postcondition):
    """After a reference refresh: no DocumentReference is still out of date after a settle wait."""

    name = "references_fresh"
    rung = "value"
    read_tool = "doc_get"
    # DrawingDocument.isUpToDate reads True while a reference is stale, so the per-reference
    # isOutOfDate walk below is the gate instead.

    def _stale_state(self):
        """Return (known stale count, complete walk)."""
        refs = safe(lambda: app.activeDocument.documentReferences)
        if refs is None:
            return 0, False
        count = counted(lambda: refs.count)
        if count is None:
            return 0, False
        stale, complete = 0, True
        for i in range(count):
            ref = safe(lambda k=i: refs.item(k))
            if ref is None:
                complete = False
                continue
            is_stale = read_flag(lambda ref=ref: ref.isOutOfDate)
            if is_stale is None:
                complete = False
            elif is_stale:
                stale += 1
        return stale, complete

    def capture(self, kwargs):
        return self._stale_state()

    def verify(self, kwargs, payload, before):
        from . import _export

        def probe():
            state = self._stale_state()
            return state[0] == 0, state

        _settled, state = _export.pump_until(probe, _REFERENCE_SETTLE_S,
                                             _REFERENCE_SETTLE_POLL_SLEEP)
        stale, complete = state
        if stale:
            if complete:
                reason = f"{stale} reference(s) are STILL out of date"
            else:
                reason = f"at least {stale} known reference(s) are STILL out of date"
            return (f"refresh ran but {reason} - the references did not fully update. The refresh "
                    f"was given {_REFERENCE_SETTLE_S:g}s to settle."), {}
        if not complete:
            return "", {"references_confirmed": False}
        return "", {"stale_references_after": 0}


class FileLanded(Postcondition):
    """After an export: a non-empty file EXISTS at the payload's path key (proving THIS call wrote it
    needs the pre-write state, which only the handler holds)."""

    name = "file_landed"
    rung = "value"

    def __init__(self, key="file_path"):
        self.key = key

    def verify(self, kwargs, payload, before):
        path = payload.get(self.key)
        if not path:
            return f"no '{self.key}' in the result to verify a written file against.", {}
        from . import _export
        size, verr = _export.verify_written(path)
        if verr:
            return (f"the tool reported success but {verr}. The API returned true but produced "
                    "nothing on disk."), {}
        return "", {"file_exists": True, "size_bytes": size}

    def describe(self) -> str:
        return f"{self.name}({self.key})"


class DeliverablesExist(Postcondition):
    """Every file an export payload CLAIMS - each 'files' entry by its path_key, or a single
    'file_path' - exists non-empty on disk; claiming neither key, or an EMPTY list, fails."""

    name = "deliverables_exist"
    rung = "value"

    def __init__(self, list_key="files", path_key="file_path", single_key="file_path"):
        self.list_key = list_key
        self.path_key = path_key
        self.single_key = single_key

    def verify(self, kwargs, payload, before):
        from . import _export
        paths = []
        entries = payload.get(self.list_key)
        if isinstance(entries, list) and entries:
            for i, it in enumerate(entries):
                p = it.get(self.path_key) if isinstance(it, dict) else None
                if not p:
                    return (f"'{self.list_key}[{i}]' claims a deliverable but carries no "
                            f"'{self.path_key}' to verify."), {}
                paths.append(p)
        elif payload.get(self.single_key):
            paths.append(payload[self.single_key])
        else:
            state = "an EMPTY list" if isinstance(entries, list) else "absent"
            return (f"the result claims success but names no deliverable to verify on disk "
                    f"('{self.list_key}' is {state}, no '{self.single_key}')."), {}
        for p in paths:
            _size, verr = _export.verify_written(p)
            if verr:
                return f"claimed deliverable '{p}': {verr}.", {}
        return "", {"deliverables_verified": len(paths)}

    def describe(self) -> str:
        return f"{self.name}({self.list_key}|{self.single_key})"


# errorOrWarningMessage joins its sentences with this marker and repeats the whole run.
_COMPUTE_FAILED_MARKER = "Compute Failed"
_MESSAGE_LIMIT = 240


def compute_failure_message(raw, limit=_MESSAGE_LIMIT):
    """The one readable sentence of a Fusion compute failure: the text before the first 'Compute
    Failed' marker, whitespace-collapsed and bounded, a cut marked with a trailing ' ...'."""
    text = " ".join((raw or "").split(_COMPUTE_FAILED_MARKER)[0].split())
    if len(text) > limit:
        return text[:limit].rstrip() + " ..."
    return text


def compute_failure(entity):
    """('error' | 'warning', condensed message) when `entity` carries a FAILED compute state, else
    None - the STATE is read, never the message text."""
    # errorOrWarningMessage RAISES on some healthy items, so it is read only on the unhealthy branch.
    if entity is None:
        return None
    states = adsk.fusion.FeatureHealthStates
    hs = safe(lambda: entity.healthState)
    if hs is None:
        return None
    if hs == safe(lambda: states.ErrorFeatureHealthState):
        label = "error"
    elif hs == safe(lambda: states.WarningFeatureHealthState):
        label = "warning"
    else:
        return None
    return label, compute_failure_message(safe(lambda: entity.errorOrWarningMessage))


def health_state_read(entity):
    """True when `entity` ANSWERED a compute state - what tells compute_failure's 'not flagged' None
    apart from its 'carries no healthState' None."""
    return entity is not None and safe(lambda: entity.healthState) is not None


def compute_state(entity):
    """('broken' | 'healthy' | 'unknown', the compute_failure pair or None) for ONE entity: the
    entity and its timelineObject are asked, entity first, and 'unknown' means neither answered."""
    # An AsBuiltJoint or RigidGroup raises on healthState while its TimelineObject answers.
    sources = (entity, safe(lambda: entity.timelineObject))
    for src in sources:
        failure = compute_failure(src)
        if failure is not None:
            return "broken", failure
    if any(health_state_read(src) for src in sources):
        return "healthy", None
    return "unknown", None


class FeatureHealthy(Postcondition):
    """After a feature-creating Edit: every timeline item added between capture and verify computed
    cleanly. No timeline or no added item is skipped; a WARNING is folded as evidence."""

    name = "feature_healthy"
    rung = "exists"
    read_tool = "design_get"

    def _timeline(self):
        from ._common import design
        d = design()
        return safe(lambda: d.timeline) if d else None

    def capture(self, kwargs):
        tl = self._timeline()
        return safe(lambda: tl.count) if tl is not None else None

    def verify(self, kwargs, payload, before):
        tl = self._timeline()
        count = safe(lambda: tl.count) if tl is not None else None
        if tl is None or before is None or count is None:
            # A direct-modelling design legitimately has no timeline, so this discloses, not fails.
            return "", {"feature_health_confirmed": False}
        if count <= before:
            return "", {}                    # nothing new on the timeline - nothing to gate
        warnings = []
        for i in range(before, count):
            item = safe(lambda k=i: tl.item(k))
            if item is None:
                continue
            nm = safe(lambda: item.name) or "the created feature"
            failure = compute_failure(item)
            if failure is None:
                continue
            label, msg = failure
            if label == "error":
                return ((f"'{nm}' was created but FAILED to compute. " + msg).strip()
                        + " It remains in the timeline - fix its inputs or remove it with "
                          "design_delete_feature. Not measured whether later items this call "
                          "added computed; re-read with design_get(include=['timeline'])."), {}
            warnings.append((nm + ": " + msg).strip().rstrip(":"))
        evidence = {"features_verified": count - before}
        if warnings:
            evidence["feature_warnings"] = warnings
        return "", evidence


def _xyz(point):
    """(x, y, z) in cm, rounded - or None when any component is unreadable (never a zero corner)."""
    out = []
    for axis in ("x", "y", "z"):
        v = safe(lambda axis=axis: getattr(point, axis))
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        out.append(round(float(v), 7))
    return tuple(out)


def entity_position(entity):
    """A position fingerprint for ONE sketch entity - bbox corners in cm PLUS start/end sketch-point
    coordinates, which break the tie a bbox misses on a 180-degree rotation about the midpoint."""
    marks = []
    bb = safe(lambda: entity.boundingBox)
    for get_pt in (lambda: bb.minPoint, lambda: bb.maxPoint):
        p = safe(get_pt) if bb is not None else None
        marks.append(_xyz(p) if p is not None else None)
    for get_pt in (lambda: entity.startSketchPoint.geometry,
                   lambda: entity.endSketchPoint.geometry,
                   lambda: entity.geometry):
        # a curve carries start/end; a SketchPoint carries only .geometry; a circle/ellipse neither
        p = safe(get_pt)
        marks.append(_xyz(p) if p is not None else None)
    return tuple(marks) if any(m is not None for m in marks) else None


class SketchCurvesChanged(Postcondition):
    """After a sketch edit: the target sketch's curves AND points differ, keyed entityToken ->
    (length in cm, position). ``keys`` names the sketch kwargs in priority order, and ``scope_keys``
    pairs each POSITIONALLY with the handler's component-scope kwarg for the same reference."""

    name = "sketch_curves_changed"
    rung = "geometry"
    read_tool = "sketch_get"

    def __init__(self, keys=("sketch_name",), scope_keys=()):
        self.keys = tuple(keys)
        self.scope_keys = tuple(scope_keys)
        self.input_keys = self.keys + tuple(k for k in self.scope_keys if k)

    def _fingerprint(self, kwargs):
        from ._common import design
        from ._sketch_detail import scoped_or_recent_sketch
        d = design()
        if d is None:
            return None
        wanted, scope = "", ""
        for i, key in enumerate(self.keys):
            # A blank name means "the most recent sketch", and its paired scope decides whose.
            wanted = (kwargs.get(key) or "").strip()
            scope = ((kwargs.get(self.scope_keys[i]) or "").strip()
                     if i < len(self.scope_keys) and self.scope_keys[i] else "")
            if wanted:
                break
        sketch, _requested, _refusal = scoped_or_recent_sketch(d, wanted, scope)
        if sketch is None:
            return None
        marks = {}
        curves = safe(lambda: sketch.sketchCurves)
        n = (safe(lambda: curves.count, 0) or 0) if curves is not None else 0
        for i in range(n):
            c = safe(lambda i=i: curves.item(i))
            if c is None:
                continue
            marks[("curve", safe(lambda c=c: c.entityToken) or f"#{i}")] = (
                measured(lambda c=c: c.length, 1.0, 7), entity_position(c))
        points = safe(lambda: sketch.sketchPoints)
        m = (safe(lambda: points.count, 0) or 0) if points is not None else 0
        for i in range(m):
            p = safe(lambda i=i: points.item(i))
            if p is None:
                continue
            # a SketchPoint carries no .length, so position is its whole fingerprint
            marks[("point", safe(lambda p=p: p.entityToken) or f"#{i}")] = (None, entity_position(p))
        return {"marks": marks, "curves": n}

    def describe(self) -> str:
        return f"{self.name}({'|'.join(self.keys)})"

    def capture(self, kwargs):
        return self._fingerprint(kwargs)

    def verify(self, kwargs, payload, before):
        after = self._fingerprint(kwargs)
        if before is None or after is None:
            return "", {"sketch_curves_confirmed": False}
        if after["marks"] == before["marks"]:
            return ("the edit reported success but the sketch's entities are unchanged - nothing was "
                    "added, removed, shortened, lengthened or moved."), {}
        return "", {"curve_count_after": after["curves"]}


class ChildGeometryMoved(Postcondition):
    """After a joint mutation: a part whose transform TRANSLATED carried its deepest nested body
    geometry with it. The flag is null - no verdict - when nothing was repositioned, and
    'repositioned_occurrences' names the parts that did move."""

    name = "child_geometry_moved"
    rung = "geometry"
    read_tool = "find_geometry"

    _MOVE_TOL_CM = 0.01                   # 0.1 mm - below this a "move" is joint-solver noise

    def _translation(self, occ):
        """A placed occurrence's world translation in cm, or None."""
        point = occurrence_world_translation(occ)
        return tuple(point.values()) if point is not None else None

    def _deep_body_point(self, occ):
        """A WORLD-space bbox-min corner of a body on occ's DEEPEST descendant occurrence that owns
        one, else occ's own first body; None when no body is reachable."""
        best, best_depth = None, -1
        stack = [(occ, 0)]
        while stack:
            cur, depth = stack.pop()
            bodies = safe(lambda cur=cur: cur.bRepBodies)
            bcount = (safe(lambda: bodies.count, 0) or 0) if bodies is not None else 0
            if bcount and depth > best_depth:
                best, best_depth = cur, depth
            children = safe(lambda cur=cur: cur.childOccurrences)
            ccount = (safe(lambda: children.count, 0) or 0) if children is not None else 0
            for i in range(ccount):
                ch = safe(lambda i=i, children=children: children.item(i))
                if ch is not None:
                    stack.append((ch, depth + 1))
        if best is None:
            return None
        body = safe(lambda: best.bRepBodies.item(0))
        bb = safe(lambda: body.boundingBox) if body is not None else None
        mn = safe(lambda: bb.minPoint) if bb is not None else None
        if mn is None:
            return None
        return (safe(lambda: mn.x, 0.0) or 0.0, safe(lambda: mn.y, 0.0) or 0.0,
                safe(lambda: mn.z, 0.0) or 0.0)

    def _top_occurrences(self):
        """The root's top-level occurrences, or None when the walk itself could not be read."""
        from ._common import design
        d = design()
        root = safe(lambda: d.rootComponent) if d else None
        occs = safe(lambda: root.occurrences) if root is not None else None
        if occs is None:
            return None
        n = safe(lambda: occs.count, 0) or 0
        return [safe(lambda i=i: occs.item(i)) for i in range(n)]

    @staticmethod
    def _dist(a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5

    def capture(self, kwargs):
        occs = self._top_occurrences()
        if occs is None:
            return None                       # the walk failed - verify has no baseline to compare
        entries = []
        for occ in occs:
            if occ is None:
                continue
            tr = self._translation(occ)
            pt = self._deep_body_point(occ)
            if pt is None:
                continue
            entries.append((occ, tr, pt))
        return entries

    def verify(self, kwargs, payload, before):
        if before is None:
            return "", {"child_geometry_move_verified": False}
        if not before:
            return "", {}                     # no occurrence carried a body to gate
        tol = self._MOVE_TOL_CM
        unverified = []
        repositioned = []
        for occ, tr0, pt0 in before:
            tr1 = self._translation(occ)
            pt1 = self._deep_body_point(occ)
            if tr0 is None or tr1 is None or pt1 is None:
                unverified.append(safe(lambda occ=occ: occ.name) or "an unnamed occurrence")
                continue
            parent_moved = self._dist(tr0, tr1)
            child_moved = self._dist(pt0, pt1)
            if parent_moved > tol:
                repositioned.append(safe(lambda occ=occ: occ.name) or "an unnamed occurrence")
            if parent_moved > tol and child_moved <= tol:
                nm = safe(lambda: occ.name) or "a repositioned part"
                return (f"the joint reported success and repositioned '{nm}' by "
                        f"{round(parent_moved * 10.0, 3)} mm (its transform moved) but its nested body "
                        "geometry did NOT move - the reposition did not propagate into the nested "
                        "occurrence. The joint REMAINS in the timeline: delete it, LOCK every "
                        "nested free occurrence (assembly_ground each ground_to_parent=true, "
                        "deepest included), joint the WRAPPER, then recompute."), {}
        if unverified:
            # The flag reports whether the CHECK ran, not whether a part moved.
            return "", {"child_geometry_move_verified": False,
                        "child_geometry_unverified": unverified}
        if not repositioned:
            # Nothing moved, so there is no verdict to give - null, not True.
            return "", {"child_geometry_move_verified": None, "repositioned_occurrences": []}
        return "", {"child_geometry_move_verified": True,
                    "repositioned_occurrences": repositioned}


# ── the design-wide body census the surface and pattern kinds read ─────────────────────────────

# Above these sizes the census is not taken: a verify must never park a write behind a walk of
# every edge in a large assembly (one faces.count read per edge) or every body's area.
_CENSUS_EDGE_CAP = 20000
_CENSUS_BODY_CAP = 2000
_AREA_TOL_CM2 = 1e-6
_PLACE_TOL_CM = 1e-4
_ELEMENT_CAP = 400
# The rotation cells of a row-major 4x4 and the cell difference two orientations may read apart by
# and still count as one: adjacent copies of a 400-instance ring differ by 1.6e-2.
_ROTATION_CELLS = (0, 1, 2, 4, 5, 6, 8, 9, 10)
_TURN_TOL = 1e-6


def census_bodies():
    """Every native BRep body in every component of the active design, or None when a component's
    body collection did not read."""
    from ._common import design, all_components, iter_collection
    d = design()
    if d is None:
        return None
    bodies = []
    for comp in all_components(d):
        coll = safe(lambda comp=comp: comp.bRepBodies)
        if coll is None:
            return None
        bodies.extend(b for b in iter_collection(coll) if b is not None)
    return bodies


def free_edge_count(bodies):
    """How many edges across `bodies` bound exactly ONE face - a surface's open boundary - or None
    when the walk passes _CENSUS_EDGE_CAP or an edge's face count did not read."""
    from ._common import counted
    total, free = 0, 0
    for b in bodies:
        edges = safe(lambda b=b: b.edges)
        n = counted(lambda: edges.count) if edges is not None else None
        if n is None:
            return None
        total += n
        if total > _CENSUS_EDGE_CAP:
            return None
        for i in range(n):
            faces = counted(lambda i=i: edges.item(i).faces.count)
            if faces is None:
                return None
            if faces == 1:
                free += 1
    return free


def total_area(bodies):
    """(sum of body areas in cm2, how many bodies' area did not read), or None over the body cap."""
    if len(bodies) > _CENSUS_BODY_CAP:
        return None
    total, unread = 0.0, 0
    for b in bodies:
        a = measured(lambda b=b: b.area, 1.0, 9)
        if a is None:
            unread += 1
        else:
            total += a
    return total, unread


_NOT_MEASURED_CONSUMED = " Not measured whether its input bodies were consumed."


class FreeEdgesChanged(Postcondition):
    """After a stitch or unstitch: the design's FREE-edge count moved the declared way - 'sealed'
    drops it (edge pairs joined), 'opened' raises it (faces set loose)."""

    name = "free_edges_changed"
    rung = "geometry"
    read_tool = "model_inspect"

    def __init__(self, direction):
        if direction not in ("sealed", "opened"):
            raise ValueError(f"direction must be 'sealed' or 'opened', got {direction!r}")
        self.direction = direction

    def describe(self) -> str:
        return f"{self.name}({self.direction})"

    def capture(self, kwargs):
        bodies = census_bodies()
        return {"free": free_edge_count(bodies) if bodies is not None else None,
                "timeline": _timeline_count()}

    def verify(self, kwargs, payload, before):
        since = before.get("timeline") if isinstance(before, dict) else None
        before = before.get("free") if isinstance(before, dict) else None
        bodies = census_bodies()
        after = free_edge_count(bodies) if bodies is not None else None
        if before is None or after is None:
            return "", {"free_edges_confirmed": False}
        if self.direction == "sealed":
            if before == 0:
                # A stitch takes open surfaces, which carry free edges; a census holding none did
                # not reach the inputs, so it cannot convict.
                return "", {"free_edges_confirmed": False}
            if after >= before:
                return (f"the stitch reported success but the design's free-edge count did not drop "
                        f"({before} before, {after} after) - no edge pair was sealed."
                        + _NOT_MEASURED_CONSUMED + _left_by(payload, always=True, since=since)), {}
        elif after <= before:
            return (f"the unstitch reported success but the design's free-edge count did not rise "
                    f"({before} before, {after} after) - no face was set loose."
                    + _NOT_MEASURED_CONSUMED + _left_by(payload, always=True, since=since)), {}
        return "", {"free_edges_before": before, "free_edges_after": after}


class SurfaceAreaAdded(Postcondition):
    """Verify that total body surface area increased beyond the area threshold."""

    name = "surface_area_added"
    rung = "geometry"
    read_tool = "model_inspect"

    def capture(self, kwargs):
        bodies = census_bodies()
        return {"area": total_area(bodies) if bodies is not None else None,
                "timeline": _timeline_count()}

    def verify(self, kwargs, payload, before):
        since = before.get("timeline") if isinstance(before, dict) else None
        before = before.get("area") if isinstance(before, dict) else None
        bodies = census_bodies()
        after = total_area(bodies) if bodies is not None else None
        if before is None or after is None:
            return "", {"surface_area_confirmed": False}
        delta = after[0] - before[0]
        if delta > _AREA_TOL_CM2:
            return "", {"area_added_cm2": round(delta, 6)}
        if before[1] or after[1]:
            return "", {"surface_area_confirmed": False}
        return (f"the surface was reported created, but total body surface area changed by "
                f"{delta:.12g} cm2; verification requires an increase above {_AREA_TOL_CM2:g} cm2."
                + _left_by(payload, since=since)), {
                    "area_change_cm2": delta, "area_increase_threshold_cm2": _AREA_TOL_CM2}


def _timeline_count():
    """The active design's timeline count, or None when it does not read (DIRECT mode raises)."""
    from ._common import design
    d = design()
    tl = safe(lambda: d.timeline) if d is not None else None
    return safe(lambda: tl.count) if tl is not None else None


def _added_address(name, since):
    """The address of the ONE timeline item named `name` added at index `since` or later, else None."""
    from ._common import design
    from ._inputs import candidate_address
    d = design()
    tl = safe(lambda: d.timeline) if d is not None else None
    count = safe(lambda: tl.count) if tl is not None else None
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (since, count)):
        return None
    items = [safe(lambda k=k: tl.item(k)) for k in range(since, count)]
    hits = [o for o in items if o is not None and (safe(lambda o=o: o.name) or "").strip() == name]
    return candidate_address(hits[0]) if len(hits) == 1 else None


def _left_by(payload, always=False, since=None):
    """The removal clause for the payload's feature and bodies ('' with none, unless `always`)."""
    from ._common import design, left_in_timeline
    feature = payload.get("feature") or payload.get("form")
    if not isinstance(feature, str) or not feature:
        return " " + left_in_timeline(design(), None) if always else ""
    bodies = [b for b in payload.get("result_bodies") or () if isinstance(b, str)]
    added = (" Its result bodies: " + ", ".join(f"'{b}'" for b in bodies) + "." if bodies else "")
    address = _added_address(feature.strip(), since) or feature
    return added + " " + left_in_timeline(design(), address)


class PatternElementsPlaced(Postcondition):
    """After a pattern: the copies sit at DISTINCT places. With ``spacings`` ((quantity key,
    spacing key, quantity default, spacing default) per grid direction, direction one innermost)
    the read is the element transforms, the first instance one spacing from the seed; without
    them it is the result bodies' boxes, or a bodiless pattern's element occurrence poses."""

    # A circular element's transform is NOT its placement (a 4 x 360 deg ring reads 0/180/270/0 deg
    # while its bodies sit at 0/90/180/270, the seed LAST in feature.bodies), so a ring is read by
    # its boxes - and softly, since a symmetric body on its own axis patterns onto itself.

    name = "pattern_elements_placed"
    rung = "geometry"
    read_tool = "design_get"

    def __init__(self, spacings=(), units_key="units", severity="hard"):
        self.spacings = tuple(spacings)
        self.units_key = units_key
        self.severity = severity
        keys = [k for spec in self.spacings for k in spec[:2]]
        self.input_keys = tuple(keys + ([units_key] if self.spacings else []))

    def describe(self) -> str:
        return f"{self.name}({'|'.join(s[1] for s in self.spacings) or 'bodies'})"

    def _timeline(self):
        from ._common import design
        d = design()
        return safe(lambda: d.timeline) if d else None

    def capture(self, kwargs):
        tl = self._timeline()
        return safe(lambda: tl.count) if tl is not None else None

    def _feature(self, payload, before):
        """The timeline entity added by this call under the payload's feature name, or None."""
        tl = self._timeline()
        count = safe(lambda: tl.count) if tl is not None else None
        name = payload.get("feature")
        if tl is None or before is None or count is None or not name:
            return None
        for i in range(before, count):
            item = safe(lambda k=i: tl.item(k))
            if item is not None and safe(lambda: item.name) == name:
                return safe(lambda: item.entity)
        return None

    @staticmethod
    def _transforms(feature):
        """[(the 16 matrix values, translation)] per element, or None when any did not read."""
        from ._common import counted
        els = safe(lambda: feature.patternElements)
        n = counted(lambda: els.count) if els is not None else None
        if n is None or n > _ELEMENT_CAP:
            return None
        out = []
        for i in range(n):
            m = safe(lambda k=i: els.item(k).transform)
            arr = safe(lambda: m.asArray()) if m is not None else None
            tr = _xyz(safe(lambda: m.translation)) if m is not None else None
            if arr is None or tr is None:
                return None
            out.append((tuple(round(float(v), 6) for v in arr), tr))
        return out

    @staticmethod
    def _body_boxes(feature):
        """[(min corner + max corner, min corner)] per result body, or None when the feature owns
        no body (an occurrence pattern) or a box did not read."""
        from ._common import result_bodies
        bodies = result_bodies(feature)
        if not bodies or len(bodies) > _ELEMENT_CAP:
            return None
        out = []
        for b in bodies:
            bb = safe(lambda b=b: b.boundingBox)
            lo = _xyz(safe(lambda: bb.minPoint)) if bb is not None else None
            hi = _xyz(safe(lambda: bb.maxPoint)) if bb is not None else None
            if lo is None or hi is None:
                return None
            out.append((lo + hi, lo))
        return out

    @staticmethod
    def _occurrence_poses(feature):
        """[[16 transform2 values per occurrence] per element], or None when any did not read."""
        from ._common import finite_number
        els = safe(lambda: feature.patternElements)
        n = counted(lambda: els.count) if els is not None else None
        if not n or n > _ELEMENT_CAP:
            return None
        out = []
        for i in range(n):
            # An element's occurrences are an OccurrenceVector: it iterates and carries no count.
            occs = safe(lambda k=i: list(els.item(k).occurrences))
            if not occs or (out and len(occs) != len(out[0])):
                return None
            poses = []
            for o in occs:
                arr = safe(lambda o=o: [finite_number(v) for v in o.transform2.asArray()])
                if arr is None or len(arr) != 16 or None in arr:
                    return None
                poses.append(arr)
            out.append(poses)
        return out

    @staticmethod
    def _one_pose(a, b):
        """Whether two poses read one position (within _PLACE_TOL_CM) and one orientation."""
        moved = ChildGeometryMoved._dist((a[3], a[7], a[11]), (b[3], b[7], b[11]))
        return moved <= _PLACE_TOL_CM and all(abs(a[k] - b[k]) <= _TURN_TOL
                                              for k in _ROTATION_CELLS)

    def _occurrences_placed(self, feature, quantity):
        """Count pairwise-distinct occurrence poses for bodiless patterns, else return unconfirmed."""
        # A circular element's own transform reads a zero translation, so it is never the read.
        unknown = {"pattern_elements_confirmed": False}
        placed = self._occurrence_poses(feature)
        if placed is None:
            return unknown
        if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity != len(placed):
            return unknown
        for i, poses in enumerate(placed):
            if any(all(self._one_pose(a, b) for a, b in zip(poses, other))
                   for other in placed[:i]):
                return unknown
        return {"elements_placed": len(placed)}

    def _spacing_miss(self, kwargs, placed):
        """The clause naming the first direction whose landed step is not the requested spacing."""
        from ._common import scale
        k = scale(kwargs.get(self.units_key) or "mm")
        if not k:
            return ""
        stride = 1
        for qkey, skey, qdef, sdef in self.spacings:
            quantity = int(kwargs.get(qkey) if kwargs.get(qkey) is not None else qdef)
            spacing = abs(float(kwargs.get(skey) if kwargs.get(skey) is not None else sdef)) * k
            if quantity > 1 and stride < len(placed):
                landed = ChildGeometryMoved._dist(placed[0][1], placed[stride][1])
                if abs(landed - spacing) > _PLACE_TOL_CM:
                    return (f"the first instance along '{skey}' landed {round(landed * 10.0, 4)} mm "
                            f"from the seed, not the requested {round(spacing * 10.0, 4)} mm")
            stride *= max(1, quantity)
        return ""

    def verify(self, kwargs, payload, before):
        if payload.get("entity_kind") in ("features", "faces"):
            return "", {"pattern_elements_confirmed": False}
        feature = self._feature(payload, before)
        if feature is None:
            placed = None
        elif self.spacings:
            placed = self._transforms(feature)
        else:
            from ._common import result_bodies
            placed = self._body_boxes(feature)
            if placed is None and not result_bodies(feature):
                return "", self._occurrences_placed(feature, payload.get("quantity"))
        if placed is None:
            return "", {"pattern_elements_confirmed": False}
        seen = {}
        remedy = (" The feature is left in the timeline for inspection - design_delete_feature "
                  "removes it.")
        what = "one transform" if self.spacings else "one bounding box"
        for i, (key, _tr) in enumerate(placed):
            if key in seen:
                return (f"the pattern reported {len(placed)} instances but copies {seen[key]} and "
                        f"{i} share {what} - the copies are STACKED on each other." + remedy), {}
            seen[key] = i
        miss = self._spacing_miss(kwargs, placed)
        if miss:
            return miss + "." + remedy, {}
        return "", {"elements_placed": len(placed)}


def _verification_failed(post, ex, payload=None):
    """Return a hard capture refusal or an unverified post-write error with reported identities."""
    detail = str(ex)[:160]
    tool = getattr(post, "read_tool", None)
    reread = (f"Re-read with {tool} and retry only if the change did not take."
              if tool else "Re-read the affected state and retry only if the change did not take.")
    body = {"postcondition": post.name, "verification_error": detail}
    if payload is None:
        body.update(handler_not_run=True,
                    note="The required baseline could not be read; this tool's handler was not run. "
                         "Inspect the affected state before retrying.")
        message = f"{post.name}: baseline capture failed; handler not run - {detail}"
    else:
        body.update(handler_reported_unverified_result=payload,
                    note=f"The mutation may have succeeded, but its verification could not run ({detail}). "
                         "Nested results are handler-reported, not confirmation. " + reread)
        message = f"{post.name}: verification could not run - {detail}"
    return {"content": [{"type": "text", "text": json.dumps(
                body, indent=2)}], "isError": True, "message": message}


def _check_input_keys(handler, posts):
    """Raise at registration when a postcondition names a handler parameter that does not exist -
    such a key reads None and the kind would verify its default target instead."""
    import inspect
    try:
        params = set(inspect.signature(handler).parameters)
    except (TypeError, ValueError):
        return                       # an unintrospectable callable - nothing to check against
    for post in posts:
        unknown = [k for k in getattr(post, "input_keys", ()) or () if k not in params]
        if unknown:
            raise ValueError(
                f"postcondition {post.name} reads handler argument(s) {', '.join(unknown)}, which "
                f"{getattr(handler, '__name__', 'the handler')} does not take "
                f"({', '.join(sorted(params)) or 'no parameters'}). It would verify the wrong state.")


def wrap(handler, postconditions):
    """Guard an Edit's baseline, run its handler, then verify JSON success without rollback."""
    posts = list(postconditions or [])
    if not posts:
        return handler
    _check_input_keys(handler, posts)

    def _capture(p, kwargs):
        try:
            return p.capture(kwargs), None
        except Exception as ex:     # a raising capture leaves no baseline - recorded, not swallowed
            return None, ex

    def asserted(**kwargs):
        before = [_capture(p, kwargs) for p in posts]
        for p, (_baseline, cap_ex) in zip(posts, before):
            if cap_ex is not None and p.severity != "soft":
                return _verification_failed(p, cap_ex)
        result = handler(**kwargs)
        if not isinstance(result, dict) or result.get("isError"):
            return result
        content = result.get("content")
        if not (isinstance(content, list) and content and isinstance(content[0], dict)
                and content[0].get("type") == "text"):
            return result
        try:
            payload = json.loads(content[0]["text"])
        except Exception:
            return result
        if not isinstance(payload, dict):
            return result

        for p, (b, cap_ex) in zip(posts, before):
            soft = (p.severity == "soft")
            if cap_ex is not None:
                payload.setdefault(p.name + "_confirmed", False)
                payload.setdefault("verify_error", ("capture failed: " + str(cap_ex))[:120])
                continue
            try:
                reason, evidence = p.verify(kwargs, payload, b)
            except Exception as ex:
                # A raising verify cannot read ground truth: HARD fails closed, SOFT annotates.
                if soft:
                    payload.setdefault(p.name + "_confirmed", False)
                    payload.setdefault("verify_error", str(ex)[:120])
                    continue
                return _verification_failed(p, ex, payload)
            if reason:
                if soft:
                    payload.setdefault("verified", {})[p.name] = {"confirmed": False,
                                                                  "reason": reason}
                    continue
                reread = f"Re-read with {p.read_tool}." if p.read_tool else "Re-read the affected state."
                return {"content": [{"type": "text", "text": json.dumps(
                            {"postcondition": p.name, "note": reason + " " + reread
                             + " Nested results are handler-reported, not confirmation; inspect before retrying.",
                             "handler_reported_unverified_result": payload,
                             "verification_evidence": evidence or {}}, indent=2)}],
                        "isError": True,
                        "message": f"{p.name}: {reason}"}
            for k, v in (evidence or {}).items():
                payload.setdefault(k, v)
        content[0]["text"] = json.dumps(payload, indent=2)
        return result

    asserted.__name__ = getattr(handler, "__name__", "asserted")
    asserted.__wrapped__ = handler                   # tests/introspection reach the original
    asserted.__assert_postconditions__ = posts       # the declaration lint reads this
    return asserted
