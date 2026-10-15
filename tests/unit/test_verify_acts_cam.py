# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The parse the unlocked-row verdict stands on, and the operation-address verdict beside it."""

import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TESTS_DIR, "live"))
import verify_acts_cam  # noqa: E402
import verify_acts_mesh  # noqa: E402


@pytest.fixture
def remesh_history_control(monkeypatch):
    """Install complete prior history and the legal remesh's published BaseFeature name."""
    prior_row = {"index": 0, "name": "Seed", "type": "ExtrudeFeature"}
    before = {"tree": {"child_count": 0}, "timeline": {
        "count": 1, "returned": 1, "marker_position": 1, "timeline": [prior_row],
        "summary": {"states": {"healthy": 1}, "exceptions": []}}}
    monkeypatch.setitem(verify_acts_mesh._RECALL, "density_control_design", before)
    monkeypatch.setitem(verify_acts_mesh._RECALL, "density_control_result", {"base_feature": "RemeshBase"})
    return {"tree": {"child_count": 0}, "timeline": {
        "count": 2, "returned": 2, "marker_position": 2,
        "timeline": [prior_row, {"index": 1, "name": "RemeshBase", "type": "BaseFeature"}],
        "summary": {"states": {"healthy": 2}, "exceptions": []}}}


class TestRemeshControlHistory:
    @pytest.mark.parametrize("prior_health", ["suppressed", "warning"])
    def test_new_healthy_feature_preserves_qualified_prior_history(self, remesh_history_control, prior_health):
        prior = verify_acts_mesh._RECALL["density_control_design"]["timeline"]
        prior["timeline"][0]["health"] = prior_health
        prior["summary"]["states"] = {prior_health: 1}
        after = remesh_history_control["timeline"]
        after["summary"]["states"] = {prior_health: 1, "healthy": 1}
        if prior_health == "warning":
            exception = {"name": "Seed", "index": 0, "health": "warning"}
            prior["summary"]["exceptions"] = [exception]
            after["summary"]["exceptions"] = [exception]
        assert verify_acts_mesh._remesh_control_history(remesh_history_control) is True

    @pytest.mark.parametrize("health", ["warning", "error", None])
    def test_correct_name_and_prefix_do_not_admit_unhealthy_new_feature(
            self, remesh_history_control, health):
        assert verify_acts_mesh._remesh_control_history(remesh_history_control) is True
        remesh_history_control["timeline"]["timeline"][-1]["health"] = health
        with pytest.raises(AssertionError, match="legal-remesh BaseFeature"):
            verify_acts_mesh._remesh_control_history(remesh_history_control)


class TestOrganicSourceReadback:
    def test_sweep_requires_an_independent_closed_mesh_read_after_refusal(self):
        assert verify_acts_mesh._organic_source_retained({
            "truncated": False,
            "meshes": [{"name": "MA", "is_closed": True, "triangle_count": 12}],
        }) is True
        with pytest.raises(AssertionError, match="organic source mesh remains readable"):
            verify_acts_mesh._organic_source_retained({"truncated": False, "meshes": []})


@pytest.fixture
def selector_tool_read():
    """Return a complete cutter and exact-query parameter payload for the selector oracle."""
    return {"tool": {"operation": "Face1", "dimensions": {"diameter": 12, "units": "mm"}},
            "parameters": {"operation": "Face1", "requested_parameter_count": 3,
                "requested_parameters": [{"name": name, "expression": value} for name, value in
                    (("tool_diameter", "12."), ("tool_feedCutting", "1000."), ("tool_spindleSpeed", "5000rpm"))]}}


class TestSelectorSnapshotCompleteness:
    @pytest.mark.parametrize("diameter", [None, 0, -1, True, "12", float("nan"), float("inf")])
    def test_unread_or_invalid_cutter_cannot_form_a_preservation_snapshot(self, selector_tool_read, diameter):
        assert verify_acts_cam._selector_tool_state(selector_tool_read) is not None
        selector_tool_read["tool"]["dimensions"]["diameter"] = diameter
        assert verify_acts_cam._selector_tool_state(selector_tool_read) is None

    def test_cutter_units_must_be_disclosed_as_millimeters(self, selector_tool_read):
        selector_tool_read["tool"]["dimensions"]["units"] = "cm"
        assert verify_acts_cam._selector_tool_state(selector_tool_read) is None

    @pytest.mark.parametrize("truncated", [True, None, "missing"])
    def test_only_explicit_complete_operation_census_forms_a_snapshot(self, truncated):
        rec = {"setup": verify_acts_cam.CAM_SETUP, "operations": [{"name": "Face1"}],
               "operations_truncated": False}
        payload = {"operations": {"setups": [rec]}}
        assert verify_acts_cam._selector_operations_state(payload) == rec
        if truncated == "missing":
            del rec["operations_truncated"]
        else:
            rec["operations_truncated"] = truncated
        assert verify_acts_cam._selector_operations_state(payload) is None




@pytest.fixture
def mixed_remesh_component():
    """Return the measured complete Msh occurrence with three solid BReps and one open surface."""
    return {'target': "occurrence 'Msh:1'",
     'frame': 'world axes (axis-aligned)',
     'box_read': 'boundingBox+preciseBoundingBox',
     'oriented': False,
     'units': 'mm',
     'x': 75.0,
     'y': 75.0,
     'z': 20.0,
     'min_point': {'x': 654.0, 'y': 1465.0, 'z': 0.0},
     'max_point': {'x': 729.0, 'y': 1540.0, 'z': 20.0},
     'center': {'x': 691.5, 'y': 1502.5, 'z': 10.0},
     'kind': 'occurrence',
     'mass': {'target': "occurrence 'Msh:1'",
              'units': 'mm',
              'accuracy': 'very_high',
              'mass_kg': 0.76942,
              'volume': 98015.279671,
              'area': 29203.040977,
              'density_kg_per_cm3': 0.00785,
              'center_of_mass': [699.716876, 1510.716644, 8.571689],
              'inertia_world': {'about': 'world coordinate origin',
                                'units': 'kg*unit^2',
                                'Ixx': 1790689.739619,
                                'Iyy': 384145.469598,
                                'Izz': 2174672.051807,
                                'Ixy': -829102.787166,
                                'Iyz': -10182.88761,
                                'Ixz': -4735.128373},
              'principal_moments': {'about': 'center of mass (principal axes)',
                                    'units': 'kg*unit^2',
                                    'i1': 41827.816282,
                                    'i2': 159.078005,
                                    'i3': 41945.502901},
              'principal_axes': {'x': [0.897776, -0.411941, 0.155896],
                                 'y': [0.416175, 0.909265, 0.005972],
                                 'z': [-0.144211, 0.059518, 0.987755]},
              'radius_of_gyration': {'kx': 233.158298, 'ky': 14.378823, 'kz': 233.486074},
              'rotation_to_principal_rad': {'rx': 0.060573, 'ry': 0.142034, 'rz': 0.438374},
              'accuracy_used': 'very_high',
              'per_occurrence': [],
              'per_occurrence_count': 0,
              'per_occurrence_truncated': False,
              'per_body': [{'body': 'Body1',
                            'occurrence': None,
                            'is_solid': True,
                            'mass_kg': 0.0314,
                            'volume': 4000.0,
                            'lump_count': 1},
                           {'body': 'Body2',
                            'occurrence': None,
                            'is_solid': True,
                            'mass_kg': 0.110977,
                            'volume': 14137.166941,
                            'lump_count': 1},
                           {'body': 'Body3',
                            'occurrence': None,
                            'is_solid': True,
                            'mass_kg': 0.0314,
                            'volume': 4000.0,
                            'lump_count': 1},
                           {'body': 'Body4',
                            'occurrence': None,
                            'is_solid': False,
                            'mass_kg': 0.0,
                            'volume': 0.0,
                            'lump_count': 1}],
              'per_body_count': 4,
              'per_body_truncated': False}}


class TestRemeshMixedBrepPreservation:
    def test_legal_control_checks_measured_geometry_and_untouched_mesh(self, monkeypatch):
        import copy
        witness = {"handle": "witness", "name": "MC", "triangle_count": 12, "node_count": 24,
                   "area": 1600.0, "volume": 4000.0}
        target = {"handle": "target", "name": "MDensityZero", "triangle_count": 80, "node_count": 84,
                  "area": 3270.651551, "volume": 13927.186755}
        before = {"count": 2, "truncated": False, "units": "mm", "meshes": [witness, target]}
        after = copy.deepcopy(before)
        after["meshes"][1].update(triangle_count=6, node_count=8, area=1422.629396, volume=2785.620098)
        result = {"after": {"triangle_count": 6, "area_cm2": 14.226294, "volume_cm3": 2.78562}}
        monkeypatch.setitem(verify_acts_mesh._RECALL, "density_control_meshes",
                            verify_acts_mesh._remesh_census_state(before))
        monkeypatch.setitem(verify_acts_mesh._RECALL, "density_control_result", result)
        check = verify_acts_mesh._remesh_control_effect("MDensityZero")
        assert check(after) is True
        after["meshes"][1]["area"] += 2
        with pytest.raises(AssertionError, match="other meshes stayed exact"):
            check(after)
        after = copy.deepcopy(before)
        after["meshes"][1].update(triangle_count=6, node_count=8, area=1422.629396, volume=2785.620098)
        after["meshes"][0]["volume"] += 1
        with pytest.raises(AssertionError, match="other meshes stayed exact"):
            check(after)

    def test_source_mass_witnesses_inspect_body_owners_instead_of_fixture_faces(self):
        rows = verify_acts_mesh._remesh_density_rows()
        sources = [args for tool, args, _, _ in rows if tool == "model_inspect"
                   and isinstance(args, dict) and args.get("accuracy") == "very_high"
                   and args.get("target") != "Msh:1"]
        assert len(sources) == 10
        assert [args["target"] for args in sources] == ["Msh:1:Body2", "Msh:1:Body1"] * 5
        assert all(args["include"] == ["default", "mass"] and args["units"] == "mm" for args in sources)

    def test_open_surface_zero_scalars_are_retained_with_all_four_rows_and_aggregate(self, mixed_remesh_component):
        state = verify_acts_mesh._remesh_component_state(mixed_remesh_component)
        assert state is not None
        assert state["bounds"]["min_point"] == {"x": 654.0, "y": 1465.0, "z": 0.0}
        assert state["material"] == mixed_remesh_component["mass"]
        assert state["material"]["per_body_count"] == 4
        assert state["material"]["per_body"][-1] == {"body": "Body4", "occurrence": None,
            "is_solid": False, "mass_kg": 0.0, "volume": 0.0, "lump_count": 1}

    @pytest.mark.parametrize("path,value", [
        (("min_point", "z"), None), (("mass", "area"), None), (("mass", "area"), float("nan")),
        (("mass", "center_of_mass"), [1, 2]), (("mass", "per_body_count"), 3),
        (("mass", "per_body_truncated"), None), (("mass", "per_occurrence_truncated"), True),
        (("mass", "per_body", 3, "is_solid"), None), (("mass", "per_body", 3, "is_solid"), 0),
        (("mass", "per_body", 3, "mass_kg"), None), (("mass", "per_body", 3, "volume"), None),
        (("mass", "per_body", 3, "lump_count"), None), (("mass", "principal_axes", "x"), None)])
    def test_unread_mixed_body_or_component_measurement_cannot_form_a_snapshot(
            self, mixed_remesh_component, path, value):
        assert verify_acts_mesh._remesh_component_state(mixed_remesh_component) is not None
        target = mixed_remesh_component
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        assert verify_acts_mesh._remesh_component_state(mixed_remesh_component) is None

    def test_missing_surface_field_is_not_zero_and_missing_row_is_not_a_complete_census(self, mixed_remesh_component):
        del mixed_remesh_component["mass"]["per_body"][-1]["volume"]
        assert verify_acts_mesh._remesh_component_state(mixed_remesh_component) is None
        mixed_remesh_component["mass"]["per_body"].pop()
        assert verify_acts_mesh._remesh_component_state(mixed_remesh_component) is None

    def test_full_snapshot_equality_detects_changed_surface_row_and_aggregate(self, mixed_remesh_component, monkeypatch):
        extract = verify_acts_mesh._remesh_component_state
        import copy
        monkeypatch.setitem(verify_acts_mesh._RECALL, "mixed_remesh", copy.deepcopy(extract(mixed_remesh_component)))
        check = verify_acts_mesh._retire_compare("mixed_remesh", extract, True)
        assert check(mixed_remesh_component) is True
        mixed_remesh_component["mass"]["per_body"][-1]["volume"] = 1
        with pytest.raises(AssertionError, match="mixed_remesh"):
            check(mixed_remesh_component)
        mixed_remesh_component["mass"]["per_body"][-1]["volume"] = 0
        mixed_remesh_component["mass"]["area"] += 1
        with pytest.raises(AssertionError, match="mixed_remesh"):
            check(mixed_remesh_component)

class TestLeadingNumber:
    def test_a_read_back_states_its_unit_and_a_wordy_one_carries_no_number(self):
        assert verify_acts_cam._leading_number("0.5mm") == 0.5
        assert verify_acts_cam._leading_number("3") == 3.0
        assert verify_acts_cam._leading_number("-2.5deg") == -2.5
        assert verify_acts_cam._leading_number(".5mm") == 0.5
        assert verify_acts_cam._leading_number("true") is None
        assert verify_acts_cam._leading_number(None) is None


class TestReadsBack:
    def test_a_number_survives_its_unit_and_a_word_is_compared_as_text(self):
        assert verify_acts_cam._reads_back("0.5mm", "0.5mm") is True
        assert verify_acts_cam._reads_back("0.5mm", 0.5) is True
        assert verify_acts_cam._reads_back("10.5mm", "0.5mm") is False
        assert verify_acts_cam._reads_back("3", 3) is True
        assert verify_acts_cam._reads_back("true", "true") is True
        assert verify_acts_cam._reads_back("false", "true") is False


class TestParamValue:
    def test_a_length_read_back_states_its_unit_and_a_wrong_number_still_fails(self):
        landed = verify_acts_cam._param_value("stockToLeave", 0.5)
        assert landed({"edited": True,
                       "changed": [{"name": "stockToLeave", "after": "0.5 mm"}]}) is True
        with pytest.raises(AssertionError):
            landed({"edited": True,
                    "changed": [{"name": "stockToLeave", "after": "10.5 mm"}]})


def _ops_payload(*rows):
    """cam_get(include=['operations']) shaped down to what the address verdict reads."""
    return {"operations": {"setups": [{"setup": "CamJob", "operations": list(rows)}]}}


class TestPathsAddressEveryOperation:
    """Either half alone admits the ambiguity the verdict exists to refuse, so both are pinned."""

    VERDICT = staticmethod(verify_acts_cam._paths_address_every_operation("CamJob"))

    def test_a_foldered_row_and_a_root_row_each_carry_their_own_full_path(self):
        assert self.VERDICT(_ops_payload(
            {"name": "Face1", "path": "CamJob / Face1"},
            {"name": "Drill1", "folder": "Drilling", "path": "CamJob / Drilling / Drill1"})) is True

    def test_two_rows_sharing_a_name_fail_even_with_every_path_well_formed(self):
        # the ordinal '<name>#<n>' address this verdict refuses: both paths are correct for their
        # own row, and the pair is still unaddressable.
        with pytest.raises(AssertionError, match="duplicate_names"):
            self.VERDICT(_ops_payload(
                {"name": "Face1", "path": "CamJob / Face1"},
                {"name": "Face1", "folder": "Drilling", "path": "CamJob / Drilling / Face1"}))

    def test_a_path_that_drops_its_folder_segment_fails(self):
        with pytest.raises(AssertionError, match="mismatched"):
            self.VERDICT(_ops_payload(
                {"name": "Drill1", "folder": "Drilling", "path": "CamJob / Drill1"}))

    def test_a_setup_with_no_operations_fails_rather_than_passing_vacuously(self):
        with pytest.raises(AssertionError):
            self.VERDICT(_ops_payload())
