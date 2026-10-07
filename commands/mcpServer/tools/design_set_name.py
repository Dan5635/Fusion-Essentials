# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: rename a target, feature, joint, Joint Origin, or construction datum. WRITES."""

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, iter_collection, ok, safe
from . import _common
from . import _inputs
from . import _joints
from . import _outputs

# The renameable kinds: a FACE has no name and '' (the whole design) has nothing to rename, so both
# are out of allow=. MeshBody.name is settable and reads back off a fresh meshBodies.item() fetch.
_TARGET = _inputs.TargetRef("target", allow=("body", "mesh", "occurrence", "component"))
_OWNER = _inputs.TargetRef("owner", allow=("component", "occurrence"),
                          collapse_ambiguous_occurrences=True, required=True)
_OCCURRENCE = _inputs.OccurrenceRef("occurrence", allow_root=True, required=True)
_FEATURE = _inputs.FeatureRef("target", required=True)
_JOINT_ORIGIN = _inputs.JointOriginRef("target", native=True, required=True)
_PLANE = _inputs.PlaneRef("target", required=True)
_AXIS = _inputs.AxisRef("target", entity_only=True, required=True)
_POINT = _inputs.PointRef("target", required=True)
_KINDS = ("target", "feature", "joint", "joint_origin", "plane", "axis", "point")

RETURNS = [
    _outputs.ReturnsName("name", of="landed target",
                         consumers=["find_geometry", "design_get"]),
]


def _label(entity, kind):
    """'component X' / 'body X' / 'occurrence Sub:1+Bolt:1' - what the call addressed."""
    if kind == "occurrence":
        return "occurrence '%s'" % (safe(lambda: entity.fullPathName)
                                    or safe(lambda: entity.name) or "?")
    return "%s '%s'" % (kind, safe(lambda: entity.name) or "?")


def _instances_of(design, component):
    """Every occurrence referencing `component` - the instances whose browser name follows a
    component rename."""
    root = safe(lambda: design.rootComponent)
    if root is None:
        return []
    return list(iter_collection(safe(lambda: root.allOccurrencesByComponent(component))))


def _actionable_address(design, entity, owner, kind, owner_address=None, index=None):
    """A unique owner/name address, or a typed token/index when owner names collide."""
    name = safe(lambda: entity.name)
    if kind == "feature":
        return str(index) if index is not None else None
    if kind == "joint" and owner_address:
        return f"{owner_address}:{name}"
    owner_name = safe(lambda: owner.name)
    components = list(iter_collection(safe(lambda: design.allComponents)))
    owners = [candidate for candidate in components
              if safe(lambda candidate=candidate: candidate.name) == owner_name]
    if owner_name and len(owners) > 1:
        token = safe(lambda: entity.entityToken)
        if token:
            return token
        return None
    return f"{owner_name}/{name}" if owner_name and name else None


def _owner_and_name(raw, kind):
    """(owner, local name, error) for a component-qualified construction datum address."""
    if not isinstance(raw, str) or _inputs.is_handle(raw) or "/" not in raw:
        return None, None, f"'{kind}' needs '<component>/<name>' or a find_geometry handle."
    owner_name, _, local_name = raw.partition("/")
    if not owner_name.strip() or not local_name.strip():
        return None, None, f"'{kind}' needs '<component>/<name>' with both parts present."
    resolved, err = _OWNER.resolve(owner_name.strip())
    if err:
        return None, None, err
    owner, owner_kind = resolved
    if owner_kind == "occurrence":
        owner = safe(lambda: owner.component)
        if owner is None:
            return None, None, (f"'{kind}': the occurrence '{owner_name.strip()}' resolved, but its "
                                "component definition could not be read.")
    elif owner_kind != "component":
        return None, None, (f"'{kind}': '{owner_name.strip()}' did not resolve to a component "
                            "definition.")
    return owner, local_name.strip(), None


def _resolve_namespace_target(design, target, kind):
    """(entity, owner, address, error) for one non-default rename namespace."""
    owner_address, index = None, None
    scoped_owner = None
    if kind == "feature":
        resolved, err = _FEATURE.resolve(target)
        if err:
            return None, None, None, err
        entity, _timeline_name = resolved
        owner = safe(lambda: entity.parentComponent)
        index = safe(lambda: entity.timelineObject.index)
        if index is None:
            return None, None, None, "The feature's timeline index could not be read for an actionable address."
    elif kind == "joint":
        owner = None
        local_name = target
        owner_address = None
        if isinstance(target, str) and _inputs.is_handle(target):
            entity, err = _joints.find_joint(design, target)
        elif isinstance(target, str) and ":" in target:
            owner_spec, _, local_name = target.rpartition(":")
            if not owner_spec.strip() or not local_name.strip():
                return None, None, None, "A qualified joint target needs '<occurrence>:<name>'."
            occurrence, err = _OCCURRENCE.resolve(owner_spec.strip())
            if err:
                return None, None, None, err
            root = safe(lambda: design.rootComponent)
            owner = (occurrence if _common.same_component(occurrence, root) is True else
                     safe(lambda: occurrence.component))
            if owner is None:
                return None, None, None, "The joint owner's component could not be read."
            owner_address = owner_spec.strip()
            entity, err = _joints.find_joint(design, local_name, component=owner)
        elif isinstance(target, str) and "/" in target:
            owner, local_name, err = _owner_and_name(target, kind)
            if err:
                return None, None, None, err
            scoped_owner = owner
            entity, err = _joints.find_joint(design, local_name, component=owner)
        else:
            entity, err = _joints.find_joint(design, local_name)
        if err:
            return None, None, None, err
        if entity is None:
            return None, None, None, f"No joint named '{target}'. Use assembly_get to list joints."
        owner = safe(lambda: entity.parentComponent)
    elif kind == "joint_origin":
        if isinstance(target, str) and _inputs.is_handle(target):
            entity, err = _JOINT_ORIGIN.resolve(target)
            owner = safe(lambda: entity.parentComponent) if entity is not None else None
        elif isinstance(target, str) and "/" in target:
            owner, local_name, err = _owner_and_name(target, kind)
            if err:
                return None, None, None, err
            scoped_owner = owner
            entity, err = _JOINT_ORIGIN.resolve(local_name, component=owner)
        else:
            entity, err = _JOINT_ORIGIN.resolve(target)
            owner = None
        if err:
            return None, None, None, err
        owner = safe(lambda: entity.parentComponent)
    elif kind == "plane":
        if isinstance(target, str) and _inputs.is_handle(target):
            entity, err = _PLANE.resolve(target)
            owner = safe(lambda: entity.component) if entity is not None else None
        elif isinstance(target, str) and "/" in target:
            owner, local_name, err = _owner_and_name(target, kind)
            if err:
                return None, None, None, err
            scoped_owner = owner
            entity, err = _PLANE.resolve(local_name, component=owner)
        else:
            return None, None, None, "A plane name needs '<component>/<name>'; pass a find_geometry handle for a direct reference."
        if err:
            return None, None, None, err
        if "ConstructionPlane" not in (safe(lambda: entity.objectType) or type(entity).__name__):
            return None, None, None, "A plane rename needs a construction-plane target."
        owner = safe(lambda: entity.component) or owner
    elif kind == "axis":
        if isinstance(target, str) and _inputs.is_handle(target):
            resolved, err = _AXIS.resolve(target)
            owner = None
        elif isinstance(target, str) and "/" in target:
            owner, local_name, err = _owner_and_name(target, kind)
            if err:
                return None, None, None, err
            scoped_owner = owner
            resolved, err = _AXIS.resolve(local_name, component=owner)
        else:
            return None, None, None, "An axis name needs '<component>/<name>'; pass a find_geometry handle for a direct reference."
        if err:
            return None, None, None, err
        if not isinstance(resolved, tuple) or len(resolved) != 2 or resolved[0] != "edge":
            return None, None, None, "An axis rename needs a construction-axis target."
        entity = resolved[1]
        if "ConstructionAxis" not in (safe(lambda: entity.objectType) or type(entity).__name__):
            return None, None, None, "An axis rename needs a construction-axis target."
        owner = safe(lambda: entity.component) or owner
    elif kind == "point":
        if isinstance(target, str) and _inputs.is_handle(target):
            entity, err = _POINT.resolve(target)
            owner = safe(lambda: entity.component) if entity is not None else None
        elif isinstance(target, str) and "/" in target:
            owner, local_name, err = _owner_and_name(target, kind)
            if err:
                return None, None, None, err
            scoped_owner = owner
            entity, err = _POINT.resolve(local_name, owner_component=owner)
        else:
            return None, None, None, "A point name needs '<component>/<name>'; pass a find_geometry handle for a direct reference."
        if err:
            return None, None, None, err
        if "ConstructionPoint" not in (safe(lambda: entity.objectType) or type(entity).__name__):
            return None, None, None, "A point rename needs a construction-point target."
        owner = safe(lambda: entity.component) or owner
    else:
        return None, None, None, f"Unknown rename kind '{kind}'. Use {', '.join(_KINDS)}."
    if scoped_owner is not None:
        actual_owner = (safe(lambda: entity.parentComponent)
                        if kind in ("joint", "joint_origin")
                        else safe(lambda: entity.component))
        if actual_owner is None:
            remedy = (" Use design_get(include=['tree']) to confirm its component owner, then "
                      "retry with '<component>/<name>'." if kind == "joint_origin" else "")
            return None, None, None, (f"The {kind.replace('_', ' ')} resolved under the requested "
                                      f"component, but its actual owner could not be read.{remedy}")
        same_owner = _common.same_component(actual_owner, scoped_owner)
        if same_owner is None:
            return None, None, None, (f"The {kind.replace('_', ' ')} owner could not be compared "
                                      "with the requested component definition.")
        if not same_owner:
            return None, None, None, (f"The resolved {kind.replace('_', ' ')} belongs to a different "
                                      "component than the requested owner.")
        owner = actual_owner
    if owner is None:
        remedy = (" Use design_get(include=['tree']) to confirm its component owner, then "
                  "retry with '<component>/<name>'." if kind == "joint_origin" else "")
        return None, None, None, (f"The {kind.replace('_', ' ')}'s owning component could not be "
                                  f"read.{remedy}")
    address = _actionable_address(design, entity, owner, kind, owner_address, index)
    if address is None:
        return None, None, None, f"The {kind.replace('_', ' ')} has no unique owner-qualified address; use a handle or timeline index."
    return entity, owner, address, None


def handler(target: str = "", new_name: str = "", kind: str = "target") -> dict:
    """Rename the resolved target and publish the name Fusion actually landed. WRITES."""
    want = (new_name or "").strip()
    if not want:
        return error("'new_name' is required - a non-empty name to give the target.")
    if kind not in _KINDS:
        return error(f"Unknown rename kind '{kind}'. Use {', '.join(_KINDS)}.")

    design = _common.design()
    if not design:
        return error("No active design. Open a document first (see doc_open / doc_new).")

    owner = None
    address = None
    if kind == "target":
        resolved, terr = _TARGET.resolve(target)
        if terr:
            return error(terr)
        entity, kind = resolved
        addressed = _label(entity, kind)
    else:
        entity, owner, address, terr = _resolve_namespace_target(design, target, kind)
        if terr:
            return error(terr)
        addressed = f"{kind} '{address}'"
    occurrence = None
    if kind == "occurrence":
        # An occurrence has no name of its own - its browser name is the COMPONENT's name plus the
        # instance number - so an occurrence target renames the component behind it, and every other
        # instance of that component follows.
        occurrence = entity
        entity = safe(lambda: occurrence.component)
        if entity is None:
            return error(f"Could not reach the component behind {addressed} to rename it.")
        kind = "component"

    # Renaming the ROOT component raises '3 : root component name cannot be changed', and that raise
    # aborts the enclosing transaction even when caught, so it must never be attempted. The check is
    # same_component, never `is`: component identity is not stable across reads.
    if kind == "component":
        is_root = _common.same_component(entity, safe(lambda: design.rootComponent))
        if is_root is True:
            return error(f"'{safe(lambda: entity.name)}' is the ROOT component and Fusion refuses to "
                         "rename it ('root component name cannot be changed') - its name IS the "
                         "document name. Rename the document instead (doc_save_as), or target a "
                         "body/sub-component.")
        if is_root is None:
            # The guard exists because the platform's refusal aborts the enclosing transaction even
            # when caught, so an unproven not-root cannot be attempted: the rename is refused here
            # instead of risking that abort.
            return error(f"Whether '{addressed}' is this design's ROOT component could not be read, "
                         "and the platform's refusal to rename the root aborts the enclosing "
                         "transaction even when it is caught - so this rename was not attempted. "
                         "Target a body or a sub-component by name, or rename the document with "
                         "doc_save_as.")

    previous = safe(lambda: entity.name)
    instances = _instances_of(design, entity) if kind == "component" else []
    read_occ = occurrence if occurrence is not None else (instances[0] if instances else None)

    if previous == want:
        result = {
            "renamed": True,
            "changed": False,
            "kind": kind,
            "addressed": addressed,
            "previous_name": previous,
            "requested_name": want,
            "name": previous,
            "deduped": False,
            "note": f"{addressed} already holds the name '{want}' - nothing changed.",
        }
        return ok(result)

    try:
        # The MUTATION - not safe-wrapped, so a refusal raises here and is reported instead of
        # being swallowed into a false success.
        entity.name = want
    except Exception as e:
        return error(f"Could not rename {addressed} to '{want}': {e}")

    landed = safe(lambda: entity.name)
    if landed is None:
        return error(f"Renamed {addressed} to '{want}' but the name could not be read back, so the "
                     "rename is unverified. Check the browser (design_get(include=['tree'])).")
    if landed == previous:
        return error(f"The rename did not take - {addressed} still reads '{previous}' after setting "
                     f"the name to '{want}'.")

    deduped = landed != want
    note = f"Renamed: '{previous}' -> '{landed}'."
    if deduped:
        note += (f" Fusion deduped the requested name '{want}' (a sibling already holds it) - the "
                 f"name that LANDED is '{landed}'; refer to that one, not what was requested.")
    if address is not None:
        if _inputs.is_handle(address):
            address = safe(lambda: entity.entityToken) or address
            addressed = f"{kind} '{address}'"
        elif kind == "feature":
            addressed = f"feature '{address}'"
        elif kind == "joint" and ":" in address:
            addressed = f"joint '{address.rpartition(':')[0]}:{landed}'"
        else:
            addressed = f"{kind} '{safe(lambda: owner.name)}/{landed}'"
    if kind == "component" and len(instances) > 1:
        note += (f" This is a component: all {len(instances)} of its instances now read the new "
                 "name.")

    result = {
        "renamed": True,
        "changed": True,
        "kind": kind,
        "addressed": addressed,
        "previous_name": previous,
        "requested_name": want,
        "name": landed,
        "deduped": deduped,
        "note": note,
    }
    if kind == "component":
        result["occurrences"] = len(instances)
        # Read one instance back: it is the evidence that the browser name (and the fullPathName
        # every occurrence-taking tool keys off) followed the component rename.
        result["occurrence_name"] = safe(lambda: read_occ.name) if read_occ is not None else None
        result["occurrence_path"] = (safe(lambda: read_occ.fullPathName)
                                     if read_occ is not None else None)
    return ok(result)


_DESC = (
"Rename by kind.\n"
+ _outputs.produces_block(RETURNS)
)

_TARGET_NAME, _TARGET_SCHEMA = _TARGET.as_property()
_TARGET_SCHEMA["description"] = (
    "target: handle/name; feature: owner/name or index; joint: occ:name or owner/name; datums: owner/name or handle."
)

tool = (
    Tool.create_simple(name="design_set_name", description=_DESC)
    .add_input_property("kind", {"type": "string", "enum": list(_KINDS), "default": "target"})
    .add_input_property(_TARGET_NAME, _TARGET_SCHEMA)
    .add_input_property("new_name", {"type": "string"})
    .strict_schema()
)
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline", rung="value",
        evidence_test="tests/unit/test_design_set_name.py::TestGuards"
                      "::test_a_silently_refused_set_is_an_error_not_a_false_ok"))


def register_tool():
    register(item)
