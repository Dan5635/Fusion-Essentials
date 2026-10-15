# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Read-only admission refuses incomplete identity, unaccepted work and unsupported prerequisites."""

import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def preflight_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "live"))
    return importlib.import_module("preflight")


@pytest.fixture
def inputs(preflight_module):
    enum = lambda value: {"enum": value}
    config = json.loads(preflight_module.machine_config.example_text())
    config["port"] = 40123
    return {"config": config,
            "health": {"bound": {"port": 40123, "host": "127.0.0.1",
                                  "mcp_url": "http://127.0.0.1:40123/mcp"}},
            "tools": ["doc_new", "doc_get", "sys_get_preferences", "model_extrude"],
            "needed": ["doc_new", "model_extrude"],
            "documents": {"open_count": 2, "truncated": False, "open_documents": [
                {"name": "Owned", "document_handle": "session:owned", "is_modified": True},
                {"name": "Protected", "document_handle": "session:protected", "is_modified": False}]},
            "preferences": {"preferences": {
                "general": {"defaultModelingOrientation": enum("ZUpModelingOrientation"),
                            "userLanguage": enum("EnglishLanguage")},
                "units_defaults": {"Design": {"defaultUnitSystem": enum("MillimeterGramUnitSystem")}}}}}


def test_exact_owned_resume_handles_do_not_exempt_unrelated_modified_work(preflight_module, inputs):
    assert preflight_module.problems(**inputs, owned_handles=["session:owned"]) == []
    inputs["documents"]["open_documents"][1]["is_modified"] = True
    found = preflight_module.problems(**inputs, owned_handles=["session:owned"])
    assert len(found) == 1 and "session:protected" in found[0] and "--accept-open-work" in found[0]
    assert preflight_module.problems(**inputs, accept_open_work=True) == []


def test_checkpoint_ownership_uses_actual_handle_lists_not_document_rows(preflight_module):
    assert preflight_module.owned_handles(None) == ()
    assert preflight_module.owned_handles({"owned_documents": ["session:owned"],
        "lifecycle_owned_documents": ["session:anchor", "session:owned"]}) == ("session:owned", "session:anchor")
    for wrong in ({"owned_documents": [{"document_handle": "session:owned"}]},
                  {"owned_documents": "session:owned"}, {"owned_documents": ["Owner Name"]},
                  {"owned_documents": ["session: bad"]}):
        with pytest.raises(ValueError, match="exact session handles"):
            preflight_module.owned_handles(wrong)


@pytest.mark.parametrize("mutation", ["cut", "count", "duplicate", "unread-flag", "missing-handle"])
def test_incomplete_census_stops_even_when_open_work_is_accepted(preflight_module, inputs, mutation):
    documents = inputs["documents"]
    if mutation == "cut":
        documents["truncated"] = True
    elif mutation == "count":
        documents["open_count"] = 3
    elif mutation == "duplicate":
        documents["open_documents"][1]["document_handle"] = "session:owned"
    elif mutation == "unread-flag":
        documents["open_documents"][1]["is_modified"] = None
    else:
        del documents["open_documents"][1]["document_handle"]
    found = preflight_module.problems(**inputs, accept_open_work=True)
    assert len(found) == 1 and "census is incomplete or ambiguous" in found[0]


def test_compacted_healthy_flags_are_absent_but_explicit_null_is_unread(preflight_module, inputs):
    row = inputs["documents"]["open_documents"][1]
    del row["is_modified"]
    assert preflight_module.problems(**inputs, owned_handles=["session:owned"]) == []
    row["is_modified"] = None
    found = preflight_module.problems(**inputs, owned_handles=["session:owned"])
    assert len(found) == 1 and "incomplete or ambiguous" in found[0]


@pytest.mark.parametrize("key,value", [("port", 37182), ("port", "40123"),
                                       ("host", "0.0.0.0"), ("mcp_url", "http://127.0.0.1:37182/mcp")])
def test_endpoint_must_match_all_configured_bound_fields(preflight_module, inputs, key, value):
    inputs["health"]["bound"][key] = value
    found = preflight_module.problems(**inputs, accept_open_work=True)
    assert len(found) == 1 and "configuration port=40123" in found[0]


def test_requested_scripts_stop_on_missing_registration_but_off_scripts_need_no_tool(preflight_module, inputs):
    assert preflight_module.problems(**inputs, accept_open_work=True) == []
    inputs["config"]["tiers"]["native_script"] = True
    found = preflight_module.problems(**inputs, accept_open_work=True)
    assert len(found) == 1 and preflight_module.SCRIPT_SETTING in found[0]
    inputs["tools"].append("sys_execute_script")
    assert preflight_module.problems(**inputs, accept_open_work=True) == []


def test_native_off_cannot_admit_a_required_home_observer_even_when_registered(preflight_module, inputs):
    inputs["tools"].append("sys_execute_script")
    found = preflight_module.problems(**inputs, accept_open_work=True, home_observer_required=True)
    assert len(found) == 1 and "tiers.native_script=false" in found[0]
    assert "strict home" in found[0] and "before family writes" in found[0]
    inputs["config"]["tiers"]["native_script"] = True
    assert preflight_module.problems(**inputs, accept_open_work=True, home_observer_required=True) == []


def test_home_prerequisite_refusal_stays_read_only_and_names_the_explicit_choice(preflight_module, inputs, wire):
    harness, calls = wire
    inputs["tools"].append("sys_execute_script")
    message = preflight_module.refusal(inputs["config"], harness, inputs["needed"],
        owned_handles=["session:owned"], home_observer_required=True)
    assert "one thing" in message and "tiers.native_script=false" in message
    assert [name for name, _args in calls] == ["health", "tools/list", "doc_get", "sys_get_preferences"]


def test_registration_refusal_names_observed_missing_tools_without_inventing_cause(preflight_module, inputs):
    inputs["needed"] += ["cam_get", "data_get"]
    found = preflight_module.problems(**inputs, accept_open_work=True)
    assert len(found) == 1 and "cam_get, data_get" in found[0]
    assert "family is switched off" not in found[0] and "server version" in found[0]


@pytest.mark.parametrize("path,value", [
    (("general", "defaultModelingOrientation"), "YUpModelingOrientation"),
    (("general", "userLanguage"), "GermanLanguage"),
    (("units_defaults", "Design", "defaultUnitSystem"), "InchImperialUnitSystem")])
def test_unmeasured_preference_and_unread_preference_both_stop(preflight_module, inputs, path, value):
    holder = inputs["preferences"]["preferences"]
    for key in path[:-1]:
        holder = holder[key]
    holder[path[-1]]["enum"] = value
    found = preflight_module.problems(**inputs, accept_open_work=True)
    assert len(found) == 1 and value in found[0] and ".".join(path) in found[0]
    del holder[path[-1]]
    found = preflight_module.problems(**inputs, accept_open_work=True)
    assert len(found) == 1 and "None" in found[0]


@pytest.fixture
def wire(inputs):
    """Inject source-shaped replies and retain every attempted admission dispatch."""
    calls = []

    def call(tool, args):
        calls.append((tool, args))
        return False, copy.deepcopy(inputs["documents" if tool == "doc_get" else "preferences"])

    harness = SimpleNamespace(
        health_gate=lambda: calls.append(("health", {})) or inputs["health"],
        registered_tools=lambda health: calls.append(("tools/list", {})) or inputs["tools"],
        call=call)
    return harness, calls


def test_refusal_reads_four_times_and_never_dispatches_a_write(preflight_module, inputs, wire):
    harness, calls = wire
    assert preflight_module.refusal(inputs["config"], harness, inputs["needed"],
                                    owned_handles=["session:owned"]) is None
    assert calls == [("health", {}), ("tools/list", {}), ("doc_get", {"max_results": 1000}),
                     ("sys_get_preferences", {"include": ["general", "units_defaults"]})]


def test_invalid_configuration_stops_before_any_admission_call(preflight_module, inputs, wire):
    harness, calls = wire
    del inputs["config"]["allow"]["preference_writes"]
    with pytest.raises(SystemExit, match="missing: allow.preference_writes"):
        preflight_module.refusal(inputs["config"], harness, inputs["needed"])
    assert calls == []


def test_failed_reads_never_admit_the_first_write(preflight_module, inputs, wire, monkeypatch):
    harness, calls = wire
    monkeypatch.setattr(harness, "call", lambda *args: (True, "injected read failure"))
    message = preflight_module.refusal(inputs["config"], harness, inputs["needed"])
    assert "4 things" in message and "census is incomplete" in message
    assert "defaultModelingOrientation" in message and "defaultUnitSystem" in message
    assert "userLanguage" in message
