# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The post-run beat that switches three tool families off in the add-in's Settings file, reads
their absence off tools/list and sys_capability_map, and puts the file back.

`family_switch_smoke` runs just before the reload beat and hands it the identity it ends on. It is
the one place the sweep writes the Settings file: read the function top to bottom before a change."""

import importlib.util
import json
import os
import platform
import tempfile
import time

from verify_core import ENDPOINT, NOTE_MAX, REPO_ROOT, facade

# The families the beat switches off: each has a family_enabled_<family> row in the MCP group.
SWITCHED = ("pmi", "render", "sheet")
_ROW_TOOL = "sys_capability_map"
_SETTINGS_NAME = "FusionEssentialsSettings.json"
# Beside the Settings file from before the first write until the restore has read back. A run
# killed in between leaves it there, holding the bytes the Settings file had.
BACKUP_SUFFIX = ".family-switch-backup"
_FINGERPRINTS = ("implementation_fingerprint", "schema_fingerprint")
_IDENTITY = _FINGERPRINTS + ("load_id", "session_id")
_PROBE_GAP_S = 0.25
_UP_POLLS = 60
_PUT_BACK_TRIES = 5
_SETTLE_READS = 10
_SETTLE_GAP_S = 1.0


class _Unsettled(Exception):
    """A reload whose reply or new identity did not arrive: the add-in's state is not known."""


def settings_file(home=None, system=None):
    """(Settings file, MCP group id) of the add-in loaded from this checkout, by the directory
    rule of shared_state.get_settings_directory."""
    spec = importlib.util.spec_from_file_location(
        "fusion_essentials_config", os.path.join(REPO_ROOT, "config.py"))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    folder = f"{config.COMPANY_NAME}_{config.ADDIN_NAME}"
    home = home or os.path.expanduser("~")
    system = system or platform.system()
    if system == "Windows":
        directory = os.path.join(home, "AppData", "Roaming", folder)
    elif system == "Darwin":
        directory = os.path.join(home, "Library", "Application Support", folder)
    else:
        directory = os.path.join(home, "." + folder)
    return os.path.join(directory, _SETTINGS_NAME), folder + "_MCP"


def _family(name):
    """A tool's family, as the add-in's registry.family_of reads it."""
    return (name or "").split("_", 1)[0]


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _replace(path, data):
    """Put `data` at `path` through a synced temporary file beside it; whether it reads back."""
    fd, temp = tempfile.mkstemp(prefix=".FusionEssentials-", suffix=".tmp",
                                dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    return _read(path) == data


def _put_back(path, original):
    """Write the original bytes back; None once they read back, else the last failure as text."""
    problem = "no attempt was made"
    for attempt in range(_PUT_BACK_TRIES):
        if attempt:
            time.sleep(_PROBE_GAP_S)
        try:
            if _replace(path, original):
                return None
            problem = "the bytes written did not read back"
        except OSError as exc:
            problem = f"{type(exc).__name__}: {exc}"
    return problem


def _same_content(path, original):
    """Whether `path` holds the original bytes, or JSON equal to them (the add-in re-serializes
    the file on every load)."""
    try:
        now = _read(path)
        return now == original or json.loads(now) == json.loads(original)
    except (OSError, ValueError):
        return False


def _switched_off(original, group_id, start):
    """(the Settings text with the three rows' default false, None), or (None, why this file is
    refused). Nothing is written here."""
    try:
        data = json.loads(original)
    except ValueError as exc:
        return None, f"the Settings file is not JSON ({exc})"
    group = data.get(group_id) if isinstance(data, dict) else None
    settings = group.get("settings") if isinstance(group, dict) else None
    if not isinstance(settings, dict):
        return None, f"the Settings file has no '{group_id}' group with settings"
    port, _why = ENDPOINT.configured_port(settings.get(ENDPOINT.PORT_SETTING))
    from verify_core import PORT
    if port != PORT:
        return None, (f"the Settings file's {ENDPOINT.PORT_SETTING} reads {port!r}, not the "
                      f"{PORT} this run is connected on")
    for family in SWITCHED:
        row = settings.get("family_enabled_" + family)
        if not isinstance(row, dict) or row.get("default") is not True:
            shown = row.get("default") if isinstance(row, dict) else row
            return None, (f"the Settings row family_enabled_{family} reads {shown!r}; the beat "
                          "needs it present and true")
    # The add-in reads a falsy "default" as switched off. A row that reads off while the starting
    # tool list holds that family's tools is not the file the serving add-in loaded.
    for key, row in sorted(settings.items()):
        family = key[len("family_enabled_"):] if key.startswith("family_enabled_") else None
        if family and isinstance(row, dict) and not row.get("default", True):
            listed = sum(1 for name in start if _family(name) == family)
            if listed:
                return None, (f"the Settings row {key} reads off while the starting tool list "
                              f"has {listed} {family} tool(s)")
    for family in SWITCHED:
        settings["family_enabled_" + family]["default"] = False
    return json.dumps(data, indent=4).encode("ascii"), None


def _map_census(failed, payload):
    """(family names, tool_count) off a sys_capability_map reply, or None when it lacks them."""
    families = payload.get("families") if isinstance(payload, dict) and not failed else None
    count = payload.get("tool_count") if isinstance(payload, dict) else None
    if (not isinstance(families, list) or type(count) is not int
            or any(not isinstance(row, dict) or not isinstance(row.get("family"), str)
                   for row in families)):
        return None
    return {row["family"] for row in families}, count


def _reload(previous, up_polls):
    """Reload the add-in and return (health, identity) once /health attests a load and a session
    both new against `previous`; raises _Unsettled when the reply or that identity is missing."""
    call, health_gate = facade("call"), facade("health_gate")
    attestation_identity = facade("attestation_identity")
    try:
        is_error, payload = call("sys_reload_addin", {})
    except Exception as exc:
        raise _Unsettled(f"sys_reload_addin did not answer ({str(exc)[:NOTE_MAX]})") from exc
    if is_error or "Reload scheduled" not in str(payload):
        raise _Unsettled(f"sys_reload_addin scheduled no reload ({str(payload)[:NOTE_MAX]})")
    for attempt in range(up_polls):
        if attempt:
            time.sleep(_PROBE_GAP_S)
        try:
            health = health_gate()
            identity = attestation_identity(health)
        except (OSError, ValueError, SystemExit):
            continue
        if identity and all(identity.get(key) != previous.get(key)
                            for key in ("load_id", "session_id")):
            return health, identity
    raise _Unsettled(f"no new load and session identity within {up_polls} /health reads")


def _difference(expected, actual):
    """The names missing from and added to `actual`, as one clause."""
    missing = sorted(set(expected) - set(actual))
    added = sorted(set(actual) - set(expected))
    return f"missing {missing[:5]} ({len(missing)}), added {added[:5]} ({len(added)})"


def _absence_problem(health, kept, gone, map_before):
    """None when the switched-off add-in lists exactly `kept` and its map lost exactly SWITCHED
    and len(gone) tools, else what differed."""
    try:
        census = facade("registered_tools")(health)
        failed, mapped = facade("call")("sys_capability_map", {})
    except (Exception, SystemExit) as exc:
        return f"the switched-off tool list or map was not read ({str(exc)[:NOTE_MAX]})"
    left = [name for name in census if _family(name) in SWITCHED]
    if left:
        return f"{len(left)} tool(s) of a switched-off family are still listed: {left[:5]}"
    if census != kept:
        return ("the switched-off tool list differs from the starting one beyond the three "
                "families: " + _difference(kept, census))
    after = _map_census(failed, mapped)
    if after is None:
        return "sys_capability_map did not return its families and tool_count"
    if map_before[0] - after[0] != set(SWITCHED) or not after[0] <= map_before[0]:
        return ("sys_capability_map's families did not lose exactly the three: "
                + _difference(map_before[0] - set(SWITCHED), after[0]))
    if after[1] != map_before[1] - len(gone):
        return (f"sys_capability_map tool_count reads {after[1]}; {map_before[1]} before less "
                f"the {len(gone)} switched-off tools is {map_before[1] - len(gone)}")
    return None


def _restored_problem(health, identity, start, pinned):
    """None when the restored add-in lists the starting tools under the pinned fingerprints."""
    try:
        census = facade("registered_tools")(health)
    except (Exception, SystemExit) as exc:
        return f"the restored tool list was not read ({str(exc)[:NOTE_MAX]})"
    if census != start:
        return "the restored tool list differs from the starting one: " + _difference(start, census)
    if any(identity.get(key) != pinned.get(key) for key in _FINGERPRINTS):
        return "the restored add-in does not attest the pinned implementation and schema fingerprints"
    return None


def family_switch_smoke(rows, expected_attestation, before_tool_census, valued=None,
                        settings=None, up_polls=_UP_POLLS, settle_reads=_SETTLE_READS):
    """Switch SWITCHED off in the Settings file, read their absence, restore the file and the
    tools; the identity the restored add-in attests, or None with a row saying what stopped it."""
    from verify_core import require_machine
    import machine_config
    config = require_machine()
    machine_config.require_call(config, "sys_set_preferences", {})
    machine_config.require_call(config, "sys_reload_addin", {})
    start = sorted(before_tool_census or [])
    gone = [name for name in start if _family(name) in SWITCHED]
    kept = [name for name in start if name not in gone]
    listed = "/".join(SWITCHED)

    def stop(status, why):
        print("  family switch beat: " + why)
        rows.append((_ROW_TOOL, status, why))

    # GATES, in the order of what they touch: nothing, the file (read only), the serving add-in
    # (reads only). Each refusal leaves the Settings file as it was found.
    absent = sorted(set(SWITCHED) - {_family(name) for name in gone})
    if absent:
        return stop("blocked", f"the starting tool list has no {', '.join(absent)} tool; the "
                               "Settings file was not opened")
    path, group_id = settings or settings_file()
    backup = path + BACKUP_SUFFIX
    try:
        original = _read(path)
        # A backup an earlier beat left is dropped only when the Settings file reads the same.
        if os.path.exists(backup):
            if not _same_content(path, _read(backup)):
                return stop("blocked", f"{backup} differs from {path}: an earlier beat did not "
                                       "restore the Settings file. Put the backup's rows back by "
                                       "hand, then delete it; nothing was written")
            os.remove(backup)
    except OSError as exc:
        return stop("blocked", f"reading {path} or clearing its leftover backup failed ({exc}); "
                               "the Settings file was not written")
    switched_off, problem = _switched_off(original, group_id, start)
    if problem:
        return stop("blocked", f"{problem} ({path}); nothing was written")
    try:
        health = facade("health_gate")()
        identity = facade("attestation_identity")(health)
        map_before = _map_census(*facade("call")("sys_capability_map", {}))
    except (Exception, SystemExit) as exc:
        return stop("blocked", "the serving add-in was not read before the switch "
                               f"({str(exc)[:NOTE_MAX]}); nothing was written")
    if not isinstance(identity, dict) or any(
            identity.get(key) != expected_attestation.get(key) for key in _IDENTITY):
        return stop("blocked", "the serving identity differs from the run's loaded identity; "
                               "nothing was written")
    if map_before is None or not set(SWITCHED) <= map_before[0]:
        return stop("blocked", f"sys_capability_map does not list {listed} before the switch; "
                               "nothing was written")

    # THE SWITCH. Once the Settings file is touched, its original bytes go back in the finally
    # whatever happens; the backup stays until those bytes have read back.
    addin = "serving its starting tools"
    failure = unsettled = identity_off = not_restored = None
    touched = False
    try:
        with open(backup, "xb") as fh:
            fh.write(original)
        if _read(backup) != original:
            raise OSError("the backup did not read back")
        touched = True
        if not _replace(path, switched_off):
            raise OSError("the switched-off Settings text did not read back")
        health_off, identity_off = _reload(expected_attestation, up_polls)
        addin = f"serving without {listed} tools"
        failure = _absence_problem(health_off, kept, gone, map_before)
    except _Unsettled as exc:
        unsettled = str(exc)
    except OSError as exc:
        failure = f"the Settings file was not switched ({type(exc).__name__}: {exc})"
    finally:
        if touched:
            not_restored = _put_back(path, original)

    def file_state(problem, rewrites=0):
        """(whether the Settings file reads as the original now, the sentence saying so); a
        restored file drops its backup."""
        if _same_content(path, original):
            if os.path.exists(backup):
                os.remove(backup)
            again = f" after {rewrites} rewrite(s) over other content" if rewrites else ""
            return True, "the Settings file holds its original content, read back" + again
        kept_in = (f"its original bytes are in {backup}" if os.path.exists(backup)
                   else "no backup of it exists")
        return False, (f"the Settings file {path} is NOT restored "
                       f"({problem or 'it reads other content'}); {kept_in}")

    def stop_unsettled(why, problem):
        # No wire call follows an unsettled reload. A load still in flight can write its own copy
        # of the file over the restore, so the file alone is re-read and put back for a while.
        rewrites = 0
        for _ in range(settle_reads):
            time.sleep(_SETTLE_GAP_S)
            if not _same_content(path, original):
                rewrites += 1
                problem = _put_back(path, original)
        _restored, file_text = file_state(problem, rewrites)
        return stop("FAIL", f"{why}; {file_text}; the add-in was last read {addin} and is not "
                            "read again: it may be stopped, loading, or serving either tool list")

    if unsettled:
        return stop_unsettled(unsettled, not_restored)
    if identity_off is None:
        return stop("FAIL", f"{failure}; {file_state(not_restored)[1]}; the add-in was not reloaded")

    # THE RESTORE. The file already holds the original bytes; this reload makes the add-in read
    # them, and it runs whether or not the absence checks passed.
    try:
        health_on, identity_on = _reload(identity_off, up_polls)
    except _Unsettled as exc:
        return stop_unsettled(f"{failure + '; ' if failure else ''}the restoring reload: {exc}",
                              not_restored)
    addin = "on its second reload"
    failure = failure or _restored_problem(health_on, identity_on, start, expected_attestation)
    if not _same_content(path, original):
        not_restored = _put_back(path, original)
        failure = failure or "the Settings file read other content after the restoring reload"
    restored, file_text = file_state(not_restored)
    if failure or not restored:
        return stop("FAIL", f"{failure or 'the Settings file did not restore'}; {file_text}; "
                            f"the add-in was last read {addin}")
    rows.append((_ROW_TOOL, "pass",
                 f"Settings rows family_enabled_{{{','.join(SWITCHED)}}} written false and the "
                 f"add-in reloaded: tools/list lost exactly their {len(gone)} tools and kept the "
                 f"other {len(kept)}; sys_capability_map lost exactly those families and its "
                 f"tool_count read {map_before[1] - len(gone)} against {map_before[1]} before; "
                 f"{file_text}, and the next reload listed all {len(start)} starting tools "
                 "under the pinned implementation and schema fingerprints"))
    if valued is not None:
        valued.add(_ROW_TOOL)
    return identity_on
