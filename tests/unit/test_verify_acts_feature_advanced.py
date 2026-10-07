"""Unit checks for the measured advanced-feature live witness predicates."""

import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TESTS_DIR, "live"))
import verify_acts_feature_advanced as witness  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_advanced_state(monkeypatch):
    monkeypatch.setattr(witness, "_ADVANCED_STATE", {})


def _prime_feature_state():
    witness.advanced_feature_edit_rows()
    state = witness._ADVANCED_STATE
    definitions = {
        "adv_pipe": ("PS_R22", "PipeFeature", 4, {"path": {"references": [
            {"handle": "R22_Sk/line:0"}]}}),
        "adv_scale": ("PS_R10", "ScaleFeature", 2, {
            "is_uniform": True, "scale_expressions": ["1.5", "1.5", "1.5"],
            "input_entities": []}),
        "adv_emboss": ("PS_R23", "EmbossFeature", 12, {"profiles": [
            {"profile_handle": "profile-circle"}], "depth": "0.50 mm"}),
        "adv_pattern": ("PS_R21", "PathPatternFeature", 19, {
            "path": {"references": [{"handle": "R21_Path/line:0"}]},
            "orientation": True, "pattern_elements": 3, "quantity": "10.00 mm",
            "input_entities": []}),
        "adv_shell": ("PS_R08", "ShellFeature", 8, {"input_faces": [
            {"handle": "shell-face"}], "inside_thickness": "1.00 mm",
            "outside_thickness": None, "is_tangent_chain": False}),
    }
    for key, (feature, kind, index, fields) in definitions.items():
        state[key] = {"feature": feature, "type": kind, "timeline_index": index,
                      "unavailable": {}, **fields}
        state[key + "_address"] = f"RootComponent/{feature}@{index}"
    state["fixture_timeline_count"] = 24
    state["fixture_feature_indices"] = {
        "PS_R22": 4, "PS_R10": 2, "PS_R23": 12, "PS_R21": 19, "PS_R08": 8}
    return state


def test_model_edit_rows_keep_each_feature_address_bound():
    rows = witness.advanced_feature_edit_rows()
    state = _prime_feature_state()
    state["adv_shell_side"] = "shell-side-handle"
    context = {"advanced_doc": "doc-handle", "adv_shell_side": "shell-side-handle"}
    edits = [args(context) for name, args, _expect, _save in rows if name == "model_edit_feature"]
    assert [row["feature"] for row in edits] == [
        state["adv_pipe_address"], state["adv_pipe_address"],
        state["adv_scale_address"], state["adv_scale_address"],
        state["adv_emboss_address"], state["adv_emboss_address"],
        state["adv_pattern_address"], state["adv_pattern_address"],
        state["adv_pattern_address"], state["adv_pattern_address"],
        state["adv_shell_address"], state["adv_shell_address"],
    ]


def test_feature_edit_reply_requires_measured_health_and_end_marker():
    state = _prime_feature_state()
    address = state["adv_scale_address"]
    payload = {"edited": True, "same_feature": True, "definition_matches": True,
               "geometry_changed": False, "marker_restored": True,
               "marker_before": 24, "marker_after": 24,
               "feature_health": {"errors": [], "warnings": []},
               "new_timeline_errors": [], "new_timeline_warnings": [],
               "definition_before": {"feature_address": address, "unavailable": {}},
               "definition_after": {"feature_address": address, "unavailable": {}}}
    check = witness._feature_edit_reply("PS_R10", "mode", changed=False)
    assert check(payload) is True
    payload["feature_health"] = "healthy"
    with pytest.raises(AssertionError):
        check(payload)


def test_roll_check_requires_exact_position_and_count():
    state = _prime_feature_state()
    state["adv_pipe"]["timeline_index"] = 4
    check = witness._roll_check("before", "PS_R22", "adv_pipe")
    result = {"rolled": True, "to": "before", "feature": "PS_R22",
              "marker_position": 4, "timeline_count": 24, "rolled_back": 20}
    assert check(result) is True
    result["marker_position"] = 5
    with pytest.raises(AssertionError):
        check(result)


def test_first_roll_uses_fixture_index_before_any_definition_read():
    rows = witness.advanced_feature_edit_rows()
    result = {"fixture": "advanced-feature-edit",
              "features": ["PS_R22", "PS_R10", "PS_R23", "PS_R21", "PS_R08"],
              "feature_indices": {"PS_R22": 4, "PS_R10": 2, "PS_R23": 12,
                                  "PS_R21": 19, "PS_R08": 8},
              "timeline_count": 24, "marker": 24, "healthy": True, "control_body": "R10"}
    assert witness._fixture_result(result) is True
    assert "adv_pipe" not in witness._ADVANCED_STATE
    check = next(expect for name, _args, expect, _save in rows
                 if name == "design_edit_timeline")
    roll = {"rolled": True, "to": "before", "feature": "PS_R22",
            "marker_position": 4, "timeline_count": 24, "rolled_back": 20}
    assert check(roll) is True
    roll["marker_position"] = 3
    with pytest.raises(AssertionError):
        check(roll)
    definition = {"definition": {"feature": "PS_R22", "type": "PipeFeature",
                                 "timeline_index": 4, "component": "RootComponent",
                                 "feature_address": "RootComponent/PS_R22@4", "unavailable": {}}}
    assert witness._feature_state("PS_R22", "PipeFeature", "adv_pipe", [])(definition) is True
    definition["definition"]["timeline_index"] = 5
    with pytest.raises(AssertionError):
        witness._feature_state("PS_R22", "PipeFeature", "adv_pipe", [])(definition)


def test_typed_path_and_shell_face_use_measured_public_shapes():
    assert witness._path_is({"references": [{"handle": "R22_Sk/line:1"}]},
                            "R22_Sk/line:1")
    assert not witness._path_is({"references": [{"handle": "sketch:R22_Sk/line:1"}]},
                                "R22_Sk/line:1")
    _prime_feature_state()
    face = witness._one_face("shell", [0, 215, 10], [-1, 0, 0])
    payload = {"match_count": 6, "returned": 1, "matches": [{"kind": "planar_face",
               "position": [0, 215, 10], "normal": [-1, 0, 0], "handle": "face-handle"}]}
    assert face(payload) is True
    payload["matches"][0]["normal"] = [0, 0, 1]
    with pytest.raises(AssertionError):
        face(payload)


def test_fixture_defines_the_required_script_entrypoint():
    import ast
    tree = ast.parse(witness._ADVANCED_FEATURE_FIXTURE)
    entry = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
    assert entry.name == "run" and [a.arg for a in entry.args.args] == ["context"]


def test_orientation_retains_the_measured_replaced_path_shape():
    from copy import deepcopy
    payload = {"kind": "design", "min_point": {"x": 0, "y": 0, "z": 0},
               "max_point": {"x": 10, "y": 10, "z": 10},
               "mass": {"volume": 1, "area": 6, "center_of_mass": [5, 5, 5],
                        "per_body_count": 1, "per_body_truncated": False,
                        "per_body": [{"body": "R10", "occurrence": None, "is_solid": True,
                                      "volume": 1, "lump_count": 1}]}}
    assert witness._material_snapshot("pattern", "before")(payload)
    moved = deepcopy(payload)
    moved["max_point"]["x"] = 20
    assert witness._material_snapshot("pattern", "path_changed")(moved)
    assert witness._material_snapshot("pattern", "same_as_path_changed")(moved)
    moved["max_point"]["y"] = 12
    with pytest.raises(AssertionError):
        witness._material_snapshot("pattern", "same_as_path_changed")(moved)


def test_material_snapshot_uses_actual_per_body_schema():
    witness.advanced_feature_edit_rows()
    payload = {"kind": "design", "min_point": {"x": 0, "y": 0, "z": 0},
               "max_point": {"x": 10, "y": 10, "z": 10},
               "mass": {"volume": 1, "area": 6,
                        "center_of_mass": [5, 5, 5],
                        "per_body_count": 1, "per_body_truncated": False,
                        "per_body": [{"body": "R10", "occurrence": None, "is_solid": True,
                                      "volume": 1, "lump_count": 1}]}}
    assert witness._material_snapshot("adv_scale", "before")(payload) is True
    del payload["mass"]["center_of_mass"]
    with pytest.raises(AssertionError):
        witness._material_snapshot("adv_scale", "before")(payload)
    payload["mass"]["center_of_mass"] = [5, 5, 5]
    payload["mass"]["volume"] = float("nan")
    with pytest.raises(AssertionError):
        witness._material_snapshot("adv_scale", "before")(payload)


def test_control_snapshot_requires_the_named_body_bounds_and_pose():
    witness.advanced_feature_edit_rows()
    payload = {"kind": "body", "target": "body 'R10'", "units": "mm", "lump_count": 1,
               "min_point": {"x": 0, "y": 0, "z": 0},
               "max_point": {"x": 10, "y": 10, "z": 10},
               "mass": {"volume": 1, "area": 6,
                        "center_of_mass": [5, 5, 5]}}
    assert witness._control_snapshot("before")(payload) is True
    payload["min_point"]["x"] = 1
    with pytest.raises(AssertionError):
        witness._control_snapshot("changed")(payload)


def test_path_pattern_distance_accepts_complete_untruncated_timeline_shape():
    witness.advanced_feature_edit_rows()
    payload = {"timeline": {"count": 1, "returned": 1, "marker_position": 1,
                            "summary": {"states": {"healthy": 1},
                            "exceptions": []}, "timeline": [{"name": "PS_R21", "params": [
                                {"role": "PathPatternDelta", "expression": "10.00 mm"}]}]}}
    assert witness._path_pattern_distance("before")(payload) is True
    payload["timeline"]["truncated"] = True
    with pytest.raises(AssertionError):
        witness._path_pattern_distance("same")(payload)
    del payload["timeline"]["truncated"]
    del payload["timeline"]["summary"]
    with pytest.raises(AssertionError):
        witness._path_pattern_distance("same")(payload)
    payload["timeline"]["summary"] = {"states": {"healthy": 1}, "exceptions": []}
    payload["timeline"]["marker_position"] = 0
    with pytest.raises(AssertionError):
        witness._path_pattern_distance("same")(payload)
