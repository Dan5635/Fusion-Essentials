# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The batch loop the sketch write tools share: the entries of one call run in order against ONE
resolved sketch, the first failure stops the run, and the payload says what landed, what failed and
what was not attempted."""

from ._common import counted, error, ok, safe

MAP_BLURB = ("the sketch batch substrate: entries_or_error - the list-shape guard; run_batch - one "
             "sketch's entries in order, stopping at the first failure or raise, with the shared "
             "landed/failed/not_attempted payload; refuse - an entry refused before any write; "
             "entry_counts - the four counts a failed entry is judged by; retired_clause - delete "
             "an entry's minted midpoint anchors, judged by those counts")

# Above this an entry list is refused: a call is one turn's work, not a whole drawing.
_MAX_ENTRIES = 200
UNKNOWN_RETENTION = object()
MID_ANCHORS = ("mid", "midpoint")


class Refusal(str):
    """An entry error decided before the entry's first write."""


def refuse(text):
    """(None, Refusal) - the return of an entry refused before its first write."""
    return None, Refusal(text)


def entries_or_error(raw, name, allowed):
    """(entries, error): `raw` must be a non-empty list of objects carrying only `allowed` fields."""
    if not isinstance(raw, list) or not raw:
        return None, f"'{name}' must be a non-empty list of entries."
    if len(raw) > _MAX_ENTRIES:
        return None, f"'{name}' holds {len(raw)} entries; the cap is {_MAX_ENTRIES} per call."
    allowed = set(allowed)
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            return None, f"{name}[{i}] is not an object."
        unknown = sorted(k for k in entry if k not in allowed)
        if unknown:
            return None, (f"{name}[{i}] carries unknown field(s): {', '.join(unknown)}. "
                          f"An entry takes: {', '.join(sorted(allowed))}.")
    return raw, None


def entry_counts(sketch):
    """Read the four sketch collection counts, retaining unknown values."""
    values = {label: counted(lambda attr=attr: getattr(sketch, attr).count)
              for label, attr in (("curves", "sketchCurves"), ("points", "sketchPoints"),
                                  ("constraints", "geometricConstraints"), ("dimensions", "sketchDimensions"))}
    return {key: n if n is not None and n >= 0 else None for key, n in values.items()}


def retired_clause(sketch, minted, baseline):
    """Delete the midpoint anchor points this entry made; the clause the sketch counts back."""
    if not minted:
        return ""
    # A cleanup of the entry's own points: a delete that raises or declines is judged by the counts.
    for point in minted:
        safe(lambda p=point: p.deleteMe())
    after = entry_counts(sketch)
    stayed = [f"{k}=unknown" if None in (after[k], baseline[k])
              else f"{k}={after[k] - baseline[k]:+d}" for k in ("points", "constraints")
              if None in (after[k], baseline[k]) or after[k] != baseline[k]]
    if not stayed:
        return (" The midpoint anchor(s) it made were deleted: the point and constraint counts read "
                "back as before the entry.")
    return (f" Deleting the midpoint anchor(s) it made left {', '.join(stayed)} against the counts "
            "before the entry; sketch_get(include_entities=true) lists them and "
            "sketch_delete_entity removes one.")


def _failed_counts(before, after, wrote):
    """Return per-entry count evidence and its note; the readback guidance only after a write."""
    change = {key: after[key] - value if value is not None and after[key] is not None else None
              for key, value in before.items()}
    text = ", ".join(f"{key}={value:+d}" if value is not None else f"{key}=unknown"
                     for key, value in change.items())
    note = f"Failed-entry count changes: {text}."
    if wrote:
        note += (" Counts do not establish unchanged geometry. Read "
                 "sketch_get(include_entities=true) for current entities and constraints.")
    return {"before": before, "after": after, "change": change}, note


def _retained_text(kept, change):
    """The failed entry's retained-effect clause, naming each counted kind that changed."""
    moved = [(key, n) for key, n in change.items() if n]
    unread = [key for key, n in change.items() if n is None]
    if [n for _key, n in moved] == [kept] and not unread:
        return f"The failed entry left {kept} retained effect in the sketch, identified in 'retained'"
    text = (f"The failed entry left {', '.join(f'{k}={n:+d}' for k, n in moved)} in the sketch; "
            f"'retained' identifies {kept} of those effects" if moved else
            f"The failed entry kept {kept} effect, identified in 'retained'")
    return text + (f" ({', '.join(unread)} did not read)" if unread else "")


def run_batch(entries, one, name, verb, sketch_name, *, sketch, result_note="", result_fields=None):
    """Run one sketch batch and report completed, retained, failed, and unattempted entries."""
    results = []
    retained = []
    retention_unknown = False
    failed = None
    count_evidence, count_note = None, ""
    for i, entry in enumerate(entries):
        before = entry_counts(sketch)
        try:
            res, err = one(i, entry)
        except Exception as e:
            res, err = UNKNOWN_RETENTION, f"The entry raised: {str(e).rstrip('.')}."
        if err:
            failed = {"index": i, "error": err}
            count_evidence, count_note = _failed_counts(before, entry_counts(sketch),
                                                        not isinstance(err, Refusal))
            if res is UNKNOWN_RETENTION:
                retention_unknown = True
            elif res is not None:
                kept = dict(res)
                kept["index"] = i
                retained.append(kept)
            break
        res = dict(res or {})
        res["index"] = i
        results.append(res)
    requested = len(entries)
    if failed and not results and not retained:
        rest = requested - 1
        tail = (f" {rest} later entr{'y was' if rest == 1 else 'ies were'} not attempted."
                if rest else "")
        landed = ("Nothing completed; whether the failed entry retained an effect in the sketch "
                  "could not be read." if retention_unknown else "Nothing completed.")
        landed += " " + count_note
        return error(f"{name}[{failed['index']}]: {failed['error']} {landed}{tail}")
    payload = {verb: len(results), "requested": requested, "sketch": sketch_name,
               "results": results}
    note = f"{len(results)} of {requested} {name} landed."
    if failed:
        payload["failed"] = failed
        payload["failed_entry_counts"] = count_evidence
        payload["not_attempted"] = requested - failed["index"] - 1
        if retained:
            payload["retained"] = retained
            note = (f"{len(results)} of {requested} {name} completed. Stopped at "
                    f"{name}[{failed['index']}]: {failed['error']} "
                    f"{_retained_text(len(retained), count_evidence['change'])}; "
                    f"{payload['not_attempted']} after it were not attempted.")
        elif retention_unknown:
            payload["retained"] = None
            note = (f"{len(results)} of {requested} {name} completed. Stopped at "
                    f"{name}[{failed['index']}]: {failed['error']} Whether the failed entry retained "
                    f"an effect could not be read; 'retained' is null. {payload['not_attempted']} "
                    "after it were not attempted.")
        else:
            note += (f" Stopped at {name}[{failed['index']}]: {failed['error']} The entries before "
                     f"it are in the sketch; {payload['not_attempted']} after it were not attempted.")
        note += " " + count_note
    payload["note"] = note
    if result_fields:
        payload = {**(result_fields(results) or {}), **payload}
    if result_note:
        payload["result_note"] = result_note
    return error(payload["note"], payload=payload) if failed else ok(payload)
