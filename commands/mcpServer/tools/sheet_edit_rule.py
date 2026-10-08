# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Copy or edit a design-local sheet-metal rule."""

import math
import re

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common, _inputs, _outputs, _sheet_common

_RULE = _inputs.SheetMetalRuleRef("rule", required=True)
_ACTION = _inputs.Choice("action", ("copy", "update", "delete"), default="copy")
_LENGTH = re.compile(r"^\s*[+]?(?:\d+(?:\.\d*)?|\.\d+)\s*(?:mm|cm|in)\s*$", re.I)
_FIELDS = (("thickness", "thickness"), ("bend_radius", "bendRadius"), ("gap", "gap"),
           ("relief_width", "reliefWidth"), ("relief_depth", "reliefDepth"), ("relief_remnant", "reliefRemnant"),
           ("two_bend_relief_size", "twoBendReliefSize"), ("three_bend_relief_radius", "threeBendReliefRadius"))
_SHAPES = [_inputs.Choice(key, tuple(row[2])) for key, row in _sheet_common.RULE_SHAPES.items()]
RETURNS = [_outputs.ReturnsValue("action", "the completed action"),
           _outputs.ReturnsValue("rule", "the rule record"),
           _outputs.ReturnsValue("before", "the source rule record"),
           _outputs.ReturnsValue("after", "the retained rule record or empty after deletion"),
           _outputs.ReturnsValue("deleted", "whether the rule was removed")]


def _length_cm(expr):
    """Return an explicit-unit positive length in centimeters."""
    match = re.fullmatch(r"\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(mm|cm|in)\s*", expr, re.I)
    number, unit = float(match.group(1)), match.group(2).lower()
    return number * _common.scale(unit)


def _specs(lengths, k_factor):
    """Return validated explicit-unit expressions and K factor."""
    values = lengths
    for key, expr in values.items():
        if expr is not None and (not isinstance(expr, str) or not _LENGTH.fullmatch(expr)):
            return None, f"'{key}' value '{expr}' needs a positive literal with mm, cm, or in units."
        if expr is not None and (not math.isfinite(_length_cm(expr)) or _length_cm(expr) <= 0):
            return None, f"'{key}' value '{expr}' must be positive."
    if k_factor is not None and (isinstance(k_factor, bool) or not isinstance(k_factor, (int, float))
                                 or not math.isfinite(k_factor) or not 0 <= k_factor <= 1):
        return None, f"'k_factor' value '{k_factor}' must be a finite number from 0 to 1."
    return values, None


def handler(action: str = "copy", rule: str = "", name: str = "", thickness: str = None,
            bend_radius: str = None, gap: str = None, k_factor: float = None,
            relief_width: str = None, relief_depth: str = None, relief_remnant: str = None,
            two_bend_relief_size: str = None, three_bend_relief_radius: str = None,
            relief_shape: str = None, two_bend_relief_shape: str = None,
            two_bend_relief_placement: str = None, three_bend_relief_shape: str = None) -> dict:
    """See TOOL_DESCRIPTION."""
    design = _common.design()
    if design is None:
        return error("No active design. Create or open a design first.")
    choice, cerr = _ACTION.resolve(action)
    if cerr:
        return error(cerr)
    source, rerr = _RULE.resolve(rule)
    if rerr:
        return error(rerr)
    selected, scope = source
    values, verr = _specs(dict(zip((key for key, _ in _FIELDS), (thickness, bend_radius, gap,
        relief_width, relief_depth, relief_remnant, two_bend_relief_size, three_bend_relief_radius))), k_factor)
    if verr:
        return error(verr)
    shapes, refusal = _inputs.resolve_inputs(_SHAPES, dict(zip((kind.name for kind in _SHAPES),
        (relief_shape, two_bend_relief_shape, two_bend_relief_placement, three_bend_relief_shape))))
    if refusal:
        return refusal
    shapes = {key: value for key, value in shapes.items() if value is not None}
    requested_enums = {key: _sheet_common.relief_enum(key, value) for key, value in shapes.items()}
    if any(value is None for value in requested_enums.values()):
        return error(f"Relief choices {shapes!a} are unavailable in this build; no rule mutation attempted.")
    target_shape = two_bend_relief_shape
    if two_bend_relief_shape is not None or two_bend_relief_placement is not None:
        pair = {}
        for key in ("two_bend_relief_shape", "two_bend_relief_placement"):
            current = safe(lambda key=key: getattr(selected, _sheet_common.RULE_SHAPES[key][0]))
            pair[key] = shapes.get(key, next((label for label in _sheet_common.RULE_SHAPES[key][2]
                if current is not None and current == _sheet_common.relief_enum(key, label)), None))
        target_shape = pair["two_bend_relief_shape"]
        if (None in pair.values() or target_shape == "square" and pair["two_bend_relief_placement"] == "tangent"):
            return error("Two-bend relief needs round with intersection/tangent/vertex, or square with "
                         "intersection/vertex. Supply both choices if the current pair did not read; no edit attempted.")
        shapes.update(pair)
        requested_enums.update({key: _sheet_common.relief_enum(key, value) for key, value in pair.items()})
    if choice != "copy" and scope != "design":
        return error(f"rule '{rule}' is a library rule; copy it with action='copy' before editing.")
    before_row = _sheet_common.rule_row(design, selected, scope)
    if choice == "delete":
        if name.strip() or any(value is not None for value in values.values()) or k_factor is not None or shapes:
            return error("action='delete' takes only rule; omit name and edit fields.")
        if _common.read_flag(lambda: selected.isUsed) is not False:
            return error(f"Rule '{rule}' is used or usage did not read; delete only an unused design rule.")
        rules_before = _sheet_common.scoped_rules(design, "design")
        index = before_row.get("index")
        if rules_before is None or type(index) is not int or not 0 <= index < len(rules_before):
            return error("The selected rule's collection position did not read; re-read sheet_get before deleting.")
        names = [r.name for r in rules_before]
        expected_names = names[:index] + names[index + 1:]
        try:
            deleted = selected.deleteMe()
        except Exception as exc:
            return error(f"Rule deletion raised: {exc}. Read sheet_get before retrying.")
        rules_after = _sheet_common.scoped_rules(design, "design")
        if deleted is not True or rules_after is None or [r.name for r in rules_after] != expected_names:
            return error("Rule deletion was not confirmed; read sheet_get before retrying.")
        return ok({"action": choice, "rule": before_row, "before": before_row, "after": {}, "deleted": True})
    if choice == "copy":
        new_name = name.strip()
        if not new_name:
            return error("action='copy' needs a nonempty 'name' for the design-local rule.")
        existing = _sheet_common.matching_rules(design, "design", new_name)
        if existing is None:
            return error("Design-local rules could not be read; no copy attempted.")
        if existing:
            return error(f"Design-local rule '{new_name}' already exists; choose another name or update it.")
        local = safe(lambda: design.designSheetMetalRules)
        if local is None or safe(lambda: local.count) in (None, 0):
            return error("Design sheet-metal rule data is uninitialized. Create a root sheet-metal "
                         "component with model_create_component(sheet_metal=true), then retry the copy.")
        before = safe(lambda: local.count)
        try:
            created = local.addByCopy(selected, new_name)
        except Exception as exc:
            return error(f"Could not copy rule '{rule}' as '{new_name}': {exc}. "
                         "Read sheet_get(include=['rules']) before retrying.")
        hits = _sheet_common.matching_rules(design, "design", new_name)
        if created is None or hits is None or len(hits) != 1 or safe(lambda: local.count) != before + 1:
            return error(f"Copy of '{rule}' as '{new_name}' was not verified. "
                         "Read sheet_get(include=['rules']) to inspect any partial effect.")
        target = hits[0]
    else:
        if name.strip():
            return error("'name' applies only to action='copy'; use the scoped rule ref for update.")
        if not any(v is not None for v in values.values()) and k_factor is None and not shapes:
            return error("action='update' needs a length, k_factor or relief choice.")
        target = selected
    applied = []
    for input_name, native_name in _FIELDS:
        expr = values[input_name]
        if expr is None:
            continue
        value = safe(lambda native_name=native_name: getattr(target, native_name))
        if value is None:
            return error(f"Rule '{safe(lambda: target.name)}' persists; {input_name} could not be read. "
                         f"Applied so far: {applied}. Read sheet_get(include=['rules']).")
        try:
            value.expression = expr
        except Exception as exc:
            return error(f"Rule '{safe(lambda: target.name)}' persists; {input_name}='{expr}' failed: {exc}. "
                         f"Applied so far: {applied}. Read sheet_get(include=['rules']).")
        landed = safe(lambda value=value: value.expression)
        actual_cm = safe(lambda value=value: value.value)
        expected_cm = _length_cm(expr)
        if landed is None or actual_cm is None or not math.isclose(actual_cm, expected_cm, rel_tol=1e-8, abs_tol=1e-9):
            return error(f"Rule '{safe(lambda: target.name)}' persists; {input_name}='{expr}' "
                         f"did not evaluate to {expected_cm} cm (got {actual_cm} cm; expression '{landed}'). "
                         f"Applied so far: {applied}.")
        applied.append(input_name)
    if k_factor is not None:
        try:
            target.kFactor = float(k_factor)
        except Exception as exc:
            return error(f"Rule '{safe(lambda: target.name)}' persists; k_factor={k_factor} failed: {exc}. "
                         f"Applied so far: {applied}.")
        landed = safe(lambda: target.kFactor)
        if landed is None or not math.isclose(landed, k_factor, abs_tol=1e-9):
            return error(f"Rule '{safe(lambda: target.name)}' persists; k_factor={k_factor} did not "
                         f"read back (got '{landed}'). Applied so far: {applied}.")
        applied.append("k_factor")
    order = list(requested_enums)
    if target_shape == "square" and "two_bend_relief_placement" in order:
        order.remove("two_bend_relief_placement")
        order.insert(0, "two_bend_relief_placement")
        if "two_bend_relief_shape" in order:
            order.append("two_bend_relief_placement")
    for key in order:
        wanted = requested_enums[key]
        member = _sheet_common.RULE_SHAPES[key][0]
        try:
            if safe(lambda member=member: getattr(target, member)) != wanted:
                setattr(target, member, wanted)
        except Exception as exc:
            return error(f"Rule persists; {key}='{shapes[key]}' failed: {exc}. Applied: {applied}. Read sheet_get.")
        if safe(lambda member=member: getattr(target, member)) != wanted:
            return error(f"Rule persists; {key}='{shapes[key]}' did not read back. Applied: {applied}. Read sheet_get.")
        if key not in applied:
            applied.append(key)
    row = _sheet_common.rule_row(design, target, "design")
    for input_name, native_name in _FIELDS:
        expr = values[input_name]
        actual = (row.get(native_name) or {}).get("value_cm")
        if expr is not None and (actual is None or not math.isclose(actual, _length_cm(expr), rel_tol=1e-8, abs_tol=1e-9)):
            return error(f"Rule persists; final {input_name}='{expr}' did not read back (got {actual} cm). "
                         f"Applied: {applied}. Read sheet_get.")
    if k_factor is not None and (row.get("k_factor") is None or not math.isclose(row["k_factor"], k_factor, abs_tol=1e-9)):
        return error(f"Rule persists; final k_factor={k_factor} did not read back. Applied: {applied}. Read sheet_get.")
    for key, wanted in shapes.items():
        if row.get(key) != wanted:
            return error(f"Rule persists; final {key}='{wanted}' did not read back (got {row.get(key)!a}). "
                         f"Applied: {applied}. Read sheet_get.")
    if choice == "copy" and row["name"] != new_name:
        return error(f"Copied rule name '{new_name}' did not persist; actual is '{row['name']}'.")
    return ok({"action": choice, "rule": row, "before": before_row, "after": row, "deleted": False,
               "applied": applied, "note": "Design-local rule values read back; relief geometry was not verified. "
               "Assign or convert a component separately."})


TOOL_DESCRIPTION = ("Copy or update a design sheet rule, or delete an unused design rule. "
                    "Lengths are positive literals with units; sheet_get supplies exact refs.")

tool = (Tool.create_simple(name="sheet_edit_rule", description=TOOL_DESCRIPTION + "\n" + _outputs.produces_block(RETURNS))
        .add_input_property(*_ACTION.as_property())
        .add_input_property(*_RULE.as_property())
        .add_required_input("rule")
        .add_input_property("name", {"type": "string"})
        .add_input_property("thickness", {"type": "string", "description": "Length with units."})
        .add_input_property("bend_radius", {"type": "string", "description": "Length with units."})
        .add_input_property("gap", {"type": "string", "description": "Length with units."})
        .add_input_property("k_factor", {"type": "number", "minimum": 0, "maximum": 1})
        .add_input_property("relief_width", {"type": "string"})
        .add_input_property("relief_depth", {"type": "string"})
        .add_input_property("relief_remnant", {"type": "string"})
        .add_input_property("two_bend_relief_size", {"type": "string"})
        .add_input_property("three_bend_relief_radius", {"type": "string"})
        .add_input_property(*_SHAPES[0].as_property()).add_input_property(*_SHAPES[1].as_property())
        .add_input_property(*_SHAPES[2].as_property()).add_input_property(*_SHAPES[3].as_property())
        .strict_schema())
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(kind="effect", rung="value",
                              evidence_test="tests/unit/test_sheet_edit_rule.py::test_copy_requires_initialized_design_rules"))


def register_tool():
    register(item)
