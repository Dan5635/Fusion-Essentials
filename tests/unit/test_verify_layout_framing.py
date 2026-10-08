# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The framing pass reading the camera rows an act module wrote by hand, and the frame a placement
reads a step's coordinates in.

An act module builds its rows as it imports, before any chunk is placed and before any sketch plane
is known. The framing pass is the first place that knows both, so it is where a hand row's view is
settled and where the standing frame it leaves behind is recorded - a hand row walked past unread
leaves the pass deciding against a view the camera left several steps ago.
"""

import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TESTS_DIR, "live"))
import tool_verify  # noqa: E402
import verify_core  # noqa: E402
import verify_layout  # noqa: E402
import verify_program  # noqa: E402
import verify_acts_model_solids  # noqa: E402
import verify_acts_model_details  # noqa: E402
import verify_acts_model_sweep  # noqa: E402
import verify_acts_model_extrude_organization as organization  # noqa: E402
from verify_families import fixture_steps  # noqa: E402
import verify_acts_motion  # noqa: E402
import verify_acts_doc  # noqa: E402
import verify_acts_cam  # noqa: E402
import verify_acts_sketch  # noqa: E402
import verify_acts_cloud  # noqa: E402
import verify_acts_mesh  # noqa: E402
import verify_acts_sheet  # noqa: E402
import verify_acts_surface_boundaries as surface_boundaries  # noqa: E402
import verify_acts_surface_edit  # noqa: E402


@pytest.mark.parametrize("invalid", [None, True, float("inf"), float("nan")])
def test_joint_identity_control_pose_rejects_unreadable_coordinates(invalid):
    paths = ["IdParent:1", "IdParent:2", "IdParent:1+IdArm:1", "IdParent:1+IdTip:1",
             "IdParent:2+IdArm:1", "IdParent:2+IdTip:1", "IdBase:1"]
    rows = []
    for path in paths:
        bodies = 0 if path in paths[:2] else 1
        row = {"full_path": path, "body_count": bodies, "origin": [0, 0, 0],
               "x_axis": [1, 0, 0], "y_axis": [0, 1, 0], "z_axis": [0, 0, 1]}
        if bodies:
            row.update(bbox_center=[0, 0, 0], bbox_size=[1, 1, 1])
        rows.append(row)
    payload = {"units": "mm", "is_healthy": True, "occurrence_count": 3,
               "all_occurrence_count": 7, "all_occurrences": rows,
               "all_occurrences_truncated": False, "occurrences_truncated": False,
               "joints_truncated": False, "joint_count": 2,
               "joints": [{"name": "IdPivot"}, {"name": "IdLock"}],
               "broken_joints": [], "broken_relations": [], "unresolved_references": []}
    assert verify_acts_motion._joint_identity_pose_snapshot(payload) is not None
    rows[-1]["origin"][0] = invalid
    assert verify_acts_motion._joint_identity_pose_snapshot(payload) is None


def test_face_point_cleanup_uses_the_verified_owner_and_adopted_feature_name(monkeypatch):
    details = verify_acts_model_details
    monkeypatch.setattr(details, "_RECALL", {})
    rows = details._face_point_witness_rows()
    create = next(row for row in rows if row[0] == "model_hole" and isinstance(row[3], tuple))
    reply = {"holes_verified": True, "holes": 1, "point_space": "face-owner",
             "point": [570, 90, 10], "units": "mm", "host_component": "HolePointFlat",
             "host_verified": True, "feature": "Hole7"}
    assert create[2](reply) is True
    assert not create[2]({**reply, "host_component": "Bracket"})
    key, save = create[3]
    assert save(reply) == "HolePointFlat/Hole7"
    cleanup = next(row for row in rows if row[0] == "design_delete_feature")
    assert cleanup[1]({key: save(reply)})["feature"] == "HolePointFlat/Hole7"


def test_core_feature_scratch_builds_stay_inside_their_documents_after_family_compilation():
    authored = verify_acts_model_details.feature_edit_rows()
    compiled = next(rows for name, _pre, rows, _fallback in verify_program.ACTS
                    if name == "ACT 5 - DETAILS")
    cases = [save[0] for tool, _args, _check, save in authored
             if tool == "doc_new" and save]
    build_tools = {"model_create_component", "sketch_create", "sketch_add_geometry"}
    for key in cases:
        def build_requests(rows):
            start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == key)
            end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
            return [(tool, args({}) if callable(args) else args)
                    for tool, args, _check, _save in rows[start:end] if tool in build_tools]
        actual = build_requests(compiled)
        assert actual == build_requests(authored), key
        assert sum(tool == "model_create_component" for tool, _args in actual) == 1


def test_feature_rename_restore_uses_the_name_read_after_factory_creation(monkeypatch):
    details = verify_acts_model_details
    monkeypatch.setitem(details._RECALL, "rn_feature_a", {})
    rows = details._namespace_rename_witness_rows()
    monkeypatch.setitem(details._RECALL, "rn_feature_a", {"feature": "OriginalExtrude"})
    monkeypatch.setitem(details._RECALL, "rn_indexes", {"feature": 17})
    calls = [args({"rn_body_face": "face"}) for tool, args, *_ in rows
             if tool == "design_set_name" and callable(args)]
    restore = [call for call in calls if call.get("kind") == "feature" and call.get("target") == "17"]
    assert restore == [{"kind": "feature", "target": "17", "new_name": "OriginalExtrude"}]


def test_rename_design_census_accepts_omitted_truncated_when_counts_are_exact(monkeypatch):
    details = verify_acts_model_details
    monkeypatch.setattr(details, "_RECALL", {})
    a, b = details._RN["a"], details._RN["b"]
    initial = [
        ("OriginalExtrude", "ExtrudeFeature", a),
        (details._RN["joint"], "Joint", "Root"),
        (details._RN["origin"], "JointOrigin", a),
        (details._RN["plane"], "ConstructionPlane", a),
        (details._RN["axis"], "ConstructionAxis", a),
        (details._RN["point"], "ConstructionPoint", a),
    ]
    datum_rows = [
        {"component": owner, "kind": kind, "name": name}
        for owner, kind, name in (
            (a, "construction_plane", details._RN["plane"]),
            (b, "construction_plane", details._RN["plane"]),
            (a, "construction_axis", details._RN["axis"]),
            (b, "construction_axis", details._RN["axis"]),
            (a, "construction_point", details._RN["point"]),
            (b, "construction_point", details._RN["point"]),
        )
    ]

    def payload(names):
        timeline_rows = [{"index": i, "name": name, "type": kind,
                          "component": owner, "health": "healthy"}
                         for i, (name, kind, owner) in enumerate(names)]
        return {
            "timeline": {"count": len(timeline_rows), "returned": len(timeline_rows),
                         "marker_position": len(timeline_rows), "summary": {"healthy": 6},
                         "timeline": timeline_rows},
            "tree": {"truncated": False, "children_truncated": False, "children": [
                {"component": a, "bodies": [{"name": "OriginalExtrude"}]},
                {"component": b, "bodies": [{"name": "PartnerBody"}]},
            ]},
            "datums": {"datums": [dict(row) for row in datum_rows]},
        }

    monkeypatch.setitem(details._RECALL, "rn_feature_a", {"feature": "OriginalExtrude"})
    monkeypatch.setitem(details._RECALL, "rn_feature_b", {"body": "PartnerBody"})
    assert details._rn_design("baseline")(payload(initial)) is True
    names = [
        (details._RN_NEW["feature"], "ExtrudeFeature", a),
        (details._RN_NEW["joint"], "Joint", "Root"),
        (details._RN_NEW["joint_origin"], "JointOrigin", a),
        (details._RN_NEW["plane"], "ConstructionPlane", a),
        (details._RN_NEW["axis"], "ConstructionAxis", a),
        (details._RN_NEW["point"], "ConstructionPoint", a),
    ]
    renamed = payload(names)
    renamed["datums"]["datums"] = [
        {**row, "name": (details._RN_NEW["plane"] if row["kind"] == "construction_plane"
                          else details._RN_NEW["axis"] if row["kind"] == "construction_axis"
                          else details._RN_NEW["point"] if row["component"] == a else row["name"])}
        if row["component"] == a else row
        for row in renamed["datums"]["datums"]
    ]

    assert details._rn_design("renamed")(renamed) is True
    incomplete = {**renamed, "timeline": {**renamed["timeline"], "returned": 5,
                                        "timeline": renamed["timeline"]["timeline"][:-1]}}
    with pytest.raises(AssertionError):
        details._rn_design("renamed")(incomplete)
    missing_count = {**renamed, "timeline": dict(renamed["timeline"])}
    missing_count["timeline"].pop("returned")
    with pytest.raises(AssertionError):
        details._rn_design("renamed")(missing_count)


def test_nested_group_ambiguity_lists_both_addresses_in_either_order():
    rows = verify_acts_motion._nested_relation_rows()
    matches = [row[2] for row in rows if hasattr(row[2], "fragments")
               and any("names 2 rigid groups" in f for f in row[2].fragments)]
    assert len(matches) == 1
    check = matches[0]
    prefix = "'Rigid Group 1' names 2 rigid groups - refusing to guess which one. Pass one as listed: "
    for addresses in ("'NrEye/Rigid Group 1', 'NrRet/Rigid Group 1'.",
                      "'NrRet/Rigid Group 1', 'NrEye/Rigid Group 1'."):
        assert check.missing(prefix + addresses) == []
    assert check.missing(prefix + "'NrRet/Rigid Group 1'.")
    assert check.missing(prefix + "'NrEye/Rigid Group 1'.")
    assert check.missing("'NrEye/Rigid Group 1', 'NrRet/Rigid Group 1'.")


def test_loft_refusal_fixture_defers_handler_until_script_entry():
    namespace = {}
    exec(verify_acts_model_sweep._loft_refusal_details_script("LoftEdit/Loft1"), namespace)
    entry = namespace.get("run")
    assert callable(entry) and entry.__code__.co_argcount == 1


def test_body_move_history_checks_sparse_row_summary(monkeypatch):
    before = {"index": 0, "name": "Extrude1", "type": "ExtrudeFeature"}
    after = {"index": 1, "name": "CutPasteBodies1", "type": "CutPasteBody"}
    monkeypatch.setattr(organization, "_org_tree_counts", lambda *_: lambda p: True)
    monkeypatch.setitem(organization._RECALL, "body_history", {"timeline": [before]})
    timeline = {"count": 2, "returned": 2, "marker_position": 2,
                "timeline": [before, after],
                "summary": {"states": {"healthy": 2}, "exceptions": []}}
    check = organization._org_tree_history({}, 0, "body_history")
    assert check({"timeline": timeline}) is not None
    for summary in ({}, {"states": {"healthy": 1, "warning": 1}, "exceptions": []}):
        timeline["summary"] = summary
        with pytest.raises(AssertionError):
            check({"timeline": timeline})


def test_body_move_round_trip_uses_the_returned_name(monkeypatch):
    rows = organization._body_organization_rows()
    context = {"org_doc": "scratch", "org_nested_root": {"handle": "root-body"}}
    returned_index = next(i for i, row in enumerate(rows) if row[0] == "model_edit_body"
                          and row[3] and row[3][0] == "org_body_name")
    returned = rows[returned_index]
    assert returned[1](context)["body"] == "root-body"
    assert returned[1](context)["destination"] == "OrgSource:2"
    monkeypatch.setitem(organization._RECALL, "org_body_name", "Body1")
    key, getter = returned[3]
    context[key] = getter({"body_name": "Body3"})
    refusal_index = next(i for i, row in enumerate(rows) if i > returned_index
                         and row[0] == "model_edit_body"
                         and callable(row[1]) and row[1](context).get("action") == "copy"
                         and "destination" not in row[1](context))
    following = rows[refusal_index + 1]
    assert following[0] == "find_geometry"
    assert following[1](context)["target"] == "OrgSource:2:Body3"
    copy = rows[refusal_index + 2]
    assert copy[0] == "model_edit_body"
    assert copy[1](context)["body"] == "OrgSource:2:Body3"


@pytest.mark.parametrize("factory,home,context", [
    (verify_acts_doc._product_disclosure_rows, "disclosure_home", {
        "disclosure_home": "home", "disclosure_doc": "scratch", "disclosure_witness": "Body1",
        "disclosure_stock": "Body2", "disclosure_DatumA": "plane-a", "disclosure_DatumB": "plane-b",
        "disclosure_fresh_face": "fresh-face"}),
    (verify_acts_mesh._thicken_visibility_rows, "thicken_home", {
        "thicken_home": "home", "thicken_doc": "scratch", "thicken_visible": "Body1", "thicken_hidden": "Body2",
        "thicken_witness": "Body3", "thicken_face": "source-face", "thicken_wall_visible": "Body4",
        "thicken_wall_hidden": "Body5", "thicken_visible_after": {"Body1": "fresh-source1"},
        "thicken_hidden_after": {"Body2": "fresh-source2"}, "pt_face": "placed-face",
        "pt_source_handle": "placed-source"})])
def test_product_disclosure_scenes_keep_local_geometry_fresh_consumers_and_recovery(factory, home, context):
    rows = [row for _name, _pre, narrative, _fallback in verify_program.ACTS for row in narrative]
    start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == home)
    end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
    wanted = {"sketch_create", "sketch_add_geometry", "sketch_get", "model_create_component", "model_construction",
              "model_extrude", "surface_extrude", "surface_thicken", "find_geometry", "model_inspect", "view_set"}
    def requests(selected):
        return [(tool, args(context) if callable(args) else args) for tool, args, _check, _save in selected if tool in wanted]
    authored = requests(factory())
    assert requests(rows[start:end]) == authored
    if home == "disclosure_home":
        parameter = next(args(context) if callable(args) else args
                         for tool, args, _check, _save in rows[start:end] if tool == "param_add")
        assert parameter == {"name": "DisclosureHeight", "expression": "10 mm", "unit": "mm", "expect_document": "scratch"}
        reads = [a for t, a in authored if t == "sketch_get"]
        assert [(a["sketch_name"], a["component"]) for a in reads] == [("DatumAPick", "DatumA:1"), ("DatumBPick", "DatumB:1")]
        planes = [row for row in factory() if row[0] == "model_construction"]
        for row, owner in zip(planes, ("DatumA", "DatumB")):
            assert row[3][0] == "disclosure_" + owner and row[3][1]({"handle": "native-plane"}) == "native-plane"
        consumers = [a for t, a in authored if t == "sketch_create" and a["name"].endswith("Pick")]
        assert [a["plane"] for a in consumers] == ["plane-a", "plane-b"]
        assert all(row[3] is None for row in factory() if row[0] == "find_geometry"
                   and row[1](context).get("kind") == "construction_plane")
        assert any(t == "model_inspect" and a["target"] == "fresh-face" for t, a in authored)
        create = next(row for row in factory() if row[0] == "model_create_component" and row[1](context)["name"] == "EmptyFocus")
        assert create[2]({"created": True, "activated": False, "occurrence": "EmptyFocus:1", "full_path": "EmptyFocus:1"}) is True
    else:
        recovery = [a for t, a in authored if t == "view_set" and a.get("target") in (["fresh-source1"], ["fresh-source2"])]
        assert recovery == [{"action": "show", "target": ["fresh-source1"], "expect_document": "scratch"},
                            {"action": "hide", "target": ["fresh-source2"], "expect_document": "scratch"}]
        lines = [a["geometry"] for t, a in authored if t == "sketch_add_geometry"]
        assert lines[:2] == [[{"kind": "line", "x1": x, "y1": 20, "x2": x + 10, "y2": 20}] for x in (0, 30)]


def test_saved_configuration_scene_keeps_owned_local_geometry_refusals_and_close():
    context = {"configure_home": "session:home", "configure_owned": "session:coupon", "configure_urn": "urn:coupon",
               "lin_home": "session:home", "lin_owned": "session:lineage", "lin_reopened": "session:reopened"}
    authored = verify_acts_cloud._CLOUD_CONFIGURE
    compiled = next(rows for name, _pre, rows, _fallback in verify_program.ACTS
                    if name == "ACT 11e - CLOUD: CONFIGURATION COLUMN REFUSALS")
    def configuration_scenes(rows):
        end = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == "cr_home")
        return rows[:end]
    authored = configuration_scenes(authored)
    compiled = configuration_scenes(compiled)
    def requests(rows):
        return [(tool, args(context) if callable(args) else args) for tool, args, _check, _save in rows
                if tool in {"sketch_create", "sketch_add_geometry", "model_extrude", "design_configure",
                            "doc_save_as", "doc_close", "design_activate_component"}]
    compiled_requests = requests(compiled)
    assert compiled_requests == requests(authored)
    lineage_start = next(i for i, row in enumerate(compiled) if row[3] and row[3][0] == "lin_home")
    coupon_requests = requests(compiled[:lineage_start])
    outlines = [args for tool, args in coupon_requests if tool == "sketch_add_geometry"]
    assert [p["geometry"] for p in outlines] == [
        [{"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 8}],
        [{"kind": "rectangle", "x1": 40, "y1": 0, "x2": 45, "y2": 5}]]
    assert [args["distance"] for tool, args in coupon_requests if tool == "model_extrude"] == ["ProbeW", "5 mm"]
    columns = [args for tool, args in coupon_requests if tool == "design_configure" and args["action"] == "add_parameter"]
    assert [p["values"] for p in columns] == [{"B": "NoSuchProbe * 2"}, {"B": "5 kg"}, {"B": "13 mm"}]
    assert all(p["expect_document"] == "session:coupon" for p in columns)
    assert next(args for tool, args in requests(compiled) if tool == "doc_close") == {
        "name": "session:coupon", "save_changes": False, "expect_document": "session:coupon"}
    assert verify_program.ACT_NEEDS["ACT 11e - CLOUD: CONFIGURATION COLUMN REFUSALS"] == verify_program.CLOUD_TIER


def test_extent_story_consumes_the_names_and_handles_its_reads_retained(monkeypatch):
    retained = {}
    monkeypatch.setattr(verify_core, "_RECALL", retained)
    monkeypatch.setattr(verify_acts_model_solids, "_RECALL", retained)
    rows = verify_acts_model_solids._w2_extrude_extent_rows()
    context = {"w2_extents_doc": "session:scratch"}
    for role, name in (("Near", "Body1"), ("Far", "Body2"), ("Mixed", "Body3"), ("Start", "Body4")):
        key = "w2_extents_W2" + role + "Target"
        save = next(row[3] for row in rows if row[3] and row[3][0] == key)
        context[key] = save[1]({"result_bodies": [name]})
    body_read = next(row for row in rows if row[0] == "design_get"
                     and isinstance(row[1], dict) and row[1].get("tree_bodies") is True)
    assert body_read[2]({"tree": {"root_bodies": [
        {"name": "Body1", "handle": "near-body"}, {"name": "Body2", "handle": "far-body"}]}})
    stop_calls = [next(row[1](context) for row in rows if row[3]
                      and row[3][0] == "w2_extents_" + role) for role in ("near", "far")]
    assert [args["to_object"] for args in stop_calls] == ["near-body", "far-body"]
    for role, z, profile, field in (("Mixed", 8, "W2MixedProfile", "to_object"),
                                   ("Start", .1, "W2StartProfile", "start_object")):
        body = context["w2_extents_W2" + role + "Target"]
        read = next(row for row in rows if row[0] == "find_geometry"
                    and row[1](context).get("target") == body)
        assert read[2]({"match_count": 1, "matches": [{"kind": "planar_face", "handle": role,
                         "position": [0, 0, z], "normal": [0, 0, 1], "area": 400}]})
        output_key = "mixed" if role == "Mixed" else "entity_start"
        arguments = next(row[1](context) for row in rows if row[3]
                         and row[3][0] == "w2_extents_" + output_key)
        assert arguments["sketch_name"] == profile and arguments[field] == role
        assert arguments["expect_document"] == "session:scratch"


def test_w2_draft_and_split_writes_consume_the_retained_face_handles(monkeypatch):
    retained = {}
    monkeypatch.setattr(verify_core, "_RECALL", retained)
    monkeypatch.setattr(verify_acts_model_solids, "_RECALL", retained)
    monkeypatch.setattr(organization, "_RECALL", retained)

    split = organization._w2_directional_split_rows()
    split_context = {"w2_vector_split_doc": "session:split",
                     "w2_vector_split_target": "body split-target"}
    split_read = next(row for row in split if row[0] == "find_geometry"
                      and row[1](split_context).get("nearest_to") == [20, 20, 20])
    assert split_read[2]({"matches": [{"kind": "planar_face", "handle": "split-top",
        "area": 1600, "position": [20, 20, 20], "normal": [0, 0, 1]}]})
    split_write = next(row for row in split if row[0] == "model_split")
    assert split_write[1](split_context)["faces"] == ["split-top"]
    assert split_write[1](split_context)["expect_document"] == "session:split"

    draft = verify_acts_model_solids._w2_two_angle_draft_rows()
    draft_context = {"w2_two_angle_draft_doc": "session:draft",
                     "w2_two_angle_draft_body": "body draft-source"}
    draft_read = next(row for row in draft if row[0] == "find_geometry"
                      and row[1](draft_context).get("nearest_to") == [0, 20, 20])
    assert draft_read[2]({"matches": [{"kind": "planar_face", "handle": "draft-side",
        "area": 1600, "position": [0, 20, 20], "normal": [1, 0, 0]}]})
    draft_write = next(row for row in draft if row[0] == "model_draft")
    assert draft_write[1](draft_context)["faces"] == ["draft-side"]
    assert draft_write[1](draft_context)["expect_document"] == "session:draft"


@pytest.fixture
def field(monkeypatch):
    """Two adjacent chunks that share a frame, and one a long way off."""
    for chunk, box in (("Alpha", [0.0, 20.0, 0.0, 20.0]), ("Beta", [10.0, 30.0, 0.0, 20.0]),
                       ("Far", [900.0, 920.0, 900.0, 920.0])):
        monkeypatch.setitem(verify_layout._PLACED_BOX, chunk, box)


def _made(name):
    return [("model_create_component", {"name": name, "activate": True}, "ok", None),
            ("model_extrude", {"distance": 5}, "ok", None)]


def _frames(rows):
    return [s[1]["focus"] for s in rows if s[0] == "view_set"]


class TestStandingFrame:
    def test_a_hand_frame_sends_the_next_subject_back_on_camera(self, field):
        rows = verify_layout._framed(
            _made("Alpha") + [tool_verify._watch("Far:1")] + _made("Beta"))
        # Beta sits inside the frame Alpha was given, but the camera is on Far by then.
        assert "Beta:1" in _frames(rows)[-1]

    def test_a_row_that_only_isolates_leaves_the_frame_where_it_was(self, field):
        rows = verify_layout._framed(
            _made("Alpha")
            + [("view_set", {"action": "isolate", "focus": "Far:1"}, "ok", None)]
            + _made("Beta"))
        # An isolate aims nothing, so Beta is still on screen and costs no second frame.
        assert _frames(rows) == [["Alpha:1"], "Far:1"]


class TestMeasuredExtents:
    """The authored box counts only the coordinates a step carries, so a pattern or a mirror reaches
    past it. A measured row widens the frame; it never shrinks one."""

    def test_a_measured_overrun_widens_the_frame_and_never_narrows_it(self, field, monkeypatch):
        assert verify_layout._chunk_box("Alpha") == [0.0, 20.0, 0.0, 20.0]
        monkeypatch.setitem(verify_layout._MEASURED_BOX, "Alpha", [-240.0, 390.0, 5.0, 15.0])
        # x grows both ways; y stays the authored span, which the narrower measurement cannot cut
        assert verify_layout._chunk_box("Alpha") == [-240.0, 390.0, 0.0, 20.0]
        assert verify_layout._frame_box(["Alpha:1"]) == [-240.0, 390.0, 0.0, 20.0]

    def test_measured_boxes_unions_the_instances_and_drops_an_unread_corner(self):
        rows = verify_layout.measured_boxes({
            "Alpha:1": {"min_point": {"x": 0.0, "y": 1.0, "z": 0.0},
                        "max_point": {"x": 10.0, "y": 4.0, "z": 2.0}},
            "Alpha:2": {"min_point": {"x": -5.0, "y": 2.0, "z": 0.0},
                        "max_point": {"x": 6.0, "y": 9.0, "z": 2.0}},
            "Beta:1": {"min_point": {"x": None, "y": 0.0, "z": 0.0},
                       "max_point": {"x": 3.0, "y": 3.0, "z": 1.0}},
        })
        assert rows == {"Alpha": [-5.0, 10.0, 1.0, 9.0]}


class TestLayoutDriftGate:
    """ACT 9's receipt row: _MEASURED_BOX is only true while the field still stands where it was
    read, so a layout move has to fail rather than age the table silently."""

    def _points(self, box):
        return ({"x": box[0], "y": box[2], "z": 0.0}, {"x": box[1], "y": box[3], "z": 0.0})

    def test_every_gated_chunk_passes_where_it_was_measured_and_fails_when_moved(self):
        for chunk in verify_layout._DRIFT_CHUNKS:
            recorded = verify_layout._MEASURED_BOX[chunk]
            lo, hi = self._points(recorded)
            assert verify_layout.layout_placed_as_measured(chunk, lo, hi) is True, chunk
            # one gutter of travel is the smallest move that matters - never agreement
            lo, hi = self._points([v + 60.0 for v in recorded])
            assert verify_layout.layout_placed_as_measured(chunk, lo, hi) is False, chunk

    def test_a_corner_that_did_not_read_is_not_agreement(self):
        chunk = verify_layout._DRIFT_CHUNKS[0]
        lo, hi = self._points(verify_layout._MEASURED_BOX[chunk])
        assert verify_layout.layout_placed_as_measured(
            chunk, {"x": None, "y": lo["y"], "z": 0.0}, hi) is False

    def test_the_four_rows_are_built_from_one_shared_predicate(self):
        # the gate widens by a NAME, not by another copy of the check: each row targets its own
        # occurrence and every row is judged by the same layout_placed_as_measured.
        rows = [verify_layout.drift_row(c) for c in verify_layout._DRIFT_CHUNKS]
        assert [r[1]["target"] for r in rows] == [c + ":1" for c in verify_layout._DRIFT_CHUNKS]
        for chunk, row in zip(verify_layout._DRIFT_CHUNKS, rows):
            box = verify_layout._MEASURED_BOX[chunk]
            lo, hi = self._points(box)
            assert row[2]({"min_point": lo, "max_point": hi}) is True, chunk
            lo, hi = self._points([v + 60.0 for v in box])
            assert row[2]({"min_point": lo, "max_point": hi}) is False, chunk


class TestPlacementFrame:
    """A coordinate LIST is read in the sketch's own frame, as the pair keys already are."""

    _POINTS = {"sketch_name": "XZOnly", "kind": "polyline",
               "points": [[400.0, 5.0], [460.0, 40.0]]}

    def test_an_xz_points_list_pins_only_the_axis_its_plane_spans(self):
        # read as world (x, y) the depths land as world Y, so the chunk measures 5..40 mm deep in an
        # axis the XZ plane does not span - and the shift then carries it along that axis.
        assert verify_layout._place_points(self._POINTS, "xz", "sketch_add_geometry") == [
            (400.0, None), (460.0, None)]
        moved = verify_layout._place_shift(self._POINTS, 100.0, 200.0, "xz", "sketch_add_geometry")
        assert moved["points"] == [[500.0, 5.0], [560.0, 40.0]]

    def test_a_points_only_xz_chunk_stays_where_it_was_authored(self):
        program = [("act", None, [
            ("sketch_create", {"name": "XZOnly", "plane": "xz"}, "ok", None),
            ("sketch_add_geometry", self._POINTS, "ok", None)], None)]
        assert verify_layout._family_slots("act", program) == {}
        assert verify_layout._placed(program[0][2], {}) == program[0][2]

    def test_definition_scratch_queries_stay_with_local_stock_in_composed_act(self):
        rows = next(rows for name, _pre, rows, _fallback in tool_verify.ACTS
                    if name == "ACT 5 - DETAILS")
        context = {"def_doc": "scratch-document"}
        top_index = next(i for i, step in enumerate(rows)
                         if step[3] and step[3][0] == "hf_top")
        stock_step = rows[top_index - 2]
        assert stock_step[0] == "sketch_add_geometry"
        stock = stock_step[1](context)
        assert stock["expect_document"] == "scratch-document"
        assert stock["geometry"] == [
            {"kind": "rectangle", "x1": 200, "y1": 0, "x2": 260, "y2": 40}]
        start = next(i for i, step in enumerate(rows) if step[3] and step[3][0] == "def_doc")
        end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
        queries = [args(context) if callable(args) else args
                   for tool, args, _check, _save in rows[start:end] if tool == "find_geometry"]
        targets = {"DefinitionBench", "TapControlBench", "HoleFeedback", "DefinitionPost"}
        positions = [(q["target"], q["nearest_to"]) for q in queries
                     if q.get("target") in targets and "nearest_to" in q]
        assert positions == [
            ("DefinitionBench", [12.5, 12.5, 30]),
            ("DefinitionBench", [5, 17, 20]), ("DefinitionBench", [17, 5, 20]),
            ("TapControlBench", [130, 12.5, 30]), ("TapControlBench", [110, 10, 15]),
            ("HoleFeedback", [230, 20, 30]), ("HoleFeedback", [215, 30, 20]),
            ("HoleFeedback", [245, 30, 20]), ("HoleFeedback", [230, 30, 20]),
            ("DefinitionPost", [70, 0, 12.5]), ("DefinitionPost", [70, 0, 12.5])]


class TestDatumOperandStory:
    def test_the_operand_story_rides_no_slot_so_its_world_points_stay_authored(self):
        # Its predicates expect bare world millimetres; a slot or a ridden cursor would shift the
        # geometry and every read away from them.
        import verify_acts_model as acts
        mine = {id(row) for row in acts._DATUM_OPERANDS}
        chunks = [chunk for step, chunk, _cursor, _frame in verify_layout._place_walk(acts._DETAILS)
                  if id(step) in mine]
        assert len(chunks) == len(acts._DATUM_OPERANDS) and set(chunks) == {None}


def test_redistributed_sketch_frames_name_subjects_in_their_own_act():
    import verify_program

    for rows in verify_program._LOCAL_SKETCHES.values():
        known = set()
        for tool, args, _expect, _save in rows:
            if tool == "model_create_component":
                known.update((args["name"], args["name"] + ":1"))
            elif tool == "sketch_create":
                known.add(args["name"])
            elif tool == "view_set" and args.get("focus"):
                focus = args["focus"]
                assert set(focus if isinstance(focus, list) else [focus]) <= known
        assert rows[-1][:2] == ("design_activate_component", {"occurrence": "root"})

    details = verify_program._LOCAL_SKETCHES["ACT 5 - DETAILS"]
    assert any(row[0] == "view_set" and row[1].get("focus") == ["EmbossBlockS"]
               and row[1].get("orientation") == "top" for row in details)

    duplicate = [(name, None, [("sketch_create", {"name": "Shared", "plane": "xy"},
                               "ok", None)], []) for name in ("ACT X", "ACT Y")]
    with pytest.raises(ValueError, match="belongs to two acts"):
        verify_program._sketch_owners(duplicate)


class TestSketchView:
    def test_a_hand_frame_written_before_the_planes_were_known_is_rewritten(self, monkeypatch):
        monkeypatch.setitem(tool_verify._SKETCH_PLANE, "FarS", "xz")
        stale = ("view_set", {"action": "orient", "orientation": "iso-top-right",
                              "focus": "FarS"}, "ok", None)
        assert verify_layout._framed([stale])[0][1]["orientation"] == "front"


def _component(name, low, high):
    """One component with a line whose endpoints define its authored layout box."""
    sketch = name + "Sketch"
    return [
        ("model_create_component", {"name": name, "activate": True}, "ok", None),
        ("sketch_create", {"name": sketch, "plane": "xy"}, "ok", None),
        ("sketch_add_geometry", {"sketch_name": sketch, "kind": "line",
                                 "x1": low[0], "y1": low[1],
                                 "x2": high[0], "y2": high[1]}, "ok", None),
    ]


class TestFocusCap:
    def test_a_whole_known_neighbour_group_cannot_overrun_the_focus_cap(self):
        focus, _box = verify_layout._frame_neighbourhood(
            ["Subject"], [0.0, 1.0, 0.0, 1.0],
            [(["NearA", "NearB", "NearC"], [10.0, 11.0, 0.0, 1.0])],
            target=100.0, cap=2)
        assert focus == ["Subject"]

    def test_an_unknown_subject_still_enforces_the_focus_cap_by_whole_group(self):
        focus, _box = verify_layout._frame_neighbourhood(
            ["Unknown"], None,
            [(["NearA", "NearB", "NearC"], [10.0, 11.0, 0.0, 1.0])],
            target=100.0, cap=2)
        assert focus == ["Unknown"]


class TestPatternSuffix:
    def test_a_plain_name_ending_in_one_is_not_treated_as_a_colon_one_occurrence(
            self, monkeypatch):
        monkeypatch.setattr(verify_layout, "_PATTERNED", {"Part"})
        monkeypatch.setitem(verify_layout._PLACED_BOX, "Neighbor", [600.0, 700.0, 0.0, 100.0])
        monkeypatch.setitem(verify_layout._PLACED_BOX, "Part11", [0.0, 100.0, 0.0, 100.0])
        rows = verify_layout._framed(_made("Neighbor") + _made("Part11"))
        assert _frames(rows)[-1] == ["Part11:1"]


class TestSketchHoistOwner:
    def test_hoist_uses_recorded_active_owner_through_reading_order(self):
        narrative = [
            ("model_create_component", {"name": "OwnerA", "activate": True}, "ok", None),
            ("model_create_component", {"name": "NearB", "activate": True}, "ok", None),
            ("design_activate_component", {"occurrence": "OwnerA:1"}, "ok", None),
            ("sketch_create", {"name": "OwnedSketch", "plane": "xy"}, "ok", None),
            ("sketch_add_geometry", {"sketch_name": "OwnedSketch", "kind": "line",
                                     "x1": 0.0, "y1": 0.0, "x2": 20.0, "y2": 0.0},
             "ok", None),
        ]
        hoisted, _kept = verify_layout._sketches_first(
            [("owners", None, narrative, None)], set())
        created = [s[1]["name"] for s in hoisted if s[0] == "model_create_component"]
        assert created == ["OwnerA"]
        reading = verify_layout._sketch_reading_order(hoisted, {"OwnerA": (0.0, 0.0)})
        reading_created = [s[1]["name"] for s in reading
                           if s[0] == "model_create_component"]
        assert reading_created == ["OwnerA"]

class TestMappedPatternIdentity:
    def test_an_exact_mapped_pattern_key_still_widens_the_frame(self, monkeypatch):
        monkeypatch.setattr(verify_layout, "_PATTERNED", {"Pattern:1"})
        monkeypatch.setitem(verify_layout._CHUNK_OF, "Alias", "Pattern:1")
        monkeypatch.setitem(verify_layout._CHUNK_OF, "Alias:1", "Pattern:1")
        monkeypatch.setitem(verify_layout._PLACED_BOX, "Pattern:1",
                            [0.0, 100.0, 0.0, 100.0])
        monkeypatch.setitem(verify_layout._PLACED_BOX, "Neighbor",
                            [600.0, 700.0, 0.0, 100.0])
        rows = verify_layout._framed(_made("Neighbor") + _made("Alias"))
        assert _frames(rows)[-1] == ["Alias:1", "Neighbor:1"]


class TestNonactivatingSketchOwner:
    def test_hoist_creates_then_activates_a_recorded_owner(self):
        narrative = [
            ("model_create_component", {"name": "OwnerA", "activate": False}, "ok", None),
            ("design_activate_component", {"occurrence": "OwnerA:1"}, "ok", None),
            ("sketch_create", {"name": "OwnedSketch", "plane": "xy"}, "ok", None),
            ("sketch_add_geometry", {"sketch_name": "OwnedSketch", "kind": "line",
                                     "x1": 0.0, "y1": 0.0, "x2": 20.0, "y2": 0.0},
             "ok", None),
        ]
        hoisted, _kept = verify_layout._sketches_first(
            [("owner", None, narrative, None)], set())
        reading = verify_layout._sketch_reading_order(hoisted, {"OwnerA": (0.0, 0.0)})
        tools = [step[0] for step in reading]
        create_at = tools.index("model_create_component")
        activate_at = tools.index("design_activate_component")
        sketch_at = tools.index("sketch_create")
        assert create_at < activate_at < sketch_at
        assert reading[create_at][1]["activate"] is False
        assert reading[activate_at][1]["occurrence"] == "OwnerA:1"

    @pytest.mark.parametrize("second_activates", [False, True])
    def test_multiple_hoisted_creates_precede_their_sketch_activation(self, second_activates):
        a = _component("A", (400.0, 400.0), (420.0, 420.0))
        b = _component("B", (500.0, 500.0), (520.0, 520.0))
        narrative = [
            ("model_create_component", {"name": "A", "activate": False}, "ok", None),
            ("model_create_component", {"name": "B", "activate": second_activates}, "ok", None),
            ("design_activate_component", {"occurrence": "B:1"}, "ok", None),
        ] + b[1:] + [
            ("design_activate_component", {"occurrence": "A:1"}, "ok", None),
        ] + a[1:]
        hoisted, _kept = verify_layout._sketches_first(
            [("owners", None, narrative, None)], set())
        reading = verify_layout._sketch_reading_order(hoisted, {"A": (0, 0), "B": (100, 0)})
        for rows in (hoisted, reading):
            created, owners, active = set(), {}, None
            for tool, args, _expected, _capture in rows:
                if tool == "model_create_component":
                    created.add(args["name"])
                    if args.get("activate"):
                        active = args["name"]
                elif tool == "design_activate_component":
                    active = args["occurrence"].removesuffix(":1")
                    assert active == "root" or active in created
                elif tool == "sketch_create":
                    owners[args["name"]] = active
            assert owners == {"ASketch": "A", "BSketch": "B"}


def _argument_signature(value):
    if callable(value):
        return (value.__code__.co_code, _argument_signature(value.__defaults__),
                tuple(_argument_signature(cell.cell_contents)
                      for cell in (value.__closure__ or ())))
    if isinstance(value, dict):
        return tuple(sorted((key, _argument_signature(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_argument_signature(item) for item in value)
    return value


def _act_arguments(acts):
    return {name: tuple(tuple((row[0], _argument_signature(row[1])) for row in lane)
                        for lane in (narrative, fallback or []))
            for name, _pre, narrative, fallback in acts}


def _fixture_arguments(acts, slots):
    owners = verify_program.family_names(acts)
    result = {}
    for family in set(owners.values()):
        setup = fixture_steps(family, slots=slots[family])
        result[family, "setup"] = tuple((row[0], _argument_signature(row[1])) for row in setup)
    for name in owners:
        family = owners[name]
        for entitled in (False, True):
            before = fixture_steps(family, before_act=name, entitled=entitled,
                                   slots=slots[family])
            result[family, name, entitled] = tuple(
                (row[0], _argument_signature(row[1])) for row in before)
    return result


def test_removing_or_reordering_families_cannot_move_retained_rows_or_frames():
    raw = verify_program._RAW_ACT_PROGRAM
    owners = verify_program.family_names(raw)
    original = _act_arguments(verify_program.ACTS)
    original_fixtures = _fixture_arguments(verify_program.ACTS, verify_program.FAMILY_SLOTS)
    for excluded in ("sketch", "surfaces", "details"):
        subset = [act for act in raw if owners[act[0]] != excluded]
        compiled = verify_program.compile_program(subset)
        assert _act_arguments(compiled["acts"]) == {
            name: rows for name, rows in original.items() if owners[name] != excluded}
        assert _fixture_arguments(compiled["acts"], compiled["slots"]) == {
            key: rows for key, rows in original_fixtures.items() if key[0] != excluded}
    reversed_program = verify_program.compile_program(list(reversed(raw)))
    assert _act_arguments(reversed_program["acts"]) == original
    assert _fixture_arguments(reversed_program["acts"], reversed_program["slots"]) == original_fixtures


def test_same_sketch_name_in_separate_family_documents_has_local_owner():
    def act(name, plane):
        return (name, None, [
            ("sketch_create", {"name": "Shared", "plane": plane}, "ok", None),
            ("sketch_add_geometry", {"sketch_name": "Shared", "geometry": [
                {"kind": "line", "x1": 0.0, "y1": 0.0, "x2": 20.0, "y2": 0.0}]}, "ok", None)], [])
    compiled = verify_program.compile_program([
        act("ACT 4 - MESH", "xy"), act("ACT 6b - NESTING", "xz")])
    assert [name for name, *_rest in compiled["acts"]] == ["ACT 4 - MESH", "ACT 6b - NESTING"]
    assert all(any(row[0] == "sketch_create" and row[1]["name"] == "Shared"
                   for row in narrative)
               for _name, _pre, narrative, _fallback in compiled["acts"])
    assert compiled["frames"]["mesh"]["planes"]["Shared"] == "xy"
    assert compiled["frames"]["nesting"]["planes"]["Shared"] == "xz"


@pytest.fixture
def direct_body_material_read():
    """Return the measured direct-body bounds/material projection with an empty subtree body census."""
    return {"target": "body 'Body1'", "kind": "body", "units": "mm",
            "frame": "world axes (axis-aligned)", "box_read": "preciseBoundingBox", "oriented": False,
            "x": 120.0, "y": 80.0, "z": 45.0,
            "min_point": {"x": -60.0, "y": -40.0, "z": 0.0},
            "max_point": {"x": 60.0, "y": 40.0, "z": 45.0},
            "center": {"x": 0.0, "y": 0.0, "z": 22.5}, "lump_count": 1,
            "mass": {"target": "body 'Body1'", "units": "mm", "accuracy_used": "very_high",
                     "mass_kg": 2.441735, "volume": 311049.084447, "area": 41374.689466,
                     "density_kg_per_cm3": 0.00785, "per_body": [], "per_body_count": 0,
                     "per_body_truncated": False}}


def test_scoped_direct_body_witness_accepts_measured_empty_subtree_census(direct_body_material_read):
    state = verify_acts_model_solids._symmetric_target_body_state(direct_body_material_read)
    assert state is not None
    assert state["material"] == direct_body_material_read["mass"]
    assert state["bounds"]["min_point"] == {"x": -60.0, "y": -40.0, "z": 0.0}
    assert state["lump_count"] == 1 and state["material"]["per_body_count"] == 0


@pytest.mark.parametrize("path", [("min_point", "z"), ("mass", "volume"), ("mass", "mass_kg"),
                                  ("mass", "area"), ("lump_count",)])
def test_scoped_direct_body_witness_refuses_unread_main_measurement(direct_body_material_read, path):
    target = direct_body_material_read
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = None
    assert verify_acts_model_solids._symmetric_target_body_state(direct_body_material_read) is None


def test_geometry_contract_scratch_coordinates_survive_preceding_full_family_rows():
    import verify_acts_sketch as sketch
    import verify_acts_model_solids as solids
    import verify_acts_model_sweep as sweep
    coordinates = {"sketch_add_geometry", "sketch_edit_curve", "find_geometry", "model_construction"}
    cases = [(sketch._fillet_radius_rows, "fillet_doc", {"fillet_doc": "scratch", "fillet_story": "home"}),
             (solids._symmetric_target_rows, "extent_doc", {"extent_doc": "scratch", "extent_story": "home",
                 "extent_block": "Body1", "extent_top": "face", "extent_ordinary": "Body2", "extent_distance": "Body3"}),
             (sweep._loft_endpoint_rows, "endpoint_doc", {"endpoint_doc": "scratch", "endpoint_story": "home",
                 "endpoint_body": "Body1"})]
    compiled = verify_program.compile_program(verify_program._RAW_ACT_PROGRAM)["acts"]
    for factory, key, context in cases:
        authored = factory()
        rows = next(rows for _name, _pre, rows, _fallback in compiled
                    if any(save and save[0] == key for _tool, _args, _check, save in rows))
        start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == key)
        end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
        def requests(selected):
            return [(tool, args(context) if callable(args) else args)
                    for tool, args, _check, _save in selected if tool in coordinates]
        assert requests(rows[start:end]) == requests(authored), key


def test_geometry_contract_scratch_root_resets_prior_sketch_cursor():
    import verify_acts_sketch as sketch
    import verify_acts_model_solids as solids
    import verify_acts_model_sweep as sweep
    prefix = [("sketch_create", {"plane": "xy", "name": "EditCorner"}, "ok", None),
              ("sketch_add_geometry", {"sketch_name": "EditCorner", "geometry": [
                  {"kind": "line", "x1": 600, "y1": 0, "x2": 660, "y2": 0}]}, "ok", None)]
    coordinates = {"sketch_add_geometry", "sketch_edit_curve", "find_geometry", "model_construction"}
    context = {"fillet_doc": "scratch", "extent_doc": "scratch", "endpoint_doc": "scratch",
               "extent_block": "Body1", "extent_top": "face", "extent_ordinary": "Body2",
               "extent_distance": "Body3", "endpoint_body": "Body1"}
    def requests(rows):
        return [(tool, args(context) if callable(args) else args)
                for tool, args, _check, _save in rows if tool in coordinates]
    for factory in (sketch._fillet_radius_rows, solids._symmetric_target_rows,
                    sweep._loft_endpoint_rows):
        authored = factory()
        placed = verify_layout._placed(prefix + authored, verify_layout._SLOTS)[len(prefix):]
        assert requests(placed) == requests(authored), factory.__name__


def test_acquired_target_face_feeds_both_symmetric_extent_requests(monkeypatch):
    faces = [{"position": p, "normal": n, "area": area, "handle": "face-" + str(i)}
             for i, (p, n, area) in enumerate([
                 ([10, 10, 10], [0, 0, 1], 400), ([10, 10, 0], [0, 0, -1], 400),
                 ([10, 20, 5], [0, 1, 0], 200), ([20, 10, 5], [1, 0, 0], 200),
                 ([10, 0, 5], [0, -1, 0], 200), ([0, 10, 5], [-1, 0, 0], 200)])]
    payload = {"units": "mm", "match_count": 6, "returned": 6, "matches": faces}
    monkeypatch.setitem(verify_acts_model_solids._RECALL, "extent_top", None)
    rows = verify_acts_model_solids._symmetric_target_rows()
    acquire = next(row for row in rows if row[0] == "find_geometry")
    assert acquire[2](payload) is True
    key, extract = acquire[3]
    context = {"extent_doc": "scratch", key: extract(payload)}
    requests = [args(context) for tool, args, _check, _save in rows if tool == "model_extrude"]
    targets = [r for r in requests if r.get("symmetric") and "to_object" in r]
    assert len(targets) == 2 and all(r["to_object"] == "face-0" for r in targets)


def test_sheet_single_bend_control_requires_the_other_bends_full_geometry(monkeypatch):
    import copy
    import verify_acts_sheet as sheet
    rows = [{"handle": str(i), "kind": "cylinder_face", "position": position, "radius": radius,
             "area": area, "normal": normal, "axis": [0.0, 1.0, -0.0], "occurrence": "BendCoupon:1"}
            for i, (position, radius, area, normal) in enumerate([
                ([54.593573, 20.0, -.346013], 2.0, 83.776, [-.5, 0.0, -.866]),
                ([25.768796, 20.0, 2.22676], 2.0, 125.664, [.7071, 0.0, .7071]),
                ([55.30977, 20.0, .894477], 3.5, 146.608, [.5, 0.0, .866]),
                ([24.813866, 20.0, 1.271831], 3.5, 219.911, [-.7071, 0.0, -.7071])])]
    before = {"units": "mm", "match_count": 4, "returned": 4, "matches": rows}
    monkeypatch.setitem(sheet._RECALL, "sm_first_bend_walls", None)
    monkeypatch.setitem(sheet._RECALL, "sm_array_bends", None)
    assert sheet._capture_bend_witnesses(before) == "0"
    remaining = {"units": "mm", "match_count": 2, "returned": 2, "matches": copy.deepcopy([rows[1], rows[3]])}
    assert sheet._first_bend_preserved(remaining) is True
    remaining["matches"][0]["position"][1] += 1
    with pytest.raises(AssertionError, match="unselected physical bend"):
        sheet._first_bend_preserved(remaining)
    assert sheet._bend_wall_state({"units": "mm", "match_count": 0, "returned": 0, "matches": []}) == []
    assert sheet._bend_wall_state({"units": "mm", "match_count": 0}) is None
    del before["matches"][0]["axis"]
    assert sheet._bend_wall_state(before) is None


def test_sheet_rule_control_rejects_sibling_setting_change_and_unread_census(monkeypatch):
    import copy
    import verify_acts_sheet as sheet
    fields = ("thickness", "bendRadius", "gap", "reliefWidth", "reliefDepth",
              "reliefRemnant", "twoBendReliefSize", "threeBendReliefRadius")
    rows = [{"name": name, "index": i, "scope": "design", "ref": ref, "k_factor": .44,
             "is_used": i < 2, **{field: {
                 "expression": expr if field == "thickness" else "Thickness" + suffix,
                 "value_cm": cm * factor}
                 for field, (suffix, factor) in zip(fields, [
                     ("", 1), ("", 1), ("", 1), ("", 1), (" * 0.5", .5),
                     (" * 2.0", 2), (" * 4.0", 4), ("", 1)])}}
            for i, (name, ref, expr, cm) in enumerate([
                ("Steel (mm)", {"scope": "design", "index": 0}, "1.2 mm", .12),
                ("Steel (mm)", "design:Steel (mm)#2", "2.50 mm", .25),
                ("Steel (mm)#1", {"scope": "design", "index": 2}, "3 mm", .3)])]
    before = {"rules": {"readable": True, "truncated": False, "total": 3, "rules": rows},
              "components": {"walk_complete": True, "truncated": False, "total": 1,
                             "components": [{"component": "RuleSeed", "active_rule": "Steel (mm)",
                                             "bodies": [], "has_flat_pattern": False}]}}
    monkeypatch.setitem(sheet._RECALL, "sm_collision_indices", [0, 1, 2])
    monkeypatch.setitem(sheet._RECALL, "sm_collision_rules", sheet._collision_rule_state(before))
    after = copy.deepcopy(before)
    after["rules"]["rules"][0]["thickness"] = {"expression": "1.7 mm", "value_cm": .17}
    assert sheet._collision_edit_read(0, .17)(after) is True
    broken = copy.deepcopy(after)
    broken["rules"]["rules"][1]["gap"]["value_cm"] = .7
    broken["rules"]["rules"][2]["thickness"] = {"expression": "3.4 mm", "value_cm": .34}
    with pytest.raises(AssertionError, match="all siblings preserved"):
        sheet._collision_edit_read(2, .34)(broken)
    del broken["rules"]["rules"][1]["gap"]["value_cm"]
    assert sheet._collision_rule_state(broken) is None


def test_sheet_component_rule_ref_is_forwarded_and_checked_against_native_assignment(monkeypatch):
    import json
    import verify_acts_sheet as sheet
    ref = {"scope": "design", "index": 1}
    assignment = {"component": "RuleIdentityA", "index": 1, "ref": ref}
    other = {"component": "Component2", "index": 2,
             "ref": {"scope": "design", "index": 2}}
    monkeypatch.setitem(sheet._RECALL, "sm_component_rule_target", assignment)
    monkeypatch.setitem(sheet._RECALL, "sm_component_rule_assignments", [assignment, other])

    assert sheet._collision_component_rule_edit_args(None)["rule"] is ref
    assert sheet._collision_assignment_read("assignments " + json.dumps({"RuleIdentityA": [1], "Component2": [2]})) is True
    with pytest.raises(AssertionError, match="independently read native assignments"):
        sheet._collision_assignment_read("assignments " + json.dumps({"RuleIdentityA": [0, 1], "Component2": [2]}))


def test_sheet_component_rule_unknown_probe_requires_unknown_and_no_active_states():
    import json
    import verify_acts_sheet as sheet
    native = [["Sheet", True, [0]], ["Plain", False, []]]
    rows = [{"component": "Sheet", "active_rule_ref": None, "active_rule_ref_state": "unknown"},
            {"component": "Plain", "active_rule_ref": None, "active_rule_ref_state": "none"}]
    assert sheet._collision_unknown_probe("probe " + json.dumps({
        "before": native, "after": native, "rows": rows})) is True
    with pytest.raises(AssertionError, match="distinguishes unknown from no active rule"):
        sheet._collision_unknown_probe("probe " + json.dumps({
            "before": native, "after": native,
            "rows": [{"component": "Sheet", "active_rule_ref": None,
                     "active_rule_ref_state": "unknown"},
                    {"component": "Wrong", "active_rule_ref": None,
                     "active_rule_ref_state": "none"}]}))


def test_selected_owner_oracle_requires_complete_poses_and_only_the_measured_d_seat(monkeypatch):
    import copy
    parts = []
    for name, x in (("ClaimA", 0), ("ClaimB", 10), ("SelectedC", 20), ("SelectedD", 40)):
        parts.append({"name": name + ":1", "component": name, "full_path": name + ":1",
                      "body_count": 1, "grounded": False, "ground_to_parent": name in ("ClaimA", "SelectedC"),
                      "origin": [x, 0, 0], "x_axis": [1, 0, 0], "y_axis": [0, 1, 0], "z_axis": [0, 0, 1],
                      "bbox_center": [x + 2, 2, 5], "bbox_size": [4, 4, 10], "joints": []})
    before = {"units": "mm", "is_healthy": True, "occurrence_count": 4, "all_occurrence_count": 4,
              "all_occurrences": parts, "occurrences": [{k: v for k, v in r.items() if k != "full_path"} for r in parts],
              "all_occurrences_truncated": False, "occurrences_truncated": False,
              "joints_truncated": False, "relations_truncated": False,
              "relations": {"rigid_groups": [], "motion_links": [], "constraints": []},
              "relation_counts": {"rigid_groups": 0, "motion_links": 0, "constraints": 0}}
    assert verify_acts_motion._selected_owner_state(before) == before
    monkeypatch.setitem(verify_acts_motion._RECALL, "selected_owner_assembly", before)
    after = copy.deepcopy(before)
    after["all_occurrences"][-1].update(origin=[20, 0, -10], bbox_center=[22, 2, -5])
    after["relations"]["constraints"] = [{"name": "Constraint 1", "relationship_count": 1,
                                            "healthy": True, "suppressed": False}]
    after["relation_counts"]["constraints"] = 1
    assert verify_acts_motion._selected_owner_landed(after)
    for defect in ("unread", "truncated", "sibling", "axes", "wrong_seat", "unhealthy"):
        broken = copy.deepcopy(after)
        if defect == "unread":
            broken["all_occurrences"][0]["origin"][0] = None
        elif defect == "truncated":
            del broken["relations_truncated"]
        elif defect == "sibling":
            broken["all_occurrences"][1]["origin"][0] = 11
        elif defect == "axes":
            broken["all_occurrences"][-1]["x_axis"] = [-1, 0, 0]
        elif defect == "wrong_seat":
            broken["all_occurrences"][-1]["origin"] = [20, 0, 10]
        else:
            broken["relations"]["constraints"][0]["healthy"] = False
        with pytest.raises(AssertionError, match="matched C/D owners"):
            verify_acts_motion._selected_owner_landed(broken)


def test_selected_owner_scene_keeps_measured_coordinates_after_full_motion_family():
    authored = verify_acts_motion._selected_owner_rows()
    compiled = verify_program.compile_program(verify_program._RAW_ACT_PROGRAM)["acts"]
    rows = next(rows for _name, _pre, rows, _fallback in compiled
                if any(save and save[0] == "selected_owner_doc" for _tool, _args, _check, save in rows))
    start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == "selected_owner_doc")
    end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
    tools = {"model_create_component", "sketch_add_geometry", "find_geometry"}
    def requests(selected):
        return [(tool, args({}) if callable(args) else args)
                for tool, args, _check, _save in selected if tool in tools]
    assert requests(rows[start:end]) == requests(authored)


def test_joint_and_mesh_remedy_scenes_keep_native_coordinates_after_prior_rows():
    acts = verify_program.compile_program(verify_program._RAW_ACT_PROGRAM)["acts"]
    rows = [row for _name, _pre, narrative, _fallback in acts for row in narrative]
    wanted = {"PinA": 2, "PinB": 2, "MeshSeed": 5}
    found, positions, active = {}, [], False
    for tool, args, _check, save in rows:
        if save and isinstance(save, tuple) and save[0] in ("jf_story", "mr_story"):
            active = True
        if active and tool in ("sketch_add_geometry", "model_create_component"):
            args = args({}) if callable(args) else args
            if tool == "sketch_add_geometry" and args.get("sketch_name") in wanted:
                found[args["sketch_name"]] = args["geometry"]
            if tool == "model_create_component" and args.get("name") in ("JointA", "JointB"):
                positions.append(args["x"])
        if tool == "doc_close":
            active = False
    assert found == {name: [{"kind": "circle", "cx": 0, "cy": 0, "radius": radius}]
                     for name, radius in wanted.items()}
    assert positions == [0, 20]


def test_crossindex_owned_scene_retains_its_measured_witness_coordinates():
    rows = [row for _name, _pre, narrative, _fallback in verify_program.ACTS for row in narrative]
    active, found = False, []
    for tool, args, _check, save in rows:
        if save and isinstance(save, tuple) and save[0] == "ci_story":
            active = True
        if active and tool == "sketch_add_geometry":
            args = args({}) if callable(args) else args
            found.append(args)
        if tool == "doc_close":
            active = False
    assert len(found) == 1 and found[0]["sketch_name"] == "Witness"
    assert found[0]["geometry"] == [{"kind": "rectangle", "x1": 100, "y1": 0, "x2": 120, "y2": 20}]


def test_origin_consumers_owned_scene_retains_its_measured_witness_coordinates():
    rows = [row for _name, _pre, narrative, _fallback in verify_program.ACTS for row in narrative]
    active, found = False, []
    for tool, args, _check, save in rows:
        if save and isinstance(save, tuple) and save[0] == "oc_story":
            active = True
        if active and tool == "sketch_add_geometry":
            found.append(args({}) if callable(args) else args)
        if tool == "doc_close":
            active = False
    assert len(found) == 1 and found[0]["sketch_name"] == "Witness"
    assert found[0]["geometry"] == [{"kind": "rectangle", "x1": 100, "y1": 0, "x2": 120, "y2": 20}]
    creations = [(args({}), check) for tool, args, check, _save
                 in verify_acts_motion._origin_consumer_rows() if tool == "model_create_component"]
    assert len(creations) == 2
    for args, check in creations:
        reply = {"occurrence": args["name"] + ":1", "full_path": args["name"] + ":1", "activated": False}
        assert args["activate"] is False and check(reply)
        with pytest.raises(AssertionError, match="not activated"):
            check(dict(reply, activated=True))


def test_edge_and_signed_extent_scenes_keep_original_coordinates_in_complete_family():
    compiled = verify_program.compile_program(verify_program._RAW_ACT_PROGRAM)["acts"]
    for duplicate, tag in ((True, "distinct_edge"), (False, "signed_all")):
        authored = verify_acts_model_solids._edge_extent_rows(duplicate)
        context = {tag + "_" + key: value for key, value in
                   (("home", "home"), ("doc", "scratch"), ("stock", "Body1"),
                    ("witness", "Body2"), ("edge", "edge"), ("feature", "Feature"), ("wall", "wall"))}
        rows = next(rows for _name, _pre, rows, _fallback in compiled
                    if any(save and save[0] == tag + "_doc" for _tool, _args, _check, save in rows))
        start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == tag + "_doc")
        end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
        def requests(selected):
            return [(tool, args(context) if callable(args) else args)
                    for tool, args, _check, _save in selected
                    if tool in {"sketch_add_geometry", "find_geometry", "model_fillet", "model_extrude"}]
        assert requests(rows[start:end]) == requests(authored), tag


def test_signed_extent_oracle_rejects_wrong_side_even_with_correct_removed_volume():
    rows = verify_acts_model_solids._edge_extent_rows(False)
    checks = [check for tool, _args, check, _save in rows
              if tool == "find_geometry" and callable(check) and check.__name__ == "side"]
    def payload(x, z):
        return {"units": "mm", "returned": 1, "match_count": 1, "matches": [
            {"handle": "wall", "kind": "cylinder_face", "radius": .5, "area": 15.708,
             "normal": [0, 1, 0], "position": [x, 4, z]}]}
    assert len(checks) == 3
    assert checks[1](payload(5, -2.5)) is True
    with pytest.raises(AssertionError, match="requested side"):
        checks[1](payload(5, 2.5))
    assert checks[2](payload(8, 0)) is True
    assert verify_acts_model_solids._edge_extent_geometry({"units": "mm", "returned": 0,
        "match_count": 0, "matches": []}) is None


@pytest.mark.parametrize("kind,missing", [("planar_face", "area"), ("cylinder_face", "radius"),
                                         ("line_edge", "length")])
def test_edge_extent_census_refuses_missing_measured_geometry(kind, missing):
    row = {"handle": "geometry", "kind": kind, "position": [5, 4, -2.5],
           "area": 15.708, "radius": .5, "length": 10, "normal": [1, 0, 0]}
    payload = {"units": "mm", "returned": 1, "match_count": 1, "matches": [row]}
    assert verify_acts_model_solids._edge_extent_geometry(payload) is not None
    del row[missing]
    assert verify_acts_model_solids._edge_extent_geometry(payload) is None


def test_placed_extent_refusal_scene_keeps_recorded_pose_and_local_requests_in_full_family():
    rows = [row for _name, _pre, narrative, _fallback in verify_program.ACTS for row in narrative]
    authored = verify_acts_model_solids._placed_extent_refusal_rows()
    context = {"placed_extent_doc": "scratch", "placed_extent_home": "home",
               "placed_extent_bodies": {"stock": "placed-body", "witness": "root-body"}}
    start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == "placed_extent_home")
    end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
    wanted = {"sketch_add_geometry", "model_create_component", "model_extrude", "find_geometry", "sketch_get"}
    def requests(selected):
        return [(tool, args(context) if callable(args) else args) for tool, args, _check, _save in selected if tool in wanted]
    assert requests(rows[start:end]) == requests(authored)
    cuts = [args for tool, args in requests(authored) if tool == "model_extrude" and args.get("operation") == "cut"]
    assert [(r["distance"], r["symmetric"], "target_bodies" in r) for r in cuts if r["extent"] == "through_all"] == [
        (1, False, True), (-1, False, True), (1, True, True)]
    assert [r["distance"] for r in cuts if r["extent"] == "distance"] == [10]
    assert all(r["component"] == "PlacedStock:1" for r in cuts)


def test_unread_timeline_owned_scene_keeps_local_cube_and_read_order_in_full_family():
    rows = [row for _name, _pre, narrative, _fallback in verify_program.ACTS for row in narrative]
    context = {"timeline_home": "home", "timeline_doc": "scratch"}
    start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == "timeline_home")
    end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
    wanted = {"sketch_add_geometry", "model_extrude", "view_set", "workspace_orient", "model_base_feature", "design_set_mode"}
    def requests(selected):
        return [(tool, args(context) if callable(args) else args) for tool, args, _check, _save in selected if tool in wanted]
    authored = verify_acts_doc._timeline_health_rows()
    assert requests(rows[start:end]) == requests(authored)
    assert [tool for tool, _args in requests(authored)] == [
        "sketch_add_geometry", "model_extrude", "view_set", "workspace_orient", "model_base_feature",
        "workspace_orient", "model_base_feature", "workspace_orient", "design_set_mode", "workspace_orient"]
    cameras = [args for tool, args in requests(rows[start:end]) if tool == "view_set"]
    assert cameras == [{"action": "orient", "orientation": "iso-top-right", "fit": True,
                        "expect_document": "scratch"}]


def test_setup_preflight_scene_keeps_owned_source_witness_and_requests_in_full_family():
    rows = [row for _name, _pre, narrative, _fallback in verify_program.ACTS for row in narrative]
    context = {"setup_preflight_home": "home", "setup_preflight_doc": "scratch",
               "setup_unlock_before": {"expression": "false"},
               "setup_stock_before": {"job_stockOffsetSides": "captured sides", "job_stockOffsetTop": "captured top"}}
    start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == "setup_preflight_home")
    end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
    wanted = {"model_create_component", "sketch_add_geometry", "model_extrude", "view_set",
              "cam_create_setup", "cam_edit_setup"}
    def requests(selected):
        return [(tool, args(context) if callable(args) else args) for tool, args, _check, _save in selected if tool in wanted]
    authored = verify_acts_cam._setup_preflight_rows()
    assert requests(rows[start:end]) == requests(authored)
    boxes = [args["geometry"] for tool, args in requests(authored) if tool == "sketch_add_geometry"]
    assert boxes == [[{"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}],
                     [{"kind": "rectangle", "x1": 40, "y1": 0, "x2": 50, "y2": 10}]]
    assert [args for tool, args in requests(authored) if tool == "view_set"] == [
        {"action": "orient", "orientation": "iso-top-right", "fit": True, "expect_document": "scratch"}]
    edits = [args for tool, args in requests(authored) if tool == "cam_edit_setup"]
    assert edits[1] == {"setup": "SetupB", "stock_mode": "relative_box", "expect_document": "scratch"}
    assert edits[-2:] == [
        {"setup": "SetupB", "parameters": {"job_stockOffsetSides": "2 mm", "job_stockOffsetTop": "2 mm",
                                           "wcs_origin_boxPoint": "NoSuchProbeBoxPoint"},
         "expect_document": "scratch"},
        {"setup": "SetupB", "parameters": context["setup_stock_before"], "expect_document": "scratch"}]


def test_midpoint_preflight_scene_keeps_original_source_and_read_order_in_full_family():
    rows = [row for _name, _pre, narrative, _fallback in verify_program.ACTS for row in narrative]
    context = {"pattern_home": "home", "pattern_doc": "scratch", "pattern_ids": ["line:0", "circle:0"]}
    start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == "pattern_home")
    end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
    wanted = {"sketch_create", "sketch_add_geometry", "sketch_constrain", "sketch_get", "design_get"}
    def requests(selected):
        return [(tool, args(context) if callable(args) else args) for tool, args, _check, _save in selected if tool in wanted]
    authored = verify_acts_sketch._pattern_preflight_rows()
    assert requests(rows[start:end]) == requests(authored)
    geometry = [args["geometry"] for tool, args in requests(authored) if tool == "sketch_add_geometry"]
    assert geometry[0] == [{"kind": "line", "x1": 0, "y1": 0, "x2": 20, "y2": 0},
                           {"kind": "circle", "cx": 40, "cy": 0, "radius": 5}]
    constraints = [args["constraints"][0] for tool, args in requests(authored) if tool == "sketch_constrain"]
    assert [r["quantity"] for r in constraints] == [1, 3, 3, 3, 3]
    assert [r["entities"] for r in constraints] == ["circle:0", "circle:0", "circle:99", "", "circle:0"]
    assert constraints[1]["suppressed"] == [True] and "suppressed" not in constraints[-1]


def test_joint_preflight_scene_keeps_measured_local_pair_and_typed_public_read_order():
    rows = [row for _name, _pre, narrative, _fallback in verify_program.ACTS for row in narrative]
    context = {"joint_preflight_home": "home", "joint_preflight_doc": "scratch"}
    start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == "joint_preflight_home")
    end = next(i for i in range(start, len(rows)) if rows[i][0] == "doc_close")
    wanted = {"model_create_component", "sketch_add_geometry", "joint_create_as_built", "joint_edit",
              "assembly_get", "design_get", "find_geometry", "model_inspect", "view_set"}
    def requests(selected):
        return [(tool, args(context) if callable(args) else args) for tool, args, _check, _save in selected if tool in wanted]
    authored = verify_acts_motion._joint_preflight_rows()
    assert requests(rows[start:end + 2]) == requests(authored)
    shapes = [a["geometry"] for t, a in requests(authored) if t == "sketch_add_geometry"]
    assert shapes == [[{"kind": "rectangle", "x1": 0, "y1": 0, "x2": 4, "y2": 4}]] * 2
    edits = [a for t, a in requests(authored) if t == "joint_edit"]
    assert [(a.get("joint_type"), a.get("offset"), a.get("angle")) for a in edits[:4]] == [
        ("slider", 5, None), ("slider", None, 30), ("slider", None, None), ("revolute", None, None)]
    assert edits[-2:] == [{"joint_name": "AB", "min_deg": -15, "expect_document": "scratch"},
                         {"joint_name": "AB", "max_deg": 15, "expect_document": "scratch"}]
    assert all(t != "sys_execute_script" for t, _a, _c, _s in authored)
    assert all(authored[i + 1][0] == "assembly_get" and authored[i + 2][0] == "design_get"
               for i, row in enumerate(authored) if row[0] == "joint_edit")


def test_joint_preflight_material_accepts_recorded_body_rows_without_per_body_area():
    payload = {
        "target": "whole design", "units": "mm", "frame": "world axes (axis-aligned)",
        "min_point": {"x": 0, "y": 0, "z": 0}, "max_point": {"x": 24, "y": 4, "z": 10},
        "mass": {"volume": 320.0, "area": 384.0, "mass_kg": 0.002512,
                 "per_body_count": 2, "per_body_truncated": False, "per_body": [
                     {"body": "Body1", "occurrence": "A:1", "is_solid": True,
                      "mass_kg": 0.001256, "volume": 160.0, "lump_count": 1},
                     {"body": "Body1", "occurrence": "B:1", "is_solid": True,
                      "mass_kg": 0.001256, "volume": 160.0, "lump_count": 1}]} }
    state = verify_acts_motion._joint_preflight_material(payload)
    assert state is not None and state["bodies"] == payload["mass"]["per_body"]
    payload["mass"]["area"] = 383
    assert verify_acts_motion._joint_preflight_material(payload) is None
    payload["mass"]["area"] = 384
    payload["mass"]["per_body"][1]["volume"] = 159
    assert verify_acts_motion._joint_preflight_material(payload) is None


def test_sheet_serial_scene_keeps_local_coupons_and_typed_group_recovery_in_full_family():
    rows = [row for _name, _pre, narrative, _fallback in verify_program.ACTS for row in narrative]
    ctx = {'serial_home_handle': 'home', 'serial_doc': 'scratch', 'serial_witness': 'witness',
           'serial_rim': 'rim', 'serial_stationary': 'top', 'serial_other_face': 'other', 'serial_unfold': 'Unfold1'}
    start = next(i for i, row in enumerate(rows) if row[3] and row[3][0] == 'serial_home_handle')
    end = next(i for i in range(start, len(rows)) if rows[i][0] == 'doc_close')
    authored = verify_acts_sheet._sheet_serial_rows()
    wanted = {'sketch_add_geometry', 'model_create_component', 'sheet_create_flange', 'sheet_create_unfold',
              'sheet_create_refold', 'design_edit_timeline', 'view_set', 'assembly_get', 'find_geometry'}
    def requests(selected):
        return [(t, a(ctx) if callable(a) else a) for t, a, _c, _s in selected if t in wanted]
    assert requests(rows[start:end]) == requests(authored)
    boxes = [a['geometry'] for t, a in requests(authored) if t == 'sketch_add_geometry']
    assert boxes == [[{'kind': 'rectangle', 'x1': 220, 'y1': 0, 'x2': 240, 'y2': 20}],
                     [{'kind': 'rectangle', 'x1': 0, 'y1': 0, 'x2': 80, 'y2': 40}],
                     [{'kind': 'rectangle', 'x1': 100, 'y1': 0, 'x2': 180, 'y2': 40}]]
    assert [(a['feature'], a['collapsed']) for t, a in requests(authored)
            if t == 'design_edit_timeline' and a['action'] == 'group_state'] == [
        ('Group1', True), ('Group1', False), ('Group1', True), ('Group2', True),
        ('Group1', False), ('Group2', False)]
    assert [a['feature'] for t, a in requests(authored)
            if t == 'design_edit_timeline' and a['action'] == 'suppress'] == ['Unfold1', 'SerialA/Refold1']
    assert [a['feature'] for t, a in requests(authored)
            if t == 'design_edit_timeline' and a['action'] == 'ungroup'] == ['Group1']
    assert [a['unfold'] for t, a in requests(authored) if t == 'sheet_create_refold'] == [
        'SerialA/Unfold1', 'SerialA/Unfold1', 'SerialB/Unfold1', 'SerialA/Unfold1']
    first_sketch = next(i for i, row in enumerate(authored) if row[0] == 'sketch_create')
    assert first_sketch > 0
    assert authored[first_sketch - 1][:2] == ('design_activate_component', {'occurrence': 'root'})
    assert all(t != 'sys_execute_script' for t, _a, _c, _s in authored)


def test_serial_sheet_pose_admission_rejects_finite_nonidentity_basis():
    rows = [{'name': name + ':1', 'component': name, 'body_count': 1, 'origin': [0, 0, 0],
             'x_axis': [1, 0, 0], 'y_axis': [0, 1, 0], 'z_axis': [0, 0, 1],
             'grounded': False, 'ground_to_parent': False} for name in ('SerialA', 'SerialB')]
    value = {'units': 'mm', 'occurrence_count': 2, 'occurrences_truncated': False, 'occurrences': rows}
    assert verify_acts_sheet._serial_sheet_poses(value) is not None
    rows[1]['x_axis'] = [0, 1, 0]
    assert verify_acts_sheet._serial_sheet_poses(value) is None


def test_serial_sheet_history_rejects_missing_or_failed_summary(monkeypatch):
    old = {'index': 0, 'name': 'Base1', 'type': 'FlangeFeature'}
    fresh = {'index': 1, 'name': 'Unfold1', 'type': 'UnfoldFeature', 'component': 'SerialA'}
    before = {'timeline': {'timeline': [old]}}
    current = {'timeline': {'timeline': [old, fresh], 'summary': {'states': {'healthy': 2}, 'exceptions': []}}}
    monkeypatch.setitem(verify_acts_sheet._RECALL, 'serial_stage_design', before)
    monkeypatch.setattr(verify_acts_sheet, '_retire_design_state', lambda p: p)
    check = verify_acts_sheet._serial_sheet_history('SerialA', 'UnfoldFeature')
    assert check(current)
    for states in (None, {'healthy': 1, 'unknown': 1}):
        monkeypatch.setitem(verify_acts_sheet._RECALL, 'serial_stage_design', before)
        current['timeline']['summary']['states'] = states
        with pytest.raises(AssertionError):
            check(current)



def test_sweep_scope_edit_reads_the_actual_tool_payload(monkeypatch):
    monkeypatch.setitem(verify_acts_model_sweep._RECALL, "sweep_scope_identity_Guide", "identity")
    monkeypatch.setitem(verify_acts_model_sweep._RECALL, "sweep_scope_guide_original", "old-rail")
    check = verify_acts_model_sweep._sweep_scope_edit("guide_path", "replace", "Guide")
    payload = {
        "edited": True, "action": "guide_path", "same_feature": True,
        "definition_matches": True, "geometry_changed": True, "marker_restored": True,
        "new_timeline_errors": [], "new_timeline_warnings": [], "outside_body_changes": [],
        "participant_scope_preserved": True,
        "definition_before": {"guide_path_curves": 1, "guide_path_signature": "old-rail"},
        "definition_after": {"guide_path_curves": 1, "guide_path_signature": "new-rail"},
    }
    assert check(payload) is not None
    payload["edited"] = False
    with pytest.raises(AssertionError):
        check(payload)


def test_sweep_scope_definition_qualifies_rolled_timeline_without_summary_claim(monkeypatch):
    monkeypatch.setitem(verify_acts_model_sweep._RECALL, "sweep_scope_identity_Guide", None)
    rows = [
        {"index": 0, "name": "Seed", "type": "ExtrudeFeature"},
        {"index": 1, "name": "Control", "type": "ExtrudeFeature"},
        {"index": 2, "name": "Guide", "type": "SweepFeature", "is_rolled_back": True},
        {"index": 3, "is_rolled_back": True},
    ]
    payload = {
        "definition": {"feature": "Guide", "component": "Root", "type": "SweepFeature",
                       "timeline_index": 2, "operation": "new", "is_solid": True,
                       "orientation_name": "perpendicular", "path_count": 1,
                       "path_truncated": False},
        "timeline": {"marker_position": 2, "count": 4, "returned": 4,
                     "timeline": rows},
    }
    assert verify_acts_model_sweep._sweep_scope_definition("Guide", "new")(payload) is not None
    unavailable = dict(payload, definition=dict(payload["definition"], orientation=None,
        orientation_name=None, unavailable={"orientation": "2 : InternalValidationError : false"}))
    with pytest.raises(AssertionError):
        verify_acts_model_sweep._sweep_scope_definition("Guide", "new")(unavailable)
    guided = dict(unavailable, definition=dict(unavailable["definition"], feature="R7Sweep"),
        timeline=dict(payload["timeline"], timeline=[dict(row, name="R7Sweep")
            if row.get("name") == "Guide" else row for row in rows]))
    assert verify_acts_model_sweep._sweep_scope_definition("R7Sweep", "new")(guided)
    unknown = dict(guided, definition=dict(guided["definition"], unavailable={}))
    with pytest.raises(AssertionError):
        verify_acts_model_sweep._sweep_scope_definition("R7Sweep", "new")(unknown)
    for broken in (dict(rows[0], is_rolled_back=None),
                   dict(rows[2], is_rolled_back=False)):
        changed = dict(payload)
        changed["timeline"] = dict(payload["timeline"], timeline=list(rows))
        changed["timeline"]["timeline"][broken["index"]] = broken
        with pytest.raises(AssertionError):
            verify_acts_model_sweep._sweep_scope_definition("Guide", "new")(changed)


def test_sweep_scope_end_health_reads_every_row():
    rows = [{"index": 0, "name": "Seed", "type": "ExtrudeFeature"},
            {"index": 1, "name": "Sweep", "type": "SweepFeature"}]
    check = verify_acts_model_sweep._sweep_scope_end_health()
    assert check({"timeline": {"marker_position": 2, "count": 2, "returned": 2,
                               "summary": {"states": {"healthy": 2}, "exceptions": []},
                               "timeline": rows}}) is not None
    with pytest.raises(AssertionError):
        check({"timeline": {"marker_position": 2, "count": 2, "returned": 2,
                             "summary": {"states": {"healthy": 2}, "exceptions": []},
                             "timeline": [rows[0], dict(rows[1], is_rolled_back=True)]}})
    with pytest.raises(AssertionError):
        check({"timeline": {"marker_position": 2, "count": 2, "returned": 2,
                             "summary": {"states": {"healthy": 1, "rolled_back": 1},
                                         "exceptions": []},
                             "timeline": rows}})

import verify_acts_feature_edit as feature_edit  # noqa: E402


def test_feature_edit_end_marker_requires_complete_explicit_health_summary():
    rows = [{"index": 0, "name": "Seed", "type": "ExtrudeFeature"},
            {"index": 1, "name": "Revolve", "type": "RevolveFeature"}]
    complete = {"count": 2, "returned": 2, "marker_position": 2, "timeline": rows,
                "summary": {"states": {"healthy": 2}, "exceptions": []}}
    assert feature_edit._marker_end({"timeline": complete}) is True

    bad_timelines = [
        {k: v for k, v in complete.items() if k != "summary"},
        {**complete, "summary": {"states": {"healthy": 2}}},
        {**complete, "summary": {"states": {"healthy": 1}, "exceptions": []}},
        {**complete, "summary": {"states": {"healthy": 1, "warning": 1}, "exceptions": []}},
        {**complete, "summary": {"states": {"healthy": 2}, "exceptions": [{"name": "Revolve"}]}},
        {**complete, "truncated": True},
        {**complete, "returned": 1},
    ]
    for timeline in bad_timelines:
        with pytest.raises(AssertionError):
            feature_edit._marker_end({"timeline": timeline})


def test_feature_edit_reference_change_preserves_real_control_geometry(monkeypatch):
    key = "mirror_reference_test"
    before = {
        "feature": "Mirror1", "component": "FeatureEditBench", "type": "MirrorFeature",
        "timeline_index": 4, "feature_address": "FeatureEditBench/Mirror1",
        "mirror_plane": {"handle": "plane-a", "kind": "construction_plane", "name": "PlaneA",
                         "owner": {"component": "FeatureEditBench", "occurrence": None},
                         "geometry": {"frame": "world", "origin_cm": [0.5, 0.0, 0.0],
                                      "normal": [1.0, 0.0, 0.0]}},
        "input_entities": [{"handle": "body-a", "kind": "body", "name": "SeedBody",
                            "owner": {"component": "FeatureEditBench", "occurrence": None},
                            "geometry": {"world_cm": None, "area": 12.0, "volume": 1.0,
                                         "center_cm": [2.0, 0.5, 0.5]}}],
        "supported_edits": [], "unavailable": {},
    }
    monkeypatch.setitem(feature_edit._RECALL, key, before)
    changed = {
        **before,
        "mirror_plane": {"handle": "plane-b", "kind": "construction_plane", "name": "PlaneB",
                         "owner": {"component": "FeatureEditBench", "occurrence": None},
                         "geometry": {"frame": "world", "origin_cm": [0.0, 0.0, 0.0],
                                      "normal": [1.0, 0.0, 0.0]}},
    }
    assert feature_edit._definition_after(key, "mirror_plane")({"definition": changed}) is True

    changed_control = {**changed, "input_entities": [{**before["input_entities"][0],
        "geometry": {**before["input_entities"][0]["geometry"], "center_cm": [3.0, 0.5, 0.5]}}]}
    with pytest.raises(AssertionError):
        feature_edit._definition_after(key, "mirror_plane")({"definition": changed_control})


def test_surface_fixture_and_manual_refusal_use_run_steps_payload_contract(monkeypatch):
    features = [
        {"name": "EditStitch", "type": "StitchFeature"},
        {"name": "EditUnstitch", "type": "UnstitchFeature"},
        {"name": "UntrimInternal", "type": "UntrimFeature"},
        {"name": "UntrimExternal", "type": "UntrimFeature"},
        {"name": "UntrimManual", "type": "UntrimFeature"},
        {"name": "EditDeleteHeal", "type": "DeleteFaceFeature"},
        {"name": "EditDeleteSurface", "type": "SurfaceDeleteFaceFeature"},
    ]
    assert surface_boundaries._fixture({
        "fixture": "surface-boundary-edit-v1", "control": "SurfaceBoundaryControl",
        "features": features,
    }) is True
    with pytest.raises(AssertionError):
        surface_boundaries._fixture({
            "isError": False, "content": [{"text": '{"fixture":"surface-boundary-edit-v1"}'}]
        })

    refusal = next(expect for tool, _args, expect, _save in surface_boundaries.surface_boundary_edit_rows()
                   if tool == "model_edit_feature" and isinstance(expect, verify_core._Refusal))
    assert refusal.missing("Feature edit refused: the existing manual Untrim loop selection "
                           "cannot be read for exact restoration.") == []
    key = "manual_untrim_payload"
    monkeypatch.setitem(surface_boundaries._RECALL, key + "_rolled_index", 4)
    monkeypatch.setitem(surface_boundaries._RECALL, key + "_baseline", None)
    manual = {"definition": {"type": "UntrimFeature", "component": "(Unsaved)",
        "feature_address": "UntrimManual", "timeline_index": 4, "loop_type": "manual",
        "faces_to_untrim": [{"handle": "manual-face", "kind": "face"}], "unavailable": {}}}
    assert surface_boundaries._baseline(key, "UntrimFeature", "faces_to_untrim")(manual) is True

def test_surface_body_inspect_shape_and_all_writes_are_document_pinned(monkeypatch):
    body = {
        "target": "DeleteSurfaceBody", "kind": "body", "units": "mm",
        "min_point": {"x": 0.0, "y": 1400.0, "z": 0.0},
        "max_point": {"x": 20.0, "y": 1420.0, "z": 10.0},
        "lump_count": 1,
        "mass": {"target": "DeleteSurfaceBody", "units": "mm", "accuracy_used": "very_high",
                 "area": 200.0, "volume": 0.0, "center_of_mass": [10.0, 1410.0, 5.0],
                 "per_body": [], "per_body_count": 0, "per_body_truncated": False},
    }
    state = surface_boundaries._metric(body)
    assert state is not None and state["kind"] == "body" and state["area"] == 200.0
    assert state["lump_count"] == 1
    body["mass"].pop("center_of_mass")
    assert surface_boundaries._metric(body) is None
    monkeypatch.setitem(surface_boundaries._RECALL, "candidate_fixture_expected", None)
    monkeypatch.setitem(surface_boundaries._RECALL, "stitch_candidate_expected", None)
    monkeypatch.setitem(surface_boundaries._RECALL, "candidate_fixture_baseline", {"component": "(Unsaved)"})
    candidate = surface_boundaries._candidate("planar_face", [1.0, 2.0, 3.0],
                                               "candidate_fixture", "candidate_fixture_baseline")
    assert candidate({"returned": 1, "match_count": 1, "matches": [
        {"handle": "face-handle", "kind": "planar_face", "area": 2.0,
         "normal": [0, 0, 1], "position": [1.1, 2.0, 3.0]}]}) is True
    with pytest.raises(AssertionError):
        candidate({"returned": 1, "match_count": 1, "matches": [
            {"handle": "edge-handle", "kind": "edge", "area": 2.0,
             "position": [1.0, 2.0, 3.0]}]})
    tree_payload = {"tree": {"root": "(Unsaved)", "truncated": False,
        "children_truncated": False, "root_bodies": [
            {"name": "StitchC", "handle": "body-token", "is_solid": False, "visible": True}]}}
    assert surface_boundaries._surface_body_candidate("StitchC", "stitch_candidate")(tree_payload) is True
    for field, wrong in (("root_bodies_truncated", True), ("truncated", True),
                         ("children_truncated", True)):
        tree_payload["tree"][field] = wrong
        with pytest.raises(AssertionError):
            surface_boundaries._surface_body_candidate("StitchC", "stitch_candidate")(tree_payload)
        tree_payload["tree"][field] = False
    tree_payload["tree"]["root_bodies"][0]["is_solid"] = True
    with pytest.raises(AssertionError):
        surface_boundaries._surface_body_candidate("StitchC", "stitch_candidate")(tree_payload)

    rows = surface_boundaries.surface_boundary_edit_rows()
    context = {"surface_home": "session:home", "surface_doc": "session:scratch"}
    for _tool, _args, _expect, saved in rows:
        if saved and saved[0] not in context:
            context[saved[0]] = "session:fixture"
    writes = {"doc_new", "sys_execute_script", "design_edit_timeline", "model_edit_feature",
              "doc_activate", "doc_close"}
    authored = [(tool, args(context) if callable(args) else args)
                for tool, args, _expect, _saved in rows if tool in writes]
    assert authored and all(args.get("expect_document") ==
                            ("session:home" if tool in ("doc_new", "doc_close") else "session:scratch")
                            for tool, args in authored)
    assert next(args for tool, args in authored if tool == "doc_new")["expect_document"] == "session:home"
    assert not any(tool == "find_geometry" and not callable(args) and args.get("kind") == "body"
                   for tool, args, _expect, _save in rows)
    stitch_body_read = next(args for tool, args, _expect, _save in rows
                            if tool == "design_get" and not callable(args) and args.get("tree_bodies"))
    assert stitch_body_read["tree_handles"] is True and stitch_body_read["include"] == ["tree"]


def test_surface_handle_checks_total_candidates_and_exact_returned_row(monkeypatch):
    monkeypatch.setitem(verify_acts_surface_edit._RECALL,
                        "surface_edit_root_component", "RootComponent")
    check = verify_acts_surface_edit._face_handle("surface_face_test", [10, 300, 5])
    row = {"kind": "planar_face", "handle": "face-handle", "position": [10, 300, 5],
           "area": 20, "normal": [0, 0, 1], "occurrence": None}
    unrelated = {"kind": "planar_face", "handle": "other-face", "position": [0, 0, 0],
                 "area": 50, "normal": [0, 1, 0], "occurrence": None}
    payload = {"units": "mm", "target": "whole design", "match_count": 2,
               "returned": 2, "matches": [unrelated, row]}
    assert check(payload) is not None
    key, save = verify_acts_surface_edit._geometry_save(
        "surface_face_test", "planar_face", [10, 300, 5])
    assert key == "surface_face_test" and save(payload) == "face-handle"
    with pytest.raises(AssertionError):
        check({**payload, "match_count": 3})
    edge_check = verify_acts_surface_edit._edge_handle("edge_test", [20, 610, 0])
    edge_row = {"kind": "line_edge", "handle": "target-edge", "position": [20, 610, 0],
                "length": 2, "direction": [0, 1, 0]}
    edge_payload = {"units": "mm", "target": "whole design", "match_count": 2,
                    "returned": 2, "matches": [unrelated, edge_row]}
    assert edge_check(edge_payload) is not None
    _key, edge_save = verify_acts_surface_edit._geometry_save(
        "edge_test", "line_edge", [20, 610, 0])
    assert edge_save(edge_payload) == "target-edge"


def test_surface_publication_saves_run_against_their_actual_payload_shapes():
    rows = verify_acts_surface_edit.surface_feature_edit_rows()
    source_scans = [args for tool, args, _check, _save in rows
                    if tool == "find_geometry" and isinstance(args, dict)
                    and args.get("kind") in {"planar_face", "line_edge"}
                    and args.get("target") == ""]
    assert len(source_scans) == 12
    assert all(args.get("max_results") == 100 for args in source_scans)
    bodies = [{"name": "SFE_ReverseA", "handle": "body:a"},
              {"name": "SFE_ReverseB", "handle": "body:b"}]
    payloads = {
        "doc_get": {"active": {"document_handle": "session:home"},
                    "open_documents": [{"is_active": True,
                                        "document_handle": "session:home"}]},
        "doc_new": {"document_handle": "session:scratch"},
        "sys_execute_script": {"timeline_count": 17},
        "design_get": {"tree": {"root": "RootComponent", "truncated": False,
                                  "child_count": 0, "children_truncated": False,
                                  "root_bodies_truncated": False,
                                  "root_bodies": bodies}},
    }
    saved = {}
    for tool, _args, _check, save in rows:
        if save is not None:
            key, extract = save
            if tool == "find_geometry":
                _key, args = key, _args
                kind, position = args["kind"], args["nearest_to"]
                row = {"kind": kind, "handle": key + "-handle", "position": position}
                if kind == "planar_face":
                    row.update(area=20, normal=[0, 0, 1], occurrence=None)
                payload = {"target": "whole design", "units": "mm", "match_count": 1,
                           "returned": 1, "matches": [row]}
                if kind == "sketch_circle":
                    payload = {"matches": [{"handle": key + "-handle"}]}
            else:
                assert tool in payloads
                payload = payloads[tool]
            saved[key] = extract(payload)
    assert saved["surface_edit_home"] == "session:home"
    assert saved["surface_edit_doc"] == "session:scratch"
    assert saved["surface_edit_timeline_count"] == 17
    assert saved["surface_edit_root_component"] == "RootComponent"
    assert verify_acts_surface_edit._root_component(payloads["design_get"]) is not None
    assert saved["surface_edit_reverse_a"] == "body:a"
    assert saved["surface_edit_reverse_b"] == "body:b"


def test_surface_sketch_circle_acquisition_requires_exact_circle_id():
    check = verify_acts_surface_edit._sketch_circle_handle(
        "circle-test", "SFE_Patch_Sk", "circle:1", [40, 200, 0], 15)
    row = {"kind": "sketch_circle", "sketch": "SFE_Patch_Sk", "id": "circle:1",
           "radius": 15, "center": [40, 200, 0], "position": [40, 200, 0],
           "handle": "circle-handle"}
    payload = {"units": "mm", "match_count": 1, "returned": 1, "matches": [row]}
    assert check(payload) is not None
    with pytest.raises(AssertionError):
        check({**payload, "matches": [{**row, "id": "circle:0"}]})


@pytest.mark.parametrize(("feature", "field", "prefix", "feature_type", "point_a", "point_b"), [
    ("SFE_Offset", "entities", "surface_edit_offset", "OffsetFeature",
     [10, 300, 5], [20, 310, 5]),
    ("SFE_Thicken", "input_faces", "surface_edit_thicken", "ThickenFeature",
     [10, 900, 5], [20, 910, 5]),
])
def test_surface_face_lists_pin_acquired_area_normal_owner_and_original(
        monkeypatch, feature, field, prefix, feature_type, point_a, point_b):
    details = verify_acts_surface_edit
    monkeypatch.setitem(details._RECALL, "surface_edit_root_component", "RootComponent")
    for suffix, point, normal in (("face_a", point_a, [0, 0, 1]),
                                  ("face_b", point_b, [1, 0, 0])):
        key = prefix + "_" + suffix
        check = details._face_handle(key, point)
        row = {"kind": "planar_face", "handle": key + "-token", "position": point,
               "area": 20, "normal": normal, "occurrence": None}
        assert check({"target": "whole design", "units": "mm", "match_count": 1, "returned": 1,
                      "matches": [row]}) is not None
    first = {"handle": "original-token", "kind": "face", "name": "Face",
             "owner": {"component": "RootComponent", "occurrence": None},
             "geometry": {"area": .2, "normal": [0, 0, 1],
                          "point_cm": [8, 90, 5], "frame": "entity_context"}}
    second = {"handle": "alternate-token", "kind": "face", "name": "Face",
              "owner": {"component": "RootComponent", "occurrence": None},
              "geometry": {"area": .2, "normal": [1, 0, 0],
                           "point_cm": [2, 91, 5], "frame": "entity_context"}}
    timeline = [{"index": 0, "name": feature, "type": feature_type}]
    def payload(selected):
        return {"definition": {"type": feature_type, "feature_address": feature,
                                "timeline_index": 0, field: selected, "unavailable": {}},
                "timeline": {"marker_position": 0, "count": 1, "returned": 1,
                             "timeline": timeline}}
    assert details._definition(feature, field, "before", 1)(payload([first]))
    check_after = details._definition(feature, field, "after", 2,
                                      (prefix + "_face_a", prefix + "_face_b"))
    assert check_after(payload([first, second]))
    wrong_normal = {**second, "geometry": {**second["geometry"], "normal": [0, 0, 1]}}
    with pytest.raises(AssertionError):
        check_after(payload([first, wrong_normal]))
    with pytest.raises(AssertionError):
        check_after(payload(None))


def test_surface_thicken_volume_rejects_wrong_depth_even_when_area_is_equal(monkeypatch):
    monkeypatch.setitem(verify_acts_surface_edit._RECALL,
                        "surface_edit_mass_thicken-volume", {
                            "area": 1000, "volume": 500, "center": (10, 90, 5),
                            "center_of_mass": (10, 90, 5), "min_point": (0, 90, 0),
                            "max_point": (20, 92, 10), "body_count": 1,
                            "per_body_count": 1})
    check = verify_acts_surface_edit._mass_state("thicken-volume", "changed", True,
                                                 {"volume": 840})
    def payload(volume):
        return {"mass": {"area": 1000, "volume": volume, "per_body_count": 1,
                          "per_body_truncated": False, "center_of_mass": [10, 90, 5]},
                "center": [10, 90, 5], "min_point": [0, 90, 0], "max_point": [20, 92, 10]}
    assert check(payload(840))
    with pytest.raises(AssertionError):
        check(payload(1290))


def test_surface_tree_handle_accepts_serializer_omission_of_false_truncation():
    check = verify_acts_surface_edit._body_handle("ReverseA", "surface_body_test")
    payload = {"tree": {"truncated": False,
                        "root_bodies": [{"name": "ReverseA", "handle": "body-handle"}]}}
    assert check(payload) is not None
    payload["tree"]["root_bodies_truncated"] = True
    with pytest.raises(AssertionError):
        check(payload)


def test_surface_offset_checks_new_output_body_and_preserves_its_source(monkeypatch):
    details = verify_acts_surface_edit
    assert "offset_before = {root.bRepBodies.item(i).entityToken" in details._SURFACE_EDIT_SETUP
    assert "if len(offset_created) != 1:" in details._SURFACE_EDIT_SETUP
    assert "offset_created[0].name = 'SFE_OffsetBody'" in details._SURFACE_EDIT_SETUP
    assert "f.bodies.item(0).name = 'SFE_OffsetBody'" not in details._SURFACE_EDIT_SETUP

    monkeypatch.setitem(details._RECALL, "surface_edit_mass_SFE_Offset", {
        "area": 200, "volume": 0, "center": (10, 297, 5),
        "center_of_mass": (0, 0, 0), "min_point": (0, 297, 0),
        "max_point": (20, 297, 10), "body_count": 1, "per_body_count": 0})
    changed = details._mass_state("SFE_Offset", "changed", True, {
        "area": 460, "volume": 0, "center": [11.5, 308.5, 5],
        "min_point": [0, 297, 0], "max_point": [23, 320, 10]})
    result = {"mass": {"area": 460, "volume": 0,
                       "center_of_mass": [0, 0, 0], "per_body_truncated": False},
              "center": [11.5, 308.5, 5], "min_point": [0, 297, 0],
              "max_point": [23, 320, 10]}
    assert changed(result)
    wrong_named_source = {**result, "mass": {**result["mass"], "area": 400},
                          "center": [10, 310, 5], "min_point": [0, 300, 0],
                          "max_point": [20, 320, 10]}
    with pytest.raises(AssertionError):
        changed(wrong_named_source)

    monkeypatch.setitem(details._RECALL, "surface_edit_mass_offset_source", {
        "area": 400, "volume": 0, "center": (10, 310, 5),
        "center_of_mass": (0, 0, 0), "min_point": (0, 300, 0),
        "max_point": (20, 320, 10), "body_count": None, "per_body_count": None})
    unchanged = details._mass_state("offset_source", "unchanged", False)
    source_result = {**wrong_named_source, "mass": {**wrong_named_source["mass"], "area": 400}}
    assert unchanged(source_result)
    source_result["mass"]["area"] = 410
    with pytest.raises(AssertionError):
        unchanged(source_result)


def test_surface_changed_shape_requires_measured_expected_center_and_bounds(monkeypatch):
    monkeypatch.setitem(verify_acts_surface_edit._RECALL, "surface_edit_mass_expected-surface",
                        {"area": 400, "volume": 0, "center_of_mass": (10, 610, 0),
                         "min_point": (0, 600, 0), "max_point": (20, 620, 0),
                         "body_count": None, "per_body_count": 1})
    check = verify_acts_surface_edit._mass_state("expected-surface", "changed", True, {
        "area": 560, "volume": 0, "center": [6, 610, 0],
        "min_point": [-8, 600, 0], "max_point": [20, 620, 0],
    })
    payload = {"mass": {"area": 560, "volume": 0, "per_body_truncated": False,
                        "center_of_mass": [5, 609, 0], "per_body_count": 1},
               "center": {"x": 6, "y": 610, "z": 0},
               "min_point": {"x": -8, "y": 600, "z": 0},
               "max_point": {"x": 20, "y": 620, "z": 0}}
    assert check(payload) is not None
    payload["center"] = {"x": 10, "y": 610, "z": 0}
    with pytest.raises(AssertionError):
        check(payload)


def _driving_sketch(width, height):
    """A sketch_get X-ray of DrSk carrying these (expression, value, driving) dimension rows."""
    rows = [{"name": name, "value": value, "value_units": "mm", "expression": expression,
             "driving": driving, "type": "sketchlinear", "entities": entities}
            for name, entities, (expression, value, driving) in (
                ("d1", ["point:1", "point:2"], width), ("d2", ["point:2", "point:3"], height))]
    return {"truncated": False, "entities": [], "profiles": [], "profile_count": 1,
            "counts": {"lines": 4}, "constraints": [], "frame": {"space": "world"},
            "dimensions": rows, "driving_dimension_count": sum(r["driving"] for r in rows)}


@pytest.mark.parametrize("base_height, width, height, accepted", [
    ("10 mm", ("30 mm", 30.0, True), ("10.00 mm", 10.0, False), True),
    ("10 mm", ("30 mm", 30.0, True), ("12 mm", 12.0, False), False),
    ("10 mm", ("30.00 mm", 30.0, True), ("10 mm", 10.0, False), False),
    ("d9 / 3", ("30 mm", 30.0, True), ("d9/3", 10.0, False), False),
    ("10 mm", ("30 mm", 30.0, True), ("10.00 mm", 10.0, True), False),
], ids=["toggled-restated", "toggled-other-value", "untoggled-restated", "toggled-formula",
        "driving-flag-wrong"])
def test_driving_read_accepts_a_restated_expression_on_toggled_dimensions_only(
        monkeypatch, base_height, width, height, accepted):
    """Pins that only a toggled dimension may restate a plain expression of the same value."""
    sketch = verify_acts_sketch
    first = _driving_sketch(("30 mm", 30.0, True), (base_height, 10.0, True))
    for key, value in (("dr_sketch", sketch._sketch_facts(first)), ("dr_w", "d1"), ("dr_h", "d2")):
        monkeypatch.setitem(sketch._RECALL, key, value)
    check = sketch._driving_read(("dr_h",), dr_h=False)
    if accepted:
        assert check(_driving_sketch(width, height)) is True
    else:
        with pytest.raises(AssertionError, match="driving flag per dimension name"):
            check(_driving_sketch(width, height))


def test_finishing_census_reads_published_rows_and_rejects_a_malformed_census():
    """Pins that the finishing story reads the reply's body rows and never passes a broken census."""
    import verify_acts_feature_finishing as finishing
    row = {"identity": ["tokA", None], "component": "(Unsaved)", "body": "Body1",
           "shape": {"volume_cm3": 5.0, "area_cm2": 19.0, "face_count": 6}}
    twin = {**row, "identity": ["tokB", None], "body": "Body2"}
    rows = finishing._shapes({"bodies": [row, twin]})
    assert rows[0] == {"identity": ("tokA", None), "body": "Body1", "volume": 5.0,
                       "area": 19.0, "faces": 6} and len(rows) == 2
    assert finishing._shapes({"bodies": {"tokA": row}}) == []
    assert finishing._shapes({"bodies": [row, {**twin, "identity": ["tokA", None]}]}) == []
    assert finishing._shapes({"bodies": [{**row, "identity": None}]}) == []
    assert finishing._shapes(None) == []


def test_surface_candidate_requires_complete_census_owner_and_exact_operand_count(monkeypatch):
    key = "surface_candidate_kill"
    expected = {"definition_kind": "face", "owner": "Root", "area_cm2": 0.02,
                "normal": [0.0, 0.0, 1.0]}
    old = {"handle": "old-handle", "kind": "face", "name": "BRepFace",
           "owner": {"component": "Root", "occurrence": None},
           "geometry": {"area": 0.04, "normal": [0.0, 0.0, 1.0]}}
    candidate = {"handle": "opaque-candidate", "kind": "face", "name": "BRepFace",
                 "owner": {"component": "Root", "occurrence": None},
                 "geometry": {"area": 0.02, "normal": [0.0, 0.0, 1.0]}}
    before = {"feature": "Surface1", "component": "Root", "type": "UntrimFeature",
              "timeline_index": 4, "feature_address": "Surface1", "unavailable": {},
              "faces_to_untrim": [old], "loop_type": "internal"}
    monkeypatch.setitem(surface_boundaries._RECALL, key, before)
    monkeypatch.setitem(surface_boundaries._RECALL, key + "_candidate_expected", expected)
    after = {"definition": {**before, "faces_to_untrim": [old, candidate]}}
    assert surface_boundaries._changed(key, "faces_to_untrim", candidate_key=key + "_candidate")(after)

    for wrong_rows in ([old], [old, candidate, candidate],
                       [old, {**candidate, "owner": {"component": "Other", "occurrence": None}}],
                       [old, {**candidate, "geometry": {"area": 0.03, "normal": [0, 0, 1]}}]):
        with pytest.raises(AssertionError):
            surface_boundaries._changed(key, "faces_to_untrim",
                candidate_key=key + "_candidate")({"definition": {**before, "faces_to_untrim": wrong_rows}})

    incomplete = {"returned": 1, "match_count": 6, "matches": [
        {"handle": "face", "kind": "planar_face", "area": 2.0,
         "position": [1.0, 2.0, 3.0], "normal": [0, 0, 1]}]}
    with pytest.raises(AssertionError):
        surface_boundaries._candidate("planar_face", [1, 2, 3], key + "_candidate", key)(incomplete)


def test_surface_restore_and_setter_require_banked_baseline_and_published_owner_flags(monkeypatch):
    key = "surface_restore_kill"
    definition = {"feature": "Stitch1", "component": "Root", "type": "StitchFeature",
        "timeline_index": 8, "feature_address": "Stitch1", "unavailable": {},
        "stitch_surfaces": [{"handle": "opaque", "kind": "entity"}]}
    monkeypatch.setitem(surface_boundaries._RECALL, key, None)
    with pytest.raises(AssertionError):
        surface_boundaries._restored(key, "stitch_surfaces")({"definition": definition})
    monkeypatch.setitem(surface_boundaries._RECALL, key, definition)
    assert surface_boundaries._restored(key, "stitch_surfaces")({"definition": definition})

    monkeypatch.setitem(surface_boundaries._RECALL, "Stitch1_baseline", definition)
    good = {"edited": True, "definition_matches": True, "same_feature": True,
            "owner_matches": True, "marker_restored": True, "feature_health": {},
            "new_timeline_errors": [], "new_timeline_warnings": [], "geometry_changed": True}
    assert surface_boundaries._setter_result("Stitch1")(good)
    bad = {**good, "owner_matches": False}
    with pytest.raises(AssertionError):
        surface_boundaries._setter_result("Stitch1")(bad)
    monkeypatch.setitem(surface_boundaries._RECALL, "Stitch1_baseline", None)
    with pytest.raises(AssertionError):
        surface_boundaries._setter_result("Stitch1")(good)


def test_surface_delete_face_replaces_candidate_and_keeps_body_for_readback(monkeypatch):
    rows = surface_boundaries.surface_boundary_edit_rows()
    edit = next(args for tool, args, _check, _save in rows if tool == "model_edit_feature"
                and callable(args) and args.__defaults__ and args.__defaults__[0] == "EditDeleteSurface")
    monkeypatch.setitem(surface_boundaries._RECALL, "EditDeleteSurface_baseline",
        {"feature_address": "EditDeleteSurface", "deleted_faces": [{"handle": "old-face"}]})
    context = {"surface_doc": "scratch", "EditDeleteSurface_candidate": "new-face"}
    args = edit(context)
    assert args["references"] == ["new-face"]
    assert any(tool == "model_inspect" and args.get("target") == "DeleteSurfaceBody"
               for tool, args, _check, _save in rows)
    assert "opened_candidates" in surface_boundaries._FIXTURE
    assert "key=lambda b: abs(b.boundingBox.minPoint.y-y)" not in surface_boundaries._FIXTURE


def test_surface_candidate_reads_owner_after_baseline_and_uses_feature_body_handle_key(monkeypatch):
    rows = surface_boundaries.surface_boundary_edit_rows()
    query = next(args for tool, args, _check, _save in rows
                 if tool == "find_geometry" and callable(args))
    check = next(check for tool, _args, check, _save in rows
                 if tool == "find_geometry" and callable(_args))
    feature = query.__defaults__[3]
    body = query.__defaults__[0]
    monkeypatch.setitem(surface_boundaries._RECALL, feature + "_baseline", {"component": "(Unsaved)"})
    ctx = {feature + "_body_handle": "body-handle-for-feature"}
    assert query(ctx)["target"] == "body-handle-for-feature"
    payload = {"returned": 1, "match_count": 1, "matches": [
        {"handle": "face", "kind": "planar_face", "area": 1.0,
         "position": [30.0, 810.0, 2.0], "normal": [0.0, 0.0, 1.0]}]}
    assert check(payload) is True
    assert surface_boundaries._RECALL[feature + "_candidate_expected"]["owner"] == "(Unsaved)"
    with pytest.raises(KeyError):
        query({body + "_body_handle": "wrong-key"})


def test_surface_owned_body_candidate_accepts_solid_delete_heal_box():
    payload = {"tree": {"root": "(Unsaved)", "truncated": False,
        "children_truncated": False, "root_bodies": [{"name": "DeleteHealBox",
        "handle": "heal-body", "is_solid": True, "visible": True}]}}
    assert surface_boundaries._owned_body_candidate(
        "DeleteHealBox", "delete_heal", expected_solid=True)(payload) is True
    with pytest.raises(AssertionError):
        surface_boundaries._owned_body_candidate(
            "DeleteHealBox", "delete_heal_wrong", expected_solid=False)(payload)

def test_combine_body_restore_read_follows_public_restore_edit(monkeypatch):
    import verify_acts_feature_edit as feature_edit

    case = "CombineFeature"
    before_key = case + "_tools_before"
    target_key = case + "_target"
    monkeypatch.setitem(feature_edit._RECALL, before_key, {
        "feature_address": "Combine1", "tool_bodies": [{"handle": "original-tool"}]})
    monkeypatch.setitem(feature_edit._RECALL, target_key, "TargetBody")
    monkeypatch.setitem(feature_edit._RECALL, target_key + "_state", {
        "name": "TargetBody", "volume": 1.0, "min": [0.0, 0.0, 0.0],
        "max": [1.0, 1.0, 1.0], "center": [0.5, 0.5, 0.5]})
    rows = []
    feature_edit._transition(rows, case, "feature", "tools", "tool_bodies",
        candidate_key=case + "_tool2", body_target_key=target_key)
    ctx = {case + "_doc": "doc", case + "_component": "component",
           case + "_control": "control", case + "_tool2": "replacement-tool",
           target_key: "TargetBody", "feature": "feature-handle"}
    restore_edit = next(i for i, (tool, args, _check, _save) in enumerate(rows)
        if tool == "model_edit_feature" and callable(args)
        and args(ctx).get("references") == ["original-tool"])
    restored_check = next((i, args, check) for i, (tool, args, check, _save) in enumerate(rows)
        if tool == "model_inspect" and callable(args) and callable(check)
        and args(ctx).get("target") == "TargetBody"
        and any(value == "CombineFeature restored" for value in
                (cell.cell_contents for cell in (check.__closure__ or ()))))
    assert restored_check[0] > restore_edit
    assert restored_check[1](ctx)["target"] == "TargetBody"
    payload = {"kind": "body", "units": "mm", "target": "body 'TargetBody'",
        "mass": {"accuracy_used": "very_high", "volume": 1.0, "center_of_mass": [0.5, 0.5, 0.5]},
        "min_point": {"x": 0.0, "y": 0.0, "z": 0.0},
        "max_point": {"x": 1.0, "y": 1.0, "z": 1.0}}
    assert restored_check[2](payload)
