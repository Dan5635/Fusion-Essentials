# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The model solid creation act and its read-back predicates."""

import math
import json

from verify_core import (
    _activated, _box, _document_closed, _home_address, _new_document,
    _RECALL, _chamfered, _component_metadata, _ctx_get, _cut_on_its_pivot, _datum, _datum_plane, _drafted, _drafted_on_its_pivot, _drafted_symmetric, _drilled, _extent_measured, _extruded, _face_up_at, _fg, _fgn, _filleted, _gap_measured, _home_document, _joint_origin_at, _lofted, _made_component, _material_assigned, _matched, _measured, _metadata_set, _mirrored, _moved_occurrence, _captured, _near, _needs, _num, _offset_faces, _param_read, _param_traced, _patterned, _prof, _recall, _refused, _relation_measured, _relation_passes, _relation_read, _replaced_on_its_pivot, _sits_on_a_face, _swept, _unless, _watch)
from verify_acts_cam import (
    MACHINING_EXTENSION)
from verify_layout import (
    _px, _py)





from verify_acts_model_combine_revolve import (
    _COMBINE_COMPLETE, _COMBINE_CUT_NONE, _COMBINE_NONE, _COMBINE_NONROOT_PARTIAL, _COMBINE_PARTIAL, _REVOLVE_PARTICIPANTS, _combine_body, _combine_inspect, _combine_pin, _combine_story_address)
from verify_acts_model_extrude_organization import (
    _extrude_edit_dependent)
from verify_acts_model_precision import (
    _FINE_ANGLE_DEG, _HOLE_ACTIVE, _HOLE_ACTIVE_X0, _HOLE_HOST, _HOLE_VOLUME, _HOLE_X0, _PRECISION_READS, _control_top_args, _fine_angle_param, _fine_angle_plane, _hole_active_handle, _hole_active_tree, _hole_body_state, _hole_created, _hole_cylinder_args, _hole_cylinders, _hole_face_bounds, _hole_host_tree, _hole_inspect_args, _hole_lower_handle, _hole_timeline, _hole_upper_handle, _radius_body_size, _radius_filtered_handle, _scoped_bore_args, _scoped_hole_args, _scoped_top_args, _sweep_brep_list_edited, _sweep_dependent_survived, _sweep_edit_at_volume, _sweep_inspected_at_volume, _unscoped_hole_args)
from verify_acts_model_sweep import (
    _LATER_OPERAND, _LOFT_ALIGNMENT, _LOFT_EDITOR, _LOFT_PARTICIPANTS, _SOLID_TOOL,
    _SWEEP_EDIT_MODES, _TANGENT_PATH, _retire_compare, _retire_material_state, _sweep_mode_box_equal,
    _retire_reads, _retire_design_state, _rolled_back_body,
    _retire_body_state as _symmetric_target_body_state)


def _pattern_single_row_history(p):
    """Require the created pattern's native counts and spacing from the independent timeline."""
    rows = [r for r in (p.get("timeline") or {}).get("timeline", [])
            if r.get("name") == _RECALL.get("count_pattern")]
    params = {r.get("role"): r.get("value") for r in rows[0].get("params", [])} if len(rows) == 1 else {}
    return _measured("single-row native pattern counts and spacing", params,
                     params.get("countU") == 2 and params.get("CountV") == 1
                     and _near(params.get("uSpaceDistance"), 3, .0001))


def _pattern_single_row_material(p):
    """Require two separate seed-sized solids spanning the requested single-row placement."""
    state = _retire_material_state(p)
    rows = (p.get("mass") or {}).get("per_body") or []
    return _measured("two 4000 mm3 solids 30 mm apart along x", state,
                     state is not None and len(rows) == 2
                     and len({r.get("body") for r in rows}) == 2
                     and all(_near(r.get("volume"), 4000, .001) for r in rows)
                     and _near((p.get("mass") or {}).get("volume"), 8000, .001)
                     and all(_near(p.get(axis), size, .001) for axis, size in zip("xyz", (50, 20, 10))))


def _face_sketch_disclosure(p):
    """Check the face-handle read, its normal meanings, and the returned sketch frame."""
    frame, note = p.get("frame"), p.get("note", "")
    return _measured("face sketch separates its normals and returns its placement frame",
                     {"frame": frame, "note": note, "on_face": p.get("on_face")},
                     _sits_on_a_face(p) and isinstance(frame, dict)
                     and frame.get("space") == "world"
                     and "outward face normal" in note
                     and "supporting plane normal" in note
                     and "returned new-sketch frame" in note)


def _pattern_count_rows():
    """Exercise second-count refusal and the legal single row on an owned document."""
    rows = [("doc_get", {}, _home_document, ("count_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "count_home", "story")},
             _new_document, ("count_doc", lambda p: p["document_handle"]))]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(
            c, "count_doc", args(c) if callable(args) else args), check, save))
    for tool, args, check, save in _box("CountSeed") + _box("CountWitness", ox=100):
        write(tool, args, check, save)
    write("design_activate_component", {"occurrence": "CountSeed:1"})
    rows.append(_watch(["CountSeed:1", "CountWitness:1"]))
    rows.extend(_retire_reads("count_refusal", ["CountSeed:1", "CountWitness:1", ""], []))
    for count in (0, -2):
        write("model_pattern_rectangular", {"bodies": ["CountSeed"], "quantity_one": 2,
              "spacing_one": 30, "quantity_two": count}, _refused(f"quantity_two={count}", "Use 1"))
        rows.extend(_retire_reads("count_refusal", ["CountSeed:1", "CountWitness:1", ""], [], after=True))
    write("model_pattern_rectangular", {"bodies": ["CountSeed"], "quantity_one": 2,
          "spacing_one": 30, "quantity_two": 1}, _patterned("total_instances", 2),
          ("count_pattern", _recall("count_pattern", lambda p: p["feature"])))
    rows.extend([
        ("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
         _pattern_single_row_history, None),
        ("model_inspect", {"target": "CountSeed:1", "include": ["default", "mass"],
                           "per_body": True, "units": "mm", "accuracy": "very_high"},
         _pattern_single_row_material, None),
        ("model_inspect", {"target": "CountWitness:1", "include": ["default", "mass"],
                           "per_body": True, "units": "mm", "accuracy": "very_high"},
         _retire_compare("count_refusal_CountWitness:1", _retire_material_state, True), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, "count_home", "story"),
             "expect_document": _ctx_get(c, "count_doc", "count scratch")}, "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "count_doc", "count scratch"),
             "save_changes": False, "expect_document": _ctx_get(c, "count_home", "story")},
         _document_closed, None),
    ])
    return rows


def _pattern_timeline_healthy(p):
    timeline = p.get("timeline") or {}
    summary = timeline.get("summary") or {}
    rows = timeline.get("timeline") or []
    return (timeline.get("truncated", False) is False and timeline.get("returned") == timeline.get("count")
            and set(summary.get("states") or {}) == {"healthy"}
            and isinstance(summary.get("exceptions"), list) and not summary.get("exceptions")
            and all(r.get("health", "healthy") == "healthy"
                    and r.get("is_rolled_back", False) is False for r in rows))


def _capture_pattern_count(feature_key, component, role, expression, recall_key):
    def check(p):
        feature = _RECALL.get(feature_key)
        rows = [r for r in (p.get("timeline") or {}).get("timeline", [])
                if r.get("name") == feature and r.get("component") == component]
        params = (rows[0].get("params") or []) if len(rows) == 1 else []
        matches = [r for r in params if r.get("role") == role]
        name = matches[0].get("name") if len(matches) == 1 else None
        if name:
            _RECALL[recall_key] = name
        got = matches[0] if len(matches) == 1 else {}
        return _measured("one scoped pattern count parameter", {"feature": feature,
                         "component": component, "parameter": got},
                         len(rows) == 1 and len(matches) == 1 and bool(name)
                         and got.get("expression") == expression and _pattern_timeline_healthy(p))
    return check


def _pattern_count_read(feature_key, component, role, expression, value):
    def check(p):
        feature = _RECALL.get(feature_key)
        rows = [r for r in (p.get("timeline") or {}).get("timeline", [])
                if r.get("name") == feature and r.get("component") == component]
        params = (rows[0].get("params") or []) if len(rows) == 1 else []
        matches = [r for r in params if r.get("name") == _RECALL.get(feature_key + "_" + role)]
        got = matches[0] if len(matches) == 1 else {}
        return _measured("pattern count expression and value", got,
                         len(matches) == 1 and got.get("role") == role
                         and got.get("expression") == expression and _near(got.get("value"), value, 1e-6)
                         and _pattern_timeline_healthy(p))
    return check


def _pattern_body_count(target, count, body_volume=1000, bounds=None):
    def check(p):
        mass = p.get("mass") or {}
        bodies = mass.get("per_body") or []
        volumes = [r.get("volume") for r in bodies]
        names = [r.get("body") for r in bodies]
        envelope = all(_near(p.get(axis), want, .05) for axis, want in (bounds or {}).items())
        return _measured("native patterned body count", {"count": mass.get("per_body_count"),
                         "volumes": volumes, "bodies": names,
                         "envelope_mm": {axis: p.get(axis) for axis in "xyz"}},
                         mass.get("per_body_count") == count
                         and len(bodies) == count
                         and len(set(names)) == count
                         and envelope
                         and all(_near(v, body_volume, .02) for v in volumes))
    return check


def _pattern_occurrence_count(expected, other_occurrences=0):
    def check(p):
        rows = [r for r in p.get("occurrences") or [] if r.get("component") == "OccPatternSeed"]
        return _measured("native occurrence pattern count", {
            "occurrence_count": p.get("occurrence_count"), "seed_instances": [r.get("name") for r in rows]},
            p.get("occurrences_truncated") is False and len(rows) == expected
            and p.get("occurrence_count") == expected + other_occurrences)
    return check


def _pattern_parameter_rows():
    rows = [("doc_get", {}, _home_document, ("pattern_param_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "pattern_param_home", "home")},
             _new_document, ("pattern_param_doc", lambda p: p["document_handle"]))]

    doc_key = "pattern_param_doc"

    def write(tool, args, check="ok", save=None):
        key = doc_key
        if tool in {"design_get", "model_inspect", "assembly_get"}:
            rows.append((tool, args, check, save))
        else:
            rows.append((tool, lambda c, args=args, key=key: _combine_pin(
                c, key, args(c) if callable(args) else args), check, save))

    def body_seed(component, sketch, x, path=False):
        write("model_create_component", {"name": component, "activate": True}, _made_component)
        write("sketch_create", {"plane": "xy", "name": sketch})
        write("sketch_add_geometry", {"sketch_name": sketch, "geometry": [
            {"kind": "rectangle", "x1": x, "y1": 0, "x2": x + 10, "y2": 10}]})
        write("model_extrude", {"sketch_name": sketch, "profile_index": 0, "distance": 10}, _extruded)
        if path:
            path_sketch = sketch + "Path"
            write("sketch_create", {"plane": "xy", "name": path_sketch})
            write("sketch_add_geometry", {"sketch_name": path_sketch, "geometry": [
                {"kind": "line", "x1": x, "y1": 30, "x2": x + 100, "y2": 30}]})

    def count_steps(feature_key, component, role, baseline, up, down, count_after_up,
                    count_after_down, count_v=None, baseline_bounds=None):
        write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
              _capture_pattern_count(feature_key, component, role, str(baseline),
                                     feature_key + "_" + role))
        name = lambda: _RECALL.get(feature_key + "_" + role)
        write("model_inspect", {"target": component + ":1", "include": ["default", "mass"],
                                "per_body": True, "units": "mm", "accuracy": "very_high"},
              _pattern_body_count(component, baseline, bounds=baseline_bounds))
        if count_v is not None:
            vkey = feature_key + "_CountV"
            write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
                  _capture_pattern_count(feature_key, component, "CountV", "1", vkey))
            write("param_set", lambda c: {"name": _RECALL.get(vkey), "expression": "2"})
            write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
                  _pattern_count_read(feature_key, component, "CountV", "2", 2))
            write("model_inspect", {"target": component + ":1", "include": ["default", "mass"],
                                    "per_body": True, "units": "mm", "accuracy": "very_high"},
                  _pattern_body_count(component, 6, bounds={"x": 70, "y": 40, "z": 10}))
            write("param_set", lambda c: {"name": name(), "expression": str(up)})
            write("model_inspect", {"target": component + ":1", "include": ["default", "mass"],
                                    "per_body": True, "units": "mm", "accuracy": "very_high"},
                  _pattern_body_count(component, count_after_up, bounds={"x": 130, "y": 40, "z": 10}))
            write("param_set", lambda c: {"name": name(), "expression": str(down)})
            write("param_set", lambda c: {"name": _RECALL.get(vkey), "expression": "1"})
            write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
                  _pattern_count_read(feature_key, component, "CountV", "1", 1))
            write("model_inspect", {"target": component + ":1", "include": ["default", "mass"],
                                    "per_body": True, "units": "mm", "accuracy": "very_high"},
                  _pattern_body_count(component, count_after_down, bounds={"x": 40, "y": 10, "z": 10}))
        else:
            write("param_set", lambda c: {"name": name(), "expression": str(up)})
            write("model_inspect", {"target": component + ":1", "include": ["default", "mass"],
                                    "per_body": True, "units": "mm", "accuracy": "very_high"},
                  _pattern_body_count(component, count_after_up))
            write("param_set", lambda c: {"name": name(), "expression": str(down)})
            write("model_inspect", {"target": component + ":1", "include": ["default", "mass"],
                                    "per_body": True, "units": "mm", "accuracy": "very_high"},
                  _pattern_body_count(component, count_after_down))
        write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
              _pattern_count_read(feature_key, component, role, str(down), down))

    body_seed("PBRect", "PBRectS", 500)
    write("model_pattern_rectangular", {"bodies": ["PBRect"], "quantity_one": 3,
          "spacing_one": 30, "direction_one": "x", "quantity_two": 1, "spacing_two": 30,
          "direction_two": "y"}, _patterned("total_instances", 3),
          ("param_rect_feature", _recall("param_rect_feature", lambda p: p["feature"])))
    count_steps("param_rect_feature", "PBRect", "countU", 3, 5, 2, 10, 2, count_v=True,
                baseline_bounds={"x": 70, "y": 10, "z": 10})
    write("param_add", {"name": "PatternRows", "expression": "4", "unit": ""},
          lambda p: p.get("added") is True and (p.get("parameter") or {}).get("name") == "PatternRows")
    write("param_set", lambda c: {"name": _RECALL.get("param_rect_feature_countU"),
                                  "expression": "PatternRows"})
    write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
          _pattern_count_read("param_rect_feature", "PBRect", "countU", "PatternRows", 4))
    write("model_inspect", {"target": "PBRect:1", "include": ["default", "mass"],
                            "per_body": True, "units": "mm", "accuracy": "very_high"},
          _pattern_body_count("PBRect", 4, bounds={"x": 100, "y": 10, "z": 10}))
    write("param_set", {"name": "PatternRows", "expression": "3"})
    write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
          _pattern_count_read("param_rect_feature", "PBRect", "countU", "PatternRows", 3))
    write("model_inspect", {"target": "PBRect:1", "include": ["default", "mass"],
                            "per_body": True, "units": "mm", "accuracy": "very_high"},
          _pattern_body_count("PBRect", 3, bounds={"x": 70, "y": 10, "z": 10}))

    body_seed("PBCir", "PBCirS", 700)
    write("model_pattern_circular", {"bodies": ["PBCir"], "quantity": 4,
          "total_angle_deg": 360, "axis": "z"}, lambda p: p.get("patterned") is True,
          ("param_cir_feature", _recall("param_cir_feature", lambda p: p["feature"])))
    count_steps("param_cir_feature", "PBCir", "countU", 4, 6, 3, 6, 3)

    body_seed("PBPath", "PBPathS", 900, path=True)
    write("model_pattern_path", {"bodies": ["PBPath"], "path": "sketch:PBPathSPath",
          "quantity": 3, "distance": 10, "distance_type": "spacing"},
          lambda p: p.get("patterned") is True,
          ("param_path_feature", _recall("param_path_feature", lambda p: p["feature"])))
    count_steps("param_path_feature", "PBPath", "countU", 3, 5, 2, 5, 2)

    rows.extend([("doc_activate", lambda c: {"name": _ctx_get(c, "pattern_param_home", "home"),
         "expect_document": _ctx_get(c, "pattern_param_doc", "scratch")}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "pattern_param_doc", "scratch"),
         "save_changes": False, "expect_document": _ctx_get(c, "pattern_param_home", "home")},
         _document_closed, None),
        ("doc_new", lambda c: {"expect_document": _ctx_get(c, "pattern_param_home", "home")},
         _new_document, ("occ_pattern_doc", lambda p: p["document_handle"]))])
    doc_key = "occ_pattern_doc"
    body_seed("OccPatternSeed", "OccPatternSeedS", 1100)
    write("design_activate_component", {"occurrence": "root"})
    write("sketch_create", {"plane": "xy", "name": "OccPatternPathS"})
    write("sketch_add_geometry", {"sketch_name": "OccPatternPathS", "geometry": [
        {"kind": "line", "x1": 1100, "y1": 30, "x2": 1200, "y2": 30}]})
    write("model_pattern_rectangular", {"occurrences": ["OccPatternSeed:1"], "quantity_one": 3,
          "spacing_one": 30, "direction_one": "x", "quantity_two": 1, "spacing_two": 30,
          "direction_two": "y"}, lambda p: p.get("patterned") is True,
          ("param_orect_feature", _recall("param_orect_feature", lambda p: p["feature"])))
    write("model_pattern_circular", {"occurrences": ["OccPatternSeed:1"], "quantity": 4,
          "total_angle_deg": 360, "axis": "z"}, lambda p: p.get("patterned") is True,
          ("param_ocir_feature", _recall("param_ocir_feature", lambda p: p["feature"])))
    write("model_pattern_path", {"occurrences": ["OccPatternSeed:1"],
          "path": "sketch:OccPatternPathS", "quantity": 3, "distance": 10,
          "distance_type": "spacing"}, lambda p: p.get("patterned") is True,
          ("param_opath_feature", _recall("param_opath_feature", lambda p: p["feature"])))
    write("assembly_get", {"max_occurrences": 100}, _pattern_occurrence_count(8))
    for key, role, up, down in (("param_orect_feature", "countU", 4, 2),
                                ("param_ocir_feature", "countU", 6, 3),
                                ("param_opath_feature", "countU", 5, 2)):
        write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
              _capture_pattern_count(key, None, role,
                                     str({"param_orect_feature": 3, "param_ocir_feature": 4,
                                          "param_opath_feature": 3}[key]), key + "_" + role))
        expected_counts = {"param_orect_feature": (9, 7),
                           "param_ocir_feature": (9, 6), "param_opath_feature": (8, 5)}[key]
        for number, expected in zip((up, down), expected_counts):
            write("param_set", lambda c, key=key, role=role, number=number: {
                "name": _RECALL.get(key + "_" + role), "expression": str(number)})
            write("assembly_get", {"max_occurrences": 100}, _pattern_occurrence_count(expected))
        write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
              _pattern_count_read(key, None, role, str(down), down))

    rows.extend([("doc_activate", lambda c: {"name": _ctx_get(c, "pattern_param_home", "home"),
         "expect_document": _ctx_get(c, "occ_pattern_doc", "scratch")}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "occ_pattern_doc", "scratch"),
         "save_changes": False, "expect_document": _ctx_get(c, "pattern_param_home", "home")},
         _document_closed, None)])
    return rows


def _loft_curve_refusal_rows():
    """Refuse line handles with the exact sketch-curve form, then loft and retire that form."""
    rows = [("doc_get", {}, _home_document, ("lcr_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "lcr_home", "home")},
             _new_document, ("lcr_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(
            c, "lcr_doc", args(c) if callable(args) else args), check, save))

    write("model_create_component", {"name": "LoftCurveRefs", "activate": True}, _made_component)
    write("sketch_create", {"plane": "xy", "name": "CurveA"})
    write("sketch_add_geometry", {"sketch_name": "CurveA", "geometry": [
        {"kind": "line", "x1": 40, "y1": 0, "x2": 60, "y2": 0}]})
    write("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy",
                                 "offset": 10, "name": "CurvePlane"}, _datum_plane("xy"))
    write("sketch_create", {"plane": "CurvePlane", "name": "CurveB"})
    write("sketch_add_geometry", {"sketch_name": "CurveB", "geometry": [
        {"kind": "line", "x1": 40, "y1": 0, "x2": 60, "y2": 0}]})
    for name, z in (("CurveA", 0), ("CurveB", 10)):
        rows.append(("find_geometry", {"target": "LoftCurveRefs", "kind": "sketch_line",
                     "nearest_to": [50, 0, z], "max_results": 1}, _matched(1, "sketch_line"),
                     _fg("lcr_" + name.lower())))
        rows.append(("sketch_get", {"sketch_name": name, "component": "LoftCurveRefs",
                     "include_entities": True},
                     lambda p, name=name: p.get("sketch") == name
                     and p.get("component") == "LoftCurveRefs"
                     and (p.get("counts") or {}).get("lines") == 1,
                     ("lcr_sketch_" + name, _recall("lcr_sketch_" + name, lambda p: p))))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100}, "ok",
                 ("lcr_rows", _recall("lcr_rows", lambda p: p["timeline"])) ))
    write("model_loft", lambda c: {"component": "LoftCurveRefs", "as_surface": True, "profiles": [
        _ctx_get(c, "lcr_curvea", "CurveA line handle"),
        _ctx_get(c, "lcr_curveb", "CurveB line handle")]},
        _refused("SketchLine handle, not a loft profile", "CurveA/line:0",
                 "sketch-curve section reference"))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 lambda p: _measured("line-handle refusal preserves timeline", p.get("timeline"),
                     p.get("timeline") == _RECALL.get("lcr_rows")), None))
    for name in ("CurveA", "CurveB"):
        rows.append(("sketch_get", {"sketch_name": name, "component": "LoftCurveRefs", "include_entities": True},
                     lambda p, name=name: _measured("line-handle refusal preserves " + name,
                         p, p == _RECALL.get("lcr_sketch_" + name)), None))
    write("model_loft", {"component": "LoftCurveRefs", "as_surface": True,
                         "profiles": ["CurveA/line:0", "CurveB/line:0"]}, _lofted,
          ("lcr_feature", lambda p: {"feature": "LoftCurveRefs/" + p["feature"],
                                    "body": "LoftCurveRefs:" + p["result_bodies"][0]}))
    rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "lcr_feature", "open loft")["body"],
                                      "units": "cm"},
          lambda p: _measured("corrected curve refs build the measured surface bounds", {
              "kind": p.get("kind"), "units": p.get("units"), "x": p.get("x"), "y": p.get("y"),
              "z": p.get("z"), "min_point": p.get("min_point"), "max_point": p.get("max_point")},
              p.get("kind") == "body" and p.get("units") == "cm"
              and _near(p.get("x"), 2, .0001) and _near(p.get("y"), 0, .0001)
              and _near(p.get("z"), 1, .0001)
              and p.get("min_point") == {"x": 4.0, "y": 0.0, "z": 0.0}
              and p.get("max_point") == {"x": 6.0, "y": 0.0, "z": 1.0}), None))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, "lcr_feature", "open loft")["body"],
                 "kind": "planar_face", "units": "cm", "max_results": 2},
                 lambda p: _measured("corrected loft has its measured surface face", p.get("matches"),
                     p.get("match_count") == p.get("returned") == 1
                     and _near((p.get("matches") or [{}])[0].get("area"), 2, .0001)), None))
    write("design_delete_feature", lambda c: {"feature": _ctx_get(c, "lcr_feature", "open loft")["feature"]})
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 lambda p: _measured("loft retirement restores the prior timeline", p.get("timeline"),
                     p.get("timeline") == _RECALL.get("lcr_rows")), None))
    for name in ("CurveA", "CurveB"):
        rows.append(("sketch_get", {"sketch_name": name, "component": "LoftCurveRefs", "include_entities": True},
                     lambda p, name=name: _measured("loft retirement restores public sketch " + name,
                         p, p == _RECALL.get("lcr_sketch_" + name)), None))
    rows.extend([("doc_activate", lambda c: {"name": _ctx_get(c, "lcr_home", "home")}, "ok", None),
                 ("doc_close", lambda c: {"name": _ctx_get(c, "lcr_doc", "scratch"),
                    "save_changes": False, "expect_document": _ctx_get(c, "lcr_home", "home")},
                  _document_closed, None)])
    return rows


def _hole_note_detail(p):
    """Read the requested hole-note values and display back off an independent pmi_get record."""
    notes = [a for a in p.get("annotations") or [] if a.get("name") == "SweepHoleNote"]
    note = notes[0] if len(notes) == 1 else {}
    dia, depth = note.get("diameter") or {}, note.get("depth") or {}
    tol = dia.get("tolerance") or {}
    primary, secondary = note.get("display") or {}, note.get("display_secondary") or {}
    valid = (p.get("units") == "mm" and note.get("kind") == "hole_note"
             and _near(depth.get("value"), 4.5, 1e-6) and depth.get("overridden") is True
             and _near(dia.get("value"), 4.2, 1e-6) and dia.get("overridden") is True
             and tol.get("type") == "symmetric" and _near(tol.get("upper"), .05, 1e-6)
             and _near(tol.get("lower"), -.05, 1e-6)
             and primary.get("precision") == 2 and primary.get("leading_zeros") is True
             and secondary.get("precision") == 3 and secondary.get("units") == "inches")
    return _measured("hole note values and display read back", notes, valid)


_SOLIDS = [
    # The sketch acts have already drawn the whole scratch field by now, so a whole-model fit is a
    # metre of scenery with the part a speck in it. Frame the profiles the features below consume,
    # and the bracket appears inside the shot instead of off the edge of one.
    _watch(["BracketBody", "BracketStep", "BracketPocket"]),
    ("design_activate_component", {"occurrence": "Bracket:1"}, "ok", None),
    # THE BLOCK, THE STEP AND THE BOSS - three extrudes off the three parametric profiles, each
    # taking its depth from the parameter that states it, so the resize walks the solid as well as
    # the sketches.
    ("model_extrude", {"sketch_name": "BracketBody", "profile_index": 0,
                       "distance": "PartHt - StepDrop"}, _extruded, None),
    # THE BLOCK MEASURED WHERE IT IS BUILT: the two span dimensions are the only thing standing
    # between the driver and the solid, and a dimension that anchored the wrong point leaves a
    # block of the wrong size that nothing downstream would name until the resize act.
    ("model_inspect", {"target": "Bracket:1"},
     lambda p: _measured("the block is PartLen x PartWid x (PartHt - StepDrop)",
                         {"x": p.get("x"), "y": p.get("y"), "z": p.get("z")},
                         _near(p.get("x"), 120.0, 0.1) and _near(p.get("y"), 80.0, 0.1)
                         and _near(p.get("z"), 30.0, 0.1)), None),
    ("model_extrude", {"sketch_name": "BracketStep", "profile_index": 0, "distance": "StepDrop",
                       "operation": "join"}, _extruded, None),
    ("model_extrude", {"sketch_name": "BracketBoss", "profile_index": 0, "distance": "PartHt / 8",
                       "operation": "join"}, _extruded, None),
    # WHAT A PARAMETER CHANGE TOUCHES, read instead of simulated: PartHt drives StepDrop and BoreDia
    # directly, reaches the boss diameter's own sketch dimension a hop further out, and the trace
    # names the extrudes that consume those sketches - the recompute an agent would otherwise have
    # to drive to find out. trace_depth=3 asks for the deep rows the default summarizes.
    ("param_get", {"name": "PartHt", "trace": True, "trace_depth": 3},
     _param_traced("PartHt", direct=("StepDrop", "BoreDia")), None),
    # THE POCKET, cut UP from its own floor and out through the step top - the direction with a
    # body in it. It runs one edge break PAST that face so the cut opens the pocket instead of
    # ending coincident with it.
    ("model_extrude", {"sketch_name": "BracketPocket", "profile_index": 0,
                       "distance": "PocketDepth + EdgeBreak", "operation": "cut"}, _extruded, None),
    # A MATERIAL-REMOVAL FEATURE IS JUDGED BY THE MATERIAL: the cut opened a floor 16 mm under the
    # step top, so the pocket floor is a planar face at z=14 that did not exist a step ago. A cut
    # that ran the wrong way, or found no body, leaves no such face.
    ("find_geometry", {"target": "Bracket", "kind": "planar_face", "nearest_to": [-35, 0, 14],
                       "max_results": 1}, _face_up_at(-35, 0, 14, tol=2.0), None),
    # THE POCKET'S CORNER RADII, at the parameter itself: model_fillet takes a radius EXPRESSION,
    # so the created feature holds 'PocketRad' rather than the number that expression evaluates to -
    # which is what lets the recompute in the resize act carry it.
    ("find_geometry", {"target": "Bracket", "kind": "line_edge", "nearest_to": [-50, -22, 22],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("pk_c1")),
    ("find_geometry", {"target": "Bracket", "kind": "line_edge", "nearest_to": [-20, -22, 22],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("pk_c2")),
    ("find_geometry", {"target": "Bracket", "kind": "line_edge", "nearest_to": [-20, 22, 22],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("pk_c3")),
    ("find_geometry", {"target": "Bracket", "kind": "line_edge", "nearest_to": [-50, 22, 22],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("pk_c4")),
    ("model_fillet", lambda c: {"edges": [_ctx_get(c, "pk_c1", "pocket corner one"),
                                          _ctx_get(c, "pk_c2", "pocket corner two"),
                                          _ctx_get(c, "pk_c3", "pocket corner three"),
                                          _ctx_get(c, "pk_c4", "pocket corner four")],
                                "radius": "PocketRad"}, _filleted, None),
    # THE TWO THROUGH BORES, one of them up the boss. model_hole's diameter is an EXPRESSION, so
    # these follow the part's own section where a fillet radius cannot.
    # EVERY hole below places its points in WORLD space. The default 'sketch' frame is the frame of
    # the placement sketch model_hole lays on the chosen face, and that frame is the face's, not the
    # world's; the tool converts a world point through the sketch's own converter and REFUSES one
    # that does not lie on the face, so the z coordinate is the face's own height.
    # Each face is MEASURED before it is drilled: a hole through the wrong face is a hole every
    # read after it still calls a hole. 'nearest_to' ranks by distance to each face's own CENTROID,
    # not to the nearest point on it - measured: a probe sitting ON this top face but off toward
    # its edge lost to the block's L-shaped +Y side wall, whose centroid was nearer - so every
    # probe below is aimed at the centroid the face it wants will have.
    # The raised half spans x[-10,60] and its middle is x=25; the boss standing on it takes a
    # circular bite that pulls the centroid about 1.2 mm back along -x, which the band absorbs.
    ("find_geometry", {"target": "Bracket", "kind": "planar_face", "nearest_to": [25, 0, 40],
                       "max_results": 1}, _face_up_at(25, 0, 40, tol=2.0), _fg("step_top")),
    ("model_hole", lambda c: {"face": _ctx_get(c, "step_top", "the high half of the top"),
                              "hole_type": "simple", "diameter": "BoreDia", "extent": "through",
                              "points_space": "world", "points": [[20, 0, 40]]}, _drilled(1), None),
    ("find_geometry", {"target": "Bracket", "kind": "planar_face", "nearest_to": [45, 0, 45],
                       "max_results": 1}, _face_up_at(45, 0, 45, tol=0.5), _fg("boss_top")),
    ("model_hole", lambda c: {"face": _ctx_get(c, "boss_top", "the boss top"),
                              "hole_type": "simple", "diameter": "BoreDia", "extent": "through",
                              "points_space": "world", "points": [[45, 0, 45]]}, _drilled(1), None),
    # THE MOUNTING PATTERN: four COUNTERBORED holes through the low half of the top in one call -
    # 'holes_verified' counts the drill axes off the created feature, so four here is four.
    # the low half spans x[-60,-10]: its middle is x=-35, and the pocket it lost is centred there
    # too, so removing that opening leaves the centroid where it was.
    ("find_geometry", {"target": "Bracket", "kind": "planar_face", "nearest_to": [-35, 0, 30],
                       "max_results": 1}, _face_up_at(-35, 0, 30, tol=2.0), _fg("low_top")),
    ("model_hole", lambda c: {"face": _ctx_get(c, "low_top", "the low half of the top"),
                              "hole_type": "counterbore", "diameter": "MountDia",
                              "cbore_diameter": "MountDia * 1.8", "cbore_depth": "EdgeBreak",
                              "extent": "through", "points_space": "world",
                              "points": [[-45, 30, 30], [-25, 30, 30],
                                         [-45, -30, 30], [-25, -30, 30]]},
     _drilled(4), None),
    # THE HANDLED EDGES, and the split between the two tools: a fillet RADIUS may be a parameter
    # expression, so the rounded edge carries 'EdgeBreak' itself; a chamfer DISTANCE is judged
    # against the number it was given, so it stays a literal READ from that same parameter.
    ("param_get", {"name": "EdgeBreak"}, _param_read("EdgeBreak", 3),
     ("edge_break", lambda p: p["parameter"]["value"])),
    ("find_geometry", {"target": "Bracket", "kind": "line_edge", "nearest_to": [-10, 0, 40],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("step_lead")),
    ("model_fillet", lambda c: {"edges": [_ctx_get(c, "step_lead", "the step's leading edge")],
                                "radius": "EdgeBreak"}, _filleted, None),
    ("find_geometry", {"target": "Bracket", "kind": "line_edge", "nearest_to": [60, 0, 40],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("step_out")),
    ("model_chamfer", lambda c: {"edges": [_ctx_get(c, "step_out", "the step's outboard edge")],
                                 "distance": _ctx_get(c, "edge_break", "the edge break")},
     _chamfered, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # The WCS anchor the CAM setup binds to, at the part's own origin: parametric, so it holds
    # position through the recompute the resize act drives.
    ("joint_create_origin", {"anchor": "coordinates", "target": "origin", "name": "StockCenter"},
     _joint_origin_at("StockCenter", 0, 0, 0), None),
    # THE TWO SOLID BUILDERS THE BRACKET HAS NO HOME FOR, each on a cameo of its own out on the
    # field: a base-to-post loft and a swept boss.
    # a default create with no 'part_number' input: the new component's own partNumber is WRITTEN
    # to its name (the timestamp Fusion mints it with otherwise), read back off the receipt.
    ("model_create_component", {"name": "LoftCameo", "activate": True},
     lambda p: _made_component(p) and _measured("part_number defaults to the component's own name",
                                                 {"part_number": p.get("part_number"),
                                                  "component": p.get("component")},
                                                 p.get("part_number") == p.get("component")), None),
    ("sketch_create", {"plane": "xy", "name": "LoftBase"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 250, "cy": 0, "radius": 16}],
                             "sketch_name": "LoftBase"}, "ok", None),
    ("sketch_get", {"sketch_name": "LoftBase"}, "ok", _prof("loft_base")),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 40, "name": "LoftTopPlane"},
     _datum_plane("xy"), None),
    ("sketch_create", {"plane": "LoftTopPlane", "name": "LoftTop"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 250, "cy": 0, "radius": 8}],
                             "sketch_name": "LoftTop"}, "ok", None),
    ("sketch_get", {"sketch_name": "LoftTop"}, "ok", _prof("loft_top")),
    ("model_loft", lambda c: {"profiles": [_ctx_get(c, "loft_base", "the loft's base profile"),
                                           _ctx_get(c, "loft_top", "the loft's top profile")]},
     _lofted, ("sweep_edit_witness_body", lambda p: p["result_bodies"][0])),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "SweepCameo", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xz", "name": "SweepPath"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 250, "y1": 0,
                                           "x2": 250, "y2": -50}],
                             "sketch_name": "SweepPath"}, "ok", None),
    ("sketch_create", {"plane": "xy", "name": "SweepProf"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 250, "cy": 0, "radius": 5}],
                             "sketch_name": "SweepProf"}, "ok", None),
    ("sketch_create", {"plane": "xy", "name": "SweepProfWide"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 250, "cy": 0, "radius": 8}],
                             "sketch_name": "SweepProfWide"}, "ok", None),
    ("sketch_create", {"plane": "xz", "name": "SweepPathArc"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "arc", "cx": 300, "cy": 0,
                                            "x1": 250, "y1": 0, "sweep_deg": 90}],
                             "sketch_name": "SweepPathArc"}, "ok", None),
    ("sketch_create", {"plane": "xz", "name": "SweepPathDown"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 250, "y1": 0,
                                           "x2": 250, "y2": 50}],
                             "sketch_name": "SweepPathDown"}, "ok", None),
    ("sketch_create", {"plane": "xy", "name": "SweepBasePocket"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 255, "cy": 0, "radius": 1}],
                             "sketch_name": "SweepBasePocket"}, "ok", None),
    ("sketch_create", {"plane": "xz", "name": "SweepPathSide"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 260, "y1": 0,
                                           "x2": 260, "y2": -50}],
                             "sketch_name": "SweepPathSide"}, "ok", None),
    ("sketch_create", {"plane": "xz", "name": "SweepPathBrepSource"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [
        {"kind": "line", "x1": 250, "y1": 0, "x2": 250, "y2": -10},
        {"kind": "arc", "cx": 260, "cy": -10, "x1": 250, "y1": -10, "sweep_deg": 45}],
        "sketch_name": "SweepPathBrepSource"}, "ok", None),
    ("model_extrude", {"sketch_name": "SweepPathBrepSource", "distance": 3,
                       "as_surface": True}, _extruded,
     ("sweep_brep_strip", lambda p: p["result_bodies"][0])),
    ("model_sweep", {"profile": {"sketch": "SweepProf", "profile_index": 0},
                     "path": "sketch:SweepPath"}, _swept,
     ("sweep_edit_body", _recall("sweep_edit_body", lambda p: p["result_bodies"][0]))),
    ("find_geometry", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_edit_body", "sweep body"),
                                  "kind": "planar_face", "nearest_to": [250, 0, 50],
                                  "max_results": 1}, _matched(1, "planar_face"), _fg("sweep_end_cap")),
    ("model_construction", lambda c: {"kind": "plane", "plane": _ctx_get(c, "sweep_end_cap", "end cap"),
                                       "offset": 2, "name": "SweepSupportPlane"},
     _datum_plane("xy"), None),
    ("sketch_create", {"plane": "SweepSupportPlane", "name": "SweepDependent"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 2}],
                             "sketch_name": "SweepDependent"}, "ok", None),
    ("model_extrude", {"sketch_name": "SweepDependent", "distance": 1}, _extruded,
     ("sweep_dependent_body", _recall("sweep_dependent_body", lambda p: p["result_bodies"][0]))),
    ("design_get", {"include": ["tree"], "component": "SweepCameo", "tree_bodies": True}, "ok",
     ("sweep_dependent_handle", lambda p: next(
         body["handle"] for body in p["tree"]["tree"]["bodies"]
         if body["name"] == _RECALL["sweep_dependent_body"]))),
    ("model_inspect", lambda c: {"target": _ctx_get(c, "sweep_dependent_handle", "dependent handle"),
                                 "include": ["default", "mass"], "units": "cm"}, "ok",
     ("sweep_dependent_before", _recall("sweep_dependent_before", lambda p: {
         "volume": p["mass"]["volume"], "min_point": p["min_point"],
         "max_point": p["max_point"]}))),
    ("model_inspect", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_edit_body", "sweep body"),
                                 "include": ["mass"], "units": "cm"},
     _sweep_inspected_at_volume(math.pi * 0.5 ** 2 * 5), None),
    ("model_inspect", lambda c: {"target": "LoftCameo:" + _ctx_get(
        c, "sweep_edit_witness_body", "loft witness"), "include": ["mass"], "units": "cm"},
     lambda p: _num((p.get("mass") or {}).get("volume")),
     ("sweep_edit_witness_volume", _recall("sweep_edit_witness_volume",
                                              lambda p: p["mass"]["volume"]))),
    ("model_edit_sweep", {"feature": "SweepCameo/Sweep1", "action": "profile",
                          "profile": {"sketch": "SweepProfWide", "profile_index": 0},
                          "component": "SweepCameo"},
     _sweep_edit_at_volume(math.pi * 0.8 ** 2 * 5), None),
    ("model_inspect", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_edit_body", "sweep body"),
                                 "include": ["mass"], "units": "cm"},
     _sweep_inspected_at_volume(math.pi * 0.8 ** 2 * 5), None),
    ("model_inspect", lambda c: {"target": _ctx_get(c, "sweep_dependent_handle", "dependent handle"),
                                 "include": ["default", "mass"], "units": "cm"},
     _sweep_dependent_survived(False), None),
    # A pocket up into the start cap. A downward path leaves it cutting air, so the new warning
    # fails the check and the prior path curve is swept again.
    ("model_extrude", lambda c: {"sketch_name": "SweepBasePocket", "distance": 2, "operation": "cut",
                                 "target_bodies": ["SweepCameo:" + _ctx_get(c, "sweep_edit_body",
                                                                            "sweep body")]},
     _extruded, ("sweep_base_pocket", _recall("sweep_base_pocket", lambda p: p["feature"]))),
    ("model_inspect", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_edit_body", "sweep body"),
                                 "include": ["mass"], "units": "cm"},
     _sweep_inspected_at_volume(math.pi * 0.8 ** 2 * 5 - math.pi * 0.1 ** 2 * 0.2),
     ("sweep_pocketed_volume", _recall("sweep_pocketed_volume", lambda p: p["mass"]["volume"]))),
    # The restored path sweeps the prior shape into a body of a new name and identity.
    ("model_edit_sweep", {"feature": "SweepCameo/Sweep1", "action": "path",
                          "path": "sketch:SweepPathDown"},
     _refused("New evaluated timeline errors or warnings",
              "It was rolled back and re-read: path reads SweepPath/line:0 again; the body shapes "
              "match the pre-edit read. The body now reads as '",
              "; re-read names and handles held for it."), None),
    ("model_inspect", {"target": "SweepCameo:1", "include": ["mass"], "units": "cm", "per_body": True},
     *_rolled_back_body("sweep_pocketed_volume", "sweep_edit_body", renamed=True)),
    ("model_inspect", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_edit_body", "sweep body"),
                                 "include": ["mass"], "units": "cm"},
     lambda p: _measured("rolled-back sweep volume", (p.get("mass") or {}).get("volume"), _near(
         (p.get("mass") or {}).get("volume"), _RECALL["sweep_pocketed_volume"], 0.0001)), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000},
     _extrude_edit_dependent("sweep_base_pocket", "SweepCameo", healthy=True), None),
    ("model_inspect", lambda c: {"target": _ctx_get(c, "sweep_dependent_handle", "dependent handle"),
                                 "include": ["default", "mass"], "units": "cm"},
     _sweep_dependent_survived(False), None),
    # A parallel straight path 10 mm to the side sweeps the same body: the edit lands, the bodies
    # read identical before and after, and the call succeeds saying so.
    ("model_inspect", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_edit_body", "sweep body"),
                                 "include": ["default", "mass"], "units": "cm"}, "ok",
     ("sweep_side_before", _recall("sweep_side_before", lambda p: {
         "volume": p["mass"]["volume"], "min_point": p["min_point"],
         "max_point": p["max_point"]}))),
    ("model_edit_sweep", {"feature": "SweepCameo/Sweep1", "action": "path",
                          "path": "sketch:SweepPathSide"},
     lambda p: _measured("identical-geometry path edit", {
         "edited": p.get("edited"), "geometry_changed": p.get("geometry_changed"),
         "operand_after": p.get("operand_after"), "note": p.get("note")},
         p.get("edited") is True and p.get("definition_matches") is True
         and p.get("geometry_changed") is False and p.get("outside_body_changes") == []
         and p.get("operand_after") == "SweepPathSide/line:0" and "rollback" not in p
         and "The body geometry reads identical before and after." in str(p.get("note"))), None),
    ("model_inspect", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_edit_body", "sweep body"),
                                 "include": ["default", "mass"], "units": "cm"},
     lambda p: _measured("sweep body after the identical-geometry edit", {
         "volume": (p.get("mass") or {}).get("volume"), "min_point": p.get("min_point"),
         "max_point": p.get("max_point"), "before": _RECALL["sweep_side_before"]},
         _near((p.get("mass") or {}).get("volume"), _RECALL["sweep_side_before"]["volume"], 0.0001)
         and all(_near((p.get(corner) or {}).get(axis),
                       _RECALL["sweep_side_before"][corner][axis], 0.0001)
                 for corner in ("min_point", "max_point") for axis in "xyz")), None),
    ("model_edit_sweep", {"feature": "SweepCameo/Sweep1", "action": "path",
                          "path": "sketch:SweepPathArc"},
     _sweep_edit_at_volume(math.pi * 0.8 ** 2 * 5 * math.pi / 2), None),
    ("model_inspect", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_edit_body", "sweep body"),
                                 "include": ["mass"], "units": "cm"},
     _sweep_inspected_at_volume(math.pi * 0.8 ** 2 * 5 * math.pi / 2), None),
    ("model_inspect", lambda c: {"target": _ctx_get(c, "sweep_dependent_handle", "dependent handle"),
                                 "include": ["default", "mass"], "units": "cm"},
     _sweep_dependent_survived(True), None),
    ("find_geometry", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_brep_strip", "strip"),
                                  "kind": "line_edge", "nearest_to": [250, 0, 5],
                                  "max_results": 1}, _matched(1, "line_edge"), _fg("sweep_brep_line")),
    ("find_geometry", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_brep_strip", "strip"),
                                  "kind": "arc_edge", "nearest_to": [251, 0, 13],
                                  "max_results": 1}, _matched(1, "arc_edge"), _fg("sweep_brep_arc")),
    ("model_edit_sweep", lambda c: {"feature": "SweepCameo/Sweep1", "action": "path",
                                       "path": [_ctx_get(c, "sweep_brep_line", "strip line"),
                                                _ctx_get(c, "sweep_brep_arc", "strip arc")]},
     _sweep_brep_list_edited, None),
    ("model_inspect", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_edit_body", "sweep body"),
                                 "include": ["mass"], "units": "cm"},
     _sweep_inspected_at_volume(math.pi * 0.8 ** 2 * (1 + math.pi / 4)), None),
    ("model_edit_sweep", {"feature": "SweepCameo/Sweep1", "action": "path",
                          "path": "sketch:SweepPath", "profile": {"sketch": "SweepProf", "profile_index": 0}},
     _refused("unused"), None),
    ("model_inspect", lambda c: {"target": "SweepCameo:" + _ctx_get(c, "sweep_edit_body", "sweep body"),
                                 "include": ["mass"], "units": "cm"},
     _sweep_inspected_at_volume(math.pi * 0.8 ** 2 * (1 + math.pi / 4)), None),
    ("model_inspect", lambda c: {"target": "LoftCameo:" + _ctx_get(
        c, "sweep_edit_witness_body", "loft witness"), "include": ["mass"], "units": "cm"},
     lambda p: _measured("untouched loft witness", {"volume_cm3": (p.get("mass") or {}).get("volume")},
                         _num((p.get("mass") or {}).get("volume")) and _near(
                             p["mass"]["volume"], _RECALL["sweep_edit_witness_volume"], 0.001)),
     None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # THE GUIDE SCOPE: a sketch name is only unique INSIDE a component, so two components each hold
    # one called 'Spine' and the loft below has to be told which one its rail lives in.
    ("model_create_component", {"name": "GuideRail", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "GuideBase"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 420, "cy": 0, "radius": 16}],
                             "sketch_name": "GuideBase"}, "ok", None),
    ("sketch_get", {"sketch_name": "GuideBase"}, "ok", _prof("guide_base")),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 40, "name": "GuideTopPlane"},
     _datum_plane("xy"), None),
    ("sketch_create", {"plane": "GuideTopPlane", "name": "GuideTop"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 420, "cy": 0, "radius": 8}],
                             "sketch_name": "GuideTop"}, "ok", None),
    ("sketch_get", {"sketch_name": "GuideTop"}, "ok", _prof("guide_top")),
    # the rail climbs from the base circle's rim to the top circle's: z runs along the xy sketch's
    # own normal, which is where the offset plane above put the top section.
    ("sketch_create", {"plane": "xy", "name": "Spine"}, "ok", None),
    ("sketch_add_3d_line", {"sketch_name": "Spine", "component": "GuideRail",
                            "x1": 436, "y1": 0, "z1": 0, "x2": 428, "y2": 0, "z2": 40},
     "ok", None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "GuideDupe", "activate": True}, _made_component, None),
    # The DRAWN sketch carries a name of its own: the framing pass writes a camera row per sketch it
    # sees drawn, and view_set refuses a 'focus' that two sketches answer to.
    ("sketch_create", {"plane": "xy", "name": "DupeMark"}, "ok", None),
    ("sketch_add_3d_line", {"sketch_name": "DupeMark", "component": "GuideDupe",
                            "x1": 520, "y1": 0, "z1": 0, "x2": 520, "y2": 20, "z2": 10},
     "ok", None),
    # the SAME name in the second component, left EMPTY - nothing draws on it, so it is no framing
    # subject. Asserted: a name Fusion had deduped would leave every refusal below testing nothing.
    ("sketch_create", {"plane": "xy", "name": "Spine"},
     lambda p: _measured("the duplicate guide name survived the create",
                         {"sketch_name": p.get("sketch_name"),
                          "rename_warning": p.get("rename_warning")},
                         p.get("sketch_name") == "Spine" and "rename_warning" not in p), None),
    ("design_activate_component", {"occurrence": "GuideRail:1"}, "ok", None),
    # un-scoped, the rail's sketch name answers to two sketches and the loft refuses rather than
    # picking one - naming the scope that narrows the GUIDES, which is the one this call can pass.
    ("model_loft", lambda c: {"profiles": [_ctx_get(c, "guide_base", "the guide loft's base"),
                                           _ctx_get(c, "guide_top", "the guide loft's top")],
                              "rails": ["Spine/line:0"]},
     _refused("2 sketches are named 'Spine'", "'guide_component'"), None),
    # a scope that owns no sketch of that name refuses NAMING the scope - 'GuideBase' answers to
    # exactly one sketch design-wide, so dropping the scope would loft along another component's
    # curve and say nothing.
    ("model_loft", lambda c: {"profiles": [_ctx_get(c, "guide_base", "the guide loft's base"),
                                           _ctx_get(c, "guide_top", "the guide loft's top")],
                              "rails": ["GuideBase/circle:0"], "guide_component": "GuideDupe"},
     _refused("GuideDupe", "no sketch named 'GuideBase'", "GuideRail"), None),
    # scoped, the same call builds: the rail resolves inside GuideRail, whose 'Spine' is the line
    # that touches both sections (GuideDupe's runs off sideways and would fail the add).
    ("model_loft", lambda c: {"profiles": [_ctx_get(c, "guide_base", "the guide loft's base"),
                                           _ctx_get(c, "guide_top", "the guide loft's top")],
                              "rails": ["Spine/line:0"], "guide_component": "GuideRail"},
     lambda p: _measured("loft along the component-scoped guide",
                         {"feature": p.get("feature"), "result_bodies": p.get("result_bodies"),
                          "rails_count": p.get("rails_count")},
                         bool(p.get("feature")) and bool(p.get("result_bodies"))
                         and p.get("rails_count") == 1), None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # the part is whole: frame IT for the colouring beats, not the metre-wide cameo grid.
    _watch("Bracket:1"),
    ("appearance_set", {"target": "Bracket", "color": "#5E6AD2"}, "ok", None),
    ("appearance_set", {"target": "LoftCameo", "color": "#8A94A6"}, "ok", None),
    ("appearance_set", {"target": "SweepCameo", "color": "#F5A623"}, "ok", None),
    ("model_set_material", {"target": "Bracket:1", "material": "Steel"}, _material_assigned, None),
    # a miss whose catalog carries the actual entry ('Steel AISI 4130 259 QT') alongside several
    # same-prefix decoys ('Steel AISI 1060/1061/...') - the CONTAINING name is what the Nearest
    # list has to lead with, not the decoys difflib's edit distance would rank ahead of it.
    ("model_set_material", {"target": "Bracket:1", "material": "Steel AISI 4130"},
     _refused("Nearest: 'Steel AISI 4130 259 QT'"), None),
    # honest reads on the real part: the boss wall to its own bore, the two of them coaxial, and
    # the part's measured extent.
    ("find_geometry", {"target": "Bracket", "kind": "cylinder_face", "radius": 10,
                       "max_results": 1}, _matched(1, "cylinder_face"), _fg("boss_wall")),
    # the bore INSIDE that boss, pinned by position: the part carries two of this diameter, and the
    # coaxial read below is only a claim about the boss if it picked the boss's own.
    ("find_geometry", {"target": "Bracket", "kind": "cylinder_face", "radius": 6,
                       "nearest_to": [45, 0, 42], "max_results": 1},
     _matched(1, "cylinder_face"), _fg("bore_wall")),
    ("model_measure_between", lambda c: {"a": _ctx_get(c, "boss_wall", "the boss wall"),
                                         "b": _ctx_get(c, "bore_wall", "the bore wall")},
     _gap_measured, None),
    ("model_measure_relation", lambda c: {"relation": "coaxial",
                                          "entity_a": _ctx_get(c, "boss_wall", "the boss wall"),
                                          "entity_b": _ctx_get(c, "bore_wall", "the bore wall")},
     _relation_measured("coaxial"), None),
    ("model_inspect", {"target": "Bracket:1"}, _extent_measured, None),
    # THE PART'S ENGINEERING IDENTITY: Fusion mints a part number of its own for every component, so
    # the read comes first and shows what is there; the set then replaces it with the shop's, and
    # the second read is the independent confirmation that the value is the component's own.
    ("design_get", {"include": ["metadata"]}, _component_metadata("Bracket"), None),
    ("design_set_metadata", {"target": "Bracket", "part_number": "FE-BRACKET-001",
                             "description": "Sweep bracket"},
     _metadata_set("Bracket", "FE-BRACKET-001", "Sweep bracket"), None),
    ("design_get", {"include": ["metadata", "tree"], "name_filter": "Bracket"},
     lambda p: _component_metadata("Bracket", part_number="FE-BRACKET-001",
                                  description="Sweep bracket")(p)
     and [r.get("name") for r in (p.get("metadata") or {}).get("components") or []] == ["Bracket"]
     and _measured("tree filter selects only the Bracket placement",
                   (p.get("tree") or {}).get("children"),
                   (p.get("tree") or {}).get("matched") == 1
                   and [(r.get("name"), r.get("component")) for r in
                        (p.get("tree") or {}).get("children") or []] == [("Bracket:1", "Bracket")]),
     None),
    # PMI CONTENT writes need the Design or Manufacturing Extension (the platform raises
    # "Manufacturing or Design Extension is required" without one - measured on the lapsed install),
    # so the four write rows run entitled and assert the created/edited/deleted values read back off
    # the annotations, while the unentitled variants assert the refusal names the extension and the
    # next step. Reads and the blank-name guards run on either licence.
    ("find_geometry", {"target": "Bracket", "kind": "planar_face", "nearest_to": [-35, 0, 14],
                       "max_results": 1}, _face_up_at(-35, 0, 14, tol=2.0), _fg("pmi_floor")),
    ("pmi_create", lambda c: {"kind": "note", "geometry": [_ctx_get(c, "pmi_floor", "the pocket floor")], "text": "{flatness}0.05", "name": "PmiFlat"},
     _needs(MACHINING_EXTENSION, lambda p: p.get("annotation") == "PmiFlat" and p.get("markup") == "{flatness}0.05" and p.get("kind") == "note"), None),
    ("pmi_create", lambda c: {"kind": "note", "geometry": [_ctx_get(c, "pmi_floor", "the pocket floor")], "text": "{flatness}0.05", "name": "PmiFlat"},
     _unless(MACHINING_EXTENSION,
             _refused("Extension is required", "This operation requires", "pmi_get")), None),
    ("find_geometry", {"target": "Bracket", "kind": "cylinder_face", "radius": 3, "max_results": 1},
     _matched(1, "cylinder_face"), _fg("mount_bore")),
    ("pmi_create", lambda c: {"kind": "hole_note", "geometry": [_ctx_get(c, "mount_bore", "a mounting bore")]},
     _needs(MACHINING_EXTENSION, lambda p: p.get("kind") == "hole_note" and bool(p.get("annotation")) and "<HDIA>" in str(p.get("markup"))), None),
    ("pmi_create", lambda c: {"kind": "hole_note", "geometry": [_ctx_get(c, "mount_bore", "a mounting bore")]},
     _unless(MACHINING_EXTENSION,
             _refused("Extension is required", "This operation requires", "pmi_get")), None),
    # requested values and display differ from the bore's nominal, so the independent read below
    # cannot pass on the nominal masquerading as the set.
    ("pmi_create", lambda c: {"kind": "hole_note", "geometry": [_ctx_get(c, "mount_bore", "a mounting bore")],
                              "name": "SweepHoleNote", "units": "mm",
                              "values": {"depth": 4.5, "diameter": {"value": 4.2, "tolerance": {"type": "symmetric", "value": 0.05}}},
                              "display": {"precision": 2, "leading_zeros": True, "secondary": {"precision": 3, "units": "in"}}},
     _needs(MACHINING_EXTENSION, lambda p: p.get("annotation") == "SweepHoleNote" and p.get("kind") == "hole_note"), None),
    ("pmi_create", lambda c: {"kind": "hole_note", "geometry": [_ctx_get(c, "mount_bore", "a mounting bore")],
                              "name": "SweepHoleNote", "units": "mm",
                              "values": {"depth": 4.5, "diameter": {"value": 4.2, "tolerance": {"type": "symmetric", "value": 0.05}}},
                              "display": {"precision": 2, "leading_zeros": True, "secondary": {"precision": 3, "units": "in"}}},
     _unless(MACHINING_EXTENSION,
             _refused("Extension is required", "This operation requires", "pmi_get")), None),
    ("pmi_get", {"include": ["detail"]}, _needs(MACHINING_EXTENSION, _hole_note_detail), None),
    ("pmi_delete", {"annotation": "SweepHoleNote"},
     _needs(MACHINING_EXTENSION, lambda p: p.get("deleted") == "SweepHoleNote" and p.get("kind") == "hole_note"), None),
    ("pmi_get", {"include": ["segments", "detail"]}, "ok", None),
    # an over-cap 'max_results' is CLAMPED, not refused - pmi_get's own contract, since every record
    # it returns crosses the wire whole. The answer still comes back with its census keys.
    ("pmi_get", {"max_results": 99999},
     lambda p: isinstance(p.get("annotations"), list) and "total" in p, None),
    ("pmi_edit", {"action": "set_text", "annotation": "PmiFlat", "text": "{perpendicularity}0.03"},
     _needs(MACHINING_EXTENSION, lambda p: p.get("name") == "PmiFlat" and p.get("markup") == "{perpendicularity}0.03"), None),
    # the blank name is its own guard, ahead of any lookup - on either licence.
    ("pmi_edit", {"action": "hide", "annotation": ""}, "refused", None),
    ("pmi_delete", {"annotation": ""}, "refused", None),
    ("pmi_delete", {"annotation": "PmiFlat"},
     _needs(MACHINING_EXTENSION, lambda p: p.get("deleted") == "PmiFlat" and isinstance(p.get("remaining_pmi"), int)), None),
    # THE DATUM BENCH: one bored block, and every way the API knows of hanging a plane, an axis or a
    # point off it. The modes divide by what they READ, so the bench has to carry all of it - six
    # faces, the linear edges where they meet, the vertices where those meet, and a bore for the
    # curved-face and circular-edge modes. Each row's receipt is the created datum's OWN geometry:
    # every mode returns an object, and only the read-back distinguishes one that landed where the
    # mode says from one that landed anywhere at all.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "DatumBench", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "DBPad"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 200, "y1": 0,
                                           "x2": 260, "y2": 40}],
                             "sketch_name": "DBPad"}, "ok", None),
    ("model_extrude", {"sketch_name": "DBPad", "profile_index": 0, "distance": 20}, _extruded, None),
    ("find_geometry", {"target": "DatumBench", "kind": "planar_face", "nearest_to": [230, 20, 20],
                       "max_results": 1}, "ok", _fg("db_top")),
    ("model_hole", lambda c: {"face": _ctx_get(c, "db_top", "bench top face"), "hole_type": "simple",
                              "diameter": "10 mm", "extent": "through", "points": [[230, 20, 0]]},
     _drilled(1), None),
    # the reference set every mode below draws from, acquired once the bore exists so no handle is
    # stale: the top face, the bore, its rim, two coplanar top edges, one vertical edge that MEETS
    # one of them, and three top-face corners that form a triangle.
    ("find_geometry", {"target": "DatumBench", "kind": "planar_face", "nearest_to": [230, 20, 20],
                       "max_results": 1}, "ok", _fg("db_top2")),
    ("find_geometry", {"target": "DatumBench", "kind": "cylinder_face", "nearest_to": [230, 20, 10],
                       "max_results": 1}, "ok", _fg("db_bore")),
    ("find_geometry", {"target": "DatumBench", "kind": "circular_edge", "nearest_to": [230, 20, 20],
                       "max_results": 1}, "ok", _fg("db_rim")),
    ("find_geometry", {"target": "DatumBench", "kind": "line_edge", "nearest_to": [230, 0, 20],
                       "max_results": 1}, "ok", _fg("db_front")),
    ("find_geometry", {"target": "DatumBench", "kind": "line_edge", "nearest_to": [230, 40, 20],
                       "max_results": 1}, "ok", _fg("db_back")),
    ("find_geometry", {"target": "DatumBench", "kind": "line_edge", "nearest_to": [200, 0, 10],
                       "max_results": 1}, "ok", _fg("db_post")),
    ("find_geometry", {"target": "DatumBench", "kind": "vertex", "nearest_to": [200, 0, 20],
                       "max_results": 1}, "ok", _fg("db_c1")),
    ("find_geometry", {"target": "DatumBench", "kind": "vertex", "nearest_to": [260, 0, 20],
                       "max_results": 1}, "ok", _fg("db_c2")),
    ("find_geometry", {"target": "DatumBench", "kind": "vertex", "nearest_to": [200, 40, 20],
                       "max_results": 1}, "ok", _fg("db_c3")),
    # the bore's seam vertex - a point that sits ON the cylindrical face, which is what a tangent
    # plane needs. A box corner is not on the bore, and the tangency has nowhere to land.
    ("find_geometry", {"target": "DatumBench", "kind": "vertex", "nearest_to": [230, 20, 20],
                       "max_results": 1}, "ok", _fg("db_seam")),
    # PLANES. at_angle swings the XY plane about a top edge; three_points spans the three corners;
    # midplane splits XY and the top face, landing halfway up the block; two_edges spans the two
    # coplanar top edges; tangent_at_point rests on the bore wall.
    ("model_construction", lambda c: {"kind": "plane", "mode": "at_angle", "plane": "xy",
                                      "edges": [_ctx_get(c, "db_front", "bench front top edge")],
                                      "angle": 30, "name": "DBAngle"},
     lambda p: _datum("plane")(p) and _measured("swung off the base plane's normal",
                                                {"normal_changed": p.get("normal_changed")},
                                                p.get("normal_changed") is True), None),
    # a long-decimal angle: the plane's own parameter must hold every digit, read back separately.
    ("model_construction", lambda c: {"kind": "plane", "mode": "at_angle", "plane": "xy",
                                      "edges": [_ctx_get(c, "db_front", "bench front top edge")],
                                      "angle": _FINE_ANGLE_DEG, "name": "DBAngleFine"},
     _fine_angle_plane,
     ("db_fine_param", _recall("db_fine_param", lambda p: p["model_parameters"]["angle"]))),
    ("param_get", lambda c: {"name": _ctx_get(c, "db_fine_param", "the fine plane's parameter")},
     _fine_angle_param, None),
    ("model_construction", lambda c: {"kind": "plane", "mode": "three_points",
                                      "points": [_ctx_get(c, "db_c1", "bench corner 1"),
                                                 _ctx_get(c, "db_c2", "bench corner 2"),
                                                 _ctx_get(c, "db_c3", "bench corner 3")],
                                      "name": "DBTri"}, _datum("plane"), None),
    ("model_construction", lambda c: {"kind": "plane", "mode": "midplane", "plane": "xy",
                                      "plane2": _ctx_get(c, "db_top2", "bench top face"),
                                      "name": "DBMid"}, _datum("plane"), None),
    ("model_construction", lambda c: {"kind": "plane", "mode": "two_edges",
                                      "edges": [_ctx_get(c, "db_front", "bench front top edge"),
                                                _ctx_get(c, "db_back", "bench back top edge")],
                                      "name": "DBSpan"}, _datum("plane"), None),
    ("model_construction", lambda c: {"kind": "plane", "mode": "tangent_at_point",
                                      "face": _ctx_get(c, "db_bore", "bench bore"),
                                      "points": [_ctx_get(c, "db_seam", "bench bore seam vertex")],
                                      "name": "DBTangent"}, _datum("plane"), None),
    # AXES. An edge IS an axis; two corners span one; the bore's own centreline; and the normal of
    # the top face taken at a corner sitting on it.
    ("model_construction", lambda c: {"kind": "axis", "mode": "edge",
                                      "axis": _ctx_get(c, "db_front", "bench front top edge"),
                                      "name": "DBEdgeAxis"}, _datum("axis"), None),
    ("model_construction", lambda c: {"kind": "axis", "mode": "two_points",
                                      "points": [_ctx_get(c, "db_c1", "bench corner 1"),
                                                 _ctx_get(c, "db_c3", "bench corner 3")],
                                      "name": "DBSpanAxis"}, _datum("axis"), None),
    ("model_construction", lambda c: {"kind": "axis", "mode": "perpendicular_at_point",
                                      "face": _ctx_get(c, "db_top2", "bench top face"),
                                      "points": [_ctx_get(c, "db_c2", "bench corner 2")],
                                      "name": "DBNormalAxis"},
     lambda p: _datum("axis")(p) and _measured("axis along the face normal",
                                               {"aligned": p.get("aligned_to_face_normal")},
                                               p.get("aligned_to_face_normal") is True), None),
    # a world axis through a coordinate is setByLine, which is DIRECT-edit-only - this design is
    # parametric, so the mode is refused up front with the parametric routes named.
    ("model_construction", {"kind": "axis", "mode": "world", "axis": "x", "x": 200, "y": 0, "z": 0,
                            "name": "DBWorldAxis"}, "refused", None),
    # POINTS. The bore rim's centre; the corner where a top edge meets the post below it; the origin
    # the three world planes share; and where the post pierces XY.
    ("model_construction", lambda c: {"kind": "point", "mode": "circle_center",
                                      "edges": [_ctx_get(c, "db_rim", "bench bore rim")],
                                      "name": "DBBoreCentre"}, _datum("point"), None),
    ("model_construction", lambda c: {"kind": "point", "mode": "two_edges",
                                      "edges": [_ctx_get(c, "db_front", "bench front top edge"),
                                                _ctx_get(c, "db_post", "bench corner post")],
                                      "name": "DBCorner"}, _datum("point"), None),
    ("model_construction", {"kind": "point", "mode": "three_planes", "plane": "xy", "plane2": "xz",
                            "plane3": "yz", "name": "DBOrigin"}, _datum("point"), None),
    ("model_construction", lambda c: {"kind": "point", "mode": "edge_plane",
                                      "edges": [_ctx_get(c, "db_post", "bench corner post")],
                                      "plane": "xy", "name": "DBFoot"}, _datum("point"), None),
    # the coordinate point is setByPoint - direct-edit-only for the same reason as the world axis.
    ("model_construction", {"kind": "point", "mode": "coordinate", "x": 230, "y": 20, "z": 40,
                            "name": "DBCoord"}, "refused", None),
    # THE RELATION VOCABULARY, on the same block. Each relation reports a DIFFERENT measurement -
    # an angle for the alignments, a distance for the fits - and the pairs here are chosen so the
    # geometry, not the tool, settles the verdict: a face is flush with itself, a bore concentric
    # with itself, the top face perpendicular to a wall it meets and touching it along that edge,
    # and 20 mm clear of the floor below it.
    ("find_geometry", {"target": "DatumBench", "kind": "planar_face", "nearest_to": [200, 20, 10],
                       "max_results": 1}, "ok", _fg("db_wall")),
    ("find_geometry", {"target": "DatumBench", "kind": "planar_face", "nearest_to": [230, 20, 0],
                       "max_results": 1}, "ok", _fg("db_floor")),
    ("model_measure_relation", lambda c: {"relation": "perpendicular",
                                          "entity_a": _ctx_get(c, "db_top2", "bench top face"),
                                          "entity_b": _ctx_get(c, "db_wall", "bench wall")},
     _relation_passes("perpendicular"), None),
    ("model_measure_relation", lambda c: {"relation": "flush",
                                          "entity_a": _ctx_get(c, "db_top2", "bench top face"),
                                          "entity_b": _ctx_get(c, "db_top2", "bench top face")},
     _relation_read("flush", "normal_angle_deg"), None),
    ("model_measure_relation", lambda c: {"relation": "concentric",
                                          "entity_a": _ctx_get(c, "db_bore", "bench bore"),
                                          "entity_b": _ctx_get(c, "db_bore", "bench bore")},
     _relation_read("concentric", "center_distance"), None),
    ("model_measure_relation", lambda c: {"relation": "touching",
                                          "entity_a": _ctx_get(c, "db_top2", "bench top face"),
                                          "entity_b": _ctx_get(c, "db_wall", "bench wall")},
     _relation_read("touching", "min_distance"), None),
    ("model_measure_relation", lambda c: {"relation": "clearance",
                                          "entity_a": _ctx_get(c, "db_top2", "bench top face"),
                                          "entity_b": _ctx_get(c, "db_floor", "bench floor")},
     _relation_read("clearance", "min_distance"), None),
    # HOLE-HOST-1: two drillable B solids share z=0, while a separate A plate stays active. The
    # layout pass gives B and A different cells; the hole callables compensate for A's wrapper
    # offset so the world points land in B exactly once while every acquired handle stays unchanged.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": _HOLE_HOST, "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "Plate-upper"}, "ok", None),
    ("sketch_add_geometry",
     {"geometry": [{"kind": "rectangle", "x1": _HOLE_X0, "y1": 0,
                    "x2": _HOLE_X0 + 20, "y2": 20}], "sketch_name": "Plate-upper"}, "ok", None),
    ("model_extrude", {"sketch_name": "Plate-upper", "profile_index": 0, "distance": 10},
     _extruded, None),
    ("sketch_create", {"plane": "xy", "name": "Plate-lower"}, "ok", None),
    ("sketch_add_geometry",
     {"geometry": [{"kind": "rectangle", "x1": _HOLE_X0, "y1": 0,
                    "x2": _HOLE_X0 + 20, "y2": 20}], "sketch_name": "Plate-lower"}, "ok", None),
    ("model_extrude", {"sketch_name": "Plate-lower", "profile_index": 0, "distance": -10},
     _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": _HOLE_ACTIVE, "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "Active-A-Plate"}, "ok", None),
    ("sketch_add_geometry",
     {"geometry": [{"kind": "rectangle", "x1": _HOLE_ACTIVE_X0, "y1": 0,
                    "x2": _HOLE_ACTIVE_X0 + 20, "y2": 20}],
      "sketch_name": "Active-A-Plate"}, "ok", None),
    ("model_extrude", {"sketch_name": "Active-A-Plate", "profile_index": 0, "distance": 10},
     _extruded, None),
    ("design_activate_component", {"occurrence": _HOLE_ACTIVE + ":1"},
     lambda p: (p.get("activated") == _HOLE_ACTIVE + ":1"
                and p.get("active_occurrence") == _HOLE_ACTIVE + ":1"
                and p.get("active_component") == _HOLE_ACTIVE), None),
    # The participant is a fresh body handle from a component-rooted tree read. Component scopes
    # only the tree; the separate timeline reads below use their own explicit full-list bound.
    ("design_get", {"include": ["tree"], "component": _HOLE_HOST,
                    "tree_bodies": True, "max_results": 10},
     _hole_host_tree, ("hh_upper", _hole_upper_handle)),
    ("design_get", {"include": ["tree"], "component": _HOLE_HOST,
                    "tree_bodies": True, "max_results": 10},
     _hole_host_tree, ("hh_lower", _hole_lower_handle)),
    ("design_get", {"include": ["tree"], "component": _HOLE_ACTIVE,
                    "tree_bodies": True, "max_results": 10},
     _hole_active_tree, ("hh_active", _hole_active_handle)),
    ("model_inspect", lambda c: _hole_inspect_args(c, "hh_upper"),
     _hole_body_state(_HOLE_HOST, (_HOLE_X0, 0, 0), (_HOLE_X0 + 20, 20, 10), 4000.0),
     None),
    ("model_inspect", lambda c: _hole_inspect_args(c, "hh_lower"),
     _hole_body_state(_HOLE_HOST, (_HOLE_X0, 0, -10), (_HOLE_X0 + 20, 20, 0), 4000.0),
     None),
    ("model_inspect", lambda c: _hole_inspect_args(c, "hh_active"),
     _hole_body_state(_HOLE_ACTIVE, (_HOLE_ACTIVE_X0, 0, 0),
                      (_HOLE_ACTIVE_X0 + 20, 20, 10), 4000.0), None),
    ("find_geometry", lambda c: _hole_cylinder_args(c, "hh_upper"),
     _hole_cylinders(_HOLE_HOST, ()), None),
    ("find_geometry", lambda c: _hole_cylinder_args(c, "hh_lower"),
     _hole_cylinders(_HOLE_HOST, ()), None),
    ("find_geometry", lambda c: _hole_cylinder_args(c, "hh_active"),
     _hole_cylinders(_HOLE_ACTIVE, ()), None),
    ("find_geometry", _scoped_top_args,
     lambda p: _face_up_at(_px(_HOLE_HOST, _HOLE_X0 + 10),
                           _py(_HOLE_HOST, 10), 10)(p), _fg("hh_top")),
    ("model_hole", _scoped_hole_args, _hole_created(True), None),
    # The scoped cut removes exactly one 4 mm x 10 mm bore from upper B. Lower B and active A keep
    # their original bounds, volume and empty cylinder censuses.
    ("model_inspect", lambda c: _hole_inspect_args(c, "hh_upper"),
     _hole_body_state(_HOLE_HOST, (_HOLE_X0, 0, 0), (_HOLE_X0 + 20, 20, 10),
                      4000.0 - _HOLE_VOLUME), None),
    ("model_inspect", lambda c: _hole_inspect_args(c, "hh_lower"),
     _hole_body_state(_HOLE_HOST, (_HOLE_X0, 0, -10), (_HOLE_X0 + 20, 20, 0), 4000.0),
     None),
    ("model_inspect", lambda c: _hole_inspect_args(c, "hh_active"),
     _hole_body_state(_HOLE_ACTIVE, (_HOLE_ACTIVE_X0, 0, 0),
                      (_HOLE_ACTIVE_X0 + 20, 20, 10), 4000.0), None),
    ("find_geometry", lambda c: _hole_cylinder_args(c, "hh_upper"),
     _hole_cylinders(_HOLE_HOST, ((_HOLE_X0 + 10, 10, 5),)), None),
    ("find_geometry", lambda c: _hole_cylinder_args(c, "hh_lower"),
     _hole_cylinders(_HOLE_HOST, ()), None),
    ("find_geometry", lambda c: _hole_cylinder_args(c, "hh_active"),
     _hole_cylinders(_HOLE_ACTIVE, ()), None),
    # Reacquire the new bore after the write and consume its real handle. Its 4 x 4 x 10 mm bounds
    # prove radius, depth and world location independently of model_hole's participant echo.
    ("find_geometry", _scoped_bore_args,
     _hole_cylinders(_HOLE_HOST, ((_HOLE_X0 + 10, 10, 5),)), _fg("hh_bore")),
    ("model_inspect", lambda c: {"target": _ctx_get(c, "hh_bore", "fresh scoped bore face"),
                                 "units": "mm"}, _hole_face_bounds, None),
    ("design_get", {"include": ["timeline"], "max_results": 2000},
     _hole_timeline(False), None),
    # Positive control: A is explicitly active again and target_bodies is omitted. Both stacked B
    # bodies lose one bore, proving the lower body was drillable; A still does not change.
    ("design_activate_component", {"occurrence": _HOLE_ACTIVE + ":1"},
     lambda p: (p.get("activated") == _HOLE_ACTIVE + ":1"
                and p.get("active_occurrence") == _HOLE_ACTIVE + ":1"
                and p.get("active_component") == _HOLE_ACTIVE), None),
    ("find_geometry", _control_top_args,
     lambda p: _face_up_at(_px(_HOLE_HOST, _HOLE_X0 + 10),
                           _py(_HOLE_HOST, 10), 10, tol=2.0)(p), _fg("hh_top_control")),
    ("model_hole", _unscoped_hole_args, _hole_created(False), None),
    ("model_inspect", lambda c: _hole_inspect_args(c, "hh_upper"),
     _hole_body_state(_HOLE_HOST, (_HOLE_X0, 0, 0), (_HOLE_X0 + 20, 20, 10),
                      4000.0 - 2 * _HOLE_VOLUME), None),
    ("model_inspect", lambda c: _hole_inspect_args(c, "hh_lower"),
     _hole_body_state(_HOLE_HOST, (_HOLE_X0, 0, -10), (_HOLE_X0 + 20, 20, 0),
                      4000.0 - _HOLE_VOLUME), None),
    ("model_inspect", lambda c: _hole_inspect_args(c, "hh_active"),
     _hole_body_state(_HOLE_ACTIVE, (_HOLE_ACTIVE_X0, 0, 0),
                      (_HOLE_ACTIVE_X0 + 20, 20, 10), 4000.0), None),
    ("find_geometry", lambda c: _hole_cylinder_args(c, "hh_upper"),
     _hole_cylinders(_HOLE_HOST, ((_HOLE_X0 + 5, 5, 5),
                                  (_HOLE_X0 + 10, 10, 5))), None),
    ("find_geometry", lambda c: _hole_cylinder_args(c, "hh_lower"),
     _hole_cylinders(_HOLE_HOST, ((_HOLE_X0 + 5, 5, -5),)), None),
    ("find_geometry", lambda c: _hole_cylinder_args(c, "hh_active"),
     _hole_cylinders(_HOLE_ACTIVE, ()), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000},
     _hole_timeline(True), None),
    # feature cameos on same-doc scratch bodies (no natural home on the part for these verbs).
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "FeatureCameo", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "FCPad"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 200, "y1": 0,
                                           "x2": 240, "y2": 40}],
                             "sketch_name": "FCPad"}, "ok", None),
    ("model_extrude", {"sketch_name": "FCPad", "profile_index": 0, "distance": 20}, _extruded, None),
    _watch("FeatureCameo:1"),
    ("find_geometry", {"target": "FeatureCameo", "kind": "planar_face", "nearest_to": [200, 20, 10], "max_results": 1}, "ok", _fg("fc_side")),
    ("model_draft", lambda c: {"faces": [_ctx_get(c, "fc_side", "cameo side face")], "pull_direction": "xy", "angle_deg": 3},
     _drafted, None),
    # The three PIVOT gates: a write whose pull plane / replacement surface / edge set meets the
    # geometry at its MIDDLE adds exactly what it cuts, so the volume holds to the last bit. Each
    # of these was a false refusal until the boundary read joined the material one.
    ("model_create_component", {"name": "PivotCameo", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "PvL"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": "PvL", "geometry": [
        {"kind": "closed_path", "points": [[300, 0], [340, 0], [340, 20], [320, 20], [320, 40],
                                           [300, 40]]}]}, "ok", None),
    ("model_extrude", {"sketch_name": "PvL", "profile_index": 0, "distance": 30}, _extruded, None),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 15, "name": "PvMid"},
     _datum_plane("xy"), None),
    # Each gate gets its OWN face, so none disturbs another and nothing has to be deleted: a fillet
    # standing on a drafted face eats a strip off it, which both spoils the pivot (measured: the
    # volume moves -0.000615 cm3) and consumes the input wrapper (faces_compared 0).
    # ONE-SIDED about a plane CROSSING the face: it pivots there, tilting the face while the volume
    # holds to the last bit - the case the material gate alone refused.
    ("find_geometry", {"target": "PivotCameo", "kind": "planar_face", "nearest_to": [300, 20, 15],
                       "max_results": 1}, "ok", _fg("pv_face")),
    ("model_draft", lambda c: {"faces": [_ctx_get(c, "pv_face", "the face the plane crosses")],
                               "pull_direction": "PvMid", "angle_deg": 5, "tangent_chain": False},
     _drafted_on_its_pivot, None),
    # SYMMETRIC, on the next face round: it SPLITS that face at the plane (faces_drafted 2 from one
    # requested) and, measured here, tapers both halves the same way - so the volume MOVES. This
    # branch carries its own verdict, not an exemption.
    ("find_geometry", {"target": "PivotCameo", "kind": "planar_face", "nearest_to": [320, 0, 15],
                       "max_results": 1}, "ok", _fg("pv_sym_face")),
    ("model_draft", lambda c: {"faces": [_ctx_get(c, "pv_sym_face", "the y=0 face")],
                               "pull_direction": "PvMid", "angle_deg": 5, "symmetric": True,
                               "tangent_chain": False}, _drafted_symmetric, None),
    # one CONVEX and one CONCAVE vertical edge, same length and radius, both on faces no draft
    # touched: the wedge cut off the first is the wedge filled into the second, so only the surface
    # area moves.
    ("find_geometry", {"target": "PivotCameo", "kind": "line_edge", "nearest_to": [340, 20, 15],
                       "max_results": 1}, "ok", _fg("pv_convex")),
    ("find_geometry", {"target": "PivotCameo", "kind": "line_edge", "nearest_to": [320, 20, 15],
                       "max_results": 1}, "ok", _fg("pv_concave")),
    ("model_fillet", lambda c: {"edges": [_ctx_get(c, "pv_convex", "the outer corner"),
                                          _ctx_get(c, "pv_concave", "the inner corner")],
                                "radius": 5, "tangent_chain": False}, _cut_on_its_pivot, None),
    # A sketch on a FACE has no construction plane to name. Both the write that makes it and the
    # read that returns to it name the BODY and carry that face's own handle instead of plane null;
    # the read gets there by rolling the marker to the sketch and putting it back, because
    # referencePlane answers a BRepFace only from there.
    ("find_geometry", {"target": "PivotCameo", "kind": "planar_face", "nearest_to": [310, 30, 30],
                       "max_results": 1}, "ok", _fg("pv_lid")),
    ("sketch_create", lambda c: {"on_face": _ctx_get(c, "pv_lid", "the L-prism lid"),
                                 "name": "PvOnFace"}, _face_sketch_disclosure, None),
    ("sketch_get", {"sketch_name": "PvOnFace"},
     lambda p: _sits_on_a_face(p) and "timeline_marker_unrestored" not in p,
     ("pv_face_handle", lambda p: p["on_face"]["handle"])),
    # the handle that read CONSUMED: fed straight back as a face handle, it pushes that same face.
    ("model_offset_face", lambda c: {"faces": [_ctx_get(c, "pv_face_handle", "the sketch's face")],
                                     "distance": 2}, _offset_faces, None),
    # the third pivot gate, in this same component so the block and the sheet share one cell: a
    # replacement surface TILTED about the middle of the face it replaces adds exactly what it cuts,
    # so volume AND face count both hold and only the area moves.
    ("sketch_create", {"plane": "xy", "name": "PvBlkS"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": "PvBlkS", "geometry": [
        {"kind": "rectangle", "x1": 360, "y1": 0, "x2": 390, "y2": 30}]}, "ok", None),
    ("model_extrude", {"sketch_name": "PvBlkS", "profile_index": 0, "distance": 20},
     _extruded, None),
    ("sketch_create", {"plane": "xz", "name": "PvRoofS"}, "ok", None),
    # sketch +Y maps to world -Z here, so these two points put the sheet at world z 16 -> 24,
    # crossing the block's z=20 top at x=375 - the middle of that face.
    ("sketch_add_geometry", {"sketch_name": "PvRoofS", "geometry": [
        {"kind": "line", "x1": 355, "y1": -16, "x2": 395, "y2": -24}]}, "ok", None),
    ("surface_extrude", {"sketch_name": "PvRoofS", "distance": 80, "symmetric": True},
     lambda p: p.get("is_solid") is False, ("pv_sheet_body", lambda p: p["result_bodies"][0])),
    ("find_geometry", {"target": "PivotCameo", "kind": "planar_face", "nearest_to": [375, 15, 20],
                       "max_results": 1}, "ok", _fg("pv_top")),
    ("model_replace_face", lambda c: {"faces": [_ctx_get(c, "pv_top", "the block top")],
                                      "target": "PivotCameo:" + _ctx_get(c, "pv_sheet_body", "the tilted sheet")},
     _replaced_on_its_pivot, None),
    ("design_activate_component", {"occurrence": "FeatureCameo:1"}, "ok", None),
    ("find_geometry", {"target": "FeatureCameo", "kind": "planar_face", "nearest_to": [220, 20, 20], "max_results": 1}, "ok", _fg("fc_top")),
    # hole points are in the FACE'S LOCAL frame, whose origin for this face is the MODEL origin
    # projected onto its plane - so on-pad coordinates are the world x,y. ([5,5] here drilled at
    # world (5,5), a point off this pad entirely: the hole silently cut whatever body sat near
    # the origin, and the axis-count read-back cannot see a wrong-body cut. Measured live.)
    ("model_hole", lambda c: {"face": _ctx_get(c, "fc_top", "cameo top face"), "hole_type": "simple", "diameter": "4 mm", "extent": "blind", "depth": "8 mm", "points": [[220, 20, 0]]}, _drilled(1), None),
    # the three additive placement modes. Each act re-acquires its own edge: the center act below
    # consumes the 4 mm rim by drilling an 8 mm bore concentric with it, so a handle captured once
    # and reused would be pointing at geometry that no longer exists.
    ("find_geometry", {"target": "FeatureCameo", "kind": "circular_edge", "radius": 2,
                       "nearest_to": [220, 20, 20], "max_results": 1}, "ok", _fg("fc_hole_edge")),
    ("model_hole", lambda c: {"face": _ctx_get(c, "fc_top", "cameo top face"),
                              "placement": "center", "edge": _ctx_get(c, "fc_hole_edge", "hole rim"),
                              "diameter": "8 mm", "extent": "blind", "depth": "3 mm"},
     lambda p: p.get("placement") == "center" and p.get("holes_verified") is True, None),
    ("find_geometry", {"target": "FeatureCameo", "kind": "line_edge", "nearest_to": [220, 0, 20],
                       "max_results": 1}, "ok", _fg("fc_edge")),
    ("model_hole", lambda c: {"face": _ctx_get(c, "fc_top", "cameo top face"),
                              "placement": "on_edge", "edge": _ctx_get(c, "fc_edge", "pad edge"),
                              "edge_position": "middle", "diameter": "3 mm",
                              "extent": "blind", "depth": "3 mm"},
     lambda p: p.get("placement") == "on_edge", None),
    # on_edge at the edge's START vertex - RE-ACQUIRED first: the middle-hole above SPLITS the
    # pad edge (measured: a handle captured before that hole resolves to 2 sub-edges and is
    # refused as stale), so every act re-acquires its own edge.
    ("find_geometry", {"target": "FeatureCameo", "kind": "line_edge", "nearest_to": [220, 0, 20],
                       "max_results": 1}, "ok", _fg("fc_edge2")),
    ("model_hole", lambda c: {"face": _ctx_get(c, "fc_top", "cameo top face"),
                              "placement": "on_edge", "edge": _ctx_get(c, "fc_edge2", "pad edge"),
                              "edge_position": "start", "diameter": "3 mm",
                              "extent": "blind", "depth": "3 mm"}, _drilled(1), None),
    # plane_offsets measures from STRAIGHT edges - a circular one is refused by name
    ("find_geometry", {"target": "FeatureCameo", "kind": "circular_edge",
                       "nearest_to": [220, 20, 20], "max_results": 1}, "ok", _fg("fc_rim2")),
    ("model_hole", lambda c: {"face": _ctx_get(c, "fc_top", "cameo top face"),
                              "placement": "plane_offsets", "point": [215, 15, 20],
                              "offset_edge_one": _ctx_get(c, "fc_rim2", "a round rim"),
                              "offset_one": "5 mm", "diameter": "3 mm", "extent": "blind",
                              "depth": "3 mm"}, "refused", None),
    # re-acquired again: the start-vertex hole above can notch this edge the same way. The query
    # aims at the LONG remaining stretch of the pad's bottom boundary (x~232) - the notch cuts
    # mint short edges near the hole sites that are NOT parallel to the hole plane, and Fusion
    # refuses a non-parallel reference edge (measured).
    ("find_geometry", {"target": "FeatureCameo", "kind": "line_edge", "nearest_to": [232, 0, 20],
                       "max_results": 1}, "ok", _fg("fc_edge3")),
    ("model_hole", lambda c: {"face": _ctx_get(c, "fc_top", "cameo top face"),
                              "placement": "plane_offsets", "point": [215, 15, 20],
                              "offset_edge_one": _ctx_get(c, "fc_edge3", "pad edge"),
                              "offset_one": "6 mm", "diameter": "3 mm", "extent": "blind",
                              "depth": "3 mm"},
     lambda p: p.get("placement") == "plane_offsets", None),
    ("find_geometry", {"target": "FeatureCameo", "kind": "planar_face", "nearest_to": [220, 20, 20], "max_results": 1}, "ok", _fg("fc_body")),
    ("model_mirror", lambda c: {"bodies": [_ctx_get(c, "fc_body", "cameo body")], "plane": "yz"}, _mirrored, None),
    # a real GRID, not a row: two directions at once, spaced wider than the 40 mm pad so the
    # instances stand clear of each other. 3 x 2 is also the read-back that catches a tool
    # multiplying the directions wrongly - a row of 3 and a row of 6 both pass a bare "more than 1".
    ("model_pattern_rectangular", lambda c: {"bodies": [_ctx_get(c, "fc_body", "cameo body")],
                                             "quantity_one": 3, "spacing_one": 75, "direction_one": "x",
                                             "quantity_two": 2, "spacing_two": 70, "direction_two": "y"},
     _patterned("total_instances", 6), None),
    # An axis OUTSIDE the part, so the pattern reads as an orbit rather than a body spun in place:
    # two origin planes offset to cross 30 mm clear of the pad's -X edge, and their INTERSECTION is
    # the axis. The world z axis would do the same job 200 mm away, swinging the copies across the
    # whole scene and through the machined part.
    ("model_construction", {"kind": "plane", "plane": "yz", "offset": 170, "name": "OrbitYZ"},
     _datum_plane("yz"), None),
    ("model_construction", {"kind": "plane", "plane": "xz", "offset": 20, "name": "OrbitXZ"},
     _datum_plane("xz"), None),
    ("model_construction", {"kind": "axis", "mode": "two_planes", "plane": "OrbitYZ",
                            "plane2": "OrbitXZ", "name": "CameoOrbit"},
     lambda p: bool(p.get("handle")), None),
    ("model_pattern_circular", lambda c: {"bodies": [_ctx_get(c, "fc_body", "cameo body")],
                                          "quantity": 4, "total_angle_deg": 360,
                                          "axis": "CameoOrbit"},
     lambda p: p.get("quantity") == 4 and p.get("axis") == "CameoOrbit", None),
    # pattern the cameo along one of its own line edges - the count is a read-back, never an echo.
    ("find_geometry", {"target": "FeatureCameo", "kind": "line_edge", "max_results": 1}, "ok", _fg("dc_edge")),
    ("model_pattern_path", lambda c: {"bodies": [_ctx_get(c, "fc_body", "cameo body")], "path": [_ctx_get(c, "dc_edge", "path edge")], "quantity": 3, "distance": 55, "distance_type": "spacing"},
     lambda p: p.get("patterned") is True and p.get("quantity") == 3, None),
    # the pattern axis as a DATUM: the cameo's own bore defines a construction axis, whose published
    # handle is what the pattern turns about. The axis label is read back off the resolved entity, so
    # the datum's name proves the handle reached the datum and not a world axis fallback.
    ("find_geometry", {"target": "FeatureCameo", "kind": "cylinder_face", "max_results": 1}, "ok",
     _fg("fc_cyl")),
    ("model_construction", lambda c: {"kind": "axis", "mode": "circular_face",
                                      "face": _ctx_get(c, "fc_cyl", "a cameo bore face"),
                                      "name": "CameoSpin"},
     lambda p: bool(p.get("handle")), ("cam_axis", lambda p: p["handle"])),
    ("model_pattern_circular", lambda c: {"bodies": [_ctx_get(c, "fc_body", "cameo body")],
                                          "quantity": 4, "total_angle_deg": 360,
                                          "axis": _ctx_get(c, "cam_axis", "the datum axis handle")},
     lambda p: p.get("quantity") == 4 and p.get("axis") == "CameoSpin", None),
    # the same axis reached BY NAME while its component is active - the handle-free route.
    ("model_pattern_circular", lambda c: {"bodies": [_ctx_get(c, "fc_body", "cameo body")],
                                          "quantity": 3, "total_angle_deg": 180,
                                          "axis": "CameoSpin"},
     lambda p: p.get("quantity") == 3 and p.get("axis") == "CameoSpin", None),
    # the CYLINDRICAL FACE itself as the axis: off-origin, the case a direction vector cannot
    # express, and the label reads the resolved entity's type because a face carries no name.
    ("model_pattern_circular", lambda c: {"bodies": [_ctx_get(c, "fc_body", "cameo body")],
                                          "quantity": 3,
                                          "axis": _ctx_get(c, "fc_cyl", "a cameo bore face")},
     lambda p: p.get("quantity") == 3 and p.get("axis") == "BRepFace", None),
    # a circular_face axis inside a ROTATED occurrence: ConstructionAxis.geometry stays COMPONENT-
    # LOCAL even through a face proxy, so the local axis must be LIFTED through the occurrence's own
    # transform2 to read as world. A YZ-plane rod's local axis is world X before the rotation; a
    # -90 deg Z turn carries it to world (0,-1,0).
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # placed at x=1300 mm: clear of the story's stock and bracket in the interference census
    ("model_create_component", {"name": "AxisFrameRig", "activate": True, "x": 1300},
     _made_component, None),
    ("sketch_create", {"plane": "yz", "name": "AxisFrameRigS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 5}],
                             "sketch_name": "AxisFrameRigS"}, "ok", None),
    ("model_extrude", {"sketch_name": "AxisFrameRigS", "profile_index": 0, "distance": 20},
     _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("assembly_move", {"occurrence": "AxisFrameRig:1", "rotate_deg": -90, "rotate_axis": "z"},
     _moved_occurrence(), None),
    # captured, or the add below recomputes the design and the uncaptured pose of this grounded
    # occurrence reverts to identity (measured burn82) - the row would then pass on no rotation.
    ("assembly_capture_position", {"action": "capture"}, _captured, None),
    ("design_activate_component", {"occurrence": "AxisFrameRig:1"}, "ok", None),
    ("find_geometry", {"target": "AxisFrameRig", "kind": "cylinder_face", "max_results": 1}, "ok",
     _fg("afr_cyl")),
    ("model_construction", lambda c: {"kind": "axis", "mode": "circular_face",
                                      "face": _ctx_get(c, "afr_cyl", "the rotated rod's face"),
                                      "name": "AxisFrameSpin"},
     lambda p: _measured("a rotated occurrence's local axis lifts to the face proxy's world reading",
                         {"frame": p.get("frame"),
                          "direction": (p.get("geometry") or {}).get("direction"),
                          "aligned": p.get("aligned_to_face_axis")},
                         p.get("frame") == "world" and p.get("aligned_to_face_axis") is True
                         and _near(abs(((p.get("geometry") or {}).get("direction") or [0, 0, 0])[1]),
                                   1.0, 1e-3)), None),
    # a rotate move BY NAME about that same construction axis, still inside a rotated, captured
    # occurrence: the axis's owning component equals the move's host, which a proxy lift must not
    # skip just because "nothing foreign" - the body it turns is what proves the axis landed.
    ("model_move", {"mode": "rotate", "bodies": ["AxisFrameRig"], "axis": "AxisFrameSpin",
                    "angle_deg": 30},
     lambda p: _measured("rotate by NAME about a construction axis owned by the rotated occurrence "
                         "itself",
                         {"mode": p.get("mode"), "moved": p.get("moved"),
                          "displacement": p.get("displacement")},
                         p.get("moved") is True and p.get("mode") == "rotate"
                         and isinstance(p.get("displacement"), (int, float))
                         and p.get("displacement") > 0), None),
    # a datum NAME reaches only the ACTIVE component, so the same name from the root is refused
    # rather than resolved to something else. (A second same-named axis is never ambiguous - Fusion
    # dedupes the name itself.) The activation is put back so the cameo tree is unchanged.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_pattern_circular", lambda c: {"bodies": [_ctx_get(c, "fc_body", "cameo body")],
                                          "quantity": 3, "axis": "CameoSpin"}, "refused", None),
    ("design_activate_component", {"occurrence": "FeatureCameo:1"}, "ok", None),
    # Three isolated root-parametric joins carry the accepted complete, partial and disjoint
    # controls. Each owns and closes its scratch document, then returns the story to root.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("doc_get", {}, _home_document,
     ("combine_story", _recall("combine_story", _combine_story_address))),
] + _COMBINE_COMPLETE + _COMBINE_PARTIAL + _COMBINE_NONE + _COMBINE_CUT_NONE + _COMBINE_NONROOT_PARTIAL + _REVOLVE_PARTICIPANTS + [
    ("design_activate_component", {"occurrence": "root"}, "ok", None),    # the revolve axis as a CYLINDRICAL FACE, off the origin - the case a world key cannot express.
    # A face mapped to a direction VECTOR keeps the direction and DROPS the location, so the ring is
    # turned about the world axis through the ORIGIN and reported as success: the label is checked
    # AND the geometry measured. Live: a cylinder at x=30, a 2x3 mm profile at x 36-38 on the XZ
    # plane, ring bbox x 22..38. The cameo sits at z=100, clear of the part and the other cameos.
    ("model_create_component", {"name": "RevolveCameo", "activate": True}, _made_component, None),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 100, "name": "RevAxisPlane"},
     _datum_plane("xy"), None),
    ("sketch_create", {"plane": "RevAxisPlane", "name": "RevAxisS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 30, "cy": 0, "radius": 5}],
                             "sketch_name": "RevAxisS"}, "ok", None),
    ("model_extrude", {"sketch_name": "RevAxisS", "profile_index": 0, "distance": 20}, _extruded, None),
    ("find_geometry", {"target": "RevolveCameo", "kind": "cylinder_face", "radius": 5, "max_results": 1}, "ok", _fg("rv_cyl")),
    ("sketch_create", {"plane": "xz", "name": "RevRingS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 36, "y1": 100,
                                           "x2": 38, "y2": 103}],
                             "sketch_name": "RevRingS"}, "ok", None),
    ("model_revolve", lambda c: {"sketch_name": "RevRingS", "profile_index": 0,
                                 "axis": _ctx_get(c, "rv_cyl", "the off-origin cylinder face"),
                                 "angle_deg": 360},
     lambda p: p.get("axis") == "BRepFace", None),
    # the label alone cannot see wrong geometry: the ring must stand AROUND x=30, never around the
    # origin (about the world z axis this profile spans x -38..38, so a positive min x is the tell).
    ("model_inspect", {"target": "RevolveCameo:1"},
     lambda p: (p["min_point"]["x"] >= 20 and p["max_point"]["x"] <= 40
                and p["min_point"]["x"] > 0), None),
    # a PLANAR face carries a normal, not an axis - refused by name (only a cylindrical/conical/
    # toroidal face defines one) instead of turned into a direction the caller never asked for.
    ("find_geometry", {"target": "RevolveCameo", "kind": "planar_face", "nearest_to": [30, 0, 120],
                       "max_results": 1}, "ok", _fg("rv_flat")),
    ("model_revolve", lambda c: {"sketch_name": "RevRingS", "profile_index": 0,
                                 "axis": _ctx_get(c, "rv_flat", "a planar cap face"),
                                 "angle_deg": 360}, "refused", None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # 'all' takes EVERY closed region, and the bays inside a frame outline are closed regions too -
    # so this extrude fills them with material. The payload cannot show a solid bay, so the enclosed
    # regions are NAMED: an outer rectangle plus three bays reports the three that sit inside another.
    ("model_create_component", {"name": "BayCameo", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "BayS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 200, "y1": 900,
                                           "x2": 290, "y2": 960}],
                             "sketch_name": "BayS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 210, "y1": 910,
                                           "x2": 230, "y2": 950}],
                             "sketch_name": "BayS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 240, "y1": 910,
                                           "x2": 260, "y2": 950}],
                             "sketch_name": "BayS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 270, "y1": 910,
                                           "x2": 285, "y2": 950}],
                             "sketch_name": "BayS"}, "ok", None),
    ("model_extrude", {"sketch_name": "BayS", "profile_index": "all", "distance": 8},
     lambda p: (isinstance(p.get("enclosed_profile_indices"), list)
                and len(p["enclosed_profile_indices"]) > 0
                and "enclosed" in p.get("note", "")), None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # Radius filtering uses the full measurement while the returned record stays at three decimals.
    # Two separately measured cylinders make the target/decoy decision observable in every unit.
    ("model_create_component", {"name": "RadiusFilterBench", "activate": True},
     _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "RadiusTargetS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 2300, "cy": 0,
                                           "radius": 2.68224}],
                             "sketch_name": "RadiusTargetS"}, "ok", None),
    ("model_extrude", {"sketch_name": "RadiusTargetS", "profile_index": 0, "distance": 10},
     _extruded, None),
    ("sketch_create", {"plane": "xy", "name": "RadiusDecoyS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 2320, "cy": 0,
                                           "radius": 5}],
                             "sketch_name": "RadiusDecoyS"}, "ok", None),
    ("model_extrude", {"sketch_name": "RadiusDecoyS", "profile_index": 0, "distance": 10},
     _extruded, None),
    # Position-only acquisition keeps the size proof independent of the radius filter. The target
    # face set has one cylindrical face; the target edge set has both circular rims, selected ahead
    # of the decoy by distance to their midpoint.
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "cylinder_face",
                       "nearest_to": [2300, 0, 5], "max_results": 1},
     _matched(1, "cylinder_face"), _fgn("radius_target_faces")),
    ("model_inspect", lambda c: {"target": _ctx_get(
        c, "radius_target_faces", "the independently acquired target face")[0], "units": "mm"},
     _radius_body_size("independent target face is a 2.68224 mm radius cylinder", 5.36448),
     None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "cylinder_face",
                       "nearest_to": [2320, 0, 5], "max_results": 1},
     _matched(1, "cylinder_face"), _fg("radius_decoy_face")),
    ("model_inspect", lambda c: {"target": _ctx_get(
        c, "radius_decoy_face", "the independently acquired decoy face"), "units": "mm"},
     _radius_body_size("independent decoy face is a 5 mm radius cylinder", 10.0), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "circular_edge",
                       "nearest_to": [2300, 0, 5], "max_results": 2},
     _matched(2, "circular_edge"), _fgn("radius_target_edges")),
    ("model_inspect", lambda c: {"target": _ctx_get(
        c, "radius_target_edges", "the independently acquired target edges")[0], "units": "mm"},
     _radius_body_size(
         "independent target edge resolves to its 2.68224 mm radius owning body", 5.36448),
     None),
    # The inside query must include the target and the 0.00124 mm farther query must exclude it.
    # Each positive call retains every handle. The following model_inspect calls consume the actual
    # filtered handles; the tight body-size readback proves each one belongs to the target cylinder.
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "cylinder_face",
                       "radius": 2.55524, "units": "mm"},
     _matched(1, "cylinder_face"), _fgn("radius_face_mm")),
    ("model_inspect", lambda c: _radius_filtered_handle(
        c, "radius_face_mm", 0),
     _radius_body_size("mm-filtered face is the 2.68224 mm radius target", 5.36448), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "cylinder_face",
                       "radius": 2.554, "units": "mm"},
     _matched(0, "cylinder_face"), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "cylinder_face",
                       "radius": 0.255524, "units": "cm"},
     _matched(1, "cylinder_face"), _fgn("radius_face_cm")),
    ("model_inspect", lambda c: _radius_filtered_handle(
        c, "radius_face_cm", 0),
     _radius_body_size("cm-filtered face is the 2.68224 mm radius target", 5.36448), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "cylinder_face",
                       "radius": 0.2554, "units": "cm"},
     _matched(0, "cylinder_face"), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "cylinder_face",
                       "radius": 0.1006, "units": "in"},
     _matched(1, "cylinder_face"), _fgn("radius_face_in")),
    ("model_inspect", lambda c: _radius_filtered_handle(
        c, "radius_face_in", 0),
     _radius_body_size("inch-filtered face is the 2.68224 mm radius target", 5.36448), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "cylinder_face",
                       "radius": 0.1005511811023622, "units": "in"},
     _matched(0, "cylinder_face"), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "circular_edge",
                       "radius": 2.55524, "units": "mm"},
     _matched(2, "circular_edge"), _fgn("radius_edges_mm")),
    ("model_inspect", lambda c: _radius_filtered_handle(
        c, "radius_edges_mm", 0),
     _radius_body_size("first mm-filtered edge owns the 2.68224 mm radius target", 5.36448), None),
    ("model_inspect", lambda c: _radius_filtered_handle(
        c, "radius_edges_mm", 1),
     _radius_body_size("second mm-filtered edge owns the 2.68224 mm radius target", 5.36448), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "circular_edge",
                       "radius": 2.554, "units": "mm"},
     _matched(0, "circular_edge"), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "circular_edge",
                       "radius": 0.255524, "units": "cm"},
     _matched(2, "circular_edge"), _fgn("radius_edges_cm")),
    ("model_inspect", lambda c: _radius_filtered_handle(
        c, "radius_edges_cm", 0),
     _radius_body_size("first cm-filtered edge owns the 2.68224 mm radius target", 5.36448), None),
    ("model_inspect", lambda c: _radius_filtered_handle(
        c, "radius_edges_cm", 1),
     _radius_body_size("second cm-filtered edge owns the 2.68224 mm radius target", 5.36448), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "circular_edge",
                       "radius": 0.2554, "units": "cm"},
     _matched(0, "circular_edge"), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "circular_edge",
                       "radius": 0.1006, "units": "in"},
     _matched(2, "circular_edge"), _fgn("radius_edges_in")),
    ("model_inspect", lambda c: _radius_filtered_handle(
        c, "radius_edges_in", 0),
     _radius_body_size(
         "first inch-filtered edge owns the 2.68224 mm radius target", 5.36448), None),
    ("model_inspect", lambda c: _radius_filtered_handle(
        c, "radius_edges_in", 1),
     _radius_body_size(
         "second inch-filtered edge owns the 2.68224 mm radius target", 5.36448), None),
    ("find_geometry", {"target": "RadiusFilterBench", "kind": "circular_edge",
                       "radius": 0.1005511811023622, "units": "in"},
     _matched(0, "circular_edge"), None),
    *_PRECISION_READS,
    # AS_SURFACE OVER A CLOSED ELLIPSE: the sketch also holds the ellipse's two construction axes.
    # The extrude must land a surface wall, read off the feature AND off the body's own flag. Each
    # of these three benches sits out at x 1410..1540 through its component placement.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "EllipseWall", "activate": True, "x": 1410},
     _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "EllipseWallS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "ellipse", "cx": 0, "cy": 0, "radius": 15,
                                           "minor": 8}],
                             "sketch_name": "EllipseWallS"}, "ok", None),
    ("model_extrude", {"sketch_name": "EllipseWallS", "profile_index": 0, "distance": 10,
                       "as_surface": True},
     lambda p: _measured("an ellipse extruded as_surface lands a surface",
                         {"as_surface": p.get("as_surface"), "is_solid": p.get("is_solid")},
                         p.get("as_surface") is True and p.get("is_solid") is False), None),
    ("model_inspect", {"target": "EllipseWall:1", "include": ["default", "mass"],
                       "per_body": True},
     lambda p: _measured("the ellipse wall's one body reads is_solid false",
                         [(r.get("body"), r.get("is_solid"))
                          for r in (p.get("mass") or {}).get("per_body") or []],
                         [r.get("is_solid") for r in (p.get("mass") or {}).get("per_body") or []]
                         == [False]), None),
    # TO_FACE DEPTH: a to-face extent has no distance parameter, so the landed depth is read off
    # the new body. The circle on z=0 runs up to the roof block's underside at z=30.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "ToFaceCap", "activate": True, "x": 1470},
     _made_component, None),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 30, "name": "ToFaceRoof"},
     _datum_plane("xy"), None),
    ("sketch_create", {"plane": "ToFaceRoof", "name": "ToFaceRoofS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": -20, "y1": -20,
                                           "x2": 20, "y2": 20}],
                             "sketch_name": "ToFaceRoofS"}, "ok", None),
    ("model_extrude", {"sketch_name": "ToFaceRoofS", "profile_index": 0, "distance": 10},
     _extruded, None),
    # a callable, so the layout reads no world point off it: the bench is placed by its component
    ("find_geometry", lambda c: {"target": "ToFaceCap", "kind": "planar_face",
                                 "nearest_to": [1470, 0, 30], "max_results": 1},
     _matched(1, "planar_face"), _fg("to_face_floor")),
    ("sketch_create", {"plane": "xy", "name": "ToFaceS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 5}],
                             "sketch_name": "ToFaceS"}, "ok", None),
    ("model_extrude", lambda c: {"sketch_name": "ToFaceS", "profile_index": 0,
                                 "extent": "to_face",
                                 "to_object": _ctx_get(c, "to_face_floor", "the roof's underside")},
     lambda p: _measured("to_face publishes the landed depth",
                         {"extent": p.get("extent"), "depth_mm": p.get("depth_mm")},
                         p.get("extent") == "to_object" and _near(p.get("depth_mm"), 30.0, 0.05)),
     None),
    # A ROTATED OCCURRENCE'S BOX: a 40 mm disc turned 45 deg about its own axis still spans 40 mm.
    # Measured on a 200 mm disc: the proxy's plain boundingBox read 200 x sqrt 2 after the turn.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "RotDisc", "activate": True, "x": 1540},
     _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "RotDiscS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 20}],
                             "sketch_name": "RotDiscS"}, "ok", None),
    ("model_extrude", {"sketch_name": "RotDiscS", "profile_index": 0, "distance": 5},
     _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("assembly_move", {"occurrence": "RotDisc:1", "rotate_deg": 45, "rotate_axis": "z"},
     _moved_occurrence(), None),
    ("assembly_capture_position", {"action": "capture"}, _captured, None),
    ("model_inspect", {"target": "RotDisc:1", "units": "mm"},
     lambda p: _measured("a 45 deg turned disc keeps its tight 40 mm box",
                         {"x": p.get("x"), "y": p.get("y"), "box_read": p.get("box_read")},
                         _near(p.get("x"), 40.0, 0.05) and _near(p.get("y"), 40.0, 0.05)
                         and p.get("box_read") == "preciseBoundingBox"), None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    *_SWEEP_EDIT_MODES,
    *_LOFT_EDITOR,
    *_LATER_OPERAND,
    *_LOFT_PARTICIPANTS,
    *_LOFT_ALIGNMENT,
    *_SOLID_TOOL,
    *_TANGENT_PATH,
    *_pattern_count_rows(),
]

_SOLIDS += _loft_curve_refusal_rows()


def _component_block(steps, component, last_tool, last_key=None, last_value=None):
    """Take one named component's rows through its last required effect."""
    starts = [i for i, row in enumerate(steps)
              if row[0] == "model_create_component" and isinstance(row[1], dict)
              and row[1].get("name") == component]
    if len(starts) != 1:
        raise ValueError("component fixture boundary is not unique: " + component)
    start = starts[0]
    ends = [i for i in range(start + 1, len(steps))
            if steps[i][0] == last_tool
            and (last_key is None or (isinstance(steps[i][1], dict)
                                      and steps[i][1].get(last_key) == last_value))]
    if not ends:
        raise ValueError("component fixture has no last effect: " + component)
    return list(steps[start:ends[0] + 1])


_STOCK_CENTER_END = next(i for i, row in enumerate(_SOLIDS)
                         if row[0] == "joint_create_origin" and isinstance(row[1], dict)
                         and row[1].get("name") == "StockCenter")
FINISHED_BRACKET = list(_SOLIDS[:_STOCK_CENTER_END + 1])
DATUM_BENCH_DETAILS = _component_block(_SOLIDS, "DatumBench", "find_geometry", "kind",
                                       "cylinder_face")
DATUM_BENCH_RESIZE = _component_block(_SOLIDS, "DatumBench", "model_extrude")


def _symmetric_target_top(p):
    """Acquire the unique measured top face of the owned 20 x 20 x 10 mm block."""
    rows = p.get("matches") or []
    top = [r for r in rows if r.get("position") == [10, 10, 10] and r.get("normal") == [0, 0, 1]]
    valid = (p.get("units") == "mm" and p.get("match_count") == p.get("returned") == len(rows) == 6
             and len(top) == 1 and top[0].get("handle") and _near(top[0].get("area"), 400, .001))
    if valid:
        _RECALL["extent_top"] = top[0]["handle"]
    return _measured("one target top planar face at z=10", top, bool(valid))


def _symmetric_target_rows():
    """Verify target-symmetry refusals and independently read both legal extent controls."""
    from verify_acts_model_sweep import _retire_compare, _retire_reads
    rows = [("doc_get", {}, _home_document, ("extent_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "extent_story", "story")},
             _new_document, ("extent_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "extent_doc", args(c) if callable(args) else args), check, save))

    for name, low, high in (("Block", (0, 0), (20, 20)), ("TargetProfile", (5, 5), (9, 9)),
                            ("DistanceProfile", (30, 0), (34, 4))):
        write("sketch_create", {"name": name, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [
            {"kind": "rectangle", "x1": low[0], "y1": low[1], "x2": high[0], "y2": high[1]}]})
        if name == "Block":
            write("model_extrude", {"sketch_name": name, "distance": 10}, _extruded,
                  ("extent_block", lambda p: p["result_bodies"][0]))
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True})
    block_args = lambda c: {**_combine_inspect(_ctx_get(c, "extent_block", "target block")), "per_body": True}
    rows += [("model_inspect", block_args, _combine_body("target block", (0, 0, 0), (20, 20, 10), 4000), None),
             ("model_inspect", block_args, _retire_compare("extent_block_state", _symmetric_target_body_state, False), None),
             ("find_geometry", lambda c: {"target": _ctx_get(c, "extent_block", "target block"),
                                           "kind": "planar_face", "nearest_to": [10, 10, 10],
                                           "max_results": 20, "units": "mm"}, _symmetric_target_top,
              ("extent_top", lambda p: _RECALL["extent_top"]))]
    rows += _retire_reads("extent_refusal", [""], [("", "TargetProfile"), ("", "DistanceProfile")])
    for explicit in (True, False):
        write("model_extrude", lambda c, explicit=explicit: {
            "sketch_name": "TargetProfile", "to_object": _ctx_get(c, "extent_top", "target top face"),
            "symmetric": True, **({"extent": "to_face"} if explicit else {})},
            _refused("symmetric=true", "to_object", "symmetric=false", "omit to_object"))
        rows += _retire_reads("extent_refusal", [""], [("", "TargetProfile"), ("", "DistanceProfile")], True)
    write("model_extrude", lambda c: {"sketch_name": "TargetProfile", "extent": "to_face",
        "to_object": _ctx_get(c, "extent_top", "target top face"), "symmetric": False}, _extruded,
        ("extent_ordinary", lambda p: p["result_bodies"][0]))
    rows.append(("model_inspect", lambda c: _combine_inspect(_ctx_get(c, "extent_ordinary", "one-sided result")),
                 _combine_body("one-sided to-face", (5, 5, 0), (9, 9, 10), 160), None))
    write("model_extrude", {"sketch_name": "DistanceProfile", "distance": 5, "symmetric": True}, _extruded,
          ("extent_distance", lambda p: p["result_bodies"][0]))
    rows += [("model_inspect", lambda c: _combine_inspect(_ctx_get(c, "extent_distance", "symmetric result")),
              _combine_body("symmetric distance", (30, 0, -5), (34, 4, 5), 160), None),
             ("model_inspect", block_args, _retire_compare("extent_block_state", _symmetric_target_body_state, True), None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "extent_story", "story"),
                                         "expect_document": _ctx_get(c, "extent_doc", "scratch")}, _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "extent_doc", "scratch"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "extent_story", "story")}, _document_closed, None)]
    return rows


_SOLIDS += _symmetric_target_rows()


def _edge_extent_geometry(p):
    """Return a complete finite public face/edge census without transient handle text."""
    rows = p.get("matches")
    if (p.get("units") != "mm" or not isinstance(rows, list) or not rows
            or p.get("match_count") != p.get("returned") or p.get("returned") != len(rows)):
        return None
    for row in rows:
        position = row.get("position")
        if (not row.get("handle") or not row.get("kind")
                or not isinstance(position, list) or len(position) != 3
                or not all(_num(v) and math.isfinite(v) for v in position)):
            return None
        required = ("area",) if row["kind"].endswith("face") else ("length",)
        if row["kind"] in ("cylinder_face", "circular_edge", "arc_edge"):
            required += ("radius",)
        for key in required:
            if not _num(row.get(key)) or not math.isfinite(row[key]) or row[key] <= 0:
                return None
        if row["kind"].endswith("face"):
            normal = row.get("normal")
            if (not isinstance(normal, list) or len(normal) != 3
                    or not all(_num(v) and math.isfinite(v) for v in normal)):
                return None
    return sorted(({k: v for k, v in row.items() if k != "handle"} for row in rows),
                  key=lambda r: (r["kind"], r["position"]))


def _edge_extent_history(tag, feature_key, feature_type):
    """Require exactly one healthy feature after the unchanged baseline history."""
    def check(p):
        now = _retire_design_state(p)
        before = _RECALL.get(tag + "_design")
        old = (before or {}).get("timeline", {})
        tl = (now or {}).get("timeline", {})
        rows = tl.get("timeline") or []
        states = dict((old.get("summary") or {}).get("states") or {})
        states["healthy"] = states.get("healthy", 0) + 1
        valid = (now is not None and before is not None and len(rows) == len(old["timeline"]) + 1
                 and rows[:-1] == old["timeline"] and rows[-1].get("name") == _RECALL.get(feature_key)
                 and rows[-1].get("type") == feature_type and rows[-1].get("health", "healthy") == "healthy"
                 and (tl.get("summary") or {}).get("states") == states
                 and (tl.get("summary") or {}).get("exceptions") == (old.get("summary") or {}).get("exceptions"))
        return _measured("one healthy feature with retained prior history", tl, valid)
    return check


def _edge_extent_rows(duplicate):
    """Compare repeated-edge fillets/chamfers or signed through-all cuts against independent public reads."""
    tag = "distinct_edge" if duplicate else "signed_all"
    rows = [("doc_get", {}, _home_document, (tag + "_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, tag + "_home", "story")},
             _new_document, (tag + "_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(
            c, tag + "_doc", args(c) if callable(args) else args), check, save))

    dimensions = (10, 8, 6) if duplicate else (12, 8, 5)
    for name, x, size in (("EdgeExtentStock", 0, dimensions), ("EdgeExtentWitness", 100, (20, 20, 20))):
        write("sketch_create", {"name": name, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [
            {"kind": "rectangle", "x1": x, "y1": 0, "x2": x + size[0], "y2": size[1]}]})
        write("model_extrude", {"sketch_name": name, "distance": size[2],
                               "symmetric": not duplicate and x == 0}, _extruded,
              (tag + ("_stock" if x == 0 else "_witness"), lambda p: p["result_bodies"][0]))
    if not duplicate:
        for name, x in (("AllPositive", 2), ("AllNegative", 5), ("AllSymmetric", 8)):
            write("sketch_create", {"name": name, "plane": "xy"})
            write("sketch_add_geometry", {"sketch_name": name, "geometry": [
                {"kind": "circle", "cx": x, "cy": 4, "radius": .5}]})
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True})

    def inspect(role):
        return lambda c: {**_combine_inspect(_ctx_get(c, tag + "_" + role, role)), "per_body": True}

    def geometry(role, kind=""):
        return lambda c: {"target": _ctx_get(c, tag + "_" + role, role), **({"kind": kind} if kind else {}),
                          "max_results": 100, "units": "mm"}

    baseline_volume = 480 if duplicate else 960
    rows += [("model_inspect", inspect("stock"),
              _combine_body("source stock", (0, 0, 0 if duplicate else -5),
                            (dimensions[0], 8, 6 if duplicate else 5), baseline_volume), None),
             ("model_inspect", inspect("witness"),
              _combine_body("independent witness", (100, 0, 0), (120, 20, 20), 8000), None)]
    rows += _retire_reads(tag, [""], [])
    for role in ("stock", "witness"):
        rows += [("model_inspect", inspect(role), _retire_compare(
                  tag + "_" + role + "_state", _symmetric_target_body_state, False), None),
                 ("find_geometry", geometry(role), _retire_compare(
                  tag + "_" + role + "_geometry", _edge_extent_geometry, False), None)]

    def changed_material(expected):
        def check(p):
            now = _symmetric_target_body_state(p)
            return _measured("independent landed material", now,
                now is not None and _near(now["material"].get("volume"), expected, .001)
                and now["bounds"] == _RECALL[tag + "_stock_state"]["bounds"])
        return check

    def acquire_edge(p):
        state = _edge_extent_geometry(p)
        matches = [r for r in p.get("matches") or [] if r.get("position") == [5, 8, 0]]
        valid = state is not None and len(state) == 12 and len(matches) == 1
        if valid:
            _RECALL[tag + "_edge"] = matches[0]["handle"]
        return _measured("one resolved physical edge at [5,8,0]", matches, valid)

    def edge_result(kind, n):
        def check(p):
            note = p.get("note") or ""
            said = f"The {n} handles named 1 distinct edge(s), so each was sent once." in note
            valid = (p.get(kind + "ed") is True and p.get("edges_requested") == n
                     and p.get("edge_selection") == "1 edge seed(s) from handles"
                     and p.get("edges_cut") == 1 and p.get("faces_created") == 1
                     and p.get("tangent_chain") is False
                     and (said if n > 1 else "handles named" not in note))
            return _measured(f"{n} {kind} handle(s) naming one physical edge, cut once", p, valid)
        return check

    def landed(family, n):
        compare = _retire_compare(f"{tag}_{family}_landed_geometry", _edge_extent_geometry, n > 1)
        def check(p):
            state = _edge_extent_geometry(p) or []
            faces = sum(1 for r in state if r["kind"].endswith("face"))
            census = {"faces": faces, "edges": len(state) - faces}
            _measured("landed stock census", census, census == {"faces": 7, "edges": 15})
            return compare(p)
        return check

    def retired(feature_type):
        def check(p):
            return _measured("the created feature deleted by type", p,
                p.get("deleted") is True and p.get("feature") == _RECALL.get(tag + "_feature")
                and p.get("entity_type") == feature_type and p.get("also_deleted") == [])
        return check

    # (family, tool, size args, landed stock volume mm3, feature type): the one-handle control and
    # the repeated handle must both land this volume and the same face/edge census.
    families = (("constant", "model_fillet", {"radius": .5, "tangent_chain": False},
                 479.4634954084937, "FilletFeature"),
                ("chamfer", "model_chamfer", {"distance": .5, "tangent_chain": False},
                 478.75, "ChamferFeature"),
                ("chord", "model_fillet", {"fillet_type": "chord_length", "chord_length": .5,
                                           "tangent_chain": False}, 479.731748, "FilletFeature"),
                ("variable", "model_fillet", {"fillet_type": "variable", "radius": .5,
                                              "end_radius": 1}, 478.749187, "FilletFeature"))
    cases = tuple((family, n) for family in families for n in (1, 2)) if duplicate else (
        ("AllPositive", 1), ("AllNegative", -1), ("AllSymmetric", 1))
    for case, value in cases:
        if duplicate:
            family, tool, size_args, expected_volume, feature_type = case
            rows.append(("find_geometry", geometry("stock", "line_edge"), acquire_edge,
                         (tag + "_edge", lambda p: _RECALL[tag + "_edge"])))
            write(tool, lambda c, n=value, size_args=size_args: {"edges": [
                _ctx_get(c, tag + "_edge", "physical edge")] * n, "units": "mm", **size_args},
                edge_result(tool[len("model_"):], value),
                (tag + "_feature", _recall(tag + "_feature", lambda p: p["feature"])))
        else:
            write("model_extrude", lambda c, case=case, value=value: {
                "sketch_name": case, "operation": "cut", "extent": "through_all", "distance": value,
                "symmetric": case == "AllSymmetric", "target_bodies": [_ctx_get(c, tag + "_stock", "stock")]},
                lambda p, case=case: _extruded(p) and _measured(
                    "through_all reply names the side its extent reads", p.get("direction"),
                    p.get("direction") == {"AllPositive": "positive", "AllNegative": "negative",
                                           "AllSymmetric": "symmetric"}[case]),
                (tag + "_feature", _recall(tag + "_feature", lambda p: p["feature"])))
            expected_volume = baseline_volume - math.pi * .5 ** 2 * (10 if case == "AllSymmetric" else 5)
        rows += [("model_inspect", inspect("stock"), changed_material(expected_volume), None),
                 ("model_inspect", inspect("witness"), _retire_compare(
                     tag + "_witness_state", _symmetric_target_body_state, True), None),
                 ("find_geometry", geometry("witness"), _retire_compare(
                     tag + "_witness_geometry", _edge_extent_geometry, True), None),
                 ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                                  "tree_handles": True, "max_depth": 10, "max_results": 2000},
                  _edge_extent_history(tag, tag + "_feature", feature_type if duplicate else "ExtrudeFeature"), None)]
        if duplicate:
            rows.append(("find_geometry", geometry("stock"), landed(family, value), None))
        else:
            x, z = {"AllPositive": (2, 2.5), "AllNegative": (5, -2.5), "AllSymmetric": (8, 0)}[case]
            def side(p, x=x, z=z):
                state = _edge_extent_geometry(p)
                matches = p.get("matches") or []
                valid = (state is not None and len(matches) == 1 and matches[0].get("kind") == "cylinder_face"
                         and _near(matches[0].get("radius"), .5, .000001)
                         and all(_near(v, e, .000001) for v, e in zip(matches[0]["position"], (x, 4, z))))
                return _measured("independent bore wall centroid on the requested side", matches, valid)
            rows.append(("find_geometry", geometry("stock", "cylinder_face"), side, _fg(tag + "_wall")))
            low, high = (-5 if z <= 0 else 0), (5 if z >= 0 else 0)
            def wall_bounds(p, low=low, high=high):
                bounds = [p.get(point) or {} for point in ("min_point", "max_point")]
                valid = (p.get("units") == "mm" and p.get("frame") == "world axes (axis-aligned)"
                         and all(_num(b.get(a)) and math.isfinite(b[a]) for b in bounds for a in "xyz")
                         and _near(bounds[0].get("z"), low, .000001)
                         and _near(bounds[1].get("z"), high, .000001))
                return _measured("bore wall bounds reach exactly the requested stock side", bounds, valid)
            rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, tag + "_wall", "bore wall"),
                "include": ["default"], "units": "mm"}, wall_bounds, None))
            if case == "AllNegative":
                # The side the reply named is the side the editor reads; its edit moves the wall up.
                write("model_edit_extrude", lambda c: {
                    "feature": _ctx_get(c, tag + "_feature", "created feature"), "action": "extent",
                    "extent": "through_all", "direction": "positive"},
                    lambda p: _measured("negative through_all edited to the positive side", p,
                        p.get("edited") is True and p.get("definition_matches") is True
                        and (p.get("definition_before") or {}).get("side") == "negative"
                        and (p.get("definition_after") or {}).get("side") == "positive"))
                rows += [("model_inspect", inspect("stock"), changed_material(expected_volume), None),
                         ("find_geometry", geometry("stock", "cylinder_face"),
                          lambda p, side=side: side(p, z=2.5), _fg(tag + "_wall")),
                         ("model_inspect", lambda c: {"target": _ctx_get(c, tag + "_wall", "bore wall"),
                          "include": ["default"], "units": "mm"},
                          lambda p, wall_bounds=wall_bounds: wall_bounds(p, low=0, high=5), None)]
        write("design_delete_feature", lambda c: {"feature": _ctx_get(c, tag + "_feature", "created feature")},
              retired(feature_type) if duplicate else "ok")
        rows += _retire_reads(tag, [""], [], True)
        for role in ("stock", "witness"):
            rows += [("model_inspect", inspect(role), _retire_compare(
                      tag + "_" + role + "_state", _symmetric_target_body_state, True), None),
                     ("find_geometry", geometry(role), _retire_compare(
                      tag + "_" + role + "_geometry", _edge_extent_geometry, True), None)]
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, tag + "_home", "story"),
               "expect_document": _ctx_get(c, tag + "_doc", "scratch")}, _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, tag + "_doc", "scratch"), "save_changes": False,
               "expect_document": _ctx_get(c, tag + "_home", "story")}, _document_closed, None)]
    return rows


_SOLIDS += _edge_extent_rows(True) + _edge_extent_rows(False)


def _cross_owner_fillet_rows():
    """Refuse fresh edge handles across component owners, then prove the same-owner control edits."""
    from verify_acts_model_sweep import _retire_compare
    tag = "cross_owner_fillet"
    rows = [("doc_get", {}, _home_document, (tag + "_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, tag + "_home", "story")},
             _new_document, (tag + "_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(
            c, tag + "_doc", args(c) if callable(args) else args), check, save))

    for name, x, width, height, depth in (
            ("OwnerA", 100, 10, 10, 10), ("OwnerB", 130, 12, 8, 6)):
        write("model_create_component", {"name": name, "activate": True, "x": x}, _made_component)
        write("sketch_create", {"name": name + "S", "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name + "S", "geometry": [
            {"kind": "rectangle", "x1": 0, "y1": 0, "x2": width, "y2": height}]})
        write("model_extrude", {"sketch_name": name + "S", "distance": depth}, _extruded,
              (name + "_body", lambda p: p["result_bodies"][0]))
    write("design_activate_component", {"occurrence": "root"})
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True})

    def acquire(owner, point, key):
        return ("find_geometry", {"target": owner + ":1:Body1", "kind": "line_edge",
            "nearest_to": point, "max_results": 1, "units": "mm"},
            _cross_owner_edge(owner, point), _fg(key))

    rows += [acquire("OwnerA", [105, 0, 10], tag + "_edge_a"),
             acquire("OwnerB", [136, 0, 6], tag + "_edge_b")]
    rows.append(("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
        "max_depth": 4, "max_results": 1000}, _cross_owner_body_handles,
        (tag + "_body_handles", lambda p: _RECALL[tag + "_body_handles"])))
    targets = ["", "OwnerA:1", "OwnerB:1"]
    rows += _retire_reads(tag, targets, [])
    for owner in ("OwnerA", "OwnerB"):
        rows.append(("model_inspect", lambda c, owner=owner: {
            "target": _ctx_get(c, tag + "_body_handles", "body handles")[owner],
            "include": ["default", "mass"], "per_body": True, "units": "mm",
            "accuracy": "very_high"},
            _retire_compare(tag + "_" + owner + "_state", _symmetric_target_body_state, False), None))
    write("model_fillet", lambda c: {"edges": [
        _ctx_get(c, tag + "_edge_a", "OwnerA fresh edge"),
        _ctx_get(c, tag + "_edge_b", "OwnerB fresh edge")],
        "radius": 1, "units": "mm", "tangent_chain": False},
        _refused("component 'OwnerA' at 'OwnerA:1'",
                 "component 'OwnerB' at 'OwnerB:1'",
                 "Fillet one component's edges per call", "no feature was created"))
    rows += _retire_reads(tag, targets, [], after=True)
    for owner in ("OwnerA", "OwnerB"):
        rows.append(("model_inspect", lambda c, owner=owner: {
            "target": _ctx_get(c, tag + "_body_handles", "body handles")[owner],
            "include": ["default", "mass"], "per_body": True, "units": "mm",
            "accuracy": "very_high"},
            _retire_compare(tag + "_" + owner + "_state", _symmetric_target_body_state, True), None))

    def duplicated_edge_result(p):
        note = p.get("note") or ""
        return _measured("same-owner duplicate edge control",
                         {"edges_cut": p.get("edges_cut"),
                          "edges_requested": p.get("edges_requested"),
                          "faces_created": p.get("faces_created"), "note": note},
                         p.get("filleted") is True and p.get("edges_cut") == 1
                         and p.get("edges_requested") == 2
                         and p.get("faces_created") == 1
                         and p.get("tangent_chain") is False
                         and "The 2 handles named 1 distinct edge(s), so each was sent once." in note)

    write("model_fillet", lambda c: {"edges": [
        _ctx_get(c, tag + "_edge_a", "OwnerA edge")]*2,
        "radius": 1, "units": "mm", "tangent_chain": False},
        duplicated_edge_result,
        (tag + "_feature", _recall(tag + "_feature", lambda p: p["feature"])))

    def changed_owner_a(p):
        now = _symmetric_target_body_state(p)
        before = _RECALL.get(tag + "_OwnerA_state")
        return _measured("same-owner fillet changes only OwnerA material", now,
            now is not None and before is not None
            and _near(now["material"].get("volume"), 997.853982, .001)
            and _near(now["material"].get("area"), 595.2787596, .01)
            and now["bounds"] == before["bounds"])

    rows += [
        ("model_inspect", lambda c: {"target": _ctx_get(c, tag + "_body_handles",
            "body handles")["OwnerA"], "include": ["default", "mass"], "per_body": True,
            "units": "mm", "accuracy": "very_high"}, changed_owner_a, None),
        ("model_inspect", lambda c: {"target": _ctx_get(c, tag + "_body_handles",
            "body handles")["OwnerB"], "include": ["default", "mass"], "per_body": True,
            "units": "mm", "accuracy": "very_high"},
         _retire_compare(tag + "_OwnerB_state", _symmetric_target_body_state, True), None),
        ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                        "tree_handles": True, "max_depth": 10, "max_results": 2000},
         _edge_extent_history(tag, tag + "_feature", "FilletFeature"), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, tag + "_home", "story"),
             "expect_document": _ctx_get(c, tag + "_doc", "scratch")}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, tag + "_doc", "scratch"),
             "save_changes": False, "expect_document": _ctx_get(c, tag + "_home", "story")},
         _document_closed, None)]
    return rows


def _cross_owner_body_handles(p):
    """Require one exact solid-body handle from each recorded component placement."""
    tree = p.get("tree") or {}
    nodes = {row.get("full_path"): row for row in tree.get("children") or []}
    result = {}
    valid = tree.get("truncated") is False and tree.get("children_truncated") is False
    for owner in ("OwnerA", "OwnerB"):
        node = nodes.get(owner + ":1") or {}
        bodies = node.get("bodies") or []
        valid = (valid and node.get("body_count") == len(bodies) == 1
                 and node.get("children_truncated") is not True
                 and len(bodies) == 1 and bodies[0].get("is_solid") is True
                 and bodies[0].get("visible") is True
                 and isinstance(bodies[0].get("handle"), str) and bool(bodies[0]["handle"]))
        if len(bodies) == 1:
            result[owner] = bodies[0].get("handle")
    valid = valid and set(result) == {"OwnerA", "OwnerB"}
    if valid:
        _RECALL["cross_owner_fillet_body_handles"] = result
    return _measured("two exact solid body handles from the placed owner rows", result, valid)


def _cross_owner_edge(owner, point):
    """Require one fresh edge handle at its independently measured position."""
    def check(p):
        found = [r for r in p.get("matches") or [] if r.get("position") == point]
        valid = (p.get("units") == "mm" and p.get("match_count") >= p.get("returned") == 1
                 and len(found) == 1 and found[0].get("kind") == "line_edge"
                 and bool(found[0].get("handle")))
        return _measured(owner + " edge handle at measured point", found, valid)
    return check


_SOLIDS += _cross_owner_fillet_rows()


def _placed_extent_pose_state(p):
    """Return the one measured placed stock's complete finite pose, or None when unread."""
    rows = p.get("all_occurrences")
    if (p.get("units") != "mm" or p.get("is_healthy") is not True
            or not isinstance(rows, list) or len(rows) != p.get("all_occurrence_count") or len(rows) != 1
            or p.get("occurrence_count") != 1 or len(p.get("occurrences") or []) != 1
            or p.get("joint_count") != 0 or p.get("joints") != []
            or any(p.get(k) is not False for k in ("all_occurrences_truncated", "occurrences_truncated", "joints_truncated"))):
        return None
    expected = {"origin": [30, 20, 40], "x_axis": [1, 0, 0], "y_axis": [0, 0, 1],
                "z_axis": [0, -1, 0], "bbox_center": [36, 20, 44], "bbox_size": [12, 10, 8]}
    for row in rows + p["occurrences"]:
        if (row.get("full_path", row.get("name")) != "PlacedStock:1" or row.get("component") != "PlacedStock"
                or row.get("body_count") != 1 or any(type(row.get(k)) is not bool for k in ("grounded", "ground_to_parent"))
                or any(not isinstance(row.get(k), list) or len(row[k]) != 3
                       or any(not _num(v) or not math.isfinite(v) or not _near(v, e, .000001)
                              for v, e in zip(row[k], values)) for k, values in expected.items())):
            return None
    return {k: v for k, v in p.items() if k not in ("note", "active_document")}


def _placed_extent_frame_state(p):
    """Return the readable measured placed sketch frame and current profile count."""
    frame = p.get("frame") or {}
    expected = {"origin_mm": [30, 20, 40], "normal": [0, -1, 0],
                "x_world": [1, 0, 0], "y_world": [0, 0, 1]}
    if (p.get("units") != "mm" or p.get("component") != "PlacedStock" or p.get("profile_count") != 1
            or frame.get("space") != "world" or p.get("profiles_stale") or p.get("timeline_marker_unrestored")
            or any(not isinstance(frame.get(k), list) or len(frame[k]) != 3
                   or any(not _num(v) or not math.isfinite(v) or not _near(v, e, .000001)
                          for v, e in zip(frame[k], values)) for k, values in expected.items())):
        return None
    return {"frame": frame, "profile_count": p["profile_count"]}


def _placed_extent_refusal_rows():
    """Exercise the recorded rotated placed refusals without asserting their native cause."""
    rows = [("doc_get", {}, _home_document, ("placed_extent_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "placed_extent_home", "story")},
             _new_document, ("placed_extent_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, a=args: _combine_pin(c, "placed_extent_doc", a(c) if callable(a) else a), check, save))
    write("sketch_create", {"name": "Witness", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "Witness", "units": "mm", "geometry": [
        {"kind": "rectangle", "x1": 100, "y1": 0, "x2": 120, "y2": 20}]})
    write("model_extrude", {"sketch_name": "Witness", "distance": 20, "units": "mm"}, _extruded)
    write("model_create_component", {"name": "PlacedStock", "x": 30, "y": 20, "z": 40,
        "rotate_deg": 90, "rotate_axis": "x", "units": "mm", "activate": True}, _made_component)
    write("sketch_create", {"name": "Stock", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "Stock", "units": "mm", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 12, "y2": 8}]})
    write("model_extrude", {"sketch_name": "Stock", "distance": 5, "symmetric": True, "units": "mm"}, _extruded)
    write("sketch_create", {"name": "Cut", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "Cut", "units": "mm", "geometry": [
        {"kind": "circle", "cx": 5, "cy": 4, "radius": .5}]})
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True})

    def body_handles(p):
        tree = (p.get("tree") or {})
        children, root = tree.get("children") or [], tree.get("root_bodies") or []
        bodies = (children[0].get("bodies") or []) if len(children) == 1 else []
        valid = (_retire_design_state(p) is not None and len(children) == len(root) == len(bodies) == 1
                 and children[0].get("full_path") == "PlacedStock:1" and children[0].get("body_count") == 1
                 and all(b.get("is_solid") is True and b.get("visible") is True
                         and isinstance(b.get("handle"), str) and b["handle"] for b in (root[0], bodies[0])))
        if valid:
            _RECALL["placed_extent_bodies"] = {"stock": bodies[0]["handle"], "witness": root[0]["handle"]}
        return _measured("fresh exact placed target and root witness body handles", tree, valid)
    rows.append(("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
        "max_depth": 10, "max_results": 2000}, body_handles,
        ("placed_extent_bodies", lambda p: _RECALL["placed_extent_bodies"])))

    def read_states(after):
        for tool, args, check, save in _retire_reads("placed_extent", ["", "PlacedStock:1"], [], after):
            rows.append((tool, lambda c, a=args: dict(a), check, save))
        for role in ("stock", "witness"):
            rows.append(("find_geometry", lambda c, role=role: {
                "target": _ctx_get(c, "placed_extent_bodies", "exact fixture bodies")[role], "max_results": 100, "units": "mm"},
                _retire_compare("placed_extent_" + role + "_geometry", _edge_extent_geometry, after), None))
        rows.extend([
            ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, "placed_extent_bodies", "exact fixture bodies")["witness"]),
                "per_body": True}, _retire_compare("placed_extent_witness", _symmetric_target_body_state, after), None),
            ("assembly_get", lambda c: {"include": ["all_occurrences", "poses"], "units": "mm",
                "max_occurrences": 100, "max_all_occurrences": 100, "max_joints": 100},
                _retire_compare("placed_extent_poses", _placed_extent_pose_state, after), None),
            ("sketch_get", lambda c: {"component": "PlacedStock:1", "sketch_name": "Cut", "units": "mm"},
                _retire_compare("placed_extent_frame", _placed_extent_frame_state, after), None)])
    read_states(False)
    for distance, symmetric, scoped in ((1, False, True), (-1, False, True), (1, True, True)):
        write("model_extrude", lambda c, distance=distance, symmetric=symmetric, scoped=scoped: {
            "sketch_name": "Cut", "component": "PlacedStock:1", "distance": distance, "extent": "through_all",
            "symmetric": symmetric, "units": "mm", "operation": "cut",
            **({"target_bodies": [_ctx_get(c, "placed_extent_bodies", "exact fixture bodies")["stock"]]} if scoped else {})},
            _refused("body not found", "does not establish why", "sketch_get for the profile and frame", "find_geometry for the target body geometry",
                     "sign cannot fix a symmetric extent" if symmetric else "try extent='distance'"))
        read_states(True)

    def finite_cut_effect(p):
        now = _retire_material_state(p)
        before = _RECALL.get("placed_extent_PlacedStock:1")
        valid = now is not None and before is not None
        if valid:
            removed = before["shape"]["volume"] - now["shape"]["volume"]
            expected = math.pi * .5 ** 2 * (before["shape"]["volume"] / (12 * 8)) / 2
            valid = (_near(removed, expected, .001)
                     and _sweep_mode_box_equal(now["shape"], before["shape"]))
        return _measured("finite distance cuts only the positive half of placed stock", now, valid)

    write("model_extrude", {"sketch_name": "Cut", "component": "PlacedStock:1",
        "extent": "distance", "distance": 10, "units": "mm", "operation": "cut"}, _extruded)
    rows.extend([
        ("model_inspect", {"target": "PlacedStock:1", "include": ["default", "mass"],
            "per_body": True, "accuracy": "very_high", "units": "mm"}, finite_cut_effect, None),
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, "placed_extent_bodies", "fixture bodies")["witness"]),
            "per_body": True}, _retire_compare("placed_extent_witness", _symmetric_target_body_state, True), None),
        ("assembly_get", {"include": ["all_occurrences", "poses"], "units": "mm",
            "max_occurrences": 100, "max_all_occurrences": 100, "max_joints": 100},
            _retire_compare("placed_extent_poses", _placed_extent_pose_state, True), None),
        ("design_get", {"include": ["timeline"], "max_results": 2000},
         lambda p: _measured("distance remedy leaves healthy history at the end", p.get("timeline"),
            (p.get("timeline") or {}).get("marker_position") == (p.get("timeline") or {}).get("count")
            and not (p.get("timeline") or {}).get("truncated")
            and (p.get("timeline") or {}).get("count") == (p.get("timeline") or {}).get("returned")
                == len((p.get("timeline") or {}).get("timeline") or []) > 0
            and (p.get("timeline") or {}).get("summary", {}).get("states")
                == {"healthy": (p.get("timeline") or {}).get("count")}), None),
    ])
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "placed_extent_home", "story"),
               "expect_document": _ctx_get(c, "placed_extent_doc", "scratch")}, _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "placed_extent_doc", "scratch"), "save_changes": False,
               "expect_document": _ctx_get(c, "placed_extent_home", "story")}, _document_closed, None)]
    return rows


_SOLIDS += _placed_extent_refusal_rows()
_SOLIDS += _pattern_parameter_rows()


def _feature_face_pattern_rows(family, seed_kind):
    """Pattern one hole feature or wall face and independently measure every resulting hole."""
    key = "w2_pattern_" + family + "_" + seed_kind
    count = 2 if family == "rectangular" else 3
    centers = {"rectangular": [(20, 0, 10), (60, 0, 10)],
               "circular": [(-20, 0, 10), (0, 20, 10), (20, 0, 10)],
               "path": [(20, 0, 10), (50, 0, 10), (80, 0, 10)]}[family]
    rows = [("doc_get", {}, _home_document, (key + "_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, key + "_home", "pattern home")},
             _new_document, (key + "_doc", lambda p: p["document_handle"]))]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(c, key + "_doc",
            args(c) if callable(args) else args), check, save))

    def one_body(p):
        names = p.get("result_bodies")
        return _extruded(p) and isinstance(names, list) and len(names) == 1 and bool(names[0])
    def inspect_args(c, role):
        return {**_combine_inspect(_ctx_get(c, key + "_" + role, "pattern body")), "per_body": True}
    def material(expected):
        def check(p):
            state = _symmetric_target_body_state(p)
            return _measured("pattern stock volume and unchanged outer bounds", state,
                state is not None and _near(state["material"]["volume"], expected, .01)
                and all(_near(p.get(axis), size, .001) for axis, size in zip("xyz", (200, 200, 20))))
        return check
    def cylinders(expected):
        def check(p):
            matches = p.get("matches")
            valid = (p.get("match_count") == len(expected) and p.get("returned") == len(expected)
                     and isinstance(matches, list)
                     and len(matches) == len(expected) and not p.get("truncated")
                     and all(m.get("kind") == "cylinder_face" and isinstance(m.get("handle"), str)
                             and m["handle"] and _near(m.get("radius"), 5, .0001)
                             and isinstance(m.get("axis"), list) and len(m["axis"]) == 3
                             and _near(m["axis"][0], 0, .0001)
                             and _near(m["axis"][1], 0, .0001)
                             and _near(abs(m["axis"][2]), 1, .0001)
                             and isinstance(m.get("position"), list)
                             and len(m["position"]) == 3 for m in matches))
            positions = sorted(m["position"] for m in matches) if valid else []
            valid = valid and all(all(_near(a, b, .001) for a, b in zip(actual, want))
                                  for actual, want in zip(positions, sorted(expected)))
            return _measured("distinct radius-5 cylindrical wall centers", positions, valid)
        return check
    def seed(c):
        return {seed_kind: [_ctx_get(c, key + ("_cut" if seed_kind == "features" else "_face"), "pattern seed")]}
    def patterned(p):
        return _measured("new seed kind with independently checkable geometry", p,
            p.get("patterned") is True and p.get("entity_kind") == seed_kind
            and bool(p.get("feature")) and p.get("pattern_geometry_changed") is True
            and p.get("pattern_elements_confirmed") is False
            and p.get("total_instances" if family == "rectangular" else "quantity") == count)

    write("design_activate_component", {"occurrence": "root"})
    write("sketch_create", {"name": "W2Stock", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "W2Stock", "units": "mm", "geometry": [
        {"kind": "rectangle", "x1": -100, "y1": -100, "x2": 100, "y2": 100}]})
    write("model_extrude", {"sketch_name": "W2Stock", "distance": 20, "units": "mm"},
        one_body, (key + "_stock", lambda p: p["result_bodies"][0]))
    write("sketch_create", {"name": "W2Hole", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "W2Hole", "units": "mm", "geometry": [
        {"kind": "circle", "cx": 20, "cy": 0, "radius": 5}]})
    write("model_extrude", lambda c: {"sketch_name": "W2Hole", "distance": 20,
        "units": "mm", "operation": "cut", "target_bodies": [_ctx_get(c, key + "_stock", "stock")]},
        _extruded, (key + "_cut", lambda p: p["feature"]))
    write("sketch_create", {"name": "W2Control", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "W2Control", "units": "mm", "geometry": [
        {"kind": "rectangle", "x1": 300, "y1": 0, "x2": 310, "y2": 10}]})
    write("model_extrude", {"sketch_name": "W2Control", "distance": 10, "units": "mm"},
        one_body, (key + "_control", lambda p: p["result_bodies"][0]))
    if family == "path":
        write("sketch_create", {"name": "W2Path", "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": "W2Path", "units": "mm", "geometry": [
            {"kind": "line", "x1": 20, "y1": 0, "x2": 80, "y2": 0}]})
    rows.extend([
        ("model_inspect", lambda c: inspect_args(c, "stock"), material(800000 - 500 * math.pi), None),
        ("model_inspect", lambda c: inspect_args(c, "control"),
            _retire_compare(key + "_control_state", _symmetric_target_body_state, False), None),
        ("find_geometry", lambda c: {"target": _ctx_get(c, key + "_stock", "stock"),
            "kind": "cylinder_face", "radius": 5, "units": "mm", "max_results": 64},
            cylinders([(20, 0, 10)]), (key + "_face", lambda p: p["matches"][0]["handle"])),
    ])
    args = {"rectangular": {"quantity_one": 2, "spacing_one": 40, "quantity_two": 1, "units": "mm"},
            "circular": {"quantity": 3, "total_angle_deg": 180, "axis": "z"},
            "path": {"path": "sketch:W2Path", "quantity": 3, "distance": 30, "units": "mm"}}[family]
    write("model_pattern_" + family, lambda c: {**args, **seed(c),
        "bodies": [_ctx_get(c, key + "_stock", "stock")]}, _refused("conflict", "Supply only one"))
    rows.append(("model_inspect", lambda c: inspect_args(c, "stock"),
        material(800000 - 500 * math.pi), None))
    if seed_kind == "faces":
        write("model_pattern_" + family, lambda c: {**args,
            "faces": [_ctx_get(c, key + "_face", "face")] * 2},
            _refused("repeated seed", "list each entity once"))
        rows.append(("model_inspect", lambda c: inspect_args(c, "stock"),
            material(800000 - 500 * math.pi), None))
    write("model_pattern_" + family, lambda c: {**args, **seed(c)}, patterned)
    rows.extend([
        ("find_geometry", lambda c: {"target": _ctx_get(c, key + "_stock", "stock"),
            "kind": "cylinder_face", "radius": 5, "units": "mm", "max_results": 64}, cylinders(centers), None),
        ("model_inspect", lambda c: inspect_args(c, "stock"), material(800000 - count * 500 * math.pi), None),
        ("model_inspect", lambda c: inspect_args(c, "control"),
            _retire_compare(key + "_control_state", _symmetric_target_body_state, True), None),
        ("design_get", {"include": ["timeline"], "max_results": 100},
            lambda p: _measured("pattern history healthy at end", p.get("timeline"), _pattern_timeline_healthy(p)
                and (p.get("timeline") or {}).get("marker_position") == (p.get("timeline") or {}).get("count")), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, key + "_home", "home"),
            "expect_document": _ctx_get(c, key + "_doc", "scratch")}, "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, key + "_doc", "scratch"), "save_changes": False,
            "expect_document": _ctx_get(c, key + "_home", "home")}, _document_closed, None),
    ])
    return rows


for _w2_family in ("rectangular", "circular", "path"):
    for _w2_kind in ("features", "faces"):
        _SOLIDS += _feature_face_pattern_rows(_w2_family, _w2_kind)


def _w2_extrude_extent_rows():
    """Check mixed extents, body solutions, thin walls, starts, and second taper from fresh geometry."""
    key = "w2_extents"
    rows = [("doc_get", {}, _home_document, (key + "_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, key + "_home", "home")},
             _new_document, (key + "_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(c, key + "_doc",
            args(c) if callable(args) else args), check, save))

    rows.append(("design_activate_component", lambda c: _combine_pin(c, key + "_doc",
        {"occurrence": "root"}), "ok", None))
    def rectangle(name, x, y, width, height, plane="xy"):
        write("sketch_create", {"name": name, "plane": plane})
        write("sketch_add_geometry", {"sketch_name": name, "units": "mm", "geometry": [{
            "kind": "rectangle", "x1": x, "y1": y, "x2": x + width, "y2": y + height}]})

    def box(name, x, y, z, width, height, depth):
        write("model_construction", {"kind": "plane", "plane": "xy", "offset": z,
                                     "units": "mm", "name": name + "Plane"})
        rectangle(name + "S", x, y, width, height, name + "Plane")
        write("model_extrude", {"sketch_name": name + "S", "distance": depth,
                                "units": "mm", "operation": "new"}, _extruded,
              (key + "_" + name, _recall(key + "_" + name, lambda p: p["result_bodies"][0])))

    def retain_top_face(p, recall_key, z, area, label):
        hits = [m for m in p.get("matches", []) if m.get("kind") == "planar_face"
                and m.get("handle") and _near((m.get("position") or [0, 0, 0])[2], z, .001)
                and _near((m.get("normal") or [0, 0, 0])[2], 1, .001)
                and _near(m.get("area"), area, .001)]
        if len(hits) == 1:
            _RECALL[recall_key] = hits[0]["handle"]
        return _measured(label, hits, len(hits) == 1)

    # Separate target bodies make the two minimum-solution cases independent.
    rectangle("W2NearProfile", 0, 0, 10, 8)
    rectangle("W2FarProfile", 50, 0, 10, 8)
    box("W2NearTarget", 0, 0, 4, 20, 16, 3)
    box("W2FarTarget", 50, 0, 4, 20, 16, 3)

    def retain_body_handles(p):
        body_rows = (p.get("tree") or {}).get("root_bodies") or []
        retained = {}
        target_names = {"near": _RECALL.get(key + "_W2NearTarget"),
                        "far": _RECALL.get(key + "_W2FarTarget")}
        for role, body_name in target_names.items():
            hits = [row for row in body_rows if isinstance(body_name, str)
                    and row.get("name") == body_name
                    and isinstance(row.get("handle"), str) and row["handle"]]
            if len(hits) == 1:
                retained[role] = hits[0]["handle"]
                _RECALL[key + "_" + role + "_target_handle"] = hits[0]["handle"]
        return _measured("unique exact root body handles for near/far stops",
            {"target_names": target_names, "body_names": [row.get("name") for row in body_rows],
             "retained": retained, "truncated": (p.get("tree") or {}).get("root_bodies_truncated")},
            len(retained) == 2 and (p.get("tree") or {}).get("root_bodies_truncated") is not True)
    rows.append(("design_get", {"include": ["tree"], "tree_bodies": True}, retain_body_handles, None))
    rows += [
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_W2NearTarget", "near target")), "per_body": True},
         _retire_compare(key + "_near_target_state", _symmetric_target_body_state, False), None),
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_W2FarTarget", "far target")), "per_body": True},
         _retire_compare(key + "_far_target_state", _symmetric_target_body_state, False), None)]
    rectangle("W2ControlS", 100, 0, 5, 5)
    write("model_extrude", {"sketch_name": "W2ControlS", "distance": 2, "units": "mm"},
          _extruded, (key + "_control", lambda p: p["result_bodies"][0]))
    rows.append(("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_control", "control")), "per_body": True},
                 _retire_compare(key + "_control_state", _symmetric_target_body_state, False), None))
    write("model_extrude", lambda c: {"sketch_name": "W2NearProfile", "extent": "to_face",
        "to_object": _ctx_get(_RECALL, key + "_near_target_handle", "near target body handle"),
        "minimum_solution": True, "units": "mm"}, _extruded,
        (key + "_near", lambda p: p["result_bodies"][0]))
    rows.append(("model_inspect", lambda c: _combine_inspect(_ctx_get(c, key + "_near", "near result")),
        _combine_body("near body stop", (0, 0, 0), (10, 8, 4), 320), None))
    write("model_extrude", lambda c: {"sketch_name": "W2FarProfile", "extent": "to_face",
        "to_object": _ctx_get(_RECALL, key + "_far_target_handle", "far target body handle"),
        "minimum_solution": False, "units": "mm"}, _extruded,
        (key + "_far", lambda p: p["result_bodies"][0]))
    rows.append(("model_inspect", lambda c: _combine_inspect(_ctx_get(c, key + "_far", "far result")),
        _combine_body("far body stop", (50, 0, 0), (60, 8, 7), 560), None))

    # Mixed finite distance and face stop have zero offsets; 10x10x(8+4) mm = 1200 mm3.
    rectangle("W2MixedProfile", 150, 0, 10, 10)
    box("W2MixedTarget", 180, 0, 7, 20, 20, 1)
    rows.append(("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_W2MixedTarget", "mixed target")), "per_body": True},
                 _retire_compare(key + "_mixed_target_state", _symmetric_target_body_state, False), None))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, key + "_W2MixedTarget", "stop body"),
        "kind": "planar_face", "nearest_to": [190, 10, 8], "units": "mm", "max_results": 12},
        lambda p: (p.get("match_count") == len(p.get("matches") or [])
                   and retain_top_face(p, key + "_mixed_face", 8, 400,
                                       "unique mixed-side stop face at z=8 mm")), None))
    write("model_extrude", lambda c: {"sketch_name": "W2MixedProfile", "extent": "two_side",
        "extent_one": "to_face", "extent_two": "distance",
        "to_object": _ctx_get(_RECALL, key + "_mixed_face", "z=8 stop face"),
        "distance2": 4, "units": "mm"}, _extruded,
        (key + "_mixed", lambda p: p["result_bodies"][0]))
    rows.append(("model_inspect", lambda c: _combine_inspect(_ctx_get(c, key + "_mixed", "mixed result")),
        _combine_body("mixed distance and to-face extents", (150, 0, -4), (160, 10, 8), 1200), None))

    # Native EXT fixture: 10x8 mm rectangle, 5/3 mm extents, 1/2 mm wall settings -> 348 mm3.
    rectangle("W2ThinProfile", 220, 0, 10, 8)
    write("model_extrude", {"sketch_name": "W2ThinProfile", "extent": "two_side",
        "distance": 5, "distance2": 3, "wall_thickness": 1, "wall_side": "center",
        "wall_thickness_two": 2, "wall_side_two": "side_one", "units": "mm"}, _extruded,
        (key + "_thin", lambda p: p["result_bodies"][0]))
    rows.append(("model_inspect", lambda c: _combine_inspect(_ctx_get(c, key + "_thin", "thin result")),
        _combine_body("two distinct thin wall sides", (219.5, -.5, -3), (230.5, 8.5, 5), 348), None))

    # Native EXS placement: z=.1 start face, +1 mm offset, 5 mm depth, 80 mm2 profile.
    rectangle("W2StartProfile", 260, 0, 10, 8)
    box("W2StartTarget", 260, 0, 0, 20, 20, .1)
    rows.append(("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_W2StartTarget", "start target")), "per_body": True},
                 _retire_compare(key + "_start_target_state", _symmetric_target_body_state, False), None))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, key + "_W2StartTarget", "start body"),
        "kind": "planar_face", "nearest_to": [270, 10, .1], "units": "mm", "max_results": 12},
        lambda p: (p.get("match_count") == len(p.get("matches") or [])
                   and retain_top_face(p, key + "_start_face", .1, 400,
                                       "unique entity start face at z=.1 mm")), None))
    write("model_extrude", lambda c: {"sketch_name": "W2StartProfile", "distance": 5,
        "start_object": _ctx_get(_RECALL, key + "_start_face", "z=.1 start face"),
        "start_offset": "1 mm", "units": "mm"},
        lambda p: _extruded(p) and _near(p.get("start_offset"), 1, .001),
        (key + "_entity_start", lambda p: p["result_bodies"][0]))
    rows.append(("model_inspect", lambda c: _combine_inspect(_ctx_get(c, key + "_entity_start", "entity start")),
        _combine_body("entity start and offset", (260, 0, 1.1), (270, 8, 6.1), 400), None))
    rectangle("W2OffsetProfile", 300, 0, 10, 8)
    write("model_extrude", {"sketch_name": "W2OffsetProfile", "distance": 3,
        "start_offset": 2, "units": "mm"},
        lambda p: _extruded(p) and _near(p.get("start_offset"), 2, .001),
        (key + "_offset_start", lambda p: p["result_bodies"][0]))
    rows.append(("model_inspect", lambda c: _combine_inspect(_ctx_get(c, key + "_offset_start", "offset start")),
        _combine_body("profile-plane start offset", (300, 0, 2), (310, 8, 5), 240), None))

    rectangle("W2TaperProfile", 340, 0, 10, 8)
    write("model_extrude", {"sketch_name": "W2TaperProfile", "extent": "two_side",
        "distance": 5, "distance2": 3, "taper_deg": 0, "taper_two_deg": 5, "units": "mm"},
        lambda p: _measured("second-side taper is read from the feature", p,
            _extruded(p) and _near(p.get("taper_deg"), 0, .001)
            and _near(p.get("taper_two_deg"), 5, .001)),
        (key + "_taper", lambda p: p["result_bodies"][0]))

    def taper_faces(p):
        upper, lower = [], []
        for face in p.get("matches", []):
            normal, position = face.get("normal"), face.get("position")
            if (face.get("kind") == "planar_face" and isinstance(normal, list)
                    and len(normal) == 3 and isinstance(position, list) and len(position) == 3):
                side_norm = math.hypot(normal[0], normal[1])
                if side_norm > .1:
                    tilt = math.degrees(math.atan2(normal[2], side_norm))
                    if position[2] > .001:
                        upper.append(tilt)
                    elif position[2] < -.001:
                        lower.append(tilt)
        return _measured("untapered upper walls and positive 5 degree lower-wall normal tilt",
                         {"upper_signed_tilts": upper, "lower_signed_tilts": lower},
                         p.get("match_count") == p.get("returned")
                         and len(upper) == len(lower) == 4
                         and all(_near(value, 0, .01) for value in upper)
                         and all(_near(value, 5, .01) for value in lower))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, key + "_taper", "taper result"),
        "kind": "planar_face", "max_results": 32, "units": "mm"},
        taper_faces, None))
    rows += [
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_W2NearTarget", "near target")), "per_body": True},
         _retire_compare(key + "_near_target_state", _symmetric_target_body_state, True), None),
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_W2FarTarget", "far target")), "per_body": True},
         _retire_compare(key + "_far_target_state", _symmetric_target_body_state, True), None),
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_W2MixedTarget", "mixed target")), "per_body": True},
         _retire_compare(key + "_mixed_target_state", _symmetric_target_body_state, True), None),
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_W2StartTarget", "start target")), "per_body": True},
         _retire_compare(key + "_start_target_state", _symmetric_target_body_state, True), None),
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_control", "control")), "per_body": True},
         _retire_compare(key + "_control_state", _symmetric_target_body_state, True), None),
        ("design_get", {"include": ["timeline"], "max_results": 100},
         lambda p: _measured("extent history healthy at end marker", p,
             _pattern_timeline_healthy(p) and (p.get("timeline") or {}).get("marker_position")
             == (p.get("timeline") or {}).get("count")), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, key + "_home", "home"),
            "expect_document": _ctx_get(c, key + "_doc", "scratch")}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, key + "_doc", "scratch"),
            "save_changes": False, "expect_document": _ctx_get(c, key + "_home", "home")},
         _document_closed, None)]
    return rows


_SOLIDS += _w2_extrude_extent_rows()


def _w2_revolve_rows(two_sided):
    """Verify one- or two-plane parametric revolve stops against the landed cap planes and sector."""
    key = "w2_revolve_two" if two_sided else "w2_revolve_one"
    rows = [("doc_get", {}, _home_document, (key + "_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, key + "_home", "home")},
             _new_document, (key + "_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(c, key + "_doc",
            args(c) if callable(args) else args), check, save))

    rows.append(("design_activate_component", lambda c: _combine_pin(c, key + "_doc",
        {"occurrence": "root"}), "ok", None))
    # Revolve a 10..12 mm radial by 10 mm high rectangular profile around root Z.
    write("model_construction", {"kind": "plane", "plane": "xy", "offset": -15,
        "units": "mm", "name": "W2RevolveAxisBase"})
    write("sketch_create", {"name": "W2RevolveAxis", "plane": "W2RevolveAxisBase"})
    write("sketch_add_geometry", {"sketch_name": "W2RevolveAxis", "units": "mm", "geometry": [{
        "kind": "rectangle", "x1": 0, "y1": 0, "x2": 1, "y2": 1}]})
    write("model_extrude", {"sketch_name": "W2RevolveAxis", "distance": 30, "units": "mm"},
        _extruded, (key + "_axis_body", lambda p: p["result_bodies"][0]))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, key + "_axis_body", "axis body"),
        "kind": "line_edge", "nearest_to": [0, 0, 0], "max_results": 1, "units": "mm"},
        lambda p: _matched(1, "line_edge")(p)
            and _near(p["matches"][0].get("length"), 30, .001)
            and all(_near(v, 0, .001) for v in p["matches"][0].get("position", []))
            and len(p["matches"][0].get("position", [])) == 3,
        _fg(key + "_axis_edge")))
    write("sketch_create", {"name": "W2RevolveProfile", "plane": "xz"})
    write("sketch_add_geometry", {"sketch_name": "W2RevolveProfile", "units": "mm", "geometry": [{
        "kind": "rectangle", "x1": 10, "y1": 0, "x2": 12, "y2": 10}]})
    for name, angle in (("W2RevolveStopOne", 60), ("W2RevolveStopTwo", -35)):
        if name == "W2RevolveStopTwo" and not two_sided:
            continue
        write("model_construction", lambda c, name=name, angle=angle: {"kind": "plane", "mode": "at_angle", "plane": "xz",
            "edges": [_ctx_get(c, key + "_axis_edge", "root Z edge")], "angle": angle, "name": name}, _datum("plane"),
            (key + "_" + name, _recall(key + "_" + name,
                lambda p: p.get("geometry"))))
    write("sketch_create", {"name": "W2RevolveControlS", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "W2RevolveControlS", "units": "mm", "geometry": [{
        "kind": "rectangle", "x1": 40, "y1": 40, "x2": 45, "y2": 45}]})
    write("model_extrude", {"sketch_name": "W2RevolveControlS", "distance": 5, "units": "mm"},
          _extruded, (key + "_control", lambda p: p["result_bodies"][0]))
    rows.append(("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_control", "control")), "per_body": True},
                 _retire_compare(key + "_control_state", _symmetric_target_body_state, False), None))
    args = {"sketch_name": "W2RevolveProfile", "axis": "z"}
    if two_sided:
        args.update({"to_object": "W2RevolveStopOne", "to_object_two": "W2RevolveStopTwo"})
        expected_volume = 364.773814
        bounds = (-12, -10.392305, -10), (-5, 6.882917, 0)
    else:
        args["to_object"] = "W2RevolveStopOne"
        expected_volume = 230.383461
        bounds = (5, 0, -10), (12, 10.392305, 0)
    write("model_revolve", args,
        lambda p: _measured("plane-stopped revolve feature", p,
            p.get("revolved") is True and p.get("operation") == "new"
            and p.get("extent") == ("two_side_to_object" if two_sided else "to_object")
            and bool(p.get("feature"))),
        (key + "_body", lambda p: p["result_bodies"][0]))
    rows.append(("model_inspect", lambda c: _combine_inspect(_ctx_get(c, key + "_body", "revolve result")),
        _combine_body("independently measured stopped sector", bounds[0], bounds[1], expected_volume), None))

    def caps(p):
        faces = [m for m in p.get("matches", []) if m.get("kind") == "planar_face"
                 and isinstance(m.get("normal"), list) and isinstance(m.get("position"), list)]
        expected = [key + "_W2RevolveStopOne"] + ([key + "_W2RevolveStopTwo"] if two_sided else [])
        found = []
        for ref in expected:
            geometry = _RECALL.get(ref) or {}
            normal, origin = geometry.get("normal"), geometry.get("origin")
            origin = [origin.get(axis) for axis in "xyz"] if isinstance(origin, dict) else origin
            hit = [f for f in faces if normal and origin
                   and abs(sum(a * b for a, b in zip(f["normal"], normal))) > .999
                   and abs(sum((f["position"][i] - origin[i]) * normal[i] for i in range(3))) < .01]
            found.append(len(hit))
        return _measured("each selected root construction plane has a planar result cap",
                         {"cap_matches_per_stop": found}, all(n >= 1 for n in found))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, key + "_body", "revolve result"),
        "kind": "planar_face", "units": "mm", "max_results": 64}, caps, None))
    rows += [
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_control", "control")), "per_body": True},
         _retire_compare(key + "_control_state", _symmetric_target_body_state, True), None),
        ("design_get", {"include": ["timeline"], "max_results": 100},
         lambda p: _measured("revolve timeline healthy at end marker", p,
             _pattern_timeline_healthy(p) and (p.get("timeline") or {}).get("marker_position")
             == (p.get("timeline") or {}).get("count")), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, key + "_home", "home"),
            "expect_document": _ctx_get(c, key + "_doc", "scratch")}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, key + "_doc", "scratch"),
            "save_changes": False, "expect_document": _ctx_get(c, key + "_home", "home")},
         _document_closed, None)]
    return rows


_SOLIDS += _w2_revolve_rows(False)
_SOLIDS += _w2_revolve_rows(True)


def _w2_two_angle_draft_rows():
    """Verify both draft slopes on opposite sides of the measured z=20 mm neutral plane."""
    key = "w2_two_angle_draft"
    rows = [("doc_get", {}, _home_document, (key + "_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, key + "_home", "home")},
             _new_document, (key + "_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(c, key + "_doc",
            args(c) if callable(args) else args), check, save))

    rows.append(("design_activate_component", lambda c: _combine_pin(c, key + "_doc",
        {"occurrence": "root"}), "ok", None))
    write("sketch_create", {"name": "W2DraftBlock", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "W2DraftBlock", "units": "mm", "geometry": [{
        "kind": "rectangle", "x1": 0, "y1": 0, "x2": 30, "y2": 40}]})
    write("model_extrude", {"sketch_name": "W2DraftBlock", "distance": 40, "units": "mm"},
          _extruded, (key + "_body", lambda p: p["result_bodies"][0]))
    write("sketch_create", {"name": "W2DraftControlS", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "W2DraftControlS", "units": "mm", "geometry": [{
        "kind": "rectangle", "x1": 60, "y1": 0, "x2": 80, "y2": 20}]})
    write("model_extrude", {"sketch_name": "W2DraftControlS", "distance": 20, "units": "mm"},
          _extruded, (key + "_control", lambda p: p["result_bodies"][0]))
    write("model_construction", {"kind": "plane", "plane": "xy", "offset": 20,
        "units": "mm", "name": "W2DraftNeutral"}, _datum_plane("xy"))
    rows.append(("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_body", "draft source")), "per_body": True},
                 _retire_compare(key + "_source_state", _symmetric_target_body_state, False), None))
    rows.append(("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_control", "control")), "per_body": True},
                 _retire_compare(key + "_control_state", _symmetric_target_body_state, False), None))

    def retain_draft_face(p):
        hits = [m for m in p.get("matches", []) if m.get("kind") == "planar_face" and m.get("handle")
                and _near(m.get("area"), 1600, .001)
                and _near((m.get("position") or [None, None, None])[0], 0, .001)
                and _near(abs((m.get("normal") or [0, 0, 0])[0]), 1, .001)]
        if len(hits) == 1:
            _RECALL[key + "_face"] = hits[0]["handle"]
        return _measured("unique full side face crossing the pull plane", hits, len(hits) == 1)
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, key + "_body", "draft source"),
        "kind": "planar_face", "nearest_to": [0, 20, 20], "units": "mm", "max_results": 16},
        retain_draft_face, None))
    write("model_draft", lambda c: {"faces": [_ctx_get(_RECALL, key + "_face", "side face")],
        "pull_direction": "W2DraftNeutral", "angle_deg": 15, "angle_two_deg": 5,
        "tangent_chain": False, "symmetric": True},
        _refused("angle_two_deg", "symmetric=true"))
    rows.append(("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_body", "draft source")), "per_body": True},
                 _retire_compare(key + "_source_state", _symmetric_target_body_state, True), None))
    write("model_draft", lambda c: {"faces": [_ctx_get(_RECALL, key + "_face", "side face")],
        "pull_direction": "W2DraftNeutral", "angle_deg": 15, "angle_two_deg": 5,
        "tangent_chain": False},
        lambda p: _measured("two-angle draft feature", p,
            p.get("drafted") is True and p.get("effect_unverified") is not True
            and bool(p.get("feature"))))

    def slopes(p):
        faces = [m for m in p.get("matches", []) if m.get("kind") == "planar_face"
                 and isinstance(m.get("normal"), list) and isinstance(m.get("position"), list)]
        side_faces = [m for m in faces if abs(m["normal"][1]) < .01
                      and abs(m["normal"][0]) > .5]
        measured = sorted((round(math.degrees(math.atan2(abs(m["normal"][2]),
                    abs(m["normal"][0]))), 3), m["position"][2]) for m in side_faces)
        return _measured("independent 15 and 5 degree side slopes straddle z=20 mm",
            measured, any(_near(a, 15, .2) and z > 20 for a, z in measured)
            and any(_near(a, 5, .2) and z < 20 for a, z in measured))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, key + "_body", "drafted body"),
        "kind": "planar_face", "units": "mm", "max_results": 64}, slopes, None))
    rows.append(("model_inspect", lambda c: _combine_inspect(_ctx_get(c, key + "_body", "drafted body")),
        lambda p: _measured("drafted body has the measured volume", p,
            _near(((p.get("mass") or {}).get("volume")), 45156.497, .02)), None))
    rows += [
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_control", "control")), "per_body": True},
         _retire_compare(key + "_control_state", _symmetric_target_body_state, True), None),
        ("design_get", {"include": ["timeline"], "max_results": 100},
         lambda p: _measured("draft history healthy at end marker", p,
            _pattern_timeline_healthy(p) and (p.get("timeline") or {}).get("marker_position")
            == (p.get("timeline") or {}).get("count")), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, key + "_home", "home"),
            "expect_document": _ctx_get(c, key + "_doc", "scratch")}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, key + "_doc", "scratch"),
            "save_changes": False, "expect_document": _ctx_get(c, key + "_home", "home")},
         _document_closed, None)]
    return rows


_SOLIDS += _w2_two_angle_draft_rows()


_SIDE_FIXTURE = """CASE = __CASE__
ROTATED = __ROTATED__
FLIP = __FLIP__
MODE = __MODE__


def run(context):
    import adsk.core, adsk.fusion, json, math
    app = adsk.core.Application.get()
    doc = app.activeDocument
    design = adsk.fusion.Design.cast(app.activeProduct)
    if doc is None or doc.isSaved or design is None:
        raise RuntimeError('Side fixture requires its own unsaved design')
    root = design.rootComponent
    if (design.designType != adsk.fusion.DesignTypes.ParametricDesignType
            or design.activeComponent != root or design.timeline.count
            or root.bRepBodies.count or root.sketches.count or root.occurrences.count):
        raise RuntimeError('Side fixture requires a blank parametric scratch')
    matrix = adsk.core.Matrix3D.create()
    if ROTATED:
        axis = adsk.core.Vector3D.create(1, 2, 3)
        if axis.normalize() is not True:
            raise RuntimeError('Fixture rotation axis is invalid')
        if matrix.setToRotation(math.radians(47), axis,
                                adsk.core.Point3D.create(0, 0, 0)) is not True:
            raise RuntimeError('Fixture rotation refused')
        matrix.translation = adsk.core.Vector3D.create(7, 3, 5)
    occ = root.occurrences.addNewComponent(matrix)
    comp = occ.component
    comp.name = 'SidePart'
    if occ.activate() is not True or design.activeComponent != comp:
        raise RuntimeError('Fixture component did not become active')

    def rectangle(name, x, width, height, plane=None, allow_projected=False):
        sketch = comp.sketches.add(plane if plane is not None else comp.xYConstructionPlane)
        sketch.name = name
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(
            adsk.core.Point3D.create(x, 0, 0), adsk.core.Point3D.create(x + width, height, 0))
        if not allow_projected and sketch.profiles.count != 1:
            raise RuntimeError('Fixture profile is not unique: ' + name)
        return sketch

    def block(name, x, width, height, depth):
        sketch = rectangle(name + 'Sketch', x, width, height)
        given = comp.features.extrudeFeatures.createInput(
            sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        if given.setDistanceExtent(False, adsk.core.ValueInput.createByReal(depth)) is not True:
            raise RuntimeError('Fixture block extent refused')
        feature = comp.features.extrudeFeatures.add(given)
        if feature is None or feature.bodies.count != 1:
            raise RuntimeError('Fixture block did not create exactly one body')
        body = feature.bodies.item(0)
        body.name = name
        return body

    control = block('SideControl', 6, 2, 2, 2)
    bottom = [f for f in control.faces if adsk.core.Plane.cast(f.geometry) is not None
              and abs(f.centroid.z) < 1e-7 and abs(f.area - 4) < 1e-7]
    if len(bottom) != 1:
        raise RuntimeError('Fixture control bottom face is not unique')
    reference_face = bottom[0]
    selected_planes = []
    target = None
    extra_control = None
    args = {}
    if CASE == 'draft':
        target = block('SideTarget', 0, 3, 4, 4)
        planes = comp.constructionPlanes
        given = planes.createInput()
        if given.setByOffset(comp.xYConstructionPlane, adsk.core.ValueInput.createByReal(2)) is not True:
            raise RuntimeError('Fixture neutral plane refused')
        neutral = planes.add(given)
        neutral.name = 'SideNeutral'
        hits = [f for f in target.faces
                if adsk.core.Plane.cast(f.geometry) is not None and abs(f.centroid.x) < 1e-7
                and abs(f.area - 16) < 1e-7]
        if len(hits) != 1:
            raise RuntimeError('Fixture draft face is not unique')
        args = {'faces': [hits[0].entityToken], 'pull_direction': neutral.entityToken,
                'angle_deg': 15, 'angle_two_deg': 5, 'tangent_chain': False, 'flip': FLIP}
        origin, normal = neutral.geometry.origin, neutral.geometry.normal
        if MODE == 'face':
            face_sketch = rectangle('PullFaceSketch', 6, 2, 2, neutral)
            pull_input = comp.features.extrudeFeatures.createInput(
                face_sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            if pull_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(2)) is not True:
                raise RuntimeError('Pull face block extent refused')
            pull_feature = comp.features.extrudeFeatures.add(pull_input)
            if pull_feature is None or pull_feature.bodies.count != 1:
                raise RuntimeError('Pull face block did not create one body')
            extra_control = pull_feature.bodies.item(0)
            extra_control.name = 'PullFaceControl'
            pull_faces = [f for f in extra_control.faces if adsk.core.Plane.cast(f.geometry) is not None
                          and abs(f.centroid.z - 2) < 1e-7 and abs(f.area - 4) < 1e-7]
            if len(pull_faces) != 1:
                raise RuntimeError('Pull bottom face is not unique')
            pull = pull_faces[0]
            args['pull_direction'] = pull.entityToken
            origin, normal = pull.geometry.origin, pull.geometry.normal
    elif CASE == 'extrude':
        profile_x = 20 if MODE == 'face' else 0
        sketch = rectangle('SideProfile', profile_x, 3, 4,
                           comp.xZConstructionPlane if MODE == 'xz' else
                           comp.yZConstructionPlane if MODE == 'yz' else
                           reference_face if MODE == 'face' else None,
                           allow_projected=MODE == 'face')
        args = {'sketch_name': sketch.name, 'component': comp.name, 'extent': 'two_side',
                'distance': 10, 'distance2': 20, 'taper_deg': 5, 'taper_two_deg': 15, 'units': 'mm'}
        if MODE != 'xy':
            profile_hits = []
            for profile in sketch.profiles:
                props = profile.areaProperties()
                center = props.centroid
                if (abs(props.area - 12) < 1e-7
                        and abs(center.x - profile_x - 1.5) < 1e-7
                        and abs(center.y - 2) < 1e-7):
                    profile_hits.append(profile)
            if len(profile_hits) != 1:
                raise RuntimeError('Authored rectangle profile did not resolve by area and centroid')
            args['profile_index'] = profile_hits[0].entityToken
        origin, normal = sketch.origin, sketch.xDirection.crossProduct(sketch.yDirection)
    elif CASE == 'fillet':
        target = block('SideTarget', 0, 2.2, 2, 1.8)
        hits = [e for e in target.edges if abs(e.boundingBox.minPoint.x) < 1e-7
                and abs(e.boundingBox.maxPoint.x) < 1e-7 and abs(e.boundingBox.minPoint.y) < 1e-7
                and abs(e.boundingBox.maxPoint.y) < 1e-7
                and abs(e.boundingBox.maxPoint.z - e.boundingBox.minPoint.z - 1.8) < 1e-7]
        if len(hits) != 1 or hits[0].faces.count != 2:
            raise RuntimeError('Fixture fillet edge/adjacent faces are not unique')
        edge = hits[0]
        for face in edge.faces:
            plane = adsk.core.Plane.cast(face.geometry)
            if plane is None:
                raise RuntimeError('Fixture fillet adjacent face is not planar')
            good, outward = face.evaluator.getNormalAtPoint(face.pointOnFace)
            if not good:
                raise RuntimeError('Fixture adjacent face normal unreadable')
            selected_planes.append({'face_token': face.entityToken, 'point_cm': face.pointOnFace.asArray(),
                                    'normal': outward.asArray()})
        args = {'edges': [edge.entityToken], 'fillet_type': 'asymmetric', 'radius': 1,
                'end_radius': 2, 'flipped': FLIP, 'tangent_chain': False, 'units': 'mm'}
        origin = edge.startVertex.geometry
        normal = origin.vectorTo(edge.endVertex.geometry)
    else:
        raise RuntimeError('Unknown fixture case')
    if normal.normalize() is not True:
        raise RuntimeError('Fixture operand normal is invalid')
    record = {'case': CASE, 'rotated': ROTATED, 'flip': FLIP, 'requested_frame': matrix.asArray(),
              'component_token': comp.entityToken, 'occurrence_token': occ.entityToken,
              'control_token': control.entityToken, 'args': args,
              'target_token': target.entityToken if target else None,
              'extra_control_token': extra_control.entityToken if extra_control else None,
              'operand_origin_cm': origin.asArray(), 'operand_normal': normal.asArray(),
              'operand_token': (pull.entityToken if CASE == 'draft' and MODE == 'face' else
                                neutral.entityToken if CASE == 'draft' else
                                sketch.entityToken if CASE == 'extrude' else None),
              'mode': MODE,
              'adjacent_planes': selected_planes, 'baseline_count': design.timeline.count}
    design.attributes.add('Wave4Side', 'fixture', json.dumps(record))
    if design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('Fixture did not finish at the timeline end')
    print('SIDE:' + json.dumps(record))
"""
_SIDE_READ = """def run(context):
    import adsk.core, adsk.fusion, json, math
    app = adsk.core.Application.get()
    doc = app.activeDocument
    design = adsk.fusion.Design.cast(app.activeProduct)
    if doc is None or doc.isSaved or design is None:
        raise RuntimeError('Side read requires the owned unsaved design')
    tag = design.attributes.itemByName('Wave4Side', 'fixture')
    if tag is None:
        raise RuntimeError('Side read has no ownership marker')
    record = json.loads(tag.value)

    def resolve(token, cls):
        found = list(design.findEntityByToken(token))
        if len(found) != 1 or cls.cast(found[0]) is None:
            raise RuntimeError('Side fixture identity did not resolve uniquely')
        return cls.cast(found[0])

    comp = resolve(record['component_token'], adsk.fusion.Component)
    occ = resolve(record['occurrence_token'], adsk.fusion.Occurrence)
    control = resolve(record['control_token'], adsk.fusion.BRepBody)
    extra = (resolve(record['extra_control_token'], adsk.fusion.BRepBody)
             if record.get('extra_control_token') else None)
    if (design.activeComponent != comp or occ.component != comp or control.parentComponent != comp
            or design.rootComponent.occurrences.count != 1 or design.rootComponent.bRepBodies.count
            or design.timeline.markerPosition != design.timeline.count):
        raise RuntimeError('Side fixture scope or end marker changed')
    matrix = occ.transform2
    origin = adsk.core.Point3D.create(*record['operand_origin_cm'])
    normal = adsk.core.Vector3D.create(*record['operand_normal'])
    face_outward = None
    if record['case'] == 'draft':
        if record.get('mode') == 'face':
            face = resolve(record['operand_token'], adsk.fusion.BRepFace)
            origin, normal = face.geometry.origin, face.geometry.normal
            good, face_outward = face.evaluator.getNormalAtPoint(face.pointOnFace)
            if good is not True or face_outward.normalize() is not True:
                raise RuntimeError('Pull face outward normal did not read')
        else:
            plane = resolve(record['operand_token'], adsk.fusion.ConstructionPlane).geometry
            origin, normal = plane.origin, plane.normal
    elif record['case'] == 'extrude':
        sketch = resolve(record['operand_token'], adsk.fusion.Sketch)
        origin = sketch.origin
        normal = sketch.xDirection.crossProduct(sketch.yDirection)
    if normal.normalize() is not True:
        raise RuntimeError('Operand normal is invalid')
    world_origin, world_normal = origin.copy(), normal.copy()
    if world_origin.transformBy(matrix) is not True or world_normal.transformBy(matrix) is not True:
        raise RuntimeError('Operand frame transform refused')

    def point(values):
        p = adsk.core.Point3D.create(*values)
        if p.transformBy(matrix) is not True:
            raise RuntimeError('Point transform refused')
        return p.asArray()

    def vector(values):
        v = adsk.core.Vector3D.create(*values)
        if v.transformBy(matrix) is not True:
            raise RuntimeError('Vector transform refused')
        return v.asArray()

    def shape(body):
        props = body.getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy)
        return {'volume_cm3': props.volume, 'solid': body.isSolid,
                'vertices_cm': sorted([v.geometry.asArray() for v in body.vertices]),
                'face_count': body.faces.count}

    targets = [b for b in comp.bRepBodies if b != control and b != extra]
    if len(targets) > 1:
        raise RuntimeError('Side read has more than one target body')
    if record.get('target_token'):
        pinned = resolve(record['target_token'], adsk.fusion.BRepBody)
        if len(targets) != 1 or targets[0] != pinned or pinned.parentComponent != comp:
            raise RuntimeError('Draft target identity changed')
    faces, vertices, boundaries = [], [], []
    if targets:
        target = targets[0]
        for index, face in enumerate(target.faces):
            good, outward = face.evaluator.getNormalAtPoint(face.pointOnFace)
            if not good:
                raise RuntimeError('Target face normal unreadable')
            centroid = face.centroid
            signed = origin.vectorTo(centroid).dotProduct(normal)
            cosine = max(-1, min(1, outward.dotProduct(normal) / outward.length))
            faces.append({'index': index, 'handle': face.entityToken, 'area_cm2': face.area,
                          'planar': adsk.core.Plane.cast(face.geometry) is not None,
                          'centroid_local_cm': centroid.asArray(), 'normal_local': outward.asArray(),
                          'centroid_world_cm': point(centroid.asArray()), 'normal_world': vector(outward.asArray()),
                          'signed_distance_cm': signed, 'normal_angle_deg': math.degrees(math.acos(cosine))})
            for prior in record['adjacent_planes']:
                n = adsk.core.Vector3D.create(*prior['normal'])
                p = adsk.core.Point3D.create(*prior['point_cm'])
                if (adsk.core.Plane.cast(face.geometry) is None
                        or abs(abs(n.dotProduct(outward)) - 1) > 1e-6
                        or abs(p.vectorTo(centroid).dotProduct(n)) > 1e-6):
                    continue
                for edge in face.edges:
                    others = [f for f in edge.faces if f != face]
                    if len(others) != 1 or adsk.core.Plane.cast(others[0].geometry) is not None:
                        continue
                    ends = [edge.startVertex.geometry, edge.endVertex.geometry]
                    offsets = []
                    for end in ends:
                        delta = origin.vectorTo(end)
                        along = delta.dotProduct(normal)
                        offsets.append(math.sqrt(max(0, delta.length ** 2 - along ** 2)))
                    boundaries.append({'original_face': prior, 'current_face_handle': face.entityToken,
                                       'boundary_handle': edge.entityToken,
                                       'endpoints_local_cm': [e.asArray() for e in ends],
                                       'endpoints_world_cm': [point(e.asArray()) for e in ends],
                                       'setback_cm': offsets})
        vertices = [{'local_cm': v.geometry.asArray(), 'world_cm': point(v.geometry.asArray()),
                     'signed_distance_cm': origin.vectorTo(v.geometry).dotProduct(normal)} for v in target.vertices]
    proxy_samples = sorted([v.geometry.asArray() for v in control.createForAssemblyContext(occ).vertices])
    expected_samples = sorted([point(v.geometry.asArray()) for v in control.vertices])
    if (len(proxy_samples) != len(expected_samples) or any(abs(a - b) > 1e-6
            for actual, expected in zip(proxy_samples, expected_samples) for a, b in zip(actual, expected))):
        raise RuntimeError('Native-to-world frame does not match assembly proxy geometry')
    unhealthy = [{'name': design.timeline.item(i).name, 'state': int(design.timeline.item(i).healthState)}
                 for i in range(design.timeline.count)
                 if design.timeline.item(i).healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState]
    print('SIDE:' + json.dumps({'case': record['case'], 'rotated': record['rotated'], 'flip': record['flip'],
          'operand': {'origin_local_cm': origin.asArray(), 'normal_local': normal.asArray(),
                      'origin_world_cm': world_origin.asArray(), 'normal_world': world_normal.asArray(),
                      'face_outward_local': face_outward.asArray() if face_outward else None,
                      'face_outward_world': vector(face_outward.asArray()) if face_outward else None},
          'occurrence_frame': matrix.asArray(), 'control': shape(control),
          'extra_control': shape(extra) if extra else None,
          'target': shape(targets[0]) if targets else None, 'faces': faces,
          'vertices': vertices, 'fillet_boundaries': boundaries, 'timeline_count': design.timeline.count,
          'baseline_count': record['baseline_count'], 'unhealthy': unhealthy,
          'frame_control': {'proxy_cm': proxy_samples, 'calculated_cm': expected_samples}}))
"""


def _side_data(p):
    """Decode one owned side witness."""
    if not isinstance(p, str) or not p.startswith("SIDE:"):
        raise AssertionError("Owned side witness did not return SIDE data")
    return json.loads(p[5:])


def _side_equal(a, b):
    """Compare the independent shape/frame snapshots within numeric read tolerance."""
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(_side_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(_side_equal(x, y) for x, y in zip(a, b))
    return _near(a, b, 1e-6) if isinstance(a, (int, float)) and not isinstance(a, bool) else a == b


def _side_observed(p, key, phase):
    """Compare tool side disclosure with independently read geometry and preserved controls."""
    got = _side_data(p)
    if phase == "before":
        _RECALL[key + "_before"] = got
        return _measured("side fixture frame", got["occurrence_frame"],
                         not got["unhealthy"] and got["rotated"] is True
                         and _side_equal(got["occurrence_frame"], _RECALL[key + "_fixture"]["requested_frame"]))
    before = _RECALL[key + "_before"]
    valid = (not got["unhealthy"] and _side_equal(before["control"], got["control"])
             and _side_equal(before["extra_control"], got["extra_control"])
             and _side_equal(before["occurrence_frame"], got["occurrence_frame"]))
    if phase == "restored":
        valid = (valid and _side_equal(before["target"], got["target"])
                 and before["timeline_count"] == got["timeline_count"])
    else:
        edit = _RECALL[key + "_edit"]
        valid = valid and got["timeline_count"] == before["timeline_count"] + 1 and got["target"] is not None
        if got["case"] in ("draft", "extrude"):
            ref = edit.get("side_reference") or {}
            outward = got["operand"]["face_outward_world"] if got["case"] == "draft" else None
            expected_normal = outward or got["operand"]["normal_world"]
            valid = (valid and ref.get("frame") == "world"
                     and _side_equal(list(ref.get("normal_world") or []), expected_normal)
                     and _side_equal(list(ref.get("origin_cm") or []), got["operand"]["origin_world_cm"]))
            faces = got["faces"]
            if got["case"] == "draft":
                if outward:
                    geometry = got["operand"]["normal_world"]
                    opposed = sum(a * b for a, b in zip(outward, geometry)) < -.999
                    valid = (valid and opposed and "A face uses its outward normal" in edit.get("note", "")
                             and any(f["signed_distance_cm"] < -.5
                                     and _near(180 - f["normal_angle_deg"], 75, .01) for f in faces)
                             and any(f["signed_distance_cm"] > .5
                                     and _near(180 - f["normal_angle_deg"], 95, .01) for f in faces))
                else:
                    valid = (valid and "angle_deg on its positive side" in edit.get("note", "")
                             and any(f["signed_distance_cm"] > .5 and _near(f["normal_angle_deg"], 105, .01) for f in faces)
                             and any(f["signed_distance_cm"] < -.5 and _near(f["normal_angle_deg"], 85, .01) for f in faces))
            else:
                valid = (valid and "distance2/taper_two_deg oppose" in edit.get("note", "")
                         and any(f["signed_distance_cm"] > .1 and _near(f["normal_angle_deg"], 95, .01) for f in faces)
                         and any(f["signed_distance_cm"] < -.1 and _near(f["normal_angle_deg"], 75, .01) for f in faces))
        else:
            bounds = got["fillet_boundaries"]
            offsets = sorted(round(b["setback_cm"][0], 6) for b in bounds)
            valid = (valid and "side_mapping" in edit and edit["side_mapping"] is None
                     and "Geometric setback-side mapping is unavailable" in edit.get("note", "")
                     and edit.get("flipped") is True and offsets == [.1, .2]
                     and any(b["original_face"]["normal"][0] < -.9
                             and all(_near(v, .2, 1e-6) for v in b["setback_cm"]) for b in bounds)
                     and any(b["original_face"]["normal"][1] < -.9
                             and all(_near(v, .1, 1e-6) for v in b["setback_cm"]) for b in bounds))
    return _measured("rotated side " + phase, got, valid)


def _side_disclosure_rows():
    """Demonstrate operand-relative replies on rotated owned component fixtures."""
    home = "side_disclosure_home"
    rows = [("doc_get", {}, _home_document, (home, _home_address))]
    def observed(key, phase):
        def check(payload):
            return _side_observed(payload, key, phase)
        return check
    for case, mode in (("draft", "xy"), ("extrude", "xy"), ("fillet", "xy"),
                       ("extrude", "xz"), ("extrude", "yz"), ("extrude", "face"),
                       ("draft", "face")):
        key = "side_disclosure_" + case + ("_" + mode if mode != "xy" else "")
        rows.append(("doc_new", lambda c: {"expect_document": _ctx_get(c, home, "home")},
                     _new_document, (key + "_doc", lambda p: p["document_handle"])))
        def script_args(c, code, key=key, read_only=True):
            return {"script": code, "read_only": read_only,
                    "expect_document": _ctx_get(c, key + "_doc", "side scratch")}
        flip = not (case == "draft" and mode == "face")
        code = (_SIDE_FIXTURE.replace("__CASE__", repr(case))
                .replace("__ROTATED__", "True").replace("__FLIP__", repr(flip))
                .replace("__MODE__", repr(mode)))
        def built(p, key=key):
            _RECALL[key + "_fixture"] = _side_data(p)
            return bool(_RECALL[key + "_fixture"]["requested_frame"])
        rows.append(("sys_execute_script", lambda c, code=code, f=script_args: f(c, code, read_only=False),
                     built, (key + "_fixture", _side_data)))
        rows.append(("sys_execute_script", lambda c, f=script_args: f(c, _SIDE_READ),
                     observed(key, "before"), None))
        def edit_args(c, key=key):
            return {**_ctx_get(c, key + "_fixture", "fixture")["args"],
                    "expect_document": _ctx_get(c, key + "_doc", "side scratch")}
        def edited(p, key=key):
            _RECALL[key + "_edit"] = p
            return bool(p.get("feature"))
        rows.append(("model_" + case, edit_args, edited, (key + "_feature", lambda p: p["feature"])))
        rows.append(("sys_execute_script", lambda c, f=script_args: f(c, _SIDE_READ),
                     observed(key, "after"), None))
        rows.append(("design_delete_feature", lambda c, key=key: {
            "feature": "SidePart/" + _ctx_get(c, key + "_feature", "feature"),
            "expect_document": _ctx_get(c, key + "_doc", "side scratch")}, "ok", None))
        rows.append(("sys_execute_script", lambda c, f=script_args: f(c, _SIDE_READ),
                     observed(key, "restored"), None))
        rows.append(("doc_activate", lambda c, key=key: {
            "name": _ctx_get(c, home, "home"),
            "expect_document": _ctx_get(c, key + "_doc", "side scratch")},
            _activated(), None))
        rows.append(("doc_close", lambda c, key=key: {
            "name": _ctx_get(c, key + "_doc", "side scratch"), "save_changes": False,
            "expect_document": _ctx_get(c, home, "home")}, _document_closed, None))
    return rows


_SOLIDS += _side_disclosure_rows()
