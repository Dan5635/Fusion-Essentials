"""Unit tests for ``_assert.py`` - the postcondition kernel (verify-the-effect).

Covers the wrap() contract (verify runs only on JSON ok results; a hard reason converts ok into
isError; a soft reason marks the payload unconfirmed; evidence merges via setdefault so handler
values win; error results and non-JSON pass through untouched; a capture()/verify() crash on a HARD
postcondition fails CLOSED - verification impossible is an honest error naming the exception and
the kind's read_tool, never a pass - while a soft one annotates) and each shipped kind against
fakes: VersionAdvanced (the
Document.save() false-success), ReferencesFresh (the lying isUpToDate), FileLanded (export wrote
nothing), FeatureHealthy (a feature add()ed but computed with an error health state). Every gate is
proven to BITE (the failure case goes red through the wrapper).
"""
import live_api_facts as _api_facts
_HEALTHY = _api_facts.ENUMS["fusion.FeatureHealthStates"]["HealthyFeatureHealthState"]
_ERROR = _api_facts.ENUMS["fusion.FeatureHealthStates"]["ErrorFeatureHealthState"]
from conftest import install as _install_design

import json
import sys
import types

import pytest

from conftest import (
    BRepBody,
    BRepEdge,
    BRepFace,
    FakeApplication,
    FakeData,
    FakeDataFile,
    FakeDocumentReference,
    FakeFusionDocument,
    FakeMatrix3D,
    FakeTimeline,
    FakeTimelineObject,
    FakeVector3D,
    MakeComp,
    MakeDesign,
    load_tool,
    make_occurrence,
)

kernel = load_tool("_assert")


def _ok(payload):
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


from conftest import payload as _payload


class Fixed(kernel.Postcondition):
    """A postcondition scripted per-test: returns the queued (reason, evidence)."""
    name = "fixed"

    def __init__(self, reason="", evidence=None, severity="hard", capture_value=None, boom=False,
                 capture_boom=False, read_tool=None):
        self._reason = reason
        self._evidence = evidence or {}
        self.severity = severity
        self._capture_value = capture_value
        self._boom = boom
        self._capture_boom = capture_boom
        self.read_tool = read_tool
        self.saw_before = None
        self.saw_kwargs = None

    def capture(self, kwargs):
        if self._capture_boom:
            raise RuntimeError("capture exploded")
        return self._capture_value

    def verify(self, kwargs, payload, before):
        if self._boom:
            raise RuntimeError("verify exploded")
        self.saw_before = before
        self.saw_kwargs = kwargs
        return self._reason, self._evidence


class TestWrapContract:
    def test_confirmed_effect_merges_evidence(self):
        wrapped = kernel.wrap(lambda **kw: _ok({"done": True}), [Fixed(evidence={"size_bytes": 42})])
        out = _payload(wrapped())
        assert out["done"] is True and out["size_bytes"] == 42

    def test_handler_values_win_over_evidence(self):
        wrapped = kernel.wrap(lambda **kw: _ok({"size_bytes": 7}), [Fixed(evidence={"size_bytes": 42})])
        assert _payload(wrapped())["size_bytes"] == 7   # setdefault - never clobber the handler

    def test_hard_reason_converts_ok_into_error(self):
        wrapped = kernel.wrap(lambda **kw: _ok({"done": True}), [Fixed(reason="nothing changed")])
        res = wrapped()
        assert res["isError"] is True
        assert "nothing changed" in res["message"]

    def test_soft_reason_marks_unconfirmed_not_error(self):
        wrapped = kernel.wrap(lambda **kw: _ok({"done": True}),
                              [Fixed(reason="cloud still processing", severity="soft")])
        out = _payload(wrapped())
        assert out["verified"]["fixed"]["confirmed"] is False

    def test_error_results_pass_through_unverified(self):
        p = Fixed(reason="would fail")
        err = {"content": [], "isError": True, "message": "handler refused"}
        assert kernel.wrap(lambda **kw: err, [p])() is err

    def test_capture_value_reaches_verify(self):
        p = Fixed(capture_value={"was": 3})
        _payload(kernel.wrap(lambda **kw: _ok({}), [p])(x=1))
        assert p.saw_before == {"was": 3}
        assert p.saw_kwargs == {"x": 1}

    def test_hard_verify_crash_fails_closed_with_honest_wording(self):
        # verification IMPOSSIBLE on a hard postcondition = an error, never a possible no-op as ok.
        wrapped = kernel.wrap(lambda **kw: _ok({"done": True}),
                              [Fixed(boom=True, read_tool="design_get")])
        res = wrapped()
        assert res["isError"] is True
        assert "verification could not run" in res["message"]
        assert "verify exploded" in res["message"]              # the raising exception is named
        body = json.loads(res["content"][0]["text"])
        assert "may have succeeded" in body["note"]             # honest: the mutation is NOT claimed undone
        assert "design_get" in body["note"]                     # the kind's read tool is the next step

    def test_soft_verify_crash_stays_an_annotation(self):
        wrapped = kernel.wrap(lambda **kw: _ok({"done": True}),
                              [Fixed(boom=True, severity="soft")])
        out = _payload(wrapped())                               # still ok - soft never fails the call
        assert out["fixed_confirmed"] is False
        assert "verify exploded" in out["verify_error"]

    def test_hard_capture_crash_fails_closed(self):
        wrapped = kernel.wrap(lambda **kw: _ok({"done": True}), [Fixed(capture_boom=True)])
        res = wrapped()
        assert res["isError"] is True
        assert "baseline capture failed; handler not run" in res["message"]
        assert "capture exploded" in res["message"]
        body = json.loads(res["content"][0]["text"])
        assert body["handler_not_run"] is True
        assert "handler_reported_unverified_result" not in body
        assert "may have succeeded" not in body["note"]

    def test_soft_capture_crash_stays_an_annotation(self):
        wrapped = kernel.wrap(lambda **kw: _ok({"done": True}),
                              [Fixed(capture_boom=True, severity="soft")])
        out = _payload(wrapped())
        assert out["fixed_confirmed"] is False
        assert "capture exploded" in out["verify_error"]

    def test_hard_capture_crash_blocks_the_handler(self):
        calls = {"n": 0}

        def handler(**kw):
            calls["n"] += 1
            return _ok({"done": True})

        res = kernel.wrap(handler, [Fixed(capture_boom=True)])()
        assert calls["n"] == 0 and res["isError"] is True

    def test_hard_capture_refusal_precedes_a_handler_that_would_error(self):
        err = {"content": [], "isError": True, "message": "handler refused"}
        res = kernel.wrap(lambda **kw: err, [Fixed(capture_boom=True)])()
        assert res is not err and "handler not run" in res["message"]

    @pytest.mark.parametrize("boom", [False, True])
    def test_hard_failure_retains_identities_and_completed_evidence_without_promoting_success(self, boom):
        original = {"created": True, "feature": "Extrude2", "result_bodies": ["Body2"],
                    "postcondition": "not authoritative", "note": "handler says success", "isError": False}
        posts = [Fixed(evidence={"feature_healthy": True}),
                 Fixed(reason="area below threshold", boom=boom, read_tool="model_inspect")]
        result = kernel.wrap(lambda **kw: _ok(original), posts)()
        body = json.loads(result["content"][0]["text"])
        assert result["isError"] is True and body["postcondition"] == "fixed"
        assert "created" not in body and "feature" not in body and "isError" not in body
        assert body["handler_reported_unverified_result"] == dict(original, feature_healthy=True)
        assert "model_inspect" in body["note"] and "not confirmation" in body["note"]

    def test_none_capture_baseline_still_reaches_handler_and_verify(self):
        post = Fixed(capture_value=None, evidence={"baseline_available": False})
        result = _payload(kernel.wrap(lambda **kw: _ok({"created": True}), [post])())
        assert result == {"created": True, "baseline_available": False}

    def test_no_postconditions_returns_handler_unwrapped(self):
        h = lambda **kw: _ok({})
        assert kernel.wrap(h, []) is h

    def test_wrapper_exposes_declaration_for_the_lint(self):
        posts = [Fixed()]
        wrapped = kernel.wrap(lambda **kw: _ok({}), posts)
        assert wrapped.__assert_postconditions__ == posts   # wrap copies the list defensively


# ── the shipped kinds against fakes ──────────────────────────────────────────

class _VersionData(FakeData):
    """Fresh cloud files served in call order; the final reading repeats."""
    def __init__(self, files):
        super().__init__()
        self._sequence = list(files)
        self.calls = 0

    def findFileById(self, lineage):
        item = self._sequence[min(self.calls, len(self._sequence) - 1)]
        self.calls += 1
        return item


def _version(lineage, number, latest=None):
    return FakeDataFile("Part", file_id=lineage, version=number,
                        latest_version=number if latest is None else latest,
                        version_id=f"urn:file?version={number}")


class TestVersionAdvanced:
    def _app(self, modified, lineage="urn:part", fresh=()):
        doc = FakeFusionDocument(is_modified=modified,
                                 data_file=FakeDataFile("Part", file_id=lineage))
        data = _VersionData(fresh) if fresh else FakeData()
        return FakeApplication(active_document=doc, data=data)

    def _post(self, monkeypatch):
        post = kernel.VersionAdvanced()
        monkeypatch.setattr(post, "_DEADLINE_S", 0.0)
        monkeypatch.setattr(post, "_POLL_SLEEP", 0.0)
        return post

    def test_false_success_still_modified_bites_without_claiming_cloud_absence(self, monkeypatch):
        monkeypatch.setattr(kernel, "app", self._app(True))
        wrapped = kernel.wrap(lambda **kw: _ok({"saved": True}), [self._post(monkeypatch)])
        res = wrapped()
        assert res["isError"] is True
        assert "still modified" in res["message"].lower()
        assert "created no version" not in res["message"].lower()

    @pytest.mark.parametrize("fresh,said", [
        ([_version("urn:part", 1), _version("urn:part", 2)],
         "A fresh read shows cloud version 2 landed."),
        ([_version("urn:part", 1), _version("urn:part", 1)], "A fresh read shows no new cloud version."),
        ([None, _version("urn:part", 2)], "Whether a cloud version landed is unknown")])
    def test_a_still_modified_save_reports_one_fresh_version_read(self, monkeypatch, fresh, said):
        app = self._app(True, fresh=fresh)
        monkeypatch.setattr(kernel, "app", app)
        res = kernel.wrap(lambda **kw: _ok({"saved": True}), [self._post(monkeypatch)])()
        assert res["isError"] is True and said in res["message"]
        assert app.data.calls == 2                 # the capture read and ONE fresh read, no poll

    def test_fresh_same_lineage_advance_confirms_separately_from_local_completion(self, monkeypatch):
        app = self._app(False, fresh=[_version("urn:part", 1), _version("urn:part", 2)])
        monkeypatch.setattr(kernel, "app", app)
        out = _payload(kernel.wrap(lambda **kw: _ok({"saved": True}),
                                   [self._post(monkeypatch)])())
        assert out["local_save_confirmed"] is True
        assert out["version_confirmed"] is True
        assert out["latest_version_before"] == 1 and out["latest_version_after"] == 2

    def test_unchanged_fresh_tip_is_pending_not_confirmed(self, monkeypatch):
        app = self._app(False, fresh=[_version("urn:part", 1), _version("urn:part", 1)])
        monkeypatch.setattr(kernel, "app", app)
        out = _payload(kernel.wrap(lambda **kw: _ok({"saved": True}),
                                   [self._post(monkeypatch)])())
        assert out["local_save_confirmed"] is True
        assert out["version_confirmed"] is False and out["pending"] is True

    def test_no_fresh_baseline_is_pending_not_confirmed(self, monkeypatch):
        app = self._app(False, fresh=[None, _version("urn:part", 2)])
        monkeypatch.setattr(kernel, "app", app)
        out = _payload(kernel.wrap(lambda **kw: _ok({"saved": True}),
                                   [self._post(monkeypatch)])())
        assert out["version_confirmed"] is False and out["pending"] is True

    def test_forked_lineage_is_pending_not_compared_as_an_advance(self, monkeypatch):
        app = self._app(False, lineage="urn:old",
                        fresh=[_version("urn:old", 8), _version("urn:new", 1)])
        monkeypatch.setattr(kernel, "app", app)

        def save():
            app.activeDocument.dataFile = FakeDataFile("Part", file_id="urn:new")
            return _ok({"saved": True})

        out = _payload(kernel.wrap(save, [self._post(monkeypatch)])())
        assert out["version_confirmed"] is False and out["pending"] is True
        assert out["latest_version_before"] == 8 and out["latest_version_after"] == 1

    def test_an_older_fresh_tip_is_pending_not_mistaken_for_advancement(self, monkeypatch):
        app = self._app(False, fresh=[_version("urn:part", 8), _version("urn:part", 7)])
        monkeypatch.setattr(kernel, "app", app)
        out = _payload(kernel.wrap(lambda **kw: _ok({"saved": True}),
                                   [self._post(monkeypatch)])())
        assert out["version_confirmed"] is False and out["pending"] is True
        assert out["latest_version_before"] == 8 and out["latest_version_after"] == 7

    def test_ordered_version_number_fallback_publishes_the_observed_numbers(self, monkeypatch):
        readings = [FakeDataFile("Part", file_id="urn:part", version=n, latest_raises=True)
                    for n in (1, 2)]
        monkeypatch.setattr(kernel, "app", self._app(False, fresh=readings))
        out = _payload(kernel.wrap(lambda **kw: _ok({"saved": True}),
                                   [self._post(monkeypatch)])())
        assert out["version_confirmed"] is True
        assert (out["version_before"], out["version_after"]) == (1, 2)
        assert out["latest_version_before"] is None and out["latest_version_after"] is None

    def test_changed_unordered_version_ids_are_unknown(self, monkeypatch):
        old = FakeDataFile("Part", file_id="urn:part", version="old", version_id="urn:old",
                           latest_raises=True)
        new = FakeDataFile("Part", file_id="urn:part", version="new", version_id="urn:new",
                           latest_raises=True)
        app = self._app(False, fresh=[old, new])
        monkeypatch.setattr(kernel, "app", app)
        out = _payload(kernel.wrap(lambda **kw: _ok({"saved": True}),
                                   [self._post(monkeypatch)])())
        assert out["version_id_before"] == "urn:old" and out["version_id_after"] == "urn:new"
        assert out["version_confirmed"] is False and out["pending"] is True

    def test_milestone_observation_avoids_a_second_cloud_wait(self, monkeypatch):
        app = self._app(False, fresh=[_version("urn:part", 1)])
        monkeypatch.setattr(kernel, "app", app)
        out = _payload(kernel.wrap(
            lambda **kw: _ok({"saved": True, "cloud_tip_advanced": True}),
            [self._post(monkeypatch)])())
        assert out["version_confirmed"] is True
        assert app.data.calls == 1

    def test_already_current_noop_skips_the_check(self, monkeypatch):
        monkeypatch.setattr(kernel, "app", self._app(True))
        out = _payload(kernel.wrap(lambda **kw: _ok({"saved": True, "already_current": True}),
                                   [self._post(monkeypatch)])())
        assert out["saved"] is True and "version_confirmed" not in out

    def test_an_unreadable_modified_flag_is_disclosed_not_silently_passed(self, monkeypatch):
        class _Doc(FakeFusionDocument):
            """A document whose dirty flag cannot be read."""

            @property
            def isModified(self):
                raise RuntimeError("the document is gone")

            @isModified.setter
            def isModified(self, value):
                pass

        monkeypatch.setattr(kernel, "app", FakeApplication(active_document=_Doc()))
        out = _payload(kernel.wrap(lambda **kw: _ok({"saved": True}),
                                   [self._post(monkeypatch)])())
        assert out["local_save_confirmed"] is False
        assert out["version_confirmed"] is False


class TestReferencesFresh:
    def _app(self, flags):
        refs = [FakeDocumentReference(out_of_date=f) for f in flags]
        return FakeApplication(active_document=FakeFusionDocument(references=refs))

    def test_surviving_stale_reference_bites(self, monkeypatch):
        monkeypatch.setattr(kernel, "app", self._app([False, True]))
        # the re-read is a bounded settle wait (the refresh lands asynchronously); a zero budget
        # still samples once, so the bite is exercised without spending the shipped budget.
        monkeypatch.setattr(kernel, "_REFERENCE_SETTLE_S", 0.0)
        res = kernel.wrap(lambda **kw: _ok({"updated": True}), [kernel.ReferencesFresh()])()
        assert res["isError"] is True
        assert "still out of date" in res["message"].lower()
        assert "to settle" in res["message"]      # the error says how long the refresh was given

    def test_all_fresh_confirms(self, monkeypatch):
        monkeypatch.setattr(kernel, "app", self._app([False, False]))
        out = _payload(kernel.wrap(lambda **kw: _ok({"updated": True}), [kernel.ReferencesFresh()])())
        assert out["stale_references_after"] == 0

    def test_an_unreadable_reference_walk_is_disclosed_not_silently_passed(self, monkeypatch):
        class _Doc(FakeFusionDocument):
            """The reference walk that will not answer - not the same state as no references."""

            @property
            def documentReferences(self):
                raise RuntimeError("references unavailable")

            @documentReferences.setter
            def documentReferences(self, value):
                pass

        monkeypatch.setattr(kernel, "app", FakeApplication(active_document=_Doc()))
        monkeypatch.setattr(kernel, "_REFERENCE_SETTLE_S", 0.0)
        out = _payload(kernel.wrap(lambda **kw: _ok({"updated": True}), [kernel.ReferencesFresh()])())
        assert out["references_confirmed"] is False
        assert "stale_references_after" not in out


class TestDeliverablesExist:
    def test_every_listed_file_is_verified(self, tmp_path):
        a, b = tmp_path / "a.nc", tmp_path / "b.nc"
        a.write_text("G0 X0"); b.write_text("G1 X1")
        out = _payload(kernel.wrap(
            lambda **kw: _ok({"files": [{"file_path": str(a)}, {"file_path": str(b)}]}),
            [kernel.DeliverablesExist()])())
        assert out["deliverables_verified"] == 2

    def test_one_missing_listed_file_bites(self, tmp_path):
        a = tmp_path / "a.nc"
        a.write_text("G0 X0")
        res = kernel.wrap(
            lambda **kw: _ok({"files": [{"file_path": str(a)},
                                        {"file_path": str(tmp_path / "ghost.nc")}]}),
            [kernel.DeliverablesExist()])()
        assert res["isError"] is True
        assert "ghost.nc" in res["message"]

    def test_single_file_path_shape_is_covered(self, tmp_path):
        p = tmp_path / "out.dxf"
        p.write_text("0\nSECTION")
        out = _payload(kernel.wrap(lambda **kw: _ok({"file_path": str(p)}),
                                   [kernel.DeliverablesExist()])())
        assert out["deliverables_verified"] == 1

    def test_claiming_no_deliverable_at_all_bites(self):
        res = kernel.wrap(lambda **kw: _ok({"exported": True}), [kernel.DeliverablesExist()])()
        assert res["isError"] is True
        assert "names no deliverable" in res["message"]

    def test_list_entry_without_a_path_bites(self, tmp_path):
        res = kernel.wrap(lambda **kw: _ok({"files": [{"size_bytes": 9}]}),
                          [kernel.DeliverablesExist()])()
        assert res["isError"] is True
        assert "files[0]" in res["message"]

    def test_an_empty_files_list_bites_as_no_deliverable(self):
        # a split export whose every write failed reaches the gate with files: [] - an empty list
        # names NO deliverable, so it must fail on the same footing as a missing key, never pass a
        # walk over nothing.
        res = kernel.wrap(lambda **kw: _ok({"exported": False, "files": []}),
                          [kernel.DeliverablesExist()])()
        assert res["isError"] is True
        assert "names no deliverable" in res["message"]
        assert "EMPTY" in res["message"]

    def test_an_empty_list_still_defers_to_a_single_claimed_file(self, tmp_path):
        p = tmp_path / "one.nc"
        p.write_text("G0 X0")
        out = _payload(kernel.wrap(lambda **kw: _ok({"files": [], "file_path": str(p)}),
                                   [kernel.DeliverablesExist()])())
        assert out["deliverables_verified"] == 1


def _tl_item(name, health, msg=""):
    """One timeline entry at an explicit health state - the pair every compute verdict reads."""
    return FakeTimelineObject(name=name, health=health, message=msg)


class TestFeatureHealthy:
    def _wire(self, monkeypatch, timeline):
        p = kernel.FeatureHealthy()
        monkeypatch.setattr(p, "_timeline", lambda: timeline)
        return p

    def test_healthy_added_feature_confirms_with_count(self, monkeypatch):
        tl = FakeTimeline([_tl_item("Extrude1", 0)])
        p = self._wire(monkeypatch, tl)

        def handler(**kw):
            tl._items.append(_tl_item("Extrude2", 0))
            return _ok({"extruded": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert out["features_verified"] == 1

    def test_compute_failed_feature_bites_with_name_and_message(self, monkeypatch):
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl)

        def handler(**kw):
            tl._items.append(_tl_item("Fillet1", 2, "radius too large for the geometry"))
            return _ok({"filleted": True})

        res = kernel.wrap(handler, [p])()
        assert res["isError"] is True
        assert "Fillet1" in res["message"]
        assert "radius too large" in res["message"]

    def test_a_count_that_raises_at_VERIFY_is_disclosed_not_failed_closed(self, monkeypatch):
        # capture counts the timeline, then the verify re-count raises (a mid-recompute read):
        # the count-is-None disposition must disclose feature_health_confirmed: False - without
        # it the numeric comparison against the baseline raises and fails a possibly-fine edit
        # closed.
        class _CountsOnceTimeline:
            def __init__(self):
                self.reads = 0
            @property
            def count(self):
                self.reads += 1
                if self.reads > 1:
                    raise RuntimeError("timeline mid-recompute")
                return 3
        p = self._wire(monkeypatch, _CountsOnceTimeline())
        out = _payload(kernel.wrap(lambda **kw: _ok({"edited": True}), [p])())
        assert out["feature_health_confirmed"] is False
        assert "features_verified" not in out

    def test_a_repeating_fusion_message_is_condensed_to_one_whole_sentence(self, monkeypatch):
        # Fusion's errorOrWarningMessage repeats its sentence, joined by 'Compute Failed' + the
        # feature name - measured at 684 characters for one broken joint. A raw prefix of that blob
        # crossed the wire cut mid-word ("...assembly relationships.C"), reading like a sentence
        # Fusion never finished. The published warning is the FIRST sentence, whole, with no marker
        # text and no embedded newlines.
        sentence = ("Can't resolve some component positions because there are conflicts with "
                    "assembly relationships in the design.\n\nInspect existing assembly relationships.")
        blob = ("Compute FailedChildJ".join([sentence] * 4))
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl)

        def handler(**kw):
            tl._items.append(_tl_item("ChildJ", 1, blob))
            return _ok({"created": True})

        out = _payload(kernel.wrap(handler, [p])())
        published = out["feature_warnings"][0]
        assert published.endswith("Inspect existing assembly relationships.")
        assert "Compute Failed" not in published
        assert "\n" not in published
        assert published == ("ChildJ: Can't resolve some component positions because there are "
                             "conflicts with assembly relationships in the design. Inspect "
                             "existing assembly relationships.")

    def test_compute_warning_is_evidence_not_failure(self, monkeypatch):
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl)

        def handler(**kw):
            tl._items.append(_tl_item("Hole1", 1, "hole extends outside the body"))
            return _ok({"holed": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert out["features_verified"] == 1
        assert out["feature_warnings"] == ["Hole1: hole extends outside the body"]

    def test_only_items_added_by_the_call_are_gated(self, monkeypatch):
        tl = FakeTimeline([_tl_item("OldBroken", 2, "an old unrelated break")])
        p = self._wire(monkeypatch, tl)

        def handler(**kw):
            tl._items.append(_tl_item("Combine1", 0))
            return _ok({"combined": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert out["features_verified"] == 1    # a break present before the call is not gated here

    def test_no_new_timeline_items_skips_silently(self, monkeypatch):
        tl = FakeTimeline([_tl_item("Old1", 0)])
        p = self._wire(monkeypatch, tl)
        out = _payload(kernel.wrap(lambda **kw: _ok({"done": True}), [p])())
        assert "features_verified" not in out   # nothing added -> nothing gated
        assert "feature_health_confirmed" not in out   # ...and the gate DID run

    def test_no_timeline_design_is_disclosed_not_silent(self, monkeypatch):
        # a DIRECT design has no timeline to walk, so the health gate cannot run - the payload says
        # so instead of reading like a clean compute
        p = self._wire(monkeypatch, None)
        out = _payload(kernel.wrap(lambda **kw: _ok({"done": True}), [p])())
        assert out["feature_health_confirmed"] is False
        assert "features_verified" not in out

    def test_an_unreadable_timeline_count_is_disclosed(self, monkeypatch):
        class _PoisonCount(FakeTimeline):
            @property
            def count(self):
                raise RuntimeError("timeline unavailable inside a base-feature scope")

        p = self._wire(monkeypatch, _PoisonCount())
        out = _payload(kernel.wrap(lambda **kw: _ok({"done": True}), [p])())
        assert out["feature_health_confirmed"] is False


class TestSketchCurvesChanged:
    """The entity-set fingerprint gate: an edit that changed nothing bites, and a sketch that cannot
    be read on one side of the call is DISCLOSED rather than passed as a confirmed change."""

    def _wire(self, monkeypatch, fingerprints):
        p = kernel.SketchCurvesChanged()
        seq = iter(fingerprints)
        monkeypatch.setattr(p, "_fingerprint", lambda kwargs: next(seq))
        return p

    def _handler(self, **payload):
        def handler(sketch_name=""):
            return _ok(payload or {"moved": True})
        return handler

    def test_an_unchanged_entity_set_bites(self, monkeypatch):
        marks = {"marks": {("curve", "TOK1"): (4.0, None)}, "curves": 1}
        p = self._wire(monkeypatch, [dict(marks), dict(marks)])
        res = kernel.wrap(self._handler(), [p])(sketch_name="Sketch1")
        assert res["isError"] is True
        assert "unchanged" in res["message"]

    def test_a_changed_entity_set_confirms_with_the_curve_count(self, monkeypatch):
        p = self._wire(monkeypatch, [{"marks": {("curve", "TOK1"): (4.0, None)}, "curves": 1},
                                     {"marks": {("curve", "TOK1"): (9.0, None)}, "curves": 1}])
        out = _payload(kernel.wrap(self._handler(), [p])(sketch_name="Sketch1"))
        assert out["curve_count_after"] == 1

    def test_an_unreadable_sketch_is_disclosed_not_silently_passed(self, monkeypatch):
        p = self._wire(monkeypatch, [None, None])
        out = _payload(kernel.wrap(self._handler(), [p])(sketch_name="Sketch1"))
        assert out["sketch_curves_confirmed"] is False
        assert "curve_count_after" not in out


class TestSketchCurvesChangedScope:
    """The fingerprint reads the sketch the HANDLER acted on. A handler that scoped its by-name
    resolve to a component and a fingerprint that did not would describe two different sketches
    whenever that name is shared - and a name two components share is Fusion's default, since it
    numbers sketches per component from 1."""

    def _spy(self, monkeypatch):
        """Record the (name, scope) pair the fingerprint resolves with, and answer 'no sketch' so
        the gate discloses rather than gating on a fake sketch."""
        seen = []
        import mcpServer.tools._sketch_detail as sd
        import mcpServer.tools._common as common
        _install_design(common, object())

        def _scoped(d, n, c, input_name="component"):
            seen.append((n, c))
            return None, None, None

        monkeypatch.setattr(sd, "scoped_or_recent_sketch", _scoped)
        return seen

    def test_the_handlers_scope_reaches_the_fingerprint(self, monkeypatch):
        p = kernel.SketchCurvesChanged(scope_keys=("component",))
        seen = self._spy(monkeypatch)

        def handler(sketch_name="", component=""):
            return _ok({"moved": True})

        kernel.wrap(handler, [p])(sketch_name="Plate", component="Beta")
        assert seen == [("Plate", "Beta"), ("Plate", "Beta")]     # capture and verify both scoped

    def test_two_references_do_not_borrow_each_others_scope(self, monkeypatch):
        # the copy shape: 'target_sketch' is narrowed by 'target_component', 'sketch_name' by
        # 'component'. Pairing them by anything but position reads the source's component.
        p = kernel.SketchCurvesChanged(keys=("target_sketch", "sketch_name"),
                                       scope_keys=("target_component", "component"))
        seen = self._spy(monkeypatch)

        def handler(sketch_name="", target_sketch="", component="", target_component=""):
            return _ok({"copied": True})

        kernel.wrap(handler, [p])(sketch_name="Plate", component="Alpha",
                                  target_sketch="Plate", target_component="Beta")
        assert seen == [("Plate", "Beta"), ("Plate", "Beta")]

    def test_falling_through_to_the_second_name_takes_the_SECOND_scope(self, monkeypatch):
        # a copy with no 'target_sketch' writes into the SOURCE sketch, so the fingerprint falls
        # through to 'sketch_name' - and must then read 'component', not the target scope that
        # narrows a reference this call never made.
        p = kernel.SketchCurvesChanged(keys=("target_sketch", "sketch_name"),
                                       scope_keys=("target_component", "component"))
        seen = self._spy(monkeypatch)

        def handler(sketch_name="", target_sketch="", component="", target_component=""):
            return _ok({"copied": True})

        kernel.wrap(handler, [p])(sketch_name="Plate", component="Alpha", target_component="Beta")
        assert seen == [("Plate", "Alpha"), ("Plate", "Alpha")]

    def test_a_blank_name_still_carries_its_scope(self, monkeypatch):
        # an empty name means "the most recent sketch", and the scope decides WHOSE.
        p = kernel.SketchCurvesChanged(scope_keys=("component",))
        seen = self._spy(monkeypatch)

        def handler(sketch_name="", component=""):
            return _ok({"moved": True})

        kernel.wrap(handler, [p])(component="Beta")
        assert seen == [("", "Beta"), ("", "Beta")]

    def test_a_scope_key_the_handler_does_not_take_is_refused_at_wiring(self):
        p = kernel.SketchCurvesChanged(scope_keys=("nope",))

        def handler(sketch_name=""):
            return _ok({})

        with pytest.raises(ValueError, match="nope"):
            kernel.wrap(handler, [p])


# ── ChildGeometryMoved: a joint's reposition must reach the NESTED body geometry ────────────────
#
# The fake occurrence tree is built from types.SimpleNamespace (no bespoke Fake* classes): a handler
# moves a part by reassigning occ.transform.translation and, when it propagates, the nested body's
# boundingBox.minPoint - exactly the world reads the kind captures before / verifies after.

def _pt(x, y, z):
    return types.SimpleNamespace(x=x, y=y, z=z)


def _body(bbmin):
    return types.SimpleNamespace(boundingBox=types.SimpleNamespace(minPoint=bbmin))


def _coll(items):
    return types.SimpleNamespace(count=len(items), item=lambda i, items=items: items[i])


def _occ(name, transl, bodies=None, children=None):
    matrix = types.SimpleNamespace(translation=transl)
    return make_occurrence(path=name, transform=matrix, transform2=matrix,
                           assembly_context=make_occurrence('Host:1'),
                           bodies=bodies or [], children=children or [])


class TestComputeFailureReaders:
    """The shared compute-failure readers every republished failure message goes through."""

    def test_message_stops_at_the_first_marker(self):
        raw = "Slot is outside the body.Compute FailedCut1Slot is outside the body."
        assert kernel.compute_failure_message(raw) == "Slot is outside the body."

    def test_message_collapses_the_embedded_newlines(self):
        assert kernel.compute_failure_message("a\n\nb") == "a b"

    def test_empty_and_none_answer_empty(self):
        assert kernel.compute_failure_message(None) == ""
        assert kernel.compute_failure_message("") == ""

    # The cap is an EXACT boundary: a message OF the limit crosses whole, one character more is cut
    # and MARKED, so a shortened message never reads as a complete one.
    def test_a_message_exactly_at_the_limit_is_not_cut(self):
        text = "x" * kernel._MESSAGE_LIMIT
        assert kernel.compute_failure_message(text) == text

    def test_a_message_one_over_the_limit_is_cut_and_marked(self):
        text = "x" * (kernel._MESSAGE_LIMIT + 1)
        out = kernel.compute_failure_message(text)
        assert out.endswith(" ...")
        assert out == "x" * kernel._MESSAGE_LIMIT + " ..."

    def test_classifier_labels_error_warning_and_healthy(self):
        assert kernel.compute_failure(_tl_item("F", 2, "bad")) == ("error", "bad")
        assert kernel.compute_failure(_tl_item("F", 1, "iffy")) == ("warning", "iffy")
        assert kernel.compute_failure(_tl_item("F", 0, "")) is None

    def test_an_unreadable_state_is_no_verdict(self):
        # A health state that will not read is not a failure AND not a pass - the caller decides.
        class _Blind:
            @property
            def healthState(self):
                raise RuntimeError("healthState unreadable")

        assert kernel.compute_failure(_Blind()) is None
        assert kernel.compute_failure(None) is None

    def test_health_state_read_separates_the_two_Nones_the_classifier_returns(self):
        # compute_failure answers None for a state it does not flag AND for one that never read.
        # This is the half that tells them apart, so a caller can publish 'healthy' for the first
        # and withhold the flag for the second.
        class _Blind:
            @property
            def healthState(self):
                raise RuntimeError("healthState unreadable")

        class _Absent:
            """The measured AsBuiltJoint shape: no healthState attribute at all."""

        assert kernel.health_state_read(_tl_item("F", 0, "")) is True
        assert kernel.health_state_read(_tl_item("F", 2, "bad")) is True
        assert kernel.health_state_read(_Blind()) is False
        assert kernel.health_state_read(_Absent()) is False
        assert kernel.health_state_read(None) is False


class TestComputeState:
    """The ONE entity-plus-timelineObject dispatch every published health verdict runs -
    assembly_get's rows, workspace_orient's rollup and joint_create's read-back. It answers the
    three-valued state AND the failure pair the verdict was taken from, so a caller republishing the
    message states the failure this read found rather than one of its own."""

    def _paired(self, own_health=None, tl_health=None, own_msg="", tl_msg=""):
        """An entity carrying a healthState only where `own_health` is given (the measured
        AsBuiltJoint shape has none at all) and a timelineObject only where `tl_health` is."""
        ent = types.SimpleNamespace(name="E")
        if own_health is not None:
            ent.healthState = own_health
            ent.errorOrWarningMessage = own_msg
        if tl_health is not None:
            ent.timelineObject = _tl_item("E", tl_health, tl_msg)
        return ent

    def test_a_failed_entity_answers_broken_and_hands_back_the_failure(self):
        state, failure = kernel.compute_state(self._paired(own_health=_ERROR, own_msg="over-constrained"))
        assert state == "broken"
        assert failure == ("error", "over-constrained")

    def test_a_failure_only_the_timeline_item_carries_is_still_broken(self):
        # the measured AsBuiltJoint/RigidGroup shape: no healthState on the object at all, the
        # timeline item beside it answering. A read of the entity alone calls this healthy.
        state, failure = kernel.compute_state(self._paired(tl_health=1, tl_msg="conflict"))
        assert state == "broken"
        assert failure == ("warning", "conflict")

    def test_the_entity_is_read_first_when_both_sources_fail(self):
        # both carry a failure with DIFFERENT text, so the order is what the assertion reads.
        _state, failure = kernel.compute_state(
            self._paired(own_health=_ERROR, own_msg="from the entity",
                         tl_health=_ERROR, tl_msg="from the timeline item"))
        assert failure == ("error", "from the entity")

    def test_a_healthy_timeline_item_does_not_mask_a_failed_entity(self):
        state, failure = kernel.compute_state(
            self._paired(own_health=1, own_msg="iffy", tl_health=_HEALTHY))
        assert state == "broken" and failure == ("warning", "iffy")

    # The failing pair is WARNING (1) and ERROR (2); the two states either side of it read and are
    # deliberately not flagged, so both boundaries are pinned rather than the middle alone.
    def test_healthy_is_the_boundary_below_the_failing_pair(self):
        assert kernel.compute_state(self._paired(own_health=_HEALTHY)) == ("healthy", None)

    def test_suppressed_is_the_boundary_above_the_failing_pair(self):
        # 3 = SUPPRESSED: a state that READ and is parked on purpose - healthy, never withheld.
        assert kernel.compute_state(self._paired(own_health=3)) == ("healthy", None)

    def test_a_state_only_the_timeline_item_answers_reads_healthy(self):
        assert kernel.compute_state(self._paired(tl_health=_HEALTHY)) == ("healthy", None)

    def test_neither_source_answering_is_unknown_not_healthy(self):
        # An unread state is not a clean bill of health: the caller withholds its flag on this.
        assert kernel.compute_state(self._paired()) == ("unknown", None)
        assert kernel.compute_state(None) == ("unknown", None)

    def test_a_raising_health_state_is_unknown_on_both_sources(self):
        class _Blind:
            @property
            def healthState(self):
                raise RuntimeError("healthState unreadable")

            @property
            def timelineObject(self):
                raise RuntimeError("timelineObject unreadable")

        assert kernel.compute_state(_Blind()) == ("unknown", None)


class TestChildGeometryMoved:
    def _wire(self, monkeypatch, occs):
        p = kernel.ChildGeometryMoved()
        monkeypatch.setattr(p, "_top_occurrences", lambda: occs)
        return p

    def test_propagated_move_confirms(self, monkeypatch):
        cbody = _body(_pt(0, 0, 0))
        child = _occ("Child:1", _pt(0, 0, 0), bodies=[cbody])
        wrapper = _occ("Wrapper:1", _pt(0, 0, 0), children=[child])
        p = self._wire(monkeypatch, [wrapper])

        def handler(**kw):
            wrapper.transform.translation = _pt(8.5, 8.5, 0)   # the joint moved the wrapper
            cbody.boundingBox.minPoint = _pt(8.5, 8.5, 0)      # ...and the nested child followed
            return _ok({"created": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert out["child_geometry_move_verified"] is True

    def test_frozen_nested_child_bites_and_teaches_the_lock_workaround(self, monkeypatch):
        cbody = _body(_pt(0, 0, 0))
        child = _occ("Child:1", _pt(0, 0, 0), bodies=[cbody])
        wrapper = _occ("Wrapper:1", _pt(0, 0, 0), children=[child])
        p = self._wire(monkeypatch, [wrapper])

        def handler(**kw):
            wrapper.transform.translation = _pt(8.5, 8.5, 0)   # transform moved...
            # ...but cbody stays at origin: the non-propagation defect
            return _ok({"created": True})

        res = kernel.wrap(handler, [p])()
        assert res["isError"] is True
        assert "did not propagate" in res["message"].lower()
        assert "Wrapper:1" in res["message"]
        # The taught remedy is the multi-level-proven one: LOCK every nested free occurrence
        # (ground_to_parent), then joint the WRAPPER.
        assert "LOCK" in res["message"] and "ground_to_parent" in res["message"]
        assert "joint the WRAPPER" in res["message"]

    def test_no_move_passes_but_verifies_no_move(self, monkeypatch):
        # Nothing was repositioned, so there is no move to verify: the call PASSES (an expected-zero
        # joint is legitimate) but the flag is null, not True. A True here is the measured false-ok -
        # a joint that computed broken and moved nothing published created:true beside
        # child_geometry_move_verified:true, and the flag was the reason it read as confirmed.
        cbody = _body(_pt(0, 0, 0))
        child = _occ("Child:1", _pt(0, 0, 0), bodies=[cbody])
        wrapper = _occ("Wrapper:1", _pt(0, 0, 0), children=[child])
        p = self._wire(monkeypatch, [wrapper])
        out = _payload(kernel.wrap(lambda **kw: _ok({"created": True}), [p])())
        assert out["child_geometry_move_verified"] is None
        assert out["repositioned_occurrences"] == []

    def test_a_propagated_move_names_the_part_it_repositioned(self, monkeypatch):
        cbody = _body(_pt(0, 0, 0))
        child = _occ("Child:1", _pt(0, 0, 0), bodies=[cbody])
        wrapper = _occ("Wrapper:1", _pt(0, 0, 0), children=[child])
        p = self._wire(monkeypatch, [wrapper])

        def handler(**kw):
            wrapper.transform.translation = _pt(8.5, 8.5, 0)
            cbody.boundingBox.minPoint = _pt(8.5, 8.5, 0)
            return _ok({"created": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert out["child_geometry_move_verified"] is True
        assert out["repositioned_occurrences"] == ["Wrapper:1"]

    # The move tolerance is an EXACT boundary: _MOVE_TOL_CM is solver noise, so a shift OF exactly
    # that much is not a reposition (strictly greater wins) while a hair more is.
    def test_a_shift_of_exactly_the_tolerance_is_not_a_reposition(self, monkeypatch):
        tol = kernel.ChildGeometryMoved._MOVE_TOL_CM
        cbody = _body(_pt(0, 0, 0))
        child = _occ("Child:1", _pt(0, 0, 0), bodies=[cbody])
        wrapper = _occ("Wrapper:1", _pt(0, 0, 0), children=[child])
        p = self._wire(monkeypatch, [wrapper])

        def handler(**kw):
            wrapper.transform.translation = _pt(tol, 0, 0)
            cbody.boundingBox.minPoint = _pt(tol, 0, 0)
            return _ok({"created": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert out["child_geometry_move_verified"] is None
        assert out["repositioned_occurrences"] == []

    def test_a_shift_just_over_the_tolerance_is_a_reposition(self, monkeypatch):
        tol = kernel.ChildGeometryMoved._MOVE_TOL_CM
        cbody = _body(_pt(0, 0, 0))
        child = _occ("Child:1", _pt(0, 0, 0), bodies=[cbody])
        wrapper = _occ("Wrapper:1", _pt(0, 0, 0), children=[child])
        p = self._wire(monkeypatch, [wrapper])

        def handler(**kw):
            wrapper.transform.translation = _pt(tol * 1.001, 0, 0)
            cbody.boundingBox.minPoint = _pt(tol * 1.001, 0, 0)
            return _ok({"created": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert out["child_geometry_move_verified"] is True
        assert out["repositioned_occurrences"] == ["Wrapper:1"]

    def test_samples_the_deepest_nested_body_not_the_direct_body(self, monkeypatch):
        # The wrapper's OWN direct body follows the move, but the deeper nested child body is frozen -
        # the guard must sample the DEEPEST body (the nested child) so it still bites (the exact
        # 'directly-owned bodies moved, nested child did not' shape).
        direct = _body(_pt(0, 0, 0))
        nested = _body(_pt(0, 0, 0))
        child = _occ("Child:1", _pt(0, 0, 0), bodies=[nested])
        wrapper = _occ("Wrapper:1", _pt(0, 0, 0), bodies=[direct], children=[child])
        p = self._wire(monkeypatch, [wrapper])

        def handler(**kw):
            wrapper.transform.translation = _pt(8.5, 8.5, 0)
            direct.boundingBox.minPoint = _pt(8.5, 8.5, 0)     # the direct body moved
            # nested stays frozen
            return _ok({"created": True})

        res = kernel.wrap(handler, [p])()
        assert res["isError"] is True
        assert "did not propagate" in res["message"].lower()

    def test_world_transform_is_read_off_transform2_not_transform(self, monkeypatch):
        # .transform is the occurrence's LOCAL matrix - a nested proxy under a rotated+translated
        # parent reads its parent's placement OUT of it - while .transform2 is the composed WORLD
        # matrix. This kind compares the translation against a WORLD geometry point, so reading the
        # local one reports "moved" against geometry that did not move (or the reverse). Here the
        # LOCAL matrix stays put across the handler while the WORLD one moves with the geometry:
        # off .transform the kind would see an expected-zero move and pass anything.
        cbody = _body(_pt(0, 0, 0))
        child = _occ("Child:1", _pt(0, 0, 0), bodies=[cbody])
        wrapper = _occ("Wrapper:1", _pt(0, 0, 0), children=[child])
        wrapper.transform2 = types.SimpleNamespace(translation=_pt(50, 0, 0))
        p = self._wire(monkeypatch, [wrapper])

        def handler(**kw):
            wrapper.transform2.translation = _pt(58.5, 8.5, 0)   # world moved
            # the LOCAL matrix never changes - the parent absorbed the placement
            return _ok({"created": True})

        res = kernel.wrap(handler, [p])()
        assert res["isError"] is True                  # the world move did NOT reach the geometry
        assert "did not propagate" in res["message"].lower()

    def test_missing_transform2_discloses_an_unverified_move_without_local_fallback(self, monkeypatch):
        cbody = _body(_pt(0, 0, 0))
        child = _occ("Child:1", _pt(0, 0, 0), bodies=[cbody])
        wrapper = _occ("Wrapper:1", _pt(0, 0, 0), children=[child])
        wrapper.transform2 = None
        p = self._wire(monkeypatch, [wrapper])

        def handler(**kw):
            wrapper.transform.translation = _pt(8.5, 8.5, 0)
            return _ok({"created": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert out["child_geometry_move_verified"] is False
        assert out["child_geometry_unverified"] == ["Wrapper:1"]

    @pytest.mark.parametrize('coordinate', [None, float('nan'), True])
    def test_unreadable_translation_coordinate_is_not_zeroed(self, monkeypatch, coordinate):
        wrapper = _occ('Wrapper:1', _pt(coordinate, 2.0, 3.0), bodies=[_body(_pt(0, 0, 0))])
        p = self._wire(monkeypatch, [wrapper])
        out = _payload(kernel.wrap(lambda **kw: _ok({'created': True}), [p])())
        assert out['child_geometry_move_verified'] is False
        assert out['child_geometry_unverified'] == ['Wrapper:1']

    def test_successful_native_local_translation_is_withheld(self, monkeypatch):
        native = make_occurrence('Leaf:1', transform2=FakeMatrix3D(t=(2.0, 3.0, 4.0)),
                                 bodies=[_body(_pt(1.0, 3.0, 4.0))])
        p = self._wire(monkeypatch, [native])
        out = _payload(kernel.wrap(lambda **kw: _ok({'created': True}), [p])())
        assert p._translation(native) is None
        assert out['child_geometry_move_verified'] is False
        assert out['child_geometry_unverified'] == ['Leaf:1']

    @pytest.mark.parametrize('geometry_follows', [True, False])
    def test_root_motion_is_judged_against_its_world_geometry(self, monkeypatch, geometry_follows):
        component = MakeComp(name='RootPart', entity_token='root-part')
        body = _body(_pt(0, 0, 0))
        native = make_occurrence('RootPart:1', component=component, bodies=[body],
                                 transform2=FakeMatrix3D())
        root = MakeComp(occurrences_by_component={'RootPart': [native]})
        monkeypatch.setattr(load_tool('_common'), 'design', lambda: MakeDesign(comp=root))
        condition = self._wire(monkeypatch, [native])

        def handler(**kw):
            native.transform2.translation = FakeVector3D(5, 0, 0)
            if geometry_follows:
                body.boundingBox.minPoint = _pt(5, 0, 0)
            return _ok({'created': True})

        result = kernel.wrap(handler, [condition])()
        assert result['isError'] is not geometry_follows
        if geometry_follows:
            out = _payload(result)
            assert out['child_geometry_move_verified'] is True
            assert out['repositioned_occurrences'] == ['RootPart:1']

    def test_an_unreadable_occurrence_walk_is_disclosed_not_silently_passed(self, monkeypatch):
        # no part was sampled before the mutation, so nothing was gated - the flag reports that the
        # CHECK did not run rather than leaving the payload looking verified
        p = kernel.ChildGeometryMoved()
        monkeypatch.setattr(p, "_top_occurrences", lambda: None)
        out = _payload(kernel.wrap(lambda **kw: _ok({"created": True}), [p])())
        assert out["child_geometry_move_verified"] is False

    def test_a_part_that_cannot_be_re_read_is_named_not_skipped(self, monkeypatch):
        # one part propagates cleanly, the other's geometry can no longer be sampled after the
        # mutation: reporting a clean verified pass would claim coverage the walk never had
        gbody = _body(_pt(0, 0, 0))
        good = _occ("Good:1", _pt(0, 0, 0), bodies=[gbody])
        gone = _occ("Gone:1", _pt(0, 0, 0), bodies=[_body(_pt(0, 0, 0))])
        p = self._wire(monkeypatch, [good, gone])

        def handler(**kw):
            good.transform.translation = _pt(5, 0, 0)
            gbody.boundingBox.minPoint = _pt(5, 0, 0)
            gone.bRepBodies = _coll([])          # its geometry is no longer reachable
            return _ok({"created": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert out["child_geometry_move_verified"] is False
        assert out["child_geometry_unverified"] == ["Gone:1"]

    def test_occurrence_without_bodies_is_skipped(self, monkeypatch):
        empty = _occ("Empty:1", _pt(0, 0, 0))   # no bodies anywhere - nothing to gate
        p = self._wire(monkeypatch, [empty])

        def handler(**kw):
            empty.transform.translation = _pt(8.5, 8.5, 0)
            return _ok({"created": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert "child_geometry_move_verified" not in out


# ── the design-wide census kinds: free edges, surface area, pattern placement ───────────────────
#
# Each reads the census through kernel.census_bodies, which a test replaces with ONE list the
# handler rewrites in place - the before/after pair the kind compares.

def _edge(face_count):
    """An edge bounding `face_count` faces - one on an open boundary, two once sealed."""
    return BRepEdge(curve=None, faces=[BRepFace(surface=None) for _ in range(face_count)])


def _sheet(name, free, sealed=0, area=1.0):
    return BRepBody(name=name, is_solid=False, area=area,
                    edges=[_edge(1) for _ in range(free)] + [_edge(2) for _ in range(sealed)])


def _owned_row(name, index, component):
    """A timeline row whose feature lives in `component` - what its address is qualified with."""
    feature = types.SimpleNamespace(parentComponent=types.SimpleNamespace(name=component))
    return FakeTimelineObject(name=name, index=index, entity=feature)


def _namesake_timeline(monkeypatch, name):
    """A parametric design whose timeline already holds `name` in another component, at index 0."""
    tl = FakeTimeline([_owned_row(name, 0, "Sibling")])
    common = sys.modules[kernel.__package__ + "._common"]
    _install_design(common, types.SimpleNamespace(designType=1, timeline=tl))
    return tl


class TestFreeEdgesChanged:
    def _wire(self, monkeypatch, census):
        monkeypatch.setattr(kernel, "census_bodies", lambda: census)

    def _handler(self, census, after):
        def handler(**kw):
            census[:] = after
            return _ok({"stitched": True})
        return handler

    def test_a_stitch_that_sealed_edges_confirms_with_both_counts(self, monkeypatch):
        census = [_sheet("A", free=4), _sheet("B", free=4)]
        self._wire(monkeypatch, census)
        out = _payload(kernel.wrap(self._handler(census, [_sheet("A", free=6, sealed=1)]),
                                   [kernel.FreeEdgesChanged("sealed")])())
        assert out["free_edges_before"] == 8 and out["free_edges_after"] == 6

    def test_a_stitch_that_sealed_nothing_bites(self, monkeypatch):
        census = [_sheet("A", free=4), _sheet("B", free=4)]
        self._wire(monkeypatch, census)
        res = kernel.wrap(self._handler(census, list(census)), [kernel.FreeEdgesChanged("sealed")])()
        assert res["isError"] is True
        assert "did not drop" in res["message"] and "8 before, 8 after" in res["message"]

    def test_a_stitch_whose_inputs_the_census_never_reached_is_disclosed_not_failed(self, monkeypatch):
        # A stitch takes open surfaces, so a census with no free edge at all did not hold them.
        census = [_sheet("Solid", free=0, sealed=12)]
        self._wire(monkeypatch, census)
        out = _payload(kernel.wrap(self._handler(census, list(census)),
                                   [kernel.FreeEdgesChanged("sealed")])())
        assert out["free_edges_confirmed"] is False
        assert "free_edges_after" not in out

    def test_an_unstitch_that_set_faces_loose_confirms(self, monkeypatch):
        census = [_sheet("Solid", free=0, sealed=12)]
        self._wire(monkeypatch, census)
        out = _payload(kernel.wrap(self._handler(census, [_sheet(f"F{i}", free=4) for i in range(6)]),
                                   [kernel.FreeEdgesChanged("opened")])())
        assert out["free_edges_before"] == 0 and out["free_edges_after"] == 24

    def test_an_unstitch_that_freed_no_edge_bites(self, monkeypatch):
        census = [_sheet("A", free=4)]
        self._wire(monkeypatch, census)
        res = kernel.wrap(self._handler(census, list(census)), [kernel.FreeEdgesChanged("opened")])()
        assert res["isError"] is True
        assert "did not rise" in res["message"]

    @pytest.mark.parametrize("design_type", [1, 0])
    def test_a_refused_stitch_names_its_feature_or_undo_in_direct_mode(self, monkeypatch,
                                                                         design_type):
        common = sys.modules[kernel.__package__ + "._common"]
        _install_design(common, types.SimpleNamespace(designType=design_type))
        census = [_sheet("A", free=4)]
        self._wire(monkeypatch, census)

        def handler(**kw):
            return _ok({"stitched": True, "feature": "Stitch1"})
        msg = kernel.wrap(handler, [kernel.FreeEdgesChanged("sealed")])()["message"]
        assert ("design_delete_feature(feature='Stitch1')" in msg) is (design_type == 1)
        assert ("DIRECT mode" in msg) is (design_type == 0)

    def test_a_refused_stitch_names_the_added_row_beside_a_namesake(self, monkeypatch):
        tl = _namesake_timeline(monkeypatch, "Stitch1")
        self._wire(monkeypatch, [_sheet("A", free=4)])

        def handler(**kw):
            tl._items.append(_owned_row("Stitch1", 1, "Shell"))
            return _ok({"stitched": True, "feature": "Stitch1"})
        msg = kernel.wrap(handler, [kernel.FreeEdgesChanged("sealed")])()["message"]
        assert msg.endswith("design_delete_feature(feature='Shell/Stitch1@1').")

    def test_two_added_namesake_rows_keep_the_bare_name(self, monkeypatch):
        tl = _namesake_timeline(monkeypatch, "Stitch1")
        self._wire(monkeypatch, [_sheet("A", free=4)])

        def handler(**kw):
            tl._items += [_owned_row("Stitch1", 1, "Shell"), _owned_row("Stitch1", 2, "Lid")]
            return _ok({"stitched": True, "feature": "Stitch1"})
        msg = kernel.wrap(handler, [kernel.FreeEdgesChanged("sealed")])()["message"]
        assert msg.endswith("design_delete_feature(feature='Stitch1').") and "@" not in msg

    def test_an_edge_whose_face_count_does_not_read_is_disclosed(self, monkeypatch):
        census = [BRepBody(name="A", is_solid=False, edges=[BRepEdge(curve=None)])]
        self._wire(monkeypatch, census)
        out = _payload(kernel.wrap(self._handler(census, list(census)),
                                   [kernel.FreeEdgesChanged("opened")])())
        assert out["free_edges_confirmed"] is False

    def test_a_census_over_the_edge_cap_is_not_taken(self, monkeypatch):
        monkeypatch.setattr(kernel, "_CENSUS_EDGE_CAP", 3)
        census = [_sheet("A", free=4)]
        self._wire(monkeypatch, census)
        out = _payload(kernel.wrap(self._handler(census, [_sheet("A", free=6)]),
                                   [kernel.FreeEdgesChanged("opened")])())
        assert out["free_edges_confirmed"] is False

    def test_a_direction_outside_the_two_is_refused_at_construction(self):
        with pytest.raises(ValueError, match="sideways"):
            kernel.FreeEdgesChanged("sideways")


class TestSurfaceAreaAdded:
    def _wire(self, monkeypatch, census):
        monkeypatch.setattr(kernel, "census_bodies", lambda: census)

    def _handler(self, census, after):
        def handler(**kw):
            census[:] = after
            return _ok({"created": True})
        return handler

    def test_a_created_sheet_confirms_with_the_area_it_added(self, monkeypatch):
        census = [_sheet("Old", free=4, area=3.0)]
        self._wire(monkeypatch, census)
        out = _payload(kernel.wrap(self._handler(census, census + [_sheet("New", free=4, area=2.5)]),
                                   [kernel.SurfaceAreaAdded()])())
        assert out["area_added_cm2"] == 2.5

    def test_an_unchanged_total_area_bites_naming_it(self, monkeypatch):
        census = [_sheet("Old", free=4, area=3.0)]
        self._wire(monkeypatch, census)
        res = kernel.wrap(self._handler(census, list(census)), [kernel.SurfaceAreaAdded()])()
        assert res["isError"] is True
        assert "changed by 0 cm2" in res["message"]

    def test_small_positive_area_is_disclosed_without_claiming_no_geometry(self, monkeypatch):
        census = [_sheet("Old", free=4, area=3.0)]
        self._wire(monkeypatch, census)
        res = kernel.wrap(self._handler(census, census + [_sheet("Tiny", free=4, area=5e-7)]),
                          [kernel.SurfaceAreaAdded()])()
        body = json.loads(res["content"][0]["text"])
        assert res["isError"] is True and "unchanged" not in res["message"]
        assert "increase above 1e-06 cm2" in res["message"]
        assert body["verification_evidence"]["area_change_cm2"] == pytest.approx(5e-7)
        assert body["verification_evidence"]["area_increase_threshold_cm2"] == 1e-6
        assert body["handler_reported_unverified_result"]["created"] is True

    def test_a_refused_sheet_names_its_feature_bodies_and_delete_call(self, monkeypatch):
        census = [_sheet("Old", free=4, area=3.0)]
        self._wire(monkeypatch, census)

        def handler(**kw):
            census.append(_sheet("Body2", free=4, area=5e-7))
            return _ok({"created": True, "feature": "Extrude2", "result_bodies": ["Body2"]})
        res = kernel.wrap(handler, [kernel.SurfaceAreaAdded()])()
        assert res["message"].endswith(
            " Its result bodies: 'Body2'. 'Extrude2' remains in the timeline; remove it with "
            "design_delete_feature(feature='Extrude2').")

    def test_a_refused_sheet_beside_a_namesake_names_its_own_address(self, monkeypatch):
        # A bare name another component's feature shares is refused by design_delete_feature.
        tl = _namesake_timeline(monkeypatch, "Extrude2")
        census = [_sheet("Old", free=4, area=3.0)]
        self._wire(monkeypatch, census)

        def handler(**kw):
            census.append(_sheet("Body2", free=4, area=5e-7))
            tl._items.append(_owned_row("Extrude2", 1, "H1Surf"))
            return _ok({"created": True, "feature": "Extrude2", "result_bodies": ["Body2"]})
        res = kernel.wrap(handler, [kernel.SurfaceAreaAdded()])()
        assert res["message"].endswith(
            " Its result bodies: 'Body2'. 'H1Surf/Extrude2@1' remains in the timeline; remove it "
            "with design_delete_feature(feature='H1Surf/Extrude2@1').")

    def test_no_growth_beside_an_unread_area_is_disclosed_not_failed(self, monkeypatch):
        # the sheet may be the body whose area did not read - no conviction from a blind census
        census = [BRepBody(name="Blind", is_solid=False)]
        self._wire(monkeypatch, census)
        out = _payload(kernel.wrap(self._handler(census, list(census)), [kernel.SurfaceAreaAdded()])())
        assert out["surface_area_confirmed"] is False

    def test_growth_beside_an_unread_area_still_confirms(self, monkeypatch):
        census = [BRepBody(name="Blind", is_solid=False)]
        self._wire(monkeypatch, census)
        out = _payload(kernel.wrap(self._handler(census, census + [_sheet("New", free=4, area=2.0)]),
                                   [kernel.SurfaceAreaAdded()])())
        assert out["area_added_cm2"] == 2.0

    def test_an_unreadable_census_is_disclosed(self, monkeypatch):
        monkeypatch.setattr(kernel, "census_bodies", lambda: None)
        out = _payload(kernel.wrap(lambda **kw: _ok({"created": True}), [kernel.SurfaceAreaAdded()])())
        assert out["surface_area_confirmed"] is False


def _placed(x, y=0.0, z=0.0, rotation=None):
    """A pattern element at a translation, optionally under a rotation block (a 3x3 row-major)."""
    r = rotation or (1, 0, 0, 0, 1, 0, 0, 0, 1)
    arr = (r[0], r[1], r[2], x, r[3], r[4], r[5], y, r[6], r[7], r[8], z, 0, 0, 0, 1)
    return types.SimpleNamespace(transform=types.SimpleNamespace(asArray=lambda arr=arr: arr,
                                                                  translation=_pt(x, y, z)))


_GRID = (("quantity_one", "spacing_one", 2, 10.0), ("quantity_two", "spacing_two", 1, 10.0))


class _OccurrenceVector:
    """An element's occurrences as the live vector answers them: iterable, with no count."""

    def __init__(self, occurrences):
        self._occurrences = list(occurrences)

    def __iter__(self):
        return iter(self._occurrences)


class _OccurrenceElement:
    """A pattern element carrying occurrences; `touched` records every read of its transform,
    which answers the zero translation a circular element reads."""

    def __init__(self, occurrences, touched):
        self.occurrences = _OccurrenceVector(occurrences)
        self._touched = touched

    @property
    def transform(self):
        self._touched.append(self)
        return _placed(0).transform


def _posed(x=0.0, y=0.0, deg=0.0):
    """One patterned occurrence at (x, y) cm, turned `deg` about Z."""
    return make_occurrence(path="Seed:1", transform2=FakeMatrix3D(deg=deg, t=(x, y, 0.0)))


def _celled(**cells):
    """One occurrence whose transform2 is the identity with the given row-major cells replaced."""
    arr = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    for cell, value in cells.items():
        arr[int(cell[1:])] = value
    return types.SimpleNamespace(transform2=types.SimpleNamespace(asArray=lambda: arr))


class TestPatternElementsPlaced:
    def test_face_feature_pattern_does_not_certify_placement_from_one_result_body(self, monkeypatch):
        post = kernel.PatternElementsPlaced()
        monkeypatch.setattr(post, "_feature", lambda *_args: pytest.fail("generic placement read used"))
        for kind in ("faces", "features"):
            reason, evidence = post.verify({}, {"entity_kind": kind, "pattern_geometry_changed": True}, 0)
            assert reason == "" and evidence == {"pattern_elements_confirmed": False}

    def _wire(self, monkeypatch, tl, **kw):
        p = kernel.PatternElementsPlaced(**kw)
        monkeypatch.setattr(p, "_timeline", lambda: tl)
        return p

    def _handler(self, tl, elements, name="Pattern1", feature_name="Pattern1"):
        def handler(quantity_one=2, spacing_one=10.0, quantity_two=1, spacing_two=10.0, units="mm"):
            feature = types.SimpleNamespace(patternElements=_coll(elements))
            tl._items.append(FakeTimelineObject(name=name, entity=feature))
            return _ok({"patterned": True, "feature": feature_name})
        return handler

    def test_distinct_instances_one_spacing_apart_confirm_with_the_count(self, monkeypatch):
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl, spacings=_GRID)
        out = _payload(kernel.wrap(self._handler(tl, [_placed(0), _placed(2), _placed(4)]), [p])(
            quantity_one=3, spacing_one=20, units="mm"))
        assert out["elements_placed"] == 3

    def test_stacked_copies_bite_naming_the_pair(self, monkeypatch):
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl, spacings=_GRID)
        res = kernel.wrap(self._handler(tl, [_placed(0), _placed(2), _placed(2)]), [p])(
            quantity_one=3, spacing_one=20, units="mm")
        assert res["isError"] is True
        assert "STACKED" in res["message"] and "copies 1 and 2" in res["message"]

    def test_a_first_instance_off_the_requested_spacing_bites(self, monkeypatch):
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl, spacings=_GRID)
        res = kernel.wrap(self._handler(tl, [_placed(0), _placed(1.5)]), [p])(
            quantity_one=2, spacing_one=20, units="mm")
        assert res["isError"] is True
        assert "'spacing_one'" in res["message"]
        assert "15.0 mm" in res["message"] and "20.0 mm" in res["message"]

    def test_the_second_direction_is_read_one_row_along(self, monkeypatch):
        # Elements lay out direction one innermost (measured), so the second direction's first
        # instance is the element quantity_one along, not element 1.
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl, spacings=_GRID)
        good = [_placed(0, 0), _placed(2, 0), _placed(0, 3), _placed(2, 3)]
        out = _payload(kernel.wrap(self._handler(tl, good), [p])(
            quantity_one=2, spacing_one=20, quantity_two=2, spacing_two=30, units="mm"))
        assert out["elements_placed"] == 4
        tl2 = FakeTimeline()
        p2 = self._wire(monkeypatch, tl2, spacings=_GRID)
        bad = [_placed(0, 0), _placed(2, 0), _placed(0, 2.5), _placed(2, 2.5)]
        res = kernel.wrap(self._handler(tl2, bad), [p2])(
            quantity_one=2, spacing_one=20, quantity_two=2, spacing_two=30, units="mm")
        assert res["isError"] is True and "'spacing_two'" in res["message"]

    def test_omitted_inputs_are_judged_at_the_handlers_defaults(self, monkeypatch):
        # quantity_one defaults to 2 and spacing_one to 10 mm, so a bare call still gates spacing.
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl, spacings=_GRID)
        res = kernel.wrap(self._handler(tl, [_placed(0), _placed(2)]), [p])()
        assert res["isError"] is True and "10.0 mm" in res["message"]

    def test_the_feature_named_by_the_payload_is_the_one_read(self, monkeypatch):
        tl = FakeTimeline([FakeTimelineObject(name="Pattern1", entity=types.SimpleNamespace(
            patternElements=_coll([_placed(0), _placed(0)])))])      # an OLD stacked pattern
        p = self._wire(monkeypatch, tl, spacings=_GRID)
        out = _payload(kernel.wrap(self._handler(tl, [_placed(0), _placed(1)], name="Pattern2",
                                                 feature_name="Pattern2"), [p])())
        assert out["elements_placed"] == 2

    def test_a_feature_not_found_on_the_timeline_is_disclosed(self, monkeypatch):
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl, spacings=_GRID)
        out = _payload(kernel.wrap(self._handler(tl, [_placed(0)], feature_name="Ghost"), [p])())
        assert out["pattern_elements_confirmed"] is False

    def test_an_element_transform_that_does_not_read_is_disclosed(self, monkeypatch):
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl, spacings=_GRID)
        blind = types.SimpleNamespace(transform=None)
        out = _payload(kernel.wrap(self._handler(tl, [_placed(0), blind]), [p])())
        assert out["pattern_elements_confirmed"] is False

    # Without spacings the read is the result bodies' boxes: a circular element's transform is not
    # its placement (measured: a 4 x 360 deg ring reads 0/180/270/0 deg while its bodies sit at
    # 0/90/180/270, the seed LAST in feature.bodies), so the transforms cannot be the evidence.
    def _boxed_handler(self, tl, corners, transforms=()):
        def handler(**kw):
            feature = types.SimpleNamespace(
                patternElements=_coll(list(transforms)),
                bodies=_coll([BRepBody(name=f"B{i}", bbox=types.SimpleNamespace(
                    minPoint=_pt(*c), maxPoint=_pt(c[0] + 1, c[1] + 1, c[2] + 1)))
                    for i, c in enumerate(corners)]))
            tl._items.append(FakeTimelineObject(name="Ring1", entity=feature))
            return _ok({"patterned": True, "feature": "Ring1"})
        return handler

    def test_a_ring_is_judged_by_its_bodies_boxes_not_its_element_transforms(self, monkeypatch):
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl)
        # the transforms read as the measured ring would - the seed's twice - yet the boxes differ
        out = _payload(kernel.wrap(self._boxed_handler(
            tl, [(3, 0, 0), (-3, 0, 0)], transforms=[_placed(0), _placed(0)]), [p])())
        assert out["elements_placed"] == 2

    def test_coincident_boxes_are_a_soft_verdict_when_declared_soft(self, monkeypatch):
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl, severity="soft")
        out = _payload(kernel.wrap(self._boxed_handler(tl, [(0, 0, 0), (0, 0, 0)]), [p])())
        assert out["verified"]["pattern_elements_placed"]["confirmed"] is False
        assert "copies 0 and 1" in out["verified"]["pattern_elements_placed"]["reason"]

    def test_a_pattern_owning_no_body_is_disclosed_not_judged(self, monkeypatch):
        tl = FakeTimeline()
        p = self._wire(monkeypatch, tl)
        out = _payload(kernel.wrap(self._boxed_handler(tl, []), [p])())
        assert out["pattern_elements_confirmed"] is False

    def _occurrence_ring(self, monkeypatch, elements, quantity=None, bodies=(), **payload):
        """The wrapped reply of a soft bodiless pattern whose elements hold `elements` (a list of
        occurrence lists), plus the list recording element.transform reads."""
        tl, touched = FakeTimeline(), []
        p = self._wire(monkeypatch, tl, severity="soft")

        def handler(**kw):
            feature = types.SimpleNamespace(
                patternElements=_coll([_OccurrenceElement(occs, touched) for occs in elements]),
                bodies=_coll(list(bodies)))
            tl._items.append(FakeTimelineObject(name="Ring1", entity=feature))
            return _ok({"patterned": True, "feature": "Ring1", "quantity": quantity, **payload})
        return _payload(kernel.wrap(handler, [p])()), touched

    def test_an_occurrence_ring_of_distinct_placements_confirms_the_count(self, monkeypatch):
        ring = [[_posed(4.2, 0)], [_posed(-12.5, -23)], [_posed(-39.6, -14.2)],
                [_posed(-39.6, 14.2)], [_posed(-12.5, 23)]]
        out, touched = self._occurrence_ring(monkeypatch, ring, quantity=5)
        assert out["elements_placed"] == 5 and "pattern_elements_confirmed" not in out
        assert touched == []                    # the element transform is never the read

    def test_an_occurrence_ring_with_two_copies_at_one_pose_is_not_confirmed(self, monkeypatch):
        ring = [[_posed(4, 0)], [_posed(0, 4)], [_posed(-4, 0)], [_posed(0, 4)]]
        out, _touched = self._occurrence_ring(monkeypatch, ring, quantity=4)
        assert out["pattern_elements_confirmed"] is False
        assert "elements_placed" not in out and "verified" not in out

    def test_an_on_axis_ring_is_told_apart_by_orientation(self, monkeypatch):
        ring = [[_posed(deg=d)] for d in (0, 90, 180, 270)]
        out, _touched = self._occurrence_ring(monkeypatch, ring, quantity=4)
        assert out["elements_placed"] == 4

    @pytest.mark.parametrize("blind", [
        [],                                                              # an element holding none
        [make_occurrence(path="Seed:1", raises_on={"transform2": "3 : no transform"})],
        [types.SimpleNamespace(transform2=types.SimpleNamespace(asArray=lambda: [0.0] * 12))],
        [_celled(c3=float("nan"))],
    ])
    def test_a_placement_that_does_not_read_is_unknown(self, monkeypatch, blind):
        out, _touched = self._occurrence_ring(monkeypatch, [[_posed(4, 0)], blind], quantity=2)
        assert out["pattern_elements_confirmed"] is False and "elements_placed" not in out

    def test_an_element_holding_no_occurrence_is_unknown_not_one_placement(self, monkeypatch):
        out, _touched = self._occurrence_ring(monkeypatch, [[]])
        assert out["pattern_elements_confirmed"] is False and "elements_placed" not in out

    def test_fewer_elements_than_the_reported_quantity_is_not_confirmed(self, monkeypatch):
        ring = [[_posed(4, 0)], [_posed(0, 4)], [_posed(-4, 0)]]
        out, _touched = self._occurrence_ring(monkeypatch, ring, quantity=4)
        assert out["pattern_elements_confirmed"] is False and "elements_placed" not in out

    def test_a_reply_with_no_quantity_confirms_the_elements_read(self, monkeypatch):
        # the path pattern's reply carries quantity null when its own count read fails
        out, _touched = self._occurrence_ring(monkeypatch, [[_posed(0, 0)], [_posed(3, 0)]])
        assert out["elements_placed"] == 2

    def test_position_and_orientation_tolerances_include_their_boundary(self, monkeypatch):
        tol, turn = kernel._PLACE_TOL_CM, kernel._TURN_TOL
        for pair, placed in (([_celled(), _celled(c3=tol)], None),
                             ([_celled(), _celled(c3=2 * tol)], 2),
                             ([_celled(), _celled(c1=turn)], None),
                             ([_celled(), _celled(c1=2 * turn)], 2)):
            out, _touched = self._occurrence_ring(monkeypatch, [[o] for o in pair], quantity=2)
            assert out.get("elements_placed") == placed, pair

    def test_elements_of_several_seeds_differ_when_any_seed_does(self, monkeypatch):
        ring = [[_posed(0, 0), _posed(5, 0)], [_posed(0, 0), _posed(5, 0, deg=90)]]
        out, _touched = self._occurrence_ring(monkeypatch, ring, quantity=2)
        assert out["elements_placed"] == 2
        uneven = [[_posed(0, 0), _posed(5, 0)], [_posed(9, 0)]]
        out, _touched = self._occurrence_ring(monkeypatch, uneven, quantity=2)
        assert out["pattern_elements_confirmed"] is False

    def test_a_body_ring_whose_box_does_not_read_is_never_judged_by_occurrences(self, monkeypatch):
        blind_body = BRepBody(name="B0", bbox=types.SimpleNamespace(minPoint=None, maxPoint=None))
        out, _touched = self._occurrence_ring(
            monkeypatch, [[_posed(4, 0)], [_posed(0, 4)]], quantity=2, bodies=[blind_body])
        assert out["pattern_elements_confirmed"] is False and "elements_placed" not in out

    def test_spacing_keys_the_handler_lacks_are_refused_at_wiring(self):
        p = kernel.PatternElementsPlaced(spacings=_GRID)

        def handler(quantity=2):
            return _ok({})

        with pytest.raises(ValueError, match="spacing_one"):
            kernel.wrap(handler, [p])


class TestFileLanded:
    def test_missing_file_bites(self, tmp_path):
        ghost = str(tmp_path / "ghost.pdf")
        res = kernel.wrap(lambda **kw: _ok({"file_path": ghost}), [kernel.FileLanded()])()
        assert res["isError"] is True
        assert "file_exists=False" in res["message"]

    def test_empty_file_bites(self, tmp_path):
        p = tmp_path / "empty.pdf"
        p.write_text("")
        res = kernel.wrap(lambda **kw: _ok({"file_path": str(p)}), [kernel.FileLanded()])()
        assert res["isError"] is True
        assert "file_exists=True" in res["message"] and "size_bytes=0" in res["message"]

    def test_real_file_confirms_and_supplies_size(self, tmp_path):
        p = tmp_path / "real.pdf"
        p.write_text("PDF-STUB")
        out = _payload(kernel.wrap(lambda **kw: _ok({"file_path": str(p)}), [kernel.FileLanded()])())
        assert out["file_exists"] is True and out["size_bytes"] > 0

    def test_missing_path_key_is_named(self, tmp_path):
        res = kernel.wrap(lambda **kw: _ok({"other": 1}), [kernel.FileLanded("file_path")])()
        assert res["isError"] is True
        assert "file_path" in res["message"]


class _PoisonHealthyItem(FakeTimelineObject):
    """A HEALTHY item whose errorOrWarningMessage getter RAISES - measured on a fresh
    AssemblyConstraint (and a caught adsk error has rollback risk in some contexts), which is
    why the walk reads the message only inside the unhealthy branches."""
    def __init__(self, name):
        FakeTimelineObject.__init__(self, name=name, health=_HEALTHY)

    @property
    def errorOrWarningMessage(self):
        raise RuntimeError("InternalValidationError on a healthy item")

    @errorOrWarningMessage.setter
    def errorOrWarningMessage(self, value):
        pass


class TestCheckInputKeys:
    """Registration-time wiring gate: a postcondition keyed to a handler parameter that does not
    exist would read None from kwargs, fall back to the kind's default target, verify the WRONG
    state, and still report success - so wrap() raises at import time instead."""

    class _KeyedPost(kernel.Postcondition):
        name = "keyed"
        input_keys = ("sketch_name",)

        def capture(self, kwargs):
            return None

        def verify(self, kwargs, captured, payload):
            return None

    def test_a_key_the_handler_lacks_raises_at_wrap_time(self):
        def handler(body_name="", distance=0.0):
            return _ok({})
        with pytest.raises(ValueError) as exc:
            kernel.wrap(handler, [self._KeyedPost()])
        msg = str(exc.value)
        assert "sketch_name" in msg and "handler" in msg
        assert "verify the wrong state" in msg

    def test_a_key_the_handler_takes_passes(self):
        def handler(sketch_name="", distance=0.0):
            return _ok({})
        assert callable(kernel.wrap(handler, [self._KeyedPost()]))

    def test_an_unintrospectable_handler_is_not_refused(self):
        # A C-level/builtin callable has no signature to check against - the gate stays quiet
        # rather than blocking registration on a check it cannot run.
        assert callable(kernel.wrap(min, [self._KeyedPost()]))

    def test_a_post_with_no_input_keys_never_trips_the_gate(self):
        def handler(body_name=""):
            return _ok({})
        assert callable(kernel.wrap(handler, [Fixed()]))


class TestPoisonGetterOnHealthyItems:
    def test_healthy_walk_never_reads_the_message_getter(self, monkeypatch):
        tl = FakeTimeline([_PoisonHealthyItem("Constraint1")])
        p = kernel.FeatureHealthy()
        monkeypatch.setattr(p, "_timeline", lambda: tl)

        def handler(**kw):
            tl._items.append(_PoisonHealthyItem("Constraint2"))
            return _ok({"done": True})

        out = _payload(kernel.wrap(handler, [p])())
        assert out["features_verified"] == 1        # a raise here would have failed the wrap

    def test_unhealthy_item_still_gets_its_message_read(self, monkeypatch):
        tl = FakeTimeline()
        p = kernel.FeatureHealthy()
        monkeypatch.setattr(p, "_timeline", lambda: tl)

        def handler(**kw):
            tl._items.append(_tl_item("Broken1", 2, "No target body"))
            return _ok({"done": True})

        res = kernel.wrap(handler, [p])()
        assert res["isError"] is True and "No target body" in res["message"]
