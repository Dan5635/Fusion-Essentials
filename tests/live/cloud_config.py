# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Read local cloud scope and bind each CLI run to its own top-level destination.

The operator's hub/project config stays byte-untouched. CLI bootstrap selects paths before
rows are constructed; admission creates once and independently verifies an empty folder.
A resume retains that exact folder and refuses an uncertain creation record.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import uuid
import machine_config

_HERE = os.path.dirname(os.path.abspath(__file__))

CONFIG_NAME = machine_config.CONFIG_NAME
CONFIG_PATH = machine_config.config_path()[0]

# The three strings a run of the tier needs, and the shape every refusal quotes back.
KEYS = ("hub", "project", "folder")
CONFIG_SHAPE = ('{"hub": "<the hub name data_get publishes as active_hub>", '
                '"project": "<a project in that hub>", '
                '"folder": "<the folder path under it the acts build in>"}')


def load_config(path=None):
    """Return cloud scope from the one complete machine file, never a stale legacy file."""
    chosen = CONFIG_PATH if path is None else path
    config, found = machine_config.load(chosen)
    if found:
        return None, machine_config.refusal(chosen, "cloud scope", found)
    if config["tiers"]["cloud"] is not True:
        return None, "tiers.cloud is explicitly false in " + str(chosen)
    return {key: config["cloud"][key].strip() for key in KEYS}, None


# What the config held when this module was imported, so an act's rows can be written as plain
# dicts. Every one of them is gated by the cloud_tier capability, which reads the same file - so an
# unconfigured run carries these empty strings into no wire call at all.
CONFIG = load_config()[0] or {}
HUB = CONFIG.get("hub", "")
PROJECT = CONFIG.get("project", "")
FOLDER = CONFIG.get("folder", "")


class DestinationError(SystemExit):
    """Stop cloud admission without treating a failed preparation as an omitted tier."""


RUN_BINDING = None
ARTIFACT_STAMP = None
_INVOCATION_STARTED = False
_BOOTSTRAP_RESUME = False
_MACHINE = machine_config.current()[0]
_MANIFEST_DIR = os.path.join(machine_config.record_root(_MACHINE) if _MACHINE else _HERE, "results")


def new_destination(config, config_hash, run_id=None):
    """Plan one unique top-level destination without making a cloud call."""
    token = uuid.uuid4().hex
    return {"version": 1, "run_id": run_id, "token": token,
            "operator": dict(config), "config_hash": config_hash,
            "folder": "SweepRun-" + token,
            "artifact_stamp": time.strftime("%Y%m%d-%H%M%S"),
            "state": "planned", "project_id": None, "folder_id": None}


def validate_destination(record, config, config_hash, run_id):
    """Refuse an unbound, changed or uncertain run destination."""
    if (not isinstance(record, dict) or record.get("version") != 1
            or record.get("operator") != config or record.get("config_hash") != config_hash
            or record.get("run_id") != run_id
            or not re.fullmatch(r"[0-9a-f]{32}", str(record.get("token", "")))
            or record.get("folder") != "SweepRun-" + record["token"]
            or not re.fullmatch(r"[0-9]{8}-[0-9]{6}", str(record.get("artifact_stamp", "")))
            or record.get("state") not in {"planned", "ready"}):
        raise DestinationError("cloud destination is missing, changed or uncertain; start a new run")
    if record["state"] == "ready" and any(
            not isinstance(record.get(key), str) or not record[key]
            for key in ("project_id", "folder_id")):
        raise DestinationError("cloud destination has no exact project/folder identity")
    if record["state"] == "planned" and any(record.get(key) is not None
                                             for key in ("project_id", "folder_id")):
        raise DestinationError("cloud destination has an incomplete creation record")


def destination_snapshot():
    """Return the cloud binding retained with an owned-family checkpoint."""
    return copy.deepcopy(RUN_BINDING)


def _manifest_path(record):
    return os.path.join(_MANIFEST_DIR, "cloud-destination-" + record["token"] + ".json")


def _save_destination(record):
    """Persist the attempt before a create and the verified identity after admission."""
    os.makedirs(_MANIFEST_DIR, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="cloud-", suffix=".json", dir=_MANIFEST_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, _manifest_path(record))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def bootstrap(argv):
    """Bind CLI cloud paths before the act module constructs arguments and checks."""
    global RUN_BINDING, ARTIFACT_STAMP, CONFIG, HUB, PROJECT, FOLDER, _BOOTSTRAP_RESUME
    if "verify_acts_cloud" in sys.modules:
        raise DestinationError("cloud rows already exist; start the sweep in a new process")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--check", action="store_true")
    options, _ = parser.parse_known_args(argv)
    if options.check or "--help" in argv or "-h" in argv:
        return
    if options.run is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", options.run):
        raise DestinationError("--run needs a simple run ID without path separators")
    config, problem = load_config()
    if config is None:
        return
    with open(CONFIG_PATH, "rb") as stream:
        config_hash = hashlib.sha256(stream.read()).hexdigest()
    if options.resume:
        if not options.run:
            raise DestinationError("--resume needs --run <id>")
        path = os.path.join(_MANIFEST_DIR, "run-" + options.run + ".json")
        try:
            with open(path, encoding="utf-8") as stream:
                state = json.load(stream)
            record = state.get("cloud_destination")
            validate_destination(record, config, config_hash, options.run)
            if os.path.isfile(_manifest_path(record)):
                with open(_manifest_path(record), encoding="utf-8") as stream:
                    retained = json.load(stream)
                validate_destination(retained, config, config_hash, options.run)
                immutable = ("version", "run_id", "token", "operator", "config_hash", "folder", "artifact_stamp")
                if any(retained[k] != record[k] for k in immutable):
                    raise DestinationError("cloud destination attempt disagrees with the checkpoint")
                if record["state"] == "ready" and retained != record:
                    raise DestinationError("cloud destination identity disagrees with the checkpoint")
                record = retained
            elif record["state"] != "planned":
                raise DestinationError("cloud destination has no retained admission record")
        except (OSError, ValueError, AttributeError) as exc:
            raise DestinationError("cloud destination checkpoint cannot be read: " + str(exc)) from exc
    else:
        record = new_destination(config, config_hash, options.run)
    RUN_BINDING = copy.deepcopy(record)
    _BOOTSTRAP_RESUME = options.resume
    ARTIFACT_STAMP = record["artifact_stamp"]
    CONFIG = dict(config, folder=record["folder"])
    HUB, PROJECT, FOLDER = (CONFIG[key] for key in KEYS)


def read_destination_project(wire, config):
    """Read the exact configured hub/project identity without creating a destination."""
    failed, hub = wire("data_get", {})
    projects = hub.get("projects") if isinstance(hub, dict) else None
    matching = [p for p in projects if isinstance(p, dict) and p.get("name") == config["project"]] if isinstance(projects, list) else []
    if (failed or not isinstance(hub, dict) or hub.get("active_hub") != config["hub"]
            or hub.get("truncated") is True or hub.get("time_truncated") is True or not isinstance(projects, list)
            or type(hub.get("project_count")) is not int or hub["project_count"] != len(projects)
            or len(matching) != 1
            or not isinstance(matching[0].get("id"), str) or not matching[0]["id"]):
        raise DestinationError("cloud destination hub/project is unreadable or ambiguous; nothing created")
    project_id = matching[0]["id"]
    return project_id


def admit_destination(wire, record, save):
    """Create once, independently read an empty top-level folder, or recheck its retained identity."""
    config = record["operator"]
    validate_destination(record, config, record["config_hash"], record["run_id"])
    project_id = read_destination_project(wire, config)
    if record["state"] == "ready" and record["project_id"] != project_id:
        raise DestinationError("cloud destination project identity changed; nothing created")
    creating = record["state"] == "planned"
    if creating:
        record["state"] = "creating"
        save(copy.deepcopy(record))
        failed, created = wire("data_create_folder", {
            "folder_name": record["folder"], "project_id": project_id, "parent_folder": ""})
        record["creation_reply"] = copy.deepcopy(created)
        record["creation_error"] = failed
        save(copy.deepcopy(record))
        if (failed or not isinstance(created, dict) or created.get("created") is not True
                or created.get("name") != record["folder"] or created.get("path") != record["folder"]
                or created.get("project") != config["project"]
                or created.get("auto_created_parents") != []
                or not isinstance(created.get("id"), str) or not created["id"]):
            raise DestinationError("cloud destination creation failed or is uncertain; no retry or deletion")
        record["folder_id"] = created["id"]
        record["project_id"] = project_id
        save(copy.deepcopy(record))
    failed, summary = wire("data_get", {
        "project_id": project_id, "folder": record["folder"], "include": ["summary"]})
    project = summary.get("project") if isinstance(summary, dict) else {}
    folder = summary.get("folder") if isinstance(summary, dict) else {}
    if (failed or not isinstance(summary, dict) or summary.get("exists") is not True
            or not isinstance(project, dict) or project.get("id") != project_id
            or project.get("name") != config["project"]
            or not isinstance(folder, dict) or folder.get("id") != record["folder_id"]
            or folder.get("name") != record["folder"] or folder.get("path") != record["folder"]
            or folder.get("is_root") is not False or summary.get("unavailable_fields") != []
            or any(type(summary.get(key)) is not int or summary[key] < 0
                   for key in ("immediate_file_count", "immediate_child_folder_count"))
            or (creating and (summary["immediate_file_count"] != 0
                              or summary["immediate_child_folder_count"] != 0))):
        raise DestinationError("cloud destination identity/emptiness did not read; no retry or deletion")
    record["state"] = "ready"
    save(copy.deepcopy(record))
    return copy.deepcopy(record)


def ensure_run_destination(wire):
    """Admit the paths already captured by the CLI's cloud rows."""
    if RUN_BINDING is None:
        raise DestinationError("cloud destination is unbound; launch tool_verify.py in a new process")
    config, problem = load_config()
    if problem:
        raise DestinationError("cloud destination operator config changed: " + problem)
    with open(CONFIG_PATH, "rb") as stream:
        config_hash = hashlib.sha256(stream.read()).hexdigest()
    validate_destination(RUN_BINDING, config, config_hash, RUN_BINDING["run_id"])
    admit_destination(wire, RUN_BINDING, _save_destination)
    return True



def start_invocation(run_id, resume):
    """Refuse cloud runs whose imported rows are not bound to this invocation."""
    global _INVOCATION_STARTED
    config, problem = load_config()
    if config is None:
        if RUN_BINDING is not None:
            raise DestinationError("cloud destination operator config no longer reads: " + str(problem))
        return False
    if (RUN_BINDING is None or _INVOCATION_STARTED
            or RUN_BINDING["run_id"] != run_id or _BOOTSTRAP_RESUME != resume):
        raise DestinationError("cloud rows are not bound to this run; launch tool_verify.py in a new process")
    with open(CONFIG_PATH, "rb") as stream:
        config_hash = hashlib.sha256(stream.read()).hexdigest()
    validate_destination(RUN_BINDING, config, config_hash, run_id)
    _INVOCATION_STARTED = True
    return True
