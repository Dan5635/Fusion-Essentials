# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Family stamps refuse stale closures and unsupported evidence provenance."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import types

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live"))
import verify_core
import verify_receipts as receipts
import verify_runner
import tool_verify


def _lifecycle_observations(census):
    """Return valid compact reload observations for data-level lifecycle checks."""
    att = {"implementation_fingerprint": "a" * 64, "schema_fingerprint": "b" * 64,
           "load_id": "load-old", "session_id": "session-old", "complete": True,
           "loaded_matches_source": True}
    after = dict(att, load_id="load-new", session_id="session-new")
    keys = ("new_load_and_session", "same_implementation_and_schema", "tool_census_matches",
            "old_transport_refused_empty_404", "fresh_session_changed",
            "fresh_session_read_new_handle", "nonce_read_back_before_reload", "reload_scheduled",
            "nonce_survived_reload", "old_handle_refused", "stale_write_absent",
            "fresh_handle_write_readback", "recovery_parameter_removed",
            "scratch_closed_and_home_restored")
    home_rows = [{"document_handle": "session:home", "name": "Home", "is_active": True},
                 {"document_handle": "session:other", "name": "Other"}]
    post_rows = [{"document_handle": "session:home-new", "name": "Home"},
                 {"document_handle": "session:other-new", "name": "Other"},
                 {"document_handle": "session:scratch-new", "name": "Scratch", "is_active": True}]
    home = {"handle": "session:home", "document_id": "urn:home", "name": "Home",
            "complete": True, "open_count": 2, "rows": home_rows}
    post = {"handle": "session:scratch-new", "document_id": None, "name": "Scratch",
            "complete": True, "open_count": 3, "rows": post_rows}
    scratch_cleanup = {"handle": "session:other-new", "document_id": None, "name": "Other",
                       "complete": True, "open_count": 2,
                       "rows": [dict(post_rows[0]), dict(post_rows[1], is_active=True)]}
    return {"before_attestation": att, "after_attestation": after,
            "before_tool_census": list(census), "after_tool_census": list(census),
            "checks": {key: True for key in keys}, "after_health": {},
            "after_build_observation": {"fusion_version": "Fusion-1"},
            "after_fusion_version": "Fusion-1", "before_mcp_session": "mcp-old",
            "after_mcp_session": "mcp-new",
            "fresh_transport_document_handle": "session:scratch-new",
            "pre_reload_census": home, "post_reload_census": post, "cleanup_census": post,
            "scratch_cleanup_census": scratch_cleanup, "restored_census": copy.deepcopy(home),
            "scratch_handle_before_reload": "session:scratch-old",
            "nonce_name": "ReloadNonce1", "nonce_value_mm": 17}


@pytest.fixture(autouse=True)
def retained_results(tmp_path, monkeypatch):
    monkeypatch.setattr(receipts, "_evidence_directory", lambda directory:
                        Path(directory) if directory is not None else tmp_path / "results")
    real_write = receipts.write_aggregate
    def with_lifecycle(path, stamps, closures, census, run_id, **kwargs):
        if kwargs.get("lifecycle") is None:
            kwargs["lifecycle"] = receipts.make_lifecycle(
                _lifecycle_observations(census), run_id, "a" * 64, "Fusion-1")
        return real_write(path, stamps, closures, census, run_id, **kwargs)
    monkeypatch.setattr(receipts, "write_aggregate", with_lifecycle)


@pytest.fixture
def candidate(tmp_path):
    files = {
        "Fusion-Essentials.py": "from .lib import loaded_attestation\n",
        "lib/loaded_attestation.py": "IDENTITY = 1\n",
        "commands/mcpServer/entry.py": "from .server import core\n",
        "commands/mcpServer/server/core.py": "from ..mcp_primitives import registry\n",
        "commands/mcpServer/mcp_primitives/registry.py": "REGISTRY = 1\n",
        "commands/mcpServer/guidance/parametric_cad_design.json": "{}\n",
        "commands/mcpServer/tools/alpha_tool.py": "from . import _shared\n",
        "commands/mcpServer/tools/beta_tool.py": "from . import _shared\n",
        "commands/mcpServer/tools/producer_tool.py": "from . import _producer\n",
        "commands/mcpServer/tools/unrelated_tool.py": "VALUE = 1\n",
        "commands/mcpServer/tools/_shared.py": "VALUE = 1\n",
        "commands/mcpServer/tools/_producer.py": "VALUE = 1\n",
        "tests/live/tool_verify.py": "FACADE = 1\n",
        "tests/live/verify_runner.py": "RUNNER = 1\n",
        "tests/live/verify_families.py": "PRODUCERS = 1\n",
        "tests/live/verify_predicate.py": "def predicate(p):\n    return p['value'] == 1\n",
    }
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body.encode())
    namespace = {}
    path = tmp_path / "tests/live/verify_predicate.py"
    exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    acts = [("alpha act", None, [("alpha_tool", {}, namespace["predicate"], None)], []),
            ("beta act", None, [("beta_tool", {}, "ok", None)], [])]
    owners = {"alpha act": "alpha", "beta act": "beta"}
    fixtures = lambda family, **kw: [("producer_tool", {}, "ok", None)] if family == "alpha" else []
    return tmp_path, acts, owners, fixtures


def closures(candidate):
    return receipts.family_closures(*candidate)


def change(root, path):
    file = root / path
    file.write_bytes(file.read_bytes() + b"CHANGED = 1\n")


@pytest.mark.parametrize("path, affected", [
    ("commands/mcpServer/tools/alpha_tool.py", {"alpha"}),
    ("commands/mcpServer/tools/unrelated_tool.py", set()),
    ("commands/mcpServer/tools/_shared.py", {"alpha", "beta"}),
    ("commands/mcpServer/tools/_producer.py", {"alpha"}),
    ("tests/live/verify_predicate.py", {"alpha", "beta"}),
    ("tests/live/verify_families.py", {"alpha", "beta"}),
    ("commands/mcpServer/server/core.py", {"alpha", "beta"}),
    ("lib/loaded_attestation.py", {"alpha", "beta"}),
    ("commands/mcpServer/guidance/parametric_cad_design.json", {"alpha", "beta"}),
])
def test_source_attribution_invalidates_only_actual_consumers(candidate, path, affected):
    before = closures(candidate)
    change(candidate[0], path)
    after = closures(candidate)
    assert {name for name in before if before[name]["hash"] != after[name]["hash"]} == affected


def test_new_registration_requires_all_families_to_bootstrap(candidate):
    before = closures(candidate)
    (candidate[0] / "commands/mcpServer/tools/new_tool.py").write_bytes(b"VALUE = 1\n")
    after = closures(candidate)
    assert all(before[name]["hash"] != after[name]["hash"] for name in before)


def test_function_imports_and_unresolved_dynamic_imports_are_closed(candidate):
    root = candidate[0]
    path = root / "commands/mcpServer/tools/alpha_tool.py"
    path.write_bytes(b"def read():\n    from . import _producer\n    return _producer.VALUE\n")
    assert "commands/mcpServer/tools/_producer.py" in receipts.import_closure(
        root, ["commands/mcpServer/tools/alpha_tool.py"])
    path.write_bytes(b"import importlib\ndef read(name):\n    return importlib.import_module(name)\n")
    with pytest.raises(ValueError, match="unbounded dynamic import"):
        receipts.import_closure(root, ["commands/mcpServer/tools/alpha_tool.py"])
    path.write_bytes(b"from .missing import VALUE\n")
    with pytest.raises(ValueError, match="unresolved relative import"):
        receipts.import_closure(root, ["commands/mcpServer/tools/alpha_tool.py"])
    path.write_bytes(b"from commands.mcpServer.missing import VALUE\n")
    with pytest.raises(ValueError, match="unresolved local import"):
        receipts.import_closure(root, ["commands/mcpServer/tools/alpha_tool.py"])


def test_end_rehash_reads_actual_bytes_without_rediscovering_imports(candidate, monkeypatch):
    before = closures(candidate)
    monkeypatch.setattr(receipts, "import_closure", lambda *args: pytest.fail("rediscovery"))
    assert receipts.rehash_closures(candidate[0], before) == before
    change(candidate[0], "commands/mcpServer/tools/_producer.py")
    after = receipts.rehash_closures(candidate[0], before)
    assert {name for name in before if before[name] != after[name]} == {"alpha"}


def test_module_qualified_callback_binds_helper_side_tool(candidate, monkeypatch):
    root, acts, owners, fixtures = candidate
    helper_path = root / "tests/live/receipt_side_helper.py"
    helper_path.write_bytes(b"def call(tool, args):\n    return args\n"
                            b"def read(p):\n    call('beta_tool', {})\n    return p['value'] == 1\n")
    helper = types.ModuleType("receipt_side_helper")
    helper.__file__ = str(helper_path)
    exec(compile(helper_path.read_bytes(), str(helper_path), "exec"), helper.__dict__)
    monkeypatch.setitem(sys.modules, helper.__name__, helper)
    path = root / "tests/live/receipt_callback.py"
    path.write_bytes(b"import receipt_side_helper\ndef predicate(p):\n"
                     b"    return receipt_side_helper.read(p)\n")
    namespace = {}
    exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    acts[0][2][0] = ("alpha_tool", {}, namespace["predicate"], None)
    before = closures(candidate)
    assert "beta_tool" in before["alpha"]["tools"]
    assert "tests/live/receipt_side_helper.py" in before["alpha"]["files"]
    change(root, "commands/mcpServer/tools/beta_tool.py")
    assert before["alpha"]["hash"] != closures(candidate)["alpha"]["hash"]


def test_unbounded_callback_dispatch_refuses_a_stamp(candidate):
    root = candidate[0]
    path = root / "tests/live/receipt_callback.py"
    path.write_bytes(b"def call(tool, args):\n    return args\n"
                     b"def predicate(p):\n    return call(p['tool'], {})\n")
    namespace = {}
    exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    with pytest.raises(ValueError, match="unbounded callback tool dispatch"):
        receipts.callable_sources(namespace["predicate"], root, set(receipts.tool_census(root)))


@pytest.fixture
def execution():
    census = {"complete": True, "open_count": 1, "active": "session:home",
              "documents": [{"document_handle": "session:home", "open_index": 0,
                             "is_active": True}]}
    return {
        "run_id": "native-run", "family_run_id": "family-run", "whole_family": True,
        "cleanup": True, "source_unchanged": True, "stopped": False, "acts": ["act"],
        "start_health": {"version": "add-in-1", "fusion_version": "Fusion-1", "session_id": "session-id",
                         "attestation": {"complete": True, "loaded_matches_source": True,
                                         "implementation_fingerprint": "a" * 64,
                                         "schema_fingerprint": "b" * 64, "load_id": "load-1",
                                         "session_id": "session-id"}},
        "start_census": census, "end_census": copy.deepcopy(census),
        "rows": [["write_tool", "pass", "changed"], ["read_tool", "pass", "value held"]],
        "producers": [], "self_reported": ["write_tool", "read_tool"],
        "independent": ["write_tool"], "witnesses": [{"row_index": 1,
            "targets": ["write_tool"], "tool": "read_tool", "witness": "tool:read_tool",
            "reader_is_read": True}], "act_modes": [["act", "narrative"]],
    }


@pytest.fixture
def closure():
    return {"hash": "c" * 64, "files": {"tool.py": "d" * 64},
            "tools": ["write_tool", "read_tool"], "acts": ["act"]}


@pytest.mark.parametrize("field, value", [("cleanup", False), ("source_unchanged", False),
    ("whole_family", False), ("stopped", True), ("acts", []), ("run_id", "")])
def test_failed_or_partial_execution_cannot_stamp(execution, closure, field, value):
    execution[field] = value
    with pytest.raises(ValueError, match="incomplete|source changed"):
        receipts.make_stamp("family", closure, execution, closure)


def test_source_change_at_mint_boundary_refuses_even_with_old_run_flag(execution, closure):
    changed = dict(closure, hash="f" * 64)
    with pytest.raises(ValueError, match="source changed"):
        receipts.make_stamp("family", closure, execution, changed)


@pytest.mark.parametrize("failure", ["attestation", "census", "duplicate", "active", "step", "cleanup"])
def test_incomplete_start_and_failed_steps_refuse(execution, closure, failure):
    if failure == "attestation":
        execution["start_health"]["attestation"]["loaded_matches_source"] = False
    elif failure == "census":
        execution["start_census"]["open_count"] = 2
    elif failure == "duplicate":
        execution["start_census"]["documents"] *= 2
        execution["start_census"]["open_count"] = 2
    elif failure == "active":
        execution["start_census"]["active"] = "session:missing"
    elif failure == "cleanup":
        execution.pop("end_census")
    else:
        execution["rows"].append(["write_tool", "FAIL", "no effect"])
    with pytest.raises(ValueError):
        receipts.make_stamp("family", closure, execution, closure)


def test_local_producer_evidence_requires_executed_rows_on_same_family_build(execution, closure):
    producer = {"run_id": "executed-producer", "family_run_id": execution["family_run_id"],
                "phase": "setup", "fusion_version": "Fusion-1", "closure_hash": closure["hash"],
                "rows": [["producer_tool", "pass", "produced"]], "success": True}
    execution["producers"] = [producer]
    execution["rows"].insert(0, list(producer["rows"][0]))
    execution["witnesses"][0]["row_index"] += 1
    stamp = receipts.make_stamp("family", closure, execution, closure)
    assert stamp["producer_run_ids"] == ["executed-producer"]
    producer["rows"] = []
    with pytest.raises(ValueError, match="producer execution"):
        receipts.make_stamp("family", closure, execution, closure)


def test_independent_counts_are_separate_and_require_matching_read_witness(execution, closure):
    stamp = receipts.make_stamp("family", closure, execution, closure)
    assert stamp["evidence"]["counts"] == {"covered": 1, "self-reported": 1,
                                           "called": 0, "refusals-only": 0}
    witness = verify_core.Independent(lambda p: p["measured"], ["write_tool"], "tool:read_tool")
    assert verify_core.independent_targets(witness, "read_tool", {"write_tool"}, True) == {"write_tool"}
    assert not verify_core.independent_targets(witness, "other_tool", {"write_tool"}, True)
    assert not verify_core.independent_targets(witness, "read_tool", {"write_tool"}, False)
    assert not verify_core.independent_targets(witness, "read_tool", set(), True)
    assert not verify_core.independent_targets(lambda p: p["verified"], "read_tool", {"write_tool"}, True)
    execution["witnesses"][0]["reader_is_read"] = False
    with pytest.raises(ValueError, match="witness provenance"):
        receipts.make_stamp("family", closure, execution, closure)


def test_current_source_and_mixed_builds_refuse_aggregate(execution, closure, tmp_path):
    closures = {"alpha": closure, "beta": closure}
    stamps = {name: receipts.make_stamp(name, closure, copy.deepcopy(execution), closure)
              for name in closures}
    path = tmp_path / "families.json"
    receipt = receipts.write_aggregate(path, stamps, closures, ["write_tool", "read_tool"],
                                      "native-run", full=True)
    stale = copy.deepcopy(closures)
    stale["alpha"]["hash"] = "e" * 64
    with pytest.raises(ValueError, match="source changed"):
        receipts.validate_aggregate(receipt, stale, receipt["tool_census"])
    changed = copy.deepcopy(execution)
    changed["run_id"] = "new-run"
    changed["family_run_id"] = "new-family-run"
    changed["start_health"]["fusion_version"] = "Fusion-2"
    updated = {"alpha": receipts.make_stamp("alpha", closure, changed, closure)}
    mixed = receipts.write_aggregate(path, updated, closures, receipt["tool_census"], "new-run")
    with pytest.raises(ValueError, match="mixes Fusion builds"):
        receipts.validate_aggregate(mixed, closures, receipt["tool_census"])
    assert json.loads(path.read_text())["families"]["alpha"] == updated["alpha"]


def test_new_load_can_refresh_one_current_family_without_global_identity_invalidation(execution, closure, tmp_path):
    closures = {"alpha": closure, "beta": closure}
    stamps = {name: receipts.make_stamp(name, closure, copy.deepcopy(execution), closure)
              for name in closures}
    path = tmp_path / "families.json"
    receipts.write_aggregate(path, stamps, closures, [], "native-run", full=True)
    execution["run_id"] = "refresh-run"
    execution["family_run_id"] = "refresh-family"
    execution["start_health"]["attestation"]["implementation_fingerprint"] = "e" * 64
    execution["start_health"]["attestation"]["load_id"] = "load-2"
    updated = receipts.make_stamp("alpha", closure, execution, closure)
    result = receipts.write_aggregate(path, {"alpha": updated}, closures, [], "refresh-run")
    assert result["families"]["beta"]["run_id"] == "native-run"
    assert result["families"]["alpha"]["run_id"] == "refresh-run"
    assert result["lifecycle_history"][0]["run_id"] == "native-run"
    assert result["lifecycle"]["run_id"] == "refresh-run"


def test_old_aggregate_tables_and_incomplete_family_selection_cannot_bootstrap(execution, closure, tmp_path):
    stamp = receipts.make_stamp("alpha", closure, execution, closure)
    with pytest.raises(ValueError, match="complete fresh native run"):
        receipts.write_aggregate(tmp_path / "receipt.json", {"alpha": stamp},
                                 {"alpha": closure, "beta": closure}, [], "native-run", full=True)
    with pytest.raises(ValueError, match="bootstrap"):
        receipts.validate_aggregate({"format": 1, "families": {"alpha": stamp}}, {"alpha": closure}, [])


def test_check_never_falls_back_to_green_legacy_table(monkeypatch, tmp_path):
    monkeypatch.setattr(tool_verify, "FAMILY_RECEIPTS", True)
    monkeypatch.setattr(verify_runner, "FAMILY_RECEIPT", str(tmp_path / "missing.json"))
    monkeypatch.setattr(tool_verify, "source_hash", lambda *a: pytest.fail("legacy fallback"))
    assert tool_verify.check() == 1


def test_local_cloud_config_distinguishes_absent_opt_out_from_present_invalid_request(
        monkeypatch, tmp_path):
    config = tmp_path / "cloud_config.local.json"
    monkeypatch.setattr(receipts.cloud_config, "CONFIG_PATH", str(config))
    absent = receipts.declared_scope()
    assert absent["cloud_tier"] == "off"
    assert absent["cloud_config_hash"] is None
    config.write_bytes(b"not json\n")
    requested = receipts.declared_scope()
    assert requested == {"cloud_tier": "requested",
                         "cloud_config_hash": hashlib.sha256(config.read_bytes()).hexdigest(),
                         "quarantined": [verify_core.CLOUD_LINK_CRASH_REVIEW]}
    assert receipts.scope_disposition(verify_core.CLOUD_TIER, requested)[0] == "held"


def test_whole_family_held_at_zero_rows_keeps_other_bootstrap_stamp(execution, closure, tmp_path):
    scopes = {"cloud_tier": "requested", "cloud_config_hash": "a" * 64,
              "quarantined": [verify_core.CLOUD_LINK_CRASH_REVIEW]}
    held = copy.deepcopy(execution)
    held.update(rows=[], producers=[], self_reported=[], independent=[], witnesses=[],
                scope=scopes, omitted=[{"act": "act", "kind": "act",
                    "capability": verify_core.CLOUD_TIER, "reason": "active hub did not match",
                    "tools": ["read_tool", "write_tool"], "state": "held"}])
    closures = {"cloud": dict(closure, tools=["read_tool", "write_tool"]),
                "model": dict(closure, tools=["read_tool", "write_tool"])}
    stamps = {"cloud": receipts.make_stamp("cloud", closures["cloud"], held, closures["cloud"])}
    active = copy.deepcopy(execution)
    active.update(rows=[["write_tool", "pass", "changed"]], self_reported=["write_tool"],
                  independent=[], witnesses=[], scope=scopes, omitted=[])
    stamps["model"] = receipts.make_stamp("model", closures["model"], active, closures["model"])
    census = ["read_tool", "write_tool"]
    receipt = receipts.write_aggregate(tmp_path / "families.json", stamps, closures, census,
                                       "native-run", full=True)
    assert receipt["families"]["cloud"]["state"] == "held"
    assert receipt["families"]["cloud"]["row_count"] == 0
    assert receipt["families"]["model"]["run_id"] == "native-run"
    assert receipts.validate_aggregate(receipt, closures, census, require_exercised=False,
                                       evidence_dir=tmp_path / "clone-results")
    with pytest.raises(ValueError, match="aggregate incomplete; family held"):
        receipts.validate_aggregate(receipt, closures, census,
                                    evidence_dir=tmp_path / "clone-results")
    assert receipts.aggregate_ledger(receipt, closures, census)[0][1].startswith("skipped: held")


def test_unless_entitled_control_is_conditional_scope_without_evidence(execution, closure, tmp_path):
    capability = verify_runner.MACHINING_EXTENSION
    run = copy.deepcopy(execution)
    run.update(scope={"cloud_tier": "requested", "cloud_config_hash": "a" * 64,
                      "quarantined": [verify_core.CLOUD_LINK_CRASH_REVIEW]},
               omitted=[{"act": "act", "kind": "step", "capability": capability,
                         "reason": "extension is entitled; control runs only when absent",
                         "tools": ["conditional_tool"], "state": "not-applicable",
                         "polarity": "unless", "observed_verdict": True}])
    stamp = receipts.make_stamp("family", closure, run, closure)
    census = ["conditional_tool", "read_tool", "write_tool"]
    receipt = receipts.write_aggregate(tmp_path / "families.json", {"family": stamp},
                                       {"family": closure}, census, "native-run", full=True)
    assert receipts.validate_aggregate(receipt, {"family": closure}, census, full_scope=True)
    buckets = stamp["evidence"]["buckets"]
    assert all("conditional_tool" not in tools for tools in buckets.values())
    assert "not applicable (conditional): " + capability in receipts.scope_description(
        {"family": stamp})


@pytest.mark.parametrize("verdict", [None, False])
def test_unless_not_applicable_requires_positive_entitlement(execution, closure, verdict):
    capability = verify_runner.MACHINING_EXTENSION
    run = copy.deepcopy(execution)
    run.update(scope={"cloud_tier": "requested", "cloud_config_hash": "a" * 64,
                      "quarantined": [verify_core.CLOUD_LINK_CRASH_REVIEW]},
               omitted=[{"act": "act", "kind": "step", "capability": capability,
                         "reason": "invalid conditional skip", "tools": ["write_tool"],
                         "state": "not-applicable", "polarity": "unless",
                         "observed_verdict": verdict}])
    with pytest.raises(ValueError, match="conditional omission"):
        receipts.make_stamp("family", closure, run, closure)


def test_requested_needs_omission_with_entitlement_is_invalid(execution, closure):
    run = copy.deepcopy(execution)
    run.update(scope={"cloud_tier": "requested", "cloud_config_hash": "a" * 64,
                      "quarantined": [verify_core.CLOUD_LINK_CRASH_REVIEW]},
               omitted=[{"act": "act", "kind": "step", "capability": verify_runner.MACHINING_EXTENSION,
                         "reason": "invalid Needs omission", "tools": ["write_tool"],
                         "state": "held", "polarity": "needs", "observed_verdict": True}])
    with pytest.raises(ValueError, match="conditional omission"):
        receipts.make_stamp("family", closure, run, closure)


def test_not_in_scope_is_omission_only_and_clone_check_uses_recorded_scope(
        execution, closure, tmp_path, monkeypatch):
    scope = {"cloud_tier": "off", "cloud_config_hash": None,
             "quarantined": [verify_core.CLOUD_LINK_CRASH_REVIEW]}
    out = copy.deepcopy(execution)
    out.update(rows=[], producers=[], self_reported=[], independent=[], witnesses=[], scope=scope,
               omitted=[{"act": "act", "kind": "act", "capability": verify_core.CLOUD_TIER,
                         "reason": "cloud tier is opt-in; local config is absent",
                         "tools": ["read_tool", "write_tool"], "state": "not-in-scope"}])
    closures = {"cloud": dict(closure, tools=["read_tool", "write_tool"]),
                "model": dict(closure, tools=["read_tool", "write_tool"])}
    out["act_modes"] = [["act", "skipped(cloud tier is opt-in; local config is absent)"]]
    omitted = receipts.make_stamp("cloud", closures["cloud"], out, closures["cloud"])
    assert omitted == {"family": "cloud", "state": "not-in-scope", "scope": scope,
                       "acts": ["act"], "act_modes": [["act", "skipped(cloud tier is opt-in; local config is absent)"]],
                       "omitted": out["omitted"]}
    active = copy.deepcopy(execution)
    active.update(scope=scope)
    stamps = {"cloud": omitted, "model": receipts.make_stamp(
        "model", closures["model"], active, closures["model"])}
    census = ["read_tool", "write_tool"]
    path = tmp_path / "families.json"
    receipt = receipts.write_aggregate(path, stamps, closures, census, "native-run", full=True)
    assert "cloud" not in receipt["families"]
    assert receipt["not_in_scope"]["cloud"] == omitted
    assert "cloud" not in receipts._retained(
        receipt["bootstrap"]["raw"], tmp_path / "results")["stamps"]
    assert receipt["bootstrap"]["executed_families"] == ["model"]
    assert receipts.aggregate_modes(receipt, closures) == [
        ("act", "skipped(cloud tier is opt-in; local config is absent)"), ("act", "narrative")]
    monkeypatch.setattr(receipts.cloud_config, "CONFIG_PATH", str(tmp_path / "missing-clone-config.json"))
    monkeypatch.setattr(verify_runner, "FAMILY_RECEIPT", str(path))
    monkeypatch.setattr(verify_runner, "receipt_closures", lambda: closures)
    monkeypatch.setattr(receipts, "tool_census", lambda _root: census)
    original_facade = verify_runner.facade
    monkeypatch.setattr(verify_runner, "facade", lambda name: (lambda *args: "a" * 64)
                        if name == "source_hash" else original_facade(name))
    assert verify_runner.check() == 0
    closures["cloud"]["acts"] = ["act", "new ungated act"]
    assert verify_runner.check() == 1
    closures["cloud"]["acts"] = ["act"]
    assert verify_runner.check(full_scope=True) == 1
    with pytest.raises(ValueError, match="not full admitted scope"):
        receipts.validate_aggregate(receipt, closures, census, full_scope=True,
                                    evidence_dir=tmp_path / "empty-clone-results")
    admitted = copy.deepcopy(execution)
    admitted.update(run_id="refresh-run", family_run_id="cloud-execution", scope={
        "cloud_tier": "requested", "cloud_config_hash": "b" * 64,
        "quarantined": [verify_core.CLOUD_LINK_CRASH_REVIEW]}, omitted=[])
    refreshed = receipts.make_stamp("cloud", closures["cloud"], admitted, closures["cloud"])
    aggregate = receipts.write_aggregate(path, {"cloud": refreshed}, closures, census,
                                         "refresh-run", evidence_dir=tmp_path / "refresh-results")
    assert "cloud" not in aggregate["not_in_scope"]
    assert aggregate["families"]["cloud"]["run_id"] == "refresh-run"
    assert receipts.validate_aggregate(aggregate, closures, census, full_scope=True,
                                       evidence_dir=tmp_path / "refresh-results")


def test_value_evidence_is_family_local_when_the_same_tool_has_a_bare_call(execution, closure):
    value_run = copy.deepcopy(execution)
    value_run.update(rows=[["write_tool", "pass", "changed"]], self_reported=["write_tool"],
                     independent=[], witnesses=[])
    call_run = copy.deepcopy(execution)
    call_run.update(rows=[["write_tool", "pass", "ok"]], self_reported=[],
                    independent=[], witnesses=[])
    value_stamp = receipts.make_stamp("value_family", closure, value_run, closure)
    call_stamp = receipts.make_stamp("call_family", closure, call_run, closure)
    assert value_stamp["evidence"]["buckets"]["self-reported"] == ["write_tool"]
    assert call_stamp["evidence"]["buckets"]["self-reported"] == []
    assert call_stamp["evidence"]["buckets"]["called"] == ["write_tool"]


@pytest.mark.parametrize("state", ["closed", "modified", "active", "leaked-scratch"])
def test_complete_end_census_does_not_hide_owner_document_changes(execution, closure, state):
    if state == "closed":
        execution["end_census"] = {"complete": True, "open_count": 1, "active": "session:replacement",
                                   "documents": [{"document_handle": "session:replacement"}]}
    elif state == "modified":
        execution["end_census"]["documents"][0]["is_modified"] = True
    else:
        execution["end_census"]["documents"].append({"document_handle": "session:other"})
        execution["end_census"]["open_count"] = 2
        if state != "leaked-scratch":
            execution["end_census"]["active"] = "session:other"
    with pytest.raises(ValueError, match="owner"):
        receipts.make_stamp("family", closure, execution, closure)


def test_actual_wire_health_normalizes_session_and_keeps_addin_version_separate(execution):
    wire = copy.deepcopy(execution["start_health"])
    wire.pop("fusion_version")
    wire["attestation"].pop("session_id")
    normalized = receipts.normalized_health(wire, "Fusion-1")
    assert normalized["attestation"]["session_id"] == wire["session_id"]
    assert normalized["version"] == "add-in-1"
    assert normalized["fusion_version"] == "Fusion-1"
    assert "session_id" not in wire["attestation"]
    missing = copy.deepcopy(execution)
    missing["start_health"]["attestation"].pop("session_id")
    with pytest.raises(ValueError, match="session_id"):
        receipts.exact_start(missing["start_health"], missing["start_census"])
    normalized["attestation"]["session_id"] = "other-session"
    with pytest.raises(ValueError, match="sessions disagree"):
        receipts.exact_start(normalized, execution["start_census"])


def test_current_attestation_flags_without_identity_do_not_validate_aggregate(execution, closure, tmp_path):
    stamp = receipts.make_stamp("alpha", closure, execution, closure)
    receipt = receipts.write_aggregate(tmp_path / "receipt.json", {"alpha": stamp},
                                       {"alpha": closure}, [], "native-run", full=True)
    with pytest.raises(ValueError, match="attestation missing"):
        receipts.validate_aggregate(receipt, {"alpha": closure}, [],
                                    {"complete": True, "loaded_matches_source": True})


def test_compact_stamps_validate_on_a_clone_without_ignored_results(execution, closure, tmp_path):
    stamp = receipts.make_stamp("alpha", closure, execution, closure)
    receipt = receipts.write_aggregate(tmp_path / "receipt.json", {"alpha": stamp},
                                       {"alpha": closure}, [], "native-run", full=True)
    assert "rows" not in stamp and "closure" not in stamp and "stamps" not in receipt["bootstrap"]
    assert receipts.validate_aggregate(receipt, {"alpha": closure}, [],
                                      evidence_dir=tmp_path / "empty-clone-results")
    raw = receipts._evidence_directory(None) / stamp["raw"]["file"]
    raw.write_bytes(raw.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum differs"):
        receipts.validate_aggregate(receipt, {"alpha": closure}, [])


@pytest.mark.parametrize("field", ["counts", "producer", "identity", "witness"])
def test_compact_provenance_tampering_refuses_without_raw(execution, closure, tmp_path, field):
    execution["producers"] = [{"run_id": "producer", "family_run_id": "family-run",
                               "phase": "setup", "fusion_version": "Fusion-1",
                               "closure_hash": closure["hash"], "success": True,
                               "rows": [["write_tool", "pass", "changed"]]}]
    stamp = receipts.make_stamp("alpha", closure, execution, closure)
    receipt = receipts.write_aggregate(tmp_path / "receipt.json", {"alpha": stamp},
                                       {"alpha": closure}, [], "native-run", full=True)
    if field == "counts":
        stamp["evidence"]["counts"]["covered"] = 2
    elif field == "producer":
        stamp["producers"][0]["family_run_id"] = "different-family"
    elif field == "identity":
        stamp["identity"]["complete"] = False
    else:
        stamp["witnesses"][0]["targets"] = ["read_tool"]
    with pytest.raises(ValueError):
        receipts.validate_aggregate(receipt, {"alpha": closure}, [],
                                    evidence_dir=tmp_path / "empty-clone-results")


def test_two_family_refresh_composes_old_and_new_evidence_and_leaves_stale_pending(execution, closure, tmp_path):
    family_closures, stamps = {}, {}
    for name in ("alpha", "beta"):
        family_closures[name] = dict(closure, tools=[name + "_tool"])
        run = copy.deepcopy(execution)
        run.update(rows=[[name + "_tool", "pass", "value held"]],
                   self_reported=[name + "_tool"], independent=[], witnesses=[])
        stamps[name] = receipts.make_stamp(name, family_closures[name], run, family_closures[name])
    path, census = tmp_path / "receipt.json", ["alpha_tool", "beta_tool"]
    receipts.write_aggregate(path, stamps, family_closures, census, "native-run", full=True)
    refreshed = copy.deepcopy(stamps["alpha"])
    run["run_id"], run["family_run_id"] = "refresh-run", "refresh-family"
    run.update(rows=[["alpha_tool", "pass", "value held"]], self_reported=["alpha_tool"])
    refreshed = receipts.make_stamp("alpha", family_closures["alpha"], run, family_closures["alpha"])
    aggregate = receipts.write_aggregate(path, {"alpha": refreshed}, family_closures, census, "refresh-run")
    assert aggregate["families"]["beta"] == stamps["beta"]
    assert receipts.aggregate_ledger(aggregate, family_closures, census) == [
        ("alpha_tool", "self-reported"), ("beta_tool", "self-reported")]
    assert receipts.aggregate_modes(aggregate, family_closures) == [("act", "narrative"),
                                                                    ("act", "narrative")]
    table = tmp_path / "verified.md"
    verify_runner.write_verified(receipts.aggregate_ledger(aggregate, family_closures, census),
        "Fusion-1", "today", "a" * 64, path=table,
        attestation=execution["start_health"]["attestation"],
        family_runs=aggregate["families"], aggregate_current=True)
    rendered = table.read_text()
    assert "refresh-run" in rendered and "native-run" in rendered and "Aggregate: current" in rendered
    assert "does not claim" in rendered and "2 self-reported" in rendered
    stale = copy.deepcopy(family_closures)
    stale["beta"]["hash"] = "e" * 64
    assert receipts.aggregate_ledger(aggregate, stale, census)[1] == (
        "beta_tool", "PENDING (no current family evidence)")
    with pytest.raises(ValueError, match="source changed"):
        receipts.validate_aggregate(aggregate, stale, census)
    assert receipts.aggregate_ledger({"families": {"alpha": refreshed}}, family_closures, census)[1][1].startswith("PENDING")


def test_reload_coverage_requires_current_lifecycle_and_failed_replacement_keeps_old_record(
        execution, closure, tmp_path):
    closures = {"alpha": dict(closure, tools=["sys_reload_addin"])}
    stamp = receipts.make_stamp("alpha", closures["alpha"], execution, closures["alpha"])
    path = tmp_path / "families.json"
    receipt = receipts.write_aggregate(path, {"alpha": stamp}, closures,
                                       ["sys_reload_addin"], "native-run", full=True)
    inactive = receipt["lifecycle"]["pre_reload_census"]["rows"][1]
    assert "is_active" not in inactive and "is_saved" not in inactive
    unreadable = copy.deepcopy(receipt)
    unreadable["lifecycle"]["pre_reload_census"]["rows"][1]["is_visible"] = None
    with pytest.raises(ValueError, match="document state is unreadable"):
        receipts.validate_aggregate(unreadable, closures, ["sys_reload_addin"])
    assert receipts.aggregate_ledger(receipt, closures, ["sys_reload_addin"])[0][1] == "self-reported"
    missing = dict(receipt, lifecycle=None)
    assert receipts.aggregate_ledger(missing, closures, ["sys_reload_addin"])[0][1].startswith("PENDING")
    assert verify_runner.receipt_notes(
        [("sys_reload_addin", "self-reported"), ("stale_tool", "PENDING (stale)")],
        {"sys_reload_addin": "current reload story", "stale_tool": "old story"}) == {
            "sys_reload_addin": "current reload story"}
    stale = copy.deepcopy(receipt)
    stale["lifecycle"]["source_hash"] = "f" * 64
    assert receipts.aggregate_ledger(stale, closures, ["sys_reload_addin"],
                                     source_hash="a" * 64)[0][1].startswith("PENDING")
    for key, value in (("run_id", "relabelled-run"), ("source_hash", "f" * 64)):
        relabelled = copy.deepcopy(receipt)
        relabelled["lifecycle"][key] = value
        with pytest.raises(ValueError, match="retained lifecycle"):
            receipts.validate_aggregate(relabelled, closures, ["sys_reload_addin"])
    before = path.read_bytes()
    execution["run_id"], execution["family_run_id"] = "refresh-run", "refresh-family"
    refreshed = receipts.make_stamp("alpha", closures["alpha"], execution, closures["alpha"])
    with pytest.raises(ValueError, match="lifecycle"):
        receipts.write_aggregate(path, {"alpha": refreshed}, closures,
                                 ["sys_reload_addin"], "refresh-run",
                                 lifecycle={"run_id": "refresh-run"})
    assert path.read_bytes() == before


@pytest.mark.parametrize(("fault", "reason"), [
    ("identity", "attestation identity incomplete"),
    ("dropped-owner", "owner census did not restore"),
    ("changed-owner-state", "owner document state changed"),
])
def test_make_lifecycle_rejects_raw_identity_and_full_census_faults(tmp_path, fault, reason):
    evidence = _lifecycle_observations([])
    if fault == "identity":
        evidence["before_attestation"].pop("implementation_fingerprint")
    elif fault == "dropped-owner":
        evidence["pre_reload_census"]["rows"].pop()
        evidence["pre_reload_census"]["open_count"] = 1
    else:
        evidence["restored_census"]["rows"][1]["is_modified"] = True

    with pytest.raises(ValueError, match=reason):
        receipts.make_lifecycle(evidence, "native-run", "a" * 64, "Fusion-1",
                                evidence_dir=tmp_path / fault)


def test_two_stale_families_can_refresh_sequentially_without_replaying_each_other(execution, closure, tmp_path):
    old_closures = {name: copy.deepcopy(closure) for name in ("alpha", "beta")}
    stamps = {name: receipts.make_stamp(name, old_closures[name], copy.deepcopy(execution), old_closures[name])
              for name in old_closures}
    path = tmp_path / "receipt.json"
    receipts.write_aggregate(path, stamps, old_closures, [], "native-run", full=True)
    current = {name: dict(closure, hash=("e" if name == "alpha" else "f") * 64) for name in old_closures}
    for name in ("alpha", "beta"):
        run = copy.deepcopy(execution)
        run["run_id"], run["family_run_id"] = name + "-refresh", name + "-execution"
        fresh = receipts.make_stamp(name, current[name], run, current[name])
        aggregate = receipts.write_aggregate(path, {name: fresh}, current, [], run["run_id"])
        assert json.loads(path.read_text())["families"][name] == fresh
        if name == "alpha":
            assert aggregate["families"]["beta"] == stamps["beta"]
            with pytest.raises(ValueError, match="source changed"):
                receipts.validate_aggregate(aggregate, current, [])
        else:
            assert receipts.validate_aggregate(aggregate, current, [])


def test_act_list_change_refresh_keeps_other_historical_modes(execution, closure, tmp_path):
    closures = {name: copy.deepcopy(closure) for name in ("alpha", "beta")}
    stamps = {name: receipts.make_stamp(name, closures[name], copy.deepcopy(execution), closures[name])
              for name in closures}
    path = tmp_path / "receipt.json"
    receipts.write_aggregate(path, stamps, closures, [], "native-run", full=True)
    current = {name: dict(item, hash="e" * 64, acts=["act", "new act"])
               for name, item in closures.items()}
    run = copy.deepcopy(execution)
    run["run_id"], run["family_run_id"] = "refresh-run", "refresh-family"
    run["acts"] = ["act", "new act"]
    run["act_modes"] = [["act", "narrative"], ["new act", "fallback"]]
    fresh = receipts.make_stamp("alpha", current["alpha"], run, current["alpha"])
    aggregate = receipts.write_aggregate(path, {"alpha": fresh}, current, [], "refresh-run")
    assert aggregate["families"]["beta"] == stamps["beta"]
    assert receipts.aggregate_modes(aggregate, current) == [
        ("act", "narrative"), ("new act", "fallback")]
