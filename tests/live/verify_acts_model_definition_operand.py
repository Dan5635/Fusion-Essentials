# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Hole definitions and placed datum operand checks for model acts."""

import math

from verify_core import (
    _RECALL, _ctx_get, _datum, _document_closed, _drilled, _extruded, _face_up_at, _fg, _filleted, _home_address, _home_document, _made_component, _matched, _measured, _moved_occurrence, _captured, _near, _new_document, _num, _param_added, _param_set_to, _recall, _refused)





from verify_acts_model_combine_revolve import (
    _combine_inspect, _combine_pin)

def _hole_definition(extent, units, tapped=False):
    """Check native hole extent and hidden child independently of the drilling response."""
    def check(p):
        row = p.get("definition") or {}
        thread = row.get("thread") or {}
        factor = 1 if units == "mm" else 1 / 25.4
        good = (row.get("type") == "HoleFeature" and row.get("component") == "DefinitionBench"
                and row.get("units") == units and row.get("extent") == extent
                and row.get("tapped") is tapped and row.get("thread_present") is tapped
                and row.get("depth_applicable") is (extent == "blind"))
        if tapped:
            info, child_info = row.get("tapped_hole_info") or {}, thread.get("thread_info") or {}
            full = thread.get("full_length")
            length, offset = thread.get("length"), thread.get("offset")
            numeric = (length is None and offset is None if full is True else
                       isinstance(length, (int, float)) and length > 0
                       and isinstance(offset, (int, float)) and offset >= 0)
            good = (good and _near(row.get("depth"), 22.225 * factor, 0.000001)
                    and row.get("diameter_parameter_applicable") is False
                    and row.get("diameter_parameter") is None
                    and info.get("designation") == "3/8-16 UNC"
                    and all(isinstance(info.get(key), str) and bool(info[key])
                            and child_info.get(key) == info[key]
                            for key in ("designation", "thread_type", "thread_class"))
                    and thread.get("type") == "ThreadFeature" and isinstance(full, bool)
                    and thread.get("length_applicable") is (not full)
                    and thread.get("offset_applicable") is (not full)
                    and isinstance(thread.get("modeled"), bool) and numeric)
            if units == "in":
                prior = (_RECALL.get("def_tap_mm") or {}).get("thread") or {}
                good = (good and child_info == prior.get("thread_info")
                        and all(thread.get(key) == prior.get(key) for key in
                                ("full_length", "modeled", "length_applicable", "offset_applicable"))
                        and all(thread.get(key) is None if prior.get(key) is None else
                                _near(thread.get(key), prior[key] / 25.4, 0.000001)
                                for key in ("length", "offset")))
        else:
            good = (good and row.get("depth") is None and row.get("thread") is None
                    and _near(row.get("diameter_parameter"), 4 * factor, 0.000001)
                    and row.get("diameter_parameter_applicable") is True)
        return _measured("hole definition and actual child in " + units, row, good)
    return check


def _cosmetic_resize(before, after):
    """The cosmetic reply's radius row, `before` then `after` mm; after None accepts a read radius or the not-measured note."""
    def check(p):
        rows, note = p.get("cylinder_radii") or [], p.get("note") or ""
        row = rows[0] if len(rows) == 1 else {}
        read = (_near(row.get("after"), after, .0001) if after is not None
                else _num(row.get("after")) or "was not measured" in note)
        change = row.get("change")
        return _measured("cosmetic thread reports its cylinder radius before and after", rows,
                         p.get("modeled") is False and p.get("units") == "mm"
                         and _near(row.get("before"), before, .000001) and read
                         and (change is None or _near(change, row["after"] - row["before"], .000002))
                         and "may resize" not in note)
    return check


def _thread_ref(park=None):
    """Save the thread's address; with `park`, also park the one radius its reply read after it."""
    def take(p):
        if park:
            rows = p.get("cylinder_radii") or []
            _RECALL[park] = rows[0].get("after") if len(rows) == 1 else None
        return "DefinitionPost/" + p["feature"]
    return take


def _cosmetic_reread(key):
    """find_geometry: the one face found reads the radius parked under `key`, when one was reported."""
    def check(p):
        reported, ms = _RECALL.get(key, "unsaved"), p.get("matches") or []
        return _measured("find_geometry re-reads the cosmetic radius the reply reported",
                         {"reported": reported, "matches": ms[:1]},
                         _matched(1, "cylinder_face")(p) and reported != "unsaved"
                         and (reported is None or _near(ms[0].get("radius"), reported, .0001)))
    return check


def _thread_definition(full, units):
    """Check standalone full/partial thread metadata without inferring full-thread length."""
    def check(p):
        row = p.get("definition") or {}
        info = row.get("thread_info") or {}
        factor = 1 if units == "mm" else 1 / 25.4
        lengths = (row.get("length") is None and row.get("offset") is None if full else
                   _near(row.get("length"), 12 * factor, 0.000001)
                   and _near(row.get("offset"), 2 * factor, 0.000001))
        return _measured("standalone thread definition in " + units, row,
                         row.get("type") == "ThreadFeature" and row.get("component") == "DefinitionPost"
                         and row.get("units") == units and row.get("modeled") is False
                         and row.get("full_length") is full
                         and row.get("length_applicable") is (not full)
                         and row.get("offset_applicable") is (not full) and lengths
                         and info.get("designation") == ("M6x1" if full else "M10x1.5")
                         and info.get("thread_class") == "6g"
                         and info.get("thread_type") == "ISO Metric profile"
                         and info.get("internal") is False)
    return check


def _definition_doc_state(p):
    """The active document identity and readable modified flag for a paired read check."""
    modified = (p.get("active") or {}).get("is_modified")
    if not isinstance(modified, bool):
        raise AssertionError("document modified state did not read")
    return {"document_handle": _home_address(p), "is_modified": modified}


def _thread_visibility(p):
    """Read the complete single-post body visibility without transient handles."""
    tree = p["tree"]
    node = tree["tree"]
    bodies = node.get("bodies") or []
    if (tree.get("truncated") is not False or node.get("body_count") != 1
            or node.get("child_count") != 0 or len(bodies) != 1
            or any(not isinstance(row.get(key), bool) for row in bodies
                   for key in ("visible", "is_solid"))):
        raise AssertionError("post visibility was unreadable or incomplete")
    return [{key: row[key] for key in ("name", "visible", "is_solid")} for row in bodies]


def _tapped_created_ref(key, component="DefinitionBench"):
    """Retain the actual creation disclosure and return its scoped feature reference."""
    def capture(p):
        _RECALL[key] = p
        return component + "/" + p["feature"]
    return capture


def _tapped_control_definition(key, full=None, extent="blind", modeled=False, component="DefinitionBench"):
    """Compare the tapped-hole disclosure with its independent native definition reader."""
    def check(p):
        row, made = p.get("definition") or {}, _RECALL.get(key) or {}
        child = row.get("thread") or {}
        info = child.get("thread_info") or {}
        mapping = {"thread_full_length": "full_length", "thread_length_applicable": "length_applicable",
                   "thread_offset_applicable": "offset_applicable", "modeled": "modeled"}
        good = (row.get("type") == "HoleFeature" and row.get("component") == component
                and row.get("extent") == extent and row.get("depth_applicable") is (extent == "blind")
                and (_near(row.get("depth"), 22.225, 0.000001) if extent == "blind" else row.get("depth") is None)
                and row.get("tapped") is True and row.get("thread_present") is True
                and row.get("diameter_parameter") is None
                and row.get("diameter_parameter_applicable") is False
                and row.get("tapped_hole_info") == info and info.get("internal") is True
                and row.get("feature") == made.get("feature")
                and row.get("units") == made.get("units") == "mm"
                and info.get("designation") == made.get("tapped") == "3/8-16 UNC"
                and info.get("thread_type") == made.get("thread_type") == "ANSI Unified Screw Threads"
                and isinstance(info.get("thread_class"), str) and bool(info["thread_class"])
                and info.get("thread_class") == made.get("thread_class")
                and isinstance(child.get("full_length"), bool) and child.get("modeled") is modeled
                and all(key in made and made[key] == child.get(value) for key, value in mapping.items())
                and all(key in made and (made[key] is None if child.get(value) is None else
                        _near(made[key], child[value], 0.000001))
                        for key, value in (("thread_length", "length"), ("thread_offset", "offset"))))
        if full is not None:
            good = (good and info.get("thread_class") == "2B" and child.get("full_length") is full
                    and child.get("length_applicable") is (not full)
                    and child.get("offset_applicable") is (not full)
                    and (child.get("length") is None and child.get("offset") is None if full else
                         _near(child.get("length"), 12, 0.000001)
                         and _near(child.get("offset"), 2, 0.000001)))
        return _measured("tapped controls and actual creation disclosure", row, good)
    return check


def _tapped_geometry(p):
    """Capture the complete coupon face/edge measurements without transient handles."""
    matches = p.get("matches") or []
    if not matches or p.get("match_count") != len(matches) or p.get("returned") != len(matches):
        raise AssertionError("tapped coupon geometry acquisition was empty or capped")
    return [{key: value for key, value in row.items() if key != "handle"} for row in matches]


def _tapped_control_rows():
    """Exercise explicit and omitted tapped controls on the existing definition coupon."""
    rows = [("design_get", lambda c: {"include": ["definition"], "units": "mm",
             "feature": _ctx_get(c, "def_tap", "default tap")},
             _tapped_control_definition("def_tap_created"), None)]
    for extra, refusal in (({}, _refused("thread_length")),
                           ({"thread_length": 40, "thread_offset": 2}, _refused("THREAD_OVER_EXTENT"))):
        rows.append(("design_get", {"include": ["timeline"], "max_results": 1000}, "ok",
                     ("def_rejected_timeline", _recall("def_rejected_timeline", lambda p: p["timeline"]))))
        rows.append(("find_geometry", {"target": "DefinitionBench", "max_results": 1000}, "ok",
                     ("def_rejected_geometry", _recall("def_rejected_geometry", _tapped_geometry))))
        rows.append(("model_hole", lambda c, extra=extra: _combine_pin(c, "def_doc", {
            "face": _ctx_get(c, "def_top", "top face"), "points_space": "world", "points": [[5, 17, 30]],
            "diameter": "0.3125 in", "extent": "blind", "depth": "0.875 in", "tap": "3/8-16 UNC",
            "thread_type": "ANSI Unified Screw Threads", "thread_class": "2B", "thread_extent": "partial",
            **extra}), refusal, None))
        rows.append(("design_get", {"include": ["timeline"], "max_results": 1000},
                     lambda p: _measured("invalid partial preserves timeline", p.get("timeline"),
                         bool(_RECALL.get("def_rejected_timeline"))
                         and p.get("timeline") == _RECALL["def_rejected_timeline"]), None))
        rows.append(("find_geometry", {"target": "DefinitionBench", "max_results": 1000},
                     lambda p: _measured("invalid partial preserves coupon geometry", p.get("match_count"),
                         _tapped_geometry(p) == _RECALL.get("def_rejected_geometry")), None))
    for full, point in ((True, [5, 17, 30]), (False, [17, 5, 30])):
        key = "def_control_full" if full else "def_control_partial"
        rows.append(("model_hole", lambda c, full=full, point=point: _combine_pin(c, "def_doc", {
            "face": _ctx_get(c, "def_top", "top face"), "points_space": "world", "points": [point],
            "diameter": "0.3125 in", "extent": "blind", "depth": "0.875 in", "tap": "3/8-16 UNC",
            "thread_type": "ANSI Unified Screw Threads", "thread_class": "2B",
            "thread_extent": "full" if full else "partial",
            **({} if full else {"thread_length": 12, "thread_offset": 2})}),
            _drilled(1), (key, _tapped_created_ref(key))))
        rows.append(("design_get", lambda c, key=key: {"include": ["definition"], "units": "mm",
                     "feature": _ctx_get(c, key, "controlled tap")},
                     _tapped_control_definition(key, full), None))
        rows.append(("find_geometry", {"target": "DefinitionBench", "kind": "cylinder_face",
                     "nearest_to": [point[0], point[1], 20], "max_results": 1},
                     lambda p, point=point: _measured("controlled tap bore location", p.get("matches"),
                         _matched(1, "cylinder_face")(p)
                         and _near(p["matches"][0]["position"][0], point[0], 0.000001)
                         and _near(p["matches"][0]["position"][1], point[1], 0.000001)
                         and p["matches"][0].get("radius", 0) > 0), None))
    def write(name, args):
        rows.append((name, lambda c, args=args: _combine_pin(c, "def_doc", args), "ok", None))
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "TapControlBench", "activate": True})
    write("sketch_create", {"plane": "xy", "name": "TapControlStock"})
    write("sketch_add_geometry", {"sketch_name": "TapControlStock", "geometry": [
        {"kind": "rectangle", "x1": 100, "y1": 0, "x2": 160, "y2": 25}]})
    write("model_extrude", {"sketch_name": "TapControlStock", "distance": 30})
    rows.append(("find_geometry", {"target": "TapControlBench", "kind": "planar_face",
                 "nearest_to": [130, 12.5, 30], "max_results": 1},
                 _face_up_at(130, 12.5, 30, 0.000001), _fg("def_control_top")))
    for extent, modeled, x in (("through", False, 110), ("blind", False, 130), ("blind", True, 150)):
        full = extent == "through"
        key = "def_control_through" if full else "def_control_modeled" if modeled else "def_control_cosmetic"
        rows.append(("model_inspect", _combine_inspect("TapControlBench"), "ok",
                     ("def_control_volume", _recall("def_control_volume", lambda p: p["mass"]["volume"]))))
        rows.append(("model_hole", lambda c, extent=extent, modeled=modeled, x=x, full=full: _combine_pin(
            c, "def_doc", {"face": _ctx_get(c, "def_control_top", "control stock top"),
                "points_space": "world", "points": [[x, 10, 30]], "diameter": "0.3125 in",
                "extent": extent, "tap": "3/8-16 UNC", "thread_type": "ANSI Unified Screw Threads",
                "thread_class": "2B", "thread_extent": "full" if full else "partial", "modeled": modeled,
                **({} if full else {"depth": "0.875 in", "thread_length": 12, "thread_offset": 2})}),
            _drilled(1), (key, _tapped_created_ref(key, "TapControlBench"))))
        rows.append(("design_get", lambda c, key=key: {"include": ["definition"], "units": "mm",
                     "feature": _ctx_get(c, key, "controlled tap")},
                     _tapped_control_definition(key, full, extent, modeled, "TapControlBench"), None))
        rows.append(("model_inspect", _combine_inspect("TapControlBench"),
                     lambda p, modeled=modeled: _measured("tap material removal and modeled helix excess", {
                         "mass": p.get("mass"), "before": _RECALL.get("def_control_volume"),
                         "cosmetic_removed": _RECALL.get("def_control_cosmetic_removed")},
                         p.get("units") == "mm" and isinstance(_RECALL.get("def_control_volume"), (int, float))
                         and isinstance((p.get("mass") or {}).get("volume"), (int, float))
                         and 0 < p["mass"]["volume"] < _RECALL["def_control_volume"] - 1
                         and (not modeled or isinstance(_RECALL.get("def_control_cosmetic_removed"), (int, float))
                              and _RECALL["def_control_volume"] - p["mass"]["volume"]
                                  > _RECALL["def_control_cosmetic_removed"] + 1)),
                     ("def_control_cosmetic_removed", _recall("def_control_cosmetic_removed",
                         lambda p: _RECALL["def_control_volume"] - p["mass"]["volume"]))
                     if not full and not modeled else None))
        if full:
            rows.append(("find_geometry", {"target": "TapControlBench", "kind": "cylinder_face",
                         "nearest_to": [110, 10, 15], "max_results": 1},
                         _matched(1, "cylinder_face"), _fg("def_control_bore")))
            rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "def_control_bore", "through tap bore")},
                         lambda p: _measured("through tap crosses stock", p,
                             _near(p.get("z"), 30, 0.000001)
                             and _near((p.get("center") or {}).get("x"), 110, 0.000001)
                             and _near((p.get("center") or {}).get("y"), 10, 0.000001)
                             and p.get("x", 0) > 0 and _near(p.get("x"), p.get("y"), 0.000001)), None))
    return rows


def _hole_feedback_rows():
    """Check expression refusals, live parameter links, and tap-controlled bore geometry."""
    rows = []
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(
            c, "def_doc", args(c) if callable(args) else args), check, save))
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "HoleFeedback", "activate": True})
    write("sketch_create", {"plane": "xy", "name": "HoleFeedbackStock"})
    write("sketch_add_geometry", {"sketch_name": "HoleFeedbackStock", "geometry": [
        {"kind": "rectangle", "x1": 200, "y1": 0, "x2": 260, "y2": 40}]})
    write("model_extrude", {"sketch_name": "HoleFeedbackStock", "distance": 30})
    rows.append(("find_geometry", lambda c: {"target": "HoleFeedback", "kind": "planar_face",
                 "nearest_to": [230, 20, 30], "max_results": 1}, _face_up_at(230, 20, 30, .000001), _fg("hf_top")))
    for field, value in (("diameter", "5/16 in"), ("depth", "MissingHoleDepth/2")):
        for tool, args, key, extract in (
                ("design_get", {"include": ["timeline"], "max_results": 1000}, "hf_timeline", lambda p: p["timeline"]),
                ("sketch_get", {"component": "HoleFeedback", "max_results": 1000}, "hf_sketches", lambda p: p),
                ("find_geometry", {"target": "HoleFeedback", "max_results": 1000}, "hf_geometry", _tapped_geometry)):
            rows.append((tool, args, "ok", (key, _recall(key, extract))))
        write("model_hole", lambda c, field=field, value=value: {
            "face": _ctx_get(c, "hf_top", "stock top"), "points_space": "world", "points": [[230, 10, 30]],
            "diameter": "4 mm", "extent": "blind", "depth": "12 mm", field: value},
            _refused(field, value, "0.3125 in"))
        for tool, args, key, extract in (
                ("design_get", {"include": ["timeline"], "max_results": 1000}, "hf_timeline", lambda p: p["timeline"]),
                ("sketch_get", {"component": "HoleFeedback", "max_results": 1000}, "hf_sketches", lambda p: p),
                ("find_geometry", {"target": "HoleFeedback", "max_results": 1000}, "hf_geometry", _tapped_geometry)):
            rows.append((tool, args, lambda p, key=key, extract=extract: _measured(
                "invalid hole preserves " + key, extract(p), bool(_RECALL.get(key))
                and extract(p) == _RECALL[key]), None))
    write("param_add", {"name": "FeedbackDia", "expression": "4 mm"}, _param_added("FeedbackDia", 4))
    write("param_add", {"name": "FeedbackDepth", "expression": "12 mm"}, _param_added("FeedbackDepth", 12))
    write("model_hole", lambda c: {"face": _ctx_get(c, "hf_top", "stock top"), "points_space": "world",
        "points": [[210, 10, 30]], "diameter": "FeedbackDia", "depth": "FeedbackDepth", "extent": "blind"},
        _drilled(1), ("hf_ordinary", _tapped_created_ref("hf_ordinary", "HoleFeedback")))
    rows.append(("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 1000},
        lambda p: _measured("hole preserves both parameter expressions", p.get("timeline"), any(
            row.get("name") == (_RECALL.get("hf_ordinary") or {}).get("feature")
            and row.get("component") == "HoleFeedback"
            and {"FeedbackDia", "FeedbackDepth"}.issubset({q.get("expression") for q in row.get("params") or []})
            for row in (p.get("timeline") or {}).get("timeline") or [])), None))
    for diameter in (4, 6):
        if diameter == 6:
            write("param_set", {"name": "FeedbackDia", "expression": "6 mm"}, _param_set_to("FeedbackDia", 6))
        rows.append(("design_get", lambda c: {"include": ["definition"], "feature": _ctx_get(c, "hf_ordinary", "hole")},
            lambda p, diameter=diameter: _measured("ordinary diameter remains applicable", p.get("definition"),
                (p.get("definition") or {}).get("diameter_parameter_applicable") is True
                and _near((p.get("definition") or {}).get("diameter_parameter"), diameter, .000001)
                and _near((p.get("definition") or {}).get("depth"), 12, .000001)), None))
        rows.append(("find_geometry", {"target": "HoleFeedback", "kind": "cylinder_face", "radius": diameter/2},
            lambda p, diameter=diameter: _matched(1, "cylinder_face")(p)
            and _measured("parameter drives actual hole radius", p["matches"],
                _near(p["matches"][0].get("radius"), diameter/2, .000001)
                and _near(p["matches"][0]["position"][0], 210, .000001)), None))
    rows.append(("workspace_orient", {}, lambda p: _measured(
        "numeric-string hole requires disclosed millimeter document units", p.get("design"),
        (p.get("design") or {}).get("units") == "mm"), None))
    write("model_hole", lambda c: {"face": _ctx_get(c, "hf_top", "stock top"), "points_space": "world",
        "points": [[250/25.4, 10/25.4, 30/25.4]], "units": "in", "diameter": "5",
        "depth": "12 mm", "extent": "blind"}, _drilled(1),
        ("hf_unitless", lambda p: "HoleFeedback/" + p["feature"]))
    rows.append(("design_get", lambda c: {"include": ["definition"], "units": "mm",
                 "feature": _ctx_get(c, "hf_unitless", "numeric-string hole")},
        lambda p: _measured("numeric-string diameter uses document units", p.get("definition"),
            (p.get("definition") or {}).get("diameter_parameter_applicable") is True
            and _near((p.get("definition") or {}).get("diameter_parameter"), 5, .000001)
            and _near((p.get("definition") or {}).get("depth"), 12, .000001)), None))
    rows.append(("find_geometry", {"target": "HoleFeedback", "kind": "cylinder_face", "radius": 2.5},
        lambda p: _matched(1, "cylinder_face")(p) and _measured("numeric-string hole actual bore", p["matches"],
            _near(p["matches"][0].get("radius"), 2.5, .000001)
            and _near(p["matches"][0]["position"][0], 250, .000001)
            and _near(p["matches"][0]["position"][1], 10, .000001)), None))
    for index, (x, diameter) in enumerate(((215, "0.3125 in"), (245, "10 mm"), (230, None))):
        key = "hf_tap_" + str(index)
        write("model_hole", lambda c, diameter=diameter, x=x: {
            "face": _ctx_get(c, "hf_top", "stock top"), "points_space": "world", "points": [[x, 30, 30]],
            **({"diameter": diameter} if diameter is not None else {}),
            "extent": "blind", "depth": "0.875 in", "tap": "3/8-16 UNC",
            "thread_type": "ANSI Unified Screw Threads", "thread_class": "2B", "thread_extent": "full"},
            lambda p, diameter=diameter: _drilled(1)(p) and _measured("writer discloses tap-controlled bore", p.get("note"),
                ("tap definition governs bore size" in p.get("note", "") and "diameter=" not in p.get("note", "")
                 if diameter is None else ("diameter=" + repr(diameter) + " is unused") in p.get("note", ""))),
            (key, _tapped_created_ref(key, "HoleFeedback")))
        rows.append(("design_get", {"include": ["timeline"], "max_results": 1000}, "ok",
                     ("hf_read_timeline", _recall("hf_read_timeline", lambda p: p["timeline"]))))
        rows.append(("doc_get", {}, _home_document,
                     ("hf_read_doc", _recall("hf_read_doc", _definition_doc_state))))
        rows.append(("design_get", lambda c, key=key: {"include": ["definition"], "units": "mm",
                     "feature": _ctx_get(c, key, "tap")},
                     _tapped_control_definition(key, True, "blind", False, "HoleFeedback"), None))
        rows.append(("design_get", {"include": ["timeline"], "max_results": 1000},
            lambda p: _measured("diameter read preserves marker and timeline", p.get("timeline"),
                bool(_RECALL.get("hf_read_timeline")) and p.get("timeline") == _RECALL["hf_read_timeline"]), None))
        rows.append(("doc_get", {}, lambda p: _measured("diameter read preserves document state", p.get("active"),
            _definition_doc_state(p) == _RECALL.get("hf_read_doc")), None))
        rows.append(("find_geometry", lambda c, x=x: {"target": "HoleFeedback", "kind": "cylinder_face",
                     "nearest_to": [x, 30, 20], "max_results": 1},
            lambda p, index=index, x=x: _matched(1, "cylinder_face")(p) and _measured(
                "tap bore ignores nominal diameter input", p["matches"],
                _near(p["matches"][0].get("radius"), 7.9756/2, .0001)
                and _near(p["matches"][0]["position"][0], x, .000001)
                and (index == 0 or _near(p["matches"][0].get("radius"), _RECALL.get("hf_tap_radius"), .000001))),
            ("hf_tap_radius", _recall("hf_tap_radius", lambda p: p["matches"][0]["radius"])) if index == 0
            else _fg("hf_omitted_bore") if diameter is None else None))
        if diameter is None:
            rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "hf_omitted_bore", "tap bore"), "units": "mm"},
                lambda p: _measured("omitted diameter preserves the actual tapped bore and depth", p,
                    p.get("units") == "mm" and all(_near(p.get(axis), size, .0001)
                    for axis, size in zip("xyz", (7.9756, 7.9756, 22.225)))), None))
    return rows


def _definition_rows():
    """Build a bounded Hole/Thread read coupon in an owned scratch document."""
    rows = [("doc_get", {}, _home_document, ("def_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "def_story", "story")},
             _new_document, ("def_doc", lambda p: p["document_handle"]))]
    def write(name, args, save=None, check="ok"):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "def_doc", args(c) if callable(args) else args), check, save))
    def read(key, check, units):
        rows.append(("design_get", lambda c, key=key, units=units: {
            "include": ["definition"], "feature": _ctx_get(c, key, "created feature"), "units": units},
            check, (key + "_mm", _recall(key + "_mm", lambda p: p["definition"]))
            if units == "mm" else None))
    def state(before):
        if before:
            rows.append(("doc_get", {}, _home_document,
                         ("def_active", _recall("def_active", _definition_doc_state))))
            rows.append(("design_get", {"include": ["timeline"]}, "ok",
                         ("def_timeline", _recall("def_timeline", lambda p: {
                             key: p["timeline"][key] for key in ("marker_position", "count")}))))
        else:
            rows.append(("design_get", {"include": ["timeline"]},
                         lambda p: _measured("definition read preserves timeline", p.get("timeline"),
                             all((p.get("timeline") or {}).get(key) == value for key, value in
                                 (_RECALL.get("def_timeline") or {}).items())
                             and bool(_RECALL.get("def_timeline"))), None))
            rows.append(("doc_get", {}, lambda p: _measured("definition read preserves document state",
                         _definition_doc_state(p), _definition_doc_state(p) == _RECALL.get("def_active")), None))
    write("model_create_component", {"name": "DefinitionBench", "activate": True})
    write("sketch_create", {"plane": "xy", "name": "DefinitionBlock"})
    write("sketch_add_geometry", {"sketch_name": "DefinitionBlock", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 25, "y2": 25}]})
    write("model_extrude", {"sketch_name": "DefinitionBlock", "distance": 30})
    rows.append(("find_geometry", {"target": "DefinitionBench", "kind": "planar_face",
                                   "nearest_to": [12.5, 12.5, 30], "max_results": 1},
                 _matched(1, "planar_face"), _fg("def_top")))
    for key, point, extra in (("def_through", [5, 5, 30], {"diameter": "4 mm", "extent": "through"}),
                              ("def_tap", [17, 17, 30], {"tap": "3/8-16 UNC", "diameter": "0.3125 in", "extent": "blind",
                                                          "depth": "0.875 in"})):
        write("model_hole", lambda c, point=point, extra=extra: {
            "face": _ctx_get(c, "def_top", "top face"), "points_space": "world", "points": [point],
            **extra}, (key, _tapped_created_ref("def_tap_created") if key == "def_tap" else
                        lambda p: "DefinitionBench/" + p["feature"]))
        state(True)
        for units in ("mm", "in"):
            read(key, _hole_definition(extra["extent"], units, key == "def_tap"), units)
        state(False)
    rows.append(("find_geometry", {"target": "DefinitionBench", "kind": "cylinder_face", "radius": 2},
                 _matched(1, "cylinder_face"), _fg("def_bore")))
    rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "def_bore", "through bore")},
                 lambda p: _measured("independent through-hole diameter/depth", p,
                                     _near(p.get("x"), 4, 0.00001) and _near(p.get("y"), 4, 0.00001)
                                     and _near(p.get("z"), 30, 0.00001)), None))
    rows += _tapped_control_rows()
    rows += _hole_feedback_rows()
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "DefinitionPost", "activate": True})
    write("sketch_create", {"plane": "xy", "name": "DefinitionPostS"})
    write("sketch_add_geometry", {"sketch_name": "DefinitionPostS", "geometry": [
        {"kind": "circle", "cx": 50, "cy": 0, "radius": 3}]})
    write("model_extrude", {"sketch_name": "DefinitionPostS", "distance": 25})
    rows.append(("find_geometry", {"target": "DefinitionPost", "kind": "cylinder_face"},
                 _matched(1, "cylinder_face"), _fg("def_post")))
    for full in (True, False):
        if full:
            controls = (
                ("design_get", {"include": ["timeline"], "max_results": 1000}, "thread_before", lambda p: p["timeline"]),
                ("sketch_get", {"component": "DefinitionPost", "max_results": 1000}, "thread_sketches", lambda p: p),
                ("find_geometry", {"target": "DefinitionPost", "max_results": 1000}, "thread_geometry", _tapped_geometry),
                ("design_get", {"include": ["tree"], "component": "DefinitionPost", "tree_bodies": True},
                 "thread_visibility", _thread_visibility))
            for tool, args, key, extract in controls:
                rows.append((tool, args, "ok", (key, _recall(key, extract))))
            for standard, fit, choice in (
                    ("ISO Metric profile", "6g", "'M6x1' in 'ISO Metric profile' (classes: 6g)"),
                    ("unknown standard", "6g", "'M6x1' in 'ISO Metric profile' (classes: 4g6g, 6g)"),
                    ("ISO Metric profile", "6H", "'M6x1' in 'ISO Metric profile' (classes: 4g6g, 6g)")):
                rows.append(("model_thread", lambda c, standard=standard, fit=fit: _combine_pin(c, "def_doc", {
                    "faces": [_ctx_get(c, "def_post", "post cylinder")], "designation": "M6x1.0",
                    "thread_type": standard, "thread_class": fit}),
                    _refused("M6x1.0", "Nearby library spellings (not fit recommendations)",
                             choice, "Choose a listed designation, type and class"), None))
                for tool, args, key, extract in controls:
                    rows.append((tool, args, lambda p, key=key, extract=extract: _measured(
                        "unknown thread preserves " + key, extract(p), bool(_RECALL.get(key))
                        and extract(p) == _RECALL[key]), None))
            # No library spelling is near 'QQ', so the refusal names the closest one per type.
            rows.append(("model_thread", lambda c: _combine_pin(c, "def_doc", {
                "faces": [_ctx_get(c, "def_post", "post cylinder")], "designation": "QQ",
                "thread_type": "ISO Metric profile"}),
                _refused("No thread designation 'QQ'", "Closest designation per thread type: '",
                         "' in 'ISO Metric profile'",
                         "Retry with one as designation and its thread_type."), None))
            for tool, args, key, extract in controls:
                rows.append((tool, args, lambda p, key=key, extract=extract: _measured(
                    "far thread spelling preserves " + key, extract(p), bool(_RECALL.get(key))
                    and extract(p) == _RECALL[key]), None))
        if not full:
            write("sketch_create", {"plane": "xy", "name": "DefinitionPartialS"})
            write("sketch_add_geometry", {"sketch_name": "DefinitionPartialS", "geometry": [
                {"kind": "circle", "cx": 70, "cy": 0, "radius": 5}]})
            write("model_extrude", {"sketch_name": "DefinitionPartialS", "distance": 25})
            rows.append(("find_geometry", {"target": "DefinitionPost", "kind": "cylinder_face",
                                           "nearest_to": [70, 0, 12.5], "max_results": 1},
                         _matched(1, "cylinder_face"), _fg("def_post")))
        write("model_thread", lambda c, full=full: {
            "faces": [_ctx_get(c, "def_post", "post cylinder")], "designation": "M6x1" if full else "M10x1.5",
            "thread_type": "ISO Metric profile", "thread_class": "6g",
            **({} if full else {"length": 12, "offset": 2})},
            ("def_thread", _thread_ref(None if full else "def_cosmetic_after")),
            _cosmetic_resize(3.0, 2.942) if full else _cosmetic_resize(5.0, None))
        if not full:
            rows.append(("find_geometry", {"target": "DefinitionPost", "kind": "cylinder_face",
                                           "nearest_to": [70, 0, 12.5], "max_results": 1},
                         _cosmetic_reread("def_cosmetic_after"), None))
        if full:
            rows.append(("design_get", {"include": ["timeline"], "max_results": 1000},
                lambda p: _measured("literal thread recovery adds only one feature", p.get("timeline"),
                    (p.get("timeline") or {}).get("count") == _RECALL["thread_before"]["count"] + 1
                    and (p["timeline"].get("timeline") or [])[:-1] == _RECALL["thread_before"]["timeline"]
                    and p["timeline"]["timeline"][-1].get("type") == "ThreadFeature"), None))
            rows.append(("design_get", {"include": ["tree"], "component": "DefinitionPost", "tree_bodies": True},
                lambda p: _measured("thread recovery preserves post visibility", p.get("tree"),
                                    _thread_visibility(p) == _RECALL.get("thread_visibility")), None))
            rows.append(("find_geometry", {"target": "DefinitionPost", "kind": "cylinder_face"},
                lambda p: _matched(1, "cylinder_face")(p) and p.get("match_count") == 1
                and _near(p["matches"][0].get("radius"), 2.942, .0001), _fg("def_post")))
        rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "def_post", "threaded cylinder")},
                     lambda p, full=full: _measured("capture threaded cylinder before definition reads", p,
                         all(isinstance(p.get(key), (int, float)) and math.isfinite(p[key]) and p[key] > 0
                             for key in ("x", "y"))
                         and (not full or all(_near(p.get(key), 5.884, .0001) for key in ("x", "y")))
                         and _near(p.get("z"), 25, 0.00001)
                         and _near((p.get("center") or {}).get("x"), 50 if full else 70, 0.00001)),
                     ("def_thread_shape", _recall("def_thread_shape", lambda p: {
                         key: p[key] for key in ("kind", "units", "x", "y", "z", "min_point", "max_point", "center")}))))
        state(True)
        for units in ("mm", "in"):
            read("def_thread", _thread_definition(full, units), units)
        state(False)
        rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "def_post", "threaded cylinder")},
                     lambda p, full=full: _measured("definition reads preserve threaded cylinder geometry", p,
                                         bool(_RECALL.get("def_thread_shape"))
                                         and all(p.get(key) == value for key, value in
                                                 (_RECALL.get("def_thread_shape") or {}).items())
                                         and _near(p.get("z"), 25, 0.00001)
                                         and _near((p.get("center") or {}).get("x"),
                                                   50 if full else 70, 0.00001)), None))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "def_story", "story"),
                                        "expect_document": _ctx_get(c, "def_doc", "coupon")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "def_doc", "coupon"), "save_changes": False,
                                     "expect_document": _ctx_get(c, "def_story", "story")}, _document_closed, None)]
    return rows


_DEFINITION_READS = _definition_rows()


# OperandBench is turned 30 deg about world Z and moved (100, 200, 0) mm, so its XZ plane - the one
# OperandS sits on - has the normal R30 * (0, 1, 0) and holds the moved origin.
_OPERAND_NORMAL = [-math.sin(math.radians(30)), math.cos(math.radians(30)), 0.0]
_OPERAND_MOVE = [100.0, 200.0, 0.0]


def _operand_frame_read():
    """The OperandS frame sketch_get published, as recalled."""
    f = _RECALL.get("dop_frame") or {}
    if not all(isinstance(f.get(k), list) for k in ("origin_mm", "x_world", "y_world", "normal")):
        raise AssertionError(f"the OperandS frame did not read: {f!r}")
    return f


def _frame_world(u, v):
    """WORLD mm of OperandS point (u, v) mm, through the frame sketch_get read off its proxy."""
    f = _operand_frame_read()
    return [f["origin_mm"][i] + u * f["x_world"][i] + v * f["y_world"][i] for i in range(3)]


def _swung(u, v, sign):
    """WORLD mm of OperandS point (u, v) after a 90 deg turn, either way, about its sketch x axis."""
    n = _operand_frame_read()["normal"]
    return [a + sign * v * b for a, b in zip(_frame_world(u, 0), n)]


def _operand_at(got, want, tol=0.001):
    """True when a published [x, y, z] (or {x, y, z}) sits at `want` within `tol` mm."""
    if isinstance(got, dict):
        got = [got.get(k) for k in "xyz"]
    return isinstance(got, list) and len(got) == 3 and all(_near(a, b, tol) for a, b in zip(got, want))


def _on_moved_plane(normal, origin):
    """True when a plane (unit normal, origin mm) is OperandBench's XZ plane, turned and moved."""
    if isinstance(origin, dict):
        origin = [origin.get(k) for k in "xyz"]
    if not (isinstance(normal, list) and len(normal) == 3 and isinstance(origin, list)
            and len(origin) == 3 and all(isinstance(v, (int, float)) for v in normal + origin)):
        return False
    along = sum(a * b for a, b in zip(normal, _OPERAND_NORMAL))
    return (_near(abs(along), 1.0, 1e-5)
            and _near(sum(a * b for a, b in zip(normal, origin)),
                      sum(a * b for a, b in zip(normal, _OPERAND_MOVE)), 1e-3))


def _placed_plane_sketch_frame(p):
    """Require distinct in-plane origins and the actual root owner after consuming a placed plane."""
    datum = _RECALL.get("dop_local_plane_witness") or {}
    frame = p.get("frame") or {}
    normal, point = datum.get("normal"), datum.get("position")
    sketch_normal, origin = frame.get("normal"), frame.get("origin_mm")
    vectors = (normal, point, sketch_normal, origin)
    measured = all(isinstance(v, list) and len(v) == 3
                   and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)
                   for v in vectors)
    separation = (math.dist(point, origin) if measured else None)
    residual = (sum(n * (o - q) for n, o, q in zip(normal, origin, point))
                if measured else None)
    parallel = (abs(sum(a * b for a, b in zip(normal, sketch_normal)))
                if measured else None)
    owner, root_owner = p.get("component"), _RECALL.get("dop_root_owner")
    return _measured("placed support with independent sketch origin and root owner",
                     {"owner": owner, "root": root_owner,
                      "datum": datum, "frame": frame, "separation_mm": separation,
                      "residual_mm": residual, "normal_dot_abs": parallel},
                     measured and p.get("plane") == "LocalPlane"
                     and isinstance(owner, str) and bool(owner)
                     and isinstance(root_owner, str) and bool(root_owner)
                     and owner == root_owner and owner != "OperandBench"
                     and frame.get("space") == "world"
                     and separation > 1.0 and abs(residual) < 0.001
                     and _near(parallel, 1.0, 1e-5))


def _remember_local_plane(p):
    """Keep the acquired public plane row beside its handle for later frame checks."""
    row = p["matches"][0]
    _RECALL["dop_local_plane_witness"] = row
    return row["handle"]


def _placed_plane_sketch_points(p):
    """Require the new local point's world readback on the independently acquired support plane."""
    datum = _RECALL.get("dop_local_plane_witness") or {}
    frame = _RECALL.get("dop_local_sketch_frame") or {}
    normal, point = datum.get("normal"), datum.get("position")
    origin, x_axis, y_axis = (frame.get("origin_mm"), frame.get("x_world"),
                              frame.get("y_world"))
    rows = p.get("matches") or []
    valid = (all(isinstance(v, list) and len(v) == 3
                 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)
                 for v in (normal, point, origin, x_axis, y_axis))
             and p.get("match_count") == len(rows) == 2)
    expected = ([origin[i] + 3 * x_axis[i] + 2 * y_axis[i] for i in range(3)]
                if valid else None)
    positions = [row.get("position") for row in rows]
    if valid:
        valid = (any(_operand_at(pos, expected, 0.001) for pos in positions)
                 and any(_operand_at(pos, origin, 0.001) for pos in positions)
                 and all(row.get("kind") == "sketch_point"
                         and row.get("sketch") == "RediscoveredLocalPlaneS"
                         and row.get("occurrence") is None for row in rows)
                 and all(isinstance(pos, list) and len(pos) == 3
                         and all(isinstance(x, (int, float)) and math.isfinite(x) for x in pos)
                         and abs(sum(n * (v - q) for n, v, q in zip(normal, pos, point))) < 0.001
                         for pos in positions))
    return _measured("root-owned sketch point independently lies on placed plane",
                     {"positions": positions, "expected_local_3_2": expected}, valid)


def _operand_frame(p):
    """sketch_get: OperandS's world frame lies on the turned, moved XZ plane."""
    f = p.get("frame") or {}
    return _measured("OperandS frame on the turned, moved XZ plane", f,
                     f.get("space") == "world" and _on_moved_plane(f.get("normal"),
                                                                    f.get("origin_mm")))


def _operand_ends(ends, a, b):
    """True when a line operand's two published world ends are `a` and `b`, in either order."""
    if not isinstance(ends, list) or len(ends) != 2:
        return False
    return ((_operand_at(ends[0], a) and _operand_at(ends[1], b))
            or (_operand_at(ends[0], b) and _operand_at(ends[1], a)))


def _operand_ids(p):
    """The sketch ids and handles of OperandS's three free points, found by sketch-local position."""
    out = {}
    for key, (x, y) in (("p1", (10, 20)), ("p2", (40, 20)), ("p3", (10, 50))):
        hits = [r for r in p.get("entities") or [] if r.get("type") == "point"
                and _near((r.get("position") or {}).get("x"), x, 1e-6)
                and _near((r.get("position") or {}).get("y"), y, 1e-6)]
        if len(hits) != 1:
            raise AssertionError(f"OperandS point ({x}, {y}) read {len(hits)} rows")
        (row,) = hits
        out[key], out[key + "_handle"] = row["id"], row.get("handle")
    return out


def _operand_xray(p):
    """sketch_get: every point and curve row carries a handle minted through OperandBench:1."""
    rows = [r for r in p.get("entities") or []
            if r.get("type") in ("point", "line", "circle", "arc", "spline")]
    return _measured("each sketch row prints its handle beside its id",
                     [(r.get("id"), r.get("handle")) for r in rows],
                     (p.get("frame") or {}).get("space") == "world" and len(rows) >= 12
                     and all(isinstance(r.get("handle"), str) and "|@sketch_" in r["handle"]
                             and r["handle"].endswith(";occ=OperandBench:1") for r in rows))


def _operand_match(kind, wants, shape=None):
    """find_geometry: ONE `kind` read through OperandBench:1 at one of `wants()` (world mm)."""
    def check(p):
        rows = p.get("matches") or []
        row = rows[0] if len(rows) == 1 else {}
        return _measured(f"one {kind} at its world position", rows,
                         len(rows) == 1 and row.get("kind") == kind
                         and any(_operand_at(row.get("position"), w) for w in wants())
                         and row.get("occurrence") == "OperandBench:1"
                         and f"|@{kind}:" in (row.get("handle") or "")
                         and (shape is None or shape(row)))
    return check


def _round_shape(u, v, radius):
    """A find_geometry arc/circle row's world centre is OperandS (u, v) and its radius `radius` mm."""
    return lambda row: (_operand_at(row.get("center"), _frame_world(u, v))
                        and _near(row.get("radius"), radius, 1e-6))


def _operand_rows_at(p, wants, path="OperandBench:1"):
    """The datum's 'operands' sit at `wants` (world mm), each read through `path`."""
    ops = p.get("operands") or []
    return (len(ops) == len(wants)
            and all(op.get("assembly_path") == path and _operand_at(op.get("world"), w)
                    for op, w in zip(ops, wants)))


def _operand_plane(wants, path="OperandBench:1"):
    """three_points: through every operand, on the turned and moved XZ plane, read back in world."""
    def check(p):
        g = p.get("geometry") or {}
        return _datum("plane")(p) and _measured(
            "a plane through three points of the turned, moved component",
            {"geometry": g, "through": p.get("passes_through_points"),
             "operands": p.get("operands")},
            p.get("passes_through_points") is True and _operand_rows_at(p, wants(), path)
            and _on_moved_plane(g.get("normal"), g.get("origin")))
    return check


def _operand_axis(direction, through=True):
    """An axis along the world `direction()` (either sense), through its operands when asked."""
    def check(p):
        d = (p.get("geometry") or {}).get("direction") or [0, 0, 0]
        dot = sum(a * b for a, b in zip(d, direction()))
        return _datum("axis")(p) and _measured(
            "an axis along the operands' world direction",
            {"direction": d, "through": p.get("passes_through_points"),
             "operands": p.get("operands")},
            _near(abs(dot), 1.0, 1e-5)
            and (not through or p.get("passes_through_points") is True))
    return check


def _operand_point(u, v, path="OperandBench:1"):
    """at_point: the datum sits at OperandS (u, v)'s world point, read back off the datum."""
    def check(p):
        want = _frame_world(u, v)
        return _datum("point")(p) and _measured(
            "a point datum at its operand's world point", p,
            p.get("at_operand") is True and _operand_at(p.get("world"), want)
            and _operand_rows_at(p, [want], path))
    return check


def _rediscovered_axis(p):
    """The acquired axis lies on OperandS's independently read world x line."""
    rows = p.get("matches") or []
    row = rows[0] if len(rows) == 1 else {}
    point, direction = row.get("position"), row.get("direction")
    anchor, along = _frame_world(0, 0), _operand_frame_read()["x_world"]
    if (not isinstance(point, list) or len(point) != 3
            or not isinstance(direction, list) or len(direction) != 3):
        return False
    dot = sum(a * b for a, b in zip(direction, along))
    delta = [a - b for a, b in zip(point, anchor)]
    cross = [delta[1] * along[2] - delta[2] * along[1],
             delta[2] * along[0] - delta[0] * along[2],
             delta[0] * along[1] - delta[1] * along[0]]
    return _measured("rediscovered placed axis has its independent world line", row,
                     p.get("match_count") == 1 and row.get("occurrence") == "OperandBench:1"
                     and "|@construction_axis:" in (row.get("handle") or "")
                     and _near(abs(dot), 1, 1e-5)
                     and sum(v * v for v in cross) ** 0.5 < 0.001)


def _swung_about_the_piece(p):
    """After the 90 deg turn about the first piece: its start stays, P1 swings to one side."""
    rows = [r.get("position") for r in p.get("matches") or []]
    swung = [r for r in rows if _operand_at(r, _swung(10, 20, 1)) or _operand_at(r, _swung(10, 20, -1))]
    return _measured("a point on the axis stays put and one off it swings 90 deg", rows,
                     p.get("match_count") == len(rows)
                     and any(_operand_at(r, _frame_world(0, 0)) for r in rows)
                     and len(swung) == 1
                     and not any(_operand_at(r, _frame_world(10, 20)) for r in rows))


def _datum_operand_rows():
    """Sketch -> point -> plane/axis on a turned, moved component's XZ plane, in a scratch document."""
    rows = [("doc_get", {}, _home_document, ("dop_story", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "dop_story", "story")},
             _new_document, ("dop_doc", lambda p: p["document_handle"]))]

    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: _combine_pin(
            c, "dop_doc", args(c) if callable(args) else args), check, save))

    def read(name, args, check, save=None):
        rows.append((name, lambda c, args=args: args(c) if callable(args) else dict(args),
                     check, save))

    def ids(c):
        return _ctx_get(c, "dop_ids", "OperandS ids and handles")

    def acquire(kind, u, v, wants, shape=None, save=None):
        # With no frame recalled (its read failed) the query goes unsorted and the check says so.
        read("find_geometry", lambda c: {"target": "OperandBench", "kind": kind, "max_results": 1,
                                         **({"nearest_to": _frame_world(u, v)}
                                            if _RECALL.get("dop_frame") else {})},
             _operand_match(kind, wants, shape), save)

    write("model_create_component", {"name": "OperandBench", "activate": True},
          _made_component)
    # XZ, so the sketch transform is not the identity: every expected world point below comes
    # from the frame sketch_get reads off the sketch proxy, a path apart from the one under test.
    write("sketch_create", {"plane": "xz", "name": "OperandS"})
    write("sketch_add_geometry", {"sketch_name": "OperandS", "geometry": [
        {"kind": "point", "cx": 10, "cy": 20}, {"kind": "point", "cx": 40, "cy": 20},
        {"kind": "point", "cx": 10, "cy": 50},
        {"kind": "line", "x1": 0, "y1": 0, "x2": 40, "y2": 0},
        {"kind": "circle", "cx": 30, "cy": 30, "radius": 10},
        {"kind": "arc", "cx": 60, "cy": 30, "x1": 70, "y1": 30, "sweep_deg": 90},
        {"kind": "spline", "points": [[80, 0], [90, 10], [100, 0]]}]})
    write("design_activate_component", {"occurrence": "root"})
    # A position capture reverts the pending move of the design's first root occurrence unless that
    # occurrence is released from its parent first; OperandBench:1 is this document's first.
    write("assembly_ground", {"occurrence": "OperandBench:1", "ground_to_parent": False},
          lambda p: p.get("isGroundToParent") is False)
    write("assembly_move", {"occurrence": "OperandBench:1", "rotate_deg": 30, "rotate_axis": "z",
                            "dx": 100, "dy": 200}, _moved_occurrence(100.0))
    # captured, or a later add recomputes the design and the uncaptured pose reverts.
    write("assembly_capture_position", {"action": "capture"}, _captured)
    read("sketch_get", {"sketch_name": "OperandS"}, _operand_frame,
         ("dop_frame", _recall("dop_frame", lambda p: p["frame"])))
    read("sketch_get", {"sketch_name": "OperandS", "include_entities": True}, _operand_xray,
         ("dop_ids", _recall("dop_ids", _operand_ids)))
    acquire("sketch_point", 10, 20, lambda: [_frame_world(10, 20)], save=_fg("dop_p1"))
    acquire("sketch_line", 20, 0, lambda: [_frame_world(20, 0)], save=_fg("dop_line"))
    # a curve's position is the midpoint of its ends: the arc's other end sits a quarter turn from
    # (70, 30) either way round, so both chord midpoints are the arithmetic; its centre is not.
    acquire("sketch_arc", 65, 30, lambda: [_frame_world(65, 35), _frame_world(65, 25)],
            _round_shape(60, 30, 10.0))
    acquire("sketch_circle", 30, 30, lambda: [_frame_world(30, 30)], _round_shape(30, 30, 10.0),
            ("dop_circle", lambda p: f"{p['matches'][0]['sketch']}/{p['matches'][0]['id']}:center"))
    acquire("sketch_spline", 90, 0, lambda: [_frame_world(90, 0)])
    # three forms in one call, from the root: a find_geometry handle, a sketch_get handle, and the
    # circle row's centre form, whose native point is lifted through the one placement.
    write("model_construction", lambda c: {
        "kind": "plane", "mode": "three_points", "name": "OperandPlane",
        "points": [_ctx_get(c, "dop_p1", "P1 handle"), ids(c)["p2_handle"],
                   _ctx_get(c, "dop_circle", "circle centre ref")]},
        _operand_plane(lambda: [_frame_world(10, 20), _frame_world(40, 20), _frame_world(30, 30)]))
    write("sketch_create", {"plane": "OperandPlane", "name": "OperandPlaneS"})
    read("sketch_get", {"sketch_name": "OperandPlaneS"},
         lambda p: _measured("a sketch on the operand plane frames the turned, moved XZ plane",
                             p.get("frame"), (p.get("frame") or {}).get("space") == "world"
                             and _on_moved_plane((p.get("frame") or {}).get("normal"),
                                                 (p.get("frame") or {}).get("origin_mm"))))
    read("find_geometry", {"kind": "construction_plane", "name": "OperandPlane"},
         lambda p: _matched(1, "construction_plane")(p)
         and p.get("match_count") == 1
         and _on_moved_plane(p["matches"][0].get("normal"), p["matches"][0].get("position"))
         and "|@construction_plane:" in (p["matches"][0].get("handle") or ""),
         _fg("dop_plane_rediscovered"))
    write("sketch_create", lambda c: {"plane": _ctx_get(c, "dop_plane_rediscovered", "plane"),
                                      "name": "RediscoveredPlaneS"})
    read("sketch_get", {"sketch_name": "RediscoveredPlaneS"},
         lambda p: _measured("rediscovered plane handle seats a sketch on the independent plane",
                             p.get("frame"), (p.get("frame") or {}).get("space") == "world"
                             and _on_moved_plane((p.get("frame") or {}).get("normal"),
                                                 (p.get("frame") or {}).get("origin_mm"))))
    write("model_construction", lambda c: {
        "kind": "axis", "mode": "two_points", "name": "OperandAxis",
        "points": [_ctx_get(c, "dop_p1", "P1 handle"), "OperandS/" + ids(c)["p3"]]},
        _operand_axis(lambda: _operand_frame_read()["y_world"]))
    write("model_construction", {"kind": "axis", "mode": "edge", "axis": "OperandS/line:0",
                                 "name": "OperandLineAxis"},
          lambda p: _operand_axis(lambda: _operand_frame_read()["x_world"], through=False)(p)
          and _measured(
              "the index-ref line went in through its one placement, ends in world",
              p.get("operands"),
              len(p.get("operands") or []) == 1
              and p["operands"][0].get("assembly_path") == "OperandBench:1"
              and _operand_ends(p["operands"][0].get("world"), _frame_world(0, 0),
                                _frame_world(40, 0))))
    write("model_construction", lambda c: {"kind": "point", "mode": "at_point",
                                           "name": "OperandCentre",
                                           "points": [_ctx_get(c, "dop_circle", "centre ref")]},
          _operand_point(30, 30))
    read("find_geometry", {"kind": "construction_point", "name": "OperandCentre"},
         lambda p: _matched(1, "construction_point")(p) and _measured(
             "the datum point read back where its operand sits", p["matches"],
             _operand_at(p["matches"][0].get("position"), _frame_world(30, 30))),
         _fg("dop_point_rediscovered"))
    write("model_construction", lambda c: {"kind": "point", "mode": "at_point",
                                           "name": "RediscoveredPoint",
                                           "points": [_ctx_get(c, "dop_point_rediscovered", "point")]},
          lambda p: _datum("point")(p) and p.get("at_operand") is True
          and _operand_at(p.get("world"), _frame_world(30, 30)))
    read("find_geometry", {"kind": "construction_point", "name": "RediscoveredPoint"},
         lambda p: _matched(1, "construction_point")(p)
         and _operand_at(p["matches"][0].get("position"), _frame_world(30, 30)))
    # inside the placed component the SAME native points go in native, and still land in world;
    # the plane's own read runs through the active occurrence.
    write("design_activate_component", {"occurrence": "OperandBench:1"})
    write("model_construction", lambda c: {"kind": "point", "mode": "at_point",
                                           "name": "LocalCentre",
                                           "points": ["OperandS/" + ids(c)["p2"]]},
          _operand_point(40, 20, path=None))
    write("model_construction", lambda c: {
        "kind": "plane", "mode": "three_points", "name": "LocalPlane",
        "points": ["OperandS/" + ids(c)[k] for k in ("p1", "p2", "p3")]},
        _operand_plane(lambda: [_frame_world(10, 20), _frame_world(40, 20), _frame_world(10, 50)],
                       path=None))
    write("design_activate_component", {"occurrence": "root"},
          lambda p: p.get("activated") == "root" and p.get("is_root_component_active") is True
          and isinstance(p.get("active_component"), str) and bool(p["active_component"]),
          ("dop_root_owner", _recall("dop_root_owner", lambda p: p["active_component"])))
    read("find_geometry", {"target": "OperandBench:1", "kind": "construction_plane",
                           "name": "LocalPlane"},
         lambda p: _matched(1, "construction_plane")(p)
         and p.get("match_count") == 1
         and p["matches"][0].get("occurrence") == "OperandBench:1"
         and _on_moved_plane(p["matches"][0].get("normal"), p["matches"][0].get("position")),
         ("dop_local_plane_rediscovered", lambda p: _remember_local_plane(p)))
    write("sketch_create", lambda c: {"plane": _ctx_get(c, "dop_local_plane_rediscovered", "plane"),
                                      "name": "RediscoveredLocalPlaneS"}, _placed_plane_sketch_frame)
    read("sketch_get", {"sketch_name": "RediscoveredLocalPlaneS"},
         _placed_plane_sketch_frame,
         ("dop_local_sketch_frame", _recall("dop_local_sketch_frame", lambda p: p["frame"])))
    read("sketch_get", {},
         lambda p: _measured("sketch list independently names the root owner",
                             p.get("sketches"),
                             [(r.get("name"), r.get("component"))
                              for r in p.get("sketches") or []
                              if r.get("name") == "RediscoveredLocalPlaneS"]
                             == [("RediscoveredLocalPlaneS", _RECALL.get("dop_root_owner"))]))
    write("sketch_add_geometry", {"sketch_name": "RediscoveredLocalPlaneS",
                                  "geometry": [{"kind": "point", "cx": 3, "cy": 2}]})
    read("find_geometry", {"kind": "sketch_point", "sketch": "RediscoveredLocalPlaneS",
                           "max_results": 5}, _placed_plane_sketch_points)
    # a split leaves the pre-split handle naming a piece that no longer sits where it was read.
    write("sketch_edit_curve", {"action": "split", "sketch_name": "OperandS",
                                "entity_one": "line:0", "x1": 20, "y1": 0})
    write("model_construction", lambda c: {"kind": "axis", "axis": _ctx_get(c, "dop_line", "line")},
          _refused("did not resolve", "find_geometry"))
    acquire("sketch_line", 10, 0, lambda: [_frame_world(10, 0)], save=_fg("dop_piece"))
    write("design_activate_component", {"occurrence": "OperandBench:1"})
    write("model_construction", lambda c: {"kind": "axis", "name": "OperandPieceAxis",
                                           "axis": _ctx_get(c, "dop_piece", "first piece")},
          lambda p: p.get("component") == "OperandBench"
          and _operand_axis(lambda: _operand_frame_read()["x_world"], through=False)(p))
    write("design_activate_component", {"occurrence": "root"})
    write("design_add_instance", {"component": "OperandBench", "x": 400, "units": "mm"},
          lambda p: p.get("occurrence") == "OperandBench:2")
    read("design_get", {"include": ["datums"], "name_filter": "Operand"},
         lambda p: _measured("lost datum replies rediscovered as definition rows",
                             (p.get("datums") or {}).get("counts"),
                             {("construction_axis", "OperandPieceAxis"),
                              ("construction_plane", "OperandPlane"),
                              ("construction_point", "OperandCentre")}
                             <= {(r.get("kind"), r.get("name"))
                                 for r in (p.get("datums") or {}).get("datums") or []}
                             and (p.get("datums") or {}).get("match_count") is not None
                             and any(r.get("name") == "OperandPieceAxis"
                                     and r.get("placement_count") == 2
                                     for r in (p.get("datums") or {}).get("datums") or [])))
    read("find_geometry", {"target": "OperandBench:1", "kind": "construction_axis",
                           "name": "OperandPieceAxis"}, _rediscovered_axis,
         _fg("dop_axis_rediscovered"))
    read("find_geometry", {"target": "OperandBench:2", "kind": "construction_axis",
                           "name": "OperandPieceAxis"},
         lambda p: _matched(1, "construction_axis")(p)
         and p.get("match_count") == 1
         and p["matches"][0].get("occurrence") == "OperandBench:2"
         and (p["matches"][0].get("handle") or "").endswith(";occ=OperandBench:2"))
    # The reacquired datum, consumed by handle, turns about the piece's WORLD line.
    write("assembly_move", lambda c: {"occurrence": "OperandBench:1", "rotate_deg": 90,
                                      "rotate_axis": _ctx_get(c, "dop_axis_rediscovered", "piece axis")},
          _moved_occurrence())
    read("find_geometry", {"target": "OperandBench:1", "kind": "sketch_point", "max_results": 100},
         _swung_about_the_piece)
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "dop_story", "story"),
                                         "expect_document": _ctx_get(c, "dop_doc", "operands")},
              "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "dop_doc", "operands"),
                                      "save_changes": False,
                                      "expect_document": _ctx_get(c, "dop_story", "story")},
              _document_closed, None)]
    return rows


_DATUM_OPERANDS = _datum_operand_rows()



def _nested_datum_rows():
    """Rediscover a nested plane and consume its handle in the explicitly selected owner."""
    rows = [("doc_get", {}, _home_document, ("nd_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "nd_home", "home")},
             _new_document, ("nd_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(
            c, "nd_doc", args(c) if callable(args) else args), check, save))

    write("sketch_create", {"name": "NestedWitness", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "NestedWitness", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}]})
    write("model_extrude", {"sketch_name": "NestedWitness", "distance": 20})
    rows.append(("find_geometry", {"target": "Body1", "max_results": 100},
                 lambda p: bool(_tapped_geometry(p)),
                 ("nd_witness", _recall("nd_witness", _tapped_geometry))))
    write("model_create_component", {"name": "Outer", "x": 30, "rotate_deg": 90,
                                     "rotate_axis": "z", "activate": True})
    write("model_create_component", {"name": "Leaf", "parent": "Outer:1", "x": 5,
                                     "z": 3, "activate": True})
    write("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy",
                                "offset": 7, "name": "NestedPlane"})
    write("design_activate_component", {"occurrence": "root"})
    rows.append(("design_get", {"include": ["datums"], "component": "Outer:1+Leaf:1"},
                 _nested_datum_inventory, None))
    rows.append(("find_geometry", {"target": "Outer:1+Leaf:1", "kind": "construction_plane",
                 "name": "NestedPlane", "max_results": 10},
                 lambda p: _matched(1, "construction_plane")(p)
                 and p["matches"][0].get("occurrence") == "Outer:1+Leaf:1"
                 and _operand_at(p["matches"][0].get("position"), [30, 5, 10])
                 and _operand_at(p["matches"][0].get("normal"), [0, 0, 1]), _fg("nd_plane")))
    write("design_activate_component", {"occurrence": "Outer:1+Leaf:1"})
    write("sketch_create", lambda c: {"name": "DatumPick", "plane": _ctx_get(c, "nd_plane", "plane")},
          lambda p: _measured("nested sketch owner and independent world frame", p.get("frame"),
              p.get("component") == "Leaf" and p.get("plane") == "NestedPlane"
              and (p.get("frame") or {}).get("space") == "world"
              and all(_operand_at((p.get("frame") or {}).get(key), want) for key, want in (
                  ("origin_mm", [30, 5, 10]), ("x_world", [0, 1, 0]),
                  ("y_world", [-1, 0, 0]), ("normal", [0, 0, 1])))))
    write("sketch_add_geometry", {"sketch_name": "DatumPick", "geometry": [
        {"kind": "circle", "cx": 2, "cy": 3, "radius": 1}]})
    rows.append(("find_geometry", {"target": "Outer:1+Leaf:1", "kind": "sketch_circle"},
                 lambda p: _measured("nested circle lands at analytic world position", p.get("matches"),
                     _matched(1, "sketch_circle")(p)
                     and _operand_at(p["matches"][0].get("center"), [27, 7, 10])
                     and _near(p["matches"][0].get("radius"), 1, 0.000001)), None))
    write("design_activate_component", {"occurrence": "root"})
    rows.append(("find_geometry", {"target": "Body1", "max_results": 100},
                 lambda p: _measured("nested datum leaves root witness unchanged", p.get("match_count"),
                     _tapped_geometry(p) == _RECALL.get("nd_witness")), None))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 100},
                 lambda p: _measured("nested datum timeline healthy", p.get("timeline"),
                     (p.get("timeline") or {}).get("count") == 6
                     and (p.get("timeline") or {}).get("returned") == 6
                     and ((p.get("timeline") or {}).get("summary") or {}).get("states") == {"healthy": 6}
                     and ((p.get("timeline") or {}).get("summary") or {}).get("exceptions") == []), None))
    write("doc_activate", lambda c: {"name": _ctx_get(c, "nd_home", "home")})
    rows.append(("doc_close", lambda c: {"name": _ctx_get(c, "nd_doc", "scratch"),
                 "save_changes": False, "expect_document": _ctx_get(c, "nd_home", "home")},
                 _document_closed, None))
    return rows


def _nested_datum_inventory(p):
    """Require the definition inventory to retain the exact nested owner and placement."""
    result = p.get("datums") or {}
    rows = result.get("datums") or []
    row = rows[0] if len(rows) == 1 else {}
    return _measured("nested plane inventory", result,
                     result.get("match_count") == result.get("returned") == 1
                     and result.get("truncated") is False
                     and row.get("name") == "NestedPlane" and row.get("component") == "Leaf"
                     and row.get("kind") == "construction_plane"
                     and row.get("occurrences") == ["Outer:1+Leaf:1"]
                     and isinstance(row.get("timeline_index"), int))


_DATUM_OPERANDS += _nested_datum_rows()



def _tap_variant_definition(modeled, extent, partial):
    """Check native omitted-diameter tap metadata without treating the nominal size as its bore."""
    def check(p):
        d = p.get("definition") or {}
        thread, info = d.get("thread") or {}, d.get("tapped_hole_info") or {}
        return _measured("omitted-diameter tap native flags and extent", d,
                         d.get("extent") == extent and d.get("tapped") is True
                         and d.get("diameter_parameter_applicable") is False
                         and d.get("diameter_parameter") is None
                         and (d.get("depth") is None if extent == "through" else _near(d.get("depth"), 8, .00001))
                         and info.get("designation") == "M6x1" and info.get("thread_class") == "6H"
                         and info.get("internal") is True and thread.get("thread_info") == info
                         and thread.get("modeled") is modeled and thread.get("full_length") is (not partial)
                         and (all(_near(thread.get(k), v, .00001) for k, v in (("length", 4), ("offset", 1)))
                              if partial else thread.get("length") is None and thread.get("offset") is None))
    return check


def _tap_variant_material(key, volume):
    """Require measured bore removal, with modeled material distinct from the cosmetic control."""
    def check(p):
        got = (p.get("mass") or {}).get("volume")
        if key == "modeled":
            before = _RECALL.get("tv_cosmetic_volume")
            valid = (isinstance(before, (int, float)) and isinstance(got, (int, float))
                     and 0 < got < before - 20)
        else:
            valid = _near(got, volume, .002)
        return _measured("tap actual material volume independent of nominal diameter", {"volume_mm3": got}, valid)
    return check


def _thread_variant_rows():
    """Exercise omitted-diameter taps and external cosmetic resizing on owned analytic coupons."""
    rows = [("doc_get", {}, _home_document, ("tv_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "tv_home", "home")},
             _new_document, ("tv_doc", lambda p: p["document_handle"]))]

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: _combine_pin(
            c, "tv_doc", args(c) if callable(args) else args), check, save))

    write("sketch_create", {"name": "TapStock", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "TapStock", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}]})
    write("model_extrude", {"sketch_name": "TapStock", "distance": 20})
    rows.append(("find_geometry", {"target": "Body1", "max_results": 100},
                 lambda p: bool(_tapped_geometry(p)),
                 ("tv_stock", _recall("tv_stock", _tapped_geometry))))
    for key, modeled, extent, partial, volume in (
            ("cosmetic", False, "blind", False, 7830.674085324574),
            ("modeled", True, "blind", False, None),
            ("through", False, "through", False, 8000 - math.pi * 2.5175 ** 2 * 20),
            ("partial", False, "blind", True, 7830.674085324574)):
        rows.append(("find_geometry", {"target": "Body1", "kind": "planar_face",
                     "nearest_to": [10, 10, 20], "max_results": 1}, _face_up_at(10, 10, 20, .000001), _fg("tv_top")))
        write("model_hole", lambda c, modeled=modeled, extent=extent, partial=partial: {
            "face": _ctx_get(c, "tv_top", "stock top"), "points_space": "world", "points": [[10, 10, 20]],
            "target_bodies": ["Body1"], "tap": "M6x1", "thread_type": "ISO Metric profile",
            "thread_class": "6H", "modeled": modeled, "extent": extent, "depth": 8,
            "thread_extent": "partial" if partial else "full",
            **({"thread_length": 4, "thread_offset": 1} if partial else {})},
            lambda p: _drilled(1)(p) and "tap definition governs bore size" in p.get("note", ""),
            ("tv_hole", lambda p: {"feature": p["feature"], "placement": p["placement_sketch"]}))
        rows.append(("design_get", lambda c: {"include": ["definition"],
                     "feature": _ctx_get(c, "tv_hole", "hole")["feature"]},
                     _tap_variant_definition(modeled, extent, partial), None))
        rows.append(("find_geometry", {"target": "Body1", "kind": "cylinder_face", "radius": 2.5175},
                     lambda p: _matched(1, "cylinder_face")(p)
                     and _near(p["matches"][0].get("radius"), 2.5175, .00001), None))
        rows.append(("model_inspect", {"target": "Body1", "include": ["default", "mass"],
                     "units": "mm", "accuracy": "very_high"}, _tap_variant_material(key, volume),
                     ("tv_cosmetic_volume", _recall("tv_cosmetic_volume", lambda p: p["mass"]["volume"]))
                     if key == "cosmetic" else None))
        write("design_delete_feature", lambda c: {"feature": _ctx_get(c, "tv_hole", "hole")["feature"]})
        write("design_delete_feature", lambda c: {"feature": _ctx_get(c, "tv_hole", "hole")["placement"]})
        rows.append(("find_geometry", {"target": "Body1", "max_results": 100},
                     lambda p: _measured("tap retirement restores coupon geometry", p.get("match_count"),
                         _tapped_geometry(p) == _RECALL.get("tv_stock")), None))
    write("sketch_create", {"name": "CosmeticShaft", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "CosmeticShaft", "geometry": [
        {"kind": "circle", "cx": 50, "cy": 0, "radius": 10}]})
    write("model_extrude", {"sketch_name": "CosmeticShaft", "distance": 30})
    for designation, radius in (("M30x3.5", 14.86725), ("M20x2.5", 9.89525)):
        rows.append(("find_geometry", {"target": "Body2", "kind": "cylinder_face", "radius": 10},
                     _matched(1, "cylinder_face"), _fg("tv_wall")))
        write("model_thread", lambda c, designation=designation: {
            "faces": [_ctx_get(c, "tv_wall", "shaft wall")], "designation": designation,
            "thread_type": "ISO Metric profile", "thread_class": "4g6g", "modeled": False},
            _cosmetic_resize(10.0, radius), ("tv_thread", lambda p: p["feature"]))
        rows.append(("find_geometry", {"target": "Body2", "kind": "cylinder_face"},
                     lambda p, radius=radius: _measured("cosmetic actual radius, not nominal size", p.get("matches"),
                         _matched(1, "cylinder_face")(p) and _near(p["matches"][0].get("radius"), radius, .00001)), None))
        rows.append(("design_get", lambda c: {"include": ["definition"], "feature": _ctx_get(c, "tv_thread", "thread")},
                     lambda p, designation=designation: _measured("cosmetic native designation and flags", p.get("definition"),
                         (p.get("definition") or {}).get("modeled") is False
                         and (p.get("definition") or {}).get("full_length") is True
                         and ((p.get("definition") or {}).get("thread_info") or {}).get("designation") == designation
                         and ((p.get("definition") or {}).get("thread_info") or {}).get("internal") is False), None))
        write("design_delete_feature", lambda c: {"feature": _ctx_get(c, "tv_thread", "thread")})
    rows.append(("find_geometry", {"target": "Body1", "max_results": 100},
                 lambda p: _measured("thread operations preserve stock witness", p.get("match_count"),
                     _tapped_geometry(p) == _RECALL.get("tv_stock")), None))
    write("doc_activate", lambda c: {"name": _ctx_get(c, "tv_home", "home")})
    rows.append(("doc_close", lambda c: {"name": _ctx_get(c, "tv_doc", "scratch"),
                 "save_changes": False, "expect_document": _ctx_get(c, "tv_home", "home")}, _document_closed, None))
    return rows


_DEFINITION_READS += _thread_variant_rows()
