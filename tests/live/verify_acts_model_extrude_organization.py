# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Extrude editing and body organization checks for model acts."""

import math

from verify_core import (
    _RECALL, _activated, _ctx_get, _datum, _document_closed, _extruded, _fg, _home_address, _home_document, _made_component, _made_component_inactive, _matched, _measured, _moved, _near, _num, _new_document, _recall, _refused)





from verify_acts_model_combine_revolve import (
    _combine_body, _combine_inspect, _combine_pin)
from verify_acts_model_sweep import _retire_compare, _retire_material_state, _retire_body_state


def _extrude_definition(extent, distance, distance2=None, units="mm", side_count=None):
    """Check definition values without substituting unavailable participants or numeric extents."""
    def check(p):
        d = p.get("definition") or {}
        available = d.get("unavailable") or {}
        profile = d.get("profile") or {}
        numeric = extent not in ("through_all", "to_face")
        omitted = ["taper_angle", "thin", "start_extent", "is_solid"] + (
            ["extent_target"] if extent == "to_face" else [])
        return _measured(f"read {extent} Extrude definition in {units}", d,
            d.get("type") == "ExtrudeFeature" and d.get("extent") == extent and d.get("units") == units
            and d.get("not_read") == omitted and "extent" not in available
            and (d.get("note") or "").endswith(
                " This Extrude definition is partial: not_read lists fields it omits.")
            and bool(profile.get("profile_handle")) and profile.get("profile_index") == 0
            and bool(profile.get("source_sketch"))
            and d.get("distance_applicable") is numeric
            and (_near(d.get("distance"), distance, 1e-6) if numeric else d.get("distance") is None)
            and d.get("distance2_applicable") is (distance2 is not None)
            and (_near(d.get("distance2"), distance2, 1e-6) if distance2 is not None
                 else d.get("distance2") is None)
            and (bool(d.get("distance_parameter")) and bool(d.get("distance_expression")) if numeric
                 else d.get("distance_parameter") is None and d.get("distance_expression") is None)
            and (bool(d.get("distance2_parameter")) and bool(d.get("distance2_expression"))
                 if distance2 is not None else True)
            and d.get("extent_side_count") == side_count
            and d.get("direction") is None
            and (d.get("symmetric_full_length") is False if extent == "symmetric" else True)
            and d.get("participants") is None and bool(available.get("participants"))
            and "side" not in d)
    return check


def _definition_timeline_unchanged(p):
    """Check complete row order, health and marker against the independent pre-read snapshot."""
    before = _RECALL.get("definition_timeline") or {}
    now = p.get("timeline") or {}
    return _measured("definition read leaves timeline and health unchanged", now,
        bool(before) and not now.get("truncated") and now == before)

def _extrude_edit_landed(p):
    """Require the existing feature, requested definition and restored marker to survive an edit."""
    return _measured("existing Extrude edit", p,
                     p.get("edited") is True and p.get("same_feature") is True
                     and p.get("definition_matches") is True and p.get("geometry_changed") is True
                     and p.get("marker_restored") is True
                     and p.get("marker_before") == p.get("marker_after")
                     and p.get("other_components_unchanged") is True
                     and p.get("linked_scope_verified_at_edit") is True
                     and p.get("new_timeline_errors") == [])


def _extrude_edit_mass(volume, center_axis=None, center=None):
    """Read the solid volume and optional mass centroid independently of the editor."""
    def check(p):
        mass = p.get("mass") or {}
        centroid = mass.get("center_of_mass")
        coordinate = (centroid["xyz".index(center_axis)]
                      if center_axis in ("x", "y", "z")
                      and isinstance(centroid, list) and len(centroid) == 3 else None)
        want = center
        if center_axis in ("x", "y"):
            want = _ee_shift(center, 0.0)[0] if center_axis == "x" else _ee_shift(0.0, center)[1]
        return _measured("edited Extrude material", {"volume": mass.get("volume"), "center": centroid},
                         _near(mass.get("volume"), volume, 0.005)
                         and (center_axis is None or _near(coordinate, want, 0.005)))
    return check


def _extrude_start_body(shift_mm):
    """Check the target's independent bounds and volume against its pre-edit read."""
    def check(p):
        before = _RECALL.get("ee_start_before") or {}
        old_lo, old_hi = before.get("min_point") or {}, before.get("max_point") or {}
        lo, hi = p.get("min_point") or {}, p.get("max_point") or {}
        mass = p.get("mass") or {}
        good = (p.get("kind") == "body" and p.get("units") == "mm"
                and p.get("lump_count") == 1 and _near(mass.get("volume"), 1000, 0.001)
                and all(_near(lo.get(axis), old_lo.get(axis), 0.01)
                        and _near(hi.get(axis), old_hi.get(axis), 0.01) for axis in ("x", "y"))
                and _near(lo.get("z"), old_lo.get("z", float("nan")) + shift_mm, 0.01)
                and _near(hi.get("z"), old_hi.get("z", float("nan")) + shift_mm, 0.01))
        return _measured("Extrude start moves target material", p, good)
    return check


def _extrude_start_history(p):
    """Check the feature row and marker against the pre-edit timeline read."""
    before = _RECALL.get("ee_start_history") or {}
    now = p.get("timeline") or {}
    return _measured("start edit preserves timeline identity", now,
                     bool(before.get("timeline")) and now == before)


def _extrude_start_seed(p):
    """Check the source body's independent bounds and volume are unchanged."""
    before = _RECALL.get("ee_start_seed") or {}
    mass = p.get("mass") or {}
    return _measured("start edit leaves source material unchanged", p,
                     p.get("min_point") == before.get("min_point")
                     and p.get("max_point") == before.get("max_point")
                     and _near(mass.get("volume"), 500, 0.001))


def _ee_shift(x, y):
    """(x, y) moved to where the extrusion story's block landed, the ee_at recall of its origin."""
    at = _RECALL.get("ee_at")
    if not isinstance(at, dict) or not all(
            isinstance(at.get(axis), (int, float)) and not isinstance(at.get(axis), bool)
            and math.isfinite(at[axis]) for axis in ("x", "y")):
        raise AssertionError("ee_at baseline requires finite numeric x and y")
    return x + at["x"], y + at["y"]


def _extrude_edit_roof(p):
    """Check the unaffected roof's six direct planar areas and world centroids."""
    rows = p.get("matches") or []
    expected = [[area, *_ee_shift(x, y), z] for area, x, y, z in (
        [100, -5, 5, 32.5], [100, 35, 5, 32.5], [200, 15, -5, 32.5], [200, 15, 15, 32.5],
        [800, 15, 5, 30], [800, 15, 5, 35])]
    actual = [[row.get("area"), *(row.get("position") or [])] for row in rows]
    good = (p.get("units") == "mm" and p.get("match_count") == len(rows) == 6
            and all(row.get("kind") == "planar_face" for row in rows)
            and all(len(row) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                          and math.isfinite(v) for v in row) for row in actual))
    return _measured("unaffected roof planar area/centroid set", actual,
                     good and all(_near(v, want, 0.00001) for row, wanted in zip(sorted(actual), expected)
                                  for v, want in zip(row, wanted)))


def _extrude_edit_roof_signature(p):
    """Capture the independent roof face areas and centroids around a mass read."""
    return sorted([[row.get("area"), *(row.get("position") or [])]
                   for row in p.get("matches") or []])


def _extrude_edit_roof_unchanged(key):
    """Compare the roof's direct face geometry before and after the mass read."""
    def check(p):
        before, after = _RECALL.get(key), _extrude_edit_roof_signature(p)
        return _measured("unaffected roof face geometry around mass read",
                         {"before": before, "after": after},
                         isinstance(before, list) and len(before) == len(after) == 6
                         and before == after and _extrude_edit_roof(p) is True)
    return check


def _extrude_mass_freshness(label, volume=None, area=None, center=None, disclose=False):
    """Check the witnessed roof mass state and the public freshness remedy disclosure."""
    def check(p):
        mass = p.get("mass") or {}
        got_center = mass.get("center_of_mass") or []
        note = mass.get("note") or ""
        good = (p.get("kind") == "body" and mass.get("units") == "mm"
                and mass.get("accuracy") == "very_high"
                and mass.get("accuracy_used") == "very_high"
                and mass.get("freshness_verified") is False
                and _num(mass.get("volume")) and _num(mass.get("area"))
                and len(got_center) == 3
                and all(_num(value) for value in got_center))
        if volume is not None:
            good = good and _near(mass.get("volume"), volume, 0.001)
        if area is not None:
            good = good and _near(mass.get("area"), area, 0.001)
        if center is not None:
            expected_xy = _ee_shift(center[0], center[1])
            good = (good and _near(got_center[0], expected_xy[0], 0.0001)
                    and _near(got_center[1], expected_xy[1], 0.0001)
                    and _near(got_center[2], center[2], 0.0001))
        if disclose:
            note = note.lower()
            good = (good and "physical-property freshness is unverified" in note
                    and "linked feature edits may leave stale values" in note
                    and "design_recompute and read again" in note
                    and "uncaptured driven joint poses" in note
                    and "recompute does not verify freshness" in note)
        return _measured(label, {"volume": mass.get("volume"), "area": mass.get("area"),
                                 "center": got_center, "accuracy_used": mass.get("accuracy_used"),
                                 "note": note}, good)
    return check


def _extrude_mass_bundle(p):
    """Keep the complete mass-property bundle needed to compare consecutive reads."""
    return p.get("mass") or {}


def _extrude_mass_bundle_unchanged(key):
    """Require a repeated mass read to preserve the actual property bundle."""
    def check(p):
        before, after = _RECALL.get(key), _extrude_mass_bundle(p)
        disclosed = (_extrude_mass_freshness(
            "second mass read carries the freshness disclosure", disclose=True)(p) is True)
        return _measured("second mass read preserves the post-edit property bundle",
                         {"before": before, "after": after},
                         isinstance(before, dict) and before == after and disclosed)
    return check


def _extrude_edit_history(p):
    """The complete timeline row identities and marker stay where the earlier read placed them."""
    timeline = p.get("timeline") or {}
    before = _RECALL.get("ee_history") or {}
    fields = lambda t: [(r.get("index"), r.get("name"), r.get("type"), r.get("component"))
                        for r in t.get("timeline") or []]
    return _measured("edit preserves timeline rows and parked marker", timeline,
                     timeline.get("marker_position") == before.get("marker_position")
                     and fields(timeline) == fields(before) and bool(fields(before)))


def _extrude_edit_dependent(key, component, healthy):
    """The recalled dependent row's health in an independent timeline read; a failed one is a
    plain-text warning while no row reads error."""
    def check(p):
        timeline = (p.get("timeline") or {}).get("timeline") or []
        rows = [r for r in timeline
                if r.get("name") == _RECALL.get(key) and r.get("component") == component]
        health = rows[0].get("health", "healthy") if len(rows) == 1 else None
        if healthy:
            return _measured("dependent feature health", health, health == "healthy")
        message = rows[0].get("message") if rows else None
        return _measured("dependent feature warning", {"health": health, "message": message},
                         health == "warning" and isinstance(message, str) and bool(message.strip())
                         and "<" not in message and ">" not in message
                         and not message.endswith(_RECALL.get(key) or "\0")
                         and all(r.get("health") != "error" for r in timeline))
    return check


def _orient_warnings(count):
    """workspace_orient's design health: no errors, `count` timeline warnings, still healthy."""
    return lambda p: _measured(f"workspace_orient reads {count} timeline warning(s)",
                               {"health": p.get("health")},
                               (p.get("health") or {}).get("timeline_errors") == 0
                               and (p.get("health") or {}).get("timeline_warnings") == count
                               and (p.get("health") or {}).get("is_healthy") is True)


def _extrude_side_body(label, z_low, z_high, volume):
    """The side story's body z span and volume in mm, read independently of the editor."""
    def check(p):
        mass = p.get("mass") or {}
        span = [(p.get("min_point") or {}).get("z"), (p.get("max_point") or {}).get("z")]
        return _measured(label, {"z": span, "volume": mass.get("volume")},
                         _near(span[0], z_low, 0.01) and _near(span[1], z_high, 0.01)
                         and _near(mass.get("volume"), volume, 0.01))
    return check


def _extrude_side_edit(before_cm, after_cm, side):
    """A landed distance edit whose signed read-back shows the side and keeps the parameter."""
    def check(p):
        was, now = p.get("definition_before") or {}, p.get("definition_after") or {}
        return _measured("signed distance read-back", {"was": was, "now": now},
                         _extrude_edit_landed(p) is True
                         and _near(was.get("distance_cm"), before_cm, 1e-6)
                         and _near(now.get("distance_cm"), after_cm, 1e-6) and now.get("side") == side
                         and now.get("distance_parameter") == _RECALL.get("ee_side_param"))
    return check


def _extrude_edit_identical(sketch):
    """A landed profile swap whose bodies re-read identical, reported as a success."""
    def check(p):
        after = p.get("definition_after") or {}
        return _measured("identical-geometry profile swap", {
            "edited": p.get("edited"), "definition_matches": p.get("definition_matches"),
            "geometry_changed": p.get("geometry_changed"), "rollback": p.get("rollback"),
            "other_components_unchanged": p.get("other_components_unchanged"),
            "profile_sketch": after.get("profile_sketch"), "note": p.get("note")},
            p.get("edited") is True and p.get("definition_matches") is True
            and p.get("geometry_changed") is False
            and p.get("other_components_unchanged") is True and "rollback" not in p
            and after.get("profile_sketch") == sketch
            and (p.get("note") or "").endswith("The body geometry reads identical before and after."))
    return check


def _extrude_edit_rows():
    """Build a bounded definition-edit bench in an owned scratch document."""
    rows = [
        ("doc_get", {}, _home_document, ("ee_story", _recall("ee_story", _home_address))),
        ("doc_new", lambda c: {"expect_document": _ctx_get(c, "ee_story", "story")},
         _new_document, ("ee_doc", _recall("ee_doc", lambda p: p["document_handle"]))),
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "ee_doc", args(c) if callable(args) else args), check, save))

    def rectangle(name, low, high, plane="xy"):
        write("sketch_create", {"name": name, "plane": plane})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [{
            "kind": "rectangle", "x1": low[0], "y1": low[1], "x2": high[0], "y2": high[1]}]})

    def inspect(target, check):
        rows.append(("model_inspect", lambda c, target=target: _combine_inspect(target), check, None))

    def placed(label, low, high, volume):
        # the layout moves this story's geometry as a block; the EditOriginal extrude's min point
        # (authored at the origin, recalled as ee_at) is where the block landed
        def check(p):
            dx, dy = _ee_shift(0.0, 0.0)
            return _combine_body(label, (low[0] + dx, low[1] + dy, low[2]),
                                 (high[0] + dx, high[1] + dy, high[2]), volume)(p)
        return check

    def definition(key, extent, distance=None, distance2=None, units="mm", side_count=None):
        rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
            lambda p: _measured("complete timeline before definition read", p.get("timeline"),
                bool((p.get("timeline") or {}).get("timeline"))
                and not (p.get("timeline") or {}).get("truncated")),
            ("definition_timeline", _recall("definition_timeline", lambda p: p["timeline"]))))
        rows.append(("design_get", lambda c: {"include": ["definition"],
            "feature": _ctx_get(c, key, "Extrude"), "units": units},
            _extrude_definition(extent, distance, distance2, units, side_count), None))
        rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                     _definition_timeline_unchanged, None))

    def edit(key, args):
        write("model_edit_extrude", lambda c, key=key, args=args: {
            "feature": _ctx_get(c, key, "existing Extrude"), **args}, _extrude_edit_landed)
        if key == "ee_scope":
            rows.append(("find_geometry", {"target": "EditProfile:Body1", "kind": "planar_face",
                          "units": "mm", "max_results": 6}, _extrude_edit_roof, None))
            inspect("EditProfile:Body2", _extrude_edit_mass(482))

    write("model_create_component", {"name": "EditProfile", "activate": True}, _made_component)
    write("model_construction", {"kind": "plane", "plane": "xy", "offset": 30, "name": "EditRoof"})
    rectangle("EditRoofS", (-5, -5), (35, 15), "EditRoof")
    write("model_extrude", {"sketch_name": "EditRoofS", "distance": 5}, _extruded)
    rows.append(("find_geometry", lambda c: {"target": "EditProfile:Body1", "kind": "planar_face",
                 "nearest_to": [25, 5, 30], "max_results": 1}, _matched(1, "planar_face"), _fg("ee_roof")))
    rectangle("EditOriginal", (0, 0), (10, 10))
    rectangle("EditShifted", (20, 0), (30, 10))
    write("model_extrude", {"sketch_name": "EditOriginal", "distance": 10}, _extruded,
          ("ee_profile", _recall("ee_profile", lambda p: "EditProfile/" + p["feature"])))
    rows.append(("model_inspect", lambda c: _combine_inspect("EditProfile:Body2"), "ok",
                 ("ee_at", _recall("ee_at", lambda p: p["min_point"]))))
    write("sketch_create", {"name": "EditTrailing", "plane": "xy"})
    write("design_edit_timeline", lambda c: {"action": "roll", "feature": _ctx_get(c, "ee_profile", "Extrude"),
                                             "to": "after"})
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100}, "ok",
                 ("ee_history", _recall("ee_history", lambda p: p["timeline"]))))
    edit("ee_profile", {"action": "profile", "profile": {"sketch": "EditShifted", "profile_index": 0}})
    inspect("EditProfile:Body2", placed("shifted equal-volume extrusion", (20, 0, 0), (30, 10, 10), 1000))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100}, _extrude_edit_history, None))
    write("design_edit_timeline", {"action": "roll", "to": "end"})
    for args, low, high, volume in [
        ({"extent": "symmetric", "distance": 8}, (20, 0, -8), (30, 10, 8), 1600),
        ({"extent": "two_side", "distance": 12, "distance2": 8}, (20, 0, -8), (30, 10, 12), 2000),
    ]:
        edit("ee_profile", {"action": "extent", **args})
        inspect("EditProfile:Body2", placed(args["extent"], low, high, volume))
        factor = 0.1 if args["extent"] == "two_side" else 1
        definition("ee_profile", args["extent"], args["distance"] * factor,
                   args.get("distance2", 0) * factor if "distance2" in args else None,
                   "cm" if factor == 0.1 else "mm")
        inspect("EditProfile:Body2", placed("definition read preserves " + args["extent"], low, high, volume))
    write("model_edit_extrude", lambda c: {"feature": _ctx_get(c, "ee_profile", "Extrude"),
          "action": "extent", "extent": "to_face", "to_object": _ctx_get(c, "ee_roof", "roof")},
          _extrude_edit_landed)
    inspect("EditProfile:Body2", placed("to-face replacement", (20, 0, 0), (30, 10, 30), 3000))
    definition("ee_profile", "to_face")
    inspect("EditProfile:Body2", placed("definition read preserves to_face", (20, 0, 0), (30, 10, 30),
                                        3000))
    edit("ee_profile", {"action": "extent", "extent": "distance", "distance": 5})
    inspect("EditProfile:Body2", placed("distance replacement", (20, 0, 0), (30, 10, 5), 500))
    rectangle("EditDependentCut", (21, 1), (24, 4))
    write("model_extrude", {"sketch_name": "EditDependentCut", "distance": 2, "operation": "cut",
                            "target_bodies": ["EditProfile:Body2"]}, _extruded,
          ("ee_dependent", _recall("ee_dependent", lambda p: p["feature"])))
    write("model_edit_extrude", lambda c: {"feature": _ctx_get(c, "ee_profile", "Extrude"),
          "action": "profile", "profile": {"sketch": "EditOriginal", "profile_index": 0}},
          _refused("definition landed", "downstream", "It was rolled back and re-read: profile "
                   "reads sketch 'EditShifted' profile 0 again"))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 _extrude_edit_dependent("ee_dependent", "EditProfile", healthy=True), None))
    inspect("EditProfile:Body2", placed("rolled-back edit keeps its dependent cut",
                                        (20, 0, 0), (30, 10, 5), 482))

    def side_refs(p):
        _RECALL["ee_side_param"] = p["model_parameters"]["distance"]
        return "EditSide/" + p["feature"]

    def side_edit(args, check):
        write("model_edit_extrude", lambda c, args=args: {
            "feature": _ctx_get(c, "ee_side", "EditSide extrude"), "action": "extent", **args}, check)

    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "EditSide", "activate": True}, _made_component)
    rectangle("EditSideS", (50, 0), (70, 20))
    # The same rectangle again: a profile swap to it leaves the body identical.
    rectangle("EditSideTwin", (50, 0), (70, 20))
    write("model_extrude", {"sketch_name": "EditSideS", "distance": -10}, _extruded,
          ("ee_side", side_refs))
    inspect("EditSide:Body1", _extrude_side_body("negative extrusion", -10, 0, 4000))
    definition("ee_side", "distance", -10 / 25.4, units="in")
    inspect("EditSide:Body1", _extrude_side_body("definition read preserves negative extrusion", -10, 0, 4000))
    for args, was, now, side, span in (
            ({"distance": 5}, -1.0, -0.5, "negative", (-5, 0)),
            ({"distance": 5, "direction": "positive"}, -0.5, 0.5, "positive", (0, 5)),
            ({"distance": 10, "direction": "negative"}, 0.5, -1.0, "negative", (-10, 0))):
        side_edit({"extent": "distance", **args}, _extrude_side_edit(was, now, side))
        inspect("EditSide:Body1", _extrude_side_body(f"{side} side after distance edit", *span,
                                                     abs(span[0] - span[1]) * 400))
    rectangle("EditSidePocket", (55, 5), (65, 15))
    write("model_extrude", {"sketch_name": "EditSidePocket", "distance": -3, "operation": "cut",
                            "target_bodies": ["EditSide:Body1"]}, _extruded,
          ("ee_side_pocket", _recall("ee_side_pocket", lambda p: p["feature"])))
    inspect("EditSide:Body1", _extrude_side_body("pocketed negative extrusion", -10, 0, 3700))
    # The flip leaves the pocket cutting air, so its health fails the check and the signed
    # distance is restored through its parameter's expression.
    side_edit({"extent": "distance", "distance": 10, "direction": "positive"},
              _refused("downstream", "It was rolled back and re-read: extent reads distance "
                       "-10.0 mm again"))
    rows.append(("param_get", lambda c: {"name": _RECALL["ee_side_param"]},
                 lambda p: _measured("restored signed distance parameter", p.get("parameter"),
                                     _near((p.get("parameter") or {}).get("value"), -10, 1e-6)), None))
    inspect("EditSide:Body1", _extrude_side_body("rolled-back flip keeps the pocket", -10, 0, 3700))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 _extrude_edit_dependent("ee_side_pocket", "EditSide", healthy=True), None))
    side_edit({"extent": "symmetric", "distance": 10}, _extrude_edit_landed)
    inspect("EditSide:Body1", _extrude_side_body("symmetric side extent", -10, 10, 7700))
    # A symmetric prior has no measured reverse, so the same failure names what stayed applied.
    side_edit({"extent": "distance", "distance": 10, "direction": "positive"},
              _refused("downstream", "This STAYED APPLIED (not rolled back): extent now reads "
                       "distance 10.0 mm (was symmetric 10.0 mm per side)",
                       "extent='symmetric', distance=10.0"))
    inspect("EditSide:Body1", _extrude_side_body("kept flip beside its failed pocket", 0, 10, 4000))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 _extrude_edit_dependent("ee_side_pocket", "EditSide", healthy=False), None))
    rows.append(("workspace_orient", {}, _orient_warnings(1), None))
    side_edit({"extent": "symmetric", "distance": 10.0}, _extrude_edit_landed)
    inspect("EditSide:Body1", _extrude_side_body("named remedy restores the pocket", -10, 10, 7700))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 _extrude_edit_dependent("ee_side_pocket", "EditSide", healthy=True), None))
    rows.append(("workspace_orient", {}, _orient_warnings(0), None))
    side_edit({"extent": "symmetric", "distance": 10.0},
              _refused("already has that definition", "Nothing was edited"))
    inspect("EditSide:Body1", _extrude_side_body("identical re-edit refused", -10, 10, 7700))
    # The lone body's extrude is written join; Fusion keeps it new.
    write("model_edit_extrude", lambda c: {"feature": _ctx_get(c, "ee_side", "EditSide extrude"),
          "action": "operation", "operation": "join"},
          _refused("Fusion kept the prior definition", "Nothing changed: operation still reads new"))
    inspect("EditSide:Body1", _extrude_side_body("refused join", -10, 10, 7700))
    write("model_edit_extrude", lambda c: {"feature": _ctx_get(c, "ee_side", "EditSide extrude"),
          "action": "profile", "profile": {"sketch": "EditSideTwin", "profile_index": 0}},
          _extrude_edit_identical("EditSideTwin"))
    inspect("EditSide:Body1", _extrude_side_body("identical profile swap", -10, 10, 7700))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 _extrude_edit_dependent("ee_side_pocket", "EditSide", healthy=True), None))

    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "EditScope", "activate": True}, _made_component)
    rectangle("EditStock", (0, 0), (10, 10))
    write("model_extrude", {"sketch_name": "EditStock", "distance": 10, "symmetric": True}, _extruded)
    inspect("EditScope:Body1", placed("symmetric distance 10 is per side",
                                     (0, 0, -10), (10, 10, 10), 2000))
    for name, z, depth in (("EditUpper", 0, 20), ("EditHidden", 40, 10)):
        if z:
            write("model_construction", {"kind": "plane", "plane": "xy", "offset": z, "name": name})
        rectangle(name + "S", (0, 0), (10, 10), name if z else "xy")
        write("model_extrude", {"sketch_name": name + "S", "distance": depth}, _extruded)
    write("view_set", {"action": "hide", "target": "EditScope:Body3"})
    rows.append(("find_geometry", lambda c: {"target": "EditScope:Body3", "kind": "planar_face",
                 "nearest_to": [7.5, 2.5, 40], "max_results": 1}, _matched(1, "planar_face"), _fg("ee_scope_roof")))
    rectangle("EditPocketA", (1, 1), (4, 4))
    rectangle("EditPocketB", (6, 1), (9, 4))
    write("model_extrude", {"sketch_name": "EditPocketA", "distance": 2}, _extruded,
          ("ee_scope", _recall("ee_scope", lambda p: "EditScope/" + p["feature"])))
    for op, volume in (("join", 3000), ("cut", 1982), ("intersect", 18)):
        edit("ee_scope", {"action": "operation", "operation": op,
                          **({"target_bodies": ["EditScope:Body1"]} if op != "join" else {})})
        inspect("EditScope:Body1", _extrude_edit_mass(volume))
    edit("ee_scope", {"action": "operation", "operation": "new"})
    inspect("EditScope:1", _extrude_edit_mass(5018))
    edit("ee_scope", {"action": "operation", "operation": "cut", "target_bodies": ["EditScope:Body1"]})
    edit("ee_scope", {"action": "profile", "profile": {"sketch": "EditPocketB", "profile_index": 0}})
    inspect("EditScope:Body1", _extrude_edit_mass(1982, "x", (10000 - 18 * 7.5) / 1982))
    inspect("EditScope:Body2", _extrude_edit_mass(2000))
    rows.append(("model_inspect", _combine_inspect("EditProfile:Body1"),
                 _extrude_mass_freshness("roof mass before through-all replay", 4000, 2200,
                                         (15, 5, 32.5), disclose=True), None))
    rows.append(("find_geometry", {"target": "EditProfile:Body1", "kind": "planar_face",
                                   "units": "mm", "max_results": 6}, _extrude_edit_roof,
                 ("ee_mass_roof_faces", _recall("ee_mass_roof_faces", _extrude_edit_roof_signature))))
    write("model_edit_extrude", lambda c: {
        "feature": _ctx_get(c, "ee_scope", "Extrude"),
        "action": "extent", "extent": "through_all", "direction": "positive"},
        lambda p: _measured("linked source remains the addressed edit feature",
                            p.get("linked_component_aliases"),
                            _extrude_edit_landed(p) is True
                            and p.get("linked_component_aliases") == ["EditProfile"]))
    rows.append(("model_inspect", _combine_inspect("EditProfile:Body1"),
                 _extrude_mass_freshness("post-edit roof mass state is reported",
                                         disclose=True),
                 ("ee_roof_replay_mass",
                  _recall("ee_roof_replay_mass", _extrude_mass_bundle))))
    rows.append(("find_geometry", {"target": "EditProfile:Body1", "kind": "planar_face",
                                   "units": "mm", "max_results": 6},
                 _extrude_edit_roof_unchanged("ee_mass_roof_faces"), None))
    rows.append(("model_inspect", _combine_inspect("EditProfile:Body1"),
                 _extrude_mass_bundle_unchanged("ee_roof_replay_mass"), None))
    write("design_recompute", {},
          lambda p: _measured("explicit recompute reports healthy timeline", p,
                              p.get("recomputed") is True and p.get("error_count") == 0
                              and p.get("errors") == []))
    rows.append(("model_inspect", _combine_inspect("EditProfile:Body1"),
                 _extrude_mass_freshness("roof mass after explicit recompute", 4000, 2200,
                                         (15, 5, 32.5), disclose=True), None))
    inspect("EditScope:Body1", _extrude_edit_mass(1910, "z", -450 / 1910))
    definition("ee_scope", "through_all", side_count=1)
    inspect("EditScope:Body1", _extrude_edit_mass(1910, "z", -450 / 1910))
    inspect("EditScope:Body2", _extrude_edit_mass(2000))
    write("model_edit_extrude", lambda c: {
        "feature": "EditProfile/" + _ctx_get(c, "ee_scope", "Extrude").split("/")[-1],
        "action": "extent", "extent": "distance", "distance": 5},
        _refused("no timeline feature matches", "EditProfile/", "design_get", "timeline"))
    rows.append(("find_geometry", {"target": "EditProfile:Body1", "kind": "planar_face",
                                   "units": "mm", "max_results": 6}, _extrude_edit_roof, None))
    inspect("EditProfile:Body2", _extrude_edit_mass(482))
    inspect("EditScope:Body1", _extrude_edit_mass(1910, "z", -450 / 1910))
    inspect("EditScope:Body2", _extrude_edit_mass(2000))
    edit("ee_scope", {"action": "participants", "target_bodies": ["EditScope:Body2"]})
    inspect("EditScope:Body1", _extrude_edit_mass(2000))
    inspect("EditScope:Body2", _extrude_edit_mass(1820))
    inspect("EditScope:Body3", _extrude_edit_mass(1000))
    edit("ee_scope", {"action": "participants", "target_bodies": ["EditScope:Body1"]})
    edit("ee_scope", {"action": "extent", "extent": "through_all", "direction": "negative"})
    inspect("EditScope:Body1", _extrude_edit_mass(1910, "z", 450 / 1910))
    write("model_edit_extrude", lambda c: {"feature": _ctx_get(c, "ee_scope", "Extrude"),
          "action": "extent", "extent": "through_all", "direction": "both"},
          _refused("Two-sided through_all", "participant assignment is unsupported", "separate one-sided"))
    rows.append(("find_geometry", {"target": "EditProfile:Body1", "kind": "planar_face",
                                   "units": "mm", "max_results": 6}, _extrude_edit_roof, None))
    inspect("EditProfile:Body2", _extrude_edit_mass(482))
    inspect("EditScope:Body1", _extrude_edit_mass(1910, "z", 450 / 1910))
    inspect("EditScope:Body2", _extrude_edit_mass(2000))
    inspect("EditScope:Body3", _extrude_edit_mass(1000))
    write("model_edit_extrude", lambda c: {"feature": _ctx_get(c, "ee_scope", "Extrude"),
          "action": "extent", "extent": "to_face", "to_object": _ctx_get(c, "ee_scope_roof", "roof")},
          _extrude_edit_landed)
    rows.append(("find_geometry", {"target": "EditProfile:Body1", "kind": "planar_face",
                          "units": "mm", "max_results": 6}, _extrude_edit_roof, None))
    inspect("EditProfile:Body2", _extrude_edit_mass(482))
    inspect("EditScope:Body1", _extrude_edit_mass(1910, "z", -450 / 1910))
    inspect("EditScope:Body2", _extrude_edit_mass(2000))
    edit("ee_scope", {"action": "operation", "operation": "intersect", "target_bodies": ["EditScope:Body1"]})
    inspect("EditScope:Body1", _extrude_edit_mass(90))
    edit("ee_scope", {"action": "participants", "target_bodies": ["EditScope:Body2"]})
    inspect("EditScope:Body1", _extrude_edit_mass(2000))
    inspect("EditScope:Body2", _extrude_edit_mass(180))
    inspect("EditScope:Body3", _extrude_edit_mass(1000))
    rectangle("EditLate", (1, 1), (4, 4))
    write("model_edit_extrude", lambda c: {"feature": _ctx_get(c, "ee_scope", "Extrude"),
          "action": "profile", "profile": {"sketch": "EditLate", "profile_index": 0}},
          _refused("sketch 'EditLate' is at timeline row", "action='reorder', feature='EditLate@",
                   "to='before'", "Nothing was edited."))
    inspect("EditScope:Body2", _extrude_edit_mass(180))
    write("model_extrude", {"sketch_name": "EditPocketA", "operation": "cut",
                            "extent": "through_all", "symmetric": True,
                            "target_bodies": ["EditScope:Body1"]}, _extruded,
          ("ee_both_source", lambda p: "EditScope/" + p["feature"]))
    definition("ee_both_source", "through_all", side_count=2)
    for after_refusal in (False, True):
        if after_refusal:
            write("model_edit_extrude", lambda c: {
                "feature": _ctx_get(c, "ee_both_source", "existing two-sided through cut"),
                "action": "participants", "target_bodies": ["EditScope:Body2"]},
                _refused("Two-sided through_all", "participant assignment is unsupported", "separate one-sided"))
        inspect("EditScope:Body1", _extrude_edit_mass(1820, "z", 0))
        inspect("EditScope:Body2", _extrude_edit_mass(180))
        inspect("EditScope:Body3", _extrude_edit_mass(1000))
        rows.append(("find_geometry", {"target": "EditProfile:Body1", "kind": "planar_face",
                                       "units": "mm", "max_results": 6}, _extrude_edit_roof, None))

    def four_state(label, bodies, dimensions, fragment_volumes=()):
        def check(p):
            mass = p.get("mass") or {}
            got = {row.get("body"): row.get("volume") for row in mass.get("per_body") or []}
            fragments = [volume for name, volume in got.items() if name not in bodies]
            spans = sorted(p.get(axis) for axis in ("x", "y", "z")
                           if isinstance(p.get(axis), (int, float)))
            good = (p.get("kind") == "occurrence" and p.get("units") == "mm"
                    and mass.get("accuracy_used") == "very_high"
                    and mass.get("per_body_truncated") is False
                    and mass.get("per_body_count") == len(bodies) + len(fragment_volumes) == len(got)
                    and set(bodies).issubset(got) and len(spans) == 3
                    and all(_near(got[name], volume, 0.005) for name, volume in bodies.items())
                    and all(isinstance(volume, (int, float)) for volume in fragments)
                    and all(_near(a, b, 0.005) for a, b in
                            zip(sorted(fragments), sorted(fragment_volumes)))
                    and all(_near(a, b, 0.01) for a, b in zip(spans, sorted(dimensions)))
                    and _near(mass.get("volume"), sum(bodies.values()) + sum(fragment_volumes), 0.005))
            return _measured(label + " independent material and bounds",
                             {"bodies": got, "volume": mass.get("volume"), "dimensions": spans}, good)
        return check

    def four_read(bodies, dimensions, label, fragment_volumes=()):
        rows.append(("model_inspect", {**_combine_inspect("G18Four:1"), "per_body": True},
                     four_state(label, bodies, dimensions, fragment_volumes), None))
        rows.append(("model_inspect", {**_combine_inspect("G18EditDecoy:1"), "per_body": True},
                     four_state(label + " decoy", {"Body1": 500}, (5, 10, 10)), None))

    def four_edit(args, operation, sketch, participants):
        def check(p):
            landed = _extrude_edit_landed(p)
            after = p.get("definition_after") or {}
            return _measured("four-profile definition readback", after,
                             landed is True and p.get("action") == args["action"]
                             and after.get("operation") == operation
                             and after.get("profile_sketch") == sketch
                             and after.get("extent") == "symmetric"
                             and after.get("participants") == participants)
        write("model_edit_extrude", lambda c, args=args: {
            "feature": _ctx_get(c, "ee_four", "four-profile Extrude"), **args}, check)

    # A literal root keeps the owned mixed-plane fixture outside the story layout.
    rows.append(("design_activate_component", {"occurrence": "root"}, "ok", None))
    write("model_create_component", {"name": "G18EditDecoy", "activate": True}, _made_component)
    rectangle("G18DecoyProfile", (100, 100), (110, 110))
    write("model_extrude", {"sketch_name": "G18DecoyProfile", "distance": 5,
                            "operation": "new"}, _extruded)
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "G18Four", "activate": True}, _made_component)
    for name, low, high in (("G18StockA", (190, -30), (235, 0)),
                            ("G18StockB", (190, 0), (235, 30))):
        rectangle(name, low, high)
        write("model_extrude", {"sketch_name": name, "distance": 20,
                                "symmetric": True, "operation": "new"}, _extruded)
    rectangle("G18Replacement", (205, 0), (215, -10), "xz")
    write("sketch_create", {"name": "G18FourProfile", "plane": "xz"})
    write("sketch_add_geometry", {"sketch_name": "G18FourProfile", "geometry": [
        {"kind": "rectangle", "x1": 190, "y1": 0, "x2": 235, "y2": -6},
        {"kind": "rectangle", "x1": 194, "y1": 0, "x2": 200, "y2": -40}]})
    write("model_extrude", {"sketch_name": "G18FourProfile", "profile_index": "all",
                            "distance": 45, "symmetric": True, "operation": "new"},
          lambda p: _measured("four-profile source selection", p,
                              p.get("extruded") is True and p.get("profiles_extruded") == 4
                              and sorted(p.get("profile_index") or []) == [0, 1, 2, 3]),
          ("ee_four", _recall("ee_four", lambda p: "G18Four/" + p["feature"])))
    four_read({"Body1": 54000, "Body2": 54000, "Body3": 42660},
              (45, 90, 60), "four-profile initial")
    four_edit({"action": "extent", "extent": "symmetric", "distance": 30},
              "new", "G18FourProfile", [])
    four_read({"Body1": 54000, "Body2": 54000, "Body3": 28440},
              (45, 60, 60), "four-profile extent")
    four_edit({"action": "operation", "operation": "cut",
               "target_bodies": ["G18Four:Body1"]}, "cut", "G18FourProfile", ["Body1"])
    four_read({"Body2": 54000}, (40, 45, 60),
              "four-profile scoped cut", (1680, 14700, 27000))
    four_edit({"action": "participants", "target_bodies": ["G18Four:Body2"]},
              "cut", "G18FourProfile", ["Body2"])
    four_read({"Body1": 54000}, (40, 45, 60),
              "four-profile participant switch", (1680, 14700, 27000))
    four_edit({"action": "profile", "profile": {"sketch": "G18Replacement",
                                                "profile_index": 0}},
              "cut", "G18Replacement", ["Body2"])
    four_read({"Body1": 54000, "Body2": 51000}, (40, 45, 60),
              "four-profile scalar replacement")
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "EditStart", "activate": True}, _made_component)
    rectangle("EditStartSeed", (100, 0), (110, 10))
    write("model_extrude", {"sketch_name": "EditStartSeed", "distance": 5}, _extruded)
    rectangle("EditStartTarget", (120, 0), (130, 10))
    write("model_extrude", {"sketch_name": "EditStartTarget", "distance": 10}, _extruded,
          ("ee_start_feature", _recall("ee_start_feature", lambda p: "EditStart/" + p["feature"])))
    rows.append(("model_inspect", _combine_inspect("EditStart:Body2"), _extrude_edit_mass(1000),
                 ("ee_start_before", _recall("ee_start_before", lambda p: p))))
    rows.append(("model_inspect", _combine_inspect("EditStart:Body1"), _extrude_edit_mass(500),
                 ("ee_start_seed", _recall("ee_start_seed", lambda p: p))))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100}, "ok",
                 ("ee_start_history", _recall("ee_start_history", lambda p: p["timeline"]))))
    rows.append(("find_geometry", lambda c: {
        "target": "EditStart:Body1", "kind": "planar_face", "units": "mm", "max_results": 1,
        "nearest_to": [*_ee_shift(105, 5), 5]}, _matched(1, "planar_face"), _fg("ee_start_face")))
    for args, shift in (({"start_offset": 5}, 5),
                        ({"start_object": "xy", "start_offset": 8}, 8),
                        ({"start_object": "face", "start_offset": 0}, 5)):
        write("model_edit_extrude", lambda c, args=args: {
            "feature": _ctx_get(c, "ee_start_feature", "EditStart extrude"), "action": "start",
            **{key: _ctx_get(c, "ee_start_face", "seed face") if key == "start_object" and value == "face"
               else value for key, value in args.items()}}, _extrude_edit_landed)
        rows.append(("model_inspect", _combine_inspect("EditStart:Body2"),
                     _extrude_start_body(shift), None))
        rows.append(("model_inspect", _combine_inspect("EditStart:Body1"),
                     _extrude_start_seed, None))
        rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                     _extrude_start_history, None))
    rows += [
        ("doc_activate", lambda c: {"name": _ctx_get(c, "ee_story", "story"),
                                    "expect_document": _ctx_get(c, "ee_doc", "scratch")}, "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "ee_doc", "scratch"), "save_changes": False,
                                 "expect_document": _ctx_get(c, "ee_story", "story")}, _document_closed, None),
    ]
    return rows


def _org_vertices(p):
    """Read a complete set of finite world vertices from find_geometry."""
    rows = p.get("matches") or []
    if (p.get("units") != "mm" or p.get("truncated") is True
            or p.get("match_count") != len(rows) or not rows):
        raise AssertionError("Incomplete organization vertex census")
    points = []
    for row in rows:
        xyz = row.get("position")
        if (row.get("kind") != "vertex" or not isinstance(xyz, list) or len(xyz) != 3
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                           and math.isfinite(x) for x in xyz)):
            raise AssertionError("Unreadable organization vertex")
        if not any(all(abs(a-b) <= 0.00001 for a, b in zip(xyz, old)) for old in points):
            points.append(xyz)
    return sorted(points)


def _org_same_vertices(key):
    """Compare independently read world vertex sets with a saved source."""
    def check(p):
        before, after = _RECALL.get(key), _org_vertices(p)
        good = (isinstance(before, list) and len(before) == len(after) and len(before) in (4, 8)
                and all(sum(all(abs(a-b) <= 0.00001 for a, b in zip(point, candidate))
                            for candidate in after) == 1 for point in before))
        return _measured("organized body world vertices", {"before": before, "after": after}, good)
    return check


def _org_result(action, kind, source_count, destination_count):
    """Require the writer's ownership facts and a fresh consumable reference."""
    def check(p):
        return _measured("body ownership result", p,
                         p.get("action") == action and p.get("body_kind") == kind
                         and isinstance(p.get("handle"), str) and bool(p["handle"])
                         and p.get("source_membership_before") == source_count
                         and p.get("source_membership_after") == (
                             source_count if action == "copy" else source_count - 1)
                         and p.get("destination_membership_after") == destination_count
                         and p.get("selected_world_sample_preserved") is True
                         and p.get("source_retained") is (action == "copy"))
    return check


def _org_tree_history(expected, root_count, history_key):
    """Check occurrence material membership and one healthy appended move row."""
    def check(p):
        _org_tree_counts(expected, root_count)(p)
        old = _RECALL.get(history_key) or {}
        now = p.get("timeline") or {}
        old_rows, rows = old.get("timeline") or [], now.get("timeline") or []
        valid = (("truncated" not in now or now.get("truncated") is False)
                 and now.get("count") == now.get("returned") == len(rows)
                 and now.get("marker_position") == len(rows) and len(rows) == len(old_rows) + 1
                 and rows[:-1] == old_rows
                 and (now.get("summary") or {}).get("states") == {"healthy": len(rows)}
                 and (now.get("summary") or {}).get("exceptions") == [])
        return _measured("body move appends one healthy timeline row",
                         {"before_count": len(old_rows), "after": now}, valid)
    return check


def _org_nested_move_result(p):
    """Require a nested move to publish the two measured destination placements."""
    _org_result("move", "brep", 2, 1)(p)
    effect = p.get("definition_effect") or {}
    placements = effect.get("destination_placements") or {}
    paths = sorted(placements.get("paths") or [])
    wanted = ["OrgDestination:1+OrgExistingChild:1",
              "OrgDestination:2+OrgExistingChild:1"]
    return _measured("nested destination definition has both placed paths", placements,
                     placements.get("count") == 2 and paths == wanted)


def _org_body_material(volume, area):
    """Read a placed body's independently measured material."""
    def check(p):
        mass = p.get("mass") or {}
        return _measured("placed body material", mass,
                         mass.get("units") == "mm" and mass.get("accuracy_used") == "very_high"
                         and _near(mass.get("volume"), volume, .001)
                         and _near(mass.get("area"), area, .001))
    return check


def _org_tree_counts(expected, root_count=0, no_children_of=()):
    """Read all occurrence body counts without trusting the ownership writer."""
    def check(p):
        tree = p.get("tree") or {}
        rows = tree.get("children") or []
        got = {}
        complete = tree.get("truncated") is False and tree.get("children_truncated") is False
        pending = list(rows)
        while pending:
            row = pending.pop()
            complete = (complete and row.get("children_truncated") is not True
                        and row.get("bodies_truncated") is not True)
            got[row.get("full_path")] = row.get("body_count")
            pending.extend(row.get("children") or [])
        wanted = expected() if callable(expected) else expected
        return _measured("organized body occurrence census", got,
                         complete and len(tree.get("root_bodies") or []) == root_count
                         and tree.get("root_bodies_truncated") is not True
                         and all(not any(path.startswith(parent + "+") for path in got)
                                 for parent in no_children_of)
                         and all(got.get(name) == count for name, count in wanted.items()))
    return check


def _org_mesh_count(count):
    """Require a complete scoped mesh census with the expected membership."""
    def check(p):
        rows = p.get("meshes") or []
        return _measured("organized mesh membership", {"count": p.get("count"), "rows": rows},
                         p.get("truncated") is False and p.get("count") == len(rows) == count
                         and all(row.get("triangle_count") == 12 for row in rows))
    return check


def _org_mesh_shape(p):
    """Read mesh topology and analytic box mass through an independent reader."""
    points = _RECALL.get("org_before") or []
    center = (p.get("bbox") or {}).get("center") or {}
    expected_center = [sum(point[i] for point in points) / len(points) for i in range(3)] if points else []
    return _measured("organized mesh shape", p,
                     p.get("kind") == "mesh" and p.get("units") == "mm"
                     and p.get("triangle_count") == 12 and p.get("is_closed") is True
                     and p.get("is_oriented") is True
                     and len(expected_center) == 3
                     and all(_near(center.get(axis), value, 0.001)
                             for axis, value in zip("xyz", expected_center))
                     and _near(p.get("volume"), 672.0, 0.001)
                     and _near(p.get("area"), 472.0, 0.001))


def _org_mesh_box_shape(p, vertices_key, volume, area, label="organized mesh witness"):
    """Measure a mesh witness against its authored box and world center."""
    points = _RECALL.get(vertices_key) or []
    center = (p.get("bbox") or {}).get("center") or {}
    expected = [sum(point[i] for point in points) / len(points) for i in range(3)] if points else []
    return _measured(label, p,
                     p.get("kind") == "mesh" and p.get("units") == "mm"
                     and p.get("triangle_count") == 12 and p.get("is_closed") is True
                     and p.get("is_oriented") is True and len(expected) == 3
                     and all(_near(center.get(axis), value, 0.001)
                             for axis, value in zip("xyz", expected))
                     and _near(p.get("volume"), volume, 0.001)
                     and _near(p.get("area"), area, 0.001))


def _org_mesh_snapshot(p):
    """Keep the independently read mesh geometry needed across a refused write."""
    bbox = p.get("bbox") or {}
    return {"name": p.get("name"), "kind": p.get("kind"), "units": p.get("units"),
            "triangle_count": p.get("triangle_count"), "is_closed": p.get("is_closed"),
            "is_oriented": p.get("is_oriented"), "volume": p.get("volume"),
            "area": p.get("area"), "center": bbox.get("center"),
            "min_point": bbox.get("min_point"), "max_point": bbox.get("max_point")}


def _org_mesh_unchanged(key):
    """Compare a mesh's direct geometry reads around a refused write."""
    def check(p):
        before, after = _RECALL.get(key), _org_mesh_snapshot(p)
        exact = ("name", "kind", "units", "triangle_count", "is_closed", "is_oriented")
        good = (isinstance(before, dict) and all(before.get(field) == after.get(field) for field in exact)
                and all(_num(before.get(field)) and _num(after.get(field))
                        and _near(after[field], before[field], 0.001)
                        for field in ("volume", "area"))
                and all(isinstance(before.get(field), dict) and isinstance(after.get(field), dict)
                        and all(_num(before[field].get(axis)) and _num(after[field].get(axis))
                                and _near(after[field][axis], before[field][axis], 0.001)
                                for axis in "xyz")
                        for field in ("center", "min_point", "max_point")))
        return _measured("mesh geometry after refused write", {"before": before, "after": after}, good)
    return check


def _org_mesh_inventory_unchanged(key):
    """Compare complete scoped mesh membership around a refused write."""
    def check(p):
        before = _RECALL.get(key) or {}
        old, now = before.get("meshes") or [], p.get("meshes") or []
        facts = lambda row: {name: value for name, value in row.items() if name != "handle"}
        good = (before.get("truncated") is False and p.get("truncated") is False
                and before.get("count") == len(old) and p.get("count") == len(now)
                and [facts(row) for row in old] == [facts(row) for row in now])
        return _measured("mesh membership after refused write", {"before": old, "after": now}, good)
    return check


def _org_translated_vertices(p):
    """Check that the returned body handle drives an independent one-millimeter move."""
    before, after = _RECALL.get("org_before"), _org_vertices(p)
    expected = [[x + 1, y, z] for x, y, z in before] if isinstance(before, list) else []
    return _measured("fresh handle consumer translation", {"expected": expected, "actual": after},
                     len(expected) == len(after) and len(expected) in (4, 8)
                     and all(sum(all(abs(a-b) <= 0.00001 for a, b in zip(point, candidate))
                                 for candidate in after) == 1 for point in expected))


def _org_sphere_mass(p):
    """Independently measure a six-millimeter sphere at its selected world position."""
    mass = p.get("mass") or {}
    center = mass.get("center_of_mass") or []
    return _measured("organized sphere mass and world center", mass,
                     mass.get("units") == "mm" and len(center) == 3
                     and all(_near(a, b, 0.001) for a, b in zip(center, (40, 20, 10)))
                     and _near(mass.get("volume"), 4 * math.pi * 6**3 / 3, 0.01)
                     and _near(mass.get("area"), 4 * math.pi * 6**2, 0.01))


def _org_same_copy_result(kind):
    """Require a fresh same-owner copy and its one-placement context."""
    def check(p):
        history = p.get("timeline_health") or {}
        witness = p.get("witness_check") or {}
        return _measured("same-owner body copy", p,
                         p.get("action") == "copy" and p.get("body_kind") == kind
                         and isinstance(p.get("handle"), str) and bool(p["handle"])
                         and p.get("full_path") == "OrgSameSource:1"
                         and p.get("owner_component") == "OrgSameSource"
                         and p.get("source_membership_before") == 2
                         and p.get("source_membership_after") == 3
                         and p.get("destination_membership_before") == 2
                         and p.get("destination_membership_after") == 3
                         and p.get("source_retained") is True
                         and p.get("selected_world_sample_preserved") is True
                         and history.get("checked") is True and history.get("healthy") is True
                         and witness.get("unchanged") is True)
    return check


def _org_same_timeline(p, copied):
    """Check a refused move leaves history or a copy adds one healthy row."""
    before, after = _RECALL.get("org_same_history"), p.get("timeline")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return _measured("same-owner timeline", after, False)
    old, now = before.get("timeline") or [], after.get("timeline") or []
    complete = (before.get("truncated") is not True and after.get("truncated") is not True
                and before.get("count") == before.get("returned") == len(old)
                and after.get("count") == after.get("returned") == len(now))
    fields = lambda rows: [(r.get("index"), r.get("name"), r.get("type"),
                            r.get("component"), r.get("health")) for r in rows]
    old_states = (before.get("summary") or {}).get("states") or {}
    new_states = (after.get("summary") or {}).get("states") or {}
    healthy_added = (isinstance(old_states.get("healthy"), int)
                     and new_states.get("healthy") == old_states["healthy"] + 1
                     and all(new_states.get(key) == value for key, value in old_states.items()
                             if key != "healthy")
                     and (after.get("summary") or {}).get("exceptions")
                     == (before.get("summary") or {}).get("exceptions"))
    good = (complete and isinstance(before.get("count"), int)
            and isinstance(before.get("marker_position"), int)
            and after.get("count") == before["count"] + (1 if copied else 0)
            and after.get("marker_position") == before.get("marker_position") + (1 if copied else 0)
            and fields(now[:len(old)]) == fields(old)
            and (bool(now) and now[-1].get("health", "healthy") == "healthy"
                 and healthy_added if copied else after == before))
    return _measured("same-owner copy history" if copied else "same-owner move refusal history",
                     {"before": before, "after": after}, good)


def _org_same_mesh_inventory(p, count):
    """Read the unchanged original/sibling rows and one new copied mesh."""
    rows = p.get("meshes") or []
    saved = _RECALL.get("org_same_mesh_rows") or []
    names = [row.get("name") for row in rows]
    copied = _RECALL.get("org_same_copied_name")
    facts = lambda row: {key: value for key, value in row.items() if key != "handle"}
    good = (p.get("truncated") is False and p.get("count") == len(rows) == count
            and len(saved) == 2 and len(set(names)) == count
            and all(row.get("triangle_count") == 12 for row in rows)
            and all(sum(row.get("name") == old.get("name") and facts(row) == facts(old)
                        for row in rows) == 1
                    for old in saved)
            and (count == 2 or (isinstance(copied, str)
                                and copied not in {old.get("name") for old in saved}
                                and names.count(copied) == 1)))
    return _measured("same-owner mesh census", {"before": saved, "after": rows}, good)


def _org_same_mesh_copy(p):
    """The copied handle resolves the new named mesh with measured geometry."""
    name = p.get("name")
    original_names = {row.get("name") for row in _RECALL.get("org_same_mesh_rows") or []}
    return (_org_mesh_shape(p) and _measured("copied mesh handle resolves new body", name,
                                            isinstance(name, str) and bool(name)
                                            and name not in original_names))


def _org_same_mesh_sibling(p):
    """Measure the actual sibling mesh against its authored box geometry."""
    return _org_mesh_box_shape(p, "org_same_sibling", 546.0, 422.0,
                               "same-owner sibling mesh geometry")


def _instance_at(path_prefix, origin, deg):
    """Require an instance landed at the requested local origin and Z rotation; record its frame."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    want = {"x": [c, s, 0.0], "y": [-s, c, 0.0], "z": [0.0, 0.0, 1.0]}

    def check(p):
        position, axes = p.get("position") or {}, p.get("axes") or {}
        path = p.get("full_path") or ""
        valid = (p.get("created") is True and p.get("units") == "mm"
                 and path.startswith(path_prefix) and path[len(path_prefix):].isdigit()
                 and all(_num(position.get(a)) and _near(position[a], v, 1e-4)
                         for a, v in zip("xyz", origin))
                 and all(isinstance(axes.get(a), list) and len(axes[a]) == 3
                         and all(_num(g) and _near(g, w, 1e-5) for g, w in zip(axes[a], want[a]))
                         for a in "xyz"))
        _RECALL.pop("org_offset_instance", None)
        if valid:
            _RECALL["org_offset_instance"] = {
                "path": path, "origin": [position[a] for a in "xyz"],
                "axes": [axes[a] for a in "xyz"]}
        return _measured("instance reads back at the requested local placement",
                         {"full_path": path, "position": position, "axes": axes}, valid)
    return check


def _instance_offset_world(p):
    """Compose the host's world pose with the refusal's local frame and compare assembly_get."""
    got = _RECALL.get("org_offset_instance") or {}
    rows = {r.get("full_path"): r for r in p.get("all_occurrences") or []}
    host, inst = rows.get("OrgDestination:1") or {}, rows.get(got.get("path")) or {}
    keys = ("origin", "x_axis", "y_axis", "z_axis")
    valid = (p.get("units") == "mm" and bool(got) and all(
        isinstance(r.get(k), list) and len(r[k]) == 3 and all(_num(v) for v in r[k])
        for r in (host, inst) for k in keys))
    if valid:
        basis = [host[k] for k in keys[1:]]
        def world(local):
            return [sum(local[j] * basis[j][i] for j in range(3)) for i in range(3)]
        want = [[h + w for h, w in zip(host["origin"], world(got["origin"]))]]
        want += [world(axis) for axis in got["axes"]]
        valid = all(_near(v, e, .01 if k == "origin" else .001)
                    for k, w in zip(keys, want) for v, e in zip(inst[k], w))
    return _measured("instance world pose equals host pose composed with the reply's local frame",
                     {"reply": got, "host": host, "instance": inst}, valid)


def _instance_unplaced(p):
    """An instance given no placement is ok, off the origin, and its note states the read position."""
    position, path = p.get("position") or {}, p.get("full_path") or ""
    xyz = [position.get(a) for a in "xyz"]
    sentence = ("No placement was requested; it reads at ({}, {}, {}) mm in the root component."
                .format(*xyz))
    valid = (p.get("created") is True and p.get("units") == "mm" and all(_num(v) for v in xyz)
             and path.startswith("OrgSource:") and path[len("OrgSource:"):].isdigit()
             and math.dist(xyz, [0, 0, 0]) > 1 and sentence in (p.get("note") or ""))
    _RECALL.pop("org_unplaced_instance", None)
    if valid:
        _RECALL["org_unplaced_instance"] = {"path": path, "origin": xyz,
                                            "axes": [(p.get("axes") or {}).get(a) for a in "xyz"]}
    return _measured("unplaced instance is ok and names its read position",
                     {"full_path": path, "position": position, "note": p.get("note")}, valid)


def _instance_unplaced_world(p):
    """assembly_get reads the unplaced instance at the reply's frame, the first occurrence's pose."""
    got = _RECALL.get("org_unplaced_instance") or {}
    rows = {r.get("full_path"): r for r in p.get("all_occurrences") or []}
    inst, first = rows.get(got.get("path")) or {}, rows.get("OrgSource:1") or {}
    keys = ("origin", "x_axis", "y_axis", "z_axis")
    want = [got.get("origin")] + list(got.get("axes") or [])
    valid = (p.get("units") == "mm" and bool(got) and len(want) == 4 and all(
        isinstance(r.get(k), list) and len(r[k]) == 3 and all(_num(v) for v in r[k])
        for r in (inst, first) for k in keys))
    if valid:
        valid = all(_near(v, e, .01 if k == "origin" else .001)
                    for k, w in zip(keys, want) for v, e in zip(inst[k], w))
        valid = valid and all(_near(v, e, .01 if k == "origin" else .001)
                              for k in keys for v, e in zip(inst[k], first[k]))
    return _measured("unplaced instance world pose equals the reply and the first occurrence",
                     {"reply": got, "instance": inst, "first": first}, valid)


def _body_organization_rows():
    """Exercise ownership transfers and output-handle consumers in owned documents."""
    rows = []

    def row(name, args, check="ok", save=None, write=False):
        def arguments(c):
            values = args(c) if callable(args) else dict(args)
            if name == "doc_get":
                values["max_results"] = 1000
            if write:
                values["expect_document"] = _ctx_get(c, "org_doc", "owned organization document")
            return values
        rows.append((name, arguments, check, save))

    def save(key, getter):
        return key, _recall(key, getter)

    def box(sketch, low, high, height):
        row("sketch_create", {"plane": "xy", "name": sketch}, write=True)
        row("sketch_add_geometry", {"sketch_name": sketch, "geometry": [
            {"kind": "rectangle", "x1": low[0], "y1": low[1],
             "x2": high[0], "y2": high[1]}]}, write=True)
        row("model_extrude", {"sketch_name": sketch, "distance": height}, _extruded, write=True)

    def vertices(target, check, capture=None):
        row("find_geometry", lambda c: {"target": target(c) if callable(target) else target,
            "kind": "vertex", "units": "mm", "max_results": 64}, check, capture)

    def source_ref(c):
        return "OrgSource:2:" + _ctx_get(c, "org_body_name", "selected body")

    for kind, mode, surface in (("brep", "parametric", False), ("mesh", "parametric", False),
                                ("brep", "direct", False), ("mesh", "direct", False),
                                ("brep", "parametric", True)):
        row("doc_get", {}, _home_document, save("org_home", _home_address))
        row("doc_new", lambda c: {"expect_document": _ctx_get(c, "org_home", "home")},
            _new_document, save("org_doc", lambda p: p["document_handle"]))
        row("doc_get", {}, lambda p: (p.get("active") or {}).get("document_handle") == _RECALL.get("org_doc"),
            save("org_body_name", lambda p, kind=kind: "OrgMesh" if kind == "mesh" else "Body1"))
        # The literal root selector resets the sweep layout cursor for this owned document.
        rows.append(("design_activate_component", {"occurrence": "root"}, "ok", None))
        if mode == "direct":
            row("design_set_mode", {"target": "direct", "confirm_history_loss": True},
                lambda p: p.get("now") == "direct", write=True)
        row("model_create_component", {"name": "OrgSource", "activate": True, "x": 40, "y": 20,
            "z": 10, "rotate_deg": 90, "rotate_axis": "z"}, _made_component, write=True)
        box("OrgPicked", (2, 3), (14, 11), 7)
        box("OrgSibling", (22, 3), (28, 10), 13)
        if surface:
            row("find_geometry", {"target": "OrgSource:1:Body1", "kind": "planar_face",
                "max_results": 1}, _matched(1, "planar_face"), _fg("org_face"))
            row("surface_offset", lambda c: {"faces": [_ctx_get(c, "org_face", "face")],
                "distance": 0, "chaining": False},
                lambda p: p.get("offset") is True and p.get("is_solid") is False
                and len(p.get("result_bodies") or []) == 1,
                save("org_body_name", lambda p: p["result_bodies"][0]), write=True)
        if kind == "mesh":
            row("save_as_mesh", {"body": "OrgSource:1:Body1", "name": "OrgMesh", "quality": "low"},
                lambda p: p.get("triangle_count") == 12 and p.get("name") == "OrgMesh", write=True)
            row("save_as_mesh", {"body": "OrgSource:1:Body2", "name": "OrgSiblingMesh", "quality": "low"},
                lambda p: p.get("triangle_count") == 12 and p.get("name") == "OrgSiblingMesh", write=True)
        row("design_activate_component", {"occurrence": "root"}, write=True)
        row("model_create_component", {"name": "OrgDestination", "activate": True,
            "x": -30, "y": 70, "z": 5, "rotate_deg": -30, "rotate_axis": "z"},
            _made_component, write=True)
        box("OrgSentinel", (0, 0), (4, 6), 9)
        if kind == "mesh":
            row("save_as_mesh", {"body": "OrgDestination:1:Body1",
                "name": "OrgSentinelMesh", "quality": "low"},
                lambda p: p.get("triangle_count") == 12 and p.get("name") == "OrgSentinelMesh", write=True)
        row("design_activate_component", {"occurrence": "root"}, write=True)
        row("model_create_component", {"name": "OrgExistingChild", "parent": "OrgDestination:1"},
            lambda p: _made_component_inactive(p)
            and p.get("full_path") == "OrgDestination:1+OrgExistingChild:1", write=True)
        row("design_add_instance", {"component": "OrgSource", "x": -50, "y": -20,
            "z": 30, "rotate_deg": -45, "rotate_axis": "z"},
            lambda p: p.get("full_path") == "OrgSource:2"
            and _instance_at("OrgSource:", (-50, -20, 30), -45)(p), write=True)
        row("design_add_instance", {"component": "OrgDestination", "x": 70, "y": -50,
            "z": 10, "rotate_deg": 60, "rotate_axis": "z"},
            lambda p: p.get("full_path") == "OrgDestination:2"
            and _instance_at("OrgDestination:", (70, -50, 10), 60)(p), write=True)
        vertices((source_ref if surface else "OrgSource:2:Body1"),
                 lambda p, surface=surface: len(_org_vertices(p)) == (4 if surface else 8),
                 save("org_before", _org_vertices))
        vertices("OrgSource:2:Body2", lambda p: len(_org_vertices(p)) == 8,
                 save("org_sibling", _org_vertices))
        vertices("OrgDestination:2:Body1", lambda p: len(_org_vertices(p)) == 8,
                 save("org_sentinel", _org_vertices))
        if kind == "brep" and mode == "parametric" and not surface:
            _nested_before = {"OrgSource:1": 2, "OrgSource:2": 2,
                              "OrgDestination:1": 1, "OrgDestination:2": 1,
                              "OrgDestination:1+OrgExistingChild:1": 0,
                              "OrgDestination:2+OrgExistingChild:1": 0}
            row("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                "tree_handles": True, "max_depth": 5, "max_results": 1000},
                _org_tree_counts(_nested_before),
                save("org_nested_history_before", lambda p: p["timeline"]))
            row("model_edit_body", lambda c: {"action": "move", "body": source_ref(c),
                "destination": "OrgDestination:2+OrgExistingChild:1"},
                _org_nested_move_result, save("org_nested_move", lambda p: p), write=True)
            row("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                "tree_handles": True, "max_depth": 5, "max_results": 1000},
                _org_tree_history({
                    "OrgSource:1": 1, "OrgSource:2": 1,
                    "OrgDestination:1": 1, "OrgDestination:2": 1,
                    "OrgDestination:1+OrgExistingChild:1": 1,
                    "OrgDestination:2+OrgExistingChild:1": 1}, 0,
                    "org_nested_history_before"),
                save("org_nested_history_after", lambda p: p["timeline"]))
            vertices("OrgDestination:2+OrgExistingChild:1:Body1",
                     _org_same_vertices("org_before"))
            vertices("OrgDestination:1+OrgExistingChild:1:Body1",
                     lambda p: _measured("second placed child has a complete world-vertex read",
                         _org_vertices(p), len(_org_vertices(p)) == 8))
            row("model_inspect", {"target": "OrgDestination:1+OrgExistingChild:1",
                "include": ["mass"], "units": "mm", "accuracy": "very_high"},
                _org_body_material(672, 472))
            row("model_inspect", {"target": "OrgDestination:2+OrgExistingChild:1",
                "include": ["mass"], "units": "mm", "accuracy": "very_high"},
                _org_body_material(672, 472))
            row("model_edit_body", lambda c: {"action": "move",
                "body": _ctx_get(c, "org_nested_move", "nested child body")["handle"],
                "destination": "root"}, _org_result("move", "brep", 1, 1),
                save("org_nested_root", lambda p: p), write=True)
            row("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                "tree_handles": True, "max_depth": 5, "max_results": 1000},
                _org_tree_history({
                    "OrgSource:1": 1, "OrgSource:2": 1,
                    "OrgDestination:1": 1, "OrgDestination:2": 1,
                    "OrgDestination:1+OrgExistingChild:1": 0,
                    "OrgDestination:2+OrgExistingChild:1": 0}, 1,
                    "org_nested_history_after"),
                save("org_nested_root_history", lambda p: p["timeline"]))
            vertices(lambda c: _ctx_get(c, "org_nested_root", "root control body")["handle"],
                     _org_same_vertices("org_before"))
            row("model_inspect", lambda c: {"target": _ctx_get(c, "org_nested_root",
                "root control body")["handle"], "include": ["mass"], "units": "mm",
                "accuracy": "very_high"}, _org_body_material(672, 472))
            row("model_edit_body", lambda c: {"action": "move",
                "body": _ctx_get(c, "org_nested_root", "root control body")["handle"],
                "destination": "OrgSource:2"}, _org_result("move", "brep", 1, 2),
                save("org_body_name", lambda p: p["body_name"]), write=True)
            row("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                "tree_handles": True, "max_depth": 5, "max_results": 1000},
                _org_tree_history({
                    "OrgSource:1": 2, "OrgSource:2": 2,
                    "OrgDestination:1": 1, "OrgDestination:2": 1,
                    "OrgDestination:1+OrgExistingChild:1": 0,
                    "OrgDestination:2+OrgExistingChild:1": 0}, 0,
                    "org_nested_root_history"))
        if kind == "mesh":
            row("model_inspect", {"target": "OrgSource:2:OrgMesh"}, _org_mesh_shape,
                save("org_mesh_selected_before", _org_mesh_snapshot))
            row("model_inspect", {"target": "OrgSource:2:OrgSiblingMesh"},
                lambda p: _org_mesh_box_shape(p, "org_sibling", 546.0, 422.0),
                save("org_mesh_sibling_before", _org_mesh_snapshot))
            row("model_inspect", {"target": "OrgDestination:2:OrgSentinelMesh"},
                lambda p: _org_mesh_box_shape(p, "org_sentinel", 216.0, 228.0),
                save("org_mesh_sentinel_before", _org_mesh_snapshot))
            row("mesh_get", {"target": "OrgSource:2"}, _org_mesh_count(2),
                save("org_mesh_source_before", lambda p: p))
            row("mesh_get", {"target": "OrgDestination:2"}, _org_mesh_count(1),
                save("org_mesh_destination_before", lambda p: p))
        row("model_edit_body", lambda c: {"action": "copy", "body": source_ref(c)},
            _refused("destination"), write=True)
        vertices((source_ref if kind == "brep" else "OrgSource:2:Body1"), _org_same_vertices("org_before"))
        if kind == "mesh":
            row("model_edit_body", lambda c: {"action": "copy", "body": source_ref(c),
                "destination": "OrgDestination:2"},
                _refused("Mesh copy", "OrgDestination:2", "component 'OrgDestination'",
                         "2 placements", "OrgDestination:1", "singly placed destination"), write=True)
            row("model_inspect", {"target": "OrgSource:2:OrgMesh"},
                _org_mesh_unchanged("org_mesh_selected_before"))
            row("model_inspect", {"target": "OrgSource:2:OrgSiblingMesh"},
                _org_mesh_unchanged("org_mesh_sibling_before"))
            row("model_inspect", {"target": "OrgDestination:2:OrgSentinelMesh"},
                _org_mesh_unchanged("org_mesh_sentinel_before"))
            row("mesh_get", {"target": "OrgSource:2"},
                _org_mesh_inventory_unchanged("org_mesh_source_before"))
            row("mesh_get", {"target": "OrgDestination:2"},
                _org_mesh_inventory_unchanged("org_mesh_destination_before"))
            row("design_activate_component", {"occurrence": "root"}, write=True)
            row("model_create_component", {"name": "OrgMeshLanding", "activate": True,
                "x": 110, "y": 40, "z": 15, "rotate_deg": -15, "rotate_axis": "z"},
                _made_component, write=True)
            box("OrgLandingSentinel", (0, 0), (4, 6), 9)
            row("save_as_mesh", {"body": "OrgMeshLanding:1:Body1",
                "name": "OrgLandingSentinelMesh", "quality": "low"},
                lambda p: p.get("triangle_count") == 12
                and p.get("name") == "OrgLandingSentinelMesh", write=True)
            row("design_activate_component", {"occurrence": "root"}, write=True)
            vertices("OrgMeshLanding:1:Body1", lambda p: len(_org_vertices(p)) == 8,
                     save("org_landing_sentinel", _org_vertices))
            row("model_inspect", {"target": "OrgMeshLanding:1:OrgLandingSentinelMesh"},
                lambda p: _org_mesh_box_shape(p, "org_landing_sentinel", 216.0, 228.0))
            row("mesh_get", {"target": "OrgMeshLanding:1"}, _org_mesh_count(1))
        landing = "OrgMeshLanding:1" if kind == "mesh" else "OrgDestination:2"
        row("model_edit_body", lambda c, landing=landing: {"action": "copy", "body": source_ref(c),
            "destination": landing}, _org_result("copy", kind, 3 if surface else 2, 2),
            save("org_copy", lambda p: p), write=True)
        if kind == "brep":
            vertices(lambda c: _ctx_get(c, "org_copy", "copy")["handle"], _org_same_vertices("org_before"))
            row("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                "max_depth": 4}, _org_tree_counts({"OrgSource:1": 3 if surface else 2,
                                                  "OrgSource:2": 3 if surface else 2,
                                                  "OrgDestination:1": 2, "OrgDestination:2": 2}))
        else:
            row("model_inspect", lambda c: {"target": _ctx_get(c, "org_copy", "copy")["handle"]},
                _org_mesh_shape, save("org_mesh_copy_before", _org_mesh_snapshot))
            row("mesh_get", {"target": "OrgSource:2"}, _org_mesh_count(2))
            row("mesh_get", {"target": landing}, _org_mesh_count(2),
                save("org_mesh_landing_after_copy", lambda p: p))
            row("mesh_get", {"target": "OrgDestination:2"}, _org_mesh_count(1))
        if kind == "mesh" and mode == "direct":
            row("design_get", {"include": ["tree"], "tree_bodies": True,
                "tree_handles": True, "max_depth": 4},
                _org_tree_counts({"OrgMeshLanding:1": 1},
                                 no_children_of=("OrgMeshLanding:1",)))
            row("model_edit_body", lambda c: {"action": "create_component",
                "body": _ctx_get(c, "org_copy", "copy")["handle"]},
                _refused("Direct mesh create_component", "OrgMeshLanding:1",
                         "component 'OrgMeshLanding'", "nonidentity transforms",
                         "mesh in root", "identity-placed component"), write=True)
            row("model_inspect", lambda c: {"target": _ctx_get(c, "org_copy", "copy")["handle"]},
                _org_mesh_unchanged("org_mesh_copy_before"))
            row("model_inspect", {"target": "OrgSource:2:OrgMesh"},
                _org_mesh_unchanged("org_mesh_selected_before"))
            row("model_inspect", {"target": "OrgSource:2:OrgSiblingMesh"},
                _org_mesh_unchanged("org_mesh_sibling_before"))
            row("model_inspect", {"target": "OrgDestination:2:OrgSentinelMesh"},
                _org_mesh_unchanged("org_mesh_sentinel_before"))
            row("model_inspect", {"target": "OrgMeshLanding:1:OrgLandingSentinelMesh"},
                lambda p: _org_mesh_box_shape(p, "org_landing_sentinel", 216.0, 228.0))
            row("mesh_get", {"target": "OrgSource:2"},
                _org_mesh_inventory_unchanged("org_mesh_source_before"))
            row("mesh_get", {"target": "OrgDestination:2"},
                _org_mesh_inventory_unchanged("org_mesh_destination_before"))
            row("mesh_get", {"target": landing},
                _org_mesh_inventory_unchanged("org_mesh_landing_after_copy"))
            row("design_get", {"include": ["tree"], "tree_bodies": True,
                "tree_handles": True, "max_depth": 4},
                _org_tree_counts({"OrgMeshLanding:1": 1},
                                 no_children_of=("OrgMeshLanding:1",)))
            row("model_edit_body", lambda c: {"action": "move",
                "body": _ctx_get(c, "org_copy", "copy")["handle"], "destination": "root"},
                _org_result("move", "mesh", 2, 1), save("org_first_root", lambda p: p), write=True)
            row("model_inspect", lambda c: {"target": _ctx_get(c, "org_first_root", "root mesh")["handle"]},
                _org_mesh_shape)
            row("mesh_get", {"target": landing}, _org_mesh_count(1))
            row("mesh_get", {}, _org_mesh_count(5))
            row("model_edit_body", lambda c: {"action": "create_component",
                "body": _ctx_get(c, "org_first_root", "root mesh")["handle"]},
                _org_result("create_component", "mesh", 1, 1),
                save("org_first_child", lambda p: p), write=True)
            row("model_inspect", lambda c: {"target": _ctx_get(c, "org_first_child", "root child")["handle"]},
                _org_mesh_shape)
            row("mesh_get", lambda c: {"target": _ctx_get(c, "org_first_child", "root child")["full_path"]},
                _org_mesh_count(1))
            row("model_edit_body", lambda c: {"action": "create_component",
                "body": _ctx_get(c, "org_first_child", "root child")["handle"]},
                _org_result("create_component", "mesh", 1, 1),
                save("org_child", lambda p: p), write=True)
        else:
            row("model_edit_body", lambda c: {"action": "create_component",
                "body": _ctx_get(c, "org_copy", "copy")["handle"]},
                _org_result("create_component", kind, 2, 1), save("org_child", lambda p: p), write=True)
        row("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True, "max_depth": 4},
            _org_tree_counts({"OrgDestination:1+OrgExistingChild:1": 0,
                              "OrgDestination:2+OrgExistingChild:1": 0}))
        if kind == "brep":
            vertices(lambda c: _ctx_get(c, "org_child", "child")["handle"], _org_same_vertices("org_before"))
            row("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                "max_depth": 4}, _org_tree_counts(lambda surface=surface: {
                    "OrgSource:1": 3 if surface else 2, "OrgSource:2": 3 if surface else 2,
                    "OrgDestination:1": 1, "OrgDestination:2": 1,
                    _RECALL["org_child"]["full_path"]: 1}))
        else:
            row("model_inspect", lambda c: {"target": _ctx_get(c, "org_child", "child")["handle"]},
                _org_mesh_shape)
            row("mesh_get", lambda c: {"target": _ctx_get(c, "org_child", "child")["full_path"]},
                _org_mesh_count(1))
            row("mesh_get", {"target": landing}, _org_mesh_count(1))
            row("mesh_get", {"target": "OrgDestination:2"}, _org_mesh_count(1))
        row("model_edit_body", lambda c: {"action": "move",
            "body": _ctx_get(c, "org_child", "new child")["handle"], "destination": "root"},
            _org_result("move", kind, 1, 1), save("org_root", lambda p: p), write=True)
        if kind == "brep":
            vertices(lambda c: _ctx_get(c, "org_root", "root body")["handle"], _org_same_vertices("org_before"))
            row("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                "max_depth": 4}, _org_tree_counts(lambda surface=surface: {
                    "OrgSource:1": 3 if surface else 2, "OrgSource:2": 3 if surface else 2,
                    "OrgDestination:1": 1, "OrgDestination:2": 1,
                    _RECALL["org_child"]["full_path"]: 0}, root_count=1))
            row("model_move", lambda c: {"bodies": [_ctx_get(c, "org_root", "root body")["handle"]],
                "dx": 1, "units": "mm"}, _moved, write=True)
            vertices(lambda c: _ctx_get(c, "org_root", "root body")["handle"], _org_translated_vertices)
        else:
            row("model_inspect", lambda c: {"target": _ctx_get(c, "org_root", "root mesh")["handle"]},
                _org_mesh_shape)
            row("mesh_get", lambda c: {"target": _ctx_get(c, "org_child", "child")["full_path"]},
                _org_mesh_count(0))
            row("mesh_get", {}, _org_mesh_count(5))
            row("mesh_to_brep", lambda c: {"mesh": _ctx_get(c, "org_root", "root mesh")["handle"],
                "method": "faceted"}, lambda p: p.get("converted") is True
                and len(p.get("brep_bodies") or []) == 1,
                save("org_converted", lambda p: p["brep_bodies"][0]["handle"]), write=True)
            vertices(lambda c: _ctx_get(c, "org_converted", "converted body"), _org_same_vertices("org_before"))
        vertices("OrgSource:2:Body2", _org_same_vertices("org_sibling"))
        vertices("OrgDestination:2:Body1", _org_same_vertices("org_sentinel"))
        if kind == "mesh":
            row("model_inspect", {"target": "OrgSource:2:OrgMesh"},
                _org_mesh_unchanged("org_mesh_selected_before"))
            row("model_inspect", {"target": "OrgSource:2:OrgSiblingMesh"},
                _org_mesh_unchanged("org_mesh_sibling_before"))
            row("model_inspect", {"target": "OrgDestination:2:OrgSentinelMesh"},
                _org_mesh_unchanged("org_mesh_sentinel_before"))
            row("model_inspect", {"target": "OrgMeshLanding:1:OrgLandingSentinelMesh"},
                lambda p: _org_mesh_box_shape(p, "org_landing_sentinel", 216.0, 228.0))
        if kind == "brep" and mode == "parametric" and not surface:
            # An already-placed component instanced into a rotated non-root host: the row requires
            # the requested local frame, then composes it with the host's world pose.
            row("design_add_instance", {"component": "OrgSource", "into_component": "OrgDestination:1",
                "rotate_deg": 180, "rotate_axis": "z"},
                _instance_at("OrgDestination:1+OrgSource:", (0, 0, 0), 180), write=True)
            row("assembly_get", {"include": ["all_occurrences", "poses"], "units": "mm",
                "max_all_occurrences": 100}, _instance_offset_world)
            # No placement given: the instance is ok where Fusion put it, on the first occurrence.
            row("design_add_instance", {"component": "OrgSource"}, _instance_unplaced, write=True)
            row("assembly_get", {"include": ["all_occurrences", "poses"], "units": "mm",
                "max_all_occurrences": 100}, _instance_unplaced_world)
        row("doc_close", lambda c: {"name": _ctx_get(c, "org_doc", "owned document"),
            "save_changes": False}, _document_closed, write=True)
        row("doc_activate", lambda c: {"name": _ctx_get(c, "org_home", "home")},
            lambda p: p.get("activated") is True)
        row("doc_get", {}, lambda p: (p.get("active") or {}).get("document_handle") == _RECALL.get("org_home"))

    for kind in ("brep", "mesh"):
        row("doc_get", {}, _home_document, save("org_home", _home_address))
        row("doc_new", lambda c: {"expect_document": _ctx_get(c, "org_home", "home")},
            _new_document, save("org_doc", lambda p: p["document_handle"]))
        rows.append(("design_activate_component", {"occurrence": "root"}, "ok", None))
        row("model_create_component", {"name": "OrgSameSource", "activate": True,
            "x": 40, "y": 20, "z": 10, "rotate_deg": 90, "rotate_axis": "z"},
            _made_component, write=True)
        box("OrgSamePicked", (2, 3), (14, 11), 7)
        box("OrgSameSibling", (22, 3), (28, 10), 13)
        if kind == "mesh":
            row("save_as_mesh", {"body": "OrgSameSource:1:Body1", "name": "OrgSameMesh",
                "quality": "low"}, lambda p: p.get("triangle_count") == 12
                and p.get("name") == "OrgSameMesh", write=True)
            row("save_as_mesh", {"body": "OrgSameSource:1:Body2", "name": "OrgSameSiblingMesh",
                "quality": "low"}, lambda p: p.get("triangle_count") == 12
                and p.get("name") == "OrgSameSiblingMesh", write=True)
        row("design_activate_component", {"occurrence": "root"}, write=True)
        vertices("OrgSameSource:1:Body1", lambda p: len(_org_vertices(p)) == 8,
                 save("org_before", _org_vertices))
        vertices("OrgSameSource:1:Body2", lambda p: len(_org_vertices(p)) == 8,
                 save("org_same_sibling", _org_vertices))
        same_ref = "OrgSameSource:1:OrgSameMesh" if kind == "mesh" else "OrgSameSource:1:Body1"
        if kind == "mesh":
            row("mesh_get", {"target": "OrgSameSource:1"}, _org_mesh_count(2),
                save("org_same_mesh_rows", lambda p: p["meshes"]))
            row("model_inspect", {"target": same_ref}, _org_mesh_shape)
            row("model_inspect", {"target": "OrgSameSource:1:OrgSameSiblingMesh"},
                _org_same_mesh_sibling)
        else:
            row("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                "max_depth": 3}, _org_tree_counts({"OrgSameSource:1": 2}))
        row("design_get", {"include": ["timeline"], "max_results": 1000}, "ok",
            save("org_same_history", lambda p: p["timeline"]))
        row("model_edit_body", {"action": "move", "body": same_ref,
            "destination": "OrgSameSource:1"},
            _refused("Cannot copy the body" if kind == "brep" else "bodyPaths.size() == 1"),
            write=True)
        row("design_get", {"include": ["timeline"], "max_results": 1000},
            lambda p: _org_same_timeline(p, False))
        if kind == "mesh":
            row("mesh_get", {"target": "OrgSameSource:1"},
                lambda p: _org_same_mesh_inventory(p, 2))
            row("model_inspect", {"target": same_ref}, _org_mesh_shape)
            row("model_inspect", {"target": "OrgSameSource:1:OrgSameSiblingMesh"},
                _org_same_mesh_sibling)
        else:
            vertices(same_ref, _org_same_vertices("org_before"))
            row("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                "max_depth": 3}, _org_tree_counts({"OrgSameSource:1": 2}))
        vertices("OrgSameSource:1:Body2", _org_same_vertices("org_same_sibling"))
        row("model_edit_body", {"action": "copy", "body": same_ref,
            "destination": "OrgSameSource:1"}, _org_same_copy_result(kind),
            save("org_same_copy", lambda p: p), write=True)
        row("design_get", {"include": ["timeline"], "max_results": 1000},
            lambda p: _org_same_timeline(p, True))
        if kind == "mesh":
            row("model_inspect", lambda c: {"target": _ctx_get(c, "org_same_copy", "copied mesh")["handle"]},
                _org_same_mesh_copy, save("org_same_copied_name", lambda p: p["name"]))
            row("mesh_get", {"target": "OrgSameSource:1"},
                lambda p: _org_same_mesh_inventory(p, 3))
            row("model_inspect", {"target": same_ref}, _org_mesh_shape)
            row("model_inspect", {"target": "OrgSameSource:1:OrgSameSiblingMesh"},
                _org_same_mesh_sibling)
        else:
            vertices(lambda c: _ctx_get(c, "org_same_copy", "copied body")["handle"],
                     _org_same_vertices("org_before"))
            row("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                "max_depth": 3}, _org_tree_counts({"OrgSameSource:1": 3}))
            row("model_move", lambda c: {"bodies": [_ctx_get(c, "org_same_copy", "copied body")["handle"]],
                "dx": 1, "units": "mm"}, _moved, write=True)
            vertices(lambda c: _ctx_get(c, "org_same_copy", "copied body")["handle"],
                     _org_translated_vertices)
            vertices(same_ref, _org_same_vertices("org_before"))
        vertices("OrgSameSource:1:Body2", _org_same_vertices("org_same_sibling"))
        row("doc_close", lambda c: {"name": _ctx_get(c, "org_doc", "same-owner document"),
            "save_changes": False}, _document_closed, write=True)
        row("doc_activate", lambda c: {"name": _ctx_get(c, "org_home", "home")},
            lambda p: p.get("activated") is True)
        row("doc_get", {}, lambda p: (p.get("active") or {}).get("document_handle") == _RECALL.get("org_home"))

    row("doc_get", {}, _home_document, save("org_home", _home_address))
    row("doc_new", lambda c: {"expect_document": _ctx_get(c, "org_home", "home")},
        _new_document, save("org_doc", lambda p: p["document_handle"]))
    rows.append(("design_activate_component", {"occurrence": "root"}, "ok", None))
    row("model_create_component", {"name": "OrgSphere", "activate": True,
        "x": 40, "y": 20, "z": 10, "rotate_deg": 90, "rotate_axis": "z"},
        _made_component, write=True)
    row("sketch_create", {"plane": "xy", "name": "OrgSphereProfile"}, write=True)
    row("sketch_add_geometry", {"sketch_name": "OrgSphereProfile", "geometry": [
        {"kind": "arc", "cx": 0, "cy": 0, "x1": 0, "y1": 6, "sweep_deg": 180},
        {"kind": "line", "x1": 0, "y1": -6, "x2": 0, "y2": 6}]}, write=True)
    row("model_revolve", {"sketch_name": "OrgSphereProfile", "axis": "y", "angle_deg": 360},
        lambda p: p.get("revolved") is True and len(p.get("result_bodies") or []) == 1,
        save("org_sphere_body", lambda p: "OrgSphere:1:" + p["result_bodies"][0]), write=True)
    row("design_activate_component", {"occurrence": "root"}, write=True)
    row("model_create_component", {"name": "OrgSphereDestination", "activate": True,
        "x": -30, "y": 70, "z": 5, "rotate_deg": -30, "rotate_axis": "z"},
        _made_component, write=True)
    row("model_inspect", lambda c: {"target": _ctx_get(c, "org_sphere_body", "sphere"),
        "include": ["mass"], "units": "mm", "accuracy": "very_high"}, _org_sphere_mass)
    row("find_geometry", lambda c: {"target": _ctx_get(c, "org_sphere_body", "sphere"),
        "kind": "vertex", "units": "mm", "max_results": 64},
        lambda p: p.get("truncated") is not True
        and p.get("match_count") == len(p.get("matches") or []),
        save("org_sphere_vertex_count", lambda p: p["match_count"]))
    for action, input_key, output_key, destination in (
            ("copy", "org_sphere_body", "org_sphere_copy", "OrgSphereDestination:1"),
            ("create_component", "org_sphere_copy", "org_sphere_child", None),
            ("move", "org_sphere_child", "org_sphere_root", "root")):
        def sphere_args(c, action=action, input_key=input_key, destination=destination):
            value = _ctx_get(c, input_key, "sphere target")
            args = {"action": action, "body": value if isinstance(value, str) else value["handle"]}
            if destination is not None:
                args["destination"] = destination
            return args
        row("model_edit_body", sphere_args, _org_result(action, "brep", 1, 1),
            save(output_key, lambda p: p), write=True)
        row("model_inspect", lambda c, key=output_key: {
            "target": _ctx_get(c, key, "organized sphere")["handle"],
            "include": ["mass"], "units": "mm", "accuracy": "very_high"}, _org_sphere_mass)
        row("find_geometry", lambda c, key=output_key: {
            "target": _ctx_get(c, key, "organized sphere")["handle"],
            "kind": "sphere_face", "units": "mm", "max_results": 8},
            _matched(1, "sphere_face"))
    row("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True, "max_depth": 4},
        _org_tree_counts(lambda: {"OrgSphere:1": 1, "OrgSphereDestination:1": 0,
                                 _RECALL["org_sphere_child"]["full_path"]: 0}, root_count=1))
    row("doc_close", lambda c: {"name": _ctx_get(c, "org_doc", "sphere document"),
        "save_changes": False}, _document_closed, write=True)
    row("doc_activate", lambda c: {"name": _ctx_get(c, "org_home", "home")},
        lambda p: p.get("activated") is True)
    row("doc_get", {}, lambda p: (p.get("active") or {}).get("document_handle") == _RECALL.get("org_home"))
    return rows


def _d_merge_native_script(target, witness):
    """Return direct native material/vertex and optional history evidence for the two solids."""
    return f'''import adsk.core, adsk.fusion, json
def run(context):
    app=adsk.core.Application.get()
    d=adsk.fusion.Design.cast(app.activeProduct)
    c=d.rootComponent
    def pt(p): return [round(p.x*10,9),round(p.y*10,9),round(p.z*10,9)]
    def body(name):
        b=c.bRepBodies.itemByName(name)
        return {{"name":b.name,"solid":b.isSolid,
            "face_count":b.faces.count,"volume_cm3":round(b.volume,12),
            "area_cm2":round(b.physicalProperties.area,12),
            "bounds_mm":[pt(b.boundingBox.minPoint),pt(b.boundingBox.maxPoint)],
            "vertices_mm":sorted(pt(v.geometry) for v in b.vertices),
            "face_areas_cm2":sorted(round(f.area,12) for f in b.faces)}}
    record={{"design_type":int(d.designType),"body_names":sorted(b.name for b in c.bRepBodies),
            "target":body({target!r}),
            "witness":body({witness!r})}}
    if d.designType==adsk.fusion.DesignTypes.ParametricDesignType:
        record["timeline"]=[{{"name":o.name,"type":o.entity.objectType,"health":int(o.healthState)}}
            for o in d.timeline]
        record["marker"]=d.timeline.markerPosition
    print(json.dumps(record))
'''


def _d_merge_snapshot(key, stage):
    """Compare public refusal and direct merge with independent native material and identity reads."""
    def check(p):
        old = _RECALL.get(key)
        valid = isinstance(old, dict) and isinstance(p.get("target"), dict)
        if stage == "unchanged":
            valid = valid and p == old
        elif stage == "direct_baseline":
            target = p.get("target") or {}
            prior = _RECALL.get("d_merge_parametric") or {}
            valid = (valid and p.get("design_type") != old.get("design_type")
                     and p.get("body_names") == ["Body1", "Body2"]
                     and target.get("face_count") == 7
                     and _near(target.get("volume_cm3"), 8, 1e-9)
                     and _near(target.get("area_cm2"), 24, 1e-9)
                     and target.get("face_areas_cm2") == [2.0, 2.0, 4.0, 4.0, 4.0, 4.0, 4.0]
                     and target.get("bounds_mm") == [[40.0, 0.0, 0.0], [60.0, 20.0, 20.0]]
                     and p.get("witness") == prior.get("witness"))
        elif stage == "merged":
            target, witness = p.get("target") or {}, p.get("witness") or {}
            expected_vertices = sorted([[x, y, z] for x in (40.0, 60.0)
                                        for y in (0.0, 20.0) for z in (0.0, 20.0)])
            valid = (valid and p.get("design_type") == old.get("design_type")
                     and p.get("body_names") == ["Body1", "Body2"]
                     and target.get("face_count") == 6 and target.get("solid") is True
                     and _near(target.get("volume_cm3"), 8, 1e-9)
                     and _near(target.get("area_cm2"), 24, 1e-9)
                     and target.get("bounds_mm") == [[40.0, 0.0, 0.0], [60.0, 20.0, 20.0]]
                     and target.get("face_areas_cm2") == [4.0] * 6
                     and target.get("vertices_mm") == expected_vertices
                     and witness == old.get("witness"))
        return _measured("native direct merge " + stage, {"before": old, "after": p}, valid)
    return check


def _d_merge_split_face(p):
    """Select the single intact top face before the measured split."""
    matches = p.get("matches") or []
    top = [m for m in matches if isinstance(m.get("normal"), list)
           and len(m["normal"]) == 3 and m["normal"][2] > 0.999
           and isinstance(m.get("position"), list) and len(m["position"]) == 3
           and abs(m["position"][2] - 20) < 0.001]
    good = (len(top) == 1 and top[0].get("kind") == "planar_face"
            and top[0].get("handle") and _near(top[0].get("area"), 400, 0.001)
            and abs(top[0]["position"][0] - 50) < 0.001)
    return _measured("one intact top face before split", {
        "matches": len(matches), "top": [(m.get("position"), m.get("area")) for m in top]}, good)


def _d_merge_top_pair(p):
    """Select only the two measured upper planar faces split at x=50 mm."""
    matches = p.get("matches") or []
    top = [m for m in matches if isinstance(m.get("normal"), list)
           and len(m["normal"]) == 3 and m["normal"][2] > 0.999
           and isinstance(m.get("position"), list) and len(m["position"]) == 3
           and abs(m["position"][2] - 20) < 0.001]
    top.sort(key=lambda m: m["position"][0])
    good = (len(top) == 2 and all(m.get("kind") == "planar_face" and m.get("handle")
            and _near(m.get("area"), 200, 0.001) for m in top)
            and abs(top[0]["position"][0] - 45) < 0.001
            and abs(top[1]["position"][0] - 55) < 0.001)
    return _measured("two current top faces on either side of the split", {
        "matches": len(matches), "selected": [(m.get("position"), m.get("area")) for m in top]}, good)


def _d_merge_succeeded(p):
    """Check the public edit reports a one-face merge and retained material."""
    return _measured("public direct face merge", p, p.get("action") == "merge_faces"
        and p.get("faces_before") == 7 and p.get("faces_after") == 6
        and p.get("material_kept") is True and _near(p.get("volume_cm3"), 8, 1e-9)
        and _near(p.get("area_cm2"), 24, 1e-9) and bool(p.get("handle")))


def _merge_face_rows():
    """Exercise parametric no-op refusal and measured direct-design merge in a disposable doc."""
    rows = [
        ("doc_get", {}, _d_home_capture("d_merge_home_census"),
         ("d_merge_home", _home_address)),
        ("doc_new", lambda c: {"expect_document": _ctx_get(c, "d_merge_home", "home")},
         _new_document, ("d_merge_doc", _d_merge_new_doc)),
    ]

    def row(name, args, check="ok", save=None, write=True):
        def arguments(c):
            values = args(c) if callable(args) else dict(args)
            if write:
                values = _combine_pin(c, "d_merge_doc", values)
            return values
        rows.append((name, arguments, check, save))

    def native_script(c):
        return _d_merge_native_script(_ctx_get(c, "d_merge_target", "split cube"),
                                      _ctx_get(c, "d_merge_witness", "witness solid"))

    for name, x in (("DMergeTarget", 40), ("DMergeWitness", 100)):
        row("sketch_create", {"name": name, "plane": "xy"})
        row("sketch_add_geometry", {"sketch_name": name, "units": "mm", "geometry": [
            {"kind": "rectangle", "x1": x, "y1": 0, "x2": x + 20, "y2": 20}]})
        row("model_extrude", {"sketch_name": name, "distance": 20, "units": "mm",
                               "operation": "new"}, _extruded,
            ("d_merge_target" if name == "DMergeTarget" else "d_merge_witness",
             lambda p: p["result_bodies"][0]))
    row("model_construction", {"kind": "plane", "mode": "offset", "plane": "yz",
        "offset": 50, "units": "mm", "name": "DMergeSplitPlane"})
    row("find_geometry", lambda c: {"target": _ctx_get(c, "d_merge_target", "target cube"),
        "kind": "planar_face", "units": "mm", "max_results": 12},
        _d_merge_split_face, ("d_merge_split_face", _recall("d_merge_split_face",
            lambda p: next(m["handle"] for m in p["matches"]
                if m.get("normal", [0, 0, 0])[2] > 0.999
                and abs(m.get("position", [0, 0, 0])[2] - 20) < 0.001))), write=False)
    def split_args(c):
        return {"split": "face", "faces": [_ctx_get(c, "d_merge_split_face", "intact top face")],
                "split_plane": "DMergeSplitPlane", "extend_tool": True}
    row("model_split", split_args, lambda p: p.get("split") == "face"
        and p.get("result_count") == 1 and bool(p.get("feature")))
    row("find_geometry", lambda c: {"target": _ctx_get(c, "d_merge_target", "target cube"),
        "kind": "planar_face", "units": "mm", "max_results": 12},
        _d_merge_top_pair, ("d_merge_top_faces", _recall("d_merge_top_faces",
            lambda p: [m["handle"] for m in sorted((m for m in p["matches"]
                if m.get("normal", [0, 0, 0])[2] > 0.999
                and abs(m.get("position", [0, 0, 0])[2] - 20) < 0.001),
                key=lambda m: m["position"][0])])), write=False)

    def capture(stage):
        return ("sys_execute_script", lambda c: _combine_pin(c, "d_merge_doc", {
            "script": native_script(c), "read_only": True}), _d_merge_capture(stage),
            ("d_merge_parametric" if stage == "parametric" else "d_merge_direct",
             _recall("d_merge_parametric" if stage == "parametric" else "d_merge_direct",
                     lambda p: p)))
    rows.append(capture("parametric"))
    row("model_edit_body", lambda c: {"action": "merge_faces",
        "faces": _ctx_get(c, "d_merge_top_faces", "top face pair")},
        _refused("Face merge requires a direct design", "current design history is unchanged",
                 "separate direct-design copy"))
    rows.append(("sys_execute_script", lambda c: _combine_pin(c, "d_merge_doc", {
        "script": native_script(c), "read_only": True}),
        _d_merge_snapshot("d_merge_parametric", "unchanged"), None))
    convert = '''import adsk.core, adsk.fusion, json
def run(context):
    app=adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    d=adsk.fusion.Design.cast(app.activeProduct)
    d.designType=adsk.fusion.DesignTypes.DirectDesignType
    print(json.dumps({"direct":d.designType==adsk.fusion.DesignTypes.DirectDesignType}))
'''
    row("sys_execute_script", {"script": convert, "read_only": False},
        lambda p: _measured("owned design entered direct mode", p, p.get("direct") is True))
    rows.append(("sys_execute_script", lambda c: _combine_pin(c, "d_merge_doc", {
        "script": native_script(c), "read_only": True}), _d_merge_capture("direct_baseline"),
        ("d_merge_direct", _recall("d_merge_direct", lambda p: p))))
    row("find_geometry", lambda c: {"target": _ctx_get(c, "d_merge_target", "target cube"),
        "kind": "planar_face", "units": "mm", "max_results": 12},
        _d_merge_top_pair, ("d_merge_direct_faces", _recall("d_merge_direct_faces",
            lambda p: [m["handle"] for m in sorted((m for m in p["matches"]
                if m.get("normal", [0, 0, 0])[2] > 0.999
                and abs(m.get("position", [0, 0, 0])[2] - 20) < 0.001),
                key=lambda m: m["position"][0])])), write=False)
    row("model_edit_body", lambda c: {"action": "merge_faces",
        "faces": _ctx_get(c, "d_merge_direct_faces", "fresh direct top face pair")},
        _d_merge_succeeded, ("d_merge_reply", _recall("d_merge_reply", lambda p: p)))
    rows.append(("sys_execute_script", lambda c: _combine_pin(c, "d_merge_doc", {
        "script": native_script(c), "read_only": True}),
        _d_merge_snapshot("d_merge_direct", "merged"), None))
    rows.extend([
        ("doc_activate", lambda c: {"name": _ctx_get(c, "d_merge_home", "home"),
            "expect_document": _ctx_get(c, "d_merge_doc", "merge scratch")}, "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "d_merge_doc", "merge scratch"),
            "save_changes": False, "expect_document": _ctx_get(c, "d_merge_home", "home")},
         _document_closed, None),
        ("doc_get", {}, _d_home_same("d_merge_home_census"), None),
    ])
    return rows


def _d_merge_capture(stage):
    """Capture a measured mode baseline before the native state comparisons."""
    def check(p):
        target = p.get("target") or {}
        witness = p.get("witness") or {}
        valid = (target.get("name") == "Body1" and witness.get("name") == "Body2"
                 and p.get("body_names") == ["Body1", "Body2"]
                 and target.get("face_count") == 7 and witness.get("face_count") == 6
                 and _near(target.get("volume_cm3"), 8, 1e-9)
                 and _near(target.get("area_cm2"), 24, 1e-9)
                 and target.get("face_areas_cm2") == [2.0, 2.0, 4.0, 4.0, 4.0, 4.0, 4.0]
                 and _near(witness.get("volume_cm3"), 8, 1e-9)
                 and target.get("bounds_mm") == [[40.0, 0.0, 0.0], [60.0, 20.0, 20.0]]
                 and len(witness.get("vertices_mm") or []) == 8)
        if stage == "parametric":
            valid = valid and "timeline" in p and len(p["timeline"]) > 0
        else:
            prior = _RECALL.get("d_merge_parametric") or {}
            valid = (valid and "timeline" not in p
                     and p.get("design_type") != prior.get("design_type")
                     and p.get("body_names") == ["Body1", "Body2"]
                     and p.get("witness") == prior.get("witness"))
        return _measured("native merge fixture " + stage, p, valid)
    return check


def _d_home_same(key):
    """Require cleanup to restore the original active document handle."""
    def check(p):
        before = _RECALL.get(key) or {}
        return _measured("original active document restored", {
            "expected": before, "actual": _d_home_signature(p)},
            bool(before) and _d_home_signature(p) == before)
    return check


def _d_home_capture(key):
    """Capture the active document and complete open-document census before scratch creation."""
    def check(p):
        valid = _home_document(p)
        if valid:
            _RECALL[key] = _d_home_signature(p)
        return valid
    return check


def _d_home_signature(p):
    """The active handle and complete open-document identities."""
    active = p.get("active") or {}
    return {"active": active.get("document_handle"), "open_count": p.get("open_count"),
            "documents": sorted(r["document_handle"] for r in p.get("open_documents", []))}


def _d_merge_new_doc(p):
    """Clear cached merge handles and reads before retaining the new scratch document."""
    for key in ("d_merge_target", "d_merge_witness", "d_merge_split_face", "d_merge_top_faces",
                "d_merge_direct_faces", "d_merge_parametric", "d_merge_direct", "d_merge_reply"):
        _RECALL.pop(key, None)
    return p["document_handle"]


_BODY_ORGANIZATION = _body_organization_rows()
_BODY_ORGANIZATION += _merge_face_rows()


def _w2_directional_split_rows():
    """Prove the tilted split lands at x=30 mm and preserves stock and control solids."""
    key = "w2_vector_split"
    rows = [("doc_get", {}, _home_document, (key + "_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, key + "_home", "home")},
             _new_document, (key + "_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(c, key + "_doc",
            args(c) if callable(args) else args), check, save))

    rows.append(("design_activate_component", lambda c: _combine_pin(c, key + "_doc",
        {"occurrence": "root"}), "ok", None))

    def rectangle(name, x, y, width, height):
        write("sketch_create", {"name": name, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name, "units": "mm", "geometry": [{
            "kind": "rectangle", "x1": x, "y1": y, "x2": x + width, "y2": y + height}]})

    def retain_face(p):
        hits = [m for m in p.get("matches", []) if m.get("kind") == "planar_face"
                and m.get("handle") and _near(m.get("area"), 1600, .001)
                and _near((m.get("position") or [0, 0, 0])[2], 20, .001)
                and _near((m.get("normal") or [0, 0, 0])[2], 1, .001)]
        if len(hits) == 1:
            _RECALL[key + "_face"] = hits[0]["handle"]
        return _measured("unique 1600 mm2 top face", hits, len(hits) == 1)

    rectangle("W2SplitTargetS", 0, 0, 40, 40)
    write("model_extrude", {"sketch_name": "W2SplitTargetS", "distance": 20, "units": "mm"},
          _extruded, (key + "_target", lambda p: p["result_bodies"][0]))
    rectangle("W2SplitControlS", 60, 0, 20, 20)
    write("model_extrude", {"sketch_name": "W2SplitControlS", "distance": 20, "units": "mm"},
          _extruded, (key + "_control", lambda p: p["result_bodies"][0]))
    rows += [
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_target", "target")), "per_body": True},
         _retire_compare(key + "_target_state", _retire_body_state, False), None),
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_control", "control")), "per_body": True},
         _retire_compare(key + "_control_state", _retire_body_state, False), None),
        ("find_geometry", lambda c: {"target": _ctx_get(c, key + "_target", "target"),
            "kind": "planar_face", "nearest_to": [20, 20, 20], "units": "mm", "max_results": 12},
         retain_face, None)]
    write("model_construction", {"kind": "plane", "plane": "xy", "offset": 10,
                                 "units": "mm", "name": "W2SplitToolPlane"})
    # The tilted projection from z=10 mm lands at x=30 mm on the top at z=20 mm.
    write("sketch_create", {"name": "W2SplitToolAtTop", "plane": "W2SplitToolPlane"})
    write("sketch_add_geometry", {"sketch_name": "W2SplitToolAtTop", "units": "mm",
        "geometry": [{"kind": "line", "x1": 20, "y1": -10, "x2": 20, "y2": 50}]})
    write("sketch_create", {"name": "W2SplitDirection", "plane": "xz"})
    write("sketch_add_geometry", {"sketch_name": "W2SplitDirection", "units": "mm",
        "geometry": [{"kind": "line", "x1": 0, "y1": 0, "x2": 10, "y2": -10}]})
    write("model_construction", {"kind": "axis", "mode": "edge",
        "axis": "W2SplitDirection/line:0", "name": "W2SplitVector"}, _datum("axis"))
    write("model_split", lambda c: {"split": "along_vector",
        "faces": [_ctx_get(_RECALL, key + "_face", "target top face")],
        "split_line": "W2SplitToolAtTop/line:0", "view_direction": "W2SplitVector"},
        lambda p: _measured("along-vector split feature", p,
            p.get("split") == "along_vector" and p.get("result_count", 0) > 0
            and bool(p.get("feature")) and not p.get("unverified")))

    def top_halves(p):
        matches = p.get("matches") or []
        tops = [m for m in matches if m.get("kind") == "planar_face"
                and _near((m.get("position") or [0, 0, 0])[2], 20, .001)
                and _near((m.get("normal") or [0, 0, 0])[2], 1, .001)]
        areas = sorted(m.get("area") for m in tops if _num(m.get("area")))
        centers = sorted(m["position"][0] for m in tops
                         if isinstance(m.get("position"), list) and len(m["position"]) == 3)
        return _measured("partition at x=30 mm with 1200/400 mm2 top halves",
            {"areas": areas, "x_centers": centers},
            len(tops) == 2 and len(areas) == 2 and _near(areas[0], 400, .001)
            and _near(areas[1], 1200, .001) and len(centers) == 2
            and _near(centers[0], 15, .001) and _near(centers[1], 35, .001))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, key + "_target", "split target"),
        "kind": "planar_face", "nearest_to": [20, 20, 20], "units": "mm", "max_results": 32},
        top_halves, None))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, key + "_target", "split target"),
        "kind": "line_edge", "nearest_to": [30, 20, 20], "units": "mm", "max_results": 32},
        lambda p: _measured("new cut edge spans the measured partition", p,
            any(_near(m.get("length"), 40, .001)
                and isinstance(m.get("position"), list) and len(m["position"]) == 3
                and all(_near(v, expected, .001)
                        for v, expected in zip(m["position"], [30, 20, 20]))
                for m in p.get("matches", []))), None))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, key + "_target", "split target"),
        "kind": "line_edge", "nearest_to": [20, 20, 20], "units": "mm", "max_results": 32},
        lambda p: _measured("no competing x=20 mm partition edge", p,
            p.get("match_count") == p.get("returned") == len(p.get("matches", []))
            and p.get("truncated") is not True
            and not any(_near(m.get("length"), 40, .001)
                    and isinstance(m.get("position"), list) and len(m["position"]) == 3
                    and all(_near(v, expected, .001)
                            for v, expected in zip(m["position"], [20, 20, 20]))
                    for m in p.get("matches", []))), None))
    rows += [
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_target", "split target")), "per_body": True},
         _retire_compare(key + "_target_state", _retire_body_state, True), None),
        ("model_inspect", lambda c: {**_combine_inspect(_ctx_get(c, key + "_control", "control")), "per_body": True},
         _retire_compare(key + "_control_state", _retire_body_state, True), None),
        ("design_get", {"include": ["timeline"], "max_results": 100},
         lambda p: _measured("split history healthy at end marker", p,
            bool((p.get("timeline") or {}).get("timeline"))
            and (p.get("timeline") or {}).get("marker_position") == (p.get("timeline") or {}).get("count")
            and all(not r.get("error") and not r.get("warning")
                    for r in (p.get("timeline") or {}).get("timeline", []))), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, key + "_home", "home"),
            "expect_document": _ctx_get(c, key + "_doc", "scratch")}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, key + "_doc", "scratch"),
            "save_changes": False, "expect_document": _ctx_get(c, key + "_home", "home")},
         _document_closed, None)]
    return rows


_BODY_ORGANIZATION += _w2_directional_split_rows()


_EXTRUDE_EDITS = _extrude_edit_rows()


_MIXED_EXTENT_CREATE = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None, 'owned unsaved scratch only'
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    assert root.bRepBodies.count == 1, 'one base body'
    all_faces = root.bRepBodies.item(0).faces
    faces = [f for f in (all_faces.item(i) for i in range(all_faces.count))
             if abs(f.boundingBox.minPoint.z + 1.0) < 1e-9 and abs(f.boundingBox.maxPoint.z + 1.0) < 1e-9]
    assert len(faces) == 1, 'one base face at z -10 mm'
    extrudes = root.features.extrudeFeatures
    feature_input = extrudes.createInput(root.sketches.itemByName('MixProfS').profiles.item(0),
                                         adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    one = adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByString('3 mm'))
    two = adsk.fusion.ToEntityExtentDefinition.create(faces[0], False)
    assert feature_input.setTwoSidesExtent(one, two) is True, 'two-sided setter refused'
    feature = extrudes.add(feature_input)
    assert feature is not None
    feature.name = 'MixedExtrude'
    feature.bodies.item(0).name = 'MixedBody'
    print(json.dumps({'name': feature.name, 'health': int(feature.healthState),
                      'bodies': feature.bodies.count}))
"""


def _mixed_extent_definition(p):
    """A distance + to-entity two-sided Extrude reads no extent and names the class pair."""
    d = p.get("definition") or {}
    return _measured("unsupported two-sided extent is named, not an unexplained null", d,
                     d.get("type") == "ExtrudeFeature" and d.get("extent") is None
                     and d.get("extent_side_count") is None and d.get("direction") is None
                     and d.get("distance") is None and d.get("distance2") is None
                     and d.get("distance_applicable") is None and d.get("distance2_applicable") is None
                     and (d.get("unavailable") or {}).get("extent")
                     == "two-sided DistanceExtentDefinition + ToEntityExtentDefinition is not a supported extent"
                     and d.get("not_read") == ["taper_angle", "thin", "start_extent", "is_solid"])


def _mixed_extent_rows():
    """A natively built distance + to-face Extrude, its named definition gap and its material."""
    rows = [("doc_get", {}, _home_document, ("mx_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "mx_story", "story")},
             _new_document, ("mx_doc", lambda p: p["document_handle"]))]

    def write(name, args, check="ok"):
        rows.append((name, lambda c, args=args: _combine_pin(c, "mx_doc", args), check, None))

    for name, low, high in (("MixBaseS", (40, 0), (60, 20)), ("MixProfS", (45, 5), (55, 15))):
        write("sketch_create", {"name": name, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [{
            "kind": "rectangle", "x1": low[0], "y1": low[1], "x2": high[0], "y2": high[1]}]})
        if name == "MixBaseS":
            write("model_extrude", {"sketch_name": name, "distance": -10}, _extruded)
    write("sys_execute_script", {"script": _MIXED_EXTENT_CREATE, "read_only": False},
          lambda p: _measured("mixed two-sided extrude built natively", p,
                              p.get("name") == "MixedExtrude" and p.get("health") == 0
                              and p.get("bodies") == 1))
    rows += [("design_get", {"include": ["definition"], "feature": "MixedExtrude", "units": "mm"},
              _mixed_extent_definition, None),
             ("model_inspect", _combine_inspect("MixedBody"),
              _combine_body("mixed two-sided extrude", (45, 5, -10), (55, 15, 3), 1300), None),
             ("model_inspect", _combine_inspect("Body1"),
              _combine_body("mixed extrude base unchanged", (40, 0, -10), (60, 20, 0), 4000), None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "mx_story", "story"),
                                         "expect_document": _ctx_get(c, "mx_doc", "scratch")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "mx_doc", "scratch"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "mx_story", "story")},
              _document_closed, None)]
    return rows


_EXTRUDE_EDITS += _mixed_extent_rows()
