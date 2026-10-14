# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Compare read-only sweep admission observations with explicit machine configuration."""

import machine_config
import re

SCRIPT_TOOL = "sys_execute_script"
SCRIPT_SETTING = "Allow AI scripts (unsafe)"
MEASURED_PREFERENCES = (
    (("general", "defaultModelingOrientation"), "ZUpModelingOrientation",
     "its geometry rows place and measure with Z up"),
    (("units_defaults", "Design", "defaultUnitSystem"), "MillimeterGramUnitSystem",
     "its new documents are measured in millimetres"),
    (("general", "userLanguage"), "EnglishLanguage",
     "library and object names are matched in English"))
PREFERENCE_GROUPS = sorted({path[0] for path, _, _ in MEASURED_PREFERENCES})
HEAD = "The sweep did not start: {0} to settle first. No document, preference or library was touched."


def permission_notes(config):
    """Disclose retained library effects conditionally before a permitted run writes."""
    if not config["allow"]["library_writes"]:
        return []
    return [f"allow.library_writes is on. If the Local tool-library seed story runs, it retains "
            f"'{machine_config.RETAINED_LIBRARY_NAME}' at its selected URL; it has no library-delete step. "
            "Inspect the selected exact URL and stored content; a name alone does not establish its identity."]


def _dig(value, path):
    """Return a nested published field or None when any object is absent."""
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def required_tools(config, rows, conditions, support_routes=()):
    """Return only admitted row tools; an off choice never invents an absent measured fact."""
    from verify_core import _leaves_no_row
    requested = machine_config.asked(config)
    quarantined = machine_config.record_scope(config)["quarantined"]
    needed = {"doc_get", "sys_get_preferences"}
    for step in rows:
        tool, _args, expect, _save = step
        gates = conditions(expect)
        excluded = any(name in quarantined or (polarity == "needs" and requested.get(name) is False)
                       for name, polarity in gates)
        if not excluded and not _leaves_no_row(step):
            needed.add(tool)
    for _route, tools, expect in support_routes:
        gates = conditions(expect)
        excluded = any(name in quarantined or (polarity == "needs" and requested.get(name) is False)
                       for name, polarity in gates)
        if not excluded:
            needed.update(tools)
    return needed


def owned_handles(state):
    """Return only opaque owned checkpoint handles, never names or blanket resume exemptions."""
    if state is None:
        return ()
    groups = [state.get(key, []) for key in ("owned_documents", "lifecycle_owned_documents")]
    if (any(not isinstance(group, list) for group in groups)
            or any(not isinstance(handle, str) or not re.fullmatch(r"session:\S+", handle)
                   for group in groups for handle in group)):
        raise ValueError("checkpoint owned documents must be exact session handles")
    return tuple(dict.fromkeys(handle for group in groups for handle in group))


def problems(config, health, tools, needed, documents, preferences,
             accept_open_work=False, owned_handles=(), home_observer_required=False):
    """Return observed admission failures, exempting only exact checkpoint-owned documents."""
    found = []
    if home_observer_required and not config["tiers"]["native_script"]:
        found.append("tiers.native_script=false: the family sweep cannot certify its strict home "
                     "content-count/modified-flag fence without the read-only native observer. "
                     "Explicitly set tiers.native_script=true before family writes; "
                     "public missing counts are not zero and no writable fallback is used.")
    bound = health.get("bound") if isinstance(health, dict) else None
    if (not isinstance(bound, dict) or type(bound.get("port")) is not int
            or bound["port"] != config["port"] or bound.get("host") != "127.0.0.1"
            or bound.get("mcp_url") != f"http://127.0.0.1:{config['port']}/mcp"):
        found.append(f"The add-in reports bound={bound!r}; configuration port={config['port']}. "
                     "Match port to the add-in's mcp_port on the loopback endpoint.")
    names = set(tools) if isinstance(tools, (list, tuple, set, frozenset)) else set()
    if config["tiers"]["native_script"] and SCRIPT_TOOL not in names:
        found.append(f"tiers.native_script=true but {SCRIPT_TOOL} is not registered. Check "
                     f"'{SCRIPT_SETTING}' in add-in settings, or explicitly exclude the tier.")
    missing = sorted(set(needed) - names - {SCRIPT_TOOL})
    if missing:
        found.append("Required scoped tools are not registered: " + ", ".join(missing)
                     + ". Check the server version and enabled tool families.")
    rows = documents.get("open_documents") if isinstance(documents, dict) else None
    valid = (isinstance(rows, list) and documents.get("truncated") is False
             and type(documents.get("open_count")) is int and documents["open_count"] == len(rows)
             and all(isinstance(row, dict) and isinstance(row.get("document_handle"), str)
                     and re.fullmatch(r"session:\S+", row["document_handle"])
                     and all(type(row[key]) is bool for key in (
                         "is_active", "is_visible", "is_saved", "is_modified") if key in row)
                     for row in rows))
    if valid:
        valid = len({row["document_handle"] for row in rows}) == len(rows)
    if not valid:
        found.append("The open-document census is incomplete or ambiguous; unsaved work cannot be ruled out.")
    elif not accept_open_work:
        # doc_get compacts is_modified=False away; an unread field remains explicit null.
        unsaved = [f"{row.get('name')!r} ({row['document_handle']})" for row in rows
                   if row.get("is_modified") is True and row["document_handle"] not in owned_handles]
        if unsaved:
            found.append("Unaccepted open work: " + ", ".join(unsaved)
                         + ". Save/close it or pass --accept-open-work; resume only exempts owned handles.")
    groups = preferences.get("preferences") if isinstance(preferences, dict) else None
    for path, want, why in MEASURED_PREFERENCES:
        got = _dig(groups, path + ("enum",))
        if got != want:
            found.append(f"Preference {'.'.join(path)} reads {got!r}; the sweep is measured only with "
                         f"{want} ({why}). It never changes this prerequisite.")
    return found


def refusal(config, harness, needed, accept_open_work=False, owned_handles=(), home_observer_required=False):
    """Return a read-only admission refusal, validating configuration before any transport."""
    invalid = machine_config.problems(config)
    if invalid:
        raise SystemExit(machine_config.refusal("supplied configuration", "caller", invalid))
    health = harness.health_gate()
    tools = harness.registered_tools(health)
    documents = harness.call("doc_get", {"max_results": 1000})
    preferences = harness.call("sys_get_preferences", {"include": PREFERENCE_GROUPS})
    found = problems(config, health, tools, needed, None if documents[0] else documents[1],
                     None if preferences[0] else preferences[1], accept_open_work, owned_handles,
                     home_observer_required)
    if not found:
        return None
    count = "one thing" if len(found) == 1 else f"{len(found)} things"
    return "\n".join([HEAD.format(count)] + [f"  {i}. {line}" for i, line in enumerate(found, 1)])
