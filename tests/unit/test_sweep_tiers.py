# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Asked scope never fabricates entitlement or applies one condition's polarity to another."""

import importlib
import copy
import json
import ast
import subprocess
import sys
from types import CodeType
from pathlib import Path

import pytest


@pytest.fixture
def policy(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "live"))
    return importlib.import_module("machine_config")


@pytest.mark.parametrize("asked,measured,needs,unless", [
    (True, True, "run", "not-applicable"),
    (True, False, "stop", "stop"),
    (True, None, "stop", "stop"),
    (False, True, "not-in-scope", "not-applicable"),
    (False, False, "not-in-scope", "run"),
    (False, None, "not-in-scope", "held")])
def test_declared_extension_and_observed_entitlement_remain_distinct(policy, asked, measured, needs, unless):
    for polarity, state in (("needs", needs), ("unless", unless)):
        row = policy.condition("machining_extension", polarity, asked, measured)
        assert row == {"capability": "machining_extension", "polarity": polarity,
                       "asked": asked, "measured": measured, "state": state,
                       "reason": row["reason"]}
        assert (row["reason"] is None) == (state == "run")


def test_each_persistent_permission_off_blocks_needs_without_forging_measurement(policy):
    assert policy.PERMISSIONS == {"library_writes", "preference_writes", "addin_reload"}
    for name in policy.PERMISSIONS:
        off = policy.condition(name, "needs", False, True)
        assert off["state"] == "not-in-scope" and off["measured"] is True
        assert policy.condition(name, "needs", True, True)["state"] == "run"


def test_conjunction_preserves_all_conditions_and_uses_declared_rank(policy):
    rows = [policy.condition("machining_extension", "unless", False, None),
            policy.condition("native_script", "needs", False, True),
            policy.condition("cloud_tier", "needs", True, False)]
    combined = policy.conjunction(rows)
    assert combined["state"] == "stop" and combined["conditions"] == rows
    assert policy.conjunction(rows[:2])["state"] == "not-in-scope"
    assert policy.conjunction(rows[:1])["state"] == "held"
    assert policy.conjunction([policy.condition("machining_extension", "unless", False, True)]
                              )["state"] == "not-applicable"
    assert policy.conjunction([]) == {"state": "run", "reason": None, "conditions": []}


def test_quarantine_cannot_be_enabled_by_configuration(policy):
    row = policy.condition("cloud_link_crash_review_authorization", "needs", True, True,
                            ["cloud_link_crash_review_authorization"])
    assert row["state"] == "not-in-scope" and "quarantined" in row["reason"]


@pytest.mark.parametrize("polarity,asked,measured", [("maybe", True, True), ("needs", "yes", True),
                                                    ("needs", True, 1)])
def test_mistyped_condition_values_are_not_coerced_to_entitlement(policy, polarity, asked, measured):
    with pytest.raises(ValueError):
        policy.condition("machining_extension", polarity, asked, measured)


@pytest.mark.parametrize("tool,args,switch", [
    ("cam_create_machine", {}, "allow.library_writes"),
    ("cam_delete_machine", {}, "allow.library_writes"),
    ("cam_save_template", {}, "allow.library_writes"),
    ("cam_delete_template", {}, "allow.library_writes"),
    ("cam_edit_tools", {"scope": "local", "action": "add"}, "allow.library_writes"),
    ("sys_set_preferences", {}, "allow.preference_writes"),
    ("sys_reload_addin", {}, "allow.addin_reload"),
    ("data_create_folder", {}, "tiers.cloud"),
    ("drawing_get", {}, "tiers.cloud"),
    ("sys_execute_script", {"read_only": True}, "tiers.native_script")])
def test_direct_dispatch_fences_every_persistent_and_opt_in_route(policy, tool, args, switch):
    config = json.loads(policy.example_text())
    with pytest.raises(SystemExit, match=switch):
        policy.require_call(config, tool, args)


def test_document_tools_do_not_need_library_permission_but_all_shared_mutations_do(policy):
    config = json.loads(policy.example_text())
    assert policy.require_call(config, "cam_edit_tools", {"scope": "document", "action": "add"}) is None
    assert policy.require_call(config, "cam_edit_tools", {"scope": "local", "action": "list"}) is None
    for action in ("create_library", "add", "edit", "remove", "add_preset", "remove_preset", "unknown"):
        with pytest.raises(SystemExit, match="allow.library_writes"):
            policy.require_call(config, "cam_edit_tools", {"scope": "local", "action": action})
    assert policy.require_call(config, "cam_edit_tools", {"scope": " Document ", "action": "ADD"}) is None
    assert policy.require_call(config, "cam_edit_tools", {"scope": "Local", "action": "LIST"}) is None


def test_document_local_cleanup_and_unlink_do_not_borrow_cloud_permission(policy):
    for args in ({}, {"save_changes": False}):
        assert policy.call_requirements("doc_close", args) == ()
    assert policy.call_requirements("doc_update_xref", {"action": " Break_Link "}) == ()
    assert policy.call_requirements("doc_insert_import", {"file_path": "injected.f3d"}) == ()
    assert policy.call_requirements("doc_new", {}) == ()


def test_static_save_cleanup_rows_carry_cloud_gate_without_replacing_predicates(sweep):
    core = sweep.verify_core
    predicate = lambda payload: payload["saved"] is True
    save = ("saved", lambda payload: payload["document_id"])
    rows = [("doc_save", {}, predicate, save),
            ("doc_close", {"save_changes": True}, "ok", None),
            ("doc_close", {"save_changes": False}, "ok", None)]
    assembled = core.tiered(rows)
    assert core.step_conditions(assembled[0][2]) == (("cloud_tier", "needs"),)
    assert core.step_conditions(assembled[1][2]) == (("cloud_tier", "needs"),)
    assert core.step_conditions(assembled[2][2]) == ()
    assert core._unparked(assembled[0][2]) is predicate and assembled[0][3] is save
    assert not core.gate_allows({"cloud_tier": True}, assembled[0][2])
    assert assembled[0][:2] == rows[0][:2]


def test_unclassified_native_script_does_not_borrow_permission_from_its_tier(policy):
    config = json.loads(policy.example_text())
    config["tiers"]["native_script"] = True
    with pytest.raises(SystemExit) as refused:
        policy.require_call(config, "sys_execute_script", {"script": "unclassified"})
    assert all("allow." + key in str(refused.value) for key in config["allow"])
    assert "tiers.cloud" in str(refused.value)
    assert policy.require_call(config, "sys_execute_script", {"script": "classified-doc-only"}, []) is None
    with pytest.raises(SystemExit, match="allow.preference_writes"):
        policy.require_call(config, "sys_execute_script", {}, ["preference_writes"])
    with pytest.raises(ValueError):
        policy.require_call(config, "sys_execute_script", {}, ["preference_write_typo"])


def test_permission_is_an_explicit_choice_not_a_fabricated_native_observation(policy):
    assert policy.condition("preference_writes", "needs", True, None)["state"] == "run"
    assert policy.condition("preference_writes", "needs", False, None)["state"] == "not-in-scope"


@pytest.mark.parametrize("permission", ["library_writes", "preference_writes", "addin_reload"])
def test_unknown_read_only_script_does_not_exempt_external_persistent_permissions(policy, permission):
    config = json.loads(policy.example_text())
    config["tiers"].update(native_script=True, cloud=True)
    config["cloud"].update(hub="unit hub", project="unit project", folder="unit folder")
    config["allow"].update({key: True for key in config["allow"]})
    config["allow"][permission] = False
    arguments = {"script": "unclassified external effects", "read_only": True}
    with pytest.raises(SystemExit, match="allow." + permission):
        policy.require_call(config, "sys_execute_script", arguments)
    assert policy.require_call(config, "sys_execute_script", arguments, []) is None


@pytest.mark.parametrize("tool,args", [
    ("cam_save_template", {}), ("cam_save_template", {"location": "cloud"}),
    ("cam_save_template", {"location": "hub"}), ("cam_save_template", {"location": None}),
    ("cam_edit_tools", {"scope": "cloud", "action": "add"}),
    ("cam_edit_tools", {"scope": "hub", "action": "remove"}),
    ("cam_edit_tools", {"scope": "cloud", "action": "list"}),
    ("cam_edit_tools", {"scope": "hub", "action": "parameters"})])
def test_library_permission_does_not_authorize_cloud_library_selectors(policy, tool, args):
    config = json.loads(policy.example_text())
    config["allow"]["library_writes"] = True
    with pytest.raises(SystemExit, match="tiers.cloud"):
        policy.require_call(config, tool, args)


@pytest.mark.parametrize("tool,args", [
    ("cam_create_machine", {}), ("cam_delete_machine", {}), ("cam_delete_template", {}),
    ("cam_save_template", {"location": "local"}),
    ("cam_edit_tools", {"scope": "local", "action": "create_library"}),
    ("cam_edit_tools", {"scope": "cloud", "action": "list_types"})])
def test_cloud_fence_keeps_local_library_writes_and_bundled_type_catalog_admitted(policy, tool, args):
    config = json.loads(policy.example_text())
    config["allow"]["library_writes"] = True
    assert policy.require_call(config, tool, args) is None


def test_record_scope_and_directory_bind_all_machine_choices(policy):
    config = json.loads(policy.example_text())
    scope = policy.record_scope(config)
    assert policy.validate_scope(scope) == scope
    assert scope["asked"] == policy.asked(config)
    assert scope["machine"] == "my-machine" and scope["config_hash"] == policy.fingerprint(config)
    root = Path(policy.record_root(config))
    assert root.parts[-3:-1] == ("records", "my-machine")
    assert len(root.name) == 64 and scope["os"] and scope["checkout"]
    config["allow"]["preference_writes"] = True
    assert policy.record_root(config) != str(root)
    for change in ({"version": True}, {"asked": {"cloud_tier": False}}, {"machine": "CON"},
                   {"config_hash": "unreadable"}, {"quarantined": []}, {"os": None}, {"checkout": ""}):
        with pytest.raises(ValueError):
            policy.validate_scope(dict(scope, **change))


def test_record_directory_does_not_mix_equal_labels_on_different_os_or_checkouts(policy, monkeypatch):
    config = json.loads(policy.example_text())
    first = policy.record_root(config)
    scope = policy.record_scope(config)
    monkeypatch.setattr(policy.platform, "system", lambda: "Injected Other OS")
    assert policy.record_root(config) != first
    assert policy.validate_scope(scope) == scope
    second = policy.record_root(config)
    monkeypatch.setattr(policy, "_HERE", str(Path(policy._HERE).parent / "injected" / "live"))
    assert policy.record_root(config) != second


def test_full_scope_is_not_redefined_by_this_readers_configuration(policy):
    config = json.loads(policy.example_text())
    old_scope = policy.record_scope(config)
    for group in ("tiers", "allow"):
        config[group].update({name: True for name in config[group]})
    assert policy.require_full_scope(policy.record_scope(config)) is None
    with pytest.raises(ValueError, match="excluded choices"):
        policy.require_full_scope(old_scope)
    for name in policy.SWITCHES:
        scope = policy.record_scope(config)
        scope["asked"][name] = False
        with pytest.raises(ValueError, match=name):
            policy.require_full_scope(scope)


def test_omission_preserves_each_gate_polarity_and_rejects_relabeling(policy):
    scope = policy.record_scope(json.loads(policy.example_text()))
    conditions = [policy.condition("native_script", "needs", False, True),
                  policy.condition("machining_extension", "unless", False, False)]
    row = policy.omission("ACT 5", "step", ["sys_execute_script"], conditions)
    assert row["state"] == "not-in-scope" and row["conditions"] == conditions
    assert policy.validate_omission(row, scope) == row
    for key, value in (("asked", True), ("polarity", "needs"), ("measured", None)):
        corrupt = copy.deepcopy(row)
        corrupt["conditions"][1][key] = value
        with pytest.raises(ValueError):
            policy.validate_omission(corrupt, scope)
    for state in ("run", "held", "not-applicable"):
        with pytest.raises(ValueError):
            policy.validate_omission(dict(row, state=state), scope)
    with pytest.raises(ValueError):
        policy.validate_omission(dict(row, conditions=conditions + [conditions[0]]), scope)
    with pytest.raises(ValueError):
        policy.omission("ACT 5", "step", [], [policy.condition("native_script", "needs", True, None)])


@pytest.fixture
def sweep(policy, monkeypatch, tmp_path):
    from conftest import load_tool_verify
    config = json.loads(policy.example_text())
    path = tmp_path / "machine.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv(policy.ENV, str(path))
    module = load_tool_verify()
    monkeypatch.setitem(sys.modules, "tool_verify", module)
    monkeypatch.setattr(module.verify_core, "MACHINE", config)
    monkeypatch.setattr(module.verify_core, "_MACHINE_READ", (config, [], str(path), policy.ENV))
    return module


def test_real_gate_walker_keeps_mixed_polarities_and_innermost_predicate(sweep):
    core = sweep.verify_core
    predicate = lambda payload: payload["count"] == 2
    witness = core.Independent(predicate, ["model_extrude"], "tool:model_inspect")
    expect = core.Needs("native_script", core.Parked("held commentary",
               core.Unless("machining_extension", witness)))
    assert core.step_conditions(expect) == (("native_script", "needs"), ("machining_extension", "unless"))
    assert core._unparked(expect) is predicate
    result = core.gate_decision({"native_script": True, "machining_extension": False}, expect)
    assert [row["state"] for row in result["conditions"]] == ["not-in-scope", "run"]
    assert result["state"] == "not-in-scope" and not core.gate_allows(
        {"native_script": True, "machining_extension": False}, expect)


def test_actual_compiled_and_fixture_scripts_carry_all_conservative_requirements(sweep, policy):
    from verify_families import fixture_steps
    count = 0
    for name, _pre, narrative, fallback in sweep.ACTS:
        for tool, args, expect, _save in list(narrative) + list(fallback or []):
            if tool != "sys_execute_script":
                continue
            count += 1
            declaration = sweep.verify_core.step_script_declaration(expect)
            requirements = policy.call_requirements(tool, args if isinstance(args, dict) else {},
                declaration["effects"] if declaration is not None else None)
            assert {(value, "needs") for value in requirements} <= set(sweep.verify_core.step_conditions(expect)), name
    assert count == 271
    fixture_count = 0
    for family in set(sweep.FAMILY_PROGRAM.values()):
        rows = fixture_steps(family)
        for name, owner in sweep.FAMILY_PROGRAM.items():
            if owner == family:
                rows += fixture_steps(family, before_act=name)
        for tool, args, expect, _save in rows:
            if tool == "sys_execute_script":
                fixture_count += 1
                assert ("native_script", "needs") in sweep.verify_core.step_conditions(expect)
    assert fixture_count == 20


def test_tier_annotation_is_idempotent_and_preserves_original_row_callbacks(sweep):
    core = sweep.verify_core
    args = lambda ctx: {"script": ctx["script"]}
    predicate = lambda payload: payload["count"] == 2
    save = lambda ctx, payload: ctx.update(count=payload["count"])
    expect = core.Unless("machining_extension", core.Needs("native_script", predicate))
    once = core.tiered([("sys_execute_script", args, expect, save)])
    twice = core.tiered(once)
    assert twice == once
    assert once[0][1] is args and once[0][3] is save and core._unparked(once[0][2]) is predicate
    assert core.step_conditions(once[0][2]).count(("native_script", "needs")) == 1
    assert ("machining_extension", "unless") in core.step_conditions(once[0][2])


def test_receipt_validator_consumes_all_conditions_and_binds_policy_source(sweep, policy):
    receipts = importlib.import_module("verify_receipts")
    assert receipts.FORMAT == 2
    assert {"tests/live/machine_config.py", "tests/live/preflight.py"} <= set(receipts._ENGINE)
    scope = policy.record_scope(json.loads(policy.example_text()))
    row = policy.omission("ACT 5", "step", ["sys_execute_script"], [
        policy.condition("native_script", "needs", False, True),
        policy.condition("machining_extension", "unless", False, False)])
    assert receipts._recorded_scope(scope) == scope
    assert receipts._scope_rows([row], ["ACT 5"]) == [row]
    assert receipts._validate_omission_scope(row, scope) is None
    assert "not in scope: native_script" in receipts.scope_description({"details": {"omitted": [row]}})
    corrupt = copy.deepcopy(row)
    corrupt["conditions"][1]["polarity"] = "needs"
    with pytest.raises(ValueError, match="scope/polarity/observation"):
        receipts._validate_omission_scope(corrupt, scope)


def test_real_permission_probe_does_not_report_native_entitlement(sweep):
    core = sweep.verify_core
    measured = core.probe_capabilities(["library_writes", "preference_writes", "addin_reload"])
    assert measured == {"library_writes": None, "preference_writes": None, "addin_reload": None}
    assert not core.gate_allows(measured, core.Needs("preference_writes"))
    core.MACHINE["allow"]["preference_writes"] = True
    assert core.gate_allows(measured, core.Needs("preference_writes"))
    assert core.gate_decision(measured, core.Needs("preference_writes"))["conditions"][0]["measured"] is None


@pytest.fixture
def graphics_preference_row(sweep, monkeypatch):
    row = next(row for row in sweep._OVERTURE if row[0] == "sys_get_preferences"
               and row[1] == {"include": ["graphics"]})
    monkeypatch.setattr(sweep.verify_core, "_RECALL", {})
    return row


@pytest.mark.parametrize("member", [None, "minimumFramesPerSecond", "degradedSelectionDisplayStyle"])
def test_actual_graphics_row_accepts_the_published_census_and_records_names(graphics_preference_row, member, sweep, capsys):
    graphics = {"graphicsPreset": {"tier": "W", "value": "injected-preset"}}
    payload = {"preferences": {"graphics": graphics}}
    names = [] if member is None else ["graphics." + member]
    if member is not None:
        graphics[member] = {"tier": "W", "unreadable": True, "value": None}
        payload.update(unreadable=names, unreadable_count=1)
    assert graphics_preference_row[2](payload) is True
    key, save = graphics_preference_row[3]
    expected = {"unreadable": names, "unreadable_count": len(names), "unknown_members": []}
    assert key == "pref_graphics_unreadable" and save(payload) == expected
    assert sweep.verify_core._RECALL[key] == expected
    published = capsys.readouterr().out
    assert "preference unreadable census: " + json.dumps(expected, sort_keys=True) in published


@pytest.mark.parametrize("mutation", ["unknown_members", "unknown_flag", "bad_list", "missing_member",
                                     "unflagged_member", "unlisted_flag", "count", "bool_count", "duplicate"])
def test_actual_graphics_row_refuses_unknown_or_inconsistent_census(graphics_preference_row, mutation):
    record = {"tier": "W", "unreadable": True, "value": None}
    payload = {"preferences": {"graphics": {"graphicsPreset": {"tier": "W", "value": "injected-preset"},
                                               "minimumFramesPerSecond": record}},
               "unreadable": ["graphics.minimumFramesPerSecond"], "unreadable_count": 1}
    if mutation == "unknown_members":
        payload[mutation] = ["graphics.minimumFramesPerSecond"]
    elif mutation == "unknown_flag":
        record["unknown_member"] = True
    elif mutation == "bad_list":
        payload["unreadable"] = None
    elif mutation == "missing_member":
        del payload["preferences"]["graphics"]["minimumFramesPerSecond"]
    elif mutation == "unflagged_member":
        del record["unreadable"]
    elif mutation == "unlisted_flag":
        payload["unreadable"], payload["unreadable_count"] = [], 0
    elif mutation in {"count", "bool_count"}:
        payload["unreadable_count"] = 2 if mutation == "count" else True
    else:
        payload["unreadable"].append("graphics.minimumFramesPerSecond")
        payload["unreadable_count"] = 2
    for check in (graphics_preference_row[2], graphics_preference_row[3][1]):
        with pytest.raises(AssertionError):
            check(payload)


def test_quarantined_real_gate_stays_outside_scope_without_an_unreadable_hold(sweep):
    core = sweep.verify_core
    decision = core.gate_decision({}, core.Needs(core.CLOUD_LINK_CRASH_REVIEW))
    assert decision["state"] == "not-in-scope"
    assert decision["conditions"][0]["measured"] is None


def test_actual_closing_hooks_refuse_before_settings_files_or_scratch_calls(sweep, monkeypatch):
    switch = importlib.import_module("verify_family_switch")
    doc = importlib.import_module("verify_acts_doc")
    attempted = []
    monkeypatch.setattr(switch, "settings_file", lambda: attempted.append("settings"))
    monkeypatch.setattr(switch, "_read", lambda *args: attempted.append("file-read"))
    monkeypatch.setattr(switch, "_replace", lambda *args: attempted.append("file-write"))
    monkeypatch.setattr(sweep, "call", lambda *args, **kw: attempted.append("call"))
    with pytest.raises(SystemExit, match="refused before transport: excluded allow.preference_writes"):
        switch.family_switch_smoke([], {}, ["model_inspect"])
    with pytest.raises(SystemExit, match="refused before transport: excluded allow.addin_reload"):
        doc.reload_smoke([], {})
    assert attempted == []


def test_omitted_lifecycle_has_no_native_evidence_and_receives_no_execution_credit(sweep, policy):
    receipts = importlib.import_module("verify_receipts")
    source = "a" * 64
    lifecycle = receipts.make_lifecycle(None, "run", source, "build")
    assert lifecycle["state"] == "not-in-scope"
    assert set(lifecycle) == {"state", "run_id", "source_hash", "fusion_version", "scope", "omitted"}
    assert set(lifecycle["omitted"]) == {"switch", "reload"}
    receipts._validate_lifecycle(lifecycle, source, "build", ["sys_reload_addin"])
    ledger = receipts.aggregate_ledger({"lifecycle": lifecycle}, {}, ["sys_reload_addin"], source_hash=source)
    assert ledger == [("sys_reload_addin", "skipped: not-in-scope allow.addin_reload is false")]
    for corrupt in (dict(lifecycle, raw={}), dict(lifecycle, state="executed"),
                    dict(lifecycle, source_hash="b" * 64), dict(lifecycle, omitted={})):
        with pytest.raises(ValueError):
            receipts._validate_lifecycle(corrupt, source, "build", [])
    with pytest.raises(ValueError, match="excluded reload cannot carry execution evidence"):
        receipts.make_lifecycle({}, "run", source, "build")


def test_lifecycle_switch_and_reload_permissions_are_independent(sweep, policy):
    receipts = importlib.import_module("verify_receipts")
    config = json.loads(policy.example_text())
    config["allow"]["addin_reload"] = True
    omitted = receipts.lifecycle_omissions(policy.record_scope(config))
    assert set(omitted) == {"switch"}
    assert [row["asked"] for row in omitted["switch"]["conditions"]] == [False, True]
    config["allow"]["preference_writes"] = True
    assert receipts.lifecycle_omissions(policy.record_scope(config)) == {}


@pytest.fixture
def runner_spy(sweep, monkeypatch):
    # One empty injected act isolates closing orchestration, not native family acceptance.
    identity = {"implementation_fingerprint": "a" * 64, "schema_fingerprint": "b" * 64,
                "load_id": "injected-load", "session_id": "injected-session"}
    monkeypatch.setattr(sweep, "ACTS", [("ACT unit", None, [], None)])
    monkeypatch.setattr(sweep, "ACT_NEEDS", {})
    monkeypatch.setattr(sweep, "FAMILY_PROGRAM", None)
    monkeypatch.setattr(sweep, "health_gate", lambda: {"server": "injected", "version": "unit",
        "bound": {"host": "127.0.0.1", "port": 37182, "mcp_url": "http://127.0.0.1:37182/mcp"}})
    monkeypatch.setattr(sweep, "attestation_identity", lambda health: identity)
    monkeypatch.setattr(sweep, "registered_tools", lambda *args, **kwargs: (
        ["doc_get", "sys_get_preferences", "sys_reload_addin"], ()))
    monkeypatch.setattr(sweep, "source_hash", lambda: "c" * 64)
    monkeypatch.setattr(sweep, "_document_now", lambda: {"state": "none"})
    calls = []
    def admission_read(tool, args):
        calls.append(tool)
        if tool == "doc_get":
            return False, {"open_count": 0, "open_documents": [], "truncated": False}
        if tool == "sys_get_preferences":
            return False, {"preferences": {
                "general": {"defaultModelingOrientation": {"enum": "ZUpModelingOrientation"},
                            "userLanguage": {"enum": "EnglishLanguage"}},
                "units_defaults": {"Design": {"defaultUnitSystem": {"enum": "MillimeterGramUnitSystem"}}}}}
        pytest.fail("closing wire call attempted: " + tool)
    monkeypatch.setattr(sweep, "call", admission_read)
    monkeypatch.setattr(sweep, "family_switch_smoke", lambda *args, **kwargs: pytest.fail("Settings hook attempted"))
    monkeypatch.setattr(sweep.family_switch_smoke, "support_routes", (), raising=False)
    monkeypatch.setattr(sweep, "reload_smoke", lambda *args, **kwargs: pytest.fail("reload hook attempted"))
    monkeypatch.setattr(sweep.reload_smoke, "support_routes", (), raising=False)
    tables = []
    monkeypatch.setattr(sweep, "write_verified", lambda ledger, *args, **kwargs: tables.append(ledger) or "injected")
    return calls, tables


def test_actual_runner_suppresses_both_closing_hooks_when_permissions_are_off(sweep, runner_spy):
    calls, tables = runner_spy
    assert sweep.run(False) == 0
    assert dict(tables[0])["sys_reload_addin"] == "skipped: not-in-scope: allow.addin_reload is false; no reload attempted"
    assert calls == ["doc_get", "sys_get_preferences"]


@pytest.mark.parametrize("enabled", [False, True])
def test_actual_runner_discloses_retained_library_permission_before_first_write_attempt(
        sweep, runner_spy, monkeypatch, capsys, enabled):
    core = sweep.verify_core
    core.MACHINE["allow"]["library_writes"] = enabled
    Path(core._MACHINE_READ[2]).write_text(json.dumps(core.MACHINE), encoding="utf-8")
    monkeypatch.setattr(sweep, "ACTS", [("ACT unit", None, [("doc_new", {}, "ok", None)], None)])
    monkeypatch.setattr(sweep, "registered_tools", lambda *args, **kwargs: (
        ["doc_get", "sys_get_preferences", "doc_new", "doc_close", "doc_activate"], ()))
    original_call = sweep.call
    events = []
    def call(tool, arguments, **kwargs):
        if tool == "doc_new":
            events.append("write_attempt")
            return True, "injected first write refusal"
        return original_call(tool, arguments)
    monkeypatch.setattr(sweep, "call", call)
    import builtins
    original_print = builtins.print
    def printed(*args, **kwargs):
        if "allow.library_writes is on" in " ".join(str(value) for value in args):
            events.append("notice")
        original_print(*args, **kwargs)
    monkeypatch.setattr(builtins, "print", printed)
    assert sweep.run(False) == 1
    assert events == (["notice", "write_attempt"] if enabled else ["write_attempt"])
    output = capsys.readouterr().out
    assert ("retains 'Fusion-Essentials sweep test data'" in output) is enabled


@pytest.fixture
def retained_seed(sweep, monkeypatch):
    cam = importlib.import_module("verify_acts_cam")
    seed = {"geometry": {"diameter": 6.0}, "description": "injected seed", "guid": "injected-source-guid",
            "post-process": {"number": 0, "diameter-offset": 0, "length-offset": 0, "comment": "keep"},
            "holder": {"segments": [{"height": 2.5}]}, "start-values": {"presets": [{"name": "Keep"}]}}
    parameters = {"tool_number": {"expression": "0", "value": 0},
                  "tool_diameterOffset": {"expression": "tool_number", "value": 0},
                  "tool_lengthOffset": {"expression": "tool_number", "value": 0}}
    before = {"owned_name": cam.RETAINED_LIBRARY_NAME, "source_url": "injected://source",
              "source_seed": seed, "local_urls": ["injected://foreign"],
              "local_names": ["Foreign.json"], "owned_url": None, "owned_seed": None,
              "source_parameters": parameters, "owned_parameters": None,
              "empty_is_none": False, "empty_bool": False, "empty_count": 0}
    monkeypatch.setattr(cam, "_RECALL", {"seed_library_before": before})
    return cam, before


def test_retained_seed_create_then_second_invocation_reuses_exact_url_and_raw_reply(retained_seed):
    cam, before = retained_seed
    assert cam._seed_library_select_args({}) == {
        "action": "create_library", "scope": "local", "library": cam.RETAINED_LIBRARY_NAME,
        "add_tools": [{"library_url": "injected://source", "index": 0}]}
    created = {"created_library": cam.RETAINED_LIBRARY_NAME, "scope": "local",
               "tool_count": 1, "url": "injected://owned"}
    record = cam._seed_library_selection(created)
    assert record == {"raw_reply": created, "url": "injected://owned", "tool_count": 1,
                      "created_this_run": True}
    before.update(local_urls=before["local_urls"] + [record["url"]],
                  local_names=before["local_names"] + [cam.RETAINED_LIBRARY_NAME.upper() + ".json"],
                  owned_url=record["url"], owned_seed=copy.deepcopy(before["source_seed"]),
                  owned_parameters=copy.deepcopy(before["source_parameters"]))
    assert cam._seed_library_select_args({}, reuse_only=True) == {
        "action": "list", "scope": "local", "library": "injected://owned"}
    listed = {"tool_count": 1, "tools": [{"index": 0}]}
    assert cam._seed_library_selection(listed) == {
        "raw_reply": listed, "url": "injected://owned", "tool_count": 1, "created_this_run": False}
    assert "created_library" not in listed and "url" not in listed


@pytest.mark.parametrize("fault", ["missing_identity", "malformed_name", "duplicate_url", "alias_collision",
                                     "encoded_name", "mismatched_seed", "bool_count"])
def test_retained_seed_unknown_or_collision_stops_before_selecting_mutation(retained_seed, fault):
    cam, before = retained_seed
    if fault == "missing_identity":
        del before["owned_url"]
    elif fault == "malformed_name":
        before["local_names"] = [None]
    elif fault == "duplicate_url":
        before["local_urls"] *= 2
        before["local_names"] *= 2
    elif fault == "alias_collision":
        before.update(local_urls=["injected://a", "injected://b"],
                      local_names=[cam.RETAINED_LIBRARY_NAME, cam.RETAINED_LIBRARY_NAME + ".json"],
                      owned_url="injected://a", owned_seed=before["source_seed"])
    elif fault == "encoded_name":
        before["local_names"] = ["unknown%20name.json"]
    elif fault == "mismatched_seed":
        before.update(local_names=[cam.RETAINED_LIBRARY_NAME], owned_url=before["local_urls"][0],
                      owned_seed={"geometry": {"diameter": 7.0}})
    else:
        before["empty_count"] = False
    with pytest.raises(AssertionError, match="fixed retained library input"):
        cam._seed_library_select_args({})


@pytest.mark.parametrize("size,existing,accepted", [(255, False, True), (256, False, False),
                                                    (256, True, True), (257, True, False)])
def test_retained_seed_census_cap_allows_reuse_but_reserves_creation_slot(retained_seed, size, existing, accepted):
    cam, before = retained_seed
    before.update(local_urls=[f"injected://{i}" for i in range(size)],
                  local_names=[f"Foreign{i}.json" for i in range(size)])
    if existing:
        before.update(owned_url=before["local_urls"][0], owned_seed=before["source_seed"],
                      owned_parameters=copy.deepcopy(before["source_parameters"]))
        before["local_names"][0] = cam.RETAINED_LIBRARY_NAME
    if accepted:
        assert cam._seed_library_ready(before) is True
    else:
        with pytest.raises(AssertionError, match="fixed retained library input"):
            cam._seed_library_ready(before)


def test_second_invocation_missing_asset_has_no_create_fallback(retained_seed):
    cam, _before = retained_seed
    with pytest.raises(ValueError, match="no create fallback"):
        cam._seed_library_select_args({}, reuse_only=True)


@pytest.mark.parametrize("fault", ["wrong_content", "changed_source", "new_foreign_asset",
                                     "removed_foreign_asset", "missing_additions", "wrong_url"])
def test_retained_seed_independent_read_rejects_wrong_effect_and_collateral_change(retained_seed, fault):
    cam, before = retained_seed
    reply = cam._seed_library_selection({"created_library": cam.RETAINED_LIBRARY_NAME, "scope": "local",
                                         "tool_count": 1, "url": "injected://owned"})
    cam._RECALL["seed_library_reply"] = reply
    after = {"url": reply["url"], "retained_url": reply["url"], "count": 1, "is_none": False,
             "source_seed": copy.deepcopy(before["source_seed"]),
             "stored_seed": copy.deepcopy(before["source_seed"]),
             "source_parameters": copy.deepcopy(before["source_parameters"]),
             "stored_parameters": copy.deepcopy(before["source_parameters"]),
             "local_urls": before["local_urls"] + [reply["url"]],
             "added": [{"url": reply["url"], "name": cam.RETAINED_LIBRARY_NAME + ".json"}],
             "cleanup_attempted": False}
    assert cam._seed_library_stored(after) is True
    empty = dict(after, count=0, stored_seed=None, stored_parameters=None)
    assert cam._seed_library_empty(empty) is True
    if fault in {"wrong_content", "changed_source"}:
        after["stored_seed" if fault == "wrong_content" else "source_seed"]["geometry"]["diameter"] = 7.0
    elif fault == "new_foreign_asset":
        after["local_urls"].append("injected://unrelated-new")
    elif fault == "removed_foreign_asset":
        after["local_urls"].remove("injected://foreign")
    elif fault == "missing_additions":
        del after["added"]
    else:
        after["url"] = "injected://other"
    with pytest.raises(AssertionError, match="exact URL and complete stored content"):
        cam._seed_library_stored(after)


def test_retained_seed_script_arguments_compile_without_running_sdk_and_keep_refusal_row(retained_seed):
    cam, before = retained_seed
    cam._RECALL["seed_library_reply"] = {"url": "injected://owned", "created_this_run": True, "tool_count": 1}
    rows = cam._SEEDED_LIBRARY_ROWS
    assert len(rows) == 14 and rows[1][1]["library"] == "FWSeedGuardRefused"
    assert rows[1][1]["add_tools"] == [{"from_type": "flat end mill"}]
    for tool, arguments, _expect, _save in rows:
        if tool == "sys_execute_script":
            value = arguments({})
            assert value["read_only"] is True
            compile(value["script"], "seed-observer", "exec")
            assert "OWNED_NAME" not in value["script"] and "EXPECTED_COUNT" not in value["script"]
    assert "uuid" not in cam._seed_library_before({})["script"]


def _added_seed_inputs(before):
    """Injected new-entry identity and the explicit empty-target numbering transformation."""
    seed, parameters = copy.deepcopy(before["source_seed"]), copy.deepcopy(before["source_parameters"])
    seed["guid"] = "injected-new-entry-guid"
    seed["post-process"].update(number=1, **{"diameter-offset": 1, "length-offset": 1})
    parameters["tool_number"].update(expression="1", value=1)
    for name in ("tool_diameterOffset", "tool_lengthOffset"):
        parameters[name]["value"] = 1
    return seed, parameters


def _seed_readback(before, reply, seed, parameters):
    """A separate injected native read with the exact source and selected-root footprint."""
    return {"url": reply["url"], "retained_url": reply["url"], "count": 1, "is_none": False,
            "source_seed": copy.deepcopy(before["source_seed"]),
            "source_parameters": copy.deepcopy(before["source_parameters"]),
            "stored_seed": copy.deepcopy(seed), "stored_parameters": copy.deepcopy(parameters),
            "local_urls": before["local_urls"] + ([reply["url"]] if reply["created_this_run"] else []),
            "added": [{"url": reply["url"], "name": before["owned_name"]}] if reply["created_this_run"] else [],
            "cleanup_attempted": False}


@pytest.mark.parametrize("initial", ["missing", "create-copy", "added-entry"])
def test_retained_seed_all_fourteen_rows_keep_create_add_and_full_reuse_distinct(retained_seed, monkeypatch, initial):
    import conftest

    cam, before = retained_seed
    items = {item.primitive.name: item for item in conftest.register_all_tools()}
    server = conftest.load_mcp_server().SimpleMCPServer()
    monkeypatch.setattr(importlib.import_module("verify_core"), "_RECALL", cam._RECALL)
    added, added_parameters = _added_seed_inputs(before)
    if initial != "missing":
        before.update(local_urls=before["local_urls"] + ["injected://owned"],
                      local_names=before["local_names"] + [cam.RETAINED_LIBRARY_NAME],
                      owned_url="injected://owned",
                      owned_seed=copy.deepcopy(added if initial == "added-entry" else before["source_seed"]),
                      owned_parameters=copy.deepcopy(added_parameters if initial == "added-entry" else before["source_parameters"]))
    rows, context, dispatched = cam._SEEDED_LIBRARY_ROWS, {}, []
    assert len(rows) == 14
    for index, (tool, arguments, check, save) in enumerate(rows):
        args = arguments(context) if callable(arguments) else dict(arguments)
        assert server._validate_tool_arguments(tool, items[tool], args) is None
        if tool == "sys_execute_script":
            assert args["read_only"] is True
            compile(args["script"], "inert seed observer", "exec")
        dispatched.append((tool, args.get("action")))
        if index in (0, 11):
            payload = copy.deepcopy(before)
        elif index == 1:
            assert not check.missing("takes exactly 'library_url'; action='add' only; Nothing was created")
            continue
        elif index in (2, 12):
            payload = ({"created_library": cam.RETAINED_LIBRARY_NAME, "scope": "local",
                        "tool_count": 1, "url": "injected://owned"} if args["action"] == "create_library"
                       else {"tool_count": 1, "tools": [{"index": 0}]})
        elif index in (3, 6, 9):
            payload = {"tool_count": 0 if index == 6 else 1}
        elif index in (4, 7, 10, 13):
            reply = cam._RECALL["seed_library_reply"]
            seed = added if index == 10 else before["source_seed"] if reply["created_this_run"] else before["owned_seed"]
            parameters = added_parameters if index == 10 else before["source_parameters"] if reply["created_this_run"] else before["owned_parameters"]
            payload = _seed_readback(before, reply, seed, parameters)
            if index == 7:
                payload.update(count=0, stored_seed=None, stored_parameters=None)
        elif index == 5:
            payload = {"removed": 1, "tool_count": 0}
        else:
            assert index == 8
            payload = {"added": 1, "tool_count": 1, "assigned_tool_numbers": [1], "verified_in_memory_only": False}
        assert check(payload) is True
        if save:
            context[save[0]] = save[1](payload)
        if index == 10:
            before.update(local_urls=payload["local_urls"],
                          local_names=before["local_names"] + ([cam.RETAINED_LIBRARY_NAME] if initial == "missing" else []),
                          owned_url=payload["url"], owned_seed=copy.deepcopy(added),
                          owned_parameters=copy.deepcopy(added_parameters))
    assert dispatched[5:11] == [("cam_edit_tools", "remove"), ("cam_edit_tools", "list"),
        ("sys_execute_script", None), ("cam_edit_tools", "add"), ("cam_edit_tools", "list"),
        ("sys_execute_script", None)]
    assert dispatched[-2:] == [("cam_edit_tools", "list"), ("sys_execute_script", None)]
    assert cam._RECALL["seed_library_reply"]["created_this_run"] is False


@pytest.mark.parametrize("fault", ["guid-missing", "guid-empty", "guid-source", "number", "diameter-offset",
    "length-offset", "consistent-wrong-number", "geometry", "holder", "preset", "unrelated-key", "unknown-key"])
def test_retained_seed_add_signature_refuses_undeclared_changes_or_unread_identity(retained_seed, fault):
    cam, before = retained_seed
    seed, parameters = _added_seed_inputs(before)
    assert cam._seed_library_add_signature(before["source_seed"], seed, parameters) is True
    if fault == "guid-missing":
        del seed["guid"]
    elif fault == "guid-empty":
        seed["guid"] = " "
    elif fault == "guid-source":
        seed["guid"] = before["source_seed"]["guid"].upper()
    elif fault in {"number", "diameter-offset", "length-offset"}:
        seed["post-process"][fault] = 2
    elif fault == "consistent-wrong-number":
        seed["post-process"].update(number=2, **{"diameter-offset": 2, "length-offset": 2})
        parameters["tool_number"]["expression"] = "2"
        for row in parameters.values():
            row["value"] = 2
    elif fault == "geometry":
        seed["geometry"]["diameter"] += 1
    elif fault == "holder":
        seed["holder"]["segments"][0]["height"] += 1
    elif fault == "preset":
        seed["start-values"]["presets"][0]["name"] = "Changed"
    else:
        seed["description" if fault == "unrelated-key" else "unexpected"] = "Changed"
    assert cam._seed_library_add_signature(before["source_seed"], seed, parameters) is False


@pytest.mark.parametrize("fault", ["missing", "unread-expression", "constant-offset", "complex-offset",
                                  "unread-value", "bool-value", "wrong-value"])
def test_retained_seed_parameter_relationship_refuses_before_mutation(retained_seed, fault):
    cam, before = retained_seed
    if fault == "missing":
        del before["source_parameters"]["tool_lengthOffset"]
    else:
        key, value = {"unread-expression": ("expression", None), "constant-offset": ("expression", "0"),
            "complex-offset": ("expression", "tool_number + 0"), "unread-value": ("value", None),
            "bool-value": ("value", False), "wrong-value": ("value", 1)}[fault]
        before["source_parameters"]["tool_lengthOffset"][key] = value
    with pytest.raises(AssertionError, match="fixed retained library input"):
        cam._seed_library_select_args({})


@pytest.mark.parametrize("assigned", [None, [], [0], [True], [1, 2]])
def test_retained_seed_add_requires_exact_actual_assignment(assigned, retained_seed):
    cam, _before = retained_seed
    assert cam._seed_library_added({"added": 1, "tool_count": 1, "assigned_tool_numbers": [1],
                                    "verified_in_memory_only": False}) is True
    assert cam._seed_library_added({"added": 1, "tool_count": 1, "assigned_tool_numbers": assigned,
                                    "verified_in_memory_only": False}) is False


@pytest.mark.parametrize("field", ["guid", "number", "diameter-offset", "length-offset"])
def test_retained_seed_reuse_compares_all_acquired_identity_and_numbering_fields(retained_seed, field):
    cam, before = retained_seed
    seed, parameters = _added_seed_inputs(before)
    before.update(local_urls=before["local_urls"] + ["injected://owned"],
                  local_names=before["local_names"] + [cam.RETAINED_LIBRARY_NAME],
                  owned_url="injected://owned", owned_seed=seed, owned_parameters=parameters)
    assert cam._seed_library_ready(before) is True
    reply = cam._seed_library_selection({"tool_count": 1, "tools": [{"index": 0}]})
    cam._RECALL["seed_library_reply"] = reply
    payload = _seed_readback(before, reply, seed, parameters)
    assert cam._seed_library_stored(payload) is True
    if field == "guid":
        payload["stored_seed"][field] = "injected-different-reuse-guid"
    else:
        payload["stored_seed"]["post-process"][field] = 2
    with pytest.raises(AssertionError, match="complete stored content"):
        cam._seed_library_stored(payload)


@pytest.mark.parametrize("observed", [True, False, None])
def test_actual_act_opt_out_keeps_the_observation_without_claiming_no_entitlement(
        sweep, runner_spy, monkeypatch, observed):
    calls, tables = runner_spy
    monkeypatch.setattr(sweep, "ACTS", [("ACT unit", None, [
        ("doc_get", lambda ctx: pytest.fail("excluded act arguments resolved"), "ok", None)], None)])
    monkeypatch.setattr(sweep, "ACT_NEEDS", {"ACT unit": "machining_extension"})
    monkeypatch.setattr(sys.modules["verify_runner"], "probe_capabilities",
                        lambda names: {"machining_extension": observed})
    assert sweep.run(False) == 0
    reason = dict(tables[0])["doc_get"]
    assert reason == ("skipped: not-in-scope: machining_extension needs "
                      f"asked=False measured={observed!r}")
    assert calls == ["doc_get", "sys_get_preferences"]


def test_actual_runner_stops_missing_selected_tool_before_resolving_its_arguments(sweep, runner_spy, monkeypatch):
    calls, tables = runner_spy
    args = lambda ctx: pytest.fail("arguments resolved before admission")
    monkeypatch.setattr(sweep, "ACTS", [("ACT unit", None, [("doc_new", args, "ok", None)], None)])
    assert sweep.run(False) == 1
    assert calls == ["doc_get", "sys_get_preferences"] and tables == []


def test_actual_runner_stops_requested_unavailable_native_tier_before_any_write(sweep, runner_spy):
    calls, tables = runner_spy
    core = sweep.verify_core
    core.MACHINE["tiers"]["native_script"] = True
    Path(core._MACHINE_READ[2]).write_text(json.dumps(core.MACHINE), encoding="utf-8")
    assert sweep.run(False) == 1
    assert calls == ["doc_get", "sys_get_preferences"] and tables == []


def test_actual_family_runner_stops_native_off_before_owned_creation(sweep, runner_spy, monkeypatch, capsys):
    calls, tables = runner_spy
    runner = importlib.import_module("verify_runner")
    families = {"ACT unit": "injected-family"}
    monkeypatch.setattr(sweep, "FAMILY_PROGRAM", families)
    monkeypatch.setattr(sweep, "FAMILY_RECEIPTS", False)
    monkeypatch.setattr(runner, "family_names", lambda acts: families)
    monkeypatch.setattr(runner, "ordered_acts", lambda acts: acts)
    monkeypatch.setattr(runner, "fixture_steps", lambda *args, **kwargs: [])
    monkeypatch.setattr(sweep, "registered_tools", lambda *args, **kwargs: (
        ["doc_get", "sys_get_preferences", "sys_execute_script"], ()))
    assert sweep.run(False) == 1
    assert calls == ["doc_get", "sys_get_preferences"] and tables == []
    assert "tiers.native_script=false" in capsys.readouterr().out


@pytest.mark.parametrize("verdict", [False, None])
def test_actual_runner_stops_requested_unavailable_extension_before_any_write(sweep, runner_spy, monkeypatch, verdict):
    calls, tables = runner_spy
    core = sweep.verify_core
    core.MACHINE["tiers"]["machining_extension"] = True
    Path(core._MACHINE_READ[2]).write_text(json.dumps(core.MACHINE), encoding="utf-8")
    runner = importlib.import_module("verify_runner")
    observed = []
    monkeypatch.setattr(runner, "probe_capabilities", lambda names: observed.append(names) or {"machining_extension": verdict})
    assert sweep.run(False) == 1
    assert observed == [["machining_extension"]]
    assert calls == ["doc_get", "sys_get_preferences"] and tables == []


def test_actual_runner_cloud_admission_is_only_a_read_before_folder_creation(sweep, runner_spy, monkeypatch):
    calls, tables = runner_spy
    core = sweep.verify_core
    core.MACHINE["tiers"]["cloud"] = True
    core.MACHINE["cloud"].update(hub="Injected Hub", project="Injected Project", folder="operator label")
    Path(core._MACHINE_READ[2]).write_text(json.dumps(core.MACHINE), encoding="utf-8")
    previous = sweep.call
    def wire(tool, args):
        if tool == "data_get":
            calls.append(tool)
            return True, "injected unavailable cloud"
        return previous(tool, args)
    monkeypatch.setattr(sweep, "call", wire)
    assert sweep.run(False) == 1
    assert calls == ["doc_get", "sys_get_preferences", "data_get"] and tables == []


def test_required_registration_is_selected_scope_not_the_global_program(sweep, policy):
    preflight = importlib.import_module("preflight")
    core = sweep.verify_core
    config = json.loads(policy.example_text())
    rows = core.tiered([
        ("model_inspect", {}, "ok", None),
        ("sys_execute_script", {"script": "unclassified"}, "ok", None),
        ("cam_edit_operation", {}, core.Unless("machining_extension", "refused"), None),
        ("data_get", {}, "ok", None),
        ("sys_set_preferences", {}, "ok", None)])
    rows.append(core._dwell(0))
    needed = preflight.required_tools(config, rows, core.step_conditions)
    assert needed == {"doc_get", "sys_get_preferences", "model_inspect", "cam_edit_operation"}
    assert preflight.required_tools(config, rows[:1], core.step_conditions) == {
        "doc_get", "sys_get_preferences", "model_inspect"}
    config["tiers"]["cloud"] = True
    assert "data_get" in preflight.required_tools(config, rows, core.step_conditions)


def test_source_closed_chain_unit_omits_home_seed_consumers_and_cleanup_together(sweep, policy):
    cam = importlib.import_module("verify_acts_cam")
    core = sweep.verify_core
    rows = core.tiered(cam._chain_transformed_rows())
    assert len(rows) == 16
    assert rows[0][0] == "doc_get" and rows[-1][0] == "doc_close"
    assert sum(tool == "sys_execute_script" for tool, *_ in rows) == 3
    for tool, _args, expect, _save in rows:
        assert {("native_script", "needs"), ("library_writes", "needs")} <= set(core.step_conditions(expect))
        assert not core.gate_allows({"native_script": True, "library_writes": None}, expect)
    assert [row for row in rows if core.gate_allows({"native_script": True, "library_writes": None}, row[2])] == []
    declaration_hashes = {core.step_script_declaration(expect)["sha256"]
        for tool, _args, expect, _save in rows if tool == "sys_execute_script"}
    assert declaration_hashes == {policy.effect_declaration(script, [])["sha256"]
                                 for script in (cam._CHAIN_BUILD, cam._CHAIN_READ)}


def test_script_effects_survive_mixed_gates_without_changing_effect_predicate(sweep):
    core = sweep.verify_core
    predicate = lambda payload: payload["count"] == 2
    source = "def run(context): pass"
    effect = core.ScriptEffects(source, [], core.Independent(predicate, ["model_extrude"], "tool:model_inspect"))
    expect = core.Needs("native_script", core.Unless("machining_extension", core.Parked("comment", effect)))
    assert core.step_script_declaration(expect) == effect.declaration
    assert core._unparked(expect) is predicate
    with pytest.raises(ValueError, match="conflicting"):
        core.step_script_declaration(core.ScriptEffects("changed", [], effect))


def test_runner_forwards_validated_declaration_outside_the_wire_arguments(sweep, monkeypatch):
    core = sweep.verify_core
    source = "def run(context): pass"
    expect = core.ScriptEffects(source, [], lambda payload: payload["count"] == 2)
    args = {"script": source, "read_only": True}
    observed = []
    def wire(tool, arguments, **metadata):
        observed.append((tool, arguments, metadata))
        return False, {"count": 2}
    monkeypatch.setattr(sweep, "call", wire)
    rows = sweep.run_steps([("sys_execute_script", args, expect, None)], {}, sleep_s=0)
    assert rows == [("sys_execute_script", "pass", "")]
    assert observed == [("sys_execute_script", args, {"script_declaration": expect.declaration})]
    observed.clear()
    with pytest.raises(SystemExit, match="changed before transport"):
        sweep.run_steps([("sys_execute_script", {**args, "script": source + "\nchanged"}, expect, None)], {}, sleep_s=0)
    assert observed == []


@pytest.fixture
def frame_case(sweep):
    rows = []
    for name in ("Hidden", "Visible"):
        rows += [("model_create_component", {"name": name, "activate": True}, "ok", None),
                 ("sketch_create", {"name": name + "Sketch", "plane": "xy"}, "ok", None),
                 ("sketch_add_geometry", {"sketch_name": name + "Sketch", "geometry": [
                     {"kind": "rectangle", "x": 0, "y": 0, "width": 10, "height": 10}]}, "ok", None),
                 ("model_extrude", {"sketch_name": name + "Sketch", "distance": "10 mm"}, "ok", None)]
    layout = {"home": {"HiddenSketch": "Hidden", "VisibleSketch": "Visible"},
              "components": {"Hidden", "Visible"}, "patterned": set(),
              "planes": {"HiddenSketch": "xy", "VisibleSketch": "xy"},
              "boxes": {"Hidden": [0, 10, 0, 10], "Visible": [12, 22, 0, 10]}}
    return rows, layout


def test_all_on_frame_payloads_and_predicates_match_the_unmodified_spatial_pass(sweep, frame_case):
    layout = importlib.import_module("verify_layout")
    source = subprocess.run(["git", "show", "HEAD:tests/live/verify_layout.py"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, check=True).stdout
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "_framed")
    namespace = dict(layout.__dict__)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "baseline-frame-source", "exec"), namespace)
    core = sweep.verify_core
    for group in ("tiers", "allow"):
        core.MACHINE[group].update({name: True for name in core.MACHINE[group]})
    rows, bounds = frame_case
    expected = namespace["_framed"](rows, bounds)
    actual = layout._framed(core.scope_unit(rows[:4], ["native_script"]) + rows[4:], bounds)
    assert [(tool, args, core._unparked(expect), save) for tool, args, expect, save in actual] == expected


def test_all_on_whole_program_frame_payloads_and_inner_predicates_match_previous_passes(sweep):
    program = importlib.import_module("verify_program")
    layout = importlib.import_module("verify_layout")
    core = sweep.verify_core
    for group in ("tiers", "allow"):
        core.MACHINE[group].update({name: True for name in core.MACHINE[group]})
    namespace = dict(program.__dict__)
    for filename, names, globals_ in (("verify_layout.py", ["_framed"], layout.__dict__),
                                      ("verify_program.py", ["_checked_sketch_frames"], namespace)):
        source = subprocess.run(["git", "show", "HEAD:tests/live/" + filename],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, check=True).stdout
        nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in names]
        loaded = dict(globals_)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "baseline-" + filename, "exec"), loaded)
        namespace.update({name: loaded[name] for name in names})
    compile_node = next(node for node in ast.parse(Path(program.__file__).read_text(encoding="utf-8")).body
                        if isinstance(node, ast.FunctionDef) and node.name == "compile_program")
    exec(compile(ast.Module(body=[compile_node], type_ignores=[]), "baseline-compiler", "exec"), namespace)
    before = namespace["compile_program"](program._RAW_ACT_PROGRAM)["acts"]
    after = program.compile_program(program._RAW_ACT_PROGRAM)["acts"]
    receipts = importlib.import_module("verify_receipts")
    root = Path(__file__).resolve().parents[2]
    substitutions = receipts._runtime_substitutions(root)
    def wire_rows(acts):
        return [(name, pre, [(tool, args, core._unparked(expect), save) for tool, args, expect, save in narrative],
                 [(tool, args, core._unparked(expect), save) for tool, args, expect, save in fallback] if fallback is not None else None)
                for name, pre, narrative, fallback in acts]
    assert receipts._program_value(wire_rows(before), root, substitutions) == receipts._program_value(
        wire_rows(after), root, substitutions)


def test_restricted_frames_keep_omission_rows_but_never_target_excluded_producers(sweep, frame_case):
    layout = importlib.import_module("verify_layout")
    core = sweep.verify_core
    rows, bounds = frame_case
    gated = core.scope_unit(rows[:4], ["native_script"]) + rows[4:]
    result = layout._framed(gated, bounds)
    assert result[:4] == gated[:4]
    frames = [step for step in result if step[0] == "view_set"]
    assert frames and all("Hidden:1" not in step[1]["focus"] for step in frames)
    assert any("Visible:1" in step[1]["focus"] for step in frames)


def test_unless_producer_does_not_suppress_an_unconditional_frame_with_an_unbuilt_standing_view(sweep, frame_case):
    layout = importlib.import_module("verify_layout")
    core = sweep.verify_core
    rows, bounds = frame_case
    bounds["boxes"]["Visible"] = [2, 4, 2, 4]
    gated = [(tool, args, core.Unless("machining_extension", expect), save)
             for tool, args, expect, save in rows[:4]] + rows[4:]
    frames = [step for step in layout._framed(gated, bounds) if step[0] == "view_set"]
    visible = [step for step in frames if "Visible:1" in step[1]["focus"]]
    assert visible, "a held conditional camera cannot stand in for the admitted producer's camera"
    assert all("Hidden:1" not in step[1]["focus"] and core.step_conditions(step[2]) == () for step in visible)


def test_hoisted_sketch_frames_inherit_own_gates_and_off_sketches_remain_omitted(sweep, monkeypatch):
    program = importlib.import_module("verify_program")
    core = sweep.verify_core
    owner = "scope-test-owner"
    monkeypatch.setitem(program._HOIST_FRAMES, owner, {"ProbeSketch": (["ProbeSketch"], "top")})
    rows = [("sketch_create", {"name": "ProbeSketch", "plane": "xy"}, "ok", None),
            ("sketch_add_geometry", {"sketch_name": "ProbeSketch", "geometry": [
                {"kind": "rectangle", "x": 0, "y": 0, "width": 10, "height": 10}]}, "ok", None)]
    gated = core.scope_unit(rows, ["native_script"])
    bounds = {"planes": {"ProbeSketch": "xy"}}
    assert program._checked_sketch_frames(owner, gated, {}, bounds) == gated
    core.MACHINE["tiers"]["native_script"] = True
    result = program._checked_sketch_frames(owner, gated, {}, bounds)
    frames = [step for step in result if step[0] == "view_set"]
    assert len(frames) == 1 and core.step_conditions(frames[0][2]) == (("native_script", "needs"),)


def test_guided_sweep_entire_owned_story_is_withheld_when_native_is_off(sweep):
    source = importlib.import_module("verify_acts_model_sweep")
    core = sweep.verify_core
    rows = core.tiered(source._guided_sweep_rows())
    assert len(rows) == 20 and sum(row[0] == "sys_execute_script" for row in rows) == 3
    assert all(("native_script", "needs") in core.step_conditions(row[2]) for row in rows)
    assert [row for row in rows if core.gate_allows({"native_script": True}, row[2])] == []
    assert rows[0][0] == "doc_get" and rows[-1][0] == "doc_close"


def test_guided_sweep_literals_bind_exact_emitted_bytes_without_persistent_permissions(sweep, policy):
    source = importlib.import_module("verify_acts_model_sweep")
    core = sweep.verify_core
    core.MACHINE["tiers"]["native_script"] = True
    context = {"guided_doc": "session:injected-guided", "guided_story": "session:injected-story"}
    rows = core.tiered(source._guided_sweep_rows())
    assert all(core.gate_allows({"native_script": True}, row[2]) for row in rows)
    emitted = []
    for tool, args, expect, save in rows:
        if tool != "sys_execute_script":
            continue
        arguments = args(context) if callable(args) else dict(args)
        declaration = core.step_script_declaration(expect)
        assert declaration == policy.effect_declaration(arguments["script"], [])
        assert arguments["read_only"] is False
        assert policy.require_call(core.MACHINE, tool, arguments, declaration["effects"]) is None
        with pytest.raises(SystemExit, match="changed before transport"):
            policy.declared_effects(tool, {**arguments, "script": arguments["script"] + "\nchanged"}, declaration)
        emitted.append(arguments["script"])
    assert emitted == [source._GUIDED_SWEEP_CREATE, source._GUIDED_SWEEP_NATIVE, source._GUIDED_SWEEP_NATIVE]


@pytest.mark.parametrize("factory", ["_guided_sweep_rows", "_sweep_scope_edit_rows", "_loft_edit_rows", "_d_loft_rows",
                                     "advanced_feature_edit_rows", "_side_disclosure_rows"])
def test_scoped_story_all_on_args_predicates_and_saved_callbacks_match_the_original_factory(sweep, factory):
    module_name = ({"advanced_feature_edit_rows": "verify_acts_feature_advanced",
                    "_side_disclosure_rows": "verify_acts_model_solids"}.get(factory, "verify_acts_model_sweep"))
    source = importlib.import_module(module_name)
    core = sweep.verify_core
    original = subprocess.run(["git", "show", "HEAD:tests/live/" + module_name + ".py"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, check=True, encoding="utf-8").stdout
    node = next(node for node in ast.parse(original).body if isinstance(node, ast.FunctionDef)
                and node.name == factory)
    namespace = dict(source.__dict__)
    exec(compile(ast.Module(body=[node], type_ignores=[]), source.__file__, "exec"), namespace)
    before = namespace[factory]()
    after = getattr(source, factory)()
    receipts = importlib.import_module("verify_receipts")
    root = Path(__file__).resolve().parents[2]
    substitutions = receipts._runtime_substitutions(root)
    def payload(rows):
        return [(tool, args, core._unparked(expect), save) for tool, args, expect, save in rows]
    assert receipts._program_value(payload(before), root, substitutions) == receipts._program_value(
        payload(after), root, substitutions)
    def code(value):
        if isinstance(value, CodeType):
            return (value.co_code, value.co_names, value.co_varnames, value.co_freevars,
                    tuple(code(item) for item in value.co_consts))
        return value
    for original_row, current_row in zip(payload(before), payload(after)):
        for original_value, current_value in zip(original_row, current_row):
            if callable(original_value):
                assert code(original_value.__code__) == code(current_value.__code__)
        if original_row[3] is not None:
            assert code(original_row[3][1].__code__) == code(current_row[3][1].__code__)


@pytest.fixture
def sweep_scope_cases(sweep):
    source = importlib.import_module("verify_acts_model_sweep")
    rows = sweep.verify_core.tiered(source._sweep_scope_edit_rows())
    starts = [index for index, row in enumerate(rows) if row[0] == "doc_get"] + [len(rows)]
    cases = [rows[start:end] for start, end in zip(starts, starts[1:])]
    assert [len(case) for case in cases] == [25, 29, 39]
    return source, cases


def test_r7_scope_off_withholds_its_whole_story_but_keeps_typed_r8_r9(sweep, policy, sweep_scope_cases):
    _source, cases = sweep_scope_cases
    core = sweep.verify_core
    r7, r8, r9 = cases
    assert all(("native_script", "needs") in core.step_conditions(row[2]) for row in r7)
    assert sum(row[0] == "sys_execute_script" for row in r7) == 4
    for measured in (True, False, None):
        assert not any(core.gate_allows({"native_script": measured}, row[2]) for row in r7)
        assert all(core.gate_allows({"native_script": measured}, row[2]) for row in r8 + r9)
    assert r7[0][0] == "doc_get" and r7[-1][0] == "doc_close"
    needed = importlib.import_module("preflight").required_tools(
        core.MACHINE, r7 + r8 + r9, core.step_conditions)
    assert "sys_execute_script" not in needed and "model_sweep" in needed


def test_r7_literal_scripts_admit_local_native_scope_and_bind_resolved_owned_args(sweep, policy, sweep_scope_cases):
    source, cases = sweep_scope_cases
    core = sweep.verify_core
    core.MACHINE["tiers"]["native_script"] = True
    context = {"scope_r7_doc": "session:injected-r7"}
    assert all(core.gate_allows({"native_script": True}, row[2]) for case in cases for row in case)
    emitted = []
    for tool, args, expect, _save in cases[0]:
        if tool != "sys_execute_script":
            continue
        arguments = args(context)
        declaration = core.step_script_declaration(expect)
        assert declaration == policy.effect_declaration(arguments["script"], [])
        assert arguments["read_only"] is False and arguments["expect_document"] == context["scope_r7_doc"]
        assert policy.require_call(core.MACHINE, tool, arguments, declaration["effects"]) is None
        with pytest.raises(SystemExit, match="changed before transport"):
            policy.declared_effects(tool, {**arguments, "script": arguments["script"] + "\nchanged"}, declaration)
        emitted.append(arguments["script"])
    assert emitted == [source._SWEEP_GUIDE_FIXTURE] + [source._SWEEP_GUIDE_CENSUS] * 3


@pytest.mark.parametrize("excluded", ["native_script", "cloud_tier", "library_writes",
                                     "preference_writes", "addin_reload"])
@pytest.mark.parametrize("factory,native_count,last_tool", [
    ("_loft_edit_rows", 1, "doc_close"), ("_d_loft_rows", 5, "doc_get")])
def test_unknown_loft_native_unit_cannot_leave_typed_mates_or_cleanup_when_a_requirement_is_off(
        sweep, policy, excluded, factory, native_count, last_tool):
    source = importlib.import_module("verify_acts_model_sweep")
    core = sweep.verify_core
    rows = core.tiered(getattr(source, factory)())
    assert sum(row[0] == "sys_execute_script" for row in rows) == native_count
    assert rows[0][0] == "doc_get" and rows[-1][0] == last_tool
    config = core.MACHINE
    for group in ("tiers", "allow"):
        config[group].update({name: True for name in config[group]})
    config["cloud"].update(hub="unit hub", project="unit project", folder="unit folder")
    observed = {"native_script": True, "cloud_tier": True}
    assert all(core.gate_allows(observed, row[2]) for row in rows)
    group, key = policy.SWITCHES[excluded]
    config[group][key] = False
    assert not any(core.gate_allows(observed, row[2]) for row in rows)
    needed = importlib.import_module("preflight").required_tools(config, rows, core.step_conditions)
    assert needed == {"doc_get", "sys_get_preferences"}


@pytest.mark.parametrize("excluded", ["native_script", "cloud_tier", "library_writes",
                                     "preference_writes", "addin_reload"])
def test_shared_advanced_native_collection_has_no_surviving_typed_mates_after_opt_out(sweep, policy, excluded):
    source = importlib.import_module("verify_acts_feature_advanced")
    core = sweep.verify_core
    rows = core.tiered(source.advanced_feature_edit_rows())
    assert rows[0][0] == "doc_get" and rows[-1][0] == "doc_close"
    assert sum(row[0] == "sys_execute_script" for row in rows) > 20
    assert any(row[3] and row[3][0] == "advanced_home" for row in rows)
    assert any(row[0] == "model_edit_feature" for row in rows)
    config = core.MACHINE
    for group in ("tiers", "allow"):
        config[group].update({name: True for name in config[group]})
    config["cloud"].update(hub="unit hub", project="unit project", folder="unit folder")
    observed = {"native_script": True, "cloud_tier": True}
    assert all(core.gate_allows(observed, row[2]) for row in rows)
    group, key = policy.SWITCHES[excluded]
    config[group][key] = False
    assert not any(core.gate_allows(observed, row[2]) for row in rows)
    needed = importlib.import_module("preflight").required_tools(config, rows, core.step_conditions)
    assert needed == {"doc_get", "sys_get_preferences"}


@pytest.mark.parametrize("excluded", ["native_script", "cloud_tier", "library_writes",
                                     "preference_writes", "addin_reload"])
def test_rotated_side_unit_cannot_keep_typed_edits_without_its_native_fixture(sweep, policy, excluded):
    source = importlib.import_module("verify_acts_model_solids")
    core = sweep.verify_core
    rows = core.tiered(source._side_disclosure_rows())
    assert len(rows) == 64 and sum(row[0] == "sys_execute_script" for row in rows) == 28
    assert rows[0][3][0] == "side_disclosure_home" and rows[-1][0] == "doc_close"
    assert sum(row[0] == "design_delete_feature" for row in rows) == 7
    config = core.MACHINE
    for group in ("tiers", "allow"):
        config[group].update({name: True for name in config[group]})
    config["cloud"].update(hub="unit hub", project="unit project", folder="unit folder")
    observed = {"native_script": True, "cloud_tier": True}
    assert all(core.gate_allows(observed, row[2]) for row in rows)
    group, key = policy.SWITCHES[excluded]
    config[group][key] = False
    assert not any(core.gate_allows(observed, row[2]) for row in rows)
    needed = importlib.import_module("preflight").required_tools(config, rows, core.step_conditions)
    assert needed == {"doc_get", "sys_get_preferences"}


@pytest.mark.parametrize("excluded", ["native_script", "cloud_tier", "library_writes",
                                     "preference_writes", "addin_reload"])
def test_lookup_family_cannot_leave_consumers_when_unknown_native_requirements_are_off(sweep, policy, excluded):
    core = sweep.verify_core
    for group in ("tiers", "allow"):
        core.MACHINE[group].update({name: True for name in core.MACHINE[group]})
    core.MACHINE["cloud"].update(hub="unit hub", project="unit project", folder="unit folder")
    name = "ACT 14 - LOOKUP TARGETING"
    rows = next(act[2] for act in sweep.ACTS if act[0] == name)
    caps = sweep.ACT_NEEDS.get(name)
    caps = caps if isinstance(caps, tuple) else (caps,) if caps is not None else ()
    conditions = tuple((cap, "needs") for cap in caps)
    observed = {"native_script": True, "cloud_tier": True}
    annotated = [core.condition_expect(conditions, row[2]) for row in rows]
    assert any(row[3] and row[3][0] == "seed_library_reply" for row in rows)
    assert all(core.gate_allows(observed, expect) for expect in annotated)
    group, key = policy.SWITCHES[excluded]
    core.MACHINE[group][key] = False
    assert not any(core.gate_allows(observed, expect) for expect in annotated)
