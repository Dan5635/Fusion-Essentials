# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The parametric resize act and model fallbacks."""


from verify_core import (
    _RECALL, _box, _chamfered, _ctx_get, _datum_plane, _document_closed, _drafted, _drilled, _extent_measured, _extruded, _fg, _filleted, _gap_measured, _home_address, _home_document, _interference_measured, _joined, _joint_origin_at, _joint_origins_listed, _lofted, _made_component, _made_component_inactive, _material_assigned, _measured, _mirrored, _near, _new_document, _param_added, _param_deleted, _param_set_to, _patterned, _prof, _recall, _refused, _relation_passes, _revolved, _shelled, _swept, _watch)





from verify_acts_model_precision import (
    _addr_planes_own_their_params, _section_census, _section_created, _section_named_clear)
from verify_acts_model_combine_revolve import (
    _contact_overlap, _contact_part_poses, _fractional_helix_cap, _interference_budget, _interference_pair_named, _interference_pin, _peg_faces_per_instance, _separated_block_poses, _separated_interference, _shared_cube_overlap, _shared_cube_poses)

def _fillet_expression_followed(expression, mm):
    """design_get(include=['timeline'], timeline_params=True): the row whose Radius parameter is
    the EXPRESSION the fillet was built with, and the value that expression now evaluates to.

    A radius passed as a parameter name is stored as that name, so the recompute re-evaluates it -
    a radius baked to a number would read back as the number it was built at. Rows carry their
    value in internal cm, and the feature is found by its own expression rather than by a
    'Fillet<n>' name the platform picks."""
    def check(p):
        rows = (p.get("timeline") or {}).get("timeline") or []
        hit = next(((r, q) for r in rows for q in (r.get("params") or [])
                    if q.get("expression") == expression), (None, None))
        row, param = hit
        return _measured(f"the fillet built at '{expression}' now measures {mm} mm",
                         {"feature": row and row.get("name"), "param": param},
                         param is not None and _near(param.get("value"), mm / 10.0, 1e-3))
    return check


def _interference_body_handle(p):
    """Return BlockA's sole body handle from the complete occurrence tree."""
    tree = p.get("tree") or {}
    hits = [node for node in (tree.get("children") or []) if node.get("name") == "BlockA:1"]
    if (len(hits) != 1 or hits[0].get("body_count") != 1
            or hits[0].get("bodies_truncated") or tree.get("truncated")
            or tree.get("children_truncated")):
        return None
    bodies = hits[0].get("bodies") or []
    if (len(bodies) != 1 or bodies[0].get("is_solid") is not True
            or bodies[0].get("visible") is not True
            or not isinstance(bodies[0].get("handle"), str) or not bodies[0]["handle"]):
        return None
    return bodies[0]["handle"]


def _interference_body_visibility(visible):
    """Check a body bulb's readback after view_set hide/show."""
    def check(p):
        rows = p.get("bodies") or []
        valid = (p.get("action") == ("show" if visible else "hide") and len(rows) == 1
                 and rows[0].get("light_bulb_on") is visible
                 and rows[0].get("visible") is visible)
        return _measured("BlockA body visibility", rows, valid)
    return check


def _interference_hidden_overlap(visible):
    """Check hidden-body visibility and independently retain the measured placed overlap."""
    def check(p):
        measured = p.get("measured") or {}
        census = measured.get("body_census") or {}
        rows = census.get("bodies") or []
        body = next((r for r in rows if r.get("occurrence_path") == "BlockA:1"), {})
        pairs = measured.get("interferences") or []
        valid = (p.get("passed") is False and measured.get("analysis_complete") is True
                 and census.get("enumeration_complete") is True and census.get("count") == 2
                 and body.get("occurrence_visible") is True
                 and body.get("body_visible") is visible
                 and len(pairs) == 1
                 and {pairs[0].get("occurrence_one"), pairs[0].get("occurrence_two")}
                 == {"BlockA:1", "Peg:1"})
        return _measured("hidden BlockA body remains in interference analysis", {
            "body_visible": body.get("body_visible"), "pairs": pairs,
            "analysis_complete": measured.get("analysis_complete")}, valid)
    return check


def _interference_container_child(p):
    """The child selector a container refusal advertised analyses the child's body, complete and clear."""
    measured = p.get("measured") or {}
    census = measured.get("body_census") or {}
    rows = census.get("bodies") or []
    valid = (p.get("passed") is True and measured.get("analysis_complete") is True
             and measured.get("scope") == {"kind": "selected_occurrences", "occurrence_count": 2}
             and measured.get("interferences") == [] and measured.get("pairs_omitted") == 0
             and census.get("count") == len(rows) == 2 and census.get("enumeration_complete") is True
             and {row.get("occurrence_path") for row in rows} == {"Holder:1+Insert:1", "BlockB:1"})
    return _measured("advertised child selector analyses the child's body beside BlockB", measured, valid)


def _interference_scope_clear(p):
    """Check an interference-free selected subset while the wider design contains overlaps."""
    measured = p.get("measured") or {}
    census = measured.get("body_census") or {}
    rows = census.get("bodies") or []
    valid = (p.get("passed") is True and measured.get("analysis_complete") is True
             and measured.get("scope") == {"kind": "selected_occurrences", "occurrence_count": 2}
             and measured.get("interferences") == [] and measured.get("pairs_analyzed") == 0
             and measured.get("pairs_pruned") == 1 and measured.get("pairs_omitted") == 0
             and measured.get("root_bodies_checked") == 0
             and census.get("count") == census.get("returned_count") == len(rows) == 2
             and census.get("enumeration_complete") is True and census.get("truncated") is False
             and census.get("next_offset") is None
             and {row.get("occurrence_path") for row in rows} == {"BlockB:1", "Peg:1"}
             and all(row.get("pairs_analyzed") == row.get("pairs_omitted") == 0
                     and row.get("pairs_pruned") == 1 for row in rows))
    return _measured("clear selected body subset excludes the wider design's overlaps",
                     {"scope": measured.get("scope"), "census": census,
                      "pairs": {k: measured.get(k) for k in
                                ("pairs_analyzed", "pairs_pruned", "pairs_omitted")}}, valid)


def _interference_scope_page(offset):
    """Check a one-body census page and its independently repeated selected-pair result."""
    def check(p):
        measured = p.get("measured") or {}
        census = measured.get("body_census") or {}
        rows = census.get("bodies") or []
        scope = measured.get("scope") or {}
        pairs = measured.get("interferences") or []
        valid = (p.get("passed") is False and measured.get("analysis_complete") is True
                 and scope == {"kind": "selected_occurrences", "occurrence_count": 2}
                 and census.get("count") == 2 and census.get("offset") == offset
                 and census.get("returned_count") == 1 and census.get("enumeration_complete") is True
                 and census.get("truncated") is (offset == 0)
                 and census.get("next_offset") == (1 if offset == 0 else None)
                 and len(rows) == 1 and rows[0].get("body_handle")
                 and rows[0].get("body_name") and rows[0].get("occurrence_handle")
                 and rows[0].get("occurrence_path") in {"BlockA:1", "Peg:1"}
                 and rows[0].get("pairs_analyzed") == 1
                 and rows[0].get("pairs_pruned") == rows[0].get("pairs_omitted") == 0
                 and len(pairs) == 1
                 and {pairs[0].get("occurrence_one"), pairs[0].get("occurrence_two")}
                 == {"BlockA:1", "Peg:1"})
        key = "interference_scope_page_0_path"
        if valid and offset == 0:
            _RECALL[key] = rows[0]["occurrence_path"]
        elif valid:
            valid = rows[0]["occurrence_path"] != _RECALL.get(key)
        return _measured("selected placed bodies and pair participation on census page " + str(offset),
                         {"scope": scope, "body_census": census, "interferences": pairs}, valid)
    return check


# --- ACT 6: THE RESIZE - the parametric resize check (mirrors scenario S6) ---------------------
# Bump the one driving length; the whole bracket grows. It runs BEFORE the billet and the vise are
# built, which is the order a shop works in: the part is settled, then the stock is sized from it
# and the jaws close on that.
_RESIZE = [
    # the resize walks the whole part - frame it so the features are seen to move.
    _watch("Bracket:1"),
    ("view_screenshot", {"width": 400, "height": 300}, "ok", None),
    ("sketch_get", {"sketch_name": "BracketBody"}, "ok", None),   # before
    ("param_set", {"name": "PartLen", "expression": "160 mm"},
     _param_set_to("PartLen", 160), None),
    # 'new_errors' names the features that came back broken from THIS rebuild (the walk before it is
    # what makes that a difference) - a resize that breaks a downstream feature returns ok.
    ("design_recompute", {},
     lambda p: (p["recomputed"] is True and isinstance(p["error_count"], int)
                and "new_errors" not in p), None),
    ("sketch_get", {"sketch_name": "BracketBody"}, "ok", None),   # after - the block grew
    ("sketch_get", {"sketch_name": "BracketPocket"}, "ok", None),
    # THE MEASURED PROOF, on all three axes: the driver is the part's LENGTH, so x follows it a
    # third longer while the width and the height - their own parameters - hold exactly where they
    # were. A resize that moved every axis is a sketch anchored on the wrong point, and only
    # reading the two that must NOT move says so.
    ("model_inspect", {"target": "Bracket:1"},
     lambda p: _measured("only the length followed the driver (want x 160, y 80, z 45)",
                         {"x": p.get("x"), "y": p.get("y"), "z": p.get("z")},
                         _near(p.get("x"), 160.0, 0.1) and _near(p.get("y"), 80.0, 0.1)
                         and _near(p.get("z"), 45.0, 0.1)), None),
    # ...and the FEATURE side of the same recompute: the pocket's corner fillet was built at the
    # expression 'PocketRad', so the timeline row holds that name and the value it evaluates to now
    # (PartLen/15 at the driven 160 mm), not the 8 mm the feature was created at.
    ("design_get", {"include": ["timeline"], "timeline_params": True},
     _fillet_expression_followed("PocketRad", 160.0 / 15.0), None),
    # the StockCenter JO (the CAM WCS anchor) read back after the resize: parametrically anchored at
    # the part's own origin, it HOLDS position through the recompute.
    ("assembly_get", {"include": ["joint_origins"]}, _joint_origins_listed("StockCenter"), None),
    ("view_screenshot", {"width": 400, "height": 300}, "ok", None),
    ("param_set", {"name": "PartLen", "expression": "120 mm"},
     _param_set_to("PartLen", 120), None),   # restore
    ("design_recompute", {}, "ok", None),
    ("sketch_get", {"sketch_name": "BracketBody"}, "ok", None),   # restored
    ("param_add", {"name": "ScratchDim", "expression": "5 mm"}, _param_added("ScratchDim", 5), None),
    ("param_delete", {"name": "ScratchDim"}, _param_deleted("ScratchDim"), None),
    # the design at rest after the rebuild: the census the check ran, with the rows it found.
    ("assembly_inspect_interference", {}, _interference_measured, None),
    # FSAE-0922-INTERFERENCE-INSTANCE-1: a component instanced twice must be named EXACTLY, never
    # guessed from candidates - and two occurrences with no body must refuse, never pass. Isolated
    # in its own scratch document so the census is exactly what this rig places.
    ("doc_get", {}, _home_document,
     ("interference_story", _recall("interference_story", _home_address))),
    ("doc_new",
     lambda c: {"expect_document": _ctx_get(c, "interference_story", "the story document")},
     _new_document,
     ("interference_scratch", _recall("interference_scratch", lambda p: p["document_handle"]))),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "EmptyA", "activate": True}), _made_component, None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "EmptyB", "activate": True}), _made_component, None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    # two occurrences with ZERO solid bodies between them - the false pass this row exists to catch.
    ("assembly_inspect_interference", {}, _refused("EmptyA:1", "EmptyB:1", "NOT a pass"), None),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "BlockA", "activate": True}), _made_component, None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "BlockAS"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"geometry": [{"kind": "rectangle", "x1": 0, "y1": 0,
                                                    "x2": 10, "y2": 10}], "sketch_name": "BlockAS"}),
     "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "BlockAS", "profile_index": 0, "distance": 10}),
     _extruded, None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "BlockB", "activate": True, "x": 50}),
     _made_component, None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "BlockBS"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"geometry": [{"kind": "rectangle", "x1": 0, "y1": 0,
                                                    "x2": 10, "y2": 10}], "sketch_name": "BlockBS"}),
     "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "BlockBS", "profile_index": 0, "distance": 10}),
     _extruded, None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    ("assembly_get", {"include": ["poses"]}, _separated_block_poses, None),
    ("assembly_inspect_interference", {}, _separated_interference(False), None),
    ("assembly_inspect_interference", {"include_coincident_faces": True},
     _separated_interference(True), None),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "Peg", "activate": True}), _made_component, None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "PegS"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"geometry": [{"kind": "circle", "cx": 5, "cy": 5, "radius": 2}],
                                     "sketch_name": "PegS"}), "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "PegS", "profile_index": 0, "distance": 10}),
     _extruded, None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    # a second instance of the SAME component, overlapping the OTHER block - the multi-instance case
    # analyzeInterference alone cannot name (native bodies carry no assemblyContext).
    ("design_add_instance",
     lambda c: _interference_pin(c, {"component": "Peg", "x": 50}),
     lambda p: p.get("created") is True, None),
    ("assembly_inspect_interference", {}, _interference_pair_named, None),
    ("assembly_inspect_interference", {"occurrences": []},
     _refused("at least one occurrence"), None),
    ("assembly_inspect_interference", {"occurrences": ["BlockA:1", "BlockA:1"]},
     _refused("repeats placement", "BlockA:1"), None),
    ("assembly_inspect_interference", {"occurrences": ["NoSuch:1", "BlockA:1"]},
     _refused("no occurrence matching", "NoSuch:1"), None),
    # EmptyA holds no solid body: beside the two separated blocks it is refused, not dropped.
    ("assembly_inspect_interference", {"occurrences": ["EmptyA:1", "BlockA:1", "BlockB:1"]},
     _refused("1 selected occurrence(s) hold no direct solid body", "EmptyA:1 (no child occurrence found)",
              "Nothing was analysed."), None),
    ("assembly_inspect_interference", {"occurrences": ["BlockB:1", "Peg:1"], "max_results": 2},
     _interference_scope_clear, None),
    # An explicit list analyzes only these two placed bodies; the census is paged independently
    # from pair work, and each page re-runs the scoped check.
    ("assembly_inspect_interference", {"occurrences": ["Peg:1", "BlockA:1"], "max_results": 1},
     _interference_scope_page(0), None),
    ("assembly_inspect_interference", {"occurrences": ["Peg:1", "BlockA:1"], "max_results": 1, "offset": 1},
     _interference_scope_page(1), None),
    ("design_get", {"include": ["tree"], "tree_bodies": True, "tree_handles": True,
                     "max_depth": 2, "max_results": 2000},
     lambda p: _measured("BlockA body identity for visibility control", p.get("tree"),
                         _interference_body_handle(p) is not None),
     ("interference_hidden_body", _recall("interference_hidden_body", _interference_body_handle))),
    ("view_set", lambda c: _interference_pin(c, {"action": "hide", "target": [
         _ctx_get(c, "interference_hidden_body", "BlockA body handle")]}),
     _interference_body_visibility(False), None),
    ("assembly_inspect_interference", {"occurrences": ["Peg:1", "BlockA:1"], "max_results": 2},
     _interference_hidden_overlap(False), None),
    ("view_set", lambda c: _interference_pin(c, {"action": "show", "target": [
         _ctx_get(c, "interference_hidden_body", "BlockA body handle")]}),
     _interference_body_visibility(True), None),
    ("assembly_inspect_interference", {"occurrences": ["Peg:1", "BlockA:1"], "max_results": 2},
     _interference_hidden_overlap(True), None),
    ("find_geometry", {"target": "Peg", "kind": "cylinder_face"}, _peg_faces_per_instance, None),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "OverlapPart", "activate": True, "x": 200}),
     _made_component, None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "OverlapCubeA"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"sketch_name": "OverlapCubeA", "geometry": [
         {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}]}), "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "OverlapCubeA", "profile_index": 0,
                                     "distance": 20}), _extruded, None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    ("design_add_instance",
     lambda c: _interference_pin(c, {"component": "OverlapPart", "x": 210}),
     lambda p: p.get("created") is True, None),
    ("assembly_get", {"include": ["poses"]}, _shared_cube_poses(1), None),
    ("assembly_inspect_interference", {}, _shared_cube_overlap(4.0, 3, 12), None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "OverlapPart:1"}), "ok", None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "OverlapCubeB"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"sketch_name": "OverlapCubeB", "geometry": [
         {"kind": "rectangle", "x1": 50, "y1": 0, "x2": 70, "y2": 20}]}), "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "OverlapCubeB", "profile_index": 0,
                                     "distance": 20}), _extruded, None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    ("assembly_get", {"include": ["poses"]}, _shared_cube_poses(2), None),
    ("assembly_inspect_interference", {}, _shared_cube_overlap(8.0, 4, 24), None),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "ContactPart", "activate": True, "x": 400}),
     _made_component, None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "ContactLeft"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"sketch_name": "ContactLeft", "geometry": [
         {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}]}), "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "ContactLeft", "distance": 20,
                                     "operation": "new"}), _extruded, None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "ContactRight"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"sketch_name": "ContactRight", "geometry": [
         {"kind": "rectangle", "x1": 20, "y1": 0, "x2": 40, "y2": 20}]}), "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "ContactRight", "distance": 20,
                                     "operation": "new"}), _extruded, None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    ("assembly_get", {"include": ["poses"]}, _contact_part_poses(2), None),
    ("assembly_inspect_interference", {}, _contact_overlap([]), None),
    ("assembly_inspect_interference", {"include_coincident_faces": True}, _contact_overlap([0.0]), None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "ContactPart:1"}), "ok", None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "ContactMiddle"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"sketch_name": "ContactMiddle", "geometry": [
         {"kind": "rectangle", "x1": 10, "y1": 0, "x2": 30, "y2": 20}]}), "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "ContactMiddle", "distance": 20,
                                     "operation": "new"}), _extruded, None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    ("assembly_get", {"include": ["poses"]}, _contact_part_poses(3), None),
    ("assembly_inspect_interference", {}, _contact_overlap([8.0]), None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "ContactAlias"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"sketch_name": "ContactAlias", "geometry": [
         {"kind": "rectangle", "x1": 400, "y1": 0, "x2": 420, "y2": 20}]}), "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "ContactAlias", "distance": 20,
                                     "operation": "new"}), _extruded, None),
    ("design_get", {"include": ["tree"], "max_depth": 1, "tree_bodies": True, "tree_handles": True},
     lambda p: len(p["tree"]["root_bodies"]) == 1
     and bool(p["tree"]["root_bodies"][0].get("handle")),
     ("contact_alias", _recall("contact_alias", lambda p: p["tree"]["root_bodies"][0]["handle"]))),
    ("design_set_name",
     lambda c: _interference_pin(c, {"target": _ctx_get(c, "contact_alias", "the sole root body"),
                                     "new_name": "ContactPart:1"}),
     lambda p: p.get("name") == "ContactPart:1" and p.get("kind") == "body", None),
    ("model_inspect", lambda c: {"target": _ctx_get(c, "contact_alias", "the colliding-label body")},
     lambda p: _near(p.get("x"), 20, 0.001) and _near(p.get("y"), 20, 0.001)
     and _near(p.get("z"), 20, 0.001), None),
    ("assembly_inspect_interference", {}, _contact_overlap([8.0, 12.0]), None),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "BudgetPart", "activate": True, "x": 600}),
     _made_component, None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "BudgetCube"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"sketch_name": "BudgetCube", "geometry": [
         {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 20}]}), "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "BudgetCube", "distance": 20}),
     _extruded, None),
    ("model_pattern_rectangular",
     lambda c: _interference_pin(c, {"bodies": ["BudgetPart"], "direction_one": "x",
                                     "quantity_one": 102, "spacing_one": 0.1}),
     _patterned("total_instances", 102), None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    ("assembly_get", {"include": ["poses"]},
     lambda p: _measured("102 overlapping cubes, each shifted 0.1 mm",
                         {"rows": [r for r in p.get("occurrences", [])
                                   if r.get("name") == "BudgetPart:1"]},
                         any(r.get("name") == "BudgetPart:1" and r.get("body_count") == 102
                             and len(r.get("bbox_size", [])) == 3
                             and all(_near(a, b, 0.005) for a, b in
                                     zip(r["bbox_size"], [30.1, 20, 20]))
                             for r in p.get("occurrences", []))), None),
    ("assembly_inspect_interference", {}, _interference_budget, None),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "HelixCheck", "activate": True}),
     _made_component, None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "FractionalHelix"}), "ok", None),
    ("sketch_add_3d_spline",
     lambda c: _interference_pin(c, {"sketch_name": "FractionalHelix", "helix": {
         "axis": "z", "center": [0, 0, 100], "radius": 10, "pitch": 10,
         "turns": 1.1, "points_per_turn": 24}}),
     lambda p: p.get("kind") == "fitted" and p.get("is_valid") is True, None),
    ("model_pipe",
     lambda c: _interference_pin(c, {"path": "sketch:FractionalHelix", "section_size": 1}),
     lambda p: p.get("path_curves") == 1, None),
    ("find_geometry", {"target": "HelixCheck:1", "kind": "planar_face", "max_results": 2},
     _fractional_helix_cap, None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "ShortHelix"}), "ok", None),
    ("sketch_add_3d_spline",
     lambda c: _interference_pin(c, {"sketch_name": "ShortHelix", "helix": {
         "axis": "z", "center": [0, 0, 120], "radius": 10, "pitch": 10,
         "turns": 0.1, "points_per_turn": 6}}),
     lambda p: p.get("kind") == "fitted" and p.get("is_valid") is True
     and p.get("point_count") == 3, None),
    ("model_pipe",
     lambda c: _interference_pin(c, {"path": "sketch:ShortHelix", "section_size": 1}),
     lambda p: p.get("path_curves") == 1, None),
    ("find_geometry", {"target": "HelixCheck:1", "kind": "planar_face",
                       "nearest_to": [8.09017, 5.87785, 121], "max_results": 1},
     lambda p: _fractional_helix_cap(p, turns=0.1, start_z=120), None),
    # A selected sub-assembly with no direct body but a child occurrence: the refusal names the
    # child selector, and that selector then analyses the child's body beside BlockB.
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "Holder", "activate": True}), _made_component, None),
    ("model_create_component",
     lambda c: _interference_pin(c, {"name": "Insert", "parent": "Holder:1", "activate": True}), _made_component, None),
    ("sketch_create",
     lambda c: _interference_pin(c, {"plane": "xy", "name": "InsertS"}), "ok", None),
    ("sketch_add_geometry",
     lambda c: _interference_pin(c, {"geometry": [{"kind": "rectangle", "x1": 400, "y1": 0,
                                                    "x2": 410, "y2": 10}], "sketch_name": "InsertS"}),
     "ok", None),
    ("model_extrude",
     lambda c: _interference_pin(c, {"sketch_name": "InsertS", "profile_index": 0, "distance": 10}),
     _extruded, None),
    ("design_activate_component",
     lambda c: _interference_pin(c, {"occurrence": "root"}), "ok", None),
    ("assembly_inspect_interference", {"occurrences": ["Holder:1", "BlockB:1"]},
     _refused("1 selected occurrence(s) hold no direct solid body",
              "Holder:1 (child occurrences: Holder:1+Insert:1)",
              "Pass the child occurrences that hold the bodies instead", "Nothing was analysed."), None),
    ("assembly_inspect_interference", {"occurrences": ["Holder:1+Insert:1", "BlockB:1"], "max_results": 2},
     _interference_container_child, None),
    ("doc_activate",
     lambda c: {"name": _ctx_get(c, "interference_story", "the story document"),
                "expect_document": _ctx_get(c, "interference_scratch",
                                            "the interference scratch document")},
     "ok", None),
    ("doc_close",
     lambda c: {"name": _ctx_get(c, "interference_scratch", "the interference scratch document"),
                "save_changes": False,
                "expect_document": _ctx_get(c, "interference_story", "the story document")},
     _document_closed, None),
    # TIMELINE: roll back over the assembly, group a range, suppress and restore, then return the
    # marker to the end. Every beat reads the marker back, and the blast-radius refusal is exercised
    # WITHOUT the confirmation so nothing is discarded from the story.
    ("design_edit_timeline", {"action": "roll", "to": "previous"},
     lambda p: p.get("marker_position") == p.get("marker_position_before", -1) - 1, None),
    ("design_edit_timeline", {"action": "delete_after_marker"}, "refused", None),
    ("design_edit_timeline", {"action": "roll", "to": "end"},
     lambda p: p.get("rolled_back") == 0, None),
    ("design_edit_timeline", {"action": "roll", "feature": "NoSuchFeature"}, "refused", None),
    ("design_edit_timeline", {"action": "group", "feature": "ScratchDim",
                              "end_feature": "ScratchDim"}, "refused", None),
    # ATTRIBUTES: tag a real timeline feature (the part's own step floor), re-tag it,
    # then remove the tag. An attribute reached through the timeline lives on the ENTITY the item
    # wraps, and every beat reads back both the value on that entity and the design-wide census of
    # the group/name pair - which is what turns the delete into a verdict instead of a claim.
    ("design_edit_timeline", {"action": "set_attribute", "feature": "StepFloor",
                              "attribute_group": "sweep_w11_8", "attribute_name": "note",
                              "attribute_value": "beat-1"},
     lambda p: p.get("value") == "beat-1" and p.get("design_matches", 0) >= 1
     and "previous_value" not in p, None),
    # add() on an existing group/name UPDATES in place, so the value it replaced is readable only
    # before the call - and it is disclosed rather than lost.
    ("design_edit_timeline", {"action": "set_attribute", "feature": "StepFloor",
                              "attribute_group": "sweep_w11_8", "attribute_name": "note",
                              "attribute_value": "beat-2"},
     lambda p: p.get("previous_value") == "beat-1" and p.get("value") == "beat-2", None),
    # this tool's own wire bound on the value, refused with the length that broke it.
    ("design_edit_timeline", {"action": "set_attribute", "feature": "StepFloor",
                              "attribute_group": "sweep_w11_8", "attribute_name": "note",
                              "attribute_value": "x" * 10001}, "refused", None),
    # a leading 're:' turns the attribute search into a REGULAR EXPRESSION instead of naming this
    # literal group, so it is refused rather than silently matching something else.
    ("design_edit_timeline", {"action": "set_attribute", "feature": "StepFloor",
                              "attribute_group": "re:sweep", "attribute_name": "note",
                              "attribute_value": "beat-3"}, "refused", None),
    ("design_edit_timeline", {"action": "delete_attribute", "feature": "StepFloor",
                              "attribute_group": "sweep_w11_8", "attribute_name": "note"},
     lambda p: p.get("attribute_deleted") is True and p.get("deleted_value") == "beat-2"
     and p.get("design_matches") == 0, None),
    # the same delete again has nothing to remove, and says so naming the group/name pair.
    ("design_edit_timeline", {"action": "delete_attribute", "feature": "StepFloor",
                              "attribute_group": "sweep_w11_8", "attribute_name": "note"},
     "refused", None),
    # THE 'name@index' FORM - a valid address in its own right, resolved by reading each timeline
    # object's OWN .index - the same number design_get publishes - never by position in a list, so
    # the index taken from this read is the index that must resolve.
    # the slice is a DICT (marker_position / count / summary / groups / timeline) and the ordered
    # rows sit under its own 'timeline' key - each a terse {index, name, type}.
    ("design_get", {"include": ["timeline"]},
     lambda p: any(r.get("name") == "StepFloor" for r in p["timeline"]["timeline"]),
     ("hub_index", lambda p: next(r["index"] for r in p["timeline"]["timeline"]
                                  if r["name"] == "StepFloor"))),
    ("design_edit_timeline", lambda c: {
        "action": "set_attribute",
        "feature": "StepFloor@{0}".format(_ctx_get(c, "hub_index", "the step floor's index")),
        "attribute_group": "sweep_w1d", "attribute_name": "at", "attribute_value": "by-index"},
     lambda p: p.get("value") == "by-index" and p.get("feature") == "StepFloor", None),
    ("design_edit_timeline", lambda c: {
        "action": "delete_attribute",
        "feature": "StepFloor@{0}".format(_ctx_get(c, "hub_index", "the step floor's index")),
        "attribute_group": "sweep_w1d", "attribute_name": "at"},
     lambda p: p.get("attribute_deleted") is True, None),
    # the NEIGHBOURING index: the pair must agree, so an off-by-one is refused - and the refusal
    # says what sits at the index asked for and which index 'StepFloor' answers to now, rather than
    # editing the feature next door.
    ("design_edit_timeline", lambda c: {
        "action": "set_attribute",
        "feature": "StepFloor@{0}".format(_ctx_get(c, "hub_index",
                                                         "the step floor's index") + 1),
        "attribute_group": "sweep_w1d", "attribute_name": "at", "attribute_value": "x"},
     _refused("'StepFloor' is at index", "design_get(include=['timeline'])"), None),
    # THE '<component>/<name>' FORM: two components each hold a plane named 'AddrPlane', so the bare
    # name is refused naming BOTH qualified candidates; the qualified form deletes the right one, and
    # the bare name resolving alone afterwards is the independent proof it was the right one that went.
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "AddrCompA", "activate": True}, _made_component, None),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 5, "name": "AddrPlane"},
     _datum_plane("xy"), None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_create_component", {"name": "AddrCompB", "activate": True}, _made_component, None),
    ("model_construction", {"kind": "plane", "plane": "xy", "offset": 5, "name": "AddrPlane"},
     _datum_plane("xy"), None),
    # the two same-named planes each own an offset parameter: a row resolved by name hands one
    # plane's parameters to the other.
    ("design_get", {"include": ["timeline"], "timeline_params": True, "max_results": 5000},
     _addr_planes_own_their_params, None),
    ("design_delete_feature", {"feature": "AddrPlane"},
     _refused("AddrCompA/AddrPlane", "AddrCompB/AddrPlane", "matches 2 timeline objects"), None),
    ("design_delete_feature", {"feature": "AddrCompA/AddrPlane"},
     lambda p: p["deleted"] is True and p["feature"] == "AddrPlane", None),
    ("design_delete_feature", {"feature": "AddrPlane"},
     lambda p: p["deleted"] is True and p["feature"] == "AddrPlane", None),
]

# --- the retained SCRATCH fixtures - the precondition fallbacks (today's proven step bodies) ---
# When an act's precondition read fails (an upstream act could not build the geometry it consumes),
# the act runs one of these instead, so its tools are still covered - each row marked "(fallback
# fixture)". These are the minimal self-contained scratch fixtures the sweep has always used.

_SOLIDS_FB = (
    _box("FbSolid")
    + [
        ("find_geometry", {"target": "FbSolid", "kind": "planar_face", "nearest_to": [10, 10, 10], "max_results": 1}, "ok", _fg("fb_body")),
        ("appearance_set", {"target": "FbSolid", "color": "#1E8E3E"}, "ok", None),
        ("model_set_material", {"target": "FbSolid", "material": "Steel"}, _material_assigned, None),
        ("model_mirror", lambda c: {"bodies": [_ctx_get(c, "fb_body", "body handle")], "plane": "yz"}, _mirrored, None),
        ("model_pattern_rectangular", lambda c: {"bodies": [_ctx_get(c, "fb_body", "body handle")], "quantity_one": 2, "spacing_one": 60, "direction_one": "y"}, _patterned("total_instances", 2), None),
        ("model_pattern_circular", lambda c: {"bodies": [_ctx_get(c, "fb_body", "body handle")], "quantity": 3, "total_angle_deg": 360, "axis": "z"}, _patterned("quantity", 3), None),
        ("find_geometry", {"target": "FbSolid", "kind": "planar_face", "nearest_to": [10, 10, 10], "max_results": 1}, "ok", _fg("fb_top")),
        ("model_hole", lambda c: {"face": _ctx_get(c, "fb_top", "top face"), "hole_type": "simple", "diameter": "4 mm", "extent": "blind", "depth": "8 mm", "points": [[5, 5, 0]]}, _drilled(1), None),
        ("find_geometry", {"target": "FbSolid", "kind": "planar_face", "nearest_to": [0, 10, 5], "max_results": 1}, "ok", _fg("fb_side")),
        ("model_draft", lambda c: {"faces": [_ctx_get(c, "fb_side", "side face")], "pull_direction": "xy", "angle_deg": 3},
         _drafted, None),
        ("model_measure_between", lambda c: {"a": _ctx_get(c, "fb_body", "body"), "b": "FbSolid"}, _gap_measured, None),
        # a face compared with ITSELF is parallel to itself, so this beat asserts the verdict too.
        ("model_measure_relation", lambda c: {"relation": "parallel", "entity_a": _ctx_get(c, "fb_top", "top face"), "entity_b": _ctx_get(c, "fb_top", "top face")}, _relation_passes("parallel"), None),
        ("model_inspect", {"target": "FbSolid"}, _extent_measured, None),
        ("model_create_component", {"name": "FbRev", "activate": True}, _made_component, None),
        ("sketch_create", {"plane": "xz", "name": "FbRevS"}, "ok", None),
        ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 10, "y1": 0,
                                               "x2": 20, "y2": 30}],
                                 "sketch_name": "FbRevS"}, "ok", None),
        ("model_revolve", {"sketch_name": "FbRevS", "profile_index": 0, "axis": "z", "angle_deg": 360}, _revolved, None),
        ("model_create_component", {"name": "FbSwp", "activate": True}, _made_component, None),
        ("sketch_create", {"plane": "xz", "name": "FbPath"}, "ok", None),
        ("sketch_add_geometry", {"geometry": [{"kind": "line", "x1": 0, "y1": 0,
                                               "x2": 0, "y2": 40}],
                                 "sketch_name": "FbPath"}, "ok", None),
        ("sketch_create", {"plane": "xy", "name": "FbProf"}, "ok", None),
        ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 5}],
                                 "sketch_name": "FbProf"}, "ok", None),
        ("model_sweep", {"profile": {"sketch": "FbProf", "profile_index": 0}, "path": "sketch:FbPath"}, _swept, None),
        ("model_create_component", {"name": "FbLft", "activate": True}, _made_component, None),
        ("sketch_create", {"plane": "xy", "name": "FbLb"}, "ok", None),
        ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 10}],
                                 "sketch_name": "FbLb"}, "ok", None),
        ("sketch_get", {"sketch_name": "FbLb"}, "ok", _prof("fb_lb")),
        ("model_construction", {"kind": "plane", "plane": "xy", "offset": 40, "name": "FbTop"},
         _datum_plane("xy"), None),
        ("sketch_create", {"plane": "FbTop", "name": "FbLt"}, "ok", None),
        ("sketch_add_geometry", {"geometry": [{"kind": "circle", "cx": 0, "cy": 0, "radius": 5}],
                                 "sketch_name": "FbLt"}, "ok", None),
        ("sketch_get", {"sketch_name": "FbLt"}, "ok", _prof("fb_lt")),
        ("model_loft", lambda c: {"profiles": [_ctx_get(c, "fb_lb", "loft bottom"), _ctx_get(c, "fb_lt", "loft top")]}, _lofted, None),
        ("model_create_component", {"name": "FbCmb", "activate": True}, _made_component, None),
        ("sketch_create", {"plane": "xy", "name": "FbCb1"}, "ok", None),
        ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 0, "y1": 0,
                                               "x2": 30, "y2": 30}],
                                 "sketch_name": "FbCb1"}, "ok", None),
        ("model_extrude", {"sketch_name": "FbCb1", "profile_index": 0, "distance": 10}, _extruded, None),
        ("sketch_create", {"plane": "xy", "name": "FbCb2"}, "ok", None),
        ("sketch_add_geometry", {"geometry": [{"kind": "rectangle", "x1": 20, "y1": 20,
                                               "x2": 50, "y2": 50}],
                                 "sketch_name": "FbCb2"}, "ok", None),
        ("model_extrude", {"sketch_name": "FbCb2", "profile_index": 0, "distance": 10}, _extruded, None),
        ("find_geometry", {"target": "FbCmb", "kind": "planar_face", "nearest_to": [5, 5, 10], "max_results": 1}, "ok", _fg("fb_c1")),
        ("find_geometry", {"target": "FbCmb", "kind": "planar_face", "nearest_to": [45, 45, 10], "max_results": 1}, "ok", _fg("fb_c2")),
        ("model_combine", lambda c: {"target": _ctx_get(c, "fb_c1", "combine target"), "tools": [_ctx_get(c, "fb_c2", "combine tool")], "operation": "join"}, _joined, None),
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
        # the WCS anchor by the name the CAM acts bind to, so a fallback world still carries one.
        ("joint_create_origin", {"anchor": "coordinates", "target": "origin",
                                 "name": "StockCenter"},
         _joint_origin_at("StockCenter", 0, 0, 0), None),
    ]
)

# ACT 4 fallback: a scratch details fixture.
_DETAILS_FB = (
    _box("FbDet")
    + [
        ("find_geometry", {"target": "FbDet", "kind": "line_edge", "max_results": 1}, "ok", _fg("fd_edge")),
        ("model_fillet", lambda c: {"edges": [_ctx_get(c, "fd_edge", "edge")], "radius": 1}, _filleted, None),
        ("find_geometry", {"target": "FbDet", "kind": "line_edge", "max_results": 1}, "ok", _fg("fd_edge2")),
        ("model_chamfer", lambda c: {"edges": [_ctx_get(c, "fd_edge2", "edge")], "distance": 0.5}, _chamfered, None),
        ("find_geometry", {"target": "FbDet", "kind": "planar_face", "nearest_to": [10, 10, 10], "max_results": 1}, "ok", _fg("fd_top")),
        ("model_shell", lambda c: {"body_name": "FbDet", "remove_faces": [_ctx_get(c, "fd_top", "top")], "thickness": 2}, _shelled, None),
        ("model_construction", {"kind": "plane", "plane": "xy", "offset": 5, "name": "FbWart"},
         _datum_plane("xy"), None),
        ("design_delete_feature", {"feature": "FbWart"},
         lambda p: (p["deleted"] is True and p["feature"] == "FbWart"
                    and "timeline_warning" not in p), None),
        ("model_create_component", {"name": "FbJunk", "activate": False}, _made_component_inactive, None),
        ("design_delete_occurrence", {"occurrence": "FbJunk:1"},
         lambda p: (p["deleted"] is True and p["occurrence"] == "FbJunk:1"
                    and "timeline_warning" not in p), None),
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
        ("view_section", {"action": "cut", "plane": "xy", "offset": 5,
                          "auto_view": False},
         _section_created(),
         ("fb_section_one", _recall("fb_section_one", lambda p: p["section"]))),
        ("view_section", {"action": "cut", "plane": "yz", "offset": 5,
                          "auto_view": False},
         _section_created("fb_section_one"),
         ("fb_section_two", _recall("fb_section_two", lambda p: p["section"]))),
        ("view_section", {"action": "list"},
         _section_census(("fb_section_one", "fb_section_two"), (False, True)), None),
        ("view_section", lambda c: {"action": "clear",
                                    "section": _ctx_get(c, "fb_section_one",
                                                        "the first fallback section")},
         _section_named_clear("fb_section_one"), None),
        ("view_section", {"action": "list"},
         _section_census(("fb_section_two",), (True,)), None),
        ("view_screenshot", {"width": 400, "height": 300}, "ok", None),
        ("view_section", {"action": "clear"},
         lambda p: (p["removed"] == [_RECALL.get("fb_section_two")]
                    and p["removed_count"] == p["sections_before"] == 1
                    and p["sections_after"] == 0), None),
        ("view_screenshot_multi", {"views": ["front", "top"], "width": 300, "height": 250}, "ok", None),
    ]
)

# ACT 6 fallback: a scratch parameter set/delete.
_RESIZE_FB = [
    ("param_add", {"name": "FbParam", "expression": "12 mm"}, _param_added("FbParam", 12), None),
    ("param_set", {"name": "FbParam", "expression": "14 mm"}, _param_set_to("FbParam", 14), None),
    ("design_recompute", {},
     lambda p: (p["recomputed"] is True and isinstance(p["error_count"], int)
                and "new_errors" not in p), None),
    ("param_delete", {"name": "FbParam"}, _param_deleted("FbParam"), None),
]
