# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The facts ledger's entitlement carryover, all against tmp_path copies of the ledger/facts."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live"))
import measure_api  # noqa: E402

_ATTESTATION = {
    "implementation_fingerprint": "a" * 64,
    "schema_fingerprint": "b" * 64,
    "load_id": "L1",
    "session_id": "S1",
}
_SOURCE_HASH = "0" * 64
_GATED_ROW = {"id": "gated-row", "claim": "c1", "encoded_in": "e1",
              "entitlement": "design_manufacturing_extension"}
_PLAIN_ROW = {"id": "plain-row", "claim": "c2", "encoded_in": "e2"}

# The measured refusal texts, verbatim from tests/live/results/contracts-20260927-014118.json,
# contracts-20260926-130846.json and -103807.json.
_REFUSAL_EXTENSION = "RuntimeError: 3 : Manufacturing or Design Extension is required."
_REFUSAL_EQ = "advanced_swarf reads isGenerationAllowed=False - not created, inconclusive"
_REFUSAL_LISTED = ("isGenerationAllowed is not True for multi_axis_contour=False "
                    "- nothing created, inconclusive")
_REFUSAL_EQ_NONE = "advanced_swarf reads isGenerationAllowed=None - not created, inconclusive"
_REFUSAL_LISTED_WITH_NONE = ("isGenerationAllowed is not True for trace=None, morph=False "
                              "- nothing created, inconclusive")
_REFUSAL_ADDITIVE = "Additive Extension is required."


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A tmp_path VERIFIED_API_FACTS.md - measure_api.LEDGER points here for the test's duration."""
    path = tmp_path / "VERIFIED_API_FACTS.md"
    monkeypatch.setattr(measure_api, "LEDGER", str(path))
    return path


def _seed(path, results, build, date):
    """Write a real ledger at path through write_ledger itself."""
    measure_api.write_ledger(results, build, date, _SOURCE_HASH, _ATTESTATION)
    return path


class TestEntitlementRefusal:
    def test_the_extension_required_raise_is_a_refusal(self):
        assert measure_api._entitlement_refusal(_REFUSAL_EXTENSION)

    def test_a_false_isgenerationallowed_equals_form_is_a_refusal(self):
        assert measure_api._entitlement_refusal(_REFUSAL_EQ)

    def test_a_false_isgenerationallowed_listed_form_is_a_refusal(self):
        assert measure_api._entitlement_refusal(_REFUSAL_LISTED)

    def test_isgenerationallowed_true_is_not_a_refusal(self):
        assert not measure_api._entitlement_refusal("row: reads isGenerationAllowed=True - ok")

    def test_isgenerationallowed_none_equals_form_is_not_a_refusal(self):
        assert not measure_api._entitlement_refusal(_REFUSAL_EQ_NONE)

    def test_a_listed_form_with_any_none_pair_is_not_a_refusal(self):
        assert not measure_api._entitlement_refusal(_REFUSAL_LISTED_WITH_NONE)

    def test_additive_extension_required_is_not_a_refusal(self):
        assert not measure_api._entitlement_refusal(_REFUSAL_ADDITIVE)

    def test_unrelated_fail_text_is_not_a_refusal(self):
        assert not measure_api._entitlement_refusal("row: measured 3 but expected 4")


class TestCarryEntitlements:
    def test_a_gated_refusal_carries_forward_dated_from_the_old_stamp(self, ledger):
        _seed(ledger, [(_GATED_ROW, "PASS", "")], build="OLDBUILD", date="OLDDATE")
        [(_row, status, detail)], refusals = measure_api._carry_entitlements(
            [(_GATED_ROW, "FAIL", _REFUSAL_EQ)])
        assert status == "CARRIED"
        assert detail == "needs the Design/Manufacturing Extension; measured OLDDATE on OLDBUILD"
        assert refusals == {"gated-row": _REFUSAL_EQ}

    def test_a_gated_rows_other_failure_stays_fail(self, ledger):
        _seed(ledger, [(_GATED_ROW, "PASS", "")], build="OLDBUILD", date="OLDDATE")
        other = "gated-row: expected 4 counts, measured 3"
        results, refusals = measure_api._carry_entitlements([(_GATED_ROW, "FAIL", other)])
        assert results == [(_GATED_ROW, "FAIL", other)]
        assert refusals == {}

    def test_an_ungated_row_with_the_refusal_text_stays_fail(self, ledger):
        _seed(ledger, [(_PLAIN_ROW, "PASS", "")], build="OLDBUILD", date="OLDDATE")
        results, refusals = measure_api._carry_entitlements([(_PLAIN_ROW, "FAIL", _REFUSAL_EQ)])
        assert results == [(_PLAIN_ROW, "FAIL", _REFUSAL_EQ)]
        assert refusals == {}

    def test_a_gated_row_whose_old_ledger_row_was_fail_stays_fail(self, ledger):
        _seed(ledger, [(_GATED_ROW, "FAIL", "boom")], build="OLDBUILD", date="OLDDATE")
        results, refusals = measure_api._carry_entitlements([(_GATED_ROW, "FAIL", _REFUSAL_EQ)])
        assert results == [(_GATED_ROW, "FAIL", _REFUSAL_EQ)]
        assert refusals == {}

    def test_a_gated_row_absent_from_the_old_ledger_stays_as_measured(self, ledger):
        _seed(ledger, [(_PLAIN_ROW, "PASS", "")], build="OLDBUILD", date="OLDDATE")
        results, refusals = measure_api._carry_entitlements([(_GATED_ROW, "FAIL", _REFUSAL_EQ)])
        assert results == [(_GATED_ROW, "FAIL", _REFUSAL_EQ)]
        assert refusals == {}

    def test_no_ledger_file_leaves_results_as_measured(self, tmp_path, monkeypatch):
        monkeypatch.setattr(measure_api, "LEDGER", str(tmp_path / "absent.md"))
        results, refusals = measure_api._carry_entitlements([(_GATED_ROW, "FAIL", _REFUSAL_EQ)])
        assert results == [(_GATED_ROW, "FAIL", _REFUSAL_EQ)]
        assert refusals == {}

    def test_carrying_an_already_carried_row_twice_keeps_the_first_date_and_build(self, ledger):
        _seed(ledger, [(_GATED_ROW, "CARRIED",
                        "needs the Design/Manufacturing Extension; measured OLDDATE on OLDBUILD")],
              build="NEWBUILD", date="NEWDATE")
        [(_row, status, detail)], refusals = measure_api._carry_entitlements(
            [(_GATED_ROW, "FAIL", _REFUSAL_EQ)])
        assert status == "CARRIED"
        assert detail == "needs the Design/Manufacturing Extension; measured OLDDATE on OLDBUILD"
        assert refusals == {"gated-row": _REFUSAL_EQ}


class TestCheckAcceptsCarried:
    def _prep(self, monkeypatch, rows):
        monkeypatch.setattr(measure_api, "ROWS", rows)
        monkeypatch.setattr(measure_api, "health_gate", lambda: "HEALTH")
        monkeypatch.setattr(measure_api, "_current_attestation",
                            lambda health=None: dict(_ATTESTATION))
        monkeypatch.setattr(measure_api, "_fusion_version", lambda health=None: "B1")
        monkeypatch.setattr(measure_api, "_measure_source_hash", lambda: _SOURCE_HASH)

    def test_check_passes_a_ledger_holding_carried_rows_and_fails_one_holding_fail(
            self, ledger, monkeypatch, capsys):
        rows = [{"id": "r1", "claim": "c1", "encoded_in": "e1"}]
        self._prep(monkeypatch, rows)
        _seed(ledger, [(rows[0], "CARRIED",
                        "needs the Design/Manufacturing Extension; measured D1 on B1")],
              build="B1", date="D1")
        assert measure_api.check() == 0
        out = capsys.readouterr().out
        assert "CARRIED: r1" in out
        assert "all rows PASS" not in out

        _seed(ledger, [(rows[0], "FAIL", "boom")], build="B1", date="D1")
        assert measure_api.check() == 1

    def test_the_projection_still_catches_a_claim_mismatch_with_a_carried_row_present(
            self, ledger, monkeypatch):
        rows = [{"id": "r1", "claim": "c1", "encoded_in": "e1"}]
        self._prep(monkeypatch, rows)
        stale = {"id": "r1", "claim": "a different claim", "encoded_in": "e1"}
        _seed(ledger, [(stale, "CARRIED",
                        "needs the Design/Manufacturing Extension; measured D1 on B1")],
              build="B1", date="D1")
        assert measure_api.check() == 1


class TestResolveCarriedShapes:
    def _write_standing_facts(self, path, shapes):
        path.write_text(
            "FUSION_VERSION = 'X'\nVERIFIED_ON = 'Y'\nENUMS = {}\nNOT_ENUMS = []\nBEHAVIOR = {}\n"
            "SHAPES = " + repr(shapes) + "\n", encoding="utf-8")

    def test_owned_shapes_are_copied_and_unowned_ones_are_not(self, tmp_path, monkeypatch):
        facts_path = tmp_path / "live_api_facts.py"
        self._write_standing_facts(facts_path, {"Foo": ["a", "b"], "Bar": ["z"]})
        monkeypatch.setattr(measure_api, "FACTS", str(facts_path))
        row = {"id": "gated-row", "owns_shapes": ["Foo"]}
        extra = measure_api._resolve_carried_shapes([(row, "detail")])
        assert extra == {"Foo": ["a", "b"]}

    def test_a_missing_owned_name_raises_naming_the_row_and_the_name(self, tmp_path, monkeypatch):
        facts_path = tmp_path / "live_api_facts.py"
        self._write_standing_facts(facts_path, {"Foo": ["a"]})
        monkeypatch.setattr(measure_api, "FACTS", str(facts_path))
        row = {"id": "gated-row", "owns_shapes": ["Missing"]}
        with pytest.raises(ValueError, match="gated-row"):
            measure_api._resolve_carried_shapes([(row, "detail")])

    def test_a_row_owning_no_shapes_needs_no_standing_module(self, tmp_path, monkeypatch):
        monkeypatch.setattr(measure_api, "FACTS", str(tmp_path / "absent.py"))
        row = {"id": "cam-row"}
        assert measure_api._resolve_carried_shapes([(row, "detail")]) == {}

    def test_an_absent_standing_module_raises_valueerror_naming_the_row(self, tmp_path, monkeypatch):
        monkeypatch.setattr(measure_api, "FACTS", str(tmp_path / "absent.py"))
        row = {"id": "gated-row", "owns_shapes": ["Foo"]}
        with pytest.raises(ValueError, match="gated-row"):
            measure_api._resolve_carried_shapes([(row, "detail")])

    def test_an_unreadable_standing_module_raises_valueerror_naming_the_row(self, tmp_path, monkeypatch):
        facts_path = tmp_path / "live_api_facts.py"
        facts_path.write_text("this is not (valid python\n", encoding="utf-8")
        monkeypatch.setattr(measure_api, "FACTS", str(facts_path))
        row = {"id": "gated-row", "owns_shapes": ["Foo"]}
        with pytest.raises(ValueError, match="gated-row"):
            measure_api._resolve_carried_shapes([(row, "detail")])

    def test_a_standing_module_lacking_shapes_raises_valueerror_naming_the_row(
            self, tmp_path, monkeypatch):
        facts_path = tmp_path / "live_api_facts.py"
        facts_path.write_text("FUSION_VERSION = 'X'\n", encoding="utf-8")
        monkeypatch.setattr(measure_api, "FACTS", str(facts_path))
        row = {"id": "gated-row", "owns_shapes": ["Foo"]}
        with pytest.raises(ValueError, match="gated-row"):
            measure_api._resolve_carried_shapes([(row, "detail")])


class TestWriteApiFactsCarriedComment:
    def test_the_shapes_block_names_the_carried_row_its_label_and_its_owned_types(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(measure_api, "FACTS", str(tmp_path / "live_api_facts.py"))
        row = {"id": "gated-row", "owns_shapes": ["Foo"]}
        label = "needs the Design/Manufacturing Extension; measured D1 on B1"
        measure_api.write_api_facts({}, "B1", "D1", shapes={"Foo": ["a"]}, carried=[(row, label)])
        written = (tmp_path / "live_api_facts.py").read_text(encoding="utf-8")
        assert "# CARRIED gated-row: " + label + " - owns Foo" in written


def _fake_fusion(script_responses):
    """A minimal live-Fusion call() double: scratch lifecycle plus one canned script response per row."""
    closed = {"value": False}

    def call(tool, _args):
        if tool == "doc_new":
            return False, {"document_handle": "session:TESTDOC"}
        if tool == "doc_get":
            docs = [] if closed["value"] else [
                {"document_handle": "session:TESTDOC", "is_active": True, "is_saved": False}]
            return False, {"open_documents": docs, "truncated": False}
        if tool == "doc_close":
            closed["value"] = True
            return False, {}
        if tool == "sys_execute_script":
            return script_responses.pop(0)
        raise AssertionError("unexpected tool: " + tool)
    return call


def _install(monkeypatch, tmp_path, rows, script_responses):
    monkeypatch.setattr(measure_api, "ROWS", rows)
    monkeypatch.setattr(measure_api, "LEDGER", str(tmp_path / "VERIFIED_API_FACTS.md"))
    monkeypatch.setattr(measure_api, "FACTS", str(tmp_path / "live_api_facts.py"))
    monkeypatch.setattr(measure_api, "health_gate", lambda: "HEALTH")
    monkeypatch.setattr(measure_api, "_current_attestation", lambda health=None: dict(_ATTESTATION))
    monkeypatch.setattr(measure_api, "_fusion_version", lambda health=None: "NEWBUILD")
    monkeypatch.setattr(measure_api, "registered_tools",
                        lambda health=None, include_rows=False: ["sys_execute_script"])
    monkeypatch.setattr(measure_api, "_measure_source_hash", lambda: _SOURCE_HASH)
    monkeypatch.setattr(measure_api, "call", _fake_fusion(script_responses))
    return measure_api.LEDGER


class TestRunMeasurementsRewriteGate:
    ROWS = [dict(_PLAIN_ROW, body="    pass\n"),
            dict(_GATED_ROW, body="    pass\n", owns_shapes=["Foo"])]

    def test_pass_and_carried_together_rewrite_the_ledger(self, tmp_path, monkeypatch, capsys):
        ledger_path = _install(monkeypatch, tmp_path, self.ROWS,
                               [(False, "PASS plain-row ok"), (False, "FAIL " + _REFUSAL_EQ)])
        (tmp_path / "live_api_facts.py").write_text(
            "FUSION_VERSION = 'X'\nVERIFIED_ON = 'Y'\nENUMS = {}\nNOT_ENUMS = []\nBEHAVIOR = {}\n"
            "SHAPES = {'Foo': ['x', 'y']}\n", encoding="utf-8")
        _seed(tmp_path / "VERIFIED_API_FACTS.md",
             [(self.ROWS[0], "PASS", ""), (self.ROWS[1], "PASS", "")],
             build="OLDBUILD", date="OLDDATE")
        rc = measure_api.run_measurements(write_json=False)
        assert rc == 0
        written = open(ledger_path, encoding="utf-8").read()
        assert "| CARRIED: needs the Design/Manufacturing Extension; " \
               "measured OLDDATE on OLDBUILD | gated-row |" in written
        assert "| PASS | plain-row |" in written
        assert "Stamp: Fusion NEWBUILD" in written
        facts_written = (tmp_path / "live_api_facts.py").read_text(encoding="utf-8")
        assert '"Foo": [' in facts_written and '"x",' in facts_written and '"y",' in facts_written
        assert ("# CARRIED gated-row: needs the Design/Manufacturing Extension; "
               "measured OLDDATE on OLDBUILD - owns Foo") in facts_written
        out = capsys.readouterr().out
        assert "FAIL   gated-row" in out
        assert "CARRIED gated-row" in out
        assert "1 shaped types" in out

    def test_one_uncarriable_fail_blocks_the_rewrite(self, tmp_path, monkeypatch):
        ledger_path = _install(monkeypatch, tmp_path, self.ROWS,
                               [(False, "PASS plain-row ok"),
                                (False, "FAIL gated-row: measured 3 but expected 4")])
        seeded = _seed(tmp_path / "VERIFIED_API_FACTS.md",
                       [(self.ROWS[0], "PASS", ""), (self.ROWS[1], "PASS", "")],
                       build="OLDBUILD", date="OLDDATE")
        before = open(seeded, encoding="utf-8").read()
        rc = measure_api.run_measurements(write_json=False)
        assert rc == 1
        after = open(ledger_path, encoding="utf-8").read()
        assert after == before

    def test_a_missing_owned_shape_leaves_both_files_untouched_and_returns_1(
            self, tmp_path, monkeypatch):
        rows = [dict(_PLAIN_ROW, body="    pass\n"),
                dict(_GATED_ROW, body="    pass\n", owns_shapes=["Missing"])]
        ledger_path = _install(monkeypatch, tmp_path, rows,
                               [(False, "PASS plain-row ok"), (False, "FAIL " + _REFUSAL_EQ)])
        facts_path = tmp_path / "live_api_facts.py"
        facts_path.write_text(
            "FUSION_VERSION = 'X'\nVERIFIED_ON = 'Y'\nENUMS = {}\nNOT_ENUMS = []\nBEHAVIOR = {}\n"
            "SHAPES = {'Foo': ['x']}\n", encoding="utf-8")
        facts_before = facts_path.read_text(encoding="utf-8")
        seeded = _seed(tmp_path / "VERIFIED_API_FACTS.md",
                       [(rows[0], "PASS", ""), (rows[1], "PASS", "")],
                       build="OLDBUILD", date="OLDDATE")
        ledger_before = open(seeded, encoding="utf-8").read()
        rc = measure_api.run_measurements(write_json=False)
        assert rc == 1
        assert open(ledger_path, encoding="utf-8").read() == ledger_before
        assert facts_path.read_text(encoding="utf-8") == facts_before

    def test_an_absent_standing_module_returns_1_but_still_writes_the_json_archive(
            self, tmp_path, monkeypatch):
        ledger_path = _install(monkeypatch, tmp_path, self.ROWS,
                               [(False, "PASS plain-row ok"), (False, "FAIL " + _REFUSAL_EQ)])
        # FACTS is never written in this test - the standing module this run would read from
        # does not exist.
        seeded = _seed(tmp_path / "VERIFIED_API_FACTS.md",
                       [(self.ROWS[0], "PASS", ""), (self.ROWS[1], "PASS", "")],
                       build="OLDBUILD", date="OLDDATE")
        ledger_before = open(seeded, encoding="utf-8").read()
        rc = measure_api.run_measurements(write_json=True)
        assert rc == 1
        assert open(ledger_path, encoding="utf-8").read() == ledger_before
        [path] = list((tmp_path / "results").glob("contracts-*.json"))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert any(r["id"] == "gated-row" for r in data["rows"])

    def test_only_never_rewrites_even_when_carried(self, tmp_path, monkeypatch):
        ledger_path = _install(monkeypatch, tmp_path, self.ROWS, [(False, "FAIL " + _REFUSAL_EQ)])
        # A resolvable standing module: the only thing that can block a rewrite here is the
        # --only gate itself, not an incidental shape-resolution failure.
        (tmp_path / "live_api_facts.py").write_text(
            "FUSION_VERSION = 'X'\nVERIFIED_ON = 'Y'\nENUMS = {}\nNOT_ENUMS = []\nBEHAVIOR = {}\n"
            "SHAPES = {'Foo': ['x']}\n", encoding="utf-8")
        seeded = _seed(tmp_path / "VERIFIED_API_FACTS.md",
                       [(self.ROWS[0], "PASS", ""), (self.ROWS[1], "PASS", "")],
                       build="OLDBUILD", date="OLDDATE")
        before = open(seeded, encoding="utf-8").read()
        measure_api.run_measurements(write_json=False, only={"gated-row"})
        after = open(ledger_path, encoding="utf-8").read()
        assert after == before

    def test_a_fresh_dump_wins_over_a_carried_copy_for_the_same_type(self, tmp_path, monkeypatch):
        rows = [dict(_PLAIN_ROW, body="    pass\n"),
                dict(_GATED_ROW, body="    pass\n", owns_shapes=["Foo"])]
        _install(monkeypatch, tmp_path, rows,
                [(False, "PASS plain-row ok\nSHAPE Foo fresh_attr"),
                 (False, "FAIL " + _REFUSAL_EQ)])
        (tmp_path / "live_api_facts.py").write_text(
            "FUSION_VERSION = 'X'\nVERIFIED_ON = 'Y'\nENUMS = {}\nNOT_ENUMS = []\nBEHAVIOR = {}\n"
            "SHAPES = {'Foo': ['carried_attr']}\n", encoding="utf-8")
        _seed(tmp_path / "VERIFIED_API_FACTS.md",
             [(rows[0], "PASS", ""), (rows[1], "PASS", "")], build="OLDBUILD", date="OLDDATE")
        measure_api.run_measurements(write_json=False)
        written = (tmp_path / "live_api_facts.py").read_text(encoding="utf-8")
        assert '"fresh_attr"' in written
        assert "carried_attr" not in written

    def test_the_json_row_keeps_the_refusal_detail_beside_the_carried_label(
            self, tmp_path, monkeypatch):
        _install(monkeypatch, tmp_path, self.ROWS,
                [(False, "PASS plain-row ok"), (False, "FAIL " + _REFUSAL_EQ)])
        (tmp_path / "live_api_facts.py").write_text(
            "FUSION_VERSION = 'X'\nVERIFIED_ON = 'Y'\nENUMS = {}\nNOT_ENUMS = []\nBEHAVIOR = {}\n"
            "SHAPES = {'Foo': ['x']}\n", encoding="utf-8")
        _seed(tmp_path / "VERIFIED_API_FACTS.md",
             [(self.ROWS[0], "PASS", ""), (self.ROWS[1], "PASS", "")],
             build="OLDBUILD", date="OLDDATE")
        measure_api.run_measurements(write_json=True)
        [path] = list((tmp_path / "results").glob("contracts-*.json"))
        data = json.loads(path.read_text(encoding="utf-8"))
        [gated_row] = [r for r in data["rows"] if r["id"] == "gated-row"]
        assert gated_row["status"] == "CARRIED"
        assert gated_row["detail"] == \
            "needs the Design/Manufacturing Extension; measured OLDDATE on OLDBUILD"
        assert gated_row["refusal"] == _REFUSAL_EQ
