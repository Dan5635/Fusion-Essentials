# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Copy, edit or remove a design-local plastic rule."""

import math

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _inputs, _outputs, _plastic_common

_ACTION = _inputs.Choice("action", ("copy", "update", "delete"), required=True)
_RULE = _inputs.PlasticRuleRef("rule", required=True)
_FIELDS = {"minimum_thickness": "minimumThickness", "maximum_thickness": "maximumThickness",
           "minimum_draft_deg": "minimumDraftAngle"}
RETURNS = [_outputs.ReturnsValue("action", "the completed action"),
           _outputs.ReturnsValue("rule", "the scoped rule record"),
           _outputs.ReturnsValue("before", "the source rule record"),
           _outputs.ReturnsValue("after", "the retained rule record or empty after deletion"),
           _outputs.ReturnsValue("deleted", "whether the rule was removed")]


def _requested(design, factor, minimum, maximum, draft):
    """Return finite native-unit requested fields or a preflight refusal."""
    values = {}
    for name, raw in (("minimum_thickness", minimum), ("maximum_thickness", maximum)):
        if raw is None:
            continue
        if isinstance(raw, bool):
            return None, f"'{name}' got {raw!a}; use a positive length."
        _, cm, reason = _inputs.length_value_input(raw, factor, design, name)
        if reason:
            return None, reason
        if not isinstance(cm, (float, int)) or not math.isfinite(cm) or cm <= 0:
            return None, f"'{name}' got {raw!a}; use a finite positive length."
        values[name] = cm
    if draft is not None:
        if (isinstance(draft, bool) or not isinstance(draft, (float, int))
                or not math.isfinite(draft) or not 0 <= draft < 90):
            return None, f"'minimum_draft_deg' got {draft!a}; use a finite angle from 0 to below 90 deg."
        values["minimum_draft_deg"] = math.radians(draft)
    return values, None


def _record(design, target, factor, index, scope="design"):
    """Read the exact current rule reference, refusing an incomplete collection."""
    rules = _plastic_common.plastic_rules(design, scope)
    if rules is None or index >= len(rules):
        return None
    if rules[index].name != _common.safe(lambda: target.name):
        return None
    return _plastic_common.plastic_rule_row(rules[index], scope, index, 1 / factor)


def handler(action: str = "", rule=None, name: str = "", minimum_thickness=None,
            maximum_thickness=None, minimum_draft_deg: float = None, units: str = "mm") -> dict:
    """Return verified rule edits or an explicit partial-effect refusal."""
    design, design_refusal = _common.require_design(none_only=True)
    if design_refusal is not None:
        return design_refusal
    values, refusal = _inputs.resolve_inputs([_ACTION, _RULE, _inputs.UNITS],
                                            {"action": action, "rule": rule, "units": units})
    if refusal:
        return refusal
    choice, (selected, scope, source_index) = values["action"], values["rule"]
    factor = _common.scale(values["units"])
    wanted, reason = _requested(design, factor, minimum_thickness, maximum_thickness, minimum_draft_deg)
    if reason:
        return _common.error(reason)
    if choice != "copy" and scope != "design":
        return _common.error(f"rule {rule!a} is a library rule; action='copy' makes a design-local copy.")
    if choice == "delete" and (name.strip() or wanted):
        return _common.error("action='delete' takes only a rule; omit name and edit fields.")
    if choice == "update" and not (name.strip() or wanted):
        return _common.error("action='update' needs name or a minimum/maximum field.")
    rules = _plastic_common.plastic_rules(design, "design")
    if rules is None:
        return _common.error("Design plastic rules could not be completely read; no edit attempted.")
    new_name = name.strip()
    if choice == "copy" and not new_name:
        return _common.error("action='copy' needs a nonempty name for the design-local rule.")
    if new_name and any(index != source_index and r.name.lower() == new_name.lower()
                        for index, r in enumerate(rules)):
        return _common.error(f"Design plastic rule '{new_name}' already exists; choose another name.")
    if choice == "copy" and any(r.name.lower() == new_name.lower() for r in rules):
        return _common.error(f"Design plastic rule '{new_name}' already exists; choose another name.")
    lower = wanted.get("minimum_thickness", _common.measured(lambda: selected.minimumThickness))
    upper = wanted.get("maximum_thickness", _common.measured(lambda: selected.maximumThickness))
    if any(key in wanted for key in ("minimum_thickness", "maximum_thickness")) and (
            lower is None or upper is None or lower > upper):
        return _common.error(f"Thickness range {lower!a}..{upper!a} cm is unreadable or reversed; "
                             "read design_get(include=['plastic_rules']) and use minimum <= maximum.")
    before = _record(design, selected, factor, source_index, scope)
    if before is None:
        return _common.error("The rule's exact reference did not read; re-read design_get plastic_rules. No edit attempted.")
    if choice == "delete":
        names_before = [r.name for r in rules]
        used = _common.read_flag(lambda: selected.isUsed)
        if used is not False:
            return _common.error(f"Rule {rule!a} is used or its usage did not read; delete only an unused design rule.")
        try:
            deleted = selected.deleteMe()
        except Exception as exc:
            return _common.error(f"Rule delete raised: {exc}. Read design_get(include=['plastic_rules']) before retrying.")
        after_rules = _plastic_common.plastic_rules(design, "design")
        expected_names = names_before[:source_index] + names_before[source_index + 1:]
        if (deleted is not True or after_rules is None or len(after_rules) != len(rules) - 1
                or [r.name for r in after_rules] != expected_names):
            return _common.error("Rule deletion was not confirmed; read design_get(include=['plastic_rules']) before retrying.")
        return _common.ok({"action": choice, "rule": before, "before": before, "after": {}, "deleted": True})
    target = selected
    target_index = source_index
    applied = []
    try:
        if choice == "copy":
            target = design.designPlasticRules.addByCopy(selected, new_name)
            current = _plastic_common.plastic_rules(design, "design")
            hits = [i for i, r in enumerate(current or []) if r.name == new_name]
            if (target is None or current is None or len(current) != len(rules) + 1
                    or len(hits) != 1 or _common.safe(lambda: target.name) != new_name
                    or [r.name for r in current if r.name != new_name] != [r.name for r in rules]):
                raise RuntimeError("copy membership/count/name did not read back")
            target_index = hits[0]
            applied.append("copy")
        elif new_name:
            target.name = new_name
            if _common.safe(lambda: target.name) != new_name:
                raise RuntimeError(f"name '{new_name}' did not read back")
            applied.append("name")
        order = list(wanted)
        if "minimum_thickness" in wanted and "maximum_thickness" in wanted:
            current_upper = _common.measured(lambda: target.maximumThickness)
            if current_upper is None:
                raise RuntimeError("maximum thickness did not read before the range update")
            if wanted["minimum_thickness"] > current_upper:
                order.remove("maximum_thickness")
                order.insert(0, "maximum_thickness")
        for field in order:
            setattr(target, _FIELDS[field], wanted[field])
            landed = _common.measured(lambda field=field: getattr(target, _FIELDS[field]), places=12)
            if landed is None or not math.isclose(landed, wanted[field], abs_tol=1e-9, rel_tol=1e-8):
                raise RuntimeError(f"{field} did not read back: {landed!a}")
            applied.append(field)
        if choice == "copy" and _record(design, selected, factor, source_index, scope) != before:
            raise RuntimeError("the source rule record changed during copy")
    except Exception as exc:
        return _common.error(f"Plastic rule action '{choice}' failed: {exc}. Applied: {applied!a}. "
                             f"Current rule: {_record(design, target, factor, target_index)!a}. "
                             "A copy may exist even when its membership did not verify. "
                             "Read design_get(include=['plastic_rules']); partial edits are retained.")
    after = _record(design, target, factor, target_index)
    if after is None:
        return _common.error("Rule changed but its exact reference could not be read; read design_get(include=['plastic_rules']).")
    return _common.ok({"action": choice, "rule": after, "before": before, "after": after,
                       "deleted": False, "applied": applied,
                       "note": "Design-local rule values retained. Component geometry was not verified."})


TOOL_DESCRIPTION = ("Copy a plastic rule into the design, update it or delete an unused design rule. "
                    "design_get plastic_rules supplies exact refs.")
tool = (Tool.create_simple(name="design_edit_plastic_rule", description=TOOL_DESCRIPTION + "\n" + _outputs.produces_block(RETURNS))
        .add_input_property(*_ACTION.as_property()).add_required_input("action")
        .add_input_property(*_RULE.as_property()).add_required_input("rule")
        .add_input_property("name", {"type": "string", "description": "Copy name or new design-rule name."})
        .add_input_property("minimum_thickness", {"type": ["number", "string"]})
        .add_input_property("maximum_thickness", {"type": ["number", "string"]})
        .add_input_property("minimum_draft_deg", {"type": "number"})
        .add_input_property(*_inputs.UNITS.as_property()).strict_schema())
item = Item.create_tool_item(tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(kind="effect", rung="value",
        evidence_test="tests/unit/test_design_edit_plastic_rule.py::test_noop_setter_is_a_failure"))


def register_tool():
    register(item)
