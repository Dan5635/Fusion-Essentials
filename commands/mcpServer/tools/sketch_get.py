# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: read sketches by zoom level - a summary list of every sketch in the design,
or ONE sketch's overview / full X-ray through the _sketch_detail engine. Read-only.
"""

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from ._sketch_detail import (DEFERRED_NOTE, _ENTITY_PAGE_DEFAULT, _XRAY_CAP,
                             _detail_engine, _sketch_summary)
from . import _common
from . import _inputs

app = adsk.core.Application.get()


def _shared_component_names(design) -> set:
    """The lower-cased component names carried by MORE THAN ONE component."""
    counts = {}
    for comp in _common.all_components(design):
        nm = (safe(lambda c=comp: c.name) or "").strip().lower()
        if nm:
            counts[nm] = counts.get(nm, 0) + 1
    return {nm for nm, n in counts.items() if n > 1}


# Rows PAGED design-wide, so a sketch-dense document cannot flood the list however its sketches are
# spread over components. max_results is the page size - the same knob and the same default shape
# design_get's tree children use.
_LIST_CAP = 50

_LIST_CAP_NOTE = ("Sketches are paged {cap} per read; 'sketch_count' is the true total. Raise "
                  "max_results for the rows past the page, narrow with component='<name or "
                  "occurrence path>', or read one sketch by sketch_get(sketch_name='<name>').")


def _list_sketches(component: str = "", max_results: int = 0) -> dict:
    """List the design's sketches, each tagged with its owning component, max_results rows per read;
    'component' narrows the list, taking the same component name / occurrence path / handle the
    by-name read scopes by. Two components can wear one NAME, so the rows they own are identical -
    top-level 'placements' carries the occurrence paths that tell them apart."""
    design, design_refusal = _common.require_design()
    if design_refusal is not None:
        return design_refusal
    comps, scope_error = _detail_engine().scope_components(design, component)
    if scope_error:
        return error(scope_error)
    try:
        cap = max(1, int(max_results)) if max_results else _LIST_CAP
    except (TypeError, ValueError):
        cap = _LIST_CAP
    sketches, total = [], 0
    try:
        for comp in comps:
            comp_name = safe(lambda c=comp: c.name)
            for sk in _common.iter_collection(safe(lambda c=comp: c.sketches)):
                total += 1
                # The walk runs on PAST the page so sketch_count stays the count of what is there,
                # never the count of what fitted.
                if len(sketches) >= cap:
                    continue
                rec = _sketch_summary(sk)
                rec["component"] = comp_name
                sketches.append(rec)
    except Exception as e:
        return error(f"Could not read sketches: {e}")
    withheld = total > len(sketches)
    payload = {"sketch_count": total, "sketches": sketches}
    if withheld:
        payload["returned"] = len(sketches)
        payload["truncated"] = True
    # Only the ambiguous names THIS RESPONSE's rows carry earn the placement block.
    shared = _shared_component_names(design)
    listed = [r["component"] for r in sketches]
    ambiguous = sorted({n for n in listed if (n or "").strip().lower() in shared})
    in_answer = {(n or "").strip().lower() for n in ambiguous}
    placements = [{"path": p, "component": safe(lambda c=c: c.name)}
                  for p, c in _common.component_placements(design)
                  if (safe(lambda c=c: c.name) or "").strip().lower() in in_answer]
    if ambiguous and placements:
        payload["placements"] = placements
        payload["note"] = (
            "More than one component wears the same name here (" + ", ".join(ambiguous) + "), so a "
            "row's 'component' does not identify which one holds it, and this list does not tell "
            "those rows apart. 'placements' lists every occurrence path placing a component of one "
            "of the names just listed, and no others; passing one back as 'component' reads THAT "
            "component's sketches.")
    if withheld:
        payload["note"] = (payload.get("note", "") + " " + _LIST_CAP_NOTE.format(cap=cap)).strip()
    if any(r.get("compute_deferred") for r in sketches):
        payload["note"] = (payload.get("note", "") + " " + DEFERRED_NOTE).strip()
    return ok(payload)


def handler(sketch_name: str = "", include_entities: bool = False, units: str = "mm",
            component: str = "", max_results: int = 0, entity_offset: int = 0) -> dict:
    """List sketches or read one sketch's overview or entity X-ray."""
    if type(entity_offset) is not int or entity_offset < 0:
        return error(f"'entity_offset' must be a nonnegative integer, got {entity_offset!r}.")
    if entity_offset and (not (sketch_name or "").strip() or not include_entities):
        return error("'entity_offset' requires sketch_name and include_entities=true.")
    if (sketch_name or "").strip():
        if include_entities and (type(max_results) is not int or max_results < 0):
            return error(f"'max_results' must be a nonnegative integer for an entity X-ray, got {max_results!r}.")
        return _detail_engine().handler(sketch_name=sketch_name, component=component,
                                        include_entities=include_entities, units=units,
                                        entity_offset=entity_offset, max_results=max_results)
    return _list_sketches(component, max_results)


TOOL_DESCRIPTION = (
    "Read sketches, curves, constraints and profile handles for model_extrude."
)
tool = (
    Tool.create_simple(name="sketch_get", description=TOOL_DESCRIPTION)
    .add_input_property("sketch_name", {"type": "string"})
    .add_input_property("max_results", {"type": "integer",
            "description": f"List default {_LIST_CAP}; X-ray default {_ENTITY_PAGE_DEFAULT} per entity collection, cap {_XRAY_CAP}."})
    .add_input_property("component", {"type": "string",
            "description": "Name, occurrence path or handle."})
    .add_input_property("include_entities", {"type": "boolean",
            "description": "Entity X-ray."})
    .add_input_property("entity_offset", {"type": "integer", "minimum": 0,
            "description": "Skip rows per entity collection; named X-ray only."})
    .add_input_property(*_inputs.UNITS.as_property())
    .strict_schema()
)
item = Item.create_tool_item(tool=tool, write="read", handler=handler,
                             run_on_main_thread=True)


def register_tool():
    register(item)
