# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The eval proctor's decisions that do not need Fusion: what the executor receives, when a stage
refuses, which chain document is opened, when a run counts as stalled, and what the record says.
The Fusion wire is a stub returning (is_error, payload); nothing here launches an executor."""

import json
import io
import os
import sys
import types
from pathlib import Path

import pytest

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TESTS_DIR, "live", "evals"))
import proctor  # noqa: E402

_SCENARIO = """---
id: S99_Widget
fixture: none
---

## Prompt

Build a widget and save it into project {{PROJECT}}, folder {{FOLDER}}.

## Grader notes

A good widget has a hole. SECRET-GRADER-TEXT.
"""


def _wire(answers):
    """A stub call(tool, args) answering from a tool -> (is_error, payload) map and logging calls."""
    log = []

    def call(tool, args):
        log.append((tool, args))
        answer = answers[tool]
        return answer(args) if callable(answer) else answer
    call.log = log
    return call


class TestPrompt:
    @pytest.fixture
    def scenario(self, tmp_path):
        path = tmp_path / "S99_Widget.md"
        path.write_text(_SCENARIO, encoding="utf-8")
        preamble = tmp_path / "preamble.md"
        preamble.write_text("PREAMBLE RULES\n", encoding="utf-8")
        return path, preamble

    def test_prompt_is_preamble_then_brief_with_tokens_filled(self, scenario):
        path, preamble = scenario
        sid, fixture, body = proctor.read_scenario(str(path))
        prompt = proctor.build_prompt(body, "Proj", "Root/Eval-1", preamble_path=str(preamble))
        assert (sid, fixture) == ("S99_Widget", None)
        assert prompt.startswith("PREAMBLE RULES\n\nBuild a widget")
        assert "project Proj, folder Root/Eval-1." in prompt

    def test_grader_notes_never_reach_the_prompt(self, scenario):
        path, preamble = scenario
        _, _, body = proctor.read_scenario(str(path))
        prompt = proctor.build_prompt(body, "P", "F", preamble_path=str(preamble))
        assert "SECRET-GRADER-TEXT" not in prompt and "## Grader" not in prompt

    def test_skill_body_lands_after_the_brief(self, scenario, tmp_path, monkeypatch):
        path, preamble = scenario
        skills = tmp_path / "skills"
        (skills / "practice").mkdir(parents=True)
        (skills / "practice" / "SKILL.md").write_text("---\nname: practice\n---\n\nPLAN FIRST\n",
                                                      encoding="utf-8")
        monkeypatch.setattr(proctor, "SKILLS_DIR", str(skills))
        _, _, body = proctor.read_scenario(str(path))
        prompt = proctor.build_prompt(body, "P", "F", skill="practice", preamble_path=str(preamble))
        assert prompt.index("Build a widget") < prompt.index(proctor.SKILL_HEADER) < prompt.index("PLAN FIRST")
        assert "name: practice" not in prompt

    def test_a_chain_stage_receives_the_newest_prior_report_after_its_brief(self, scenario, tmp_path):
        path, preamble = scenario
        set_dir = tmp_path / "set"
        for nn, text in (("01", "old plan"), ("02", "newest plan")):
            (set_dir / f"S98_Base_{nn}").mkdir(parents=True)
            (set_dir / f"S98_Base_{nn}" / "report.txt").write_text(text, encoding="utf-8")
        (set_dir / "S98_Base_03").mkdir()
        assert proctor.prior_report(str(set_dir), "S98_Base") == "newest plan"
        assert proctor.prior_report(str(set_dir), None) == ""
        _, _, body = proctor.read_scenario(str(path))
        prompt = proctor.build_prompt(body, "P", "F", preamble_path=str(preamble),
                                      prior_report="newest plan")
        assert prompt.index("Build a widget") < prompt.index(proctor.REPORT_HEADER) < prompt.index("newest plan")

    def test_a_variant_file_keeps_the_scenario_id(self, tmp_path):
        path = tmp_path / "S99_Widget.B.md"
        path.write_text(_SCENARIO.replace("fixture: none", "fixture: S98_Base"), encoding="utf-8")
        sid, fixture, _ = proctor.read_scenario(str(path))
        assert (sid, fixture) == ("S99_Widget", "S98_Base")


class TestShippedScenarios:
    def test_every_scenario_parses_and_every_fixture_names_a_scenario(self):
        files = sorted(f for f in os.listdir(proctor.SCENARIOS) if f.endswith(".md"))
        ids = {}
        for name in files:
            sid, fixture, prompt = proctor.read_scenario(os.path.join(proctor.SCENARIOS, name))
            assert name.startswith(sid), f"{name}: id {sid!r} does not match its file"
            assert len(prompt) > 200, f"{name}: the prompt is too short to be a brief"
            assert "## Grader" not in prompt and "VERDICT:" not in prompt, name
            ids[name] = (sid, fixture)
        known = {sid for sid, _ in ids.values()}
        for name, (_, fixture) in ids.items():
            assert fixture is None or fixture in known, f"{name}: fixture {fixture!r} is no scenario"
        assert len(files) >= 16 and "S13_Surfaced-Bottle.B.md" in files


class TestProject:
    def test_missing_project_is_created_and_announced(self, capsys):
        call = _wire({"data_get": (False, {"projects": [{"name": "Other", "id": "p1"}]}),
                      "data_create_project": (False, {"created": True, "name": "Evals", "id": "p2"})})
        assert proctor.ensure_project("Evals", "Hub", call) == "Evals"
        assert call.log[-1] == ("data_create_project", {"name": "Evals"})
        assert "created project 'Evals' on hub 'Hub'" in capsys.readouterr().out

    def test_present_project_is_matched_case_insensitively_and_not_recreated(self):
        call = _wire({"data_get": (False, {"projects": [{"name": "MCP Evals", "id": "p1"}]})})
        assert proctor.ensure_project("mcp evals", "Hub", call) == "MCP Evals"
        assert [t for t, _ in call.log] == ["data_get"]

    def test_existing_set_folder_is_not_an_error(self):
        call = _wire({"data_create_folder": (True, "A folder named 'Eval-1' already exists at 'Root'")})
        assert proctor.ensure_folder("P", "Root", "Eval-1", call) == "Root/Eval-1"

    def test_other_folder_failures_stop_the_run(self):
        call = _wire({"data_create_folder": (True, "Project not found: P")})
        with pytest.raises(SystemExit):
            proctor.ensure_folder("P", "Root", "Eval-1", call)


class TestStaging:
    def _orient(self, bodies, occurrences):
        return (False, {"document": {"name": "Untitled"},
                        "design": {"bodies": bodies, "total_occurrences": occurrences}})

    def test_empty_stage_passes_on_zero_bodies_and_occurrences(self):
        call = _wire({"doc_new": (False, {"created": True}), "workspace_orient": self._orient(0, 0)})
        assert proctor.stage_empty(call) == "Untitled"

    def test_empty_stage_refuses_a_document_with_bodies(self):
        call = _wire({"doc_new": (False, {"created": True}), "workspace_orient": self._orient(82, 45)})
        with pytest.raises(SystemExit, match="bodies=82"):
            proctor.stage_empty(call)

    def test_empty_stage_refuses_an_unreadable_census(self):
        call = _wire({"doc_new": (False, {"created": True}), "workspace_orient": self._orient(None, 0)})
        with pytest.raises(SystemExit):
            proctor.stage_empty(call)

    def test_fixture_opens_the_newest_matching_document(self):
        files = [{"name": "S1_Foundation_01", "id": "urn:1"}, {"name": "S1_Foundation_03", "id": "urn:3"},
                 {"name": "S1_Foundation_02", "id": "urn:2"}, {"name": "S1_Foundation", "id": "urn:0"},
                 {"name": "S12_Dumbbell_01", "id": "urn:12"}]
        call = _wire({"data_get": (False, {"files": files}),
                      "doc_open": (False, {"opened": True}),
                      "workspace_orient": (False, {"document": {"name": "S1_Foundation_03 v1"}})})
        assert proctor.stage_fixture("S1_Foundation", "P", "F", call, sleep=lambda s: None) == "S1_Foundation_03"
        assert ("doc_open", {"file_id": "urn:3", "force_api_open": True}) in call.log

    def test_fixture_refuses_when_no_stage_output_is_in_the_set(self):
        call = _wire({"data_get": (False, {"files": [{"name": "S12_Dumbbell_01", "id": "urn:12"}]})})
        with pytest.raises(SystemExit, match="run S1_Foundation into this set first"):
            proctor.stage_fixture("S1_Foundation", "P", "F", call)

    def test_fixture_refuses_when_the_open_never_becomes_active(self, monkeypatch):
        clock = iter([0.0, 0.0, 200.0, 200.0])
        monkeypatch.setattr(proctor.time, "time", lambda: next(clock))
        call = _wire({"data_get": (False, {"files": [{"name": "S1_Foundation_01", "id": "urn:1"}]}),
                      "doc_open": (False, {"opened": True}),
                      "workspace_orient": (False, {"document": {"name": "Bench"}})})
        with pytest.raises(SystemExit, match="did not become the active document"):
            proctor.stage_fixture("S1_Foundation", "P", "F", call, wait_s=120, sleep=lambda s: None)


class TestWatch:
    _CALL = '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"x"}]}}\n'
    _THINK = '{"type":"system","subtype":"thinking_tokens","estimated_tokens":9000}\n'

    def test_thinking_does_not_reset_the_idle_clock_but_a_call_does(self):
        live = proctor.Liveness(0.0)
        live.read(self._CALL, 10.0)
        live.read(self._THINK, 500.0)
        assert live.idle_s(700.0) == 690.0
        live.read(self._CALL, 700.0)
        assert live.calls == 2 and live.idle_s(705.0) == 5.0
        assert live.call_times == [10, 700]

    def test_harness_label_names_only_the_switches_off_their_defaults(self):
        assert proctor.harness_label({"skill": None, "tool_search": False, "preamble": "preamble"}) == "-"
        assert proctor.harness_label({"skill": "practice", "tool_search": True,
                                      "preamble": "preamble-lean", "label": "bare"}) == \
            "skill:practice tool-search:on preamble:preamble-lean label:bare"

    def test_stall_limit_reads_the_env_and_falls_back(self, monkeypatch):
        monkeypatch.setenv("EVAL_STALL_S", "45")
        assert proctor.stall_limit_s() == 45
        monkeypatch.setenv("EVAL_STALL_S", "soon")
        assert proctor.stall_limit_s() == proctor.STALL_S_DEFAULT

    def _creds(self, tmp_path, expires_s):
        path = tmp_path / ".credentials.json"
        path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-1",
                                                      "expiresAt": int(expires_s * 1000)}}),
                        encoding="utf-8")
        return str(path)

    def test_oauth_token_is_read_when_it_has_time_left(self, tmp_path):
        assert proctor.oauth_token(self._creds(tmp_path, 10_000), now=0.0) == "tok-1"

    def test_oauth_token_refuses_when_close_to_expiry_or_absent(self, tmp_path):
        with pytest.raises(SystemExit, match="expires in"):
            proctor.oauth_token(self._creds(tmp_path, 600), now=0.0)
        with pytest.raises(SystemExit, match="claude login"):
            proctor.oauth_token(str(tmp_path / "missing.json"), now=0.0)

    def test_a_key_or_token_in_the_environment_passes_through_without_the_file(self, tmp_path):
        missing = str(tmp_path / "missing.json")
        assert proctor.executor_login({"ANTHROPIC_API_KEY": "sk-x"}, creds=missing) == {}
        assert proctor.executor_login({"CLAUDE_CODE_OAUTH_TOKEN": "t"}, creds=missing) == {}
        with pytest.raises(SystemExit, match="setup-token"):
            proctor.executor_login({}, creds=missing)

    def test_kill_tree_uses_taskkill_on_windows_and_kill_elsewhere(self, monkeypatch):
        ran = []
        monkeypatch.setattr(proctor.sys, "platform", "win32")
        monkeypatch.setattr(proctor, "subprocess",
                            types.SimpleNamespace(run=lambda cmd, **kw: ran.append(cmd)))
        proc = types.SimpleNamespace(pid=4242, kill=lambda: ran.append("kill"))
        proctor.kill_tree(proc)
        assert ran == [["taskkill", "/PID", "4242", "/T", "/F"]]
        monkeypatch.setattr(proctor.sys, "platform", "linux")
        proctor.kill_tree(proc)
        assert ran[-1] == "kill"

    @pytest.mark.parametrize("start_fails", [False, True])
    def test_launch_isolates_cwd_and_preserves_artifacts(self, tmp_path, monkeypatch, start_fails):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        monkeypatch.setattr(proctor.shutil, "which", lambda name: "claude")
        monkeypatch.setattr(proctor, "CONFIG_DIR", str(tmp_path / "config"))
        monkeypatch.setattr(proctor, "executor_login", lambda env: {})
        working_dirs = []
        def spawn(*args, **kwargs):
            cwd = kwargs["cwd"]
            working_dirs.append(cwd)
            assert os.path.isdir(cwd) and os.listdir(cwd) == []
            for parent in (str(tmp_path), proctor.harness.REPO_ROOT):
                assert not Path(cwd).resolve().is_relative_to(Path(parent).resolve())
            if start_fails:
                raise OSError("quota")
            return types.SimpleNamespace(stdin=io.StringIO(), stderr=io.StringIO(),
                                         poll=lambda: 0, wait=lambda: 0, returncode=0)
        monkeypatch.setattr(proctor.subprocess, "Popen", spawn)
        monkeypatch.setattr(proctor, "kill_tree", lambda proc: None)
        ended, call_times, returncode = proctor.launch("prompt", str(run_dir), "opus")
        assert ended == ("executor launch failed: quota" if start_fails else
                         "blocked init: no system init event")
        assert call_times == [] and returncode == (None if start_fails else 0)
        assert (run_dir / "stderr.txt").read_text(encoding="utf-8") == ("quota" if start_fails else "")
        assert (run_dir / "transcript.jsonl").exists() and (run_dir / "mcp.json").exists()
        assert len(working_dirs) == 1 and not os.path.exists(working_dirs[0])

    @pytest.mark.parametrize("server,tools,tool_search,expected", [
        ({"name": "fusion-essentials", "status": "failed"}, ["DesignSync"], False,
         "blocked init: fusion-essentials status failed"),
        (None, ["DesignSync"], False, "blocked init: fusion-essentials status missing"),
        ({"name": "fusion-essentials", "status": "connected"}, ["DesignSync"], False,
         "blocked init: no fusion-essentials tools"),
        ({"name": "fusion-essentials", "status": "connected"},
         ["DesignSync", "mcp__fusion-essentials__workspace_orient", "Bash"], False,
         "blocked init: tools held beside the Fusion ones: Bash, DesignSync"),
        ({"name": "fusion-essentials", "status": "connected"},
         ["mcp__fusion-essentials__workspace_orient", "ListMcpResourcesTool", "ReadMcpResourceTool",
          "ReadMcpResourceDirTool", "WaitForMcpServers"], False, "report"),
        ({"name": "fusion-essentials", "status": "connected"}, [], True, "report"),
        ({"name": "fusion-essentials", "status": "pending"}, ["DesignSync", "ToolSearch"], True, "report"),
        ({"name": "fusion-essentials", "status": "pending"}, [], False,
         "blocked init: fusion-essentials status pending"),
        ({"name": "fusion-essentials", "status": "failed"}, [], True,
         "blocked init: fusion-essentials status failed"),
    ])
    def test_launch_validates_exact_init_even_after_quick_exit(self, tmp_path, monkeypatch,
                                                                server, tools, tool_search, expected):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        monkeypatch.setattr(proctor.shutil, "which", lambda name: "claude")
        monkeypatch.setattr(proctor, "CONFIG_DIR", str(tmp_path / "config"))
        monkeypatch.setattr(proctor, "executor_login", lambda env: {})
        killed = []
        monkeypatch.setattr(proctor, "kill_tree", lambda proc: killed.append(True))
        init = {"type": "system", "subtype": "init", "tools": tools,
                "mcp_servers": [server] if server else []}

        def spawn(*args, **kwargs):
            kwargs["stdout"].write(json.dumps({"type": "system", "subtype": "notice"}) + "\n")
            kwargs["stdout"].write(json.dumps(init) + "\n")
            kwargs["stdout"].flush()
            return types.SimpleNamespace(stdin=io.StringIO(), stderr=io.StringIO(),
                                         poll=lambda: 0, wait=lambda: 0, returncode=0)

        monkeypatch.setattr(proctor.subprocess, "Popen", spawn)
        ended, calls, code = proctor._launch("prompt", str(run_dir), "opus", (), tool_search,
                                             str(tmp_path))
        assert (ended, calls, code) == (expected, [], 0)
        assert killed == [True]

    def test_a_second_server_at_start_blocks_the_run_by_name(self):
        init = {"tools": ["mcp__fusion-essentials__doc_get"],
                "mcp_servers": [{"name": "fusion-essentials", "status": "connected"},
                                {"name": "fusion-spatial", "status": "connected"}]}
        for tool_search in (False, True):
            assert proctor.start_verdict(init, tool_search) == (
                "blocked init: a second server is configured: fusion-spatial")

    @pytest.mark.parametrize("tool_search", [False, True])
    def test_built_in_tools_are_switched_off_unless_tool_search_needs_its_own(self, tmp_path, monkeypatch,
                                                                              tool_search):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        monkeypatch.setattr(proctor.shutil, "which", lambda name: "claude")
        monkeypatch.setattr(proctor, "CONFIG_DIR", str(tmp_path / "config"))
        monkeypatch.setattr(proctor, "executor_login", lambda env: {})
        monkeypatch.setattr(proctor, "kill_tree", lambda proc: None)
        lines = []

        def spawn(cmd, **kwargs):
            lines.append(cmd)
            return types.SimpleNamespace(stdin=io.StringIO(), stderr=io.StringIO(),
                                         poll=lambda: 0, wait=lambda: 0, returncode=0)

        monkeypatch.setattr(proctor.subprocess, "Popen", spawn)
        proctor._launch("prompt", str(run_dir), "opus", (), tool_search, str(tmp_path))
        cmd = lines[0]
        assert ("--tools" in cmd) is (not tool_search)
        if not tool_search:
            assert cmd[cmd.index("--tools") + 1] == ""
        assert cmd[cmd.index("--allowedTools") + 1] == "mcp__fusion-essentials__*"

    def test_blocked_init_records_artifacts_without_save_or_next_run(self, tmp_path, monkeypatch):
        scenario = tmp_path / "S99_Widget.md"
        scenario.write_text(_SCENARIO, encoding="utf-8")
        results = tmp_path / "results"
        monkeypatch.setattr(proctor, "RESULTS", str(results))
        monkeypatch.setattr(proctor, "INDEX", str(results / "index.md"))
        monkeypatch.setattr(proctor, "scenario_path", lambda name: str(scenario))
        monkeypatch.setattr(proctor.cloud_config, "load_config",
                            lambda: ({"hub": "H", "project": "P", "folder": "F"}, None))
        monkeypatch.setattr(proctor.harness, "health_gate", lambda: None)
        monkeypatch.setattr(proctor, "ensure_hub", lambda hub, call: None)
        monkeypatch.setattr(proctor, "ensure_project", lambda project, hub, call: project)
        monkeypatch.setattr(proctor, "ensure_folder", lambda project, folder, name, call: name)
        staged = []
        monkeypatch.setattr(proctor, "stage_empty", lambda call: staged.append("staged") or "staged-doc")
        monkeypatch.setattr(proctor, "build_prompt", lambda *args, **kwargs: "prompt")
        monkeypatch.setattr(proctor, "launch", lambda *args: ("blocked init: fusion-essentials status failed", [], 0))
        monkeypatch.setattr(proctor, "audit", lambda transcript: (0, 0, ""))
        monkeypatch.setattr(proctor, "run_facts", lambda transcript: (None, ""))
        saves = []
        monkeypatch.setattr(proctor, "save_result", lambda *args: saves.append(args))
        monkeypatch.setattr(proctor.sys, "argv", ["proctor.py", "S99_Widget", "--runs", "3"])

        assert proctor.main() == 1
        run_dirs = list(results.glob("Eval-*/S99_Widget_*"))
        assert len(run_dirs) == 1 and staged == ["staged"] and saves == []
        rec = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
        assert rec["outcome"] == rec["execution_state"] == "blocked_init"
        assert rec["saved"]["error"] == "save skipped: blocked init: fusion-essentials status failed"
        assert (run_dirs[0] / "prompt.txt").exists() and (run_dirs[0] / "report.txt").exists()
        assert "blocked init: fusion-essentials status failed" in (results / "index.md").read_text(encoding="utf-8")

    def test_main_records_failed_staged_and_partial_runs_and_returns_nonzero(self, tmp_path, monkeypatch):
        scenario = tmp_path / "S99_Widget.md"
        scenario.write_text(_SCENARIO, encoding="utf-8")
        results = tmp_path / "results"
        outcomes = iter([
            ("executor exited 1", [], 1, 0, ""),
            ("executor exited 1", [1.0], 1, 2, "partial"),
            ("report", [1.0], 0, 2, "done"),
        ])
        monkeypatch.setattr(proctor, "RESULTS", str(results))
        monkeypatch.setattr(proctor, "INDEX", str(results / "index.md"))
        monkeypatch.setattr(proctor, "scenario_path", lambda name: str(scenario))
        monkeypatch.setattr(proctor.cloud_config, "load_config",
                            lambda: ({"hub": "H", "project": "P", "folder": "F"}, None))
        monkeypatch.setattr(proctor.harness, "health_gate", lambda: None)
        monkeypatch.setattr(proctor, "ensure_hub", lambda hub, call: None)
        monkeypatch.setattr(proctor, "ensure_project", lambda project, hub, call: project)
        monkeypatch.setattr(proctor, "ensure_folder", lambda project, folder, name, call: name)
        monkeypatch.setattr(proctor, "stage_empty", lambda call: "staged-doc")
        monkeypatch.setattr(proctor, "build_prompt", lambda *args, **kwargs: "prompt")
        monkeypatch.setattr(proctor, "save_result",
                            lambda name, project, folder, run_dir, call: {
                                "web_url": None, "document_id": None, "error": "saved-partial"})
        monkeypatch.setattr(proctor, "launch",
                            lambda prompt, run_dir, model, deny, tool_search: next(outcomes)[:3])
        monkeypatch.setattr(proctor, "audit",
                            lambda transcript: (next_audit.pop(0), 0, ""))
        said = ["You've hit your weekly limit | resets 11pm", "", "ignored on a report"]
        monkeypatch.setattr(proctor, "run_facts",
                            lambda transcript: ({"tools_beside_fusion": []}, said.pop(0) if said else ""))
        next_audit = [0, 2, 2]
        monkeypatch.setattr(proctor.sys, "argv",
                            ["proctor.py", "S99_Widget", "--runs", "3"])
        assert proctor.main() == 1
        records = [json.loads((path / "run.json").read_text(encoding="utf-8"))
                   for path in sorted(results.glob("Eval-*/*")) if (path / "run.json").is_file()]
        assert [record["outcome"] for record in records] == [
            "executor_failed", "executor_failed", "executor_completed"]
        assert [record["execution_state"] for record in records] == [
            "staged_only", "partial_failed", "completed"]
        assert records[0]["executor_exit"] == 1 and records[0]["calls"] == 0
        assert records[1]["calls"] == 2 and records[2]["executor_exit"] == 0
        # The client's own error text joins a failed exit, in the record and on one index line.
        assert [record["ended"] for record in records] == [
            "executor exited 1: You've hit your weekly limit | resets 11pm", "executor exited 1", "report"]
        assert records[0]["start"] == {"tools_beside_fusion": []}
        index = (results / "index.md").read_text(encoding="utf-8").splitlines()
        assert "| executor exited 1: You've hit your weekly limit / resets 11pm |" in index[2]
        assert index[2].count("|") == index[1].count("|")
        outcomes = iter([("report", [], 0)])
        next_audit[:] = [0]
        monkeypatch.setattr(proctor.sys, "argv",
                            ["proctor.py", "S99_Widget", "--runs", "1"])
        assert proctor.main() == 0
        latest = sorted(results.glob("Eval-*/*"))[-1] / "run.json"
        assert json.loads(latest.read_text(encoding="utf-8"))["outcome"] == "executor_completed"



class TestRecord:
    def _transcript(self, tmp_path, lines):
        path = tmp_path / "t.jsonl"
        path.write_text("".join(json.dumps(ev) + "\n" for ev in lines), encoding="utf-8")
        return str(path)

    def test_audit_counts_fusion_calls_only_and_reads_the_result(self, tmp_path):
        path = self._transcript(tmp_path, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__fusion-essentials__doc_get"},
                {"type": "tool_use", "name": "TodoWrite"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__fusion-essentials__model_extrude"}]}},
            {"type": "result", "result": "Built it.", "usage": {"output_tokens": 1234}}])
        assert proctor.audit(path) == (2, 1234, "Built it.")

    def test_run_facts_read_the_start_record_and_only_an_error_result(self, tmp_path):
        init = {"type": "system", "subtype": "init", "claude_code_version": "2.1.197",
                "model": "claude-opus-4-8", "tools": ["mcp__fusion-essentials__doc_get", "DesignSync"],
                "mcp_servers": [{"name": "fusion-essentials", "status": "pending"}]}
        start = {"client_version": "2.1.197", "model": "claude-opus-4-8",
                 "servers": {"fusion-essentials": "pending"}, "fusion_tools": 1,
                 "tools_beside_fusion": ["DesignSync"]}
        limit = {"type": "result", "is_error": True, "result": "You've hit your weekly limit\n resets 11pm"}
        assert proctor.run_facts(self._transcript(tmp_path, [init, limit])) == (
            start, "You've hit your weekly limit resets 11pm")
        report = {"type": "result", "is_error": False, "result": "Built it."}
        assert proctor.run_facts(self._transcript(tmp_path, [init, report])) == (start, "")
        assert proctor.run_facts(self._transcript(tmp_path, [report])) == (None, "")

    def test_save_reports_the_refusal_and_still_takes_the_screenshot(self, tmp_path):
        call = _wire({"doc_save_as": (True, "Fusion declined to save"),
                      "view_screenshot": (False, {"ok": True})})
        saved = proctor.save_result("S99_01", "P", "F", str(tmp_path), call)
        assert saved["error"] == "Fusion declined to save" and saved["screenshot"] == "iso.png"
        assert call.log[-1][0] == "view_screenshot"
        assert call.log[-1][1]["file_path"] == os.path.join(str(tmp_path), "iso.png")

    def test_save_waits_for_the_url_to_settle(self, tmp_path):
        reads = iter([(False, {"active": {"fusion_web_url": None}}),
                      (False, {"active": {"fusion_web_url": "https://x/9", "document_id": "urn:9"}})])
        call = _wire({"doc_save_as": (False, {"saved": True, "document_id": None}),
                      "doc_get": lambda args: next(reads),
                      "view_screenshot": (False, {})})
        naps = []
        saved = proctor.save_result("S99_01", "P", "F", str(tmp_path), call, sleep=naps.append)
        assert (saved["document_id"], saved["web_url"], saved["error"]) == ("urn:9", "https://x/9", None)
        assert naps == [5]

    def test_index_row_links_the_document_or_names_the_failure(self):
        rec = {"started": "10:00", "set": "Eval-S99", "variant": "S99_Widget.B",
               "model": "opus", "skill": None, "denied": [], "calls": 40, "output_tokens": 5000,
               "ended": "report", "saved": {"web_url": None, "error": "declined"}}
        row = proctor.index_row(rec)
        assert row.startswith("| 10:00 | Eval-S99 | S99_Widget.B | opus | - | - | 40 | 5000 | report | declined |")
        rec["saved"] = {"web_url": "https://x/1", "error": None}
        assert proctor.index_row(rec).rstrip().endswith("| https://x/1 |")

    def test_run_dirs_number_from_the_first_free_slot(self, tmp_path):
        os.makedirs(tmp_path / "S99_Widget_01")
        os.makedirs(tmp_path / "S99_Widget_02")
        assert proctor.next_run_dir(str(tmp_path), "S99_Widget") == (
            os.path.join(str(tmp_path), "S99_Widget_03"), "03")
