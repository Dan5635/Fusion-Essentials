# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""sys_get_guidance - the server's packaged CAD design guidance: the index, one section, or one
recipe per call. Static content read through ``..guidance.loader``; nothing here touches Fusion."""

from ._common import ok, error
from . import _inputs
from ..guidance import loader
from ..guidance import resources
from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register

_SECTION = _inputs.Choice(
    "section", loader.SECTION_IDS,
    description="Omit for the index.")

_RECIPE = _inputs.Choice("recipe", loader.RECIPE_IDS)

INDEX_NOTE = (
    "Packaged design guidance. 'kernel' gives five rules; 'sections' and 'recipes' index narrower "
    "reads. Call section=<id> or recipe=<id>. Rules and recipes declare 'scenarios'. 'sha256' "
    "hashes the current source; 'resource_uri' serves the add-in-load snapshot. Compare its source "
    "stamp and reload the add-in if hashes differ.")

SECTION_NOTE = (
    "The kernel's five habits apply to every step in this section. Each rule has 'when', 'do', "
    "'except', 'prove', and 'scenarios'; 'kind' marks a safety invariant, while other rules are "
    "strategy. 'kernel' carries them unless this is the kernel section, where 'rules' has them. "
    "'recipe_index' names this section's recipes; recipe=<id> returns one "
    "whole. 'next_sections' names other sections.")

RECIPE_NOTE = (
    "The kernel's five habits apply to every step of this recipe. A recipe is one worked "
    "construction, not a macro: 'use_when' names prerequisites and each step names its tool. "
    "A 'read_back' may need a companion read; intermediate calls and justified alternatives are "
    "allowed. An unanswered read_back blocks only the steps that depend on it. 'bar' is done; "
    "'exemplar' is an optional document to X-ray.")

TRUNCATED_NOTE = (
    " This section holds more rules than one call returns: 'rule_count' of 'rule_total' are in "
    "'rules' and the rest are not here. Read the document at 'resource_uri' over the resource "
    "channel for all of them - it is rendered whole, with no per-section cap.")


def handler(section=None, recipe=None) -> dict:
    """See TOOL_DESCRIPTION."""
    wanted, refusal = _SECTION.resolve(section)
    if refusal:
        return error(refusal)
    wanted_recipe, refusal = _RECIPE.resolve(recipe)
    if refusal:
        return error(refusal)
    if wanted and wanted_recipe:
        return error(f"Ask for one or the other: section='{wanted}' returns that section's rules, "
                     f"recipe='{wanted_recipe}' returns that one recipe. Call twice.")

    try:
        doc, sha256 = loader.load()
    except loader.GuidanceUnavailable as exc:
        return error(str(exc))

    ids = loader.section_ids(doc)
    kernel = loader.find_section(doc, loader.KERNEL)
    kernel_rules = list((kernel or {}).get("rules") or [])
    result = {"guidance_id": doc.get("guidance_id"), "title": doc.get("title"), "sha256": sha256,
              "resource_uri": resources.uri_for(doc.get("guidance_id"))}

    if wanted_recipe:
        rec = loader.find_recipe(doc, wanted_recipe)
        if rec is None:
            carried = [r.get("id") for r in loader.recipes(doc)]
            return error(f"The packaged guidance document carries no recipe '{wanted_recipe}'. It "
                         "carries: " + (", ".join(str(i) for i in carried) or "none") + ".")
        result.update({"recipe": rec, "kernel": kernel_rules, "note": RECIPE_NOTE})
        return ok(result)

    if not wanted:
        result.update({"section": None,
                       "kernel": kernel_rules,
                       "sections": loader.section_index(doc),
                       "recipes": loader.recipe_map(doc),
                       "scenarios": list(doc.get("scenarios") or []),
                       "next_sections": ids,
                       "note": INDEX_NOTE})
        return ok(result)

    sec = loader.find_section(doc, wanted)
    if sec is None:
        return error(f"The packaged guidance document carries no section '{wanted}'. It carries: "
                     + ", ".join(str(i) for i in ids) + ".")

    rules = list(sec.get("rules") or [])
    shown = rules[:loader.MAX_SECTION_RULES]
    result.update({"section": wanted,
                   "section_title": sec.get("title"),
                   "use_when": sec.get("use_when"),
                   "rule_count": len(shown),
                   "rules": shown,
                   "recipe_index": loader.recipe_index(sec),
                   "next_sections": [i for i in ids if i != wanted],
                   "note": SECTION_NOTE})
    if wanted != loader.KERNEL:
        result["kernel"] = kernel_rules
    if len(rules) > loader.MAX_SECTION_RULES:
        result["truncated"] = True
        result["rule_total"] = len(rules)
        result["note"] = SECTION_NOTE + TRUNCATED_NOTE
    return ok(result)


TOOL_DESCRIPTION = (
    "Call with no arguments first for the index and five kernel rules. Use section=<id> for a "
    "section's rules or recipe=<id> for one recipe; both carry the kernel habits."
)

tool = (
    Tool.create_simple(name="sys_get_guidance", description=TOOL_DESCRIPTION)
    .add_input_property(*_SECTION.as_property())
    .add_input_property(*_RECIPE.as_property())
    .strict_schema()
)
item = Item.create_tool_item(tool=tool, write="read", handler=handler, run_on_main_thread=False)


def register_tool():
    register(item)
