# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Read native sheet-metal rules, component ownership and flat-pattern presence."""

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common, _sheet_common, _edit_feature_common

_SLICES = ("rules", "library_rules", "components", "features")


def _normalize_include(include):
    """Return requested rich-read slices."""
    if include in (None, "", []):
        return []
    if isinstance(include, str):
        return [part.strip().lower() for part in include.split(",") if part.strip()]
    return [str(part).strip().lower() for part in include]


def _rules(design, scope, limit):
    """Return readable scoped rule rows up to the response cap."""
    rules = _sheet_common.scoped_rules(design, scope)
    if rules is None:
        return {"readable": False, "rules": None}
    return {"readable": True, "rules": [_sheet_common.rule_row(design, r, scope) for r in rules[:limit]],
            "total": len(rules), "truncated": len(rules) > limit}


def _components(design, limit):
    """Return component rows and disclose an incomplete design walk."""
    collection = safe(lambda: design.allComponents)
    expected = safe(lambda: collection.count) if collection is not None else None
    comps = _common.all_components(design)
    complete = expected is not None and len(comps) == expected
    rules = _sheet_common.scoped_rules(design, "design")
    return {"components": [_sheet_common.component_row(c, rules) for c in comps[:limit]],
            "total": len(comps) if complete else None,
            "walk_complete": complete, "truncated": len(comps) > limit,
            "note": "Use active_rule_ref with sheet_edit_rule; unknown means identity is unconfirmed. Component names may repeat; use a face/edge handle from find_geometry on the body for sheet_convert."}


def _hem_kind(hem):
    """Return the hem's definition kind ('flat', 'rolled', ...) from its objectType suffix, or None."""
    cls = (safe(lambda: hem.definition.objectType) or "").split("::")[-1]
    if not cls:
        return None
    return cls[:-len("HemFeatureDefinition")].lower() if cls.endswith("HemFeatureDefinition") else cls.lower()


def _feature_row(component, geometry_limit):
    """Return one component's fold/hem/rip/join/flange counts and flat-pattern state."""
    feats = safe(lambda: component.features)
    def _count(attr):
        coll = safe(lambda: getattr(feats, attr)) if feats is not None else None
        return safe(lambda: coll.count) if coll is not None else None
    hems, hem_read = _definition_rows(safe(lambda: feats.hemFeatures), geometry_limit, hem=True)
    rips, rip_read = _definition_rows(safe(lambda: feats.ripFeatures), geometry_limit)
    return {"component": safe(lambda: component.name),
            "folds": _count("foldFeatures"), "hems": hems, "hem_count": _count("hemFeatures"),
            "rips": _count("ripFeatures"), "rip_definitions": rips,
            "definition_limit": geometry_limit, "hem_read": hem_read, "rip_read": rip_read,
            "joins": _count("joinByBendFeatures"), "flanges": _count("flangeFeatures"),
            "flat_pattern": _sheet_common.flat_pattern_row(component, geometry_limit=geometry_limit)}


def _definition_rows(collection, limit, hem=False):
    """Read capped feature definitions and disclose missing collection entries."""
    count = _common.counted(lambda: collection.count)
    if count is None:
        return None, {"total": None, "truncated": None, "unread_indices": None}
    rows, unread = [], []
    for index in range(min(count, limit)):
        feature = safe(lambda index=index: collection.item(index))
        if feature is None:
            unread.append(index)
            continue
        row = {"name": safe(lambda: feature.name),
               "definition": _edit_feature_common.feature_definition(feature, 10)}
        if hem:
            row["kind"] = _hem_kind(feature)
        rows.append(row)
    return rows, {"total": count, "truncated": count > limit, "unread_indices": unread}


def _features(design, limit):
    """Return per-component feature-family counts, capped, and disclose an incomplete walk."""
    collection = safe(lambda: design.allComponents)
    expected = safe(lambda: collection.count) if collection is not None else None
    comps = _common.all_components(design)
    complete = expected is not None and len(comps) == expected
    return {"components": [_feature_row(c, min(32, limit)) for c in comps[:limit]],
            "total": len(comps) if complete else None,
            "walk_complete": complete, "truncated": len(comps) > limit}


def handler(include=None, max_results: int = 50) -> dict:
    """See TOOL_DESCRIPTION."""
    inc = _normalize_include(include)
    bad = [name for name in inc if name not in _SLICES and name != "default"]
    if bad:
        return error(f"Unknown include {bad}. Use rules, library_rules, components, features, or default.")
    if not isinstance(max_results, int) or not 1 <= max_results <= 200:
        return error(f"max_results '{max_results}' must be an integer from 1 to 200.")
    design = _common.design()
    if design is None:
        return error("No active design. Create or open a design first.")
    out = {}
    if not inc or "default" in inc:
        local = safe(lambda: design.designSheetMetalRules)
        library = safe(lambda: design.librarySheetMetalRules)
        out["design_rule_count"] = safe(lambda: local.count) if local is not None else None
        out["library_rule_count"] = safe(lambda: library.count) if library is not None else None
        out["next"] = [name for name in _SLICES if name not in inc]
    if "rules" in inc:
        out["rules"] = _rules(design, "design", max_results)
    if "library_rules" in inc:
        out["library_rules"] = _rules(design, "library", max_results)
    if "components" in inc:
        out["components"] = _components(design, max_results)
    if "features" in inc:
        out["features"] = _features(design, max_results)
    return ok(out)


TOOL_DESCRIPTION = "Read sheet rules and assignments; include rules, library_rules, components or features."

tool = (Tool.create_simple(name="sheet_get", description=TOOL_DESCRIPTION)
        .add_input_property("include", {"type": "array", "items": {"type": "string",
                                          "enum": list(_SLICES) + ["default"]}})
        .add_input_property("max_results", {"type": "integer"})
        .strict_schema())
item = Item.create_tool_item(tool=tool, write="read", handler=handler, run_on_main_thread=True)


def register_tool():
    register(item)
