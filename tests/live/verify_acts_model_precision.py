# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Precision, section, and hole geometry checks for model acts."""

import math

from verify_core import (
    _RECALL, _ctx_get, _datum, _extruded, _made_component, _measured, _near, _num)
from verify_layout import (
    _px, _py)


_RADIUS_DIAMETER_TOL_MM = 0.0005




def _sweep_edit_at_volume(expected):
    """Check one edit's verified target shape and preserved sweep identity."""
    def check(p):
        bodies = p.get("target_after") or []
        volume = bodies[0].get("volume_cm3") if len(bodies) == 1 else None
        return _measured("sweep operand edit", {
            "same_feature": p.get("same_feature"), "definition_matches": p.get("definition_matches"),
            "geometry_changed": p.get("geometry_changed"), "target_volume_cm3": volume,
            "outside_body_changes": p.get("outside_body_changes"),
            "marker_restored": p.get("marker_restored"),
            "new_errors": p.get("new_timeline_errors"),
            "new_warnings": p.get("new_timeline_warnings")},
            p.get("edited") is True and p.get("same_feature") is True
            and p.get("definition_matches") is True and p.get("geometry_changed") is True
            and (p.get("definition_before") or {}).get("profile_members") == 1
            and (p.get("definition_after") or {}).get("profile_members") == 1
            and p.get("outside_body_changes") == [] and p.get("marker_restored") is True
            and p.get("feature_health") == "healthy"
            and p.get("new_timeline_errors") == [] and p.get("new_timeline_warnings") == []
            and _num(volume) and _near(volume, expected, 0.02))
    return check


def _sweep_inspected_at_volume(expected):
    """Check independent model_inspect volume in cm3 after a sweep edit."""
    def check(p):
        volume = (p.get("mass") or {}).get("volume")
        return _measured("independent swept body volume", {"volume_cm3": volume},
                         _num(volume) and _near(volume, expected, 0.02))
    return check


def _sweep_brep_list_edited(p):
    """Check the exact two-member BRep path and independent target material delta."""
    path_count = (p.get("definition_after") or {}).get("path_curves")
    return _sweep_edit_at_volume(math.pi * 0.8 ** 2 * (1 + math.pi / 4))(p) and _measured(
        "two BRep path members", {"count": path_count}, path_count == 2)


def _sweep_dependent_survived(changed_bounds):
    """Check the saved dependent body handle, material and expected support motion."""
    def check(p):
        base = _RECALL["sweep_dependent_before"]
        volume = (p.get("mass") or {}).get("volume")
        bounds = (p.get("min_point"), p.get("max_point"))
        moved = bounds != (base["min_point"], base["max_point"])
        return _measured("sweep dependent body", {"volume_cm3": volume, "bounds_moved": moved},
                         _num(volume) and _near(volume, base["volume"], 0.001)
                         and moved is changed_bounds)
    return check

_HOLE_HOST = "HoleHostB"
_HOLE_ACTIVE = "ActiveA"
_HOLE_X0 = 2600.0
_HOLE_ACTIVE_X0 = 2650.0
_HOLE_VOLUME = 125.663706


def _section_created(other_key=None):
    """Require one generated section name, distinct from an earlier cut when supplied."""
    def check(p):
        name = p.get("section")
        other = _RECALL.get(other_key) if other_key else None
        return _measured("generated section identity", {"section": name, "other": other},
                         isinstance(name, str) and bool(name)
                         and (other_key is None or name != other))
    return check


def _section_census(keys, visible):
    """Require the complete generated-name and visibility census for the retained sections."""
    def check(p):
        rows = p.get("sections") or []
        expected = [_RECALL.get(key) for key in keys]
        got = [row.get("name") for row in rows]
        bulbs = [row.get("visible") for row in rows]
        return _measured("section analysis census",
                         {"count": p.get("count"), "names": got, "visible": bulbs},
                         all(isinstance(name, str) and name for name in expected)
                         and p.get("count") == len(rows) == len(expected)
                         and got == expected and bulbs == list(visible))
    return check


def _section_named_clear(removed_key):
    """Require one exact generated section removed with bounded count facts."""
    def check(p):
        removed = _RECALL.get(removed_key)
        valid = (p.get("section") == removed and p.get("removed") == [removed]
                 and p.get("removed_count") == 1 and p.get("sections_before") == 2
                 and p.get("sections_after") == 1 and "remaining" not in p)
        return _measured("selected section deletion",
                         {"removed": p.get("removed"), "before": p.get("sections_before"),
                          "after": p.get("sections_after")},
                         valid)
    return check


def _section_camera(p):
    """Return one complete workspace camera record for later equality."""
    view = p.get("view") or {}
    if (view.get("projection") not in ("orthographic", "perspective")
            or not isinstance(view.get("eye"), dict) or not isinstance(view.get("target"), dict)):
        raise AssertionError(f"section camera is incomplete: {view!r}")
    return view


def _section_camera_unchanged(key):
    """Require the workspace camera to equal the retained pre-cut record."""
    def check(p):
        current, before = _section_camera(p), _RECALL.get(key)
        return _measured("section clear camera preservation",
                         {"before": before, "after": current}, current == before)
    return check


_FINE_ANGLE_DEG = 4.0909090909


def _fine_angle_plane(p):
    """model_construction at a long-decimal angle publishes the angle its own parameter landed."""
    return _datum("plane")(p) and _measured(
        "at_angle plane lands the long-decimal angle",
        {"angle_deg": p.get("angle_deg"), "expression": p.get("angle_expression"),
         "model_parameters": p.get("model_parameters")},
        _near(p.get("angle_deg"), _FINE_ANGLE_DEG, 1e-8)
        and bool((p.get("model_parameters") or {}).get("angle")))


def _fine_angle_param(p):
    """param_get of that plane's angle parameter reads every digit asked for, in degrees."""
    par = p.get("parameter") or {}
    return _measured("the fine plane's angle parameter read back",
                     {"name": par.get("name"), "expression": par.get("expression"),
                      "value": par.get("value"), "value_units": par.get("value_units")},
                     par.get("name") == _RECALL.get("db_fine_param")
                     and par.get("value_units") == "deg"
                     and _near(par.get("value"), _FINE_ANGLE_DEG, 1e-8))


def _addr_planes_own_their_params(p):
    """Both components' AddrPlane rows carry parameters, and no parameter name sits on both."""
    rows = [r for r in (p.get("timeline") or {}).get("timeline") or []
            if r.get("name") == "AddrPlane"]
    names = [sorted(q.get("name") for q in r.get("params") or []) for r in rows]
    # A construction plane's timeline row reads component None (measured rel6), so the two rows are
    # told apart by their parameters alone here.
    return _measured(
        "same-named planes in two components carry their own parameters",
        {"components": [r.get("component") for r in rows], "params": names},
        len(rows) == 2 and all(names) and not set(names[0]) & set(names[1]))


def _placed_xyz(component, xyz):
    """One authored point after the layout pass places its component."""
    return [_px(component, xyz[0]), _py(component, xyz[1]), xyz[2]]


def _hole_body_state(component, low, high, volume):
    """A body has the exact measured bounds and volume for one hole-participant beat."""
    def check(p):
        got_low, got_high = p.get("min_point") or {}, p.get("max_point") or {}
        want_low, want_high = _placed_xyz(component, low), _placed_xyz(component, high)
        got_volume = (p.get("mass") or {}).get("volume")
        bounds_ok = all(
            _near(got.get(axis), want, 0.01)
            for got, wanted in ((got_low, want_low), (got_high, want_high))
            for axis, want in zip(("x", "y", "z"), wanted))
        return _measured(
            f"{component} body volume and bounds",
            {"kind": p.get("kind"), "units": p.get("units"),
             "accuracy": (p.get("mass") or {}).get("accuracy_used"),
             "volume": got_volume, "min": got_low, "max": got_high},
            p.get("kind") == "body" and p.get("units") == "mm"
            and (p.get("mass") or {}).get("accuracy_used") == "very_high"
            and _near(got_volume, volume, 0.001) and bounds_ok)
    return check


def _hole_cylinders(component, positions):
    """The complete radius-2 cylinder census at the expected placed positions."""
    def check(p):
        matches = p.get("matches") or []
        wanted = sorted(tuple(round(v, 3) for v in _placed_xyz(component, pos))
                        for pos in positions)
        got = sorted(tuple(round(v, 3) for v in m.get("position", [])) for m in matches)
        exact_faces = all(
            m.get("kind") == "cylinder_face" and _near(m.get("radius"), 2.0, 0.001)
            for m in matches)
        return _measured(
            f"{component} radius-2 cylinder census",
            {"match_count": p.get("match_count"), "returned": p.get("returned"),
             "positions": got, "units": p.get("units"), "truncated": p.get("truncated")},
            p.get("units") == "mm"
            and p.get("match_count") == p.get("returned") == len(wanted)
            and len(matches) == len(wanted) and p.get("truncated") is not True
            and exact_faces and got == wanted)
    return check


def _hole_face_bounds(p):
    """The fresh scoped bore handle resolves to the measured 4 x 4 x 10 mm face."""
    low = _placed_xyz(_HOLE_HOST, (_HOLE_X0 + 8, 8, 0))
    high = _placed_xyz(_HOLE_HOST, (_HOLE_X0 + 12, 12, 10))
    center = _placed_xyz(_HOLE_HOST, (_HOLE_X0 + 10, 10, 5))
    got_low, got_high = p.get("min_point") or {}, p.get("max_point") or {}
    got_center = p.get("center") or {}
    return _measured(
        "fresh scoped bore face bounds",
        {"kind": p.get("kind"), "units": p.get("units"),
         "x": p.get("x"), "y": p.get("y"), "z": p.get("z"),
         "min": got_low, "max": got_high, "center": got_center},
        p.get("kind") == "face" and p.get("units") == "mm"
        and _near(p.get("x"), 4.0, 0.01) and _near(p.get("y"), 4.0, 0.01)
        and _near(p.get("z"), 10.0, 0.01)
        and all(_near(got_low.get(axis), want, 0.01)
                for axis, want in zip(("x", "y", "z"), low))
        and all(_near(got_high.get(axis), want, 0.01)
                for axis, want in zip(("x", "y", "z"), high))
        and all(_near(got_center.get(axis), want, 0.01)
                for axis, want in zip(("x", "y", "z"), center)))


def _hole_host_tree(p):
    """The component-rooted tree names both B bodies and publishes consumable handles."""
    tree = p.get("tree") or {}
    node = tree.get("tree") or {}
    bodies = node.get("bodies") or []
    return _measured(
        "HoleHostB component-rooted body tree",
        {"root": tree.get("root"), "component": node.get("component"),
         "body_count": node.get("body_count"),
         "bodies": [(b.get("name"), bool(b.get("handle"))) for b in bodies]},
        tree.get("root") == _HOLE_HOST and tree.get("truncated") is False
        and node.get("component") == _HOLE_HOST and node.get("body_count") == 2
        and [b.get("name") for b in bodies] == ["Body1", "Body2"]
        and all(isinstance(b.get("handle"), str) and b["handle"]
                and b.get("is_solid") is True for b in bodies))


def _hole_upper_handle(p):
    """The exact upper-body handle from the component-rooted tree."""
    bodies = ((p.get("tree") or {}).get("tree") or {}).get("bodies") or []
    hit = [b.get("handle") for b in bodies if b.get("name") == "Body1"]
    if len(hit) != 1 or not isinstance(hit[0], str) or not hit[0]:
        raise AssertionError(f"HoleHostB Body1 handle is not unique: {hit!r}")
    return hit[0]


def _hole_lower_handle(p):
    """The exact lower-body handle from the component-rooted tree."""
    bodies = ((p.get("tree") or {}).get("tree") or {}).get("bodies") or []
    hit = [b.get("handle") for b in bodies if b.get("name") == "Body2"]
    if len(hit) != 1 or not isinstance(hit[0], str) or not hit[0]:
        raise AssertionError(f"HoleHostB Body2 handle is not unique: {hit!r}")
    return hit[0]


def _hole_active_tree(p):
    """The component-rooted tree names A's sole body and its consumable handle."""
    tree = p.get("tree") or {}
    node = tree.get("tree") or {}
    bodies = node.get("bodies") or []
    return _measured(
        "ActiveA component-rooted body tree",
        {"root": tree.get("root"), "component": node.get("component"),
         "body_count": node.get("body_count"),
         "bodies": [(b.get("name"), bool(b.get("handle"))) for b in bodies]},
        tree.get("root") == _HOLE_ACTIVE and tree.get("truncated") is False
        and node.get("component") == _HOLE_ACTIVE and node.get("body_count") == 1
        and [b.get("name") for b in bodies] == ["Body1"]
        and isinstance(bodies[0].get("handle"), str) and bodies[0]["handle"]
        and bodies[0].get("is_solid") is True)


def _hole_active_handle(p):
    """The exact A-body handle from the component-rooted tree."""
    bodies = ((p.get("tree") or {}).get("tree") or {}).get("bodies") or []
    hit = [b.get("handle") for b in bodies if b.get("name") == "Body1"]
    if len(hit) != 1 or not isinstance(hit[0], str) or not hit[0]:
        raise AssertionError(f"ActiveA Body1 handle is not unique: {hit!r}")
    return hit[0]


def _hole_inspect_args(ctx, key):
    """Mass-and-bounds arguments consuming one retained body handle."""
    return {"target": _ctx_get(ctx, key, "hole fixture body"), "include": ["default", "mass"],
            "units": "mm", "accuracy": "very_high"}


def _hole_cylinder_args(ctx, key):
    """Cylinder-census arguments consuming one retained body handle."""
    return {"target": _ctx_get(ctx, key, "hole fixture body"), "kind": "cylinder_face",
            "radius": 2, "units": "mm", "max_results": 10}


def _hole_point_while_active_a(x, y, z):
    """A B-authored point before the layout wrapper adds active A's offset."""
    return [_px(_HOLE_HOST, x) - _px(_HOLE_ACTIVE, 0.0),
            _py(_HOLE_HOST, y) - _py(_HOLE_ACTIVE, 0.0), z]


def _scoped_top_args(ctx):
    """The upper-face acquisition at the scoped bore point."""
    return {"target": _ctx_get(ctx, "hh_upper", "HoleHostB upper body"),
            "kind": "planar_face",
            "nearest_to": _hole_point_while_active_a(_HOLE_X0 + 10, 10, 10),
            "units": "mm", "max_results": 1}


def _control_top_args(ctx):
    """The upper-face acquisition at the positive-control bore point."""
    return {"target": _ctx_get(ctx, "hh_upper", "HoleHostB upper body"),
            "kind": "planar_face",
            "nearest_to": _hole_point_while_active_a(_HOLE_X0 + 5, 5, 10),
            "units": "mm", "max_results": 1}


def _scoped_bore_args(ctx):
    """The complete post-write bore census on the retained upper-body handle."""
    return {"target": _ctx_get(ctx, "hh_upper", "HoleHostB upper body"),
            "kind": "cylinder_face", "radius": 2, "units": "mm", "max_results": 1}


def _scoped_hole_args(ctx):
    """The upper-only hole arguments while ActiveA remains the runtime edit target."""
    return {"face": _ctx_get(ctx, "hh_top", "HoleHostB upper top face"),
            "hole_type": "simple", "diameter": "4 mm", "extent": "through",
            "points_space": "world", "units": "mm",
            "points": [_hole_point_while_active_a(_HOLE_X0 + 10, 10, 10)],
            "target_bodies": [_ctx_get(ctx, "hh_upper", "HoleHostB upper body")]}


def _unscoped_hole_args(ctx):
    """The positive-control hole arguments with target_bodies intentionally absent."""
    return {"face": _ctx_get(ctx, "hh_top_control", "HoleHostB upper top face"),
            "hole_type": "simple", "diameter": "4 mm", "extent": "through",
            "points_space": "world", "units": "mm",
            "points": [_hole_point_while_active_a(_HOLE_X0 + 5, 5, 10)]}


def _hole_created(scoped):
    """model_hole reports the face host and the exact participant mode."""
    def check(p):
        scope = p.get("scoped_to_bodies")
        scope_ok = (scope == [f"{_HOLE_HOST}:1:Body1"] if scoped
                    else "scoped_to_bodies" not in p)
        suffix = "1" if scoped else "2"
        return _measured(
            "scoped hole" if scoped else "unscoped positive-control hole",
            {"feature": p.get("feature"), "host": p.get("host_component"),
             "sketch": p.get("placement_sketch"), "scope": scope},
            p.get("holes") == 1 and p.get("holes_verified") is True
            and p.get("host_from_face") is True and p.get("host_verified") is True
            and p.get("host_component") == _HOLE_HOST
            and p.get("world_lift_component") == _HOLE_HOST
            and p.get("points_space") == "world" and p.get("feature") == f"Hole{suffix}"
            and p.get("placement_sketch") == f"Sketch{int(suffix) + 2}" and scope_ok)
    return check


def _hole_timeline(control):
    """The complete bounded timeline locates each hole and placement sketch in B."""
    def check(p):
        timeline = p.get("timeline") or {}
        rows = timeline.get("timeline") or []
        required = {("Sketch3", "Sketch", _HOLE_HOST),
                    ("Hole1", "HoleFeature", _HOLE_HOST)}
        if control:
            required |= {("Sketch4", "Sketch", _HOLE_HOST),
                         ("Hole2", "HoleFeature", _HOLE_HOST)}
        got = {(r.get("name"), r.get("type"), r.get("component")) for r in rows}
        active_a_holes = [r.get("name") for r in rows
                          if r.get("component") == _HOLE_ACTIVE
                          and r.get("type") == "HoleFeature"]
        count, returned = timeline.get("count"), timeline.get("returned")
        return _measured(
            "complete bounded hole-host timeline",
            {"count": count, "returned": returned, "required": sorted(required - got),
             "active_a_holes": active_a_holes, "truncated": timeline.get("truncated")},
            isinstance(count, int) and count <= 2000 and returned == count == len(rows)
            and timeline.get("truncated") is not True and required <= got
            and not active_a_holes)
    return check


def _radius_body_size(label, diameter_mm):
    """A 10 mm cylinder whose diameter is precise enough to settle the radius boundary."""
    def check(p):
        return _measured(
            label,
            {"x": p.get("x"), "y": p.get("y"), "z": p.get("z")},
            _near(p.get("x"), diameter_mm, _RADIUS_DIAMETER_TOL_MM)
            and _near(p.get("y"), diameter_mm, _RADIUS_DIAMETER_TOL_MM)
            and _near(p.get("z"), 10.0, 0.01))
    return check


def _radius_filtered_handle(ctx, filtered_key, index):
    """One actual radius-filtered handle for independent body-size readback."""
    filtered = _ctx_get(ctx, filtered_key, "the radius-filtered handles")
    if not isinstance(filtered, list):
        raise AssertionError(f"filtered handles {filtered!r} are not a list")
    if not 0 <= index < len(filtered):
        raise AssertionError(f"filtered handle index {index} is outside {len(filtered)} handles")
    return {"target": filtered[index], "units": "mm"}


def _precision_geometry(kind, units):
    """Check analytic radii and positions without rounding away the journal's tolerance span."""
    def check(p):
        rows = sorted(p.get("matches") or [], key=lambda row: row.get("radius", 0))
        factor = 25.4 if units == "mm" else 1.0
        count = 2 if kind == "cylinder_face" else 4
        radii = [0.312125, 0.88575] if count == 2 else [0.312125] * 2 + [0.88575] * 2
        good = len(rows) == p.get("match_count") == count and p.get("units") == units
        for row, radius in zip(rows, radii):
            position = row.get("position") or []
            cx = 0.123456 if radius == 0.312125 else 3.654321
            good = (good and row.get("kind") == kind
                    and _near(row.get("radius"), radius * factor, 0.000001)
                    and len(position) == 3
                    and _near(position[0], _px("PrecisionBench", (cx + 100) * 25.4)
                              * factor / 25.4, 0.000001)
                    and _near(position[1], _py("PrecisionBench", 0.234567 * 25.4)
                              * factor / 25.4, 0.000001))
            if radius == 0.88575:
                diameter = 2 * row.get("radius", 0) / factor
                good = good and 1.7714 <= diameter <= 1.7716
        return _measured("close-tolerance acquired " + kind + " in " + units,
                         [{k: row.get(k) for k in ("radius", "position", "handle")} for row in rows], good)
    return check


def _precision_planes(units):
    """Check the four planar caps and their world frames against their analytic heights."""
    def check(p):
        rows = p.get("matches") or []
        factor = 1 if units == "mm" else 1 / 25.4
        return _measured("precise planar cap frames in " + units, rows,
                         len(rows) == p.get("match_count") == 4
                         and all(row.get("kind") == "planar_face" and row.get("frame")
                                 and _near(row["frame"]["origin"][2], row["position"][2], 0.000001)
                                 and any(_near(row["frame"]["origin"][2], z * factor, 0.000001)
                                         for z in (0, 10)) for row in rows)
                         and sum(_near(row["frame"]["origin"][2], 10 * factor, 0.000001)
                                 for row in rows) == 2)
    return check


def _precision_ellipse(units):
    """Check both analytic ellipse edges, including precise radii and world centers."""
    def check(p):
        rows = sorted(p.get("matches") or [], key=lambda row: (row.get("position") or [0, 0, 0])[2])
        factor = 1 if units == "mm" else 1 / 25.4
        center = [_px("PrecisionEllipseBench", 2700 + 0.123456 * 25.4),
                  _py("PrecisionEllipseBench", 0.234567 * 25.4)]
        good = len(rows) == p.get("match_count") == 2 and p.get("units") == units
        for row, z in zip(rows, (0, 10.123456)):
            position = row.get("position") or []
            good = (good and row.get("kind") == "ellipse_edge" and bool(row.get("handle"))
                    and _near(row.get("major_radius"), 0.88575 * 25.4 * factor, 0.000001)
                    and _near(row.get("minor_radius"), 0.312125 * 25.4 * factor, 0.000001)
                    and len(position) == 3
                    and all(_near(actual, expected * factor, 0.000001)
                            for actual, expected in zip(position, [*center, z])))
        return _measured("precise ellipse radii and centers in " + units, rows, good)
    return check


def _precision_vertex_points():
    """The eight independently authored box corners in world millimetres."""
    return [[_px("PrecisionVertexBench", 2800 + x * 25.4),
             _py("PrecisionVertexBench", y * 25.4), z]
            for x in (0.123456, 0.765432) for y in (0.234567, 0.876543)
            for z in (0, 10.123456)]


def _precision_vertices(units):
    """Check all fractional-coordinate vertices against the authored corner set."""
    def check(p):
        rows = p.get("matches") or []
        factor = 1 if units == "mm" else 1 / 25.4
        expected = sorted(_precision_vertex_points())
        good = (len(rows) == p.get("match_count") == 8 and p.get("units") == units
                and all(row.get("kind") == "vertex" and row.get("handle")
                        and len(row.get("position") or []) == 3 for row in rows))
        if good:
            actual = sorted(row["position"] for row in rows)
            good = all(_near(a, e * factor, 0.000001)
                       for point, wanted in zip(actual, expected) for a, e in zip(point, wanted))
        return _measured("precise fractional vertices in " + units, rows, good)
    return check


def _precision_vertex_bounds(p):
    """Independently confirm the vertex coupon's world bounds through model_inspect."""
    points = _precision_vertex_points()
    low, high = p.get("min_point") or {}, p.get("max_point") or {}
    return _measured("independent fractional vertex bounds", p,
                     all(_near(bound.get(axis), choose(q[i] for q in points), 0.000001)
                         for bound, choose in ((low, min), (high, max))
                         for i, axis in enumerate("xyz")))


def _precision_edge_gap(height, units):
    """Check actual cap-edge spacing and the measured endpoints in the requested units."""
    def check(p):
        expected = height if units == "mm" else height / 25.4
        a, b = p.get("closest_point_on_a") or {}, p.get("closest_point_on_b") or {}
        zs = [a.get("z"), b.get("z")]
        return _measured("independent cap-edge spacing in " + units, p,
                         p.get("mode") == "distance" and p.get("units") == units
                         and all(str(p.get(key, "")).startswith("edge '") for key in ("a", "b"))
                         and _near(p.get("distance"), expected, 0.000001)
                         and all(_near(a.get(axis), b.get(axis), 0.000001) for axis in ("x", "y"))
                         and all(isinstance(z, (int, float)) and not isinstance(z, bool) for z in zs)
                         and _near(min(zs), 0, 0.000001) and _near(max(zs), expected, 0.000001))
    return check


def _precision_rows():
    """Cross-check cylinder, ellipse and vertex acquisitions in inches and mm."""
    rows = [("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("model_create_component", {"name": "PrecisionBench", "activate": True,
                                         "x": 2540}, _made_component, None)]
    for name, radius, cx in (("PrecisionLug", 0.312125, 0.123456),
                             ("PrecisionJournal", 0.88575, 3.654321)):
        rows += [
            ("sketch_create", {"plane": "xy", "name": name}, "ok", None),
            ("sketch_add_geometry", {"sketch_name": name, "units": "in", "geometry": [
                {"kind": "circle", "cx": cx, "cy": 0.234567, "radius": radius}]}, "ok", None),
            ("model_extrude", {"sketch_name": name, "distance": 10, "operation": "new"},
             _extruded, None),
        ]
    for units in ("in", "mm"):
        rows.append(("find_geometry", {"target": "PrecisionBench", "kind": "planar_face",
                                       "units": units}, _precision_planes(units), None))
        for kind in ("cylinder_face", "circular_edge"):
            key = "precision_" + kind + "_" + units
            rows.append(("find_geometry", {"target": "PrecisionBench", "kind": kind,
                                           "units": units}, _precision_geometry(kind, units),
                         (key, lambda p: [r["handle"] for r in sorted(
                             p["matches"], key=lambda row: row["radius"])])))
            for index, radius in enumerate([0.312125, 0.88575] if kind == "cylinder_face"
                                            else [0.312125] * 2 + [0.88575] * 2):
                rows.append(("model_inspect", lambda c, key=key, index=index: {
                    "target": _ctx_get(c, key, "the precise acquired handles")[index], "units": "mm"},
                    lambda p, radius=radius: _measured(
                        "independent acquired face or owning-body diameter",
                        {"x": p.get("x"), "y": p.get("y"), "z": p.get("z")},
                        _near(p.get("x"), radius * 50.8, 0.000002)
                        and _near(p.get("y"), radius * 50.8, 0.000002)
                        and _near(p.get("z"), 10, 0.000002)), None))
            if kind == "circular_edge":
                for first in (0, 2):
                    rows.append(("model_measure_between", lambda c, key=key, first=first, units=units: {
                        "a": _ctx_get(c, key, "the precise cap-edge handles")[first],
                        "b": _ctx_get(c, key, "the precise cap-edge handles")[first + 1],
                        "units": units}, _precision_edge_gap(10, units), None))
    rows += [
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
        ("model_create_component", {"name": "PrecisionEllipseBench", "activate": True,
                                     "x": 2700}, _made_component, None),
        ("sketch_create", {"plane": "xy", "name": "PrecisionEllipse"}, "ok", None),
        ("sketch_add_geometry", {"sketch_name": "PrecisionEllipse", "units": "in", "geometry": [
            {"kind": "ellipse", "cx": 0.123456, "cy": 0.234567,
             "radius": 0.88575, "minor": 0.312125}]}, "ok", None),
        ("model_extrude", {"sketch_name": "PrecisionEllipse", "distance": 10.123456,
                           "operation": "new"}, _extruded, None),
    ]
    for units in ("in", "mm"):
        key = "precision_ellipse_" + units
        rows.append(("find_geometry", {"target": "PrecisionEllipseBench", "kind": "ellipse_edge",
                                       "units": units}, _precision_ellipse(units),
                     (key, lambda p: [r["handle"] for r in sorted(
                         p["matches"], key=lambda row: row["position"][2])])))
        for index in (0, 1):
            rows.append(("model_inspect", lambda c, key=key, index=index: {
                "target": _ctx_get(c, key, "the precise ellipse handles")[index], "units": "mm"},
                lambda p: _measured("independent ellipse owning-body extent", p,
                    _near(p.get("x"), 0.88575 * 50.8, 0.000002)
                    and _near(p.get("y"), 0.312125 * 50.8, 0.000002)
                    and _near(p.get("z"), 10.123456, 0.000001)
                    and _near((p.get("center") or {}).get("z"), 10.123456 / 2, 0.000001)), None))
        rows.append(("model_measure_between", lambda c, key=key, units=units: {
            "a": _ctx_get(c, key, "the precise ellipse cap-edge handles")[0],
            "b": _ctx_get(c, key, "the precise ellipse cap-edge handles")[1],
            "units": units}, _precision_edge_gap(10.123456, units), None))
    rows += [
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
        ("model_create_component", {"name": "PrecisionVertexBench", "activate": True,
                                     "x": 2800}, _made_component, None),
        ("sketch_create", {"plane": "xy", "name": "PrecisionVertices"}, "ok", None),
        ("sketch_add_geometry", {"sketch_name": "PrecisionVertices", "units": "in", "geometry": [
            {"kind": "rectangle", "x1": 0.123456, "y1": 0.234567,
             "x2": 0.765432, "y2": 0.876543}]}, "ok", None),
        ("model_extrude", {"sketch_name": "PrecisionVertices", "distance": 10.123456,
                           "operation": "new"}, _extruded, None),
        ("model_inspect", {"target": "PrecisionVertexBench", "units": "mm"},
         _precision_vertex_bounds, None),
    ]
    for units in ("in", "mm"):
        rows.append(("find_geometry", {"target": "PrecisionVertexBench", "kind": "vertex",
                                       "units": units}, _precision_vertices(units), None))
    return rows


_PRECISION_READS = _precision_rows()
