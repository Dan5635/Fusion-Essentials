# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The live sweep's own program tables and placement: producers, dependencies and layout agree."""

import sys
import pytest

from conftest import load_tool_verify as _load_verify


class TestToolVerifyProgram:
    def test_base_feature_story_captures_family_handle_before_opening_scratch(self, monkeypatch):
        f = _load_verify()
        monkeypatch.setitem(sys.modules, "tool_verify", f)
        mesh = sys.modules["verify_acts_mesh"]
        monkeypatch.setitem(mesh._RECALL, "bf_story_doc", None)
        monkeypatch.setitem(mesh._RECALL, "a8_duplicate_doc", None)
        current = {"handle": "session:family"}
        calls = []
        def call(tool, args):
            calls.append((tool, args))
            if tool == "doc_get":
                row = {"name": "Untitled", "document_handle": current["handle"],
                       "is_active": True, "has_data_file": False, "is_saved": False}
                return False, {"active": row, "open_documents": [row], "open_count": 1}
            assert tool == "doc_new"
            assert args["expect_document"] == "session:family"
            current["handle"] = "session:duplicate"
            return False, {"created": True, "is_active": True, "document_name": "Untitled",
                           "document_handle": current["handle"]}
        monkeypatch.setattr(f, "call", call)
        rows = mesh._a8_duplicate_rows()
        ctx = {}
        result = f.run_steps(rows[:2], ctx, sleep_s=0, stop_on_failure=True)
        assert [row[1] for row in result] == ["pass", "pass"]
        assert calls[0][0] == "doc_get"
        assert ctx["bf_story_doc"] == mesh._RECALL["bf_story_doc"] == "session:family"
        assert ctx["a8_duplicate_doc"] == "session:duplicate"
        ctx["a8_captured_doc"] = "session:captured"
        assert rows[-3][1](ctx)["name"] == "session:family"
        assert rows[-2][1](ctx)["expect_document"] == "session:family"
        assert rows[-1][1](ctx)["expect_document"] == "session:family"

    @pytest.mark.parametrize("marker", ["absent", None, False, True, -1, 3])
    def test_a8_duplicate_marker_must_read_in_range(self, monkeypatch, marker):
        _load_verify()
        mesh = sys.modules["verify_acts_mesh"]
        payload = {"mode_detail": {"design_type": "parametric", "has_timeline": True,
                    "timeline_feature_count": 2, "base_feature_count": 2},
                   "timeline": {"count": 2, "returned": 2,
                    "timeline": [{"index": i, "name": "Shared", "component": owner,
                                  "type": "BaseFeature"}
                                 for i, owner in enumerate(["Left", "Right"])]}}
        if marker != "absent":
            payload["timeline"]["marker_position"] = marker
        monkeypatch.setitem(mesh._RECALL, "a8_duplicate_name", "Shared")
        with pytest.raises(AssertionError):
            mesh._a8_duplicate_baseline(payload)
        with pytest.raises(AssertionError):
            mesh._a8_snapshot(payload)

    @pytest.mark.parametrize("index,marker", [(0, 1), (999, 1), (0, 999), (0, 0)])
    def test_a8_captured_actual_read_requires_index_and_end_marker(self, monkeypatch, index, marker):
        _load_verify()
        mesh = sys.modules["verify_acts_mesh"]
        before = {"mode_detail": {"design_type": "parametric", "has_timeline": True,
                   "timeline_feature_count": 0, "base_feature_count": 0},
                  "timeline": {"count": 0, "returned": 0, "marker_position": 0, "timeline": []}}
        assert mesh._a8_captured_baseline(before) is True
        monkeypatch.setitem(mesh._RECALL, "a8_captured_before", mesh._a8_snapshot(before))
        monkeypatch.setitem(mesh._RECALL, "a8_captured_name", "Captured")
        after = {"mode_detail": {"design_type": "parametric", "has_timeline": True,
                  "timeline_feature_count": 1, "base_feature_count": 1},
                 "timeline": {"count": 1, "returned": 1, "marker_position": marker,
                  "timeline": [{"index": index, "name": "Captured", "component": "Root",
                                "type": "BaseFeature"}]}}
        predicate = mesh._a8_duplicate_rows()[19][2].expect
        if (index, marker) == (0, 1):
            assert predicate(after) is True
        else:
            with pytest.raises(AssertionError):
                predicate(after)

    @pytest.mark.parametrize("field,value", [
        ("closed_scopes", None), ("closed_scopes", []),
        ("closed_scopes", [{"name": "Other", "finished": True}]),
        ("closed_scopes", [{"name": "Captured", "finished": False}]),
        ("closed_scopes", [{"name": "Captured", "finished": True}] * 2),
        ("named_finished", "Other"), ("named_finished", None),
        ("editing", True), ("editing", None)])
    def test_a8_actual_finish_row_requires_exact_retained_closure(self, monkeypatch, field, value):
        _load_verify()
        mesh = sys.modules["verify_acts_mesh"]
        monkeypatch.setitem(mesh._RECALL, "a8_captured_name", "Captured")
        predicate = mesh._a8_duplicate_rows()[18][2]
        good = {"editing": False, "named_finished": "Captured",
                "closed_scopes": [{"name": "Captured", "finished": True}]}
        assert predicate(good) is True
        wrong = {**good, field: value}
        with pytest.raises(AssertionError):
            predicate(wrong)
        wrong = dict(good)
        del wrong[field]
        with pytest.raises(AssertionError):
            predicate(wrong)

    @pytest.mark.parametrize("changed", ["marker", "owner", "truncated", "type"])
    def test_duplicate_base_feature_witness_rejects_changed_independent_state(self, monkeypatch, changed):
        import copy
        _load_verify()
        mesh = sys.modules["verify_acts_mesh"]
        payload = {"mode_detail": {"design_type": "parametric", "has_timeline": True,
                    "timeline_feature_count": 2, "base_feature_count": 2},
                   "timeline": {"count": 2, "returned": 2, "marker_position": 2,
                    "timeline": [{"index": index, "name": "Shared", "component": owner,
                                  "type": "BaseFeature"}
                                 for index, owner in enumerate(["Left", "Right"])]}}
        monkeypatch.setitem(mesh._RECALL, "a8_duplicate_name", "Shared")
        assert mesh._a8_duplicate_baseline(payload) is True
        monkeypatch.setitem(mesh._RECALL, "a8_duplicate_before", mesh._a8_snapshot(payload))
        assert mesh._a8_unchanged(payload) is True
        wrong = copy.deepcopy(payload)
        if changed == "marker":
            wrong["timeline"]["marker_position"] = 1
        elif changed == "truncated":
            wrong["timeline"]["truncated"] = True
        else:
            wrong["timeline"]["timeline"][1]["component" if changed == "owner" else "type"] = (
                "Left" if changed == "owner" else "ExtrudeFeature")
        with pytest.raises(AssertionError):
            mesh._a8_unchanged(wrong)
        if changed != "marker":
            with pytest.raises(AssertionError):
                mesh._a8_duplicate_baseline(wrong)

    @pytest.mark.parametrize("capture", [0, 1, 2])
    def test_partial_edit_native_baselines_are_saved_through_real_runner(self, monkeypatch, capture):
        f = _load_verify()
        monkeypatch.setitem(sys.modules, "tool_verify", f)
        cam = sys.modules["verify_acts_cam"]
        rows = [r for r in cam._PARTIAL_EDIT_ROWS if r[0] == "sys_execute_script" and r[3] is not None]
        params = ({"multiAxisMachiningType":("'three_axis'", "three_axis"),
                   "toolAxisMode":(cam._DR_DERIVED,"vertical"), "tiltTool":("false",False),
                   "useShaftAndHolder":("tiltTool",False), "tiltToolMode":("derived","automatic")},
                  {"roughingType":("'offset'","offset"), "stepover":("tool_diameter * 0.5",0.6)},
                  {"multiAxisMachiningType":("'five_axis'","five_axis"),
                   "toolAxisMode":(cam._DR_DERIVED,"vertical"),"tiltToolMode":("derived","automatic")})
        payload = {"id":3,"operation":(cam._PE_OP,cam._MD_OP,cam._DR_OP)[capture],
                   "has_error":capture == 1,"tool_sha256":"a"*64,
                   "parameters":{n:{"expression":e,"value":v,"error":"","enabled":True,"editable":True}
                                 for n,(e,v) in params[capture].items()},
                   "value":"vertical","expression":cam._DR_DERIVED,"tilt":"automatic","error":""}
        monkeypatch.setattr(f,"call",lambda tool,args:(False,payload))
        key = ("partial_edit_before","partial_mode_before","derived_edit_before")[capture]
        monkeypatch.setitem(cam._RECALL,key,None)
        ctx = {}
        result = f.run_steps([rows[capture]],ctx,sleep_s=0)
        assert result[0][1] == "pass"
        assert ctx[key] == cam._RECALL[key] == payload

    def test_partial_edit_restore_requires_identity_flags_values_and_exact_other_expressions(self, monkeypatch):
        import copy
        _load_verify()
        cam = sys.modules["verify_acts_cam"]
        def row(expression, value):
            return {"expression":expression,"value":value,"error":"","enabled":False,"editable":False}
        before = {"id":3,"operation":cam._PE_OP,"tool_sha256":"a"*64,"has_error":False,
                  "parameters":{
                      "multiAxisMachiningType":row("'three_axis'","three_axis"),
                      "toolAxisMode":row(cam._DR_DERIVED,"vertical"),
                      "tiltTool":row("false",False),"useShaftAndHolder":row("tiltTool",False),
                      "tiltToolMode":row("derived","automatic")}}
        monkeypatch.setitem(cam._RECALL,"partial_edit_before",before)
        after = copy.deepcopy(before)
        after["parameters"]["toolAxisMode"]["expression"] = "'vertical'"
        assert cam._partial_compound_restored(after)
        for key,value in (("id",4),("tool_sha256","b"*64),("operation","Other"),("has_error",True)):
            bad = copy.deepcopy(after); bad[key] = value
            with pytest.raises(AssertionError):
                cam._partial_compound_restored(bad)
        for key,value in (("value",True),("expression","true"),("enabled",None),("error","invalid")):
            bad = copy.deepcopy(after); bad["parameters"]["tiltTool"][key] = value
            with pytest.raises(AssertionError):
                cam._partial_compound_restored(bad)
        bad = copy.deepcopy(after); del bad["parameters"]["toolAxisMode"]
        with pytest.raises(AssertionError):
            cam._partial_compound_restored(bad)

    def test_partial_existing_error_control_requires_changed_stepover_and_exact_restore(self, monkeypatch):
        import copy
        _load_verify()
        cam = sys.modules["verify_acts_cam"]
        before = {"id":5,"operation":cam._MD_OP,"tool_sha256":"a"*64,"has_error":True,
                  "parameters":{
                      "roughingType":{"expression":"'offset'","value":"offset","error":"","enabled":True,"editable":True},
                      "stepover":{"expression":"tool_diameter * 0.5","value":0.6,"error":"","enabled":True,"editable":True}}}
        monkeypatch.setitem(cam._RECALL,"partial_mode_before",before)
        after = copy.deepcopy(before)
        after["parameters"]["stepover"].update(expression="2.4 mm",value=0.24)
        assert cam._partial_existing_error_read(after)
        assert cam._partial_existing_error_read(before,restored=True)
        for key,value in (("value",0.6),("expression","tool_diameter * 0.5"),("error","bad")):
            bad = copy.deepcopy(after); bad["parameters"]["stepover"][key] = value
            with pytest.raises(AssertionError):
                cam._partial_existing_error_read(bad)
        with pytest.raises(AssertionError):
            cam._partial_existing_error_read(after,restored=True)

    def test_nested_insertion_witness_requires_the_frame_limit(self):
        _load_verify()
        cloud = sys.modules["verify_acts_cloud"]
        payload = {"is_reference": True, "new_occurrence_name": "Part:1"}
        phrases = ["placed_at is in the host component's frame",
                   "world placements are unconfirmed", "read each path with assembly_get"]
        assert cloud._cr_insert_landed({**payload, "note": "; ".join(phrases)}, nested=True)
        assert cloud._cr_insert_landed(payload)
        for missing in phrases:
            with pytest.raises(AssertionError):
                cloud._cr_insert_landed({**payload, "note": "; ".join(
                    phrase for phrase in phrases if phrase != missing)}, nested=True)

    def test_later_copy_feature_requires_its_independent_root_solid(self):
        _load_verify()
        motion = sys.modules["verify_acts_motion"]
        root = {"occurrence": None, "is_solid": True, "volume": 160}
        mass = {"units": "mm", "accuracy": "very_high", "per_body_truncated": False}
        assert motion._after_copy_feature_landed({"mass": {**mass, "per_body": [root]}})
        for rows in ([], [{**root, "occurrence": "Existing:1"}],
                     [{"is_solid": True, "volume": 160}], [{**root, "volume": 0}]):
            with pytest.raises(AssertionError, match="later feature added its own"):
                motion._after_copy_feature_landed({"mass": {**mass, "per_body": rows}})

    def test_matching_fixture_is_not_republished(self, monkeypatch, tmp_path):
        verify = _load_verify().verify_core
        path = tmp_path / "fixture.svg"
        original = b"<svg>unchanged</svg>"
        path.write_bytes(original)

        def unexpected_publish(*args, **kwargs):
            raise AssertionError("an identical fixture was opened for publication")

        monkeypatch.setattr(verify.tempfile, "NamedTemporaryFile", unexpected_publish)
        monkeypatch.setattr(verify.os, "replace", unexpected_publish)
        assert verify._write_fixture(str(path), original) == str(path)
        assert path.read_bytes() == original

    def test_changed_fixture_stays_complete_until_atomic_publication(self, monkeypatch, tmp_path):
        verify = _load_verify().verify_core
        path = tmp_path / "fixture.svg"
        original, changed = b"<svg>old complete</svg>", b"<svg>new complete</svg>"
        path.write_bytes(original)
        real_replace = verify.os.replace
        published = []

        def inspect_publish(source, target):
            from pathlib import Path
            assert path.read_bytes() == original
            assert Path(source).read_bytes() == changed
            assert str(target) == str(path)
            published.append(source)
            real_replace(source, target)

        monkeypatch.setattr(verify.os, "replace", inspect_publish)
        assert verify._write_fixture(str(path), changed) == str(path)
        assert len(published) == 1
        assert path.read_bytes() == changed
        assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]

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


def test_family_case_helpers_retain_the_owned_document_and_reject_another(monkeypatch):
    _load_verify()
    import verify_acts_sketch as sketch
    rows, write, read, close = sketch._family_rows("case_doc")
    monkeypatch.setitem(sketch._RECALL, "case_doc", "session:owned")
    write("sketch_create", {"name": "OneCase", "plane": "xy"})
    read("sketch_get", {"sketch_name": "OneCase"}, "ok")
    close()
    assert not {"doc_new", "doc_close", "doc_activate"} & {row[0] for row in rows}
    args = next(row[1] for row in rows if row[0] == "sketch_create")
    assert args({"case_doc": "session:owned"})["expect_document"] == "session:owned"
    owned = {"name": "Owned", "document_handle": "session:owned", "has_data_file": False}
    census = {"active": owned, "open_count": 1,
              "open_documents": [dict(owned, is_active=True)]}
    assert rows[-1][2](census)
    wrong = dict(owned, document_handle="session:other")
    with pytest.raises(AssertionError, match="owned family document unchanged"):
        rows[-1][2](dict(census, active=wrong,
                        open_documents=[dict(wrong, is_active=True)]))


def test_fff_and_appearance_families_have_no_authored_document_lifecycle():
    _load_verify()
    import verify_acts_doc as doc
    import verify_acts_hub as hub
    import verify_acts_sketch as sketch
    for rows in (hub._FFF_EXPORT, doc._SMALL_EDITS, sketch._paging_rows(),
                 sketch._anchor_retention_rows(), sketch._pattern_preflight_rows()):
        assert not {"doc_new", "doc_close", "doc_activate"} & {row[0] for row in rows}
    rows = doc._appearance_library_rows()
    targets = [row[1]({"ap_body": "Body1"})["target"]
               for row in rows if row[0] == "model_inspect"]
    assert "AppearanceLibraryCoupon:1:Body1" in targets
    assert targets.count("EditTarget:1") == 2
    assert targets.count("EditTarget:1:Body1") == 2


def test_joined_mirror_witness_rejects_separate_bodies_with_the_same_total_mass(monkeypatch):
    _load_verify()
    import verify_acts_feature_edit as edits
    key = "mirror_volume_guard"
    monkeypatch.setitem(edits._RECALL, key, None)

    def payload(volumes):
        return {"units": "mm", "min_point": {"x": -12, "y": 0, "z": 0},
                "max_point": {"x": 107, "y": 8, "z": 6},
                "mass": {"accuracy_used": "very_high", "volume": sum(volumes),
                         "center_of_mass": [8, 4, 3], "per_body_truncated": False,
                         "per_body_count": len(volumes),
                         "per_body": [{"body": f"Body{i}", "is_solid": True,
                                       "lump_count": 1, "volume": volume}
                                      for i, volume in enumerate(volumes)]}}

    predicate = edits._shape_capture(key, "joined mirror", [105, 1152])
    assert predicate(payload([105, 1152]))
    with pytest.raises(AssertionError, match="independent body census"):
        predicate(payload([105, 576, 576]))


def test_thread_material_witness_rejects_unchanged_or_unread_material(monkeypatch):
    _load_verify()
    import verify_acts_model_details as details
    key = "thread_material_witness"

    def payload(volume, accuracy="very_high"):
        return {"units": "mm", "min_point": {"x": 0, "y": 0, "z": 0},
                "max_point": {"x": 10, "y": 10, "z": 25},
                "mass": {"volume": volume, "center_of_mass": [5, 5, 12.5],
                         "accuracy_used": accuracy}}

    monkeypatch.setitem(details._RECALL, key, details._thread_body_facts(payload(1900)))
    predicate = details._thread_material_cut(key)
    assert predicate(payload(1700))
    assert predicate(payload(1899.98))
    for wrong in (payload(1900), payload(1899.99), payload(1899.999), payload(0),
                  payload(1700, "low"), {}):
        with pytest.raises(AssertionError, match="independently read material"):
            predicate(wrong)
    for baseline in (payload(1900, "low"), {}):
        facts = details._thread_body_facts(baseline)
        assert facts is None
        monkeypatch.setitem(details._RECALL, key, facts)
        with pytest.raises(AssertionError, match="independently read material"):
            predicate(payload(1700))
    for bank in ("thread_right_before", "thread_material_before", "thread_control_before"):
        row = next(row for row in details._DETAILS if row[3] and row[3][0] == bank)
        monkeypatch.setitem(details._RECALL, bank, None)
        for baseline in (payload(1900, "low"), {}):
            assert row[2](baseline) is False
            assert row[3][1](baseline) is None
            assert details._RECALL[bank] is None
        assert row[2](payload(1900)) is True
        assert row[3][1](payload(1900)) == details._thread_body_facts(payload(1900))
