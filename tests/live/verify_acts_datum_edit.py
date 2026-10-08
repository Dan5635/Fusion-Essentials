# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Datum and joint-origin definition edits, each on its own scratch document."""

import math

from verify_core import (
    _RECALL, _ctx_get, _datum, _document_closed, _face_up_at, _fg, _home_address, _home_document,
    _matched, _measured, _near, _new_document, _recall, _refused)

from verify_acts_model_combine_revolve import _combine_body, _combine_inspect, _combine_pin
from verify_acts_model_definition_operand import _operand_at

_DISC = math.pi * 25 * 5


def _story(key):
    """(rows, write, read, close) for one owned scratch document pinned under `key`."""
    rows = [("doc_get", {}, _home_document, (key + "_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, key + "_home", "home")},
             _new_document, (key + "_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(
            c, key + "_doc", args(c) if callable(args) else args), check, save))

    def read(tool, args, check, save=None):
        rows.append((tool, args, check, save))

    def close():
        write("doc_activate", lambda c: {"name": _ctx_get(c, key + "_home", "home")})
        rows.append(("doc_close", lambda c: {"name": _ctx_get(c, key + "_doc", "scratch"),
                     "save_changes": False, "expect_document": _ctx_get(c, key + "_home", "home")},
                     _document_closed, None))
        return rows

    return rows, write, read, close


def _box(write, name, x1, y1, x2, y2, height, plane="xy"):
    """One extruded rectangle on a named sketch."""
    write("sketch_create", {"name": name, "plane": plane})
    write("sketch_add_geometry", {"sketch_name": name, "geometry": [
        {"kind": "rectangle", "x1": x1, "y1": y1, "x2": x2, "y2": y2}]})
    write("model_extrude", {"sketch_name": name, "distance": height})


def _built(kind):
    """model_construction: a datum of this kind was created and carries a handle."""
    return lambda p: _measured(kind + " datum built", {"kind": p.get("kind"),
                                                       "created": p.get("created")},
                               p.get("created") is True and p.get("kind") == kind
                               and bool(p.get("handle")))


def _extent(label, low, high, volume, count):
    """model_inspect over the design: bounds (None skips an axis), body count and total volume."""
    def check(p):
        mass = p.get("mass") or {}
        bounds = ((p.get("min_point") or {}), (p.get("max_point") or {}))
        good = all(want is None or _near(point.get(axis), want, 0.01)
                   for point, wanted in zip(bounds, (low, high))
                   for axis, want in zip("xyz", wanted))
        return _measured(label + " design extent", {"min": bounds[0], "max": bounds[1],
                                                    "volume": mass.get("volume"),
                                                    "bodies": mass.get("per_body_count")},
                         good and mass.get("per_body_count") == count
                         and mass.get("per_body_truncated") is False
                         and _near(mass.get("volume"), volume, 0.01))
    return check


def _healthy_at_end(p):
    """design_get timeline: every row healthy and the marker at the end."""
    timeline = p.get("timeline") or {}
    summary = timeline.get("summary") or {}
    count = timeline.get("count")
    return _measured("timeline healthy with the marker at its end",
                     {"count": count, "marker": timeline.get("marker_position"),
                      "states": summary.get("states"), "exceptions": summary.get("exceptions")},
                     isinstance(count, int) and count > 0 and timeline.get("returned") == count
                     and timeline.get("marker_position") == count
                     and summary.get("states") == {"healthy": count}
                     and summary.get("exceptions") == [])


def _datum_row(p):
    """The one datum a named find_geometry read returned, without its transient handle."""
    matches = p.get("matches") or []
    if len(matches) != 1:
        raise AssertionError("the datum read did not return exactly one row")
    return {key: value for key, value in matches[0].items() if key != "handle"}


def _same_datum(key):
    """find_geometry: a control datum reads exactly as it was parked under `key`."""
    return lambda p: _measured("control datum unchanged", p.get("matches"),
                               key in _RECALL and _datum_row(p) == _RECALL[key])


def _edited(action, note=None):
    """The edit reply: verified definition, changed geometry, healthy timeline and an unmoved marker."""
    def check(p):
        return _measured(
            "datum edit reply", {key: p.get(key) for key in (
                "edited", "definition_matches", "geometry_changed", "same_feature",
                "marker_before", "marker_after", "new_timeline_errors", "new_timeline_warnings")},
            p.get("action") == action and p.get("edited") is True
            and p.get("definition_matches") is True and p.get("geometry_changed") is True
            and p.get("same_feature") is True and p.get("marker_restored") is True
            and isinstance(p.get("marker_before"), int)
            and p.get("marker_after") == p["marker_before"]
            and p.get("new_timeline_errors") == [] and p.get("new_timeline_warnings") == []
            and p.get("target_geometry_before") != p.get("target_geometry_after")
            and (note is None or note in (p.get("note") or "")))
    return check


def _definition_of(action, park=None):
    """design_get definition: the datum reads its one supported edit with a concrete call."""
    def check(p):
        row = p.get("definition") or {}
        edits = row.get("supported_edits") or []
        if park:
            _RECALL[park] = row.get("offset")
        return _measured("datum definition lists its edit", {"edits": edits,
                                                             "unavailable": row.get("unavailable")},
                         row.get("unavailable") == {} and len(edits) == 1
                         and edits[0].get("action") == action
                         and str(edits[0].get("call") or "").startswith("model_edit_feature("))
    return check


def _parallel_axis(vector, axis):
    """True when a unit vector lies along one world axis, either way."""
    return (isinstance(vector, list) and len(vector) == 3
            and all(_near(abs(v) if i == axis else v, 1 if i == axis else 0, 0.0001)
                    for i, v in enumerate(vector)))


def _seat_at(stage):
    """find_geometry: the edited plane's position and normal at one stage of the plane story."""
    def check(p):
        row = _datum_row(p)
        position, normal = row.get("position"), row.get("normal")
        if stage == "turned":
            good = (_parallel_axis(normal, 1) and isinstance(position, list)
                    and _near(abs(position[1]), 10, 0.001))
        else:
            good = (_operand_at(position, [0, 0, {"built": 10, "parallel": 15}[stage]])
                    and _operand_at(normal, [0, 0, 1], 0.0001))
        return _measured("edited plane position and normal, " + stage, row,
                         _matched(1, "construction_plane")(p) and good)
    return check


def _seat_sketch_at(stage):
    """sketch_get: the dependent sketch's frame lies on the plane at this stage."""
    def check(p):
        frame = p.get("frame") or {}
        origin, normal = frame.get("origin_mm"), frame.get("normal")
        if stage == "turned":
            good = (_parallel_axis(normal, 1) and isinstance(origin, list) and len(origin) == 3
                    and _near(abs(origin[1]), 10, 0.001))
        else:
            good = (isinstance(origin, list) and len(origin) == 3
                    and _near(origin[2], {"built": 10, "parallel": 15}[stage], 0.001)
                    and _operand_at(normal, [0, 0, 1], 0.0001))
        return _measured("dependent sketch frame, " + stage, frame,
                         frame.get("space") == "world" and good)
    return check


def _turned_extent(p):
    """model_inspect: the dependent disc sits 10 to 15 mm off the XZ plane, on either side."""
    low, high = p.get("min_point") or {}, p.get("max_point") or {}
    mass = p.get("mass") or {}
    side = _near(low.get("y"), 10, 0.01) or _near(low.get("y"), -15, 0.01)
    return _measured("turned dependent lies on the new plane", {"min": low, "max": high,
                                                               "volume": mass.get("volume")},
                     side and _near(low.get("x"), -5, 0.01) and _near(low.get("z"), -5, 0.01)
                     and _near(high.get("x"), 50, 0.01) and _near(high.get("y"), 50, 0.01)
                     and _near(high.get("z"), 5, 0.01) and mass.get("per_body_count") == 2
                     and _near(mass.get("volume"), 500 + _DISC, 0.01))


def _plane_rows():
    """Re-base an offset plane onto a parallel and a turned plane under a sketch and an extrude."""
    _rows, write, read, close = _story("dep")
    control = lambda: read("model_inspect", _combine_inspect("Body1"),
                           _combine_body("control", (40, 40, 0), (50, 50, 5), 500))
    seat = lambda stage: (
        read("find_geometry", {"kind": "construction_plane", "name": "Seat"}, _seat_at(stage)),
        read("sketch_get", {"sketch_name": "SeatSk"}, _seat_sketch_at(stage)))

    _box(write, "CtlSk", 40, 40, 50, 50, 5)
    write("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy", "offset": 5,
                                 "name": "Low"}, _datum("plane"))
    write("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy", "offset": 10,
                                 "name": "Seat"}, _datum("plane"))
    write("model_construction", {"kind": "plane", "mode": "offset", "plane": "xz", "offset": 7,
                                 "name": "Witness"}, _datum("plane"))
    write("model_construction", {"kind": "plane", "mode": "midplane", "plane": "xy",
                                 "plane2": "Low", "name": "Middle"}, _built("plane"))
    write("sketch_create", {"name": "SeatSk", "plane": "Seat"})
    write("sketch_add_geometry", {"sketch_name": "SeatSk", "geometry": [
        {"kind": "circle", "cx": 0, "cy": 0, "radius": 5}]})
    write("model_extrude", {"sketch_name": "SeatSk", "distance": 5})
    seat("built")
    read("model_inspect", _combine_inspect(),
         _extent("built", (-5, -5, 0), (50, 50, 15), 500 + _DISC, 2))
    read("find_geometry", {"kind": "construction_plane", "name": "Witness"},
         _matched(1, "construction_plane"), ("dep_witness", _recall("dep_witness", _datum_row)))
    read("find_geometry", {"kind": "construction_plane", "name": "Middle"},
         _matched(1, "construction_plane"), ("dep_middle", _recall("dep_middle", _datum_row)))
    read("design_get", {"include": ["definition"], "feature": "Seat"},
         _definition_of("plane", park="dep_offset"))

    write("model_edit_feature", {"feature": "Seat", "action": "plane", "references": ["Low"]},
          lambda p: _edited("plane", "can change orientation")(p) and _measured(
              "parallel re-base keeps the offset and reads the new base", p.get("definition_after"),
              p.get("returned") is True
              and (p.get("definition_after") or {}).get("offset") == _RECALL.get("dep_offset")
              and ((p.get("definition_after") or {}).get("base_plane") or {}).get("name") == "Low"
              and _operand_at((p.get("target_geometry_after") or {}).get("origin_cm"),
                              [0, 0, 1.5], 0.00001)))
    seat("parallel")
    read("model_inspect", _combine_inspect(),
         _extent("parallel", (-5, -5, 0), (50, 50, 20), 500 + _DISC, 2))
    read("design_get", {"include": ["timeline"], "max_results": 100}, _healthy_at_end)
    control()
    read("find_geometry", {"kind": "construction_plane", "name": "Witness"},
         _same_datum("dep_witness"))

    write("model_edit_feature", {"feature": "Seat", "action": "plane", "references": ["xz"]},
          lambda p: _edited("plane", "can change orientation")(p) and _measured(
              "turned re-base keeps the offset and turns the plane", p.get("target_geometry_after"),
              (p.get("definition_after") or {}).get("offset") == _RECALL.get("dep_offset")
              and _parallel_axis((p.get("target_geometry_after") or {}).get("normal"), 1)))
    seat("turned")
    read("model_inspect", _combine_inspect(), _turned_extent)
    read("design_get", {"include": ["timeline"], "max_results": 100}, _healthy_at_end)
    control()
    read("find_geometry", {"kind": "construction_plane", "name": "Witness"},
         _same_datum("dep_witness"))

    read("design_get", {"include": ["definition"], "feature": "Middle"},
         lambda p: _measured("a midplane offers no edit", p.get("definition"),
                             (p.get("definition") or {}).get("supported_edits") == []))
    write("model_edit_feature", {"feature": "Middle", "action": "plane", "references": ["xz"]},
          _refused("definition type reads", "model_construction(kind='plane', mode='offset')",
                   "Nothing was edited"))
    read("find_geometry", {"kind": "construction_plane", "name": "Middle"},
         _same_datum("dep_middle"))
    return close()


def _spin_at(x):
    """find_geometry: the edited axis runs along Z through (x, 0)."""
    def check(p):
        row = _datum_row(p)
        position = row.get("position")
        return _measured("edited axis position and direction", row,
                         _matched(1, "construction_axis")(p) and isinstance(position, list)
                         and _near(position[0], x, 0.001) and _near(position[1], 0, 0.001)
                         and _parallel_axis(row.get("direction"), 2))
    return check


def _axis_rows():
    """Re-define a two-plane axis and read the circular-pattern copy it carries."""
    _rows, write, read, close = _story("dea")
    fixed = lambda: (
        read("model_inspect", _combine_inspect("Body1"),
             _combine_body("pattern seed", (25, -2.5, 0), (30, 2.5, 5), 125)),
        read("model_inspect", _combine_inspect("Body2"),
             _combine_body("control", (40, 50, 0), (45, 55, 5), 125)))

    _box(write, "SeedSk", 25, -2.5, 30, 2.5, 5)
    _box(write, "CtlSk", 40, 50, 45, 55, 5)
    for name, offset in (("AxA", 10), ("AxB", 20)):
        write("model_construction", {"kind": "plane", "mode": "offset", "plane": "yz",
                                     "offset": offset, "name": name}, _datum("plane"))
    write("model_construction", {"kind": "axis", "mode": "two_planes", "plane": "AxA",
                                 "plane2": "xz", "name": "Spin"}, _built("axis"))
    write("model_pattern_circular", {"bodies": ["Body1"], "quantity": 2, "total_angle_deg": 360,
                                     "axis": "Spin"},
          lambda p: p.get("quantity") == 2 and p.get("axis") == "Spin")
    read("find_geometry", {"kind": "construction_axis", "name": "Spin"}, _spin_at(10))
    read("model_inspect", _combine_inspect(),
         _extent("built", (-10, -2.5, 0), (45, 55, 5), 375, 3))
    read("design_get", {"include": ["definition"], "feature": "Spin"}, _definition_of("axis"))

    pair = [{"first_plane": "AxB", "second_plane": "xz"}]
    write("model_edit_feature", {"feature": "Spin", "action": "axis", "references": pair},
          lambda p: _edited("axis")(p) and _measured(
              "both plane roles read back as requested", p.get("definition_after"),
              p.get("returned") is True
              and (((p.get("definition_after") or {}).get("planes") or {}).get("first_plane")
                   or {}).get("name") == "AxB"
              and (((p.get("definition_after") or {}).get("planes") or {}).get("second_plane")
                   or {}).get("kind") == "construction_plane"
              and _near(((p.get("target_geometry_after") or {}).get("origin_cm") or [None])[0],
                        2.0, 0.00001)))
    read("find_geometry", {"kind": "construction_axis", "name": "Spin"}, _spin_at(20))
    read("model_inspect", _combine_inspect(),
         _extent("re-defined", (10, -2.5, 0), (45, 55, 5), 375, 3))
    read("design_get", {"include": ["timeline"], "max_results": 100}, _healthy_at_end)
    fixed()

    write("model_edit_feature", {"feature": "Spin", "action": "plane", "references": ["AxA"]},
          _refused("does not support action='plane'", "Supported: axis", "Example:"))
    write("model_edit_feature", {"feature": "Spin", "action": "axis",
                                 "references": [{"first_plane": "xz", "second_plane": "xz"}]},
          _refused("name the same plane", "Nothing was edited"))
    read("find_geometry", {"kind": "construction_axis", "name": "Spin"}, _spin_at(20))
    read("model_inspect", _combine_inspect(),
         _extent("after refusals", (10, -2.5, 0), (45, 55, 5), 375, 3))
    return close()


def _pin_at(x, y, z):
    """find_geometry: the edited point sits at one box vertex."""
    return lambda p: _measured("edited point position", p.get("matches"),
                               _matched(1, "construction_point")(p)
                               and _operand_at(p["matches"][0].get("position"), [x, y, z]))


def _vertex_at(x, y, z):
    """find_geometry: the nearest vertex is the one asked for."""
    return lambda p: _measured("vertex acquired", p.get("matches"),
                               _matched(1, "vertex")(p)
                               and _operand_at(p["matches"][0].get("position"), [x, y, z]))


def _point_rows():
    """Move a point datum to another vertex under a plane, a sketch and an extrude built on it."""
    _rows, write, read, close = _story("dpt")
    box = lambda: read("model_inspect", _combine_inspect("Body1"),
                       _combine_body("control box", (0, 0, 0), (10, 10, 10), 1000))

    _box(write, "BoxSk", 0, 0, 10, 10, 10)
    read("find_geometry", {"target": "Body1", "kind": "vertex", "nearest_to": [10, 10, 10],
                           "max_results": 1}, _vertex_at(10, 10, 10), _fg("dpt_top"))
    read("find_geometry", {"target": "Body1", "kind": "vertex", "nearest_to": [0, 0, 0],
                           "max_results": 1}, _vertex_at(0, 0, 0), _fg("dpt_low"))
    write("model_construction", lambda c: {"kind": "point", "mode": "at_point", "name": "Pin",
                                           "points": [_ctx_get(c, "dpt_top", "top vertex")]},
          _datum("point"))
    write("model_construction", {"kind": "plane", "mode": "offset_through_point", "plane": "xy",
                                 "points": ["Pin"], "name": "PinPlane"}, _built("plane"))
    write("sketch_create", {"name": "PinSk", "plane": "PinPlane"})
    write("sketch_add_geometry", {"sketch_name": "PinSk", "geometry": [
        {"kind": "circle", "cx": 0, "cy": 0, "radius": 5}]})
    write("model_extrude", {"sketch_name": "PinSk", "distance": 5})
    read("find_geometry", {"kind": "construction_point", "name": "Pin"}, _pin_at(10, 10, 10))
    read("model_inspect", _combine_inspect(),
         _extent("built", (None, None, 0), (None, None, 15), 1000 + _DISC, 2))
    read("design_get", {"include": ["definition"], "feature": "Pin"}, _definition_of("point"))

    write("model_edit_feature", lambda c: {"feature": "Pin", "action": "point",
                                           "references": [_ctx_get(c, "dpt_low", "low vertex")]},
          lambda p: _edited("point")(p) and _measured(
              "the point reads at the requested vertex", p.get("target_geometry_after"),
              ((p.get("definition_after") or {}).get("point_entity") or {}).get("kind") == "vertex"
              and _operand_at((p.get("target_geometry_after") or {}).get("world_cm"),
                              [0, 0, 0], 0.00001)))
    read("find_geometry", {"kind": "construction_point", "name": "Pin"}, _pin_at(0, 0, 0))
    read("model_inspect", _combine_inspect(),
         _extent("moved", (None, None, 0), (None, None, 10), 1000 + _DISC, 2))
    read("design_get", {"include": ["timeline"], "max_results": 100}, _healthy_at_end)
    box()

    write("model_edit_feature", {"feature": "Pin", "action": "plane", "references": ["xy"]},
          _refused("does not support action='plane'", "Supported: point", "Example:"))
    read("find_geometry", {"kind": "construction_point", "name": "Pin"}, _pin_at(0, 0, 0))
    read("model_inspect", _combine_inspect(),
         _extent("after refusal", (None, None, 0), (None, None, 10), 1000 + _DISC, 2))
    return close()


def _dock_at(position, z_axis):
    """assembly_get joint_origins: the re-anchored origin's world position and Z, beside the idle one."""
    def check(p):
        rows = {row.get("name"): row for row in (p.get("joint_origins") or [])}
        dock, idle = rows.get("Dock") or {}, rows.get("Idle") or {}
        frame = dock.get("frame") or {}
        axes = [frame.get(key) for key in ("x_axis", "y_axis", "z_axis")]
        square = all(isinstance(a, list) and len(a) == 3 for a in axes) and all(
            _near(sum(u * v for u, v in zip(axes[i], axes[j])), 1 if i == j else 0, 0.0001)
            for i in range(3) for j in range(3))
        return _measured("joint origin world frame", {"dock": dock, "idle": idle},
                         _operand_at(dock.get("world_position"), position)
                         and _operand_at(frame.get("z_axis"), z_axis, 0.0001) and square
                         and _operand_at(idle.get("world_position"), [0, 0, 0]))
    return check


def _reanchored(p):
    """The joint-origin reply: rolled route restored to the end, entity, origin and three axes read."""
    after = p.get("target_geometry_after") or {}
    axes = [after.get(key) for key in ("primary_axis", "secondary_axis", "third_axis")]
    return _measured(
        "joint origin re-anchor reply", {"after": after, "marker": p.get("marker_after"),
                                         "matches": p.get("definition_matches")},
        p.get("action") == "geometry" and p.get("edited") is True
        and p.get("definition_matches") is True and p.get("same_feature") is True
        and p.get("marker_restored") is True and p.get("marker_after") == p.get("marker_before")
        and p.get("new_timeline_errors") == [] and p.get("geometry_changed") is True
        and ((p.get("definition_after") or {}).get("geometry") or {}).get("kind") == "face"
        and _operand_at(after.get("origin_cm"), [0, 1, 0.5], 0.00001)
        and _operand_at(axes[0], [-1, 0, 0], 0.0001)
        and all(isinstance(axis, list) and len(axis) == 3 for axis in axes)
        and (p.get("target_geometry_before") or {}).get("primary_axis") != axes[0])


def _origin_rows():
    """Re-anchor a joint origin from a box's top face to its side face."""
    _rows, write, read, close = _story("djo")
    _box(write, "DockSk", 0, 0, 20, 20, 10)
    read("find_geometry", {"target": "Body1", "kind": "planar_face", "nearest_to": [10, 10, 10],
                           "max_results": 1}, _face_up_at(10, 10, 10, 0.001), _fg("djo_top"))
    read("find_geometry", {"target": "Body1", "kind": "planar_face", "nearest_to": [0, 10, 5],
                           "max_results": 1},
         lambda p: _matched(1, "planar_face")(p)
         and _operand_at(p["matches"][0].get("position"), [0, 10, 5])
         and _operand_at(p["matches"][0].get("normal"), [-1, 0, 0], 0.0001), _fg("djo_side"))
    write("joint_create_origin", lambda c: {"anchor": "face_center", "name": "Dock",
                                            "geometry": _ctx_get(c, "djo_top", "top face")},
          lambda p: p.get("created") is True and p.get("joint_origin_name") == "Dock")
    write("joint_create_origin", {"anchor": "coordinates", "target": "origin", "name": "Idle"},
          lambda p: p.get("created") is True and p.get("joint_origin_name") == "Idle")
    read("assembly_get", {"include": ["joint_origins"], "units": "mm"},
         _dock_at([10, 10, 10], [0, 0, 1]))
    read("design_get", {"include": ["definition"], "feature": "Dock"}, _definition_of("geometry"))

    write("model_edit_feature", lambda c: {"feature": "Dock", "action": "geometry",
                                           "references": [_ctx_get(c, "djo_side", "side face")]},
          _reanchored)
    read("assembly_get", {"include": ["joint_origins"], "units": "mm"},
         _dock_at([0, 10, 5], [-1, 0, 0]))
    read("design_get", {"include": ["timeline"], "max_results": 100}, _healthy_at_end)
    read("model_inspect", _combine_inspect("Body1"),
         _combine_body("control box", (0, 0, 0), (20, 20, 10), 4000))

    write("model_edit_feature", {"feature": "Dock", "action": "mode", "mode": "flipped"},
          _refused("does not support action='mode'", "Supported: geometry"))
    read("assembly_get", {"include": ["joint_origins"], "units": "mm"},
         _dock_at([0, 10, 5], [-1, 0, 0]))
    read("design_get", {"include": ["timeline"], "max_results": 100}, _healthy_at_end)
    return close()


def _plane_read(check, park=None):
    """find_geometry on one named construction plane: `check(position, normal)` on its own row."""
    def judge(p):
        row = _datum_row(p)
        position, normal = row.get("position"), row.get("normal")
        good = (isinstance(position, list) and isinstance(normal, list) and len(position) == 3
                and len(normal) == 3 and _near(sum(v * v for v in normal), 1, 0.0001))
        if good and park:
            _RECALL[park] = (position, normal)
        return _measured("construction plane position and normal", row,
                         _matched(1, "construction_plane")(p) and good and check(position, normal))
    return judge


def _perpendicular_and_tangent_rows():
    """A plane perpendicular to XY, one offset from it, and a plane tangent to a cylinder."""
    _rows, write, read, close = _story("pt")
    plane = lambda name: {"kind": "construction_plane", "name": name}
    # A cylinder of radius 5 about the vertical through (30, 0), 10 tall.
    write("sketch_create", {"name": "PtCyl", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "PtCyl", "geometry": [
        {"kind": "circle", "cx": 30, "cy": 0, "radius": 5}]})
    write("model_extrude", {"sketch_name": "PtCyl", "distance": 10})
    read("find_geometry", {"kind": "cylinder_face", "radius": 5, "max_results": 5},
         _matched(1, "cylinder_face"), _fg("pt_wall"))
    write("model_construction", {"kind": "plane", "mode": "perpendicular_to_plane", "plane": "xy",
                                 "offset": 4, "points": ["anything"], "name": "PtBoth"},
          _refused("'offset' OR through one of 'points', not both"))
    write("model_construction", {"kind": "plane", "mode": "perpendicular_to_plane", "plane": "xy",
                                 "name": "PtUp"},
          lambda p: _built("plane")(p) and p.get("perpendicular") is True)
    read("find_geometry", plane("PtUp"),
         _plane_read(lambda position, normal: abs(normal[2]) < 0.0001, park="pt_up"))
    write("model_construction", {"kind": "plane", "mode": "perpendicular_to_plane", "plane": "xy",
                                 "offset": 12, "name": "PtUpOff"},
          lambda p: _built("plane")(p) and p.get("perpendicular") is True
          and p.get("offset") in (12.0, None))
    # The offset plane is the first one moved 12 mm along its own normal, either way.
    read("find_geometry", plane("PtUpOff"), _plane_read(
        lambda position, normal: abs(normal[2]) < 0.0001 and _near(abs(sum(
            n * (a - b) for n, a, b in zip(_RECALL["pt_up"][1], position, _RECALL["pt_up"][0]))),
            12, 0.001)))
    tangent = lambda c, reference, name: {
        "kind": "plane", "mode": "tangent", "face": _ctx_get(c, "pt_wall", "the cylinder wall"),
        "plane": reference, "angle": 0, "name": name}
    write("model_construction", lambda c: tangent(c, "xy", "PtFlat"),
          _refused("square to the cylinder's axis"))
    write("model_construction", lambda c: tangent(c, "xz", "PtTan"),
          lambda p: _built("plane")(p) and p.get("tangent_to_face") is True)
    # Tangent: the plane stands upright and sits one radius, 5 mm, from the axis through (30, 0).
    read("find_geometry", plane("PtTan"), _plane_read(
        lambda position, normal: abs(normal[2]) < 0.0001 and _near(
            abs(normal[0] * (position[0] - 30) + normal[1] * position[1]), 5, 0.001)))
    read("find_geometry", {"kind": "construction_plane", "max_results": 20},
         lambda p: {"PtTan", "PtUp", "PtUpOff"} <= {m.get("name") for m in p.get("matches") or []}
         and not {"PtBoth", "PtFlat"} & {m.get("name") for m in p.get("matches") or []})
    for name in ("PtUp", "PtTan"):
        read("design_get", {"include": ["definition"], "feature": name},
             lambda p: isinstance(p.get("definition"), dict))
    read("design_get", {"include": ["timeline"], "max_results": 200}, _healthy_at_end)
    return close()


_DATUM_EDITS = (_plane_rows() + _axis_rows() + _point_rows() + _origin_rows()
                + _perpendicular_and_tangent_rows())
