# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The model detail act and its read-back predicates."""


from verify_core import (
    EXPORT_DIR, _RECALL, _activated, _axis_aligned_face_at, _box, _chamfered, _ctx_get, _cut_a_chain, _cut_exactly, _document_closed, _home_address, _home_document, _marker_parked_after, _datum_plane, _extent_measured, _extruded, _fg, _fgn, _filleted, _full_rounded, _holes_recognized, _holes_windowed, _made_component, _made_component_inactive, _matched, _measured, _mirrored, _moved, _near, _needs, _new_document, _num, _offset_faces, _param_added, _param_deleted, _param_set_to, _path_count, _piped, _pocket_boss, _pockets_recognized, _prof, _recall, _recognized_cbore_walls, _recognized_pocket_floor, _refused, _shelled, _split_bodies, _unless, _watch)
from verify_acts_cam import (
    MACHINING_EXTENSION)
from verify_core import _face_up_at
from verify_core import _jointed
from verify_core import _captured
from verify_acts_sketch import _body_facts, _unchanged
from verify_layout import (
    _px, _py)


_SHOT_PATH = EXPORT_DIR + "/w4_shot"


def _thread_body_facts(p):
    """Return complete thread-body measurements only at the reported very-high accuracy."""
    return (_body_facts(p) if (p.get("mass") or {}).get("accuracy_used") == "very_high"
            else None)


def _thread_material_cut(key):
    """Require an independently inspected threaded body to lose material from its banked baseline."""
    def check(p):
        before, after = _RECALL.get(key), _thread_body_facts(p)
        return _measured("modeled thread removes independently read material", after,
                         before is not None and after is not None
                         and 0 < after["volume"] < before["volume"] - .01)
    return check



from verify_acts_model_extrude_organization import (
    _BODY_ORGANIZATION, _EXTRUDE_EDITS)
from verify_acts_model_definition_operand import (
    _DATUM_OPERANDS, _DEFINITION_READS)
from verify_acts_model_precision import (
    _section_camera, _section_camera_unchanged, _section_census, _section_created, _section_named_clear)
from verify_acts_model_sweep import _retire_reads, _retire_material_state
from verify_acts_model_combine_revolve import _combine_pin
from verify_acts_datum_edit import _DATUM_EDITS
from verify_acts_feature_edit import feature_edit_rows
from verify_acts_feature_finishing import feature_finishing_rows
from verify_acts_feature_advanced import advanced_feature_edit_rows
from verify_acts_surface_boundaries import surface_boundary_edit_rows
from verify_acts_surface_edit import surface_feature_edit_rows


def _pipe_path_visibility(p):
    """Read the disjoint-cut path's visibility from the independent sketch listing."""
    rows = [r for r in p.get("sketches", []) if r.get("name") == "PipeJoinMissPath"]
    return _measured("PipeJoinMissPath remains visible", rows,
                     p.get("sketch_count") == len(p.get("sketches", []))
                     and p.get("truncated") is not True and len(rows) == 1
                     and rows[0].get("is_visible") is True and rows[0].get("line_count") == 1)


def _capture_scale_factor(p):
    feature = _RECALL.get("scale_expression_feature")
    rows = [r for r in (p.get("timeline") or {}).get("timeline", [])
            if r.get("name") == feature and r.get("component") == "ScaleExpressionWitness"]
    params = (rows[0].get("params") or []) if len(rows) == 1 else []
    matches = [r for r in params if r.get("role") == "ScaleFactor"]
    name = matches[0].get("name") if len(matches) == 1 else None
    if name:
        _RECALL["scale_expression_parameter"] = name
    return _measured("one scoped scale factor parameter", {"feature": feature, "rows": len(rows),
                     "matches": matches}, len(rows) == 1 and len(matches) == 1 and bool(name)
                     and matches[0].get("expression") == "1.5"
                     and _near(matches[0].get("value"), 1.5, 1e-6)
                     and _parameter_timeline_healthy(p))


def _scale_expression_state(volume, bounds):
    def check(p):
        mass = p.get("mass") or {}
        got_bounds = {f"{point}_{axis}": (p.get(point + "_point") or {}).get(axis)
                      for point in ("min", "max") for axis in "xyz"}
        good_bounds = all(_near(got_bounds.get(key), want, .05)
                          for key, want in bounds.items())
        return _measured("scale expression geometry read", {
            "volume_mm3": mass.get("volume"), "bounds_mm": got_bounds,
            "parameter": _RECALL.get("scale_expression_parameter")},
            _near(mass.get("volume"), volume, .02) and good_bounds)
    return check


def _capture_exact_user_parameters(p, expected=("ScaleWitnessK", "Wd")):
    rows = p.get("user_parameters") or []
    names = sorted(r.get("name") for r in rows if r.get("name"))
    return _measured("independent authored parameter list", {
        "count": p.get("user_parameter_count"), "returned": p.get("returned"), "names": names},
        names == sorted(expected) and p.get("user_parameter_count") == len(expected)
        and p.get("returned") == len(rows))


def _parameter_refusal_text(name):
    return _refused("Could not add '" + name + "'", "param name is not valid")


def _bodyref_scale_state(p):
    """Return independent scale-stock bounds and volume when every field reads."""
    mass = p.get("mass") or {}
    values = [p.get(axis) for axis in ("x", "y", "z")] + [mass.get("volume")]
    if (p.get("units") != "mm" or mass.get("accuracy_used") != "very_high"
            or not all(isinstance(v, (int, float)) and v > 0 for v in values)
            or not all(isinstance((p.get(key) or {}).get(axis), (int, float))
                       for key in ("min_point", "max_point") for axis in ("x", "y", "z"))):
        return None
    return {"values": values, "min": p["min_point"], "max": p["max_point"]}


def _bodyref_surface_state(p):
    """Return a complete single-surface tree and timeline for refusal comparison."""
    tree, timeline = p.get("tree") or {}, p.get("timeline") or {}
    node = tree.get("tree") or {}
    bodies = node.get("bodies") or []
    if (tree.get("truncated") is not False or node.get("body_count") != 1 or len(bodies) != 1
            or bodies[0].get("is_solid") is not False or not bodies[0].get("handle")
            or not timeline.get("timeline") or timeline.get("truncated")):
        return None
    return {"tree": tree, "timeline": timeline}


def _absolute_datum_position(kind, distance, name):
    """Check a datum's independently acquired geometry along either orientation of the seed edge."""
    def check(p):
        row = (p.get("matches") or [{}])[0]
        point, normal = row.get("position"), row.get("normal")
        valid = (p.get("match_count") == p.get("returned") == 1
                 and row.get("kind") == kind and row.get("name") == name
                 and isinstance(point, list) and len(point) == 3
                 and any(_near(point[0], _px("ShellCap", x), 0.001)
                         for x in (400 + distance, 430 - distance))
                 and _near(point[1], _py("ShellCap", 0), 0.001)
                 and _near(point[2], 0, 0.001))
        if kind == "construction_plane":
            valid = (valid and isinstance(normal, list) and len(normal) == 3
                     and _near(abs(normal[0]), 1, 0.000001)
                     and _near(normal[1], 0, 0.000001) and _near(normal[2], 0, 0.000001))
        return _measured("absolute datum identity, position and plane normal", row, valid)
    return check


def _absolute_datum_health(p):
    """Require every named absolute datum to be present with no timeline exception."""
    timeline = p.get("timeline") or {}
    names = {"AbsInsidePlane", "BeforeStartPlane", "PastEndPoint", "AtEndPlane"}
    present = {r.get("name") for r in timeline.get("timeline") or []}
    exceptions = (timeline.get("summary") or {}).get("exceptions")
    return _measured("absolute datum features remain healthy", timeline,
                     timeline.get("returned") == timeline.get("count")
                     and names <= present and isinstance(exceptions, list)
                     and set((timeline.get("summary") or {}).get("states") or {}) == {"healthy"}
                     and all(row.get("health", "healthy") == "healthy" for row in timeline.get("timeline") or []
                             if row.get("name") in names)
                     and not any(r.get("name") in names for r in exceptions))


def _face_point_timeline_snapshot(p):
    timeline = p.get("timeline") or {}
    rows = timeline.get("timeline") or []
    complete = (timeline.get("count") == timeline.get("returned")
                and timeline.get("truncated") is not True)
    return {
        "count": timeline.get("count"),
        "marker": timeline.get("marker_position"),
        "health_exceptions": (timeline.get("summary") or {}).get("exceptions"),
        "returned": timeline.get("returned"),
        "truncated": timeline.get("truncated") is True,
        "rows": [(r.get("index"), r.get("name"), r.get("type")) for r in rows],
        "complete": complete,
    }


def _capture_face_point_timeline(p):
    snap = _face_point_timeline_snapshot(p)
    _RECALL["face_point_timeline_before"] = snap
    return _measured("complete timeline before face-point refusal", snap,
                     snap["complete"] and snap["count"] == len(snap["rows"])
                     and snap["marker"] == snap["count"] and snap["health_exceptions"] == []
                     and not snap["truncated"])


def _same_face_point_timeline(p):
    snap = _face_point_timeline_snapshot(p)
    return _measured("timeline unchanged after face-point operation",
                     {"before": _RECALL.get("face_point_timeline_before"), "after": snap},
                     snap["complete"] and snap == _RECALL.get("face_point_timeline_before"))


def _face_point_mass(target, before_key=None, delta=None, restore_key=None):
    def check(p):
        mass = p.get("mass") or {}
        rows = mass.get("per_body") or []
        volume = mass.get("volume")
        body_volumes = [r.get("volume") for r in rows if r.get("is_solid") is True]
        readable = (len(body_volumes) == 1 and _num(volume) and _num(body_volumes[0])
                    and mass.get("per_body_count") == len(rows)
                    and mass.get("per_body_truncated") is False)
        if before_key:
            if readable:
                _RECALL[before_key] = volume
            passed = readable
        elif delta is not None:
            baseline = _RECALL.get(restore_key)
            passed = (readable and _num(baseline)
                      and abs((volume - baseline) - delta) < 2.0)
        else:
            baseline = _RECALL.get(restore_key)
            passed = readable and _num(baseline) and abs(volume - baseline) < 1e-4
        return _measured("independent single-body mass read", {
            "target": target, "volume_mm3": volume, "body_volumes_mm3": body_volumes,
            "baseline_mm3": _RECALL.get(restore_key) if restore_key else None,
            "expected_delta_mm3": delta}, passed)
    return check


def _face_point_cylinder(center, axis, span_axis, span, tol=0.5):
    def check(p):
        rows = p.get("matches") or []
        row = rows[0] if rows else {}
        got_axis, pos = row.get("axis"), row.get("position")
        direction_ok = (isinstance(got_axis, list) and len(got_axis) == 3
                        and all(_num(v) for v in got_axis)
                        and abs(got_axis[axis]) > 0.999
                        and all(abs(got_axis[i]) < 0.01 for i in range(3) if i != axis))
        center_ok = (isinstance(pos, list) and len(pos) == 3
                     and all(_num(v) for v in pos)
                     and all(abs(pos[i] - center[i]) < tol for i in range(3) if i != span_axis)
                     and span[0] - tol <= pos[span_axis] <= span[1] + tol)
        return _measured("independent world cylinder axis and center read", {
            "count": len(rows), "kind": row.get("kind"), "radius_mm": row.get("radius"),
            "position_world_mm": pos, "axis_world": got_axis},
            len(rows) == 1 and row.get("kind") == "cylinder_face"
            and _near(row.get("radius"), 2.0, 0.02) and direction_ok and center_ok)
    return check


def _face_point_witness_rows():
    rows = _box("HolePointFlat", ox=560, oy=80)
    rows += _box("HolePointTurn", ox=0, oy=0)
    rows += [
        ("assembly_move", {"occurrence": "HolePointTurn:1", "rotate_y": 90, "dx": 80},
         lambda p: p.get("moved") is True and p.get("position", {}).get("x") == 80.0, None),
        ("assembly_capture_position", {"action": "capture"}, _captured, None),
        ("design_activate_component", {"occurrence": "HolePointFlat:1"}, "ok", None),
        ("find_geometry", {"target": "HolePointFlat:1", "kind": "planar_face",
                            "nearest_to": [570, 90, 10], "max_results": 1},
         _face_up_at(570, 90, 10), _fg("face_point_flat_face")),
        ("model_inspect", {"target": "HolePointFlat:1", "include": ["mass"],
                            "per_body": True, "units": "mm"},
         _face_point_mass("HolePointFlat:1", before_key="face_point_flat_volume"), None),
        ("design_get", {"include": ["timeline"], "max_results": 2000},
         _capture_face_point_timeline, None),
        ("model_hole", lambda c: {"diameter": "4 mm", "extent": "through",
                                   "placement": "face_point", "face": _ctx_get(
                                       c, "face_point_flat_face", "flat top face"),
                                   "point": [570, 90, 10]},
         lambda p: (p.get("holes_verified") is True and p.get("holes") == 1
                    and p.get("point_space") == "face-owner"
                    and p.get("point") == [570, 90, 10] and p.get("units") == "mm"
                    and p.get("host_component") == "HolePointFlat"
                    and p.get("host_verified") is True and bool(p.get("feature"))),
         ("face_point_flat_feature", _recall("face_point_flat_feature", lambda p:
             p["host_component"] + "/" + p["feature"]))),
        ("find_geometry", {"target": "HolePointFlat:1", "kind": "cylinder_face",
                            "radius": 2, "nearest_to": [570, 90, 5], "max_results": 1},
         _face_point_cylinder([570, 90, 5], 2, 2, (0, 10)), None),
        ("model_inspect", {"target": "HolePointFlat:1", "include": ["mass"],
                            "per_body": True, "units": "mm"},
         _face_point_mass("HolePointFlat:1", delta=-125.663706, restore_key="face_point_flat_volume"), None),
        ("design_delete_feature", lambda c: {"feature": _ctx_get(
            c, "face_point_flat_feature", "created face-point hole")},
         lambda p: p.get("deleted") is True, None),
        ("model_inspect", {"target": "HolePointFlat:1", "include": ["mass"],
                            "per_body": True, "units": "mm"},
         _face_point_mass("HolePointFlat:1", restore_key="face_point_flat_volume"), None),
        ("design_get", {"include": ["timeline"], "max_results": 2000},
         _same_face_point_timeline, None),
        ("find_geometry", {"target": "HolePointFlat:1", "kind": "planar_face",
                            "nearest_to": [570, 90, 10], "max_results": 1},
         _face_up_at(570, 90, 10), _fg("face_point_flat_face")),
        ("model_inspect", {"target": "HolePointFlat:1", "include": ["mass"],
                            "per_body": True, "units": "mm"},
         _face_point_mass("HolePointFlat:1", before_key="face_point_flat_volume_after_delete"), None),
        ("model_hole", lambda c: {"diameter": "4 mm", "extent": "through",
                                   "placement": "face_point", "face": _ctx_get(
                                       c, "face_point_flat_face", "flat top face"),
                                   "point": [570, 90, 13]},
         _refused("3 mm off", "selected face"), None),
        ("model_hole", lambda c: {"diameter": "4 mm", "extent": "through",
                                   "placement": "face_point", "face": _ctx_get(
                                       c, "face_point_flat_face", "flat top face"),
                                   "point": [600, 90, 10]},
         _refused("outside", "No hole was created"), None),
        ("model_inspect", {"target": "HolePointFlat:1", "include": ["mass"],
                            "per_body": True, "units": "mm"},
         _face_point_mass("HolePointFlat:1", restore_key="face_point_flat_volume_after_delete"), None),
        ("design_get", {"include": ["timeline"], "max_results": 2000},
         _same_face_point_timeline, None),
        ("design_activate_component", {"occurrence": "HolePointTurn:1"}, "ok", None),
        ("find_geometry", {"target": "HolePointTurn:1", "kind": "planar_face",
                            "nearest_to": [90, 10, -10], "max_results": 1},
         lambda p: _measured("turned placed face in world", {
             "count": len(p.get("matches") or []),
             "position": (p.get("matches") or [{}])[0].get("position"),
             "normal": (p.get("matches") or [{}])[0].get("normal")},
             len(p.get("matches") or []) == 1
             and isinstance(p["matches"][0].get("normal"), list)
             and len(p["matches"][0]["normal"]) == 3
             and all(_num(v) for v in p["matches"][0]["normal"])
             and isinstance(p["matches"][0].get("position"), list)
             and len(p["matches"][0]["position"]) == 3
             and all(_num(v) for v in p["matches"][0]["position"])
             and (p["matches"][0].get("normal") or [0, 0, 0])[0] > 0.999
             and all(abs(v - w) < 0.5 for v, w in zip(
                 p["matches"][0].get("position") or [], [90, 10, -10]))),
         _fg("face_point_turn_face")),
        ("model_inspect", {"target": "HolePointTurn:1", "include": ["mass"],
                            "per_body": True, "units": "mm"},
         _face_point_mass("HolePointTurn:1", before_key="face_point_turn_volume"), None),
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
        ("model_hole", lambda c: {"diameter": "4 mm", "extent": "through",
                                   "placement": "face_point", "face": _ctx_get(
                                       c, "face_point_turn_face", "turned placed face"),
                                   "point": [10, 10, 10]},
         lambda p: (p.get("holes_verified") is True and p.get("holes") == 1
                    and p.get("point_space") == "face-owner"
                    and p.get("point") == [10, 10, 10] and p.get("units") == "mm"
                    and p.get("host_component") == "HolePointTurn"
                    and p.get("host_verified") is True), None),
        ("find_geometry", {"target": "HolePointTurn:1", "kind": "cylinder_face",
                            "radius": 2, "nearest_to": [85, 10, -10], "max_results": 1},
         _face_point_cylinder([85, 10, -10], 0, 0, (80, 90)), None),
        ("model_inspect", {"target": "HolePointTurn:1", "include": ["mass"],
                            "per_body": True, "units": "mm"},
         _face_point_mass("HolePointTurn:1", delta=-125.663706, restore_key="face_point_turn_volume"), None),
    ]
    return rows


_DETAILS = [
    *_DEFINITION_READS,
    *_DATUM_OPERANDS,
    # THE HOLES AS THE MACHINE SEES THEM, read FIRST: the chamfers below break two of these rims,
    # and a broken rim is a hole of a different shape, so the recognizer's grouping is read while
    # the drilled pattern is still as model_hole left it. The saved handles drive the CAM act's
    # recognized-hole drill; BoreDia is PartHt * 0.3 = 12 mm.
    # Recognition needs the Manufacturing Extension (measured on the lapsed install: "Requires the
    # Manufacturing Extension to be active"), so the recognizer rows ride the tier and the
    # unentitled variant asserts the refusal names the extension and the by-hand route.
    ("cam_find_holes", {"bodies": ["Bracket:1"]},
     _needs(MACHINING_EXTENSION, _holes_recognized(2, 4, 12.0)),
     _recognized_cbore_walls("recognized_cbore_walls", count_key="holes_group_count")),
    ("cam_find_holes", {"bodies": ["Bracket:1"]},
     _unless(MACHINING_EXTENSION,
             _refused("Manufacturing Extension", "This operation requires", "find_geometry")), None),
    # The window, on the same part: at 11 mm every BoreDia group falls out (the step bore and the
    # longer boss bore are separate groups - the recognizer groups by identical length) and the
    # 10.8 mm counterbores stay; kept plus dropped is the unwindowed total, so nothing is lost.
    ("cam_find_holes", {"bodies": ["Bracket:1"], "max_diameter": 11},
     _needs(MACHINING_EXTENSION, _holes_windowed(12.0, "holes_group_count")), None),
    # THE POCKET AS THE MACHINE SEES IT, down the same axis a 3-axis setup attacks: PocketDepth is
    # PartHt * 0.4 = 16 mm, so the floor sits that far under the low top the cut opened, and the
    # four PocketRad corners round its single boundary loop. The saver takes that pocket's FLOOR
    # handle - the face whose locator sits lowest along the attack - which drives a 2D pocket of its
    # own in the CAM act; its count and its loop size are what the two rows after it read back.
    # Plain pocket recognition runs on the base licence (measured on the lapsed install: 8 pockets
    # read back); only the boss-aware route below rides the tier.
    ("cam_find_pockets", {"bodies": ["Bracket:1"]}, _pockets_recognized(16.0),
     _recognized_pocket_floor("pocket_floor", 16.0, count_key="pockets_plain_count",
                              loop_key="pocket_loop_segments")),
    # ...and the boss, which only the boss-aware route reports: it comes back as a pocket with an
    # ISLAND and no boundary - the one shape that separates a boss from a recess. The row rides the
    # extension tier, so a base licence skips it rather than reddening the run.
    ("cam_find_pockets", {"bodies": ["Bracket:1"], "include_bosses": True},
     _needs(MACHINING_EXTENSION, _pocket_boss("pockets_plain_count")), None),
    # The rims the part is handled by, each asked for by RADIUS - the one query that keeps naming
    # the same edge after the driver changes. A fillet's own tangent circle is not a corner, and
    # handing one back to model_fillet answers FILLET_NO_EDGE_FOUND, so every beat below picks a
    # rim no earlier feature has already rounded.
    # Every one of these queries FEEDS the next step, so each asserts the count it found: a radius
    # filter that matches nothing still returns ok, and the ledger then reports a bare pass on a
    # query whose handle the following row cannot take.
    ("find_geometry", {"target": "Bracket", "kind": "circular_edge", "radius": 10,
                       "max_results": 1}, _matched(1, "circular_edge"), _fg("boss_rim")),
    ("model_fillet", lambda c: {"edges": [_ctx_get(c, "boss_rim", "the boss rim")],
                                "radius": 1.5}, _filleted, None),
    ("find_geometry", {"target": "Bracket", "kind": "circular_edge", "radius": 6,
                       "max_results": 1}, _matched(1, "circular_edge"), _fg("bore_rim")),
    ("model_chamfer", lambda c: {"edges": [_ctx_get(c, "bore_rim", "a through-bore rim")], "distance": 1}, _chamfered, None),
    # the distance-and-angle definition with an explicit corner type. Both assertions are on values
    # READ BACK off the created feature - a corner type the platform silently ignored builds an
    # identical face count, so an echoed payload would sail through this predicate.
    ("find_geometry", {"target": "Bracket", "kind": "circular_edge", "radius": 3,
                       "max_results": 4}, _matched(4, "circular_edge"),
     ("mount_rim", lambda p: p["matches"][-1]["handle"])),
    ("model_chamfer", lambda c: {"edges": [_ctx_get(c, "mount_rim", "a mounting-bore rim")],
                                 "distance": 1, "angle_deg": 30, "corner_type": "miter"},
     lambda p: p.get("corner_type") == "miter" and abs((p.get("angle_deg") or 0) - 30) < 1e-6
     and not p.get("corner_type_unverified") and not p.get("angle_deg_unverified") and not p.get("chamfer_type_unverified"), None),
    # a shell cameo cap, a wart feature added and deleted (timeline health diff), a scratch occurrence.
    ("model_create_component", {"name": "ShellCap", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "ShellS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 400, "y1": 0,
                                           "x2": 430, "y2": 30}],
                             "sketch_name": "ShellS"}, "ok", None),
    ("model_extrude", {"sketch_name": "ShellS", "profile_index": 0, "distance": 20}, _extruded, None),
    ("find_geometry", {"target": "ShellCap", "kind": "planar_face", "nearest_to": [415, 15, 20], "max_results": 1}, "ok", _fg("shell_top")),
    ("model_shell", lambda c: {"body_name": "ShellCap", "remove_faces": [_ctx_get(c, "shell_top", "shell top")], "thickness": 2}, _shelled, None),
    # THE TWO-SIDED EXTENT, in its own component so nothing else's body census moves. Side one lands
    # on extentOne and side two on extentTwo, each reporting the depth THAT side asked for, and the
    # tool now compares them side by side - so an UNEQUAL pair is the shape that tells the compare
    # apart from one reading a single number twice. The payload alone cannot show where the material
    # went, hence the inspect below.
    ("model_create_component", {"name": "TwoSideCap", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "TwoSideS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 470, "y1": 0,
                                           "x2": 500, "y2": 30}],
                             "sketch_name": "TwoSideS"}, "ok", None),
    # 'model_parameters' carrying BOTH distance and distance2 is the feature really holding two
    # extents; an EMPTY unverified disclosure is the compare having judged both sides rather than
    # skipping one (it names any side it could not judge).
    ("model_extrude", {"sketch_name": "TwoSideS", "profile_index": 0, "extent": "two_side",
                       "distance": 12, "distance2": 8},
     lambda p: (p.get("extent") == "two_side" and p.get("distance") == 12.0
                and p.get("distance2") == 8.0 and bool(p.get("result_bodies"))
                and "distance" in (p.get("model_parameters") or {})
                and "distance2" in (p.get("model_parameters") or {})
                and "not depth-verified" not in (p.get("note") or "")), None),
    # Where the material actually went: the sketch sits on z=0, so a correct two-sided extrude
    # STRADDLES it 20 mm deep and UNEQUALLY. A symmetric 12/12 or 8/8 fails the inequality, a
    # one-sided 20 fails the straddle, and a swap only changes which face is which - all three are
    # payloads that would read identically above.
    ("model_inspect", {"target": "TwoSideCap:1"},
     lambda p: (p["min_point"]["z"] < -0.001 and p["max_point"]["z"] > 0.001
                and abs((p["max_point"]["z"] - p["min_point"]["z"]) - 20) < 0.05
                and abs(abs(p["max_point"]["z"]) - abs(p["min_point"]["z"])) > 3), None),
    # back to the shell cameo's component, so every step after this lands where it did before.
    *_EXTRUDE_EDITS,
    *_BODY_ORGANIZATION,
    ("design_activate_component", {"occurrence": "ShellCap:1"}, "ok", None),
    # THE WartPlane ROW carries the offset_from predicate - the sweep's only offset-plane call, so
    # it is where 'offset_from' gets read once against a real resolved origin plane: the payload
    # must name the PLANE ('XY'), never echo the 'xy' request token. The unit fake spells the name
    # uppercase from the sibling convention; this beat is what MEASURES the live casing, so a
    # failure on the string alone means the FAKE is what is wrong, never the tool.
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 12, "name": "WartPlane"},
     lambda p: p.get("offset_from") == "XY", None),
    # 'deleted' is true only where the timeline name census read on BOTH sides of the delete; null is
    # an absence nothing could prove, and a delete that broke a downstream feature says so.
    ("design_delete_feature", {"feature": "WartPlane"},
     lambda p: (p["deleted"] is True and p["feature"] == "WartPlane"
                and "timeline_warning" not in p), None),
    # the three datum modes with no other route in the API: a plane rotated about a curved face's
    # own inferred axis, a plane pinned through a vertex, and a plane/point at a ratio along a path.
    # The angled plane is built on the DATUM BENCH's bore, not on the machined part. A datum
    # plane is an infinite visual object and the shaft sits at the world origin - which is where the
    # vise is later built around the machined part, so a plane hung there leans across the fixture
    # for the rest of the run. The bench is out on the field with its own cell and its own frame.
    ("model_construction", lambda c: {"kind": "plane", "mode": "at_angle_on_face",
                                      "face": _ctx_get(c, "db_bore", "bench bore"),
                                      "plane": "xz", "angle": 30, "name": "BenchAnglePlane"},
     # the bore's axis is Z through the bench's own centre, so the plane contains that axis and its
     # origin sits ON it - asked through _px/_py because the layout moves the bench.
     lambda p: p.get("contains_face_axis") is True and p.get("angle_deg") == 30
     and _near(p["geometry"]["origin"]["x"], _px("DatumBench", 230.0), 1e-3)
     and _near(p["geometry"]["origin"]["y"], _py("DatumBench", 20.0), 1e-3), None),
    ("find_geometry", {"target": "ShellCap", "kind": "vertex", "max_results": 1}, "ok", _fg("cd_vert")),
    ("model_construction", lambda c: {"kind": "plane", "mode": "offset_through_point", "plane": "xy",
                                      "points": [_ctx_get(c, "cd_vert", "shell vertex")],
                                      "name": "ThroughVertexPlane"},
     lambda p: p.get("passes_through_point") is True, None),
    # the bottom front edge specifically: (400,0,0) -> (430,0,0), midpoint (415,0,0).
    ("find_geometry", {"target": "ShellCap", "kind": "line_edge", "nearest_to": [415, 0, 0], "max_results": 1},
     "ok", _fg("cd_edge")),
    # The on-path placements all ride ONE known path: the cap's bottom front edge, 30 mm long from
    # (400,0,0) to (430,0,0). A PROPORTIONAL placement reads 'at' as a unitless ratio and publishes
    # it back as the ratio it landed on - no path extent at all, because a ratio cannot leave the
    # path. Every absolute beat below is measured against that same 30 mm.
    ("model_construction", lambda c: {"kind": "plane", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"),
                                      "at": 0.5, "name": "MidPathPlane"},
     lambda p: p.get("at_ratio") == 0.5
     and abs(p["geometry"]["origin"]["x"] - _px("ShellCap", 415)) < 1e-3
     and abs(p["geometry"]["origin"]["y"] - _py("ShellCap", 0)) < 1e-3
     and abs(p["geometry"]["origin"]["z"]) < 1e-3
     and p.get("landed", {}).get("distance") == "0.5"
     and "path_length" not in p and "beyond_path" not in p
     and "not clamped" not in (p.get("note") or ""), None),
    # a quarter along the SAME edge: 7.5 mm from the midpoint whichever way the edge runs.
    ("model_construction", lambda c: {"kind": "point", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"),
                                      "at": 0.25, "name": "QuarterPathPoint"},
     lambda p: p.get("at_ratio") == 0.25
     and abs(abs(p["geometry"]["at"]["x"] - _px("ShellCap", 415)) - 7.5) < 1e-3
     and abs(p["geometry"]["at"]["y"] - _py("ShellCap", 0)) < 1e-3
     and abs(p["geometry"]["at"]["z"]) < 1e-3, None),
    # setByPath RAISES on a proportional value outside 0-1 and the raise rolls back the whole
    # transaction, so the range is refused before the call - and the next call still answers.
    ("model_construction", lambda c: {"kind": "point", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"), "at": 1.5},
     "refused", None),
    # ABSOLUTE: 'at' is a LENGTH from the path start, so the payload swaps the ratio for the pair
    # that can be compared - the measured path length and where this datum sits along it. 12 mm is
    # inside the 30 mm edge, so beyond_path is false and the note warns of nothing.
    ("model_construction", lambda c: {"kind": "plane", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"),
                                      "at": 12, "distance_type": "absolute",
                                      "name": "AbsInsidePlane"},
     lambda p: p.get("distance_type") == "absolute" and "at_ratio" not in p
     and isinstance(p.get("landed", {}).get("distance"), str)
     and abs(p.get("path_length", 0) - 30.0) < 1e-3
     and abs(p.get("along_path", -1) - 12.0) < 1e-3
     and p.get("beyond_path") is False and "OFF the path" not in (p.get("note") or ""), None),
    # An absolute distance is not clamped at EITHER end: a NEGATIVE one places the datum before the
    # path start, along the tangent, with a healthy feature. That is a legal placement the platform
    # accepts, so it is reported with its measured numbers - and the note says it landed off.
    ("model_construction", lambda c: {"kind": "plane", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"),
                                      "at": -5, "distance_type": "absolute",
                                      "name": "BeforeStartPlane"},
     lambda p: p.get("beyond_path") is True and abs(p.get("along_path", 0) + 5.0) < 1e-3
     and "OFF the path" in (p.get("note") or ""), None),
    # the far end of the same range, on the point kind: 500 mm along a 30 mm edge.
    ("model_construction", lambda c: {"kind": "point", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"),
                                      "at": 500, "distance_type": "absolute",
                                      "name": "PastEndPoint"},
     lambda p: p.get("beyond_path") is True and abs(p.get("path_length", 0) - 30.0) < 1e-3, None),
    # the boundary itself: a datum exactly AT the path length is ON the path, not beyond it.
    ("model_construction", lambda c: {"kind": "plane", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"),
                                      "at": 30, "distance_type": "absolute",
                                      "name": "AtEndPlane"},
     lambda p: p.get("beyond_path") is False
     and abs(p.get("along_path", -1) - p.get("path_length", 0)) < 1e-6, None),
    *[("find_geometry", {"target": "ShellCap", "kind": kind, "name": name, "max_results": 10},
       _absolute_datum_position(kind, distance, name), None)
      for kind, name, distance in (("construction_plane", "AbsInsidePlane", 12),
                                   ("construction_plane", "BeforeStartPlane", -5),
                                   ("construction_point", "PastEndPoint", 500),
                                   ("construction_plane", "AtEndPlane", 30))],
    ("design_get", {"include": ["timeline"], "max_results": 1000},
     _absolute_datum_health, None),
    # an EXPRESSION placement is measured exactly as a literal one - the expression is what the
    # datum's own model parameter carries, and that parameter's name is what param_set retargets.
    ("model_construction", lambda c: {"kind": "point", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"),
                                      "at": "22 mm", "distance_type": "absolute",
                                      "name": "ExprPathPoint"},
     lambda p: "22" in (p.get("landed", {}).get("distance") or "")
     and str(p.get("model_parameters", {}).get("distance", "")).startswith("d"), None),
    # proportional on the plane kind reads back as the bare ratio, with no extent published - the
    # pair that separates the two distance types in one payload.
    ("model_construction", lambda c: {"kind": "plane", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"),
                                      "at": 0.5, "distance_type": "proportional",
                                      "name": "RatioPlane"},
     lambda p: p.get("landed", {}).get("distance") == "0.5"
     and "path_length" not in p and "beyond_path" not in p, None),
    # to_object: the plane lands at a VERTEX's own along-path position PLUS a signed offset, and the
    # two arrive as SEPARATE model parameters. 40 mm past either end of a 30 mm edge is off the path
    # whichever vertex the edge starts at, so this one carries the same off-path disclosure.
    ("find_geometry", {"target": "ShellCap", "kind": "vertex", "nearest_to": [430, 0, 0],
                       "max_results": 1}, "ok", _fg("cd_vert_end")),
    ("model_construction", lambda c: {"kind": "plane", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"),
                                      "to_object": _ctx_get(c, "cd_vert_end", "a path end vertex"),
                                      "offset": 40, "name": "ToObjectFarPlane"},
     lambda p: p.get("to_object") is True
     and set(p.get("landed", {})) == {"distance", "offset"}
     and set(p.get("model_parameters", {})) == {"distance", "offset"}
     and abs(p.get("path_length", 0) - 30.0) < 1e-3
     and p.get("along_path", 0) > p.get("path_length", 0)
     and p.get("beyond_path") is True and "OFF the path" in (p.get("note") or ""), None),
    # the same shape landing INSIDE, so the disclosure is proven to discriminate: the cap's bottom
    # front and right edges chain into a 60 mm path whose shared vertex sits at 30 mm, and 5 mm past
    # that is still on the path.
    ("find_geometry", {"target": "ShellCap", "kind": "line_edge", "nearest_to": [430, 15, 0],
                       "max_results": 1}, "ok", _fg("cd_edge2")),
    ("model_construction", lambda c: {"kind": "plane", "mode": "on_path",
                                      "path": [_ctx_get(c, "cd_edge", "datum path edge"),
                                               _ctx_get(c, "cd_edge2", "the connected second edge")],
                                      "to_object": _ctx_get(c, "cd_vert_end", "the shared vertex"),
                                      "offset": 5, "name": "ToObjectMidPlane"},
     lambda p: p.get("beyond_path") is False and abs(p.get("along_path", 0) - 35.0) < 1e-3
     and "OFF the path" not in (p.get("note") or ""), None),
    # ConstructionPointInput carries setByPath but NOT setByPathToObject, so the point kind refuses
    # 'to_object' by name instead of dropping it.
    ("model_construction", lambda c: {"kind": "point", "mode": "on_path",
                                      "path": _ctx_get(c, "cd_edge", "datum path edge"),
                                      "to_object": _ctx_get(c, "cd_vert_end", "a path end vertex")},
     "refused", None),
    # a CHAINED path is measured whole: 45 mm is past the first edge but inside the 60 mm total, so
    # the datum is on the path and 'path_length' is the SUM, not the seed edge's own length.
    ("model_construction", lambda c: {"kind": "plane", "mode": "on_path",
                                      "path": [_ctx_get(c, "cd_edge", "datum path edge"),
                                               _ctx_get(c, "cd_edge2", "the connected second edge")],
                                      "at": 45, "distance_type": "absolute",
                                      "name": "ChainedPathPlane"},
     lambda p: p.get("beyond_path") is False and abs(p.get("path_length", 0) - 60.0) < 1e-3
     and abs(p.get("along_path", 0) - 45.0) < 1e-3, None),
    # sketch_project's two new actions, on the cap the datum beats already measured. The section
    # sketch sits on MidPathPlane (x=415, normal along X), which crosses the cap cleanly; the cap's
    # x=400 side face is PARALLEL to that plane, so it is the same-context source that contributes
    # nothing and the partial path must name it.
    ("sketch_create", {"plane": "MidPathPlane", "name": "SecS"}, "ok", None),
    # the section of the HOLLOW cap is outer + inner rectangles - at least 8 curves. Attribution is
    # honestly SUPPRESSED whenever any created curve fails to match back, so the beat asserts the
    # census, not per_source.
    ("sketch_project", {"action": "intersect", "sketch_name": "SecS", "bodies": ["ShellCap"]},
     lambda p: p.get("created_count", 0) >= 8 and len(p.get("entity_refs") or []) >= 8, None),
    # the cap's x=400 side face is PARALLEL to the section plane: zero curves created is the
    # measured silent-empty, which the tool's own gate converts into an error naming the source.
    ("find_geometry", {"target": "ShellCap", "kind": "planar_face", "nearest_to": [400, 15, 10], "max_results": 1}, "ok", _fg("sp_far")),
    ("sketch_project", lambda c: {"action": "intersect", "sketch_name": "SecS",
                                  "entities": [_ctx_get(c, "sp_far", "cap far side face")]},
     "refused", None),
    # to_surface: ShellS's own lines projected onto the cap's top face, received by a THIRD sketch -
    # the source sketch must differ from the receiver (measured same-sketch refusal), the curves
    # land ON the face (off the receiver's plane), and the linkage is read back per curve.
    ("sketch_create", {"plane": "xy", "name": "ProjS"}, "ok", None),
    ("find_geometry", {"target": "ShellCap", "kind": "planar_face", "nearest_to": [415, 15, 20], "max_results": 1}, "ok", _fg("sp_top")),
    ("sketch_project", lambda c: {"action": "to_surface", "sketch_name": "ProjS",
                                  "target_faces": [_ctx_get(c, "sp_top", "cap top face")],
                                  "source_sketch": "ShellS", "curve_refs": ["line:0"]},
     lambda p: p.get("created_count", 0) >= 1
     and (p.get("off_plane_count") == p.get("created_count") or "census alone" in p.get("note", ""))
     and ("REFERENCE curves" in p.get("note", "") or "census alone" in p.get("note", "")), None),
    ("sketch_project", {"action": "to_surface", "sketch_name": "ProjS", "target_faces": [],
                        "source_sketch": "ProjS", "curve_refs": ["line:0"]}, "refused", None),
    ("sketch_project", lambda c: {"action": "to_surface", "sketch_name": "ProjS",
                                  "target_faces": [_ctx_get(c, "sp_top", "cap top face")],
                                  "source_sketch": "ShellS", "curve_refs": ["line:0"],
                                  "project_type": "along_vector"}, "refused", None),
    ("model_create_component", {"name": "ScratchOcc", "activate": False}, _made_component_inactive, None),
    # 'deleted' is true only where the assembly path census carried this occurrence BEFORE the delete
    # and not after; null is an unverified absence the payload publishes as a successful call.
    ("design_delete_occurrence", {"occurrence": "ScratchOcc:1"},
     lambda p: (p["deleted"] is True and p["occurrence"] == "ScratchOcc:1"
                and "timeline_warning" not in p), None),
    # scale + offset-face beats on a scratch block: push a face and read the volume move, then the
    # scale contract - uniform f^3, per-axis x*y*z, the three refusal shapes (unresolvable /
    # length-carrying / angle-carrying expression), a bare unitless parameter accepted, and a
    # vertex-anchored scale.
    ("model_create_component", {"name": "ScaleBlock", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "ScaleS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 470, "y1": 0,
                                           "x2": 490, "y2": 20}],
                             "sketch_name": "ScaleS"}, "ok", None),
    ("model_extrude", {"sketch_name": "ScaleS", "profile_index": 0, "distance": 20}, _extruded, None),
    _watch("ScaleBlock:1"),
    ("find_geometry", {"target": "ScaleBlock", "kind": "planar_face", "nearest_to": [480, 10, 20],
                       "max_results": 1}, "ok", _fg("scale_top")),
    ("model_offset_face", lambda c: {"faces": [_ctx_get(c, "scale_top", "block top")],
                                     "distance": 2}, _offset_faces, None),
    # a UNITLESS and an ANGLE parameter: 'value_units' is the parameter's OWN unit read back, which
    # is what says the angle came out of the internal radians into degrees.
    ("param_add", {"name": "ShrinkProbe", "expression": "0.5", "unit": ""},
     _param_added("ShrinkProbe", 0.5, units=""), None),
    ("param_add", {"name": "TiltProbe", "expression": "30 deg", "unit": "deg"},
     _param_added("TiltProbe", 30, units="deg"), None),
    # a solid body's volume IS readable, so the verdict is the measured ratio and the skip flag is
    # absent - its presence would mean the check fell back to "the geometry moved".
    # A SCALE IS ORIGIN-RELATIVE: it multiplies coordinates measured from the world origin, so a
    # block authored at x=470 doubles to x=940 - it grows AND travels, right out of the frame it was
    # framed in. Every scale that moves it is followed by a fresh frame, or the operation the viewer
    # came to watch happens off screen.
    ("model_inspect", {"target": "ScaleBlock", "include": ["default", "mass"],
                       "units": "mm", "accuracy": "very_high"},
     lambda p: _measured("solid stock before missing-body refusal", p,
                         _bodyref_scale_state(p) is not None),
     ("bodyref_scale_before", _recall("bodyref_scale_before", _bodyref_scale_state))),
    ("model_scale", {"bodies": ["MissingScaleBody"], "factor": 2},
     _refused("MissingScaleBody", "Pass a face/edge handle from find_geometry on that body"), None),
    ("model_inspect", {"target": "ScaleBlock", "include": ["default", "mass"],
                       "units": "mm", "accuracy": "very_high"},
     lambda p: _measured("missing-body refusal preserves scale stock", _bodyref_scale_state(p),
                         bool(_RECALL.get("bodyref_scale_before"))
                         and _bodyref_scale_state(p) == _RECALL.get("bodyref_scale_before")), None),
    ("find_geometry", {"target": "ScaleBlock", "kind": "planar_face", "max_results": 1},
     _matched(1, "planar_face"), _fg("bodyref_scale_face")),
    ("model_scale", lambda c: {"bodies": [_ctx_get(c, "bodyref_scale_face", "stock face")], "factor": 2},
     lambda p: p.get("scale_check") == "volume_ratio"
     and abs(p.get("volume_ratio", 0) - 8.0) < 1e-6 and "volume_check_skipped" not in p, None),
    ("model_inspect", {"target": "ScaleBlock", "include": ["default", "mass"],
                       "units": "mm", "accuracy": "very_high"},
     lambda p: _measured("face-handle remedy scales the intended stock", _bodyref_scale_state(p),
                         _bodyref_scale_state(p) is not None and bool(_RECALL.get("bodyref_scale_before"))
                         and all(_near(got, before * multiplier, 0.001)
                                 for got, before, multiplier in zip(_bodyref_scale_state(p)["values"],
                                     _RECALL["bodyref_scale_before"]["values"], (2, 2, 2, 8)))), None),
    _watch("ScaleBlock:1"),
    ("model_scale", {"bodies": ["ScaleBlock"], "x_factor": 3, "y_factor": 2, "z_factor": 1},
     lambda p: abs(p.get("expected_volume_ratio", 0) - 6.0) < 1e-6, None),
    _watch("ScaleBlock:1"),
    ("model_scale", {"bodies": ["ScaleBlock"], "factor": "NoSuchParamXyz * 2"}, "refused", None),
    ("model_scale", {"bodies": ["ScaleBlock"], "factor": "5 mm"}, "refused", None),
    ("model_scale", {"bodies": ["ScaleBlock"], "factor": "TiltProbe"}, "refused", None),
    ("model_scale", {"bodies": ["ScaleBlock"], "factor": "ShrinkProbe"},
     lambda p: abs(p.get("expected_volume_ratio", 0) - 0.125) < 1e-6, None),
    _watch("ScaleBlock:1"),
    ("find_geometry", {"target": "ScaleBlock", "kind": "vertex", "max_results": 1}, "ok",
     _fg("scale_vtx")),
    ("model_scale", lambda c: {"bodies": ["ScaleBlock"], "factor": 1.5,
                               "anchor": _ctx_get(c, "scale_vtx", "block vertex")},
     lambda p: abs(p.get("volume_ratio", 0) - 3.375) < 1e-6, None),
    ("param_delete", {"name": "ShrinkProbe"}, _param_deleted("ShrinkProbe"), None),
    ("param_delete", {"name": "TiltProbe"}, _param_deleted("TiltProbe"), None),
    ("model_move", {"bodies": ["ScaleBlock"], "dx": 10},
     lambda p: abs(p.get("displacement", 0) - 10.0) < 1e-3, None),
    ("model_move", {"mode": "along_entity", "bodies": ["ScaleBlock"], "axis": "y",
                    "distance": 5}, lambda p: abs(p.get("displacement", 0) - 5.0) < 1e-3, None),
    ("model_move", {"mode": "rotate", "bodies": ["ScaleBlock"], "axis": "z", "angle_deg": 15},
     _moved, None),
    ("model_move", lambda c: {"mode": "along_entity", "bodies": ["ScaleBlock"],
                              "axis": _ctx_get(c, "scale_top", "block top"), "distance": 5},
     "refused", None),
    ("model_move", lambda c: {"bodies": ["ScaleBlock"],
                              "faces": [_ctx_get(c, "scale_top", "block top")], "dx": 5},
     "refused", None),
    # SINGLE vs DOUBLE placement: the along_entity beats above moved a body in a component placed
    # ONCE (the axis is proxied into that one occurrence). The same call on a component placed TWICE
    # must refuse naming BOTH paths - each instance holds that body somewhere else, and the
    # displacement read-back cannot tell a right instance from a wrong one.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "TwicePlaced", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "TwicePlacedS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 1900, "y1": 200,
                                           "x2": 1920, "y2": 220}],
                             "sketch_name": "TwicePlacedS"}, "ok", None),
    ("model_extrude", {"sketch_name": "TwicePlacedS", "profile_index": 0, "distance": 10},
     _extruded, None),
    # [F75]/NEW-16: name the body uniquely, then resolve it BARE while the component is still the
    # ACTIVE component and placed ONCE - the walk reaches it both natively (active-comp scope) and
    # as the occurrence proxy, whose entityTokens DIFFER; grouping by native token collapses the
    # pair to ONE candidate (a bare-token key refused this as 'names 2 bodies').
    ("find_geometry", {"target": "TwicePlaced", "kind": "planar_face",
                       "nearest_to": [1910, 210, 10], "max_results": 1}, "ok",
     _fg("twice_face")),
    ("design_set_name", lambda c: {"target": _ctx_get(c, "twice_face", "the TwicePlaced body"),
                                   "new_name": "TwiceBody"},
     lambda p: p.get("name") == "TwiceBody", None),
    ("model_inspect", {"target": "TwiceBody"}, _extent_measured, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("design_add_instance", {"component": "TwicePlaced", "x": 40, "y": 0, "units": "mm"},
     lambda p: p.get("created") is True, ("twice_b", lambda p: p["full_path"])),
    ("model_move", {"mode": "along_entity", "bodies": ["TwicePlaced"], "axis": "y", "distance": 5},
     _refused("placed 2 times", "TwicePlaced:1"), None),
    # placed TWICE the same bare name is two world placements - the refusal lists BOTH
    # instance-qualified forms (the dropped native spelling is not offered), and the qualified
    # form is the way out.
    ("model_inspect", {"target": "TwiceBody"},
     _refused("TwicePlaced:1", "TwicePlaced:2"), None),
    ("model_inspect", {"target": "TwicePlaced:2:TwiceBody"}, _extent_measured, None),
    # back to the component that was active before this cameo, so the ones after it nest as before.
    ("design_activate_component", {"occurrence": "ScaleBlock:1"}, "ok", None),
    # point_to_point: the tool refuses a travel that does not equal the two vertices' own
    # separation, so a plain ok here IS the distance check
    ("find_geometry", {"target": "ScaleBlock", "kind": "vertex", "max_results": 8}, "ok",
     _fgn("mv_verts")),
    ("model_move", lambda c: {"mode": "point_to_point", "bodies": ["ScaleBlock"],
                              "from_point": _ctx_get(c, "mv_verts", "block vertices")[0],
                              "to_point": _ctx_get(c, "mv_verts", "block vertices")[1]},
     lambda p: p.get("moved") is True and p.get("displacement", 0) > 0, None),
    ("model_create_component", {"name": "ThreadPost", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "ThreadS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 530, "cy": 10, "radius": 5}],
                             "sketch_name": "ThreadS"}, "ok", None),
    ("model_extrude", {"sketch_name": "ThreadS", "profile_index": 0, "distance": 25}, _extruded, None),
    ("find_geometry", {"target": "ThreadPost", "kind": "cylinder_face", "max_results": 1}, "ok",
     _fg("post_wall")),
    ("model_thread", lambda c: {"faces": [_ctx_get(c, "post_wall", "post wall")],
                                "designation": "M99x9"}, "refused", None),
    ("model_thread", lambda c: {"faces": [_ctx_get(c, "post_wall", "post wall")],
                                "designation": "M10x1.5", "offset": 2}, "refused", None),
    ("model_thread", lambda c: {"faces": [_ctx_get(c, "post_wall", "post wall")],
                                "designation": "M10x1.5", "length": 12, "offset": 2},
     lambda p: p.get("internal") is False and p.get("designation") == "M10x1.5"
     and p.get("right_handed") is True and p.get("length") == 12, None),
    # the partial extent is read back off the feature, and a metric call-out sits in several
    # standards, so the alternatives ride along
    ("model_thread", lambda c: {"faces": [_ctx_get(c, "post_wall", "post wall")],
                                "designation": "M10x1.5", "length": 12, "offset": 2,
                                "thread_type": "ISO Metric profile"},
     lambda p: p.get("thread_type") == "ISO Metric profile"
     and len(p.get("thread_type_alternatives") or []) > 1, None),
    # a modeled designation far too big for the post grows the body instead of cutting it
    ("model_thread", lambda c: {"faces": [_ctx_get(c, "post_wall", "post wall")],
                                "designation": "M30x3.5", "modeled": True}, "refused", None),
    ("model_create_component", {"name": "ThreadPostRight", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "ThreadRightS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 550, "cy": 10, "radius": 5}],
                             "sketch_name": "ThreadRightS"}, "ok", None),
    ("model_extrude", {"sketch_name": "ThreadRightS", "profile_index": 0, "distance": 25}, _extruded, None),
    ("find_geometry", {"target": "ThreadPostRight", "kind": "cylinder_face", "max_results": 1}, "ok",
     _fg("right_post_wall")),
    ("model_inspect", {"target": "ThreadPostRight", "include": ["default", "mass"],
                       "accuracy": "very_high", "units": "mm"},
     lambda p: _thread_body_facts(p) is not None,
     ("thread_right_before", _recall("thread_right_before", _thread_body_facts))),
    ("model_thread", lambda c: {"faces": [_ctx_get(c, "right_post_wall", "right post wall")],
                                "designation": "M10x1.5", "modeled": True},
     lambda p: p.get("modeled") is True and p.get("right_handed") is True, None),
    ("model_inspect", {"target": "ThreadPostRight", "include": ["default", "mass"],
                       "accuracy": "very_high", "units": "mm"},
     _thread_material_cut("thread_right_before"), None),
    # a modeled thread that FITS must cut real material - the rung-4 gate's own regression net.
    # Left-handed, so the hand the tool wrote is read back off the feature.
    ("model_create_component", {"name": "ThreadPost2", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "ThreadS2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 570, "cy": 10, "radius": 5}],
                             "sketch_name": "ThreadS2"}, "ok", None),
    ("model_extrude", {"sketch_name": "ThreadS2", "profile_index": 0, "distance": 25}, _extruded, None),
    ("find_geometry", {"target": "ThreadPost2", "kind": "cylinder_face", "max_results": 1}, "ok",
     _fg("post2_wall")),
    ("model_inspect", {"target": "ThreadPost:1", "include": ["default", "mass"],
                       "accuracy": "very_high", "units": "mm"},
     lambda p: _thread_body_facts(p) is not None,
     ("thread_control_before", _recall("thread_control_before", _thread_body_facts))),
    ("model_inspect", {"target": "ThreadPost2", "include": ["default", "mass"],
                       "accuracy": "very_high", "units": "mm"},
     lambda p: _thread_body_facts(p) is not None,
     ("thread_material_before", _recall("thread_material_before", _thread_body_facts))),
    ("model_thread", lambda c: {"faces": [_ctx_get(c, "post2_wall", "second post wall")],
                                "designation": "M10x1.5", "modeled": True, "left_handed": True},
     lambda p: p.get("modeled") is True and p.get("right_handed") is False
     and p.get("volume_delta_cm3", 0) < 0, None),
    ("model_inspect", {"target": "ThreadPost2", "include": ["default", "mass"],
                       "accuracy": "very_high", "units": "mm"},
     _thread_material_cut("thread_material_before"), None),
    ("model_inspect", {"target": "ThreadPost:1", "include": ["default", "mass"],
                       "accuracy": "very_high", "units": "mm"},
     _unchanged("thread_control_before", _thread_body_facts, 1e-5), None),
    # the INTERNAL side of the same tool, on a real bore: 'internal' is derived from the face's own
    # out-of-material normal (never echoed), and the ThreadInfo it built is checked against the face
    # at add() - so an 'internal' that disagreed with the geometry would have raised. Then a PARTIAL
    # thread measured from the LOW end, with the end it was measured from read back off the feature.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "ThreadBore", "activate": True}, _made_component, None),
    # the bore is CUT, not left as the inner loop of a two-circle profile: which region a
    # multi-profile sketch calls its last one is the platform's to decide, and picking the disc
    # there builds a plain rod whose radius-4 wall is EXTERNAL - the thread then lands external and
    # the beat asserts nothing about bores. A solid rod plus a through cut is unambiguous.
    ("sketch_create", {"plane": "xy", "name": "ThreadBoreS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 610, "cy": 10, "radius": 12}],
                             "sketch_name": "ThreadBoreS"}, "ok", None),
    ("model_extrude", {"sketch_name": "ThreadBoreS", "profile_index": 0, "distance": 25},
     _extruded, None),
    ("sketch_create", {"plane": "xy", "name": "ThreadBoreCut"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 610, "cy": 10, "radius": 4}],
                             "sketch_name": "ThreadBoreCut"}, "ok", None),
    ("model_extrude", {"sketch_name": "ThreadBoreCut", "profile_index": 0, "distance": 25,
                       "operation": "cut"}, _extruded, None),
    ("find_geometry", {"target": "ThreadBore", "kind": "cylinder_face", "radius": 4,
                       "max_results": 1}, "ok", _fg("bore_wall")),
    ("model_thread", lambda c: {"faces": [_ctx_get(c, "bore_wall", "the bore wall")],
                                "designation": "M8x1.25"},
     lambda p: p.get("internal") is True and p.get("designation") == "M8x1.25", None),
    ("model_thread", lambda c: {"faces": [_ctx_get(c, "bore_wall", "the bore wall")],
                                "designation": "M8x1.25", "length": 10, "location": "low"},
     lambda p: p.get("internal") is True and p.get("location") == "low"
     and p.get("length") == 10, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # a model EDGE handle as the path: the placement call accepts it and Fusion then rejects the
    # add, so the guard refuses it up front and points at sketch_project.
    ("sketch_set_text", lambda c: {"text": "EDGE", "sketch_name": "TextPaths", "create": True,
                                   "mode": "along_path",
                                   "path": _ctx_get(c, "cd_edge", "a model edge handle")},
     "refused", None),
    # design_remove_feature: cast a scratch body, remove it (the census is the verdict), then
    # delete the Remove feature - the body comes back, which is the reversibility the note claims.
    ("model_create_component", {"name": "RmScratch", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "RmS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 1100, "y1": 0,
                                           "x2": 1120, "y2": 20}],
                             "sketch_name": "RmS"}, "ok", None),
    ("model_extrude", {"sketch_name": "RmS", "profile_index": 0, "distance": 5}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("design_remove_feature", {"body": "RmScratch"},
     lambda p: p.get("target_kind") == "body" and p.get("feature_read_back") is True,
     ("rm_feat", lambda p: p["feature"])),
    ("design_delete_feature", lambda c: {"feature": _ctx_get(c, "rm_feat", "remove feature")},
     "ok", None),
    # the body is back: a component with no body has no faces, so exactly one match discriminates.
    ("find_geometry", {"target": "RmScratch", "kind": "planar_face", "max_results": 1},
     lambda p: len(p.get("matches") or []) == 1, None),
    # the occurrence variant of the same round trip.
    ("design_remove_feature", {"occurrence": "RmScratch:1"},
     lambda p: p.get("target_kind") == "occurrence" and p.get("feature_read_back") is True,
     ("rm_feat2", lambda p: p["feature"])),
    ("design_delete_feature", lambda c: {"feature": _ctx_get(c, "rm_feat2", "remove feature")},
     "ok", None),
    ("model_inspect", {"target": "RmScratch:1"}, _extent_measured, None),
    # model_emboss: a raise then an engrave on one scratch block's top face. The profiles are drawn
    # on a datum plane COINCIDENT with that face, so each sketch holds exactly one profile (an
    # on-face sketch auto-projects the face boundary and would offer two). The verdict is the
    # measured volume direction: 'mode' echoes the sign of the depth and the call is refused when
    # the material moved the other way.
    *_box("EmbossBlock", ox=600, oy=100),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 10, "name": "EmbPlane"},
     _datum_plane("xy"), None),
    ("find_geometry", {"target": "EmbossBlock", "kind": "planar_face", "nearest_to": [610, 110, 10],
                       "max_results": 1}, "ok", _fg("emb_top")),
    ("sketch_create", {"plane": "EmbPlane", "name": "EmbRaise"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 605, "cy": 105, "radius": 3}],
                             "sketch_name": "EmbRaise"}, "ok", None),
    ("sketch_get", {"sketch_name": "EmbRaise"}, "ok", _prof("emb_prof_up")),
    ("model_emboss", lambda c: {"profiles": [_ctx_get(c, "emb_prof_up", "emboss profile")],
                                "faces": [_ctx_get(c, "emb_top", "emboss block top")], "depth": 2},
     lambda p: p.get("mode") == "raise" and p.get("volume_delta_cm3", 0) > 0,
     ("emb_feat", lambda p: p["feature"])),
    # the top face was re-cut by the raise, so the engrave takes a FRESH handle for it.
    ("find_geometry", {"target": "EmbossBlock", "kind": "planar_face", "nearest_to": [610, 110, 10],
                       "max_results": 1}, "ok", _fg("emb_top2")),
    ("sketch_create", {"plane": "EmbPlane", "name": "EmbCut"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 615, "cy": 115, "radius": 3}],
                             "sketch_name": "EmbCut"}, "ok", None),
    ("sketch_get", {"sketch_name": "EmbCut"}, "ok", _prof("emb_prof_down")),
    ("model_emboss", lambda c: {"profiles": [_ctx_get(c, "emb_prof_down", "engrave profile")],
                                "faces": [_ctx_get(c, "emb_top2", "emboss block top")], "depth": -2},
     lambda p: p.get("mode") == "engrave" and p.get("volume_delta_cm3", 0) < 0, None),
    ("model_emboss", lambda c: {"profiles": [_ctx_get(c, "emb_prof_up", "emboss profile")],
                                "faces": [_ctx_get(c, "emb_top2", "emboss block top")], "depth": 0},
     "refused", None),
    # model_mirror's FEATURE mode, on the emboss the beat above just made - an EmbossFeature is the
    # class MEASURED as accepted by the input collection. The mirror plane runs down the block's own
    # middle so the mirrored emboss lands back ON the block; the body/volume census is the verdict,
    # since MirrorFeature.resultFeatures.count reads None even when the mirror mints geometry.
    ("model_construction", {"kind": "plane", "plane": "yz", "offset": 610, "name": "EmbMirrorPlane"},
     _datum_plane("yz"), None),
    ("model_mirror", lambda c: {"features": [_ctx_get(c, "emb_feat", "the emboss feature")],
                                "plane": "EmbMirrorPlane"},
     lambda p: p.get("mode") == "features"
     and (p.get("bodies_added") or p.get("volume_change_cm3")), None),
    # join is a BODY-mode setting and 'joined' is read off the created feature, never echoed. The
    # body is named through a FRESH face handle: the mirrored emboss re-cut the one taken above.
    # A JOIN NEEDS THE TWO HALVES TO TOUCH, and the mirror plane is what decides whether they do.
    # About an ORIGIN plane this block's reflection lands 200 mm away with nothing between them:
    # Fusion keeps the feature, makes a second body and marks it "Could not join, multiple bodies
    # created" - a timeline WARNING left in the finished document, which the 'joined' flag alone does
    # not catch because the SETTING was honoured even though the join was not. Mirroring about the
    # block's own +X face gives the reflection that face to fuse across, and the volume the tool
    # measures for itself is what says it fused rather than landing beside it.
    ("model_construction", {"kind": "plane", "plane": "yz", "offset": 620, "name": "EmbJoinPlane"},
     _datum_plane("yz"), None),
    ("find_geometry", {"target": "EmbossBlock", "kind": "planar_face", "nearest_to": [610, 110, 10],
                       "max_results": 1}, "ok", _fg("emb_body")),
    ("model_mirror", lambda c: {"bodies": [_ctx_get(c, "emb_body", "the emboss block body")],
                                "plane": "EmbJoinPlane", "join": True},
     lambda p: p.get("joined") is True and _mirrored(p), None),
    ("model_mirror", lambda c: {"features": [_ctx_get(c, "emb_feat", "the emboss feature")],
                                "plane": "EmbMirrorPlane", "join": True}, "refused", None),
    # model_replace_face: a scratch block whose top face is replaced by an OPEN sheet sitting above
    # it. The sheet is sloped, so the body's measured volume has to move - a replace that changed
    # nothing is an error, not a quiet ok.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "ReplBlock", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "ReplS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 660, "y1": 0,
                                           "x2": 690, "y2": 30}],
                             "sketch_name": "ReplS"}, "ok", None),
    ("model_extrude", {"sketch_name": "ReplS", "profile_index": 0, "distance": 20}, _extruded, None),
    # the replacement rides its own component so one find_geometry names it without ambiguity, and
    # surface_extrude reads is_solid=false back off the result - which is what makes it a legal
    # target. Symmetric, so the sheet spans the block whichever way the extrude runs.
    ("model_create_component", {"name": "ReplRoof", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xz", "name": "ReplRoofS"}, "ok", None),
    # on the xz plane sketch +Y maps to world -Z, so y=-26 puts the sheet at world z=+26 - a FLAT
    # plane ABOVE the z0-20 block, the measured-computable replace shape (a tilted or below-the-
    # block sheet fails compute with ASM_REPL_FACE_FAILED).
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 655, "y1": -26,
                                           "x2": 695, "y2": -26}],
                             "sketch_name": "ReplRoofS"}, "ok", None),
    ("surface_extrude", {"sketch_name": "ReplRoofS", "distance": 80, "symmetric": True},
     lambda p: p.get("is_solid") is False, None),
    ("find_geometry", {"target": "ReplRoof", "kind": "planar_face", "max_results": 1}, "ok",
     _fg("repl_sheet")),
    ("design_get", {"include": ["tree", "timeline"], "component": "ReplRoof",
                    "tree_bodies": True, "tree_handles": True, "max_results": 1000},
     lambda p: _measured("surface tree and timeline before wrong-kind refusals", p,
                         _bodyref_surface_state(p) is not None),
     ("bodyref_surface_before", _recall("bodyref_surface_before", _bodyref_surface_state))),
    ("model_scale", {"bodies": ["ReplRoof"], "factor": 2},
     _refused("the name 'ReplRoof' resolves to an OPEN SURFACE body"), None),
    ("model_scale", lambda c: {"bodies": [_ctx_get(c, "repl_sheet", "open sheet face")], "factor": 2},
     _refused("that handle points at an OPEN SURFACE body"), None),
    ("design_get", {"include": ["tree", "timeline"], "component": "ReplRoof",
                    "tree_bodies": True, "tree_handles": True, "max_results": 1000},
     lambda p: _measured("wrong-kind refusals preserve surface tree and timeline", _bodyref_surface_state(p),
                         bool(_RECALL.get("bodyref_surface_before"))
                         and _bodyref_surface_state(p) == _RECALL.get("bodyref_surface_before")), None),
    # build the feature on the component that owns the BODY, not the one holding the sheet.
    ("design_activate_component", {"occurrence": "ReplBlock:1"}, "ok", None),
    ("find_geometry", {"target": "ReplBlock", "kind": "planar_face", "nearest_to": [675, 15, 20],
                       "max_results": 1}, "ok", _fg("repl_top")),
    # a clean parametric replace has a feature to read AND a measured volume move, so the payload
    # carries no 'effect_unverified' hedge - that key appears only when neither could be read.
    ("model_replace_face", lambda c: {"faces": [_ctx_get(c, "repl_top", "block top")],
                                      "target": _ctx_get(c, "repl_sheet", "the open roof sheet")},
     lambda p: p.get("replaced") is True and p.get("volume_delta_cm3") not in (None, 0)
     and "effect_unverified" not in p, None),
    # a SOLID face as the replacement target is refused: the target must be a surface face or body.
    ("find_geometry", {"target": "ReplBlock", "kind": "planar_face", "nearest_to": [675, 15, 0],
                       "max_results": 1}, "ok", _fg("repl_bottom")),
    ("find_geometry", {"target": "ReplBlock", "kind": "planar_face", "nearest_to": [660, 15, 10],
                       "max_results": 1}, "ok", _fg("repl_side")),
    ("model_replace_face", lambda c: {"faces": [_ctx_get(c, "repl_side", "block side")],
                                      "target": _ctx_get(c, "repl_bottom", "a solid face")},
     "refused", None),
    # model_pipe: a HOLLOW pipe on its own path (the wall is read back off the created feature),
    # then a HALF-path pipe whose bounding box proves path_fraction is a FRACTION - 20 mm of pipe on
    # a 40 mm path, not 0.5 mm - and finally the reverse extent refused on an OPEN path, which the
    # platform would otherwise swallow in silence.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "PipeRun", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xz", "name": "PipeRunPath"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 720, "y1": 0,
                                           "x2": 720, "y2": 40}],
                             "sketch_name": "PipeRunPath"}, "ok", None),
    # PipeFeature.startFaces/endFaces/sideFaces all read EMPTY on a freshly added hollow pipe, so
    # nothing on this build can say whether the ends are capped - and the payload publishes no
    # 'capped_ends' key rather than a guess dressed as a read.
    ("model_pipe", {"path": "sketch:PipeRunPath", "section_size": 10, "wall_thickness": 1.5},
     lambda p: p.get("hollow") is True and abs((p.get("wall_thickness") or 0) - 1.5) < 1e-6
     and "capped_ends" not in p, None),
    # a five-curve TANGENT stadium (line, arc, line, arc, line), each joint coincident-constrained
    # but the curves' own SketchPoints unmerged - the showcase's hoop as agents draw it. Curves
    # that merely touch by coordinate are not a path at all (Path.create raises, measured burn83);
    # constrained, the collection build takes every curve, so the pipe follows the whole 102.83 mm
    # loop and its volume is the d10 section area times that length, not the first leg.
    ("model_create_component", {"name": "PipeChain", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "PipeChainPath"}, "ok", None),
    # (x >= 900: clear of the story's stock and bracket, which the interference census walks)
    ("sketch_add_geometry", {"geometry": [
        {"kind": "line", "x1": 905, "y1": 0, "x2": 920, "y2": 0},
        {"kind": "arc", "cx": 920, "cy": 10, "x1": 920, "y1": 0, "sweep_deg": 180},
        {"kind": "line", "x1": 920, "y1": 20, "x2": 900, "y2": 20},
        {"kind": "arc", "cx": 900, "cy": 10, "x1": 900, "y1": 20, "sweep_deg": 180},
        {"kind": "line", "x1": 900, "y1": 0, "x2": 905, "y2": 0}],
                             "sketch_name": "PipeChainPath"}, "ok", None),
    ("sketch_constrain", {"constraints": [
        {"constraint": "coincident", "entity_one": "line:0:end", "entity_two": "arc:0:start"},
        {"constraint": "coincident", "entity_one": "arc:0:end", "entity_two": "line:1:start"},
        {"constraint": "coincident", "entity_one": "line:1:end", "entity_two": "arc:1:start"},
        {"constraint": "coincident", "entity_one": "arc:1:end", "entity_two": "line:2:start"},
        {"constraint": "coincident", "entity_one": "line:2:end", "entity_two": "line:0:start"}],
                          "sketch_name": "PipeChainPath"}, "ok", None),
    ("model_pipe", {"path": "sketch:PipeChainPath", "section_size": 10},
     lambda p: _measured("5-curve tangent stadium pipes the whole 102.83 mm loop at d10",
                         {"path_curves": p.get("path_curves"),
                          "path_sketch_curves": p.get("path_sketch_curves"),
                          "volume_cm3": p.get("volume_cm3")},
                         p.get("path_curves") == 5 and p.get("path_sketch_curves") == 5
                         and _near(p.get("volume_cm3"), 8.076396, 0.1)), None),
    ("model_create_component", {"name": "PipeHalf", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xz", "name": "PipeHalfPath"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 760, "y1": 0,
                                           "x2": 760, "y2": 40}],
                             "sketch_name": "PipeHalfPath"}, "ok", None),
    ("model_pipe", {"path": "sketch:PipeHalfPath", "section_size": 6, "section_type": "square",
                    "path_fraction": 0.5}, _piped, None),
    # the occurrence bounding box counts BODIES only, so the path sketch cannot inflate this read.
    ("model_inspect", {"target": "PipeHalf:1"}, lambda p: abs(p.get("z", 0) - 20.0) < 1.0, None),
    ("model_pipe", {"path": "sketch:PipeRunPath", "section_size": 6, "path_fraction": 0.5,
                    "path_fraction_reverse": 0.4}, "refused", None),
    # a CUT scoped to named bodies: participantBodies is write-only on the created feature, so the
    # scope cannot be read back - the note says the list is what was REQUESTED rather than dressing
    # an echo up as a read-back. The block is built around the path so the cut has material to take.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "PipeCut", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "PipeCutS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 800, "y1": -20,
                                           "x2": 840, "y2": 20}],
                             "sketch_name": "PipeCutS"}, "ok", None),
    ("model_extrude", {"sketch_name": "PipeCutS", "profile_index": 0, "distance": 20}, _extruded, None),
    ("sketch_create", {"plane": "xz", "name": "PipeCutPath"}, "ok", None),
    # on an xz sketch +Y maps to world -Z, so this line runs through the block at world z=10, y=0,
    # entering and leaving it - a cut that removes real material.
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 790, "y1": -10,
                                           "x2": 850, "y2": -10}],
                             "sketch_name": "PipeCutPath"}, "ok", None),
    ("model_inspect", {"target": "PipeCut:1", "include": ["default", "mass"], "per_body": True,
                       "accuracy": "very_high", "units": "mm"},
     lambda p: _measured("pipe cut control before", _retire_material_state(p), _retire_material_state(p) is not None),
     ("pipe_cut_before", _recall("pipe_cut_before", _retire_material_state))),
    ("model_pipe", {"path": "sketch:PipeCutPath", "section_size": 8, "operation": "cut",
                    "target_bodies": ["PipeCut"]},
     lambda p: "REQUESTED" in (p.get("note") or "") and p.get("scoped_to_bodies"), None),
    ("model_inspect", {"target": "PipeCut:1", "include": ["default", "mass"], "per_body": True,
                       "accuracy": "very_high", "units": "mm"},
     lambda p: (lambda now, before: _measured("successful pipe cut removes independent material",
         {"before": before, "now": now}, now is not None and before is not None
         and len(now["bodies"]) == len(before["bodies"]) == 1
         and 0 < now["shape"]["volume"] < before["shape"]["volume"]
         and all(now["shape"][k] == before["shape"][k] for k in ("min", "max"))))(
             _retire_material_state(p), _RECALL.get("pipe_cut_before")), None),
    # a pipe JOIN whose path touches nothing: the tube lands as a body of its own, so the error
    # names the new orphan body and points at model_combine(join) instead of just "nothing changed".
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "PipeJoinMiss", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "PipeJoinTargetS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 1000, "y1": 0,
                                           "x2": 1020, "y2": 20}],
                             "sketch_name": "PipeJoinTargetS"}, "ok", None),
    ("model_extrude", {"sketch_name": "PipeJoinTargetS", "profile_index": 0, "distance": 10},
     _extruded, None),
    ("sketch_create", {"plane": "xy", "name": "PipeJoinMissPath"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1050, "y1": 0,
                                           "x2": 1050, "y2": 40}],
                             "sketch_name": "PipeJoinMissPath"}, "ok", None),
    *_retire_reads("pipe_retire", ["PipeJoinMiss:1", "PipeCut:1"],
                  [("PipeJoinMiss", "PipeJoinTargetS"), ("PipeJoinMiss", "PipeJoinMissPath"),
                   ("PipeCut", "PipeCutS"), ("PipeCut", "PipeCutPath")]),
    ("sketch_get", {"component": "PipeJoinMiss"},
     _pipe_path_visibility, None),
    ("model_pipe", {"path": "sketch:PipeJoinMissPath", "section_size": 6, "operation": "cut",
                    "target_bodies": ["PipeJoinMiss"]},
     _refused("no body's volume changed", "was removed", "checked body shapes were restored",
              "path sketch visibility was restored"), None),
    *_retire_reads("pipe_retire", ["PipeJoinMiss:1", "PipeCut:1"],
                  [("PipeJoinMiss", "PipeJoinTargetS"), ("PipeJoinMiss", "PipeJoinMissPath"),
                   ("PipeCut", "PipeCutS"), ("PipeCut", "PipeCutPath")], after=True),
    ("sketch_get", {"component": "PipeJoinMiss"},
     _pipe_path_visibility, None),
    # then the same path as a JOIN lands an orphan tube, which the error names
    ("model_pipe", {"path": "sketch:PipeJoinMissPath", "section_size": 6, "operation": "join"},
     _refused("no body's volume changed", "operation='join' landed a NEW body (",
              "model_combine(join) merges them"), None),
    ("model_inspect", {"target": "PipeJoinMiss:1", "include": ["default", "mass"], "per_body": True,
                       "accuracy": "very_high", "units": "mm"},
     lambda p: (lambda now, before: _measured("effectful disjoint join retains its new body",
         {"before": before, "now": now}, now is not None and before is not None
         and len(now["bodies"]) == len(before["bodies"]) + 1
         and now["shape"]["volume"] > before["shape"]["volume"]
         and all(any(r["body"] == old["body"] and r["volume"] == old["volume"] for r in now["bodies"])
                 for old in before["bodies"]))) (
             _retire_material_state(p), _RECALL.get("pipe_retire_PipeJoinMiss:1")), None),
    # Retiring the empty cut removes its warning; the disjoint join remains an effectful feature.
    ("assembly_get", {},
     lambda p: _measured("the retired empty pipe leaves no assembly health warning",
                         {"is_healthy": p.get("is_healthy"),
                          "timeline_problems": p.get("timeline_problems"),
                          "timeline_warnings": p.get("timeline_warnings")},
                         p.get("is_healthy") is True and p.get("timeline_problems") == []
                         and p.get("timeline_warnings") == []), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000},
     lambda p: (lambda warned: _measured(
         "the removed empty pipe leaves no warning row",
         {"warned": [(r.get("name"), r.get("message")) for r in warned]},
         not warned))(
         [r for r in ((p.get("timeline") or {}).get("timeline") or [])
          if r.get("health") == "warning" and "Pipe" in (r.get("name") or "")]), None),
    ("workspace_orient", {},
     lambda p: _measured("workspace_orient confirms the empty pipe warning was removed",
                         {"health": p.get("health")},
                         (p.get("health") or {}).get("timeline_errors") == 0
                         and (p.get("health") or {}).get("timeline_warnings") == 0
                         and (p.get("health") or {}).get("is_healthy") is True), None),
    # a d70 CUT across a 100 x 30 x 8 plate: the tube is wider than the plate, so it DISCONNECTS
    # the plate into two bodies - the split is named, not left for 'result_bodies' alone to imply.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "PipeSplit", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "PipeSplitS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 1100, "y1": 0,
                                           "x2": 1200, "y2": 30}],
                             "sketch_name": "PipeSplitS"}, "ok", None),
    ("model_extrude", {"sketch_name": "PipeSplitS", "profile_index": 0, "distance": 8},
     _extruded, None),
    ("sketch_create", {"plane": "xy", "name": "PipeSplitPath"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1150, "y1": -20,
                                           "x2": 1150, "y2": 50}],
                             "sketch_name": "PipeSplitPath"}, "ok", None),
    ("model_pipe", {"path": "sketch:PipeSplitPath", "section_size": 70, "operation": "cut",
                    "target_bodies": ["PipeSplit"]},
     lambda p: _measured("a d70 cut across a 100x30x8 plate DISCONNECTS it into 2 bodies",
                         {"body_split": p.get("body_split"), "note": (p.get("note") or "")[:200]},
                         isinstance(p.get("body_split"), list) and len(p["body_split"]) == 2
                         and "DISCONNECTED" in (p.get("note") or "")), None),
    # A parameter change that breaks a downstream feature: the split plane rides a user parameter,
    # and moving it off the box leaves the split with nothing to cut. param_set names the split
    # among the errors it newly raised; putting the value back clears it.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # placed at x=1300 mm like AxisFrameRig, drawn at the component's own origin: the split plane's
    # offset is a parameter, which a re-packed literal sketch would leave behind.
    ("model_create_component", {"name": "ParamBreak", "activate": True, "x": 1300},
     _made_component, None),
    ("param_add", {"name": "BrkSplitX", "expression": "20 mm"},
     _param_added("BrkSplitX", 20), None),
    ("sketch_create", {"plane": "xy", "name": "ParamBreakS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 0, "y1": 0,
                                           "x2": 40, "y2": 20}],
                             "sketch_name": "ParamBreakS"}, "ok", None),
    ("model_extrude", {"sketch_name": "ParamBreakS", "profile_index": 0, "distance": 10},
     _extruded, None),
    ("model_construction", {"kind": "plane", "plane": "yz", "offset": "BrkSplitX",
                            "name": "BrkSplitPlane"}, _datum_plane("yz"), None),
    ("find_geometry", {"target": "ParamBreak", "kind": "planar_face",
                       "nearest_to": [1310, 10, 10], "max_results": 1}, "ok", _fg("brk_body")),
    ("model_split", lambda c: {"split": "body", "target": _ctx_get(c, "brk_body", "the box"),
                               "split_plane": "BrkSplitPlane"},
     _split_bodies, ("brk_split", _recall("brk_split", lambda p: p["feature"]))),
    ("param_set", {"name": "BrkSplitX", "expression": "200 mm"},
     lambda p: _param_set_to("BrkSplitX", 200)(p) and _measured(
         "param_set names the split its value broke",
         {"split": _RECALL.get("brk_split"), "new_timeline_errors": p.get("new_timeline_errors"),
          "note": p.get("note")},
         _RECALL.get("brk_split") in (p.get("new_timeline_errors") or [])), None),
    ("param_set", {"name": "BrkSplitX", "expression": "20 mm"},
     lambda p: _param_set_to("BrkSplitX", 20)(p) and _measured(
         "restoring the value raised no new error",
         {"new_timeline_errors": p.get("new_timeline_errors")},
         not p.get("new_timeline_errors")), None),
    ("assembly_get", {},
     lambda p: _measured("the split reads healthy again after the restore",
                         {"split": _RECALL.get("brk_split"),
                          "timeline_problems": p.get("timeline_problems")},
                         _RECALL.get("brk_split") not in
                         [r.get("name") for r in (p.get("timeline_problems") or [])]), None),
    # sketch_add_3d_spline: a 2-turn helix (r20 mm, pitch30 mm) as a FITTED spline pipes at d4 to
    # the analytic tube volume (pi*r_section^2*helix_length = 3.2477 cm3, measured within 0.04%);
    # the SAME helix as a CONTROL-POINT spline mints construction lines beside it (one per
    # control-polygon segment) and still pipes as ONE path curve - a pipe ignores construction geometry.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "PipeSpline", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "PipeSplineFitted"}, "ok", None),
    ("sketch_add_3d_spline", {"sketch_name": "PipeSplineFitted", "kind": "fitted",
                              "helix": {"axis": "z", "center": [2800, 0, 0], "radius": 20,
                                        "pitch": 30, "turns": 2}},
     lambda p: p.get("kind") == "fitted" and p.get("point_count") == 49
     and p.get("off_plane") is True, None),
    ("model_pipe", {"path": "sketch:PipeSplineFitted", "section_size": 4},
     lambda p: _measured("a 2-turn r20/pitch30 helix pipes at d4 to the analytic tube volume",
                         {"path_curves": p.get("path_curves"), "volume_cm3": p.get("volume_cm3")},
                         p.get("path_curves") == 1 and _near(p.get("volume_cm3"), 3.2477, 0.033)),
     None),
    ("sketch_create", {"plane": "xy", "name": "PipeSplineControl"}, "ok", None),
    ("sketch_add_3d_spline", {"sketch_name": "PipeSplineControl", "kind": "control", "degree": "3",
                              "helix": {"axis": "z", "center": [2900, 0, 0], "radius": 20,
                                        "pitch": 30, "turns": 2}},
     lambda p: p.get("kind") == "control"
     and (p.get("construction_lines_added") or 0) > 0, None),
    ("model_pipe", {"path": "sketch:PipeSplineControl", "section_size": 4},
     lambda p: p.get("path_curves") == 1, None),
    # BUILD_PATH's measured chaining rule, on two fixtures of its own. ONE seed handle is not one
    # edge: chaining follows TANGENT CONTINUITY and stops where that continuity breaks - a sharp
    # corner ends an open run, while a genuinely tangent loop chains the whole way round ([F52a],
    # and [F68] which corrected [F52b]: the earlier no-chaining reading came from a rig whose
    # junctions ran through fillet corner PATCHES, not from the loop being closed). Neither open
    # nor closed predicts the number, so the label's count is read off the BUILT path - these two
    # beats are what keep the wording honest for every consumer of the shared resolver (sweep /
    # pipe / path pattern / on-path datum).
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "TangentRun", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "TangentRunS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 1900, "y1": 0,
                                           "x2": 1960, "y2": 60}],
                             "sketch_name": "TangentRunS"}, "ok", None),
    ("model_extrude", {"sketch_name": "TangentRunS", "profile_index": 0, "distance": 20},
     _extruded, None),
    # ONE vertical edge rounded: the top rim reads line - arc - line, bounded by sharp corners.
    ("find_geometry", {"target": "TangentRun", "kind": "line_edge", "nearest_to": [1900, 0, 10],
                       "max_results": 1}, "ok", _fg("tr_corner")),
    ("model_fillet", lambda c: {"edges": [_ctx_get(c, "tr_corner", "the box corner edge")],
                                "radius": 8}, _filleted, None),
    # a fillet's rim is an ARC (Arc3D), not a full circle - find_geometry keys its edge kinds off
    # the curve type, so 'circular_edge' does not match it and 'arc_edge' is the pick.
    ("find_geometry", {"target": "TangentRun", "kind": "arc_edge", "nearest_to": [1900, 0, 20],
                       "max_results": 1}, "ok", _fg("tr_arc")),
    ("find_geometry", {"target": "TangentRun", "kind": "line_edge", "nearest_to": [1940, 0, 20],
                       "max_results": 1}, "ok", _fg("tr_line")),
    # TWO handles are used EXACTLY - no chaining at all - and the label says which of the two rules
    # ran, so a list quietly chained into more edges could not report this.
    ("find_geometry", {"target": "TangentRun", "kind": "planar_face", "nearest_to": [1930, 30, 20],
                       "max_results": 1}, "ok", _fg("tr_body")),
    ("model_pattern_path", lambda c: {"bodies": [_ctx_get(c, "tr_body", "the tangent-run body")],
                                      "path": [_ctx_get(c, "tr_arc", "the fillet arc"),
                                               _ctx_get(c, "tr_line", "the tangent-adjacent line")],
                                      "quantity": 2, "distance": 6, "distance_type": "spacing"},
     lambda p: p.get("path") == "2 edge(s) from 2 handles, used exactly", None),
    # ONE seed on the OPEN run: the arc chains across both tangent connections, so the built path
    # holds MORE than the seed.
    ("model_pipe", lambda c: {"path": _ctx_get(c, "tr_arc", "the fillet arc"), "section_size": 3},
     lambda p: _path_count(p.get("path"), 1) > 1, None),
    # the CLOSED tangent loop: all four verticals rounded, so the top rim is 4 lines + 4 arcs, every
    # junction tangent. One seed chains the WHOLE loop - all 8 edges - and the built path reports
    # itself closed. Rounding the VERTICALS is what makes the junctions tangent: rounding the top
    # edges instead puts a corner patch at each junction and the chain stops there ([F68]).
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "TangentLoop", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "TangentLoopS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 2000, "y1": 0,
                                           "x2": 2060, "y2": 60}],
                             "sketch_name": "TangentLoopS"}, "ok", None),
    ("model_extrude", {"sketch_name": "TangentLoopS", "profile_index": 0, "distance": 20},
     _extruded, None),
    # each vertical edge is the nearest line edge to its own corner at mid-height (10 mm away from
    # the two horizontals meeting there), so the four picks are unambiguous.
    ("find_geometry", {"target": "TangentLoop", "kind": "line_edge", "nearest_to": [2000, 0, 10],
                       "max_results": 1}, "ok", _fg("tl_e1")),
    ("find_geometry", {"target": "TangentLoop", "kind": "line_edge", "nearest_to": [2060, 0, 10],
                       "max_results": 1}, "ok", _fg("tl_e2")),
    ("find_geometry", {"target": "TangentLoop", "kind": "line_edge", "nearest_to": [2060, 60, 10],
                       "max_results": 1}, "ok", _fg("tl_e3")),
    ("find_geometry", {"target": "TangentLoop", "kind": "line_edge", "nearest_to": [2000, 60, 10],
                       "max_results": 1}, "ok", _fg("tl_e4")),
    ("model_fillet", lambda c: {"edges": [_ctx_get(c, "tl_e1", "loop corner 1"),
                                          _ctx_get(c, "tl_e2", "loop corner 2"),
                                          _ctx_get(c, "tl_e3", "loop corner 3"),
                                          _ctx_get(c, "tl_e4", "loop corner 4")],
                                "radius": 8}, _filleted, None),
    ("find_geometry", {"target": "TangentLoop", "kind": "arc_edge",
                       "nearest_to": [2000, 0, 20], "max_results": 1}, "ok", _fg("tl_arc")),
    ("model_pipe", lambda c: {"path": _ctx_get(c, "tl_arc", "one arc of the closed tangent loop"),
                              "section_size": 3},
     lambda p: _measured("closed tangent loop: want 8 edges from 1 seed, closed",
                         {"path": p.get("path"), "path_closed": p.get("path_closed")},
                         _path_count(p.get("path"), 1) == 8
                         and p.get("path_closed") is True), None),
    # THE SAME CLOSED RIM, now as an edge TREATMENT target: one handle on the front top line, cut
    # with tangent_chain=false. edges_cut is read off the feature's own edge set, and the rim
    # OPPOSITE is then read independently - a chain that reached it would put a 45 deg bevel face
    # centred exactly where the query looks.
    ("find_geometry", {"target": "TangentLoop", "kind": "line_edge", "nearest_to": [2030, 0, 20],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("tl_rim_front")),
    ("model_chamfer", lambda c: {"edges": [_ctx_get(c, "tl_rim_front", "the front top rim line")],
                                 "distance": 1, "tangent_chain": False},
     _cut_exactly("chamfer", 1), None),
    ("find_geometry", {"target": "TangentLoop", "kind": "planar_face",
                       "nearest_to": [2030, 59.5, 19.5], "max_results": 1},
     _axis_aligned_face_at(2030, 59.5, 19.5), None),
    # and the DEFAULT on the back rim line: the seeds chain, so the feature cuts more edges than the
    # one handle it was given. The number is read off the built feature - the beat above broke the
    # rim's tangency at the front, so how far this chain reaches is not something to predict.
    ("find_geometry", {"target": "TangentLoop", "kind": "line_edge", "nearest_to": [2030, 60, 20],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("tl_rim_back")),
    ("model_chamfer", lambda c: {"edges": [_ctx_get(c, "tl_rim_back", "the back top rim line")],
                                 "distance": 1}, _cut_a_chain("chamfer", 1), None),
    # A PARKED MARKER, which reading the resolved edge set has to move and put back. Rolling to the
    # previous step parks it before the chamfer above; the cut below lands at the marker, and the
    # rolled-out feature has to still be rolled out afterwards. The seed is the front BOTTOM rim,
    # which no earlier beat has touched.
    # the parked INDEX is saved off the roll's own receipt: it is where the cut below lands, and a
    # feature name cannot say that - names are component-local and the Bracket has chamfers of its
    # own carrying the same ones.
    ("design_edit_timeline", {"action": "roll", "to": "previous"},
     lambda p: _measured("one feature rolled out", {"rolled_back": p.get("rolled_back"),
                                                    "marker_position": p.get("marker_position")},
                         p.get("rolled") is True and p.get("rolled_back") == 1),
     ("parked_at", _recall("parked_at", lambda p: p["marker_position"]))),
    ("find_geometry", {"target": "TangentLoop", "kind": "line_edge", "nearest_to": [2030, 0, 0],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("tl_rim_low")),
    ("model_chamfer", lambda c: {"edges": [_ctx_get(c, "tl_rim_low", "the front bottom rim line")],
                                 "distance": 1, "tangent_chain": False},
     _cut_exactly("chamfer", 1),
     ("parked_chamfer", _recall("parked_chamfer", lambda p: p["feature"]))),
    # the INDEPENDENT read: the design's own timeline, not the chamfer's receipt.
    ("design_get", {"include": ["timeline"], "max_results": 2000},
     _marker_parked_after("parked_at", "parked_chamfer"), None),
    ("design_edit_timeline", {"action": "roll", "to": "end"},
     lambda p: _measured("nothing left rolled out", {"rolled_back": p.get("rolled_back")},
                         p.get("rolled") is True and p.get("rolled_back") == 0), None),
    # THE BLANKET call, on a box of its own: every one of a cuboid's 12 edges is a sharp corner with
    # no tangent junction to chain across, so the resolved set is the swept set.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "BlanketBox", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "BlanketS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 2200, "y1": 0,
                                           "x2": 2220, "y2": 20}],
                             "sketch_name": "BlanketS"}, "ok", None),
    ("model_extrude", {"sketch_name": "BlanketS", "profile_index": 0, "distance": 10},
     _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_chamfer", {"body_name": "BlanketBox", "edge_filter": "all", "distance": 1},
     _cut_exactly("chamfer", 12, chain=True), None),
    # FULL ROUND, on a slab of its own: one face replaced by a round tangent to the two beside it,
    # so the radius comes from the geometry and 'radius' does not drive it at all.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "FullRound", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "FullRoundS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 2100, "y1": 0,
                                           "x2": 2180, "y2": 40}],
                             "sketch_name": "FullRoundS"}, "ok", None),
    ("model_extrude", {"sketch_name": "FullRoundS", "profile_index": 0, "distance": 10},
     _extruded, None),
    ("find_geometry", {"target": "FullRound", "kind": "planar_face", "nearest_to": [2140, 0, 5],
                       "max_results": 1}, _matched(1, "planar_face"), _fg("fr_side")),
    ("find_geometry", {"target": "FullRound", "kind": "planar_face", "nearest_to": [2140, 20, 0],
                       "max_results": 1}, _matched(1, "planar_face"), _fg("fr_bottom")),
    ("find_geometry", {"target": "FullRound", "kind": "planar_face", "nearest_to": [2140, 20, 10],
                       "max_results": 1}, _matched(1, "planar_face"), _fg("fr_top")),
    ("model_fillet", lambda c: {"fillet_type": "full_round",
                                "center_face": _ctx_get(c, "fr_side", "the face to round away"),
                                "faces": [_ctx_get(c, "fr_bottom", "the slab's underside")],
                                "second_faces": [_ctx_get(c, "fr_top", "the slab's top")]},
     _full_rounded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # Section lifecycle: preserve the camera, retain both generated names, remove one exact cut,
    # and independently read the surviving decoy before the existing clear-all cleanup.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    _watch("Bracket:1"),
    ("workspace_orient", {}, lambda p: bool(_section_camera(p)),
     ("section_camera_before", _recall("section_camera_before", _section_camera))),
    ("view_section", {"action": "cut", "plane": "xz", "offset": 0, "auto_view": False},
     _section_created(), ("section_one", _recall("section_one", lambda p: p["section"]))),
    ("view_section", {"action": "cut", "plane": "xy", "offset": 0, "auto_view": False},
     _section_created("section_one"),
     ("section_two", _recall("section_two", lambda p: p["section"]))),
    ("view_section", {"action": "list"},
     _section_census(("section_one", "section_two"), (False, True)), None),
    ("view_section", {"action": "clear", "section": "SweepNoSuchSection"},
     _refused("no section named", "Available"), None),
    ("view_section", {"action": "list"},
     _section_census(("section_one", "section_two"), (False, True)), None),
    ("view_section", lambda c: {"action": "clear",
                                "section": _ctx_get(c, "section_one", "the first generated cut")},
     _section_named_clear("section_one"), None),
    ("view_section", {"action": "list"},
     _section_census(("section_two",), (True,)), None),
    ("workspace_orient", {}, _section_camera_unchanged("section_camera_before"), None),
    ("view_screenshot", {"width": 500, "height": 400}, "ok", None),
    ("view_section", {"action": "clear"},
     lambda p: (p["removed"] == [_RECALL.get("section_two")]
                and p["removed_count"] == p["sections_before"] == 1
                and p["sections_after"] == 0), None),
    ("view_screenshot_multi", {"views": ["front", "top"], "width": 400, "height": 300}, "ok", None),
    # THE RASTER WRITER (NEW-13): file_path also writes the rendered PNG to disk - the extension is
    # appended, the landed file is verified non-zero, and path + size are published beside the
    # inline image. The fleet's only raster writer, which is what feeds drawing_insert_image.
    ("view_screenshot", {"width": 400, "height": 300,
                         "file_path": _SHOT_PATH},
     lambda p: "w4_shot.png" in str(p) and "size_bytes=" in str(p), None),
    # a second write to the SAME path lands without a refusal - the overwrite behaviour that makes
    # this tool write-kind (and puts it behind the write guard below).
    ("view_screenshot", {"width": 200, "height": 150,
                         "file_path": _SHOT_PATH},
     lambda p: "w4_shot.png" in str(p) and "size_bytes=" in str(p), None),
    ("view_screenshot", {"width": 200, "height": 150,
                         "file_path": _SHOT_PATH,
                         "expect_document": "ZzNoSuchDocument"},
     _refused("active_document_changed"), None),
    # The dimension/constraint beats that measure TO a model face sit at the end of the act,
    # not in the middle of the modelling: they are sketch work, and they are here only
    # because a face is what they measure against.
    # the angular wedge rule: a horizontal and a 60 deg line crossing far from the origin. The
    # measured contract dims the wedge FACING THE SKETCH ORIGIN - 60 deg, not the 120 supplement.
    ("sketch_create", {"plane": "xy", "name": "W3Dims"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 900, "y1": 100,
                                           "x2": 920, "y2": 100}],
                             "sketch_name": "W3Dims"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 905, "y1": 91.34,
                                           "x2": 915, "y2": 108.66}],
                             "sketch_name": "W3Dims"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "angle", "entity_one": "line:0",
                                          "entity_two": "line:1"}],
                          "sketch_name": "W3Dims"},
     lambda p: "deg" in (p["results"][0].get("value") or "")
     and abs(float((p["results"][0].get("value") or "0 x").split()[0]) - 60) < 0.1, None),
    # offset with a NON-parallel second line: the constraint ROTATES it parallel (geometry moves,
    # no raise) and the note says so.
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 940, "y1": 100,
                                           "x2": 960, "y2": 100}],
                             "sketch_name": "W3Dims"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 940, "y1": 110,
                                           "x2": 960, "y2": 113}],
                             "sketch_name": "W3Dims"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "offset", "entity_one": "line:2",
                                          "entity_two": "line:3"}],
                          "sketch_name": "W3Dims"},
     lambda p: "ROTAT" in (p["results"][0].get("note") or ""), None),
    # linear_diameter with the same shape REFUSES - the API's own parallelism sentence surfaces.
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 980, "y1": 100,
                                           "x2": 1000, "y2": 100}],
                             "sketch_name": "W3Dims"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 980, "y1": 110,
                                           "x2": 1000, "y2": 114}],
                             "sketch_name": "W3Dims"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "linear_diameter", "entity_one": "line:4",
                                          "entity_two": "line:5"}],
                          "sketch_name": "W3Dims"}, "refused", None),
    # line/point vs a MODEL face: the ShellCap outer -X wall sits on the x=400 plane, 620 mm from
    # a line at x=1020. The value is read back off the parameter; the surface label is the
    # RESOLVED entity, so 'BRepFace' proves the payload is not echoing the handle string.
    ("find_geometry", {"target": "ShellCap", "kind": "planar_face", "nearest_to": [400, 15, 10],
                       "max_results": 1}, "ok", _fg("w3_wall")),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1020, "y1": 100,
                                           "x2": 1020, "y2": 140}],
                             "sketch_name": "W3Dims"}, "ok", None),
    ("sketch_dimension", lambda c: {"dimensions": [{
        "dim_type": "line_to_surface", "entity_one": "line:6",
        "surface": _ctx_get(c, "w3_wall", "shell wall")}],
        "sketch_name": "W3Dims"},
     lambda p: "mm" in (p["results"][0].get("value") or "")
     and abs(float((p["results"][0].get("value") or "0 x").split()[0])
             - abs(_px("W3Dims", 1020) - _px("ShellCap", 400))) < 0.1
     and p["results"][0].get("surface") == "BRepFace", None),
    # a line NOT parallel to that wall refuses with the API's self-naming error.
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1040, "y1": 100,
                                           "x2": 1060, "y2": 100}],
                             "sketch_name": "W3Dims"}, "ok", None),
    ("sketch_dimension", lambda c: {"dimensions": [{
        "dim_type": "line_to_surface", "entity_one": "line:7",
        "surface": _ctx_get(c, "w3_wall", "shell wall")}],
        "sketch_name": "W3Dims"}, "refused", None),
    # anchored on line:7 (undimensioned - the refused line_to_surface left it free): dimensioning
    # line:6's own endpoint against the same wall it is dimensioned to over-constrains the sketch.
    ("sketch_dimension", lambda c: {"dimensions": [{
        "dim_type": "point_to_surface", "entity_one": "line:7:start",
        "surface": _ctx_get(c, "w3_wall", "shell wall")}],
        "sketch_name": "W3Dims"},
     lambda p: p["results"][0].get("surface") == "BRepFace", None),
    # shared-resolver regression: the point dim's resolver allows curved faces; the constrain
    # tool rides the same _inputs.resolve_surface, so a cylinder accepted here and refused for
    # line_on_surface pins the allow_curved split. Fresh sketch: the origin point is point:0,
    # so the drawn point is point:1.
    ("sketch_create", {"plane": "xy", "name": "W3Pt"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "point", "cx": 1080, "cy": 100}],
                             "sketch_name": "W3Pt"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1080, "y1": 120,
                                           "x2": 1100, "y2": 120}],
                             "sketch_name": "W3Pt"}, "ok", None),
    ("sketch_constrain", lambda c: {"constraints": [{
        "constraint": "coincident_to_surface", "entity_one": "point:1",
        "surface": _ctx_get(c, "post_wall", "thread post wall")}],
        "sketch_name": "W3Pt"},
     lambda p: p["results"][0].get("surface") == "BRepFace", None),
    ("sketch_constrain", lambda c: {"constraints": [{
        "constraint": "line_on_surface", "entity_one": "line:0",
        "surface": _ctx_get(c, "post_wall", "thread post wall")}],
        "sketch_name": "W3Pt"}, "refused", None),
    *_face_point_witness_rows(),
]


def _parameter_witness_rows():
    rows = [("doc_get", {}, _home_document, ("parameter_witness_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "parameter_witness_home", "home")},
             _new_document, ("parameter_witness_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        if tool in {"design_get", "model_inspect", "param_get"}:
            rows.append((tool, args, check, save))
        else:
            rows.append((tool, lambda c, args=args: _combine_pin(
                c, "parameter_witness_doc", args(c) if callable(args) else args), check, save))

    write("model_create_component", {"name": "ScaleExpressionWitness", "activate": True}, _made_component)
    write("sketch_create", {"plane": "xy", "name": "ScaleExpressionWitnessS"})
    write("sketch_add_geometry", {"sketch_name": "ScaleExpressionWitnessS", "geometry": [
        {"kind": "rectangle", "x1": 2000, "y1": 0, "x2": 2010, "y2": 20}]})
    write("model_extrude", {"sketch_name": "ScaleExpressionWitnessS", "profile_index": 0,
                           "distance": 5}, _extruded)
    write("param_add", {"name": "ScaleWitnessK", "expression": "1.5", "unit": ""},
          lambda p: p.get("added") is True and (p.get("parameter") or {}).get("name") == "ScaleWitnessK")
    write("model_inspect", {"target": "ScaleExpressionWitness:1", "include": ["default", "mass"],
                            "units": "mm", "accuracy": "very_high"},
          _scale_expression_state(1000, {"min_x": 2000, "max_x": 2010,
              "min_y": 0, "max_y": 20, "min_z": 0, "max_z": 5}))
    write("model_scale", {"bodies": ["ScaleExpressionWitness"], "factor": "ScaleWitnessK"},
          lambda p: p.get("scaled") is True and p.get("resolved_factor") == 1.5,
          ("scale_expression_feature", _recall("scale_expression_feature", lambda p: p["feature"])))
    write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
          _capture_scale_factor)
    write("param_set", lambda c: {"name": _RECALL.get("scale_expression_parameter"),
                                  "expression": "ScaleWitnessK"})
    write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
          _scale_expression_parameter_read("ScaleWitnessK", 1.5))
    write("model_inspect", {"target": "ScaleExpressionWitness:1", "include": ["default", "mass"],
                            "units": "mm", "accuracy": "very_high"},
          _scale_expression_state(3375, {"min_x": 3000, "max_x": 3015,
              "min_y": 0, "max_y": 30, "min_z": 0, "max_z": 7.5}))
    write("param_set", {"name": "ScaleWitnessK", "expression": "2"})
    write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
          _scale_expression_parameter_read("ScaleWitnessK", 2.0))
    write("model_inspect", {"target": "ScaleExpressionWitness:1", "include": ["default", "mass"],
                            "units": "mm", "accuracy": "very_high"},
          _scale_expression_state(8000, {"min_x": 4000, "max_x": 4020,
              "min_y": 0, "max_y": 40, "min_z": 0, "max_z": 10}))

    write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
          _capture_parameter_timeline)
    for name in ("W", "mm", "N", "s", "kg", "1Len", "Len A", "Len-A"):
        write("param_add", {"name": name, "expression": "1 mm", "unit": "mm"},
              _parameter_refusal_text(name))
        if name == "W":
            write("param_set", {"name": "W", "expression": "1 mm", "create": True, "unit": "mm"},
                  _refused("Could not create user parameter 'W'", "param name is not valid"))
    write("param_add", {"name": "Wd", "expression": "1 mm", "unit": "mm"},
          lambda p: p.get("added") is True and (p.get("parameter") or {}).get("name") == "Wd")
    write("param_get", {}, _capture_exact_user_parameters, None)
    write("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 2000},
          _verify_parameter_timeline)
    rows.extend([("doc_activate", lambda c: {"name": _ctx_get(
        c, "parameter_witness_home", "home"), "expect_document": _ctx_get(
        c, "parameter_witness_doc", "scratch")}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(
            c, "parameter_witness_doc", "scratch"), "save_changes": False,
            "expect_document": _ctx_get(c, "parameter_witness_home", "home")},
         _document_closed, None)])
    return rows


def _scale_expression_parameter_read(expression, value):
    def check(p):
        rows = [r for r in (p.get("timeline") or {}).get("timeline", [])
                if r.get("name") == _RECALL.get("scale_expression_feature")
                and r.get("component") == "ScaleExpressionWitness"]
        params = (rows[0].get("params") or []) if len(rows) == 1 else []
        matches = [r for r in params if r.get("name") == _RECALL.get("scale_expression_parameter")]
        got = matches[0] if len(matches) == 1 else {}
        return _measured("scale factor expression and value", got,
                         len(matches) == 1 and got.get("role") == "ScaleFactor"
                         and got.get("expression") == expression and _near(got.get("value"), value, 1e-6)
                         and _parameter_timeline_healthy(p))
    return check


def _parameter_timeline_healthy(p):
    timeline = p.get("timeline") or {}
    summary = timeline.get("summary") or {}
    rows = timeline.get("timeline") or []
    return (timeline.get("truncated", False) is False and timeline.get("returned") == timeline.get("count")
            and set(summary.get("states") or {}) == {"healthy"}
            and isinstance(summary.get("exceptions"), list) and not summary.get("exceptions")
            and all(r.get("health", "healthy") == "healthy"
                    and r.get("is_rolled_back", False) is False for r in rows))


def _capture_parameter_timeline(p):
    timeline = p.get("timeline") or {}
    rows = timeline.get("timeline") or []
    _RECALL["parameter_witness_timeline"] = [
        (r.get("name"), r.get("type"), r.get("health", "healthy")) for r in rows]
    return _measured("parameter refusal timeline baseline", _RECALL["parameter_witness_timeline"],
                     bool(rows) and _parameter_timeline_healthy(p))


def _verify_parameter_timeline(p):
    timeline = p.get("timeline") or {}
    rows = timeline.get("timeline") or []
    state = [(r.get("name"), r.get("type"), r.get("health", "healthy")) for r in rows]
    return _measured("name refusals leave the healthy timeline unchanged", state,
                     state == _RECALL.get("parameter_witness_timeline")
                     and _parameter_timeline_healthy(p))


_DETAILS += _parameter_witness_rows()


_RN = {"a": "RenameWitnessA", "b": "RenameWitnessB", "plane": "RenameSharedPlane",
       "axis": "RenameSharedAxis", "point": "RenameSharedPoint",
       "origin": "RenameSharedOrigin", "joint": "RenameWitnessJoint"}
_RN_NEW = {"feature": "RenameFeatureMoved", "joint": "RenameJointMoved",
           "joint_origin": "RenameOriginMoved", "plane": "RenamePlaneMoved",
           "axis": "RenameAxisMoved", "point": "RenamePointMoved"}


def _rn_extrude(p, owner, key):
    feature, body = p.get("feature"), (p.get("result_bodies") or [None])[0]
    good = p.get("extruded") is True and p.get("component") == owner and feature and body and feature != body
    if good:
        _RECALL[key] = {"feature": feature, "body": body}
    return _measured("public extrusion fixture route assumption", {
        "component": p.get("component"), "feature": feature, "body": body}, good)


def _rn_design(stage):
    def check(p):
        history, tree, datums = p.get("timeline") or {}, p.get("tree") or {}, p.get("datums") or {}
        rows, children, datum_rows = history.get("timeline") or [], tree.get("children") or [], datums.get("datums") or []
        a, b = _RN["a"], _RN["b"]
        f = (_RECALL.get("rn_feature_a") or {}).get("feature")
        if stage == "baseline":
            specs = [("feature", f, "ExtrudeFeature", a), ("joint", _RN["joint"], "Joint", None),
                     ("joint_origin", _RN["origin"], "JointOrigin", a),
                     ("plane", _RN["plane"], "ConstructionPlane", a),
                     ("axis", _RN["axis"], "ConstructionAxis", a),
                     ("point", _RN["point"], "ConstructionPoint", a)]
            selected = {}
            for key, name, typ, comp in specs:
                hits = [r for r in rows if r.get("name") == name and r.get("type") == typ
                        and (comp is None or r.get("component") == comp)]
                if len(hits) == 1:
                    selected[key] = (hits[0].get("index"), name, typ, hits[0].get("component"))
            na = [n for n in children if n.get("component") == a]
            nb = [n for n in children if n.get("component") == b]
            ba = (na[0].get("bodies") or []) if len(na) == 1 else []
            bb = (nb[0].get("bodies") or []) if len(nb) == 1 else []
            good = (len(selected) == len(specs) and len(na) == len(nb) == 1
                    and tree.get("truncated") is False and tree.get("children_truncated") is False
                    and len(ba) == len(bb) == 1 and ba[0].get("name") == f
                    and bb[0].get("name") == (_RECALL.get("rn_feature_b") or {}).get("body")
                    and sum(r.get("component") == a and r.get("kind") == "construction_plane"
                            and r.get("name") == _RN["plane"] for r in datum_rows) == 1
                    and sum(r.get("component") == b and r.get("kind") == "construction_plane"
                            and r.get("name") == _RN["plane"] for r in datum_rows) == 1)
            if good:
                _RECALL["rn_timeline"] = [(r.get("index"), r.get("name"), r.get("type"),
                                            r.get("component"), r.get("health", "healthy")) for r in rows]
                _RECALL["rn_indexes"] = {k: v[0] for k, v in selected.items()}
                _RECALL["rn_count"] = history.get("count")
                _RECALL["rn_marker"] = history.get("marker_position")
                _RECALL["rn_summary"] = history.get("summary")
                _RECALL["rn_body_names"] = (ba[0].get("name"), bb[0].get("name"))
            return _measured("rename fixture exposes two owners, repeated datum names, and a body/feature name collision",
                             {"selected_timeline": selected, "bodies": [ba, bb],
                              "duplicate_planes": [(r.get("component"), r.get("name"))
                                                   for r in datum_rows if r.get("kind") == "construction_plane"
                                                   and r.get("name") == _RN["plane"]]}, good)
        baseline = _RECALL.get("rn_timeline") or []
        indexes = _RECALL.get("rn_indexes") or {}
        changes = ({indexes["feature"]: _RN_NEW["feature"], indexes["joint"]: _RN_NEW["joint"],
                    indexes["joint_origin"]: _RN_NEW["joint_origin"], indexes["plane"]: _RN_NEW["plane"],
                    indexes["axis"]: _RN_NEW["axis"], indexes["point"]: _RN_NEW["point"]}
                   if stage == "renamed" else {})
        current = [(r.get("index"), r.get("name"), r.get("type"), r.get("component"),
                    r.get("health", "healthy")) for r in rows]
        expected = [(i, changes.get(i, name), typ, comp, health)
                    for i, name, typ, comp, health in baseline]
        body_rows = []
        for owner in (a, b):
            nodes = [n for n in children if n.get("component") == owner]
            body_rows.append((nodes[0].get("bodies") or []) if len(nodes) == 1 else [])
        expected_bodies = _RECALL.get("rn_body_names") or ()
        datum_checks = [(a, "construction_plane", _RN_NEW["plane"] if stage == "renamed" else _RN["plane"]),
                        (b, "construction_plane", _RN["plane"]),
                        (a, "construction_axis", _RN_NEW["axis"] if stage == "renamed" else _RN["axis"]),
                        (b, "construction_axis", _RN["axis"]),
                        (a, "construction_point", _RN_NEW["point"] if stage == "renamed" else _RN["point"]),
                        (b, "construction_point", _RN["point"])]
        datums_ok = all(sum(r.get("component") == owner and r.get("kind") == kind
                            and r.get("name") == name for r in datum_rows) == 1
                        for owner, kind, name in datum_checks)
        good = (current == expected and history.get("count") == _RECALL.get("rn_count")
                and type(history.get("count")) is int
                and type(history.get("returned")) is int
                and history.get("count") == history.get("returned") == len(rows)
                and history.get("marker_position") == _RECALL.get("rn_marker")
                and history.get("summary") == _RECALL.get("rn_summary")
                and len(body_rows) == 2
                and all(len(x) == 1 for x in body_rows)
                and tuple(x[0].get("name") for x in body_rows) == expected_bodies
                and (tree.get("truncated") is False) and datums_ok)
        return _measured(f"{stage} exact timeline index, duplicate datum owner, and body control",
                         {"timeline_count": history.get("count"), "timeline": current,
                          "body_names": [x[0].get("name") for x in body_rows if len(x) == 1],
                          "datums": [(r.get("component"), r.get("kind"), r.get("name"))
                                     for r in datum_rows if r.get("component") in (a, b)]}, good)
    return check


def _rn_vector(value, unit=False):
    """Require a finite three-vector, optionally normalized."""
    valid = isinstance(value, (list, tuple)) and len(value) == 3 and all(
        _near(v, 0, float("inf")) for v in value)
    return valid and (not unit or _near(sum(v * v for v in value), 1.0, 0.02))


def _rn_frame(value, position_key, axis_keys):
    """Require finite position and all three finite unit frame axes."""
    return isinstance(value, dict) and (not position_key or _rn_vector(value.get(position_key))) and all(
        _rn_vector(value.get(key), unit=True) for key in axis_keys)


def _rn_geometry(owner, kind, name, stage):
    def check(p):
        rows = p.get("matches") or []
        row = rows[0] if len(rows) == 1 else {}
        key = f"rn_geom_{owner}_{kind}"
        frame = {k: row.get(k) for k in ("position", "normal", "direction") if row.get(k) is not None}
        shape_ok = _rn_vector(frame.get("position")) and (
            _rn_vector(frame.get("normal"), unit=True) if kind == "construction_plane" else
            _rn_vector(frame.get("direction"), unit=True) if kind == "construction_axis" else True)
        if stage == "baseline" and rows and shape_ok:
            _RECALL[key] = frame
            frame_ok = True
        else:
            before = _RECALL.get(key) or {}
            frame_ok = shape_ok and set(frame) == set(before) and all(
                len(frame[k]) == len(before[k]) and all(_near(x, y, 0.001)
                    for x, y in zip(frame[k], before[k])) for k in frame)
        return _measured(f"{stage} {owner} {kind} name, owner and frame", {"match_count": p.get("match_count"),
            "matches": rows}, p.get("incomplete") is not True and p.get("match_count") == 1
            and p.get("returned") == 1 and row.get("name") == name
            and row.get("occurrence") == owner + ":1" and frame_ok)
    return check


def _rn_assembly(stage):
    def check(p):
        origins = p.get("joint_origins") or []
        joints = p.get("joints") or []
        first_name = _RN_NEW["joint_origin"] if stage == "renamed" else _RN["origin"]
        joint_name = _RN_NEW["joint"] if stage == "renamed" else _RN["joint"]
        a, b = _RN["a"], _RN["b"]
        first = [r for r in origins if r.get("component") == a and r.get("name") == first_name]
        second = [r for r in origins if r.get("component") == b and r.get("name") == _RN["origin"]]
        joint = [r for r in joints if r.get("name") == joint_name]
        first_state = (first[0].get("world_position"), first[0].get("frame")) if len(first) == 1 else (None, None)
        second_state = (second[0].get("world_position"), second[0].get("frame")) if len(second) == 1 else (None, None)
        joint_state = ({k: joint[0].get(k) for k in
                        ("healthy", "occurrence_one_path", "occurrence_two_path", "frame")}
                       if len(joint) == 1 else {})
        axes = ("x_axis", "y_axis", "z_axis")
        jo_frames_ok = (_rn_vector(first_state[0]) and _rn_frame(first_state[1], "", axes)
                        and _rn_vector(second_state[0]) and _rn_frame(second_state[1], "", axes))
        joint_frame = joint_state.get("frame") or {}
        joint_frame_ok = _rn_vector(joint_frame.get("origin")) and all(
            _rn_vector(joint_frame.get(axis), unit=True) for axis in axes)
        if stage == "baseline" and len(first) == len(second) == len(joint) == 1 and jo_frames_ok and joint_frame_ok:
            _RECALL["rn_frames"] = {"a": first_state, "b": second_state, "joint": joint_state}
        before = _RECALL.get("rn_frames") or {}
        good = (jo_frames_ok and joint_frame_ok and p.get("is_healthy") is True and p.get("joint_origins_truncated") is False
                and p.get("joints_truncated") is False and len(first) == len(second) == len(joint) == 1
                and first[0].get("qualified_name") == a + ":1:" + first_name
                and second[0].get("qualified_name") == b + ":1:" + _RN["origin"]
                and (first[0].get("world_position"), first[0].get("frame")) == before.get("a")
                and (second[0].get("world_position"), second[0].get("frame")) == before.get("b")
                and {k: joint[0].get(k) for k in before.get("joint", {})} == before.get("joint")
                and joint[0].get("healthy") is True)
        return _measured(f"{stage} joint and Joint Origin public frame census",
                         {"joint": joint, "first_origin": first, "second_origin": second}, good)
    return check


def _rn_body(p, owner, stage):
    state = _bodyref_scale_state(p)
    if state is None:
        return _measured(f"{stage} {owner} body read", p, False)
    key = "rn_body_" + owner
    if stage == "baseline":
        _RECALL[key] = state
        return _measured(f"baseline {owner} body geometry", state, True)
    before = _RECALL.get(key) or {}
    same = (len(state["values"]) == len(before.get("values", []))
            and all(_near(x, y, 0.02) for x, y in zip(state["values"], before["values"]))
            and all(_near(state[part][axis], before[part][axis], 0.02)
                    for part in ("min", "max") for axis in "xyz"))
    return _measured(f"{stage} {owner} body bounds and mass unchanged", state, same)


def _rn_final_design(p):
    history, tree = p.get("timeline") or {}, p.get("tree") or {}
    rows = history.get("timeline") or []
    expected = _RECALL.get("rn_timeline") or []
    current = [(r.get("index"), r.get("name"), r.get("type"), r.get("component"),
                r.get("health", "healthy")) for r in rows]
    children = tree.get("children") or []
    node = [n for n in children if n.get("component") == _RN["a"]]
    bodies = (node[0].get("bodies") or []) if len(node) == 1 else []
    original_body = (_RECALL.get("rn_feature_a") or {}).get("body")
    good = (current == expected and history.get("count") == _RECALL.get("rn_count")
            and history.get("marker_position") == _RECALL.get("rn_marker")
            and history.get("summary") == _RECALL.get("rn_summary")
            and tree.get("truncated") is False and len(bodies) == 1
            and bodies[0].get("name") == original_body)
    return _measured("final original body name and restored feature history", {
        "timeline": current, "body": bodies}, good)


def _namespace_rename_witness_rows():
    rows = []
    def add(tool, args, check="ok", save=None):
        rows.append((tool, args, check, save))
    a, b = _RN["a"], _RN["b"]
    add("design_activate_component", {"occurrence": "root"})
    add("model_create_component", {"name": a, "x": 5000, "units": "mm", "activate": True}, _made_component)
    add("sketch_create", {"plane": "xy", "name": a + "Sketch"})
    add("sketch_add_geometry", {"sketch_name": a + "Sketch", "units": "mm",
        "geometry": [{"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}]})
    add("model_extrude", {"sketch_name": a + "Sketch", "distance": 10, "units": "mm"},
        lambda p: _rn_extrude(p, a, "rn_feature_a"))
    add("find_geometry", {"target": a + ":1", "kind": "planar_face", "nearest_to": [5010, 10, 10],
        "units": "mm", "max_results": 1}, "ok", _fg("rn_body_face"))
    add("design_set_name", lambda c: {"target": _ctx_get(c, "rn_body_face", "first body face"),
        "new_name": (_RECALL.get("rn_feature_a") or {}).get("feature"), "kind": "target"},
        lambda p: p.get("changed") is True and p.get("kind") == "body"
        and p.get("name") == (_RECALL.get("rn_feature_a") or {}).get("feature"))
    add("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy", "offset": 2,
        "units": "mm", "name": _RN["plane"]},
        lambda p: p.get("created") is True and p.get("component") == a and p.get("name") == _RN["plane"])
    add("model_construction", {"kind": "axis", "mode": "two_planes", "plane": "xy", "plane2": "xz",
        "name": _RN["axis"]},
        lambda p: p.get("created") is True and p.get("component") == a and p.get("name") == _RN["axis"])
    add("sketch_create", {"plane": "xy", "name": a + "PointSketch"})
    add("sketch_add_geometry", {"sketch_name": a + "PointSketch", "units": "mm",
        "geometry": [{"kind": "point", "cx": 10, "cy": 10}]})
    add("model_construction", {"kind": "point", "mode": "at_point", "name": _RN["point"],
        "points": [a + "PointSketch/point:1"]},
        lambda p: p.get("created") is True and p.get("component") == a and p.get("name") == _RN["point"])
    add("joint_create_origin", {"anchor": "coordinates", "target": "origin", "component": a + ":1",
        "name": _RN["origin"], "units": "mm"},
        lambda p: p.get("created") is True and p.get("component") == a
        and p.get("joint_origin_name") == _RN["origin"])
    add("design_activate_component", {"occurrence": "root"})
    add("model_create_component", {"name": b, "x": 5050, "units": "mm", "activate": True}, _made_component)
    add("sketch_create", {"plane": "xy", "name": b + "Sketch"})
    add("sketch_add_geometry", {"sketch_name": b + "Sketch", "units": "mm",
        "geometry": [{"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}]})
    add("model_extrude", {"sketch_name": b + "Sketch", "distance": 10, "units": "mm"},
        lambda p: _rn_extrude(p, b, "rn_feature_b"))
    add("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy", "offset": 2,
        "units": "mm", "name": _RN["plane"]},
        lambda p: p.get("created") is True and p.get("component") == b and p.get("name") == _RN["plane"])
    add("model_construction", {"kind": "axis", "mode": "two_planes", "plane": "xy", "plane2": "xz",
        "name": _RN["axis"]},
        lambda p: p.get("created") is True and p.get("component") == b and p.get("name") == _RN["axis"])
    add("sketch_create", {"plane": "xy", "name": b + "PointSketch"})
    add("sketch_add_geometry", {"sketch_name": b + "PointSketch", "units": "mm",
        "geometry": [{"kind": "point", "cx": 10, "cy": 10}]})
    add("model_construction", {"kind": "point", "mode": "at_point", "name": _RN["point"],
        "points": [b + "PointSketch/point:1"]},
        lambda p: p.get("created") is True and p.get("component") == b and p.get("name") == _RN["point"])
    add("joint_create_origin", {"anchor": "coordinates", "target": "origin", "component": b + ":1",
        "name": _RN["origin"], "units": "mm"},
        lambda p: p.get("created") is True and p.get("component") == b
        and p.get("joint_origin_name") == _RN["origin"])
    add("design_activate_component", {"occurrence": "root"})
    add("joint_create", {"occurrence_one": a + ":1:" + _RN["origin"],
        "occurrence_two": b + ":1:" + _RN["origin"], "joint_type": "rigid", "name": _RN["joint"]},
        _jointed(_RN["joint"]))
    add("design_get", {"include": ["tree", "timeline", "datums"], "tree_bodies": True,
        "tree_handles": True, "max_results": 2000}, _rn_design("baseline"))
    for owner in (a, b):
        for kind, name in (("construction_plane", _RN["plane"]), ("construction_axis", _RN["axis"]),
                           ("construction_point", _RN["point"])):
            add("find_geometry", {"target": owner + ":1", "kind": kind, "name": name,
                "units": "mm", "max_results": 1}, _rn_geometry(owner, kind, name, "baseline"))
    add("assembly_get", {"include": ["poses", "joint_origins"], "units": "mm",
        "max_joint_origins": 100, "max_joints": 100}, _rn_assembly("baseline"))
    for owner, key in ((a, "rn_feature_a"), (b, "rn_feature_b")):
        add("model_inspect", lambda c, owner=owner, key=key: {"target": owner + ":1:" +
            ((_RECALL.get(key) or {}).get("feature" if owner == a else "body", "")), "include": ["default", "mass"],
            "units": "mm", "accuracy": "very_high"}, lambda p, owner=owner:
            p.get("mass") is not None and _rn_body(p, owner, "baseline"))

    def rename(kind, target, new_name, address):
        requested_name = lambda: new_name() if callable(new_name) else new_name
        add("design_set_name", lambda c, kind=kind, target=target, new_name=new_name:
            {"kind": kind, "target": target(), "new_name": requested_name()},
            lambda p, kind=kind, new_name=new_name, address=address: p.get("renamed") is True
            and p.get("changed") is True and p.get("kind") == kind and p.get("name") == requested_name()
            and p.get("addressed") == address())
    feature = lambda: (_RECALL.get("rn_feature_a") or {}).get("feature", "")
    index = lambda: str((_RECALL.get("rn_indexes") or {}).get("feature", ""))
    rename("feature", lambda: a + "/" + feature(), _RN_NEW["feature"], lambda: "feature '" + index() + "'")
    rename("joint", lambda: "root:" + _RN["joint"], _RN_NEW["joint"], lambda: "joint 'root:" + _RN_NEW["joint"] + "'")
    rename("joint_origin", lambda: a + "/" + _RN["origin"], _RN_NEW["joint_origin"],
           lambda: "joint_origin '" + a + "/" + _RN_NEW["joint_origin"] + "'")
    rename("plane", lambda: a + "/" + _RN["plane"], _RN_NEW["plane"], lambda: "plane '" + a + "/" + _RN_NEW["plane"] + "'")
    rename("axis", lambda: a + "/" + _RN["axis"], _RN_NEW["axis"], lambda: "axis '" + a + "/" + _RN_NEW["axis"] + "'")
    rename("point", lambda: a + "/" + _RN["point"], _RN_NEW["point"], lambda: "point '" + a + "/" + _RN_NEW["point"] + "'")
    add("design_get", {"include": ["tree", "timeline", "datums"], "tree_bodies": True,
        "tree_handles": True, "max_results": 2000}, _rn_design("renamed"))
    add("assembly_get", {"include": ["poses", "joint_origins"], "units": "mm",
        "max_joint_origins": 100, "max_joints": 100}, _rn_assembly("renamed"))
    for owner in (a, b):
        for kind, old, moved in (("construction_plane", _RN["plane"], _RN_NEW["plane"]),
                                 ("construction_axis", _RN["axis"], _RN_NEW["axis"]),
                                 ("construction_point", _RN["point"], _RN_NEW["point"])):
            name = moved if owner == a else old
            add("find_geometry", {"target": owner + ":1", "kind": kind, "name": name,
                "units": "mm", "max_results": 1}, _rn_geometry(owner, kind, name, "renamed"))
    for owner, key in ((a, "rn_feature_a"), (b, "rn_feature_b")):
        add("model_inspect", lambda c, owner=owner, key=key: {"target": owner + ":1:" +
            ((_RECALL.get(key) or {}).get("feature" if owner == a else "body", "")), "include": ["default", "mass"],
            "units": "mm", "accuracy": "very_high"}, lambda p, owner=owner:
            p.get("mass") is not None and _rn_body(p, owner, "renamed"))

    rename("feature", index, feature, lambda: "feature '" + index() + "'")
    rename("joint", lambda: "root:" + _RN_NEW["joint"], _RN["joint"], lambda: "joint 'root:" + _RN["joint"] + "'")
    rename("joint_origin", lambda: a + "/" + _RN_NEW["joint_origin"], _RN["origin"],
           lambda: "joint_origin '" + a + "/" + _RN["origin"] + "'")
    rename("plane", lambda: a + "/" + _RN_NEW["plane"], _RN["plane"], lambda: "plane '" + a + "/" + _RN["plane"] + "'")
    rename("axis", lambda: a + "/" + _RN_NEW["axis"], _RN["axis"], lambda: "axis '" + a + "/" + _RN["axis"] + "'")
    rename("point", lambda: a + "/" + _RN_NEW["point"], _RN["point"], lambda: "point '" + a + "/" + _RN["point"] + "'")
    add("design_get", {"include": ["tree", "timeline", "datums"], "tree_bodies": True,
        "tree_handles": True, "max_results": 2000}, _rn_design("restored"))
    add("assembly_get", {"include": ["poses", "joint_origins"], "units": "mm",
        "max_joint_origins": 100, "max_joints": 100}, _rn_assembly("restored"))
    for owner in (a, b):
        for kind, name in (("construction_plane", _RN["plane"]), ("construction_axis", _RN["axis"]),
                           ("construction_point", _RN["point"])):
            add("find_geometry", {"target": owner + ":1", "kind": kind, "name": name,
                "units": "mm", "max_results": 1}, _rn_geometry(owner, kind, name, "restored"))
    for owner, key in ((a, "rn_feature_a"), (b, "rn_feature_b")):
        add("model_inspect", lambda c, owner=owner, key=key: {"target": owner + ":1:" +
            ((_RECALL.get(key) or {}).get("feature" if owner == a else "body", "")), "include": ["default", "mass"],
            "units": "mm", "accuracy": "very_high"}, lambda p, owner=owner:
            p.get("mass") is not None and _rn_body(p, owner, "restored"))
    add("design_set_name", lambda c: {"target": _ctx_get(c, "rn_body_face", "first body face"),
        "new_name": (_RECALL.get("rn_feature_a") or {}).get("body"), "kind": "target"},
        lambda p: p.get("changed") is True and p.get("kind") == "body"
        and p.get("name") == (_RECALL.get("rn_feature_a") or {}).get("body"))
    add("model_inspect", lambda c: {"target": a + ":1:" +
        (_RECALL.get("rn_feature_a") or {}).get("body", ""), "include": ["default", "mass"],
        "units": "mm", "accuracy": "very_high"}, lambda p: _rn_body(p, a, "restored"))
    add("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
        "tree_handles": True, "max_results": 2000}, _rn_final_design)
    return rows


_DETAILS += _namespace_rename_witness_rows()
_DETAILS += feature_edit_rows()
_DETAILS += feature_finishing_rows()
_DETAILS += advanced_feature_edit_rows()
_DETAILS += surface_boundary_edit_rows()
_DETAILS += surface_feature_edit_rows()
_DETAILS += _DATUM_EDITS

from verify_acts_plastic import rib_web_retarget_rows, rib_web_rows

_DETAILS += rib_web_rows() + rib_web_retarget_rows()


def _chamfer_body_state(p):
    """One body's independently read box, mass and area, or None when incomplete."""
    from verify_acts_sketch import _body_facts
    state = _body_facts(p)
    mass = p.get("mass") or {}
    if (state is None or p.get("kind") != "body" or p.get("lump_count") != 1
            or mass.get("accuracy_used") != "very_high" or not _num(mass.get("area"))):
        return None
    return {**state, "area": mass["area"]}


def _chamfer_body_read(volume, area, before=None):
    """Require measured mass and area, and material removal from a separately banked read."""
    def check(p):
        state, baseline = _chamfer_body_state(p), _RECALL.get(before)
        return _measured("independent chamfer body geometry", {"now": state, "before": baseline},
                         state is not None and _near(state["volume"], volume, .01)
                         and _near(state["area"], area, .01)
                         and (before is None or (baseline is not None
                              and 0 < state["volume"] < baseline["volume"]
                              and state["min"] == baseline["min"]
                              and state["max"] == baseline["max"])))
    return check


def _chamfer_face_census(faces, edges):
    """Require a complete public face-and-edge listing with the measured topology."""
    def check(p):
        rows = p.get("matches") or []
        actual = sum(str(r.get("kind", "")).endswith("_face") for r in rows)
        return _measured("independent chamfer face census", {
            "faces": actual, "match_count": p.get("match_count"), "returned": p.get("returned")},
            p.get("units") == "mm" and p.get("kind_filter") == "faces+edges"
            and p.get("match_count") == p.get("returned") == len(rows) == faces + edges
            and actual == faces and all(r.get("handle") for r in rows))
    return check


def _chamfer_geometry_rows():
    """Three-edge corners, an unchained rim and an angle chain, with independent body reads."""
    from verify_acts_sketch import _boxed, _keep, _scratch_rows, _solid, _unchanged
    rows, write, read, close = _scratch_rows("chamfer_geometry_doc")

    def census(key, faces, edges):
        read("find_geometry", lambda c: {"target": _ctx_get(c, key, "chamfer body"),
                                         "max_results": 100, "units": "mm"},
             _chamfer_face_census(faces, edges))

    def pick(key, suffix, point):
        def at_seed(p):
            matches = p.get("matches") or []
            row = matches[0] if len(matches) == 1 else {}
            pos = row.get("position")
            return _measured("chamfer seed at the measured midpoint", row,
                             p.get("units") == "mm" and row.get("kind") == "line_edge"
                             and bool(row.get("handle")) and isinstance(pos, list) and len(pos) == 3
                             and all(_near(a, b, .001) for a, b in zip(pos, point)))
        read("find_geometry", lambda c: {"target": _ctx_get(c, key, "chamfer body"),
                                         "kind": "line_edge", "nearest_to": point,
                                         "max_results": 1, "units": "mm"},
             at_seed, _fg(key + suffix))

    # The corner controls share dimensions and seeds; only the requested corner treatment differs.
    for key, x, corner, volume, area, faces in (
            ("cg_ordinary", 0, "chamfer", 23955.666667, 5145.4026053, 10),
            ("cg_miter", 60, "miter", 23955.75, 5145.5972401, 9)):
        _boxed(write, key + "S", [x, 0, x + 40, 30], 20, key)
        _keep(read, "model_inspect", _solid(key), key + "_before", _chamfer_body_state)
        census(key, 6, 12)
        for suffix, point in (("_x", [x + 20, 0, 20]), ("_y", [x, 15, 20]),
                              ("_z", [x, 0, 10])):
            pick(key, suffix, point)
        write("model_chamfer", lambda c, key=key, corner=corner: {
            "edges": [_ctx_get(c, key + suffix, "corner seed") for suffix in ("_x", "_y", "_z")],
            "distance": 1, "tangent_chain": False, "corner_type": corner}, _cut_exactly("chamfer", 3))
        read("model_inspect", _solid(key), _chamfer_body_read(volume, area, key + "_before"))
        census(key, faces, 21)
        if key == "cg_ordinary":
            _keep(read, "model_inspect", _solid(key), "cg_control", _chamfer_body_state)
    read("model_inspect", _solid("cg_ordinary"),
         _unchanged("cg_control", _chamfer_body_state, 1e-6))
    census("cg_ordinary", 10, 21)

    for key, x, angle, volume, area, faces, edges in (
            ("cg_unchained", 120, None, 23912.32005, 5101.6500435, 11, 27),
            ("cg_angle", 180, 30, 23778.470949, 5007.0766497, 18, 36)):
        _boxed(write, key + "S", [x, 0, x + 40, 30], 20, key)
        for i, point in enumerate(([x, 0, 10], [x + 40, 0, 10],
                                   [x + 40, 30, 10], [x, 30, 10])):
            pick(key, "_v" + str(i), point)
        write("model_fillet", lambda c, key=key: {
            "edges": [_ctx_get(c, key + "_v" + str(i), "upright seed") for i in range(4)],
            "radius": 2, "tangent_chain": False}, _cut_exactly("fillet", 4))
        _keep(read, "model_inspect", _solid(key), key + "_before", _chamfer_body_state)
        pick(key, "_rim", [x + 20, 0, 20])
        write("model_chamfer", lambda c, key=key, angle=angle: {
            "edges": [_ctx_get(c, key + "_rim", "front top rim seed")],
            "distance": 1 if angle is None else 2, "tangent_chain": angle is not None,
            **({"angle_deg": angle} if angle is not None else {})},
            _cut_exactly("chamfer", 1) if angle is None else _cut_a_chain("chamfer", 1))
        read("model_inspect", _solid(key), _chamfer_body_read(volume, area, key + "_before"))
        census(key, faces, edges)
    read("model_inspect", _solid("cg_ordinary"),
         _unchanged("cg_control", _chamfer_body_state, 1e-6))
    census("cg_ordinary", 10, 21)
    close()
    return rows


_DETAILS += _chamfer_geometry_rows()
