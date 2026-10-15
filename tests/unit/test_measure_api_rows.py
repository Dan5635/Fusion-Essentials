# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The measurement registry's shape: every ROW composes into a script Fusion can run.

A row's body is source text that only ever executes inside live Fusion, so a syntax error in one
reaches the run as an ERROR row hours later - and a duplicate id silently overwrites a claim's
ledger cell. Both are decidable offline, against the same _compose the runner calls. A row that
touches the operator's own cloud files or session state is read here as data for the same reason.
"""

import ast
import os
import sys
import types

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live"))
import measure_api  # noqa: E402


def _run_body(row_id):
    """One row's own composed statements - the `run` function _compose builds around its body, so
    the shared template's helpers are outside what these tests read."""
    row = next(r for r in measure_api.ROWS if r["id"] == row_id)
    tree = ast.parse(measure_api._compose(row))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "run")


def _dumped_shape_labels(row):
    """A row's dump_shape("Label", ...) labels, direct or via a (label, object) tuple literal."""
    tree = ast.parse(measure_api._compose(row))
    labels = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "dump_shape" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            labels.add(node.args[0].value)
        elif (isinstance(node, ast.Tuple) and len(node.elts) == 2
              and isinstance(node.elts[0], ast.Constant) and isinstance(node.elts[0].value, str)):
            labels.add(node.elts[0].value)
    return labels


class TestRowRegistry:
    def test_every_row_composes_into_compilable_python(self):
        broken = []
        for row in measure_api.ROWS:
            try:
                compile(measure_api._compose(row), row["id"], "exec")
            except SyntaxError as e:
                broken.append(f"{row['id']}: line {e.lineno}: {e.msg}")
        assert not broken, (
            "measurement row bodies that do not compile - they would reach live Fusion as ERROR "
            "rows:\n  " + "\n  ".join(broken))

    def test_every_closing_script_composes_into_compilable_python(self):
        # a closing script is built from the first script's output, so it never meets the check
        # above - and the one that ends an open Form edit is what the rows after it depend on.
        printed = 'FORMSTATE {"token": "t", "count": 1}\nPASS opened'
        closing = [row for row in measure_api.ROWS if row.get("script_after_fn")]
        assert closing
        for row in closing:
            compile(measure_api._compose(measure_api._closing_row(row, printed)), row["id"], "exec")

    def test_row_ids_are_unique(self):
        seen, dupes = set(), []
        for row in measure_api.ROWS:
            if row["id"] in seen:
                dupes.append(row["id"])
            seen.add(row["id"])
        assert not dupes, "duplicate measurement row ids: " + ", ".join(sorted(set(dupes)))

    def test_every_row_carries_a_claim_and_an_encoding(self):
        # the two columns write_ledger publishes - a row missing either lands a blank ledger cell
        thin = [row["id"] for row in measure_api.ROWS
                if not str(row.get("claim", "")).strip()
                or not str(row.get("encoded_in", "")).strip()]
        assert not thin, "rows with an empty claim or encoded_in: " + ", ".join(thin)

    def test_gated_rows_name_a_known_entitlement_and_their_owned_shapes_match_the_body(self):
        offenders = []
        for row in measure_api.ROWS:
            entitlement = row.get("entitlement")
            if entitlement is None:
                continue
            if entitlement not in measure_api._ENTITLEMENTS:
                offenders.append(f"{row['id']}: unknown entitlement {entitlement!r}")
                continue
            dumped, owned = _dumped_shape_labels(row), set(row.get("owns_shapes", []))
            if dumped != owned:
                offenders.append(f"{row['id']}: body dumps {sorted(dumped)}, "
                                 f"owns_shapes declares {sorted(owned)}")
        assert not offenders, offenders
        gated = {row["id"] for row in measure_api.ROWS if row.get("entitlement")}
        assert gated == {"shape-dump-pmi-world", "cam-advanced-swarf-surface-set-editable",
                         "cam-curves-parameter-carriers"}


class TestWireChecksPinTheScratch:
    def test_a_write_check_carries_the_scratch_pin_and_a_strict_read_does_not(self, monkeypatch):
        rows = ({"name": "design_delete_feature",
                 "inputSchema": {"properties": {"feature": {}, "expect_document": {}}}},
                {"name": "workspace_orient", "inputSchema": {"properties": {}}})
        monkeypatch.setattr(measure_api, "registered_tools",
                            lambda include_rows=False: ([r["name"] for r in rows], rows))
        sent = []
        monkeypatch.setattr(measure_api, "call",
                            lambda tool, args: sent.append((tool, args)) or (True, "refused"))
        row = {"wire_checks": [("workspace_orient", {}, lambda e, p: (True, "read")),
                               ("design_delete_feature", {"feature": "Form1"},
                                lambda e, p: (True, "refused"))]}
        measure_api._run_followups(row, "SCRATCH", "PASS", "", "")
        assert sent == [("workspace_orient", {}),
                        ("design_delete_feature", {"feature": "Form1",
                                                   "expect_document": "SCRATCH"})]


class TestTheDrawingRowDeletesOnlyWhatItSaved:
    """The row saves a file into the operator's OWN cloud project, so a delete keyed on the shared
    name would take whatever else answers to that name - another run's file, or the operator's."""

    ROW = "shape-dump-drawing-world"

    def test_the_only_delete_is_keyed_on_the_id_this_run_saved(self):
        run = _run_body(self.ROW)
        calls = [n for n in ast.walk(run) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "deleteMe"]
        assert len(calls) == 1, [ast.unparse(c) for c in calls]
        target = calls[0].func.value
        assert isinstance(target, ast.Name), ast.unparse(calls[0])
        assigned = [ast.unparse(a.value) for a in ast.walk(run) if isinstance(a, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == target.id for t in a.targets)]
        assert assigned == ["file_by_id(urn)"], assigned

    def test_the_lookup_matches_the_cloud_id_and_never_the_name(self):
        fn = next(n for n in ast.walk(_run_body(self.ROW))
                  if isinstance(n, ast.FunctionDef) and n.name == "file_by_id")
        read = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        assert "id" in read and "name" not in read, sorted(read)

    def test_an_id_that_never_settled_deletes_nothing(self):
        # THE loop that deletes, not any loop in the row: the gate has to sit on the one whose body
        # calls deleteMe, or a settle pump wearing the same gate would pass this.
        deleting = [w for w in ast.walk(_run_body(self.ROW)) if isinstance(w, ast.While)
                    and "deleteMe" in ast.unparse(w)]
        assert len(deleting) == 1, [ast.unparse(w.test) for w in deleting]
        assert "urn is not None" in ast.unparse(deleting[0].test)


class TestTheStickyStlRowRestoresTheSession:
    """The row ASSIGNS the sticky STL unit, which every later export in that Fusion session
    inherits - so a leg that raises must not leave the session on inches."""

    ROW = "stl-export-unittype-is-sticky-session-state"

    def _restoring_try(self):
        tries = [t for t in ast.walk(_run_body(self.ROW)) if isinstance(t, ast.Try)
                 and any("restore-mm" in ast.unparse(n) for n in t.finalbody)]
        assert len(tries) == 1, "the restore is not in exactly one finally"
        return tries[0]

    def test_the_legs_that_move_the_unit_sit_inside_the_restoring_try(self):
        # A finally around nothing restores nothing: the assigning legs have to be in its try.
        body = "\n".join(ast.unparse(n) for n in self._restoring_try().body)
        assert "set-inch" in body and "set-cm" in body, body

    def test_the_files_the_legs_wrote_are_removed_in_the_same_finally(self):
        # Over the list the legs COLLECTED, not any list: `for p in []: os.remove(p)` removes
        # nothing while reading like a cleanup.
        loops = [n for n in self._restoring_try().finalbody if isinstance(n, ast.For)]
        assert len(loops) == 1, [ast.unparse(n) for n in self._restoring_try().finalbody]
        assert ast.unparse(loops[0].iter) == "written"
        assert "os.remove(p)" in ast.unparse(loops[0])
        leg = next(n for n in ast.walk(_run_body(self.ROW))
                   if isinstance(n, ast.FunctionDef) and n.name == "leg")
        assert "written.append(p)" in ast.unparse(leg)


class TestPlatformSkips:
    def _projection_of(self, row, status, detail):
        return measure_api._ledger_projection(measure_api._ledger_row(row, status, detail))[0]

    def test_a_skip_is_accepted_only_on_a_row_that_declares_that_platform(self):
        skipping = next(r for r in measure_api.ROWS if r.get("skip_on"))
        running = next(r for r in measure_api.ROWS if not r.get("skip_on"))
        platform = sorted(skipping["skip_on"])[0]
        written = self._projection_of(
            skipping, "SKIP", measure_api._skip_detail(skipping, platform))
        assert written in measure_api._accepted_ledger_fields(skipping, platform)
        forged = self._projection_of(running, "SKIP", "not run on " + platform + ": hangs")
        assert forged not in measure_api._accepted_ledger_fields(running, platform)

    def test_a_darwin_skip_satisfies_the_check_on_darwin_and_on_no_other_platform(
            self, tmp_path, monkeypatch):
        row = {"id": "r1", "claim": "c1", "encoded_in": "e1", "skip_on": {"darwin": "hangs"}}
        seen = {"implementation_fingerprint": "a" * 64, "schema_fingerprint": "b" * 64,
                "load_id": "L1", "session_id": "S1"}
        monkeypatch.setattr(measure_api, "LEDGER", str(tmp_path / "VERIFIED_API_FACTS.md"))
        monkeypatch.setattr(measure_api, "ROWS", [row])
        monkeypatch.setattr(measure_api, "health_gate", lambda: "HEALTH")
        monkeypatch.setattr(measure_api, "_current_attestation", lambda health=None: dict(seen))
        monkeypatch.setattr(measure_api, "_fusion_version", lambda health=None: "B1")
        monkeypatch.setattr(measure_api, "_measure_source_hash", lambda: "0" * 64)
        measure_api.write_ledger([(row, "SKIP", measure_api._skip_detail(row, "darwin"))],
                                 "B1", "D1", "0" * 64, seen)
        assert measure_api.check(platform="darwin") == 0
        assert measure_api.check(platform="win32") == 1
        # With no platform passed, the checking machine's own sys.platform decides.
        monkeypatch.setattr(measure_api, "sys", types.SimpleNamespace(platform="win32"))
        assert measure_api.check() == 1

    def test_a_skipped_row_runs_on_a_platform_it_does_not_name(self):
        skipping = next(r for r in measure_api.ROWS if r.get("skip_on"))
        assert measure_api._skip_detail(skipping, "no-such-platform") is None

    def test_a_carried_fact_missing_from_the_previous_facts_file_carries_nothing(
            self, tmp_path, monkeypatch):
        facts = tmp_path / "live_api_facts.py"
        facts.write_text("BEHAVIOR = {}\n", encoding="utf-8")
        monkeypatch.setattr(measure_api, "FACTS", str(facts))
        row = {"facts_on_pass": {"behavior.some_flag": True}}
        assert measure_api._carried_facts(row) is None
        facts.write_text("BEHAVIOR = {'some_flag': False}\n", encoding="utf-8")
        assert measure_api._carried_facts(row) == {"behavior.some_flag": False}
