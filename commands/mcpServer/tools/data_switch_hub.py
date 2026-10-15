# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""List the user's Autodesk data hubs and switch the active one after a cloud-edit preflight."""

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import counted, ok, error, safe, read_flag
from . import _inputs
from . import _write_guard

app = adsk.core.Application.get()

_ACTIONS = ("list", "switch")
_MAX_OPEN_DOCUMENTS = 50
_UNREADABLE = object()


def _hub_census(data):
    """Return hub/name/id rows and whether the full collection read."""
    hubs = safe(lambda: data.dataHubs)
    count = counted(lambda: hubs.count)
    out = []
    for i in range(count or 0):
        h = safe(lambda i=i: hubs.item(i))
        if h is not None:
            out.append((h, safe(lambda h=h: h.name) or None, safe(lambda h=h: h.id)))
    return out, count is not None and len(out) == count


def _document_census(application):
    """Read at most 50 open documents with session identity and cloud-edit state."""
    docs = safe(lambda: application.documents)
    if docs is None:
        return [], None, False, False, []
    total = counted(lambda: docs.count)
    if total is None or total < 0:
        return [], total, False, False, []
    truncated = total > _MAX_OPEN_DOCUMENTS
    rows = []
    unreadable = []
    for i in range(min(total, _MAX_OPEN_DOCUMENTS)):
        doc = safe(lambda i=i: docs.item(i), _UNREADABLE)
        if doc is _UNREADABLE or doc is None:
            rows.append(None)
            unreadable.append(f"open document at index {i} could not be read")
            continue
        handle = safe(lambda doc=doc: _write_guard.document_handle(doc))
        name = safe(lambda doc=doc: doc.name)
        modified = read_flag(lambda doc=doc: doc.isModified)
        data_file = safe(lambda doc=doc: doc.dataFile, _UNREADABLE)
        if data_file is _UNREADABLE:
            cloud_backed, document_id = None, None
        elif data_file is None:
            cloud_backed, document_id = False, None
        else:
            document_id = safe(lambda data_file=data_file: data_file.id, _UNREADABLE)
            if document_id is _UNREADABLE or not isinstance(document_id, str) or not document_id:
                cloud_backed = None
                document_id = None
            else:
                cloud_backed = True
        rows.append({
            "name": name if isinstance(name, str) and name else None,
            "document_id": document_id,
            "document_handle": handle,
            "is_modified": modified,
            "cloud_backed": cloud_backed,
        })
        row_label = (f"{name} ({handle})" if isinstance(name, str) and name and handle
                     else handle or f"open document at index {i}")
        if not handle:
            unreadable.append(f"{row_label}: session identity unreadable")
        if modified is None:
            unreadable.append(f"{row_label}: modified state unreadable")
        if cloud_backed is None:
            unreadable.append(f"{row_label}: cloud backing or file identity unreadable")
    complete = not truncated and len(rows) == total and not unreadable
    return rows, total, complete, truncated, unreadable


def _census_refusal(total, truncated, unreadable):
    """Explain how to restore a complete document census before retrying."""
    if total is None:
        why = "the open-document count could not be read"
    elif truncated:
        why = (f"{total} documents exceed the {_MAX_OPEN_DOCUMENTS}-document safety limit; "
               "close or reduce the open documents you own, or ask the user to do so")
    else:
        why = "one or more document identities or save states could not be read"
    detail = "; ".join(unreadable[:5])
    if len(unreadable) > 5:
        detail += f"; and {len(unreadable) - 5} more unreadable item(s)"
    suffix = f" Details: {detail}." if detail else ""
    return error(f"Cannot safely switch hubs because {why}.{suffix} Read doc_get. If an owned "
                 "document stays unreadable, ask the user to preserve its edits and close it. "
                 "Retry only when every remaining document identity and save state reads.")


def _document_payload(rows):
    """Return public document rows without internal cloud classification."""
    return [{key: row[key] for key in ("name", "document_id", "document_handle",
                                        "is_modified")} for row in rows if row is not None]


def _switch_effect(before, after, after_complete):
    """Compare session handles only when both censuses are complete."""
    if not after_complete:
        return None, None
    old = {row["document_handle"] for row in before}
    new = {row["document_handle"] for row in after}
    return sorted(old - new), sorted(old & new)


def _name_target(hubs, complete, want):
    """((hub, name, id), None) for the one hub named `want`, or (None, error text)."""
    wl = want.lower()
    matches = [row for row in hubs if (row[1] or "").strip().lower() == wl]
    if len(matches) > 1:
        rows = ", ".join(f"'{nm}' ({hid})" for (_, nm, hid) in matches)
        return None, (f"Hub name '{want}' matches {len(matches)} hubs: {rows}. Nothing was "
                      "switched. Pass hub=<id> to choose one.")
    unread = [hid or "(id unread)" for (_, nm, hid) in hubs if nm is None]
    if unread or not complete:
        what = (f"the name of hub(s) {', '.join(unread)} did not read" if unread
                else "the hub list did not read completely")
        return None, (f"Hub name '{want}' cannot be resolved: {what}. Nothing was switched. Pass "
                      "hub=<id> from data_get(include=['hubs']).")
    return (matches[0] if matches else None), None


def handler(action: str = "list", hub: str = "") -> dict:
    """See TOOL_DESCRIPTION."""
    act = (action or "list").strip().lower()
    if act not in _ACTIONS:
        return error(f"Unknown action '{action}'. Use: list, switch.")

    data = safe(lambda: app.data)
    if not data:
        return error("Data not available (not signed in?).")

    active = safe(lambda: data.activeHub)
    active_id = safe(lambda: active.id) if active else None
    hubs, complete = _hub_census(data)

    if act == "list":
        return ok({
        "active_hub": ({"name": safe(lambda: active.name), "id": active_id} if active else None),
        "hub_count": len(hubs),
        "hubs": [{"name": nm or "(unnamed)", "id": hid, "is_active": (hid == active_id)}
                 for (_, nm, hid) in hubs],
        })

    # switch
    want = (hub or "").strip()
    if not want:
        return error("Provide 'hub' - the name or id of the hub to switch to (see action='list').")

    # an exact id first; a name only when it names exactly one hub of a census that read whole
    by_id = [row for row in hubs if row[2] == want]
    target, name_error = (by_id[0], None) if len(by_id) == 1 else _name_target(hubs, complete, want)
    if name_error:
        return error(name_error)
    if target is None:
        names = ", ".join(nm or "(unnamed)" for (_, nm, _) in hubs) or "(none)"
        return error(f"No hub matched '{want}'. Available: {names}.")

    th, tname, tid = target
    tname = tname or "(unnamed)"
    if not isinstance(tid, str) or not tid:
        return error(f"Cannot switch to hub '{tname}': its identity could not be read. "
                     "Pass hub=<id> from data_get(include=['hubs']) once the id reads.")
    if not isinstance(active_id, str) or not active_id:
        return error("Cannot switch hubs because the active hub identity could not be read. "
                     "Read data_get(include=['hubs']) and retry once the active hub is known.")
    if tid == active_id:
        return ok({
        "switched": False,
        "already_active": True,
        "active_hub": {"name": tname, "id": tid},
        "note": f"'{tname}' is already the active hub - nothing to do.",
        })

    before, before_count, before_complete, before_truncated, before_unreadable = _document_census(app)
    if not before_complete:
        return _census_refusal(before_count, before_truncated, before_unreadable)
    dirty_cloud = [row for row in before if row["cloud_backed"] and row["is_modified"]]
    if dirty_cloud:
        rows = [{"name": row["name"], "document_id": row["document_id"],
                 "document_handle": row["document_handle"], "is_modified": True,
                 "remedy": (f"doc_activate(name='{row['document_handle']}') then "
                            f"doc_save(expect_document='{row['document_handle']}'), or "
                            f"doc_close(name='{row['document_handle']}', save_changes=false)")}
                for row in dirty_cloud]
        return error(
            f"Refusing hub switch: {len(rows)} cloud-backed document(s) have unsaved edits. "
            "Use each document's listed activate-and-save or close remedy, then retry, or remain in the "
            "current hub. Never-saved modified documents do not block this switch.",
            {"blocked_by": "modified_cloud_documents",
             "modified_cloud_document_count": len(rows),
             "modified_cloud_documents_truncated": False,
             "modified_cloud_documents": rows})

    # An assignment that returns is not an assignment that landed, so the active hub is re-read and
    # the switch is judged by that read alone.
    assign_error = None
    try:
        data.activeHub = th
    except Exception as e:
        assign_error = str(e)

    new_active = safe(lambda: data.activeHub)
    new_id = safe(lambda: new_active.id) if new_active else None
    after, after_count, after_complete, after_truncated, after_unreadable = _document_census(app)
    before_public = _document_payload(before)
    after_public = _document_payload(after)
    closed_handles, retained_handles = _switch_effect(before, after, after_complete)
    census = {
        "switched": new_id == tid if new_id else None,
        "active_hub_before": {"name": safe(lambda: active.name), "id": active_id},
        "active_hub_after": ({"name": safe(lambda: new_active.name), "id": new_id}
                              if new_active and new_id else None),
        "assignment_error": assign_error,
        "documents_before_count": before_count,
        "documents_before_truncated": False,
        "documents_before": before_public,
        "documents_after_count": after_count,
        "documents_after_truncated": after_truncated,
        "documents_after_complete": after_complete,
        "documents_after_unreadable": after_unreadable[:5],
        "documents_after": after_public,
        "closed_document_handles": closed_handles,
        "retained_document_handles": retained_handles,
    }
    if not isinstance(new_id, str) or not new_id or new_id != tid:
        now = (safe(lambda: new_active.name) or new_id) if new_active else None
        message = (
            f"Could not switch to hub '{tname}' ({tid}): the re-read after the assignment shows the "
            f"active hub as {now!r}, not the target"
            + (f" - the assignment raised: {assign_error}" if assign_error else "")
            + ". Switch hubs from the Fusion data panel (the hub dropdown), then verify the open documents.")
        return error(message, {**census, "note": message})

    if not after_complete:
        message = (f"Hub '{tname}' became active, but the post-switch document census is incomplete; "
                   "the exact closed and retained documents are unknown. Read doc_get before continuing.")
        if assign_error:
            message += f" The assignment also raised: {assign_error}."
        return error(message, {**census, "note": message})

    return ok({
        **census,
        "already_active": False,
        "active_hub": {"name": safe(lambda: new_active.name) or tname, "id": new_id},
        "note": (f"Active hub switched. {len(closed_handles)} document(s) closed; "
                 f"{len(retained_handles)} retained by session handle. "
                 + (f"The assignment raised after the target became active: {assign_error}. "
                    if assign_error else "")
                 + "Re-list projects and re-resolve hub-scoped URNs with data_get."),
    })


TOOL_DESCRIPTION = (
    "Switch the active Autodesk data hub after checking cloud-backed edits; list hubs with data_get(include=['hubs'])."
)

tool = (
    Tool.create_simple(name="data_switch_hub", description=TOOL_DESCRIPTION)
    .add_input_property(*_inputs.Choice("action", list(_ACTIONS), default="list").as_property())
    .add_input_property("hub", {"type": "string", "description": "Hub name or id."})
    .strict_schema()
)

item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline",
        evidence_test="tests/unit/test_data_switch_hub.py::TestTheReReadDecides"
                      "::test_silent_noop_setter_reports_honest_error_not_false_success",
        rung="value"))


def register_tool():
    register(item)
