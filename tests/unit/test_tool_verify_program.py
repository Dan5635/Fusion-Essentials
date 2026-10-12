# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The live sweep's own program tables and placement: producers, dependencies and layout agree."""

import sys

from conftest import load_tool_verify as _load_verify


class TestToolVerifyProgram:
    def test_authored_act_dependencies_and_producer_saves_are_complete(self):
        verify = _load_verify()
        acts = {row[0] for row in verify.ACTS}
        families = set(verify.FAMILY_PROGRAM.values())
        assert set(verify.ACT_DEPENDENCIES) == acts
        assert set(verify.FAMILY_DEPENDENCIES) == families
        assert set(verify.PRODUCER_ROWS) == set(verify.PRODUCER_SLOTS)
        assert set(verify.ACT_PRODUCER_OVERRIDES) <= acts

        unknown = sorted({producer for row in verify.ACT_DEPENDENCIES.values()
                          for producer in row["producers"]} - set(verify.PRODUCER_ROWS))
        families = sys.modules["verify_families"]
        assert set(families.ACT_PRODUCER_CONDITIONAL_OVERRIDES) <= acts
        known_gates = set(verify.ACT_NEEDS.values())
        unknown_gates = sorted({gate for rows in
                                families.ACT_PRODUCER_CONDITIONAL_OVERRIDES.values()
                                for gate in rows} - known_gates)
        assert not unknown_gates
        unknown.extend(sorted({producer for row in families.ACT_PRODUCER_CONDITIONAL_OVERRIDES.values()
                               for producers in row.values() for producer in producers}
                              - set(verify.PRODUCER_ROWS)))
        assert not unknown
        missing_saves = {}
        for producer, slots in verify.PRODUCER_SLOTS.items():
            saved = {row[3][0] for row in verify.PRODUCER_ROWS[producer]
                     if len(row) > 3 and isinstance(row[3], tuple)
                     and row[3] and isinstance(row[3][0], str)}
            absent = sorted(set(slots) - saved)
            if absent:
                missing_saves[producer] = absent
        assert not missing_saves
        for name, row in verify.ACT_DEPENDENCIES.items():
            assert row["conditional_producers"] == \
                families.ACT_PRODUCER_CONDITIONAL_OVERRIDES.get(name, {})
            assert row["entitlement"] == verify.ACT_NEEDS.get(name)
            assert row["generation"] == verify.POLL_AFTER.get(name)

    def test_family_producer_rows_match_local_fixture_steps(self):
        verify = _load_verify()
        families = sys.modules["verify_families"]
        drift = {}
        for family, dependency in verify.FAMILY_DEPENDENCIES.items():
            expected = [step for producer in dependency["producers"]
                        for step in verify.PRODUCER_ROWS[producer]]
            actual = families.fixture_steps(family, raw=True)
            if actual != expected:
                drift[family] = {"expected": [row[0] for row in expected],
                                 "actual": [row[0] for row in actual]}
        assert not drift, f"family producer declarations differ from fixture steps: {drift}"

    def test_conditional_act_producers_match_entitled_fixture_steps(self):
        verify = _load_verify()
        families = sys.modules["verify_families"]
        drift = {}
        for act, gates in families.ACT_PRODUCER_CONDITIONAL_OVERRIDES.items():
            family = verify.FAMILY_PROGRAM[act]
            if len(gates) != 1:
                drift[(act, "gate-count")] = sorted(gates)
                continue
            for entitled in (False, True):
                expected_producers = list(families.ACT_PRODUCER_OVERRIDES.get(act, ()))
                if entitled:
                    expected_producers.extend(next(iter(gates.values())))
                expected = [row for producer in expected_producers
                            for row in verify.PRODUCER_ROWS[producer]]
                actual = [row for row in families.fixture_steps(
                    family, before_act=act, entitled=entitled, raw=True)
                          if row[0] != "view_switch_workspace"]
                if actual != expected:
                    drift[(act, entitled)] = {"expected": [row[0] for row in expected],
                                              "actual": [row[0] for row in actual]}
        assert not drift, f"conditional producer declarations differ from fixture steps: {drift}"


def _families(verify):
    """Return authored acts grouped by their owned document."""
    return {family: [act for act in verify._ACT_PROGRAM
                     if verify.FAMILY_PROGRAM[act[0]] == family]
            for family in set(verify.FAMILY_PROGRAM.values())}


def _footprints(verify, program, steps_of):
    """Return chunk footprints for one owned document."""
    box = {}
    for name, _pre, narr, _fb in program:
        for step, chunk, _cursor, frame in verify._place_walk(steps_of(narr)):
            args = step[1]
            if chunk is None or not isinstance(args, dict):
                continue
            for x, y in verify._place_points(args, frame, step[0]):
                b = box.setdefault(chunk, [None, None, None, None])
                if x is not None:
                    b[0] = x if b[0] is None else min(b[0], x)
                    b[1] = x if b[1] is None else max(b[1], x)
                if y is not None:
                    b[2] = y if b[2] is None else min(b[2], y)
                    b[3] = y if b[3] is None else max(b[3], y)
    return {c: [v if v is not None else 0.0 for v in b] for c, b in box.items()}


def _hits(a, b):
    return a[0] <= b[1] and b[0] <= a[1] and a[2] <= b[3] and b[2] <= a[3]


class TestToolVerifyLayout:
    """Check each owned document's authored layout and camera references."""

    def test_coordinate_makers_have_a_readable_placement(self):
        verify = _load_verify()
        missing = []
        for name, _pre, narrative, fallback in verify._ACT_PROGRAM:
            for lane, steps in (("narrative", narrative), ("fallback", fallback or [])):
                for step, _chunk, _cursor, frame in verify._place_walk(steps):
                    tool, args, expect, _save = step
                    expect = verify._unparked(expect)
                    deliberate_refusal = isinstance(expect, verify._Refusal) or expect == "refused"
                    if (tool not in ("sketch_add_geometry", "sketch_add_3d_line")
                            or callable(args) or deliberate_refusal):
                        continue
                    if not isinstance(args, dict) or not verify._place_points(args, "xy", tool):
                        missing.append(f"{name} {lane}: {tool}")
        assert not missing, (
            "successful literal sketch geometry steps have no placement coordinate understood by "
            "verify_layout._place_points:\n  " + "\n  ".join(missing))

    def test_no_two_placed_chunks_share_ground(self):
        # Joint partners intentionally share ground; independent chunks do not.
        verify = _load_verify()
        fam = verify._JOINT_FAMILY
        clashes = []
        for family, program in _families(verify).items():
            box = _footprints(verify, program,
                              lambda narr: verify._placed(narr, verify._SLOTS))
            placed = sorted((c, b) for c, b in box.items() if c in verify._SLOTS)
            clashes.extend(f"{family}: {a} {box[a]} overlaps {b} {box[b]}"
                           for i, (a, _ba) in enumerate(placed)
                           for b, _bb in placed[i + 1:]
                           if _hits(box[a], box[b])
                           and not (a in fam and fam[a] == fam.get(b)))
        assert not clashes, (
            "independent authored chunks overlap, so a frame on one shows the other:\n  "
            + "\n  ".join(clashes))

    def test_no_placed_chunk_lands_on_a_pinned_one(self):
        # measured against the pinned chunks' own footprints, not against the pin constant - the
        # bracket, the vise and the CAM stock are what a stray cell would actually land on.
        verify = _load_verify()
        clashes = []
        saw_pinned = False
        for family, program in _families(verify).items():
            box = _footprints(verify, program,
                              lambda narr: verify._placed(narr, verify._SLOTS))
            pinned = {c: b for c, b in box.items() if c not in verify._SLOTS}
            saw_pinned |= bool(pinned)
            clashes.extend(f"{family}: {c} {b} lands on pinned {p} {pinned[p]}"
                           for c, b in sorted(box.items()) if c in verify._SLOTS
                           for p in sorted(pinned) if _hits(b, pinned[p]))
        assert saw_pinned, "no chunk is pinned - the origin world would be free to wander"
        assert not clashes, (
            "placed chunks land on the origin world, where the bracket, the vise and the CAM "
            "stock live and cannot move:\n  " + "\n  ".join(clashes))

    def test_chunks_that_address_each_other_stay_together(self):
        # the failure this catches is silent and green: two sketches whose solids must overlap (the
        # combine pair) drift apart, the combine still runs, and it joins nothing.
        verify = _load_verify()
        split = []
        for family, program in _families(verify).items():
            authored = _footprints(verify, program, lambda narr: narr)
            for name, _pre, narr, _fb in program:
                for _step, chunk, cursor, _frame in verify._place_walk(narr):
                    if not chunk or not cursor or chunk == cursor:
                        continue
                    if chunk not in authored or cursor not in authored:
                        continue
                    if not _hits(authored[chunk], authored[cursor]):
                        continue
                    if verify._SLOTS.get(chunk, (0, 0)) != verify._SLOTS.get(cursor, (0, 0)):
                        split.append(f"{family}/{name}: {cursor} and {chunk} move apart")
        assert not split, (
            "chunks that share ground and address each other were placed in different cells:\n  "
            + "\n  ".join(sorted(set(split))))

    def test_no_frame_names_an_entity_the_story_already_deleted(self):
        # view_set REFUSES a focus it cannot resolve, so a camera row aimed at something a later
        # act deleted is a hard failure - and one that only shows up live, after three minutes of
        # run.
        verify = _load_verify()
        offenders = []
        for family, program in _families(verify).items():
            gone = {}
            for name, _pre, narr, _fb in program:
                for step in narr:
                    args = step[1] if isinstance(step[1], dict) else {}
                    if step[0] == "design_delete_occurrence" and isinstance(args.get("occurrence"), str):
                        gone.setdefault(args["occurrence"], name)
                    if step[0] == "view_set" and args.get("focus"):
                        focus = args["focus"]
                        for nm in (focus if isinstance(focus, list) else [focus]):
                            if nm in gone:
                                offenders.append(
                                    f"{family}/{name}: frames '{nm}', deleted in {gone[nm]}")
        assert not offenders, (
            "camera rows name entities the story has already deleted - view_set refuses a focus it "
            "cannot resolve:\n  " + "\n  ".join(offenders))

    def test_placement_is_a_rigid_translation(self):
        # every position in a step moves by ONE offset: a shift that dropped or scaled a coordinate
        # would leave the chunk's internal geometry - and its probe points - subtly wrong.
        verify = _load_verify()
        skewed = []
        for name, _pre, narr, _fb in verify._ACT_PROGRAM:
            moved = verify._placed(narr, verify._SLOTS)
            assert len(moved) == len(narr)
            frames = [f for _s, _c, _cur, f in verify._place_walk(narr)]
            for before, after, frame in zip(narr, moved, frames):
                if not isinstance(before[1], dict):
                    continue
                was = verify._place_points(before[1], frame, before[0])
                now = verify._place_points(after[1], frame, before[0])
                if len(was) != len(now):
                    skewed.append(f"{name}: {before[0]} lost a position in the move")
                    continue
                for axis, i in (("x", 0), ("y", 1)):
                    moves = {round(b[i] - a[i], 9) for a, b in zip(was, now)
                             if a[i] is not None and b[i] is not None}
                    if len(moves) > 1:
                        skewed.append(
                            f"{name}: {before[0]} moved its {axis} by {sorted(moves)}")
        assert not skewed, ("placement is not a pure translation:\n  " + "\n  ".join(skewed))
