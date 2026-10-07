# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Set a design parameter's expression, or create it as a user parameter (create=true). WRITES."""

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import ok, error, safe
from . import _common, _sketch_detail
from ._param_common import (_expression_identifiers, _find_parameter, _normalized_expression,
                            _param_summary)
from ._joints import (driven_joint_snapshot as _driven_joint_snapshot,
                      driven_joints_reset as _driven_joints_reset, driven_reset_note)

_SKETCH_CAP = 6          # driven sketches whose points are read around one write
_MOVED_CAP = 12          # moved points listed per sketch; moved_count carries the rest
_DEPENDENT_CAP = 20      # dependents listed per rename; dependents_total counts every one


def _driven_sketches(param):
    """[(sketch, [its dimension parameters])] among `param` and its dependentParameters."""
    groups = {}
    for p in [param] + list(_common.iter_collection(safe(lambda: param.dependentParameters))):
        # A dimension parameter's createdBy is its Sketch, not the dimension (measured).
        owner = safe(lambda p=p: p.createdBy)
        if type(owner).__name__ == "Sketch":
            key = _common.native_identity(owner) or safe(lambda p=p: p.name)
            groups.setdefault(key, (owner, []))[1].append(p)
    return list(groups.values())


def _moves_before(param):
    """(the capped driven sketches with their point census read now, how many were left unread)."""
    groups = _driven_sketches(param)
    return ([(sketch, params, _sketch_detail.point_census(sketch))
             for sketch, params in groups[:_SKETCH_CAP]], max(len(groups) - _SKETCH_CAP, 0))


def _dimension_rows(sketch, params):
    """{parameter, entities} for each of the sketch's dimensions whose parameter is in `params`."""
    token_ids = _sketch_detail.sketch_token_ids(sketch)
    rows = []
    for dim in _common.iter_collection(safe(lambda: sketch.sketchDimensions)):
        hit = next((p for p in params if safe(lambda p=p: dim.parameter == p) is True), None)
        if hit is not None:
            rows.append({"parameter": safe(lambda: hit.name),
                         "entities": _sketch_detail.dimension_entities(sketch, dim, token_ids)})
    return rows


def _sketch_move_row(sketch, params, before):
    """One driven sketch's dimensions and the points the write moved; moved is None when unread."""
    moved = _sketch_detail.moved_points(before, _sketch_detail.point_census(sketch))
    row = {"sketch": safe(lambda: sketch.name), "dimensions": _dimension_rows(sketch, params),
           "moved": None, "moved_count": None}
    if moved is not None:
        shown = moved[:_MOVED_CAP]
        ends = _sketch_detail.point_ends(sketch, [ref for ref, _was, _now in shown])
        row["moved"] = [{"id": ref, "from_mm": _sketch_detail.point_mm(was),
                         "to_mm": _sketch_detail.point_mm(now), "ends": ends[ref]}
                        for ref, was, now in shown]
        row["moved_count"] = len(moved)
    return row


def _with_moves(out, taken):
    """`out` plus sketch_moves: each driven sketch's points re-read after the write."""
    read, unread = taken
    if not read:
        return out
    out["sketch_moves"] = [_sketch_move_row(*entry) for entry in read]
    tol = _sketch_detail.MOVE_TOL_CM * _common.CM_TO_UNIT["mm"]
    notes = [f"sketch_moves lists the points that moved over {tol:g} mm, in each sketch's own "
             "coordinates (mm); sketch_get(sketch_name=...) gives that sketch's frame."]
    blind = [f"'{row['sketch']}'" for row in out["sketch_moves"] if row["moved"] is None]
    if blind:
        notes.append(f"The moves in sketch {', '.join(blind)} were not read.")
    if unread:
        out["sketch_moves_unread"] = unread
        notes.append(f"The moves in {unread} more driven sketch(es) were not read.")
    out["note"] = " ".join(([out["note"]] if out.get("note") else []) + notes)
    return out


def _before(design):
    """(driven-joint snapshot, timeline health census) read ahead of the write."""
    return _driven_joint_snapshot(design), _common.timeline_health(design)


def _with_reset(out, before, design):
    """`out`, plus observed driven-joint value changes and newly raised timeline health."""
    joints_before, (errors_before, warnings_before, _total) = before
    reset = _driven_joints_reset(joints_before, _driven_joint_snapshot(design))
    notes = []
    if reset:
        out["driven_joints_reset"] = reset
        notes.append(driven_reset_note(reset))
    errors_after, warnings_after, _total = _common.timeline_health(design)
    new_errors = [n for n in errors_after if n not in errors_before]
    new_warnings = [n for n in warnings_after if n not in warnings_before]
    if new_errors:
        out["new_timeline_errors"] = new_errors
    if new_warnings:
        out["new_timeline_warnings"] = new_warnings
    if new_errors or new_warnings:
        named = ", ".join(new_errors + new_warnings)
        notes.append(f"The value took, and the recompute left {len(new_errors)} new timeline "
                     f"error(s) and {len(new_warnings)} new warning(s): {named}. Nothing was "
                     "rolled back; read design_get(include=['timeline']) for the messages, or "
                     "set the previous value again.")
    if notes:
        out["note"] = " ".join(notes)
    return out


def _name_taken(design, name):
    """True when a listed user or model parameter's name reads exactly `name`."""
    return any(safe(lambda p=p: p.name) == name
               for coll in (safe(lambda: design.userParameters), safe(lambda: design.allParameters))
               for p in _common.iter_collection(coll))




def _dependents_before(param, unread):
    """[(index, dependent, name, expression)] by slot ahead of a rename; None when uncounted."""
    coll, why = _common.read_optional(lambda: param.dependentParameters)
    count, why = _common.read_optional(lambda: coll.count) if why is None else (None, why)
    if why is None and (isinstance(count, bool) or not isinstance(count, int)):
        why = f"count read {count!r}"
    if why is not None:
        unread["dependents"] = why
        return None
    census = []
    for i in range(count):
        p, why = _common.read_optional(lambda i=i: coll.item(i))
        if why is not None:
            unread[f"dependents[{i}]"] = why
            census.append((i, None, None, None))
            continue
        was, why = _common.read_optional(lambda p=p: p.expression)
        if why is not None:
            unread[f"dependents[{i}].expression_before"] = why
        census.append((i, p, safe(lambda p=p: p.name), was))
    return census


def _dependent_rows(before, previous, adopted, unread):
    """(rows, unchecked labels): each slot's expression before and after, `follows` where judged."""
    rows, unchecked = [], []
    for i, p, name, was in before:
        if p is None:
            rows.append({"index": i, "name": None, "expression_before": None,
                         "expression_after": None})
            unchecked.append(f"dependents[{i}]")
            continue
        now, why = _common.read_optional(lambda p=p: p.expression)
        row = {"name": name, "expression_before": was, "expression_after": now}
        if was is None:
            unchecked.append(str(name) if name else f"dependents[{i}]")
        # dependentParameters is the transitive closure: an indirect dependent never held the name.
        elif previous in _expression_identifiers(was):
            row["follows"] = None if now is None else adopted in _expression_identifiers(now)
            if now is None:
                unread[f"dependents[{i}].expression_after"] = why
        rows.append(row)
    return rows, unchecked


def _rename(name, new_name, expression, create, unit):
    """Rename one parameter; publish the adopted name and its dependents' expressions as re-read."""
    given = ([f"expression '{expression}'"] if (expression or "").strip() else [])
    given += ["create=true"] if create else []
    given += [f"unit '{unit}'"] if unit not in ("mm", None) else []
    if given:
        return error(f"new_name '{new_name}' only renames '{name}'; it was sent with "
                     f"{', '.join(given)}. Rename in one call and set the value in another.")
    design = _common.design()
    if not design:
        return error("No active design (open a document with design geometry).")
    param = _find_parameter(design, name)
    if not param:
        return error(f"Parameter not found: '{name}'. Use param_get to list them.")
    previous = safe(lambda: param.name)
    if not isinstance(previous, str):
        return error(f"The name of parameter '{name}' did not read; nothing was renamed.")
    if new_name in (name, previous):
        return error(f"'{new_name}' is already this parameter's name; nothing was renamed.")
    if _name_taken(design, new_name):
        return error(f"Cannot rename '{previous}' to '{new_name}': another parameter already has "
                     "that name. Nothing was renamed; choose a name param_get does not list.")

    before = _param_summary(param)
    unread_why = {}
    dependents = _dependents_before(param, unread_why)
    errors_before, warnings_before, _total = _common.timeline_health(design)
    raised = None
    try:
        param.name = new_name
    except Exception as e:
        raised = e
    adopted = safe(lambda: param.name)
    if raised is not None:
        reads = f"is named '{adopted}'" if isinstance(adopted, str) else "did not read back"
        return error(f"Could not rename '{previous}' to '{new_name}': {raised}. "
                     f"The parameter {reads} now.")
    if not isinstance(adopted, str):
        return error(f"'{new_name}' was assigned to '{previous}' but the name did not read back, "
                     "so the rename is unverified. Read param_get before using either name.")
    if adopted == previous:
        return error(f"Assigning '{new_name}' raised no error but the parameter is still named "
                     f"'{previous}' - the rename did not take, and Fusion gave no reason. "
                     "Try another name.")

    rows, unchecked = ([], []) if dependents is None else _dependent_rows(
        dependents, previous, adopted, unread_why)
    stray = [str(r["name"]) for r in rows if r.get("follows") is False]
    followed = [str(r["name"]) for r in rows if r.get("follows") is True]
    unread = [str(r["name"]) for r in rows if "follows" in r and r["follows"] is None]
    rows.sort(key=lambda r: r.get("follows") is not False)
    out = {"renamed": True, "previous_name": previous, "requested_name": new_name,
           "name": adopted, "before": before, "after": _param_summary(param),
           "dependents": rows[:_DEPENDENT_CAP], "dependents_total": len(rows),
           "dependents_truncated": len(rows) > _DEPENDENT_CAP}
    notes = []
    if dependents is None:
        out.update(dependents=None, dependents_total=None, dependents_truncated=None)
        notes.append("The dependents did not read before the rename, so their expressions were "
                     "not checked; read them with param_get.")
    if unchecked:
        notes.append(f"{len(unchecked)} dependent(s) did not read before the rename and were not "
                     f"checked: {_common.named_with_remainder(unchecked)}.")
    if unread_why:
        out["unread"] = unread_why
    if adopted != new_name:
        notes.append(f"Fusion adopted the name '{adopted}', not the requested '{new_name}'.")
    if unread:
        notes.append("The expression did not read after the rename for: "
                     f"{_common.named_with_remainder(unread)}.")
    errors_after, warnings_after, _total = _common.timeline_health(design)
    new_errors = [n for n in errors_after if n not in errors_before]
    new_warnings = [n for n in warnings_after if n not in warnings_before]
    if new_errors:
        out["new_timeline_errors"] = new_errors
    if new_warnings:
        out["new_timeline_warnings"] = new_warnings
    if new_errors or new_warnings:
        notes.append(f"The timeline reads {len(new_errors)} new error(s) and {len(new_warnings)} "
                     f"new warning(s) after the rename: {', '.join(new_errors + new_warnings)}. "
                     "Nothing was rolled back.")
    if stray:
        text = (f"'{previous}' is now named '{adopted}', but {len(stray)} dependent expression(s) "
                f"do not use the new name: {_common.named_with_remainder(stray)}; "
                f"{len(followed)} followed. Nothing was rolled back; 'dependents' lists each "
                "expression before and after - set the stray ones with param_set.")
        out["note"] = " ".join([text] + notes)
        return error(text, out)
    if notes:
        out["note"] = " ".join(notes)
    return ok(out)


def handler(name: str = "", expression: str = "", create: bool = False,
            unit: str = "mm", new_name: str = "") -> dict:
    """Set a design parameter's expression, create it (create=true), or rename it. WRITES."""
    name = (name or "").strip()
    if not name:
        return error("Provide 'name' - the parameter to set.")
    if (new_name or "").strip():
        return _rename(name, new_name.strip(), expression, create, unit)
    if (expression or "").strip() == "" and expression != "0":
        return error("Provide 'expression' - the new value/expression for the parameter.")

    design = _common.design()
    if not design:
        return error("No active design (open a document with design geometry).")

    param = _find_parameter(design, name)
    if not param:
        if not create:
            return error(f"Parameter not found: '{name}'. Use param_get to list them, or pass "
                          "create=true to make it a new user parameter.")
        # create-or-update: make a new user parameter with the given expression + unit.
        reads_before = _before(design)
        try:
            vi = adsk.core.ValueInput.createByString(expression)
            param = design.userParameters.add(name, vi, unit or "", "")
        except Exception as e:
            return error(f"Could not create user parameter '{name}' = '{expression}' "
                          f"(unit '{unit}'): {e}.")
        if not param:
            return error(f"Creating user parameter '{name}' returned nothing.")
        return ok(_with_reset({"set": True, "created": True, "name": name,
        "before": None, "after": _param_summary(param)}, reads_before, design))

    before = _param_summary(param)
    reads_before = _before(design)
    moves_before = _moves_before(param)
    try:
        param.expression = expression
    except Exception as e:
        return error(f"Could not set '{name}' to '{expression}': {e}. "
    "(Model/feature parameters may be read-only or require a valid "
    "expression; text parameters need quotes, e.g. \"'text'\".)")

    after = _param_summary(param)
    if after == before:
        if _normalized_expression(expression) == _normalized_expression(before.get("expression")):
            return ok(_with_moves(_with_reset({"set": True, "created": False, "name": name,
                       "already_current": True, "before": before, "after": after},
                       reads_before, design), moves_before))
        return error(f"Assignment raised no error but '{name}' still reads expression "
                     f"'{before.get('expression')}' - setting '{expression}' did not take.")
    return ok(_with_moves(_with_reset({"set": True, "created": False, "name": name,
              "before": before, "after": after}, reads_before, design), moves_before))


TOOL_DESCRIPTION = (
"Set expression or rename; param_get lists names. driven_joints_reset lists value changes, "
"not causes."
)

tool = (
    Tool.create_with_string_input(
        name="param_set",
        description=TOOL_DESCRIPTION,
        input_param_name="name",
        input_param_description="The parameter to set.",
    )
    .add_input_property("expression", {"type": "string",
            "description": "e.g. '2 in', 'StockX/2', \"'text'\"; function args use ';': if(a>=2 in; 10 mm; 5 mm)."})
    .add_input_property("create", {"type": "boolean"})
    .add_input_property("unit", {"type": "string",
            "description": "For a created parameter ('' unitless)."})
    .add_input_property("new_name", {"type": "string"})
    .strict_schema()
)

item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline", rung="value",
        evidence_test="tests/unit/test_param_set.py::TestSetCreateOrUpdate"
                      "::test_silent_no_op_assignment_bites"))


def register_tool():
    register(item)
