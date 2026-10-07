# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Split, silhouette, offset-face, fillet and chamfer operand edits, each on its own scratch document."""

from verify_core import (
    _RECALL, _ctx_get, _datum, _extruded, _measured, _near, _num, _recall, _refused)

from verify_acts_datum_edit import _healthy_at_end
from verify_acts_model_combine_revolve import _combine_inspect
from verify_acts_sketch import (
    _alike, _body_facts, _box_reads, _boxed, _inspect, _keep, _scratch_rows, _solid, _unchanged,
    _vec3)

# Volumes and areas are the measured values in mm3 and mm2; the bands cover their rounding.
_VOLUME_TOL, _AREA_TOL, _BOX_TOL, _SHAPE_TOL = 0.05, 0.05, 0.01, 0.0001
_HISTORY = {"include": ["timeline"], "max_results": 100}
_EDGES = {"kind": "line_edge", "max_results": 100}
_FACES = {"kind": "planar_face", "max_results": 100}


def _named(key, what="a saved name"):
    """An argument reader for the name an earlier step saved under `key`."""
    return lambda c: _ctx_get(c, key, what)


def _body_reads(label, low, high, volume, area):
    """model_inspect: one solid lump with these bounds, volume and surface area in mm."""
    def check(p):
        mass = p.get("mass") or {}
        lo, hi = p.get("min_point") or {}, p.get("max_point") or {}
        return _measured(label, {"min": lo, "max": hi, "volume": mass.get("volume"),
                                 "area": mass.get("area"), "lumps": p.get("lump_count")},
                         p.get("kind") == "body" and p.get("units") == "mm"
                         and p.get("lump_count") == 1 and mass.get("accuracy_used") == "very_high"
                         and all(_near(lo.get(a), w, _BOX_TOL) for a, w in zip("xyz", low))
                         and all(_near(hi.get(a), w, _BOX_TOL) for a, w in zip("xyz", high))
                         and _near(mass.get("volume"), volume, _VOLUME_TOL)
                         and _near(mass.get("area"), area, _AREA_TOL))
    return check


def _topology(label, count):
    """find_geometry with no kind: the body's faces plus edges count."""
    return lambda p: _measured(label + " faces plus edges", {"match_count": p.get("match_count"),
                                                             "kind_filter": p.get("kind_filter")},
                               p.get("kind_filter") == "faces+edges"
                               and p.get("match_count") == count)


def _pick(kind, position, normal=None, length=None, area=None, along=None):
    """(check, handle reader) for the ONE listed row at `position`; None skips an axis."""
    def rows(p):
        def fits(m):
            at, heading = m.get("position"), m.get("direction")
            return (m.get("kind") == kind and _vec3(at)
                    and all(w is None or _near(v, w, 0.001) for v, w in zip(at, position))
                    and (normal is None or _alike(m.get("normal"), list(normal), 0.0001))
                    and (along is None or (_vec3(heading) and _alike(
                        [abs(v) for v in heading], list(along), 0.0001)))
                    and (length is None or _near(m.get("length"), length, 0.001))
                    and (area is None or _near(m.get("area"), area, 0.01)))
        return [m for m in p.get("matches") or [] if fits(m)]

    def check(p):
        hits = rows(p)
        return _measured(f"one {kind} at {list(position)}",
                         {"match_count": p.get("match_count"), "returned": p.get("returned"),
                          "hits": [(m.get("position"), m.get("normal"), m.get("length"),
                                    m.get("area")) for m in hits]},
                         p.get("units") == "mm" and p.get("returned") == p.get("match_count")
                         and len(hits) == 1 and isinstance(hits[0].get("handle"), str)
                         and bool(hits[0]["handle"]))
    return check, lambda p: rows(p)[0]["handle"]


def _acquire(read, body, key, args, *want, **more):
    """A find_geometry read over the saved body that saves the one matching handle under `key`."""
    check, take = _pick(args["kind"], *want, **more)
    read("find_geometry", lambda c: {"target": _ctx_get(c, body, "the body"), **args}, check,
         (key, take))


def _count(p):
    """design_get timeline: its row count."""
    return (p.get("timeline") or {}).get("count")


def _history(key):
    """design_get timeline: every row healthy, the marker at the end, the banked row count."""
    return lambda p: _healthy_at_end(p) and _measured(
        "timeline row count as first read", {"count": _count(p), "banked": _RECALL.get(key)},
        _num(_RECALL.get(key)) and _count(p) == _RECALL[key])


def _rolled(to, key):
    """design_edit_timeline roll: before the last row, or back at the end of the banked count."""
    def check(p):
        count = _RECALL.get(key)
        back = 1 if to == "before" else 0
        return _measured("marker rolled " + to, {k: p.get(k) for k in (
            "rolled", "to", "marker_position", "timeline_count", "rolled_back")},
            p.get("rolled") is True and p.get("to") == to and _num(count)
            and p.get("timeline_count") == count and p.get("rolled_back") == back
            and p.get("marker_position") == count - back)
    return check


def _offered(row, action):
    """The one supported_edits call text a definition lists for `action`, else ''."""
    offered = [e for e in row.get("supported_edits") or [] if e.get("action") == action]
    return str(offered[0].get("call") or "") if len(offered) == 1 else ""


def _defined(label, action, facts, want, park=None, retained=None, same=None, call=""):
    """design_get definition, rolled before the feature: operands, retained fields, the offer."""
    def check(p):
        row = p.get("definition") or {}
        got, text = facts(row), _offered(row, action)
        kept = (_RECALL.get(retained) or {}).get("retained") if retained else None
        good = (got is not None and row.get("unavailable") == {}
                and all(v is not None for v in got["retained"].values())
                and text.startswith("model_edit_feature(feature='")
                and f"action='{action}'" in text and "references=[" in text and call in text
                and bool(want(got))
                and (retained is None or (kept is not None and _alike(got["retained"], kept, 1e-9)))
                and (same is None or _alike(got, _RECALL.get(same), 1e-6)))
        if good and park:
            _RECALL[park] = got
        return _measured(label, {"facts": got, "call": text,
                                 "unavailable": row.get("unavailable")}, good)
    return check


def _rolled_read(write, read, feature, count, check):
    """Roll before the feature, read its definition, roll to the end, read the marker there."""
    write("design_edit_timeline", lambda c: {"action": "roll", "to": "before",
                                             "feature": feature(c)}, _rolled("before", count))
    read("design_get", lambda c: {"include": ["definition"], "feature": feature(c)}, check)
    write("design_edit_timeline", {"action": "roll", "to": "end"}, _rolled("end", count))
    read("design_get", _HISTORY, _history(count))


def _shapes(side):
    """The reply's body census as rows of identity, name, cm3, cm2 and face count; [] when malformed."""
    rows = (side or {}).get("bodies")
    if (not isinstance(rows, list) or not rows
            or any(not isinstance(r, dict) or not isinstance(r.get("identity"), list)
                   or len(r["identity"]) != 2 or not isinstance(r["identity"][0], str)
                   or not r["identity"][0] for r in rows)
            or len({tuple(r["identity"]) for r in rows}) != len(rows)):
        return []
    return [{"identity": tuple(r["identity"]), "body": r.get("body"),
             "volume": (r.get("shape") or {}).get("volume_cm3"),
             "area": (r.get("shape") or {}).get("area_cm2"),
             "faces": (r.get("shape") or {}).get("face_count")} for r in rows]


def _shape_of(rows, key):
    """The one census row of the body whose name was saved under `key`, else {}."""
    hits = [r for r in rows if r["body"] is not None and r["body"] == _RECALL.get(key)]
    return hits[0] if len(hits) == 1 else {}


def _shape_is(row, volume, area, faces):
    """Whether a census row reads this cm3, cm2 and face count."""
    return (_near(row.get("volume"), volume, _SHAPE_TOL) and _near(row.get("area"), area, _SHAPE_TOL)
            and row.get("faces") == faces)


def _edited(action, feature, count, facts, was, now, shapes):
    """The edit reply: both definitions, retained fields, identity, marker, health and bodies."""
    def check(p):
        before = facts(p.get("definition_before") or {})
        after = facts(p.get("definition_after") or {})
        health = p.get("feature_health") or {}
        return _measured(
            "feature edit reply", {"before": before, "after": after, **{k: p.get(k) for k in (
                "edited", "definition_matches", "geometry_changed", "same_feature",
                "marker_before", "marker_after", "marker_restored", "feature_health",
                "new_timeline_errors", "new_timeline_warnings")},
                "bodies": [_shapes(p.get("geometry_before")), _shapes(p.get("geometry_after"))]},
            p.get("action") == action and p.get("edited") is True
            and p.get("feature") is not None and p.get("feature") == _RECALL.get(feature)
            and p.get("definition_matches") is True and p.get("same_feature") is True
            and p.get("owner_matches") is True and p.get("marker_restored") is True
            and _num(_RECALL.get(count))
            and p.get("marker_before") == p.get("marker_after") == _RECALL[count]
            and health.get("errors") == [] and health.get("warnings") == []
            and p.get("new_timeline_errors") == [] and p.get("new_timeline_warnings") == []
            and p.get("geometry_changed") is True and "read back" in (p.get("note") or "")
            and before is not None and after is not None and bool(was(before))
            and bool(now(after)) and _alike(before["retained"], after["retained"], 1e-9)
            and bool(shapes(_shapes(p.get("geometry_before")), _shapes(p.get("geometry_after")))))
    return check


def _edit(write, read, count, feature, action, references, check, **extra):
    """One model_edit_feature row, then the timeline read that finds the marker at the end."""
    write("model_edit_feature", lambda c: {"feature": feature(c), "action": action,
                                           "references": references(c), **extra}, check)
    read("design_get", _HISTORY, _history(count))


def _control(read, key, target, later=False):
    """The control box: banked on its first read, compared with that read afterwards."""
    if later:
        read("model_inspect", target, _unchanged(key, _body_facts, 1e-6))
    else:
        _keep(read, "model_inspect", target, key, _body_facts, _box_reads(10, 10, 10))


def _as_built(key, reads):
    """model_inspect: the measured body again, equal to its banked first read."""
    return lambda p: reads(p) and _unchanged(key, _body_facts, 1e-6)(p)


# --- SplitBodyFeature: splitting tool ------------------------------------------------------------

def _split_facts(row):
    """A split definition's tool plane and retained flag, or None when one did not read."""
    tool = row.get("splitting_tool") or {}
    geometry = tool.get("geometry") or {}
    origin, normal = geometry.get("origin_cm"), geometry.get("normal")
    if not tool.get("handle") or not _vec3(origin) or not _vec3(normal):
        return None
    return {"tool": {"name": tool.get("name"), "kind": tool.get("kind"), "x_cm": origin[0],
                     "normal": [abs(v) for v in normal]},
            "retained": {"extended": row.get("is_splitting_tool_extended")}}


def _split_tool(name, x_cm):
    """Whether split facts read the named construction plane at this world x."""
    return lambda got: (_alike(got["tool"], {"name": name, "kind": "construction_plane",
                                             "x_cm": x_cm, "normal": [1, 0, 0]}, 1e-6)
                        and got["retained"]["extended"] is True)


def _pieces(p):
    """model_inspect over the design: sorted solid volumes and the bounds, or None when partial."""
    mass = p.get("mass") or {}
    rows = mass.get("per_body")
    lo, hi = p.get("min_point"), p.get("max_point")
    if (p.get("kind") != "design" or p.get("units") != "mm" or not isinstance(rows, list)
            or mass.get("per_body_truncated") is not False or len(rows) != mass.get("per_body_count")
            or not isinstance(lo, dict) or not isinstance(hi, dict)
            or any(r.get("is_solid") is not True or r.get("lump_count") != 1
                   or not _num(r.get("volume")) for r in rows)):
        return None
    return {"volumes": sorted(r["volume"] for r in rows), "total": mass.get("volume"),
            "min": [lo.get(a) for a in "xyz"], "max": [hi.get(a) for a in "xyz"]}


def _pieces_read(label, volumes):
    """model_inspect: the control and the two pieces at these volumes inside the fixture's box."""
    return lambda p: _measured(label, _pieces(p), _pieces(p) is not None and _alike(
        _pieces(p), {"volumes": sorted(volumes), "total": 9000, "min": [0, 400, 0],
                     "max": [70, 420, 10]}, _BOX_TOL))


def _cut_faces(x):
    """find_geometry: the two coincident cut faces sit at world x, facing opposite ways."""
    def check(p):
        rows = p.get("matches") or []
        normals = sorted(round((m.get("normal") or [0])[0], 3) for m in rows)
        return _measured(f"cut faces at x {x}", [(m.get("position"), m.get("normal"), m.get("area"))
                                                 for m in rows],
                         p.get("match_count") == 18 and len(rows) == 2 and normals == [-1, 1]
                         and all(_alike(m.get("position"), [x, 410, 5], 0.001)
                                 and _near(m.get("area"), 200, 0.01) for m in rows))
    return check


def _split_rows():
    """Move a body split from plane FfSplitP1 to FfSplitP2 and back."""
    rows, write, read, close = _scratch_rows("ff_split_doc")
    feature = _named("ff_split_feat", "the split feature")
    count = "ff_split_count"
    cut = lambda x: read("find_geometry", lambda c: {"target": "", "kind": "planar_face",
                                                     "nearest_to": [x, 410, 5], "max_results": 2},
                         _cut_faces(x))
    volumes = lambda rows_: sorted(r["volume"] for r in rows_)
    shapes = lambda was, now: lambda b, a: (
        _alike(volumes(b), was, _SHAPE_TOL) and _alike(volumes(a), now, _SHAPE_TOL)
        and all(r["faces"] == 6 for r in b + a))
    control = lambda later: _control(read, "ff_split_ctl", _solid("ff_split_ctl_body"), later)

    _boxed(write, "FfSplitSk", (0, 400, 40, 420), 10, "ff_split_body")
    _boxed(write, "FfSplitCtl", (60, 400, 70, 410), 10, "ff_split_ctl_body")
    for name, offset in (("FfSplitP1", 10), ("FfSplitP2", 25)):
        write("model_construction", {"kind": "plane", "mode": "offset", "plane": "yz",
                                     "offset": offset, "name": name},
              lambda p, name=name: _datum("plane")(p) and _measured(
                  "plane name as asked", p.get("name"), p.get("name") == name))
    write("model_split", lambda c: {"split": "body", "split_plane": "FfSplitP1",
                                    "target": _ctx_get(c, "ff_split_body", "the body")},
          lambda p: _measured("split in two", {k: p.get(k) for k in (
              "split", "result_count", "feature", "result_bodies")},
              p.get("split") == "body" and p.get("result_count") == 2 and bool(p.get("feature"))),
          ("ff_split_feat", _recall("ff_split_feat", lambda p: p["feature"])))

    _keep(read, "model_inspect", _combine_inspect(), "ff_split_pieces", _pieces,
          _pieces_read("pieces as built", [1000, 2000, 6000]))
    cut(10)
    control(False)
    _keep(read, "design_get", _HISTORY, count, _count, _healthy_at_end)
    _rolled_read(write, read, feature, count, _defined(
        "split definition as built", "tools", _split_facts, _split_tool("FfSplitP1", 1.0),
        park="ff_split_def"))

    _edit(write, read, count, feature, "tools", lambda c: ["FfSplitP2"], _edited(
        "tools", "ff_split_feat", count, _split_facts, _split_tool("FfSplitP1", 1.0),
        _split_tool("FfSplitP2", 2.5), shapes([1, 2, 6], [1, 3, 5])))
    _rolled_read(write, read, feature, count, _defined(
        "split definition after the edit", "tools", _split_facts, _split_tool("FfSplitP2", 2.5),
        retained="ff_split_def"))
    read("model_inspect", _combine_inspect(), _pieces_read("pieces after the edit",
                                                           [1000, 3000, 5000]))
    cut(25)
    control(True)

    _edit(write, read, count, feature, "tools", lambda c: ["FfSplitP1"], _edited(
        "tools", "ff_split_feat", count, _split_facts, _split_tool("FfSplitP2", 2.5),
        _split_tool("FfSplitP1", 1.0), shapes([1, 3, 5], [1, 2, 6])))
    _rolled_read(write, read, feature, count, _defined(
        "split definition restored", "tools", _split_facts, _split_tool("FfSplitP1", 1.0),
        same="ff_split_def"))
    restored = lambda: (
        read("model_inspect", _combine_inspect(), lambda p: _pieces_read(
            "pieces restored", [1000, 2000, 6000])(p) and _unchanged(
                "ff_split_pieces", _pieces, 1e-6)(p)),
        cut(10), control(True))
    restored()

    _edit(write, read, count, feature, "tools", lambda c: ["FfSplitP1", "FfSplitP2"],
          _refused("Feature edit refused", "needs exactly one item for action='tools' (got 2)",
                   "The marker was restored at"))
    restored()
    read("design_get", _HISTORY, _history(count))
    close()
    return rows


# --- SilhouetteSplitFeature: view direction ------------------------------------------------------

def _silhouette_facts(row):
    """A silhouette split's view axis with its retained target and operation, or None."""
    view, target = row.get("view_direction") or {}, row.get("target_body") or {}
    direction = (view.get("geometry") or {}).get("direction")
    if not view.get("handle") or not _vec3(direction):
        return None
    return {"view": {"name": view.get("name"), "kind": view.get("kind"),
                     "axis": [abs(v) for v in direction]},
            "retained": {"target_body": target.get("name"), "operation": row.get("operation")}}


def _view(name, axis):
    """Whether silhouette facts read this origin axis over the saved cylinder."""
    return lambda got: (_alike(got["view"], {"name": name, "kind": "construction_axis",
                                             "axis": axis}, 1e-6)
                        and got["retained"]["target_body"] == _RECALL.get("ff_sil_body")
                        and got["retained"]["operation"] == 0)


def _line_edges(p):
    """find_geometry line edges as sorted direction, length and plan position rows, or None."""
    rows = p.get("matches")
    if not isinstance(rows, list) or not rows or p.get("returned") != p.get("match_count"):
        return None
    out = []
    for m in rows:
        direction, at = m.get("direction"), m.get("position")
        if not _vec3(direction) or not _vec3(at) or not _num(m.get("length")):
            return None
        upright = abs(direction[2]) > 0.999
        out.append([[round(abs(v), 3) for v in direction], round(m["length"], 3),
                    [round(at[0], 3), round(at[1], 3)] if upright else None])
    return sorted(out, key=repr)


def _silhouette_rows():
    """Turn a cylinder's silhouette split from the X view to the Y view and back."""
    rows, write, read, close = _scratch_rows("ff_sil_doc")
    feature = _named("ff_sil_feat", "the silhouette split")
    count = "ff_sil_count"
    body = lambda c, **more: {"target": _ctx_get(c, "ff_sil_body", "the cylinder"), **more}
    cylinder = _body_reads("silhouette cylinder", (0, 590, 0), (20, 610, 20), 6283.19, 1884.956)
    same = lambda before, after: (
        _shape_is(_shape_of(before, "ff_sil_body"), 6.28319, 18.84956, 6)
        and _shape_is(_shape_of(after, "ff_sil_body"), 6.28319, 18.84956, 6)
        and bool(_shape_of(before, "ff_sil_ctl_body"))
        and _shape_of(before, "ff_sil_ctl_body") == _shape_of(after, "ff_sil_ctl_body"))
    control = lambda later: _control(read, "ff_sil_ctl", _solid("ff_sil_ctl_body"), later)

    write("sketch_create", {"plane": "xy", "name": "FfSilSk"})
    write("sketch_add_geometry", {"sketch_name": "FfSilSk", "geometry": [
        {"kind": "circle", "cx": 10, "cy": 600, "radius": 10}]})
    write("model_extrude", {"sketch_name": "FfSilSk", "profile_index": 0, "distance": 20,
                            "operation": "new"}, _extruded,
          ("ff_sil_body", _recall("ff_sil_body", lambda p: p["result_bodies"][0])))
    _boxed(write, "FfSilCtl", (40, 590, 50, 600), 10, "ff_sil_ctl_body")
    write("model_split", lambda c: body(c, split="silhouette", view_direction="x"),
          lambda p: _measured("silhouette split along X", {k: p.get(k) for k in (
              "split", "feature", "faces_before", "faces_after")},
              p.get("split") == "silhouette" and p.get("faces_after") == 6
              and bool(p.get("feature"))),
          ("ff_sil_feat", _recall("ff_sil_feat", lambda p: p["feature"])))

    _keep(read, "model_inspect", _solid("ff_sil_body"), "ff_sil_solid", _body_facts, cylinder)
    read("find_geometry", lambda c: body(c, max_results=1), _topology("X view", 16))
    _keep(read, "find_geometry", lambda c: body(c, **_EDGES), "ff_sil_lines", _line_edges)
    control(False)
    _keep(read, "design_get", _HISTORY, count, _count, _healthy_at_end)
    _rolled_read(write, read, feature, count, _defined(
        "silhouette definition as built", "axis", _silhouette_facts, _view("X", [1, 0, 0]),
        park="ff_sil_def"))

    _edit(write, read, count, feature, "axis", lambda c: ["y"], _edited(
        "axis", "ff_sil_feat", count, _silhouette_facts, _view("X", [1, 0, 0]),
        _view("Y", [0, 1, 0]), same))
    _rolled_read(write, read, feature, count, _defined(
        "silhouette definition after the edit", "axis", _silhouette_facts, _view("Y", [0, 1, 0]),
        retained="ff_sil_def"))
    read("model_inspect", _solid("ff_sil_body"), cylinder)
    read("find_geometry", lambda c: body(c, max_results=1), _topology("Y view", 14))
    read("find_geometry", lambda c: body(c, **_EDGES),
         lambda p: _measured("straight edges differ from the X view",
                             {"now": _line_edges(p), "was": _RECALL.get("ff_sil_lines")},
                             _line_edges(p) is not None and "ff_sil_lines" in _RECALL
                             and _line_edges(p) != _RECALL["ff_sil_lines"]))
    control(True)

    _edit(write, read, count, feature, "axis", lambda c: ["x"], _edited(
        "axis", "ff_sil_feat", count, _silhouette_facts, _view("Y", [0, 1, 0]),
        _view("X", [1, 0, 0]), same))
    _rolled_read(write, read, feature, count, _defined(
        "silhouette definition restored", "axis", _silhouette_facts, _view("X", [1, 0, 0]),
        same="ff_sil_def"))
    restored = lambda: (
        read("model_inspect", _solid("ff_sil_body"), _as_built("ff_sil_solid", cylinder)),
        read("find_geometry", lambda c: body(c, max_results=1), _topology("X view again", 16)),
        read("find_geometry", lambda c: body(c, **_EDGES), _unchanged("ff_sil_lines", _line_edges)),
        control(True))
    restored()

    _edit(write, read, count, feature, "plane", lambda c: ["xz"],
          _refused("does not support action='plane'", "Supported: axis"))
    restored()
    read("design_get", _HISTORY, _history(count))
    close()
    return rows


# --- OffsetFacesFeature and the rule fillet: face operands ---------------------------------------

def _face_facts(field, *retained):
    """A reader of one face-list definition field beside the named retained fields."""
    def facts(row):
        faces = row.get(field)
        if not isinstance(faces, list) or not faces:
            return None
        out = []
        for face in faces:
            geometry = face.get("geometry") or {}
            if (not face.get("handle") or face.get("kind") != "face"
                    or not _vec3(geometry.get("normal")) or not _num(geometry.get("area"))):
                return None
            out.append({"normal": geometry["normal"], "area": geometry["area"]})
        return {"faces": out, "retained": {key: row.get(key) for key in retained}}
    return facts


def _faces(*want):
    """Whether face facts read these (normal, cm2) faces in order."""
    return lambda got: _alike(got["faces"], [{"normal": list(n), "area": a} for n, a in want],
                              0.0001)


_UP, _DOWN, _LEFT = ((0, 0, 1), 9.0), ((0, 0, -1), 9.0), ((-1, 0, 0), 6.0)


def _offset_rows():
    """Widen an offset-faces feature from the top face to the top and one side, and back."""
    rows, write, read, close = _scratch_rows("ff_off_doc")
    feature = _named("ff_off_feat", "the offset-faces feature")
    count, facts = "ff_off_count", _face_facts("input_faces", "distance")
    body = lambda c, **more: {"target": _ctx_get(c, "ff_off_body", "the box"), **more}
    built = _body_reads("offset top", (0, 1000, 0), (30, 1030, 24), 21600, 4680)
    control = lambda later: _control(read, "ff_off_ctl", _solid("ff_off_ctl_body"), later)
    ctl_same = lambda b, a: (bool(_shape_of(b, "ff_off_ctl_body"))
                             and _shape_of(b, "ff_off_ctl_body") == _shape_of(a, "ff_off_ctl_body"))
    grown = lambda b, a: (_shape_is(_shape_of(b, "ff_off_body"), 21.6, 46.8, 6)
                          and _shape_is(_shape_of(a, "ff_off_body"), 24.48, 51.12, 6)
                          and ctl_same(b, a))
    shrunk = lambda b, a: (_shape_is(_shape_of(b, "ff_off_body"), 24.48, 51.12, 6)
                           and _shape_is(_shape_of(a, "ff_off_body"), 21.6, 46.8, 6)
                           and ctl_same(b, a))

    _boxed(write, "FfOffSk", (0, 1000, 30, 1030), 20, "ff_off_body")
    _boxed(write, "FfOffCtl", (60, 1000, 70, 1010), 10, "ff_off_ctl_body")
    _acquire(read, "ff_off_body", "ff_off_seed", _FACES, (15, 1015, 20), normal=(0, 0, 1), area=900)
    write("model_offset_face", lambda c: {"faces": [_ctx_get(c, "ff_off_seed", "top face")],
                                          "distance": 4},
          lambda p: _measured("top face offset 4 mm", {k: p.get(k) for k in (
              "offset", "feature", "volume_delta_cm3")},
              p.get("offset") is True and bool(p.get("feature"))
              and _near(p.get("volume_delta_cm3"), 3.6, _SHAPE_TOL)),
          ("ff_off_feat", _recall("ff_off_feat", lambda p: p["feature"])))

    _keep(read, "model_inspect", _solid("ff_off_body"), "ff_off_solid", _body_facts, built)
    read("find_geometry", lambda c: body(c, max_results=1), _topology("offset top", 18))
    control(False)
    _keep(read, "design_get", _HISTORY, count, _count, _healthy_at_end)
    _rolled_read(write, read, feature, count, _defined(
        "offset definition as built", "inputs", facts, _faces(_UP), park="ff_off_def"))

    _acquire(read, "ff_off_body", "ff_off_top", _FACES, (15, 1015, 24), normal=(0, 0, 1), area=900)
    _acquire(read, "ff_off_body", "ff_off_side", _FACES, (0, 1015, 12), normal=(-1, 0, 0), area=720)
    _edit(write, read, count, feature, "inputs",
          lambda c: [_ctx_get(c, "ff_off_top", "top face"), _ctx_get(c, "ff_off_side", "side face")],
          _edited("inputs", "ff_off_feat", count, facts, _faces(_UP), _faces(_UP, _LEFT), grown))
    _rolled_read(write, read, feature, count, _defined(
        "offset definition after the edit", "inputs", facts, _faces(_UP, _LEFT),
        retained="ff_off_def"))
    read("model_inspect", _solid("ff_off_body"),
         _body_reads("offset top and side", (-4, 1000, 0), (30, 1030, 24), 24480, 5112))
    read("find_geometry", lambda c: body(c, max_results=1), _topology("offset top and side", 18))
    read("design_get", _HISTORY, _history(count))
    control(True)

    _acquire(read, "ff_off_body", "ff_off_back", _FACES, (13, 1015, 24), normal=(0, 0, 1),
             area=1020)
    _edit(write, read, count, feature, "inputs", lambda c: [_ctx_get(c, "ff_off_back", "top face")],
          _edited("inputs", "ff_off_feat", count, facts, _faces(_UP, _LEFT), _faces(_UP), shrunk))
    _rolled_read(write, read, feature, count, _defined(
        "offset definition restored", "inputs", facts, _faces(_UP), same="ff_off_def"))
    restored = lambda: (
        read("model_inspect", _solid("ff_off_body"), _as_built("ff_off_solid", built)),
        read("find_geometry", lambda c: body(c, max_results=1), _topology("offset restored", 18)),
        control(True))
    restored()

    _edit(write, read, count, feature, "inputs", lambda c: [_ctx_get(c, "ff_off_back", "top face")],
          _refused("'mode' is unused for action='inputs'; remove it."), mode="flipped")
    restored()
    read("design_get", _HISTORY, _history(count))
    close()
    return rows


def _mirrored(key):
    """model_inspect: the banked centre of mass mirrored about the box's mid height, z 10 mm."""
    def check(p):
        was = (_RECALL.get(key) or {}).get("center_of_mass")
        now = (_body_facts(p) or {}).get("center_of_mass")
        return _measured("centre of mass mirrored in z", {"was": was, "now": now},
                         _vec3(was) and _vec3(now) and abs(was[2] - 10) > 0.01
                         and _alike(now, [was[0], was[1], 20 - was[2]], 0.001))
    return check


def _plan_faces(p):
    """find_geometry planar faces as sorted area and position rows, or None when cut."""
    rows = p.get("matches")
    if not isinstance(rows, list) or not rows or p.get("returned") != p.get("match_count"):
        return None
    return sorted([m.get("area"), m.get("position")] for m in rows)


def _rule_rows():
    """Move a rule fillet from the edges of the top face to the edges of the bottom face."""
    rows, write, read, close = _scratch_rows("ff_rule_doc")
    feature = _named("ff_rule_feat", "the rule fillet")
    count, facts = "ff_rule_count", _face_facts("rule_faces", "rule_type", "radius")
    body = lambda c, **more: {"target": _ctx_get(c, "ff_rule_body", "the box"), **more}
    built = _body_reads("rule fillet", (0, 500, 0), (30, 530, 20), 17778.58, 4040.389)
    control = lambda later: _control(read, "ff_rule_ctl", _solid("ff_rule_ctl_body"), later)
    moved = lambda b, a: (
        _shape_is(_shape_of(b, "ff_rule_body"), 17.77858, 40.40389, 10)
        and _shape_is(_shape_of(a, "ff_rule_body"), 17.77858, 40.40389, 10)
        and bool(_shape_of(b, "ff_rule_ctl_body"))
        and _shape_of(b, "ff_rule_ctl_body") == _shape_of(a, "ff_rule_ctl_body"))
    top = lambda key: _acquire(read, "ff_rule_body", key, _FACES, (15, 515, 20), normal=(0, 0, 1),
                               area=900)

    _boxed(write, "FfRuleSk", (0, 500, 30, 530), 20, "ff_rule_body")
    _boxed(write, "FfRuleCtl", (60, 500, 70, 510), 10, "ff_rule_ctl_body")
    top("ff_rule_seed")
    write("model_fillet", lambda c: {"fillet_type": "rule", "radius": 3,
                                     "faces": [_ctx_get(c, "ff_rule_seed", "top face")]},
          lambda p: _measured("rule fillet on the top face", {k: p.get(k) for k in (
              "filleted", "feature", "fillet_type", "rule", "radius", "topology")},
              p.get("filleted") is True and p.get("fillet_type") == "rule"
              and p.get("rule") == "all_edges" and _near(p.get("radius"), 3, 1e-6)
              and bool(p.get("feature"))),
          ("ff_rule_feat", _recall("ff_rule_feat", lambda p: p["feature"])))

    _keep(read, "model_inspect", _solid("ff_rule_body"), "ff_rule_solid", _body_facts, built)
    read("find_geometry", lambda c: body(c, max_results=1), _topology("rule fillet", 30))
    _keep(read, "find_geometry", lambda c: body(c, **_FACES), "ff_rule_faces", _plan_faces)
    control(False)
    _keep(read, "design_get", _HISTORY, count, _count, _healthy_at_end)
    _rolled_read(write, read, feature, count, _defined(
        "rule fillet definition as built", "inputs", facts, _faces(_UP), park="ff_rule_def"))

    _acquire(read, "ff_rule_body", "ff_rule_low", _FACES, (15, 515, 0), normal=(0, 0, -1),
             area=900)
    _edit(write, read, count, feature, "inputs", lambda c: [_ctx_get(c, "ff_rule_low", "bottom face")],
          _edited("inputs", "ff_rule_feat", count, facts, _faces(_UP), _faces(_DOWN), moved))
    _rolled_read(write, read, feature, count, _defined(
        "rule fillet definition after the edit", "inputs", facts, _faces(_DOWN),
        retained="ff_rule_def"))
    read("model_inspect", _solid("ff_rule_body"),
         lambda p: built(p) and _mirrored("ff_rule_solid")(p))
    read("find_geometry", lambda c: body(c, max_results=1), _topology("rule fillet moved", 30))
    read("find_geometry", lambda c: body(c, **_FACES),
         lambda p: _measured("planar faces differ from the first read",
                             {"now": _plan_faces(p), "was": _RECALL.get("ff_rule_faces")},
                             _plan_faces(p) is not None and "ff_rule_faces" in _RECALL
                             and not _alike(_plan_faces(p), _RECALL["ff_rule_faces"], 0.01)))
    control(True)

    top("ff_rule_back")
    _edit(write, read, count, feature, "inputs", lambda c: [_ctx_get(c, "ff_rule_back", "top face")],
          _edited("inputs", "ff_rule_feat", count, facts, _faces(_DOWN), _faces(_UP), moved))
    _rolled_read(write, read, feature, count, _defined(
        "rule fillet definition restored", "inputs", facts, _faces(_UP), same="ff_rule_def"))
    restored = lambda: (
        read("model_inspect", _solid("ff_rule_body"), _as_built("ff_rule_solid", built)),
        read("find_geometry", lambda c: body(c, max_results=1), _topology("rule restored", 30)),
        read("find_geometry", lambda c: body(c, **_FACES),
             _unchanged("ff_rule_faces", _plan_faces, 0.001)),
        control(True))
    restored()

    _edit(write, read, count, feature, "inputs", lambda c: [_ctx_get(c, "ff_rule_back", "top face")],
          _refused("'set_index' is unused for action='inputs'; remove it."), set_index=0)
    restored()
    read("design_get", _HISTORY, _history(count))
    close()
    return rows


# --- FilletFeature and ChamferFeature: one edge set's edges --------------------------------------

def _edge_set_facts(set_type):
    """A reader of the one edge set a definition lists: its upright edges and retained fields."""
    def facts(row):
        sets = row.get("edge_sets")
        if not isinstance(sets, list) or len(sets) != 1 or sets[0].get("type") != set_type:
            return None
        edges = []
        for edge in sets[0].get("edges") or []:
            ends = (edge.get("geometry") or {}).get("ends_cm")
            if (not edge.get("handle") or not isinstance(ends, list) or len(ends) != 2
                    or not all(_vec3(end) for end in ends)
                    or not _alike(ends[0][:2], ends[1][:2], 1e-6)
                    or not _near(abs(ends[0][2] - ends[1][2]), 2.0, 1e-6)):
                return None
            edges.append([round(ends[0][0], 6), round(ends[0][1], 6)])
        if not edges:
            return None
        return {"edges": sorted(edges),
                "retained": {k: v for k, v in sets[0].items() if k != "edges"}}
    return facts


def _edges(size, text, *want):
    """Whether edge-set facts read exactly the upright edges at these plan positions in cm."""
    return lambda got: (_alike(got["edges"], sorted(list(xy) for xy in want), 1e-6)
                        and got["retained"].get("index") == 0
                        and isinstance(got["retained"].get("is_tangent_chain"), bool)
                        and isinstance(got["retained"].get(size), str)
                        and (text is None or got["retained"][size] == text))


def _edge_story(key, y, feature, body, ctl, control, fixture, size, text, one, two):
    """Rows moving one edge set from the box corner at x 0 to both corners at x 30, and back."""
    rows, write, read, close = _scratch_rows(key + "_doc")
    count = key + "_count"
    facts = _edge_set_facts("ConstantRadiusFilletEdgeSet" if size == "radius"
                            else "EqualDistanceChamferEdgeSet")
    target = lambda c, **more: {"target": body(c), **more}
    was = _edges(size, text, (0, y / 10))
    now = _edges(size, text, (3, y / 10), (3, y / 10 + 3))
    built = _body_reads(key + " one edge", (0, y, 0), (30, y + 30, 20), one[0] * 1000,
                        one[1] * 100)
    spread = _body_reads(key + " two edges", (0, y, 0), (30, y + 30, 20), two[0] * 1000,
                         two[1] * 100)
    corner = lambda slot, x, dy: _acquire_edge(read, target, slot, x, y + dy)
    ctl_same = lambda b, a: bool(_shape_of(b, ctl)) and _shape_of(b, ctl) == _shape_of(a, ctl)
    out = lambda b, a: (_shape_is(_shape_of(b, key + "_body"), *one, 7)
                        and _shape_is(_shape_of(a, key + "_body"), *two, 8) and ctl_same(b, a))
    back = lambda b, a: (_shape_is(_shape_of(b, key + "_body"), *two, 8)
                         and _shape_is(_shape_of(a, key + "_body"), *one, 7) and ctl_same(b, a))
    guard = lambda later: _control(read, key + "_ctl", control, later)

    fixture(write, read, corner)
    _keep(read, "model_inspect", lambda c: _inspect(body(c)), key + "_solid", _body_facts, built)
    read("find_geometry", lambda c: target(c, max_results=1), _topology(key + " one edge", 22))
    guard(False)
    _keep(read, "design_get", _HISTORY, count, _count, _healthy_at_end)
    _rolled_read(write, read, feature, count, _defined(
        key + " definition as built", "inputs", facts, was, park=key + "_def",
        call="set_index=0"))

    corner(key + "_e1", 30, 0)
    corner(key + "_e2", 30, 30)
    _edit(write, read, count, feature, "inputs",
          lambda c: [_ctx_get(c, key + "_e1", "edge"), _ctx_get(c, key + "_e2", "edge")],
          _edited("inputs", key + "_feat", count, facts, was, now, out), set_index=0)
    _rolled_read(write, read, feature, count, _defined(
        key + " definition after the edit", "inputs", facts, now, retained=key + "_def",
        call="set_index=0"))
    read("model_inspect", lambda c: _inspect(body(c)), spread)
    read("find_geometry", lambda c: target(c, max_results=1), _topology(key + " two edges", 26))
    read("design_get", _HISTORY, _history(count))
    guard(True)

    corner(key + "_e0", 0, 0)
    _edit(write, read, count, feature, "inputs", lambda c: [_ctx_get(c, key + "_e0", "edge")],
          _edited("inputs", key + "_feat", count, facts, now, was, back), set_index=0)
    _rolled_read(write, read, feature, count, _defined(
        key + " definition restored", "inputs", facts, was, same=key + "_def",
        call="set_index=0"))
    restored = lambda: (
        read("model_inspect", lambda c: _inspect(body(c)), _as_built(key + "_solid", built)),
        read("find_geometry", lambda c: target(c, max_results=1),
             _topology(key + " restored", 22)),
        guard(True))
    restored()
    return rows, write, read, close, count, restored


def _acquire_edge(read, target, key, x, y):
    """A find_geometry read saving the one 20 mm upright edge at plan position (x, y) mm."""
    check, take = _pick("line_edge", (x, y, None), length=20, along=(0, 0, 1))
    read("find_geometry", lambda c: target(c, **_EDGES), check, (key, take))


def _fillet_rows():
    """Move a constant-radius fillet's edge set from one upright edge to two others, and back."""
    feature, body = _named("ff_fil_feat", "the fillet"), _named("ff_fil_body", "the box")

    def fixture(write, read, corner):
        _boxed(write, "FfFilSk", (0, 400, 30, 430), 20, "ff_fil_body")
        _boxed(write, "FfFilCtl", (60, 400, 70, 410), 10, "ff_fil_ctl_body")
        corner("ff_fil_seed", 0, 0)
        write("model_fillet", lambda c: {"edges": [_ctx_get(c, "ff_fil_seed", "edge")],
                                         "radius": 4},
              lambda p: _measured("4 mm fillet on one edge", {k: p.get(k) for k in (
                  "filleted", "feature", "fillet_type", "edges_cut", "tangent_chain")},
                  p.get("filleted") is True and p.get("fillet_type") == "constant"
                  and p.get("edges_cut") == 1 and p.get("tangent_chain") is True
                  and bool(p.get("feature"))),
              ("ff_fil_feat", _recall("ff_fil_feat", lambda p: p["feature"])))

    rows, write, read, close, count, restored = _edge_story(
        "ff_fil", 400, feature, body, "ff_fil_ctl_body", _solid("ff_fil_ctl_body"), fixture,
        "radius", None, (17.93133, 41.58796), (17.86265, 41.17593))
    _edit(write, read, count, feature, "axis", lambda c: ["z"],
          _refused("does not support action='axis'", "Supported: inputs"))
    restored()
    read("design_get", _HISTORY, _history(count))
    close()
    return rows


# No public creator builds a chamfer from createInput2 and an equal-distance edge set.
_CHAMFER_FIXTURE = '''
import json

import adsk.core
import adsk.fusion


def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if (design is None or app.activeDocument.isSaved
            or design.designType != adsk.fusion.DesignTypes.ParametricDesignType
            or design.timeline.count != 0 or design.rootComponent.bRepBodies.count != 0
            or design.rootComponent.occurrences.count != 0):
        print(json.dumps({"built": False}))
        return
    root = design.rootComponent
    real = adsk.core.ValueInput.createByReal

    def box(name, x0, y0, w, d, h):
        sketch = root.sketches.add(root.xYConstructionPlane)
        sketch.name = name + "Sk"
        at = lambda x, y: sketch.modelToSketchSpace(adsk.core.Point3D.create(x, y, 0))
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(at(x0, y0), at(x0 + w, y0 + d))
        extrude = root.features.extrudeFeatures.addSimple(
            sketch.profiles.item(0), real(h),
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        body = extrude.bodies.item(0)
        body.name = name
        return body

    def middle(edge):
        low, high = edge.boundingBox.minPoint, edge.boundingBox.maxPoint
        return ((low.x + high.x) / 2, (low.y + high.y) / 2, (low.z + high.z) / 2)

    body = box("FfChamBody", 0, 70, 3, 3, 2)
    control = box("FfChamCtl", 6, 70, 1, 1, 1)
    edge = min(body.edges, key=lambda e: sum(
        (a - b) ** 2 for a, b in zip(middle(e), (0, 70, 1))))
    edges = adsk.core.ObjectCollection.create()
    edges.add(edge)
    chamfer_input = root.features.chamferFeatures.createInput2()
    chamfer_input.chamferEdgeSets.addEqualDistanceChamferEdgeSet(edges, real(0.15), True)
    feature = root.features.chamferFeatures.add(chamfer_input)
    feature.name = "FfChamfer"
    owned = []
    for parameter in design.allParameters:
        model = adsk.fusion.ModelParameter.cast(parameter)
        if model and model.createdBy and model.createdBy.name == feature.name:
            owned.append({"name": model.name, "role": model.role,
                          "expression": model.expression})
    print(json.dumps({"built": True, "feature": feature.name, "body": body.name,
                      "control": control.name, "parameters": owned,
                      "timeline_count": design.timeline.count}))
'''


def _distance_parameter(p):
    """The script's one chamfer parameter with role Distance; parks the names it printed."""
    hits = [row for row in p.get("parameters") or [] if row.get("role") == "Distance"]
    if len(hits) != 1 or not hits[0].get("name"):
        raise AssertionError(f"no single Distance parameter: {p.get('parameters')}")
    _RECALL.update(ff_cham_feat=p.get("feature"), ff_cham_body=p.get("body"),
                   ff_cham_ctl_body=p.get("control"))
    return hits[0]["name"]


def _chamfer_rows():
    """Move an equal-distance chamfer's edge set from one upright edge to two others, and back."""
    feature, body = (lambda c: _RECALL["ff_cham_feat"]), (lambda c: _RECALL["ff_cham_body"])

    def fixture(write, read, corner):
        write("sys_execute_script", {"script": _CHAMFER_FIXTURE, "read_only": False},
              lambda p: _measured("chamfer fixture names", p, isinstance(p, dict)
                                  and p.get("built") is True and p.get("feature") == "FfChamfer"
                                  and p.get("body") == "FfChamBody"
                                  and p.get("control") == "FfChamCtl"
                                  and p.get("timeline_count") == 5
                                  and bool(_distance_parameter(p))),
              ("ff_cham_param", _recall("ff_cham_param", _distance_parameter)))
        write("param_set", lambda c: {"name": _ctx_get(c, "ff_cham_param", "chamfer distance"),
                                      "expression": "2.5 mm"},
              lambda p: _measured("chamfer distance set to 2.5 mm", {k: p.get(k) for k in (
                  "set", "created", "name", "after")},
                  p.get("set") is True and p.get("created") is False
                  and p.get("name") == _RECALL.get("ff_cham_param")
                  and (p.get("after") or {}).get("expression") == "2.5 mm"))

    rows, write, read, close, count, restored = _edge_story(
        "ff_cham", 700, feature, body, "ff_cham_ctl_body",
        lambda c: _inspect(_RECALL["ff_cham_ctl_body"]),
        fixture, "distance", "2.5 mm", (17.9375, 41.64461), (17.875, 41.28921))
    _edit(write, read, count, feature, "inputs", lambda c: [_ctx_get(c, "ff_cham_e0", "edge")],
          _refused("Feature edit refused", "'set_index' 1 is out of range for 1 sets",
                   "The marker was restored at"), set_index=1)
    restored()
    read("design_get", _HISTORY, _history(count))
    close()
    return rows


def feature_finishing_rows():
    """The six operand-edit stories, in order, as one list of sweep rows."""
    return (_split_rows() + _silhouette_rows() + _offset_rows() + _fillet_rows() + _rule_rows()
            + _chamfer_rows())
