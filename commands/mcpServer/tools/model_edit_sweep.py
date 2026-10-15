# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Edit a measured Sweep operand or Boolean scope on a parametric feature."""

import hashlib

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _assert, _common, _design_common, _inputs, _path_common, _sketch_detail, _sweep_common
from ._edit_feature_common import (address_text, all_shapes as _all_shapes, at_address,
                                   body_creator, failed,
                                   collection_entities as _collection_entities,
                                   feature_body_keys as _feature_body_keys,
                                   health as _health, identical_geometry_reply,
                                   later_operand_refusal, matched, operand_source,
                                   read_sweep_definition, restore_definition, restore_gaps, roll_to_edit, rolled_back_text,
                                   same_feature as _same_feature, sentence, shape_match,
                                   sketch_address)
from ._common import counted, error, ok, outcome_clause, safe


_FEATURE = _inputs.FeatureRef("feature", required=True)
_ACTION = _inputs.Choice("action", ("profile", "path", "guide_path", "operation", "participants"),
                        required=True)
_OPERATION = _inputs.boolean_op(default=None, description="")
_TARGET_BODIES = _inputs.BodyRefList("target_bodies", kind="solid")
_SPEC = [_FEATURE, _ACTION, _OPERATION, _TARGET_BODIES]
_UNREAD = object()
_KEEP_OWNER_MODE = "Replacement profile must keep this Sweep's owner and solid/surface mode."


def _profile_members(profile):
    """The profile's native identity or ordered open-curve identities, or None."""
    entity = _common._native_of(profile)
    if safe(lambda: entity.objectType) == "adsk::fusion::Path":
        return _path_members(entity)
    if safe(lambda: entity.objectType) == "adsk::core::ObjectCollection":
        count = counted(lambda: entity.count)
        if not count:
            return None
        keys = [_common.native_identity(safe(lambda i=i: entity.item(i))) for i in range(count)]
        return tuple(keys) if all(keys) else None
    key = _common.native_identity(entity)
    return (key,) if key is not None else None


def _path_members(path):
    """Ordered native identities of a path's actual member entities, or None."""
    count = counted(lambda: path.count)
    if not count:
        return None
    keys = [_common.native_identity(safe(lambda i=i: path.item(i).entity)) for i in range(count)]
    return tuple(keys) if all(keys) else None


def _definition(feature):
    """The edit-position sweep definition, or None when a required getter fails."""
    read = read_sweep_definition(feature)
    profile = _profile_members(read["profile"])
    path = _path_members(read["path"])
    raw_guide = safe(lambda: feature.guideRail, _UNREAD)
    guide_path = (None if raw_guide is None else
                  _path_members(raw_guide) if raw_guide is not _UNREAD else None)
    guide_surfaces = _collection_entities(safe(lambda: feature.guideSurfaces, _UNREAD))
    solid_body = safe(lambda: feature.solidBody, _UNREAD)
    operation, solid = read["operation"], read["is_solid"]
    orientation_applicable = raw_guide is None
    profile_scaling = (safe(lambda: feature.profileScaling, _UNREAD)
                       if raw_guide is not None and raw_guide is not _UNREAD else None)
    orientation = read["orientation"] if orientation_applicable else None
    orientation_name = read["orientation_name"] if orientation_applicable else None
    if (profile is None or path is None or operation is None
            or raw_guide is not None and raw_guide is not _UNREAD
            and type(profile_scaling) is not int
            or orientation_applicable and orientation_name not in ("perpendicular", "parallel")
            or raw_guide is _UNREAD or raw_guide is not None and guide_path is None
            or guide_surfaces != [] or solid_body is not None or solid not in (True, False)):
        return None
    participants = _participants(feature, operation)
    if operation != adsk.fusion.FeatureOperations.NewBodyFeatureOperation and participants is None:
        return None
    participant_keys = (None if participants is None else
                        tuple(_common.native_identity(body) for body in participants))
    return {"profile": profile, "path": path, "guide_path": guide_path, "operation": operation,
            "participants": participant_keys, "orientation": orientation,
            "orientation_applicable": orientation_applicable,
            "profile_scaling": profile_scaling, "is_solid": solid}

def _definition_report(definition):
    """A compact account of read-back members and retained mode controls."""
    if definition is None:
        return None
    profile, path, guide = (definition["profile"], definition["path"],
                            definition.get("guide_path"))
    return {"profile_signature": hashlib.sha256(repr(profile).encode("ascii")).hexdigest()[:16],
            "profile_members": len(profile) if isinstance(profile, tuple) else 1,
            "path_signature": hashlib.sha256(repr(path).encode("ascii")).hexdigest()[:16],
            "path_curves": len(path),
            "guide_path_signature": (hashlib.sha256(repr(guide).encode("ascii")).hexdigest()[:16]
                                     if guide is not None else None),
            "guide_path_curves": len(guide) if guide is not None else 0,
            "operation": definition["operation"],
            "orientation": definition["orientation"],
            "orientation_applicable": definition.get("orientation_applicable"),
            "profile_scaling": definition.get("profile_scaling"),
            "is_solid": definition["is_solid"]}


def _members(operand):
    """The member entities of a profile or path: a Path's or collection's items, else the operand."""
    entity = _common._native_of(operand)
    kind = safe(lambda: entity.objectType)
    if kind == "adsk::fusion::Path":
        return [safe(lambda i=i: entity.item(i).entity) for i in range(counted(lambda: entity.count) or 0)]
    if kind == "adsk::core::ObjectCollection":
        return list(_common.iter_collection(entity))
    return [entity]


def _addresses(operand):
    """The sketch address of each member of a profile or path, None for a member outside a sketch."""
    return [sketch_address(member) for member in _members(operand)]


def _rolled_back_row(design, owner, name):
    """The timeline row of the one rolled-back sketch of `owner` named `name`, else None."""
    timeline = safe(lambda: design.timeline)
    rows = []
    for i in range(counted(lambda: timeline.count) or 0):
        obj = safe(lambda i=i: timeline.item(i))
        entity = safe(lambda: obj.entity)
        if (safe(lambda: obj.name) == name and _common.read_flag(lambda: obj.isRolledBack) is True
                and safe(lambda: entity.objectType) == "adsk::fusion::Sketch"
                and _common.same_component(safe(lambda: entity.parentComponent), owner) is True):
            rows.append(counted(lambda: obj.index))
    return rows[0] if len(rows) == 1 else None


def _later_refusal(design, owner, label, index, action, raw, component):
    """(reorder advice, unmovable refusal, open profile, refusal before any roll, later-body refusal)."""
    open_profile = host = later_body = None
    if action in ("path", "guide_path"):
        operand, _label, refusal = _inputs.build_path(owner, raw)
        name = raw.split(":", 1)[1].strip() if isinstance(raw, str) and ":" in raw else None
        row = (_rolled_back_row(design, owner, name)
               if refusal and name and raw.strip().lower().startswith("sketch:") else None)
        if row is not None:
            return None, None, False, (
                f"Editing '{label}': sketch '{name}' at timeline row {row} is rolled back behind "
                "the marker. Roll to the end with design_edit_timeline(action='roll', to='end'), "
                "then retry. Nothing was edited."), None
    else:
        operand, _solid, open_profile, host, sketch, refusal = _sweep_common.resolve_profile(
            design, owner, raw, False, component)
        # An open Profile has no parentSketch; its source curves carry timeline provenance.
        if not refusal and open_profile:
            operand, _label, refusal = _inputs.build_path(host, f"sketch:{sketch.name}")
    members = [] if refusal else _members(operand)
    for member in members:
        source, row, from_sketch = operand_source(member)
        hint = (_design_common.collapsed_group_hint_for(safe(lambda: design.timeline), source,
                                                        safe(lambda: source.name))
                if from_sketch and row is None else None)
        if hint:
            return None, None, False, (f"{hint} The {action} sketch timeline row does not read; "
                                       "nothing was edited."), None
        body = safe(lambda m=member: _common._native_of(m).body)
        if action == "path" and not from_sketch and body is not None and later_body is None:
            made, body_name = body_creator(design, body), safe(lambda body=body: body.name)
            if made and body_name and made[1] > index:
                later_body = (
                    f"'path' edge belongs to '{body_name}', made by '{made[0]}' at row {made[1]}, "
                    f"after '{label}' at row {index}. Use an edge or sketch that exists before row "
                    f"{index}; a fresh find_geometry handle on that body repeats this refusal.")
    advice = later_operand_refusal(label, index, members) if members else None
    if advice is None:
        return None, None, False, None, later_body
    if action == "profile" and _common.same_component(host, owner) is not True:
        return advice, _KEEP_OWNER_MODE, open_profile, None, None
    return (advice, safe(lambda: _operand_error(operand, action, owner, None)), open_profile, None,
            None)


def _members_text(addresses):
    """A profile or path's members as an outcome sentence names them."""
    texts = [address_text(address) for address in addresses or []]
    if not texts or None in texts:
        return f"{len(texts)} member(s), not all in a sketch" if texts else None
    return ", ".join(texts[:3]) + (f" and {len(texts) - 3} more" if len(texts) > 3 else "")


def _remedy(label, action, addresses, host):
    """A model_edit_sweep call that re-applies the prior operand, else 'Undo it in Fusion.'."""
    sketch = addresses[0][0] if addresses and None not in addresses else None
    name = safe(lambda: sketch.name) if sketch is not None else None
    call = f"Restore it with model_edit_sweep(feature='{label}', action='{action}', "
    if action == "profile" and name and len(addresses) == 1 and addresses[0][1] == "profile":
        return f"{call}profile={{'sketch': '{name}', 'profile_index': {addresses[0][2]}}})."
    curves = [at_address(a) for a in addresses] if name and action in ("path", "guide_path") else []
    # 'sketch:<name>' builds from every non-construction curve of the sketch that name resolves to.
    if (curves and None not in curves and len({a[1:] for a in addresses}) == len(addresses)
            and all(a[1] != "profile" and a[0] == sketch for a in addresses)
            and not any(safe(lambda c=c: c.isConstruction, False) for c in curves)
            and _path_common.path_sketch_curve_count(host, f"sketch:{name}") == len(addresses)
            and safe(lambda: _common.target_sketch(host, name)[0] == sketch) is True):
        return f"{call}path='sketch:{name}')."
    return "Undo it in Fusion."


def _path_restorer(entity, owner, addresses, participants, member="path"):
    """The measured path reverse - createPath over the prior sketch curves - or None."""
    if not addresses or any(a is None or a[1] == "profile" for a in addresses):
        return None

    def restore():
        curves = [at_address(address) for address in addresses]
        if None in curves:
            raise RuntimeError("a prior path curve no longer resolves in its sketch")
        seed = curves[0]
        if len(curves) > 1:
            seed = adsk.core.ObjectCollection.create()
            for curve in curves:
                seed.add(curve)
        setattr(entity, member, owner.features.createPath(seed, False))
        if participants:
            entity.participantBodies = list(participants)
    return restore


def _settle(design, entity, label, restore, rows, remedy, details, prior, where,
            member="path", result_bodies_before=None):
    """Run the measured path reverse; the outcome sentence its re-read backs."""
    definition_before, before_shapes, participants_before, health_before = prior
    marker, index, token, count = where
    operation = definition_before["operation"]
    result_bodies_after = {}

    def restored_definition(e):
        operand = (_addresses(safe(lambda: getattr(e, member))) if member else None)
        return (_definition(e), operand,
                _participant_keys(e, operation))

    def restored_shapes():
        shapes = _all_shapes(design)
        if result_bodies_before is not None:
            result_bodies_after["rows"] = _result_body_rows(entity)
        return shapes

    back = restore_definition(design, entity, restore, restored_definition,
                              index + 1, restored_shapes, marker)
    definition, members, keys = back["definition"] or (None, None, None)
    health_back = _health(design, marker) if back["marker_after"] == marker else None
    shapes_back, recreated = shape_match(back["shapes"], before_shapes)
    scope_match = (matched(keys, participants_before)
                   if operation != adsk.fusion.FeatureOperations.NewBodyFeatureOperation else None)
    why = restore_gaps(back["error"], definition=matched(definition, definition_before),
                       shapes=shapes_back,
                       health=matched(health_back, health_before),
                       row=_same_feature(design, token, entity, index, count),
                       **({"scope": scope_match} if scope_match is not None else {}))
    result_identity_restored = None
    if result_bodies_before is not None:
        result_bodies_now = result_bodies_after.get("rows")
        result_identity_restored = (None if result_bodies_now is None else
            {row["token"] for row in result_bodies_now} ==
            {row["token"] for row in result_bodies_before})
        if result_identity_restored is not True:
            why.append("the restored result body identity changed or could not be read; refresh its handle")
        details["result_bodies_after_restore"] = result_bodies_now
        details["result_body_identity_restored"] = result_identity_restored
    details["rollback"] = {"ran": back["ran"], "verified": not why, "unverified": why,
                           "operand_after": _members_text(members), "marker_after": back["marker_after"],
                           "recreated": recreated,
                           "result_body_identity_restored": result_identity_restored}
    if not back["ran"]:
        return outcome_clause("kept", f"'{label}'", rows, remedy, back["error"])
    if not why:
        return rolled_back_text(rows, recreated)
    now = _members_text(members)
    # model_edit_sweep refuses an operand the feature already reads.
    return outcome_clause("rollback_failed", f"'{label}'", [(rows[0][0], now, rows[0][2])],
                          remedy if now != rows[0][2] else "Undo it in Fusion.", "; ".join(why))


def _participants(feature, operation):
    """Native participant bodies for a boolean sweep, or None on an unreadable list."""
    if operation == adsk.fusion.FeatureOperations.NewBodyFeatureOperation:
        return None
    bodies = safe(lambda: list(feature.participantBodies))
    if bodies is None:
        return None
    native = [_common._native_of(body) for body in bodies]
    keys = [_common.native_identity(body) for body in native]
    return native if native and len(native) == len(set(keys)) and all(keys) else None


def _participant_keys(feature, operation):
    """Native participant identities after a setter, or None when unreadable."""
    bodies = _participants(feature, operation)
    return None if bodies is None else {_common.native_identity(body) for body in bodies}


def _result_body_rows(feature, cap=64):
    """Result-body names and native tokens at the evaluated Sweep position, or None when unread."""
    bodies = safe(lambda: feature.bodies)
    count = counted(lambda: bodies.count)
    if count is None or count > cap:
        return None
    rows = []
    for index in range(count):
        body = safe(lambda index=index: bodies.item(index))
        token = safe(lambda body=body: body.entityToken)
        name = safe(lambda body=body: body.name)
        owner = safe(lambda body=body: body.parentComponent.name)
        if (body is None or not isinstance(token, str) or not token or not isinstance(name, str)
                or not isinstance(owner, str) or not owner):
            return None
        rows.append({"name": name, "token": token, "component": owner})
    return rows


def _participant_rows(bodies):
    """The native body names, tokens and owners for an explicitly known participant list."""
    if bodies is None:
        return None
    rows = []
    for body in bodies:
        native = _common._native_of(body)
        token = safe(lambda: native.entityToken)
        name = safe(lambda: native.name)
        owner = safe(lambda: native.parentComponent.name)
        if not all(isinstance(value, str) and value for value in (token, name, owner)):
            return None
        rows.append({"name": name, "token": token, "component": owner})
    return rows


def _participant_refusal(design, owner, index, bodies):
    """A refusal when an explicit Boolean target is not an earlier native solid body of this owner."""
    if not bodies:
        return "Boolean Sweep edits require nonempty explicit 'target_bodies'."
    keys = [_common.native_identity(_common._native_of(body)) for body in bodies]
    if any(key is None for key in keys) or len(keys) != len(set(keys)):
        return "'target_bodies' must contain uniquely readable native body identities."
    for body in bodies:
        native = _common._native_of(body)
        if (native is None or safe(lambda: native.isSolid) is not True
                or _common.same_component(owner, safe(lambda: native.parentComponent)) is not True
                or safe(lambda: native.assemblyContext, _UNREAD) is not None):
            return "Each 'target_bodies' entry must be a native solid body in the Sweep owner."
        creator = body_creator(design, native)
        if creator is None:
            return "A 'target_bodies' source feature could not be read; inspect design_get before editing."
        if creator[1] >= index:
            return (f"'target_bodies' body '{safe(lambda: native.name)}' is created at row "
                    f"{creator[1]}; every target must precede Sweep row {index}.")
    return None


def _operation_restorer(entity, operation):
    """Restore the measured NewBody operation without inventing a prior participant list."""
    def restore():
        entity.operation = operation
    return restore


def _participants_restorer(entity, participants):
    """Restore an explicitly read Boolean participant list."""
    def restore():
        entity.participantBodies = list(participants)
    return restore


def _operand_owner(entity):
    """The native profile or path member's component and source timeline index."""
    source, row, _from_sketch = operand_source(entity)
    return safe(lambda: source.parentComponent), row


def _operand_error(operand, action, component, index):
    """A refusal for a future, foreign or invalid operand, or None; index None skips row checks."""
    if action == "profile" and safe(lambda: operand.objectType) == "adsk::fusion::Path":
        members = [safe(lambda i=i: operand.item(i).entity)
                   for i in range(counted(lambda: operand.count) or 0)]
    elif action == "profile" and safe(lambda: operand.objectType) == "adsk::core::ObjectCollection":
        members = list(_common.iter_collection(operand))
    elif action == "profile":
        members = [operand]
    else:
        members = [operand.item(i).entity for i in range(operand.count)]
    if not members:
        return f"'{action}' has no readable members."
    for member in members:
        owner, row = _operand_owner(member)
        if _common.same_component(owner, component) is not True:
            return f"'{action}' has a member outside the Sweep's owning component."
        if index is None:
            if safe(lambda m=member: m.isValid) is not True:
                return f"'{action}' has an invalid member at the current marker."
            continue
        if (row is None and safe(lambda m=member: m.parentSketch) is not None) or (
                row is not None and row >= index):
            return f"'{action}' has a member at row {row}; every source must precede Sweep row {index}."
        if row is None:
            body = safe(lambda m=member: _common._native_of(m).body)
            bodies = safe(lambda: component.bRepBodies)
            edges = safe(lambda: body.edges)
            body_key = _common.native_identity(body)
            member_key = _common.native_identity(member)
            body_count = counted(lambda: bodies.count)
            edge_count = counted(lambda: edges.count)
            if (body_key is None or member_key is None or body_count is None
                    or edge_count is None or not any(
                        _common.native_identity(safe(lambda i=i: bodies.item(i))) == body_key
                        for i in range(body_count)) or not any(
                        _common.native_identity(safe(lambda i=i: edges.item(i))) == member_key
                        for i in range(edge_count))):
                return f"'{action}' has an edge absent from its evaluated source body at the Sweep row."
        if safe(lambda m=member: m.isValid) is not True:
            return f"'{action}' has an invalid member at the Sweep edit position."
    return None


def _inactive_link_count(feature, index):
    """Count same-row bodyless rolled-back Sweep companions, or return None."""
    links = safe(lambda: feature.linkedFeatures)
    count = counted(lambda: links.count)
    if count is None:
        return None
    states = adsk.fusion.FeatureHealthStates
    for i in range(count):
        link = safe(lambda i=i: links.item(i))
        if (link is None or safe(lambda l=link: l.objectType) != adsk.fusion.SweepFeature.classType()
                or counted(lambda l=link: l.timelineObject.index) != index
                or safe(lambda l=link: l.healthState) != states.RolledBackFeatureHealthState
                or counted(lambda l=link: l.bodies.count) != 0):
            return None
    return count


def _target_error(feature, label):
    """A refusal for sweep forms whose profile/path setters are outside this tool."""
    if safe(lambda: feature.objectType) != adsk.fusion.SweepFeature.classType():
        return f"'{label}' is not a Sweep feature. Use design_get(include=['timeline'])."
    for name, want in (("isParametric", True), ("isSuppressed", False)):
        got = safe(lambda n=name: getattr(feature, n))
        if got is not want:
            return f"'{label}' has {name}={got}; this edit requires {name}={want}."
    if safe(lambda: feature.baseFeature, _UNREAD) is not None:
        return f"'{label}' is not a standalone parametric Sweep."
    index = counted(lambda: feature.timelineObject.index)
    if index is None or _inactive_link_count(feature, index) is None:
        return f"'{label}' has linked features outside readable same-row bodyless rolled-back Sweeps; inspect design_get."
    return None


def handler(feature: str = "", action: str = "", profile=None, path=None,
            component: str = "", operation: str = "", target_bodies=None) -> dict:
    """Replace one Sweep operand and report definition, geometry, scope and health evidence."""
    raw = dict(locals())
    values, refusal = _inputs.resolve_inputs(_SPEC, raw)
    if refusal:
        return refusal
    action = values["action"]
    allowed = {"profile": {"profile", "component"}, "path": {"path", "component"},
               "guide_path": {"path", "component"}, "operation": {"operation", "target_bodies"},
               "participants": {"target_bodies"}}[action]
    for name in ("profile", "path", "component", "operation", "target_bodies"):
        if raw[name] not in (None, "", []) and name not in allowed:
            return error(f"'{name}' is unused for action='{action}'; remove it.")
    operand_input = ("profile" if action == "profile" else
                     "path" if action in ("path", "guide_path") else None)
    if operand_input and raw[operand_input] in (None, "", []):
        return error(f"action='{action}' requires '{operand_input}'.")
    if action == "operation" and not values["operation"]:
        return error("action='operation' requires 'operation'.")
    if action == "operation" and not values.get("target_bodies"):
        return error("action='operation' requires nonempty explicit 'target_bodies'.")
    if action == "participants" and not values["target_bodies"]:
        return error("action='participants' requires nonempty 'target_bodies'.")
    entity, label = values["feature"]
    refusal = _target_error(entity, label)
    if refusal:
        return error(refusal)
    design = _common.design()
    timeline = safe(lambda: design.timeline)
    marker = counted(lambda: timeline.markerPosition)
    count = counted(lambda: timeline.count)
    index = counted(lambda: entity.timelineObject.index)
    token = safe(lambda: entity.entityToken)
    component_owner = safe(lambda: entity.parentComponent)
    if None in (marker, count, index) or not token or component_owner is None:
        return error(f"'{label}' has unreadable timeline identity; nothing was edited.")
    if marker <= index:
        return error(f"'{label}' is after marker {marker}; roll after it with design_edit_timeline.")
    if action in ("profile", "path", "guide_path"):
        pending_later_refusal, later_blocker, later_open, unread_row, later_body = _later_refusal(
            design, component_owner, label, index, action, raw[operand_input], component)
        if unread_row:
            return error(unread_row)
    else:
        pending_later_refusal, later_blocker, later_open, later_body = None, None, False, None
    linked_before = _inactive_link_count(entity, index)
    if linked_before is None:
        return error(f"'{label}' has unreadable or active linked features; nothing was edited.")
    health_before = _health(design, marker)
    if health_before is None:
        return error(f"'{label}'s evaluated-health census is unreadable; nothing was edited.")
    failure = post_error_read_failure = None
    attempted = replayed = False
    definition_before = definition_after = None
    operation_after = None
    participant_rows_before = participant_rows_requested = participant_rows_after = None
    participants_before = participants_after = participant_names = participants = None
    desired = before_shapes = after_shapes = target_before = target_after = None
    result_bodies_before = result_bodies_after = None
    target_before_bodies = target_after_bodies = participant_names_after = None
    target_participants = None
    target_participants_match = None
    linked_evaluated = linked_restored = None
    sketch_curve_count = members_before = members_after = None
    left_out = []
    try:
        if not roll_to_edit(entity, timeline, index):
            raise RuntimeError("Fusion refused the Sweep edit position.")
        current_guide = safe(lambda: entity.guideRail, _UNREAD)
        current_guide_surfaces = safe(lambda: entity.guideSurfaces, _UNREAD)
        current_solid_tool = safe(lambda: entity.solidBody, _UNREAD)
        if (current_guide is _UNREAD or current_guide_surfaces is _UNREAD
                or current_solid_tool is _UNREAD):
            raise ValueError("Sweep guide and solid-tool fields are unreadable at the edit position.")
        surface_entities = _collection_entities(current_guide_surfaces)
        if surface_entities is None:
            raise ValueError("Sweep guide-surface collection is unreadable at the edit position.")
        if surface_entities or current_solid_tool is not None:
            raise ValueError("Sweep guide surfaces and solid-tool edits are not supported here.")
        if action == "guide_path" and current_guide is None:
            raise ValueError("action='guide_path' requires an existing guide rail.")
        if action != "guide_path" and current_guide is not None:
            raise ValueError("This action supports only a Sweep without a guide or solid-tool definition.")
        timeline.markerPosition = index + 1
        if counted(lambda: timeline.markerPosition) != index + 1:
            raise RuntimeError("The original Sweep could not be evaluated for a body census.")
        before_shapes = _all_shapes(design)
        target_before = _feature_body_keys(entity)
        if before_shapes is None or not target_before:
            raise ValueError("The original Sweep's body census is unreadable.")
        if action in ("operation", "participants"):
            result_bodies_before = _result_body_rows(entity)
            if result_bodies_before is None:
                raise ValueError("The original Sweep result-body identities are unreadable.")
        if not roll_to_edit(entity, timeline, index):
            raise RuntimeError("The Sweep could not return to its edit position.")
        definition_before = _definition(entity)
        if definition_before is None:
            raise ValueError("The Sweep definition is unreadable at its edit position.")
        member = ("profile" if action == "profile" else "path" if action == "path"
                  else "guideRail" if action == "guide_path" else None)
        members_before = (_addresses(safe(lambda: getattr(entity, member)))
                          if member is not None else None)
        operation = definition_before["operation"]
        allowed_operations = (adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
                              adsk.fusion.FeatureOperations.JoinFeatureOperation,
                              adsk.fusion.FeatureOperations.CutFeatureOperation,
                              adsk.fusion.FeatureOperations.IntersectFeatureOperation)
        if operation not in allowed_operations:
            raise ValueError("This Sweep operation is outside model_sweep's editable operation set.")
        participants = _participants(entity, operation)
        is_new = operation == adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        if not is_new and participants is None:
            raise ValueError("Current Boolean participants are unreadable; their material scope cannot be retained.")
        participants_before = (None if is_new else
                               {_common.native_identity(body) for body in participants})
        participant_names = (None if participants is None else
                             [safe(lambda b=body: b.name) for body in participants])
        target_participants = participants
        if action == "operation":
            if not is_new or values.get("operation") != "cut":
                raise ValueError("Only the measured NewBody-to-Cut Sweep operation is supported.")
            refusal = _participant_refusal(design, component_owner, index,
                                          values.get("target_bodies"))
            if refusal:
                raise ValueError(refusal)
            target_participants = [_common._native_of(body) for body in values["target_bodies"]]
            desired = adsk.fusion.FeatureOperations.CutFeatureOperation
        elif action == "participants":
            if operation != adsk.fusion.FeatureOperations.CutFeatureOperation:
                raise ValueError("Participant edits require an existing Cut Sweep.")
            refusal = _participant_refusal(design, component_owner, index,
                                          values.get("target_bodies"))
            if refusal:
                raise ValueError(refusal)
            target_participants = [_common._native_of(body) for body in values["target_bodies"]]
            desired = tuple(_common.native_identity(body) for body in target_participants)
            if set(desired) == participants_before:
                raise ValueError(f"'{label}' already uses those participants.")
        if action in ("operation", "participants"):
            participant_rows_before = _participant_rows(participants)
            participant_rows_requested = _participant_rows(target_participants)
            if participant_rows_requested is None or not is_new and participant_rows_before is None:
                raise ValueError("Sweep participant names, tokens or owners are unreadable.")
        if pending_later_refusal:
            # Every refusal a reorder would not cure comes first: the advice is a lasting change.
            if later_blocker:
                raise ValueError(later_blocker)
            if later_open and definition_before["is_solid"]:
                raise ValueError(_KEEP_OWNER_MODE)
            timeline.markerPosition = marker
            if counted(lambda: timeline.markerPosition) != marker:
                raise RuntimeError("The timeline marker could not be restored after the read-only preflight.")
            return error(pending_later_refusal)
        if action == "profile":
            operand, solid, open_profile, host, source_sketch, refusal = _sweep_common.resolve_profile(
                design, component_owner, profile, not definition_before["is_solid"], component)
            if refusal:
                raise ValueError(refusal)
            if _common.same_component(host, component_owner) is not True or solid != definition_before["is_solid"]:
                raise ValueError(_KEEP_OWNER_MODE)
            checked_operand = operand
            if open_profile:
                source_name = safe(lambda: source_sketch.name)
                if not source_name:
                    raise ValueError("The open profile's source sketch name is unreadable.")
                checked_operand, _label, refusal = _inputs.build_path(host, f"sketch:{source_name}")
                if refusal:
                    raise ValueError(refusal)
                source_count = _path_common.path_sketch_curve_count(host, f"sketch:{source_name}")
                if source_count is None or counted(lambda: checked_operand.count) != source_count:
                    raise ValueError("The open profile's source path omits sketch curves.")
            desired = _profile_members(checked_operand)
        elif action in ("path", "guide_path"):
            operand, _label, refusal = _inputs.build_path(component_owner, path, left_out)
            if refusal:
                raise ValueError(later_body or refusal)
            desired = _path_members(operand)
            sketch_curve_count = _path_common.path_sketch_curve_count(component_owner, path)
            checked_operand = operand
        if action in ("profile", "path", "guide_path"):
            if desired is None:
                raise ValueError(f"Replacement '{action}' members could not be read.")
            refusal = _operand_error(checked_operand, action, component_owner, index)
            if refusal:
                raise ValueError(refusal)
            if desired == definition_before[action]:
                raise ValueError(f"'{label}' already uses that {action}.")
        attempted = True
        setter_failure = None
        try:
            if action == "operation":
                entity.operation = desired
                entity.participantBodies = list(target_participants)
            elif action == "participants":
                entity.participantBodies = list(target_participants)
            else:
                setattr(entity, member, operand)
        except Exception as exc:
            setter_failure = exc
        # Native setters can expand scope even when they raise after a partial assignment.
        if action in ("profile", "path", "guide_path") and participants:
            entity.participantBodies = list(participants)
            replayed = True
        definition_after = _definition(entity)
        operation_after = definition_after.get("operation") if definition_after else None
        participants_after = _participant_keys(entity, operation_after)
        if setter_failure is not None:
            raise setter_failure
        timeline.markerPosition = index + 1
        if counted(lambda: timeline.markerPosition) != index + 1:
            raise RuntimeError("The edited Sweep could not be evaluated for a body census.")
        after_shapes = _all_shapes(design)
        target_after = _feature_body_keys(entity)
        if action in ("operation", "participants"):
            result_bodies_after = _result_body_rows(entity)
            if result_bodies_after is None:
                raise RuntimeError("The edited Sweep result-body identities are unreadable.")
        linked_evaluated = _inactive_link_count(entity, index)
        if linked_evaluated is None:
            raise RuntimeError("The edited Sweep has an active or unreadable linked feature.")
        if not roll_to_edit(entity, timeline, index):
            raise RuntimeError("The evaluated Sweep could not be rolled back for definition verification.")
        definition_after = _definition(entity)
        members_after = (_addresses(safe(lambda: getattr(entity, member)))
                         if member is not None else None)
        definition_after = _definition(entity)
        operation_after = definition_after.get("operation") if definition_after else None
        participants_after = _participant_keys(entity, operation_after)
        if action in ("operation", "participants"):
            participant_rows_after = _participant_rows(_participants(entity, operation_after))
            if participant_rows_after is None:
                raise RuntimeError("The edited Sweep participant read-back is unreadable.")
    except Exception as exc:
        failure = sentence(exc)
        if attempted:
            if counted(lambda: timeline.markerPosition) == index:
                definition_after = _definition(entity)
                members_after = (_addresses(safe(lambda: getattr(entity, member)))
                                 if member is not None else None)
                operation_after = definition_after.get("operation") if definition_after else None
                participants_after = _participant_keys(entity, operation_after)
                if action in ("operation", "participants"):
                    participant_rows_after = _participant_rows(_participants(entity, operation_after))
            if after_shapes is None:
                try:
                    timeline.markerPosition = index + 1
                    if counted(lambda: timeline.markerPosition) != index + 1:
                        raise RuntimeError("The partial edit could not be evaluated.")
                    after_shapes = _all_shapes(design)
                    target_after = _feature_body_keys(entity)
                    if action in ("operation", "participants"):
                        result_bodies_after = _result_body_rows(entity)
                    if after_shapes is None or target_after is None:
                        raise RuntimeError("The partial edit body census is unreadable.")
                except Exception as read_exc:
                    post_error_read_failure = str(read_exc)
        elif definition_before is not None:
            definition_after = _definition(entity)
    finally:
        safe(lambda: setattr(timeline, "markerPosition", marker))
    restored = counted(lambda: timeline.markerPosition) == marker
    linked_restored = _inactive_link_count(entity, index) if restored else None
    same = _same_feature(design, token, entity, index, count)
    state, compute_failure = _assert.compute_state(entity)
    health_after = _health(design, marker) if restored else None
    new_errors = (None if health_after is None else
                  [name for name in health_after["errors"] if name not in health_before["errors"]])
    new_warnings = (None if health_after is None else
                    [name for name in health_after["warnings"] if name not in health_before["warnings"]])
    definition_keys = ({"operation", "participants"} if action == "operation" else
                       {"participants"} if action == "participants" else {action})
    operation_participant_keys = (None if target_participants is None else
                                  {_common.native_identity(body) for body in target_participants})

    def same_definition_value(key, left, right):
        if key == "participants":
            if left is None or right is None:
                return left is right
            return set(left) == set(right)
        return left == right

    definition_matches = (definition_before is not None and definition_after is not None
                          and (same_definition_value("participants",
                                                     definition_after.get("participants"), desired)
                               if action == "participants"
                               else definition_after.get(action) == desired)
                          and (action != "operation" or
                               operation_participant_keys is not None
                               and set(definition_after.get("participants") or ()) ==
                               operation_participant_keys)
                          and all(same_definition_value(key, definition_after[key],
                                                        definition_before[key])
                                  for key in definition_before if key not in definition_keys))
    if action == "participants":
        requested_participant_keys = set(desired) if desired is not None else None
    elif action == "operation":
        requested_participant_keys = operation_participant_keys
    else:
        requested_participant_keys = participants_before
    scope_matches = (participants_after == requested_participant_keys
                     if participants_after is not None
                     else True if requested_participant_keys is None else None)
    affected = set(target_before or ())
    if action in ("operation", "participants") and target_participants:
        affected.update(_common.native_identity(body) for body in target_participants)
    target_before_shapes = ({key: before_shapes[key]["shape"] for key in target_before}
                            if before_shapes is not None and target_before is not None
                            and target_before <= set(before_shapes) else None)
    target_after_shapes = ({key: after_shapes[key]["shape"] for key in target_after}
                           if after_shapes is not None and target_after is not None
                           and target_after <= set(after_shapes) else None)
    if action in ("operation", "participants"):
        if before_shapes is None or after_shapes is None:
            geometry_changed = None
        else:
            geometry_changed = any(
                (before_shapes.get(key) or {}).get("shape") !=
                (after_shapes.get(key) or {}).get("shape")
                for key in affected)
    else:
        geometry_changed = (None if target_before_shapes is None or target_after_shapes is None else
                            sorted(target_before_shapes.values(), key=repr) !=
                            sorted(target_after_shapes.values(), key=repr))
    outside = (set(before_shapes) - affected if before_shapes is not None
               and target_before is not None else None)
    outside_changes = (None if after_shapes is None or target_after is None or outside is None else
                       [before_shapes[key]["body"] for key in outside
                        if key not in after_shapes or after_shapes[key] != before_shapes[key]]
                       + [after_shapes[key]["body"] for key in set(after_shapes) - set(before_shapes)
                          if key not in target_after])
    details = {"feature": label, "action": action, "mutation_attempted": attempted,
               "definition_before": _definition_report(definition_before),
               "definition_after": _definition_report(definition_after),
               "definition_matches": definition_matches, "participants_replayed": replayed,
               "participant_scope_preserved": (scope_matches
                                               if action not in ("operation", "participants")
                                               else None),
               "participant_scope_matches_request": (scope_matches
                                                     if action in ("operation", "participants")
                                                     else None),
               "retained_participants": participant_names, "geometry_changed": geometry_changed,
               "participant_scope_reason": (
                   "The original NewBody sweep has no Boolean participant scope."
                   if (definition_before or {}).get("operation") ==
                   adsk.fusion.FeatureOperations.NewBodyFeatureOperation else None),
               "requested_participants": participant_rows_requested,
               "participants_before": participant_rows_before,
               "participants_after": participant_rows_after,
               "result_bodies_before": result_bodies_before,
               "result_bodies_after": result_bodies_after,
               "target_before": list(target_before_shapes.values()) if target_before_shapes is not None else None,
               "target_after": list(target_after_shapes.values()) if target_after_shapes is not None else None,
               "outside_body_changes": outside_changes,
               "outside_check": "all bodies present immediately after the Sweep, before downstream features",
               "same_feature": same,
               "inactive_linked_before": linked_before,
               "inactive_linked_evaluated": linked_evaluated,
               "inactive_linked_after": linked_restored,
               "marker_before": marker, "marker_after": counted(lambda: timeline.markerPosition),
               "marker_restored": restored, "feature_health": state,
               "unevaluated_timeline_items": count - marker,
               "post_error_read_failure": post_error_read_failure,
               "new_timeline_errors": new_errors, "new_timeline_warnings": new_warnings,
               "geometry_frame": "owning_component", "geometry_units": "cm, cm2, cm3"}
    if action in ("path", "guide_path"):
        details["path_curves"] = len(desired) if desired is not None else None
        if sketch_curve_count is not None:
            details["path_sketch_curves"] = sketch_curve_count
    details["operand_before"] = _members_text(members_before)
    details["operand_after"] = _members_text(members_after)
    missed = [name for name, good in (
        ("marker_restored", restored), ("same_feature", same is True),
        ("inactive_linked_evaluated", linked_evaluated is not None),
        ("inactive_linked_after", linked_restored is not None),
        ("definition_matches", definition_matches is True),
        ("participant_scope_preserved", scope_matches is True),
        ("geometry_changed", geometry_changed is True), ("outside_body_changes", outside_changes == []),
        ("feature_health", state == "healthy"), ("new_timeline_errors", new_errors == []),
        ("new_timeline_warnings", new_warnings == [])) if not good]
    identical = not failure and missed == ["geometry_changed"] and geometry_changed is False
    if (failure or missed) and not identical:
        rows = [(action, details["operand_after"], details["operand_before"])]
        remedy = _remedy(label, action, members_before, component_owner)
        reason = (failure or
                  ("New evaluated timeline errors or warnings appeared." if new_errors or new_warnings else "")
                  or ("Material outside the Sweep result changed." if outside_changes else "")
                  or (sentence(compute_failure) if compute_failure else "")
                  or f"These checks failed: {', '.join(missed)}.")
        if not attempted:
            text = f"{reason} Nothing was edited."
        elif (definition_after is not None and definition_after == definition_before
              and geometry_changed is False and outside_changes == [] and scope_matches is True):
            text = (f"{failure or 'Fusion kept the prior definition.'} "
                    + outcome_clause("unchanged", f"'{label}'", rows))
        elif definition_after is None or definition_after == definition_before:
            text = f"{reason} " + outcome_clause(
                "unconfirmed", f"'{label}'", remedy="model_inspect", evidence=(
                    f"definition_after={'unread' if definition_after is None else 'as before'}, "
                    f"geometry_changed={geometry_changed}, outside_body_changes={outside_changes}, "
                    f"participant_scope_preserved={scope_matches}"))
        else:
            restore = (_path_restorer(entity, component_owner, members_before, participants, member)
                       if action in ("path", "guide_path") else
                       _operation_restorer(entity, operation) if action == "operation" else
                       _participants_restorer(entity, participants) if action == "participants" else None)
            settle_member = member if action in ("profile", "path", "guide_path") else None
            text = f"{reason} " + (outcome_clause("kept", f"'{label}'", rows, remedy) if restore is None
                                   else _settle(design, entity, label, restore, rows, remedy, details,
                                                (definition_before, before_shapes, participants_before,
                                                 health_before), (marker, index, token, count),
                                                member=settle_member, result_bodies_before=result_bodies_before))
        now = counted(lambda: timeline.markerPosition)
        if now != marker:
            text += f" Also, {_common.marker_clause(marker, now, 'the edit')}."
        return failed(f"Editing '{label}': {text}", details)
    details["edited"] = True
    details["note"] = ("Sweep Cut scope changed on the same feature; inspect model_inspect."
                       if action == "participants" else
                       "Sweep changed to Cut with the requested bodies; inspect model_inspect."
                       if action == "operation" else
                       "Sweep operand changed on the same feature. Boolean edits retain the current "
                       "participants; newly reached bodies are excluded. Inspect model_inspect.")
    if action in ("path", "guide_path"):
        details["note"] += " " + _path_common.path_chain_warning(len(desired), sketch_curve_count, "sweep", left_out)
        details["note"] = details["note"].strip()
    return identical_geometry_reply(details) if identical else ok(details)


tool = _inputs.apply_to_tool(
    Tool.create_simple(name="model_edit_sweep", description=(
        "Edit Sweep operands or Boolean scope; read model_inspect.")),
    _SPEC)
tool.add_input_property("profile", _inputs.ProfileRef("profile", scope_input="component").schema())
tool.add_input_property("path", {"type": ["string", "array"], "items": {"type": "string"},
                                 "description": "Edge handle(s) or sketch:<name>."})
tool.add_input_property(*_sketch_detail.COMPONENT_SCOPE)
tool.strict_schema()
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(kind="inline", rung="geometry",
                              evidence_test="tests/unit/test_model_edit_sweep.py::test_ignored_setter_is_an_error"))


def register_tool():
    register(item)
