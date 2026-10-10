# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""ACT rows: the machined part's parametric skeleton, and the sketch tools on scratch sketches.

Both run before anything is solid - which is the order the work is done in - so these rows read
sketch geometry and user parameters, never bodies.
"""

import json
from math import isfinite

from verify_core import (
    EXPORT_DIR, SVG96_PATH, SVG_PATH, _ctx_get, _datum_plane, _dim_measures, _extruded,
    _made_component, _param_added, _param_favorited, _params_listed, _refused, _svg96_extent,
    _watch_all, _measured, _RECALL, _recall, _home_document, _home_address,
    _new_document, _document_closed, _activated, _near, _num, _Refusal)
from verify_layout import _px, _py
from verify_acts_model_combine_revolve import _combine_pin
from verify_acts_model_sweep import _FilletRadiusRefusal, _retire_compare, _retire_sketch_state, _timeline_names


class _SketchBatchRefusal(_Refusal):
    """Check a structured partial sketch error and optionally retain a landed identity."""
    def __init__(self, check, remember=None):
        super().__init__(())
        self.check, self.remember = check, remember

    def missing(self, text):
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return ["structured sketch batch error body"]
        if not isinstance(payload, dict) or not payload.get("failed"):
            return ["failed sketch batch"]
        try:
            if not self.check(payload):
                return ["structured batch assertions"]
            if self.remember:
                key, extract = self.remember
                _RECALL[key] = extract(payload)
        except Exception as exc:
            return [f"structured batch predicate: {exc}"]
        return []


def _split_public(stage):
    """Check constraint attribution against independently acquired curve endpoints and ids."""
    def check(p):
        lines = [r for r in p.get("entities", []) if r.get("type") == "line"]
        expected = {
            "right": [[_px("EditSplit", x), _py("EditSplit", 0)] for x in (650, 700)],
            "left": [[_px("EditSplit", x), _py("EditSplit", 0)] for x in (600, 650)],
            "control": [[_px("EditSplit", 650), _py("EditSplit", y)] for y in (-50, 50)]}
        selected = {}
        for name, ends in expected.items():
            hits = [r for r in lines if sorted([[r.get(end, {}).get(axis) for axis in ("x", "y")]
                                               for end in ("start", "end")]) == sorted(ends)]
            if len(hits) != 1:
                return _measured("split piece endpoints", lines, False)
            selected[name] = hits[0]["id"]
        stable = {key: p.get(key) for key in (
            "counts", "dimension_count", "profile_count", "is_fully_constrained", "compute_deferred")}
        stable["entities"] = [{k: v for k, v in row.items() if k != "handle"}
                              for row in p.get("entities", [])]
        if stage == 0:
            _RECALL["split_public_geometry"] = stable
            _RECALL["split_targets"] = [selected["right"], selected["left"]]
        targets = _RECALL.get("split_targets", [])
        wanted = [{"type": "horizontal", "entities": [ref]} for ref in targets[:stage]]
        return _measured("split labels match the constrained endpoint-selected pieces", p.get("constraints"),
                         p.get("truncated") is False and len(lines) == 3
                         and len(set(selected.values())) == 3
                         and targets == [selected["right"], selected["left"]]
                         and p.get("counts", {}).get("lines") == 3
                         and p.get("dimension_count") == 0 and p.get("profile_count") == 0
                         and p.get("is_fully_constrained") is False
                         and stable == _RECALL.get("split_public_geometry")
                         and p.get("constraint_count") == stage and p.get("constraints") == wanted)
    return check


def _split_history(p):
    """Require complete, unchanged feature history around split constraint additions."""
    timeline = p.get("timeline") or {}
    return _measured("split constraint history unchanged", timeline,
                     timeline.get("truncated") is not True
                     and timeline.get("count") == timeline.get("returned") == len(timeline.get("timeline", []))
                     and timeline == _RECALL.get("split_history"))


def _radial_state(payload, radii, dimension_values):
    circles = [(e.get("id"), e.get("center", {}).get("x"), e.get("center", {}).get("y"),
                e.get("radius")) for e in payload.get("entities", [])
               if e.get("type") == "circle"]
    dimensions = payload.get("dimensions") or []
    expected = [(f"circle:{i}", _px("RetainedDims", 1180 + i * 40),
                 _py("RetainedDims", 560), radius)
                for i, radius in enumerate(radii)]
    return (payload.get("truncated") is False
            and payload.get("counts", {}).get("circles") == 3
            and payload.get("dimension_count") == len(dimension_values)
            and circles == expected
            and sorted(round(d.get("value"), 4) for d in dimensions)
            == sorted(dimension_values)
            and all(d.get("name") and d.get("driving") is True for d in dimensions))


def _retained_dims_create(_ctx):
    for key in ("radial_first_wire", "radial_mixed"):
        _RECALL.pop(key, None)
    return {"plane": "xy", "name": "RetainedDims"}


def _mixed_curve_state(fixed):
    """Check projected and authored curves independently, with uncapped state totals."""
    def check(p):
        curves = {e.get("id"): e for e in p.get("entities", []) if e.get("type") == "line"}
        projected, authored = curves.get("line:0", {}), curves.get("line:1", {})
        totals = {key: p.get(key + "_curve_count") for key in ("fixed", "reference", "linked")}
        return _measured("mixed projected/authored curve states",
                         {"curves": curves, "totals": totals,
                          "constraint_objects": p.get("constraint_count")},
                         len(curves) == 2 and p.get("truncated") is False
                         and projected.get("reference") is True and projected.get("linked") is True
                         and isinstance(projected.get("fixed"), bool)
                         and authored.get("fixed") is fixed
                         and authored.get("reference") is False and authored.get("linked") is False
                         and p.get("constraint_count") == 0
                         and all(totals[key] == sum(e[key] for e in curves.values())
                                 for key in totals))
    return check


def _first_radial_cleanup_args(ctx):
    """Require the first retained identity to match its independent read and deletion."""
    wire = _RECALL.get("radial_first_wire")
    read = _ctx_get(ctx, "radial_first_read", "the first retained dimension row")
    deleted = _ctx_get(ctx, "radial_first_deleted", "the first deletion response")
    if not wire or wire != read or wire != deleted:
        raise AssertionError("first retained dimension identity did not match read-back and cleanup")
    return {"sketch_name": "RetainedDims", "include_entities": True}


def _mixed_radial_cleanup_args(ctx):
    """Require both mixed identities to match the independent rows and deletion responses."""
    wire = _RECALL.get("radial_mixed")
    read = _ctx_get(ctx, "radial_mixed_read", "the mixed radial dimension rows")
    set_name = _ctx_get(ctx, "radial_mixed_set", "the restored completed dimension")
    retained = _ctx_get(ctx, "radial_mixed_retained_deleted", "the retained deletion")
    completed = _ctx_get(ctx, "radial_mixed_completed_deleted", "the completed deletion")
    if (wire != read or wire.get("completed") != set_name
            or wire.get("retained") != retained or wire.get("completed") != completed):
        raise AssertionError("mixed dimension identities did not match read-back and cleanup")
    return {"sketch_name": "RetainedDims", "include_entities": True}


def _at(row, chunk, x, y, tol=0.01):
    """True when an {x, y} read sits at the authored (x, y) once `chunk` is placed."""
    return (isinstance(row, dict) and _near(row.get("x"), _px(chunk, x), tol)
            and _near(row.get("y"), _py(chunk, y), tol))


def _rows_by_id(p):
    return {e.get("id"): e for e in p.get("entities") or []}


def _polygon_witness(p):
    """The polygon constraint names the square's four lines, each one of its edges."""
    lines = _rows_by_id(p)
    polys = [c.get("entities") for c in p.get("constraints") or [] if c.get("type") == "polygon"]
    want = {"line:5", "line:6", "line:7", "line:8"}
    corners = [(x, y) for x in (940, 980) for y in (505, 545)]

    def corner(row):
        return next((c for c in corners if _at(row, "ConBench2", *c)), None)
    edges = {frozenset((corner(lines.get(i, {}).get("start")), corner(lines.get(i, {}).get("end"))))
             for i in want}
    return _measured("the polygon names the square's own four edges", polys,
                     p.get("truncated") is False and len(polys) == 1 and len(polys[0] or []) == 4
                     and set(polys[0]) == want and None not in set().union(*edges)
                     and len(edges) == 4 and all(len(e) == 2 for e in edges))


# line:0 once the collinear constraint with line:1 has turned it off its authored (860,480)-(930,486).
_CONBENCH2_LINE0 = ((860.0459, 479.7323), (929.8883, 487.3514))


def _line0_end_points(p):
    """The ids of the point rows sitting on line:0's start and end, read by coordinates."""
    rows = _rows_by_id(p)
    line = rows.get("line:0") or {}

    def on(end):
        return [i for i, r in rows.items() if r.get("type") == "point" and isinstance(end, dict)
                and isinstance(r.get("position"), dict)
                and _near(r["position"].get("x"), end.get("x"), 1e-4)
                and _near(r["position"].get("y"), end.get("y"), 1e-4)]
    return on(line.get("start")), on(line.get("end"))


def _line0_at_measured(line):
    return (_at(line.get("start"), "ConBench2", *_CONBENCH2_LINE0[0])
            and _at(line.get("end"), "ConBench2", *_CONBENCH2_LINE0[1]))


def _fixed_line_moved(p):
    """line:3 reads fixed, yet the 15 mm mid-to-end dimension pulled both ends in to 30 mm apart."""
    rows = _rows_by_id(p)
    line = rows.get("line:3") or {}
    start, end = line.get("start") or {}, line.get("end") or {}
    starts, ends = _line0_end_points(p)
    _RECALL.pop("conbench2_line0_ends", None)
    if len(starts) == 1 and len(ends) == 1 and starts != ends:
        _RECALL["conbench2_line0_ends"] = (starts[0], ends[0])
    return _measured("fixed line:3 moved under its dimension; line:0's end points read by position",
                     {"line:3": {k: line.get(k) for k in ("fixed", "start", "end")},
                      "line:0": {k: (rows.get("line:0") or {}).get(k) for k in ("start", "end")},
                      "end_points": (starts, ends)},
                     p.get("truncated") is False and line.get("fixed") is True
                     and not _at(start, "ConBench2", 880, 505)
                     and not _at(end, "ConBench2", 920, 511)
                     and _at(start, "ConBench2", 885, 505.75)
                     and _at(end, "ConBench2", 915, 510.25)
                     and "conbench2_line0_ends" in _RECALL
                     and _line0_at_measured(rows.get("line:0") or {}))


def _fix_line0_and_ends(ctx):
    ends = _ctx_get(_RECALL, "conbench2_line0_ends", "line:0's end point ids")
    return {"constraints": [{"constraint": "fix", "entity_one": ref} for ref in ("line:0", *ends)],
            "sketch_name": "ConBench2"}


def _endpoint_fixed_held(p):
    """line:0 with its two end points fixed is where it was read, and no dimension was added."""
    rows = _rows_by_id(p)
    line = rows.get("line:0") or {}
    starts, ends = _line0_end_points(p)
    return _measured("endpoint-fixed line:0 held and the refused dimension left nothing",
                     {"line:0": {k: line.get(k) for k in ("fixed", "start", "end")},
                      "end_points": (starts, ends), "dimension_count": p.get("dimension_count")},
                     p.get("truncated") is False and line.get("fixed") is True
                     and _line0_at_measured(line)
                     and (starts + ends) == list(_RECALL.get("conbench2_line0_ends") or ())
                     and p.get("dimension_count") == _RECALL.get("conbench2_dims"))


def _offset_witness(p):
    """The offset names the two parents then the two children, each child 8 mm outside its parent."""
    rows = _rows_by_id(p)
    off = [c.get("entities") for c in p.get("constraints") or [] if c.get("type") == "offset"]
    l2, l3 = rows.get("line:2") or {}, rows.get("line:3") or {}
    return _measured("offset parents then children, by coordinates", {"offset": off, "line:2": l2,
                                                                      "line:3": l3},
                     p.get("truncated") is False and off == [["line:0", "line:1", "line:2", "line:3"]]
                     and _at((rows.get("line:0") or {}).get("start"), "OffOne", 860, 730)
                     and _at((rows.get("line:1") or {}).get("end"), "OffOne", 940, 790)
                     and all(_near((l2.get(k) or {}).get("y"), _py("OffOne", 722), 0.01)
                             for k in ("start", "end"))
                     and all(_near((l3.get(k) or {}).get("x"), _px("OffOne", 948), 0.01)
                             for k in ("start", "end")))


def _angle_measures(p):
    """sketch_dimension angle: one of the two angles a 1:3 slope makes with a vertical line."""
    parts = ((p.get("results") or [{}])[0].get("value") or "").split()
    try:
        got = float(parts[0])
    except (IndexError, ValueError):
        got = None
    return _measured("angle between line:0 and line:1", p.get("results"),
                     got is not None and min(abs(got - 71.5651), abs(got - 108.4349)) < 0.01)


def _dimbench_pair_ids(p):
    """[the line at authored y 506, the line at y 526] off one DimBench read."""
    ids = [next(e["id"] for e in p.get("entities") or [] if e.get("type") == "line"
                and _at(e.get("start"), "DimBench", 1095, y)) for y in (506, 526)]
    _RECALL["dimbench_pair"] = ids
    return ids


def _dimbench_witness(p):
    """The eight dimension classes name the entities they were authored on, by coordinates."""
    rows = _rows_by_id(p)
    dims = {}
    for d in p.get("dimensions") or []:
        dims.setdefault(d.get("type"), []).append(d.get("entities"))
    pair = _RECALL.get("dimbench_pair") or []
    want = {"sketchlinear": [["point:1", "point:2"]], "sketchdiameter": [["circle:0"]],
            "sketchconcentriccircle": [["circle:0", "circle:1"]],
            "sketchtangentdistance": [["line:1", "circle:0"]],
            "sketchellipsemajorradius": [["ellipse:0"]], "sketchellipseminorradius": [["ellipse:0"]],
            "sketchangular": [["line:0", "line:1"]], "sketchlineardiameter": [pair]}
    c0, c1, el = rows.get("circle:0") or {}, rows.get("circle:1") or {}, rows.get("ellipse:0") or {}
    return _measured("eight dimension classes name their authored entities", dims,
                     p.get("truncated") is False and len(pair) == 2 and dims == want
                     and _at((rows.get("point:1") or {}).get("position"), "DimBench", 1060, 480)
                     and _at((rows.get("point:2") or {}).get("position"), "DimBench", 1120, 500)
                     and _at(c0.get("center"), "DimBench", 1090, 560) and _near(c0.get("radius"), 24, .01)
                     and _at(c1.get("center"), "DimBench", 1090, 560) and _near(c1.get("radius"), 12, .01)
                     and _near(((rows.get("line:1") or {}).get("start") or {}).get("x"),
                               _px("DimBench", 1140), .01)
                     and _at(el.get("center"), "DimBench", 1090, 650)
                     and _at((rows.get(pair[1]) or {}).get("end"), "DimBench", 1130, 526)
                     and sum(1 for e in rows.values()
                             if e.get("type") == "line" and e.get("construction") is True) == 2)


def _xray_gaps_2_w3conic(payload):
    return (payload.get("truncated") is False and payload.get("counts", {}).get("conics") == 1
            and any(e.get("id") == "conic:0" and e.get("type") == "conic"
                    for e in payload.get("entities", [])))


def _xray_gaps_2_w3earc(payload):
    return (payload.get("truncated") is False
            and payload.get("counts", {}).get("elliptical_arcs") == 1
            and any(e.get("id") == "elliptical_arc:0" and e.get("type") == "elliptical_arc"
                    for e in payload.get("entities", [])))


# --- ACT 1: PARAMETERS + THE PART'S SKETCHES - the bracket, drawn before anything is solid -----
_SKELETON = [
    # ONE driving length, two independent extents (width, height), and the features derived from
    # the section they are cut into. Each derived parameter's expected value is what the
    # DESIGN evaluates the expression to off the 120 mm driver above it - so the read-back proves
    # Fusion resolved the reference, not that the expression text was accepted (the CAM parameter
    # store accepts a bogus name unevaluated).
    ("param_add", {"name": "PartLen", "expression": "120 mm",
                   "comment": "The driving length: the pocket length and corner radius follow it"},
     _param_added("PartLen", 120), None),
    # The part's OTHER two extents are their own parameters, not ratios of the length: a bracket
    # that is made longer is not made wider and taller with it, and the resize act reads exactly
    # that - one axis follows the driver while the other two hold.
    ("param_add", {"name": "PartWid", "expression": "80 mm"}, _param_added("PartWid", 80), None),
    ("param_add", {"name": "PartHt", "expression": "40 mm"}, _param_added("PartHt", 40), None),
    # Everything the part is FEATURED with derives from the height or the width it is cut into.
    ("param_add", {"name": "StepDrop", "expression": "PartHt / 4",
                   "comment": "How far the low half of the stepped top sits under the high half"},
     _param_added("StepDrop", 10), None),
    ("param_add", {"name": "BoreDia", "expression": "PartHt * 0.3"},
     _param_added("BoreDia", 12), None),
    ("param_add", {"name": "PocketLen", "expression": "PartLen / 4"},
     _param_added("PocketLen", 30), None),
    ("param_add", {"name": "PocketWid", "expression": "PartWid * 0.55"},
     _param_added("PocketWid", 44), None),
    ("param_add", {"name": "PocketDepth", "expression": "PartHt * 0.4"},
     _param_added("PocketDepth", 16), None),
    ("param_add", {"name": "PocketRad", "expression": "PartLen / 15",
                   "comment": "Pocket corner radius - what a cutter has to clear the corner with"},
     _param_added("PocketRad", 8), None),
    ("param_add", {"name": "BossDia", "expression": "PartHt / 2"},
     _param_added("BossDia", 20), None),
    ("param_add", {"name": "MountDia", "expression": "PartHt * 0.15"},
     _param_added("MountDia", 6), None),
    # A RULE, not a ratio: the edge break scales with the section but stops at a floor, so thinning
    # the part thins the break only until it reaches one that can still be cut.
    ("param_add", {"name": "EdgeBreak", "expression": "max(PartHt * 0.075; 2 mm)",
                   "comment": "Break on a handled edge - floored so it stays cuttable"},
     _param_added("EdgeBreak", 3), None),
    ("param_set_favorite", {"name": "PartLen", "favorite": True}, _param_favorited("PartLen"), None),
    ("param_get", {}, _params_listed("PartLen", "PartWid", "PartHt", "StepDrop", "BoreDia",
                                     "PocketLen", "PocketWid", "PocketDepth", "PocketRad",
                                     "BossDia", "MountDia", "EdgeBreak"), None),
    # THE PART, cast as its own component at the ROOT: the vise is built around it and the CAM setup
    # names it, so it is never nested inside anything that could carry it somewhere else.
    ("model_create_component", {"name": "Bracket", "activate": True}, _made_component, None),
    # the SHARED SKELETON on the root: two in-plane axes (construction) + the height as a 3D line.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # 'sketch_name' is the name READ BACK off the sketch (Fusion dedupes a taken one, and every step
    # after this names 'Skeleton'), and the frame's normal is computed from the created sketch's own
    # axes - an XY sketch's is the Z axis.
    ("sketch_create", {"plane": "xy", "name": "Skeleton"},
     lambda p: (p["sketch_name"] == "Skeleton" and bool(p["plane"])
                and abs(p["frame"]["normal"][2]) > 0.999), None),
    # 'curves_added' is the LINE collection's own delta, so a single line reads 1 - the floor the
    # composite kinds (rectangle 4, polygon 6, slot 3) are counted against.
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": -70, "y1": 0, "x2": 70, "y2": 0,
                                           "is_construction": True}],
                             "sketch_name": "Skeleton"},
     lambda p: p["results"][0].get("curves_added") == 1, None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 0, "y1": -70, "x2": 0, "y2": 70,
                                           "is_construction": True}],
                             "sketch_name": "Skeleton"}, "ok", None),
    # start/end are the created line's own SketchPoints read back in mm: a z that came back at a
    # different scale is the unit conversion, and a zero one is a line flattened onto the plane.
    ("sketch_add_3d_line", {"x1": 0, "y1": 0, "z1": -70, "x2": 0, "y2": 0, "z2": 70,
                            "sketch_name": "Skeleton"},
     lambda p: (abs(p["start"]["z"] + 70) < 1e-6 and abs(p["end"]["z"] - 70) < 1e-6
                and p["end_is_off_plane"] is True), None),
    # the camera has been fitted to an EMPTY document since the overture - the skeleton is the
    # first thing in the world worth looking at.
    _watch_all(),
    ("sketch_constrain", {"constraints": [{"constraint": "horizontal", "entity_one": "line:0"}],
                          "sketch_name": "Skeleton"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "distance", "entity_one": "point:0",
                                          "entity_two": "point:1", "value": "PartLen"}],
                          "sketch_name": "Skeleton"}, "ok", None),
    ("sketch_get", {"sketch_name": "Skeleton"}, "ok", None),
    # draw a helper constraint then delete it - the count drop is the read-back.
    ("sketch_delete_entity", {"sketch_name": "Skeleton", "target": "constraint:0"}, "ok", None),
    # THE BRACKET, drawn: the base footprint, the raised half of the stepped top, the pocket, and
    # the boss on the finished top. Every profile's SPANS are dimensioned to parameters, so the
    # resize act walks all of them; what stays authored is where each feature sits on the block -
    # the boss centre and the pocket's corner - which no dimension here pins.
    # 'active_component' is design.activeComponent read AFTER the activate; the handler's mismatch
    # guard is skipped when that read declines, so a null here is an activation nobody confirmed.
    ("design_activate_component", {"occurrence": "Bracket:1"},
     lambda p: bool(p["active_component"]) and p["active_component"] == p["component"], None),
    ("sketch_create", {"plane": "xy", "name": "BracketBody"}, "ok", None),
    # a rectangle is built BY a SketchLines factory, so its four sides are the delta counted.
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": -60, "y1": -40,
                                           "x2": 60, "y2": 40}],
                             "sketch_name": "BracketBody"},
     lambda p: p["results"][0].get("curves_added") == 4, None),
    # EACH SPAN DIMENSIONED ACROSS ONE EDGE'S OWN TWO ENDPOINTS. A bare 'point:N' is refused as an
    # anchor by sketch_dimension's own contract - point:0 is the sketch ORIGIN - and an
    # origin-anchored span drives a CORNER's distance from the origin, not the width of the
    # rectangle. Anchored on the edge, whichever endpoint the solver frees, the span it leaves IS
    # the parameter. line:0 is the first line addTwoPointRectangle draws (the y1 edge, horizontal)
    # and line:1 the next (the x2 edge, vertical).
    ("sketch_dimension", {"dimensions": [{"dim_type": "horizontal_distance",
                                          "entity_one": "line:0:start", "entity_two": "line:0:end",
                                          "value": "PartLen"}],
                          "sketch_name": "BracketBody"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "vertical_distance",
                                          "entity_one": "line:1:start", "entity_two": "line:1:end",
                                          "value": "PartWid"}],
                          "sketch_name": "BracketBody"}, "ok", None),
    # the step floor: the low half of the stepped top, and the face the pocket is cut down from.
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": "PartHt - StepDrop",
                            "name": "StepFloor"}, _datum_plane("xy"), None),
    ("sketch_create", {"plane": "StepFloor", "name": "BracketStep"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": -10, "y1": -40,
                                           "x2": 60, "y2": 40}],
                             "sketch_name": "BracketStep"}, "ok", None),
    # The raised half's WIDTH follows the part; its LENGTH stays authored on purpose. A driven
    # length changes the block's span but not which end the solver grows it from, and a step whose
    # length moved with it could take the low shelf out from under the holes drilled into it.
    ("sketch_dimension", {"dimensions": [{"dim_type": "vertical_distance",
                                          "entity_one": "line:1:start", "entity_two": "line:1:end",
                                          "value": "PartWid"}],
                          "sketch_name": "BracketStep"}, "ok", None),
    # THE POCKET IS DRAWN ON ITS OWN FLOOR, not on the face it opens through: the cut then runs
    # UPWARD out of solid material, which is the direction that has a body in it. Measured: the
    # same profile on the step floor cutting down answers '3 : No target body found to cut'.
    ("model_construction", {"kind": "plane", "plane": "xy",
                            "offset": "PartHt - StepDrop - PocketDepth", "name": "PocketFloor"},
     _datum_plane("xy"), None),
    ("sketch_create", {"plane": "PocketFloor", "name": "BracketPocket"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": -50, "y1": -22,
                                           "x2": -20, "y2": 22}],
                             "sketch_name": "BracketPocket"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "horizontal_distance",
                                          "entity_one": "line:0:start", "entity_two": "line:0:end",
                                          "value": "PocketLen"}],
                          "sketch_name": "BracketPocket"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "vertical_distance",
                                          "entity_one": "line:1:start", "entity_two": "line:1:end",
                                          "value": "PocketWid"}],
                          "sketch_name": "BracketPocket"}, "ok", None),
    # the boss stands on the FINISHED top, so its plane is the part's full height.
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": "PartHt",
                            "name": "TopFloor"}, _datum_plane("xy"), None),
    ("sketch_create", {"plane": "TopFloor", "name": "BracketBoss"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 45, "cy": 0, "radius": 10}],
                             "sketch_name": "BracketBoss"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "diameter", "entity_one": "circle:0",
                                          "value": "BossDia"}],
                          "sketch_name": "BracketBoss"}, "ok", None),
    # the engraved nameplate, on the high half of the stepped top.
    ("sketch_create", {"plane": "TopFloor", "name": "NamePlate"}, "ok", None),
    ("sketch_set_text", {"text": "FUSION ESSENTIALS", "sketch_name": "NamePlate", "create": True,
                         "height": 5, "x": -5, "y": -32}, "ok", None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    _watch_all(),                       # the whole part is drawn
]

_PARAM_END = next(i for i, row in enumerate(_SKELETON)
                  if row[0] == "param_get" and isinstance(row[1], dict)
                  and row[1] == {})
_BRACKET_COMPONENT_START = next(i for i, row in enumerate(_SKELETON)
                                if row[0] == "model_create_component"
                                and isinstance(row[1], dict) and row[1].get("name") == "Bracket")
_BRACKET_PROFILE_START = next(i for i, row in enumerate(_SKELETON)
                              if row[0] == "design_activate_component"
                              and isinstance(row[1], dict)
                              and row[1].get("occurrence") == "Bracket:1")
_BRACKET_PROFILE_END = next(i for i, row in enumerate(_SKELETON)
                            if row[0] == "sketch_dimension" and isinstance(row[1], dict)
                            and row[1].get("sketch_name") == "BracketBoss")
BRACKET_PARAMETERS = _SKELETON[:_PARAM_END + 1]
_BRACKET_COMPONENT = _SKELETON[_PARAM_END + 1:_BRACKET_COMPONENT_START + 1]
_SKELETON_BENCH = _SKELETON[_BRACKET_COMPONENT_START + 1:_BRACKET_PROFILE_START]
BRACKET_PROFILES = _SKELETON[_BRACKET_PROFILE_START:_BRACKET_PROFILE_END + 1]
_BRACKET_SKETCH_TAIL = _SKELETON[_BRACKET_PROFILE_END + 1:]
_BRACKET_PROFILE_ROOT = next(row for row in _BRACKET_SKETCH_TAIL
                             if row[0] == "design_activate_component"
                             and isinstance(row[1], dict) and row[1].get("occurrence") == "root")
BRACKET_PARAMETERS_PROFILES = (BRACKET_PARAMETERS + _BRACKET_COMPONENT + BRACKET_PROFILES
                               + [_BRACKET_PROFILE_ROOT])
_SKELETON = (BRACKET_PARAMETERS + _BRACKET_COMPONENT + _SKELETON_BENCH
             + BRACKET_PROFILES + _BRACKET_SKETCH_TAIL)

# --- the sketch TOOLS, as their own act: every beat that needs no solid, so the run draws before
# it builds. What is missing from here is only what cannot be sketched in an empty
# document - a dimension MEASURED to a model face, a text path REFUSED a model edge - and those
# few beats stay in _DETAILS, next to the bodies they read.
_SKETCHWORK = [
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # sketch_edit_curve: one sketch per action, so no edit can perturb the next.
    ("sketch_create", {"plane": "xy", "name": "EditTrim"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 0, "x2": 700, "y2": 0}],
                             "sketch_name": "EditTrim"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 650, "y1": -50,
                                           "x2": 650, "y2": 50}],
                             "sketch_name": "EditTrim"}, "ok", None),
    ("sketch_edit_curve", {"sketch_name": "EditTrim", "action": "trim", "entity_one": "line:0",
                           "x1": 610, "y1": 0},
     lambda p: [r.get("length") for r in p.get("resulting", [])] == [50.0], None),
    ("sketch_create", {"plane": "xy", "name": "EditExt"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 10,
                                           "x2": 630, "y2": 10}],
                             "sketch_name": "EditExt"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 680, "y1": -20,
                                           "x2": 680, "y2": 40}],
                             "sketch_name": "EditExt"}, "ok", None),
    # extend returns an EMPTY collection on success, so the verdict is the curve's own length:
    # 30 mm reaching the crossing line at x=680 makes it 80.
    ("sketch_edit_curve", {"sketch_name": "EditExt", "action": "extend", "entity_one": "line:0",
                           "x1": 628, "y1": 10},
     lambda p: [r.get("length") for r in p.get("resulting", [])] == [80.0], None),
    ("sketch_create", {"plane": "xy", "name": "EditSplit"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 0, "x2": 700, "y2": 0}],
                             "sketch_name": "EditSplit"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 650, "y1": -50,
                                           "x2": 650, "y2": 50}],
                             "sketch_name": "EditSplit"}, "ok", None),
    # both halves are 50 long and must carry DISTINCT ids - the two pieces share one entityToken,
    # so an id resolved by token would report the same curve twice.
    ("sketch_edit_curve", {"sketch_name": "EditSplit", "action": "split", "entity_one": "line:0",
                           "x1": 650, "y1": 0},
     lambda p: [r.get("length") for r in p.get("resulting", [])] == [50.0, 50.0]
     and len({r.get("id") for r in p.get("resulting", [])}) == 2, None),
    ("design_get", {"include": ["timeline"], "max_results": 200}, "ok",
     ("split_history", _recall("split_history", lambda p: p["timeline"]))),
    ("sketch_get", {"sketch_name": "EditSplit", "include_entities": True}, _split_public(0),
     ("split_targets", lambda p: _RECALL["split_targets"])),
    ("sketch_constrain", lambda c: {"sketch_name": "EditSplit", "constraints": [
        {"constraint": "horizontal", "entity_one": _ctx_get(c, "split_targets", "endpoint-selected split ids")[0]}]}, "ok", None),
    ("sketch_get", {"sketch_name": "EditSplit", "include_entities": True}, _split_public(1), None),
    ("design_get", {"include": ["timeline"], "max_results": 200}, _split_history, None),
    ("sketch_constrain", lambda c: {"sketch_name": "EditSplit", "constraints": [
        {"constraint": "horizontal", "entity_one": _ctx_get(c, "split_targets", "endpoint-selected split ids")[1]}]}, "ok", None),
    ("sketch_get", {"sketch_name": "EditSplit", "include_entities": True}, _split_public(2), None),
    ("design_get", {"include": ["timeline"], "max_results": 200}, _split_history, None),
    ("sketch_create", {"plane": "xy", "name": "EditCorner"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 0, "x2": 660, "y2": 0}],
                             "sketch_name": "EditCorner"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 660, "y1": 0,
                                           "x2": 660, "y2": 40}],
                             "sketch_name": "EditCorner"}, "ok", None),
    ("sketch_edit_curve", {"sketch_name": "EditCorner", "action": "fillet", "entity_one": "line:0",
                           "x1": 655, "y1": 0, "entity_two": "line:1", "x2": 660, "y2": 5,
                           "radius": 10},
     lambda p: abs((p.get("resulting") or [{}])[0].get("length", 0) - 15.708) < 0.01, None),
    ("sketch_create", {"plane": "xy", "name": "EditChamfer"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 0, "x2": 660, "y2": 0}],
                             "sketch_name": "EditChamfer"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 660, "y1": 0,
                                           "x2": 660, "y2": 40}],
                             "sketch_name": "EditChamfer"}, "ok", None),
    ("sketch_edit_curve", {"sketch_name": "EditChamfer", "action": "chamfer",
                           "entity_one": "line:0", "x1": 655, "y1": 0, "entity_two": "line:1",
                           "x2": 660, "y2": 5, "distance": 8},
     lambda p: abs((p.get("resulting") or [{}])[0].get("length", 0) - 11.3137) < 0.01, None),
    ("sketch_create", {"plane": "xy", "name": "EditOffset"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 0, "x2": 700, "y2": 0}],
                             "sketch_name": "EditOffset"}, "ok", None),
    # the direction point picks the side: above the line offsets to +y
    ("sketch_edit_curve", {"sketch_name": "EditOffset", "action": "offset", "entity_one": "line:0",
                           "x1": 650, "y1": 20, "distance": 15},
     lambda p: p.get("curve_count_after") == 2, None),
    ("sketch_edit_curve", {"sketch_name": "EditOffset", "action": "chamfer", "entity_one": "line:0",
                           "x1": 650, "y1": 0, "entity_two": "line:1", "x2": 650, "y2": 15,
                           "distance": 5}, "refused", None),
    # sketch_move / sketch_copy: a transform is verified by COORDINATES, never by the API's bool -
    # Sketch.move returns true for an entity a constraint held still. A two-line chain on its own
    # clear band carries every beat below.
    ("sketch_create", {"plane": "xy", "name": "XformSrc"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 500,
                                           "x2": 650, "y2": 500}],
                             "sketch_name": "XformSrc"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 650, "y1": 500,
                                           "x2": 650, "y2": 540}],
                             "sketch_name": "XformSrc"}, "ok", None),
    # the copied collection counts the copied ENDPOINTS as well as the curves - 6 entities for a
    # two-line chain - so the target's own curve count is the honest read-back, and the new refs
    # are identity-matched against the target's collections.
    ("sketch_copy", {"sketch_name": "XformSrc", "entities": "line:0,line:1", "dx": 100},
     lambda p: p.get("curve_count_after", 0) - p.get("curve_count_before", 0) == 2
     and p.get("new_curves") == ["line:2", "line:3"]
     and p.get("returned_entity_count") == 6, None),
    # WHERE they landed: a count-only check passes a copy dropped on top of the original, so the
    # copy is read back at its offset position (x 600 -> 700).
    ("sketch_get", {"sketch_name": "XformSrc", "include_entities": True},
     lambda p: any(abs((e.get("start") or {}).get("x", 0) - _px("XformSrc", 700)) < 0.01
                   for e in (p.get("entities") or []) if e.get("type") == "line"), None),
    # move the ORIGINAL: line:0 runs 600->650 at y=500 and must land at 620->670, y=530.
    ("sketch_move", {"sketch_name": "XformSrc", "entities": "line:0", "dx": 20, "dy": 30},
     lambda p: p.get("moved_entities") == ["line:0"] and not p.get("unmoved_entities"), None),
    ("sketch_get", {"sketch_name": "XformSrc", "include_entities": True},
     lambda p: any(abs((e.get("start") or {}).get("x", 0) - _px("XformSrc", 620)) < 0.01
                   and abs((e.get("start") or {}).get("y", 0) - _py("XformSrc", 530)) < 0.01
                   for e in (p.get("entities") or []) if e.get("type") == "line"), None),
    # 180 deg about the line's OWN midpoint: the bounding box is identical afterwards and only the
    # endpoints swap, so the move is seen by the endpoint fingerprint and by nothing coarser.
    ("sketch_move", {"sketch_name": "XformSrc", "entities": "line:0", "rotation_deg": 180,
                     "center_x": 645, "center_y": 530},
     lambda p: p.get("moved_entities") == ["line:0"], None),
    # a cross-sketch copy lands in the TARGET, whose count rises from zero.
    ("sketch_create", {"plane": "xy", "name": "XformDst"}, "ok", None),
    # ONE curve across into an empty target - and the note states the id rule that holds for a COPY:
    # an added curve APPENDS, so the ids already in use keep their entities. Removing a curve is what
    # RENUMBERS (sketch_edit_curve's rule), and saying so here would be wrong for this call.
    ("sketch_copy", {"sketch_name": "XformSrc", "target_sketch": "XformDst",
                     "entities": "line:1", "dx": 0, "dy": -60},
     lambda p: p.get("target_sketch") == "XformDst" and p.get("curve_count_before") == 0
     and p.get("curve_count_after") == 1
     and "APPENDS" in (p.get("note") or "") and "RENUMBER" not in (p.get("note") or ""), None),
    # an IDENTITY copy (no dx/dy/rotation/scale) into a DIFFERENT target sketch: 'nothing to apply'
    # is refused only when the target IS the source, never for a target that merely asks for no
    # transform - so this lands, and the target's own curve count is the independent read-back.
    ("sketch_copy", {"sketch_name": "XformSrc", "target_sketch": "XformDst", "entities": "line:0"},
     lambda p: p.get("copied") is True and p.get("target_sketch") == "XformDst"
     and p.get("curve_count_before") == 1 and p.get("curve_count_after") == 2, None),
    ("sketch_get", {"sketch_name": "XformDst", "include_entities": True},
     lambda p: p.get("counts", {}).get("lines") == 2, None),
    # a mirror asked for as a negative scale, and a transform that asks for nothing: neither runs.
    ("sketch_move", {"sketch_name": "XformDst", "entities": "line:0", "scale_factor": -1},
     "refused", None),
    ("sketch_move", {"sketch_name": "XformDst", "entities": "line:0"}, "refused", None),
    # the same copy inside a COMPONENT sketch - the occurrence-proxy seam. Sketch.copy hands back
    # assembly-context proxies whose own tokens are NOT the landed curves', so a ref can only be
    # named through each proxy's native entity: an empty 'new_curves' beside a count that rose is
    # the seam breaking, and 'new_curves_complete' appears only when refs went missing.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "CopyComp", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "CompCopyS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1400, "y1": 0,
                                           "x2": 1450, "y2": 0}],
                             "sketch_name": "CompCopyS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1450, "y1": 0,
                                           "x2": 1450, "y2": 40}],
                             "sketch_name": "CompCopyS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1450, "y1": 40,
                                           "x2": 1400, "y2": 40}],
                             "sketch_name": "CompCopyS"}, "ok", None),
    ("sketch_copy", {"sketch_name": "CompCopyS", "entities": "line:0,line:1,line:2", "dy": 60},
     lambda p: p.get("new_curves") == ["line:3", "line:4", "line:5"]
     and p.get("curve_count_after", 0) - p.get("curve_count_before", 0) == 3
     and "new_curves_complete" not in p, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # autoConstrain takes the whole sketch: a loose rectangle flips is_fully_constrained to true,
    # and the added counts are read off the sketch's own collections.
    # THE CONSTRAINT BENCH - one scratch sketch carrying a spread of constraint kinds, several of
    # them taking TWO operands, each verified by the sketch's own constrained-state read rather than
    # by the call returning ok. Geometric constraints are what make a sketch a MODEL rather than a
    # picture, and a surface that only ever ran 'auto' has never shown that.
    ("sketch_create", {"plane": "xy", "name": "ConBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 480,
                                           "x2": 680, "y2": 486}],
                             "sketch_name": "ConBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 500,
                                           "x2": 676, "y2": 512}],
                             "sketch_name": "ConBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 700, "y1": 480,
                                           "x2": 706, "y2": 530}],
                             "sketch_name": "ConBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 640, "cy": 545, "radius": 14}],
                             "sketch_name": "ConBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 676, "cy": 545, "radius": 9}],
                             "sketch_name": "ConBench"}, "ok", None),
    # HORIZONTAL takes one operand; the rest below each take two.
    ("sketch_constrain", {"constraints": [{"constraint": "horizontal", "entity_one": "line:0"}],
                          "sketch_name": "ConBench"},
     lambda p: p["results"][0].get("applied") == "horizontal", None),
    ("sketch_constrain", {"constraints": [{"constraint": "parallel", "entity_one": "line:1",
                                           "entity_two": "line:0"}],
                          "sketch_name": "ConBench"},
     lambda p: p["results"][0].get("applied") == "parallel", None),
    ("sketch_constrain", {"constraints": [{"constraint": "perpendicular", "entity_one": "line:2",
                                           "entity_two": "line:0"}],
                          "sketch_name": "ConBench"},
     lambda p: p["results"][0].get("applied") == "perpendicular", None),
    ("sketch_constrain", {"constraints": [{"constraint": "equal", "entity_one": "circle:0",
                                           "entity_two": "circle:1"}],
                          "sketch_name": "ConBench"},
     lambda p: p["results"][0].get("applied") == "equal", None),
    # SYMMETRY takes three: the pair, and the line they mirror across.
    ("sketch_constrain", {"constraints": [{"constraint": "symmetry", "entity_one": "circle:0",
                                           "entity_two": "circle:1",
                                           "symmetry_line": "line:2"}],
                          "sketch_name": "ConBench"},
     lambda p: p["results"][0].get("applied") == "symmetry"
     and p["results"][0].get("symmetry_line") == "line:2", None),
    # MIDPOINT puts a line's own end at the middle of another - a point-and-curve pair.
    ("sketch_constrain", {"constraints": [{"constraint": "midpoint", "entity_one": "line:1:start",
                                           "entity_two": "line:0"}],
                          "sketch_name": "ConBench"},
     lambda p: p["results"][0].get("applied") == "midpoint", None),
    # the state read is the verdict: the sketch is MORE constrained than it was, and the tool's
    # own count of what it added is what says so - a call that returned ok and added nothing is a
    # silent no-op, which is the failure this beat exists to catch.
    ("sketch_get", {"sketch_name": "ConBench"},
     lambda p: p.get("constraint_count", 0) >= 6, None),
    # a constraint the geometry cannot satisfy is REFUSED by name, not silently dropped.
    ("sketch_constrain", {"constraints": [{"constraint": "tangent", "entity_one": "line:0",
                                           "entity_two": "line:1"}],
                          "sketch_name": "ConBench"}, "refused", None),
    # THE SECOND BENCH: the constraint kinds the first has no geometry for. Deliberately its own
    # sketch - every curve on ConBench is already pinned by the constraints above, and stacking more
    # onto them refuses as over-constrained instead of proving anything. Two ordering facts drive
    # the refs: a fresh sketch owns its ORIGIN as point:0, so the first drawn point is point:1; and
    # the kinds that CREATE curves run in sketches of their own, below, because a new curve renumbers
    # every ref written after it.
    ("sketch_create", {"plane": "xy", "name": "ConBench2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 860, "y1": 480,
                                           "x2": 930, "y2": 486}],
                             "sketch_name": "ConBench2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 945, "y1": 489,
                                           "x2": 1000, "y2": 495}],
                             "sketch_name": "ConBench2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 860, "y1": 505,
                                           "x2": 866, "y2": 560}],
                             "sketch_name": "ConBench2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 880, "y1": 505,
                                           "x2": 920, "y2": 511}],
                             "sketch_name": "ConBench2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 880, "y1": 590,
                                           "x2": 920, "y2": 602}],
                             "sketch_name": "ConBench2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 940, "y1": 505,
                                           "x2": 980, "y2": 545}],
                             "sketch_name": "ConBench2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 880, "cy": 660, "radius": 20}],
                             "sketch_name": "ConBench2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 884, "cy": 664, "radius": 10}],
                             "sketch_name": "ConBench2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "spline",
                                           "points": [[920, 602], [950, 616], [980, 600]]}],
                             "sketch_name": "ConBench2"}, "ok", None),
    ("sketch_constrain", {"constraints": [{"constraint": "vertical", "entity_one": "line:2"}],
                          "sketch_name": "ConBench2"},
     lambda p: p["results"][0].get("applied") == "vertical", None),
    ("sketch_constrain", {"constraints": [{"constraint": "collinear", "entity_one": "line:1",
                                           "entity_two": "line:0"}],
                          "sketch_name": "ConBench2"},
     lambda p: p["results"][0].get("applied") == "collinear", None),
    ("sketch_constrain", {"constraints": [{"constraint": "concentric", "entity_one": "circle:1",
                                           "entity_two": "circle:0"}],
                          "sketch_name": "ConBench2"},
     lambda p: p["results"][0].get("applied") == "concentric", None),
    # the spline continues the line it was drawn from, sharing that endpoint, and 'smooth' makes the
    # join curvature-continuous - the one kind that needs a spline on at least one side.
    ("sketch_constrain", {"constraints": [{"constraint": "smooth", "entity_one": "spline:0",
                                           "entity_two": "line:4"}],
                          "sketch_name": "ConBench2"},
     lambda p: p["results"][0].get("applied") == "smooth", None),
    # the square's four lines told they ARE a polygon - equal lengths and equal angles in one
    # constraint instead of six.
    ("sketch_constrain", {"constraints": [{"constraint": "polygon",
                                           "entities": "line:5,line:6,line:7,line:8"}],
                          "sketch_name": "ConBench2"},
     lambda p: p["results"][0].get("applied") == "polygon", None),
    ("sketch_get", {"sketch_name": "ConBench2", "include_entities": True, "max_results": 200},
     _polygon_witness, None),
    # fix pins a curve where it sits; unfix releases the same one, so the pair is checkable as a
    # pair - a 'fix' that silently did nothing leaves nothing for 'unfix' to find.
    ("sketch_constrain", {"constraints": [{"constraint": "fix", "entity_one": "line:3"}],
                          "sketch_name": "ConBench2"},
     lambda p: p["results"][0].get("applied") == "fix"
     and "endpoints can still move" in (p["results"][0].get("note") or ""), None),
    # A fixed line's ends still move under a driving mid-to-end dimension; the read names it.
    ("sketch_dimension", {"dimensions": [{"dim_type": "horizontal_distance",
                                          "entity_one": "line:3:mid", "entity_two": "line:3:end",
                                          "value": "15 mm"}],
                          "sketch_name": "ConBench2"},
     lambda p: p["results"][0].get("fixed_entity_moved") == ["line:3"], None),
    ("sketch_get", {"sketch_name": "ConBench2", "include_entities": True, "max_results": 200},
     _fixed_line_moved, ("conbench2_dims", _recall("conbench2_dims",
                                                   lambda p: p["dimension_count"]))),
    ("sketch_constrain", {"constraints": [{"constraint": "unfix", "entity_one": "line:3"}],
                          "sketch_name": "ConBench2"},
     lambda p: p["results"][0].get("applied") == "unfix", None),
    # The pair: with line:0 AND its two end points fixed, the same dimension is over-constrained.
    ("sketch_constrain", _fix_line0_and_ends, lambda p: p.get("constrained") == 3, None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "horizontal_distance",
                                          "entity_one": "line:0:mid", "entity_two": "line:0:end",
                                          "value": "30 mm"}],
                          "sketch_name": "ConBench2"}, _refused("OVER_CONSTRAINT"), None),
    ("sketch_get", {"sketch_name": "ConBench2", "include_entities": True, "max_results": 200},
     _endpoint_fixed_held, None),
    # THE POINT-PAIR KINDS, on four free stubs of their own. They take POINTS, and a bare 'point:N'
    # counts every point the sketch owns - a line's own endpoints included - so 'point:1' on a
    # sketch holding curves is the first line's start, not the first point drawn. Anchored refs name
    # the endpoint directly, which is the whole reason the anchor form exists.
    ("sketch_create", {"plane": "xy", "name": "PtBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1060, "y1": 300,
                                           "x2": 1090, "y2": 306}],
                             "sketch_name": "PtBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1110, "y1": 296,
                                           "x2": 1140, "y2": 304}],
                             "sketch_name": "PtBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1060, "y1": 340,
                                           "x2": 1090, "y2": 348}],
                             "sketch_name": "PtBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1066, "y1": 380,
                                           "x2": 1096, "y2": 388}],
                             "sketch_name": "PtBench"}, "ok", None),
    # two stubs made LEVEL by their start points, and two made PLUMB by theirs - no curve is
    # constrained either time, which is what separates these from plain horizontal/vertical.
    ("sketch_constrain", {"constraints": [{"constraint": "horizontal_points",
                                           "entity_one": "line:0:start",
                                           "entity_two": "line:1:start"}],
                          "sketch_name": "PtBench"},
     lambda p: p["results"][0].get("applied") == "horizontal_points", None),
    ("sketch_constrain", {"constraints": [{"constraint": "vertical_points",
                                           "entity_one": "line:2:start",
                                           "entity_two": "line:3:start"}],
                          "sketch_name": "PtBench"},
     lambda p: p["results"][0].get("applied") == "vertical_points", None),
    # THE CREATOR KINDS. Each gets its own sketch: an offset lands NEW curves, so a second one
    # written against the same sketch would be aimed at refs the first has already renumbered. The
    # verdict is 'created_count' - a constraint that returned ok and drew nothing is the silent
    # no-op these rows exist to catch.
    ("sketch_create", {"plane": "xy", "name": "OffOne"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 860, "y1": 730,
                                           "x2": 940, "y2": 730}],
                             "sketch_name": "OffOne"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 940, "y1": 730,
                                           "x2": 940, "y2": 790}],
                             "sketch_name": "OffOne"}, "ok", None),
    ("sketch_constrain", {"constraints": [{"constraint": "offset", "entities": "line:0,line:1",
                                           "distance": 8}],
                          "sketch_name": "OffOne"},
     lambda p: p["results"][0].get("applied") == "offset"
     and p["results"][0].get("created_count", 0) >= 2, None),
    ("sketch_get", {"sketch_name": "OffOne", "include_entities": True, "max_results": 200},
     _offset_witness, None),
    ("sketch_create", {"plane": "xy", "name": "OffTwo"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 960, "y1": 730,
                                           "x2": 1040, "y2": 730}],
                             "sketch_name": "OffTwo"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1040, "y1": 730,
                                           "x2": 1040, "y2": 790}],
                             "sketch_name": "OffTwo"}, "ok", None),
    # the two-sided form draws the offset on BOTH sides of the source, so it lands twice the curves.
    ("sketch_constrain", {"constraints": [{"constraint": "offset_two_sides",
                                           "entities": "line:0,line:1", "distance": 8}],
                          "sketch_name": "OffTwo"},
     lambda p: p["results"][0].get("applied") == "offset_two_sides"
     and p["results"][0].get("created_count", 0) >= 4, None),
    ("sketch_create", {"plane": "xy", "name": "CircPat"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "point", "cx": 900, "cy": 880}],
                             "sketch_name": "CircPat"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 940, "cy": 880, "radius": 6}],
                             "sketch_name": "CircPat"}, "ok", None),
    # six around the drawn centre point: five NEW circles, the original not counted.
    ("sketch_constrain", {"constraints": [{"constraint": "circular_pattern",
                                           "entities": "circle:0", "entity_one": "point:1",
                                           "quantity": 6, "angle": 360}],
                          "sketch_name": "CircPat"},
     lambda p: p["results"][0].get("applied") == "circular_pattern"
     and p["results"][0].get("created_count") == 5, None),
    # THE DIMENSION BENCH: the sizing kinds the story's own sketches never need. Each one names a
    # different pair of operand types, so each needs its own geometry - a circle pair sharing a
    # centre, a line and a circle for the tangent measure, and an ellipse for the two radius kinds.
    # Every row reads the LANDED value back: a dimension that attached to the wrong entity still
    # returns ok, and only its measured number says so.
    ("sketch_create", {"plane": "xy", "name": "DimBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1060, "y1": 480,
                                           "x2": 1120, "y2": 500}],
                             "sketch_name": "DimBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 1090, "cy": 560, "radius": 24}],
                             "sketch_name": "DimBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 1090, "cy": 560, "radius": 12}],
                             "sketch_name": "DimBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1140, "y1": 530,
                                           "x2": 1140, "y2": 590}],
                             "sketch_name": "DimBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "ellipse", "cx": 1090, "cy": 650,
                                           "radius": 30, "minor": 16}],
                             "sketch_name": "DimBench"}, "ok", None),
    # These parallel lines exist before the ellipse dimensions mint construction axes ahead of them.
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1095, "y1": 506,
                                           "x2": 1130, "y2": 506}],
                             "sketch_name": "DimBench"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1095, "y1": 526,
                                           "x2": 1130, "y2": 526}],
                             "sketch_name": "DimBench"}, "ok", None),
    # the horizontal component of a slanted line's own span: 60 mm across, not its 63.2 mm length.
    ("sketch_dimension", {"dimensions": [{"dim_type": "horizontal_distance",
                                          "entity_one": "line:0:start",
                                          "entity_two": "line:0:end"}],
                          "sketch_name": "DimBench"},
     _dim_measures(60.0), None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "diameter", "entity_one": "circle:0"}],
                          "sketch_name": "DimBench"}, _dim_measures(48.0), None),
    # the gap between two circles on one centre: 24 mm outer less 12 mm inner.
    ("sketch_dimension", {"dimensions": [{"dim_type": "concentric_circle",
                                          "entity_one": "circle:0", "entity_two": "circle:1"}],
                          "sketch_name": "DimBench"},
     _dim_measures(12.0), None),
    # line to the NEAR tangent of the circle: the line stands at x 1140, the circle's near side at
    # 1090+24, so 26 mm.
    ("sketch_dimension", {"dimensions": [{"dim_type": "tangent_distance", "entity_one": "line:1",
                                          "entity_two": "circle:0"}],
                          "sketch_name": "DimBench"},
     _dim_measures(26.0), None),
    # Refuse both numeric point and line suffixes after the ellipse dimensions mint axes.
    ("sketch_dimension", {"dimensions": [
        {"dim_type": "ellipse_major_radius", "entity_one": "ellipse:0"},
        {"dim_type": "distance", "entity_one": "point:8", "entity_two": "point:9"},
        {"dim_type": "linear_diameter", "entity_one": "line:2", "entity_two": "line:3"}],
        "sketch_name": "DimBench"},
     _SketchBatchRefusal(lambda p: p.get("dimensioned") == 1
     and [r.get("dim_type") for r in p.get("results") or []] == ["ellipse_major_radius"]
     and p.get("failed", {}).get("index") == 1 and p.get("not_attempted") == 1
     and "'point:8'" in p["failed"]["error"] and "'point:9'" in p["failed"]["error"]
     and "construction axes and endpoints" in p["failed"]["error"]
     and "sketch_get(include_entities=true)" in p["failed"]["error"]
     and p.get("failed_entry_counts", {}).get("change") == {
         "curves": 0, "points": 0, "constraints": 0, "dimensions": 0}), None),
    ("sketch_dimension", {"dimensions": [
        {"dim_type": "ellipse_minor_radius", "entity_one": "ellipse:0"},
        {"dim_type": "linear_diameter", "entity_one": "line:2", "entity_two": "line:3"}],
        "sketch_name": "DimBench"},
     _SketchBatchRefusal(lambda p: p.get("dimensioned") == 1
     and [r.get("dim_type") for r in p.get("results") or []] == ["ellipse_minor_radius"]
     and p.get("failed", {}).get("index") == 1 and p.get("not_attempted") == 0
     and "'line:2'" in p["failed"]["error"] and "'line:3'" in p["failed"]["error"]
     and "construction axes and endpoints" in p["failed"]["error"]
     and "sketch_get(include_entities=true)" in p["failed"]["error"]
     and p.get("failed_entry_counts", {}).get("change") == {
         "curves": 0, "points": 0, "constraints": 0, "dimensions": 0}), None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "angle", "entity_one": "line:0",
                                          "entity_two": "line:1"}],
                          "sketch_name": "DimBench"}, _angle_measures, None),
    # sketch_get below supplies current line ids after both ellipse axes were added.
    ("sketch_get", {"sketch_name": "DimBench", "include_entities": True, "max_results": 200},
     "ok", ("dimbench_pair", _dimbench_pair_ids)),
    ("sketch_dimension", lambda c: {"dimensions": [{
        "dim_type": "linear_diameter",
        "entity_one": _ctx_get(c, "dimbench_pair", "DimBench parallel pair")[0],
        "entity_two": _ctx_get(c, "dimbench_pair", "DimBench parallel pair")[1]}],
        "sketch_name": "DimBench"}, _dim_measures(40.0), None),
    ("sketch_get", {"sketch_name": "DimBench", "include_entities": True, "max_results": 200},
     _dimbench_witness, None),
    # A SECOND COORDINATE DIMENSION AT A SHARED X: point:2 stands at the x point:1 is already
    # dimensioned to, and the solver refuses the second horizontal distance as over-constrained.
    # The refusal names point:1 and the two-point constraint that ties them. On XZ, so the sketch
    # is nailed where it is drawn and deals no new cell.
    ("sketch_create", {"plane": "xz", "name": "CoordDims"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "point", "cx": 1450, "cy": 120},
                                          {"kind": "point", "cx": 1450, "cy": 150}],
                             "sketch_name": "CoordDims"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "horizontal_distance",
                                          "entity_one": "point:0", "entity_two": "point:1"}],
                          "sketch_name": "CoordDims"}, _dim_measures(1450.0), None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "horizontal_distance",
                                          "entity_one": "point:0", "entity_two": "point:2"}],
                          "sketch_name": "CoordDims"},
     _refused("OVER_CONSTRAINT", "point:1 already stand(s) at the same x", "'vertical_points'"),
     None),
    # A missing first reference is a nonmutation control; the later valid entry stays unattempted.
    ("sketch_create", _retained_dims_create, "ok", None),
    ("sketch_add_geometry", {"geometry": [
        {"kind": "circle", "cx": 1180, "cy": 560, "radius": 10},
        {"kind": "circle", "cx": 1220, "cy": 560, "radius": 10},
        {"kind": "circle", "cx": 1260, "cy": 560, "radius": 10}],
        "sketch_name": "RetainedDims"}, "ok", None),
    ("sketch_get", {"sketch_name": "RetainedDims", "include_entities": True},
     lambda p: p.get("truncated") is False and _radial_state(p, [10, 10, 10], []), None),
    ("sketch_dimension", {"dimensions": [
        {"dim_type": "radius", "entity_one": "circle:99", "value": "1 mm +"},
        {"dim_type": "radius", "entity_one": "circle:0", "value": "8 mm"}],
        "sketch_name": "RetainedDims"},
     _refused("circle:99", "Nothing completed", "1 later entry was not attempted"), None),
    ("sketch_get", {"sketch_name": "RetainedDims", "include_entities": True},
     lambda p: p.get("truncated") is False and _radial_state(p, [10, 10, 10], []), None),
    # A rejected value on the first entry leaves one measured dimension and skips the suffix.
    ("sketch_dimension", {"dimensions": [
        {"dim_type": "radius", "entity_one": "circle:0", "value": "1 mm +"},
        {"dim_type": "radius", "entity_one": "circle:2", "value": "8 mm"}],
        "sketch_name": "RetainedDims"},
     _SketchBatchRefusal(lambda p: p.get("dimensioned") == 0 and p.get("results") == []
     and p.get("failed", {}).get("index") == 0 and p.get("not_attempted") == 1
     and len(p.get("retained") or []) == 1
     and p["retained"][0].get("index") == 0 and bool(p["retained"][0].get("parameter"))
     and p["retained"][0].get("value_driven") is False
     and p["retained"][0].get("is_driving") is True
     and "Nothing landed" not in (p.get("note") or ""),
     ("radial_first_wire", lambda p: p["retained"][0]["parameter"])), None),
    ("sketch_get", {"sketch_name": "RetainedDims", "include_entities": True},
     lambda p: p.get("truncated") is False and _radial_state(p, [10, 10, 10], [10]),
     ("radial_first_read", lambda p: p["dimensions"][0]["name"])),
    ("sketch_delete_entity", {"sketch_name": "RetainedDims", "target": "dimension:0"},
     lambda p: p.get("dimensions_before") == 1 and p.get("dimensions_after") == 0
     and bool(p.get("parameter")),
     ("radial_first_deleted", lambda p: p["parameter"])),
    ("sketch_get", _first_radial_cleanup_args,
     lambda p: p.get("truncated") is False and _radial_state(p, [10, 10, 10], []), None),
    # A valid prefix and failed second value publish separate completed and retained identities.
    ("sketch_dimension", {"dimensions": [
        {"dim_type": "radius", "entity_one": "circle:0", "value": "12 mm"},
        {"dim_type": "radius", "entity_one": "circle:1", "value": "1 mm +"},
        {"dim_type": "radius", "entity_one": "circle:2", "value": "8 mm"}],
        "sketch_name": "RetainedDims"},
     _SketchBatchRefusal(lambda p: p.get("dimensioned") == 1 and len(p.get("results") or []) == 1
     and p["results"][0].get("index") == 0 and p["results"][0].get("value_driven") is True
     and p["results"][0].get("is_driving") is True
     and len(p.get("retained") or []) == 1 and p["retained"][0].get("index") == 1
     and p["retained"][0].get("value_driven") is False
     and p["retained"][0].get("is_driving") is True
     and bool(p["results"][0].get("parameter")) and bool(p["retained"][0].get("parameter"))
     and p["results"][0].get("parameter") != p["retained"][0].get("parameter")
     and p.get("failed", {}).get("index") == 1 and p.get("not_attempted") == 1,
     ("radial_mixed", lambda p: {"completed": p["results"][0]["parameter"],
                                 "retained": p["retained"][0]["parameter"]})), None),
    ("sketch_get", {"sketch_name": "RetainedDims", "include_entities": True},
     lambda p: p.get("truncated") is False and _radial_state(p, [12, 10, 10], [10, 12]),
     ("radial_mixed_read", lambda p: {
         "completed": p["dimensions"][0]["name"], "retained": p["dimensions"][1]["name"]})),
    ("param_set", lambda c: {
        "name": _RECALL["radial_mixed"]["completed"],
        "expression": "10 mm"},
     lambda p: p.get("set") is True and p.get("created") is False
     and abs(p.get("before", {}).get("value", 0) - 12) < 1e-4
     and abs(p.get("after", {}).get("value", 0) - 10) < 1e-4,
     ("radial_mixed_set", lambda p: p["name"])),
    ("sketch_delete_entity", {"sketch_name": "RetainedDims", "target": "dimension:1"},
     lambda p: p.get("dimensions_before") == 2 and p.get("dimensions_after") == 1
     and bool(p.get("parameter")),
     ("radial_mixed_retained_deleted", lambda p: p["parameter"])),
    ("sketch_delete_entity", {"sketch_name": "RetainedDims", "target": "dimension:0"},
     lambda p: p.get("dimensions_before") == 1 and p.get("dimensions_after") == 0
     and bool(p.get("parameter")),
     ("radial_mixed_completed_deleted", lambda p: p["parameter"])),
    ("sketch_get", _mixed_radial_cleanup_args,
     lambda p: p.get("truncated") is False and _radial_state(p, [10, 10, 10], []), None),
    ("sketch_dimension", {"dimensions": [
        {"dim_type": "radius", "entity_one": "circle:0", "value": "12 mm"},
        {"dim_type": "radius", "entity_one": "circle:1", "value": "8 mm"}],
        "sketch_name": "RetainedDims"},
     lambda p: p.get("dimensioned") == 2 and len(p.get("results") or []) == 2
     and (p.get("result_note") or "").count("'solved' is each REFERENCED") == 1
     and all("'solved' is each REFERENCED" not in (r.get("note") or "")
             for r in p["results"])
     and [(r["solved"][0]["ref"], r["solved"][0]["radius_mm"])
          for r in p["results"]] == [("circle:0", 12), ("circle:1", 8)], None),
    ("sketch_get", {"sketch_name": "RetainedDims", "include_entities": True},
     lambda p: p.get("truncated") is False and _radial_state(p, [12, 8, 10], [8, 12]), None),
    ("sketch_create", {"plane": "xy", "name": "AutoCon"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 600, "y1": 560,
                                           "x2": 700, "y2": 600}],
                             "sketch_name": "AutoCon"}, "ok", None),
    ("sketch_get", {"sketch_name": "AutoCon"},
     lambda p: p.get("is_fully_constrained") is False, None),
    ("sketch_constrain", {"constraints": [{"constraint": "auto"}], "sketch_name": "AutoCon"},
     lambda p: p["results"][0].get("added_constraints", 0)
     + p["results"][0].get("added_dimensions", 0) > 0
     and p["results"][0].get("is_fully_constrained") is True, None),
    # a re-run on the constrained sketch adds nothing and is a clean no-op, not an error.
    ("sketch_constrain", {"constraints": [{"constraint": "auto"}], "sketch_name": "AutoCon"},
     lambda p: p["results"][0].get("added_dimensions") == 0
     and p["results"][0].get("added_constraints") == 0
     and p["results"][0].get("is_fully_constrained") is True, None),
    # the SECOND solver option, on a sketch of its own - option1 above is the default and the one
    # the payload names, so a request for the other has to come back named as the other or the knob
    # was dropped on the way in.
    ("sketch_create", {"plane": "xy", "name": "AutoCon2"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 720, "y1": 560,
                                           "x2": 820, "y2": 600}],
                             "sketch_name": "AutoCon2"}, "ok", None),
    ("sketch_constrain", {"constraints": [{"constraint": "auto", "result_option": "option2"}],
                          "sketch_name": "AutoCon2"},
     lambda p: p["results"][0].get("result_option_requested") == "option2"
     and p["results"][0].get("added_constraints", 0)
     + p["results"][0].get("added_dimensions", 0) > 0
     and p["results"][0].get("is_fully_constrained") is True, None),
    # rectangular_pattern with distance_type='extent': 'distance' is the pattern's TOTAL span, so
    # three instances 90 mm across sit at x 600 / 645 / 690 - the landed centre is the verdict, and
    # a spacing read in centimetres would put the last one at 609.
    ("sketch_create", {"plane": "xy", "name": "PatExtent"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 600, "cy": 640, "radius": 5}],
                             "sketch_name": "PatExtent"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 660,
                                           "x2": 700, "y2": 660}],
                             "sketch_name": "PatExtent"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 660,
                                           "x2": 600, "y2": 760}],
                             "sketch_name": "PatExtent"}, "ok", None),
    ("sketch_constrain", {"constraints": [{"constraint": "rectangular_pattern",
                                           "entities": "circle:0", "entity_one": "line:0",
                                           "entity_two": "line:1", "quantity": 3, "distance": 90,
                                           "quantity_two": 1, "distance_two": 10,
                                           "distance_type": "extent"}],
                          "sketch_name": "PatExtent"},
     lambda p: p["results"][0].get("distance_type") == "extent"
     and p["results"][0].get("created_count", 0) == 2, None),
    ("sketch_get", {"sketch_name": "PatExtent", "include_entities": True},
     lambda p: abs(max((e.get("center") or {}).get("x", 0) for e in (p.get("entities") or [])
                       if e.get("type") == "circle") - _px("PatExtent", 690.0)) < 0.01, None),
    # per-instance suppression: a 3x2 pattern of one circle has 5 SUPPRESSIBLE instances (the
    # original does not count), and the flags are read back off the CREATED constraint. A suppressed
    # instance draws no curve, so 5 instances less 2 suppressed is 3 new curves - the count and the
    # landed flags together are what an echoed payload cannot fake.
    ("sketch_create", {"plane": "xy", "name": "PatSupp"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 600, "cy": 800, "radius": 4}],
                             "sketch_name": "PatSupp"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 820,
                                           "x2": 700, "y2": 820}],
                             "sketch_name": "PatSupp"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 600, "y1": 820,
                                           "x2": 600, "y2": 920}],
                             "sketch_name": "PatSupp"}, "ok", None),
    ("sketch_constrain", {"constraints": [{"constraint": "rectangular_pattern",
                                           "entities": "circle:0", "entity_one": "line:0",
                                           "entity_two": "line:1", "quantity": 3,
                                           "quantity_two": 2, "distance": 20, "distance_two": 20,
                                           "suppressed": [False, True, False, True, False]}],
                          "sketch_name": "PatSupp"},
     lambda p: p["results"][0].get("suppressed_applied") == [False, True, False, True, False]
     and p["results"][0].get("created_count") == 3, None),
    # the N-1 length IS the input's contract: 6 flags for a 3x2 counts the original, and the guard
    # refuses it naming expected against got, before anything is created.
    ("sketch_constrain", {"constraints": [{"constraint": "rectangular_pattern",
                                           "entities": "circle:0", "entity_one": "line:0",
                                           "entity_two": "line:1", "quantity": 3,
                                           "quantity_two": 2, "distance": 20, "distance_two": 20,
                                           "suppressed": [False] * 6}],
                          "sketch_name": "PatSupp"}, "refused", None),
    # a knob whose input object exists on ONE constraint only is refused elsewhere, never dropped.
    ("sketch_constrain", {"constraints": [{"constraint": "horizontal", "entity_one": "line:0",
                                           "dimension_strategy": "chain"}],
                          "sketch_name": "PatSupp"}, "refused", None),
    # autoConstrain's four dimensioning-strategy setters are UNAVAILABLE on this build - the input
    # object refuses the assignment ("This API is not currently available") - so the request is
    # refused NAMING the knob that would not take, before autoConstrain runs and before anything is
    # constrained. Plain constraint='auto' still solves (the beats above), and this beat is the one
    # that fails loudly if a strategy is ever quietly dropped instead.
    ("sketch_create", {"plane": "xy", "name": "AutoStrat"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 740, "y1": 800,
                                           "x2": 840, "y2": 850}],
                             "sketch_name": "AutoStrat"}, "ok", None),
    ("sketch_constrain", {"constraints": [{"constraint": "auto",
                                           "dimension_strategy": "baseline",
                                           "linear_diameter_dims": "avoid"}],
                          "sketch_name": "AutoStrat"}, "refused", None),
    # sketch_insert_svg: art from local disk into a FRESH sketch. importSVG ignores the file's own
    # width/height and viewBox - 1 SVG user unit lands as 1/96 inch times 'scale' - so the 36-unit
    # rectangle measures ~36 mm at scale=3.7795 and nothing else can produce that width. The art is
    # placed AT the sketch origin, so this empty-before sketch's own box IS the art's size.
    ("sketch_create", {"plane": "xy", "name": "SvgTarget"}, "ok", None),
    ("sketch_insert_svg", {"file_path": SVG_PATH, "sketch_name": "SvgTarget", "scale": 3.7795},
     lambda p: p.get("curves_added", 0) > 0 and p.get("sketch") == "SvgTarget"
     and 30 < (p.get("sketch_extent") or {}).get("width", 0) < 42, None),
    # SK-5's closure, through the TOOL: the 96-user-unit square at scale 1 is exactly one inch, and
    # the art lands Y-DOWN from the sketch origin - so this empty-before sketch measures 25.4 mm
    # square with its min y at -25.4. A y-up landing (or any scale drift) moves that number.
    ("sketch_create", {"plane": "xy", "name": "Svg96"}, "ok", None),
    ("sketch_insert_svg", {"file_path": SVG96_PATH, "sketch_name": "Svg96", "scale": 1},
     _svg96_extent, None),
    # importSVG RAISES on a path that is not a file and that raise rolls back the whole surrounding
    # transaction, so the miss is named before Fusion is touched.
    ("sketch_insert_svg", {"file_path": EXPORT_DIR + "/no_such_logo.svg",
                           "sketch_name": "SvgTarget"}, "refused", None),
    # Wave-3 sketch surface: the new curve kinds + dimension types, each asserting a read-back
    # the payload could not echo (the degree clamp, the wedge rule, the offset rotation, and the
    # API's own self-naming parallelism raises - all measured contracts).
    ("sketch_create", {"plane": "xy", "name": "W3Curves"}, "ok", None),
    # degree 5 over 3 control points: the API silently CLAMPS to n-1, and the payload publishes
    # the BUILT degree read off the spline - 2 here is a live read-back, not an echo of the 5.
    ("sketch_add_geometry", {"geometry": [{"kind": "cv_spline",
                                           "points": [[740, 0], [760, 20], [780, 0]],
                                           "degree": 5}],
                             "sketch_name": "W3Curves"},
     lambda p: p["results"][0].get("degree") == 2, None),
    ("sketch_add_geometry", {"geometry": [{"kind": "cv_spline",
                                           "points": [[740, -40], [750, -20], [760, -40],
                                                      [770, -20], [780, -40], [790, -20]],
                                           "degree": 5}],
                             "sketch_name": "W3Curves"},
     lambda p: p["results"][0].get("degree") == 5, None),
    # 'minor' omitted: the label reports the EFFECTIVE minor radius (major/2), never None.
    ("sketch_add_geometry", {"geometry": [{"kind": "ellipse", "cx": 830, "cy": 0, "radius": 20}],
                             "sketch_name": "W3Curves"},
     lambda p: "minor=10" in (p["results"][0].get("label") or ""), None),
    # conic closed by its chord forms a profile that extrudes - this proves the note's modelling
    # claim end to end.
    ("sketch_create", {"plane": "xy", "name": "W3Conic"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "conic", "x1": 740, "y1": 60,
                                           "x2": 780, "y2": 60, "cx": 760, "cy": 90,
                                           "rho": 0.6}],
                             "sketch_name": "W3Conic"}, "ok", None),
    ("sketch_get", {"sketch_name": "W3Conic", "include_entities": True},
     _xray_gaps_2_w3conic, None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 740, "y1": 60,
                                           "x2": 780, "y2": 60}],
                             "sketch_name": "W3Conic"}, "ok", None),
    ("model_extrude", {"sketch_name": "W3Conic", "profile_index": 0, "distance": 5}, _extruded, None),
    ("sketch_create", {"plane": "xy", "name": "W3Earc"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "elliptical_arc", "cx": 840, "cy": 80,
                                           "radius": 30, "minor": 15, "sweep_deg": 180}],
                             "sketch_name": "W3Earc"}, "ok", None),
    ("sketch_get", {"sketch_name": "W3Earc", "include_entities": True},
     _xray_gaps_2_w3earc, None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 870, "y1": 80,
                                           "x2": 810, "y2": 80}],
                             "sketch_name": "W3Earc"}, "ok", None),
    ("model_extrude", {"sketch_name": "W3Earc", "profile_index": 0, "distance": 5}, _extruded, None),
    # the coincident TRAP, on the success path where the caller who meant "centre this here" is:
    # addCoincident(point, circle) succeeds and lands the point ON the rim, so the note has to say
    # so - and it must NOT say so when the operand was a POINT, where the point really is centred.
    ("sketch_create", {"plane": "xy", "name": "CoincTrap"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 1500, "cy": 0, "radius": 20}],
                             "sketch_name": "CoincTrap"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "point", "cx": 1560, "cy": 0}],
                             "sketch_name": "CoincTrap"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "point", "cx": 1560, "cy": 30}],
                             "sketch_name": "CoincTrap"}, "ok", None),
    ("sketch_constrain", {"constraints": [{"constraint": "coincident", "entity_one": "point:2",
                                           "entity_two": "circle:0"}],
                          "sketch_name": "CoincTrap"},
     lambda p: "ON that curve" in (p["results"][0].get("note") or ""), None),
    ("sketch_constrain", {"constraints": [{"constraint": "coincident", "entity_one": "point:3",
                                           "entity_two": "point:1"}],
                          "sketch_name": "CoincTrap"},
     lambda p: "ON that curve" not in (p["results"][0].get("note") or ""), None),
    # sketch_set_text's PATH layouts: one scratch sketch holding a line and a closed circle, then
    # text laid ALONG each and FITTED to the line. 'definition_type' is the created text's own
    # objectType and 'mode_verified' says whether it matches the mode asked for, so a text that
    # landed in another layout cannot pass as this one.
    ("sketch_create", {"plane": "xy", "name": "TextPaths"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1200, "y1": 0,
                                           "x2": 1300, "y2": 0}],
                             "sketch_name": "TextPaths"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 1250, "cy": 60, "radius": 25}],
                             "sketch_name": "TextPaths"}, "ok", None),
    ("sketch_set_text", {"text": "ALONG", "sketch_name": "TextPaths", "create": True,
                         "mode": "along_path", "path": "line:0", "height": 5},
     lambda p: p.get("mode_verified") is True
     and str(p.get("definition_type") or "").endswith("AlongPathTextDefinition"), None),
    # a CLOSED circle wraps the text right around the hole it marks - the headline path case.
    ("sketch_set_text", {"text": "M8 CLEARANCE", "sketch_name": "TextPaths", "create": True,
                         "mode": "along_path", "path": "circle:0", "align": "center", "height": 4},
     lambda p: p.get("mode_verified") is True, None),
    # fit_on_path spaces the characters over the whole path itself, so the payload carries neither
    # 'align' nor 'character_spacing' - its definition object has no slot for either.
    ("sketch_set_text", {"text": "FIT", "sketch_name": "TextPaths", "create": True,
                         "mode": "fit_on_path", "path": "line:0", "height": 5},
     lambda p: str(p.get("definition_type") or "").endswith("FitOnPathTextDefintion")
     and "align" not in p and "character_spacing" not in p, None),
    # cross-mode inputs: each is refused BY NAME rather than silently dropped, and nothing is created.
    ("sketch_set_text", {"text": "X", "sketch_name": "TextPaths", "create": True,
                         "mode": "fit_on_path", "path": "line:0", "align": "center"}, "refused", None),
    ("sketch_set_text", {"text": "X", "sketch_name": "TextPaths", "create": True,
                         "mode": "along_path", "path": "line:0", "x": 10}, "refused", None),
    ("sketch_set_text", {"text": "X", "sketch_name": "TextPaths", "create": True,
                         "mode": "multi_line", "path": "line:0"}, "refused", None),
    # the layout inputs shape NEW text only: passing one to an EDIT is refused, never ignored.
    ("sketch_set_text", {"text": "FIT", "sketch_name": "TextPaths", "angle_deg": 15},
     "refused", None),
    ("sketch_create", {"plane": "xy", "name": "TextBinding"}, "ok", None),
    ("param_add", {"name": "SweepLabel", "unit": "Text", "expression": "'ALPHA'"},
     lambda p: p.get("parameter", {}).get("value") == "ALPHA", None),
    ("sketch_set_text", {"sketch_name": "TextBinding", "text": "seed", "create": True,
                         "x": 1200, "y": 120, "height": 5, "font_name": "Arial"},
     lambda p: p.get("sketch_text_count") == 1, None),
    ("sketch_set_text", {"sketch_name": "TextBinding", "index": 0, "parameter": "SweepLabel"},
     lambda p: p.get("changed_count") == 1
     and p["changed"][0].get("expression") == "SweepLabel", None),
    ("sketch_get", {"sketch_name": "TextBinding", "include_entities": True},
     lambda p: [(e.get("text"), e.get("text_expression"))
                for e in p.get("entities", []) if e.get("type") == "text"]
     == [("ALPHA", "SweepLabel")], None),
    ("param_set", {"name": "SweepLabel", "expression": "'BETA'"},
     lambda p: p.get("after", {}).get("value") == "BETA", None),
    ("sketch_get", {"sketch_name": "TextBinding", "include_entities": True},
     lambda p: [(e.get("text"), e.get("text_expression"))
                for e in p.get("entities", []) if e.get("type") == "text"]
     == [("BETA", "SweepLabel")], None),
    ("sketch_set_text", {"sketch_name": "TextBinding", "index": 0, "text": ""},
     lambda p: p.get("changed_count") == 1 and p["changed"][0].get("after") == "", None),
    ("sketch_get", {"sketch_name": "TextBinding", "include_entities": True},
     lambda p: [(e.get("text"), e.get("text_expression"))
                for e in p.get("entities", []) if e.get("type") == "text"]
     == [("", None)], None),
    ("sketch_set_text", {"sketch_name": "TextBinding", "index": 0, "text": "   "},
     lambda p: p.get("changed_count") == 1 and p["changed"][0].get("after") == "   ", None),
    ("sketch_get", {"sketch_name": "TextBinding", "include_entities": True},
     lambda p: [(e.get("text"), e.get("text_expression"))
                for e in p.get("entities", []) if e.get("type") == "text"]
     == [("   ", None)], None),
    ("sketch_set_text", {"sketch_name": "TextBinding", "index": 0,
                         "text": "", "parameter": "SweepLabel"},
     lambda p: p.get("changed_count") == 1
     and p["changed"][0].get("expression") == "SweepLabel", None),
    ("sketch_get", {"sketch_name": "TextBinding", "include_entities": True},
     lambda p: [(e.get("text"), e.get("text_expression"))
                for e in p.get("entities", []) if e.get("type") == "text"]
     == [("BETA", "SweepLabel")], None),
    ("sketch_set_text", {"sketch_name": "TextBinding", "index": 0,
                         "text": "WRONG", "parameter": "SweepLabel"},
     _refused("two different string sources"), None),
    ("sketch_get", {"sketch_name": "TextBinding", "include_entities": True},
     lambda p: [(e.get("text"), e.get("text_expression"))
                for e in p.get("entities", []) if e.get("type") == "text"]
     == [("BETA", "SweepLabel")], None),
    # FONT: the one input that reaches the API twice - onto the INPUT before a create, onto the
    # SketchText itself on an edit. No API lists or validates the legal names, so Fusion's own
    # "invalid input font name" raise IS the whole check, and each refusal hands that sentence on
    # with the name it was given. Its own scratch sketch carries the whole run.
    ("sketch_create", {"plane": "xy", "name": "FontProbe"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1200, "y1": 200,
                                           "x2": 1300, "y2": 200}],
                             "sketch_name": "FontProbe"}, "ok", None),
    # the font is read back off the LANDED text, not off the input, so 'font' here is what the
    # created text reports - and nothing sits in 'requested', which is where an unread value goes.
    ("sketch_set_text", {"text": "FONT", "sketch_name": "FontProbe", "create": True,
                         "x": 1200, "y": 160, "height": 6, "font_name": "Arial"},
     lambda p: p.get("font") == "Arial" and p.get("sketch_text_count") == 1
     and "requested" not in p, None),
    # the same font through a setAs* PLACEMENT: it is applied to the input before the placement
    # call and survives it, which is what makes the along-path text report it too.
    ("sketch_set_text", {"text": "ALONGFONT", "sketch_name": "FontProbe", "create": True,
                         "mode": "along_path", "path": "line:0", "height": 5,
                         "font_name": "Arial"},
     lambda p: p.get("font") == "Arial" and p.get("sketch_text_count") == 2, None),
    # a font this machine does not carry: the create raises at add() and the refusal names it.
    ("sketch_set_text", {"text": "NOFONT", "sketch_name": "FontProbe", "create": True,
                         "x": 1200, "y": 140, "height": 6,
                         "font_name": "ZzNoSuchFont_MCP_Probe"}, "refused", None),
    # font names are CASE-SENSITIVE at the API, so 'arial' is as unknown as any other miss.
    ("sketch_set_text", {"text": "NOFONT", "sketch_name": "FontProbe", "create": True,
                         "x": 1200, "y": 140, "height": 6, "font_name": "arial"}, "refused", None),
    # the count is the proof the two refusals created nothing: this is the THIRD text in the
    # sketch. It carries the no-font regression too - omit 'font_name' and no 'font' key is
    # published at all, on the payload or on a record.
    ("sketch_set_text", {"text": "NOFONTKEY", "sketch_name": "FontProbe", "create": True,
                         "x": 1200, "y": 120, "height": 6},
     lambda p: p.get("sketch_text_count") == 3 and "font" not in p, None),
    # EDITING one text: the font goes on FIRST and each changed record carries the font that text
    # reports back beside the string that landed.
    ("sketch_set_text", {"text": "FONT2", "sketch_name": "FontProbe", "index": 0,
                         "font_name": "Arial"},
     lambda p: p["changed"][0].get("font") == "Arial"
     and p["changed"][0].get("after") == "FONT2", None),
    # the unknown name on an EDIT: because the font is applied ahead of the string, the refusal
    # leaves this text's string untouched as well.
    ("sketch_set_text", {"text": "FONT3", "sketch_name": "FontProbe", "index": 0,
                         "font_name": "ZzNoSuchFont_MCP_Probe"}, "refused", None),
    # the next edit answers normally, and its 'before' is what proves the refused call wrote
    # nothing - the string is still the one the successful edit left.
    ("sketch_set_text", {"text": "FONT4", "sketch_name": "FontProbe", "index": 0},
     lambda p: p["changed"][0].get("before") == "FONT2"
     and p["changed"][0].get("after") == "FONT4" and "font" not in p["changed"][0], None),
    # sketch text is deleted by the SAME index sketch_set_text edits by: one text in its own sketch,
    # deleted as 'text:0'. The deleted string and the collection count read back off the sketch are
    # the verdict - a delete that removed nothing is an error, never a false ok.
    ("sketch_create", {"plane": "xy", "name": "TextDel"}, "ok", None),
    ("sketch_set_text", {"text": "SCRAP", "sketch_name": "TextDel", "create": True,
                         "x": 1200, "y": 100, "height": 5}, "ok", None),
    # SketchTexts.add APPENDS, so the SECOND text is 'text:1' - and deleting that index has to take
    # the second one, never the first. The deleted STRING is what separates the two.
    ("sketch_set_text", {"text": "SCRAP2", "sketch_name": "TextDel", "create": True,
                         "x": 1200, "y": 80, "height": 5}, "ok", None),
    # THE EDIT-PATH RESIZE, before those deletes and leaving their inputs untouched: 'height' on an
    # EDIT writes SketchText.heightParameter and the glyph geometry follows it. The same string goes
    # back in, so the string and the count the deletes below read are exactly what they were. The
    # tool REFUSES a resize whose value landed while the box stayed put, so a green step here is
    # itself the geometry-followed proof - what the predicate reads is the numbers it published.
    ("sketch_set_text", {"text": "SCRAP2", "sketch_name": "TextDel", "index": 1, "height": 3},
     lambda p: p.get("changed_count") == 1 and (lambda c:
         c.get("height") == 3.0 and c.get("height_before") == 5.0
         and c.get("before") == "SCRAP2" and c.get("after") == "SCRAP2"
         and isinstance(c.get("measured_width"), (int, float)) and c["measured_width"] > 0
         and isinstance(c.get("measured_height"), (int, float)) and c["measured_height"] > 0
     )(p["changed"][0]), None),
    ("sketch_delete_entity", {"sketch_name": "TextDel", "target": "text:1"},
     lambda p: p.get("text") == "SCRAP2" and p.get("texts_before") == 2
     and p.get("texts_after") == 1, None),
    ("sketch_delete_entity", {"sketch_name": "TextDel", "target": "text:0"},
     lambda p: p.get("text") == "SCRAP" and p.get("texts_before") == 1
     and p.get("texts_after") == 0, None),
    # the emptied sketch has no text at that index any more - the refusal names the index and count.
    ("sketch_delete_entity", {"sketch_name": "TextDel", "target": "text:0"}, "refused", None),
    # THE TEXT READ-BACK (the S6 gap): sketch_get's X-ray lists each SketchText at its text:<i>
    # address with the string, the FONT (fontName is API-readable), the height in display units,
    # and a sketch-space bounding box. FontProbe's final state pins all three record shapes at
    # once: text:0 was edited to FONT4 (its Arial ride-along from the FONT2 edit stays), text:1 is
    # the along-path ALONGFONT, text:2 was created with NO font and reads font None.
    ("sketch_get", {"sketch_name": "FontProbe"},
     lambda p: (p.get("counts") or {}).get("texts") == 3 and "entities" not in p, None),
    # text:2 was created with NO font_name and still reads a real font (measured: the platform
    # gives every text the app default) - so 'font' is a non-empty string on all three records.
    ("sketch_get", {"sketch_name": "FontProbe", "include_entities": True},
     lambda p: (lambda t: [r["id"] for r in t] == ["text:0", "text:1", "text:2"]
                and t[0].get("text") == "FONT4" and t[0].get("font") == "Arial"
                and isinstance(t[0].get("height"), (int, float)) and t[0]["height"] > 0
                and t[1].get("text") == "ALONGFONT"
                and t[2].get("text") == "NOFONTKEY"
                and isinstance(t[2].get("font"), str) and t[2]["font"]
                and "min" in (t[0].get("bounding_box") or {}))
     ([e for e in p.get("entities", []) if e.get("type") == "text"]), None),
    # A WRONG DIMENSION COMES OUT: 'dimension:<i>' indexes sketchDimensions in the order the X-ray
    # lists them, and the parameter name captured before the mutation says WHICH one went. The two
    # lines are DIFFERENT lengths so the survivor's expression convicts a wrong-index delete.
    ("sketch_create", {"plane": "xy", "name": "DimDel"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1300, "y1": 100,
                                           "x2": 1360, "y2": 100}],
                             "sketch_name": "DimDel"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1300, "y1": 120,
                                           "x2": 1340, "y2": 120}],
                             "sketch_name": "DimDel"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "distance", "entity_one": "line:0",
                                          "value": "60 mm"}],
                          "sketch_name": "DimDel"}, "ok", None),
    ("sketch_dimension", {"dimensions": [{"dim_type": "distance", "entity_one": "line:1",
                                          "value": "40 mm"}],
                          "sketch_name": "DimDel"}, "ok", None),
    ("sketch_get", {"sketch_name": "DimDel", "include_entities": True},
     lambda p: p.get("dimension_count") == 2, None),
    ("sketch_delete_entity", {"sketch_name": "DimDel", "target": "dimension:1"},
     lambda p: p.get("dimensions_before") == 2 and p.get("dimensions_after") == 1
     and isinstance(p.get("parameter"), str) and bool(p["parameter"]), None),
    ("sketch_get", {"sketch_name": "DimDel", "include_entities": True},
     lambda p: p.get("dimension_count") == 1
     and "60" in (p["dimensions"][0].get("expression") or ""), None),
    # the emptied index refuses naming the count - never a false ok on a dimension that is gone.
    ("sketch_delete_entity", {"sketch_name": "DimDel", "target": "dimension:1"}, "refused", None),
    # THE SLOT FAMILY, one scratch sketch per shape in a clear band so every count is absolute.
    # 'radius' is the HALF width throughout (the label carries the full width), each tailed
    # constructor takes its tail POSITIONALLY, and the ladders differ per kind - which is what the
    # cross-kind refusals below pin.
    ("sketch_create", {"plane": "xy", "name": "SlotA"}, "ok", None),
    # a three-point arc slot is built entirely out of SketchArcs - five of them, and its closed
    # outline forms a profile. The only dimension it can create is the width one.
    ("sketch_add_geometry", {"geometry": [{"kind": "three_point_arc_slot", "x1": 1700, "y1": 900,
                                           "x2": 1800, "y2": 900, "cx": 1750, "cy": 930,
                                           "radius": 5, "create_width_dimension": True}],
                             "sketch_name": "SlotA"},
     lambda p: (lambda r: r.get("curves_added") == 5 and r["sketch"]["arc_count"] == 5
                and r["sketch"]["profile_count"] >= 1
                and "three_point_arc_slot" in (r.get("label") or "")
                and "w=10" in (r.get("label") or ""))(p["results"][0]), None),
    # its arc is fixed by its three points, so it has no radius or angle to dimension - the flag
    # that belongs to the centre-point kind is refused by name and points there.
    ("sketch_add_geometry", {"geometry": [{"kind": "three_point_arc_slot", "x1": 1700, "y1": 900,
                                           "x2": 1800, "y2": 900, "cx": 1750, "cy": 930,
                                           "radius": 5, "create_angle_dimension": True}],
                             "sketch_name": "SlotA"}, "refused", None),
    # the centre-point arc slot in its four-argument form: centre, start, end, width.
    ("sketch_create", {"plane": "xy", "name": "SlotB"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "center_point_arc_slot", "cx": 1700,
                                           "cy": 1000, "x1": 1750, "y1": 1000, "x2": 1700,
                                           "y2": 1050, "radius": 5}],
                             "sketch_name": "SlotB"},
     lambda p: p["results"][0].get("curves_added") == 5, None),
    # the full ladder: a supplied arc_radius overrides the centre-to-start distance and the angle
    # takes a unit-bearing expression, then each of the three flags gates its OWN dimension - so
    # width + angle asked for and radius declined must land exactly two dimensions.
    ("sketch_create", {"plane": "xy", "name": "SlotC"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "center_point_arc_slot", "cx": 1700,
                                           "cy": 1100, "x1": 1750, "y1": 1100, "x2": 1700,
                                           "y2": 1150, "radius": 5, "arc_radius": 30,
                                           "angle_deg": 45, "create_width_dimension": True,
                                           "create_radius_dimension": False,
                                           "create_angle_dimension": True}],
                             "sketch_name": "SlotC"},
     lambda p: p["results"][0].get("curves_added") == 5, None),
    ("sketch_get", {"sketch_name": "SlotC", "include_entities": True},
     lambda p: p.get("dimension_count") == 2
     and any("diameter" in (d.get("type") or "") for d in p["dimensions"])
     and any("angular" in (d.get("type") or "") for d in p["dimensions"])
     and not any("radial" in (d.get("type") or "") for d in p["dimensions"]), None),
    # an OVERALL slot measures tip to tip: its two points are the outer extremes, so the cap arc
    # centres land inset by the half width - 60 mm tip to tip from centres 52 mm apart.
    ("sketch_create", {"plane": "xy", "name": "SlotD"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "overall_slot", "x1": 1700, "y1": 1200,
                                           "x2": 1760, "y2": 1200, "radius": 4}],
                             "sketch_name": "SlotD"},
     lambda p: p["results"][0].get("curves_added") == 3
     and "w=8" in (p["results"][0].get("label") or ""), None),
    ("sketch_get", {"sketch_name": "SlotD", "include_entities": True},
     lambda p: sorted(round(e["center"]["x"], 3) for e in p["entities"] if e["type"] == "arc")
     == [_px("SlotD", 1704.0), _px("SlotD", 1756.0)], None),
    # the length and the angle are VALUES, not flags: passing either creates its own dimension and
    # adds the fourth line, while the width dimension stays gated on its flag.
    ("sketch_create", {"plane": "xy", "name": "SlotE"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "overall_slot", "x1": 1700, "y1": 1300,
                                           "x2": 1760, "y2": 1300, "radius": 4,
                                           "slot_length": 40, "angle_deg": 30,
                                           "create_width_dimension": True}],
                             "sketch_name": "SlotE"},
     lambda p: p["results"][0].get("curves_added") == 4, None),
    ("sketch_get", {"sketch_name": "SlotE", "include_entities": True},
     lambda p: p.get("dimension_count") == 3
     and any("diameter" in (d.get("type") or "") for d in p["dimensions"])
     and any("linear" in (d.get("type") or "") and abs((d.get("value") or 0) - 40.0) < 1e-3
             and d.get("value_units") == "mm" for d in p["dimensions"])
     # the ANGLE's value is published in DEGREES beside its own 'deg' unit key - the parameter's
     # own read is radians, which would land 0.5236 here against a "30 deg" expression.
     and any("angular" in (d.get("type") or "") and "30" in (d.get("expression") or "")
             and abs((d.get("value") or 0) - 30.0) < 1e-2 and d.get("value_units") == "deg"
             for d in p["dimensions"]), None),
    # the flag ALONE, with no tail: three lines and exactly the one dimension it asked for.
    ("sketch_create", {"plane": "xy", "name": "SlotF"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "overall_slot", "x1": 1700, "y1": 1400,
                                           "x2": 1760, "y2": 1400, "radius": 4,
                                           "create_width_dimension": True}],
                             "sketch_name": "SlotF"},
     lambda p: p["results"][0].get("curves_added") == 3, None),
    ("sketch_get", {"sketch_name": "SlotF", "include_entities": True},
     lambda p: p.get("dimension_count") == 1, None),
    # a CENTRE-point slot's length is the HALF length, centre to cap centre, and it is forwarded
    # unhalved - so a cap centre lands exactly on the second point and the dimension reads 25.
    ("sketch_create", {"plane": "xy", "name": "SlotG"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "center_point_slot", "x1": 1700, "y1": 1500,
                                           "x2": 1725, "y2": 1500, "radius": 3,
                                           "slot_length": 25}],
                             "sketch_name": "SlotG"},
     lambda p: "half_len=25" in (p["results"][0].get("label") or ""), None),
    ("sketch_get", {"sketch_name": "SlotG", "include_entities": True},
     lambda p: any(abs(e["center"]["x"] - _px("SlotG", 1725)) < 1e-3
                   and abs(e["center"]["y"] - _py("SlotG", 1500)) < 1e-3
                   for e in p["entities"] if e["type"] == "arc")
     and any("linear" in (d.get("type") or "") and abs((d.get("value") or 0) - 25.0) < 1e-3
             for d in p["dimensions"]), None),
    # an angle with no length has nothing to sit on: refused naming both.
    ("sketch_add_geometry", {"geometry": [{"kind": "overall_slot", "x1": 1700, "y1": 1400,
                                           "x2": 1760, "y2": 1400, "radius": 4,
                                           "angle_deg": 30}],
                             "sketch_name": "SlotF"}, "refused", None),
    # the linear kinds have no angle FLAG - the angular dimension comes from angle_deg itself.
    ("sketch_add_geometry", {"geometry": [{"kind": "overall_slot", "x1": 1700, "y1": 1400,
                                           "x2": 1760, "y2": 1400, "radius": 4,
                                           "slot_length": 40,
                                           "create_angle_dimension": True}],
                             "sketch_name": "SlotF"}, "refused", None),
    # each cross-kind input is refused pointing at the kind that DOES carry it: arc_radius belongs
    # to the centre-point ARC slot, slot_length to the straight ones - and the three-point arc slot
    # has no radius argument at all, so its refusal must not offer arc_radius as the remedy.
    ("sketch_add_geometry", {"geometry": [{"kind": "center_point_slot", "x1": 1700, "y1": 1500,
                                           "x2": 1725, "y2": 1500, "radius": 3,
                                           "arc_radius": 30}],
                             "sketch_name": "SlotG"}, "refused", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "center_point_arc_slot", "cx": 1700,
                                           "cy": 1000, "x1": 1750, "y1": 1000, "x2": 1700,
                                           "y2": 1050, "radius": 5, "slot_length": 40}],
                             "sketch_name": "SlotB"}, "refused", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "three_point_arc_slot", "x1": 1700, "y1": 900,
                                           "x2": 1800, "y2": 900, "cx": 1750, "cy": 930,
                                           "radius": 5, "slot_length": 40}],
                             "sketch_name": "SlotA"}, "refused", None),
    # the legacy centre-to-centre slot takes two centres and a width and nothing else: a tail would
    # be dropped, so it is refused - and the bare call still draws.
    ("sketch_create", {"plane": "xy", "name": "SlotH"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "slot", "x1": 1700, "y1": 1600,
                                           "x2": 1760, "y2": 1600, "radius": 4,
                                           "slot_length": 40}],
                             "sketch_name": "SlotH"}, "refused", None),
    # the legacy form's own census: addCenterToCenterSlot lands 5 curves - 2 solid lines, 1
    # CONSTRUCTION line (the centre-to-centre one) and 2 arc caps - and 'curves_added' counts the
    # LINE collection's delta, so it reads 3. The note has to say which 5, because the number alone
    # reads like a 3-curve slot.
    ("sketch_add_geometry", {"geometry": [{"kind": "slot", "x1": 1700, "y1": 1600,
                                           "x2": 1760, "y2": 1600, "radius": 4}],
                             "sketch_name": "SlotH"},
     lambda p: (lambda r: r.get("curves_added") == 3
                and "2 solid SketchLines" in (r.get("note") or "")
                and "1 CONSTRUCTION SketchLine" in (r.get("note") or "")
                and "2 SketchArc end caps" in (r.get("note") or ""))(p["results"][0]), None),
    # the independent read: three lines of which EXACTLY ONE is construction, plus the two arc caps.
    ("sketch_get", {"sketch_name": "SlotH", "include_entities": True},
     lambda p: len([e for e in p["entities"] if e["type"] == "line"]) == 3
     and len([e for e in p["entities"] if e["type"] == "line" and e.get("construction")]) == 1
     and len([e for e in p["entities"] if e["type"] == "arc"]) == 2, None),
    # a POLYGON is built by the same SketchLines factory, so its side count is the delta.
    ("sketch_create", {"plane": "xy", "name": "PolyHex"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "polygon", "cx": 1700, "cy": 1700,
                                           "radius": 20, "sides": 6}],
                             "sketch_name": "PolyHex"},
     lambda p: p["results"][0].get("curves_added") == 6, None),
    # sketch_project(into_sketch)'s SECOND entity route: 'source_sketch' + 'curves' read a NAMED
    # curve out of a DIFFERENT sketch by its '<type>:<index>' ref, rather than a find_geometry
    # handle. Proven into a sketch at ROOT and into one owned by a SEPARATE component, then a
    # linked copy tracking its source after the source moves and the design recomputes.
    ("sketch_create", {"plane": "xy", "name": "ProjMaster"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 1900, "y1": 0, "x2": 1950, "y2": 0}],
                             "sketch_name": "ProjMaster"}, "ok", None),
    ("sketch_create", {"plane": "xy", "name": "ProjTargetRoot"}, "ok", None),
    # the projected line arrives with its two endpoints ('point:N' refs beside 'line:0' - measured)
    ("sketch_project", {"action": "into_sketch", "sketch_name": "ProjTargetRoot",
                        "source_sketch": "ProjMaster", "curves": ["line:0"], "link": True},
     lambda p: "line:0" in (p.get("entity_refs") or []) and p.get("linked") is True, None),
    ("model_create_component", {"name": "ProjComp", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "ProjTargetComp"}, "ok", None),
    ("sketch_project", {"action": "into_sketch", "sketch_name": "ProjTargetComp",
                        "source_sketch": "ProjMaster", "curves": ["line:0"], "link": True},
     lambda p: "line:0" in (p.get("entity_refs") or []) and p.get("linked") is True, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("sketch_move", {"sketch_name": "ProjMaster", "entities": "line:0", "dx": 10},
     lambda p: p.get("moved_entities") == ["line:0"], None),
    ("design_recompute", {}, "ok", None),
    ("sketch_get", {"sketch_name": "ProjTargetRoot", "include_entities": True},
     lambda p: any(e.get("type") == "line"
                   and abs((e.get("start") or {}).get("x", 0) - _px("ProjMaster", 1910)) < 0.01
                   and abs((e.get("end") or {}).get("x", 0) - _px("ProjMaster", 1960)) < 0.01
                   for e in (p.get("entities") or [])), None),
    ("sketch_get", {"sketch_name": "ProjTargetComp", "include_entities": True},
     lambda p: any(e.get("type") == "line"
                   and abs((e.get("start") or {}).get("x", 0) - _px("ProjMaster", 1910)) < 0.01
                   and abs((e.get("end") or {}).get("x", 0) - _px("ProjMaster", 1960)) < 0.01
                   for e in (p.get("entities") or [])), None),
    ("sketch_add_geometry", {"sketch_name": "ProjTargetRoot", "geometry": [
        {"kind": "line", "x1": 1900, "y1": 40, "x2": 1950, "y2": 43}]}, "ok", None),
    ("sketch_get", {"sketch_name": "ProjTargetRoot", "include_entities": True},
     _mixed_curve_state(False), None),
    ("sketch_constrain", {"sketch_name": "ProjTargetRoot", "constraints": [
        {"constraint": "fix", "entity_one": "line:1"}]}, "ok", None),
    ("sketch_get", {"sketch_name": "ProjTargetRoot", "include_entities": True},
     _mixed_curve_state(True), ("mixed_curve_fixed", _recall("mixed_curve_fixed", lambda p: {
         key: p[key] for key in ("fixed_curve_count", "reference_curve_count", "linked_curve_count")}))),
    ("sketch_get", {"max_results": 1000},
     lambda p: any(row.get("name") == "ProjTargetRoot"
                   and all(row.get(key) == value for key, value in
                           _ctx_get(_RECALL, "mixed_curve_fixed", "the fixed curve census").items())
                   and row.get("reference_curve_count") == 1 and row.get("linked_curve_count") == 1
                   and row.get("constraint_count") == 0
                   for row in p.get("sketches", [])), None),
    ("sketch_constrain", {"sketch_name": "ProjTargetRoot", "constraints": [
        {"constraint": "unfix", "entity_one": "line:1"}]}, "ok", None),
    ("sketch_get", {"sketch_name": "ProjTargetRoot", "include_entities": True},
     _mixed_curve_state(False), None),
]


def _paging_rows():
    """Page a large sketch and consume a late point in an owned document."""
    rows = [("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("doc_get", {}, _home_document, ("paging_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "paging_home", "home")},
             _new_document, ("paging_doc", lambda p: p["document_handle"]))]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: {
            **(args(c) if callable(args) else args),
            "expect_document": _ctx_get(c, "paging_doc", "paging document")},
            check, save))

    def read(name, args, check, save=None):
        rows.append((name, lambda c, args=args: args(c) if callable(args) else dict(args),
                     check, save))

    # A fresh sketch owns point:0 as its origin; all pages use absolute indices.
    write("sketch_create", {"plane": "xy", "name": "PagingPoints"})
    write("sketch_add_geometry", {"sketch_name": "PagingPoints", "geometry": [
        {"kind": "point", "cx": 2100 + i * 2, "cy": -200} for i in range(200)]},
        lambda p: p.get("drawn") == 200 and len(p.get("results") or []) == 200
        and [r["index"] for r in p["results"]] == list(range(200))
        and p["sketch_state"]["point_count"] == 201)
    write("sketch_add_geometry", {"sketch_name": "PagingPoints", "geometry": [
        {"kind": "point", "cx": 2100 + i * 2, "cy": -200} for i in range(200, 250)]},
        lambda p: p.get("drawn") == 50 and len(p.get("results") or []) == 50
        and [r["index"] for r in p["results"]] == list(range(50))
        and p["sketch_state"]["point_count"] == 251)
    read("sketch_get", {"sketch_name": "PagingPoints", "include_entities": True},
         lambda p: (p["counts"]["points"] == 251
                    and [e["id"] for e in p["entities"]] == [f"point:{i}" for i in range(50)]
                    and p["entities"][0].get("origin") is True
                    and p["entity_pages"]["points"] == {
                        "count": 251, "offset": 0, "next_offset": 50}
                    and p["constraint_count"] == 0 and p["dimension_count"] == 0),
         ("paging_first_ids", _recall("paging_first_ids", lambda p: [
             e["id"] for e in p["entities"]])))
    read("sketch_get", {"sketch_name": "PagingPoints", "include_entities": True,
                        "entity_offset": 50, "max_results": 50},
         lambda p: ([e["id"] for e in p["entities"]]
                    == [f"point:{i}" for i in range(50, 100)]
                    and not set(e["id"] for e in p["entities"]) & set(_ctx_get(
                        _RECALL, "paging_first_ids", "the first point page"))
                    and p["entity_pages"]["points"] == {
                        "count": 251, "offset": 50, "next_offset": 100}),
         ("paging_second_ids", _recall("paging_second_ids", lambda p: [
             e["id"] for e in p["entities"]])))
    read("sketch_get", {"sketch_name": "PagingPoints", "include_entities": True,
                        "max_results": -1}, _refused("max_results", "-1"))
    read("sketch_get", {"sketch_name": "PagingPoints", "include_entities": True,
                        "entity_offset": 200, "max_results": 200},
         lambda p: ([e["id"] for e in p["entities"]]
                    == [f"point:{i}" for i in range(200, 251)]
                    and not set(e["id"] for e in p["entities"]) & set(_ctx_get(
                        _RECALL, "paging_first_ids", "the first point page"))
                    and not set(e["id"] for e in p["entities"]) & set(_ctx_get(
                        _RECALL, "paging_second_ids", "the second point page"))
                    and p["entity_pages"]["points"] == {
                        "count": 251, "offset": 200, "next_offset": None}
                    and next(e for e in p["entities"] if e["id"] == "point:230")
                    ["position"] == {"x": 2558.0, "y": -200.0}
                    and bool(next(e for e in p["entities"] if e["id"] == "point:230")
                             ["handle"])),
         ("paging_point230", _recall("paging_point230", lambda p: next(
             e for e in p["entities"] if e["id"] == "point:230"))))
    read("sketch_get", {"sketch_name": "PagingPoints", "include_entities": True,
                        "entity_offset": 400},
         lambda p: p["entities"] == [] and p["counts"]["points"] == 251
         and p["entity_pages"]["points"] == {
             "count": 251, "offset": 400, "next_offset": None})
    read("sketch_get", {"sketch_name": "PagingPoints", "include_entities": True,
                        "entity_offset": -1}, _refused("entity_offset"))
    write("model_construction", lambda c: {"kind": "point", "mode": "at_point",
                                           "name": "PagedPoint230", "points": [
                                               _ctx_get(c, "paging_point230", "the late point row")
                                               ["handle"]]},
          lambda p: p.get("at_operand") is True
          and abs((p.get("world") or {}).get("x", 0) - 2558) < 0.001
          and abs((p.get("world") or {}).get("y", 0) + 200) < 0.001)
    read("find_geometry", {"kind": "construction_point", "name": "PagedPoint230"},
         lambda p: p.get("match_count") == 1
         and p["matches"][0].get("position") == [2558.0, -200.0, 0.0])
    write("sketch_create", {"plane": "xy", "name": "ReceiptPoints"})
    write("sketch_add_geometry", {"sketch_name": "ReceiptPoints", "geometry": [
        {"kind": "point", "cx": 3100 + i, "cy": -300} for i in range(193)]},
        lambda p: (p.get("drawn"), p.get("requested")) == (193, 193)
        and p.get("sketch") == "ReceiptPoints" and p.get("units") == "mm"
        and [r["index"] for r in p["results"]] == list(range(193))
        and p["results"][-1]["label"] == "point (3292,-300)"
        and all(r["kind"] == "point" and "sketch" not in r and "note" not in r
                for r in p["results"])
        and p["sketch_state"]["point_count"] == 194
        and p["result_note"].count("Draw more") == 1
        and "sketch_get(include_entities=true)" in p["result_note"])
    read("sketch_get", {"sketch_name": "ReceiptPoints"},
         lambda p: p["counts"]["points"] == 194)
    write("sketch_add_geometry", {"sketch_name": "ReceiptPoints", "geometry": [
        {"kind": "point", "cx": 3300, "cy": -300},
        {"kind": "polygon", "cx": 0, "cy": 0, "radius": 5, "sides": 2},
        {"kind": "point", "cx": 3301, "cy": -300}]},
        _SketchBatchRefusal(lambda p: (p.get("drawn"), p.get("requested")) == (1, 3)
        and p.get("failed", {}).get("index") == 1 and p.get("not_attempted") == 1
        and [r["index"] for r in p["results"]] == [0]
        and p["sketch_state"]["point_count"] == 195))
    read("sketch_get", {"sketch_name": "ReceiptPoints"},
         lambda p: p["counts"]["points"] == 195)
    write("sketch_create", {"plane": "xy", "name": "ReceiptMixed"})
    write("sketch_add_geometry", {"sketch_name": "ReceiptMixed", "geometry": [
        {"kind": "circle", "cx": 3500, "cy": -300, "radius": 5},
        {"kind": "rectangle", "x1": 3530, "y1": -310, "x2": 3550, "y2": -290},
        {"kind": "cv_spline", "points": [[3600, -300], [3610, -280], [3620, -300]],
         "degree": 5}]},
        lambda p: (p.get("drawn"), p.get("requested")) == (3, 3)
        and [r["index"] for r in p["results"]] == [0, 1, 2]
        and [r["kind"] for r in p["results"]] == ["circle", "rectangle", "cv_spline"]
        and p["results"][0].get("center_point", "").startswith("point:")
        and p["results"][1].get("curves_added") == 4
        and p["results"][1].get("constraints_added", 0) > 0
        and (p["results"][2].get("degree_requested"), p["results"][2].get("degree")) == (5, 2)
        and p["result_note"].count("rectangle constraints_added=") == 1
        and "Built degree differs" in p["result_note"]
        and p["sketch_state"]["line_count"] == 6
        and p["sketch_state"]["circle_count"] == 1,
        ("receipt_mixed", _recall("receipt_mixed", lambda p: {
            "center": p["results"][0]["center_point"],
            "constraints": p["results"][1]["constraints_added"]})))
    read("sketch_get", {"sketch_name": "ReceiptMixed", "include_entities": True},
         lambda p: p["counts"]["circles"] == 1 and p["counts"]["lines"] == 6
         and sum(e["type"] == "line" and e.get("construction") is False
                 for e in p["entities"]) == 4
         and sum(e["type"] == "line" and e.get("construction") is True
                 for e in p["entities"]) == 2
         and p["counts"]["cv_splines"] == 1
         and p["constraint_count"] == _ctx_get(
             _RECALL, "receipt_mixed", "mixed receipt")["constraints"]
         and any(e["id"] == "circle:0" and e.get("center") == {"x": 3500.0, "y": -300.0}
                 and abs(e.get("radius", 0) - 5) < 0.001 for e in p["entities"])
         and any(e["id"] == _ctx_get(_RECALL, "receipt_mixed", "mixed receipt")["center"]
                 and e.get("position") == {"x": 3500.0, "y": -300.0} for e in p["entities"])
         and any(e["id"] == "cv_spline:0" and e.get("control_point_count") == 3
                 and e.get("control_points") == [
                     {"x": 3600.0, "y": -300.0}, {"x": 3610.0, "y": -280.0},
                     {"x": 3620.0, "y": -300.0}] for e in p["entities"]))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "paging_home", "home"),
                                         "expect_document": _ctx_get(c, "paging_doc", "paging")},
              _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "paging_doc", "paging"),
                                      "save_changes": False,
                                      "expect_document": _ctx_get(c, "paging_home", "home")},
              _document_closed, None)]
    return rows


_SKETCH_PAGING = _paging_rows()
_SKETCHWORK += _SKETCH_PAGING


def _dm_line(x, y):
    """sketch_get: point:1 held at (0, y); point:2 and line:0's end at (x, y), in mm."""
    def check(p):
        rows = {e.get("id"): e for e in p.get("entities") or []}
        got = [(rows.get("point:1") or {}).get("position"), (rows.get("point:2") or {}).get("position"),
               (rows.get("line:0") or {}).get("end")]
        want = [(0, y), (x, y), (x, y)]
        return _measured(f"line held at x 0 and ending at x {x}", got, all(
            isinstance(g, dict) and _near(g.get("x"), wx, 0.001) and _near(g.get("y"), wy, 0.001)
            for g, (wx, wy) in zip(got, want)))
    return check


def _dm_moved(row, sketch, key, x0, x1, y):
    """One sketch_moves row: only point:2 moved, x0 -> x1, as line:0's end, under the named dim."""
    moved = row.get("moved") or [{}]
    ends = [moved[0].get("from_mm") or [], moved[0].get("to_mm") or []]
    return (row.get("sketch") == sketch and row.get("moved_count") == 1 and len(moved) == 1
            and moved[0].get("id") == "point:2" and moved[0].get("ends") == ["line:0 end"]
            and all(len(e) == 3 and all(_near(a, b, 0.001) for a, b in zip(e, want))
                    for e, want in zip(ends, [(x0, y, 0), (x1, y, 0)]))
            and row.get("dimensions") == [{"parameter": _RECALL.get(key),
                                           "entities": ["point:1", "point:2"]}])


def _dimension_move_rows():
    """Name a dimension's entities, then drive it and a user parameter over it: what moved."""
    rows = [("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("doc_get", {}, _home_document, ("dm_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "dm_home", "home")},
             _new_document, ("dm_doc", lambda p: p["document_handle"]))]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: {
            **(args(c) if callable(args) else args),
            "expect_document": _ctx_get(c, "dm_doc", "dimension document")}, check, save))

    def read(name, args, check, save=None):
        rows.append((name, lambda c, args=args: args(c) if callable(args) else dict(args),
                     check, save))

    def driven(sketch, y, length, value, key):
        # Drawn at the length its dimension is created at (SlotW reads 45 mm for DriveB).
        write("sketch_create", {"plane": "xy", "name": sketch})
        write("sketch_add_geometry", {"sketch_name": sketch, "geometry": [
            {"kind": "line", "x1": 0, "y1": y, "x2": length, "y2": y}]})
        read("sketch_get", {"sketch_name": sketch, "include_entities": True}, _dm_line(length, y))
        write("sketch_dimension", {"sketch_name": sketch, "dimensions": [
            {"dim_type": "distance", "entity_one": "point:1", "entity_two": "point:2",
             "value": value}]},
            lambda p: bool(p["results"][0].get("parameter")),
            (key, _recall(key, lambda p: p["results"][0]["parameter"])))

    # The dimension row names the two points the dimension was given.
    driven("Drive", 40, 30, "30 mm", "dm_a")
    read("sketch_get", {"sketch_name": "Drive", "include_entities": True},
         lambda p: _measured("the dimension names point:1 and point:2", p.get("dimensions"),
                             [(d.get("name"), d.get("entities")) for d in p.get("dimensions") or []]
                             == [(_RECALL.get("dm_a"), ["point:1", "point:2"])]))
    # Driving it moves point:2 - line:0's end - and holds point:1, read back independently.
    write("param_set", lambda c: {"name": _ctx_get(c, "dm_a", "Drive's dimension"),
                                  "expression": "45 mm"},
          lambda p: _measured("the write names the point and line end it moved",
                              p.get("sketch_moves"), len(p.get("sketch_moves") or []) == 1
                              and _dm_moved(p["sketch_moves"][0], "Drive", "dm_a", 30, 45, 40)))
    read("sketch_get", {"sketch_name": "Drive", "include_entities": True}, _dm_line(45, 40))
    write("param_set", {"name": "SlotW", "expression": "45 mm", "create": True},
          lambda p: p.get("created") is True)
    write("param_set", lambda c: {"name": _ctx_get(c, "dm_a", "Drive's dimension"),
                                  "expression": "SlotW"},
          lambda p: _measured("binding at the same value moved nothing", p.get("sketch_moves"),
                              [(r.get("sketch"), r.get("moved"), r.get("moved_count"))
                               for r in p.get("sketch_moves") or []] == [("Drive", [], 0)]))
    driven("DriveB", 80, 45, "SlotW", "dm_b")
    write("param_set", {"name": "SlotW", "expression": "60 mm"},
          lambda p: (lambda by: _measured(
              "the user parameter reports both sketches it drives", sorted(by),
              sorted(by) == ["Drive", "DriveB"]
              and _dm_moved(by["Drive"], "Drive", "dm_a", 45, 60, 40)
              and _dm_moved(by["DriveB"], "DriveB", "dm_b", 45, 60, 80)))(
                  {r.get("sketch"): r for r in p.get("sketch_moves") or []}))
    for sketch, y in (("Drive", 40), ("DriveB", 80)):
        read("sketch_get", {"sketch_name": sketch, "include_entities": True}, _dm_line(60, y))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "dm_home", "home"),
                                         "expect_document": _ctx_get(c, "dm_doc", "dimension")},
              _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "dm_doc", "dimension"),
                                      "save_changes": False,
                                      "expect_document": _ctx_get(c, "dm_home", "home")},
              _document_closed, None)]
    return rows


_SKETCHWORK += _dimension_move_rows()


def _anchor_history(key, before):
    """Check the complete healthy timeline without moving or adding feature rows."""
    def check(p):
        tl = p.get("timeline") or {}
        rows = tl.get("timeline")
        good = (isinstance(rows, list) and tl.get("count") == tl.get("returned") == tl.get("marker_position") == len(rows)
                and tl.get("truncated") is not True and p.get("timeline_healthy") is True
                and tl.get("summary", {}).get("states") == {"healthy": len(rows)}
                and tl["summary"].get("exceptions") == []
                and all(r.get("index") == i and r.get("name") and r.get("type") for i, r in enumerate(rows)))
        if before and good:
            _RECALL[key + "_history"] = tl
        return _measured("sketch entry leaves healthy history unchanged", tl,
                         good and tl == _RECALL.get(key + "_history"))
    return check


def _anchor_state(key, stage):
    """Read complete sketch controls and distinguish added midpoint or batch-prefix geometry."""
    def check(p):
        counts, entities = p.get("counts"), p.get("entities")
        if (p.get("sketch") != key or p.get("units") != "mm"
                or p.get("truncated") is not False or p.get("compute_deferred") is True
                or p.get("profiles_stale") is True or p.get("timeline_marker_unrestored") is True
                or not isinstance(counts, dict) or not isinstance(entities, list)
                or not all(type(n) is int and 0 <= n < 100 for n in counts.values())
                or sum(counts.values()) != len(entities)
                or not isinstance(p.get("frame"), dict) or type(p.get("is_fully_constrained")) is not bool
                or any(type(p.get(n)) is not int or not isinstance(p.get(k), list) or p[n] != len(p[k])
                       for n, k in (("constraint_count", "constraints"), ("dimension_count", "dimensions"),
                                    ("profile_count", "profiles")))):
            return _measured("complete sketch census", p, False)
        facts = {k: p.get(k) for k in ("counts", "constraints", "dimensions", "frame", "is_fully_constrained", "compute_deferred")}
        for kind in ("entities", "profiles"):
            facts[kind] = [{k: v for k, v in e.items() if k != "handle"} for e in p[kind]]
        by = {e.get("id"): e for e in facts["entities"]}
        if not all(isinstance(i, str) and i for i in by) or len(by) != len(entities):
            return _measured("unique current sketch ids", entities, False)
        for e in entities:
            fields = {"line": ("start", "end"), "circle": ("center",), "point": ("position",)}.get(e.get("type"))
            if fields is None or any(not isinstance(e.get(k), dict) or not all(
                    type(e[k].get(a)) in (int, float) and isfinite(e[k][a]) for a in "xy") for k in fields):
                return _measured("readable sketch coordinates", e, False)
            if e.get("type") == "circle" and not (type(e.get("radius")) in (int, float)
                                                     and isfinite(e["radius"]) and e["radius"] > 0):
                return _measured("readable circle radius", e, False)
        if any(type(r.get("area")) not in (int, float) or not isfinite(r["area"]) or r["area"] <= 0
               or not isinstance(r.get("centroid"), list) or len(r["centroid"]) != 3
               or not all(type(x) in (int, float) and isfinite(x) for x in r["centroid"]) for r in p["profiles"]):
            return _measured("readable profiles", p["profiles"], False)
        pattern = key == "PatternPreflight"
        if pattern:
            facts.update({k: p.get(k) for k in ("fixed_curve_count", "reference_curve_count", "linked_curve_count",
                                                "construction_count", "driving_dimension_count")})
            if any(facts[k] != 0 for k in ("fixed_curve_count", "reference_curve_count", "linked_curve_count",
                                          "construction_count", "driving_dimension_count")):
                return _measured("unchanged pattern fixed and dimension flags", facts, False)
        if stage == "before":
            selected = []
            endpoints = (([0, 0], [20, 0]),) if pattern else (([10, 10], [30, 10]), ([100, 100], [120, 100]))
            for ends in endpoints:
                hits = [e["id"] for e in entities if e.get("type") == "line"
                        and [[e.get(k, {}).get(a) for a in "xy"] for k in ("start", "end")] == list(ends)]
                if len(hits) != 1:
                    return _measured("independent anchor/control endpoints", entities, False)
                selected += hits
            circles = [e for e in entities if e.get("type") == "circle"]
            good = (counts.get("lines") == (1 if pattern else 2) and counts.get("points") == (4 if pattern else 6)
                    and len(circles) == counts.get("circles") == 1
                    and circles[0].get("center") == {"x": 40.0 if pattern else 60.0, "y": 0.0 if pattern else 10.0}
                    and circles[0].get("radius") == 5.0
                    and p["constraint_count"] == p["dimension_count"] == 0 and p["profile_count"] == 1
                    and all(type(e.get(k)) is bool for e in entities if e.get("type") in ("line", "circle")
                            for k in ("construction", "fixed", "reference", "linked")))
            if good:
                _RECALL[key] = facts
                _RECALL[key + "_ids"] = selected + [circles[0]["id"]]
            return _measured("fresh independent sketch witness", facts, good)
        old = _RECALL.get(key, {})
        if stage in ("unchanged", "solver"):
            return _measured("preflight preserves the full disclosed sketch", facts, facts == old)
        prior = {e["id"]: e for e in old.get("entities", [])}
        new = [e for i, e in by.items() if i not in prior]
        if pattern:
            line, circle = _RECALL.get(key + "_ids", [None, None])
            added = [e for e in new if e.get("type") == "circle"]
            points = [e for e in new if e.get("type") == "point"]
            midpoint = [e["id"] for e in points if e.get("position") == {"x": 10.0, "y": 0.0}]
            expected = dict(old.get("counts", {}), circles=3, points=7)
            centers = sorted((e["center"]["x"], e["center"]["y"]) for e in added)
            wanted = ([{"type": "midpoint", "entities": [midpoint[0], line]},
                       {"type": "circular_pattern", "entities": [midpoint[0], circle]}] if len(midpoint) == 1 else None)
            good = (all(by.get(i) == e for i, e in prior.items()) and facts["frame"] == old.get("frame")
                    and facts["is_fully_constrained"] == old.get("is_fully_constrained")
                    and facts["compute_deferred"] == old.get("compute_deferred")
                    and counts == expected and len(new) == 5 and len(points) == 3 and len(added) == 2
                    and len(centers) == 2 and all(_near(x, -5, .001) for x, _y in centers)
                    and _near(centers[0][1], -25.980762114, .001) and _near(centers[1][1], 25.980762114, .001)
                    and all(e.get("radius") == 5 and all(e.get(k) is False for k in
                            ("construction", "fixed", "reference", "linked")) for e in added)
                    and all(any(e.get("position") == c.get("center") for e in points) for c in added)
                    and p["constraints"] == wanted and p["dimensions"] == []
                    and p["profile_count"] == 3 and all(e in facts["profiles"] for e in old.get("profiles", [])))
            return _measured("three solved circles with midpoint relations and unchanged source", facts, good)
        line, control, circle = _RECALL.get(key + "_ids", [None] * 3)
        centers = [e["id"] for e in prior.values() if e.get("type") == "point"
                   and e.get("position") == {"x": 60.0, "y": 10.0}]
        n = 1 if stage in ("success", "con_success", "geometry") else 0
        added_points = [e for e in new if e.get("type") == "point"]
        expected_position = {"x": 40.0, "y": 40.0} if stage == "geometry" else {"x": 20.0, "y": 10.0}
        expected_counts = dict(old.get("counts", {}))
        expected_counts["points"] += n
        if stage == "geometry":
            expected_counts["circles"] += 1
        wanted = [{"type": "horizontal", "entities": [control]}] if stage == "mixed" else []
        if stage != "geometry":
            wanted += [{"type": "midpoint", "entities": [e["id"], line]} for e in added_points]
        if stage == "con_success" and len(added_points) == len(centers) == 1:
            wanted += [{"type": "horizontal_points", "entities": [added_points[0]["id"], centers[0]]}]
        dimensions = p["dimensions"]
        good = (all(by.get(i) == e for i, e in prior.items()) and facts["frame"] == old.get("frame")
                and facts["is_fully_constrained"] == old.get("is_fully_constrained")
                and facts["compute_deferred"] == old.get("compute_deferred")
                and counts == expected_counts and len(added_points) == n
                and all(e.get("position") == expected_position for e in added_points)
                and p["constraints"] == wanted and all(e in facts["profiles"] for e in old.get("profiles", [])))
        if stage == "geometry":
            new_circles = [e for e in new if e.get("type") == "circle"]
            good = (good and len(new) == 2 and len(new_circles) == 1
                    and new_circles[0].get("center") == expected_position and new_circles[0].get("radius") == 3.0
                    and len(facts["profiles"]) == 2 and dimensions == [])
        else:
            good = good and len(new) == n and facts["profiles"] == old.get("profiles")
            if stage in ("success", "dim_mixed", "dim_preflight"):
                refs = [circle] if stage in ("dim_mixed", "dim_preflight") else (
                    [added_points[0]["id"], centers[0]] if len(added_points) == len(centers) == 1 else None)
                good = (good and len(dimensions) == 1 and dimensions[0].get("value") == (5.0 if stage in ("dim_mixed", "dim_preflight") else 40.0)
                        and dimensions[0].get("driving") is True and dimensions[0].get("name")
                        and refs is not None and dimensions[0].get("entities") == refs)
            else:
                good = good and dimensions == []
        return _measured("independent retained geometry and unchanged controls", facts, good)
    return check


def _anchor_partial(geometry=False, dimension=False):
    """Separate completed prefix, failed-entry counts and unattempted suffix."""
    def check(p):
        before = {"curves": 4 if geometry else 3, "points": 7 if geometry else 6,
                  "constraints": 0 if geometry or dimension else 1, "dimensions": int(dimension)}
        change = {"curves": 0, "points": 0, "constraints": 0, "dimensions": 0}
        retired = "The midpoint anchor(s) it made were deleted" in p.get("note", "")
        return _measured("per-entry counts exclude the completed prefix", p,
                         retired is dimension and
                         p.get("drawn" if geometry else "dimensioned" if dimension else "constrained") == 1 and p.get("requested") == 3
                         and len(p.get("results", [])) == 1 and p["results"][0].get("index") == 0
                         and p.get("failed", {}).get("index") == 1 and p.get("not_attempted") == 1
                         and "retained" not in p and p.get("failed_entry_counts") == {
                             "before": before, "after": {k: before[k] + change[k] for k in before}, "change": change}
                         and ("Counts do not establish unchanged geometry" in p.get("note", ""))
                         is dimension)
    return check


def _anchor_retained(p):
    """Check a rejected value on a midpoint-anchored distance names every effect it kept."""
    return _measured("retained anchored dimension with its point and constraint", p,
                     p.get("dimensioned") == 0 and p.get("results") == [] and p.get("not_attempted") == 0
                     and len(p.get("retained") or []) == 1 and p["retained"][0].get("value_driven") is False
                     and (p.get("failed_entry_counts") or {}).get("change") == {
                         "curves": 0, "points": 1, "constraints": 1, "dimensions": 1}
                     and ("The failed entry left points=+1, constraints=+1, dimensions=+1 in the sketch; "
                          "'retained' identifies 1 of those effects") in (p.get("note") or ""))


def _anchor_retention_rows():
    """Exercise anchor preflight and failed-entry retention on fresh equivalent sketches."""
    rows = [("doc_get", {}, _home_document, ("anchor_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "anchor_home", "home")},
             _new_document, ("anchor_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok"):
        rows.append((tool, lambda c, args=args: {**(args(c) if callable(args) else args),
                    "expect_document": _ctx_get(c, "anchor_doc", "anchor document")}, check, None))

    for key, stage in (("AnchorSurface", "unchanged"), ("AnchorConKind", "unchanged"), ("AnchorKind", "unchanged"),
                       ("AnchorConSolver", "unchanged"), ("AnchorDimSolver", "solver"),
                       ("AnchorMixed", "mixed"), ("AnchorDimMixed", "dim_mixed"), ("AnchorGeometry", "geometry"),
                       ("AnchorDimPreflight", "dim_preflight"),
                       ("AnchorConSuccess", "con_success"), ("AnchorSuccess", "success"),
                       ("AnchorDimRetained", "success")):
        write("sketch_create", {"name": key, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": key, "geometry": [
            {"kind": "line", "x1": 10, "y1": 10, "x2": 30, "y2": 10},
            {"kind": "circle", "cx": 60, "cy": 10, "radius": 5},
            {"kind": "line", "x1": 100, "y1": 100, "x2": 120, "y2": 100}]})
        read_args = {"sketch_name": key, "include_entities": True, "max_results": 200, "units": "mm"}
        rows.append(("sketch_get", read_args, _anchor_state(key, "before"),
                     (key + "_ids", lambda _p, key=key: _RECALL[key + "_ids"])))
        rows.append(("design_get", {"include": ["default", "timeline"], "max_results": 200}, _anchor_history(key, True), None))

        def arguments(c, key=key):
            line, control, circle = _ctx_get(c, key + "_ids", "current anchor ids")
            if key == "AnchorDimPreflight":
                return {"sketch_name": key, "dimensions": [
                    {"dim_type": "radius", "entity_one": circle, "value": "5 mm"},
                    {"dim_type": "radius", "entity_one": "circle:99", "value": "6 mm"},
                    {"dim_type": "radius", "entity_one": circle, "value": "7 mm"}]}
            if key == "AnchorGeometry":
                return {"sketch_name": key, "geometry": [
                    {"kind": "circle", "cx": 40, "cy": 40, "radius": 3},
                    {"kind": "circle", "cx": 70, "cy": 40, "radius": -1},
                    {"kind": "circle", "cx": 80, "cy": 40, "radius": 2}]}
            if key == "AnchorConSuccess":
                return {"sketch_name": key, "constraints": [{"constraint": "horizontal_points",
                        "entity_one": line + ":mid", "entity_two": circle + ":center"}]}
            if key in ("AnchorSurface", "AnchorConKind", "AnchorConSolver", "AnchorMixed"):
                entries = ([{"constraint": "horizontal", "entity_one": control}] if key == "AnchorMixed" else [])
                entries += [{"constraint": "coincident_to_surface", "entity_one": line + ":mid"}
                            if key == "AnchorSurface" else
                            {"constraint": "coincident", "entity_one": line + ":mid",
                             "entity_two": (circle if key == "AnchorConKind" else line) + ":mid"}]
                if key == "AnchorMixed":
                    entries += [{"constraint": "vertical", "entity_one": control}]
                return {"sketch_name": key, "constraints": entries}
            entries = [{"dim_type": "radius", "entity_one": circle, "value": "5 mm"}] if key == "AnchorDimMixed" else []
            entries += [{"dim_type": "distance", "entity_one": line + ":mid",
                         "entity_two": circle + ":mid" if key == "AnchorKind" else
                         circle + ":center" if key in ("AnchorSuccess", "AnchorDimRetained")
                         else line + ":mid"}]
            if key == "AnchorSuccess":
                entries[-1]["value"] = "40 mm"
            if key == "AnchorDimRetained":
                # A rejected value keeps the measured 40 mm dimension on its welded midpoint.
                entries[-1]["value"] = "1 mm +"
            if key == "AnchorDimMixed":
                entries += [{"dim_type": "distance", "entity_one": control, "value": "20 mm"}]
            return {"sketch_name": key, "dimensions": entries}

        tool = ("sketch_add_geometry" if stage == "geometry" else "sketch_constrain"
                if key in ("AnchorSurface", "AnchorConKind", "AnchorConSolver", "AnchorMixed", "AnchorConSuccess") else "sketch_dimension")
        def dim_preflight(p):
            return _measured("dimension preflight keeps only the completed prefix", p,
                             p.get("dimensioned") == 1 and p.get("requested") == 3
                             and [r.get("index") for r in p.get("results", [])] == [0]
                             and p.get("failed", {}).get("index") == 1 and p.get("not_attempted") == 1
                             and p.get("failed_entry_counts", {}).get("change") == {
                                 "curves": 0, "points": 0, "constraints": 0, "dimensions": 0}
                             and "circle:99" in p["failed"]["error"]
                             and "Counts do not establish unchanged geometry" not in p.get("note", "")
                             and "retained" not in p)

        verdict = (_SketchBatchRefusal(_anchor_partial(stage == "geometry", stage == "dim_mixed"))
                   if stage in ("mixed", "dim_mixed", "geometry")
                   else _SketchBatchRefusal(dim_preflight) if stage == "dim_preflight"
                   else _SketchBatchRefusal(_anchor_retained) if key == "AnchorDimRetained"
                   else "ok" if stage in ("success", "con_success")
                   else _refused("The midpoint anchor(s) it made were deleted", "points=+0, constraints=+0")
                   if stage == "solver"
                   else _refused("points=+0", "constraints=+0", "needs 'surface'" if key == "AnchorSurface"
                                 else "SAME line midpoint" if key == "AnchorConSolver" else "LINE"))
        write(tool, arguments, verdict)
        rows.append(("sketch_get", read_args, _anchor_state(key, stage), None))
        rows.append(("design_get", {"include": ["default", "timeline"], "max_results": 200}, _anchor_history(key, False), None))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "anchor_home", "home"),
                                        "expect_document": _ctx_get(c, "anchor_doc", "anchor document")}, _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "anchor_doc", "anchor document"), "save_changes": False,
                                     "expect_document": _ctx_get(c, "anchor_home", "home")}, _document_closed, None)]
    return rows


_SKETCHWORK += _anchor_retention_rows()


def _failed_entry_evidence_rows():
    """Separate a pre-write refusal, a write failure, a raising entry and a retired midpoint anchor."""
    rows = [("doc_get", {}, _home_document, ("evidence_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "evidence_home", "home")},
             _new_document, ("evidence_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok"):
        rows.append((tool, lambda c, args=args: {**(args(c) if callable(args) else args),
                    "expect_document": _ctx_get(c, "evidence_doc", "evidence document")}, check, None))

    def parameters(p):
        return _measured("single-parameter refusal preserves the empty table", p,
                         p.get("user_parameter_count") == p.get("returned") == p.get("matched") == 0
                         and p.get("user_parameters") == [] and not p.get("walk_truncated"))

    rows.append(("param_get", {}, parameters, None))
    for field, value in (("name", 7), ("expression", 7), ("unit", 7), ("comment", 7)):
        write("param_add", {"name": "EvidenceLength", "expression": "5 mm", field: value},
              _refused(field, "string", "No parameter added"))
        rows.append(("param_get", {}, parameters, None))
    write("param_add", {"name": "EvidenceLength", "expression": "5 mm"},
          _param_added("EvidenceLength", 5))
    rows.append(("param_get", {}, _params_listed("EvidenceLength"), None))

    def partial(key, error_fragment, guidance):
        """One landed horizontal, the second entry failed as named, the third not attempted."""
        def check(p):
            failed = p.get("failed") or {}
            return _measured("failed entry " + key, p,
                             p.get("constrained") == 1 and [r.get("index") for r in p.get("results", [])] == [0]
                             and failed.get("index") == 1 and error_fragment in str(failed.get("error"))
                             and p.get("not_attempted") == 1
                             and (p.get("failed_entry_counts") or {}).get("change") == {
                                 "curves": 0, "points": 0, "constraints": 0, "dimensions": 0}
                             and "Failed-entry count changes: curves=+0" in p.get("note", "")
                             and ("Counts do not establish unchanged geometry" in p.get("note", "")) is guidance)
        return check

    for key in ("EvidenceRefusal", "EvidenceWrite", "EvidenceRaise", "EvidenceRetire"):
        write("sketch_create", {"name": key, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": key, "geometry": [
            {"kind": "line", "x1": 10, "y1": 10, "x2": 30, "y2": 10},
            {"kind": "circle", "cx": 60, "cy": 10, "radius": 5},
            {"kind": "line", "x1": 100, "y1": 100, "x2": 120, "y2": 100}]})
        read_args = {"sketch_name": key, "include_entities": True, "max_results": 200, "units": "mm"}
        rows.append(("sketch_get", read_args, _anchor_state(key, "before"),
                     (key + "_ids", lambda _p, key=key: _RECALL[key + "_ids"])))
        rows.append(("design_get", {"include": ["default", "timeline"], "max_results": 200},
                     _anchor_history(key, True), None))

        def entries(c, key=key):
            line, control, circle = _ctx_get(c, key + "_ids", "current evidence ids")
            if key == "EvidenceRetire":
                return {"sketch_name": key, "constraints": [
                    {"constraint": "coincident", "entity_one": line + ":mid", "entity_two": line}]}
            second = {"EvidenceRefusal": {"constraint": "horizontal", "entity_one": "line:99"},
                      "EvidenceWrite": {"constraint": "horizontal", "entity_one": circle},
                      "EvidenceRaise": {"constraint": "vertical", "entity_one": 5}}[key]
            return {"sketch_name": key, "constraints": [
                {"constraint": "horizontal", "entity_one": control}, second,
                {"constraint": "vertical", "entity_one": control}]}

        verdict = {
            # An input refusal decided before any write carries the counts but no guidance.
            "EvidenceRefusal": _SketchBatchRefusal(partial(key, "Could not resolve entity_one 'line:99'", False)),
            # A write the API refuses (addHorizontal takes a SketchLine) keeps the guidance.
            "EvidenceWrite": _SketchBatchRefusal(partial(key, "Could not apply horizontal", True)),
            # A raise inside one entry is that entry's failure, with the landed entry listed.
            "EvidenceRaise": _SketchBatchRefusal(
                lambda p, key=key: partial(key, "The entry raised:", True)(p)
                and p.get("retained") is None
                and "'int' object has no attribute 'strip'" in p["failed"]["error"]),
            # The midpoint anchor the failed entry minted is deleted, proven by the counts.
            "EvidenceRetire": _refused("The midpoint anchor(s) it made were deleted",
                                       "points=+0, constraints=+0"),
        }[key]
        write("sketch_constrain", entries, verdict)
        # Independent effect: the sketch holds the one landed horizontal (or, for the retire,
        # exactly what it held before), and the history is unchanged.
        rows.append(("sketch_get", read_args,
                     _anchor_state(key, "unchanged" if key == "EvidenceRetire" else "mixed"), None))
        rows.append(("design_get", {"include": ["default", "timeline"], "max_results": 200},
                     _anchor_history(key, False), None))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "evidence_home", "home"),
                                        "expect_document": _ctx_get(c, "evidence_doc", "evidence document")},
              _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "evidence_doc", "evidence document"),
                                     "save_changes": False,
                                     "expect_document": _ctx_get(c, "evidence_home", "home")},
              _document_closed, None)]
    return rows


_SKETCHWORK += _failed_entry_evidence_rows()


def _partial_witness_home(p):
    """Preserve the complete open-document census and return the active home handle."""
    active = p.get("active") or {}
    docs = p.get("open_documents")
    good = (bool(active.get("name")) and isinstance(active.get("document_handle"), str)
            and active["document_handle"].startswith("session:")
            and p.get("truncated") is False and type(p.get("open_count")) is int
            and isinstance(docs, list) and len(docs) == p.get("open_count")
            and sum(bool(r.get("is_active")) for r in docs) == 1
            and next((r.get("document_handle") for r in docs if r.get("is_active")), None)
            == active["document_handle"])
    if not good:
        return _measured("complete home document census", p, False)
    census = {"active": active["document_handle"], "open_count": p["open_count"],
              "open_documents": docs}
    if not _measured("complete home document census", census, True):
        raise AssertionError("home document census was incomplete")
    _RECALL["partial_witness_home_census"] = census
    return active["document_handle"]


def _partial_witness_home_restored(p):
    """Check the complete original home census after closing the scratch document."""
    active = p.get("active") or {}
    docs = p.get("open_documents")
    if not (isinstance(docs, list) and p.get("truncated") is False
            and type(p.get("open_count")) is int and len(docs) == p.get("open_count")):
        return _measured("complete home document census", p, False)
    census = {"active": (active.get("document_handle")), "open_count": p["open_count"],
              "open_documents": docs}
    return _measured("complete home document census", census,
                     census == _RECALL.get("partial_witness_home_census"))


def _partial_witness_ids(p):
    """Acquire line identities from the four requested endpoint pairs."""
    lines = [e for e in p.get("entities", []) if e.get("type") == "line"]
    endpoints = {
        "guides": (([0.0, 30.0], [20.0, 30.0]), ([0.0, 40.0], [20.0, 40.0])),
        "horizontal": (([25.0, 30.0], [35.0, 32.0]),),
        "vertical": (([25.0, 40.0], [35.0, 42.0]),)}
    selected = {}
    for name, pairs in endpoints.items():
        for pair in pairs:
            wanted = sorted(pair)
            hits = [e for e in lines if sorted([[e.get(k, {}).get(a) for a in "xy"]
                                                for k in ("start", "end")]) == wanted]
            if len(hits) != 1:
                return _measured("unique endpoint-selected witness lines", lines, False)
            selected.setdefault(name, []).append(hits[0].get("id"))
    good = (p.get("sketch") == "PartialWitness" and p.get("units") == "mm"
            and p.get("truncated") is False and p.get("counts", {}).get("lines") == 4
            and p.get("counts", {}).get("points") == 9 and len(lines) == 4
            and all(isinstance(i, str) and i for group in selected.values() for i in group)
            and len({i for group in selected.values() for i in group}) == 4)
    if good:
        _RECALL["partial_witness_line_ids"] = {
            "guide0": selected["guides"][0], "guide1": selected["guides"][1],
            "horizontal": selected["horizontal"][0], "vertical": selected["vertical"][0]}
    return _measured("endpoint-selected four-line witness", selected, good)


def _partial_witness_state(stage):
    """Check the construction guides, batch prefix, and independently read sketch state."""
    def check(p):
        ids = _RECALL.get("partial_witness_line_ids", {})
        entities = p.get("entities")
        counts = p.get("counts") or {}
        lines = {e.get("id"): e for e in entities or [] if e.get("type") == "line"}
        wanted_ids = {ids.get(k) for k in ("guide0", "guide1", "horizontal", "vertical")}
        baseline = _RECALL.get("partial_witness_before")
        valid = (p.get("sketch") == "PartialWitness" and p.get("units") == "mm"
                 and p.get("truncated") is False and p.get("compute_deferred") is not True
                 and p.get("profiles_stale") is not True and p.get("timeline_marker_unrestored") is not True
                 and counts.get("lines") == 4 and counts.get("points") == 9
                 and all(counts.get(k) == 0 for k in
                         ("arcs", "circles", "ellipses", "elliptical_arcs", "conics", "splines",
                          "cv_splines", "fixed_splines", "texts"))
                 and len(entities or []) == sum(counts.values()) == 13
                 and len(lines) == 4 and set(lines) == wanted_ids
                 and p.get("constraint_count") == len(p.get("constraints") or [])
                 and p.get("dimension_count") == p.get("profile_count") == 0
                 and p.get("dimensions") == [] and p.get("profiles") == [])
        flags = ("construction", "fixed", "reference", "linked")
        for key in ("guide0", "guide1", "horizontal", "vertical"):
            line = lines.get(ids.get(key)) or {}
            if any(type(line.get(f)) is not bool for f in flags):
                valid = False
        if stage == "select":
            valid = (valid and all(lines[ids[k]].get("construction") is True
                                   for k in ("guide0", "guide1"))
                     and all(lines[ids[k]].get("fixed") is False
                             for k in ("guide0", "guide1")))
            return _measured("construction guide identities before fixing", lines, valid)
        if stage == "before":
            valid = (valid and all(lines[ids[k]].get("construction") is True
                                   and lines[ids[k]].get("fixed") is True
                                   for k in ("guide0", "guide1"))
                     and all(lines[ids[k]].get("construction") is False
                             and lines[ids[k]].get("fixed") is False
                             for k in ("horizontal", "vertical"))
                     and p.get("constraints") == [])
            if valid:
                facts = {"counts": counts, "frame": p.get("frame"),
                         "is_fully_constrained": p.get("is_fully_constrained"),
                         "entities": [{k: v for k, v in e.items() if k != "handle"}
                                      for e in entities]}
                _RECALL["partial_witness_before"] = facts
            return _measured("fixed construction guides before partial batch", lines, valid)
        old = baseline or {}
        prior = {e.get("id"): e for e in old.get("entities", [])}
        constraints = [{"type": "horizontal", "entities": [ids["horizontal"]]}]
        unchanged_lines = all(
            lines[ids[k]].get(f) == prior.get(ids[k], {}).get(f)
            for k in ("guide0", "guide1", "vertical") for f in ("start", "end", *flags))
        flags_unchanged = all(
            lines[ids[k]].get(f) == prior.get(ids[k], {}).get(f)
            for k in ("guide0", "guide1", "horizontal", "vertical") for f in flags)
        horizontal = lines.get(ids.get("horizontal"), {})
        start, end = horizontal.get("start") or {}, horizontal.get("end") or {}
        good = (valid and bool(old) and unchanged_lines and flags_unchanged
                and p.get("constraint_count") == 1 and p.get("constraints") == constraints
                and start.get("x") != end.get("x") and _near(start.get("y"), end.get("y"), .001)
                and all(e.get("id") in prior for e in entities))
        return _measured("one horizontal prefix and unchanged independent witness", {
            "counts": counts, "lines": [{k: v for k, v in e.items() if k != "handle"}
                                         for e in lines.values()],
            "constraints": p.get("constraints"), "point_count": counts.get("points")}, good)
    return check


def _partial_witness_rows():
    """Reproduce the cold three-entry partial failure on an owned four-line scratch sketch."""
    rows = [("doc_get", {}, _home_document, ("partial_witness_home", _partial_witness_home)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "partial_witness_home", "home")},
             _new_document, ("partial_witness_doc", lambda p: p["document_handle"])),
            ("sketch_create", lambda c: {"name": "PartialWitness", "plane": "xy",
                                          "expect_document": _ctx_get(c, "partial_witness_doc", "scratch")},
             "ok", None),
            ("sketch_add_geometry", lambda c: {"sketch_name": "PartialWitness", "units": "mm",
                "geometry": [{"kind": "line", "x1": 0, "y1": 30, "x2": 20, "y2": 30,
                              "is_construction": True},
                             {"kind": "line", "x1": 0, "y1": 40, "x2": 20, "y2": 40,
                              "is_construction": True},
                             {"kind": "line", "x1": 25, "y1": 30, "x2": 35, "y2": 32},
                             {"kind": "line", "x1": 25, "y1": 40, "x2": 35, "y2": 42}],
                "expect_document": _ctx_get(c, "partial_witness_doc", "scratch")}, "ok", None),
            ("sketch_get", {"sketch_name": "PartialWitness", "include_entities": True,
                            "max_results": 200, "units": "mm"},
             _partial_witness_ids, None),
            ("sketch_get", {"sketch_name": "PartialWitness", "include_entities": True,
                            "max_results": 200, "units": "mm"},
             _partial_witness_state("select"), None)]

    def guide_fix(c):
        ids = _RECALL.get("partial_witness_line_ids", {})
        return {"sketch_name": "PartialWitness", "units": "mm", "constraints": [
            {"constraint": "fix", "entity_one": ids.get("guide0")},
            {"constraint": "fix", "entity_one": ids.get("guide1")}],
            "expect_document": _ctx_get(c, "partial_witness_doc", "scratch")}

    rows += [("sketch_constrain", guide_fix, "ok", None),
             ("sketch_get", {"sketch_name": "PartialWitness", "include_entities": True,
                             "max_results": 200, "units": "mm"},
              _partial_witness_state("before"), None),
             ("design_get", {"include": ["default", "timeline"], "max_results": 200},
              _anchor_history("partial_witness", True), None)]

    def batch_args(c):
        ids = _RECALL.get("partial_witness_line_ids", {})
        return {"sketch_name": "PartialWitness", "units": "mm", "constraints": [
            {"constraint": "horizontal", "entity_one": ids["horizontal"]},
            {"constraint": "coincident", "entity_one": ids["guide0"] + ":mid",
             "entity_two": ids["guide1"]},
            {"constraint": "vertical", "entity_one": ids["vertical"]}],
            "expect_document": _ctx_get(c, "partial_witness_doc", "scratch")}

    def failed_batch(p):
        failed = p.get("failed") or {}
        change = (p.get("failed_entry_counts") or {}).get("change") or {}
        landed = p.get("results") or []
        error = str(failed.get("error", ""))
        note = str(p.get("note", ""))
        return _measured("cold native partial witness payload", p,
                         p.get("constrained") == 1 and p.get("requested") == 3
                         and [r.get("index") for r in landed] == [0]
                         and landed[0].get("applied") == "horizontal"
                         and landed[0].get("entity_one") == _RECALL["partial_witness_line_ids"]["horizontal"]
                         and failed.get("index") == 1 and p.get("not_attempted") == 1
                         and change == {"curves": 0, "points": 0, "constraints": 0, "dimensions": 0}
                         and "The midpoint anchor(s) it made were deleted" in note
                         and "Could not apply coincident" in error
                         and "retained" not in p)

    rows.append(("sketch_constrain", batch_args, _SketchBatchRefusal(failed_batch), None))
    rows += [("sketch_get", {"sketch_name": "PartialWitness", "include_entities": True,
                             "max_results": 200, "units": "mm"},
              _partial_witness_state("after"), None),
             ("design_get", {"include": ["default", "timeline"], "max_results": 200},
              _anchor_history("partial_witness", False), None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "partial_witness_home", "home"),
                                         "expect_document": _ctx_get(c, "partial_witness_doc", "scratch")},
              _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "partial_witness_doc", "scratch"),
                                      "save_changes": False,
                                      "expect_document": _ctx_get(c, "partial_witness_home", "home")},
              _document_closed, None),
             ("doc_get", {}, _partial_witness_home_restored, None)]
    return rows


_SKETCHWORK += _partial_witness_rows()



def _pattern_preflight_rows():
    """Check midpoint preflight refusals and three solved circle instances with a separate sketch witness."""
    rows = [("doc_get", {}, _home_document, ("pattern_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "pattern_home", "home")},
             _new_document, ("pattern_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]

    def write(tool, args, check="ok"):
        rows.append((tool, lambda c, args=args: _combine_pin(c, "pattern_doc", args(c) if callable(args) else args), check, None))

    for name, geometry in (("PatternPreflight", [{"kind": "line", "x1": 0, "y1": 0, "x2": 20, "y2": 0},
                                               {"kind": "circle", "cx": 40, "cy": 0, "radius": 5}]),
                           ("PatternWitness", [{"kind": "line", "x1": 10, "y1": 10, "x2": 30, "y2": 10},
                                              {"kind": "circle", "cx": 60, "cy": 10, "radius": 5},
                                              {"kind": "line", "x1": 100, "y1": 100, "x2": 120, "y2": 100}])):
        write("sketch_create", {"name": name, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": geometry})
    target = {"sketch_name": "PatternPreflight", "include_entities": True, "max_results": 200, "units": "mm"}
    witness = {"sketch_name": "PatternWitness", "include_entities": True, "max_results": 200, "units": "mm"}
    history = {"include": ["default", "timeline"], "max_results": 200}
    rows += [("sketch_get", target, _anchor_state("PatternPreflight", "before"),
              ("pattern_ids", lambda _p: _RECALL["PatternPreflight_ids"])),
             ("sketch_get", witness, _anchor_state("PatternWitness", "before"), None),
             ("design_get", history, _anchor_history("PatternPreflight", True), None)]
    for knobs, reason in (({"quantity": 1}, "quantity >= 2"),
                          ({"quantity": 3, "suppressed": [True]}, "needs 2 flag(s)"),
                          ({"quantity": 3, "entities": "circle:99"}, "Could not resolve 'circle:99'"),
                          ({"quantity": 3, "entities": ""}, "needs 'entities'"),
                          ({"quantity": 3}, None)):
        def args(c, knobs=knobs):
            line, circle = _ctx_get(c, "pattern_ids", "current source ids")
            return {"sketch_name": "PatternPreflight", "constraints": [{"constraint": "circular_pattern",
                    "entity_one": line + ":mid", "entities": circle, **knobs}]}
        write("sketch_constrain", args, _refused(reason, "points=+0", "constraints=+0") if reason else "ok")
        rows += [("sketch_get", target, _anchor_state("PatternPreflight", "unchanged" if reason else "pattern"), None),
                 ("sketch_get", witness, _anchor_state("PatternWitness", "unchanged"), None),
                 ("design_get", history, _anchor_history("PatternPreflight", False), None)]
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "pattern_home", "home"),
                                        "expect_document": _ctx_get(c, "pattern_doc", "scratch")}, _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "pattern_doc", "scratch"), "save_changes": False,
                                     "expect_document": _ctx_get(c, "pattern_home", "home")}, _document_closed, None)]
    return rows


_SKETCHWORK += _pattern_preflight_rows()


def _solved_fillet_effect(control=False):
    """Read the retained arc radius, tangent neighbors and their solved coordinates."""
    def check(p):
        state = _retire_sketch_state(p)
        entities = {r.get("id"): r for r in p.get("entities", [])}
        arc = entities.get("arc:0", {})
        lines = [entities.get("line:" + str(i), {}) for i in (0, 1)]
        tangent = {tuple(sorted(r.get("entities", []))) for r in p.get("constraints", [])
                   if r.get("type") == "tangent"}
        radius = 10 if control else 18.7766
        valid = (state is not None and p.get("units") == "mm" and p.get("is_fully_constrained") is False
                 and p.get("counts", {}).get("lines") == 2 and p.get("counts", {}).get("arcs") == 1
                 and _near(arc.get("radius"), radius, .001)
                 and tangent == {("arc:0", "line:0"), ("arc:0", "line:1")})
        if valid and not control:
            reported = _RECALL.get("fillet_reported_radius")
            old = _RECALL.get("fillet_before") or {}
            prior = {r.get("id"): r for r in old.get("entities", [])}
            valid = (isinstance(reported, (int, float)) and not isinstance(reported, bool)
                     and _near(arc.get("radius"), reported, .001)
                     and lines[0].get("end") != prior.get("line:0", {}).get("end")
                     and lines[1].get("start") != prior.get("line:1", {}).get("start")
                     and _near(lines[0]["end"].get("x"), 214.6263, .001)
                     and _near(lines[1]["start"].get("x"), 224.5797, .001))
        return _measured("solved fillet radius and retained tangent neighbors", state, valid)
    return check


def _fillet_radius_rows():
    """Verify a retained oblique-radius mismatch and the independent right-angle control."""
    rows = [("doc_get", {}, _home_document, ("fillet_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "fillet_story", "story")},
             _new_document, ("fillet_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]

    def write(name, args, check="ok"):
        rows.append((name, lambda c, args=args: _combine_pin(c, "fillet_doc", args), check, None))

    for name, geometry in (("EditCorner", [{"kind": "line", "x1": 600, "y1": 0, "x2": 660, "y2": 0},
                                          {"kind": "line", "x1": 660, "y1": 0, "x2": 660, "y2": 40}]),
                           ("FilletPath", [{"kind": "polyline", "points": [[10, -30], [220, -30], [260, -55]]}])):
        write("sketch_create", {"name": name, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": geometry})
    write("view_set", {"action": "orient", "focus": ["EditCorner", "FilletPath"], "orientation": "top", "fit": True})
    write("sketch_edit_curve", {"sketch_name": "EditCorner", "action": "fillet", "entity_one": "line:0",
                                "entity_two": "line:1", "x1": 655, "y1": 0, "x2": 660, "y2": 5, "radius": 10},
          lambda p: _near(p.get("radius"), 10, .001))
    corner = lambda c: {"sketch_name": "EditCorner", "include_entities": True, "units": "mm"}
    path = {"sketch_name": "FilletPath", "include_entities": True, "units": "mm"}
    rows += [("sketch_get", corner, _solved_fillet_effect(True), None),
             ("sketch_get", corner, _retire_compare("fillet_control", _retire_sketch_state, False), None),
             ("sketch_get", path, _retire_compare("fillet_before", _retire_sketch_state, False), None),
             ("design_get", {"include": ["timeline"], "max_results": 200},
              _retire_compare("fillet_history", lambda p: p.get("timeline") if _timeline_names(p) is not None else None,
                              False), None)]
    write("sketch_edit_curve", {"sketch_name": "FilletPath", "action": "fillet", "entity_one": "line:0",
                                "entity_two": "line:1", "x1": 200, "y1": -30, "x2": 230, "y2": -36, "radius": 20},
          _FilletRadiusRefusal("fillet_reported_radius"))
    rows += [("sketch_get", path, _solved_fillet_effect(), None),
             ("sketch_get", corner, _retire_compare("fillet_control", _retire_sketch_state, True), None),
             ("design_get", {"include": ["timeline"], "max_results": 200},
              _retire_compare("fillet_history", lambda p: p.get("timeline") if _timeline_names(p) is not None else None,
                              True), None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "fillet_story", "story"),
                                         "expect_document": _ctx_get(c, "fillet_doc", "scratch")}, _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "fillet_doc", "scratch"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "fillet_story", "story")}, _document_closed, None)]
    return rows


_SKETCHWORK += _fillet_radius_rows()


def _scratch_rows(key):
    """(rows opening an owned scratch document under `key`, its write, its read, its close)."""
    home = key + "_home"
    rows = [("doc_get", {}, _home_document, (home, _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, home, "home")},
             _new_document, (key, lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: {**(args(c) if callable(args) else args),
                     "expect_document": _ctx_get(c, key, "scratch")}, check, save))

    def read(tool, args, check, save=None):
        rows.append((tool, lambda c, args=args: args(c) if callable(args) else dict(args),
                     check, save))

    def close():
        rows.extend([("doc_activate", lambda c: {"name": _ctx_get(c, home, "home"),
                                                 "expect_document": _ctx_get(c, key, "scratch")},
                      _activated(), None),
                     ("doc_close", lambda c: {"name": _ctx_get(c, key, "scratch"),
                                              "save_changes": False,
                                              "expect_document": _ctx_get(c, home, "home")},
                      _document_closed, None)])
    return rows, write, read, close


def _two_source_pattern(p):
    """The pattern names both source circles then both directions; the copies sit 40 mm along x."""
    rows = _rows_by_id(p)
    pats = [c.get("entities") for c in p.get("constraints") or []
            if c.get("type") == "rectangular_pattern"]
    circles = [(i, (rows.get(i) or {}).get("center") or {}, (rows.get(i) or {}).get("radius"))
               for i in ("circle:0", "circle:1", "circle:2", "circle:3")]
    want = [(300, 5), (320, 4), (340, 5), (360, 4)]
    return _measured("two-source rectangular pattern by ids and coordinates", {"pattern": pats,
                                                                              "circles": circles},
                     p.get("truncated") is False
                     and pats == [["circle:0", "circle:1", "line:0", "line:1"]]
                     and all(_near(c.get("x"), x, .01) and _near(c.get("y"), 300, .01)
                             and _near(r, rad, .01) for (_i, c, r), (x, rad) in zip(circles, want)))


def _pattern_witness_rows():
    """A rectangular pattern of TWO source circles, its constraint ids read against coordinates."""
    rows, write, read, close = _scratch_rows("refpat_doc")
    write("sketch_create", {"plane": "xy", "name": "RefPat"})
    write("sketch_add_geometry", {"sketch_name": "RefPat", "geometry": [
        {"kind": "circle", "cx": 300, "cy": 300, "radius": 5},
        {"kind": "circle", "cx": 320, "cy": 300, "radius": 4}]})
    write("sketch_add_geometry", {"sketch_name": "RefPat", "geometry": [
        {"kind": "line", "x1": 300, "y1": 320, "x2": 400, "y2": 320}]})
    write("sketch_add_geometry", {"sketch_name": "RefPat", "geometry": [
        {"kind": "line", "x1": 300, "y1": 320, "x2": 300, "y2": 420}]})
    write("sketch_constrain", {"sketch_name": "RefPat", "constraints": [{
        "constraint": "rectangular_pattern", "entities": "circle:0,circle:1", "entity_one": "line:0",
        "entity_two": "line:1", "quantity": 2, "distance": 40, "quantity_two": 1,
        "distance_two": 10}]}, lambda p: p["results"][0].get("created_count") == 2)
    read("sketch_get", {"sketch_name": "RefPat", "include_entities": True, "max_results": 200},
         _two_source_pattern)
    close()
    return rows


_SKETCHWORK += _pattern_witness_rows()


def _profile_with(area_mm2, loops):
    """sketch_get: the ONE profile of this area and loop count; saves its handle."""
    def pick(p):
        hits = [r for r in p.get("profiles") or []
                if _near(r.get("area"), area_mm2, 0.01) and r.get("loop_count") == loops]
        if len(hits) != 1 or not hits[0].get("handle"):
            raise AssertionError(f"no single {area_mm2} mm2 {loops}-loop profile: {p.get('profiles')}")
        return hits[0]["handle"]
    return pick


def _largest_planar_face(area_mm2):
    """find_geometry: the largest planar face of the scoped part reads this area."""
    def check(p):
        areas = [m.get("area") for m in p.get("matches") or [] if m.get("kind") == "planar_face"]
        return _measured(f"largest planar face {area_mm2} mm2", areas,
                         bool(areas) and p.get("truncated") is not True
                         and _near(max(a for a in areas if isinstance(a, (int, float))), area_mm2, 0.01))
    return check


def _placed_profile_handle_rows():
    """Profile handles minted by sketch_get in placed components, consumed by extrude and flange."""
    rows, write, read, close = _scratch_rows("profile_doc")
    write("model_create_component", {"name": "YCarriage", "activate": True, "x": 30, "y": 50},
          _made_component)
    write("model_construction", {"kind": "plane", "plane": "xy", "offset": -42, "name": "ZGuideBase"},
          _datum_plane("xy"))
    write("sketch_create", {"plane": "ZGuideBase", "name": "KeyedZGuide"})
    write("sketch_add_geometry", {"sketch_name": "KeyedZGuide", "geometry": [
        {"kind": "rectangle", "x1": -20, "y1": -20, "x2": 20, "y2": 20},
        {"kind": "rectangle", "x1": -16, "y1": -16, "x2": 16, "y2": 16}]})
    # The annulus's token also answers its island profile; the handle must still name the annulus.
    read("sketch_get", {"sketch_name": "KeyedZGuide", "component": "YCarriage:1"}, "ok",
         ("guide_ring", _profile_with(576.0, 2)))
    write("model_extrude", lambda c: {"sketch_name": "KeyedZGuide", "component": "YCarriage:1",
                                      "profile_index": _ctx_get(c, "guide_ring", "annulus handle"),
                                      "distance": 10, "operation": "new"},
          lambda p: _extruded(p) and p.get("component") == "YCarriage")
    read("model_inspect", {"target": "YCarriage:1", "include": ["default", "mass"], "units": "mm"},
         lambda p: _measured("annulus extrude volume", p.get("mass"),
                             _near((p.get("mass") or {}).get("volume"), 5760, 0.5)))
    read("find_geometry", {"target": "YCarriage:1", "kind": "planar_face", "max_results": 20},
         _largest_planar_face(576.0))
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "SheetTray", "activate": True}, _made_component)
    write("model_construction", {"kind": "plane", "plane": "xy", "offset": -44, "name": "TrayBase"},
          _datum_plane("xy"))
    write("sketch_create", {"plane": "TrayBase", "name": "TrayBlank"})
    write("sketch_add_geometry", {"sketch_name": "TrayBlank", "geometry": [
        {"kind": "rectangle", "x1": -32, "y1": 18, "x2": 32, "y2": 101.5},
        {"kind": "rectangle", "x1": -12, "y1": 40, "x2": 12, "y2": 44},
        {"kind": "rectangle", "x1": -12, "y1": 70, "x2": 12, "y2": 74}]})
    read("sketch_get", {"sketch_name": "TrayBlank", "component": "SheetTray:1"}, "ok",
         ("tray_blank", _profile_with(5152.0, 3)))
    write("sheet_create_flange", lambda c: {"kind": "base", "component": "SheetTray:1",
                                            "profile": _ctx_get(c, "tray_blank", "blank handle"),
                                            "orientation": "side_one"},
          lambda p: p.get("created") is True)
    read("find_geometry", {"target": "SheetTray:1", "kind": "planar_face", "max_results": 40},
         _largest_planar_face(5152.0))
    close()
    return rows


_SKETCHWORK += _placed_profile_handle_rows()


# --- sketch_edit, the curve state flags and a dimension's driving flag, each on owned geometry ---

class _NamedRefusal(_Refusal):
    """A refusal that must also carry fragments built from recalled values."""
    def __init__(self, *fragments, recalled):
        super().__init__(fragments)
        self.recalled = recalled

    def missing(self, text):
        try:
            extra = list(self.recalled(_RECALL))
        except Exception as exc:
            return [f"recalled fragments: {exc}"]
        return [f for f in (*self.fragments, *extra) if f not in text]


_HISTORY = {"include": ["timeline"], "max_results": 200}


def _xray(sketch_name, **scope):
    """sketch_get arguments for one sketch's full X-ray in mm."""
    return {"sketch_name": sketch_name, "include_entities": True, "max_results": 200,
            "units": "mm", **scope}


def _inspect(target):
    """model_inspect arguments for a body's box and physical properties in mm."""
    return {"target": target, "include": ["default", "mass"], "units": "mm",
            "accuracy": "very_high"}


def _solid(key):
    """model_inspect arguments for the body whose name an earlier step saved under `key`."""
    return lambda c: _inspect(_ctx_get(c, key, "the extruded body's name"))


def _alike(a, b, tol):
    """Whether two JSON values match, numbers within `tol`."""
    if _num(a) and _num(b):
        return abs(a - b) <= tol
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_alike(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_alike(x, y, tol) for x, y in zip(a, b))
    return a == b


def _unchanged(key, pick, tol=0.0):
    """A read whose picked facts match the ones recalled under `key`."""
    def check(p):
        now, before = pick(p), _RECALL.get(key)
        return _measured(f"{key} unchanged", {"before": before, "now": now},
                         now is not None and before is not None and _alike(now, before, tol))
    return check


def _keep(read, tool, args, key, pick, also=None):
    """Append a first read recalling `pick` under `key`, judged by `also` as well when given."""
    def check(p):
        return _measured(f"{key} first read", pick(p),
                         pick(p) is not None and (also is None or bool(also(p))))
    read(tool, args, check, (key, _recall(key, pick)))


def _sketch_facts(p):
    """One sketch's X-ray without its name or handle text, or None when the read is partial."""
    if (p.get("truncated") is not False or p.get("profiles_stale")
            or p.get("timeline_marker_unrestored") or not isinstance(p.get("entities"), list)
            or not isinstance(p.get("profiles"), list) or not isinstance(p.get("frame"), dict)):
        return None
    facts = {k: p.get(k) for k in ("component", "plane", "counts", "constraints", "dimensions",
                                   "frame", "profile_count", "construction_count",
                                   "driving_dimension_count")}
    facts["entities"] = [{k: v for k, v in e.items() if k != "handle"} for e in p["entities"]]
    facts["profiles"] = [{k: v for k, v in r.items() if k != "handle"} for r in p["profiles"]]
    return facts


def _sketch_list(p):
    """sketch_get list: every row by sketch name, or None when the list is cut or names repeat."""
    rows = p.get("sketches")
    if not isinstance(rows, list) or p.get("truncated") or p.get("sketch_count") != len(rows):
        return None
    by_name = {r.get("name"): r for r in rows}
    return by_name if len(by_name) == len(rows) else None


def _body_facts(p):
    """A body's world box, volume and centre of mass in mm, or None when one did not read."""
    mass = p.get("mass") or {}
    lo, hi, com = p.get("min_point"), p.get("max_point"), mass.get("center_of_mass")
    if (p.get("units") != "mm" or not isinstance(lo, dict) or not isinstance(hi, dict)
            or not _vec3(com) or not _num(mass.get("volume"))
            or not all(_num(d.get(a)) for d in (lo, hi) for a in "xyz")):
        return None
    return {"min": [lo[a] for a in "xyz"], "max": [hi[a] for a in "xyz"],
            "volume": mass["volume"], "center_of_mass": com}


def _box_reads(dx, dy, dz):
    """model_inspect: a box of these extents in mm, its volume their product."""
    def check(p):
        return (_near(p.get("x"), dx, 1e-3) and _near(p.get("y"), dy, 1e-3)
                and _near(p.get("z"), dz, 1e-3)
                and _near((p.get("mass") or {}).get("volume"), dx * dy * dz, 0.5))
    return check


def _boxed(write, name, rect, height, key):
    """Rows extruding rectangle `rect` drawn on root XY sketch `name`; the body name saves as `key`."""
    write("sketch_create", {"plane": "xy", "name": name})
    write("sketch_add_geometry", {"sketch_name": name, "geometry": [
        {"kind": "rectangle", "x1": rect[0], "y1": rect[1], "x2": rect[2], "y2": rect[3]}]})
    write("model_extrude", {"sketch_name": name, "profile_index": 0, "distance": height,
                            "operation": "new"},
          _extruded, (key, _recall(key, lambda p: p["result_bodies"][0])))


def _vec3(v):
    return isinstance(v, list) and len(v) == 3 and all(_num(c) for c in v)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _frame_on(frame, point, normal):
    """Whether a world sketch frame has its origin on, and its normal parallel to, the plane."""
    if not isinstance(frame, dict) or frame.get("space") != "world":
        return False
    o, n, x, y = (frame.get(k) for k in ("origin_mm", "normal", "x_world", "y_world"))
    point, normal = list(point), list(normal)
    if not all(_vec3(v) for v in (o, n, x, y, point, normal)):
        return False
    return (abs(abs(_dot(n, normal)) - 1) < 1e-5
            and abs(_dot([a - b for a, b in zip(o, point)], normal)) < 1e-3
            and all(abs(_dot(a, b)) < 1e-5 for a, b in ((x, n), (y, n), (x, y))))


def _support(p):
    """sketch_get: where a sketch sits - its frame and the plane it names - or None if unread."""
    frame = p.get("frame")
    return {"frame": frame, "plane": p.get("plane")} if isinstance(frame, dict) else None


# --- sketch_edit(new_name) ---------------------------------------------------------------------

def _renamed(previous, wanted, exact=False):
    """sketch_edit(new_name): the adopted name read back, and an address naming that sketch."""
    def check(p):
        name, address = p.get("name"), p.get("address")
        good = (p.get("action") == "new_name" and p.get("previous_name") == previous
                and p.get("requested_name") == wanted and isinstance(name, str) and bool(name)
                and p.get("adopted_differs") is (name != wanted)
                and p.get("old_name_resolves") is False and "unread" not in p
                and isinstance(address, dict) and address.get("sketch_name") == name
                and set(address) <= {"sketch_name", "component"}
                and (name != wanted or exact or bool(address.get("component"))))
        if exact:
            good = good and name == wanted and address == {"sketch_name": wanted}
        return _measured(f"'{previous}' renamed for '{wanted}'",
                         {k: p.get(k) for k in ("previous_name", "requested_name", "name",
                                                "adopted_differs", "old_name_resolves",
                                                "address", "unread")}, good)
    return check


def _sketch_reads(key, name=None, address_key=None):
    """sketch_get: the facts recalled under `key`, answering to the expected sketch name."""
    def check(p):
        want = name if name is not None else (_RECALL.get(address_key) or {}).get("sketch_name")
        return (_unchanged(key, _sketch_facts)(p)
                and _measured("sketch name", {"sketch": p.get("sketch"), "want": want},
                              bool(want) and p.get("sketch") == want))
    return check


def _history_with(key, was, now):
    """design_get: the recalled timeline, healthy, with one row answering to its new name."""
    def check(p):
        new = now() if callable(now) else now
        want = [new if n == was else n for n in _RECALL.get(key) or []]
        return _measured(f"timeline row '{was}' now reads '{new}'",
                         {"rows": _timeline_names(p), "want": want},
                         bool(new) and was in (_RECALL.get(key) or [])
                         and _timeline_names(p) == want)
    return check


def _sketch_rename_rows():
    """Rename a sketch, read it by both names, then rename onto a name another component holds."""
    rows, write, read, close = _scratch_rows("ren_doc")
    _boxed(write, "RenSrc", (0, 0, 20, 10), 5, "ren_body")
    write("sketch_create", {"plane": "xy", "name": "RenCtl"})
    write("sketch_add_geometry", {"sketch_name": "RenCtl", "geometry": [
        {"kind": "line", "x1": 40, "y1": 0, "x2": 60, "y2": 0}]})
    write("model_create_component", {"name": "RenOther", "activate": True}, _made_component)
    write("sketch_create", {"plane": "xy", "name": "RenTaken"})
    write("sketch_add_geometry", {"sketch_name": "RenTaken", "geometry": [
        {"kind": "line", "x1": 0, "y1": 40, "x2": 20, "y2": 40}]})
    write("design_activate_component", {"occurrence": "root"})
    other = _xray("RenTaken", component="RenOther:1")
    _keep(read, "sketch_get", _xray("RenSrc"), "ren_src", _sketch_facts,
          lambda p: p["counts"]["lines"] == 4 and p["profile_count"] == 1)
    _keep(read, "sketch_get", _xray("RenCtl"), "ren_ctl", _sketch_facts)
    _keep(read, "sketch_get", other, "ren_other", _sketch_facts,
          lambda p: p["component"] == "RenOther" and p["counts"]["lines"] == 1)
    _keep(read, "model_inspect", _solid("ren_body"), "ren_solid", _body_facts, _box_reads(20, 10, 5))
    _keep(read, "design_get", _HISTORY, "ren_history", _timeline_names,
          lambda p: "RenSrc" in _timeline_names(p))

    # The first name is free: it is adopted as asked and the former one stops resolving.
    write("sketch_edit", {"sketch_name": "RenSrc", "new_name": "RenNew"},
          _renamed("RenSrc", "RenNew", exact=True))
    read("sketch_get", _xray("RenNew"), _sketch_reads("ren_src", "RenNew"))
    read("sketch_get", {"sketch_name": "RenSrc"}, _refused("No sketch named 'RenSrc'", "RenNew"))
    read("design_get", _HISTORY, _history_with("ren_history", "RenSrc", "RenNew"))
    read("model_inspect", _solid("ren_body"), _unchanged("ren_solid", _body_facts, 1e-3))
    read("sketch_get", _xray("RenCtl"), _unchanged("ren_ctl", _sketch_facts))

    # 'RenTaken' is held by a sketch of RenOther; the reply's address is what the next read uses.
    def adopted():
        return (_RECALL.get("ren_addr") or {}).get("sketch_name")

    def addressed(c):
        return _xray(**_ctx_get(c, "ren_addr", "the renamed sketch's address"))

    write("sketch_edit", {"sketch_name": "RenNew", "new_name": "RenTaken"},
          _renamed("RenNew", "RenTaken"), ("ren_addr", _recall("ren_addr", lambda p: p["address"])))
    read("sketch_get", addressed, _sketch_reads("ren_src", address_key="ren_addr"))
    read("sketch_get", other, _unchanged("ren_other", _sketch_facts))
    read("design_get", _HISTORY, _history_with("ren_history", "RenSrc", adopted))
    read("model_inspect", _solid("ren_body"), _unchanged("ren_solid", _body_facts, 1e-3))

    def same_name(c):
        address = _ctx_get(c, "ren_addr", "the renamed sketch's address")
        return {**address, "new_name": address["sketch_name"]}

    write("sketch_edit", same_name,
          _NamedRefusal("already has that name", "nothing was changed",
                        recalled=lambda r: [f"Sketch '{r['ren_addr']['sketch_name']}'"]))
    read("sketch_get", addressed, _sketch_reads("ren_src", address_key="ren_addr"))
    read("sketch_get", _xray("RenCtl"), _unchanged("ren_ctl", _sketch_facts))
    close()
    return rows


_SKETCHWORK += _sketch_rename_rows()


def _axis_point(p, ref, which):
    """The sketch-local XYZ start or end in mm for one line row."""
    row = _rows_by_id(p).get(ref) or {}
    point = row.get(which) or {}
    return (tuple(point.get(a, 0.0) for a in "xyz")
            if all(a in point for a in "xy") else None)


def _axis_at(p, ref, xyz, which="end"):
    """Whether sketch_get reads one line point at the expected XYZ position."""
    got = _axis_point(p, ref, which)
    return _measured(f"{ref} {which} XYZ", {"got": got, "want": xyz},
                     got is not None and all(abs(a - b) < 0.01 for a, b in zip(got, xyz)))


def _axis_transform_rows():
    """Rotate a moved and a copied line about local X with an off-plane pivot."""
    rows, write, read, close = _scratch_rows("axis_doc")
    for name in ("AxisMove", "AxisCopy"):
        write("sketch_create", {"plane": "xy", "name": name})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [
            {"kind": "line", "x1": 0, "y1": 0, "x2": 0, "y2": 10}]})
        read("sketch_get", _xray(name), lambda p: _axis_at(p, "line:0", (0, 10, 0)))
    transform = {"rotation_deg": 45, "rotation_axis": [1, 0, 0], "center_z": 5}
    write("sketch_move", {"sketch_name": "AxisMove", "entities": "line:0", **transform},
          lambda p: p.get("moved_entities") == ["line:0"]
          and p.get("coordinates_verified") is True)
    read("sketch_get", _xray("AxisMove"),
         lambda p: _axis_at(p, "line:0", (0, 3.5355, 1.4645), "start")
         and _axis_at(p, "line:0", (0, 10.6066, 8.5355)))
    write("sketch_copy", {"sketch_name": "AxisCopy", "entities": "line:0", **transform},
          lambda p: p.get("new_curves") == ["line:1"]
          and p.get("curve_count_after") - p.get("curve_count_before") == 1
          and p.get("coordinates_verified") is True)
    read("sketch_get", _xray("AxisCopy"),
         lambda p: _axis_at(p, "line:0", (0, 0, 0), "start")
         and _axis_at(p, "line:0", (0, 10, 0))
         and _axis_at(p, "line:1", (0, 3.5355, 1.4645), "start")
         and _axis_at(p, "line:1", (0, 10.6066, 8.5355)))
    write("sketch_move", {"sketch_name": "AxisMove", "entities": "line:0",
                          "rotation_deg": 45, "rotation_axis": [0, 0, 0]}, "refused")
    write("sketch_copy", {"sketch_name": "AxisCopy", "entities": "line:0",
                          "dx": 1, "rotation_axis": [1, 0, 0]}, "refused")
    write("sketch_copy", {"sketch_name": "AxisCopy", "entities": "line:0",
                          "mirror_line": "line:0", "rotation_axis": [1, 0, 0]}, "refused")
    close()
    return rows


_SKETCHWORK += _axis_transform_rows()


# --- sketch_edit(visible) ----------------------------------------------------------------------

def _bulb_set(sketch, want, before):
    """sketch_edit(visible): the bulb and the effective visibility either side of the write."""
    def check(p):
        changed = before is not want
        return _measured(f"'{sketch}' bulb {before} -> {want}",
                         {k: p.get(k) for k in ("requested", "bulb_before", "bulb_after",
                                                "effective_visible_before",
                                                "effective_visible_after", "changed", "unread")},
                         p.get("action") == "visible" and p.get("sketch") == sketch
                         and p.get("requested") is want and p.get("bulb_before") is before
                         and p.get("bulb_after") is want and p.get("changed") is changed
                         and p.get("effective_visible_before") is before
                         and p.get("effective_visible_after") is want and "unread" not in p
                         and ("nothing was written" in (p.get("note") or "")) is (not changed))
    return check


def _listed(key, name, visible):
    """sketch_get list: every row as first read, except `name`'s effective visibility."""
    def check(p):
        base, now = _RECALL.get(key) or {}, _sketch_list(p)
        want = {n: (dict(r, is_visible=visible) if n == name else r) for n, r in base.items()}
        return _measured(f"sketch rows with '{name}' visible {visible}",
                         {"now": now, "want": want}, name in base and now == want)
    return check


def _sketch_visible_rows():
    """Turn a sketch's bulb off and on; the sketch list reads its visibility beside a control."""
    rows, write, read, close = _scratch_rows("bulb_doc")
    for name, y in (("BulbSk", 0), ("BulbCtl", 30)):
        write("sketch_create", {"plane": "xy", "name": name})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [
            {"kind": "line", "x1": 0, "y1": y, "x2": 20, "y2": y}]})
    _keep(read, "sketch_get", {}, "bulb_list", _sketch_list,
          lambda p: all(_sketch_list(p)[n]["is_visible"] is True for n in ("BulbSk", "BulbCtl")))
    _keep(read, "sketch_get", _xray("BulbSk"), "bulb_sketch", _sketch_facts)
    write("sketch_edit", {"sketch_name": "BulbSk", "visible": False},
          _bulb_set("BulbSk", False, True))
    read("sketch_get", {}, _listed("bulb_list", "BulbSk", False))
    write("sketch_edit", {"sketch_name": "BulbSk", "visible": False},
          _bulb_set("BulbSk", False, False))
    read("sketch_get", {}, _listed("bulb_list", "BulbSk", False))
    write("sketch_edit", {"sketch_name": "BulbSk", "visible": True},
          _bulb_set("BulbSk", True, False))
    read("sketch_get", {}, _listed("bulb_list", "BulbSk", True))
    read("sketch_get", _xray("BulbSk"), _unchanged("bulb_sketch", _sketch_facts))
    close()
    return rows


_SKETCHWORK += _sketch_visible_rows()


# --- sketch_edit(plane) ------------------------------------------------------------------------

def _plane_moved(tag, sketch, label, plane_after=None, later=None):
    """sketch_edit(plane): redefine took, the frame is on the target and no later row broke."""
    def check(p):
        was = _RECALL.get(tag + "_at") or {}
        target = label() if callable(label) else label
        rows, unread = p.get("later_features"), p.get("unread") or {}
        named = (p.get("plane_after") == plane_after and "plane_after" not in unread
                 if plane_after else
                 p.get("plane_after") is None and "BRefFace" in str(unread.get("plane_after")))
        return _measured(
            f"'{sketch}' redefined onto {target}",
            {k: p.get(k) for k in (
                "requested_plane", "redefine_returned", "plane_before", "plane_after",
                "on_target_plane", "normal_vs_target", "origin_off_plane_mm", "frame_before",
                "frame_after", "frame_changed", "sketch_health", "later_features",
                "new_timeline_errors", "new_timeline_warnings", "marker_before", "marker_after",
                "unread")},
            p.get("action") == "plane" and p.get("sketch") == sketch
            and p.get("requested_plane") == target and p.get("redefine_returned") is True
            and p.get("on_target_plane") is True
            and p.get("normal_vs_target") in ("same", "opposed")
            and _num(p.get("origin_off_plane_mm")) and abs(p["origin_off_plane_mm"]) < 1e-3
            and isinstance(was.get("frame"), dict) and p.get("frame_before") == was["frame"]
            and p.get("plane_before") == was.get("plane") and p.get("frame_changed") is True
            and isinstance(p.get("frame_after"), dict) and named
            and p.get("sketch_health") == "healthy" and isinstance(rows, list)
            and all(r.get("health") == "healthy" for r in rows)
            and (later is None or [r.get("name") for r in rows] == later())
            and p.get("later_features_truncated") is False
            and p.get("new_timeline_errors") == [] and p.get("new_timeline_warnings") == []
            and _num(p.get("marker_before")) and p.get("marker_before") == p.get("marker_after"))
    return check


def _sketch_on(tag, sketch, plane, plane_name=None, face_body=None, origin=None):
    """sketch_get: the frame is on `plane`, equals the edit's frame_after and names its support."""
    def check(p):
        point, normal = plane() if callable(plane) else plane
        frame, face = p.get("frame"), p.get("on_face") or {}
        support = (p.get("plane") == plane_name and "on_face" not in p if face_body is None
                   else p.get("plane") is None and bool(face.get("handle"))
                   and face.get("body") == _RECALL.get(face_body))
        return _measured(f"'{sketch}' frame on its target plane",
                         {"frame": frame, "plane": p.get("plane"), "on_face": p.get("on_face"),
                          "target": [list(point), list(normal)]},
                         p.get("sketch") == sketch and _frame_on(frame, point, normal)
                         and frame == _RECALL.get(tag + "_reply") and support
                         and (origin is None or _alike(frame["origin_mm"], list(origin), 1e-3))
                         and p.get("profile_count") == 1
                         and not p.get("timeline_marker_unrestored"))
    return check


def _body_on_frame(tag, centre, height, volume, rect=None):
    """model_inspect: the extrude sits where the sketch frame read under `tag` puts its profile."""
    def check(p):
        frame = (_RECALL.get(tag + "_at") or {}).get("frame") or {}
        o, n, x, y = (frame.get(k) for k in ("origin_mm", "normal", "x_world", "y_world"))
        mass = p.get("mass") or {}
        com = mass.get("center_of_mass")
        good = all(_vec3(v) for v in (o, n, x, y, com)) and _near(mass.get("volume"), volume, 0.5)
        if good:
            rel = [c - q for c, q in zip(com, o)]
            # The side of the plane the extrude grows to is read, not asserted.
            good = (abs(_dot(rel, x) - centre[0]) < 0.01 and abs(_dot(rel, y) - centre[1]) < 0.01
                    and abs(abs(_dot(rel, n)) - height / 2) < 0.01)
        if good and rect is not None:
            lo, hi = p.get("min_point") or {}, p.get("max_point") or {}

            def box(side):
                corners = [[o[i] + u * x[i] + v * y[i] + w * side * n[i] for i in range(3)]
                           for u in rect[0::2] for v in rect[1::2] for w in (0, height)]
                return [(min(c[i] for c in corners), max(c[i] for c in corners)) for i in range(3)]
            good = any(all(_near(lo.get(a), span[i][0], 0.01) and _near(hi.get(a), span[i][1], 0.01)
                           for i, a in enumerate("xyz")) for span in (box(1), box(-1)))
        return _measured("extrude follows the sketch frame",
                         {"frame": frame, "center_of_mass": com, "volume": mass.get("volume"),
                          "min_point": p.get("min_point"), "max_point": p.get("max_point")}, good)
    return check


def _x_axis_edges(p):
    """find_geometry: the 20 mm line edges lying on the world X axis."""
    return [m for m in p.get("matches") or []
            if m.get("kind") == "line_edge" and _near(m.get("length"), 20, 1e-3)
            and _vec3(m.get("position")) and abs(m["position"][1]) < 1e-6
            and abs(m["position"][2]) < 1e-6 and m.get("handle")]


def _face_at(position, normal):
    """A save slot's extractor: the handle of the one planar face at this centroid and normal."""
    def pick(p):
        hits = [m for m in p.get("matches") or []
                if m.get("kind") == "planar_face" and _alike(m.get("position"), position, 1e-4)
                and _alike(m.get("normal"), normal, 1e-4) and m.get("handle")]
        if len(hits) != 1:
            raise AssertionError(f"no single planar face at {position} facing {normal}: "
                                 f"{[(m.get('position'), m.get('normal')) for m in p.get('matches') or []]}")
        return hits[0]["handle"]
    return pick


def _turned_plane(p):
    """model_construction(at_angle): a plane through the world X axis, 30 deg off XY."""
    geometry = p.get("geometry") or {}
    o, n = geometry.get("origin") or {}, geometry.get("normal")
    return _measured("plane turned 30 deg about the world X axis",
                     {"name": p.get("name"), "angle_deg": p.get("angle_deg"), "geometry": geometry},
                     p.get("name") == "PlTurn" and _near(p.get("angle_deg"), 30, 1e-6)
                     and _vec3(n) and abs(n[0]) < 1e-5 and _near(abs(n[1]), 0.5, 1e-5)
                     and _near(abs(n[2]), 0.866025, 1e-5)
                     and all(_num(o.get(a)) for a in "xyz")
                     and abs(o["y"] * n[1] + o["z"] * n[2]) < 1e-4)


_PLANE_RECT = (10, 5, 30, 15)       # PlMove's profile in sketch mm; extruded 6 mm it holds 1200 mm3


def _sketch_plane_rows():
    """Move a root sketch to an offset plane, a turned plane and an earlier face; refuse a later one."""
    rows, write, read, close = _scratch_rows("pl_doc")
    _boxed(write, "PlBase", (40, 0, 60, 30), 10, "pl_base")
    read("find_geometry", lambda c: {"target": _ctx_get(c, "pl_base", "the base body"),
                                     "kind": "line_edge", "units": "mm", "max_results": 50},
         lambda p: p.get("match_count") == 12 and len(_x_axis_edges(p)) == 1,
         ("pl_edge", lambda p: _x_axis_edges(p)[0]["handle"]))
    write("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy", "offset": 7,
                                 "name": "PlOff"},
          lambda p: _datum_plane("xy")(p) and p.get("name") == "PlOff"
          and _near((p["geometry"].get("origin") or {}).get("z"), 7, 1e-6))
    write("model_construction", lambda c: {
        "kind": "plane", "mode": "at_angle", "plane": "xy", "angle": 30, "name": "PlTurn",
        "edges": [_ctx_get(c, "pl_edge", "the base edge on the X axis")]},
        _turned_plane, ("pl_turn", _recall("pl_turn", lambda p: [
            [p["geometry"]["origin"][a] for a in "xyz"], p["geometry"]["normal"]])))
    _boxed(write, "PlMove", _PLANE_RECT, 6, "pl_dep")
    _boxed(write, "PlLate", (40, -40, 60, -20), 10, "pl_late")
    _boxed(write, "PlCtl", (-40, -40, -20, -20), 4, "pl_ctl")
    for body, key, position, normal in (("pl_base", "pl_base_face", [60, 15, 5], [1, 0, 0]),
                                        ("pl_late", "pl_late_face", [50, -30, 10], [0, 0, 1])):
        read("find_geometry", lambda c, body=body: {
            "target": _ctx_get(c, body, "the body's name"), "kind": "planar_face", "units": "mm",
            "max_results": 20},
            lambda p: p.get("match_count") == 6, (key, _face_at(position, normal)))

    def follows(rect=None):
        return _body_on_frame("pl", (20, 10), 6, 1200, rect)

    def later():
        names = _RECALL.get("pl_history") or []
        return names[names.index("PlMove") + 1:] if "PlMove" in names else None

    _keep(read, "sketch_get", _xray("PlMove"), "pl_at", _support,
          lambda p: _frame_on(p["frame"], (0, 0, 0), (0, 0, 1))
          and _alike(p["frame"]["origin_mm"], [0, 0, 0], 1e-3) and bool(p.get("plane")))
    read("model_inspect", _solid("pl_dep"), follows(_PLANE_RECT),
         ("pl_dep_solid", _recall("pl_dep_solid", _body_facts)))
    _keep(read, "design_get", _HISTORY, "pl_history", _timeline_names,
          lambda p: "PlMove" in _timeline_names(p)[:-1])
    _keep(read, "sketch_get", _xray("PlCtl"), "pl_ctl_sketch", _sketch_facts)
    _keep(read, "model_inspect", _solid("pl_ctl"), "pl_ctl_solid", _body_facts, _box_reads(20, 20, 4))

    def unmoved():
        read("design_get", _HISTORY, _unchanged("pl_history", _timeline_names))
        read("sketch_get", _xray("PlCtl"), _unchanged("pl_ctl_sketch", _sketch_facts))
        read("model_inspect", _solid("pl_ctl"), _unchanged("pl_ctl_solid", _body_facts, 1e-3))

    def move(args, label, plane, plane_name=None, face_body=None, rect=None):
        write("sketch_edit", args, _plane_moved("pl", "PlMove", label, plane_name, later),
              ("pl_reply", _recall("pl_reply", lambda p: p["frame_after"])))
        read("sketch_get", _xray("PlMove"),
             _sketch_on("pl", "PlMove", plane, plane_name, face_body),
             ("pl_at", _recall("pl_at", _support)))
        read("model_inspect", _solid("pl_dep"), follows(rect),
             ("pl_dep_solid", _recall("pl_dep_solid", _body_facts)))
        unmoved()

    # The target planes in world mm: z = 7, the turned plane as it was built, and the base's x = 60.
    move({"sketch_name": "PlMove", "plane": "PlOff"}, "plane 'PlOff'",
         ((0, 0, 7), (0, 0, 1)), plane_name="PlOff", rect=_PLANE_RECT)
    move({"sketch_name": "PlMove", "plane": "PlTurn"}, "plane 'PlTurn'",
         lambda: _RECALL["pl_turn"], plane_name="PlTurn")
    move(lambda c: {"sketch_name": "PlMove",
                    "plane": _ctx_get(c, "pl_base_face", "the base body's x = 60 face")},
         lambda: f"a face of body '{_RECALL.get('pl_base')}'",
         ((60, 0, 0), (1, 0, 0)), face_body="pl_base", rect=_PLANE_RECT)

    # PlLate's body is built after PlMove, so its face cannot carry it.
    write("sketch_edit", lambda c: {"sketch_name": "PlMove",
                                    "plane": _ctx_get(c, "pl_late_face", "the later body's top face")},
          _refused("Sketch.redefine raised on sketch 'PlMove'", "CIRCULAR_DEPENDENCY",
                   "The sketch was not moved: its frame reads as before"))
    read("sketch_get", _xray("PlMove"), _unchanged("pl_at", _support))
    read("model_inspect", _solid("pl_dep"), _unchanged("pl_dep_solid", _body_facts, 1e-3))
    unmoved()
    close()
    return rows


_SKETCHWORK += _sketch_plane_rows()


# A sketch on the XY plane of a component turned 90 deg about world Y and set at x = 50 mm.
_PLACED_XY_FRAME = {"origin_mm": [50, 0, 0], "normal": [1, 0, 0], "space": "world",
                    "x_world": [0, 0, -1], "y_world": [0, 1, 0]}


def _sketch_plane_placed_rows():
    """Move a sketch of a turned, translated component from that component's XY plane to its XZ."""
    rows, write, read, close = _scratch_rows("pc_doc")
    write("sketch_create", {"plane": "xy", "name": "PcCtl"})
    write("sketch_add_geometry", {"sketch_name": "PcCtl", "geometry": [
        {"kind": "line", "x1": 0, "y1": 30, "x2": 20, "y2": 30}]})
    write("model_create_component", {"name": "PcChild", "activate": True, "x": 50,
                                     "rotate_deg": 90, "rotate_axis": "y"}, _made_component)
    write("sketch_create", {"plane": "xy", "name": "PcSketch"})
    write("sketch_add_geometry", {"sketch_name": "PcSketch", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]})
    write("design_activate_component", {"occurrence": "root"})
    placed = _xray("PcSketch", component="PcChild:1")
    _keep(read, "sketch_get", placed, "pc_at", _support,
          lambda p: p.get("plane") == "XY" and _alike(p["frame"], _PLACED_XY_FRAME, 1e-6))
    _keep(read, "sketch_get", _xray("PcCtl"), "pc_ctl", _sketch_facts)
    _keep(read, "design_get", _HISTORY, "pc_history", _timeline_names)
    write("sketch_edit", {"sketch_name": "PcSketch", "component": "PcChild:1", "plane": "xz"},
          _plane_moved("pc", "PcSketch", "plane 'XZ'", "XZ"),
          ("pc_reply", _recall("pc_reply", lambda p: p["frame_after"])))
    # The component's XZ plane, carried through its placement: world y = 0 through (50, 0, 0).
    read("sketch_get", placed,
         _sketch_on("pc", "PcSketch", ((50, 0, 0), (0, 1, 0)), "XZ", origin=(50, 0, 0)))
    read("design_get", _HISTORY, _unchanged("pc_history", _timeline_names))
    read("sketch_get", _xray("PcCtl"), _unchanged("pc_ctl", _sketch_facts))
    close()
    return rows


_SKETCHWORK += _sketch_plane_placed_rows()


def _sketch_edit_refusal_rows():
    """Refuse no edit, two edits, another component's plane, and a plane move off the timeline end."""
    rows, write, read, close = _scratch_rows("rf_doc")
    write("sketch_create", {"plane": "xy", "name": "RfSk"})
    write("sketch_add_geometry", {"sketch_name": "RfSk", "geometry": [
        {"kind": "line", "x1": 0, "y1": 0, "x2": 20, "y2": 0}]})
    write("model_create_component", {"name": "RfOther", "activate": True}, _made_component)
    write("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy", "offset": 5,
                                 "name": "RfForeign"},
          lambda p: p.get("name") == "RfForeign" and p.get("component") == "RfOther")
    write("design_activate_component", {"occurrence": "root"})
    _keep(read, "sketch_get", _xray("RfSk"), "rf_sketch", _sketch_facts)
    _keep(read, "sketch_get", {}, "rf_list", _sketch_list,
          lambda p: list(_sketch_list(p)) == ["RfSk"])
    _keep(read, "design_get", _HISTORY, "rf_history", _timeline_names)

    def untouched():
        read("sketch_get", _xray("RfSk"), _unchanged("rf_sketch", _sketch_facts))

    write("sketch_edit", {"sketch_name": "RfSk"},
          _refused("Pass exactly one of new_name, visible, plane", "got none",
                   "Nothing was changed"))
    write("sketch_edit", {"sketch_name": "RfSk", "new_name": "RfTwo", "visible": False},
          _refused("Pass exactly one of new_name, visible, plane", "got new_name, visible",
                   "Nothing was changed"))
    untouched()
    read("sketch_get", {}, _unchanged("rf_list", _sketch_list))
    write("sketch_edit", {"sketch_name": "RfSk", "plane": "RfForeign"},
          _refused("'plane' resolved to plane 'RfForeign'",
                   "not read as belonging to the sketch's own component",
                   "sketch 'RfSk' was not changed"))
    untouched()
    # One step back leaves RfSk computed and the marker short of the end.
    write("design_edit_timeline", {"action": "roll", "to": "previous"},
          lambda p: p.get("rolled") is True and _num(p.get("timeline_count"))
          and p.get("marker_position") == p["timeline_count"] - 1,
          ("rf_marker", _recall("rf_marker", lambda p: [p["marker_position"],
                                                        p["timeline_count"]])))
    write("sketch_edit", {"sketch_name": "RfSk", "plane": "xz"},
          _NamedRefusal("a plane change needs it at the end",
                        "design_edit_timeline(action='roll', to='end')",
                        recalled=lambda r: ["The timeline marker is at {0} of {1}".format(
                            *r["rf_marker"])]))
    untouched()
    write("design_edit_timeline", {"action": "roll", "to": "end"},
          lambda p: p.get("rolled") is True and p.get("rolled_back") == 0
          and p.get("marker_position") == p.get("timeline_count") == _RECALL["rf_marker"][1])
    read("design_get", _HISTORY, _unchanged("rf_history", _timeline_names))
    untouched()
    close()
    return rows


_SKETCHWORK += _sketch_edit_refusal_rows()


# --- sketch_edit_curve(construction / centerline) ----------------------------------------------

def _flag_set(action, ref, before, after, profiles=None):
    """sketch_edit_curve(state): the flag either side of the write, and the profile counts."""
    def check(p):
        changed = before is not after
        return _measured(f"{ref} {action} {before} -> {after}",
                         {k: p.get(k) for k in ("requested", "state_before", "state_after",
                                                "changed", "profile_count_before",
                                                "profile_count_after")},
                         p.get("action") == action and p.get("sketch") == "CsSk"
                         and p.get("entity_one") == ref and p.get("requested") is after
                         and p.get("state_before") is before and p.get("state_after") is after
                         and p.get("changed") is changed
                         and (profiles is None or (p.get("profile_count_before"),
                                                   p.get("profile_count_after")) == profiles)
                         and ("nothing was written" in (p.get("note") or "")) is (not changed))
    return check


def _curve_rows_read(ref=None, profile_count=None):
    """sketch_get: CsSk's rows as first read, `ref` alone construction, at this profile count."""
    def check(p):
        base, now = _RECALL.get("cs_sketch") or {}, _sketch_facts(p) or {}
        want = [dict(e, construction=True) if e.get("id") == ref else e
                for e in base.get("entities") or []]
        return _measured(f"construction flag on {ref} only",
                         {"entities": now.get("entities"), "want": want,
                          "profile_count": now.get("profile_count")},
                         bool(want) and now.get("entities") == want
                         and now.get("construction_count") == int(ref is not None)
                         and (profile_count is None
                              or (now.get("profile_count") == profile_count
                                  and len(now.get("profiles") or []) == profile_count)))
    return check


def _line_centerlines(p):
    """sketch_get: each line row's centerline flag by id, None where the key is absent."""
    return {e.get("id"): e.get("centerline") for e in p.get("entities") or []
            if e.get("type") == "line"}


def _centerline_read(ref=None):
    """sketch_get: CsSk's rows as first read, `ref` alone a centerline and no line construction."""
    def check(p):
        base, now = _RECALL.get("cs_sketch") or {}, _sketch_facts(p) or {}
        want = [dict(e, centerline=True) if e.get("id") == ref else e
                for e in base.get("entities") or []]
        flags = _line_centerlines(p)
        return _measured(f"centerline flag on {ref} only",
                         {"centerline": flags, "entities": now.get("entities"), "want": want},
                         len(flags) == 4 and (ref is None or ref in flags)
                         and all(flag is (line == ref) for line, flag in flags.items())
                         and bool(want) and now.get("entities") == want
                         and now.get("construction_count") == 0)
    return check


def _curve_state_rows():
    """Set a line's construction and centerline flags both ways; refuse the calls that fit neither."""
    rows, write, read, close = _scratch_rows("cs_doc")
    for name, geometry in (("CsSk", {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 10}),
                           ("CsCircle", {"kind": "circle", "cx": 50, "cy": 5, "radius": 4}),
                           ("CsCtl", {"kind": "line", "x1": 0, "y1": 30, "x2": 20, "y2": 30})):
        write("sketch_create", {"plane": "xy", "name": name})
        write("sketch_add_geometry", {"sketch_name": name, "geometry": [geometry]})
    _keep(read, "sketch_get", _xray("CsSk"), "cs_sketch", _sketch_facts,
          lambda p: p["counts"]["lines"] == 4 and p["profile_count"] == 1
          and p["construction_count"] == 0 and len(_line_centerlines(p)) == 4
          and all(flag is False for flag in _line_centerlines(p).values()))
    _keep(read, "sketch_get", _xray("CsCircle"), "cs_circle", _sketch_facts)
    _keep(read, "sketch_get", _xray("CsCtl"), "cs_ctl", _sketch_facts)

    def state(action, ref, value):
        return {"sketch_name": "CsSk", "action": action, "entity_one": ref, "state": value}

    # A profile edge made construction stops bounding the profile, and bounds it again when solid.
    write("sketch_edit_curve", state("construction", "line:0", True),
          _flag_set("construction", "line:0", False, True, (1, 0)))
    read("sketch_get", _xray("CsSk"), _curve_rows_read("line:0", 0))
    write("sketch_edit_curve", state("construction", "line:0", True),
          _flag_set("construction", "line:0", True, True, (0, 0)))
    write("sketch_edit_curve", state("construction", "line:0", False),
          _flag_set("construction", "line:0", True, False, (0, 1)))
    read("sketch_get", _xray("CsSk"), _unchanged("cs_sketch", _sketch_facts))
    # Each line row carries its own centerline flag; the other three lines are the control.
    write("sketch_edit_curve", state("centerline", "line:1", True),
          _flag_set("centerline", "line:1", False, True))
    read("sketch_get", _xray("CsSk"), _centerline_read("line:1"))
    write("sketch_edit_curve", state("centerline", "line:1", False),
          _flag_set("centerline", "line:1", True, False))
    read("sketch_get", _xray("CsSk"), _centerline_read())
    write("sketch_edit_curve", {"sketch_name": "CsCircle", "action": "centerline",
                                "entity_one": "circle:0", "state": True},
          _refused("centerline applies to a straight LINE", "'entity_one' = 'circle:0' is a circle"))
    read("sketch_get", _xray("CsCircle"), _unchanged("cs_circle", _sketch_facts))
    write("sketch_edit_curve", {"sketch_name": "CsSk", "action": "construction",
                                "entity_one": "line:0"},
          _refused("'construction' needs 'state' (true or false)", "got None"))
    write("sketch_edit_curve", {"sketch_name": "CsSk", "action": "trim", "entity_one": "line:0",
                                "x1": 5, "y1": 0, "state": True},
          _refused("'state' applies to construction/centerline, the spline handles and close",
                   "'trim' takes none",
                   "got True"))
    read("sketch_get", _xray("CsSk"), _curve_rows_read())
    read("sketch_get", _xray("CsCtl"), _unchanged("cs_ctl", _sketch_facts))
    close()
    return rows


_SKETCHWORK += _curve_state_rows()


# --- sketch_edit_curve(break_link) -------------------------------------------------------------

_BL_KEEPS = "This tool cannot restore the link, and the curve no longer follows its source."


def _bl_edges(p):
    """find_geometry: the handles of the box's two 30 mm top edges along X, at y 0 and y 20 mm."""
    out = {}
    for key, y in (("a", 0), ("b", 20)):
        hits = [m for m in p.get("matches") or []
                if m.get("kind") == "line_edge" and _near(m.get("length"), 30, 1e-3)
                and _vec3(m.get("position")) and abs(m["position"][1] - y) < 1e-3
                and abs(m["position"][2] - 10) < 1e-3 and m.get("handle")]
        if len(hits) != 1:
            raise AssertionError(f"{len(hits)} 30 mm top edges read at y {y}: {p.get('matches')}")
        out[key] = hits[0]["handle"]
    return out


def _bl_projected(p):
    """sketch_project: one linked line landed; its '<type>:<index>' ref."""
    lines = [r for r in p.get("entity_refs") or [] if r.startswith("line:")]
    if p.get("projected") is not True or p.get("linked") is not True or len(lines) != 1:
        raise AssertionError(f"no single linked projected line: {p}")
    return lines[0]


def _bl_state(p):
    """sketch_get: BlProj's line rows by id beside its link counts, or None when the read is cut."""
    rows = [e for e in p.get("entities") or [] if e.get("type") == "line"]
    if p.get("truncated") is not False or len(rows) != (p.get("counts") or {}).get("lines"):
        return None
    return {"lines": {e.get("id"): {k: e.get(k) for k in ("reference", "linked", "start", "end",
                                                          "handle")} for e in rows},
            **{k: p.get(k) for k in ("reference_curve_count", "linked_curve_count",
                                     "is_fully_constrained", "profile_count")}}


def _bl_length(row):
    """A line row's length in mm between its two ends, or None when an end did not read."""
    ends = [(row or {}).get(k) for k in ("start", "end")]
    if not all(isinstance(e, dict) and _num(e.get("x")) and _num(e.get("y")) for e in ends):
        return None
    return sum((ends[0].get(k, 0) - ends[1].get(k, 0)) ** 2 for k in "xyz") ** 0.5


def _bl_pair(p):
    """(state, line A's row, line B's row) off a BlProj read, the rows None where absent."""
    state = _bl_state(p) or {}
    lines = state.get("lines") or {}
    return state, lines.get(_RECALL.get("bl_a")), lines.get(_RECALL.get("bl_b"))


def _bl_reads(a_mm, b_mm, broken=False):
    """sketch_get: lines A and B at these lengths, B linked, A linked unless `broken`."""
    def check(p):
        state, a, b = _bl_pair(p)
        linked = 1 if broken else 2
        return _measured(f"A {a_mm} mm {'broken' if broken else 'linked'}, B {b_mm} mm linked",
                         state,
                         a is not None and b is not None and len(state["lines"]) == 2
                         and _near(_bl_length(a), a_mm, 1e-3) and _near(_bl_length(b), b_mm, 1e-3)
                         and a["reference"] is (not broken) and a["linked"] is (not broken)
                         and b["reference"] is True and b["linked"] is True
                         and state["reference_curve_count"] == linked
                         and state["linked_curve_count"] == linked
                         and isinstance(a["handle"], str) and bool(a["handle"]))
    return check


def _bl_broke(p):
    """sketch_edit_curve(break_link): both flags true -> false on line A, its geometry unchanged."""
    before = _RECALL.get("bl_linked") or {}
    return _measured("line A's link broken, one-way",
                     {k: v for k, v in p.items() if k != "note"},
                     p.get("action") == "break_link" and p.get("sketch") == "BlProj"
                     and p.get("entity_one") == _RECALL.get("bl_a") and p.get("changed") is True
                     and (p.get("reference_before"), p.get("reference_after")) == (True, False)
                     and (p.get("linked_before"), p.get("linked_after")) == (True, False)
                     and p.get("reversible") is False and p.get("geometry_unchanged") is True
                     and _near(p.get("length"), 40, 1e-3) and p.get("units") == "mm"
                     and "fully_constrained_after" in p and "profile_count_after" in p
                     and p.get("fully_constrained_before") == before.get("is_fully_constrained")
                     and p.get("profile_count_before") == before.get("profile_count")
                     and _BL_KEEPS in (p.get("note") or ""))


def _bl_after_break(p):
    """sketch_get: A unlinked where it lay under its own handle, B as read before, per the reply."""
    state, a, b = _bl_pair(p)
    before, reply = _RECALL.get("bl_linked") or {}, _RECALL.get("bl_reply") or {}
    was_a = (before.get("lines") or {}).get(_RECALL.get("bl_a")) or {}
    was_b = (before.get("lines") or {}).get(_RECALL.get("bl_b"))
    return (_bl_reads(40, 40, broken=True)(p)
            and _measured("A's ends and handle kept, B untouched, the reply's sketch facts",
                          {"now": state, "before": before, "reply": reply},
                          _alike([a["start"], a["end"]], [was_a.get("start"), was_a.get("end")],
                                 1e-6)
                          and a["handle"] == was_a.get("handle") and b == was_b
                          and state["is_fully_constrained"] is reply.get("fully_constrained_after")
                          and state["profile_count"] == reply.get("profile_count_after")))


def _bl_handle_is_a(p):
    """model_construction(axis): the pre-break handle resolved to line A, read at its 40 mm ends."""
    rows = p.get("operands") or []
    row = rows[0] if len(rows) == 1 else {}
    ends = row.get("world") or []
    span = (sum((u - v) ** 2 for u, v in zip(*ends)) ** 0.5
            if len(ends) == 2 and all(_vec3(e) for e in ends) else None)
    return _measured("the handle read before the break names line A", rows,
                     p.get("created") is True and p.get("kind") == "axis"
                     and row.get("ref") == f"BlProj/{_RECALL.get('bl_a')}"
                     and _near(span, 40, 1e-3))


def _break_link_rows():
    """Break one of two linked projections; the other keeps following the box it was taken from."""
    rows, write, read, close = _scratch_rows("bl_doc")
    write("sketch_create", {"plane": "xy", "name": "BlBox"})
    write("sketch_add_geometry", {"sketch_name": "BlBox", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 30, "y2": 20}]})
    # The box's width along X is this one driving dimension; its parameter name is read back.
    write("sketch_dimension", {"sketch_name": "BlBox", "dimensions": [
        {"dim_type": "horizontal_distance", "entity_one": "line:0:start",
         "entity_two": "line:0:end", "value": "30 mm"},
        {"dim_type": "vertical_distance", "entity_one": "line:1:start",
         "entity_two": "line:1:end", "value": "20 mm"}]},
        _dim_measures(30.0), ("bl_w", _recall("bl_w", lambda p: p["results"][0]["parameter"])))
    write("model_extrude", {"sketch_name": "BlBox", "profile_index": 0, "distance": 10,
                            "operation": "new"},
          _extruded, ("bl_body", _recall("bl_body", lambda p: p["result_bodies"][0])))
    read("model_inspect", _solid("bl_body"), _box_reads(30, 20, 10))
    write("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy", "offset": 25,
                                 "name": "BlPlane"}, lambda p: p.get("name") == "BlPlane")
    write("sketch_create", {"plane": "BlPlane", "name": "BlProj"})
    read("find_geometry", lambda c: {"target": _ctx_get(c, "bl_body", "the box"),
                                     "kind": "line_edge", "units": "mm", "max_results": 20},
         lambda p: p.get("match_count") == p.get("returned") == 12, ("bl_edges", _bl_edges))
    for key in ("a", "b"):
        write("sketch_project", lambda c, key=key: {
            "action": "into_sketch", "sketch_name": "BlProj", "link": True,
            "entities": [_ctx_get(c, "bl_edges", "the box's top edges")[key]]},
            "ok", ("bl_" + key, _recall("bl_" + key, _bl_projected)))

    def width(mm):
        write("param_set", lambda c: {"name": _ctx_get(c, "bl_w", "the width parameter"),
                                      "expression": f"{mm} mm"}, lambda p: p.get("set") is True)

    def line(key):
        return lambda c: _ctx_get(c, key, "a projected line's ref")

    read("sketch_get", _xray("BlProj"), _bl_reads(30, 30))
    # Before the break both projections follow the box.
    width(40)
    _keep(read, "sketch_get", _xray("BlProj"), "bl_linked", _bl_state, _bl_reads(40, 40))
    write("sketch_edit_curve", lambda c: {"sketch_name": "BlProj", "action": "break_link",
                                          "entity_one": line("bl_a")(c)},
          _bl_broke, ("bl_reply", _recall("bl_reply", lambda p: {
              k: p[k] for k in ("fully_constrained_after", "profile_count_after")})))
    read("sketch_get", _xray("BlProj"), _bl_after_break)
    # An axis along line A takes the handle read before the break and names the line it resolved.
    write("model_construction", lambda c: {
        "kind": "axis", "mode": "edge", "name": "BlAxis",
        "axis": _ctx_get(c, "bl_linked", "BlProj before the break")["lines"][
            line("bl_a")(c)]["handle"]}, _bl_handle_is_a)
    # After it only line B follows the box; line A keeps the length it was broken at.
    width(50)
    _keep(read, "sketch_get", _xray("BlProj"), "bl_after", _bl_state,
          _bl_reads(40, 50, broken=True))
    read("model_inspect", _solid("bl_body"), _box_reads(50, 20, 10))
    write("sketch_edit_curve", lambda c: {"sketch_name": "BlProj", "action": "break_link",
                                          "entity_one": line("bl_b")(c), "state": True},
          _refused("break_link only breaks a link", "this tool cannot re-establish one",
                   "got True"))
    read("sketch_get", _xray("BlProj"), _unchanged("bl_after", _bl_state))
    write("sketch_edit_curve", lambda c: {"sketch_name": "BlProj", "action": "break_link",
                                          "entity_one": line("bl_a")(c)},
          lambda p: _measured("a broken line is left as it is",
                              {k: v for k, v in p.items() if k != "note"},
                              p.get("changed") is False and p.get("reference_before") is False
                              and p.get("reference_after") is False
                              and "nothing was written" in (p.get("note") or "")))
    read("sketch_get", _xray("BlProj"), _unchanged("bl_after", _bl_state))
    close()
    return rows


_SKETCHWORK += _break_link_rows()


# --- sketch_dimension(dimension, is_driving) ---------------------------------------------------

def _driving_set(key, want, before):
    """sketch_dimension(is_driving): the flag either side of the write, the parameter name kept."""
    def check(p):
        name, changed = _RECALL.get(key), before is not want
        landed = (not changed or (p.get("parameter") == name and p.get("new_timeline_errors") == []
                                  and p.get("new_timeline_warnings") == []
                                  and p.get("sketch_health") == "healthy"))
        return _measured(f"dimension '{name}' is_driving {before} -> {want}",
                         {k: p.get(k) for k in ("dimension", "requested", "is_driving_before",
                                                "is_driving", "changed", "parameter_before",
                                                "parameter", "sketch_health", "unread")},
                         bool(name) and p.get("sketch") == "DrSk" and p.get("dimension") == name
                         and p.get("requested") is want and p.get("is_driving_before") is before
                         and p.get("is_driving") is want and p.get("changed") is changed
                         and p.get("parameter_before") == name and "unread" not in p and landed
                         and ("nothing was written" in (p.get("note") or "")) is (not changed))
    return check


_DIMENSION_TOL = 1e-3      # mm; the band this story reads a dimension's value in


def _plain_quantity(expression):
    """('<number> <unit>' as (float, unit)), or None for a formula, a reference or anything else."""
    parts = expression.split() if isinstance(expression, str) else []
    if len(parts) != 2 or not parts[1].isalpha():
        return None
    try:
        number = float(parts[0])
    except ValueError:
        return None
    return (number, parts[1]) if isfinite(number) else None


def _same_quantity(now, before):
    """Whether two expressions name one number in one unit; exact text when either is not plain."""
    a, b = _plain_quantity(now), _plain_quantity(before)
    if a is None or b is None:
        return now == before
    return a[1] == b[1] and _near(a[0], b[0], _DIMENSION_TOL)


def _dimension_rows_match(now, want, toggled):
    """Dimension rows equal `want`; a row named in `toggled` may restate its plain expression."""
    if not isinstance(now, list) or len(now) != len(want):
        return False
    for got, row in zip(now, want):
        if not isinstance(got, dict) or got.get("name") not in toggled:
            if got != row:
                return False
            continue
        rest = [k for k in row if k not in ("expression", "value")]
        if (got.keys() != row.keys() or any(got[k] != row[k] for k in rest)
                or not _near(got.get("value"), row.get("value"), _DIMENSION_TOL)
                or not _same_quantity(got.get("expression"), row.get("expression"))):
            return False
    return True


def _driving_read(toggled=(), **driven):
    """sketch_get: DrSk as first read, except the driving flag of the dimensions keyed here."""
    def check(p):
        base, now = _RECALL.get("dr_sketch") or {}, _sketch_facts(p) or {}
        flags = {_RECALL.get(key): value for key, value in driven.items()}
        want = [dict(d, driving=flags.get(d.get("name"), d.get("driving")))
                for d in base.get("dimensions") or []]
        restated = {_RECALL.get(key) for key in toggled}
        return _measured("driving flag per dimension name",
                         {"dimensions": now.get("dimensions"), "want": want,
                          "toggled": sorted(str(n) for n in restated)},
                         len(want) == 2 and None not in flags and None not in restated
                         and _dimension_rows_match(now.get("dimensions"), want, restated)
                         and now.get("driving_dimension_count") == sum(d["driving"] for d in want)
                         and all(now.get(k) == base.get(k) for k in (
                             "entities", "profiles", "profile_count", "counts", "frame",
                             "constraints")))
    return check


def _param_row(p):
    """param_get(name): the parameter's name, expression and value, or None when unread."""
    row = p.get("parameter") or {}
    if not row.get("name") or not _num(row.get("value")):
        return None
    return {k: row.get(k) for k in ("name", "expression", "value", "value_units")}


def _dimension_driving_rows():
    """Make a height and a width dimension driven and driving again under a dependent extrude."""
    rows, write, read, close = _scratch_rows("dr_doc")
    write("sketch_create", {"plane": "xy", "name": "DrSk"})
    write("sketch_add_geometry", {"sketch_name": "DrSk", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 30, "y2": 10}]})
    for key, kind, line, value in (("dr_w", "horizontal_distance", "line:0", 30),
                                   ("dr_h", "vertical_distance", "line:1", 10)):
        write("sketch_dimension", {"sketch_name": "DrSk", "dimensions": [
            {"dim_type": kind, "entity_one": line + ":start", "entity_two": line + ":end",
             "value": f"{value} mm"}]},
            _dim_measures(float(value)),
            (key, _recall(key, lambda p: p["results"][0]["parameter"])))
    # The extrude's depth is an expression over the width dimension's own parameter.
    write("model_extrude", lambda c: {
        "sketch_name": "DrSk", "profile_index": 0, "operation": "new",
        "distance": _ctx_get(c, "dr_w", "the width dimension's parameter") + " / 3"},
        _extruded, ("dr_made", _recall("dr_made", lambda p: {
            "body": p["result_bodies"][0], "depth": p["model_parameters"]["distance"]})))
    write("sketch_create", {"plane": "xy", "name": "DrOther"})
    write("sketch_add_geometry", {"sketch_name": "DrOther", "geometry": [
        {"kind": "line", "x1": 60, "y1": 0, "x2": 80, "y2": 0}]})
    write("sketch_dimension", {"sketch_name": "DrOther", "dimensions": [
        {"dim_type": "distance", "entity_one": "line:0", "value": "20 mm"}]},
        _dim_measures(20.0), ("dr_foreign", _recall("dr_foreign",
                                                   lambda p: p["results"][0]["parameter"])))

    def depth(c):
        return {"name": _ctx_get(c, "dr_made", "the extrude's names")["depth"]}

    def body(c):
        return _inspect(_ctx_get(c, "dr_made", "the extrude's names")["body"])

    def fresh(p):
        dims = {d.get("name"): d for d in p.get("dimensions") or []}
        wide, high = dims.get(_RECALL.get("dr_w")) or {}, dims.get(_RECALL.get("dr_h")) or {}
        return (len(dims) == 2 and _near(wide.get("value"), 30, 1e-3)
                and _near(high.get("value"), 10, 1e-3) and wide.get("driving") is True
                and high.get("driving") is True and p.get("driving_dimension_count") == 2
                and p.get("profile_count") == 1)

    _keep(read, "sketch_get", _xray("DrSk"), "dr_sketch", _sketch_facts, fresh)
    _keep(read, "param_get", depth, "dr_depth", _param_row,
          lambda p: _near(p["parameter"]["value"], 10, 1e-6)
          and p["parameter"].get("value_units") == "mm"
          and _RECALL["dr_w"] in p["parameter"]["expression"])
    _keep(read, "model_inspect", body, "dr_solid", _body_facts, _box_reads(30, 10, 10))
    _keep(read, "sketch_get", _xray("DrOther"), "dr_other", _sketch_facts,
          lambda p: [d.get("name") for d in p["dimensions"]] == [_RECALL["dr_foreign"]])

    toggled = []

    def drive(key, want, **driven):
        write("sketch_dimension", lambda c: {
            "sketch_name": "DrSk", "is_driving": want,
            "dimension": _ctx_get(c, key, "the dimension's parameter name")},
            _driving_set(key, want, not want))
        # A dimension made driven restates its expression ("10 mm" reads "10.00 mm").
        if key not in toggled:
            toggled.append(key)
        read("sketch_get", _xray("DrSk"), _driving_read(tuple(toggled), **driven))
        read("param_get", depth, _unchanged("dr_depth", _param_row, 1e-6))
        read("model_inspect", body, _unchanged("dr_solid", _body_facts, 1e-3))
        read("sketch_get", _xray("DrOther"), _unchanged("dr_other", _sketch_facts))

    drive("dr_h", False, dr_h=False)
    drive("dr_h", True)
    drive("dr_w", False, dr_w=False)
    drive("dr_w", True)
    write("sketch_dimension", lambda c: {
        "sketch_name": "DrSk", "is_driving": True,
        "dimension": _ctx_get(c, "dr_h", "the height dimension's parameter")},
        _driving_set("dr_h", True, True))
    # A parameter another sketch's dimension owns is refused naming that sketch.
    write("sketch_dimension", lambda c: {
        "sketch_name": "DrSk", "is_driving": False,
        "dimension": _ctx_get(c, "dr_foreign", "DrOther's dimension parameter")},
        _NamedRefusal("names no dimension of sketch 'DrSk'",
                      "that parameter was created by sketch 'DrOther'", "sketch_name='DrOther'",
                      recalled=lambda r: [f"'dimension' = '{r['dr_foreign']}'"]))
    read("sketch_get", _xray("DrSk"), _driving_read(tuple(toggled)))
    read("sketch_get", _xray("DrOther"), _unchanged("dr_other", _sketch_facts))
    close()
    return rows


_SKETCHWORK += _dimension_driving_rows()


def _one_profile(area_mm2, centroid=None, tol=0.02):
    """sketch_get: exactly one profile, of this area and, when given, this (x, y) centroid in mm."""
    def check(p):
        rows = p.get("profiles") or []
        at = (rows[0].get("centroid") or [None, None]) if rows else [None, None]
        return _measured(f"one profile of {area_mm2:.3f} mm2", rows,
                         p.get("truncated") is False and p.get("profile_count") == 1
                         and len(rows) == 1 and _near(rows[0].get("area"), area_mm2, tol)
                         and (centroid is None or (_near(at[0], centroid[0], tol)
                                                   and _near(at[1], centroid[1], tol))))
    return check


def _round_row(ref, cx, cy, radius):
    """sketch_get: the arc or circle `ref` reads this centre and radius in mm."""
    def check(p):
        row = _rows_by_id(p).get(ref) or {}
        centre = row.get("center") or {}
        return _measured(f"{ref} centre and radius", row,
                         _near(centre.get("x"), cx, 0.001) and _near(centre.get("y"), cy, 0.001)
                         and _near(row.get("radius"), radius, 0.001) and "z" not in centre)
    return check


def _line_corners(count, corners):
    """sketch_get: `count` lines whose ends are exactly these (x, y) corners in mm, no constraint."""
    def check(p):
        lines = [r for r in p.get("entities") or [] if r.get("type") == "line"]
        ends = [(r.get(end) or {}) for r in lines for end in ("start", "end")]
        hit = [sum(1 for e in ends if _near(e.get("x"), x, 0.01) and _near(e.get("y"), y, 0.01))
               for x, y in corners]
        return _measured(f"{count} lines on {len(corners)} corners", [r.get("id") for r in lines],
                         p.get("truncated") is False and len(lines) == count
                         and len(ends) == 2 * len(corners) and all(n == 2 for n in hit))
    return check


def _drawn(kind, **facts):
    """sketch_add_geometry: the one result row of this kind carrying these as-built facts."""
    def check(p):
        row = (p.get("results") or [{}])[0]
        return _measured(f"{kind} as built", row,
                         p.get("drawn") == 1 and row.get("kind") == kind
                         and all(_alike(row.get(key), want, 0.001) for key, want in facts.items()))
    return check


def _exact_curve_rows():
    """Arcs, circles, a rectangle and polygons drawn from points, each judged on the public read."""
    from math import asin, pi, sin, sqrt
    rows, write, read, close = _scratch_rows("xc_doc")

    def sketch(name, *geometry_and_checks):
        write("sketch_create", {"plane": "xy", "name": name})
        for geometry, check in geometry_and_checks:
            write("sketch_add_geometry", {"sketch_name": name, "geometry": [geometry]}, check)

    # A clockwise three-point arc is stored counter-clockwise; its chord closes ONE region, and that
    # region's area says which side of the chord the arc bulges to.
    theta = 2 * asin(10 / 12.5)
    sketch("XcArc3",
           ({"kind": "three_point_arc", "points": [[0, 0], [10, 5], [20, 0]]},
            _drawn("three_point_arc", start=[20.0, 0.0], end=[0.0, 0.0], center=[10.0, -7.5],
                   radius=12.5, ends_exchanged=True, curves_added=1)),
           ({"kind": "line", "x1": 0, "y1": 0, "x2": 20, "y2": 0}, "ok"))
    read("sketch_get", _xray("XcArc3"), _round_row("arc:0", 10, -7.5, 12.5))
    read("sketch_get", _xray("XcArc3"), _one_profile(12.5 ** 2 / 2 * (theta - sin(theta))))
    # A centre arc runs counter-clockwise from its start: the quarter disc, not the other three.
    sketch("XcArcC",
           ({"kind": "center_arc", "cx": 0, "cy": 0, "x1": 10, "y1": 0, "x2": 0, "y2": 10},
            _drawn("center_arc", start=[10.0, 0.0], end=[0.0, 10.0], center=[0.0, 0.0],
                   radius=10.0)),
           ({"kind": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0}, "ok"),
           ({"kind": "line", "x1": 0, "y1": 0, "x2": 0, "y2": 10}, "ok"))
    quarter = 40 / (3 * pi)
    read("sketch_get", _xray("XcArcC"), _one_profile(25 * pi, (quarter, quarter)))
    sketch("XcCircle",
           ({"kind": "two_point_circle", "x1": 0, "y1": 0, "x2": 20, "y2": 0},
            _drawn("two_point_circle", center=[10.0, 0.0], radius=10.0)),
           ({"kind": "three_point_circle", "points": [[40, 0], [50, 10], [60, 0]]},
            _drawn("three_point_circle", center=[50.0, 0.0], radius=10.0)))
    read("sketch_get", _xray("XcCircle"), _round_row("circle:0", 10, 0, 10))
    read("sketch_get", _xray("XcCircle"), _round_row("circle:1", 50, 0, 10))
    sketch("XcRect",
           ({"kind": "three_point_rectangle", "points": [[0, 0], [30, 0], [10, 20]]},
            lambda p: p["results"][0].get("curves_added") == 4
            and p["results"][0].get("constraints_added") == 0))
    read("sketch_get", _xray("XcRect"),
         _line_corners(4, [(0, 0), (30, 0), (30, 20), (0, 20)]))
    read("sketch_get", _xray("XcRect"),
         lambda p: _one_profile(600.0, (15, 10))(p) and p.get("constraint_count") == 0)
    # An edge polygon lies to the RIGHT of its first edge: below an edge drawn towards +X.
    sketch("XcEdge",
           ({"kind": "edge_polygon", "x1": 0, "y1": 0, "x2": 10, "y2": 0, "sides": 6},
            lambda p: p["results"][0].get("curves_added") == 6))
    read("sketch_get", _xray("XcEdge"), _one_profile(150 * sqrt(3), (5, -5 * sqrt(3))))
    # A circumscribed radius is centre to EDGE; angle_deg directs its outward edge normal.
    sketch("XcCircum",
           ({"kind": "circumscribed_polygon", "cx": 50, "cy": 0, "radius": 10, "sides": 4,
             "angle_deg": 45},
            lambda p: p["results"][0].get("curves_added") == 4))
    read("sketch_get", _xray("XcCircum"),
         _line_corners(4, [(50, 10 * sqrt(2)), (50 - 10 * sqrt(2), 0),
                          (50, -10 * sqrt(2)), (50 + 10 * sqrt(2), 0)]))
    read("sketch_get", _xray("XcCircum"), _one_profile(400.0, (50, 0)))

    write("sketch_create", {"plane": "xy", "name": "XcRefuse"})
    for geometry, said in (
            ({"kind": "three_point_arc", "points": [[0, 0], [5, 5], [10, 10]]},
             ("three points that are not in a line", "collinear")),
            ({"kind": "three_point_circle", "points": [[0, 0], [5, 5], [0, 0]]},
             ("three distinct points", "coincide")),
            ({"kind": "center_arc", "cx": 0, "cy": 0, "x1": 10, "y1": 0, "x2": 0, "y2": 12},
             ("start is 10 from the centre and end is 12",)),
            ({"kind": "two_point_circle", "x1": 3, "y1": 4, "x2": 3, "y2": 4},
             ("two distinct points",)),
            ({"kind": "edge_polygon", "x1": 0, "y1": 0, "x2": 10, "y2": 0, "sides": 2},
             ("sides >= 3",))):
        write("sketch_add_geometry", {"sketch_name": "XcRefuse", "geometry": [geometry]},
              _refused(*said))
    read("sketch_get", _xray("XcRefuse"),
         lambda p: p.get("truncated") is False and p.get("profile_count") == 0
         and all(p["counts"].get(kind) == 0 for kind in ("lines", "arcs", "circles")))
    close()
    return rows


_SKETCHWORK += _exact_curve_rows()


def _line_ends(ref, a, b):
    """sketch_get: line `ref` runs between these two (x, y) mm points, in either order, in plane."""
    def check(p):
        row = _rows_by_id(p).get(ref) or {}
        ends = [row.get("start") or {}, row.get("end") or {}]
        got = sorted((e.get("x"), e.get("y")) for e in ends if _num(e.get("x")) and _num(e.get("y")))
        return _measured(f"{ref} end points", row,
                         len(got) == 2 and all("z" not in e for e in ends)
                         and all(_near(g[0], w[0], 0.01) and _near(g[1], w[1], 0.01)
                                 for g, w in zip(got, sorted([a, b]))))
    return check


def _mirror_rows():
    """Mirror a line and an arc about a line; the images are read, then follow a moved source."""
    from math import asin, sin
    rows, write, read, close = _scratch_rows("mr_doc")
    write("sketch_create", {"plane": "xy", "name": "MrSk"})
    write("sketch_add_geometry", {"sketch_name": "MrSk", "geometry": [
        {"kind": "line", "x1": 10, "y1": 0, "x2": 30, "y2": 10},
        {"kind": "line", "x1": 0, "y1": -20, "x2": 0, "y2": 40},
        {"kind": "three_point_arc", "points": [[10, 20], [20, 25], [30, 20]]}]})
    write("sketch_copy", {"sketch_name": "MrSk", "entities": "line:0,arc:0", "mirror_line": "line:1",
                          "dx": 5}, _refused("Drop: dx."))
    write("sketch_copy", {"sketch_name": "MrSk", "entities": "circle:0", "mirror_line": "line:1"},
          _refused("Could not resolve 'circle:0'"))
    write("sketch_copy", {"sketch_name": "MrSk", "entities": "ellipse:0", "mirror_line": "line:1"},
          _refused("mirrors lines, arcs and circles", "ellipse:0 is none of them"))
    write("sketch_copy", {"sketch_name": "MrSk", "entities": "line:0,line:1",
                          "mirror_line": "line:1"}, _refused("also in 'entities'"))
    read("sketch_get", _xray("MrSk"),
         lambda p: p["counts"]["lines"] == 2 and p["counts"]["arcs"] == 1
         and p.get("constraint_count") == 0)
    write("sketch_copy", {"sketch_name": "MrSk", "entities": "line:0,arc:0", "mirror_line": "line:1"},
          lambda p: p.get("mirrored") is True and p.get("new_curves") == ["line:2", "arc:1"]
          and (p.get("curve_count_before"), p.get("curve_count_after")) == (3, 5)
          and p.get("constraints_added", 0) > 0)
    read("sketch_get", _xray("MrSk"), _line_ends("line:2", (-10, 0), (-30, 10)))
    read("sketch_get", _xray("MrSk"), _line_ends("line:0", (10, 0), (30, 10)))
    read("sketch_get", _xray("MrSk"), _round_row("arc:1", -20, 12.5, 12.5))
    read("sketch_get", _xray("MrSk"),
         lambda p: any(c.get("type") == "symmetry" for c in p.get("constraints") or []))
    # A chord under the mirrored arc closes one region: the minor segment, bulging up as its source.
    write("sketch_add_geometry", {"sketch_name": "MrSk", "geometry": [
        {"kind": "line", "x1": -30, "y1": 20, "x2": -10, "y2": 20}]})
    theta = 2 * asin(10 / 12.5)
    read("sketch_get", _xray("MrSk"), _one_profile(12.5 ** 2 / 2 * (theta - sin(theta))))
    read("sketch_get", _xray("MrSk"),
         lambda p: p["profiles"][0]["centroid"][0] < -10 and p["profiles"][0]["centroid"][1] > 20)
    # The image follows its source through the symmetry constraints.
    write("sketch_move", {"sketch_name": "MrSk", "entities": "line:0", "dy": 5},
          lambda p: p.get("moved_entities") == ["line:0"]
          and "line:2" in (p.get("followed_entities") or []))
    read("sketch_get", _xray("MrSk"), _line_ends("line:0", (10, 5), (30, 15)))
    read("sketch_get", _xray("MrSk"), _line_ends("line:2", (-10, 5), (-30, 15)))
    # A circle mirrors too: reflected centre, same radius, the source left alone, one curve added.
    write("sketch_add_geometry", {"sketch_name": "MrSk", "geometry": [
        {"kind": "circle", "cx": 20, "cy": -10, "radius": 5}]})
    write("sketch_copy", {"sketch_name": "MrSk", "entities": "circle:0", "mirror_line": "line:1"},
          lambda p: p.get("mirrored") is True and p.get("new_curves") == ["circle:1"]
          and p.get("curve_count_after") == p.get("curve_count_before") + 1
          and p.get("constraints_added", 0) > 0)
    read("sketch_get", _xray("MrSk"), _round_row("circle:1", -20, -10, 5))
    read("sketch_get", _xray("MrSk"), _round_row("circle:0", 20, -10, 5))
    write("sketch_move", {"sketch_name": "MrSk", "entities": "circle:0", "dy": 5},
          lambda p: p.get("moved_entities") == ["circle:0"]
          and "circle:1" in (p.get("followed_entities") or []))
    read("sketch_get", _xray("MrSk"), _round_row("circle:1", -20, -5, 5))
    read("sketch_get", _xray("MrSk"), _round_row("circle:0", 20, -5, 5))
    close()
    return rows


_SKETCHWORK += _mirror_rows()


def _through(ref, x, y, wanted):
    """sketch_get: whether line `ref`, extended, passes through (x, y) mm - `wanted` says which."""
    def check(p):
        row = _rows_by_id(p).get(ref) or {}
        a, b = row.get("start") or {}, row.get("end") or {}
        if not all(_num(v) for v in (a.get("x"), a.get("y"), b.get("x"), b.get("y"))):
            return _measured(f"{ref} readable", row, False)
        length = ((b["x"] - a["x"]) ** 2 + (b["y"] - a["y"]) ** 2) ** 0.5
        off = abs((b["x"] - a["x"]) * (y - a["y"]) - (b["y"] - a["y"]) * (x - a["x"])) / length
        return _measured(f"{ref} {'through' if wanted else 'clear of'} ({x}, {y})", off,
                         (off < 0.001) is wanted and (wanted or off > 1.0))
    return check


def _perpendicular_to_curve_rows():
    """A line made perpendicular to ONE arc: it passes through that arc's centre, not the other's."""
    rows, write, read, close = _scratch_rows("pc_doc")
    write("sketch_create", {"plane": "xy", "name": "PcSk"})
    write("sketch_add_geometry", {"sketch_name": "PcSk", "geometry": [
        {"kind": "center_arc", "cx": 0, "cy": 0, "x1": 20, "y1": 0, "x2": 0, "y2": 20},
        {"kind": "center_arc", "cx": 60, "cy": 0, "x1": 80, "y1": 0, "x2": 60, "y2": 20},
        {"kind": "line", "x1": 30, "y1": 30, "x2": 50, "y2": 45},
        {"kind": "line", "x1": 0, "y1": 60, "x2": 40, "y2": 60}]})
    read("sketch_get", _xray("PcSk"), _through("line:0", 0, 0, False))
    read("sketch_get", _xray("PcSk"), _through("line:0", 60, 0, False))

    def constrain(one, two, check):
        write("sketch_constrain", {"sketch_name": "PcSk", "constraints": [
            {"constraint": "perpendicular_to_curve", "entity_one": one, "entity_two": two}]}, check)
    constrain("arc:0", "line:0", _refused("needs a LINE as entity_one", "'arc:0'"))
    constrain("line:0", "line:1", _refused("needs an ARC or CIRCLE as entity_two",
                                           "Two lines take constraint=perpendicular"))
    read("sketch_get", _xray("PcSk"), lambda p: p.get("constraint_count") == 0)
    constrain("line:0", "arc:0",
              lambda p: p["results"][0].get("applied") == "perpendicular_to_curve"
              and "line only" in p["results"][0].get("note", ""))
    read("sketch_get", _xray("PcSk"), _through("line:0", 0, 0, True))
    read("sketch_get", _xray("PcSk"), _through("line:0", 60, 0, False))
    read("sketch_get", _xray("PcSk"), _round_row("arc:0", 0, 0, 20))
    read("sketch_get", _xray("PcSk"),
         lambda p: _round_row("arc:1", 60, 0, 20)(p) and p.get("constraint_count") == 1)
    close()
    return rows


_SKETCHWORK += _perpendicular_to_curve_rows()


def _offset_topology_rows():
    """An offset that swallows a fillet is refused while topology is matched, and built without."""
    rows, write, read, close = _scratch_rows("ot_doc")
    write("sketch_create", {"plane": "xy", "name": "OtSk"})
    write("sketch_add_geometry", {"sketch_name": "OtSk", "geometry": [
        {"kind": "line", "x1": 0, "y1": 0, "x2": 40, "y2": 0},
        {"kind": "line", "x1": 40, "y1": 0, "x2": 40, "y2": 30}]})
    write("sketch_edit_curve", {"sketch_name": "OtSk", "action": "fillet", "entity_one": "line:0",
                                "entity_two": "line:1", "x1": 35, "y1": 0, "x2": 40, "y2": 5,
                                "radius": 3}, lambda p: _near(p.get("radius"), 3, .001))
    counted = lambda lines, arcs: (lambda p: p.get("truncated") is False
                                   and p["counts"]["lines"] == lines
                                   and p["counts"]["arcs"] == arcs)
    read("sketch_get", _xray("OtSk"), counted(2, 1))

    def offset(check, **extra):
        write("sketch_constrain", {"sketch_name": "OtSk", "constraints": [
            {"constraint": "offset", "entities": "line:0,arc:0,line:1", "distance": -5, **extra}]},
            check)
    offset(_refused("topology of the offset curves does not match", "Pass match_topology=false"))
    read("sketch_get", _xray("OtSk"), counted(2, 1))
    write("sketch_constrain", {"sketch_name": "OtSk", "constraints": [
        {"constraint": "parallel", "entity_one": "line:0", "entity_two": "line:1",
         "match_topology": False}]}, _refused("match_topology applies to constraint=offset only"))
    offset(lambda p: p["results"][0].get("match_topology") is False
           and p["results"][0].get("created_count") == 2, match_topology=False)
    read("sketch_get", _xray("OtSk"), counted(4, 1))
    close()
    return rows


_SKETCHWORK += _offset_topology_rows()


def _edge_at(length, y, z):
    """A save slot's extractor: the handle of the one straight edge of this length on this y and z."""
    def pick(p):
        hits = [m for m in p.get("matches") or []
                if m.get("kind") == "line_edge" and _near(m.get("length"), length, 1e-3)
                and _vec3(m.get("position")) and _near(m["position"][1], y, 1e-4)
                and _near(m["position"][2], z, 1e-4) and m.get("handle")]
        if len(hits) != 1:
            raise AssertionError(f"no single {length} mm edge at y {y}, z {z}: "
                                 f"{[(m.get('length'), m.get('position')) for m in p.get('matches') or []]}")
        return hits[0]["handle"]
    return pick


def _reference_lines(count, z=None):
    """sketch_get: `count` lines, every one linked reference geometry, at sketch height `z` mm."""
    def check(p):
        lines = [r for r in p.get("entities") or [] if r.get("type") == "line"]
        heights = [(r.get(end) or {}).get("z", 0.0) for r in lines for end in ("start", "end")]
        return _measured(f"{count} reference lines at z {z}", lines,
                         p.get("truncated") is False and len(lines) == count
                         and all(r.get("reference") is True for r in lines)
                         and (z is None or all(_near(h, z, 0.001) for h in heights)))
    return check


def _include_and_cut_rows():
    """Include an edge where it is, off the sketch plane; cut a body with a sketch plane."""
    rows, write, read, close = _scratch_rows("ic_doc")
    _boxed(write, "IcBase", (0, 0, 20, 10), 8, "ic_body")
    read("find_geometry", lambda c: {"target": _ctx_get(c, "ic_body", "the box"),
                                     "kind": "line_edge", "max_results": 50},
         lambda p: p.get("truncated") is not True,
         ("ic_edge", _recall("ic_edge", _edge_at(20, 0, 8))))
    write("sketch_create", {"plane": "xy", "name": "IcSk"})
    write("sketch_project", lambda c: {"action": "include", "sketch_name": "IcSk",
                                       "entities": [_ctx_get(c, "ic_edge", "the top edge")],
                                       "bodies": [_ctx_get(c, "ic_body", "the box")]},
          _refused("'bodies' applies only to"))
    write("sketch_project", lambda c: {"action": "include", "sketch_name": "IcSk",
                                       "entities": [_ctx_get(c, "ic_edge", "the top edge")]},
          lambda p: p.get("action") == "include" and p.get("created_count", 0) >= 1
          and p.get("off_plane_count") == 1
          and p.get("entity_refs") == ["line:0", "point:1", "point:2"]
          and "not flattened" in p.get("note", ""))
    # The included line sits at the edge's own height, 8 mm above the XY sketch plane.
    read("sketch_get", _xray("IcSk"), _reference_lines(1, 8.0))
    read("sketch_get", _xray("IcSk"),
         lambda p: _rows_by_id(p)["line:0"].get("linked") is True and p.get("profile_count") == 0)
    for name, offset in (("IcMid", 4), ("IcHigh", 20)):
        write("model_construction", {"kind": "plane", "plane": "xy", "offset": offset, "name": name})
        write("sketch_create", {"plane": name, "name": name + "Sk"})

    def cut(sketch, check):
        write("sketch_project", lambda c: {"action": "cut_edges", "sketch_name": sketch,
                                           "bodies": [_ctx_get(c, "ic_body", "the box")]}, check)
    cut("IcHighSk", _refused("cuts none of"))
    read("sketch_get", _xray("IcHighSk"), _reference_lines(0))
    cut("IcMidSk", lambda p: p.get("action") == "cut_edges" and p.get("created_count") == 4
        and p["per_source"][0].get("created") == 4)
    read("sketch_get", _xray("IcMidSk"), _reference_lines(4, 0.0))
    read("sketch_get", _xray("IcMidSk"), _one_profile(200.0))
    close()
    return rows


_SKETCHWORK += _include_and_cut_rows()


def _spline_row(fit_points, closed):
    """sketch_get: spline:0 with this many fit points and this closed state."""
    def check(p):
        row = _rows_by_id(p).get("spline:0") or {}
        return _measured(f"spline:0 {fit_points} fit points, closed {closed}", row,
                         p.get("truncated") is False and row.get("fit_point_count") == fit_points
                         and row.get("is_closed") is closed)
    return check


def _point_rows(p):
    """sketch_get: {point id: (x, y)} for every point row."""
    return {r["id"]: ((r.get("position") or {}).get("x"), (r.get("position") or {}).get("y"))
            for r in p.get("entities") or [] if r.get("type") == "point"}


def _spline_edit_rows():
    """Add a fit point, raise and drive a tangent handle, add a curvature handle, close and reopen."""
    rows, write, read, close = _scratch_rows("sp_doc")
    write("sketch_create", {"plane": "xy", "name": "SpSk"})
    write("sketch_add_geometry", {"sketch_name": "SpSk", "geometry": [
        {"kind": "spline", "points": [[0, 0], [10, 10], [20, 0], [30, 10]]},
        {"kind": "line", "x1": 0, "y1": 40, "x2": 30, "y2": 40}]})

    def edit(check, save=None, **args):
        write("sketch_edit_curve", {"sketch_name": "SpSk", "entity_one": "spline:0", **args},
              check, save)
    read("sketch_get", _xray("SpSk"), _spline_row(4, False))
    write("sketch_edit_curve", {"sketch_name": "SpSk", "entity_one": "line:0",
                                "action": "add_point", "x1": 15, "y1": 40},
          _refused("applies to a fitted spline", "'line:0' is a line"))
    edit(_refused("action='tangent_handle' with state=false"),
         action="curvature_handle", x1=10, y1=10, state=False)
    # The spline is point-symmetric about (15, 5), so it passes through that point.
    edit(lambda p: (p.get("fit_point_count_before"), p.get("fit_point_count_after")) == (4, 5)
         and _alike(p.get("point"), [15.0, 5.0], 0.01), action="add_point", x1=15, y1=5)
    read("sketch_get", _xray("SpSk"), _spline_row(5, False))
    _keep(read, "sketch_get", _xray("SpSk"), "sp_points", _point_rows,
          lambda p: any(_near(x, 15, 0.01) and _near(y, 5, 0.01)
                        for x, y in _point_rows(p).values()))
    edit(lambda p: p.get("changed") is True and p.get("fit_point_index") == 1
         and _alike(p.get("fit_point"), [10.0, 10.0], 0.001)
         and len(p.get("handle_points") or []) == 2 and p.get("curve_changed") is True,
         ("sp_handle", _recall("sp_handle", lambda p: p["handle_points"])),
         action="tangent_handle", x1=10, y1=10)
    # The handle's two end points are new point rows; sketch_get lists no line for the handle.
    read("sketch_get", _xray("SpSk"),
         lambda p: set(_RECALL["sp_handle"]) <= set(_point_rows(p))
         and not set(_RECALL["sp_handle"]) & set(_RECALL["sp_points"])
         and p["counts"]["lines"] == 1,
         ("sp_handle_at", _recall("sp_handle_at", lambda p: _point_rows(p)[_RECALL["sp_handle"][1]])))
    write("sketch_move", lambda c: {"sketch_name": "SpSk", "dx": 3, "dy": 3,
                                    "entities": _ctx_get(c, "sp_handle", "the handle ends")[1]},
          lambda p: bool(p.get("moved_entities")))
    read("sketch_get", _xray("SpSk"),
         lambda p: not _alike(list(_point_rows(p)[_RECALL["sp_handle"][1]]),
                              list(_RECALL["sp_handle_at"]), 0.5)
         and _spline_row(5, False)(p))
    edit(lambda p: p.get("changed") is False, action="tangent_handle", x1=10, y1=10)
    edit(lambda p: p.get("changed") is True and p.get("fit_point_index") == 3,
         action="curvature_handle", x1=20, y1=0)
    edit(lambda p: p.get("changed") is True, action="tangent_handle", x1=10, y1=10, state=False)
    # The tangent handle's two points are gone; the curvature handle at fit point 3 keeps its five.
    read("sketch_get", _xray("SpSk"),
         lambda p: len(_point_rows(p)) == len(_RECALL["sp_points"]) + 5 and _spline_row(5, False)(p))
    edit(lambda p: p.get("closed") is True and p.get("changed") is True, action="close", state=True)
    read("sketch_get", _xray("SpSk"), _spline_row(5, True))
    edit(lambda p: p.get("closed") is False, action="close", state=False)
    read("sketch_get", _xray("SpSk"), _spline_row(5, False))
    close()
    return rows


_SKETCHWORK += _spline_edit_rows()


def _line_height(ref, z):
    """sketch_get: both ends of line `ref` sit `z` mm off the sketch plane (0 = in it)."""
    def check(p):
        row = _rows_by_id(p).get(ref) or {}
        heights = [(row.get(end) or {}).get("z", 0.0) for end in ("start", "end")]
        return _measured(f"{ref} at sketch height {z}", row,
                         bool(row) and all(_near(h, z, 0.001) for h in heights))
    return check


def _point_at(x, y):
    """A save slot's extractor: the id of the one non-origin point row at (x, y) mm."""
    def pick(p):
        hits = [r["id"] for r in p.get("entities") or []
                if r.get("type") == "point" and not r.get("origin")
                and _near((r.get("position") or {}).get("x"), x, 0.001)
                and _near((r.get("position") or {}).get("y"), y, 0.001)]
        if len(hits) != 1:
            raise AssertionError(f"no single point at ({x}, {y}): {hits}")
        return hits[0]
    return pick


def _off_plane_rows():
    """Lift a line off its sketch plane; lift one corner of a loop and watch its profile go and return."""
    rows, write, read, close = _scratch_rows("dz_doc")
    write("sketch_create", {"plane": "xy", "name": "DzSk"})
    write("sketch_add_geometry", {"sketch_name": "DzSk", "geometry": [
        {"kind": "three_point_rectangle", "points": [[0, 0], [20, 0], [20, 20]]},
        {"kind": "line", "x1": 50, "y1": 0, "x2": 70, "y2": 0}]})
    read("sketch_get", _xray("DzSk"), _one_profile(400.0, (10, 10)),
         ("dz_corner", _recall("dz_corner", _point_at(20, 20))))

    def lifted(before, after):
        return lambda p: (p.get("profile_count_before"), p.get("profile_count_after")) == (
            before, after) and bool(p.get("moved_entities")) and "on_plane_entities" not in p
    write("sketch_move", {"sketch_name": "DzSk", "entities": "line:4", "dz": 5},
          lambda p: lifted(1, 1)(p) and p["requested"].get("dz") == 5.0)
    read("sketch_get", _xray("DzSk"), _line_height("line:4", 5.0))
    read("sketch_get", _xray("DzSk"), _one_profile(400.0, (10, 10)))

    def corner(dz, check):
        write("sketch_move", lambda c: {"sketch_name": "DzSk", "dz": dz,
                                        "entities": _ctx_get(c, "dz_corner", "the corner point")},
              check)
    corner(5, lambda p: lifted(1, 0)(p) and "from 1 to 0 profile(s)" in p.get("note", ""))
    read("sketch_get", _xray("DzSk"),
         lambda p: p.get("truncated") is False and p.get("profile_count") == 0
         and _near((_rows_by_id(p)[_RECALL["dz_corner"]].get("position") or {}).get("z"), 5, .001))
    corner(-5, lambda p: (p.get("profile_count_before"), p.get("profile_count_after")) == (0, 1)
           and p.get("moved_entities") == [_RECALL["dz_corner"]]
           and p.get("returned_to_plane") == [_RECALL["dz_corner"]]
           and "on_plane_entities" not in p and "still read z = 0" not in p.get("note", ""))
    read("sketch_get", _xray("DzSk"), _one_profile(400.0, (10, 10)))
    write("sketch_copy", {"sketch_name": "DzSk", "entities": "line:4", "dz": 10},
          lambda p: p.get("new_curves") == ["line:5"] and p["requested"].get("dz") == 10.0)
    read("sketch_get", _xray("DzSk"), _line_height("line:5", 15.0))
    read("sketch_get", _xray("DzSk"), _line_height("line:4", 5.0))
    close()
    return rows


_SKETCHWORK += _off_plane_rows()


def _constrained_lift_rows():
    """Lift one corner of a CONSTRAINED rectangle: the whole loop follows and keeps its profile."""
    rows, write, read, close = _scratch_rows("cl_doc")
    sides = ["line:0", "line:1", "line:2", "line:3"]
    write("sketch_create", {"plane": "xy", "name": "ClSk"})
    write("sketch_add_geometry", {"sketch_name": "ClSk", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}]})
    read("sketch_get", _xray("ClSk"), _one_profile(400.0, (10, 10)),
         ("cl_corner", _recall("cl_corner", _point_at(20, 20))))

    def corner(dz, check):
        write("sketch_move", lambda c: {"sketch_name": "ClSk", "dz": dz,
                                        "entities": _ctx_get(c, "cl_corner", "the corner point")},
              lambda p: (p.get("profile_count_before"), p.get("profile_count_after")) == (1, 1)
              and p.get("moved_entities") == [_RECALL["cl_corner"]]
              and sorted(p.get("followed_entities") or []) == sides and check(p))
    corner(5, lambda p: "on_plane_entities" not in p and "returned_to_plane" not in p)
    for side in sides:
        read("sketch_get", _xray("ClSk"), _line_height(side, 5.0))
    read("sketch_get", _xray("ClSk"), _one_profile(400.0, (10, 10)))
    corner(-5, lambda p: p.get("returned_to_plane") == [_RECALL["cl_corner"]]
           and "on_plane_entities" not in p)
    for side in sides:
        read("sketch_get", _xray("ClSk"), _line_height(side, 0.0))
    read("sketch_get", _xray("ClSk"), _one_profile(400.0, (10, 10)))
    close()
    return rows


_SKETCHWORK += _constrained_lift_rows()


_TEXT_OUTLINE_SCRIPT = (
    "import adsk.core, adsk.fusion, json\n"
    "def run(context):\n"
    "    design=adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)\n"
    "    text=design.rootComponent.sketches.itemByName('TxSk').sketchTexts.item(0)\n"
    "    ends=[]; unread=0\n"
    "    for curve in text.asCurves():\n"
    "        got=curve.evaluator.getEndPoints()\n"
    "        if got[0] is not True:\n"
    "            unread+=1; continue\n"
    "        ends += [[round(p.x,5),round(p.y,5)] for p in got[1:3]]\n"
    "    ends.sort()\n"
    "    lines=design.rootComponent.sketches.itemByName('TxSk').sketchCurves.sketchLines\n"
    "    try:\n"
    "        on=[text.definition.path==lines.item(i) for i in (0,1)]\n"
    "    except Exception as exc:\n"
    "        on=str(exc)[:120]\n"
    "    print(json.dumps({'curves':len(ends)//2,'unread':unread,'ends':ends,'path_is':on,\n"
    "        'flip_h':text.isHorizontalFlip,'flip_v':text.isVerticalFlip}))\n")


def _script_reply(reply):
    """A read-only script's one JSON object, whether the harness decoded its output or not."""
    if isinstance(reply, dict):
        return reply
    found = None
    for line in str(reply or "").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            if found is not None:
                raise AssertionError("the script printed more than one JSON object")
            found = row
    if found is None:
        raise AssertionError(f"the script printed no JSON object: {str(reply)[:300]}")
    return found


def _outline_read(flip_h, same_as_first):
    """The read-only glyph outline of TxSk text 0: the flag, and whether it equals the first read."""
    def check(p):
        p = _script_reply(p)
        first = _RECALL.get("tx_outline")
        ends = p.get("ends")
        return _measured(f"text outline with flip_h {flip_h}",
                         {"curves": p.get("curves"), "unread": p.get("unread"),
                          "flip_h": p.get("flip_h")},
                         p.get("unread") == 0 and p.get("curves", 0) > 0
                         and p.get("flip_h") is flip_h and first is not None
                         and len(ends) == len(first) and (ends == first) is same_as_first)
    return check


def _text_box(key=None, x=None, y=None):
    """sketch_get: text `key`'s box as [min x, min y, max x, max y] mm, inside the given spans."""
    def check(p):
        row = _rows_by_id(p).get(key or "text:0") or {}
        box = row.get("bounding_box") or {}
        got = [(box.get("min") or {}).get("x"), (box.get("min") or {}).get("y"),
               (box.get("max") or {}).get("x"), (box.get("max") or {}).get("y")]
        return _measured(f"{key or 'text:0'} box", got,
                         all(_num(v) for v in got)
                         and (x is None or (x[0] <= got[0] and got[2] <= x[1]))
                         and (y is None or (y[0] <= got[1] and got[3] <= y[1])))
    return check


def _box_of(p):
    box = (_rows_by_id(p).get("text:0") or {}).get("bounding_box") or {}
    return [box.get("min"), box.get("max")] if box.get("min") and box.get("max") else None


def _text_layout_rows():
    """Flip, style, re-lay and explode EXISTING sketch text; the flip is judged on its glyph outline."""
    rows, write, read, close = _scratch_rows("tx_doc")
    write("sketch_create", {"plane": "xy", "name": "TxSk"})
    write("sketch_add_geometry", {"sketch_name": "TxSk", "geometry": [
        {"kind": "line", "x1": 0, "y1": -30, "x2": 60, "y2": -30},
        {"kind": "line", "x1": 0, "y1": -60, "x2": 60, "y2": -60}]})
    write("sketch_set_text", {"text": "AB", "sketch_name": "TxSk", "create": True, "height": 5,
                              "mode": "along_path", "path": "line:0"},
          lambda p: p.get("created") is True and p.get("mode_verified") is True)
    write("sketch_set_text", {"text": "CD", "sketch_name": "TxSk", "create": True, "height": 5,
                              "x": 0, "y": 20}, lambda p: p.get("sketch_text_count") == 2)
    outline = {"script": _TEXT_OUTLINE_SCRIPT, "read_only": True}

    def layout(check, index=0, **args):
        write("sketch_set_text", {"sketch_name": "TxSk", "index": index, **args}, check)
    # The text starts above line:0, at its start.
    _keep(read, "sketch_get", _xray("TxSk"), "tx_box", _box_of,
          _text_box(x=(-1, 20), y=(-30.5, -22)))
    first = lambda p: _script_reply(p)
    read("sys_execute_script", outline,
         lambda p: first(p).get("unread") == 0 and first(p).get("curves", 0) > 0
         and first(p).get("flip_h") is False and first(p).get("path_is") == [True, False],
         ("tx_outline", _recall("tx_outline", lambda p: first(p)["ends"])))
    layout(lambda p: p.get("flip_h") is True and p.get("flip_h_outline_changed") is True,
           flip_h=True)
    read("sys_execute_script", outline, _outline_read(True, False))
    layout(lambda p: p.get("flip_h") is False, flip_h=False)
    read("sys_execute_script", outline, _outline_read(False, True))
    read("sketch_get", _xray("TxSk"), _unchanged("tx_box", _box_of, 0.001))
    layout(lambda p: p.get("style") == ["bold"], style=["bold"])
    read("sketch_get", _xray("TxSk"),
         lambda p: _box_of(p) is not None and not _alike(_box_of(p), _RECALL["tx_box"], 0.001))
    layout(lambda p: p.get("style") == [], style=[])
    read("sketch_get", _xray("TxSk"), _unchanged("tx_box", _box_of, 0.001))
    # Refused before anything is written: the flip must still read false afterwards.
    layout(_refused("'path' did not resolve 'line:9'"), flip_h=True, mode="along_path",
           path="line:9")
    read("sys_execute_script", outline, _outline_read(False, True))
    layout(_refused("multi-line box"), index=1, mode="along_path", path="line:1")
    layout(lambda p: p.get("mode") == "along_path" and p.get("path") == "line:1"
           and p.get("path_confirmed") is not False and p.get("placement_checked") is True,
           mode="along_path", path="line:1")
    read("sketch_get", _xray("TxSk"), _text_box(x=(-1, 20), y=(-60.5, -52)))
    # The text's own definition names line:1 now, read apart from the tool that re-laid it.
    read("sys_execute_script", outline,
         lambda p: _measured("the definition's path after the re-lay", first(p).get("path_is"),
                             first(p).get("path_is") == [False, True]))
    read("sketch_get", _xray("TxSk"), lambda p: p["counts"]["texts"] == 2,
         ("tx_counts", _recall("tx_counts", lambda p: dict(p["counts"]))))
    layout(_refused("rides alone"), index=1, explode=True, flip_h=True)
    layout(lambda p: p.get("exploded") is True and p.get("curve_count", 0) > 0
           and p.get("sketch_text_count") == 1, index=1, explode=True)
    read("sketch_get", _xray("TxSk"),
         lambda p: p["counts"]["texts"] == 1
         and sum(v for k, v in p["counts"].items() if k not in ("texts", "points"))
         > sum(v for k, v in _RECALL["tx_counts"].items() if k not in ("texts", "points")))
    close()
    return rows


_SKETCHWORK += _text_layout_rows()
