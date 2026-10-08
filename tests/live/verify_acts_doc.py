# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""ACT rows: the overture that opens the document, the showcase, and the finale that discards it.

The orientation reads and the one `doc_new` at the top; the presentation act - beauty shots, the
view verbs, the renames and the export/import round trips - which runs before the machining acts
so the CAM job is what the sweep ends on; and the discard. `reload_smoke` is the post-run beat
run() fires after every act: the add-in reload, which restarts the server and so can be no step.
"""

import copy
import json
import math
import os
import time
import urllib.request

from verify_core import (
    BASE, EXPORT_DIR, MCP, NOTE_MAX, SERVER_NAME, SVG_PATH, _RECALL, _activated, _bound_on_harness,
    _ctx_get,
    _document_closed, _document_read, _exported_bytes, _extruded, _fg, _home_address,
    _home_document, _imported_curves, _imported_sketches, _made_component, _made_component_inactive,
    _component_metadata, _measured,
    _metadata_set,
    _new_document, _near, _num, _param_added, _param_deleted, _param_read, _param_set_to, _recall, _refused, _watch, facade)
from verify_layout import _DRIFT_CHUNKS, drift_row
from verify_acts_model_sweep import (
    _retire_compare, _retire_design_state, _retire_material_state, _sweep_mode_shape, _sweep_mode_box_equal)


def _kernel_rules_present(p, field="kernel"):
    """Check the five kernel rules and their applicability fields in a guidance reply."""
    rules = p.get(field) or []
    return ([r.get("id") for r in rules] == [
        "declare-acceptance-and-interfaces", "sequence-is-the-design",
        "encode-intended-changeability", "build-and-observe-in-milestones",
        "compare-the-artifact-with-acceptance"]
        and all(r.get("when") and r.get("do") and r.get("except") and r.get("scenarios")
                and r.get("prove")
                and all(step.get("tool") and step.get("observe") for step in r["prove"])
                for r in rules))


_SMALL_EDIT_NATIVE = """import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    matches = [o for o in design.rootComponent.allOccurrences if o.fullPathName == 'EditTarget:1']
    assert len(matches) == 1
    occ = matches[0]
    assert app.activeDocument.dataFile is None
    body = occ.component.bRepBodies.item(0)
    def color(a):
        if a is None: return None
        for p in a.appearanceProperties:
            if type(p).__name__ == 'ColorProperty' and p.id == 'opaque_albedo':
                c = p.value
                return {'name': a.name, 'id': a.id, 'rgb': [int(c.red), int(c.green), int(c.blue)]}
        return {'name': a.name, 'id': a.id, 'rgb': None}
    def assignment(b):
        row = {'body': b.name}
        unavailable = {}
        for field, read in (('material', lambda: b.material.name),
                            ('appearance', lambda: b.appearance.name),
                            ('appearance_source_type', lambda: int(b.appearanceSourceType)),
                            ('opacity', lambda: b.opacity), ('visible_opacity', lambda: b.visibleOpacity)):
            try: row[field] = read()
            except Exception as exc:
                row[field] = None
                unavailable[field] = str(exc) or type(exc).__name__
        value = row.get('appearance_source_type')
        labels = [name for name in dir(adsk.core.AppearanceSourceTypes)
                  if not name.startswith('_') and name != 'thisown'
                  and isinstance(getattr(adsk.core.AppearanceSourceTypes, name), int)
                  and getattr(adsk.core.AppearanceSourceTypes, name) == value]
        row['appearance_source'] = labels[0] if len(labels) == 1 else None
        if row['appearance_source'] is None: unavailable['appearance_source'] = 'enum label unread'
        row['unavailable'] = unavailable
        return row
    print(json.dumps({'opacity': occ.component.opacity, 'occurrence': color(occ.appearance),
        'body': color(body.appearance), 'proxy_body': color(occ.bRepBodies.item(0).appearance),
        'assignment_body': assignment(body), 'assignment_proxy': assignment(occ.bRepBodies.item(0)),
        'document_asset': color(design.appearances.itemByName('ProbeGreen'))}))
"""


def _small_edit_assignment(p, before_key):
    """Check opt-in assignments against a separate native read of the same body placement."""
    native = (_RECALL.get(before_key) or {}).get("assignment_proxy")
    valid = isinstance(native, dict) and "mass" not in p and "x" not in p
    observed = {}
    for slice_name, fields in (("material", ("material",)),
                               ("appearance", ("appearance", "appearance_source_type",
                                               "appearance_source", "opacity", "visible_opacity"))):
        scope = p.get(slice_name) or {}
        rows = scope.get("bodies") or []
        observed[slice_name] = scope
        valid = (valid and scope.get("scope_complete") is True
                 and scope.get("truncated") is False and not scope.get("unavailable_census")
                 and not scope.get("unavailable_slots") and len(rows) == 1)
        if len(rows) == 1 and isinstance(native, dict):
            row = rows[0]
            valid = (valid and row.get("body") == native.get("body")
                     and row.get("occurrence") == "EditTarget:1"
                     and all(field in row and field in native and row[field] == native[field]
                             and bool((row.get("unavailable") or {}).get(field)) ==
                             bool((native.get("unavailable") or {}).get(field)) for field in fields))
    return _measured("actual body assignment and placed opacity without default slice", observed, valid)


def _small_edit_native_after(p, before):
    """Check native opacity and each appearance channel against the live entity and asset."""
    keys = ("opacity", "occurrence", "body", "proxy_body", "document_asset")
    got = {key: p.get(key) for key in keys}
    expected = {"opacity": .35, "occurrence": {"name": "ProbeGreen", "rgb": [0, 255, 0]},
                "body": {"name": "ProbeRed", "rgb": [255, 0, 0]},
                "proxy_body": {"name": "ProbeRed", "rgb": [255, 0, 0]},
                "document_asset": {"name": "ProbeGreen", "rgb": [0, 255, 0]}}
    checks = all(got[key] and all(got[key].get(field) == value
                  for field, value in expected[key].items()) for key in keys[1:])
    checks = (checks and _near(got["opacity"], expected["opacity"], 1e-6)
              and _near(before.get("opacity"), 1, 1e-6)
              and before.get("occurrence") is None)
    checks = checks and got["occurrence"].get("id") == got["document_asset"].get("id")
    return _measured("native opacity, occurrence/body colors and retained document asset",
                     {"before": before, "after": got}, checks)


def _small_edit_parameter_absent(p):
    rows = p.get("user_parameters") or []
    return _measured("malformed batch added no prefix", {"names": [r.get("name") for r in rows]},
                     isinstance(p.get("user_parameters"), list)
                     and not p.get("walk_truncated") and not p.get("truncated")
                     and p.get("user_parameter_count") == p.get("matched") == p.get("returned") == 0
                     and len(rows) == 0
                     and not any(r.get("name") == "ProbePrefix" for r in rows))


def _small_edit_native_prefix(p):
    rows = p.get("user_parameters") or []
    values = {r.get("name"): r.get("expression") for r in rows}
    expected = {"LegalBatchA": "3 mm", "LegalBatchB": "4 mm",
                "NativeExisting": "2 mm", "NativePrefix": "1 mm"}
    return _measured("duplicate-existing refusal kept the completed prefix", values,
                     isinstance(p.get("user_parameters"), list)
                     and not p.get("walk_truncated") and not p.get("truncated")
                     and p.get("user_parameter_count") == p.get("matched") == p.get("returned") == 4
                     and len(rows) == 4 and values == expected)


def _small_edit_asset(p):
    rows = ((p.get("appearances") or {}).get("document") or {}).get("entries") or []
    row = next((r for r in rows if r.get("name") == "ProbeGreen"), None)
    return _measured("ProbeGreen is present in the document appearance catalog", row,
                     row is not None and row.get("scope") == "document" and row.get("is_used") is True
                     and (p.get("appearances") or {}).get("document", {}).get("readable") is True
                     and not (p.get("appearances") or {}).get("document", {}).get("truncated"))


def _subject_visible(name, visible):
    """Read effective body visibility from the scoped design tree."""
    def check(p):
        row = (p.get("tree") or {}).get("tree") or {}
        bodies = row.get("bodies") or []
        return _measured(f"{name} body visibility restored to {visible}", {"bodies": bodies},
                         row.get("name") == name and bool(bodies)
                         and all(b.get("visible") is visible for b in bodies))
    return check


# --- the SECOND document: what puts doc_activate in the always-on receipt -----------------------
# doc_new mints an UNSAVED document with a session handle that addresses it exactly.

def _story_address(p):
    """Return the story document's exact handle while recording the open count."""
    _RECALL["open_before"] = p.get("open_count")
    return _home_address(p)


def _home_cloud_identity_unavailable(p):
    """Require the current cloud identity and both dependent slices to stay unknown."""
    active = p.get("active") or {}
    versions, used_in = p.get("versions") or {}, p.get("used_in") or {}
    exceptions = (p.get("summary") or {}).get("exceptions") or []
    text = json.dumps({"active": active, "versions": versions, "used_in": used_in}).lower()
    return _home_document(p) and _measured(
        "no current cloud identity makes cloud history and where-used unavailable",
        {"active": active, "versions": versions, "used_in": used_in,
         "exceptions": exceptions},
        active.get("has_data_file") is False and active.get("is_saved") is False
        and active.get("document_id") is None
        and "current cloud identity unavailable" in active.get("save_state", "")
        and any("data_file_unavailable" in e.get("unsaved", []) for e in exceptions)
        and versions.get("available") is False and used_in.get("available") is False
        and "could not be read" in versions.get("note", "")
        and "relationship is unknown" in used_in.get("note", "")
        and all(term in text for term in (
            "keep using document_handle", "retry doc_get",
            "if this is a new document, use doc_save_as"))
        and not any(claim in text for claim in (
            "never saved", "no version history exists", "cannot be referenced")))


def _scratch_gone_story_active(p):
    """doc_get after the scratch is closed: the story document is active at its original handle."""
    rows = [r for r in (p.get("open_documents") or []) if r.get("is_active")]
    here = _home_address(p) if len(rows) == 1 else None
    return _measured("the scratch is closed and the session is back on the story document",
                     {"open_count": p.get("open_count"), "open_before": _RECALL["open_before"],
                      "active": here, "story": _RECALL["story_doc"]},
                     p.get("open_count") == _RECALL["open_before"]
                     and here == _RECALL["story_doc"])


def _scratch_opened_beside_it(p):
    """doc_get after the scratch doc_new: the session holds one MORE document than it did, and the
    ACTIVE one is the scratch - a new document that replaced the story one would read the same
    count and the same address."""
    rows = [r for r in (p.get("open_documents") or []) if r.get("is_active")]
    here = _home_address(p) if len(rows) == 1 else None
    _RECALL["scratch_open_index"] = rows[0].get("open_index") if len(rows) == 1 else None
    return _measured("the scratch document opened BESIDE the story document",
                     {"open_count": p.get("open_count"), "open_before": _RECALL["open_before"],
                      "scratch": here, "story": _RECALL["story_doc"]},
                     _num(p.get("open_count"))
                     and p["open_count"] == _RECALL["open_before"] + 1
                     and here is not None and here != _RECALL["story_doc"])


def _scratch_active_in_capped_census(p):
    """Require the active scratch's full-read handle and original slot in one capped row."""
    rows = p.get("open_documents") or []
    row = rows[0] if len(rows) == 1 else {}
    return _measured("the active scratch survives a one-row document census",
                     {"row": row, "active": p.get("active"), "open_count": p.get("open_count"),
                      "truncated": p.get("truncated")},
                     len(rows) == 1 and row.get("is_active") is True
                     and row.get("document_handle") == _RECALL.get("scratch_doc")
                     and (p.get("active") or {}).get("document_handle") == _RECALL.get("scratch_doc")
                     and type(row.get("open_index")) is int
                     and row["open_index"] == _RECALL.get("scratch_open_index")
                     and row["open_index"] > 0
                     and type(p.get("open_count")) is int
                     and p["open_count"] == _RECALL.get("open_before") + 1
                     and p.get("truncated") is True)


def _handle_args(ctx, key, name, expression):
    """Build a parameter write pinned to the exact document saved in key."""
    return {"name": name, "expression": expression,
            "expect_document": _ctx_get(ctx, key, "the exact owned document handle")}


def _camera_target(p):
    """Return the independently read camera target, or None."""
    target = (p.get("view") or {}).get("target") or {}
    values = tuple(target.get(axis) for axis in ("x", "y", "z"))
    return values if all(type(value) in (int, float) for value in values) else None


# workspace_orient reports camera points to 0.001 cm; model_inspect retains more precision.
_CAMERA_TARGET_TOLERANCE_CM = 0.001
_VIEW_FOCUS_RUN = str(time.time_ns())


def _world_box(name):
    """Return a predicate for one current occurrence box in world-axis centimetres."""
    expected = f"occurrence '{name}'"

    def check(p):
        points = [p.get(key) or {} for key in ("min_point", "max_point")]
        values = [point.get(axis) for point in points for axis in ("x", "y", "z")]
        return (p.get("target") == expected and p.get("kind") == "occurrence"
                and p.get("frame") == "world axes (axis-aligned)"
                and p.get("oriented") is False and p.get("units") == "cm"
                and all(type(value) in (int, float) for value in values))
    return check


def _focus_center_cm(*keys):
    """Return the union center of recalled model boxes in camera centimetres."""
    boxes = [_RECALL.get(key) or {} for key in keys]
    if not boxes or any(box.get("units") != "cm" for box in boxes):
        return None
    points = []
    for box in boxes:
        lo, hi = box.get("min_point") or {}, box.get("max_point") or {}
        values = tuple((lo.get(axis), hi.get(axis)) for axis in ("x", "y", "z"))
        if any(type(value) not in (int, float) for pair in values for value in pair):
            return None
        points.append(values)
    return tuple((min(point[axis][0] for point in points)
                  + max(point[axis][1] for point in points)) / 2 for axis in range(3))


def _camera_focus_read(projection, *keys, differs_from=()):
    """Return a predicate comparing camera target to current independently read geometry."""
    def check(p):
        actual = _camera_target(p)
        expected = _focus_center_cm(*keys)
        previous = _focus_center_cm(*differs_from) if differs_from else None
        matches = (actual is not None and expected is not None
                   and all(abs(a - e) <= _CAMERA_TARGET_TOLERANCE_CM
                           for a, e in zip(actual, expected)))
        moved = (previous is None or any(abs(e - old) > _CAMERA_TARGET_TOLERANCE_CM
                                        for e, old in zip(expected or (), previous)))
        return _measured("camera target matches current focus geometry",
                         {"target_cm": actual, "expected_cm": expected,
                          "projection": (p.get("view") or {}).get("projection"),
                          "different_subject": moved},
                         matches and moved
                         and (p.get("view") or {}).get("projection") == projection)
    return check


def _sketch_placed(p):
    """sketch_get(include_entities, cm): a world frame and line endpoints to place the sketch by."""
    frame = p.get("frame") or {}
    lines = [e for e in (p.get("entities") or []) if e.get("type") == "line"]
    return _measured("the sketch reads a world frame and its lines", {"frame": frame,
                                                                     "lines": len(lines)},
                     frame.get("space") == "world" and bool(lines) and p.get("units") == "cm")


def _camera_on_sketch(sketch_key, box_key):
    """workspace_orient: the camera target lies ON the recalled sketch's world plane, inside its
    drawn lines in-plane, and inside the occurrence box model_inspect read independently."""
    def check(p):
        target = _camera_target(p)
        sk, box = _RECALL.get(sketch_key) or {}, _RECALL.get(box_key) or {}
        frame = sk.get("frame") or {}
        pts = [e.get(end) or {} for e in (sk.get("entities") or []) if e.get("type") == "line"
               for end in ("start", "end")]
        lo, hi = box.get("min_point") or {}, box.get("max_point") or {}
        tol = 0.01
        got = {"target_cm": target, "frame": frame, "box": [lo, hi]}
        if target is None or not pts or not all(
                frame.get(k) for k in ("origin_mm", "x_world", "y_world", "normal")):
            return _measured("camera target placed on the sketch", got, False)
        d = [t - o / 10.0 for t, o in zip(target, frame["origin_mm"])]
        u, v, w = (sum(a * b for a, b in zip(d, frame[k])) for k in ("x_world", "y_world", "normal"))
        xs, ys = [q.get("x") for q in pts], [q.get("y") for q in pts]
        in_box = all(_num(lo.get(a)) and lo[a] - tol <= t <= hi[a] + tol
                     for a, t in zip("xyz", target))
        got.update({"plane_offset_cm": w, "in_plane_cm": (u, v), "in_occurrence_box": in_box})
        return _measured("camera target placed on the sketch", got,
                         abs(w) <= tol and min(xs) - tol <= u <= max(xs) + tol
                         and min(ys) - tol <= v <= max(ys) + tol and in_box)
    return check


def _outframes(blank_path, shot_path, factor=2):
    """The named shot's PNG is at least `factor` times the parked, subject-less 'current' PNG - a
    frame holding only backdrop compresses to a few KB, a framed part to tens."""
    def check(payload):
        sizes = [os.path.getsize(f) if os.path.isfile(f) else None for f in (blank_path, shot_path)]
        return _measured("the named view framed the visible subject",
                         {"blank_bytes": sizes[0], "shot_bytes": sizes[1], "factor": factor},
                         f"file_path={shot_path}" in str(payload)
                         and all(_num(s) for s in sizes) and sizes[1] >= factor * sizes[0])
    return check


def _distinct_saved_cameras(names):
    """Return a predicate requiring list_views' rows for `names` to publish READABLE, DIFFERING
    eye_cm points - FSAE-0922-LIST-VIEWS-CAMERA-1: two saved views naming the same executor-visible
    camera would mean the per-row camera is not the view's OWN, whatever eye/target it names."""
    def check(p):
        rows = {v.get("name"): (v.get("camera") or {}).get("eye_cm") or {}
                for v in (p.get("named_views") or [])}
        eyes = [rows.get(n) for n in names]
        readable = all(all(type(e.get(ax)) in (int, float) for ax in ("x", "y", "z")) for e in eyes)
        return _measured("saved views publish distinct, readable cameras",
                         {"names": names, "eyes": eyes, "readable": readable},
                         readable and eyes[0] != eyes[1])
    return check


def _retained_png(path, at_least=1):
    """Return a predicate requiring the requested screenshot file to hold at least 'at_least' bytes
    (a blank frame of the fixture's backdrop is a few KB; a framed shot is tens of KB)."""
    def check(payload):
        size = os.path.getsize(path) if os.path.isfile(path) else None
        reported = f"file_path={path}" in str(payload)
        return _measured("PNG retained on disk",
                         {"file_path": path, "size_bytes": size, "at_least": at_least,
                          "reported": reported},
                         reported and _num(size) and size >= at_least)
    return check


# The scratch beat owns two handles, proves wrong-tab and stale-handle refusals before mutation,
# then returns home and writes and reads on the surviving exact target.
_SCRATCH_DOCUMENT = [
    ("doc_get", {"include": ["default", "versions", "used_in"]},
     _home_cloud_identity_unavailable, ("story_doc", _recall("story_doc", _story_address))),
    ("doc_new", {}, _new_document, None),
    ("doc_get", {"max_results": 1000}, _scratch_opened_beside_it,
     ("scratch_doc", _recall("scratch_doc", _home_address))),
    ("doc_get", {"max_results": 1}, _scratch_active_in_capped_census, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "story_doc", "the story document")},
     _activated(), None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "scratch_doc", "the scratch document")},
     _activated(), None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "story_doc", "the story document")},
     _activated(), None),
    ("param_add", lambda c: _handle_args(c, "scratch_doc", "HandleWrong", "1 mm"),
     _refused("active_document_changed", "doc_activate"), None),
    ("param_get", {"name": "HandleWrong"}, _refused("HandleWrong"), None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "scratch_doc", "the scratch document")},
     _activated(), None),
    ("param_get", {"name": "HandleWrong"}, _refused("HandleWrong"), None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "story_doc", "the story document")},
     _activated(), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "scratch_doc", "the scratch document"),
                             "save_changes": False}, _document_closed, None),
    ("param_add", lambda c: _handle_args(c, "scratch_doc", "HandleClosed", "3 mm"),
     _refused("unknown_document_handle", "doc_get"), None),
    ("param_get", {"name": "HandleClosed"}, _refused("HandleClosed"), None),
    ("doc_get", {}, _scratch_gone_story_active, None),
    ("param_add", lambda c: _handle_args(c, "story_doc", "HandleRecovered", "2 mm"),
     _param_added("HandleRecovered", 2), None),
    ("param_get", {"name": "HandleRecovered"}, _param_read("HandleRecovered", 2), None),
    ("param_delete", {"name": "HandleRecovered"}, _param_deleted("HandleRecovered"), None),
    ("param_get", {"name": "HandleRecovered"}, _refused("HandleRecovered"), None),
]


def _dxf_layer_sketch(p):
    """Parks the first DXF-imported sketch's name ('0', its layer) for the numeric-reference rows."""
    names = [c.get("name") for c in (p.get("created") or []) if c.get("name")]
    _RECALL["dxf_sketch"] = names[0] if names else None
    return _imported_sketches(p)


def _timeline_rows(p):
    return (p.get("timeline") or {}).get("timeline") or []


def _numref_shape(p):
    """design_get: the occurrence sits at index 0, the digit-named sketch once at index 1 inside it."""
    rows = _timeline_rows(p)
    name = _RECALL.get("dxf_sketch")
    seat = [r for r in rows if r.get("index") == 0]
    sk = [r for r in rows if r.get("name") == name]
    ok = (isinstance(name, str) and name.isascii() and name.isdecimal() and len(seat) == 1
          and seat[0].get("type") == "Occurrence" and len(sk) == 1 and sk[0].get("index") == 1
          and bool(sk[0].get("component")))
    if ok:
        _RECALL["numref_seat"] = seat[0].get("name")
        _RECALL["numref_sketch_at"] = f"{sk[0]['component']}/{name}@1"
        _RECALL["numref_count"] = (p.get("timeline") or {}).get("count")
    return _measured("an occurrence at index 0 and a digit-named sketch at index 1",
                     {"name": name, "seat": [r.get("name") for r in seat], "sketch": sk[:1]}, ok)


def _numref_bare_delete(c):
    """design_delete_feature args: the imported sketch's bare digit name, also timeline index 0."""
    return {"feature": _RECALL["dxf_sketch"]}


def _numref_listed_delete(c):
    """design_delete_feature args: the sketch's candidate exactly as the refusal lists it."""
    return {"feature": _RECALL["numref_sketch_at"]}


def _numref_untouched(p):
    """design_get after the refusal: the count and the occurrence at index 0 both hold."""
    rows = _timeline_rows(p)
    count = (p.get("timeline") or {}).get("count")
    seat = [r.get("name") for r in rows if r.get("index") == 0]
    return _measured("timeline untouched by the refusal",
                     {"count": count, "before": _RECALL.get("numref_count"), "seat": seat},
                     _num(count) and count == _RECALL["numref_count"]
                     and seat == [_RECALL["numref_seat"]])


def _numref_sketch_deleted(p):
    """The listed candidate deleted exactly the sketch at index 1 and nothing else."""
    return _measured("the digit-named sketch alone deleted",
                     {"feature": p.get("feature"), "index": p.get("index"), "also": p.get("also_deleted")},
                     p.get("deleted") is True and p.get("feature") == _RECALL["dxf_sketch"]
                     and p.get("index") == 1 and p.get("also_deleted") == [])


def _numref_occurrence_kept(p):
    """design_get(tree, timeline) after the delete: the occurrence node stands, the sketch is gone, count -1."""
    rows = _timeline_rows(p)
    count = (p.get("timeline") or {}).get("count")
    seat = [r.get("name") for r in rows if r.get("index") == 0]
    nodes = [n.get("name") for n in ((p.get("tree") or {}).get("children") or [])]
    return _measured("the occurrence kept, the sketch gone, count -1",
                     {"count": count, "before": _RECALL.get("numref_count"), "seat": seat, "nodes": nodes},
                     _num(count) and count == _RECALL["numref_count"] - 1
                     and seat == [_RECALL["numref_seat"]]
                     and not any(r.get("name") == _RECALL["dxf_sketch"] for r in rows)
                     and nodes == [_RECALL["numref_seat"].strip()])


def _numref_grouped(p):
    """design_get while NumRefG is collapsed: the occurrence at 0, one group row over 2 unlisted members."""
    rows = _timeline_rows(p)
    name = _RECALL.get("dxf_sketch")
    seat = [r.get("name") for r in rows if r.get("index") == 0]
    group = [r for r in rows if r.get("name") == "NumRefG"]
    ok = (seat == [_RECALL["numref_seat"]] and len(group) == 1
          and group[0].get("is_collapsed") is True and group[0].get("member_count") == 2
          and not any(r.get("name") == name for r in rows))
    if ok:
        _RECALL["numref_grouped_count"] = (p.get("timeline") or {}).get("count")
    return _measured("NumRefG collapsed over the digit-named sketch and its sibling",
                     {"seat": seat, "group": group[:1],
                      "sketch_rows": [r for r in rows if r.get("name") == name]}, ok)


def _numref_untouched_grouped(p):
    """design_get after the hidden-twin refusal: the grouped count and the occurrence at 0 hold."""
    rows = _timeline_rows(p)
    count = (p.get("timeline") or {}).get("count")
    seat = [r.get("name") for r in rows if r.get("index") == 0]
    return _measured("timeline untouched by the hidden-twin refusal",
                     {"count": count, "before": _RECALL.get("numref_grouped_count"), "seat": seat},
                     _num(count) and count == _RECALL["numref_grouped_count"]
                     and seat == [_RECALL["numref_seat"]])


def _numref_ungrouped(p):
    """design_get after the ungroup: the count and the sketch's index-1 seat are back, no group row."""
    rows = _timeline_rows(p)
    count = (p.get("timeline") or {}).get("count")
    name = _RECALL.get("dxf_sketch")
    sk = [r for r in rows if r.get("name") == name]
    return _measured("the digit-named sketch back at index 1 with no group row",
                     {"count": count, "before": _RECALL.get("numref_count"), "sketch": sk[:1]},
                     _num(count) and count == _RECALL["numref_count"] and len(sk) == 1
                     and sk[0].get("index") == 1
                     and not any(r.get("name") == "NumRefG" for r in rows))


def _numref_first_shape(p):
    """design_get: the digit-named sketch is the FIRST timeline item, one item follows it."""
    rows = _timeline_rows(p)
    name = _RECALL.get("dxf_sketch")
    ok = (len(rows) == 2 and rows[0].get("name") == name and rows[0].get("index") == 0
          and rows[1].get("index") == 1)
    if ok:
        _RECALL["numref_successor"] = rows[1].get("name")
    return _measured("the digit-named sketch at index 0 with one successor",
                     {"rows": [(r.get("index"), r.get("name")) for r in rows]}, ok)


def _numref_first_deleted(p):
    """A delete whose successor renumbers into the freed index still reports the delete."""
    return _measured("the index-0 sketch deleted and reported so",
                     {"deleted": p.get("deleted"), "feature": p.get("feature"), "index": p.get("index")},
                     p.get("deleted") is True and p.get("feature") == _RECALL["dxf_sketch"]
                     and p.get("index") == 0)


def _numref_successor_moved_up(p):
    """design_get after it: the successor now reads index 0 and no digit-named row remains."""
    rows = _timeline_rows(p)
    return _measured("the successor at index 0, the sketch gone",
                     {"rows": [(r.get("index"), r.get("name")) for r in rows]},
                     len(rows) == 1 and rows[0].get("index") == 0
                     and rows[0].get("name") == _RECALL.get("numref_successor"))


# A sketch's DXF lands on layer '0' and the import names the sketch after the layer, so the bare
# token '0' also names timeline index 0; two scratch shapes, each in its own document.
_NUMERIC_REFERENCE = [
    ("doc_new", {}, _new_document, None),
    ("doc_get", {}, _scratch_opened_beside_it, ("numref_doc", _home_address)),
    ("sketch_create", {"plane": "xy", "name": "Seed"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 5}],
                             "sketch_name": "Seed"}, "ok", None),
    ("design_export", {"format": "dxf", "file_path": EXPORT_DIR + "/numref_seed",
                       "dxf_sketch": "Seed"}, _exported_bytes, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "story_doc", "the story document")},
     _activated(), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "numref_doc", "the numeric-reference document"),
                             "save_changes": False}, _document_closed, None),
    # shape 1: an occurrence at index 0, the sketch '0' at index 1 inside it
    ("doc_new", {}, _new_document, None),
    ("doc_get", {}, _scratch_opened_beside_it, ("numref_doc", _home_address)),
    ("model_create_component", {"name": "NumRefBracket", "activate": True}, _made_component, None),
    ("doc_insert_import", {"file_path": EXPORT_DIR + "/numref_seed.dxf", "format": "dxf",
                           "plane": "xy"}, _dxf_layer_sketch, None),
    ("sketch_create", {"plane": "xy", "name": "NumRefSecond"}, "ok", None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _numref_shape, None),
    # the sketch and its sibling collapsed into a group: the bare "0" still hits index 0, and the
    # refusal names the group and the ungroup call instead of taking the occurrence
    ("design_edit_timeline",
     lambda c: {"action": "group", "name": "NumRefG", "feature": _RECALL["numref_sketch_at"],
                "end_feature": "NumRefBracket/NumRefSecond"},
     lambda p: p.get("grouped") is True and p.get("group") == "NumRefG", None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _numref_grouped, None),
    # the hidden-twin refusal and a listed address's group miss, through the shared kind
    ("form_get", {"form": "0", "include": ["cage"]},
     _refused("'0' matches NumRefBracket:1@0 and also names an item inside the collapsed timeline "
              "group 'NumRefG'", "design_edit_timeline(action='ungroup', feature='NumRefG')"), None),
    ("form_get", {"form": "NumRefBracket/0@1", "include": ["cage"]},
     _refused("'NumRefBracket/0' is inside the collapsed timeline group 'NumRefG'",
              "design_edit_timeline(action='ungroup', feature='NumRefG')"), None),
    ("design_delete_feature", _numref_bare_delete,
     _refused("'0' matches NumRefBracket:1@0 and also names an item inside the collapsed timeline "
              "group 'NumRefG'", "design_edit_timeline(action='ungroup', feature='NumRefG')"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _numref_untouched_grouped, None),
    ("design_edit_timeline", {"action": "ungroup", "feature": "NumRefG"},
     lambda p: p.get("ungrouped") is True, None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _numref_ungrouped, None),
    ("design_delete_feature", _numref_bare_delete,
     _refused("matches 2 timeline objects", "(NumRefBracket:1@0, NumRefBracket/0@1)",
              "exactly as listed"), None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _numref_untouched, None),
    ("design_delete_feature", _numref_listed_delete, _numref_sketch_deleted, None),
    ("design_get", {"include": ["tree", "timeline"], "max_results": 2000}, _numref_occurrence_kept, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "story_doc", "the story document")},
     _activated(), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "numref_doc", "the numeric-reference document"),
                             "save_changes": False}, _document_closed, None),
    # shape 2: the sketch '0' at index 0 with one successor
    ("doc_new", {}, _new_document, None),
    ("doc_get", {}, _scratch_opened_beside_it, ("numref_doc", _home_address)),
    ("doc_insert_import", {"file_path": EXPORT_DIR + "/numref_seed.dxf", "format": "dxf",
                           "plane": "xy"}, _dxf_layer_sketch, None),
    ("sketch_create", {"plane": "xy", "name": "After"}, "ok", None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _numref_first_shape, None),
    ("design_delete_feature", _numref_bare_delete, _numref_first_deleted, None),
    ("design_get", {"include": ["timeline"], "max_results": 2000}, _numref_successor_moved_up, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "story_doc", "the story document")},
     _activated(), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "numref_doc", "the numeric-reference document"),
                             "save_changes": False}, _document_closed, None),
    ("doc_get", {}, _scratch_gone_story_active, None),
]


def _target_design(p):
    """Return the complete small targeting fixture's tree and indexed history."""
    tree, tl = p.get("tree") or {}, p.get("timeline") or {}
    nodes, rows = tree.get("children"), tl.get("timeline")
    valid = (isinstance(nodes, list) and tree.get("child_count") == len(nodes)
             and tree.get("truncated") is False and tree.get("children_truncated") is False
             and not tree.get("root_bodies") and not tree.get("root_bodies_truncated")
             and isinstance(rows, list) and tl.get("count") == tl.get("returned") == len(rows)
             and type(tl.get("marker_position")) is int and 0 <= tl["marker_position"] <= len(rows)
             and not tl.get("truncated") and isinstance(tl.get("groups"), dict)
             and (tl.get("summary") or {}).get("states") == {"healthy": sum(
                 r.get("member_count", 1) for r in rows)} and tl["summary"].get("exceptions") == []
             and all(type(r.get("index")) is int and r["index"] == i and r.get("name") and r.get("type")
                     for i, r in enumerate(rows)))
    for n in nodes or []:
        valid = (valid and n.get("component") and n.get("full_path") and n.get("handle")
                 and n.get("child_count") == 0 and not n.get("children_truncated")
                 and type(n.get("body_count")) is int and n["body_count"] == len(n.get("bodies", []))
                 and not n.get("bodies_truncated") and all(b.get("name") and b.get("handle")
                     and type(b.get("is_solid")) is bool and type(b.get("visible")) is bool
                     for b in n.get("bodies", [])))
    valid = valid and len({n.get("full_path") for n in nodes or []}) == len(nodes or [])
    valid = valid and sum(n.get("body_count", 0) for n in nodes or []) == 1
    return {"tree": tree, "timeline": tl} if valid else None


def _target_material(p):
    """Read the independent 10 mm cube's actual material and world-axis bounds."""
    mass = p.get("mass") or {}
    bodies = mass.get("per_body") or []
    values = [p.get(a) for a in "xyz"] + [mass.get("volume"), mass.get("area")]
    valid = (p.get("target") == "occurrence 'Witness:1'" and p.get("units") == "mm"
             and p.get("frame") == "world axes (axis-aligned)" and len(bodies) == 1
             and mass.get("per_body_count") == 1 and mass.get("per_body_truncated") is False
             and bodies[0].get("body") and bodies[0].get("is_solid") is True
             and bodies[0].get("lump_count") == 1 and _num(bodies[0].get("volume"))
             and abs(bodies[0]["volume"] - 1000) < .001
             and all(_num(a) and abs(a-b) < .001 for a, b in zip(values, [10, 10, 10, 1000, 600])))
    bounds = [p.get(k, {}).get(a) for k in ("min_point", "max_point") for a in "xyz"]
    return {"mass": mass, "bounds": bounds} if valid and all(_num(v) for v in bounds) else None


def _target_sketch(p, owner, name, radius=None):
    """Read all disclosed sketch geometry and flags, retaining only stable selector-free facts."""
    counts, entities = p.get("counts"), p.get("entities")
    valid = (p.get("component") == owner and p.get("sketch") == name and p.get("units") == "mm"
             and isinstance(counts, dict) and all(type(n) is int and n >= 0 for n in counts.values())
             and isinstance(entities, list) and sum(counts.values()) == len(entities)
             and p.get("truncated") is False and not p.get("profiles_stale")
             and not p.get("timeline_marker_unrestored") and isinstance(p.get("frame"), dict))
    for e in entities or []:
        fields = {"line": ("start", "end"), "circle": ("center",), "point": ("position",)}.get(e.get("type"))
        valid = valid and fields is not None and all(isinstance(e.get(k), dict) and e[k]
                  and all(_num(v) for v in e[k].values()) for k in fields or ())
        if e.get("type") == "circle":
            valid = valid and _num(e.get("radius")) and e["radius"] > 0
    for count, key in (("constraint_count", "constraints"), ("dimension_count", "dimensions"), ("profile_count", "profiles")):
        valid = valid and type(p.get(count)) is int and isinstance(p.get(key), list) and p[count] == len(p[key])
    if radius is not None:
        circles = [e for e in entities or [] if e.get("type") == "circle"]
        valid = valid and len(circles) == 1 and circles[0].get("center") == {"x": 30.0, "y": 20.0}
        valid = valid and circles[0].get("radius") == radius
    if not valid:
        return None
    return {"entities": [{k: v for k, v in e.items() if k != "handle"} for e in entities],
            "profiles": [{k: v for k, v in r.items() if k != "handle"} for r in p["profiles"]],
            **{k: p[k] for k in ("counts", "constraints", "dimensions", "frame")}}


def _target_listing(p, sketches, baseline=None, removed=None):
    """Require every expected current sketch and retain its disclosed counts and visibility."""
    rows = p.get("sketches")
    if (not isinstance(rows, list) or p.get("sketch_count") != len(rows) or p.get("truncated")
            or sorted((r.get("component"), r.get("name")) for r in rows) != sorted(sketches)
            or not all(type(r.get("is_visible")) is bool for r in rows)):
        return None
    if baseline:
        prior = _RECALL.get(baseline)
        if prior is None or rows != [r for r in prior if (r["component"], r["name"]) != removed]:
            return None
    return rows


def _target_document(p):
    """Read the owned coupon's actual saved/modified flags and complete open-document identities."""
    active, rows = p.get("active") or {}, p.get("open_documents")
    if (active.get("document_handle") != _RECALL.get("target_doc") or active.get("has_data_file") is not False
            or any(type(active.get(k)) is not bool for k in ("is_saved", "is_modified"))
            or not isinstance(rows, list) or p.get("open_count") != len(rows) or p.get("truncated")
            or not all(r.get("document_handle") and r.get("name") for r in rows)):
        return None
    return {"active": {k: active[k] for k in ("name", "document_handle", "is_saved", "is_modified")},
            "open": [(r["document_handle"], r["name"]) for r in rows]}


def _target_row(tool, args, key, extract, baseline=None):
    """Build one targeting read whose saved facts also enter the runner's actual context."""
    def check(p):
        facts = extract(p)
        return _measured(key, facts, facts is not None and (baseline is None or facts == _RECALL.get(baseline)))
    return (tool, args, check, (key, _recall(key, extract)))


def _target_history_change(key, owner, name, deleted=False):
    """Compare a roll or deletion against the independently read exact prior timeline."""
    def read(p):
        now, before = _target_design(p), _RECALL.get(key)
        if now is None or before is None:
            return None
        old = before["timeline"]
        hits = [r for r in old["timeline"] if (r.get("component"), r.get("name")) == (owner, name)]
        if len(hits) != 1:
            return None
        target = hits[0]
        if deleted:
            rows = [dict(r, index=i) for i, r in enumerate(r for r in old["timeline"] if r != target)]
            marker = min(old["marker_position"], len(rows))
        else:
            marker = target["index"]
            rows = [dict(r, is_rolled_back=True) if r["index"] >= marker else r for r in old["timeline"]]
        return now if (now["tree"] == before["tree"] and now["timeline"]["timeline"] == rows
                       and now["timeline"]["count"] == len(rows) and now["timeline"]["marker_position"] == marker
                       and now["timeline"]["groups"] == old["groups"]) else None
    return read


def _target_address(ctx, key, owner, name):
    """Acquire the current indexed address from a completed independent timeline read."""
    facts = _ctx_get(ctx, key, "the current full targeting timeline")
    hits = [r for r in facts["timeline"]["timeline"] if (r.get("component"), r.get("name")) == (owner, name)]
    if len(hits) != 1 or type(hits[0].get("index")) is not int:
        raise AssertionError("Target has no unique current timeline address")
    return f"{owner}/{name}@{hits[0]['index']}"


def _target_reads(tag, sketches, baseline=None, changed=None, grouped=False):
    """Read the finite targeting coupon's history, cube, current sketches and optional hidden group."""
    design = _target_design if changed is None else _target_history_change(*changed)
    rows = [_target_row("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                "tree_handles": True, "max_depth": 3, "max_results": 200}, tag + "_design", design,
                baseline + "_design" if baseline and changed is None else None),
            _target_row("model_inspect", {"target": "Witness:1", "include": ["default", "mass"],
                "per_body": True, "accuracy": "very_high", "units": "mm"}, tag + "_body", _target_material,
                baseline + "_body" if baseline else None),
            _target_row("sketch_get", {"max_results": 200}, tag + "_list",
                lambda p: _target_listing(p, [(o, n) for o, n, _ in sketches],
                    baseline + "_list" if baseline else None, tuple(changed[1:3]) if changed else None)),
            _target_row("doc_get", {"max_results": 1000}, tag + "_doc", _target_document,
                baseline + "_doc" if baseline else None)]
    for owner, name, radius in sketches:
        rows.append(_target_row("sketch_get", {"component": owner, "sketch_name": name,
                    "include_entities": True, "max_results": 200, "units": "mm"}, tag + owner + name,
                    lambda p, o=owner, n=name, r=radius: _target_sketch(p, o, n, r),
                    baseline + owner + name if baseline else None))
    if grouped:
        def group(p):
            tl = p.get("timeline") or {}
            members = tl.get("timeline") or []
            full = _RECALL.get(tag + "_design", {}).get("timeline", {}).get("timeline", [])
            gs = [r for r in full if r.get("name") == "HiddenPair"]
            return members if (len(gs) == 1 and gs[0].get("is_collapsed") is True and gs[0].get("member_count") == 2
                and len(members) == tl.get("returned") == 2 and not tl.get("truncated")
                and [(r.get("component"), r.get("name")) for r in members] == [("Hidden", "Twin"), ("Hidden", "Sibling")]
                and all(r.get("parent_group") == "HiddenPair" for r in members)) else None
        rows.append(_target_row("design_get", {"include": ["timeline"], "group": "HiddenPair", "max_results": 200},
                                tag + "_group", group, baseline + "_group" if baseline else None))
    rows.append(_target_row("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                "tree_handles": True, "max_depth": 3, "max_results": 200}, tag + "_settled", _target_design, tag + "_design"))
    return rows


def _target_circle(owner, name, radius):
    return [("sketch_create", {"plane": "xy", "name": name},
             lambda p: p.get("created") is True and p.get("sketch_name") == name and p.get("component") == owner, None),
            ("sketch_add_geometry", {"component": owner, "sketch_name": name, "units": "mm",
             "geometry": [{"kind": "circle", "cx": 30, "cy": 20, "radius": radius}]}, "ok", None)]


def _target_begin():
    return [("doc_new", {}, _new_document, None),
            ("doc_get", {}, _scratch_opened_beside_it, ("target_doc", _recall("target_doc", _home_address))),
            ("model_create_component", {"name": "Witness", "activate": True}, _made_component, None),
            ("sketch_create", {"plane": "xy", "name": "Cube"}, "ok", None),
            ("sketch_add_geometry", {"component": "Witness", "sketch_name": "Cube", "units": "mm",
             "geometry": [{"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]}, "ok", None),
            ("model_extrude", {"component": "Witness", "sketch_name": "Cube", "profile_index": 0,
                               "distance": 10, "operation": "new", "units": "mm"}, _extruded, None)]


def _target_end():
    return [("doc_activate", lambda c: {"name": _ctx_get(c, "story_doc", "the story document")}, _activated(), None),
            ("doc_close", lambda c: {"name": _ctx_get(c, "target_doc", "the owned targeting coupon"),
                                      "save_changes": False}, _document_closed, None),
            ("doc_get", {}, _scratch_gone_story_active, None)]


_TARGET_CUBE = [("Witness", "Cube", None)]


def _boolean_suppressed(p):
    """Check actual missing material and the sole suppressed feature against the baseline."""
    expected = copy.deepcopy(_RECALL.get("bool_seed_design"))
    if expected is None:
        return None
    nodes = expected["tree"]["children"]
    if len(nodes) != 1 or nodes[0].get("component") != "Witness":
        return None
    nodes[0]["body_count"] = 0
    nodes[0].pop("bodies", None)
    timeline = expected["timeline"]
    hits = [r for r in timeline["timeline"] if r.get("component") == "Witness"
            and r.get("type") == "ExtrudeFeature"]
    if len(hits) != 1:
        return None
    hits[0].update(is_suppressed=True, health="suppressed")
    timeline["summary"]["states"] = {"healthy": len(timeline["timeline"]) - 1, "suppressed": 1}
    actual = {"tree": p.get("tree"), "timeline": p.get("timeline")}
    return actual if actual == expected else None


def _boolean_reads(tag, baseline=None, suppressed=False):
    """Read the owned Boolean coupon's history, material and open-document census."""
    rows = [_target_row("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                "tree_handles": True, "max_depth": 3, "max_results": 200}, tag + "_design",
                _boolean_suppressed if suppressed else _target_design,
                baseline + "_design" if baseline else None),
            _target_row("doc_get", {"max_results": 1000}, tag + "_doc", _target_document,
                baseline + "_doc" if baseline else None)]
    if not suppressed:
        rows.append(_target_row("model_inspect", {"target": "Witness:1", "include": ["default", "mass"],
                "per_body": True, "accuracy": "very_high", "units": "mm"}, tag + "_body",
                _target_material, baseline + "_body" if baseline else None))
    return rows


def _favorite_parameter_state(p):
    """Return every readable user parameter's complete value/flag row without accepting a capped census."""
    rows = p.get("user_parameters")
    if (not isinstance(rows, list) or p.get("walk_truncated") or p.get("truncated")
            or p.get("user_parameter_count") != p.get("matched") or p.get("matched") != p.get("returned")
            or p.get("returned") != len(rows) or len({r.get("name") for r in rows}) != len(rows)
            or any(not r.get("name") or not isinstance(r.get("expression"), str) or not r["expression"]
                   or r.get("unit") != "mm" or not isinstance(r.get("comment"), str)
                   or type(r.get("favorite")) is not bool or not _num(r.get("value"))
                   or not _num(r.get("value_internal")) or r.get("value_units") != "mm" for r in rows)):
        return None
    return sorted(rows, key=lambda row: row["name"])


def _favorite_batch_rows():
    """Exercise nested favorite preflight and real Boolean effects on the existing owned coupon."""
    rows = []
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c: {**args, "expect_document": _ctx_get(c, "target_doc", "Boolean coupon")}, check, save))
    for name in ("ScratchFlag", "UntouchedFlag"):
        write("param_add", {"name": name, "expression": "10 mm", "unit": "mm", "favorite": False},
              lambda p, name=name: p.get("added") is True and (p.get("parameter") or {}).get("name") == name
              and p.get("favorite") is False,
              ("favorite_fixture", lambda p: p["parameter"]["name"]) if name == "ScratchFlag" else None)
    def census(tag, added=None):
        def state(p):
            actual, before = _favorite_parameter_state(p), _RECALL.get("favorite_baseline")
            if actual is None:
                return None
            if tag == "favorite_baseline":
                return actual if ([r["name"] for r in actual] == ["ScratchFlag", "UntouchedFlag"]
                    and all(r["favorite"] is False and r["value"] == 10 and r["value_internal"] == 1
                            and r["expression"] == "10 mm" and r["comment"] == "" for r in actual)) else None
            if not isinstance(before, list):
                return None
            expected_names = [r["name"] for r in before] + ([added[0]] if added else [])
            if sorted(r["name"] for r in actual) != sorted(expected_names):
                return None
            if any(r != old for old in before for r in actual if r["name"] == old["name"]):
                return None
            extra = [r for r in actual if r["name"] not in {old["name"] for old in before}]
            if added and (len(extra) != 1 or extra[0]["favorite"] is not added[1]
                          or extra[0]["expression"] != "2 mm" or extra[0]["value"] != 2
                          or extra[0]["value_internal"] != .2 or extra[0]["comment"] != ""):
                return None
            return actual
        rows.append(_target_row("param_get", {"include_generated": True, "max_results": 100}, tag, state))
        rows.extend(_boolean_reads(tag + "_witness", "bool_seed"))
    census("favorite_baseline")
    for prefix in (False, True):
        specs = ([{"name": "BatchPrefix", "expression": "2 mm", "unit": "mm", "favorite": False}] if prefix else [])
        specs.append({"name": "BatchFlag", "expression": "2 mm", "unit": "mm", "favorite": "false"})
        write("param_add", {"params": specs},
              _refused(f"params[{int(prefix)}].favorite='false'", "JSON true or false", "No parameters added"))
        census("favorite_refused_" + str(prefix))
    for suffix, favorite in (("Omitted", None), ("True", True), ("False", False)):
        name = "Batch" + suffix
        spec = {"name": name, "expression": "2 mm", "unit": "mm"}
        if favorite is not None:
            spec["favorite"] = favorite
        wanted = favorite is True
        write("param_add", {"params": [spec]}, lambda p, wanted=wanted: p.get("added_count") == 1
              and len(p.get("results") or []) == 1 and p["results"][0].get("favorite") is wanted)
        census("favorite_control_" + suffix, (name, wanted))
        write("param_delete", {"name": name}, lambda p, name=name: p.get("deleted") is True and p.get("name") == name)
        census("favorite_retired_" + suffix)
    for name in ("ScratchFlag", "UntouchedFlag"):
        write("param_delete", {"name": name}, lambda p, name=name: p.get("deleted") is True and p.get("name") == name)
    rows.append(("param_get", {"include_generated": True, "max_results": 100},
                 lambda p: _measured("all owned favorite parameters retired", p, _favorite_parameter_state(p) == []), None))
    rows.extend(_boolean_reads("favorite_all_retired", "bool_seed"))
    return rows


_BOOLEAN_FLAGS = _target_begin() + _boolean_reads("bool_seed")
_BOOLEAN_FLAGS += [
    ("design_get", {"include": ["tree"], "tree_handles": None},
     _refused("Invalid Boolean for 'tree_handles'", "Omit this optional key to use its default"), None),
    ("design_get", {"include": ["tree"]},
     lambda p: _measured("omitted Boolean uses the default", p, isinstance(p.get("tree"), dict)), None),
] + _boolean_reads("bool_null_omitted", "bool_seed")
for _bool_tool, _bool_args, _bool_path in [
    ("design_edit_timeline", lambda c: {"action": "suppress", "suppressed": "false",
        "feature": _target_address(c, "bool_seed_design", "Witness", "Extrude1")}, "suppressed"),
    ("doc_close", lambda c: {"close_all": "false", "save_changes": False,
        "expect_document": _ctx_get(c, "story_doc", "the inactive story document")}, "close_all"),
    ("doc_close", lambda c: {"name": _ctx_get(c, "target_doc", "the owned coupon"), "save_changes": "false",
        "expect_document": _ctx_get(c, "story_doc", "the inactive story document")}, "save_changes"),
    ("cam_post", lambda c: {"program_name": "BooleanGuardNonexistent", "output_folder": EXPORT_DIR,
        "overwrite": "false", "expect_document": _ctx_get(c, "story_doc", "the inactive story document")}, "overwrite"),
    ("form_create", lambda c: {"primitive": {"shape": "cylinder", "size": [10, 10], "spans": [8, 2],
        "capped": "false"}, "expect_document": _ctx_get(c, "story_doc", "the inactive story document")}, "primitive.capped"),
    # Untyped objects reach the handler, whose own gate refuses the string before any write.
    ("assembly_constrain", {"relationships": [{"snap_one": "Witness:1:top", "snap_two": "Witness:1:bottom",
        "flip": "false"}]}, "relationships[0].flip"),
    ("pmi_create", {"kind": "hole_note", "geometry": ["unresolved"], "flags": {"threaded": "false"}},
     "flags.threaded"),
    # The display object is checked with the flags, before the geometry resolves or a note exists.
    ("pmi_create", {"kind": "hole_note", "geometry": ["unresolved"],
                    "display": {"precision": 2, "leading_zeros": "false"}}, "display.leading_zeros"),
]:
    _BOOLEAN_FLAGS += [(_bool_tool, _bool_args,
        _refused("Invalid Boolean for " + repr(_bool_path), "'false'", "Use true or false."), None)]
    _BOOLEAN_FLAGS += _boolean_reads("bool_refused_" + _bool_path, "bool_seed")
# A Boolean value is refused before the geometry resolves, so the unresolvable geometry never answers.
_BOOLEAN_FLAGS += [("pmi_create", {"kind": "hole_note", "geometry": ["unresolved"], "values": {"depth": True}},
    _refused("'depth' must be a number (in 'units'), got True.", "No annotation was created."), None)]
_BOOLEAN_FLAGS += _boolean_reads("bool_refused_values", "bool_seed")
for _bool_tag, _bool_flag in [("true", {"suppressed": True}), ("omitted", {})]:
    _BOOLEAN_FLAGS += [("design_edit_timeline", lambda c, flags=_bool_flag: {"action": "suppress",
        "feature": _target_address(c, "bool_seed_design", "Witness", "Extrude1"), **flags},
        lambda p: p.get("is_suppressed") is True, None)]
    _BOOLEAN_FLAGS += _boolean_reads("bool_" + _bool_tag, suppressed=True)
    _BOOLEAN_FLAGS += [("design_edit_timeline", lambda c: {"action": "suppress", "suppressed": False,
        "feature": _target_address(c, "bool_seed_design", "Witness", "Extrude1")},
        lambda p: p.get("is_suppressed") is False, None)]
    _BOOLEAN_FLAGS += _boolean_reads("bool_restored_" + _bool_tag, "bool_seed")
_BOOLEAN_FLAGS += _favorite_batch_rows() + _target_end()

_TARGET_CONFIRMATION = _target_begin() + [
    ("model_create_component", {"name": "Suffix", "activate": True}, _made_component, None),
] + _target_circle("Suffix", "Tail", 3) + _target_reads("tc_end", _TARGET_CUBE + [("Suffix", "Tail", 3)]) + [
    ("design_edit_timeline", lambda c: {"action": "roll", "feature": _target_address(c, "tc_end_design", "Suffix", "Tail"),
                                        "to": "before"}, lambda p: p.get("rolled") is True, None),
] + _target_reads("tc_rolled", _TARGET_CUBE, "tc_end", ("tc_end_design", "Suffix", "Tail", False)) + [
    ("design_edit_timeline", {"action": "delete_after_marker", "confirm_delete_after_marker": False},
     _refused("Refusing:", "DISCARDS 1 timeline item(s)", "confirm_delete_after_marker=true"), None),
] + _target_reads("tc_false", _TARGET_CUBE, "tc_rolled") + [
    ("design_edit_timeline", {"action": "delete_after_marker", "confirm_delete_after_marker": "false"},
     _refused("Invalid Boolean for 'confirm_delete_after_marker'", "'false'", "Use true or false."), None),
] + _target_reads("tc_string", _TARGET_CUBE, "tc_rolled") + [
    ("design_edit_timeline", {"action": "delete_after_marker", "confirm_delete_after_marker": True},
     lambda p: (p.get("deleted_after_marker") is True and p.get("deleted_timeline_entries") == 1
                and p.get("retained_prefix_confirmed") is True), None),
] + _target_reads("tc_deleted", _TARGET_CUBE, "tc_rolled", ("tc_rolled_design", "Suffix", "Tail", True)) + _target_end()


_TARGET_GROUP_TAIL = _target_begin() + [
    ("model_create_component", {"name": "Suffix", "activate": True}, _made_component, None),
] + _target_reads("tg_base", _TARGET_CUBE) + _target_circle("Suffix", "DiscardCircleA", 3) + _target_circle("Suffix", "DiscardCircleB", 4) + [
    ("design_edit_timeline", {"action": "group", "feature": "Suffix/DiscardCircleA", "end_feature": "Suffix/DiscardCircleB",
                              "name": "DiscardTail"}, lambda p: p.get("member_count") == 2, None),
    ("design_get", {"include": ["timeline"]},
     lambda p: (len([r for r in _timeline_rows(p) if r.get("name") == "DiscardTail"
                    and r.get("member_count") == 2 and r.get("is_collapsed") is True]) == 1), None),
    ("design_edit_timeline", {"action": "roll", "feature": "DiscardTail", "to": "before"},
     lambda p: p.get("rolled") is True, None),
    ("design_edit_timeline", {"action": "delete_after_marker"},
     _refused("DISCARDS 2 timeline item(s)", "DiscardTail", "Nothing was deleted"), None),
    ("design_edit_timeline", {"action": "delete_after_marker", "confirm_delete_after_marker": True},
     lambda p: (p.get("deleted_after_marker") is True and p.get("deleted") == 2
                and p.get("deleted_timeline_entries") == 1 and p.get("retained_prefix_confirmed") is True), None),
] + _target_reads("tg_deleted", _TARGET_CUBE, "tg_base") + [
    ("design_edit_timeline", {"action": "delete_after_marker", "confirm_delete_after_marker": True},
     _refused("Nothing lies after the marker"), None),
] + _target_reads("tg_repeated", _TARGET_CUBE, "tg_base") + _target_end()

_TARGET_HIDDEN_GEOMETRY = _TARGET_CUBE + [("Hidden", "Twin", 3), ("Hidden", "Sibling", 4)]
_TARGET_HIDDEN = _target_begin() + [
    ("model_create_component", {"name": "Hidden", "activate": True}, _made_component, None),
] + _target_circle("Hidden", "Twin", 3) + _target_circle("Hidden", "Sibling", 4) + _target_reads("th_seed", _TARGET_HIDDEN_GEOMETRY) + [
    ("design_edit_timeline", lambda c: {"action": "group", "name": "HiddenPair",
     "feature": _target_address(c, "th_seed_design", "Hidden", "Twin"),
     "end_feature": _target_address(c, "th_seed_design", "Hidden", "Sibling")}, lambda p: p.get("grouped") is True, None),
    ("model_create_component", {"name": "Visible", "activate": True}, _made_component, None),
] + _target_circle("Visible", "Twin", 5) + _target_reads("th_before", _TARGET_HIDDEN_GEOMETRY + [("Visible", "Twin", 5)], grouped=True) + [
    ("design_delete_feature", {"feature": "Twin"}, _refused("'Twin' matches Visible/Twin@", "collapsed timeline group 'HiddenPair'"), None),
] + _target_reads("th_refused", _TARGET_HIDDEN_GEOMETRY + [("Visible", "Twin", 5)], "th_before", grouped=True) + [
    ("design_delete_feature", lambda c: {"feature": _target_address(c, "th_refused_design", "Visible", "Twin")},
     lambda p: p.get("deleted") is True and p.get("feature") == "Twin", None),
] + _target_reads("th_deleted", _TARGET_HIDDEN_GEOMETRY, "th_before", ("th_before_design", "Visible", "Twin", True), True) + _target_end()

_TARGET_SLASH_GEOMETRY = _TARGET_CUBE + [("X/Y", "Target", 3)]
_TARGET_SLASH = _target_begin() + [
    ("model_create_component", {"name": "X/Y", "activate": True}, _made_component, None),
] + _target_circle("X/Y", "Target", 3) + _target_reads("ts_before", _TARGET_SLASH_GEOMETRY) + [
    ("design_edit_timeline", {"action": "roll", "feature": "X/Y/Target", "to": "before"}, lambda p: p.get("rolled") is True, None),
] + _target_reads("ts_rolled", _TARGET_CUBE, "ts_before", ("ts_before_design", "X/Y", "Target", False)) + [
    ("design_edit_timeline", {"action": "roll", "to": "end"}, lambda p: p.get("rolled") is True, None),
] + _target_reads("ts_restored", _TARGET_SLASH_GEOMETRY, "ts_before") + [
    ("design_edit_timeline", lambda c: {"action": "roll", "to": "before",
     "feature": _target_address(c, "ts_restored_design", "X/Y", "Target")}, lambda p: p.get("rolled") is True, None),
] + _target_reads("ts_indexed", _TARGET_CUBE, "ts_before", ("ts_before_design", "X/Y", "Target", False)) + [
    ("design_edit_timeline", {"action": "roll", "to": "end"}, lambda p: p.get("rolled") is True, None),
] + _target_reads("ts_indexed_end", _TARGET_SLASH_GEOMETRY, "ts_before") + [
    ("model_create_component", {"name": "Literal", "activate": True}, _made_component, None),
] + _target_circle("Literal", "A/B", 4) + [
    ("model_create_component", {"name": "A", "activate": True}, _made_component, None),
] + _target_circle("A", "B", 5) + _target_reads("ts_collision", _TARGET_SLASH_GEOMETRY + [("Literal", "A/B", 4), ("A", "B", 5)]) + [
    ("design_delete_feature", {"feature": "A/B"}, _refused("matches 2 timeline objects", "Literal/A/B@", "A/B@"), None),
] + _target_reads("ts_refused", _TARGET_SLASH_GEOMETRY + [("Literal", "A/B", 4), ("A", "B", 5)], "ts_collision") + [
    ("design_delete_feature", lambda c: {"feature": _target_address(c, "ts_refused_design", "Literal", "A/B")},
     lambda p: p.get("deleted") is True and p.get("feature") == "A/B", None),
] + _target_reads("ts_deleted", _TARGET_SLASH_GEOMETRY + [("A", "B", 5)], "ts_collision",
                  ("ts_collision_design", "Literal", "A/B", True)) + _target_end()

def _timeline_cube_material(p):
    """Return the measured complete 20 mm cube material and bounds, or None when unread."""
    state = _retire_material_state(p)
    if (state is None or len(state["bodies"]) != 1
            or abs(state["shape"]["volume"] - 8000) > .001
            or abs(state["shape"]["area"] - 2400) > .001
            or any(abs(state["shape"][side][axis] - value) > .001
                   for side, value in (("min", 0), ("max", 20)) for axis in "xyz")):
        return None
    return state


def _timeline_cube_geometry(p):
    """Return the complete finite cube face-edge or vertex census without handle text."""
    rows = p.get("matches")
    vertex = p.get("kind_filter") == "vertex"
    if (p.get("units") != "mm" or not isinstance(rows, list)
            or p.get("match_count") != p.get("returned") or p.get("returned") != len(rows)
            or len(rows) != (8 if vertex else 18)):
        return None
    kinds = [r.get("kind") for r in rows]
    if (kinds.count("vertex") != 8 if vertex else
            kinds.count("planar_face") != 6 or kinds.count("line_edge") != 12):
        return None
    for row in rows:
        if (not isinstance(row.get("handle"), str) or not row["handle"]
                or not isinstance(row.get("position"), list) or len(row["position"]) != 3
                or any(not _num(v) or not math.isfinite(v) for v in row["position"])):
            return None
        if row["kind"] != "vertex":
            metric, value = ("area", 400) if row["kind"] == "planar_face" else ("length", 20)
            vector = row.get("normal" if metric == "area" else "direction")
            if (not _num(row.get(metric)) or not math.isfinite(row[metric]) or abs(row[metric] - value) > .001
                    or not isinstance(vector, list) or len(vector) != 3
                    or any(not _num(v) or not math.isfinite(v) for v in vector)):
                return None
    return sorted([{k: v for k, v in row.items() if k != "handle"} for row in rows],
                  key=lambda row: (row["kind"], row["position"]))


def _timeline_health_rows():
    """Read unavailable history in the owned base edit and converted direct cube without changing it."""
    rows = [("doc_get", {}, _home_document, ("timeline_home", _home_address)),
            ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                            "max_depth": 10, "max_results": 2000},
             _retire_compare("timeline_home_design", _retire_design_state, False), None),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "timeline_home", "home")},
             _new_document, ("timeline_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]
    def write(tool, args, check="ok"):
        rows.append((tool, lambda c: {**args, "expect_document": _ctx_get(c, "timeline_doc", "owned cube")}, check, None))
    write("sketch_create", {"name": "Witness", "plane": "xy"})
    write("sketch_add_geometry", {"sketch_name": "Witness", "units": "mm", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}]})
    write("model_extrude", {"sketch_name": "Witness", "distance": 20, "units": "mm", "operation": "new"}, _extruded)
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True})

    def snapshot(tag, count, after=False):
        direct = count is None
        def mode(p):
            detail = p.get("mode_detail") or {}
            valid = (all(k in p for k in ("feature_count", "timeline_healthy"))
                     and "timeline_feature_count" in detail
                     and p.get("design_type") == ("direct" if direct else "parametric")
                     and p.get("feature_count") == count and p.get("timeline_healthy") is (None if direct else True)
                     and detail.get("has_timeline") is (not direct) and detail.get("timeline_feature_count") == count
                     and (not direct or "model_base_feature(action='finish')" in p.get("note", "")))
            return p if valid else None
        rows.append(("design_get", lambda c: {"include": ["default", "mode"]},
                     _retire_compare("timeline_mode_" + tag, mode, after), None))
        rows.append(("model_inspect", lambda c: {"target": "", "include": ["default", "mass"],
                     "per_body": True, "accuracy": "very_high", "units": "mm"},
                     _retire_compare("timeline_cube_material", _timeline_cube_material, tag != "parametric" or after), None))
        for kind in ("", "vertex"):
            rows.append(("find_geometry", lambda c, kind=kind: {"target": "Body1", "units": "mm", "max_results": 100,
                         **({"kind": kind} if kind else {})},
                         _retire_compare("timeline_cube_" + kind, _timeline_cube_geometry, tag != "parametric" or after), None))
        if direct:
            rows.append(("design_get", lambda c: {"include": ["timeline"]}, _refused("no timeline", "not a parametric design"), None))
        else:
            def history(p):
                state = _retire_design_state(p)
                tl = (state or {}).get("timeline") or {}
                return state if (tl.get("count") == count and (tl.get("summary") or {}).get("states") == {"healthy": count}
                                 and (tl.get("summary") or {}).get("exceptions") == []) else None
            rows.append(("design_get", lambda c: {"include": ["tree", "timeline"], "tree_bodies": True,
                         "tree_handles": True, "max_depth": 10, "max_results": 2000},
                         _retire_compare("timeline_history_" + tag, history, after), None))

    def orient(count):
        def check(p):
            health, design = p.get("health") or {}, p.get("design") or {}
            unread = count is None
            expected = {"timeline_features": count, "timeline_errors": None if unread else 0,
                        "timeline_warnings": None if unread else 0, "timeline_suppressed": None if unread else 0,
                        "timeline_markers": None if unread else 0, "timeline_rolled_back": None if unread else False,
                        "is_healthy": None if unread else True}
            valid = (all(k in health and (health[k] is v if v is None or type(v) is bool else
                         type(health[k]) is int and health[k] == v) for k, v in expected.items())
                     and health.get("joint_count") == 0 and health.get("broken_joints") == []
                     and health.get("broken_relations") == [] and health.get("out_of_date_references") == []
                     and health.get("unresolved_references") == [] and design.get("bodies") == 1
                     and design.get("mode") == ("direct" if unread else "parametric")
                     and ("not observed zero/healthy history" in p.get("note", "")
                          and not p.get("note", "").startswith("No compute errors") if unread else
                          p.get("note", "").startswith("No compute errors")))
            return _measured("orientation qualifies only unavailable history", p, valid)
        return check
    for tag, count in (("parametric", 2), ("open_base", None), ("finished_base", 3), ("direct", None)):
        if tag == "open_base":
            write("model_base_feature", {"action": "start", "base_feature": "HealthScope"},
                  lambda p: p.get("editing") is True and p.get("base_feature") == "HealthScope" and p.get("open_scope_count") == 1)
        elif tag == "finished_base":
            write("model_base_feature", {"action": "finish", "base_feature": "HealthScope"},
                  lambda p: p.get("editing") is False and p.get("design_mode_now") == "parametric"
                  and p.get("open_scope_count") == 0 and [r.get("name") for r in p.get("closed_scopes") or []] == ["HealthScope"])
        elif tag == "direct":
            write("design_set_mode", {"target": "direct", "confirm_history_loss": True},
                  lambda p: p.get("converted") is True and p.get("history_discarded") is True and p.get("now") == "direct")
        snapshot(tag, count)
        rows.append(("workspace_orient", lambda c: {}, orient(count), None))
        snapshot(tag, count, True)
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "timeline_home", "home"),
               "expect_document": _ctx_get(c, "timeline_doc", "owned cube")}, _activated(), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "timeline_doc", "owned cube"), "save_changes": False,
               "expect_document": _ctx_get(c, "timeline_home", "home")}, _document_closed, None),
             ("design_get", lambda c: {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
               "max_depth": 10, "max_results": 2000}, _retire_compare("timeline_home_design", _retire_design_state, True), None)]
    return rows


def _disclosure_plane_state(p):
    """Return complete history/tree and independently indexed plane owners."""
    state = _retire_design_state(p)
    datums = p.get("datums") or {}
    rows = datums.get("datums") or []
    if (state is None or datums.get("match_count") != datums.get("returned") or len(rows) != 2
            or datums.get("returned") != 2 or datums.get("truncated") is not False):
        return None
    planes = [r for r in state["timeline"]["timeline"] if r.get("type") == "ConstructionPlane"]
    if (len(planes) != 2 or {(r.get("name"), r.get("component")) for r in planes}
            != {("PlaneTwin", "DatumA"), ("PlaneTwin", "DatumB")}):
        return None
    for datum in rows:
        owner = datum.get("component")
        if (owner not in ("DatumA", "DatumB") or datum.get("name") != "PlaneTwin"
                or datum.get("kind") != "construction_plane" or datum.get("placement_count") != 1
                or datum.get("occurrences") != [owner + ":1"] or datum.get("occurrences_truncated")
                or not any(row.get("index") == datum.get("timeline_index")
                           and row.get("component") == owner for row in planes)):
            return None
    return {**state, "datums": datums}


def _disclosure_poses(p):
    """Return the complete three empty placed components and their finite bases."""
    rows = p.get("occurrences") or []
    expected = {"DatumA:1": [30, 0, 0], "DatumB:1": [60, 0, 0], "EmptyFocus:1": [40, 0, 0]}
    if (p.get("units") != "mm" or p.get("occurrences_truncated") is not False
            or p.get("occurrence_count") != 3 or len(rows) != 3
            or {r.get("name") for r in rows} != set(expected)):
        return None
    for row in rows:
        if (row.get("body_count") != 0 or row.get("origin") != expected[row["name"]]
                or any(type(row.get(k)) is not bool for k in ("grounded", "ground_to_parent"))
                or any(not isinstance(row.get(k), list) or len(row[k]) != 3
                       or any(not _num(v) or not math.isfinite(v) for v in row[k])
                       for k in ("x_axis", "y_axis", "z_axis"))):
            return None
    return rows


def _disclosure_witness_material(p):
    """Return the full independently measured root cube material and finite bounds."""
    shape = _sweep_mode_shape(p)
    expected = {"min": dict.fromkeys("xyz", 0), "max": dict.fromkeys("xyz", 20)}
    if (p.get("units") != "mm" or p.get("lump_count") != 1
            or not _sweep_mode_box_equal(shape, expected)
            or not _num(shape["volume"]) or abs(shape["volume"] - 8000) > .001
            or not _num(shape["area"]) or abs(shape["area"] - 2400) > .001):
        return None
    return {"shape": shape, "mass": p["mass"]}


def _product_disclosure_rows():
    """Disclose datum owners, empty focus and handle lifetime in one owned scene."""
    rows = [("doc_get", {}, _home_document, ("disclosure_home", _home_address)),
            ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                            "tree_handles": True, "max_results": 2000},
             _retire_compare("disclosure_home_design", _retire_design_state, False), None),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "disclosure_home", "home")},
             _new_document, ("disclosure_doc", lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c: {**(args(c) if callable(args) else args),
                     "expect_document": _ctx_get(c, "disclosure_doc", "owned disclosure scene")}, check, save))
    write("param_add", {"name": "DisclosureHeight", "expression": "10 mm", "unit": "mm"},
          _param_added("DisclosureHeight", 10))
    for name, coords, distance, key in (("Witness", (0, 0, 20, 20), "20 mm", "disclosure_witness"),
                                         ("Stock", (100, 0, 110, 8), "DisclosureHeight", "disclosure_stock")):
        write("sketch_create", {"name": name, "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": name, "units": "mm", "geometry": [
            dict(zip(("kind", "x1", "y1", "x2", "y2"), ("rectangle", *coords)))]})
        write("model_extrude", {"sketch_name": name, "distance": distance, "operation": "new"},
              _extruded, (key, lambda p: p["result_bodies"][0]))
    for owner, x, z in (("DatumA", 30, 3), ("DatumB", 60, 7)):
        write("design_activate_component", {"occurrence": "root"})
        write("model_create_component", {"name": owner, "x": x, "activate": True, "units": "mm"}, _made_component)
        write("model_construction", {"kind": "plane", "mode": "offset", "plane": "xy",
              "offset": z, "name": "PlaneTwin", "units": "mm"}, lambda p, owner=owner: p.get("component") == owner
              and isinstance(p.get("handle"), str) and bool(p["handle"])
              and "pass it as 'plane' to sketch_create" in p.get("note", "")
              and "NAME instead" not in p.get("note", ""),
              ("disclosure_" + owner, lambda p: p["handle"]))
        rows.append(("find_geometry", lambda c, owner=owner: {"target": owner + ":1", "kind": "construction_plane",
                     "name": "PlaneTwin", "units": "mm", "max_results": 10},
                     lambda p, owner=owner, x=x, z=z: p.get("match_count") == p.get("returned") == 1
                     and p["matches"][0].get("position") == [x, 0, z]
                     and p["matches"][0].get("normal") == [0, 0, 1]
                     and p["matches"][0].get("occurrence") == owner + ":1", None))
        write("sketch_create", lambda c, owner=owner: {"name": owner + "Pick", "plane": _ctx_get(c, "disclosure_" + owner, "plane")},
              lambda p, owner=owner, x=x, z=z: p.get("component") == owner
              and (p.get("frame") or {}).get("space") == "world" and p["frame"].get("origin_mm") == [x, 0, z])
        rows.append(("sketch_get", lambda c, owner=owner: {"sketch_name": owner + "Pick", "component": owner + ":1", "include_entities": True},
                     lambda p, owner=owner, x=x, z=z: p.get("component") == owner
                     and (p.get("frame") or {}).get("space") == "world"
                     and p["frame"].get("origin_mm") == [x, 0, z]
                     and p["frame"].get("normal") == [0, 0, 1], None))
    write("design_activate_component", {"occurrence": "root"})
    write("model_create_component", {"name": "EmptyFocus", "x": 40, "activate": False, "units": "mm"}, _made_component_inactive)
    write("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": True})
    def unchanged(after=False):
        rows.append(("design_get", lambda c: {"include": ["tree", "timeline", "datums"], "tree_bodies": True,
                     "tree_handles": True, "max_results": 2000},
                     _retire_compare("disclosure_read_design", _disclosure_plane_state, after), None))
        rows.append(("assembly_get", lambda c: {"include": ["poses"], "units": "mm", "max_occurrences": 100},
                     _retire_compare("disclosure_read_poses", _disclosure_poses, after), None))
        rows.append(("model_inspect", lambda c: {"target": "", "include": ["default", "mass"], "per_body": True,
                     "units": "mm", "accuracy": "very_high"},
                     _retire_compare("disclosure_read_material", _retire_material_state, after), None))
        rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, "disclosure_witness", "cube"), "units": "mm", "max_results": 100},
                     _retire_compare("disclosure_witness_geometry", _timeline_cube_geometry, after), None))
    unchanged()
    rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "disclosure_witness", "cube"),
                 "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                 _retire_compare("disclosure_witness_material", _disclosure_witness_material, False), None))
    for fit in (True, False):
        def focus(p, fit=fit):
            a, note = p.get("applied") or {}, p.get("note", "")
            return (a.get("focus") == "EmptyFocus:1" and a.get("orientation") == "front"
                    and (a.get("no_measurable_size") is True and a.get("frame_ratio") is None
                         and "no measurable size" in note and "framed on" not in note if fit else
                         "WITHOUT zooming" in note and "attempt framing when the focus has measurable size" in note))
        write("view_set", {"action": "orient", "orientation": "front", "focus": "EmptyFocus:1", "fit": fit}, focus)
        rows.append(("workspace_orient", lambda c: {}, lambda p: _camera_target(p) == (0, 0, 0), None))
        unchanged(True)
    write("view_set", {"action": "orient", "orientation": "front", "fit": False},
          lambda p: "focus" not in (p.get("applied") or {}) and "Camera aimed" in p.get("note", ""))
    unchanged(True)
    write("view_set", {"action": "orient", "orientation": "front", "focus": "Witness", "fit": True},
          lambda p: "framed on 'Witness'" in p.get("note", "")
          and _num((p.get("applied") or {}).get("frame_ratio")) and p["applied"]["frame_ratio"] > 0)
    rows.append(("workspace_orient", lambda c: {}, lambda p: _camera_target(p) == (1, 1, 0), None))
    unchanged(True)
    rows.append(("sys_capability_map", {}, lambda p: any(r.get("family") == "find"
                 and r.get("entry_tool") == "find_geometry" and "short-lived" in r.get("summary", "")
                 and "re-find if stale" in r.get("summary", "") and "stable" not in r.get("summary", "")
                 for r in p.get("families") or []), None))
    write("param_set", {"name": "DisclosureHeight", "expression": "13 mm"}, _param_set_to("DisclosureHeight", 13))
    rows.append(("param_get", {"name": "DisclosureHeight"}, _param_read("DisclosureHeight", 13), None))
    rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "disclosure_stock", "driven box"),
                 "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                 lambda p: _num((p.get("mass") or {}).get("volume")) and abs(p["mass"]["volume"] - 1040) < .001
                 and [p.get(k) for k in "xyz"] == [10, 8, 13], None))
    def fresh_face(p):
        faces = [r for r in p["matches"] if r.get("kind") == "planar_face"
                 and r.get("position") == [10, 10, 20] and r.get("normal") == [0, 0, 1]]
        _measured("one fresh witness top face", faces, len(faces) == 1)
        return faces[0]["handle"]
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, "disclosure_witness", "fresh cube handles"), "units": "mm", "max_results": 100},
                 _retire_compare("disclosure_witness_geometry", _timeline_cube_geometry, True), ("disclosure_fresh_face", fresh_face)))
    rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "disclosure_fresh_face", "fresh witness top face"), "units": "mm"},
                 lambda p: p.get("kind") == "face" and p.get("oriented") is False
                 and p.get("min_point") == {"x": 0, "y": 0, "z": 20}
                 and p.get("max_point") == {"x": 20, "y": 20, "z": 20}
                 and p.get("center") == {"x": 10, "y": 10, "z": 20}, None))
    rows.append(("model_inspect", lambda c: {"target": _ctx_get(c, "disclosure_witness", "cube"),
                 "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                 _retire_compare("disclosure_witness_material", _disclosure_witness_material, True), None))
    write("param_set", {"name": "DisclosureHeight", "expression": "10 mm"}, _param_set_to("DisclosureHeight", 10))
    unchanged(True)
    # Namesake axes and points in two sub-components: each timeline row names the owner that
    # model_construction reported, read here after the plane-owner snapshots above are closed.
    datums = (("axis", "ConstructionAxis", "AxisTwin", {"mode": "two_planes", "plane": "xz", "plane2": "yz"}),
              ("point", "ConstructionPoint", "PointTwin",
               {"mode": "three_planes", "plane": "xy", "plane2": "xz", "plane3": "yz"}))
    for owner in ("DatumA", "DatumB"):
        write("design_activate_component", {"occurrence": owner + ":1"})
        for kind, _type, name, args in datums:
            write("model_construction", {"kind": kind, "name": name, "units": "mm", **args},
                  lambda p, owner=owner, kind=kind, name=name: p.get("component") == owner
                  and p.get("kind") == kind and p.get("name") == name and bool(p.get("handle")),
                  ("disclosure_" + kind + "_" + owner, _recall("disclosure_" + kind + "_" + owner,
                                                             lambda p: p.get("component"))))
    write("design_activate_component", {"occurrence": "root"})
    def datum_owners(p):
        tl = p.get("timeline") or {}
        got = [(r.get("type"), r.get("name"), r.get("component")) for r in tl.get("timeline") or []
               if r.get("type") in ("ConstructionAxis", "ConstructionPoint")]
        want = [(t, n, _RECALL.get("disclosure_" + k + "_" + o)) for o in ("DatumA", "DatumB")
                for k, t, n, _a in datums]       # creation order, which the timeline keeps
        return _measured("datum timeline owners match model_construction's component", {"rows": got, "want": want},
                         not tl.get("truncated") and tl.get("count") == tl.get("returned") and got == want
                         and {w[2] for w in want} == {"DatumA", "DatumB"})
    rows.append(("design_get", {"include": ["timeline"], "max_results": 2000}, datum_owners, None))
    rows += [("doc_activate", lambda c: {"name": _ctx_get(c, "disclosure_home", "home"),
                                        "expect_document": _ctx_get(c, "disclosure_doc", "owned scene")}, "ok", None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "disclosure_doc", "owned scene"), "save_changes": False,
                                      "expect_document": _ctx_get(c, "disclosure_home", "home")}, _document_closed, None),
             ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True,
                             "tree_handles": True, "max_results": 2000},
              _retire_compare("disclosure_home_design", _retire_design_state, True), None)]
    return rows


# --- ACT 13: SMALL EDIT SAFETY -----------------------------------------------------------------
_SMALL_EDITS = [
    ("design_set_metadata", {"target": "EditTarget", "part_number": "PN-SMALL-1",
                              "description": "small edit control"},
     _metadata_set("EditTarget", "PN-SMALL-1", "small edit control"), None),
    ("design_set_metadata", {"target": "EditTarget", "part_number": "PN-MUST-NOT-LAND",
                              "description": 123},
     _refused("'description'=123", "must be a string", "No metadata was changed"), None),
    ("design_get", {"include": ["metadata"]},
     _component_metadata("EditTarget", "PN-SMALL-1", "small edit control"), None),
    ("param_add", {"params": [{"name": "ProbePrefix", "expression": "1 mm"}, "oops"]},
     _refused("params[1] must be a dict", "No parameters added"), None),
    ("param_add", {"params": [{"name": "ProbePrefix", "expression": "1 mm"},
                                {"name": "Bad", "expression": 2}]},
     _refused("params[1].expression", "must be a string", "No parameters added"), None),
    ("param_add", {"params": [{"name": "ProbePrefix", "expression": "1 mm"},
                                {"name": "Bad", "expression": "2", "unit": 5}]},
     _refused("params[1].unit", "must be a string", "No parameters added"), None),
    ("param_add", {"params": [{"name": "ProbePrefix", "expression": "1 mm"},
                                {"name": "Bad", "expression": "2", "comment": 5}]},
     _refused("params[1].comment", "must be a string", "No parameters added"), None),
    ("param_add", {"params": [{"name": "ProbePrefix", "expression": "1 mm"},
                                {"name": 5, "expression": "2"}]},
     _refused("params[1].name", "must be a string", "No parameters added"), None),
    ("param_add", {"params": [{"name": "ProbePrefix", "expression": "1 mm"},
                                {"expression": "2"}]},
     _refused("params[1] is missing 'name'", "No parameters added"), None),
    ("param_add", {"params": [{"name": "ProbePrefix", "expression": "1 mm"},
                                {"name": "Bad"}]},
     _refused("params[1] is missing 'expression'", "No parameters added"), None),
    ("param_add", {"params": [{"name": "ProbePrefix", "expression": "1 mm"},
                                {"name": "Bad", "expression": ""}]},
     _refused("params[1].expression is empty", "No parameters added"), None),
    ("param_add", {"params": [{"name": "ProbePrefix", "expression": "1 mm"},
                                {"name": "", "expression": "2"}]},
     _refused("params[1].name is empty", "No parameters added"), None),
    ("param_get", {"include_generated": True, "max_results": 100},
     _small_edit_parameter_absent, None),
    ("param_add", {"params": [{"name": "LegalBatchA", "expression": "3 mm"},
                                {"name": "LegalBatchB", "expression": "4 mm"}]},
     lambda p: p.get("added_count") == 2 and len(p.get("results") or []) == 2, None),
    ("param_get", {"include_generated": True, "max_results": 100},
     lambda p: _measured("legal batch values read back",
         {r.get("name"): r.get("expression") for r in p.get("user_parameters") or []},
         all(any(r.get("name") == name and r.get("expression") == expression
                 for r in p.get("user_parameters") or [])
             for name, expression in (("LegalBatchA", "3 mm"), ("LegalBatchB", "4 mm")))), None),
    ("param_add", {"name": "NativeExisting", "expression": "2 mm"},
     _param_added("NativeExisting", 2), None),
    ("param_add", {"params": [{"name": "NativePrefix", "expression": "1 mm"},
                                {"name": "NativeExisting", "expression": "3 mm"}]},
     _refused("already exists", "1 added before this"), None),
    ("param_get", {"include_generated": True, "max_results": 100}, _small_edit_native_prefix, None),
    ("appearance_set", {"target": "EditTarget:1:Body1", "color": "#FF0000", "name": "ProbeRed"},
     lambda p: p.get("kind") == "body" and p.get("appearance") == "ProbeRed"
               and p.get("color_rgb") == [255, 0, 0] and p.get("applied_to") == ["Body1"], None),
    ("sys_execute_script", {"script": _SMALL_EDIT_NATIVE, "read_only": True},
     lambda p: _measured("pre-failure opacity and body color", p,
                         p.get("opacity") != .35 and (p.get("body") or {}).get("name") == "ProbeRed"
                         and (p.get("body") or {}).get("rgb") == [255, 0, 0]
                         and (p.get("proxy_body") or {}).get("name") == "ProbeRed"
                         and (p.get("proxy_body") or {}).get("rgb") == [255, 0, 0]
                         and p.get("document_asset") is None
                         and (p.get("occurrence") or {}).get("name") != "ProbeGreen"),
     ("small_edit_native_before", _recall("small_edit_native_before", lambda p: p))),
    ("model_inspect", {"target": "EditTarget:1:Body1", "include": ["material", "appearance"]},
     lambda p: _small_edit_assignment(p, "small_edit_native_before"), None),
    ("model_inspect", {"target": "EditTarget:1"},
     lambda p: _measured("default inspect does not disclose assignments", p,
                         "material" not in p and "appearance" not in p
                         and isinstance(p.get("x"), (int, float))), None),
    ("appearance_set", {"target": "EditTarget:1", "color": "#00FF00",
                         "opacity": 35, "name": "ProbeGreen"},
     _refused("reached NONE", "ProbeRed",
              "Component opacity now reads", "(before this call: 1.0)",
              "Occurrence appearance now reads {'name': 'ProbeGreen'"), None),
    ("design_get", {"include": ["appearances"], "name_filter": "ProbeGreen"},
     _small_edit_asset, None),
    ("sys_execute_script", {"script": _SMALL_EDIT_NATIVE, "read_only": True},
     lambda p: _small_edit_native_after(p, _RECALL["small_edit_native_before"]),
     ("small_edit_native_after", _recall("small_edit_native_after", lambda p: p))),
    ("model_inspect", {"target": "EditTarget:1", "include": ["material", "appearance"]},
     lambda p: _small_edit_assignment(p, "small_edit_native_after"), None),
    ("param_delete", {"name": "LegalBatchA"}, _param_deleted("LegalBatchA"), None),
    ("param_delete", {"name": "LegalBatchB"}, _param_deleted("LegalBatchB"), None),
    ("param_delete", {"name": "NativePrefix"}, _param_deleted("NativePrefix"), None),
    ("param_delete", {"name": "NativeExisting"}, _param_deleted("NativeExisting"), None),
]


# --- a library appearance and its clear, on a body and on one face ------------------------------

_AP_LIBRARY, _AP_NAME = "Fusion Additive Material Library", "Aluminum - Satin"


def _ap_body_reads(appearance=None, source=None, recall=None):
    """model_inspect: the one body's appearance and source, or the pair recalled under `recall`."""
    def check(p):
        scope = p.get("appearance") or {}
        rows = scope.get("bodies") or []
        got = (rows[0].get("appearance"), rows[0].get("appearance_source")) if len(rows) == 1 else None
        want = (_RECALL.get(recall) if recall else
                None if appearance is None and source is None else (appearance, source))
        return _measured("body appearance and its source", got,
                         scope.get("scope_complete") is True and scope.get("truncated") is False
                         and got is not None and None not in got
                         and (recall is None or want is not None)
                         and (want is None or tuple(want) == got))
    return check


def _ap_faces_args(ctx):
    """A read-only native read of the two saved faces' appearance and appearance source."""
    tokens = [str(ctx.get(key) or "").partition("|@")[0] for key in ("ap_top", "ap_side")]
    if not all(tokens):
        raise ValueError("the two face handles are not both readable")
    script = (
        "import adsk.core, adsk.fusion, json\n"
        "def run(context):\n"
        "    design=adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)\n"
        "    kinds=adsk.core.AppearanceSourceTypes\n"
        "    names={getattr(kinds,n):n for n in dir(kinds) if n.endswith('AppearanceSource')}\n"
        "    rows=[]\n"
        "    for token in " + repr(tokens) + ":\n"
        "        found=list(design.findEntityByToken(token))\n"
        "        face=adsk.fusion.BRepFace.cast(found[0]) if len(found)==1 else None\n"
        "        rows.append(None if face is None else\n"
        "            [face.appearance.name, names.get(face.appearanceSourceType)])\n"
        "    print(json.dumps({'faces':rows}))\n")
    return {"script": script, "read_only": True}


def _appearance_library_rows():
    """Assign a library appearance to a body and to one face, and clear each override again."""
    from verify_acts_sketch import _boxed, _scratch_rows, _script_reply
    rows, write, read, close = _scratch_rows("ap_doc")
    _boxed(write, "ApBase", (0, 0, 20, 10), 8, "ap_body")
    body = lambda c: _ctx_get(c, "ap_body", "the box")
    inspect = lambda c: {"target": body(c), "include": ["appearance"]}
    for key, at in (("ap_top", [10, 5, 8]), ("ap_side", [10, 0, 4])):
        read("find_geometry", lambda c, at=at: {"target": body(c), "kind": "planar_face",
                                                "nearest_to": at, "max_results": 1},
             lambda p: len(p.get("matches") or []) == 1, _fg(key))
    aluminium = (_AP_NAME, "BodyAppearanceSource")
    read("model_inspect", inspect,
         lambda p: _ap_body_reads()(p)
         and p["appearance"]["bodies"][0]["appearance_source"] == "MaterialAppearanceSource",
         ("ap_plain", _recall("ap_plain", lambda p: (
             p["appearance"]["bodies"][0]["appearance"],
             p["appearance"]["bodies"][0]["appearance_source"]))))
    read("design_get", {"include": ["appearances"], "library": _AP_LIBRARY, "name_filter": _AP_NAME},
         lambda p: [e.get("name") for e in p["appearances"].get("entries") or []] == [_AP_NAME])

    def paint(target, check, **args):
        write("appearance_set", lambda c: {"target": target(c), **args}, check)
    library = {"appearance": _AP_NAME, "library": _AP_LIBRARY}
    paint(body, _refused("'appearance' is a call of its own", "'color'"), color="#FF0000", **library)
    paint(body, _refused("carries no override of its own", "MaterialAppearanceSource"), clear=True)
    read("model_inspect", inspect, _ap_body_reads(recall="ap_plain"))
    paint(body, lambda p: p.get("applied") is True and p.get("appearance") == _AP_NAME
          and p.get("library") == _AP_LIBRARY
          and p.get("appearance_source") == "BodyAppearanceSource", **library)
    read("model_inspect", inspect, _ap_body_reads(*aluminium))
    paint(body, lambda p: p.get("cleared") is True and p.get("appearance_before") == _AP_NAME
          and p.get("appearance_source") == "MaterialAppearanceSource", clear=True)
    read("model_inspect", inspect, _ap_body_reads(recall="ap_plain"))
    # A face has no public appearance read, so the two faces are read natively and read-only.
    top = lambda c: _ctx_get(c, "ap_top", "the top face")
    plain = lambda p: ([[_RECALL["ap_plain"][0], "MaterialAppearanceSource"]] * 2
                       == _script_reply(p).get("faces"))
    read("sys_execute_script", _ap_faces_args, plain)
    paint(top, lambda p: p.get("kind") == "face"
          and p.get("appearance_source") == "FaceAppearanceSource", **library)
    read("sys_execute_script", _ap_faces_args,
         lambda p: _script_reply(p).get("faces") == [
             [_AP_NAME, "FaceAppearanceSource"],
             [_RECALL["ap_plain"][0], "MaterialAppearanceSource"]])
    read("model_inspect", inspect, _ap_body_reads(recall="ap_plain"))
    paint(top, lambda p: p.get("cleared") is True
          and p.get("appearance_source") == "MaterialAppearanceSource", clear=True)
    read("sys_execute_script", _ap_faces_args, plain)
    read("model_inspect", inspect, _ap_body_reads(recall="ap_plain"))
    close()
    return rows


_SMALL_EDITS += _appearance_library_rows()


# --- ACT 0: OVERTURE - orient, then open the first family document -----------------------------
_OVERTURE = [
    ("doc_new", {}, _new_document, None),
    ("workspace_orient", {}, "ok", ("fusion_version", lambda p: p["fusion_version"])),
    # the family map is a live registry walk: a family whose module failed to register is ABSENT
    # here, not merely uncounted, and every family it does list has to carry an entry tool.
    ("sys_capability_map", {},
     lambda p: ({"cam", "mesh", "model", "sketch", "surface", "view"}
                <= {f["family"] for f in p["families"]}
                and all(f["tool_count"] >= 1 and f["entry_tool"] for f in p["families"])
                and p["tool_count"] >= 150
                and any(row.get("tool") == "sys_execute_script"
                        and row.get("enable_path") == (
                            "Fusion Essentials Settings command -> MCP Server tab -> "
                            "'Allow AI scripts (unsafe)' checkbox")
                        for row in p["gated"]["tools"])), None),
    # the map publishes the address the server's socket bound: it has to be the one this run is
    # talking to, on the add-in's default port.
    ("sys_capability_map", {},
     lambda p: _bound_on_harness("sys_capability_map", p["bound"]), None),
    # the read stamp is for DOCUMENT reads: a tool that answers off the registry rather than the
    # active design carries no 'active_document' key at all (design_get's own beat in the FINALE is
    # the other half of this pair).
    ("sys_find_tool", {"query": "revolve"},
     lambda p: "active_document" not in p and p.get("tool_count", 0) > 0, None),
    ("sys_find_tool", {"query": "body"},
     lambda p: (p.get("tool_count", 0) > 0
                and "BodyRef" in {row.get("kind") for row in p.get("kinds", [])}
                and "tool's schema" in p.get("note", "")
                and "handle, name or index" in p.get("note", "")
                and not any(text in p.get("note", "") for text in ("CLAUDE.md", "_inputs.py", "hand-roll"))), None),
    ("sys_get_api_doc", {"searchPattern": "a+"}, _refused("unsupported repetition"), None),
    # the introspection FOUND the class in the module it lives in: an adsk submodule that would not
    # import is skipped silently, and the search then answers ok with nothing in it.
    ("sys_get_api_doc", {"searchPattern": "RevolveFeatures", "max_results": 3},
     lambda p: (any(c["name"] == "RevolveFeatures" and c["namespace"] == "adsk.fusion"
                    for c in p["classes"])
                and p["counts"]["classes"] == len(p["classes"])), None),
    # the packaged design guidance, the way a client with tools and no skill loader reads it: the
    # index, then ONE section - its rule records keyed by the ids the canonical document carries,
    # beside the content hash that says which version answered.
    ("sys_get_guidance", {},
     lambda p: (p.get("recipes") and all(r.get("id") and r.get("use_when") for r in p["recipes"])
                and all("steps" not in r for r in p["recipes"])
                and any(r.get("id") == "model" and "sheet metal" in r.get("use_when", "")
                        for r in p.get("sections", []))
                and _kernel_rules_present(p)), None),
    ("sys_get_guidance", {"section": "model"},
     lambda p: (any(r.get("id") == "threads-by-intent"
                   and "tapped hole with model_hole(tap=...)" in r.get("do", "")
                   and "existing cylindrical face with model_thread" in r.get("do", "")
                   for r in p.get("rules", []))
                and any(r.get("id") == "sheet-metal-by-intent"
                        and all(tool in r.get("do", "") for tool in (
                            "sheet_get", "sheet_create_flange", "sheet_convert",
                            "sheet_create_flat_pattern", "design_export"))
                        for r in p.get("rules", [])) and _kernel_rules_present(p)), None),
    ("sys_get_guidance", {"section": "assemble"},
     lambda p: ({"connected-reference-path", "exercise-the-mechanism"}
                <= {r.get("id") for r in (p.get("rules") or [])}
                and _kernel_rules_present(p)
                and len(p.get("sha256") or "") == 64
                and all(c in "0123456789abcdef" for c in p.get("sha256") or "")), None),
    ("sys_get_guidance", {"section": "kernel"},
     lambda p: (_kernel_rules_present(p, "rules") and "kernel" not in p), None),
    # the recipe read: ONE recipe whole - the ordered steps, each with what to read back, and
    # the bar. This is the id cam_get's strategies note tells a caller to ask for.
    ("sys_get_guidance", {"recipe": "manufacture-choose-a-strategy"},
     lambda p: (p["recipe"]["id"] == "manufacture-choose-a-strategy"
                and _kernel_rules_present(p)
                and len(p["recipe"]["steps"]) >= 3
                and all(s.get("tool") and s.get("read_back") for s in p["recipe"]["steps"])
                and p["recipe"]["bar"]["measure"] and p["recipe"]["bar"]["eyes"]), None),
    # each row's is_active is read off the workspace itself and a read that raises publishes null,
    # so exactly one row flagged active - and it is the one 'active_workspace' names - is the read.
    ("view_list_workspaces", {},
     lambda p: (p["workspace_count"] == len(p["workspaces"])
                and [w["name"] for w in p["workspaces"] if w["is_active"]]
                == [p["active_workspace"]]), None),
    ("view_set", {"action": "orient", "orientation": "iso-top-right"}, "ok", None),
    # camera projection: a perspective orient carries the angle through to the camera and reads it
    # back; the follow-up orient returns the projection to orthographic for the rest of the story.
    ("view_set", {"action": "orient", "orientation": "iso-top-right", "projection": "perspective",
                  "perspective_angle_deg": 45},
     lambda p: p.get("applied", {}).get("perspective_angle_deg") == 45.0, None),
    ("view_set", {"action": "orient", "orientation": "iso-top-right", "projection": "orthographic"},
     "ok", None),
    # capture options: the transparent + anti-aliased overload at an explicit size produces an image.
    ("view_screenshot", {"width": 320, "height": 240, "transparent_background": True,
                         "anti_aliased": True}, "ok", None),
    ("sys_get_selection", {}, "refused", None),   # nothing picked yet - the expected empty-selection refusal
    # PREFERENCES: read the application's own configuration, round-trip ONE invisible member, put it
    # back. The sweep leaves the application exactly as it found it, so the restore is an ASSERTION
    # (previous/now inside its own payload), not cleanup - it runs whether or not the bump asserted.
    # recoverSaveScanFrequency is the round-trip member: integer-exact, invisible to a watching
    # operator, and it perturbs no other beat's formatting.
    ("sys_get_preferences", {},
     lambda p: (p["preferences"]["display"]["generalPrecision"]["value"] is not None
                and p["preferences"]["general"]["isAutomaticVersioningEnabled"]["tier"] == "W"
                and p["preferences"]["products"]["Design"]["isFirstComponentGroundToParent"]["value"]
                is not None), None),
    # the enum FAMILY names are string literals inside the member table, so a typo degrades to a bare
    # int that no offline test can see - only a live decode of two known members catches it.
    ("sys_get_preferences", {"include": ["display", "general"]},
     lambda p: (p["preferences"]["display"]["materialDisplayUnit"].get("enum")
                == "MetricStandardDisplayUnits"
                and p["preferences"]["general"]["defaultModelingOrientation"].get("enum")
                == "ZUpModelingOrientation"), None),
    ("sys_get_preferences", {"include": ["compatibility"]},
     lambda p: p["preferences"]["compatibility"]["recoverSaveScanFrequency"]["value"] > 0,
     ("pref_scan",
      lambda p: p["preferences"]["compatibility"]["recoverSaveScanFrequency"]["value"])),
    # the members that RAISE on read are published as null + named in 'unreadable', never dropped -
    # all THREE of the raising members the [F21] census found on this build, and none of them
    # miscategorised as a member the build does not carry ('unknown_members' must be absent).
    ("sys_get_preferences", {"include": ["graphics"]},
     lambda p: ("graphicsPreset" in p["preferences"]["graphics"]
                and set(p.get("unreadable") or []) >= {"graphics.autoThrottleEffects",
                                                       "graphics.degradedSelectionDisplayStyle",
                                                       "graphics.isLimitEffectsDuringNavigation"}
                and "unknown_members" not in p), None),
    ("sys_set_preferences", lambda c: {"member": "compatibility.recoverSaveScanFrequency",
                                       "value": _ctx_get(c, "pref_scan", "the scan frequency") + 1},
     lambda p: p["now"] == p["previous"] + 1, None),
    ("sys_set_preferences", lambda c: {"member": "compatibility.recoverSaveScanFrequency",
                                       "value": _ctx_get(c, "pref_scan", "the scan frequency")},
     lambda p: p["now"] == p["previous"] - 1, None),   # RESTORED - asserted, not cleanup
    # the documented "greater than 0" bound is refused BEFORE the assignment, so nothing is written
    # and there is nothing to restore.
    ("sys_set_preferences", {"member": "compatibility.recoverSaveScanFrequency", "value": 0},
     "refused", None),
    # a tier-R member names the member and the reason, with nothing written.
    ("sys_set_preferences", {"member": "network.proxyHost", "value": "127.0.0.1"}, "refused", None),
] + _SCRATCH_DOCUMENT + _NUMERIC_REFERENCE + _BOOLEAN_FLAGS + _TARGET_CONFIRMATION + _TARGET_GROUP_TAIL + _TARGET_HIDDEN + _TARGET_SLASH + _timeline_health_rows() + _product_disclosure_rows()

# --- THE SHOWCASE: the finished fixture photographed, renamed, exported and read back -----------
# It runs BEFORE the machining acts so the sweep ends on the CAM job and its post, which is the
# deliverable. Nothing here touches the part's name or its geometry, so the CAM acts that follow
# address exactly what the modelling acts built.
_SHOWCASE = [
    ("model_extrude", {"sketch_name": "NoSuchSketch", "distance": 5}, "refused", None),   # guard probe
    ("param_set", {"name": "", "expression": "1"}, "refused", None),                      # guard probe
    # THE SCRATCH FIELD OFF THE PICTURES: every act above this one left its sketches on screen, and
    # the shots below are of the fixture. The FOLDER bulb, so no entity's own visibility is
    # disturbed; the finale puts it back after the machining acts have finished with it too.
    ("view_set", {"action": "display", "categories": ["sketches"], "visible": False},
     lambda p: p.get("visible") is False, None),
    # the machined part in its fixture - the end state of the modelling movement is the vise
    # holding the billet the bracket is cut from.
    _watch(["ViseBase:1", "STOCK:1"]),
    # the summary counts the views actually CAPTURED - one that failed to orient or capture is
    # skipped, not failed - and names the camera it could not put back after a read.
    ("view_screenshot_multi", {"views": ["iso-top-right", "front"], "width": 500, "height": 400},
     lambda p: ("Captured 2 view(s): iso-top-right, front" in str(p)
                and "could NOT be put back" not in str(p)), None),
    # THE VIEW VERBS, all on the finished fixture. ONE framed orient sets the subject; every preset
    # after it carries fit=false and no focus, so the camera ROTATES about what is already framed
    # instead of re-fitting per preset. That is the difference between a turntable and ten separate
    # zoom-outs - the vise stays the same size in the same place and only the angle changes. It also
    # keeps the tour silent: the runner shoots a frame for a camera row that names a focus, so ten
    # focused orients would write ten near-identical screenshots.
    # The tour opens with a snapshot and closes on 'restore', which is what makes it checkable -
    # camera, style and every visibility bulb come back to the state the tour started from.
    ("view_set", {"action": "snapshot"}, "ok", None),
    # Projection plus focus is checked against current geometry and retained as current-view PNGs.
    ("model_inspect", {"target": "ViseBase:1", "units": "cm"}, _world_box("ViseBase:1"),
     ("view_focus_vise_box", _recall("view_focus_vise_box", lambda p: p))),
    ("model_inspect", {"target": "STOCK:1", "units": "cm"}, _world_box("STOCK:1"),
     ("view_focus_stock_box", _recall("view_focus_stock_box", lambda p: p))),
    ("view_set", {"action": "orient", "orientation": "top",
                  "focus": ["ViseBase:1", "STOCK:1"], "projection": "orthographic"},
     "ok", None),
    ("workspace_orient", {},
     _camera_focus_read("orthographic", "view_focus_vise_box", "view_focus_stock_box"), None),
    ("view_screenshot", {"view": "current", "width": 500, "height": 400,
                         "file_path": EXPORT_DIR + "/view-focus-" + _VIEW_FOCUS_RUN + "-ortho.png"},
     _retained_png(EXPORT_DIR + "/view-focus-" + _VIEW_FOCUS_RUN + "-ortho.png"), None),
    ("view_set", {"action": "orient", "orientation": "top",
                  "focus": ["ViseBase:1", "STOCK:1"], "projection": "perspective"},
     lambda p: p.get("applied", {}).get("frame_fill") is not None, None),
    ("workspace_orient", {},
     _camera_focus_read("perspective", "view_focus_vise_box", "view_focus_stock_box"), None),
    ("view_screenshot", {"view": "current", "width": 500, "height": 400,
                         "file_path": EXPORT_DIR + "/view-focus-" + _VIEW_FOCUS_RUN + "-persp.png"},
     _retained_png(EXPORT_DIR + "/view-focus-" + _VIEW_FOCUS_RUN + "-persp.png"), None),
    ("model_inspect", {"target": "JawMoving:1", "units": "cm"}, _world_box("JawMoving:1"),
     ("view_focus_jaw_box", _recall("view_focus_jaw_box", lambda p: p))),
    ("view_set", {"action": "orient", "focus": "JawMoving:1"},
     lambda p: p.get("applied", {}).get("frame_fill") is not None, None),
    ("workspace_orient", {},
     _camera_focus_read("perspective", "view_focus_jaw_box",
                        differs_from=("view_focus_vise_box", "view_focus_stock_box")), None),
    ("view_screenshot", {"view": "current", "width": 500, "height": 400,
                         "file_path": EXPORT_DIR + "/view-focus-" + _VIEW_FOCUS_RUN + "-refocus.png"},
     _retained_png(EXPORT_DIR + "/view-focus-" + _VIEW_FOCUS_RUN + "-refocus.png"), None),
    # HandleS sits on an XZ datum 125 mm off the origin inside the
    # LeadScrew component, so its sketch-space box and its world box differ in both rotation and
    # offset. The target must land on that plane, inside the drawn lines, inside the placed part.
    ("model_inspect", {"target": "LeadScrew:1", "units": "cm"}, _world_box("LeadScrew:1"),
     ("view_focus_screw_box", _recall("view_focus_screw_box", lambda p: p))),
    ("sketch_get", {"sketch_name": "HandleS", "include_entities": True, "units": "cm"},
     _sketch_placed, ("view_focus_handle", _recall("view_focus_handle", lambda p: p))),
    ("view_set", {"action": "orient", "focus": "HandleS"},
     lambda p: (p.get("applied", {}).get("sketch_frames") or {}).get("HandleS", {}).get("space")
     == "world", None),
    ("workspace_orient", {}, _camera_on_sketch("view_focus_handle", "view_focus_screw_box"), None),
    ("view_set", {"action": "orient", "orientation": "front",
                  "focus": ["ViseBase:1", "STOCK:1"], "projection": "orthographic"},
     "ok", None),
    ("view_set", {"action": "orient", "orientation": "back", "fit": False}, "ok", None),
    ("view_set", {"action": "orient", "orientation": "left", "fit": False}, "ok", None),
    ("view_set", {"action": "orient", "orientation": "right", "fit": False}, "ok", None),
    ("view_set", {"action": "orient", "orientation": "top", "fit": False}, "ok", None),
    ("view_set", {"action": "orient", "orientation": "bottom", "fit": False}, "ok", None),
    ("view_set", {"action": "orient", "orientation": "iso-top-left", "fit": False}, "ok", None),
    ("view_set", {"action": "orient", "orientation": "iso-bottom-right", "fit": False}, "ok", None),
    ("view_set", {"action": "orient", "orientation": "iso-bottom-left", "fit": False}, "ok", None),
    ("view_set", {"action": "orient", "orientation": "iso-top-right", "fit": False}, "ok", None),
    # every visual style the tool offers, held on the one hero angle. 'current' on view_screenshot is
    # the no-move capture - the only way to shoot what the camera already frames, since a NAMED view
    # refits the whole model.
    ("view_set", {"action": "style", "style": "wireframe"}, "ok", None),
    ("view_set", {"action": "style", "style": "wireframe-edges"}, "ok", None),
    ("view_set", {"action": "style", "style": "wireframe-hidden-edges"}, "ok", None),
    ("view_set", {"action": "style", "style": "shaded-hidden-edges"}, "ok", None),
    ("view_set", {"action": "style", "style": "shaded"}, "ok", None),
    ("view_screenshot", {"view": "current", "width": 500, "height": 400}, "ok", None),
    ("view_set", {"action": "style", "style": "shaded-edges"}, "ok", None),
    # visibility, in the order that leaves nothing hidden behind: isolate the stock, hide one jaw,
    # show it again, then drop the isolation. Each verb reports what it reached. The story document
    # already reads modified, so the isolate claims no flip of its own.
    ("view_set", {"action": "isolate", "target": "STOCK:1"},
     lambda p: _measured("the already-modified document is not claimed by the isolate",
                         {k: p.get(k) for k in ("document_modified", "modified_by_this_call")},
                         p.get("document_modified") is True
                         and "modified_by_this_call" not in p), None),
    ("view_set", {"action": "clear_isolation"}, "ok", None),
    ("view_set", {"action": "hide", "target": "JawMoving:1"}, "ok", None),
    ("view_set", {"action": "show", "target": "JawMoving:1"}, "ok", None),
    # a persistent Named View: parked, listed among the document's own, and re-applied.
    ("view_set", {"action": "save_view", "view_name": "SweepHero"}, "ok", None),
    # the camera has to LEAVE the saved view for re-applying it to prove anything - in place, so the
    # proof does not cost a fit-to-whole-model on the way out and another on the way back.
    ("view_set", {"action": "orient", "orientation": "bottom", "fit": False}, "ok", None),
    ("view_set", {"action": "apply_view", "view_name": "SweepHero"}, "ok", None),
    ("view_set", {"action": "list_views"},
     lambda p: "SweepHero" in [v.get("name") for v in (p.get("named_views") or [])], None),
    # FSAE-0922-LIST-VIEWS-CAMERA-1: a second saved view at a different orientation, and list_views'
    # two rows read back distinct cameras - the executor can now tell one saved view from another
    # without re-applying each one just to see where it points.
    ("view_set", {"action": "orient", "orientation": "top", "fit": False}, "ok", None),
    ("view_set", {"action": "save_view", "view_name": "CamRowTop"}, "ok", None),
    ("view_set", {"action": "list_views"},
     _distinct_saved_cameras(["SweepHero", "CamRowTop"]), None),
    # A NAMED shot frames the visible geometry whatever the camera was framing (here the moving
    # jaw alone), and fit_to isolates its subject in ONE write and clears it again - so the
    # clear_isolation that follows finds nothing to clear. Both shots are retained.
    ("view_set", {"action": "orient", "focus": "JawMoving:1"}, "ok", None),
    ("view_screenshot", {"view": "front", "width": 500, "height": 400,
                         "file_path": EXPORT_DIR + "/view-frame-" + _VIEW_FOCUS_RUN + "-front.png"},
     _retained_png(EXPORT_DIR + "/view-frame-" + _VIEW_FOCUS_RUN + "-front.png", 1000), None),
    ("view_screenshot", {"view": "iso-top-right", "fit_to": "JawMoving:1", "width": 500,
                         "height": 400,
                         "file_path": EXPORT_DIR + "/view-frame-" + _VIEW_FOCUS_RUN + "-fit-to.png"},
     _retained_png(EXPORT_DIR + "/view-frame-" + _VIEW_FOCUS_RUN + "-fit-to.png", 1000), None),
    ("view_set", {"action": "clear_isolation"},
     lambda p: _measured("fit_to left no isolation behind", {"cleared_count": p.get("cleared_count")},
                         p.get("cleared_count") == 0), None),
    # With the jaw isolated and the camera parked on MateArm, two metres off,
    # 'current' shoots backdrop; a plain view='front' (no fit asked) has to frame the jaw anyway.
    ("view_set", {"action": "isolate", "target": "JawMoving:1"}, "ok", None),
    ("view_set", {"action": "orient", "focus": "MateArm:1"}, "ok", None),
    ("view_screenshot", {"view": "current", "width": 500, "height": 400,
                         "file_path": EXPORT_DIR + "/view-frame-" + _VIEW_FOCUS_RUN + "-parked.png"},
     _retained_png(EXPORT_DIR + "/view-frame-" + _VIEW_FOCUS_RUN + "-parked.png"), None),
    ("view_screenshot", {"view": "front", "width": 500, "height": 400,
                         "file_path": EXPORT_DIR + "/view-frame-" + _VIEW_FOCUS_RUN + "-unparked.png"},
     _outframes(EXPORT_DIR + "/view-frame-" + _VIEW_FOCUS_RUN + "-parked.png",
                EXPORT_DIR + "/view-frame-" + _VIEW_FOCUS_RUN + "-unparked.png"), None),
    ("view_set", {"action": "clear_isolation"},
     lambda p: _measured("the parked-shot isolation cleared",
                         {"cleared_count": p.get("cleared_count")}, p.get("cleared_count") == 1), None),
    ("view_set", {"action": "isolate", "target": "JawMoving:1"}, "ok", None),
    ("view_screenshot", {"fit_to": "JawMoving:1", "width": 300, "height": 240}, "ok", None),
    ("design_get", {"include": ["tree"], "component": "JawMoving:1", "tree_bodies": True},
     _subject_visible("JawMoving:1", True), None),
    ("design_get", {"include": ["tree"], "component": "STOCK:1", "tree_bodies": True},
     _subject_visible("STOCK:1", False), None),
    ("view_set", {"action": "clear_isolation"},
     lambda p: _measured("one prior isolation survived capture",
                         {"cleared_count": p.get("cleared_count")}, p.get("cleared_count") == 1), None),
    ("view_set", {"action": "isolate", "target": "STOCK:1"}, "ok", None),
    ("view_screenshot", {"fit_to": "JawMoving:1", "width": 300, "height": 240}, "ok", None),
    ("design_get", {"include": ["tree"], "component": "JawMoving:1", "tree_bodies": True},
     _subject_visible("JawMoving:1", False), None),
    ("design_get", {"include": ["tree"], "component": "STOCK:1", "tree_bodies": True},
     _subject_visible("STOCK:1", True), None),
    ("view_set", {"action": "clear_isolation"},
     lambda p: _measured("one prior isolation survived capture",
                         {"cleared_count": p.get("cleared_count")}, p.get("cleared_count") == 1), None),
    ("view_set", {"action": "restore"}, "ok", None),
    # one contact sheet, four presets. This tool walks the camera per view and fits each one, so its
    # cost on screen is one zoom-out per view in the list - a seven-view sheet and an 'all' sheet
    # behind it read as the camera coming loose right at the end of the run. Four is enough to show
    # the sheet is a sheet; the orientation vocabulary is already covered by the turntable above,
    # which pays nothing to do it.
    ("view_screenshot_multi", {"views": ["back", "bottom", "left", "iso-bottom-left"],
                               "width": 300, "height": 240}, "ok", None),
    # THE RENAMES, last: a rename invalidates every row that names its target, so they run once the
    # build is done. A two-body cameo carries the dedupe beat - it needs a SIBLING pair, and the
    # machined part is a component of one body.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "TwinCameo", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "TwinA"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 1400, "y1": 200,
                                           "x2": 1430, "y2": 230}],
                             "sketch_name": "TwinA"}, "ok", None),
    ("model_extrude", {"sketch_name": "TwinA", "profile_index": 0, "distance": 10}, _extruded, None),
    ("sketch_create", {"plane": "xy", "name": "TwinB"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 1450, "y1": 200,
                                           "x2": 1480, "y2": 230}],
                             "sketch_name": "TwinB"}, "ok", None),
    ("model_extrude", {"sketch_name": "TwinB", "profile_index": 0, "distance": 10}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("find_geometry", {"target": "TwinCameo", "kind": "planar_face", "nearest_to": [1415, 215, 10],
                       "max_results": 1}, "ok", _fg("twin_a")),
    ("find_geometry", {"target": "TwinCameo", "kind": "planar_face", "nearest_to": [1465, 215, 10],
                       "max_results": 1}, "ok", _fg("twin_b")),
    ("design_set_name", lambda c: {"target": _ctx_get(c, "twin_a", "the first twin body"),
                                   "new_name": "TwinPlate"},
     lambda p: p.get("name") == "TwinPlate" and p.get("kind") == "body"
     and p.get("deduped") is False, None),
    # the name its sibling already holds: Fusion dedupes it to 'TwinPlate (1)' and THAT is the name
    # the payload has to publish - a payload echoing the request would read 'TwinPlate' here.
    ("design_set_name", lambda c: {"target": _ctx_get(c, "twin_b", "the second twin body"),
                                   "new_name": "TwinPlate"},
     lambda p: p.get("deduped") is True and p.get("name") == "TwinPlate (1)", None),
    # an OCCURRENCE target renames the COMPONENT behind it, and the instance name follows.
    ("design_set_name", {"target": "TwinCameo:1", "new_name": "TwinAssy"},
     lambda p: p.get("kind") == "component" and p.get("occurrence_name") == "TwinAssy:1", None),
    # THE OCCURRENCE FAN-OUT, in the two-step shape that discriminates ([F64]): colour ONE body
    # directly (colour A), then write the OCCURRENCE in a different colour (colour B). The
    # occurrence's own read-back agrees with the write whether or not a body took it, so the bodies
    # are re-read: the body holding its own override kept colour A and must come back under
    # 'bodies_not_reached' - NOT under applied_to. Both colours are minted from one base asset, so
    # they share an Appearance.id and differ only by NAME - an id-only comparison lists the
    # overridden body as reached, which is exactly the defect this beat stands on.
    ("appearance_set", {"target": "TwinPlate", "color": "#C2185B"},
     lambda p: p.get("kind") == "body" and p.get("applied_to") == ["TwinPlate"], None),
    ("appearance_set", {"target": "TwinAssy:1", "color": "#00897B"},
     lambda p: any(o.get("body") == "TwinPlate" for o in (p.get("bodies_not_reached") or []))
     and "TwinPlate" not in (p.get("applied_to") or [])
     and "TwinPlate (1)" in (p.get("applied_to") or []), None),
    # the same shape where the overridden body is the occurrence's ONLY one: nothing was reached, so
    # the call is a refusal naming the body to colour directly - never an ok on the occurrence's own
    # agreeable read-back.
    ("model_create_component", {"name": "SoloColor", "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": "SoloS"}, "ok", None),
    ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 1500, "y1": 200,
                                           "x2": 1530, "y2": 230}],
                             "sketch_name": "SoloS"}, "ok", None),
    ("model_extrude", {"sketch_name": "SoloS", "profile_index": 0, "distance": 10}, _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("find_geometry", {"target": "SoloColor", "kind": "planar_face", "nearest_to": [1515, 215, 10],
                       "max_results": 1}, "ok", _fg("solo_face")),
    ("design_set_name", lambda c: {"target": _ctx_get(c, "solo_face", "the solo body"),
                                   "new_name": "SoloBody"},
     lambda p: p.get("kind") == "body" and p.get("name") == "SoloBody", None),
    ("appearance_set", {"target": "SoloBody", "color": "#C2185B"},
     lambda p: p.get("kind") == "body", None),
    ("appearance_set", {"target": "SoloColor:1", "color": "#00897B"},
     _refused("reached NONE", "SoloBody"), None),
    # A COMPONENT rename, then the component re-found through the name that landed - the rename
    # reaches the browser name every other tool addresses it by. It is taken on a cameo rather than
    # on the machined part, because the CAM acts after this one address the part by the name the
    # modelling acts gave it.
    ("design_set_name", {"target": "SoloColor:1", "new_name": "SoloRenamed"},
     lambda p: p.get("name") == "SoloRenamed" and p.get("previous_name") == "SoloColor"
     and p.get("kind") == "component", None),
    ("find_geometry", {"target": "SoloRenamed", "kind": "planar_face", "max_results": 1}, "ok", None),
    # re-asking for the name it already holds mutates nothing and says so.
    ("design_set_name", {"target": "SoloRenamed", "new_name": "SoloRenamed"},
     lambda p: p.get("changed") is False, None),
    ("design_set_name", {"target": "", "new_name": "X"}, "refused", None),
    # the ROOT component is refused UP FRONT: its name is the document's, and the platform's own
    # raise would abort the transaction around it. The root name is read off the tree, never guessed.
    ("design_get", {"include": ["tree"]}, "ok", ("root_name", lambda p: p["tree"]["root"])),
    ("design_set_name", lambda c: {"target": _ctx_get(c, "root_name", "the root component name"),
                                   "new_name": "RootRename"}, "refused", None),
    # every DOCUMENT read is stamped with the document it read from, so two tallies taken in two
    # documents are distinguishable. (sys_find_tool, the registry read in the overture, carries no
    # such key - it never touched the design.)
    ("design_get", {},
     lambda p: bool((p.get("active_document") or {}).get("name")), None),
    # The default read's joint count is the design-wide walk
    # assembly_get counts, whichever component is active.
    ("assembly_get", {}, lambda p: _num(p.get("joint_count")) and p["joint_count"] > 0,
     ("joint_total", _recall("joint_total", lambda p: p["joint_count"]))),
    ("design_activate_component", {"occurrence": "LeadScrew:1"}, "ok", None),
    ("design_get", {},
     lambda p: _measured("design_get joints equal assembly_get joint_count, a child active",
                         {"joints": (p.get("contents") or {}).get("joints"),
                          "joint_count": _RECALL.get("joint_total")},
                         (p.get("contents") or {}).get("joints") == _RECALL.get("joint_total")),
     None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    # the assignable catalog, at both zoom levels: the document's own entries plus a count-only
    # census of every loaded library, then ONE library paged by name_filter/max_results. A library
    # name that is not loaded is refused with the loaded names listed.
    ("design_get", {"include": ["materials"]}, "ok", None),
    ("design_get", {"include": ["appearances"], "library": "Fusion Appearance Library",
                    "name_filter": "paint", "max_results": 5}, "ok", None),
    ("design_get", {"include": ["appearances"], "library": "NoSuchLibrary"}, "refused", None),
    # EVERY neutral-CAD format the exporter declares, one file per factory, each measured ON DISK -
    # a build missing a factory, or one that reports success and writes nothing, fails here rather
    # than at whoever opens the file. The formats ImportManager can read then come straight back in
    # with the format named EXPLICITLY: doc_insert_import refuses a format that contradicts the
    # file's extension, so naming it checks that the extension the exporter chose is the one the
    # importer expects.
    ("design_export", {"format": "iges", "file_path": EXPORT_DIR + "/fmt_bracket",
                       "target": "Bracket"}, _exported_bytes, None),
    # SAT is deliberately NOT here. Measured on this build: the FIRST createSATExportOptions export
    # in a Fusion session writes its file, and every one after it returns false having written
    # nothing - on any target, in a fresh document holding one box, and into a directory no .sat has
    # ever been written to, while IGES and SMT through the same call shape keep working in that same
    # session. The tool reports the failure honestly, which is the behaviour that matters; what the
    # sweep cannot do is assert an outcome that depends on whether anything exported SAT earlier.
    ("design_export", {"format": "smt", "file_path": EXPORT_DIR + "/fmt_bracket",
                       "target": "Bracket"}, _exported_bytes, None),
    # F3D of a COMPONENT is the row where execute()'s bool and the disk disagree: the archive lands
    # while execute() answers false, so the tool verifies the file and discloses the bool under
    # 'execute_returned_false' - and this row stands on the size on disk, as its siblings do.
    ("design_export", {"format": "f3d", "file_path": EXPORT_DIR + "/fmt_bracket",
                       "target": "Bracket"}, _exported_bytes, None),
    ("design_export", {"format": "obj", "file_path": EXPORT_DIR + "/fmt_bracket",
                       "target": "Bracket"}, _exported_bytes, None),
    ("design_export", {"format": "3mf", "file_path": EXPORT_DIR + "/fmt_bracket",
                       "target": "Bracket"}, _exported_bytes, None),
    # USD lands as .usdz whatever extension the path carries - Fusion appends its own - so the tool
    # publishes the path it actually wrote.
    ("design_export", {"format": "usd", "file_path": EXPORT_DIR + "/fmt_bracket",
                       "target": "Bracket"},
     lambda p: _exported_bytes(p) is True and str(p.get("file_path", "")).endswith(".usdz"), None),
    # STL with the units baked in: the one format carrying its own unit, so the knob is set and read
    # back off the options object that LANDED. The single-file path publishes 'options_applied' and
    # 'options_requested'; this predicate reads only the applied value - what the options object
    # that wrote THIS file read back. Reading 'options_requested' here would only echo this step's
    # own two arguments back at it.
    ("design_export", {"format": "stl", "file_path": EXPORT_DIR + "/fmt_bracket_in",
                       "target": "Bracket", "stl_units": "in", "stl_binary": False},
     lambda p: _exported_bytes(p) is True
     and (p.get("options_applied") or {}).get("stl_units") == "in"
     and (p.get("options_applied") or {}).get("stl_binary") is False, None),
    # the 2D branch: a sketch written as DXF, then read back onto a named plane as sketches.
    ("design_export", {"format": "dxf", "file_path": EXPORT_DIR + "/fmt_twin",
                       "dxf_sketch": "TwinA"}, _exported_bytes, None),
    ("doc_insert_import", {"file_path": EXPORT_DIR + "/fmt_twin.dxf", "format": "dxf",
                           "plane": "xy"}, _imported_sketches, None),
    # SVG lands in an EXISTING sketch (there is no component-level SVG import), so one is made for it.
    ("sketch_create", {"plane": "xy", "name": "SvgImport"}, "ok", None),
    ("doc_insert_import", {"file_path": SVG_PATH, "format": "svg", "sketch": "SvgImport"},
     _imported_curves, None),
    # NO further solid re-imports. An import lands its geometry at the coordinates the FILE carries,
    # so re-importing a part into the design it came from drops a second copy exactly on top of the
    # original - measured: one per format left FIVE coincident copies on the machined part, which is
    # the one thing the CAM shot is of. Every format is proven by its own measured bytes on disk,
    # which costs the scene nothing; the STEP round trip the deliverables act runs is the visible
    # proof that a written file reads back.
    # the contradiction the explicit format exists to catch, on a file that is certainly there.
    ("doc_insert_import", {"file_path": EXPORT_DIR + "/fmt_bracket.smt", "format": "step"},
     "refused", None),
    # DRAWING GUARDS: every one of these is settled before the tool looks for a cloud source, so
    # they run on the story document exactly as they would on a saved one, and each refuses for the
    # reason it names with no drawing created. The creation path itself is cloud-tier (it needs a
    # saved source design) and stays out of the default sweep.
    # adsk.drawing carries no plain shaded member - shading pairs with hidden or with visible edges.
    ("drawing_create", {"view_style": "shaded"}, "refused", None),
    ("drawing_create", {"tangent_edges": "partial"}, "refused", None),
    # Fusion gates manual creation on a template carrying view-placeholder information, and the
    # failure escapes an enclosing try/except - so the mode is refused up front instead of called
    # into, and the session is still healthy afterwards.
    ("drawing_create", {"creation_mode": "manual"}, "refused", None),
    ("workspace_orient", {}, "ok", None),
    # the API silently IGNORES a sheet size from the other standard, so the pairing is guarded here.
    ("drawing_create", {"standard": "asme", "sheet_size": "a2"}, "refused", None),
    # FSAE-0922-JOINT-ORIGIN-FOLDER-1: a joint origin NO joint consumes - the repro needs a free
    # one, since a consumed one's triad clears through a different mechanism.
    ("joint_create_origin", {"anchor": "coordinates", "target": "origin", "name": "FreeOrigin"},
     "ok", None),
    ("view_set", {"action": "display", "categories": ["joint_origins"], "visible": False},
     lambda p: p.get("folders_set", {}).get("joint_origins", 0) >= 1
     and not any(s.get("category") == "joint_origins" for s in (p.get("stuck") or [])), None),
    # a SECOND, separately-issued call finds the bulb already false - a fresh read, not the first
    # call's own report, is what proves the fold landed and held.
    ("view_set", {"action": "display", "categories": ["joint_origins"], "visible": False},
     lambda p: p.get("folders_set") == {"joint_origins": 0}, None),
    ("view_set", {"action": "display", "categories": ["joint_origins"], "visible": True},
     lambda p: p.get("visible") is True, None),
]

# THE LAYOUT DRIFT GATE, on the field ACT 9 has finished dressing. verify_layout._MEASURED_BOX
# records where the chunks really are and the framing pass widens every frame from it, so a layout
# move that outdates the table fails HERE rather than ageing it silently.
_SHOWCASE += [drift_row(chunk) for chunk in _DRIFT_CHUNKS]


# --- FINALE: put the workspace and the browser back, then DISCARD the document on camera --------
# Everything that must run LAST and nothing else. The machining acts leave Manufacture active and
# the sketch folders hidden, so the two restores are the sweep leaving the application as it found
# it; the document identity is read while it still answers, and then it goes.
_FINALE = [
    # the CAM acts left Manufacture active, so this is a real switch: 'activation_verified' is true
    # only where isActive or the UI's own active workspace read the change back.
    ("view_switch_workspace", {"workspace": "design"},
     lambda p: p.get("switched") is True and p.get("activation_verified") is True, None),
    # CAM hid the sketch folders for the machining movement; this is where they come back.
    ("view_set", {"action": "display", "categories": ["sketches"], "visible": True},
     lambda p: p.get("visible") is True, None),
    ("doc_get", {}, _document_read, None),
    ("doc_close", {"save_changes": False}, _document_closed, None),
]


# --- the reload beat: the one tool no act can hold, driven after every act has run ---------------
# sys_reload_addin restarts the server the sweep is talking to, so it can be no step: the call
# after it would reach a socket that is coming down. It is a post-run beat instead, and what it
# has to establish is that the restart HAPPENED. The reload is DEFERRED - the handler starts a
# timer and returns while the server is still answering - so a /health read taken when the call
# comes back describes the pre-teardown state. Attested calls require fresh load/session identities;
# legacy calls observe /health going down and answering again.
_RELOAD_PROBE_GAP_S = 0.25
_RELOAD_PROBE_TIMEOUT_S = 5.0
# Attempt budgets, not deadlines, so the beat's cost is bounded the way poll_generation's is: 40
# probes to catch the teardown and 60 to see the re-import answer, a quarter-second apart, each
# probe itself capped by the timeout above. A budget that runs out ends the beat, never the wait.
_RELOAD_DOWN_POLLS = 40
_RELOAD_UP_POLLS = 60
# The smoke read: a registry search. sys_find_tool is registered run_on_main_thread=False, so it
# answers off the registry rather than queuing behind Fusion's main thread, and entry.start()
# collects and registers every tool BEFORE it starts the HTTP server - so a /health that answers
# is a registry already populated, and this read is of the restarted add-in, not a race with it.
_RELOAD_SMOKE_QUERY = "reload addin"


def _server_answers(timeout=_RELOAD_PROBE_TIMEOUT_S):
    """True when GET /health answers right now AS THIS SERVER. Every other outcome is False -
    refused, reset, timed out, or a different server holding the port - because none of them is
    this add-in answering, and the caller reads the two states apart, never the reason."""
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    return data.get("server") == SERVER_NAME


def _health_bound(timeout=20):
    """The 'bound' row GET /health publishes right now; a read that fails raises."""
    with urllib.request.urlopen(BASE + "/health", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8")).get("bound")


def _poll_health(up, polls):
    """Poll /health until it reads `up` (True = answering as this server, False = not), bounded by
    `polls` attempts. True when that state was OBSERVED, False when the budget ran out - a budget
    that runs out is never read as the state it was waiting for."""
    answers = facade("_server_answers")
    for i in range(polls):
        if i:
            time.sleep(_RELOAD_PROBE_GAP_S)
        if bool(answers()) is up:
            return True
    return False


def _reload_handle(value):
    return (isinstance(value, str) and value.startswith("session:")
            and len(value) > len("session:") and not any(c.isspace() for c in value))


def _reload_census(call, phase="census"):
    try:
        is_error, payload = call("doc_get", {"max_results": 1000})
    except Exception as e:
        return None, f"{phase} doc_get did not answer: {e}"
    if is_error or not isinstance(payload, dict) or payload.get("truncated") is not False:
        return None, f"{phase} census was unreadable or truncated"
    rows = payload.get("open_documents")
    count = payload.get("open_count")
    if not isinstance(rows, list) or type(count) is not int or count != len(rows):
        return None, f"{phase} census was incomplete"
    handles = []
    for row in rows:
        if not isinstance(row, dict) or not _reload_handle(row.get("document_handle")):
            return None, f"{phase} census had an invalid document handle"
        if row.get("document_handle") in handles:
            return None, f"{phase} census had duplicate document handles"
        handles.append(row["document_handle"])
    active = payload.get("active")
    if not isinstance(active, dict):
        return None, f"{phase} active document was unreadable"
    active_handle = active.get("document_handle")
    active_rows = [r for r in rows if r.get("is_active") is True]
    if not _reload_handle(active_handle) or len(active_rows) != 1:
        return None, f"{phase} active document was not uniquely readable"
    if active_rows[0].get("document_handle") != active_handle:
        return None, f"{phase} active document did not match its census row"
    return {"handle": active_handle, "document_id": active.get("document_id"),
            "name": active.get("name"), "rows": rows}, None


def _reload_cleanup(call, scratch, home):
    """Close only the proven scratch and independently restore the original home."""
    problems = []
    state, problem = _reload_census(call, "cleanup")
    if problem:
        return False, problem
    if not _reload_handle(scratch):
        problems.append("scratch ownership unresolved")
    elif scratch in {row["document_handle"] for row in state["rows"]}:
        try:
            is_error, closed = call("doc_close", {
                "name": scratch, "save_changes": False, "expect_document": state["handle"]})
            if (is_error or not isinstance(closed, dict)
                    or not isinstance(closed.get("closed"), list)
                    or len(closed["closed"]) != 1 or closed.get("closed_count") != 1):
                problems.append("scratch close was not confirmed")
        except Exception as e:
            problems.append(f"scratch close raised: {e}")
        state, problem = _reload_census(call, "scratch cleanup")
        if problem:
            return False, "; ".join(problems + [problem])
        if scratch in {row["document_handle"] for row in state["rows"]}:
            problems.append("owned scratch remains open")
    handles = {row["document_handle"] for row in state["rows"]}
    target = home["handle"] if home["handle"] in handles else home["document_id"]
    if not target:
        matches = [row for row in state["rows"] if row.get("name") == home["name"]]
        if len(matches) != 1:
            return False, "; ".join(problems + ["unsaved home is not uniquely identifiable"])
        target = matches[0]["document_handle"]
    try:
        is_error, activated = call("doc_activate", {
            "name": target, "expect_document": state["handle"]})
        if is_error:
            problems.append("original home activation refused: " + str(activated)[:NOTE_MAX])
    except Exception as e:
        problems.append(f"original home activation raised: {e}")
    restored, problem = _reload_census(call, "home restoration")
    if problem:
        problems.append(problem)
    elif (_reload_handle(target) and restored["handle"] != target) or (
            not _reload_handle(target) and restored["document_id"] != target):
        problems.append("original home identity did not read back")
    if problems:
        return False, "; ".join(problems)
    return True, "scratch cleanup and home restoration verified"


def _reload_owned_handle(call, old_handle, nonce_name):
    """Recover scratch ownership from its surviving handle or active nonce."""
    state, problem = _reload_census(call, "scratch ownership")
    if problem:
        return None
    if old_handle in {row["document_handle"] for row in state["rows"]}:
        return old_handle
    try:
        is_error, payload = call("param_get", {"name": nonce_name})
    except Exception:
        return None
    par = payload.get("parameter") if isinstance(payload, dict) else None
    if (not is_error and isinstance(par, dict) and par.get("name") == nonce_name
            and par.get("value") == 17):
        return state["handle"]
    return None


def _reload_document_probe(call, old_handle, home, nonce_name):
    def ask(tool, args):
        try:
            is_error, payload = call(tool, args)
        except Exception as e:
            return True, str(e)
        return is_error, payload

    payload, problem = _reload_census(call, "post-reload")
    if problem:
        return False, problem, None
    fresh = payload["handle"]
    if fresh == old_handle:
        return False, "post-reload scratch handle was not fresh", None
    is_error, nonce = ask("param_get", {"name": nonce_name})
    par = (nonce or {}).get("parameter") if isinstance(nonce, dict) else None
    if (is_error or not isinstance(par, dict) or par.get("name") != nonce_name
            or par.get("value") != 17):
        return False, "post-reload nonce did not identify the owned scratch", None
    is_error, stale = ask("param_add", {"name": "ReloadStale", "expression": "1 mm",
                                        "expect_document": old_handle})
    if not is_error or "unknown_document_handle" not in str(stale):
        return False, "the expired scratch handle did not refuse before writing", fresh
    is_error, absent = ask("param_get", {"name": "ReloadStale"})
    if not is_error or "Parameter not found" not in str(absent):
        return False, "the stale-handle parameter was not absent", fresh
    is_error, added = ask("param_add", {"name": "ReloadRecovered", "expression": "2 mm",
                                        "expect_document": fresh})
    par = (added or {}).get("parameter") if isinstance(added, dict) else None
    if (is_error or not isinstance(par, dict) or added.get("added") is not True
            or par.get("name") != "ReloadRecovered" or par.get("value") != 2):
        return False, "fresh scratch handle did not write and read back", fresh
    is_error, read_back = ask("param_get", {"name": "ReloadRecovered"})
    par = (read_back or {}).get("parameter") if isinstance(read_back, dict) else None
    if is_error or not isinstance(par, dict) or par.get("value") != 2:
        return False, "fresh scratch parameter did not read back", fresh
    is_error, deleted = ask("param_delete", {"name": "ReloadRecovered",
                                              "expect_document": fresh})
    if is_error or not isinstance(deleted, dict) or deleted.get("deleted") is not True:
        return False, "fresh scratch cleanup did not delete the recovery parameter", fresh
    is_error, absent = ask("param_get", {"name": "ReloadRecovered"})
    if not is_error or "Parameter not found" not in str(absent):
        return False, "fresh scratch cleanup was not read back", fresh
    return True, "fresh scratch handle recovered and stale handle refused", fresh

def reload_smoke(rows, notes, valued=None, down_polls=_RELOAD_DOWN_POLLS,
                 up_polls=_RELOAD_UP_POLLS, expected_attestation=None):
    """Reload the add-in and verify a run-owned document survives with fresh identity."""
    call, STORY = facade("call"), facade("STORY")
    home, problem = _reload_census(call, "pre-reload")
    if problem:
        print("  reload beat: " + problem)
        return
    if home["document_id"] is not None and (
            not isinstance(home["document_id"], str) or not home["document_id"].startswith("urn:")):
        print("  reload beat: original home lineage is invalid")
        return
    if not home["document_id"]:
        matches = [row for row in home["rows"] if row.get("name") == home["name"]]
        if not home["name"] or len(matches) != 1:
            print("  reload beat: unsaved home name is not unique")
            return
    try:
        is_error, created = call("doc_new", {"expect_document": home["handle"]})
    except Exception as e:
        print("  reload beat: could not create owned scratch: " + str(e)[:NOTE_MAX])
        return
    canary = (created or {}).get("document_handle") if isinstance(created, dict) else None
    if (is_error or not isinstance(created, dict) or created.get("created") is not True
            or not _reload_handle(canary)
            or canary in {row["document_handle"] for row in home["rows"]}):
        print("  reload beat: owned scratch creation was not verified")
        return
    nonce_name = "ReloadNonce" + canary.split(":")[-1][:8]
    fresh = None
    cleanup_note = None
    try:
        is_error, added = call("param_add", {
            "name": nonce_name, "expression": "17 mm", "expect_document": canary})
        par = (added or {}).get("parameter") if isinstance(added, dict) else None
        if (is_error or not isinstance(par, dict) or added.get("added") is not True
                or par.get("name") != nonce_name or par.get("value") != 17):
            raise RuntimeError("owned scratch nonce was not verified")
        is_error, before_nonce = call("param_get", {"name": nonce_name})
        par = (before_nonce or {}).get("parameter") if isinstance(before_nonce, dict) else None
        if (is_error or not isinstance(par, dict) or par.get("name") != nonce_name
                or par.get("value") != 17):
            raise RuntimeError("owned scratch nonce did not read back before reload")
        is_error, payload = call("sys_reload_addin", {})
        if is_error or "Reload scheduled" not in str(payload):
            raise RuntimeError(f"no reload was scheduled - {str(payload)[:NOTE_MAX]}")
        current_attestation = None
        if expected_attestation is not None:
            for attempt in range(up_polls):
                if attempt:
                    time.sleep(_RELOAD_PROBE_GAP_S)
                try:
                    current_health = facade("health_gate")()
                    current_attestation = facade("attestation_identity")(current_health)
                except (OSError, ValueError, SystemExit):
                    continue
                if current_attestation and all(
                        current_attestation.get(field) != expected_attestation.get(field)
                        for field in ("load_id", "session_id")):
                    break
            else:
                raise RuntimeError("reload did not establish a new load and session identity")
            if not all(current_attestation.get(field) == expected_attestation.get(field)
                       for field in ("implementation_fingerprint", "schema_fingerprint")):
                raise RuntimeError("new server did not prove the expected build")
            if "sys_reload_addin" not in facade("registered_tools")(current_health):
                raise RuntimeError("restarted tools/list did not return sys_reload_addin")
            restart_note = "new load and session identities proved the expected build"
        else:
            if not _poll_health(False, down_polls):
                raise RuntimeError(f"/health kept answering across {down_polls} probes")
            if not _poll_health(True, up_polls):
                raise RuntimeError(f"/health did not answer again within {up_polls} probes")
            restart_note = f"/health stopped answering and answered again as {SERVER_NAME}"
        try:
            found = call("sys_find_tool", {"query": _RELOAD_SMOKE_QUERY})[1]
        except Exception as e:
            raise RuntimeError(f"registry read did not come back: {e}")
        matches = found.get("tools") or [] if isinstance(found, dict) else []
        names = [m.get("tool") for m in matches if isinstance(m, dict)]
        if "sys_reload_addin" not in names:
            raise RuntimeError("restarted registry did not return sys_reload_addin")
        # Two reads of the restarted server, each compared with the URL this run connected on.
        _bound_on_harness("/health", facade("_health_bound")())
        mapped = call("sys_capability_map", {})[1]
        _bound_on_harness("sys_capability_map",
                          mapped.get("bound") if isinstance(mapped, dict) else None)
        ok, note, fresh = _reload_document_probe(call, canary, home, nonce_name)
        if not ok:
            raise RuntimeError(note)
        cleanup_ok, cleanup_note = _reload_cleanup(call, fresh, home)
        if not cleanup_ok:
            raise RuntimeError(cleanup_note)
        rows.append(("sys_reload_addin", "pass",
                     f"{restart_note}; the restarted "
                     f"registry returned {len(names)} match(es) for '{_RELOAD_SMOKE_QUERY}', "
                     f"sys_reload_addin among them; /health and sys_capability_map both publish "
                     f"{MCP} as bound"))
        notes["sys_reload_addin"] = STORY.get("sys_reload_addin", "")
        if valued is not None:
            valued.add("sys_reload_addin")
        return current_attestation
    except Exception as e:
        print("  reload beat: " + str(e)[:NOTE_MAX])
    finally:
        if cleanup_note is None:
            owned = fresh or _reload_owned_handle(call, canary, nonce_name)
            cleanup_ok, cleanup_note = _reload_cleanup(call, owned, home)
        if cleanup_note and not cleanup_note.startswith("scratch cleanup and home restoration"):
            print("  reload beat: cleanup unresolved for " + canary
                  + ": " + cleanup_note[:NOTE_MAX])
