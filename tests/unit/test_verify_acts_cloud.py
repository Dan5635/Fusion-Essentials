# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The cloud tier's value predicates - the ones whose failure mode is a GREEN row.

A cloud act's predicates are read on a run nobody watches, against an operator's real hub, so the
readings that must not pass are the ones pinned here: a folder tree that never looked where the
target sits reading as absence, a local cache path standing in for a lineage URN, and a partition
claimed off a call that cannot produce one of its buckets.
"""

import ast
import json
import os
from pathlib import Path
import re
import sys
from copy import deepcopy

import pytest

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TESTS_DIR, "live"))
import tool_verify  # noqa: E402
import verify_acts_cloud as acts  # noqa: E402
import verify_acts_sheet as sheet  # noqa: E402
import verify_acts_census as census  # noqa: E402


@pytest.mark.parametrize("fault", [None, "old_cell", "new_value", "missing_cell", "row_identity"])
def test_configuration_column_witness_checks_growth_and_retained_cells(monkeypatch, fault):
    rows = [{"name": "Configuration 1", "id": "first", "index": 1, "is_active": False},
            {"name": "B", "id": "second", "index": 2, "is_active": True}]
    old = {"table_id": "table", "active_configuration": "B", "configuration_count": 2,
           "configurations": rows,
           "columns": [{"title": "Part Number", "id": "old", "type": "ConfigurationPropertyColumn"}],
           "cell_count": 2, "cells": [
               {"row_id": r["id"], "column_id": "old", "kind": "ConfigurationPropertyCell",
                "value_unread": "no value field of this cell kind is read here"} for r in rows]}
    now = deepcopy(old)
    now["columns"].append({"title": "ProbeW", "id": "new", "type": "ConfigurationParameterColumn"})
    now["cells"].extend({"row_id": r["id"], "column_id": "new", "kind": "ConfigurationParameterCell",
                         "expression": "13 mm" if r["name"] == "B" else "10 mm"} for r in rows)
    now["cell_count"] = 4
    if fault == "old_cell":
        now["cells"][0]["value_unread"] = "changed"
    elif fault == "new_value":
        now["cells"][-1]["expression"] = "10 mm"
    elif fault == "missing_cell":
        now["cells"].pop()
        now["cell_count"] = 3
    elif fault == "row_identity":
        now["configurations"][0]["id"] = "other"
    monkeypatch.setitem(acts._RECALL, "configure_table", old)
    monkeypatch.setitem(acts._RECALL, "configure_legal_column", "new")
    check = next(s[2] for s in acts._configure_column_rows() if getattr(s[2], "__name__", "") == "legal_table")
    if fault:
        with pytest.raises(AssertionError):
            check({"configurations": now})
    else:
        assert check({"configurations": now}) is True


@pytest.mark.parametrize("fault", [None, "initial_identity", "polled_identity", "incomplete"])
def test_saved_derive_source_waits_for_its_exact_cloud_record(monkeypatch, fault):
    pending = {"file": {"name": "OwnedSource", "id": "urn:owned"},
               "location": {"parent_folder": {"path": acts.FOLDER}},
               "state": {"is_complete": False}}
    ready = deepcopy(pending)
    ready["state"]["is_complete"] = fault != "incomplete"
    if fault == "initial_identity":
        pending["file"]["id"] = "urn:other"
    elif fault == "polled_identity":
        ready["file"]["name"] = "OtherSource"
    monkeypatch.setitem(acts._RECALL, "source_ready", "urn:owned")
    monkeypatch.setattr(acts.time, "sleep", lambda _seconds: None)
    calls = []

    def call(tool, arguments):
        calls.append((tool, arguments))
        return False, ready

    monkeypatch.setattr(acts, "facade", lambda _name: call)
    check = acts._file_settled(acts.FOLDER, polls=2, file_key="source_ready", file_name="OwnedSource")
    if fault:
        with pytest.raises(AssertionError):
            check(pending)
    else:
        assert check(pending) is True
    assert calls == ([] if fault == "initial_identity" else [("data_get", {"file": "urn:owned"})])


@pytest.fixture
def owned_cleanup(monkeypatch):
    name = "SweepFitRefusal." + acts._STAMP
    record = {"file": {"id": "urn:owned", "name": name},
              "state": {"is_in_use": True, "is_complete": True}}
    story = {"data_get": "read", "data_delete_file": "delete"}
    calls = []
    replies = [(True, f"Delete failed for '{name}': 2 : InternalValidationError : res"),
               (False, deepcopy(record))]

    def call(tool, args):
        calls.append((tool, args))
        return replies.pop(0)

    monkeypatch.setattr(acts, "facade", lambda key: {"call": call, "STORY": story}[key])
    monkeypatch.setitem(acts._RECALL, "closed_cloud_delete_limits", [])
    row = acts._released_then_deleted(name, "fit")[-1]
    row[1]({"fit_urn": "urn:owned", "fit_home": "session:home"})
    return row, record, replies, calls, story


def test_owned_in_use_refusal_requires_retained_file_and_qualifies_receipt(owned_cleanup):
    row, record, _, calls, story = owned_cleanup
    assert row[2](record) is True
    assert calls == [("data_delete_file", {"document_id": "urn:owned", "confirm_name": record["file"]["name"],
                                          "expect_document": "session:home"}),
                     ("data_get", {"file": "urn:owned"})]
    assert "Successful-delete path on this coupon was not demonstrated" in story["data_get"]
    assert "urn:owned" in story["data_delete_file"]


@pytest.mark.parametrize("fault", ["other_file", "released", "other_error", "after_missing", "after_not_in_use"])
def test_owned_cleanup_does_not_excuse_other_failures(owned_cleanup, fault):
    row, record, replies, calls, story = owned_cleanup
    if fault == "other_file":
        record["file"]["id"] = "urn:other"
    elif fault == "released":
        record["state"]["is_in_use"] = False
    elif fault == "other_error":
        replies[0] = (True, "permission denied")
    elif fault == "after_missing":
        replies[1] = (True, "not found")
    else:
        replies[1][1]["state"]["is_in_use"] = False
    with pytest.raises(AssertionError):
        row[2](record)
    assert story == {"data_get": "read", "data_delete_file": "delete"}
    assert len([c for c in calls if c[0] == "data_delete_file"]) <= 1


def test_owned_cleanup_still_requires_verified_success_on_deleted_path(owned_cleanup):
    row, record, replies, _, story = owned_cleanup
    replies[:] = [(False, {"deleted": True, "name": record["file"]["name"], "document_id": "urn:owned",
                          "forced": False, "absence_observed": True})]
    assert row[2](record) is True
    assert story == {"data_get": "read", "data_delete_file": "delete"}


@pytest.fixture
def morph_status(monkeypatch):
    monkeypatch.setattr(census, "facade", lambda key: None)
    return {"completed": True, "target": "operation 'MorphPair'",
            "completion_basis": "operation 'MorphPair'", "elapsed_seconds": 2.3,
            "live_states": {"valid": 1, "total": 1, "errored": 0, "out_of_date": 0,
                            "generating": 0, "generating_settled": 0, "unread": 0, "nonfinite": 0},
            "counts": {"empty_toolpaths": 0}}


@pytest.mark.parametrize("fault", [None, "settled_flag", "unsettled_flag", "document_scope", "empty", "invalid", "unread_time"])
def test_morph_completion_requires_scoped_valid_nonempty_evidence(morph_status, fault):
    if fault == "settled_flag":
        morph_status["live_states"].update(generating=1, generating_settled=1)
    elif fault == "unsettled_flag":
        morph_status["live_states"]["generating"] = 1
    elif fault == "document_scope":
        morph_status["completion_basis"] = "document"
    elif fault == "empty":
        morph_status["counts"]["empty_toolpaths"] = 1
    elif fault == "invalid":
        morph_status["live_states"].update(valid=0, out_of_date=1)
    elif fault == "unread_time":
        morph_status["elapsed_seconds"] = None
    if fault in (None, "settled_flag"):
        assert census._morph_completed(morph_status) is True
    else:
        with pytest.raises(AssertionError):
            census._morph_completed(morph_status)


def _step(narrative, tool, nth=0):
    """The nth step driving `tool` in an act's narrative."""
    hits = [s for s in narrative if s[0] == tool]
    assert len(hits) > nth, f"{tool} has {len(hits)} step(s) in this act"
    return hits[nth]


class TestCappedNameMoveProbe:
    def test_generated_script_matches_python_run_contract_and_predicate_accepts_decoded_output(self):
        ctx = {"cloud_file_name": "owned.png", "cloud_file": "urn:owned",
               "data_root_summary": {"project_id": "project-id"}}
        script = acts._capped_name_move_probe(ctx)["script"]
        parsed = ast.parse(script)
        runs = [node for node in parsed.body
                if isinstance(node, ast.FunctionDef) and node.name == "run"]
        assert len(runs) == 1 and len(runs[0].args.args) == 1

        repo = Path(acts.__file__).parents[2]
        execute_source = ast.parse(
            (repo / "commands" / "mcpServer" / "tools" / "sys_execute_script.py")
            .read_text(encoding="utf-8"))
        handler = next(node for node in execute_source.body
                       if isinstance(node, ast.FunctionDef) and node.name == "handler")
        patterns = [ast.literal_eval(call.args[0]) for call in ast.walk(handler)
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name) and call.func.value.id == "re"
                    and call.func.attr == "search" and call.args]
        assert len(patterns) == 1 and re.search(patterns[0], script)

        result = {"file_name": "owned.png", "file_id": "urn:owned", "folder_id": "folder-id",
                  "file_count": 1, "child_folder_count": 1,
                  "before_parent_id": "folder-id", "after_refusal_parent_id": "folder-id",
                  "after_project_error_parent_id": "folder-id",
                  "after_exact_parent_id": "folder-id", "cap_restored": True,
                  "project_finder_restored": True,
                  "project_lookup_error_injected": True,
                  "capped_by_name": {"is_error": True,
                                     "payload": "name census is incomplete after the cap"},
                  "injected_project_error": {"is_error": True,
                      "payload": ("synthetic project lookup failure; "
                                  "data_get(project_id=<id>), then pass that id as 'file'.")},
                  "exact_urn": {"is_error": False, "payload": {"already_in_target": True}}}
        assert acts._capped_name_move_result(result) is True


@pytest.fixture
def sheet_home(monkeypatch):
    for key in ("sm_home", "sm_home_state", "sm_coupon", "sm_drawing_session"):
        monkeypatch.setitem(sheet._RECALL, key, None)
    return {"active": {"document_handle": "session:home", "name": "DrawSelection",
                       "document_id": "urn:owned-source", "has_data_file": True,
                       "is_saved": True, "is_modified": False},
            "open_count": 2, "truncated": False,
            "open_documents": [{"document_handle": "session:home", "name": "DrawSelection"},
                               {"document_handle": "session:witness", "name": "Untouched"}]}


class TestSheetOriginalHome:
    @pytest.mark.parametrize("saved", [True, False])
    def test_saved_or_unsaved_original_home_is_restored_exactly(self, sheet_home, saved):
        if not saved:
            sheet_home["active"].update(document_id=None, has_data_file=False, is_saved=False, is_modified=True)
        start = sheet._SHEET_BUILD[0]
        assert start[2](sheet_home) is True
        assert start[3][1](sheet_home) == "session:home"
        assert sheet._story_restored(deepcopy(sheet_home)) is True

    @pytest.mark.parametrize("field,value", [
        ("document_handle", "session:witness"), ("name", "Renamed"), ("document_id", "urn:other"),
        ("has_data_file", False), ("is_saved", False), ("is_modified", True)])
    def test_restore_rejects_changed_identity_or_save_state(self, sheet_home, field, value):
        start = sheet._SHEET_BUILD[0]
        start[2](sheet_home)
        start[3][1](sheet_home)
        restored = deepcopy(sheet_home)
        restored["active"][field] = value
        with pytest.raises(AssertionError, match="story session restored"):
            sheet._story_restored(restored)

    @pytest.mark.parametrize("value", [None, 0])
    def test_unread_or_nonboolean_flags_fail_capture_and_restore(self, sheet_home, value):
        start = sheet._SHEET_BUILD[0]
        start[2](sheet_home)
        start[3][1](sheet_home)
        unread = deepcopy(sheet_home)
        unread["active"]["is_modified"] = value
        with pytest.raises(AssertionError, match="story session restored"):
            sheet._story_restored(unread)
        with pytest.raises(AssertionError, match="story session before sheet coupon"):
            start[2](unread)

    @pytest.mark.parametrize("fault", ["lost_witness", "missing_row", "truncated", "coupon", "drawing"])
    def test_restore_requires_complete_census_and_closed_owned_documents(self, sheet_home, fault):
        start = sheet._SHEET_BUILD[0]
        start[2](sheet_home)
        start[3][1](sheet_home)
        restored = deepcopy(sheet_home)
        if fault in ("lost_witness", "missing_row"):
            restored["open_documents"].pop()
            if fault == "lost_witness":
                restored["open_count"] -= 1
        elif fault == "truncated":
            restored["truncated"] = True
        else:
            key = "sm_coupon" if fault == "coupon" else "sm_drawing_session"
            sheet._RECALL[key] = "session:" + fault
            restored["open_documents"].append({"document_handle": "session:" + fault, "name": fault})
            restored["open_count"] += 1
        with pytest.raises(AssertionError, match="story session restored"):
            sheet._story_restored(restored)


class TestMovedFileListingSettle:
    def test_parent_listing_lags_beyond_twelve_reads_then_excludes_child(self, monkeypatch):
        lineage = "urn:moved-file"
        monkeypatch.setitem(acts._RECALL, "cloud_file", lineage)
        stale = {"folder": acts.RUN_PATH, "recursive": False,
                 "files": [{"id": lineage}], "file_count": 1,
                 "truncated": False, "time_truncated": False, "folders_unreadable": False}
        empty = dict(stale, files=[], file_count=0)
        calls = []

        def reread(tool, arguments):
            calls.append((tool, arguments))
            return False, stale if len(calls) <= 13 else empty

        monkeypatch.setattr(acts, "facade", lambda name: reread)
        monkeypatch.setattr(acts.time, "sleep", lambda _: None)
        assert acts._known_child_excluded(stale) is True
        assert len(calls) == 14
        assert all(tool == "data_get" and args == {
            "project": acts.PROJECT, "folder": acts.RUN_PATH, "recursive": False}
            for tool, args in calls)

    def test_parent_listing_still_present_at_bound_fails(self, monkeypatch):
        lineage = "urn:moved-file"
        monkeypatch.setitem(acts._RECALL, "cloud_file", lineage)
        stale = {"folder": acts.RUN_PATH, "recursive": False,
                 "files": [{"id": lineage}], "file_count": 1,
                 "truncated": False, "time_truncated": False, "folders_unreadable": False}
        monkeypatch.setattr(acts, "facade", lambda name: lambda *args: (False, stale))
        monkeypatch.setattr(acts.time, "sleep", lambda _: None)
        with pytest.raises(AssertionError, match="run folder excludes"):
            acts._known_child_excluded(stale, polls=3)


class TestTheDeleteReceipt:
    """How the tier proves its folders are gone. MEASURED on a real project: a project-wide
    folder-tree read is over its 20-folder fetch budget at any depth that would reach these paths
    (105 folders, ~30 of them top-level), so it reports a cut walk on every run whatever the deletes
    did. The receipt addresses the run folder DIRECTLY instead, where a miss is a REFUSAL - which no
    budget cut can imitate."""

    def test_the_delete_receipt_is_a_scoped_miss_not_the_project_tree(self):
        tree_reads = [s for s in acts._CLOUD_DATA if s[0] == "data_get"
                      and isinstance(s[1], dict) and s[1].get("include") == ["folders"]]
        assert tree_reads == [], "the project-wide tree read cannot pass on a real project"
        last = [s for s in acts._CLOUD_DATA if s[0] != tool_verify._DWELL][-1]
        assert last[0] == "data_get" and last[1]["folder"] == acts.RUN_PATH
        assert "recursive" not in last[1] or last[1]["recursive"] is False
        for fragment in ("not found", "no subfolder", acts.RUN_FOLDER):
            assert fragment in last[2].fragments


class TestVersionsRead:
    """What settles and what lags are DIFFERENT KEYS in this slice, and only the settled ones are
    asserted: the version ROWS arrive with their count, the TIP NUMBER trails them."""

    # measured on cloud1, right after a doc_save_milestone that had already reported
    # cloud_tip_advanced true - the rows are there and the tip is one behind the saves made
    MEASURED = {"versions": {"available": True, "history_readable": True,
                             "latest_version_number": 2, "milestone_count": 0,
                             "version_count": 2, "versions": [{}, {}]}}
    # measured on the burn10 restamp: the SAME slice, the same two rows, and the tip a further
    # version behind. The rows are what settled; the number had not caught up yet.
    LAGGING_TIP = {"versions": dict(MEASURED["versions"], latest_version_number=1)}

    def test_both_measured_payloads_pass_on_their_rows(self):
        assert acts._versions_read(2)(self.MEASURED) is True
        assert acts._versions_read(2)(self.LAGGING_TIP) is True

    def test_a_lineage_short_of_the_rows_it_should_hold_fails(self):
        # the rows are the claim, so this is the boundary that matters: one version where the act
        # made two says a save did not land, which is not the metadata lagging.
        payload = {"versions": {"available": True, "history_readable": True,
                                "latest_version_number": 1, "milestone_count": 0,
                                "version_count": 1, "versions": [{}]}}
        with pytest.raises(AssertionError, match="version_count"):
            acts._versions_read(2)(payload)

    def test_a_count_disagreeing_with_the_rows_it_published_fails(self):
        # version_count is len() over the rows read, so the two cannot disagree - a payload where
        # they do is a slice that did not enumerate what it counted.
        payload = {"versions": dict(self.MEASURED["versions"], version_count=3)}
        with pytest.raises(AssertionError, match="version_count"):
            acts._versions_read(2)(payload)

    def test_an_unavailable_or_unreadable_history_fails(self):
        for key in ("available", "history_readable"):
            payload = {"versions": dict(self.MEASURED["versions"], **{key: False})}
            with pytest.raises(AssertionError):
                acts._versions_read(2)(payload)

    def test_the_tip_and_the_milestone_count_are_published_but_asserted_nowhere(self):
        # the milestone's own row proves the version it made; repeating the claim here would only
        # be asserting how fast the metadata caught up.
        try:
            acts._versions_read(9)(self.LAGGING_TIP)
        except AssertionError as e:
            assert "latest_version_number" in str(e) and "milestone_count" in str(e)
        else:
            raise AssertionError("expected the row-count floor to fail")


class TestTheRestoreBeat:
    """Promoting the LATEST version is a no-op the tool answers with an early return, so the beat
    has to name one the tip has moved past."""

    # doc_restore_version's early return: no promote call, no tip either side to compare
    EARLY = {"restored": False, "restored_version": 1, "latest_version_number": 1,
             "note": "Version 1 is already the latest version; nothing to restore."}
    PROMOTED = {"promote_call_returned_true": True, "restored": True, "restored_version": 1,
                "latest_before": 3, "latest_after": 4}

    def test_the_early_return_is_not_a_restore(self):
        with pytest.raises(AssertionError, match="promote_call_returned_true"):
            acts._restored(1)(self.EARLY)

    def test_a_real_promote_passes(self):
        assert acts._restored(1)(self.PROMOTED) is True

    def test_a_promote_of_another_version_fails(self):
        with pytest.raises(AssertionError):
            acts._restored(1)(dict(self.PROMOTED, restored_version=2))


class TestTheUrnRead:
    """Every lineage-URN capture goes through ONE shared read. The failure it exists for is silent
    where it is caused - the save reports saved and the right name - and only shows ten steps later,
    at an activate, a close and a delete that address a local path."""

    def test_the_capture_is_the_urn_asserting_read(self):
        steps = acts._settled("Doc", "doc_urn")
        assert len(steps) == 1
        read = steps[0]
        assert read[0] == "doc_get" and read[3][0] == "doc_urn"
        assert read[3][1]({"active": {"document_id": "urn:x"}}) == "urn:x"
        # ...and the read is the one that refuses a path
        with pytest.raises(AssertionError):
            read[2]({"active": {"name": "Doc", "has_data_file": True,
                                "document_id": "C:/tmp/Doc.f3d"}})

    def test_the_capture_spends_no_hold_of_its_own(self):
        # doc_save_as waits for the urn before it answers, up to the window a cloud read is
        # measured to trail in - so a dwell here would re-spend a wait the save already spent, and
        # _dwell's own contract is that it never guards a correctness step.
        assert not [s for s in acts._settled("Doc", "doc_urn") if s[0] == tool_verify._DWELL]

    def test_each_walk_after_a_document_switch_confirms_that_document_first(self):
        # MEASURED: the switch to the host was blocked, the walk ran against whatever was active and
        # reported total_references None - a walk aimed at one document reading another's refs. Two
        # walks follow a switch: the host's, and the derive host's after it is closed and reopened.
        tools = [s[0] for s in acts._CLOUD_DOC]
        confirmed = set()
        for i, tool in enumerate(tools):
            if tool != "doc_update_xref" or tools[i - 1] != "doc_get":
                continue
            for name in (acts.HOST_DOC, acts.DERIVE_DOC):
                # the confirming read RAISES on the wrong document, which is the behaviour being
                # asserted: only the name it was built for gets through.
                try:
                    acts._CLOUD_DOC[i - 1][2]({"active": {
                        "name": name, "has_data_file": True, "document_id": "urn:x"}})
                except AssertionError:
                    continue
                confirmed.add(name)
        assert confirmed == {acts.HOST_DOC, acts.DERIVE_DOC}


class TestTheSourceTipGate:
    """The derive leg's staleness depends on the CLOUD publishing the source's new version, which
    trails the save - so the row that proves the tip moved is the gate, not the dwell before it."""

    def _versions(self, latest):
        return {"versions": {"available": True, "history_readable": True,
                             "latest_version_number": latest, "version_count": latest}}

    def test_a_tip_that_moved_past_the_banked_number_passes(self):
        acts._RECALL["source_tip_before"] = 2
        assert acts._tip_advanced("source_tip_before")(self._versions(3)) is True

    def test_a_tip_STILL_AT_the_banked_number_fails(self):
        # the exact boundary, and the race itself: the save returned, the version metadata has not
        # caught up, and the derive would read 'already up to date' ten steps later.
        acts._RECALL["source_tip_before"] = 2
        with pytest.raises(AssertionError, match="tip_before"):
            acts._tip_advanced("source_tip_before")(self._versions(2))

    def test_a_tip_that_did_not_read_fails_rather_than_passing(self):
        acts._RECALL["source_tip_before"] = 2
        with pytest.raises(AssertionError):
            acts._tip_advanced("source_tip_before")({"versions": {"available": True}})


class TestFilesGone:
    """The file listing's THIRD way of not looking: a folder whose enumeration raised is counted,
    and 'truncated' stays false."""

    NAMES = ("SweepCloudSource x", "SweepCloudCopy x", "SweepCloudHost x",
             "SweepCloudDerive x", "SweepCloudLink x")

    def _payload(self, **over):
        base = {"file_count": 0, "files": [], "truncated": False, "time_truncated": False}
        base.update(over)
        return base

    def test_an_empty_listing_fully_read_is_the_files_gone(self):
        assert acts._files_gone(*self.NAMES)(self._payload()) is True

    def test_a_file_still_listed_fails(self):
        with pytest.raises(AssertionError, match="still_there"):
            acts._files_gone(*self.NAMES)(
                self._payload(file_count=1, files=[{"name": self.NAMES[0]}]))

    def test_a_folder_whose_enumeration_raised_fails_with_truncated_false(self):
        # the exact shape: the walk never opened one folder, published the count and WHERE, and left
        # 'truncated' false - a file of these names could be sitting in precisely that folder.
        with pytest.raises(AssertionError, match="folders_unreadable"):
            acts._files_gone(*self.NAMES)(
                self._payload(folders_unreadable=1, folders_unreadable_at=["Somewhere/Locked"]))

    def test_the_size_and_time_caps_still_fail(self):
        for flag in ("truncated", "time_truncated"):
            with pytest.raises(AssertionError, match=flag):
                acts._files_gone(*self.NAMES)(self._payload(**{flag: True}))

    def _witness(self):
        """The tier's closing folder read - the delete receipt standing apart from the deletes."""
        reads = [s for s in acts._CLOUD_DRAWING if s[0] == "data_get"
                 and isinstance(s[1], dict) and s[1].get("folder") == acts.FOLDER]
        assert len(reads) == 1
        return reads[0]

    def test_the_step_reads_the_configured_folder_ITSELF(self):
        # MEASURED: recursive over a working folder walks every run that ever used it - 49 files
        # across 30-odd subfolders, past the 20 s budget, which reds this row for the folder's size
        # rather than for a file left behind. The tier's documents sit in the folder itself.
        assert self._witness()[1].get("recursive") is False


class TestTheSavedDocumentUrn:
    """A saveAs holds a LOCAL cache path under document_id until the cloud id arrives, and the read
    that must refuse it is this one."""

    def test_a_saved_document_whose_urn_would_not_read_fails(self):
        # doc_get reads document_id through a guarded getter, so a read that raised publishes null.
        # Passing on the NAME alone hands None to every open, close and delete after it - the
        # teardown then leaves the run's documents standing in the operator's hub.
        with pytest.raises(AssertionError, match="document_id"):
            acts._document_is("SweepCloudSource x")(
                {"active": {"name": "SweepCloudSource x", "has_data_file": True,
                            "document_id": None}})
        assert acts._document_is("SweepCloudSource x")(
            {"active": {"name": "SweepCloudSource x", "has_data_file": True,
                        "document_id": "urn:adsk.wipprod:dm.lineage:abc"}}) is True

    # the payload a restamp MEASURED: the save reported saved, the name is right, has_data_file is
    # true - and document_id is the LOCAL cache path a saveAs holds until the cloud id arrives.
    UNSETTLED = {"active": {
        "name": "SweepCloudHost 20260907-090457", "has_data_file": True,
        "document_id": ("C:/Users/machinist/AppData/Local/Autodesk/Autodesk Fusion 360/100000000000001/"
                        "W.login/F/_SweepCloudHost 20260907-090457."
                        "66f87ddd-9eb6-4d2c-809a-4d26a7402bac.f3d")}}

    def test_the_measured_unsettled_save_fails_naming_the_path_it_saw(self):
        # This is the whole defect: nothing at the save is wrong, so the row that must catch it is
        # this one - and its evidence has to carry the path, or the diagnosis is ten steps away.
        with pytest.raises(AssertionError, match="document_id"):
            acts._document_is("SweepCloudHost 20260907-090457")(self.UNSETTLED)
        try:
            acts._document_is("SweepCloudHost 20260907-090457")(self.UNSETTLED)
        except AssertionError as e:
            assert ".f3d" in str(e) and "W.login" in str(e)

    def test_the_same_read_passes_once_the_urn_lands(self):
        settled = {"active": dict(self.UNSETTLED["active"],
                                  document_id="urn:adsk.wipprod:dm.lineage:abc")}
        assert acts._document_is("SweepCloudHost 20260907-090457")(settled) is True


class TestXrefPartition:
    """updated/skipped are only a partition where BOTH buckets can be reached."""

    SKIPPED = {"total_references": 1, "updated_count": 0, "updated": [],
               "skipped": [{"name": "Src", "reason": "already up to date"}]}
    UPDATED = {"total_references": 1, "updated_count": 1,
               "updated": [{"name": "Src", "was_out_of_date": True}], "skipped": []}

    def test_the_counts_this_beat_put_there_are_what_passes(self):
        assert acts._xrefs(1, 0, 1)(self.SKIPPED)
        assert acts._xrefs(1, 1, 0)(self.UPDATED)
        with pytest.raises(AssertionError):
            acts._xrefs(1, 0, 1)(self.UPDATED)

    def test_the_bucket_free_form_takes_either_and_still_partitions(self):
        # the walk straight after an insert: MEASURED, a just-inserted xref read out of date, so
        # which bucket it lands in is the cloud's business - the partition is still asserted.
        assert acts._xrefs(1)(self.SKIPPED) and acts._xrefs(1)(self.UPDATED)
        with pytest.raises(AssertionError):
            acts._xrefs(1)({"total_references": 2, "updated_count": 1,
                            "updated": [{"name": "Src"}], "skipped": []})

    def test_a_reference_in_NEITHER_bucket_fails(self):
        # total says one reference, both buckets are empty - it went somewhere the walk did not
        # report (doc_update_xref's third outcome is 'error'), and free-form must not read that as
        # a clean walk just because no count was demanded.
        with pytest.raises(AssertionError):
            acts._xrefs(1)({"total_references": 1, "updated_count": 0, "updated": [],
                            "skipped": []})

    def test_a_payload_missing_a_bucket_fails(self):
        # doc_update_xref's no-references early return publishes updated/updated_count and NOTHING
        # else - read as a partition it would say a host with no xref at all walked clean.
        with pytest.raises(AssertionError):
            acts._xrefs(1, 0, 1)({"updated_count": 0, "updated": []})
        with pytest.raises(AssertionError):
            acts._xrefs(1)({"updated_count": 0, "updated": []})

    def test_a_count_disagreeing_with_its_own_list_fails(self):
        with pytest.raises(AssertionError):
            acts._xrefs(1, 1, 0)({"total_references": 1, "updated_count": 1, "updated": [],
                                  "skipped": []})

    def test_every_walk_asks_for_only_out_of_date_and_each_bucket_is_claimed_once(self):
        # under only_out_of_date false NOTHING can land in 'skipped' - every reference is refreshed
        # whether it needed one or not - so the partition would be claimed off a branch that cannot
        # run. Four walks: one reporting, one pinning the SKIP, one pinning the UPDATE, and the
        # derive host's, which asserts a refusal instead of a bucket.
        walks = [s for s in acts._CLOUD_DOC if s[0] == "doc_update_xref"]
        assert len(walks) == 4
        assert all(s[1]["only_out_of_date"] is True for s in walks)
        assert walks[1][2](self.SKIPPED) and walks[2][2](self.UPDATED)
        with pytest.raises(AssertionError):
            walks[1][2](self.UPDATED)
        with pytest.raises(AssertionError):
            walks[2][2](self.SKIPPED)

    def test_the_derive_walk_asserts_the_refusal_and_not_a_bucket(self):
        # a stale DERIVE row's refresh raises (measured), so doc_update_xref errors naming the row
        # and the delete-and-re-derive remedy. Read as a partition this walk would demand buckets
        # the erroring call never publishes, and a bare 'refused' would pass on any failure - the
        # remedy fragment is what ties the row to the measurement.
        walk = [s for s in acts._CLOUD_DOC if s[0] == "doc_update_xref"][3]
        # rebuilt in the tool's OWN shape - the per-row error record doc_update_xref writes when the
        # version assignment raises, wrapped in the headline it returns - rather than paraphrased,
        # so a reworded remedy fails here instead of on the run.
        row = {"name": acts.SOURCE_DOC, "kind": "derive",
               "error": ("Fusion refused the refresh (RuntimeError: 2 : InternalValidationError : "
                         "res) - delete and re-derive (design_delete_feature, then "
                         "doc_insert_derive) to pick up the source's latest version.")}
        whole = f"Some references failed to update: {json.dumps([row])}. (Updated: 0.)"
        assert walk[2].missing(whole) == []
        # the remedy is a fragment in its OWN right: a call that failed for any other reason carries
        # the first two phrases and not the route out, and must not read as this measurement.
        assert walk[2].missing("Some references failed to update: Fusion refused the refresh") != []


class TestTheGuardedFolderDelete:
    """The non-empty refusal is pinned on the blast radius it measured, not on its shape."""

    def test_the_refusal_names_the_counts_the_preview_read(self):
        step = _step(acts._CLOUD_DATA, "data_delete_folder")
        fragments = step[2].fragments
        assert "is not empty" in fragments and "recursive_confirm" in fragments
        # the measured radius at that moment: no file directly in the run folder, one subfolder, and
        # one file plus one subfolder in the subtree below it
        assert "immediate files: 0, subfolders: 1" in fragments
        assert "1 file(s) and 1 subfolder(s) total" in fragments


class TestTheSharedRasterFixture:
    """One PNG writer, one stable path - a stamped fixture leaves a file per pytest run."""

    def test_the_marker_is_the_shared_fixture_and_its_path_carries_no_stamp(self):
        assert acts.MARKER_PNG is tool_verify.MARKER_PNG
        assert os.path.basename(acts.MARKER_PNG) == "sweep_marker.png"
        assert os.path.isfile(acts.MARKER_PNG)

    def test_the_writer_produces_a_png_both_harnesses_can_place(self, tmp_path):
        path = tool_verify.write_png(str(tmp_path / "x.png"), size=8)
        with open(path, "rb") as fh:
            head = fh.read(8)
        assert head == b"\x89PNG\r\n\x1a\n"
        assert os.path.getsize(path) > 0


@pytest.mark.parametrize("active", ["Configuration 1", "B"])
def test_reopened_lineage_table_accepts_either_active_row_but_requires_its_identities(active):
    table = {"table_id": "table-id", "configuration_count": 2, "active_configuration": active,
             "configurations": [{"name": name, "id": name + "-id", "is_active": name == active}
                                for name in ("Configuration 1", "B")],
             "columns": [{"id": "width-id", "title": "ProbeW", "type": "parameter"}], "truncated": False}
    step = next(row for row in acts._lineage_open_rows() if row[0] == "design_get")
    assert step[2]({"configurations": table}) is True
    missing_column = deepcopy(table)
    missing_column["columns"][0]["title"] = "Other"
    with pytest.raises(AssertionError):
        step[2]({"configurations": missing_column})
    missing_row = deepcopy(table)
    missing_row["configurations"].pop()
    with pytest.raises(AssertionError):
        step[2]({"configurations": missing_row})


@pytest.mark.parametrize("fault", [None, "wrong_record", "other_error", "timeout"])
def test_lineage_save_as_is_published_before_close_and_reopen(monkeypatch, fault):
    rows = acts._lineage_open_rows()
    publication = next(i for i, row in enumerate(rows) if getattr(row[2], "__name__", "") == "published")
    assert [row[0] for row in rows[publication - 2:publication]] == ["doc_save_as", "data_get"]
    assert rows[publication - 1][1]({"lin_inplace": "urn:source"}) == {"file": "urn:source"}
    assert [row[0] for row in rows[publication + 1:publication + 4]] == ["doc_activate", "doc_close", "doc_open"]
    name = "SweepLineageSaveAs." + acts._STAMP
    complete = {"file": {"id": "urn:owned", "name": name},
                "location": {"parent_folder": {"path": acts.FOLDER}}, "state": {"is_complete": True}}
    missing = ("No cloud file resolves from 'urn:owned'. Tried: urn:owned. "
               "Get a lineage URN from data_get(project=<name>) ('id' on each file).")
    replies = [(True, missing), (False, complete)]
    if fault == "wrong_record":
        complete["file"]["id"] = "urn:other"
    elif fault == "other_error":
        replies[0] = (True, "permission denied")
    elif fault == "timeout":
        replies[:] = [(True, missing)] * 3
    calls = []
    def call(tool, args):
        calls.append((tool, args))
        return replies.pop(0)
    monkeypatch.setitem(acts._RECALL, "lin_saveas", "urn:owned")
    monkeypatch.setattr(acts, "facade", lambda key: call)
    monkeypatch.setattr(acts.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(acts, "_SETTLE_POLLS", 3)
    start = {"active": {"name": name, "document_id": "urn:owned"}}
    if fault is None:
        assert rows[publication][2](start) is True
    else:
        with pytest.raises(AssertionError):
            rows[publication][2](start)
    assert len(calls) == (1 if fault == "other_error" else 3 if fault == "timeout" else 2)
    assert all(call == ("data_get", {"file": "urn:owned"}) for call in calls)


@pytest.mark.parametrize("fault", [None, "permission", "wrong_record", "timeout"])
def test_configured_source_wait_retries_only_the_exact_pending_lineage(monkeypatch, fault):
    rows = acts._lineage_open_rows()
    step = next(row for row in rows if getattr(row[2], "__name__", "") == "prior_backing")
    urn = "urn:source"
    missing = (f"No cloud file resolves from '{urn}'. Tried: {urn}. "
               "Get a lineage URN from data_get(project=<name>) ('id' on each file).")
    record = {"file": {"id": urn, "name": "Configuration 1"},
              "location": {"project": {"id": "config", "name": "System Project - CONFIG"},
                           "parent_folder": {"name": "Backing"}},
              "state": {"is_complete": False}}
    replies = [(True, missing), (False, record)]
    if fault == "permission":
        replies[0] = (True, "permission denied")
    elif fault == "wrong_record":
        record["file"]["id"] = "urn:other"
    elif fault == "timeout":
        replies[:] = [(True, missing)] * 3
    calls = []
    def call(tool, args):
        calls.append((tool, args))
        return replies.pop(0)
    monkeypatch.setattr(acts, "facade", lambda key: call)
    monkeypatch.setattr(acts.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(acts, "_SETTLE_POLLS", 3)
    if fault is None:
        assert step[1]({"lin_first": urn}) == {"file": urn}
    else:
        with pytest.raises(AssertionError):
            step[1]({"lin_first": urn})
    assert len(calls) == (1 if fault == "permission" else 3 if fault == "timeout" else 2)
    assert all(call == ("data_get", {"file": urn}) for call in calls)
