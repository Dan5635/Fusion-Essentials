# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Sweep and loft editing checks for model acts."""

import math
import re

from verify_core import (
    _RECALL, _Refusal, _ctx_get, _datum_plane, _document_closed, _extruded, _fg, _home_address, _home_document, _lofted, _made_component, _matched, _measured, _near, _num, _new_document, _prof, _recall, _refused, _revolved, _swept, _watch)





from verify_acts_model_combine_revolve import (
    _combine_body, _combine_inspect, _combine_pin)

# --- ACT 2: SOLIDS - the parts turn solid, each part its own color (mirrors scenario S2) -------
# The hero solids ride on ACT 1's parametric sketches; the multi-body feature tools that have no
# natural home on the part (draft/mirror/patterns/combine) ride cameo bodies in the SAME
# document, so every one is exercised without contorting the mechanism.
def _sweep_mode_shape(p):
    """Return the independent body volume, area and world bounds used by sweep edit rows."""
    mass = p.get("mass") or {}
    return {"volume": mass.get("volume"), "area": mass.get("area"),
            "min": p.get("min_point"), "max": p.get("max_point")}


def _sweep_mode_box_equal(left, right, tol=0.0001):
    """Compare complete measured body bounds without accepting unread coordinates."""
    return all(isinstance((left.get(side) or {}).get(axis), (int, float))
               and isinstance((right.get(side) or {}).get(axis), (int, float))
               and math.isfinite(left[side][axis]) and math.isfinite(right[side][axis])
               and abs(left[side][axis] - right[side][axis]) <= tol
               for side in ("min", "max") for axis in ("x", "y", "z"))


def _solid_tool_expected(case, role):
    """Return analytic world bounds and volume in millimeters for the owned tool sweep."""
    angle = math.radians(25)
    co, si = math.cos(angle), math.sin(angle)
    x, y = 3200, 500
    if role == "source":
        half = 2.5 * (co + si)
        lo, hi, volume = (x - half, y - half, 0), (x + half, y + half, 5), 125
    else:
        lo = (x - 2.5 * (co + si), y - 2.5 * (co + si), 0)
        hi = (x + 22.5 * co + 2.5 * si, y + 22.5 * si + 2.5 * co, 5)
        volume = 625
    return {"min": dict(zip(("x", "y", "z"), lo)),
            "max": dict(zip(("x", "y", "z"), hi)), "volume": volume}


def _solid_tool_mass(case, role, previous=None):
    """Check measured volume and placed bounds against the tool sweep geometry."""
    def check(p):
        got, expected = _sweep_mode_shape(p), _solid_tool_expected(case, role)
        old = _RECALL.get(previous) if previous else None
        valid = (p.get("kind") == "body" and p.get("units") == "mm"
                 and _near(got["volume"], expected["volume"], 1.0)
                 and _sweep_mode_box_equal(got, expected, 0.3)
                 and (previous is None or got == old))
        return _measured(f"{case} solid tool {role} independent volume and world bounds",
                         {"actual": got, "expected": expected, "before": old}, valid)
    return check


def _solid_tool_census(p):
    """Return the owner's body identities and every SweepFeature row's (name, health), or None on an unreadable or truncated read."""
    tree = p.get("tree") or {}
    node = tree.get("tree") or {}
    bodies = node.get("bodies") if node else tree.get("root_bodies")
    timeline = (p.get("timeline") or {}).get("timeline")
    if (not isinstance(bodies, list) or not isinstance(timeline, list)
            or tree.get("truncated") or tree.get("children_truncated")
            or tree.get("root_bodies_truncated") or node.get("bodies_truncated")
            or (p.get("timeline") or {}).get("truncated")
            or any(not isinstance(b, dict) or not b.get("name") or not b.get("handle")
                   for b in bodies)):
        return None
    return {"bodies": sorted((b.get("name"), b.get("handle")) for b in bodies),
            "sweeps": sorted((r.get("name"), r.get("health")) for r in timeline
                             if r.get("type") == "SweepFeature")}


def _solid_tool_health(host, key):
    """Check the new sweep's own timeline row in its owner reads healthy."""
    def check(p):
        timeline = p.get("timeline") or {}
        feature = (_RECALL.get(key) or {}).get("feature")
        rows = [r for r in timeline.get("timeline") or []
                if r.get("name") == feature and r.get("component") == host
                and r.get("type") == "SweepFeature"]
        # A healthy timeline row is published without its health key.
        return _measured("new solid sweep timeline health", rows,
                         bool(feature) and not timeline.get("truncated") and len(rows) == 1
                         and rows[0].get("health", "healthy") == "healthy")
    return check


def _retire_design_state(p):
    """Return complete ungrouped tree/history facts for failed-create comparisons."""
    tree, tl = p.get("tree") or {}, p.get("timeline") or {}
    rows = tl.get("timeline")
    def complete(node):
        children = node.get("children", [])
        return (node.get("child_count") == len(children) and not node.get("children_truncated")
                and not node.get("truncated") and not node.get("bodies_truncated")
                and not node.get("root_bodies_truncated") and not node.get("unresolved")
                and ("component" not in node or type(node.get("body_count")) is int
                     and node["body_count"] == len(node.get("bodies", [])))
                and all(b.get("name") and type(b.get("is_solid")) is bool and type(b.get("visible")) is bool
                        for b in node.get("bodies", []))
                and all(complete(c) for c in children))
    if (not complete(tree) or not isinstance(rows, list) or tl.get("truncated")
            or tl.get("count") != tl.get("returned") or tl.get("count") != len(rows)
            or tl.get("marker_position") != len(rows)
            or any(r.get("index") != i or not r.get("name") or not r.get("type") for i, r in enumerate(rows))):
        return None
    return {"tree": tree, "timeline": tl}


def _retire_material_state(p):
    """Return independently counted body material, visibility and world bounds."""
    mass = p.get("mass") or {}
    rows = mass.get("per_body")
    shape = _sweep_mode_shape(p)
    if (p.get("units") != "mm" or p.get("frame") != "world axes (axis-aligned)"
            or not _sweep_mode_box_equal(shape, shape)
            or not all(_num(shape[k]) and shape[k] > 0 for k in ("volume", "area"))
            or not isinstance(rows, list) or not rows or mass.get("per_body_count") != len(rows)
            or mass.get("per_body_truncated") is not False
            or any(not r.get("body") or r.get("is_solid") is not True or r.get("lump_count") != 1
                   or not _num(r.get("volume")) or r["volume"] <= 0 for r in rows)):
        return None
    return {"shape": shape, "bodies": rows}


def _retire_sphere_fixture(p):
    """Require the measured sphere and witness geometry on the owned solid fixture's reads."""
    state = _retire_material_state(p)
    if state is None:
        return None
    if p.get("target") not in ("occurrence 'RetireSolid:1'", "occurrence 'RetireWitness:1'"):
        return None
    source = p["target"] == "occurrence 'RetireSolid:1'"
    size, volume = (5, 4 * math.pi * 2.5 ** 3 / 3) if source else (10, 1000)
    if not all(_near(p.get(axis), size, .001) for axis in "xyz") or not _near(state["shape"]["volume"], volume, .001):
        return None
    return state


def _retire_sketch_state(p):
    """Return complete sketch geometry, constraints and frame without handle text."""
    counts, entities = p.get("counts"), p.get("entities")
    if (not isinstance(counts, dict) or any(type(n) is not int or n < 0 for n in counts.values())
            or not isinstance(entities, list) or sum(counts.values()) != len(entities)
            or p.get("truncated") is not False or p.get("profiles_stale") or p.get("timeline_marker_unrestored")
            or not isinstance(p.get("frame"), dict)):
        return None
    for e in entities:
        fields = {"line": ("start", "end"), "arc": ("center",), "point": ("position",)}.get(e.get("type"))
        if fields is None or any(not isinstance(e.get(k), dict) or not e[k]
                                 or any(not _num(v) for v in e[k].values()) for k in fields):
            return None
        if e.get("type") == "arc" and (not _num(e.get("radius")) or not math.isfinite(e["radius"]) or e["radius"] <= 0):
            return None
    for count, key in (("constraint_count", "constraints"), ("dimension_count", "dimensions"), ("profile_count", "profiles")):
        if type(p.get(count)) is not int or not isinstance(p.get(key), list) or p[count] != len(p[key]):
            return None
    return {"counts": counts, "entities": [{k: v for k, v in e.items() if k != "handle"} for e in entities],
            "profiles": [{k: v for k, v in e.items() if k != "handle"} for e in p["profiles"]],
            "constraints": p["constraints"], "dimensions": p["dimensions"], "frame": p["frame"]}


def _retire_compare(key, extract, after):
    """Require the complete independent read to equal its pre-failure observation."""
    def check(p):
        now = extract(p)
        before = _RECALL.get(key)
        valid = now is not None and (not after or before is not None and now == before)
        if valid and not after:
            _RECALL[key] = now
        return _measured("failed creation leaves " + key + " unchanged", {"before": before, "now": now}, valid)
    return check


def _retire_reads(tag, targets, sketches, after=False, material_read=_retire_material_state):
    """Read the entire history/tree and each affected or control body's material and sketches."""
    rows = [("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                              "max_depth": 10, "max_results": 2000},
             _retire_compare(tag + "_design", _retire_design_state, after), None)]
    for target in targets:
        rows.append(("model_inspect", {"target": target, "include": ["default", "mass"], "per_body": True,
                                       "accuracy": "very_high", "units": "mm"},
                     _retire_compare(tag + "_" + target, material_read, after), None))
    for owner, name in sketches:
        rows.append(("sketch_get", {"component": owner, "sketch_name": name, "include_entities": True,
                                    "max_results": 200, "units": "mm"},
                     _retire_compare(tag + "_" + name, _retire_sketch_state, after), None))
    return rows


def _retire_summary(p, after=False):
    """Compare native summary bounds with independently preserved sketch coordinates."""
    box = (p.get("design") or {}).get("overall_bbox") or {}
    size, center = box.get("size") or {}, box.get("center") or {}
    complete = (box.get("units") == "mm" and all(_num(d.get(k)) for d in (size, center) for k in "xyz"))
    minimum = center["x"] - size["x"] / 2 if complete else None
    old = _RECALL.get("retire_summary_min")
    sketch = _RECALL.get("solid_retire_RetireArc") or {}
    frame = sketch.get("frame") or {}
    points = [e.get("position") for e in sketch.get("entities", []) if e.get("type") == "point"]
    endpoint = {"x": -20.0, "y": 20.0} in points
    valid = (complete and "may omit hidden geometry" in box.get("scope", "")
             and "model_inspect" in box.get("scope", "") and endpoint
             and frame.get("space") == "world" and frame.get("origin_mm") == [100, 0, 0]
             and frame.get("x_world") == [1, 0, 0] and frame.get("y_world") == [0, 1, 0]
             and (_num(old) and _near(minimum, old, 0.1)
                  if after else _near(minimum, 79.98, 0.1)))
    if valid and not after:
        _RECALL["retire_summary_min"] = minimum
    return _measured("component summary versus extant world sketch point [80,20,0]",
                     {"summary": box, "prior_min_x": old, "min_x": minimum, "sketch_frame": frame}, valid)


def _retire_sketch_visibility(p):
    """Check the owned path sketch's restored visibility independently."""
    rows = p.get("sketches") or []
    path = [r for r in rows if r.get("name") == "RetireArc"]
    return _measured("surviving path visibility", rows,
                     p.get("sketch_count") == len(rows) == 2 and p.get("truncated") is not True
                     and len(path) == 1 and path[0].get("is_visible") is True
                     and path[0].get("arc_count") == 1 and path[0].get("point_count") == 4)


def _empty_solid_rows():
    """Verify the measured curved solid-sweep failure is retired without disturbing its controls."""
    rows = [("doc_get", {}, _home_document, ("retire_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "retire_home", "story")},
             _new_document, ("retire_doc", lambda p: p["document_handle"]))]
    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "retire_doc", args(c) if callable(args) else args), check, save))
    write("model_create_component", {"name": "RetireWitness", "activate": True, "x": 3225, "y": 520}, _made_component)
    write("sketch_create", {"plane": "xy", "name": "RetireWitnessS"})
    write("sketch_add_geometry", {"sketch_name": "RetireWitnessS", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]})
    write("model_extrude", {"sketch_name": "RetireWitnessS", "distance": 10}, _extruded)
    write("model_create_component", {"name": "RetireSolid", "activate": True, "x": 100}, _made_component)
    write("sketch_create", {"plane": "xy", "name": "RetireSphere"})
    write("sketch_add_geometry", {"sketch_name": "RetireSphere", "geometry": [
        {"kind": "arc", "cx": 0, "cy": 0, "x1": 2.5, "y1": 0, "sweep_deg": 180},
        {"kind": "line", "x1": -2.5, "y1": 0, "x2": 2.5, "y2": 0}]})
    write("sketch_create", {"plane": "xy", "name": "RetireArc"})
    write("sketch_add_geometry", {"sketch_name": "RetireArc", "geometry": [
        {"kind": "arc", "cx": -20, "cy": 0, "x1": 0, "y1": 0, "sweep_deg": 90}]})
    write("model_revolve", {"sketch_name": "RetireSphere", "component": "RetireSolid", "axis": "x", "angle_deg": 360}, _revolved)
    rows.append(("find_geometry", {"target": "RetireSolid:1", "kind": "sphere_face", "nearest_to": [100, 0, 0], "max_results": 8},
                 lambda p: _measured("one placed source sphere face", p.get("matches"),
                     p.get("returned") == p.get("match_count") == 1 and bool(p["matches"][0].get("handle"))), _fg("retire_sphere")))
    write("design_activate_component", {"occurrence": "RetireWitness:1"})
    targets = ["RetireSolid:1", "RetireWitness:1"]
    sketches = [("RetireSolid", "RetireSphere"), ("RetireSolid", "RetireArc"), ("RetireWitness", "RetireWitnessS")]
    rows.extend(_retire_reads("solid_retire", targets, sketches, material_read=_retire_sphere_fixture))
    rows.extend([("workspace_orient", {}, _retire_summary, None),
                 ("sketch_get", {"component": "RetireSolid:1"}, _retire_sketch_visibility, None)])
    write("model_sweep", lambda c: {"solid_body": _ctx_get(c, "retire_sphere", "sphere face"),
          "path": "sketch:RetireArc", "component": "RetireSolid", "operation": "new"},
          _refused("new result body could not be identified", "was removed", "checked body shapes were restored"))
    rows.extend(_retire_reads("solid_retire", targets, sketches, after=True, material_read=_retire_sphere_fixture))
    rows.extend([("workspace_orient", {}, lambda p: _retire_summary(p, True), None),
                 ("sketch_get", {"component": "RetireSolid:1"}, _retire_sketch_visibility, None)])
    rows.extend([("doc_activate", lambda c: {"name": _ctx_get(c, "retire_home", "story"),
                    "expect_document": _ctx_get(c, "retire_doc", "retirement scratch")}, "ok", None),
                 ("doc_close", lambda c: {"name": _ctx_get(c, "retire_doc", "retirement scratch"), "save_changes": False,
                    "expect_document": _ctx_get(c, "retire_home", "story")}, _document_closed, None)])
    return rows


def _solid_tool_rows():
    """Exercise NewBody solid sweeps through placed proxy handles and independent geometry."""
    # A curved solid sweep in a component offset along x builds an empty feature that reads
    # healthy (measured on 2706.0.97, also through the raw API), so the owned story uses the
    # straight path; the tool refuses that empty result.
    cases = (("straight", "SolidToolStraight", 3200),)
    rows = [("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("model_create_component", {"name": "SolidToolWitness", "activate": True,
                                        "x": 3225, "y": 520}, _made_component, None),
            ("sketch_create", {"plane": "xy", "name": "SolidToolWitnessS"}, "ok", None),
            ("sketch_add_geometry", {"sketch_name": "SolidToolWitnessS", "geometry": [
                {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]}, "ok", None),
            ("model_extrude", {"sketch_name": "SolidToolWitnessS", "distance": 10},
             _extruded, ("st_witness", lambda p: p["result_bodies"][0])),
            ("model_inspect", lambda c: _combine_inspect(
                "SolidToolWitness:1:" + _ctx_get(c, "st_witness", "witness")),
             lambda p: _measured("unrelated solid sweep witness before", p.get("mass"),
                                 _near((p.get("mass") or {}).get("volume"), 1000, 0.01)),
             ("st_witness_shape", _recall("st_witness_shape", _sweep_mode_shape)))]
    # Host-named sketches share the host's camera group, so the hand frame below owns the story.
    for case, host, x in cases:
        source, path, body_key = host + "S", host + "Path", "st_" + case + "_body"
        rows.extend([
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("model_create_component", {"name": host, "activate": True,
                                        "x": x, "y": 500, "rotate_deg": 25}, _made_component, None),
            ("sketch_create", {"plane": "xy", "name": source}, "ok", None),
            ("sketch_add_geometry", {"sketch_name": source, "component": host,
                                     "geometry": [{"kind": "rectangle", "x1": -2.5, "y1": -2.5,
                                                   "x2": 2.5, "y2": 2.5}]}, "ok", None),
            ("sketch_create", {"plane": "xy", "name": path}, "ok", None),
            ("sketch_add_geometry", {"sketch_name": path, "component": host,
                                     "geometry": [{"kind": "line", "x1": 0, "y1": 0,
                                                   "x2": 20, "y2": 0}]}, "ok", None),
            ("model_extrude", {"sketch_name": source, "component": host, "distance": 5},
             _extruded, (body_key, lambda p: p["result_bodies"][0])),
            ("model_inspect", lambda c, key=body_key, host=host: _combine_inspect(
                host + ":1:" + _ctx_get(c, key, "solid tool source")),
             _solid_tool_mass(case, "source"),
             ("st_" + case + "_shape", _recall("st_" + case + "_shape", _sweep_mode_shape)))])
    # The swept result lies beside the witness, so one frame holds both hosts.
    rows.append(_watch(["SolidToolStraight:1", "SolidToolWitness:1"]))
    for case, host, x in cases:
        path, body_key = host + "Path", "st_" + case + "_body"
        handle_key, result_key = "st_" + case + "_handle", "st_" + case + "_result"
        rows.extend([
            ("find_geometry", lambda c, key=body_key, host=host, x=x: {
                "target": host + ":1:" + _ctx_get(c, key, "solid tool source"),
                "kind": "planar_face", "nearest_to": [x, 500, 5],
                "units": "mm", "max_results": 1},
             lambda p: _measured("placed source face handle for solid sweep", p.get("matches"),
                                  p.get("returned") == 1 and bool((p.get("matches") or [{}])[0].get("handle"))),
             _fg(handle_key)),
            ("design_activate_component", {"occurrence": "SolidToolWitness:1"}, "ok", None),
            ("model_sweep", lambda c, key=handle_key, path=path, host=host: {
                "solid_body": _ctx_get(c, key, "placed solid tool handle"),
                "path": "sketch:" + path, "component": host, "operation": "new"},
             lambda p, host=host: _measured("owner-local NewBody solid sweep", p,
                 p.get("swept") is True and p.get("component") == host
                 and p.get("source_retained") is True and bool(p.get("feature"))
                 and p.get("orientation") == "perpendicular"
                 and p.get("path_curves") == 1 and len(p.get("result_bodies") or []) == 1),
             (result_key, _recall(result_key, lambda p: {"feature": p["feature"],
                                                         "body": p["result_bodies"][0]}))),
            ("design_get", {"include": ["timeline"], "max_results": 2000},
             _solid_tool_health(host, result_key), None),
            ("model_inspect", lambda c, key=result_key, host=host: _combine_inspect(
                host + ":1:" + _ctx_get(c, key, "solid sweep result")["body"]),
             _solid_tool_mass(case, "result"), None),
            ("model_inspect", lambda c, key=body_key, host=host: _combine_inspect(
                host + ":1:" + _ctx_get(c, key, "solid tool source")),
             _solid_tool_mass(case, "source", "st_" + case + "_shape"), None),
            ("model_inspect", lambda c: _combine_inspect(
                "SolidToolWitness:1:" + _ctx_get(c, "st_witness", "witness")),
             lambda p: _measured("unrelated witness unchanged by solid sweep", _sweep_mode_shape(p),
                 _sweep_mode_shape(p) == _RECALL.get("st_witness_shape")
                 and _sweep_mode_box_equal(_sweep_mode_shape(p),
                                           _RECALL.get("st_witness_shape") or {}, 0)), None),
        ])
    rows.extend([
        ("design_get", {"include": ["tree", "timeline"], "component": "SolidToolStraight",
                        "tree_bodies": True, "tree_handles": True, "max_results": 2000},
         lambda p: _measured("solid sweep refusal baseline", _solid_tool_census(p),
                             _solid_tool_census(p) is not None),
         ("st_guard", _recall("st_guard", _solid_tool_census))),
        ("model_sweep", lambda c: {"solid_body": "SolidToolStraight:1:" + _ctx_get(
            c, "st_straight_body", "solid tool source"),
                                   "path": "sketch:SolidToolStraightPath", "as_surface": True},
         _refused("as_surface"), None),
        ("design_get", {"include": ["tree", "timeline"], "component": "SolidToolStraight",
                        "tree_bodies": True, "tree_handles": True, "max_results": 2000},
         lambda p: _measured("invalid solid sweep left bodies and features unchanged",
                             _solid_tool_census(p),
                             _solid_tool_census(p) is not None
                             and _solid_tool_census(p) == _RECALL.get("st_guard")), None),
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ])
    return rows


_SOLID_TOOL = _solid_tool_rows() + _empty_solid_rows()


def _sweep_mode_expected_volume(case, stage):
    """Return the selected stock volume after clipping a circular sweep at x=0.05 cm."""
    radius = 0.1 if stage == "before" else 0.15
    length = 3.0 if stage == "path" else 2.0
    cap = 0.05
    disk = math.pi * radius * radius
    inside = (disk / 2 + cap * math.sqrt(radius * radius - cap * cap)
              + radius * radius * math.asin(cap / radius))
    return {"join": 1.65 + (disk - inside) * length,
            "cut": 1.65 - inside * length,
            "intersect": inside * length}[case]


def _sweep_mode_solid(case, stage, role, previous=None):
    """Require a selected volume change or a pristine independent witness read."""
    def check(p):
        got = _sweep_mode_shape(p)
        old = _RECALL.get(previous) if previous else None
        volume, area = got["volume"], got["area"]
        valid = (p.get("kind") == "body" and p.get("units") == "cm"
                 and (p.get("mass") or {}).get("accuracy_used") == "very_high"
                 and isinstance(volume, (int, float)) and math.isfinite(volume) and volume > 0
                 and isinstance(area, (int, float)) and math.isfinite(area) and area > 0
                 and _sweep_mode_box_equal(got, got)
                 and (previous is None or old is not None))
        if valid and role == "SelectedStock":
            valid = abs(volume - _sweep_mode_expected_volume(case, stage)) <= 0.002
        if valid and role != "SelectedStock":
            lo, hi, expected_volume = {
                "UnselectedStock": ((0.06, -0.5, 0), (0.6, 0.5, 3), 1.62),
                "OverlappingForeign": ((0.08, -0.5, 0), (0.3, 0.5, 3), 0.66),
            }[role]
            expected_box = {"min": dict(zip(("x", "y", "z"), lo)),
                            "max": dict(zip(("x", "y", "z"), hi))}
            valid = (abs(volume - expected_volume) <= 0.002
                     and _sweep_mode_box_equal(got, expected_box, 0.001))
        if old is not None and valid:
            if role == "SelectedStock":
                valid = (isinstance(old.get("volume"), (int, float))
                         and abs(volume - old["volume"]) > 0.0001)
            else:
                valid = (abs(volume - old["volume"]) <= 0.00001
                         and abs(area - old["area"]) <= 0.00001
                         and _sweep_mode_box_equal(got, old))
        return _measured(f"{case} {stage} {role} independent volume/bounds",
                         {"current": got, "previous": old,
                          "selected_expected_cm3": (_sweep_mode_expected_volume(case, stage)
                                                    if role == "SelectedStock" else None)}, valid)
    return check


def _sweep_mode_edit(case, action, surface=False):
    """Require one edit to retain its feature, scope, marker and readable body shape."""
    def check(p):
        after = p.get("target_after") or []
        shape = after[0] if len(after) == 1 else {}
        return _measured(f"{case} {action} sweep definition and participants", p,
                         p.get("edited") is True and p.get("action") == action
                         and p.get("same_feature") is True
                         and p.get("definition_matches") is True
                         and (p.get("definition_before") or {}).get("profile_members") == 1
                         and (p.get("definition_after") or {}).get("profile_members") == 1
                         and p.get("geometry_changed") is True
                         and p.get("participant_scope_preserved") is True
                         and p.get("participants_replayed") is (not surface)
                         and (all(key in p and p[key] is None for key in (
                             "retained_participants", "participants_before", "participants_after"))
                             and p.get("participant_scope_reason") ==
                             "The original NewBody sweep has no Boolean participant scope."
                              if surface else p.get("retained_participants") == ["SelectedStock"])
                         and p.get("marker_restored") is True
                         and p.get("outside_body_changes") == []
                         and p.get("new_timeline_errors") == []
                         and p.get("new_timeline_warnings") == []
                         and shape.get("solid") is (not surface)
                         and (shape.get("volume_cm3") is None if surface else
                              isinstance(shape.get("volume_cm3"), (int, float))))
    return check


def _sweep_mode_surface(case, stage, previous=None):
    """Require the independently found surface face area to change after each edit."""
    def check(p):
        rows = p.get("matches") or []
        row = rows[0] if len(rows) == 1 else {}
        area = row.get("area")
        old = _RECALL.get(previous) if previous else None
        valid = (p.get("units") == "cm" and p.get("match_count") == 1
                 and p.get("returned") == 1 and p.get("truncated") is not True
                 and isinstance(area, (int, float)) and math.isfinite(area) and area > 0
                 and (previous is None or old is not None))
        width = 0.2 if stage == "before" else 0.3
        length = 3.0 if stage == "path" else 2.0
        expected = width * length if case == "open" else math.pi * width * length
        if valid:
            valid = abs(area - expected) <= 0.005
        if old is not None and valid:
            valid = abs(area - old) > 0.01
        return _measured(f"{case} {stage} independent surface face area",
                         {"area_cm2": area, "expected_cm2": expected,
                          "previous_cm2": old}, valid)
    return check


def _sweep_mode_bounds(case, stage, previous=None):
    """Require a complete surface body box, changed after each edit."""
    def check(p):
        got = _sweep_mode_shape(p)
        old = _RECALL.get(previous) if previous else None
        valid = (p.get("kind") == "body" and p.get("units") == "cm"
                 and _sweep_mode_box_equal(got, got)
                 and (previous is None or old is not None))
        expected_x = 0.2 if stage == "before" else 0.3
        expected_z = 3.0 if stage == "path" else 2.0
        if valid:
            valid = (_near(p.get("x"), expected_x, 0.01)
                     and _near(p.get("z"), expected_z, 0.01))
        if old is not None and valid:
            valid = not _sweep_mode_box_equal(got, old, 0.01)
        return _measured(f"{case} {stage} independent surface bounds",
                         {"current": got, "x": p.get("x"), "z": p.get("z"),
                          "expected_x": expected_x, "expected_z": expected_z,
                          "previous": old}, valid)
    return check


def _sweep_edit_modes_rows():
    """Exercise scoped boolean and surface sweep edits in one owned scratch document."""
    rows = [("doc_get", {}, _home_document, ("sem_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "sem_story", "story")},
             _new_document, ("sem_doc", lambda p: p["document_handle"]))]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "sem_doc", args(c) if callable(args) else args), check, save))

    def read(name, args, check, save=None):
        rows.append((name, args, check, save))

    def box(component, name, low, high, key):
        sketch = component + name + "S"
        write("sketch_create", {"plane": "xy", "name": sketch})
        write("sketch_add_geometry", {"sketch_name": sketch, "geometry": [
            {"kind": "rectangle", "x1": low[0], "y1": low[1],
             "x2": high[0], "y2": high[1]}]})
        write("model_extrude", {"sketch_name": sketch, "profile_index": 0,
                                "distance": high[2]}, _extruded,
              (key, lambda p: p["result_bodies"][0]))
        write("design_set_name", lambda c: {
            "target": component + ":" + _ctx_get(c, key, "new stock body"),
            "new_name": name}, lambda p: p.get("renamed") is True and p.get("name") == name)

    def solid_read(case, stage, component, role, previous=None):
        key = f"sem_{case}_{stage}_{role}"
        read("model_inspect", {"target": f"{component}:{role}",
                               "include": ["default", "mass"], "units": "cm",
                               "accuracy": "very_high"},
             _sweep_mode_solid(case, stage, role, previous),
             (key, _recall(key, _sweep_mode_shape)))
        return key

    def surface_read(case, stage, component, face_kind, previous_area=None,
                     previous_bounds=None):
        target = f"{component}:SweepSheet"
        bkey, akey = f"sem_{case}_{stage}_bounds", f"sem_{case}_{stage}_area"
        read("model_inspect", {"target": target, "units": "cm"},
             _sweep_mode_bounds(case, stage, previous_bounds),
             (bkey, _recall(bkey, _sweep_mode_shape)))
        read("find_geometry", {"target": target, "kind": face_kind,
                               "units": "cm", "max_results": 2},
             _sweep_mode_surface(case, stage, previous_area),
             (akey, _recall(akey, lambda p: p["matches"][0]["area"])))
        return akey, bkey

    for case in ("join", "cut", "intersect"):
        host, foreign = "Sweep" + case.title(), "Foreign" + case.title()
        write("model_create_component", {"name": host, "activate": True}, _made_component)
        for name, radius in (("OriginalProfile", 1), ("AlternateProfile", 1.5)):
            write("sketch_create", {"plane": "xy", "name": name})
            write("sketch_add_geometry", {"sketch_name": name, "component": host, "geometry": [
                {"kind": "circle", "cx": 0, "cy": 0, "radius": radius}]})
        for name, length in (("OriginalPath", 20), ("AlternatePath", 30)):
            write("sketch_create", {"plane": "xz", "name": name})
            write("sketch_add_geometry", {"sketch_name": name, "component": host, "geometry": [
                {"kind": "line", "x1": 0, "y1": 0, "x2": 0, "y2": -length}]})
        for role, lo, hi in (
                ("SelectedStock", (-5, -5, 0), (0.5, 5, 30)),
                ("UnselectedStock", (0.6, -5, 0), (6, 5, 30))):
            box(host, role, lo, hi, f"sem_{case}_{role}_body")
        write("design_activate_component", {"occurrence": "root"})
        write("model_create_component", {"name": foreign, "activate": True}, _made_component)
        for role, lo, hi in (
                ("OverlappingForeign", (0.8, -5, 0), (3, 5, 30)),):
            box(foreign, role, lo, hi, f"sem_{case}_{role}_body")
        write("design_activate_component", {"occurrence": host + ":1"})
        feature_key = f"sem_{case}_feature"
        write("model_sweep", {"profile": {"sketch": "OriginalProfile", "profile_index": 0},
                              "path": "sketch:OriginalPath", "operation": case,
                              "target_bodies": [f"{host}:SelectedStock"], "component": host},
              lambda p, case=case, host=host: _measured(
                  f"{case} scoped sweep created", p,
                  p.get("swept") is True and p.get("operation") == case
                  and p.get("component") == host
                  and p.get("scoped_to_bodies") == ["SelectedStock"]
                  and p.get("is_solid") is True and bool(p.get("result_bodies"))),
              (feature_key, lambda p, host=host: host + "/" + p["feature"]))
        roles = ((host, "SelectedStock"), (host, "UnselectedStock"),
                 (foreign, "OverlappingForeign"))
        before = {role: solid_read(case, "before", component, role)
                  for component, role in roles}
        for action, operand in (("profile", {"sketch": "AlternateProfile", "profile_index": 0}),
                                ("path", "sketch:AlternatePath")):
            write("model_edit_sweep", lambda c, action=action, operand=operand, host=host,
                  feature_key=feature_key: {
                      "feature": _ctx_get(c, feature_key, "scoped sweep feature"),
                      "action": action, action: operand,
                      **({"component": host} if action == "profile" else {})},
                  _sweep_mode_edit(case, action))
            stage = action
            for component, role in roles:
                prior = before[role]
                before[role] = solid_read(case, stage, component, role, prior)
        write("design_activate_component", {"occurrence": "root"})

    for case, face_kind in (("open", "planar_face"), ("closed", "cylinder_face")):
        host = "Surface" + case.title()
        write("model_create_component", {"name": host, "activate": True}, _made_component)
        for name, width in (("OriginalProfile", 2), ("AlternateProfile", 3)):
            write("sketch_create", {"plane": "xy", "name": name})
            geometry = ({"kind": "line", "x1": 0, "y1": 0, "x2": width, "y2": 0}
                        if case == "open" else
                        {"kind": "circle", "cx": 0, "cy": 0, "radius": width / 2})
            write("sketch_add_geometry", {"sketch_name": name, "component": host, "geometry": [geometry]})
        for name, length in (("OriginalPath", 20), ("AlternatePath", 30)):
            write("sketch_create", {"plane": "xz", "name": name})
            write("sketch_add_geometry", {"sketch_name": name, "component": host, "geometry": [
                {"kind": "line", "x1": 0, "y1": 0, "x2": 0, "y2": -length}]})
        feature_key, body_key = f"sem_{case}_feature", f"sem_{case}_body"

        def surface_refs(p, host=host, body_key=body_key):
            _RECALL[body_key] = p["result_bodies"][0]
            return host + "/" + p["feature"]

        write("model_sweep", {"profile": {"sketch": "OriginalProfile", "profile_index": 0},
                              "path": "sketch:OriginalPath", "as_surface": True,
                              "component": host},
              lambda p, case=case, host=host: _measured(
                  f"{case} surface sweep created", p,
                  p.get("swept") is True and p.get("component") == host
                  and p.get("is_solid") is False
                  and p.get("as_surface") is True
                  and len(p.get("result_bodies") or []) == 1),
              (feature_key, surface_refs))
        write("design_set_name", lambda c, host=host, body_key=body_key: {
            "target": host + ":" + _RECALL[body_key],
            "new_name": "SweepSheet"},
            lambda p: p.get("renamed") is True and p.get("name") == "SweepSheet")
        area, bounds = surface_read(case, "before", host, face_kind)
        for action, operand in (("profile", {"sketch": "AlternateProfile", "profile_index": 0}),
                                ("path", "sketch:AlternatePath")):
            write("model_edit_sweep", lambda c, action=action, operand=operand, host=host,
                  feature_key=feature_key: {
                      "feature": _ctx_get(c, feature_key, "surface sweep feature"),
                      "action": action, action: operand,
                      **({"component": host} if action == "profile" else {})},
                  _sweep_mode_edit(case, action, surface=True))
            area, bounds = surface_read(case, action, host, face_kind, area, bounds)
        write("design_activate_component", {"occurrence": "root"})

    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "sem_story", "story"),
                                         "expect_document": _ctx_get(c, "sem_doc", "sweep modes")},
              "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "sem_doc", "sweep modes"),
                                      "save_changes": False,
                                      "expect_document": _ctx_get(c, "sem_story", "story")},
              _document_closed, None)]
    return rows


_SWEEP_EDIT_MODES = _sweep_edit_modes_rows()


def _sweep_scope_mass(expected, key, result_name_key=None):
    """Require the named solid-body volumes in an independent complete mass read."""
    def check(p):
        mass = p.get("mass") or {}
        want = dict(expected)
        if result_name_key:
            result_name = _RECALL.get(result_name_key)
            if not isinstance(result_name, str) or not result_name:
                return _measured("independent complete sweep body volumes",
                                 {"expected_mm3": want, "result_name": result_name}, False)
            want[result_name] = want.pop("$result")
        rows = mass.get("per_body")
        volumes = ({row.get("body"): row.get("volume") for row in rows
                    if isinstance(row, dict) and row.get("body")}
                   if isinstance(rows, list) else {})
        valid = (p.get("kind") == "design" and p.get("units") == "mm"
                 and mass.get("accuracy_used") == "very_high"
                 and isinstance(rows, list) and mass.get("per_body_count") == len(rows)
                 and mass.get("per_body_truncated") is False
                 and len(volumes) == len(rows) and set(volumes) == set(want)
                 and all(_near(volumes.get(name), value, 0.002)
                         for name, value in want.items()))
        if valid:
            _RECALL[key] = dict(volumes)
        return _measured("independent complete sweep body volumes", {
            "expected_mm3": want, "actual_mm3": volumes,
            "count": mass.get("per_body_count"),
            "truncated": mass.get("per_body_truncated")}, valid)
    return check


def _sweep_scope_end_health():
    """Check the independent end-position timeline health census."""
    def check(p):
        timeline = p.get("timeline") or {}
        rows = timeline.get("timeline") or []
        valid = (timeline.get("count") == timeline.get("returned") == len(rows)
                 and timeline.get("truncated") is not True
                 and timeline.get("marker_position") == timeline.get("count")
                 and [row.get("index") for row in rows] == list(range(len(rows)))
                 and (timeline.get("summary") or {}).get("states") == {"healthy": len(rows)}
                 and (timeline.get("summary") or {}).get("exceptions") == []
                 and all(row.get("is_rolled_back", False) is False
                         and row.get("health", "healthy") == "healthy" for row in rows))
        return _measured("independent healthy end-position timeline", timeline, valid)
    return check


def _sweep_scope_definition(feature_ref, operation, participants=None, previous=False):
    """Check the independent typed feature definition, identity, and healthy timeline."""
    def check(p):
        feature_name = _RECALL.get(feature_ref, feature_ref)
        definition, timeline = p.get("definition") or {}, p.get("timeline") or {}
        rows = timeline.get("timeline") or []
        found = [row for row in rows if row.get("name") == feature_name
                 and row.get("type") == "SweepFeature"]
        identity = {key: definition.get(key) for key in
                    ("feature", "component", "type", "timeline_index")}
        identity_key = "sweep_scope_identity_" + feature_name
        old = _RECALL.get(identity_key) if previous else None
        got_participants = definition.get("participants")
        orientation_ok = definition.get("orientation_name") == "perpendicular"
        if feature_name == "R7Sweep":
            orientation_ok = (definition.get("orientation") is None
                              and definition.get("orientation_name") is None
                              and definition.get("unavailable")
                              == {"orientation": "2 : InternalValidationError : false"})
        valid = (definition.get("feature") == feature_name
                 and definition.get("type") == "SweepFeature"
                 and definition.get("operation") == operation
                 and definition.get("is_solid") is True
                 and orientation_ok
                 and definition.get("path_count") == 1
                 and definition.get("path_truncated") is False
                 and isinstance(definition.get("timeline_index"), int)
                 and timeline.get("count") == timeline.get("returned") == len(rows)
                 and timeline.get("truncated") is not True
                 and timeline.get("marker_position") == definition.get("timeline_index")
                 and [row.get("index") for row in rows] == list(range(len(rows)))
                 and len(found) == 1 and found[0].get("index") == definition.get("timeline_index")
                 and all(row.get("is_rolled_back", False) is False
                         and row.get("health", "healthy") == "healthy"
                         for row in rows if isinstance(row.get("index"), int)
                         and row["index"] < definition.get("timeline_index"))
                 and all(row.get("is_rolled_back") is True
                         for row in rows if isinstance(row.get("index"), int)
                         and row["index"] >= definition.get("timeline_index"))
                 and (participants is None or isinstance(got_participants, list)
                      and definition.get("participants_truncated") is False
                      and set(got_participants) == set(participants))
                 and (not previous or old is not None and identity == old))
        if valid and not previous:
            _RECALL[identity_key] = identity
        return _measured("independent Sweep definition and healthy timeline", {
            "definition": definition, "timeline_count": timeline.get("count"),
            "timeline_feature": found, "previous_identity": old}, valid)
    return check


def _sweep_scope_marker(stage, feature_ref):
    """Require a measured feature-row roll before the public definition read and end afterward."""
    def check(p):
        feature_name = _RECALL.get(feature_ref, feature_ref)
        if stage == "before":
            valid = (p.get("rolled") is True and p.get("to") == "before"
                     and p.get("feature") == feature_name
                     and _num(p.get("marker_position"))
                     and _num(p.get("timeline_count"))
                     and p["marker_position"] < p["timeline_count"]
                     and p.get("rolled_back") == p["timeline_count"] - p["marker_position"])
        else:
            valid = (p.get("rolled") is True and p.get("to") == "end"
                     and p.get("marker_position") == p.get("timeline_count")
                     and p.get("rolled_back") == 0)
        return _measured("Sweep public definition marker " + stage, p, valid)
    return check


def _sweep_scope_edit(action, stage, feature_ref, participant_names=None):
    """Check an edit's actual operand, participant scope, and result-body read-back."""
    def check(p):
        feature_name = _RECALL.get(feature_ref, feature_ref)
        before, after = p.get("definition_before") or {}, p.get("definition_after") or {}
        identity = _RECALL.get("sweep_scope_identity_" + feature_name)
        requested = p.get("requested_participants")
        prior = p.get("participants_before")
        actual = p.get("participants_after")
        requested_names = ({row.get("name") for row in requested or []}
                           if isinstance(requested, list) else set())
        actual_names = ({row.get("name") for row in actual or []}
                        if isinstance(actual, list) else set())
        before_names = ({row.get("name") for row in prior or []}
                        if isinstance(prior, list) else set())
        requested_tokens = ({row.get("token") for row in requested or []}
                            if isinstance(requested, list) else set())
        actual_tokens = ({row.get("token") for row in actual or []}
                         if isinstance(actual, list) else set())
        if action == "guide_path":
            old_sig, new_sig = before.get("guide_path_signature"), after.get("guide_path_signature")
            if stage == "replace" and old_sig:
                _RECALL["sweep_scope_guide_original"] = old_sig
            expected_sig = (_RECALL.get("sweep_scope_guide_original") if stage == "restore" else None)
            specific = (before.get("guide_path_curves") == after.get("guide_path_curves") == 1
                        and isinstance(old_sig, str) and isinstance(new_sig, str)
                        and p.get("participant_scope_preserved") is True
                        and (old_sig != new_sig if stage == "replace" else new_sig == expected_sig))
        else:
            specific = (p.get("participant_scope_matches_request") is True
                        and p.get("participant_scope_preserved") is None
                        and isinstance(requested, list) and isinstance(actual, list)
                        and requested_names == set(participant_names or ())
                        and actual_names == requested_names
                        and len(requested_tokens) == len(requested)
                        and actual_tokens == requested_tokens
                        and all(isinstance(row.get("token"), str) and row.get("token")
                                and row.get("component") for row in requested + actual)
                        and (action != "participants"
                             or isinstance(prior, list) and before_names
                             and before_names != actual_names))
            if action == "operation":
                before_results = p.get("result_bodies_before")
                after_results = p.get("result_bodies_after")
                before_tokens = ({row.get("token") for row in before_results}
                                 if isinstance(before_results, list) else set())
                after_identity = ({(row.get("name"), row.get("token"), row.get("component"))
                                   for row in after_results}
                                  if isinstance(after_results, list) else set())
                participant_identity = ({(row.get("name"), row.get("token"), row.get("component"))
                                         for row in actual}
                                        if isinstance(actual, list) else set())
                result_rows = ((before_results if isinstance(before_results, list) else [])
                               + (after_results if isinstance(after_results, list) else []))
                specific = (specific and prior is None
                            and isinstance(before_results, list) and len(before_results) == 1
                            and isinstance(after_results, list) and isinstance(actual, list)
                            and len(after_results) == len(actual)
                            and all(isinstance(row.get("name"), str) and row.get("name")
                                    and isinstance(row.get("token"), str) and row.get("token")
                                    and row.get("component") for row in result_rows)
                            and after_identity == participant_identity
                            and before_tokens.isdisjoint({row[1] for row in after_identity}))
            elif action == "participants":
                before_results = p.get("result_bodies_before")
                after_results = p.get("result_bodies_after")
                rows = ((before_results if isinstance(before_results, list) else [])
                        + (after_results if isinstance(after_results, list) else []))
                specific = (specific and isinstance(before_results, list)
                            and isinstance(after_results, list)
                            and all(isinstance(row.get("name"), str) and row.get("name")
                                    and isinstance(row.get("token"), str) and row.get("token")
                                    and row.get("component") for row in rows))
        return _measured("public Sweep edit read-back and named scope", p,
                         p.get("edited") is True and p.get("action") == action
                         and p.get("same_feature") is True
                         and p.get("definition_matches") is True
                         and p.get("geometry_changed") is True
                         and p.get("marker_restored") is True
                         and p.get("new_timeline_errors") == []
                         and p.get("new_timeline_warnings") == []
                         and p.get("outside_body_changes") == []
                         and specific and identity is not None)
    return check


_SWEEP_GUIDE_CENSUS = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    feature = adsk.fusion.SweepFeature.cast(root.features.itemByName('R7Sweep'))
    if feature is None:
        raise RuntimeError('R7Sweep is unreadable')
    marker = design.timeline.markerPosition
    try:
        if feature.timelineObject.rollTo(True) is not True:
            raise RuntimeError('R7Sweep could not be rolled for guide read-back')
        rail = feature.guideRail
        count = 0 if rail is None else rail.count
        guide = [] if rail is None else [
            {'type': rail.item(i).entity.objectType,
             'sketch': rail.item(i).entity.parentSketch.name} for i in range(count)]
    finally:
        design.timeline.markerPosition = marker
    print(json.dumps({'feature': feature.name, 'index': feature.timelineObject.index,
        'count': design.timeline.count, 'marker_before': marker,
        'marker_after': design.timeline.markerPosition, 'guide': guide,
        'health': int(feature.healthState)}))
"""


def _sweep_scope_guide_census(expected_sketch):
    """Check the native guide source independently and require the timeline marker restored."""
    def check(p):
        rows = p.get("guide") or []
        return _measured("independent native guide-rail source and restored marker", p,
                         p.get("feature") == "R7Sweep" and p.get("index") == 4
                         and p.get("count") == 7 and p.get("marker_before") == 7
                         and p.get("marker_after") == 7 and p.get("health") == 0
                         and len(rows) == 1 and rows[0].get("type") == "adsk::fusion::SketchLine"
                         and rows[0].get("sketch") == expected_sketch)
    return check


_SWEEP_GUIDE_FIXTURE = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    if app.activeDocument.dataFile is not None:
        raise RuntimeError('R7 requires the owned unsaved scratch')
    design = adsk.fusion.Design.cast(app.activeProduct)
    if (design is None or design.designType != adsk.fusion.DesignTypes.ParametricDesignType
            or design.activeComponent != design.rootComponent
            or design.timeline.markerPosition != design.timeline.count):
        raise RuntimeError('R7 requires root active and the marker at the end')
    root = design.rootComponent
    section = root.sketches.add(root.xYConstructionPlane)
    section.name = 'R7Section'
    section.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(0, 0, 0), adsk.core.Point3D.create(0.4, 0.2, 0))
    if section.profiles.count != 1:
        raise RuntimeError('R7 section must have one profile')
    main_sketch = root.sketches.add(root.yZConstructionPlane)
    main_sketch.name = 'R7MainPath'
    main_line = main_sketch.sketchCurves.sketchLines.addByTwoPoints(
        main_sketch.modelToSketchSpace(adsk.core.Point3D.create(0, 0, 0)),
        main_sketch.modelToSketchSpace(adsk.core.Point3D.create(0, 0, 3)))
    main_path = root.features.createPath(main_line, False)
    if main_line is None or main_path is None or main_path.count != 1:
        raise RuntimeError('R7 main path must have one curve')
    def rail(name, start_x, end_x):
        sketch = root.sketches.add(root.xZConstructionPlane)
        sketch.name = name
        line = sketch.sketchCurves.sketchLines.addByTwoPoints(
            sketch.modelToSketchSpace(adsk.core.Point3D.create(start_x, 0, 0)),
            sketch.modelToSketchSpace(adsk.core.Point3D.create(end_x, 0, 3)))
        return root.features.createPath(line, False)
    original = rail('R7RailOriginal', 0.4, 0.4)
    replacement = rail('R7RailReplacement', 0.4, 0.8)
    if original is None or replacement is None or original.count != 1 or replacement.count != 1:
        raise RuntimeError('R7 replacement rails must each have one curve')
    inp = root.features.sweepFeatures.createInput(
        section.profiles.item(0), main_path, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.guideRail = original
    feature = root.features.sweepFeatures.add(inp)
    if feature is None or feature.bodies.count != 1:
        raise RuntimeError('R7 guided sweep must create one result body')
    feature.name = 'R7Sweep'
    body = feature.bodies.item(0)
    body.name = 'R7SweepBody'
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.name = 'R7ControlSketch'
    sk.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(10, 0, 0), adsk.core.Point3D.create(11, 1, 0))
    ex_in = root.features.extrudeFeatures.createInput(
        sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    if ex_in.setDistanceExtent(False, adsk.core.ValueInput.createByString('10 mm')) is not True:
        raise RuntimeError('R7 control extrusion extent was refused')
    ex = root.features.extrudeFeatures.add(ex_in)
    if ex is None or ex.bodies.count != 1:
        raise RuntimeError('R7 control must create one body')
    control = ex.bodies.item(0)
    control.name = 'R7Control'
    print(json.dumps({'feature': feature.name, 'body': body.name,
        'control': control.name, 'original_count': original.count,
        'replacement_count': replacement.count, 'marker': design.timeline.markerPosition,
        'count': design.timeline.count}))
"""


def _sweep_scope_edit_rows():
    """Exercise measured guided-rail, New-to-Cut, and Cut participant edits with public reads."""
    rows = []

    def session(tag, title):
        rows.extend([("doc_get", {}, _home_document, (tag + "_home", _home_address)),
                     ("doc_new", lambda c, tag=tag: {"expect_document": _ctx_get(
                         c, tag + "_home", "home document")}, _new_document,
                      (tag + "_doc", lambda p: p["document_handle"]))])

    def write(tag, name, args, check="ok", save=None):
        rows.append((name, lambda c, tag=tag, args=args: _combine_pin(
            c, tag + "_doc", args(c) if callable(args) else args), check, save))

    def read(name, args, check, save=None):
        rows.append((name, args, check, save))

    def definition_read(tag, feature_arg, feature_ref, operation, participants=None, previous=False):
        args = feature_arg if callable(feature_arg) else lambda _c, value=feature_arg: value
        write(tag, "design_edit_timeline", lambda c, a=args: {
            "action": "roll", "feature": a(c), "to": "before"},
            _sweep_scope_marker("before", feature_ref))
        read("design_get", lambda c, a=args: {"include": ["definition", "timeline"],
             "feature": a(c), "units": "mm", "max_results": 200},
             _sweep_scope_definition(feature_ref, operation, participants, previous))
        write(tag, "design_edit_timeline", {"action": "roll", "to": "end"},
              _sweep_scope_marker("end", feature_ref))
        read("design_get", {"include": ["timeline"], "max_results": 200},
             _sweep_scope_end_health())

    def body_box(tag, name, x1, y1, x2, y2, thickness, symmetric=False):
        sketch = name + "Sketch"
        write(tag, "sketch_create", {"plane": "xy", "name": sketch})
        write(tag, "sketch_add_geometry", {"sketch_name": sketch, "units": "mm",
              "geometry": [{"kind": "rectangle", "x1": x1, "y1": y1,
                            "x2": x2, "y2": y2}]})
        key = tag + "_body_name_" + name
        write(tag, "model_extrude", {"sketch_name": sketch, "distance": thickness,
              "symmetric": symmetric, "units": "mm"}, _extruded,
              (key, _recall(key, lambda p: p["result_bodies"][0])))
        write(tag, "design_set_name", lambda c, name=name, key=key: {
              "target": _ctx_get(c, key, name + " extrusion body"), "new_name": name},
              lambda p, name=name: p.get("renamed") is True and p.get("name") == name)

    def remember_sweep(feature_key, result_key=None):
        def save(p):
            name = p.get("feature")
            result_bodies = p.get("result_bodies") or []
            if isinstance(name, str) and name:
                _RECALL[feature_key] = name
            if result_key and len(result_bodies) == 1 and isinstance(result_bodies[0], str):
                _RECALL[result_key] = result_bodies[0]
            return name
        return save

    def sketch_sweep_setup(tag, feature_key, section_half, path_start, path_end,
                           operation, targets=None, result_key=None):
        write(tag, "model_construction", {"kind": "plane", "mode": "offset", "plane": "yz",
              "offset": -5, "units": "mm", "name": tag + "SectionPlane"}, _datum_plane("yz"))
        write(tag, "sketch_create", {"plane": tag + "SectionPlane", "name": tag + "Section"})
        write(tag, "sketch_add_geometry", {"sketch_name": tag + "Section", "units": "mm",
              "geometry": [{"kind": "rectangle", "x1": -section_half, "y1": -section_half,
                            "x2": section_half, "y2": section_half}]})
        write(tag, "sketch_create", {"plane": "xy", "name": tag + "Path"})
        write(tag, "sketch_add_geometry", {"sketch_name": tag + "Path", "units": "mm",
              "geometry": [{"kind": "line", "x1": path_start, "y1": 0,
                            "x2": path_end, "y2": 0}]})
        args = {"profile": {"sketch": tag + "Section", "profile_index": 0},
                "path": "sketch:" + tag + "Path", "operation": operation}
        if targets:
            args["target_bodies"] = targets
        write(tag, "model_sweep", args,
              lambda p, tag=tag, operation=operation, targets=targets: _measured(
                  "public model_sweep fixture creation", p,
                  p.get("swept") is True and p.get("operation") == operation
                  and p.get("component") and p.get("is_solid") is True
                  and (targets is None or p.get("scoped_to_bodies") == targets)
                  and isinstance(p.get("feature"), str) and bool(p.get("feature"))
                  and bool(p.get("result_bodies"))),
              (feature_key, remember_sweep(feature_key, result_key)))

    def read_mass(tag, expected, suffix):
        read("model_inspect", {"target": "", "include": ["default", "mass"],
             "per_body": True, "accuracy": "very_high", "units": "mm"},
             _sweep_scope_mass(expected, tag + "_" + suffix))

    def finish(tag, title):
        rows.extend([("doc_activate", lambda c, tag=tag: {
                     "name": _ctx_get(c, tag + "_home", "home document"),
                     "expect_document": _ctx_get(c, tag + "_doc", title)}, "ok", None),
                     ("doc_close", lambda c, tag=tag: {
                     "name": _ctx_get(c, tag + "_doc", title), "save_changes": False,
                     "expect_document": _ctx_get(c, tag + "_home", "home document")},
                      _document_closed, None)])

    # model_sweep has no guideRail creation input, so this one measured fixture uses native setup;
    # every edit and independent material/definition check is still through the registered tools.
    tag = "scope_r7"
    session(tag, "R7 guided scratch")
    write(tag, "sys_execute_script", {"script": _SWEEP_GUIDE_FIXTURE, "read_only": False},
          lambda p: _measured("measured R7 one-curve guided fixture", p,
                              p.get("feature") == "R7Sweep" and p.get("body") == "R7SweepBody"
                              and p.get("control") == "R7Control"
                              and p.get("original_count") == p.get("replacement_count") == 1
                              and p.get("marker") == p.get("count")))
    read_mass(tag, {"R7SweepBody": 240, "R7Control": 1000}, "before")
    definition_read(tag, "R7Sweep", "R7Sweep", "new")
    write(tag, "sys_execute_script", {"script": _SWEEP_GUIDE_CENSUS, "read_only": False},
          _sweep_scope_guide_census("R7RailOriginal"))
    write(tag, "model_edit_sweep", {"feature": "R7Sweep", "action": "guide_path",
          "path": "sketch:R7RailReplacement"}, _sweep_scope_edit("guide_path", "replace", "R7Sweep"))
    read_mass(tag, {"R7SweepBody": 560, "R7Control": 1000}, "replacement")
    definition_read(tag, "R7Sweep", "R7Sweep", "new", previous=True)
    write(tag, "sys_execute_script", {"script": _SWEEP_GUIDE_CENSUS, "read_only": False},
          _sweep_scope_guide_census("R7RailReplacement"))
    write(tag, "model_edit_sweep", {"feature": "R7Sweep", "action": "guide_path",
          "path": "sketch:R7RailOriginal"}, _sweep_scope_edit("guide_path", "restore", "R7Sweep"))
    read_mass(tag, {"R7SweepBody": 240, "R7Control": 1000}, "restore")
    definition_read(tag, "R7Sweep", "R7Sweep", "new", previous=True)
    write(tag, "sys_execute_script", {"script": _SWEEP_GUIDE_CENSUS, "read_only": False},
          _sweep_scope_guide_census("R7RailOriginal"))
    finish(tag, "R7 guided scratch")

    tag = "scope_r8"
    session(tag, "R8 operation scratch")
    body_box(tag, "R8Box", 0, -10, 40, 10, 5, symmetric=True)
    body_box(tag, "R8Control", 100, 0, 110, 10, 10)
    sweep_key = tag + "_feature"
    result_key = tag + "_result_body"
    sketch_sweep_setup(tag, sweep_key, 2, -5, 45, "new", result_key=result_key)
    read("model_inspect", {"target": "", "include": ["default", "mass"],
         "per_body": True, "accuracy": "very_high", "units": "mm"},
         _sweep_scope_mass({"R8Box": 8000, "R8Control": 1000, "$result": 800},
                           tag + "_before", result_key))
    definition_read(tag, lambda c, key=sweep_key: _ctx_get(c, key, "Sweep feature"),
                    sweep_key, "new")
    write(tag, "model_edit_sweep", lambda c, key=sweep_key: {"feature": _ctx_get(c, key, "Sweep"),
          "action": "operation", "operation": "cut", "target_bodies": ["R8Box"]},
          _sweep_scope_edit("operation", "cut", sweep_key, ("R8Box",)))
    read_mass(tag, {"R8Box": 7360, "R8Control": 1000}, "cut")
    definition_read(tag, lambda c, key=sweep_key: _ctx_get(c, key, "Sweep feature"), sweep_key,
                    "cut", ("R8Box",), previous=True)
    # Cut-to-New is not admitted; discard this scratch instead of asserting output identity or reversing it.
    finish(tag, "R8 operation scratch")

    tag = "scope_r9"
    session(tag, "R9 participant scratch")
    body_box(tag, "R9A", 0, -5, 10, 5, 5, symmetric=True)
    body_box(tag, "R9B", 20, -5, 30, 5, 5, symmetric=True)
    body_box(tag, "R9Control", 100, -5, 110, 5, 5, symmetric=True)
    sweep_key = tag + "_feature"
    sketch_sweep_setup(tag, sweep_key, 1, -5, 35, "cut", ["R9A"])
    read_mass(tag, {"R9A": 960, "R9B": 1000, "R9Control": 1000}, "before")
    definition_read(tag, lambda c, key=sweep_key: _ctx_get(c, key, "Sweep feature"),
                    sweep_key,
                    "cut", ("R9A",))
    write(tag, "model_edit_sweep", lambda c, key=sweep_key: {"feature": _ctx_get(c, key, "Sweep"),
          "action": "participants", "target_bodies": ["R9B"]},
          _sweep_scope_edit("participants", "retarget", sweep_key, ("R9B",)))
    read_mass(tag, {"R9A": 1000, "R9B": 960, "R9Control": 1000}, "retarget")
    definition_read(tag, lambda c, key=sweep_key: _ctx_get(c, key, "Sweep feature"),
                    sweep_key,
                    "cut", ("R9B",), previous=True)
    write(tag, "model_edit_sweep", lambda c, key=sweep_key: {"feature": _ctx_get(c, key, "Sweep"),
          "action": "participants", "target_bodies": ["R9A"]},
          _sweep_scope_edit("participants", "restore", sweep_key, ("R9A",)))
    read_mass(tag, {"R9A": 960, "R9B": 1000, "R9Control": 1000}, "restore")
    definition_read(tag, lambda c, key=sweep_key: _ctx_get(c, key, "Sweep feature"),
                    sweep_key,
                    "cut", ("R9A",), previous=True)
    finish(tag, "R9 participant scratch")
    return rows


_SWEEP_EDIT_MODES += _sweep_scope_edit_rows()


class _FilletRadiusRefusal(_Refusal):
    """Capture the numeric solved radius for comparison with an independent sketch read."""
    def __init__(self, key):
        super().__init__(("requested 20 mm", "REMAINS", "arc:0", "line:0", "line:1", "sketch_get"))
        self.key = key

    def missing(self, text):
        _RECALL.pop(self.key, None)
        missing = super().missing(text)
        match = re.search(r"\bsolved (\S+) mm\b", text)
        try:
            radius = float(match[1]) if match else None
        except ValueError:
            radius = None
        if radius is None or not math.isfinite(radius) or radius <= 0:
            missing.append("finite positive solved radius in mm")
        elif not missing:
            _RECALL[self.key] = radius
        return missing


def _tangent_path_expected(p):
    """Derive tube volume and terminal point from the independently read, solved sketch."""
    entities = {e["id"]: e for e in p.get("entities") or []}
    first, last, arc = (entities.get(key) or {} for key in ("line:0", "line:1", "arc:0"))
    valid = (p.get("units") == "mm" and not p.get("truncated")
             and (p.get("counts") or {}).get("lines") == 2
             and (p.get("counts") or {}).get("arcs") == 1)
    _measured("filleted path has two solved lines and one arc", p.get("counts"), valid)
    reported = _RECALL.get("tp_fillet_reported_radius")
    _measured("reported fillet radius matches independent sketch read",
              {"reported": reported, "radius": arc.get("radius")},
              _num(reported) and _near(arc.get("radius"), reported, .001))
    points = [tuple(row[side][a] for a in ("x", "y"))
              for row in (first, last) for side in ("start", "end")]
    center = tuple(arc["center"][a] for a in ("x", "y"))
    vectors = [tuple(pt[i] - center[i] for i in (0, 1)) for pt in (points[1], points[2])]
    norms = [math.hypot(*v) for v in vectors]
    _measured("solved arc joins both line ends", {"norms": norms, "radius": arc.get("radius")},
              all(_near(n, arc.get("radius"), 0.01) and n > 0 for n in norms))
    angle = math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(*vectors))
                                   / (norms[0] * norms[1]))))
    length = math.dist(points[0], points[1]) + arc["radius"] * angle + math.dist(points[2], points[3])
    return {"volume": math.pi * 4 * length, "end": [*points[3], 0]}


def _tangent_path_mass(expected):
    """Check the swept body's volume and terminal extent against the solved path."""
    def check(p):
        want = _RECALL[expected]
        mass, lo, hi = p.get("mass") or {}, p.get("min_point") or {}, p.get("max_point") or {}
        valid = (p.get("kind") == "body" and p.get("units") == "mm"
                 and _near(mass.get("volume"), want["volume"], want["volume"] * 0.003)
                 and _num(hi.get("x")) and hi["x"] >= want["end"][0] - 0.1
                 and _num(lo.get("y")) and lo["y"] <= want["end"][1] + 0.1
                 and _near(lo.get("z"), -2, 0.05) and _near(hi.get("z"), 2, 0.05))
        return _measured("full path independent tube volume and terminal extent",
                         {"volume": mass.get("volume"), "min": lo, "max": hi, "expected": want}, valid)
    return check


def _tangent_path_end(expected):
    """Check an independently found end cap reaches the path's solved terminal point."""
    def check(p):
        want = _RECALL[expected]["end"]
        matches = p.get("matches") or []
        hits = [r for r in matches if isinstance(r.get("position"), list)
                and len(r["position"]) == 3
                and all(_near(a, b, 0.1) for a, b in zip(r["position"], want))
                and _near(r.get("area"), math.pi * 4, 0.1)]
        return _measured("sweep end cap reaches independently solved path end",
                         {"end": want, "matches": matches}, len(hits) == 1)
    return check


def _tangent_path_rows():
    """Exercise fillet-chain completion, separate coincident lines and construction refusal."""
    rows = [("doc_get", {}, _home_document, ("tp_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "tp_story", "story")},
             _new_document, ("tp_doc", lambda p: p["document_handle"]))]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "tp_doc", args(c) if callable(args) else args), check, save))

    write("model_construction", {"kind": "plane", "plane": "yz", "offset": 10,
                                 "name": "PathStartPlane"}, _datum_plane("yz"))
    for name, y in (("FilletProfile", -30), ("SeparateProfile", 0)):
        write("sketch_create", {"plane": "PathStartPlane", "name": name})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [
            {"kind": "circle", "cx": 0, "cy": y, "radius": 2}]})
    write("sketch_create", {"plane": "xy", "name": "FilletPath"})
    write("sketch_add_geometry", {"sketch_name": "FilletPath", "geometry": [
        {"kind": "polyline", "points": [[10, -30], [220, -30], [260, -55]]}]})
    write("sketch_edit_curve", {"sketch_name": "FilletPath", "action": "fillet",
                                "entity_one": "line:0", "entity_two": "line:1", "radius": 20,
                                "x1": 200, "y1": -30, "x2": 230, "y2": -36},
          _FilletRadiusRefusal("tp_fillet_reported_radius"))
    rows.append(("sketch_get", {"sketch_name": "FilletPath", "include_entities": True},
                 lambda p: bool(_tangent_path_expected(p)),
                 ("tp_fillet_shape", _recall("tp_fillet_shape", _tangent_path_expected))))
    write("sketch_create", {"plane": "xy", "name": "SeparatePath"})
    for start, end in ((10, 30), (30, 50)):
        write("sketch_add_geometry", {"sketch_name": "SeparatePath", "geometry": [
            {"kind": "line", "x1": start, "y1": 0, "x2": end, "y2": 0}]})
    rows.append(("sketch_get", {"sketch_name": "SeparatePath", "include_entities": True},
                 lambda p: _measured("two separately drawn coincident lines", p.get("counts"),
                                     (p.get("counts") or {}).get("lines") == 2),
                 ("tp_separate_shape", _recall("tp_separate_shape", lambda p: {
                     "volume": math.pi * 4 * 40, "end": [50, 0, 0]}))))
    for case, curves in (("Fillet", 3), ("Separate", 2)):
        key = "tp_" + case.lower()
        write("model_sweep", {"profile": {"sketch": case + "Profile", "profile_index": 0},
                              "path": "sketch:" + case + "Path"},
              lambda p, curves=curves: _measured("sweep covers every intended path curve", p,
                  p.get("swept") is True and p.get("is_solid") is True
                  and p.get("path_curves") == p.get("path_sketch_curves") == curves
                  and len(p.get("result_bodies") or []) == 1 and "WARNING" not in p.get("note", "")),
              (key + "_body", lambda p: p["result_bodies"][0]))
        rows.append(("model_inspect", lambda c, key=key: {
            "target": _ctx_get(c, key + "_body", "swept body"), "include": ["default", "mass"],
            "units": "mm", "accuracy": "very_high"}, _tangent_path_mass(key + "_shape"), None))
        rows.append(("find_geometry", lambda c, key=key: {
            "target": _ctx_get(c, key + "_body", "swept body"), "kind": "planar_face",
            "units": "mm", "max_results": 10}, _tangent_path_end(key + "_shape"), None))
    write("sketch_create", {"plane": "xy", "name": "ConstructionPath"})
    write("sketch_add_geometry", {"sketch_name": "ConstructionPath", "geometry": [
        {"kind": "line", "x1": 10, "y1": 0, "x2": 50, "y2": 0, "is_construction": True}]})
    rows.append(("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "max_results": 100},
                 lambda p: _measured("construction refusal baseline", _solid_tool_census(p),
                                     _solid_tool_census(p) is not None),
                 ("tp_guard", _recall("tp_guard", _solid_tool_census))))
    write("model_sweep", {"profile": {"sketch": "SeparateProfile", "profile_index": 0},
                          "path": "sketch:ConstructionPath"}, _refused("no non-construction curves"))
    rows.append(("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "max_results": 100},
                 lambda p: _measured("construction refusal leaves bodies and sweeps unchanged",
                                     _solid_tool_census(p), _solid_tool_census(p) is not None
                                     and _solid_tool_census(p) == _RECALL.get("tp_guard")), None))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "tp_story", "story"),
                                         "expect_document": _ctx_get(c, "tp_doc", "path scratch")},
              "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "tp_doc", "path scratch"),
                                      "save_changes": False,
                                      "expect_document": _ctx_get(c, "tp_story", "story")},
              _document_closed, None)]
    return rows


_TANGENT_PATH = _tangent_path_rows()


def _loft_edit_definition(sources):
    """Check ordered section sources through an independent read."""
    def check(p):
        definition = p.get("definition") or {}
        rows = definition.get("sections") or []
        got = [row.get("source_sketch") for row in rows]
        return _measured("ordered Loft section sources", {
            "count": definition.get("section_count"), "sources": got,
            "indices": [row.get("index") for row in rows],
            "truncated": definition.get("truncated")},
            definition.get("section_count") == len(sources)
            and definition.get("truncated") is False
            and got == list(sources)
            and [row.get("index") for row in rows] == list(range(len(sources)))
            and all(row.get("kind") == "Profile" and row.get("profile_handle")
                    and row.get("source_component") == "LoftEdit"
                    for row in rows)
            and rows[0].get("end_condition") == "adsk::fusion::LoftDirectionEndCondition"
            and rows[-1].get("end_condition") == "adsk::fusion::LoftFreeEndCondition"
            and definition.get("is_solid") is True
            and definition.get("is_closed") is False
            and definition.get("guide_count") == 0)
    return check


def _loft_edit_landed(count):
    """Check one edit's definition, result material, scope and timeline evidence."""
    def check(p):
        before, after = p.get("target_before") or [], p.get("target_after") or []
        first = before[0].get("volume_cm3") if len(before) == 1 else None
        last = after[0].get("volume_cm3") if len(after) == 1 else None
        return _measured("interior Loft edit", {
            "before_cm3": first, "after_cm3": last,
            "sections": (p.get("definition_after") or {}).get("section_count"),
            "outside_changes": p.get("outside_body_changes"),
            "same_feature": p.get("same_feature"),
            "marker_restored": p.get("marker_restored"),
            "errors": p.get("new_timeline_errors"),
            "warnings": p.get("new_timeline_warnings")},
            p.get("edited") is True and p.get("definition_matches") is True
            and (p.get("definition_after") or {}).get("section_count") == count
            and p.get("geometry_changed") is True and _num(first) and _num(last)
            and abs(last - first) > 0.05
            and p.get("outside_body_changes") == []
            and p.get("same_feature") is True and p.get("marker_restored") is True
            and p.get("feature_health") == "healthy"
            and p.get("new_timeline_errors") == [] and p.get("new_timeline_warnings") == [])
    return check


def _loft_edit_volume(stage, previous=None):
    """Check an independent post-downstream material reading."""
    def check(p):
        volume = (p.get("mass") or {}).get("volume")
        prior = _RECALL.get(previous) if previous else None
        return _measured("Loft material after " + stage,
                         {"volume_cm3": volume, "previous_cm3": prior},
                         _num(volume) and volume > 0 and
                         (previous is None or (_num(prior) and abs(volume - prior) > 0.05)))
    return check


def _loft_edit_volume_kept(p):
    """Check the rolled-back Loft's independent volume against its pre-edit reading."""
    volume = (p.get("mass") or {}).get("volume")
    return _measured("rolled-back Loft material", {"volume_cm3": volume,
                                                   "created_cm3": _RECALL.get("le_volume_created")},
                     _near(volume, _RECALL["le_volume_created"], 0.0001))


def _rolled_back_body(volume_key, name_key, renamed=None):
    """(check, save) re-reading the one solid at a recalled volume; renamed pins its name change."""
    def solids(p):
        return [r.get("body") for r in (p.get("mass") or {}).get("per_body") or []
                if r.get("is_solid") is True and _near(r.get("volume"), _RECALL[volume_key], 0.0001)]

    def check(p):
        names, was = solids(p), _RECALL.get(name_key)
        return _measured("one solid at the rolled-back volume", {"names": names, "was": was},
                         len(names) == 1 and (renamed is None or (names[0] != was) is renamed))
    return check, (name_key, _recall(name_key, lambda p: solids(p)[0]))


def _loft_edit_identical(p):
    """Check a landed retarget whose bodies re-read identical, reported as a success."""
    return _measured("identical-geometry Loft retarget", {
        "edited": p.get("edited"), "definition_matches": p.get("definition_matches"),
        "geometry_changed": p.get("geometry_changed"), "rollback": p.get("rollback"),
        "outside_changes": p.get("outside_body_changes"), "note": p.get("note")},
        p.get("edited") is True and p.get("definition_matches") is True
        and p.get("geometry_changed") is False and p.get("outside_body_changes") == []
        and "rollback" not in p
        and (p.get("note") or "").endswith("The body geometry reads identical before and after."))


def _loft_edit_witness(p):
    """Check the unrelated witness body retained its measured volume."""
    volume = (p.get("mass") or {}).get("volume")
    return _measured("unchanged Loft witness", {"volume_cm3": volume},
                     _num(volume) and _near(volume, _RECALL["le_witness_volume"], 0.0001))


def _loft_edit_timeline_evidence(p):
    """The complete evaluated timeline and uniquely scoped dependent cut."""
    timeline = p.get("timeline") or {}
    rows = timeline.get("timeline") or []
    matches = [row for row in rows if row.get("name") == _RECALL.get("le_cut")
               and row.get("component") == "LoftEdit" and row.get("type") == "ExtrudeFeature"]
    summary = timeline.get("summary") or {}
    return {"cut": matches[0] if len(matches) == 1 else None,
            "cut_matches": len(matches), "marker": timeline.get("marker_position"),
            "count": timeline.get("count"), "returned": timeline.get("returned"),
            "row_count": len(rows), "states": summary.get("states"),
            "exceptions": summary.get("exceptions")}


def _loft_edit_downstream(p, baseline=False):
    """Check the scoped cut and complete timeline against their pre-edit state."""
    now = _loft_edit_timeline_evidence(p)
    before = _RECALL.get("le_timeline_before") if not baseline else None
    cut = now["cut"] or {}
    complete = (now["cut_matches"] == 1 and type(cut.get("index")) is int
                and type(now["count"]) is int and now["count"] > 0
                and now["marker"] == now["count"] == now["returned"] == now["row_count"]
                and now["states"] == {"healthy": now["count"]}
                and now["exceptions"] == [])
    retained = (baseline or (isinstance(before, dict) and
                all(now[key] == before.get(key) for key in
                    ("cut", "marker", "count", "returned", "states", "exceptions"))))
    return _measured("retained downstream Loft cut and timeline",
                     {"before": before, "after": now}, complete and retained)


def _loft_edit_end_parameter(key, baseline=None):
    """Check one public model parameter retained its expression and evaluated value."""
    def check(p):
        param = p.get("parameter") or {}
        expected = _RECALL.get("le_parameter_" + key) if baseline else None
        observed = {name: param.get(name) for name in
                    ("name", "expression", "value", "value_units")}
        return _measured("Loft " + key + " parameter", observed,
                         observed["name"] == _RECALL["le_parameters"][key]
                         and isinstance(observed["expression"], str)
                         and _num(observed["value"])
                         and (expected is None or observed == expected))
    return check


def _loft_refusal_details_script(feature):
    """Repeat the minimum-section refusal and expose its structured comparison evidence."""
    return f'''import json, sys

def run(context):
    modules = [m for n, m in sys.modules.items() if n.endswith('.tools.model_edit_loft')]
    assert len(modules) == 1
    result = modules[0].handler(feature={feature!r}, action='remove', section_index=1)
    print(json.dumps({{'is_error': result.get('isError') is True, 'details': result.get('details')}}))
'''


def _loft_unchanged_refusal(p):
    """Require a refusal that independently re-reads its unchanged definition without an edit."""
    detail = p.get("details") or {}
    return _measured("refused Loft removal re-reads its definition unchanged", detail,
                     p.get("is_error") is True and detail.get("mutation_attempted") is False
                     and detail.get("definition_matches") is True
                     and detail.get("definition_before") is not None
                     and detail.get("definition_before") == detail.get("definition_after")
                     and detail.get("marker_restored") is True)


def _loft_edit_rows():
    """Exercise profile retarget, three-to-two removal and minimum refusal in scratch."""
    rows = [("doc_get", {}, _home_document, ("le_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "le_story", "story")},
             _new_document, ("le_doc", lambda p: p["document_handle"]))]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "le_doc", args(c) if callable(args) else args), check, save))

    def read_ends(baseline):
        for key in ("start_weight", "start_angle"):
            rows.append(("param_get", lambda c, key=key: {
                "name": _RECALL["le_parameters"][key]},
                _loft_edit_end_parameter(key, baseline),
                (("le_parameter_" + key, _recall("le_parameter_" + key,
                   lambda p: {name: (p.get("parameter") or {}).get(name) for name in
                              ("name", "expression", "value", "value_units")}))
                 if not baseline else None)))

    write("model_create_component", {"name": "LoftWitness", "activate": True}, _made_component)
    write("sketch_create", {"plane": "xy", "name": "WitnessSketch"})
    write("sketch_add_geometry", {"sketch_name": "WitnessSketch", "geometry": [
        {"kind": "rectangle", "x1": 100, "y1": 100, "x2": 110, "y2": 110}]})
    def witness_refs(p):
        _RECALL["le_witness_feature"] = "LoftWitness/" + p["feature"]
        return p["result_bodies"][0]

    write("model_extrude", {"sketch_name": "WitnessSketch", "distance": 10}, _extruded,
          ("le_witness", witness_refs))
    rows.append(("model_inspect", lambda c: {"target": "LoftWitness:" + _ctx_get(
        c, "le_witness", "witness body"), "include": ["mass"], "units": "cm"},
        lambda p: _num((p.get("mass") or {}).get("volume")),
        ("le_witness_volume", _recall("le_witness_volume", lambda p: p["mass"]["volume"]))))
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "LoftEdit", "activate": True}, _made_component)
    for sketch, plane, radius in (("Start", "xy", 5), ("Middle", "MidPlane", 6),
                                  ("MiddleTwin", "MidPlane", 6),
                                  ("Alternate", "MidPlane", 9), ("Narrow", "MidPlane", 1),
                                  ("Penultimate", "LatePlane", 7), ("End", "EndPlane", 4)):
        if sketch == "Middle":
            write("model_construction", {"kind": "plane", "plane": "xy", "offset": 10,
                                         "name": "MidPlane"}, _datum_plane("xy"))
        if sketch == "End":
            write("model_construction", {"kind": "plane", "plane": "xy", "offset": 20,
                                         "name": "EndPlane"}, _datum_plane("xy"))
        if sketch == "Penultimate":
            write("model_construction", {"kind": "plane", "plane": "xy", "offset": 15,
                                         "name": "LatePlane"}, _datum_plane("xy"))
        write("sketch_create", {"plane": plane, "name": sketch})
        write("sketch_add_geometry", {"sketch_name": sketch, "geometry": [
            {"kind": "circle", "cx": 0, "cy": 0, "radius": radius}]})
        rows.append(("sketch_get", {"sketch_name": sketch}, "ok", _prof("le_" + sketch.lower())))
    def loft_refs(p):
        _RECALL["le_body"] = p["result_bodies"][0]
        _RECALL["le_parameters"] = p["model_parameters"]
        return "LoftEdit/" + p["feature"]

    write("model_loft", lambda c: {"profiles": [_ctx_get(c, "le_start", "start profile"),
                                               _ctx_get(c, "le_middle", "middle profile"),
                                               _ctx_get(c, "le_penultimate", "late profile"),
                                               _ctx_get(c, "le_end", "end profile")],
                                           "start": "direction"},
          _lofted, ("le_feature", loft_refs))
    read_ends(False)
    rows.append(("design_get", lambda c: {"include": ["definition"],
        "feature": _ctx_get(c, "le_feature", "Loft feature")},
        _loft_edit_definition(("Start", "Middle", "Penultimate", "End")), None))
    # A side slot just under the middle section: every section set below reaches x=2.5 there
    # except the Narrow waist, which leaves the slot cutting air.
    write("sketch_create", {"plane": "MidPlane", "name": "DependentCutSketch"})
    write("sketch_add_geometry", {"sketch_name": "DependentCutSketch", "geometry": [
        {"kind": "rectangle", "x1": 2.5, "y1": -0.5, "x2": 20, "y2": 0.5}]})
    write("model_extrude", lambda c: {"sketch_name": "DependentCutSketch", "distance": -0.5,
        "operation": "cut", "target_bodies": ["LoftEdit:" + _RECALL["le_body"]]},
        _extruded, ("le_cut", _recall("le_cut", lambda p: p["feature"])))
    rows.append(("model_inspect", lambda c: {"target": "LoftEdit:" + _RECALL["le_body"],
        "include": ["mass"], "units": "cm"},
        _loft_edit_volume("creation"),
        ("le_volume_created", _recall("le_volume_created", lambda p: p["mass"]["volume"]))))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 lambda p: _loft_edit_downstream(p, baseline=True),
                 ("le_timeline_before", _recall("le_timeline_before",
                                                _loft_edit_timeline_evidence))))
    write("model_edit_loft", lambda c: {"feature": _ctx_get(c, "le_feature", "Loft feature"),
        "action": "retarget", "section_index": 1,
        "profile": _ctx_get(c, "le_narrow", "narrow profile"), "component": "LoftEdit"},
        _refused("New evaluated timeline errors or warnings", "It was rolled back and re-read: "
                 "section 1 reads sketch 'Middle' profile 0 again"))
    # The rows below target the Loft body by name, so the name is read back after the restore.
    rows.append(("model_inspect", {"target": "LoftEdit:1", "include": ["mass"], "units": "cm",
                                   "per_body": True}, *_rolled_back_body("le_volume_created", "le_body")))
    rows.append(("design_get", lambda c: {"include": ["definition"],
        "feature": _ctx_get(c, "le_feature", "Loft feature")},
        _loft_edit_definition(("Start", "Middle", "Penultimate", "End")), None))
    rows.append(("model_inspect", lambda c: {"target": "LoftEdit:" + _RECALL["le_body"],
        "include": ["mass"], "units": "cm"}, _loft_edit_volume_kept, None))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 _loft_edit_downstream, None))
    write("model_edit_loft", lambda c: {"feature": _ctx_get(c, "le_feature", "Loft feature"),
        "action": "retarget", "section_index": 1,
        "profile": _ctx_get(c, "le_middletwin", "middle twin profile"), "component": "LoftEdit"},
        _loft_edit_identical)
    rows.append(("design_get", lambda c: {"include": ["definition"],
        "feature": _ctx_get(c, "le_feature", "Loft feature")},
        _loft_edit_definition(("Start", "MiddleTwin", "Penultimate", "End")), None))
    rows.append(("model_inspect", lambda c: {"target": "LoftEdit:" + _RECALL["le_body"],
        "include": ["mass"], "units": "cm"}, _loft_edit_volume_kept, None))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 _loft_edit_downstream, None))
    # A collapsed group before the marker is read through its members: the retarget below runs
    # with the witness rows grouped, and the volume read after it is taken before the ungroup.
    write("design_edit_timeline", lambda c: {"action": "group", "name": "LoftEarlier",
        "feature": "WitnessSketch", "end_feature": _RECALL["le_witness_feature"]},
        lambda p: _measured("witness rows grouped before the Loft", p, p.get("grouped") is True
                            and p.get("group") == "LoftEarlier" and p.get("member_count") == 2))
    write("model_edit_loft", lambda c: {"feature": _ctx_get(c, "le_feature", "Loft feature"),
        "action": "retarget", "section_index": 1,
        "profile": _ctx_get(c, "le_alternate", "alternate profile"), "component": "LoftEdit"},
        _loft_edit_landed(4))
    read_ends(True)
    rows.append(("design_get", lambda c: {"include": ["definition"],
        "feature": _ctx_get(c, "le_feature", "Loft feature")},
        _loft_edit_definition(("Start", "Alternate", "Penultimate", "End")), None))
    rows.append(("model_inspect", lambda c: {"target": "LoftEdit:" + _RECALL["le_body"],
        "include": ["mass"], "units": "cm"},
        _loft_edit_volume("retarget", "le_volume_created"),
        ("le_volume_retarget", _recall("le_volume_retarget", lambda p: p["mass"]["volume"]))))
    write("design_edit_timeline", {"action": "ungroup", "feature": "LoftEarlier"},
          lambda p: _measured("witness group ungrouped", p, p.get("ungrouped") is True))
    write("model_edit_loft", lambda c: {"feature": _ctx_get(c, "le_feature", "Loft feature"),
        "action": "remove", "section_index": 2}, _loft_edit_landed(3))
    read_ends(True)
    rows.append(("design_get", lambda c: {"include": ["definition"],
        "feature": _ctx_get(c, "le_feature", "Loft feature")},
        _loft_edit_definition(("Start", "Alternate", "End")), None))
    rows.append(("model_inspect", lambda c: {"target": "LoftEdit:" + _RECALL["le_body"],
        "include": ["mass"], "units": "cm"},
        _loft_edit_volume("four-to-three removal", "le_volume_retarget"),
        ("le_volume_three", _recall("le_volume_three", lambda p: p["mass"]["volume"]))))
    write("model_edit_loft", lambda c: {"feature": _ctx_get(c, "le_feature", "Loft feature"),
        "action": "remove", "section_index": 1}, _loft_edit_landed(2))
    read_ends(True)
    rows.append(("design_get", lambda c: {"include": ["definition"],
        "feature": _ctx_get(c, "le_feature", "Loft feature")},
        _loft_edit_definition(("Start", "End")), None))
    rows.append(("model_inspect", lambda c: {"target": "LoftEdit:" + _RECALL["le_body"],
        "include": ["mass"], "units": "cm"},
        _loft_edit_volume("three-to-two removal", "le_volume_three"),
        ("le_volume_removed", _recall("le_volume_removed", lambda p: p["mass"]["volume"]))))
    write("model_edit_loft", lambda c: {"feature": _ctx_get(c, "le_feature", "Loft feature"),
        "action": "remove", "section_index": 1}, _refused("fewer than two"))
    write("sys_execute_script", lambda c: {"script": _loft_refusal_details_script(
        _ctx_get(c, "le_feature", "Loft feature")), "read_only": False}, _loft_unchanged_refusal)
    rows.append(("design_get", lambda c: {"include": ["definition"],
        "feature": _ctx_get(c, "le_feature", "Loft feature")},
        _loft_edit_definition(("Start", "End")), None))
    rows.append(("model_inspect", lambda c: {"target": "LoftEdit:" + _RECALL["le_body"],
        "include": ["mass"], "units": "cm"},
        lambda p: _near((p.get("mass") or {}).get("volume"),
                        _RECALL["le_volume_removed"], 0.0001), None))
    rows.append(("model_inspect", lambda c: {"target": "LoftWitness:" + _ctx_get(
        c, "le_witness", "witness body"), "include": ["mass"], "units": "cm"},
        _loft_edit_witness, None))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 _loft_edit_downstream, None))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "le_story", "story"),
                                         "expect_document": _ctx_get(c, "le_doc", "Loft edit")},
              "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "le_doc", "Loft edit"),
                                      "save_changes": False,
                                      "expect_document": _ctx_get(c, "le_story", "story")},
              _document_closed, None)]
    return rows


_LOFT_EDITOR = _loft_edit_rows()


def _d_loft_definition(sources):
    """Read the public ordered sections for the measured root surface Loft."""
    def check(p):
        definition = p.get("definition") or {}
        rows = definition.get("sections") or []
        got = [row.get("source_sketch") for row in rows]
        return _measured("ordered surface Loft sections", {
            "sources": got, "count": definition.get("section_count"),
            "truncated": definition.get("truncated")},
            got == list(sources) and definition.get("section_count") == len(sources)
            and definition.get("truncated") is False
            and [row.get("index") for row in rows] == list(range(len(sources)))
            and all(row.get("kind") == "SketchLine" for row in rows)
            and definition.get("is_solid") is False
            and definition.get("is_closed") is False
            and definition.get("guide_count") == 0)
    return check


def _d_loft_native_script(loft_name="", offset_name="", loft_body="", offset_body=""):
    """Return an independent body/feature/history reader for the disposable Loft document."""
    return f'''import adsk.core, adsk.fusion, json
def run(context):
    app=adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    d=adsk.fusion.Design.cast(app.activeProduct)
    c=d.rootComponent
    def pt(p): return [round(p.x*10,9),round(p.y*10,9),round(p.z*10,9)]
    def body(b):
        return {{"name":b.name,"token":b.entityToken,"solid":b.isSolid,
            "volume_cm3":round(b.volume,12),"area_cm2":round(b.physicalProperties.area,12),
            "bounds_mm":[pt(b.boundingBox.minPoint),pt(b.boundingBox.maxPoint)],
            "vertices_mm":sorted(pt(v.geometry) for v in b.vertices)}}
    def safe_name(obj):
        try:return obj.name
        except:return None
    def feature(collection,name,old_token):
        f=collection.itemByName(name) if name else None
        if f is None:return None
        hits=d.findEntityByToken(old_token) if old_token else []
        same=(len(hits)==1 and safe_name(hits[0])==f.name
            and hits[0].objectType==f.objectType
            and hits[0].timelineObject.index==f.timelineObject.index) if f is not None else False
        return None if f is None else {{"name":f.name,"token":f.entityToken,
            "identity_resolves":same,
            "health":int(f.healthState)}}
    tl=[{{"name":o.name,"type":o.entity.objectType,"health":int(o.healthState)}}
        for o in d.timeline]
    print(json.dumps({{"bodies":sorted((body(b) for b in c.bRepBodies),key=lambda r:r["name"]),
        "loft":feature(c.features.loftFeatures,{loft_name!r},{_RECALL.get("d_loft_loft_token", "")!r}),
        "offset":feature(c.features.offsetFeatures,{offset_name!r},{_RECALL.get("d_loft_offset_token", "")!r}),
        "loft_body":next((body(b) for b in c.bRepBodies if b.name=={loft_body!r}),None),
        "offset_body":next((body(b) for b in c.bRepBodies if b.name=={offset_body!r}),None),
        "timeline":tl,"marker":d.timeline.markerPosition}}))
'''


def _d_loft_snapshot(key, stage):
    """Compare a fresh native snapshot with the saved stage and measured shape facts."""
    def check(p):
        before = _RECALL.get(key)
        valid = isinstance(before, dict) and isinstance(p.get("bodies"), list)
        if stage == "fixture":
            valid = valid and p.get("loft") is None and p.get("offset") is None
        elif stage == "edited":
            loft, offset = p.get("loft") or {}, p.get("offset") or {}
            body, offset_body = p.get("loft_body") or {}, p.get("offset_body") or {}
            old_body, old_offset = before.get("loft_body") or {}, before.get("offset_body") or {}
            valid = (valid and loft.get("identity_resolves") is True
                     and offset.get("identity_resolves") is True
                     and loft.get("health") == offset.get("health") == 0
                     and p.get("timeline") == before.get("timeline")
                     and p.get("marker") == before.get("marker")
                     and body.get("solid") is False and offset_body.get("solid") is False
                     and _near(body.get("area_cm2"), 6.2604905683130445, 0.02)
                     and _near(offset_body.get("area_cm2"), 6.557733794975538, 0.02)
                     and body.get("vertices_mm") != old_body.get("vertices_mm")
                     and offset_body.get("vertices_mm") != old_offset.get("vertices_mm")
                     and body.get("bounds_mm") != old_body.get("bounds_mm")
                     and offset_body.get("bounds_mm") != old_offset.get("bounds_mm")
                     and _d_loft_witness_same(before, p))
        elif stage == "restored":
            valid = (valid and _d_loft_state(p) == _d_loft_state(before)
                     and (p.get("loft") or {}).get("identity_resolves") is True
                     and (p.get("offset") or {}).get("identity_resolves") is True)
        elif stage == "retired":
            base = _RECALL.get("d_loft_fixture")
            valid = (valid and isinstance(base, dict)
                     and _d_loft_retired_state(p) == _d_loft_retired_state(base))
        return _measured("native Loft and dependent surface state " + stage,
                         {"before": before, "after": p}, valid)
    return check


def _d_loft_witness_same(before, after):
    """Require the separately authored solid witness body to remain exactly unchanged."""
    def witness(rows):
        return [row for row in rows if row.get("name", "").startswith("Body")
                and row.get("solid") is True]
    left, right = witness(before.get("bodies") or []), witness(after.get("bodies") or [])
    strip = lambda rows: [{k: v for k, v in row.items() if k != "token"} for row in rows]
    return bool(left) and strip(left) == strip(right)


def _d_loft_state(value):
    """Compare restored material/history while excluding Fusion's token spellings."""
    bodies = [{k: v for k, v in row.items() if k != "token"} for row in value.get("bodies", [])]
    return {"bodies": bodies,
            "loft": {k: v for k, v in (value.get("loft") or {}).items()
                     if k not in ("identity_resolves", "token")},
            "offset": {k: v for k, v in (value.get("offset") or {}).items()
                       if k not in ("identity_resolves", "token")},
            "timeline": value.get("timeline"), "marker": value.get("marker")}


def _d_loft_retired_state(value):
    """Compare source sketches, witness geometry and history after feature retirement."""
    state = _d_loft_state(value)
    state.pop("marker", None)
    return state


def _d_loft_rows():
    """Exercise native-measured surface Loft reorder and exact restoration in a disposable doc."""
    rows = [
        ("doc_get", {}, _d_loft_home_capture("d_loft_home_census"),
         ("d_loft_home", _home_address)),
        ("doc_new", lambda c: {"expect_document": _ctx_get(c, "d_loft_home", "home")},
         _new_document, ("d_loft_doc", _d_loft_new_doc)),
    ]

    def write(name, args, check="ok", save=None, write=True):
        def arguments(c):
            values = args(c) if callable(args) else dict(args)
            return _combine_pin(c, "d_loft_doc", values) if write else values
        rows.append((name, arguments, check, save))

    def native_script(c):
        loft = _RECALL.get("d_loft_make") or {}
        offset = _RECALL.get("d_loft_offset_make") or {}
        return _d_loft_native_script(loft.get("feature", ""), offset.get("feature", ""),
            (loft.get("result_bodies") or [""])[0],
            (offset.get("result_bodies") or [""])[0])

    def loft_feature(c):
        return _ctx_get(c, "d_loft_make", "Loft result")["feature"]

    write("sketch_create", {"name": "DLoftWitness", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "DLoftWitness", "units": "mm",
        "geometry": [{"kind": "rectangle", "x1": 100, "y1": 100,
                      "x2": 110, "y2": 110}]})
    write("model_extrude", {"sketch_name": "DLoftWitness", "distance": 10,
                            "units": "mm", "operation": "new"}, _extruded)
    for name, x, z in (("DSectionA", 0, 0), ("DSectionB", 20, 5), ("DSectionC", 40, 0)):
        if name == "DSectionB":
            write("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy",
                "offset": 5, "units": "mm", "name": "DSectionMid"}, _datum_plane("xy"))
            plane = "DSectionMid"
        else:
            plane = "xy"
        write("sketch_create", {"name": name, "plane": plane})
        write("sketch_add_geometry", {"sketch_name": name, "units": "mm", "geometry": [
            {"kind": "line", "x1": x, "y1": 0, "x2": x, "y2": 10}]})

    def fixture_snapshot(p):
        # The fixture-stage check is repeated after section creation; only the witness body is solid.
        return _measured("Loft fixture witness and source sketches exist", p,
            bool(p.get("bodies")) and len([b for b in p["bodies"] if b.get("solid")]) == 1
            and p.get("loft") is None and p.get("offset") is None)
    write("sys_execute_script", {"script": _d_loft_native_script(), "read_only": True},
          fixture_snapshot, ("d_loft_fixture", _recall("d_loft_fixture", lambda p: p)))

    write("model_loft", {"profiles": ["DSectionA/line:0", "DSectionB/line:0", "DSectionC/line:0"],
                          "as_surface": True, "operation": "new"}, _lofted,
          ("d_loft_make", _recall("d_loft_make", lambda p: p)))
    write("find_geometry", lambda c: {"target": _ctx_get(c, "d_loft_make", "surface Loft result")
        ["result_bodies"][0],
        "kind": "nurbs_face", "units": "mm", "max_results": 10},
        _matched(1, "nurbs_face"), ("d_loft_face", lambda p: p["matches"][0]["handle"]), write=False)
    write("surface_offset", lambda c: {"faces": [_ctx_get(c, "d_loft_face", "Loft face")],
        "distance": 1, "units": "mm", "chaining": False, "operation": "new"}, "ok",
        ("d_loft_offset_make", _recall("d_loft_offset_make", lambda p: p)))
    rows.append(("sys_execute_script", lambda c: _combine_pin(c, "d_loft_doc", {
        "script": native_script(c), "read_only": True}), "ok", None))
    rows[-1] = (rows[-1][0], rows[-1][1],
        _d_loft_capture_before("d_loft_before"),
        ("d_loft_before", _recall("d_loft_before", lambda p: p)))
    rows.append(("design_get", lambda c: {
        "include": ["definition"], "feature": loft_feature(c)},
        lambda p: _d_loft_definition(("DSectionA", "DSectionB", "DSectionC"))(p)
        and _measured("Loft note names the properties the mass read exposes",
                      (p.get("definition") or {}).get("note"),
                      "model_inspect include=['mass'] reads mass, volume and density"
                      in ((p.get("definition") or {}).get("note") or "")
                      and "reads material" not in ((p.get("definition") or {}).get("note") or "")), None))
    rows.append(("model_inspect", {"target": "Body1", "include": ["mass"], "units": "mm"},
        lambda p: _measured("solid witness mass and density read independently", p.get("mass"),
                           _near((p.get("mass") or {}).get("volume"), 1000, .01)
                           and all(_num((p.get("mass") or {}).get(k))
                                   for k in ("mass_kg", "density_kg_per_cm3"))
                           and not any("material" in k for k in (p.get("mass") or {}))), None))
    write("model_edit_loft", lambda c: {"feature": loft_feature(c),
        "action": "reorder", "section_index": 1, "new_index": 0}, _d_loft_edit_reply)
    rows.append(("sys_execute_script", lambda c: _combine_pin(c, "d_loft_doc", {
        "script": native_script(c), "read_only": True}),
        _d_loft_snapshot("d_loft_before", "edited"),
        ("d_loft_edited", _recall("d_loft_edited", lambda p: p))))
    rows.append(("design_get", lambda c: {
        "include": ["definition"], "feature": loft_feature(c)},
        _d_loft_definition(("DSectionB", "DSectionA", "DSectionC")), None))
    write("model_edit_loft", lambda c: {"feature": loft_feature(c),
        "action": "reorder", "section_index": 0, "new_index": 1}, _d_loft_edit_reply)
    rows.append(("sys_execute_script", lambda c: _combine_pin(c, "d_loft_doc", {
        "script": native_script(c), "read_only": True}),
        _d_loft_snapshot("d_loft_before", "restored"), None))
    write("design_delete_feature", lambda c: {"feature": _ctx_get(
        c, "d_loft_offset_make", "offset result")["feature"]})
    write("design_delete_feature", lambda c: {"feature": loft_feature(c)})
    rows.append(("sys_execute_script", lambda c: _combine_pin(c, "d_loft_doc", {
        "script": native_script(c), "read_only": True}),
        _d_loft_snapshot("d_loft_before", "retired"), None))
    rows.extend([
        ("doc_activate", lambda c: {"name": _ctx_get(c, "d_loft_home", "home"),
            "expect_document": _ctx_get(c, "d_loft_doc", "Loft scratch")}, "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "d_loft_doc", "Loft scratch"),
            "save_changes": False, "expect_document": _ctx_get(c, "d_loft_home", "home")},
         _document_closed, None),
        ("doc_get", {}, _d_loft_home_same("d_loft_home_census"), None),
    ])
    return rows


def _d_loft_capture_before(key):
    """Capture all independent Loft/dependent body and feature fields after the offset lands."""
    def check(p):
        ok = (isinstance(p.get("bodies"), list) and len(p["bodies"]) == 3
              and p.get("loft") and p.get("offset")
              and p["loft"].get("health") == p["offset"].get("health") == 0
              and p.get("loft_body") and p.get("offset_body")
              and _near((p.get("loft_body") or {}).get("area_cm2"), 4.160915277738203, 0.02)
              and _near((p.get("offset_body") or {}).get("area_cm2"), 4.0681857559380425, 0.02)
              and (p.get("loft_body") or {}).get("bounds_mm") == [[0.0, 0.0, 0.0], [40.0, 10.0, 5.0]]
              and len(p.get("timeline") or []) >= 1)
        if ok:
            _RECALL["d_loft_loft_token"] = (p.get("loft") or {}).get("token")
            _RECALL["d_loft_offset_token"] = (p.get("offset") or {}).get("token")
        return _measured("native Loft/dependent pre-edit baseline", p, ok)
    return check


def _d_loft_new_doc(p):
    """Clear cached Loft fixture values before retaining the new document handle."""
    for key in ("d_loft_fixture", "d_loft_before", "d_loft_edited", "d_loft_make",
                "d_loft_offset_make", "d_loft_loft_token", "d_loft_offset_token"):
        _RECALL.pop(key, None)
    return p["document_handle"]


def _d_loft_home_same(key):
    """Require cleanup to restore the original active document handle."""
    def check(p):
        before = _RECALL.get(key) or {}
        return _measured("original active document restored", {
            "expected": before, "actual": _d_home_signature(p)},
            bool(before) and _d_home_signature(p) == before)
    return check


def _d_loft_home_capture(key):
    """Capture the active document and full open-document census before creating scratch."""
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


def _d_loft_edit_reply(p):
    """Require the public edit's section, marker, dependent-health and body-scope reports."""
    return _measured("public Loft reorder result", p,
        p.get("action") == "reorder" and p.get("order_matches") is True
        and p.get("marker_restored") is True and p.get("same_feature") is True
        and p.get("geometry_changed") is True and p.get("outside_body_changes") == []
        and p.get("new_timeline_errors") == [] and p.get("new_timeline_warnings") == [])


_LOFT_EDITOR += _d_loft_rows()


def _later_refusal(sketch, row, feature, feature_row):
    """The one sentence the editors refuse an operand drawn after their feature with."""
    return _refused(f"Editing '{feature}': sketch '{sketch}' is at timeline row {row}, after "
                    f"'{feature}' at row {feature_row}. Move it first with design_edit_timeline("
                    f"action='reorder', feature='{sketch}@{row}', to='before', "
                    f"end_feature='{feature}@{feature_row}'), then retry. Nothing was edited.")


class _RefusedWithout(_Refusal):
    """A refusal carrying every fragment and none of `banned`."""

    def __init__(self, fragments, banned):
        super().__init__(fragments)
        self.banned = banned

    def missing(self, text):
        return super().missing(text) + [f"absent {b!r}" for b in self.banned if b in text]


def _timeline_names(p):
    """The timeline's row names in order, or None unless every row is listed and healthy."""
    t = p.get("timeline") or {}
    rows = t.get("timeline") or []
    whole = (t.get("count") == t.get("marker_position") == len(rows) and not t.get("truncated")
             and (t.get("summary") or {}).get("states") == {"healthy": len(rows)})
    return [r.get("name") for r in rows] if whole else None


def _timeline_reads(label, want):
    """An independent timeline read: every row healthy and `want(names)` true of the order."""
    return lambda p: _measured(label, _timeline_names(p),
                               _timeline_names(p) is not None and want(_timeline_names(p)))


def _later_operand_rows():
    """Refuse operands drawn after their feature, reorder one earlier and edit, refuse a cycle."""
    rows = [("doc_get", {}, _home_document, ("lo_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "lo_story", "story")},
             _new_document, ("lo_doc", lambda p: p["document_handle"]))]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "lo_doc", args(c) if callable(args) else args), check, save))

    def read(name, args, check, save=None):
        rows.append((name, lambda c, args=args: args(c) if callable(args) else dict(args),
                     check, save))

    def sketch(name, plane, geometry):
        write("sketch_create", {"plane": plane, "name": name})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [geometry]})

    def volume(label, cm3):
        read("model_inspect", lambda c: {"target": _ctx_get(c, "lo_body", "sweep body"),
                                         "include": ["mass"], "units": "cm"},
             lambda p: _measured(label, (p.get("mass") or {}).get("volume"),
                                 _near((p.get("mass") or {}).get("volume"), cm3, 0.0001)))

    # Rows 0-10 hold the sweep, extrude and loft with their sketches and planes; 11-14 the
    # sketches drawn after every one of them.
    sketch("Prof", "yz", {"kind": "circle", "cx": 0, "cy": 0, "radius": 5})
    sketch("PathA", "xy", {"kind": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 0})
    write("model_sweep", {"profile": {"sketch": "Prof", "profile_index": 0},
                          "path": "sketch:PathA", "operation": "new"}, _swept,
          ("lo_body", lambda p: p["result_bodies"][0]))
    sketch("Box", "xy", {"kind": "rectangle", "x1": 200, "y1": -20, "x2": 240, "y2": 20})
    write("model_extrude", {"sketch_name": "Box", "profile_index": 0, "distance": 20}, _extruded,
          ("lo_later_body", lambda p: p["result_bodies"][0]))
    for offset in (20, 40):
        write("model_construction", {"kind": "plane", "plane": "xy", "offset": offset,
                                     "name": f"PlaneZ{offset}"}, _datum_plane("xy"))
    for name, plane, radius in (("S0", "xy", 10), ("S1", "PlaneZ20", 6), ("S2", "PlaneZ40", 10)):
        sketch(name, plane, {"kind": "circle", "cx": 400, "cy": 0, "radius": radius})
    write("model_loft", {"profiles": [{"sketch": s, "profile_index": 0} for s in ("S0", "S1", "S2")]},
          _lofted)
    sketch("PathLater", "xy", {"kind": "line", "x1": 0, "y1": 0, "x2": 80, "y2": 0})
    sketch("ProfLater", "yz", {"kind": "circle", "cx": 0, "cy": 0, "radius": 8})
    sketch("BoxLater", "xy", {"kind": "rectangle", "x1": 300, "y1": -10, "x2": 320, "y2": 10})
    sketch("S1Later", "PlaneZ20", {"kind": "circle", "cx": 400, "cy": 0, "radius": 8})
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("later-operand baseline", lambda names: names[2] == "Sweep1"
                         and names[11:] == ["PathLater", "ProfLater", "BoxLater", "S1Later"]),
         ("lo_rows", _recall("lo_rows", _timeline_names)))
    volume("sweep volume along the 100 mm path", 7.853982)
    write("model_edit_extrude", {"feature": "X/Y/NoSuchFeature", "action": "extent",
                                "extent": "distance", "distance": 1},
          _refused("no timeline feature matches 'X/Y/NoSuchFeature'",
                   "design_get(include=['timeline'])"))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("unresolved slash address preserves all current timeline rows",
                         lambda names: names == _RECALL.get("lo_rows")))
    volume("unresolved slash address preserves sweep material", 7.853982)
    read("design_get", {"include": ["definition"], "feature": "Sweep1"},
         lambda p: _measured("Sweep definition keeps readable fields when path needs edit context", p.get("definition"),
             (p.get("definition") or {}).get("type") == "SweepFeature"
             and (p.get("definition") or {}).get("operation") == "new"
             and (p.get("definition") or {}).get("is_solid") is True
             and (p.get("definition") or {}).get("orientation") is not None
             and (p.get("definition") or {}).get("orientation_name") == "perpendicular"
             and (p.get("definition") or {}).get("path") is None
             and (p.get("definition") or {}).get("path_count") is None
             and (p.get("definition") or {}).get("path_truncated") is None
             and (p.get("definition") or {}).get("participants") is None
             and (p.get("definition") or {}).get("participants_truncated") is None
             and bool(((p.get("definition") or {}).get("unavailable") or {}).get("path"))
             and bool(((p.get("definition") or {}).get("unavailable") or {}).get("participants"))
             and ((p.get("definition") or {}).get("profile") or {}).get("source_sketch") == "Prof"
             and bool(((p.get("definition") or {}).get("profile") or {}).get("profile_handle"))),
         ("lo_profile_handle", lambda p: p["definition"]["profile"]["profile_handle"]))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("definition read preserves every healthy timeline row and marker",
                         lambda names: names == _RECALL.get("lo_rows")))
    volume("definition read preserves the sweep volume", 7.853982)
    write("model_edit_sweep", lambda c: {"feature": "Sweep1", "action": "profile",
        "profile": _ctx_get(c, "lo_profile_handle", "profile from definition read")},
        _refused("already uses that profile", "Nothing was edited"))
    # Each editor names the later sketch, both rows and the move; nothing is edited.
    write("model_edit_sweep", {"feature": "Sweep1", "action": "path", "path": "sketch:PathLater"},
          _later_refusal("PathLater", 11, "Sweep1", 2))
    write("model_edit_sweep", {"feature": "Sweep1", "action": "profile",
                               "profile": {"sketch": "ProfLater", "profile_index": 0}},
          _later_refusal("ProfLater", 12, "Sweep1", 2))
    write("model_edit_extrude", {"feature": "Extrude1", "action": "profile",
                                 "profile": {"sketch": "BoxLater", "profile_index": 0}},
          _later_refusal("BoxLater", 13, "Extrude1", 4))
    write("model_edit_loft", {"feature": "Loft1", "action": "retarget", "section_index": 1,
                              "profile": {"sketch": "S1Later", "profile_index": 0}},
          _later_refusal("S1Later", 14, "Loft1", 10))
    # An edge of the body Extrude1 built after Sweep1: the handle resolves at the marker, is
    # refused at the Sweep's row, and the refusal names the one feature holding that body.
    read("find_geometry", lambda c: {"target": _ctx_get(c, "lo_later_body", "the later body"),
                                     "kind": "line_edge", "max_results": 1},
         lambda p: _measured("one straight edge of the later body", p.get("returned"),
                             p.get("returned") == 1), _fg("lo_later_edge"))
    write("model_edit_sweep", lambda c: {"feature": "Sweep1", "action": "path",
                                         "path": _ctx_get(c, "lo_later_edge", "later-body edge")},
          _refused("Editing 'Sweep1': 'path' edge belongs to '",
                   "', made by 'Extrude1' at row 4, after 'Sweep1' at row 2. Use an edge or sketch "
                   "that exists before row 2; a fresh find_geometry handle on that body repeats "
                   "this refusal. Nothing was edited."))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("refused edits left the timeline as it was",
                         lambda names: names == _RECALL.get("lo_rows")))
    volume("refused edits left the sweep volume", 7.853982)
    # The move the refusal names, read back independently, then the edit it unblocks.
    write("design_edit_timeline", {"action": "reorder", "feature": "PathLater@11", "to": "before",
                                   "end_feature": "Sweep1@2"},
          lambda p: _measured("PathLater moved before Sweep1", p, p.get("reordered") is True
                              and (p.get("index_before"), p.get("index_after")) == (11, 2)))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("PathLater sits before Sweep1, every other row in its order",
                         lambda names: names[1:4] == ["PathA", "PathLater", "Sweep1"]
                         and [n for n in names if n != "PathLater"]
                         == [n for n in _RECALL.get("lo_rows") or [] if n != "PathLater"]))
    write("model_edit_sweep", {"feature": "Sweep1", "action": "path", "path": "sketch:PathLater"},
          lambda p: _measured("the unblocked path edit landed", p, p.get("edited") is True
                              and p.get("operand_after") == "PathLater/line:0"))
    volume("sweep volume along the 80 mm path", 6.283185)
    # A sketch projecting the sweep's own edge depends on it: Fusion refuses the move.
    read("find_geometry", lambda c: {"target": _ctx_get(c, "lo_body", "sweep body"),
                                     "kind": "circular_edge", "max_results": 1},
         lambda p: _measured("one sweep end edge", p.get("returned"), p.get("returned") == 1),
         _fg("lo_edge"))
    write("sketch_create", {"plane": "xy", "name": "Dep"})
    write("sketch_project", lambda c: {"sketch_name": "Dep", "entities": [
        _ctx_get(c, "lo_edge", "sweep end edge")]},
          lambda p: _measured("the sweep edge projected into Dep", p.get("created_count"),
                              _num(p.get("created_count")) and p["created_count"] >= 1))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("Dep drawn last", lambda names: names[-1] == "Dep"),
         ("lo_rows_dep", _recall("lo_rows_dep", _timeline_names)))
    write("design_edit_timeline", {"action": "reorder", "feature": "Dep", "to": "before",
                                   "end_feature": "Sweep1"},
          _refused("Fusion refused to move 'Dep' before 'Sweep1'", "CIRCULAR_DEPENDENCY",
                   "Nothing moved (the timeline re-reads unchanged)."))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("the refused move left every row where it was",
                         lambda names: names == _RECALL.get("lo_rows_dep")))
    # An earlier item moves later; the end-of-timeline refusal names a two-move remedy.
    write("design_edit_timeline", {"action": "reorder", "feature": "PathA", "to": "after",
                                   "end_feature": "Loft1"},
          lambda p: _measured("PathA moved after Loft1", p, p.get("reordered") is True
                              and (p.get("index_before"), p.get("index_after")) == (1, 11)))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("PathA sits right after Loft1; the end-move operands retain their rows",
                         lambda names: len(names) == 16 and names[10:12] == ["Loft1", "PathA"]
                         and names[12:] == ["ProfLater", "BoxLater", "S1Later", "Dep"]),
         ("lo_before_end", _recall("lo_before_end", _timeline_names)))
    write("design_edit_timeline", {"action": "reorder", "feature": "ProfLater", "to": "after",
                                   "end_feature": "Dep"},
          _refused("Fusion cannot place an item after the last timeline row", "Nothing moved.",
                   "To make 'ProfLater' last, run design_edit_timeline(action='reorder', "
                   "feature='ProfLater@12', to='before', end_feature='Dep@15'), then "
                   "design_edit_timeline(action='reorder', feature='Dep@15', to='before', "
                   "end_feature='ProfLater@14')."))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("the refused end move left every row where it was",
                         lambda names: names == _RECALL.get("lo_before_end")))
    write("design_edit_timeline", lambda c: {
        "action": "reorder", "to": "before",
        "feature": "ProfLater@" + str(_ctx_get(c, "lo_before_end", "timeline").index("ProfLater")),
        "end_feature": "Dep@" + str(_ctx_get(c, "lo_before_end", "timeline").index("Dep"))},
        lambda p: _measured("the remedy moved ProfLater before Dep", p,
                            p.get("reordered") is True and p.get("feature") == "ProfLater"
                            and p.get("end_feature") == "Dep"))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("ProfLater sits before Dep; every other row kept its order",
                         lambda names: names[-2:] == ["ProfLater", "Dep"]
                         and [n for n in names if n != "ProfLater"]
                         == [n for n in _RECALL.get("lo_before_end") or [] if n != "ProfLater"]),
         ("lo_before_swap", _recall("lo_before_swap", _timeline_names)))
    write("design_edit_timeline", lambda c: {
        "action": "reorder", "to": "before",
        "feature": "Dep@" + str(_ctx_get(c, "lo_before_swap", "timeline").index("Dep")),
        "end_feature": "ProfLater@" + str(_ctx_get(c, "lo_before_swap", "timeline").index("ProfLater"))},
        lambda p: _measured("the remedy moved Dep before ProfLater", p,
                            p.get("reordered") is True and p.get("feature") == "Dep"
                            and p.get("end_feature") == "ProfLater"))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("ProfLater is last; every other row kept its order",
                         lambda names: names[-2:] == ["Dep", "ProfLater"]
                         and names == [n for n in _RECALL.get("lo_before_end") or []
                                       if n != "ProfLater"] + ["ProfLater"]))
    # The item one before the last needs a single move to become last.
    write("design_edit_timeline", {"action": "reorder", "feature": "Dep", "to": "after",
                                   "end_feature": "ProfLater"},
          _refused("Fusion cannot place an item after the last timeline row", "Nothing moved.",
                   "To make 'Dep' last, run design_edit_timeline(action='reorder', "
                   "feature='ProfLater@15', to='before', end_feature='Dep@14')."))
    write("design_edit_timeline", {"action": "reorder", "feature": "ProfLater@15", "to": "before",
                                   "end_feature": "Dep@14"},
          lambda p: _measured("the one-move remedy moved ProfLater before Dep", p,
                              p.get("reordered") is True
                              and (p.get("index_before"), p.get("index_after")) == (15, 14)))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("Dep is last; every other row kept its order",
                         lambda names: names[-2:] == ["ProfLater", "Dep"]
                         and names[:-2] == [n for n in _RECALL.get("lo_before_end") or []
                                            if n not in ("ProfLater", "Dep")]),
         ("lo_rows_end", _recall("lo_rows_end", _timeline_names)))
    # A path sketch rolled back behind the marker is named with its row and the roll remedy.
    write("design_edit_timeline", {"action": "roll", "feature": "PathA", "to": "before"},
          lambda p: _measured("marker rolled to before PathA", p, p.get("rolled") is True
                              and p.get("marker_position") == 11))
    write("model_edit_sweep", {"feature": "Sweep1", "action": "path", "path": "sketch:PathA"},
          _refused("Editing 'Sweep1': sketch 'PathA' at timeline row 11 is rolled back behind the "
                   "marker. Roll to the end with design_edit_timeline(action='roll', to='end'), "
                   "then retry. Nothing was edited."))
    write("design_edit_timeline", {"action": "roll", "to": "end"},
          lambda p: _measured("marker back at the end", p, p.get("rolled") is True
                              and p.get("marker_position") == p.get("timeline_count") == 16))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("the rolled-back refusal left every row and the marker",
                         lambda names: names == _RECALL.get("lo_rows_end")))
    volume("the rolled-back refusal left the sweep volume", 6.283185)
    # A collapsed group before the marker is read through its members; a path sketch inside it
    # gets the ungroup hint.
    write("design_edit_timeline", {"action": "group", "name": "LaterGroup", "feature": "PathA",
                                   "end_feature": "BoxLater"},
          lambda p: _measured("later path sketch grouped", p, p.get("grouped") is True
                              and p.get("group") == "LaterGroup" and p.get("member_count") == 2))
    write("model_edit_sweep", {"feature": "Sweep1", "action": "path", "path": "sketch:PathLater"},
          _refused("'Sweep1' already uses that path", "Nothing was edited"))
    write("model_edit_sweep", {"feature": "Sweep1", "action": "path", "path": "sketch:PathA"},
          _refused("'PathA' is inside the collapsed timeline group 'LaterGroup', which the "
                   "timeline lists as one item. Run design_edit_timeline(action='ungroup', "
                   "feature='LaterGroup') - its items are kept - then retry. The path sketch "
                   "timeline row does not read; nothing was edited."))
    write("design_edit_timeline", {"action": "ungroup", "feature": "LaterGroup"},
          lambda p: _measured("later path group ungrouped", p, p.get("ungrouped") is True))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         _timeline_reads("the grouped refusals left every row and the marker",
                         lambda names: names == _RECALL.get("lo_rows_end")))
    volume("the grouped refusals left the sweep volume", 6.283185)
    # A collapsed group can make a member sketch's timeline row unreadable to the profile editor.
    sketch("TimelineFirst", "xy", {"kind": "rectangle", "x1": 900, "y1": 0,
                                     "x2": 910, "y2": 10})
    sketch("TimelineSecond", "xy", {"kind": "rectangle", "x1": 900, "y1": 0,
                                      "x2": 912, "y2": 12})
    write("model_extrude", {"sketch_name": "TimelineFirst", "profile_index": 0, "distance": 5},
          _extruded, ("lo_timeline_extrude", _recall("lo_timeline_extrude", lambda p: p)))
    read("model_inspect", lambda c: {"target": _ctx_get(c, "lo_timeline_extrude", "profile extrusion")["result_bodies"][0],
                                     "include": ["mass"], "units": "cm"},
         lambda p: _measured("timeline-profile control material", (p.get("mass") or {}).get("volume"),
                             _near((p.get("mass") or {}).get("volume"), .5, .0002)),
         ("lo_grouped_profile_before", _recall("lo_grouped_profile_before", lambda p: p["mass"]["volume"])))
    write("design_edit_timeline", {"action": "group", "name": "TimelineProfiles",
                                   "feature": "TimelineFirst", "end_feature": "TimelineSecond"},
          lambda p: _measured("profile edit fixture group", p, p.get("grouped") is True
                              and p.get("group") == "TimelineProfiles"))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         lambda p: _measured("profile edit fixture grouped", p.get("timeline"),
             (p.get("timeline") or {}).get("groups") == {"TimelineProfiles": 2}
             and (p.get("timeline") or {}).get("returned") == (p.get("timeline") or {}).get("count")
             and ((p.get("timeline") or {}).get("summary") or {}).get("exceptions") == []),
         ("lo_grouped_profile_rows", _recall("lo_grouped_profile_rows", lambda p: p["timeline"])))
    write("model_edit_extrude", lambda c: {"feature": _ctx_get(c, "lo_timeline_extrude", "profile extrusion")["feature"],
                                           "action": "profile",
                                           "profile": {"sketch": "TimelineSecond", "profile_index": 0}},
          _refused("TimelineProfiles", "ungroup", "timeline row does not read", "nothing was edited"))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         lambda p: _measured("refused grouped profile edit preserves timeline", p.get("timeline"),
                             p.get("timeline") == _RECALL.get("lo_grouped_profile_rows")))
    read("model_inspect", lambda c: {"target": _ctx_get(c, "lo_timeline_extrude", "profile extrusion")["result_bodies"][0],
                                     "include": ["mass"], "units": "cm"},
         lambda p: _measured("refused grouped profile edit preserves material",
                             (p.get("mass") or {}).get("volume"),
                             _near((p.get("mass") or {}).get("volume"),
                                   _RECALL.get("lo_grouped_profile_before"), .00001)))
    write("design_edit_timeline", {"action": "ungroup", "feature": "TimelineProfiles"},
          lambda p: _measured("explicit profile ungroup", p, p.get("ungrouped") is True))
    write("model_edit_extrude", lambda c: {"feature": _ctx_get(c, "lo_timeline_extrude", "profile extrusion")["feature"],
                                           "action": "profile",
                                           "profile": {"sketch": "TimelineSecond", "profile_index": 0}},
          lambda p: _measured("profile edit succeeds after explicit ungroup", p,
                              p.get("edited") is True))
    read("model_inspect", lambda c: {"target": _ctx_get(c, "lo_timeline_extrude", "profile extrusion")["result_bodies"][0],
                                     "include": ["mass"], "units": "cm"},
         lambda p: _measured("ungrouped profile independent material read",
                             (p.get("mass") or {}).get("volume"),
                             _near((p.get("mass") or {}).get("volume"), 0.72, .0002)))
    # Two components each hold a sketch 'Twin' in its own collapsed group, the namesake's first:
    # the refusal names the group holding the edited extrude's own profile sketch.
    for part, size in (("A", 10), ("B", 12)):
        write("model_create_component", {"name": f"Twin{part}", "activate": True}, _made_component)
        for name, x, side in ((f"TwinPad{part}1", 940, 10), ("Twin", 960, size),
                              (f"TwinPad{part}2", 980, 10)):
            write("sketch_create", {"plane": "xy", "name": name})
            write("sketch_add_geometry", {"sketch_name": name, "component": f"Twin{part}", "geometry": [
                {"kind": "rectangle", "x1": x, "y1": 0, "x2": x + side, "y2": side}]})
        if part == "B":
            read("sketch_get", {"sketch_name": "Twin", "component": "TwinB"},
                 lambda p: _measured("TwinB's own Twin profile", len(p.get("profiles") or []),
                                     len(p.get("profiles") or []) == 1), _prof("lo_twin_profile"))
            write("model_extrude", {"sketch_name": "TwinPadB1", "profile_index": 0, "distance": 5},
                  _extruded, ("lo_twin_extrude", _recall("lo_twin_extrude", lambda p: p)))
        write("design_edit_timeline", {"action": "group", "name": f"TwinGroup{part}",
                                       "feature": f"TwinPad{part}1", "end_feature": f"TwinPad{part}2"},
              lambda p, part=part: _measured("namesake sketch group", p, p.get("grouped") is True
                                             and p.get("group") == f"TwinGroup{part}"
                                             and p.get("member_count") == 3))
        write("design_activate_component", {"occurrence": "root"})
    read("design_get", {"include": ["timeline"], "max_results": 100},
         lambda p: _measured("two namesake groups, A listed first", p.get("timeline"),
                             list(((p.get("timeline") or {}).get("groups") or {}).items())
                             == [("TwinGroupA", 3), ("TwinGroupB", 3)]),
         ("lo_twin_rows", _recall("lo_twin_rows", lambda p: p["timeline"])))
    read("model_inspect", {"target": "TwinB:1", "include": ["mass"], "units": "cm"},
         lambda p: _measured("TwinB control material", (p.get("mass") or {}).get("volume"),
                             _near((p.get("mass") or {}).get("volume"), .5, .0002)))
    write("model_edit_extrude", lambda c: {
        "feature": "TwinB/" + _ctx_get(c, "lo_twin_extrude", "twin extrusion")["feature"],
        "action": "profile", "profile": _ctx_get(c, "lo_twin_profile", "TwinB Twin profile")},
          _RefusedWithout(("'Twin' is inside the collapsed timeline group 'TwinGroupB'",
                           "design_edit_timeline(action='ungroup', feature='TwinGroupB')",
                           "timeline row does not read; nothing was edited"), ("TwinGroupA",)))
    read("design_get", {"include": ["timeline"], "max_results": 100},
         lambda p: _measured("refused namesake profile edit preserves timeline", p.get("timeline"),
                             p.get("timeline") == _RECALL.get("lo_twin_rows")))
    read("model_inspect", {"target": "TwinB:1", "include": ["mass"], "units": "cm"},
         lambda p: _measured("refused namesake profile edit preserves material",
                             (p.get("mass") or {}).get("volume"),
                             _near((p.get("mass") or {}).get("volume"), .5, .0002)))

    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "lo_story", "story"),
                                         "expect_document": _ctx_get(c, "lo_doc", "later operand")},
              "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "lo_doc", "later operand"),
                                      "save_changes": False,
                                      "expect_document": _ctx_get(c, "lo_story", "story")},
              _document_closed, None)]
    return rows


_LATER_OPERAND = _later_operand_rows()


def _later_operand_preflight_rows():
    """Refuse later operands a reorder would not cure before any reorder advice; nothing moves."""
    rows = [("doc_get", {}, _home_document, ("lp_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "lp_story", "story")},
             _new_document, ("lp_doc", lambda p: p["document_handle"]))]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(c, "lp_doc", args), check, save))

    def sketch(name, plane, geometry):
        write("sketch_create", {"plane": plane, "name": name})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [geometry]})

    sketch("Prof", "yz", {"kind": "circle", "cx": 0, "cy": 0, "radius": 5})
    sketch("PathA", "xy", {"kind": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 0})
    write("model_sweep", {"profile": {"sketch": "Prof", "profile_index": 0},
                          "path": "sketch:PathA", "operation": "new"}, _swept,
          ("lp_body", lambda p: p["result_bodies"][0]))
    for offset in (20, 40):
        write("model_construction", {"kind": "plane", "plane": "xy", "offset": offset,
                                     "name": f"PlaneZ{offset}"}, _datum_plane("xy"))
    for name, plane, radius in (("S0", "xy", 10), ("S1", "PlaneZ20", 6), ("S2", "PlaneZ40", 10)):
        sketch(name, plane, {"kind": "circle", "cx": 400, "cy": 0, "radius": radius})
    write("model_loft", {"profiles": [{"sketch": s, "profile_index": 0} for s in ("S0", "S1", "S2")]},
          _lofted)
    # Drawn after both features: an open line in the root, and two closed circles in another part.
    sketch("OpenLater", "yz", {"kind": "line", "x1": -5, "y1": 0, "x2": 5, "y2": 0})
    write("model_create_component", {"name": "OtherPart", "activate": True}, _made_component)
    sketch("OtherProf", "yz", {"kind": "circle", "cx": 0, "cy": 0, "radius": 4})
    sketch("OtherS1", "xy", {"kind": "circle", "cx": 400, "cy": 0, "radius": 7})
    write("design_activate_component", {"occurrence": "root"})
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 _timeline_reads("later-operand preflight baseline",
                                 lambda names: "Sweep1" in names and names[-2:] == ["OtherProf", "OtherS1"]),
                 ("lp_rows", _recall("lp_rows", _timeline_names))))
    owner_mode = ("Editing 'Sweep1': Replacement profile must keep this Sweep's owner and "
                  "solid/surface mode. Nothing was edited.")
    write("model_edit_sweep", {"feature": "Sweep1", "action": "profile",
                               "profile": {"sketch": "OpenLater", "profile_index": 0}},
          _refused(owner_mode))
    write("model_edit_sweep", {"feature": "Sweep1", "action": "profile", "component": "OtherPart",
                               "profile": {"sketch": "OtherProf", "profile_index": 0}},
          _refused(owner_mode))
    write("model_edit_loft", {"feature": "Loft1", "action": "retarget", "section_index": 1,
                              "component": "OtherPart",
                              "profile": {"sketch": "OtherS1", "profile_index": 0}},
          _refused("Editing 'Loft1': 'profile' is outside the Loft's owning component. "
                   "Nothing was edited."))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 _timeline_reads("the refusals moved no timeline row",
                                 lambda names: names == _RECALL.get("lp_rows")), None))
    rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "lp_body", "sweep body"),
                                             "include": ["mass"], "units": "cm"},
                 lambda p: _measured("the refusals left the sweep volume", (p.get("mass") or {}).get("volume"),
                                     _near((p.get("mass") or {}).get("volume"), 7.853982, 0.0001)), None))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "lp_story", "story"),
                                         "expect_document": _ctx_get(c, "lp_doc", "later preflight")},
              "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "lp_doc", "later preflight"),
                                      "save_changes": False,
                                      "expect_document": _ctx_get(c, "lp_story", "story")},
              _document_closed, None)]
    return rows


_LATER_OPERAND += _later_operand_preflight_rows()


def _loft_scoped_body(case, stage, role, expected, previous=None):
    """Check a scoped loft body using an independent mass and bounds read."""
    def check(p):
        got = _sweep_mode_shape(p)
        old = _RECALL.get(previous) if previous else None
        volume, area = got["volume"], got["area"]
        valid = (p.get("kind") == "body" and p.get("units") == "cm"
                 and (p.get("mass") or {}).get("accuracy_used") == "very_high"
                 and _num(volume) and _num(area) and _sweep_mode_box_equal(got, got)
                 and _near(volume, expected, 0.002)
                 and (previous is None or old is not None))
        if valid and old is not None:
            if role == "SelectedStock" and stage == "after":
                valid = (abs(volume - old["volume"]) > 0.001
                         and abs(area - old["area"]) > 0.001)
            else:
                valid = (abs(volume - old["volume"]) < 0.00001
                         and abs(area - old["area"]) < 0.00001
                         and _sweep_mode_box_equal(got, old))
        return _measured(f"{case} loft {stage} {role} independent material and bounds",
                         {"current": got, "previous": old, "expected_cm3": expected}, valid)
    return check


def _loft_consumed_public(p):
    """Require the retained selected body's zero material from a typed independent read."""
    mass = p.get("mass") or {}
    return _measured("retained selected body has zero volume, area and lumps",
                     {"kind": p.get("kind"), "units": p.get("units"),
                      "lumps": p.get("lump_count"),
                      "volume_mm3": mass.get("volume"), "area_mm2": mass.get("area"),
                      "accuracy": mass.get("accuracy_used")},
                     p.get("kind") == "body" and p.get("units") == "mm"
                     and mass.get("accuracy_used") == "very_high"
                     and p.get("lump_count") == 0
                     and mass.get("volume") == 0 and mass.get("area") == 0)


def _loft_split_fragment(index, first_key=None):
    """Verify one independently inspected half of the selected split stock."""
    def check(p):
        mass = p.get("mass") or {}
        lo, hi = p.get("min_point") or {}, p.get("max_point") or {}
        side = (-1 if _num(hi.get("x")) and hi["x"] < 0 else
                1 if _num(lo.get("x")) and lo["x"] > 0 else 0)
        previous_side = _RECALL.get(first_key) if first_key else None
        valid = (p.get("kind") == "body" and p.get("units") == "mm"
                 and mass.get("accuracy_used") == "very_high"
                 and _near(mass.get("volume"), 246.9417, 0.02)
                 and side != 0 and (first_key is None or
                                    previous_side in (-1, 1) and side == -previous_side)
                 and _near(lo.get("y"), -2, 0.01) and _near(hi.get("y"), 2, 0.01)
                 and _near(lo.get("z"), 10, 0.01) and _near(hi.get("z"), 20, 0.01)
                 and _near(lo.get("x") if side < 0 else hi.get("x"),
                           -10 if side < 0 else 10, 0.01)
                 and _near(hi.get("x") if side < 0 else lo.get("x"),
                           -math.sqrt(12) if side < 0 else math.sqrt(12), 0.02))
        return _measured(f"split loft fragment {index} independent volume and opposite X bounds",
                         {"volume_mm3": mass.get("volume"), "min": lo, "max": hi,
                          "side": side, "previous_side": previous_side}, valid)
    return check


def _loft_participants_rows():
    """Exercise explicit cut and intersect participants with five independent body witnesses."""
    rows = []
    for case, selected_after in (("cut", 1.09530556), ("intersect", 0.94469444)):
        story, doc = f"loft_{case}_story", f"loft_{case}_doc"
        host, foreign = f"Loft{case.title()}Host", f"Loft{case.title()}Foreign"
        rows.extend([
            ("doc_get", {}, _home_document, (story, _home_address)),
            ("doc_new", lambda c, story=story: {
                "expect_document": _ctx_get(c, story, "loft story")},
             _new_document, (doc, lambda p: p["document_handle"]))])

        def write(tool, args, check="ok", save=None, doc=doc):
            rows.append((tool, lambda c, args=args, doc=doc: _combine_pin(
                c, doc, args(c) if callable(args) else args), check, save))

        def box(owner, role, low, high):
            sketch = role + "Sketch"
            plane = "xy"
            if low[2]:
                plane = role + "Plane"
                write("model_construction", {"kind": "plane", "plane": "xy",
                                             "offset": low[2], "name": plane}, _datum_plane("xy"))
            write("sketch_create", {"plane": plane, "name": sketch})
            write("sketch_add_geometry", {"sketch_name": sketch, "component": owner,
                                           "geometry": [{"kind": "rectangle", "x1": low[0],
                                                         "y1": low[1], "x2": high[0],
                                                         "y2": high[1]}]})
            body_key = f"loft_{case}_{role}_body"
            write("model_extrude", {"sketch_name": sketch, "component": owner,
                                    "distance": high[2] - low[2], "operation": "new"}, _extruded,
                  (body_key, lambda p: p["result_bodies"][0]))
            write("design_set_name", lambda c, owner=owner, role=role, key=body_key: {
                "target": owner + ":" + _ctx_get(c, key, "loft stock"),
                "new_name": role},
                  lambda p, role=role: p.get("renamed") is True and p.get("name") == role)

        write("model_create_component", {"name": host, "activate": True}, _made_component)
        for role, low, high in (
                ("SelectedStock", (-6, -5, 0), (0.8, 5, 30)),
                ("UnselectedOverlap", (1.2, -5, 0), (6, 5, 30)),
                ("HostSentinel", (30, 30, 0), (40, 40, 10))):
            box(host, role, low, high)
        write("sketch_create", {"plane": "xy", "name": "LoftBase"})
        write("sketch_add_geometry", {"sketch_name": "LoftBase", "component": host,
                                       "geometry": [{"kind": "circle", "cx": 0, "cy": 0,
                                                     "radius": 4}]})
        write("model_construction", {"kind": "plane", "plane": "xy", "offset": 30,
                                     "name": "LoftTopPlane"}, _datum_plane("xy"))
        write("sketch_create", {"plane": "LoftTopPlane", "name": "LoftTop"})
        write("sketch_add_geometry", {"sketch_name": "LoftTop", "component": host,
                                       "geometry": [{"kind": "circle", "cx": 0, "cy": 0,
                                                     "radius": 4}]})
        write("design_activate_component", {"occurrence": "root"})
        write("model_create_component", {"name": foreign, "activate": True}, _made_component)
        for role, low, high in (
                ("ForeignOverlap", (-2.5, -3, 0), (2.5, 3, 30)),
                ("ForeignSentinel", (50, 50, 0), (60, 60, 10))):
            box(foreign, role, low, high)
        roles = ((host, "SelectedStock", 2.04), (host, "UnselectedOverlap", 1.44),
                 (host, "HostSentinel", 1.0), (foreign, "ForeignOverlap", 0.9),
                 (foreign, "ForeignSentinel", 1.0))
        for owner, role, expected in roles:
            key = f"loft_{case}_before_{role}"
            rows.append(("model_inspect", {"target": f"{owner}:{role}",
                                           "include": ["default", "mass"],
                                           "units": "cm", "accuracy": "very_high"},
                         _loft_scoped_body(case, "before", role, expected),
                         (key, _recall(key, _sweep_mode_shape))))
        if case == "cut":
            rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                         _timeline_reads("complete timeline before scoped join refusal", bool),
                         ("loft_join_before", _recall("loft_join_before", lambda p: p["timeline"]))))
            write("model_loft", {"profiles": [{"sketch": "LoftBase", "profile_index": 0},
                                               {"sketch": "LoftTop", "profile_index": 0}],
                                  "component": host, "operation": "join",
                                  "target_bodies": ["SelectedStock"]},
                  _refused("'target_bodies' only applies to cut/intersect operations."))
            rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                         lambda p: _measured("scoped join refusal leaves timeline unchanged",
                             p.get("timeline"), bool(_RECALL.get("loft_join_before"))
                             and p.get("timeline") == _RECALL.get("loft_join_before")), None))
            for owner, role, expected in roles:
                rows.append(("model_inspect", {"target": f"{owner}:{role}",
                                               "include": ["default", "mass"],
                                               "units": "cm", "accuracy": "very_high"},
                             _loft_scoped_body(case, "refused", role, expected,
                                               f"loft_{case}_before_{role}"), None))
        write("model_loft", {"profiles": [{"sketch": "LoftBase", "profile_index": 0},
                                          {"sketch": "LoftTop", "profile_index": 0}],
                             "component": host, "operation": case,
                             "target_bodies": ["SelectedStock"]},
              lambda p, case=case, host=host: _measured(
                  f"{case} loft configured scope and verified outside bodies", p,
                  p.get("lofted") is True and p.get("operation") == case
                  and p.get("scoped_to_bodies") == [f"{host}:SelectedStock"]
                  and p.get("outside_body_changes") == []
                  and _num(p.get("volume_delta_cm3")) and bool(p.get("result_bodies"))))
        for owner, role, expected in roles:
            key = f"loft_{case}_before_{role}"
            rows.append(("model_inspect", {"target": f"{owner}:{role}",
                                           "include": ["default", "mass"],
                                           "units": "cm", "accuracy": "very_high"},
                         _loft_scoped_body(case, "after", role,
                                           selected_after if role == "SelectedStock" else expected,
                                           key), None))
        if case == "cut":
            write("design_activate_component", {"occurrence": host + ":1"})
            box(host, "ConsumedStock", (-1, -1, 0), (1, 1, 30))
            rows.append(("model_inspect", _combine_inspect(host + ":ConsumedStock"),
                         _combine_body("loft stock before full consumption",
                                       (-1, -1, 0), (1, 1, 30), 120), None))
            rows.append(("design_get", {"include": ["tree"], "component": host,
                                        "tree_bodies": True, "tree_handles": True},
                         lambda p: _measured(
                             "loft full-consumption source identity",
                             (p.get("tree") or {}).get("tree"),
                             sum(b.get("name") == "ConsumedStock" for b in
                                 ((p.get("tree") or {}).get("tree") or {}).get("bodies", [])) == 1),
                         ("loft_consumed_handle", _recall("loft_consumed_handle", lambda p:
                             next(b["handle"] for b in p["tree"]["tree"]["bodies"]
                                  if b["name"] == "ConsumedStock")))))
            write("model_loft", {"profiles": [{"sketch": "LoftBase", "profile_index": 0},
                                              {"sketch": "LoftTop", "profile_index": 0}],
                                 "component": host, "operation": "cut",
                                 "target_bodies": ["ConsumedStock"]},
                  lambda p, host=host: _measured(
                      "fully consumed selected stock scoped loft", p,
                      p.get("lofted") is True and p.get("operation") == "cut"
                      and p.get("scoped_to_bodies") == [host + ":ConsumedStock"]
                      and p.get("outside_body_changes") == []
                      and _near(p.get("volume_delta_cm3"), -0.12, 0.00001)
                      and p.get("result_bodies") == ["ConsumedStock"]))
            rows.append(("design_get", {"include": ["tree"], "component": host,
                                        "tree_bodies": True, "tree_handles": True},
                         lambda p: (lambda bodies: _measured(
                             "fully cut source retains its identity with zero material",
                             bodies, len(bodies) == 4
                             and sum(b.get("name") == "ConsumedStock"
                                     and b.get("handle") == _RECALL.get("loft_consumed_handle")
                                     for b in bodies) == 1))(
                                 ((p.get("tree") or {}).get("tree") or {}).get("bodies", [])), None))
            rows.append(("model_inspect", lambda c: {
                "target": _ctx_get(c, "loft_consumed_handle", "consumed stock identity"),
                "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                _loft_consumed_public, None))
            for owner, role, expected in (roles[1], roles[3]):
                rows.append(("model_inspect", {"target": f"{owner}:{role}",
                                               "include": ["default", "mass"],
                                               "units": "cm", "accuracy": "very_high"},
                             _loft_scoped_body("consumed", "after", role, expected,
                                               f"loft_cut_before_{role}"), None))

            box(host, "SplitStock", (-10, -2, 10), (10, 2, 20))
            rows.append(("model_inspect", _combine_inspect(host + ":SplitStock"),
                         _combine_body("loft stock before split", (-10, -2, 10),
                                       (10, 2, 20), 800), None))
            write("model_loft", {"profiles": [{"sketch": "LoftBase", "profile_index": 0},
                                              {"sketch": "LoftTop", "profile_index": 0}],
                                 "component": host, "operation": "cut",
                                 "target_bodies": ["SplitStock"]},
                  lambda p, host=host: _measured(
                      "selected stock split into two attributed result bodies", p,
                      p.get("lofted") is True and p.get("operation") == "cut"
                      and p.get("scoped_to_bodies") == [host + ":SplitStock"]
                      and p.get("outside_body_changes") == []
                      and len(p.get("result_bodies") or []) == 2
                      and "volume_delta_cm3" not in p),
                  ("loft_split_names", _recall("loft_split_names", lambda p: p["result_bodies"])))
            rows.append(("design_get", {"include": ["tree"], "component": host,
                                        "tree_bodies": True, "tree_handles": True},
                         lambda p: (lambda bodies, names: _measured(
                             "split result names independently present in host census",
                             {"tree": bodies, "results": names},
                             len(bodies) == 6 and len(names) == 2
                             and len(set(names)) == 2
                             and set(names) <= {b.get("name") for b in bodies}
                             and sum(b.get("name") == "ConsumedStock"
                                     and b.get("handle") == _RECALL.get("loft_consumed_handle")
                                     for b in bodies) == 1))(
                                 ((p.get("tree") or {}).get("tree") or {}).get("bodies", []),
                                 _RECALL.get("loft_split_names") or []), None))
            for index in range(2):
                rows.append(("model_inspect", lambda c, index=index, host=host: {
                    **_combine_inspect(host + ":" + _ctx_get(
                        c, "loft_split_names", "split loft result bodies")[index])},
                    _loft_split_fragment(index, "loft_split_first_side" if index else None),
                    ("loft_split_first_side", _recall("loft_split_first_side", lambda p:
                        -1 if p["max_point"]["x"] < 0 else 1)) if index == 0 else None))
            for owner, role, expected in (roles[1], roles[3]):
                rows.append(("model_inspect", {"target": f"{owner}:{role}",
                                               "include": ["default", "mass"],
                                               "units": "cm", "accuracy": "very_high"},
                             _loft_scoped_body("split", "after", role, expected,
                                               f"loft_cut_before_{role}"), None))
        rows.extend([
            ("doc_activate", lambda c, story=story, doc=doc: {
                "name": _ctx_get(c, story, "loft story"),
                "expect_document": _ctx_get(c, doc, "loft scratch")}, "ok", None),
            ("doc_close", lambda c, story=story, doc=doc: {
                "name": _ctx_get(c, doc, "loft scratch"), "save_changes": False,
                "expect_document": _ctx_get(c, story, "loft story")},
             _document_closed, None)])
    return rows


_LOFT_PARTICIPANTS = _loft_participants_rows()


def _loft_alignment_census(p):
    """Return host body identities and Loft timeline rows when both slices read."""
    bodies = ((p.get("tree") or {}).get("tree") or {}).get("bodies")
    timeline = (p.get("timeline") or {}).get("timeline")
    if not isinstance(bodies, list) or not isinstance(timeline, list):
        return None
    return {"bodies": sorted((b.get("name"), b.get("handle")) for b in bodies),
            "lofts": sorted((r.get("name"), r.get("health")) for r in timeline
                            if r.get("component") == "LoftEdgeAlign"
                            and r.get("type") == "LoftFeature")}


def _loft_alignment_face(p):
    """Return the source face's independent area, position and cylinder geometry."""
    row = (p.get("matches") or [{}])[0]
    return {key: row.get(key) for key in ("kind", "area", "position", "radius", "axis")}


def _loft_alignment_world(x, y):
    """Return the placed host's world query point in mm."""
    angle = math.radians(25)
    return [100 + math.cos(angle) * x - math.sin(angle) * y,
            50 + math.sin(angle) * x + math.cos(angle) * y, 0]


def _loft_alignment_rows():
    """Demonstrate open-edge alignment through owned-component public geometry reads."""
    rows = []
    host, decoy = "LoftEdgeAlign", "LoftEdgeDecoy"
    rows.append(("design_activate_component", {"occurrence": "root"}, "ok", None))
    rows.append(("model_create_component", {"name": host, "activate": True,
                                            "x": 100, "y": 50, "rotate_deg": 25},
                 _made_component, None))
    rows.append(("model_construction", {"kind": "plane", "plane": "xy",
                                         "offset": 30, "name": "LoftAlignTop"},
                 _datum_plane("xy"), None))
    rows.append(("design_activate_component", {"occurrence": "root"}, "ok", None))
    rows.append(("model_create_component", {"name": decoy, "activate": True},
                 _made_component, None))
    rows.extend([
        ("sketch_create", {"plane": "xy", "name": "LoftAlignWitnessS"}, "ok", None),
        ("sketch_add_geometry", {"sketch_name": "LoftAlignWitnessS", "geometry": [
            {"kind": "rectangle", "x1": 3000, "y1": 3000, "x2": 3010, "y2": 3010}]},
         "ok", None),
        ("model_extrude", {"sketch_name": "LoftAlignWitnessS", "distance": 10},
         _extruded, ("la_witness", lambda p: p["result_bodies"][0])),
        ("model_inspect", lambda c: {"target": decoy + ":" +
             _ctx_get(c, "la_witness", "Loft witness"), "include": ["mass"], "units": "cm"},
         lambda p: _measured("unrelated Loft witness before alignment",
                             (p.get("mass") or {}).get("volume"),
                             _near((p.get("mass") or {}).get("volume"), 1.0, 0.001)), None),
    ])

    cases = (("start_g1_free", 2600, "start", "tangent", "free", 322.7386),
             ("start_g1_edges", 2660, "start", "tangent", "align_edges", 346.3860),
             ("end_g2_free", 2720, "end", "smooth", "free", 321.6790),
             ("end_g2_surface", 2780, "end", "smooth", "align_surface", 347.9951))
    for label, x, side, condition, alignment, expected_area in cases:
        source, target = label + "Source", label + "Target"
        source_key, edge_key, loft_key = label + "Body", label + "Edge", label + "Loft"
        shape_key = label + "SourceShape"
        rows.extend([
            ("design_activate_component", {"occurrence": host + ":1"}, "ok", None),
            ("sketch_create", {"plane": "xy", "name": source}, "ok", None),
            ("sketch_add_geometry", {"sketch_name": source, "component": host,
                                      "geometry": [{"kind": "arc", "cx": x, "cy": 1,
                                                    "x1": x + 8, "y1": 1,
                                                    "sweep_deg": 90}]}, "ok", None),
            ("model_extrude", {"sketch_name": source, "component": host,
                               "distance": -10, "as_surface": True},
             lambda p: p.get("is_solid") is False and len(p.get("result_bodies") or []) == 1,
             (source_key, lambda p: p["result_bodies"][0])),
            ("find_geometry", lambda c, key=source_key: {
                "target": host + ":" + _ctx_get(c, key, "alignment source body"),
                "kind": "cylinder_face", "units": "mm", "max_results": 1},
             lambda p: _measured("a single quarter-cylinder source face before Loft",
                                  p.get("matches"), p.get("match_count") == 1
                                  and _near((p["matches"][0]).get("area"), 125.664, 0.5)),
             (shape_key, _recall(shape_key, _loft_alignment_face))),
            ("find_geometry", lambda c, key=source_key, near=x: {
                "target": host + ":" + _ctx_get(c, key, "alignment source body"),
                "kind": "arc_edge", "radius": 8,
                "nearest_to": _loft_alignment_world(near + 6, 7),
                "units": "mm", "max_results": 1},
             lambda p: _measured("one top connected arc edge", p.get("matches"),
                                  p.get("match_count") == 2 and p.get("returned") == 1
                                  and _near((p["matches"][0]).get("length"), 12.566, 0.05)
                                  and _near(((p["matches"][0]).get("position") or
                                             [None, None, None])[2], 0, 0.05)),
             _fg(edge_key)),
            ("sketch_create", {"plane": "LoftAlignTop", "name": target}, "ok", None),
            ("sketch_add_geometry", {"sketch_name": target, "component": host,
                                      "geometry": [{"kind": "arc", "cx": x + 5, "cy": 1,
                                                    "x1": x + 11, "y1": 1,
                                                    "sweep_deg": 90}]}, "ok", None),
            ("design_activate_component", {"occurrence": decoy + ":1"}, "ok", None),
            ("model_loft", lambda c, s=side, cond=condition, mode=alignment,
                           edge=edge_key, target=target: {
                "profiles": ([_ctx_get(c, edge, "connected source edge"), target + "/arc:0"]
                             if s == "start" else
                             [target + "/arc:0", _ctx_get(c, edge, "connected source edge")]),
                "component": host, "as_surface": True, "operation": "new",
                s: cond, s + "_alignment": mode},
             lambda p, s=side, cond=condition, mode=alignment: _measured(
                 "owned open-edge Loft control", p,
                 p.get("lofted") is True and p.get("is_solid") is False
                 and p.get("section_kinds") == (["open_edge", "curve"] if s == "start"
                                                  else ["curve", "open_edge"])
                 and (p.get("ends") or {}).get(s) == cond
                 and p.get(s + "_alignment") == mode
                 and len(p.get("result_bodies") or []) == 1),
             (loft_key, lambda p: {"feature": host + "/" + p["feature"],
                                   "body": host + ":" + p["result_bodies"][0]})),
            ("design_get", lambda c, key=loft_key: {
                "include": ["definition"],
                "feature": _ctx_get(c, key, "aligned Loft")["feature"]},
             lambda p, s=side, mode=alignment: _measured(
                 "Loft definition in its source component", p.get("definition"),
                 (p.get("definition") or {}).get("component") == host
                 and (p.get("definition") or {}).get("section_count") == 2
                 and (p.get("definition") or {}).get(s + "_alignment") == mode
                 and (p.get("definition") or {}).get("is_solid") is False), None),
            ("find_geometry", lambda c, key=loft_key: {
                "target": _ctx_get(c, key, "aligned Loft")["body"],
                "kind": "nurbs_face", "units": "mm", "max_results": 1},
             lambda p, want=expected_area, mode=alignment, s=side: _measured(
                 "aligned Loft body area independently differs from Free",
                 p.get("matches"), p.get("match_count") == 1
                 and _near((p["matches"][0]).get("area"), want, 5)
                 and (mode == "free" or
                      (p["matches"][0]).get("area", 0) >
                      _RECALL.get(s + "_free_area", float("inf")) + 15)),
             ((side + "_free_area", _recall(side + "_free_area",
               lambda p: p["matches"][0]["area"])) if alignment == "free" else None)),
            ("model_measure_continuity", lambda c, edge=edge_key, key=loft_key: {
                "edges": [_ctx_get(c, edge, "connected source edge")],
                "against": _ctx_get(c, key, "aligned Loft")["body"],
                "samples": 9, "units": "mm"},
             lambda p, cond=condition: _measured(
                 "nine sampled points on the connected Loft seam", p.get("edges"),
                 len(p.get("edges") or []) == 1
                 and (p["edges"][0]).get("samples") == 9
                 and _num((p["edges"][0]).get("max_gap"))
                 and p["edges"][0]["max_gap"] < 0.02
                 and _num((p["edges"][0]).get("max_normal_angle_deg"))
                 and p["edges"][0]["max_normal_angle_deg"] < 0.5
                 and (cond != "smooth" or
                      (_num((p["edges"][0]).get("max_curvature_jump"))
                       and p["edges"][0]["max_curvature_jump"] < 0.01))), None),
            ("find_geometry", lambda c, key=source_key: {
                "target": host + ":" + _ctx_get(c, key, "alignment source body"),
                "kind": "cylinder_face", "units": "mm", "max_results": 1},
             lambda p, key=shape_key: _measured("original connected sheet remains unchanged",
                                  p.get("matches"), p.get("match_count") == 1
                                  and _loft_alignment_face(p) == _RECALL.get(key)
                                  and _near((p["matches"][0]).get("area"), 125.664, 0.5)), None),
        ])
    rows.extend([
        ("design_get", {"include": ["tree", "timeline"], "component": host,
                        "tree_bodies": True, "tree_handles": True, "max_results": 2000},
         lambda p: _measured("alignment guard baseline census", _loft_alignment_census(p),
                             _loft_alignment_census(p) is not None),
         ("la_guard_census", _recall("la_guard_census", _loft_alignment_census))),
        ("model_loft", lambda c: {"profiles": ["end_g2_surfaceTarget/arc:0",
                            _ctx_get(c, "end_g2_surfaceEdge", "connected source edge")],
                            "component": host, "as_surface": True, "end": "smooth",
                            "start_alignment": "align_edges"},
         _refused("start_alignment"), None),
        ("design_get", {"include": ["tree", "timeline"], "component": host,
                        "tree_bodies": True, "tree_handles": True, "max_results": 2000},
         lambda p: _measured("invalid alignment left feature and body census unchanged",
                             _loft_alignment_census(p),
                             _loft_alignment_census(p) is not None
                             and _loft_alignment_census(p) == _RECALL.get("la_guard_census")), None),
    ])
    rows.extend([
        ("model_inspect", lambda c: {"target": decoy + ":" +
             _ctx_get(c, "la_witness", "Loft witness"), "include": ["mass"], "units": "cm"},
         lambda p: _measured("unrelated Loft witness still has its original volume",
                             (p.get("mass") or {}).get("volume"),
                             _near((p.get("mass") or {}).get("volume"), 1.0, 0.001)), None),
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ])
    return rows


_LOFT_ALIGNMENT = _loft_alignment_rows()


def _loft_endpoint_rows():
    """Refuse both endpoints without reorder advice, then verify the legal interior workflow."""
    from verify_core import _activated
    rows = [("doc_get", {}, _home_document, ("endpoint_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "endpoint_story", "story")},
             _new_document, ("endpoint_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "endpoint_doc", args(c) if callable(args) else args), check, save))

    for offset, name in ((10, "MiddlePlane"), (20, "EndPlane")):
        write("model_construction", {"kind": "plane", "plane": "xy", "offset": offset, "name": name},
              _datum_plane("xy"))
    for name, plane, radius in (("Start", "xy", 5), ("Middle", "MiddlePlane", 4), ("End", "EndPlane", 3)):
        write("sketch_create", {"name": name, "plane": plane})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [
            {"kind": "circle", "cx": 0, "cy": 0, "radius": radius}]})
    write("model_loft", {"profiles": [{"sketch": name, "profile_index": 0}
                                      for name in ("Start", "Middle", "End")], "operation": "new"},
          _lofted, ("endpoint_body", lambda p: p["result_bodies"][0]))
    write("sketch_create", {"name": "Later", "plane": "MiddlePlane"})
    write("sketch_add_geometry", {"sketch_name": "Later", "geometry": [
        {"kind": "circle", "cx": 0, "cy": 0, "radius": 6}]})
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True})
    body_args = lambda c: _combine_inspect(_ctx_get(c, "endpoint_body", "Loft body"))
    rows.append(("model_inspect", body_args,
                 _combine_body("original Loft", (-5, -5, 0), (5, 5, 20), 1026.2536), None))
    rows += _retire_reads("loft_endpoint", [""], [])
    write("model_edit_loft", {"feature": "Loft1", "action": "retarget", "section_index": 0,
                              "profile": {"sketch": "Later", "profile_index": 0}},
          _refused("'section_index'=0 is an endpoint", "Choose an interior", "Nothing was edited"))
    rows += _retire_reads("loft_endpoint", [""], [], True)
    write("model_edit_loft", {"feature": "Loft1", "action": "retarget", "section_index": 2,
                              "profile": {"sketch": "Later", "profile_index": 0}},
          _refused("'section_index'=2 must select an interior section of 3", "Nothing was edited"))
    rows += _retire_reads("loft_endpoint", [""], [], True)
    write("model_edit_loft", {"feature": "Loft1", "action": "retarget", "section_index": 1,
                              "profile": {"sketch": "Later", "profile_index": 0}},
          _later_refusal("Later", 6, "Loft1", 5))
    rows += _retire_reads("loft_endpoint", [""], [], True)
    write("design_edit_timeline", {"action": "reorder", "feature": "Later@6", "to": "before",
                                   "end_feature": "Loft1@5"},
          lambda p: _measured("legal interior source moved before Loft", p,
                               p.get("reordered") is True and (p.get("index_before"), p.get("index_after")) == (6, 5)))
    rows += [("design_get", {"include": ["timeline"], "max_results": 200},
              _timeline_reads("legal Loft source reorder keeps all seven rows healthy",
                              lambda names: names == ["MiddlePlane", "EndPlane", "Start", "Middle", "End", "Later", "Loft1"]), None),
             ("model_inspect", {**_combine_inspect(), "per_body": True},
              _retire_compare("loft_endpoint_", _retire_material_state, True), None)]
    write("model_edit_loft", {"feature": "Loft1", "action": "retarget", "section_index": 1,
                              "profile": {"sketch": "Later", "profile_index": 0}},
          lambda p: _measured("legal later interior section changed", p,
                               p.get("edited") is True and p.get("definition_matches") is True
                               and p.get("geometry_changed") is True and p.get("marker_restored") is True
                               and p.get("outside_body_changes") == []))
    rows += [("model_inspect", body_args,
              _combine_body("retargeted Loft", (-6.107822, -6.107822, 0), (6.107822, 6.107822, 20), 1829.564155), None),
             ("design_get", {"include": ["timeline"], "max_results": 200},
              _timeline_reads("legal interior edit keeps every healthy timeline row and order",
                              lambda names: names == ["MiddlePlane", "EndPlane", "Start", "Middle", "End", "Later", "Loft1"]), None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "endpoint_story", "story"),
                                         "expect_document": _ctx_get(c, "endpoint_doc", "scratch")}, _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "endpoint_doc", "scratch"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "endpoint_story", "story")}, _document_closed, None)]
    return rows


_LATER_OPERAND += _loft_endpoint_rows()


_GUIDED_SWEEP_CREATE = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None, 'owned unsaved scratch only'
    design = adsk.fusion.Design.cast(app.activeProduct)
    component = design.rootComponent
    main = component.features.createPath(
        component.sketches.itemByName('GuidedMain').sketchCurves.sketchLines.item(0), False)
    guide = component.features.createPath(
        component.sketches.itemByName('GuidedRail').sketchCurves.sketchLines.item(0), False)
    feature_input = component.features.sweepFeatures.createInput(
        component.sketches.itemByName('GuidedSeed').profiles.item(0), main,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    feature_input.guideRail = guide
    feature = component.features.sweepFeatures.add(feature_input)
    assert feature is not None
    feature.name = 'GuidedSweep'
    print(json.dumps({'name': feature.name, 'health': int(feature.healthState)}))
"""

_GUIDED_SWEEP_NATIVE = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None, 'owned unsaved scratch only'
    design = adsk.fusion.Design.cast(app.activeProduct)
    component = design.rootComponent
    feature = component.features.sweepFeatures.itemByName('GuidedSweep')
    def body_state():
        return [{'name': body.name, 'faces': body.faces.count,
                 'volume_cm3': round(body.physicalProperties.volume, 9),
                 'bounds_cm': [[round(body.boundingBox.minPoint.x, 9),
                                round(body.boundingBox.minPoint.y, 9),
                                round(body.boundingBox.minPoint.z, 9)],
                               [round(body.boundingBox.maxPoint.x, 9),
                                round(body.boundingBox.maxPoint.y, 9),
                                round(body.boundingBox.maxPoint.z, 9)]]}
                for body in component.bRepBodies]
    before = body_state()
    marker = design.timeline.markerPosition
    try:
        assert feature.timelineObject.rollTo(True)
        rail = feature.guideRail
        mode = {'guide_rail': [] if rail is None else [
            {'sketch': rail.item(i).entity.parentSketch.name,
             'construction': rail.item(i).entity.isConstruction} for i in range(rail.count)],
            'guide_surfaces': len(feature.guideSurfaces), 'solid_body': feature.solidBody is not None}
    finally:
        design.timeline.markerPosition = marker
        assert design.timeline.markerPosition == marker
    assert before == body_state(), 'mode read changed body state'
    print(json.dumps({'mode': mode, 'health': int(feature.healthState),
        'message': feature.errorOrWarningMessage, 'marker': marker,
        'order': [design.timeline.item(i).name for i in range(design.timeline.count)],
        'bodies': body_state()}))
"""


def _guided_sweep_native_state(p):
    """Return measured guide mode, healthy history and body state when fully readable."""
    mode = p.get("mode") or {}
    bodies, order = p.get("bodies"), p.get("order")
    bounds = (bodies[0].get("bounds_cm") if isinstance(bodies, list) and len(bodies) == 1
              and isinstance(bodies[0], dict) else None)
    if (mode != {"guide_rail": [{"sketch": "GuidedRail", "construction": False}],
                 "guide_surfaces": 0, "solid_body": False}
            or p.get("health") != 0 or p.get("message") != "" or p.get("marker") != 5
            or order != ["GuidedSeed", "GuidedMain", "GuidedRail", "GuidedSweep", "LaterProfile"]
            or not isinstance(bodies, list) or len(bodies) != 1
            or bodies[0].get("name") != "Body1" or bodies[0].get("faces") != 3
            or not _near(bodies[0].get("volume_cm3"), 0.031415927, 0.000001)
            or not isinstance(bounds, list) or len(bounds) != 2
            or not all(isinstance(side, list) and len(side) == 3 for side in bounds)
            or not all(_near(got, want, 0.000001) for got, want in zip(
                [v for side in bounds for v in side], [0, -0.1, -0.1, 1, 0.1, 0.1]))):
        return None
    body = bodies[0]
    stable_body = {"name": body["name"], "faces": body["faces"],
                   "volume_cm3": round(body["volume_cm3"], 8),
                   "bounds_cm": [[round(v, 8) for v in side] for side in bounds]}
    return {"mode": mode, "health": p["health"], "message": p["message"], "marker": p["marker"],
            "order": order, "bodies": [stable_body]}


def _guided_sweep_native_read(stage):
    """Compare independent native mode and body evidence before and after the refusal."""
    def check(p):
        now, before = _guided_sweep_native_state(p), _RECALL.get("guided_sweep_native")
        valid = now is not None and (stage == "before" or now == before)
        if valid and stage == "before":
            _RECALL["guided_sweep_native"] = now
        return _measured("guided mode and native body/history " + stage, now, valid)
    return check


def _guided_sweep_design(stage):
    """Check the typed timeline read before and after the guided-mode refusal."""
    def check(p):
        timeline = p.get("timeline") or {}
        names = _timeline_names(p)
        before = _RECALL.get("guided_sweep_timeline")
        valid = (p.get("design_type") == "parametric" and names == [
            "GuidedSeed", "GuidedMain", "GuidedRail", "GuidedSweep", "LaterProfile"]
            and timeline.get("count") == timeline.get("marker_position") == 5
            and (stage == "before" or names == before))
        if valid and stage == "before":
            _RECALL["guided_sweep_timeline"] = names
        return _measured("typed healthy timeline " + stage, timeline, valid)
    return check


def _guided_sweep_body(stage):
    """Compare independent typed material and bounds before and after the refusal."""
    def check(p):
        measured = _sweep_mode_shape(p)
        minimum, maximum = measured.get("min") or {}, measured.get("max") or {}
        now = {"volume": round(measured["volume"], 8) if _num(measured.get("volume")) else None,
               "area": round(measured["area"], 8) if _num(measured.get("area")) else None,
               "min": {k: round(v, 8) for k, v in minimum.items() if _num(v)},
               "max": {k: round(v, 8) for k, v in maximum.items() if _num(v)}}
        before = _RECALL.get("guided_sweep_body")
        valid = (p.get("kind") == "body" and p.get("units") == "cm"
                 and _near((p.get("mass") or {}).get("volume"), 0.031415927, 0.000001)
                 and all(_near(minimum.get(k), v, 0.000001) for k, v in
                         (("x", 0), ("y", -0.1), ("z", -0.1)))
                 and all(_near(maximum.get(k), v, 0.000001) for k, v in
                         (("x", 1), ("y", 0.1), ("z", 0.1)))
                 and (stage == "before" or now == before))
        if valid and stage == "before":
            _RECALL["guided_sweep_body"] = now
        return _measured("typed body material and bounds " + stage, now, valid)
    return check


def _guided_sweep_rows():
    """Exercise a guided Sweep's mode refusal with independent native and typed state reads."""
    rows = [
        ("doc_get", {}, _home_document, ("guided_story", _home_address)),
        ("doc_new", lambda c: {"expect_document": _ctx_get(c, "guided_story", "story")},
         _new_document, ("guided_doc", lambda p: p["document_handle"])),
    ]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "guided_doc", args(c) if callable(args) else args), check, save))

    write("sketch_create", {"name": "GuidedSeed", "plane": "yz"})
    write("sketch_add_geometry", {"sketch_name": "GuidedSeed", "units": "mm",
                                  "geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 1}]})
    write("sketch_create", {"name": "GuidedMain", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "GuidedMain", "units": "mm",
                                  "geometry": [{"kind": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}]})
    write("sketch_create", {"name": "GuidedRail", "plane": "xz"})
    write("sketch_add_geometry", {"sketch_name": "GuidedRail", "units": "mm",
                                  "geometry": [{"kind": "line", "x1": 0, "y1": 1, "x2": 10, "y2": 1}]})
    write("sys_execute_script", {"script": _GUIDED_SWEEP_CREATE, "read_only": False},
          lambda p: _measured("guided sweep fixture created", p, p.get("name") == "GuidedSweep"
                              and p.get("health") == 0))
    write("sketch_create", {"name": "LaterProfile", "plane": "yz"})
    write("sketch_add_geometry", {"sketch_name": "LaterProfile", "units": "mm",
                                  "geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 0.5}]})
    rows.extend([
        ("sys_execute_script", {"script": _GUIDED_SWEEP_NATIVE, "read_only": False},
         _guided_sweep_native_read("before"), None),
        ("design_get", {"include": ["default", "tree", "timeline"], "tree_bodies": True,
                         "max_results": 100}, _guided_sweep_design("before"), None),
        ("model_inspect", {"target": "Body1", "include": ["default", "mass"],
                            "accuracy": "very_high", "units": "cm"},
         _guided_sweep_body("before"), None),
    ])
    write("model_edit_sweep", {"feature": "GuidedSweep", "action": "profile",
                               "profile": {"sketch": "LaterProfile", "profile_index": 0}},
          _refused("This action supports only a Sweep without a guide or solid-tool definition",
                   "Nothing was edited"))
    rows.extend([
        ("sys_execute_script", {"script": _GUIDED_SWEEP_NATIVE, "read_only": False},
         _guided_sweep_native_read("after"), None),
        ("design_get", {"include": ["default", "tree", "timeline"], "tree_bodies": True,
                         "max_results": 100}, _guided_sweep_design("after"), None),
        ("model_inspect", {"target": "Body1", "include": ["default", "mass"],
                            "accuracy": "very_high", "units": "cm"},
         _guided_sweep_body("after"), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, "guided_story", "story"),
                                     "expect_document": _ctx_get(c, "guided_doc", "guided scratch")},
         "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "guided_doc", "guided scratch"),
                                  "save_changes": False,
                                  "expect_document": _ctx_get(c, "guided_story", "story")},
         _document_closed, None),
    ])
    return rows


_LATER_OPERAND += _guided_sweep_rows()


def _partial_path_shape(length):
    """Check an independently read unit-radius solid against the selected path length."""
    def check(p):
        lo, hi, mass = p.get("min_point") or {}, p.get("max_point") or {}, p.get("mass") or {}
        valid = (p.get("kind") == "body" and p.get("units") == "mm"
                 and _near(mass.get("volume"), math.pi * length, 0.001)
                 and all(_near((lo if side == "min" else hi).get(axis), value, 0.001)
                         for side, axis, value in (("min", "x", 0), ("max", "x", length),
                             ("min", "y", -1), ("max", "y", 1), ("min", "z", -1), ("max", "z", 1))))
        return _measured("partial path independent material and bounds", {"min": lo, "max": hi, "mass": mass}, valid)
    return check


def _partial_path_datum(kind, name, plane=False):
    """Check a named on-path datum through an independent geometry acquisition."""
    def check(p):
        row = (p.get("matches") or [{}])[0]
        pos, normal = row.get("position"), row.get("normal")
        valid = (p.get("match_count") == p.get("returned") == 1
                 and row.get("kind") == kind and row.get("name") == name
                 and isinstance(pos, list) and len(pos) == 3
                 and _near(pos[0], 10, .001) and _near(pos[1], 0, .001)
                 and _near(pos[2], 0, .001))
        if plane:
            valid = (valid and isinstance(normal, list) and len(normal) == 3
                     and _near(abs(normal[0]), 1, .000001)
                     and _near(normal[1], 0, .000001) and _near(normal[2], 0, .000001))
        return _measured("partial-path datum independent position and orientation", row, valid)
    return check


def _partial_pattern_history(stage):
    """Compare complete body and feature counts around a partial-path body pattern."""
    def check(p):
        state = _retire_design_state(p)
        if state is None:
            return _measured("partial-path pattern complete history and body census " + stage, p, False)
        tree = state["tree"]
        bodies = tree.get("root_bodies") or []
        timeline = state["timeline"].get("timeline") or []
        current = {"bodies": sorted((b.get("name"), b.get("handle")) for b in bodies),
                   "timeline": [(r.get("name"), r.get("type")) for r in timeline]}
        before = _RECALL.get("partial_path_pattern_before")
        if stage == "before":
            _RECALL["partial_path_pattern_before"] = current
            return _measured("partial-path pattern protected census before", current,
                             len(bodies) > 0 and not tree.get("children")
                             and p.get("contents", {}).get("bodies") == len(bodies)
                             and all(name and handle for name, handle in current["bodies"]))
        old_handles = {handle for _name, handle in (before or {}).get("bodies", [])}
        new_bodies = [(name, handle) for name, handle in current["bodies"]
                      if handle not in old_handles]
        old_timeline = (before or {}).get("timeline", [])
        feature = (_RECALL.get("partial_path_pattern_feature") or "")
        valid = (before is not None and len(current["bodies"]) == len(before["bodies"]) + 1
                 and {h for _n, h in current["bodies"]} >= old_handles
                 and len(current["timeline"]) == len(old_timeline) + 1
                 and current["timeline"][:len(old_timeline)] == old_timeline
                 and len(new_bodies) == 1 and bool(new_bodies[0][1])
                 and any(name == feature for name, _kind in current["timeline"][len(old_timeline):]))
        if valid:
            _RECALL["partial_path_pattern_copy"] = new_bodies[0][1]
        return _measured("partial-path pattern added one body and one feature", current, valid)
    return check


def _partial_pattern_copy(length):
    """Check the new body has seed-sized material at an independently shifted position."""
    def check(p):
        shape = _sweep_mode_shape(p)
        lo, hi = shape.get("min") or {}, shape.get("max") or {}
        copied_span = hi.get("x", 0) - lo.get("x", 0)
        copied_center = (hi.get("x", 0) + lo.get("x", 0)) / 2
        valid = (p.get("kind") == "body" and p.get("units") == "mm"
                 and _near(shape.get("volume"), math.pi * length, .001)
                 and all(_num((lo if side == "min" else hi).get(axis)) for side in ("min", "max")
                         for axis in "xyz")
                 and _near(copied_span, length, .001)
                 and _near(abs(copied_center - length / 2), 10, .001)
                 and _near(lo.get("y"), -1, .001) and _near(hi.get("y"), 1, .001)
                 and _near(lo.get("z"), -1, .001) and _near(hi.get("z"), 1, .001))
        return _measured("partial-path pattern copy material and shifted world bounds", shape, valid)
    return check


def _partial_pattern_created(p):
    """Check the path warning and retain the returned feature name for the census read."""
    valid = (p.get("patterned") is True and p.get("type") == "path"
             and p.get("path") == "sketch:OutOfOrder" and p.get("quantity") == 2
             and "Not in the path: line:1" in p.get("note", "") and bool(p.get("feature")))
    if valid:
        _RECALL["partial_path_pattern_feature"] = p["feature"]
    return _measured("partial-path body pattern keeps exact sketch path", p, valid)


def _partial_path_definition(name, indices, orientation):
    """Read the selected native Path's exact sketch-curve identities at the explicit marker."""
    def check(p):
        d = p.get("definition") or {}
        refs = [r.get("curve_ref") for r in d.get("path") or []]
        return _measured("selected Path identities exclude omitted and construction curves", d,
                         d.get("path_count") == len(indices) and d.get("path_truncated") is False
                         and d.get("orientation_name") == orientation
                         and refs == [f"{name}/line:{i}" for i in indices])
    return check


def _partial_path_rows():
    """Compare partial warnings, a separate first run and a genuinely shared-point chain."""
    rows = [("doc_get", {}, _home_document, ("pp_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "pp_home", "home")},
             _new_document, ("pp_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(
            c, "pp_doc", args(c) if callable(args) else args), check, save))

    write("sketch_create", {"name": "PartialProfile", "plane": "yz"})
    write("sketch_add_geometry", {"sketch_name": "PartialProfile", "geometry": [
        {"kind": "circle", "cx": 0, "cy": 0, "radius": 1}]})
    def line(a, b, construction=False):
        return {"kind": "line", "x1": a, "y1": 0, "x2": b, "y2": 0, "is_construction": construction}
    fixtures = [
        ("Disconnected", [line(0, 10), line(20, 30)], [0], 2, 10, "perpendicular"),
        ("SeparateRun", [line(0, 10)], [0], 1, 10, "perpendicular"),
        ("ParallelRun", [line(0, 10)], [0], 1, 10, "parallel"),
        ("OutOfOrder", [line(0, 10), line(20, 30), line(10, 20)], [0, 2], 3, 20, "perpendicular"),
        ("ConstructionBridge", [line(0, 10), line(20, 30), line(10, 20, True)], [0], 2, 10, "perpendicular"),
        ("SharedPointRun", [{"kind": "polyline", "points": [[0, 0], [10, 0], [20, 0], [30, 0]]}], [0, 1, 2], 3, 30, "perpendicular"),
    ]
    for name, geometry, indices, count, length, orientation in fixtures:
        # The non-construction lines are line:0..count-1 in every fixture; the rest were left out.
        left = ", ".join(f"line:{i}" for i in range(count) if i not in indices)
        write("sketch_create", {"name": name, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": geometry})
        write("model_sweep", {"profile": {"sketch": "PartialProfile", "profile_index": 0},
                              "path": "sketch:" + name, "operation": "new", "orientation": orientation},
              lambda p, n=len(indices), count=count, name=name, left=left: _measured(
                  "partial path names the curves it left out", p,
                  p.get("swept") is True and p.get("path_curves") == n
                  and p.get("path_sketch_curves") == count and len(p.get("result_bodies") or []) == 1
                  and p.get("path") == "sketch:" + name
                  and (not left or f"Not in the path: {left}" in p.get("note", ""))
                  and (("WARNING" in p.get("note", "") and "separate path sketch" in p["note"])
                       if n < count else "WARNING" not in p.get("note", ""))),
              ("pp_result", lambda p: {"feature": p["feature"], "body": p["result_bodies"][0]}))
        rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "pp_result", "sweep")["body"],
                     "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                     _partial_path_shape(length), None))
        write("design_edit_timeline", lambda c: {"action": "roll", "to": "before",
                                                  "feature": _ctx_get(c, "pp_result", "sweep")["feature"]})
        rows.append(("design_get", lambda c: {"include": ["definition"],
                     "feature": _ctx_get(c, "pp_result", "sweep")["feature"]},
                     _partial_path_definition(name, indices, orientation), None))
        write("design_edit_timeline", {"action": "roll", "to": "end"})
        if name == "OutOfOrder":
            write("model_construction", {"kind": "point", "mode": "on_path", "path": "sketch:OutOfOrder",
                                          "at": 0.5, "name": "OutOfOrderMidpoint"},
                  lambda p: _measured("partial-path midpoint point created", p,
                                      p.get("created") is True and p.get("path") == "sketch:OutOfOrder"
                                      and p.get("at_ratio") == 0.5
                                      and "Not in the path: line:1" in p.get("note", "")),
                  ("pp_outoforder_midpoint", lambda p: p["handle"]))
            rows.append(("find_geometry", {"kind": "construction_point", "name": "OutOfOrderMidpoint"},
                         _partial_path_datum("construction_point", "OutOfOrderMidpoint"), None))
            write("model_construction", {"kind": "plane", "mode": "on_path", "path": "sketch:OutOfOrder",
                                          "at": 0.5, "name": "OutOfOrderMidplane"},
                  lambda p: _measured("partial-path midpoint plane created", p,
                                      p.get("created") is True and p.get("path") == "sketch:OutOfOrder"
                                      and p.get("at_ratio") == 0.5
                                      and "Not in the path: line:1" in p.get("note", "")))
            rows.append(("find_geometry", {"kind": "construction_plane", "name": "OutOfOrderMidplane"},
                         _partial_path_datum("construction_plane", "OutOfOrderMidplane", plane=True), None))
            write("model_construction", lambda c: {
                  "kind": "plane", "mode": "on_path", "path": "sketch:OutOfOrder",
                  "to_object": _ctx_get(c, "pp_outoforder_midpoint", "midpoint datum handle"),
                  "name": "OutOfOrderObjectPlane"},
                  lambda p: _measured("partial-path point-anchored plane created", p,
                                      p.get("created") is True and p.get("path") == "sketch:OutOfOrder"
                                      and p.get("to_object") is True
                                      and "Not in the path: line:1" in p.get("note", "")))
            rows.append(("find_geometry", {"kind": "construction_plane", "name": "OutOfOrderObjectPlane"},
                         _partial_path_datum("construction_plane", "OutOfOrderObjectPlane", plane=True), None))
            rows.append(("design_get", {"include": ["default", "tree", "timeline"],
                                         "tree_bodies": True, "max_results": 200},
                         _partial_pattern_history("before"), None))
            write("model_pattern_path", lambda c: {
                  "bodies": [_ctx_get(c, "pp_result", "sweep")["body"]],
                  "path": "sketch:OutOfOrder", "quantity": 2, "distance": 10,
                  "distance_type": "spacing"},
                  _partial_pattern_created)
            rows.append(("design_get", {"include": ["default", "tree", "timeline"],
                                         "tree_bodies": True, "max_results": 200},
                         _partial_pattern_history("after"), None))
            rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "pp_result", "sweep")["body"],
                         "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                         _partial_path_shape(length), None))
            rows.append(("model_inspect", lambda _c: {"target": _RECALL.get("partial_path_pattern_copy"),
                         "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                         _partial_pattern_copy(length), None))
    write("doc_activate", lambda c: {"name": _ctx_get(c, "pp_home", "home")})
    rows.append(("doc_close", lambda c: {"name": _ctx_get(c, "pp_doc", "scratch"),
                 "save_changes": False, "expect_document": _ctx_get(c, "pp_home", "home")}, _document_closed, None))
    return rows


_TANGENT_PATH += _partial_path_rows()
