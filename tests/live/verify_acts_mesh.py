# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""ACT rows: the surface-prep, mesh and arrange cameos.

Families with no home on the mechanism ride scratch fixtures in the SAME document - surface bodies
built, trimmed and stitched, a mesh round-tripped through export and insert, and the arrange solver
nesting last, because it adds Arrange/Envelope occurrences beside what it nests.
"""

import copy
import hashlib
import math
from pathlib import Path
import struct

from verify_core import (
    EXPORT_DIR, _RECALL, _activated, _arranged, _base_feature_open, _box, _captured, _ctx_get,
    _datum_plane, _document_closed, _document_read, _drilled, _dwell, _extent_measured, _extruded,
    _fg, _fgn, _holder_computed, _home_address, _home_document, _made_component, _matched, _measured, _mesh_round_trip,
    _near, _needs, _new_document, _num, _packed, _prof, _rebuilt, _recall, _refused, _repair_no_op,
    _same_face_area, _shelled, _split_bodies, _stitched, _trim_scoped_to_target, _unless,
    _unstitched, _watch)
from verify_acts_cam import MACHINING_EXTENSION
from verify_acts_doc import _subject_visible
from verify_acts_model_combine_revolve import _combine_pin
from verify_layout import _px, _py
from verify_acts_model_sweep import (
    _retire_compare, _retire_design_state, _retire_material_state, _retire_reads, _retire_sketch_state,
    _sweep_mode_shape, _sweep_mode_box_equal)
from verify_acts_model_solids import _edge_extent_geometry


def _mesh_remedy_census(p):
    """Return the complete readable target and witness mesh census."""
    rows = p.get("meshes")
    if (p.get("units") != "mm" or p.get("truncated") is not False or p.get("count") != 2
            or not isinstance(rows, list) or len(rows) != 2
            or {r.get("name") for r in rows} != {"CouponMesh", "WitnessMesh"}
            or any(not isinstance(r.get("handle"), str) or not r["handle"]
                   or any(type(r.get(k)) is not int or r[k] <= 0 for k in ("triangle_count", "node_count"))
                   or r.get("polygon_count") != 0 or r.get("is_closed") is not True
                   or r.get("is_oriented") is not True
                   or any(not _num(r.get(k)) or not math.isfinite(r[k]) or r[k] <= 0
                          for k in ("area", "volume")) for r in rows)):
        return None
    return {r["name"]: r for r in rows}


def _mesh_remedy_brep(p):
    """Return independently readable source BRep geometry and material."""
    mass = p.get("mass") or {}
    if (p.get("kind") != "body" or p.get("units") != "mm" or p.get("lump_count") != 1
            or p.get("frame") != "world axes (axis-aligned)"
            or any(not _num((p.get(k) or {}).get(a)) or not math.isfinite(p[k][a])
                   for k in ("min_point", "max_point") for a in "xyz")
            or any(not _num(mass.get(k)) or not math.isfinite(mass[k]) or mass[k] <= 0
                   for k in ("volume", "area", "mass_kg"))):
        return None
    return {"bounds": [p["min_point"], p["max_point"]], "mass": mass, "lump_count": p["lump_count"]}


def _refinement_source(p, after=False):
    """Compare the cylinder's readable geometry before and after exports."""
    now, before = _mesh_remedy_brep(p), _RECALL.get("stl_refinement_source")
    valid = now is not None and (not after or before is not None and now == before)
    if valid and not after:
        _RECALL["stl_refinement_source"] = now
        _RECALL["stl_refinement_files"] = {}
    return _measured("STL export preserves the curved source", now, valid)


def _refinement_artifact(quality, repeat, path):
    """Check the binary triangles, source bounds and same-run refinement effect."""
    def check(p):
        data = Path(path).read_bytes() if Path(path).is_file() else b""
        count = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else 0
        valid = (p.get("exported") is True and p.get("file_path") == path
                 and p.get("format") == "stl" and p.get("refinement") == quality
                 and (p.get("options_applied") or {}).get("stl_units") == "mm"
                 and p.get("size_bytes") == len(data) == 84 + 50 * count and count > 0)
        vertices = []
        if valid:
            for offset in range(84, len(data), 50):
                row = struct.unpack_from("<12fH", data, offset)
                valid = valid and all(math.isfinite(v) for v in row[:12])
                vertices.extend((row[3:6], row[6:9], row[9:12]))
        source = _RECALL.get("stl_refinement_source") or {}
        bounds = source.get("bounds") or []
        if vertices and len(bounds) == 2:
            actual = [[fn(v[i] for v in vertices) for i in range(3)] for fn in (min, max)]
            valid = valid and all(_near(actual[end][i], bounds[end].get(axis), .05)
                                  for end in range(2) for i, axis in enumerate("xyz"))
        else:
            valid = False
        digest = hashlib.sha256(data[84:]).hexdigest()
        observed = {"triangles": count, "sha256": digest, "bytes": len(data)}
        files = _RECALL.get("stl_refinement_files") or {}
        if repeat:
            valid = valid and observed == files.get(quality)
        else:
            valid = valid and all(digest != row["sha256"] for row in files.values())
        if quality == "low":
            valid = valid and count < files.get("medium", {}).get("triangles", 0)
        elif quality == "high":
            valid = valid and count > files.get("medium", {}).get("triangles", float("inf"))
        if valid and not repeat:
            files[quality] = observed
            _RECALL["stl_refinement_files"] = files
        return _measured("STL refinement changes triangles; repeats agree", observed, valid)
    return check


def _refinement_rows():
    """Export the same curved body at three settings and repeat both finer settings."""
    args = lambda c: {"target": _ctx_get(c, "cyl_brep", "curved source body"),
                      "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"}
    rows = [("model_inspect", args, _refinement_source, None)]
    for quality, repeat in (("medium", False), ("high", False), ("low", False),
                            ("medium", True), ("high", True)):
        path = EXPORT_DIR + "/eval_refinement_" + quality + ("_repeat" if repeat else "") + ".stl"
        rows.append(("mesh_export", lambda c, q=quality, f=path: {
            "target": _ctx_get(c, "cyl_body", "curved source"), "file_path": f,
            "format": "stl", "refinement": q, "stl_units": "mm"},
            _refinement_artifact(quality, repeat, path), None))
    rows.append(("model_inspect", args, lambda p: _refinement_source(p, True), None))
    return rows


def _mesh_remedy_reduced(p):
    """Check target decimation from its advertised handle and exact witness preservation."""
    now, before = _mesh_remedy_census(p), _RECALL.get("mesh_remedy_census")
    valid = (now is not None and before is not None
             and now["WitnessMesh"] == before["WitnessMesh"]
             and before["CouponMesh"]["triangle_count"] == 76
             and now["CouponMesh"]["triangle_count"] == 38
             and now["CouponMesh"]["node_count"] == 42
             and now["CouponMesh"]["volume"] < before["CouponMesh"]["volume"])
    return _measured("only the advertised target mesh decimated; witness held", now, valid)


def _organic_source_retained(p):
    """Read the closed source mesh after the organic API outcome."""
    rows = [m for m in p.get("meshes") or [] if m.get("name") == "MA"]
    row = rows[0] if len(rows) == 1 else {}
    return _measured("organic source mesh remains readable",
                     {"count": len(rows), "is_closed": row.get("is_closed"),
                      "triangle_count": row.get("triangle_count")},
                     p.get("truncated") is False and row.get("is_closed") is True
                     and _num(row.get("triangle_count")) and row["triangle_count"] > 0)


def _failed_mesh_scope_timeline(p, after=False):
    """Compare the bounded Mesh-to-BRep failure's retained timeline row independently."""
    timeline = p.get("timeline") or {}
    rows = timeline.get("timeline") or []
    now = [(row.get("name"), row.get("type"), row.get("index")) for row in rows]
    complete = (timeline.get("count") == timeline.get("marker_position") == len(rows)
                and not timeline.get("truncated")
                and (timeline.get("summary") or {}).get("states") == {"healthy": len(rows)})
    key = "mesh_failed_scope_timeline"
    before = _RECALL.get(key)
    if not after:
        if complete:
            _RECALL[key] = now
        return _measured("parametric history before failed mesh conversion", now, complete)
    added = now[len(before):] if complete and before is not None and now[:len(before)] == before else []
    valid = (complete and before is not None and len(added) == 1
             and isinstance(added[0][0], str) and added[0][0].startswith("Base Feature")
             and added[0][1] == "BaseFeature"
             and added[0][2] == len(before))
    return _measured("failed conversion's retained base-feature history row", {
        "before": before, "after": now, "added": added}, valid)


def _mesh_remedy_rows():
    """Exercise a plain miss, its mesh_get remedy and independently scoped decimation."""
    rows = [("doc_get", {}, _home_document, ("mr_story", _home_address)),
            ("doc_new", {}, _new_document, None),
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("doc_get", {}, _home_document, ("mr_doc", _home_address))]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, a=args: dict(a), check, save))
    write("sketch_create", {"name": "MeshSeed", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "MeshSeed",
                                "geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 5}]})
    write("model_extrude", {"sketch_name": "MeshSeed", "distance": 10}, _extruded,
          ("mr_body", lambda p: p["result_bodies"][0]))
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True})
    for name in ("CouponMesh", "WitnessMesh"):
        rows.append(("save_as_mesh", lambda c, n=name: {"body": _ctx_get(c, "mr_body", "source BRep"),
                                                        "name": n, "quality": "low"}, "ok", None))
    census = {"units": "mm", "max_results": 100}
    history = {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
               "max_depth": 10, "max_results": 2000}
    def brep(after):
        return ("model_inspect", lambda c: {"target": _ctx_get(c, "mr_body", "source BRep"),
                                            "include": ["default", "mass"], "accuracy": "very_high", "units": "mm"},
                _retire_compare("mesh_remedy_brep", _mesh_remedy_brep, after), None)
    rows += [("mesh_get", census, _retire_compare("mesh_remedy_census", _mesh_remedy_census, False), None),
             ("design_get", history, _retire_compare("mesh_remedy_design", _retire_design_state, False), None), brep(False)]
    write("mesh_reduce", {"mesh": "MissingMesh", "target": "proportion", "value": 50},
          _refused("MissingMesh", "mesh_get"))
    rows += [("mesh_get", census, _retire_compare("mesh_remedy_census", _mesh_remedy_census, True), None),
             ("design_get", history, _retire_compare("mesh_remedy_design", _retire_design_state, True), None), brep(True),
             ("mesh_get", census, _retire_compare("mesh_remedy_census", _mesh_remedy_census, True),
              ("mr_mesh", lambda p: _mesh_remedy_census(p)["CouponMesh"]["handle"])),
             ("mesh_reduce", lambda c: {"mesh": _ctx_get(c, "mr_mesh", "mesh_get target handle"),
                                         "target": "proportion", "value": 50},
              lambda p: _measured("target mesh reduce reports the observed count change", p,
                                  p.get("reduced") is True and (p.get("before") or {}).get("triangle_count") == 76
                                  and (p.get("after") or {}).get("triangle_count") == 38), None),
             ("mesh_get", census, _mesh_remedy_reduced, None), brep(True),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "mr_story", "story"),
                                         "expect_document": _ctx_get(c, "mr_doc", "mesh scratch")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "mr_doc", "mesh scratch"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "mr_story", "story")}, _document_closed, None)]
    return rows


def _base_feature_state(p):
    """The complete mode and timeline values used around a base-feature scope."""
    mode = p.get("mode_detail") or {}
    timeline = p.get("timeline") or {}
    rows = timeline.get("timeline") or []
    return {
        "design_type": mode.get("design_type"),
        "has_timeline": mode.get("has_timeline"),
        "timeline_feature_count": mode.get("timeline_feature_count"),
        "base_feature_count": mode.get("base_feature_count"),
        "timeline_count": timeline.get("count"),
        "returned": timeline.get("returned"),
        "truncated": timeline.get("truncated") is True,
        "rows": [[row.get("index"), row.get("name"), row.get("type")] for row in rows],
    }


def _base_feature_parametric(p):
    """A complete parametric mode/timeline baseline."""
    state = _base_feature_state(p)
    count = state["timeline_count"]
    complete = (isinstance(count, int) and state["returned"] == count
                and len(state["rows"]) == count and not state["truncated"])
    return _measured(
        "complete parametric base-feature baseline",
        state,
        state["design_type"] == "parametric" and state["has_timeline"] is True
        and state["timeline_feature_count"] == count
        and isinstance(state["base_feature_count"], int) and complete)


def _base_feature_direct(p):
    """An independent mode read while a base-feature scope is open."""
    mode = p.get("mode_detail") or {}
    facts = {key: mode.get(key) for key in
             ("design_type", "has_timeline", "timeline_feature_count")}
    return _measured(
        "open base-feature mode",
        facts,
        facts["design_type"] == "direct" and facts["has_timeline"] is False
        and facts["timeline_feature_count"] is None)


def _base_feature_same_name(name_key):
    """An opened scope whose adopted name equals the first document's adopted name."""
    def check(p):
        _base_feature_open(p)
        expected = _RECALL[name_key]
        actual = p.get("base_feature")
        return _measured(
            "same adopted base-feature name before cross-document finish",
            {"expected": expected, "actual": actual}, actual == expected)
    return check


def _base_feature_added(before_key, name_key):
    """The complete parametric timeline after one named base feature was added."""
    def check(p):
        before = _RECALL[before_key]
        after = _base_feature_state(p)
        remaining = list(after["rows"])
        preserved = True
        for row in before["rows"]:
            if row in remaining:
                remaining.remove(row)
            else:
                preserved = False
        expected_name = _RECALL[name_key]
        added = (len(remaining) == 1 and remaining[0][1] == expected_name
                 and remaining[0][2] == "BaseFeature")
        complete = (after["returned"] == after["timeline_count"] == len(after["rows"])
                    and not after["truncated"])
        valid = (
            after["design_type"] == "parametric" and after["has_timeline"] is True
            and after["timeline_feature_count"] == after["timeline_count"]
            and after["timeline_count"] == before["timeline_count"] + 1
            and after["base_feature_count"] == before["base_feature_count"] + 1
            and preserved and added and complete)
        return _measured(
            f"one BaseFeature named {expected_name} added to the complete timeline",
            {"before_count": before["timeline_count"], "after": after,
             "added_rows": remaining, "expected_name": expected_name},
            valid)
    return check


def _opposite_rim_first(p):
    """The rim's four handles with the two edges running along x first - two edges sharing no
    vertex, so the list as handed over does not chain end to end."""
    ms = p["matches"]
    along_x = [m["handle"] for m in ms if abs((m.get("direction") or [0.0])[0]) > 0.5]
    if len(along_x) != 2:
        raise ValueError(f"expected 2 of the {len(ms)} rim edges along x, read {len(along_x)}")
    return along_x + [m["handle"] for m in ms if m["handle"] not in along_x]


def _domed_patch(flat_mm2):
    """find_geometry on the tangent patch body: its faces read, none is planar, and their area
    sum is over the flat patch the opening would take by 1 % - the patch that ignores its
    continuity is one flat face, the group-tangent one a dome."""
    def check(p):
        faces = [m for m in p.get("matches") or [] if str(m.get("kind")).endswith("face")]
        areas = [m.get("area") for m in faces]
        good = (bool(faces) and all(m.get("kind") != "planar_face" for m in faces)
                and all(_num(a) for a in areas) and sum(areas) > 1.01 * flat_mm2)
        return _measured(f"a domed patch over the flat {flat_mm2} mm2",
                         {"kinds": [m.get("kind") for m in faces], "areas": areas}, good)
    return check


def _seams_read(label, test, jumps=lambda js: True):
    """model_measure_continuity: every edge's normal angle passes `test`, the jump list `jumps`."""
    def check(p):
        rows = p.get("edges") or []
        got = {"angles": [r.get("max_normal_angle_deg") for r in rows],
               "modes": [r.get("mode") for r in rows],
               "jumps": [r.get("max_curvature_jump") for r in rows]}
        return _measured(label, got, bool(rows) and all(_num(a) and test(a)
                                                        for a in got["angles"])
                         and jumps(got["jumps"]))
    return check


def _g2_start_g1_end(js):
    """[smooth rim, tangent rim] jumps: the tangent seam's is non-zero and 10x the smooth one's."""
    return len(js) == 2 and all(_num(j) for j in js) and js[1] > 0 and js[0] * 10 < js[1]


def _edges_of(p):
    """find_geometry: the handles of every edge match - the faces the same query lists left out."""
    return [m["handle"] for m in p.get("matches") or [] if "edge" in str(m.get("kind"))]


def _blend_lofted(start, end):
    """model_loft between two rims: ends read back as asked, edge sections, a weight per end."""
    def check(p):
        params = p.get("model_parameters") or {}
        weighted = [side for side, cond in (("start", start), ("end", end)) if cond != "free"]
        got = {"ends": p.get("ends"), "kinds": p.get("section_kinds"), "weights": params,
               "is_solid": p.get("is_solid")}
        return _measured(f"a {start}-to-{end} edge loft", got,
                         p.get("ends") == {"start": start, "end": end}
                         and p.get("section_kinds") == ["edge", "edge"]
                         and set(params) == {f"{s}_weight" for s in weighted}
                         and p.get("is_solid") is False)
    return check


def _blend_lofts_healthy(count):
    """design_get(include=['timeline']): the Blend component's `count` loft rows all read healthy."""
    def check(p):
        rows = [r for r in (p.get("timeline") or {}).get("timeline") or []
                if r.get("component") == "Blend" and r.get("type") == "LoftFeature"]
        got = {r.get("name"): r.get("health", "healthy") for r in rows}
        return _measured(f"{count} healthy Blend loft(s)", got,
                         len(rows) == count and all(h == "healthy" for h in got.values()))
    return check


def _lofted_as(ends, kinds, params, **more):
    """model_loft: the ends, section kinds and parameter names read off the feature, and `more`."""
    def check(p):
        got = {"ends": p.get("ends"), "kinds": p.get("section_kinds"),
               "params": sorted(p.get("model_parameters") or {}),
               **{k: p.get(k) for k in more}}
        return _measured(f"a {kinds} loft ending {ends}", got,
                         got["ends"] == ends and got["kinds"] == kinds
                         and got["params"] == sorted(params) and "unverified" not in p
                         and all(got[k] == v for k, v in more.items()))
    return check


def _seam_jump_past(key, factor):
    """model_measure_continuity: a seam under 0.01 deg, its curvature jump past factor x the twin's."""
    def check(p):
        row = (p.get("edges") or [{}])[0]
        got = {"angle": row.get("max_normal_angle_deg"), "jump": row.get("max_curvature_jump"),
               "twin_jump": _RECALL.get(key)}
        return _measured(f"a seam bending over {factor}x its twin's", got,
                         _num(got["angle"]) and got["angle"] < 0.01 and _num(got["jump"])
                         and _num(got["twin_jump"]) and got["jump"] > factor * got["twin_jump"])
    return check


def _box_x(lo, hi):
    """model_inspect: the body's x extent lies in [lo, hi] mm."""
    return lambda p: _measured(f"an x extent in [{lo}, {hi}] mm", p.get("x"),
                               _num(p.get("x")) and lo <= p["x"] <= hi)


def _timeline_rows_suppressed(*keys):
    """design_get(include=['timeline']): the rows the recalled Cascade features name all read
    is_suppressed true - read off the timeline, not off the suppress reply."""
    def check(p):
        rows = (p.get("timeline") or {}).get("timeline") or []
        want = [_RECALL[k] for k in keys]
        got = {r.get("name"): r.get("is_suppressed") for r in rows
               if r.get("component") == "Cascade" and r.get("name") in want}
        return _measured("cascade rows suppressed on the timeline", got,
                         all(got.get(n) is True for n in want))
    return check


def _also_named(key, *keys):
    """The suppress/unsuppress reply names every recalled Cascade dependent under `key`."""
    def check(p):
        also = p.get(key)
        want = [_RECALL[k] for k in keys]
        return _measured(f"{key} names the dependents", {key: also, "want": want},
                         isinstance(also, list) and all(n in also for n in want))
    return check


def _same_volume(key):
    """model_inspect: the volume reads what it read before the suppress/unsuppress pair."""
    def check(p):
        got = (p.get("mass") or {}).get("volume")
        return _measured("volume restored", {"volume": got, "before": _RECALL.get(key)},
                         _num(got) and abs(got - _RECALL[key]) < 0.01)
    return check


# Pinned at the cameo's own sizes, not scaled from the 200 mm probes; measure_api's
# form-crease-fillet-two-sizes re-measures the fillet figure by raw-API script at both sizes.
_FORM_BOX_CM3 = 7.225184674         # the 3x3x3 box cage, 20 mm
_FORM_CREASE_CM3 = 7.465881190      # the same cage, its top rim creased
_FORM_FILLET_CM3 = -0.018444933     # the four creased edges filleted at 1 mm


def _near_rel(got, want, rel=1e-4):
    return _num(got) and abs(got - want) <= rel * abs(want)


def _inspected_mm3(label, want_cm3):
    """model_inspect in mm: the body's own volume within 1e-4 of the measured one."""
    def check(p):
        got = (p.get("mass") or {}).get("volume")
        return _measured(label, {"volume_mm3": got, "want_mm3": round(want_cm3 * 1000, 6)},
                         _near_rel(got, want_cm3 * 1000))
    return check


def _form_made(volume_cm3, sharp):
    """form_create: a solid six-face Form whose own read-back verified, at the measured volume, with
    `sharp` sharp edges read off its seams."""
    def check(p):
        facts = {k: p.get(k) for k in ("created", "is_solid", "brep_faces", "readback",
                                       "volume_cm3")}
        facts["sharp_edges"] = len(p.get("sharp_edges") or [])
        return _measured(f"a verified Form at {volume_cm3} cm3", facts,
                         p.get("created") is True and p.get("is_solid") is True
                         and p.get("brep_faces") == 6 and p.get("readback") == "exact"
                         and facts["sharp_edges"] == sharp
                         and _near_rel(p.get("volume_cm3"), volume_cm3))
    return check


def _form_row_added(p):
    """design_get after the create: the timeline is one row longer and that row is a FormFeature
    in FormDemo carrying the Form's name - read off the timeline, not off the create's reply."""
    tl = p.get("timeline") or {}
    name = _RECALL["form_box"].split("/", 1)[1]
    hits = [r for r in tl.get("timeline") or [] if r.get("name") == name
            and r.get("type") == "FormFeature" and r.get("component") == "FormDemo"]
    return _measured("one FormFeature row added", {"count": tl.get("count"),
                                                   "before": _RECALL["form_tl0"], "rows": hits},
                     tl.get("count") == _RECALL["form_tl0"] + 1 and len(hits) == 1)


def _form_cage_read(p):
    """form_get(include=['cage']): the census Fusion's own read-back gives - 54 quads, 56 points,
    closed, the eight valence-3 corners - and the stored record still matching it."""
    census = p.get("census") or {}
    got = {k: census.get(k) for k in ("faces", "vertices", "closed", "stars")}
    got["record_matches_cage"] = p.get("record_matches_cage")
    return _measured("the box Form's cage read back", got,
                     got["faces"] == 54 and got["vertices"] == 56 and got["closed"] is True
                     and got["stars"] == {"3": 8} and got["record_matches_cage"] is True
                     and isinstance(p.get("cage"), dict))


def _creased_rim_cage(ctx):
    """form_create args: the box's own cage moved 30 mm along x, its 12 top-rim edges creased -
    every cage edge whose two ends sit at the top and on one outer side."""
    cage = _ctx_get(ctx, "form_box_cage", "the box Form's cage")
    verts = cage["vertices"]
    top = max(v[2] for v in verts)
    sides = [(axis, pick(v[axis] for v in verts)) for axis in (0, 1) for pick in (min, max)]

    def at(v, axis, value):
        return abs(verts[v][axis] - value) < 1e-6
    rim = set()
    for f in cage["faces"]:
        for k in range(4):
            a, b = f[k], f[(k + 1) % 4]
            if at(a, 2, top) and at(b, 2, top) and any(at(a, ax, val) and at(b, ax, val)
                                                       for ax, val in sides):
                rim.add(tuple(sorted((a, b))))
    return {"cage": {"vertices": [[v[0] + 30.0, v[1], v[2]] for v in verts],
                     "faces": cage["faces"], "creases": [list(e) for e in sorted(rim)]},
            "name": "FormCrease", "component": "FormDemo:1"}


def _crease_made(p):
    """The creased Form's address, saved and recalled; its sharp-edge handles parked for the
    fillet that takes them."""
    _RECALL["form_crease_edges"] = [row["edge"] for row in p["sharp_edges"]]
    _RECALL["form_crease"] = p["form"]
    return p["form"]


def _forms_modified(p):
    """form_get: the filleted Form reads modified downstream and the untouched box does not."""
    rows = {r.get("form"): r.get("modified_downstream") for r in p.get("forms") or []}
    got = {"box": rows.get(_RECALL["form_box"]), "crease": rows.get(_RECALL["form_crease"])}
    return _measured("modified_downstream off the creation record", got,
                     got["crease"] is True and got["box"] is False)


def _named_exactly(key, recall_key):
    """The suppress/delete reply names exactly the recalled fillet under `key`."""
    def check(p):
        want = [_RECALL[recall_key]]
        return _measured(f"{key} names the fillet alone", {key: p.get(key), "want": want},
                         p.get(key) == want)
    return check


def _form_pair_suppressed(p):
    """design_get: the Form and its fillet both read suppressed on the timeline itself."""
    names = [_RECALL["form_crease"].split("/", 1)[1], _RECALL["form_fillet"]]
    got = {r.get("name"): r.get("is_suppressed")
           for r in (p.get("timeline") or {}).get("timeline") or []
           if r.get("component") == "FormDemo" and r.get("name") in names}
    return _measured("the Form and its fillet suppressed", got,
                     len(got) == 2 and all(v is True for v in got.values()))


def _form_count_is(key, delta):
    """design_get: the timeline count reads the recalled count plus `delta`."""
    def check(p):
        count = (p.get("timeline") or {}).get("count")
        return _measured(f"timeline count {delta:+d}", {"count": count, "before": _RECALL[key]},
                         _num(count) and count == _RECALL[key] + delta)
    return check


def _form_body_state(p):
    """The FormDemo body and aggregate physical-property signature."""
    mass = p.get("mass") or {}
    rows = mass.get("per_body") or []
    bodies = [{key: row.get(key) for key in ("body", "is_solid", "volume", "mass_kg", "lump_count")}
              for row in rows]
    aggregate = {key: mass.get(key) for key in ("volume", "area", "mass_kg")}
    readable = (mass.get("per_body_truncated") is False
                and bool(bodies)
                and all(isinstance(row["body"], str) and row["body"]
                        and row["is_solid"] is True and _num(row["volume"])
                        and _num(row["mass_kg"]) and type(row["lump_count"]) is int
                        for row in bodies)
                and all(_num(value) for value in aggregate.values()))
    return {"aggregate": aggregate, "bodies": bodies}, readable


def _form_body_state_read(p):
    """Capture FormDemo body geometry and mass before the tiny-Form rollback attempt."""
    state, readable = _form_body_state(p)
    if readable:
        _RECALL["form_body_state_before_tiny"] = state
    return _measured("FormDemo body geometry before the tiny Form", state, readable)


def _form_tiny_rollback_timeline(p):
    """design_get confirms the rejected tiny Form left the timeline exactly as captured."""
    timeline = p.get("timeline") or {}
    rows = timeline.get("timeline") or []
    before = _RECALL.get("form_timeline_before_tiny")
    now = {"count": timeline.get("count"), "marker_position": timeline.get("marker_position"),
           "rows": rows}
    complete = (isinstance(before, dict) and not timeline.get("truncated")
                and timeline.get("count") == len(rows) and timeline.get("returned") == len(rows)
                and now == before)
    return _measured("timeline history unchanged after the tiny Form", now, complete)


def _form_timeline_before_tiny(p):
    """Capture the complete FormDemo timeline before the tiny-Form rollback attempt."""
    timeline = p.get("timeline") or {}
    rows = timeline.get("timeline") or []
    state = {"count": timeline.get("count"), "marker_position": timeline.get("marker_position"),
             "rows": rows}
    complete = (not timeline.get("truncated") and timeline.get("count") == len(rows)
                and timeline.get("returned") == len(rows)
                and timeline.get("marker_position") == timeline.get("count"))
    if complete:
        _RECALL["form_timeline_before_tiny"] = state
    return _measured("complete timeline before the tiny Form", state, complete)


def _form_body_state_unchanged(p):
    """model_inspect confirms the rejected tiny Form left FormDemo geometry unchanged."""
    state, readable = _form_body_state(p)
    before = _RECALL.get("form_body_state_before_tiny")
    same = (readable and isinstance(before, dict)
            and state["bodies"] == before["bodies"]
            and all(_near_rel(state["aggregate"][key], before["aggregate"][key], 1e-9)
                    for key in state["aggregate"]))
    return _measured("FormDemo geometry after the tiny Form rollback", state, same)


def _form_box_bounds_read(p):
    """Capture the existing FormBox's independently measured bounding box."""
    bounds = {key: p.get(key) for key in ("min_point", "max_point")}
    good = all(isinstance(bounds[key], dict)
               and all(_num(bounds[key].get(axis)) for axis in "xyz") for key in bounds)
    if good:
        _RECALL["form_box_bounds_before_tiny"] = bounds
    return _measured("FormBox bounds before the tiny Form", bounds, good)


def _form_box_bounds_unchanged(p):
    """model_inspect confirms the existing FormBox bounds did not change."""
    bounds = {key: p.get(key) for key in ("min_point", "max_point")}
    before = _RECALL.get("form_box_bounds_before_tiny")
    same = (isinstance(before, dict)
            and all(isinstance(bounds[key], dict)
                    and all(_num(bounds[key].get(axis))
                            and _near_rel(bounds[key][axis], before[key][axis], 1e-9)
                            for axis in "xyz") for key in bounds))
    return _measured("FormBox bounds after the tiny Form rollback", bounds, same)


def _crease_handles_found(p):
    """find_geometry on the creased Form: every sharp-edge handle form_create returned is one of its
    own edge handles - the same occurrence proxy at the same world point."""
    def key(h):
        return str(h).split(";rv=")[0]
    got = {key(h) for h in _edges_of(p)}
    want = [key(h) for h in _RECALL["form_crease_edges"]]
    return _measured("the crease handles are find_geometry's", {"want": want, "found": sorted(got)},
                     len(want) == 4 and all(h in got for h in want))


def _form_name(key):
    """The Form name of a recalled '<component>/<name>' label."""
    label = _RECALL[key] if isinstance(_RECALL[key], str) else _RECALL[key]["form"]
    return label.split("/", 1)[1]


def _cyl_made(p):
    """form_create behind the marker: a solid six-face capped cylinder, read back exactly, with no
    sharp edge, naming the rolled-back box Form as the item after it."""
    facts = {k: p.get(k) for k in ("created", "is_solid", "brep_faces", "readback", "volume_cm3",
                                   "inserted_before", "timeline_index")}
    facts["sharp_edges"] = p.get("sharp_edges")
    return _measured("a capped cylinder Form before the box", facts,
                     p.get("created") is True and p.get("is_solid") is True
                     and p.get("brep_faces") == 6 and p.get("readback") == "exact"
                     and p.get("sharp_edges") == [] and _num(p.get("volume_cm3"))
                     and p.get("inserted_before") == _form_name("form_box"))


def _cyl_before_box(p):
    """design_get: the cylinder Form's row is followed by the box Form's - the order form_create's
    inserted_before named, read off the timeline."""
    rows = {r.get("index"): r for r in (p.get("timeline") or {}).get("timeline") or []}
    at = [i for i, r in rows.items() if r.get("name") == _form_name("form_cyl")
          and r.get("component") == "FormDemo" and r.get("type") == "FormFeature"]
    after = rows.get(at[0] + 1, {}).get("name") if len(at) == 1 else None
    return _measured("the box Form follows the cylinder", {"cylinder_at": at, "next": after},
                     after == _RECALL["form_cyl"]["inserted_before"])


def _cyl_inspected(p):
    """model_inspect: the cylinder's own volume is form_create's, inside its 20 x 20 x 40 mm cage."""
    got = {"volume_mm3": (p.get("mass") or {}).get("volume"), "extent": [p.get(a) for a in "xyz"]}
    want = _RECALL["form_cyl"]["volume_cm3"] * 1000
    return _measured(f"the cylinder at {want} mm3", got,
                     _near_rel(got["volume_mm3"], want)
                     and all(_num(e) and 0 < e <= c + 1e-3
                             for e, c in zip(got["extent"], (20, 20, 40))))


def _group_collapsed(name):
    """design_get: the named timeline group reads collapsed with its two Forms in it."""
    def check(p):
        rows = [r for r in (p.get("timeline") or {}).get("timeline") or []
                if r.get("name") == name and r.get("is_group") is True]
        got = [(r.get("is_collapsed"), r.get("member_count")) for r in rows]
        return _measured(f"group {name} collapsed", got, got == [(True, 2)])
    return check


def _cyl_cage_read(p):
    """form_get(include=['cage']) on the grouped cylinder: its own 40-quad, 42-point cage."""
    census = p.get("census") or {}
    got = {k: census.get(k) for k in ("faces", "vertices", "closed", "stars")}
    got["record_matches_cage"] = p.get("record_matches_cage")
    return _measured("the grouped cylinder's cage read back", got,
                     got["faces"] == 40 and got["vertices"] == 42 and got["closed"] is True
                     and got["stars"] == {"3": 8} and got["record_matches_cage"] is True)


def _tube_made(p):
    """form_create on an uncapped cylinder: an open surface Form read back exactly, its area
    published in place of a volume, no seam read sharp or unread."""
    facts = {k: p.get(k) for k in ("created", "is_solid", "readback", "area_cm2", "volume_cm3",
                                   "seams_unread")}
    facts["sharp_edges"] = p.get("sharp_edges")
    return _measured("an open tube Form", facts,
                     p.get("created") is True and p.get("is_solid") is False
                     and p.get("readback") == "exact" and _num(p.get("area_cm2"))
                     and "volume_cm3" not in p and p.get("sharp_edges") == [])


def _tube_area(p):
    """find_geometry on the tube: its faces' areas sum to the area form_create published."""
    areas = [m.get("area") for m in p.get("matches") or [] if str(m.get("kind")).endswith("face")]
    want = _RECALL["form_tube"]["area_cm2"] * 100
    return _measured(f"the tube's faces at {want} mm2", {"areas": areas},
                     bool(areas) and all(_num(a) for a in areas) and _near_rel(sum(areas), want))


def _form_bodies_solid(p):
    """model_inspect per_body on FormDemo: the cylinder reads solid and the tube open."""
    rows = {r.get("body"): r.get("is_solid") for r in (p.get("mass") or {}).get("per_body") or []}
    got = {k: rows.get(k) for k in ("FormCyl", "FormTube")}
    return _measured("the cylinder solid and the tube open", got,
                     got == {"FormCyl": True, "FormTube": False})


def _tube_raised(p):
    """model_inspect: the tube's lowest point sits 10 mm above where it was before the move."""
    z = (p.get("min_point") or {}).get("z")
    return _measured("the tube raised 10 mm", {"z": z, "before": _RECALL["form_tube_z"]},
                     _num(z) and abs(z - (_RECALL["form_tube_z"] + 10.0)) < 1e-3)


def _moved_form_modified(p):
    """form_get: the moved tube reads modified downstream; the cylinder and the box do not."""
    rows = {r.get("form"): r.get("modified_downstream") for r in p.get("forms") or []}
    got = {k: rows.get(_RECALL[k] if isinstance(_RECALL[k], str) else _RECALL[k]["form"])
           for k in ("form_tube", "form_cyl", "form_box")}
    return _measured("modified_downstream after a move", got,
                     got == {"form_tube": True, "form_cyl": False, "form_box": False})


def _cascade_counted(p):
    """design_get after the delete: what the reply named, plus its unnamed count, is exactly what
    left the timeline besides the target - both counts read off the timeline itself."""
    reply = _RECALL["cascade_delete"]
    also = reply.get("also_deleted")
    before, after = _RECALL["cascade_count"], (p.get("timeline") or {}).get("count")
    named = (reply.get("also_deleted_count", len(also)) + reply.get("also_deleted_unnamed", 0)
             if isinstance(also, list) else None)
    return _measured("the delete names every item that left with it",
                     {"also_deleted": also, "unnamed": reply.get("also_deleted_unnamed"),
                      "count_before": before, "count_after": after},
                     named is not None and _num(after) and named == before - after - 1)


def _cascade_group_collapsed(p):
    """design_get(include=['timeline']): one CascadeG row, collapsed, standing for 2 members that
    are not listed beside it - the state the census caveat reports on."""
    rows = (p.get("timeline") or {}).get("timeline") or []
    group = [r for r in rows if r.get("name") == "CascadeG"]
    members = [r.get("name") for r in rows if r.get("component") == "Cascade"
               and r.get("name") in (_RECALL["cascade_extrude"], _RECALL["cascade_shell"])]
    return _measured("CascadeG reads collapsed over 2 unlisted members",
                     {"group_rows": group, "members_listed": members},
                     len(group) == 1 and group[0].get("is_collapsed") is True
                     and group[0].get("member_count") == 2 and not members)


def _caveat_names_groups(n):
    """The suppress reply's census_caveat counts `n` collapsed group(s); also_suppressed rides along."""
    def check(p):
        caveat = p.get("census_caveat")
        return _measured(f"census_caveat names {n} group(s)",
                         {"census_caveat": caveat, "also_suppressed": p.get("also_suppressed")},
                         isinstance(caveat, str)
                         and caveat.startswith(f"{n} collapsed timeline group(s)"))
    return check


def _tiny_surface_history(after=False):
    """Require the tiny sheet's one retained feature/body and unchanged prior tree/history."""
    def check(p):
        state = _retire_design_state(p)
        before = _RECALL.get("tiny_surface_design")
        valid = state is not None
        if valid:
            tree, timeline = state["tree"], state["timeline"]
            valid = (tree.get("child_count") == 3 and timeline["count"] == (12 if after else 11)
                     and timeline.get("summary") == {"states": {"healthy": timeline["count"]}, "exceptions": []}
                     and timeline.get("groups") == {})
        if valid and after:
            reduced = copy.deepcopy(tree)
            owners = [n for n in reduced["children"] if n.get("component") == "K2Surface"]
            added = [b for n in owners for b in n["bodies"] if b.get("name") == "Body2"]
            valid = (before is not None and len(owners) == len(added) == 1
                     and added[0].get("is_solid") is False and added[0].get("visible") is True
                     and bool(added[0].get("handle"))
                     and timeline["timeline"][:-1] == before["timeline"]["timeline"]
                     and timeline["timeline"][-1] == {"index": 11, "name": "Extrude2",
                                                    "type": "ExtrudeFeature", "component": "K2Surface"})
            if valid:
                owners[0]["bodies"].remove(added[0])
                owners[0]["body_count"] -= 1
                valid = reduced == before["tree"]
        if valid and not after:
            _RECALL["tiny_surface_design"] = state
        return _measured("one retained tiny-sheet feature/body with prior controls unchanged", state, valid)
    return check


def _tiny_surface_bounds(p, kind="body"):
    """Return complete world-axis bounds without interpreting rounded surface area."""
    values = [p.get(axis) for axis in "xyz"] + [
        (p.get(side) or {}).get(axis) for side in ("min_point", "max_point") for axis in "xyz"]
    if (p.get("units") != "mm" or p.get("frame") != "world axes (axis-aligned)"
            or p.get("kind") != kind or not all(_num(v) for v in values)):
        return None
    return values


def _tiny_surface_face(p):
    """Return one independently acquired surface face's disclosed geometry."""
    rows = p.get("matches") or []
    if p.get("units") != "mm" or p.get("match_count") != 1 or p.get("returned") != 1 or len(rows) != 1:
        return None
    row = rows[0]
    if (row.get("kind") != "planar_face" or not row.get("handle") or not _num(row.get("area"))
            or not all(isinstance(row.get(k), list) and len(row[k]) == 3 and all(_num(v) for v in row[k])
                       for k in ("position", "normal")) or not isinstance(row.get("frame"), dict)):
        return None
    return {k: row[k] for k in ("kind", "area", "position", "normal", "frame")}


def _cowl_wall_material(p):
    """Require the returned wall's positive volume and one solid lump beside its source sheet."""
    mass = p.get("mass") or {}
    rows = mass.get("per_body") or []
    solid = [r for r in rows if r.get("is_solid") is True]
    valid = (mass.get("units") == "mm" and mass.get("per_body_count") == len(rows) == 2
             and mass.get("per_body_truncated") is False and len(solid) == 1
             and sum(r.get("is_solid") is False for r in rows) == 1
             and solid[0].get("body") == _RECALL.get("cowl_wall")
             and solid[0].get("lump_count") == 1
             and _num(solid[0].get("volume")) and math.isfinite(solid[0]["volume"])
             and solid[0]["volume"] > 0
             and _num(mass.get("volume")) and math.isfinite(mass["volume"]) and mass["volume"] > 0)
    return _measured("single-face thicken remedy leaves one solid lump with positive volume", mass, valid)


def _symmetric_cowl_rows():
    """A symmetric 89.4 deg revolve spans 178.8 deg; its two faces refuse one thicken, one face does not."""
    cowl = [[87, -66], [85, -73], [76, -85], [66, -94], [57, -99], [54, -99]]
    return [
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
        ("model_create_component", {"name": "SRevCowl", "activate": True, "x": 1600}, _made_component, None),
        ("sketch_create", {"plane": "xy", "name": "SRevCowlS"}, "ok", None),
        ("sketch_add_geometry", {"sketch_name": "SRevCowlS", "geometry": [
            {"kind": "cv_spline", "points": cowl, "degree": 3}]}, "ok", None),
        # The area equals the one-sided 178.8 deg revolve of this spline (110.364137 cm2, measured).
        ("surface_revolve", {"sketch_name": "SRevCowlS", "axis": "y", "angle_deg": 89.4, "symmetric": True},
         lambda p: _measured("a symmetric angle is read back per side with its 2x total",
                             {k: p.get(k) for k in ("angle_deg", "total_angle_deg", "symmetric", "area_added_cm2")},
                             p.get("angle_deg") == 89.4 and p.get("total_angle_deg") == 178.8
                             and p.get("symmetric") is True and p.get("is_solid") is False
                             and _near(p.get("area_added_cm2"), 110.364137, .001)), None),
        ("find_geometry", {"target": "SRevCowl", "kind": "nurbs_face", "units": "mm", "max_results": 10},
         lambda p: p.get("match_count") == p.get("returned") == 2
         and all(_near(m.get("area"), 5518.207, .01) for m in p["matches"]), _fgn("cowl_faces")),
        ("surface_thicken", lambda c: {"faces": _ctx_get(c, "cowl_faces", "both cowl halves"), "thickness": -2.5},
         _refused("ASM_INCONSISTENT_ORIENTATION", "thicken each face in its own call with chaining=false"), None),
        ("surface_thicken", lambda c: {"faces": _ctx_get(c, "cowl_faces", "both cowl halves")[:1],
                                       "thickness": -2.5, "chaining": False},
         lambda p: p.get("thickened") is True and p.get("is_solid") is True
         and len(p.get("result_bodies") or []) == 1,
         ("cowl_wall", _recall("cowl_wall", lambda p: p["result_bodies"][0]))),
        ("model_inspect", {"target": "SRevCowl:1", "include": ["mass"], "per_body": True, "units": "mm"},
         _cowl_wall_material, None),
    ]


_TINY_ADDRESS = "K2Surface/Extrude2@11"


def _tiny_surface_rows():
    """Demonstrate a small retained sheet after an area-threshold refusal using public reads."""
    rows = [("doc_get", {}, _home_document, ("tiny_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "tiny_home", "story")},
             _new_document, ("tiny_doc", lambda p: p["document_handle"]))]
    def write(tool, args, expect="ok"):
        rows.append((tool, lambda c, args=args: dict(args, expect_document=_ctx_get(c, "tiny_doc", "owned scratch")), expect, None))
    write("model_create_component", {"name": "K2Witness", "activate": True, "x": 100}, _made_component)
    write("sketch_create", {"plane": "xy", "name": "K2Cube"})
    write("sketch_add_geometry", {"sketch_name": "K2Cube", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]})
    write("model_extrude", {"sketch_name": "K2Cube", "component": "K2Witness", "distance": 10}, _extruded)
    # A sibling component whose second extrude is also 'Extrude2': the bare name is then ambiguous.
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "K2Sib", "activate": True, "x": 200}, _made_component)
    write("sketch_create", {"plane": "xy", "name": "K2SibS"})
    write("sketch_add_geometry", {"sketch_name": "K2SibS", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 10},
        {"kind": "rectangle", "x1": 20, "y1": 0, "x2": 30, "y2": 10}]})
    for index, name in ((0, "Extrude1"), (1, "Extrude2")):
        write("model_extrude", {"sketch_name": "K2SibS", "component": "K2Sib", "profile_index": index,
                                "distance": 5, "operation": "new"},
              lambda p, name=name: _extruded(p) and p.get("feature") == name)
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "K2Surface", "activate": True}, _made_component)
    write("sketch_create", {"plane": "xy", "name": "K2Normal"})
    write("sketch_add_geometry", {"sketch_name": "K2Normal", "geometry": [
        {"kind": "line", "x1": 0, "y1": 0, "x2": 20, "y2": 0}]})
    write("surface_extrude", {"sketch_name": "K2Normal", "component": "K2Surface", "distance": 10},
          lambda p: p.get("created") is True and p.get("is_solid") is False and p.get("result_bodies") == ["Body1"])
    write("sketch_create", {"plane": "xy", "name": "K2Tiny"})
    write("sketch_add_geometry", {"sketch_name": "K2Tiny", "geometry": [
        {"kind": "line", "x1": 40, "y1": 0, "x2": 40.01, "y2": 0}]})
    for after in (False, True):
        if after:
            write("surface_extrude", {"sketch_name": "K2Tiny", "component": "K2Surface", "distance": 0.005,
                                       "units": "mm", "operation": "new"},
                  _refused('"postcondition": "surface_area_added"', '"handler_reported_unverified_result"',
                           '"feature": "Extrude2"', '"result_bodies"', '"Body2"', '"source": "K2Tiny"',
                           '"features_verified": 1', '"area_change_cm2"', '"area_increase_threshold_cm2": 1e-06',
                           "not confirmation", "Re-read with model_inspect",
                           "Its result bodies: 'Body2'.",
                           f"'{_TINY_ADDRESS}' remains in the timeline; remove it with "
                           f"design_delete_feature(feature='{_TINY_ADDRESS}')."))
        rows.append(("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                                     "tree_handles": True, "max_results": 200}, _tiny_surface_history(after), None))
        rows.append(("model_inspect", {"target": "K2Witness:1", "include": ["default", "mass"], "per_body": True,
                                       "units": "mm", "accuracy": "very_high"},
                     _retire_compare("tiny_cube", lambda p: _retire_material_state(p)
                                     if all(p.get(a) == 10 for a in "xyz")
                                     and (p.get("mass") or {}).get("volume") == 1000 else None, after), None))
        rows.append(("model_inspect", {"target": "K2Surface:1:Body1", "units": "mm"},
                     _retire_compare("tiny_normal_bounds", lambda p: (v if (v := _tiny_surface_bounds(p))
                                     == [20.0, 0.0, 10.0, 0.0, 0.0, 0.0, 20.0, 0.0, 10.0] else None), after), None))
        rows.append(("find_geometry", {"target": "K2Surface:1:Body1", "kind": "planar_face", "units": "mm",
                                       "max_results": 100}, _retire_compare("tiny_normal_face", lambda p:
                                       (v if (v := _tiny_surface_face(p)) is not None and v["area"] == 200 else None), after), None))
        for owner, name in (("K2Witness", "K2Cube"), ("K2Surface", "K2Normal"), ("K2Surface", "K2Tiny")):
            rows.append(("sketch_get", {"component": owner, "sketch_name": name, "include_entities": True,
                                        "max_results": 200, "units": "mm"},
                         _retire_compare("tiny_" + name, _retire_sketch_state, after), None))
    rows.extend([
        ("find_geometry", {"target": "K2Surface:1:Body2", "kind": "planar_face", "units": "mm", "max_results": 100},
         lambda p: _measured("tiny sheet has one readable face despite rounded area",
                              _tiny_surface_face(p), _tiny_surface_face(p) is not None
                              and _tiny_surface_face(p)["position"] == [40.005, 0.0, 0.0025]), _fg("tiny_face")),
        ("model_inspect", lambda c: {"target": _ctx_get(c, "tiny_face", "retained sheet face"), "units": "mm"},
         lambda p: _measured("retained sheet independently spans 0.01 by 0.005 mm",
                              _tiny_surface_bounds(p, "face"), _tiny_surface_bounds(p, "face")
                              == [0.01, 0.0, 0.005, 40.0, 0.0, 0.0, 40.01, 0.0, 0.005]), None),
        # The bare name is refused beside the sibling's namesake; the reply's own address is not.
        ("design_delete_feature", lambda c: {"feature": "Extrude2",
                                             "expect_document": _ctx_get(c, "tiny_doc", "owned scratch")},
         _refused("matches 2 timeline objects", "K2Sib/Extrude2@6", _TINY_ADDRESS), None),
        ("design_delete_feature", lambda c: {"feature": _TINY_ADDRESS,
                                             "expect_document": _ctx_get(c, "tiny_doc", "owned scratch")},
         lambda p: _measured("the reply's address removes exactly the retained tiny sheet",
                             {k: p.get(k) for k in ("deleted", "feature", "index", "entity_type")},
                             p.get("deleted") is True and p.get("feature") == "Extrude2"
                             and p.get("index") == 11 and p.get("entity_type") == "ExtrudeFeature"), None),
        ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                        "max_results": 200},
         lambda p: _measured("tree and history read as before the refused write",
                             _retire_design_state(p),
                             _retire_design_state(p) is not None
                             and _retire_design_state(p) == _RECALL.get("tiny_surface_design")), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, "tiny_home", "story"),
                                     "expect_document": _ctx_get(c, "tiny_doc", "owned scratch")}, "ok", None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "tiny_doc", "owned scratch"), "save_changes": False,
                                  "expect_document": _ctx_get(c, "tiny_home", "story")}, _document_closed, None),
    ])
    return rows


# --- the CAMEO acts: surface-prep, mesh, and CAM families ride scratch fixtures in the SAME doc -
# These families have no natural home on the mechanism itself, so the spec places them as cameos.

# ACT 5: MACHINING PREP - surfaces, sheet ops, split/stitch/arrange/base-feature, holder read.
_MACHINING = [
    *_tiny_surface_rows(),
    # the surface/split/stitch cameos live on a GRID (y=200 row, plus a z-lifted revolve) so each
    # builds in clear space a viewer can see, never on top of the part or another cameo.
    ("model_create_component", {"name": "SRev", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xz", "name": "SRevS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 10, "y1": 60,
                                           "x2": 10, "y2": 90}],
                             "sketch_name": "SRevS"}, "ok", None),
    # 'is_solid' is isSolid read off the created body: a profile that closed into a SOLID, and a
    # body whose flag would not read at all (named in 'unverified'), both return ok.
    ("surface_revolve", {"sketch_name": "SRevS", "axis": "z", "angle_deg": 360},
     lambda p: p["is_solid"] is False and bool(p["result_bodies"]) and "unverified" not in p, None),
    # ONE open fitted spline beside a construction line on the axis: the construction line stays
    # out of the profile, so the spline alone revolves into a sheet whose area is measured. The
    # bench sits out at x=1360 through its component placement.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "SRevSpline", "activate": True, "x": 1360},
     _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "SRevSplineS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 0, "y1": 0, "x2": 0, "y2": 30,
                                           "is_construction": True},
                                          {"kind": "spline", "points": [[6, 0], [12, 15], [6, 30]]}],
                             "sketch_name": "SRevSplineS"}, "ok", None),
    ("surface_revolve", {"sketch_name": "SRevSplineS", "axis": "y", "angle_deg": 360},
     lambda p: _measured("an open spline revolves alone into a measured sheet",
                         {"is_solid": p.get("is_solid"), "area_added_cm2": p.get("area_added_cm2")},
                         p.get("is_solid") is False and _num(p.get("area_added_cm2"))
                         and p["area_added_cm2"] > 0), None),
    *_symmetric_cowl_rows(),
    ("design_activate_component", {"occurrence": "SRev:1"}, "ok", None),
    # a CLOSED revolved sphere surface encloses one cell; surface_fill must seal it to a SOLID at
    # the enclosed volume (r=6mm -> 904.78 mm3) MEASURED off the result, never predicted.
    ("model_create_component", {"name": "FillDemo", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xz", "name": "FillProf"}, "ok", None),
    # the arc's endpoints must sit ON the revolve axis (x=0) or the revolved surface is an open
    # tube enclosing nothing, and surface_fill refuses it (live-measured).
    ("sketch_add_geometry", {"geometry": [{"kind": "arc", "cx": 0, "cy": 150, "x1": 0, "y1": 156,
                                           "sweep_deg": 180}],
                             "sketch_name": "FillProf"}, "ok", None),
    ("surface_revolve", {"sketch_name": "FillProf", "axis": "z", "angle_deg": 360}, "ok", None),
    # the closed sphere sheet encloses exactly ONE cell, so index 1 is one past the end: refused
    # NAMING the index and the range that exists, never clamped onto a neighbouring cell. The parse
    # happens before any cell is kept, so the sheet is untouched and the fill below is still its
    # first feature.
    ("surface_fill", {"tools": ["FillDemo"], "operation": "new", "cells": [1]},
     _refused("does not exist", "0..0"), None),
    ("surface_fill", {"tools": ["FillDemo"], "operation": "new"},
     lambda p: p.get("filled") is True and p.get("all_solid") is True
     and abs(p.get("result_volume", 0) - 904.78) < 10
     and p.get("tools_unclassified", 0) == 0, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("find_geometry", {"target": "SRev", "kind": "cylinder_face", "max_results": 1}, "ok", _fg("srev_face")),
    ("surface_thicken", lambda c: {"faces": [_ctx_get(c, "srev_face", "surface face")], "thickness": 2}, "ok", None),
    ("model_create_component", {"name": "Surf", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "SurfS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 200, "y1": 200,
                                           "x2": 240, "y2": 230}],
                             "sketch_name": "SurfS"}, "ok", None),
    ("surface_extrude", {"sketch_name": "SurfS", "distance": 15}, "ok", None),
    ("find_geometry", {"target": "Surf", "kind": "planar_face", "max_results": 1}, "ok", _fg("surf_face")),
    # 'faces_offset' is counted off the CREATED surface, so it disagrees with the one face requested
    # when chaining widened the selection - and reads null (in 'unverified') when nothing was read.
    ("surface_offset", lambda c: {"faces": [_ctx_get(c, "surf_face", "surface face")], "distance": 3},
     lambda p: (p["faces_offset"] == p["faces_requested"] == 1 and bool(p["result_bodies"])
                and "unverified" not in p), None),
    ("surface_offset", lambda c: {"faces": [_ctx_get(c, "surf_face", "surface face")], "distance": 0}, "ok", None),
    # THREE edges of ONE body, not one: edge.body hands back a fresh proxy per read, so a
    # body-set walk keyed on object identity counts this single body three times and refuses a
    # legal call as multi-body. A single-edge beat cannot catch that - one edge never disagrees
    # with itself. nearest_to pins the pick to the TOP rim (z=15): three of that rim's four edges
    # connect at endpoints into one open chain, while an arbitrary pick mixes top and bottom rims
    # into a disconnected set the platform rejects as an invalid extend input.
    ("find_geometry", {"target": "Surf", "kind": "line_edge", "nearest_to": [220, 215, 15], "max_results": 3}, "ok", _fgn("surf_edges")),
    ("surface_extend", lambda c: {"edges": _ctx_get(c, "surf_edges", "surface edges"), "distance": 2},
     # no extend_alignment given: the key is ABSENT from the payload, so nothing was written and
     # the API's own default stands - an echoed key here would be a claim about an unwritten value.
     lambda p: p.get("body_count", 1) == 1 and "extend_alignment" not in p, None),
    ("find_geometry", {"target": "Surf", "kind": "planar_face", "max_results": 1}, "ok", _fg("surf_body")),
    # the flip is invisible in every other read, so the row asserts the tool's own isParamReversed
    # read-back: 'reversed_confirmed' is false whenever the after-count does not match the flip.
    ("surface_reverse_normal", lambda c: {"bodies": [_ctx_get(c, "surf_body", "surface body")]},
     lambda p: p.get("reversed_confirmed") is True and p.get("faces_total", 0) > 0, None),
    # extend_alignment + thicken_type, on their own sheet so the read-backs never ride on edges an
    # earlier extend already moved. Both properties are written through set_verified, so a value the
    # platform drops comes back as an error rather than an echoed success. A rectangle extruded as a
    # surface gives a four-walled sheet, which is the convex corner set 'rounded' needs to mean
    # anything - a single flat face has no corner to round.
    ("model_create_component", {"name": "SAlign", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "SAlignS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 700, "y1": 200,
                                           "x2": 740, "y2": 230}],
                             "sketch_name": "SAlignS"}, "ok", None),
    ("surface_extrude", {"sketch_name": "SAlignS", "distance": 15}, "ok", None),
    ("find_geometry", {"target": "SAlign", "kind": "line_edge", "nearest_to": [720, 215, 15],
                       "max_results": 3}, "ok", _fgn("salign_edges")),
    ("surface_extend", lambda c: {"edges": _ctx_get(c, "salign_edges", "aligned sheet edges"),
                                  "distance": 2, "extend_alignment": "align_edges"},
     lambda p: p.get("extend_alignment") == "align_edges", None),
    ("find_geometry", {"target": "SAlign", "kind": "planar_face", "max_results": 1}, "ok",
     _fg("salign_face")),
    ("surface_thicken", lambda c: {"faces": [_ctx_get(c, "salign_face", "aligned sheet face")],
                                   "thickness": 1, "thicken_type": "rounded"},
     lambda p: p.get("thicken_type") == "rounded", None),
    # symmetric thicken: 'thickness' stays the PER-SIDE number asked for, and 'wall_total' - the
    # raw feature readback, published only when symmetric - is the wall that actually landed (2x).
    ("model_create_component", {"name": "ThkSym", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "ThkSymS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 760, "y1": 200,
                                           "x2": 790, "y2": 220}],
                             "sketch_name": "ThkSymS"}, "ok", None),
    ("surface_extrude", {"sketch_name": "ThkSymS", "distance": 15}, "ok", None),
    ("find_geometry", {"target": "ThkSym", "kind": "planar_face", "max_results": 1}, "ok",
     _fg("thksym_face")),
    ("surface_thicken", lambda c: {"faces": [_ctx_get(c, "thksym_face", "symmetric sheet face")],
                                   "thickness": 4, "symmetric": True},
     lambda p: _measured("symmetric thicken: wall_total is 2x the per-side thickness",
                         {"thickness": p.get("thickness"), "wall_total": p.get("wall_total")},
                         p.get("thickness") == 4.0 and p.get("wall_total") == 8.0), None),
    # back to the component that was active before this cameo, so the ones after it nest as before.
    ("design_activate_component", {"occurrence": "Surf:1"}, "ok", None),
    ("model_create_component", {"name": "SDel", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "SD1"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 300, "y1": 200,
                                           "x2": 320, "y2": 220}],
                             "sketch_name": "SD1"}, "ok", None),
    ("model_extrude", {"sketch_name": "SD1", "profile_index": 0, "distance": 10}, _extruded, None),
    ("find_geometry", {"target": "SDel", "kind": "planar_face", "nearest_to": [310, 210, 10], "max_results": 1}, "ok", _fg("sdel_top")),
    # one face off a six-faced box: 'faces_delta' is measured across the result bodies' own counts,
    # and a delete that RAISED the count or ate a whole body is published with a warning, not an error.
    ("surface_delete_face", lambda c: {"faces": [_ctx_get(c, "sdel_top", "top face")], "heal": False},
     lambda p: p["faces_delta"] == -1 and p["bodies_consumed"] == 0, None),
    ("find_geometry", {"target": "SDel", "kind": "line_edge", "nearest_to": [310, 210, 10], "max_results": 4}, "ok", _fgn("sdel_rim")),
    # read while the open box's rim is the only line edges near that point: a patch body's own
    # boundary edges sit on the rim and would tie them in the nearest_to sort.
    ("find_geometry", {"target": "SDel", "kind": "line_edge", "nearest_to": [310, 210, 10],
                       "max_results": 4}, _matched(4, "line_edge"),
     ("sdel_rim_scrambled", _opposite_rim_first)),
    ("surface_patch", lambda c: {"boundary": _ctx_get(c, "sdel_rim", "rim edges")}, "ok",
     ("sdel_flat_body", lambda p: "SDel:1:" + p["result_body"])),
    # a patch with operation 'new' leaves the opened body untouched, so the SAME rim carries the
    # option beats below. The tangent beat hands the rim over with its two opposite edges first, an
    # order that does not chain, and 'continuity' is the FEATURE's groupContinuity read back.
    ("surface_patch", lambda c: {"boundary": _ctx_get(c, "sdel_rim_scrambled",
                                                      "the rim, opposite edges first"),
                                 "continuity": "tangent"},
     lambda p: p.get("continuity") == "tangent" and "unverified" not in p,
     ("sdel_tangent_body", lambda p: "SDel:1:" + p["result_body"])),
    # the body itself, apart from the reply: a patch that ignores its continuity is ONE flat face
    # over the 20 x 20 mm opening, and a tangent one bulges into a dome with more area than that.
    ("find_geometry", lambda c: {"target": _ctx_get(c, "sdel_tangent_body", "the tangent patch")},
     _domed_patch(400.0), None),
    # the seam itself, read edge by edge between the walls and each patch: the tangent patch meets
    # them within half a degree, the connected one (a flat lid on vertical walls) far from it - so a
    # read that always answers 0 fails the second row.
    ("model_measure_continuity",
     lambda c: {"edges": _ctx_get(c, "sdel_rim", "rim edges"),
                "against": _ctx_get(c, "sdel_tangent_body", "the tangent patch")},
     _seams_read("the tangent patch meets the walls within 0.5 deg", lambda a: a < 0.5), None),
    ("model_measure_continuity",
     lambda c: {"edges": _ctx_get(c, "sdel_rim", "rim edges"),
                "against": _ctx_get(c, "sdel_flat_body", "the connected patch")},
     _seams_read("the connected patch creases the walls past 45 deg", lambda a: a > 45.0), None),
    # an interior RAIL the patch surface must pass through: a sheet standing in the opening, whose
    # top edge crosses it end to end with both ends landing on the rim. 'interior_rail_count' is the
    # count PatchFeatureInput.interiorRailsAndPoints reads back, not the number of handles passed.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "PatchRail", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "PatchRailS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 300, "y1": 210,
                                           "x2": 320, "y2": 210}],
                             "sketch_name": "PatchRailS"}, "ok", None),
    ("surface_extrude", {"sketch_name": "PatchRailS", "distance": 10}, "ok", None),
    ("find_geometry", {"target": "PatchRail", "kind": "line_edge", "nearest_to": [310, 210, 10],
                       "max_results": 1}, "ok", _fg("patch_rail")),
    ("design_activate_component", {"occurrence": "SDel:1"}, "ok", None),
    ("surface_patch", lambda c: {"boundary": _ctx_get(c, "sdel_rim", "rim edges"),
                                 "interior_rails": [_ctx_get(c, "patch_rail", "the interior rail")]},
     lambda p: p.get("interior_rail_count") == 1, None),
    # three of the four rim edges are no closed loop: refused by the vertex walk before Fusion
    # sees them, the timeline unchanged.
    ("design_get", {"include": ["timeline"], "max_results": 2000}, "ok",
     ("sdel_tl", _recall("sdel_tl", lambda p: p["timeline"]["count"]))),
    ("surface_patch", lambda c: {"boundary": _ctx_get(c, "sdel_rim", "rim edges")[:3]},
     _refused("'boundary'", "not one closed loop"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _form_count_is("sdel_tl", 0),
     None),
    # rails fit ONE patch surface, so pairing them with the multi-loop 'boundaries' is refused
    # BEFORE any patch runs - every loop would otherwise be handed the same rails.
    ("surface_patch", lambda c: {"boundaries": [_ctx_get(c, "sdel_rim", "rim edges")],
                                 "interior_rails": [_ctx_get(c, "patch_rail", "the interior rail")]},
     "refused", None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # THE CASCADE, in a scratch document of its own: a sketch, an extrude on it and a shell on the
    # extrude. Suppressing the sketch switches the other two off, and deleting the extrude takes
    # what depends on it - each reply names what else it changed, checked against separate reads.
    ("doc_get", {}, _document_read,
     ("cascade_home", _recall("cascade_home", lambda p: p["active"]["document_handle"]))),
    ("doc_new", lambda c: {"expect_document": _ctx_get(c, "cascade_home", "the sweep document")},
     _new_document, ("cascade_doc", _recall("cascade_doc", lambda p: p["document_handle"]))),
    ("model_create_component", {"name": "Cascade", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "CascadeS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 1100, "y1": 200,
                                           "x2": 1130, "y2": 230}],
                             "sketch_name": "CascadeS"}, "ok", None),
    ("model_extrude", {"sketch_name": "CascadeS", "profile_index": 0, "distance": 20}, _extruded,
     ("cascade_extrude", _recall("cascade_extrude", lambda p: p["feature"]))),
    ("find_geometry", {"target": "Cascade", "kind": "planar_face", "nearest_to": [1115, 215, 20],
                       "max_results": 1}, "ok", _fg("cascade_top")),
    ("model_shell", lambda c: {"body_name": "Cascade", "thickness": 2,
                               "remove_faces": [_ctx_get(c, "cascade_top", "the cascade top")]},
     _shelled, ("cascade_shell", _recall("cascade_shell", lambda p: p["feature"]))),
    ("model_inspect", {"target": "Cascade:1", "include": ["default", "mass"], "units": "mm"},
     lambda p: _num((p.get("mass") or {}).get("volume")),
     ("cascade_volume", _recall("cascade_volume", lambda p: p["mass"]["volume"]))),
    ("design_edit_timeline", {"action": "suppress", "feature": "CascadeS"},
     _also_named("also_suppressed", "cascade_extrude", "cascade_shell"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000},
     _timeline_rows_suppressed("cascade_extrude", "cascade_shell"), None),
    ("design_edit_timeline", {"action": "suppress", "feature": "CascadeS", "suppressed": False},
     _also_named("also_unsuppressed", "cascade_extrude", "cascade_shell"), None),
    ("model_inspect", {"target": "Cascade:1", "include": ["default", "mass"], "units": "mm"},
     _same_volume("cascade_volume"), None),
    # A collapsed group hides the extrude and shell from the suppress census: the reply says so in
    # census_caveat, and the group= listing shows the hidden members did switch off.
    ("design_edit_timeline",
     lambda c: {"action": "group", "name": "CascadeG",
                "feature": "Cascade/" + _ctx_get(c, "cascade_extrude", "the cascade extrude"),
                "end_feature": "Cascade/" + _ctx_get(c, "cascade_shell", "the cascade shell")},
     lambda p: p.get("grouped") is True and p.get("group") == "CascadeG", None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _cascade_group_collapsed, None),
    ("design_edit_timeline", {"action": "suppress", "feature": "CascadeS"},
     _caveat_names_groups(1), None),
    ("design_get", {"include": ["timeline"], "group": "CascadeG", "max_results": 2000},
     _timeline_rows_suppressed("cascade_extrude", "cascade_shell"), None),
    ("design_edit_timeline", {"action": "suppress", "feature": "CascadeS", "suppressed": False},
     lambda p: p.get("is_suppressed") is False, None),
    ("model_inspect", {"target": "Cascade:1", "include": ["default", "mass"], "units": "mm"},
     _same_volume("cascade_volume"), None),
    # a member of the collapsed group is one timeline item with it: a write naming the member is
    # refused naming the group and the ungroup call, and nothing is suppressed or deleted.
    ("design_edit_timeline",
     lambda c: {"action": "suppress",
                "feature": _ctx_get(c, "cascade_shell", "the cascade shell")},
     _refused("'CascadeG'", "design_edit_timeline(action='ungroup', feature='CascadeG')"), None),
    ("design_delete_feature",
     lambda c: {"feature": _ctx_get(c, "cascade_shell", "the cascade shell")},
     _refused("'CascadeG'", "design_edit_timeline(action='ungroup', feature='CascadeG')"), None),
    ("model_inspect", {"target": "Cascade:1", "include": ["default", "mass"], "units": "mm"},
     _same_volume("cascade_volume"), None),
    ("design_edit_timeline", {"action": "ungroup", "feature": "CascadeG"},
     lambda p: p.get("ungrouped") is True, None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, "ok",
     ("cascade_count", _recall("cascade_count", lambda p: p["timeline"]["count"]))),
    ("design_delete_feature",
     lambda c: {"feature": "Cascade/" + _ctx_get(c, "cascade_extrude", "the cascade extrude")},
     lambda p: p.get("deleted") is True and isinstance(p.get("also_deleted"), list),
     ("cascade_delete", _recall("cascade_delete", lambda p: p))),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _cascade_counted, None),
    ("doc_activate",
     lambda c: {"name": _ctx_get(c, "cascade_home", "the sweep document"),
                "expect_document": _ctx_get(c, "cascade_doc", "the cascade document")},
     _activated(), None),
    ("doc_close",
     lambda c: {"name": _ctx_get(c, "cascade_doc", "the cascade document"),
                "save_changes": False,
                "expect_document": _ctx_get(c, "cascade_home", "the sweep document")},
     _document_closed, None),
    # THE FORM: a T-spline box built from a cage, its cage read back and re-created with the top
    # rim creased, the four sharp edges that makes filleted, then the rebuild loop's suppress and
    # delete naming the fillet they take - each against a separate read.
    ("model_create_component", {"name": "FormDemo", "activate": True}, _made_component, None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, "ok",
     ("form_tl0", _recall("form_tl0", lambda p: p["timeline"]["count"]))),
    ("form_create", {"primitive": {"shape": "box", "size": [20, 20, 20], "spans": [3, 3, 3]},
                     "name": "FormBox", "component": "FormDemo:1", "origin": [1300, 200, 10]},
     _form_made(_FORM_BOX_CM3, 0), ("form_box", _recall("form_box", lambda p: p["form"]))),
    _watch("FormDemo:1"),
    ("model_inspect", {"target": "FormBox", "include": ["default", "mass"], "units": "mm"},
     _inspected_mm3("FormBox volume", _FORM_BOX_CM3), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _form_row_added, None),
    # the Form's faces are NURBS surfaces, which kind='nurbs_face' selects.
    ("find_geometry", {"target": "FormBox", "kind": "nurbs_face"},
     lambda p: _measured("the box Form's NURBS faces", {"match_count": p.get("match_count")},
                         p.get("match_count") == 6), None),
    # every seam of the uncreased box reads smooth, measured apart from form_create's own gate.
    ("find_geometry", {"target": "FormBox", "max_results": 50},
     lambda p: _measured("the box Form's edges", {"edges": len(_edges_of(p))},
                         0 < len(_edges_of(p)) <= 20),
     ("form_box_edges", _edges_of)),
    ("model_measure_continuity",
     lambda c: {"edges": _ctx_get(c, "form_box_edges", "the box Form's edges")},
     _seams_read("the uncreased box Form's seams read smooth", lambda a: a < 0.01), None),
    ("workspace_orient", {}, lambda p: _measured("the workspace after form_create",
                                                 p.get("workspace"), p.get("workspace") == "Design"),
     None),
    ("form_get", lambda c: {"form": _ctx_get(c, "form_box", "the box Form"), "include": ["cage"]},
     _form_cage_read, ("form_box_cage", lambda p: p["cage"])),
    ("form_create", _creased_rim_cage, _form_made(_FORM_CREASE_CM3, 4),
     ("form_crease", _crease_made)),
    ("find_geometry", {"target": "FormCrease", "max_results": 50}, _crease_handles_found, None),
    # the four sharp edges form_create returned read as the right-angle crease they are, before
    # the fillet below rounds them away.
    ("model_measure_continuity", lambda c: {"edges": _RECALL["form_crease_edges"]},
     _seams_read("the creased rim reads 90 deg", lambda a: abs(a - 90.0) < 0.1), None),
    ("model_inspect", {"target": "FormCrease", "include": ["default", "mass"], "units": "mm"},
     _inspected_mm3("FormCrease volume", _FORM_CREASE_CM3), None),
    ("model_fillet", lambda c: {"edges": _RECALL["form_crease_edges"], "radius": 1},
     lambda p: _measured("the creased rim filleted", {k: p.get(k) for k in
                                                      ("edges_cut", "volume_delta_cm3")},
                         p.get("edges_cut") == 4
                         and _near_rel(p.get("volume_delta_cm3"), _FORM_FILLET_CM3)),
     ("form_fillet", _recall("form_fillet", lambda p: p["feature"]))),
    ("model_inspect", {"target": "FormCrease", "include": ["default", "mass"], "units": "mm"},
     _inspected_mm3("the filleted FormCrease volume", _FORM_CREASE_CM3 + _FORM_FILLET_CM3),
     ("form_crease_volume", _recall("form_crease_volume", lambda p: p["mass"]["volume"]))),
    ("form_get", {}, _forms_modified, None),
    ("design_edit_timeline", lambda c: {"action": "suppress",
                                        "feature": _ctx_get(c, "form_crease", "the creased Form")},
     _named_exactly("also_suppressed", "form_fillet"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _form_pair_suppressed, None),
    ("design_edit_timeline", lambda c: {"action": "suppress", "suppressed": False,
                                        "feature": _ctx_get(c, "form_crease", "the creased Form")},
     _named_exactly("also_unsuppressed", "form_fillet"), None),
    ("model_inspect", {"target": "FormCrease", "include": ["default", "mass"], "units": "mm"},
     _same_volume("form_crease_volume"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, "ok",
     ("form_tl_pre", _recall("form_tl_pre", lambda p: p["timeline"]["count"]))),
    ("design_delete_feature", lambda c: {"feature": _ctx_get(c, "form_crease", "the creased Form")},
     _named_exactly("also_deleted", "form_fillet"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _form_count_is("form_tl_pre", -2),
     ("form_tl_post", _recall("form_tl_post", lambda p: p["timeline"]["count"]))),
    # an index past the eight vertices - a face naming a grip that does not exist is refused
    # before Fusion sees it, and the timeline reads unchanged.
    ("form_create", {"cage": {"vertices": [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
                                           [0, 0, 10], [10, 0, 10], [10, 10, 10], [0, 10, 10]],
                              "faces": [[0, 1, 2, 99]]}, "component": "FormDemo:1"},
     _refused("face 0", "99"), None),
    ("form_create", {"primitive": {"shape": "box", "size": [10, 10, 10], "spans": [1, 1, 1]},
                     "cage": {"vertices": [], "faces": []}, "component": "FormDemo:1"},
     _refused("primitive", "cage"), None),
    ("model_inspect", {"target": "FormDemo:1", "include": ["mass"], "per_body": True},
     _form_body_state_read, None),
    ("model_inspect", {"target": "FormBox", "include": ["default", "mass"], "units": "mm"},
     _form_box_bounds_read, None),
    ("design_get", {"include": ["timeline"], "max_results": 2000},
     _form_timeline_before_tiny, None),
    # This is the measured 0.005 mm box cage with only its first face's four edges creased. The
    # crease keeps Fusion past its unrelated smooth-seam guard so the area threshold is exercised.
    ("form_create", {"cage": {
                         "vertices": [[-0.0025, 0.0025, -0.0025], [0.0025, 0.0025, -0.0025],
                                      [0.0025, -0.0025, -0.0025], [-0.0025, -0.0025, -0.0025],
                                      [-0.0025, -0.0025, 0.0025], [0.0025, -0.0025, 0.0025],
                                      [0.0025, 0.0025, 0.0025], [-0.0025, 0.0025, 0.0025]],
                         "faces": [[0, 1, 2, 3], [4, 5, 6, 7], [3, 2, 5, 4], [1, 0, 7, 6],
                                   [2, 1, 6, 5], [0, 3, 4, 7]],
                         "creases": [[0, 1], [0, 3], [1, 2], [2, 3]]},
                     "name": "FormTiny", "component": "FormDemo:1"},
     _refused("FormTiny", "surface area", "1e-06 cm2"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000},
     _form_tiny_rollback_timeline, None),
    ("model_inspect", {"target": "FormDemo:1", "include": ["mass"], "per_body": True},
     _form_body_state_unchanged, None),
    ("model_inspect", {"target": "FormBox", "include": ["default", "mass"], "units": "mm"},
     _form_box_bounds_unchanged, None),
    # A cage whose surface passes through itself passes the cage check, finishEdit raises, and the
    # Form edit stays OPEN for the user to close (measured: measure_api's last row), so that refusal
    # runs there, never in this story document.
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _form_count_is("form_tl_post", 0),
     None),
    # A capped cylinder built with the marker rolled back before the box Form: it lands before the
    # box, names it, and its grouped cage still reads by the Form's own address.
    ("design_edit_timeline", lambda c: {"action": "roll", "to": "before",
                                        "feature": _ctx_get(c, "form_box", "the box Form")},
     lambda p: p.get("rolled") is True, None),
    ("form_create", {"primitive": {"shape": "cylinder", "size": [20, 40], "spans": [4]},
                     "name": "FormCyl", "component": "FormDemo:1", "origin": [1270, 200, 20]},
     _cyl_made, ("form_cyl", _recall("form_cyl", lambda p: p))),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _cyl_before_box, None),
    ("design_edit_timeline", {"action": "roll", "to": "end"},
     lambda p: p.get("rolled") is True and p.get("rolled_back") == 0, None),
    ("model_inspect", {"target": "FormCyl", "include": ["default", "mass"], "units": "mm"},
     _cyl_inspected, None),
    ("design_edit_timeline", lambda c: {"action": "group", "name": "FormPair",
                                        "feature": _RECALL["form_cyl"]["form"],
                                        "end_feature": _ctx_get(c, "form_box", "the box Form")},
     lambda p: p.get("grouped") is True and p.get("group") == "FormPair", None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _group_collapsed("FormPair"),
     None),
    ("form_get", lambda c: {"form": _RECALL["form_cyl"]["form"], "include": ["cage"]},
     _cyl_cage_read, None),
    ("design_edit_timeline", {"action": "ungroup", "feature": "FormPair"},
     lambda p: p.get("ungrouped") is True, None),
    # An uncapped cylinder is an open surface Form: its area stands in for a volume, and a
    # downstream move is what its record's corners catch.
    ("form_create", {"primitive": {"shape": "cylinder", "size": [20, 40], "spans": [4],
                                   "capped": False},
                     "name": "FormTube", "component": "FormDemo:1", "origin": [1360, 200, 20]},
     _tube_made, ("form_tube", _recall("form_tube", lambda p: p))),
    _watch("FormDemo:1"),
    ("find_geometry", {"target": "FormTube", "max_results": 20}, _tube_area, None),
    ("model_inspect", {"target": "FormDemo:1", "include": ["mass"], "per_body": True},
     _form_bodies_solid, None),
    ("model_inspect", {"target": "FormTube", "units": "mm"}, "ok",
     ("form_tube_z", _recall("form_tube_z", lambda p: p["min_point"]["z"]))),
    ("model_move", {"bodies": ["FormTube"], "dz": 10}, "ok", None),
    ("model_inspect", {"target": "FormTube", "units": "mm"}, _tube_raised, None),
    ("form_get", {}, _moved_form_modified, None),
    # THE BLEND: an edge loft with smooth and tangent ends; a free-ended loft over the same rims
    # is the crease an always-0 seam read fails.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "Blend", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "BlendA"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 1500, "cy": 200, "radius": 14}],
                             "sketch_name": "BlendA"}, "ok", None),
    ("surface_extrude", {"sketch_name": "BlendA", "distance": 50}, "ok", None),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 90, "name": "BlendTopPlane"},
     _datum_plane("xy"), None),
    ("sketch_create", {"plane": "BlendTopPlane", "name": "BlendB"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 1508, "cy": 200, "radius": 10}],
                             "sketch_name": "BlendB"}, "ok", None),
    ("surface_extrude", {"sketch_name": "BlendB", "distance": 50}, "ok", None),
    ("find_geometry", {"target": "Blend", "kind": "circular_edge", "radius": 14,
                       "nearest_to": [1500, 200, 50], "max_results": 1},
     _matched(1, "circular_edge"), _fg("blend_rim_a")),
    ("find_geometry", {"target": "Blend", "kind": "circular_edge", "radius": 10,
                       "nearest_to": [1508, 200, 90], "max_results": 1},
     _matched(1, "circular_edge"), _fg("blend_rim_b")),
    ("model_loft", lambda c: {"profiles": [_ctx_get(c, "blend_rim_a", "tube A's rim"),
                                           _ctx_get(c, "blend_rim_b", "tube B's rim")],
                              "as_surface": True, "start": "smooth", "end": "tangent"},
     _blend_lofted("smooth", "tangent"),
     ("blend_smooth", _recall("blend_smooth", lambda p: {
         "body": "Blend:1:" + p["result_bodies"][0],
         "start_weight": p["model_parameters"]["start_weight"]}))),
    ("model_measure_continuity",
     lambda c: {"edges": [_ctx_get(c, "blend_rim_a", "tube A's rim"),
                          _ctx_get(c, "blend_rim_b", "tube B's rim")],
                "against": _RECALL["blend_smooth"]["body"]},
     _seams_read("both seams under 0.01 deg, the tangent one's curvature jump 10x the smooth one's",
                 lambda a: a < 0.01, _g2_start_g1_end), None),
    ("param_set", lambda c: {"name": _RECALL["blend_smooth"]["start_weight"], "expression": "1.5"},
     lambda p: _measured("the start weight moved to 1.5",
                         {"set": p.get("set"), "after": (p.get("after") or {}).get("expression")},
                         p.get("set") is True and (p.get("after") or {}).get("expression") == "1.5"),
     None),
    ("design_recompute", {},
     lambda p: p.get("recomputed") is True and _num(p.get("error_count")), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _blend_lofts_healthy(1), None),
    ("model_measure_continuity",
     lambda c: {"edges": [_ctx_get(c, "blend_rim_a", "tube A's rim")],
                "against": _RECALL["blend_smooth"]["body"]},
     _seams_read("the reweighted smooth seam still reads under 0.01 deg", lambda a: a < 0.01),
     None),
    ("model_loft", lambda c: {"profiles": [_ctx_get(c, "blend_rim_a", "tube A's rim"),
                                           _ctx_get(c, "blend_rim_b", "tube B's rim")],
                              "as_surface": True},
     _blend_lofted("free", "free"),
     ("blend_free", _recall("blend_free", lambda p: "Blend:1:" + p["result_bodies"][0]))),
    ("model_measure_continuity",
     lambda c: {"edges": [_ctx_get(c, "blend_rim_a", "tube A's rim")],
                "against": _RECALL["blend_free"]},
     _seams_read("the free end creases the seam past 2 deg", lambda a: a > 2.0), None),
    # a tangent end on a PROFILE section: refused before Fusion sees it, the timeline unchanged.
    ("sketch_get", {"sketch_name": "BlendA"}, "ok", _prof("blend_a_profile")),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, "ok",
     ("blend_tl", _recall("blend_tl", lambda p: p["timeline"]["count"]))),
    ("model_loft", lambda c: {"profiles": [_ctx_get(c, "blend_a_profile", "tube A's profile"),
                                           _ctx_get(c, "blend_rim_b", "tube B's rim")],
                              "as_surface": True, "start": "tangent"},
     _refused("tangent", "edge"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _form_count_is("blend_tl", 0),
     None),
    # a NOSE from tube B's free rim to a sketch point: the point_tangent tip is a dome, so the
    # rim seam bends harder than under the point_sharp twin's cone - both seams stay tangent.
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 160,
                            "name": "BlendNosePlane"}, _datum_plane("xy"), None),
    ("sketch_create", {"plane": "BlendNosePlane", "name": "BlendNose"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "point", "cx": 1508, "cy": 200}],
                             "sketch_name": "BlendNose"}, "ok", None),
    ("find_geometry", {"target": "Blend", "kind": "circular_edge", "radius": 10,
                       "nearest_to": [1508, 200, 140], "max_results": 1},
     _matched(1, "circular_edge"), _fg("blend_rim_top")),
    ("model_loft", lambda c: {"profiles": [_ctx_get(c, "blend_rim_top", "tube B's free rim"),
                                           "BlendNose/point:1"],
                              "as_surface": True, "start": "tangent", "end": "point_sharp"},
     _lofted_as({"start": "tangent", "end": "point_sharp"}, ["edge", "point"], ["start_weight"]),
     ("blend_cone", _recall("blend_cone", lambda p: "Blend:1:" + p["result_bodies"][0]))),
    ("model_loft", lambda c: {"profiles": [_ctx_get(c, "blend_rim_top", "tube B's free rim"),
                                           "BlendNose/point:1"],
                              "as_surface": True, "start": "tangent", "end": "point_tangent"},
     _lofted_as({"start": "tangent", "end": "point_tangent"}, ["edge", "point"],
                ["start_weight", "end_weight"]),
     ("blend_dome", _recall("blend_dome", lambda p: "Blend:1:" + p["result_bodies"][0]))),
    ("model_measure_continuity",
     lambda c: {"edges": [_ctx_get(c, "blend_rim_top", "tube B's free rim")],
                "against": _RECALL["blend_cone"]},
     _seams_read("the cone's rim seam under 0.01 deg", lambda a: a < 0.01),
     ("blend_cone_jump", _recall("blend_cone_jump",
                                 lambda p: p["edges"][0]["max_curvature_jump"]))),
    ("model_measure_continuity",
     lambda c: {"edges": [_ctx_get(c, "blend_rim_top", "tube B's free rim")],
                "against": _RECALL["blend_dome"]},
     _seam_jump_past("blend_cone_jump", 1.5), None),
    # OPEN sketch curves with a direction start: at the 0 deg default the surface stays over the
    # 100 mm-wide sections, and the start_angle parameter at 30 deg pushes its box past them.
    ("sketch_create", {"plane": "xy", "name": "BlendOpenA"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "spline",
                                           "points": [[1600, 200], [1650, 220], [1700, 200]]}],
                             "sketch_name": "BlendOpenA"}, "ok", None),
    ("sketch_create", {"plane": "BlendTopPlane", "name": "BlendOpenB"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "spline",
                                           "points": [[1600, 200], [1650, 190], [1700, 205]]}],
                             "sketch_name": "BlendOpenB"}, "ok", None),
    ("model_loft", {"profiles": ["BlendOpenA/spline:0", "BlendOpenB/spline:0"],
                    "as_surface": True, "start": "direction"},
     _lofted_as({"start": "direction", "end": "free"}, ["curve", "curve"],
                ["start_weight", "start_angle"]),
     ("blend_open", _recall("blend_open", lambda p: {
         "body": "Blend:1:" + p["result_bodies"][0],
         "angle": p["model_parameters"]["start_angle"]}))),
    ("model_inspect", lambda c: {"target": _RECALL["blend_open"]["body"]},
     _box_x(99.99, 100.01), None),
    ("param_set", lambda c: {"name": _RECALL["blend_open"]["angle"], "expression": "30 deg"},
     lambda p: p.get("set") is True, None),
    ("model_inspect", lambda c: {"target": _RECALL["blend_open"]["body"]},
     _box_x(105.0, 130.0), None),
    # a section OBJECT carrying a key the selector does not read is refused, naming the string
    # form a sketch curve takes - never resolved as that sketch's profile 0.
    ("model_loft", {"profiles": [{"sketch": "BlendOpenA", "curve": "spline:0"},
                                 "BlendOpenB/spline:0"], "as_surface": True},
     _refused("'curve' is not read", "'<sketch>/<type>:<index>'"), None),
    # the same direction start on two PROFILES: 32 x 28 mm over the rims at 0 deg, wider at 30.
    ("model_loft", {"profiles": [{"sketch": "BlendA", "profile_index": 0},
                                 {"sketch": "BlendB", "profile_index": 0}],
                    "as_surface": True, "start": "direction"},
     _lofted_as({"start": "direction", "end": "free"}, ["profile", "profile"],
                ["start_weight", "start_angle"]),
     ("blend_prof_dir", _recall("blend_prof_dir", lambda p: {
         "body": "Blend:1:" + p["result_bodies"][0],
         "angle": p["model_parameters"]["start_angle"]}))),
    ("model_inspect", lambda c: {"target": _RECALL["blend_prof_dir"]["body"]},
     _box_x(31.99, 32.01), None),
    ("param_set", lambda c: {"name": _RECALL["blend_prof_dir"]["angle"], "expression": "30 deg"},
     lambda p: p.get("set") is True, None),
    ("model_inspect", lambda c: {"target": _RECALL["blend_prof_dir"]["body"]},
     _box_x(35.0, 60.0), None),
    # RAILS: two strips' inner edges guide a loft between open splines. rail_continuity g1 meets
    # the strip tangent along the rail; the g0 twin creases it.
    ("sketch_create", {"plane": "xy", "name": "BlendStripL"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1800, "y1": 200,
                                           "x2": 1760, "y2": 180}],
                             "sketch_name": "BlendStripL"}, "ok", None),
    ("surface_extrude", {"sketch_name": "BlendStripL", "distance": 90}, "ok", None),
    ("sketch_create", {"plane": "xy", "name": "BlendStripR"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1840, "y1": 200,
                                           "x2": 1880, "y2": 180}],
                             "sketch_name": "BlendStripR"}, "ok", None),
    ("surface_extrude", {"sketch_name": "BlendStripR", "distance": 90}, "ok", None),
    ("sketch_create", {"plane": "xy", "name": "BlendRailA"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "spline",
                                           "points": [[1800, 200], [1820, 202], [1840, 200]]}],
                             "sketch_name": "BlendRailA"}, "ok", None),
    ("sketch_create", {"plane": "BlendTopPlane", "name": "BlendRailB"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "spline",
                                           "points": [[1800, 200], [1820, 202], [1840, 200]]}],
                             "sketch_name": "BlendRailB"}, "ok", None),
    ("find_geometry", {"target": "Blend", "kind": "line_edge", "nearest_to": [1800, 200, 45],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("blend_rail_l")),
    ("find_geometry", {"target": "Blend", "kind": "line_edge", "nearest_to": [1840, 200, 45],
                       "max_results": 1}, _matched(1, "line_edge"), _fg("blend_rail_r")),
    ("model_loft", lambda c: {"profiles": ["BlendRailA/spline:0", "BlendRailB/spline:0"],
                              "rails": [_ctx_get(c, "blend_rail_l", "the left strip's edge"),
                                        _ctx_get(c, "blend_rail_r", "the right strip's edge")],
                              "as_surface": True, "rail_continuity": "g1"},
     _lofted_as({"start": "free", "end": "free"}, ["curve", "curve"], [],
                rail_continuity="g1", rails_count=2),
     ("blend_rail_g1", _recall("blend_rail_g1", lambda p: "Blend:1:" + p["result_bodies"][0]))),
    ("model_loft", lambda c: {"profiles": ["BlendRailA/spline:0", "BlendRailB/spline:0"],
                              "rails": [_ctx_get(c, "blend_rail_l", "the left strip's edge"),
                                        _ctx_get(c, "blend_rail_r", "the right strip's edge")],
                              "as_surface": True, "rail_continuity": "g0"},
     _lofted_as({"start": "free", "end": "free"}, ["curve", "curve"], [],
                rail_continuity="g0", rails_count=2),
     ("blend_rail_g0", _recall("blend_rail_g0", lambda p: "Blend:1:" + p["result_bodies"][0]))),
    ("model_measure_continuity",
     lambda c: {"edges": [_ctx_get(c, "blend_rail_l", "the left strip's edge")],
                "against": _RECALL["blend_rail_g1"]},
     _seams_read("the g1 rail seam under 0.01 deg", lambda a: a < 0.01), None),
    ("model_measure_continuity",
     lambda c: {"edges": [_ctx_get(c, "blend_rail_l", "the left strip's edge")],
                "against": _RECALL["blend_rail_g0"]},
     _seams_read("the g0 twin creases the rail seam past 10 deg", lambda a: a > 10.0), None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("sketch_create", {"plane": "xy", "name": "Proj"}, "ok", None),
    ("find_geometry", {"target": "SDel", "kind": "planar_face", "nearest_to": [310, 210, 0], "max_results": 1}, "ok", _fg("proj_face")),
    ("sketch_project", lambda c: {"entities": [_ctx_get(c, "proj_face", "project face")], "sketch_name": "Proj"}, "ok", None),
    # surface_trim + surface_untrim on intersecting sheets in clear space, with a COPLANAR decoy
    # sheet the same cutter crosses: its cells enter the same compute, so the trim below is only
    # correct if it removes the cells its target owns and leaves the decoy's alone.
    ("model_create_component", {"name": "SHole", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "SH1"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 0,
                                           "x2": 640, "y2": 0}],
                             "sketch_name": "SH1"}, "ok", None),
    ("surface_extrude", {"sketch_name": "SH1", "distance": 40}, "ok", None),
    ("sketch_create", {"plane": "xz", "name": "SH2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 620, "cy": -20, "radius": 5}],
                             "sketch_name": "SH2"}, "ok", None),
    ("surface_extrude", {"sketch_name": "SH2", "distance": 10, "symmetric": True}, "ok", None),
    ("find_geometry", {"target": "SHole", "kind": "planar_face", "nearest_to": [620, 0, 20], "max_results": 1}, "ok", _fg("sh_sheet")),
    ("find_geometry", {"target": "SHole", "kind": "cylinder_face", "nearest_to": [620, 0, 20], "max_results": 1}, "ok", _fg("sh_cutter")),
    # the decoy: a second sheet in the same plane, starting ON the cutter's axis so the cylinder
    # cuts a half-disc out of it too. It stays VISIBLE through the trim.
    ("sketch_create", {"plane": "xy", "name": "SH3"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 620, "y1": 0,
                                           "x2": 660, "y2": 0}],
                             "sketch_name": "SH3"}, "ok", None),
    ("surface_extrude", {"sketch_name": "SH3", "distance": 40},
     lambda p: p["is_solid"] is False and len(p["result_bodies"]) == 1,
     ("sh_decoy_body", _recall("sh_decoy_body", lambda p: p["result_bodies"][0]))),
    # the decoy's area BEFORE the trim - the number the read after it is compared against.
    ("find_geometry", {"target": "SHole", "kind": "planar_face", "nearest_to": [650, 0, 20],
                       "max_results": 1}, _matched(1, "planar_face"),
     ("sh_decoy_area", _recall("sh_decoy_area", lambda p: p["matches"][0]["area"]))),
    ("view_set", {"action": "snapshot"}, "ok", None),
    ("view_set", {"action": "isolate", "target": ["SHole:1"]},
     lambda p: p.get("action") == "isolate" and p.get("affected") == ["SHole:1"], None),
    # REFUSED: a second occurrence alongside it. Fusion holds one isolation at a time, so the pair
    # cannot both be isolated and the refusal hands over the two ways round it. Nothing is written -
    # the isolation above is still the one in force for the trim beats below.
    ("view_set", {"action": "isolate", "target": ["SHole:1", "SDel:1"]},
     _refused("one isolation at a time", "PARENT occurrence", "snapshot"), None),
    ("view_set", lambda c: {"action": "hide",
                            "target": [_ctx_get(c, "sh_cutter", "cylinder cutter")]},
     lambda p: p.get("action") == "hide" and bool(p.get("bodies"))
     and all(row.get("visible") is False for row in p["bodies"]), None),
    # the cell bookkeeping is the read-back: at least one cell REMOVED (a trim that removed none
    # kept the whole sheet), a kept area the phantom-cell gate could measure, and the decoy's cells
    # named as another body's and left unselected.
    ("surface_trim", lambda c: {"surface": _ctx_get(c, "sh_sheet", "sheet face"), "trim_tool": _ctx_get(c, "sh_cutter", "cylinder cutter")},
     _trim_scoped_to_target("sh_decoy_body"), None),
    # the decoy measured again, INDEPENDENTLY of the trim's own foreign_bodies_unchanged read.
    ("find_geometry", {"target": "SHole", "kind": "planar_face", "nearest_to": [650, 0, 20],
                       "max_results": 1}, _same_face_area("sh_decoy_area"), None),
    ("find_geometry", {"target": "SHole", "kind": "planar_face", "nearest_to": [620, 0, 20], "max_results": 1}, "ok", _fg("sh_trimmed")),
    # removing the hole loop FILLS it, so the created faces' area sum is the read-back that the
    # extent grew; an untrim that created nothing leaves area_after at or below area_before.
    ("surface_untrim", lambda c: {"faces": [_ctx_get(c, "sh_trimmed", "trimmed sheet face")], "loop_type": "internal"},
     lambda p: p.get("extent_grew") is True and p.get("faces_created", 0) >= 1
     and p["area_after"] > p["area_before"], None),
    # Body bulbs are outside snapshot/restore, so show the cutter before restoring occurrences/camera.
    ("view_set", lambda c: {"action": "show",
                            "target": [_ctx_get(c, "sh_cutter", "cylinder cutter")]},
     lambda p: p.get("action") == "show" and bool(p.get("bodies"))
     and all(row.get("visible") is True for row in p["bodies"]), None),
    ("view_set", {"action": "restore"},
     lambda p: p.get("camera_restored") is True and p.get("visual_style_restored") is True
     and p.get("missing_occurrences") == 0 and p.get("restored_occurrences", 0) >= 1
     and p.get("snapshot_kept") is False, None),
    # RULED surfaces off a rim edge. A line extruded as a surface gives a vertical sheet whose top
    # rim (z=30) is the seed every ruled beat leaves from; each type builds a DIFFERENT surface off
    # that same edge, so the payload's own ruled_type/direction is what separates them.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "Ruled", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "RuledS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 900, "y1": 0,
                                           "x2": 940, "y2": 0}],
                             "sketch_name": "RuledS"}, "ok", None),
    ("surface_extrude", {"sketch_name": "RuledS", "distance": 30}, "ok", None),
    ("find_geometry", {"target": "Ruled", "kind": "line_edge", "nearest_to": [920, 0, 30],
                       "max_results": 1}, "ok", _fg("ruled_edge")),
    # tangent continues the parent face's own plane past the rim, landing ONE new open body.
    ("surface_create_ruled", lambda c: {"edges": [_ctx_get(c, "ruled_edge", "the rim edge")],
                                        "distance": 15, "ruled_type": "tangent"},
     lambda p: p.get("is_solid") is False and len(p.get("result_bodies", [])) == 1
     and p.get("ruled_type") == "tangent", None),
    # normal stands perpendicular to that same face - a different surface off the same seed edge.
    ("surface_create_ruled", lambda c: {"edges": [_ctx_get(c, "ruled_edge", "the rim edge")],
                                        "distance": 15, "ruled_type": "normal"},
     lambda p: p.get("is_solid") is False and p.get("ruled_type") == "normal", None),
    # direction sweeps along an ENTITY: a world axis resolves to the component's origin axis, which
    # is what createInput consumes (a direction VECTOR cannot be handed to it).
    ("surface_create_ruled", lambda c: {"edges": [_ctx_get(c, "ruled_edge", "the rim edge")],
                                        "distance": 15, "ruled_type": "direction", "direction": "z"},
     lambda p: p.get("direction") == "z-axis" and p.get("is_solid") is False, None),
    # angle_deg reads back in DEGREES off the feature's own ModelParameter (radians at the API).
    ("surface_create_ruled", lambda c: {"edges": [_ctx_get(c, "ruled_edge", "the rim edge")],
                                        "distance": 15, "angle_deg": 20},
     lambda p: abs(p.get("angle_deg", 0) - 20) < 1e-6, None),
    # a direction entity with a type that ignores it is refused: the payload could otherwise claim
    # tangent while a Direction surface was built.
    ("surface_create_ruled", lambda c: {"edges": [_ctx_get(c, "ruled_edge", "the rim edge")],
                                        "distance": 15, "ruled_type": "tangent", "direction": "z"},
     "refused", None),
    # the Direction type with no entity: Fusion itself refuses to build the input.
    ("surface_create_ruled", lambda c: {"edges": [_ctx_get(c, "ruled_edge", "the rim edge")],
                                        "distance": 15, "ruled_type": "direction"}, "refused", None),
    # ruling off a SOLID box edge - the draft-check case. The feature's body collection holds the
    # box AND the new sheet, so a handler publishing that collection raw would report the box as
    # created and read is_solid=true off it: the new sheet alone is the result.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "RuledSolid", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "RuledSolidS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 980, "y1": 200,
                                           "x2": 1020, "y2": 240}],
                             "sketch_name": "RuledSolidS"}, "ok", None),
    ("model_extrude", {"sketch_name": "RuledSolidS", "profile_index": 0, "distance": 20}, _extruded, None),
    ("find_geometry", {"target": "RuledSolid", "kind": "line_edge", "nearest_to": [1000, 200, 20],
                       "max_results": 1}, "ok", _fg("ruled_solid_edge")),
    ("surface_create_ruled", lambda c: {"edges": [_ctx_get(c, "ruled_solid_edge", "a box top edge")],
                                        "distance": 15, "ruled_type": "tangent"},
     lambda p: p.get("is_solid") is False and len(p.get("result_bodies", [])) == 1
     and "Body1" not in p.get("result_bodies", []), None),
    # back to the component that was active before this cameo, so the ones after it nest as before.
    ("design_activate_component", {"occurrence": "SHole:1"}, "ok", None),
    # split / unstitch / stitch / base-feature / arrange / compute-holder.
    ("model_create_component", {"name": "Spl", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "Sp1"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 400, "y1": 200,
                                           "x2": 440, "y2": 240}],
                             "sketch_name": "Sp1"}, "ok", None),
    ("model_extrude", {"sketch_name": "Sp1", "profile_index": 0, "distance": 20}, _extruded, None),
    ("model_construction", {"kind": "plane", "plane": "xz", "offset": 220, "name": "SplMid"},
     _datum_plane("xz"), None),
    ("find_geometry", {"target": "Spl", "kind": "planar_face", "nearest_to": [420, 220, 20], "max_results": 1}, "ok", _fg("spl_body")),
    ("model_split", lambda c: {"split": "body", "target": _ctx_get(c, "spl_body", "split body"), "split_plane": "SplMid"}, _split_bodies, None),
    ("model_create_component", {"name": "Stc", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "St1"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 500, "y1": 200,
                                           "x2": 520, "y2": 220}],
                             "sketch_name": "St1"}, "ok", None),
    ("model_extrude", {"sketch_name": "St1", "profile_index": 0, "distance": 10}, _extruded, None),
    ("find_geometry", {"target": "Stc", "kind": "planar_face", "nearest_to": [510, 210, 10], "max_results": 1}, "ok", _fg("stc_body")),
    ("model_unstitch", lambda c: {"target": _ctx_get(c, "stc_body", "unstitch body"), "chain": False}, _unstitched, None),
    ("find_geometry", {"target": "Stc", "kind": "planar_face", "nearest_to": [510, 210, 0], "max_results": 1}, "ok", _fg("stc_f1")),
    ("find_geometry", {"target": "Stc", "kind": "planar_face", "nearest_to": [500, 210, 5], "max_results": 1}, "ok", _fg("stc_f2")),
    ("model_stitch", lambda c: {"bodies": [_ctx_get(c, "stc_f1", "stitch a"), _ctx_get(c, "stc_f2", "stitch b")]}, _stitched, None),
    # Preserve the full composed timeline, prove a wrong name leaves BF1 open, then finish by the
    # actual adopted name and independently read the one-row delta.
    ("doc_get", {}, _document_read,
     ("bf_story_doc", _recall("bf_story_doc", lambda p: p["active"]["document_handle"]))),
    ("design_get", {"include": ["mode", "timeline"], "max_results": 2000},
     _base_feature_parametric,
     ("bf_story_before", _recall("bf_story_before", _base_feature_state))),
    ("model_base_feature",
     lambda c: {"action": "start", "base_feature": "BF1",
                "expect_document": _ctx_get(c, "bf_story_doc", "the sweep document")},
     _base_feature_open,
     ("bf_story_name", _recall("bf_story_name", lambda p: p["base_feature"]))),
    ("design_get", {"include": ["mode"]}, _base_feature_direct, None),
    ("model_base_feature",
     lambda c: {"action": "finish", "base_feature": "BF1Missing",
                "expect_document": _ctx_get(c, "bf_story_doc", "the sweep document")},
     _refused("No captured or existing base feature named 'BF1Missing'",
              "active document", "exact base_feature returned by start"), None),
    ("design_get", {"include": ["mode"]}, _base_feature_direct, None),
    ("model_base_feature",
     lambda c: {"action": "finish",
                "base_feature": _ctx_get(c, "bf_story_name", "the adopted BF1 name"),
                "expect_document": _ctx_get(c, "bf_story_doc", "the sweep document")},
     lambda p: p.get("editing") is False and len(p.get("closed_scopes") or []) == 1
     and p.get("named_finished") == _RECALL["bf_story_name"], None),
    ("design_get", {"include": ["mode", "timeline"], "max_results": 2000},
     _base_feature_added("bf_story_before", "bf_story_name"),
     ("bf_story_after", _recall("bf_story_after", _base_feature_state))),

    # Named round: open the same adopted name in the sweep document and one owned scratch document.
    # Finishing B must leave A direct/no-timeline until A is activated and explicitly finished.
    ("model_base_feature",
     lambda c: {"action": "start", "base_feature": "BFCrossNamed",
                "expect_document": _ctx_get(c, "bf_story_doc", "the sweep document")},
     _base_feature_open,
     ("bf_cross_named_a", _recall("bf_cross_named_a", lambda p: p["base_feature"]))),
    ("design_get", {"include": ["mode"]}, _base_feature_direct, None),
    ("doc_new",
     lambda c: {"expect_document": _ctx_get(c, "bf_story_doc", "the sweep document")},
     _new_document,
     ("bf_extra_doc", _recall("bf_extra_doc", lambda p: p["document_handle"]))),
    ("design_get", {"include": ["mode", "timeline"], "max_results": 200},
     _base_feature_parametric,
     ("bf_extra_before", _recall("bf_extra_before", _base_feature_state))),
    ("model_base_feature",
     lambda c: {"action": "start",
                "base_feature": _ctx_get(c, "bf_cross_named_a", "the shared scope name"),
                "expect_document": _ctx_get(c, "bf_extra_doc", "the extra document")},
     _base_feature_same_name("bf_cross_named_a"),
     ("bf_cross_named_b", _recall("bf_cross_named_b", lambda p: p["base_feature"]))),
    ("design_get", {"include": ["mode"]}, _base_feature_direct, None),
    ("model_base_feature",
     lambda c: {"action": "finish",
                "base_feature": _ctx_get(c, "bf_cross_named_b", "the extra document scope"),
                "expect_document": _ctx_get(c, "bf_extra_doc", "the extra document")},
     lambda p: p.get("editing") is False and len(p.get("closed_scopes") or []) == 1,
     None),
    ("design_get", {"include": ["mode", "timeline"], "max_results": 200},
     _base_feature_added("bf_extra_before", "bf_cross_named_b"),
     ("bf_extra_named_after", _recall("bf_extra_named_after", _base_feature_state))),
    ("doc_activate",
     lambda c: {"name": _ctx_get(c, "bf_story_doc", "the sweep document"),
                "expect_document": _ctx_get(c, "bf_extra_doc", "the extra document")},
     _activated(), None),
    ("design_get", {"include": ["mode"]}, _base_feature_direct, None),
    ("model_base_feature",
     lambda c: {"action": "finish",
                "base_feature": _ctx_get(c, "bf_cross_named_a", "the sweep document scope"),
                "expect_document": _ctx_get(c, "bf_story_doc", "the sweep document")},
     lambda p: p.get("editing") is False and len(p.get("closed_scopes") or []) == 1,
     None),
    ("design_get", {"include": ["mode", "timeline"], "max_results": 2000},
     _base_feature_added("bf_story_after", "bf_cross_named_a"),
     ("bf_story_named_after", _recall("bf_story_named_after", _base_feature_state))),

    # Unnamed round on the same two documents proves the active-document filter also governs the
    # legacy finish route. Each document remains independently readable before the other closes.
    ("model_base_feature",
     lambda c: {"action": "start", "base_feature": "BFCrossUnnamed",
                "expect_document": _ctx_get(c, "bf_story_doc", "the sweep document")},
     _base_feature_open,
     ("bf_cross_unnamed_a", _recall("bf_cross_unnamed_a", lambda p: p["base_feature"]))),
    ("design_get", {"include": ["mode"]}, _base_feature_direct, None),
    ("doc_activate",
     lambda c: {"name": _ctx_get(c, "bf_extra_doc", "the extra document"),
                "expect_document": _ctx_get(c, "bf_story_doc", "the sweep document")},
     _activated(), None),
    ("model_base_feature",
     lambda c: {"action": "start",
                "base_feature": _ctx_get(c, "bf_cross_unnamed_a", "the shared scope name"),
                "expect_document": _ctx_get(c, "bf_extra_doc", "the extra document")},
     _base_feature_same_name("bf_cross_unnamed_a"),
     ("bf_cross_unnamed_b", _recall("bf_cross_unnamed_b", lambda p: p["base_feature"]))),
    ("design_get", {"include": ["mode"]}, _base_feature_direct, None),
    ("model_base_feature",
     lambda c: {"action": "finish",
                "expect_document": _ctx_get(c, "bf_extra_doc", "the extra document")},
     lambda p: p.get("editing") is False and len(p.get("closed_scopes") or []) == 1,
     None),
    ("design_get", {"include": ["mode", "timeline"], "max_results": 200},
     _base_feature_added("bf_extra_named_after", "bf_cross_unnamed_b"), None),
    ("doc_activate",
     lambda c: {"name": _ctx_get(c, "bf_story_doc", "the sweep document"),
                "expect_document": _ctx_get(c, "bf_extra_doc", "the extra document")},
     _activated(), None),
    ("design_get", {"include": ["mode"]}, _base_feature_direct, None),
    ("model_base_feature",
     lambda c: {"action": "finish",
                "expect_document": _ctx_get(c, "bf_story_doc", "the sweep document")},
     lambda p: p.get("editing") is False and len(p.get("closed_scopes") or []) == 1,
     None),
    ("design_get", {"include": ["mode", "timeline"], "max_results": 2000},
     _base_feature_added("bf_story_named_after", "bf_cross_unnamed_a"), None),
    ("doc_close",
     lambda c: {"name": _ctx_get(c, "bf_extra_doc", "the extra document"),
                "save_changes": False,
                "expect_document": _ctx_get(c, "bf_story_doc", "the sweep document")},
     _document_closed, None),
    ("design_activate_component", {"occurrence": "Stc:1"}, "ok", None),
] + [
    # compute_holder needs a body + a cyl-face axis + a planar end-datum.
    ("model_create_component", {"name": "HolderPart", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "HP1"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 600, "y1": 200,
                                           "x2": 640, "y2": 220}],
                             "sketch_name": "HP1"}, "ok", None),
    ("model_extrude", {"sketch_name": "HP1", "profile_index": 0, "distance": 10}, _extruded, None),
    ("find_geometry", {"target": "HolderPart", "kind": "planar_face", "nearest_to": [620, 210, 10], "max_results": 1}, "ok", _fg("hp_top")),
    # hole points ride the face's LOCAL frame = the model origin projected onto the face, so
    # on-pad coordinates are the world x,y (same measured fact as the FeatureCameo hole).
    ("model_hole", lambda c: {"face": _ctx_get(c, "hp_top", "holder top"), "hole_type": "simple", "diameter": "4 mm", "extent": "blind", "depth": "8 mm", "points": [[605, 205, 0]]}, _drilled(1), None),
    ("find_geometry", {"target": "HolderPart", "kind": "planar_face", "max_results": 1}, "ok", _fg("hp_body")),
    ("find_geometry", {"target": "HolderPart", "kind": "cylinder_face", "radius": 2, "max_results": 1}, "ok", _fg("hp_axis")),
    ("find_geometry", {"target": "HolderPart", "kind": "planar_face", "nearest_to": [620, 210, 10], "max_results": 1}, "ok", _fg("hp_datum")),
    ("model_compute_holder", lambda c: {"body": _ctx_get(c, "hp_body", "holder body"), "axis": _ctx_get(c, "hp_axis", "holder axis"), "end_datum": _ctx_get(c, "hp_datum", "holder datum")}, _holder_computed, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
]

_HOLDER_TAPER_STATE = '''import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    design = adsk.fusion.Design.cast(app.activeProduct)
    def point(p): return [round(p.x*10, 9), round(p.y*10, 9), round(p.z*10, 9)]
    def face(f):
        circles = []
        for edge in f.edges:
            c = adsk.core.Circle3D.cast(edge.geometry)
            if c is not None: circles.append([point(c.center), c.radius*10])
        return {'type': f.geometry.objectType, 'area': f.area, 'circles': circles}
    print(json.dumps({'timeline': design.timeline.count, 'marker': design.timeline.markerPosition,
        'bodies': [{'name': b.name, 'solid': b.isSolid, 'faces': [face(f) for f in b.faces],
                    'volume': b.physicalProperties.volume,
                    'box': [point(b.boundingBox.minPoint), point(b.boundingBox.maxPoint)]}
                   for b in design.rootComponent.bRepBodies]}))
'''


def _holder_taper_native(p, hollow):
    """Compare the unchanged exterior and measured enclosed cavity independently of the holder export."""
    bodies = p.get("bodies") or []
    if len(bodies) != 1:
        return False
    body = bodies[0]
    faces = body.get("faces") or []
    cones = [f for f in faces if f.get("type") == "adsk::core::Cone"]
    valid = (body.get("solid") is True and bool(body.get("name"))
             and body.get("box") == [[-20, 0, -20], [20, 30, 20]]
             and len(faces) == (6 if hollow else 3) and len(cones) == 1
             and _near(cones[0].get("area"), 29.8037647973883, 1e-8)
             and sorted(cones[0].get("circles") or []) == [[[0, 0, 0], 10], [[0, 30, 0], 20]])
    if hollow:
        control = _RECALL.get("holder_taper_solid", {}).get("bodies", [])
        cylinders = [f for f in faces if f.get("type") == "adsk::core::Cylinder"]
        valid = (valid and len(control) == 1 and len(cylinders) == 1
                 and sorted(cylinders[0].get("circles") or []) == [[[0, 10, 0], 8], [[0, 20, 0], 8]]
                 and _near(control[0]["volume"] - body["volume"], math.pi * .8**2, 1e-8))
    return _measured("holder exterior and enclosed cavity", p, valid)


def _holder_taper_reply(p):
    """Require the exported envelope to describe the measured outer frustum only."""
    segments = [{"height": 30.0, "lower-diameter": 20.0, "upper-diameter": 40.0}]
    return _measured("one unchanged tapered holder envelope", p,
                     p.get("segment_count") == 1 and p.get("segments_mm") == segments
                     and (p.get("holder_json") or {}).get("segments") == segments)


def _holder_taper_rows():
    """Compare solid and enclosed-void holder envelopes in one disposable document."""
    rows = [("doc_get", {}, _home_document,
             ("holder_taper_home", _recall("holder_taper_home", _home_address))),
            ("doc_new", {}, _new_document,
             ("holder_taper_doc", _recall("holder_taper_doc", lambda p: p["document_handle"])))]
    for hollow, sketch in ((False, "HolderOuter"), (True, "HolderCavity")):
        key = "holder_taper_hollow" if hollow else "holder_taper_solid"
        geometry = ([{"kind": "rectangle", "x1": 0, "y1": 10, "x2": 8, "y2": 20}] if hollow
                    else [{"kind": "closed_path", "points": [[0, 0], [10, 0], [20, 30], [0, 30]]}])
        rows += [("sketch_create", {"plane": "xy", "name": sketch}, "ok", None),
                 ("sketch_add_geometry", {"sketch_name": sketch, "units": "mm", "geometry": geometry}, "ok", None),
                 ("model_revolve", lambda c, sketch=sketch, hollow=hollow:
                  {"sketch_name": sketch, "axis": "y", "operation": "cut" if hollow else "new",
                   **({"target_bodies": [_RECALL["holder_taper_solid"]["bodies"][0]["name"]]} if hollow else {})}, "ok", None),
                 ("sys_execute_script", {"script": _HOLDER_TAPER_STATE, "read_only": True},
                  lambda p, hollow=hollow: bool(p.get("bodies")) and _holder_taper_native(p, hollow),
                  (key, _recall(key, lambda p: p))),
                 ("find_geometry", lambda c, key=key: {"target": _RECALL[key]["bodies"][0]["name"],
                   "kind": "cone_face", "max_results": 10},
                  lambda p: len(p.get("matches") or []) == 1, _fg("holder_taper_axis")),
                 ("find_geometry", lambda c, key=key: {"target": _RECALL[key]["bodies"][0]["name"],
                   "kind": "planar_face", "nearest_to": [5, 0, 0], "max_results": 1},
                  lambda p: len(p.get("matches") or []) == 1, _fg("holder_taper_end")),
                 ("model_compute_holder", lambda c, key=key: {"body": _RECALL[key]["bodies"][0]["name"],
                   "axis": _ctx_get(c, "holder_taper_axis", "outer cone"),
                   "end_datum": _ctx_get(c, "holder_taper_end", "lower end"), "name": "TaperEnvelope"},
                  _holder_taper_reply, None),
                 ("sys_execute_script", {"script": _HOLDER_TAPER_STATE, "read_only": True},
                  lambda p, key=key: _measured("holder read preserves geometry and history", p,
                                               len(p.get("bodies") or []) == 1
                                               and p == _RECALL.get(key)), None)]
    return rows + [
        ("doc_close", lambda c: {"name": _ctx_get(c, "holder_taper_doc", "owned holder coupon"),
                                  "save_changes": False}, _document_closed, None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, "holder_taper_home", "original family document")},
         _activated(), None),
        ("doc_get", {}, lambda p: _home_address(p) == _RECALL.get("holder_taper_home"), None)]


_MACHINING += _holder_taper_rows()
_DESIGN_D_STATE = """import adsk.core, adsk.fusion, json

def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    d = adsk.fusion.Design.cast(app.activeProduct)
    def pt(p): return [round(getattr(p, a)*10, 9) for a in ('x', 'y', 'z')]
    def body(b):
        vertical = []
        for e in b.edges:
            if isinstance(e.geometry, adsk.core.Line3D):
                a, z = e.startVertex.geometry, e.endVertex.geometry
                if abs(a.x-z.x) < 1e-9 and abs(a.y-z.y) < 1e-9 and abs(a.z-z.z) > .1:
                    vertical.append(pt(a)[:2])
        return {'name': b.name, 'solid': b.isSolid, 'volume_cm3': b.volume,
            'area_cm2': b.physicalProperties.area, 'face_count': b.faces.count,
            'bbox_mm': [pt(b.boundingBox.minPoint), pt(b.boundingBox.maxPoint)],
            'vertices_mm': sorted(pt(v.geometry) for v in b.vertices),
            'vertical_edge_xy_mm': sorted(vertical),
            'face_types': sorted(f.geometry.objectType for f in b.faces),
            'face_areas_cm2': sorted(round(f.area, 12) for f in b.faces)}
    result = {'bodies': [body(b) for b in d.rootComponent.bRepBodies],
        'timeline': [{'name': t.name, 'type': t.entity.objectType, 'health': int(t.healthState)}
                     for t in d.timeline], 'marker': d.timeline.markerPosition,
        'sketches': [{'name': s.name, 'bulb': s.isLightBulbOn, 'visible': s.isVisible,
            'lines': s.sketchCurves.sketchLines.count, 'points': sorted(pt(p.geometry) for p in s.sketchPoints)}
                    for s in d.rootComponent.sketches]}
    patch_name = PATCH_NAME
    if patch_name is not None:
        found = [b for b in d.rootComponent.bRepBodies if b.name == patch_name]
        assert len(found) == 1 and found[0].faces.count == 1
        face = found[0].faces.item(0)
        good, uv = face.evaluator.getParameterAtPoint(adsk.core.Point3D.create(.5, .5, .2))
        assert good
        good, sample = face.evaluator.getPointAtParameter(uv)
        assert good
        result['patch_sample_mm'] = pt(sample)
    print(json.dumps(result))
"""


def _design_d_read(key, patch=False):
    """Read complete owned scratch material/history and optionally sample the returned patch."""
    def args(c):
        name = _ctx_get(c, key + "_patch", "new patch")["body"] if patch else None
        return {"script": _DESIGN_D_STATE.replace("PATCH_NAME", repr(name)), "read_only": True,
                "expect_document": _ctx_get(c, key + "_doc", "owned Design D scratch")}
    return args


def _design_d_begin(key):
    """Open one disposable root fixture with a typed independent witness cube."""
    return [("doc_get", {}, _home_document, (key + "_home", _recall(key + "_home", _home_address))),
            ("doc_new", {}, _new_document, (key + "_doc", _recall(key + "_doc", lambda p: p["document_handle"]))),
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("sketch_create", lambda c: _combine_pin(c, key + "_doc",
                {"name": key + "Witness", "plane": "xy"}),
             "ok", None),
            ("sketch_add_geometry", lambda c: _combine_pin(c, key + "_doc", {
                "sketch_name": key + "Witness", "units": "mm", "geometry": [
                {"kind": "rectangle", "x1": 100, "y1": 0, "x2": 120, "y2": 20}]}), "ok", None),
            ("model_extrude", {"sketch_name": key + "Witness", "distance": 20, "units": "mm", "operation": "new"},
             _extruded, (key + "_witness", _recall(key + "_witness", lambda p: p["result_bodies"][0])))]


def _design_d_close(key):
    """Close only the owned disposable document and return to the captured home session."""
    return [("doc_close", lambda c: {"name": _ctx_get(c, key + "_doc", "owned Design D scratch"),
                  "save_changes": False, "expect_document": _ctx_get(c, key + "_doc", "owned Design D scratch")},
             _document_closed, None),
            ("doc_activate", lambda c: {"name": _ctx_get(c, key + "_home", "home session")}, _activated(), None),
            ("doc_get", {}, lambda p: _home_address(p) == _RECALL.get(key + "_home"), None)]


def _design_d_same(key):
    """Require complete independent geometry, history and sketch state to equal the baseline."""
    return lambda p: _measured("Design D native state restored", p,
                               bool(p.get("bodies")) and p == _RECALL.get(key + "_before"))


def _silhouette_reply(axis):
    """Require the public split to disclose the direction-specific measured generator edges."""
    xy = ((40, -10), (40, 10)) if axis == "x" else ((30, 0), (50, 0))
    expected = {((x, y, 0), (x, y, 20)) for x, y in xy}
    return lambda p: _measured("silhouette topology and generator positions", p,
        p.get("split") == "silhouette" and p.get("faces_before") == 3 and p.get("faces_after") == 6
        and p.get("result_count") == 3 and abs(p.get("volume_change_cm3", 1)) <= 1e-9
        and expected <= {tuple(tuple(v) for v in e) for e in p.get("new_line_edges_mm", [])}
        and bool(p.get("feature")))


def _silhouette_native(p, axis):
    """Compare actual cylinder topology/material, split caps and the independent witness."""
    baseline = _RECALL["DSil_before"]
    target = _RECALL["DSil_body"]
    before = {b["name"]: b for b in baseline["bodies"]}
    after = {b["name"]: b for b in p.get("bodies", [])}
    cylinder = after.get(target, {})
    xy = [[40, -10], [40, 10]] if axis == "x" else [[30, 0], [50, 0]]
    return _measured("native cylinder silhouette and unchanged witness", p,
        len(after) == 2 and set(after) == set(before) and cylinder.get("face_count") == 6
        and cylinder.get("solid") is True and cylinder.get("bbox_mm") == [[30, -10, 0], [50, 10, 20]]
        and _near(cylinder.get("volume_cm3"), before[target]["volume_cm3"], 1e-9)
        and _near(cylinder.get("area_cm2"), 18.84955592153876, 1e-8)
        and all(v in cylinder.get("vertical_edge_xy_mm", []) for v in xy)
        and cylinder.get("face_types", []).count("adsk::core::Plane") == 4
        and cylinder.get("face_types", []).count("adsk::core::Cylinder") == 2
        and all(after[name] == before[name] for name in before if name != target)
        and p.get("sketches") == baseline["sketches"]
        and len(p.get("timeline", [])) == len(baseline["timeline"]) + 1
        and p["timeline"][:-1] == baseline["timeline"] and p["timeline"][-1]["health"] == 0
        and p["timeline"][-1]["type"] == "adsk::fusion::SilhouetteSplitFeature"
        and p.get("marker") == baseline["marker"] + 1)


def _design_d_silhouette_rows():
    """Run independent X/Y silhouette cases from the same restored cylinder baseline."""
    key = "DSil"
    rows = _design_d_begin(key) + [
        ("sketch_create", lambda c: _combine_pin(c, key + "_doc",
            {"name": "DSilCylinder", "plane": "xy"}),
         "ok", None),
        ("sketch_add_geometry", lambda c: _combine_pin(c, key + "_doc", {
            "sketch_name": "DSilCylinder", "units": "mm",
            "geometry": [{"kind": "circle", "cx": 40, "cy": 0, "radius": 10}]}), "ok", None),
        ("model_extrude", {"sketch_name": "DSilCylinder", "distance": 20, "units": "mm", "operation": "new"},
         _extruded, ("DSil_body", _recall("DSil_body", lambda p: p["result_bodies"][0]))),
        ("sys_execute_script", _design_d_read(key),
         lambda p: len(p.get("bodies", [])) == 2 and all(t["health"] == 0 for t in p.get("timeline", []))
         and any(b["name"] == _RECALL["DSil_body"] and b["face_count"] == 3
                 and b["bbox_mm"] == [[30, -10, 0], [50, 10, 20]]
                 and _near(b["volume_cm3"], 6.283185307179316, 1e-9) for b in p["bodies"]),
         ("DSil_before", _recall("DSil_before", lambda p: p))),
    ]
    for axis in ("x", "y"):
        rows += [("find_geometry", lambda c: {"target": _ctx_get(c, "DSil_body", "cylinder"),
                    "kind": "cylinder_face", "max_results": 10}, _matched(1, "cylinder_face"), _fg("DSil_handle")),
                 ("model_split", lambda c, axis=axis: {"split": "silhouette", "view_direction": axis,
                    "target": _ctx_get(c, "DSil_handle", "current cylinder face")}, _silhouette_reply(axis),
                  ("DSil_feature", lambda p: p["feature"])),
                 ("sys_execute_script", _design_d_read(key), lambda p, axis=axis: bool(p.get("bodies")) and _silhouette_native(p, axis), None),
                 ("design_delete_feature", lambda c: {"feature": _ctx_get(c, "DSil_feature", "silhouette")},
                  lambda p: p.get("deleted") is True and p.get("also_deleted") == [], None),
                 ("sys_execute_script", _design_d_read(key), _design_d_same(key), None)]
    return rows + _design_d_close(key)


def _patch_boundary_handles(p):
    """Acquire one square profile and its four current line handles in drawn loop order."""
    profiles = p.get("profiles") or []
    lines = sorted((r for r in p.get("entities", []) if r.get("type") == "line"), key=lambda r: r["id"])
    valid = (len(profiles) == 1 and _near(profiles[0].get("area"), 100, 1e-6)
             and bool(profiles[0].get("handle")) and len(lines) == 4
             and [r["id"] for r in lines] == ["line:" + str(i) for i in range(4)]
             and all(r.get("handle") for r in lines))
    if valid:
        _RECALL["DPatch_profile"] = profiles[0]["handle"]
        _RECALL["DPatch_lines"] = [r["handle"] for r in lines]
    return _measured("current square profile and four line handles", p, valid)


def _patch_native(p):
    """Require one new healthy square sheet with its center sampled independently."""
    baseline = _RECALL["DPatch_before"]
    name = _RECALL["DPatch_patch"]["body"]
    bodies = p.get("bodies") or []
    patches = [b for b in bodies if b.get("name") == name]
    patch = patches[0] if len(patches) == 1 else {}
    return _measured("native sketch-boundary patch material and sample", p,
        len(bodies) == len(baseline["bodies"]) + 1
        and [b for b in bodies if b.get("name") != name] == baseline["bodies"]
        and patch.get("solid") is False and patch.get("face_count") == 1
        and _near(patch.get("area_cm2"), 1, 1e-9)
        and patch.get("bbox_mm") == [[0, 0, 0], [10, 10, 0]] and p.get("patch_sample_mm") == [5, 5, 0]
        and p.get("timeline", [])[:-1] == baseline["timeline"]
        and len(p.get("timeline", [])) == len(baseline["timeline"]) + 1
        and p["timeline"][-1]["type"] == "adsk::fusion::PatchFeature" and p["timeline"][-1]["health"] == 0
        and p.get("marker") == baseline["marker"] + 1)


def _patch_bulb_reset(c):
    """Restore only this owned fixture's consumed sketch bulb, separately from feature retirement."""
    return {"expect_document": _ctx_get(c, "DPatch_doc", "owned patch scratch"), "read_only": False,
        "script": """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile is None
    d = adsk.fusion.Design.cast(app.activeProduct)
    s = d.rootComponent.sketches.itemByName('DPatchBoundary')
    assert s is not None and s.sketchCurves.sketchLines.count == 4
    before = s.isLightBulbOn
    s.isLightBulbOn = True
    print(json.dumps({'sketch': s.name, 'bulb_before': before, 'bulb_after': s.isLightBulbOn,
                      'fixture_visibility_reset': True}))
"""}


def _design_d_patch_rows():
    """Patch one root square by profile and lines, then refuse a separately drawn gapped boundary."""
    key = "DPatch"
    rows = _design_d_begin(key) + [
        ("sketch_create", lambda c: _combine_pin(c, key + "_doc",
            {"name": "DPatchBoundary", "plane": "xy"}),
         "ok", None),
        ("sketch_add_geometry", lambda c: _combine_pin(c, key + "_doc", {
            "sketch_name": "DPatchBoundary", "units": "mm",
            "geometry": [{"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]}), "ok", None),
        ("sys_execute_script", _design_d_read(key), lambda p: len(p.get("bodies", [])) == 1
         and all(t["health"] == 0 for t in p.get("timeline", []))
         and any(s["name"] == "DPatchBoundary" and s["bulb"] is True for s in p.get("sketches", [])),
         ("DPatch_before", _recall("DPatch_before", lambda p: p))),
    ]
    for kind in ("profile", "sketch_lines"):
        rows += [("sketch_get", {"sketch_name": "DPatchBoundary", "include_entities": True,
                     "max_results": 100, "units": "mm"}, _patch_boundary_handles, None),
                 ("surface_patch", lambda c, kind=kind: {"boundary": _RECALL[
                     "DPatch_profile" if kind == "profile" else "DPatch_lines"]},
                  lambda p, kind=kind: p.get("patched") is True and p.get("boundary_kind") == kind
                  and p.get("boundary_edge_count") is None and p.get("is_solid") is False,
                  ("DPatch_patch", _recall("DPatch_patch", lambda p: {"body": p["result_body"], "feature": p["feature"]}))),
                 ("sys_execute_script", _design_d_read(key, patch=True), _patch_native, None),
                 ("design_delete_feature", lambda c: {"feature": _ctx_get(c, "DPatch_patch", "patch")["feature"]},
                  lambda p: p.get("deleted") is True and p.get("also_deleted") == [], None),
                 ("sys_execute_script", _design_d_read(key),
                  lambda p: _measured("retired patch preserves native material/history before bulb reset", p,
                      p.get("bodies") == _RECALL["DPatch_before"]["bodies"]
                      and p.get("timeline") == _RECALL["DPatch_before"]["timeline"]
                      and p.get("marker") == _RECALL["DPatch_before"]["marker"]), None),
                 ("sys_execute_script", _patch_bulb_reset,
                  lambda p: p.get("sketch") == "DPatchBoundary" and p.get("bulb_after") is True
                  and p.get("fixture_visibility_reset") is True, None),
                 ("sys_execute_script", _design_d_read(key), _design_d_same(key), None)]
    rows += [("sketch_create", lambda c: _combine_pin(c, key + "_doc",
              {"name": "DPatchGap", "plane": "xy"}),
              "ok", None),
             ("sketch_add_geometry", lambda c: _combine_pin(c, key + "_doc", {
                 "sketch_name": "DPatchGap", "units": "mm", "geometry": [
                 {"kind": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0},
                 {"kind": "line", "x1": 10, "y1": 0, "x2": 10, "y2": 10},
                 {"kind": "line", "x1": 10, "y1": 10, "x2": 0, "y2": 10},
                 {"kind": "line", "x1": 0, "y1": 10, "x2": 0, "y2": 1}]}), "ok", None),
             ("find_geometry", {"kind": "sketch_line", "sketch": "DPatchGap", "max_results": 10},
              _matched(4, "sketch_line"), _fgn("DPatch_gap_handles")),
             ("sys_execute_script", _design_d_read(key), lambda p: len(p.get("bodies", [])) == 1,
              ("DPatch_gap_before", _recall("DPatch_gap_before", lambda p: p))),
             ("surface_patch", lambda c: {"boundary": _ctx_get(c, "DPatch_gap_handles", "gapped lines")},
              _refused("gap", "closing the last line to the first"), None),
             ("sys_execute_script", _design_d_read(key), _design_d_same("DPatch_gap"), None)]
    return rows + _design_d_close(key)


_MACHINING += _design_d_silhouette_rows() + _design_d_patch_rows()


def _thicken_source_geometry(p):
    """Read the complete planar sheet geometry apart from its disclosed visibility."""
    rows = _edge_extent_geometry(p)
    if (rows is None or len(rows) != 5 or sum(r["kind"] == "planar_face" for r in rows) != 1
            or sum(r["kind"] == "line_edge" for r in rows) != 4
            or next(r for r in rows if r["kind"] == "planar_face")["area"] != 60):
        return None
    return [{k: v for k, v in r.items() if k != "hidden"} for r in rows]


def _thicken_material(p):
    """Read finite solid bounds and physical properties for the wall or witness."""
    shape = _sweep_mode_shape(p)
    if (p.get("kind") != "body" or p.get("units") != "mm" or p.get("lump_count") != 1
            or not _sweep_mode_box_equal(shape, shape)
            or any(not _num(shape[k]) or not math.isfinite(shape[k]) or shape[k] <= 0 for k in ("volume", "area"))):
        return None
    return {"shape": shape, "mass": p.get("mass")}


def _thicken_witness_material(p):
    """Read the independently placed five millimeter cube's complete physical snapshot."""
    state = _thicken_material(p)
    if (state is None or not _near(state["shape"]["volume"], 125, .0001)
            or not _near(state["shape"]["area"], 150, .0001)
            or [p.get(a) for a in "xyz"] != [5, 5, 5]
            or p.get("min_point") != {"x": 60, "y": 0, "z": 0}
            or p.get("max_point") != {"x": 65, "y": 5, "z": 5}):
        return None
    return state


def _placed_sheet_bodies(p):
    """The PTSheet occurrence's body rows in a design_get tree, or None when not exactly one node."""
    nodes = [n for n in (p.get("tree") or {}).get("children") or [] if n.get("component") == "PTSheet"]
    return nodes[0].get("bodies") if len(nodes) == 1 else None


def _placed_sheet_visible(visible):
    """The placed sheet reads back under the thicken's disclosed handle with this visibility."""
    def check(p):
        bodies = _placed_sheet_bodies(p)
        want = _RECALL.get("pt_source_handle")
        # The new wall lands beside its source in the active component: one sheet, one solid.
        sheets = [b for b in bodies or [] if b.get("is_solid") is False]
        return _measured("placed source read under the disclosed handle", bodies,
                         isinstance(bodies, list) and len(bodies) == 2 and len(sheets) == 1 and bool(want)
                         and sheets[0].get("handle") == want and sheets[0].get("visible") is visible
                         and sum(b.get("is_solid") is True for b in bodies) == 1)
    return check


def _placed_source_thickened(p):
    """The hidden placed source is undone by view_set on its own handle, with no tree detour."""
    rows = p.get("source_visibility") or [{}]
    handle, body = rows[0].get("handle"), rows[0].get("body")
    note = p.get("note") or ""
    return _measured("placed source remedy names its own handle", {"rows": rows, "note": note},
                     p.get("is_solid") is True and len(rows) == 1 and isinstance(handle, str) and bool(handle)
                     and isinstance(body, str) and rows[0].get("occurrence") == "PTSheet:1"
                     and rows[0].get("after") == {"light_bulb_on": False, "visible": False}
                     and f"Source '{body}' in 'PTSheet:1' became hidden. Undo it with "
                         f"view_set(action='show', target=['{handle}'])." in note
                     and "design_get" not in note)


def _thicken_placed_source_rows(write, rows):
    """A sheet in a TRANSLATED component: the thicken's source handle is the tree's, and shows it."""
    write("model_create_component", {"name": "PTSheet", "activate": True, "x": -120, "y": -120},
          _made_component)
    write("sketch_create", {"name": "PTSheetS", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "PTSheetS", "units": "mm", "geometry": [
        {"kind": "line", "x1": 0, "y1": 0, "x2": 20, "y2": 0}]})
    write("surface_extrude", {"sketch_name": "PTSheetS", "component": "PTSheet", "distance": 10,
                              "units": "mm", "operation": "new"},
          lambda p: p.get("created") is True and p.get("is_solid") is False)
    rows.append(("find_geometry", {"target": "PTSheet:1", "kind": "planar_face", "units": "mm", "max_results": 10},
                 lambda p: p.get("match_count") == p.get("returned") == 1
                 and p["matches"][0].get("position") == [-110, -120, 5] and p["matches"][0].get("area") == 200,
                 _fg("pt_face")))
    write("surface_thicken", lambda c: {"faces": [_ctx_get(c, "pt_face", "placed sheet face")], "thickness": 1,
          "units": "mm", "chaining": False, "operation": "new"}, _placed_source_thickened,
          ("pt_source_handle", _recall("pt_source_handle", lambda p: p["source_visibility"][0]["handle"])))
    tree = {"include": ["tree"], "tree_bodies": True, "tree_handles": True, "max_results": 2000}
    rows.append(("design_get", tree, _placed_sheet_visible(False), None))
    write("view_set", lambda c: {"action": "show", "target": [_ctx_get(c, "pt_source_handle", "disclosed handle")]},
          lambda p: [(b.get("light_bulb_on"), b.get("visible")) for b in p.get("bodies") or []] == [(True, True)])
    rows.append(("design_get", tree, _placed_sheet_visible(True), None))


def _thicken_visibility_rows():
    """Check two source visibility transitions and typed recovery in an owned scene."""
    rows = [("doc_get", {}, _home_document, ("thicken_home", _home_address)),
            ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True, "max_results": 2000},
             _retire_compare("thicken_home_design", _retire_design_state, False), None),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "thicken_home", "home")}, _new_document,
             ("thicken_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c: {**(args(c) if callable(args) else args),
                     "expect_document": _ctx_get(c, "thicken_doc", "owned thicken scene")}, check, save))
    for role, x in (("visible", 0), ("hidden", 30)):
        name = "Sheet_" + role
        write("sketch_create", {"name": name, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name, "units": "mm", "geometry": [
            {"kind": "line", "x1": x, "y1": 20, "x2": x + 10, "y2": 20}]})
        write("surface_extrude", {"sketch_name": name, "distance": 6, "units": "mm", "operation": "new"},
              lambda p: p.get("created") is True and p.get("is_solid") is False and len(p.get("result_bodies") or []) == 1,
              ("thicken_" + role, lambda p: p["result_bodies"][0]))
    write("sketch_create", {"name": "Witness", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "Witness", "units": "mm", "geometry": [
        {"kind": "rectangle", "x1": 60, "y1": 0, "x2": 65, "y2": 5}]})
    write("model_extrude", {"sketch_name": "Witness", "distance": 5, "units": "mm", "operation": "new"},
          _extruded, ("thicken_witness", lambda p: p["result_bodies"][0]))
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True})
    write("view_set", lambda c: {"action": "hide", "target": [_ctx_get(c, "thicken_hidden", "second sheet")]},
          lambda p: p.get("bodies") == [{"body": "Body2", "light_bulb_on": False, "visible": False}])
    def design_read(key, phase, before=None):
        def check(p):
            state = _retire_design_state(p)
            bodies = (p.get("tree") or {}).get("root_bodies")
            expected = {"Body1": (False, phase != "visible_after"), "Body2": (False, phase == "hidden_after"),
                        "Body3": (True, True)}
            if phase not in ("baseline",):
                expected["Body4"] = (True, True)
            if phase in ("hidden_after", "hidden_restored"):
                expected["Body5"] = (True, True)
            valid = (state is not None and isinstance(bodies, list) and len(bodies) == len(expected)
                     and {b.get("name") for b in bodies} == set(expected)
                     and all((b.get("is_solid"), b.get("visible")) == expected[b["name"]]
                             and isinstance(b.get("handle"), str) and b["handle"] for b in bodies)
                     and p["tree"].get("child_count") == 0)
            if before and valid:
                prior = _RECALL[before]
                old, now = prior["timeline"]["timeline"], state["timeline"]["timeline"]
                added = phase.endswith("after")
                valid = (now[:-1] == old and len(now) == len(old) + 1
                         and now[-1].get("type") == "ThickenFeature" and now[-1].get("health", "healthy") == "healthy"
                         if added else now == old)
                old_bodies = {b["name"]: b for b in prior["tree"]["root_bodies"]}
                valid = valid and all({k: v for k, v in b.items() if k != "visible"} ==
                                      {k: v for k, v in old_bodies[b["name"]].items() if k != "visible"}
                                      for b in bodies if b["name"] in old_bodies)
            _measured("source visibility with complete held body/history census", p, valid)
            _RECALL[key] = state
            return True
        def handles(p):
            return {b["name"]: b["handle"] for b in p["tree"]["root_bodies"]}
        rows.append(("design_get", lambda c: {"include": ["tree", "timeline"], "tree_bodies": True,
                     "tree_handles": True, "max_results": 2000}, check, (key, handles)))
    def controls(after):
        for role in ("visible", "hidden"):
            rows.append(("find_geometry", lambda c, role=role: {"target": _ctx_get(c, "thicken_" + role, "source sheet"),
                         "units": "mm", "max_results": 100},
                         _retire_compare("thicken_geometry_" + role, _thicken_source_geometry, after), None))
        rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "thicken_witness", "witness"),
                     "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                     _retire_compare("thicken_witness_material", _thicken_witness_material, after), None))
        def witness_geometry(p):
            geometry = _edge_extent_geometry(p)
            if (geometry is None or len(geometry) != 18
                    or sum(r["kind"] == "planar_face" for r in geometry) != 6
                    or sum(r["kind"] == "line_edge" for r in geometry) != 12):
                return None
            return geometry
        rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, "thicken_witness", "witness"),
                     "units": "mm", "max_results": 100},
                     _retire_compare("thicken_witness_geometry", witness_geometry, after), None))
    design_read("thicken_baseline", "baseline")
    controls(False)
    for role, x, body, action, before in (("visible", 0, "Body1", "show", "thicken_baseline"),
                                         ("hidden", 30, "Body2", "hide", "thicken_visible_restored")):
        rows.append(("find_geometry", lambda c, role=role: {"target": _ctx_get(c, "thicken_" + role, "source sheet"),
                     "kind": "planar_face", "units": "mm", "max_results": 10},
                     lambda p, x=x: p.get("match_count") == p.get("returned") == 1
                     and p["matches"][0].get("position") == [x + 5, 20, 3] and p["matches"][0].get("area") == 60,
                     _fg("thicken_face")))
        def landed(p, body=body, role=role, action=action):
            want_before = role == "visible"
            sources = p.get("source_visibility") or [{}]
            handle = sources[0].get("handle")
            valid = (p.get("thickened") is True and p.get("is_solid") is True and p.get("thickness") == 1
                     and len(p.get("result_bodies") or []) == 1 and isinstance(handle, str) and handle
                     and sources == [{"body": body, "face_indices": [0], "handle": handle,
                        "before": {"light_bulb_on": want_before, "visible": want_before},
                        "after": {"light_bulb_on": not want_before, "visible": not want_before}}]
                     and p.get("note", "").count(f"Source '{body}' became "
                                                 + ("hidden." if want_before else "shown.")) == 1
                     and f"Undo it with view_set(action='{action}', target=['{handle}'])." in p["note"])
            if valid:
                _RECALL["thicken_source_handle_" + role] = handle
            return bool(valid)
        write("surface_thicken", lambda c: {"faces": [_ctx_get(c, "thicken_face", "sheet face")], "thickness": 1,
              "units": "mm", "symmetric": False, "chaining": False, "operation": "new"}, landed,
              ("thicken_wall_" + role, lambda p: p["result_bodies"][0]))
        after_key = "thicken_" + role + "_after"
        design_read(after_key, role + "_after", before)
        # The handle the disclosure names is the source's own tree handle, read independently.
        rows.append(("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                                    "max_results": 2000},
                     lambda p, body=body, role=role: _measured(
                         "the disclosed source handle is the body's tree handle",
                         (p.get("tree") or {}).get("root_bodies"),
                         [b.get("handle") for b in (p.get("tree") or {}).get("root_bodies") or []
                          if b.get("name") == body] == [_RECALL.get("thicken_source_handle_" + role)]),
                     None))
        controls(True)
        def wall(p, x=x):
            state = _thicken_material(p)
            return (state is not None and _near(state["shape"]["volume"], 60, .0001)
                    and [p.get(a) for a in "xyz"] == [10, 1, 6]
                    and p.get("min_point") == {"x": x, "y": 19, "z": 0}
                    and p.get("max_point") == {"x": x + 10, "y": 20, "z": 6})
        rows.append(("model_inspect", lambda c, role=role: {"target": _ctx_get(c, "thicken_wall_" + role, "new wall"),
                     "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"}, wall, None))
        rows.append(("find_geometry", lambda c, role=role: {"target": _ctx_get(c, "thicken_wall_" + role, "new wall"), "units": "mm", "max_results": 100},
                     lambda p: _edge_extent_geometry(p) is not None and len(p["matches"]) == 18
                     and sum(r["kind"] == "planar_face" for r in p["matches"]) == 6
                     and sum(r["kind"] == "line_edge" for r in p["matches"]) == 12, None))
        write("view_set", lambda c, action=action, key=after_key, body=body: {
              "action": action, "target": [_ctx_get(c, key, "fresh tree body handles")[body]]},
              lambda p, body=body, role=role: p.get("bodies") == [{"body": body,
                  "light_bulb_on": role == "visible", "visible": role == "visible"}])
        design_read("thicken_" + role + "_restored", role + "_restored", after_key)
        controls(True)
        rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "thicken_wall_visible", "first wall control"),
                     "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                     _retire_compare("thicken_first_wall", _thicken_material, role == "hidden"), None))
    _thicken_placed_source_rows(write, rows)
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "thicken_home", "home"),
                                        "expect_document": _ctx_get(c, "thicken_doc", "owned scene")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "thicken_doc", "owned scene"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "thicken_home", "home")}, _document_closed, None),
             ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True, "max_results": 2000},
              _retire_compare("thicken_home_design", _retire_design_state, True), None)]
    return rows


_MACHINING += _thicken_visibility_rows()


def _repeat_isolate_rows():
    """A repeat isolate after a sibling was shown re-applies the isolation, judged by the tree."""
    rows = [("doc_get", {}, _home_document, ("iso_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "iso_home", "home")}, _new_document,
             ("iso_doc", lambda p: p["document_handle"]))]
    def write(tool, args, check="ok"):
        rows.append((tool, lambda c: {**args, "expect_document": _ctx_get(c, "iso_doc", "owned isolate scene")},
                     check, None))
    for name, (x1, y1, x2, y2), height in (("Tray", (0, 0, 60, 40), 10), ("Chassis", (-10, -30, 70, -10), 60)):
        write("design_activate_component", {"occurrence": "root"})
        write("model_create_component", {"name": name, "activate": True}, _made_component)
        write("sketch_create", {"plane": "xy", "name": name + "S"})
        write("sketch_add_geometry", {"sketch_name": name + "S", "geometry": [
            {"kind": "rectangle", "x1": x1, "y1": y1, "x2": x2, "y2": y2}]})
        write("model_extrude", {"sketch_name": name + "S", "component": name, "distance": height}, _extruded)
    write("design_activate_component", {"occurrence": "Tray:1"})
    write("view_set", {"action": "isolate", "target": ["Tray:1"]}, lambda p: p.get("affected") == ["Tray:1"])
    write("view_set", {"action": "show", "target": ["Chassis:1"]}, lambda p: p.get("affected") == ["Chassis:1"])
    write("design_activate_component", {"occurrence": "root"})
    # The repeat: Tray:1 already reads isolated, and the chassis shown above must not stay drawn.
    write("view_set", {"action": "isolate", "target": ["Tray:1"]}, lambda p: p.get("affected") == ["Tray:1"])
    rows += [("design_get", {"include": ["tree"], "component": "Chassis:1", "tree_bodies": True},
              _subject_visible("Chassis:1", False), None),
             ("design_get", {"include": ["tree"], "component": "Tray:1", "tree_bodies": True},
              _subject_visible("Tray:1", True), None),
             ("view_screenshot", {"view": "iso-top-right", "width": 640, "height": 480}, "ok", None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "iso_home", "home"),
                                         "expect_document": _ctx_get(c, "iso_doc", "owned isolate scene")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "iso_doc", "owned isolate scene"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "iso_home", "home")}, _document_closed, None)]
    return rows


_MACHINING += _repeat_isolate_rows()


def _disc_centre_within(label, chunk, x0, y0, half):
    """model_inspect: the disc reads under its own top-level path, centred within `half` mm of the
    authored (x0, y0) of `chunk` as the layout placed it."""
    def check(p):
        c = p.get("center") or {}
        return _measured(label, {"target": p.get("target"), "center": c},
                         "ArrP3:1" in str(p.get("target")) and _num(c.get("x")) and _num(c.get("y"))
                         and abs(c["x"] - _px(chunk, x0)) < half and abs(c["y"] - _py(chunk, y0)) < half)
    return check


def _move_originals_rows():
    """move_originals moves the disc in place on its own path; the feature only ADDS occurrences."""
    return [
        ("model_arrange", {"boundary_sketch": "ArrB", "shapes": ["ArrP3:1"], "solver": "true_shape",
                           "spacing": 2, "move_originals": True},
         lambda p: _measured("move_originals moved the input in place and listed what it added",
                             {k: p.get(k) for k in ("moved", "new_occurrences", "note")},
                             p.get("moved") == ["ArrP3:1"] and bool(p.get("new_occurrences"))
                             and "ArrP3:1" not in p["new_occurrences"]
                             and "Inputs moved on their own paths; new_occurrences lists the added "
                                 "occurrences." in (p.get("note") or "")
                             and "restructured" not in (p.get("note") or "")),
         ("arr_moved", lambda p: p["feature"])),
        # The hexagon is authored at (300, 500), radius 120 mm; the box is wide enough for either radius.
        ("model_inspect", {"target": "ArrP3:1", "units": "mm"},
         _disc_centre_within("the disc reads on ArrP3:1 inside the hexagon's box", "ArrB", 300, 500, 140), None),
        ("design_delete_feature", lambda c: {"feature": _ctx_get(c, "arr_moved", "move_originals nest")},
         "ok", None),
        ("model_inspect", {"target": "ArrP3:1", "units": "mm"},
         _disc_centre_within("the disc is back where it was drawn", "ArrP3", 350, 359, .01), None),
    ]

# ACT 7b: NESTING - model_arrange as a FUNCTION of its boundary. It runs after the
# parametric resize on purpose: the solver adds Arrange/Envelope occurrences and moves or
# copies the parts it nests, and that is not a thing to hand to an act that recomputes the
# whole assembly.
_NESTING = _box("ArrP1", ox=200, oy=350) + [
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # THREE DIFFERENT shapes to nest, not two of the same box: a square pad, a long bar and a disc.
    # A nest that only ever sees one footprint proves nothing about the solver.
    ("model_create_component", {"name": "ArrP2", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "ArrP2S"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 260, "y1": 350,
                                           "x2": 320, "y2": 368}],
                             "sketch_name": "ArrP2S"}, "ok", None),
    ("model_extrude", {"sketch_name": "ArrP2S", "profile_index": 0, "distance": 10}, _extruded, None),
    ("model_create_component", {"name": "ArrP3", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "ArrP3S"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 350, "cy": 359, "radius": 16}],
                             "sketch_name": "ArrP3S"}, "ok", None),
    ("model_extrude", {"sketch_name": "ArrP3S", "profile_index": 0, "distance": 10}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # a SECOND bar, so the nest carries repeats as well as variety - four shapes from three
    # components. The instance number is Fusion's to pick, so it is read back, never predicted.
    ("design_add_instance", {"component": "ArrP2", "x": 0, "y": -35, "units": "mm"},
     lambda p: p.get("created") is True and str(p.get("full_path", "")).startswith("ArrP2:"),
     ("arr_bar2", lambda p: p["full_path"])),
    # The boundary is a HEXAGON, not a rectangle: a true-shape nest against a slanted wall is the
    # case a box boundary cannot show. Its six lines are line:0..line:5, which is what the reshape
    # below scales.
    ("sketch_create", {"plane": "xy", "name": "ArrB"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "polygon", "cx": 300, "cy": 500,
                                           "radius": 120, "sides": 6}],
                             "sketch_name": "ArrB"},
     lambda p: p["results"][0].get("curves_added") == 6, None),
    _watch(["ArrB", "ArrP1:1", "ArrP2:1", "ArrP3:1"]),
    # THE PINNED SHAPE: a shape reading isGroundToParent True is what the solver calls "Pinned"
    # (ARRANGE_ITEM_GROUNDED, measured), so an in-place arrange refuses it BEFORE the feature, naming
    # the shape and the release; the phrase asserted is the pre-flight's own, not the platform's.
    ("assembly_ground", {"occurrence": "ArrP1:1", "ground_to_parent": True},
     lambda p: p.get("isGroundToParent") is True and bool(p.get("occurrence")), None),
    ("model_arrange", {"boundary_sketch": "ArrB", "shapes": ["ArrP1:1"], "move_originals": True},
     _refused("ArrP1:1", "read isGroundToParent True", "ground_to_parent=false"), None),
    ("assembly_ground", {"occurrence": "ArrP1:1", "ground_to_parent": False},
     lambda p: p.get("isGroundToParent") is False and bool(p.get("occurrence")), None),
    # THE ACTIVE EDIT TARGET: measured on both solvers, an arrange whose shapes include the active
    # component fails with a bare '3 :' - so the shape is refused before the feature, and the same
    # call lands once root is active again (the nest below it).
    ("design_activate_component", {"occurrence": "ArrP1:1"}, "ok", None),
    ("model_arrange", {"boundary_sketch": "ArrB", "shapes": ["ArrP1:1"]},
     _refused("ArrP1:1", "ACTIVE edit target", "design_activate_component('root')"), None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    *_move_originals_rows(),
    # TRUE-SHAPE, because the boundary is a hexagon: the rectangular solver nests bounding boxes and
    # refuses a non-rectangular envelope outright (ARRANGE_ERROR_ENVELOPE_INVALIDRECTANGULAR), which
    # is exactly what a slanted wall is for. The solver places COPIES under an Envelope occurrence
    # and leaves the named inputs where they were, so the nested part is picked out of what the call
    # PUBLISHED - and it is that copy the reshape below is measured on.
    # Every solver runs on the base licence with a boundary or an envelope and a spacing (measured
    # on the lapsed install: this nest placed 4, the sheet 3, the box 3); the platform's "Cannot
    # set extension value" is an OPTION the extension owns, which none of these rows pass.
    # The spacing is 1/64 in: 0.0396875 cm carries more decimals than the 6-place read-back.
    ("model_arrange", lambda c: {"boundary_sketch": "ArrB",
                                 "shapes": ["ArrP1:1", "ArrP2:1",
                                            _ctx_get(c, "arr_bar2", "the second bar"), "ArrP3:1"],
                                 "solver": "true_shape", "spacing": 0.015625, "units": "in"},
     lambda p: _arranged(4)(p) and _measured(
         "the 1/64 in spacing read back", {"settings": p.get("settings"), "units": p.get("units")},
         p.get("units") == "in" and (p.get("settings") or {}).get("spacing") == 0.015625),
     ("nest_disc", lambda p: next(o for o in p["new_occurrences"] if "+ArrP3:" in o))),
    ("model_inspect", lambda c: {"target": _ctx_get(c, "nest_disc", "the nested disc")},
     _extent_measured, ("nest_y0", _recall("nest_y0", lambda p: p["center"]["y"]))),
    _dwell(2.0),
    # RESHAPE the boundary: the Arrange feature RECOMPUTES off its boundary sketch, so the nest is a
    # FUNCTION of the envelope rather than a one-time placement. Solving again would not show this -
    # a second identical arrange stacks another coincident copy set (measured, and the tool says so).
    # The proof is the nested disc having MOVED, read back off its own bounding box.
    ("sketch_move", {"sketch_name": "ArrB",
                     "entities": "line:0,line:1,line:2,line:3,line:4,line:5",
                     "scale_factor": 0.65, "center_x": 300, "center_y": 500},
     lambda p: len(p.get("moved_entities") or []) == 6 and not p.get("unmoved_entities"), None),
    ("model_inspect", lambda c: {"target": _ctx_get(c, "nest_disc", "the nested disc")},
     lambda p: _measured("the nest re-solved off the smaller boundary",
                         {"y_before": _RECALL.get("nest_y0"),
                          "y_now": p.get("center", {}).get("y")},
                         abs(p["center"]["y"] - _RECALL["nest_y0"]) > 1.0), None),
    _dwell(2.0),
    # The envelope forms that need NO sketch: a sized rectangle on a plane, then the 3D packer on a
    # box. Both are judged on the feature's own arrangeStatistics - what the solver placed and what
    # it left out - which the profile nest above cannot show. A sized envelope is anchored on its
    # plane's origin, so both are offset into clear ground rather than onto the vise and the CAM
    # stock, and each nest is deleted again: these rows are about the solver, not about the field.
    # The sized rectangular sheet passes rotation and quantity, and one of those is the
    # extension's (measured on the lapsed install: "Cannot set extension value" here while the
    # boundary nest above and the 3D box below, which pass neither, place their shapes), so this
    # row rides the tier and its unentitled variant asserts the refusal names the candidates.
    ("model_arrange", {"shapes": ["ArrP1:1", "ArrP2:1", "ArrP3:1"], "solver": "rectangular",
                       "envelope_plane": "xy", "envelope_length": 300, "envelope_width": 200,
                       "envelope_origin": [600, 400], "rotation": "none", "quantity": 1,
                       "spacing": 5},
     _needs(MACHINING_EXTENSION, _packed(3, extent=(300, 200))),
     ("arr_sheet", lambda p: p["feature"])),
    ("model_arrange", {"shapes": ["ArrP1:1", "ArrP2:1", "ArrP3:1"], "solver": "rectangular",
                       "envelope_plane": "xy", "envelope_length": 300, "envelope_width": 200,
                       "envelope_origin": [600, 400], "rotation": "none", "quantity": 1,
                       "spacing": 5},
     _unless(MACHINING_EXTENSION, _refused("extension-only setting", "rotation")), None),
    ("design_delete_feature",
     lambda c: {"feature": _ctx_get(c, "arr_sheet", "the plane-envelope nest")},
     _needs(MACHINING_EXTENSION, "ok"), None),
    ("model_arrange", {"shapes": ["ArrP1:1", "ArrP2:1", "ArrP3:1"], "solver": "3d",
                       "envelope_plane": "xy", "envelope_length": 200, "envelope_width": 200,
                       "envelope_height": 100, "envelope_origin": [600, 400], "spacing": 5},
     _packed(3, extent=(200, 200, 100)), ("arr_box", lambda p: p["feature"])),
    ("design_delete_feature",
     lambda c: {"feature": _ctx_get(c, "arr_box", "the 3D nest")}, "ok", None),
    _dwell(2.0),
]


# The asymmetric occurrence-qualified mesh fixture. Its authored box is moved by the layout pass
# before the occurrence transform is applied, so every expected world bound reads through _px/_py.
_MESH_POSE = "MeshPose"
_MESH_POSE_AUTHORED = (180.0, 180.0)
_MESH_POSE_MOVE = (100.0, 40.0, 30.0)
_MESH_POSE_TOL = 0.01


def _mesh_pose_transform(bounds):
    """Bounds after Rz(90) and the fixture translation."""
    mn, mx = bounds
    points = [(x, y, z) for x in (mn[0], mx[0])
              for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
    moved = [(100.0 - y, 40.0 + x, 30.0 + z) for x, y, z in points]
    return (tuple(min(p[i] for p in moved) for i in range(3)),
            tuple(max(p[i] for p in moved) for i in range(3)))


def _mesh_pose_bounds():
    """The fixture's identity, once-transformed and double-transformed world bounds."""
    x0, y0 = _MESH_POSE_AUTHORED
    identity = ((_px(_MESH_POSE, x0), _py(_MESH_POSE, y0), 0.0),
                (_px(_MESH_POSE, x0 + 20.0), _py(_MESH_POSE, y0 + 10.0), 5.0))
    once = _mesh_pose_transform(identity)
    return identity, once, _mesh_pose_transform(once)


def _mesh_pose_points(payload):
    """The target's min/max points, normalized across BRep and mesh inspect payloads."""
    box = payload.get("bbox") if payload.get("kind") == "mesh" else payload
    box = box or {}
    out = []
    for key in ("min_point", "max_point"):
        point = box.get(key) or {}
        out.append(tuple(point.get(axis) for axis in ("x", "y", "z")))
    return tuple(out)


def _mesh_pose_bounds_match(got, expected):
    """Whether two min/max triples agree within the mesh fixture tolerance."""
    return all(_num(a) and abs(a - b) <= _MESH_POSE_TOL
               for ga, ea in zip(got, expected) for a, b in zip(ga, ea))


def _mesh_pose_body_signature(payload):
    """The source-body values that must hold across mesh conversion."""
    mass = payload.get("mass") or {}
    return (_mesh_pose_points(payload), mass.get("volume"), mass.get("area"))


def _mesh_pose_mesh_signature(payload):
    """The mesh values that must hold across occurrence and instance reads."""
    return (_mesh_pose_points(payload), payload.get("volume"), payload.get("area"),
            payload.get("triangle_count"), payload.get("node_count"),
            payload.get("is_closed"), payload.get("is_oriented"))


def _mesh_pose_body(expected, same_as=None):
    """A source-body oracle requiring exact bounds and independently read physical properties."""
    def check(p):
        mass = p.get("mass") or {}
        got = _mesh_pose_points(p)
        state = _mesh_pose_body_signature(p)
        good = (p.get("kind") == "body" and p.get("units") == "mm"
                and _mesh_pose_bounds_match(got, expected)
                and _num(mass.get("volume")) and abs(mass["volume"] - 1000.0) <= 0.01
                and _num(mass.get("area")) and abs(mass["area"] - 700.0) <= 0.01)
        if same_as:
            good = good and state == _RECALL.get(same_as)
        return _measured("MeshPose source volume, area and world bounds",
                         {"state": state, "expected_bounds": expected,
                          "same_as": same_as and _RECALL.get(same_as)}, good)
    return check


def _mesh_pose_mesh(expected, same_as=None, reject_bounds=None):
    """A mesh oracle requiring placement, closure, orientation and scalar geometry."""
    def check(p):
        got = _mesh_pose_points(p)
        state = _mesh_pose_mesh_signature(p)
        good = (p.get("kind") == "mesh" and p.get("units") == "mm"
                and _mesh_pose_bounds_match(got, expected)
                and (reject_bounds is None or not _mesh_pose_bounds_match(got, reject_bounds))
                and _num(p.get("volume")) and abs(p["volume"] - 1000.0) <= 0.01
                and _num(p.get("area")) and abs(p["area"] - 700.0) <= 0.01
                and p.get("triangle_count") == 12 and _num(p.get("node_count"))
                and p["node_count"] > 0 and p.get("is_closed") is True
                and p.get("is_oriented") is True)
        if same_as:
            good = good and state == _RECALL.get(same_as)
        return _measured("MeshPose mesh placement and geometry",
                         {"state": state, "expected_bounds": expected,
                          "rejected_bounds": reject_bounds,
                          "same_as": same_as and _RECALL.get(same_as)}, good)
    return check


def _mesh_pose_pose_signature(payload):
    """Exact pose rows for the minted MeshPose occurrence paths."""
    wanted = [p for p in (_RECALL.get("mesh_pose_first"), _RECALL.get("mesh_pose_second")) if p]
    rows = {r.get("name"): r for r in (payload.get("occurrences") or [])}
    keys = ("component", "origin", "x_axis", "y_axis", "z_axis")
    return {name: {key: rows.get(name, {}).get(key) for key in keys} for name in wanted}


def _mesh_pose_poses(first_moved=True, same_as=None):
    """A complete occurrence census with exact independent shared-instance placements."""
    def check(p):
        first = _RECALL.get("mesh_pose_first")
        other = _RECALL.get("mesh_pose_second")
        rows = {r.get("name"): r for r in (p.get("occurrences") or [])}
        expected = {
            first: ({"origin": [100.0, 40.0, 30.0],
                     "x_axis": [0.0, 1.0, 0.0], "y_axis": [-1.0, 0.0, 0.0],
                     "z_axis": [0.0, 0.0, 1.0]} if first_moved else
                    {"origin": [0.0, 0.0, 0.0],
                     "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0],
                     "z_axis": [0.0, 0.0, 1.0]}),
        }
        if other:
            expected[other] = {"origin": [0.0, 0.0, 0.0],
                               "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0],
                               "z_axis": [0.0, 0.0, 1.0]}
        signature = _mesh_pose_pose_signature(p)
        good = (first is not None and p.get("occurrences_truncated") is False
                and p.get("occurrence_count") == len(p.get("occurrences") or []))
        for name, pose in expected.items():
            row = rows.get(name) or {}
            good = (good and row.get("component") == _MESH_POSE
                    and all(row.get(key) == value for key, value in pose.items()))
        if same_as:
            good = good and signature == _RECALL.get(same_as)
        return _measured("MeshPose complete occurrence census and exact poses",
                         {"signature": signature, "expected": expected,
                          "count": p.get("occurrence_count"),
                          "returned": len(p.get("occurrences") or []),
                          "truncated": p.get("occurrences_truncated")}, good)
    return check


def _mesh_pose_census(p):
    """The complete two-mesh component census with both minted names."""
    rows = p.get("meshes") or []
    wanted = {_RECALL.get("mesh_pose_m0"), _RECALL.get("mesh_pose_m1")}
    got = {row.get("name") for row in rows}
    good = (p.get("truncated") is False and p.get("count") == len(rows) == 2
            and got == wanted and all(row.get("triangle_count") == 12 for row in rows))
    return _measured("MeshPose complete mesh census",
                     {"count": p.get("count"), "returned": len(rows),
                      "truncated": p.get("truncated"), "names": sorted(got)}, good)


def _remesh_census_state(p):
    """Return complete independently read mesh rows with comparable geometry facts."""
    rows = p.get("meshes") or []
    if (p.get("truncated") is not False or p.get("count") != len(rows) or not rows
            or any(not r.get("handle") or not r.get("name")
                   or not all(_num(r.get(k)) for k in ("triangle_count", "node_count", "area", "volume"))
                   for r in rows)):
        return None
    return rows


def _remesh_component_state(p):
    """Return complete mixed-BRep material and world bounds for the four-body remesh witness."""
    mass = p.get("mass") or {}
    rows = mass.get("per_body")
    bounds = {key: p.get(key) for key in ("frame", "box_read", "oriented", "units", "x", "y", "z",
                                         "min_point", "max_point", "center")}
    values = [p.get(axis) for axis in "xyz"]
    values += [(p.get(point) or {}).get(axis) for point in ("min_point", "max_point", "center") for axis in "xyz"]
    values += [mass.get(key) for key in ("mass_kg", "volume", "area", "density_kg_per_cm3")]
    for group, keys in (("inertia_world", ("Ixx", "Iyy", "Izz", "Ixy", "Iyz", "Ixz")),
                        ("principal_moments", ("i1", "i2", "i3")),
                        ("radius_of_gyration", ("kx", "ky", "kz")),
                        ("rotation_to_principal_rad", ("rx", "ry", "rz"))):
        values += [(mass.get(group) or {}).get(key) for key in keys]
    vectors = [mass.get("center_of_mass")]
    vectors += [(mass.get("principal_axes") or {}).get(axis) for axis in "xyz"]
    if (p.get("target") != "occurrence 'Msh:1'" or p.get("kind") != "occurrence"
            or p.get("frame") != "world axes (axis-aligned)" or p.get("units") != "mm"
            or not p.get("box_read") or p.get("oriented") is not False
            or mass.get("target") != p["target"] or mass.get("units") != "mm"
            or mass.get("accuracy") != "very_high" or mass.get("accuracy_used") != "very_high"
            or not all(_num(v) and math.isfinite(v) for v in values)
            or any(not isinstance(v, list) or len(v) != 3
                   or not all(_num(n) and math.isfinite(n) for n in v) for v in vectors)
            or not isinstance(rows, list) or mass.get("per_body_count") != len(rows) or len(rows) != 4
            or mass.get("per_body_truncated") is not False
            or mass.get("per_occurrence") != [] or mass.get("per_occurrence_count") != 0
            or mass.get("per_occurrence_truncated") is not False):
        return None
    if (not all(mass[key] > 0 for key in ("mass_kg", "volume", "area"))
            or any(not isinstance((mass.get(group) or {}).get(key), str)
                   or not mass[group][key] for group in ("inertia_world", "principal_moments")
                   for key in ("about", "units"))):
        return None
    expected = {"Body1": True, "Body2": True, "Body3": True, "Body4": False}
    if ({r.get("body") for r in rows} != set(expected)
            or any(r.get("is_solid") is not expected[r["body"]] or r.get("occurrence", "unread") is not None
                   or type(r.get("lump_count")) is not int or r["lump_count"] != 1
                   or not all(_num(r.get(key)) and math.isfinite(r[key]) and r[key] >= 0
                              and (r[key] > 0 if r["is_solid"] else True)
                              for key in ("mass_kg", "volume")) for r in rows)):
        return None
    return {"bounds": bounds, "material": {k: v for k, v in mass.items() if k != "note"}}


def _remesh_source_state(p):
    """Return readable BRep source bounds and material independently of adjacent meshes."""
    state = _mesh_pose_body_signature(p)
    if (p.get("kind") != "body" or p.get("units") != "mm"
            or not all(_num(v) for point in state[0] for v in point)
            or not all(_num(v) and v > 0 for v in state[1:])):
        return None
    return state


def _remesh_target_state(p):
    """Return readable target bounds, material, mesh counts and topology flags."""
    state = _mesh_pose_mesh_signature(p)
    if (p.get("kind") != "mesh" or p.get("units") != "mm"
            or not all(_num(v) for point in state[0] for v in point)
            or not all(_num(v) for v in state[1:5])
            or not all(type(v) is bool for v in state[5:])):
        return None
    return state


def _remesh_control_effect(name):
    """Compare the independent target geometry and every untouched mesh with their pre-call rows."""
    def check(p):
        now = _remesh_census_state(p)
        before = _RECALL.get("density_control_meshes")
        result = _RECALL.get("density_control_result") or {}
        changed = [r for r in now or [] if r.get("name") == name]
        initial = [r for r in before or [] if r.get("name") == name]
        after = result.get("after") or {}
        valid = (now is not None and before is not None and len(changed) == len(initial) == 1
                 and [r for r in now if r.get("name") != name] == [r for r in before if r.get("name") != name])
        if valid:
            row, prior = changed[0], initial[0]
            valid = (row.get("triangle_count") == after.get("triangle_count")
                     and _near(row.get("area"), after.get("area_cm2", -1) * 100, .0001)
                     and _near(row.get("volume"), after.get("volume_cm3", -1) * 1000, .001)
                     and row.get("triangle_count") > 0 and row.get("volume") > 0
                     and any(row[k] != prior[k] for k in ("triangle_count", "area", "volume")))
        return _measured("remesh target changed and other meshes stayed exact", {"name": name, "before": initial,
                         "after": changed, "reported": after}, valid)
    return check


def _remesh_control_history(p):
    """Require one new BaseFeature after a legal remesh with every prior timeline row retained."""
    now = _retire_design_state(p)
    before = _RECALL.get("density_control_design")
    result = _RECALL.get("density_control_result") or {}
    timeline = (now or {}).get("timeline") or {}
    rows = timeline.get("timeline") or []
    summary = timeline.get("summary") or {}
    prior_summary = ((before or {}).get("timeline") or {}).get("summary") or {}
    expected_states = dict(prior_summary.get("states") or {})
    expected_states["healthy"] = expected_states.get("healthy", 0) + 1
    return _measured("one legal-remesh BaseFeature with prior history retained", timeline,
                     now is not None and before is not None
                     and timeline.get("count") == before["timeline"]["count"] + 1
                     and rows[:-1] == before["timeline"]["timeline"]
                     and rows[-1].get("name") == result.get("base_feature")
                     and rows[-1].get("type") == "BaseFeature"
                     and rows[-1].get("health", "healthy") == "healthy"
                     and rows[-1].get("is_suppressed", False) is False
                     and summary.get("states") == expected_states
                     and isinstance(prior_summary.get("exceptions"), list)
                     and summary.get("exceptions") == prior_summary["exceptions"])


def _remesh_density_rows():
    """Exercise negative-density preservation and zero/omitted/positive native controls."""
    rows = []
    for name in ("MDensityZero", "MDensityOmitted", "MDensityPositive"):
        rows.append(("save_as_mesh", lambda c, name=name: {
            "body": _ctx_get(c, "cyl_body", "cylinder source"), "name": name, "quality": "low"}, "ok", None))
    rows.extend(_retire_reads("density_refusal", ["Msh:1"], [], material_read=_remesh_component_state))
    def source_reads(after):
        return [("model_inspect", {"target": target,
                    "include": ["default", "mass"], "accuracy": "very_high", "units": "mm"},
                 _retire_compare("density_source_" + key, _remesh_source_state, after), None)
                for key, target in (("cylinder", "Msh:1:Body2"), ("box", "Msh:1:Body1"))]
    rows.extend(source_reads(False))
    rows.extend([
        ("mesh_get", {"target": "Msh"}, _retire_compare("density_refusal_meshes", _remesh_census_state, False), None),
        ("model_inspect", {"target": "MC", "units": "mm"},
         _retire_compare("density_refusal_target", _remesh_target_state, False), None),
        ("mesh_remesh", {"mesh": "MC", "density": -1}, _refused("density=-1 is negative", "0 for the API default"), None),
        # A non-number reaches the handler (the transport types only Booleans) and is refused there,
        # not run as the default remesh; the reads below find both refusals changed nothing.
        ("mesh_remesh", {"mesh": "MC", "density": "fine"},
         _refused("density='fine' is not a number", "0 for the API default"), None),
        ("mesh_get", {"target": "Msh"}, _retire_compare("density_refusal_meshes", _remesh_census_state, True), None),
        ("model_inspect", {"target": "MC", "units": "mm"},
         _retire_compare("density_refusal_target", _remesh_target_state, True), None),
    ])
    rows.extend(_retire_reads("density_refusal", ["Msh:1"], [], after=True, material_read=_remesh_component_state))
    rows.extend(source_reads(True))
    for name, density in (("MDensityZero", 0), ("MDensityOmitted", None), ("MDensityPositive", 1)):
        args = {"mesh": name}
        if density is not None:
            args["density"] = density
        rows.extend([
            ("mesh_get", {"target": "Msh"}, _retire_compare("density_control_meshes", _remesh_census_state, False), None),
            ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                "max_depth": 10, "max_results": 2000}, _retire_compare("density_control_design", _retire_design_state, False), None),
            ("mesh_remesh", args, lambda p, density=density: p.get("remeshed") is True
                and p.get("design_mode") == "parametric" and bool(p.get("base_feature"))
                and (p.get("density_applied") == density if density == 1 else "density_applied" not in p),
             ("density_control_result", _recall("density_control_result", lambda p: p))),
            ("mesh_get", {"target": "Msh"}, _remesh_control_effect(name), None),
            ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                "max_depth": 10, "max_results": 2000}, _remesh_control_history, None),
        ])
        rows.extend(source_reads(True))
    return rows


# ACT 7: MESH - a scratch solid becomes a mesh, then the mesh family works it (one mesh per op).
_MESH = [
    # A fresh asymmetric 20 x 10 x 5 mm source: identity conversion is the control, then the
    # occurrence moves through the reproduced Rz90 + [100,40,30] pose before a qualified conversion.
    ("model_create_component", {"name": _MESH_POSE, "activate": True}, _made_component,
     ("mesh_pose_first", _recall("mesh_pose_first", lambda p: p["full_path"]))),
    ("sketch_create", {"plane": "xy", "name": _MESH_POSE + "S"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle",
                                           "x1": _MESH_POSE_AUTHORED[0],
                                           "y1": _MESH_POSE_AUTHORED[1],
                                           "x2": _MESH_POSE_AUTHORED[0] + 20.0,
                                           "y2": _MESH_POSE_AUTHORED[1] + 10.0}],
                             "sketch_name": _MESH_POSE + "S"}, "ok", None),
    ("model_extrude", {"sketch_name": _MESH_POSE + "S", "profile_index": 0, "distance": 5},
     _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("find_geometry", lambda c: {"target": _ctx_get(c, "mesh_pose_first", "first occurrence"),
                                 "kind": "planar_face", "max_results": 1},
     "ok", _fg("mesh_pose_body")),
    ("model_inspect", lambda c: {
        "target": _ctx_get(c, "mesh_pose_first", "first occurrence") + ":Body1",
        "include": ["default", "mass"], "accuracy": "very_high", "units": "mm"},
     lambda p: _mesh_pose_body(_mesh_pose_bounds()[0])(p),
     ("mesh_pose_source_identity",
      _recall("mesh_pose_source_identity", _mesh_pose_body_signature))),
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "mesh_pose_body", "source body"),
                                "name": "MeshPoseM0", "quality": "low"},
     lambda p: _measured("MeshPose identity conversion",
                         {"name": p.get("name"), "component": p.get("component"),
                          "source_body": p.get("source_body"),
                          "triangle_count": p.get("triangle_count")},
                         p.get("component") == _MESH_POSE and p.get("source_body") == "Body1"
                         and p.get("name") == "MeshPoseM0"
                         and p.get("triangle_count") == 12),
     ("mesh_pose_m0", _recall("mesh_pose_m0", lambda p: p["name"]))),
    ("model_inspect", lambda c: {
        "target": (_ctx_get(c, "mesh_pose_first", "first occurrence") + ":"
                   + _ctx_get(c, "mesh_pose_m0", "identity mesh")),
        "units": "mm"}, lambda p: _mesh_pose_mesh(_mesh_pose_bounds()[0])(p),
     ("mesh_pose_m0_identity",
      _recall("mesh_pose_m0_identity", _mesh_pose_mesh_signature))),
    # Create the shared placement while the first is still at identity. Fusion then keeps the
    # second at identity when only the first occurrence is released and moved.
    ("design_add_instance", lambda c: {
        "component": _ctx_get(c, "mesh_pose_first", "first occurrence")},
     lambda p: p.get("created") is True and p.get("component") == _MESH_POSE,
     ("mesh_pose_second", _recall("mesh_pose_second", lambda p: p["full_path"]))),
    ("assembly_get", {"include": ["poses"], "max_occurrences": 200, "units": "mm"},
     _mesh_pose_poses(first_moved=False), None),
    ("assembly_ground", lambda c: {
        "occurrence": _ctx_get(c, "mesh_pose_first", "first occurrence"),
        "ground_to_parent": False},
     lambda p: p.get("isGroundToParent") is False, None),
    ("assembly_move", lambda c: {
        "occurrence": _ctx_get(c, "mesh_pose_first", "first occurrence"),
        "rotate_deg": 90, "rotate_axis": "z", "units": "mm"},
     lambda p: p.get("moved") is True and p.get("rotate_deg") == 90.0
     and p.get("rotate_axis") == "z", None),
    ("assembly_move", lambda c: {
        "occurrence": _ctx_get(c, "mesh_pose_first", "first occurrence"),
        "dx": _MESH_POSE_MOVE[0], "dy": _MESH_POSE_MOVE[1], "dz": _MESH_POSE_MOVE[2],
        "units": "mm"},
     lambda p: _measured("MeshPose translated occurrence pose",
                         {"position": p.get("position"), "translation": p.get("translation")},
                         p.get("moved") is True
                         and p.get("position") == {"x": 100.0, "y": 40.0, "z": 30.0}),
     None),
    ("assembly_capture_position", {"action": "capture"}, _captured, None),
    ("assembly_get", {"include": ["poses"], "max_occurrences": 200, "units": "mm"},
     _mesh_pose_poses(),
     ("mesh_pose_pose_before",
      _recall("mesh_pose_pose_before", _mesh_pose_pose_signature))),
    ("model_inspect", lambda c: {
        "target": _ctx_get(c, "mesh_pose_first", "first occurrence") + ":Body1",
        "include": ["default", "mass"], "accuracy": "very_high", "units": "mm"},
     lambda p: _mesh_pose_body(_mesh_pose_bounds()[1])(p),
     ("mesh_pose_source_moved",
      _recall("mesh_pose_source_moved", _mesh_pose_body_signature))),
    ("model_inspect", lambda c: {
        "target": (_ctx_get(c, "mesh_pose_first", "first occurrence") + ":"
                   + _ctx_get(c, "mesh_pose_m0", "identity mesh")),
        "units": "mm"}, lambda p: _mesh_pose_mesh(_mesh_pose_bounds()[1])(p),
     ("mesh_pose_m0_moved",
      _recall("mesh_pose_m0_moved", _mesh_pose_mesh_signature))),
    ("save_as_mesh", lambda c: {
        "body": _ctx_get(c, "mesh_pose_first", "first occurrence") + ":Body1",
        "name": "MeshPoseM1", "quality": "low"},
     lambda p: _measured("MeshPose occurrence-qualified conversion",
                         {"name": p.get("name"), "component": p.get("component"),
                          "source_body": p.get("source_body"),
                          "triangle_count": p.get("triangle_count")},
                         p.get("component") == _MESH_POSE and p.get("source_body") == "Body1"
                         and p.get("name") == "MeshPoseM1"
                         and p.get("triangle_count") == 12),
     ("mesh_pose_m1", _recall("mesh_pose_m1", lambda p: p["name"]))),
    ("model_inspect", lambda c: {
        "target": (_ctx_get(c, "mesh_pose_first", "first occurrence") + ":"
                   + _ctx_get(c, "mesh_pose_m1", "qualified mesh")),
        "units": "mm"},
     lambda p: _mesh_pose_mesh(_mesh_pose_bounds()[1],
                               reject_bounds=_mesh_pose_bounds()[2])(p), None),
    ("mesh_get", lambda c: {
        "target": _ctx_get(c, "mesh_pose_first", "first occurrence"),
        "max_results": 10, "units": "mm"}, _mesh_pose_census, None),
    # Fresh independent reads prove conversion did not move the source, M0 or the captured pose.
    ("model_inspect", lambda c: {
        "target": _ctx_get(c, "mesh_pose_first", "first occurrence") + ":Body1",
        "include": ["default", "mass"], "accuracy": "very_high", "units": "mm"},
     lambda p: _mesh_pose_body(_mesh_pose_bounds()[1], "mesh_pose_source_moved")(p), None),
    ("model_inspect", lambda c: {
        "target": (_ctx_get(c, "mesh_pose_first", "first occurrence") + ":"
                   + _ctx_get(c, "mesh_pose_m0", "identity mesh")),
        "units": "mm"},
     lambda p: _mesh_pose_mesh(_mesh_pose_bounds()[1], "mesh_pose_m0_moved")(p), None),
    ("assembly_get", {"include": ["poses"], "max_occurrences": 200, "units": "mm"},
     _mesh_pose_poses(same_as="mesh_pose_pose_before"), None),
    # Mesh bodies belong to the component: the independent second placement sees the same M1 at
    # identity, while the first placement remains at its captured rotated and translated pose.
    ("model_inspect", lambda c: {
        "target": _ctx_get(c, "mesh_pose_second", "second occurrence") + ":Body1",
        "include": ["default", "mass"], "accuracy": "very_high", "units": "mm"},
     lambda p: _mesh_pose_body(_mesh_pose_bounds()[0], "mesh_pose_source_identity")(p), None),
    ("model_inspect", lambda c: {
        "target": (_ctx_get(c, "mesh_pose_second", "second occurrence") + ":"
                   + _ctx_get(c, "mesh_pose_m1", "qualified mesh")),
        "units": "mm"}, lambda p: _mesh_pose_mesh(_mesh_pose_bounds()[0])(p), None),
    ("model_inspect", lambda c: {
        "target": _ctx_get(c, "mesh_pose_first", "first occurrence") + ":Body1",
        "include": ["default", "mass"], "accuracy": "very_high", "units": "mm"},
     lambda p: _mesh_pose_body(_mesh_pose_bounds()[1], "mesh_pose_source_moved")(p), None),
    ("model_inspect", lambda c: {
        "target": (_ctx_get(c, "mesh_pose_first", "first occurrence") + ":"
                   + _ctx_get(c, "mesh_pose_m1", "qualified mesh")),
        "units": "mm"},
     lambda p: _mesh_pose_mesh(_mesh_pose_bounds()[1],
                               reject_bounds=_mesh_pose_bounds()[2])(p), None),
    ("assembly_get", {"include": ["poses"], "max_occurrences": 200, "units": "mm"},
     _mesh_pose_poses(same_as="mesh_pose_pose_before"), None),
    ("model_create_component", {"name": "Msh", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "MshS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 200, "y1": 300,
                                           "x2": 220, "y2": 320}],
                             "sketch_name": "MshS"}, "ok", None),
    # FRAME BEFORE THE FIRST BODY, on the sketch that is about to become one. The automatic camera
    # row lands on a chunk's first body, which means the body appears while the camera is still on
    # whatever the previous act was doing - and this act's sketch was drawn back in the sketch phase,
    # so nothing has brought the camera here since. Framing the sketch first is what makes the mesh
    # source appear IN shot instead of somewhere off screen.
    _watch("MshS"),
    ("model_extrude", {"sketch_name": "MshS", "profile_index": 0, "distance": 10}, _extruded, None),
    # THE ONE FRAME THE WHOLE FAMILY PLAYS IN. Every mesh below is cast from a body inside Msh, and
    # none of those steps makes a sketch or a component, so the framing pass adds no row of its own
    # and nothing moves the camera off this shot.
    _watch("Msh:1"),
    ("find_geometry", {"target": "Msh", "kind": "planar_face", "nearest_to": [210, 310, 10], "max_results": 1}, "ok", _fg("msh_body")),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 5, "name": "MshMid"},
     _datum_plane("xy"), None),
    ("sketch_create", {"plane": "xy", "name": "MshCyl"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 260, "cy": 360,
                                           "radius": 15}],
                             "sketch_name": "MshCyl"}, "ok", None),
    ("model_extrude", {"sketch_name": "MshCyl", "profile_index": 0, "distance": 20},
     lambda p: _extruded(p) and len(p.get("result_bodies") or []) == 1,
     ("cyl_brep", lambda p: "Msh:1:" + p["result_bodies"][0])),
    ("find_geometry", {"target": "Msh", "kind": "cylinder_face", "nearest_to": [260, 360, 10], "max_results": 1}, "ok", _fg("cyl_body")),
] + _refinement_rows() + [
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "cyl_body", "cyl body"), "name": "MRED", "quality": "high"}, "ok", None),
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MA", "quality": "low"}, "ok", None),
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MC", "quality": "low"}, "ok", None),
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MD", "quality": "low"}, "ok", None),
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "ME", "quality": "low"}, "ok", None),
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MF", "quality": "low"}, "ok", None),
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MOPEN", "quality": "low"}, "ok", None),
    ("mesh_get", {"target": "Msh"}, "ok", None),
    # The closed one-group mesh reproduces the measured prismatic refusal. Read history on both
    # sides because the failed scoped add can retain a finished BaseFeature.
    ("design_get", {"include": ["timeline"], "max_results": 2000},
     _failed_mesh_scope_timeline, None),
    ("mesh_to_brep", {"mesh": "MA", "method": "prismatic"},
     _refused("meshConvertFeatures.add raised", "mesh_generate_face_groups",
              "design_get(include=['timeline'])", "design_delete_feature"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000},
     lambda p: _failed_mesh_scope_timeline(p, True), None),
    ("mesh_get", {"target": "Msh"}, _organic_source_retained, None),
    # MA is a box cast to mesh, measured to segment 1 -> 6 groups under 'fast', so THIS row's
    # generation must move the count - a payload reporting no movement here is a generation that
    # did nothing. (The tool passes no verdict of its own: one flat region segments into one group.)
    ("mesh_generate_face_groups", {"mesh": "MA", "method": "fast"},
     lambda p: (p["generated"] is True and p["changed"] is True
                and p["face_group_count"] > p["face_group_count_before"]), None),
    # The enum is API availability only; method presence does not establish extension access.
    # Read the source back before the faceted control.
    ("mesh_to_brep", {"mesh": "MA", "method": "organic", "accuracy": "low",
                       "operation": "base_feature"},
     _refused("Could not configure the mesh-convert input: 3 : For organic mesh conversion "
              "design extension must be available."), None),
    ("mesh_get", {"target": "Msh"}, _organic_source_retained, None),
    # the converted bodies are the component's BRep census differenced across the add; a row with no
    # handle is a body the next tool cannot address, and 'design_mode' is read before the scope opens.
    # This faceted follow-up recovers the measured organic refusal on installations without access.
    ("mesh_to_brep", {"mesh": "MA", "method": "faceted", "operation": "base_feature"},
     lambda p: (bool(p["brep_bodies"]) and all(b["handle"] for b in p["brep_bodies"])
                and p["method"] == "faceted" and p["design_mode"] == "parametric"), None),
    # THE OPEN HALF: 'none' leaves the cut face unfilled, so the trimmed mesh is not watertight.
    ("mesh_plane_cut", {"mesh": "MOPEN", "plane": "MshMid", "cut_type": "trim", "fill": "none"},
     lambda p: p.get("fill") == "none" and p.get("triangles_before") and p.get("triangles_after")
     and (p["triangles_after"] != p["triangles_before"]
          or p.get("volume_after_cm3") != p.get("volume_before_cm3")), None),
    # the independent read that says WHY the convert below lands a surface rather than a solid.
    ("mesh_get", {"target": "Msh"},
     lambda p: _measured("the trimmed half reads open",
                         {"rows": [[m.get("name"), m.get("is_closed")] for m in p["meshes"]]},
                         any(m.get("name") == "MOPEN" and m.get("is_closed") is False
                             for m in p["meshes"])), None),
    # prismatic on an open mesh is unmeasured, so it still refuses - naming the repair that closes a
    # hole, which is what makes the refusal actionable. It runs first: it mutates nothing.
    ("mesh_to_brep", {"mesh": "MOPEN", "method": "prismatic"},
     _refused("NOT watertight", "mesh_repair(repair_type='close_holes')"), None),
    # MEASURED: the faceted convert of an OPEN mesh builds a SURFACE body - the watertight guard
    # refuses only the two methods that were never measured on one. is_solid and face_count are read
    # off the produced body, so a solid here is the wrong body published under the right count.
    ("mesh_to_brep", {"mesh": "MOPEN", "method": "faceted", "operation": "base_feature"},
     lambda p: _measured("faceted convert of an open mesh",
                         {"brep_bodies": p.get("brep_bodies"), "note": p.get("note")},
                         bool(p["brep_bodies"])
                         and all(b["is_solid"] is False and (b["face_count"] or 0) > 0
                                 for b in p["brep_bodies"])
                         and "SURFACE" in (p.get("note") or "")), None),
    # both triangle counts are read off the model; 'reduced_pct' is published only where both read,
    # so an after-count that would not read is caught here rather than passing as a reduce.
    ("mesh_reduce", {"mesh": "MRED", "target": "proportion", "value": 50},
     lambda p: (p["after"]["triangle_count"] < p["before"]["triangle_count"]
                and (p.get("reduced_pct") or 0) > 0), None),
    # 'density' is set-then-read-back off the input (a build that drops it refuses), and the
    # before/after triangle counts are read off the model - 'changed' is null when either count
    # could not be read at all, which is a remesh nothing was measured about.
    *_remesh_density_rows(),
    ("mesh_remesh", {"mesh": "MC", "density": 1},
     lambda p: p.get("density_applied") == 1 and (p["after"]["triangle_count"] or 0) > 0
     and p.get("changed") is not None, None),
    # the cut's own effect evidence, mirrored into the receipt: the triangle count moved, or (a
    # fill that replaces as many triangles as it removed) the mesh's area/volume did.
    ("mesh_plane_cut", {"mesh": "MD", "plane": "MshMid", "cut_type": "trim"},
     lambda p: p.get("fill") == "minimal" and p.get("triangles_before") and p.get("triangles_after")
     and (p["triangles_after"] != p["triangles_before"]
          or p.get("volume_after_cm3") != p.get("volume_before_cm3")), None),
    # a parametric mesh write reports the MODE it ran in and the base feature it opened to run
    # there: the scope is what a parametric design requires, and the payload names both.
    # 'algorithm' is the input's read-back; no feature comes back to say which algorithm ran.
    ("mesh_combine", {"target": "ME", "tools": ["MF"], "operation": "join"},
     lambda p: _measured("combine names its algorithm as an input read-back",
                         {k: p.get(k) for k in ("design_mode", "base_feature", "algorithm_source", "note")},
                         p.get("design_mode") == "parametric" and bool(p.get("base_feature"))
                         and p.get("algorithm_source") == "input_readback"
                         and "the algorithm that ran is not confirmed." in (p.get("note") or "")
                         and "fewer triangles" not in (p.get("note") or "")), None),
    # a pristine scratch mesh deleted with the survivor check: the payload's own claim is the
    # re-scan. A mesh another feature already transformed (e.g. the plane-cut MD) carries a
    # different lineage; this beat exercises the plain-delete contract.
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MDEL",
                                "quality": "low"}, "ok", None),
    # 'deleted_via' names the branch the design's own mode chose - a parametric delete leaves an
    # undoable MeshRemoveFeature - and 'remaining_meshes' is the design-wide re-scan behind it.
    ("mesh_delete", {"mesh": "MDEL"},
     lambda p: (p["deleted"] == "MDEL" and p["deleted_via"] == "meshRemoveFeatures"
                and isinstance(p["remaining_meshes"], int)), None),
    # execute() answers true while writing nothing, so the file's own size is the read-back - and
    # it is the same file the mesh_insert beat below re-imports.
    ("mesh_export", {"target": "MA", "file_path": EXPORT_DIR + "/eval_mesh", "format": "stl"},
     lambda p: (p.get("size_bytes") or 0) > 0 and p.get("file_exists") is True, None),
    # THE RE-IMPORT GETS ITS OWN COMPONENT, and the mesh act goes back to Msh afterwards.
    # mesh_insert does NOT land the mesh where the file's own geometry sits: measured on the live
    # document, a mesh exported from (770,875) came back at (30,34) - near the world origin, a metre
    # from every other body in Msh. Inside Msh that one stray body stretched the component's
    # bounding box to 815 x 916 mm, so every camera row framing 'Msh:1' fitted THAT instead of the
    # 75 mm of mesh work, and the whole mesh act was watched from the far zoom.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "MshIn", "activate": True}, _made_component, None),
    # units='mm' because that is what the FILE holds: the mesh_export beat above named no unit, and
    # mesh_export's stl_units default is mm. Stated rather than left to mesh_insert's own default,
    # so the round trip below pins mesh_export's default alone - reading it back at mesh_insert's
    # default too would pass on any pair of defaults that happen to match. Importing the file
    # at the wrong unit divides every coordinate by 25.4, and a mesh a fortieth of its size lands a
    # fortieth of its distance from the origin too - measured, near the world origin and inside
    # whatever is parked there, not out on the field where it was exported from. The size read-back
    # below is what makes that a failure instead of a surprise.
    # the row is the imported body read back: the name it answers to (a dedupe leaves the model_inspect
    # below naming a mesh that is not this one) and a triangle count off the mesh itself.
    # target_component is the OCCURRENCE PATH 'MshIn:1', not a bare component name - the typed
    # occurrence kind this input resolves through accepts that spelling every other tool does.
    ("mesh_insert", {"file_path": EXPORT_DIR + "/eval_mesh.stl", "name": "MshIns",
                     "units": "mm", "target_component": "MshIn:1"},
     lambda p: (len(p["bodies"]) == 1 and p["bodies"][0]["name"] == "MshIns"
                and (p["bodies"][0]["triangle_count"] or 0) > 0
                and p.get("name_applied") is True
                and "rename_warning" not in p), None),
    # the round trip measured END TO END: the re-imported mesh is the size of the mesh that was
    # written - measured 74.99 x 74.99 x 20.0 on a finished run. A size, not a position: the layout
    # moves the bench, and 25.4 is the only thing this is looking for.
    ("model_inspect", {"target": "MshIns"}, _mesh_round_trip(75.0, 20.0), None),
    ("design_activate_component", {"occurrence": "Msh:1"}, "ok", None),
    # repair on a HEALTHY mesh: nothing of that kind to fix is an honest success, not a failure, and
    # the payload must say so rather than claim a repair. Then a rebuild, whose density is read back
    # off the feature's own parameter - the request is never echoed.
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MFIX",
                                "quality": "low"}, "ok", None),
    ("mesh_repair", {"mesh": "MFIX", "repair_type": "one_touch_fix"},
     lambda p: p.get("repaired") is True and p.get("watertight") is True, None),
    ("mesh_repair", {"mesh": "MFIX", "repair_type": "rebuild", "rebuild_method": "fast",
                     "density": 32},
     lambda p: p.get("density") == 32.0 and "density_unverified" not in p, None),
    # the rest of the rebuild vocabulary on the same mesh - each method re-triangulates it a
    # different way, and each row reads its own density back off the feature's ModelParameter rather
    # than echoing the request, so a method that quietly fell back to another is visible.
    ("mesh_repair", {"mesh": "MFIX", "repair_type": "rebuild",
                     "rebuild_method": "preserve_sharp_edges", "density": 40},
     _rebuilt("preserve_sharp_edges", 40.0), None),
    # 'offset' is accepted by the accurate method ALONE - it is the deviation that method solves to.
    ("mesh_repair", {"mesh": "MFIX", "repair_type": "rebuild", "rebuild_method": "accurate",
                     "density": 48, "offset": 0.2}, _rebuilt("accurate", 48.0), None),
    ("mesh_repair", {"mesh": "MFIX", "repair_type": "rebuild", "rebuild_method": "blocky",
                     "density": 24}, _rebuilt("blocky", 24.0), None),
    ("mesh_repair", {"mesh": "MFIX", "repair_type": "rebuild", "rebuild_method": "adaptive",
                     "density": 32}, _rebuilt("adaptive", 32.0), None),
    ("mesh_repair", {"mesh": "MFIX", "repair_type": "rebuild",
                     "rebuild_method": "adaptive_preserve_sharp_edges", "density": 32},
     _rebuilt("adaptive_preserve_sharp_edges", 32.0), None),
    # the offset/method pairing, refused rather than dropped, on the method it does not belong to.
    ("mesh_repair", {"mesh": "MFIX", "repair_type": "rebuild", "rebuild_method": "blocky",
                     "density": 24, "offset": 0.2}, "refused", None),
    # 'wrap' shrink-wraps the mesh closed. It is not a rebuild, so it takes none of the rebuild
    # knobs - handing it one is refused by name.
    ("mesh_repair", {"mesh": "MFIX", "repair_type": "wrap"},
     lambda p: p.get("repaired") is True and p.get("repair_type") == "wrap", None),
    ("mesh_repair", {"mesh": "MFIX", "repair_type": "close_holes", "density": 32}, "refused", None),
    # A repair that finds nothing of its kind is an honest success, and the payload has to say so
    # rather than claim a repair - 'changed' empty is that statement. A mesh straight out of
    # save_as_mesh is NOT that fixture: the first stitch_and_remove on it measurably moves the
    # counts (it has duplicate vertices to weld), so the no-op case is the SECOND call, once the
    # first has done the welding. That also makes the beat an idempotence check.
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MSTITCH",
                                "quality": "low"}, "ok", None),
    ("mesh_repair", {"mesh": "MSTITCH", "repair_type": "stitch_and_remove"},
     lambda p: p.get("repaired") is True, None),
    ("mesh_repair", {"mesh": "MSTITCH", "repair_type": "stitch_and_remove"}, _repair_no_op, None),
    # mesh_shell hollows the SAME body in place and re-triangulates it: the payload's before/after
    # counts and the volume DROP are the verdict, and the thickness is read off the feature.
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MSHL",
                                "quality": "low"}, "ok", None),
    # 'hollowed' needs BOTH a volume drop and a body that still reads watertight - a shell that lost
    # the closure reports the same drop for the opposite reason, so the flag pair is the verdict.
    ("mesh_shell", {"mesh": "MSHL", "thickness": 2, "units": "mm"},
     lambda p: p.get("hollowed") is True and abs(p.get("thickness", 0) - 2.0) < 1e-6
     and p.get("watertight") is True
     and p.get("volume_change", 0) < 0 and "volume" in (p.get("changed") or []), None),
    ("mesh_shell", {"mesh": "MSHL", "thickness": -2}, "refused", None),
    # a thickness thicker than half the thinnest wall does NOT quietly cut through: the platform
    # refuses the shell outright ([F50] - measured on a closed cube), and the tool hands that
    # compute failure on by name instead of reporting a hollow that never happened. The box is
    # 10 mm through its thinnest axis, so 6 mm is past the half-wall.
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MSHL2",
                                "quality": "low"}, "ok", None),
    ("mesh_shell", {"mesh": "MSHL2", "thickness": 6, "units": "mm"},
     _refused("MESH_FAILED_HOLLOW"), None),
    # mesh_smooth: the node coordinates move. nodes_moved > 0 is the gate - the counts holding
    # still is measured on a 12-triangle box only, so it is NOT asserted here.
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "cyl_body", "cyl body"), "name": "MSMO",
                                "quality": "high"}, "ok", None),
    ("mesh_smooth", {"mesh": "MSMO", "smoothness": 0.05},
     lambda p: p.get("nodes_moved", 0) > 0 and abs(p.get("smoothness", 0) - 0.05) < 1e-6, None),
    ("mesh_smooth", {"mesh": "MSMO", "smoothness": 1.5}, "refused", None),
    # A 'merge' combine of two DISJOINT meshes yields ONE body holding TWO shells, which the
    # separate then takes apart: measured 24 triangles in, two 12-triangle pieces out.
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MSEPA",
                                "quality": "low"}, "ok", None),
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "cyl_body", "cyl body"), "name": "MSEPB",
                                "quality": "low"}, "ok", None),
    ("mesh_combine", {"target": "MSEPA", "tools": ["MSEPB"], "operation": "merge"}, "ok", None),
    ("mesh_separate", {"mesh": "MSEPA"},
     lambda p: p.get("piece_count", 0) >= 2 and len(p.get("pieces") or []) >= 2, None),
    # mesh_reverse_normal: the signed volume changes sign; is_closed / is_oriented do not move.
    ("save_as_mesh", lambda c: {"body": _ctx_get(c, "msh_body", "box body"), "name": "MREV",
                                "quality": "low"}, "ok", None),
    ("mesh_reverse_normal", {"mesh": "MREV"},
     lambda p: p.get("reversed") is True
     and (p.get("volume_sign_flipped") is True or p.get("normals_negated") is True), None),
    # MeshBody.name IS settable ([F37]): the rename lands on the mesh kind, and a FRESH fetch of the
    # component's meshes - not the wrapper the write held - is what proves it stuck.
    ("design_set_name", {"target": "MREV", "new_name": "MeshRenamed"},
     lambda p: p.get("kind") == "mesh" and p.get("name") == "MeshRenamed"
     and p.get("previous_name") == "MREV", None),
    ("mesh_get", {"target": "Msh", "max_results": 100},
     lambda p: any(m.get("name") == "MeshRenamed" for m in (p.get("meshes") or [])), None),
    # THE QUALIFIED ADDRESS, on a component this document places ONCE. Fusion names the first body
    # of every component 'Body1', so the bare name reaches several of them and is refused with the
    # candidate list; the '<occurrence>:<body>' spelling that refusal offers picks Msh's own.
    ("save_as_mesh", {"body": "Body1", "name": "MQUAL", "quality": "low"},
     _refused("is ambiguous - it names",
              "qualified '<occurrence-or-component>:<body>' names"), None),
    ("save_as_mesh", {"body": "Msh:1:Body1", "name": "MQUAL", "quality": "low"},
     lambda p: _measured("the qualified source address reached Msh's own body",
                         {"component": p.get("component"), "source_body": p.get("source_body"),
                          "name": p.get("name"), "triangle_count": p.get("triangle_count")},
                         p.get("component") == "Msh" and p.get("source_body") == "Body1"
                         and p.get("name") == "MQUAL" and _num(p.get("triangle_count"))
                         and p["triangle_count"] > 0), None),
    # ...and the MESH under the same spelling. A mesh belongs to the COMPONENT rather than to a
    # placement, so the address is answered through the placed component - and the facts read back
    # are the mesh's own, not the source solid's.
    ("model_inspect", {"target": "Msh:1:MQUAL"},
     lambda p: _measured("the mesh's own facts under its '<occurrence>:<mesh>' address",
                         {"kind": p.get("kind"), "name": p.get("name"),
                          "triangle_count": p.get("triangle_count"), "volume": p.get("volume"),
                          "is_closed": p.get("is_closed")},
                         p.get("kind") == "mesh" and p.get("name") == "MQUAL"
                         and _num(p.get("triangle_count")) and p["triangle_count"] > 0), None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
]

_MESH += _mesh_remedy_rows()


# name -> (primitive, cage faces, solid, half extents in mm, volume cm3 or None for the open plane)
_NATIVE_FORMS = {
    "W3Sphere": ({"shape": "sphere", "size": [10], "spans": [8, 8]}, 64, True, (10, 10, 10),
                 4.182580493),
    "W3Torus": ({"shape": "torus", "size": [20, 5], "spans": [8, 4]}, 32, True, (25, 25, 5),
                9.570318357),
    "W3Quadball": ({"shape": "quadball", "size": [10], "spans": [2]}, 24, True, (10, 10, 10),
                   4.173558535),
    "W3Plane": ({"shape": "plane", "size": [20, 10], "spans": [2, 2]}, 4, False, (10, 5, 0), None),
}


def _native_form_made(name):
    """form_create: Fusion's own primitive, checked by faces, solidity and box, at its size."""
    _prim, faces, solid, _half, volume = _NATIVE_FORMS[name]

    def check(p):
        facts = {k: p.get(k) for k in ("created", "is_solid", "readback", "volume_cm3", "area_cm2")}
        facts["cage_faces"] = (p.get("cage") or {}).get("faces")
        return _measured(f"native Form {name}", facts,
                         p.get("created") is True and p.get("is_solid") is solid
                         and facts["cage_faces"] == faces
                         and p.get("readback") == "faces, solidity and box"
                         and (_near_rel(p.get("volume_cm3"), volume) if solid
                              else _near(p.get("area_cm2"), 2.0, 1e-6)))
    return check


def _native_form_box(name, x_mm):
    """model_inspect: the Form's body spans exactly the asked envelope about its origin, in mm."""
    half = _NATIVE_FORMS[name][3]

    def check(p):
        lo, hi = p.get("min_point") or {}, p.get("max_point") or {}
        want = [(x_mm - half[0], x_mm + half[0]), (-half[1], half[1]), (-half[2], half[2])]
        return _measured(f"{name} bounds", {"min": lo, "max": hi},
                         all(_near(lo.get(a), w[0], 0.01) and _near(hi.get(a), w[1], 0.01)
                             for a, w in zip("xyz", want)))
    return check


def _native_form_rows():
    """The four native Form primitives, each read back apart from the create's own reply."""
    from verify_acts_sketch import _scratch_rows
    rows, write, read, close = _scratch_rows("nf_doc")
    for i, name in enumerate(_NATIVE_FORMS):
        x_mm = 80 * i
        write("form_create", {"primitive": _NATIVE_FORMS[name][0], "name": name,
                              "origin": [x_mm, 0, 0]}, _native_form_made(name))
        read("model_inspect", {"target": name, "units": "mm"}, _native_form_box(name, x_mm))
        read("form_get", {"max_results": 10},
             lambda p, name=name, i=i: _measured(
                 f"{name} recorded as a primitive", (p.get("forms") or [{}])[-1].get("record"),
                 p.get("count") == i + 1
                 and ((p["forms"][-1].get("record") or {}).get("primitive") or {}).get("shape")
                 == _NATIVE_FORMS[name][0]["shape"]
                 and p["forms"][-1].get("modified_downstream") is False))
    # refusals that never reach Fusion, and the cylinder's unchanged meaning beside them
    write("form_create", {"primitive": {"shape": "sphere", "size": [10], "spans": [8, 8],
                                        "capped": False}}, _refused("has no caps"))
    write("form_create", {"primitive": {"shape": "torus", "size": [20], "spans": [8, 4]}},
          _refused("size for a torus is 2"))
    read("form_get", {}, lambda p: p.get("count") == len(_NATIVE_FORMS))
    close()
    return rows


_MESH += _native_form_rows()


def _mesh_translate_rows():
    """Translate a mesh body and translate it back, each judged by a later independent read."""
    from verify_acts_sketch import _scratch_rows
    rows, write, read, close = _scratch_rows("mt_doc")
    write("sketch_create", {"plane": "xy", "name": "MtSk"})
    write("sketch_add_geometry", {"sketch_name": "MtSk", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 10}]})
    write("model_extrude", {"sketch_name": "MtSk", "distance": 5}, "ok",
          ("mt_body", _recall("mt_body", lambda p: (p.get("result_bodies") or p.get("bodies"))[0])))
    write("save_as_mesh", lambda c: {"body": _ctx_get(c, "mt_body", "source body"),
                                     "name": "MtMesh", "quality": "low"},
          lambda p: p.get("name") == "MtMesh")

    def at(x_mm):
        return lambda p: _measured(f"MtMesh min x at {x_mm} mm", p.get("bbox"),
                                   _near(((p.get("bbox") or {}).get("min_point") or {}).get("x"), x_mm, 0.001)
                                   and _near(((p.get("bbox") or {}).get("max_point") or {}).get("x"), x_mm + 20, 0.001))

    def moved(p):
        return (p.get("moved") is True and p.get("body_kind") == "mesh"
                and p.get("displacement") == 10.0 and p.get("nodes_checked", 0) > 0
                and "feature" not in p and p.get("no_feature_object") is True
                and p.get("timeline_items_added") == 1 and bool(p.get("timeline_item")))
    read("model_inspect", {"target": "MtMesh", "units": "mm"}, at(0))
    write("model_move", {"bodies": ["MtMesh"], "dx": 10}, moved,
          ("mt_item", _recall("mt_item", lambda p: p["timeline_item"])))
    read("model_inspect", {"target": "MtMesh", "units": "mm"}, at(10))
    # the source solid did not ride along
    read("model_inspect", lambda c: {"target": _ctx_get(c, "mt_body", "source body"), "units": "mm"},
         lambda p: _near((p.get("min_point") or {}).get("x"), 0, 0.001))
    write("model_move", {"bodies": ["MtMesh"], "dx": -10},
          lambda p: moved(p) and p.get("timeline_item") != _RECALL["mt_item"])
    read("model_inspect", {"target": "MtMesh", "units": "mm"}, at(0))
    # the guards: one kind per call, translate only
    write("model_move", lambda c: {"bodies": ["MtMesh", _ctx_get(c, "mt_body", "source body")],
                                   "dx": 5}, _refused("mixes mesh and BRep bodies"))
    write("model_move", {"mode": "rotate", "bodies": ["MtMesh"], "axis": "z", "angle_deg": 30},
          _refused("moves by mode 'translate' only"))
    read("model_inspect", {"target": "MtMesh", "units": "mm"}, at(0))
    close()
    return rows


_MESH += _mesh_translate_rows()


_W3_TETRA = {"vertices": [[0, 0, 0], [30, 0, 0], [0, 20, 0], [0, 0, 10]],
             "triangles": [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]}


def _mesh_bounds(name, lo, hi):
    """model_inspect on a mesh: its box corners in mm, read apart from the write before it."""
    def check(p):
        box = p.get("bbox") or {}
        return _measured(f"{name} bounds", box, all(
            _near((box.get("min_point") or {}).get(a), lo[i], 0.001)
            and _near((box.get("max_point") or {}).get(a), hi[i], 0.001)
            for i, a in enumerate("xyz")))
    return check


def _mesh_data_rows():
    """Caller triangle data becomes one mesh; mesh_find reads it; a move spends the revision."""
    from verify_acts_sketch import _scratch_rows
    rows, write, read, close = _scratch_rows("md_doc")
    write("mesh_insert", {"data": {**_W3_TETRA, "triangles": [[0, 1, 9]]}},
          _refused("data.triangles[0] is [0, 1, 9]"))
    read("mesh_get", {}, lambda p: p.get("count") == 0)
    read("design_get", {"include": ["timeline"]},
         lambda p: _measured("no base feature left by the refused data",
                             (p.get("timeline") or {}).get("count"),
                             (p.get("timeline") or {}).get("count") == 0))
    write("mesh_insert", {"data": _W3_TETRA, "name": "W3Tetra"},
          lambda p: p.get("imported") is True and p.get("source") == "data"
          and (p.get("vertices"), p.get("triangles")) == (4, 4) and p.get("name_applied") is True)
    read("model_inspect", {"target": "W3Tetra", "units": "mm"},
         lambda p: _mesh_bounds("W3Tetra", (0, 0, 0), (30, 20, 10))(p)
         and p.get("is_closed") is True and _near(p.get("volume"), 1000.0, 0.01))
    write("mesh_insert", {"data": {"vertices": [[50, 0, 0], [60, 0, 0], [50, 10, 0]],
                                   "triangles": [[0, 1, 2]], "normals": [[1, 0, 0]],
                                   "normal_indices": [[0, 0, 0]]}, "name": "W3Open"},
          _refused("'data' is an object of vertices, triangles"))
    write("mesh_insert", {"data": {"vertices": [[50, 0, 0], [60, 0, 0], [50, 10, 0]],
                                   "triangles": [[0, 1, 2]]}, "name": "W3Open"},
          lambda p: p.get("imported") is True and (p.get("vertices"), p.get("triangles")) == (3, 1))
    read("model_inspect", {"target": "W3Open", "units": "mm"},
         lambda p: _mesh_bounds("W3Open", (50, 0, 0), (60, 10, 0))(p) and p.get("is_closed") is False)
    write("sys_execute_script", {"read_only": True, "script": """import adsk.core, adsk.fusion, json
def run(context):
    app=adsk.core.Application.get(); d=adsk.fusion.Design.cast(app.activeProduct)
    if d is None or app.activeDocument.isSaved:
        raise RuntimeError('owned unsaved mesh scratch required')
    hits=[b for b in d.rootComponent.meshBodies if b.name == 'W3Open']
    if len(hits) != 1: raise RuntimeError('one W3Open mesh required')
    m=hits[0].mesh
    print(json.dumps({'vertices_cm':list(m.nodeCoordinatesAsDouble),
                     'triangles':list(m.triangleNodeIndices),
                     'normals':list(m.normalVectorsAsDouble)}))
"""}, lambda p: _measured("independent caller mesh geometry", p,
          p.get("vertices_cm") == [5.0, 0.0, 0.0, 6.0, 0.0, 0.0, 5.0, 1.0, 0.0]
          and p.get("triangles") == [0, 1, 2]))
    read("mesh_find", {"body": "W3Tetra", "kind": "node", "nearest_to": [30, 0, 0]},
         lambda p: p.get("total") == 4 and p["matches"][0]["index"] == 1
         and p["matches"][0]["position"] == [30.0, 0.0, 0.0] and p.get("frame") == "world",
         ("md_rev", _recall("md_rev", lambda p: p["revision"])))
    read("mesh_find", {"body": "W3Tetra", "kind": "triangle", "max_results": 2},
         lambda p: p.get("total") == 4 and len(p["matches"]) == 2 and p.get("truncated") is True
         and p.get("revision") == _RECALL["md_rev"])
    read("mesh_find", {"body": "W3Tetra", "kind": "group"},
         lambda p: p.get("total", 0) >= 1 and all(_num(m.get("area")) for m in p["matches"]))
    # straight down through (5, 5): the sloped face x/30 + y/20 + z/10 = 1 at z = 35/6, then z = 0
    read("mesh_find", {"body": "W3Tetra", "kind": "ray", "ray_origin": [5, 5, 50],
                       "ray_direction": [0, 0, -1]},
         lambda p: _measured("ray hits", p.get("matches"),
                             [round(m["position"][2], 3) for m in p["matches"]] == [5.833, 0.0]))
    read("mesh_find", {"body": "W3Tetra", "kind": "ray", "ray_origin": [500, 5, 50],
                       "ray_direction": [0, 0, -1]}, lambda p: p.get("matches") == [])
    read("mesh_find", {"body": "W3Tetra", "kind": "silhouette", "plane": "xy"},
         lambda p: _measured("silhouette on xy", p.get("matches"),
                             len(p["matches"]) == 1 and p["matches"][0]["closed"] is True
                             and p["matches"][0]["max"][:2] == [30.0, 20.0]))
    read("mesh_find", {"body": "W3Tetra", "kind": "ray", "ray_origin": [5, 5, 50]},
         _refused("missing ray_direction"))
    write("model_move", {"bodies": ["W3Tetra"], "dx": 10}, lambda p: p.get("moved") is True)
    read("mesh_find", {"body": "W3Tetra", "kind": "node", "nearest_to": [40, 0, 0]},
         lambda p: p["matches"][0]["position"] == [40.0, 0.0, 0.0]
         and p.get("revision") != _RECALL["md_rev"])
    close()
    return rows


_MESH += _mesh_data_rows()


def _tessellation_rows():
    """A coarser and a finer angle on one cylinder, compared on what was actually produced."""
    from verify_acts_sketch import _scratch_rows
    rows, write, read, close = _scratch_rows("ts_doc")
    write("sketch_create", {"plane": "xy", "name": "TsSk"})
    write("sketch_add_geometry", {"sketch_name": "TsSk", "geometry": [
        {"kind": "circle", "cx": 0, "cy": 0, "radius": 10}]})
    write("model_extrude", {"sketch_name": "TsSk", "distance": 20}, "ok",
          ("ts_body", _recall("ts_body", lambda p: p["result_bodies"][0])))

    def saved(key, name, **controls):
        write("save_as_mesh", lambda c: {"body": _ctx_get(c, "ts_body", "cylinder"),
                                         "name": name, **controls},
              lambda p: p.get("name") == name and (p.get("controls_applied") or {}) == {
                  k: float(v) for k, v in controls.items()} and _num(p.get("triangle_count")),
              (key, _recall(key, lambda p: p["triangle_count"])))
        read("model_inspect", {"target": name, "units": "mm"},
             lambda p: p.get("triangle_count") == _RECALL[key])
    saved("ts_coarse", "TsCoarse", normal_deviation_deg=30)
    saved("ts_fine", "TsFine", normal_deviation_deg=5)
    read("mesh_get", {}, lambda p: _measured(
        "a finer angle makes more triangles", [_RECALL["ts_coarse"], _RECALL["ts_fine"]],
        _RECALL["ts_fine"] > _RECALL["ts_coarse"] and p.get("count") == 2))
    saved("ts_surface_coarse", "TsSurfaceCoarse", surface_tolerance=0.5)
    saved("ts_surface_fine", "TsSurfaceFine", surface_tolerance=0.005)
    read("mesh_get", {}, lambda p: _measured(
        "surface tolerance refines the cylinder", [_RECALL["ts_surface_coarse"], _RECALL["ts_surface_fine"]],
        p.get("count") == 4 and _RECALL["ts_surface_fine"] > _RECALL["ts_surface_coarse"]))
    saved("ts_edge_plain", "TsEdgePlain")
    saved("ts_edge", "TsEdge", max_edge_length=2)
    read("mesh_get", {}, lambda p: _measured(
        "edge length refines the cylinder", [_RECALL["ts_edge_plain"], _RECALL["ts_edge"]],
        p.get("count") == 6 and _RECALL["ts_edge"] > _RECALL["ts_edge_plain"]))
    write("save_as_mesh", lambda c: {"body": _ctx_get(c, "ts_body", "cylinder"),
                                     "normal_deviation_deg": 200}, _refused("at most 180"))
    write("save_as_mesh", lambda c: {"body": _ctx_get(c, "ts_body", "cylinder"),
                                     "max_aspect_ratio": 4}, _refused("max_aspect_ratio"))

    def exported(key, deg):
        path = EXPORT_DIR + f"/w3_cyl_{deg}.stl"
        write("mesh_export", lambda c: {"target": _ctx_get(c, "ts_body", "cylinder"),
                                        "format": "stl", "file_path": path,
                                        "normal_deviation_deg": deg},
              lambda p: p.get("exported") is True and p.get("refinement") == "custom"
              and (p.get("options_applied") or {}).get("normal_deviation_deg") == float(deg)
              and _num(p.get("triangle_count")) and p.get("size_bytes") == 84 + 50 * p["triangle_count"],
              (key, _recall(key, lambda p: p["triangle_count"])))
    exported("ts_stl_coarse", 30)
    exported("ts_stl_fine", 0.8)
    for key, suffix, controls in (("ts_stl_default", "default", {}),
                                  ("ts_stl_ratio", "ratio", {"max_aspect_ratio": 2})):
        write("mesh_export", lambda c, suffix=suffix, controls=controls: {
            "target": _ctx_get(c, "ts_body", "cylinder"), "format": "stl",
            "file_path": EXPORT_DIR + f"/w3_cyl_{suffix}.stl", **controls},
            lambda p, controls=controls: p.get("exported") is True
            and p.get("options_applied") == {"stl_units": "mm", **controls}
            and _num(p.get("triangle_count")) and p.get("size_bytes") == 84 + 50 * p["triangle_count"],
            (key, _recall(key, lambda p: p["triangle_count"])))

    def on_disk(p):
        files = {}
        for key, deg in (("ts_stl_coarse", 30), ("ts_stl_fine", 0.8),
                         ("ts_stl_default", "default"), ("ts_stl_ratio", "ratio")):
            data = Path(EXPORT_DIR + f"/w3_cyl_{deg}.stl").read_bytes()
            files[key] = (struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else None,
                          len(data), hashlib.sha256(data[84:]).hexdigest()[:12])
        return _measured("the four STL files on disk", files, p.get("count") == 6 and all(
            count == _RECALL[key] and size == 84 + 50 * count
            for key, (count, size, _digest) in files.items())
            and files["ts_stl_fine"][0] > files["ts_stl_coarse"][0]
            and files["ts_stl_fine"][2] != files["ts_stl_coarse"][2]
            and files["ts_stl_ratio"][0] > files["ts_stl_default"][0]
            and files["ts_stl_ratio"][2] != files["ts_stl_default"][2])
    read("mesh_get", {}, on_disk)
    write("mesh_export", lambda c: {"target": _ctx_get(c, "ts_body", "cylinder"), "format": "obj",
                                    "file_path": EXPORT_DIR + "/w3_cyl.obj",
                                    "max_aspect_ratio": 3}, _refused("format=obj"))
    close()
    return rows


_MESH += _tessellation_rows()


def _cage_vertex_at(x, y, z):
    """find_geometry(form_vertex): the nearest cage vertex sits at this point, in mm."""
    return lambda p: _measured(f"cage vertex at ({x}, {y}, {z})", (p.get("matches") or [{}])[0],
                               bool(p.get("matches"))
                               and p["matches"][0]["position"] == [float(x), float(y), float(z)])


def _form_edit_rows():
    """A cage vertex moved and returned, an edge creased, the whole body moved: each re-read."""
    from verify_acts_sketch import _scratch_rows
    rows, write, read, close = _scratch_rows("fe_doc")
    write("form_create", {"primitive": {"shape": "box", "size": [20, 20, 20], "spans": [2, 2, 2]},
                          "name": "W3Box"}, lambda p: p.get("created") is True,
          ("fe_form", _recall("fe_form", lambda p: p["form"])))
    read("model_inspect", {"target": "W3Box", "include": ["default", "mass"], "units": "mm"}, "ok",
         ("fe_volume", _recall("fe_volume", lambda p: p["mass"]["volume"])))

    def find(kind, near, check, save):
        read("find_geometry", lambda c: {"kind": kind, "nearest_to": near, "max_results": 1,
                                         "name": _ctx_get(c, "fe_form", "the Form")},
             check, (save, _recall(save, lambda p: p["matches"][0]["handle"])))

    def edit(args, check):
        write("form_edit", lambda c: {"body": _ctx_get(c, "fe_form", "the Form"),
                                      **(args(c) if callable(args) else args)}, check)
    find("form_vertex", [10, 10, 10], _cage_vertex_at(10, 10, 10), "fe_corner")
    edit(lambda c: {"action": "move", "entities": [_ctx_get(c, "fe_corner", "corner")],
                    "translation": [5, 5, 5]},
         lambda p: p.get("edited") is True and p.get("changed") is True
         and p.get("moved_vertices") == 1
         and p["cage_before"]["revision"] != p["cage_after"]["revision"])
    read("model_inspect", {"target": "W3Box", "include": ["default", "mass"], "units": "mm"},
         lambda p: _measured("the solid grew with its corner", (p.get("mass") or {}).get("volume"),
                             p["mass"]["volume"] > _RECALL["fe_volume"] + 1.0))
    # the handle read before the move is spent
    edit(lambda c: {"action": "move", "entities": [_ctx_get(c, "fe_corner", "corner")],
                    "translation": [-5, -5, -5]}, _refused("earlier cage"))
    find("form_vertex", [15, 15, 15], _cage_vertex_at(15, 15, 15), "fe_corner2")
    edit(lambda c: {"action": "move", "entities": [_ctx_get(c, "fe_corner2", "moved corner")],
                    "translation": [-5, -5, -5]}, lambda p: p.get("edited") is True)
    read("model_inspect", {"target": "W3Box", "include": ["default", "mass"], "units": "mm"},
         lambda p: _near_rel((p.get("mass") or {}).get("volume"), _RECALL["fe_volume"], 1e-7))
    at = lambda x, y, z: lambda p: p["matches"][0]["position"] == [float(x), float(y), float(z)]
    find("form_face", [5, 5, 10], at(5, 5, 10), "fe_face")
    edit(lambda c: {"action": "move", "entities": [_ctx_get(c, "fe_face", "top face")],
                    "translation": [0, 0, 5]},
         lambda p: p.get("edited") is True and p.get("changed") is True
         and p.get("moved_vertices") == 4)
    read("model_inspect", {"target": "W3Box", "include": ["default", "mass"], "units": "mm"},
         lambda p: _measured("the solid grew with its face", (p.get("mass") or {}).get("volume"),
                             p["mass"]["volume"] > _RECALL["fe_volume"] + 1.0))
    find("form_face", [5, 5, 15], at(5, 5, 15), "fe_face2")
    edit(lambda c: {"action": "move", "entities": [_ctx_get(c, "fe_face2", "moved face")],
                    "translation": [0, 0, -5]}, lambda p: p.get("edited") is True)
    read("model_inspect", {"target": "W3Box", "include": ["default", "mass"], "units": "mm"},
         lambda p: _near_rel((p.get("mass") or {}).get("volume"), _RECALL["fe_volume"], 1e-7))
    find("form_face", [5, 5, 10], at(5, 5, 10), "fe_face3")
    find("form_edge", [10, 10, 5], lambda p: p["matches"][0]["creased"] is False, "fe_edge")
    edit(lambda c: {"action": "crease", "entities": [_ctx_get(c, "fe_edge", "edge")],
                    "creased": True},
         lambda p: p.get("edited") is True and p["cage_after"]["creased_edges"] == 1
         and p.get("moved_vertices") == 0)
    find("form_edge", [10, 10, 5], lambda p: p["matches"][0]["creased"] is True, "fe_edge2")
    edit({"action": "move", "translation": [0, 0, 10]},
         lambda p: p.get("edited") is True and p.get("moved_vertices") == p["cage_after"]["vertices"])
    read("model_inspect", {"target": "W3Box", "units": "mm"},
         lambda p: _near((p.get("min_point") or {}).get("z"), 0, 0.01)
         and _near((p.get("max_point") or {}).get("z"), 20, 0.01))
    read("form_get", {}, lambda p: (p["forms"][0].get("record") or {}).get("edited_by") == "form_edit"
         and p["forms"][0].get("modified_downstream") is False)
    edit({"action": "move", "translation": [0, 0, 0]}, _refused("not all zero"))
    close()
    return rows


_MESH += _form_edit_rows()


def _image_row(kind, **want):
    """design_get(reference_images): the one image of `kind` reads these values."""
    def check(p):
        hits = [r for r in (p.get("reference_images") or {}).get("images") or []
                if r.get("kind") == kind]
        row = hits[0] if len(hits) == 1 else {}
        return _measured(f"the {kind}'s row", row, bool(row) and all(
            row.get(k) == v if not isinstance(v, list)
            else isinstance(row.get(k), list) and len(row[k]) == len(v)
            and all(_near(a, b, 0.001) for a, b in zip(row[k], v))
            for k, v in want.items()))
    return check


def _reference_image_rows():
    """A canvas and a decal created, placed, styled and deleted, each read back by design_get."""
    from verify_acts_sketch import _scratch_rows
    rows, write, read, close = _scratch_rows("ri_doc")
    image = EXPORT_DIR + "/w3_reference.png"
    images = {"include": ["reference_images"], "units": "mm"}
    write("sketch_create", {"plane": "xy", "name": "RiSk"})
    write("sketch_add_geometry", {"sketch_name": "RiSk", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 40, "y2": 30}]})
    write("model_extrude", {"sketch_name": "RiSk", "distance": 10})
    read("view_screenshot", {"view": "top", "width": 64, "height": 32, "file_path": image}, "ok")

    def edit(args, check, save=None):
        write("design_edit_reference_image", args, check, save)
    edit({"action": "create", "kind": "canvas", "image": image, "plane": "xy"},
         lambda p: p.get("kind") == "canvas" and p.get("before") is None
         and bool(p.get("reference")),
         ("ri_canvas", _recall("ri_canvas", lambda p: p["reference"])))
    read("design_get", images, _image_row("canvas", position=[0, 0], mirrored=False),
         ("ri_size", _recall("ri_size", lambda p: p["reference_images"]["images"][0]["size"])))
    edit(lambda c: {"action": "place", "kind": "canvas", "position": [10, 20], "scale": [2, 2],
                    "rotation_deg": 90, "reference": _ctx_get(c, "ri_canvas", "canvas")},
         lambda p: p["after"]["position"] == [10.0, 20.0] and p["after"]["rotation_deg"] == 90.0)
    read("design_get", images, lambda p: _image_row(
        "canvas", position=[10, 20], rotation_deg=90.0,
        size=[2 * _RECALL["ri_size"][0], 2 * _RECALL["ri_size"][1]])(p))
    edit(lambda c: {"action": "style", "kind": "canvas", "opacity": 30, "display_through": False,
                    "reference": _ctx_get(c, "ri_canvas", "canvas")},
         lambda p: p["after"]["opacity"] == 30.0 and p["after"]["display_through"] is False)
    read("design_get", images, _image_row("canvas", opacity=30.0, display_through=False))
    edit(lambda c: {"action": "style", "kind": "canvas", "opacity": 30.5, "name": "MustNotRename",
                    "reference": _ctx_get(c, "ri_canvas", "canvas")}, _refused("whole number from 0 to 100"))
    read("design_get", images, _image_row("canvas", name="w3_reference", opacity=30.0, display_through=False))
    edit(lambda c: {"action": "place", "kind": "canvas", "flip_horizontal": True,
                    "reference": _ctx_get(c, "ri_canvas", "canvas")},
         lambda p: p["after"]["mirrored"] is True and p["after"]["position"] == [10.0, 20.0])
    edit(lambda c: {"action": "style", "kind": "canvas", "opacity": 150,
                    "reference": _ctx_get(c, "ri_canvas", "canvas")}, _refused("from 0 to 100"))
    # a canvas on a planar face, and a decal on the same face
    read("find_geometry", {"kind": "planar_face", "nearest_to": [20, 15, 10], "max_results": 1},
         lambda p: _near(p["matches"][0]["position"][2], 10, 0.001),
         ("ri_top", _recall("ri_top", lambda p: p["matches"][0]["handle"])))
    edit(lambda c: {"action": "create", "kind": "canvas", "image": image, "name": "RiOnFace",
                    "plane": _ctx_get(c, "ri_top", "top face")},
         lambda p: p["after"]["name"] == "RiOnFace",
         ("ri_face_canvas", _recall("ri_face_canvas", lambda p: p["reference"])))
    edit(lambda c: {"action": "delete", "kind": "canvas",
                    "reference": _ctx_get(c, "ri_face_canvas", "face canvas")},
         lambda p: p.get("deleted") is True and p.get("after") is None)
    edit(lambda c: {"action": "create", "kind": "decal", "image": image, "origin": [20, 15, 10],
                    "faces": [_ctx_get(c, "ri_top", "top face")], "opacity": 40},
         lambda p: p["after"]["opacity"] == 40.0 and p["after"]["origin"] == [20.0, 15.0, 10.0],
         ("ri_decal", _recall("ri_decal", lambda p: p["reference"])))
    decal_of = lambda p: [r for r in p["reference_images"]["images"] if r["kind"] == "decal"][0]
    read("design_get", images, _image_row("decal", origin=[20, 15, 10],
                                          first_face_centroid=[20, 15, 10]),
         ("ri_dsize", _recall("ri_dsize", lambda p: decal_of(p)["size"])))
    read("design_get", {"include": ["timeline"]}, "ok",
         ("ri_marker", _recall("ri_marker", lambda p: p["timeline"].get("marker_position"))))
    edit(lambda c: {"action": "place", "kind": "decal", "origin": [10, 10, 10],
                    "scale": [0.5, 0.5], "x_direction": [0, 1, 0],
                    "reference": _ctx_get(c, "ri_decal", "decal")},
         lambda p: p["after"]["origin"] == [10.0, 10.0, 10.0]
         and p["after"]["x_direction"] == [0.0, 1.0, 0.0])
    read("design_get", {"include": ["timeline"]},
         lambda p: p["timeline"].get("marker_position") == _RECALL["ri_marker"])
    read("design_get", images, _image_row("decal", origin=[10, 10, 10], opacity=40.0))
    edit(lambda c: {"action": "place", "kind": "decal", "x_direction": [0, 0, 1],
                    "reference": _ctx_get(c, "ri_decal", "decal")},
         _refused("must lie in the first face's plane"))
    read("find_geometry", {"kind": "planar_face", "nearest_to": [40, 15, 5], "max_results": 1},
         lambda p: _near(p["matches"][0]["position"][0], 40, 0.001),
         ("ri_side", _recall("ri_side", lambda p: p["matches"][0]["handle"])))
    # a decal stays on its faces; two faces need chaining off
    edit(lambda c: {"action": "place", "kind": "decal", "origin": [40, 15, 5],
                    "faces": [_ctx_get(c, "ri_side", "side face")],
                    "reference": _ctx_get(c, "ri_decal", "decal")},
         _refused("Delete the decal and create it"))
    read("design_get", images, _image_row("decal", origin=[10, 10, 10],
                                          first_face_centroid=[20, 15, 10]))

    def drop(key, kind):
        edit(lambda c: {"action": "delete", "kind": kind, "reference": _ctx_get(c, key, kind)},
             lambda p: p.get("deleted") is True)
    drop("ri_decal", "decal")
    both = lambda c: [_ctx_get(c, "ri_side", "side face"), _ctx_get(c, "ri_top", "top face")]
    edit(lambda c: {"action": "create", "kind": "decal", "image": image, "origin": [40, 15, 5],
                    "faces": both(c)}, _refused("chain_faces=false"))
    # off the first face: Fusion's own refusal comes through and nothing is left behind
    edit(lambda c: {"action": "create", "kind": "decal", "image": image, "origin": [50, 15, 5],
                    "faces": both(c), "chain_faces": False}, _refused("not located on primary face"))
    read("design_get", images, lambda p: not [r for r in p["reference_images"]["images"]
                                              if r["kind"] == "decal"])
    # on the +X side face and the top, direction given: read apart from the write
    edit(lambda c: {"action": "create", "kind": "decal", "image": image, "origin": [40, 15, 5],
                    "faces": both(c), "chain_faces": False, "x_direction": [0, 0, 1]},
         lambda p: p["after"]["origin"] == [40.0, 15.0, 5.0],
         ("ri_decal_side", _recall("ri_decal_side", lambda p: p["reference"])))
    read("design_get", images, _image_row(
        "decal", origin=[40, 15, 5], x_direction=[0, 0, 1], first_face_centroid=[40, 15, 5],
        face_count=2, chain_faces=False))
    drop("ri_decal_side", "decal")
    edit(lambda c: {"action": "create", "kind": "decal", "image": image, "origin": [30, 10, 10],
                    "faces": [_ctx_get(c, "ri_top", "top face")], "scale": [2, 2],
                    "x_direction": [0, 1, 0], "chain_faces": False},
         lambda p: p["after"]["origin"] == [30.0, 10.0, 10.0],
         ("ri_decal2", _recall("ri_decal2", lambda p: p["reference"])))
    read("design_get", images, lambda p: _image_row(
        "decal", origin=[30, 10, 10], x_direction=[0, 1, 0], first_face_centroid=[20, 15, 10],
        face_count=1, size=[2 * _RECALL["ri_dsize"][0], 2 * _RECALL["ri_dsize"][1]])(p))
    drop("ri_decal2", "decal")
    drop("ri_canvas", "canvas")
    read("design_get", images, lambda p: p["reference_images"].get("total") == 0)
    edit(lambda c: {"action": "delete", "kind": "canvas",
                    "reference": _ctx_get(c, "ri_canvas", "canvas")},
         _refused("no longer names a root canvas"))
    close()
    return rows


_MESH += _reference_image_rows()
