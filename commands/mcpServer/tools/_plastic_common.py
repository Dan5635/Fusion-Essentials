# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Scoped plastic-rule collections and their shared read records."""

import math

from . import _common

MAP_BLURB = "plastic_rules/plastic_rule_row - complete scoped rule lookup and unit-aware records."


def plastic_rules(design, scope):
    """Return a complete indexed rule collection, or None when any slot is unreadable."""
    collection = _common.safe(lambda: design.designPlasticRules if scope == "design"
                              else design.libraryPlasticRules)
    count = _common.counted(lambda: collection.count)
    if count is None or count < 0 or count > 2000:
        return None
    rules = [_common.safe(lambda index=index: collection.item(index)) for index in range(count)]
    if any(rule is None or not isinstance(_common.safe(lambda rule=rule: rule.name), str)
           for rule in rules):
        return None
    return rules


def plastic_rule_row(rule, scope, index, factor):
    """Read one scoped plastic rule with explicit length and angle units."""
    safe = _common.safe
    row = {"ref": {"scope": scope, "index": index, "name": safe(lambda: rule.name)},
           "is_used": _common.read_flag(lambda: rule.isUsed),
           "minimum_thickness": _common.measured(lambda: rule.minimumThickness, factor),
           "maximum_thickness": _common.measured(lambda: rule.maximumThickness, factor),
           "minimum_draft_angle_deg": _common.measured(lambda: math.degrees(rule.minimumDraftAngle))}
    for key, member in (("thickness", "thickness"), ("nominal_radius", "nominalRadius"),
                        ("draft_angle", "draftAngle")):
        parameter = safe(lambda member=member: getattr(rule, member))
        row[key] = {"expression": safe(lambda: parameter.expression),
                    "value_deg" if key == "draft_angle" else "value":
                        _common.measured(lambda: math.degrees(parameter.value)) if key == "draft_angle"
                        else _common.measured(lambda: parameter.value, factor)}
    return row
