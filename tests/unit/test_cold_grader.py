# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The cold self-test's grader: each outcome fails for its own reason and for no other."""

import copy
import importlib.util
import json
import os

import pytest

_COLD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live", "cold")


def _grader():
    spec = importlib.util.spec_from_file_location("cold_grader", os.path.join(_COLD, "grader.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


grader = _grader()
A, B = "session:a", "session:b"


def _row(tool, arguments, payload, failed=False):
    return grader.call_row(tool, arguments, {"content": [{"type": "text", "text": json.dumps(payload)}],
                                             "isError": failed})


def _sketch(count, start_y, end_y):
    return {"constraint_count": count,
            "entities": [{"type": "point", "position": {"x": 0, "y": 0}},
                         {"type": "line", "start": {"x": 0, "y": start_y}, "end": {"x": 30, "y": end_y}}]}


def _active(handle):
    return {"active": {"document_handle": handle}}


@pytest.fixture
def run():
    """A healthy run: the child's calls, the script's reads, and the pack's checks."""
    with open(os.path.join(_COLD, "packs", "core", "checks.json"), encoding="utf-8") as fh:
        checks = json.load(fh)
    calls = []
    for flag in (True, False, True):
        calls.append(_row("param_set_favorite", {"name": "ColdLength", "favorite": flag}, {"name": "ColdLength"}))
        calls.append(_row("param_get", {"name": "ColdLength"}, {"parameter": {"favorite": flag}}))
    for handle in (A, B):
        calls.append(_row("doc_activate", {"name": handle}, {"activated": True}))
        calls.append(_row("doc_get", {}, _active(handle)))
    calls.append(_row("sketch_get", {"sketch_name": "ColdBatch"}, _sketch(0, 0.0, 10.0)))
    calls.append(_row("sketch_constrain", {"sketch_name": "ColdBatch"},
                      {"note": "1 of 2 landed", "constrained": 1, "requested": 2, "failed": {"index": 1}},
                      failed=True))
    calls.append(_row("sketch_get", {"sketch_name": "ColdBatch"}, _sketch(1, 5.0, 5.0)))
    reads = [_row("doc_get", {}, _active(B)),
             _row("param_get", {"name": "ColdLength"}, {"parameter": {"favorite": True}}),
             _row("sketch_get", {"sketch_name": "ColdBatch", "include_entities": True, "units": "mm"},
                  _sketch(1, 5.0, 5.0))]
    return {"checks": checks, "calls": calls, "reads": reads, "context": {"owned": [A, B]}}


def _verdicts(run, **changed):
    parts = dict(run, **changed)
    outcomes = grader.grade(parts["checks"], parts["calls"], parts["reads"], parts["context"])
    return {outcome["id"]: outcome["verdict"] for outcome in outcomes}


def _edited(rows, index, **payload):
    rows = copy.deepcopy(rows)
    rows[index]["payload"].update(payload)
    return rows


ALL_PASS = {"favorite": "PASS", "activation": "PASS", "partial_batch": "PASS"}


def test_a_healthy_run_passes_every_outcome(run):
    assert _verdicts(run) == ALL_PASS


def test_a_final_flag_the_script_reads_false_fails_the_favorite_outcome_alone(run):
    reads = _edited(run["reads"], 1, parameter={"favorite": False})
    assert _verdicts(run, reads=reads) == dict(ALL_PASS, favorite="FAIL")


def test_a_write_whose_separate_read_disagrees_fails_the_favorite_outcome(run):
    calls = _edited(run["calls"], 3, parameter={"favorite": True})
    assert _verdicts(run, calls=calls) == dict(ALL_PASS, favorite="FAIL")


def test_a_write_with_no_read_before_the_next_write_fails(run):
    calls = [row for i, row in enumerate(run["calls"]) if i != 1]
    assert _verdicts(run, calls=calls)["favorite"] == "FAIL"


def test_a_switch_to_a_document_the_run_does_not_own_does_not_count_as_one_of_the_two(run):
    assert _verdicts(run, context={"owned": [A]}) == dict(ALL_PASS, activation="FAIL")


def test_an_extra_switch_to_a_foreign_document_is_ignored_but_still_ends_the_stretch(run):
    foreign = [_row("doc_activate", {"name": "session:home"}, {"activated": True}),
               _row("doc_get", {}, _active("session:home"))]
    assert _verdicts(run, calls=run["calls"] + foreign) == ALL_PASS
    # the foreign switch sits between A's activation and its read: A is no longer confirmed
    calls = run["calls"][:7] + foreign[:1] + run["calls"][7:]
    assert _verdicts(run, calls=calls)["activation"] == "FAIL"


def test_a_batch_recorded_as_completed_fails_the_partial_batch_outcome_alone(run):
    calls = copy.deepcopy(run["calls"])
    calls[11]["failed"] = False
    assert _verdicts(run, calls=calls) == dict(ALL_PASS, partial_batch="FAIL")


def test_a_refusal_before_the_first_entry_landed_does_not_satisfy_the_batch(run):
    calls = _edited(run["calls"], 11, constrained=0)
    assert _verdicts(run, calls=calls)["partial_batch"] == "FAIL"


def test_endpoints_the_script_reads_unequal_fail_the_partial_batch_outcome_alone(run):
    reads = copy.deepcopy(run["reads"])
    reads[2]["payload"] = _sketch(1, 0.0, 0.002)
    assert _verdicts(run, reads=reads) == dict(ALL_PASS, partial_batch="FAIL")


def test_endpoints_exactly_the_tolerance_apart_pass(run):
    reads = copy.deepcopy(run["reads"])
    reads[2]["payload"] = _sketch(1, 0.0, 0.001)
    assert _verdicts(run, reads=reads) == ALL_PASS


def test_a_run_with_no_tool_call_is_untested_not_failed(run):
    outcomes = grader.grade(run["checks"], [], run["reads"], run["context"])
    assert {o["verdict"] for o in outcomes} == {"UNTESTED"}
    assert outcomes[0]["checks"][0]["detail"] == "the client recorded no tool call"


def test_a_read_the_script_could_not_make_fails_with_the_refusal_text(run):
    reads = copy.deepcopy(run["reads"])
    reads[1] = grader.call_row("param_get", {"name": "ColdLength"},
                               {"content": [{"type": "text", "text": "No parameter named ColdLength"}],
                                "isError": True})
    outcome = grader.grade(run["checks"], run["calls"], reads, run["context"])[0]
    assert outcome["verdict"] == "FAIL"
    assert "No parameter named ColdLength" in outcome["checks"][1]["detail"]


def test_renaming_maps_the_packs_fixed_names_onto_a_recorded_runs(run):
    checks = grader.renamed(run["checks"], {"ColdLength": "ScratchLength"})
    assert _verdicts(run, checks=checks)["favorite"] == "FAIL"
    calls = json.loads(json.dumps(run["calls"]).replace("ColdLength", "ScratchLength"))
    reads = json.loads(json.dumps(run["reads"]).replace("ColdLength", "ScratchLength"))
    assert _verdicts(run, checks=checks, calls=calls, reads=reads) == ALL_PASS
