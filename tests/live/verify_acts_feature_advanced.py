# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Live public witnesses for the measured advanced feature edit rows."""

import json
import math

from verify_core import scope_unit

from verify_core import (
    _ctx_get, _document_closed, _fg, _home_address, _home_document, _measured, _near, _new_document, _num, _refused)
from verify_acts_model_combine_revolve import _combine_inspect, _combine_pin


_ADVANCED_FEATURE_FIXTURE = r"""def run(context):
    import adsk.core, adsk.fusion, json
    app = adsk.core.Application.get()
    d = adsk.fusion.Design.cast(app.activeProduct)
    if (d is None or app.activeDocument.isSaved or d.timeline.count != 0
            or d.rootComponent.bRepBodies.count != 0):
        raise RuntimeError('feature fixture requires a fresh unsaved empty design')
    if d.designType != adsk.fusion.DesignTypes.ParametricDesignType:
        d.designType = adsk.fusion.DesignTypes.ParametricDesignType
    r = d.rootComponent
    F = r.features
    V = adsk.core.ValueInput.createByReal
    P = adsk.core.Point3D.create
    def S(sk, x, y, z=0): return sk.modelToSketchSpace(P(x, y, z))
    def C(*items):
        out = adsk.core.ObjectCollection.create()
        for item in items: out.add(item)
        return out
    def box(name, x, y, w, h, z):
        sk = r.sketches.add(r.xYConstructionPlane)
        sk.name = name + '_Sk'
        sk.sketchCurves.sketchLines.addTwoPointRectangle(S(sk, x, y), S(sk, x+w, y+h))
        ext = F.extrudeFeatures.addSimple(sk.profiles.item(0), V(z),
                                          adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        ext.bodies.item(0).name = name
        return ext.bodies.item(0)
    def face(body, x, y, z):
        return min(body.faces, key=lambda f: (f.centroid.x-x)**2+(f.centroid.y-y)**2+(f.centroid.z-z)**2)
    def edge(sk, idx): return sk.sketchCurves.sketchLines.item(idx)

    # Equal scale values permit both mode directions without changing geometry.
    b10 = box('R10', 0, 0, 2, 2, 1)
    s10 = r.sketches.add(r.xYConstructionPlane)
    scale = F.scaleFeatures.add(F.scaleFeatures.createInput(C(b10), s10.sketchPoints.add(S(s10, 0, 0)), V(1.5)))
    scale.name = 'PS_R10'

    # A one-sided shell has no outside thickness parameter.
    b08 = box('R08', 0, 20, 3, 3, 2)
    si = F.shellFeatures.createInput(C(face(b08, 1.5, 21.5, 2)), False)
    si.insideThickness = V(0.1)
    shell = F.shellFeatures.add(si)
    shell.name = 'PS_R08'

    # Both paths retain the same 4 mm circular section.
    sk22 = r.sketches.add(r.xYConstructionPlane)
    sk22.name = 'R22_Sk'
    l22a = sk22.sketchCurves.sketchLines.addByTwoPoints(S(sk22, 0, 40), S(sk22, 3, 40))
    sk22.sketchCurves.sketchLines.addByTwoPoints(S(sk22, 0, 42), S(sk22, 5, 42))
    pi = F.pipeFeatures.createInput(F.createPath(l22a, False),
                                    adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    pi.sectionSize = V(0.4)
    pipe = F.pipeFeatures.add(pi)
    pipe.name = 'PS_R22'
    pipe.bodies.item(0).name = 'R22'

    # Separate sketches keep each profile selector scope-unique.
    b23 = box('R23', 0, 50, 4, 3, 1)
    plane_input = r.constructionPlanes.createInput()
    plane_input.setByOffset(r.xYConstructionPlane, V(0.12))
    plane = r.constructionPlanes.add(plane_input)
    plane.name = 'R23_Pl'
    circle_sk = r.sketches.add(plane)
    circle_sk.name = 'R23_Circle'
    circle_sk.sketchCurves.sketchCircles.addByCenterRadius(S(circle_sk, 1, 51.5, 1.2), 0.4)
    rect_sk = r.sketches.add(plane)
    rect_sk.name = 'R23_Rect'
    rect_sk.sketchCurves.sketchLines.addTwoPointRectangle(
        S(rect_sk, 2.5, 51, 1.2), S(rect_sk, 3.3, 52, 1.2))
    emboss = F.embossFeatures.add(F.embossFeatures.createInput(
        [circle_sk.profiles.item(0)], [face(b23, 2, 51.5, 1)], V(0.05)))
    emboss.name = 'PS_R23'

    # Path and orientation edits have separate geometry checks.
    b21 = box('R21', 0, 60, 0.5, 0.5, 0.5)
    sk21 = r.sketches.add(r.xYConstructionPlane)
    sk21.name = 'R21_Path'
    l21a = sk21.sketchCurves.sketchLines.addByTwoPoints(S(sk21, 0, 62), S(sk21, 4, 62))
    sk21.sketchCurves.sketchLines.addByTwoPoints(S(sk21, 0, 63), S(sk21, 4, 64))
    pattern_input = F.pathPatternFeatures.createInput(
        C(b21), F.createPath(l21a, False), V(3), V(1.0),
        adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
    pattern = F.pathPatternFeatures.add(pattern_input)
    pattern.name = 'PS_R21'

    bad = []
    for i in range(d.timeline.count):
        item = d.timeline.item(i)
        if item.healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState:
            bad.append([i, item.name, int(item.healthState), item.errorOrWarningMessage])
    feature_indices = {feature.name: feature.timelineObject.index for feature in
                       (pipe, scale, emboss, pattern, shell)}
    if any(type(index) is not int for index in feature_indices.values()):
        raise RuntimeError('advanced feature timeline indices are unreadable')
    if bad or d.timeline.markerPosition != d.timeline.count:
        raise RuntimeError('advanced feature fixture is unhealthy or not at its end marker')
    print(json.dumps({'fixture': 'advanced-feature-edit', 'features': [
        'PS_R22', 'PS_R10', 'PS_R23', 'PS_R21', 'PS_R08'], 'feature_indices': feature_indices,
        'marker': d.timeline.markerPosition,
        'timeline_count': d.timeline.count, 'healthy': not bad, 'control_body': 'R10'}))
"""


_CURVED_PATTERN_FIXTURE = r"""def run(context):
    import adsk.core, adsk.fusion, json, math
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if (design is None or app.activeDocument.isSaved or design.timeline.count != 0
            or design.rootComponent.bRepBodies.count != 0
            or design.rootComponent.sketches.count != 0
            or design.rootComponent.occurrences.count):
        raise RuntimeError('curved pattern requires a fresh unsaved empty design')
    if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    root = design.rootComponent
    if design.activeComponent != root or design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('curved pattern fixture requires the root active at the end marker')
    if design.attributes.itemByName('PS', 'W2CP') is not None:
        raise RuntimeError('curved pattern fixture marker already exists')
    P, V = adsk.core.Point3D.create, adsk.core.ValueInput.createByString
    section = root.sketches.add(root.xZConstructionPlane)
    section.name = 'R6Section'
    polygon = [[1.8, 0.0], [2.4, 0.0], [2.4, 0.2], [2.0, 0.2], [2.0, 0.6], [1.8, 0.6]]
    for i, a in enumerate(polygon):
        b = polygon[(i + 1) % len(polygon)]
        section.sketchCurves.sketchLines.addByTwoPoints(P(a[0], a[1], 0), P(b[0], b[1], 0))
    if section.profiles.count != 1:
        raise RuntimeError('curved pattern asymmetric L profile is not unique')
    ext_input = root.features.extrudeFeatures.createInput(
        section.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    if ext_input.setDistanceExtent(False, V('2 mm')) is False:
        raise RuntimeError('curved pattern seed extrusion extent was refused')
    ext = root.features.extrudeFeatures.add(ext_input)
    if ext is None or ext.bodies.count != 1:
        raise RuntimeError('curved pattern seed extrusion did not create one body')
    seed = ext.bodies.item(0)
    seed.name = 'R6Seed'

    path_sketch = root.sketches.add(root.xYConstructionPlane)
    path_sketch.name = 'R6QuarterCircle'
    arc = path_sketch.sketchCurves.sketchArcs.addByCenterStartSweep(
        P(0, 0, 0), P(2, 0, 0), math.pi / 2)
    if arc is None:
        raise RuntimeError('curved pattern quarter-circle path was not created')
    control_sketch = root.sketches.add(root.xYConstructionPlane)
    control_sketch.name = 'R6ControlSketch'
    control_sketch.sketchCurves.sketchLines.addTwoPointRectangle(P(10, 0, 0), P(11, 1, 0))
    if control_sketch.profiles.count != 1:
        raise RuntimeError('curved pattern control profile is not unique')
    control_input = root.features.extrudeFeatures.createInput(
        control_sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    if control_input.setDistanceExtent(False, V('10 mm')) is False:
        raise RuntimeError('curved pattern control extrusion extent was refused')
    control_feature = root.features.extrudeFeatures.add(control_input)
    if control_feature is None or control_feature.bodies.count != 1:
        raise RuntimeError('curved pattern control extrusion did not create one body')
    control = control_feature.bodies.item(0)
    control.name = 'R6Control'
    record = {'fixture': 'W2CP', 'seed_token': seed.entityToken,
              'control_token': control.entityToken, 'path_token': arc.entityToken,
              'path_owner_token': path_sketch.entityToken,
              'source_profile_mm': [[18, 0], [24, 0], [24, 2], [20, 2], [20, 6], [18, 6]],
              'source_profile_sketch_cm': [[1.8, 0.0], [2.4, 0.0], [2.4, 0.2],
                                           [2.0, 0.2], [2.0, 0.6], [1.8, 0.6]],
              'path_center_mm': [0, 0, 0], 'path_start_mm': [20, 0, 0],
              'path_sweep_rad': math.pi / 2, 'control_cube_size_mm': 10,
              'marker': design.timeline.markerPosition, 'count': design.timeline.count}
    design.attributes.add('PS', 'W2CP', json.dumps(record))
    print('W2CP-FIXTURE ' + json.dumps(record))
"""


_CURVED_PATTERN_CENSUS = r"""def run(context):
    import adsk.core, adsk.fusion, json, math
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None or app.activeDocument.isSaved:
        raise RuntimeError('W2CP census requires the owned unsaved design')
    root, timeline = design.rootComponent, design.timeline
    mark = design.attributes.itemByName('PS', 'W2CP')
    if mark is None or timeline.markerPosition != timeline.count:
        raise RuntimeError('W2CP census requires its banked fixture at the end marker')
    record = json.loads(mark.value)
    if record.get('fixture') != 'W2CP' or root.occurrences.count or design.activeComponent != root:
        raise RuntimeError('W2CP marker, root owner, or occurrence guard differs')
    seed_hits = list(design.findEntityByToken(record['seed_token']))
    control_hits = list(design.findEntityByToken(record['control_token']))
    path_hits = list(design.findEntityByToken(record['path_token']))
    path_owner_hits = list(design.findEntityByToken(record['path_owner_token']))
    if len(seed_hits) != 1 or len(control_hits) != 1 or len(path_hits) != 1 or len(path_owner_hits) != 1:
        raise RuntimeError('W2CP source tokens do not resolve uniquely')
    feature = adsk.fusion.PathPatternFeature.cast(root.features.itemByName(FEATURE_NAME))
    if feature is None or feature.parentComponent != root:
        raise RuntimeError('W2CP public pattern feature does not resolve in the root')
    feature_token = feature.entityToken
    feature_hits = list(design.findEntityByToken(feature_token))
    if len(feature_hits) != 1 or feature_hits[0] != feature:
        raise RuntimeError('W2CP feature token does not resolve to its held wrapper')
    marker_before, count_before = timeline.markerPosition, timeline.count
    definition, definition_error, restore_error = None, None, None
    try:
        if feature.timelineObject.rollTo(True) is False:
            raise RuntimeError('feature timelineObject.rollTo(True) returned false')
        path = feature.path
        path_rows = []
        for i in range(path.count):
            entity = path.item(i).entity
            owner = entity.parentSketch
            path_rows.append({'object_type': entity.objectType,
                              'same_as_fixture_path_wrapper': entity == path_hits[0],
                              'owner_is_fixture_sketch_wrapper': owner == path_owner_hits[0],
                              'owner_name': owner.name})
        definition = {'marker': timeline.markerPosition,
                      'feature_index': feature.timelineObject.index,
                      'feature_identity_resolves': feature_hits[0] == feature,
                      'feature_owner_is_root': feature.parentComponent == root,
                      'orientation_along_path': feature.isOrientationAlongPath,
                      'pattern_element_count': feature.patternElements.count,
                      'quantity_expression': feature.quantity.expression,
                      'distance_expression': feature.distance.expression,
                      'path_count': path.count, 'path': path_rows}
    except Exception as exc:
        definition_error = type(exc).__name__ + ': ' + str(exc)
    finally:
        try:
            moved = timeline.moveToEnd()
            if moved is False or timeline.markerPosition != timeline.count:
                raise RuntimeError('timeline did not restore to its actual end marker')
        except Exception as exc:
            restore_error = type(exc).__name__ + ': ' + str(exc)

    def vector(point): return [point.x, point.y, point.z]
    def body_record(body):
        physical = body.getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy)
        normals = []
        for i in range(body.faces.count):
            face = body.faces.item(i)
            ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
            if not ok:
                raise RuntimeError('face normal read failed')
            length = math.sqrt(normal.x * normal.x + normal.y * normal.y + normal.z * normal.z)
            if not math.isfinite(length) or length <= 0:
                raise RuntimeError('face normal was not finite and nonzero')
            normals.append([normal.x / length, normal.y / length, normal.z / length])
        seed_now = list(design.findEntityByToken(record['seed_token']))
        control_now = list(design.findEntityByToken(record['control_token']))
        if len(seed_now) != 1 or len(control_now) != 1:
            raise RuntimeError('W2CP seed or control identity no longer resolves uniquely')
        return {'name': body.name, 'token': body.entityToken, 'valid': body.isValid,
                'solid': body.isSolid, 'owner_is_root': body.parentComponent == root,
                'is_seed': seed_now[0] == body, 'is_control': control_now[0] == body,
                'volume_cm3': physical.volume,
                'bounds_cm': [vector(body.boundingBox.minPoint), vector(body.boundingBox.maxPoint)],
                'vertices_cm': sorted([vector(body.vertices.item(i).geometry)
                                       for i in range(body.vertices.count)]),
                'face_normals': sorted(normals)}
    bodies, end_read_error = None, None
    if restore_error is None and timeline.markerPosition == timeline.count:
        try:
            bodies = [body_record(root.bRepBodies.item(i)) for i in range(root.bRepBodies.count)]
        except Exception as exc:
            end_read_error = type(exc).__name__ + ': ' + str(exc)
    print('W2CP-CENSUS ' + json.dumps({'feature_name': FEATURE_NAME,
          'marker_before': marker_before, 'count_before': count_before,
          'at_feature_marker': definition, 'feature_read_exception': definition_error,
          'end_restore_exception': restore_error, 'end_read_exception': end_read_error,
          'marker_after': timeline.markerPosition, 'count_after': timeline.count,
          'bodies_at_end': bodies}))
"""


def _feature_state(feature, expected_type, key, field_checks):
    """Check a public definition row and retain its stable feature address and values."""
    def check(payload):
        definition = payload.get("definition") or {}
        expected_index = (_ADVANCED_STATE.get("fixture_feature_indices") or {}).get(feature)
        ok = (definition.get("feature") == feature and definition.get("type") == expected_type
              and isinstance(definition.get("timeline_index"), int)
              and definition.get("timeline_index") == expected_index
              and definition.get("unavailable") == {})
        ok = ok and all(test(definition) for test in field_checks)
        if ok:
            _ADVANCED_STATE[key] = definition
            owner = definition.get("component")
            address = definition.get("feature_address")
            if (not isinstance(owner, str) or not owner or not isinstance(address, str)
                    or not address.rsplit("/", 1)[-1].startswith(feature + "@")):
                return _measured(feature + " public definition owner", definition, False)
            _ADVANCED_STATE[key + "_address"] = address
        return _measured(feature + " public definition at its consuming marker", definition, ok)
    return check


def _definition_matches(key, fields):
    """Compare the independent restored definition after removing transient handle strings."""
    def strip(value):
        if isinstance(value, dict):
            return {name: strip(item) for name, item in value.items()
                    if name not in ("handle", "profile_handle")}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value
    def check(payload):
        before = _ADVANCED_STATE.get(key) or {}
        after = payload.get("definition") or {}
        wanted = {field: strip(before.get(field)) for field in fields}
        got = {field: strip(after.get(field)) for field in fields}
        valid = (after.get("type") == before.get("type")
                 and after.get("feature") == before.get("feature")
                 and after.get("unavailable") == {} and got == wanted)
        return _measured(key + " restored independent definition", got, valid)
    return check


def _feature_edit_reply(feature, action, changed=True):
    """Require the public edit's independent definition, geometry and marker checks."""
    def check(payload):
        before, after = payload.get("definition_before") or {}, payload.get("definition_after") or {}
        address = before.get("feature_address")
        return _measured(feature + " public " + action + " edit", {
            "edited": payload.get("edited"), "same_feature": payload.get("same_feature"),
            "definition_matches": payload.get("definition_matches"),
            "geometry_changed": payload.get("geometry_changed"),
            "marker_restored": payload.get("marker_restored"),
            "marker_before": payload.get("marker_before"),
            "marker_after": payload.get("marker_after"),
            "health": payload.get("feature_health"),
            "new_errors": payload.get("new_timeline_errors"),
            "new_warnings": payload.get("new_timeline_warnings")},
            payload.get("edited") is True and isinstance(address, str)
            and address.rsplit("/", 1)[-1].startswith(feature + "@")
            and payload.get("same_feature") is True and payload.get("definition_matches") is True
            and payload.get("geometry_changed") is changed
            and payload.get("marker_restored") is True
            and payload.get("marker_before") == _ADVANCED_STATE.get("fixture_timeline_count")
            and payload.get("marker_after") == _ADVANCED_STATE.get("fixture_timeline_count")
            and payload.get("feature_health") == {"errors": [], "warnings": []}
            and before.get("unavailable") == {} and after.get("unavailable") == {}
            and payload.get("new_timeline_errors") == []
            and payload.get("new_timeline_warnings") == []
            and isinstance(after.get("feature_address"), str)
            and after.get("feature_address") == address)
    return check


def _fixture_result(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
    try:
        rows = [json.loads(line) for line in text.splitlines() if line.lstrip().startswith("{")]
    except ValueError:
        rows = []
    result = next((row for row in reversed(rows) if row.get("fixture") == "advanced-feature-edit"), {})
    valid = (result.get("features") == ["PS_R22", "PS_R10", "PS_R23", "PS_R21", "PS_R08"]
             and result.get("healthy") is True
             and type(result.get("timeline_count")) is int
             and result.get("timeline_count") == result.get("marker")
             and result.get("control_body") == "R10"
             and isinstance(result.get("feature_indices"), dict)
             and set(result["feature_indices"]) == set(result.get("features") or [])
             and all(type(index) is int and 0 <= index < result["timeline_count"]
                     for index in result["feature_indices"].values()))
    if valid:
        _ADVANCED_STATE["fixture_timeline_count"] = result["timeline_count"]
        _ADVANCED_STATE["fixture_feature_indices"] = result["feature_indices"]
    return _measured("bounded advanced feature fixture", result, valid)


def _roll_check(to, feature=None, key=None):
    """Require the public roll result to report its exact feature or end marker position."""
    def check(payload):
        count = _ADVANCED_STATE.get("fixture_timeline_count")
        expected = ((_ADVANCED_STATE.get("fixture_feature_indices") or {}).get(feature)
                    if to == "before" and feature else count)
        valid = (payload.get("rolled") is True and payload.get("to") == to
                 and payload.get("timeline_count") == count
                 and payload.get("marker_position") == expected
                 and payload.get("rolled_back") == count - expected)
        if feature is not None:
            valid = valid and payload.get("feature") == feature
        return _measured("public timeline roll " + (feature or "end"), {
            "to": payload.get("to"), "feature": payload.get("feature"),
            "marker_position": payload.get("marker_position"),
            "timeline_count": payload.get("timeline_count"),
            "rolled_back": payload.get("rolled_back")}, valid)
    return check


def _definition_assert(key, label, predicate):
    """Require a complete independently read definition to contain the requested state."""
    def check(payload):
        expected = _ADVANCED_STATE.get(key) or {}
        definition = payload.get("definition") or {}
        valid = (definition.get("feature") == expected.get("feature")
                 and definition.get("type") == expected.get("type")
                 and definition.get("unavailable") == {} and predicate(definition))
        return _measured(label, definition, valid)
    return check


def _advanced_edit_rows():
    """Build public definition, edit, restore and independent-read beats for five measured families."""
    rows = [("doc_get", {}, _home_document, ("advanced_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "advanced_home", "home")},
             _new_document, ("advanced_doc", lambda p: p["document_handle"])),
            ("sys_execute_script", lambda c: _combine_pin(c, "advanced_doc", {
                "script": _ADVANCED_FEATURE_FIXTURE, "read_only": False}), _fixture_result, None)]

    def write(tool, arguments, expect="ok", save=None):
        rows.append((tool, lambda c, a=arguments: _combine_pin(
            c, "advanced_doc", a(c) if callable(a) else a), expect, save))

    def roll_before(feature, key):
        rows.append(("design_edit_timeline", lambda c, f=feature, k=key: _combine_pin(
            c, "advanced_doc", {"action": "roll", "to": "before", "feature": f}),
            _roll_check("before", feature, key), None))

    def roll_end():
        rows.append(("design_edit_timeline", lambda c: _combine_pin(
            c, "advanced_doc", {"action": "roll", "to": "end"}), _roll_check("end"), None))

    def read_definition(feature, key, expected_type, fields, checks):
        roll_before(feature, key)
        rows.append(("design_get", lambda c, f=feature: {"include": ["definition"],
                     "feature": f, "units": "mm"},
                     _feature_state(feature, expected_type, key, checks), None))

    def end_marker():
        roll_end()

    def read_after_edit(feature, key, label, predicate):
        roll_before(feature, key)
        rows.append(("design_get", lambda c, f=feature: {"include": ["definition"],
                     "feature": f, "units": "mm"},
                     _definition_assert(key, label, predicate), None))
        roll_end()

    def inspect_state(key, stage):
        rows.append(("model_inspect", _combine_inspect(), _material_snapshot(key, stage), None))
        rows.append(("model_inspect", _combine_inspect("R10"), _control_snapshot(stage), None))

    # Pipe path: change to the separately named line and restore the original typed path.
    key = "adv_pipe"
    read_definition("PS_R22", key, "PipeFeature", ("section_type", "section_size", "path"), (
        lambda d: type(d.get("section_type")) is int,
        lambda d: d.get("section_size") == "4.00 mm",
        lambda d: len((d.get("path") or {}).get("references") or []) == 1))
    original = lambda c, k=key: _path_handles(_ADVANCED_STATE[k].get("path"))
    end_marker()
    inspect_state(key, "before")
    alt_path = ["R22_Sk/line:1"]
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "path", "references": alt_path}, _feature_edit_reply("PS_R22", "path"))
    inspect_state(key, "changed")
    read_after_edit("PS_R22", key, "Pipe path changed",
                    lambda d, k=key: (_path_is(d.get("path"), "R22_Sk/line:1")
                                      and _same_public_field(k, d, "section_type")
                                      and _same_public_field(k, d, "section_size")))
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "path", "references": original(c)}, _feature_edit_reply("PS_R22", "path"))
    roll_before("PS_R22", key)
    rows.append(("design_get", {"include": ["definition"], "feature": "PS_R22", "units": "mm"},
                 _definition_matches(key, ("section_type", "section_size", "path")), None))
    end_marker()
    inspect_state(key, "restored")

    # Scale mode: equal factors are retained when uniformity is toggled both ways.
    key = "adv_scale"
    read_definition("PS_R10", key, "ScaleFeature", ("is_uniform", "scale_expressions", "input_entities"), (
        lambda d: d.get("is_uniform") is True,
        lambda d: isinstance(d.get("scale_expressions"), list)
        and len(d["scale_expressions"]) == 3 and len(set(d["scale_expressions"])) == 1))
    end_marker()
    inspect_state(key, "before")
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "mode", "mode": "nonuniform"},
          _feature_edit_reply("PS_R10", "mode", changed=False))
    inspect_state(key, "same_geometry")
    read_after_edit("PS_R10", key, "Scale nonuniform mode",
                    lambda d, k=key: d.get("is_uniform") is False and _equal_scale_expressions(d)
                    and _same_public_field(k, d, "input_entities"))
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "mode", "mode": "uniform"},
          _feature_edit_reply("PS_R10", "mode", changed=False))
    read_after_edit("PS_R10", key, "Scale uniform mode",
                    lambda d, k=key: d.get("is_uniform") is True and _equal_scale_expressions(d)
                    and _same_public_field(k, d, "input_entities"))
    roll_before("PS_R10", key)
    rows.append(("design_get", {"include": ["definition"], "feature": "PS_R10", "units": "mm"},
                 _definition_matches(key, ("is_uniform", "scale_expressions", "input_entities")), None))
    end_marker()
    inspect_state(key, "restored")

    # Emboss profile: move to the rectangle profile, then restore the circle profile.
    key = "adv_emboss"
    read_definition("PS_R23", key, "EmbossFeature", ("profiles", "depth"), (
        lambda d: len(d.get("profiles") or []) == 1,
        lambda d: d.get("depth") == "0.50 mm"))
    original_profiles = lambda c, k=key: _profile_handles(_ADVANCED_STATE[k].get("profiles"))
    end_marker()
    inspect_state(key, "before")
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "inputs", "references": [{"sketch": "R23_Rect", "profile_index": 0}]},
          _feature_edit_reply("PS_R23", "inputs"))
    inspect_state(key, "changed")
    read_after_edit("PS_R23", key, "Emboss rectangle profile",
                    lambda d, k=key: (_profile_is_from(d.get("profiles"), "R23_Rect")
                                      and _same_public_field(k, d, "depth")))
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "inputs", "references": original_profiles(c)}, _feature_edit_reply("PS_R23", "inputs"))
    roll_before("PS_R23", key)
    rows.append(("design_get", {"include": ["definition"], "feature": "PS_R23", "units": "mm"},
                 _definition_matches(key, ("profiles", "depth")), None))
    end_marker()
    inspect_state(key, "restored")

    # PathPattern path and orientation: the edit and its reverse each use the end-marker public tool.
    key = "adv_pattern"
    read_definition("PS_R21", key, "PathPatternFeature",
                    ("path", "orientation", "pattern_elements", "quantity", "input_entities"), (
        lambda d: len((d.get("path") or {}).get("references") or []) == 1,
        lambda d: type(d.get("orientation")) is bool,
        lambda d: isinstance(d.get("quantity"), str)))
    original_pattern_path = lambda c, k=key: _path_handles(_ADVANCED_STATE[k].get("path"))
    end_marker()
    rows.append(("design_get", {"include": ["timeline"], "timeline_params": True,
                 "max_results": 100}, _path_pattern_distance("before"), None))
    inspect_state(key, "before")
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "path", "references": ["R21_Path/line:1"]},
          _feature_edit_reply("PS_R21", "path"))
    inspect_state(key, "path_changed")
    read_after_edit("PS_R21", key, "PathPattern replacement path",
                    lambda d, k=key: (_path_is(d.get("path"), "R21_Path/line:1")
                               and d.get("orientation") is _ADVANCED_STATE[k]["orientation"]
                               and all(_same_public_field(k, d, field) for field in (
                                   "pattern_elements", "quantity", "input_entities"))))
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "mode", "mode": "identical" if _ADVANCED_STATE[k]["orientation"] is True
          else "along_path"},
          _feature_edit_reply("PS_R21", "mode", changed=False))
    inspect_state(key, "same_as_path_changed")
    read_after_edit("PS_R21", key, "PathPattern orientation changed",
                    lambda d, k=key: (d.get("orientation") is not _ADVANCED_STATE[k]["orientation"]
                               and _path_is(d.get("path"), "R21_Path/line:1")
                               and all(_same_public_field(k, d, field) for field in (
                                   "pattern_elements", "quantity", "input_entities"))))
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "mode", "mode": "along_path" if _ADVANCED_STATE[k]["orientation"] is True
          else "identical"},
          _feature_edit_reply("PS_R21", "mode", changed=False))
    inspect_state(key, "same_as_path_changed")
    read_after_edit("PS_R21", key, "PathPattern orientation restored",
                    lambda d, k=key: (d.get("orientation") is _ADVANCED_STATE[k]["orientation"]
                               and _path_is(d.get("path"), "R21_Path/line:1")))
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "path", "references": original_pattern_path(c)}, _feature_edit_reply("PS_R21", "path"))
    roll_before("PS_R21", key)
    rows.append(("design_get", {"include": ["definition", "timeline"],
                 "feature": "PS_R21", "units": "mm", "timeline_params": True,
                 "max_results": 100},
                 _definition_matches(key, ("path", "orientation", "pattern_elements", "quantity",
                                           "input_entities")), None))
    end_marker()
    rows.append(("design_get", {"include": ["timeline"], "timeline_params": True,
                 "max_results": 100}, _path_pattern_distance("same"), None))
    inspect_state(key, "restored")

    # Shell inputs: one-sided thickness and a null outside parameter are retained exactly.
    key = "adv_shell"
    read_definition("PS_R08", key, "ShellFeature", ("input_faces", "inside_thickness",
                    "outside_thickness", "is_tangent_chain"), (
        lambda d: len(d.get("input_faces") or []) == 1,
        lambda d: d.get("inside_thickness") == "1.00 mm",
        lambda d: d.get("outside_thickness") is None,
        lambda d: d.get("is_tangent_chain") is False))
    original_faces = lambda c, k=key: _reference_handles(_ADVANCED_STATE[k].get("input_faces"))
    end_marker()
    inspect_state(key, "before")
    roll_before("PS_R08", key)
    rows.append(("find_geometry", {"target": "R08", "kind": "planar_face",
                 "nearest_to": [0, 215, 10], "max_results": 1},
                 _one_face("adv_shell_side", [0, 215, 10], [-1, 0, 0]),
                 ("adv_shell_side", lambda p: p["matches"][0]["handle"])))
    roll_end()
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "inputs", "references": [_ctx_get(c, "adv_shell_side", "shell side face")]},
          _feature_edit_reply("PS_R08", "inputs"))
    inspect_state(key, "changed")
    read_after_edit("PS_R08", key, "Shell replacement input face",
                    lambda d, k=key: (_face_is(d.get("input_faces"))
                                      and _same_public_field(k, d, "inside_thickness")
                                      and _same_public_field(k, d, "outside_thickness")
                                      and _same_public_field(k, d, "is_tangent_chain")))
    write("model_edit_feature", lambda c, k=key: {"feature": _ADVANCED_STATE[k + "_address"],
          "action": "inputs", "references": original_faces(c)}, _feature_edit_reply("PS_R08", "inputs"))
    roll_before("PS_R08", key)
    rows.append(("design_get", {"include": ["definition"], "feature": "PS_R08", "units": "mm"},
                 _definition_matches(key, ("input_faces", "inside_thickness", "outside_thickness",
                                           "is_tangent_chain")), None))
    end_marker()
    inspect_state(key, "restored")

    rows.extend([
        ("doc_activate", lambda c: {"name": _ctx_get(c, "advanced_home", "home"),
         "expect_document": _ctx_get(c, "advanced_doc", "advanced scratch")}, "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "advanced_doc", "advanced scratch"),
         "save_changes": False, "expect_document": _ctx_get(c, "advanced_home", "home")},
         _document_closed, None),
    ])

    # A second owned scratch exercises the curved path through public creation, edit, and restore.
    rows.extend([
        ("doc_new", lambda c: {"expect_document": _ctx_get(c, "advanced_home", "home")},
         _new_document, ("curved_doc", lambda p: p["document_handle"])),
        ("sys_execute_script", lambda c: _combine_pin(c, "curved_doc", {
            "script": _CURVED_PATTERN_FIXTURE, "read_only": False}),
         _curved_fixture_result, None),
        ("model_pattern_path", lambda c: _combine_pin(c, "curved_doc", {
            "bodies": ["R6Seed"], "path": "sketch:R6QuarterCircle", "quantity": 3,
            "distance": 5 * math.pi, "distance_type": "spacing", "units": "mm"}),
         _curved_pattern_created, ("curved_feature", lambda p: p["feature"])),
        ("sys_execute_script", lambda c: _curved_census_arguments(c),
         _curved_census("baseline"), None),
        ("design_edit_timeline", lambda c: _curved_roll_arguments(c, "before"),
         _curved_roll_check("before"), None),
        ("design_get", lambda c: _curved_definition_arguments(),
         _curved_definition("baseline", False), None),
        ("design_edit_timeline", lambda c: _curved_roll_arguments(c, "end"),
         _curved_roll_check("end"), None),
        ("model_edit_feature", lambda c: _curved_mode_arguments(c, "along_path"),
         _curved_edit_reply("along_path"), None),
        ("sys_execute_script", lambda c: _curved_census_arguments(c),
         _curved_census("along_path"), None),
        ("design_edit_timeline", lambda c: _curved_roll_arguments(c, "before"),
         _curved_roll_check("before"), None),
        ("design_get", lambda c: _curved_definition_arguments(),
         _curved_definition("along_path", True), None),
        ("design_edit_timeline", lambda c: _curved_roll_arguments(c, "end"),
         _curved_roll_check("end"), None),
        ("model_edit_feature", lambda c: _curved_mode_arguments(c, "identical"),
         _curved_edit_reply("identical"), None),
        ("sys_execute_script", lambda c: _curved_census_arguments(c),
         _curved_census("restored"), None),
        ("design_edit_timeline", lambda c: _curved_roll_arguments(c, "before"),
         _curved_roll_check("before"), None),
        ("design_get", lambda c: _curved_definition_arguments(),
         _curved_definition("restored", False), None),
        ("design_edit_timeline", lambda c: _curved_roll_arguments(c, "end"),
         _curved_roll_check("end"), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, "advanced_home", "home"),
         "expect_document": _ctx_get(c, "curved_doc", "curved pattern scratch")}, "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "curved_doc", "curved pattern scratch"),
         "save_changes": False, "expect_document": _ctx_get(c, "advanced_home", "home")},
         _document_closed, None),
    ])
    rows.extend(_w2_sweep_rows())
    rows.extend(_w2_solid_rows())
    rows.extend(_w2_patch_rows())
    rows.extend(_w2_rail_rows())
    rows.extend(_w2_fillet_rows())
    return rows


def _script_record(payload, prefix):
    """Parse one explicitly tagged JSON script record from a tool response."""
    text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
    for line in reversed(text.splitlines()):
        if line.startswith(prefix):
            try:
                return json.loads(line[len(prefix):])
            except ValueError:
                return {}
    return {}


def _curved_fixture_result(payload):
    """Require the measured asymmetric seed, circular path, and separate control fixture."""
    record = _script_record(payload, "W2CP-FIXTURE ")
    valid = (record.get("fixture") == "W2CP"
             and record.get("source_profile_mm") == [[18, 0], [24, 0], [24, 2],
                                                      [20, 2], [20, 6], [18, 6]]
             and record.get("path_center_mm") == [0, 0, 0]
             and record.get("path_start_mm") == [20, 0, 0]
             and record.get("control_cube_size_mm") == 10
             and _finite_num(record.get("path_sweep_rad"))
             and abs(record["path_sweep_rad"] - math.pi / 2) <= 1e-12
             and all(isinstance(record.get(key), str) and record[key]
                     for key in ("seed_token", "control_token", "path_token", "path_owner_token"))
             and type(record.get("marker")) is int and record.get("marker") == record.get("count"))
    return _measured("owned W2CP measured curved-path fixture", record, valid)


def _curved_pattern_created(payload):
    """Require public creation to report the requested path spacing and actual three instances."""
    feature = payload.get("feature") if isinstance(payload, dict) else None
    distance = payload.get("distance") if isinstance(payload, dict) else None
    quantity = payload.get("quantity") if isinstance(payload, dict) else None
    valid = (isinstance(payload, dict) and payload.get("patterned") is True
             and payload.get("type") == "path" and payload.get("entity_kind") == "bodies"
             and isinstance(feature, str) and bool(feature)
             and quantity == 3 and payload.get("distance_type") == "spacing"
             and isinstance(distance, (int, float)) and abs(distance - 5 * math.pi) <= 1e-6
             and payload.get("units") == "mm" and payload.get("start_point") == 0.0
             and payload.get("symmetric") is False)
    if valid:
        _ADVANCED_STATE["curved_feature"] = feature
    return _measured("public curved PathPattern creation", payload, valid)


def _curved_census_arguments(ctx):
    """Run the independent W2CP census for the exact public-created feature."""
    feature = _ADVANCED_STATE.get("curved_feature")
    if not isinstance(feature, str) or not feature:
        raise ValueError("public W2CP pattern feature name was not captured")
    script = _CURVED_PATTERN_CENSUS.replace("FEATURE_NAME", json.dumps(feature))
    return _combine_pin(ctx, "curved_doc", {"script": script, "read_only": False})


def _curved_definition_arguments():
    """Read the public definition for the current curved-pattern state."""
    feature = _ADVANCED_STATE.get("curved_feature")
    if not isinstance(feature, str) or not feature:
        raise ValueError("public W2CP pattern feature name was not captured")
    return {"include": ["definition"], "feature": feature, "units": "mm"}


def _curved_roll_arguments(ctx, to):
    """Roll the owned curved-pattern fixture to its definition or computed end."""
    args = {"action": "roll", "to": to}
    if to == "before":
        args["feature"] = _ADVANCED_STATE["curved_feature"]
    return _combine_pin(ctx, "curved_doc", args)


def _curved_roll_check(to):
    """Require the measured curved-pattern marker before reading or editing it."""
    def check(payload):
        count = _ADVANCED_STATE["curved_timeline_count"]
        expected = _ADVANCED_STATE["curved_feature_index"] if to == "before" else count
        valid = (payload.get("rolled") is True and payload.get("to") == to
                 and payload.get("timeline_count") == count
                 and payload.get("marker_position") == expected
                 and payload.get("rolled_back") == count - expected)
        if to == "before":
            valid = valid and payload.get("feature") == _ADVANCED_STATE["curved_feature"]
        return _measured("curved PathPattern public marker " + to, payload, valid)
    return check


def _curved_definition(stage, along_path):
    """Capture the public feature address and require its path and requested mode to read back."""
    def check(payload):
        definition = payload.get("definition") or {}
        path = definition.get("path") or {}
        refs = path.get("references") or []
        expected_path = _ADVANCED_STATE.get("curved_public_path")
        basic = (definition.get("feature") == _ADVANCED_STATE.get("curved_feature")
                 and definition.get("type") == "PathPatternFeature"
                 and definition.get("orientation") is along_path
                 and definition.get("pattern_elements") == 3
                 and definition.get("quantity") == "3"
                 and path.get("member_count") == 1 and len(refs) == 1
                 and refs[0].get("kind") == "sketch_curve"
                 and isinstance(refs[0].get("handle"), str) and bool(refs[0]["handle"])
                 and definition.get("unavailable") == {})
        address = definition.get("feature_address")
        if stage == "baseline" and basic:
            _ADVANCED_STATE["curved_public_path"] = path
            _ADVANCED_STATE["curved_feature_address"] = address
        elif expected_path is not None:
            basic = basic and path == expected_path
        else:
            basic = False
        if not isinstance(address, str) or not address.rsplit("/", 1)[-1].startswith(
                _ADVANCED_STATE.get("curved_feature", "") + "@"):
            basic = False
        elif _ADVANCED_STATE.get("curved_feature_address") is not None:
            basic = basic and address == _ADVANCED_STATE["curved_feature_address"]
        if basic:
            _ADVANCED_STATE["curved_public_stage"] = stage
        return _measured("curved PathPattern public descriptor " + stage,
                         {"orientation": definition.get("orientation"), "path": path,
                          "pattern_elements": definition.get("pattern_elements"),
                          "quantity": definition.get("quantity"), "address": address,
                          "unavailable": definition.get("unavailable")}, basic)
    return check


def _curved_mode_arguments(ctx, mode):
    """Allow each one-shot mode edit only after the prior census and descriptor passed."""
    required_stage = "baseline" if mode == "along_path" else "along_path"
    if (_ADVANCED_STATE.get("curved_census_stage") != required_stage
            or _ADVANCED_STATE.get("curved_public_stage") != required_stage):
        raise ValueError("curved PathPattern edit stopped because its preceding independent checks failed")
    previous_edit = None if mode == "along_path" else "along_path"
    if _ADVANCED_STATE.get("curved_edit_stage") != previous_edit:
        raise ValueError("curved PathPattern edit stopped because its prior public mode call did not pass")
    feature_address = _ADVANCED_STATE.get("curved_feature_address")
    if not isinstance(feature_address, str) or not feature_address:
        raise ValueError("curved PathPattern edit has no qualified public feature address")
    return _combine_pin(ctx, "curved_doc", {"feature": feature_address,
                                               "action": "mode", "mode": mode})


def _curved_edit_reply(mode):
    """Require a successful public mode edit and restored end marker before the next census."""
    def check(payload):
        count = _ADVANCED_STATE.get("curved_timeline_count")
        before = payload.get("definition_before") or {}
        after = payload.get("definition_after") or {}
        valid = (payload.get("edited") is True and payload.get("same_feature") is True
                 and payload.get("geometry_changed") is True
                 and payload.get("marker_restored") is True
                 and payload.get("marker_before") == count
                 and payload.get("marker_after") == count
                 and payload.get("feature_health") == {"errors": [], "warnings": []}
                 and payload.get("new_timeline_errors") == []
                 and payload.get("new_timeline_warnings") == []
                 and before.get("unavailable") == {} and after.get("unavailable") == {}
                 and before.get("orientation") is (mode == "identical")
                 and after.get("orientation") is (mode == "along_path")
                 and after.get("feature_address") == _ADVANCED_STATE.get("curved_feature_address"))
        if valid:
            _ADVANCED_STATE["curved_edit_stage"] = mode
        return _measured("public curved PathPattern " + mode + " edit", {
            "edited": payload.get("edited"), "same_feature": payload.get("same_feature"),
            "geometry_changed": payload.get("geometry_changed"),
            "marker_before": payload.get("marker_before"),
            "marker_after": payload.get("marker_after"),
            "definition_before": before, "definition_after": after}, valid)
    return check


def _curved_geometry(body):
    """Build a finite rounded vertices-and-normal signature for one native body."""
    vertices, normals = body.get("vertices_cm"), body.get("face_normals")
    bounds, volume = body.get("bounds_cm"), body.get("volume_cm3")
    if (not isinstance(vertices, list) or not isinstance(normals, list)
            or not isinstance(bounds, list) or len(bounds) != 2
            or not all(isinstance(vector, list) and len(vector) == 3
                       and all(_finite_num(value) for value in vector)
                       for vector in vertices + normals + bounds)
            or not _finite_num(volume)):
        return None
    def vectors(values):
        return tuple(sorted(tuple(round(value, 6) for value in vector)
                            for vector in values))
    return (vectors(vertices), vectors(normals), round(volume, 8), vectors(bounds))


def _curved_census(stage):
    """Require distinct curved copies, unchanged source/control, and exact restored geometry."""
    def check(payload):
        record = _script_record(payload, "W2CP-CENSUS ")
        marker = record.get("marker_after")
        count = record.get("count_after")
        feature = record.get("at_feature_marker") or {}
        bodies = record.get("bodies_at_end") or []
        error_free = (record.get("feature_read_exception") is None
                      and record.get("end_restore_exception") is None
                      and record.get("end_read_exception") is None
                      and type(marker) is int and marker == count
                      and record.get("marker_before") == record.get("count_before"))
        seed = [body for body in bodies if body.get("is_seed") is True]
        control = [body for body in bodies if body.get("is_control") is True]
        copies = [body for body in bodies if body.get("is_seed") is not True
                  and body.get("is_control") is not True]
        distance_expression = feature.get("distance_expression")
        try:
            distance_value = float(distance_expression.split()[0]) if isinstance(
                distance_expression, str) else None
        except (ValueError, IndexError):
            distance_value = None
        definition_ok = (feature.get("orientation_along_path") is (stage == "along_path")
                         and type(feature.get("feature_index")) is int
                         and feature.get("marker") == feature.get("feature_index")
                         and feature.get("feature_identity_resolves") is True
                         and feature.get("feature_owner_is_root") is True
                         and feature.get("pattern_element_count") == 3
                         and feature.get("quantity_expression") == "3"
                         and _finite_num(distance_value)
                         and abs(distance_value - 15.708) < 0.002
                         and feature.get("path_count") == 1
                         and len(feature.get("path") or []) == 1
                         and feature["path"][0].get("object_type") == "adsk::fusion::SketchArc"
                         and feature["path"][0].get("same_as_fixture_path_wrapper") is True
                         and feature["path"][0].get("owner_is_fixture_sketch_wrapper") is True)
        geometry_ok = (len(bodies) == 4 and len(seed) == 1 and len(control) == 1
                       and len(copies) == 2
                       and all(body.get("valid") is True and body.get("solid") is True
                               and body.get("owner_is_root") is True
                               and isinstance(body.get("vertices_cm"), list)
                               and isinstance(body.get("face_normals"), list)
                               and isinstance(body.get("bounds_cm"), list)
                               and len(body["bounds_cm"]) == 2
                               and _finite_num(body.get("volume_cm3"))
                               and all(_finite_num(value) for vector in body["vertices_cm"]
                                       for value in vector)
                               and all(_finite_num(value) for vector in body["face_normals"]
                                       for value in vector)
                               and all(_finite_num(value) for vector in body["bounds_cm"]
                                       for value in vector)
                               for body in bodies)
                       and abs(seed[0].get("volume_cm3", 0) - 0.04) <= 1e-7
                       and abs(control[0].get("volume_cm3", 0) - 1.0) <= 1e-7)
        expected_seed_vertices = {
            (1.8, 0.0, -0.6), (1.8, 0.0, 0.0), (1.8, 0.2, -0.6), (1.8, 0.2, 0.0),
            (2.0, 0.0, -0.6), (2.0, 0.0, -0.2), (2.0, 0.2, -0.6), (2.0, 0.2, -0.2),
            (2.4, 0.0, -0.2), (2.4, 0.0, 0.0), (2.4, 0.2, -0.2), (2.4, 0.2, 0.0)}
        seed_vertices = (seed[0].get("vertices_cm") or []) if len(seed) == 1 else []
        seed_vertices_valid = (isinstance(seed_vertices, list)
                               and all(isinstance(point, list) and len(point) == 3
                                       and all(_finite_num(value) for value in point)
                                       for point in seed_vertices))
        actual_seed_vertices = ({tuple(round(value, 6) for value in point)
                                 for point in seed_vertices} if seed_vertices_valid else set())
        control_bounds = (control[0].get("bounds_cm") or []) if len(control) == 1 else []
        geometry_ok = (geometry_ok and len(seed_vertices) == len(expected_seed_vertices)
                       and seed_vertices_valid
                       and actual_seed_vertices == expected_seed_vertices
                       and len(control_bounds) == 2
                       and all(isinstance(point, list) and len(point) == 3
                               and all(_finite_num(value) for value in point)
                               for point in control_bounds)
                       and all(abs(actual - expected) <= 1e-6
                               for actual_point, expected_point in zip(control_bounds,
                                   ([10.0, 0.0, 0.0], [11.0, 1.0, 1.0]))
                               for actual, expected in zip(actual_point, expected_point)))
        seed_geometry = _curved_geometry(seed[0]) if len(seed) == 1 else None
        control_geometry = _curved_geometry(control[0]) if len(control) == 1 else None
        copy_geometries = [_curved_geometry(body) for body in copies]
        state = {"seed": seed_geometry, "control": control_geometry,
                 "copies": sorted(copy_geometries) if all(
                     geometry is not None for geometry in copy_geometries) else None}
        state["copy_vertices"] = (sorted(geometry[0] for geometry in copy_geometries)
                                  if all(geometry is not None for geometry in copy_geometries) else None)
        state["copy_normals"] = (sorted(geometry[1] for geometry in copy_geometries)
                                 if all(geometry is not None for geometry in copy_geometries) else None)
        geometry_ok = geometry_ok and state["seed"] is not None and state["control"] is not None \
            and state["copies"] is not None and state["copy_vertices"] is not None \
            and state["copy_normals"] is not None
        expected_bounds = [((1.8, 0.0, -0.6), (2.4, 0.2, 0.0)),
                           ((1.2142, 1.4142, -0.6), (1.8142, 1.6142, 0.0)),
                           ((-0.2, 2.0, -0.6), (0.4, 2.2, 0.0))]
        observed_bounds = [body.get("bounds_cm") for body in (seed + copies)]
        remaining_bounds = list(expected_bounds)
        placement_ok = len(observed_bounds) == len(remaining_bounds)
        for bounds in observed_bounds:
            def matches_bounds(actual, expected):
                return (isinstance(actual, list) and len(actual) == 2
                        and all(isinstance(point, list) and len(point) == 3
                                and all(_finite_num(value) for value in point)
                                for point in actual)
                        and all(abs(value - wanted) <= 0.001
                                for actual_point, expected_point in zip(actual, expected)
                                for value, wanted in zip(actual_point, expected_point)))
            matches = [index for index, wanted in enumerate(remaining_bounds)
                       if matches_bounds(bounds, wanted)]
            if not matches:
                placement_ok = False
                break
            remaining_bounds.pop(matches[0])
        baseline = _ADVANCED_STATE.get("curved_native_baseline")
        if stage == "baseline":
            valid = error_free and definition_ok and geometry_ok and placement_ok and baseline is None
            if valid:
                _ADVANCED_STATE["curved_native_baseline"] = state
                _ADVANCED_STATE["curved_timeline_count"] = count
                _ADVANCED_STATE["curved_feature_index"] = feature["feature_index"]
        elif stage == "along_path":
            valid = (error_free and definition_ok and geometry_ok and baseline is not None
                     and state["seed"] == baseline["seed"]
                     and state["control"] == baseline["control"]
                     and state["copies"] != baseline["copies"]
                     and state["copy_vertices"] != baseline["copy_vertices"]
                     and state["copy_normals"] != baseline["copy_normals"]
                     and all(signature not in baseline["copies"] for signature in state["copies"]))
        else:
            valid = (error_free and definition_ok and geometry_ok and baseline is not None
                     and state == baseline)
        if valid:
            _ADVANCED_STATE["curved_census_stage"] = stage
        return _measured("curved PathPattern independent native geometry " + stage, {
            "feature": {key: feature.get(key) for key in (
                "orientation_along_path", "pattern_element_count", "quantity_expression",
                "distance_expression", "path_count", "path")},
            "body_count": len(bodies), "seed_identity_count": len(seed),
            "control_identity_count": len(control), "copy_count": len(copies),
            "copy_vertices_changed": state.get("copy_vertices") != (baseline or {}).get("copy_vertices"),
            "copy_normals_changed": state.get("copy_normals") != (baseline or {}).get("copy_normals"),
            "initial_seed_and_copy_placement_matches_quarter_arc": placement_ok,
            "seed_unchanged": baseline is not None and state.get("seed") == baseline.get("seed"),
            "control_unchanged": baseline is not None and state.get("control") == baseline.get("control"),
            "marker": marker, "count": count,
            "exceptions": [record.get("feature_read_exception"),
                           record.get("end_restore_exception"), record.get("end_read_exception")]},
            valid)
    return check


def _path_handles(value):
    rows = (value or {}).get("references") or []
    handles = [row.get("handle") for row in rows if isinstance(row, dict)]
    if len(handles) != len(rows) or any(not isinstance(handle, str) or not handle for handle in handles):
        raise ValueError("public Pipe/PathPattern GET did not return exact path handles")
    return handles


def _profile_handles(value):
    rows = value or []
    handles = [row.get("profile_handle") for row in rows if isinstance(row, dict)]
    if len(handles) != len(rows) or any(not isinstance(handle, str) or not handle for handle in handles):
        raise ValueError("public Emboss GET did not return exact profile handles")
    return handles


def _reference_handles(value):
    rows = value or []
    handles = [row.get("handle") for row in rows if isinstance(row, dict)]
    if len(handles) != len(rows) or any(not isinstance(handle, str) or not handle for handle in handles):
        raise ValueError("public reference GET did not return exact geometry handles")
    return handles


def _one_face(key, position, normal):
    """Require one planar face at the measured world position and with its measured normal."""
    def close_vector(value, expected, tol):
        return (isinstance(value, list) and len(value) == len(expected)
                and all(_num(a) and abs(a - b) <= tol for a, b in zip(value, expected)))
    def check(payload):
        matches = payload.get("matches") or []
        row = matches[0] if len(matches) == 1 else {}
        valid = (type(payload.get("match_count")) is int and payload["match_count"] >= 1
                 and payload.get("returned") == len(matches) == 1
                 and row.get("kind") == "planar_face"
                 and close_vector(row.get("position"), position, 0.001)
                 and close_vector(row.get("normal"), normal, 0.001)
                 and isinstance(row.get("handle"), str) and bool(row["handle"]))
        return _measured(key + " exact world face position and normal", row, valid)
    return check


def _path_is(value, handle):
    refs = (value or {}).get("references") or []
    return len(refs) == 1 and refs[0].get("handle") == handle


def _same_public_field(key, definition, field):
    def strip(value):
        if isinstance(value, dict):
            return {name: strip(item) for name, item in value.items()
                    if name not in ("handle", "profile_handle")}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value
    return strip(definition.get(field)) == strip((_ADVANCED_STATE.get(key) or {}).get(field))


def _equal_scale_expressions(definition):
    expressions = definition.get("scale_expressions")
    baseline = (_ADVANCED_STATE.get("adv_scale") or {}).get("scale_expressions")
    return (isinstance(expressions, list) and len(expressions) == 3
            and expressions == baseline and len(set(expressions)) == 1
            and all(isinstance(value, str) and value for value in expressions))


def _profile_is_from(profiles, sketch):
    return (isinstance(profiles, list) and len(profiles) == 1
            and profiles[0].get("source_sketch") == sketch
            and profiles[0].get("profile_index") == 0)


def _face_is(faces):
    if not isinstance(faces, list) or len(faces) != 1:
        return False
    geometry = faces[0].get("geometry") or {}
    point, normal = geometry.get("point_cm"), geometry.get("normal")
    return (geometry.get("frame") == "entity_context"
            and isinstance(point, list) and len(point) == 3
            and all(_num(value) for value in point)
            and abs(point[0]) <= 0.001 and 20.0 <= point[1] <= 23.0
            and 0.0 <= point[2] <= 2.0
            and isinstance(normal, list) and len(normal) == 3
            and all(_num(value) for value in normal)
            and all(abs(a - b) <= 0.001 for a, b in zip(normal, [-1.0, 0.0, 0.0])))


_ADVANCED_STATE = {}


def _snapshot_equal(first, second):
    """Compare complete shape signatures, allowing only finite measurement noise."""
    if isinstance(first, tuple) and isinstance(second, tuple):
        return len(first) == len(second) and all(
            _snapshot_equal(a, b) for a, b in zip(first, second))
    if type(first) in (int, float) and type(second) in (int, float):
        return math.isfinite(first) and math.isfinite(second) and abs(first - second) <= 1e-5
    return type(first) is type(second) and first == second


def _control_snapshot(stage):
    """Compare the independently inspected R10 body's mass, bounds and pose with its baseline."""
    def check(payload):
        mass = payload.get("mass") or {}
        center = mass.get("center_of_mass")
        minimum, maximum = payload.get("min_point") or {}, payload.get("max_point") or {}
        if (payload.get("kind") != "body" or payload.get("target") != "body 'R10'"
                or payload.get("units") != "mm" or not _finite_num(mass.get("volume"))
                or not _finite_num(mass.get("area")) or not isinstance(payload.get("lump_count"), int)
                or not isinstance(center, list) or len(center) != 3
                or not all(_finite_num(value) for value in center)
                or not all(_finite_num(point.get(axis)) for point in (minimum, maximum) for axis in "xyz")):
            return _measured("independent R10 control body " + stage, payload, False)
        state = (round(mass["volume"], 8), round(mass["area"], 8), payload["lump_count"],
                 tuple(round(value, 6) for value in center),
                 tuple(round(minimum[axis], 6) for axis in "xyz"),
                 tuple(round(maximum[axis], 6) for axis in "xyz"))
        baseline = _ADVANCED_STATE.get("adv_control_target_snapshot")
        if baseline is None:
            _ADVANCED_STATE["adv_control_target_snapshot"] = state
            valid = stage == "before"
        else:
            valid = _snapshot_equal(state, baseline)
        return _measured("independent R10 control body " + stage, state, valid)
    return check


def _material_snapshot(key, stage):
    """Compare independently inspected per-body material and bounds across forward and restore edits."""
    def check(payload):
        mass = payload.get("mass") or {}
        center = mass.get("center_of_mass")
        minimum, maximum = payload.get("min_point") or {}, payload.get("max_point") or {}
        bodies = mass.get("per_body") or []
        volume, area = mass.get("volume"), mass.get("area")
        if (payload.get("kind") != "design" or mass.get("per_body_truncated") is not False
                or mass.get("per_body_count") != len(bodies) or not bodies
                or not _finite_num(volume) or not _finite_num(area)
                or not isinstance(center, list) or len(center) != 3
                or not all(_finite_num(value) for value in center)
                or not all(_finite_num(point.get(axis)) for point in (minimum, maximum) for axis in "xyz")):
            return _measured(key + " independent body material " + stage, payload, False)
        body_state = []
        for body in bodies:
            if (not isinstance(body.get("body"), str) or not _finite_num(body.get("volume"))
                    or type(body.get("is_solid")) is not bool
                    or not isinstance(body.get("lump_count"), int)):
                return _measured(key + " complete per-body shape state " + stage, body, False)
            body_state.append((body["body"], round(body["volume"], 8), body["is_solid"],
                               body["lump_count"], body.get("occurrence")))
        body_state.sort()
        control_rows = [row for row in body_state if row[0] == "R10"]
        if len(control_rows) != 1:
            return _measured(key + " unique R10 control " + stage, control_rows, False)
        state = (round(volume, 8), round(area, 8),
                 tuple(round(value, 6) for value in center),
                 tuple(round(minimum[axis], 6) for axis in "xyz"),
                 tuple(round(maximum[axis], 6) for axis in "xyz"), tuple(body_state))
        saved = _ADVANCED_STATE.get(key + "_material_before")
        control = control_rows[0]
        control_before = _ADVANCED_STATE.get("adv_control_material")
        design_before = _ADVANCED_STATE.get("adv_design_material")
        if stage == "before":
            _ADVANCED_STATE[key + "_material_before"] = state
            if design_before is None:
                _ADVANCED_STATE["adv_design_material"] = state
            else:
                if not _snapshot_equal(state, design_before):
                    return _measured(key + " restored whole-design baseline", state, False)
            if control_before is None:
                _ADVANCED_STATE["adv_control_material"] = control
                valid = True
            else:
                valid = control == control_before
            return _measured(key + " independent body material " + stage, state, valid)
        elif stage in ("changed", "path_changed"):
            valid = saved is not None and not _snapshot_equal(state, saved)
        elif stage == "same_geometry":
            valid = saved is not None and _snapshot_equal(state, saved)
        elif stage == "same_as_path_changed":
            expected = _ADVANCED_STATE.get(key + "_material_path_changed")
            valid = expected is not None and _snapshot_equal(state, expected)
        elif stage == "restored":
            valid = saved is not None and _snapshot_equal(state, saved)
        else:
            valid = False
        valid = valid and control_before is not None and control == control_before
        if stage == "path_changed" and valid:
            _ADVANCED_STATE[key + "_material_path_changed"] = state
        return _measured(key + " independent body material " + stage, state, valid)
    return check


def _path_pattern_distance(stage):
    """Read PathPatternDelta from its public timeline row and require the R6 expression to persist."""
    def check(payload):
        timeline = payload.get("timeline") or {}
        timeline_rows = timeline.get("timeline")
        matches = [row for row in timeline_rows or []
                   if row.get("name") == "PS_R21"]
        params = matches[0].get("params") or [] if len(matches) == 1 else []
        rows = [row for row in params if row.get("role") == "PathPatternDelta"]
        measured = rows[0] if len(rows) == 1 else None
        expression = measured.get("expression") if isinstance(measured, dict) else None
        summary = timeline.get("summary")
        states = summary.get("states") if isinstance(summary, dict) else None
        count = timeline.get("count")
        valid = (type(count) is int and type(timeline.get("returned")) is int
                 and type(timeline.get("marker_position")) is int
                 and isinstance(timeline_rows, list) and len(timeline_rows) == count
                 and timeline.get("returned") == count and timeline.get("marker_position") == count
                 and timeline.get("truncated", False) is False and len(rows) == 1
                 and isinstance(states, dict) and states == {"healthy": len(timeline_rows)}
                 and isinstance(summary.get("exceptions"), list)
                 and summary["exceptions"] == []
                 and isinstance(expression, str) and expression)
        baseline = _ADVANCED_STATE.get("adv_pattern_distance")
        if stage == "before" and valid:
            _ADVANCED_STATE["adv_pattern_distance"] = expression
            passed = expression == "10.00 mm"
        else:
            passed = valid and baseline is not None and expression == baseline
        return _measured("R6 PathPatternDelta public parameter " + stage,
                         {"count": timeline.get("count"), "returned": timeline.get("returned"),
                          "parameter": measured}, passed)
    return check


_W2_SWEEP_FIXTURE = r"""def run(context):
    import adsk.core, adsk.fusion, json
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if (design is None or app.activeDocument.isSaved or design.timeline.count != 0
            or design.rootComponent.bRepBodies.count != 0
            or design.rootComponent.sketches.count != 0
            or design.rootComponent.occurrences.count):
        raise RuntimeError('W2 sweep arm requires a fresh unsaved empty design')
    root = design.rootComponent
    if design.activeComponent != root or design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 sweep arm requires the root active at its end marker')
    if design.attributes.itemByName('PS', 'W2SW') is not None:
        raise RuntimeError('W2 sweep marker already exists')
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    P, V = adsk.core.Point3D.create, adsk.core.ValueInput.createByString
    def world(sk, x, y, z): return sk.modelToSketchSpace(P(x/10, y/10, z/10))
    profile = root.sketches.add(root.yZConstructionPlane)
    profile.name = 'W2Profile'
    profile.sketchCurves.sketchLines.addTwoPointRectangle(
        world(profile, 0, -10, -5), world(profile, 0, 10, 5))
    path = root.sketches.add(root.xYConstructionPlane)
    path.name = 'W2Path'
    path.sketchCurves.sketchLines.addByTwoPoints(world(path, 0, 0, 0), world(path, 60, 0, 0))
    control_sketch = root.sketches.add(root.xYConstructionPlane)
    control_sketch.name = 'W2ControlProfile'
    control_sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        world(control_sketch, 100, 0, 0), world(control_sketch, 110, 10, 0))
    if control_sketch.profiles.count != 1 or profile.profiles.count != 1:
        raise RuntimeError('W2 sweep source or control profile is not unique')
    ei = root.features.extrudeFeatures.createInput(
        control_sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    if ei.setDistanceExtent(False, V('10 mm')) is not True:
        raise RuntimeError('W2 sweep control extent was refused')
    ef = root.features.extrudeFeatures.add(ei)
    if ef is None or ef.bodies.count != 1:
        raise RuntimeError('W2 sweep control body was not created')
    control = ef.bodies.item(0)
    control.name = 'W2Control'
    reference_input = root.features.sweepFeatures.createInput(
        profile.profiles.item(0), root.features.createPath(path.sketchCurves.sketchLines.item(0), False),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    reference_feature = root.features.sweepFeatures.add(reference_input)
    if reference_feature is None or reference_feature.bodies.count != 1:
        raise RuntimeError('W2 sweep fixture plain reference was not created')
    reference = reference_feature.bodies.item(0)
    reference.name = 'W2PlainReference'
    marker = {'profile': [[0, -10, -5], [0, 10, -5], [0, 10, 5], [0, -10, 5]],
              'path_start_mm': [0, 0, 0], 'path_end_mm': [60, 0, 0],
              'control_bounds_mm': [[100, 0, 0], [110, 10, 10]],
              'arm': __W2_ARM__, 'mode': __W2_MODE__,
              'profile_token': profile.entityToken, 'path_token': path.entityToken,
              'reference_token': reference.entityToken, 'control_token': control.entityToken}
    design.attributes.add('PS', 'W2SW', json.dumps(marker))
    if design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 sweep fixture did not finish at its end marker')
    print('W2SW-FIXTURE:' + json.dumps({'tag': 'W2SW-FIXTURE', 'marker': marker,
          'control': control.entityToken, 'timeline_count': design.timeline.count,
          'marker_position': design.timeline.markerPosition}))
"""


_W2_SWEEP_CENSUS = r"""def run(context):
    import adsk.core, adsk.fusion, json, math
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None or app.activeDocument.isSaved:
        raise RuntimeError('W2 sweep census requires the owned unsaved design')
    root = design.rootComponent
    marker_attr = design.attributes.itemByName('PS', 'W2SW')
    if marker_attr is None or design.activeComponent != root:
        raise RuntimeError('W2 sweep census lost its root-active owner marker')
    marker = json.loads(marker_attr.value)
    if marker.get('arm') != __W2_ARM__ or marker.get('mode') != __W2_MODE__:
        raise RuntimeError('W2 sweep census marker does not match this arm and mode')
    if design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 sweep census requires the timeline at its actual end marker')
    body = next((b for b in root.bRepBodies if b.name == __W2_BODY__), None)
    reference = next((b for b in root.bRepBodies if b.name == 'W2PlainReference'), None)
    control = next((b for b in root.bRepBodies if b.name == 'W2Control'), None)
    if body is None or reference is None or control is None:
        raise RuntimeError('W2 sweep census could not resolve result, plain reference, and control bodies')
    sketches = {s.name: s for s in root.sketches}
    def resolve(token, expected, label):
        hits = list(design.findEntityByToken(token))
        if len(hits) != 1:
            raise RuntimeError('W2 sweep token did not resolve exactly once: ' + label)
        obj = expected.cast(hits[0])
        if obj is None or hits[0] != obj:
            raise RuntimeError('W2 sweep token resolved to the wrong native type: ' + label)
        return obj
    resolved = {'profile': resolve(marker['profile_token'], adsk.fusion.Sketch, 'profile'),
                'path': resolve(marker['path_token'], adsk.fusion.Sketch, 'path'),
                'reference': resolve(marker['reference_token'], adsk.fusion.BRepBody, 'reference'),
                'control': resolve(marker['control_token'], adsk.fusion.BRepBody, 'control')}
    if (resolved['profile'] is None or resolved['profile'] != sketches.get('W2Profile')
            or resolved['path'] is None or resolved['path'] != sketches.get('W2Path')
            or resolved['reference'] is None or resolved['reference'] != reference
            or resolved['control'] is None or resolved['control'] != control):
        raise RuntimeError('W2 sweep census token resolution did not identify held source/control objects')
    def box(b):
        q = b.boundingBox
        return [[q.minPoint.x*10, q.minPoint.y*10, q.minPoint.z*10],
                [q.maxPoint.x*10, q.maxPoint.y*10, q.maxPoint.z*10]]
    def vertices(b):
        return [[round(v.geometry.x*10, 6), round(v.geometry.y*10, 6), round(v.geometry.z*10, 6)]
                for v in b.vertices]
    def caps(b):
        rows = []
        bounds = b.boundingBox
        low, high = bounds.minPoint.x, bounds.maxPoint.x
        for f in b.faces:
            if not isinstance(f.geometry, adsk.core.Plane):
                continue
            n = f.geometry.normal
            c = f.centroid
            if (abs(abs(n.x) - 1.0) > 1e-6 or abs(n.y) > 1e-6 or abs(n.z) > 1e-6
                    or min(abs(c.x - low), abs(c.x - high)) > 1e-5):
                continue
            rows.append({'area_mm2': f.area*100, 'center_mm': [c.x*10, c.y*10, c.z*10],
                         'normal': [n.x, n.y, n.z],
                         'vertices_mm': [[round(v.geometry.x*10, 6), round(v.geometry.y*10, 6),
                                          round(v.geometry.z*10, 6)] for v in f.vertices]})
        return rows
    def physical(b):
        p = b.getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy)
        return {'volume_mm3': p.volume*1000, 'area_mm2': p.area*100}
    def line_ends(sketch):
        result = []
        for line in sketch.sketchCurves.sketchLines:
            geom = line.worldGeometry
            a, b = geom.startPoint, geom.endPoint
            result.append(sorted([[round(a.x*10, 6), round(a.y*10, 6), round(a.z*10, 6)],
                                  [round(b.x*10, 6), round(b.y*10, 6), round(b.z*10, 6)]]))
        return sorted(result)
    profile_sketch = next((s for s in root.sketches if s.name == 'W2Profile'), None)
    path_sketch = next((s for s in root.sketches if s.name == 'W2Path'), None)
    if profile_sketch is None or path_sketch is None:
        raise RuntimeError('W2 sweep census lost its source profile or path sketch')
    health = []
    for i in range(design.timeline.count):
        item = design.timeline.item(i)
        health.append({'index': i, 'name': item.name,
                       'healthy': item.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,
                       'state': int(item.healthState)})
    result = {'tag': 'W2SW-CENSUS', 'arm': marker['arm'], 'mode': marker['mode'],
              'marker': marker, 'timeline_count': design.timeline.count,
              'marker_position': design.timeline.markerPosition,
              'health': health,
              'source_inputs': {'profile_line_count': profile_sketch.sketchCurves.sketchLines.count,
                                'profile_world_ends_mm': line_ends(profile_sketch),
                                'path_line_count': path_sketch.sketchCurves.sketchLines.count,
                                'path_world_ends_mm': line_ends(path_sketch)},
              'target': {'name': body.name, 'token': body.entityToken, 'bounds_mm': box(body),
                         'vertices_mm': vertices(body), 'caps': caps(body),
                         'physical': physical(body)},
              'reference': {'name': reference.name, 'token': reference.entityToken,
                            'bounds_mm': box(reference), 'vertices_mm': vertices(reference),
                            'caps': caps(reference), 'physical': physical(reference)},
              'control': {'name': control.name, 'token': control.entityToken,
                          'bounds_mm': box(control), 'vertices_mm': vertices(control),
                          'physical': physical(control)}}
    print('W2SW-CENSUS:' + json.dumps(result))
"""


def _w2_sweep_census_arguments(ctx, arm, mode):
    """Build the tagged independent geometry read for the currently owned sweep arm."""
    state = _ADVANCED_STATE.get('w2sw_' + arm) or {}
    body = state.get('body')
    if not isinstance(body, str) or not body:
        raise ValueError('W2 sweep census has no public result body name')
    script = (_W2_SWEEP_CENSUS.replace('__W2_ARM__', repr(arm))
              .replace('__W2_MODE__', repr(mode)).replace('__W2_BODY__', repr(body)))
    return _combine_pin(ctx, 'w2sw_' + arm + '_doc', {'script': script, 'read_only': True})


def _w2_sweep_fixture_arguments(ctx, arm, mode):
    script = (_W2_SWEEP_FIXTURE.replace('__W2_ARM__', repr(arm))
              .replace('__W2_MODE__', repr(mode)))
    return _combine_pin(ctx, 'w2sw_' + arm + '_doc', {'script': script, 'read_only': False})


def _w2_sweep_fixture_result(payload, arm, mode):
    record = _script_record(payload, 'W2SW-FIXTURE:')
    marker = record.get('marker') or {}
    valid = (record.get('tag') == 'W2SW-FIXTURE' and marker.get('arm') == arm
             and marker.get('mode') == mode
             and record.get('control') and type(record.get('timeline_count')) is int
             and record.get('timeline_count') == record.get('marker_position'))
    return _measured('owned W2 profile sweep fixture ' + arm, record, valid)


def _w2_sweep_created(payload, arm, mode):
    names = payload.get('result_bodies') or []
    params = payload.get('sweep_parameters') or {}
    expected_parameter = {'twist': 'twistAngle', 'taper': 'taperAngle',
                          'fraction': 'distanceOne'}.get(mode)
    parameter_ok = (not expected_parameter or
                    (params.get(expected_parameter) or {}).get('matches') is True)
    valid = (payload.get('swept') is True and payload.get('operation') == 'new'
             and payload.get('is_solid') is True and len(names) == 1
             and isinstance(names[0], str) and bool(names[0])
             and payload.get('path_curves') == 1 and parameter_ok)
    if valid:
        _ADVANCED_STATE['w2sw_' + arm] = {'body': names[0], 'mode': mode,
                                          'feature': payload.get('feature')}
    return _measured('public profile sweep creation ' + arm + ' ' + mode, payload, valid)


def _w2_sweep_census(stage, arm, mode):
    """Check the actual caps and bodies for a sweep arm against its independent baseline."""
    def check(payload):
        rec = _script_record(payload, 'W2SW-CENSUS:')
        target, control, reference, marker = (rec.get('target') or {}, rec.get('control') or {},
                                              rec.get('reference') or {}, rec.get('marker') or {})
        tb, cb = target.get('bounds_mm'), control.get('bounds_mm')
        tmass, cmass = target.get('physical') or {}, control.get('physical') or {}
        caps = target.get('caps') or []
        good = (rec.get('tag') == 'W2SW-CENSUS' and rec.get('arm') == arm
                and rec.get('mode') == mode and marker.get('arm') == arm
                and marker.get('mode') == mode and rec.get('timeline_count') == rec.get('marker_position')
                and isinstance(rec.get('health'), list) and rec.get('health')
                and all(row.get('healthy') is True for row in rec['health'])
                and rec.get('source_inputs') == {
                    'profile_line_count': 4,
                    'profile_world_ends_mm': [
                        [[0, -10, -5], [0, -10, 5]], [[0, -10, -5], [0, 10, -5]],
                        [[0, -10, 5], [0, 10, 5]], [[0, 10, -5], [0, 10, 5]]],
                    'path_line_count': 1, 'path_world_ends_mm': [[[0, 0, 0], [60, 0, 0]]]}
                and isinstance(tb, list) and len(tb) == 2 and isinstance(cb, list) and len(cb) == 2
                and reference.get('name') == 'W2PlainReference'
                and reference.get('bounds_mm') == [[0, -10, -5], [60, 10, 5]]
                and len(caps) >= 2 and all(_finite_num(x) for x in tmass.values())
                and all(_finite_num(x) for x in cmass.values())
                and _near((reference.get('physical') or {}).get('volume_mm3'), 12000, .2)
                and _near(cmass.get('volume_mm3'), 1000, .02)
                and cb == [[100, 0, 0], [110, 10, 10]])
        old = reference
        old_caps = old.get('caps') or []
        old_mass = old.get('physical') or {}
        def cap_cross_section(rows, x):
            hits = [face for face in rows if isinstance(face.get('center_mm'), list)
                    and len(face['center_mm']) == 3 and _near(face['center_mm'][0], x, .01)]
            if len(hits) != 1:
                return None, None
            vertices = hits[0].get('vertices_mm') or []
            if len(vertices) != 4 or any(not isinstance(v, list) or len(v) != 3 for v in vertices):
                return None, None
            return sorted((v[1], v[2]) for v in vertices), hits[0].get('area_mm2')
        def cap_matches(actual, expected, tolerance):
            return (actual is not None and len(actual) == len(expected)
                    and all(_near(actual[i][j], expected[i][j], tolerance)
                            for i in range(len(expected)) for j in range(2)))
        expected_rect = sorted((y, z) for y in (-10.0, 10.0) for z in (-5.0, 5.0))
        ref_start, _ = cap_cross_section(old_caps, 0.0)
        ref_end, _ = cap_cross_section(old_caps, 60.0)
        got_start, _ = cap_cross_section(caps, 0.0)
        got_end, got_end_area = cap_cross_section(caps, 60.0)
        if mode == 'twist':
            angle = math.radians(45.0)
            expected_twist = sorted((y*math.cos(angle)-z*math.sin(angle),
                                     y*math.sin(angle)+z*math.cos(angle))
                                    for y, z in expected_rect)
            good = (good and _near(tmass.get('volume_mm3'), old_mass.get('volume_mm3'), .2)
                    and len(old_caps) == len(caps) == 2
                    and cap_matches(ref_start, expected_rect, .001)
                    and cap_matches(ref_end, expected_rect, .001)
                    and cap_matches(got_start, expected_rect, .001)
                    and cap_matches(got_end, expected_twist, .01)
                    and tb[0][0] < tb[1][0])
        elif mode == 'taper':
            growth = 60.0*math.tan(math.radians(8.0))
            half_y, half_z = 10.0+growth, 5.0+growth
            expected_taper_end = sorted((y, z) for y in (-half_y, half_y) for z in (-half_z, half_z))
            expected_area = 4.0*half_y*half_z
            good = (good and len(old_caps) == len(caps) == 2
                    and cap_matches(ref_start, expected_rect, .001)
                    and cap_matches(ref_end, expected_rect, .001)
                    and cap_matches(got_start, expected_rect, .001)
                    and cap_matches(got_end, expected_taper_end, .02)
                    and _near(got_end_area, expected_area, .2)
                    and not _near(tmass.get('volume_mm3'), old_mass.get('volume_mm3'), .2))
        elif mode == 'fraction':
            good = (good and _near(tb[1][0] - tb[0][0], 30, .1)
                    and _near(tmass.get('volume_mm3'), 6000, 1))
        elif mode == 'plain':
            good = (good and _snapshot_equal(
                {k: target.get(k) for k in ('bounds_mm', 'caps', 'physical')},
                {k: reference.get(k) for k in ('bounds_mm', 'caps', 'physical')}))
        return _measured('independent W2 profile sweep geometry ' + arm + ' ' + stage,
                         {'tagged_census': rec, 'valid': good}, good)
    return check


def _w2_sweep_rows():
    """Exercise three profile controls on separate owned scratches with independent cap reads."""
    rows = []
    for arm, mode, extra in (('plain', 'plain', {}),
                             ('twist', 'twist', {'twist_deg': 45}),
                             ('taper', 'taper', {'taper_deg': 8}),
                             ('fraction', 'fraction', {'path_fraction': .5})):
        tag = 'w2sw_' + arm
        rows.extend([('doc_new', lambda c: {'expect_document': _ctx_get(
            c, 'advanced_home', 'home')}, _new_document,
            (tag + '_doc', lambda p: p['document_handle'])),
            ('sys_execute_script', lambda c, arm=arm, mode=mode: _w2_sweep_fixture_arguments(c, arm, mode),
             lambda p, arm=arm, mode=mode: isinstance(p, str) and p.startswith('W2SW-FIXTURE:') and
                 _w2_sweep_fixture_result(p, arm, mode), None),
            ('model_sweep', lambda c, extra=extra, tag=tag: _combine_pin(c, tag + '_doc', {
                'profile': {'sketch': 'W2Profile', 'profile_index': 0},
                'path': 'sketch:W2Path', 'operation': 'new', **extra}),
             lambda p, arm=arm, mode=mode: p.get('swept') is True and
                 _w2_sweep_created(p, arm, mode), None),
            ('sys_execute_script', lambda c, arm=arm, mode=mode: _w2_sweep_census_arguments(c, arm, mode),
             lambda p, arm=arm, mode=mode: isinstance(p, str) and p.startswith('W2SW-CENSUS:') and
                 _w2_sweep_census('result' if mode != 'plain' else 'baseline', arm, mode)(p), None),
            ('doc_activate', lambda c, tag=tag: {'name': _ctx_get(c, 'advanced_home', 'home'),
             'expect_document': _ctx_get(c, tag + '_doc', 'W2 sweep scratch')}, 'ok', None),
            ('doc_close', lambda c, tag=tag: {'name': _ctx_get(c, tag + '_doc', 'W2 sweep scratch'),
             'save_changes': False, 'expect_document': _ctx_get(c, 'advanced_home', 'home')},
             _document_closed, None)])
    return rows


_W2_SOLID_FIXTURE = r"""def run(context):
    import adsk.core, adsk.fusion, json
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if (design is None or app.activeDocument.isSaved or design.timeline.count != 0
            or design.rootComponent.bRepBodies.count != 0
            or design.rootComponent.sketches.count != 0
            or design.rootComponent.occurrences.count):
        raise RuntimeError('W2 solid orientation arm requires a fresh unsaved empty design')
    root = design.rootComponent
    if design.activeComponent != root or design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 solid orientation arm requires root active at end marker')
    if design.attributes.itemByName('PS', 'W2SO') is not None:
        raise RuntimeError('W2 solid orientation marker already exists')
    design_preferences = app.preferences.productPreferences.itemByName('Design')
    if design_preferences is None or design_preferences.is3DSketchingAllowed is not True:
        raise RuntimeError('W2 solid fixture requires Design preference is3DSketchingAllowed=true; no preference or geometry was changed')
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    P, V = adsk.core.Point3D.create, adsk.core.ValueInput.createByString
    def Pmm(x, y, z): return P(x/10, y/10, z/10)
    tool_sk = root.sketches.add(root.xYConstructionPlane)
    tool_sk.name = 'W2SolidToolProfile'
    tool_sk.sketchCurves.sketchLines.addTwoPointRectangle(Pmm(0, 0, 0), Pmm(2, 1, 0))
    if tool_sk.profiles.count != 1:
        raise RuntimeError('W2 asymmetric solid tool profile is not unique')
    ext_input = root.features.extrudeFeatures.createInput(
        tool_sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    if ext_input.setDistanceExtent(False, V('3 mm')) is not True:
        raise RuntimeError('W2 asymmetric solid tool extrusion was refused')
    ext = root.features.extrudeFeatures.add(ext_input)
    if ext is None or ext.bodies.count != 1:
        raise RuntimeError('W2 asymmetric solid tool body was not created')
    tool = ext.bodies.item(0)
    tool.name = 'W2SolidTool'
    control_sk = root.sketches.add(root.xYConstructionPlane)
    control_sk.name = 'W2SolidControlProfile'
    control_sk.sketchCurves.sketchLines.addTwoPointRectangle(Pmm(30, 0, 0), Pmm(40, 10, 0))
    control_input = root.features.extrudeFeatures.createInput(
        control_sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    if control_input.setDistanceExtent(False, V('10 mm')) is not True:
        raise RuntimeError('W2 solid control extrusion was refused')
    control_feature = root.features.extrudeFeatures.add(control_input)
    if control_feature is None or control_feature.bodies.count != 1:
        raise RuntimeError('W2 solid control body was not created')
    control = control_feature.bodies.item(0)
    control.name = 'W2SolidControl'
    path_sk = root.sketches.add(root.xYConstructionPlane)
    path_sk.name = 'W2SolidPath'
    pts = [Pmm(0, 0, 0), Pmm(0, 0, 6), Pmm(0, 6, 6), Pmm(6, 6, 6)]
    lines = [path_sk.sketchCurves.sketchLines.addByTwoPoints(pts[i], pts[i+1])
             for i in range(3)]
    if any(line is None for line in lines):
        raise RuntimeError('W2 three-segment solid path could not be created')
    actual = []
    for line in lines:
        curve = line.worldGeometry
        a, b = curve.startPoint, curve.endPoint
        actual.append(sorted([[round(a.x*10, 6), round(a.y*10, 6), round(a.z*10, 6)],
                              [round(b.x*10, 6), round(b.y*10, 6), round(b.z*10, 6)]]))
    expected = [[[0, 0, 0], [0, 0, 6]], [[0, 0, 6], [0, 6, 6]],
                [[0, 6, 6], [6, 6, 6]]]
    if actual != expected or path_sk.sketchCurves.sketchLines.count != 3:
        raise RuntimeError('W2 connected Z-to-Y-to-X path did not retain its world endpoints')
    record = {'arm': __W2_ARM__, 'path_world_ends_mm': actual,
              'source_bounds_expected_mm': [[0, 0, 0], [2, 1, 3]],
              'control_bounds_expected_mm': [[30, 0, 0], [40, 10, 10]],
              'source_token': tool.entityToken, 'control_token': control.entityToken}
    design.attributes.add('PS', 'W2SO', json.dumps(record))
    if design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 solid fixture did not finish at its end marker')
    print('W2SO-FIXTURE:' + json.dumps({'tag': 'W2SO-FIXTURE', 'marker': record,
          'source_token': tool.entityToken, 'control_token': control.entityToken,
          'timeline_count': design.timeline.count, 'marker_position': design.timeline.markerPosition}))
"""


_W2_SOLID_CENSUS = r"""def run(context):
    import adsk.core, adsk.fusion, json
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None or app.activeDocument.isSaved:
        raise RuntimeError('W2 solid census requires the owned unsaved design')
    root = design.rootComponent
    attr = design.attributes.itemByName('PS', 'W2SO')
    if attr is None or design.activeComponent != root or design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 solid census lost its root marker or end position')
    marker = json.loads(attr.value)
    if marker.get('arm') != __W2_ARM__:
        raise RuntimeError('W2 solid census marker does not match this orientation arm')
    feature_name = __W2_FEATURE__
    if not isinstance(feature_name, str) or not feature_name:
        raise RuntimeError('W2 solid census requires the created feature name')
    feature_hits = []
    for i in range(design.timeline.count):
        entity = design.timeline.item(i).entity
        if entity is not None and entity.name == feature_name:
            cast = adsk.fusion.SweepFeature.cast(entity)
            if cast is not None and cast == entity:
                feature_hits.append(cast)
    if len(feature_hits) != 1:
        raise RuntimeError('W2 solid feature name did not resolve to one SweepFeature')
    feature = feature_hits[0]
    feature_token_hits = list(design.findEntityByToken(feature.entityToken))
    feature_resolves = (len(feature_token_hits) == 1
                        and adsk.fusion.SweepFeature.cast(feature_token_hits[0]) == feature
                        and feature_token_hits[0] == feature)
    if not feature_resolves:
        raise RuntimeError('W2 solid feature token did not resolve to the held SweepFeature')
    feature_definition = {'name': feature.name, 'token_resolves_to_held_feature': feature_resolves,
                          'timeline_index': feature.timelineObject.index}
    try:
        rolled = feature.timelineObject.rollTo(True)
        feature_definition['roll_return'] = rolled
        if rolled is not True or design.timeline.markerPosition != feature_definition['timeline_index']:
            feature_definition['read_error'] = 'feature row roll did not reach its marker'
        else:
            actual_orientation = feature.solidOrientation
            orientation_names = {
                'perpendicular': adsk.fusion.SweepSolidOrientationTypes.PerpendicularSolidOrientationType,
                'rigid': adsk.fusion.SweepSolidOrientationTypes.RigidSolidOrientationType,
                'aligned': adsk.fusion.SweepSolidOrientationTypes.AlignedSolidOrientationType}
            feature_definition['orientation'] = next(
                (name for name, value in orientation_names.items() if actual_orientation == value), None)
            feature_definition['orientation_value'] = int(actual_orientation)
            if marker.get('arm') == 'aligned':
                actual_axis = feature.solidAlignedAxis
                expected_axes = [axis for axis in root.constructionAxes
                                 if axis.name == 'W2SolidAlignedZ']
                axis_hits = list(design.findEntityByToken(actual_axis.entityToken)) if actual_axis else []
                resolved_axis = (adsk.fusion.ConstructionAxis.cast(axis_hits[0])
                                 if len(axis_hits) == 1 else None)
                feature_definition['aligned_axis_resolves_to_held_axis'] = (
                    len(expected_axes) == 1 and actual_axis is not None and resolved_axis is not None
                    and axis_hits[0] == resolved_axis and resolved_axis == actual_axis
                    and resolved_axis == expected_axes[0])
                feature_definition['aligned_axis_owner_root'] = (
                    actual_axis is not None and actual_axis.component == root)
    except Exception as exc:
        feature_definition['read_error'] = type(exc).__name__ + ': ' + str(exc)[:220]
    finally:
        try:
            restored = design.timeline.moveToEnd()
            feature_definition['marker_restored_to_end'] = (
                restored is True and design.timeline.markerPosition == design.timeline.count)
        except Exception as exc:
            feature_definition['marker_restore_error'] = type(exc).__name__ + ': ' + str(exc)[:220]
    if feature_definition.get('marker_restored_to_end') is not True:
        raise RuntimeError('W2 solid census failed to restore the actual end marker after native reads')
    def resolve(token, expected, label):
        hits = list(design.findEntityByToken(token))
        if len(hits) != 1:
            raise RuntimeError('W2 solid token did not resolve exactly once: ' + label)
        obj = expected.cast(hits[0])
        if obj is None or hits[0] != obj:
            raise RuntimeError('W2 solid token resolved to the wrong native type: ' + label)
        return obj
    def body_entity(name):
        matches = [b for b in root.bRepBodies if b.name == name]
        if len(matches) != 1:
            raise RuntimeError('W2 solid census body name is not unique: ' + name)
        return matches[0]
    def body(name):
        b = body_entity(name)
        bb = b.boundingBox
        pp = b.getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy)
        vertices = sorted([[round(v.geometry.x*10, 6), round(v.geometry.y*10, 6),
                            round(v.geometry.z*10, 6)] for v in b.vertices])
        return {'name': b.name, 'owner_root': b.parentComponent == root,
                'token': b.entityToken, 'solid': b.isSolid,
                'bounds_mm': [[round(v*10, 6) for v in (bb.minPoint.x, bb.minPoint.y, bb.minPoint.z)],
                              [round(v*10, 6) for v in (bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z)]],
                'volume_mm3': pp.volume*1000, 'area_mm2': pp.area*100,
                'vertices_mm': vertices}
    source_entity = resolve(marker['source_token'], adsk.fusion.BRepBody, 'source')
    control_entity = resolve(marker['control_token'], adsk.fusion.BRepBody, 'control')
    if (source_entity != body_entity('W2SolidTool')
            or control_entity != body_entity('W2SolidControl')):
        raise RuntimeError('W2 solid census token resolution did not identify held source/control bodies')
    health = []
    for i in range(design.timeline.count):
        f = design.timeline.item(i)
        health.append({'index': i, 'name': f.name,
                       'healthy': f.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,
                       'state': int(f.healthState)})
    result = {'tag': 'W2SO-CENSUS', 'arm': marker['arm'], 'marker': marker,
              'timeline_count': design.timeline.count, 'marker_position': design.timeline.markerPosition,
              'feature_definition': feature_definition,
              'health': health, 'source': body('W2SolidTool'), 'control': body('W2SolidControl'),
              'result': body(__W2_RESULT__)}
    print('W2SO-CENSUS:' + json.dumps(result))
"""


_W2_AXIS_OWNER_READ = r"""def run(context):
    import adsk.core, adsk.fusion, json
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent if design is not None else None
    axis = root.constructionAxes.itemByName('W2SolidAlignedZ') if root is not None else None
    if axis is None or design.activeComponent != root or design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 aligned-axis owner read requires its typed axis at the root end marker')
    members = {}
    for name in ('component', 'parentComponent', 'parentSketch', 'body', 'nativeObject'):
        try:
            value = getattr(axis, name)
            members[name] = {'read': True, 'none': value is None,
                             'same_root': value == root if value is not None else False,
                             'class': type(value).__name__ if value is not None else None,
                             'object_type': getattr(value, 'objectType', None) if value is not None else None}
        except Exception as exc:
            members[name] = {'read': False, 'exception': type(exc).__name__}
    print('W2SO-AXIS-OWNER:' + json.dumps({'tag': 'W2SO-AXIS-OWNER',
          'axis_name': axis.name, 'axis_class': type(axis).__name__,
          'axis_object_type': axis.objectType, 'members': members,
          'root_class': type(root).__name__, 'root_object_type': root.objectType,
          'timeline_count': design.timeline.count, 'marker_position': design.timeline.markerPosition}))
"""


def _w2_solid_fixture_arguments(ctx, arm):
    script = _W2_SOLID_FIXTURE.replace('__W2_ARM__', repr(arm))
    return _combine_pin(ctx, 'w2so_' + arm + '_doc', {'script': script, 'read_only': False})


def _w2_solid_census_arguments(ctx, arm):
    state = _ADVANCED_STATE.get('w2so_' + arm) or {}
    result_name = state.get('result')
    feature_name = state.get('feature')
    if not isinstance(result_name, str) or not result_name or not isinstance(feature_name, str) or not feature_name:
        raise ValueError('W2 solid census has no public result body and feature names')
    script = (_W2_SOLID_CENSUS.replace('__W2_ARM__', repr(arm))
              .replace('__W2_FEATURE__', repr(feature_name))
              .replace('__W2_RESULT__', repr(result_name)))
    return _combine_pin(ctx, 'w2so_' + arm + '_doc', {'script': script, 'read_only': False})


def _w2_axis_owner_arguments(ctx):
    return _combine_pin(ctx, 'w2so_aligned_doc', {'script': _W2_AXIS_OWNER_READ, 'read_only': True})


def _w2_solid_census(stage, arm, orientation):
    """Require changed native result geometry and retained source/control bodies."""
    def check(payload):
        rec = _script_record(payload, 'W2SO-CENSUS:')
        marker = rec.get('marker') or {}
        source, control, result = (rec.get('source') or {}, rec.get('control') or {},
                                   rec.get('result') or {})
        definition = rec.get('feature_definition') or {}
        ok = (rec.get('tag') == 'W2SO-CENSUS' and rec.get('arm') == arm
              and marker.get('arm') == arm and rec.get('timeline_count') == rec.get('marker_position')
              and definition.get('token_resolves_to_held_feature') is True
              and definition.get('marker_restored_to_end') is True
              and definition.get('orientation') == orientation
              and (orientation != 'aligned' or
                   (definition.get('aligned_axis_resolves_to_held_axis') is True
                    and definition.get('aligned_axis_owner_root') is True))
              and isinstance(rec.get('health'), list) and rec['health']
              and all(h.get('healthy') is True for h in rec['health'])
              and source.get('owner_root') is True and control.get('owner_root') is True
              and source.get('solid') is True and result.get('solid') is True
              and control.get('solid') is True
              and source.get('bounds_mm') == [[0, 0, 0], [2, 1, 3]]
              and control.get('bounds_mm') == [[30, 0, 0], [40, 10, 10]]
              and _near(source.get('volume_mm3'), 6, .002)
              and _near(control.get('volume_mm3'), 1000, .02)
              and not _near(result.get('volume_mm3'), 6, .001)
              and isinstance(result.get('vertices_mm'), list) and len(result['vertices_mm']) >= 8)
        if ok:
            signature = (tuple(tuple(p) for p in result['vertices_mm']),
                         tuple(tuple(p) for p in result.get('bounds_mm') or []),
                         round(result.get('volume_mm3'), 5))
            key = 'w2so_' + arm + '_signature'
            _ADVANCED_STATE[key] = signature
            previous = _ADVANCED_STATE.get('w2so_signatures', {})
            if signature in previous.values():
                ok = False
            previous[arm] = signature
            _ADVANCED_STATE['w2so_signatures'] = previous
        return _measured('independent W2 solid sweep ' + orientation + ' ' + stage,
                         {'census': rec, 'signature': _ADVANCED_STATE.get('w2so_' + arm + '_signature')}, ok)
    return check


def _w2_solid_created(payload, arm, orientation):
    names = payload.get('result_bodies') or []
    ok = (payload.get('swept') is True and payload.get('operation') == 'new'
          and payload.get('source_retained') is True and payload.get('orientation') == orientation
          and payload.get('is_solid') is True and payload.get('path_curves') == 3
          and len(names) == 1 and isinstance(names[0], str) and bool(names[0]))
    if ok:
        _ADVANCED_STATE['w2so_' + arm] = {'result': names[0], 'feature': payload.get('feature')}
    return _measured('public solid-body sweep ' + orientation, payload, ok)


def _w2_solid_rows():
    """Compare perpendicular, rigid and aligned solid-body sweeps on a three-segment 3D path."""
    rows = []
    for arm, orientation in (('perpendicular', 'perpendicular'), ('rigid', 'rigid'), ('aligned', 'aligned')):
        tag = 'w2so_' + arm
        rows.extend([('doc_new', lambda c: {'expect_document': _ctx_get(
            c, 'advanced_home', 'home')}, _new_document,
            (tag + '_doc', lambda p: p['document_handle'])),
            ('sys_execute_script', lambda c, arm=arm: _w2_solid_fixture_arguments(c, arm),
             lambda p, arm=arm: isinstance(p, str) and p.startswith('W2SO-FIXTURE:') and _measured('owned W2 asymmetric solid fixture ' + arm,
                 _script_record(p, 'W2SO-FIXTURE:'),
                 (_script_record(p, 'W2SO-FIXTURE:').get('tag') == 'W2SO-FIXTURE'
                  and (_script_record(p, 'W2SO-FIXTURE:').get('marker') or {}).get('arm') == arm
                  and (_script_record(p, 'W2SO-FIXTURE:').get('marker') or {}).get('path_world_ends_mm') ==
                      [[[0, 0, 0], [0, 0, 6]], [[0, 0, 6], [0, 6, 6]], [[0, 6, 6], [6, 6, 6]]]
                  and _script_record(p, 'W2SO-FIXTURE:').get('timeline_count') ==
                      _script_record(p, 'W2SO-FIXTURE:').get('marker_position'))), None),
        ])
        if orientation == 'aligned':
            rows.append(('find_geometry', {'target': 'W2SolidTool', 'kind': 'line_edge',
                'nearest_to': [0, 0, 1.5], 'units': 'mm', 'max_results': 1},
                lambda p: p.get('returned') == 1 and len(p.get('matches') or []) == 1
                    and _near(p['matches'][0].get('length'), 3, .000001),
                _fg('w2so_axis_seed')))
            rows.append(('model_construction', lambda c: _combine_pin(c, tag + '_doc', {
                'kind': 'axis', 'mode': 'edge', 'axis': _ctx_get(c, 'w2so_axis_seed', 'axis seed'),
                'name': 'W2SolidAlignedZ'}),
                lambda p: _measured('typed edge-defined Z construction axis for aligned solid sweep', p,
                    bool(p.get('created') or p.get('name') == 'W2SolidAlignedZ')), None))
            rows.append(('sys_execute_script', _w2_axis_owner_arguments,
                lambda p: isinstance(p, str) and p.startswith('W2SO-AXIS-OWNER:') and _measured('read-only aligned-axis owner member census',
                    _script_record(p, 'W2SO-AXIS-OWNER:'),
                    (_script_record(p, 'W2SO-AXIS-OWNER:').get('tag') == 'W2SO-AXIS-OWNER'
                     and (_script_record(p, 'W2SO-AXIS-OWNER:').get('members') or {}).get('component', {}).get('read') is True
                     and _script_record(p, 'W2SO-AXIS-OWNER:').get('timeline_count') ==
                         _script_record(p, 'W2SO-AXIS-OWNER:').get('marker_position'))), None))
        args = {'solid_body': None, 'path': 'sketch:W2SolidPath', 'operation': 'new',
                'orientation': orientation}
        if orientation == 'aligned':
            args['solid_aligned_axis'] = 'W2SolidAlignedZ'
        rows.extend([
            ('model_sweep', lambda c, args=args, arm=arm, tag=tag: _combine_pin(c, tag + '_doc', {
                **args, 'solid_body': 'W2SolidTool'}),
             lambda p, arm=arm, orientation=orientation: p.get('swept') is True and
                 _w2_solid_created(p, arm, orientation), None),
            ('sys_execute_script', lambda c, arm=arm: _w2_solid_census_arguments(c, arm),
             lambda p, arm=arm, orientation=orientation: isinstance(p, str) and p.startswith('W2SO-CENSUS:') and
                 _w2_solid_census('result', arm, orientation)(p), None),
            ('doc_activate', lambda c, tag=tag: {'name': _ctx_get(c, 'advanced_home', 'home'),
             'expect_document': _ctx_get(c, tag + '_doc', 'W2 solid scratch')}, 'ok', None),
            ('doc_close', lambda c, tag=tag: {'name': _ctx_get(c, tag + '_doc', 'W2 solid scratch'),
             'save_changes': False, 'expect_document': _ctx_get(c, 'advanced_home', 'home')},
             _document_closed, None)])
    return rows


_W2_PATCH_FIXTURE = r"""def run(context):
    import adsk.core, adsk.fusion, json
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if (design is None or app.activeDocument.isSaved or design.timeline.count != 0
            or design.rootComponent.bRepBodies.count != 0
            or design.rootComponent.sketches.count != 0
            or design.rootComponent.occurrences.count):
        raise RuntimeError('W2 patch fixture requires a fresh unsaved empty design')
    root = design.rootComponent
    if design.activeComponent != root or design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 patch fixture requires root active at end marker')
    if design.attributes.itemByName('PS', 'W2PC') is not None:
        raise RuntimeError('W2 patch fixture marker already exists')
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    P, V = adsk.core.Point3D.create, adsk.core.ValueInput.createByString
    def Pmm(x, y, z): return P(x/10, y/10, z/10)
    def cube(name, x):
        sk = root.sketches.add(root.xYConstructionPlane)
        sk.name = name + 'Profile'
        sk.sketchCurves.sketchLines.addTwoPointRectangle(Pmm(x, 0, 0), Pmm(x+2, 2, 0))
        inp = root.features.extrudeFeatures.createInput(
            sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        if inp.setDistanceExtent(False, V('2 mm')) is not True:
            raise RuntimeError('W2 patch fixture extrusion was refused')
        feat = root.features.extrudeFeatures.add(inp)
        if feat is None or feat.bodies.count != 1:
            raise RuntimeError('W2 patch fixture body was not created')
        body = feat.bodies.item(0)
        body.name = name
        return body
    target, control = cube('W2PatchSource', 0), cube('W2PatchControl', 50)
    record = {'source_token': target.entityToken, 'control_token': control.entityToken,
              'source_bounds_mm': [[0, 0, 0], [2, 2, 2]],
              'control_bounds_mm': [[50, 0, 0], [52, 2, 2]]}
    design.attributes.add('PS', 'W2PC', json.dumps(record))
    if design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 patch fixture did not finish at end marker')
    print('W2PC-FIXTURE:' + json.dumps({'tag': 'W2PC-FIXTURE', 'marker': record,
          'timeline_count': design.timeline.count, 'marker_position': design.timeline.markerPosition}))
"""


_W2_PATCH_DEFAULTS = r"""def run(context):
    import adsk.core, adsk.fusion, json
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent if design is not None else None
    attr = design.attributes.itemByName('PS', 'W2PC') if design is not None else None
    if (attr is None or app.activeDocument.isSaved or design.activeComponent != root
            or design.timeline.markerPosition != design.timeline.count):
        raise RuntimeError('W2 patch defaults read requires the owned root-active end-marker fixture')
    marker = json.loads(attr.value)
    source_hits = list(design.findEntityByToken(marker['source_token']))
    if len(source_hits) != 1:
        raise RuntimeError('W2 patch defaults source token did not resolve exactly once')
    source = adsk.fusion.BRepBody.cast(source_hits[0])
    named_sources = [b for b in root.bRepBodies if b.name == 'W2PatchSource']
    named_source = named_sources[0] if len(named_sources) == 1 else None
    if source is None or source_hits[0] != source or source != named_source:
        raise RuntimeError('W2 patch defaults read could not resolve its held source body')
    edges = []
    endpoints = []
    for edge in source.edges:
        vs = [edge.startVertex, edge.endVertex]
        if any(v is None for v in vs) or any(abs(v.geometry.z*10 - 2) > 1e-6 for v in vs):
            continue
        points = sorted([[round(v.geometry.x*10, 6), round(v.geometry.y*10, 6),
                          round(v.geometry.z*10, 6)] for v in vs])
        edges.append(edge)
        endpoints.append(points)
    if len(edges) != 4 or len({tuple(map(tuple, p)) for p in endpoints}) != 4:
        raise RuntimeError('W2 patch defaults read did not find the unique four-edge top loop')
    coll = adsk.core.ObjectCollection.create()
    for edge in edges:
        coll.add(edge)
    inp = root.features.patchFeatures.createInput(
        coll, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    raw = inp.getContinuity()
    if not isinstance(raw, (list, tuple)) or len(raw) != 5 or raw[0] is not True:
        raise RuntimeError('W2 PatchFeatureInput.getContinuity did not return its five-part success value')
    values = [list(raw[i]) for i in range(1, 5)]
    if any(len(v) != 4 for v in values):
        raise RuntimeError('W2 native patch defaults do not have four entries per edge setting')
    identity_unique = all(values[0][i] != values[0][j]
                          for i in range(4) for j in range(i+1, 4))
    requested_cont = [adsk.fusion.SurfaceContinuityTypes.ConnectedSurfaceContinuityType,
                      adsk.fusion.SurfaceContinuityTypes.TangentSurfaceContinuityType,
                      adsk.fusion.SurfaceContinuityTypes.CurvatureSurfaceContinuityType,
                      adsk.fusion.SurfaceContinuityTypes.ConnectedSurfaceContinuityType]
    requested_weights, requested_flips = [.7, .8, .9, 1.0], [False, False, True, False]
    set_ok = inp.setContinuity(requested_cont, requested_weights, requested_flips)
    probe = inp.getContinuity()
    if not isinstance(probe, (list, tuple)) or len(probe) != 5 or probe[0] is not True:
        raise RuntimeError('W2 native varied patch probe could not read its five-part result')
    probe_values = [list(probe[i]) for i in range(1, 5)]
    edge_identity_retained = (len(probe_values[0]) == 4
                              and all(values[0][i] == probe_values[0][i] for i in range(4)))
    probe_matches_request = (set_ok is True
                             and [int(v) for v in probe_values[1]] ==
                                 [int(v) for v in requested_cont]
                             and all(abs(float(got)-want) <= 1e-8
                                     for got, want in zip(probe_values[2], requested_weights))
                             and [bool(v) for v in probe_values[3]] == requested_flips)
    print('W2PC-DEFAULTS:' + json.dumps({'tag': 'W2PC-DEFAULTS', 'marker': marker,
          'source_edges_mm': endpoints, 'native_before': {'continuity': [int(v) for v in values[1]],
          'weights': [float(v) for v in values[2]], 'flipped': [bool(v) for v in values[3]]},
          'probe': {'set_ok': set_ok is True, 'continuity': [int(v) for v in probe_values[1]],
          'weights': [float(v) for v in probe_values[2]], 'flipped': [bool(v) for v in probe_values[3]],
          'edge_identity_retained': edge_identity_retained,
          'matches_request': probe_matches_request},
          'identity_unique': identity_unique,
          'timeline_count': design.timeline.count, 'marker_position': design.timeline.markerPosition}))
"""


_W2_PATCH_CENSUS = r"""def run(context):
    import adsk.core, adsk.fusion, json, math
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent if design is not None else None
    attr = design.attributes.itemByName('PS', 'W2PC') if design is not None else None
    if (attr is None or app.activeDocument.isSaved or design.activeComponent != root
            or design.timeline.markerPosition != design.timeline.count):
        raise RuntimeError('W2 patch census requires the owned root-active end-marker fixture')
    marker = json.loads(attr.value)
    def body_entity(name):
        matches = [b for b in root.bRepBodies if b.name == name]
        if len(matches) != 1:
            raise RuntimeError('W2 patch census body name is not unique: ' + name)
        return matches[0]
    def body_record(b):
        bb = b.boundingBox
        pp = b.getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy)
        return {'name': b.name, 'owner_root': b.parentComponent == root,
                'token': b.entityToken, 'solid': b.isSolid,
                'face_count': b.faces.count, 'bounds_mm': [[bb.minPoint.x*10, bb.minPoint.y*10,
                bb.minPoint.z*10], [bb.maxPoint.x*10, bb.maxPoint.y*10, bb.maxPoint.z*10]],
                'volume_mm3': pp.volume*1000, 'area_mm2': pp.area*100}
    def body(name):
        return body_record(body_entity(name))
    def resolve(token, label):
        hits = list(design.findEntityByToken(token))
        if len(hits) != 1:
            raise RuntimeError('W2 patch token did not resolve exactly once: ' + label)
        obj = adsk.fusion.BRepBody.cast(hits[0])
        if obj is None or hits[0] != obj:
            raise RuntimeError('W2 patch token resolved to the wrong native type: ' + label)
        return obj
    source_entity = resolve(marker['source_token'], 'source')
    control_entity = resolve(marker['control_token'], 'control')
    if (source_entity != body_entity('W2PatchSource')
            or control_entity != body_entity('W2PatchControl')):
        raise RuntimeError('W2 patch census token resolution did not match the held source/control bodies')
    source, control = body_record(source_entity), body_record(control_entity)
    feature_name = __W2_FEATURE__
    feature_conditions = {'feature_name': feature_name, 'token_resolves_to_held_feature': False,
                         'per_edge': []}
    source_edge_by_label = {}
    feature_hits = []
    for i in range(design.timeline.count):
        entity = design.timeline.item(i).entity
        if entity is not None and entity.name == feature_name:
            cast = adsk.fusion.PatchFeature.cast(entity)
            if cast is not None and cast == entity:
                feature_hits.append(cast)
    if len(feature_hits) == 1:
        patch_feature = feature_hits[0]
        feature_token_hits = list(design.findEntityByToken(patch_feature.entityToken))
        resolved_feature = (adsk.fusion.PatchFeature.cast(feature_token_hits[0])
                            if len(feature_token_hits) == 1 else None)
        feature_conditions['token_resolves_to_held_feature'] = (
            resolved_feature is not None and feature_token_hits[0] == resolved_feature
            and resolved_feature == patch_feature)
        source_top_faces = [face for face in source_entity.faces
                            if isinstance(face.geometry, adsk.core.Plane)
                            and abs(abs(face.geometry.normal.z)-1.0) <= 1e-6
                            and abs(face.centroid.z*10-2.0) <= .001]
        if (feature_conditions['token_resolves_to_held_feature'] and len(source_top_faces) == 1):
            source_edges = list(source_top_faces[0].edges)
            if len(source_edges) == 4:
                try:
                    roll_index = patch_feature.timelineObject.index
                    rolled = patch_feature.timelineObject.rollTo(True)
                    feature_conditions['roll_return'] = rolled
                    feature_conditions['timeline_index'] = roll_index
                    if rolled is not True or design.timeline.markerPosition != roll_index:
                        feature_conditions['read_error'] = 'feature row roll did not reach its marker'
                    else:
                        raw = patch_feature.getContinuity()
                        if not isinstance(raw, (list, tuple)) or len(raw) != 5 or raw[0] is not True:
                            feature_conditions['read_error'] = 'PatchFeature.getContinuity returned an unexpected shape'
                        else:
                            arrays = [list(raw[i]) for i in range(1, 5)]
                            if any(len(values) != 4 for values in arrays):
                                feature_conditions['read_error'] = 'PatchFeature.getContinuity arrays were not four-wide'
                            else:
                                edges, continuities, weights, flips = arrays
                                expected_midpoints = {
                                    'bottom': (1.0, 0.0), 'right': (2.0, 1.0),
                                    'top': (1.0, 2.0), 'left': (0.0, 1.0)}
                                continuity_names = {
                                    'connected': adsk.fusion.SurfaceContinuityTypes.ConnectedSurfaceContinuityType,
                                    'tangent': adsk.fusion.SurfaceContinuityTypes.TangentSurfaceContinuityType,
                                    'curvature': adsk.fusion.SurfaceContinuityTypes.CurvatureSurfaceContinuityType}
                                for i, edge in enumerate(edges):
                                    edge_hits = list(design.findEntityByToken(edge.entityToken))
                                    resolved_edge = (adsk.fusion.BRepEdge.cast(edge_hits[0])
                                                     if len(edge_hits) == 1 else None)
                                    matches = ([candidate for candidate in source_edges
                                                if candidate == resolved_edge]
                                               if resolved_edge is not None
                                               and edge_hits[0] == resolved_edge else [])
                                    if len(matches) != 1:
                                        raise RuntimeError('feature edge did not resolve to one held source boundary wrapper')
                                    vertices = [matches[0].startVertex, matches[0].endVertex]
                                    if any(vertex is None for vertex in vertices):
                                        raise RuntimeError('source boundary edge did not have two vertices')
                                    midpoint_x = (vertices[0].geometry.x+vertices[1].geometry.x)*5
                                    midpoint_y = (vertices[0].geometry.y+vertices[1].geometry.y)*5
                                    labels = [name for name, point in expected_midpoints.items()
                                              if abs(midpoint_x-point[0]) <= .001
                                              and abs(midpoint_y-point[1]) <= .001]
                                    word = next((name for name, value in continuity_names.items()
                                                 if continuities[i] == value), None)
                                    if len(labels) != 1:
                                        raise RuntimeError('feature edge does not map to one named fixture side')
                                    source_edge_by_label[labels[0]] = matches[0]
                                    feature_conditions['per_edge'].append({
                                        'edge': labels[0], 'identity_resolves_to_source_boundary': True,
                                        'continuity': word, 'weight': float(weights[i]),
                                        'flipped': flips[i]})
                except Exception as exc:
                    feature_conditions['read_error'] = type(exc).__name__ + ': ' + str(exc)[:220]
                finally:
                    try:
                        moved = design.timeline.moveToEnd()
                        feature_conditions['marker_restored_to_end'] = (
                            moved is True and design.timeline.markerPosition == design.timeline.count)
                    except Exception as exc:
                        feature_conditions['marker_restore_error'] = type(exc).__name__ + ': ' + str(exc)[:220]
                if feature_conditions.get('marker_restored_to_end') is not True:
                    raise RuntimeError('W2 patch census failed to restore the actual end marker after feature reads')
            else:
                feature_conditions['read_error'] = 'source top boundary did not have four actual edge wrappers'
        else:
            feature_conditions['read_error'] = 'patch feature identity or unique source top face was unavailable'
    else:
        feature_conditions['read_error'] = 'created patch name did not resolve to one PatchFeature'
    result = body(__W2_PATCH_RESULT__)
    patch_matches = [b for b in root.bRepBodies if b.name == __W2_PATCH_RESULT__]
    patch = patch_matches[0] if len(patch_matches) == 1 else None
    if patch is None or patch.faces.count != 1:
        raise RuntimeError('W2 patch census expected one patch face for seam sampling')
    def normal_vec(evaluator, point):
        got = evaluator.getNormalAtPoint(point)
        if not isinstance(got, (tuple, list)) or len(got) != 2 or got[0] is not True:
            return None
        vector = got[1]
        values = [vector.x, vector.y, vector.z]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            return None
        length = math.sqrt(sum(v*v for v in values))
        return [v/length for v in values] if length > 0 else None
    seams = []
    edge_rows = {row['edge']: row for row in feature_conditions['per_edge']}
    for label in ('bottom', 'right', 'top', 'left'):
        try:
            source_edge = source_edge_by_label[label]
            ends = [source_edge.startVertex, source_edge.endVertex]
            if any(v is None for v in ends): raise RuntimeError('source edge endpoint is unreadable')
            source_mid = adsk.core.Point3D.create(*(
                (getattr(ends[0].geometry, k)+getattr(ends[1].geometry, k))/2 for k in ('x','y','z')))
            adjacent = list(source_edge.faces)
            if len(adjacent) != 2 or not any(face == source_top_faces[0] for face in adjacent):
                raise RuntimeError('source seam edge does not have exactly top and side faces')
            source_samples = []
            for face in adjacent:
                mapped, uv = face.evaluator.getParameterAtPoint(source_mid)
                if mapped is not True or uv is None or face.evaluator.isParameterOnFace(uv) is not True:
                    raise RuntimeError('adjacent source face UV is not on its bounded face')
                located, source_point = face.evaluator.getPointAtParameter(uv)
                if located is not True or source_point is None:
                    raise RuntimeError('adjacent source face point is unreadable')
                source_gap = source_mid.distanceTo(source_point)*10
                source_normal = normal_vec(face.evaluator, source_point)
                if source_gap > .001 or source_normal is None:
                    raise RuntimeError('adjacent source face midpoint or normal is unreadable')
                geom = face.geometry.normal
                role = 'top' if face == source_top_faces[0] else 'side_' + max(
                    ('x','y','z'), key=lambda a: abs(getattr(geom, a)))
                source_samples.append({'role': role, 'gap_mm': source_gap, 'normal': source_normal})
            patch_hits = []
            for patch_edge in patch.edges:
                ev = patch_edge.evaluator; ex = ev.getParameterExtents()
                if (not isinstance(ex, (tuple, list)) or len(ex) != 3 or ex[0] is not True
                        or not math.isfinite(ex[1]) or not math.isfinite(ex[2]) or ex[2] <= ex[1]):
                    continue
                got = ev.getParameterAtPoint(source_mid)
                if (not isinstance(got, (tuple, list)) or len(got) != 2 or got[0] is not True
                        or not math.isfinite(got[1]) or not ex[1] <= got[1] <= ex[2]):
                    continue
                ok, point = ev.getPointAtParameter(got[1])
                gap = source_mid.distanceTo(point)*10 if ok is True and point is not None else float('inf')
                if gap <= .01: patch_hits.append((patch_edge, point, got[1], gap))
            if len(patch_hits) != 1:
                raise RuntimeError('source seam midpoint does not identify one finite-domain patch edge')
            patch_edge, edge_point, param, edge_gap = patch_hits[0]
            patch_faces = list(patch_edge.faces)
            if len(patch_faces) != 1: raise RuntimeError('open patch edge does not have one patch face')
            face_ev = patch_faces[0].evaluator
            mapped, uv = face_ev.getParameterAtPoint(source_mid)
            if mapped is not True or uv is None:
                raise RuntimeError('source seam midpoint surface parameter is unreadable')
            patch_face_on_face = face_ev.isParameterOnFace(uv)
            located, patch_point = face_ev.getPointAtParameter(uv)
            if located is not True or patch_point is None:
                raise RuntimeError('patch surface projection is unreadable at source seam midpoint')
            face_gap = source_mid.distanceTo(patch_point)*10
            patch_normal = normal_vec(face_ev, patch_point)
            if face_gap > .001 or patch_normal is None:
                raise RuntimeError('patch surface projection or normal is outside measured tolerance')
            feature_row = edge_rows[label]
            expected_role = ('side_x' if label == 'right' and feature_row['continuity'] == 'tangent'
                             and feature_row['flipped'] is False else
                             'top' if label == 'top' and feature_row['continuity'] == 'curvature'
                             and feature_row['flipped'] is True else None)
            selected = [row for row in source_samples if row['role'] == expected_role] if expected_role else []
            angle = None
            if expected_role:
                if len(selected) != 1: raise RuntimeError('continuity setting did not select its measured adjacent source face')
                dot = sum(a*b for a, b in zip(patch_normal, selected[0]['normal']))
                angle = math.degrees(math.acos(max(-1.0, min(1.0, abs(dot)))))
            seams.append({'edge': label, 'continuity': feature_row['continuity'], 'flipped': feature_row['flipped'],
                          'source_midpoint_mm': [source_mid.x*10, source_mid.y*10, source_mid.z*10],
                          'patch_parameter': param, 'patch_match_count': 1,
                          'patch_edge_approximation_gap_mm': edge_gap,
                          'patch_face_uv': [uv.x, uv.y], 'patch_face_on_face': patch_face_on_face,
                          'patch_face_gap_mm': face_gap,
                          'patch_normal': patch_normal, 'source_faces': source_samples,
                          'selected_source_role': expected_role, 'normal_plane_angle_deg': angle})
        except Exception as exc:
            seams.append({'edge': label, 'read_error': type(exc).__name__ + ': ' + str(exc)})
    health = []
    for i in range(design.timeline.count):
        f = design.timeline.item(i)
        health.append({'name': f.name,
                       'healthy': f.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,
                       'state': int(f.healthState)})
    print('W2PC-CENSUS:' + json.dumps({'tag': 'W2PC-CENSUS', 'marker': marker,
          'timeline_count': design.timeline.count, 'marker_position': design.timeline.markerPosition,
          'health': health, 'source': source, 'control': control, 'result': result,
          'seam_normals': seams, 'feature_conditions': feature_conditions}))
"""


def _w2_patch_args(ctx, script, read_only=True):
    return _combine_pin(ctx, 'w2pc_doc', {'script': script, 'read_only': read_only})


def _w2_patch_defaults_result(payload):
    rec = _script_record(payload, 'W2PC-DEFAULTS:')
    probe = rec.get('probe') or {}
    valid = (rec.get('tag') == 'W2PC-DEFAULTS' and len(rec.get('source_edges_mm') or []) == 4
             and len((rec.get('native_before') or {}).get('continuity') or []) ==
                 len((rec.get('native_before') or {}).get('weights') or []) ==
                 len((rec.get('native_before') or {}).get('flipped') or []) == 4
             and probe.get('set_ok') is True and len(probe.get('continuity') or []) ==
                 len(probe.get('weights') or []) == len(probe.get('flipped') or []) == 4
             and probe.get('edge_identity_retained') is True
             and probe.get('matches_request') is True
             and len(set(probe.get('continuity') or [])) == 3
             and len(set(probe.get('weights') or [])) == 4
             and sum(probe.get('flipped') or []) == 1
             and rec.get('identity_unique') is True
             and rec.get('timeline_count') == rec.get('marker_position'))
    return _measured('native per-edge patch defaults before public mutation', rec, valid)


def _w2_patch_edge_found(payload, edge, position):
    rows = payload.get('matches') or []
    match = rows[0] if len(rows) == 1 else {}
    ok = (payload.get('returned') == 1 and match.get('kind') == 'line_edge'
          and match.get('handle') and isinstance(match.get('position'), list)
          and len(match['position']) == 3
          and all(_near(match['position'][i], position[i], .001) for i in range(3)))
    return _measured('unique W2 patch boundary edge ' + edge, match, ok)


def _w2_patch_census_arguments(ctx):
    state = _ADVANCED_STATE.get('w2pc') or {}
    result, feature = state.get('result'), state.get('feature')
    if not isinstance(result, str) or not result or not isinstance(feature, str) or not feature:
        raise ValueError('W2 patch census has no public result body and feature names')
    script = (_W2_PATCH_CENSUS.replace('__W2_PATCH_RESULT__', repr(result))
              .replace('__W2_FEATURE__', repr(feature)))
    return _w2_patch_args(ctx, script, False)


def _w2_patch_census(payload):
    rec = _script_record(payload, 'W2PC-CENSUS:')
    source, control, result = (rec.get('source') or {}, rec.get('control') or {}, rec.get('result') or {})
    health = rec.get('health') or []
    seams = rec.get('seam_normals') or []
    feature = rec.get('feature_conditions') or {}
    feature_rows = feature.get('per_edge') or []
    feature_map = {row.get('edge'): row for row in feature_rows if isinstance(row, dict)}
    feature_expected = {'bottom': 'connected', 'right': 'tangent',
                        'top': 'curvature', 'left': 'connected'}
    feature_conditions_ok = (
        feature.get('token_resolves_to_held_feature') is True
        and feature.get('marker_restored_to_end') is True and not feature.get('read_error')
        and len(feature_rows) == 4 and len(feature_map) == 4
        and set(feature_map) == set(feature_expected)
        and all(row.get('identity_resolves_to_source_boundary') is True
                and row.get('continuity') == feature_expected[name]
                and _finite_num(row.get('weight')) and type(row.get('flipped')) is bool
                for name, row in feature_map.items())
        and _near(feature_map.get('bottom', {}).get('weight'), .7, 1e-8)
        and feature_map.get('bottom', {}).get('flipped') is False
        and feature_map.get('top', {}).get('flipped') is True)
    bounds = (result.get('bounds_mm') or [])
    finite_bounds = (len(bounds) == 2 and all(isinstance(point, list) and len(point) == 3
                      and all(_finite_num(v) for v in point) for point in bounds))
    seam_map = {row.get('edge'): row for row in seams if isinstance(row, dict)}
    seam_expected = {'bottom': (1, 0), 'right': (2, 1), 'top': (1, 2), 'left': (0, 1)}
    def sampled_faces_ok(row):
        faces = row.get('source_faces')
        return (isinstance(faces, list) and len(faces) == 2 and all(
            _finite_num(face.get('gap_mm')) and face['gap_mm'] <= .001
            and isinstance(face.get('normal'), list) and len(face['normal']) == 3
            and all(_finite_num(v) for v in face['normal']) for face in faces))
    def seam_ok(label):
        row = seam_map.get(label) or {}; point = row.get('source_midpoint_mm'); xy = seam_expected[label]
        return (isinstance(point, list) and len(point) == 3
                and all(_near(point[i], wanted, .001) for i, wanted in enumerate((*xy, 2)))
                and row.get('patch_match_count') == 1 and _finite_num(row.get('patch_parameter'))
                and _finite_num(row.get('patch_edge_approximation_gap_mm'))
                and row['patch_edge_approximation_gap_mm'] <= .01
                and isinstance(row.get('patch_face_uv'), list) and len(row['patch_face_uv']) == 2
                and all(_finite_num(v) for v in row['patch_face_uv'])
                and type(row.get('patch_face_on_face')) is bool
                and _finite_num(row.get('patch_face_gap_mm')) and row['patch_face_gap_mm'] <= .001
                and isinstance(row.get('patch_normal'), list) and len(row['patch_normal']) == 3
                and all(_finite_num(v) for v in row['patch_normal']) and sampled_faces_ok(row))
    tangent_seam, curvature_seam = seam_map.get('right') or {}, seam_map.get('top') or {}
    seam_normals_ok = (len(seams) == 4 and len(seam_map) == 4
        and all(seam_ok(name) for name in ('bottom', 'right', 'top', 'left'))
        and tangent_seam.get('continuity') == 'tangent' and tangent_seam.get('flipped') is False
        and tangent_seam.get('selected_source_role') == 'side_x'
        and _finite_num(tangent_seam.get('normal_plane_angle_deg'))
        and tangent_seam['normal_plane_angle_deg'] <= .05
        and curvature_seam.get('continuity') == 'curvature' and curvature_seam.get('flipped') is True
        and curvature_seam.get('selected_source_role') == 'top'
        and _finite_num(curvature_seam.get('normal_plane_angle_deg'))
        and curvature_seam['normal_plane_angle_deg'] <= .05)
    ok = (rec.get('tag') == 'W2PC-CENSUS' and rec.get('timeline_count') == rec.get('marker_position')
          and bool(health) and all(row.get('healthy') is True for row in health)
          and source.get('owner_root') is True and control.get('owner_root') is True
          and source.get('bounds_mm') == [[0, 0, 0], [2, 2, 2]]
          and control.get('bounds_mm') == [[50, 0, 0], [52, 2, 2]]
          and _near(source.get('volume_mm3'), 8, .002)
          and _near(control.get('volume_mm3'), 8, .002)
          and result.get('solid') is False and result.get('face_count') == 1
          and _finite_num(result.get('area_mm2')) and result.get('area_mm2') > 0
          and finite_bounds and seam_normals_ok and feature_conditions_ok)
    return _measured('independent W2 per-edge patch and source/control preservation', rec, ok)


def _w2_patch_created(payload):
    rows = payload.get('edge_conditions') or []
    result = payload.get('result_body')
    expected = _ADVANCED_STATE.get('w2pc_requested') or []
    by_edge = {row.get('edge'): row for row in rows if isinstance(row, dict)}
    mapped = (len(by_edge) == 4 and all(
        edge in by_edge and by_edge[edge].get('continuity') == continuity
        and (_finite_num(by_edge[edge].get('weight')) if weight is None
             else _near(by_edge[edge].get('weight'), weight, 1e-8))
        and (type(by_edge[edge].get('flipped')) is bool if flipped is None
             else by_edge[edge].get('flipped') is flipped)
        for edge, continuity, weight, flipped in expected))
    ok = (payload.get('patched') is True and payload.get('is_solid') is False
          and payload.get('boundary_edge_count') == 4 and len(rows) == 4
          and len(expected) == 4 and mapped
          and isinstance(result, str) and bool(result)
          and {row.get('continuity') for row in rows} == {'connected', 'tangent', 'curvature'}
          and any(row.get('flipped') is True for row in rows))
    if ok:
        _ADVANCED_STATE['w2pc'] = {'result': result, 'feature': payload.get('feature'),
                                   'conditions': rows}
    return _measured('public per-edge patch settings retained', payload, ok)


def _w2_patch_arguments(ctx):
    handles = [_ctx_get(ctx, 'w2pc_edge' + str(i), 'boundary edge') for i in range(4)]
    _ADVANCED_STATE['w2pc_requested'] = [
        (handles[0], 'connected', .7, False), (handles[1], 'tangent', None, None),
        (handles[2], 'curvature', None, True), (handles[3], 'connected', None, None)]
    return _combine_pin(ctx, 'w2pc_doc', {
        'boundary': handles,
        'edge_conditions': [
            {'edge': handles[0], 'continuity': 'connected', 'weight': .7, 'flipped': False},
            {'edge': handles[1], 'continuity': 'tangent'},
            {'edge': handles[2], 'continuity': 'curvature', 'flipped': True},
            {'edge': handles[3], 'continuity': 'connected'}]})


def _w2_patch_rows():
    """Set a complete mixed per-edge patch map and read the actual patch surface independently."""
    rows = [
        ('doc_get', {}, _home_document, ('w2pc_home', _home_address)),
        ('doc_new', lambda c: {'expect_document': _ctx_get(c, 'w2pc_home', 'home')},
         _new_document, ('w2pc_doc', lambda p: p['document_handle'])),
        ('sys_execute_script', lambda c: _w2_patch_args(c, _W2_PATCH_FIXTURE, False),
         lambda p: isinstance(p, str) and p.startswith('W2PC-FIXTURE:') and _measured('owned W2 patch source and control fixture', _script_record(p, 'W2PC-FIXTURE:'),
             (_script_record(p, 'W2PC-FIXTURE:').get('tag') == 'W2PC-FIXTURE'
              and _script_record(p, 'W2PC-FIXTURE:').get('timeline_count') ==
                  _script_record(p, 'W2PC-FIXTURE:').get('marker_position'))), None),
        ('find_geometry', {'target': 'W2PatchSource', 'kind': 'line_edge',
         'nearest_to': [1, 0, 2], 'units': 'mm', 'max_results': 1},
         lambda p: p.get('returned') == 1 and _w2_patch_edge_found(p, 'bottom', [1, 0, 2]), _fg('w2pc_edge0')),
        ('find_geometry', {'target': 'W2PatchSource', 'kind': 'line_edge',
         'nearest_to': [2, 1, 2], 'units': 'mm', 'max_results': 1},
         lambda p: p.get('returned') == 1 and _w2_patch_edge_found(p, 'right', [2, 1, 2]), _fg('w2pc_edge1')),
        ('find_geometry', {'target': 'W2PatchSource', 'kind': 'line_edge',
         'nearest_to': [1, 2, 2], 'units': 'mm', 'max_results': 1},
         lambda p: p.get('returned') == 1 and _w2_patch_edge_found(p, 'top', [1, 2, 2]), _fg('w2pc_edge2')),
        ('find_geometry', {'target': 'W2PatchSource', 'kind': 'line_edge',
         'nearest_to': [0, 1, 2], 'units': 'mm', 'max_results': 1},
         lambda p: p.get('returned') == 1 and _w2_patch_edge_found(p, 'left', [0, 1, 2]), _fg('w2pc_edge3')),
        ('sys_execute_script', lambda c: _w2_patch_args(c, _W2_PATCH_DEFAULTS, False),
         _w2_patch_defaults_result, None),
        ('surface_patch', _w2_patch_arguments,
         _w2_patch_created, None),
        ('sys_execute_script', _w2_patch_census_arguments, _w2_patch_census, None),
        ('doc_activate', lambda c: {'name': _ctx_get(c, 'w2pc_home', 'home'),
         'expect_document': _ctx_get(c, 'w2pc_doc', 'W2 patch scratch')}, 'ok', None),
        ('doc_close', lambda c: {'name': _ctx_get(c, 'w2pc_doc', 'W2 patch scratch'),
         'save_changes': False, 'expect_document': _ctx_get(c, 'w2pc_home', 'home')},
         _document_closed, None)]
    return rows


_W2_RAIL_FIXTURE = r"""def run(context):
    import adsk.core, adsk.fusion, json
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if (design is None or app.activeDocument.isSaved or design.timeline.count != 0
            or design.rootComponent.bRepBodies.count != 0
            or design.rootComponent.sketches.count != 0
            or design.rootComponent.occurrences.count):
        raise RuntimeError('W2 fitted-rail fixture requires a fresh unsaved empty design')
    root = design.rootComponent
    if design.activeComponent != root or design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 fitted-rail fixture requires root active at end marker')
    if design.attributes.itemByName('PS', 'W2IR') is not None:
        raise RuntimeError('W2 fitted-rail marker already exists')
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    P, V = adsk.core.Point3D.create, adsk.core.ValueInput.createByString
    def Pmm(x, y, z): return P(x/10, y/10, z/10)
    def extrude(name, sketch, distance):
        inp = root.features.extrudeFeatures.createInput(
            sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        if inp.setDistanceExtent(False, V(distance)) is not True:
            raise RuntimeError('W2 fitted-rail fixture extrusion was refused: ' + name)
        feat = root.features.extrudeFeatures.add(inp)
        if feat is None or feat.bodies.count != 1:
            raise RuntimeError('W2 fitted-rail fixture body was not created: ' + name)
        body = feat.bodies.item(0)
        body.name = name
        return body
    def rect_sketch(name, plane, lo, hi):
        sk = root.sketches.add(plane)
        sk.name = name
        sk.sketchCurves.sketchLines.addTwoPointRectangle(Pmm(*lo), Pmm(*hi))
        if sk.profiles.count != 1:
            raise RuntimeError('W2 fitted-rail fixture profile is not unique: ' + name)
        return sk
    source = extrude('W2RailSource', rect_sketch('W2RailSourceProfile', root.xYConstructionPlane,
                     (0, 0, 0), (2, 2, 0)), '2 mm')
    control = extrude('W2RailControl', rect_sketch('W2RailControlProfile', root.xYConstructionPlane,
                      (50, 0, 0), (52, 2, 0)), '2 mm')
    plane_input = root.constructionPlanes.createInput()
    if plane_input.setByOffset(root.xYConstructionPlane, V('2.25 mm')) is not True:
        raise RuntimeError('W2 fitted-rail offset plane was refused')
    rail_plane = root.constructionPlanes.add(plane_input)
    if rail_plane is None:
        raise RuntimeError('W2 fitted-rail offset plane was not created')
    rail_sk = rect_sketch('W2RailDonorProfile', rail_plane, (.5, .95, 0), (1.5, 1.05, 0))
    donor = extrude('W2RailDonor', rail_sk, '.25 mm')
    rail_edges = []
    for edge in donor.edges:
        vertices = [edge.startVertex, edge.endVertex]
        if any(vertex is None for vertex in vertices):
            continue
        endpoints = sorted([[round(v.geometry.x*10, 6), round(v.geometry.y*10, 6),
                             round(v.geometry.z*10, 6)] for v in vertices])
        if endpoints == [[.5, .95, 2.5], [1.5, .95, 2.5]]:
            rail_edges.append(edge)
    if len(rail_edges) != 1:
        raise RuntimeError('W2 interior rail edge is not unique')
    record = {'source_token': source.entityToken, 'control_token': control.entityToken,
              'donor_token': donor.entityToken, 'rail_token': rail_edges[0].entityToken,
              'source_bounds_mm': [[0, 0, 0], [2, 2, 2]],
              'control_bounds_mm': [[50, 0, 0], [52, 2, 2]],
              'donor_bounds_mm': [[.5, .95, 2.25], [1.5, 1.05, 2.5]],
              'rail_endpoints_mm': [[.5, .95, 2.5], [1.5, .95, 2.5]]}
    design.attributes.add('PS', 'W2IR', json.dumps(record))
    if design.timeline.markerPosition != design.timeline.count:
        raise RuntimeError('W2 fitted-rail fixture did not finish at end marker')
    print('W2IR-FIXTURE:' + json.dumps({'tag': 'W2IR-FIXTURE', 'marker': record,
          'timeline_count': design.timeline.count, 'marker_position': design.timeline.markerPosition}))
"""


_W2_RAIL_CENSUS = r"""def run(context):
    import adsk.core, adsk.fusion, json, math
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent if design is not None else None
    attr = design.attributes.itemByName('PS', 'W2IR') if design is not None else None
    if (attr is None or app.activeDocument.isSaved or design.activeComponent != root
            or design.timeline.markerPosition != design.timeline.count):
        raise RuntimeError('W2 rail census requires the owned root-active end-marker fixture')
    marker = json.loads(attr.value)
    def named(name):
        found = [b for b in root.bRepBodies if b.name == name]
        if len(found) != 1:
            raise RuntimeError('W2 rail census body name is not unique: ' + name)
        return found[0]
    def resolve(token, expected, label):
        hits = list(design.findEntityByToken(token))
        if len(hits) != 1:
            raise RuntimeError('W2 rail token did not resolve exactly once: ' + label)
        obj = expected.cast(hits[0])
        if obj is None or hits[0] != obj:
            raise RuntimeError('W2 rail token resolved to the wrong native type: ' + label)
        return obj
    source = resolve(marker['source_token'], adsk.fusion.BRepBody, 'source')
    control = resolve(marker['control_token'], adsk.fusion.BRepBody, 'control')
    donor = resolve(marker['donor_token'], adsk.fusion.BRepBody, 'donor')
    if source != named('W2RailSource') or control != named('W2RailControl') or donor != named('W2RailDonor'):
        raise RuntimeError('W2 rail token identity did not match held source/control/donor bodies')
    if any(body.parentComponent != root for body in (source, control, donor)):
        raise RuntimeError('W2 rail token owner did not match the root fixture component')
    rail = resolve(marker['rail_token'], adsk.fusion.BRepEdge, 'rail')
    if rail.body != donor:
        raise RuntimeError('W2 rail census could not resolve the held donor edge')
    patch = named(__W2_RAIL_RESULT__)
    if patch.isSolid is not False or patch.faces.count != 1:
        raise RuntimeError('W2 rail census expected one open patch face')
    edge_eval = rail.evaluator
    extent = edge_eval.getParameterExtents()
    if not isinstance(extent, (tuple, list)) or len(extent) != 3 or extent[0] is not True:
        raise RuntimeError('W2 rail curve parameter extents were unreadable')
    lo, hi = extent[1:]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lo, hi)) or hi <= lo:
        raise RuntimeError('W2 rail curve parameter bounds were not finite and increasing')
    face = patch.faces.item(0)
    samples = []
    for fraction in (.1, .3, .5, .7, .9):
        ok, source_point = edge_eval.getPointAtParameter(lo + (hi-lo)*fraction)
        if ok is not True or source_point is None:
            raise RuntimeError('W2 rail curve point evaluation failed at a predeclared fraction')
        got, uv = face.evaluator.getParameterAtPoint(source_point)
        if got is not True or uv is None or face.evaluator.isParameterOnFace(uv) is not True:
            raise RuntimeError('W2 patch could not map a rail sample to its bounded face domain')
        on_surface, surface_point = face.evaluator.getPointAtParameter(uv)
        if on_surface is not True or surface_point is None:
            raise RuntimeError('W2 patch could not evaluate a rail sample on its face')
        gap_mm = source_point.distanceTo(surface_point)*10
        points = [source_point.x*10, source_point.y*10, source_point.z*10]
        if not all(math.isfinite(v) for v in points+[gap_mm]) or gap_mm < 0:
            raise RuntimeError('W2 rail sample contains nonfinite geometry')
        samples.append({'fraction': fraction, 'rail_point_mm': points, 'gap_mm': gap_mm,
                        'parameter_on_face': True})
    def physical(body):
        bb = body.boundingBox
        pp = body.getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy)
        return {'bounds_mm': [[bb.minPoint.x*10, bb.minPoint.y*10, bb.minPoint.z*10],
                              [bb.maxPoint.x*10, bb.maxPoint.y*10, bb.maxPoint.z*10]],
                'volume_mm3': pp.volume*1000, 'area_mm2': pp.area*100, 'solid': body.isSolid}
    health = []
    for i in range(design.timeline.count):
        f = design.timeline.item(i)
        health.append({'name': f.name,
                       'healthy': f.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,
                       'state': int(f.healthState)})
    result = {'tag': 'W2IR-CENSUS', 'marker': marker, 'timeline_count': design.timeline.count,
              'marker_position': design.timeline.markerPosition,
              'health': health,
              'source': physical(source), 'control': physical(control), 'donor': physical(donor),
              'patch': physical(patch), 'rail_samples': samples}
    print('W2IR-CENSUS:' + json.dumps(result))
"""


def _w2_rail_arguments(ctx):
    name = (_ADVANCED_STATE.get('w2ir') or {}).get('result')
    if not isinstance(name, str) or not name:
        raise ValueError('W2 fitted-rail census has no public result body name')
    script = _W2_RAIL_CENSUS.replace('__W2_RAIL_RESULT__', repr(name))
    return _combine_pin(ctx, 'w2ir_doc', {'script': script, 'read_only': True})


def _w2_rail_created(payload):
    name = payload.get('result_body')
    ok = (payload.get('patched') is True and payload.get('is_solid') is False
          and payload.get('interior_rail_count') == 1 and isinstance(name, str) and bool(name))
    if ok:
        _ADVANCED_STATE['w2ir'] = {'result': name, 'feature': payload.get('feature')}
    return _measured('public BRep-edge interior-rail patch creation', payload, ok)


def _w2_rail_census(payload):
    rec = _script_record(payload, 'W2IR-CENSUS:')
    samples = rec.get('rail_samples') or []
    health = rec.get('health') or []
    ok = (rec.get('tag') == 'W2IR-CENSUS' and rec.get('timeline_count') == rec.get('marker_position')
          and bool(health) and all(row.get('healthy') is True for row in health)
          and (rec.get('source') or {}).get('bounds_mm') == [[0, 0, 0], [2, 2, 2]]
          and (rec.get('control') or {}).get('bounds_mm') == [[50, 0, 0], [52, 2, 2]]
          and (rec.get('donor') or {}).get('bounds_mm') == [[.5, .95, 2.25], [1.5, 1.05, 2.5]]
          and (rec.get('patch') or {}).get('solid') is False
          and _near(((rec.get('patch') or {}).get('bounds_mm') or [[0, 0, 0], [0, 0, 0]])[1][2], 2.5, .02)
          and len(samples) == 5 and [s.get('fraction') for s in samples] == [.1, .3, .5, .7, .9]
          and all(s.get('parameter_on_face') is True and _finite_num(s.get('gap_mm'))
                  and s['gap_mm'] <= .02 for s in samples)
          and _near((rec.get('source') or {}).get('volume_mm3'), 8, .002)
          and _near((rec.get('control') or {}).get('volume_mm3'), 8, .002)
          and _near((rec.get('donor') or {}).get('volume_mm3'), .025, .001))
    return _measured('five-point BRep rail fit and source/donor/control preservation', rec, ok)


def _w2_rail_rows():
    """Prove an interior BRep rail lies on the returned patch at five bounded samples."""
    rows = [
        ('doc_get', {}, _home_document, ('w2ir_home', _home_address)),
        ('doc_new', lambda c: {'expect_document': _ctx_get(c, 'w2ir_home', 'home')},
         _new_document, ('w2ir_doc', lambda p: p['document_handle'])),
        ('sys_execute_script', lambda c: _combine_pin(c, 'w2ir_doc',
            {'script': _W2_RAIL_FIXTURE, 'read_only': False}),
         lambda p: isinstance(p, str) and p.startswith('W2IR-FIXTURE:') and _measured('owned five-point BRep rail fixture', _script_record(p, 'W2IR-FIXTURE:'),
             (_script_record(p, 'W2IR-FIXTURE:').get('tag') == 'W2IR-FIXTURE'
              and _script_record(p, 'W2IR-FIXTURE:').get('timeline_count') ==
                  _script_record(p, 'W2IR-FIXTURE:').get('marker_position'))), None)]
    for i, position in enumerate(([1, 0, 2], [2, 1, 2], [1, 2, 2], [0, 1, 2])):
        rows.append(('find_geometry', {'target': 'W2RailSource', 'kind': 'line_edge',
            'nearest_to': position, 'units': 'mm', 'max_results': 1},
            lambda p, i=i, position=position: p.get('returned') == 1 and
                _w2_patch_edge_found(p, 'boundary' + str(i), position),
            _fg('w2ir_boundary' + str(i))))
    rows.extend([
        ('find_geometry', {'target': 'W2RailDonor', 'kind': 'line_edge',
         'nearest_to': [1, .95, 2.5], 'units': 'mm', 'max_results': 1},
         lambda p: p.get('returned') == 1 and
             _w2_patch_edge_found(p, 'interior rail', [1, .95, 2.5]), _fg('w2ir_rail')),
        ('surface_patch', lambda c: _combine_pin(c, 'w2ir_doc', {
            'boundary': [_ctx_get(c, 'w2ir_boundary0', 'boundary edge'),
                         _ctx_get(c, 'w2ir_boundary1', 'boundary edge'),
                         _ctx_get(c, 'w2ir_boundary2', 'boundary edge'),
                         _ctx_get(c, 'w2ir_boundary3', 'boundary edge')],
            'interior_rails': [_ctx_get(c, 'w2ir_rail', 'interior BRep rail')]}),
         _w2_rail_created, None),
        ('sys_execute_script', _w2_rail_arguments, _w2_rail_census, None),
        ('doc_activate', lambda c: {'name': _ctx_get(c, 'w2ir_home', 'home'),
         'expect_document': _ctx_get(c, 'w2ir_doc', 'W2 rail scratch')}, 'ok', None),
        ('doc_close', lambda c: {'name': _ctx_get(c, 'w2ir_doc', 'W2 rail scratch'),
         'save_changes': False, 'expect_document': _ctx_get(c, 'w2ir_home', 'home')},
         _document_closed, None)])
    return rows


_W2_FILLET_FIXTURE = r"""def run(context):
    import adsk.core, adsk.fusion, json
    app = adsk.core.Application.get()
    doc = app.activeDocument
    design = adsk.fusion.Design.cast(app.activeProduct)
    if (doc is None or doc.isSaved or design is None or
            design.designType != adsk.fusion.DesignTypes.ParametricDesignType):
        raise RuntimeError('W2 fillet case requires a fresh unsaved parametric design')
    root, timeline = design.rootComponent, design.timeline
    if (design.activeComponent != root or timeline.markerPosition != timeline.count
            or root.bRepBodies.count or timeline.count or root.sketches.count
            or root.occurrences.count):
        raise RuntimeError('W2 fillet case requires root active, end marker, and empty stock/history')
    case = __W2_CASE__
    if design.attributes.itemByName('PS', 'W2F') is not None:
        raise RuntimeError('W2 fillet case marker already exists')
    def block(name, x):
        sk = root.sketches.add(root.xYConstructionPlane)
        sk.name = name + 'Sketch'
        sk.sketchCurves.sketchLines.addTwoPointRectangle(
            adsk.core.Point3D.create(x, 0, 0), adsk.core.Point3D.create(x + 2.2, 2, 0))
        if sk.profiles.count != 1:
            raise RuntimeError(name + ' profile is not unique')
        inp = root.features.extrudeFeatures.createInput(
            sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        if inp.setDistanceExtent(False, adsk.core.ValueInput.createByString('18 mm')) is not True:
            raise RuntimeError(name + ' extrusion extent was refused')
        feat = root.features.extrudeFeatures.add(inp)
        if feat is None or feat.bodies.count != 1:
            raise RuntimeError(name + ' body was not created')
        body = feat.bodies.item(0)
        body.name = name
        body.attributes.add('PS', 'W2F', '20261007-' + case + '-' + name)
        return body
    target, control = block('W2FilletTarget', 0), block('W2FilletControl', 3)
    vertical = []
    for edge in target.edges:
        b = edge.boundingBox
        dx, dy, dz = (b.maxPoint.x-b.minPoint.x, b.maxPoint.y-b.minPoint.y,
                      b.maxPoint.z-b.minPoint.z)
        if dz > 1.7 and dx < 1e-7 and dy < 1e-7:
            vertical.append(edge)
    vertical.sort(key=lambda e: (e.boundingBox.minPoint.x, e.boundingBox.minPoint.y))
    if len(vertical) != 4:
        raise RuntimeError('W2 fillet fixture expected four vertical target edges')
    edge_a, edge_b = vertical[0], vertical[-1]
    edge_a.attributes.add('PS', 'W2F', '20261007-' + case + '-edge-a')
    edge_b.attributes.add('PS', 'W2F', '20261007-' + case + '-edge-b')
    record = {'case': case, 'target_token': target.entityToken,
              'control_token': control.entityToken, 'edge_a_token': edge_a.entityToken,
              'edge_b_token': edge_b.entityToken,
              'target_marker': '20261007-' + case + '-W2FilletTarget',
              'control_marker': '20261007-' + case + '-W2FilletControl',
              'edge_a_marker': '20261007-' + case + '-edge-a',
              'edge_b_marker': '20261007-' + case + '-edge-b',
              'fixture_count': timeline.count, 'timeline_marker': timeline.markerPosition}
    design.attributes.add('PS', 'W2F', json.dumps(record))
    if timeline.markerPosition != timeline.count:
        raise RuntimeError('W2 fillet fixture did not finish at its end marker')
    def shape(body):
        b = body.boundingBox
        pp = body.getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy)
        vertices = sorted([[round(v.geometry.x*10, 6), round(v.geometry.y*10, 6),
                            round(v.geometry.z*10, 6)] for v in body.vertices])
        return {'owner_root': body.parentComponent == root, 'solid': body.isSolid,
                'bounds_mm': [[round(b.minPoint.x*10, 6), round(b.minPoint.y*10, 6), round(b.minPoint.z*10, 6)],
                              [round(b.maxPoint.x*10, 6), round(b.maxPoint.y*10, 6), round(b.maxPoint.z*10, 6)]],
                'volume_mm3': pp.volume*1000, 'vertices_mm': vertices}
    print('W2F-FIXTURE:' + json.dumps({'tag': 'W2F-FIXTURE', 'marker': record,
          'timeline_count': timeline.count, 'marker_position': timeline.markerPosition,
          'target': shape(target), 'control': shape(control)}))
"""


_W2_FILLET_CENSUS = r"""def run(context):
    import adsk.core, adsk.fusion, json, math
    app = adsk.core.Application.get()
    doc = app.activeDocument
    design = adsk.fusion.Design.cast(app.activeProduct)
    if doc is None or doc.isSaved or design is None:
        raise RuntimeError('W2 fillet census requires the owned unsaved design')
    root, timeline = design.rootComponent, design.timeline
    attr = design.attributes.itemByName('PS', 'W2F')
    if attr is None or design.activeComponent != root:
        raise RuntimeError('W2 fillet census lost its root-active fixture marker')
    marker = json.loads(attr.value)
    if marker.get('case') != __W2_CASE__:
        raise RuntimeError('W2 fillet census case marker mismatch')
    def resolve(token, expected):
        hits = list(design.findEntityByToken(token))
        if len(hits) != 1:
            raise RuntimeError('W2 fillet census fixture token did not resolve once')
        obj = expected.cast(hits[0])
        if obj is None or hits[0] != obj:
            raise RuntimeError('W2 fillet census fixture token resolved to wrong native type')
        return obj
    def require_tag(obj, name, value):
        tag = obj.attributes.itemByName('PS', 'W2F')
        if tag is None or tag.value != value:
            raise RuntimeError('W2 fillet census fixture attribute mismatch: ' + name)
    feature = None
    feature_name = __W2_FEATURE_NAME__
    sets = None
    read_errors = []
    target_at_marker = control_at_marker = None
    edge_a_identity = edge_b_identity = False
    if feature_name is not None:
        found = [f for f in root.features.filletFeatures if f.name == feature_name]
        if len(found) != 1:
            raise RuntimeError('W2 fillet census could not resolve the unique public feature name')
        feature = found[0]
        set_rows = []
        try:
            if feature.timelineObject.rollTo(True) is not True:
                raise RuntimeError('W2 fillet census could not roll to its feature marker')
            if timeline.markerPosition != feature.timelineObject.index:
                raise RuntimeError('W2 fillet census did not reach the feature marker')
            target_at_marker = resolve(marker['target_token'], adsk.fusion.BRepBody)
            control_at_marker = resolve(marker['control_token'], adsk.fusion.BRepBody)
            edge_a = resolve(marker['edge_a_token'], adsk.fusion.BRepEdge)
            edge_b = resolve(marker['edge_b_token'], adsk.fusion.BRepEdge)
            require_tag(target_at_marker, 'target', marker['target_marker'])
            require_tag(control_at_marker, 'control', marker['control_marker'])
            require_tag(edge_a, 'edge-a', marker['edge_a_marker'])
            require_tag(edge_b, 'edge-b', marker['edge_b_marker'])
            edge_a_identity = edge_b_identity = True
            for i in range(feature.edgeSets.count):
                item = feature.edgeSets.item(i)
                row = {'index': i, 'object_type': item.objectType,
                       'continuity': safe(lambda item=item: int(item.continuity)),
                       'tangent_chain': safe(lambda item=item: item.isTangentChain),
                       'edge_count': safe(lambda item=item: item.edges.count),
                       'contains_edge_a': any(e == edge_a for e in item.edges),
                       'contains_edge_b': any(e == edge_b for e in item.edges)}
                asym = adsk.fusion.AsymmetricFilletEdgeSet.cast(item)
                const = adsk.fusion.ConstantRadiusFilletEdgeSet.cast(item)
                variable = adsk.fusion.VariableRadiusFilletEdgeSet.cast(item)
                if asym is not None:
                    row.update({'kind': 'asymmetric',
                                'offset_one_mm': safe(lambda: asym.offsetOne.value*10),
                                'offset_one_expression': safe(lambda: asym.offsetOne.expression),
                                'offset_two_mm': safe(lambda: asym.offsetTwo.value*10),
                                'offset_two_expression': safe(lambda: asym.offsetTwo.expression),
                                'flipped': safe(lambda: asym.isFlipped)})
                elif const is not None:
                    row.update({'kind': 'constant', 'radius_mm': safe(lambda: const.radius.value*10),
                                'radius_expression': safe(lambda: const.radius.expression)})
                elif variable is not None:
                    row.update({'kind': 'variable',
                                'start_radius_mm': safe(lambda: variable.startRadius.value*10),
                                'start_expression': safe(lambda: variable.startRadius.expression),
                                'end_radius_mm': safe(lambda: variable.endRadius.value*10),
                                'end_expression': safe(lambda: variable.endRadius.expression),
                                'mid_radius_count': safe(lambda: variable.midRadii.count),
                                'mid_position_count': safe(lambda: variable.midPositions.count)})
                else:
                    row['kind'] = 'other'
                set_rows.append(row)
        except Exception as exc:
            read_errors.append(type(exc).__name__ + ': ' + str(exc))
        finally:
            moved = timeline.moveToEnd()
            if moved is not True or timeline.markerPosition != timeline.count:
                raise RuntimeError('W2 fillet census did not restore and verify the timeline end marker')
        sets = set_rows
        try:
            target = resolve(marker['target_token'], adsk.fusion.BRepBody)
            control = resolve(marker['control_token'], adsk.fusion.BRepBody)
            target_identity = target_at_marker is not None and target == target_at_marker
            control_identity = control_at_marker is not None and control == control_at_marker
        except Exception as exc:
            read_errors.append(type(exc).__name__ + ': ' + str(exc))
            target = control = None
            target_identity = control_identity = False
    else:
        if timeline.markerPosition != timeline.count or timeline.count != marker['fixture_count']:
            raise RuntimeError('W2 refusal census expected the unchanged fixture end marker and count')
        target = resolve(marker['target_token'], adsk.fusion.BRepBody)
        control = resolve(marker['control_token'], adsk.fusion.BRepBody)
        edge_a = resolve(marker['edge_a_token'], adsk.fusion.BRepEdge)
        edge_b = resolve(marker['edge_b_token'], adsk.fusion.BRepEdge)
        require_tag(target, 'target', marker['target_marker'])
        require_tag(control, 'control', marker['control_marker'])
        require_tag(edge_a, 'edge-a', marker['edge_a_marker'])
        require_tag(edge_b, 'edge-b', marker['edge_b_marker'])
        target_identity = control_identity = True
        edge_a_identity = edge_b_identity = True
    def shape(body):
        b = body.boundingBox
        pp = body.getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy)
        vertices = sorted([[round(v.geometry.x*10, 6), round(v.geometry.y*10, 6),
                            round(v.geometry.z*10, 6)] for v in body.vertices])
        faces = []
        for face in body.faces:
            p = face.pointOnFace
            normal = face.evaluator.getNormalAtPoint(p)
            faces.append({'point_mm': [p.x*10, p.y*10, p.z*10],
                          'normal': ([normal[1].x, normal[1].y, normal[1].z]
                                     if isinstance(normal, (tuple, list)) and len(normal) == 2
                                     and normal[0] is True else None),
                          'area_mm2': face.area*100})
        return {'owner_root': body.parentComponent == root, 'solid': body.isSolid,
                'bounds_mm': [[round(b.minPoint.x*10, 6), round(b.minPoint.y*10, 6), round(b.minPoint.z*10, 6)],
                              [round(b.maxPoint.x*10, 6), round(b.maxPoint.y*10, 6), round(b.maxPoint.z*10, 6)]],
                'volume_mm3': pp.volume*1000, 'area_mm2': pp.area*100,
                'vertices_mm': vertices, 'faces': faces}
    health = []
    for i in range(timeline.count):
        item = timeline.item(i)
        health.append({'index': i, 'name': item.name,
                       'healthy': item.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,
                       'state': int(item.healthState)})
    print('W2F-CENSUS:' + json.dumps({'tag': 'W2F-CENSUS', 'case': marker['case'],
          'marker_before': marker['fixture_count'], 'timeline_count': timeline.count,
          'marker_position': timeline.markerPosition,
          'feature_name': feature_name, 'feature_token_resolves': (None if feature is None else
              resolve(feature.entityToken, adsk.fusion.FilletFeature) == feature),
          'feature_sets': sets, 'feature_read_errors': read_errors,
                    'target_identity': target_identity, 'control_identity': control_identity,
          'edge_a_identity': edge_a_identity, 'edge_b_identity': edge_b_identity,
          'target': shape(target), 'control': shape(control), 'health': health}))


def safe(fn):
    try:
        return fn()
    except Exception as exc:
        return {'read_error': type(exc).__name__ + ': ' + str(exc)}
"""


def _w2_fillet_fixture_arguments(ctx, case):
    script = _W2_FILLET_FIXTURE.replace('__W2_CASE__', repr(case))
    return _combine_pin(ctx, 'w2f_' + case + '_doc', {'script': script, 'read_only': False})


def _w2_fillet_census_arguments(ctx, case, feature_name=None):
    state = _ADVANCED_STATE.get('w2f_' + case) or {}
    script = (_W2_FILLET_CENSUS.replace('__W2_CASE__', repr(case))
              .replace('__W2_FEATURE_NAME__', repr(feature_name)))
    return _combine_pin(ctx, 'w2f_' + case + '_doc', {'script': script, 'read_only': False})


def _w2_fillet_fixture_result(payload, case):
    rec = _script_record(payload, 'W2F-FIXTURE:')
    marker = rec.get('marker') or {}
    target, control = rec.get('target') or {}, rec.get('control') or {}
    ok = (rec.get('tag') == 'W2F-FIXTURE' and marker.get('case') == case
          and marker.get('target_token') and marker.get('control_token')
          and marker.get('edge_a_token') and marker.get('edge_b_token')
          and marker.get('fixture_count') == marker.get('timeline_marker')
          and rec.get('timeline_count') == rec.get('marker_position') == marker.get('fixture_count')
          and target.get('bounds_mm') == [[0, 0, 0], [22, 20, 18]]
          and control.get('bounds_mm') == [[30, 0, 0], [52, 20, 18]]
          and _near(target.get('volume_mm3'), 7920, .2)
          and _near(control.get('volume_mm3'), 7920, .2))
    if ok:
        _ADVANCED_STATE['w2f_' + case + '_before'] = {
            'target': target, 'control': control, 'timeline_count': rec['timeline_count']}
    return _measured('owned asymmetric/mixed fillet fixture ' + case, rec, ok)


def _w2_fillet_created(payload, case, kind):
    name = payload.get('feature')
    rows = payload.get('edge_sets') or []
    expected_sets = 2 if kind == 'mixed' else 1
    expected_type = ('edge_sets' if kind == 'mixed' else 'asymmetric' if kind == 'asymmetric'
                     else 'constant' if kind.startswith('constant') else 'variable')
    ok = (payload.get('filleted') is True and isinstance(name, str) and bool(name)
          and payload.get('fillet_type') == expected_type
          and len(rows) == expected_sets
          and all(row.get('edges_count') == 1 and row.get('edges_match') is True for row in rows))
    if ok:
        _ADVANCED_STATE['w2f_' + case] = {'feature': name, 'kind': kind}
    return _measured('public asymmetric/mixed fillet creation ' + case, payload, ok)


def _w2_fillet_census(payload, case, stage, kind, flipped=None):
    rec = _script_record(payload, 'W2F-CENSUS:')
    target, control = rec.get('target') or {}, rec.get('control') or {}
    baseline_key = 'w2f_' + case + '_before'
    if stage == 'before':
        ok = (rec.get('case') == case and rec.get('feature_name') is None
              and rec.get('target_identity') is True and rec.get('control_identity') is True
              and rec.get('edge_a_identity') is True and rec.get('edge_b_identity') is True
              and rec.get('timeline_count') == rec.get('marker_position') == rec.get('marker_before')
              and target.get('bounds_mm') == [[0, 0, 0], [22, 20, 18]]
              and control.get('bounds_mm') == [[30, 0, 0], [52, 20, 18]]
              and _near(target.get('volume_mm3'), 7920, .2)
              and _near(control.get('volume_mm3'), 7920, .2))
        if ok:
            _ADVANCED_STATE[baseline_key] = {'target': target, 'control': control,
                                              'timeline_count': rec['timeline_count']}
    elif stage == 'after_refusal':
        before = _ADVANCED_STATE.get(baseline_key) or {}
        ok = (rec.get('case') == case and rec.get('feature_name') is None
              and rec.get('timeline_count') == rec.get('marker_position') == before.get('timeline_count')
              and rec.get('marker_before') == before.get('timeline_count')
              and rec.get('target_identity') is True and rec.get('control_identity') is True
              and rec.get('edge_a_identity') is True and rec.get('edge_b_identity') is True
              and _snapshot_equal(target, before.get('target'))
              and _snapshot_equal(control, before.get('control')))
    else:
        before = _ADVANCED_STATE.get(baseline_key) or {}
        feature_sets = rec.get('feature_sets') or []
        ok = (rec.get('case') == case and rec.get('feature_name')
              and rec.get('feature_token_resolves') is True
              and rec.get('timeline_count') == rec.get('marker_position')
              and rec.get('marker_before') == before.get('timeline_count')
              and rec.get('target_identity') is True and rec.get('control_identity') is True
              and len(feature_sets) == (2 if kind == 'mixed' else 1)
              and not rec.get('feature_read_errors')
              and all(h.get('healthy') is True for h in rec.get('health') or [])
              and not _snapshot_equal(target, before.get('target'))
              and _snapshot_equal(control, before.get('control'))
              and target.get('bounds_mm') == [[0, 0, 0], [22, 20, 18]])
        if kind == 'asymmetric':
            rows = feature_sets
            ok = (ok and rows[0].get('kind') == 'asymmetric'
                  and rows[0].get('contains_edge_a') is True
                  and _near(rows[0].get('offset_one_mm'), 1, .001)
                  and _near(rows[0].get('offset_two_mm'), 2, .001)
                  and rows[0].get('flipped') is flipped and rows[0].get('edge_count') == 1)
            near_x = sorted({round(p[0], 3) for p in target.get('vertices_mm') or []
                             if abs(p[1]) <= .001 and 0 < p[0] <= 3})
            near_y = sorted({round(p[1], 3) for p in target.get('vertices_mm') or []
                             if abs(p[0]) <= .001 and 0 < p[1] <= 3})
            ok = ok and 2 in near_x and 1 in near_y if flipped is False else ok and 1 in near_x and 2 in near_y
            old_pair = _ADVANCED_STATE.get('w2f_asym_false_setbacks')
            if flipped is False and ok:
                _ADVANCED_STATE['w2f_asym_false_setbacks'] = (near_x, near_y)
            elif flipped is True:
                ok = ok and old_pair is not None and near_x == old_pair[1] and near_y == old_pair[0]
        elif kind == 'mixed':
            asym = next((r for r in feature_sets if r.get('kind') == 'asymmetric'), {})
            const = next((r for r in feature_sets if r.get('kind') == 'constant'), {})
            ok = (ok and asym.get('edge_count') == const.get('edge_count') == 1
                  and asym.get('contains_edge_a') is True and const.get('contains_edge_b') is True
                  and _near(asym.get('offset_one_mm'), 1, .001)
                  and _near(asym.get('offset_two_mm'), 2, .001)
                  and _near(const.get('radius_mm'), 1.5, .001)
                  and asym.get('flipped') is False)
            vertices = target.get('vertices_mm') or []
            asym_x = sorted({round(p[0], 3) for p in vertices if abs(p[1]) <= .001 and 0 < p[0] <= 3})
            asym_y = sorted({round(p[1], 3) for p in vertices if abs(p[0]) <= .001 and 0 < p[1] <= 3})
            const_x = sorted({round(p[0], 3) for p in vertices if abs(p[1]-20) <= .001 and 19 < p[0] < 22})
            const_y = sorted({round(p[1], 3) for p in vertices if abs(p[0]-22) <= .001 and 17 < p[1] < 20})
            ok = (ok and 2 in asym_x and 1 in asym_y and 20.5 in const_x and 18.5 in const_y)
        elif kind.startswith('constant'):
            ok = (ok and feature_sets[0].get('kind') == 'constant'
                  and feature_sets[0].get('contains_edge_a') is True
                  and _near(feature_sets[0].get('radius_mm'), 1, .001)
                  and feature_sets[0].get('edge_count') == 1)
        elif kind.startswith('variable'):
            ok = (ok and feature_sets[0].get('kind') == 'variable'
                  and feature_sets[0].get('contains_edge_a') is True
                  and _near(feature_sets[0].get('start_radius_mm'), 1, .001)
                  and _near(feature_sets[0].get('end_radius_mm'), 2, .001)
                  and feature_sets[0].get('edge_count') == 1)
    return _measured('independent asymmetric/mixed fillet geometry ' + case + ' ' + stage, rec, bool(ok))


def _w2_fillet_seam_found(payload, case, side, point):
    rows = payload.get('matches') or []
    match = rows[0] if len(rows) == 1 else {}
    position = match.get('position')
    ok = (payload.get('returned') == 1 and match.get('kind') == 'line_edge'
          and match.get('handle') and isinstance(position, list) and len(position) == 3
          and all(_finite_num(v) for v in position)
          and all(_near(position[i], point[i], .15) for i in range(3)))
    return _measured('typed W2 fillet seam edge ' + case + ' ' + side, match, ok)


def _w2_g2_continuity(payload, family, mode):
    rows = payload.get('edges') or []
    values = [(row.get('max_normal_angle_deg'), row.get('max_curvature_jump')) for row in rows]
    finite = (len(rows) == 2 and [row.get('edge') for row in rows] == [0, 1]
              and all(_finite_num(a) and _finite_num(b) and b >= 0
                                     and _finite_num(row.get('max_gap'))
                                     for row, (a, b) in zip(rows, values)))
    normal_ok = finite and all(a <= .05 for a, _ in values)
    valid = (payload.get('units') == 'mm' and normal_ok
             and all(row.get('max_gap') <= .001 for row in rows)
             and all(row.get('samples') == 9 and row.get('mode') == 'one_body'
                     and row.get('off_face_samples') == 0 for row in rows))
    if valid:
        _ADVANCED_STATE['w2g2_' + family + '_' + mode] = values
    if mode == 'curvature' and valid:
        tangent = _ADVANCED_STATE.get('w2g2_' + family + '_tangent')
        valid = tangent is not None and all(after[1] < before[1]
                                            for before, after in zip(tangent, values))
    return _measured('typed two-seam ' + family + ' ' + mode + ' continuity', {
        'edges': rows, 'tangent_reference': _ADVANCED_STATE.get('w2g2_' + family + '_tangent'),
        'normal_angle_tolerance_deg': .05, 'curvature_jump_decreased_on_both_seams':
            (None if mode == 'tangent' else valid)}, valid)


def _w2_fillet_rows():
    """Demonstrate asymmetric, mixed, refusal, and sampled continuity fillet routes."""
    rows = []
    cases = [
        ('asym_false', 'asymmetric', {'fillet_type': 'asymmetric', 'radius': 1,
         'end_radius': 2, 'flipped': False, 'tangent_chain': False}, False),
        ('asym_true', 'asymmetric', {'fillet_type': 'asymmetric', 'radius': 1,
         'end_radius': 2, 'flipped': True, 'tangent_chain': False}, True),
        ('mixed', 'mixed', {'tangent_chain': False}, None),
        ('asym_tangent_refuse', 'refusal', {'fillet_type': 'asymmetric', 'radius': 1,
         'end_radius': 2, 'continuity': 'tangent', 'tangent_chain': False}, None),
        ('asym_curvature_refuse', 'refusal', {'fillet_type': 'asymmetric', 'radius': 1,
         'end_radius': 2, 'continuity': 'curvature', 'tangent_chain': False}, None),
        ('constant_tangent', 'constant_tangent', {'fillet_type': 'constant', 'radius': 1,
         'continuity': 'tangent', 'tangent_chain': False}, None),
        ('constant_curvature', 'constant_curvature', {'fillet_type': 'constant', 'radius': 1,
         'continuity': 'curvature', 'tangent_chain': False}, None),
        ('variable_tangent', 'variable_tangent', {'fillet_type': 'variable', 'radius': 1,
         'end_radius': 2, 'positions': [.5], 'radii': [1.5], 'continuity': 'tangent',
         'tangent_chain': False}, None),
        ('variable_curvature', 'variable_curvature', {'fillet_type': 'variable', 'radius': 1,
         'end_radius': 2, 'positions': [.5], 'radii': [1.5], 'continuity': 'curvature',
         'tangent_chain': False}, None),
    ]
    for case, kind, spec, flipped in cases:
        tag = 'w2f_' + case
        rows.extend([
            ('doc_new', lambda c: {'expect_document': _ctx_get(c, 'advanced_home', 'home')},
             _new_document, (tag + '_doc', lambda p: p['document_handle'])),
            ('sys_execute_script', lambda c, case=case: _w2_fillet_fixture_arguments(c, case),
             lambda p, case=case: isinstance(p, str) and p.startswith('W2F-FIXTURE:')
                 and _w2_fillet_fixture_result(p, case), None),
            ('find_geometry', {'target': 'W2FilletTarget', 'kind': 'line_edge',
             'nearest_to': [0, 0, 9], 'units': 'mm', 'max_results': 1},
             lambda p, case=case: p.get('returned') == 1 and
                 _w2_patch_edge_found(p, 'fillet edge A ' + case, [0, 0, 9]),
             _fg(tag + '_edge_a')),
        ])
        if case == 'mixed':
            rows.append(('find_geometry', {'target': 'W2FilletTarget', 'kind': 'line_edge',
                'nearest_to': [22, 20, 9], 'units': 'mm', 'max_results': 1},
                lambda p, case=case: p.get('returned') == 1 and
                    _w2_patch_edge_found(p, 'fillet edge B ' + case, [22, 20, 9]),
                _fg(tag + '_edge_b')))
        rows.append(('sys_execute_script',
            lambda c, case=case: _w2_fillet_census_arguments(c, case),
            lambda p, case=case, kind=kind: isinstance(p, str)
                and p.startswith('W2F-CENSUS:')
                and _w2_fillet_census(p, case, 'before', kind), None))
        def mutation_args(ctx, tag=tag, case=case, kind=kind, spec=spec):
            edge_a = _ctx_get(ctx, tag + '_edge_a', 'W2 asymmetric edge')
            if kind == 'mixed':
                edge_b = _ctx_get(ctx, tag + '_edge_b', 'W2 disjoint edge')
                body = {'edge_sets': [
                    {'edges': [edge_a], 'fillet_type': 'asymmetric', 'radius': 1,
                     'end_radius': 2, 'flipped': False, 'tangent_chain': False},
                    {'edges': [edge_b], 'fillet_type': 'constant', 'radius': 1.5,
                     'tangent_chain': False}], 'units': 'mm'}
            else:
                body = {'edges': [edge_a], 'units': 'mm', **spec}
            return _combine_pin(ctx, tag + '_doc', body)
        if kind == 'refusal':
            check = _refused('asymmetric', "'continuity'", 'omit continuity')
        else:
            check = lambda p, case=case, kind=kind: (p.get('filleted') is True and
                _w2_fillet_created(p, case, kind))
        rows.append(('model_fillet', mutation_args, check, None))
        # Successful feature names are captured by the public response assertion for the census.
        def census_args(ctx, tag=tag, case=case, kind=kind):
            state = _ADVANCED_STATE.get('w2f_' + case) or {}
            return _w2_fillet_census_arguments(ctx, case, state.get('feature'))
        rows.append(('sys_execute_script', census_args,
            lambda p, case=case, kind=kind, flipped=flipped: isinstance(p, str)
                and p.startswith('W2F-CENSUS:') and
                _w2_fillet_census(p, case, 'after_refusal' if kind == 'refusal' else 'result',
                                  kind, flipped), None))
        if kind in ('constant_tangent', 'constant_curvature', 'variable_tangent',
                    'variable_curvature'):
            family = 'constant' if kind.startswith('constant') else 'variable'
            mode = 'curvature' if kind.endswith('curvature') else 'tangent'
            edge_points = ([1, 0, 9], [0, 1, 9]) if family == 'constant' else (
                [1.5, 0, 9], [0, 1.5, 9])
            for side, point in zip(('x', 'y'), edge_points):
                rows.append(('find_geometry', {'target': 'W2FilletTarget', 'kind': 'line_edge',
                    'nearest_to': point, 'units': 'mm', 'max_results': 1},
                    lambda p, case=case, side=side, point=point:
                        p.get('returned') == 1 and _w2_fillet_seam_found(p, case, side, point),
                    _fg(tag + '_seam_' + side)))
            rows.append(('model_measure_continuity', lambda c, tag=tag: {
                'edges': [_ctx_get(c, tag + '_seam_x', 'first fillet seam'),
                          _ctx_get(c, tag + '_seam_y', 'second fillet seam')],
                'samples': 9, 'units': 'mm'},
                lambda p, family=family, mode=mode: bool(p.get('edges')) and
                    _w2_g2_continuity(p, family, mode), None))
        rows.extend([
            ('doc_activate', lambda c, tag=tag: {'name': _ctx_get(c, 'advanced_home', 'home'),
             'expect_document': _ctx_get(c, tag + '_doc', 'W2 fillet scratch')}, 'ok', None),
            ('doc_close', lambda c, tag=tag: {'name': _ctx_get(c, tag + '_doc', 'W2 fillet scratch'),
             'save_changes': False, 'expect_document': _ctx_get(c, 'advanced_home', 'home')},
             _document_closed, None)])
    return rows


def _finite_num(value):
    """Return whether a measured value is a finite real number."""
    if not _num(value):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def advanced_feature_edit_rows():
    """Return the bounded five-family public edit and independent restoration witness rows."""
    _ADVANCED_STATE.clear()
    return scope_unit(_advanced_edit_rows(), ["native_script", "cloud_tier", "library_writes",
                                            "preference_writes", "addin_reload"])
