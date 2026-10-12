# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The cold self-test: hand a small task to a fresh agent that holds only the Fusion tools, then
read what it left and grade it.

    python tests/live/cold/selftest.py                       run it against your session
    python tests/live/cold/selftest.py --replay RUN --replay-opening FILE --replay-reads FILE
                                                             grade a recorded run, no Fusion

It needs Fusion running with the add-in loaded and one agent client that is signed in. It reads no
cloud configuration, uses no scripting tool and writes nothing outside scratch documents it closes
again. README.md beside this file says what it does to your session and what the result means."""

import argparse
import hashlib
import json
import os
import platform
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

import clients
import grader
import wire as wire_client

HERE = os.path.dirname(os.path.abspath(__file__))
PACKS = os.path.join(HERE, "packs")
ALL_DOCUMENTS = {"max_results": 1000}
EXIT_PASS, EXIT_FAIL, EXIT_NOT_RUN, EXIT_SESSION_DIFFERS = 0, 1, 2, 3


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def load_pack(name):
    """(task bytes, checks, {file: sha256}) for a pack whose files match the tracked manifest."""
    folder = os.path.join(PACKS, name)
    with open(os.path.join(PACKS, "manifest.json"), encoding="utf-8") as fh:
        listed = json.load(fh).get(name)
    if not listed:
        sys.exit(f"No pack named '{name}' in {os.path.join(PACKS, 'manifest.json')}.")
    found = {fn: _sha(os.path.join(folder, fn)) for fn in listed}
    changed = sorted(fn for fn in listed if found[fn] != listed[fn])
    if changed:
        sys.exit(f"Pack '{name}' does not match its manifest ({', '.join(changed)}); a task or its "
                 "checks was edited without the other. Restore the files or update the manifest.")
    with open(os.path.join(folder, "task.md"), "rb") as fh:
        task = fh.read().replace(b"\r\n", b"\n")
    with open(os.path.join(folder, "checks.json"), encoding="utf-8") as fh:
        return task, json.load(fh), found


def admit(wire, checks, accept_open_work):
    """(admission record, opening document list, refusal). A refusal names its own remedy."""
    try:
        health = wire.health()
    except OSError as exc:
        return None, None, (f"No server answered at {wire.base} ({exc}). Start Fusion with the "
                            "add-in loaded, or pass --port with the add-in's mcp_port.")
    if health.get("server") != wire_client.SERVER_NAME:
        return None, None, (f"{wire.base} answers as {health.get('server')!r}, not "
                            f"{wire_client.SERVER_NAME!r}. Pass --port with this add-in's port.")
    attestation = health.get("attestation") or {}
    if attestation.get("complete") is not True or attestation.get("loaded_matches_source") is not True:
        return None, None, ("The add-in Fusion loaded does not match its source files "
                            f"(problems: {attestation.get('problems')}). Reload the add-in and rerun.")
    asked = urllib.parse.urlparse(wire.base).port
    bound = (health.get("bound") or {}).get("port")
    if bound is not None and bound != asked:
        return None, None, f"The server reports port {bound} but was reached on {asked}."
    names = wire.tool_names()
    missing = sorted(set(checks["needs_tools"]) - set(names))
    if missing:
        return None, None, ("This session does not serve tools the pack needs: "
                            f"{', '.join(missing)}. Enable their families in the add-in settings.")
    census = wire.call("doc_get", ALL_DOCUMENTS)
    opening = grader.document_list(census["payload"])
    if census["failed"] or not opening[2]:
        return None, None, ("The open documents could not be listed completely "
                            f"({census['text'][:200]}). Close some documents and rerun.")
    unsaved = sorted(h for h, state in opening[0].items() if state["modified"])
    if unsaved and not accept_open_work:
        return None, None, (f"{len(unsaved)} open document(s) hold unsaved changes. Save or close "
                            "them first: an agent is about to work in this session. To run anyway, "
                            "pass --accept-open-work.")
    orient = wire.call("workspace_orient", {})
    record = {
        "server": {"version": health.get("version"), "bound": health.get("bound"),
                   "attestation": attestation},
        "session": {"fusion_version": (orient["payload"] or {}).get("fusion_version"),
                    "os": platform.platform(), "python": platform.python_version()},
        "tier": {"tools": len(names), "scripting_tool": "sys_execute_script" in names},
        "opening": {"documents": opening[0], "active": opening[1]},
    }
    return record, opening, ""


def run_child(reader, argv, env, cwd, task, run_dir, max_calls, max_seconds):
    """(call rows, how the run ended) for one child launched with the task on its stdin."""
    calls, lines = [], queue.Queue()

    def pump(stream):
        for line in stream:
            lines.put(line)
        lines.put(None)

    started, status = time.monotonic(), "completed"
    with open(os.path.join(run_dir, "client-stderr.log"), "wb") as err, \
            open(os.path.join(run_dir, "transcript.jsonl"), "wb") as transcript:
        process = clients.start(argv, cwd, err, env)
        process.stdin.write(task)
        process.stdin.close()
        threading.Thread(target=pump, args=(process.stdout,), daemon=True).start()
        while True:
            if time.monotonic() - started >= max_seconds:
                status = "time_cap"
                break
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                break
            transcript.write(line)
            transcript.flush()
            calls.extend(reader.feed(line.decode("utf-8", "replace")))
            if len(calls) >= max_calls:
                status = "call_cap"
                break
        if status != "completed":
            clients.kill_tree(process)
        try:
            code = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            clients.kill_tree(process)
            code = process.wait()
    return calls, {"status": status, "exit_code": code, "calls": len(calls),
                   "seconds": round(time.monotonic() - started, 1)}


def _activate(wire, handle, active):
    """The active handle after making `handle` active (unchanged when the switch was refused)."""
    if handle == active:
        return active
    row = wire.call("doc_activate", {"name": handle, "expect_document": active})
    return active if row["failed"] else handle


def _census(wire):
    """(the doc_get row, its document list); the list is None when the read was refused or did not
    list every open document."""
    row = wire.call("doc_get", ALL_DOCUMENTS)
    listing = grader.document_list(row["payload"])
    return row, (None if row["failed"] or not listing[2] else listing)


def own_reads(wire, checks, opening, calls):
    """(read rows, owned handles, unexpected handles): the script's own reads, taken in each
    document the child's doc_new replies prove it made. With no complete document list there are no
    reads and nothing is owned."""
    census, listing = _census(wire)
    if listing is None:
        return None, [], []
    owned, unexpected = grader.owned_handles(calls, listing, opening)
    active = listing[1]
    rows, asked = [census], []
    for outcome in checks["outcomes"]:
        for check in outcome["checks"]:
            spec = check.get("read") or {}
            if "arguments" not in spec or spec["tool"] == "doc_get" or spec in asked:
                continue
            asked.append(spec)
            for handle in owned:
                active = _activate(wire, handle, active)
                if active == handle:
                    rows.append(dict(wire.call(spec["tool"], spec["arguments"]), document_handle=handle))
    return rows, owned, unexpected


def clean_up(wire, owned, opening):
    """What keeps the session from being as it was found, after closing the documents this run
    made. A document is closed only while a complete list shows it open; after a list that is
    refused or incomplete nothing more is closed and no clean session is claimed."""
    notes = []
    for handle in owned:
        _row, listing = _census(wire)
        if listing is None:
            return notes + [grader.NOT_LISTED + "; cleanup stopped and closed nothing more"]
        if handle not in listing[0] or handle in opening[0]:
            continue
        if _activate(wire, handle, listing[1]) != handle:
            notes.append(f"{handle} could not be made active, so it was left open")
            continue
        closed = wire.call("doc_close", {"name": handle, "save_changes": False, "expect_document": handle})
        if closed["failed"]:
            notes.append(f"{handle} was not closed: {closed['text'][:160]}")
    _row, listing = _census(wire)
    if listing is not None and opening[1] in listing[0] and listing[1] != opening[1]:
        _activate(wire, opening[1], listing[1])
        _row, listing = _census(wire)
    if listing is None:
        return notes + [grader.NOT_LISTED]
    return notes + grader.list_differences(opening, listing)


def report(outcomes, out=sys.stdout):
    for outcome in outcomes:
        print(f"{outcome['verdict']:8} {outcome['id']} - {outcome['title']}", file=out)
        for check in outcome["checks"]:
            print(f"    [{check['evidence']}] {check['verdict']}: {check['detail']}", file=out)


def _exit_code(outcomes):
    verdicts = {outcome["verdict"] for outcome in outcomes}
    if grader.FAIL in verdicts:
        return EXIT_FAIL
    return EXIT_NOT_RUN if grader.UNTESTED in verdicts else EXIT_PASS


def _not_blind(reader):
    """The reason a run cannot be graded as cold, from the client's own start record, or ''."""
    return f"the launch was not blind: {reader.not_blind}" if reader.not_blind else ""


def _save(run_dir, name, value):
    with open(os.path.join(run_dir, name), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, indent=1)
        fh.write("\n")


def _load(path):
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def replay(args):
    """Grade a recorded run: a client's event stream and a list of reads, with no session."""
    _task, checks, _hashes = load_pack(args.task)
    checks = grader.renamed(checks, dict(pair.split("=", 1) for pair in args.rename))
    reader = clients.CLIENTS[args.client or "codex"].reader()
    stream = next(p for p in (os.path.join(args.replay, n) for n in ("transcript.jsonl", "events.jsonl"))
                  if os.path.isfile(p))
    with open(stream, encoding="utf-8", errors="replace") as fh:
        calls = [row for line in fh for row in reader.feed(line)]
    reads = [row if "failed" in row else grader.call_row(row["tool"], row["arguments"], row["result"])
             for row in _load(args.replay_reads)]
    opening = grader.document_list(_load(args.replay_opening))
    first = next((row for row in reads if row["tool"] == "doc_get" and not row["failed"]), None)
    owned, unexpected = grader.owned_handles(
        calls, grader.document_list(first["payload"] if first else None), opening)
    outcomes = grader.grade(checks, calls, reads, {"owned": owned}, _not_blind(reader))
    report(outcomes)
    code = _exit_code(outcomes)
    if args.replay_closing:
        differences = grader.list_differences(opening, grader.document_list(_load(args.replay_closing)))
        print("closing document list equals the opening one" if not differences
              else "SESSION DIFFERS:\n  " + "\n  ".join(differences))
        code = EXIT_SESSION_DIFFERS if differences else code
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        _save(args.out, "result.json", {"replayed": stream, "calls": len(calls), "owned": owned,
                                        "unexpected_documents": unexpected, "outcomes": outcomes,
                                        "exit_code": code})
    return code


def run(args):
    task, checks, hashes = load_pack(args.task)
    base, source = wire_client.base_url(args.port, args.url)
    wire = wire_client.Wire(base)
    adapter, exe, version = clients.find(args.client, args.client_path)
    if exe is None:
        sys.exit(f"Not run: {version}.")
    admission, opening, refusal = admit(wire, checks, args.accept_open_work)
    if refusal:
        sys.exit(f"Not run: {refusal}")
    run_dir = os.path.join(args.out or tempfile.mkdtemp(prefix="fusion-cold-"),
                           time.strftime("run-%Y%m%d-%H%M%S"))
    os.makedirs(run_dir)
    cwd = tempfile.mkdtemp(prefix="fusion-cold-child-")
    argv, env, why_not = adapter.launch(exe, wire.mcp, cwd, run_dir, args.model, os.environ)
    if why_not:
        sys.exit(f"Not run: {why_not}")
    # The environment is not recorded: it can hold the client's login.
    admission.update({"pack": {"name": args.task, "sha256": hashes}, "address": {"base": base, "from": source},
                      "client": {"name": adapter.name, "version": version, "model_asked": args.model},
                      "launch": {"argv": argv, "cwd": cwd, "max_calls": checks["max_calls"],
                                 "max_seconds": checks["max_seconds"]}})
    _save(run_dir, "admission.json", admission)
    print(f"Server at {base} ({source}); client {version}; {len(opening[0])} document(s) open.")
    print("Launching one agent with the Fusion tools only. It uses your client login and usage.")
    reader = adapter.reader()
    calls, ended = run_child(reader, argv, env, cwd, task, run_dir, checks["max_calls"], checks["max_seconds"])
    try:
        os.rmdir(cwd)
    except OSError:
        print(f"The agent's working folder was not empty and was left for you to look at: {cwd}")
    untested = _not_blind(reader)
    if reader.said:
        ended["client_said"] = reader.said
    if not untested and not calls:
        with open(os.path.join(run_dir, "client-stderr.log"), encoding="utf-8", errors="replace") as fh:
            said = reader.said or fh.read().strip()[-400:]
        untested = f"the client made no tool call (exit {ended['exit_code']}): {said or 'no message'}"
    reads, owned, unexpected = own_reads(wire, checks, opening, calls)
    _save(run_dir, "reads.json", reads)
    outcomes = grader.grade(checks, calls, reads, {"owned": owned}, untested)
    if not args.keep_open:
        differences = clean_up(wire, owned, opening)
    else:
        differences = [grader.NOT_LISTED] if reads is None else None
    model = reader.model or "not attested: the client did not report the model it ran"
    _save(run_dir, "result.json", dict(admission, ended=ended, owned=owned, unexpected_documents=unexpected,
                                       outcomes=outcomes, model_reported=model, script_calls=wire.calls,
                                       session_differences=differences))
    report(outcomes)
    print(f"Run folder: {run_dir}")
    if unexpected:
        print("Opened during the run and not made by it, so left alone: " + ", ".join(unexpected))
    if differences is None:
        print(f"Left open for inspection: {', '.join(owned) or 'nothing'}. Close them without saving.")
    elif differences:
        print("YOUR SESSION DIFFERS from how it was found:\n  " + "\n  ".join(differences))
        return EXIT_SESSION_DIFFERS
    return _exit_code(outcomes)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, help="the add-in's mcp_port, when it is not found by itself")
    ap.add_argument("--url", help="the server's full URL, in place of --port")
    ap.add_argument("--client", choices=sorted(clients.CLIENTS),
                    help="the agent client; unset means the one found on PATH")
    ap.add_argument("--client-path", help="the client executable, when it is not on PATH")
    ap.add_argument("--model", help="a model for the client; unset means its own default")
    ap.add_argument("--task", default="core", help="the task pack under packs/")
    ap.add_argument("--out", help="where run folders go (default: a new temp folder)")
    ap.add_argument("--accept-open-work", action="store_true",
                    help="run although open documents hold unsaved changes")
    ap.add_argument("--keep-open", action="store_true",
                    help="leave the run's scratch documents open for inspection")
    ap.add_argument("--replay", metavar="RUN", help="grade a recorded run folder, with no session")
    ap.add_argument("--replay-opening", metavar="FILE", help="the doc_get payload read before that run")
    ap.add_argument("--replay-reads", metavar="FILE", help="the reads made after that run")
    ap.add_argument("--replay-closing", metavar="FILE", help="the doc_get payload read after cleanup")
    ap.add_argument("--rename", action="append", default=[], metavar="FIXED=USED",
                    help="replay only: a name the recorded run used in place of the pack's")
    args = ap.parse_args()
    if args.replay and not (args.replay_opening and args.replay_reads):
        ap.error("--replay needs --replay-opening and --replay-reads")
    if args.replay:
        return replay(args)
    try:
        return run(args)
    except OSError as exc:
        print(f"Not finished: the server or the client stopped answering ({exc}). Check which "
              "documents are open in Fusion before you rerun.")
        return EXIT_NOT_RUN


if __name__ == "__main__":
    sys.exit(main())
