# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Public definition and geometry witnesses for selected surface-feature edits."""

import math

from verify_core import (
    _RECALL, _ctx_get, _document_closed, _home_address, _home_document, _measured,
    _new_document, _num, _near, _recall,
)
from verify_acts_model_combine_revolve import _combine_pin


_SURFACE_EDIT_SETUP = r'''import adsk.core, adsk.fusion, json
def P(x, y, z=0): return adsk.core.Point3D.create(x, y, z)
def V(x): return adsk.core.ValueInput.createByReal(x)
def C(*items):
    out = adsk.core.ObjectCollection.create()
    for item in items: out.add(item)
    return out
def at_face(body, xyz):
    return min((body.faces.item(i) for i in range(body.faces.count)),
               key=lambda f: sum((getattr(f.centroid, k)-v)**2 for k, v in zip('xyz', xyz)))
def sheet(root, F, name, pts, height):
    sk = root.sketches.add(root.xYConstructionPlane); sk.name = name + '_Sk'
    lines, curves = sk.sketchCurves.sketchLines, adsk.core.ObjectCollection.create()
    prev = P(*pts[0])
    for point in pts[1:]:
        line = lines.addByTwoPoints(prev, P(*point)); curves.add(line); prev = line.endSketchPoint
    profile = root.createOpenProfile(curves, False)
    ex_input = F.extrudeFeatures.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ex_input.isSolid = False
    ex_input.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(V(height)),
                              adsk.fusion.ExtentDirections.PositiveExtentDirection)
    ex = F.extrudeFeatures.add(ex_input); ex.name = name + '_Ext'
    ex.bodies.item(0).name = name + 'Body'
    return ex.bodies.item(0)
def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    root, F = design.rootComponent, design.rootComponent.features
    if design.timeline.count or root.bRepBodies.count:
        raise RuntimeError('surface edit witness requires its owned empty scratch')
    # The independent solid control is 10 mm on each side.
    sk = root.sketches.add(root.xYConstructionPlane); sk.name = 'SFE_Control_Sk'
    sk.sketchCurves.sketchLines.addTwoPointRectangle(P(30, 0), P(31, 1))
    ex = F.extrudeFeatures.addSimple(sk.profiles.item(0), V(1), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ex.name = 'SFE_Control_Ext'; ex.bodies.item(0).name = 'SFE_Control'
    # The alternate patch boundary has a larger radius.
    sk = root.sketches.add(root.xYConstructionPlane); sk.name = 'SFE_Patch_Sk'
    c0 = sk.sketchCurves.sketchCircles.addByCenterRadius(P(1, 20), 1)
    c1 = sk.sketchCurves.sketchCircles.addByCenterRadius(P(4, 20), 1.5)
    f = F.patchFeatures.add(F.patchFeatures.createInput(c0, adsk.fusion.FeatureOperations.NewBodyFeatureOperation))
    f.name = 'SFE_Patch'; f.bodies.item(0).name = 'SFE_PatchBody'
    # The folded sheet provides two selectable offset faces.
    src_body = sheet(root, F, 'SFE_OffsetSource', [(0, 30), (2, 30), (2, 32)], 1)
    offset_before = {root.bRepBodies.item(i).entityToken for i in range(root.bRepBodies.count)}
    oi = F.offsetFeatures.createInput(C(at_face(src_body, (1, 30, .5))), V(.3), adsk.fusion.FeatureOperations.NewBodyFeatureOperation, False)
    f = F.offsetFeatures.add(oi); f.name = 'SFE_Offset'
    offset_created = [root.bRepBodies.item(i) for i in range(root.bRepBodies.count)
                      if root.bRepBodies.item(i).entityToken not in offset_before]
    if len(offset_created) != 1:
        raise RuntimeError("offset did not create exactly one new root body")
    offset_created[0].name = 'SFE_OffsetBody'
    # The rectangular patch provides distinct opposite extension edges.
    sk = root.sketches.add(root.xYConstructionPlane); sk.name = 'SFE_Extend_Sk'
    sk.sketchCurves.sketchLines.addTwoPointRectangle(P(0, 60), P(2, 62))
    f = F.patchFeatures.add(F.patchFeatures.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation))
    f.name = 'SFE_ExtendSource'; f.bodies.item(0).name = 'SFE_ExtendBody'
    body = f.bodies.item(0)
    edge_a = min((body.edges.item(i) for i in range(body.edges.count)),
                 key=lambda e: sum((getattr(e.boundingBox.minPoint, k)-v)**2
                                   for k, v in zip('xyz', (2, 61, 0))))
    edge_b = min((body.edges.item(i) for i in range(body.edges.count)),
                 key=lambda e: sum((getattr(e.boundingBox.minPoint, k)-v)**2
                                   for k, v in zip('xyz', (0, 61, 0))))
    ei = F.extendFeatures.createInput(C(edge_a), V(.8), adsk.fusion.SurfaceExtendTypes.NaturalSurfaceExtendType, False)
    f = F.extendFeatures.add(ei); f.name = 'SFE_Extend'
    # The second folded sheet provides two selectable thickening faces.
    thicken_source = sheet(root, F, 'SFE_ThickenSource', [(0, 90), (2, 90), (2, 92)], 1)
    ti = F.thickenFeatures.createInput(C(at_face(thicken_source, (1, 90, .5))), V(.2), False, adsk.fusion.FeatureOperations.NewBodyFeatureOperation, False)
    f = F.thickenFeatures.add(ti); f.name = 'SFE_Thicken'; f.bodies.item(0).name = 'SFE_ThickenBody'
    # The reverse feature initially selects the first of two independent surfaces.
    def patch(name, x):
        s = root.sketches.add(root.xYConstructionPlane); s.name = name + '_Sk'
        s.sketchCurves.sketchLines.addTwoPointRectangle(P(x, 120), P(x+1, 121))
        p = F.patchFeatures.add(F.patchFeatures.createInput(s.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation))
        p.name = name + '_Patch'; p.bodies.item(0).name = name
        return p.bodies.item(0)
    ra, rb = patch('SFE_ReverseA', 0), patch('SFE_ReverseB', 2)
    f = F.reverseNormalFeatures.add(C(ra)); f.name = 'SFE_Reverse'
    print(json.dumps({'timeline_count': design.timeline.count, 'marker': design.timeline.markerPosition,
                      'names': ['SFE_Patch','SFE_Offset','SFE_Extend','SFE_Thicken','SFE_Reverse'],
                      'control': 'SFE_Control'}))
'''


def _surface_marker(stage, feature):
    def check(p):
        if stage == "before":
            valid = (p.get("rolled") is True and p.get("to") == "before"
                     and p.get("feature") == feature
                     and _num(p.get("marker_position")) and _num(p.get("timeline_count"))
                     and p["marker_position"] < p["timeline_count"])
        else:
            valid = (p.get("rolled") is True and p.get("to") == "end"
                     and p.get("marker_position") == p.get("timeline_count")
                     and p.get("rolled_back") == 0)
        return _measured("surface definition marker " + stage, p, valid)
    return check


def _semantic(value):
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in value.items() if key != "handle"}
    if isinstance(value, (list, tuple)):
        return [_semantic(item) for item in value]
    return value


def _definition(feature, key, stage, expected_count=None, operand_keys=()):
    def check(p):
        definition = p.get("definition") or {}
        expected_type = definition.get("type")
        field = definition.get(key)
        timeline = p.get("timeline") or {}
        state = {k: v for k, v in definition.items() if k not in ("note", "supported_edits")}
        index = definition.get("timeline_index")
        rows = timeline.get("timeline") or []
        found = [r for r in rows if r.get("name") == feature and r.get("type") == expected_type]
        marker_ok = (isinstance(index, int) and timeline.get("marker_position") == index
                     and timeline.get("count") == timeline.get("returned") == len(rows)
                     and timeline.get("truncated") is not True
                     and [r.get("index") for r in rows] == list(range(len(rows)))
                     and len(found) == 1 and found[0].get("index") == index
                     and definition.get("unavailable") == {})
        saved_key = "surface_edit_" + feature + "_" + key
        if stage == "before":
            _RECALL[saved_key] = state
            passed = (bool(expected_type) and isinstance(definition.get("feature_address"), str)
                      and bool(definition["feature_address"]) and field is not None and marker_ok)
        elif stage == "after":
            before = _RECALL.get(saved_key)
            before_field = (before or {}).get(key)
            field_size_ok = (expected_count is None or
                             isinstance(field, dict) and expected_count == 1 and bool(field)
                             or isinstance(field, (list, tuple)) and len(field) == expected_count)
            passed = (before is not None and field is not None
                      and _semantic(field) != _semantic(before_field)
                      and field_size_ok and marker_ok
                      and definition.get("feature_address") == before.get("feature_address")
                      and definition.get("type") == before.get("type")
                      and all(_semantic(definition.get(k)) == _semantic(v)
                              for k, v in before.items() if k != key))
            if feature == "SFE_Patch" and stage == "after":
                wanted = _RECALL.get("surface_edit_patch_alternate_center_cm")
                geometry = field.get("geometry") if isinstance(field, dict) else None
                world = (geometry or {}).get("world_cm")
                passed = passed and wanted is not None and isinstance(world, list) and len(world) == 3 \
                    and all(_near(a, b, .001) for a, b in zip(world, wanted))
            if operand_keys and stage == "after":
                before_descriptors = (before_field if isinstance(before_field, list)
                                      else [before_field])
                original_kept = (isinstance(field, list) and any(
                    _semantic(item) == _semantic(old)
                    for item in field for old in before_descriptors))
                acquired = [_RECALL.get("surface_edit_operand_" + operand_key)
                            for operand_key in operand_keys]
                passed = (passed and len(field) == len(operand_keys) == expected_count
                          and original_kept and all(item is not None for item in acquired)
                          and _matches_acquired_faces(field, acquired))
        else:
            before = _RECALL.get(saved_key)
            passed = (before is not None and _semantic(state) == _semantic(before) and marker_ok
                      and definition.get("feature_address") == before.get("feature_address")
                      and definition.get("type") == before.get("type"))
        return _measured(f"independent {feature} {stage} definition", state, passed)
    return check


def _located_geometry_row(p, kind, expected_position):
    rows = p.get("matches")
    total, returned = p.get("match_count"), p.get("returned")
    if (p.get("units") != "mm" or p.get("target") != "whole design"
            or not isinstance(rows, list) or not isinstance(total, int)
            or isinstance(total, bool) or returned != len(rows) or total != returned
            or p.get("incomplete") is True):
        return None
    hits = []
    for row in rows:
        position = row.get("position") if isinstance(row, dict) else None
        if (isinstance(position, list) and len(position) == 3
                and row.get("kind") == kind
                and all(_finite(value) for value in position)
                and all(_near(value, expected, .05)
                        for value, expected in zip(position, expected_position))):
            hits.append(row)
    if len(hits) != 1 or not isinstance(hits[0].get("handle"), str) or not hits[0]["handle"]:
        return None
    return hits[0]


def _face_handle(key, expected_position):
    def check(p):
        row = _located_geometry_row(p, "planar_face", expected_position) or {}
        position = row.get("position") or []
        passed = (row.get("kind") == "planar_face" and bool(row.get("handle"))
                  and _finite(row.get("area")) and row["area"] >= 0
                  and isinstance(row.get("normal"), list) and len(row["normal"]) == 3
                  and all(_finite(value) for value in row["normal"])
                  and row.get("occurrence") is None
                  and len(position) == 3 and all(_near(a, b, .05)
                                                 for a, b in zip(position, expected_position)))
        root_component = _RECALL.get("surface_edit_root_component")
        passed = passed and isinstance(root_component, str) and bool(root_component)
        if passed:
            _RECALL["surface_edit_operand_" + key] = {
                "area": row["area"] / 100.0,
                "normal": row["normal"],
                "owner": {"component": root_component, "occurrence": row.get("occurrence")},
            }
        return _measured("one exact source face handle", row, passed)
    return check


def _edge_handle(key, expected_position):
    def check(p):
        row = _located_geometry_row(p, "line_edge", expected_position) or {}
        length = row.get("length")
        passed = (_finite(length) and length > 0
                  and isinstance(row.get("direction"), list) and len(row["direction"]) == 3
                  and all(_finite(value) for value in row["direction"]))
        return _measured("one exact source edge handle", row, passed)
    return check


def _geometry_save(key, kind, expected_position):
    def save(p):
        row = _located_geometry_row(p, kind, expected_position)
        if row is None:
            raise ValueError("whole-design search did not identify one complete geometry row")
        return row["handle"]
    return key, save


def _matches_acquired_faces(descriptors, acquired):
    if not isinstance(descriptors, list) or len(descriptors) != len(acquired):
        return False
    unmatched = list(acquired)
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            return False
        geometry = descriptor.get("geometry") or {}
        owner = descriptor.get("owner")
        area, normal = geometry.get("area"), geometry.get("normal")
        if not (_finite(area) and isinstance(normal, list) and len(normal) == 3
                and all(_finite(value) for value in normal) and isinstance(owner, dict)):
            return False
        matches = [expected for expected in unmatched
                   if owner == expected["owner"]
                   and _near(area, expected["area"], .0001)
                   and all(_near(value, wanted, .001)
                           for value, wanted in zip(normal, expected["normal"]))]
        if len(matches) != 1:
            return False
        unmatched.remove(matches[0])
    return not unmatched


def _root_component(p):
    tree = p.get("tree") or {}
    root = tree.get("root")
    bodies = tree.get("root_bodies")
    return _measured("root component owner", {"root": root},
                     isinstance(root, str) and bool(root)
                     and tree.get("truncated") is False
                     and tree.get("child_count") == 0
                     and tree.get("children_truncated") is False
                     and isinstance(bodies, list)
                     and tree.get("root_bodies_truncated") is not True)


def _sketch_circle_handle(key, sketch, circle_id, center, radius):
    def check(p):
        rows = p.get("matches") or []
        row = rows[0] if rows else {}
        got = row.get("center") or []
        position = row.get("position") or []
        passed = (p.get("units") == "mm" and p.get("match_count") == p.get("returned") == len(rows) == 1
                  and row.get("kind") == "sketch_circle" and row.get("sketch") == sketch
                  and row.get("id") == circle_id
                  and row.get("radius") is not None and _near(row["radius"], radius, .01)
                  and bool(row.get("handle")) and len(got) == 3
                  and len(position) == 3
                  and all(_near(a, b, .05) for a, b in zip(got, center))
                  and all(_near(a, b, .05) for a, b in zip(position, center)))
        if passed:
            _RECALL[key + "_center_cm"] = [value / 10 for value in got]
        return _measured("one exact sketch circle handle", row, passed)
    return check


def _handle_save(key):
    return key, lambda p: p["matches"][0]["handle"]


def _tree_bodies(p):
    tree = p.get("tree") or {}
    return tree.get("root_bodies") or []


def _tree_body_row(p, name):
    tree = p.get("tree") or {}
    rows = [r for r in _tree_bodies(p) if r.get("name") == name]
    complete = (tree.get("truncated") is False
                and tree.get("root_bodies_truncated") is not True)
    if (not complete or len(rows) != 1 or not isinstance(rows[0].get("handle"), str)
            or not rows[0]["handle"]):
        return None
    return rows[0]


def _body_save(key, name):
    return key, lambda p: _tree_body_row(p, name)["handle"]


def _body_handle(name, slot):
    def check(p):
        row = _tree_body_row(p, name)
        return _measured(f"one tree body handle for {name}", row,
                         row is not None)
    return check


def _xyz(value):
    if isinstance(value, list) and len(value) == 3 and all(_finite(v) for v in value):
        return tuple(value)
    if isinstance(value, dict) and all(_finite(value.get(k)) for k in ("x", "y", "z")):
        return tuple(value[k] for k in ("x", "y", "z"))
    return None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _mass_state(slot, stage, expected_change=False, expected=None):
    def check(p):
        mass = p.get("mass") or {}
        shape = {"area": mass.get("area"), "volume": mass.get("volume"),
                 "body_count": mass.get("body_count"),
                 "per_body_count": mass.get("per_body_count"),
                 "center_of_mass": _xyz(mass.get("center_of_mass")),
                 "center": _xyz(p.get("center")),
                 "min_point": _xyz(p.get("min_point")), "max_point": _xyz(p.get("max_point"))}
        saved = "surface_edit_mass_" + slot
        usable = (_finite(shape["area"]) and shape["area"] >= 0 and _finite(shape["volume"])
                  and shape["center_of_mass"] is not None and shape["min_point"] is not None
                  and shape["max_point"] is not None and shape["center"] is not None
                  and mass.get("per_body_truncated") is False)
        if stage == "before" and usable:
            _RECALL[saved] = shape
            passed = True
        elif stage == "changed" and expected is not None:
            baseline = _RECALL.get(saved)
            passed = baseline is not None and shape != baseline and usable
            if "area" in expected:
                passed = passed and _near(shape["area"], expected["area"],
                                          expected.get("area_tolerance", .05))
            if "volume" in expected:
                passed = passed and _near(shape["volume"], expected["volume"],
                                          expected.get("volume_tolerance", .05))
            if "center" in expected:
                passed = passed and all(_near(a, b, expected.get("center_tolerance", .1))
                                        for a, b in zip(shape["center"], expected["center"]))
            for field in ("min_point", "max_point"):
                if field in expected:
                    passed = passed and all(_near(a, b, .1)
                                            for a, b in zip(shape[field], expected[field]))
        else:
            baseline = _RECALL.get(saved)
            passed = baseline is not None and usable
            if passed:
                changed = shape != baseline
                passed = changed is expected_change
        return _measured(f"independent {slot} body area and mass", shape, passed)
    return check


def _normal_relation(slot, stage):
    def check(p):
        rows = p.get("matches") or []
        row = rows[0] if rows else {}
        now = row.get("normal")
        key = "surface_edit_normal_" + slot
        before = _RECALL.get(key)
        readable = (p.get("match_count") == p.get("returned") == 1
                    and row.get("kind") == "planar_face" and isinstance(now, list)
                    and len(now) == 3 and all(_num(v) for v in now))
        if stage == "before" and readable:
            _RECALL[key] = now
            passed = True
        elif stage == "reversed":
            passed = (readable and isinstance(before, list) and len(before) == 3
                      and all(_near(a, -b, .001) for a, b in zip(now, before)))
        else:
            passed = (readable and isinstance(before, list) and len(before) == 3
                      and all(_near(a, b, .001) for a, b in zip(now, before)))
        return _measured(f"independent {slot} surface normal {stage}", row, passed)
    return check


def surface_feature_edit_rows():
    """Exercise five admitted surface edits with independent definition and geometry reads."""
    rows = [("doc_get", {}, _home_document, ("surface_edit_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "surface_edit_home", "home")},
             _new_document, ("surface_edit_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, a=args: _combine_pin(
            c, "surface_edit_doc", a(c) if callable(a) else a), check, save))

    def read(tool, args, check, save=None):
        rows.append((tool, args, check, save))

    def definition_read(feature, field, stage, expected_count=None, operand_keys=()):
        write("design_edit_timeline", {"action": "roll", "feature": feature, "to": "before"},
              _surface_marker("before", feature))
        read("design_get", {"include": ["definition", "timeline"], "feature": feature,
             "units": "mm", "max_results": 200},
             _definition(feature, field, stage, expected_count, operand_keys))
        write("design_edit_timeline", {"action": "roll", "to": "end"},
              _surface_marker("end", feature))

    def acquire_inputs(feature):
        write("design_edit_timeline", {"action": "roll", "feature": feature, "to": "before"},
              _surface_marker("before", feature))
        if feature == "SFE_Patch":
            for key, circle_id, center, radius in (
                    ("surface_edit_patch_original", "circle:0", [10, 200, 0], 10),
                    ("surface_edit_patch_alternate", "circle:1", [40, 200, 0], 15)):
                read("find_geometry", {"target": "", "kind": "sketch_circle",
                     "sketch": "SFE_Patch_Sk", "radius": radius,
                     "nearest_to": center, "max_results": 1, "units": "mm"},
                     _sketch_circle_handle(key, "SFE_Patch_Sk", circle_id, center, radius),
                     _handle_save(key))
        elif feature == "SFE_Offset":
            for key, point in (("surface_edit_offset_face_a", [10, 300, 5]),
                               ("surface_edit_offset_face_b", [20, 310, 5])):
                read("find_geometry", {"target": "", "kind": "planar_face",
                     "nearest_to": point, "max_results": 100, "units": "mm"},
                     _face_handle(key, point),
                     _geometry_save(key, "planar_face", point))
        elif feature == "SFE_Thicken":
            for key, point in (("surface_edit_thicken_face_a", [10, 900, 5]),
                               ("surface_edit_thicken_face_b", [20, 910, 5])):
                read("find_geometry", {"target": "", "kind": "planar_face",
                     "nearest_to": point, "max_results": 100, "units": "mm"},
                     _face_handle(key, point),
                     _geometry_save(key, "planar_face", point))
        elif feature == "SFE_Extend":
            for key, point in (("surface_edit_extend_edge_a", [20, 610, 0]),
                               ("surface_edit_extend_edge_b", [0, 610, 0])):
                read("find_geometry", {"target": "", "kind": "line_edge",
                     "nearest_to": point, "max_results": 100, "units": "mm"},
                     _edge_handle(key, point),
                     _geometry_save(key, "line_edge", point))
        write("design_edit_timeline", {"action": "roll", "to": "end"},
              _surface_marker("end", feature))

    write("sys_execute_script", {"script": _SURFACE_EDIT_SETUP, "read_only": False},
          lambda p: _measured("owned surface fixture setup", p,
              p.get("timeline_count") == p.get("marker") and p.get("names") ==
              ["SFE_Patch", "SFE_Offset", "SFE_Extend", "SFE_Thicken", "SFE_Reverse"]
              and p.get("control") == "SFE_Control"),
          ("surface_edit_timeline_count", _recall("surface_edit_timeline_count",
                                                 lambda p: p["timeline_count"])))

    read("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                         "max_depth": 1, "max_results": 100},
         _root_component,
         ("surface_edit_root_component", _recall("surface_edit_root_component", lambda p: p["tree"]["root"])))

    # Inputs are acquired independently after the fixture, before each edit.
    fields = {"SFE_Patch": "boundary", "SFE_Offset": "entities",
              "SFE_Extend": "edges", "SFE_Thicken": "input_faces",
              "SFE_Reverse": "surfaces"}
    for feature, field in fields.items():
        definition_read(feature, field, "before", 1)

    for feature in ("SFE_Patch", "SFE_Offset", "SFE_Thicken", "SFE_Extend"):
        acquire_inputs(feature)
    read("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                         "max_depth": 3, "max_results": 100},
          _body_handle("SFE_ReverseA", "surface_edit_reverse_a"),
          _body_save("surface_edit_reverse_a", "SFE_ReverseA"))
    read("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                         "max_depth": 3, "max_results": 100},
          _body_handle("SFE_ReverseB", "surface_edit_reverse_b"),
          _body_save("surface_edit_reverse_b", "SFE_ReverseB"))

    for name, slot, point in (("SFE_ReverseA", "reverse_a", [5, 1205, 0]),
                              ("SFE_ReverseB", "reverse_b", [25, 1205, 0])):
        read("find_geometry", {"target": name, "kind": "planar_face", "nearest_to": point,
                                "max_results": 1, "units": "mm"},
              _normal_relation(slot, "before"))

    # Record source/control measurements before changing any feature.
    for target, key in (("SFE_PatchBody", "SFE_Patch"), ("SFE_OffsetBody", "SFE_Offset"),
                        ("SFE_OffsetSourceBody", "offset_source"),
                        ("SFE_ThickenBody", "SFE_Thicken"), ("SFE_ExtendBody", "SFE_Extend"),
                        ("SFE_ReverseA", "reverse_a_mass"), ("SFE_ReverseB", "SFE_Reverse"),
                        ("SFE_Control", "control")):
        read("model_inspect", {"target": target, "include": ["default", "mass"], "units": "mm",
                                "per_body": True, "accuracy": "very_high"},
              _mass_state(key, "before"))

    cases = (
        ("SFE_Patch", "boundary", "boundary",
         [lambda c: _ctx_get(c, "surface_edit_patch_alternate", "alternate patch circle")],
         [lambda c: _ctx_get(c, "surface_edit_patch_original", "original patch circle")],
         "SFE_PatchBody", True),
        ("SFE_Offset", "inputs", "entities",
         [lambda c: _ctx_get(c, "surface_edit_offset_face_a", "original offset face"),
          lambda c: _ctx_get(c, "surface_edit_offset_face_b", "alternate offset face")],
         [lambda c: _ctx_get(c, "surface_edit_offset_face_a", "original offset face")],
         "SFE_OffsetBody", True),
        ("SFE_Extend", "inputs", "edges",
         [lambda c: _ctx_get(c, "surface_edit_extend_edge_b", "alternate extension edge")],
         [lambda c: _ctx_get(c, "surface_edit_extend_edge_a", "original extension edge")],
         "SFE_ExtendBody", True),
        ("SFE_Thicken", "inputs", "input_faces",
         [lambda c: _ctx_get(c, "surface_edit_thicken_face_a", "original thickening face"),
          lambda c: _ctx_get(c, "surface_edit_thicken_face_b", "alternate thickening face")],
         [lambda c: _ctx_get(c, "surface_edit_thicken_face_a", "original thickening face")],
         "SFE_ThickenBody", True),
        ("SFE_Reverse", "inputs", "surfaces",
         [lambda c: _ctx_get(c, "surface_edit_reverse_b", "alternate surface body")],
         [lambda c: _ctx_get(c, "surface_edit_reverse_a", "original surface body")],
         "SFE_ReverseB", False),
    )
    for feature, action, field, replacement, original, target, effect in cases:
        def ref_args(c, refs):
            return [item(c) if callable(item) else item for item in refs]
        write("model_edit_feature", lambda c, f=feature, a=action, refs=replacement: {
            "feature": f, "action": a, "references": ref_args(c, refs)},
            lambda p, f=feature: _measured(f + " public edit reply", p,
                p.get("edited") is True and p.get("definition_matches") is True
                and p.get("marker_restored") is True and p.get("same_feature") is True))
        edited_count = 2 if feature in ("SFE_Offset", "SFE_Thicken") else 1
        acquired_faces = {
            "SFE_Offset": ("surface_edit_offset_face_a", "surface_edit_offset_face_b"),
            "SFE_Thicken": ("surface_edit_thicken_face_a", "surface_edit_thicken_face_b"),
        }.get(feature, ())
        definition_read(feature, field, "after", edited_count, acquired_faces)
        expected_shapes = {
            "SFE_Patch": {"area": math.pi * 15 ** 2, "volume": 0,
                           "center": [40, 200, 0], "min_point": [25, 185, 0],
                           "max_point": [55, 215, 0]},
            "SFE_Offset": {"area": 460, "volume": 0, "center": [11.5, 308.5, 5],
                           "min_point": [0, 297, 0], "max_point": [23, 320, 10]},
            "SFE_Extend": {"area": 560, "volume": 0, "center": [6, 610, 0],
                           "min_point": [-8, 600, 0], "max_point": [20, 620, 0]},
            "SFE_Thicken": {"volume": 840},
        }
        read("model_inspect", {"target": target, "include": ["default", "mass"], "units": "mm",
                                "per_body": True, "accuracy": "very_high"},
              _mass_state(feature, "changed", effect,
                          expected_shapes.get(feature) if effect else None))
        if feature == "SFE_Offset":
            read("model_inspect", {"target": "SFE_OffsetSourceBody",
                                    "include": ["default", "mass"], "units": "mm",
                                    "per_body": True, "accuracy": "very_high"},
                 _mass_state("offset_source", "unchanged", False))
        read("model_inspect", {"target": "SFE_Control", "include": ["default", "mass"], "units": "mm",
                                "per_body": True, "accuracy": "very_high"},
              _mass_state("control", "unchanged", False))
        if feature == "SFE_Reverse":
            read("model_inspect", {"target": "SFE_ReverseA", "include": ["default", "mass"], "units": "mm",
                                    "per_body": True, "accuracy": "very_high"},
                  _mass_state("reverse_a_mass", "unchanged", False))
            for name, slot, point, normal_stage in (
                    ("SFE_ReverseA", "reverse_a", [5, 1205, 0], "reversed"),
                    ("SFE_ReverseB", "reverse_b", [25, 1205, 0], "reversed")):
                read("find_geometry", {"target": name, "kind": "planar_face", "nearest_to": point,
                                        "max_results": 1, "units": "mm"},
                      _normal_relation(slot, normal_stage))
        if feature in ("SFE_Patch", "SFE_Offset", "SFE_Thicken", "SFE_Extend"):
            acquire_inputs(feature)
        write("model_edit_feature", lambda c, f=feature, a=action, refs=original: {
            "feature": f, "action": a, "references": ref_args(c, refs)},
            lambda p, f=feature: _measured(f + " restores its original selection", p,
                p.get("edited") is True and p.get("definition_matches") is True
                and p.get("marker_restored") is True and p.get("same_feature") is True))
        definition_read(feature, field, "restored", 1)
        read("model_inspect", {"target": target, "include": ["default", "mass"], "units": "mm",
                                "per_body": True, "accuracy": "very_high"},
              _mass_state(feature, "restored", False))
        if feature == "SFE_Offset":
            read("model_inspect", {"target": "SFE_OffsetSourceBody",
                                    "include": ["default", "mass"], "units": "mm",
                                    "per_body": True, "accuracy": "very_high"},
                 _mass_state("offset_source", "still unchanged", False))
        read("model_inspect", {"target": "SFE_Control", "include": ["default", "mass"], "units": "mm",
                                "per_body": True, "accuracy": "very_high"},
              _mass_state("control", "still unchanged", False))
        if feature == "SFE_Reverse":
            read("model_inspect", {"target": "SFE_ReverseA", "include": ["default", "mass"], "units": "mm",
                                    "per_body": True, "accuracy": "very_high"},
                  _mass_state("reverse_a_mass", "still unchanged", False))
            for name, slot, point in (("SFE_ReverseA", "reverse_a", [5, 1205, 0]),
                                      ("SFE_ReverseB", "reverse_b", [25, 1205, 0])):
                read("find_geometry", {"target": name, "kind": "planar_face", "nearest_to": point,
                                        "max_results": 1, "units": "mm"},
                      _normal_relation(slot, "same"))

    def healthy_end(p):
        tl = p.get("timeline") or {}
        timeline_rows = tl.get("timeline") or []
        expected = _RECALL.get("surface_edit_timeline_count")
        return _measured("complete healthy surface edit history at end", tl,
            expected is not None and tl.get("count") == tl.get("returned") == expected
            and tl.get("marker_position") == expected and tl.get("truncated") is not True
            and (tl.get("summary") or {}).get("exceptions") == []
            and (tl.get("summary") or {}).get("states") == {"healthy": expected}
            and all(r.get("health", "healthy") == "healthy" and r.get("is_rolled_back") is not True
                    for r in timeline_rows))

    read("design_get", {"include": ["timeline"], "max_results": 200}, healthy_end)

    rows.extend([("doc_activate", lambda c: {"name": _ctx_get(c, "surface_edit_home", "home"),
                  "expect_document": _ctx_get(c, "surface_edit_doc", "scratch")}, "ok", None),
                 ("doc_close", lambda c: {"name": _ctx_get(c, "surface_edit_doc", "scratch"),
                  "save_changes": False, "expect_document": _ctx_get(c, "surface_edit_home", "home")},
                  _document_closed, None)])
    return rows
