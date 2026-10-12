# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""ACT rows: the vise that holds the machined part, and the joint bench beside it.

The billet, the fixed and moving jaws and the lead screw that drives them, jointed and driven live
with the grip proven by measurement rather than by the joint calls returning ok; then the bench
that gives every other joint motion and assembly verb a rig of its own.
"""

import math

from verify_core import (
    _RECALL, _as_built, _axis_kept, _axis_landed, _box, _captured, _constrained, _ctx_get,
    _datum_plane, _document_closed, _driven_angle, _driven_slide, _dwell, _extruded, _fg,
    _grounded, _home_address, _home_document, _interference_measured, _joint_axis_vs,
    _joint_bench, _joint_heading, _joint_is, _joint_limits, _jointed, _jointed_at_geometry,
    _joints_listed, _limits_survived, _link_healthy, _made_component, _made_component_inactive, _measured, _mod360,
    _motion_linked, _moved_occurrence, _near, _new_document, _num, _recall, _refused, _revolved,
    _rigid_grouped, _watch)
from verify_acts_model_sweep import _retire_compare, _retire_design_state, _retire_reads, _retire_material_state
from verify_acts_model_solids import _edge_extent_geometry


def _joint_preflight_assembly(motion, limits):
    """Check the measured placed pair, motion and every publicly exposed enabled bound."""
    def check(p):
        poses, all_poses, joints = p.get("occurrences"), p.get("all_occurrences"), p.get("joints")
        valid = (p.get("units") == "mm" and p.get("is_healthy") is True
                 and p.get("broken_joints") == p.get("broken_relations") == p.get("unresolved_references") == []
                 and p.get("occurrences_truncated") is False and p.get("all_occurrences_truncated") is False
                 and p.get("joints_truncated") is False and p.get("relations_truncated") is False
                 and p.get("occurrence_count") == p.get("all_occurrence_count") == 2
                 and isinstance(poses, list) and isinstance(all_poses, list) and len(poses) == len(all_poses) == 2
                 and p.get("joint_count") == 1 and isinstance(joints, list) and len(joints) == 1
                 and p.get("relations") == {"rigid_groups": [], "motion_links": [], "constraints": []})
        if valid:
            for rows in (poses, all_poses):
                valid = valid and [r.get("name") for r in rows] == ["A:1", "B:1"]
                for i, r in enumerate(rows):
                    valid = (valid and r.get("body_count") == 1 and r.get("grounded") is False
                             and r.get("ground_to_parent") is (i == 0) and r.get("origin") == [i * 20, 0, 0]
                             and r.get("bbox_center") == [i * 20 + 2, 2, 5] and r.get("bbox_size") == [4, 4, 10]
                             and r.get("x_axis") == [1, 0, 0] and r.get("y_axis") == [0, 1, 0]
                             and r.get("z_axis") == [0, 0, 1] and r.get("joints") == ["AB"])
            joint = joints[0]
            axis_key = "rotation_axis" if motion == "revolute" else "slide_direction"
            valid = (valid and joint.get("name") == "AB" and joint.get("as_built") is True
                     and joint.get("type") == motion and joint.get("dof") == 1 and joint.get("healthy") is True
                     and joint.get("occurrence_one") == "A:1" and joint.get("occurrence_two") == "B:1"
                     and joint.get("rotation_limits_deg") == limits
                     and joint.get(axis_key) == [0, 0, 1]
                     and joint.get("value_now") == ({"angle_deg": 0} if motion == "revolute" else {"slide_mm": 0})
                     and joint.get("frame") == {"origin": [22, 2, 10], "z_axis": [0, 0, 1],
                                                "x_axis": [1, 0, 0], "y_axis": [0, 1, 0]})
            before = _RECALL.get("joint_preflight_poses")
            valid = valid and (before is None or before == [poses, all_poses])
            if before is None and valid:
                _RECALL["joint_preflight_poses"] = [poses, all_poses]
        return _measured("joint preflight placed motion and exposed enabled limits", p, valid)
    return check


def _joint_limit_snapshot(name, motion, unit, lo, hi, key, baseline):
    """Read the enabled bounds and placed-state bundle before and after a refused edit."""
    limit_key = "rotation_limits_deg" if unit == "deg" else "slide_limits_mm"
    def check(p):
        row = next((j for j in (p.get("joints") or []) if j.get("name") == name), None)
        limits = (row or {}).get(limit_key) or {}
        poses = [{k: occ.get(k) for k in ("name", "origin", "x_axis", "y_axis", "z_axis",
                                           "body_count", "bbox_center", "bbox_size")}
                 for occ in p.get("occurrences") or []]
        state = {"type": (row or {}).get("type"), "limits": limits,
                 "value_now": (row or {}).get("value_now"), "frame": (row or {}).get("frame"),
                 "rotation_axis": (row or {}).get("rotation_axis"),
                 "slide_direction": (row or {}).get("slide_direction"), "poses": poses}
        valid = (p.get("is_healthy") is True and state["type"] == motion
                 and _near(limits.get("min"), lo, 1e-3) and _near(limits.get("max"), hi, 1e-3)
                 and p.get("occurrences_truncated") is False
                 and p.get("joints_truncated") is False
                 and len(poses) == p.get("occurrence_count") and len(poses) >= 2
                 and all(isinstance(occ.get("body_count"), int) and occ["body_count"] >= 0
                         and (occ["body_count"] == 0 or occ.get("bbox_size")) for occ in poses))
        prior = _RECALL.get(key)
        valid = valid and (prior is None if baseline else prior is not None and state == prior)
        if baseline and valid:
            _RECALL[key] = state
        return _measured(f"'{name}' keeps its {lo}/{hi} {unit} limits and placed state", state, valid)
    return check


def _joint_preflight_material(p):
    """Read the two independent 4x4x10 millimeter boxes' complete physical snapshot."""
    state = _retire_material_state(p)
    if (state is None or len(state["bodies"]) != 2 or not _near(state["shape"]["volume"], 320, .001)
            or not _near(state["shape"]["area"], 384, .001)
            or p.get("min_point") != {"x": 0, "y": 0, "z": 0}
            or p.get("max_point") != {"x": 24, "y": 4, "z": 10}
            or any(not _near(b.get("volume"), 160, .001)
                   for b in state["bodies"])):
        return None
    return state


def _joint_preflight_rows():
    """Refuse measured joint preconditions before writes and preserve legal controls."""
    rows = [("doc_get", {}, _home_document, ("joint_preflight_home", _home_address)),
            ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True, "max_results": 2000},
             _retire_compare("joint_preflight_home_design", _retire_design_state, False), None),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "joint_preflight_home", "home")}, _new_document,
             ("joint_preflight_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]
    def write(tool, args, check="ok"):
        rows.append((tool, lambda c: {**args, "expect_document": _ctx_get(c, "joint_preflight_doc", "owned joint scene")}, check, None))
    for name, x in (("A", 0), ("B", 20)):
        write("design_activate_component", {"occurrence": "root"})
        write("model_create_component", {"name": name, "x": x, "units": "mm", "activate": True}, _made_component)
        write("sketch_create", {"name": name + "Sketch", "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name + "Sketch", "units": "mm", "geometry": [
            {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 4, "y2": 4}]})
        write("model_extrude", {"sketch_name": name + "Sketch", "distance": 10, "units": "mm", "operation": "new"}, _extruded)
    write("design_activate_component", {"occurrence": "root"})
    write("assembly_ground", {"occurrence": "A:1", "ground_to_parent": True}, _grounded)
    write("assembly_ground", {"occurrence": "B:1", "ground_to_parent": False}, lambda p: p.get("isGroundToParent") is False)
    write("joint_create_as_built", {"occurrence_one": "A:1", "occurrence_two": "B:1", "geometry": "B:1:top",
          "joint_type": "revolute", "name": "AB"}, _as_built)
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True, "focus": ["A:1", "B:1"]})
    assembly = {"include": ["poses", "all_occurrences", "relations"], "units": "mm", "max_joints": 100,
                "max_occurrences": 100, "max_all_occurrences": 100}
    history = {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
               "timeline_params": True, "max_results": 2000}
    def history_state(p):
        state = _retire_design_state(p)
        tl = (p.get("timeline") or {}).get("timeline")
        if state is None or len(tl) != 7 or tl[-1].get("name") != "AB" or tl[-1].get("type") != "AsBuiltJoint":
            return None
        return state
    def held(after):
        rows.append(("model_inspect", lambda c: {"include": ["default", "mass"], "per_body": True,
                     "units": "mm", "accuracy": "very_high"},
                     _retire_compare("joint_preflight_material", _joint_preflight_material, after), None))
        def geometry(p):
            state = _edge_extent_geometry(p)
            if (state is None or len(state) != 18 or sum(r["kind"] == "planar_face" for r in state) != 6
                    or sum(r["kind"] == "line_edge" for r in state) != 12):
                return None
            return state
        for target in ("A:1", "B:1"):
            rows.append(("find_geometry", lambda c, target=target: {"target": target, "units": "mm", "max_results": 100},
                         _retire_compare("joint_preflight_geometry_" + target, geometry, after), None))
    rows += [("assembly_get", assembly, _joint_preflight_assembly("revolute", None), None),
             ("design_get", history, _retire_compare("joint_preflight_asbuilt_history", history_state, False), None)]
    held(False)
    for field, value in (("offset", 5), ("angle", 30)):
        write("joint_edit", {"joint_name": "AB", "joint_type": "slider", field: value, "units": "mm"},
              _refused("AS-BUILT", field + "=" + str(value), "No edits applied", "joint_create"))
        rows += [("assembly_get", assembly, _joint_preflight_assembly("revolute", None), None),
                 ("design_get", history, _retire_compare("joint_preflight_asbuilt_history", history_state, True), None)]
        held(True)
    for motion in ("slider", "revolute"):
        write("joint_edit", {"joint_name": "AB", "joint_type": motion, "axis": "z"},
              lambda p, motion=motion: p.get("edited") is True and p.get("joint_type") == motion)
        rows += [("assembly_get", assembly, _joint_preflight_assembly(motion, None), None),
                 ("design_get", history, _retire_compare("joint_preflight_asbuilt_history", history_state, True), None)]
        held(True)
    write("joint_edit", {"joint_name": "AB", "min_deg": -10, "max_deg": 10},
          lambda p: p.get("edited") is True and p.get("changes") == {"min_deg": -10, "max_deg": 10})
    rows += [("assembly_get", assembly, _joint_preflight_assembly("revolute", {"min": -10, "max": 10}), None),
             ("design_get", history, _retire_compare("joint_preflight_limit_history", history_state, False), None)]
    held(True)
    # The same-axis motion re-set keeps the limits, so a single crossing bound beside it is refused too.
    for motion, field, value, opposite in (({}, "max_deg", -20, "min_deg=-10"), ({}, "min_deg", 20, "max_deg=10"),
                                           ({"joint_type": "revolute", "axis": "z"}, "max_deg", -20, "min_deg=-10")):
        write("joint_edit", {"joint_name": "AB", **motion, field: value},
              _refused(field + "=" + str(value), opposite, "No edits applied", "assembly_get"))
        rows += [("assembly_get", assembly, _joint_preflight_assembly("revolute", {"min": -10, "max": 10}), None),
                 ("design_get", history, _retire_compare("joint_preflight_limit_history", history_state, True), None)]
        held(True)
    for field, value, limits in (("min_deg", -15, {"min": -15, "max": 10}), ("max_deg", 15, {"min": -15, "max": 15})):
        write("joint_edit", {"joint_name": "AB", field: value},
              lambda p, field=field, value=value: p.get("edited") is True and p.get("changes") == {field: value})
        rows.append(("assembly_get", assembly, _joint_preflight_assembly("revolute", limits), None))
        def legal_history(p):
            state = history_state(p)
            prior = _RECALL["joint_preflight_limit_history"]
            return (state is not None and state["tree"] == prior["tree"]
                    and state["timeline"]["timeline"][:-1] == prior["timeline"]["timeline"][:-1]
                    and state["timeline"].get("summary") == prior["timeline"].get("summary"))
        rows.append(("design_get", history, legal_history, None))
        held(True)
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "joint_preflight_home", "home"),
                                        "expect_document": _ctx_get(c, "joint_preflight_doc", "owned scene")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "joint_preflight_doc", "owned scene"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "joint_preflight_home", "home")}, _document_closed, None),
             ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True, "max_results": 2000},
              _retire_compare("joint_preflight_home_design", _retire_design_state, True), None)]
    return rows


def _failed_joint_assembly(name=None, failed=False, released=False):
    """Check the measured two-pin poses, grounding and retained or healthy rigid joint."""
    def check(p):
        poses, all_poses, joints = p.get("occurrences") or [], p.get("all_occurrences") or [], p.get("joints") or []
        expected_names = ["JointA:1", "JointB:1"]
        valid = (p.get("units") == "mm" and p.get("occurrence_count") == 2
                 and p.get("all_occurrence_count") == 2 and len(poses) == len(all_poses) == 2
                 and p.get("occurrences_truncated") is False
                 and p.get("all_occurrences_truncated") is False and p.get("joints_truncated") is False
                 and p.get("joint_count") == len(joints) == (1 if name else 0)
                 and p.get("is_healthy") is (not failed)
                 and p.get("broken_joints") == ([name] if failed else [])
                 and p.get("broken_relations") == [] and p.get("unresolved_references") == [])
        for rows in (poses, all_poses):
            valid = valid and [r.get("name") for r in rows] == expected_names
            for i, row in enumerate(rows):
                x = 0 if i == 0 or name == "FreeGeometry" else 20
                valid = (valid and row.get("body_count") == 1 and row.get("grounded") is False
                         and row.get("ground_to_parent") is (i == 0 or not released)
                         and row.get("origin") == [x, 0, 0] and row.get("bbox_center") == [x, 0, 5]
                         and row.get("bbox_size") == [4, 4, 10]
                         and row.get("x_axis") == [1, 0, 0] and row.get("y_axis") == [0, 1, 0]
                         and row.get("z_axis") == [0, 0, 1] and row.get("joints") == ([name] if name else []))
        valid = valid and [r.get("full_path") for r in all_poses] == expected_names
        if name and len(joints) == 1:
            joint = joints[0]
            valid = (valid and joint.get("name") == name and joint.get("type") == "rigid"
                     and joint.get("dof") == 0 and joint.get("healthy") is (not failed)
                     and joint.get("occurrence_one") == expected_names[0]
                     and joint.get("occurrence_two") == expected_names[1])
        return _measured("two-pin joint health, wiring and independent placed geometry", p, valid)
    return check


def _failed_joint_history(name, failed=False):
    """Check a retained failed joint or healthy control after the complete original history."""
    def check(p):
        state, before = _retire_design_state(p), _RECALL.get("joint_failure_design")
        tl = state["timeline"] if state else {}
        old = before["timeline"] if before else {}
        rows, prior = tl.get("timeline") or [], old.get("timeline") or []
        summary = tl.get("summary") or {}
        exceptions = summary.get("exceptions")
        valid = (state is not None and before is not None and len(rows) == len(prior) + 1
                 and rows[:-1] == prior and rows[-1].get("name") == name
                 and rows[-1].get("type") == "Joint"
                 and rows[-1].get("health", "healthy") == ("warning" if failed else "healthy")
                 and summary.get("states") == ({"healthy": len(prior), "warning": 1}
                                               if failed else {"healthy": len(rows)})
                 and isinstance(exceptions, list) and len(exceptions) == (1 if failed else 0))
        if failed and exceptions:
            valid = (valid and exceptions[0].get("name") == name
                     and exceptions[0].get("health") == "warning" and exceptions[0].get("index") == len(prior))
        return _measured("retained joint history and prior features", tl, valid)
    return check


def _joint_failure_rows():
    """Exercise retained compute failure, the advertised cleanup and a released-part rigid control."""
    rows = [("doc_get", {}, _home_document, ("jf_story", _home_address)),
            ("doc_new", {}, _new_document, None),
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("doc_get", {}, _home_document, ("jf_doc", _home_address))]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, a=args: dict(a), check, save))
    for name, x in (("JointA", 0), ("JointB", 20)):
        write("design_activate_component", {"occurrence": "root"})
        write("model_create_component", {"name": name, "activate": True, "x": x}, _made_component)
        write("sketch_create", {"name": "Pin" + name[-1], "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": "Pin" + name[-1],
                                    "geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 2}]})
        write("model_extrude", {"sketch_name": "Pin" + name[-1], "distance": 10}, _extruded)
    write("design_activate_component", {"occurrence": "root"})
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True,
                       "focus": ["JointA:1", "JointB:1"]})
    for name in ("JointA:1", "JointB:1"):
        write("assembly_ground", {"occurrence": name, "ground_to_parent": True}, _grounded)
    assembly = {"include": ["poses", "all_occurrences"], "units": "mm", "max_joints": 100,
                "max_occurrences": 100, "max_all_occurrences": 100}
    history = {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
               "max_depth": 10, "max_results": 2000}
    rows += [("assembly_get", assembly, _failed_joint_assembly(), None),
             ("design_get", history, _retire_compare("joint_failure_design", _retire_design_state, False), None)]
    for tool, name in (("joint_at_geometry", "LockedGeometry"), ("joint_create", "LockedRegular")):
        if tool == "joint_at_geometry":
            for owner, key in (("JointA:1", "jf_a"), ("JointB:1", "jf_b")):
                rows.append(("find_geometry", lambda c, o=owner: {"target": o, "kind": "cylinder_face",
                                                                  "max_results": 5}, "ok", _fg(key)))
            rows.append((tool, lambda c: {"handle_one": _ctx_get(c, "jf_a", "pin A"),
                                         "handle_two": _ctx_get(c, "jf_b", "pin B"),
                                         "motion": "rigid", "name": "LockedGeometry"},
                         _refused("LockedGeometry", "FAILED TO COMPUTE", "REMAINS",
                                  "design_delete_feature(feature='LockedGeometry')"), None))
        else:
            write(tool, {"occurrence_one": "JointA:1:origin", "occurrence_two": "JointB:1:origin",
                         "joint_type": "rigid", "name": name},
                  _refused(name, "FAILED to compute", "design_delete_feature(feature='LockedRegular')"))
        rows += [("assembly_get", assembly, _failed_joint_assembly(name, True), None),
                 ("design_get", history, _failed_joint_history(name, True), None)]
        write("design_delete_feature", {"feature": name})
        rows += [("assembly_get", assembly, _failed_joint_assembly(), None),
                 ("design_get", history, _retire_compare("joint_failure_design", _retire_design_state, True), None)]
    write("assembly_ground", {"occurrence": "JointB:1", "ground_to_parent": False},
          lambda p: _measured("pin B released", p, p.get("isGroundToParent") is False))
    rows.append(("assembly_get", assembly, _failed_joint_assembly(released=True), None))
    for owner, key in (("JointA:1", "jf_a"), ("JointB:1", "jf_b")):
        rows.append(("find_geometry", lambda c, o=owner: {"target": o, "kind": "cylinder_face", "max_results": 5},
                     "ok", _fg(key)))
    rows.append(("joint_at_geometry", lambda c: {"handle_one": _ctx_get(c, "jf_a", "pin A"),
                                                "handle_two": _ctx_get(c, "jf_b", "pin B"),
                                                "motion": "rigid", "name": "FreeGeometry"},
                 lambda p: _measured("released rigid joint computed", p, p.get("jointed") is True
                                     and p.get("healthy") is True and p.get("health_state") == "healthy"), None))
    rows += [("assembly_get", assembly, _failed_joint_assembly("FreeGeometry", released=True), None),
             ("design_get", history, _failed_joint_history("FreeGeometry"), None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "jf_story", "story"),
                                         "expect_document": _ctx_get(c, "jf_doc", "joint scratch")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "jf_doc", "joint scratch"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "jf_story", "story")}, _document_closed, None)]
    return rows


_CROSSINDEX_SETUP = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    root = adsk.fusion.Design.cast(app.activeProduct).rootComponent
    first = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    first.component.name = 'ReusedParent'
    child = first.component.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    child.component.name = 'Leaf'
    sketch = child.component.sketches.add(child.component.xYConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0,0,0), adsk.core.Point3D.create(.4,.4,0))
    inp = child.component.features.extrudeFeatures.createInput(sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByString('4 mm')), adsk.fusion.ExtentDirections.PositiveExtentDirection)
    feature = child.component.features.extrudeFeatures.add(inp)
    assert feature.bodies.count == 1
    matrix = adsk.core.Matrix3D.create()
    matrix.translation = adsk.core.Vector3D.create(4,0,0)
    second = root.occurrences.addExistingComponent(first.component, matrix)
    matrix = adsk.core.Matrix3D.create()
    matrix.translation = adsk.core.Vector3D.create(8,0,0)
    anchor = root.occurrences.addNewComponent(matrix)
    anchor.component.name = 'Anchor'
    children = [o for o in root.allOccurrences if o.component.name == 'Leaf']
    assert len(children) == 2
    print(json.dumps({'child_paths':[o.fullPathName for o in children], 'child_names':[o.name for o in children],
                      'parent_paths':[first.fullPathName,second.fullPathName], 'anchor_path':anchor.fullPathName}))
"""


_CROSSINDEX_NATIVE = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    def point(p): return [p.x*10,p.y*10,p.z*10]
    def body(b): return {'name':b.name, 'volume_cm3':b.volume, 'faces':b.faces.count,
                         'bbox_mm':[point(b.boundingBox.minPoint),point(b.boundingBox.maxPoint)],
                         'vertices_mm':sorted(point(v.geometry) for v in b.vertices)}
    print(json.dumps({'bodies':[body(b) for b in root.bRepBodies],
                      'placements':[{'path':o.fullPathName, 'name':o.name, 'matrix':o.transform2.asArray(),
                                     'component_body_count':o.component.bRepBodies.count,
                                     'component_bodies':[body(b) for b in o.component.bRepBodies]} for o in root.allOccurrences],
                      'joints':[{'name':j.name, 'paths':[j.occurrenceOne.fullPathName,j.occurrenceTwo.fullPathName],
                                 'health':int(j.timelineObject.healthState)} for j in root.asBuiltJoints],
                      'timeline':[{'name':t.name, 'health':int(t.healthState), 'type':t.entity.objectType} for t in design.timeline],
                      'marker':design.timeline.markerPosition}))
"""


def _crossindex_native_state(p):
    """Return the complete readable native geometry, placements, endpoints and history."""
    placements, bodies, joints, history = (p.get(k) for k in ("placements", "bodies", "joints", "timeline"))
    paths = {"ReusedParent:1", "ReusedParent:2", "ReusedParent:1+Leaf:1", "ReusedParent:2+Leaf:1", "Anchor:1"}
    def finite(values, count):
        return isinstance(values, list) and len(values) == count and all(_num(v) and math.isfinite(v) for v in values)
    def cube(row):
        bounds, vertices = row.get("bbox_mm"), row.get("vertices_mm")
        return (bool(row.get("name")) and _num(row.get("volume_cm3")) and math.isfinite(row["volume_cm3"])
                and row["volume_cm3"] > 0 and row.get("faces") == 6
                and isinstance(bounds, list) and len(bounds) == 2 and all(finite(v, 3) for v in bounds)
                and isinstance(vertices, list) and len(vertices) == 8 and all(finite(v, 3) for v in vertices))
    if (not isinstance(placements, list) or len(placements) != 5 or {r.get("path") for r in placements} != paths
            or not isinstance(bodies, list) or len(bodies) != 1 or not all(cube(b) for b in bodies)
            or not isinstance(joints, list) or len(joints) > 1 or not isinstance(history, list)
            or p.get("marker") != len(history) or len(history) not in (8, 9)
            or any(not r.get("name") or not r.get("type") or r.get("health") != 0 for r in history)):
        return None
    for row in placements:
        local = row.get("component_bodies")
        count = 1 if "+Leaf:1" in row["path"] else 0
        if (not finite(row.get("matrix"), 16) or not isinstance(local, list)
                or row.get("component_body_count") != len(local) or len(local) != count
                or not all(cube(b) for b in local)):
            return None
    if any(j.get("name") != "OnlyFirst" or j.get("health") != 0
           or j.get("paths") != ["ReusedParent:1+Leaf:1", "Anchor:1"] for j in joints):
        return None
    return {k: p[k] for k in ("bodies", "placements", "joints", "timeline", "marker")}


def _crossindex_native_read(stage):
    """Check native read nonmutation and exact restoration after typed joint retirement."""
    def check(p):
        now = _crossindex_native_state(p)
        before, joint = _RECALL.get("crossindex_before"), _RECALL.get("crossindex_joint")
        valid = now is not None
        if stage == "before":
            valid = valid and now["joints"] == [] and len(now["timeline"]) == 8
        elif stage == "joint":
            valid = (valid and before is not None and len(now["joints"]) == 1
                     and now["bodies"] == before["bodies"] and now["placements"] == before["placements"]
                     and now["timeline"][:-1] == before["timeline"]
                     and now["timeline"][-1]["name"] == "OnlyFirst"
                     and now["timeline"][-1]["type"] == "adsk::fusion::AsBuiltJoint")
        else:
            valid = valid and now == (before if stage == "restored" else joint)
        if valid and stage in ("before", "joint"):
            _RECALL["crossindex_" + stage] = now
        return _measured("native placed membership and unchanged geometry/history " + stage, now, valid)
    return check


def _crossindex_disclosure(joined=False, quiet=False, repeat=False):
    """Check exact placed membership against native endpoints while preserving all public poses."""
    def check(p):
        rows, top, joints = p.get("all_occurrences") or [], p.get("occurrences") or [], p.get("joints")
        native = _RECALL.get("crossindex_joint" if joined else "crossindex_before")
        paths = [r["path"] for r in native["placements"]] if native else []
        endpoints = native["joints"][0]["paths"] if joined and native and native["joints"] else []
        valid = (native is not None and p.get("units") == "mm" and p.get("is_healthy") is True
                 and p.get("all_occurrence_count") == len(rows) == 5 and p.get("occurrence_count") == len(top) == 3
                 and p.get("all_occurrences_truncated") is False and p.get("occurrences_truncated") is False
                 and p.get("joints_truncated") is False and p.get("joint_count") == int(joined)
                 and [r.get("full_path") for r in rows] == paths and p.get("root_bodies") == ["Body1"])
        for group in (rows, top):
            for row in group:
                path = row.get("full_path", row.get("name"))
                valid = (valid and type(row.get("grounded")) is bool and type(row.get("ground_to_parent")) is bool
                         and type(row.get("body_count")) is int
                         and all(isinstance(row.get(k), list) and len(row[k]) == 3
                                 and all(_num(v) and math.isfinite(v) for v in row[k])
                                 for k in ("origin", "x_axis", "y_axis", "z_axis")))
                if path != "Anchor:1":
                    valid = (valid and all(isinstance(row.get(k), list) and len(row[k]) == 3
                                           and all(_num(v) and math.isfinite(v) for v in row[k])
                                           for k in ("bbox_center", "bbox_size")))
                valid = valid and (("joints" not in row) if quiet else
                                  row.get("joints") == (["OnlyFirst"] if path in endpoints else []))
        if quiet:
            valid = valid and joints is None
        elif joined:
            valid = (valid and isinstance(joints, list) and len(joints) == 1
                     and joints[0].get("name") == "OnlyFirst" and joints[0].get("healthy") is True
                     and joints[0].get("as_built") is True and joints[0].get("occurrence_one") == "Leaf:1"
                     and joints[0].get("occurrence_one_path") == endpoints[0]
                     and joints[0].get("occurrence_two_path") == endpoints[1])
        else:
            valid = valid and joints == []
        poses = [[{k: v for k, v in r.items() if k != "joints"} for r in group] for group in (rows, top)]
        prior = _RECALL.get("crossindex_poses")
        if valid and prior is None:
            _RECALL["crossindex_poses"] = poses
        else:
            valid = valid and prior is not None and poses == prior
        if repeat:
            valid = valid and p == _RECALL.get("crossindex_public")
        elif joined and not quiet and valid:
            _RECALL["crossindex_public"] = p
        return _measured("public cross-index agrees with native placed endpoints; all poses held", p, valid)
    return check


_SUB_JOINT_SETUP = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    root = adsk.fusion.Design.cast(app.activeProduct).rootComponent
    def at(x_cm, y_cm):
        m = adsk.core.Matrix3D.create()
        m.translation = adsk.core.Vector3D.create(x_cm, y_cm, 0)
        return m
    sub = root.occurrences.addNewComponent(at(0.0, 6.0))
    sc = sub.component
    sc.name = 'PSub'
    def child(name, x_cm):
        occ = sc.occurrences.addNewComponent(at(x_cm, 0.0))
        comp = occ.component
        comp.name = name
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0, 0, 0), adsk.core.Point3D.create(.4, .4, 0))
        inp = comp.features.extrudeFeatures.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        inp.setDistanceExtent(False, adsk.core.ValueInput.createByString('4 mm'))
        comp.features.extrudeFeatures.add(inp)
        jo = comp.jointOrigins.add(comp.jointOrigins.createInput(adsk.fusion.JointGeometry.createByPoint(comp.originConstructionPoint)))
        jo.name = name + 'Datum'
        return occ, jo
    a, ja = child('PChildA', 0.0)
    b, jb = child('PChildB', 1.0)
    ji = sc.joints.createInput(ja.createForAssemblyContext(a), jb.createForAssemblyContext(b))
    ji.setAsRigidJointMotion()
    inner = sc.joints.add(ji)
    inner.name = 'Inner'
    second = root.occurrences.addExistingComponent(sc, at(10.0, 6.0))
    print(json.dumps({'joint': inner.name, 'placements': [sub.fullPathName, second.fullPathName]}))
"""

# Per placement of PSub, the halves Inner reads in that placement's context, plus the history.
_SUB_JOINT_NATIVE = """import adsk.core, adsk.fusion, json
def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    root = design.rootComponent
    sub = [c for c in design.allComponents if c.name == 'PSub'][0]
    inner = sub.joints.itemByName('Inner')
    halves = {}
    for p in root.allOccurrencesByComponent(sub):
        px = inner.createForAssemblyContext(p)
        halves[p.fullPathName] = [px.occurrenceOne.fullPathName, px.occurrenceTwo.fullPathName]
    print(json.dumps({'halves': halves, 'timeline_count': design.timeline.count,
                      'marker': design.timeline.markerPosition}))
"""


def _sub_joint_native(after):
    """Each PSub placement's own Inner halves, natively; the second read must equal the first."""
    def check(p):
        halves = p.get("halves") or {}
        valid = (sorted(halves) == ["PSub:1", "PSub:2"]
                 and all(v == [k + "+PChildA:1", k + "+PChildB:1"] for k, v in halves.items())
                 and p.get("marker") == p.get("timeline_count"))
        if after:
            valid = valid and p == _RECALL.get("sub_joint_native")
        elif valid:
            _RECALL["sub_joint_native"] = p
        return _measured("Inner's halves in each PSub placement", p, valid)
    return check


def _sub_joint_disclosure(p):
    """Inner is credited on all four placed child rows, and both placements' datums name it."""
    native = (_RECALL.get("sub_joint_native") or {}).get("halves") or {}
    paths = {path for pair in native.values() for path in pair}
    rows = {r.get("full_path"): r for r in p.get("all_occurrences") or []}
    inner = next((j for j in p.get("joints") or [] if j.get("name") == "Inner"), {})
    datums = {r.get("qualified_name"): r.get("consumed_by") for r in p.get("joint_origins") or []}
    placed = {r.get("placement"): [r.get("occurrence_one_path"), r.get("occurrence_two_path")]
              for r in inner.get("placements") or []}
    valid = (len(paths) == 4 and all((rows.get(path) or {}).get("joints") == ["Inner"] for path in paths)
             and all((rows.get(k) or {}).get("joints") == [] for k in ("PSub:1", "PSub:2"))
             and p.get("all_occurrences_truncated") is False and p.get("joint_origins_truncated") is False
             and inner.get("owner_component") == "PSub" and placed == native
             and all(datums.get(path + ":" + path.split("+")[-1].split(":")[0] + "Datum") == ["Inner"]
                     for path in paths))
    return _measured("sub-assembly joint on every placement of its owner", {"rows": {
        k: (rows.get(k) or {}).get("joints") for k in sorted(paths)}, "placements": placed,
        "datums": datums}, valid)


def _crossindex_rows():
    """Exercise the measured reused-parent cross-index with independent native state controls."""
    rows = [("doc_get", {}, _home_document, ("ci_story", _home_address)),
            ("doc_new", {}, _new_document, None),
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("doc_get", {}, _home_document, ("ci_doc", _home_address))]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, a=args: dict(a), check, save))
    write("sketch_create", {"name": "Witness", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "Witness", "units": "mm", "geometry": [
        {"kind": "rectangle", "x1": 100, "y1": 0, "x2": 120, "y2": 20}]})
    write("model_extrude", {"sketch_name": "Witness", "distance": 20, "units": "mm"}, _extruded)
    write("sys_execute_script", {"script": _CROSSINDEX_SETUP, "read_only": False},
          lambda p: _measured("controlled reused-parent fixture paths", p,
                              p.get("child_paths") == ["ReusedParent:1+Leaf:1", "ReusedParent:2+Leaf:1"]
                              and p.get("child_names") == ["Leaf:1", "Leaf:1"] and p.get("anchor_path") == "Anchor:1"),
          ("ci_setup", lambda p: p))
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True,
                       "focus": ["ReusedParent:1", "ReusedParent:2", "Anchor:1"]})
    def native(stage):
        write("sys_execute_script", {"script": _CROSSINDEX_NATIVE, "read_only": True}, _crossindex_native_read(stage))
    assembly = {"include": ["all_occurrences", "poses"], "units": "mm", "max_joints": 100,
                "max_occurrences": 100, "max_all_occurrences": 100}
    native("before")
    rows.append(("assembly_get", assembly, _crossindex_disclosure(), None))
    rows.append(("joint_create_as_built", lambda c: {
        "occurrence_one": _ctx_get(c, "ci_setup", "native fixture paths")["child_paths"][0],
        "occurrence_two": _ctx_get(c, "ci_setup", "native fixture paths")["anchor_path"],
        "joint_type": "rigid", "name": "OnlyFirst"}, _as_built, ("ci_joint", lambda p: p["joint"])))
    native("joint")
    rows += [("assembly_get", assembly, _crossindex_disclosure(True), None),
             ("assembly_get", assembly, _crossindex_disclosure(True, repeat=True), None),
             ("assembly_get", dict(assembly, include_joints=False), _crossindex_disclosure(True, quiet=True), None)]
    native("repeat")
    rows.append(("design_delete_feature", lambda c: {"feature": _ctx_get(c, "ci_joint", "as-built joint name")}, "ok", None))
    native("restored")
    rows.append(("assembly_get", assembly, _crossindex_disclosure(), None))
    # REVIEW-1004-ASSEMBLY-JOINT-PATHS-1: a joint owned by a twice-placed sub-assembly.
    write("sys_execute_script", {"script": _SUB_JOINT_SETUP, "read_only": False},
          lambda p: p.get("joint") == "Inner" and p.get("placements") == ["PSub:1", "PSub:2"])
    write("sys_execute_script", {"script": _SUB_JOINT_NATIVE, "read_only": True}, _sub_joint_native(False))
    write("assembly_get", {"include": ["all_occurrences", "joint_origins"], "units": "mm", "max_joints": 100,
                           "max_all_occurrences": 100, "max_joint_origins": 100}, _sub_joint_disclosure)
    write("sys_execute_script", {"script": _SUB_JOINT_NATIVE, "read_only": True}, _sub_joint_native(True))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "ci_story", "story"),
                                         "expect_document": _ctx_get(c, "ci_doc", "cross-index scratch")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "ci_doc", "cross-index scratch"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "ci_story", "story")}, _document_closed, None)]
    return rows


_REUSED_ORIGIN_SETUP = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    root = adsk.fusion.Design.cast(app.activeProduct).rootComponent
    def at(x_cm):
        m = adsk.core.Matrix3D.create()
        m.translation = adsk.core.Vector3D.create(x_cm, 0, 0)
        return m
    p1 = root.occurrences.addNewComponent(at(0.0))
    pc = p1.component
    pc.name = 'ReusedParent'
    lc = pc.occurrences.addNewComponent(at(0.0)).component
    lc.name = 'Leaf'
    sk = lc.sketches.add(lc.xYConstructionPlane)
    sk.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0, 0, 0), adsk.core.Point3D.create(.4, .4, 0))
    inp = lc.features.extrudeFeatures.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString('4 mm'))
    lc.features.extrudeFeatures.add(inp)
    datum = lc.jointOrigins.add(lc.jointOrigins.createInput(adsk.fusion.JointGeometry.createByPoint(lc.originConstructionPoint)))
    datum.name = 'Datum'
    p2 = root.occurrences.addExistingComponent(pc, at(4.0))
    leaf2 = p2.childOccurrences.item(0)
    ain = root.jointOrigins.createInput(adsk.fusion.JointGeometry.createByPoint(root.originConstructionPoint))
    ain.offsetX = adsk.core.ValueInput.createByString('40 mm')
    anchor = root.jointOrigins.add(ain)
    anchor.name = 'RootAnchor'
    ji = root.joints.createInput(datum.createForAssemblyContext(leaf2), anchor)
    ji.setAsRigidJointMotion()
    j = root.joints.add(ji)
    j.name = 'SecondOnly'
    print(json.dumps({'joint': j.name, 'one': j.occurrenceOne.fullPathName}))
"""


def _reused_origin_consumers(p):
    """consumed_by credits only the placement the joint stores, against the native half."""
    rows = {r.get("qualified_name"): r.get("consumed_by") for r in p.get("joint_origins") or []}
    return _measured("consumer attributed to the stored placement", rows,
                     rows.get("ReusedParent:2+Leaf:1:Datum") == ["SecondOnly"]
                     and rows.get("ReusedParent:1+Leaf:1:Datum") == []
                     and rows.get("RootAnchor") == ["SecondOnly"])


def _reused_origin_rows():
    """A root joint on one placement of a twice-placed leaf's origin, read through joint_origins."""
    return [("doc_get", {}, _home_document, ("ro_story", _home_address)),
            ("doc_new", {}, _new_document, None),
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("doc_get", {}, _home_document, ("ro_doc", _home_address)),
            ("sys_execute_script", {"script": _REUSED_ORIGIN_SETUP, "read_only": False},
             lambda p: p.get("joint") == "SecondOnly" and p.get("one") == "ReusedParent:2+Leaf:1", None),
            ("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True,
                          "focus": ["ReusedParent:1", "ReusedParent:2"]}, "ok", None),
            ("assembly_get", {"include": ["joint_origins"], "units": "mm", "max_joint_origins": 100},
             _reused_origin_consumers, None),
            ("doc_activate", lambda c: {"name": _ctx_get(c, "ro_story", "story"),
                                        "expect_document": _ctx_get(c, "ro_doc", "reused-origin scratch")}, "ok", None),
            ("doc_close", lambda c: {"name": _ctx_get(c, "ro_doc", "reused-origin scratch"), "save_changes": False,
                                     "expect_document": _ctx_get(c, "ro_story", "story")}, _document_closed, None)]


_ORIGIN_CONSUMER_NATIVE = """import adsk.core, adsk.fusion, json, sys
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    modules = [m for m in sys.modules.values() if str(getattr(m, '__file__', '')).replace('\\\\', '/').endswith('/commands/mcpServer/tools/_common.py')]
    assert len(modules) == 1
    common = modules[0]
    def point(p): return [p.x*10,p.y*10,p.z*10]
    def origin(jo, path, proxy=None):
        return {'name':jo.name, 'component':jo.parentComponent.name, 'path':path,
                'identity':common.native_identity(jo), 'owner_identity':common.native_identity(jo.parentComponent),
                'owner_is_root':common.same_component(jo.parentComponent,root),
                'context':jo.assemblyContext.fullPathName if jo.assemblyContext else None,
                'proxy_identity':common.native_identity(proxy) if proxy else None}
    origins = [origin(jo,None) for jo in root.jointOrigins]
    origins += [origin(jo,o.fullPathName,jo.createForAssemblyContext(o)) for o in root.occurrences for jo in o.component.jointOrigins]
    print(json.dumps({'bodies':[{'name':b.name, 'volume_cm3':b.volume, 'faces':b.faces.count,
                               'bbox_mm':[point(b.boundingBox.minPoint),point(b.boundingBox.maxPoint)],
                               'vertices_mm':sorted(point(v.geometry) for v in b.vertices)} for b in root.bRepBodies],
                      'origins':origins,
                      'placements':[{'path':o.fullPathName, 'matrix':o.transform2.asArray()} for o in root.allOccurrences],
                      'joints':[{'name':j.name, 'health':int(j.healthState),
                                 'inputs':[origin(j.geometryOrOriginOne,j.occurrenceOne.fullPathName if j.occurrenceOne else None),
                                           origin(j.geometryOrOriginTwo,j.occurrenceTwo.fullPathName if j.occurrenceTwo else None)]} for j in root.joints],
                      'timeline':[{'name':t.name, 'type':t.entity.objectType, 'health':int(t.healthState)} for t in design.timeline],
                      'marker':design.timeline.markerPosition}))
"""


def _origin_consumer_native_state(p):
    """Return the measured complete distinct-origin scene or None for an unread discriminator."""
    bodies, origins, placements, joints, history = (p.get(k) for k in
                                                   ("bodies", "origins", "placements", "joints", "timeline"))
    def finite(values, count):
        return isinstance(values, list) and len(values) == count and all(_num(v) and math.isfinite(v) for v in values)
    def identity(value):
        return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and bool(value[0])
    if (not isinstance(bodies, list) or len(bodies) != 1
            or not isinstance(origins, list) or len(origins) != 3
            or not isinstance(placements, list) or len(placements) != 2
            or {r.get("path") for r in placements} != {"OriginA:1", "OriginB:1"}
            or any(not finite(r.get("matrix"), 16) for r in placements)
            or not isinstance(joints, list) or len(joints) > 1
            or not isinstance(history, list) or len(history) not in (7, 8)
            or p.get("marker") != len(history)
            or any(not r.get("name") or not r.get("type") or r.get("health") != 0 for r in history)):
        return None
    body = bodies[0]
    if (body.get("name") != "Body1" or not _near(body.get("volume_cm3"), 8, 1e-8) or body.get("faces") != 6
            or body.get("bbox_mm") != [[100, 0, 0], [120, 20, 20]]
            or not isinstance(body.get("vertices_mm"), list) or len(body["vertices_mm"]) != 8
            or any(not finite(v, 3) for v in body["vertices_mm"])):
        return None
    if ({(r.get("path"), r.get("name")) for r in origins}
            != {(None, "RootAnchor"), ("OriginA:1", "Datum"), ("OriginB:1", "Datum")}
            or any(not identity(r.get("identity")) or not identity(r.get("owner_identity"))
                   or r.get("context") is not None or type(r.get("owner_is_root")) is not bool
                   or r["owner_is_root"] != (r["path"] is None)
                   or (r["path"] is not None and r.get("proxy_identity") != r["identity"])
                   for r in origins)
            or len({tuple(r["identity"]) for r in origins}) != 3
            or len({tuple(r["owner_identity"]) for r in origins}) != 3):
        return None
    by_path = {r["path"]: r for r in origins}
    for joint in joints:
        inputs = joint.get("inputs")
        if (joint.get("name") != "AOnly" or joint.get("health") != 0
                or not isinstance(inputs, list) or len(inputs) != 2):
            return None
        for row, path in zip(inputs, ("OriginA:1", None)):
            expected = by_path[path]
            if any(row.get(k) != expected[k] for k in
                   ("name", "component", "path", "identity", "owner_identity", "owner_is_root", "context")):
                return None
    return {k: p[k] for k in ("bodies", "origins", "placements", "joints", "timeline", "marker")}


def _origin_consumer_native_read(stage):
    """Check native identity/effect controls, read nonmutation and exact typed retirement."""
    def check(p):
        now = _origin_consumer_native_state(p)
        before, joined = _RECALL.get("origin_consumers_before"), _RECALL.get("origin_consumers_joint")
        valid = now is not None
        if stage == "before":
            valid = valid and now["joints"] == [] and len(now["timeline"]) == 7
        elif stage == "joint":
            valid = (valid and before is not None and len(now["joints"]) == 1
                     and all(now[k] == before[k] for k in ("bodies", "origins", "placements"))
                     and now["timeline"][:-1] == before["timeline"]
                     and now["timeline"][-1] == {"name": "AOnly", "type": "adsk::fusion::Joint", "health": 0})
        else:
            valid = valid and now == (before if stage == "restored" else joined)
        if valid and stage in ("before", "joint"):
            _RECALL["origin_consumers_" + stage] = now
        return _measured("native origin identities and unchanged geometry/history " + stage, now, valid)
    return check


def _origin_consumer_disclosure(joined=False, repeat=False, quiet=False):
    """Check public consumers against actual native origin and joint-half identities."""
    def check(p):
        native = _RECALL.get("origin_consumers_joint" if joined else "origin_consumers_before")
        origins, occurrences = p.get("joint_origins"), p.get("occurrences")
        valid = (native is not None and p.get("units") == "mm" and p.get("is_healthy") is True
                 and p.get("joint_count") == int(joined) and p.get("joint_origin_count") == 3
                 and p.get("joint_origins_truncated") is False and p.get("occurrences_truncated") is False
                 and p.get("joints_truncated") is False and p.get("occurrence_count") == 2
                 and isinstance(origins, list) and len(origins) == 3
                 and isinstance(occurrences, list) and len(occurrences) == 2)
        expected = {}
        if native:
            inputs = native["joints"][0]["inputs"] if joined and native["joints"] else []
            for row in native["origins"]:
                name = (row["path"] + ":" if row["path"] else "") + row["name"]
                expected[name] = ["AOnly"] if any(row["identity"] == r["identity"] and row["path"] == r["path"] for r in inputs) else []
        valid = valid and {r.get("qualified_name"): r.get("consumed_by") for r in origins or []} == expected
        for row in origins or []:
            valid = (valid and isinstance(row.get("handle"), str) and bool(row["handle"])
                     and isinstance(row.get("world_position"), list) and len(row["world_position"]) == 3
                     and all(_num(v) and math.isfinite(v) for v in row["world_position"])
                     and all(isinstance((row.get("frame") or {}).get(k), list)
                             and len(row["frame"][k]) == 3 and all(_num(v) and math.isfinite(v) for v in row["frame"][k])
                             for k in ("x_axis", "y_axis", "z_axis")))
        poses = [{k: r.get(k) for k in ("name", "origin", "x_axis", "y_axis", "z_axis", "body_count")} for r in occurrences or []]
        valid = valid and {r["name"] for r in poses} == {"OriginA:1", "OriginB:1"}
        for row in poses:
            valid = (valid and row["body_count"] == 0 and all(isinstance(row[k], list) and len(row[k]) == 3
                     and all(_num(v) and math.isfinite(v) for v in row[k]) for k in ("origin", "x_axis", "y_axis", "z_axis")))
        prior = _RECALL.get("origin_consumers_poses")
        if valid and prior is None:
            _RECALL["origin_consumers_poses"] = poses
        else:
            valid = valid and prior is not None and poses == prior
        if quiet:
            valid = valid and p.get("joints") is None and all("joints" not in r for r in occurrences or [])
        else:
            joints = p.get("joints")
            valid = valid and isinstance(joints, list) and len(joints) == int(joined)
            if joined:
                valid = (valid and joints[0].get("healthy") is True and joints[0].get("name") == "AOnly"
                         and joints[0].get("occurrence_one_path") == "OriginA:1" and joints[0].get("occurrence_two_path") is None)
        if repeat:
            valid = valid and p == _RECALL.get("origin_consumers_public")
        elif joined and not quiet and valid:
            _RECALL["origin_consumers_public"] = p
        return _measured("public distinct-origin consumers match native identities; poses held", p, valid)
    return check


def _origin_consumer_rows():
    """Reproduce the measured same-name distinct-definition origins and proven root half."""
    rows = [("doc_get", {}, _home_document, ("oc_story", _home_address)),
            ("doc_new", {}, _new_document, None),
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("doc_get", {}, _home_document, ("oc_doc", _home_address))]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, a=args: dict(a), check, save))
    write("sketch_create", {"name": "Witness", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "Witness", "units": "mm", "geometry": [
        {"kind": "rectangle", "x1": 100, "y1": 0, "x2": 120, "y2": 20}]})
    write("model_extrude", {"sketch_name": "Witness", "distance": 20, "units": "mm", "operation": "new"}, _extruded)
    for name, x in (("OriginA", 0), ("OriginB", 40)):
        write("model_create_component", {"name": name, "x": x, "units": "mm", "activate": False}, _made_component_inactive)
        write("joint_create_origin", {"anchor": "coordinates", "target": "origin", "component": name + ":1",
                                      "name": "Datum", "units": "mm"})
    write("joint_create_origin", {"anchor": "coordinates", "target": "origin", "name": "RootAnchor", "units": "mm"})
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True, "focus": ["Witness"]})
    def native(stage):
        write("sys_execute_script", {"script": _ORIGIN_CONSUMER_NATIVE, "read_only": True}, _origin_consumer_native_read(stage))
    assembly = {"include": ["joint_origins", "poses"], "units": "mm"}
    native("before")
    rows.append(("assembly_get", assembly, _origin_consumer_disclosure(), None))
    write("joint_create", {"occurrence_one": "OriginA:1:Datum", "occurrence_two": "RootAnchor",
                           "joint_type": "rigid", "name": "AOnly", "units": "mm"}, _jointed("AOnly"),
          ("oc_joint", lambda p: p["joint_name"]))
    native("joint")
    rows += [("assembly_get", assembly, _origin_consumer_disclosure(True), None),
             ("assembly_get", assembly, _origin_consumer_disclosure(True, repeat=True), None),
             ("assembly_get", dict(assembly, include_joints=False), _origin_consumer_disclosure(True, quiet=True), None)]
    native("repeat")
    rows.append(("design_delete_feature", lambda c: {"feature": _ctx_get(c, "oc_joint", "regular joint name")}, "ok", None))
    native("restored")
    rows += [("assembly_get", assembly, _origin_consumer_disclosure(), None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "oc_story", "story"),
                                         "expect_document": _ctx_get(c, "oc_doc", "origin scratch")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "oc_doc", "origin scratch"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "oc_story", "story")}, _document_closed, None)]
    return rows


def _constraint_names(p):
    """Return the complete assembly-constraint census by name, or None when the read is partial."""
    rows = (p.get("relations") or {}).get("constraints")
    if p.get("relations_truncated") is not False or not isinstance(rows, list):
        return None
    return sorted(str(r.get("name")) for r in rows)


def _selected_owner_state(p):
    """Return the complete four-part pose and relationship witness, or None when unread."""
    rows, relations = p.get("all_occurrences"), p.get("relations") or {}
    names = {"ClaimA:1", "ClaimB:1", "SelectedC:1", "SelectedD:1"}
    if (p.get("units") != "mm" or p.get("is_healthy") is not True
            or p.get("all_occurrence_count") != 4 or not isinstance(rows, list) or len(rows) != 4
            or {r.get("full_path") for r in rows} != names
            or p.get("occurrence_count") != 4 or len(p.get("occurrences") or []) != 4
            or any(p.get(k) is not False for k in ("all_occurrences_truncated", "occurrences_truncated",
                                                   "joints_truncated", "relations_truncated"))):
        return None
    for row in rows:
        if (row.get("body_count") != 1 or any(type(row.get(k)) is not bool
                                             for k in ("grounded", "ground_to_parent"))
                or any(not isinstance(row.get(k), list) or len(row[k]) != 3
                       or any(not _num(v) or not math.isfinite(v) for v in row[k])
                       for k in ("origin", "x_axis", "y_axis", "z_axis", "bbox_center", "bbox_size"))):
            return None
    for kind in ("rigid_groups", "motion_links", "constraints"):
        entries = relations.get(kind)
        if (not isinstance(entries, list) or (p.get("relation_counts") or {}).get(kind) != len(entries)
                or any(not r.get("name") or r.get("healthy") is not True
                       or type(r.get("suppressed")) is not bool for r in entries)):
            return None
    return {k: v for k, v in p.items() if k not in ("note", "active_document")}


def _selected_owner_landed(p):
    """Require the matched face constraint to move only D into the measured complementary seat."""
    now, before = _selected_owner_state(p), _RECALL.get("selected_owner_assembly")
    valid = now is not None and before is not None
    if valid:
        old = {r["full_path"]: r for r in before["all_occurrences"]}
        current = {r["full_path"]: r for r in now["all_occurrences"]}
        d = current["SelectedD:1"]
        constraints = now["relations"]["constraints"]
        valid = (len(constraints) == 1 and constraints[0].get("relationship_count") == 1
                 and constraints[0].get("suppressed") is False
                 and before["relations"]["constraints"] == []
                 and now["relations"]["rigid_groups"] == before["relations"]["rigid_groups"]
                 and now["relations"]["motion_links"] == before["relations"]["motion_links"]
                 and all(current[n] == old[n] for n in old if n != "SelectedD:1")
                 and old["SelectedD:1"]["origin"] == [40, 0, 0]
                 and d["origin"] == [20, 0, -10] and d["bbox_center"] == [22, 2, -5]
                 and {k: v for k, v in d.items() if k not in ("origin", "bbox_center")}
                 == {k: v for k, v in old["SelectedD:1"].items() if k not in ("origin", "bbox_center")})
    return _measured("matched C/D owners: D seated, A/B/C and all axes preserved", now, valid)


def _selected_owner_history(p):
    """Require one healthy constraint after the exact previous history prefix."""
    now, before = _retire_design_state(p), _RECALL.get("selected_owner_design")
    tl, old = (now or {}).get("timeline", {}), (before or {}).get("timeline", {})
    rows, prefix = tl.get("timeline") or [], old.get("timeline") or []
    return _measured("one healthy constraint after the preserved history", tl,
                     now is not None and before is not None and len(rows) == len(prefix) + 1
                     and rows[:-1] == prefix and rows[-1].get("type") == "AssemblyConstraint"
                     and rows[-1].get("health", "healthy") == "healthy"
                     and (tl.get("summary") or {}).get("states") == {"healthy": len(rows)}
                     and (tl.get("summary") or {}).get("exceptions") == [])


def _selected_owner_face(p, occurrence, normal):
    """Acquire the unique measured top or bottom face from a complete six-face box census."""
    matches = p.get("matches") or []
    chosen = [r for r in matches if r.get("normal") == [0, 0, normal]
              and r.get("occurrence") == occurrence and r.get("handle")]
    if p.get("match_count") != 6 or p.get("returned") != 6 or len(matches) != 6 or len(chosen) != 1:
        raise ValueError("the selected-owner box face census is incomplete or ambiguous")
    return chosen[0]["handle"]


def _selected_owner_script(handle=None, occurrence=None):
    """Return the measured owned-scratch selection setup, never a geometry mutation."""
    setup = "sel.clear()" if handle is None else (
        "d = adsk.fusion.Design.cast(app.activeProduct)\n"
        f"    face = adsk.fusion.BRepFace.cast(d.findEntityByToken({handle.split('|@', 1)[0]!r})[0])\n"
        f"    occ = d.rootComponent.occurrences.itemByName({occurrence!r})\n"
        "    if face.assemblyContext is None:\n"
        "        face = face.createForAssemblyContext(occ)\n"
        f"    assert face.assemblyContext.fullPathName == {occurrence!r}\n"
        "    assert sel.add(face) is True")
    return ("import adsk.core, adsk.fusion\nimport json\ndef run(context):\n"
            "    app = adsk.core.Application.get()\n"
            "    assert app.activeDocument.dataFile is None, 'owned unsaved scratch only'\n"
            "    sel = app.userInterface.activeSelections\n    " + setup + "\n"
            "    print(json.dumps({'count': sel.count, 'owners': "
            "[sel.item(i).entity.assemblyContext.fullPathName for i in range(sel.count)]}))\n")


def _selected_owner_rows():
    """Build the script-enabled selected-owner refusal and independent matched-control scene."""
    rows = [
        ("doc_get", {"max_results": 1000}, _home_document,
         ("selected_owner_story", _recall("selected_owner_story", _home_address))),
        ("doc_new", lambda c: {"expect_document": _ctx_get(c, "selected_owner_story", "story document")},
         _new_document, ("selected_owner_doc", lambda p: p["document_handle"])),
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ]
    for name, x in (("ClaimA", 0), ("ClaimB", 10), ("SelectedC", 20), ("SelectedD", 40)):
        rows += [
            ("model_create_component", lambda c, n=name, x=x: {"name": n, "x": x, "units": "mm", "activate": True},
             _made_component, None),
            ("sketch_create", lambda c, n=name: {"name": n + "Sketch", "plane": "xy"}, "ok", None),
            ("sketch_add_geometry", lambda c, n=name: {"sketch_name": n + "Sketch", "units": "mm",
             "geometry": [{"kind": "rectangle", "x1": 0, "y1": 0, "x2": 4, "y2": 4}]}, "ok", None),
            ("model_extrude", lambda c, n=name: {"sketch_name": n + "Sketch", "distance": 10,
                                               "units": "mm", "operation": "new"}, _extruded, None),
        ]
    rows += [
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
        ("assembly_ground", {"occurrence": "SelectedC:1", "ground_to_parent": True}, _grounded, None),
        ("assembly_ground", {"occurrence": "SelectedD:1", "ground_to_parent": False},
         lambda p: p.get("isGroundToParent") is False and p.get("occurrence") == "SelectedD:1", None),
        ("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True,
                      "focus": ["ClaimA:1", "ClaimB:1", "SelectedC:1", "SelectedD:1"]}, "ok", None),
        ("sys_execute_script", {"script": _selected_owner_script()}, lambda p: p.get("count") == 0, None),
    ]
    def select_pair(top):
        result = []
        for i, occurrence in enumerate(("SelectedC:1", "SelectedD:1"), 1):
            normal = (1 if top else -1) * (1 if i == 1 else -1)
            key = "selected_owner_face_" + str(i)
            result += [
                ("find_geometry", lambda c, o=occurrence: {"target": o, "kind": "planar_face", "units": "mm", "max_results": 20},
                 "ok", (key, lambda p, o=occurrence, z=normal: _selected_owner_face(p, o, z))),
                ("sys_execute_script", lambda c, k=key, o=occurrence: {"script": _selected_owner_script(_ctx_get(c, k, "selected face"), o)},
                 lambda p, n=i: p.get("count") == n and p.get("owners") == ["SelectedC:1", "SelectedD:1"][:n], None),
            ]
        return result
    parts = ["ClaimA:1", "ClaimB:1", "SelectedC:1", "SelectedD:1"]
    assembly = {"include": ["poses", "all_occurrences", "relations"], "units": "mm",
                "max_occurrences": 100, "max_all_occurrences": 100, "max_relations": 100, "max_joints": 100}
    rows += select_pair(True) + _retire_reads("selected_owner", parts, []) + [
        ("assembly_get", assembly, _retire_compare("selected_owner_assembly", _selected_owner_state, False), None),
        ("assembly_constrain", {"occurrence_one": "ClaimA:1", "occurrence_two": "ClaimB:1", "flipped": True},
         _refused("Selected entity 1", "SelectedC:1", "ClaimA:1", "occurrence_one first"), None),
    ] + _retire_reads("selected_owner", parts, [], after=True) + [
        ("assembly_get", assembly, _retire_compare("selected_owner_assembly", _selected_owner_state, True), None),
        ("sys_execute_script", {"script": _selected_owner_script()}, lambda p: p.get("count") == 0, None),
    ] + select_pair(False) + [
        ("assembly_constrain", {"occurrence_one": "SelectedC:1", "occurrence_two": "SelectedD:1", "flipped": True},
         lambda p: _constrained(p) and p.get("occurrences") == ["SelectedC:1", "SelectedD:1"]
         and p.get("relationship_count") == 1 and len(p.get("moved") or []) == 1
         and p["moved"][0].get("occurrence") == "SelectedD:1" and _near(p["moved"][0].get("distance_mm"), 22.361, .001), None),
        ("assembly_get", assembly, _selected_owner_landed, None),
        ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                        "max_depth": 10, "max_results": 2000}, _selected_owner_history, None),
        ("sys_execute_script", {"script": _selected_owner_script()}, lambda p: p.get("count") == 0, None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, "selected_owner_story", "story document"),
                                    "expect_document": _ctx_get(c, "selected_owner_doc", "selection scratch")}, "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "selected_owner_doc", "selection scratch"),
                                 "save_changes": False, "expect_document": _ctx_get(c, "selected_owner_story", "story document")},
         _document_closed, None),
    ]
    return rows


# The measured scratch-part recipe (lengths cross the API in cm): a 4 x 4 mm box, 10 mm tall unless
# given. `ground` None leaves Fusion's own ground-to-parent default.
_PART_RECIPE = """import adsk.core, adsk.fusion, json, math
def _part(parent, name, x_mm, y_mm, rot_deg=0.0, axis=None, height='10 mm', ground=None):
    m = adsk.core.Matrix3D.create()
    if rot_deg:
        m.setToRotation(math.radians(rot_deg), axis, adsk.core.Point3D.create(0, 0, 0))
    m.translation = adsk.core.Vector3D.create(x_mm / 10.0, y_mm / 10.0, 0)
    occ = parent.occurrences.addNewComponent(m)
    comp = occ.component
    comp.name = name
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0, 0, 0), adsk.core.Point3D.create(.4, .4, 0))
    inp = comp.features.extrudeFeatures.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString(height))
    comp.features.extrudeFeatures.add(inp)
    if ground is not None:
        occ.isGroundToParent = ground
    return occ
def _root():
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None, 'owned unsaved scratch only'
    return adsk.fusion.Design.cast(app.activeProduct).rootComponent
"""

# Every placed occurrence's world matrix and body boxes (mm), the constraint names and the history.
_PLACED_STATE = """import adsk.core, adsk.fusion, json
def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    root = design.rootComponent
    def box(b):
        bb = b.boundingBox
        return [[round(v * 10, 6) for v in (bb.minPoint.x, bb.minPoint.y, bb.minPoint.z)],
                [round(v * 10, 6) for v in (bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z)]]
    cons = root.assemblyConstraints
    print(json.dumps({'placements': {o.fullPathName: {'matrix': [round(c, 6) for c in o.transform2.asArray()],
                                                      'bodies': [box(o.bRepBodies.item(i)) for i in range(o.bRepBodies.count)]}
                                     for o in root.allOccurrences},
                      'constraints': [cons.item(i).name for i in range(cons.count)],
                      'timeline_count': design.timeline.count, 'marker': design.timeline.markerPosition}))
"""


def _placed(key, judge=None, what="placements held"):
    """The native placed state: parked under `key` when `judge` is None, else judge(before, now)."""
    def check(p):
        now = p if isinstance(p.get("placements"), dict) and p.get("marker") == p.get("timeline_count") else None
        before = _RECALL.get(key)
        if judge is None:
            valid = now is not None
            if valid:
                _RECALL[key] = now
        else:
            valid = now is not None and before is not None and judge(before, now)
        return _measured(what, {"before": before, "now": now}, valid)
    return check


def _all_but(before, now, moved):
    """Every placement except `moved` reads exactly as before, and no placement came or went."""
    return (set(now["placements"]) == set(before["placements"])
            and all(now["placements"][k] == v for k, v in before["placements"].items() if k not in moved))


def _scratch(tag, steps):
    """Open an owned scratch document, run `steps` there, then close it unsaved."""
    rows = [("doc_get", {}, _home_document, (tag + "_story", _home_address)),
            ("doc_new", {}, _new_document, None),
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("doc_get", {}, _home_document, (tag + "_doc", _home_address))]
    for tool, args, check, save in steps:
        rows.append((tool, args if callable(args) else (lambda c, a=args: dict(a)), check, save))
    return rows + [
        ("doc_activate", lambda c: {"name": _ctx_get(c, tag + "_story", "story"),
                                    "expect_document": _ctx_get(c, tag + "_doc", "scratch")}, "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, tag + "_doc", "scratch"), "save_changes": False,
                                 "expect_document": _ctx_get(c, tag + "_story", "story")}, _document_closed, None)]


_RIGID_EDIT_SETUP = _PART_RECIPE + """
def run(context):
    root = _root()
    assert root.occurrences.count == 0 and root.bRepBodies.count == 0
    for name, x in (('RgA', 0), ('RgB', 40), ('RgC', 80)):
        _part(root, name, x, -200)
    print(json.dumps({'paths': sorted(o.fullPathName for o in root.occurrences)}))
"""

_RIGID_EDIT_STATE = """import adsk.core, adsk.fusion, json
def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    assert adsk.core.Application.get().activeDocument.dataFile is None
    root, tl = design.rootComponent, design.timeline
    assert root.rigidGroups.count == 1
    g = root.rigidGroups.item(0)
    def read(f):
        try:
            return f()
        except Exception:
            return None
    print(json.dumps({'groups': root.rigidGroups.count,
        'members': read(lambda: sorted(o.fullPathName for o in g.occurrences)),
        'tokens': read(lambda: sorted(o.entityToken for o in g.occurrences)),
        'wanted_tokens': sorted(o.entityToken for o in root.occurrences if o.name in ('RgA:1', 'RgC:1')),
        'marker': tl.markerPosition, 'count': tl.count,
        'suppressed': read(lambda: g.isSuppressed),
        'health': read(lambda: int(g.timelineObject.healthState)),
        'rolled_back': read(lambda: g.timelineObject.isRolledBack)}))
"""


def _rigid_edit_rows():
    """Replace a group's members and check the marker, exact identities and healthy state."""
    group = lambda c: _ctx_get(c, "rg_edit", "edited group")
    edit = lambda c: {"kind": "rigid_group", "name": group(c), "action": "set_occurrences",
                      "occurrences": ["RgA:1", "RgC:1"]}
    def state(members):
        return lambda p: _measured("independent rigid group state", p,
            p.get("groups") == 1 and p.get("members") == members
            and p.get("marker") == p.get("count") == _RECALL.get("rg_edit_count")
            and p.get("suppressed") is False and p.get("health") == 0 and p.get("rolled_back") is False)
    return _scratch("rigid_edit", [
        ("sys_execute_script", {"script": _RIGID_EDIT_SETUP, "read_only": False},
         lambda p: p.get("paths") == ["RgA:1", "RgB:1", "RgC:1"], None),
        ("assembly_rigid_group", {"occurrences": ["RgA:1", "RgB:1"]}, _rigid_grouped(2),
         ("rg_edit", _recall("rg_edit", lambda p: p["assembly_rigid_group"]))),
        ("sketch_create", {"plane": "xy", "name": "RgLater"}, "ok", None),
        ("sys_execute_script", {"script": _RIGID_EDIT_STATE, "read_only": True},
         lambda p: p.get("members") == ["RgA:1", "RgB:1"] and p.get("marker") == p.get("count"),
         ("rg_edit_count", _recall("rg_edit_count", lambda p: p["count"]))),
        ("design_edit_timeline", lambda c: {"action": "roll", "feature": group(c), "to": "before"},
         lambda p: p.get("rolled") is True,
         ("rg_edit_parked", _recall("rg_edit_parked", lambda p: p["marker_position"]))),
        ("assembly_edit_relations", edit, _refused("set_occurrences starts with it at the end",
                  "design_edit_timeline(action='roll', to='end')"), None),
        ("sys_execute_script", {"script": """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    tl = adsk.fusion.Design.cast(app.activeProduct).timeline
    print(json.dumps({'marker': tl.markerPosition, 'count': tl.count}))
""", "read_only": True},
         lambda p: _measured("refusal preserves parked marker", p,
                             isinstance(p.get("marker"), int) and p["marker"] < p["count"]
                             and p["marker"] == _RECALL.get("rg_edit_parked")), None),
        ("design_edit_timeline", {"action": "roll", "to": "end"},
         lambda p: p.get("marker_position") == p.get("timeline_count"), None),
        ("sys_execute_script", {"script": _RIGID_EDIT_STATE, "read_only": True},
         state(["RgA:1", "RgB:1"]), None),
        ("assembly_edit_relations", edit,
         lambda p: _measured("member replacement reports its verified effect", p,
            p.get("changed") is True and p.get("members") == ["RgA:1", "RgC:1"]
            and p.get("members_before") == ["RgA:1", "RgB:1"] and p.get("member_count") == 2
            and p.get("is_suppressed") is False and p.get("health") == "healthy"
            and p.get("marker_position") == p.get("timeline_count") == _RECALL.get("rg_edit_count")), None),
        ("sys_execute_script", {"script": _RIGID_EDIT_STATE, "read_only": True},
         lambda p: state(["RgA:1", "RgC:1"])(p) and _measured("requested member identities read back", p,
                                                                            p.get("tokens") == p.get("wanted_tokens")), None),
        ("assembly_edit_relations", edit,
         lambda p: p.get("changed") is False and p.get("members") == ["RgA:1", "RgC:1"], None),
        ("sys_execute_script", {"script": _RIGID_EDIT_STATE, "read_only": True},
         state(["RgA:1", "RgC:1"]), None),
    ])


# ASSEMBLY-WRITE-1: a nested placement's native token raises, so the selected owner is matched by
# its unique path. The group fixture recipe: ReusedParent placed twice holding a 4 mm Leaf cube,
# and a free 4 x 4 x 10 mm Anchor at x 80 mm.
_PATTERN_POSE_SETUP = _PART_RECIPE + """
def run(context):
    root = _root()
    assert root.occurrences.count == 0 and root.bRepBodies.count == 0
    _part(root, 'RingSeed', 40, 0)
    _part(root, 'AxisSeed', 0, 0)
    _part(root, 'PathSeed', 0, 120)
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.name = 'PosePath'
    sk.sketchCurves.sketchLines.addByTwoPoints(adsk.core.Point3D.create(0,12,0), adsk.core.Point3D.create(6,12,0))
    print(json.dumps({'paths': sorted(o.fullPathName for o in root.occurrences)}))
"""

_PATTERN_POSE_STATE = """import adsk.core, adsk.fusion, json, math
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    coll = getattr(root.features, COLLECTION)
    feature = coll.itemByName(FEATURE)
    assert feature is not None
    poses = []
    for i in range(feature.patternElements.count):
        occurrences = list(feature.patternElements.item(i).occurrences)
        assert len(occurrences) == 1
        matrix = occurrences[0].transform2.asArray()
        assert len(matrix) == 16 and all(math.isfinite(v) for v in matrix)
        poses.append([round(v, 6) for v in matrix])
    print(json.dumps({'name': feature.name, 'bodies': feature.bodies.count,
        'elements': feature.patternElements.count, 'poses': poses,
        'origins': [[m[3] * 10, m[7] * 10, m[11] * 10] for m in poses],
        'health': int(feature.healthState), 'suppressed': feature.isSuppressed,
        'marker': design.timeline.markerPosition, 'count': design.timeline.count}))
"""


def _pattern_pose_rows():
    """Confirm root, on-axis and path occurrence placement through independent native poses."""
    rows = [("sys_execute_script", {"script": _PATTERN_POSE_SETUP, "read_only": False},
             lambda p: p.get("paths") == ["AxisSeed:1", "PathSeed:1", "RingSeed:1"], None)]
    for seed, quantity, collection, tool, args in (
        ("RingSeed", 5, "circularPatternFeatures", "model_pattern_circular",
         {"occurrences": ["RingSeed:1"], "axis": "z", "quantity": 5}),
        ("AxisSeed", 4, "circularPatternFeatures", "model_pattern_circular",
         {"occurrences": ["AxisSeed:1"], "axis": "z", "quantity": 4}),
        ("PathSeed", 3, "pathPatternFeatures", "model_pattern_path",
         {"occurrences": ["PathSeed:1"], "path": "sketch:PosePath", "quantity": 3,
          "distance": 10, "distance_type": "spacing", "units": "mm"}),
    ):
        key = "pattern_pose_" + seed
        rows.append((tool, args, lambda p, n=quantity: _measured("occurrence placement confirmed", p,
            p.get("elements_placed") == n and "pattern_elements_confirmed" not in p),
            (key, _recall(key, lambda p: p["feature"]))))
        def native(p, n=quantity, name=seed):
            poses, origins = p.get("poses"), p.get("origins")
            valid = (p.get("bodies") == 0 and p.get("elements") == n
                     and isinstance(poses, list) and len(poses) == n
                     and all(len(m) == 16 and all(_num(v) for v in m) for m in poses)
                     and len({tuple(m) for m in poses}) == n
                     and p.get("health") == 0 and p.get("suppressed") is False
                     and p.get("marker") == p.get("count"))
            if valid and name == "AxisSeed":
                valid = origins == [[0, 0, 0]] * n
            elif valid and name == "PathSeed":
                valid = (len(origins) == n and all(_near(o[1], 120, .001) and _near(o[2], 0, .001)
                          for o in origins) and sorted(round(o[0], 3) for o in origins) == [0, 10, 20])
            elif valid:
                valid = all(_near(math.hypot(o[0], o[1]), 40, .001) for o in origins)
            return _measured("independent " + name + " occurrence poses", p, valid)
        rows.append(("sys_execute_script", lambda c, k=key, col=collection: {
            "script": _PATTERN_POSE_STATE.replace("COLLECTION", repr(col)).replace(
                "FEATURE", repr(_ctx_get(c, k, "pattern feature"))), "read_only": True}, native, None))
    return _scratch("pattern_pose", rows)


_NESTED_OWNER_SETUP = _PART_RECIPE + """
def run(context):
    root = _root()
    first = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    first.component.name = 'ReusedParent'
    _part(first.component, 'Leaf', 0, 0, height='4 mm')
    m = adsk.core.Matrix3D.create()
    m.translation = adsk.core.Vector3D.create(4, 0, 0)
    root.occurrences.addExistingComponent(first.component, m)
    _part(root, 'Anchor', 80, 0, ground=False)
    print(json.dumps({'paths': sorted(o.fullPathName for o in root.allOccurrences)}))
"""

# Selects [ReusedParent:2+Leaf:1 top face, Anchor:1 bottom face], each a proxy in its placement.
_NESTED_OWNER_SELECT = """import adsk.core, adsk.fusion, json
def _cap(occ, top):
    body = occ.component.bRepBodies.item(0)
    best = None
    for i in range(body.faces.count):
        f = body.faces.item(i)
        lo, hi = f.boundingBox.minPoint.z, f.boundingBox.maxPoint.z
        if abs(hi - lo) <= 1e-6 and (best is None or (lo > best[0] if top else lo < best[0])):
            best = (lo, f)
    return best[1].createForAssemblyContext(occ)
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None, 'owned unsaved scratch only'
    occ = {o.fullPathName: o for o in adsk.fusion.Design.cast(app.activeProduct).rootComponent.allOccurrences}
    sel = app.userInterface.activeSelections
    sel.clear()
    added = [sel.add(_cap(occ['ReusedParent:2+Leaf:1'], True)), sel.add(_cap(occ['Anchor:1'], False))]
    print(json.dumps({'added': added, 'owners': [sel.item(i).entity.assemblyContext.fullPathName for i in range(sel.count)]}))
"""


def _anchor_seated(before, now):
    """The matched mate: one new constraint, Anchor's 4 x 4 x 10 box resting on the 4 mm Leaf top."""
    box = (now["placements"].get("Anchor:1") or {}).get("bodies") or [[[0] * 3, [0] * 3]]
    size = [b - a for a, b in zip(*box[0])]
    return (_all_but(before, now, {"Anchor:1"}) and len(now["constraints"]) == len(before["constraints"]) + 1
            and _near(box[0][0][2], 4.0, 1e-4) and all(_near(s, w, 1e-4) for s, w in zip(size, (4, 4, 10))))


def _nested_owner_rows():
    """A nested selection: the sibling placement is refused naming the real owner, the match mates."""
    selected = lambda p: p.get("added") == [True, True] and p.get("owners") == ["ReusedParent:2+Leaf:1", "Anchor:1"]
    return _scratch("nested_owner", [
        ("sys_execute_script", {"script": _NESTED_OWNER_SETUP, "read_only": False},
         lambda p: p.get("paths") == ["Anchor:1", "ReusedParent:1", "ReusedParent:1+Leaf:1",
                                      "ReusedParent:2", "ReusedParent:2+Leaf:1"], None),
        ("sys_execute_script", {"script": _NESTED_OWNER_SELECT, "read_only": False}, selected, None),
        ("sys_execute_script", {"script": _PLACED_STATE, "read_only": True}, _placed("nested_owner_before"), None),
        ("assembly_constrain", {"occurrence_one": "ReusedParent:1+Leaf:1", "occurrence_two": "Anchor:1",
                                "flipped": True},
         _refused("Selected entity 1 belongs to 'ReusedParent:2+Leaf:1'", "not requested 'ReusedParent:1+Leaf:1'"),
         None),
        ("sys_execute_script", {"script": _PLACED_STATE, "read_only": True},
         _placed("nested_owner_before", lambda b, n: n == b, "the sibling refusal changed nothing"), None),
        ("sys_execute_script", {"script": _NESTED_OWNER_SELECT, "read_only": False}, selected, None),
        ("assembly_constrain", {"occurrence_one": "ReusedParent:2+Leaf:1", "occurrence_two": "Anchor:1",
                                "flipped": True},
         lambda p: _constrained(p) and [m.get("occurrence") for m in p["moved"]] == ["Anchor:1"], None),
        ("sys_execute_script", {"script": _PLACED_STATE, "read_only": True},
         _placed("nested_owner_before", _anchor_seated, "Anchor seated on the Leaf top, all else held"), None),
        ("sys_execute_script", {"script": _selected_owner_script()}, lambda p: p.get("count") == 0, None),
    ])


# REVIEW-1005-NESTED-GROUP-PATTERN-OWNER-1 / WHT-V2-NESTED-ATTACHMENT-1: NrEye holds an unlocked
# NrBezel, a locked NrCowl and a rivet seed; NrRet holds the pair the second group takes.
_NESTED_RELATION_SETUP = _PART_RECIPE + """
def run(context):
    root = _root()
    _part(root, 'NrAnchor', 0, 80)
    eye = _part(root, 'NrEye', 0, 0)
    _part(eye.component, 'NrBezel', 10, 0, ground=False)
    _part(eye.component, 'NrCowl', 20, 0, ground=True)
    _part(eye.component, 'NrRivet', 42, 0)
    ret = _part(root, 'NrRet', 0, 40)
    _part(ret.component, 'NrDupA', 10, 0)
    _part(ret.component, 'NrDupB', 20, 0)
    print(json.dumps({'root': root.name,
                      'ground': {o.fullPathName: o.isGroundToParent for o in root.allOccurrences}}))
"""

# Every rigid group and circular pattern with the component whose collection holds it, its own
# parentComponent, and the pattern axis's component.
_NESTED_RELATION_STATE = """import adsk.core, adsk.fusion, json
def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    groups, patterns = [], []
    comps = design.allComponents
    for i in range(comps.count):
        c = comps.item(i)
        for k in range(c.rigidGroups.count):
            g = c.rigidGroups.item(k)
            groups.append({'walk': c.name, 'parent': g.parentComponent.name, 'name': g.name,
                           'suppressed': g.isSuppressed,
                           'members': sorted(o.name for o in g.occurrences),
                           'health': int(g.timelineObject.healthState)})
        cps = c.features.circularPatternFeatures
        for k in range(cps.count):
            p = cps.item(k)
            patterns.append({'walk': c.name, 'parent': p.parentComponent.name, 'name': p.name,
                             'axis_component': p.axis.component.name,
                             'element_count': p.patternElements.count,
                             'origins': [o.transform2.translation.asArray()
                                         for j in range(p.patternElements.count)
                                         for o in list(p.patternElements.item(j).occurrences)]})
    print(json.dumps({'root': design.rootComponent.name, 'groups': groups, 'patterns': patterns,
                      'marker': design.timeline.markerPosition, 'count': design.timeline.count}))
"""

# A second rigid group, in NrRet, carrying the first group's name.
_NESTED_RELATION_DUP = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None, 'owned unsaved scratch only'
    design = adsk.fusion.Design.cast(app.activeProduct)
    comps = {}
    for i in range(design.allComponents.count):
        comps[design.allComponents.item(i).name] = design.allComponents.item(i)
    first = comps['NrEye'].rigidGroups.item(0)
    ret = comps['NrRet']
    coll = adsk.core.ObjectCollection.create()
    for i in range(ret.occurrences.count):
        coll.add(ret.occurrences.item(i))
    group = ret.rigidGroups.add(coll, False)
    if group.name != first.name:
        group.name = first.name
    print(json.dumps({'first': first.name, 'second': group.name,
                      'owners': [first.parentComponent.name, group.parentComponent.name]}))
"""


def _timeline_owner(key, component):
    """design_get timeline: the one row named by the recalled feature carries this owner."""
    def check(p):
        rows = [r for r in ((p.get("timeline") or {}).get("timeline") or [])
                if r.get("name") == _RECALL.get(key)]
        return _measured(f"timeline row '{_RECALL.get(key)}' owned by {component}", rows,
                         len(rows) == 1 and rows[0].get("component") == component)
    return check


def _nested_relation_rows():
    """Nested group and pattern replies name their owner; a shared group name resolves by address."""
    bezel, cowl = "NrEye:1+NrBezel:1", "NrEye:1+NrCowl:1"
    timeline = {"include": ["timeline"], "max_results": 200}

    def grouped(p):
        note = p.get("note", "")
        return _rigid_grouped(2)(p) and _measured(
            "nested group owner and its unlocked member", p,
            p.get("component") == "NrEye" and "The group is owned by component 'NrEye'." in note
            and p.get("members_not_grounded_to_parent") == [bezel]
            and f"assembly_ground(occurrence='{bezel}', ground_to_parent=true)" in note)

    def patterned(p):
        axis, note = p.get("axis_component"), p.get("note", "")
        return _measured("nested pattern owner and its axis owner", p,
                         p.get("patterned") is True and p.get("quantity") == 5
                         and p.get("elements_placed") == 5 and "pattern_elements_confirmed" not in p
                         and p.get("component") == "NrEye" and axis == _RECALL.get("nr_root")
                         and "The pattern is owned by component 'NrEye'." in note
                         and f"Its axis belongs to component '{axis}'." in note)

    def native(second):
        """Require the measured owners and NrRet's given suppression state."""
        def check(p):
            groups = sorted([g["parent"], g["walk"], g["suppressed"]] for g in p.get("groups") or [])
            want = [["NrEye", "NrEye", False]] + ([] if second is None else [["NrRet", "NrRet", second]])
            pats = p.get("patterns") or []
            return _measured("native owners and suppression", p,
                             groups == want and len(pats) == 1
                             and pats[0]["parent"] == pats[0]["walk"] == "NrEye"
                             and pats[0]["axis_component"] == p.get("root") == _RECALL.get("nr_root")
                             and pats[0]["name"] == _RECALL.get("nr_pattern")
                             and pats[0].get("element_count") == 5
                             and len({tuple(o) for o in pats[0].get("origins", [])}) == 5)
        return check

    shared = lambda c: _ctx_get(c, "nr_group", "the shared group name")
    return _scratch("nested_relation", [
        ("sys_execute_script", {"script": _NESTED_RELATION_SETUP, "read_only": False},
         lambda p: (p.get("ground") or {}).get(bezel) is False
         and (p.get("ground") or {}).get(cowl) is True and bool(p.get("root")),
         ("nr_root", _recall("nr_root", lambda p: p["root"]))),
        ("assembly_rigid_group", {"occurrences": [bezel, cowl]}, grouped,
         ("nr_group", _recall("nr_group", lambda p: p["assembly_rigid_group"]))),
        ("design_get", timeline, _timeline_owner("nr_group", "NrEye"), None),
        ("assembly_edit_relations", lambda c: {"kind": "rigid_group", "name": shared(c),
                 "action": "set_occurrences", "occurrences": [bezel, "NrEye:1+NrRivet:1"]},
         lambda p: p.get("changed") is True and p.get("component") == "NrEye"
                   and p.get("member_count") == 2, None),
        ("sys_execute_script", {"script": _NESTED_RELATION_STATE, "read_only": True},
         lambda p: _measured("nested replacement membership and marker read independently", p,
             len(p.get("groups") or []) == 1
             and p["groups"][0].get("members") == ["NrBezel:1", "NrRivet:1"]
             and p["groups"][0].get("health") == 0 and p.get("marker") == p.get("count")), None),
        ("assembly_edit_relations", lambda c: {"kind": "rigid_group", "name": shared(c),
                 "action": "set_occurrences", "occurrences": [bezel, cowl]},
         lambda p: p.get("changed") is True and p.get("component") == "NrEye", None),
        ("sys_execute_script", {"script": _NESTED_RELATION_STATE, "read_only": True},
         lambda p: _measured("nested group restores its original members", p,
             len(p.get("groups") or []) == 1
             and p["groups"][0].get("members") == ["NrBezel:1", "NrCowl:1"]
             and p["groups"][0].get("health") == 0 and p.get("marker") == p.get("count")), None),
        ("model_pattern_circular", {"occurrences": ["NrEye:1+NrRivet:1"], "quantity": 5,
                                    "total_angle_deg": 360, "axis": "y"}, patterned,
         ("nr_pattern", _recall("nr_pattern", lambda p: p["feature"]))),
        ("design_get", timeline, _timeline_owner("nr_pattern", "NrEye"), None),
        ("sys_execute_script", {"script": _NESTED_RELATION_STATE, "read_only": True}, native(None), None),
        # The call the group reply names runs as printed.
        ("assembly_ground", {"occurrence": bezel, "ground_to_parent": True}, _grounded, None),
        # The plain name is refused listing both addresses; the listed address acts on one group.
        ("sys_execute_script", {"script": _NESTED_RELATION_DUP, "read_only": False},
         lambda p: p.get("first") == p.get("second") == _RECALL.get("nr_group")
         and p.get("owners") == ["NrEye", "NrRet"], None),
        ("assembly_edit_relations",
         lambda c: {"kind": "rigid_group", "action": "suppress", "name": shared(c)},
         _refused("names 2 rigid groups - refusing to guess which one. Pass one as listed:",
                  "'NrEye/Rigid Group 1'", "'NrRet/Rigid Group 1'"), None),
        ("sys_execute_script", {"script": _NESTED_RELATION_STATE, "read_only": True}, native(False), None),
        ("assembly_edit_relations",
         lambda c: {"kind": "rigid_group", "action": "suppress", "name": "NrRet/" + shared(c)},
         lambda p: p.get("is_suppressed") is True, None),
        ("sys_execute_script", {"script": _NESTED_RELATION_STATE, "read_only": True}, native(True), None),
    ])


# WHT-V2-ASBUILT-AXIS-EFFECT-1: two free carriages and a grounded bridge nested in one chassis.
_ASBUILT_AXIS_SETUP = _PART_RECIPE + """
def run(context):
    root = _root()
    chassis = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    chassis.component.name = 'WhChassis'
    chassis.isGroundToParent = True
    _part(chassis.component, 'WhBridge', 40, 0, ground=True)
    _part(chassis.component, 'WhCar2', 0, 30)
    _part(chassis.component, 'WhCar3', 0, 60)
    print(json.dumps({'paths': sorted(o.fullPathName for o in root.allOccurrences)}))
"""


def _slid_x(before, now):
    """Both carriages slid 2 mm along world +X (cells 3/7/11 in cm); the bridge held."""
    def delta(path):
        a, b = before["placements"][path]["matrix"], now["placements"][path]["matrix"]
        return [round(b[i] - a[i], 6) for i in (3, 7, 11)]
    return (_all_but(before, now, {"WhChassis:1+WhCar2:1", "WhChassis:1+WhCar3:1"})
            and delta("WhChassis:1+WhCar2:1") == delta("WhChassis:1+WhCar3:1") == [0.2, 0, 0])


def _asbuilt_axis_rows():
    """world_axis on an as-built slider is refused before any write; axis=x still slides along +X."""
    steps = [("sys_execute_script", {"script": _ASBUILT_AXIS_SETUP, "read_only": False},
              lambda p: p.get("paths") == ["WhChassis:1", "WhChassis:1+WhBridge:1", "WhChassis:1+WhCar2:1",
                                           "WhChassis:1+WhCar3:1"], None)]
    for name, car in (("WhAxis", "WhCar2"), ("WhWorld", "WhCar3")):
        steps.append(("joint_create_as_built", {
            "occurrence_one": f"WhChassis:1+{car}:1", "occurrence_two": "WhChassis:1+WhBridge:1",
            "geometry": f"WhChassis:1+{car}:1:origin", "joint_type": "slider", "axis": "x", "name": name},
            lambda p, n=name: _as_built(p) and p.get("joint") == n, None))
    return _scratch("asbuilt_axis", steps + [
        ("joint_edit", {"joint_name": "WhWorld", "world_axis": "x"},
         _refused("AS-BUILT", "world_axis=x", "No edits applied", "design_delete_feature", "joint_create"), None),
        ("joint_edit", {"joint_name": "WhAxis", "axis": "x"},
         lambda p: p.get("edited") is True and p.get("axis") == "x", None),
        ("design_recompute", {}, "ok", None),
        ("sys_execute_script", {"script": _PLACED_STATE, "read_only": True}, _placed("asbuilt_axis_before"), None),
        ("joint_drive", {"joint_name": "WhWorld", "distance": 2, "units": "mm"}, "ok", None),
        ("joint_drive", {"joint_name": "WhAxis", "distance": 2, "units": "mm"}, "ok", None),
        ("sys_execute_script", {"script": _PLACED_STATE, "read_only": True},
         _placed("asbuilt_axis_before", _slid_x, "both carriages slid +2 mm along world X"), None),
    ])


# The member's own body moves while its un-grounded child holds the subtree's min corner.
_DRIVE_OWN_BODY_SETUP = _PART_RECIPE + """
def run(context):
    root = _root()
    _part(root, 'JdAnchor', 0, 60, ground=True)
    eye = _part(root, 'JdEye', 0, 0, ground=False)
    child = _part(eye.component, 'JdFree', -30, 0, ground=False)
    print(json.dumps({'paths': sorted(o.fullPathName for o in root.allOccurrences),
                      'parent_ground_to_parent': eye.isGroundToParent,
                      'child_ground_to_parent': child.isGroundToParent}))
"""


def _eye_body_slid(before, now):
    """The own body translates 5 mm in X; the child, anchor and history stay unchanged."""
    paths = {'JdAnchor:1', 'JdEye:1', 'JdEye:1+JdFree:1'}
    if (set(before['placements']) != paths or set(now['placements']) != paths
            or any(len(r['bodies']) != 1 for r in before['placements'].values())
            or any(len(r['bodies']) != 1 for r in now['placements'].values())):
        return False
    a = before['placements']['JdEye:1']['bodies'][0]
    b = now['placements']['JdEye:1']['bodies'][0]
    shift = b[0][0] - a[0][0]
    return (_all_but(before, now, {'JdEye:1'}) and _near(abs(shift), 5.0, 1e-4)
            and _near(b[1][0] - a[1][0], shift, 1e-4)
            and b[0][1:] == a[0][1:] and b[1][1:] == a[1][1:]
            and now['constraints'] == before['constraints']
            and now['timeline_count'] == before['timeline_count'])


def _drive_own_body_rows():
    """Verify a slider drive against own geometry, independently of its stationary child."""
    return _scratch('drive_own_body', [
        ('sys_execute_script', {'script': _DRIVE_OWN_BODY_SETUP, 'read_only': False},
         lambda p: p.get('paths') == ['JdAnchor:1', 'JdEye:1', 'JdEye:1+JdFree:1']
                   and p.get('parent_ground_to_parent') is False
                   and p.get('child_ground_to_parent') is False, None),
        ('joint_create_as_built', {
            'occurrence_one': 'JdEye:1', 'occurrence_two': 'JdAnchor:1',
            'geometry': 'JdEye:1:origin', 'joint_type': 'slider', 'axis': 'x', 'name': 'JdSlide'},
         lambda p: _as_built(p) and p.get('joint') == 'JdSlide', None),
        ('sys_execute_script', {'script': _PLACED_STATE, 'read_only': True},
         _placed('drive_own_body_before'), None),
        ('joint_drive', {'joint_name': 'JdSlide', 'distance': 5, 'units': 'mm'},
         lambda p: _measured('the drive landed and its own body carried it',
                             {'driven': p.get('driven'), 'moved': p.get('moved')},
                             p.get('driven') is True
                             and (p.get('moved') or {}).get('occurrence') == 'JdEye:1'
                             and _near((p.get('moved') or {}).get('geometry_moved_mm'), 5.0, 1e-3)),
         None),
        ('sys_execute_script', {'script': _PLACED_STATE, 'read_only': True},
         _placed('drive_own_body_before', _eye_body_slid,
                 "JdEye's own body slid 5 mm, JdFree and the anchor held"), None),
    ])


# JOINT-CREATE-1: a slider on an anchor turned +90 deg about X lands its offset along the anchor's
# lifted frame Z and its angle about it, read off the mover's own matrix.
_PLACED_SLIDER_SETUP = _PART_RECIPE + """
def run(context):
    root = _root()
    _part(root, 'JcSlAnchor', 0, 200, 90, adsk.core.Vector3D.create(1, 0, 0), ground=True)
    _part(root, 'JcSlMove', 0, 260, ground=False)
    print(json.dumps({'paths': sorted(o.fullPathName for o in root.allOccurrences)}))
"""
_JCSL_MOVED = [0.956305, 0.292372, 0, 0, 0, 0, -1, 20.4, -0.292372, 0.956305, 0, 0, 0, 0, 0, 1]


def _slider_offset_landed(before, now):
    """The mover's matrix is the measured offset-4 / angle-17 pose; the anchor held."""
    got = now["placements"]["JcSlMove:1"]["matrix"]
    return _all_but(before, now, {"JcSlMove:1"}) and all(_near(a, b, 1e-5) for a, b in zip(got, _JCSL_MOVED))


def _placed_slider_rows():
    """joint_create's offset/angle/flip on a placed anchor, judged by the mover's native matrix."""
    return _scratch("placed_slider", [
        ("sys_execute_script", {"script": _PLACED_SLIDER_SETUP, "read_only": False},
         lambda p: p.get("paths") == ["JcSlAnchor:1", "JcSlMove:1"], None),
        ("sys_execute_script", {"script": _PLACED_STATE, "read_only": True}, _placed("placed_slider_before"), None),
        ("joint_create", {"occurrence_one": "JcSlAnchor:1:origin", "occurrence_two": "JcSlMove:1:origin",
                          "joint_type": "slider", "axis": "x", "offset": 4, "angle": 17, "flip": False,
                          "units": "mm", "name": "JcSlider"},
         lambda p: _jointed("JcSlider")(p) and p.get("offset") == 4 and p.get("angle_deg") == 17
         and p.get("flipped") is False, None),
        ("sys_execute_script", {"script": _PLACED_STATE, "read_only": True},
         _placed("placed_slider_before", _slider_offset_landed, "mover at the measured offset/angle pose"), None),
        ("design_delete_feature", {"feature": "JcSlider"}, "ok", None),
        ("sys_execute_script", {"script": _PLACED_STATE, "read_only": True},
         _placed("placed_slider_before", lambda b, n: n == b, "retiring the joint restored every pose"), None),
    ])


# REVIEW-0921-PINSLOT-CUSTOM-1: JRig's own pin-slot heading, read natively.
_JRIG_HEADING = """import adsk.core, adsk.fusion, json
def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    found = [j for c in design.allComponents for j in c.joints if j.name == 'JRig']
    assert len(found) == 1
    m, JD = found[0].jointMotion, adsk.fusion.JointDirections
    entity = m.customRotationAxisEntity
    d = entity.geometry.direction if entity else None
    names = {JD.XAxisJointDirection: 'x', JD.YAxisJointDirection: 'y', JD.ZAxisJointDirection: 'z'}
    print(json.dumps({'rotation_custom': m.rotationAxis == JD.CustomJointDirection,
                      'rotation_entity': [round(d.x, 6), round(d.y, 6), round(d.z, 6)] if d else None,
                      'slide': names.get(m.slideDirection),
                      'slide_dot_rotation': m.slideDirectionVector.dotProduct(m.rotationAxisVector),
                      'custom_slide': m.customSlideDirectionEntity is not None,
                      'health': int(found[0].healthState)}))
"""


def _jrig_custom_slide(axis):
    """JRig keeps its custom world-Y rotation entity and slides along frame `axis`, healthy."""
    def check(p):
        d = p.get("rotation_entity") or [None] * 3
        dot = p.get("slide_dot_rotation")
        return _measured("JRig custom Y rotation kept, slide on frame " + axis, p,
                         p.get("rotation_custom") is True and _near(abs(d[1] or 0), 1, 1e-6)
                         and p.get("slide") == axis and isinstance(dot, (int, float))
                         and abs(dot) < 1e-6 and p.get("custom_slide") is False
                         and p.get("health") == 0)
    return check


def _crossing_rotation_rows(motion):
    """Enabled -10/10 deg on JRig's `motion`; a crossing single bound is refused with limits held."""
    key = "jrig_" + motion + "_rotation_limits"
    history = {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True, "max_results": 2000}
    return [
        ("joint_edit", {"joint_name": "JRig", "min_deg": -10, "max_deg": 10},
         lambda p: p.get("changes") == {"min_deg": -10, "max_deg": 10}, None),
        ("assembly_get", {"include": ["poses"]},
         _joint_limit_snapshot("JRig", motion, "deg", -10, 10, key, True), None),
        ("design_get", history, _retire_compare(key + "_history", _retire_design_state, False), None),
        ("joint_edit", {"joint_name": "JRig", "max_deg": -20},
         _refused("max_deg=-20", "min_deg=-10", "No edits applied", "assembly_get"), None),
        ("assembly_get", {"include": ["poses"]},
         _joint_limit_snapshot("JRig", motion, "deg", -10, 10, key, False), None),
        ("design_get", history, _retire_compare(key + "_history", _retire_design_state, True), None),
    ]


def _joint_row(name):
    """One joint's assembly_get row, or None when it is absent."""
    return lambda p: next((j for j in (p.get("joints") or []) if j.get("name") == name), None)


# REVIEW-1004-JOINT-APPLIED-DISCLOSURE-1: a revolute between two Joint Origins, then DLate built
# after it - so DLate's faces are later in the timeline than DJoint.
_LATE_INPUT_SETUP = _PART_RECIPE + """
def run(context):
    root = _root()
    def origin(occ, name):
        comp = occ.component
        jo = comp.jointOrigins.add(comp.jointOrigins.createInput(
            adsk.fusion.JointGeometry.createByPoint(comp.originConstructionPoint)))
        jo.name = name
        return jo.createForAssemblyContext(occ)
    anchor, moving = _part(root, 'DAnchor', 240, 0, ground=True), _part(root, 'DMoving', 260, 0, ground=False)
    ji = root.joints.createInput(origin(anchor, 'DOrigA'), origin(moving, 'DOrigM'))
    ji.setAsRevoluteJointMotion(adsk.fusion.JointDirections.ZAxisJointDirection)
    root.joints.add(ji).name = 'DJoint'
    _part(root, 'DLate', 300, 0, ground=False)
    print(json.dumps({'joints': [j.name for j in root.joints],
                      'paths': sorted(o.fullPathName for o in root.allOccurrences)}))
"""


def _late_input_rows():
    """A later face as a joint input is refused before any write; joint, poses and history held."""
    history = {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
               "max_depth": 10, "max_results": 2000}
    def reads(after):
        return [("sys_execute_script", {"script": _PLACED_STATE, "read_only": True},
                 _placed("late_input_before", (lambda b, n: n == b) if after else None), None),
                ("assembly_get", {"units": "mm"}, _retire_compare("late_input_joint", _joint_row("DJoint"), after), None),
                ("design_get", history, _retire_compare("late_input_history", _retire_design_state, after), None)]
    return _scratch("late_input", [
        ("sys_execute_script", {"script": _LATE_INPUT_SETUP, "read_only": False},
         lambda p: p.get("joints") == ["DJoint"] and p.get("paths") == ["DAnchor:1", "DLate:1", "DMoving:1"], None),
    ] + reads(False) + [
        ("joint_edit", {"joint_name": "DJoint", "input_two": "DLate:1:top"},
         _refused("Cannot rewire 'DJoint' input_two", "'DLate:1'", "not before the joint", "No edits applied"),
         None),
    ] + reads(True))


def _turned_over(occurrence):
    """joint_edit(flip=...): 'moved' names the arm turned half a revolution by the flip."""
    def check(p):
        rows = [m for m in p.get("moved") or [] if m.get("occurrence") == occurrence]
        turn = rows[0].get("rotation_deg") if rows else None
        return _measured(f"{occurrence} turned over by the flip", {"moved": p.get("moved")},
                         _num(turn) and 170.0 <= turn <= 180.0)
    return check


def _center_z_vs(key, moved):
    """model_inspect: the arm's box centre z against the one recalled before the flip."""
    def check(p):
        now, was = (p.get("center") or {}).get("z"), _RECALL.get(key)
        return _measured(f"arm box centre z {'moved off' if moved else 'back at'} {was}",
                         {"center_z": now},
                         _num(now) and _num(was) and (abs(now - was) > 2.0) is moved
                         and (moved or abs(now - was) <= 0.05))
    return check


# --- ACT 7b: THE MOTION BENCH - every joint and assembly verb on rigs of its own ---------------
# The vise act ahead of this one is the STORY's mechanism; these rows are the rest of the
# vocabulary, each on a scratch rig so nothing here can disturb the part in its fixture.
_MOTION = (
    # A rigid group on two scratch boxes. Its NAME is kept: the vise act ahead of this one built a
    # rigid group and a motion link of its own, so the lifecycle below has to address the relation
    # it created rather than whichever one the design lists first.
    _box("GrpA", ox=1400, tint="#5E6AD2") + _box("GrpB", ox=1440, tint="#8A94A6")
    + [
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("assembly_rigid_group", {"occurrences": ["GrpA:1", "GrpB:1"]}, _rigid_grouped(2),
     ("bench_group", _recall("bench_group", lambda p: p["assembly_rigid_group"]))),
    # a real cylinder-face joint on a scratch pin/bore cameo pair.
    ("model_create_component", {"name": "PinCameo", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "PinS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 300, "cy": 0, "radius": 5}],
                             "sketch_name": "PinS"}, "ok", None),
    ("model_extrude", {"sketch_name": "PinS", "profile_index": 0, "distance": 20}, _extruded, None),
    ("model_create_component", {"name": "BoreCameo", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "BoreS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 300, "cy": 0, "radius": 8}],
                             "sketch_name": "BoreS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 300, "cy": 0, "radius": 5.5}],
                             "sketch_name": "BoreS"}, "ok", None),
    ("sketch_get", {"sketch_name": "BoreS"}, "ok", ("bore_ring", lambda p: p["profiles"][-1]["handle"])),
    ("model_extrude", lambda c: {"sketch_name": "BoreS", "profile_index": _ctx_get(c, "bore_ring", "bore ring"), "distance": 20}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    _watch("BoreCameo:1"),
    ("find_geometry", {"target": "PinCameo", "kind": "cylinder_face", "max_results": 1}, "ok", _fg("pin_cyl")),
    ("find_geometry", {"target": "BoreCameo", "kind": "cylinder_face", "radius": 5.5, "max_results": 1}, "ok", _fg("bore_cyl")),
    ("joint_at_geometry", lambda c: {"handle_one": _ctx_get(c, "pin_cyl", "pin face"), "handle_two": _ctx_get(c, "bore_cyl", "bore face"), "motion": "revolute"}, _jointed_at_geometry, None),
    # THE MOTION VOCABULARY at the geometry seam - a ball on a real SPHERE face, an explicit frame
    # axis, and rigid. Each beat takes its own free cameo pair, chained as a TREE (sphere - post -
    # post), so no beat closes a loop on another's joint. The sphere is built through the surface
    # family the same way the fill cameo builds one: a half-disc arc revolved into a closed sheet and
    # sealed solid, which is what gives this beat a genuine SphereSurfaceType face to joint at (a
    # sphere face takes ONLY CenterKeyPoint - the rule inside _joints.build_joint_geometry).
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "BallSphere", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xz", "name": "BallProf"}, "ok", None),
    # the arc's endpoints must sit ON the revolve axis (x=0) or the revolved surface is an open tube
    # enclosing nothing; on an xz sketch +Y maps to world -Z, so this sphere sits alone at z=+300.
    ("sketch_add_geometry", {"geometry": [{"kind": "arc", "cx": 0, "cy": -300, "x1": 0,
                                           "y1": -294, "sweep_deg": 180}],
                             "sketch_name": "BallProf"}, "ok", None),
    ("surface_revolve", {"sketch_name": "BallProf", "axis": "z", "angle_deg": 360}, "ok", None),
    ("surface_fill", {"tools": ["BallSphere"], "operation": "new"},
     lambda p: p.get("all_solid") is True, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "BallPost", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "BallPostS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 1700, "cy": 0, "radius": 5}],
                             "sketch_name": "BallPostS"}, "ok", None),
    ("model_extrude", {"sketch_name": "BallPostS", "profile_index": 0, "distance": 20}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "AxisPost", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "AxisPostS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 1700, "cy": 60, "radius": 5}],
                             "sketch_name": "AxisPostS"}, "ok", None),
    ("model_extrude", {"sketch_name": "AxisPostS", "profile_index": 0, "distance": 20}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "RigidPost", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "RigidPostS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 1700, "cy": 120, "radius": 5}],
                             "sketch_name": "RigidPostS"}, "ok", None),
    ("model_extrude", {"sketch_name": "RigidPostS", "profile_index": 0, "distance": 20}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    _watch("BallPost:1"),
    ("find_geometry", {"target": "BallSphere", "kind": "sphere_face", "max_results": 1}, "ok",
     _fg("ball_face")),
    ("find_geometry", {"target": "BallPost", "kind": "cylinder_face", "max_results": 1}, "ok",
     _fg("ball_post_cyl")),
    ("find_geometry", {"target": "AxisPost", "kind": "cylinder_face", "max_results": 1}, "ok",
     _fg("axis_post_cyl")),
    ("find_geometry", {"target": "RigidPost", "kind": "cylinder_face", "max_results": 1}, "ok",
     _fg("rigid_post_cyl")),
    # the ball seats the sphere's CENTRE on the post's own key point, and the label proves which
    # key point the sphere face resolved to. A ball joint reads no axis at all, so 'axis' is null
    # and the note carries NO axis sentence - not the frame-axis caveat, not the derived-axis one.
    ("joint_at_geometry", lambda c: {"handle_one": _ctx_get(c, "ball_face", "the sphere face"),
                                     "handle_two": _ctx_get(c, "ball_post_cyl", "the ball post wall"),
                                     "motion": "ball", "name": "BallSeat"},
     lambda p: p.get("jointed") is True and p.get("geometry_one") == "sphere_face@center"
     and p.get("axis") is None
     and "FRAME's" not in (p.get("note") or "") and "world_axis=" not in (p.get("note") or "")
     and "derived the motion axis" not in (p.get("note") or ""), None),
    # an EXPLICIT axis is frame-relative, and the note says so in the words that stop a caller
    # reading it as a world axis - plus the one tool that does set a true world axis.
    ("joint_at_geometry", lambda c: {"handle_one": _ctx_get(c, "ball_post_cyl", "the ball post wall"),
                                     "handle_two": _ctx_get(c, "axis_post_cyl", "the axis post wall"),
                                     "motion": "revolute", "axis": "y", "name": "FrameAxisSpin"},
     lambda p: "FRAME's y axis, NOT world y" in (p.get("note") or "")
     and "joint_edit(world_axis=" in (p.get("note") or ""), None),
    # an axis outside the Choice is refused by name, listing what the input carries - nothing built.
    ("joint_at_geometry", lambda c: {"handle_one": _ctx_get(c, "ball_post_cyl", "the ball post wall"),
                                     "handle_two": _ctx_get(c, "axis_post_cyl", "the axis post wall"),
                                     "motion": "revolute", "axis": "diagonal"}, "refused", None),
    # rigid has no motion to aim, so it too publishes a null axis and an axis-free note.
    ("joint_at_geometry", lambda c: {"handle_one": _ctx_get(c, "ball_post_cyl", "the ball post wall"),
                                     "handle_two": _ctx_get(c, "rigid_post_cyl", "the rigid post wall"),
                                     "motion": "rigid", "name": "PostLock"},
     lambda p: p.get("jointed") is True and p.get("axis") is None
     and "FRAME's" not in (p.get("note") or "")
     and "derived the motion axis" not in (p.get("note") or ""), None),
    # NEW-1: the TORUS keypoint gate. createByNonPlanarFace(torus, CenterKeyPoint) is measured
    # correct on a PARAMETRIC torus and silently WRONG inside a base feature (it hands back the
    # owning component's origin with no error), so the tool compares the keypoint against the
    # torus's own centre in the same world frame. This beat is the parametric side: the joint lands
    # and the payload names the key point it resolved to. (The two base-feature halves need a torus
    # built INSIDE a base feature; no tool on this surface builds one unattended - see STORY.)
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "TorusRing", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xz", "name": "TorusProf"}, "ok", None),
    # on an xz sketch +Y maps to world -Z: this circle sits at world (40, 0, 400) and revolving it
    # about z sweeps a torus of major radius 40 centred on the z axis at z=400, alone up there.
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 40, "cy": -400, "radius": 6}],
                             "sketch_name": "TorusProf"}, "ok", None),
    ("model_revolve", {"sketch_name": "TorusProf", "profile_index": 0, "axis": "z",
                       "angle_deg": 360}, _revolved, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "TorusPost", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "TorusPostS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 1700, "cy": 180, "radius": 5}],
                             "sketch_name": "TorusPostS"}, "ok", None),
    ("model_extrude", {"sketch_name": "TorusPostS", "profile_index": 0, "distance": 20}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("find_geometry", {"target": "TorusRing", "kind": "torus_face", "max_results": 1}, "ok",
     _fg("torus_face")),
    ("find_geometry", {"target": "TorusPost", "kind": "cylinder_face", "max_results": 1}, "ok",
     _fg("torus_post_cyl")),
    ("joint_at_geometry", lambda c: {"handle_one": _ctx_get(c, "torus_face", "the torus face"),
                                     "handle_two": _ctx_get(c, "torus_post_cyl",
                                                            "the torus post wall"),
                                     "motion": "rigid", "name": "TorusSeat"},
     lambda p: p.get("jointed") is True and p.get("geometry_one") == "torus_face@center", None),
    # A NON-RIGID as-built joint, on its own far-grid pair: an as-built joint moves nothing, so the
    # plate is built already seated on the pin's top face (z=20) and jointed where it stands. The
    # anchor is that shared face, reached by the pin's 'top' snap.
    ("model_create_component", {"name": "AsbPin", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "AsbPinS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 800, "y1": 300,
                                           "x2": 820, "y2": 320}],
                             "sketch_name": "AsbPinS"}, "ok", None),
    ("model_extrude", {"sketch_name": "AsbPinS", "profile_index": 0, "distance": 20}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "AsbPlate", "activate": True}, _made_component, None),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 20, "name": "AsbSeat"},
     _datum_plane("xy"), None),
    ("sketch_create", {"plane": "AsbSeat", "name": "AsbPlateS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 790, "y1": 290,
                                           "x2": 830, "y2": 330}],
                             "sketch_name": "AsbPlateS"}, "ok", None),
    ("model_extrude", {"sketch_name": "AsbPlateS", "profile_index": 0, "distance": 10}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    _watch("AsbPlate:1"),
    # the motion is read back off the CREATED joint, and the resolved anchor is named in the payload.
    # 'name' rides the same create: AsBuiltJoints.createInput/add take no name, so it is applied
    # post-create and READ BACK - 'joint' is what the browser shows, never an echo.
    ("joint_create_as_built", {"occurrence_one": "AsbPin:1", "occurrence_two": "AsbPlate:1",
                               "geometry": "AsbPin:1:top", "joint_type": "revolute", "axis": "z",
                               "name": "AsbNamed"},
     lambda p: p.get("joint_type") == "revolute" and bool(p.get("geometry"))
     and p.get("joint") == "AsbNamed"
     # the configured-design sentence is gated on THIS design carrying a configuration table, which
     # a sweep document does not - so it costs an ordinary design nothing.
     and "CONFIGURED" not in (p.get("note") or "")
     # the as-built joint's pose is a CAPTURED snapshot, not driven - the receipt says so.
     and "CAPTURED, not driven" in (p.get("note") or ""),
     ("asb_joint", lambda p: p["joint"])),
    # an INDEPENDENT read of the same joint: the tool's own read-back is not the only witness, and
    # the row + the design-level note both disclose the captured pose (FSAE-0922-ASBUILT-PARAM-FOLLOW-1).
    ("assembly_get", {},
     lambda p: any(j.get("type") == "revolute" and j.get("as_built") is True
                   and {j.get("occurrence_one"), j.get("occurrence_two")} == {"AsbPin:1", "AsbPlate:1"}
                   for j in (p.get("joints") or []))
     and "AsbNamed" in (p.get("note") or "") and "CAPTURED" in (p.get("note") or ""), None),
    # the beat the read-backs cannot fake: a motion that reads back but cannot be DRIVEN is no DOF.
    ("joint_drive", lambda c: {"joint_name": _ctx_get(c, "asb_joint", "the as-built revolute"),
                               "angle_deg": 30},
     lambda p: abs(p.get("value_now", {}).get("angle_deg", 0) - 30) < 0.5, None),
    ("joint_drive", lambda c: {"joint_name": _ctx_get(c, "asb_joint", "the as-built revolute"),
                               "angle_deg": 0}, _driven_angle(0), None),
    # Fusion refuses a non-rigid as-built joint with a null geometry, so the tool names the missing
    # anchor instead of letting add() raise.
    ("joint_create_as_built", {"occurrence_one": "AsbPin:1", "occurrence_two": "AsbPlate:1",
                               "joint_type": "revolute"}, "refused", None),
    # a rigid as-built joint IGNORES a geometry it is handed, so the pairing is refused rather than
    # accepted and dropped.
    ("joint_create_as_built", {"occurrence_one": "AsbPin:1", "occurrence_two": "AsbPlate:1",
                               "joint_type": "rigid", "geometry": "AsbPin:1:top"}, "refused", None),
    # an AsBuiltJoint exposes NO offset/angle ModelParameter for ANY motion - both parametric-drive
    # refusals name AS-BUILT and route to joint_create instead of the dead-end generic wording.
    ("joint_edit", lambda c: {"joint_name": _ctx_get(c, "asb_joint", "the as-built revolute"),
                              "offset": 5}, _refused("AS-BUILT", "joint_create"), None),
    ("joint_edit", lambda c: {"joint_name": _ctx_get(c, "asb_joint", "the as-built revolute"),
                              "angle": 30}, _refused("AS-BUILT", "joint_create"), None),
    # a SECOND as-built joint on an already-jointed pair is refused by the platform at add()
    # ("System will be over constrained") - measured; the tool surfaces it, never a false ok.
    ("joint_create_as_built", {"occurrence_one": "AsbPin:1", "occurrence_two": "AsbPlate:1",
                               "joint_type": "rigid"},
     _refused("over constrained"), None),
    # THE JOINT BENCH: one grounded base, a STATION for every motion type spaced along it, and a
    # flag-shaped indicator arm at each. The arm shape is the point - a disc turning about its own
    # axis shows nothing, so every station carries a bar whose far end reads its position at a
    # glance, and the stations are spread along the base so the seven motions stand side by side
    # instead of on top of each other. Each arm is drawn OFF the base and its joint carries it to
    # its station, so the mate itself is visible; the drive pass below then moves the ones that
    # have a degree of freedom, which is the only way a motion type can be told from a label.
    ("model_create_component", {"name": "JointBase", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "JBaseS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 860, "y1": 300,
                                           "x2": 1190, "y2": 340}],
                             "sketch_name": "JBaseS"}, "ok", None),
    ("model_extrude", {"sketch_name": "JBaseS", "profile_index": 0, "distance": 10},
     _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("appearance_set", {"target": "JointBase", "color": "#37474F"}, "ok", None),
    # GROUNDED TO PARENT - the base is the fixed frame every station's motion is read against. An
    # arm that moved because the base drifted would read as the joint working.
    ("assembly_ground", {"occurrence": "JointBase:1", "ground_to_parent": True}, _grounded, None),
] + _joint_bench() + [
    ("joint_edit", {"joint_name": "W7UnknownJointNameThatIsLongerThanFortyCharacters", "joint_type": "rigid"},
     _refused("No joint named", "W7UnknownJointNameThatIsLongerThanFortyCharacters", "design_get"), None),
    ("assembly_get", {}, _joint_is("JRev", "revolute"), None),
    # LIMITS on the revolute station, set AFTER the bench's own pass has swung it 90 deg and put it
    # back. Every published limit is read BACK off the live JointLimits, so an empty
    # 'limits_unverified' beside real numbers is the write confirmed.
    ("joint_edit", {"joint_name": "JRev", "min_deg": -45, "max_deg": 45},
     _joint_limits("JRev", min_deg=-45, max_deg=45), None),
    # THE RETYPE, on a station that is already visible: one joint walked through every motion the
    # tool carries, each retype witnessed by the design's own joint walk rather than by the writer,
    # which publishes the type it was ASKED for. It ends back on the revolute it started as.
    ("joint_edit", {"joint_name": "JRig", "joint_type": "revolute", "axis": "z"}, "ok", None),
    ("assembly_get", {}, _joint_is("JRig", "revolute"), None),
    ("joint_edit", {"joint_name": "JRig", "joint_type": "slider", "axis": "x"}, "ok", None),
    ("assembly_get", {}, _joint_is("JRig", "slider"), None),
    ("joint_edit", {"joint_name": "JRig", "min_mm": -5, "max_mm": 5},
     lambda p: p.get("changes") == {"min_mm": -5, "max_mm": 5}, None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "slider", "mm", -5, 5, "jrig_slider_limits", True), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_slider_limit_history", _retire_design_state, False), None),
    ("joint_edit", {"joint_name": "JRig", "max_mm": -10},
     _refused("max_mm=-10", "min_mm=-5", "No edits applied", "assembly_get"), None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "slider", "mm", -5, 5, "jrig_slider_limits", False), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_slider_limit_history", _retire_design_state, True), None),
    ("joint_edit", {"joint_name": "JRig", "max_mm": -1, "units": "cm"},
     _refused("max_mm=-1", "min_mm=-0.5 cm", "No edits applied", "assembly_get"), None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "slider", "mm", -5, 5, "jrig_slider_limits", False), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_slider_limit_history", _retire_design_state, True), None),
    ("joint_edit", {"joint_name": "JRig", "min_mm": 1, "units": "in"},
     _refused("min_mm=1", "max_mm=0.196850394 in", "No edits applied", "assembly_get"), None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "slider", "mm", -5, 5, "jrig_slider_limits", False), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_slider_limit_history", _retire_design_state, True), None),
    ("joint_edit", {"joint_name": "JRig", "max_mm": 0.6, "units": "cm"},
     lambda p: p.get("changes") == {"max_mm": 0.6}, None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "slider", "mm", -5, 6, "jrig_slider_cm_legal", True), None),
    ("joint_edit", {"joint_name": "JRig", "max_mm": 5, "units": "mm"},
     lambda p: p.get("changes") == {"max_mm": 5.0}, None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "slider", "mm", -5, 5, "jrig_slider_limits", False), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_slider_limit_history", _retire_design_state, True), None),
    ("joint_edit", {"joint_name": "JRig", "joint_type": "cylindrical", "axis": "z"}, "ok", None),
    ("assembly_get", {}, _joint_is("JRig", "cylindrical"), None),
    ("joint_edit", {"joint_name": "JRig", "min_mm": -5, "max_mm": 5},
     lambda p: p.get("changes") == {"min_mm": -5, "max_mm": 5}, None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "cylindrical", "mm", -5, 5, "jrig_cyl_slide_limits", True), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_cyl_slide_limit_history", _retire_design_state, False), None),
    ("joint_edit", {"joint_name": "JRig", "max_mm": -10},
     _refused("max_mm=-10", "min_mm=-5", "No edits applied", "assembly_get"), None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "cylindrical", "mm", -5, 5, "jrig_cyl_slide_limits", False), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_cyl_slide_limit_history", _retire_design_state, True), None),
    ("joint_edit", {"joint_name": "JRig", "min_deg": -10, "max_deg": 10},
     lambda p: p.get("changes") == {"min_deg": -10, "max_deg": 10}, None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "cylindrical", "deg", -10, 10, "jrig_cyl_rotation_limits", True), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_cyl_rotation_limit_history", _retire_design_state, False), None),
    ("joint_edit", {"joint_name": "JRig", "max_deg": -20},
     _refused("max_deg=-20", "min_deg=-10", "No edits applied", "assembly_get"), None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "cylindrical", "deg", -10, 10, "jrig_cyl_rotation_limits", False), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_cyl_rotation_limit_history", _retire_design_state, True), None),
    # A world_axis re-aim keeps the enabled -5/5 mm slide limits, read off the design's own walk.
    ("joint_edit", {"joint_name": "JRig", "world_axis": "y"},
     lambda p: p.get("edited") is True and p.get("world_axis") == "y", None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "cylindrical", "mm", -5, 5, "jrig_cyl_reaimed_slide_limits", True), None),
    ("joint_edit", {"joint_name": "JRig", "joint_type": "planar", "axis": "z"}, "ok", None),
    ("assembly_get", {}, _joint_is("JRig", "planar"), None),
] + _crossing_rotation_rows("planar") + [
    ("joint_edit", {"joint_name": "JRig", "joint_type": "ball"}, "ok", None),
    ("assembly_get", {}, _joint_is("JRig", "ball"), None),
    # pin_slot alone takes TWO frame directions - it rotates about one and slides along another, so
    # the pair must differ.
    ("joint_edit", {"joint_name": "JRig", "joint_type": "pin_slot", "world_axis": "y",
                    "slide_axis": "x"}, "ok", None),
    ("assembly_get", {}, _joint_is("JRig", "pin_slot"), None),
    ("joint_edit", {"joint_name": "JRig", "min_mm": -5, "max_mm": 5},
     lambda p: p.get("changes") == {"min_mm": -5, "max_mm": 5}, None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "pin_slot", "mm", -5, 5, "jrig_pin_slot_limits", True), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_pin_slot_limit_history", _retire_design_state, False), None),
    ("joint_edit", {"joint_name": "JRig", "max_mm": -10},
     _refused("max_mm=-10", "min_mm=-5", "No edits applied", "assembly_get"), None),
    ("assembly_get", {"include": ["poses"]},
     _joint_limit_snapshot("JRig", "pin_slot", "mm", -5, 5, "jrig_pin_slot_limits", False), None),
    ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                     "max_results": 2000},
     _retire_compare("jrig_pin_slot_limit_history", _retire_design_state, True), None),
] + _crossing_rotation_rows("pin_slot") + [
    # Beside the kept custom rotation entity a frame-y slide lands; a frame-z request reads back x.
    ("joint_edit", {"joint_name": "JRig", "joint_type": "pin_slot", "slide_axis": "y"},
     lambda p: p.get("edited") is True and p.get("axis") == "custom" and p.get("slide_axis") == "y"
     and p.get("axis_kept") is True, None),
    ("sys_execute_script", {"script": _JRIG_HEADING, "read_only": True}, _jrig_custom_slide("y"), None),
    ("joint_edit", {"joint_name": "JRig", "joint_type": "pin_slot", "slide_axis": "z"},
     _refused("WAS EDITED", "axis=custom", "slide_axis=x", "reads back 'x'",
              "not the requested slide_axis 'z'", "assembly_get"), None),
    ("sys_execute_script", {"script": _JRIG_HEADING, "read_only": True}, _jrig_custom_slide("x"), None),
    ("joint_edit", {"joint_name": "JRig", "joint_type": "pin_slot", "axis": "y",
                    "slide_axis": "y"}, "refused", None),
    ("joint_edit", {"joint_name": "JRig", "joint_type": "rigid"}, "ok", None),
    ("assembly_get", {}, _joint_is("JRig", "rigid"), None),
    # THE AXIS THE JOINT ALREADY CARRIES. Rigid motion answers no axis member at all, so a retype
    # naming none is refused rather than silently aimed at z - the two inputs that supply one are
    # named in the refusal.
    ("joint_edit", {"joint_name": "JRig", "joint_type": "revolute"},
     _refused("no current motion axis", "axis=x|y|z", "world_axis=x|y|z"), None),
    ("joint_edit", {"joint_name": "JRig", "joint_type": "revolute", "axis": "y"},
     _axis_landed("JRig", "revolute", "y"), None),
    # the heading the JOINT holds, parked for the two comparisons below - joint_edit never writes
    # this vector, so it is the witness the writer cannot be.
    ("assembly_get", {}, _joint_is("JRig", "revolute"),
     ("rig_axis", _recall("rig_axis", _joint_heading("JRig")))),
    # a retype with NO axis KEEPS that heading: the tool reads the joint's own direction instead of
    # defaulting to a frame axis.
    ("joint_edit", {"joint_name": "JRig", "joint_type": "cylindrical"},
     _axis_kept("JRig", "y"), None),
    ("assembly_get", {}, _joint_axis_vs("JRig", "cylindrical", "rig_axis", True), None),
    # an axis on its OWN re-aims the current motion, the way world_axis already does - and the
    # heading moves off the one recalled above, which is what says the re-aim landed.
    ("joint_edit", {"joint_name": "JRig", "axis": "x"},
     _axis_landed("JRig", "cylindrical", "x"), None),
    ("assembly_get", {}, _joint_axis_vs("JRig", "cylindrical", "rig_axis", False), None),
    # rigid takes no axis at all, so one handed to it is refused rather than dropped in silence.
    ("joint_edit", {"joint_name": "JRig", "joint_type": "rigid", "axis": "z"},
     _refused("not axis-based"), None),
    ("joint_edit", {"joint_name": "JRig", "joint_type": "rigid"}, "ok", None),
    ("assembly_get", {}, _joint_is("JRig", "rigid"), None),
    # A FLIP turns the arm over in place: 'moved' names the turn a translation-only census misses,
    # and the arm's own box, read separately, leaves its centre and comes back with the second flip.
    ("model_inspect", {"target": "IndRig:1"}, "ok",
     ("rig_center_z", _recall("rig_center_z", lambda p: p["center"]["z"]))),
    ("joint_edit", {"joint_name": "JRig", "flip": False}, _turned_over("IndRig:1"), None),
    ("model_inspect", {"target": "IndRig:1"}, _center_z_vs("rig_center_z", True), None),
    ("joint_edit", {"joint_name": "JRig", "flip": True}, _turned_over("IndRig:1"), None),
    ("model_inspect", {"target": "IndRig:1"}, _center_z_vs("rig_center_z", False), None),
] + _box("LnkA", ox=1400, oy=120, tint="#E5533C") + _box(
    "LnkB", ox=1400, oy=120, tint="#1E88E5", shape="disc") + [
    # A LINK PARTNER THAT HAS NEVER BEEN DRIVEN: the bench's own drive pass has already moved every
    # station, and the second-member guard reads the session drive registry - so the coupling below
    # needs one fresh revolute to refuse on.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("assembly_ground", {"occurrence": "LnkB:1", "ground_to_parent": True}, _grounded, None),
    ("joint_create", {"occurrence_one": "LnkA:1:top", "occurrence_two": "LnkB:1:top",
                      "joint_type": "revolute", "axis": "z", "name": "BenchLink"},
     _jointed("BenchLink"), None),
    # COUPLE the driven revolute station to it at ratio 2 - the DOF-fix step, across two chains
    # that share nothing.
    ("joint_motion_link", {"joint_one": "JRev", "joint_two": "BenchLink", "ratio": 2},
     _motion_linked("JRev", "BenchLink", False),
     ("bench_link", _recall("bench_link", lambda p: p["motion_link"]))),
    # A LINKED JOINT MAY NOT BE RE-AIMED. Changing a member's axis leaves the link reading 'Motion
    # Link joint DOF is wrong type', carrying no motion, and refusing setMotionData - so it cannot
    # be re-valued back, and the re-aim is refused before anything is written.
    ("joint_edit", {"joint_name": "JRev", "joint_type": "revolute", "axis": "x"},
     _refused("motion link", "joint_motion_link", "action='delete'"), None),
    # world_axis is the SAME change by another route: it swaps the joint's frame direction for a
    # CUSTOM one carrying a construction axis, which the enum alone cannot tell from a custom
    # direction the joint already holds - so the ENTITY is what the guard compares.
    ("joint_edit", {"joint_name": "JRev", "world_axis": "y"},
     _refused("motion link", "joint_motion_link"), None),
    # the boundary the refusal turns on: a re-set that KEEPS the axis AND the motion type leaves the
    # link healthy, so it lands - and the link read below proves the refusals above wrote nothing.
    ("joint_edit", {"joint_name": "JRev", "joint_type": "revolute", "axis": "z"},
     lambda p: _measured("the re-set joint reads healthy after the edit",
                         {"edited": p.get("edited"), "healthy": p.get("healthy"),
                          "health_error": p.get("health_error")},
                         p.get("edited") is True and p.get("healthy") is True), None),
    ("assembly_get", {"include": ["relations"]}, _link_healthy("bench_link"), None),
    # and the limits set on JRev above are still standing after this same-axis re-set.
    ("assembly_get", {}, _limits_survived("JRev", -45, 45), None),
    # every joint built above, counted off the design-wide walk by an independent read.
    ("assembly_get", {}, _joints_listed(10), None),
    # the relations LIFECYCLE: list, suppress round-trip, re-value the link (was_reversed
    # disclosed), the measured set_occurrences refusal, and a delete with the survivor re-list.
    # Both names are the ones the CREATING calls read back off their own relation - a motion link's
    # auto-name is session-global ('Motion Link 9' is a legal first link), and the vise's relations
    # sit ahead of these in the design's own list.
    ("assembly_get", {"include": ["relations"]},
     lambda p: p.get("relation_counts", {}).get("rigid_groups", 0) >= 1
     and p.get("relation_counts", {}).get("motion_links", 0) >= 1, None),
    ("assembly_edit_relations", lambda c: {"kind": "rigid_group", "name": _ctx_get(c, "bench_group", "the bench's rigid group"), "action": "suppress"},
     lambda p: p.get("is_suppressed") is True, None),
    ("assembly_edit_relations", lambda c: {"kind": "rigid_group", "name": _ctx_get(c, "bench_group", "the bench's rigid group"), "action": "unsuppress"},
     lambda p: p.get("is_suppressed") is False, None),
    ("assembly_edit_relations", lambda c: {"kind": "motion_link", "name": _ctx_get(c, "bench_link", "the bench's motion link"), "action": "set_values", "ratio": 3},
     lambda p: p.get("ratio") == 3.0 and "was_reversed" in p, None),
    # back to the 2:1 the bench link was built at, read back the same way the re-value above was.
    ("assembly_edit_relations", lambda c: {"kind": "motion_link", "name": _ctx_get(c, "bench_link", "the bench's motion link"), "action": "set_values", "ratio": 2},
     lambda p: p.get("ratio") == 2.0 and "was_reversed" in p, None),
    # One member is not a rigid group; the independent following read checks its members stayed.
    ("assembly_edit_relations", lambda c: {"kind": "rigid_group", "name": _ctx_get(c, "bench_group", "the bench's rigid group"), "action": "set_occurrences", "occurrences": ["GrpA:1"]},
     _refused("at least two occurrences", "Nothing was changed"), None),
    # the group the refusal named, found BY NAME in the design's own relation list, still counts the
    # two occurrences assembly_rigid_group built it from - the refusal wrote nothing.
    ("assembly_get", {"include": ["relations"]},
     lambda p: next((g["occurrence_count"] for g in p["relations"]["rigid_groups"]
                     if g.get("name") == _RECALL.get("bench_group")), None) == 2, None),
    ("assembly_edit_relations", {"kind": "rigid_group", "name": "NoSuchGroup", "action": "delete"}, "refused", None),
    # contact sets: the design-level lifecycle on a scratch set built from the bench's own parts -
    # create (>=2 distinct members), the single-member refusal, re-member, rename reading the LANDED
    # name back, a suppress round-trip, the two analysis flags (restored), and delete + re-list.
    ("assembly_edit_contacts", {"action": "create", "members": ["GrpA:1", "GrpB:1"]},
     lambda p: p.get("member_count") == 2 and bool(p.get("contact_set")),
     ("contact_set", lambda p: p["contact_set"])),
    ("assembly_edit_contacts", {"action": "create", "members": ["GrpA:1"]}, "refused", None),
    ("assembly_get", {"include": ["contacts"]},
     lambda p: p.get("contact_count", 0) >= 1 and "enabled" in p.get("contact_analysis", {}), None),
    ("assembly_edit_contacts", lambda c: {"action": "set_members", "name": _ctx_get(c, "contact_set", "contact set name"), "members": ["GrpA:1", "PinCameo:1"]},
     lambda p: p.get("member_count") == 2, None),
    ("assembly_edit_contacts", lambda c: {"action": "rename", "name": _ctx_get(c, "contact_set", "contact set name"), "new_name": "SweepContacts"},
     lambda p: str(p.get("contact_set", "")).startswith("SweepContacts"),
     ("contact_set", lambda p: p["contact_set"])),
    ("assembly_edit_contacts", lambda c: {"action": "suppress", "name": _ctx_get(c, "contact_set", "contact set name")},
     lambda p: p.get("is_suppressed") is True, None),
    ("assembly_edit_contacts", lambda c: {"action": "unsuppress", "name": _ctx_get(c, "contact_set", "contact set name")},
     lambda p: p.get("is_suppressed") is False, None),
    # scope is REFUSED while contact analysis is off - the platform raises '3 : Contact analysis is
    # disabled.' on the write - so the enable comes first and the design is left as it was found.
    ("assembly_edit_contacts", {"action": "set_analysis_scope", "scope": "contact_sets"}, "refused", None),
    ("assembly_edit_contacts", {"action": "enable_analysis"}, lambda p: p.get("analysis_enabled") is True, None),
    ("assembly_edit_contacts", {"action": "set_analysis_scope", "scope": "contact_sets"},
     lambda p: p.get("scope") == "contact_sets", None),
    # put the scope back to the design's own all_bodies BEFORE disabling: the flag is retained under
    # a disable and comes back on the next enable, so skipping this would leave the story document
    # carrying a contact_sets scope it never had.
    ("assembly_edit_contacts", {"action": "set_analysis_scope", "scope": "all_bodies"},
     lambda p: p.get("scope") == "all_bodies", None),
    ("assembly_edit_contacts", {"action": "disable_analysis"},
     lambda p: p.get("analysis_enabled") is False and p.get("scope") == "all_bodies", None),
    ("assembly_edit_contacts", {"action": "delete", "name": "NoSuchContactSet"}, "refused", None),
    ("assembly_edit_contacts", lambda c: {"action": "delete", "name": _ctx_get(c, "contact_set", "contact set name")},
     lambda p: p.get("deleted") is True, None),
    _watch("JointBase:1"),
    # DRIVE ON CAMERA, on the bench that carries a station per motion type: the revolute swung
    # inside the limits set above and the slider run out, both read back off the joint.
    ("joint_drive", {"joint_name": "JRev", "angle_deg": 40}, _driven_angle(40), None),
    ("joint_drive", {"joint_name": "JSld", "distance": 18}, _driven_slide(18), None),
    # JRev (a link member) is in the session drive registry, so driving its partner BenchLink must
    # REFUSE (the second-member guard). This is also the live proof that
    # MotionLink.jointOne/jointTwo resolve: a wrong property name would leave the partner lookup
    # blind and this drive would wrongly succeed, failing the row.
    ("joint_drive", {"joint_name": "BenchLink", "angle_deg": 10}, "refused", None),
    # the driven pose read back off the JOINTS themselves - the two drives above reported their own
    # value_now, and this is the second witness to the revolute's.
    ("assembly_get", {}, _joints_listed(10, {"JRev": 40}), None),
    ("assembly_inspect_interference", {}, _interference_measured, None),   # driven pose
    ("joint_drive", {"joint_name": "JRev", "angle_deg": 0}, _driven_angle(0), None),
    ("joint_drive", {"joint_name": "JSld", "distance": 0}, _driven_slide(0), None),
    ("assembly_inspect_interference", {}, _interference_measured, None),   # rest pose
    # THE SAME REFUSAL WITH THE PARTNER NAME AMBIGUOUS. Joint names are unique only within a
    # COMPONENT, so a second 'JRev' inside a sub-assembly makes BenchLink's partner name mean two
    # joints - and the safety reads have to be taken over BOTH of them. Every JRev beat above is
    # done, so the decoy lands after the last of them.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "AmbHost", "activate": True}, _made_component, None),
    ]
    + _box("AmbP", ox=1560, tint="#B28A4C")
    + _box("AmbQ", ox=1590, tint="#4C8AB2")
    + [
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # model_create_component builds at the ROOT whatever is active, so the two are RE-PARENTED into
    # the host: an as-built joint between two occurrences of one sub-assembly is owned by that
    # sub-assembly, and only there can its name sit beside the bench's without colliding.
    ("design_move_occurrence", {"occurrence": "AmbP:1", "into_component": "AmbHost"},
     lambda p: p.get("changed") is True
     and str(p.get("full_path", "")).startswith("AmbHost:1+"), None),
    ("design_move_occurrence", {"occurrence": "AmbQ:1", "into_component": "AmbHost"},
     lambda p: p.get("changed") is True
     and str(p.get("full_path", "")).startswith("AmbHost:1+"), None),
    ("joint_create_as_built", {"occurrence_one": "AmbHost:1+AmbP:1",
                               "occurrence_two": "AmbHost:1+AmbQ:1",
                               "geometry": "AmbHost:1+AmbQ:1:origin",
                               "joint_type": "revolute", "axis": "z", "name": "JRev"},
     lambda p: p.get("created") is True and p.get("joint") == "JRev", None),
    # Resolving that name to ONE joint is now impossible, and taking the miss for 'nothing driven,
    # pair plain' would let this drive through - both members of a linked pair, the sequence that
    # has killed the Fusion process. It refuses, naming what it could not resolve.
    ("joint_drive", {"joint_name": "BenchLink", "angle_deg": 10},
     _refused("names 2 joints", "did NOT read as wholly native"), None),
    # pose + constrain cameos (do not disturb the jointed bench).
    ("model_create_component", {"name": "PoseCameo", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "PoseS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 300, "y1": 100,
                                           "x2": 320, "y2": 120}],
                             "sketch_name": "PoseS"}, "ok", None),
    ("model_extrude", {"sketch_name": "PoseS", "profile_index": 0, "distance": 10}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # the cameo's first move, off a fresh occurrence still at the identity transform - so the
    # position read back off transform2 is the 40 mm this call composed onto it.
    ("assembly_move", {"occurrence": "PoseCameo:1", "dx": 40}, _moved_occurrence(40), None),
    # the pending pose is transient until captured: status sees it armed, and discard_pending throws
    # it away - the pending flag clears while the captured-marker collection is left exactly as it
    # was. The marker count is RECALLED rather than asserted at zero: the vise act captured the
    # clamped pose before this one ran, so what this beat is about is the count not MOVING.
    ("assembly_capture_position", {"action": "status"},
     lambda p: p.get("has_pending") is True and _num(p.get("snapshot_count")),
     ("snap_before", _recall("snap_before", lambda p: p["snapshot_count"]))),
    ("assembly_capture_position", {"action": "discard_pending"},
     lambda p: p.get("discarded") is True and p.get("has_pending") is False
     and p.get("snapshot_count") == _RECALL.get("snap_before"), None),
    # re-arm the move the capture below records - the discard consumed the first one. Where the
    # discard left the part is what this run measures, so only the read-back itself is asserted.
    ("assembly_move", {"occurrence": "PoseCameo:1", "dx": 40}, _moved_occurrence(), None),
    ("assembly_capture_position", {"action": "capture"}, _captured, None),
])
_MOTION += _box("ConA", ox=360, tint="#E5533C") + _box("ConB", ox=360, tint="#1E88E5", shape="disc") + [
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("assembly_constrain", {"snap_one": "ConA:1:bottom", "snap_two": "ConB:1:top", "flipped": True}, _constrained, None),
    ("design_recompute", {}, "ok", None),
] + _box("MateSeat", ox=460, tint="#6A1B9A") + _box("MateArm", ox=520, tint="#FDD835", shape="bar") + [
    # ONE CONSTRAINT, SEVERAL RELATIONSHIPS - the table in Fusion's own Constrain Components dialog,
    # where a single constraint FEATURE carries a row per geometry pair, each row with its own type,
    # offset and angle. That is how Fusion actually locates a part: a set solved TOGETHER, because one
    # face pair almost never fixes anything. The row above is the single-pair shorthand; this is the
    # set form.
    # The two rows take DIFFERENT freedoms, which is what makes the set solvable: a SEAT (the arm's
    # underside onto the seat block's top face, 2 mm proud, flipped so the two faces oppose) and a
    # TURN about it (30 deg between the two front faces). Two rows reaching for the SAME freedom
    # over-constrain instead - measured on a live document: a face-to-face mate plus a concentric on
    # one pair of discs computes with a WARNING, with and without the offset, and the tool refuses
    # rather than leave a warned constraint in the design.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    _watch(["MateSeat:1", "MateArm:1"]),
    # A relationship value that is not a number is refused, naming it, before any constraint input
    # is built; both parts and the constraint census read the same before and after.
    ("model_inspect", {"target": "MateArm:1", "include": ["default", "mass"], "per_body": True,
                       "accuracy": "very_high", "units": "mm"},
     _retire_compare("constrain_number_arm", _retire_material_state, False), None),
    ("model_inspect", {"target": "MateSeat:1", "include": ["default", "mass"], "per_body": True,
                       "accuracy": "very_high", "units": "mm"},
     _retire_compare("constrain_number_seat", _retire_material_state, False), None),
    ("assembly_get", {"include": ["relations"], "max_relations": 100},
     _retire_compare("constrain_number_relations", _constraint_names, False), None),
    ("assembly_constrain", {"relationships": [
        {"snap_one": "MateArm:1:bottom", "snap_two": "MateSeat:1:top", "flip": True, "offset": "2 mm"}]},
     _refused("'relationships[0].offset' must be a number; received '2 mm'.",
              "Nothing was constrained."), None),
    ("model_inspect", {"target": "MateArm:1", "include": ["default", "mass"], "per_body": True,
                       "accuracy": "very_high", "units": "mm"},
     _retire_compare("constrain_number_arm", _retire_material_state, True), None),
    ("model_inspect", {"target": "MateSeat:1", "include": ["default", "mass"], "per_body": True,
                       "accuracy": "very_high", "units": "mm"},
     _retire_compare("constrain_number_seat", _retire_material_state, True), None),
    ("assembly_get", {"include": ["relations"], "max_relations": 100},
     _retire_compare("constrain_number_relations", _constraint_names, True), None),
    ("assembly_constrain", {"relationships": [
        {"snap_one": "MateArm:1:bottom", "snap_two": "MateSeat:1:top", "flip": True, "offset": 2},
        {"snap_one": "MateArm:1:front", "snap_two": "MateSeat:1:front", "angle_deg": 30},
    ]},
     # BOTH ROWS IN ONE NUMBER. The count is read off the CREATED constraint, never echoed - a
     # constraint holding FEWER rows than were submitted is refused by the tool - and the rotation the
     # tool measures for itself is 180 - 30: the seat row's flip and the turn row's angle composed.
     # Neither row on its own produces 150.
     lambda p: _constrained(p) and _measured(
         "both relationship rows landed in ONE constraint, and both acted",
         {"relationship_count": p.get("relationship_count"),
          "relationships_submitted": p.get("relationships_submitted"),
          "moved": p.get("moved")},
         p.get("relationships_submitted") == 2 and p.get("relationship_count") >= 2
         and any(_near(m.get("rotation_deg"), 150.0, 0.5)
                 for m in (p.get("moved") or []))), None),
    ("design_recompute", {}, "ok", None),
    _watch("MateArm:1"),
    # THE TWO ROWS PROVEN BY THEIR EFFECTS, which is the only honest way to tell them apart: no read
    # publishes a per-row TYPE (the dialog's Type column has no counterpart on the wire), so a count
    # of two says two rows landed and nothing about what each one did. The arm's own bounding box
    # says both. Its underside sits 2 mm above the seat block's 10 mm top face - the seat row, read on
    # Z, the one axis the layout pass never moves - and a 34 x 10 mm bar turned 30 deg measures
    # 34.45 x 25.66 across the world axes, which is the turn row and nothing else.
    ("model_inspect", {"target": "MateArm:1"},
     lambda p: _measured("the seat row holds the arm 2 mm proud of a 10 mm block, the turn row has "
                         "it 30 deg off the world axes",
                         {"min_z": (p.get("min_point") or {}).get("z"),
                          "x": p.get("x"), "y": p.get("y")},
                         _near((p.get("min_point") or {}).get("z"), 12.0, 0.05)
                         and _near(p.get("x"), 34.445, 0.05)
                         and _near(p.get("y"), 25.660, 0.05)), None),
    # RESTRUCTURE: two more pin instances (they share the PinCameo component's geometry), one of
    # them re-parented under the bore cameo, then both removed so the bench is left as it was found.
    # Fusion numbers an instance from a per-component counter, so every path here is READ back,
    # never a predicted ':2'.
    ("design_add_instance", {"component": "PinCameo", "x": 60, "y": -60, "units": "mm"},
     lambda p: p.get("created") is True and p.get("component") == "PinCameo"
     and str(p.get("full_path", "")).startswith("PinCameo:"),
     ("pin_b", lambda p: p["full_path"])),
    # the SECOND call names the same component while two instances of it exist - the bare name that
    # would otherwise be ambiguous resolves because every candidate is an instance of ONE component.
    ("design_add_instance", {"component": "PinCameo", "x": 90, "y": -60, "units": "mm"},
     lambda p: p.get("created") is True
     and p.get("full_path") not in ("PinCameo:1", None), ("pin_c", lambda p: p["full_path"])),
    ("design_get", {"include": ["tree"]}, "ok", None),
    # the re-parent: the browser path changes, the world position does not.
    ("design_move_occurrence", lambda c: {"occurrence": _ctx_get(c, "pin_b", "the second pin"),
                                          "into_component": "BoreCameo:1"},
     lambda p: p.get("changed") is True and str(p.get("full_path", "")).startswith("BoreCameo:1+")
     and p.get("world_position_preserved") is True, ("pin_b", lambda p: p["full_path"])),
    # there is no root target: the API moves an occurrence into another OCCURRENCE, so the direction
    # is refused by name instead of being attempted and failing inside Fusion.
    ("design_move_occurrence", lambda c: {"occurrence": _ctx_get(c, "pin_b", "the second pin"),
                                          "into_component": "root"}, "refused", None),
    # a component may not hold an instance of itself, on either tool.
    ("design_add_instance", {"component": "BoreCameo", "into_component": "BoreCameo:1"},
     "refused", None),
    ("design_move_occurrence", {"occurrence": "BoreCameo:1", "into_component": "BoreCameo:1"},
     "refused", None),
    ("design_delete_occurrence", lambda c: {"occurrence": _ctx_get(c, "pin_b", "the second pin")},
     "ok", None),
    ("design_delete_occurrence", lambda c: {"occurrence": _ctx_get(c, "pin_c", "the third pin")},
     "ok", None),
]

# FSAE-0922-MULTI-DRIVE-1: a design_recompute can change an UNCAPTURED driven joint's pose,
# proven on its own scratch document - a bare recompute run against the bench above would also
# reset JRev and JSld, rippling into every later beat that reads them.
_MOTION += [
    ("doc_get", {}, _home_document, ("reset_story", _recall("reset_story", _home_address))),
    ("doc_new", lambda c: {"expect_document": _ctx_get(c, "reset_story", "the story document")},
     _new_document,
     ("reset_scratch", _recall("reset_scratch", lambda p: p["document_handle"]))),
    ("param_add", {"name": "RstHeight", "expression": "10 mm", "unit": "mm"},
     lambda p: p.get("added") is True
     and (p.get("parameter") or {}).get("name") == "RstHeight", None),
] + [
    # the draw rows take CALLABLE args so the layout pass does not hoist these sketches into the
    # story document's sketch phase - this rig lives on the scratch document doc_new just opened
    (t, ((lambda a: (lambda c: a))(args) if t == "sketch_add_geometry" else
         (lambda c, a=args: {**a, "distance": "RstHeight"})
         if t == "model_extrude" and args.get("sketch_name") == "RstArmS" else args), e, s)
    for t, args, e, s in (_box("RstBase") + _box("RstArm", ox=60)
                          + _box("RstBase2", oy=60) + _box("RstArm2", ox=60, oy=60))
] + [
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("joint_create", {"occurrence_one": "RstArm:1:top", "occurrence_two": "RstBase:1:top",
                      "joint_type": "revolute", "axis": "z", "name": "RstRev"},
     _jointed("RstRev"), None),
    # A second, independent pair whose edits recompute the design under RstRev's drive.
    ("joint_create", {"occurrence_one": "RstArm2:1:top", "occurrence_two": "RstBase2:1:top",
                      "joint_type": "revolute", "axis": "z", "name": "RstRev2"},
     _jointed("RstRev2"), None),
    ("joint_drive", {"joint_name": "RstRev", "angle_deg": 30}, _driven_angle(30), None),
    # UNCAPTURED: the bare recompute reads the pose right back off the joint at 0, naming RstRev.
    ("design_recompute", {},
     lambda p: p.get("driven_joints_reset") == [
         {"name": "RstRev", "before": {"angle_deg": 30.0}, "after": {"angle_deg": 0.0}}]
     and "RstRev" in (p.get("note") or "")
     and "Observed value changes" in (p.get("note") or "")
     and "If the pose is uncaptured" in (p.get("note") or "")
     and "cause is not identified" in (p.get("note") or ""), None),
    # This measured parameter-driven extrusion edit changes the same joint value independently.
    ("joint_drive", {"joint_name": "RstRev", "angle_deg": 30}, _driven_angle(30), None),
    ("assembly_get", {}, lambda p: p.get("is_healthy") is True
     and _joints_listed(1, {"RstRev": 30})(p), None),
    ("param_set", {"name": "RstHeight", "expression": "12 mm"},
     lambda p: p.get("set") is True
     and p.get("driven_joints_reset") == [
         {"name": "RstRev", "before": {"angle_deg": 30.0}, "after": {"angle_deg": 0.0}}]
     and "Observed value changes" in (p.get("note") or "")
     and "If the pose is uncaptured" in (p.get("note") or "")
     and "cause is not identified" in (p.get("note") or ""), None),
    ("assembly_get", {}, lambda p: p.get("is_healthy") is True
     and _joints_listed(1, {"RstRev": 0})(p), None),
    ("joint_drive", {"joint_name": "RstRev", "angle_deg": 30}, _driven_angle(30), None),
    # joint_edit's own recompute, on the OTHER joint, resets the uncaptured drive and says so.
    ("joint_edit", {"joint_name": "RstRev2", "min_deg": -15},
     lambda p: p.get("edited") is True and p.get("driven_joints_reset") == [
         {"name": "RstRev", "before": {"angle_deg": 30.0}, "after": {"angle_deg": 0.0}}]
     and "RstRev" in (p.get("note") or "") and "Observed value changes" in (p.get("note") or ""), None),
    ("assembly_get", {}, _joints_listed(1, {"RstRev": 0}), None),
    ("joint_drive", {"joint_name": "RstRev", "angle_deg": 30}, _driven_angle(30), None),
    ("assembly_capture_position", {"action": "capture"}, _captured, None),
    # CAPTURED: the same recompute now leaves the pose alone, and the design's own joint walk
    # agrees - an independent witness beside the tool's own driven_joints_reset omission.
    ("design_recompute", {}, lambda p: p.get("driven_joints_reset") is None, None),
    ("assembly_get", {}, _joints_listed(1, {"RstRev": 30}), None),
    ("joint_edit", {"joint_name": "RstRev2", "min_deg": -20},
     lambda p: p.get("edited") is True and "driven_joints_reset" not in p, None),
    ("assembly_get", {}, _joints_listed(1, {"RstRev": 30}), None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "reset_story", "the story document"),
                                "expect_document": _ctx_get(c, "reset_scratch",
                                                            "the driven-reset scratch")},
     "ok", None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "reset_scratch", "the driven-reset scratch"),
                             "save_changes": False,
                             "expect_document": _ctx_get(c, "reset_story", "the story document")},
    _document_closed, None),
]

# ASSEMBLY-FIRST-OCCURRENCE-CAPTURE-REVERT-1: first root child's pending pose can be lost on
# capture while ground-to-parent; a second root child keeps its separate pending pose.
_MOTION += [
    ("doc_get", {"max_results": 1000}, _home_document,
     ("capture_story", _recall("capture_story", _home_address))),
    ("doc_new", lambda c: {"expect_document": _ctx_get(c, "capture_story", "the story document")},
     _new_document, ("capture_locked", _recall("capture_locked", lambda p: p["document_handle"]))),
] + [
    (t, (lambda a: (lambda c: a))(args) if t == "sketch_add_geometry" else args, e, s)
    for t, args, e, s in _box("CapA") + _box("CapB", ox=40)
] + [
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("assembly_get", {"include": ["poses"]},
     lambda p: (lambda r: _measured("two fresh root children, first ground-to-parent",
                                   {n: (v.get("ground_to_parent"), v.get("origin"))
                                    for n, v in r.items()},
                                   len(r) == 2 and r.get("CapA:1", {}).get("ground_to_parent") is True
                                   and r.get("CapA:1", {}).get("origin") == [0, 0, 0]
                                   and r.get("CapB:1", {}).get("origin") == [0, 0, 0]))(
         {r.get("name"): r for r in p.get("occurrences") or []}), None),
    ("assembly_move", {"occurrence": "CapB:1", "dx": 40},
     lambda p: p.get("moved") is True and "first root occurrence" not in (p.get("note") or ""), None),
    ("assembly_move", {"occurrence": "CapA:1", "dx": 100, "dy": 200, "rotate_deg": 30},
     lambda p: _measured("locked first-root move discloses capture risk",
                         {"moved": p.get("moved"), "position": p.get("position"),
                          "note": p.get("note")},
                         p.get("moved") is True
                         and "'CapA:1' is the first root occurrence and is ground-to-parent"
                         in (p.get("note") or "")
                         and "capture can reset this pending move" in (p.get("note") or "")
                         and "assembly_ground(occurrence='CapA:1', ground_to_parent=false)"
                         in (p.get("note") or "")), None),
    ("assembly_get", {"include": ["poses"]},
     lambda p: (lambda r: _measured("locked A and later B have separate placed poses",
                                   {n: (v.get("origin"), v.get("x_axis")) for n, v in r.items()},
                                   len(r) == 2 and r.get("CapA:1", {}).get("origin") == [100, 200, 0]
                                   and r.get("CapA:1", {}).get("x_axis") == [0.866, 0.5, 0]
                                   and r.get("CapB:1", {}).get("origin") == [40, 0, 0]
                                   and r.get("CapB:1", {}).get("x_axis") == [1, 0, 0]))(
         {r.get("name"): r for r in p.get("occurrences") or []}), None),
    ("assembly_capture_position", {"action": "capture"},
     _refused("MOVED 1 occurrence(s)", "CapA:1", "does NOT hold"), None),
    ("assembly_get", {"include": ["poses"]},
     lambda p: (lambda r: _measured("capture reverts only locked first A, later B stays placed",
                                   {n: (v.get("origin"), v.get("x_axis")) for n, v in r.items()},
                                   len(r) == 2 and r.get("CapA:1", {}).get("origin") == [0, 0, 0]
                                   and r.get("CapA:1", {}).get("x_axis") == [1, 0, 0]
                                   and r.get("CapB:1", {}).get("origin") == [40, 0, 0]
                                   and r.get("CapB:1", {}).get("x_axis") == [1, 0, 0]))(
         {r.get("name"): r for r in p.get("occurrences") or []}), None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "capture_story", "the story document"),
                                "expect_document": _ctx_get(c, "capture_locked", "the locked scratch")},
     "ok", None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "capture_locked", "the locked scratch"),
                             "save_changes": False,
                             "expect_document": _ctx_get(c, "capture_story", "the story document")},
     _document_closed, None),
    ("doc_new", lambda c: {"expect_document": _ctx_get(c, "capture_story", "the story document")},
     _new_document,
     ("capture_released", _recall("capture_released", lambda p: p["document_handle"]))),
] + [
    (t, (lambda a: (lambda c: a))(args) if t == "sketch_add_geometry" else args, e, s)
    for t, args, e, s in _box("CapA") + _box("CapB", ox=40)
] + [
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("assembly_get", {"include": ["poses"]},
     lambda p: (lambda r: _measured("released-control starts with locked first A",
                                   {n: (v.get("ground_to_parent"), v.get("origin"))
                                    for n, v in r.items()},
                                   len(r) == 2 and r.get("CapA:1", {}).get("ground_to_parent") is True
                                   and r.get("CapA:1", {}).get("origin") == [0, 0, 0]))(
         {r.get("name"): r for r in p.get("occurrences") or []}), None),
    ("assembly_ground", {"occurrence": "CapA:1", "ground_to_parent": False},
     lambda p: p.get("isGroundToParent") is False, None),
    ("assembly_move", {"occurrence": "CapA:1", "dx": 100, "dy": 200, "rotate_deg": 30},
     lambda p: p.get("moved") is True and "first root occurrence" not in (p.get("note") or ""), None),
    ("assembly_get", {"include": ["poses"]},
     lambda p: (lambda r: _measured("released A placed before capture; B remains at home",
                                   {n: (v.get("ground_to_parent"), v.get("origin"), v.get("x_axis"))
                                    for n, v in r.items()},
                                   len(r) == 2 and r.get("CapA:1", {}).get("ground_to_parent") is False
                                   and r.get("CapA:1", {}).get("origin") == [100, 200, 0]
                                   and r.get("CapA:1", {}).get("x_axis") == [0.866, 0.5, 0]
                                   and r.get("CapB:1", {}).get("origin") == [0, 0, 0]))(
         {r.get("name"): r for r in p.get("occurrences") or []}), None),
    ("assembly_capture_position", {"action": "capture"}, _captured, None),
    ("assembly_get", {"include": ["poses"]},
     lambda p: (lambda r: _measured("released A pose survives capture; B stays at home",
                                   {n: (v.get("ground_to_parent"), v.get("origin"), v.get("x_axis"))
                                    for n, v in r.items()},
                                   len(r) == 2 and r.get("CapA:1", {}).get("ground_to_parent") is False
                                   and r.get("CapA:1", {}).get("origin") == [100, 200, 0]
                                   and r.get("CapA:1", {}).get("x_axis") == [0.866, 0.5, 0]
                                   and r.get("CapB:1", {}).get("origin") == [0, 0, 0]
                                   and r.get("CapB:1", {}).get("x_axis") == [1, 0, 0]))(
         {r.get("name"): r for r in p.get("occurrences") or []}), None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "capture_story", "the story document"),
                                "expect_document": _ctx_get(c, "capture_released",
                                                            "the released scratch")},
     "ok", None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "capture_released", "the released scratch"),
                             "save_changes": False,
                             "expect_document": _ctx_get(c, "capture_story", "the story document")},
     _document_closed, None),
]

def _joint_identity_pose_snapshot(p):
    """Return the complete seven-placement public pose census in millimetres."""
    rows = p.get("all_occurrences")
    expected = {"IdParent:1", "IdParent:2", "IdParent:1+IdArm:1", "IdParent:1+IdTip:1",
                "IdParent:2+IdArm:1", "IdParent:2+IdTip:1", "IdBase:1"}
    valid = (p.get("units") == "mm" and p.get("is_healthy") is True
             and p.get("occurrence_count") == 3 and p.get("all_occurrence_count") == 7
             and p.get("all_occurrences_truncated") is False
             and p.get("occurrences_truncated") is False and p.get("joints_truncated") is False
             and p.get("joint_count") == 2 and isinstance(p.get("joints"), list)
             and {joint.get("name") for joint in p["joints"]} == {"IdPivot", "IdLock"}
             and p.get("broken_joints") == p.get("broken_relations") == p.get("unresolved_references") == []
             and isinstance(rows, list) and len(rows) == 7)
    state = {}
    if valid:
        for row in rows:
            path = row.get("full_path")
            if (path not in expected or path in state or row.get("unresolved")
                    or row.get("body_count") != (0 if path.startswith("IdParent:") and "+" not in path else 1)
                    or not isinstance(row.get("origin"), list) or len(row["origin"]) != 3
                    or any(not isinstance(row.get(axis), list) or len(row[axis]) != 3
                           for axis in ("x_axis", "y_axis", "z_axis"))):
                valid = False
                break
            fields = ["body_count", "origin", "x_axis", "y_axis", "z_axis"]
            if row["body_count"]:
                if (not isinstance(row.get("bbox_center"), list) or len(row["bbox_center"]) != 3
                        or not isinstance(row.get("bbox_size"), list) or len(row["bbox_size"]) != 3):
                    valid = False
                    break
                fields += ["bbox_center", "bbox_size"]
            if any(not _num(value) or not math.isfinite(value) for field in fields if field != "body_count"
                   for value in row[field]):
                valid = False
                break
            state[path] = {key: row.get(key) for key in fields}
        valid = valid and set(state) == expected
    return state if valid else None


def _joint_identity_pose(stage):
    """Independently read placed poses and prove the driven child, rigid tip and unchanged twin."""
    def check(p):
        state = _joint_identity_pose_snapshot(p)
        before = _RECALL.get("joint_identity_before")
        after = _RECALL.get("joint_identity_after")
        valid = state is not None
        if stage == "before":
            valid = valid and before is None and after is None
            if valid:
                _RECALL["joint_identity_before"] = state
        elif stage == "after":
            valid = valid and before is not None and after is None
            if valid:
                arm_delta = math.dist(state["IdParent:1+IdArm:1"]["bbox_center"],
                                      before["IdParent:1+IdArm:1"]["bbox_center"])
                tip_delta = math.dist(state["IdParent:1+IdTip:1"]["bbox_center"],
                                      before["IdParent:1+IdTip:1"]["bbox_center"])
                static = ("IdParent:1", "IdParent:2", "IdParent:2+IdArm:1",
                          "IdParent:2+IdTip:1", "IdBase:1")
                valid = (_near(arm_delta, 20.7055, 0.03) and _near(tip_delta, 41.4110, 0.03)
                         and all(state[path] == before[path] for path in static))
                if valid:
                    _RECALL["joint_identity_after"] = state
        else:
            valid = valid and before is not None and after is not None and state == before
            if valid:
                pivots = [row for row in p.get("joints") or [] if row.get("name") == "IdPivot"]
                valid = (len(pivots) == 1 and pivots[0].get("healthy") is True
                         and _near((pivots[0].get("value_now") or {}).get("angle_deg"), 0, 1e-4))
        return _measured(f"complete public placed-pose census {stage} drive", state, valid)
    return check


def _joint_identity_drive(p):
    """Check the bounded drive report names the rigidly carried tip and qualifies its scan."""
    scope = p.get("motion_scope") or {}
    rows = p.get("other_moved")
    moved = p.get("moved") or {}
    valid = (p.get("driven") is True and p.get("joint") == "IdPivot"
             and _near((p.get("value_now") or {}).get("angle_deg"), 30, 1e-4)
             and moved.get("occurrence") == "IdParent:1+IdArm:1"
             and scope.get("complete") is True and scope.get("total_occurrences") == 7
             and scope.get("sampled_occurrences") == 5 and scope.get("cap") == 200
             and scope.get("truncated") is False and scope.get("broken_occurrences") == 0
             and scope.get("unread") == [] and isinstance(rows, list) and len(rows) == 1)
    if valid:
        tip = rows[0]
        valid = (tip.get("occurrence") == "IdParent:1+IdTip:1"
                 and tip.get("under_joint_member") is False
                 and _near(tip.get("delta_deg"), 30, 0.02)
                 and _near(tip.get("geometry_moved_mm"), 35.6699, 0.03))
    return _measured("joint drive reports the rigidly carried tip and complete bounded scope", p, valid)


def _joint_identity_home_drive(p):
    """Check the reset drive returned the same revolute joint to zero."""
    value = (p.get("value_now") or {}).get("angle_deg")
    return _measured("IdPivot home drive", {"joint": p.get("joint"), "value_now": p.get("value_now")},
                     p.get("driven") is True and p.get("joint") == "IdPivot"
                     and _num(value) and _mod360(value, 0) < 1e-4)


def _joint_identity_rows():
    """Drive one nested placement and independently verify its rigid child and untouched twin."""
    rows = [("doc_get", {}, _home_document, ("joint_identity_home", _home_address)),
            ("doc_new", {}, _new_document, ("joint_identity_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]
    def write(tool, args, check="ok"):
        rows.append((tool, lambda c, a=args: {**a, "expect_document":
                     _ctx_get(c, "joint_identity_doc", "owned nested joint scene")}, check, None))
    write("model_create_component", {"name": "IdParent", "activate": True}, _made_component)
    for name, rect in (("IdArm", (30, 5, 70, 15)), ("IdTip", (80, 5, 100, 15))):
        write("model_create_component", {"name": name, "activate": True, "parent": "IdParent:1"}, _made_component)
        sketch = name + "Sketch"
        write("sketch_create", {"name": sketch, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": sketch, "units": "mm", "geometry": [
            {"kind": "rectangle", "x1": rect[0], "y1": rect[1], "x2": rect[2], "y2": rect[3]}]})
        write("model_extrude", {"sketch_name": sketch, "distance": 10, "units": "mm", "operation": "new"}, _extruded)
        write("assembly_ground", {"occurrence": f"IdParent:1+{name}:1", "ground_to_parent": False},
              lambda p: p.get("isGroundToParent") is False)
    write("design_add_instance", {"component": "IdParent:1", "x": 200, "units": "mm"},
          lambda p: p.get("created") is True and p.get("full_path") == "IdParent:2")
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "IdBase", "activate": True}, _made_component)
    write("sketch_create", {"name": "IdBaseSketch", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "IdBaseSketch", "units": "mm", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}]})
    write("model_extrude", {"sketch_name": "IdBaseSketch", "distance": 10, "units": "mm", "operation": "new"}, _extruded)
    write("assembly_ground", {"occurrence": "IdBase:1", "ground_to_parent": True}, _grounded)
    write("joint_create_as_built", {"occurrence_one": "IdParent:1+IdArm:1", "occurrence_two": "IdBase:1",
          "geometry": "IdBase:1:top", "joint_type": "revolute", "axis": "z", "name": "IdPivot"}, _as_built)
    write("joint_create_as_built", {"occurrence_one": "IdParent:1+IdTip:1", "occurrence_two": "IdParent:1+IdArm:1",
          "joint_type": "rigid", "name": "IdLock"}, _as_built)
    assembly = {"include": ["poses", "all_occurrences"], "units": "mm", "max_joints": 100,
                "max_occurrences": 100, "max_all_occurrences": 100}
    rows.append(("assembly_get", assembly, _joint_identity_pose("before"), None))
    write("joint_drive", {"joint_name": "IdPivot", "angle_deg": 30}, _joint_identity_drive)
    rows.append(("assembly_get", assembly, _joint_identity_pose("after"), None))
    write("joint_drive", {"joint_name": "IdPivot", "angle_deg": 0}, _joint_identity_home_drive)
    rows.append(("assembly_get", assembly, _joint_identity_pose("home"), None))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "joint_identity_home", "home"),
                                         "expect_document": _ctx_get(c, "joint_identity_doc", "owned scene")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "joint_identity_doc", "owned scene"),
                                      "save_changes": False,
                                      "expect_document": _ctx_get(c, "joint_identity_home", "home")}, _document_closed, None),
             ("doc_get", {}, _home_document, None)]
    return rows


_GROUND_FRAME_SETUP = """import adsk.core, adsk.fusion, json, math
def run(context):
    app = adsk.core.Application.get()
    assert not app.activeDocument.isSaved
    root = adsk.fusion.Design.cast(app.activeProduct).rootComponent
    assert root.occurrences.count == root.bRepBodies.count == root.sketches.count == 0
    def matrix(x, y, z, deg):
        m = adsk.core.Matrix3D.create()
        assert m.setToRotation(math.radians(deg), adsk.core.Vector3D.create(0, 0, 1),
                               adsk.core.Point3D.create(0, 0, 0))
        m.translation = adsk.core.Vector3D.create(x, y, z)
        return m
    host = root.occurrences.addNewComponent(matrix(10, 20, 5, 90))
    host.component.name = 'GroundHost'
    leaf = host.component.occurrences.addNewComponent(matrix(2, 3, 4, 30))
    leaf.component.name = 'GroundLeaf'
    comp = leaf.component
    sk = comp.sketches.add(comp.xYConstructionPlane)
    sk.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0, 0, 0),
                                                   adsk.core.Point3D.create(1, 2, 0))
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    extent = adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByReal(3))
    assert inp.setOneSideExtent(extent, adsk.fusion.ExtentDirections.PositiveExtentDirection)
    assert ex.add(inp) is not None
    print(json.dumps({'root_count': root.occurrences.count, 'body_count': comp.bRepBodies.count,
                      'volume_cm3': comp.bRepBodies.item(0).volume}))
"""


def _ground_frame_poses(origin, grounded):
    """Check the placed origin and the asymmetric body's independent world bounds."""
    def check(p):
        rows = p.get('all_occurrences') or []
        hosts = [r for r in rows if r.get('full_path') == 'GroundHost:1']
        leaves = [r for r in rows if r.get('full_path') == 'GroundHost:1+GroundLeaf:1']
        valid = (p.get('units') == 'mm' and p.get('all_occurrences_truncated') is False
                 and p.get('occurrence_count') == 1 and p.get('all_occurrence_count') == len(rows) == 2
                 and len(hosts) == len(leaves) == 1 and hosts[0].get('origin') == [100, 200, 50])
        if valid:
            leaf = leaves[0]
            center = [origin[0] - 11.160254, origin[1] - .669873, origin[2] + 15]
            valid = (leaf.get('origin') == origin and leaf.get('ground_to_parent') is grounded
                     and leaf.get('body_count') == 1
                     and len(leaf.get('bbox_center') or []) == len(leaf.get('bbox_size') or []) == 3
                     and all(_near(a, b, .01) for a, b in zip(leaf['bbox_center'], center))
                     and all(_near(a, b, .01) for a, b in zip(leaf['bbox_size'], [22.320508, 18.660254, 30])))
        return _measured('placed grounding origin and own-body world bounds', p, valid)
    return check


def _ground_frame_rows(mode):
    """Release, move and re-lock a rotated nested placement in both design modes."""
    initial, moved = [70, 220, 90], [140, 200, 100]
    final = initial if mode == 'parametric' else moved
    path = 'GroundHost:1+GroundLeaf:1'
    poses = {'include': ['poses', 'all_occurrences'], 'units': 'mm', 'max_all_occurrences': 10}
    def ground(before, after, flag):
        return lambda p: (p.get('isGroundToParent') is flag and p.get('position_read') == {
            'coordinate_space': 'world', 'before_mm': before, 'after_mm': after})
    def relocked(p):
        reset = {'coordinate_space': 'world', 'from_mm': moved, 'to_mm': final}
        return (ground(moved, final, True)(p)
                and (p.get('position_reset') == reset if mode == 'parametric'
                     else 'position_reset' not in p and 'position_warning' not in p))
    return _scratch('ground_frames_' + mode, [
        ('design_set_mode', {'target': mode, 'confirm_history_loss': mode == 'direct'},
         lambda p: (p.get('now') == mode or p.get('converted') is False
                    and p.get('from') == p.get('to') == mode), None),
        ('sys_execute_script', {'script': _GROUND_FRAME_SETUP, 'read_only': False},
         lambda p: p.get('root_count') == p.get('body_count') == 1 and _near(p.get('volume_cm3'), 6, .0001), None),
        ('assembly_get', poses, _ground_frame_poses(initial, True), None),
        ('assembly_ground', {'occurrence': 'GroundHost:1', 'ground_to_parent': True},
         ground([100, 200, 50], [100, 200, 50], True), None),
        ('assembly_get', poses, _ground_frame_poses(initial, True), None),
        ('assembly_ground', {'occurrence': path, 'ground_to_parent': False}, ground(initial, initial, False), None),
        ('assembly_get', poses, _ground_frame_poses(initial, False), None),
        ('assembly_move', {'occurrence': path, 'dx': 70, 'dy': -20, 'dz': 10, 'units': 'mm'},
         lambda p: p.get('moved') is True, None),
        ('assembly_get', poses, _ground_frame_poses(moved, False), None),
        ('assembly_ground', {'occurrence': path, 'ground_to_parent': True}, relocked, None),
        ('assembly_get', poses, _ground_frame_poses(final, True), None),
    ])


def _instance_frame_geometry(bounds):
    """Check the acquired occurrence's own-body world box and volume."""
    def check(p):
        mass = p.get('mass') or {}
        valid = (p.get('units') == mass.get('units') == 'mm'
                 and _near(mass.get('volume'), 6000, .001))
        for key, wanted in zip(('min_point', 'max_point'), bounds):
            point = p.get(key) or {}
            valid = valid and all(_near(point.get(axis), value, .01) for axis, value in zip('xyz', wanted))
        return _measured('instance own-body world box and volume', p, valid)
    return check


def _instance_frame_rows(mode):
    """Verify current local placement for both instance factories through world geometry."""
    source = 'GroundHost:1+GroundLeaf:1'
    original = [[47.679492, 210, 90], [70, 228.660254, 120]]
    landed = [[44.195296, 185, 49.047635], [75, 195, 84.689234]]
    inspection = {'units': 'mm', 'include': ['default', 'mass'], 'accuracy': 'very_high'}
    rows = [
        ('design_set_mode', {'target': mode, 'confirm_history_loss': mode == 'direct'},
         lambda p: (p.get('now') == mode or p.get('converted') is False
                    and p.get('from') == p.get('to') == mode), None),
        ('sys_execute_script', {'script': _GROUND_FRAME_SETUP, 'read_only': False},
         lambda p: p.get('root_count') == p.get('body_count') == 1 and _near(p.get('volume_cm3'), 6, .0001), None),
        ('model_inspect', {'target': source, **inspection}, _instance_frame_geometry(original), None),
    ]
    def placed(p):
        return (p.get('created') is True and isinstance(p.get('full_path'), str)
                and p['full_path'].startswith('GroundHost:1+') and p.get('position') == {
                    'x': -15, 'y': 25, 'z': 7.5}
                and p.get('axes') == {'x': [1, 0, 0], 'y': [0, .906308, -.422618],
                                       'z': [0, .422618, .906308]})
    for independent in (False, True):
        key = 'instance_frame_' + mode + ('_copy' if independent else '_shared')
        rows += [
            ('design_add_instance', {'component': source, 'into_component': 'GroundHost:1',
                'independent': independent, 'x': -15, 'y': 25, 'z': 7.5, 'units': 'mm',
                'rotate_deg': -25, 'rotate_axis': 'x'}, placed,
             (key, _recall(key, lambda p: p['full_path']))),
            ('model_inspect', lambda c, key=key: {'target': _ctx_get(c, key, 'acquired instance'), **inspection},
             _instance_frame_geometry(landed), None),
            ('model_inspect', {'target': source, **inspection}, _instance_frame_geometry(original), None),
        ]
    return _scratch('instance_frames_' + mode, rows)


_MOTION += _ground_frame_rows('parametric') + _ground_frame_rows('direct')
_MOTION += _instance_frame_rows('parametric') + _instance_frame_rows('direct')
_MOTION += _joint_identity_rows()
_MOTION += _selected_owner_rows()

_MOTION += _joint_failure_rows()
_MOTION += _placed_slider_rows()
_MOTION += _late_input_rows()
_MOTION += _asbuilt_axis_rows()
_MOTION += _drive_own_body_rows()
_MOTION += _nested_owner_rows()
_MOTION += _nested_relation_rows()
_MOTION += _rigid_edit_rows()
_MOTION += _pattern_pose_rows()
_MOTION += _crossindex_rows()
_MOTION += _reused_origin_rows()
_MOTION += _origin_consumer_rows()
_MOTION += _joint_preflight_rows()

# ACT 7: THE VISE - the billet the bracket is cut from, and the machine vise that holds it.
# Geometry contract (all mm; the Bracket occupies x[-60,60] y[-40,40] z[0,45] with its boss):
#   STOCK      x[-63,63] y[-43,43] z[-8,48]   - 3 mm all round, 8 mm of grip stock under the part
#   ViseBase   x[-95,95] y[-95,95] z[-40,-8]  - the stock and both jaws seat on its z=-8 top
#   JawFixed   x[-70,70] y[43,78]  z[-8,10]   - its grip face IS the stock's +y side
#   JawMoving  x[-70,70] y[-84,-49] z[-8,10]  - 6 mm open; the slider closes it onto y=-43
#   LeadScrew  r6 on the world Y axis, y[-117,-80], with a cross handle at y[-125,-117]
# The jaws top out at z=10 while every machined feature - the pocket floor at z=14, the bores and
# the boss above it - stands clear above them, which is what the 8 mm of grip stock buys.

def _plate(comp, sketch, z_offset, x1, y1, x2, y2, height):
    """Component + its own build plane at z_offset + one rectangle, extruded up by height.
    The plane lives INSIDE the component: sketch_create resolves construction-plane names in
    the ACTIVE component, so a root-level plane is invisible after activate."""
    plane = comp + "Floor"
    return [
        ("model_create_component", {"name": comp, "activate": True}, _made_component, None),
        ("model_construction", {"kind": "plane", "plane": "xy", "offset": z_offset,
                                "name": plane}, _datum_plane("xy"), None),
        ("sketch_create", {"plane": plane, "name": sketch}, "ok", None),
        ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": x1, "y1": y1,
                                               "x2": x2, "y2": y2}],
                                 "sketch_name": sketch}, "ok", None),
        ("model_extrude", {"sketch_name": sketch, "profile_index": 0, "distance": height},
         _extruded, None),
    ]


# The occurrences the clamped-fixture gate judges. assembly_inspect_interference takes no scope, so
# it reports the whole design - including the scratch cameos, whose own bodies overlap by design.
_FIXTURE_PARTS = {"Bracket:1", "STOCK:1", "ViseBase:1", "JawFixed:1", "JawMoving:1", "LeadScrew:1"}


def _fixture_rest_clean(p):
    """assembly_inspect_interference read over the FIXTURE: the only pair of it allowed to overlap
    is the part inside the billet it is cut from. A jaw biting the part, or a jaw into the base, is
    a fixture that does not hold, and the interference census is the only read that says so.

    A row naming the same occurrence twice is one cameo's own two bodies, and a row naming no
    fixture part belongs to a cameo rig - neither is this gate's business."""
    rows = (p.get("measured") or {}).get("interferences") or []
    strays = []
    for i in rows:
        a = (i.get("occurrence_one") or "").replace("/", "+").split("+")[-1]
        b = (i.get("occurrence_two") or "").replace("/", "+").split("+")[-1]
        if a == b or not ({a, b} & _FIXTURE_PARTS):
            continue
        if sorted([a, b]) != ["Bracket:1", "STOCK:1"]:
            strays.append(sorted([a, b]))
    return _interference_measured(p) and _measured(
        "the clamped fixture overlaps nowhere but part-in-billet",
        {"interference_count": (p.get("measured") or {}).get("interference_count"),
         "strays": strays[:4]}, not strays)


def _linked_screw_angle(joint, mm, deg_per_mm):
    """assembly_get: the screw's own driven value after the jaw was driven, read off the DESIGN's
    joint walk rather than off the drive that moved it.

    A motion link's whole claim is that driving one member carries the other, and the partner's
    stored value is the only read that shows it. The magnitude is the ratio times the jaw's travel;
    the SIGN is the platform's to pick from the two joints' own frames, so it is reported and the
    magnitude is what is asserted."""
    def check(p):
        row = next((j for j in (p.get("joints") or []) if j.get("name") == joint), None)
        got = ((row or {}).get("value_now") or {}).get("angle_deg")
        return _measured(f"'{joint}' turned {abs(mm * deg_per_mm)} deg with the jaw's {mm} mm",
                         {"joint": row and {"name": row.get("name"), "type": row.get("type"),
                                            "value_now": row.get("value_now")}},
                         _num(got) and _mod360(abs(got), abs(mm * deg_per_mm)) < 0.5)
    return check


_STOCK_VISE = (
    # THE BILLET FIRST, dressed before any of the fixture exists. Its look has to be settled before
    # the jaws are there to close on it - a stock that changes appearance halfway through the
    # clamping reads as the clamping doing it.
    _plate("STOCK", "StockS", -8, -63, -43, 63, 43, 56)
    + [
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
        ("appearance_set", {"target": "STOCK", "color": "#8D6E63"}, "ok", None),
        # HALF translucent, so the bracket inside stays visible through the billet it is cut from -
        # the whole point of the fixture shot is the part in the stock in the vise, and an opaque
        # billet hides the part. Opacity here is the browser's Opacity Control (Component.opacity),
        # NOT the appearance's transparency: the two are unrelated, and a fully opaque colour still
        # renders see-through under an opacity override. Read back off what actually RENDERS, since
        # the override is inherited from parent components.
        ("appearance_set", {"target": "STOCK:1", "opacity": 50},
         lambda p: p.get("opacity_rendered") == 50, None),
        # the billet measured against the part it encloses: the stated allowance is 3 mm a side, so
        # a 120 x 80 part comes out of a 126 x 86 billet.
        ("model_inspect", {"target": "STOCK:1"},
         lambda p: _measured("the billet is the part's box plus its allowance",
                             {"x": p.get("x"), "y": p.get("y"), "z": p.get("z")},
                             _near(p.get("x"), 126.0, 0.5) and _near(p.get("y"), 86.0, 0.5)), None),
    ]
    + _plate("ViseBase", "VBase", -40, -95, -95, 95, 95, 32)
    + _plate("JawFixed", "JFixS", -8, -70, 43, 70, 78, 18)
    + _plate("JawMoving", "JMovS", -8, -70, -84, 70, -49, 18)
    # THE LEAD SCREW, on the world Y axis so the revolute about 'y' spins it about its own centre
    # rather than orbiting it: a circle on an XZ plane, extruded along +Y, with a cross handle on
    # its outboard end. The handle is what makes the rotation readable - a plain cylinder turning
    # about its own axis shows nothing.
    + [
        ("model_create_component", {"name": "LeadScrew", "activate": True}, _made_component, None),
        ("model_construction", {"kind": "plane", "plane": "xz", "offset": -117,
                                "name": "ScrewPlane"}, _datum_plane("xz"), None),
        ("sketch_create", {"plane": "ScrewPlane", "name": "ScrewS"}, "ok", None),
        ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 6}],
                                 "sketch_name": "ScrewS"}, "ok", None),
        ("model_extrude", {"sketch_name": "ScrewS", "profile_index": 0, "distance": 37},
         _extruded, None),
        ("model_construction", {"kind": "plane", "plane": "xz", "offset": -125,
                                "name": "HandlePlane"}, _datum_plane("xz"), None),
        ("sketch_create", {"plane": "HandlePlane", "name": "HandleS"}, "ok", None),
        ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": -3, "y1": -30,
                                               "x2": 3, "y2": 30}],
                                 "sketch_name": "HandleS"}, "ok", None),
        ("model_extrude", {"sketch_name": "HandleS", "profile_index": 0, "distance": 8},
         _extruded, None),
    ]
) + [("design_activate_component", {"occurrence": "root"}, "ok", None)]

_VISE = _STOCK_VISE + [
    ("appearance_set", {"target": "ViseBase", "color": "#455A64"}, "ok", None),
    ("appearance_set", {"target": "JawFixed", "color": "#78909C"}, "ok", None),
    ("appearance_set", {"target": "JawMoving", "color": "#E5533C"}, "ok", None),
    ("appearance_set", {"target": "LeadScrew", "color": "#F5A623"}, "ok", None),
    # THE FIXTURE SKELETON. Every component here has its origin at the WORLD origin (geometry is
    # drawn in world coordinates), so a ':origin' snap aligns already-aligned frames - a positional
    # no-op, no teleport - and the slider/revolute axes ride that world-aligned frame.
    ("assembly_ground", {"occurrence": "ViseBase:1", "ground_to_parent": True}, _grounded, None),
    # the fixed side is ONE body as far as the machine is concerned: base plus fixed jaw.
    ("assembly_rigid_group", {"occurrences": ["ViseBase:1", "JawFixed:1"]},
     _rigid_grouped(2), None),
    ("joint_create", {"occurrence_one": "JawMoving:1:origin", "occurrence_two": "ViseBase:1:origin",
                      "joint_type": "slider", "axis": "y", "name": "JawSlide"},
     _jointed("JawSlide"), None),
    ("joint_create", {"occurrence_one": "LeadScrew:1:origin", "occurrence_two": "ViseBase:1:origin",
                      "joint_type": "revolute", "axis": "y", "name": "ScrewTurn"},
     _jointed("ScrewTurn"), None),
    # TRAVEL LIMITS on the jaw, wide enough for the open pose below and stopping where the jaw would
    # run off its own way. Every published limit is the value READ BACK off the live JointLimits.
    ("joint_edit", {"joint_name": "JawSlide", "min_mm": -10, "max_mm": 8},
     _joint_limits("JawSlide", min_mm=-10, max_mm=8), None),
    # the part in the stock, as-built rigid - the billet and what will be cut out of it are one
    # piece until the cutter says otherwise. The stock is NOT jointed to the base: a billet welded to
    # the vise body is not being held by anything, and the jaws closing on it would prove nothing.
    # What holds it is the grip, captured below once the jaw has actually closed.
    ("joint_create_as_built", {"occurrence_one": "Bracket:1", "occurrence_two": "STOCK:1"},
     _as_built, None),
    # THE LEAD SCREW COUPLED TO THE JAW: 45 degrees of handle per millimetre of travel. The ratio is
    # joint_two's motion per ONE unit of joint_one, each in its own display unit - deg here, mm
    # there - and 45 is chosen so the closing travel lands the screw on 270 deg: a revolute's value
    # reads modulo full turns, so a link angle that came out a multiple of 360 would be
    # indistinguishable from a link that carried nothing.
    ("joint_motion_link", {"joint_one": "JawSlide", "joint_two": "ScrewTurn", "ratio": 45},
     _motion_linked("JawSlide", "ScrewTurn", False), None),
    _watch(["ViseBase:1", "STOCK:1"]),
    # OPEN, then CLOSED, both read back off the joint - the vise is watched working rather than
    # found already shut. The open pose is held a beat and shot before the jaw comes in. The closing
    # 6 mm is the authored gap between the moving jaw's grip face (y=-49) and the billet side
    # (y=-43), so it lands the jaw flush rather than driving it into the part.
    ("joint_drive", {"joint_name": "JawSlide", "distance": -4}, _driven_slide(-4), None),
    _dwell(1.5),
    ("view_screenshot", {"view": "current", "width": 500, "height": 400}, "ok", None),
    ("joint_drive", {"joint_name": "JawSlide", "distance": 6}, _driven_slide(6), None),
    _dwell(1.5),
    # THE LINK TRANSMITTING, read off the PARTNER rather than off the drive that moved it: the jaw
    # travelled 6 mm, so the screw stands at 6 x 45 deg. This is what the coupling claims, and the
    # design's own joint walk is the witness the writer cannot be.
    ("assembly_get", {}, _linked_screw_angle("ScrewTurn", 6, 45), None),
    # GRIP VERIFIED BY MEASURE, not by trust, and BY NAME rather than by face handle - a handle-form
    # model_measure_between reads a distance the occurrence-name form disagrees with on this build
    # (ledger row MEASBTW-1), so the grip stands on the form whose answer is trusted.
    # The FIXED jaw's face is flush from birth and proves only that nothing moved it; the MOVING
    # jaw's is the load-bearing one, and its extent is read a second way below.
    ("model_measure_between", {"a": "JawFixed", "b": "STOCK"},
     lambda p: p.get("distance", 99) <= 0.1, None),
    ("model_measure_between", {"a": "JawMoving", "b": "STOCK"},
     lambda p: p.get("distance", 99) <= 0.1, None),
    # ...and the same grip as a POSITION: touching and penetrating both measure zero distance, so
    # the moving jaw's own box is read for where its grip face came to rest - y=-43 is the billet
    # side, and anything past it is a jaw inside the part.
    ("model_inspect", {"target": "JawMoving:1"},
     lambda p: _measured("the moving jaw closed ONTO the billet side, not past it",
                         {"max_point": p.get("max_point"), "min_point": p.get("min_point")},
                         _near((p.get("max_point") or {}).get("y"), -43.0, 0.05)), None),
    # A DRIVE LEAVES A TRANSIENT POSE, and a joint create is REFUSED while one is pending (it would
    # silently revert it). So the clamped pose is recorded into the timeline first - which is also
    # the right order physically: the jaw is closed, that closure is what the grip joint captures.
    ("assembly_capture_position", {"action": "capture"}, _captured, None),
    # THE GRIP ITSELF, taken only now that both faces measure closed onto the billet: an as-built
    # joint mates two occurrences WHERE THEY ALREADY ARE, so taking it here records the clamped pose
    # rather than creating it. ONE jaw takes the joint - jointing the stock to both jaws would close
    # the loop twice and be refused as over constrained (measured).
    ("joint_create_as_built", {"occurrence_one": "STOCK:1", "occurrence_two": "JawMoving:1",
                               "name": "GripJaw"},
     lambda p: _as_built(p) and _measured("the grip joint names the jaw it was taken on",
                                          {"joint": p.get("joint")}, p.get("joint") == "GripJaw"), None),
    # THE CLAMPED READ: nothing in the fixture overlaps but the part inside its own billet.
    ("assembly_inspect_interference", {}, _fixture_rest_clean, None),
    ("view_screenshot", {"width": 500, "height": 400}, "ok", None),
]

_VISE_CAPTURE = next(i for i, row in enumerate(_VISE)
                    if row[0] == "assembly_capture_position"
                    and isinstance(row[1], dict) and row[1].get("action") == "capture")
_VISE_SHOWCASE_POSE = _VISE[len(_STOCK_VISE):_VISE_CAPTURE + 1]
