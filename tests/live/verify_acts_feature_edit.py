# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Live stories for measured model_edit_feature fields."""

from verify_core import (
    Independent,
    _RECALL, _ctx_get, _document_closed, _extruded, _home_address, _home_document,
    _made_component, _matched, _measured, _near, _new_document, _recall, _refused, _revolved, _drafted, _fg)


def _save_feature(key):
    """Save a created feature's exact public name."""
    return _recall(key, lambda p: p["feature"])


def _save_body(key):
    """Save a created solid's public body address."""
    def save(p):
        body = p["result_bodies"][0]
        _RECALL[key] = body
        return body
    return _recall(key, save)


def _save_document(p):
    """Save the exact document handle returned by doc_new."""
    handle = p.get("document_handle")
    if not isinstance(handle, str) or not handle:
        raise ValueError("doc_new returned no exact document handle")
    return handle


def _scratch_active(key):
    """Require the owned unsaved scratch to remain active."""
    def check(p):
        active = p.get("active") or {}
        return _measured("feature-edit owned scratch remains active", {
            "active": active.get("document_handle"), "owned": _RECALL.get(key)},
            active.get("document_handle") == _RECALL.get(key)
            and p.get("open_count", 0) >= 2)
    return check


def _home_active(p):
    """Require the original story document active before closing the owned scratch."""
    active = p.get("active") or {}
    return _measured("original story document active before scratch close", {
        "active": active.get("document_handle"), "home": _RECALL.get("fe_home")},
        active.get("document_handle") == _RECALL.get("fe_home"))


def _component_created(key):
    """Save and validate the fixture component's exact occurrence address."""
    def check(p):
        ok = _made_component(p)
        if ok:
            _RECALL[key] = p.get("full_path")
            _RECALL[key + "_name"] = p.get("component")
        return ok
    return check


def _definition_before(key, action, feature_type, preserved, component_key):
    """Require the public rolled definition and the requested typed edit offer."""
    def check(p):
        d = p.get("definition") or {}
        offers = d.get("supported_edits") or []
        offer = next((r for r in offers if r.get("action") == action), {})
        required = [field for field in preserved]
        valid = (d.get("type") == feature_type
                 and d.get("component") == _RECALL.get(component_key + "_name")
                 and isinstance(_RECALL.get(component_key), str) and bool(_RECALL[component_key])
                 and isinstance(d.get("feature_address"), str) and bool(d["feature_address"])
                 and d.get("unavailable") == {} and isinstance(d.get("timeline_index"), int)
                 and isinstance(offer.get("call"), str) and "model_edit_feature(" in offer["call"]
                 and all(field in d and d[field] is not None for field in required))
        if action in ("axis", "plane"):
            role = preserved[0]
            valid = valid and isinstance(d.get(role), dict) and bool(d[role].get("handle"))
        elif action == "inputs":
            items = d.get("input_faces")
            valid = valid and isinstance(items, list) and bool(items) and all(
                isinstance(item.get("handle"), str) and item.get("handle") for item in items)
        elif action == "mode":
            field = {"DraftFeature": "is_direction_flipped", "ThreadFeature": "is_modeled",
                     "CombineFeature": "operation"}.get(feature_type)
            valid = valid and field in d and d.get(field) is not None
            if feature_type == "ThreadFeature":
                valid = valid and d.get("modeled") is d.get("is_modeled")
        if feature_type == "RectangularPatternFeature":
            valid = (valid and d.get("quantity_two") == "2"
                     and d.get("distance_two") not in (None, "0", "0.00 mm")
                     and d.get("elements") == 6
                     and isinstance(d.get("direction_one_vector"), list)
                     and isinstance(d.get("direction_two_vector"), list))
        if valid:
            _RECALL[key] = d
        return _measured("public definition at feature marker has usable typed offer and retained controls",
                         {"feature": d.get("feature"), "component": d.get("component"),
                          "type": d.get("type"), "timeline_index": d.get("timeline_index"),
                          "field": d.get(preserved[0]),
                          "supported_edit": offer, "unavailable": d.get("unavailable")}, valid)
    return check


def _clean(value):
    """Remove unstable native handles while retaining owner and measured geometry."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()
                if k not in ("handle", "entity_token", "token", "profile_handle")}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _vector_near(left, right, tolerance=1e-5):
    """Compare finite three-dimensional vectors with a small unit tolerance."""
    return (isinstance(left, (list, tuple)) and isinstance(right, (list, tuple))
            and len(left) == len(right) == 3
            and all(isinstance(a, (int, float)) and not isinstance(a, bool)
                    and isinstance(b, (int, float)) and not isinstance(b, bool)
                    and abs(a - b) <= tolerance for a, b in zip(left, right)))


def _operand_matches_candidate(value, candidate, component_name, component_path, native_face=False):
    """Require the returned operand to identify the banked candidate and its measured frame."""
    if not isinstance(value, dict) or not isinstance(candidate, dict):
        return False
    owner, geometry = value.get("owner") or {}, value.get("geometry") or {}
    kind = candidate.get("kind")
    expected_kind = "face" if kind == "planar_face" else kind
    if (value.get("kind") != expected_kind
            or (candidate.get("name") is not None and value.get("name") != candidate.get("name"))
            or not isinstance(value.get("name"), str) or not value.get("name")):
        return False
    if kind == "body":
        center = geometry.get("center_cm")
        return (owner.get("component") == component_name
                and owner.get("occurrence") == component_path
                and candidate.get("component_path") == component_path
                and geometry.get("frame") == "entity_context"
                and _vector_near(center, [v * 0.1 for v in candidate.get("center", [])])
                and isinstance(geometry.get("volume"), (int, float))
                and abs(abs(geometry["volume"]) - candidate.get("volume", float("inf")) / 1000.0) <= 1e-5)
    same_handle = value.get("handle") == candidate.get("handle")
    if kind == "planar_face":
        left, _sep, _locator = str(value.get("handle", "")).partition("|@")
        right, _sep, _locator = str(candidate.get("handle", "")).partition("|@")
        same_handle = (bool(left and right) if native_face and owner.get("occurrence") is None
                       else bool(left) and left == right)
    placement_matches = (owner.get("occurrence") == candidate.get("occurrence")
                         and owner.get("occurrence") == component_path)
    if native_face and kind == "planar_face" and owner.get("occurrence") is None:
        placement_matches = candidate.get("occurrence") == component_path
    if (not same_handle
            or owner.get("component") != component_name
            or not placement_matches):
        return False
    pos = candidate.get("position")
    if not isinstance(pos, list) or len(pos) != 3:
        return False
    origin = geometry.get("origin_cm")
    if kind == "construction_axis":
        return (geometry.get("frame") == "world" and _vector_near(origin, [v * 0.1 for v in pos])
                and _vector_near(geometry.get("direction"), candidate.get("direction")))
    if kind == "construction_plane":
        return (geometry.get("frame") == "world" and _vector_near(origin, [v * 0.1 for v in pos])
                and _vector_near(geometry.get("normal"), candidate.get("normal")))
    if kind == "planar_face":
        return (geometry.get("frame") == "entity_context"
                and _vector_near(geometry.get("point_cm"), [v * 0.1 for v in pos])
                and _vector_near(geometry.get("normal"), candidate.get("normal")))
    return False


def _definition_after(key, changed_field, wanted_mode=None, candidate_key=None, native_identity=False):
    """Check the requested field changed and identity and retained controls stayed fixed."""
    def check(p):
        before = _RECALL.get(key)
        after = p.get("definition") or {}
        if not isinstance(before, dict) or not before:
            return _measured("public definition has a banked baseline", before, False)
        identity = ("feature", "component", "type", "timeline_index", "feature_address")
        stable = all(after.get(k) == before.get(k) for k in identity)
        controls = [k for k in before if k not in (changed_field, "supported_edits", "unavailable", "not_read", "note")]
        if changed_field == "is_modeled":
            controls = [k for k in controls if k != "modeled"]
        if after.get("type") == "RectangularPatternFeature":
            controls = [k for k in controls if k not in ("direction_one_vector",
                                                        "direction_two_vector")]
        controls_ok = all(_clean(after.get(k)) == _clean(before.get(k)) for k in controls)
        old, new = before.get(changed_field), after.get(changed_field)
        if wanted_mode is not None:
            field_ok = new == wanted_mode and new != old
        else:
            field_ok = _clean(new) != _clean(old) and isinstance(new, (dict, list))
        if changed_field == "is_modeled":
            field_ok = (field_ok and isinstance(new, bool) and after.get("modeled") is new
                        and before.get("modeled") is before.get("is_modeled"))
        if candidate_key:
            candidate = _RECALL.get(candidate_key + "_descriptor")
            feature_case = key.split("_", 1)[0]
            field_value = new[0] if isinstance(new, list) and len(new) == 1 else new
            field_ok = (field_ok and _operand_matches_candidate(
                field_value, candidate, _RECALL.get(feature_case + "_component_name"),
                _RECALL.get(feature_case + "_component"),
                native_face=native_identity and after.get("type") == "DraftFeature"))
        if after.get("type") == "RectangularPatternFeature":
            vector = changed_field + "_vector"
            field_ok = field_ok and not _vector_near(before.get(vector), after.get(vector))
            other = ("direction_two_vector" if changed_field == "direction_one"
                     else "direction_one_vector")
            if before.get("direction_two") is not None:
                field_ok = field_ok and _vector_near(before.get(other), after.get(other))
            if before.get("direction_two") is None:
                field_ok = (field_ok and after.get("direction_two") is None
                            and not _vector_near(before.get("direction_two_vector"),
                                                 after.get("direction_two_vector")))
        good = (after.get("unavailable") == {} and stable and controls_ok and field_ok)
        return _measured("public definition changed only the requested field", {
            "before": {k: before.get(k) for k in (changed_field, "feature", "component", "type", "timeline_index")},
            "after": {k: after.get(k) for k in (changed_field, "feature", "component", "type", "timeline_index")},
            "retained_controls_equal": controls_ok, "same_feature_address": stable,
            "unavailable": after.get("unavailable")}, good)
    return check


def _definition_restored(key, field):
    """Compare restored public definition with its independent baseline, ignoring handles."""
    def check(p):
        before, after = _RECALL.get(key), p.get("definition") or {}
        if not isinstance(before, dict) or not before or not isinstance(after, dict) or not after:
            return _measured("public feature definition has a banked nonempty baseline", {
                "before": before, "after": after}, False)
        keys = [k for k in before if k not in ("supported_edits", "unavailable", "not_read", "note")]
        same = (after.get("unavailable") == {} and all(
            _clean(after.get(k)) == _clean(before.get(k)) for k in keys))
        return _measured("public feature definition restored at rolled marker", {
            "field": field, "before": _clean(before.get(field)), "after": _clean(after.get(field)),
            "feature": after.get("feature"), "component": after.get("component"),
            "type": after.get("type"), "timeline_index": after.get("timeline_index")}, same)
    return check


def _shape_state(p):
    """Return the independent component body census, envelope, and mass when complete."""
    mass = p.get("mass") or {}
    bodies = mass.get("per_body") or []
    bounds = (p.get("min_point") or {}, p.get("max_point") or {})
    center = mass.get("center_of_mass")
    values = [mass.get("volume")] + [point.get(axis) for point in bounds for axis in "xyz"]
    rows = sorted((r.get("body"), r.get("is_solid"), r.get("lump_count"), r.get("volume"))
                  for r in bodies)
    if (p.get("units") != "mm" or mass.get("accuracy_used") != "very_high"
            or mass.get("per_body_truncated") is not False
            or mass.get("per_body_count") != len(bodies) or not bodies
            or any(not _near(v, 0, float("inf")) for v in values)
            or not isinstance(center, list) or len(center) != 3
            or any(not isinstance(v, (int, float)) or isinstance(v, bool)
                   or not _near(v, 0, float("inf")) for v in center)
            or any(r[1] is not True or not isinstance(r[2], int) or r[2] < 1
                   or not isinstance(r[3], (int, float)) for r in rows)):
        return None
    return {"volume": values[0], "min": values[1:4], "max": values[4:7],
            "center": center, "bodies": rows}


def _shape_capture(key, label):
    """Capture a complete independent component geometry census."""
    def check(p):
        state = _shape_state(p)
        if state is not None:
            _RECALL[key] = state
        return _measured(label + " independent body census", state or p, state is not None)
    return check


def _body_rows_same(before, after):
    """Compare the complete public body census with tolerance for measured volume noise."""
    return (len(before) == len(after) and all(
        a[:3] == b[:3] and _near(a[3], b[3], 1e-5) for a, b in zip(before, after)))


def _shape_changed(key, label, expected=None):
    """Require an independent component envelope or volume change with all body rows readable."""
    def check(p):
        before, after = _RECALL.get(key), _shape_state(p)
        changed = (before is not None and after is not None and
                   (not _near(before["volume"], after["volume"], 1e-5)
                    or not _vector_near(before["center"], after["center"], 1e-4)
                    or any(not _near(x, y, 1e-4) for x, y in zip(before["min"] + before["max"],
                                                                  after["min"] + after["max"]))))
        if expected is not None:
            wanted_bounds = expected.get("bounds")
            changed = (changed and isinstance(wanted_bounds, list) and len(wanted_bounds) == 6
                       and _near(after["volume"], expected.get("volume"), 1e-5)
                       and _vector_near(after["center"], expected.get("center"), 1e-4)
                       and all(_near(x, y, 1e-4) for x, y in zip(after["min"] + after["max"],
                                                                  wanted_bounds)))
        premise = " new native premise" if expected is not None else ""
        return _measured(premise + label + " independent geometry changed", after or p, changed)
    return check


def _shape_restored(key, label):
    """Require independent component geometry to return to its measured baseline."""
    def check(p):
        before, after = _RECALL.get(key), _shape_state(p)
        same = (before is not None and after is not None
                and _near(before["volume"], after["volume"], 1e-5)
                and _vector_near(before["center"], after["center"], 1e-4)
                and all(_near(x, y, 1e-4) for x, y in zip(before["min"] + before["max"],
                                                           after["min"] + after["max"]))
                and _body_rows_same(before["bodies"], after["bodies"]))
        return _measured(label + " independent geometry restored", after or p, same)
    return check


def _body_geometry(p, name):
    """Return the independent named body's volume, center and world bounds."""
    mass = p.get("mass") or {}
    minimum, maximum = p.get("min_point") or {}, p.get("max_point") or {}
    center = mass.get("center_of_mass")
    values = [mass.get("volume")] + [point.get(axis) for point in (minimum, maximum) for axis in "xyz"]
    if (p.get("kind") != "body" or p.get("units") != "mm"
            or p.get("target") != "body '" + name + "'"
            or mass.get("accuracy_used") != "very_high"
            or not isinstance(center, list) or len(center) != 3
            or any(not isinstance(v, (int, float)) or isinstance(v, bool)
                   or not _near(v, 0, float("inf")) for v in values + center)):
        return None
    return {"name": name, "volume": values[0], "min": values[1:4], "max": values[4:7],
            "center": center}


def _body_capture(key):
    """Capture a complete named body inspection."""
    def check(p):
        state = _body_geometry(p, _RECALL.get(key))
        if state is not None:
            _RECALL[key + "_state"] = state
        return _measured("named body geometry baseline", state or p, state is not None)
    return check


def _body_candidate_capture(key, component_key, shape_key):
    """Bank a body candidate only when it is unique in the exact inspected component."""
    def check(p):
        state = _body_geometry(p, _RECALL.get(key))
        component = _RECALL.get(component_key + "_name")
        path = _RECALL.get(component_key)
        census = _RECALL.get(shape_key) or {}
        rows = census.get("bodies") or []
        owner_count = sum(1 for row in rows if row[0] == _RECALL.get(key))
        valid = (state is not None and isinstance(component, str) and bool(component)
                 and isinstance(path, str) and bool(path) and owner_count == 1)
        if valid:
            _RECALL[key + "_descriptor"] = {"kind": "body", "name": state["name"],
                "component_path": path, "volume": state["volume"], "center": state["center"]}
        return _measured("body candidate has one exact owner and measured geometry", {
            "body": _RECALL.get(key), "owner_component": component, "owner_occurrence": path,
            "owner_count": owner_count, "geometry": state}, valid)
    return check


def _body_changed(key, label, expected):
    """Require the named target body to reach its expected independent geometry."""
    def check(p):
        before = _RECALL.get(key + "_state")
        after = _body_geometry(p, _RECALL.get(key))
        wanted = expected or {}
        wanted_bounds = wanted.get("bounds")
        good = (bool(before) and after is not None
                and not _vector_near(before["center"], after["center"], 1e-4)
                and isinstance(wanted_bounds, list) and len(wanted_bounds) == 6
                and _near(after["volume"], wanted.get("volume"), 1e-5)
                and _vector_near(after["center"], wanted.get("center"), 1e-4)
                and all(_near(a, b, 1e-4) for a, b in zip(after["min"] + after["max"],
                                                           wanted_bounds)))
        return _measured("new native premise " + label + " target body geometry", after or p, good)
    return check


def _body_restored(key, label):
    """Require the named body to return to its nonempty independent baseline."""
    def check(p):
        before = _RECALL.get(key + "_state")
        after = _body_geometry(p, _RECALL.get(key))
        same = (isinstance(before, dict) and bool(before) and after is not None
                and _near(before["volume"], after["volume"], 1e-5)
                and _vector_near(before["center"], after["center"], 1e-4)
                and all(_near(a, b, 1e-4) for a, b in zip(before["min"] + before["max"],
                                                           after["min"] + after["max"])))
        return _measured(label + " target body restored", after or p, same)
    return check


def _control_state(p):
    """Return a body-specific independent control signature."""
    mass = p.get("mass") or {}
    minimum, maximum = p.get("min_point") or {}, p.get("max_point") or {}
    values = [mass.get("volume")] + [point.get(axis) for point in (minimum, maximum) for axis in "xyz"]
    center = mass.get("center_of_mass")
    return values + center if (p.get("kind") == "body" and p.get("units") == "mm"
        and all(_near(v, 0, float("inf")) for v in values) and isinstance(center, list)
        and len(center) == 3 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                     and _near(v, 0, float("inf")) for v in center)) else None


def _control_capture(key):
    """Capture the independent body bounds and volume of the untouched control."""
    def check(p):
        state = _control_state(p)
        if state is not None:
            _RECALL[key] = state
        return _measured("control body bounds and volume baseline", state or p, state is not None)
    return check


def _control_same(key, stage):
    """Require the control body geometry unchanged at the named stage."""
    def check(p):
        before, after = _RECALL.get(key), _control_state(p)
        same = bool(before) and after is not None and all(
            _near(x, y, 1e-5) for x, y in zip(before, after))
        return _measured(stage + " independent control unchanged", after or p, same)
    return check


def _marker_end(p):
    """Require the independent timeline read at its exact end marker and healthy feature rows."""
    timeline = p.get("timeline") or {}
    rows = timeline.get("timeline")
    summary = timeline.get("summary") or {}
    states = summary.get("states") if isinstance(summary, dict) else None
    exceptions = summary.get("exceptions") if isinstance(summary, dict) else None
    return _measured("healthy timeline restored at end", timeline,
                     isinstance(rows, list) and timeline.get("returned") == timeline.get("count") == len(rows)
                     and timeline.get("marker_position") == timeline.get("count")
                     and timeline.get("truncated") is not True
                     and states == {"healthy": len(rows)} and exceptions == [])


def _roll_before(ctx, feature_key):
    """Roll to the feature input row before reacquiring a topology-sensitive source face."""
    return {"action": "roll", "feature": _ctx_get(ctx, feature_key, "feature"), "to": "before"}


def _roll_end():
    """Return the feature marker to the end before a public edit."""
    return {"action": "roll", "to": "end"}


def _roll_landed(to):
    """Require the requested timeline marker movement to have been read back."""
    def check(p):
        moved = (p.get("rolled") is True and p.get("to") == to
                 and isinstance(p.get("marker_position"), int))
        if to == "end":
            moved = moved and p.get("timeline_count") == p.get("marker_position")
        return _measured("timeline marker rolled " + to, p, moved)
    return check


def _draft_face_identity_args(ctx, candidate_key, definition_key):
    """Build a read-only native identity query from the two public face handles."""
    candidate = ctx.get(candidate_key)
    definition = ctx.get(definition_key) or {}
    faces = definition.get("input_faces") or []
    actual = faces[0].get("handle") if len(faces) == 1 and isinstance(faces[0], dict) else None
    if not isinstance(candidate, str) or not candidate or not isinstance(actual, str) or not actual:
        raise ValueError("Draft face handles are not both uniquely readable")
    left, _sep, _locator = candidate.partition("|@")
    right, _sep, _locator = actual.partition("|@")
    if not left or not right:
        raise ValueError("Draft face handles contain no resolvable entity token")
    script = (
        "import adsk.core, adsk.fusion, json\n"
        "def run(context):\n"
        "    design=adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)\n"
        "    left=list(design.findEntityByToken(" + repr(left) + "))\n"
        "    right=list(design.findEntityByToken(" + repr(right) + "))\n"
        "    result={'left_count':len(left),'right_count':len(right)}\n"
        "    if len(left)==1 and len(right)==1:\n"
        "        a=left[0].nativeObject or left[0]; b=right[0].nativeObject or right[0]\n"
        "        result.update(native_equal=a==b, body_equal=a.body==b.body,\n"
        "            owner_equal=a.body.parentComponent==b.body.parentComponent,\n"
        "            valid=[a.isValid,b.isValid])\n"
        "    print(json.dumps(result))\n")
    return {"script": script, "read_only": True}


def _draft_face_identity_check(p):
    """Require unique token resolution and native face, body, owner, and validity equality."""
    counts = (p.get("left_count"), p.get("right_count"))
    validity = p.get("valid")
    good = (counts == (1, 1) and p.get("native_equal") is True
            and p.get("body_equal") is True and p.get("owner_equal") is True
            and isinstance(validity, list) and validity == [True, True])
    return _measured("Draft candidate and public definition resolve to the same valid native face",
                     {"counts": counts, "native_equal": p.get("native_equal"),
                      "body_equal": p.get("body_equal"), "owner_equal": p.get("owner_equal"),
                      "valid": validity}, good)


def _transition(rows, case, feature_key, action, field, mode=None, candidate_key=None,
                expected_value=None, restore_mode=None, refresh_original=False,
                expected_shape=None, body_target_key=None, expected_body=None,
                candidate_body=False, draft_native_identity=False, role=None):
    """Run one public feature edit, independent effect read, and exact public restoration."""
    before_key = case + "_" + action + "_before"
    shape_key = case + "_" + action + "_shape"
    control_key = case + "_" + action + "_control"
    def edit_args(ctx, restore=False):
        d = _RECALL.get(before_key) or {}
        args = {"feature": d.get("feature_address", ""), "action": action}
        if mode is not None:
            args["mode"] = restore_mode if restore else mode
        else:
            if restore and refresh_original:
                args["references"] = [_ctx_get(ctx, case + "_restore_candidate", "fresh original face")]
            elif restore:
                current = d.get(field)
                descs = current if isinstance(current, list) else [current]
                args["references"] = [item.get("handle") for item in descs if isinstance(item, dict)]
            else:
                args["references"] = [_ctx_get(ctx, candidate_key, "typed edit candidate")]
            if role:
                args["references"] = [{role: handle} for handle in args["references"]]
        return args
    def edit_result(expect_change):
        def check(p):
            good = (p.get("edited") is True and p.get("definition_matches") is True
                    and p.get("same_feature") is True and p.get("owner_matches") is True
                    and p.get("marker_restored") is True and isinstance(p.get("feature_health"), dict)
                    and p.get("new_timeline_errors") == [] and p.get("new_timeline_warnings") == [])
            if expect_change:
                good = good and p.get("geometry_changed") is True
            return _measured(case + " " + action + (" edit" if expect_change else " restore")
                             + " verified by public setter", {
                "feature": p.get("feature"), "action": p.get("action"),
                "definition_matches": p.get("definition_matches"),
                "same_feature": p.get("same_feature"), "owner_matches": p.get("owner_matches"),
                "geometry_changed": p.get("geometry_changed"),
                "feature_health": p.get("feature_health"),
                "marker_restored": p.get("marker_restored"),
                "new_timeline_errors": p.get("new_timeline_errors"),
                "new_timeline_warnings": p.get("new_timeline_warnings")}, good)
        return check
    offset = len(rows)
    # The public feature-input definition is read with the marker before its feature row.
    rows += [("design_edit_timeline", lambda c: _roll_before(c, feature_key), _roll_landed("before"), None),
             ("design_get", lambda c: {"include": ["definition"], "units": "mm",
                 "feature": _ctx_get(c, feature_key, "feature")},
             _definition_before(before_key, action, case.split("_")[0], [field],
                                case + "_component"), None),
             ("design_edit_timeline", _roll_end(), _roll_landed("end"), None),
             ("model_inspect", lambda c: {"target": _ctx_get(c, case + "_component", "owned component"),
                 "include": ["default", "mass"], "units": "mm", "accuracy": "very_high", "per_body": True},
              _shape_capture(shape_key, case + " baseline"), None),
             ("model_inspect", lambda c: {"target": _ctx_get(c, case + "_control", "control body"),
                 "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
              _control_capture(control_key), None),
             ("doc_get", {}, _scratch_active(case + "_doc"), None),
             ("model_edit_feature", edit_args, edit_result(True), None),
             ("design_edit_timeline", lambda c: _roll_before(c, feature_key), _roll_landed("before"), None),
             ("design_get", lambda c: {"include": ["definition"], "units": "mm",
                 "feature": _ctx_get(c, feature_key, "feature")},
              _definition_after(before_key, field, expected_value, candidate_key,
                                native_identity=draft_native_identity),
              ((case + "_after_definition", lambda p: p.get("definition"))
               if draft_native_identity else None)),
             ("design_edit_timeline", _roll_end(), _roll_landed("end"), None),
             ("model_inspect", lambda c: {"target": _ctx_get(c, case + "_component", "owned component"),
                 "include": ["default", "mass"], "units": "mm", "accuracy": "very_high", "per_body": True},
              Independent(_shape_changed(shape_key, case + " changed", expected_shape),
                          ("model_edit_feature",), "tool:model_inspect"), None),
             ("model_inspect", lambda c: {"target": _ctx_get(c, case + "_control", "control body"),
                 "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
              _control_same(control_key, case + " changed"), None),
             ("doc_get", {}, _scratch_active(case + "_doc"), None)]
    if draft_native_identity:
        identity_index = offset + 9
        rows[identity_index:identity_index] = [("sys_execute_script",
            lambda c: _draft_face_identity_args(c, candidate_key, case + "_after_definition"),
            _draft_face_identity_check, None)]
    baseline_extra = 0
    if candidate_body:
        rows[offset + 5:offset + 5] = [("model_inspect", lambda c, candidate_key=candidate_key: {
            "target": _ctx_get(c, candidate_key, "typed body candidate"),
            "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
            _body_candidate_capture(candidate_key, case + "_component", shape_key), None)]
        baseline_extra += 1
    if body_target_key:
        body_index = offset + 5 + baseline_extra
        rows[body_index:body_index] = [("model_inspect", lambda c, body_target_key=body_target_key: {
            "target": _ctx_get(c, body_target_key, "target body"), "include": ["default", "mass"],
            "units": "mm", "accuracy": "very_high"}, _body_capture(body_target_key), None)]
        baseline_extra += 1
        changed_index = offset + 11 + baseline_extra
        rows[changed_index:changed_index] = [("model_inspect", lambda c, body_target_key=body_target_key: {
            "target": _ctx_get(c, body_target_key, "target body"), "include": ["default", "mass"],
            "units": "mm", "accuracy": "very_high"},
            _body_changed(body_target_key, case + " changed", expected_body), None)]
    if refresh_original:
        def original_face_args(ctx):
            d = _RECALL.get(before_key) or {}
            refs = d.get(field) or []
            geometry = refs[0].get("geometry") if refs and isinstance(refs[0], dict) else {}
            point_cm = geometry.get("point_cm") if isinstance(geometry, dict) else None
            if not isinstance(point_cm, list) or len(point_cm) != 3:
                raise ValueError("baseline face point is not readable; refusing stale-handle restore")
            return {"target": _ctx_get(ctx, case + "_component", "owned component"),
                    "kind": "planar_face", "nearest_to": [10.0 * v for v in point_cm],
                    "units": "mm", "max_results": 1}
        restore_key = case + "_restore_candidate"
        rows += [("design_edit_timeline", lambda c: _roll_before(c, feature_key), _roll_landed("before"), None),
                 ("find_geometry", original_face_args, _matched(1, "planar_face"), _fg(restore_key)),
                 ("design_edit_timeline", _roll_end(), _roll_landed("end"), None)]
    restore_start = len(rows)
    rows += [("doc_get", {}, _scratch_active(case + "_doc"), None),
             ("model_edit_feature", lambda c: edit_args(c, True), edit_result(False), None),
             ("design_edit_timeline", lambda c: _roll_before(c, feature_key), _roll_landed("before"), None),
             ("design_get", lambda c: {"include": ["definition"], "units": "mm",
                 "feature": _ctx_get(c, feature_key, "feature")},
              _definition_restored(before_key, field), None),
             ("design_edit_timeline", _roll_end(), _roll_landed("end"), None),
             ("model_inspect", lambda c: {"target": _ctx_get(c, case + "_component", "owned component"),
                 "include": ["default", "mass"], "units": "mm", "accuracy": "very_high", "per_body": True},
              _shape_restored(shape_key, case + " restored"), None),
             ("model_inspect", lambda c: {"target": _ctx_get(c, case + "_control", "control body"),
                 "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
              _control_same(control_key, case + " restored"), None),
             ("design_get", {"include": ["timeline"], "max_results": 2000}, _marker_end, None)]
    if body_target_key:
        rows.insert(restore_start + 6, ("model_inspect", lambda c, body_target_key=body_target_key: {
            "target": _ctx_get(c, body_target_key, "target body"), "include": ["default", "mass"],
            "units": "mm", "accuracy": "very_high"},
            _body_restored(body_target_key, case + " restored"), None))



def _grid_null_setup_args(ctx, case):
    """Prepare a measured null second entity on the exact owned scratch feature."""
    name = _ctx_get(ctx, case + "_feature", "owned pattern")
    component = _RECALL.get(case + "_component_name")
    script = (
        "import adsk.core, adsk.fusion, json\n"
        "def run(context):\n"
        "    app=adsk.core.Application.get(); doc=app.activeDocument\n"
        "    design=adsk.fusion.Design.cast(app.activeProduct)\n"
        "    root=design.rootComponent if design else None\n"
        "    if not doc or doc.isSaved or not root or root.occurrences.count != 1:\n"
        "        print(json.dumps({'refused':'not the owned unsaved one-component scratch'})); return\n"
        "    comp=root.occurrences.item(0).component\n"
        "    coll=comp.features.rectangularPatternFeatures\n"
        "    if comp.name != " + repr(component) + " or coll.count != 1 or coll.item(0).name != "
        + repr(name) + ":\n"
        "        print(json.dumps({'refused':'the exact owned pattern was not found'})); return\n"
        "    f=coll.item(0); timeline=design.timeline\n"
        "    if not f.timelineObject.rollTo(True):\n"
        "        print(json.dumps({'refused':'could not roll before the owned pattern'})); return\n"
        "    result={}\n"
        "    try:\n"
        "        result['before']={'one':f.directionOneEntity.entityToken,\n"
        "            'two':f.directionTwoEntity.entityToken if f.directionTwoEntity else None,\n"
        "            'vector_two':[f.directionTwo.x,f.directionTwo.y,f.directionTwo.z]}\n"
        "        f.directionTwoEntity=f.directionOneEntity\n"
        "        result['after']={'two':f.directionTwoEntity.entityToken if f.directionTwoEntity else None,\n"
        "            'vector_two':[f.directionTwo.x,f.directionTwo.y,f.directionTwo.z],\n"
        "            'quantity_two':f.quantityTwo.expression,\n"
        "            'distance_two':f.distanceTwo.expression,\n"
        "            'elements':f.patternElements.count}\n"
        "    except Exception as exc:\n"
        "        result['setup_error']=str(exc)\n"
        "    finally:\n"
        "        timeline.moveToEnd()\n"
        "    result['marker_end']=timeline.markerPosition==timeline.count\n"
        "    print(json.dumps(result))\n")
    return {"script": script, "read_only": False,
            "expect_document": _ctx_get(ctx, case + "_doc", "owned scratch")}


def _grid_null_setup_check(p):
    """Require the native preparation to leave six real, spaced pattern instances."""
    before, after = p.get("before") or {}, p.get("after") or {}
    good = (p.get("marker_end") is True and isinstance(before.get("one"), str)
            and isinstance(before.get("two"), str) and before["one"] != before["two"]
            and after.get("two") is None and after.get("quantity_two") == "2"
            and after.get("distance_two") not in (None, "0", "0.00 mm")
            and after.get("elements") == 6
            and not _vector_near(before.get("vector_two"), after.get("vector_two")))
    return _measured("owned 3 x 2 pattern has a moving implicit second vector", p, good)


def _grid_end_marker_read(p):
    """At the end marker the pattern's inputs do not read and the note says how to read them."""
    d = p.get("definition") or {}
    return _measured("pattern inputs unread at the end marker carry the roll remedy",
                     {"unavailable": d.get("unavailable"), "note": d.get("note")},
                     d.get("type") == "RectangularPatternFeature"
                     and "input_entities" in (d.get("unavailable") or {})
                     and "design_edit_timeline(action='roll'" in (d.get("note") or ""))


def _grid_refusal_rows(rows, case):
    """Show a colliding public edit refuses before changing definition or geometry."""
    key = case + "_axis_before"
    shape = case + "_axis_shape"
    rows.extend([
        ("design_edit_timeline", lambda c: _roll_before(c, case + "_feature"),
         _roll_landed("before"), None),
        ("design_get", lambda c: {"include": ["definition"], "units": "mm",
         "feature": _ctx_get(c, case + "_feature", "feature")},
         _definition_before(key, "axis", case, ["direction_one", "direction_two"],
                            case + "_component"), None),
        ("design_edit_timeline", _roll_end(), _roll_landed("end"), None),
        ("design_get", lambda c: {"include": ["definition"], "units": "mm",
         "feature": _ctx_get(c, case + "_feature", "feature")}, _grid_end_marker_read, None),
        ("model_inspect", lambda c: {"target": _ctx_get(c, case + "_component", "owned component"),
         "include": ["default", "mass"], "units": "mm", "accuracy": "very_high",
         "per_body": True}, _shape_capture(shape, case + " before refused collision"), None),
        ("model_edit_feature", lambda c: {"feature": _ctx_get(c, case + "_feature", "feature"),
         "action": "axis", "references": [{"direction_one":
             _RECALL[key]["direction_two"]["handle"]}]},
         _refused("direction_one and direction_two", "entityToken", "choose distinct entities"), None),
        ("design_edit_timeline", lambda c: _roll_before(c, case + "_feature"),
         _roll_landed("before"), None),
        ("design_get", lambda c: {"include": ["definition"], "units": "mm",
         "feature": _ctx_get(c, case + "_feature", "feature")},
         _definition_restored(key, "direction_one"), None),
        ("design_edit_timeline", _roll_end(), _roll_landed("end"), None),
        ("model_inspect", lambda c: {"target": _ctx_get(c, case + "_component", "owned component"),
         "include": ["default", "mass"], "units": "mm", "accuracy": "very_high",
         "per_body": True}, _shape_restored(shape, case + " after refused collision"), None),
    ])


def _start(rows, case):
    """Create one owned scratch document and its isolated fixture component."""
    rows.extend([
        ("doc_new", {}, _new_document, (case + "_doc", _recall(case + "_doc", _save_document))),
        ("doc_get", {}, _scratch_active(case + "_doc"), None),
        ("model_create_component", {"name": "FeatureEditBench", "activate": True},
         _component_created(case + "_component"),
         (case + "_component", _recall(case + "_component", lambda p: p["full_path"]))),
    ])


def _end(rows, case):
    """Restore the story document and close only the owned unsaved scratch."""
    rows.extend([
        ("doc_activate", lambda c: {"name": _ctx_get(c, "fe_home", "story document")}, "ok", None),
        ("doc_get", {}, _home_active, None),
        ("doc_close", lambda c: {"name": _ctx_get(c, case + "_doc", "owned scratch"),
                                  "save_changes": False}, _document_closed, None),
        ("doc_get", {}, _home_document, None),
    ])


def _box(rows, prefix, x1, y1, x2, y2, height, key):
    """Build a named rectangular solid and save its public body address."""
    sketch = prefix + "Sketch"
    rows.extend([
        ("sketch_create", {"plane": "xy", "name": sketch}, "ok", None),
        ("sketch_add_geometry", {"sketch_name": sketch, "units": "mm",
         "geometry": [{"kind": "rectangle", "x1": x1, "y1": y1, "x2": x2, "y2": y2}]}, "ok", None),
        ("model_extrude", {"sketch_name": sketch, "distance": height, "units": "mm"}, _extruded,
         (key, _save_body(key))),
    ])


def _candidate_saved(key, kind, expected=None):
    """Bank the exact public candidate record for later operand verification."""
    def check(p):
        matches = p.get("matches") or []
        candidate = matches[0] if len(matches) == 1 else None
        valid = (isinstance(candidate, dict) and candidate.get("kind") == kind
                 and isinstance(candidate.get("handle"), str) and bool(candidate["handle"])
                 and isinstance(candidate.get("position"), list)
                 and len(candidate["position"]) == 3
                 and isinstance(candidate.get("occurrence"), str)
                 and bool(candidate["occurrence"]))
        if valid and expected:
            wanted_position = expected.get("position", candidate["position"])
            valid = (isinstance(wanted_position, list) and len(wanted_position) == 3
                     and _vector_near(candidate["position"], wanted_position, 0.001))
            for field in ("direction", "normal"):
                if field in expected:
                    valid = valid and _vector_near(candidate.get(field), expected[field])
        if valid:
            _RECALL[key + "_descriptor"] = candidate
            _RECALL[key + "_descriptor"]["handle"] = p["matches"][0]["handle"]
        return _measured("candidate identity and geometry banked", candidate or p, valid)
    return check


def _candidate(rows, key, kind, name, expected=None):
    """Acquire a current typed candidate handle through the public geometry reader."""
    case = key.rpartition("_candidate")[0]
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, case + "_component", "owned component"),
                 "kind": kind, "name": name, "units": "mm", "max_results": 1},
                 _candidate_saved(key, kind, expected), _fg(key)))


def _cleanup_transition(rows, case):
    """Return to the home document and close the owned scratch after all public reads."""
    _end(rows, case)


def feature_edit_rows():
    """Return isolated public stories for the five measured core edit kinds and Combine mode."""
    rows = [("doc_get", {}, _home_document, ("fe_home", _recall("fe_home", _home_address)))]

    # Revolve axis: an off-origin rectangular profile makes a world-axis change alter the ring envelope.
    case = "RevolveFeature"
    _start(rows, case)
    _box(rows, "FEControl", 100, 0, 110, 10, 10, case + "_control")
    rows.extend([
        ("model_construction", {"kind": "axis", "mode": "two_planes", "plane": "xy",
         "plane2": "xz", "name": "FERevolveXAxis"}, "ok", None),
    ])
    _candidate(rows, case + "_candidate", "construction_axis", "FERevolveXAxis",
               {"position": [0, 0, 0], "direction": [-1, 0, 0]})
    rows.extend([
        ("sketch_create", {"plane": "xz", "name": "FERevolveProfile"}, "ok", None),
        ("sketch_add_geometry", {"sketch_name": "FERevolveProfile", "units": "mm",
         "geometry": [{"kind": "rectangle", "x1": 20, "y1": 0, "x2": 24, "y2": 10}]}, "ok", None),
        ("model_revolve", {"sketch_name": "FERevolveProfile", "axis": "z", "angle_deg": 360},
         _revolved, (case + "_feature", _save_feature(case + "_feature"))),
    ])
    _transition(rows, case, case + "_feature", "axis", "axis", candidate_key=case + "_candidate")
    _cleanup_transition(rows, case)

    # Mirror plane: the seed body is offset from both planes; a disjoint control remains fixed.
    case = "MirrorFeature"
    _start(rows, case)
    _box(rows, "FEMirrorSeed", 20, 0, 30, 10, 10, case + "_seed")
    _box(rows, "FEControl", 100, 0, 110, 10, 10, case + "_control")
    rows.append(("model_construction", {"kind": "plane", "mode": "offset", "plane": "yz",
        "offset": 5, "units": "mm", "name": "FEMirrorX5"}, "ok", None))
    _candidate(rows, case + "_candidate", "construction_plane", "FEMirrorX5",
               {"position": [5, 0, 0], "normal": [1, 0, 0]})
    rows.append(("model_mirror", lambda c, case=case: {"bodies": [_ctx_get(c, case + "_seed", "mirror seed")],
        "plane": "yz"}, lambda p: bool(p.get("feature")) and p.get("bodies_added", 0) > 0,
        (case + "_feature", _save_feature(case + "_feature"))))
    _transition(rows, case, case + "_feature", "plane", "mirror_plane", candidate_key=case + "_candidate")
    _cleanup_transition(rows, case)

    # CircularPattern axis: an off-axis seed distinguishes z and x pattern placements.
    case = "CircularPatternFeature"
    _start(rows, case)
    _box(rows, "FEPatternSeed", 20, 0, 24, 4, 4, case + "_seed")
    _box(rows, "FEControl", 100, 0, 110, 10, 10, case + "_control")
    rows.append(("model_construction", {"kind": "axis", "mode": "two_planes", "plane": "xy",
        "plane2": "xz", "name": "FEPatternXAxis"}, "ok", None))
    _candidate(rows, case + "_candidate", "construction_axis", "FEPatternXAxis",
               {"position": [0, 0, 0], "direction": [-1, 0, 0]})
    rows.append(("model_pattern_circular", lambda c, case=case: {"bodies": [_ctx_get(c, case + "_seed", "pattern seed")],
        "quantity": 3, "total_angle_deg": 270, "axis": "z"},
        lambda p: p.get("patterned") is True and p.get("quantity") == 3,
        (case + "_feature", _save_feature(case + "_feature"))))
    _transition(rows, case, case + "_feature", "axis", "axis", candidate_key=case + "_candidate")
    _cleanup_transition(rows, case)

    # A real 3 x 2 grid exercises both roles, refusal, and an implicit second vector.
    case = "RectangularPatternFeature"
    _start(rows, case)
    _box(rows, "FEGridSeed", 20, 0, 24, 4, 4, case + "_seed")
    _box(rows, "FEControl", 100, 0, 110, 10, 10, case + "_control")
    rows.append(("model_construction", {"kind": "axis", "mode": "two_planes", "plane": "xy",
        "plane2": "xz", "name": "FEGridXAxis"}, "ok", None))
    _candidate(rows, case + "_candidate", "construction_axis", "FEGridXAxis",
               {"position": [0, 0, 0], "direction": [-1, 0, 0]})
    rows.append(("model_pattern_rectangular", lambda c, case=case: {
        "bodies": [_ctx_get(c, case + "_seed", "pattern seed")], "quantity_one": 3,
        "spacing_one": 15, "direction_one": "y", "quantity_two": 2,
        "spacing_two": 20, "direction_two": "z"},
        lambda p: p.get("patterned") is True and p.get("total_instances") == 6
                  and p.get("quantity_two") == 2 and p.get("spacing_two") == 20,
        (case + "_feature", _save_feature(case + "_feature"))))
    _transition(rows, case, case + "_feature", "axis", "direction_one",
                candidate_key=case + "_candidate", role="direction_one")
    _transition(rows, case, case + "_feature", "axis", "direction_two",
                candidate_key=case + "_candidate", role="direction_two")
    _grid_refusal_rows(rows, case)
    rows.extend([
        ("doc_get", {}, _scratch_active(case + "_doc"), None),
        ("sys_execute_script", lambda c, case=case: _grid_null_setup_args(c, case),
         _grid_null_setup_check, None),
    ])
    _transition(rows, case, case + "_feature", "axis", "direction_one",
                candidate_key=case + "_candidate", role="direction_one")
    _cleanup_transition(rows, case)

    # Draft has separate input and mode stories; the opposite side is reacquired before feature creation.
    case = "DraftFeature"
    _start(rows, case)
    _box(rows, "FEDraftSeed", 0, 0, 30, 20, 10, case + "_seed")
    _box(rows, "FEControl", 100, 0, 110, 10, 10, case + "_control")
    rows.extend([
        ("find_geometry", lambda c, case=case: {"target": _ctx_get(c, case + "_component", "owned component"),
         "kind": "planar_face",
         "nearest_to": [30, 10, 5], "units": "mm", "max_results": 1},
         _candidate_saved(case + "_face_a", "planar_face",
                          {"position": [30, 10, 5], "normal": [1, 0, 0]}), _fg(case + "_face_a")),
        ("find_geometry", lambda c, case=case: {"target": _ctx_get(c, case + "_component", "owned component"),
         "kind": "planar_face", "nearest_to": [15, 20, 5], "units": "mm", "max_results": 1},
         _candidate_saved(case + "_face_b", "planar_face",
                          {"position": [15, 20, 5], "normal": [0, 1, 0]}), _fg(case + "_face_b")),
        ("model_draft", lambda c, case=case: {"faces": [_ctx_get(c, case + "_face_a", "draft face")],
         "pull_direction": "xy", "angle_deg": 3, "tangent_chain": False}, _drafted,
         (case + "_feature", _save_feature(case + "_feature"))),
    ])
    _transition(rows, case, case + "_feature", "inputs", "input_faces", candidate_key=case + "_face_b",
                refresh_original=True, draft_native_identity=True)
    # The input transition restores before the mode transition, so this second baseline is exact.
    _transition(rows, case, case + "_feature", "mode", "is_direction_flipped", mode="flipped",
                expected_value=True, restore_mode="normal", refresh_original=False)
    _cleanup_transition(rows, case)

    # Cosmetic Thread mode toggles to a real helix and back on an independently measured cylinder.
    case = "ThreadFeature"
    _start(rows, case)
    _box(rows, "FEControl", 100, 0, 110, 10, 10, case + "_control")
    sketch = "FEThreadCylinderSketch"
    rows.extend([
        ("sketch_create", {"plane": "xy", "name": sketch}, "ok", None),
        ("sketch_add_geometry", {"sketch_name": sketch, "units": "mm",
         "geometry": [{"kind": "circle", "cx": 20, "cy": 0, "radius": 4}]}, "ok", None),
        ("model_extrude", {"sketch_name": sketch, "distance": 20, "units": "mm"}, _extruded,
         (case + "_seed", _save_body(case + "_seed"))),
        ("find_geometry", lambda c, case=case: {"target": _ctx_get(c, case + "_component", "owned component"),
         "kind": "cylinder_face", "radius": 4, "units": "mm", "max_results": 1},
         _matched(1, "cylinder_face"), _fg(case + "_cylinder")),
        ("model_thread", lambda c, case=case: {"faces": [_ctx_get(c, case + "_cylinder", "thread cylinder")],
         "designation": "M8x1.25", "modeled": False},
         lambda p: p.get("modeled") is False and bool(p.get("feature")),
         (case + "_feature", _save_feature(case + "_feature"))),
    ])
    _transition(rows, case, case + "_feature", "mode", "is_modeled", mode="modeled",
                expected_value=True, restore_mode="cosmetic")
    _cleanup_transition(rows, case)

    # Combine retargets one disjoint, equal-volume tool and then intersects the original tool.
    case = "CombineFeature"
    _start(rows, case)
    _box(rows, "FECombineTarget", 0, 0, 40, 20, 10, case + "_target")
    _box(rows, "FECombineTool", 5, 5, 15, 15, 20, case + "_tool")
    _box(rows, "FECombineSecondTool", 20, 5, 30, 15, 20, case + "_tool2")
    _box(rows, "FEControl", 100, 0, 110, 10, 10, case + "_control")
    rows.append(("model_combine", lambda c, case=case: {"target": _ctx_get(c, case + "_target", "combine target"),
        "tools": [_ctx_get(c, case + "_tool", "combine tool")], "operation": "cut", "keep_tools": True},
        lambda p: p.get("combined") is True and p.get("operation") == "cut" and bool(p.get("feature")),
        (case + "_feature", _save_feature(case + "_feature"))))
    _transition(rows, case, case + "_feature", "tools", "tool_bodies",
                candidate_key=case + "_tool2", candidate_body=True,
                body_target_key=case + "_target",
                expected_shape={"volume": 12000, "center": [25.833333, 9.583333, 6.666667],
                                "bounds": [0, 0, 0, 110, 20, 20]},
                expected_body={"volume": 7000, "center": [19.285714, 10, 5],
                               "bounds": [0, 0, 0, 40, 20, 10]})
    _transition(rows, case, case + "_feature", "mode", "operation", mode="intersect",
                expected_value="intersect", restore_mode="cut",
                body_target_key=case + "_target",
                expected_shape={"volume": 6000, "center": [30.833333, 9.166667, 8.333333],
                                "bounds": [5, 0, 0, 110, 15, 20]},
                expected_body={"volume": 1000, "center": [10, 10, 5],
                               "bounds": [5, 5, 0, 15, 15, 10]})
    _cleanup_transition(rows, case)
    return [(tool, (lambda _context, args=args: dict(args)) if isinstance(args, dict) else args,
             check, save) for tool, args, check, save in rows]
