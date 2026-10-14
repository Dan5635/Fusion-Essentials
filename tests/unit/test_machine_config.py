# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Explicit sweep configuration refuses unsafe or incomplete choices before transport."""

import copy
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def config_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "live"))
    return importlib.import_module("machine_config")


@pytest.fixture
def good(config_module):
    return json.loads(config_module.example_text())


def test_example_is_explicit_and_requests_no_tier_or_persistent_permission(config_module, good):
    assert config_module.problems(good) == []
    assert config_module.asked(good) == {name: False for name in config_module.SWITCHES}


@pytest.mark.parametrize("arguments", [["--config", "path with spaces.json"], ["--config=path with spaces.json"]])
def test_cli_configuration_beats_environment_before_scope_capture(config_module, good, arguments, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "path with spaces.json").write_text(json.dumps(good), encoding="utf-8")
    environ = {config_module.ENV: "stale.json"}
    selected = config_module.configure_cli(arguments + ["--trace"], environ)
    assert selected == str(tmp_path / "path with spaces.json")
    assert config_module.config_path(environ)[0] == selected
    before = dict(environ)
    assert config_module.configure_cli(["--check"], environ) is None and environ == before


@pytest.mark.parametrize("arguments", [["--config"], ["--config", ""], ["--config", "  "],
                                       ["--config", "one", "--config=two"]])
def test_invalid_or_duplicate_cli_configuration_changes_nothing(config_module, arguments):
    environ = {config_module.ENV: "retained.json"}
    with pytest.raises(SystemExit) as stopped:
        config_module.configure_cli(arguments, environ)
    assert stopped.value.code == 2 and environ == {config_module.ENV: "retained.json"}


@pytest.fixture
def cli_startup(tmp_path):
    def invoke(arguments, inherited):
        tests = Path(__file__).resolve().parents[1]
        driver = '''import json, os, runpy, sys
sys.path.insert(0, sys.argv[1])
import conftest
entry = sys.argv[1] + "/live/tool_verify.py"
sys.argv = [entry] + json.loads(sys.argv[2])
try:
    runpy.run_path(entry, run_name="__main__")
except SystemExit as stop:
    status = stop.code
core = sys.modules.get("verify_core")
cloud = sys.modules.get("cloud_config")
assert not conftest._unit_transport_violations(), "CLI proof attempted real transport"
print("STARTUP-RESULT=" + json.dumps({"status": status,
    "core_loaded": core is not None, "cloud_loaded": cloud is not None,
    "base": core.BASE if core else None, "cloud_path": cloud.CONFIG_PATH if cloud else None,
    "hub": cloud.HUB if cloud else None,
    "config_env": os.environ.get("FUSION_ESSENTIALS_SWEEP_CONFIG")}))
'''
        env = dict(os.environ, FUSION_ESSENTIALS_SWEEP_CONFIG=str(inherited))
        result = subprocess.run([sys.executable, "-c", driver, str(tests), json.dumps(arguments)],
                                env=env, cwd=tmp_path, capture_output=True, text=True,
                                encoding="utf-8", timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        line = next(line for line in result.stdout.splitlines() if line.startswith("STARTUP-RESULT="))
        return json.loads(line.partition("=")[2])
    return invoke


def test_actual_cli_selects_config_before_cloud_import_and_registers_the_flag(good, cli_startup, tmp_path):
    good["port"] = 40123
    good["tiers"]["cloud"] = True
    good["cloud"].update(hub="Injected Hub", project="Injected Project", folder="Injected Folder")
    selected = tmp_path / "chosen config.json"
    selected.write_text(json.dumps(good), encoding="utf-8")
    observed = cli_startup(["--config", str(selected), "--help"], tmp_path / "stale.json")
    assert observed == {"status": 0, "core_loaded": True, "cloud_loaded": True,
                        "base": "http://127.0.0.1:40123", "cloud_path": str(selected), "hub": "Injected Hub",
                        "config_env": str(selected)}


@pytest.mark.parametrize("failure", ["missing", "incomplete", "malformed"])
def test_actual_cli_missing_selected_file_stops_before_cloud_or_core_import(good, cli_startup, tmp_path, failure):
    inherited = tmp_path / "inherited.json"
    inherited.write_text(json.dumps(good), encoding="utf-8")
    missing = tmp_path / "missing.json"
    if failure == "incomplete":
        del good["allow"]["addin_reload"]
        missing.write_text(json.dumps(good), encoding="utf-8")
    elif failure == "malformed":
        missing.write_text("{broken", encoding="utf-8")
    observed = cli_startup(["--config", str(missing)], inherited)
    assert observed["core_loaded"] is False and observed["cloud_loaded"] is False
    assert observed["config_env"] == str(inherited)
    assert isinstance(observed["status"], str) and str(missing) in observed["status"]
    if failure == "incomplete":
        assert "missing: allow.addin_reload" in observed["status"]


def test_missing_and_unknown_keys_are_all_named_without_defaulting(config_module, good):
    good["allow"]["libary_writes"] = good["allow"].pop("library_writes")
    del good["port"], good["cloud"]
    assert config_module.problems(good) == ["missing: port", "missing: cloud",
                                           "unknown key: allow.libary_writes",
                                           "missing: allow.library_writes"]


@pytest.mark.parametrize("value", [0, 1, "true", "false", None])
def test_permission_values_are_actual_booleans(config_module, good, value):
    good["allow"]["preference_writes"] = value
    assert config_module.problems(good) == ["allow.preference_writes must be true or false"]


@pytest.mark.parametrize("port", [1023, 49152, "37182", 37182.0, True, None])
def test_ports_refuse_outside_boundaries_and_non_integer_values(config_module, good, port):
    good["port"] = port
    assert config_module.problems(good) == ["port must be a whole number from 1024 to 49151"]


@pytest.mark.parametrize("port", [1024, 49151])
def test_endpoint_boundaries_are_inclusive(config_module, good, port):
    good["port"] = port
    assert config_module.problems(good) == []


@pytest.mark.parametrize("label", ["", "../up", "x/y", "has space", ".hidden", "x" * 41,
                                    "end.", "CON", "nul.txt", "COM1.log", "Lpt9"])
def test_record_labels_cannot_escape_or_alias_platform_reserved_paths(config_module, good, label):
    good["machine"] = label
    problems = config_module.problems(good)
    assert len(problems) == 1 and repr(label) in problems[0]


def test_requested_cloud_needs_three_strings_but_off_cloud_still_requires_keys(config_module, good):
    good["tiers"]["cloud"] = True
    good["cloud"]["hub"] = "My hub"
    assert config_module.problems(good) == ["tiers.cloud is true but cloud.project is empty",
                                           "tiers.cloud is true but cloud.folder is empty"]
    good["tiers"]["cloud"] = False
    del good["cloud"]["folder"]
    assert config_module.problems(good) == ["missing: cloud.folder"]


def test_nonobject_sections_are_refusals_not_crashes(config_module, good):
    good["tiers"] = False
    assert config_module.problems(good) == ["tiers must be an object"]
    assert config_module.problems([good]) == ["the file holds a list, not an object"]


def test_duplicate_json_keys_cannot_overwrite_permission_choices(config_module, tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"allow":{"library_writes":false,"library_writes":true}}', encoding="utf-8")
    config, problems = config_module.load(path)
    assert config is None and len(problems) == 1
    assert "duplicate key: library_writes" in problems[0]


def test_override_precedence_is_explicit_then_environment_then_default(config_module, tmp_path):
    explicit, environment = tmp_path / "explicit.json", tmp_path / "environment.json"
    env = {config_module.ENV: str(environment)}
    assert config_module.config_path(env, explicit) == (str(explicit), "--config")
    assert config_module.config_path(env) == (str(environment), config_module.ENV)
    default, origin = config_module.config_path({})
    assert Path(default) == Path(config_module.__file__).parent / config_module.CONFIG_NAME
    assert origin == "the default place"


def test_missing_file_refusal_names_exact_path_and_prints_whole_example(config_module, tmp_path):
    path = tmp_path / "missing.json"
    with pytest.raises(SystemExit) as refused:
        config_module.require({}, path)
    expected = ("The sweep is not set up for this machine, so nothing was called.\n"
                f"It looked for: {path}  (not found; from --config)\n"
                "Copy tests/live/sweep_config.example.json to that name and fill it in. It holds:\n"
                + config_module.example_text() + "\n"
                'What each key means is in tests/README.md, "Running the sweep on your machine".')
    assert str(refused.value) == expected


def test_malformed_and_incomplete_files_refuse_then_valid_file_round_trips(config_module, good, tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    parsed, problems = config_module.load(path)
    assert parsed is None and "JSON" in problems[0]
    del good["allow"]["addin_reload"]
    path.write_text(json.dumps(good), encoding="utf-8")
    with pytest.raises(SystemExit, match="missing: allow.addin_reload"):
        config_module.require({}, path)
    good["allow"]["addin_reload"] = False
    path.write_text(json.dumps(good), encoding="utf-8")
    assert config_module.require({}, path) == good


def test_scope_identity_binds_endpoint_every_switch_and_cloud_destination(config_module, good):
    identity = config_module.fingerprint(good)
    for group, key in config_module.SWITCHES.values():
        changed = copy.deepcopy(good)
        changed[group][key] = True
        assert config_module.fingerprint(changed) != identity
    for group, key, value in ((None, "port", 40123), (None, "machine", "other-machine"),
                              ("cloud", "folder", "other-folder")):
        changed = copy.deepcopy(good)
        (changed if group is None else changed[group])[key] = value
        assert config_module.fingerprint(changed) != identity
    assert config_module.fingerprint(json.loads(json.dumps(good, sort_keys=True))) == identity


@pytest.fixture
def core_loader(config_module, monkeypatch, tmp_path):
    def load(config):
        path = tmp_path / "machine.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setenv(config_module.ENV, str(path))
        source = Path(__file__).resolve().parents[1] / "live" / "verify_core.py"
        spec = importlib.util.spec_from_file_location("verify_core_config_witness", source)
        core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core)
        return core, path
    return load


def test_each_live_entry_refuses_bad_config_before_any_dispatch(good, core_loader, monkeypatch):
    del good["allow"]["addin_reload"]
    core, path = core_loader(good)
    attempted = []
    monkeypatch.setattr(core, "_post", lambda *args, **kw: attempted.append("post"))
    monkeypatch.setattr(core, "_health_read", lambda: attempted.append("health"))
    for invoke in (core.health_gate, core.registered_tools, lambda: core.call("model_inspect", {})):
        with pytest.raises(SystemExit, match="missing: allow.addin_reload"):
            invoke()
    assert attempted == []


def test_configured_endpoint_is_used_and_mid_run_config_drift_stops(good, core_loader, monkeypatch):
    good["port"] = 40123
    core, path = core_loader(good)
    assert (core.PORT, core.BASE, core.MCP) == (40123, "http://127.0.0.1:40123",
                                               "http://127.0.0.1:40123/mcp")
    good["allow"]["addin_reload"] = True
    path.write_text(json.dumps(good), encoding="utf-8")
    monkeypatch.setattr(core, "_post", lambda *args, **kw: pytest.fail("post attempted after config drift"))
    with pytest.raises(SystemExit, match="configuration changed or became unreadable"):
        core.call("model_inspect", {})


def test_lowest_raw_transport_and_polling_calls_cannot_bypass_permission(good, core_loader, monkeypatch):
    core, _ = core_loader(good)
    monkeypatch.setattr(core.urllib.request, "urlopen", lambda *args, **kw: pytest.fail("network attempted"))
    payload = {"method": "tools/call", "params": {"name": "sys_set_preferences", "arguments": {}}}
    with pytest.raises(SystemExit, match="allow.preference_writes"):
        core._post(payload)
    with pytest.raises(SystemExit, match="tiers.native_script"):
        core.call("sys_execute_script", {"script": "def run(context): pass"})


@pytest.fixture
def check_all_module(config_module):
    source = Path(__file__).resolve().parents[1] / "check_all.py"
    spec = importlib.util.spec_from_file_location("check_all_band_b_witness", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("tool,arguments", [
    ("doc_save", {}), ("doc_save_as", {"project": "Injected Project", "folder": "Injected Folder"}),
    ("doc_save_milestone", {"milestone_name": "Injected Milestone"}),
    ("doc_copy", {}), ("doc_restore_version", {}), ("doc_open", {}),
    ("doc_insert_occurrence", {}), ("doc_insert_derive", {}),
    ("doc_update_xref", {}), ("doc_update_xref", {"action": "replace"}),
    ("doc_close", {"save_changes": True}), ("doc_close", {"save_changes": "false"})])
def test_cloud_document_routes_refuse_at_both_real_dispatch_guards(
        good, core_loader, monkeypatch, tool, arguments):
    core, _ = core_loader(good)
    attempted = []
    monkeypatch.setattr(core.urllib.request, "urlopen", lambda *args, **kw: attempted.append("wire"))
    for invoke in (lambda: core.call(tool, arguments),
                   lambda: core._post({"method": "tools/call", "params": {
                       "name": tool, "arguments": arguments}})):
        with pytest.raises(SystemExit, match="tiers.cloud"):
            invoke()
    assert attempted == []


def test_cloud_on_preserves_save_payload_and_cloud_off_keeps_discard_close(
        good, core_loader, monkeypatch):
    good["tiers"]["cloud"] = True
    good["cloud"].update(hub="Injected Hub", project="Injected Project", folder="Injected Folder")
    core, path = core_loader(good)
    captured = []
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"result":{"content":[{"type":"text","text":"{}"}]}}'
    def transport(request, **kwargs):
        captured.append(json.loads(request.data))
        return response
    monkeypatch.setattr(core.urllib.request, "urlopen", transport)
    args = {"name": "Injected Coupon", "project": "Injected Project", "folder": "Injected Folder"}
    assert core.call("doc_save_as", args) == (False, {})
    assert captured[-1]["params"] == {"name": "doc_save_as", "arguments": args}
    core.MACHINE["tiers"]["cloud"] = False
    path.write_text(json.dumps(core.MACHINE), encoding="utf-8")
    close_args = {"name": "session:injected-owned", "save_changes": False}
    assert core.call("doc_close", close_args) == (False, {})
    assert captured[-1]["params"] == {"name": "doc_close", "arguments": close_args}
    assert len(captured) == 2


def test_check_all_live_probe_refuses_missing_configuration_before_health(good, core_loader, check_all_module, monkeypatch):
    del good["allow"]["addin_reload"]
    core, _ = core_loader(good)
    monkeypatch.setattr(check_all_module, "require_machine", core.require_machine)
    monkeypatch.setattr(check_all_module, "health_gate", lambda: pytest.fail("health attempted without config"))
    with pytest.raises(SystemExit, match="missing: allow.addin_reload"):
        check_all_module._fusion_up()


def test_check_all_health_probe_requires_the_configured_port_not_any_server_text(good, core_loader, check_all_module, monkeypatch):
    good["port"] = 40123
    core, _ = core_loader(good)
    monkeypatch.setattr(check_all_module, "require_machine", core.require_machine)
    monkeypatch.setattr(check_all_module, "_bound_on_harness", core._bound_on_harness)
    health = {"bound": {"host": "127.0.0.1", "port": 40123, "mcp_url": "http://127.0.0.1:40123/mcp"}}
    monkeypatch.setattr(check_all_module, "health_gate", lambda: health)
    assert check_all_module._fusion_up() is True
    health["bound"]["port"] = 37182
    assert check_all_module._fusion_up() is False


def test_effect_declaration_reaches_both_actual_transport_guards_without_wire_fields(good, core_loader, config_module, monkeypatch):
    good["tiers"]["native_script"] = True
    core, _ = core_loader(good)
    script = "def run(context): pass"
    args = {"script": script, "read_only": True}
    declaration = config_module.effect_declaration(script, [])
    captured = []
    def urlopen(request, **kwargs):
        captured.append(json.loads(request.data))
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({"result": {"content": [{"type": "text", "text": "{\"count\": 2}"}]}}).encode()
        return response
    monkeypatch.setattr(core.urllib.request, "urlopen", urlopen)
    assert core.call("sys_execute_script", args, script_declaration=declaration) == (False, {"count": 2})
    assert captured == [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "sys_execute_script", "arguments": args}}]
    captured.clear()
    with pytest.raises(SystemExit, match="changed before transport"):
        core.call("sys_execute_script", {**args, "script": script + "\nchanged"}, script_declaration=declaration)
    with pytest.raises(SystemExit, match="allow.library_writes"):
        core.call("sys_execute_script", args, script_declaration=config_module.effect_declaration(script, ["library_writes"]))
    with pytest.raises(SystemExit, match="excluded"):
        core.call("sys_execute_script", args)
    assert captured == []


def test_only_exact_all_on_reference_routes_to_tracked_records(config_module, good):
    good["machine"] = "reference"
    good["cloud"].update(hub="Injected Hub", project="Injected Project", folder="Injected Folder")
    for group in ("tiers", "allow"):
        good[group].update({name: True for name in good[group]})
    assert config_module.record_root(good) == config_module._HERE
    for group, key in config_module.SWITCHES.values():
        partial = copy.deepcopy(good)
        partial[group][key] = False
        root = Path(config_module.record_root(partial))
        assert root.parts[-3:-1] == ("records", "reference") and len(root.name) == 64
        assert str(root) != config_module._HERE
    good["machine"] = "Reference"
    assert Path(config_module.record_root(good)).parts[-3:-1] == ("records", "Reference")
    assert config_module.REFERENCE_MACHINE == "reference"


@pytest.mark.parametrize("reference,partial", [(True, False), (False, False), (True, True)])
def test_core_and_family_receipt_consumer_bind_the_same_record_root(
        config_module, good, core_loader, reference, partial):
    good["machine"] = "reference" if reference else "community-unit"
    good["cloud"].update(hub="Injected Hub", project="Injected Project", folder="Injected Folder")
    for group in ("tiers", "allow"):
        good[group].update({name: True for name in good[group]})
    if partial:
        good["allow"]["preference_writes"] = False
    core, _path = core_loader(good)
    source = Path(__file__).resolve().parents[1] / "live" / "verify_runner.py"
    spec = importlib.util.spec_from_file_location("verify_runner_record_route_witness", source)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    expected = Path(config_module._HERE if reference and not partial else config_module.record_root(good))
    assert Path(core.VERIFIED) == expected / "VERIFIED_TOOLS.md"
    assert Path(runner.FAMILY_RECEIPT) == expected / "VERIFIED_FAMILIES.json"
    assert config_module.record_scope(good)["asked"] == config_module.asked(good)
