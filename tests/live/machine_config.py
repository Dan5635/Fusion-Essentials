# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Validate explicit sweep configuration and keep asked scope separate from observed capabilities."""

import argparse
import hashlib
import importlib.util
import json

import os
import platform
import re

RETAINED_LIBRARY_NAME = "Fusion-Essentials sweep test data"
_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_NAME = "sweep_config.local.json"
EXAMPLE_NAME = "sweep_config.example.json"
REFERENCE_MACHINE = "reference"
ENV = "FUSION_ESSENTIALS_SWEEP_CONFIG"
SHAPE = {"machine": str, "port": int,
         "tiers": {"native_script": bool, "machining_extension": bool, "cloud": bool},
         "cloud": {"hub": str, "project": str, "folder": str},
         "allow": {"library_writes": bool, "preference_writes": bool, "addin_reload": bool}}
SWITCHES = {"native_script": ("tiers", "native_script"),
            "machining_extension": ("tiers", "machining_extension"),
            "cloud_tier": ("tiers", "cloud"),
            "library_writes": ("allow", "library_writes"),
            "preference_writes": ("allow", "preference_writes"),
            "addin_reload": ("allow", "addin_reload")}
PERMISSIONS = frozenset(name for name, path in SWITCHES.items() if path[0] == "allow")
_LIBRARY_TOOLS = frozenset({"cam_create_machine", "cam_delete_machine", "cam_save_template",
                           "cam_delete_template"})
_CLOUD_DOCUMENT_TOOLS = frozenset({"doc_save", "doc_save_as", "doc_save_milestone", "doc_copy",
                                   "doc_restore_version", "doc_open", "doc_insert_occurrence",
                                   "doc_insert_derive"})
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
_RESERVED = {"con", "prn", "aux", "nul", "clock$"} | {
    stem + str(i) for stem in ("com", "lpt") for i in range(1, 10)}
_RANK = {"run": 0, "not-applicable": 1, "held": 2, "not-in-scope": 3, "stop": 4}


def _port_limits():
    """Return the add-in endpoint's admitted port bounds without importing its runtime."""
    path = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "commands", "mcpServer", "endpoint.py")
    spec = importlib.util.spec_from_file_location("fusion_essentials_endpoint_limits", path)
    endpoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(endpoint)
    return endpoint.PORT_MIN, endpoint.PORT_MAX


def config_path(environ=None, path=None):
    """Return the explicit override, environment override, or default configuration path."""
    environ = os.environ if environ is None else environ
    if path is not None:
        return os.path.abspath(os.fspath(path)), "--config"
    if environ.get(ENV):
        return os.path.abspath(environ[ENV]), ENV
    return os.path.join(_HERE, CONFIG_NAME), "the default place"


def configure_cli(argv, environ=None):
    """Select one explicit path before any cloud scope or act module is imported."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False, prog="tool_verify.py")
    parser.add_argument("--config", action="append", metavar="PATH")
    options, _ = parser.parse_known_args(argv)
    if options.config is None:
        return None
    if len(options.config) != 1 or not options.config[0].strip():
        parser.error("--config requires one nonblank PATH and may be supplied only once")
    selected, _ = config_path(path=options.config[0])
    require(environ=environ, path=selected)
    (os.environ if environ is None else environ)[ENV] = selected
    return selected


def problems(raw, port_limits=None):
    """Return all missing, unknown, mistyped or unsafe configuration values."""
    if not isinstance(raw, dict):
        return [f"the file holds a {type(raw).__name__}, not an object"]
    found = []

    def walk(shape, value, prefix):
        found.extend(f"unknown key: {prefix}{key}" for key in value if key not in shape)
        for key, kind in shape.items():
            name = prefix + key
            if key not in value:
                found.append("missing: " + name)
            elif isinstance(kind, dict):
                if isinstance(value[key], dict):
                    walk(kind, value[key], name + ".")
                else:
                    found.append(name + " must be an object")
            elif kind is bool and type(value[key]) is not bool:
                found.append(name + " must be true or false")
            elif kind is str and not isinstance(value[key], str):
                found.append(name + " must be text")

    walk(SHAPE, raw, "")
    low, high = port_limits or _port_limits()
    if "port" in raw and not (type(raw["port"]) is int and low <= raw["port"] <= high):
        found.append(f"port must be a whole number from {low} to {high}")
    label = raw.get("machine")
    if isinstance(label, str) and (not _LABEL.fullmatch(label) or label.endswith(".")
                                  or label.split(".", 1)[0].lower() in _RESERVED):
        found.append(f"machine {label!r} must be a portable 1-to-40-character folder label: "
                     "letters, digits, dots, dashes or underscores; no trailing dot or reserved name")
    tiers, cloud = raw.get("tiers"), raw.get("cloud")
    if isinstance(tiers, dict) and tiers.get("cloud") is True and isinstance(cloud, dict):
        found.extend(f"tiers.cloud is true but cloud.{key} is empty" for key in SHAPE["cloud"]
                     if isinstance(cloud.get(key), str) and not cloud[key].strip())
    return found


def _unique_object(pairs):
    """Decode one JSON object without allowing a repeated permission or scope key."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key: " + key)
        result[key] = value
    return result


def load(path, port_limits=None):
    """Return a usable configuration or every validation/read problem, without transport."""
    try:
        with open(path, encoding="utf-8-sig") as stream:
            raw = json.load(stream, object_pairs_hook=_unique_object)
    except FileNotFoundError:
        return None, ["not found"]
    except (OSError, ValueError) as exc:
        return None, [f"it would not read as JSON ({exc})"]
    found = problems(raw, port_limits)
    return (None, found) if found else (raw, [])


def example_text():
    """Return the tracked example printed in first-run refusals."""
    with open(os.path.join(_HERE, EXAMPLE_NAME), encoding="utf-8") as stream:
        return stream.read().strip()


def refusal(path, source, found):
    """Return a complete, actionable configuration refusal before any server call."""
    missing = found == ["not found"]
    lines = ["The sweep is not set up for this machine, so nothing was called.",
             f"It looked for: {path}  ({'not found' if missing else 'found, with problems'}; from {source})"]
    lines.extend("  " + problem for problem in found if not missing)
    lines += [f"Copy tests/live/{EXAMPLE_NAME} to that name and fill it in. It holds:", example_text(),
              'What each key means is in tests/README.md, "Running the sweep on your machine".']
    return "\n".join(lines)


def current(environ=None, path=None):
    """Return configuration, problems, chosen path and path provenance."""
    chosen, source = config_path(environ, path)
    config, found = load(chosen)
    return config, found, chosen, source


def require(environ=None, path=None):
    """Return explicit usable configuration or stop before any caller can dispatch."""
    config, found, chosen, source = current(environ, path)
    if found:
        raise SystemExit(refusal(chosen, source, found))
    return config


def fingerprint(config):
    """Return the semantic configuration identity, including endpoint and every permission."""
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def asked(config):
    """Return all requested switches without inferring capability observations."""
    return {name: config[group][key] for name, (group, key) in SWITCHES.items()}


def record_scope(config):
    """Bind one recorded scope to its explicit machine, endpoint, destination and permissions."""
    checkout = os.path.normcase(os.path.realpath(os.path.dirname(os.path.dirname(_HERE))))
    return {"version": 2, "machine": config["machine"], "config_hash": fingerprint(config),
            "os": platform.system(), "checkout": checkout,
            "asked": asked(config), "quarantined": ["cloud_link_crash_review_authorization"]}


def record_root(config):
    """Return the explicit all-on reference root or a segregated community scope directory."""
    if config["machine"] == REFERENCE_MACHINE and all(value is True for value in asked(config).values()):
        return _HERE
    identity = hashlib.sha256(json.dumps(record_scope(config), sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=True).encode("ascii")).hexdigest()
    return os.path.join(_HERE, "records", config["machine"], identity)


def condition(capability, polarity, requested, measured, quarantined=()):
    """Resolve one condition while retaining its request, actual observation and polarity."""
    if polarity not in {"needs", "unless"} or (measured is not None and type(measured) is not bool):
        raise ValueError(f"invalid condition {capability!r}/{polarity!r}/{measured!r}")
    if requested is not None and type(requested) is not bool:
        raise ValueError("requested must be true, false or absent")
    if capability in quarantined:
        state, reason = "not-in-scope", "quarantined capability is outside admitted scope"
    elif capability in PERMISSIONS and polarity == "needs" and requested is True:
        state, reason = "run", None
    elif requested is True and capability not in PERMISSIONS and measured is not True:
        state, reason = "stop", "requested tier is unavailable or unreadable"
    elif polarity == "needs" and requested is False:
        state, reason = "not-in-scope", "configuration explicitly excludes this prerequisite"
    elif polarity == "unless" and measured is True:
        state, reason = "not-applicable", "conditional control requires measured absence"
    elif (polarity == "needs" and measured is True) or (polarity == "unless" and measured is False):
        state, reason = "run", None
    else:
        state, reason = "held", "required capability observation is absent or unreadable"
    return {"capability": capability, "polarity": polarity, "asked": requested,
            "measured": measured, "state": state, "reason": reason}


def omission(act, kind, tools, conditions):
    """Record every nonexecuted prerequisite without converting it into successful evidence."""
    result = conjunction(conditions)
    if result["state"] not in {"held", "not-in-scope", "not-applicable"}:
        raise ValueError("only omitted, non-stop work can have an omission record")
    winner = next(row for row in result["conditions"] if row["state"] == result["state"])
    return {"act": act, "kind": kind, "capability": winner["capability"],
            "reason": result["reason"], "tools": sorted(set(tools)), **result}


def validate_scope(scope):
    """Reject incomplete recorded requests without reading this machine's current configuration."""
    if (not isinstance(scope, dict) or set(scope) != {"version", "machine", "config_hash", "asked", "quarantined", "os", "checkout"}
            or type(scope["version"]) is not int or scope["version"] != 2
            or not isinstance(scope["machine"], str) or not _LABEL.fullmatch(scope["machine"])
            or scope["machine"].endswith(".") or scope["machine"].split(".", 1)[0].lower() in _RESERVED
            or not isinstance(scope["config_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", scope["config_hash"])
            or any(not isinstance(scope[key], str) or not scope[key] for key in ("os", "checkout"))
            or not isinstance(scope["asked"], dict) or set(scope["asked"]) != set(SWITCHES)
            or any(type(value) is not bool for value in scope["asked"].values())
            or scope["quarantined"] != ["cloud_link_crash_review_authorization"]):
        raise ValueError("recorded machine/scope provenance incomplete")
    return scope


def require_full_scope(scope):
    """Require every admitted choice from the record, not this reader's current configuration."""
    validate_scope(scope)
    off = sorted(name for name, value in scope["asked"].items() if value is False)
    if off:
        raise ValueError("record is not full admitted scope; excluded choices: " + ", ".join(off))


def validate_omission(row, scope):
    """Recompute each condition from its own polarity, recorded request and retained observation."""
    validate_scope(scope)
    if not isinstance(row, dict) or not isinstance(row.get("conditions"), list) or not row["conditions"]:
        raise ValueError("omission lacks all prerequisite conditions")
    expected = []
    identities = set()
    for item in row["conditions"]:
        if (not isinstance(item, dict) or not isinstance(item.get("capability"), str)
                or not item["capability"] or (item["capability"], item.get("polarity")) in identities):
            raise ValueError("omission has invalid or duplicate prerequisite")
        identities.add((item["capability"], item.get("polarity")))
        resolved = condition(item["capability"], item.get("polarity"),
                             scope["asked"].get(item["capability"]), item.get("measured"),
                             scope["quarantined"])
        if item != resolved:
            raise ValueError("omission condition disagrees with its scope/polarity/observation")
        expected.append(resolved)
    canonical = omission(row.get("act"), row.get("kind"), row.get("tools", []), expected)
    if row != canonical:
        raise ValueError("omission disagrees with conjunctive prerequisite decision")
    return row


def conjunction(conditions):
    """Retain every condition and select the highest-ranked outcome, without changing predicates."""
    rows = list(conditions)
    if any(not isinstance(row, dict) or row.get("state") not in _RANK for row in rows):
        raise ValueError("conditions must carry valid resolved outcomes")
    winner = max(rows, key=lambda row: _RANK[row["state"]], default=None)
    return {"state": winner["state"] if winner else "run",
            "reason": winner["reason"] if winner else None, "conditions": rows}


def call_requirements(tool, arguments, script_effects=None):
    """Return persistent/tier fences; unclassified scripts require every potentially affected permission."""
    needed = set()
    if tool.startswith(("data_", "drawing_")) or tool in _CLOUD_DOCUMENT_TOOLS:
        needed.add("cloud_tier")
    if tool == "doc_close" and arguments.get("save_changes", False) is not False:
        needed.add("cloud_tier")
    if tool == "doc_update_xref":
        action = arguments.get("action", "refresh")
        if not isinstance(action, str) or action.strip().lower() != "break_link":
            needed.add("cloud_tier")
    if tool in _LIBRARY_TOOLS:
        needed.add("library_writes")
    if tool == "cam_save_template":
        location = arguments.get("location", "cloud")
        if not isinstance(location, str) or location.strip().lower() not in {"local", "network", "external"}:
            needed.add("cloud_tier")
    scope, action = arguments.get("scope") or "document", arguments.get("action") or "list"
    scope = scope.strip().lower() if isinstance(scope, str) else "<invalid>"
    action = action.strip().lower() if isinstance(action, str) else "<invalid>"
    if tool == "cam_edit_tools" and scope != "document":
        if scope in {"cloud", "hub"} and action != "list_types":
            needed.add("cloud_tier")
        if action not in {"list", "list_types", "parameters", "where_used"}:
            needed.add("library_writes")
    if tool == "sys_set_preferences":
        needed.add("preference_writes")
    if tool == "sys_reload_addin":
        needed.add("addin_reload")
    if tool == "sys_execute_script":
        needed.add("native_script")
        if script_effects is None:
            needed.add("cloud_tier")
            needed.update(PERMISSIONS)
        else:
            if (not isinstance(script_effects, (list, tuple, set, frozenset))
                    or any(effect not in PERMISSIONS | {"cloud_tier"} for effect in script_effects)):
                raise ValueError("script effects must be classified persistent permissions or cloud_tier")
            needed.update(script_effects)
    return tuple(sorted(needed))


def effect_declaration(script, effects):
    """Bind an explicit source-audited effect declaration to the exact emitted script bytes."""
    if not isinstance(script, str) or effects is None:
        raise ValueError("script declaration needs literal script text and explicit effects")
    call_requirements("sys_execute_script", {}, effects)
    return {"sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(), "effects": tuple(sorted(set(effects)))}


def declared_effects(tool, arguments, declaration):
    """Refuse stale or malformed declarations before transport; absent declarations stay unknown."""
    if declaration is None:
        return None
    if (tool != "sys_execute_script" or not isinstance(declaration, dict)
            or set(declaration) != {"sha256", "effects"} or not isinstance(arguments.get("script"), str)):
        raise SystemExit("Invalid script-effect declaration; nothing dispatched")
    expected = effect_declaration(arguments["script"], declaration["effects"])
    if declaration != expected:
        raise SystemExit("Source-audited script bytes or effects changed before transport; nothing dispatched")
    return expected["effects"]


def require_call(config, tool, arguments, script_effects=None):
    """Refuse a direct dispatch before transport when any required choice is explicitly off."""
    requested = asked(config)
    blocked = [name for name in call_requirements(tool, arguments, script_effects) if requested[name] is not True]
    if blocked:
        switches = [".".join(SWITCHES[name]) for name in blocked]
        raise SystemExit(f"Sweep call {tool!r} refused before transport: excluded " + ", ".join(switches)
                         + ". Change the explicit configuration or omit this dependent work.")
