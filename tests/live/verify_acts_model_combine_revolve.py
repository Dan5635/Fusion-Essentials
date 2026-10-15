# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Combine, interference, and revolve checks for model acts."""

import math

from verify_core import (
    _RECALL, _ctx_get, _document_closed, _extruded, _fg, _home_address, _home_document, _made_component, _measured, _near, _new_document, _recall, _refused, _revolved)






def _interference_pin(ctx, args):
    """Add the exact owned-document pin to one interference-fixture write."""
    return {**args, "expect_document": _ctx_get(
        ctx, "interference_scratch", "the interference scratch document")}


def _peg_faces_per_instance(p):
    """find_geometry over both Peg instances: one cylinder face per instance, each naming its own."""
    got = sorted(str(m.get("occurrence")) for m in p.get("matches") or [])
    return _measured("each Peg cylinder names the instance it was read through",
                     {"occurrences": got}, got == ["Peg:1", "Peg:2"])


def _separated_block_poses(p):
    """Read two 10 mm bodies whose world centers are 50 mm apart along X."""
    rows = {r.get("name"): r for r in p.get("occurrences", [])}
    a, b = rows.get("BlockA:1", {}), rows.get("BlockB:1", {})
    ca, cb = a.get("bbox_center", []), b.get("bbox_center", [])
    return _measured("separated scratch bodies have independent world poses",
                     {"a": a, "b": b},
                     a.get("body_count") == b.get("body_count") == 1
                     and a.get("bbox_size") == b.get("bbox_size") == [10, 10, 10]
                     and len(ca) == len(cb) == 3
                     and all(_near(y - x, d, 0.001) for x, y, d in
                             zip(ca, cb, [50, 0, 0])))


def _separated_interference(include_coincident_faces):
    """Check a complete clear result under one coincident-face policy."""
    def check(p):
        m = p.get("measured") or {}
        note = p.get("note") or ""
        policy = "included" if include_coincident_faces else "excluded"
        return _measured("separated scratch bodies: clear overlap, no fit claim",
                         {"measured": m, "note": note},
                         p.get("passed") is True and m.get("analysis_complete") is True
                         and m.get("interference_count") == 0
                         and m.get("pairs_analyzed") == 0 and m.get("pairs_pruned") == 1
                         and m.get("pairs_omitted") == 0
                         and p.get("tolerance_used", {}).get("coincident_faces_included")
                         is include_coincident_faces
                         and "compared solid bodies" in note
                         and "coincident faces " + policy in note
                         and "fits" not in note.lower())
    return check


def _interference_pair_named(p):
    """assembly_inspect_interference on the Peg/BlockA/BlockB rig: each of Peg's two instances
    interferes with its OWN block, named exactly - no '(or N more instance(s))' guess."""
    rows = (p.get("measured") or {}).get("interferences") or []
    by_pair = {tuple(sorted([r.get("occurrence_one"), r.get("occurrence_two")])): r for r in rows}
    a = by_pair.get(tuple(sorted(["Peg:1", "BlockA:1"])))
    b = by_pair.get(tuple(sorted(["Peg:2", "BlockB:1"])))
    no_candidates = not any("candidates" in k for r in rows for k in r)
    return _measured(
        "Peg:1 x BlockA:1 and Peg:2 x BlockB:1 named exactly, each with its own volume",
        {"pairs": sorted(by_pair), "vol_a": a and a.get("overlap_volume_cm3"),
         "vol_b": b and b.get("overlap_volume_cm3")},
        a is not None and b is not None and no_candidates
        and isinstance(a.get("overlap_volume_cm3"), (int, float)) and a["overlap_volume_cm3"] > 0
        and isinstance(b.get("overlap_volume_cm3"), (int, float)) and b["overlap_volume_cm3"] > 0)


def _shared_cube_overlap(volume, analyzed, pruned):
    """Require the reused two-placement part's independently sized overlap."""
    def check(p):
        rows = (p.get("measured") or {}).get("interferences") or []
        pair = [r for r in rows if {r.get("occurrence_one"), r.get("occurrence_two")}
                == {"OverlapPart:1", "OverlapPart:2"}]
        measured = p.get("measured") or {}
        return _measured("repeated component overlap volume and placed-body pair counts", measured,
                         p.get("passed") is False and len(pair) == 1
                         and measured.get("pair_unit") == "placed_body"
                         and measured.get("pairs_analyzed") == analyzed
                         and measured.get("pairs_pruned") == pruned
                         and measured.get("analysis_complete") is True
                         and measured.get("pairs_omitted") == 0
                         and _near(pair[0].get("overlap_volume_cm3"), volume, 0.001))
    return check


def _shared_cube_poses(body_count):
    """Read the body envelopes and 10 mm placement offset independently of interference."""
    def check(p):
        rows = {r.get("name"): r for r in p.get("occurrences", [])}
        a, b = rows.get("OverlapPart:1", {}), rows.get("OverlapPart:2", {})
        ca, cb = a.get("bbox_center", []), b.get("bbox_center", [])
        size = [20 if body_count == 1 else 70, 20, 20]
        return _measured("two shared parts overlap by 10 mm along X", {"first": a, "second": b},
                         a.get("component") == b.get("component") == "OverlapPart"
                         and a.get("body_count") == b.get("body_count") == body_count
                         and a.get("bbox_size") == b.get("bbox_size") == size
                         and len(ca) == len(cb) == 3
                         and all(_near(y - x, d, 0.001) for x, y, d in zip(ca, cb, [10, 0, 0])))
    return check


def _contact_part_poses(count):
    """Read the contact fixture's placed body count and independent envelope."""
    def check(p):
        rows = [r for r in p.get("occurrences", []) if r.get("name") == "ContactPart:1"]
        return _measured("contact bodies span 40 x 20 x 20 mm", {"rows": rows},
                         len(rows) == 1 and rows[0].get("body_count") == count
                         and all(_near(x, y, 0.001) for x, y in
                                 zip(rows[0].get("bbox_size", []), [40, 20, 20]))
                         and len(rows[0].get("bbox_size", [])) == 3)
    return check


def _contact_overlap(volumes):
    """Require separate rows for the contact fixture, including a colliding root-body label."""
    def check(p):
        measured = p.get("measured") or {}
        rows = [r for r in measured.get("interferences", [])
                if r.get("occurrence_one") == r.get("occurrence_two") == "ContactPart:1"]
        got = sorted((r.get("overlap_volume_cm3") for r in rows),
                     key=lambda v: v if isinstance(v, (int, float)) else math.inf)
        return _measured("contact and overlap results preserve physical pairs", {"rows": rows},
                         measured.get("analysis_complete") is True
                         and len(got) == len(volumes)
                         and (not volumes or p.get("passed") is False)
                         and all(_near(a, b, 0.001) for a, b in zip(got, volumes)))
    return check


def _interference_budget(p):
    """Require a partial self-volume when the dense body's pair count exceeds the limit."""
    m = p.get("measured") or {}
    census = m.get("body_census") or {}
    body_rows = census.get("bodies") or []
    rows = [r for r in m.get("interferences", [])
            if r.get("occurrence_one") == r.get("occurrence_two") == "BudgetPart:1"]
    return _measured("dense overlap stops with disclosed omitted pairs and partial volume", m,
                     p.get("passed") is False and m.get("analysis_complete") is False
                     and 0 < m.get("pairs_analyzed", 0) <= 5000
                     and m.get("pairs_omitted", 0) > 0
                     and census.get("count", 0) >= 102 and census.get("offset") == 0
                     and census.get("returned_count") == len(body_rows) == 30
                     and census.get("truncated") is True and census.get("next_offset") == 30
                     and all(isinstance(row.get(k), int) and row[k] >= 0
                             for row in body_rows
                             for k in ("pairs_analyzed", "pairs_pruned", "pairs_omitted"))
                     and len(rows) == 1 and rows[0].get("partial") is True
                     and isinstance(rows[0].get("overlap_volume_cm3"), (int, float))
                     and 0 < rows[0]["overlap_volume_cm3"] < 34133.96)


def _fractional_helix_cap(p, turns=1.1, start_z=100):
    """Read the piped spline's end cap at the requested fractional-turn endpoint."""
    wanted = [10 * math.cos(2 * turns * math.pi), 10 * math.sin(2 * turns * math.pi),
              start_z + 10 * turns]
    positions = [r.get("position", []) for r in p.get("matches", [])]
    return _measured(f"{turns:g}-turn helix end cap at {360 * turns:g} degrees",
                     {"positions": positions, "expected": wanted},
                     any(len(at) == 3 and all(_near(a, b, 0.002) for a, b in zip(at, wanted))
                         for at in positions))


def _combine_story_address(p):
    """Return the story handle while recording the open-document baseline."""
    _RECALL["combine_open_before"] = p.get("open_count")
    return _home_address(p)


def _combine_owned_active(key):
    """The new owned document is the sole active row and opened beside the story."""
    def check(p):
        active = p.get("active") or {}
        rows = [r for r in (p.get("open_documents") or []) if r.get("is_active")]
        return _measured(
            "owned combine document active at its exact handle",
            {"active": active.get("document_handle"), "owned": _RECALL.get(key),
             "open_count": p.get("open_count"), "before": _RECALL.get("combine_open_before")},
            len(rows) == 1 and active.get("document_handle") == _RECALL.get(key)
            and rows[0].get("document_handle") == _RECALL.get(key)
            and p.get("open_count") == _RECALL.get("combine_open_before") + 1)
    return check


def _combine_story_restored(p):
    """The owned document is gone and the original story handle is active again."""
    active = p.get("active") or {}
    rows = [r for r in (p.get("open_documents") or []) if r.get("is_active")]
    return _measured(
        "combine scratch closed and story document restored",
        {"active": active.get("document_handle"), "story": _RECALL.get("combine_story"),
         "open_count": p.get("open_count"), "before": _RECALL.get("combine_open_before")},
        len(rows) == 1 and active.get("document_handle") == _RECALL.get("combine_story")
        and rows[0].get("document_handle") == _RECALL.get("combine_story")
        and p.get("open_count") == _RECALL.get("combine_open_before"))


def _combine_census(label, bodies, low, high, volume, kind="design"):
    """A complete body census with exact names, lump counts, total volume and bounds."""
    expected = sorted((name, body_volume, 1) for name, body_volume, _lo, _hi in bodies)

    def check(p):
        mass = p.get("mass") or {}
        rows = mass.get("per_body") or []
        got = sorted((r.get("body"), r.get("volume"), r.get("lump_count")) for r in rows)
        bounds = ((p.get("min_point") or {}), (p.get("max_point") or {}))
        bounds_ok = all(_near(point.get(axis), want, 0.01)
                        for point, wanted in zip(bounds, (low, high))
                        for axis, want in zip(("x", "y", "z"), wanted))
        return _measured(
            label + " complete body census",
            {"count": mass.get("per_body_count"), "returned": len(rows),
             "truncated": mass.get("per_body_truncated"), "bodies": got,
             "volume": mass.get("volume"), "min": bounds[0], "max": bounds[1]},
            p.get("kind") == kind and p.get("units") == "mm"
            and mass.get("accuracy_used") == "very_high"
            and mass.get("per_body_count") == len(expected) == len(rows)
            and mass.get("per_body_truncated") is False and got == expected
            and _near(mass.get("volume"), volume, 0.001) and bounds_ok)
    return check


def _combine_body(label, low, high, volume):
    """One result or restored body has exact bounds, volume and one connected lump."""
    def check(p):
        mass = p.get("mass") or {}
        bounds = ((p.get("min_point") or {}), (p.get("max_point") or {}))
        bounds_ok = all(_near(point.get(axis), want, 0.01)
                        for point, wanted in zip(bounds, (low, high))
                        for axis, want in zip(("x", "y", "z"), wanted))
        return _measured(
            label + " body bounds and volume",
            {"kind": p.get("kind"), "units": p.get("units"), "lumps": p.get("lump_count"),
             "volume": mass.get("volume"), "min": bounds[0], "max": bounds[1]},
            p.get("kind") == "body" and p.get("units") == "mm"
            and mass.get("accuracy_used") == "very_high" and p.get("lump_count") == 1
            and _near(mass.get("volume"), volume, 0.001) and bounds_ok)
    return check


def _combine_join_outcome(outcome, result_bodies, result_lumps):
    """The combine response reports one complete result/lump classification."""
    def check(p):
        note = p.get("note") or ""
        note_ok = ("partially fused" in note and "fused NOTHING" not in note
                   if outcome == "partial" else
                   ("fused NOTHING" in note if outcome == "none" else "WARNING" not in note))
        return _measured(
            outcome + " join result/lump report",
            {"outcome": p.get("fusion_outcome"), "fused": p.get("fused"),
             "body_count": p.get("result_body_count"),
             "bodies_complete": p.get("result_bodies_complete"),
             "input_lumps": p.get("input_lump_total"),
             "result_lumps": p.get("result_lump_total"), "feature": p.get("feature")},
            p.get("fusion_outcome") == outcome
            and p.get("fused") is (outcome != "none")
            and p.get("result_body_count") == result_bodies
            and p.get("result_bodies_complete") is True
            and p.get("input_lump_total") == 3 and p.get("result_lump_total") == result_lumps
            and p.get("feature") == "Combine1" and note_ok)
    return check


def _combine_timeline(prefix, joined, component=None):
    """The bounded timeline is exactly the authored host, bodies and optional combine."""
    wanted = [(f"{prefix}{i}", "Sketch", component) if j % 2 == 0
              else (f"Extrude{i + 1}", "ExtrudeFeature", component)
              for i in range(3) for j in range(2)]
    if component:
        wanted.insert(0, (" " + component + ":1", "Occurrence", None))
    if joined:
        wanted.append(("Combine1", "CombineFeature", component))

    def check(p):
        timeline = p.get("timeline") or {}
        rows = timeline.get("timeline") or []
        got = [(r.get("name"), r.get("type"), r.get("component") if component else None)
               for r in rows]
        return _measured(
            ("complete combine timeline" if joined else
             ("restored combine timeline" if component else "restored six-row timeline")),
            {"count": timeline.get("count"), "returned": timeline.get("returned"),
             "truncated": timeline.get("truncated"), "rows": got},
            timeline.get("count") == timeline.get("returned") == len(wanted) == len(rows)
            and timeline.get("truncated") is not True and got == wanted)
    return check


def _combine_deleted(p, index=6):
    """Only the authored Combine1 feature at the expected timeline index was deleted."""
    return _measured(
        "Combine1 deleted by exact feature name",
        {"deleted": p.get("deleted"), "feature": p.get("feature"),
         "index": p.get("index"), "entity_type": p.get("entity_type")},
        p.get("deleted") is True and p.get("feature") == "Combine1"
        and p.get("index") == index and p.get("entity_type") == "CombineFeature")


def _combine_nonroot_component(p):
    """The non-root host reports its transformed occurrence and active component."""
    position = p.get("position") or {}
    return _measured(
        "transformed non-root combine host",
        {"occurrence": p.get("occurrence"), "component": p.get("component"),
         "position": position, "rotate_deg": p.get("rotate_deg"),
         "rotate_axis": p.get("rotate_axis"), "activated": p.get("activated")},
        p.get("created") is True and p.get("occurrence") == "JoinProxyHost:1"
        and p.get("component") == "JoinProxyHost"
        and p.get("full_path") == "JoinProxyHost:1" and p.get("units") == "mm"
        and [position.get(axis) for axis in ("x", "y", "z")] == [100, 40, 30]
        and _near(p.get("rotate_deg"), 90, 0.001) and p.get("rotate_axis") == "z"
        and p.get("activated") is True)


def _combine_face(position):
    """One planar-face handle was acquired at the expected world position."""
    def check(p):
        matches = p.get("matches") or []
        got = matches[0] if len(matches) == 1 else {}
        return _measured(
            "qualified non-root planar face",
            {"count": p.get("match_count"), "returned": p.get("returned"),
             "kind": got.get("kind"), "position": got.get("position")},
            p.get("units") == "mm" and p.get("match_count") == 6
            and p.get("returned") == len(matches) == 1
            and got.get("kind") == "planar_face"
            and isinstance(got.get("handle"), str) and bool(got["handle"])
            and len(got.get("position") or []) == len(position)
            and all(_near(a, b, 0.01) for a, b in zip(got["position"], position))
            and len(got.get("normal") or []) == 3
            and all(_near(a, b, 0.001) for a, b in zip(got["normal"], (0, 0, 1))))
    return check


def _combine_pin(ctx, key, args):
    """Add the exact owned-document pin to one write."""
    return {**args, "expect_document": _ctx_get(ctx, key, "the combine scratch document")}


def _combine_inspect(target=""):
    """The canonical bounds, mass and complete per-body read arguments."""
    args = {"include": ["default", "mass"], "units": "mm", "accuracy": "very_high"}
    if target:
        args["target"] = target
    else:
        args["per_body"] = True
    return args


def _combine_case_rows(case, rectangles, before, after):
    """Build one isolated root-parametric complete/partial/none combine control."""
    owned = "combine_" + case + "_doc"
    prefix = "Join" + case.title()
    low = tuple(min(body[2][i] for body in before) for i in range(3))
    high = tuple(max(body[3][i] for body in before) for i in range(3))
    before_volume = sum(body[1] for body in before)
    after_low = tuple(min(body[2][i] for body in after) for i in range(3))
    after_high = tuple(max(body[3][i] for body in after) for i in range(3))
    after_volume = sum(body[1] for body in after)
    rows = [
        ("doc_new",
         lambda c: {"expect_document": _ctx_get(c, "combine_story", "the story document")},
         _new_document, (owned, _recall(owned, lambda p: p["document_handle"]))),
        ("doc_get", {}, _combine_owned_active(owned), None),
    ]
    if case == "complete":
        # This scratch document never enters Manufacture, so the CAM-product refusal and the
        # library listing that needs no such product make a discriminating PAIR on it: the machine
        # catalog hangs off CAMManager.libraryManager, which the document does not own.
        rows += [
            ("cam_get", {}, _refused("no CAM"), None),
            ("cam_get", {"include": ["machines"], "vendor": "Haas", "machine_type": "milling"},
             lambda p: p.get("machines", {}).get("count", 0) > 0 and "setups" not in p, None),
        ]
    for i, (x1, x2) in enumerate(rectangles):
        rows += [
            ("sketch_create",
             lambda c, name=f"{prefix}{i}": _combine_pin(
                 c, owned, {"plane": "xy", "name": name}), "ok", None),
            ("sketch_add_geometry",
             lambda c, name=f"{prefix}{i}", x1=x1, x2=x2: _combine_pin(
                 c, owned, {"geometry": [{"kind": "rectangle", "x1": x1, "y1": 0,
                                          "x2": x2, "y2": 10}],
                            "sketch_name": name}), "ok", None),
            ("model_extrude",
             lambda c, name=f"{prefix}{i}": _combine_pin(
                 c, owned, {"sketch_name": name, "profile_index": 0,
                            "distance": 10, "operation": "new"}), _extruded, None),
        ]
    if case == "complete":
        rows += [
            ("find_geometry", {"target": "Body1", "kind": "planar_face",
                               "nearest_to": [5, 5, 10], "max_results": 1},
             "ok", _fg("combine_self_a")),
            ("find_geometry", {"target": "Body1", "kind": "planar_face",
                               "nearest_to": [5, 5, 0], "max_results": 1},
             "ok", _fg("combine_self_b")),
            ("model_combine",
             lambda c: _combine_pin(
                 c, owned, {"target": _ctx_get(c, "combine_self_a", "combine target"),
                            "tools": [_ctx_get(c, "combine_self_b", "the same body again")],
                            "operation": "join"}),
             _refused("same as the target", "distinct bodies"), None),
        ]
    rows += [
        ("model_inspect", _combine_inspect(),
         _combine_census(case + " before", before, low, high, before_volume), None),
    ]
    rows += [("model_inspect", _combine_inspect(name),
              _combine_body(case + " before " + name, body_low, body_high, volume), None)
             for name, volume, body_low, body_high in before]
    rows += [
        ("model_combine",
         lambda c: _combine_pin(c, owned, {"target": "Body1", "tools": ["Body2", "Body3"],
                                                   "operation": "join", "keep_tools": False,
                                                   "new_component": False}),
         _combine_join_outcome(case, len(after), len(after)), None),
        ("model_inspect", _combine_inspect(),
         _combine_census(case + " after", after, after_low, after_high, after_volume), None),
    ]
    rows += [("model_inspect", _combine_inspect(name),
              _combine_body(case + " after " + name, body_low, body_high, volume), None)
             for name, volume, body_low, body_high in after]
    rows += [
        ("design_get", {"include": ["timeline"], "max_results": 7},
         _combine_timeline(prefix, True), None),
        ("design_delete_feature",
         lambda c: _combine_pin(c, owned, {"feature": "Combine1"}), _combine_deleted, None),
        ("model_inspect", _combine_inspect(),
         _combine_census(case + " restored", before, low, high, before_volume), None),
    ]
    rows += [("model_inspect", _combine_inspect(name),
              _combine_body(case + " restored " + name, body_low, body_high, volume), None)
             for name, volume, body_low, body_high in before]
    rows += [
        ("design_get", {"include": ["timeline"], "max_results": 6},
         _combine_timeline(prefix, False), None),
        ("doc_activate",
         lambda c: {"name": _ctx_get(c, "combine_story", "the story document"),
                    "expect_document": _ctx_get(c, owned, "the combine scratch document")},
         "ok", None),
        ("doc_close",
         lambda c: {"name": _ctx_get(c, owned, "the combine scratch document"),
                    "save_changes": False,
                    "expect_document": _ctx_get(c, "combine_story", "the story document")},
         _document_closed, None),
        ("doc_get", {}, _combine_story_restored, None),
    ]
    return rows


_COMBINE_COMPLETE = _combine_case_rows(
    "complete", ((0, 20), (10, 30), (20, 40)),
    (("Body1", 2000.0, (0, 0, 0), (20, 10, 10)),
     ("Body2", 2000.0, (10, 0, 0), (30, 10, 10)),
     ("Body3", 2000.0, (20, 0, 0), (40, 10, 10))),
    (("Body1", 4000.0, (0, 0, 0), (40, 10, 10)),))

_COMBINE_PARTIAL = _combine_case_rows(
    "partial", ((0, 20), (10, 30), (50, 60)),
    (("Body1", 2000.0, (0, 0, 0), (20, 10, 10)),
     ("Body2", 2000.0, (10, 0, 0), (30, 10, 10)),
     ("Body3", 1000.0, (50, 0, 0), (60, 10, 10))),
    (("Body1", 3000.0, (0, 0, 0), (30, 10, 10)),
     ("Body4", 1000.0, (50, 0, 0), (60, 10, 10))))

_COMBINE_NONE = _combine_case_rows(
    "none", ((0, 20), (30, 50), (60, 80)),
    (("Body1", 2000.0, (0, 0, 0), (20, 10, 10)),
     ("Body2", 2000.0, (30, 0, 0), (50, 10, 10)),
     ("Body3", 2000.0, (60, 0, 0), (80, 10, 10))),
    (("Body1", 2000.0, (0, 0, 0), (20, 10, 10)),
     ("Body4", 2000.0, (30, 0, 0), (50, 10, 10)),
     ("Body5", 2000.0, (60, 0, 0), (80, 10, 10))))


def _cut_none_timeline(p):
    """The bounded timeline holds only the two authored bodies, no combine feature."""
    timeline = p.get("timeline") or {}
    rows = timeline.get("timeline") or []
    got = [(r.get("name"), r.get("type")) for r in rows]
    wanted = [("CutNone0", "Sketch"), ("Extrude1", "ExtrudeFeature"),
              ("CutNone1", "Sketch"), ("Extrude2", "ExtrudeFeature")]
    return _measured("disjoint-cut history without a combine feature",
                     {"count": timeline.get("count"), "rows": got},
                     timeline.get("count") == len(rows) == 4 and got == wanted)


def _combine_cut_none_rows():
    """A cut whose tool misses the target: refused, its feature deleted, the body count named."""
    owned = "combine_cut_none_doc"
    bodies = (("Body1", 2000.0, (0, 0, 0), (20, 10, 10)),
              ("Body2", 2000.0, (60, 0, 0), (80, 10, 10)))
    rows = [
        ("doc_new",
         lambda c: {"expect_document": _ctx_get(c, "combine_story", "the story document")},
         _new_document, (owned, _recall(owned, lambda p: p["document_handle"]))),
        ("doc_get", {}, _combine_owned_active(owned), None),
    ]
    for i, (x1, x2) in enumerate(((0, 20), (60, 80))):
        rows += [
            ("sketch_create", lambda c, name=f"CutNone{i}": _combine_pin(
                c, owned, {"plane": "xy", "name": name}), "ok", None),
            ("sketch_add_geometry", lambda c, name=f"CutNone{i}", x1=x1, x2=x2: _combine_pin(
                c, owned, {"geometry": [{"kind": "rectangle", "x1": x1, "y1": 0,
                                         "x2": x2, "y2": 10}], "sketch_name": name}), "ok", None),
            ("model_extrude", lambda c, name=f"CutNone{i}": _combine_pin(
                c, owned, {"sketch_name": name, "profile_index": 0, "distance": 10,
                           "operation": "new"}), _extruded, None),
        ]
    rows += [
        ("model_inspect", _combine_inspect(),
         _combine_census("cut-none before", bodies, (0, 0, 0), (80, 10, 10), 4000.0), None),
        ("model_combine",
         lambda c: _combine_pin(c, owned, {"target": "Body1", "tools": ["Body2"], "operation": "cut",
                                           "keep_tools": False, "new_component": False}),
         _refused("changed NOTHING", "Deleting it returned True.", "bodies (was 2)."), None),
        ("design_get", {"include": ["timeline"], "max_results": 5}, _cut_none_timeline, None),
        ("model_inspect", _combine_inspect(),
         _combine_census("cut-none after", bodies, (0, 0, 0), (80, 10, 10), 4000.0), None),
        ("doc_activate",
         lambda c: {"name": _ctx_get(c, "combine_story", "the story document"),
                    "expect_document": _ctx_get(c, owned, "the combine scratch document")},
         "ok", None),
        ("doc_close",
         lambda c: {"name": _ctx_get(c, owned, "the combine scratch document"),
                    "save_changes": False,
                    "expect_document": _ctx_get(c, "combine_story", "the story document")},
         _document_closed, None),
        ("doc_get", {}, _combine_story_restored, None),
    ]
    return rows


_COMBINE_CUT_NONE = _combine_cut_none_rows()


def _combine_nonroot_partial_rows():
    """Build one transformed non-root partial join with proxy-face tool handles."""
    owned = "combine_nonroot_partial_doc"
    component = "JoinProxyHost"
    occurrence = component + ":1"
    before = (
        ("Body1", 2000.0, (90, 40, 30), (100, 60, 40)),
        ("Body2", 2000.0, (90, 50, 30), (100, 70, 40)),
        ("Body3", 1000.0, (90, 90, 30), (100, 100, 40)),
    )
    after = (
        ("Body1", 3000.0, (90, 40, 30), (100, 70, 40)),
        ("Body4", 1000.0, (90, 90, 30), (100, 100, 40)),
    )
    rows = [
        ("doc_new",
         lambda c: {"expect_document": _ctx_get(c, "combine_story", "the story document")},
         _new_document, (owned, _recall(owned, lambda p: p["document_handle"]))),
        ("doc_get", {}, _combine_owned_active(owned), None),
        ("model_create_component",
         lambda c: _combine_pin(
             c, owned, {"name": component, "x": 100, "y": 40, "z": 30,
                        "rotate_deg": 90, "rotate_axis": "z", "activate": True}),
         _combine_nonroot_component, None),
    ]
    for i, (x1, x2) in enumerate(((0, 20), (10, 30), (50, 60))):
        rows += [
            ("sketch_create",
             lambda c, name=f"ProxyBox{i}": _combine_pin(
                 c, owned, {"plane": "xy", "name": name}), "ok", None),
            ("sketch_add_geometry",
             lambda c, name=f"ProxyBox{i}", x1=x1, x2=x2: _combine_pin(
                 c, owned, {"geometry": [{"kind": "rectangle", "x1": x1, "y1": 0,
                                          "x2": x2, "y2": 10}],
                            "sketch_name": name}), "ok", None),
            ("model_extrude",
             lambda c, name=f"ProxyBox{i}": _combine_pin(
                 c, owned, {"sketch_name": name, "profile_index": 0,
                            "distance": 10, "operation": "new"}), _extruded, None),
        ]
    rows += [
        ("model_inspect", {**_combine_inspect(occurrence), "per_body": True},
         _combine_census("non-root partial before", before,
                         (90, 40, 30), (100, 100, 40), 5000.0, "occurrence"), None),
    ]
    rows += [
        ("model_inspect", _combine_inspect(occurrence + ":" + name),
         _combine_body("non-root partial before " + name, low, high, volume), None)
        for name, volume, low, high in before
    ]
    rows += [
        ("find_geometry", {"target": occurrence + ":Body2", "kind": "planar_face",
                           "nearest_to": [95, 60, 40], "max_results": 1},
         _combine_face((95, 60, 40)), _fg("combine_nonroot_tool_a")),
        ("find_geometry", {"target": occurrence + ":Body3", "kind": "planar_face",
                           "nearest_to": [95, 95, 40], "max_results": 1},
         _combine_face((95, 95, 40)), _fg("combine_nonroot_tool_b")),
        ("model_combine",
         lambda c: _combine_pin(
             c, owned, {"target": occurrence + ":Body1",
                        "tools": [_ctx_get(c, "combine_nonroot_tool_a", "Body2 planar face"),
                                  _ctx_get(c, "combine_nonroot_tool_b", "Body3 planar face")],
                        "operation": "join", "keep_tools": False, "new_component": False}),
         _combine_join_outcome("partial", 2, 2), None),
        ("model_inspect", {**_combine_inspect(occurrence), "per_body": True},
         _combine_census("non-root partial after", after,
                         (90, 40, 30), (100, 100, 40), 4000.0, "occurrence"), None),
    ]
    rows += [
        ("model_inspect", _combine_inspect(occurrence + ":" + name),
         _combine_body("non-root partial after " + name, low, high, volume), None)
        for name, volume, low, high in after
    ]
    rows += [
        ("design_get", {"include": ["timeline"], "max_results": 8},
         _combine_timeline("ProxyBox", True, component), None),
        ("design_delete_feature",
         lambda c: _combine_pin(c, owned, {"feature": "Combine1"}),
         lambda p: _combine_deleted(p, 7), None),
        ("model_inspect", {**_combine_inspect(occurrence), "per_body": True},
         _combine_census("non-root partial restored", before,
                         (90, 40, 30), (100, 100, 40), 5000.0, "occurrence"), None),
    ]
    rows += [
        ("model_inspect", _combine_inspect(occurrence + ":" + name),
         _combine_body("non-root partial restored " + name, low, high, volume), None)
        for name, volume, low, high in before
    ]
    rows += [
        ("design_get", {"include": ["timeline"], "max_results": 7},
         _combine_timeline("ProxyBox", False, component), None),
        ("doc_activate",
         lambda c: {"name": _ctx_get(c, "combine_story", "the story document"),
                    "expect_document": _ctx_get(c, owned, "the combine scratch document")},
         "ok", None),
        ("doc_close",
         lambda c: {"name": _ctx_get(c, owned, "the combine scratch document"),
                    "save_changes": False,
                    "expect_document": _ctx_get(c, "combine_story", "the story document")},
         _document_closed, None),
        ("doc_get", {}, _combine_story_restored, None),
    ]
    return rows


_COMBINE_NONROOT_PARTIAL = _combine_nonroot_partial_rows()

_REVOLVE_HOST = "RevolveProof"
_REVOLVE_OCCURRENCE = _REVOLVE_HOST + ":1"
_REVOLVE_BASELINE = (
    ("Body1", 1280 * math.pi, (-10, -10, 0), (10, 10, 20)),
    ("Body2", 500 * math.pi, (-5, -5, 0), (5, 5, 20)),
    ("Body3", 80 * math.pi, (28, -2, 0), (32, 2, 20)),
)


def _revolve_story_address(p):
    """Return the story handle while recording the open-document baseline."""
    _RECALL["revolve_open_before"] = p.get("open_count")
    return _home_address(p)


def _revolve_owned_active(p):
    """Require the new revolve document beside the exact story document."""
    active = p.get("active") or {}
    rows = [row for row in (p.get("open_documents") or []) if row.get("is_active")]
    return _measured(
        "owned revolve document active at its exact handle",
        {"active": active.get("document_handle"), "owned": _RECALL.get("revolve_participant_doc"),
         "open_count": p.get("open_count"), "before": _RECALL.get("revolve_open_before")},
        len(rows) == 1
        and active.get("document_handle") == _RECALL.get("revolve_participant_doc")
        and rows[0].get("document_handle") == _RECALL.get("revolve_participant_doc")
        and p.get("open_count") == _RECALL.get("revolve_open_before") + 1)


def _revolve_story_restored(p):
    """Require the revolve document gone and the exact story document active."""
    active = p.get("active") or {}
    rows = [row for row in (p.get("open_documents") or []) if row.get("is_active")]
    return _measured(
        "revolve scratch closed and story document restored",
        {"active": active.get("document_handle"), "story": _RECALL.get("revolve_story"),
         "open_count": p.get("open_count"), "before": _RECALL.get("revolve_open_before")},
        len(rows) == 1 and active.get("document_handle") == _RECALL.get("revolve_story")
        and rows[0].get("document_handle") == _RECALL.get("revolve_story")
        and p.get("open_count") == _RECALL.get("revolve_open_before"))


def _revolve_pin(ctx, args):
    """Add the exact owned-document pin to one revolve-fixture write."""
    return {**args, "expect_document": _ctx_get(
        ctx, "revolve_participant_doc", "the revolve scratch document")}


def _revolve_census(label, bodies):
    """Require one complete participant census with analytical volume and world bounds."""
    expected = {name: (volume, low, high) for name, volume, low, high in bodies}
    low = tuple(min(body[2][i] for body in bodies) for i in range(3))
    high = tuple(max(body[3][i] for body in bodies) for i in range(3))

    def check(p):
        mass = p.get("mass") or {}
        rows = mass.get("per_body") or []
        got = {row.get("body"): row for row in rows}
        bounds = (p.get("min_point") or {}, p.get("max_point") or {})
        bounds_ok = all(_near(point.get(axis), want, 0.01)
                        for point, wanted in zip(bounds, (low, high))
                        for axis, want in zip(("x", "y", "z"), wanted))
        bodies_ok = (
            set(got) == set(expected) and len(rows) == len(expected)
            and all(row.get("is_solid") is True and row.get("lump_count") == 1
                    and _near(row.get("volume"), expected[name][0], 0.001)
                    for name, row in got.items()))
        return _measured(
            label + " revolve participant census",
            {"count": mass.get("per_body_count"), "returned": len(rows),
             "truncated": mass.get("per_body_truncated"),
             "bodies": sorted((name, row.get("volume"), row.get("lump_count"))
                              for name, row in got.items()),
             "volume": mass.get("volume"), "min": bounds[0], "max": bounds[1]},
            p.get("kind") == "occurrence" and p.get("units") == "mm"
            and mass.get("accuracy_used") == "very_high"
            and mass.get("per_body_count") == len(expected) == len(rows)
            and mass.get("per_body_truncated") is False and bodies_ok
            and _near(mass.get("volume"), sum(body[1] for body in bodies), 0.001)
            and bounds_ok)
    return check


def _revolve_cut(profile, feature, result_bodies, scoped, volume_delta_cm3):
    """Require the reported cut scope/results and its material-effect mode."""
    def check(p):
        scope = p.get("scoped_to_bodies")
        scope_ok = (scope == [_REVOLVE_OCCURRENCE + ":Body1"] if scoped
                    else "scoped_to_bodies" not in p)
        if volume_delta_cm3 is None:
            effect_ok = ("volume_delta_cm3" not in p
                         and "body count changed" in (p.get("note") or ""))
        else:
            effect_ok = _near(p.get("volume_delta_cm3"), volume_delta_cm3, 0.000001)
        return _measured(
            profile + " revolve cut result",
            {"feature": p.get("feature"), "operation": p.get("operation"),
             "results": p.get("result_bodies"), "scope": scope,
             "volume_delta_cm3": p.get("volume_delta_cm3")},
            p.get("revolved") is True and p.get("feature") == feature
            and p.get("operation") == "cut" and p.get("sketch") == profile
            and p.get("component") == _REVOLVE_HOST and p.get("axis") == "z-axis"
            and _near(p.get("angle_deg"), 360.0, 0.000001)
            and p.get("result_bodies") == list(result_bodies) and scope_ok and effect_ok)
    return check


def _revolve_deleted(feature):
    """Require deletion of the exact temporary RevolveFeature."""
    def check(p):
        return _measured(
            feature + " deleted",
            {"deleted": p.get("deleted"), "feature": p.get("feature"),
             "index": p.get("index"), "entity_type": p.get("entity_type")},
            p.get("deleted") is True and p.get("feature") == feature
            and p.get("index") == 9 and p.get("entity_type") == "RevolveFeature")
    return check


def _revolve_groove_face(p):
    """Require the new radius-9 groove face at world z=7.5 mm."""
    matches = p.get("matches") or []
    groove = [row for row in matches
              if _near(row.get("radius"), 9.0, 0.001)
              and len(row.get("position") or []) == 3
              and _near(row["position"][2], 7.5, 0.01)]
    return _measured(
        "radius-9 groove face at its axial position",
        {"count": p.get("match_count"), "returned": p.get("returned"),
         "groove": [(row.get("radius"), row.get("position"), row.get("area"))
                    for row in groove], "truncated": p.get("truncated")},
        p.get("units") == "mm" and p.get("match_count") == p.get("returned") == len(matches)
        and p.get("truncated") is not True and len(groove) == 1
        and _near(groove[0].get("area"), 90 * math.pi, 0.001))


def _revolve_body_rows(label, bodies):
    """Build separate mass-and-bounds reads for every expected participant body."""
    return [
        ("model_inspect", _combine_inspect(_REVOLVE_OCCURRENCE + ":" + name),
         _combine_body(label + " " + name, low, high, volume), None)
        for name, volume, low, high in bodies
    ]


def _revolve_selector_read(key, sketch=None, after=False):
    """Require complete history or a full source-sketch read around a refused selector."""
    def check(p):
        if sketch:
            valid = (p.get("sketch") == sketch and p.get("component") == _REVOLVE_HOST
                     and p.get("units") == "mm" and p.get("truncated") is False
                     and p.get("profile_count") == len(p.get("profiles") or []) == 1
                     and p.get("constraint_count") == len(p.get("constraints") or [])
                     and p.get("dimension_count") == len(p.get("dimensions") or [])
                     and isinstance(p.get("frame"), dict) and bool(p.get("entities")))
            value = {k: v for k, v in p.items() if k != "note"}
        else:
            value = p.get("timeline") or {}
            rows = value.get("timeline") or []
            valid = (value.get("count") == value.get("returned") == value.get("marker_position")
                     == len(rows) == 9 and not value.get("truncated")
                     and (value.get("summary") or {}).get("exceptions") == []
                     and (value.get("summary") or {}).get("states") == {"healthy": 9}
                     and all(r.get("index") == i and r.get("name") and r.get("type")
                             for i, r in enumerate(rows)))
        return _measured("revolve selector preserves " + key, value,
                         valid and (not after or value == _RECALL.get(key)))
    return check


def _revolve_participant_rows():
    """Build one isolated scoped, unscoped and splitting revolve-cut proof."""
    scoped = (
        ("Body1", 1055 * math.pi, (-10, -10, 0), (10, 10, 20)),
        _REVOLVE_BASELINE[1], _REVOLVE_BASELINE[2])
    unscoped = (
        scoped[0],
        ("Body2", 420 * math.pi, (-5, -5, 0), (5, 5, 20)),
        _REVOLVE_BASELINE[2])
    split = (
        ("Body1", 320 * math.pi, (-10, -10, 0), (10, 10, 5)),
        _REVOLVE_BASELINE[1], _REVOLVE_BASELINE[2],
        ("Body4", 640 * math.pi, (-10, -10, 10), (10, 10, 20)))
    rows = [
        ("doc_get", {}, _home_document,
         ("revolve_story", _recall("revolve_story", _revolve_story_address))),
        ("doc_new",
         lambda c: {"expect_document": _ctx_get(c, "revolve_story", "the story document")},
         _new_document, ("revolve_participant_doc", _recall(
             "revolve_participant_doc", lambda p: p["document_handle"]))),
        ("doc_get", {}, _revolve_owned_active, None),
        ("model_create_component",
         lambda c: _revolve_pin(c, {"name": _REVOLVE_HOST, "activate": True}),
         _made_component, None),
        ("sketch_create",
         lambda c: _revolve_pin(c, {"name": "RingProfile", "plane": "xz"}), "ok", None),
        ("sketch_add_geometry",
         lambda c: _revolve_pin(c, {
             "sketch_name": "RingProfile",
             "geometry": [{"kind": "rectangle", "x1": 6, "y1": -20, "x2": 10, "y2": 0}]}),
         "ok", None),
        ("model_revolve",
         lambda c: _revolve_pin(c, {
             "sketch_name": "RingProfile", "axis": "z", "angle_deg": 360}),
         _revolved, None),
        ("sketch_create",
         lambda c: _revolve_pin(c, {"name": "InnerProfile", "plane": "xy"}), "ok", None),
        ("sketch_add_geometry",
         lambda c: _revolve_pin(c, {
             "sketch_name": "InnerProfile",
             "geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 5}]}),
         "ok", None),
        ("model_extrude",
         lambda c: _revolve_pin(c, {
             "sketch_name": "InnerProfile", "distance": 20, "operation": "new"}),
         _extruded, None),
        ("sketch_create",
         lambda c: _revolve_pin(c, {"name": "DecoyProfile", "plane": "xy"}), "ok", None),
        ("sketch_add_geometry",
         lambda c: _revolve_pin(c, {
             "sketch_name": "DecoyProfile",
             "geometry": [{"kind": "circle", "cx": 30, "cy": 0, "radius": 2}]}),
         "ok", None),
        ("model_extrude",
         lambda c: _revolve_pin(c, {
             "sketch_name": "DecoyProfile", "distance": 20, "operation": "new"}),
         _extruded, None),
        ("sketch_create",
         lambda c: _revolve_pin(c, {"name": "GrooveProfile", "plane": "xz"}), "ok", None),
        ("sketch_add_geometry",
         lambda c: _revolve_pin(c, {
             "sketch_name": "GrooveProfile",
             "geometry": [{"kind": "rectangle", "x1": 3, "y1": -10, "x2": 9, "y2": -5}]}),
         "ok", None),
        ("sketch_create",
         lambda c: _revolve_pin(c, {"name": "BandProfile", "plane": "xz"}), "ok", None),
        ("sketch_add_geometry",
         lambda c: _revolve_pin(c, {
             "sketch_name": "BandProfile",
             "geometry": [{"kind": "rectangle", "x1": 0, "y1": -10, "x2": 11, "y2": -5}]}),
         "ok", None),
        ("model_inspect", {**_combine_inspect(_REVOLVE_OCCURRENCE), "per_body": True},
         _revolve_census("baseline", _REVOLVE_BASELINE), None),
    ]
    rows += _revolve_body_rows("baseline", _REVOLVE_BASELINE)
    reads = [("design_get", {"include": ["timeline"], "max_results": 20},
              "revolve_selector_history", None)] + [
        ("sketch_get", {"sketch_name": name, "component": _REVOLVE_OCCURRENCE,
                        "include_entities": True, "max_results": 100, "units": "mm"},
         "revolve_selector_" + name, name)
        for name in ("RingProfile", "InnerProfile", "DecoyProfile", "GrooveProfile", "BandProfile")]
    for tool, args, key, name in reads:
        rows.append((tool, args, _revolve_selector_read(key, name),
                     (key, _recall(key, lambda p, name=name:
                                  {k: v for k, v in p.items() if k != "note"}
                                  if name else p["timeline"]))))
    rows.append(("model_revolve", lambda c: _revolve_pin(c, {
        "sketch_name": "GrooveProfile", "component": _REVOLVE_HOST, "axis": "z",
        "operation": "cut", "profile_index": "garbage", "target_bodies": [_REVOLVE_HOST + ":Body1"]}),
        _refused("profile_index", "garbage", "integer index", "sketch_get"), None))
    rows += [(tool, args, _revolve_selector_read(key, name, True), None)
             for tool, args, key, name in reads]
    rows.append(("model_inspect", {**_combine_inspect(_REVOLVE_OCCURRENCE), "per_body": True},
                 _revolve_census("selector refusal", _REVOLVE_BASELINE), None))
    rows += _revolve_body_rows("selector refusal", _REVOLVE_BASELINE)
    cases = (
        ("scoped", "GrooveProfile", "Revolve2", ("Body1",), True,
         -225 * math.pi / 1000, scoped),
        ("unscoped", "GrooveProfile", "Revolve3", ("Body1", "Body2"), False,
         -305 * math.pi / 1000, unscoped),
        ("split", "BandProfile", "Revolve4", ("Body1", "Body4"), True, None, split),
    )
    for label, profile, feature, result_bodies, is_scoped, delta, after in cases:
        def cut_args(c, profile=profile, is_scoped=is_scoped, label=label):
            args = {"sketch_name": profile, "component": _REVOLVE_HOST, "axis": "z",
                    "operation": "cut", "angle_deg": 360}
            if label == "scoped":
                args["profile_index"] = "0"
            elif label == "unscoped":
                args["profile_index"] = _ctx_get(c, "revolve_selected_profile", "current profile")
            if is_scoped:
                args["target_bodies"] = [_REVOLVE_HOST + ":Body1"]
            return _revolve_pin(c, args)

        rows += [
            ("sketch_get", {"sketch_name": profile, "component": _REVOLVE_OCCURRENCE},
             lambda p: p.get("profile_count") == len(p.get("profiles") or []) == 1
             and bool(p["profiles"][0].get("handle")),
             ("revolve_selected_profile", lambda p: p["profiles"][0]["handle"])),
            ("model_revolve", cut_args,
             _revolve_cut(profile, feature, result_bodies, is_scoped, delta), None),
            ("model_inspect", {**_combine_inspect(_REVOLVE_OCCURRENCE), "per_body": True},
             _revolve_census(label, after), None),
        ]
        rows += _revolve_body_rows(label, after)
        if profile == "GrooveProfile":
            rows += [
                ("find_geometry", {"target": _REVOLVE_OCCURRENCE + ":Body1",
                                   "kind": "cylinder_face", "units": "mm", "max_results": 100},
                 _revolve_groove_face, None),
            ]
        rows += [
            ("design_delete_feature",
             lambda c, feature=feature: _revolve_pin(c, {"feature": feature}),
             _revolve_deleted(feature), None),
            ("model_inspect", {**_combine_inspect(_REVOLVE_OCCURRENCE), "per_body": True},
             _revolve_census(label + " restored", _REVOLVE_BASELINE), None),
        ]
        rows += _revolve_body_rows(label + " restored", _REVOLVE_BASELINE)
    rows += [
        ("doc_activate",
         lambda c: {"name": _ctx_get(c, "revolve_story", "the story document"),
                    "expect_document": _ctx_get(
                        c, "revolve_participant_doc", "the revolve scratch document")},
         "ok", None),
        ("doc_close",
         lambda c: {"name": _ctx_get(c, "revolve_participant_doc",
                                     "the revolve scratch document"),
                    "save_changes": False,
                    "expect_document": _ctx_get(c, "revolve_story", "the story document")},
         _document_closed, None),
        ("doc_get", {}, _revolve_story_restored, None),
    ]
    return rows


_REVOLVE_PARTICIPANTS = _revolve_participant_rows()
