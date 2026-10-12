# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The cold self-test's cleanup against a stand-in session: it closes only what the child's own
doc_new replies prove the run made, and claims a clean session only from a complete document list."""

import importlib.util
import json
import os
import sys

_COLD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live", "cold")
_SIBLINGS = ("clients", "grader", "wire")


def _selftest():
    """selftest.py loaded with its sibling modules, leaving sys.path and sys.modules as they were."""
    kept = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
    sys.path.insert(0, _COLD)
    try:
        spec = importlib.util.spec_from_file_location("cold_selftest", os.path.join(_COLD, "selftest.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(_COLD)
        for name, was in kept.items():
            sys.modules.pop(name, None)
            if was is not None:
                sys.modules[name] = was
    return module


selftest = _selftest()
grader = selftest.grader
HOME, CHILD, OTHER = "session:home", "session:child", "session:owner-new"
NO_CHECKS = {"outcomes": []}


def _census(handles, active, count=None):
    return {"open_documents": [{"document_handle": h, "is_saved": False, "is_modified": False} for h in handles],
            "active": {"document_handle": active},
            "open_count": len(handles) if count is None else count}


def _row(tool, arguments, payload, failed=False):
    return grader.call_row(tool, arguments, {"content": [{"type": "text", "text": json.dumps(payload)}],
                                             "isError": failed})


def _made(handle, created=True, failed=False):
    return _row("doc_new", {}, {"created": created, "document_handle": handle}, failed)


class Session:
    """Open documents that answer doc_get, doc_activate and doc_close as the server's replies do."""

    def __init__(self, handles, active, hidden=0, refuse=()):
        self.handles, self.active, self.closed = list(handles), active, []
        self.hidden, self.refuse = hidden, set(refuse)

    def call(self, tool, arguments):
        if tool in self.refuse:
            return _row(tool, arguments, {"error": tool + " refused"}, failed=True)
        if tool == "doc_get":
            return _row(tool, arguments, _census(self.handles, self.active, len(self.handles) + self.hidden))
        if tool == "doc_activate":
            self.active = arguments["name"]
        if tool == "doc_close":
            self.closed.append(arguments["name"])
            self.handles.remove(arguments["name"])
            self.active = self.handles[0]
        return _row(tool, arguments, {})


OPENING = grader.document_list(_census([HOME], HOME))


def _finish(session, calls):
    """(owned, unexpected, session differences) after the script's reads and its cleanup."""
    _reads, owned, unexpected = selftest.own_reads(session, NO_CHECKS, OPENING, calls)
    return owned, unexpected, selftest.clean_up(session, owned, OPENING)


def test_the_runs_own_documents_are_closed_and_the_session_reads_as_found():
    session = Session([HOME, CHILD], CHILD)
    owned, unexpected, differences = _finish(session, [_made(CHILD)])
    assert (owned, unexpected, session.closed) == ([CHILD], [], [CHILD])
    assert differences == [] and session.active == HOME


def test_a_document_the_owner_opened_during_the_run_is_left_open_and_reported():
    session = Session([HOME, CHILD, OTHER], CHILD)
    owned, unexpected, differences = _finish(session, [_made(CHILD)])
    assert (owned, unexpected, session.closed) == ([CHILD], [OTHER], [CHILD])
    assert differences == [f"{OTHER} is open now and was not at the start"]


def test_only_a_successful_doc_new_reply_makes_a_document_the_runs_own():
    calls = [_made(CHILD, failed=True), _made(OTHER, created=False), _made(HOME),
             _row("doc_activate", {"name": OTHER}, {"document_handle": OTHER})]
    session = Session([HOME, CHILD, OTHER], HOME)
    owned, unexpected, differences = _finish(session, calls)
    assert (owned, unexpected, session.closed) == ([], [CHILD, OTHER], [])
    assert len(differences) == 2


def test_an_incomplete_document_list_is_never_a_clean_session():
    incomplete = grader.document_list(_census([HOME], HOME, count=2))
    assert grader.list_differences(OPENING, incomplete) == [grader.NOT_LISTED]
    assert grader.list_differences(incomplete, OPENING) == [grader.NOT_LISTED]
    assert grader.owned_handles([_made(CHILD)], grader.document_list(_census([HOME, CHILD], HOME, count=3)),
                                OPENING) == ([], [])


def test_a_document_saved_or_unsaved_during_the_run_is_a_difference_either_way():
    saved = {"document_handle": HOME}
    unsaved = {"document_handle": HOME, "is_saved": False}

    def listing(row):
        return grader.document_list({"open_documents": [row], "open_count": 1,
                                     "active": {"document_handle": HOME}})

    assert listing(saved)[0][HOME]["saved"] is True and listing(unsaved)[0][HOME]["saved"] is False
    for before, after in ((saved, unsaved), (unsaved, saved)):
        differences = grader.list_differences(listing(before), listing(after))
        assert len(differences) == 1 and differences[0].startswith(HOME + " changed from")
    assert grader.list_differences(listing(saved), listing(saved)) == []


def test_nothing_is_closed_when_the_documents_cannot_all_be_listed():
    for session in (Session([HOME, CHILD], CHILD, hidden=1), Session([HOME, CHILD], CHILD, refuse=["doc_get"])):
        reads, owned, unexpected = selftest.own_reads(session, NO_CHECKS, OPENING, [_made(CHILD)])
        assert (reads, owned, unexpected) == (None, [], [])
        # Cleanup refuses on its own reading too, whatever it is handed.
        differences = selftest.clean_up(session, [CHILD], OPENING)
        assert session.closed == [] and len(differences) == 1 and grader.NOT_LISTED in differences[0]


def test_the_claude_reader_keeps_the_clients_own_error_and_not_its_report():
    limit = {"type": "result", "is_error": True, "result": "You've hit your weekly limit\n resets 11pm"}
    report = {"type": "result", "is_error": False, "result": "Built it."}
    for record, said in ((limit, "You've hit your weekly limit resets 11pm"), (report, "")):
        reader = selftest.clients.CLIENTS["claude"].reader()
        assert reader.feed(json.dumps(record)) == [] and reader.said == said
    assert selftest.clients.CLIENTS["codex"].reader().said == ""


def test_the_codex_reader_keeps_a_failed_turns_message_and_not_its_warnings():
    reader = selftest.clients.CLIENTS["codex"].reader()
    warning = {"type": "item.completed", "item": {"id": "item_0", "type": "error",
                                                  "message": "Under-development features enabled"}}
    retry = {"type": "error", "message": "Reconnecting... 2/5 (unexpected status 503)"}
    failed = {"type": "turn.failed", "error": {"message": "Selected model is at capacity.\nPlease try a different model."}}
    assert [reader.feed(json.dumps(row)) for row in (warning, retry)] == [[], []] and reader.said == ""
    assert reader.feed(json.dumps(failed)) == []
    assert reader.said == "Selected model is at capacity. Please try a different model."


def test_a_refused_close_is_reported_and_the_document_stays_listed_as_a_difference():
    session = Session([HOME, CHILD], CHILD, refuse=["doc_close"])
    _owned, _unexpected, differences = _finish(session, [_made(CHILD)])
    assert session.closed == [] and len(differences) == 2
    assert differences[0].startswith(f"{CHILD} was not closed") and CHILD in differences[1]
