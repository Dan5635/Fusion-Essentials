# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The additive helper: part assignment, orientation candidates, placement and typed results."""

import math
from types import SimpleNamespace

import pytest

from conftest import load_tool

ca = load_tool("_cam_additive")

ROOT = "CAM Component:1+(Unsaved):1"
IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
# A quarter turn about X, as a candidate reads it (rotation cells at a tenth) and as a pose reads it.
TURNED_CANDIDATE = [0.1, 0.0, 0.0, 0.0, 0.0, 0.0, -0.1, 2.25, 0.0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
TURNED_POSE = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 2.25, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _matrix(cells):
    return SimpleNamespace(asArray=lambda: list(cells))


def _occurrence(path, pose=IDENTITY):
    return SimpleNamespace(kind="occurrence", fullPathName=path, transform2=_matrix(pose),
                           boundingBox=SimpleNamespace(
                               minPoint=SimpleNamespace(asArray=lambda: [0.0, 0.0, 0.0]),
                               maxPoint=SimpleNamespace(asArray=lambda: [3.0, 2.0, 1.0])))


def _candidate(cells, **values):
    return SimpleNamespace(transformation=_matrix(cells), supportVolume=values.get("support", 1.0),
                           supportArea=2.0, boundingBoxVolume=3.0, partHeight=4.0,
                           centerOfGravityHeight=5.0, rankingValue=6.0)


def _operation(targets=None, data=(), sticky=True):
    """An additive operation: `targets` maps a parameter name to the entities it holds."""
    held = {name: list(entities) for name, entities in (targets or {}).items()}

    def parameter(name):
        if name not in held:
            return None

        class _Value:
            """The assignable list behind one parts parameter; no shared fake models it."""
            @property
            def value(self):
                return list(held[name])

            @value.setter
            def value(self, entities):
                if sticky:
                    held[name] = list(entities)
        return SimpleNamespace(name=name, value=_Value())
    items = list(data)
    return SimpleNamespace(
        name="Op1", strategy="automatic_orientation", parameters=SimpleNamespace(itemByName=parameter),
        generatedDataCollection=SimpleNamespace(count=len(items), item=lambda i: items[i]),
        hasError=False, error="", hasWarning=False, warning="", held=held)


def _results(candidates, current=None):
    state = {"current": current if current is not None else _candidate([-1.0] * 16)}

    class _Set:
        """An orientation result set whose current candidate is assignable; no shared fake models it."""
        kind = "orientation"
        count = len(candidates)

        def item(self, i):
            return candidates[i]

        @property
        def currentOrientationResult(self):
            return state["current"]

        @currentOrientationResult.setter
        def currentOrientationResult(self, chosen):
            if not getattr(self, "ignores", False):
                state["current"] = chosen
    return _Set()


@pytest.fixture
def cam(monkeypatch):
    by_kind = lambda kind: SimpleNamespace(cast=lambda x: x if getattr(x, "kind", None) == kind else None)
    monkeypatch.setattr(ca.adsk.cam, "OptimizedOrientationResults", by_kind("orientation"), raising=False)
    monkeypatch.setattr(ca.adsk.cam, "AdditiveInterferenceAnalysisResult", by_kind("interference"),
                        raising=False)
    monkeypatch.setattr(ca.adsk.fusion, "Occurrence", by_kind("occurrence"), raising=False)
    monkeypatch.setattr(ca.adsk.fusion, "BRepBody", by_kind("body"), raising=False)
    side = [_occurrence(ROOT + "+PartA:1"), _occurrence(ROOT + "+PartB:1")]
    return SimpleNamespace(designRootOccurrence=SimpleNamespace(fullPathName=ROOT, childOccurrences=side),
                           side=side)


class TestAssignParts:
    def test_the_parts_asked_read_back_by_their_design_paths(self, cam):
        op = _operation({"supportTarget": []})
        # Fusion hands the design occurrence back as its Manufacture-side twin
        op.parameters.itemByName("supportTarget")
        landed, reason = ca.assign_parts(cam, op, [_occurrence("PartA:1")])
        assert reason is None and landed == {"parameter": "supportTarget", "parts_before": [],
                                             "parts": ["PartA:1"]}

    def test_a_manufacture_side_read_back_names_the_same_design_part(self, cam):
        op = _operation({"supportTarget": [cam.side[0]]})
        assert ca.target_parts(cam, op.parameters.itemByName("supportTarget")) == ["PartA:1"]

    def test_an_assignment_that_does_not_hold_is_an_error(self, cam):
        op = _operation({"supportTarget": [cam.side[1]]}, sticky=False)
        landed, reason = ca.assign_parts(cam, op, [_occurrence("PartA:1")])
        assert landed is None and "does not read the parts asked for" in reason
        assert "['PartB:1']" in reason

    @pytest.mark.parametrize("targets", [{}, {"supportTarget": [], "interferenceAnalysisTargets": []}])
    def test_an_operation_with_no_or_two_part_selections_is_refused(self, cam, targets):
        landed, reason = ca.assign_parts(cam, _operation(targets), [_occurrence("PartA:1")])
        assert landed is None and "part selections" in reason


class TestOrientation:
    def _rig(self, cam, pose=TURNED_POSE, parts=1, **kw):
        cam.side[0].transform2 = _matrix(pose)
        results = _results([_candidate(IDENTITY), _candidate(TURNED_CANDIDATE)], **kw)
        op = _operation({"optimizeOrientationTarget": cam.side[:parts]}, data=[results])
        return op, results

    def test_no_candidate_is_current_until_one_was_chosen(self, cam):
        op, _results_ = self._rig(cam)
        rows, reason = ca.orientation_rows(op)
        assert reason is None and rows["count"] == 2 and rows["current_index"] is None
        assert rows["candidates"][1]["index"] == 1 and rows["candidates"][1]["support_volume"] == 1.0

    def test_a_chosen_candidate_reads_current_and_the_part_is_turned_to_it(self, cam):
        op, results = self._rig(cam)
        chosen, reason = ca.choose_orientation(cam, op, 1)
        assert reason is None and chosen["index"] == 1 and chosen["part"] == "PartA:1"
        assert chosen["pose"] == TURNED_POSE
        assert ca.orientation_rows(op)[0]["current_index"] == 1

    def test_a_candidate_that_does_not_become_current_is_an_error(self, cam):
        op, results = self._rig(cam)
        results.ignores = True
        chosen, reason = ca.choose_orientation(cam, op, 1)
        assert chosen is None and "does not read as the current orientation" in reason

    def test_a_part_that_is_not_turned_to_the_candidate_is_an_error(self, cam):
        op, _results_ = self._rig(cam, pose=IDENTITY)
        chosen, reason = ca.choose_orientation(cam, op, 1)
        assert chosen is None and "does not read turned to it" in reason

    @pytest.mark.parametrize("index", [2, -1, True, "1"])
    def test_an_index_outside_the_candidates_is_refused_before_any_write(self, cam, index):
        op, results = self._rig(cam)
        chosen, reason = ca.choose_orientation(cam, op, index)
        assert chosen is None and "an index from 0 to 1" in reason
        assert ca.orientation_rows(op)[0]["current_index"] is None

    def test_an_operation_with_two_parts_is_refused(self, cam):
        op, _results_ = self._rig(cam, parts=2)
        chosen, reason = ca.choose_orientation(cam, op, 1)
        assert chosen is None and "exactly one part" in reason

    def test_an_operation_without_results_names_the_generation_to_run(self, cam):
        op = _operation({"optimizeOrientationTarget": [cam.side[0]]}, data=[SimpleNamespace(kind="other")])
        chosen, reason = ca.choose_orientation(cam, op, 0)
        assert chosen is None and "cam_generate" in reason

    @pytest.mark.parametrize("count", [0, None])
    def test_empty_or_unread_candidates_never_offer_a_negative_index_range(self, cam, count):
        results = _results([])
        results.count = count
        before = results.currentOrientationResult
        op = _operation({"optimizeOrientationTarget": [cam.side[0]]}, data=[results])
        chosen, reason = ca.choose_orientation(cam, op, 0)
        assert chosen is None and "from 0 to -1" not in reason
        assert results.currentOrientationResult is before
        assert ("cam_generate" in reason) if count == 0 else ("did not read" in reason)
        if count is None:
            assert "If not generated" in reason and "cam_generate" in reason

    @pytest.mark.parametrize("path", ["Sub:1+PartA:1", "PartA:1"])
    def test_an_unresolved_or_ambiguous_pose_refuses_before_changing_candidate(self, cam, path):
        op, results = self._rig(cam)
        op.held["optimizeOrientationTarget"] = [_occurrence(ROOT + "+" + path)]
        if path == "PartA:1":
            cam.side.append(_occurrence(ROOT + "+PartA:1"))
        chosen, reason = ca.choose_orientation(cam, op, 1)
        assert chosen is None and "no candidate was changed" in reason
        assert ca.orientation_rows(op)[0]["current_index"] is None


class TestReads:
    def test_unread_counts_stay_unknown_instead_of_publishing_empty_collections(self, cam):
        setup = SimpleNamespace(machine=SimpleNamespace(vendor="V", model="M", elements=None))
        printer = ca.printer_row(setup, 10)
        assert printer["element_count"] is None and printer["extruders"] is None
        op = _operation()
        op.generatedDataCollection = None
        assert ca.additive_results(cam, op)["generated_result_count"] is None

    @pytest.mark.parametrize("target, items, noted", [
        ("supportTarget", 0, True), ("supportTargetModel", 0, True), ("supportTarget", 1, False),
        ("supportTarget", None, False), ("optimizeOrientationTarget", 0, False)])
    def test_only_a_zero_count_on_a_support_operation_says_it_is_not_an_absence(self, cam, target,
                                                                                 items, noted):
        op = _operation({target: [cam.side[0]]}, data=[SimpleNamespace(kind="other")] * (items or 0))
        if items is None:
            op.generatedDataCollection = None
        out = ca.additive_results(cam, op)
        assert out["generated_result_count"] == items and out["parts"] == ["PartA:1"]
        assert out.get("note") == (ca.SUPPORT_COUNT_NOTE if noted else None)
        assert "does not say whether support was generated" in ca.SUPPORT_COUNT_NOTE

    def test_parameter_table_reports_total_count_before_truncation(self):
        table = SimpleNamespace(count=41, item=lambda i: SimpleNamespace(name=str(i), expression="1"))
        rows, count = ca._table(table, 40)
        assert len(rows) == 40 and count == 41
        assert ca._table(None, 40) == (None, None)

    def test_interference_is_told_by_class_and_names_design_parts(self, cam):
        clash = SimpleNamespace(kind="interference", interferingOccurrences=[cam.side[1], cam.side[0]])
        op = _operation({"interferenceAnalysisTargets": cam.side}, data=[SimpleNamespace(kind="other"), clash])
        out = ca.additive_results(cam, op)
        assert out["interfering_parts"] == ["PartA:1", "PartB:1"] and out["parts"] == ["PartA:1", "PartB:1"]
        assert "orientation" not in out

    def test_placement_scales_the_translation_and_the_box_and_leaves_the_rotation(self, cam):
        cam.side[0].transform2 = _matrix(TURNED_POSE)
        setup = SimpleNamespace(name="Print", models=[_occurrence("PartA:1"), _occurrence("Gone:1")])
        rows, reason = ca.placement_rows(cam, setup, 10.0)
        assert reason is None and rows[0]["pose"][3:8] == [0.0, 0.0, 0.0, -1.0, 22.5]
        assert rows[0]["max_point"] == [30.0, 20.0, 10.0] and rows[0]["read"] is True
        assert rows[1] == {"part": "Gone:1", "pose": None, "min_point": None, "max_point": None,
                           "read": False}

    def test_a_compatibility_answer_that_does_not_read_is_not_a_yes(self):
        def raises(machine):
            raise RuntimeError("no answer")
        assert ca.setting_fits(SimpleNamespace(isCompatibleWithMachine=raises), object()) is None
        assert ca.setting_fits(SimpleNamespace(isCompatibleWithMachine=lambda m: False), object()) is False
        assert math.isclose(ca.MATRIX_TOL, 1e-6)
