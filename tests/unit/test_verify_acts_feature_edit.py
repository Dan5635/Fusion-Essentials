# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Focused false-green checks for the public feature-edit live stories."""

import os
import sys
from copy import deepcopy

import pytest

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TESTS_DIR, "live"))
import verify_acts_feature_edit as witness  # noqa: E402


def test_native_face_witness_retains_exact_token_owner_and_frame():
    candidate = {"kind": "planar_face", "handle": "native-token|@face:1;occ=Bench:1",
                 "occurrence": "Bench:1", "position": [15, 20, 5], "normal": [0, 1, 0]}
    value = {"kind": "face", "name": "BRepFace", "handle": "native-token|@face:1",
             "owner": {"component": "Bench", "occurrence": None},
             "geometry": {"frame": "entity_context", "point_cm": [1.5, 2, 0.5],
                          "normal": [0, 1, 0]}}
    check = lambda v, c: witness._operand_matches_candidate(v, c, "Bench", "Bench:1", True)
    assert check(value, candidate)
    assert not witness._operand_matches_candidate(value, candidate, "Bench", "Bench:1")
    for path, replacement in (("owner.component", "Other"),
                              ("geometry.point_cm", [2, 2, 0.5]),
                              ("geometry.normal", [1, 0, 0])):
        wrong = deepcopy(value)
        target = wrong
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = replacement
        assert not check(wrong, candidate)
    assert not check(dict(value, handle=""), candidate)
    assert not witness._operand_matches_candidate(
        dict(value, handle="proxy-token|@face:1"), candidate, "Bench", "Bench:1")
    assert not check(value, dict(candidate, occurrence="Other:1"))


def test_draft_proxy_and_definition_tokens_need_separate_native_identity_proof():
    candidate = {"kind": "planar_face", "handle": "proxy-token|@face:1;occ=Bench:1",
                 "occurrence": "Bench:1", "position": [15, 20, 5], "normal": [0, 1, 0]}
    value = {"kind": "face", "name": "BRepFace", "handle": "native-token|@face:1",
             "owner": {"component": "Bench", "occurrence": None},
             "geometry": {"frame": "entity_context", "point_cm": [1.5, 2, 0.5],
                          "normal": [0, 1, 0]}}
    assert witness._operand_matches_candidate(value, candidate, "Bench", "Bench:1", True)
    assert witness._draft_face_identity_check({"left_count": 1, "right_count": 1,
        "native_equal": True, "body_equal": True, "owner_equal": True,
        "valid": [True, True]})
    for bad in (
        {"left_count": 2, "right_count": 1, "native_equal": True, "body_equal": True,
         "owner_equal": True, "valid": [True, True]},
        {"left_count": 1, "right_count": 1, "native_equal": False, "body_equal": True,
         "owner_equal": True, "valid": [True, True]},
        {"left_count": 1, "right_count": 1, "native_equal": True, "body_equal": True,
         "owner_equal": False, "valid": [True, True]},
        {"left_count": 1, "right_count": 1, "native_equal": True, "body_equal": True,
         "owner_equal": True, "valid": [True, False]},
    ):
        with pytest.raises(AssertionError, match="same valid native face"):
            witness._draft_face_identity_check(bad)


def test_combine_body_candidate_requires_its_exact_placement_and_measured_geometry():
    candidate = {"kind": "body", "name": "Body3", "component_path": "Bench:1",
                 "center": [25, 10, 10], "volume": 2000}
    value = {"kind": "body", "name": "Body3",
             "owner": {"component": "Bench", "occurrence": "Bench:1"},
             "geometry": {"frame": "entity_context", "center_cm": [2.5, 1, 1], "volume": 2}}
    check = lambda v: witness._operand_matches_candidate(v, candidate, "Bench", "Bench:1")
    assert check(value)
    for path in (None, "Bench:2", "Other:1"):
        assert not check(dict(value, owner={"component": "Bench", "occurrence": path}))
    assert not check(dict(value, name="Body2"))
    assert not check(dict(value, geometry=dict(value["geometry"], center_cm=[1, 1, 1])))


def test_draft_identity_row_uses_saved_public_definition_and_valid_script():
    ctx = {"candidate": "proxy-token|@face:1;occ=Bench:1",
           "after": {"input_faces": [{"handle": "native-token|@face:1"}]}}
    args = witness._draft_face_identity_args(ctx, "candidate", "after")
    assert args["read_only"] is True
    compile(args["script"], "draft_identity_probe.py", "exec")
    assert "findEntityByToken('proxy-token')" in args["script"]
    assert "findEntityByToken('native-token')" in args["script"]
    rows = []
    witness._transition(rows, "DraftFeature", "feature", "inputs", "input_faces",
                        candidate_key="candidate", draft_native_identity=True)
    probe = next(i for i, row in enumerate(rows) if row[0] == "sys_execute_script")
    assert rows[probe - 1][0] == "design_get"
    assert rows[probe + 1][0] == "design_edit_timeline"
    assert rows[probe - 1][3][0] == "DraftFeature_after_definition"


@pytest.fixture(autouse=True)
def isolate_recall(monkeypatch):
    monkeypatch.setattr(witness, "_RECALL", {})


def _mirror_def(plane, **extra):
    return {"feature": "Mirror1", "component": "FeatureEditBench", "type": "MirrorFeature",
            "timeline_index": 4, "feature_address": "FeatureEditBench/Mirror1",
            "mirror_plane": plane, "input_entities": [{"handle": "source", "kind": "body"}],
            **extra}


def _plane(name="FEMirrorX5", x=5, occurrence="FeatureEditBench:1", handle="token|@construction_plane"):
    return {"kind": "construction_plane", "name": name, "handle": handle,
            "position": [x, 0, 0], "normal": [1, 0, 0], "occurrence": occurrence}


def _plane_ref(candidate=None, x=5, name="FEMirrorX5", occurrence="FeatureEditBench:1"):
    candidate = candidate or _plane()
    return {"kind": "construction_plane", "name": name, "handle": candidate["handle"],
            "owner": {"component": "FeatureEditBench", "occurrence": occurrence},
            "geometry": {"frame": "world", "origin_cm": [x / 10, 0, 0],
                         "normal": [1, 0, 0]}}


def _definition_payload(definition):
    return {"definition": {**definition, "unavailable": {}}}


def _component_payload(volume, center, bounds, bodies=None):
    minimum, maximum = bounds
    return {"units": "mm", "min_point": dict(zip("xyz", minimum)),
            "max_point": dict(zip("xyz", maximum)),
            "mass": {"accuracy_used": "very_high", "volume": volume,
                     "center_of_mass": center, "per_body_truncated": False,
                     "per_body_count": len(bodies or [("Body1", True, 1, volume)]),
                     "per_body": bodies or [{"body": "Body1", "is_solid": True,
                                             "lump_count": 1, "volume": volume}]}}


def test_reference_edit_rejects_wrong_named_or_wrong_frame_operand():
    candidate = _plane()
    key = "MirrorFeature_plane_before"
    witness._RECALL[key] = _mirror_def({"kind": "construction_plane", "name": "yz"})
    witness._RECALL["MirrorFeature_component"] = "FeatureEditBench:1"
    witness._RECALL["MirrorFeature_component_name"] = "FeatureEditBench"
    witness._RECALL["MirrorFeature_candidate_descriptor"] = candidate
    check = witness._definition_after(key, "mirror_plane", candidate_key="MirrorFeature_candidate")

    check(_definition_payload(_mirror_def(_plane_ref(candidate))))
    with pytest.raises(AssertionError, match="public definition changed only"):
        check(_definition_payload(_mirror_def(_plane_ref(candidate, name="OtherPlane"))))
    with pytest.raises(AssertionError, match="public definition changed only"):
        check(_definition_payload(_mirror_def(_plane_ref(candidate, x=7))))
    with pytest.raises(AssertionError, match="public definition changed only"):
        check(_definition_payload(_mirror_def(_plane_ref(candidate, occurrence="Other:1"))))


def test_restoration_checks_refuse_missing_or_empty_baselines():
    with pytest.raises(AssertionError, match="banked nonempty baseline"):
        witness._definition_restored("Missing", "axis")({"definition": {"unavailable": {}}})
    with pytest.raises(AssertionError, match="independent geometry restored"):
        witness._shape_restored("Missing", "story")(_component_payload(
            100, [0, 0, 0], ([0, 0, 0], [1, 1, 1])))
    with pytest.raises(AssertionError, match="independent control unchanged"):
        witness._control_same("Missing", "restore")({"kind": "body", "units": "mm"})


def test_component_center_is_required_and_wrong_changed_geometry_fails_expected_value():
    baseline = _component_payload(12000, [27.083333, 9.583333, 6.666667],
                                  ([0, 0, 0], [110, 20, 20]))
    after = _component_payload(12000, [24, 9.583333, 6.666667],
                               ([0, 0, 0], [110, 20, 20]))
    witness._RECALL["CombineFeature_tools_shape"] = witness._shape_state(baseline)
    expected = {"volume": 12000, "center": [25.833333, 9.583333, 6.666667],
                "bounds": [0, 0, 0, 110, 20, 20]}
    with pytest.raises(AssertionError, match="new native premise"):
        witness._shape_changed("CombineFeature_tools_shape", "Combine changed", expected)(after)
    after["mass"]["center_of_mass"] = expected["center"]
    witness._shape_changed("CombineFeature_tools_shape", "Combine changed", expected)(after)
    after["mass"].pop("center_of_mass")
    assert witness._shape_state(after) is None


def test_body_candidate_requires_exact_name_unique_owner_and_measured_geometry():
    witness._RECALL.update({"CombineFeature_tool2": "Body4",
                            "CombineFeature_component": "FeatureEditBench:1",
                            "CombineFeature_component_name": "FeatureEditBench",
                            "CombineFeature_tools_shape": {"bodies": [
                                ("Body4", True, 1, 2000), ("Body1", True, 1, 7000)]}})
    payload = {"kind": "body", "target": "body 'Body4'", "units": "mm",
               "min_point": {"x": 20, "y": 5, "z": 0},
               "max_point": {"x": 30, "y": 15, "z": 20},
               "mass": {"accuracy_used": "very_high", "volume": 2000,
                        "center_of_mass": [25, 10, 10]}}
    witness._body_candidate_capture("CombineFeature_tool2", "CombineFeature_component",
                                    "CombineFeature_tools_shape")(payload)
    assert witness._RECALL["CombineFeature_tool2_descriptor"] == {
        "kind": "body", "name": "Body4", "component_path": "FeatureEditBench:1",
        "volume": 2000, "center": [25, 10, 10]}
    witness._RECALL["CombineFeature_tools_shape"]["bodies"].append(("Body4", True, 1, 2000))
    with pytest.raises(AssertionError, match="one exact owner"):
        witness._body_candidate_capture("CombineFeature_tool2", "CombineFeature_component",
                                        "CombineFeature_tools_shape")(payload)


def test_thread_mode_alias_must_follow_is_modeled():
    key = "ThreadFeature_mode_before"
    witness._RECALL[key] = {"feature": "Thread1", "component": "FeatureEditBench",
        "type": "ThreadFeature", "timeline_index": 5, "feature_address": "Thread1",
        "is_modeled": False, "modeled": False, "designation": "M8x1.25"}
    wrong = dict(witness._RECALL[key], is_modeled=True, modeled=False)
    with pytest.raises(AssertionError, match="public definition changed only"):
        witness._definition_after(key, "is_modeled", True)(_definition_payload(wrong))
    right = dict(witness._RECALL[key], is_modeled=True, modeled=True)
    witness._definition_after(key, "is_modeled", True)(_definition_payload(right))


def test_feature_rows_cover_combine_tool_retarget_and_intersect_with_restores():
    rows = witness.feature_edit_rows()
    calls = []
    context = {"CombineFeature_feature": "Combine1", "CombineFeature_tool2": "Body4",
               "CombineFeature_tool": "Body2", "CombineFeature_target": "Body1",
               "CombineFeature_candidate": "candidate"}
    combine_start = next(i for i, row in enumerate(rows) if row[0] == "model_combine")
    for tool, args, _check, _save in rows[combine_start:]:
        if tool != "model_edit_feature":
            continue
        payload = args(context) if callable(args) else args
        calls.append(payload)
    assert any(row.get("action") == "tools" and row.get("references") == ["Body4"]
               for row in calls)
    assert any(row.get("action") == "mode" and row.get("mode") == "intersect"
               for row in calls)
    assert len(calls) == 4
