# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The opt-in cloud tier's gate: the local config, and the probe that reads it.

The tier writes into an operator's REAL Autodesk hub, so the only thing standing between a default
sweep and someone's data is this loader answering "no config" and the probe turning that into a
capability the runner holds every cloud act back on. Both halves are pinned here, plus the two
readings that are refusals rather than licences: a config naming a hub the session is not on, and a
config naming a project the hub does not list.
"""

import pytest
import json
import os
import sys

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TESTS_DIR, "live"))
import cloud_config  # noqa: E402
import tool_verify  # noqa: E402
import verify_core  # noqa: E402


def _machine(cloud):
    return {"machine": "cloud-unit", "port": 37182,
            "tiers": {"native_script": False, "machining_extension": False, "cloud": True},
            "cloud": cloud,
            "allow": {"library_writes": False, "preference_writes": False, "addin_reload": False}}


def _write(tmp_path, body):
    if isinstance(body, dict):
        body = _machine(body)
    path = tmp_path / cloud_config.CONFIG_NAME
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return str(path)


_GOOD = {"hub": "Some Hub", "project": "Some Project", "folder": "Sweep"}


class TestLoadConfig:
    """What the loader accepts, and what its refusal has to say."""

    def test_a_complete_config_loads_the_three_strings_stripped(self, tmp_path):
        path = _write(tmp_path, {"hub": " Some Hub ", "project": "Some Project",
                                 "folder": "Sweep/Runs"})
        config, problem = cloud_config.load_config(path)
        assert problem is None
        assert config == {"hub": "Some Hub", "project": "Some Project", "folder": "Sweep/Runs"}

    def test_unknown_cloud_key_and_legacy_scope_cannot_opt_in(self, tmp_path):
        path = _write(tmp_path, {**_GOOD, "extra": "unadmitted"})
        config, problem = cloud_config.load_config(path)
        assert config is None and "unknown key: cloud.extra" in problem
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(_GOOD, stream)
        config, problem = cloud_config.load_config(path)
        assert config is None and "missing: machine" in problem and "missing: tiers" in problem

    def test_a_missing_file_names_the_path_and_the_shape(self, tmp_path):
        path = str(tmp_path / cloud_config.CONFIG_NAME)
        config, problem = cloud_config.load_config(path)
        assert config is None
        assert path in problem and '"hub"' in problem and '"project"' in problem
        assert '"folder"' in problem

    def test_an_empty_or_absent_key_is_named_in_the_refusal(self, tmp_path):
        # A key present but BLANK is as unusable as one absent, and the operator has to be told
        # which - so the names are read out of the refusal's own clause, not out of the shape it
        # quotes afterwards (every key name appears in that, so matching there proves nothing).
        path = _write(tmp_path, {"hub": "Some Hub", "project": "   "})
        config, problem = cloud_config.load_config(path)
        assert config is None
        named = problem.split("Copy tests/live/")[0]
        assert "project" in named and "folder" in named and "hub" not in named

    def test_unreadable_json_and_a_non_object_both_refuse(self, tmp_path):
        path = _write(tmp_path, "{not json")
        assert cloud_config.load_config(path)[0] is None
        path = _write(tmp_path, ["Some Hub"])
        config, problem = cloud_config.load_config(path)
        assert config is None and "not an object" in problem


class TestCloudTierProbe:
    """The probe: config first, then the hub the session is actually on."""

    @staticmethod
    def _wire(monkeypatch, answer, folder=(False, {"file_count": 0, "files": []})):
        """The two reads the probe takes: the hub-level data_get, then the FOLDER one."""
        def call(tool, args):
            return folder if args.get("folder") else answer
        monkeypatch.setattr(tool_verify, "call", call)

    @staticmethod
    def _config(monkeypatch, config, problem=None):
        monkeypatch.setattr(cloud_config, "load_config",
                            lambda path=None: (config, problem))

    def test_no_config_is_a_definite_no_and_costs_no_wire_call(self, monkeypatch):
        # False, not None: "this machine is not configured for the tier" is a settled answer, and a
        # cloud read taken to establish it would be a network call for nothing.
        called = []
        monkeypatch.setattr(tool_verify, "call",
                            lambda tool, args: called.append(tool) or (False, {}))
        self._config(monkeypatch, None, "no config here")
        assert verify_core._cloud_tier_probe() is False
        assert called == []

    def test_the_configured_hub_and_project_are_entitled(self, monkeypatch):
        self._config(monkeypatch, dict(_GOOD))
        self._wire(monkeypatch, (False, {"active_hub": "Some Hub", "project_count": 2,
                                         "projects": [{"name": "Other"},
                                                      {"name": "Some Project"}]}))
        assert verify_core._cloud_tier_probe() is True

    def test_another_hub_is_refused_rather_than_switched_to(self, monkeypatch):
        # the whole safety property: a session signed in elsewhere must not have the tier run
        # against it, and data_switch_hub would close the story document to correct it.
        self._config(monkeypatch, dict(_GOOD))
        self._wire(monkeypatch, (False, {"active_hub": "Someone Else's Hub", "project_count": 1,
                                         "projects": [{"name": "Some Project"}]}))
        assert verify_core._cloud_tier_probe() is False

    def test_a_project_the_hub_does_not_list_is_refused(self, monkeypatch):
        self._config(monkeypatch, dict(_GOOD))
        self._wire(monkeypatch, (False, {"active_hub": "Some Hub", "project_count": 1,
                                         "projects": [{"name": "Other"}]}))
        assert verify_core._cloud_tier_probe() is False

    def test_a_folder_the_project_does_not_answer_with_is_refused(self, monkeypatch):
        # THE mkdir -p HAZARD: data_create_folder creates every missing segment of a parent path, so
        # a mistyped folder does not fail the act - it MINTS folders in the operator's hub, the
        # create's own auto_created_parents check reds, and the run's deletes never name them. The
        # destination is confirmed before any act can reach a create.
        self._config(monkeypatch, dict(_GOOD))
        self._wire(monkeypatch,
                   (False, {"active_hub": "Some Hub", "project_count": 1,
                            "projects": [{"name": "Some Project"}]}),
                   folder=(True, "Folder 'Sweep' not found: no subfolder 'Sweep' in '(project "
                                 "root)'. Subfolders there: Other."))
        assert verify_core._cloud_tier_probe() is False

    def test_the_folder_read_is_scoped_to_the_configured_project_and_folder(self, monkeypatch):
        seen = []
        self._config(monkeypatch, dict(_GOOD))

        def call(tool, args):
            seen.append((tool, dict(args)))
            if args.get("folder"):
                return False, {"file_count": 0, "files": []}
            return False, {"active_hub": "Some Hub", "project_count": 1,
                           "projects": [{"name": "Some Project"}]}
        monkeypatch.setattr(tool_verify, "call", call)
        assert verify_core._cloud_tier_probe() is True
        assert seen == [("data_get", {}),
                        ("data_get", {"project": "Some Project", "folder": "Sweep",
                                      "recursive": False})]

    def test_a_cloud_read_that_did_not_answer_is_unreadable_not_a_licence(self, monkeypatch):
        # None routes as unmet exactly as False does, but it says the hub was never compared -
        # reading it as False would report a verdict nothing measured.
        self._config(monkeypatch, dict(_GOOD))
        self._wire(monkeypatch, (True, "not signed in"))
        assert verify_core._cloud_tier_probe() is None
        self._wire(monkeypatch, (False, "a string, not a payload"))
        assert verify_core._cloud_tier_probe() is None


class TestTheTierIsWired:
    """The probe is reachable by the name the acts declare, and the acts declare it."""

    def test_the_capability_name_resolves_to_this_probe(self):
        assert (verify_core.CAPABILITY_PROBES[tool_verify.CLOUD_TIER]
                is verify_core._cloud_tier_probe)

    def test_every_cloud_act_declares_its_exact_gate(self):
        ordinary = {
            "ACT 11a - CLOUD: THE DATA MODEL",
            "ACT 11b - CLOUD: THE SAVED DOCUMENT",
            "ACT 11c - CLOUD: THE DRAWING",
            "ACT 11d - CLOUD: CAM TEMPLATE PERSISTENCE",
            "ACT 11e - CLOUD: CONFIGURATION COLUMN REFUSALS",
            "ACT 11f - CLOUD: DERIVE EDITS",
            "ACT 11h - CLOUD: COMPONENT COPY",
        }
        link = "ACT 11b2 - CLOUD: LINK GUARD REVIEW"
        cloud = {name for name, _p, _n, _f in tool_verify.ACTS if name.startswith("ACT 11")}
        assert cloud == ordinary | {link}
        assert {name: tool_verify.ACT_NEEDS.get(name) for name in cloud} == {
            **{name: tool_verify.CLOUD_TIER for name in ordinary},
            link: tool_verify.CLOUD_LINK_CRASH_REVIEW,
        }

    def test_the_acts_address_the_project_the_loader_read(self):
        # a hub or project name never lives in the repo, so every step naming one has to be carrying
        # what the loader read - a literal here would address someone's hub on every run.
        import verify_acts_cloud as acts
        named = [step[1]["project"] for step in acts._CLOUD_DATA
                 if isinstance(step[1], dict) and "project" in step[1]]
        assert named, "no data act step names a project"
        assert set(named) == {cloud_config.PROJECT}
        assert acts.RUN_PATH.startswith(cloud_config.FOLDER + "/")

    def test_an_unconfigured_checkout_carries_no_hub_name(self):
        # the state a reviewer's checkout is in: no config file, so the module-level strings are
        # empty and the probe's False is what stands between the sweep and anyone's data.
        if os.path.isfile(cloud_config.CONFIG_PATH):
            return          # this machine IS configured - the assertion below is not its state
        assert (cloud_config.HUB, cloud_config.PROJECT, cloud_config.FOLDER) == ("", "", "")


@pytest.fixture
def destination_case():
    config = {"hub": "Test Hub", "project": "Test Project", "folder": "OldFolder"}
    record = cloud_config.new_destination(config, "c" * 64, "test-run")
    hub = {"active_hub": "Test Hub", "project_count": 1,
           "projects": [{"name": "Test Project", "id": "project-1"}]}
    created = {"created": True, "name": record["folder"], "path": record["folder"],
               "project": "Test Project", "id": "folder-1", "auto_created_parents": []}
    summary = {"exists": True, "project": {"name": "Test Project", "id": "project-1"},
               "folder": {"name": record["folder"], "id": "folder-1", "path": record["folder"],
                          "is_root": False}, "immediate_file_count": 0,
               "immediate_child_folder_count": 0, "unavailable_fields": []}
    calls, snapshots = [], []
    def wire(tool, args):
        calls.append((tool, args))
        if tool == "data_create_folder":
            assert snapshots[-1]["state"] == "creating"
            return False, created
        return False, summary if args.get("folder") else hub
    return record, hub, created, summary, calls, snapshots, wire


class TestFreshDestination:
    def test_each_plan_has_its_own_top_level_name_without_changing_the_operator(self):
        config = {"hub": "Test Hub", "project": "Test Project", "folder": "Nested/Old"}
        first = cloud_config.new_destination(config, "c" * 64, "same-label")
        second = cloud_config.new_destination(config, "c" * 64, "same-label")
        assert first["folder"] != second["folder"]
        assert "/" not in first["folder"] and "\\" not in first["folder"]
        assert first["operator"] == config and config["folder"] == "Nested/Old"
        assert first["state"] == "planned" and first["folder_id"] is None

    def test_create_is_fenced_by_a_durable_attempt_and_an_independent_empty_read(self, destination_case):
        record, _hub, _created, _summary, calls, snapshots, wire = destination_case
        result = cloud_config.admit_destination(wire, record, snapshots.append)
        assert [tool for tool, _ in calls] == ["data_get", "data_create_folder", "data_get"]
        assert calls[1][1] == {"folder_name": record["folder"], "project_id": "project-1", "parent_folder": ""}
        assert calls[2][1] == {"project_id": "project-1", "folder": record["folder"], "include": ["summary"]}
        assert [s["state"] for s in snapshots] == ["creating", "creating", "creating", "ready"]
        assert result["folder_id"] == "folder-1" and result["project_id"] == "project-1"
        assert record["state"] == "ready"
        result["folder_id"] = "tampered"
        assert record["folder_id"] == "folder-1"

    @pytest.mark.parametrize("field,value", [
        ("immediate_file_count", 1), ("immediate_child_folder_count", 1),
        ("immediate_file_count", None), ("immediate_file_count", True),
        ("immediate_child_folder_count", -1), ("unavailable_fields", ["immediate_file_count"]),
        ("exists", False),
    ])
    def test_unknown_or_nonempty_destination_stops_without_retry(self, destination_case, field, value):
        record, _hub, _created, summary, calls, snapshots, wire = destination_case
        summary[field] = value
        with pytest.raises(cloud_config.DestinationError, match="identity/emptiness"):
            cloud_config.admit_destination(wire, record, snapshots.append)
        assert record["state"] == "creating" and len(calls) == 3
        assert all(s["state"] == "creating" for s in snapshots)
        assert snapshots[-1]["folder_id"] == "folder-1"
        assert snapshots[-1]["creation_reply"]["id"] == "folder-1"
        with pytest.raises(cloud_config.DestinationError, match="uncertain"):
            cloud_config.admit_destination(wire, record, snapshots.append)
        assert len(calls) == 3

    @pytest.mark.parametrize("field,value", [("id", "different"), ("path", "OldFolder"),
                                            ("name", "wrong"), ("is_root", True)])
    def test_summary_must_name_the_created_folder(self, destination_case, field, value):
        record, _hub, _created, summary, calls, snapshots, wire = destination_case
        summary["folder"][field] = value
        with pytest.raises(cloud_config.DestinationError, match="identity/emptiness"):
            cloud_config.admit_destination(wire, record, snapshots.append)
        assert record["state"] == "creating" and len(calls) == 3

    @pytest.mark.parametrize("field,value", [("created", False), ("path", "OldFolder"),
                                            ("id", None), ("auto_created_parents", ["OldFolder"])])
    def test_malformed_create_stops_before_another_call(self, destination_case, field, value):
        record, _hub, created, _summary, calls, snapshots, wire = destination_case
        created[field] = value
        with pytest.raises(cloud_config.DestinationError, match="creation failed"):
            cloud_config.admit_destination(wire, record, snapshots.append)
        assert len(calls) == 2 and record["state"] == "creating"

    def test_wrong_hub_or_duplicate_project_costs_no_create(self, destination_case):
        record, hub, _created, _summary, calls, snapshots, wire = destination_case
        hub["active_hub"] = "Other Hub"
        with pytest.raises(cloud_config.DestinationError, match="hub/project"):
            cloud_config.admit_destination(wire, record, snapshots.append)
        hub["active_hub"] = "Test Hub"
        hub["projects"].append({"name": "Test Project", "id": "other-project"})
        with pytest.raises(cloud_config.DestinationError, match="ambiguous"):
            cloud_config.admit_destination(wire, record, snapshots.append)
        assert [tool for tool, _ in calls] == ["data_get", "data_get"] and snapshots == []

    def test_failed_attempt_persistence_prevents_the_cloud_write(self, destination_case):
        record, _hub, _created, _summary, calls, _snapshots, wire = destination_case
        def refuse(_record):
            raise OSError("disk full")
        with pytest.raises(OSError, match="disk full"):
            cloud_config.admit_destination(wire, record, refuse)
        assert [tool for tool, _ in calls] == ["data_get"]
        assert record["state"] == "creating"

    def test_interrupted_create_is_never_retried(self, destination_case):
        record, _hub, _created, _summary, calls, snapshots, wire = destination_case
        def interrupted(tool, args):
            if tool == "data_create_folder":
                raise TimeoutError("pending write")
            return wire(tool, args)
        with pytest.raises(TimeoutError, match="pending write"):
            cloud_config.admit_destination(interrupted, record, snapshots.append)
        with pytest.raises(cloud_config.DestinationError, match="uncertain"):
            cloud_config.admit_destination(wire, record, snapshots.append)
        assert snapshots[-1]["state"] == "creating" and len(calls) == 1

    def test_resume_checks_identity_and_allows_the_runs_own_saved_files(self, destination_case):
        record, _hub, _created, summary, calls, snapshots, wire = destination_case
        cloud_config.admit_destination(wire, record, snapshots.append)
        calls.clear()
        summary["immediate_file_count"] = 12
        summary["immediate_child_folder_count"] = 2
        result = cloud_config.admit_destination(wire, record, snapshots.append)
        assert len(calls) == 2 and all(tool == "data_get" for tool, _ in calls)
        assert result["folder_id"] == "folder-1" and result["state"] == "ready"
        summary["folder"]["id"] = "unrelated-folder"
        with pytest.raises(cloud_config.DestinationError, match="identity/emptiness"):
            cloud_config.admit_destination(wire, record, snapshots.append)
        assert all(tool == "data_get" for tool, _ in calls)

    @pytest.mark.parametrize("field,value", [("config_hash", "changed"), ("run_id", "other"),
                                            ("folder", "OldFolder"), ("state", "creating"),
                                            ("artifact_stamp", "../unsafe"), ("folder_id", "partial")])
    def test_resume_refuses_mismatched_or_uncertain_bindings(self, destination_case, field, value):
        record = destination_case[0]
        record[field] = value
        with pytest.raises(cloud_config.DestinationError, match="destination"):
            cloud_config.validate_destination(record, record["operator"], "c" * 64, "test-run")


@pytest.fixture
def isolated_cloud_binding(monkeypatch, tmp_path):
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("isolated_cloud_config", cloud_config.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config_path = tmp_path / "operator.json"
    config_path.write_text(json.dumps(_machine({"hub": "Test Hub", "project": "Test Project", "folder": "OldFolder"})) + "\n")
    original = config_path.read_bytes()
    monkeypatch.setattr(module, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(module, "_MANIFEST_DIR", str(tmp_path / "results"))
    monkeypatch.delitem(sys.modules, "verify_acts_cloud", raising=False)
    return module, config_path, original, tmp_path / "results"


class TestCloudBootstrap:
    def test_paths_bind_before_rows_without_writing_the_operator(self, isolated_cloud_binding):
        config, path, original, _results = isolated_cloud_binding
        config.bootstrap(["--run", "case-1", "--trace"])
        record = config.destination_snapshot()
        assert config.FOLDER == record["folder"] != "OldFolder"
        assert (config.HUB, config.PROJECT) == ("Test Hub", "Test Project")
        assert config.ARTIFACT_STAMP == record["artifact_stamp"]
        assert path.read_bytes() == original
        assert config.load_config()[0]["folder"] == "OldFolder"
        assert config.start_invocation("case-1", False) is True
        with pytest.raises(config.DestinationError, match="new process"):
            config.start_invocation("case-1", False)

    @pytest.mark.parametrize("argv", [["--check"], ["--check", "--full-scope"], ["--help"]])
    def test_offline_check_or_help_creates_no_binding(self, isolated_cloud_binding, argv):
        config, path, original, results = isolated_cloud_binding
        config.bootstrap(argv)
        assert config.destination_snapshot() is None and not results.exists()
        assert path.read_bytes() == original

    def test_late_binding_is_refused(self, isolated_cloud_binding, monkeypatch):
        import sys
        config, _path, _original, _results = isolated_cloud_binding
        monkeypatch.setitem(sys.modules, "verify_acts_cloud", object())
        with pytest.raises(config.DestinationError, match="rows already exist"):
            config.bootstrap(["--run", "case-1"])

    @pytest.mark.parametrize("run_id", ["../other", "a/b", "a\\b", "", "x" * 97])
    def test_run_ids_cannot_escape_the_checkpoint_directory(self, isolated_cloud_binding, run_id):
        config, _path, _original, results = isolated_cloud_binding
        with pytest.raises(config.DestinationError, match="simple run ID"):
            config.bootstrap(["--run", run_id])
        assert not results.exists()

    def test_an_unprepared_library_run_is_refused(self, isolated_cloud_binding):
        config, _path, _original, _results = isolated_cloud_binding
        with pytest.raises(config.DestinationError, match="not bound"):
            config.start_invocation(None, False)

    def test_resume_keeps_paths_stamp_and_created_identity(self, isolated_cloud_binding):
        config, path, original, results = isolated_cloud_binding
        config.bootstrap(["--run", "case-1"])
        planned = config.destination_snapshot()
        results.mkdir()
        (results / "run-case-1.json").write_text(json.dumps({"cloud_destination": planned}))
        ready = dict(planned, state="ready", project_id="project-1", folder_id="folder-1")
        config._save_destination(ready)
        config.bootstrap(["--run", "case-1", "--resume"])
        assert config.destination_snapshot() == ready
        assert config.FOLDER == planned["folder"]
        assert config.ARTIFACT_STAMP == planned["artifact_stamp"]
        assert path.read_bytes() == original
        assert config.start_invocation("case-1", True) is True

    def test_a_pending_attempt_blocks_resume_of_an_older_planned_checkpoint(self, isolated_cloud_binding):
        config, _path, _original, results = isolated_cloud_binding
        config.bootstrap(["--run", "case-1"])
        planned = config.destination_snapshot()
        results.mkdir()
        (results / "run-case-1.json").write_text(json.dumps({"cloud_destination": planned}))
        config._save_destination(dict(planned, state="creating"))
        with pytest.raises(config.DestinationError, match="uncertain"):
            config.bootstrap(["--run", "case-1", "--resume"])

    def test_byte_changed_config_blocks_resume_even_if_the_strings_are_equal(self, isolated_cloud_binding):
        config, path, original, results = isolated_cloud_binding
        config.bootstrap(["--run", "case-1"])
        results.mkdir()
        (results / "run-case-1.json").write_text(json.dumps({"cloud_destination": config.destination_snapshot()}))
        path.write_bytes(original + b"\n")
        with pytest.raises(config.DestinationError, match="changed"):
            config.bootstrap(["--run", "case-1", "--resume"])

    def test_completed_identity_without_its_manifest_is_refused(self, isolated_cloud_binding):
        config, _path, _original, results = isolated_cloud_binding
        config.bootstrap(["--run", "case-1"])
        record = dict(config.destination_snapshot(), state="ready", project_id="project-1", folder_id="folder-1")
        results.mkdir()
        (results / "run-case-1.json").write_text(json.dumps({"cloud_destination": record}))
        with pytest.raises(config.DestinationError, match="no retained"):
            config.bootstrap(["--run", "case-1", "--resume"])


@pytest.mark.parametrize("field,value", [("projects", None), ("project_count", None),
                                        ("project_count", True), ("project_count", 2), ("time_truncated", True)])
def test_unreadable_project_census_cannot_admit_a_create(destination_case, field, value):
    record, hub, _created, _summary, calls, snapshots, wire = destination_case
    hub[field] = value
    with pytest.raises(cloud_config.DestinationError, match="hub/project"):
        cloud_config.admit_destination(wire, record, snapshots.append)
    assert [tool for tool, _ in calls] == ["data_get"] and snapshots == []
