# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Keep local render futures addressable for this add-in process."""

import secrets

MAP_BLURB = "local render job IDs and bounded in-process RenderFuture retention"

_PREFIX = secrets.token_hex(8)
_LIMIT = 32
_NEXT = 0
_JOBS = {}


def capacity():
    """Return whether a future can be retained without dropping a running job."""
    return len(_JOBS) < _LIMIT or any(row["terminal"] for row in _JOBS.values())


def add(future, path, document):
    """Retain a future and return its session-local ID, or None at capacity."""
    global _NEXT
    if not capacity():
        return None
    if len(_JOBS) >= _LIMIT:
        oldest = next(key for key, row in _JOBS.items() if row["terminal"])
        del _JOBS[oldest]
    _NEXT += 1
    key = f"render:{_PREFIX}:{_NEXT}"
    _JOBS[key] = {"future": future, "path": path, "document": document, "terminal": False}
    return key


def get(job_id):
    """Return a retained local job or None for an unknown or reloaded ID."""
    return _JOBS.get(job_id)


def set_terminal(job_id):
    """Mark a job as terminal only after its native state is read."""
    row = _JOBS.get(job_id)
    if row is not None:
        row["terminal"] = True


def count():
    """Return the number of retained jobs."""
    return len(_JOBS)
