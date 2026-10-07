# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Live public witnesses for the measured advanced feature edit rows."""

import json
import math

from verify_core import (
    _ctx_get, _document_closed, _home_address, _home_document, _measured, _new_document, _num)
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
    return rows


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
    return _advanced_edit_rows()
