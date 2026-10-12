# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Grade a cold run from two records: the child's tool calls and the script's own reads.

A call row is {"tool", "arguments", "failed", "payload", "text"}; grade() takes a pack's checks,
the child's rows, the script's rows and the handles the run owns, and returns one verdict per
outcome with the evidence each check rests on. It reads fields and numbers, never wording."""

import json

PASS, FAIL, UNTESTED = "PASS", "FAIL", "UNTESTED"
_MISSING = object()


def call_row(tool, arguments, result, failed=None):
    """One call row from a raw MCP result ({"content": [...], "isError": bool})."""
    result = result if isinstance(result, dict) else {}
    text = next((block.get("text", "") for block in result.get("content") or []
                 if isinstance(block, dict) and block.get("type") == "text"), "")
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        payload = None
    if failed is None:
        failed = bool(result.get("isError"))
    return {"tool": tool, "arguments": dict(arguments or {}), "failed": bool(failed),
            "payload": payload if isinstance(payload, dict) else None, "text": text}


def lookup(payload, path):
    """The value at a dotted path; `name[key=value]` picks the first list row whose key matches."""
    node = payload
    for part in path.split("."):
        name, _, selector = part.partition("[")
        if not isinstance(node, dict) or name not in node:
            return _MISSING
        node = node[name]
        if selector:
            key, _, wanted = selector.rstrip("]").partition("=")
            rows = node if isinstance(node, list) else []
            node = next((row for row in rows
                         if isinstance(row, dict) and str(row.get(key)) == wanted), _MISSING)
            if node is _MISSING:
                return _MISSING
    return node


def _matches(row, spec):
    """True when a row is a call to spec's tool whose arguments hold every `where` pair."""
    if row["tool"] != spec["tool"]:
        return False
    wanted = spec.get("where") or spec.get("arguments") or {}
    return all(row["arguments"].get(key) == value for key, value in wanted.items())


def _shown(value):
    return "nothing" if value is _MISSING else json.dumps(value)


def _write_then_read(check, calls, reads, context):
    """Each matching write is followed, before the next one, by a read that shows its value."""
    every = [i for i, row in enumerate(calls) if _matches(row, check["write"]) and not row["failed"]]
    allowed = context.get(check.get("values_in"), None)
    # A write on something the run does not own is not counted, but it still ends the stretch in
    # which the write before it can be confirmed.
    writes = [i for i in every if allowed is None
              or calls[i]["arguments"].get(check["write"]["value"]) in allowed]
    if not writes:
        return FAIL, f"no successful {check['write']['tool']} call on the run's own in the transcript"
    values = []
    for n, at in enumerate(writes):
        stop = next((i for i in every if i > at), len(calls))
        wanted = calls[at]["arguments"].get(check["write"]["value"])
        read = next((row for row in calls[at + 1:stop]
                     if _matches(row, check["read"]) and not row["failed"]), None)
        if read is None:
            return FAIL, f"write {n + 1} ({_shown(wanted)}) has no separate {check['read']['tool']} after it"
        seen = lookup(read["payload"], check["read"]["path"])
        if seen != wanted:
            return FAIL, f"write {n + 1} asked for {_shown(wanted)}; the read after it shows {_shown(seen)}"
        values.append(wanted)
    if "expect" in check and values != check["expect"]:
        return FAIL, f"the written values were {json.dumps(values)}, not {json.dumps(check['expect'])}"
    if len(set(map(json.dumps, values))) < check.get("distinct", 0):
        return FAIL, f"{len(values)} write(s) on fewer than {check['distinct']} distinct values"
    return PASS, f"{len(values)} write(s), each confirmed by a separate read: {json.dumps(values)}"


def _failed_call(check, calls, reads, context):
    """Exactly one matching call is recorded as failed, and its content carries the named fields."""
    matching = [row for row in calls if _matches(row, check)]
    if not matching:
        return FAIL, f"no {check['tool']} call in the transcript"
    failed = [row for row in matching if row["failed"]]
    if len(failed) != 1:
        return FAIL, f"{len(failed)} of {len(matching)} {check['tool']} call(s) recorded as failed; wanted 1"
    payload = failed[0]["payload"] or {}
    first = next(iter(payload), None)
    if check.get("first_key") and first not in check["first_key"]:
        return FAIL, f"the failed reply leads with {_shown(first)}, not one of {json.dumps(check['first_key'])}"
    for path, wanted in (check.get("fields") or {}).items():
        seen = lookup(payload, path)
        if seen != wanted:
            return FAIL, f"the failed reply's {path} is {_shown(seen)}, not {_shown(wanted)}"
    return PASS, f"one failed {check['tool']} call leading with '{first}', fields as required"


def _count_step(check, calls, reads, context):
    """The child's reads just before and just after one call differ by exactly `step`."""
    at = next((i for i, row in enumerate(calls) if _matches(row, check["around"])), None)
    if at is None:
        return FAIL, f"no {check['around']['tool']} call in the transcript"
    spec = check["read"]

    def value(rows):
        row = next((r for r in rows if _matches(r, spec) and not r["failed"]), None)
        return _MISSING if row is None else lookup(row["payload"], spec["path"])

    before, after = value(reversed(calls[:at])), value(calls[at + 1:])
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (before, after)):
        return FAIL, f"{spec['path']} read {_shown(before)} before and {_shown(after)} after; both must be numbers"
    if after - before != check["step"]:
        return FAIL, f"{spec['path']} went {before} -> {after}, not a step of {check['step']}"
    return PASS, f"{spec['path']} went {before} -> {after} across the call"


def _script_read(check, reads):
    """(row, why not): the script's own successful read for a check."""
    matching = [row for row in reads if _matches(row, check["read"])]
    if not matching:
        return None, f"the script made no {check['read']['tool']} read for this"
    good = next((row for row in matching if not row["failed"] and row["payload"] is not None), None)
    if good is None:
        return None, f"the script's {check['read']['tool']} read was refused: {matching[0]['text'][:160]}"
    return good, ""


def _read_field(check, calls, reads, context):
    """The script's own read shows one field equal to a value, or among the run's own handles."""
    row, why = _script_read(check, reads)
    if row is None:
        return FAIL, why
    seen = lookup(row["payload"], check["path"])
    if "in" in check:
        if seen not in context.get(check["in"], []):
            return FAIL, f"{check['path']} reads {_shown(seen)}, which is not one of the run's {check['in']} handles"
        return PASS, f"{check['path']} reads one of the run's {check['in']} handles"
    if seen != check["equals"]:
        return FAIL, f"{check['path']} reads {_shown(seen)}, not {_shown(check['equals'])}"
    return PASS, f"{check['path']} reads {_shown(seen)}"


def _read_agrees(check, calls, reads, context):
    """The script's own read equals the child's last read of the same field."""
    row, why = _script_read(check, reads)
    if row is None:
        return FAIL, why
    spec = dict(check["read"], path=check["path"])
    last = next((r for r in reversed(calls) if _matches(r, spec) and not r["failed"]), None)
    if last is None:
        return FAIL, f"the transcript holds no {spec['tool']} read to compare with"
    mine, theirs = lookup(row["payload"], check["path"]), lookup(last["payload"], check["path"])
    if mine is _MISSING or mine != theirs:
        return FAIL, f"{check['path']}: the script reads {_shown(mine)}, the child's last read was {_shown(theirs)}"
    return PASS, f"{check['path']} reads {_shown(mine)}, as the child's last read did"


def _read_fields_equal(check, calls, reads, context):
    """Two numbers in the script's own read are equal within a tolerance."""
    row, why = _script_read(check, reads)
    if row is None:
        return FAIL, why
    first, second = (lookup(row["payload"], path) for path in check["paths"])
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (first, second)):
        return FAIL, f"{check['paths'][0]} reads {_shown(first)} and {check['paths'][1]} reads {_shown(second)}"
    if abs(first - second) > check["within"]:
        return FAIL, f"{check['paths'][0]} = {first} and {check['paths'][1]} = {second} differ by more than {check['within']}"
    return PASS, f"{check['paths'][0]} = {check['paths'][1]} = {first} within {check['within']}"


_KINDS = {
    "write_then_read": ("transcript", _write_then_read),
    "failed_call": ("transcript", _failed_call),
    "count_step": ("transcript", _count_step),
    "read_field": ("script read", _read_field),
    "read_agrees": ("script read and transcript", _read_agrees),
    "read_fields_equal": ("script read", _read_fields_equal),
}


def renamed(checks, names):
    """`checks` with each fixed name replaced by the name a recorded run used ({fixed: used})."""
    text = json.dumps(checks)
    for fixed, used in (names or {}).items():
        text = text.replace(json.dumps(fixed), json.dumps(used))
    return json.loads(text)


def grade(checks, calls, reads, context, untested=""):
    """[{id, title, verdict, checks: [{kind, evidence, verdict, detail}]}] for a pack's outcomes."""
    if not untested and not calls:
        untested = "the client recorded no tool call"
    if not untested and reads is None:
        untested = "the script could not make its own reads"
    out = []
    for outcome in checks["outcomes"]:
        rows = []
        for check in outcome["checks"]:
            evidence, judge = _KINDS[check["kind"]]
            if untested:
                verdict, detail = UNTESTED, untested
            else:
                verdict, detail = judge(check, calls, reads, context)
            rows.append({"kind": check["kind"], "evidence": evidence,
                         "verdict": verdict, "detail": detail})
        verdicts = {row["verdict"] for row in rows}
        verdict = UNTESTED if verdicts == {UNTESTED} else PASS if verdicts == {PASS} else FAIL
        out.append({"id": outcome["id"], "title": outcome["title"], "verdict": verdict, "checks": rows})
    return out


def document_list(payload):
    """({handle: {"saved", "modified"}}, active handle, complete) from one doc_get payload.
    doc_get leaves is_saved out of a row when it is true, so an absent flag reads as saved."""
    rows = payload.get("open_documents") if isinstance(payload, dict) else None
    rows = rows if isinstance(rows, list) else []
    listed = {row["document_handle"]: {"saved": bool(row.get("is_saved", True)),
                                       "modified": bool(row.get("is_modified"))}
              for row in rows if isinstance(row, dict) and row.get("document_handle")}
    active = ((payload or {}).get("active") or {}).get("document_handle")
    complete = len(listed) == len(rows) == (payload or {}).get("open_count")
    return listed, active, complete


NOT_LISTED = "the open documents could not be listed completely, so nothing is claimed about the session"


def owned_handles(calls, census, opening):
    """(owned, unexpected) handles. A document is this run's only when the child's own successful
    doc_new reply names it, a complete `census` still lists it and it was not open at the start;
    every other new document is unexpected. An incomplete census owns nothing."""
    listed, _active, complete = census
    if not complete:
        return [], []
    made = [row["payload"].get("document_handle") for row in calls
            if row["tool"] == "doc_new" and not row["failed"]
            and isinstance(row["payload"], dict) and row["payload"].get("created") is True]
    owned = [handle for handle in dict.fromkeys(made) if handle in listed and handle not in opening[0]]
    return owned, [handle for handle in listed if handle not in opening[0] and handle not in owned]


def list_differences(opening, closing):
    """What differs between two document_list() results; empty only when both are complete and the
    session is as it was."""
    (before, active_before, complete_before), (after, active_after, complete_after) = opening, closing
    if not (complete_before and complete_after):
        return [NOT_LISTED]
    out = [f"{handle} was open at the start and is not open now" for handle in before if handle not in after]
    out += [f"{handle} is open now and was not at the start" for handle in after if handle not in before]
    out += [f"{handle} changed from {before[handle]} to {after[handle]}"
            for handle in before if handle in after and before[handle] != after[handle]]
    if active_before != active_after:
        out.append(f"the active document was {active_before} and is now {active_after}")
    return out
