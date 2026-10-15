# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Read one durable deferred drawing-operation record without touching Fusion APIs."""

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..server import drawing_jobs
from ._common import ok


_PENDING_NOTE = ("Work has not finished. Poll this request_key; do not repeat this operation "
                 "with a new key.")
_RUNNING_NOTE = ("Fusion is processing this drawing job. This is not a failure or a progress "
                 "estimate; poll the same request_key, even if processing takes minutes.")
_UNRESOLVED_NOTE = ("Outcome unknown after a restart or persistence failure. For drawing_create, "
                    "check data_get for the cloud file before any retry; do not assume failure.")


def handler(request_key: str = "") -> dict:
    key = request_key.strip() if isinstance(request_key, str) else ""
    if not key:
        return ok({"request_key": request_key, "status": "unknown",
                   "note": "Provide the request_key used for deferred drawing work."})
    record = drawing_jobs.get_store().get(key)
    if record is None:
        return ok({"request_key": key, "status": "unknown",
                   "note": "No durable drawing job has this request_key."})
    record.pop("canonical_request", None)
    record.pop("owner_instance", None)
    state = record.get("status")
    if state in ("accepted", "queued"):
        note = _PENDING_NOTE
    elif state == "running":
        note = _RUNNING_NOTE
    elif state == "completed":
        note = ("Completed. Read terminal_result for the created file_id, then doc_open it."
                if record.get("tool") == "drawing_create" else
                "Completed. Read terminal_result and independently check the effect.")
    elif state == "failed":
        note = ("Failed. Read terminal_result or reason. For drawing_create, check data_get "
                "for a cloud file before retrying.")
    else:
        note = _UNRESOLVED_NOTE
    record["note"] = note
    return ok(record)


TOOL_DESCRIPTION = (
    "Poll drawing_create, drawing_update or drawing_export by request_key. "
    "Pending: wait; completed: result; failed/unresolved: inspect."
)

tool = (
    Tool.create_simple(name="drawing_get_status", description=TOOL_DESCRIPTION)
    .add_input_property("request_key", {"type": "string",
            "description": "The same key sent with deferred=true."})
    .add_required_input("request_key")
    .strict_schema()
)
item = Item.create_tool_item(tool=tool, write="read", handler=handler, run_on_main_thread=False)


def register_tool():
    register(item)
