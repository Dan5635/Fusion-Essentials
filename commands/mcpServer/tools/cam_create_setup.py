# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Create a CAM (Manufacture) setup on a part: pick an operation type and the bodies to machine (or
default to every body in the root component), producing a new Setup ready for cam_apply_template /
cam_create_operation."""

import adsk.core
import adsk.cam
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import apply_rename, ok, error, safe
from ._cam_common import (get_cam, machine_kinds, machine_label, resolve_machine,
                          resolve_print_setting, setup_names)
from . import _cam_additive
from . import _common
from . import _inputs

app = adsk.core.Application.get()

_OP_TYPES = {"milling": "MillingOperation", "turning": "TurningOperation",
             "cutting": "JetOperation", "additive": "AdditiveOperation"}

_OP_TYPE = _inputs.Choice("operation_type", options=list(_OP_TYPES), default="milling")

# The one operation type whose setup carries a machine and a print setting on its INPUT.
_ADDITIVE = "additive"
_ADDITIVE_KIND = "additive"      # the machine_kinds label an additive machine must answer to
# models: bodies (handle/name) OR component occurrences (name); omitted -> all root bodies.
# Setup.models accepts an Occurrence, a BRepBody or a MeshBody. Measured: an OCCURRENCE keeps that
# selection when the component's contents are replaced, and the setup stays valid.
_MODELS = _inputs.TargetRefList("models", required=False,
                                description="Omit = every root-component body.")
_FLATS = _inputs.BodyRefList("flat_patterns", kind="solid", required=False,
                            description="Folded sheet source bodies.")


def _flat_models(design, references):
    """Resolve folded source bodies to verified flat bodies for a cutting setup."""
    sources, why = _FLATS.resolve(references)
    if why:
        return None, None, why
    flat_bodies, rows, seen = [], [], set()
    root = safe(lambda: design.rootComponent)
    for body in sources:
        comp = safe(lambda body=body: body.parentComponent)
        label = safe(lambda body=body: body.name) or "?"
        if comp is None or _common.same_component(
                safe(lambda comp=comp: comp.parentDesign.rootComponent), root) is not True:
            return None, None, f"flat_patterns body '{label}' is not local to the active design."
        if safe(lambda body=body: body.isSheetMetal) is not True:
            return None, None, f"flat_patterns body '{label}' is not verified sheet metal."
        flat = safe(lambda comp=comp: comp.flatPattern)
        if flat is None:
            return None, None, (f"flat_patterns body '{label}' has no flat pattern. "
                                "Use sheet_create_flat_pattern first.")
        source = safe(lambda flat=flat: flat.foldedBody)
        source_key, body_key = _common.native_identity(source), _common.native_identity(body)
        if source_key is None or source_key != body_key:
            return None, None, f"flat_patterns body '{label}' is not the source of its component flat pattern."
        if body_key in seen:
            return None, None, f"flat_patterns repeats body '{label}'; list each folded source once."
        seen.add(body_key)
        developed = safe(lambda flat=flat: flat.flatBody)
        if developed is None or safe(lambda developed=developed: developed.isSolid) is not True:
            return None, None, f"flat_patterns body '{label}' has no verified solid flat body."
        if _common.native_identity(developed) is None:
            return None, None, f"flat_patterns body '{label}' flat identity could not be read."
        flat_bodies.append(developed)
        rows.append({"component": safe(lambda comp=comp: comp.name), "folded_body": label,
                     "flat_body": safe(lambda developed=developed: developed.name)})
    return flat_bodies, rows, None


def setup_name_clash(cam, want, current=""):
    """The refusal for a name setups already answer to, shared by the create and the rename arm.
    None when the name is free, empty, or already the caller's own (`current`)."""
    want = (want or "").strip()
    if not want or want.lower() == (current or "").strip().lower():
        return None
    taken = [n for n in setup_names(cam) if (n or "").lower() == want.lower()]
    if not taken:
        return None
    # Measured: Setup.name dedupes silently rather than refusing - 'LegSetup' with one taken lands
    # 'LegSetup1' - so a taken name is refused here instead of landing unasked-for.
    return (f"{len(taken)} setup(s) already answer to '{want}'. Setup.name dedupes rather than "
            f"refusing, so it would land as something like '{want}1' - a name nothing asked for. "
            "Pick one no setup carries; cam_get lists them.")


def _all_root_bodies(design):
    """Every BRep body in the root component - solid AND surface - the default machining set;
    Setup.models is typed to BRepBody, and a setup does carry a surface body."""
    root = safe(lambda: design.rootComponent)
    return list(_common.iter_collection(safe(lambda: root.bRepBodies) if root else None))


# Measured on 2705.1.15: setups.add of an AdditiveOperation input carrying no machine RAISES
# '3 : Setup creation failed' and the setup count stays where it was, so the machine is asked for
# here instead of leaving that raise for the caller.
_ADDITIVE_NEEDS_MACHINE = (
    "operation_type='additive' needs 'machine' - a printer. Without one setups.add raised "
    "'3 : Setup creation failed' and no setup landed. Pick one "
    "cam_get(include=['machines'], machine_type='additive') lists, then pass its exact name.")

_ADDITIVE_ONLY_FIELD = (
    "'{field}' applies to operation_type='additive' only, and this call asked for '{op}', so "
    "nothing was created.{remedy}")

# Carried by the MACHINE field alone: cam_edit_setup assigns one to a milling or turning setup, and
# there is no such route for a print setting - naming it for those fields would send a caller to a
# call that does not take one.
_MACHINE_AFTER_CREATE = (
    " A milling or turning setup takes its machine through cam_edit_setup(machine=...) after this "
    "call.")


def _additive_machine(request):
    """(machine, its label, None) for an additive 'machine' request, else (None, None, refusal) - the
    shared by-name resolver, plus the capability read that says this machine prints."""
    m_obj, m_label, m_err = resolve_machine(request)
    if m_err:
        return None, None, m_err
    if _ADDITIVE_KIND not in machine_kinds(m_obj):
        kinds = machine_kinds(m_obj)
        return None, None, (
            f"Machine '{m_label}' reads isAdditiveSupported false, so an additive setup cannot be "
            f"built on it (it supports: {', '.join(kinds) or 'nothing this read recognises'}). "
            "cam_get(include=['machines'], machine_type='additive') lists the printers.")
    return m_obj, m_label, None


_DESCRIPTION_WITHOUT_NAME = (
    "'print_setting_description' qualifies 'print_setting' - it picks among the settings that name "
    "answers to - so it does nothing on its own. Pass the name too, or drop it.")


def _additive_fields(op_key, machine, print_setting, print_setting_description):
    """The refusal for a machine/print_setting handed to a SUBTRACTIVE call, for an additive one
    with no machine, or for a qualifier with no name; None when the fields cohere. No library read."""
    for field, value in (("machine", machine), ("print_setting", print_setting),
                         ("print_setting_description", print_setting_description)):
        if (value or "").strip() and op_key != _ADDITIVE:
            return _ADDITIVE_ONLY_FIELD.format(
                field=field, op=op_key,
                remedy=_MACHINE_AFTER_CREATE if field == "machine" else "")
    if op_key == _ADDITIVE and not (machine or "").strip():
        return _ADDITIVE_NEEDS_MACHINE
    if (print_setting_description or "").strip() and not (print_setting or "").strip():
        return _DESCRIPTION_WITHOUT_NAME
    return None


def _additive_inputs(op_key, machine, print_setting, print_setting_description):
    """((machine, label, setting, setting name), None) for the additive arm, else (None, refusal).
    The two LIBRARY resolves, run after the document reads - the field checks above are what a call
    with no CAM product should meet first."""
    if op_key != _ADDITIVE:
        return (None, None, None, None), None
    m_obj, m_label, m_err = _additive_machine(machine)
    if m_err:
        return None, m_err
    if not (print_setting or "").strip():
        return (m_obj, m_label, None, None), None
    setting, s_name, s_err = resolve_print_setting(print_setting, print_setting_description)
    if s_err:
        return None, s_err
    return (m_obj, m_label, setting, s_name), None


_SUBTRACTIVE_NOTE = (
    "Setup created (no operations yet). Add toolpaths with cam_apply_template (a "
    "COMPATIBLE template - a milling setup needs a milling template), then "
    "cam_generate. Be in the Manufacture workspace before generating.")

_ADDITIVE_NOTE = (
    "Additive setup created. It offers the additive strategies - "
    "cam_get(include=['strategies'], setup=...) lists them with the isGenerationAllowed flag - and "
    "cam_create_operation adds one, then cam_generate. Be in the Manufacture workspace before "
    "generating.")

# Appended only where operation_count READ above zero - the seeded rows are the platform's, not
# this call's, and a caller reading 'created' otherwise counts them as its own.
_ADDITIVE_SEEDED = (
    " It is not empty: 'operation_count' is what the platform seeded the setup with.")


def _operation_type_landed(setup, op_key):
    """Whether Setup.operationType reads back the type this call asked for; None where either side
    did not read, which settles nothing."""
    want = getattr(adsk.cam.OperationTypes, _OP_TYPES[op_key], None)
    got = safe(lambda: setup.operationType)
    if want is None or got is None:
        return None
    return got == want


def _additive_readback(setup, m_label, s_name, s_desc):
    """{machine, print_setting, ...} as the CREATED setup reads them, or (None, refusal) when what
    it carries is not what was asked for - a machine that did not take is a failed create, not a
    note. The DESCRIPTION is read back too: where a name answers to several settings it is the only
    thing that says WHICH one landed."""
    applied = machine_label(safe(lambda: setup.machine))
    if not applied or applied != m_label:
        return None, (f"The additive setup landed but Setup.machine reads {applied!r}, not the "
                      f"requested {m_label!r} - it carries a printer this call did not ask for. "
                      "Remove it with cam_delete and retry.")
    row = {"machine": applied}
    if s_name is None:
        return row, None
    carried = safe(lambda: setup.printSetting.name)
    if carried != s_name:
        return None, (f"The additive setup landed but Setup.printSetting reads {carried!r}, not "
                      f"the requested {s_name!r} - it prints with a setting this call did not ask "
                      "for. Remove it with cam_delete and retry.")
    carried_desc = safe(lambda: setup.printSetting.description)
    if s_desc is not None and carried_desc != s_desc:
        return None, (f"The additive setup landed but Setup.printSetting is described "
                      f"{carried_desc!r}, not {s_desc!r} - {s_name!r} names several settings and "
                      "the one that landed is not the one picked. Remove it with cam_delete and "
                      "retry.")
    row["print_setting"] = carried
    row["print_setting_technology"] = safe(lambda: setup.printSetting.technology)
    row["print_setting_description"] = carried_desc
    return row, None


def handler(operation_type: str = "milling", models=None, name: str = "",
            machine: str = "", print_setting: str = "", flat_patterns=None,
            print_setting_description: str = "") -> dict:
    """See TOOL_DESCRIPTION."""
    op_key, oerr = _OP_TYPE.resolve(operation_type)
    if oerr:
        return error(oerr)
    if flat_patterns not in (None, "", []):
        if op_key != "cutting":
            return error(f"flat_patterns applies to operation_type='cutting', not '{op_key}'.")
        if models not in (None, "", []):
            return error("Pass flat_patterns or models, not both; a cutting setup needs one model source.")
    elif op_key == "cutting":
        return error("operation_type='cutting' needs flat_patterns: folded sheet bodies with flat patterns.")
    ferr = _additive_fields(op_key, machine, print_setting, print_setting_description)
    if ferr:
        return error(ferr)

    cam, cam_err = get_cam()
    if cam_err:
        return error(cam_err)

    design, design_refusal = _common.require_design()
    if design_refusal is not None:
        return design_refusal

    additive, aerr = _additive_inputs(op_key, machine, print_setting, print_setting_description)
    if aerr:
        return error(aerr)
    m_obj, m_label, setting, s_name = additive
    # Fusion assigns a print setting its machine cannot use without complaint, so this asks first.
    if setting is not None:
        fits = _cam_additive.setting_fits(setting, m_obj)
        if fits is not True:
            return error(_cam_additive.unfit_refusal(s_name, m_label, fits))

    # A cutting setup consumes each folded source body's native flat body.
    flat_rows = None
    if op_key == "cutting":
        body_list, flat_rows, merr = _flat_models(design, flat_patterns)
        if merr:
            return error(merr)
    elif models not in (None, "", []):
        body_list, merr = _MODELS.resolve(models)
        if merr:
            return error(merr)
    else:
        body_list = _all_root_bodies(design)
    if not body_list:
        return error("No bodies to machine. The root component holds no bodies "
    "- add geometry first, or pass 'models' = body handles/names (a body inside a "
    "sub-component is not in the default set).")

    # The name is refused BEFORE the add, through the same check the rename arm runs: a deduped
    # name would otherwise land silently and the caller would address the setup by the wrong one.
    clash = setup_name_clash(cam, name)
    if clash:
        return error(clash)

    try:
        op_enum = getattr(adsk.cam.OperationTypes, _OP_TYPES[op_key])
        inp = cam.setups.createInput(op_enum)
        inp.models = list(body_list)
        if m_obj is not None:
            inp.machine = m_obj
        if setting is not None:
            inp.printSetting = setting
        setup = cam.setups.add(inp)
    except Exception as e:
        remedy = (" Switch the workspace to Design and back to Manufacture with "
                  "view_switch_workspace, then retry."
                  if op_key == "cutting" and
                  "Used entity could not be matched in manufacturing tree" in str(e) else "")
        return error(f"Failed to create the {op_key} setup: {e}{remedy}")
    if not setup:
        return error("Setup creation returned nothing.")
    # The setup has landed, so a declined or deduped name is a DISCLOSURE, not a failed create -
    # what the payload publishes is the name Setup.name reads back.
    new_name, rename_warning = apply_rename(setup, name)
    if new_name:
        landed = any(safe(lambda s=s: s.name) == new_name
                     for s in _common.iter_collection(safe(lambda: cam.setups)))
        if not landed:
            return error(f"setups.add returned '{new_name}' but it does not appear when the setups "
                         "are re-listed - the setup did not land.")

    if flat_rows is not None:
        landed_collection = safe(lambda: setup.models)
        landed_models = (list(landed_collection) if isinstance(landed_collection, (list, tuple))
                         else list(_common.iter_collection(landed_collection))
                         if landed_collection is not None else [])
        requested_keys = [_common.native_identity(b) for b in body_list]
        landed_keys = [_common.native_identity(b) for b in landed_models]
        if (len(landed_keys) != len(requested_keys) or None in landed_keys
                or set(landed_keys) != set(requested_keys)):
            return error(f"Cutting setup '{new_name}' remains, but its selected models did not "
                         "read back as the requested flat bodies. Inspect cam_get(include=['setups']) "
                         "before retrying.")

    kind = _operation_type_landed(setup, op_key)
    if kind is False:
        return error(f"setups.add returned a setup for '{op_key}' but Setup.operationType reads "
                     f"back {safe(lambda: setup.operationType)!r}, which is not the type this call "
                     "asked for. Remove it with cam_delete and retry.")

    result = {
        "created": True,
        "setup_name": new_name,
        "operation_type": op_key,
        "model_count": len(body_list),
    "models": [safe(lambda b=b: b.name) for b in body_list],
    "operation_count": safe(lambda: setup.allOperations.count, 0),   # total incl. foldered ops
    "note": _ADDITIVE_NOTE if op_key == _ADDITIVE else _SUBTRACTIVE_NOTE,
    }
    if flat_rows is not None:
        result["flat_sources"] = flat_rows
        result["flat_models_verified"] = True
        result["note"] = ("Cutting setup uses the flat bodies of the named folded sources. "
                          "Use cam_create_operation(strategy='profile2d') for a cutting path.")
    if op_key == _ADDITIVE and (result["operation_count"] or 0) > 0:
        # Said only where the count READ above zero: the platform seeds this arm, and the sentence
        # would otherwise call a setup non-empty on a count of 0.
        result["note"] += _ADDITIVE_SEEDED
    if kind is None:
        result["operation_type_checked"] = False   # absent = Setup.operationType read it back
    if op_key == _ADDITIVE:
        carried, cerr = _additive_readback(
            setup, m_label, s_name,
            safe(lambda: setting.description) if setting is not None else None)
        if cerr:
            return error(cerr)
        result.update(carried)
    if rename_warning:
        result["rename_warning"] = rename_warning
    return ok(result)


TOOL_DESCRIPTION = ("Create a CAM setup. Cutting uses flat_patterns; add paths with cam_create_operation.")

tool = (
    Tool.create_simple(name="cam_create_setup", description=TOOL_DESCRIPTION)
    .add_input_property(_OP_TYPE.name, _OP_TYPE.schema())
    .add_input_property(_MODELS.name, _MODELS.schema())
    .add_input_property(*_FLATS.as_property())
    .add_input_property("name", {"type": "string"})
    .add_input_property("machine", {"type": "string",
            "description": "'vendor|model'. Required for additive."})
    .add_input_property("print_setting", {"type": "string",
            "description": "Additive only."})
    .add_input_property("print_setting_description", {"type": "string",
            "description": "Qualifies a shared name."})
    .strict_schema()
)

item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    # The name apply_rename reads back off Setup.name is looked for in the setups RE-LISTED off the
    # CAM product, and a name the listing does not carry is an error, not a created=true.
    verification=Verification(
        kind="inline",
        evidence_test="tests/unit/test_cam_create_setup.py::TestOperationType"
                      "::test_phantom_setup_that_never_lands_bites",
        rung="value"))


def register_tool():
    register(item)
