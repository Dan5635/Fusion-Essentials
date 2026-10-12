# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: create a new empty component occurrence in the active design.

Prerequisite for building an assembly: the modelling tools build into the active component, so
create one component per part, activate it, then model into it (sketch_create / extrude). WRITES.
"""

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, iter_collection, ok, safe, scale
from . import _common
from . import _inputs

app = adsk.core.Application.get()

# parent: nest the new component INSIDE an existing occurrence's component (occurrences.addNewComponent
# on the PARENT component - verified live). Omitted = the root component (the back-compat default).
_PARENT = _inputs.OccurrenceRef("parent", required=False)


def _ensure_multi_component_intent(design):
    """Promote a PART-intent design to HYBRID so it accepts components; a note, or None."""
    T = adsk.fusion.DesignIntentTypes
    intent = safe(lambda: design.designIntent)
    if intent != T.PartDesignIntentType:
        return None      # ASSEMBLY / HYBRID already accept components; leave the intent as set
    try:
        # HYBRID, not ASSEMBLY: it allows several internal components AND keeps modeling enabled.
        design.designIntent = T.HybridDesignIntentType
    except Exception:
        return None      # let addNewComponent raise its own error below
    if safe(lambda: design.designIntent) == T.HybridDesignIntentType:
        return ("design intent was PART (one-component-only); promoted to HYBRID so multiple "
                "components are allowed while modeling stays enabled.")
    return None


def _apply_part_number(component, part_number_input, final_name):
    """(landed_part_number, warning_or_None) - explicit input wins, else name replaces a non-name
    default; a raise or read-back mismatch is a disclosure, never a failed create."""
    requested = (part_number_input or "").strip()
    current = safe(lambda: component.partNumber)
    desired = requested if requested else (final_name if current != final_name else None)
    if desired is None:
        return current, None
    try:
        component.partNumber = desired
    except Exception as e:
        return current, f"part_number '{desired}' could not be set: {e} (component still created)."
    landed = safe(lambda: component.partNumber)
    if landed != desired:
        return landed, (f"part_number '{desired}' did not land - component reads '{landed}' "
                        "(component still created).")
    return landed, None


def _adopt_existing_rule(design, new_rule, before_rules, occ):
    """Merge a freshly-copied same-named design rule into the pre-existing one; (flags, error_or_none)."""
    if before_rules is None:
        return {"rule_census_unread": True}, None      # unread, not empty - adoption skipped, not guessed
    name = safe(lambda: new_rule.name)
    if not name or any(r == new_rule for r in before_rules):
        return {}, None      # not a fresh copy (or unnamed) - nothing to merge
    same_name_before = [r for r in before_rules
                        if (safe(lambda r=r: r.name) or "").lower() == name.lower()]
    if not same_name_before:
        return {"rule_added": True}, None
    if len(same_name_before) > 1:
        return {"rule_name_ambiguous": name}, None
    existing = same_name_before[0]
    before_count = len(before_rules)
    try:
        occ.component.activeSheetMetalRule = existing
    except Exception as e:
        return {}, (f"Sheet-metal occurrence '{safe(lambda: occ.name)}' was created, but adopting "
                    f"existing rule '{name}' failed: {e}. It still carries rule "
                    f"'{safe(lambda: occ.component.activeSheetMetalRule.name)}'; repair with sheet_edit_rule.")
    readback = safe(lambda: occ.component.activeSheetMetalRule)
    if readback is None or readback != existing:
        got = safe(lambda: readback.name) if readback is not None else None
        return {}, (f"Sheet-metal occurrence '{safe(lambda: occ.name)}' was created, but its active "
                    f"rule did not adopt '{name}' (reads '{got}'). Repair with sheet_edit_rule.")
    try:
        deleted = new_rule.deleteMe()
    except Exception as e:
        return {}, (f"Sheet-metal occurrence '{safe(lambda: occ.name)}' now carries existing rule "
                    f"'{name}', but its duplicate copy did not delete: {e}. Repair with sheet_edit_rule "
                    "or remove the stray rule.")
    after = safe(lambda: design.designSheetMetalRules)
    after_count = safe(lambda: after.count) if after is not None else None
    if deleted is not True or after_count != before_count:
        return {}, (f"Sheet-metal occurrence '{safe(lambda: occ.name)}' now carries existing rule "
                    f"'{name}', but its duplicate copy did not delete (deleteMe={deleted}, design "
                    f"rule count {after_count}, expected {before_count}). Repair with sheet_edit_rule.")
    return {"rule_adopted_existing": True, "rule_copy_deleted": True}, None


def handler(name: str = "", x: float = 0.0, y: float = 0.0, z: float = 0.0,
            units: str = "mm", activate: bool = False,
            rotate_deg: float = 0.0, rotate_axis: str = "z", parent: str = "",
            part_number: str = "", sheet_metal: bool = False) -> dict:
    """See TOOL_DESCRIPTION."""
    k = scale(units)
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")

    # parent: resolve the occurrence to nest INSIDE (its component receives the new child). Omitted =
    # root. OccurrenceRef refuses an ambiguous name instead of grabbing the wrong instance.
    parent_occ = None
    if (parent or "").strip():
        parent_occ, perr = _PARENT.resolve(parent)
        if perr:
            # The root is no occurrence, so no value of 'parent' names it; a miss says how to get it.
            if _inputs.OCCURRENCE_MISS in perr:
                perr += " To create at the root, omit 'parent'."
            return error(perr)

    if sheet_metal and parent_occ is not None:
        return error("sheet_metal=true has only been verified at root; omit parent and create a root sheet-metal component.")

    import math
    matrix = adsk.core.Matrix3D.create()
    if rotate_deg:
        axis_vec = _inputs._AXIS_VECS.get((rotate_axis or "z").strip().lower())
        if not axis_vec:
            return error(f"Unknown rotate_axis '{rotate_axis}'. Use x, y, or z.")
        # Rotate about the world origin; the translation assigned below places the component.
        matrix.setToRotation(math.radians(float(rotate_deg)),
                             adsk.core.Vector3D.create(*axis_vec), adsk.core.Point3D.create(0, 0, 0))
    if x or y or z:
        matrix.translation = adsk.core.Vector3D.create(float(x) * k, float(y) * k, float(z) * k)

    # A fresh (Part-intent) design refuses addNewComponent - promote it to Hybrid first so the build
    # can hold multiple components. Report the promotion if it happened.
    intent_note = _ensure_multi_component_intent(design)

    # ROOT (default) or NESTED: addNewComponent on the parent occurrence's COMPONENT nests the new
    # component inside it (verified live: the child then reads a nested fullPathName). Omitted = root.
    host_occurrences = (safe(lambda: parent_occ.component.occurrences) if parent_occ is not None
                        else safe(lambda: design.rootComponent.occurrences))
    if host_occurrences is None:
        return error("Could not access the target occurrences collection to create the component.")
    # addNewSheetMetalComponent copies the library rule only when the design's same-named rule no
    # longer matches the library default; otherwise it hands the existing rule back unchanged - the
    # before-census tells the two apart. None (not []) marks an UNREAD census, not an empty one.
    before_rules = []
    if sheet_metal:
        before_collection = safe(lambda: design.designSheetMetalRules)
        before_rules = list(iter_collection(before_collection)) if before_collection is not None else None
    try:
        occ = (host_occurrences.addNewSheetMetalComponent(matrix) if sheet_metal
               else host_occurrences.addNewComponent(matrix))
    except Exception as e:
        return error(f"Could not create component: {e}")
    if not occ:
        return error("Component creation returned nothing.")

    rule_flags = {}
    if sheet_metal:
        active_rule = safe(lambda: occ.component.activeSheetMetalRule)
        if active_rule is None:
            return error(f"Sheet-metal occurrence '{safe(lambda: occ.name)}' was created, but its active "
                         "rule did not read back. Inspect that occurrence with sheet_get(include=['components']) "
                         "before modeling into it.")
        rule_flags, rule_err = _adopt_existing_rule(design, active_rule, before_rules, occ)
        if rule_err:
            return error(rule_err)

    _final_name, name_warning = _common.apply_rename(occ.component, name)
    part_number_value, part_number_warning = _apply_part_number(occ.component, part_number,
                                                                 _final_name)

    # A component created via a sub-component's occurrences is NATIVE to it, so its own fullPathName
    # shows only the child; the proxy into the chosen parent's context carries the nested path.
    # Fusion joins fullPathName segments with '+', which is the fallback's shape.
    read_occ = occ
    if parent_occ is not None:
        proxy = safe(lambda: occ.createForAssemblyContext(parent_occ))
        if proxy is not None:
            read_occ = proxy
    full_path = safe(lambda: read_occ.fullPathName)
    if parent_occ is not None and read_occ is occ:
        pp, cn = safe(lambda: parent_occ.fullPathName), safe(lambda: occ.name)
        if pp and cn:
            full_path = f"{pp}+{cn}"

    activated = False
    if activate:
        activated = bool(safe(lambda: read_occ.activate(), False))

    # The FIRST component created in an empty design comes back with isGroundToParent True and the
    # next one False; it decides which member a joint drive displaces, so it is disclosed at create
    # time. read_flag keeps an unreadable flag None instead of coercing it to False.
    ground_to_parent = _common.read_flag(lambda: occ.isGroundToParent)

    out = {
        "created": True,
        "sheet_metal": sheet_metal,
        "active_sheet_metal_rule": (safe(lambda: occ.component.activeSheetMetalRule.name)
                                    if sheet_metal else None),
        "occurrence": safe(lambda: occ.name),
        "component": safe(lambda: occ.component.name),
        "full_path": full_path,               # nested path shows the parent when 'parent' was given
        "nested_in": safe(lambda: parent_occ.fullPathName) if parent_occ is not None else None,
        "position": {"x": x, "y": y, "z": z} if (x or y or z) else "origin",
        "rotate_deg": float(rotate_deg or 0.0),
        "rotate_axis": (rotate_axis or "z").lower() if rotate_deg else None,
        "units": units,
        "activated": activated,
        "ground_to_parent": ground_to_parent,
        "part_number": part_number_value,
        "note": (("Empty sheet-metal component created" if sheet_metal else "Empty component created") + (f" nested inside '{safe(lambda: parent_occ.fullPathName)}'"
                 if parent_occ is not None else " at root")
                 + (". Model a constant-thickness solid, then use sheet_convert and verify "
                    "isSheetMetal." if sheet_metal else
                    ". Activate it (or it is active) then model into it with sketch_create / extrude; "
                    "ground / joint it as an assembly part.")),
    }
    if ground_to_parent:
        out["note"] += (" ground_to_parent reads TRUE on this new occurrence - it is locked to its "
                        "parent (the FIRST component of an empty design lands locked; the next one "
                        "does not), so a joint drive displaces the OTHER member instead of this "
                        "one. assembly_ground(ground_to_parent=false) releases it.")
    if rule_flags.get("rule_name_ambiguous"):
        out["note"] += (f" Another design rule named '{rule_flags['rule_name_ambiguous']}' now "
                        "exists; read sheet_get(include=['rules']) for its '#<n>' ref and resolve "
                        "with sheet_edit_rule.")
    if rule_flags.get("rule_census_unread"):
        out["note"] += (" The design's prior sheet-metal rules could not be read, so adoption was "
                        "skipped; read sheet_get(include=['rules']) to check for a duplicate.")
    out.update(rule_flags)
    if name_warning:
        out["name_warning"] = name_warning
    if part_number_warning:
        out["part_number_warning"] = part_number_warning
    if intent_note:
        out["design_intent_promoted"] = intent_note
    return ok(out)


TOOL_DESCRIPTION = (
"Create a new EMPTY component occurrence, at root unless 'parent' nests it. Its placement composes "
"with the component-local coordinates you then sketch in."
)

tool = (
    Tool.create_simple(name="model_create_component", description=TOOL_DESCRIPTION)
    .add_input_property("name", {"type": "string"})
    .add_input_property("part_number", {"type": "string",
            "description": "Left unchanged when omitted; defaults to 'name' if Fusion's own "
                            "default (a creation timestamp) is still on the component."})
    .add_input_property("x", {"type": "number", "description": "Placement X, in 'units'."})
    .add_input_property("y", {"type": "number"})
    .add_input_property("z", {"type": "number"})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_input_property("activate", {"type": "boolean",
            "description": "Make it the active edit target."})
    .add_input_property("rotate_deg", {"type": "number",
            "description": "Orientation about 'rotate_axis'."})
    .add_input_property(*_inputs.frame_axis("rotate_axis", default="z").as_property())
    .add_input_property(*_PARENT.as_property())
    .add_input_property("sheet_metal", {"type": "boolean",
            "description": "Sheet-metal component at root; reuses a same-named rule."})
    .strict_schema()
)
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="effect",
        rung="value",
        evidence_test="tests/unit/test_model_create_component.py::TestCreateComponent"
                      "::test_rejected_rename_surfaces_warning_not_false_success"))


def register_tool():
    register(item)
