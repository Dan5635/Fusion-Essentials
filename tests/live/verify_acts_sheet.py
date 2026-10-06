# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The sheet-metal coupon act in the existing live sweep."""

from pathlib import Path
import json
import math
import time
import re

from cloud_config import FOLDER, PROJECT
from verify_acts_cam import _operation_row, _op_valid
from verify_acts_model_sweep import (_retire_reads, _retire_compare, _retire_material_state,
                                    _retire_design_state, _sweep_mode_shape)
from verify_acts_model_solids import _edge_extent_geometry
from verify_acts_cloud import (_drawing_terminal, _drawing_terminal_payload,
                               _file_settled, _opened, _version_args, _version_record,
                               _version_settled, _version_snapshot, _versioned, _version_current)

from verify_core import (EXPORT_DIR, _RECALL, _ctx_get, _dwell, _extruded, _measured, facade,
                         _near, _recall, _refused, _home_address)

_SEED = "SM Sweep Seed"
_SEED2 = "SM Sweep Second Seed"
_PART = "SM Sweep Blank"
_RULE = "SM Sweep Rule"
_BASE = "SM Sweep Base"
_SEED_BASE = "SM Sweep Seed Base"
_BEND = "SM Sweep Bend"
_BEND2 = "SM Sweep Second Bend"
_SLOT = "SM Sweep Cross Bend Slot"
_CAM_SETUP = "SM Sweep Laser Setup"
_CAM_OP = "SM Sweep Laser Perimeter"
_CAM_UNSELECTED = "SM Sweep Unfinished Path"
_MILL_SETUP = "SM Sweep Flat Mill Setup"
_MILL_OP = "SM Sweep Flat Mill Contour"
_LASER_LIBRARY = "systemlibraryroot://Samples/Cutting Tools (Metric)"
_STAMP = time.strftime("%Y%m%d-%H%M%S")
_DRAW_SOURCE = "SM Sweep Coupon " + _STAMP
_DRAW_KEY = "sm-sweep-drawing-" + _STAMP
_FLAT_TEMPLATE = "SM Sweep Flat " + _STAMP
_DXF = EXPORT_DIR + "/sm_sweep_flat.dxf"
_CUT_DXF = EXPORT_DIR + "/sm_sweep_cut.dxf"
_REFUSED_DXF = EXPORT_DIR + "/sm_sweep_flat_refused_" + _STAMP + ".dxf"
_PDF = EXPORT_DIR + "/sm_sweep_drawing.pdf"
_PDF_KEY = "sm-sweep-pdf-" + _STAMP
_DRAWING_PNG = EXPORT_DIR + "/sm_sweep_drawing_" + _STAMP + ".png"


def _ruled_component(p):
    """Require native sheet-metal component creation and an inherited rule."""
    return _measured("sheet component rule", {"component": p.get("component"),
                     "rule": p.get("active_sheet_metal_rule")},
                     p.get("sheet_metal") is True and p.get("component") == _SEED
                     and p.get("activated") is True
                     and bool(p.get("active_sheet_metal_rule")))


def _rule_settings(p):
    """Read copied rule values from the design-local collection."""
    rows = (p.get("rules") or {}).get("rules") or []
    matches = [r for r in rows if r.get("name") == _RULE]
    r = matches[0] if len(matches) == 1 else {}
    return _measured("design-local rule", {"matches": len(matches), "rule": r},
                     len(matches) == 1 and r.get("ref") == "design:" + _RULE
                     and _near((r.get("thickness") or {}).get("value_cm"), 0.15, 1e-6)
                     and _near((r.get("bendRadius") or {}).get("value_cm"), 0.2, 1e-6)
                     and _near((r.get("gap") or {}).get("value_cm"), 0.05, 1e-6)
                     and _near(r.get("k_factor"), 0.42, 1e-9))


def _seed_guard(p):
    """Check refusal preserved both the seed rule and its ordinary body."""
    rules = (p.get("rules") or {}).get("rules") or []
    components = (p.get("components") or {}).get("components") or []
    seed = [r for r in components if r.get("component") == _SEED]
    steel = [r for r in rules if r.get("name") == "Steel (mm)"]
    return _measured("ruled-component conversion refusal", {"seed": seed, "steel": steel},
                     len(seed) == 1 and len(steel) == 1
                     and len(seed[0].get("bodies") or []) == 1
                     and seed[0]["bodies"][0].get("is_sheet_metal") is False
                     and _near((steel[0].get("thickness") or {}).get("value_cm"), 0.25, 1e-6))


# addByCopy under a name already in use RAISES 'Invalid name, rule already exists' (measured live on
# 2706.0.97) and lands nothing, so the only way a same-named duplicate arises is Fusion's OWN copy on
# addNewSheetMetalComponent - the raw API, bypassing the tool's adoption entirely.
_DUP_STEEL_RULE_SCRIPT = '''import adsk.core, adsk.fusion

def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    occ = design.rootComponent.occurrences.addNewSheetMetalComponent(adsk.core.Matrix3D.create())
    print("added " + occ.name)
    print("component " + occ.component.name)
'''


def _save_raw_names(p):
    """Recall the raw duplicate's occurrence name (delete target) and bare component name (census)."""
    lines = p.splitlines() if isinstance(p, str) else []
    occ = next((ln[len("added "):].strip() for ln in lines if ln.startswith("added ")), None)
    comp = next((ln[len("component "):].strip() for ln in lines if ln.startswith("component ")), None)
    if not occ or not comp:
        raise ValueError(f"script output lacks the 'added'/'component' lines: {p!r}")
    _RECALL["sm_raw_component"] = comp
    _RECALL["sm_raw_occurrence"] = occ
    return occ


def _rule_adopted_from_copy(p):
    """Require the tool's own before/after census to fold a fresh same-named copy into 'Steel (mm)'."""
    return _measured("sheet component rule adopted from a same-named copy",
                     {"active_rule": p.get("active_sheet_metal_rule"),
                      "adopted": p.get("rule_adopted_existing"),
                      "deleted": p.get("rule_copy_deleted")},
                     p.get("sheet_metal") is True and p.get("rule_adopted_existing") is True
                     and p.get("rule_copy_deleted") is True
                     and p.get("active_sheet_metal_rule") == "Steel (mm)")


def _design_rule_count_after_adopt(p):
    """Require the design rule count unchanged from before the adopt, with exactly one 'Steel (mm)'."""
    rows = (p.get("rules") or {}).get("rules") or []
    before = _RECALL.get("sm_rule_count_before_adopt")
    steel = [r for r in rows if r.get("name") == "Steel (mm)"]
    return _measured("design rule count unchanged after adoption",
                     {"before": before, "after": len(rows), "steel_count": len(steel)},
                     isinstance(before, int) and len(rows) == before and len(steel) == 1)


def _duplicate_steel_rows(p):
    """Require a direct-API duplicate name to read back as ordinal '#1'/'#2' refs with distinct indices."""
    rows = (p.get("rules") or {}).get("rules") or []
    dups = sorted([r for r in rows if r.get("name") == "Steel (mm)"], key=lambda r: r.get("ref") or "")
    return _measured("duplicate Steel (mm) rows carry ordinal refs", {"rows": dups},
                     len(dups) == 2 and dups[0].get("ref") == "design:Steel (mm)#1"
                     and dups[1].get("ref") == "design:Steel (mm)#2"
                     and isinstance(dups[0].get("index"), int) and isinstance(dups[1].get("index"), int)
                     and dups[0]["index"] != dups[1]["index"])


def _second_dup_gap_updated(p):
    """Require the '#2' ordinal ref to resolve and land its own gap edit."""
    row = p.get("rule") or {}
    return _measured("duplicate rule '#2' gap update", {"rule": row, "applied": p.get("applied")},
                     p.get("action") == "update" and row.get("ref") == "design:Steel (mm)#2"
                     and _near((row.get("gap") or {}).get("value_cm"), 0.06, 1e-6)
                     and "gap" in (p.get("applied") or []))


def _dup_gap_isolated(p):
    """Require only the edited '#2' duplicate's gap to have moved; '#1' stays off that value."""
    rows = (p.get("rules") or {}).get("rules") or []
    by_ref = {r.get("ref"): r for r in rows if r.get("name") == "Steel (mm)"}
    r1, r2 = by_ref.get("design:Steel (mm)#1"), by_ref.get("design:Steel (mm)#2")
    return _measured("only the edited duplicate's gap moved", {"r1": r1, "r2": r2},
                     r1 is not None and r2 is not None
                     and _near((r2.get("gap") or {}).get("value_cm"), 0.06, 1e-6)
                     and not _near((r1.get("gap") or {}).get("value_cm"), 0.06, 1e-6))


def _collision_rule_state(p):
    """Return complete design rule settings and the disclosed component census."""
    listing, components = p.get("rules") or {}, p.get("components") or {}
    rows = listing.get("rules")
    fields = ("thickness", "bendRadius", "gap", "reliefWidth", "reliefDepth",
              "reliefRemnant", "twoBendReliefSize", "threeBendReliefRadius")
    if (listing.get("readable") is not True or listing.get("truncated") is not False
            or not isinstance(rows, list) or listing.get("total") != len(rows)
            or any(type(r.get("index")) is not int for r in rows)
            or sorted(r.get("index", -1) for r in rows) != list(range(len(rows)))
            or components.get("walk_complete") is not True or components.get("truncated") is not False
            or not isinstance(components.get("components"), list)
            or components.get("total") != len(components["components"])):
        return None
    for r in rows:
        if (not r.get("name") or not r.get("ref") or r.get("scope") != "design"
                or type(r.get("is_used")) is not bool
                or type(r.get("k_factor")) not in (int, float) or not math.isfinite(r["k_factor"])
                or any(not (r.get(k) or {}).get("expression")
                       or type((r.get(k) or {}).get("value_cm")) not in (int, float)
                       or not math.isfinite(r[k]["value_cm"]) for k in fields)):
            return None
    if any(not r.get("component") or type(r.get("has_flat_pattern")) is not bool
           or not isinstance(r.get("bodies"), list)
           or any(not b.get("name") or type(b.get("is_sheet_metal")) is not bool for b in r["bodies"])
           for r in components["components"]):
        return None
    return {"rules": listing, "components": components}


def _collision_refs(p):
    """Require the two colliding refs to disclose their actual distinct collection indices."""
    state = _collision_rule_state(p)
    rows = state["rules"]["rules"] if state else []
    dups = sorted([r for r in rows if r.get("name") == "Steel (mm)"], key=lambda r: r["index"])
    literal = [r for r in rows if r.get("name") == "Steel (mm)#1"]
    valid = (len(dups) == 2 and len(literal) == 1
             and dups[0]["ref"] == {"scope": "design", "index": dups[0]["index"], "name": "Steel (mm)"}
             and literal[0]["ref"] == {"scope": "design", "index": literal[0]["index"], "name": "Steel (mm)#1"}
             and dups[1]["ref"] == "design:Steel (mm)#2")
    steel_indices = {r["index"] for r in dups}
    components = state["components"]["components"] if state else []
    assigned = [r for r in components
                if r.get("active_rule") == "Steel (mm)"
                and r.get("active_rule_ref_state") == "matched"
                and isinstance(r.get("active_rule_ref"), dict)
                and r["active_rule_ref"].get("scope") == "design"
                and r["active_rule_ref"].get("name") == "Steel (mm)"
                and r["active_rule_ref"].get("index") in steel_indices]
    assigned_indices = {r["active_rule_ref"]["index"] for r in assigned}
    valid = (valid and len(assigned) >= 2 and len(assigned_indices) >= 2
             and len({r["component"] for r in assigned}) == len(assigned))
    _measured("literal/ordinal refs select distinct native rows", rows, valid)
    _RECALL["sm_collision_targets"] = [r["ref"] for r in dups + literal]
    _RECALL["sm_collision_indices"] = [r["index"] for r in dups + literal]
    assignments = [
        {"component": r["component"], "index": r["active_rule_ref"]["index"],
         "ref": r["active_rule_ref"]}
        for r in assigned]
    _RECALL["sm_component_rule_assignments"] = assignments
    _RECALL["sm_component_rule_target"] = assignments[0]
    return True


def _collision_assignment_read_args(_ctx):
    """Build a read-only native assignment census for the colliding components."""
    components = _RECALL.get("sm_component_rule_assignments") or []
    wanted = json.dumps([row["component"] for row in components])
    script = f'''import adsk.core, adsk.fusion, json

def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    wanted = {wanted}
    rules = design.designSheetMetalRules
    result = {{}}
    for component in design.allComponents:
        if component.name in wanted:
            rule = component.activeSheetMetalRule
            result[component.name] = [i for i in range(rules.count) if rules.item(i) == rule]
    print("assignments " + json.dumps(result, sort_keys=True))
'''
    return {"script": script, "read_only": True}


def _collision_assignment_read(p):
    """Require the component refs to match a separate native equality census."""
    line = next((line[len("assignments "):]
                 for line in (p.splitlines() if isinstance(p, str) else [])
                 if line.startswith("assignments ")), None)
    try:
        actual = json.loads(line) if line is not None else None
    except (TypeError, ValueError):
        actual = None
    expected = _RECALL.get("sm_component_rule_assignments") or []
    valid = (isinstance(actual, dict) and len(expected) >= 2
             and all(actual.get(row["component"]) == [row["index"]] for row in expected))
    _measured("component refs equal the independently read native assignments",
              {"expected": expected, "native": actual}, valid)
    return True


_COLLISION_UNKNOWN_PROBE = '''import adsk.core, adsk.fusion, json, sys

def _assignments(design):
    rules = design.designSheetMetalRules
    rows = []
    for component in design.allComponents:
        rule = component.activeSheetMetalRule
        indices = [] if rule is None else [i for i in range(rules.count) if rules.item(i) == rule]
        rows.append([component.name, rule is not None, indices])
    return rows

def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    modules = [m for n, m in sys.modules.items() if n.endswith(".mcpServer.tools.sheet_get")]
    assert len(modules) == 1
    sheet_get = modules[0]
    common = sheet_get._sheet_common
    original = common.scoped_rules
    before = _assignments(design)
    try:
        common.scoped_rules = lambda design, scope: None if scope == "design" else original(design, scope)
        result = sheet_get.handler(include=["components"], max_results=200)
    finally:
        common.scoped_rules = original
    after = _assignments(design)
    payload = json.loads(result["content"][0]["text"])
    rows = payload["components"]["components"]
    print("probe " + json.dumps({"before": before, "after": after, "rows": rows}, sort_keys=True))
'''


def _collision_unknown_probe(p):
    """Require injected census failure to disclose unknown while preserving no-rule state."""
    line = next((line[len("probe "):]
                 for line in (p.splitlines() if isinstance(p, str) else [])
                 if line.startswith("probe ")), None)
    try:
        result = json.loads(line) if line is not None else None
    except (TypeError, ValueError):
        result = None
    before = result.get("before") if isinstance(result, dict) else None
    after = result.get("after") if isinstance(result, dict) else None
    rows = result.get("rows") if isinstance(result, dict) else None
    valid = (isinstance(before, list) and before == after and isinstance(rows, list)
             and len(rows) == len(before) and len(rows) > 0
             and any(source[1] for source in before) and any(not source[1] for source in before)
             and all(row.get("component") == source[0]
                     and row.get("active_rule_ref") is None
                     and row.get("active_rule_ref_state") == ("unknown" if source[1] else "none")
                     for row, source in zip(rows, before)))
    _measured("injected unread rule census distinguishes unknown from no active rule",
              {"native_before": before, "native_after": after, "components": rows}, valid)
    return True


def _collision_component_rule_edit_args(_ctx):
    """Pass the component's disclosed reference to the existing rule editor."""
    target = _RECALL["sm_component_rule_target"]
    return {"action": "update", "rule": target["ref"], "gap": "0.7 mm"}


def _collision_edit_read(target, value_cm, field="thickness"):
    """Require one changed target setting and exact preservation of every sibling rule setting."""
    def check(p):
        now, before = _collision_rule_state(p), _RECALL.get("sm_collision_rules")
        index = _RECALL["sm_collision_indices"][target]
        old_rows = {r["index"]: r for r in before["rules"]["rules"]} if before else {}
        rows = {r["index"]: r for r in now["rules"]["rules"]} if now else {}
        valid = (now is not None and before is not None and rows.keys() == old_rows.keys()
                 and now["components"] == before["components"]
                 and all(rows[i] == old_rows[i] for i in rows if i != index)
                 and _near(rows[index][field]["value_cm"], value_cm, 1e-8)
                 and not _near(old_rows[index][field]["value_cm"], value_cm, 1e-8))
        _measured("one intended rule setting changes; all siblings preserved", {"before": before, "now": now}, valid)
        _RECALL["sm_collision_rules"] = now
        return True
    return check


def _collision_rule_rows():
    """Exercise ambiguous refusal and real edits through every disclosed collision/control ref."""
    reads = {"include": ["rules", "components"], "max_results": 200}
    rows = [("sheet_edit_rule", {"action": "copy", "rule": "design:Steel (mm)#2",
                               "name": "Steel (mm)#1", "thickness": "3 mm"}, "ok", None),
            ("sheet_get", reads, _collision_refs, None),
            ("sheet_get", reads, _retire_compare("sm_collision_rules", _collision_rule_state, False), None),
            ("sys_execute_script", _collision_assignment_read_args, _collision_assignment_read, None),
            ("sys_execute_script", {"script": _COLLISION_UNKNOWN_PROBE, "read_only": True},
             _collision_unknown_probe, None),
            ("sheet_edit_rule", _collision_component_rule_edit_args, "ok", None),
            ("sheet_get", reads, lambda p: _collision_edit_read(
                _RECALL["sm_collision_indices"].index(_RECALL["sm_component_rule_target"]["index"]),
                .07, "gap")(p), None),
            ("sys_execute_script", _collision_assignment_read_args, _collision_assignment_read, None)]
    rows.extend(_retire_reads("sm_collision_refusal", [_PART + ":1"], []))
    for ref in ("design:Steel (mm)#1", "design:Steel (mm)"):
        rows.append(("sheet_edit_rule", {"action": "update", "rule": ref, "thickness": "4 mm"},
                     _refused("sheet_get"), None))
        rows.append(("sheet_get", reads, _retire_compare("sm_collision_rules", _collision_rule_state, True), None))
        rows.extend(_retire_reads("sm_collision_refusal", [_PART + ":1"], [], after=True))
    for target, (thickness, cm) in enumerate((("1.7 mm", .17), ("2.8 mm", .28), ("3.4 mm", .34))):
        rows.append(("sheet_edit_rule", lambda c, target=target, thickness=thickness: {
            "action": "update", "rule": _RECALL["sm_collision_targets"][target], "thickness": thickness}, "ok", None))
        rows.append(("sheet_get", reads, _collision_edit_read(target, cm), None))
        rows.append(("model_inspect", {"target": _PART + ":1", "include": ["default", "mass"],
                                      "per_body": True, "accuracy": "very_high", "units": "mm"},
                     _retire_compare("sm_collision_refusal_" + _PART + ":1", _retire_material_state, True), None))
    return rows + _stale_rule_ref_rows()


_STALE_RULES = ("SM Stale Victim", "SM Stale Target", "SM Stale Tail")


def _delete_rules_script(names):
    """Delete each named unused design rule through the raw API, bypassing every tool."""
    return f'''import adsk.core, adsk.fusion, json

def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    rules = design.designSheetMetalRules
    out = {{}}
    for name in {json.dumps(list(names))}:
        hits = [rules.item(i) for i in range(rules.count) if rules.item(i).name == name]
        out[name] = len(hits) == 1 and not hits[0].isUsed and hits[0].deleteMe()
    print("deleted " + json.dumps(out, sort_keys=True))
'''


def _rules_deleted(names):
    """Require the raw script to report every named rule deleted."""
    def check(p):
        got = _printed("deleted", p)
        return _measured("unused rules deleted by the raw API", got,
                         got == {name: True for name in names})
    return check


def _stale_target_ref(p):
    """Build the Target rule's {scope,index,name} ref; the three fixture rules sit in order, unused."""
    rows = (p.get("rules") or {}).get("rules") or []
    hits = [r for r in rows if r.get("name") in _STALE_RULES]
    order = [r.get("name") for r in sorted(hits, key=lambda r: r.get("index", -1))]
    indices = sorted(r.get("index", -1) for r in hits)
    _measured("stale-ref fixture rules in collection order", hits,
              order == list(_STALE_RULES) and indices == list(range(indices[0], indices[0] + 3))
              and all(r.get("is_used") is False for r in hits))
    target = next(r for r in hits if r["name"] == "SM Stale Target")
    return {"scope": "design", "index": target["index"], "name": target["name"]}


def _stale_rule_ref_rows():
    """A ref read before an earlier rule's delete refuses, naming the rule now at its index."""
    reads = {"include": ["rules", "components"], "max_results": 200}
    rows = [("sheet_edit_rule", {"action": "copy", "rule": "library:Steel (mm)", "name": name}, "ok", None)
            for name in _STALE_RULES]
    rows += [("sheet_get", reads, lambda p: _stale_target_ref(p) is not None,
              ("sm_stale_ref", _recall("sm_stale_ref", _stale_target_ref))),
             ("sys_execute_script", {"script": _delete_rules_script(_STALE_RULES[:1])},
              _rules_deleted(_STALE_RULES[:1]), None),
             ("sheet_get", reads, _retire_compare("sm_stale_rules", _collision_rule_state, False), None),
             ("sheet_edit_rule", lambda c: {"action": "update", "k_factor": 0.31,
                                            "rule": _ctx_get(c, "sm_stale_ref", "Target ref before the delete")},
              _refused("is now 'SM Stale Tail', not 'SM Stale Target'", "the rule list changed",
                       "sheet_get(include=['rules','components'])"), None),
             ("sheet_get", reads, _retire_compare("sm_stale_rules", _collision_rule_state, True), None),
             ("sys_execute_script", {"script": _delete_rules_script(_STALE_RULES[1:])},
              _rules_deleted(_STALE_RULES[1:]), None)]
    return rows


def _seed2_occurrence_deleted(p):
    """Require the tool's own verified-absence verdict for the recalled Second Seed occurrence."""
    expected = _RECALL.get("sm_seed2_occurrence")
    return _measured("Second Seed occurrence delete verdict",
                     {"deleted": p.get("deleted"), "occurrence": p.get("occurrence"), "expected": expected},
                     isinstance(expected, str) and bool(expected)
                     and p.get("deleted") is True and p.get("occurrence") == expected
                     and "timeline_warning" not in p)


def _raw_component_occurrence_deleted(p):
    """Require the tool's own verified-absence verdict for the recalled raw duplicate occurrence."""
    expected = _RECALL.get("sm_raw_occurrence")
    return _measured("raw duplicate occurrence delete verdict",
                     {"deleted": p.get("deleted"), "occurrence": p.get("occurrence"), "expected": expected},
                     isinstance(expected, str) and bool(expected)
                     and p.get("deleted") is True and p.get("occurrence") == expected
                     and "timeline_warning" not in p)


def _cleanup_census(p):
    """Require a complete walk with both empty rule-test components absent and the bodied pair present."""
    census = p.get("components") or {}
    rows = census.get("components") or []
    names = [r.get("component") for r in rows]
    raw_name = _RECALL.get("sm_raw_component")
    seed = [r for r in rows if r.get("component") == _SEED]
    blank = [r for r in rows if r.get("component") == _PART]
    return _measured("post-cleanup component census", {"names": names, "raw_name": raw_name,
                     "walk_complete": census.get("walk_complete"), "truncated": census.get("truncated")},
                     census.get("walk_complete") is True and census.get("truncated") is False
                     and _SEED2 not in names
                     and isinstance(raw_name, str) and bool(raw_name) and raw_name not in names
                     and len(seed) == 1 and bool(seed[0].get("bodies"))
                     and len(blank) == 1 and bool(blank[0].get("bodies")))


def _top_match(p, area):
    """Select the upward broad face by measured area and normal."""
    matches = [m for m in (p.get("matches") or [])
               if m.get("kind") == "planar_face" and (m.get("area") or 0) > area
               and (m.get("normal") or [0, 0, 0])[2] > 0.99]
    return matches[0] if len(matches) == 1 else None


def _top_face(area):
    """Require one broad upward planar face independent of face order."""
    def check(p):
        m = _top_match(p, area)
        return _measured("sheet broad top face", {"top": m, "count": len(p.get("matches") or [])},
                         m is not None and bool(m.get("handle")))
    return check


def _top_handle(area):
    """Extract the verified broad face's handle."""
    return ("sm_top", lambda p: _top_match(p, area)["handle"])


def _line_match(p, x=25, span=(0, 40)):
    """Find one vertical bend line with the requested local endpoints."""
    matches = []
    for row in p.get("entities") or []:
        if row.get("type") != "line":
            continue
        a, b = row.get("start") or {}, row.get("end") or {}
        if (_near(a.get("x"), x, 0.01) and _near(b.get("x"), x, 0.01)
                and sorted([round(a.get("y", -999), 2), round(b.get("y", -999), 2)]) == list(span)):
            matches.append(row)
    return matches[0] if len(matches) == 1 else None


def _bend_line(p, x=25, span=(0, 40)):
    """Require a unique intended line despite auto-projected boundary curves."""
    line = _line_match(p, x, span)
    return _measured("one intended bend line", {"line": line,
                     "line_count": len([e for e in p.get("entities") or []
                                        if e.get("type") == "line"])},
                     line is not None and bool(line.get("id")))


def _converted(p):
    """Require actual sheet state and applied thickness, not requested-rule echo."""
    return _measured("converted sheet body", {"applied": p.get("applied_rule"),
                     "thickness_cm": p.get("applied_rule_thickness_cm")},
                     p.get("converted") is True and bool(p.get("applied_rule_ref"))
                     and "Use applied_rule_ref with sheet_edit_rule" in (p.get("note") or "")
                     and _near(p.get("measured_blank_thickness_cm"), 0.15, 1e-6)
                     and _near(p.get("applied_rule_thickness_cm"), 0.15, 1e-6))


def _sheet_body(p):
    """Read sheet ownership independently of conversion's return payload."""
    rows = (p.get("components") or {}).get("components") or []
    matches = [r for r in rows if r.get("component") == _PART]
    row = matches[0] if len(matches) == 1 else {}
    bodies = row.get("bodies") or []
    return _measured("sheet body census", {"component": row},
                     len(matches) == 1
                     and row.get("active_rule") == (_RECALL.get("sm_applied") or {}).get("applied_rule")
                     and "use a face/edge handle from find_geometry on the body for sheet_convert"
                     in ((p.get("components") or {}).get("note") or "")
                     and len(bodies) == 1 and bodies[0].get("is_sheet_metal") is True)


def _folded(p):
    """Require a landed 90-degree fold and changed body topology."""
    return _measured("folded coupon", {"feature": p.get("feature"),
                     "angle": p.get("angle_deg"), "faces": (p.get("faces_before"), p.get("faces_after"))},
                     p.get("created") is True and bool(p.get("feature"))
                     and _near(p.get("angle_deg"), 90, 1e-5)
                     and isinstance(p.get("faces_before"), int)
                     and isinstance(p.get("faces_after"), int)
                     and p["faces_after"] > p["faces_before"]
                     and "development remains unverified" in p.get("note", ""))


def _formed_extent(p):
    """Require the formed body to leave its former 1.5 mm slab plane."""
    return _measured("formed height", {"z_mm": p.get("z")},
                     isinstance(p.get("z"), (int, float)) and p["z"] > 10)


def _flat(p):
    """Require one nonempty flat associated with the source part."""
    return _measured("flat coupon", {"component": p.get("component"),
                     "source": p.get("folded_body"), "volume": p.get("flat_volume_cm3")},
                     p.get("created") is True and p.get("component") == _PART
                     and p.get("is_solid") is True
                     and _near(p.get("flat_volume_cm3"), 4.8, 0.02))


def _flat_census(p):
    """Read the component's flat presence independently of creation."""
    rows = (p.get("components") or {}).get("components") or []
    matches = [r for r in rows if r.get("component") == _PART]
    return _measured("flat installed", {"matches": matches},
                     len(matches) == 1 and matches[0].get("has_flat_pattern") is True)


def _dxf(p, slotted=False):
    """Inspect the landed flat DXF's closed outline, units and bend entities."""
    path = Path(p.get("file_path") or "")
    lines = path.read_text(encoding="latin-1", errors="ignore").splitlines() if path.is_file() else []
    pairs = [(lines[i].strip(), lines[i + 1].strip()) for i in range(0, len(lines) - 1, 2)]
    unit = next((pairs[i + 1][1] for i, pair in enumerate(pairs[:-1])
                 if pair == ("9", "$INSUNITS")), None)
    entities, current = [], None
    for code, value in pairs:
        if code == "0":
            if current is not None:
                entities.append(current)
            current = {"type": value, "props": []}
        elif current is not None:
            current["props"].append((code, value))
    if current is not None:
        entities.append(current)
    def layer(row):
        return next((value for code, value in row["props"] if code == "8"), None)
    outer = [row for row in entities if row["type"] == "LWPOLYLINE"
             and layer(row) == "OUTER_PROFILES"]
    inner = [row for row in entities if row["type"] == "LWPOLYLINE"
             and layer(row) == "INTERIOR_PROFILES"]
    slot = inner[0]["props"] if len(inner) == 1 else []
    slot_x = [float(v) for c, v in slot if c == "10"]
    slot_y = [float(v) for c, v in slot if c == "20"]
    bulges = [float(v) for c, v in slot if c == "42"]
    slot_ok = (len(inner) == 1 and any(c == "70" and int(v) & 1 for c, v in slot)
               and sorted(slot_x) == [50.0, 50.0, 60.0, 60.0]
               and sorted(slot_y) == [18.0, 18.0, 22.0, 22.0]
               and len(bulges) == 2 and all(_near(abs(v), 1, 1e-6) for v in bulges))
    bends = [row for row in entities if row["type"] == "LINE" and layer(row) == "BEND"]
    extents = [row for row in entities if row["type"] == "LINE"
               and layer(row) == "BEND_EXTENT"]
    poly = outer[0]["props"] if len(outer) == 1 else []
    xs = [float(value) for code, value in poly if code == "10"]
    ys = [float(value) for code, value in poly if code == "20"]
    flags = next((int(value) for code, value in poly if code == "70"), 0)
    return _measured("flat DXF entities", {"bytes": p.get("size_bytes"),
                     "insunits": unit, "outline_vertices": (xs, ys),
                     "closed": bool(flags & 1), "bends": len(bends),
                     "bend_extents": len(extents), "slot_verified": slot_ok},
                     p.get("exported") is True and p.get("size_bytes", 0) > 1000
                     and p.get("development") == "unverified"
                     and "sheet_get(include=['features'])" in p.get("note", "")
                     and unit == "4" and len(outer) == 1 and bool(flags & 1)
                     and len(xs) == len(ys) == 4
                     and _near(max(xs) - min(xs), 80, 0.01)
                     and _near(max(ys) - min(ys), 40, 0.01)
                     and ((not bends and not extents and slot_ok) if slotted
                          else (len(bends) == 1 and len(extents) == 2 and not inner)))


def _refused_dxf_absent(p):
    """Require the refused flat export's path to hold no file while the sheet part still reads."""
    exists = Path(_REFUSED_DXF).exists()
    names = [row.get("component") for row in (p.get("components") or {}).get("components") or []]
    return _measured("refused flat DXF path holds no file",
                     {"file_path": _REFUSED_DXF, "exists": exists, "components": names},
                     not exists and bool(names))


def _unfolded(p):
    """Require the explicit bend faces to unfold with measured face movement before the cut."""
    return _measured("unfolded coupon", {"feature": p.get("feature"),
                     "faces": (p.get("faces_before"), p.get("faces_after"))},
                     p.get("created") is True and p.get("all_bends") is False
                     and (p.get("faces_moved") or 0) > 0)


def _fold_cylinders_check(p):
    """Require both quarter-cylinder bend faces to span the full 40 mm sheet."""
    rows = [m for m in (p.get("matches") or []) if m.get("kind") == "cylinder_face"]
    spans = [(r.get("area") / (math.pi * r["radius"] / 2)
              if isinstance(r.get("area"), (int, float))
              and isinstance(r.get("radius"), (int, float)) and r["radius"] > 0 else None) for r in rows]
    return _measured("interior bend extends across the full sheet", {"count": len(rows), "spans_mm": spans},
                     len(rows) == 2 and all(_near(span, 40, 0.01) for span in spans))


def _fold_cylinder_handles(p):
    return [m["handle"] for m in (p.get("matches") or []) if m.get("kind") == "cylinder_face"]


def _slot_volume(p):
    """Measure removal against the folded pre-cut component volume."""
    before = _RECALL.get("sm_before_slot_volume")
    after = (p.get("mass") or {}).get("volume")
    return _measured("cross-bend slot removed material", {"before_mm3": before,
                     "after_mm3": after},
                     isinstance(before, (int, float)) and isinstance(after, (int, float))
                     and 50 < before - after < 110)


def _refolded(p, source_key="sm_unfold"):
    """Require refold to bind the recalled unfold and move its faces."""
    source = _RECALL.get(source_key)
    return _measured("refolded coupon", {"feature": p.get("feature"),
                     "unfold": p.get("unfold"), "source": source,
                     "faces": (p.get("faces_before"), p.get("faces_after"))},
                     p.get("created") is True and p.get("unfold") == source
                     and (p.get("faces_moved") or 0) > 0)


def _cutting_setup(p):
    """Verify the cutting setup accepted one flat from the folded source."""
    return _measured("flat cutting setup", {"name": p.get("setup_name"),
                     "type": p.get("operation_type"), "flat_sources": p.get("flat_sources")},
                     p.get("created") is True and p.get("setup_name") == _CAM_SETUP
                     and p.get("operation_type") == "cutting"
                     and p.get("flat_models_verified") is True
                     and p.get("model_count") == 1
                     and len(p.get("flat_sources") or []) == 1)


def _cutting_setup_read(p):
    """Read cutting type and selected flat model from the CAM setup census."""
    rows = p.get("setups") or []
    matches = [row for row in rows if row.get("name") == _CAM_SETUP]
    row = matches[0] if len(matches) == 1 else {}
    return _measured("CAM cutting setup readback", {"matches": matches},
                     len(matches) == 1 and row.get("operation_type") == "JetOperation"
                     and bool(_RECALL.get("sm_machine"))
                     and row.get("machine") == _RECALL["sm_machine"]
                     and len(row.get("selected_models") or []) == 1)


def _cutting_fit_frames_flat(p):
    """Verify a cutting fit frames the flat model, not the folded source's own footprint - the
    flat's own 80 mm developed width (_dxf, already verified) is the discriminating span, checked
    beside the camera's own read-back target landing on the fit box's centre."""
    box = p.get("fit_box_cm") or {}
    lo, hi = box.get("min"), box.get("max")
    span = max(hi[0] - lo[0], hi[1] - lo[1]) if lo and hi else None
    center = [(lo[i] + hi[i]) / 2 for i in range(3)] if lo and hi else None
    target = p.get("camera_target_cm")
    on_center = (center is not None and target is not None
                and all(abs(target[i] - center[i]) <= 0.1 for i in range(3)))
    return _measured("cutting fit frames the flat model", {"fitted_to": p.get("fitted_to"),
                     "fit_box_cm": box, "xy_span_cm": span,
                     "camera_target_cm": target, "fit_box_center_cm": center},
                     p.get("fitted_to") == "model" and span is not None and span >= 7.0
                     and on_center)


def _laser_inspected(p):
    """Require the scoped path to be valid and cut material."""
    measured = p.get("measured") or {}
    states = measured.get("states") or {}
    return _measured("nonempty flat laser path", {"passed": p.get("passed"),
                     "measured": measured},
                     p.get("passed") is True and measured.get("empty_toolpath_count") == 0
                     and states.get("valid", 0) >= 1)


def _laser_posted(p, as_is=False, scope="setup"):
    """Verify the shipped laser post wrote a nonempty NC artifact."""
    files = p.get("files") or []
    return _measured("laser post artifact", {"post": p.get("post_config"),
                     "files": files, "posted_operations": p.get("posted_operations")},
                     p.get("posted") is True and p.get("partial") is not True
                     and not p.get("failed_stubs") and not p.get("program_error")
                     and ((p.get("scope") == "as_is" and p.get("mode") == "as_is") if as_is
                          else p.get("scope") == scope and p.get("post_scope") == "fusion")
                     and p.get("posted_operations") == 1
                     and p.get("flat_models_refreshed") == 1
                     and p.get("flat_setups_regenerated") == 1
                     and p.get("flat_operations_ready") == 1
                     and p.get("file_count") == len(files) and len(files) >= 1
                     and all(f.get("size_bytes", 0) > 0 for f in files))



def _laser_feed_value(p, operation=_CAM_OP, setup_name=_CAM_SETUP):
    """Read the single coupon operation's cutting distance in millimeters."""
    rows = (p.get("time") or {}).get("setups") or []
    setup = [r for r in rows if r.get("setup") == setup_name]
    ops = [r for r in (setup[0].get("operations") or []) if r.get("operation") == operation] if len(setup) == 1 else []
    return ops[0].get("feed_distance") if len(ops) == 1 and p["time"].get("units") == "mm" else None


def _unselected_path_untouched(p):
    """Require the selected path to be current while its unfinished sibling stays ungenerated."""
    sibling = _operation_row(p, _CAM_SETUP, _CAM_UNSELECTED) or {}
    return _op_valid(_CAM_SETUP, _CAM_OP)(p) and _measured(
        "unselected operation stays ungenerated", sibling,
        sibling.get("has_toolpath") is False and sibling.get("state") != "valid")


def _laser_feed(p, width_delta=None, operation=_CAM_OP):
    """Require the perimeter to gain twice the blank's width change."""
    feed = _laser_feed_value(p, operation)
    baseline = _RECALL.get("sm_feed_baseline")
    return _measured("source width reaches cutting path", {"feed_mm": feed,
                     "baseline_mm": baseline, "width_change_mm": width_delta},
                     isinstance(feed, (int, float)) and feed > 200
                     and (width_delta is None or isinstance(baseline, (int, float))
                          and _near(feed - baseline, 2 * width_delta, 0.11)))


def _stale_after_widen(p):
    """Verify a synced read catches the widened flat as out-of-date, never falsely ready."""
    rows = (p.get("operations") or {}).get("setups") or []
    row = rows[0] if len(rows) == 1 else {}
    summary = row.get("summary") or {}
    states = summary.get("states") or {}
    return _measured("cutting setup reads stale after a design change", {
                     "states": states, "validity_synced": summary.get("validity_synced"),
                     "readiness": summary.get("readiness")},
                     row.get("setup") == _CAM_SETUP and states.get("out_of_date") == 1
                     and summary.get("validity_synced") is True
                     and "ready to post" not in (summary.get("readiness") or ""))


def _flat_template_path(p):
    """Check the created operation's native state and resized cutting distance."""
    operation = _RECALL["sm_flat_applied"]["operation"]
    return _op_valid(_CAM_SETUP, operation)(p) and _laser_feed(p, 10, operation)


def _flat_template_applied(p):
    """Require one generated flat operation and one identifiable library fork."""
    forked = (p.get("library_tools") or {}).get("forked") or []
    return _measured("flat template generation", p,
                     p.get("applied") is True and p.get("generation_mode") == "generate"
                     and p.get("flat_models_refreshed") == 1 and p.get("created_count") == 1
                     and len(p.get("created_operations") or []) == 1
                     and len(forked) == 1 and isinstance(forked[0].get("index"), int))


def _flat_generation_settled(p, empty=False, target=None):
    """Poll the owned generation within a bound and return its final status."""
    args = ({"handle": _RECALL["sm_empty_generation"]} if empty else
            {"target": target or _RECALL["sm_flat_applied"]["operation"]})
    for attempt in range(18):
        states = p.get("live_states") or {}
        settled = p.get("completed") is True and (empty or states.get("valid") == 1)
        if settled or states.get("errored") or attempt == 17:
            return p
        time.sleep(1.0)
        failed, p = facade("call")("cam_get_status", args)
        if failed or not isinstance(p, dict):
            raise AssertionError(f"Flat generation status unavailable: {p!r}")
    return p


def _flat_template_generated(p):
    """Require the applied operation's settled, nonempty native path."""
    p = _flat_generation_settled(p)
    return _measured("flat template current path", p,
                     p.get("completed") is True and (p.get("live_states") or {}).get("valid") == 1
                     and p.get("empty_toolpaths") == [])


def _mill_generated(p):
    """Require a current nonempty path on the converted flat milling setup."""
    p = _flat_generation_settled(p, target=_MILL_OP)
    return _measured("flat milling generation", p,
                     p.get("completed") is True and (p.get("live_states") or {}).get("valid") == 1
                     and p.get("empty_toolpaths") == [])


def _laser_generated(p):
    """Require the laser perimeter's settled, nonempty native path before the fit reads it."""
    p = _flat_generation_settled(p, target=_CAM_OP)
    return _measured("laser perimeter generation", p,
                     p.get("completed") is True and (p.get("live_states") or {}).get("valid") == 1
                     and p.get("empty_toolpaths") == [])


def _mill_feed(p, width_delta=None):
    """Require source width changes to reach the developed milling contour."""
    feed = _laser_feed_value(p, _MILL_OP, _MILL_SETUP)
    baseline = _RECALL.get("sm_mill_feed_baseline")
    return _measured("flat milling width reaches path", {"feed_mm": feed,
                     "baseline_mm": baseline, "width_change_mm": width_delta},
                     isinstance(feed, (int, float)) and feed > 250
                     and (width_delta is None or isinstance(baseline, (int, float))
                          and _near(feed - baseline, 2 * width_delta, 0.11)))


def _created_empty_path(p):
    """Require the generated unselected contour to stay current and explicitly empty."""
    p = _flat_generation_settled(p, empty=True)
    states = p.get("live_states") or {}
    return _measured("unselected flat operation generation", p,
                     p.get("completed") is True and states.get("out_of_date") == 0
                     and p.get("empty_toolpaths") == [_CAM_UNSELECTED]
                     and (p.get("counts") or {}).get("empty_toolpaths") == 1)


def _width_dimension(p):
    """Require a driving 90 mm blank-width dimension and its parameter name."""
    rows = p.get("results") or []
    row = rows[0] if len(rows) == 1 else {}
    solved = row.get("solved") or []
    return _measured("driving blank width", row, p.get("dimensioned") == 1
                     and row.get("is_driving") is True and bool(row.get("parameter"))
                     and len(solved) == 1 and _near(solved[0].get("length_mm"), 90, 0.01))


def _width_set(width):
    """Set the captured blank-width parameter and verify its measured value."""
    return ("param_set", lambda c: {"name": _ctx_get(c, "sm_width", "blank width parameter"),
                                     "expression": f"{width} mm"},
            lambda p: _measured("blank width changed", p.get("after"),
                                p.get("set") is True and _near((p.get("after") or {}).get("value"), width, 0.01)), None)


def _home_snapshot(p):
    """Return readable active identity/save facts and the complete open-document census."""
    active = p.get("active") or {}
    fields = ("document_handle", "name", "document_id", "has_data_file", "is_saved", "is_modified")
    state = {key: active.get(key) for key in fields}
    rows = p.get("open_documents")
    if (not all(key in active for key in fields)
            or not all(type(state[key]) is bool for key in ("has_data_file", "is_saved", "is_modified"))
            or not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows)):
        return None
    handles = [r.get("document_handle") for r in rows]
    if (p.get("truncated") is not False or type(p.get("open_count")) is not int
            or p["open_count"] != len(rows) or not rows
            or not all(isinstance(h, str) and h.startswith("session:") for h in handles)
            or len(set(handles)) != len(handles)
            or not all(isinstance(r.get("name"), str) and r["name"] for r in rows)):
        return None
    documents = {r["document_handle"]: r["name"] for r in rows}
    cloud_id = state["document_id"]
    if (not isinstance(state["document_handle"], str)
            or documents.get(state["document_handle"]) != state["name"]
            or not isinstance(state["name"], str) or not state["name"]
            or (state["has_data_file"] and not (isinstance(cloud_id, str) and cloud_id))
            or (not state["has_data_file"] and cloud_id is not None)):
        return None
    return {"active": state, "documents": documents}


def _home_session(p):
    """Capture the original story document's exact identity and save state."""
    snapshot = _home_snapshot(p)
    _measured("story session before sheet coupon", p, snapshot is not None)
    _RECALL["sm_home_state"] = snapshot
    return True


def _coupon_session(p):
    """Require a separate active scratch design for the sheet fixture."""
    return _measured("isolated sheet coupon session", p,
                     p.get("created") is True and p.get("is_active") is True
                     and str(p.get("document_handle") or "").startswith("session:")
                     and p.get("document_handle") != _RECALL.get("sm_home"))


def _source_saved(p):
    """Read the coupon's new cloud lineage and its requested scratch destination."""
    return _measured("sheet coupon saved for drawing", p,
                     p.get("saved") is True and p.get("name") == _DRAW_SOURCE
                     and p.get("destination_folder") == FOLDER
                     and str(p.get("document_id") or "").startswith("urn:")
                     and not p.get("name_collision"))


def _source_session(p):
    """Verify the saved coupon remains the active source document."""
    active = p.get("active") or {}
    return _measured("saved coupon source session", active,
                     active.get("document_id") == _RECALL.get("sm_source_urn")
                     and active.get("document_handle") == _RECALL.get("sm_coupon")
                     and active.get("has_data_file") is True)


def _drawing_started(p):
    """Keep the exact accepted drawing job for the bounded status poll."""
    poll = p.get("poll") or {}
    return _measured("coupon drawing job accepted", p,
                     p.get("accepted") is True and p.get("status") == "accepted"
                     and p.get("request_key") == _DRAW_KEY and bool(p.get("job_id"))
                     and poll.get("tool") == "drawing_get_status"
                     and poll.get("request_key") == _DRAW_KEY)


def _drawing_complete(p):
    """Verify the exact deferred drawing job, cloud file, and applied flat options."""
    expected = {"standard": "iso", "units": "mm", "sheet_size": "a3",
                "sheet_types": ["flat_pattern", "folded_model"],
                "flat_isometric": True, "bend_table": True,
                "bend_table_location": "bottom_right",
                "expect_document": _RECALL.get("sm_source_session")}
    payload = _drawing_terminal(p, "sm_draw_job", _DRAW_KEY, "drawing_create", expected)
    applied = (payload or {}).get("flat_settings_applied") or {}
    return _measured("coupon drawing cloud file and flat preferences", {"status": p.get("status"),
                     "job_id": p.get("job_id"), "payload": payload},
                     (payload or {}).get("created") is True
                     and ((payload or {}).get("settings_requested") or {}).get("auto_dimension") == "off"
                     and str((payload or {}).get("file_id") or "").startswith("urn:")
                     and applied.get("isFoldedModelIsometricViewAdded") is True
                     and applied.get("isBendTableIncluded") is True
                     and applied.get("bendTableLocation") == 3)


def _drawing_file(p):
    """Extract the successful deferred drawing's consumable cloud identity."""
    payload = _drawing_terminal_payload(p) or {}
    return [payload["file_id"], payload["drawing_name"]]


def _drawing_sheets(p):
    """Find the coupon's two native sheets and disclose their view types."""
    sheets = p.get("sheets") or []
    names = {_PART, _PART + "_2"}
    coupon = [row for row in sheets if isinstance(row, dict)
              and row.get("name") in names]
    view_types = [[view.get("type") for view in row.get("view_rows") or []]
                  for row in coupon]
    return _measured("coupon flat and folded sheet view rows", {"coupon": coupon,
                     "view_types": view_types, "active_command_id": p.get("active_command_id"),
                     "all_sheet_names": [
                         row.get("name") for row in sheets if isinstance(row, dict)]},
                     bool(p.get("active_command_id"))
                     and p.get("active_command_id") != "FusionDrawingAutoDimensionEditCommand"
                     and len(coupon) == 2 and {row.get("name") for row in coupon} == names
                     and all(isinstance(row.get("view_rows"), list)
                             and row.get("view_rows_truncated") is not True
                             and isinstance(row.get("views"), int) and row["views"] > 0
                             for row in coupon)
                     and any("flat_pattern" in types for types in view_types))


def _drawing_before_screenshot(p):
    """Require readable drawing sheets and an unused path before the no-viewport probe."""
    _drawing_sheets(p)
    exists = Path(_DRAWING_PNG).exists()
    return _measured("drawing reads before screenshot refusal; PNG path starts absent",
                     {"file_path": _DRAWING_PNG, "exists": exists}, not exists)


def _drawing_after_screenshot(p):
    """Require the drawing still reads and the refused screenshot wrote no PNG."""
    _drawing_sheets(p)
    exists = Path(_DRAWING_PNG).exists()
    return _measured("drawing remains readable and screenshot refusal wrote no PNG",
                     {"file_path": _DRAWING_PNG, "exists": exists}, not exists)




def _drawing_layout_saved(p):
    """Require the tidy edit saved in the exact opened drawing session."""
    drawing = _RECALL.get("sm_drawing") or [None, None]
    acted = p.get("acted_on") or {}
    return _measured("accepted tidy-up request saved in its own session", {"save": p,
                     "expected_lineage": drawing[0]},
                     _versioned(drawing[1])(p)
                     and acted.get("document_id") == drawing[0]
                     and acted.get("name") == drawing[1]
                     and not p.get("lineage_changed"))


def _drawing_initial_session_saved(p):
    """Require the guarded drawing session to read clean after saving."""
    drawing = _RECALL.get("sm_drawing") or [None, None]
    active = p.get("active") or {}
    return _measured("tidied drawing clean in exact session", active,
                     active.get("document_handle") == _RECALL.get("sm_drawing_initial_session")
                     and active.get("document_id") == drawing[0]
                     and active.get("name") == drawing[1]
                     and active.get("is_saved") is True
                     and active.get("is_modified") is False)


def _drawing_saved_version(p):
    """Require a fresh completed drawing version newer than the baseline."""
    drawing = _RECALL.get("sm_drawing") or [None, None]
    before = _RECALL.get("sm_drawing_before") or {}
    snap = _version_record(p)
    return _measured("fresh saved drawing version", {"before": before, "after": snap},
                     _version_current(snap)
                     and snap.get("lineage") == drawing[0] == before.get("lineage")
                     and isinstance(before.get("number"), int)
                     and snap["number"] > before["number"])


def _drawing_saved_session(p):
    """Require the reopened saved version to be active and clean before export."""
    drawing = _RECALL.get("sm_drawing") or [None, None]
    saved = _RECALL.get("sm_drawing_saved_version") or {}
    active = p.get("active") or {}
    return _measured("saved drawing active before PDF export", active,
                     active.get("document_handle") == _RECALL.get("sm_drawing_session")
                     and active.get("document_id") == drawing[0]
                     and active.get("version_id") == saved.get("version_id")
                     and active.get("is_saved") is True
                     and active.get("is_modified") is False)


def _pdf_flat_geometry(page, reader):
    """Read a stroked 2:1 flat outline, bend strokes, and the Visible-layer stroke count from one page."""
    from pypdf.generic import ContentStream
    properties = page["/Resources"].get("/Properties", {})
    layer, points, outlines, bend_strokes, visible_strokes = "", [], 0, 0, 0
    for args, op in ContentStream(page.get_contents(), reader).operations:
        if op == b"BDC":
            layer = properties[args[1]].get_object().get("/Name", "")
        elif op == b"EMC":
            layer = ""
        elif op == b"m":
            points = [tuple(float(v) for v in args)]
        elif op == b"l":
            points.append(tuple(float(v) for v in args))
        elif op == b"S":
            bend_strokes += int(layer == "Bend Center" and len(points) >= 2)
            visible_strokes += int(layer == "Visible")
            if layer == "Visible" and len(points) == 5 and points[0] == points[-1]:
                xs, ys = {xy[0] for xy in points}, {xy[1] for xy in points}
                if len(xs) == len(ys) == 2:
                    width, height = max(xs) - min(xs), max(ys) - min(ys)
                    outlines += int(height > 0 and _near(width / height, 2, 0.002))
            points = []
    return {"flat_outlines": outlines, "bend_strokes": bend_strokes, "visible_strokes": visible_strokes}


def _drawing_pdf(p):
    """Read the actual PDF's bend table, require part geometry on every page, retain for inspection."""
    from pypdf import PdfReader
    expected = {"expect_document": _RECALL.get("sm_drawing_session"),
                "file_path": _PDF, "format": "pdf"}
    payload = _drawing_terminal(p, "sm_pdf_job", _PDF_KEY, "drawing_export", expected) or {}
    path = Path(payload.get("file_path") or "")
    reader = PdfReader(path) if path.is_file() else None
    pages = list(reader.pages) if reader else []
    texts = [re.sub(r"\s+", "", page.extract_text()) for page in pages]
    tables = [i for i, t in enumerate(texts) if "BendTableIDDirectionAngleRadius1Up902" in t]
    per_page = [_pdf_flat_geometry(page, reader) for page in pages] if reader else []
    geometry = per_page[tables[0]] if len(tables) == 1 and per_page else {}
    page_visible_strokes = [g.get("visible_strokes", 0) for g in per_page]
    # the sheet names the pre-export drawing_get listed; the generator makes '<component>' and
    # '<component>_2' for every sheet-metal component, so these are the two bodied components'
    # pairs.
    sheet_names = _RECALL.get("sm_sheet_names")
    expected_names = sorted([_SEED, _SEED + "_2", _PART, _PART + "_2"])
    return _measured("PDF bend table; every page carries part geometry; inspect rendered views", {
        "file": str(path), "pages": len(pages), "sheet_names": sheet_names, "bend_tables": len(tables),
        "geometry": geometry, "page_visible_strokes": page_visible_strokes},
        payload.get("exported") is True and sheet_names == expected_names
        and len(pages) == len(sheet_names) and len(tables) == 1
        and geometry.get("flat_outlines") == 1 and geometry.get("bend_strokes", 0) > 0
        and len(page_visible_strokes) == len(pages) and all(c > 0 for c in page_visible_strokes)
        and path.stat().st_size == payload.get("size_bytes")
        and (payload.get("acted_on") or {}).get("document_id") == _RECALL["sm_drawing"][0])


def _closed_one(p):
    """Require a confirmed single-document close with no reported errors."""
    return _measured("owned sheet document closed", p,
                     p.get("closed_count") == 1 and len(p.get("closed") or []) == 1
                     and p.get("close_unconfirmed") == [] and p.get("errors") == []
                     and p.get("save_changes") is False)


def _story_restored(p):
    """Verify the original story identity, save state and document census are restored."""
    snapshot = _home_snapshot(p)
    before = _RECALL.get("sm_home_state")
    handles = snapshot["documents"] if snapshot is not None else {}
    return _measured("story session restored", {"before": before, "after": snapshot, "active": p.get("active")},
                     snapshot is not None and snapshot == before
                     and snapshot["active"]["document_handle"] == _RECALL.get("sm_home")
                     and _RECALL.get("sm_coupon") not in handles
                     and _RECALL.get("sm_drawing_session") not in handles)



def _second_folded(p):
    """Require the second, negative-angle fold to change the part."""
    return _measured("negative second bend", {"angle_deg": p.get("angle_deg"),
                     "faces": (p.get("faces_before"), p.get("faces_after"))},
                     p.get("created") is True and _near(p.get("angle_deg"), -60, 1e-5)
                     and isinstance(p.get("faces_before"), int)
                     and isinstance(p.get("faces_after"), int)
                     and p["faces_after"] > p["faces_before"])


def _bend_cylinders(p):
    """Return complete radius-bearing cylinder-face rows."""
    rows = p.get("matches") or []
    if p.get("match_count") != len(rows):
        return []
    return [r for r in rows if r.get("kind") == "cylinder_face"
            and isinstance(r.get("position"), list)
            and len(r["position"]) == 3 and isinstance(r.get("radius"), (int, float))]


def _two_bends(p):
    """Find both inner and outer cylinder pairs after both bends are folded."""
    rows = _bend_cylinders(p)
    inner = [r for r in rows if _near(r.get("radius"), 2, 0.05)]
    outer = [r for r in rows if _near(r.get("radius"), 3.5, 0.05)]
    return _measured("two physical bends", {"cylinders": rows,
                     "match_count": p.get("match_count")},
                     len(rows) == 4 and len(inner) == len(outer) == 2
                     and len([r for r in inner if 20 < r["position"][0] < 40]) == 1
                     and len([r for r in inner if r["position"][0] > 50]) == 1)


def _selected_bend_handle(p):
    """Return the unique inner face of the second bend."""
    rows = [r for r in _bend_cylinders(p)
            if _near(r.get("radius"), 2, 0.05) and r["position"][0] > 50]
    return rows[0]["handle"] if len(rows) == 1 else None


def _bend_wall_state(p):
    """Return complete finite cylinder-wall geometry without opaque handle text."""
    rows = p.get("matches")
    if (p.get("units") != "mm" or not isinstance(rows, list)
            or p.get("returned") != len(rows) or p.get("match_count") != len(rows)):
        return None
    for r in rows:
        if (r.get("kind") != "cylinder_face" or not r.get("handle") or not r.get("occurrence")
                or any(type(r.get(k)) not in (int, float) or not math.isfinite(r[k]) or r[k] <= 0
                       for k in ("area", "radius"))
                or any(not isinstance(r.get(k), list) or len(r[k]) != 3
                       or any(type(n) not in (int, float) or not math.isfinite(n) for n in r[k])
                       for k in ("position", "normal", "axis"))):
            return None
    return sorted([{k: v for k, v in r.items() if k != "handle"} for r in rows],
                  key=lambda r: (r["radius"], r["position"]))


def _capture_bend_witnesses(p):
    """Recall both independently acquired inner handles and the first bend's unchanged wall pair."""
    walls = _bend_wall_state(p)
    _measured("two-bend wall witness is complete", walls, walls is not None and len(walls) == 4)
    _RECALL["sm_first_bend_walls"] = [r for r in walls if 20 < r["position"][0] < 40]
    _RECALL["sm_array_bends"] = [r["handle"] for r in _bend_cylinders(p) if _near(r["radius"], 2, .05)]
    return _selected_bend_handle(p)


def _first_bend_preserved(p):
    """Require the remaining bend's complete wall geometry to match its prior independent read."""
    walls = _bend_wall_state(p)
    before = _RECALL.get("sm_first_bend_walls")
    return _measured("unselected physical bend preserved", {"before": before, "after": walls},
                     walls is not None and before is not None and len(before) == 2 and walls == before)


def _array_unfold_rows():
    """Reject concatenated handles without effect, then flatten and refold both physical bends."""
    cylinders = {"target": _PART, "kind": "cylinder_face", "max_results": 30, "units": "mm"}
    rows = [("find_geometry", cylinders, _two_bends, ("sm_selected_bend", _capture_bend_witnesses)),
            ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 30},
             _top_face(900), _top_handle(900)),
            ("find_geometry", cylinders, _retire_compare("sm_comma_walls", _bend_wall_state, False), None)]
    rows.extend(_retire_reads("sm_comma_refusal", [_PART + ":1"], []))
    rows.append(("sheet_create_unfold", lambda c: {
        "stationary_face": _ctx_get(c, "sm_top", "top face between bends"),
        "bend_faces": ",".join(_RECALL["sm_array_bends"])}, _refused("JSON array", "comma-joined"), None))
    rows.append(("find_geometry", cylinders, _retire_compare("sm_comma_walls", _bend_wall_state, True), None))
    rows.extend(_retire_reads("sm_comma_refusal", [_PART + ":1"], [], after=True))
    rows.extend([
        ("sheet_create_unfold", lambda c: {
            "stationary_face": _ctx_get(c, "sm_top", "top face between bends"),
            "bend_faces": _RECALL["sm_array_bends"]},
         lambda p: _selected_unfolded(p) and p.get("bend_count_unfolded") == 2,
         ("sm_array_unfold", _recall("sm_array_unfold", lambda p: p["feature"]))),
        ("find_geometry", cylinders, lambda p: _measured("both physical bend wall pairs flattened", p,
            _bend_wall_state(p) == []), None),
        ("sheet_create_refold", lambda c: {"unfold": _ctx_get(c, "sm_array_unfold", "array unfold feature")},
         lambda p: _refolded(p, "sm_array_unfold"), None),
        ("find_geometry", cylinders, _two_bends, None),
    ])
    return rows


def _selected_unfolded(p):
    """Require selected-bend mode and changed geometry."""
    return _measured("selected bend unfolded", {"feature": p.get("feature"),
                     "all_bends": p.get("all_bends"), "faces_moved": p.get("faces_moved")},
                     p.get("created") is True and p.get("all_bends") is False
                     and (p.get("faces_moved") or 0) > 0)


def _one_bend(p):
    """Require only the first bend's two cylinder faces to remain."""
    rows = _bend_cylinders(p)
    inner = [r for r in rows if _near(r.get("radius"), 2, 0.05)]
    outer = [r for r in rows if _near(r.get("radius"), 3.5, 0.05)]
    return _measured("one bend remains after selected unfold", {"cylinders": rows,
                     "match_count": p.get("match_count")},
                     len(rows) == 2 and len(inner) == len(outer) == 1
                     and 20 < inner[0]["position"][0] < 40)


def _selected_refolded(p):
    """Require refold to bind the selected unfold and move geometry."""
    return _measured("selected bend refolded", {"feature": p.get("feature"),
                     "unfold": p.get("unfold"), "faces_moved": p.get("faces_moved")},
                     p.get("created") is True
                     and p.get("unfold") == _RECALL.get("sm_selected_unfold")
                     and (p.get("faces_moved") or 0) > 0)


def _selected_before_rule(p):
    """Read both formed extents before changing the active rule."""
    x, z = p.get("x"), p.get("z")
    return _measured("two-bend extents before rule edit", {"x_mm": x, "z_mm": z},
                     isinstance(x, (int, float)) and isinstance(z, (int, float))
                     and x > 30 and z > 20)


def _used_rule_updated(p):
    """Read K factor from the applied design rule after the write."""
    row = p.get("rule") or {}
    return _measured("in-use rule K-factor update", {"rule": row,
                     "applied": p.get("applied")},
                     p.get("action") == "update"
                     and row.get("ref") == (_RECALL.get("sm_applied") or {}).get("applied_rule_ref")
                     and _near(row.get("k_factor"), 0.5, 1e-9)
                     and "k_factor" in (p.get("applied") or []))


def _applied_rule_read(p, k_factor):
    """Read the exact converted rule reference and its native name from the independent catalog."""
    rules = p.get("rules") or {}
    converted = _RECALL.get("sm_applied") or {}
    ref = converted.get("applied_rule_ref")
    matches = [r for r in rules.get("rules") or [] if r.get("ref") == ref]
    row = matches[0] if len(matches) == 1 else {}
    return _measured("converted rule reference resolves independently", row,
                     bool(ref) and rules.get("readable") is True and rules.get("truncated") is False
                     and len(matches) == 1 and row.get("name") == converted.get("applied_rule")
                     and _near(row.get("k_factor"), k_factor, 1e-9))


def _selected_after_rule(p):
    """Require both formed extents to respond to the in-use rule edit."""
    before = _RECALL.get("sm_selected_extents")
    x, z = p.get("x"), p.get("z")
    dx = abs(x - before[0]) if isinstance(x, (int, float)) and before else None
    dz = abs(z - before[1]) if isinstance(z, (int, float)) and before else None
    return _measured("in-use K factor changed folded extents", {"before_mm": before,
                     "after_mm": (x, z), "change_mm": (dx, dz)},
                     isinstance(dx, (int, float)) and isinstance(dz, (int, float))
                     and 0.05 < dx < 0.5 and 0.05 < dz < 0.5)


def _fold_position_extent(position):
    """Require the formed envelope implied by the bend allowance and chosen line position."""
    allowance = math.pi / 2 * (2 + 0.42 * 1.5)
    start_min_x = 25 - 2 - 1.5
    end_height = 25 + 2 + 1.5
    min_x = start_min_x + (allowance if position == "end" else 0)
    height = end_height - (allowance if position == "start" else 0)

    def check(p):
        minimum, maximum = p.get("min_point") or {}, p.get("max_point") or {}
        start = _RECALL.get("sm_start_envelope") if position == "end" else None
        paired = (position == "start" or
                  (isinstance(start, tuple) and len(start) == 2
                   and isinstance(minimum.get("x"), (int, float))
                   and isinstance(p.get("z"), (int, float))
                   and _near(minimum["x"] - start[0], allowance, 0.01)
                   and _near(p["z"] - start[1], allowance, 0.01)))
        measured = {"x": p.get("x"), "y": p.get("y"), "z": p.get("z"),
                    "min_point": minimum, "max_point": maximum,
                    "bend_allowance_mm": allowance, "start_envelope": start}
        return _measured(f"{position} bend-line formed envelope", measured,
                         paired and _near(minimum.get("x"), min_x, 0.01)
                         and _near(minimum.get("y"), 0, 0.01)
                         and _near(minimum.get("z"), 0, 0.01)
                         and _near(maximum.get("x"), 80, 0.01)
                         and _near(maximum.get("y"), 40, 0.01)
                         and _near(maximum.get("z"), height, 0.01)
                         and _near(p.get("x"), 80 - min_x, 0.01)
                         and _near(p.get("y"), 40, 0.01)
                         and _near(p.get("z"), height, 0.01))
    return check

_SHEET_BUILD = [
    ("doc_get", {"max_results": 1000}, _home_session,
     ("sm_home", _recall("sm_home", lambda p: p["active"]["document_handle"]))),
    ("doc_new", {}, _coupon_session,
     ("sm_coupon", _recall("sm_coupon", lambda p: p["document_handle"]))),
    ("model_create_component", {"name": _SEED, "sheet_metal": True, "activate": True}, _ruled_component, None),
    ("sheet_get", {"include": ["library_rules"]}, "ok", None),
    ("sheet_edit_rule", {"rule": "library:Steel (mm)", "name": _RULE,
                         "thickness": "1.5 mm", "bend_radius": "2 mm",
                         "gap": "0.5 mm", "k_factor": 0.4}, "ok", None),
    ("sheet_edit_rule", {"action": "update", "rule": "design:" + _RULE,
                         "k_factor": 0.42}, "ok", None),
    ("sheet_get", {"include": ["rules"]}, _rule_settings, None),
    ("sketch_create", {"name": _SEED_BASE, "plane": "xy"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _SEED_BASE, "geometry": [
        {"kind": "rectangle", "x1": 100, "y1": 0, "x2": 180, "y2": 40}]}, "ok", None),
    ("model_extrude", {"sketch_name": _SEED_BASE, "profile_index": 0,
                       "distance": 1.5, "operation": "new"}, _extruded, None),
    ("find_geometry", {"target": _SEED, "kind": "planar_face", "max_results": 20},
     _top_face(3000), _top_handle(3000)),
    ("sheet_convert", lambda c: {"body": _SEED, "base_face": _ctx_get(c, "sm_top", "seed top face"),
                                  "rule": "design:" + _RULE}, _refused("would be ignored"), None),
    ("sheet_convert", lambda c: {"body": _SEED, "base_face": _ctx_get(c, "sm_top", "seed top face"),
                                  "rule": "design:Steel (mm)"}, _refused("shared rule"), None),
    ("sheet_get", {"include": ["rules", "components"], "max_results": 200}, _seed_guard, None),
    ("model_create_component", {"name": _PART, "activate": True}, "ok", None),
    ("sketch_create", {"name": _BASE, "plane": "xy"}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _BASE, "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 80, "y2": 40}]}, "ok", None),
    ("model_extrude", {"sketch_name": _BASE, "profile_index": 0,
                       "distance": 1.5, "operation": "new"}, _extruded, None),
    ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 20},
     _top_face(3000), _top_handle(3000)),
    ("sheet_convert", lambda c: {"body": _PART, "base_face": _ctx_get(c, "sm_top", "blank top face"),
                                  "rule": "design:" + _RULE},
     _converted, ("sm_applied", _recall("sm_applied", lambda p: p))),
    ("sheet_get", {"include": ["rules"], "max_results": 200},
     lambda p: _applied_rule_read(p, 0.42), None),
    ("sheet_get", {"include": ["components"], "max_results": 200}, _sheet_body, None),
    ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 20},
     _top_face(3000), _top_handle(3000)),
    ("sketch_create", lambda c: {"name": _BEND, "on_face": _ctx_get(c, "sm_top", "sheet top face")},
     "ok", None),
    ("sketch_add_geometry", {"sketch_name": _BEND, "geometry": [
        {"kind": "line", "x1": 25, "y1": 10, "x2": 25, "y2": 30}]}, "ok", None),
    ("sketch_get", {"sketch_name": _BEND, "include_entities": True},
     lambda p: _bend_line(p, span=(10, 30)),
     ("sm_line", lambda p: _BEND + "/" + _line_match(p, span=(10, 30))["id"])),
    ("sheet_create_fold", lambda c: {"stationary_face": _ctx_get(c, "sm_top", "sheet top face"),
                                      "bend_line": _ctx_get(c, "sm_line", "intended bend line"),
                                      "component": _PART, "angle_deg": 90},
     lambda p: _folded(p) and "beyond its endpoints" in p.get("note", ""), None),
]

_SHEET = _SHEET_BUILD + [
    # SHEET-RULE-DUPLICATE-REF-1: addNewSheetMetalComponent copies a fresh library-default rule only
    # when the design's same-named rule no longer matches the library default (measured) - the step
    # above's 1.2 mm edit is what makes _SEED2's add copy instead of handing 'Steel (mm)' straight back.
    ("sheet_edit_rule", {"action": "update", "rule": "design:Steel (mm)",
                         "thickness": "1.2 mm"}, "ok", None),
    ("sheet_get", {}, "ok",
     ("sm_rule_count_before_adopt", _recall("sm_rule_count_before_adopt",
                                            lambda p: p["design_rule_count"]))),
    ("model_create_component", {"name": _SEED2, "sheet_metal": True}, _rule_adopted_from_copy,
     ("sm_seed2_occurrence", _recall("sm_seed2_occurrence", lambda p: p["occurrence"]))),
    ("sheet_get", {"include": ["rules"], "max_results": 200}, _design_rule_count_after_adopt, None),
    # A duplicate the TOOL never created (direct API, bypassing the adopt path) still has to read
    # and resolve as '#1'/'#2' - sheet_get's rows and sheet_edit_rule's rule kind, not a special case.
    ("sys_execute_script", {"script": _DUP_STEEL_RULE_SCRIPT}, "ok",
     ("sm_raw_occurrence", _save_raw_names)),
    ("sheet_get", {"include": ["rules"], "max_results": 200}, _duplicate_steel_rows, None),
    ("sheet_edit_rule", {"action": "update", "rule": "design:Steel (mm)#2",
                         "gap": "0.6 mm"}, _second_dup_gap_updated, None),
    ("sheet_get", {"include": ["rules"], "max_results": 200}, _dup_gap_isolated, None),
] + _collision_rule_rows() + [
    ("design_delete_occurrence", lambda c: {"occurrence": _ctx_get(
        c, "sm_seed2_occurrence", "Second Seed occurrence name")},
     _seed2_occurrence_deleted, None),
    ("design_delete_occurrence", lambda c: {"occurrence": _ctx_get(
        c, "sm_raw_occurrence", "raw duplicate occurrence name")},
     _raw_component_occurrence_deleted, None),
    ("sheet_get", {"include": ["components"], "max_results": 200}, _cleanup_census, None),
    ("model_inspect", {"target": _PART, "include": ["default", "mass"]}, _formed_extent,
     ("sm_before_slot_volume", _recall("sm_before_slot_volume", lambda p: (p.get("mass") or {})["volume"]))),
    ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 25},
     _top_face(900), _top_handle(900)),
    ("sheet_create_flat_pattern", lambda c: {"stationary_face": _ctx_get(c, "sm_top", "folded stationary face")},
     _flat, None),
    ("sheet_get", {"include": ["components"], "max_results": 200}, _flat_census, None),
    ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 25},
     _top_face(900), _top_handle(900)),
    ("sheet_create_flat_pattern", lambda c: {"stationary_face": _ctx_get(c, "sm_top", "flat source face")},
     _refused("already has a flat pattern"), None),
    ("design_export", {"format": "dxf", "dxf_flat_pattern": _PART, "file_path": _DXF,
                       "dxf_flat_units": "mm", "dxf_bend_lines": True,
                       "dxf_bend_extents": True}, _dxf, None),
    # Sketch-only flags beside a flat export are refused by name, and nothing is written.
    ("sheet_get", {"include": ["components"], "max_results": 200}, _refused_dxf_absent, None),
    ("design_export", {"format": "dxf", "dxf_flat_pattern": _PART, "file_path": _REFUSED_DXF,
                       "dxf_flat_units": "mm", "dxf_bend_lines": False, "dxf_bend_extents": False,
                       "dxf_export_construction": False, "dxf_export_points": False},
     _refused("dxf_flat_pattern takes dxf_flat_units, dxf_bend_lines and dxf_bend_extents only; "
              "drop dxf_export_construction, dxf_export_points."), None),
    ("sheet_get", {"include": ["components"], "max_results": 200}, _refused_dxf_absent, None),
    ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 25},
     _top_face(900), _top_handle(900)),
    ("find_geometry", {"target": _PART, "kind": "cylinder_face", "max_results": 20},
     _fold_cylinders_check, ("sm_fold_cyls", _fold_cylinder_handles)),
    ("sheet_create_unfold", lambda c: {"stationary_face": _ctx_get(c, "sm_top", "folded stationary face"),
                                        "bend_faces": _ctx_get(c, "sm_fold_cyls", "fold cylinder faces")},
     _unfolded, ("sm_unfold", _recall("sm_unfold", lambda p: p["feature"]))),
    ("model_inspect", {"target": _PART},
     lambda p: _measured("unfolded slab height", {"z_mm": p.get("z")},
                         _near(p.get("z"), 1.5, 0.01)), None),
    ("sketch_create", {"plane": "xy", "name": _SLOT}, "ok", None),
    ("sketch_add_geometry", {"sketch_name": _SLOT, "geometry": [
        {"kind": "slot", "x1": 20, "y1": 20, "x2": 30, "y2": 20, "radius": 2}]}, "ok", None),
    ("model_extrude", {"sketch_name": _SLOT, "profile_index": 0,
                       "distance": 2, "operation": "cut"}, _extruded, None),
    ("sheet_create_refold", lambda c: {"unfold": _ctx_get(c, "sm_unfold", "unfold feature")},
     _refolded, None),
    ("model_inspect", {"target": _PART}, _formed_extent, None),
    ("model_inspect", {"target": _PART, "include": ["mass"]}, _slot_volume, None),
    ("sheet_create_refold", lambda c: {"unfold": _ctx_get(c, "sm_unfold", "already refolded feature")},
     _refused("already has refold"), None),
    # all_bends on the CONVERTED, slotted coupon: the wall pairing (inner + outer cylinder on one
    # axis, no bend registry read) sends the split walls and skips the slot end on the leg, whose
    # axis lies in the base plane; the refold lands the slab back where it was.
    ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 25},
     _top_face(900), _top_handle(900)),
    ("sheet_create_unfold", lambda c: {"stationary_face": _ctx_get(c, "sm_top", "folded stationary face"),
                                        "all_bends": True},
     lambda p: _measured("converted coupon unfolds by all_bends",
                         {"bend_count_unfolded": p.get("bend_count_unfolded"), "faces_moved": p.get("faces_moved")},
                         p.get("created") is True and p.get("all_bends") is True
                         and p.get("bend_count_unfolded") == 1 and (p.get("faces_moved") or 0) > 0),
     ("sm_unfold_all", _recall("sm_unfold_all", lambda p: p["feature"]))),
    ("model_inspect", {"target": _PART},
     lambda p: _measured("all_bends slab height", {"z_mm": p.get("z")}, _near(p.get("z"), 1.5, 0.01)), None),
    ("sheet_create_refold", lambda c: {"unfold": _ctx_get(c, "sm_unfold_all", "all_bends unfold feature")},
     lambda p: _refolded(p, "sm_unfold_all"), None),
    ("model_inspect", {"target": _PART}, _formed_extent, None),
    ("design_export", {"format": "dxf", "dxf_flat_pattern": _PART,
                       "file_path": _CUT_DXF, "dxf_flat_units": "mm",
                       "dxf_bend_lines": False, "dxf_bend_extents": False},
     lambda p: _dxf(p, slotted=True), None),
    ("view_switch_workspace", {"workspace": "manufacture"}, "ok", None),
    ("cam_create_setup", {"operation_type": "cutting", "name": _CAM_SETUP,
                          "flat_patterns": [_PART]}, _cutting_setup, None),
    ("cam_edit_setup", {"setup": _CAM_SETUP, "machine": "Avid CNC|EX 3 Axis"},
     lambda p: _measured("cutting machine assignment", p,
                         bool(p.get("machine_set"))),
     ("sm_machine", _recall("sm_machine", lambda p: p["machine_set"]))),
    ("cam_get", {"include": ["setups"], "setup": _CAM_SETUP}, _cutting_setup_read, None),
    ("cam_create_operation", {"setup": _CAM_SETUP, "strategy": "profile2d",
                              "name": _CAM_OP, "tool_library_url": _LASER_LIBRARY,
                              "tool_index": 0, "generate": False}, "ok", None),
    ("cam_select_geometry", {"operation": _CAM_OP, "selection": "silhouette",
                             "loop_type": "all", "generate": False},
     lambda p: _measured("flat silhouette selected", p,
                         p.get("setup_models_selected") is True), None),
    ("cam_generate", {"target": _CAM_SETUP, "skip_valid": False}, "ok", None),
    ("cam_get_status", {"target": _CAM_OP}, _laser_generated, None),
    ("cam_show_toolpath", {"action": "isolate", "operation": _CAM_OP, "fit": True},
     _cutting_fit_frames_flat, None),
]


_FLAT_TREE_STATE = """import adsk.core, adsk.fusion, adsk.cam, json
def run(context):
    doc = adsk.core.Application.get().activeDocument
    design = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
    cam = adsk.cam.CAM.cast(doc.products.itemByProductType('CAMProductType'))
    flats = [o.component.flatPattern.flatBody for o in design.rootComponent.occurrences if o.component.flatPattern]
    def native(body):
        return body.nativeObject or body
    print(json.dumps({'setups': [{'name': s.name, 'model_count': len(s.models),
        'flat_matches': [[native(b) == native(f) for f in flats] for b in s.models]} for s in cam.setups],
        'timeline_count': design.timeline.count, 'marker': design.timeline.markerPosition,
        'flats': [{'component': o.component.name, 'token': o.component.flatPattern.flatBody.entityToken}
                  for o in design.rootComponent.occurrences if o.component.flatPattern]}))
"""


def _flat_tree_rows():
    """Exercise stale manufacturing-tree refusal and recovery in an owned base-flange document."""
    setup = {"operation_type": "cutting", "name": "FlatTreeCut", "flat_patterns": ["FlatTreeProbe"]}
    native = {"script": _FLAT_TREE_STATE, "read_only": True}
    rows = [
        ("doc_get", {"max_results": 1000}, lambda p: _home_snapshot(p) is not None,
         ("flat_tree_home", _recall("flat_tree_home", _home_snapshot))),
        ("doc_new", {}, lambda p: p.get("created") is True and p.get("is_active") is True
         and bool(p.get("document_handle")) and p["document_handle"] != _RECALL["flat_tree_home"]["active"]["document_handle"],
         ("flat_tree_doc", _recall("flat_tree_doc", lambda p: p["document_handle"]))),
        ("view_switch_workspace", {"workspace": "manufacture"}, "ok", None),
        ("model_create_component", {"name": "FlatTreeProbe", "sheet_metal": True, "activate": True}, "ok", None),
        ("sketch_create", {"name": "FlatTreeBase", "plane": "xy"}, "ok", None),
        ("sketch_add_geometry", {"sketch_name": "FlatTreeBase", "geometry": [
            {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 60, "y2": 40}]}, "ok", None),
        ("sheet_create_flange", {"kind": "base", "profile": {"sketch": "FlatTreeBase", "profile_index": 0},
         "component": "FlatTreeProbe"}, "ok", None),
        ("find_geometry", {"target": "FlatTreeProbe", "kind": "planar_face", "max_results": 20},
         _top_face(2000), ("flat_tree_top", lambda p: _top_match(p, 2000)["handle"])),
        ("sheet_create_flat_pattern", lambda c: {"stationary_face": _ctx_get(c, "flat_tree_top", "base top")}, "ok", None),
        ("sys_execute_script", native, lambda p: p.get("setups") == [] and len(p.get("flats", [])) == 1
         and p["flats"][0].get("component") == "FlatTreeProbe" and bool(p["flats"][0].get("token")),
         ("flat_tree_before", _recall("flat_tree_before", lambda p: p))),
        ("cam_create_setup", setup, _refused("Used entity could not be matched in manufacturing tree",
         "Design and back to Manufacture", "view_switch_workspace"), None),
        ("sys_execute_script", native, lambda p: _measured("flat tree refusal preserves native state", p,
         p == _RECALL["flat_tree_before"]), None),
        ("view_switch_workspace", {"workspace": "design"}, "ok", None),
        ("view_switch_workspace", {"workspace": "manufacture"}, "ok", None),
        ("cam_create_setup", setup, lambda p: p.get("created") is True and p.get("operation_type") == "cutting"
         and p.get("model_count") == 1 and p.get("flat_models_verified") is True, None),
        ("sys_execute_script", native, lambda p: _measured("recovered setup uses native flat body", p,
         len(p.get("flats", [])) == 1 and p["flats"][0].get("component") == "FlatTreeProbe"
         and p.get("setups") == [{"name": "FlatTreeCut", "model_count": 1, "flat_matches": [[True]]}]), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "flat_tree_doc", "flat tree scratch"), "save_changes": False}, _closed_one, None),
        ("doc_activate", lambda c: {"name": _RECALL["flat_tree_home"]["active"]["document_handle"]}, "ok", None),
        ("doc_get", {"max_results": 1000}, lambda p: _measured("flat tree scratch closed and home restored", p,
         _home_snapshot(p) == _RECALL["flat_tree_home"]), None),
    ]
    return rows


_SHEET = _flat_tree_rows() + _SHEET


_SHEET_SELECTED = _SHEET_BUILD + [
    ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 30},
     _top_face(900), _top_handle(900)),
    ("sketch_create", lambda c: {"name": _BEND2,
                                  "on_face": _ctx_get(c, "sm_top", "first-fold stationary face")},
     "ok", None),
    ("sketch_add_geometry", {"sketch_name": _BEND2, "geometry": [
        {"kind": "line", "x1": 55, "y1": 0, "x2": 55, "y2": 40}]}, "ok", None),
    ("sketch_get", {"sketch_name": _BEND2, "include_entities": True},
     lambda p: _bend_line(p, 55),
     ("sm_line2", lambda p: _BEND2 + "/" + _line_match(p, 55)["id"])),
    ("sheet_create_fold", lambda c: {
        "stationary_face": _ctx_get(c, "sm_top", "first-fold stationary face"),
        "bend_line": _ctx_get(c, "sm_line2", "second bend line"),
        "component": _PART, "angle_deg": -60}, _second_folded, None),
    ("find_geometry", {"target": _PART, "kind": "cylinder_face", "max_results": 30},
     _two_bends, ("sm_selected_bend", _capture_bend_witnesses)),
    ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 30},
     _top_face(900), _top_handle(900)),
    ("sheet_create_unfold", lambda c: {
        "stationary_face": _ctx_get(c, "sm_top", "top face between bends"),
        "bend_faces": [_ctx_get(c, "sm_selected_bend", "second bend inner face")]},
     _selected_unfolded,
     ("sm_selected_unfold", _recall("sm_selected_unfold", lambda p: p["feature"]))),
    ("find_geometry", {"target": _PART, "kind": "cylinder_face", "max_results": 30},
     _one_bend, None),
    ("find_geometry", {"target": _PART, "kind": "cylinder_face", "max_results": 30},
     _first_bend_preserved, None),
    ("sheet_create_refold", lambda c: {
        "unfold": _ctx_get(c, "sm_selected_unfold", "selected unfold feature")},
     _selected_refolded, None),
    ("find_geometry", {"target": _PART, "kind": "cylinder_face", "max_results": 30},
     _two_bends, None),
] + _array_unfold_rows() + [
    ("find_geometry", {"target": _PART, "kind": "planar_face", "max_results": 30},
     _top_face(900), _top_handle(900)),
    ("sheet_create_flat_pattern", lambda c: {
        "stationary_face": _ctx_get(c, "sm_top", "refolded stationary face")},
     _flat, None),
    ("model_inspect", {"target": _PART, "include": ["default", "mass"]},
     _selected_before_rule,
     ("sm_selected_extents", _recall("sm_selected_extents", lambda p: (p["x"], p["z"])))),
    ("sheet_edit_rule", lambda c: {
        "action": "update", "rule": _ctx_get(c, "sm_applied", "conversion")["applied_rule_ref"],
        "k_factor": 0.5}, _used_rule_updated, None),
    ("sheet_get", {"include": ["rules"], "max_results": 200},
     lambda p: _applied_rule_read(p, 0.5), None),
    ("model_inspect", {"target": _PART, "include": ["default", "mass"]},
     _selected_after_rule, None),
    ("sheet_get", {"include": ["components"], "max_results": 200},
     _flat_census, None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "sm_coupon", "selected coupon session"),
                             "save_changes": False}, _closed_one, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "sm_home", "original story session")},
     "ok", None),
    _dwell(4.0),
    ("doc_get", {"max_results": 1000}, _story_restored, None),
]



def _serial_sheet_geometry(p, folded=False):
    """Return complete sheet geometry, excluding planar parameter frames only for folded restoration."""
    rows = _edge_extent_geometry(p)
    if rows is None:
        return None
    return [{k: v for k, v in row.items() if not (folded and row['kind'] == 'planar_face' and k == 'frame')}
            for row in rows]


def _serial_sheet_poses(p):
    """Return the two finite identity placements independently of changing folded body bounds."""
    rows = p.get('occurrences')
    if (p.get('units') != 'mm' or p.get('occurrences_truncated') is not False
            or p.get('occurrence_count') != 2 or not isinstance(rows, list) or len(rows) != 2
            or {r.get('name') for r in rows} != {'SerialA:1', 'SerialB:1'}):
        return None
    fields = ('name', 'component', 'origin', 'x_axis', 'y_axis', 'z_axis', 'grounded', 'ground_to_parent', 'body_count')
    for r in rows:
        if (r.get('body_count') != 1 or r.get('origin') != [0, 0, 0]
                or [r.get(k) for k in ('x_axis', 'y_axis', 'z_axis')] != [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
                or any(type(r.get(k)) is not bool for k in ('grounded', 'ground_to_parent'))
                or any(not isinstance(r.get(k), list) or len(r[k]) != 3
                       or any(type(v) not in (int, float) or not math.isfinite(v) for v in r[k])
                       for k in ('x_axis', 'y_axis', 'z_axis'))):
            return None
    return sorted([{k: r[k] for k in fields} for r in rows], key=lambda r: r['name'])


def _serial_witness_material(p):
    """Require the independent root 20 mm cube's complete physical properties and world bounds."""
    shape = _sweep_mode_shape(p)
    if (p.get('units') != 'mm' or p.get('lump_count') != 1
            or shape['min'] != {'x': 220, 'y': 0, 'z': 0} or shape['max'] != {'x': 240, 'y': 20, 'z': 20}
            or not _near(shape['volume'], 8000, .001) or not _near(shape['area'], 2400, .001)):
        return None
    return {'shape': shape, 'mass': p.get('mass')}


def _serial_sheet_history(owner, kind):
    """Require one healthy feature with the prior rows and every other owner retained."""
    def check(p):
        state = _retire_design_state(p)
        old = _RECALL.get('serial_stage_design')
        rows = (state or {}).get('timeline', {}).get('timeline') or []
        prior = (old or {}).get('timeline', {}).get('timeline') or []
        valid = (state is not None and old is not None and rows[:-1] == prior
                 and len(rows) == len(prior) + 1 and rows[-1].get('type') == kind
                 and rows[-1].get('component') == owner
                 and rows[-1].get('health', 'healthy') == 'healthy'
                 and (state['timeline'].get('summary') or {}).get('states') == {'healthy': len(rows)}
                 and (state['timeline'].get('summary') or {}).get('exceptions') == [])
        if valid:
            _RECALL['serial_stage_design'] = state
        return _measured('serial sheet adds one healthy owned feature', rows, valid)
    return check


def _sheet_serial_rows():
    """Refuse an overlapping unfold and recover a collapsed unfold group through typed calls."""
    rows = [('doc_get', {'max_results': 1000}, lambda p: _retire_compare('serial_home', _home_snapshot, False)(p),
             ('serial_home_handle', _home_address)),
            ('design_get', {'include': ['tree', 'timeline'], 'tree_bodies': True, 'tree_handles': True, 'max_results': 2000},
             _retire_compare('serial_home_design', _retire_design_state, False), None),
            ('doc_new', lambda c: {'expect_document': _ctx_get(c, 'serial_home_handle', 'home')},
             lambda p: p.get('created') is True and p.get('is_active') is True,
             ('serial_doc', lambda p: p['document_handle'])),
            ('design_activate_component', {'occurrence': 'root'}, 'ok', None)]
    def write(tool, args, check='ok', save=None):
        rows.append((tool, lambda c: {**(args(c) if callable(args) else args),
                     'expect_document': _ctx_get(c, 'serial_doc', 'owned serial scene')}, check, save))
    write('sketch_create', {'name': 'SerialWitness', 'plane': 'xy'})
    write('sketch_add_geometry', {'sketch_name': 'SerialWitness', 'units': 'mm', 'geometry': [
        {'kind': 'rectangle', 'x1': 220, 'y1': 0, 'x2': 240, 'y2': 20}]})
    write('model_extrude', {'sketch_name': 'SerialWitness', 'distance': 20, 'operation': 'new', 'units': 'mm'},
          _extruded)
    def witness_handle(p):
        bodies = (p.get('tree') or {}).get('root_bodies') or []
        _measured('one independently acquired root witness body', bodies,
                  _retire_design_state(p) is not None and len(bodies) == 1 and bool(bodies[0].get('handle'))
                  and bodies[0].get('is_solid') is True and bodies[0].get('visible') is True)
        return bodies[0]['handle']
    rows.append(('design_get', lambda c: {'include': ['tree', 'timeline'], 'tree_bodies': True, 'tree_handles': True, 'max_results': 2000},
                 lambda p: _retire_design_state(p) is not None, ('serial_witness', witness_handle)))
    for owner, x in (('SerialA', 0), ('SerialB', 100)):
        write('design_activate_component', {'occurrence': 'root'})
        write('model_create_component', {'name': owner, 'sheet_metal': True, 'activate': True},
              lambda p, owner=owner: p.get('component') == owner and p.get('sheet_metal') is True and p.get('activated') is True)
        write('sketch_create', {'name': owner + 'Base', 'plane': 'xy'})
        write('sketch_add_geometry', {'sketch_name': owner + 'Base', 'units': 'mm', 'geometry': [
            {'kind': 'rectangle', 'x1': x, 'y1': 0, 'x2': x + 80, 'y2': 40}]})
        write('sheet_create_flange', {'kind': 'base', 'profile': {'sketch': owner + 'Base', 'profile_index': 0}, 'component': owner},
              lambda p: p.get('created') is True and p.get('kind') == 'base' and _near(p.get('thickness_mm'), 2.5, .001))
        def rim(p, x=x):
            matches = [r for r in p.get('matches') or [] if r.get('kind') == 'line_edge'
                       and all(_near(a, b, .001) for a, b in zip(r.get('position') or [], (x + 80, 20, 2.5)))
                       and len(r.get('position') or []) == 3 and _near(r.get('length'), 40, .001)]
            _measured('one base-flange rim edge', matches, len(matches) == 1 and bool(matches[0].get('handle')))
            return matches[0]['handle']
        rows.append(('find_geometry', {'target': owner + ':1', 'kind': 'line_edge', 'units': 'mm', 'max_results': 100},
                     lambda p: _edge_extent_geometry(p) is not None, ('serial_rim', rim)))
        write('sheet_create_flange', lambda c: {'kind': 'edge', 'edges': [_ctx_get(c, 'serial_rim', 'rim edge')], 'distance': 10, 'units': 'mm'},
              lambda p: p.get('created') is True and p.get('bend_faces_after') == p.get('bend_faces_before', -2) + 2)
    write('design_activate_component', {'occurrence': 'root'})
    write('view_set', {'action': 'orient', 'orientation': 'iso-top-right', 'focus': ['SerialA:1', 'SerialB:1'], 'fit': True})
    def geometry(owner, key, after=False, folded=False):
        rows.append(('find_geometry', lambda c: {'target': _ctx_get(c, 'serial_witness', 'witness') if owner == 'Witness' else owner + ':1',
                     'units': 'mm', 'max_results': 200},
                     _retire_compare(key, lambda p: _serial_sheet_geometry(p, folded), after), None))
    def controls(owner, other):
        geometry(other, 'serial_held_' + other, False)
        geometry('Witness', 'serial_witness_geometry', False)
        rows.append(('model_inspect', {'target': other + ':1', 'include': ['default', 'mass'], 'per_body': True, 'units': 'mm', 'accuracy': 'very_high'},
                     _retire_compare('serial_held_material', _retire_material_state, False), None))
        rows.append(('model_inspect', lambda c: {'target': _ctx_get(c, 'serial_witness', 'witness'), 'include': ['default', 'mass'],
                     'units': 'mm', 'accuracy': 'very_high'}, _retire_compare('serial_witness_material', _serial_witness_material, False), None))
    def held(other):
        geometry(other, 'serial_held_' + other, True)
        geometry('Witness', 'serial_witness_geometry', True)
        rows.append(('model_inspect', {'target': other + ':1', 'include': ['default', 'mass'], 'per_body': True, 'units': 'mm', 'accuracy': 'very_high'},
                     _retire_compare('serial_held_material', _retire_material_state, True), None))
        rows.append(('model_inspect', lambda c: {'target': _ctx_get(c, 'serial_witness', 'witness'), 'include': ['default', 'mass'],
                     'units': 'mm', 'accuracy': 'very_high'}, _retire_compare('serial_witness_material', _serial_witness_material, True), None))
        rows.append(('assembly_get', {'include': ['poses'], 'units': 'mm', 'max_occurrences': 100},
                     _retire_compare('serial_poses', _serial_sheet_poses, True), None))
    rows.append(('assembly_get', {'include': ['poses'], 'units': 'mm', 'max_occurrences': 100},
                 _retire_compare('serial_poses', _serial_sheet_poses, False), None))
    for owner, other in (('SerialA', 'SerialB'), ('SerialB', 'SerialA')):
        controls(owner, other)
        geometry(owner, 'serial_folded_' + owner, False, True)
        rows.append(('model_inspect', {'target': owner + ':1', 'include': ['default', 'mass'], 'per_body': True, 'units': 'mm', 'accuracy': 'very_high'},
                     _retire_compare('serial_folded_material', _retire_material_state, False), None))
        rows.extend(_retire_reads('serial_stage', [], []))
        rows.append(('find_geometry', {'target': owner + ':1', 'kind': 'planar_face', 'units': 'mm', 'max_results': 100},
                     _top_face(3000), ('serial_stationary', lambda p: _top_match(p, 3000)['handle'])))
        write('sheet_create_unfold', lambda c: {'stationary_face': _ctx_get(c, 'serial_stationary', 'broad stationary face'), 'all_bends': True},
              lambda p: p.get('created') is True and p.get('all_bends') is True and (p.get('faces_moved') or 0) > 0,
              ('serial_unfold', _recall('serial_unfold', lambda p: p['feature'])))
        rows.append(('design_get', {'include': ['tree', 'timeline'], 'tree_bodies': True, 'tree_handles': True, 'max_results': 2000},
                     _serial_sheet_history(owner, 'UnfoldFeature'), None))
        rows.append(('model_inspect', {'target': owner + ':1', 'include': ['default', 'mass'], 'units': 'mm', 'accuracy': 'very_high'},
                     lambda p, owner=owner: _near(p.get('z'), 2.5, .001) and _near(p.get('x'), 90.654866776, .001)
                     and _near((p.get('mass') or {}).get('volume'), 9065.486677646199, .001), None))
        held(other)
        if owner == 'SerialA':
            rows.extend(_retire_reads('serial_pending', ['', 'SerialA:1', 'SerialB:1'], []))
            for target in ('SerialA', 'SerialB'):
                geometry(target, 'serial_pending_' + target)
            rows.append(('find_geometry', {'target': 'SerialB:1', 'kind': 'planar_face', 'units': 'mm', 'max_results': 100},
                         _top_face(3000), ('serial_other_face', lambda p: _top_match(p, 3000)['handle'])))
            write('sheet_create_unfold', lambda c: {'stationary_face': _ctx_get(c, 'serial_other_face', 'other sheet face'), 'all_bends': True},
                  _refused('Serial unfold policy', 'SerialA/', 'sheet_create_refold'))
            rows.extend(_retire_reads('serial_pending', ['', 'SerialA:1', 'SerialB:1'], [], after=True))
            for target in ('SerialA', 'SerialB'):
                geometry(target, 'serial_pending_' + target, True)
            def group_state(collapsed):
                write('design_edit_timeline', {'action': 'group_state', 'feature': 'Group1', 'collapsed': collapsed},
                      lambda p, collapsed=collapsed: p.get('group') == 'Group1' and p.get('is_collapsed') is collapsed
                      and p.get('member_count') == 1 and p.get('group_canonical_identity_verified') is None)
                rows.append(('design_get', {'include': ['timeline'], 'group': 'Group1', 'max_results': 100},
                             lambda p: (p.get('timeline') or {}).get('returned') == 1
                             and all(r.get('component') == 'SerialA' and r.get('type') == 'UnfoldFeature'
                                     and r.get('parent_group') == 'Group1' for r in p['timeline']['timeline']), None))
                rows.append(('design_get', {'include': ['tree', 'timeline'], 'tree_bodies': True, 'tree_handles': True, 'max_results': 2000},
                             lambda p, collapsed=collapsed: _retire_design_state(p) is not None
                             and (p['timeline'].get('groups') or {}).get('Group1') == 1
                             and (p['timeline'].get('summary') or {}).get('exceptions') == []
                             and len([r for r in p['timeline']['timeline'] if r.get('name') == 'Group1'
                                      and r.get('is_group') is True and r.get('is_collapsed') is True
                                      and r.get('member_count') == 1]) == int(collapsed), None))
                held('SerialB')
                geometry('SerialA', 'serial_pending_SerialA', True)
            group_state(True)
            rows.extend(_retire_reads('serial_collapsed', ['', 'SerialA:1', 'SerialB:1'], []))
            write('sheet_create_refold', lambda c: {'unfold': 'SerialA/' + _ctx_get(c, 'serial_unfold', 'pending unfold')},
                  _refused("action='group_state'", 'collapsed=false', 'qualified reference'))
            rows.extend(_retire_reads('serial_collapsed', ['', 'SerialA:1', 'SerialB:1'], [], after=True))
            group_state(False)
            rows.extend(_retire_reads('serial_pending', ['', 'SerialA:1', 'SerialB:1'], [], after=True))
        write('sheet_create_refold', lambda c, owner=owner: {'unfold': owner + '/' + _ctx_get(c, 'serial_unfold', 'pending unfold')},
              lambda p: p.get('created') is True and p.get('unfold') == _RECALL.get('serial_unfold')
              and (p.get('faces_moved') or 0) > 0)
        rows.append(('design_get', {'include': ['tree', 'timeline'], 'tree_bodies': True, 'tree_handles': True, 'max_results': 2000},
                     _serial_sheet_history(owner, 'RefoldFeature'), None))
        geometry(owner, 'serial_folded_' + owner, True, True)
        rows.append(('model_inspect', {'target': owner + ':1', 'include': ['default', 'mass'], 'per_body': True, 'units': 'mm', 'accuracy': 'very_high'},
                     _retire_compare('serial_folded_material', _retire_material_state, True), None))
        held(other)
    # Both groups collapsed: the bare 'Unfold1' names each qualified candidate and its group.
    for group in ('Group1', 'Group2'):
        write('design_edit_timeline', {'action': 'group_state', 'feature': group, 'collapsed': True},
              lambda p, group=group: p.get('group') == group and p.get('is_collapsed') is True
              and p.get('member_count') == 2)
    rows.extend(_retire_reads('serial_two_groups', ['', 'SerialA:1', 'SerialB:1'], []))
    write('design_edit_timeline', {'action': 'suppress', 'feature': 'Unfold1'},
          _refused("'Unfold1' names 2 hidden unfold-group features in collapsed groups",
                   "for 'SerialA/Unfold1' run design_edit_timeline(action='group_state', "
                   "feature='Group1', collapsed=false)",
                   "for 'SerialB/Unfold1' run design_edit_timeline(action='group_state', "
                   "feature='Group2', collapsed=false)",
                   "Keep the unfold group intact."))
    # The refold of a collapsed refolded group gets the same expand advice, and the group refuses
    # an ungroup; once expanded, the unfold still reads its refold natively.
    write('design_edit_timeline', {'action': 'suppress', 'feature': 'SerialA/Refold1'},
          _refused("'SerialA/Refold1' is inside collapsed group 'Group1'. Run design_edit_timeline("
                   "action='group_state', feature='Group1', collapsed=false)",
                   "qualified reference 'SerialA/Refold1'. Keep the unfold group intact."))
    write('design_edit_timeline', {'action': 'ungroup', 'feature': 'Group1'},
          _refused("'Group1' is an unfold group; ungrouping it loses its unfold/refold association. "
                   "Expand it with design_edit_timeline(action='group_state', feature='Group1', "
                   "collapsed=false) instead."))
    rows.extend(_retire_reads('serial_two_groups', ['', 'SerialA:1', 'SerialB:1'], [], after=True))
    for group in ('Group1', 'Group2'):
        write('design_edit_timeline', {'action': 'group_state', 'feature': group, 'collapsed': False},
              lambda p, group=group: p.get('group') == group and p.get('is_collapsed') is False
              and p.get('member_count') == 2)
    write('sheet_create_refold', {'unfold': 'SerialA/Unfold1'},
          _refused("unfold='SerialA/Unfold1' already has refold 'Refold1'", 'no duplicate was created'))

    write('doc_close', lambda c: {'name': _ctx_get(c, 'serial_doc', 'owned serial scene'), 'save_changes': False}, _closed_one)
    rows += [('doc_activate', lambda c: {'name': _ctx_get(c, 'serial_home_handle', 'home')}, 'ok', None),
             ('doc_get', {'max_results': 1000}, _retire_compare('serial_home', _home_snapshot, True), None),
             ('design_get', {'include': ['tree', 'timeline'], 'tree_bodies': True, 'tree_handles': True, 'max_results': 2000},
              _retire_compare('serial_home_design', _retire_design_state, True), None)]
    return rows


_SHEET_SELECTED += _sheet_serial_rows()


def _lost_pair_history(p):
    """Require LostA's Unfold1 and Refold1 both standing healthy in a complete timeline read."""
    state = _retire_design_state(p)
    rows = (state or {}).get('timeline', {}).get('timeline') or []
    pair = sorted((r.get('type'), r.get('name')) for r in rows if r.get('component') == 'LostA'
                  and r.get('type') in ('UnfoldFeature', 'RefoldFeature'))
    valid = (state is not None and pair == [('RefoldFeature', 'Refold1'), ('UnfoldFeature', 'Unfold1')]
             and all(r.get('health', 'healthy') == 'healthy' for r in rows))
    if valid:
        _RECALL['lost_pair_design'] = state
    return _measured('the unfold and its refold both stand in the timeline', pair, valid)


def _lost_pair_gone(p):
    """Require LostA's rows to be the pair's read minus Unfold1 and Refold1, every row healthy."""
    def owned(state):
        return [(r.get('type'), r.get('name')) for r in (state or {}).get('timeline', {}).get('timeline') or []
                if r.get('component') == 'LostA' and r.get('is_group') is not True]
    state = _retire_design_state(p)
    rows = (state or {}).get('timeline', {}).get('timeline') or []
    expected = [t for t in owned(_RECALL.get('lost_pair_design'))
                if t not in (('UnfoldFeature', 'Unfold1'), ('RefoldFeature', 'Refold1'))]
    now = owned(state)
    valid = (state is not None and bool(expected) and now == expected
             and all(r.get('health', 'healthy') == 'healthy' for r in rows))
    return _measured('only the orphan refold and unfold left the timeline', now, valid)


_RAW_UNGROUP_SCRIPT = '''import adsk.core, adsk.fusion, json

def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    groups = design.timeline.timelineGroups
    hits = [groups.item(i) for i in range(groups.count) if groups.item(i).name == "Group1"]
    deleted = len(hits) == 1 and hits[0].deleteMe(False)
    print("ungrouped " + json.dumps({"deleted": deleted, "groups": groups.count}))
'''


def _sheet_lost_association_rows():
    """Lose an unfold/refold association; the unfold preflight names it, and its remedy lets an unfold land."""
    rows = [('doc_get', {'max_results': 1000}, lambda p: _retire_compare('lost_home', _home_snapshot, False)(p),
             ('lost_home_handle', _home_address)),
            ('doc_new', lambda c: {'expect_document': _ctx_get(c, 'lost_home_handle', 'home')},
             lambda p: p.get('created') is True and p.get('is_active') is True,
             ('lost_doc', lambda p: p['document_handle'])),
            ('design_activate_component', {'occurrence': 'root'}, 'ok', None)]
    def write(tool, args, check='ok', save=None):
        rows.append((tool, lambda c: {**(args(c) if callable(args) else args),
                     'expect_document': _ctx_get(c, 'lost_doc', 'owned lost-association scene')}, check, save))
    write('model_create_component', {'name': 'LostA', 'sheet_metal': True, 'activate': True},
          lambda p: p.get('component') == 'LostA' and p.get('sheet_metal') is True)
    write('sketch_create', {'name': 'LostABase', 'plane': 'xy'})
    write('sketch_add_geometry', {'sketch_name': 'LostABase', 'units': 'mm', 'geometry': [
        {'kind': 'rectangle', 'x1': 0, 'y1': 0, 'x2': 80, 'y2': 40}]})
    write('sheet_create_flange', {'kind': 'base', 'profile': {'sketch': 'LostABase', 'profile_index': 0},
                                  'component': 'LostA'},
          lambda p: p.get('created') is True and p.get('kind') == 'base')
    def rim(p):
        matches = [r for r in p.get('matches') or [] if r.get('kind') == 'line_edge'
                   and len(r.get('position') or []) == 3
                   and all(_near(a, b, .001) for a, b in zip(r['position'], (80, 20, 2.5)))
                   and _near(r.get('length'), 40, .001)]
        _measured('one base-flange rim edge', matches, len(matches) == 1 and bool(matches[0].get('handle')))
        return matches[0]['handle']
    rows.append(('find_geometry', {'target': 'LostA:1', 'kind': 'line_edge', 'units': 'mm', 'max_results': 100},
                 lambda p: _edge_extent_geometry(p) is not None, ('lost_rim', rim)))
    write('sheet_create_flange', lambda c: {'kind': 'edge', 'edges': [_ctx_get(c, 'lost_rim', 'rim edge')],
                                            'distance': 10, 'units': 'mm'},
          lambda p: p.get('created') is True)
    write('design_activate_component', {'occurrence': 'root'})
    def stationary(key):
        rows.append(('find_geometry', {'target': 'LostA:1', 'kind': 'planar_face', 'units': 'mm', 'max_results': 100},
                     _top_face(3000), (key, lambda p: _top_match(p, 3000)['handle'])))
    def folded(after):
        rows.append(('find_geometry', {'target': 'LostA:1', 'units': 'mm', 'max_results': 200},
                     _retire_compare('lost_folded', lambda p: _serial_sheet_geometry(p, True), after), None))
        rows.append(('model_inspect', {'target': 'LostA:1', 'include': ['default', 'mass'], 'per_body': True,
                                       'units': 'mm', 'accuracy': 'very_high'},
                     _retire_compare('lost_folded_material', _retire_material_state, after), None))
    folded(False)
    stationary('lost_stationary')
    write('sheet_create_unfold', lambda c: {'stationary_face': _ctx_get(c, 'lost_stationary', 'top face'),
                                            'all_bends': True},
          lambda p: p.get('created') is True and p.get('feature') == 'Unfold1')
    # The measured sequence that loses both associations: collapse the unfold's group, remove the
    # group, then refold. The tool refuses that ungroup, so the raw API removes the group; the refold
    # then lands and its own association check reports the loss.
    write('design_edit_timeline', {'action': 'group_state', 'feature': 'Group1', 'collapsed': True},
          lambda p: p.get('group') == 'Group1' and p.get('is_collapsed') is True)
    write('design_edit_timeline', {'action': 'ungroup', 'feature': 'Group1'},
          _refused("'Group1' is an unfold group; ungrouping it loses its unfold/refold association."))
    write('sys_execute_script', {'script': _RAW_UNGROUP_SCRIPT},
          lambda p: _measured('raw API removed the unfold group', _printed('ungrouped', p),
                              _printed('ungrouped', p) == {'deleted': True, 'groups': 0}))
    write('sheet_create_refold', {'unfold': 'LostA/Unfold1'},
          _refused("Refold 'Refold1' remains", 'unfold association'))
    rows.append(('design_get', {'include': ['tree', 'timeline'], 'tree_bodies': True, 'tree_handles': True,
                                'max_results': 2000}, _lost_pair_history, None))
    stationary('lost_stationary_refolded')
    write('sheet_create_unfold', lambda c: {'stationary_face': _ctx_get(c, 'lost_stationary_refolded', 'top face'),
                                            'all_bends': True},
          _refused("'LostA/Refold1' exists but reads no unfoldFeature",
                   'reading no refoldFeature: LostA/Unfold1', 'association is lost',
                   "design_delete_feature(feature='LostA/Refold1'), then the same on each unfold listed",
                   'Nothing unfolded'))
    rows.append(('design_get', {'include': ['tree', 'timeline'], 'tree_bodies': True, 'tree_handles': True,
                                'max_results': 2000},
                 lambda p: _measured('the refused unfold left the history as it was',
                                     None, _retire_design_state(p) == _RECALL.get('lost_pair_design')), None))
    # The remedy the refusal names: delete the orphan refold, then the unfold listed; the next
    # unfold then lands.
    for feature in ('LostA/Refold1', 'LostA/Unfold1'):
        write('design_delete_feature', {'feature': feature},
              lambda p: p.get('deleted') is True and p.get('also_deleted') == [])
    rows.append(('design_get', {'include': ['tree', 'timeline'], 'tree_bodies': True, 'tree_handles': True,
                                'max_results': 2000}, _lost_pair_gone, None))
    folded(True)
    stationary('lost_stationary_cleared')
    write('sheet_create_unfold', lambda c: {'stationary_face': _ctx_get(c, 'lost_stationary_cleared', 'top face'),
                                            'all_bends': True},
          lambda p: p.get('created') is True and p.get('all_bends') is True and (p.get('faces_moved') or 0) > 0)
    write('doc_close', lambda c: {'name': _ctx_get(c, 'lost_doc', 'owned lost-association scene'),
                                  'save_changes': False}, _closed_one)
    rows += [('doc_activate', lambda c: {'name': _ctx_get(c, 'lost_home_handle', 'home')}, 'ok', None),
             ('doc_get', {'max_results': 1000}, _retire_compare('lost_home', _home_snapshot, True), None)]
    return rows


_SHEET_SELECTED += _sheet_lost_association_rows()


def _position_variant(position):
    """Build, fold, inspect, and close one position-specific scratch coupon."""
    return _SHEET_BUILD[:-1] + [
        ("sheet_create_fold", lambda c: {
            "stationary_face": _ctx_get(c, "sm_top", "sheet top face"),
            "bend_line": _ctx_get(c, "sm_line", "intended bend line"),
            "component": _PART, "angle_deg": 90, "position": position}, _folded, None),
        ("model_inspect", {"target": _PART, "include": ["default"]},
         _fold_position_extent(position),
         (("sm_start_envelope", _recall("sm_start_envelope", lambda p: (
             p["min_point"]["x"], p["z"]))) if position == "start" else None)),
        ("doc_close", lambda c: {"name": _ctx_get(c, "sm_coupon", "position coupon session"),
                                 "save_changes": False}, _closed_one, None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, "sm_home", "original story session")},
         "ok", None),
        _dwell(4.0),
        ("doc_get", {"max_results": 1000}, _story_restored, None),
    ]


_SHEET_POSITIONS = _position_variant("start") + _position_variant("end")


def _z_library(p):
    """Acquire the actual unique library rule reference for both owned coupons."""
    listing = p.get("library_rules") or {}
    rows = listing.get("rules") or []
    hits = [r for r in rows if r.get("name") == "Steel (mm)"]
    _measured("Z coupon rule library", listing,
              listing.get("readable") is True and listing.get("truncated") is False
              and listing.get("total") == len(rows) and len(hits) == 1 and bool(hits[0].get("ref")))
    _RECALL["z_library"] = hits[0]["ref"]
    return True


def _z_matches(p):
    """Require every disclosed geometric match and its consumable handle."""
    rows = p.get("matches")
    _measured("complete Z geometry acquisition", p,
              isinstance(rows, list) and p.get("returned") == p.get("match_count") == len(rows)
              and all(r.get("handle") for r in rows))
    return rows


def _z_corner_edges(radius):
    """Select both vertical corner edges by measured position, length and direction."""
    def check(p):
        rows = _z_matches(p)
        corners = [(1, 1), (0, 29)] if radius == 1 else [(0, 0), (1, 30)]
        selected = []
        for x, y in corners:
            hits = [r for r in rows if r.get("kind") == "line_edge"
                    and len(r.get("position", [])) == len(r.get("direction", [])) == 3
                    and _near(r["position"][0], x, .001) and _near(r["position"][1], y, .001)
                    and _near(r.get("length"), 20, .001) and _near(abs(r["direction"][2]), 1, .001)]
            _measured("Z vertical fillet corner", hits, len(hits) == 1)
            selected.append(hits[0]["handle"])
        _RECALL["z_edges"] = selected
        return True
    return check


def _z_radii(radius):
    """Check independently acquired quarter-cylinder geometry after each corner fillet."""
    def check(p):
        rows = _z_matches(p)
        expected = [1, 1] if radius == 1 else [1, 1, 2, 2]
        return _measured("Z bend radii and areas", rows,
                         sorted(r.get("radius", -1) for r in rows) == expected
                         and all(len(r.get("axis", [])) == 3 and _near(abs(r["axis"][2]), 1, .001)
                                 and _near(r.get("area"), math.pi * r["radius"] * 10, .002)
                                 for r in rows))
    return check


def _z_stationary(p):
    """Acquire the intended broad y=0 flange by its independent geometry."""
    rows = _z_matches(p)
    hits = [r for r in rows if r.get("kind") == "planar_face"
            and len(r.get("position", [])) == len(r.get("normal", [])) == 3
            and 1 < r["position"][0] < 30 and _near(r["position"][1], 0, .001)
            and _near(r["position"][2], 10, .001) and (r.get("area") or 0) > 300
            and _near(r["normal"][1], -1, .001)]
    _measured("Z stationary flange", hits, len(hits) == 1)
    _RECALL["z_stationary"] = hits[0]["handle"]
    return True


def _z_applied(owner):
    """Consume the returned rule reference and independently read the converted body flag."""
    def check(p):
        rules = (p.get("rules") or {}).get("rules") or []
        comps = (p.get("components") or {}).get("components") or []
        applied = _RECALL.get("z_applied") or {}
        hits = [r for r in rules if r.get("ref") == applied.get("applied_rule_ref")]
        bodies = [c.get("bodies") for c in comps if c.get("component") == owner]
        return _measured("Z applied conversion rule", {"rule": hits, "bodies": bodies},
                         len(hits) == len(bodies) == 1 and len(bodies[0]) == 1
                         and bodies[0][0].get("is_sheet_metal") is True
                         and hits[0].get("name") == applied.get("applied_rule")
                         and _near((hits[0].get("thickness") or {}).get("value_cm"), .1, 1e-6))
    return check


def _z_flat_geometry(p, limit=32):
    """Distinguish the measured native Z shape and developed slab without declaring readiness."""
    listing = p.get("features") or {}
    rows = listing.get("components") or []
    _measured("complete flat owner census", listing,
              listing.get("walk_complete") is True and listing.get("truncated") is False
              and listing.get("total") == len(rows) == 4)
    for owner, count, low, high, area in (
            ("FlatSharp", 10, [-2.9, 0, -3], [3, 2, 0], 6),
            ("FlatRounded", 6, [0, 0, -.1], [8.6398229715, 2, 0], 17.279645943)):
        hits = [r.get("flat_pattern") for r in rows if r.get("component") == owner]
        _measured("unique flat owner", hits, len(hits) == 1)
        flat, geometry = hits[0], hits[0].get("geometry") or {}
        faces, box = geometry.get("faces") or [], geometry.get("bounds_cm") or {}
        # Each normal carries its label, and a face says when the two disagree in sign - judged here
        # off the two vectors the same row publishes.
        planes = [f for f in faces if isinstance(f.get("plane"), dict)]
        valid = (flat.get("present") is True and flat.get("healthy") is True
                 and "evaluator's outward normal" in (geometry.get("normals") or "")
                 and "supporting surface's parametric normal" in geometry["normals"]
                 and all(("note" in f["plane"]) is (sum(a * b for a, b in zip(
                     f.get("normal_at_sample") or [], [(f["plane"].get("normal") or {}).get(k, 0)
                                                       for k in "xyz"])) < 0) for f in planes)
                 and geometry.get("development") == "unverified"
                 and geometry.get("frame") == "flatBody native coordinates; not folded-body world coordinates"
                 and geometry.get("face_count") == count and geometry.get("returned") == len(faces) == min(count, limit)
                 and geometry.get("limit") == limit and geometry.get("truncated") is (count > limit)
                 and geometry.get("partial") is False and geometry.get("unread_face_indices") == []
                 and all(_near((box.get(side) or {}).get(axis), value, 1e-5)
                         for side, values in (("min", low), ("max", high)) for axis, value in zip("xyz", values))
                 and all(f.get("type") == "adsk::core::Plane" and f.get("unread") == []
                         and isinstance(f.get("sample_point_cm"), dict)
                         and len(f.get("normal_at_sample", [])) == 3 for f in faces))
        if limit >= count:
            broad = sorted((f for f in faces if _near(f.get("area_cm2"), area, 1e-5)),
                           key=lambda f: f["plane"]["origin_cm"]["z"])
            # Outward normals: the lower broad face reads z=-1 and the upper z=+1; a narrow face of
            # each coupon reads opposite its plane.normal, so at least one face carries the note.
            valid = (valid and len(broad) == 2
                     and all(_near(f["normal_at_sample"][2], sign, 1e-6) for f, sign in zip(broad, (-1, 1)))
                     and [round(f["plane"]["origin_cm"]["z"], 6) for f in broad] == [low[2], high[2]]
                     and any("note" in f["plane"] for f in planes))
        _measured("independent native flat bounds and broad-plane separation: " + owner, geometry, valid)
    return True


def _z_flat_rows():
    """Create sharp and radius-corrected Z coupons, inspect their native flats, and close them."""
    rows = [("doc_get", {"max_results": 1000}, _home_session,
             ("sm_home", _recall("sm_home", lambda p: p["active"]["document_handle"]))),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "sm_home", "home")}, _coupon_session,
             ("sm_coupon", _recall("sm_coupon", lambda p: p["document_handle"])))]
    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: {**(args(c) if callable(args) else args),
                     "expect_document": _ctx_get(c, "sm_coupon", "Z coupon")}, check, save))
    write("model_create_component", {"name": "FlatRuleSeed", "sheet_metal": True})
    rows.append(("sheet_get", {"include": ["library_rules"], "max_results": 200}, _z_library, None))
    polygon = [(30, 0), (30, 1), (1, 1), (1, 30), (-29, 30), (-29, 29), (0, 29), (0, 0)]
    for owner in ("FlatSharp", "FlatRounded"):
        write("design_activate_component", {"occurrence": "root"})
        write("model_create_component", {"name": owner, "activate": True})
        write("sketch_create", {"name": owner + "Z", "plane": "xy"})
        write("sketch_add_geometry", {"sketch_name": owner + "Z", "component": owner, "geometry": [
            {"kind": "line", "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1]}
            for a, b in zip(polygon, polygon[1:] + polygon[:1])]})
        write("model_extrude", {"sketch_name": owner + "Z", "component": owner,
                                 "distance": 20, "operation": "new"}, _extruded)
        rows.append(("model_inspect", {"target": owner + ":1", "include": ["default", "mass"],
                     "per_body": True, "units": "mm", "accuracy": "very_high"},
                     lambda p: _measured("initial sharp Z volume", p.get("mass"),
                          _retire_material_state(p) is not None and _near(p["mass"]["volume"], 1760, .001)), None))
    rows.append(("model_inspect", {"target": "FlatSharp:1", "include": ["default", "mass"], "per_body": True, "accuracy": "very_high"},
                 _retire_compare("z_sharp_control", _retire_material_state, False), None))
    for radius in (1, 2):
        rows.append(("find_geometry", {"target": "FlatRounded:1", "kind": "line_edge", "max_results": 100},
                     _z_corner_edges(radius), None))
        write("model_fillet", lambda c, radius=radius: {"edges": _RECALL["z_edges"], "radius": radius,
                                                        "tangent_chain": False})
        rows.extend([("find_geometry", {"target": "FlatRounded:1", "kind": "cylinder_face", "max_results": 100},
                      _z_radii(radius), None),
                     ("model_inspect", {"target": "FlatSharp:1", "include": ["default", "mass"], "per_body": True, "accuracy": "very_high"},
                      _retire_compare("z_sharp_control", _retire_material_state, True), None)])
    for owner in ("FlatSharp", "FlatRounded"):
        write("sheet_edit_rule", lambda c, owner=owner: {"action": "copy", "rule": _RECALL["z_library"],
              "name": owner + "Rule", "thickness": "1 mm", "bend_radius": "1 mm", "k_factor": .4},
              "ok", ("z_rule", _recall("z_rule", lambda p: p["rule"]["ref"])))
        read_shape = ("model_inspect", {"target": owner + ":1", "include": ["default", "mass"], "per_body": True, "accuracy": "very_high"})
        rows.append((*read_shape, _retire_compare("z_folded_" + owner, _retire_material_state, False), None))
        rows.append(("find_geometry", {"target": owner + ":1", "kind": "planar_face", "max_results": 100}, _z_stationary, None))
        write("sheet_convert", lambda c, owner=owner: {"body": owner, "base_face": _RECALL["z_stationary"],
              "rule": _RECALL["z_rule"]}, lambda p: p.get("converted") is True,
              ("z_applied", _recall("z_applied", lambda p: p)))
        rows.append(("sheet_get", {"include": ["rules", "components"], "max_results": 200},
                     _z_applied(owner), None))
        rows.append(("find_geometry", {"target": owner + ":1", "kind": "planar_face", "max_results": 100}, _z_stationary, None))
        write("sheet_create_flat_pattern", lambda c: {"stationary_face": _RECALL["z_stationary"]},
              lambda p: _measured("native creation leaves development unverified", p,
                   p.get("created") is True and p.get("development") == "unverified"
                   and "sheet_get(include=['features'])" in p.get("note", "")))
        rows.append((*read_shape, _retire_compare("z_folded_" + owner, _retire_material_state, True), None))
    sketches = [(owner, owner + "Z") for owner in ("FlatSharp", "FlatRounded")]
    targets = ["FlatSharp:1", "FlatRounded:1"]
    rows.extend(_retire_reads("z_flat_read", targets, sketches))
    rows.extend([("sheet_get", {"include": ["features"], "max_results": 4}, lambda p: _z_flat_geometry(p, 4), None),
                 ("sheet_get", {"include": ["features"], "max_results": 200}, _z_flat_geometry, None)])
    write("sheet_create_flat_pattern", lambda c: {"stationary_face": _RECALL["z_stationary"]},
          _refused("already has a flat pattern", "unverified", "sheet_get"))
    rows.extend(_retire_reads("z_flat_read", targets, sketches, after=True))
    write("doc_activate", lambda c: {"name": _ctx_get(c, "sm_home", "home")})
    rows.extend([("doc_close", lambda c: {"name": _ctx_get(c, "sm_coupon", "Z coupon"), "save_changes": False,
                 "expect_document": _ctx_get(c, "sm_home", "home")}, _closed_one, None),
                 ("doc_get", {"max_results": 1000}, _story_restored, None)])
    return rows


_SHEET_POSITIONS += _z_flat_rows()


_HEM_CHANNEL_SCRIPT = '''import adsk.core, adsk.fusion, json

def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    root = design.rootComponent
    P, V = adsk.core.Point3D.create, adsk.core.ValueInput.createByString
    occ = root.occurrences.addNewSheetMetalComponent(adsk.core.Matrix3D.create())
    occ.activate()
    comp = occ.component
    comp.name = "HemProbe"
    rule = comp.activeSheetMetalRule
    rule.thickness.expression, rule.bendRadius.expression, rule.gap.expression = "1 mm", "1 mm", "0.5 mm"
    rule.kFactor = 0.42
    sk = comp.sketches.add(root.xYConstructionPlane)
    sk.sketchCurves.sketchLines.addTwoPointRectangle(P(0, 0, 0), P(6, 4, 0))
    ff = comp.features.flangeFeatures
    ff.add(ff.createBaseFlangeInput([sk.profiles.item(0)]))
    body = comp.bRepBodies.item(0)
    top = body.boundingBox.maxPoint.z
    line = adsk.core.Curve3DTypes.Line3DCurveType
    rims = [e for e in body.edges if e.geometry.curveType == line and abs(e.length - 6.0) < 1e-6
            and abs(e.startVertex.geometry.z - top) < 1e-6 and abs(e.endVertex.geometry.z - top) < 1e-6]
    ff.add(ff.createEdgeFlangeInput(rims, V("20 mm")))
    body = comp.bRepBodies.item(0)
    plane, cyl = adsk.core.SurfaceTypes.PlaneSurfaceType, adsk.core.SurfaceTypes.CylinderSurfaceType
    stationary = [f for f in body.faces if f.geometry.surfaceType == plane
                  and abs(f.pointOnFace.z - top) < 1e-7 and f.area > 20]
    unfold_in = comp.features.unfoldFeatures.createInput(stationary[0])
    unfold_in.bendFaces = [f for f in body.faces if f.geometry.surfaceType == cyl]
    unfold = comp.features.unfoldFeatures.add(unfold_in)
    comp.features.refoldFeatures.add(comp.features.refoldFeatures.createInput(unfold))
    design.activateRootComponent()
    body = comp.bRepBodies.item(0)
    print("built " + json.dumps({"rims": len(rims), "stationary": len(stationary),
                                 "faces": body.faces.count, "volume_cm3": round(body.volume, 6)}))
'''

_HEM_SNAPSHOT_SCRIPT = '''import adsk.core, adsk.fusion, json

def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    tl = design.timeline
    comp = [c for c in design.allComponents if c.name == "HemProbe"][0]
    body = comp.bRepBodies.item(0)
    lo, hi = body.boundingBox.minPoint, body.boundingBox.maxPoint
    print("snapshot " + json.dumps({
        "timeline": [[tl.item(i).name, tl.item(i).healthState] for i in range(tl.count)],
        "marker": tl.markerPosition, "hems": comp.features.hemFeatures.count,
        "faces": body.faces.count, "volume_cm3": round(body.volume, 6),
        "box_cm": [round(v, 5) for v in (lo.x, lo.y, lo.z, hi.x, hi.y, hi.z)]}))
'''


def _printed(tag, p):
    """The JSON object a raw script printed after '<tag> ', or None."""
    line = next((ln[len(tag) + 1:] for ln in (p.splitlines() if isinstance(p, str) else [])
                 if ln.startswith(tag + " ")), None)
    try:
        return json.loads(line) if line is not None else None
    except (TypeError, ValueError):
        return None


def _hem_snapshot(p):
    """Return the channel's native timeline, hem count and body facts when they read complete."""
    snap = _printed("snapshot", p)
    return snap if isinstance(snap, dict) and snap.get("hems") == 0 and snap.get("faces") == 22 else None


def _hem_rope_failure_rows():
    """A rope hem the channel cannot take quotes Fusion's whole failure text, and nothing lands."""
    rows = [("doc_get", {"max_results": 1000}, _home_session,
             ("sm_home", _recall("sm_home", lambda p: p["active"]["document_handle"]))),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "sm_home", "home")}, _coupon_session,
             ("sm_coupon", _recall("sm_coupon", lambda p: p["document_handle"])))]
    def write(name, args, check="ok", save=None):
        rows.append((name, lambda c, args=args: {**(args(c) if callable(args) else args),
                     "expect_document": _ctx_get(c, "sm_coupon", "hem channel")}, check, save))
    write("sys_execute_script", {"script": _HEM_CHANNEL_SCRIPT},
          lambda p: _measured("rope-hem channel built", _printed("built", p), _printed("built", p) == {
              "rims": 2, "stationary": 1, "faces": 22, "volume_cm3": 4.842743}))
    def rim(p):
        rows_ = p.get("matches") or []
        _measured("one 60 mm rope rim at (30, -2, 20) mm", rows_, len(rows_) == 1
                  and all(_near(a, b, .001) for a, b in zip(rows_[0].get("position") or [], (30, -2, 20)))
                  and len(rows_[0].get("position") or []) == 3 and _near(rows_[0].get("length"), 60, .001))
        return rows_[0]["handle"]
    rows.append(("find_geometry", {"target": "HemProbe:1", "kind": "line_edge", "nearest_to": [30, -2, 20],
                                   "max_results": 1, "units": "mm"}, lambda p: rim(p) is not None, ("hem_rim", rim)))
    snapshot = {"script": _HEM_SNAPSHOT_SCRIPT, "read_only": True}
    rows.append(("sys_execute_script", snapshot, _retire_compare("hem_rope_snapshot", _hem_snapshot, False), None))
    write("sheet_create_hem", lambda c: {"kind": "rope", "edge": _ctx_get(c, "hem_rim", "rope rim"),
                                         "length": 6, "gap": .5, "radius": 1.5, "units": "mm"},
          _refused("Hem failed:", "Compute Failed // SM_HEM_ROPE_INVALID_INPUTS - Can't generate the Hem. "
                   "The input values create improper geometry. Adjust the length, gap, or radius.",
                   "No hem was added."))
    rows.append(("sys_execute_script", snapshot, _retire_compare("hem_rope_snapshot", _hem_snapshot, True), None))
    write("doc_activate", lambda c: {"name": _ctx_get(c, "sm_home", "home")})
    rows.extend([("doc_close", lambda c: {"name": _ctx_get(c, "sm_coupon", "hem channel"), "save_changes": False,
                 "expect_document": _ctx_get(c, "sm_home", "home")}, _closed_one, None),
                 ("doc_get", {"max_results": 1000}, _story_restored, None)])
    return rows


_SHEET_POSITIONS += _hem_rope_failure_rows()

_SHEET_CAM_READ = [
    ("cam_inspect_toolpaths", {"scope": _CAM_SETUP}, _laser_inspected, None),
    ("cam_post", {"scope": _CAM_SETUP, "post": "grbl laser", "post_scope": "fusion",
                  "output_folder": EXPORT_DIR + "/nc", "program_name": "SM1001"},
     _laser_posted, None),
    ("cam_get", {"setup": _CAM_SETUP, "include": ["time"]}, lambda p: _laser_feed(p),
     ("sm_feed_baseline", _recall("sm_feed_baseline", _laser_feed_value))),
    ("sketch_dimension", {"sketch_name": _BASE, "dimensions": [{
        "dim_type": "horizontal_distance", "entity_one": "line:0:start",
        "entity_two": "line:0:end", "value": "90 mm"}]}, _width_dimension,
     ("sm_width", _recall("sm_width", lambda p: p["results"][0]["parameter"]))),
    ("cam_generate", {"target": _CAM_OP}, "ok", None),
]

_SHEET_CAM_REFRESH = [
    ("cam_get", {"setup": _CAM_SETUP, "include": ["time"]}, lambda p: _laser_feed(p, 10), None),
    _width_set(80),
    ("design_export", {"format": "dxf", "dxf_flat_pattern": _PART,
                       "file_path": _CUT_DXF, "dxf_flat_units": "mm",
                       "dxf_bend_lines": False, "dxf_bend_extents": False},
     lambda p: _dxf(p, slotted=True), None),
    ("cam_post", {"program_name": "SM1001"}, lambda p: _laser_posted(p, as_is=True), None),
    ("cam_get", {"setup": _CAM_SETUP, "include": ["time"]}, lambda p: _laser_feed(p, 0), None),
    _width_set(90),
    ("cam_get", {"setup": _CAM_SETUP, "include": ["operations"]}, _stale_after_widen, None),
    ("cam_post", {"scope": _CAM_SETUP, "post": "grbl laser", "post_scope": "fusion",
                  "output_folder": EXPORT_DIR + "/nc", "program_name": "SM1001"},
     _laser_posted, None),
    ("cam_get", {"setup": _CAM_SETUP, "include": ["time"]}, lambda p: _laser_feed(p, 10), None),
    _width_set(85),
    ("cam_select_geometry", {"operation": _CAM_OP, "selection": "silhouette",
                             "loop_type": "all", "generate": True}, "ok", None),
]

_SHEET_CAM_RESTORE = [
    ("cam_get", {"setup": _CAM_SETUP, "include": ["time"]}, lambda p: _laser_feed(p, 5), None),
    _width_set(80),
    ("cam_post", {"program_name": "SM1001"}, lambda p: _laser_posted(p, as_is=True), None),
    ("cam_get", {"setup": _CAM_SETUP, "include": ["time"]}, lambda p: _laser_feed(p, 0), None),
    ("cam_create_operation", {"setup": _CAM_SETUP, "strategy": "profile2d",
                              "name": _CAM_UNSELECTED, "tool_library_url": _LASER_LIBRARY,
                              "tool_index": 0, "generate": False}, "ok", None),
    ("cam_post", {"scope": _CAM_OP, "post": "grbl laser", "post_scope": "fusion",
                  "output_folder": EXPORT_DIR + "/nc", "program_name": "SM1002"},
     lambda p: _laser_posted(p, scope="operation"), None),
    ("cam_get", {"setup": _CAM_SETUP, "include": ["operations"]},
     _unselected_path_untouched, None),
    ("cam_delete", {"entity": _CAM_UNSELECTED}, "ok", None),
]


_SHEET_CAM_RESTORE += [
    ("cam_save_template", {"setup": _CAM_SETUP, "operations": _CAM_OP,
                           "template_name": _FLAT_TEMPLATE, "location": "local"},
     lambda p: p.get("saved") is True and p.get("operation_count") == 1,
     ("sm_flat_template", _recall("sm_flat_template", lambda p: p["template_url"]))),
    _width_set(90),
    ("cam_apply_template", lambda c: {"setup": _CAM_SETUP, "generate": "generate",
        "template_url": _ctx_get(c, "sm_flat_template", "owned flat template"),
        "location": "local"}, _flat_template_applied,
     ("sm_flat_applied", _recall("sm_flat_applied", lambda p: {
         "operation": p["created_operations"][0],
         "tool": p["library_tools"]["forked"][0]["index"]}))),
    ("cam_get_status", lambda c: {"target": _ctx_get(c, "sm_flat_applied",
        "applied flat operation")["operation"]},
     _flat_template_generated, None),
    ("cam_get", {"setup": _CAM_SETUP, "include": ["operations", "time"]},
     _flat_template_path, None),
    ("cam_delete", lambda c: {"entity": _ctx_get(c, "sm_flat_applied",
        "applied flat operation")["operation"]}, "ok", None),
    ("cam_edit_tools", lambda c: {"action": "remove", "scope": "document",
        "remove_indices": [_ctx_get(c, "sm_flat_applied", "owned template fork")["tool"]]},
     "ok", None),
    ("cam_delete_template", lambda c: {"template_url": _ctx_get(c, "sm_flat_template",
        "owned flat template"), "confirm_name": _FLAT_TEMPLATE},
     lambda p: p.get("deleted") is True and p.get("loads_after_delete") is False, None),
    _width_set(85),
    ("cam_create_operation", {"setup": _CAM_SETUP, "strategy": "profile2d",
                              "name": _CAM_UNSELECTED, "tool_library_url": _LASER_LIBRARY,
                              "tool_index": 0, "generate": True},
     lambda p: p.get("generation_started") is True and p.get("flat_models_refreshed") == 1,
     ("sm_empty_generation", _recall("sm_empty_generation", lambda p: p["generation_handle"]))),
    ("cam_get_status", lambda c: {"handle": _ctx_get(c, "sm_empty_generation",
        "unselected contour generation")}, _created_empty_path, None),
    ("cam_delete", {"entity": _CAM_UNSELECTED}, "ok", None),
    _width_set(80),
    ("cam_post", {"program_name": "SM1001"}, lambda p: _laser_posted(p, as_is=True), None),
    ("cam_get", {"setup": _CAM_SETUP, "include": ["time"]}, lambda p: _laser_feed(p, 0), None),
]


_SHEET_CAM_RESTORE += [
    ("cam_create_setup", {"name": _MILL_SETUP, "operation_type": "cutting",
                          "flat_patterns": [_PART]},
     lambda p: p.get("flat_models_verified") is True, None),
    ("cam_edit_setup", {"setup": _MILL_SETUP, "machine": "Avid CNC|EX 3 Axis",
                        "parameters": {"job_type": "'milling'"}},
     lambda p: p.get("edited") is True and p.get("updated_count") == 1, None),
    ("cam_edit_tools", {"action": "add", "scope": "document", "add_tools": [
        {"from_type": "flat end mill", "diameter": "2 mm", "description": "SM flat mill"}]},
     lambda p: p.get("added") == 1 and p.get("tool_count", 0) > 0,
     ("sm_mill_tool", _recall("sm_mill_tool", lambda p: p["tool_count"] - 1))),
    ("cam_create_operation", lambda c: {"setup": _MILL_SETUP, "name": _MILL_OP,
        "strategy": "contour2d", "tool_scope": "document", "generate": False,
        "tool_index": _ctx_get(c, "sm_mill_tool", "owned flat mill")}, "ok", None),
    ("cam_select_geometry", {"operation": _MILL_OP, "selection": "silhouette",
                             "loop_type": "all", "generate": True},
     lambda p: p.get("setup_models_selected") is True and p.get("flat_models_refreshed") == 1, None),
    ("cam_get_status", {"target": _MILL_OP}, _mill_generated, None),
    ("cam_get", {"setup": _MILL_SETUP, "include": ["time"]}, lambda p: _mill_feed(p),
     ("sm_mill_feed_baseline", _recall("sm_mill_feed_baseline",
        lambda p: _laser_feed_value(p, _MILL_OP, _MILL_SETUP)))),
    _width_set(90),
    ("cam_generate", {"target": _MILL_OP},
     lambda p: p.get("launched") is True and p.get("flat_models_refreshed") == 1, None),
    ("cam_get_status", {"target": _MILL_OP}, _mill_generated, None),
    ("cam_get", {"setup": _MILL_SETUP, "include": ["time"]}, lambda p: _mill_feed(p, 10), None),
    _width_set(80),
    ("cam_post", {"scope": _MILL_OP, "post": "grbl", "post_scope": "fusion",
                  "output_folder": EXPORT_DIR + "/nc-mill", "program_name": "SM1003"},
     lambda p: _laser_posted(p, scope="operation"), None),
    ("cam_get", {"setup": _MILL_SETUP, "include": ["time"]}, lambda p: _mill_feed(p, 0), None),
    ("cam_delete", {"entity": "SM1003"}, lambda p: p.get("deleted") is True, None),
    ("cam_delete", {"entity": _MILL_SETUP}, lambda p: p.get("deleted") is True, None),
    ("cam_edit_tools", lambda c: {"action": "remove", "scope": "document",
        "remove_indices": [_ctx_get(c, "sm_mill_tool", "owned flat mill")]},
     lambda p: p.get("removed") == 1, None),
    ("cam_post", {"program_name": "SM1001"}, lambda p: _laser_posted(p, as_is=True), None),
    ("cam_get", {"setup": _CAM_SETUP, "include": ["time"]}, lambda p: _laser_feed(p, 0), None),
]


_SHEET_DRAWING = [
    ("doc_save_as", {"name": _DRAW_SOURCE, "project": PROJECT, "folder": FOLDER},
     _source_saved, ("sm_source_urn", _recall("sm_source_urn", lambda p: p["document_id"]))),
    ("doc_get", {}, _source_session,
     ("sm_source_session", _recall("sm_source_session", lambda p: p["active"]["document_handle"]))),
    ("data_get", lambda c: {"file": _ctx_get(c, "sm_source_urn", "the saved coupon")},
     _file_settled(FOLDER), None),
    ("drawing_create", lambda c: {"standard": "iso", "units": "mm", "sheet_size": "a3",
                                  "sheet_types": ["flat_pattern", "folded_model"],
                                  "flat_isometric": True, "bend_table": True,
                                  "bend_table_location": "bottom_right",
                                  "deferred": True,
                                  "request_key": _DRAW_KEY,
                                  "expect_document": _ctx_get(c, "sm_source_session", "coupon source session")},
     _drawing_started, ("sm_draw_job", _recall("sm_draw_job", lambda p: p["job_id"]))),
    ("drawing_get_status", {"request_key": _DRAW_KEY}, _drawing_complete,
     ("sm_drawing", _recall("sm_drawing", _drawing_file))),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "sm_drawing", "coupon drawing")[0],
                            "force_api_open": True},
     _opened(lambda: _RECALL.get("sm_drawing", [None, None])[1],
             lambda: _RECALL.get("sm_drawing", [None, None])[0]),
     ("sm_drawing_initial_session", _recall("sm_drawing_initial_session",
                                            lambda p: p["document_handle"]))),
    _dwell(4.0),
    ("drawing_get", {"include": ["views"]}, _drawing_before_screenshot, None),
    ("view_screenshot", lambda c: {"file_path": _DRAWING_PNG,
                                     "expect_document": _ctx_get(c, "sm_drawing_initial_session",
                                                                  "coupon drawing session")},
     _refused("No viewport is available for this drawing.",
              "drawing_export(format='pdf', file_path=...)"), None),
    ("drawing_get", {"include": ["views"]}, _drawing_after_screenshot, None),
    ("data_get", lambda c: _version_args("sm_drawing_before")(
        {"source_urn": _ctx_get(c, "sm_drawing", "coupon drawing")[0]}),
     _version_snapshot("sm_drawing_before"),
     ("sm_drawing_before", _recall("sm_drawing_before", _version_record))),
    ("drawing_edit_sheet", {"action": "tidy_up", "sheet": _PART + "_2"},
     lambda p: _measured("flat-sheet tidy-up accepted and document modified; confirmation can be "
                         "false if source was already dirty; visual effect unverified",
                         p, p.get("tidied") is True and p.get("sheet") == _PART + "_2"
                         and p.get("document_modified") is True
                         and (p.get("modified_confirmed") is True
                              or (p.get("modified_confirmed") is False
                                  and "already modified before this call" in (p.get("note") or "")
                                  and "drawing_export is the check" in (p.get("note") or "")))), None),
    ("doc_save", lambda c: {"description": "Persist the accepted tidy-up request",
                            "expect_document": _ctx_get(c, "sm_drawing_initial_session",
                                                        "coupon drawing session")},
     _drawing_layout_saved, None),
    ("doc_get", {}, _drawing_initial_session_saved, None),
    ("data_get", lambda c: {"file": _ctx_get(c, "sm_drawing", "coupon drawing")[0]},
     _version_settled("sm_drawing_before"), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "sm_drawing", "coupon drawing")[0]},
     _drawing_saved_version,
     ("sm_drawing_saved_version", _recall("sm_drawing_saved_version", _version_record))),
    ("doc_close", lambda c: {"name": _ctx_get(c, "sm_drawing_initial_session",
                                          "original drawing session"),
                             "save_changes": False}, _closed_one, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "sm_coupon", "coupon source session")},
     "ok", None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "sm_drawing", "coupon drawing")[0],
                            "force_api_open": True},
     _opened(lambda: _RECALL.get("sm_drawing", [None, None])[1],
             lambda: _RECALL.get("sm_drawing", [None, None])[0]),
     ("sm_drawing_session", _recall("sm_drawing_session", lambda p: p["document_handle"]))),
    _dwell(4.0),
    ("doc_get", {}, _drawing_saved_session, None),
    ("drawing_get", {"include": ["views"]}, _drawing_sheets,
     ("sm_sheet_names", _recall("sm_sheet_names", lambda p: sorted(
         row.get("name") for row in (p.get("sheets") or []) if isinstance(row, dict))))),
    ("drawing_edit_sheet", {"action": "tidy_up", "sheet": _PART + "_2"},
     lambda p: _measured("flat-sheet tidy-up accepted; false confirmation requires the "
                         "already-modified explanation; visual effect unverified",
                         p, p.get("tidied") is True and p.get("views") == 4
                         and p.get("document_modified") is True
                         and (p.get("modified_confirmed") is True
                              or (p.get("modified_confirmed") is False
                                  and "already modified before this call" in (p.get("note") or "")
                                  and "drawing_export is the check" in (p.get("note") or "")))), None),
    ("drawing_export", lambda c: {"format": "pdf", "file_path": _PDF,
                                  "deferred": True, "request_key": _PDF_KEY,
                                  "expect_document": _ctx_get(c, "sm_drawing_session", "coupon drawing")},
     lambda p: _measured("PDF job accepted", p, p.get("accepted") is True
                         and p.get("request_key") == _PDF_KEY and bool(p.get("job_id"))),
     ("sm_pdf_job", _recall("sm_pdf_job", lambda p: p["job_id"]))),
    ("drawing_get_status", {"request_key": _PDF_KEY}, _drawing_pdf, None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "sm_drawing_session", "coupon drawing session"),
                             "save_changes": False}, _closed_one, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "sm_coupon", "coupon source session")}, "ok", None),
    _dwell(4.0),
    ("doc_get", {}, _source_session, None),
]

_SHEET_CLEANUP = [
    ("sys_get_guidance", {"section": "model"},
     lambda p: _measured("sheet guidance qualifies native flat development", p,
         len([r for r in p.get("rules", []) if r.get("id") == "sheet-metal-by-intent"
              and "not verified development" in r.get("do", "")
              and "sheet_get(include=['features'])" in r.get("do", "")
              and "design_export" in r.get("do", "")]) == 1), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "sm_coupon", "coupon session"),
                             "save_changes": False}, _closed_one, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "sm_home", "original story session")}, "ok", None),
    _dwell(4.0),
    ("doc_get", {"max_results": 1000}, _story_restored, None),
]

