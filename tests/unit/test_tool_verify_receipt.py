# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The tool_verify receipt: the source hash + VERIFIED_TOOLS.md stamp binding a green live run to the
exact tool source it exercised.

``source_hash()`` must be OS-portable - relative paths hashed with '/' separators, CRLF
normalized to LF - because the receipt is written on one machine and checked on another (and by
git checkouts with different line-ending config). ``check()`` is the offline gate check_all
runs: red when the receipt is missing, stampless, or the source has moved since the stamp.
"""

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import urllib.request

import pytest

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TESTS_DIR, "live"))
import tool_verify  # noqa: E402
import verify_core  # noqa: E402  probe_capabilities/capability_skip_reason read their tables here
import verify_runner  # noqa: E402  source_hash reads SRC_ROOT/_HERE off ITS namespace, not the facade
import verify_acts_doc  # noqa: E402  canonical document-handle lifecycle rows
import verify_family_switch  # noqa: E402  the beat that writes the Settings file
import verify_acts_cam  # noqa: E402
import verify_acts_model_solids  # noqa: E402
import verify_acts_motion  # noqa: E402
import verify_acts_sketch  # noqa: E402
import verify_acts_model_sweep  # noqa: E402
from verify_families import (  # noqa: E402
    BRACKET_PARAMETERS_PROFILES, FINISHED_BRACKET, DATUM_BENCH_DETAILS,
    DATUM_BENCH_RESIZE, STOCK_VISE, _VISE_SHOWCASE_POSE, _SWARF_FRUSTUM,
    family_names, fixture_steps, showcase_shapes)
import machine_config  # noqa: E402
import preflight  # noqa: E402

_ATTESTATION = {"implementation_fingerprint": "a" * 64, "schema_fingerprint": "b" * 64,
                "load_id": "fixture-load", "session_id": "fixture-session"}
_ADMISSION_PENDING = {tool: "PENDING (no step yet)" for tool in
                      ("doc_get", "sys_get_preferences", "sys_execute_script")}


@pytest.fixture(autouse=True)
def _legacy_runner_fixture(monkeypatch, tmp_path_factory):
    """These wire stubs declare their own tiny act programs without family ownership."""
    monkeypatch.setattr(tool_verify, "FAMILY_PROGRAM", None)
    monkeypatch.setattr(tool_verify, "FAMILY_RECEIPTS", False)
    # The switch beat writes the add-in's Settings file: a run() here never reaches the real one.
    monkeypatch.setattr(tool_verify, "family_switch_smoke",
                        lambda rows, expected_attestation, census, **kw: expected_attestation)
    monkeypatch.setattr(tool_verify.family_switch_smoke, "support_routes", (), raising=False)
    config = json.loads(machine_config.example_text())
    config["tiers"]["native_script"] = True
    config["allow"]["preference_writes"] = True
    config["allow"]["addin_reload"] = True
    path = tmp_path_factory.mktemp("explicit-unit-machine") / "sweep.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv(machine_config.ENV, str(path))
    monkeypatch.setattr(verify_core, "_MACHINE_READ", machine_config.current())
    monkeypatch.setattr(verify_core, "MACHINE", config)


def _preference_reply():
    """Return the published prerequisite shape used by the injected admission wire."""
    groups = {}
    for path, value, _reason in preflight.MEASURED_PREFERENCES:
        group = groups
        for part in path[:-1]:
            group = group.setdefault(part, {})
        group[path[-1]] = {"enum": value}
    return False, {"preferences": groups}


def _registered(names, writes=()):
    writes = set(writes)
    rows = [{"name": name, "annotations": {"readOnlyHint": name not in writes},
             "inputSchema": {"properties": (
                 {"expect_document": {}} if name in writes else {})}}
            for name in names]
    def registered(_health=None, include_rows=False):
        return (list(names), tuple(rows)) if include_rows else list(names)
    return registered


def _known_wire(tool, args):
    if tool == "doc_get":
        active = {"name": "Untitled", "document_id": None, "document_handle": "session:test"}
        return False, {"active": active, "open_documents": [{**active, "is_active": True}],
                       "open_count": 1, "truncated": False}
    if tool == "sys_get_preferences":
        return _preference_reply()
    if tool == "design_get":
        return False, {"feature_count": 1}
    return False, {"n": 1}


def _attested_health(identity=None):
    identity = identity or _ATTESTATION
    return {"server": tool_verify.SERVER_NAME, "version": "t",
            "bound": {"host": "127.0.0.1", "port": verify_core.MACHINE["port"],
                      "mcp_url": "http://127.0.0.1:%d/mcp" % verify_core.MACHINE["port"]},
            "session_id": identity["session_id"],
            "attestation": {"complete": True, "loaded_matches_source": True,
                            "implementation_fingerprint": identity["implementation_fingerprint"],
                            "schema_fingerprint": identity["schema_fingerprint"],
                            "load_id": identity["load_id"]}}


def _reloaded_attestation():
    return dict(_ATTESTATION, load_id="fixture-load-2", session_id="fixture-session-2")


def _tree(tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    return str(tmp_path)


class TestSourceHash:
    def test_served_guidance_change_or_removal_invalidates_hash(self, tmp_path):
        rel = "guidance/parametric_cad_design.json"
        root = _tree(tmp_path, {"a.py": b"x = 1\n", rel: b'{"rules": []}\n'})
        before = tool_verify.source_hash(root)
        (tmp_path / rel).write_bytes(b'{"rules": ["changed"]}\n')
        changed = tool_verify.source_hash(root)
        assert changed != before
        (tmp_path / rel).unlink()
        assert tool_verify.source_hash(root) not in (before, changed)

    def test_same_tree_hashes_identically(self, tmp_path):
        root = _tree(tmp_path, {"a.py": b"x = 1\n", "sub/b.py": b"y = 2\n"})
        assert tool_verify.source_hash(root) == tool_verify.source_hash(root)

    def test_content_change_changes_hash(self, tmp_path):
        root = _tree(tmp_path, {"a.py": b"x = 1\n"})
        before = tool_verify.source_hash(root)
        (tmp_path / "a.py").write_bytes(b"x = 2\n")
        assert tool_verify.source_hash(root) != before

    def test_rename_changes_hash(self, tmp_path):
        a = _tree(tmp_path / "one", {"a.py": b"x = 1\n"})
        b = _tree(tmp_path / "two", {"b.py": b"x = 1\n"})
        assert tool_verify.source_hash(a) != tool_verify.source_hash(b)

    def test_crlf_and_lf_hash_identically(self, tmp_path):
        crlf = _tree(tmp_path / "crlf", {"a.py": b"x = 1\r\nif x:\r\n    pass\r\n"})
        lf = _tree(tmp_path / "lf", {"a.py": b"x = 1\nif x:\n    pass\n"})
        assert tool_verify.source_hash(crlf) == tool_verify.source_hash(lf)

    def test_non_py_and_pycache_are_ignored(self, tmp_path):
        root = _tree(tmp_path, {"a.py": b"x = 1\n"})
        before = tool_verify.source_hash(root)
        _tree(tmp_path, {"notes.md": b"prose\n", "data.json": b"{}\n",
                         "__pycache__/a.cpython-312.pyc": b"\x00",
                         "sub/__pycache__/b.py": b"cached = True\n"})
        assert tool_verify.source_hash(root) == before

    def test_paths_hash_with_forward_slashes(self, tmp_path):
        # Pins the separator normalization: the digest must be computable with '/' joined
        # relative paths regardless of the OS the receipt was written on.
        content = b"z = 3\n"
        root = _tree(tmp_path, {"sub/deep/c.py": content})
        expected = hashlib.sha256(b"sub/deep/c.py" + b"\0" + content + b"\0").hexdigest()
        assert tool_verify.source_hash(root) == expected


class TestFilletRadiusWitness:
    @pytest.mark.parametrize("make_rows,key", [
        (verify_acts_sketch._fillet_radius_rows, "fillet_reported_radius"),
        (verify_acts_model_sweep._tangent_path_rows, "tp_fillet_reported_radius")])
    def test_authored_fillet_rows_require_numeric_radius(self, monkeypatch, make_rows, key):
        monkeypatch.setitem(verify_core._RECALL, key, None)
        checks = []
        for tool, args, check, _save in make_rows():
            if tool != "sketch_edit_curve":
                continue
            args = args({"fillet_doc": "session:test", "tp_doc": "session:test"}) if callable(args) else args
            if args.get("action") == "fillet" and args.get("radius") == 20:
                checks.append(check)
        assert len(checks) == 1
        check = checks[0]
        assert isinstance(check, verify_acts_model_sweep._FilletRadiusRefusal)
        assert check.missing("requested 20 mm, solved None mm. REMAINS arc:0 line:0 line:1 sketch_get")
        assert not check.missing("requested 20 mm, solved 18.7766 mm. REMAINS arc:0 line:0 line:1 sketch_get")
        assert verify_core._RECALL[key] == 18.7766

    @pytest.mark.parametrize("reported", ["None", "nan", "inf", "-1", "0"])
    def test_unread_radius_refusal_cannot_reuse_a_prior_report(self, monkeypatch, reported):
        monkeypatch.setitem(verify_core._RECALL, "fillet_reported_radius", 18.7766)
        check = verify_acts_model_sweep._FilletRadiusRefusal("fillet_reported_radius")
        text = f"requested 20 mm, solved {reported} mm. REMAINS arc:0 line:0 line:1 sketch_get"
        assert check.missing(text)
        assert "fillet_reported_radius" not in verify_core._RECALL

    @pytest.mark.parametrize("reported", [18.7766, 12.0])
    def test_independent_sketch_read_rejects_wrong_numeric_report(self, monkeypatch, reported):
        monkeypatch.setitem(verify_core._RECALL, "fillet_reported_radius", None)
        monkeypatch.setitem(verify_core._RECALL, "fillet_before", {"entities": []})
        check = verify_acts_model_sweep._FilletRadiusRefusal("fillet_reported_radius")
        assert not check.missing(
            f"requested 20 mm, solved {reported} mm. REMAINS arc:0 line:0 line:1 sketch_get")
        payload = {
            "units": "mm", "truncated": False, "frame": {}, "is_fully_constrained": False,
            "counts": {"lines": 2, "arcs": 1}, "constraint_count": 2,
            "dimension_count": 0, "dimensions": [], "profile_count": 0, "profiles": [],
            "constraints": [{"type": "tangent", "entities": ["arc:0", "line:" + str(i)]}
                            for i in (0, 1)],
            "entities": [
                {"id": "line:0", "type": "line", "start": {"x": 10, "y": -30},
                 "end": {"x": 214.6263, "y": -30}},
                {"id": "line:1", "type": "line", "start": {"x": 224.5797, "y": -32.8623},
                 "end": {"x": 260, "y": -55}},
                {"id": "arc:0", "type": "arc", "center": {"x": 214.6263, "y": -48.7766},
                 "radius": 18.7766}]}
        if reported == 18.7766:
            assert verify_acts_sketch._solved_fillet_effect()(payload)
        else:
            with pytest.raises(AssertionError, match="solved fillet radius"):
                verify_acts_sketch._solved_fillet_effect()(payload)

    @pytest.mark.parametrize("reported", [4.0, 5.0])
    def test_tangent_path_read_checks_the_report_before_deriving_volume(self, monkeypatch, reported):
        monkeypatch.setitem(verify_core._RECALL, "tp_fillet_reported_radius", None)
        check = verify_acts_model_sweep._FilletRadiusRefusal("tp_fillet_reported_radius")
        assert not check.missing(
            f"requested 20 mm, solved {reported} mm. REMAINS arc:0 line:0 line:1 sketch_get")
        payload = {"units": "mm", "counts": {"lines": 2, "arcs": 1}, "entities": [
            {"id": "line:0", "start": {"x": -5, "y": -4}, "end": {"x": 0, "y": -4}},
            {"id": "line:1", "start": {"x": 4, "y": 0}, "end": {"x": 4, "y": 5}},
            {"id": "arc:0", "center": {"x": 0, "y": 0}, "radius": 4}]}
        if reported == 4.0:
            assert verify_acts_model_sweep._tangent_path_expected(payload)["end"] == [4, 5, 0]
        else:
            with pytest.raises(AssertionError, match="reported fillet radius"):
                verify_acts_model_sweep._tangent_path_expected(payload)


@pytest.mark.parametrize("kind", ["tool", "post"])
@pytest.mark.parametrize("message,expected", [
    ("Search was capped; absence is unknown", True),
    ("Post not found. Search was capped", False),
    ("Unknown post name", False)])
def test_capped_miss_diagnostic_requires_unknown_absence(kind, message, expected):
    script = ast.parse(verify_acts_cam._lookup_library_args({})["script"])
    assignments = [node for node in ast.walk(script) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Subscript)
                           and isinstance(target.slice, ast.Constant)
                           and target.slice.value == kind + "_missing_name_unknown"
                           for target in node.targets)]
    assert len(assignments) == 1
    expression = compile(ast.Expression(assignments[0].value), "cap diagnostic", "eval")
    result = eval(expression, {kind + "_unknown": {"is_error": True, "payload": message},
                               "after_unknown": {}, "before_post": {}})
    assert result is expected


class TestHarnessSideOfTheHash:
    """Which tests/live modules the receipt binds: the SWEEP's, and only those."""

    @staticmethod
    def _rig(tmp_path, monkeypatch):
        src = _tree(tmp_path / "src", {"a.py": b"x = 1\n"})
        live = tmp_path / "live"
        live.mkdir()
        (live / "measure_api.py").write_bytes(b"ROWS = []\n")
        (live / "verify_core.py").write_bytes(b"EXCLUDED = {}\n")
        repo = tmp_path / "repo"
        _tree(repo, {"Fusion-Essentials.py": b"from . import commands\n",
                     "lib/loaded_attestation.py": b"def begin(): pass\n",
                     "commands/updateTools/entry.py": b"def replace_with_library_tool(): pass\n"})
        monkeypatch.setattr(verify_runner, "SRC_ROOT", src)
        monkeypatch.setattr(verify_runner, "REPO_ROOT", str(repo))
        monkeypatch.setattr(verify_runner, "_HERE", str(live))
        return src, live

    def test_capture_bootstrap_and_helper_are_bound_into_the_source_hash(
            self, tmp_path, monkeypatch):
        src, _live = self._rig(tmp_path, monkeypatch)
        before = tool_verify.source_hash(src)
        helper = Path(verify_runner.REPO_ROOT) / "lib/loaded_attestation.py"
        helper.write_bytes(b"def begin(): return False\n")
        assert tool_verify.source_hash(src) != before

    def test_unjudged_gui_command_edit_leaves_the_receipt_current(self, tmp_path, monkeypatch):
        src, _live = self._rig(tmp_path, monkeypatch)
        before = tool_verify.source_hash(src)
        command = Path(verify_runner.REPO_ROOT) / "commands/updateTools/entry.py"
        command.write_bytes(b"def replace_with_library_tool(): return False\n")
        assert tool_verify.source_hash(src) == before

    def test_a_facts_harness_edit_leaves_the_hash_where_a_predicate_edit_moves_it(
            self, tmp_path, monkeypatch):
        # measure_api.py judges no step of the sweep, so a row-only edit to it must not force a
        # seven-minute re-run; verify_core.py holds the predicates the receipt exists to bind.
        src, live = self._rig(tmp_path, monkeypatch)
        before = tool_verify.source_hash(src)
        (live / "measure_api.py").write_bytes(b"ROWS = [{'id': 'new-row'}]\n")
        assert tool_verify.source_hash(src) == before
        (live / "verify_core.py").write_bytes(b"EXCLUDED = {'model_loft': 'skipped'}\n")
        assert tool_verify.source_hash(src) != before

    def test_no_module_the_sweep_imports_is_left_out_of_the_hash(self):
        # The excluded names are safe only while the sweep does not read them: a predicate reached
        # through one of these would then ride under a green receipt that never saw it change.
        skipped = {fn[:-3] for fn in verify_runner._NOT_THE_SWEEP}
        importers = []
        for fn in sorted(os.listdir(tool_verify._HERE)):
            if not fn.endswith(".py") or fn in verify_runner._NOT_THE_SWEEP:
                continue
            with open(os.path.join(tool_verify._HERE, fn), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=fn)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                importers += [f"{fn} imports {n}" for n in names if n in skipped]
        assert not importers, ("the receipt skips a module the sweep reads: "
                               + ", ".join(importers))


class TestVerifiedReceipt:
    _LEDGER = [("appearance_set", "covered"),
               ("doc_open", "skipped: opens cloud files"),
               ("model_loft", "PENDING (no step yet)")]

    def test_round_trip_write_then_check_is_current(self, tmp_path, capsys):
        root = _tree(tmp_path / "src", {"a.py": b"x = 1\n"})
        receipt = str(tmp_path / "VERIFIED_TOOLS.md")
        tool_verify.write_verified(self._LEDGER, "2704.1.23", "2026-07-11",
                                   tool_verify.source_hash(root), path=receipt, attestation=_ATTESTATION)
        assert tool_verify.check(root=root, verified_path=receipt, attestation=_ATTESTATION) == 0
        assert "2026-07-11" in capsys.readouterr().out

    def test_check_goes_red_when_source_changes_after_stamp(self, tmp_path, capsys):
        root = _tree(tmp_path / "src", {"a.py": b"x = 1\n"})
        receipt = str(tmp_path / "VERIFIED_TOOLS.md")
        tool_verify.write_verified(self._LEDGER, "2704.1.23", "2026-07-11",
                                   tool_verify.source_hash(root), path=receipt, attestation=_ATTESTATION)
        (tmp_path / "src" / "a.py").write_bytes(b"x = 2\n")
        assert tool_verify.check(root=root, verified_path=receipt, attestation=_ATTESTATION) == 1
        out = capsys.readouterr().out
        assert "changed since" in out and "tool_verify.py" in out

    def test_check_goes_red_without_a_receipt(self, tmp_path, capsys):
        root = _tree(tmp_path / "src", {"a.py": b"x = 1\n"})
        assert tool_verify.check(root=root, verified_path=str(tmp_path / "VERIFIED_TOOLS.md")) == 1
        assert "tool_verify.py" in capsys.readouterr().out

    def test_check_goes_red_when_the_loaded_stamp_is_missing_or_changed(self, tmp_path, capsys):
        root = _tree(tmp_path / "src", {"a.py": b"x = 1\n"})
        receipt = str(tmp_path / "VERIFIED_TOOLS.md")
        tool_verify.write_verified(self._LEDGER, "2704.1.23", "fixture",
                                   tool_verify.source_hash(root), path=receipt,
                                   attestation=_ATTESTATION)
        original = Path(receipt).read_text(encoding="utf-8")
        Path(receipt).write_text("\n".join(
            line for line in original.splitlines() if not line.startswith("Loaded:")) + "\n",
            encoding="utf-8")
        assert tool_verify.check(root=root, verified_path=receipt) == 1
        Path(receipt).write_text(original, encoding="utf-8")
        changed = dict(_ATTESTATION, schema_fingerprint="c" * 64)
        assert tool_verify.check(root=root, verified_path=receipt, attestation=changed) == 1
        output = capsys.readouterr().out
        assert "source/loaded stamp" in output and "differs" in output

    def test_check_goes_red_on_a_stampless_receipt(self, tmp_path, capsys):
        root = _tree(tmp_path / "src", {"a.py": b"x = 1\n"})
        receipt = tmp_path / "VERIFIED_TOOLS.md"
        receipt.write_text("# Live tool verification\n\nno stamp here\n", encoding="utf-8")
        assert tool_verify.check(root=root, verified_path=str(receipt)) == 1
        assert "stamp" in capsys.readouterr().out

    def test_receipt_carries_stamp_counts_and_ledger_rows(self, tmp_path):
        root = _tree(tmp_path / "src", {"a.py": b"x = 1\n"})
        receipt = str(tmp_path / "VERIFIED_TOOLS.md")
        src_hash = tool_verify.source_hash(root)
        tool_verify.write_verified(self._LEDGER, "2704.1.23", "2026-07-11", src_hash, path=receipt, attestation=_ATTESTATION)
        with open(receipt, encoding="utf-8") as fh:
            text = fh.read()
        m = tool_verify._STAMP_RE.search(text)
        assert m and m.groups() == (src_hash, "2704.1.23", "2026-07-11")
        assert "1 covered / 0 called / 0 refusals-only / 1 skipped(reason) / 1 pending" in text
        assert "| appearance_set | covered |" in text
        assert "| doc_open | skipped: opens cloud files |" in text
        assert "| model_loft | PENDING (no step yet) |" in text

    def test_bare_ok_row_lands_in_called_and_a_value_row_in_covered(self, tmp_path):
        # The split the receipt exists to make visible: 'covered' counts only the tools whose step
        # read a value off the payload; a bare-ok tool is counted and labelled separately.
        root = _tree(tmp_path / "src", {"a.py": b"x = 1\n"})
        receipt = str(tmp_path / "VERIFIED_TOOLS.md")
        tool_verify.write_verified([("model_extrude", "covered"), ("model_create_component", "called")],
                                   "2704.1.23", "2026-07-11", tool_verify.source_hash(root),
                                   path=receipt, attestation=_ATTESTATION)
        with open(receipt, encoding="utf-8") as fh:
            text = fh.read()
        assert "1 covered / 1 called / 0 refusals-only / 0 skipped(reason) / 0 pending" in text
        assert "| model_extrude | covered |" in text
        assert "| model_create_component | called |" in text
        # both terms are defined in the header, or the numbers are unreadable
        assert "- covered:" in text and "- called:" in text

    def test_a_parked_row_carries_its_reason_and_still_counts_as_called(self, tmp_path):
        # A parked step's reason otherwise lives only in a source comment: the receipt would show a
        # plain 'called' and no reader could tell a missing predicate from a deliberately held one.
        # The reason is RENDERING, not a third bucket - the count line must not drift from it.
        root = _tree(tmp_path / "src", {"a.py": b"x = 1\n"})
        receipt = str(tmp_path / "VERIFIED_TOOLS.md")
        tool_verify.write_verified([("model_extrude", "covered"),
                                    ("model_draft", "called (effect read unreadable - DR-1)")],
                                   "2704.1.23", "2026-07-11", tool_verify.source_hash(root),
                                   path=receipt, attestation=_ATTESTATION)
        with open(receipt, encoding="utf-8") as fh:
            text = fh.read()
        assert "1 covered / 1 called / 0 refusals-only / 0 skipped(reason) / 0 pending" in text
        assert "| model_draft | called (effect read unreadable - DR-1) |" in text


class _Clock:
    """The time module as the runner sees it, with one elapsed reading: the first time() read is the
    run's start and every later one is `elapsed` past it."""

    def __init__(self, elapsed):
        self.elapsed, self.reads = elapsed, 0
        self.performance = 0.0

    def time(self):
        self.reads += 1
        return 0.0 if self.reads == 1 else self.elapsed

    def sleep(self, seconds):
        pass

    def perf_counter(self):
        self.performance += 0.01
        return self.performance

    def strftime(self, fmt):
        return "2026-07-11"


class _Harness:
    """run() over a stubbed wire, clock and results directory. What each test varies is the act
    program, the run id and what the wire answers; everything else is held still."""

    ACTS = [("ACT A", None, [("a_get", {}, "ok", ("k", lambda p: p["n"]))], []),
            # ACT B's ARGUMENTS read a ctx value ACT A saved - the thing a chunk boundary has to
            # carry, and the one whose loss shows up as a blocked step rather than an exception.
            ("ACT B", None,
             [("b_get", lambda ctx: {"x": ctx["k"]}, lambda p: p["n"] == 1, None)], [])]

    def __init__(self, monkeypatch, tmp_path, acts=None, elapsed=1.0, document="Untitled",
                 document_handle="session:fixture-document", features=7, src_hash="0" * 64,
                 answer=None, poll_after=None):
        self.wrote, self.seen = {}, []
        self.document, self.document_handle = document, document_handle
        self.features, self.answer = features, answer
        monkeypatch.setattr(tool_verify, "call", self._call)
        monkeypatch.setattr(verify_runner, "time", _Clock(elapsed))
        monkeypatch.setattr(verify_runner, "RESULTS_DIR", str(tmp_path))
        monkeypatch.setattr(tool_verify, "health_gate", _attested_health)
        names = {step[0] for _name, pre, narrative, fallback in (acts or self.ACTS)
                 for step in list(narrative) + list(fallback or []) + ([pre] if pre else [])}
        names.update({"doc_get", "design_get", "sys_get_preferences", "sys_execute_script"})
        monkeypatch.setattr(tool_verify, "registered_tools", _registered(sorted(names)))
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: src_hash)
        monkeypatch.setattr(tool_verify, "write_verified", self._write)
        reloaded = dict(_ATTESTATION, load_id="fixture-load-2",
                        session_id="fixture-session-2")
        monkeypatch.setattr(tool_verify, "reload_smoke",
                            lambda rows, notes, valued=None, **kw:
                            (self.seen.append(("reload beat", {})), reloaded)[1])
        monkeypatch.setattr(tool_verify.reload_smoke, "support_routes", (), raising=False)
        monkeypatch.setattr(tool_verify, "POLL_AFTER", poll_after or {})
        monkeypatch.setattr(tool_verify, "EXCLUDED", {})
        monkeypatch.setattr(tool_verify, "STORY", {})
        monkeypatch.setattr(tool_verify, "ACT_NEEDS", {})
        monkeypatch.setattr(tool_verify, "ACTS", acts if acts is not None else self.ACTS)
        monkeypatch.setattr(tool_verify, "FAMILY_PROGRAM", None)
        tool_verify._RECALL.clear()

    def _call(self, tool, args):
        self.seen.append((tool, dict(args)))
        if tool == "doc_get":
            active = {"name": self.document, "document_id": None,
                      "document_handle": self.document_handle}
            return False, {"active": active, "open_documents": [{**active, "is_active": True}],
                           "open_count": 1, "truncated": False}
        if tool == "sys_get_preferences":
            return _preference_reply()
        if tool == "design_get":
            return False, {"feature_count": self.features}
        return False, self.answer if self.answer is not None else {"n": 1}

    def _write(self, rows, version, date, src_hash, path=None, notes=None, act_modes=None, attestation=None):
        self.wrote.update(ledger=dict(rows), src_hash=src_hash, attestation=attestation,
                          act_modes=list(act_modes or []))
        return "VERIFIED_TOOLS.md"

    def tools_called(self):
        return [tool for tool, _args in self.seen]

    def run(self, **kw):
        return tool_verify.run(write_json=False, **kw)


class TestTheReceiptContract:
    """What a receipt depends on: the steps, and nothing else. A run is timed and the timing is
    reported, but a long run is a slow run - not a failed one."""

    def test_a_run_far_longer_than_a_shell_call_still_stamps(self, monkeypatch, tmp_path, capsys):
        # the sweep grew past 600 s of wall clock; capping it would refuse a receipt for a run whose
        # every step passed, which is the state this contract exists to end.
        h = _Harness(monkeypatch, tmp_path, elapsed=4000.0)
        assert h.run() == 0 and h.wrote["ledger"] == {
            "a_get": "called", "b_get": "covered", "design_get": "PENDING (no step yet)", **_ADMISSION_PENDING}
        out = capsys.readouterr().out
        assert "OVER BUDGET" not in out and "4000s" in out

    def test_a_failing_step_is_what_blocks_the_receipt(self, monkeypatch, tmp_path, capsys):
        acts = [("ACT A", None, [("a_get", {}, lambda p: p["n"] == 99, None)], [])]
        h = _Harness(monkeypatch, tmp_path, acts=acts)
        assert h.run() == 1 and not h.wrote
        assert "NOT rewritten" in capsys.readouterr().out

    def test_a_failed_poll_stops_before_act_completion_and_later_acts(
            self, monkeypatch, tmp_path):
        acts = [
            ("ACT P", None, [("a_get", {}, "ok", None)], []),
            ("ACT LATER", None, [("b_get", {}, "ok", None)], []),
        ]
        h = _Harness(monkeypatch, tmp_path, acts=acts, poll_after={
            "ACT P": {"narrative": "Mill", "fallback": []}})
        monkeypatch.setattr(
            tool_verify, "poll_generation",
            lambda rows, notes, setup, valued=None, **kw:
            rows.append(("cam_get_status", "FAIL", "generation failed")))
        monkeypatch.setattr(tool_verify.poll_generation, "support_routes", (), raising=False)
        assert h.run(run_id="poll-fail") == 1
        assert "b_get" not in h.tools_called() and "reload beat" not in h.tools_called()
        assert not Path(tool_verify.run_state_path("poll-fail")).exists()

    def test_an_acts_own_poll_budget_reaches_the_generation_poll(self, monkeypatch, tmp_path):
        # a census act launches sixteen operations at once; the runner's default budget would end
        # the poll while the work is still running and fail an act that is only slow.
        polled = []
        monkeypatch.setattr(tool_verify, "poll_generation",
                            lambda rows, notes, setup, valued=None, max_polls=40,
                            document_pin=None:
                            polled.append((setup, max_polls, document_pin)))
        monkeypatch.setattr(tool_verify.poll_generation, "support_routes", (), raising=False)
        acts = [("ACT P", None, [("a_get", {}, "ok", None)], []),
                ("ACT Q", None, [("a_get", {}, "ok", None)], [])]
        h = _Harness(monkeypatch, tmp_path, acts=acts, poll_after={
            "ACT P": {"narrative": "Mill", "fallback": [], "max_polls": 90},
            "ACT Q": {"narrative": "Turn", "fallback": []}})
        h.run()
        assert polled == [("Mill", 90, None), ("Turn", 40, None)]


class TestResumableRun:
    """A run walked in CHUNKS, because the shell a chunk is launched from is killed at 600 s. Each
    chunk saves what the next one reads; the receipt is stamped from the union, once."""

    def test_a_chunk_saves_the_program_it_walked_and_stamps_nothing(self, monkeypatch, tmp_path,
                                                                    capsys):
        h = _Harness(monkeypatch, tmp_path)
        assert h.run(run_id="r1", acts_spec="ACT A") == 0
        assert not h.wrote, "a chunk that has not walked the program cannot stamp its receipt"
        state = tool_verify.load_run_state("r1")
        assert state["acts_done"] == ["ACT A"] and state["ctx"] == {"k": 1}
        assert state["rows"] == [["a_get", "pass", ""]]
        # the document is saved as the chunk leaves it, so the next chunk can refuse another one
        assert state["document"]["name"] == "Untitled"
        assert "--run r1 --resume" in capsys.readouterr().out

    def test_a_chunk_persists_home_and_legacy_state_cannot_resume(
            self, monkeypatch, tmp_path, capsys):
        first = _Harness(monkeypatch, tmp_path)
        monkeypatch.setattr(
            tool_verify, "registered_tools", _registered(
                sorted({"a_get", "b_get", "design_get", *_ADMISSION_PENDING}), {"a_get"}))
        assert first.run(run_id="r1", acts_spec="ACT A") == 0
        state = tool_verify.load_run_state("r1")
        assert state["home_document"]["document_handle"] == "session:fixture-document"
        state.pop("home_document")
        tool_verify.save_run_state("r1", state)

        second = _Harness(monkeypatch, tmp_path)
        assert second.run(run_id="r1", resume=True) == 1
        assert "b_get" not in second.tools_called()
        assert "no original active document identity" in capsys.readouterr().out

    def test_the_resume_carries_the_ctx_and_stamps_from_the_union(self, monkeypatch, tmp_path):
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        second = _Harness(monkeypatch, tmp_path)
        assert second.run(run_id="r1", resume=True) == 0
        # only the act that had not run is walked...
        assert ("b_get", {"x": 1}) in second.seen and "a_get" not in second.tools_called()
        # ...and the receipt carries BOTH acts' tools, from the union of the two chunks' ledgers
        assert second.wrote["ledger"] == {"a_get": "called", "b_get": "covered", "design_get": "PENDING (no step yet)", **_ADMISSION_PENDING}
        # the reload beat belongs to the whole run: the first chunk must not fire it, the last must
        assert "reload beat" not in first.tools_called()
        assert "reload beat" in second.tools_called()

    def test_a_same_handle_survives_document_rename(self, monkeypatch, tmp_path):
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        second = _Harness(monkeypatch, tmp_path, document="Renamed document", features=8)
        assert second.run(run_id="r1", resume=True) == 0
        assert second.wrote["ledger"] == {"a_get": "called", "b_get": "covered", "design_get": "PENDING (no step yet)", **_ADMISSION_PENDING}

    def test_a_resume_with_missing_current_handle_is_refused(self, monkeypatch, tmp_path, capsys):
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        second = _Harness(monkeypatch, tmp_path, document_handle=None)
        assert second.run(run_id="r1", resume=True) == 1
        assert not second.wrote and "no complete document handle" in capsys.readouterr().out

    def test_a_resume_after_the_source_moved_is_refused(self, monkeypatch, tmp_path, capsys):
        # the receipt binds ONE hash: a chunk judged under different source would ride under a stamp
        # no chunk was measured against.
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        second = _Harness(monkeypatch, tmp_path, src_hash="f" * 64)
        assert second.run(run_id="r1", resume=True) == 1
        assert "b_get" not in second.tools_called() and not second.wrote
        assert "tool source changed" in capsys.readouterr().out

    def test_a_resume_against_another_document_is_refused(self, monkeypatch, tmp_path, capsys):
        # the remaining acts stand on the world the earlier ones built; run them against a fresh
        # document and every read is against geometry that was never made.
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        second = _Harness(monkeypatch, tmp_path, document="Untitled",
                          document_handle="session:other-document")
        assert second.run(run_id="r1", resume=True) == 1
        assert "b_get" not in second.tools_called() and not second.wrote
        out = capsys.readouterr().out
        assert "not the active one" in out and "session:other-document" in out

    @pytest.mark.parametrize("bad_handle", ["session:a b", "session:", "session: ", True, 1,
                                             {"handle": "session:valid"}],
                             ids=["internal-whitespace", "bare-prefix", "trailing-whitespace",
                                  "boolean", "integer", "mapping"])
    def test_malformed_equal_handles_are_refused_before_remaining_acts(
            self, monkeypatch, tmp_path, capsys, bad_handle):
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        state = tool_verify.load_run_state("r1")
        state["document"]["document_handle"] = bad_handle
        tool_verify.save_run_state("r1", state)
        second = _Harness(monkeypatch, tmp_path, document_handle=bad_handle)
        assert second.run(run_id="r1", resume=True) == 1
        assert "b_get" not in second.tools_called() and not second.wrote
        assert "no complete document handle" in capsys.readouterr().out

    def test_a_legacy_identity_without_handle_is_refused(self, monkeypatch, tmp_path, capsys):
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        state = tool_verify.load_run_state("r1")
        state["document"] = {"name": "Untitled", "document_id": None, "feature_count": 7}
        tool_verify.save_run_state("r1", state)
        second = _Harness(monkeypatch, tmp_path)
        assert second.run(run_id="r1", resume=True) == 1
        assert "b_get" not in second.tools_called() and not second.wrote
        assert "no complete document handle" in capsys.readouterr().out

    def test_a_resume_of_an_unknown_run_is_refused_naming_the_file(self, monkeypatch, tmp_path,
                                                                   capsys):
        h = _Harness(monkeypatch, tmp_path)
        assert h.run(run_id="nosuch", resume=True) == 1
        assert "run-nosuch.json" in capsys.readouterr().out and not h.wrote

    @staticmethod
    def _spy_saves(monkeypatch):
        """Every state a chunk saves, in order - the first is what a kill after act one leaves."""
        saved, real = [], verify_runner.save_run_state
        monkeypatch.setattr(verify_runner, "save_run_state",
                            lambda run_id, state: (saved.append(dict(state)), real(run_id, state))[1])
        return saved

    def test_a_first_chunk_saves_the_document_at_its_very_first_boundary(self, monkeypatch,
                                                                        tmp_path):
        # The false-receipt path this closes: a --run walk with no --acts is killed by the shell at
        # 600 s, so it never reaches its own ending. Every boundary save it made in the meantime has
        # to carry the document, or the resume has nothing to refuse a different one against.
        saved = self._spy_saves(monkeypatch)
        h = _Harness(monkeypatch, tmp_path)
        h.run(run_id="r1")
        assert saved, "a --run walk saves after every act"
        assert (saved[0].get("document") or {}).get("name") == "Untitled"
        assert all((s.get("document") or {}).get("name") == "Untitled" for s in saved)

    def test_that_killed_chunks_state_refuses_a_resume_in_another_document(self, monkeypatch,
                                                                          tmp_path, capsys):
        # the same state, resumed where the sweep's document is NOT the active one: the acts that
        # remain would run against a world nothing built, so the chunk must change nothing.
        saved = self._spy_saves(monkeypatch)
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1")
        verify_runner.save_run_state("r1", dict(saved[0], complete=False))   # as a kill left it
        second = _Harness(monkeypatch, tmp_path, document="A Totally Different Document",
                          document_handle="session:other-document")
        assert second.run(run_id="r1", resume=True) == 1
        assert not second.wrote and "b_get" not in second.tools_called()
        assert "session:other-document" in capsys.readouterr().out

    def test_a_state_with_no_document_identity_is_refused(self, monkeypatch, tmp_path, capsys):
        # the belt to that brace: a state saved before any boundary (or by an older run) names no
        # document, and "nothing to compare" must read as a refusal, not as a pass.
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        verify_runner.save_run_state("r1", dict(tool_verify.load_run_state("r1"), document=None))
        second = _Harness(monkeypatch, tmp_path)
        assert second.run(run_id="r1", resume=True) == 1
        assert not second.wrote and "no complete document handle" in capsys.readouterr().out

    def test_a_chunk_that_drove_no_act_says_so_on_the_stamp_line(self, monkeypatch, tmp_path,
                                                                capsys):
        # a chunk killed after its LAST boundary save leaves every act done and no completion flag:
        # the resume walks nothing, fires the reload beat and stamps from the saved ledger. It may
        # stamp - the acts did run - but the line that announces the receipt has to say what this
        # invocation contributed.
        saved = self._spy_saves(monkeypatch)
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1")
        verify_runner.save_run_state("r1", dict(saved[-1], complete=False))  # as a kill left it
        second = _Harness(monkeypatch, tmp_path)
        assert second.run(run_id="r1", resume=True) == 0 and second.wrote
        out = capsys.readouterr().out
        assert "0 acts driven this chunk - the reload beat only" in out
        assert "a_get" not in second.tools_called() and "b_get" not in second.tools_called()

    def test_a_resume_of_a_finished_run_is_refused(self, monkeypatch, tmp_path, capsys):
        # every act of a spent id is already done, so a resume would walk nothing and stamp the
        # receipt from the saved ledger - a receipt for a run that drove nothing this time.
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1")
        assert first.wrote
        second = _Harness(monkeypatch, tmp_path)
        assert second.run(run_id="r1", resume=True) == 1
        assert not second.wrote and "already walked the whole program" in capsys.readouterr().out

    def test_a_development_walk_reruns_the_named_act_with_the_saved_ctx(self, monkeypatch,
                                                                       tmp_path, capsys):
        # iterating on one act: the saved world's ctx feeds ACT B's arguments, only ACT B runs,
        # nothing stamps, and the state is left exactly as the chunk saved it.
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        before = tool_verify.load_run_state("r1")
        second = _Harness(monkeypatch, tmp_path)
        assert second.run(run_id="r1", resume=True, acts_spec="ACT B") == 0
        assert ("b_get", {"x": 1}) in second.seen and "a_get" not in second.tools_called()
        assert not second.wrote and "reload beat" not in second.tools_called()
        assert tool_verify.load_run_state("r1") == before
        assert "development walk" in capsys.readouterr().out

    def test_a_development_walk_runs_an_act_already_done_and_tolerates_a_moved_source(
            self, monkeypatch, tmp_path):
        # the act was edited since the chunk ran it: the hash moved, and that is the point.
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        second = _Harness(monkeypatch, tmp_path, src_hash="f" * 64)
        assert second.run(run_id="r1", resume=True, acts_spec="ACT A") == 0
        assert "a_get" in second.tools_called() and not second.wrote
        assert tool_verify.load_run_state("r1")["acts_done"] == ["ACT A"]

    def test_a_development_walk_in_another_document_is_still_refused(self, monkeypatch, tmp_path,
                                                                     capsys):
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        second = _Harness(monkeypatch, tmp_path, document="Something Else",
                          document_handle="session:other-document")
        assert second.run(run_id="r1", resume=True, acts_spec="ACT B") == 1
        assert "b_get" not in second.tools_called() and "not the active one" in capsys.readouterr().out

    def test_starting_a_run_id_that_holds_state_is_refused_before_any_act(self, monkeypatch,
                                                                         tmp_path, capsys):
        # the trap: --run <id> --acts without --resume on a used id ran the acts with an empty ctx
        # and rewrote the saved progress; now it stops before the first wire call.
        first = _Harness(monkeypatch, tmp_path)
        first.run(run_id="r1", acts_spec="ACT A")
        before = tool_verify.load_run_state("r1")
        second = _Harness(monkeypatch, tmp_path)
        assert second.run(run_id="r1", acts_spec="ACT B") == 1
        assert second.seen == [] and not second.wrote
        assert tool_verify.load_run_state("r1") == before
        assert "already holds state" in capsys.readouterr().out

    def test_a_single_invocation_is_unchanged_by_the_run_id_machinery(self, monkeypatch, tmp_path):
        # the path everyone runs: no run id, no state file, one stamp at the end.
        h = _Harness(monkeypatch, tmp_path)
        assert h.run() == 0 and h.wrote["ledger"] == {
            "a_get": "called", "b_get": "covered", "design_get": "PENDING (no step yet)", **_ADMISSION_PENDING}
        assert not os.path.exists(tool_verify.run_state_path("r1"))

    def test_a_value_a_predicate_recalls_survives_the_boundary(self, monkeypatch, tmp_path):
        # _RECALL is module state, not ctx: a predicate that recalls a name saved two acts ago reads
        # nothing in a fresh process unless the chunk carried it.
        acts = [("ACT A", None,
                 [("a_get", {}, "ok", ("k", tool_verify._recall("landed", lambda p: p["n"])))], []),
                ("ACT B", None, [("b_get", {}, lambda p: p["n"] == 1, None)], [])]
        first = _Harness(monkeypatch, tmp_path, acts=acts)
        first.run(run_id="r1", acts_spec="ACT A")
        assert tool_verify.load_run_state("r1")["recall"] == {"landed": 1}
        second = _Harness(monkeypatch, tmp_path, acts=acts)      # clears _RECALL, as a new process does
        second.run(run_id="r1", resume=True)
        assert tool_verify._RECALL["landed"] == 1

    def test_a_ctx_value_that_cannot_be_saved_is_refused_by_name(self, monkeypatch, tmp_path):
        # the failure this replaces is silent: a value stringified into the state file resumes into
        # a step that fails on a bad reference, three acts later.
        with pytest.raises(TypeError) as refused:
            tool_verify.save_run_state("r1", {"ctx": {"good": 1, "handle": object()}})
        assert "handle" in str(refused.value) and "good" not in str(refused.value)

    def test_an_interrupted_serialization_preserves_the_previous_checkpoint(
            self, monkeypatch, tmp_path):
        monkeypatch.setattr(verify_runner, "RESULTS_DIR", str(tmp_path))
        previous = {"ctx": {"saved": 1}, "recall": {}, "acts_done": ["ACT A"]}
        path = Path(tool_verify.save_run_state("r1", previous))
        before = path.read_bytes()

        real_dump = verify_runner.json.dump

        def interrupted_dump(value, stream, indent=None):
            if indent == 2:
                stream.write('{"truncated":')
                raise OSError("write interrupted")
            return real_dump(value, stream, indent=indent)

        monkeypatch.setattr(verify_runner.json, "dump", interrupted_dump)
        with pytest.raises(OSError, match="interrupted"):
            tool_verify.save_run_state("r1", {"ctx": {"new": 2}, "recall": {}})
        assert path.read_bytes() == before
        assert list(tmp_path.iterdir()) == [path]

    @pytest.mark.parametrize("failure", ["write", "sync", "replace"])
    @pytest.mark.parametrize("existing", [False, True], ids=["new", "existing"])
    def test_a_failed_checkpoint_preserves_the_previous_state(
            self, monkeypatch, tmp_path, failure, existing):
        monkeypatch.setattr(verify_runner, "RESULTS_DIR", str(tmp_path))
        path = Path(tool_verify.run_state_path("r1"))
        before = None
        if existing:
            tool_verify.save_run_state("r1", {
                "ctx": {"saved": 1}, "recall": {}, "acts_done": ["ACT A"]})
            before = path.read_bytes()
        if failure == "write":
            real_fdopen = verify_runner.os.fdopen

            class FailedWriter:
                def __init__(self, *args, **kwargs):
                    self.file = real_fdopen(*args, **kwargs)

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    self.file.close()

                def write(self, value):
                    raise OSError("write failed")

            monkeypatch.setattr(verify_runner.os, "fdopen", FailedWriter)
        elif failure == "sync":
            monkeypatch.setattr(verify_runner.os, "fsync",
                                lambda fd: (_ for _ in ()).throw(OSError("sync failed")))
        else:
            monkeypatch.setattr(verify_runner.os, "replace",
                                lambda source, target: (_ for _ in ()).throw(OSError("replace failed")))
        with pytest.raises(OSError, match="failed"):
            tool_verify.save_run_state("r1", {"ctx": {"new": 2}, "recall": {}})
        if existing:
            assert path.read_bytes() == before
            assert list(tmp_path.iterdir()) == [path]
        else:
            assert not path.exists()
            assert list(tmp_path.iterdir()) == []

    def test_the_cloud_link_quarantine_is_checkpointed_and_not_replayed(
            self, monkeypatch, tmp_path):
        link_name = "ACT 11b2 - CLOUD: LINK GUARD REVIEW"
        link_act = next(act for act in tool_verify.ACTS if act[0] == link_name)
        acts = [
            link_act,
            ("ACT B", None, [("b_get", {}, lambda payload: payload["n"] == 1, None)], []),
        ]
        link_tools = {step[0] for step in tool_verify.judged_steps(link_act[2])}
        registered = sorted(link_tools | {"b_get", "design_get", *_ADMISSION_PENDING})
        first = _Harness(monkeypatch, tmp_path, acts=acts)
        monkeypatch.setattr(tool_verify, "registered_tools", _registered(registered))
        monkeypatch.setattr(
            tool_verify, "ACT_NEEDS", {link_name: tool_verify.CLOUD_LINK_CRASH_REVIEW})
        first_call = first._call

        def interrupted_call(tool, args):
            if tool == "b_get":
                raise RuntimeError("chunk interrupted")
            if tool == "doc_new":
                raise AssertionError("quarantined link act dispatched")
            return first_call(tool, args)

        monkeypatch.setattr(tool_verify, "call", interrupted_call)
        with pytest.raises(RuntimeError, match="chunk interrupted"):
            first.run(run_id="r1")
        saved = tool_verify.load_run_state("r1")
        reason = ("not-in-scope: cloud_link_crash_review_authorization needs "
                  "asked=None measured=False")
        assert saved["acts_done"] == [link_name]
        assert saved["act_modes"] == [[link_name, f"skipped({reason})"]]
        assert set(saved["gated"]) == link_tools
        assert set(saved["gated"].values()) == {reason}
        assert saved["entitlements"] == {tool_verify.CLOUD_LINK_CRASH_REVIEW: False,
                                          "native_script": True}
        assert saved["source_hash"] == "0" * 64
        assert saved["attestation"] == _ATTESTATION
        assert saved["document"]["name"] == "Untitled"
        assert "doc_new" not in first.tools_called()

        second = _Harness(monkeypatch, tmp_path, acts=acts)
        monkeypatch.setattr(tool_verify, "registered_tools", _registered(registered))
        monkeypatch.setattr(
            tool_verify, "ACT_NEEDS", {link_name: tool_verify.CLOUD_LINK_CRASH_REVIEW})
        monkeypatch.setattr(verify_runner, "probe_capabilities",
                            lambda capabilities: (_ for _ in ()).throw(
                                AssertionError("completed quarantine was repeated")))
        assert second.run(run_id="r1", resume=True) == 0
        assert "doc_new" not in second.tools_called()
        assert second.wrote["ledger"]["joint_drive"] == "skipped: " + reason
        assert second.wrote["ledger"]["b_get"] == "covered"
        assert second.wrote["act_modes"] == [
            (link_name, f"skipped({reason})"), ("ACT B", "narrative")]


class TestSourceDriftDuringRun:
    def test_source_change_during_act_without_run_id_blocks_receipt(self, monkeypatch, tmp_path):
        h = _Harness(monkeypatch, tmp_path)
        digest = ["0" * 64]
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: digest[0])
        real_call = h._call
        def call(tool, args):
            result = real_call(tool, args)
            if tool == "a_get":
                digest[0] = "f" * 64
            return result
        monkeypatch.setattr(tool_verify, "call", call)
        assert h.run() == 1
        assert not h.wrote and "b_get" not in h.tools_called()

    def test_source_change_during_act_blocks_receipt_and_checkpoint(self, monkeypatch, tmp_path):
        h = _Harness(monkeypatch, tmp_path)
        digest = ["0" * 64]
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: digest[0])
        real_call = h._call
        def call(tool, args):
            result = real_call(tool, args)
            if tool == "a_get":
                digest[0] = "f" * 64
            return result
        monkeypatch.setattr(tool_verify, "call", call)
        assert h.run(run_id="drift") == 1
        assert not h.wrote and not os.path.exists(verify_runner.run_state_path("drift"))

    def test_source_change_during_reload_blocks_receipt(self, monkeypatch, tmp_path):
        h = _Harness(monkeypatch, tmp_path)
        digest = ["0" * 64]
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: digest[0])
        def reload(*args, **kwargs):
            digest[0] = "f" * 64
        monkeypatch.setattr(tool_verify, "reload_smoke", reload)
        monkeypatch.setattr(tool_verify.reload_smoke, "support_routes", (), raising=False)
        assert h.run() == 1
        assert not h.wrote

    def test_stable_hash_is_saved_at_checkpoint(self, monkeypatch, tmp_path):
        h = _Harness(monkeypatch, tmp_path)
        assert h.run(run_id="stable", acts_spec="ACT A") == 0
        assert tool_verify.load_run_state("stable")["source_hash"] == "0" * 64

    def test_source_change_on_gated_act_blocks_checkpoint(self, monkeypatch, tmp_path):
        h = _Harness(monkeypatch, tmp_path, acts=[("ACT G", None, [("a_get", {}, "ok", None)], [])])
        digest = ["0" * 64]
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: digest[0])
        monkeypatch.setattr(tool_verify, "ACT_NEEDS", {"ACT G": "fake_tier"})
        def probe(_caps):
            digest[0] = "f" * 64
            return {"fake_tier": False}
        monkeypatch.setattr(verify_runner, "probe_capabilities", probe)
        assert h.run(run_id="gated") == 1
        assert not h.wrote and not os.path.exists(verify_runner.run_state_path("gated"))


class TestPredicateKind:
    """The classifier behind the split: it reads the step's EXPECTATION object, nothing else."""

    def test_bare_ok_string_is_a_call(self):
        assert tool_verify.predicate_kind("ok") == "call"

    def test_a_lambda_reading_the_payload_is_a_value(self):
        assert tool_verify.predicate_kind(lambda p: p.get("result_bodies")) == "value"

    def test_a_named_predicate_function_is_a_value(self):
        assert tool_verify.predicate_kind(tool_verify._repair_no_op) == "value"

    def test_a_constant_lambda_is_a_call_not_a_value(self):
        # 'lambda p: True' wears a predicate's shape and inspects nothing - counting it as covered
        # is exactly the inflation this split exists to prevent.
        assert tool_verify.predicate_kind(lambda p: True) == "call"

    def test_a_lambda_reading_a_closure_but_not_the_payload_is_a_call(self):
        want = 3
        assert tool_verify.predicate_kind(lambda p: want > 2) == "call"

    def test_refusal_strings_and_fragment_refusals_are_refusals(self):
        assert tool_verify.predicate_kind("refused") == "refusal"
        assert tool_verify.predicate_kind(tool_verify._refused("no such body")) == "refusal"

    def test_run_steps_returns_one_row_per_step_in_order(self, monkeypatch):
        # The receipt's covered/called split pairs each result row back with the EXPECTATION that
        # judged it by position, so a step that produced no row (or two) would attribute a value
        # predicate to the wrong tool. A blocked step still gets its row.
        monkeypatch.setattr(tool_verify, "call", _known_wire)
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        steps = [
            ("a_get", {}, "ok", None),
            ("b_get", {}, lambda p: p.get("n") == 1, None),
            ("c_get", lambda ctx: {"x": ctx["missing"]}, "ok", None),   # blocked: no ctx key
            ("d_get", {}, lambda p: p.get("n") == 2, None),             # predicate fails
        ]
        rows = tool_verify.run_steps(steps, {})
        assert [r[0] for r in rows] == ["a_get", "b_get", "c_get", "d_get"]
        assert [r[1] for r in rows] == ["pass", "pass", "blocked", "FAIL"]

    def test_the_step_engine_names_its_call_before_making_it(self, monkeypatch, capsys):
        # A redirected sweep log buffers per act, so the line naming a step has to be flushed
        # BEFORE the call: a step that kills the Fusion process leaves no line printed after it.
        def _call(tool, args):
            print(f"CALLED {tool}")
            return False, {"n": 1}
        monkeypatch.setattr(tool_verify, "call", _call)
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        tool_verify.run_steps([("a_get", {}, "ok", None)], {}, act="ACT 3")
        printed = [ln.strip() for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert printed == ["-> a_get ACT 3", "CALLED a_get"]

    def test_judged_steps_and_run_steps_agree_on_every_step_kind(self, monkeypatch):
        # The by-position pairing needs these two lists to be the same length, and each decides
        # what yields a row through _leaves_no_row. A second row-less step kind taught to one site
        # alone would shift the pairing again with every other test here still green.
        monkeypatch.setattr(tool_verify, "call", _known_wire)
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        steps = [
            ("bare_ok", {}, "ok", None),
            tool_verify._dwell(0),
            ("value_pred", {}, lambda p: p["n"] == 1, None),
            ("refusal", {}, "refused", None),
            ("blocked", lambda ctx: {"x": ctx["missing"]}, "ok", None),
            ("failing", {}, lambda p: p["n"] == 99, None),
            ("with_save", {}, "ok", ("k", lambda p: p["n"])),
            tool_verify._dwell(0),
        ]
        assert len(tool_verify.judged_steps(steps)) == len(tool_verify.run_steps(steps, {}))

    def test_a_dwell_does_not_shift_predicate_attribution(self, monkeypatch):
        # A _dwell is judged by nothing and leaves no row, so it is the one step that can break the
        # by-position pairing: run over the act's raw list and every expectation after a dwell is
        # credited to a LATER step's tool - a bare "ok" reads as covered and a value predicate is
        # lost. judged_steps is what the pairing runs over.
        monkeypatch.setattr(tool_verify, "call", _known_wire)
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        steps = [
            ("a_get", {}, "ok", None),
            tool_verify._dwell(0),
            ("b_get", {}, "ok", None),
            ("c_get", {}, lambda p: p["n"] == 1, None),
        ]
        rows = tool_verify.run_steps(steps, {})
        paired = [(row[0], tool_verify.predicate_kind(step[2]))
                  for step, row in zip(tool_verify.judged_steps(steps), rows)]
        assert paired == [("a_get", "call"), ("b_get", "call"), ("c_get", "value")]

    def test_run_credits_covered_to_the_tool_whose_own_step_read_a_value(self, monkeypatch):
        # The pairing AT ITS CALL SITE, over a one-act program holding the shape that breaks it: a
        # dwell between the bare-ok rows and the value predicate. Whichever list run() pairs with
        # the rows decides the ledger, so this is what a revert to zip(steps, ...) has to fail.
        ledger = {}

        def fake_write(rows, version, date, src_hash, path=None, notes=None, act_modes=None, attestation=None):
            ledger.update(rows)
            return "VERIFIED_TOOLS.md"

        monkeypatch.setattr(tool_verify, "call", _known_wire)
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        monkeypatch.setattr(tool_verify, "health_gate", _attested_health)
        monkeypatch.setattr(tool_verify, "registered_tools",
                            _registered(sorted({"a_get", "b_get", "c_get", *_ADMISSION_PENDING})))
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: "0" * 64)
        monkeypatch.setattr(tool_verify, "write_verified", fake_write)
        monkeypatch.setattr(tool_verify, "reload_smoke",
                            lambda rows, notes, valued=None, **kw: _reloaded_attestation())
        monkeypatch.setattr(tool_verify.reload_smoke, "support_routes", (), raising=False)
        monkeypatch.setattr(tool_verify, "POLL_AFTER", {})
        monkeypatch.setattr(tool_verify, "EXCLUDED", {})
        monkeypatch.setattr(tool_verify, "STORY", {})
        monkeypatch.setattr(tool_verify, "ACTS", [("ACT T", None, [
            ("a_get", {}, "ok", None),
            tool_verify._dwell(0),
            ("b_get", {}, "ok", None),
            ("c_get", {}, lambda p: p["n"] == 1, None),
        ], None)])
        monkeypatch.setattr(tool_verify, "FAMILY_PROGRAM", None)

        assert tool_verify.run(write_json=False) == 0
        assert ledger == {"a_get": "called", "b_get": "called", "c_get": "covered", **_ADMISSION_PENDING}

    def test_every_steps_row_classifies_and_no_constant_predicate_hides_in_them(self):
        # A callable in STEPS that never READS INTO its payload would be counted 'covered' on this
        # run while proving nothing; there are none, and this is what keeps it that way. Every
        # callable expectation in STEPS therefore has to satisfy the guard below.
        kinds = [tool_verify.predicate_kind(step[2]) for step in tool_verify.STEPS]
        assert set(kinds) <= {"value", "call", "refusal"}
        constants = [step[0] for step in tool_verify.STEPS
                     if callable(tool_verify._unparked(step[2]))
                     and not isinstance(tool_verify._unparked(step[2]), tool_verify._Refusal)
                     and tool_verify.predicate_kind(step[2]) == "call"]
        assert not constants, ("STEPS rows whose predicate never reads the payload: "
                               + ", ".join(sorted(set(constants))))


def _reads_a_key(payload):
    """A module-level helper that DOES read the payload - the callee side of `lambda p: helper(p)`."""
    return payload.get("result_bodies")


class TestValuePredicateGuard:
    """Loading the argument is not the same as reading it. Each shape below TOUCHES the payload and
    inspects nothing in it, and each would otherwise be bucketed 'covered' while proving no more
    than a bare "ok" - the exact inflation the covered/called split exists to prevent."""

    def test_a_truthiness_test_on_the_payload_is_a_call(self):
        assert tool_verify.predicate_kind(lambda p: p and True) == "call"

    def test_bool_of_the_payload_is_a_call(self):
        assert tool_verify.predicate_kind(lambda p: bool(p)) == "call"

    def test_a_none_check_on_the_payload_is_a_call(self):
        assert tool_verify.predicate_kind(lambda p: p is not None) == "call"

    def test_an_attribute_read_off_the_payload_is_a_value(self):
        assert tool_verify.predicate_kind(lambda p: p.get("moved") is True) == "value"

    def test_a_subscript_of_the_payload_is_a_value(self):
        assert tool_verify.predicate_kind(lambda p: p["joints"][0]["name"] == "Yaw") == "value"

    def test_handing_the_payload_to_a_reading_helper_is_a_value(self):
        assert tool_verify.predicate_kind(lambda p: _reads_a_key(p)) == "value"

    def test_a_payload_captured_by_an_inner_comprehension_is_still_a_value(self):
        # Closing over the payload inside the predicate makes it a CELL, so every read of it
        # compiles to LOAD_DEREF instead of LOAD_FAST - a real read either way.
        assert tool_verify.predicate_kind(
            lambda p: all(r.get("name") for r in (p.get("joints") or []))) == "value"


class TestParkedSteps:
    """Parked carries a ledger REASON, never a judgement."""

    def test_predicate_kind_reads_through_the_marker(self):
        assert tool_verify.predicate_kind(tool_verify.Parked("held")) == "call"
        assert tool_verify.predicate_kind(
            tool_verify.Parked("held", lambda p: p.get("n"))) == "value"
        assert tool_verify.predicate_kind(tool_verify.Parked("held", "refused")) == "refusal"

    def test_a_parked_step_is_judged_by_the_expectation_inside_it(self, monkeypatch):
        monkeypatch.setattr(tool_verify, "call", _known_wire)
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        rows = tool_verify.run_steps([
            ("a_get", {}, tool_verify.Parked("held at a bare ok"), None),
            ("b_get", {}, tool_verify.Parked("held", lambda p: p.get("n") == 2), None),
        ], {})
        assert [r[1] for r in rows] == ["pass", "FAIL"]


class TestCapabilityProbe:
    """The machining_extension probe reads workspace_orient's own entitlement block. Entitled means
    every sentinel flag answered TRUE; anything it could not read is None, which routes as unmet."""

    @staticmethod
    def _wire(monkeypatch, answer):
        monkeypatch.setattr(tool_verify, "call", lambda tool, args: answer)

    def test_all_four_sentinels_true_is_entitled(self, monkeypatch):
        self._wire(monkeypatch, (False, {"machining_capabilities": {"observed_generation": {
            "steep_and_shallow": True, "multiaxis_finishing": True,
            "swarf": True, "probe_geometry": True}}}))
        assert tool_verify._machining_extension_probe() is True

    def test_one_sentinel_false_is_not_entitled(self, monkeypatch):
        self._wire(monkeypatch, (False, {"machining_capabilities": {"observed_generation": {
            "steep_and_shallow": True, "multiaxis_finishing": True,
            "swarf": False, "probe_geometry": True}}}))
        assert tool_verify._machining_extension_probe() is False

    def test_a_null_flag_is_unreadable_not_entitled(self, monkeypatch):
        # null is 'the probe could not read it'. Reading it as False would report an entitlement
        # verdict nothing measured; reading it as True would run rows this licence cannot generate.
        self._wire(monkeypatch, (False, {"machining_capabilities": {"observed_generation": {
            "steep_and_shallow": True, "multiaxis_finishing": None,
            "swarf": True, "probe_geometry": True}}}))
        assert tool_verify._machining_extension_probe() is None

    def test_a_missing_block_and_a_failed_read_are_both_unreadable(self, monkeypatch):
        self._wire(monkeypatch, (False, {"document": {"name": "X"}}))
        assert tool_verify._machining_extension_probe() is None
        self._wire(monkeypatch, (True, "no active document"))
        assert tool_verify._machining_extension_probe() is None


def _licence_partition(acts, act_needs, opt_in):
    """(held, free) over an act program: the tools a LICENCE capability holds back, and the tools
    some ungated step drives.

    An OPT-IN TIER's steps are in NEITHER set. They are not licence-held; and reading them as
    ungated would let a cloud step stand in as a licence-gated tool's base-licence variant - a
    variant that runs on no default sweep, which is the opposite of what the invariant asks for."""
    tiered_acts = {a for a, cap in act_needs.items() if cap in opt_in}
    gated_acts = set(act_needs) - tiered_acts
    held, free = set(), set()
    for name, _pre, narr, fb in acts:
        for step in (list(narr) + list(fb or [])):
            if step[0] == tool_verify._DWELL:
                continue
            cap = tool_verify.step_capability(step[2])
            if name in tiered_acts or cap in opt_in:
                continue
            if tool_verify.step_runs_unentitled(step[2]) and name not in gated_acts:
                free.add(step[0])          # the base-licence variant itself
                continue
            (held if (name in gated_acts or cap is not None) else free).add(step[0])
    return held, free


class TestCapabilityTier:
    """The tier itself: what a declaration means, and which receipt bucket an unmet one lands in."""

    _FAKE = {"yes": lambda: True, "no": lambda: False, "dunno": lambda: None}

    def test_each_declared_capability_is_probed_once(self):
        calls = []
        probes = {"yes": lambda: calls.append("yes") or True}
        assert tool_verify.probe_capabilities(["yes", "yes"], probes) == {"yes": True}
        assert calls == ["yes"]

    def test_an_unregistered_capability_answers_unreadable(self):
        # a typo in a declaration must not read as entitled - there is no probe to say it is.
        assert tool_verify.probe_capabilities(["nosuch"], self._FAKE) == {"nosuch": None}

    def test_only_a_true_probe_is_met(self):
        ent = tool_verify.probe_capabilities(["yes", "no", "dunno"], self._FAKE)
        assert tool_verify.capability_met(ent, "yes") is True
        assert tool_verify.capability_met(ent, "no") is False
        assert tool_verify.capability_met(ent, "dunno") is False
        assert tool_verify.capability_met(ent, None) is True

    def test_the_skip_reason_separates_not_entitled_from_unreadable(self):
        ent = {"no": False, "dunno": None}
        assert tool_verify.capability_skip_reason("no", ent) == "no not entitled"
        assert "probe did not read" in tool_verify.capability_skip_reason("dunno", ent)

    def test_a_capability_detail_rides_the_skip_reason(self):
        # The detail is what an operator reading a skipped row acts on. A capability with no entry
        # keeps the bare verdict, so the two shapes cannot merge.
        assert tool_verify.capability_skip_reason("no", {"no": False}) == "no not entitled"
        reason = tool_verify.capability_skip_reason(tool_verify.CLOUD_TIER, {"cloud_tier": False})
        assert reason.startswith("cloud_tier not entitled")
        assert "sweep_config.local.json" in reason and "hub, project, folder" in reason

    def test_the_cloud_link_review_is_a_separate_dormant_act_before_drawing(self):
        names = [name for name, _pre, _narr, _fb in tool_verify._ACT_PROGRAM]
        link = "ACT 11b2 - CLOUD: LINK GUARD REVIEW"
        assert names.index("ACT 11b - CLOUD: THE SAVED DOCUMENT") < names.index(link)
        assert names.index(link) < names.index("ACT 11c - CLOUD: THE DRAWING")
        program = {name: narr for name, _pre, narr, _fb in tool_verify._ACT_PROGRAM}
        assert [(tool, args, tool_verify._unparked(expect), save)
                for tool, args, expect, save in program[link]] == [
            (tool, args, tool_verify._unparked(expect), save)
            for tool, args, expect, save in tool_verify._CLOUD_LINK]
        assert not [step for step in tool_verify._CLOUD_DOC if step[0] == "joint_drive"]
        assert tool_verify.ACT_NEEDS[link] == tool_verify.CLOUD_LINK_CRASH_REVIEW
        for safe in ("ACT 11a - CLOUD: THE DATA MODEL",
                     "ACT 11b - CLOUD: THE SAVED DOCUMENT",
                     "ACT 11c - CLOUD: THE DRAWING"):
            assert tool_verify.ACT_NEEDS[safe] == tool_verify.CLOUD_TIER
        assert tool_verify._cloud_link_crash_review_probe() is False
        reason = tool_verify.capability_skip_reason(
            tool_verify.CLOUD_LINK_CRASH_REVIEW,
            {tool_verify.CLOUD_LINK_CRASH_REVIEW: False})
        assert "deferred" in reason and "unverified" in reason
        assert "owner-approved crash review" in reason

    @staticmethod
    def _detailed(monkeypatch):
        """A capability whose probe answers false and whose skip row carries a detail sentence."""
        monkeypatch.setitem(verify_core.CAPABILITY_PROBES, "fake_tier", lambda: False)
        monkeypatch.setitem(verify_core.CAPABILITY_DETAIL, "fake_tier", "opt-in: write the config")

    def test_a_gated_acts_ledger_row_carries_its_actual_request_and_observation(self, monkeypatch):
        self._detailed(monkeypatch)
        acts = [("ACT F", None, [("a_get", {}, "ok", None)], [("fb_get", {}, "ok", None)])]
        ledger, _seen, modes = self._run(monkeypatch, acts, {"ACT F": "fake_tier"}, entitled=False,
                                         tools=["a_get", "fb_get"])
        assert ledger["a_get"] == "skipped: held: fake_tier needs asked=None measured=False"
        assert ledger["fb_get"] == ledger["a_get"]
        assert modes == [("ACT F", "skipped(held: fake_tier needs asked=None measured=False)")]

    def test_a_gated_steps_ledger_row_carries_the_actual_request_and_observation(self, monkeypatch):
        # consumer two: the per-STEP skip in run(), which words its bucket through the same helper.
        self._detailed(monkeypatch)
        acts = [("ACT S", None, [
            ("a_get", {}, "ok", None),
            ("gated_get", {}, tool_verify._needs("fake_tier", lambda p: p["n"] == 1), None),
        ], [])]
        ledger, seen, _modes = self._run(monkeypatch, acts, {}, entitled=False,
                                         tools=["a_get", "gated_get"])
        assert ledger["gated_get"] == "skipped: held: fake_tier needs asked=None measured=False"
        assert seen == ["a_get"]

    def test_the_declaration_is_read_through_both_wrappers(self):
        needs = tool_verify._needs("yes", lambda p: p.get("n"))
        assert tool_verify.step_capability(needs) == "yes"
        assert tool_verify.step_capability(tool_verify.Parked("held", needs)) == "yes"
        assert tool_verify.step_capability(tool_verify.Parked("held")) is None
        assert tool_verify.step_capability("ok") is None

    def test_a_gate_changes_the_bucket_and_never_the_judgement(self):
        # Needs carries ledger routing only: the expectation inside is what judges the step, so the
        # covered/called/refusal split must read straight through it.
        assert tool_verify.predicate_kind(tool_verify._needs("yes")) == "call"
        assert tool_verify.predicate_kind(tool_verify._needs("yes", lambda p: p["n"])) == "value"
        assert tool_verify.predicate_kind(tool_verify._needs("yes", "refused")) == "refusal"
        assert tool_verify.predicate_kind(
            tool_verify._needs("yes", tool_verify.Parked("held", lambda p: p["n"]))) == "value"

    def test_a_parked_reason_survives_a_gate_around_it(self):
        assert tool_verify.parked_reason(
            tool_verify._needs("yes", tool_verify.Parked("held at a bare ok"))) == "held at a bare ok"
        assert tool_verify.parked_reason("ok") is None

    @staticmethod
    def _run(monkeypatch, acts, act_needs, entitled, tools, poll_after=None):
        """run() over a stubbed wire, returning (ledger, the tools the wire was actually called
        with, the act modes)."""
        out = {}
        seen = []
        config = json.loads(json.dumps(verify_core.MACHINE))
        config["tiers"]["machining_extension"] = entitled is True
        path = verify_core._MACHINE_READ[2]
        Path(path).write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(verify_core, "MACHINE", config)
        monkeypatch.setattr(verify_core, "_MACHINE_READ", (config, [], path, machine_config.ENV))

        def fake_write(rows, version, date, src_hash, path=None, notes=None, act_modes=None, attestation=None):
            out["ledger"] = dict(rows)
            out["act_modes"] = list(act_modes or [])
            return "VERIFIED_TOOLS.md"

        def call(tool, args):
            seen.append(tool)
            if tool == "workspace_orient":
                flags = {n: entitled for n in ("steep_and_shallow", "multiaxis_finishing",
                                               "swarf", "probe_geometry")}
                return False, {"machining_capabilities": {"observed_generation": flags}}
            if tool == "sys_get_preferences":
                return _preference_reply()
            if tool == "doc_get":
                return False, {"active": {"name": "Untitled", "document_id": None,
                                           "document_handle": "session:test"},
                               "document_id": None, "truncated": False, "open_count": 1,
                               "open_documents": [{"name": "Untitled", "is_active": True,
                                                   "document_handle": "session:test"}]}
            if tool == "design_get":
                return False, {"feature_count": 1}
            if tool == "doc_new":
                return False, {"created": True, "document_handle": "session:test"}
            return False, {"n": 1}

        monkeypatch.setattr(tool_verify, "call", call)
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        monkeypatch.setattr(tool_verify, "health_gate", _attested_health)
        monkeypatch.setattr(
            tool_verify, "registered_tools",
            _registered(sorted(set(tools) | set(_ADMISSION_PENDING) | {"design_get", "workspace_orient"}
                               | ({"doc_close", "doc_activate"} if any(
                                   row[0] == "doc_new"
                                   and not any(machine_config.asked(config).get(cap) is False
                                               for cap in ((act_needs.get(name),)
                                                           if not isinstance(act_needs.get(name), tuple)
                                                           else act_needs[name]) if cap is not None)
                                   and not any(polarity == "needs" and machine_config.asked(config).get(cap) is False
                                               for cap, polarity in verify_core.step_conditions(row[2]))
                                   for name, _pre, narrative, fallback in acts
                                   for row in list(narrative) + list(fallback or [])) else set())),
                        {"doc_new"} if "doc_new" in tools else ()))
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: "0" * 64)
        monkeypatch.setattr(tool_verify, "write_verified", fake_write)
        # the post-run reload beat is another act's business; stubbed so 'seen' is this tier's
        monkeypatch.setattr(tool_verify, "reload_smoke",
                            lambda rows, notes, valued=None, **kw: _reloaded_attestation())
        monkeypatch.setattr(tool_verify.reload_smoke, "support_routes", (), raising=False)
        monkeypatch.setattr(tool_verify, "POLL_AFTER", poll_after or {})
        monkeypatch.setattr(tool_verify, "EXCLUDED", {})
        monkeypatch.setattr(tool_verify, "STORY", {})
        monkeypatch.setattr(tool_verify, "ACT_NEEDS", act_needs)
        monkeypatch.setattr(tool_verify, "ACTS", acts)
        monkeypatch.setattr(tool_verify, "FAMILY_PROGRAM", None)
        assert tool_verify.run(write_json=False) == 0
        assert seen[:2] == ["doc_get", "sys_get_preferences"]
        return out["ledger"], seen[2:], out["act_modes"]

    def test_a_gated_act_runs_nothing_and_banks_the_capability_bucket(self, monkeypatch):
        # BOTH lanes bank the bucket: neither ran, so a tool the fallback alone drives is skipped
        # for the same reason - reported PENDING, it would read as never scripted.
        acts = [("ACT E", ("pre_get", {}), [("a_get", {}, lambda p: p["n"] == 1, None)],
                 [("fb_get", {}, "ok", None)])]
        ledger, seen, modes = self._run(
            monkeypatch, acts, {"ACT E": "machining_extension"}, entitled=False,
            tools=["a_get", "fb_get", "pre_get"])
        reason = "not-in-scope: machining_extension needs asked=False measured=False"
        assert ledger["a_get"] == "skipped: " + reason
        assert ledger["fb_get"] == "skipped: " + reason
        # not even the act's PRECONDITION read fires - it decides between two lanes neither of
        # which may run, and a wire call for that is a call for nothing.
        assert seen == ["workspace_orient"]
        assert modes == [("ACT E", "skipped(" + reason + ")")]

    def test_the_same_act_runs_where_the_capability_is_entitled(self, monkeypatch):
        acts = [("ACT E", None, [("a_get", {}, lambda p: p["n"] == 1, None)], [])]
        ledger, seen, modes = self._run(
            monkeypatch, acts, {"ACT E": "machining_extension"}, entitled=True, tools=["a_get"])
        assert ledger["a_get"] == "covered"
        assert seen == ["workspace_orient", "a_get"]
        assert modes == [("ACT E", "narrative")]

    def test_an_unless_step_runs_where_the_capability_is_absent(self, monkeypatch):
        # the base-licence variant: the Needs row is held back and the Unless row runs in its
        # place, so the tool keeps a row on an unentitled installation
        acts = [("ACT U", None, [
            ("a_get", {}, "ok", None),
            ("gated_get", {}, tool_verify._needs("machining_extension", lambda p: p["n"] == 1), None),
            ("gated_get", {}, tool_verify._unless("machining_extension", lambda p: p["n"] == 1), None),
        ], [])]
        ledger, seen, _modes = self._run(
            monkeypatch, acts, {}, entitled=False, tools=["a_get", "gated_get"])
        assert ledger["gated_get"] == "covered"
        assert seen == ["workspace_orient", "a_get", "gated_get"]

    def test_an_unless_step_is_held_back_where_the_capability_is_entitled(self, monkeypatch):
        acts = [("ACT U", None, [
            ("a_get", {}, "ok", None),
            ("unless_get", {}, tool_verify._unless("machining_extension", "refused"), None),
        ], [])]
        ledger, seen, _modes = self._run(
            monkeypatch, acts, {}, entitled=True, tools=["a_get", "unless_get"])
        assert ledger["unless_get"] == ("skipped: not-applicable: machining_extension unless "
                                        "asked=True measured=True")
        assert seen == ["workspace_orient", "a_get"]

    def test_an_unless_step_carries_its_capability_and_its_inner_judgement(self):
        # the probe registry reads the declaration through it, and the judgement stays inside
        gate = tool_verify._unless("machining_extension", "refused")
        assert tool_verify.step_capability(gate) == "machining_extension"
        assert tool_verify.step_runs_unentitled(gate) is True
        assert tool_verify.step_runs_unentitled(tool_verify._needs("machining_extension")) is False
        assert tool_verify._unparked(gate) == "refused"
        # an unreadable probe runs neither variant
        assert tool_verify.gate_allows({"machining_extension": None}, gate) is False
        assert tool_verify.gate_allows({"machining_extension": False}, gate) is True
        assert tool_verify.gate_allows({"machining_extension": True}, gate) is False

    def test_a_gated_step_is_dropped_without_shifting_the_rows_after_it(self, monkeypatch):
        # The bug this exists to catch is silent and green: a gated step that still yielded a row
        # would pair every later expectation with the wrong tool, so a bare "ok" would read as
        # covered and a value predicate would be lost.
        acts = [("ACT T", None, [
            ("a_get", {}, "ok", None),
            ("gated_get", {}, tool_verify._needs("machining_extension", lambda p: p["n"] == 1), None),
            ("c_get", {}, lambda p: p["n"] == 1, None),
        ], [])]
        ledger, seen, _modes = self._run(
            monkeypatch, acts, {}, entitled=False, tools=["a_get", "gated_get", "c_get"])
        assert ledger == {"a_get": "called",
                          "gated_get": "skipped: not-in-scope: machining_extension needs asked=False measured=False",
                          "c_get": "covered", "design_get": "PENDING (no step yet)",
                          "workspace_orient": "PENDING (no step yet)", **_ADMISSION_PENDING}
        assert seen == ["workspace_orient", "a_get", "c_get"]

    def test_requested_extension_is_admitted_before_the_opening_act(self, monkeypatch):
        acts = [("ACT OPEN", None, [("doc_new", {}, "ok", None)], []),
                ("ACT E", None, [("a_get", {}, lambda p: p["n"] == 1, None)], [])]
        ledger, seen, _modes = self._run(
            monkeypatch, acts, {"ACT E": "machining_extension"}, entitled=True,
            tools=["a_get", "doc_new"])
        assert seen == ["workspace_orient", "doc_get", "design_get", "doc_new", "doc_get",
                        "design_get", "a_get", "doc_get", "design_get", "doc_get"]
        assert ledger["a_get"] == "covered"

    def test_a_gated_act_polls_nothing(self, monkeypatch):
        # the boundary poll certifies a generation the act launched; a held-back act launched none,
        # and polling for one would fail the run on an act that deliberately did not happen.
        polled = []
        monkeypatch.setattr(tool_verify, "poll_generation",
                            lambda rows, notes, setup, valued=None: polled.append(setup))
        monkeypatch.setattr(tool_verify.poll_generation, "support_routes", (), raising=False)
        acts = [("ACT E", None, [("a_get", {}, "ok", None)], [])]
        self._run(monkeypatch, acts, {"ACT E": "machining_extension"}, entitled=False,
                  tools=["a_get", "workspace_orient"],
                  poll_after={"ACT E": {"narrative": "SwarfSetup", "fallback": "SwarfSetup"}})
        assert polled == []

    def test_a_poll_target_list_certifies_each_setup_in_turn(self, monkeypatch):
        # one act can leave SEVERAL setups generating; a list that only polled its first element
        # would leave the rest uncertified while the run still read green.
        polled = []
        monkeypatch.setattr(tool_verify, "poll_generation",
                            lambda rows, notes, setup, valued=None, document_pin=None:
                            polled.append((setup, document_pin)))
        monkeypatch.setattr(tool_verify.poll_generation, "support_routes", (), raising=False)
        acts = [("ACT G", None, [("a_get", {}, "ok", None)], [])]
        self._run(monkeypatch, acts, {}, entitled=True,
                  tools=["a_get", "doc_new", "workspace_orient"],
                  poll_after={"ACT G": {"narrative": ["One", "Two"], "fallback": ["One", "Two"]}})
        assert polled == [("One", "session:test"), ("Two", "session:test")]

    def test_an_unreadable_probe_holds_the_steps_back_and_says_so(self, monkeypatch):
        def call(tool, args):
            return (False, {}) if tool == "workspace_orient" else _known_wire(tool, args)
        monkeypatch.setattr(tool_verify, "call", call)
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        monkeypatch.setattr(tool_verify, "health_gate", _attested_health)
        monkeypatch.setattr(tool_verify, "registered_tools",
                            _registered(sorted({"a_get", "workspace_orient", *_ADMISSION_PENDING})))
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: "0" * 64)
        ledger = {}
        monkeypatch.setattr(tool_verify, "write_verified",
                            lambda rows, v, d, h, **kw: ledger.update(rows))
        monkeypatch.setattr(tool_verify, "reload_smoke",
                            lambda rows, notes, valued=None, **kw: _reloaded_attestation())
        monkeypatch.setattr(tool_verify.reload_smoke, "support_routes", (), raising=False)
        monkeypatch.setattr(tool_verify, "POLL_AFTER", {})
        monkeypatch.setattr(tool_verify, "EXCLUDED", {})
        monkeypatch.setattr(tool_verify, "STORY", {})
        monkeypatch.setattr(tool_verify, "ACT_NEEDS", {"ACT E": "machining_extension"})
        monkeypatch.setattr(tool_verify, "ACTS",
                            [("ACT E", None, [("a_get", {}, "ok", None)], [])])
        assert tool_verify.run(write_json=False) == 0
        assert ledger["a_get"] == ("skipped: not-in-scope: machining_extension needs "
                                   "asked=False measured=None")

    def test_every_declared_capability_in_the_real_program_has_a_probe(self):
        # a declaration with no probe routes as unmet forever, so the acts it gates would never run
        # again on any installation - and nothing else in the harness would say why.
        core = tool_verify.verify_core
        declared = {cap for value in tool_verify.ACT_NEEDS.values()
                    for cap, _polarity in core.step_conditions(core.Needs(value))} | {
            cap for step in tool_verify.STEPS
            for cap, _polarity in core.step_conditions(step[2])}
        assert declared, "no capability is declared - the tier has no consumer"
        assert declared <= set(tool_verify.CAPABILITY_PROBES), (
            "capabilities declared with no probe registered: "
            + ", ".join(sorted(declared - set(tool_verify.CAPABILITY_PROBES))))

    def test_every_gated_act_name_is_a_real_act(self):
        names = {name for name, _p, _n, _f in tool_verify.ACTS}
        assert set(tool_verify.ACT_NEEDS) <= names, (
            "ACT_NEEDS names acts the program does not run: "
            + ", ".join(sorted(set(tool_verify.ACT_NEEDS) - names)))

    def test_every_extension_only_act_keeps_a_base_licence_variant(self):
        # A LICENCE capability may not take a TOOL's only step with it: every tool its acts and steps
        # drive must also be driven by an ungated step, or an unentitled installation loses that
        # tool's coverage rather than one strategy's.
        held, free = _licence_partition(tool_verify.ACTS, tool_verify.ACT_NEEDS,
                                        tool_verify.OPT_IN_TIERS)
        assert held, "no act declares a licence capability - this invariant has no subject"
        assert not (held - free), (
            "tools whose every step rides a LICENCE capability: " + ", ".join(sorted(held - free)))

    def test_an_opt_in_step_is_not_a_licence_gated_tools_base_variant(self):
        # The rule the real program cannot currently exercise: a tool whose only ungated-looking step
        # lives in an OPT-IN act has no base-licence variant at all - that step runs on no default
        # sweep. Counting an opt-in step as 'free' would report this program clean.
        acts = [("ACT LIC", None, [("x_get", {}, "ok", None)], []),
                ("ACT TIER", None, [("x_get", {}, "ok", None)], [])]
        needs = {"ACT LIC": "machining_extension", "ACT TIER": "fake_tier"}
        held, free = _licence_partition(acts, needs, frozenset({"fake_tier"}))
        assert held == {"x_get"} and free == set()
        assert held - free == {"x_get"}

    def test_a_step_level_opt_in_declaration_is_read_the_same_way(self):
        acts = [("ACT LIC", None, [("x_get", {}, tool_verify._needs("machining_extension"), None),
                                   ("x_get", {}, tool_verify._needs("fake_tier"), None)], [])]
        held, free = _licence_partition(acts, {}, frozenset({"fake_tier"}))
        assert held == {"x_get"} and free == set()

    def test_an_opt_in_tier_is_the_only_thing_holding_its_own_tools(self):
        # The other half of the pair: the cloud tier's tools ARE meant to have no ungated step - that
        # is what makes an unconfigured run skip them. A tool that drifted into an ungated act would
        # be driven against an operator's hub by a default sweep, which is exactly what the tier is
        # for, so the drift is caught here rather than live.
        tiered = {a for a, cap in tool_verify.ACT_NEEDS.items() if cap in tool_verify.OPT_IN_TIERS}
        assert tiered, "no act declares an opt-in tier - the tier has no consumer"
        held, free = set(), set()
        for name, _pre, narr, fb in tool_verify.ACTS:
            for step in (list(narr) + list(fb or [])):
                if step[0] == tool_verify._DWELL:
                    continue
                (held if name in tiered else free).add(step[0])
        # the tools the tier alone drives - the data/doc/drawing families that write to a real hub
        cloud_only = held - free
        assert {"data_upload_file", "data_delete_file", "doc_save_as", "drawing_export"} <= cloud_only
        assert not any(t.startswith("data_") for t in free), (
            "a data_* tool is driven by an act no opt-in tier gates: "
            + ", ".join(sorted(t for t in free if t.startswith("data_"))))


class TestFacadeLateBinding:
    """The call-time facade() sites with no other offline pin: each must see what a consumer
    stubs ON tool_verify at CALL time. An import-time binding of its own copy leaves the stub
    unread while every other offline test stays green, so these assertions are each site's one
    offline bite."""

    def test_precondition_holds_reads_the_stubbed_wire(self, monkeypatch):
        seen = []
        monkeypatch.setattr(tool_verify, "call",
                            lambda tool, args: (seen.append((tool, args)), (False, {}))[1])
        assert tool_verify._precondition_holds(("sketch_get", {"sketch_name": "X"})) is True
        assert seen == [("sketch_get", {"sketch_name": "X"})]
        monkeypatch.setattr(tool_verify, "call", lambda tool, args: (True, "down"))
        assert tool_verify._precondition_holds(("sketch_get", {})) is False

    def test_run_steps_pins_guarded_writes_and_rejects_authored_divergence(self, monkeypatch):
        seen = []
        monkeypatch.setattr(tool_verify, "call",
                            lambda tool, args: (seen.append((tool, dict(args))), (False, {}))[1])
        pin = {"state": "known", "handle": "session:pinned", "snapshot": {}}
        rows = tool_verify.run_steps(
            [("a_get", {}, "ok", None),
             ("b_get", {"expect_document": "session:authored"}, "ok", None),
             ("c_get", {"expect_document": None}, "ok", None),
             ("d_get", {"expect_document": " "}, "ok", None)],
            {}, sleep_s=0, document_pin=pin,
            guarded_tools={"a_get", "b_get", "c_get", "d_get"})
        assert [r[1] for r in rows] == ["pass", "blocked", "pass", "pass"]
        assert seen == [
            ("a_get", {"expect_document": "session:pinned"}),
            ("c_get", {"expect_document": "session:pinned"}),
            ("d_get", {"expect_document": "session:pinned"}),
        ]

    def test_deliberate_guard_refusal_preserves_the_retained_pin(self, monkeypatch):
        seen = []

        def call(tool, args):
            seen.append((tool, dict(args)))
            return (True, "document mismatch") if tool == "doc_activate" else (False, {})
        monkeypatch.setattr(tool_verify, "call", call)
        pin = {"state": "known", "handle": "session:pinned",
               "snapshot": {"state": "known", "document_handle": "session:pinned"},
               "known_documents": {}}
        rows = tool_verify.run_steps(
            [("doc_activate", {"name": "missing",
                               "expect_document": "session:wrong"}, "refused", None),
             ("a_get", {}, "ok", None)], {}, sleep_s=0, document_pin=pin,
            guarded_tools={"doc_activate", "a_get"})
        assert [row[1] for row in rows] == ["expected-refusal", "pass"]
        assert seen[-1] == ("a_get", {"expect_document": "session:pinned"})

    def test_unreadable_active_document_blocks_doc_new_before_dispatch(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            tool_verify, "call",
            lambda tool, args: (seen.append((tool, dict(args))), (True, "no active document"))[1])
        pin = {"state": "unknown", "handle": None, "snapshot": None,
               "known_documents": {}}
        rows = tool_verify.run_steps(
            [("doc_new", {}, "ok", None)], {}, sleep_s=0, document_pin=pin,
            guarded_tools={"doc_new"})
        assert rows[0][1] == "blocked"
        assert seen == [("doc_get", {})]

    def test_no_open_document_lets_doc_new_through_without_a_guard(self, monkeypatch):
        seen, opened = [], []

        def call(tool, args):
            seen.append((tool, dict(args)))
            if tool == "doc_new":
                opened.append("session:new")
                return False, {"created": True, "document_handle": "session:new"}
            if tool == "doc_get" and not opened:
                return True, "No active document. Open or create one first (doc_open / doc_new)."
            if tool == "doc_get":
                return False, {"active": {"name": "Untitled", "document_handle": "session:new"}}
            return False, {}
        monkeypatch.setattr(tool_verify, "call", call)
        pin = {"state": "unknown", "handle": None, "snapshot": None,
               "known_documents": {}}
        rows = tool_verify.run_steps(
            [("doc_new", {}, "ok", None), ("model_write", {}, "ok", None)],
            {}, sleep_s=0, document_pin=pin, guarded_tools={"doc_new", "model_write"})
        assert [row[1] for row in rows] == ["pass", "pass"]
        assert ("doc_new", {}) in seen
        assert ("model_write", {"expect_document": "session:new"}) in seen

    def test_failed_initial_pin_blocks_later_doc_get_capture_and_write(self, monkeypatch):
        judged, captured, seen = [], [], []
        doc_reads = iter([
            (True, "active document unreadable"),
            (False, {"active": {"name": "A", "document_handle": "session:a"}}),
        ])

        def call(tool, args):
            seen.append((tool, dict(args)))
            if tool == "doc_get":
                return next(doc_reads)
            return False, {"changed": True}

        monkeypatch.setattr(tool_verify, "call", call)
        pin = {"state": "unknown", "handle": None, "snapshot": None,
               "known_documents": {}}
        rows = tool_verify.run_steps(
            [("doc_get", {}, lambda p: judged.append(p) or True,
              ("captured", lambda p: captured.append(p) or "session:a")),
             ("model_write", {}, "ok", None)],
            {}, sleep_s=0, document_pin=pin, guarded_tools={"model_write"})
        assert [row[1] for row in rows] == ["blocked", "blocked"]
        assert judged == [] and captured == []
        assert not any(tool == "model_write" for tool, _args in seen)

    def test_mismatch_block_survives_a_later_matching_doc_get(self, monkeypatch):
        judged, captured, seen = [], [], []
        doc_reads = iter([
            (False, {"active": {"name": "B", "document_handle": "session:b"}}),
            (False, {"active": {"name": "A", "document_handle": "session:a"}}),
        ])

        def call(tool, args):
            seen.append((tool, dict(args)))
            if tool == "doc_get":
                return next(doc_reads)
            return False, {"changed": True}

        monkeypatch.setattr(tool_verify, "call", call)
        pin = {"state": "known", "handle": "session:a",
               "snapshot": {"state": "known", "document_handle": "session:a"},
               "known_documents": {"session:a": "session:a"}}
        rows = tool_verify.run_steps(
            [("doc_get", {}, lambda p: judged.append(p) or True,
              ("first", lambda p: captured.append(p) or "session:b")),
             ("doc_get", {}, lambda p: judged.append(p) or True,
              ("second", lambda p: captured.append(p) or "session:a")),
             ("model_write", {}, "ok", None)],
            {}, sleep_s=0, document_pin=pin, guarded_tools={"model_write"})
        assert [row[1] for row in rows] == ["blocked", "blocked", "blocked"]
        assert judged == [] and captured == []
        assert not any(tool == "model_write" for tool, _args in seen)

    def test_pending_activation_is_settled_before_the_following_write(self, monkeypatch):
        seen = []
        active = ["session:pinned"]

        def call(tool, args):
            seen.append((tool, dict(args)))
            if tool == "doc_activate":
                active[0] = "session:target"
                return False, {"activated": "pending"}
            if tool == "doc_get":
                return False, {"active": {"name": "Target", "document_id": "urn:target",
                                           "document_handle": active[0]}}
            if tool == "design_get":
                return False, {"feature_count": 2}
            return False, {}
        monkeypatch.setattr(tool_verify, "call", call)
        pin = {"state": "known", "handle": "session:pinned",
               "snapshot": {"state": "known", "document_handle": "session:pinned"},
               "known_documents": {}}
        rows = tool_verify.run_steps(
            [("doc_activate", {"name": "session:target"}, "ok", None),
             ("a_get", {}, "ok", None)], {}, sleep_s=0, document_pin=pin,
            guarded_tools={"doc_activate", "a_get"})
        assert [r[1] for r in rows] == ["pass", "pass"]
        assert seen[0] == ("doc_activate", {
            "name": "session:target", "expect_document": "session:pinned"})
        assert seen[-1] == ("a_get", {"expect_document": "session:target"})

    def test_unsettled_activation_blocks_the_following_write(self, monkeypatch):
        seen = []

        def call(tool, args):
            seen.append((tool, dict(args)))
            if tool == "doc_activate":
                return False, {"activated": "pending"}
            if tool == "doc_get":
                return False, {"active": {"name": "Pinned", "document_id": "urn:pinned",
                                           "document_handle": "session:pinned"}}
            if tool == "design_get":
                return False, {"feature_count": 2}
            return False, {}
        monkeypatch.setattr(tool_verify, "call", call)
        monkeypatch.setattr(verify_runner.time, "sleep", lambda _seconds: None)
        pin = {"state": "known", "handle": "session:pinned",
               "snapshot": {"state": "known", "document_handle": "session:pinned"},
               "known_documents": {}}
        rows = tool_verify.run_steps(
            [("doc_activate", {"name": "session:target"}, "ok", None),
             ("a_get", {}, "ok", None)], {}, sleep_s=0, document_pin=pin,
            guarded_tools={"doc_activate", "a_get"})
        assert [r[1] for r in rows] == ["blocked", "blocked"]
        assert [tool for tool, _args in seen].count("doc_activate") == 1
        assert not any(tool == "a_get" for tool, _args in seen)

    def test_shoot_reads_the_stubbed_wire_and_names_the_file(self, monkeypatch, tmp_path):
        seen = []
        monkeypatch.setattr(tool_verify, "call",
                            lambda tool, args: (seen.append((tool, args)), (False, {}))[1])
        path = tool_verify._shoot("Frame:1", str(tmp_path), 3)
        assert seen and seen[0][0] == "view_screenshot"
        assert path == seen[0][1]["file_path"] and "0003_Frame_1" in path
        monkeypatch.setattr(tool_verify, "call", lambda tool, args: (True, "no viewport"))
        assert tool_verify._shoot("x", str(tmp_path), 4) is None

    def test_poll_generation_reads_the_stubbed_wire_and_story(self, monkeypatch):
        monkeypatch.setattr(tool_verify, "call",
                            lambda tool, args: (False, {"completed": True,
                                                        "live_states": {"valid": 4},
                                                        "empty_toolpaths": []}))
        monkeypatch.setattr(tool_verify, "STORY", {"cam_get_status": "stubbed story line"})
        rows, notes, valued = [], {}, set()
        tool_verify.poll_generation(rows, notes, "FacadeSetup", valued=valued)
        assert rows == [("cam_get_status", "pass", "4 valid, non-empty toolpaths")]
        assert notes["cam_get_status"] == "stubbed story line"
        assert valued == {"cam_get_status"}

    def test_check_reads_the_stubbed_source_hash(self, monkeypatch, tmp_path):
        receipt = tmp_path / "VERIFIED_TOOLS.md"
        stamp = ("Stamp: source " + "ab" * 32 + " | Fusion 2705.1.4 | verified fixture\n"
                 + "Loaded: implementation " + "a" * 64 + " | schema " + "b" * 64
                 + " | load fixture-load | session fixture-session\n")
        receipt.write_text(stamp, encoding="utf-8")
        monkeypatch.setattr(tool_verify, "source_hash", lambda root=None: "ab" * 32)
        assert tool_verify.check(verified_path=str(receipt)) == 0
        monkeypatch.setattr(tool_verify, "source_hash", lambda root=None: "cd" * 32)
        assert tool_verify.check(verified_path=str(receipt)) == 1


_SCHEDULED = ("Reload scheduled. Make your next tool call after ~3 seconds - the connection "
              "reconnects automatically.")


def _harness_bound(port=None):
    """The 'bound' row a server on the harness's own endpoint publishes."""
    host, port = verify_core.ENDPOINT.HOST, port or verify_core.ENDPOINT.DEFAULT_PORT
    return {"host": host, "port": port, "mcp_url": f"http://{host}:{port}/mcp"}


def _reload_wire(reload_answer=(False, _SCHEDULED), found=("sys_reload_addin", "doc_get"),
                 map_bound=None, home_name="Home", scratch_name="Canary"):
    """A mutable session for the reload lifecycle without Autodesk objects."""
    state = {"active": "session:home", "documents": {
        "session:home": home_name, "session:other": "Other"}, "parameters": {}, "seen": []}

    def call(tool, args):
        state["seen"].append((tool, dict(args)))
        if tool == "sys_capability_map":
            return False, {"bound": map_bound or _harness_bound()}
        if tool == "doc_get":
            active = state["active"]
            return False, {"active": {"name": state["documents"][active],
                                      "document_handle": active},
                           "truncated": False, "open_count": len(state["documents"]),
                           "open_documents": [{"name": name, "document_handle": handle,
                                               **({"is_active": True} if handle == active else {})}
                                              for handle, name in state["documents"].items()]}
        if tool == "doc_new":
            state["active"] = "session:canary-old"
            state["documents"][state["active"]] = scratch_name
            return False, {"created": True, "document_handle": state["active"]}
        if tool == "sys_reload_addin":
            if isinstance(reload_answer, Exception):
                raise reload_answer
            if reload_answer == (False, _SCHEDULED):
                state["documents"] = {handle + "-new": name
                                      for handle, name in state["documents"].items()}
                state["active"] += "-new"
            return reload_answer
        if tool == "doc_activate":
            assert args.get("expect_document") == state["active"]
            if args["name"] not in state["documents"]:
                return True, "unknown_document_handle"
            state["active"] = args["name"]
            return False, {"activated": True}
        if tool == "doc_close":
            assert args.get("expect_document") == state["active"]
            name = state["documents"].pop(args["name"])
            if state["active"] == args["name"]:
                state["active"] = next(h for h, n in state["documents"].items() if n == "Other")
            return False, {"closed": [name], "closed_count": 1}
        if tool in ("param_add", "param_delete"):
            expected = args.get("expect_document")
            if expected not in state["documents"]:
                return True, {"blocked_by": ["unknown_document_handle"]}
            assert expected == state["active"]
            if tool == "param_delete":
                state["parameters"].pop(args["name"])
                return False, {"deleted": True}
            value = int(args["expression"].split()[0])
            state["parameters"][args["name"]] = value
            return False, {"added": True, "parameter": {"name": args["name"], "value": value}}
        if tool == "param_get":
            assert set(args) == {"name"}
            if args["name"] in state["parameters"]:
                return False, {"parameter": {"name": args["name"],
                                             "value": state["parameters"][args["name"]]}}
            return True, f"Parameter not found: '{args['name']}'."
        return False, {"query": args.get("query"), "tool_count": len(found),
                       "tools": [{"tool": name} for name in found]}
    call.state = state
    return call


def _health(*states):
    """A stubbed /health probe answering `states` in order and then holding the last one, so a
    poll that keeps asking sees a server that stays where the sequence left it."""
    seq = list(states)
    return lambda timeout=None: seq.pop(0) if len(seq) > 1 else seq[0]


def _urlopen(body=None, raises=None):
    """A stand-in for urllib.request.urlopen: a context manager whose read() answers `body` as a
    JSON document, or a raise standing in for a socket that answers nothing."""
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(body).encode("utf-8")

    def urlopen(url, timeout=None):
        if raises is not None:
            raise raises
        return _Response()
    return urlopen


class TestReloadBeat:
    """The post-run beat that drives sys_reload_addin. It claims a covered row ONLY for a restart
    it watched happen: the reload is deferred, so the server is still answering when the call
    returns, and every path below that cannot see /health go down and come back leaves the tool in
    its skipped bucket instead of banking a row."""

    @staticmethod
    def _drive(monkeypatch, call, answers, story="stubbed reload story", health_bound=None):
        monkeypatch.setattr(tool_verify, "call", call)
        monkeypatch.setattr(tool_verify, "_post", lambda *a, **kw: (
            {"result": {"serverInfo": {"name": tool_verify.SERVER_NAME}}}, "session-before"))
        monkeypatch.setattr(verify_acts_doc, "_reload_session_probe", lambda *a:
                            call("doc_get", {})[1]["active"]["document_handle"])
        monkeypatch.setattr(tool_verify, "_server_answers", answers)
        monkeypatch.setattr(tool_verify, "_health_bound",
                            lambda: health_bound or _harness_bound())
        monkeypatch.setattr(tool_verify, "STORY", {"sys_reload_addin": story})
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        rows, notes, valued = [], {}, set()
        tool_verify.reload_smoke(rows, notes, valued=valued, down_polls=3, up_polls=3)
        return rows, notes, valued

    def test_a_watched_restart_banks_one_covered_row(self, monkeypatch):
        rows, notes, valued = self._drive(
            monkeypatch, _reload_wire(), _health(True, False, True))
        assert [(t, s) for t, s, _ in rows] == [("sys_reload_addin", "pass")]
        assert "answered again" in rows[0][2] and "sys_reload_addin among them" in rows[0][2]
        assert notes["sys_reload_addin"] == "stubbed reload story"
        assert valued == {"sys_reload_addin"}
        assert f"both publish {tool_verify.MCP} as bound" in rows[0][2]

    def test_success_sink_keeps_reload_census_sessions_and_actual_checks(self, monkeypatch, tmp_path):
        wire = _reload_wire(home_name="Untitled", scratch_name="Untitled")
        def call(tool, args):
            if tool == "workspace_orient":
                return False, {"fusion_version": "Fusion-1"}
            return wire(tool, args)
        expected = dict(_ATTESTATION, complete=True, loaded_matches_source=True)
        after = dict(expected, load_id="fresh-load", session_id="fresh-health-session")
        monkeypatch.setattr(tool_verify, "call", call)
        monkeypatch.setattr(tool_verify, "_post", lambda *a, **kw: (
            {"result": {"serverInfo": {"name": tool_verify.SERVER_NAME}}}, "session-before"))
        health_states = iter(({"attestation": expected, "session_id": expected["session_id"]},
                              {"attestation": after, "session_id": after["session_id"]}))
        monkeypatch.setattr(tool_verify, "health_gate", lambda: next(health_states))
        monkeypatch.setattr(tool_verify, "registered_tools", lambda _health: ["doc_get", "sys_reload_addin"])
        monkeypatch.setattr(tool_verify, "_health_bound", lambda: _harness_bound())
        monkeypatch.setattr(tool_verify, "_server_answers", _health(True, False, True))
        monkeypatch.setattr(tool_verify.time, "sleep", lambda _seconds: None)

        def fresh_session(old, _handle, evidence):
            evidence["after_mcp_session"] = "session-after"
            evidence["fresh_transport_document_handle"] = call("doc_get", {})[1]["active"]["document_handle"]
            evidence.setdefault("checks", {}).update({"old_transport_refused_empty_404": True,
                "fresh_session_changed": old != "session-after", "fresh_session_read_new_handle": True})
            return evidence["fresh_transport_document_handle"]

        monkeypatch.setattr(verify_acts_doc, "_reload_session_probe", fresh_session)
        sink, rows = {}, []
        verify_acts_doc.reload_smoke(rows, {}, expected_attestation=expected, evidence=sink,
            before_tool_census=["doc_get", "sys_reload_addin"],
            expected_fusion_version="Fusion-1")
        assert rows and sink["before_mcp_session"] == "session-before"
        assert sink["after_mcp_session"] == "session-after"
        assert sink["pre_reload_census"]["rows"] and sink["post_reload_census"]["rows"]
        assert [row["name"] for row in sink["pre_reload_census"]["rows"]] == [
            "Untitled", "Other"]
        assert sum(row["name"] == "Untitled" for row in sink["post_reload_census"]["rows"]) == 2
        assert "fusion_version" not in sink["after_health"]
        assert sink["after_build_observation"]["fusion_version"] == "Fusion-1"
        assert sink["restored_census"]["name"] == "Untitled"
        assert sink["checks"]["fresh_handle_write_readback"] is True
        life = verify_runner.verify_receipts.make_lifecycle(
            sink, "native-run", "a" * 64, "Fusion-1", evidence_dir=tmp_path / "results")
        assert life["before_mcp_session"] == "session-before"
        assert life["scratch_cleanup_census"]["rows"]

    def test_pre_reload_health_exit_fails_and_cleans_owned_scratch(self, monkeypatch):
        wire = _reload_wire()
        monkeypatch.setattr(tool_verify, "call", wire)
        monkeypatch.setattr(tool_verify, "_post", lambda *a, **kw: (
            {"result": {"serverInfo": {"name": tool_verify.SERVER_NAME}}}, "session-before"))
        monkeypatch.setattr(tool_verify, "health_gate", lambda: (_ for _ in ()).throw(SystemExit(1)))
        expected = dict(_ATTESTATION, complete=True, loaded_matches_source=True)
        rows = []

        verify_acts_doc.reload_smoke(rows, {}, expected_attestation=expected)

        tools = [tool for tool, _args in wire.state["seen"]]
        assert rows == []
        assert "sys_reload_addin" not in tools
        assert "doc_close" in tools
        assert sorted(wire.state["documents"].values()) == ["Home", "Other"]
        assert wire.state["documents"][wire.state["active"]] == "Home"

    @pytest.mark.parametrize("where", ["health", "map"])
    @pytest.mark.parametrize("wrong", [
        dict(_harness_bound(), port=40123),
        dict(_harness_bound(), mcp_url="http://127.0.0.1:40123/mcp"),
        {"host": None, "port": None, "mcp_url": None},
    ], ids=["another port", "another url", "no address"])
    def test_a_restart_on_another_endpoint_banks_nothing(self, monkeypatch, where, wrong):
        # each read is compared with the URL the harness connected on, on its own: either one
        # publishing another port, another URL, or no address at all, leaves the beat unbanked.
        rows, _notes, valued = self._drive(
            monkeypatch, _reload_wire(map_bound=wrong if where == "map" else None),
            _health(True, False, True), health_bound=wrong if where == "health" else None)
        assert rows == [] and valued == set()

    @pytest.mark.parametrize("failure", ["nonce", "reload", "registry", "fresh_write"])
    def test_failed_reload_stage_cleans_owned_scratch_and_restores_home(
            self, monkeypatch, failure):
        wire = _reload_wire()

        def call(tool, args):
            if ((failure == "nonce" and tool == "param_add"
                 and args["name"].startswith("ReloadNonce"))
                    or (failure == "reload" and tool == "sys_reload_addin")
                    or (failure == "registry" and tool == "sys_find_tool")
                    or (failure == "fresh_write" and tool == "param_add"
                        and args["name"] == "ReloadRecovered")):
                return True, "deliberate stage failure"
            return wire(tool, args)

        rows, notes, valued = self._drive(monkeypatch, call, _health(True, False, True))
        assert not rows and not notes and not valued
        assert sorted(wire.state["documents"].values()) == ["Home", "Other"]
        assert wire.state["documents"][wire.state["active"]] == "Home"
        assert any(tool == "doc_close" for tool, _args in wire.state["seen"])

    def test_close_refusal_preserves_failure_and_still_restores_home(self, monkeypatch):
        wire = _reload_wire()

        def call(tool, args):
            return (True, "close refused") if tool == "doc_close" else wire(tool, args)

        rows, _notes, valued = self._drive(monkeypatch, call, _health(True, False, True))
        assert not rows and not valued
        assert "Canary" in wire.state["documents"].values()
        assert wire.state["documents"][wire.state["active"]] == "Home"

    @pytest.mark.parametrize("count", [True, 2.0, None])
    def test_invalid_census_count_refuses_before_scratch_creation(self, monkeypatch, count):
        wire = _reload_wire()

        def call(tool, args):
            error, payload = wire(tool, args)
            if tool == "doc_get":
                payload["open_count"] = count
            return error, payload

        rows, _notes, valued = self._drive(monkeypatch, call, _health(True, False, True))
        assert not rows and not valued
        assert [tool for tool, _args in wire.state["seen"]] == ["doc_get"]

    def test_a_server_that_never_goes_down_banks_nothing(self, monkeypatch):
        # The false positive the down-then-up watch exists to refuse: the reload is DEFERRED, so a
        # /health read taken when the call returns answers healthy whether or not the reload ever
        # fires. A beat that only waited for /health to answer would call this a restart.
        rows, notes, valued = self._drive(monkeypatch, _reload_wire(), _health(True))
        assert rows == [] and notes == {} and valued == set()

    def test_a_server_that_does_not_come_back_banks_nothing(self, monkeypatch):
        rows, _notes, valued = self._drive(monkeypatch, _reload_wire(), _health(True, False))
        assert rows == [] and valued == set()

    def test_a_reload_that_was_not_scheduled_banks_nothing(self, monkeypatch):
        # the tool's own refusal path (its deferred-reload event is not installed): nothing was
        # scheduled, so nothing restarts and the beat must not go on to watch for one.
        rows, _notes, valued = self._drive(
            monkeypatch, _reload_wire(reload_answer=(True, "Reload NOT scheduled: ...")),
            _health(True, False, True))
        assert rows == [] and valued == set()

    def test_an_ok_that_does_not_say_scheduled_banks_nothing(self, monkeypatch):
        rows, _notes, valued = self._drive(
            monkeypatch, _reload_wire(reload_answer=(False, "something else entirely")),
            _health(True, False, True))
        assert rows == [] and valued == set()

    def test_a_call_cut_off_by_the_teardown_banks_nothing(self, monkeypatch):
        # the response can be cut mid-flush; the beat reports that rather than raising through run
        rows, _notes, valued = self._drive(
            monkeypatch, _reload_wire(reload_answer=OSError("connection reset")),
            _health(True, False, True))
        assert rows == [] and valued == set()

    def test_a_registry_missing_the_tool_banks_nothing(self, monkeypatch):
        # /health answering is the SERVER being back; the registry answering with the tool is the
        # add-in being back. A restart that loaded no tools passes the first and fails here.
        rows, _notes, valued = self._drive(
            monkeypatch, _reload_wire(found=()), _health(True, False, True))
        assert rows == [] and valued == set()

    def test_the_smoke_read_failing_banks_nothing(self, monkeypatch):
        def call(tool, args):
            return (False, _SCHEDULED) if tool == "sys_reload_addin" else (True, "no such tool")
        rows, _notes, valued = self._drive(monkeypatch, call, _health(True, False, True))
        assert rows == [] and valued == set()

    def test_the_probe_answers_true_only_for_this_server(self, monkeypatch):
        # /health answering is not the add-in being back: another server holding the port answers
        # it too - the state health_gate hard-exits the run on - and reading that as the restart
        # would bank a covered row for a reload nobody observed.
        monkeypatch.setattr(urllib.request, "urlopen",
                            _urlopen({"server": tool_verify.SERVER_NAME, "version": "t"}))
        assert tool_verify._server_answers() is True
        monkeypatch.setattr(urllib.request, "urlopen",
                            _urlopen({"server": "Autodesk Fusion 360"}))
        assert tool_verify._server_answers() is False

    def test_a_probe_that_cannot_be_read_answers_not_up(self, monkeypatch):
        # connection-refused is the state the down-watch waits FOR. Reading a failed probe as 'up'
        # would leave that watch unable to fire, and the beat unable to record anything, silently.
        monkeypatch.setattr(urllib.request, "urlopen",
                            _urlopen(raises=OSError("connection refused")))
        assert tool_verify._server_answers() is False

    def test_poll_health_reads_the_stubbed_probe_and_gives_up_on_its_budget(self, monkeypatch):
        # the facade site: _poll_health must read the probe a consumer stubs ON tool_verify, and a
        # budget that runs out is False - never the state it was waiting for.
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        monkeypatch.setattr(tool_verify, "_server_answers", _health(True, True, False))
        assert tool_verify._poll_health(False, 3) is True
        monkeypatch.setattr(tool_verify, "_server_answers", _health(True))
        assert tool_verify._poll_health(False, 3) is False

    def test_run_fires_the_beat_after_every_act(self, monkeypatch):
        # the call SITE: the beat runs once the acts are done (it restarts the server, so nothing
        # can follow it) and its covered row reaches the ledger.
        ledger = {}

        def fake_write(rows, version, date, src_hash, path=None, notes=None, act_modes=None, attestation=None):
            ledger.update(rows)
            return "VERIFIED_TOOLS.md"

        seen = []
        wire = _reload_wire(found=tuple(sorted({"a_get", "sys_reload_addin", *_ADMISSION_PENDING}
                                              | {"doc_new", "doc_close", "doc_activate", "param_add", "param_get", "param_delete", "view_switch_workspace", "workspace_orient", "sys_find_tool", "sys_capability_map"})))
        reload_scheduled = {"value": False}

        def call(tool, args):
            seen.append(tool)
            if tool == "sys_get_preferences":
                return _preference_reply()
            if tool == "sys_reload_addin":
                reload_scheduled["value"] = True
            if tool == "a_get":
                return False, {"n": 1}
            if tool == "design_get":
                return False, {"feature_count": 1}
            return wire(tool, args)

        monkeypatch.setattr(tool_verify, "call", call)
        monkeypatch.setattr(tool_verify, "_post", lambda *a, **kw: (
            {"result": {"serverInfo": {"name": tool_verify.SERVER_NAME}}}, "session-before"))
        monkeypatch.setattr(verify_acts_doc, "_reload_session_probe", lambda *a:
                            call("doc_get", {})[1]["active"]["document_handle"])
        monkeypatch.setattr(tool_verify, "_server_answers", _health(True, False, True))
        monkeypatch.setattr(tool_verify, "_health_bound", _harness_bound)
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        monkeypatch.setattr(tool_verify, "health_gate", lambda: _attested_health(
            _reloaded_attestation() if reload_scheduled["value"] else _ATTESTATION))
        registry_health = []

        def registered(health=None, include_rows=False):
            registry_health.append(health)
            names = sorted({"a_get", "sys_reload_addin", *_ADMISSION_PENDING}
                           | {"doc_new", "doc_close", "doc_activate", "param_add", "param_get", "param_delete", "view_switch_workspace", "workspace_orient", "sys_find_tool", "sys_capability_map"})
            rows = [{"name": name, "annotations": {"readOnlyHint": True},
                     "inputSchema": {"properties": {"expect_document": {}}}}
                    for name in names]
            return (names, tuple(rows)) if include_rows else names

        monkeypatch.setattr(tool_verify, "registered_tools", registered)
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: "0" * 64)
        monkeypatch.setattr(tool_verify, "write_verified", fake_write)
        monkeypatch.setattr(tool_verify, "POLL_AFTER", {})
        monkeypatch.setattr(tool_verify, "EXCLUDED", {"sys_reload_addin": "not confirmed"})
        monkeypatch.setattr(tool_verify, "STORY", {})
        monkeypatch.setattr(tool_verify, "ACTS",
                            [("ACT T", None, [("a_get", {}, lambda p: p["n"] == 1, None)], None)])

        assert tool_verify.run(write_json=False) == 0
        assert ledger == {"a_get": "covered", "sys_reload_addin": "covered",
                          **{tool: "PENDING (no step yet)" for tool in {"doc_new", "doc_close", "doc_activate", "param_add", "param_get", "param_delete", "view_switch_workspace", "workspace_orient", "sys_find_tool", "sys_capability_map"}},
                          **_ADMISSION_PENDING}
        assert seen[:3] == ["doc_get", "sys_get_preferences", "a_get"]
        assert seen.index("sys_reload_addin") < seen.index("sys_find_tool")
        assert "param_add" in seen and "param_delete" in seen
        assert [row["session_id"] for row in registry_health] == [
            "fixture-session", "fixture-session-2"]

    def test_an_unconfirmed_beat_blocks_the_receipt(self, monkeypatch, capsys):
        # A run cannot publish when its deliberate reload did not establish a new session.
        ledger = {}

        def fake_write(rows, version, date, src_hash, path=None, notes=None, act_modes=None, attestation=None):
            ledger.update(rows)
            return "VERIFIED_TOOLS.md"

        wire = _reload_wire()
        monkeypatch.setattr(tool_verify, "call",
                            lambda tool, args: (_preference_reply() if tool == "sys_get_preferences"
                                               else (False, {"n": 1}) if tool == "a_get"
                                                else wire(tool, args)))
        monkeypatch.setattr(tool_verify, "_post", lambda *a, **kw: (
            {"result": {"serverInfo": {"name": tool_verify.SERVER_NAME}}}, "session-before"))
        monkeypatch.setattr(tool_verify, "_server_answers", _health(True))   # never goes down
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        monkeypatch.setattr(tool_verify, "health_gate", _attested_health)
        monkeypatch.setattr(tool_verify, "registered_tools",
                            _registered(sorted({"a_get", "sys_reload_addin", *_ADMISSION_PENDING}
                                               | {"doc_new", "doc_close", "doc_activate", "param_add", "param_get", "param_delete", "view_switch_workspace", "workspace_orient", "sys_find_tool", "sys_capability_map"})))
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: "0" * 64)
        monkeypatch.setattr(tool_verify, "write_verified", fake_write)
        monkeypatch.setattr(tool_verify, "POLL_AFTER", {})
        monkeypatch.setattr(tool_verify, "EXCLUDED", {"sys_reload_addin": "not confirmed"})
        monkeypatch.setattr(tool_verify, "STORY", {})
        monkeypatch.setattr(tool_verify, "ACTS",
                            [("ACT T", None, [("a_get", {}, lambda p: p["n"] == 1, None)], None)])

        assert tool_verify.run(write_json=False) == 1
        assert ledger == {}
        assert "reload did not establish a new load and session identity" in capsys.readouterr().out
        assert any(tool == "sys_reload_addin" for tool, _args in wire.state["seen"])


_SWITCH_GROUP = "GTF_Test_MCP"
_SWITCH_TOOLS = ("cam_get", "doc_get", "pmi_get", "render_get", "sheet_convert", "sheet_get",
                 "sys_capability_map", "sys_reload_addin")


def _switch_settings(tmp_path, group=_SWITCH_GROUP, text=None, **rows):
    """A Settings file of the test's own, indented unlike the add-in's writer so a reload
    re-serializes it. A keyword sets one row's default; None drops that row."""
    port = verify_core.ENDPOINT.PORT_SETTING
    settings = {"family_enabled_" + family: {"type": "checkbox", "default": True}
                for family in ("cam", "pmi", "render", "sheet")}
    settings[port] = {"type": "number", "default": verify_core.ENDPOINT.DEFAULT_PORT}
    for name, value in rows.items():
        key = port if name == "port" else "family_enabled_" + name
        if value is None:
            del settings[key]
        else:
            settings[key]["default"] = value
    path = tmp_path / "FusionEssentialsSettings.json"
    path.write_bytes(text if text is not None else json.dumps(
        {"OTHER": {"settings": {}}, group: {"name": "MCP Server", "settings": settings}},
        indent=2).encode("ascii"))
    return str(path)


class _SwitchAddin:
    """A stand-in add-in: each reload reads the family rows from the Settings file and writes the
    file back re-serialized, as entry.py and shared_state do. `fault` names one INJECTED fault."""

    def __init__(self, monkeypatch, path, fault=None):
        self.path, self.fault = path, fault
        self.load, self.off, self.seen, self.loaded_bytes, self.in_flight = 0, set(), [], [], None
        monkeypatch.setattr(tool_verify, "call", self.call)
        monkeypatch.setattr(tool_verify, "health_gate", self.health)
        monkeypatch.setattr(tool_verify, "registered_tools", self.registered)
        monkeypatch.setattr(tool_verify.time, "sleep", self.sleep)

    def identity(self):
        schema = "d" if self.fault == "restore changes schema" and self.load > 1 else (
            "c" if self.off else "b")
        return dict(_ATTESTATION, schema_fingerprint=schema * 64,
                    load_id=f"load-{self.load}", session_id=f"session-{self.load}")

    def listed(self):
        names = [name for name in _SWITCH_TOOLS if name.split("_")[0] not in self.off]
        if self.fault == "switch drops doc_get" and self.off:
            names.remove("doc_get")
        if self.fault == "restore loses cam_get" and self.load > 1:
            names.remove("cam_get")
        return names

    def health(self):
        self.seen.append("/health")
        return _attested_health(self.identity())

    def registered(self, _health=None):
        self.seen.append("tools/list")
        return self.listed()

    def call(self, tool, args):
        self.seen.append(tool)
        assert args == {}
        if tool == "sys_capability_map":
            names = self.listed()
            families = {name.split("_")[0] for name in names}
            if self.fault == "map hides pmi":
                families.discard("pmi")
            if self.fault == "map keeps render" and self.off:
                families.add("render")
            one_more = self.fault == "map counts one more" and self.off
            return False, {"families": [{"family": family} for family in sorted(families)],
                           "tool_count": len(names) + (1 if one_more else 0)}
        assert tool == "sys_reload_addin"
        nth = self.seen.count("sys_reload_addin")
        if self.fault == f"reload {nth} raises":
            raise OSError("connection reset")
        if self.fault == f"reload {nth} refuses":
            return True, "reload event is not installed"
        if self.fault == f"reload {nth} loads late":
            self.in_flight = Path(self.path).read_bytes()
        elif self.fault != f"reload {nth} never loads":
            self._load()
        return False, _SCHEDULED

    def _load(self):
        raw = Path(self.path).read_bytes()
        self.loaded_bytes.append(raw)
        data = json.loads(raw)
        self.off = {key[len("family_enabled_"):]
                    for key, row in data[_SWITCH_GROUP]["settings"].items()
                    if key.startswith("family_enabled_") and not row.get("default", True)}
        if self.fault == "sheet row is ignored":
            self.off.discard("sheet")
        Path(self.path).write_text(json.dumps(data, indent=4), encoding="utf-8")
        self.load += 1

    def sleep(self, seconds):
        # The late load lands during the beat's file watch and writes back the rows it read.
        if self.in_flight is not None and seconds == verify_family_switch._SETTLE_GAP_S:
            Path(self.path).write_bytes(self.in_flight)
            self.in_flight = None

    def switch(self, census=None, expected=None):
        rows, valued = [], set()
        got = verify_family_switch.family_switch_smoke(
            rows, expected or self.identity(),
            list(_SWITCH_TOOLS) if census is None else census, valued=valued,
            settings=(self.path, _SWITCH_GROUP), up_polls=3, settle_reads=2)
        return got, rows, valued


class TestFamilySwitchBeat:
    """The post-run beat that writes the Settings file. Every path below ends with the file
    holding what it held, and a reload that does not settle is followed by no wire call."""

    @staticmethod
    def _untouched(path, original):
        return (Path(path).read_bytes() == original
                and not os.path.exists(path + verify_family_switch.BACKUP_SUFFIX))

    def test_the_three_families_are_read_absent_and_the_file_and_tools_come_back(
            self, monkeypatch, tmp_path):
        path = _switch_settings(tmp_path)
        original = Path(path).read_bytes()
        addin = _SwitchAddin(monkeypatch, path)
        got, rows, valued = addin.switch()
        assert got == dict(_ATTESTATION, load_id="load-2", session_id="session-2")
        assert [(tool, status) for tool, status, _ in rows] == [("sys_capability_map", "pass")]
        assert valued == {"sys_capability_map"}
        read_off = json.loads(addin.loaded_bytes[0])[_SWITCH_GROUP]["settings"]
        assert {key: row["default"] for key, row in read_off.items() if "family" in key} == {
            "family_enabled_cam": True, "family_enabled_pmi": False,
            "family_enabled_render": False, "family_enabled_sheet": False}
        assert json.loads(addin.loaded_bytes[0])["OTHER"] == {"settings": {}}
        # the restoring reload read the exact original bytes, and the add-in then re-serialized them
        assert addin.loaded_bytes[1] == original
        assert Path(path).read_bytes() != original
        assert json.loads(Path(path).read_bytes()) == json.loads(original)
        assert not os.path.exists(path + verify_family_switch.BACKUP_SUFFIX)
        assert "lost exactly their 4 tools and kept the other 4" in rows[0][2]
        assert "tool_count read 4 against 8 before" in rows[0][2]
        assert addin.seen == [
            "/health", "sys_capability_map", "sys_reload_addin", "/health", "tools/list",
            "sys_capability_map", "sys_reload_addin", "/health", "tools/list"]

    @pytest.mark.parametrize("build, said", [
        (dict(census=[name for name in _SWITCH_TOOLS if name != "render_get"]), "no render tool"),
        (dict(group="GTF_Other_MCP"), "no 'GTF_Test_MCP' group"),
        (dict(text=b"{not json"), "is not JSON"),
        (dict(sheet=None), "family_enabled_sheet reads None"),
        (dict(pmi=False), "family_enabled_pmi reads False"),
        (dict(cam=False), "family_enabled_cam reads off while the starting tool list has 1 cam"),
        (dict(port=40123), "reads 40123, not the"),
        (dict(expected=dict(_ATTESTATION, load_id="another-load", session_id="session-0")),
         "serving identity differs"),
        (dict(fault="map hides pmi"), "does not list pmi/render/sheet before the switch"),
    ])
    def test_a_refusal_before_the_switch_writes_nothing(self, monkeypatch, tmp_path, build, said):
        census, expected = build.pop("census", None), build.pop("expected", None)
        fault = build.pop("fault", None)
        path = _switch_settings(tmp_path, **build)
        original = Path(path).read_bytes()
        addin = _SwitchAddin(monkeypatch, path, fault=fault)
        if census is not None:
            os.remove(path)     # the tool-list gate comes first: no file is there to open
        got, rows, _valued = addin.switch(census=census, expected=expected)
        assert got is None and [(tool, status) for tool, status, _ in rows] == [
            ("sys_capability_map", "blocked")]
        assert said in rows[0][2], rows[0][2]
        assert "sys_reload_addin" not in addin.seen
        assert addin.seen == [] if census is not None else self._untouched(path, original)

    def test_a_backup_an_earlier_beat_left_blocks_only_when_the_file_differs(
            self, monkeypatch, tmp_path):
        path = _switch_settings(tmp_path)
        original = Path(path).read_bytes()
        backup = Path(path + verify_family_switch.BACKUP_SUFFIX)
        other_rows = original.replace(b'"default": true', b'"default": false', 1)
        assert other_rows != original
        backup.write_bytes(other_rows)
        addin = _SwitchAddin(monkeypatch, path)
        got, rows, _valued = addin.switch()
        assert got is None and rows[0][1] == "blocked" and "differs from" in rows[0][2]
        assert Path(path).read_bytes() == original and backup.exists() and addin.seen == []
        backup.write_bytes(original)
        got, rows, _valued = addin.switch()
        assert got is not None and rows[0][1] == "pass" and not backup.exists()

    @pytest.mark.parametrize("fault, after_reload, said", [
        ("reload 1 refuses", [], "scheduled no reload (reload event is not installed)"),
        ("reload 1 raises", [], "did not answer (connection reset)"),
        ("reload 1 never loads", ["/health"] * 3, "no new load and session identity within 3"),
    ])
    def test_an_unsettled_switch_reload_restores_the_file_and_makes_no_further_call(
            self, monkeypatch, tmp_path, fault, after_reload, said):
        path = _switch_settings(tmp_path)
        original = Path(path).read_bytes()
        addin = _SwitchAddin(monkeypatch, path, fault=fault)
        got, rows, _valued = addin.switch()
        assert got is None and [(tool, status) for tool, status, _ in rows] == [
            ("sys_capability_map", "FAIL")]
        assert said in rows[0][2] and "serving its starting tools and is not read again" in rows[0][2]
        assert self._untouched(path, original)
        assert addin.seen == ["/health", "sys_capability_map", "sys_reload_addin"] + after_reload

    def test_an_unsettled_restoring_reload_leaves_the_file_restored_and_says_what_was_last_read(
            self, monkeypatch, tmp_path):
        path = _switch_settings(tmp_path)
        original = Path(path).read_bytes()
        addin = _SwitchAddin(monkeypatch, path, fault="reload 2 never loads")
        got, rows, _valued = addin.switch()
        assert got is None and rows[0][1] == "FAIL"
        assert "the restoring reload: no new load" in rows[0][2]
        assert "serving without pmi/render/sheet tools and is not read again" in rows[0][2]
        assert self._untouched(path, original)
        assert addin.seen[-4:] == ["sys_reload_addin", "/health", "/health", "/health"]

    def test_a_late_load_that_writes_its_rows_over_the_restore_is_written_over_again(
            self, monkeypatch, tmp_path):
        path = _switch_settings(tmp_path)
        original = Path(path).read_bytes()
        addin = _SwitchAddin(monkeypatch, path, fault="reload 1 loads late")
        got, rows, _valued = addin.switch()
        assert got is None and rows[0][1] == "FAIL"
        assert "after 1 rewrite(s) over other content" in rows[0][2]
        assert self._untouched(path, original)

    @pytest.mark.parametrize("fault, said", [
        ("sheet row is ignored", "2 tool(s) of a switched-off family are still listed"),
        ("switch drops doc_get", "beyond the three families: missing ['doc_get'] (1), added [] (0)"),
        ("map keeps render", "families did not lose exactly the three"),
        ("map counts one more", "tool_count reads 5; 8 before less the 4 switched-off tools is 4"),
        ("restore loses cam_get", "restored tool list differs from the starting one"),
        ("restore changes schema", "does not attest the pinned implementation and schema"),
    ])
    def test_a_failed_read_still_restores_the_file_and_reloads_onto_it(
            self, monkeypatch, tmp_path, fault, said):
        path = _switch_settings(tmp_path)
        original = Path(path).read_bytes()
        addin = _SwitchAddin(monkeypatch, path, fault=fault)
        got, rows, valued = addin.switch()
        assert got is None and valued == set() and [(tool, status) for tool, status, _ in rows] == [
            ("sys_capability_map", "FAIL")]
        assert said in rows[0][2], rows[0][2]
        assert addin.seen.count("sys_reload_addin") == 2 and addin.loaded_bytes[1] == original
        assert json.loads(Path(path).read_bytes()) == json.loads(original)
        assert not os.path.exists(path + verify_family_switch.BACKUP_SUFFIX)

    def test_a_restore_that_cannot_be_written_says_so_and_keeps_the_backup(
            self, monkeypatch, tmp_path):
        path = _switch_settings(tmp_path)
        original = Path(path).read_bytes()
        addin = _SwitchAddin(monkeypatch, path)
        real, writes = verify_family_switch._replace, []

        def replace(target, data):
            writes.append(data)
            if len(writes) > 1:
                raise PermissionError("the file is locked")
            return real(target, data)

        monkeypatch.setattr(verify_family_switch, "_replace", replace)
        got, rows, _valued = addin.switch()
        assert got is None and rows[0][1] == "FAIL"
        assert "is NOT restored (PermissionError: the file is locked)" in rows[0][2]
        assert Path(path + verify_family_switch.BACKUP_SUFFIX).read_bytes() == original
        assert set(writes[1:]) == {original}

    def test_a_switch_that_cannot_be_written_reloads_nothing(self, monkeypatch, tmp_path):
        path = _switch_settings(tmp_path)
        original = Path(path).read_bytes()
        addin = _SwitchAddin(monkeypatch, path)
        monkeypatch.setattr(verify_family_switch, "_replace",
                            lambda target, data: (_ for _ in ()).throw(PermissionError("locked")))
        got, rows, _valued = addin.switch()
        assert got is None and rows[0][1] == "FAIL" and "was not switched" in rows[0][2]
        assert "the add-in was not reloaded" in rows[0][2]
        assert self._untouched(path, original) and "sys_reload_addin" not in addin.seen

    def test_the_run_hands_the_switch_beats_identity_to_the_reload_beat(self, monkeypatch, tmp_path):
        h = _Harness(monkeypatch, tmp_path)
        switched = dict(_ATTESTATION, load_id="switch-load", session_id="switch-session")
        handed = {}

        def switch(rows, expected, census, valued=None):
            handed.update(switch_expected=expected, census=list(census))
            return switched

        def reload(rows, notes, valued=None, **kw):
            handed.update(reload_expected=kw["expected_attestation"])
            return _reloaded_attestation()

        monkeypatch.setattr(tool_verify, "family_switch_smoke", switch)
        monkeypatch.setattr(tool_verify.family_switch_smoke, "support_routes", (), raising=False)
        monkeypatch.setattr(tool_verify, "reload_smoke", reload)
        monkeypatch.setattr(tool_verify.reload_smoke, "support_routes", (), raising=False)
        assert h.run() == 0
        assert handed == {"switch_expected": _ATTESTATION,
                          "census": sorted({"a_get", "b_get", "design_get", *_ADMISSION_PENDING}),
                          "reload_expected": switched}
        assert h.wrote["attestation"] == _reloaded_attestation()

    def test_a_switch_beat_that_stops_refuses_the_run_before_the_reload_beat(
            self, monkeypatch, tmp_path, capsys):
        h = _Harness(monkeypatch, tmp_path)
        monkeypatch.setattr(tool_verify, "family_switch_smoke", lambda rows, *a, **kw: rows.append(
            ("sys_capability_map", "FAIL", "stubbed stop")))
        monkeypatch.setattr(tool_verify.family_switch_smoke, "support_routes", (), raising=False)
        assert h.run() == 1 and not h.wrote and "reload beat" not in h.tools_called()
        assert "family switch beat did not end on the starting tools" in capsys.readouterr().out


class TestActSelection:
    """--acts walks a SLICE of the story against the document a prior --keep-open run left open."""

    _ACTS = [("ACT 0 - OVERTURE", None, [], []),
             ("ACT 10a - CAM: JOB", None, [], []),
             ("ACT 10b - CAM: DELIVERABLES", None, [], []),
             ("ACT 10b2 - CAM: COMPONENT SCOPE", None, [], []),
             ("FINALE", None, [], [])]

    def test_one_selector_picks_exactly_its_act(self):
        assert tool_verify.select_acts(self._ACTS, "ACT 10a") == ["ACT 10a - CAM: JOB"]
        # a selector is a name prefix ending at a WORD BREAK, so 10b is not also 10b2 - a plain
        # startswith would select both and silently run an act nobody asked for.
        assert tool_verify.select_acts(self._ACTS, "ACT 10b") == ["ACT 10b - CAM: DELIVERABLES"]

    def test_a_comma_list_comes_back_in_acts_order(self):
        assert tool_verify.select_acts(self._ACTS, "FINALE, ACT 0") == ["ACT 0 - OVERTURE", "FINALE"]

    def test_a_range_spans_every_act_between_its_ends(self):
        assert tool_verify.select_acts(self._ACTS, "ACT 10a..ACT 10b2") == [
            "ACT 10a - CAM: JOB", "ACT 10b - CAM: DELIVERABLES", "ACT 10b2 - CAM: COMPONENT SCOPE"]

    def test_an_unknown_selector_and_an_empty_selection_are_refused_naming_the_acts(self):
        with pytest.raises(ValueError) as unknown:
            tool_verify.select_acts(self._ACTS, "ACT 99")
        assert "ACT 99" in str(unknown.value) and "ACT 10b2 - CAM: COMPONENT SCOPE" in str(unknown.value)
        with pytest.raises(ValueError) as empty:
            tool_verify.select_acts(self._ACTS, " ")
        assert "selects no act" in str(empty.value)

    # ACT 0 saves the ctx key ACT 10b's arguments recall, so a slice that skips it lands blocked.
    _WALK = [("ACT 0 - OVERTURE", None, [("a_get", {}, "ok", ("k", lambda p: p["n"]))], []),
             ("ACT 10a - CAM: JOB", None, [("b_get", {}, "ok", None)], []),
             ("ACT 10b - CAM: DELIVERABLES", None,
              [("c_get", lambda ctx: {"x": ctx["k"]}, "ok", None)], []),
             ("FINALE", None, [("doc_close", {}, "ok", None)], [])]

    @staticmethod
    def _run(monkeypatch, tools, **kw):
        """run() over the _WALK program on a stubbed wire -> (tools the wire saw, receipt written?,
        exit code)."""
        seen, wrote = [], []
        monkeypatch.setattr(tool_verify, "call",
                            lambda tool, args: (seen.append(tool), _known_wire(tool, args))[1])
        monkeypatch.setattr(tool_verify.time, "sleep", lambda s: None)
        monkeypatch.setattr(tool_verify, "health_gate", _attested_health)
        monkeypatch.setattr(tool_verify, "registered_tools",
                            _registered(sorted(set(tools) | set(_ADMISSION_PENDING)
                                               | ({"doc_activate"} if "doc_close" in tools else set()))))
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: "0" * 64)
        monkeypatch.setattr(tool_verify, "write_verified",
                            lambda *a, **k: wrote.append(True) or "VERIFIED_TOOLS.md")
        monkeypatch.setattr(tool_verify, "reload_smoke",
                            lambda rows, notes, valued=None, **kw2: None)
        monkeypatch.setattr(tool_verify.reload_smoke, "support_routes", (), raising=False)
        monkeypatch.setattr(tool_verify, "POLL_AFTER", {})
        monkeypatch.setattr(tool_verify, "EXCLUDED", {})
        monkeypatch.setattr(tool_verify, "STORY", {})
        monkeypatch.setattr(tool_verify, "ACT_NEEDS", {})
        monkeypatch.setattr(tool_verify, "ACTS", TestActSelection._WALK)
        code = tool_verify.run(write_json=False, **kw)
        assert seen[:2] == ["doc_get", "sys_get_preferences"]
        return seen[2:], wrote, code

    def test_the_runner_walks_only_the_selected_acts(self, monkeypatch, capsys):
        seen, _wrote, code = self._run(monkeypatch, ["a_get", "b_get", "c_get", "doc_close"],
                                       acts_spec="ACT 10a")
        assert seen == ["b_get"] and code == 0
        # the acts that did not run are named once, up front
        out = capsys.readouterr().out
        assert "3 act(s) not run - ACT 0 - OVERTURE, ACT 10b - CAM: DELIVERABLES, FINALE" in out

    def test_a_recall_an_unrun_act_would_have_saved_lands_the_step_blocked(self, monkeypatch,
                                                                          capsys):
        seen, _wrote, code = self._run(monkeypatch, ["c_get"], acts_spec="ACT 10b")
        assert seen == [] and code == 1
        assert "blocked" in capsys.readouterr().out

    def test_a_partial_run_writes_no_receipt_and_says_so_in_its_last_line(self, monkeypatch,
                                                                         capsys):
        _seen, wrote, code = self._run(monkeypatch, ["b_get"], acts_spec="ACT 10a")
        assert not wrote and code == 0
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert lines[-1] == ("partial run (--acts ACT 10a): receipt not written; the story "
                             "document is left open")

    def test_the_document_is_left_open_unless_the_finale_is_selected_and_free_to_close_it(
            self, monkeypatch, capsys):
        _seen, _wrote, _code = self._run(monkeypatch, ["b_get", "doc_close"],
                                         acts_spec="ACT 10a,FINALE")
        assert capsys.readouterr().out.splitlines()[-1] == (
            "partial run (--acts ACT 10a,FINALE): receipt not written")
        # --keep-open drops the FINALE's doc_close in a partial run exactly as in a full one
        seen, _wrote, _code = self._run(monkeypatch, ["doc_close"], acts_spec="FINALE",
                                        keep_open=True)
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert seen == [] and lines[-1].endswith("; the story document is left open")



class _DocumentWire:
    """A session whose exact handles and active tab change like the document tools report."""

    def __init__(self, drift_after_write=False, drift_after_doc_get=None,
                 invalid_handle_tool=None, refuse_close=False,
                 background_after_write=False, doc_open_existing=False):
        self.documents = {
            "session:home": {"name": "Home", "document_id": "urn:home"},
            "session:intruder": {"name": "Intruder", "document_id": "urn:intruder"},
        }
        self.active = "session:home"
        self.drift_after_write = drift_after_write
        self.drift_after_doc_get = drift_after_doc_get
        self.invalid_handle_tool = invalid_handle_tool
        self.refuse_close = refuse_close
        self.background_after_write = background_after_write
        self.doc_open_existing = doc_open_existing
        if doc_open_existing:
            self.documents["session:intruder"]["document_id"] = "urn:sweep"
        self.seen = []
        self.created = 0
        self.doc_reads = 0

    def __call__(self, tool, args):
        self.seen.append((tool, dict(args)))
        if tool == "sys_get_preferences":
            return _preference_reply()
        if tool == "doc_get":
            self.doc_reads += 1
            active = dict(self.documents[self.active], document_handle=self.active,
                          is_saved=bool(self.documents[self.active].get("document_id")),
                          has_data_file=bool(self.documents[self.active].get("document_id")),
                          is_modified=self.documents[self.active].get("is_modified", False))
            rows = [{"name": value["name"], "document_handle": handle,
                     "open_index": index, "is_active": handle == self.active,
                     "is_modified": value.get("is_modified", False)}
                    for index, (handle, value) in enumerate(self.documents.items())]
            payload = {"active": active, "open_documents": rows,
                       "open_count": len(rows), "truncated": False}
            if self.drift_after_doc_get == self.doc_reads:
                self.active = "session:intruder"
            return False, payload
        if tool == "sys_execute_script" and args.get("read_only") and "home Design product" in args.get("script", ""):
            index_reads = [node for node in ast.walk(ast.parse(args["script"]))
                           if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                           and node.func.attr == "item" and isinstance(node.func.value, ast.Attribute)
                           and node.func.value.attr == "documents"]
            handle = (list(self.documents)[index_reads[0].args[0].value]
                      if index_reads else self.active)
            value = self.documents[handle]
            return False, {"document_handle": handle, "name": value["name"],
                           "document_id": value["document_id"],
                           "is_modified": value.get("is_modified", False),
                           "feature_count": value.get("feature_count", 3),
                           "sketch_count": value.get("sketch_count", 2),
                           "body_count": value.get("body_count", 1)}
        if tool == "design_get":
            return False, {"feature_count": 3}
        if tool == "doc_new":
            self.created += 1
            handle = "session:new%d" % self.created
            self.documents[handle] = {"name": "Untitled", "document_id": None}
            self.active = handle
            payload = {"created": True, "document_handle": handle, "is_active": True,
                       "document_name": "Untitled", "is_saved": False}
            if self.invalid_handle_tool == tool:
                payload.pop("document_handle")
            return False, payload
        if tool == "doc_open":
            if self.doc_open_existing:
                self.active = "session:intruder"
                return False, {"opened": True, "document_handle": self.active}
            self.created += 1
            handle = "session:open%d" % self.created
            self.documents[handle] = {"name": "Drawing", "document_id": args["file_id"]}
            self.active = handle
            payload = {"opened": True, "document_handle": handle}
            if self.invalid_handle_tool == tool:
                payload["document_handle"] = "open:2"
            return False, payload
        if tool == "doc_activate":
            target = args["name"]
            if target not in self.documents:
                return True, "not open"
            self.active = target
            return False, {"activated": True,
                           "document_name": self.documents[target]["name"]}
        if tool == "doc_close":
            target = args.get("name") or self.active
            if target not in self.documents:
                return True, "not open"
            if self.refuse_close:
                return True, "close refused"
            name = self.documents.pop(target)["name"]
            if self.active == target:
                self.active = list(self.documents)[-1]
            return False, {"closed": [name], "closed_count": 1, "errors": []}
        if tool in {"doc_new", "doc_open", "doc_activate", "doc_close",
                    "model_write", "view_set", "view_screenshot"}:
            expected = args.get("expect_document")
            if expected and expected != self.active:
                return True, "document mismatch"
        if tool == "model_write":
            if self.background_after_write:
                self.documents["session:user"] = {"name": "User", "document_id": "urn:user"}
                self.background_after_write = False
            if self.drift_after_write:
                self.active = "session:intruder"
                self.drift_after_write = False
            return False, {"changed": True}
        return False, {"ok": True}


def _run_document_program(monkeypatch, tmp_path, wire, acts, writes, run_id=None,
                          shots_dir=None, poll_after=None, reload_smoke=None):
    wrote = {}
    names = sorted({step[0] for _name, _pre, narrative, fallback in acts
                    for step in list(narrative) + list(fallback or [])
                    if step[0] != tool_verify._DWELL} | set(_ADMISSION_PENDING)
                   | {"design_get", "doc_close", "doc_activate"}
                   | ({"view_screenshot"} if shots_dir else set()))
    monkeypatch.setattr(tool_verify, "call", wire)
    monkeypatch.setattr(verify_runner, "time", _Clock(1.0))
    monkeypatch.setattr(verify_runner, "RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(tool_verify, "health_gate", _attested_health)
    monkeypatch.setattr(tool_verify, "registered_tools", _registered(names, writes))
    monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: "0" * 64)
    monkeypatch.setattr(
        tool_verify, "write_verified",
        lambda rows, *a, **k: wrote.update(ledger=dict(rows)) or "VERIFIED_TOOLS.md")
    monkeypatch.setattr(
        tool_verify, "reload_smoke",
        reload_smoke or (lambda rows, notes, valued=None, **kw: _reloaded_attestation()))
    if reload_smoke is None:
        monkeypatch.setattr(tool_verify.reload_smoke, "support_routes", (), raising=False)
    monkeypatch.setattr(tool_verify, "POLL_AFTER", poll_after or {})
    monkeypatch.setattr(tool_verify, "EXCLUDED", {})
    monkeypatch.setattr(tool_verify, "STORY", {})
    monkeypatch.setattr(tool_verify, "ACT_NEEDS", {})
    monkeypatch.setattr(tool_verify, "ACTS", acts)
    tool_verify._RECALL.clear()
    code = tool_verify.run(write_json=False, run_id=run_id, shots_dir=shots_dir)
    return code, wrote


class TestAttributedDrawingDependency:
    @pytest.mark.parametrize("lineage,already_open,admitted", [
        ("urn:source", False, True), ("urn:foreign", False, False),
        ("urn:source", True, False)])
    def test_only_a_new_dependency_with_a_proven_owned_lineage_can_close(
            self, monkeypatch, lineage, already_open, admitted):
        wire = _DocumentWire()
        dependency = "session:dependency"
        if already_open:
            wire.documents[dependency] = {"name": "SameSource", "document_id": lineage}

        def call(tool, args):
            failed, payload = wire(tool, args)
            if tool == "doc_new":
                wire.documents[payload["document_handle"]]["document_id"] = "urn:source"
            elif tool == "doc_open" and not already_open:
                wire.documents[dependency] = {"name": "SameSource", "document_id": lineage}
            return failed, payload

        monkeypatch.setattr(tool_verify, "call", call)
        monkeypatch.setattr(verify_runner, "time", _Clock(1.0))
        steps = [
            ("doc_new", {}, "ok", None),
            ("doc_get", {}, "ok", None),
            ("doc_open", {"file_id": "urn:drawing", "force_api_open": True}, "ok", None),
            ("doc_activate", {"name": dependency}, "ok", None),
            ("doc_get", {}, "ok", None),
            ("doc_activate", {"name": "session:home"}, "ok", None),
            ("doc_close", {"name": dependency, "save_changes": False}, "ok", None),
        ]
        pin = {"track_owned_open": True}
        rows = verify_runner.run_steps(steps, {}, document_pin=pin,
            guarded_tools={"doc_new", "doc_open", "doc_activate", "doc_close"},
            stop_on_failure=True, sleep_s=0)
        assert (rows[-1][1] == "pass") is admitted
        assert (dependency not in wire.documents) is admitted
        assert (dependency in pin["owned_documents"]) is admitted
        assert pin["owned_lineages"] == ["urn:source"]
        assert "session:home" in wire.documents and "session:intruder" in wire.documents
        if not admitted:
            assert rows[-1] == ("doc_close", "blocked", "family cannot close a document it did not open")
            assert not any(tool == "doc_close" for tool, _args in wire.seen)

    def test_a_failed_lineage_read_cannot_admit_a_dependency(self, monkeypatch):
        wire = _DocumentWire()
        wire.documents["session:dependency"] = {"name": "SameSource", "document_id": "urn:source"}
        wire.active = "session:dependency"
        monkeypatch.setattr(tool_verify, "call", wire)
        pin = {"state": "known", "handle": wire.active,
               "snapshot": {"state": "known", "document_handle": wire.active},
               "track_owned_open": True, "owned_documents": ["session:source"],
               "owned_lineages": ["urn:source"], "dependency_candidates": [wire.active]}
        rows = verify_runner.run_steps([("doc_get", {}, lambda p: False, None)], {},
            document_pin=pin, guarded_tools={"doc_close"}, stop_on_failure=True, sleep_s=0)
        assert rows[0][1] == "FAIL"
        assert pin["owned_documents"] == ["session:source"]
        assert pin["dependency_candidates"] == [wire.active]

    @pytest.mark.parametrize("fault", ["truncated", "count", "active_flag", "row_flag"])
    def test_a_partial_passing_read_cannot_admit_a_dependency(self, monkeypatch, fault):
        wire = _DocumentWire()
        wire.documents["session:dependency"] = {"name": "SameSource", "document_id": "urn:source"}
        wire.active = "session:dependency"

        def call(tool, args):
            failed, payload = wire(tool, args)
            if tool == "doc_get":
                if fault == "truncated":
                    payload["truncated"] = True
                elif fault == "count":
                    payload["open_count"] = len(payload["open_documents"]) - 1
                elif fault == "active_flag":
                    payload["active"]["is_saved"] = None
                else:
                    payload["open_documents"][0]["is_modified"] = None
            return failed, payload

        monkeypatch.setattr(tool_verify, "call", call)
        pin = {"state": "known", "handle": wire.active,
               "snapshot": {"state": "known", "document_handle": wire.active},
               "track_owned_open": True, "owned_documents": ["session:source"],
               "owned_lineages": ["urn:source"], "dependency_candidates": [wire.active]}
        rows = verify_runner.run_steps([("doc_get", {}, "ok", None)], {},
            document_pin=pin, guarded_tools={"doc_close"}, stop_on_failure=True, sleep_s=0)
        assert rows[0][1] == "pass"
        assert pin["owned_documents"] == ["session:source"]
        assert pin["dependency_candidates"] == [wire.active]


class TestWithinActDocumentPin:
    def test_canonical_failure_stops_steps_poll_and_acts_then_restores_home(
            self, monkeypatch, tmp_path, capsys):
        wire = _DocumentWire()
        polled = []
        monkeypatch.setattr(
            tool_verify, "poll_generation",
            lambda rows, notes, setup, valued=None, **kw: polled.append(setup))
        monkeypatch.setattr(tool_verify.poll_generation, "support_routes", (), raising=False)
        acts = [
            ("ACT 0 - OVERTURE", None, [
                ("doc_new", {}, lambda p: p["created"] is True, None),
                ("a_get", {}, lambda p: p.get("ok") is False, None),
                ("model_write", {}, lambda p: p["changed"] is True, None),
            ], []),
            ("ACT LATER", None, [
                ("model_write", {}, lambda p: p["changed"] is True, None),
            ], []),
        ]
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, {"doc_new", "model_write"},
            run_id="fail-fast", poll_after={
                "ACT 0 - OVERTURE": {"narrative": "Setup", "fallback": []}})
        called = [tool for tool, _args in wire.seen]
        assert code == 1 and not wrote and not polled
        assert called.count("doc_new") == 1 and "model_write" not in called
        assert wire.active == "session:home" and "session:new1" not in wire.documents
        assert called.index("doc_close") < called.index("doc_activate")
        footer = capsys.readouterr().out
        assert "failed invocation is not resumable" in footer and "--resume" not in footer

    def test_refused_story_close_stays_fatal_but_home_is_restored(
            self, monkeypatch, tmp_path):
        wire = _DocumentWire(refuse_close=True)
        acts = [("ACT 0 - OVERTURE", None, [
            ("doc_new", {}, lambda p: p["created"] is True, None),
            ("a_get", {}, lambda p: p.get("ok") is False, None),
        ], [])]
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, {"doc_new"})
        assert code == 1 and not wrote and wire.active == "session:home"
        assert "session:new1" in wire.documents
        called = [tool for tool, _args in wire.seen]
        assert called.index("doc_close") < called.index("doc_activate")

    def test_unrelated_activated_tab_is_restored_but_never_closed(
            self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        acts = [("ACT SWITCH", None, [
            ("doc_activate", {"name": "session:intruder"}, "ok", None),
            ("a_get", {}, lambda p: p.get("ok") is False, None),
        ], [])]
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, {"doc_activate"})
        called = [tool for tool, _args in wire.seen]
        assert code == 1 and not wrote and wire.active == "session:home"
        assert "session:intruder" in wire.documents and "doc_close" not in called

    def test_argument_exception_stops_and_restores_home(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        acts = [("ACT 0 - OVERTURE", None, [
            ("doc_new", {}, lambda p: p["created"] is True, None),
            ("a_get", lambda _ctx: 1 / 0, "ok", None),
            ("model_write", {}, lambda p: p["changed"] is True, None),
        ], [])]
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, {"doc_new", "model_write"})
        called = [tool for tool, _args in wire.seen]
        assert code == 1 and not wrote and "model_write" not in called
        assert wire.active == "session:home" and "session:new1" not in wire.documents

    def test_result_callback_exception_stops_and_restores_home(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        original = verify_runner.run_steps
        raised = []

        def wrapped(*args, **kwargs):
            def on_result(_tool, _status, _note):
                if not raised:
                    raised.append(True)
                    raise RuntimeError("observer failed")
            return original(*args, on_result=on_result, **kwargs)

        monkeypatch.setattr(verify_runner, "run_steps", wrapped)
        acts = [("ACT 0 - OVERTURE", None, [
            ("doc_new", {}, lambda p: p["created"] is True, None),
            ("model_write", {}, lambda p: p["changed"] is True, None),
        ], [])]
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, {"doc_new", "model_write"})
        called = [tool for tool, _args in wire.seen]
        assert code == 1 and not wrote and raised == [True]
        assert "model_write" not in called
        assert wire.active == "session:home" and "session:new1" not in wire.documents

    def test_clean_completion_restores_home_before_reload(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        at_reload = []

        def reload_smoke(rows, notes, valued=None, **kw):
            at_reload.append(wire.active)
            return _reloaded_attestation()
        monkeypatch.setattr(reload_smoke, "support_routes", (), raising=False)

        acts = [
            ("ACT 0 - OVERTURE", None, [
                ("doc_new", {}, lambda p: p["created"] is True, None),
            ], []),
            ("FINALE", None, [
                ("doc_close", {"save_changes": False}, "ok", None),
            ], []),
        ]
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, {"doc_new", "doc_close"},
            reload_smoke=reload_smoke)
        assert code == 0 and wrote
        assert wire.active == "session:home" and at_reload == ["session:home"]
        called = [tool for tool, _args in wire.seen]
        assert called.index("doc_close") < called.index("doc_activate")

    def test_home_address_requires_the_active_row_exact_handle(self):
        payload = {
            "active": {"name": "Home", "document_handle": "session:home"},
            "open_count": 1,
            "open_documents": [
                {"name": "Home", "open_index": 0, "is_active": True,
                 "document_handle": "session:home"},
            ],
        }
        assert verify_core._home_document(payload) is True
        assert verify_core._home_address(payload) == "session:home"
        payload["active"]["document_handle"] = "session:other"
        with pytest.raises(AssertionError, match="exact session handle"):
            verify_core._home_document(payload)
        with pytest.raises(ValueError, match="exact session handle"):
            verify_core._home_address(payload)

    def test_run_pins_before_the_first_context_read(self, monkeypatch, tmp_path):
        judged, captured = [], []

        def predicate(payload):
            judged.append(payload)
            return True

        def extract(payload):
            captured.append(payload)
            return payload["active"]["document_handle"]

        # Admission reads the first census; drift occurs at the first context-pin census.
        wire = _DocumentWire(drift_after_doc_get=2)
        acts = [("ACT INITIAL PIN", None, [
            ("doc_get", {}, predicate, ("captured", extract)),
            ("model_write", {}, lambda p: p["changed"] is True, None),
        ], [])]
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, {"model_write"}, run_id="initial-drift")
        assert code == 1 and not wrote
        assert judged == [] and captured == []
        assert not any(tool == "model_write" for tool, _args in wire.seen)
        assert not Path(tool_verify.run_state_path("initial-drift")).exists()

    @pytest.mark.parametrize("transition", ["doc_new", "doc_open"])
    def test_invalid_transition_handle_blocks_later_write_and_checkpoint(
            self, monkeypatch, tmp_path, transition):
        wire = _DocumentWire(invalid_handle_tool=transition)
        args = {} if transition == "doc_new" else {
            "file_id": "urn:drawing", "force_api_open": True}
        key = "created" if transition == "doc_new" else "opened"
        acts = [("ACT INVALID TRANSITION", None, [
            (transition, args, lambda p: p[key] is True, None),
            ("model_write", {}, lambda p: p["changed"] is True, None),
        ], [])]
        run_id = "invalid-" + transition
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, {transition, "model_write"}, run_id=run_id)
        assert code == 1 and not wrote
        assert [tool for tool, _args in wire.seen].count(transition) == 1
        assert not any(tool == "model_write" for tool, _args in wire.seen)
        assert not Path(tool_verify.run_state_path(run_id)).exists()

    def test_authored_positive_guard_cannot_bypass_the_run_pin(
            self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        acts = [("ACT AUTHORED GUARD", None, [
            ("model_write", {"expect_document": "session:intruder"},
             lambda p: p["changed"] is True, None),
        ], [])]
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, {"model_write"}, run_id="authored")
        assert code == 1 and not wrote
        assert not any(tool == "model_write" for tool, _args in wire.seen)

    def test_intruder_doc_get_blocks_save_write_and_checkpoint(self, monkeypatch, tmp_path):
        judged, captured = [], []
        wire = _DocumentWire(drift_after_write=True)
        acts = [("ACT PIN", None, [
            ("model_write", {}, lambda p: p["changed"] is True, None),
            ("doc_get", {}, lambda p: judged.append(p) or True,
             ("captured", lambda p: captured.append(p) or p["active"]["document_handle"])),
            ("doc_activate", {"name": "session:home"}, "ok", None),
            ("model_write", {}, lambda p: p["changed"] is True, None),
        ], [])]
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, {"model_write", "doc_activate"},
            run_id="intruder")
        calls = [(tool, args) for tool, args in wire.seen if tool == "model_write"]
        assert code == 1 and not wrote and len(calls) == 1
        assert calls[0][1]["expect_document"] == "session:home"
        assert judged == [] and captured == []
        assert not any(tool == "doc_activate" for tool, _args in wire.seen)
        assert not Path(tool_verify.run_state_path("intruder")).exists()

    def test_active_closes_recover_only_through_exact_activation(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        wire.documents.pop("session:intruder")
        acts = [("ACT DOCUMENTS", None, [
            ("doc_get", {}, lambda p: p["active"]["name"] == "Home",
             ("home", lambda p: p["active"]["document_handle"])),
            ("doc_new", {}, lambda p: p["created"] is True, None),
            ("model_write", {}, lambda p: p["changed"] is True, None),
            ("doc_get", {}, lambda p: p["active"]["name"] == "Untitled",
             ("source", lambda p: p["active"]["document_handle"])),
            ("doc_open", {"file_id": "urn:drawing", "force_api_open": True},
             lambda p: p["opened"] is True, None),
            ("view_set", {"focus": ["drawing"]}, "ok", None),
            ("doc_get", {}, lambda p: p["active"]["name"] == "Drawing",
             ("drawing", lambda p: p["active"]["document_handle"])),
            ("doc_activate", lambda c: {"name": c["source"]}, "ok", None),
            ("doc_activate", {"name": "urn:drawing"}, "ok", None),
            ("doc_close", lambda c: {"name": c["drawing"]}, "ok", None),
            ("doc_close", lambda c: {"name": c["source"]}, "ok", None),
            ("doc_activate", lambda c: {"name": c["home"]}, "ok", None),
            ("model_write", {}, lambda p: p["changed"] is True, None),
        ], [])]
        writes = {"doc_new", "doc_open", "view_set", "doc_close", "doc_activate",
                  "model_write"}
        code, wrote = _run_document_program(
            monkeypatch, tmp_path, wire, acts, writes, run_id="recovery",
            shots_dir=str(tmp_path / "shots"))
        assert code == 0 and wrote
        guarded = [(tool, args["expect_document"]) for tool, args in wire.seen
                   if tool in writes]
        assert guarded == [
            ("doc_new", "session:home"),
            ("model_write", "session:new1"),
            ("doc_open", "session:new1"),
            ("view_set", "session:open2"),
            ("doc_activate", "session:open2"),
            ("doc_activate", "session:new1"),
            ("doc_close", "session:open2"),
            ("doc_close", "session:new1"),
            ("doc_activate", "session:home"),
            ("model_write", "session:home"),
        ]
        shots = [args for tool, args in wire.seen if tool == "view_screenshot"]
        assert shots and shots[0]["expect_document"] == "session:open2"
        saved = tool_verify.load_run_state("recovery")
        assert saved["complete"] is True
        assert saved["document"]["document_handle"] == "session:home"
        assert saved["document"]["feature_count"] == 3

class TestActualSchemaBinding:
    def test_identity_requires_a_load_id_and_session_id(self):
        missing_load = _attested_health()
        missing_load["attestation"].pop("load_id")
        empty_session = _attested_health()
        empty_session["session_id"] = ""
        assert verify_core.attestation_identity(missing_load) is None
        assert verify_core.attestation_identity(empty_session) is None

    def test_registry_rows_must_match_the_health_schema_and_session(self, monkeypatch):
        rows = [{"name": "a_get", "description": "read", "inputSchema": {"type": "object"}}]
        response = {"result": {"tools": rows}}
        identity = dict(_ATTESTATION, schema_fingerprint=verify_core._schema_fingerprint(rows))
        health = _attested_health(identity)
        monkeypatch.setattr(verify_core, "_post",
                            lambda payload, with_session=False: (response, identity["session_id"]))
        assert verify_core.registered_tools(health) == ["a_get"]

        wrong_schema = _attested_health(dict(identity, schema_fingerprint="c" * 64))
        with pytest.raises(SystemExit, match="schema fingerprint"):
            verify_core.registered_tools(wrong_schema)
        monkeypatch.setattr(verify_core, "_post",
                            lambda payload, with_session=False: (response, "another-session"))
        with pytest.raises(SystemExit, match="session changed"):
            verify_core.registered_tools(health)



class TestDocumentHandleLifecycleRows:
    @pytest.mark.parametrize("case", [
        "good", "stale_admitted", "stale_400", "stale_body", "init_same",
        "init_wrong_server", "fresh_error", "fresh_old_handle",
    ])
    def test_reload_transport_requires_refusal_then_fresh_identity(self, monkeypatch, case):
        requests, initialized = [], []

        def post(payload, with_session=False):
            initialized.append(payload)
            assert with_session and payload["method"] == "initialize"
            server = "wrong-server" if case == "init_wrong_server" else tool_verify.SERVER_NAME
            session = "old-session" if case == "init_same" else "new-session"
            return {"result": {"serverInfo": {"name": server}}}, session

        def opened(request, timeout=None):
            requests.append(request)
            headers = {k.lower(): v for k, v in request.header_items()}
            sent = json.loads(request.data)
            assert sent["params"] == {"name": "doc_get", "arguments": {}}
            if len(requests) == 1:
                assert headers["mcp-session-id"] == "old-session"
                if case == "stale_admitted":
                    return _urlopen({})(request, timeout)
                raise urllib.error.HTTPError(request.full_url,
                    400 if case == "stale_400" else 404, "expired", {},
                    io.BytesIO(b"html" if case == "stale_body" else b""))
            assert headers["mcp-session-id"] == "new-session"
            handle = "session:old-document" if case == "fresh_old_handle" else "session:new-document"
            return _urlopen({"result": {"isError": case == "fresh_error", "content": [
                {"type": "text", "text": json.dumps({"active": {"document_handle": handle}})}
            ]}})(request, timeout)

        monkeypatch.setattr(tool_verify, "_post", post)
        monkeypatch.setattr(verify_acts_doc.urllib.request, "urlopen", opened)
        if case == "good":
            assert verify_acts_doc._reload_session_probe(
                "old-session", "session:old-document") == "session:new-document"
            assert len(requests) == 2 and len(initialized) == 1
        else:
            with pytest.raises(RuntimeError):
                verify_acts_doc._reload_session_probe("old-session", "session:old-document")
            assert len(requests) == (2 if case.startswith("fresh_") else 1)
            assert len(initialized) == (1 if case.startswith(("init_", "fresh_")) else 0)

    def test_capped_scratch_row_uses_the_preceding_full_read(self, monkeypatch):
        recall = {"story_doc": "session:story", "open_before": 2}
        monkeypatch.setattr(verify_core, "_RECALL", recall)
        monkeypatch.setattr(verify_acts_doc, "_RECALL", recall)
        full_step, capped_step = verify_acts_doc._SCRATCH_DOCUMENT[2:4]
        assert full_step[1] == {"max_results": 1000}
        assert capped_step[1] == {"max_results": 1}
        full = {
            "active": {"document_handle": "session:scratch"},
            "open_count": 3, "truncated": False,
            "open_documents": [
                {"document_handle": "session:story", "open_index": 0},
                {"document_handle": "session:other", "open_index": 1},
                {"document_handle": "session:scratch", "open_index": 2, "is_active": True},
            ],
        }
        assert full_step[2](full)
        key, extract = full_step[3]
        assert key == "scratch_doc" and extract(full) == "session:scratch"
        assert recall["scratch_doc"] == "session:scratch"
        capped = {
            "active": {"document_handle": "session:scratch"},
            "open_count": 3, "truncated": True,
            "open_documents": [
                {"document_handle": "session:scratch", "open_index": 2, "is_active": True},
            ],
        }
        assert capped_step[2](capped)
        assert full_step[2](capped)
        wrong_handle = dict(capped, open_documents=[dict(capped["open_documents"][0],
                                                      document_handle="session:other")])
        wrong_index = dict(capped, open_documents=[dict(capped["open_documents"][0],
                                                     open_index=1)])
        with pytest.raises(AssertionError, match="active scratch survives"):
            capped_step[2](wrong_handle)
        with pytest.raises(AssertionError, match="active scratch survives"):
            capped_step[2](wrong_index)

    def test_scratch_rows_pin_wrong_tab_close_and_recovery(self):
        rows = verify_acts_doc._SCRATCH_DOCUMENT
        names = [row[0] for row in rows]
        assert names == [
            "doc_get", "doc_new", "doc_get", "doc_get", "doc_activate", "doc_activate",
            "doc_activate", "param_add", "param_get", "doc_activate", "param_get",
            "doc_activate", "doc_close", "param_add",
            "param_get", "doc_get", "param_add", "param_get", "param_delete",
            "param_get", "doc_get", "param_add", "param_get",
        ]
        ctx = {"story_doc": "session:A", "scratch_doc": "session:B",
               "recovered_doc": "session:B"}
        assert rows[3][1] == {"max_results": 1}
        wrong_args = rows[7][1](ctx)
        assert wrong_args["expect_document"] == "session:B"
        assert rows[7][2].fragments == ("active_document_changed", "doc_activate")
        assert rows[8][2].fragments == ("HandleWrong",)
        assert rows[9][1](ctx)["name"] == "session:B"
        assert rows[10][0] == "param_get" and rows[10][1]["name"] == "HandleWrong"
        assert rows[10][2].fragments == ("HandleWrong",)
        assert rows[11][1](ctx)["name"] == "session:A"
        stale_args = rows[13][1]({"scratch_doc": "session:B"})
        assert stale_args["expect_document"] == "session:B"
        assert rows[13][2].fragments == ("unknown_document_handle", "doc_get")
        assert rows[14][2].fragments == ("HandleClosed",)
        recovered_args = rows[16][1](ctx)
        assert recovered_args["expect_document"] == "session:A"
        assert verify_acts_doc._param_added("HandleRecovered", 2)(
            {"added": True, "parameter": {"name": "HandleRecovered",
             "value": 2, "value_units": "mm"}})
        assert rows[18][2].__name__ == "check"
        assert rows[19][2].fragments == ("HandleRecovered",)
        assert rows[20][3][1]({"active": {"name": "Untitled"}}) == "Untitled"
        assert rows[21][1]({"story_name": "Untitled"})["expect_document"] == "uNTITLED"
        with pytest.raises(ValueError, match="no letter whose case can differ"):
            rows[21][1]({"story_name": "2026-10"})
        assert rows[21][2].fragments == ("active_document_changed", "letter case",
                                         "document_handle")
        assert rows[22][2].fragments == ("CaseOnly",)


    def test_reload_probe_requires_fresh_handle_and_restores_home(self):
        calls = []
        recovered = [False]
        doc_reads = [
            {"active": {"name": "Canary", "document_handle": "session:new"},
             "truncated": False, "open_count": 1, "open_documents": [
                 {"name": "Canary", "is_active": True, "document_handle": "session:new"}]},
            {"active": {"name": "Home", "document_handle": "session:home2"},
             "truncated": False, "open_count": 1, "open_documents": [
                 {"name": "Home", "is_active": True, "document_handle": "session:home2"}]},
            {"active": {"name": "Home", "document_handle": "session:home2",
                        "document_id": None},
             "truncated": False, "open_count": 1, "open_documents": [
                 {"name": "Home", "is_active": True, "document_handle": "session:home2"}]},
        ]

        def call(tool, args):
            calls.append((tool, dict(args)))
            if tool == "doc_get":
                return False, doc_reads.pop(0)
            if tool == "param_get" and args["name"].startswith("ReloadNonce"):
                return False, {"parameter": {"name": args["name"], "value": 17}}
            if tool == "param_get" and args["name"] == "ReloadRecovered" and recovered[0]:
                return False, {"parameter": {"name": "ReloadRecovered", "value": 2}}
            if tool == "param_get":
                return True, "Parameter not found: " + args["name"]
            if tool == "param_add" and args["expect_document"] == "session:old":
                return True, {"blocked_by": ["unknown_document_handle"]}
            if tool == "param_add":
                recovered[0] = True
                return False, {"added": True, "parameter": {
                    "name": "ReloadRecovered", "value": 2}}
            if tool == "param_delete":
                recovered[0] = False
                return False, {"deleted": True}
            if tool == "doc_close":
                return False, {"closed": ["Canary"], "closed_count": 1}
            if tool == "doc_activate":
                return False, {"activated": True}
            raise AssertionError(tool)

        ok, note, fresh_handle = verify_acts_doc._reload_document_probe(
            call, "session:old", {"handle": "session:home", "document_id": None, "name": "Home"},
            "ReloadNonceX")
        assert ok, note
        assert fresh_handle == "session:new"
        assert "fresh scratch handle recovered" in note
        stale = [args for tool, args in calls
                  if tool == "param_add" and args["name"] == "ReloadStale"]
        fresh = [args for tool, args in calls
                 if tool == "param_add" and args["name"] == "ReloadRecovered"]
        assert stale == [{"name": "ReloadStale", "expression": "1 mm",
                          "expect_document": "session:old"}]
        assert fresh == [{"name": "ReloadRecovered", "expression": "2 mm",
                          "expect_document": "session:new"}]
        assert all(args == {"max_results": 1000} for tool, args in calls if tool == "doc_get")
        assert not [tool for tool, _args in calls if tool in ("doc_close", "doc_activate")]


class TestOwnedFamilies:
    """Real family-loop boundaries with a changing exact-handle document wire."""

    def test_home_getter_declares_only_its_exact_native_read_under_permission_off(self, monkeypatch):
        wire = _DocumentWire()
        config = json.loads(machine_config.example_text())
        config["tiers"]["native_script"] = True
        declarations = []
        def call(tool, args, *, script_declaration=None):
            effects = machine_config.declared_effects(tool, args, script_declaration)
            machine_config.require_call(config, tool, args, effects)
            if tool == "sys_execute_script":
                declarations.append((args, script_declaration))
            return wire(tool, args)
        monkeypatch.setattr(tool_verify, "call", call)
        snapshot, problem = verify_runner._home_now({"document_handle": "session:home"})
        assert problem is None and snapshot["document_handle"] == "session:home"
        assert len(declarations) == 1
        arguments, declaration = declarations[0]
        assert declaration == machine_config.effect_declaration(arguments["script"], [])
        assert set(arguments) == {"script", "read_only", "expect_document"}
        assert arguments["read_only"] is True and arguments["expect_document"] == "session:home"
        assert [tool for tool, _args in wire.seen] == ["doc_get", "sys_execute_script", "doc_get"]

    @staticmethod
    def _run(monkeypatch, tmp_path, wire, acts, acts_spec=None, hash_values=None,
             resume=False, run_id=None, fixture=None, keep_open=False, continue_families=False,
             health=None, native_available=True, accept_open_work=False):
        def admitted_wire(tool, args, **kwargs):
            if tool == "sys_get_preferences":
                return _preference_reply()
            return wire(tool, args)

        def admitted_health():
            result = dict((health or _attested_health)())
            result["bound"] = _attested_health()["bound"]
            return result

        wrote = []
        hashes = iter(hash_values or ["0" * 64] * 20)
        monkeypatch.setattr(tool_verify, "call", admitted_wire)
        monkeypatch.setattr(verify_runner, "time", _Clock(1.0))
        monkeypatch.setattr(verify_runner, "RESULTS_DIR", str(tmp_path))
        monkeypatch.setattr(verify_runner, "REPO_ROOT", str(tmp_path))
        monkeypatch.setattr(verify_runner, "fixture_steps", fixture or (lambda *a, **k: []))
        monkeypatch.setattr(tool_verify, "health_gate", admitted_health)
        names = {step[0] for _name, pre, narrative, fallback in acts
                 for step in list(narrative) + list(fallback or []) + ([pre] if pre else [])
                 if step[0] != tool_verify._DWELL}
        names.update({"model_write", "doc_new", "doc_close", "doc_open", "view_switch_workspace",
                      "doc_get", "design_get", "doc_activate", "sys_get_preferences", "sys_execute_script"})
        if not native_available:
            names.discard("sys_execute_script")
        monkeypatch.setattr(tool_verify, "registered_tools", _registered(
            sorted(names),
            {"model_write", "doc_new", "doc_close", "sys_execute_script"}))
        monkeypatch.setattr(tool_verify, "source_hash", lambda *a, **k: next(hashes))
        monkeypatch.setattr(tool_verify, "write_verified", lambda *a, **k:
                            wrote.append(True) or "VERIFIED_TOOLS.md")
        monkeypatch.setattr(tool_verify, "reload_smoke", lambda *a, **k:
                            _reloaded_attestation())
        monkeypatch.setattr(tool_verify.reload_smoke, "support_routes", (), raising=False)
        monkeypatch.setattr(tool_verify, "POLL_AFTER", {})
        monkeypatch.setattr(tool_verify, "ACT_NEEDS", {})
        monkeypatch.setattr(tool_verify, "EXCLUDED", {})
        monkeypatch.setattr(tool_verify, "STORY", {})
        monkeypatch.setattr(tool_verify, "ACTS", acts)
        monkeypatch.setattr(tool_verify, "FAMILY_PROGRAM", family_names(acts))
        code = tool_verify.run(write_json=False, acts_spec=acts_spec,
                               resume=resume, run_id=run_id, keep_open=keep_open,
                               continue_families=continue_families, accept_open_work=accept_open_work)
        evidence = sorted((tmp_path / "outputs" / "tool-sweep").glob("families-*.json"))
        return code, wrote, json.loads(evidence[-1].read_text()) if evidence else None


    @pytest.mark.parametrize("mode", ["full", "selected"])
    @pytest.mark.parametrize("field,value", [
        ("feature_count", 4), ("sketch_count", 3), ("body_count", 2), ("is_modified", True)])
    def test_home_content_or_flag_change_stops_before_the_next_family(
            self, monkeypatch, tmp_path, mode, field, value):
        wire = _DocumentWire()
        def call(tool, args, **kwargs):
            result = wire(tool, args)
            if tool == "model_write":
                wire.documents["session:home"][field] = value
            return result
        acts = [("ACT 3 - SURFACES", None, [("model_write", {}, "ok", None)], []),
                ("ACT 4 - MESH", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(monkeypatch, tmp_path, call, acts,
            acts_spec="ACT 3,ACT 4" if mode == "selected" else None)
        assert code == 1 and not wrote and evidence["stopped"] is True
        assert evidence["family_outcomes"]["surfaces"] == "failed"
        assert wire.created == 1 and wire.active == "session:home"
        assert len([t for t, _a in wire.seen if t == "model_write"]) == 1
        checks = [e for e in evidence["family_events"] if e["phase"] == "home-preservation"]
        assert len(checks) == 1 and checks[0]["after"][field] == value
        assert checks[0]["before"][field] != value
        assert not [e for e in evidence["family_events"] if e["phase"] == "after-census"]
        assert set(wire.documents) == {"session:home", "session:intruder"}

    @pytest.mark.parametrize("selected", [False, True])
    def test_two_families_preserve_a_nondefault_home_baseline(self, monkeypatch, tmp_path, selected):
        wire = _DocumentWire()
        wire.documents["session:home"].update(feature_count=19, sketch_count=0,
                                            body_count=0, is_modified=True)
        acts = [("ACT 3 - SURFACES", None, [("model_write", {}, "ok", None)], []),
                ("ACT 4 - MESH", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(monkeypatch, tmp_path, wire, acts,
            acts_spec="ACT 3,ACT 4" if selected else None, accept_open_work=True)
        assert code == 0 and evidence["receipt_written"] is (not selected)
        assert wrote == ([] if selected else [True])
        checks = [e for e in evidence["family_events"] if e["phase"] == "home-preservation"]
        assert len(checks) == 2 and wire.created == 2 and wire.active == "session:home"
        assert all(e["before"] == e["after"] and e["after"]["is_modified"] is True
                   and e["after"]["feature_count"] == 19 and e["after"]["sketch_count"] == 0
                   and e["after"]["body_count"] == 0 for e in checks)
        native = [a for t, a in wire.seen if t == "sys_execute_script"]
        assert len(native) == 4 and all(a["read_only"] is True
                                      and a["expect_document"] == "session:home" for a in native)


    @pytest.mark.parametrize("stage", ["both", "closing"])
    @pytest.mark.parametrize("field", ["name", "document_id", "is_modified", "has_data_file",
                                      "lineage-pair", "row-name", "row-modified"])
    def test_inactive_current_bookends_require_known_facts(self, monkeypatch, stage, field):
        wire = _DocumentWire()
        wire.active = "session:intruder"
        reads = 0
        def call(tool, args, **kwargs):
            nonlocal reads
            bad, payload = wire(tool, args)
            if tool == "doc_get":
                reads += 1
                if stage == "both" or reads == 2:
                    if field in {"name", "document_id"}:
                        payload["active"].pop(field)
                    elif field in {"is_modified", "has_data_file"}:
                        payload["active"][field] = None
                    elif field == "lineage-pair":
                        payload["active"]["document_id"] = None
                    else:
                        row = next(r for r in payload["open_documents"] if r["is_active"])
                        row["name" if field == "row-name" else "is_modified"] = None
            return bad, payload
        monkeypatch.setattr(tool_verify, "call", call)
        snapshot, problem = verify_runner._home_now({"document_handle": "session:home",
            "name": "Home", "document_id": "urn:home"}, allow_inactive=True)
        assert snapshot is None and "current" in problem
        assert wire.active == "session:intruder" and wire.created == 0
        assert len([t for t, _a in wire.seen if t == "sys_execute_script"]) == (stage == "closing")
        assert not [t for t, _a in wire.seen if t in {"doc_new", "doc_activate", "doc_close"}]

    def test_native_off_refuses_before_any_family_write(self, monkeypatch, tmp_path, capsys):
        wire = _DocumentWire()
        acts = [("ACT 3 - SURFACES", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(monkeypatch, tmp_path, wire, acts,
                                        acts_spec="ACT 3", native_available=False)
        assert code == 1 and not wrote and evidence is None
        assert wire.created == 0 and not [t for t, _a in wire.seen
                                          if t in {"model_write", "sys_execute_script", "doc_new"}]
        assert "tiers.native_script=true but sys_execute_script is not registered" in capsys.readouterr().out

    @pytest.mark.parametrize("fault", ["native-refusal", "native-handle", "native-name",
        "native-urn", "native-flag", "closing-handle", "closing-flag", "closing-flag-type",
        "opening-flag", "opening-flag-missing", "opening-row-flag", "opening-lineage", "closing-index",
        "feature_count", "sketch_count", "body_count",
        "negative-count", "boolean-count", "missing-count", "transport"])
    def test_home_snapshot_refuses_unreadable_or_mixed_identity(self, monkeypatch, fault):
        wire = _DocumentWire()
        reads = 0
        def call(tool, args, **kwargs):
            nonlocal reads
            if tool == "sys_execute_script" and fault == "transport":
                raise TimeoutError("observer outcome unknown")
            bad, payload = wire(tool, args)
            if tool == "doc_get":
                reads += 1
                active = payload["active"]
                if reads == 1 and fault == "opening-flag":
                    active["is_modified"] = None
                if reads == 1 and fault == "opening-flag-missing":
                    active.pop("is_modified")
                if reads == 1 and fault == "opening-row-flag":
                    payload["open_documents"][0]["is_modified"] = True
                if reads == 2 and fault == "closing-index":
                    payload["open_documents"][0]["open_index"] = 1
                    payload["open_documents"][1]["open_index"] = 0
                if reads == 1 and fault == "opening-lineage":
                    active["document_id"] = None
                if reads == 2 and fault == "closing-handle":
                    active["document_handle"] = "session:intruder"
                if reads == 2 and fault == "closing-flag":
                    active["is_modified"] = True
                if reads == 2 and fault == "closing-flag-type":
                    active["is_modified"] = 0
            if tool == "sys_execute_script":
                if fault == "native-refusal":
                    return True, "read-only unavailable; no mutable fallback"
                if fault.startswith("native-"):
                    key = {"native-handle": "document_handle", "native-name": "name",
                           "native-urn": "document_id", "native-flag": "is_modified"}[fault]
                    payload[key] = "other" if key != "is_modified" else True
                if fault in {"feature_count", "sketch_count", "body_count"}:
                    payload[fault] = None
                if fault == "negative-count":
                    payload["body_count"] = -1
                if fault == "boolean-count":
                    payload["sketch_count"] = False
                if fault == "missing-count":
                    payload.pop("body_count")
            return bad, payload
        monkeypatch.setattr(tool_verify, "call", call)
        snapshot, problem = verify_runner._home_now({"document_handle": "session:home"})
        assert snapshot is None and problem and any(word in problem for word in ("home", "observer", "current"))
        assert all(t in {"doc_get", "sys_execute_script"} for t, _a in wire.seen)
        assert wire.active == "session:home" and wire.created == 0

    def test_truncated_sketch_adapter_damage_cannot_receive_a_pass_label(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        def call(tool, args, **kwargs):
            result = wire(tool, args)
            if tool == "model_write":
                wire.documents[wire.active].update(feature_count=18, sketch_count=17,
                                                   is_modified=True)
            return result
        acts = [("ACT 1b - SKETCH TOOLS", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(monkeypatch, tmp_path, call, acts, acts_spec="ACT 1b")
        assert code == 1 and not wrote and evidence["family_outcomes"] == {"sketch": "failed"}
        assert wire.created == 0 and wire.active == "session:home"
        writes = [a for t, a in wire.seen if t == "model_write"]
        assert writes == [{"expect_document": "session:home"}]
        check = next(e for e in evidence["family_events"] if e["phase"] == "home-preservation")
        assert check["after"]["sketch_count"] == 17 and check["before"]["sketch_count"] == 2

    def test_resume_keeps_the_original_family_home_baseline(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        acts = [("ACT 3 - SURFACES", None, [("model_write", {}, "ok", None)], []),
                ("ACT 3 - SURFACES SECOND", None, [("model_write", {"interrupt": True}, "ok", None)], [])]
        def interrupted(tool, args):
            if tool == "model_write" and args.get("interrupt"):
                raise SystemExit("injected process interruption")
            return wire(tool, args)
        with pytest.raises(SystemExit, match="injected process interruption"):
            self._run(monkeypatch, tmp_path, interrupted, acts, run_id="home-resume")
        prior = verify_runner.load_run_state("home-resume")
        assert prior["family_home_before"]["feature_count"] == 3
        wire.documents["session:home"]["feature_count"] = 18
        code, wrote, evidence = self._run(monkeypatch, tmp_path, wire, acts,
                                        run_id="home-resume", resume=True)
        assert code == 1 and not wrote and wire.created == 1
        check = next(e for e in evidence["family_events"] if e["phase"] == "home-preservation")
        assert check["before"]["feature_count"] == 3 and check["after"]["feature_count"] == 18
        assert evidence["family_outcomes"] == {"surfaces": "failed"}


    @pytest.mark.parametrize("fault", [None, "inactive", "body-collection", "sketch-collection", "timeline",
                                      "component-slot", "component-cap", "component-boundary", "identity", "non-design"])
    def test_exact_native_observer_reads_own_product_or_refuses(
            self, monkeypatch, capsys, fault):
        import adsk.core
        from conftest import make_design
        from tests.fakes.data_docs import FakeFusionDocument, FakeProducts
        from tests.fakes.scaffold import _NamedCollection
        design = make_design(timeline=_NamedCollection([None] * 7))
        root = design.rootComponent
        root.isValid = True
        root.bRepBodies = _NamedCollection([None])
        root.sketches = _NamedCollection([None] * 5)
        doc = FakeFusionDocument(name="Home", design=design, is_modified=False,
                                 products=FakeProducts(design=design))
        app = adsk.core.Application.get()
        monkeypatch.setattr(app, "activeDocument", doc)
        foreign = make_design(timeline=_NamedCollection([None] * 99))
        foreign.rootComponent.isValid = True
        monkeypatch.setattr(app, "activeProduct", foreign)
        if fault == "inactive":
            current = FakeFusionDocument(name="Family", is_modified=True)
            monkeypatch.setattr(app, "activeDocument", current)
            monkeypatch.setattr(app, "documents", _NamedCollection([doc, current]))
        if fault == "body-collection":
            root.bRepBodies._raises = "injected body count failure"
        if fault == "sketch-collection":
            root.sketches._raises = "injected sketch count failure"
        if fault == "timeline":
            design.timeline._raises = "injected timeline failure"
        if fault == "component-slot":
            design._all_components = [None]
        if fault == "component-cap":
            design._all_components = [root] * 1001
        if fault == "component-boundary":
            design._all_components = [root] * 1000
        if fault == "identity":
            doc.name = "Another document"
        if fault == "non-design":
            doc.products = FakeProducts()
        script = verify_runner._HOME_CONTENT_SCRIPT.replace("__HOME_IDENTITY__", repr(("Home", None))).replace(
            "__HOME_HANDLE__", repr("session:home")).replace("__HOME_TARGET__",
                "app.documents.item(0)" if fault == "inactive" else "app.activeDocument")
        namespace = {}
        exec(compile(script, "home-observer", "exec"), namespace)
        if fault not in (None, "inactive", "component-boundary"):
            with pytest.raises((ValueError, RuntimeError), match="home|injected"):
                namespace["run"](None)
            assert capsys.readouterr().out == ""
        else:
            namespace["run"](None)
            result = json.loads(capsys.readouterr().out)
            assert result == {"name": "Home", "document_id": None, "document_handle": "session:home",
                              "feature_count": 7, "sketch_count": 5000 if fault == "component-boundary" else 5,
                              "body_count": 1000 if fault == "component-boundary" else 1, "is_modified": False}
        assert app.activeDocument == (current if fault == "inactive" else doc) and doc.isModified is False

    def test_canonical_opening_in_subset_writes_only_the_owned_document(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        targets = []
        def call(tool, args, **kwargs):
            result = wire(tool, args)
            if tool == "model_write":
                targets.append((wire.active, args["expect_document"]))
                wire.documents[wire.active].update(feature_count=18, sketch_count=17, is_modified=True)
            return result
        opening = verify_acts_doc._OVERTURE[0]
        acts = [("ACT 0 - OVERTURE", None, [opening], None),
                ("ACT 1b - SKETCH TOOLS", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(monkeypatch, tmp_path, call, acts, acts_spec="ACT 1b")
        assert code == 0 and not wrote and targets == [("session:new1", "session:new1")]
        assert wire.created == 1 and wire.active == "session:home"
        checks = [e for e in evidence["family_events"] if e["phase"] == "home-preservation"]
        assert len(checks) == 1 and checks[0]["before"] == checks[0]["after"]
        assert set(wire.documents) == {"session:home", "session:intruder"}
        assert [a["name"] for t, a in wire.seen if t == "doc_close"] == ["session:new1"]

    @pytest.mark.parametrize("discovery", [False, True])
    def test_family_failure_blocks_dependents_and_discovers_later_failures(
            self, monkeypatch, tmp_path, discovery, capsys):
        wire = _DocumentWire()
        acts = [
            ("ACT 10a - CAM: JOB", None, [
                ("model_write", {"mark": "first"}, lambda p: False, None),
                ("model_write", {"mark": "remaining-step"}, "ok", None)], []),
            ("ACT 10b - CAM: DELIVERABLES", None,
             [("model_write", {"mark": "dependent"}, "ok", None)], []),
            ("ACT 11a - CLOUD: THE DATA MODEL", None,
             [("model_write", {"mark": "second"}, lambda p: False, None)], []),
            ("ACT 12e - SHEET METAL SELECTED BEND", None,
             [("model_write", {"mark": "last"}, lambda p: p["changed"], None)], []),
        ]
        code, wrote, evidence = self._run(
            monkeypatch, tmp_path, wire, acts, continue_families=True,
            run_id=None if discovery else "acceptance",
            acts_spec="ACT 10a,ACT 11a,ACT 12e" if discovery else None)
        assert code == 1 and not wrote and evidence["receipt_written"] is False
        assert [args["mark"] for tool, args in wire.seen if tool == "model_write"] == [
            "first", "second", "last"]
        assert [row[1] for row in evidence["narrative_steps"]] == ["FAIL", "FAIL", "pass"]
        assert evidence["family_outcomes"] == {
            "part_cam": "failed", "cloud": "failed", "sheet_selected": "passed"}
        assert [row["act"] for row in evidence["blocked_acts"]] == ["ACT 10b - CAM: DELIVERABLES"]
        assert evidence["blocked_steps"] == [{"family": "part_cam", "act": "ACT 10a - CAM: JOB",
                                               "tool": "model_write", "step_index": 1}]
        assert wire.active == "session:home" and wire.created == 3
        assert set(wire.documents) == {"session:home", "session:intruder"}
        assert "part_cam=failed" in capsys.readouterr().out
        if not discovery:
            state = verify_runner.load_run_state("acceptance")
            assert set(state["failed_families"]) == {"part_cam", "cloud"}
            assert "failed families" in verify_runner.resume_refusal(
                state, "acceptance", "0" * 64, {}, _ATTESTATION)

    @pytest.mark.parametrize("continuation,discovery", [(False, False), (True, True), (True, False)])
    def test_green_discovery_never_stamps_and_default_remains_fail_fast(
            self, monkeypatch, tmp_path, continuation, discovery):
        wire = _DocumentWire()
        acts = [("ACT 3 - SURFACES", None,
                 [("model_write", {}, "ok" if continuation else lambda p: False, None)], []),
                ("ACT 4 - MESH", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(
            monkeypatch, tmp_path, wire, acts, continue_families=continuation,
            acts_spec="ACT 3,ACT 4" if discovery else None,
            run_id="green-acceptance" if continuation and not discovery else None)
        assert code == (0 if continuation else 1)
        assert wrote == ([True] if continuation and not discovery else [])
        assert wire.created == (2 if continuation else 1)
        assert evidence["receipt_written"] is (continuation and not discovery)

    @pytest.mark.parametrize("fault", [
        "cleanup", "transport", "pin", "source", "identity", "missing-home",
        "modified-home", "unreadable-flags", "duplicate-census", "pending", "shared", "script",
        "nested-transport", "server-timeout", "publication", "unresolved-upload", "cleanup-transport"])
    def test_unsafe_family_failure_stops_globally(self, monkeypatch, tmp_path, fault):
        wire = _DocumentWire(refuse_close=fault == "cleanup", drift_after_write=fault == "pin")
        damaged = False

        def call(tool, args, **kwargs):
            nonlocal damaged
            if tool == "doc_close" and fault == "cleanup-transport":
                wire.seen.append((tool, dict(args)))
                raise TimeoutError("cleanup outcome unknown")
            if tool in {"model_write", "render_edit", "sys_execute_script"} and not args.get("read_only"):
                damaged = True
                if fault == "transport":
                    wire.seen.append((tool, dict(args)))
                    raise TimeoutError("dispatch outcome unknown")
            if tool == "doc_get" and damaged and fault == "missing-home":
                wire.documents.pop("session:home", None)
            failed, payload = wire(tool, args)
            if tool == "doc_get" and damaged:
                if fault == "duplicate-census":
                    payload["open_documents"].append(dict(payload["open_documents"][0]))
                    payload["open_count"] += 1
                for row in payload["open_documents"]:
                    if row["document_handle"] == "session:home":
                        if fault == "modified-home":
                            row["is_modified"] = True
                        if fault == "unreadable-flags":
                            row["is_visible"] = None
            if tool == "model_write" and fault == "pending":
                payload["pending"] = True
            if tool == "model_write" and fault == "server-timeout":
                return True, "Handler is still running after 120s and could NOT be cancelled"
            if tool == "doc_save":
                return False, {"cloud_processing_complete": False}
            return failed, payload

        health_calls = 0

        def health():
            nonlocal health_calls
            health_calls += 1
            identity = dict(_ATTESTATION)
            if fault == "identity" and health_calls > 2:
                identity["load_id"] = "other-load"
            return _attested_health(identity)

        def predicate(payload):
            if fault == "nested-transport":
                raise TimeoutError("nested reader outcome unknown")
            return False

        first = ("render_edit" if fault == "shared" else "sys_execute_script" if fault == "script"
                 else "doc_save" if fault == "publication" else "data_upload_file"
                 if fault == "unresolved-upload" else "model_write")
        acts = [("ACT 3 - SURFACES", None, [(first, {}, predicate, None)], []),
                ("ACT 4 - MESH", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(
            monkeypatch, tmp_path, call, acts, continue_families=True, health=health,
            hash_values=["0" * 64, "0" * 64, "1" * 64] if fault == "source" else None)
        assert code == 1 and not wrote and wire.created == 1
        assert evidence["stopped"] is True and evidence["receipt_written"] is False
        assert evidence["family_outcomes"]["mesh"] == "not-run"
        assert any(row["phase"] == "continuation" and row["allowed"] is False
                   for row in evidence["family_events"])
        if fault in {"transport", "nested-transport", "server-timeout", "cleanup-transport"}:
            assert wire.seen[-1][0] == ("doc_close" if fault == "cleanup-transport" else first)
            assert evidence["transport_uncertain"] is True
            assert evidence["owned_scratch"] == ["session:new1"]
            assert "session:new1" in wire.documents

    @pytest.mark.parametrize("missing_gate,pending,publication,save_tool", [
        (False, False, True, "doc_save"), (True, False, True, "doc_save"),
        (False, True, True, "doc_save"), (False, True, False, "doc_save"),
        (False, True, None, "doc_save"), (False, True, True, "doc_save_as"),
        (False, True, False, "doc_save_as")])
    def test_cloud_name_failure_requires_prior_specific_restoration_gates(
            self, monkeypatch, tmp_path, missing_gate, pending, publication, save_tool):
        import verify_acts_cloud as cloud
        wire = _DocumentWire()
        restored = lambda p: p.get("restored") is True
        generated = lambda p: p.get("completed") is True
        deleted = lambda p: p.get("loads_after_delete") is False
        scripts = []
        for prefix in ("_capped_name_move", "_duplicate_project", "_duplicate_hub", "_hub_edit_preflight"):
            provider = lambda ctx: {"script": "injected restore witness"}
            monkeypatch.setattr(cloud, prefix + "_probe", provider)
            monkeypatch.setattr(cloud, prefix + "_result", restored)
            scripts.append(("sys_execute_script", provider, restored, None))
        terminal = ("cam_get_status", {"target": "owned setup"}, generated, None)
        cleanup = ("cam_delete_template", {"name": "owned template"}, deleted, None)
        monkeypatch.setattr(cloud, "_CLOUD_DATA", scripts[:3])
        monkeypatch.setattr(cloud, "_CLOUD_DOC", scripts[3:])
        monkeypatch.setattr(cloud, "_CLOUD_DRAWING", [])
        monkeypatch.setattr(cloud, "_CLOUD_CAM_PERSISTENCE", [terminal, cleanup])

        def call(tool, args, **kwargs):
            if tool == "sys_execute_script" and not args.get("read_only"):
                return False, {"restored": True}
            if tool == "cam_get_status":
                return False, {"completed": True}
            if tool == "cam_delete_template":
                return False, {"loads_after_delete": False}
            if tool == save_tool:
                payload = {"pending": pending, "version_confirmed": False, "cloud_tip_advanced": False}
                if publication is not None:
                    payload["cloud_processing_complete"] = publication
                return False, payload
            if tool == "data_get":
                return False, {"file": {"name": "old backing name"}}
            return wire(tool, args)

        acts = [
            ("ACT 11a - CLOUD: THE DATA MODEL", None, scripts[:3], []),
            ("ACT 11b - CLOUD: THE SAVED DOCUMENT", None, scripts[3:], []),
            ("ACT 11c - CLOUD: THE DRAWING", None, [], []),
            ("ACT 11d - CLOUD: CAM TEMPLATE PERSISTENCE", None,
             [("cam_generate", {}, "ok", None), terminal] + ([] if missing_gate else [cleanup]), []),
            ("ACT 11e - CLOUD: CONFIGURATION COLUMN REFUSALS", None, [
                (save_tool, {}, "ok", None),
                ("data_get", {}, lambda p: p["file"]["name"] == "Configuration 1", None)], []),
            ("ACT 11f - CLOUD: DERIVE EDITS", None,
             [("model_write", {"dependent": True}, "ok", None)], []),
            ("ACT 12e - SHEET METAL SELECTED BEND", None,
             [("model_write", {"independent": True}, "ok", None)], []),
        ]
        code, wrote, evidence = self._run(
            monkeypatch, tmp_path, call, acts, continue_families=True)
        assert code == 1 and not wrote
        blocked = missing_gate or publication is not True
        assert wire.created == (1 if blocked else 2)
        assert [row for row in evidence["narrative_steps"] if row[1] == "FAIL"] == [
            ["data_get", "FAIL", "{'file': {'name': 'old backing name'}}"]]
        assert evidence["family_outcomes"]["sheet_selected"] == ("not-run" if blocked else "passed")
        assert not [args for tool, args in wire.seen if tool == "model_write" and args.get("dependent")]

    def test_fixture_logical_failure_keeps_its_evidence_and_runs_next_family(
            self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        acts = [("ACT 3 - SURFACES", None, [("model_write", {"dependent": True}, "ok", None)], []),
                ("ACT 4 - MESH", None, [("model_write", {"independent": True}, "ok", None)], [])]
        fixture = lambda family, before_act=None, **kw: (
            [("model_write", {}, lambda p: False, None)]
            if family == "surfaces" and before_act is None else [])
        code, wrote, evidence = self._run(
            monkeypatch, tmp_path, wire, acts, fixture=fixture, continue_families=True)
        assert code == 1 and not wrote and wire.created == 2
        assert evidence["family_outcomes"] == {"surfaces": "failed", "mesh": "passed"}
        assert [row[1] for row in evidence["narrative_steps"]] == ["pass"]
        assert any(event["phase"] == "setup" and event["steps"][0][1] == "FAIL"
                   for event in evidence["family_events"])
        assert not [args for tool, args in wire.seen if tool == "model_write" and args.get("dependent")]

    @pytest.mark.parametrize("tool,arguments,refused", [
        ("view_set", {"action": "orient", "projection": "perspective"}, False),
        ("view_set", {"action": "orient", "projection": "perspective"}, True),
        ("sys_set_preferences", {"member": "compatibility.recoverSaveScanFrequency", "value": 17}, True)])
    def test_attempted_shared_write_remains_uncertified_even_when_refused(
            self, monkeypatch, tmp_path, tool, arguments, refused):
        wire = _DocumentWire()

        def call(name, args):
            if name == tool:
                return (True, "injected partial write refusal") if refused else (False, {"changed": True})
            return wire(name, args)

        acts = [("ACT 3 - SURFACES", None, [
            (tool, arguments, "refused" if refused else "ok", None),
            ("model_write", {}, lambda p: False, None)], []),
            ("ACT 4 - MESH", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(
            monkeypatch, tmp_path, call, acts, continue_families=True)
        assert code == 1 and not wrote and wire.created == 1
        assert [row[1] for row in evidence["narrative_steps"]] == [
            "expected-refusal" if refused else "pass", "FAIL"]
        gate = next(event for event in evidence["family_events"] if event["phase"] == "continuation")
        assert gate["allowed"] is False and tool in gate["reason"]

    def test_all_selected_families_reset_recall_and_never_stamp(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        acts = [
            ("ACT 3 - SURFACES", None, [
                ("model_write", {}, lambda p: p["changed"],
                 ("foreign", tool_verify._recall("foreign", lambda p: 1)))], []),
            ("ACT 4 - MESH", None, [
                ("model_write", {}, lambda p: p["changed"]
                 and "foreign" not in tool_verify._RECALL, None)], []),
        ]
        tool_verify._RECALL["foreign"] = "stale before run"
        code, wrote, evidence = self._run(
            monkeypatch, tmp_path, wire, acts, acts_spec="ACT 3,ACT 4")
        assert code == 0 and not wrote
        assert evidence["receipt_written"] is False
        assert [row["phase"] for row in evidence["family_events"]].count("before-census") == 2
        assert wire.active == "session:home"
        assert set(wire.documents) == {"session:home", "session:intruder"}
        assert wire.created == 2

    def test_selected_sheet_family_reads_owned_design_beside_drawing_home(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        wire.documents["session:home"]["name"] = "Owner Drawing"
        baseline = dict(wire.documents)
        targets = []

        def call(tool, args, **kwargs):
            if tool == "design_get" and args.get("include") == ["tree", "timeline"]:
                targets.append(wire.active)
                if wire.active == "session:home":
                    return True, "No active design"
            return wire(tool, args)

        acts = [("ACT 12e - SHEET METAL SELECTED BEND", None,
                 [("design_get", {"include": ["tree", "timeline"]},
                   lambda p: p.get("feature_count") == 3, None)], [])]
        code, wrote, evidence = self._run(monkeypatch, tmp_path, call, acts, acts_spec="ACT 12e")
        assert code == 0 and not wrote and evidence["receipt_written"] is False
        assert targets == ["session:new1"]
        assert wire.active == "session:home" and wire.documents == baseline
        assert [args["name"] for tool, args in wire.seen if tool == "doc_close"] == ["session:new1"]

    def test_full_run_uses_same_family_loop_and_stamps(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        acts = [("ACT 3 - SURFACES", None, [("model_write", {}, "ok", None)], []),
                ("ACT 4 - MESH", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(monkeypatch, tmp_path, wire, acts)
        assert code == 0 and wrote == [True]
        assert evidence["receipt_written"] is True
        timed = [row for row in evidence["family_events"] if "elapsed_s" in row]
        assert timed and all(isinstance(row["elapsed_s"], (int, float))
                             and row["elapsed_s"] >= 0 for row in timed)
        assert {row["phase"] for row in timed} >= {
            "setup", "narrative ACT 3 - SURFACES", "cleanup-total"}
        assert wire.created == 2 and wire.active == "session:home"
        assert set(wire.documents) == {"session:home", "session:intruder"}

    @pytest.mark.parametrize("mode", ["full", "selected", "continue"])
    def test_after_census_omits_a_dependency_that_unloaded_with_the_owned_tab(
            self, monkeypatch, tmp_path, mode):
        wire = _DocumentWire()

        def call(tool, args, **kwargs):
            result = wire(tool, args)
            if tool == "model_write":
                wire.documents["session:dependency"] = {
                    "name": "Dependency", "document_id": "urn:dependency"}
            elif tool == "doc_close":
                wire.documents.pop("session:dependency", None)
                if wire.active == "session:dependency":
                    wire.active = "session:home"
            return result

        acts = [("ACT 3 - SURFACES", None, [("model_write", {}, "ok", None)], [])]
        code, _wrote, evidence = self._run(
            monkeypatch, tmp_path, call, acts,
            acts_spec="ACT 3" if mode == "selected" else None,
            continue_families=mode == "continue")
        assert code == 0
        after = [row for row in evidence["family_events"] if row["phase"] == "after-census"]
        assert len(after) == 1 and after[0]["documents"] == sorted(wire.documents)
        assert after[0]["documents"] == ["session:home", "session:intruder"]
        assert after[0]["active"] == wire.active == "session:home"

    def test_source_drift_cleans_owned_document_and_saves_failure(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        acts = [("ACT 10a - CAM: JOB", None, [("model_write", {}, "ok", None)], []),
                ("ACT 10b - CAM: DELIVERABLES", None,
                 [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(monkeypatch, tmp_path, wire, acts,
                                           hash_values=["0" * 64, "1" * 64])
        assert code == 1 and not wrote and evidence["stopped"] is True
        assert wire.active == "session:home"
        assert set(wire.documents) == {"session:home", "session:intruder"}
        assert any(row["phase"] == "cleanup" for row in evidence["family_events"])

    def test_old_single_document_checkpoint_is_refused_before_wire(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        acts = [("ACT 3 - SURFACES", None, [("model_write", {}, "ok", None)], [])]
        monkeypatch.setattr(verify_runner, "RESULTS_DIR", str(tmp_path))
        verify_runner.save_run_state("old", {"run": "old", "acts_done": []})
        code, wrote, evidence = self._run(monkeypatch, tmp_path, wire, acts,
                                           run_id="old", resume=True)
        assert code == 1 and not wrote and evidence is None
        assert wire.seen == []

    def test_fixture_failure_is_separate_and_restores_home(self, monkeypatch, tmp_path):
        wire = _DocumentWire()
        acts = [("ACT 3 - SURFACES", None, [("model_write", {}, "ok", None)], [])]
        fixture = lambda family, before_act=None, entitled=True: (
            [("model_write", {}, lambda p: p.get("changed") is False, None)]
            if before_act is None else [])
        code, wrote, evidence = self._run(monkeypatch, tmp_path, wire, acts,
                                           fixture=fixture, acts_spec="ACT 3")
        assert code == 1 and not wrote and evidence["stopped"] is True
        assert evidence["narrative_steps"] == []
        assert any(row["phase"] == "setup" and row["steps"][0][1] == "FAIL"
                   for row in evidence["family_events"])
        assert wire.active == "session:home"
        assert set(wire.documents) == {"session:home", "session:intruder"}

    @pytest.mark.parametrize("fault", [None, "unknown", "changed"])
    def test_keep_open_checks_home_without_cleanup_or_activation(self, monkeypatch, tmp_path, fault):
        wire = _DocumentWire()
        def call(tool, args, **kwargs):
            result = wire(tool, args)
            if tool == "model_write" and fault:
                wire.documents["session:home"]["body_count"] = None if fault == "unknown" else 2
            return result
        acts = [("ACT 3 - SURFACES", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, evidence = self._run(monkeypatch, tmp_path, call, acts,
                                           acts_spec="ACT 3", keep_open=True)
        assert code == (1 if fault else 0) and not wrote and evidence["receipt_written"] is False
        assert wire.active == "session:new1" and wire.created == 1
        assert set(wire.documents) == {"session:home", "session:intruder", "session:new1"}
        assert not [t for t, _a in wire.seen if t in {"doc_activate", "doc_close"}]
        check = next(e for e in evidence["family_events"] if e["phase"] == "home-preservation-kept")
        assert check["cleanup"] is False
        if not fault:
            assert check["before"] == check["after"]
        native = [a for t, a in wire.seen if t == "sys_execute_script"]
        assert native[-1]["expect_document"] == "session:new1"
        assert "app.documents.item(0)" in native[-1]["script"]

    def test_unrelated_new_tab_survives_family_cleanup(self, monkeypatch, tmp_path):
        wire = _DocumentWire(background_after_write=True)
        acts = [("ACT 3 - SURFACES", None, [("model_write", {}, "ok", None)], [])]
        code, wrote, _evidence = self._run(monkeypatch, tmp_path, wire, acts,
                                            acts_spec="ACT 3")
        assert code == 0 and not wrote and wire.active == "session:home"
        assert set(wire.documents) == {"session:home", "session:intruder", "session:user"}

    @pytest.mark.parametrize("existing", [False, True])
    def test_doc_open_ownership_distinguishes_new_from_existing(
            self, monkeypatch, tmp_path, existing):
        wire = _DocumentWire(doc_open_existing=existing)
        acts = [("ACT 3 - SURFACES", None, [], [])]
        fixture = lambda family, before_act=None, entitled=True: (
            [("doc_open", {"file_id": "urn:sweep"}, "ok", None)]
            if before_act is None else [])
        code, wrote, evidence = self._run(monkeypatch, tmp_path, wire, acts,
                                           acts_spec="ACT 3", fixture=fixture)
        assert code == 0 and not wrote and evidence["receipt_written"] is False
        assert wire.active == "session:home"
        assert set(wire.documents) == {"session:home", "session:intruder"}
        closed = [args.get("name") for tool, args in wire.seen if tool == "doc_close"]
        assert ("session:open2" in closed) is (not existing)
        assert "session:intruder" not in closed

    def test_narrative_cannot_close_a_preexisting_opened_tab(self, monkeypatch, tmp_path):
        wire = _DocumentWire(doc_open_existing=True)
        acts = [("ACT 3 - SURFACES", None, [
            ("doc_close", {"name": "session:intruder", "save_changes": False}, "ok", None)
        ], [])]
        fixture = lambda family, before_act=None, entitled=True: (
            [("doc_open", {"file_id": "urn:sweep"}, "ok", None)]
            if before_act is None else [])
        code, wrote, evidence = self._run(monkeypatch, tmp_path, wire, acts,
                                           acts_spec="ACT 3", fixture=fixture)
        assert code == 1 and not wrote
        assert evidence["narrative_steps"][0][1] == "blocked"
        assert "did not open" in evidence["narrative_steps"][0][2]
        assert wire.active == "session:home"
        assert set(wire.documents) == {"session:home", "session:intruder"}
        assert not [args for tool, args in wire.seen
                    if tool == "doc_close" and args.get("name") == "session:intruder"]


def test_resize_fixture_supplies_a_separate_second_solid_before_interference():
    """The first Resize interference read needs two bodies before its own scratch opens."""
    rows = fixture_steps("resize")
    extra = rows[-5:]
    assert [row[0] for row in extra] == [
        "model_create_component", "sketch_create", "sketch_add_geometry",
        "model_extrude", "design_activate_component"]
    assert extra[0][1]["name"] == "DatumBench"
    rectangle = extra[2][1]["geometry"][0]
    assert rectangle["x1"] > 160 and rectangle["x2"] > rectangle["x1"]
    assert extra[3][1]["sketch_name"] == "DBPad"
    assert extra[-1][1]["occurrence"] == "root"


def test_showcase_fixture_captures_rotated_handle_before_other_modelling():
    """The HandleS focus uses the captured ScrewTurn pose before cameos are built."""
    rows = fixture_steps("showcase")
    jaw = next(i for i, row in enumerate(rows)
               if row[0] == "joint_create" and row[1].get("name") == "JawSlide")
    ball = next(i for i, row in enumerate(rows)
                if row[0] == "model_create_component" and row[1].get("name") == "BallSphere")
    pose = rows[jaw + 1:ball]
    assert [row[0] for row in pose] == [
        "joint_create", "joint_edit", "joint_create_as_built", "joint_motion_link",
        "joint_drive", "joint_drive", "assembly_get", "model_measure_between",
        "model_measure_between", "model_inspect", "assembly_capture_position"]
    assert pose[0][1]["name"] == "ScrewTurn"
    assert [row[1]["distance"] for row in pose if row[0] == "joint_drive"] == [-4, 6]
    assert pose[-1][1]["action"] == "capture"


def test_showcase_drift_subjects_build_their_original_final_effects():
    """The four measured cameos need joints, a mate and patterns before drift reads."""
    rows = showcase_shapes()
    components = [row[1]["name"] for row in rows if row[0] == "model_create_component"]
    assert components == ["BallSphere", "BallPost", "AxisPost", "RigidPost",
                          "TorusRing", "TorusPost", "MateSeat", "MateArm", "FeatureCameo"]
    assert sum(row[0] == "joint_at_geometry" for row in rows) == 5
    assert any(row[0] == "assembly_constrain" and len(row[1]["relationships"]) == 2
               for row in rows)
    assert any(row[0] == "design_recompute" for row in rows)
    assert [row[0] for row in rows[-6:]] == [
        "model_mirror", "model_pattern_rectangular", "model_construction",
        "model_construction", "model_construction", "model_pattern_circular"]
    assert rows[-2][1]["name"] == "CameoOrbit"


def test_cam_fixtures_initialize_product_then_build_models_in_design():
    """A fresh CAM document needs Manufacture once before document-tool access."""
    for family, first_cam in (("swarf_cam", "ACT 10b2"),
                              ("hub_cam", "ACT 10c4")):
        setup = fixture_steps(family)
        assert [(row[0], row[1].get("workspace")) for row in setup] == [
            ("view_switch_workspace", "manufacture"),
            ("cam_edit_tools", None),
            ("view_switch_workspace", "design")]
        assert fixture_steps(family, before_act=first_cam) == [setup[0]]
    for family, later in (("hub_cam", "ACT 10c15"),
                          ("part_cam", "ACT 10e")):
        rows = fixture_steps(family, before_act=later)
        first_cam = next(i for i, row in enumerate(rows) if row[0].startswith("cam_"))
        assert rows[0][1]["workspace"] == "design"
        switches = [row[1]["workspace"] for row in rows[:first_cam]
                    if row[0] == "view_switch_workspace"]
        assert switches[-1] == "manufacture"


def test_late_part_cam_fixture_queries_its_placed_frustum_and_gates_extension():
    """The local top-face query follows its frustum and basic setup survives without extension."""
    base = fixture_steps("part_cam", before_act="ACT 10e", entitled=False)
    raw = fixture_steps("part_cam", before_act="ACT 10e", entitled=False, raw=True)
    rectangle = next(geometry for tool, args, _pred, _save in base
                     if tool == "sketch_add_geometry" and args["sketch_name"] == "FrustumSketch"
                     for geometry in args["geometry"] if geometry["kind"] == "rectangle")
    raw_rectangle = next(geometry for tool, args, _pred, _save in raw
                         if tool == "sketch_add_geometry" and args["sketch_name"] == "FrustumSketch"
                         for geometry in args["geometry"] if geometry["kind"] == "rectangle")
    top_face = next(args for tool, args, _pred, save in base
                    if tool == "find_geometry" and save and save[0] == "scope_top_face")
    raw_top_face = next(args for tool, args, _pred, save in raw
                        if tool == "find_geometry" and save and save[0] == "scope_top_face")
    dx, dy = rectangle["x1"] - raw_rectangle["x1"], rectangle["y1"] - raw_rectangle["y1"]
    assert rectangle["x2"] - raw_rectangle["x2"] == dx
    assert rectangle["y2"] - raw_rectangle["y2"] == dy
    assert top_face["nearest_to"] == [raw_top_face["nearest_to"][0] + dx,
                                     raw_top_face["nearest_to"][1] + dy,
                                     raw_top_face["nearest_to"][2]]
    assert top_face["nearest_to"][:2] == [
        (rectangle["x1"] + rectangle["x2"]) / 2,
        (rectangle["y1"] + rectangle["y2"]) / 2]
    assert [args["setup"] for tool, args, _pred, _save in base
            if tool == "cam_edit_setup"] == ["SwarfSetup2"]
    full = fixture_steps("part_cam", before_act="ACT 10e", entitled=True)
    assert [args["setup"] for tool, args, _pred, _save in full
            if tool == "cam_edit_setup"] == ["SwarfSetup2", "SwarfSetup", "MultiAxisSetup"]


def test_bracket_and_datum_producers_keep_authored_geometry_and_root_context():
    sketch = verify_acts_sketch
    assert BRACKET_PARAMETERS_PROFILES == (
        sketch.BRACKET_PARAMETERS + sketch._BRACKET_COMPONENT + sketch.BRACKET_PROFILES
        + [sketch._BRACKET_PROFILE_ROOT])
    assert any(row[0] == "param_get" for row in BRACKET_PARAMETERS_PROFILES)
    assert any(row[0] == "model_create_component" and row[1].get("name") == "Bracket"
               for row in BRACKET_PARAMETERS_PROFILES)
    assert BRACKET_PARAMETERS_PROFILES[-1][0] == "design_activate_component"
    assert BRACKET_PARAMETERS_PROFILES[-1][1]["occurrence"] == "root"
    assert not any(row[0] == "sketch_create" and row[1].get("name") in ("Skeleton", "NamePlate")
                   for row in BRACKET_PARAMETERS_PROFILES)
    assert any(row[0] == "sketch_create" and row[1].get("name") == "Skeleton"
               for row in sketch._SKELETON)
    assert any(row[0] == "sketch_create" and row[1].get("name") == "NamePlate"
               for row in sketch._SKELETON)

    solids = verify_acts_model_solids
    assert FINISHED_BRACKET == solids._SOLIDS[:solids._STOCK_CENTER_END + 1]
    assert FINISHED_BRACKET[-1][1]["name"] == "StockCenter"
    assert DATUM_BENCH_DETAILS[-1][0] == "find_geometry"
    assert DATUM_BENCH_DETAILS[-1][3][0] == "db_bore"
    assert DATUM_BENCH_RESIZE[-1][0] == "model_extrude"
    assert DATUM_BENCH_RESIZE[-1][1]["sketch_name"] == "DBPad"


def test_vise_and_cam_producers_stop_at_their_consumed_boundaries():
    motion = verify_acts_motion
    assert STOCK_VISE == list(motion._STOCK_VISE)
    assert STOCK_VISE[-1] == ("design_activate_component", {"occurrence": "root"}, "ok", None)
    appearances = [row[1].get("target") for row in STOCK_VISE if row[0] == "appearance_set"]
    assert "STOCK" in appearances
    assert not {"ViseBase", "JawFixed", "JawMoving", "LeadScrew"} & set(appearances)
    capture = next(i for i, row in enumerate(motion._VISE)
                   if row[0] == "assembly_capture_position"
                   and row[1].get("action") == "capture")
    assert _VISE_SHOWCASE_POSE == motion._VISE[len(STOCK_VISE):capture + 1]
    assert _VISE_SHOWCASE_POSE[-1][1]["action"] == "capture"
    assert any(row[0] == "appearance_set" for row in _VISE_SHOWCASE_POSE)

    cam = verify_acts_cam
    assert _SWARF_FRUSTUM == cam._SWARF_RIG[:len(_SWARF_FRUSTUM)]
    assert _SWARF_FRUSTUM[-1][0] == "model_inspect"
    assert any(row[0] == "model_create_component" and row[1].get("name") == cam._L_COMP
               for row in cam._SWARF_RIG)
    late = fixture_steps("part_cam", before_act="ACT 10e", entitled=False)
    assert not any(row[0] == "model_create_component" and row[1].get("name") == cam._L_COMP
                   for row in late)
    early = fixture_steps("part_cam")
    components = {row[1].get("name") for row in early + late
                  if row[0] == "model_create_component"}
    assert {"Bracket", cam._SW_COMP} <= components
    ambiguous = next(row for row in cam._CAM_SCOPE
                     if row[0] == "cam_select_geometry" and callable(row[1])
                     and isinstance(row[2], verify_core._Refusal))
    assert ambiguous[1]({"setup2_op": "fixture-op"})["bodies"] == ["Body1"]
    assert "component" not in ambiguous[1]({"setup2_op": "fixture-op"})


def test_grounding_witness_requires_the_placed_body_not_only_a_reported_origin():
    check = verify_acts_motion._ground_frame_poses([70, 220, 90], True)
    payload = {'units': 'mm', 'all_occurrences_truncated': False, 'occurrence_count': 1,
               'all_occurrence_count': 2, 'all_occurrences': [
                   {'full_path': 'GroundHost:1', 'origin': [100, 200, 50]},
                   {'full_path': 'GroundHost:1+GroundLeaf:1', 'origin': [70, 220, 90],
                    'ground_to_parent': True, 'body_count': 1,
                    'bbox_center': [58.84, 219.33, 105], 'bbox_size': [22.321, 18.66, 30]}]}
    assert check(payload)
    payload['all_occurrences'][1]['bbox_center'][0] += 70
    with pytest.raises(AssertionError, match='own-body world bounds'):
        check(payload)
    payload['all_occurrences'][1]['bbox_center'][0] -= 70
    payload['all_occurrences'][1]['origin'] = [20, 30, 40]
    with pytest.raises(AssertionError, match='own-body world bounds'):
        check(payload)


def test_instance_geometry_witness_reads_nested_mass_and_keeps_world_bounds():
    check = verify_acts_motion._instance_frame_geometry(
        [[47.679492, 210, 90], [70, 228.660254, 120]])
    payload = {'units': 'mm', 'kind': 'occurrence',
               'min_point': {'x': 47.679492, 'y': 210.0, 'z': 90.0},
               'max_point': {'x': 70.0, 'y': 228.660254, 'z': 120.0},
               'mass': {'units': 'mm', 'volume': 6000.0}}
    assert check(payload)
    payload['mass']['volume'] = 5999.0
    with pytest.raises(AssertionError, match='own-body world box and volume'):
        check(payload)
    payload['mass']['volume'] = 6000.0
    payload['mass']['units'] = 'cm'
    with pytest.raises(AssertionError, match='own-body world box and volume'):
        check(payload)
    payload['mass']['units'] = 'mm'
    payload['min_point']['x'] += 70
    with pytest.raises(AssertionError, match='own-body world box and volume'):
        check(payload)


class TestChamferGeometryWitness:
    def test_miter_mass_read_refuses_the_ordinary_geometry_and_no_removal(self, monkeypatch):
        import verify_acts_model_details as details
        def body(volume):
            return dict(kind='body', units='mm', lump_count=1,
                        min_point=dict(x=0, y=0, z=0), max_point=dict(x=40, y=30, z=20),
                        mass=dict(volume=volume, area=5145.5972401, accuracy_used='very_high',
                                  center_of_mass=[20, 15, 10]))
        monkeypatch.setitem(details._RECALL, 'cg_test_before', details._chamfer_body_state(body(24000)))
        check = details._chamfer_body_read(23955.75, 5145.5972401, 'cg_test_before')
        assert check(body(23955.75))
        for volume in (23955.666667, 24000):
            with pytest.raises(AssertionError, match='independent chamfer body geometry'):
                check(body(volume))
        monkeypatch.setitem(details._RECALL, 'cg_test_before', None)
        with pytest.raises(AssertionError, match='independent chamfer body geometry'):
            check(body(23955.75))

    def test_census_refuses_wrong_faces_at_the_same_total_and_incomplete_listing(self):
        import verify_acts_model_details as details
        rows = [dict(kind='planar_face', handle=str(i)) for i in range(9)]
        rows += [dict(kind='line_edge', handle=str(i)) for i in range(9, 30)]
        payload = dict(units='mm', kind_filter='faces+edges', match_count=30, returned=30,
                       matches=rows)
        check = details._chamfer_face_census(9, 21)
        assert check(payload)
        rows[9]['kind'] = 'planar_face'
        with pytest.raises(AssertionError, match='independent chamfer face census'):
            check(payload)
        rows[9]['kind'] = 'line_edge'
        payload['returned'] = 29
        with pytest.raises(AssertionError, match='independent chamfer face census'):
            check(payload)

    def test_story_pins_three_seeds_and_one_rim_seed_with_independent_reads(self):
        import verify_acts_model_details as details
        rows = details._chamfer_geometry_rows()
        ctx = {save[0]: 'offline:' + save[0] for _, _, _, save in rows if save}
        cuts = [(i, args(ctx)) for i, (tool, args, _, _) in enumerate(rows)
                if tool == 'model_chamfer']
        assert len(rows) == 58 and [i for i, _ in cuts] == [11, 23, 38, 51]
        assert [len(args['edges']) for _, args in cuts] == [3, 3, 1, 1]
        assert [args['tangent_chain'] for _, args in cuts] == [False, False, False, True]
        assert [args.get('corner_type') for _, args in cuts[:2]] == ['chamfer', 'miter']
        assert cuts[-1][1]['distance'] == 2 and cuts[-1][1]['angle_deg'] == 30
        for i, _ in cuts:
            assert [row[0] for row in rows[i + 1:i + 3]] == ['model_inspect', 'find_geometry']
        seed = rows[8][2]
        assert seed(dict(units='mm', matches=[dict(kind='line_edge', handle='seed',
                                                 position=[20, 0, 20])]))
        with pytest.raises(AssertionError, match='measured midpoint'):
            seed(dict(units='mm', matches=[dict(kind='line_edge', handle='seed', position=[20, 0, 0])]))
        assert [row[0] for row in rows[-2:]] == ['doc_activate', 'doc_close']
        assert rows[-1][1](ctx)['save_changes'] is False


def _baseline_real_consumer_spies(monkeypatch, extra_tools):
    """Inject only explicit inert support and retain real admission/dispatch batch objects."""
    program = sys.modules["verify_program"]
    original_registered = _registered
    original_tools = preflight.required_tools
    original_steps = verify_runner.run_steps
    original_run = tool_verify.run
    registration, dispatch, records = [], [], []

    def registered(names, writes=()):
        return original_registered(sorted(set(names) | set(extra_tools)), writes)

    def required(config, batch, conditions, support_routes=()):
        registration.append((batch, tuple(support_routes)))
        return original_tools(config, batch, conditions, support_routes=support_routes)

    def steps(batch, *args, **kwargs):
        assert isinstance(batch, tuple), "consumer recomputed the admitted batch"
        assert any(batch is candidate for candidate, _routes in registration), (
            "dispatch did not consume the identical checked batch")
        dispatch.append(batch)
        return original_steps(batch, *args, **kwargs)

    def run(*args, **kwargs):
        # These existing helpers replace lifecycle with inert functions, explicitly no wire support.
        monkeypatch.setattr(tool_verify.reload_smoke, "support_routes", (), raising=False)
        monkeypatch.setattr(tool_verify.family_switch_smoke, "support_routes", (), raising=False)
        return original_run(*args, **dict(kwargs, batch_records=records))

    monkeypatch.setitem(globals(), "_registered", registered)
    monkeypatch.setattr(preflight, "required_tools", required)
    monkeypatch.setattr(verify_runner, "run_steps", steps)
    monkeypatch.setattr(tool_verify, "run", run)
    return program, registration, dispatch, records


@pytest.mark.parametrize("selected,keep_open", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("observed", [False, None])
@pytest.mark.parametrize("fallback", [False, True])
def test_baseline_real_family_consumer_caches_false_branch_and_resolves_once(
        monkeypatch, tmp_path, selected, keep_open, observed, fallback):
    wire = _DocumentWire()
    act = "ACT 10e - CAM: THE PART"
    # These are reached by the actual pin/home, false-entitlement observer/poll and cleanup.
    extra = {"pre_get", "design_get", "workspace_orient", "cam_get_status"}
    if not keep_open:
        extra.add("doc_activate")
    program, registration, dispatch, records = _baseline_real_consumer_spies(monkeypatch, extra)
    made, evaluated = {}, []

    def fixture(family, before_act=None, entitled=True):
        key = (family, before_act, entitled if before_act else None)
        made[key] = made.get(key, 0) + 1
        assert made[key] == 1, "fixture rebuilt between admission and real run"
        def args(context):
            evaluated.append(key)
            return {"stage": repr(key), "seed": context.get("seed", 7)}
        return [("model_write", args, "ok", ("seed", lambda _payload: 7))]

    def arguments(context):
        evaluated.append("actor")
        return {"stage": "actor", "seed": context["seed"]}

    actors = [("model_write", arguments, "ok", None)]
    acts = [(act, ("pre_get", {}), actors, list(actors))]
    def call(tool, args):
        if tool == "pre_get":
            wire.seen.append((tool, args))
            return (True, "injected missing premise") if fallback else (False, {"found": True})
        if tool == "workspace_orient":
            wire.seen.append((tool, args))
            return False, {"machining_capabilities": {"observed_generation": {"swarf": observed}}}
        if tool == "cam_get_status":
            wire.seen.append((tool, args))
            return False, {"completed": True, "empty_toolpaths": [], "live_states": {"valid": 1}}
        return wire(tool, args)

    code, wrote, evidence = TestOwnedFamilies._run(
        monkeypatch, tmp_path, call, acts, fixture=fixture,
        acts_spec=act if selected else None, keep_open=keep_open)
    assert code == 0
    assert made == {("part_cam", None, None): 1, ("part_cam", act, False): 1,
                    ("part_cam", act, True): 1}
    assert evaluated == [("part_cam", None, None), ("part_cam", act, False), "actor"]
    assert evidence["admitted_batches"] == records
    assert all(record["status"] == "admitted" for record in records)
    assert any(record["phase"] == act + (" fallback" if fallback else " narrative")
               for record in records)
    assert dispatch and all(any(batch is cached for cached, _routes in registration)
                            for batch in dispatch)
    assert all(not any(route[0] in ("reload-smoke", "family-switch") for route in routes)
               for _batch, routes in registration if selected)
    assert (wire.active != "session:home") is keep_open


@pytest.mark.parametrize("selected,keep_open", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("fallback", [False, True])
def test_baseline_real_tiny_legacy_consumer_has_no_unreachable_family_support(
        monkeypatch, tmp_path, selected, keep_open, fallback):
    program, registration, dispatch, records = _baseline_real_consumer_spies(
        monkeypatch, {"pre_get"})
    evaluated = []
    actors = [("probe_get", lambda context: evaluated.append("actor") or {"n": 7}, "ok", None)]
    acts = [("A", ("pre_get", {}), actors, list(actors))]
    def call(tool, args):
        if tool == "sys_get_preferences":
            assert evaluated == [], "arguments evaluated before admission"
            return _preference_reply()
        if tool == "doc_get":
            return False, {"active": {"document_handle": "session:home", "is_modified": False},
                           "open_count": 1, "truncated": False, "open_documents": [
                               {"document_handle": "session:home", "is_active": True}]}
        if tool == "pre_get":
            return (True, "missing") if fallback else (False, {"n": 1})
        return False, {"n": 1}
    real_run = tool_verify.run
    monkeypatch.setattr(tool_verify, "run", lambda *args, **kwargs: real_run(
        *args, **dict(kwargs, acts_spec="A" if selected else None, keep_open=keep_open)))
    code, wrote = _run_document_program(monkeypatch, tmp_path, call, acts, writes=())
    assert code == 0 and evaluated == ["actor"] and len(dispatch) == 1
    assert all(not routes for _batch, routes in registration)
    assert records == [{"phase": "A " + ("fallback" if fallback else "narrative"),
                        "tools": ["probe_get"], "source_indices": [0], "status": "admitted"}]


@pytest.mark.parametrize("branch", ["initial", "before"])
def test_baseline_real_consumer_refuses_substituted_cached_row_before_arguments(
        monkeypatch, tmp_path, branch):
    wire = _DocumentWire()
    act = "ACT 3 - SURFACES"
    program, registration, dispatch, records = _baseline_real_consumer_spies(
        monkeypatch, {"design_get", "doc_activate"})
    original_cache = program.cache_baseline_plan
    forbidden = []
    def substitute(*args, **kwargs):
        plan = original_cache(*args, **kwargs)
        rogue = ("model_write", lambda context: forbidden.append(True) or {}, "ok", None)
        if branch == "initial":
            plan["initial"]["surfaces"] = (rogue,)
        else:
            plan["before"][act][True] = (rogue,)
        return plan
    monkeypatch.setattr(program, "cache_baseline_plan", substitute)
    def fixture(family, before_act=None, entitled=True):
        return [("model_write", {}, "ok", None)]
    code, wrote, evidence = TestOwnedFamilies._run(
        monkeypatch, tmp_path, wire, [(act, None, [("model_write", {}, "ok", None)], [])],
        fixture=fixture, acts_spec=act)
    assert code == 1 and not wrote and not forbidden
    assert evidence["stopped"] is True
    assert any(record["status"] == "blocked" for record in records)
