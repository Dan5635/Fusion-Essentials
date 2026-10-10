# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Change one measured reference or mode field on a supported timeline feature."""

import json

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _edit_feature_common as _edit, _inputs, _joints, _sheet_edit
from . import doc_insert_derive as _derive
from ._common import counted, error, ok, safe

_FEATURE = _inputs.FeatureRef("feature", required=True)
_ACTION = _inputs.Choice("action", ("inputs", "axis", "plane", "point", "path", "boundary",
                                    "tools", "geometry", "mode", "break_link"), required=True)
_REFERENCES = _inputs.FeatureEditOperands("references")
_MODE = _inputs.InputKind("mode")
_SPEC = [_FEATURE, _ACTION, _REFERENCES, _MODE]
_UNREAD = object()
_MISMATCH = "the requested definition or a retained field did not read back"
_UNVERIFIED = "the definition or the new reference identity did not read, so the edit is unverified"


def _reply_geometry_snapshot(snapshot):
    """Convert private body identity keys to JSON-safe rows for a tool reply."""
    if snapshot is None or not isinstance(snapshot, dict):
        return snapshot
    bodies = snapshot.get("bodies")
    if not isinstance(bodies, dict):
        return snapshot
    rows = []
    for identity, body in bodies.items():
        if not isinstance(identity, tuple):
            raise TypeError("A body snapshot has no native identity tuple.")
        rows.append({"identity": list(identity), **body})
    return {**snapshot, "bodies": rows}


def _reply_geometry_details(details):
    """Copy details with private geometry censuses converted at the JSON boundary."""
    result = dict(details)
    for key in ("geometry_before", "geometry_after", "geometry_restored"):
        if key in result:
            result[key] = _reply_geometry_snapshot(result[key])
    return result


def _collection(values):
    """Build the ObjectCollection used by measured surface-feature setters."""
    result = adsk.core.ObjectCollection.create()
    for value in values:
        result.add(value)
    return result


def _tangent_chain(before_state, row):
    """Return the banked tangent-chain state or refuse an unread value."""
    field = (f"edge_set_{row['set_index']}_tangent_chain"
             if row.get("setter") == "edge_set_edges" else "is_tangent_chain")
    value = before_state.get(field) if isinstance(before_state, dict) else None
    if type(value) is not bool:
        raise RuntimeError("The retained tangent-chain setting is unreadable.")
    return value


def _mode_value(row, mode):
    """Resolve one closed mode name through its measured enum member."""
    value = row["values"][mode]
    if row.get("mode_enum"):
        return getattr(getattr(adsk.fusion, row["mode_enum"]), value)
    return value


def _restore_value(feature, row, value, before_state=None):
    """Restore the original property value at the feature's edit row."""
    if row.get("setter") == "rib_web_curves":
        feature.curves = list(value)
        return
    if row.get("setter") == "hem_definition":
        _sheet_edit.write_hem(feature, value)
        return
    if row.get("reader") == "single_reference_collection":
        _edit.set_feature_path(feature, row["member"], value)
        return
    if row.get("setter") == "scale_mode":
        uniform, expressions = value
        if uniform is True:
            result = feature.setToUniform(adsk.core.ValueInput.createByString(expressions[0]))
        else:
            result = feature.setToNonUniform(*(adsk.core.ValueInput.createByString(item)
                                               for item in expressions))
        if result is not True:
            raise RuntimeError("Fusion did not restore the scale mode.")
        return True
    if row.get("setter") == "pipe_path":
        path, section_type, section_size = value
        feature.path = path
        feature.sectionType = section_type
        feature.sectionSize.expression = section_size
        return True
    if row.get("setter") == "shell_inputs":
        collection, _entities = value
        if feature.setInputEntities(collection, _tangent_chain(before_state, row)) is not True:
            raise RuntimeError("Fusion did not restore the shell input faces.")
        return True
    if row.get("setter") == "split_body_tool":
        tool, extended = value
        if feature.setSplittingTool(tool, extended) is not True:
            raise RuntimeError("Fusion did not restore the splitting tool.")
        return True
    if row.get("setter") == "rule_faces":
        if feature.ruleFilletSettings.setByAllEdges(list(value)) is not True:
            raise RuntimeError("Fusion did not restore the rule faces.")
        return True
    if row.get("setter") == "edge_set_edges":
        edge_set = getattr(feature, row["set_collection"]).item(row["set_index"])
        tangent_chain = _tangent_chain(before_state, row)
        edge_set.edges = _collection(value)
        edge_set = getattr(feature, row["set_collection"]).item(row["set_index"])
        edge_set.isTangentChain = tangent_chain
        return True
    setter = row.get("setter")
    if setter == "redefineLoopsFromFaces":
        mode = before_state.get(row["mode_field"])
        result = getattr(feature, setter)(list(value), _mode_value(row, mode))
        if result is not True:
            raise RuntimeError(f"{setter} did not confirm restoration of the original input.")
    elif setter:
        coll = _collection(value)
        if row.get("chain_field"):
            result = getattr(feature, setter)(coll, before_state[row["chain_field"]])
        else:
            result = getattr(feature, setter)(coll)
        if result is not True:
            raise RuntimeError(f"{setter} did not confirm restoration of the original input.")
    elif row.get("reference") == "bodies":
        setattr(feature, row["member"], _collection(value))
    elif row.get("assignment") == "object_collection":
        setattr(feature, row["member"], _collection(value))
    elif row.get("assignment") == "list" or row.get("reference") == "profiles":
        setattr(feature, row["member"], list(value))
    else:
        _edit.set_feature_path(feature, row["member"], value)



def _apply_value(feature, row, resolved, mode, before_state=None):
    """Apply one row from the closed support table."""
    if row.get("setter") == "rib_web_curves":
        curves = _edit.path_entities(resolved)
        if not curves:
            raise RuntimeError("The resolved path has no complete sketch-curve sequence.")
        feature.curves = curves
        return
    if row.get("setter") == "hem_definition":
        _sheet_edit.write_hem(feature, resolved)
        return
    if row.get("reader") == "single_reference_collection":
        values = resolved if isinstance(resolved, list) else [resolved]
        setattr(feature, row["member"], _collection(values))
        return
    if row.get("setter") == "scale_mode":
        expressions = _edit._scale_expressions(feature)
        if not expressions or len(set(expressions)) != 1:
            raise RuntimeError("Scale mode change needs three readable equal scale expressions.")
        expression = expressions[0]
        if mode == "uniform":
            result = feature.setToUniform(adsk.core.ValueInput.createByString(expression))
        else:
            value = adsk.core.ValueInput.createByString(expression)
            result = feature.setToNonUniform(value, value, value)
        if result is not True:
            raise RuntimeError("Fusion did not accept the scale mode.")
    elif row.get("setter") == "pipe_path":
        if before_state is None:
            raise RuntimeError("Pipe section controls are unreadable.")
        feature.path = resolved
        feature.sectionType = before_state["section_type"]
        feature.sectionSize.expression = before_state["section_size"]
    elif row.get("setter") == "shell_inputs":
        if feature.setInputEntities(
                _collection(resolved), _tangent_chain(before_state, row)) is not True:
            raise RuntimeError("Fusion did not accept the shell input faces.")

    if row.get("setter") in ("scale_mode", "pipe_path", "shell_inputs"):
        return
    if row.get("setter") == "split_body_tool":
        result = feature.setSplittingTool(resolved, feature.isSplittingToolExtended)
        if result is not True:
            raise RuntimeError("Fusion did not accept the splitting tool.")
    elif row.get("setter") == "rule_faces":
        result = feature.ruleFilletSettings.setByAllEdges(list(resolved))
        if result is not True:
            raise RuntimeError("Fusion did not accept the rule faces.")
    elif row.get("setter") == "edge_set_edges":
        edge_set = getattr(feature, row["set_collection"]).item(row["set_index"])
        tangent_chain = _tangent_chain(before_state, row)
        edge_set.edges = _collection(resolved)
        edge_set = getattr(feature, row["set_collection"]).item(row["set_index"])
        edge_set.isTangentChain = tangent_chain

    if row.get("setter") in ("split_body_tool", "rule_faces", "edge_set_edges"):
        return
    setter = row.get("setter")
    if setter == "redefineLoopsFromFaces":
        result = getattr(feature, setter)(list(resolved), _mode_value(row, mode))
        if result is not True:
            raise RuntimeError(f"{setter} did not confirm the input edit.")
    elif setter:
        coll = _collection(resolved)
        if row.get("chain_field"):
            result = getattr(feature, setter)(coll, before_state[row["chain_field"]])
        else:
            result = getattr(feature, setter)(coll)
        if result is not True:
            raise RuntimeError(f"{setter} did not confirm the input edit.")
    elif row.get("reference") == "bodies":
        setattr(feature, row["member"], _collection(resolved))
    elif row.get("assignment") == "object_collection":
        setattr(feature, row["member"], _collection(resolved))
    elif row.get("assignment") == "list" or row.get("reference") == "profiles":
        setattr(feature, row["member"], list(resolved))
    elif row.get("choices") and not row.get("reference"):
        value = _mode_value(row, mode)
        if row.get("reader") == "operation":
            value = getattr(adsk.fusion.FeatureOperations, _common.OPERATIONS[value])
        setattr(feature, row["member"], value)
    else:
        _edit.set_feature_path(feature, row["member"], resolved)



def _definition_is(desired, before, after, before_state, after_state, native_identity=False):
    """Whether the requested private operand landed and every measured control stayed fixed."""
    if (before.get("unavailable") or after.get("unavailable")
            or before_state is None or after_state is None):
        return None
    same = _edit.same_feature_edit_state(before_state, after_state, desired)
    if same is not True and native_identity and _edit.references_identified(
            after_state.get(desired.get("field")), desired.get("value")) is None:
        return None
    return same


def _example(entity, action, row):
    """A concrete call for one offered action on this timeline entity."""
    address = _inputs.candidate_address(safe(lambda: entity.timelineObject)) or "<feature>"
    return f"model_edit_feature(feature='{address}', action='{action}', {row['example']})"


def _prepared(row, resolved):
    """The value the row's member takes: a JointGeometry for a joint origin, else the operand."""
    if row.get("reference") != "joint_geometry":
        return resolved
    geometry, _label, reason = _joints.build_joint_geometry(resolved)
    if reason or geometry is None:
        raise ValueError("'references'[0] cannot anchor a joint origin: "
                         f"{reason or 'no joint geometry was built'}")
    return geometry


def _derive_definition(entity):
    """A derive's definition as read at the current marker."""
    state, fields, unavailable = _edit.feature_edit_state(entity)
    return _edit.feature_definition_view(entity, state, fields, unavailable)


def _edit_derive(design, timeline, entity, label, action, supported, row, raw, marker, count,
                 index, token):
    """Run one derive edit through its doc_insert_derive helper and pass that verdict through."""
    names = None
    if row.get("reference"):
        names, reason = _REFERENCES.resolve_for(raw["references"], entity, action, supported)
        if reason:
            return error(f"{reason} Example: {_example(entity, action, row)}. Nothing was edited.")
    before = _derive_definition(entity)
    if action == "inputs":
        result = _derive.set_source_entities(design, entity, names)
    elif action == "mode":
        result = _derive.set_favorite_parameters(design, entity, row["values"][raw["mode"]])
    else:
        result = _derive.break_link(design, entity)
    failed = result.get("isError") is not False
    reported = result.get("details") if failed else json.loads(result["content"][0]["text"])
    if not isinstance(reported, dict):
        return result
    details = dict(reported)
    details.setdefault("action", action)
    details.setdefault("definition_before", before)
    if details.get("replaced") is True:
        details.setdefault("definition_after", None)
        details.setdefault("definition_after_unread", "the derive was replaced")
    else:
        details.setdefault("definition_after", _derive_definition(entity))
        details.setdefault("same_feature", _edit.same_feature(design, token, entity, index, count))
    details.setdefault("marker_before", marker)
    details.setdefault("marker_after", counted(lambda: timeline.markerPosition))
    public = _reply_geometry_details(details)
    return _edit.failed(result.get("message") or "The derive edit failed.", public) if failed \
        else ok(public)


def _restore_at_end(design, timeline, entity, row, role, before_state, health_before,
                    owner_before, token, index, count, marker, failure, details):
    """Write a datum's original operands back at the end marker and report what did not restore."""
    restore_error = None
    try:
        original = _edit.record_entities(before_state[row["field"]])
        back = _edit.write_datum(row, entity, before_state, original)
        if row.get("returns") and back is not True:
            restore_error = f"the restoring redefinition returned {back!r}"
    except Exception as exc:
        restore_error = f"the restore raised: {exc}"
    restored_state = _edit.feature_edit_state(entity)[0]
    shapes = _edit.feature_geometry_snapshot(design)
    own_after = _edit.own_geometry(entity, role)[0]
    marker_after = counted(lambda: timeline.markerPosition)
    health = _edit.health(design, marker) if marker_after == marker else None
    identity = _edit.same_feature(design, token, entity, index, count)
    owner = _common.same_component(owner_before, safe(lambda: entity.component))
    gaps = _edit.restore_gaps(
        restore_error, definition=_edit.same_feature_edit_state(before_state, restored_state),
        shapes=_edit.matched(shapes, details["geometry_before"]),
        row=counted(lambda: entity.timelineObject.index) == index, identity=identity, owner=owner,
        health=_edit.matched(health, health_before), marker=marker_after == marker == count,
        count=counted(lambda: timeline.count) == count)
    if own_after != details["target_geometry_before"]:
        gaps.append("the datum geometry does not match the pre-edit read" if own_after is not None
                    else "the datum geometry was not re-read")
    details.update(edited=None if gaps else False, same_feature=identity, owner_restored=owner,
                   feature_health=health, marker_after=marker_after,
                   marker_restored=marker_after == marker == count, restore_gaps=gaps,
                   target_geometry_restored=own_after)
    text = ("The original definition, owner, datum identity, geometry, health and end marker were "
            "restored." if not gaps else
            "Restoration is incomplete; inspect restore_gaps and re-read "
            "design_get(include=['definition']).")
    return _edit.failed(f"Datum edit failed: {restore_error or failure}. {text}",
                        _reply_geometry_details(details))


def _edit_at_end(design, timeline, entity, label, action, supported, row, raw, marker, count,
                 index, token):
    """Edit one datum definition at the end marker without rolling, then verify or restore it."""
    meta = supported["_meta"]
    gap = _edit.definition_type_gap(entity, supported)
    if gap:
        return error(f"'{label}' {gap}, the only type action='{action}' edits. Build one with "
                     f"{meta['create']}. Nothing was edited.")
    if (safe(lambda: entity.isParametric) is not True
            or safe(lambda: entity.timelineObject.isSuppressed) is not False):
        return error(f"'{label}' must be an unsuppressed parametric datum; nothing was edited.")
    owner_before = safe(lambda: entity.component)
    health_before = _edit.health(design, marker)
    if owner_before is None or health_before is None:
        return error(f"'{label}' owner or evaluated health is unreadable; nothing was edited.")
    before_state, fields, unavailable = _edit.feature_edit_state(entity)
    before = _edit.feature_definition_view(entity, before_state, fields, unavailable)
    if before["unavailable"]:
        return error(f"'{label}' definition is unreadable: {before['unavailable']}. "
                     "Nothing was edited.")
    resolved, reason = _REFERENCES.resolve_for(raw["references"], entity, action, supported)
    if reason:
        return error(f"{reason} Example: {_example(entity, action, row)}. Nothing was edited.")
    later = _edit.later_operand_refusal(label, index,
                                        resolved if isinstance(resolved, list) else [resolved])
    if later:
        return error(later)
    role = meta["geometry"]
    try:
        desired = {"field": row["field"],
                   "value": _edit.feature_reference_state(resolved, row["reference"])}
    except Exception as exc:
        return error(f"'references' did not read as an operand: {exc}. Nothing was edited.")
    own_before, own_reason = _edit.own_geometry(entity, role)
    before_geometry = _edit.feature_geometry_snapshot(design)
    if own_before is None or before_geometry is None:
        return error(f"'{label}' geometry or the body census is unreadable"
                     + (f" ({own_reason})" if own_reason else "") + "; nothing was edited.")

    returned = failure = None
    try:
        returned = _edit.write_datum(row, entity, before_state, resolved)
        if row.get("returns") and returned is not True:
            failure = f"the redefinition returned {returned!r}"
    except Exception as exc:
        failure = f"the write raised: {exc}"
    after_state, fields, unavailable = _edit.feature_edit_state(entity)
    after = _edit.feature_definition_view(entity, after_state, fields, unavailable)
    definition_matches = _definition_is(desired, before, after, before_state, after_state, True)
    after_geometry = _edit.feature_geometry_snapshot(design)
    own_after, own_reason = _edit.own_geometry(entity, role)
    same = _edit.same_feature(design, token, entity, index, count)
    owner_matches = _common.same_component(owner_before, safe(lambda: entity.component))
    marker_after = counted(lambda: timeline.markerPosition)
    feature_health = _edit.health(design, marker) if marker_after == marker else None
    new_errors, new_warnings = _new_health(health_before, feature_health)
    if failure is None:
        if definition_matches is not True:
            failure = _UNVERIFIED if definition_matches is None else _MISMATCH
        elif after_geometry is None or own_after is None:
            failure = "the post-edit geometry is unreadable"
        elif (marker_after != marker or same is not True or owner_matches is not True
              or feature_health is None):
            failure = "datum identity, the end marker, or evaluated health could not be verified"
        elif new_errors or new_warnings:
            failure = "the edit introduced timeline health errors or warnings"
    details = {"feature": label, "action": action, "edited": failure is None,
               "returned": returned,
               "definition_before": before, "definition_after": after,
               "definition_matches": definition_matches,
               "target_geometry_before": own_before, "target_geometry_after": own_after,
               "geometry_before": before_geometry, "geometry_after": after_geometry,
               "same_feature": same, "owner_matches": owner_matches,
               "marker_before": marker, "marker_after": marker_after,
               "marker_restored": marker_after == marker,
               "health_before": health_before, "feature_health": feature_health,
               "new_timeline_errors": new_errors, "new_timeline_warnings": new_warnings}
    if failure:
        return _restore_at_end(design, timeline, entity, row, role, before_state, health_before,
                               owner_before, token, index, count, marker, failure, details)
    bodies_match = _edit.shape_match(after_geometry["bodies"], before_geometry["bodies"])[0]
    details["geometry_changed"] = None if bodies_match is None else (
        bodies_match is False or own_after != own_before
        or after_geometry["occurrences"] != before_geometry["occurrences"])
    details["note"] = meta["note"]
    public = _reply_geometry_details(details)
    return (_edit.identical_geometry_reply(public) if details["geometry_changed"] is False
            else ok(public))


def _new_health(before, after):
    """The new health rows in the error and warning lists, or None when either read failed."""
    if before is None or after is None:
        return None, None
    return tuple([row for row in after[key] if row not in before[key]]
                 for key in ("errors", "warnings"))


def _compensate(design, timeline, entity, row, original, label, action, before_state,
                before, before_geometry, health_before, owner_before, token, index, count, marker,
                after, after_geometry, definition_matches, failure, surface_targets=None,
                surface_normals_before=None, own=(None, None)):
    """Restore one failed feature write and verify definition, geometry, identity, owner, health and marker."""
    restored_state = {}

    def read_restored(item):
        state, definition, unavailable = _edit.feature_edit_state(item)
        restored_state.update(state=state, unavailable=unavailable)
        return _edit.feature_definition_view(item, state, definition, unavailable)

    restored_surface_normals = {}

    def snapshot_restored_geometry():
        shapes = _edit.feature_geometry_snapshot(design)
        if surface_targets is not None:
            restored_surface_normals["value"] = _edit.surface_normal_snapshot(surface_targets)
        return shapes

    restore = _edit.restore_definition(
        design, entity, lambda: _restore_value(entity, row, original, before_state), read_restored,
        index + 1, snapshot_restored_geometry, marker)
    restore_definition = restore["definition"]
    restore_shape = restore["shapes"]
    restore_geometry = _edit.matched(restore_shape, before_geometry)
    restore_surface_normals = (_edit.matched(restored_surface_normals.get("value"),
                                              surface_normals_before)
                               if surface_targets is not None else True)
    restore_state_match = _edit.same_feature_edit_state(before_state, restored_state.get("state"))
    row_match = counted(lambda: entity.timelineObject.index) == index
    identity = _edit.same_feature(design, token, entity, index, count)
    owner = _common.same_component(owner_before, safe(lambda: entity.parentComponent))
    health = _edit.health(design, marker) if counted(lambda: timeline.markerPosition) == marker else None
    health_match = _edit.matched(health, health_before)
    count_match = counted(lambda: timeline.count) == count
    marker_match = counted(lambda: timeline.markerPosition) == marker == count
    gaps = _edit.restore_gaps(restore["error"], definition=restore_state_match,
                              shapes=restore_geometry, row=row_match, identity=identity,
                              owner=owner, health=health_match, marker=marker_match,
                              count=count_match,
                              **({"surface_normals": restore_surface_normals}
                                 if surface_targets is not None else {}))
    gaps.extend(_edit.shape_match((restore_shape or {}).get("bodies"),
                                  (before_geometry or {}).get("bodies"))[1])
    details = {"feature": label, "action": action, "edited": None if gaps else False,
               "definition_before": before, "definition_after": after,
               "definition_matches": definition_matches,
               "geometry_before": before_geometry, "geometry_after": after_geometry,
               "definition_restored": restore_definition, "geometry_restored": restore_shape,
               "same_feature": identity, "owner_restored": owner,
               "surface_normals_restored": restore_surface_normals,
               "feature_health": health, "marker_before": marker,
               "marker_after": counted(lambda: timeline.markerPosition),
               "marker_restored": marker_match, "restore_gaps": gaps}
    if own[0]:
        own_after = _edit.own_geometry(entity, own[0])[0] if marker_match else None
        if own_after != own[1]:
            gaps.append("the edited entity's own geometry does not match the pre-edit read"
                        if own_after is not None else
                        "the edited entity's own geometry was not re-read")
        details.update(edited=None if gaps else False, target_geometry_before=own[1],
                       target_geometry_restored=own_after)
    if not gaps:
        text = "The original definition, owner, feature identity, geometry, health and end marker were restored."
    else:
        text = "Restoration is incomplete; inspect restore_gaps and use design_edit_timeline to restore the end marker."
    reason = restore["error"] or failure or "verification failed"
    return _edit.failed(f"Feature edit failed: {reason.rstrip('. ')}. {text}",
                        _reply_geometry_details(details))


def handler(feature: str = "", action: str = "", references=None, mode: str = "",
            set_index: int = None, hem=None) -> dict:
    """Edit one supported feature field and report definition, geometry, identity and marker reads."""
    raw = dict(locals())
    values, refusal = _inputs.resolve_inputs([_FEATURE, _ACTION], raw)
    if refusal:
        return refusal
    entity, label = values["feature"]
    action = values["action"]
    feature_type = safe(lambda: entity.objectType)
    if hem is not None:
        if feature_type != "adsk::fusion::HemFeature" or action != "mode":
            return error("'hem' is only used on a Hem feature with action='mode'; remove it.")
        if not isinstance(hem, dict):
            return error("'hem' must be an object with type and the mode's dimensions.")
        if mode not in (None, "", hem.get("type")):
            return error(f"mode={mode!r} disagrees with hem.type={hem.get('type')!r}; remove mode.")
        mode = raw["mode"] = hem.get("type")
    supported = _edit.FEATURE_EDIT_SUPPORT.get(feature_type)
    if supported is None:
        target = {"adsk::fusion::ExtrudeFeature": "model_edit_extrude",
                  "adsk::fusion::SweepFeature": "model_edit_sweep",
                  "adsk::fusion::LoftFeature": "model_edit_loft"}.get(feature_type)
        return error(f"'{label}' has no supported '{action}' edit here."
                     + (f" Use {target}." if target else " Read design_get(include=['definition'])."))
    raw_row = supported.get(action)
    row = _edit._row_for(entity, raw_row) if raw_row is not None else None
    if row is None:
        choices = ", ".join(name for name, offered in supported.items()
                            if not name.startswith("_") and _edit._row_for(entity, offered) is not None)
        example = next((_example(entity, name, offered) for name, offered in supported.items()
                        if not name.startswith("_") and offered.get("example")), None)
        return error(f"'{label}' does not support action='{action}'. "
                     + (f"Supported: {choices}." if choices else "This feature subtype has no admitted edits.")
                     + (f" Example: {example}." if example else ""))
    if raw["set_index"] is not None and not row.get("set_collection"):
        return error(f"'set_index' is unused for action='{action}'; remove it.")
    if row.get("reference") is None and raw["references"] not in (None, [], ""):
        return error(f"'references' is unused for action='{action}'; remove it.")
    if not row.get("choices") and raw["mode"] not in (None, ""):
        return error(f"'mode' is unused for action='{action}'; remove it.")
    if row.get("choices") and raw["mode"] not in row["choices"]:
        return error(f"'mode' for action='{action}' must be one of {', '.join(row['choices'])}.")

    design = _common.design()
    timeline = safe(lambda: design.timeline)
    marker, count = _common.timeline_marker(design)
    index = counted(lambda: entity.timelineObject.index)
    token = safe(lambda: entity.entityToken)
    if None in (marker, count, index) or not isinstance(token, str) or not token:
        return error(f"'{label}' has unreadable timeline identity; nothing was edited.")
    if marker != count:
        return error(f"The timeline marker is at {marker} of {count}; roll it to the end with "
                     "design_edit_timeline(action='roll', to='end') before editing.")
    if index < 0 or index >= count or marker <= index:
        return error(f"'{label}' has invalid timeline row {index} for marker {marker}.")
    meta = supported.get("_meta", {})
    if meta.get("route") == "derive":
        return _edit_derive(design, timeline, entity, label, action, supported, row, raw, marker,
                            count, index, token)
    if meta.get("route") == "end":
        return _edit_at_end(design, timeline, entity, label, action, supported, row, raw, marker,
                            count, index, token)
    # A joint origin has no isParametric, isSuppressed or baseFeature; its timeline row is read.
    is_feature = meta.get("feature_members") is not False
    if not is_feature and safe(lambda: entity.timelineObject.isSuppressed) is not False:
        return error(f"'{label}' must be unsuppressed; nothing was edited.")
    if is_feature and (safe(lambda: entity.isParametric) is not True
                       or safe(lambda: entity.isSuppressed) is not False):
        return error(f"'{label}' must be an unsuppressed parametric feature; nothing was edited.")
    if is_feature and safe(lambda: entity.baseFeature, _UNREAD) is not None:
        return error(f"'{label}' has a base-feature relationship that is not readable as absent; "
                     "inspect design_get before editing it.")
    health_before = _edit.health(design, marker)
    if health_before is None:
        return error(f"'{label}' evaluated health is unreadable; nothing was edited.")

    mutation_attempted = False
    failure = None
    before = after = before_geometry = after_geometry = None
    before_state = after_state = None
    resolved = original = None
    surface_targets = surface_normals_before = surface_normals_after = None
    desired = None
    definition_matches = same = owner_matches = marker_restored = None
    feature_health = new_errors = new_warnings = None
    owner_before = safe(lambda: entity.parentComponent)
    if owner_before is None:
        return error(f"'{label}' has an unreadable owner; nothing was edited.")
    own_role = meta.get("geometry")
    own_before, own_reason = _edit.own_geometry(entity, own_role) if own_role else (None, None)
    own_after = None
    if own_role and own_before is None:
        return error(f"'{label}' geometry is unreadable ({own_reason}); nothing was edited.")
    try:
        if safe(lambda: entity.timelineObject.rollTo(True)) is not True or counted(
                lambda: timeline.markerPosition) != index:
            raise RuntimeError("Fusion refused the feature edit position.")
        if row.get("set_collection"):
            edge_sets = _edit.edge_set_entities(entity, row)
            if edge_sets is None or not edge_sets:
                raise ValueError(f"'{label}' has no complete edge-set list; nothing was edited.")
            set_index = raw["set_index"]
            if set_index is None:
                if len(edge_sets) != 1:
                    raise ValueError(f"'{label}' has {len(edge_sets)} edge sets; pass 'set_index'.")
                set_index = 0
            if type(set_index) is not int or set_index < 0 or set_index >= len(edge_sets):
                raise ValueError(f"'set_index' {set_index!r} is out of range for {len(edge_sets)} sets.")
            if safe(lambda: edge_sets[set_index].objectType) != row["set_type"]:
                raise ValueError(f"'{label}' edge set {set_index} is not a supported constant-radius set.")
            row = dict(row, set_index=set_index, field=f"edge_set_{set_index}_edges")
        before_state, before_fields, before_unavailable = _edit.feature_edit_state(entity)
        before = _edit.feature_definition_view(entity, before_state, before_fields, before_unavailable)
        if not isinstance(before, dict) or before.get("unavailable"):
            unread = [f"{name} ({why})" for name, why in before_unavailable.items()
                      if name in supported.get("_preserve", {})]
            if unread and not is_feature:
                raise ValueError(f"'{label}' retained {', '.join(unread)} did not read rolled "
                                 "before it, so the edit could not be checked; nothing was written")
            raise ValueError(f"'{label}' definition is unreadable at its edit row: "
                             f"{(before or {}).get('unavailable')}.")
        original = (_edit.collection_entities(safe(lambda: getattr(entity, row["set_collection"])
                                                    .item(row["set_index"]).edges, _UNREAD))
                    if row.get("setter") == "edge_set_edges" else
                    safe(lambda: _edit._feature_path(entity, row["member"]), _UNREAD))
        if original is _UNREAD or original is None:
            raise ValueError(f"'{label}.{row['member']} is unreadable at its edit row.")
        if row.get("setter") == "hem_definition":
            original = before_fields["hem"]
        elif row.get("setter") == "shell_inputs":
            original_entities = _edit.collection_entities(original)
            if not original_entities:
                raise ValueError(f"'{label}.{row['member']} is empty or unreadable at its edit row.")
            original = (original, original_entities)
        elif row.get("reader") in ("references", "profiles", "rule_faces"):
            original = _edit.collection_entities(original)
            if original is None or not original:
                raise ValueError(f"'{label}.{row['member']} is empty or unreadable at its edit row.")
        if row.get("setter") == "split_body_tool":
            extended = before_state.get("is_splitting_tool_extended")
            if type(extended) is not bool:
                raise ValueError(f"'{label}.isSplittingToolExtended is unreadable at its edit row.")
            original = (original, extended)
        elif row.get("setter") == "pipe_path":
            original = (original, before_state["section_type"], before_state["section_size"])
        elif row.get("setter") == "scale_mode":
            original = (before_state["is_uniform"], before_state["scale_expressions"])
        if (row.get("mode_field") == "loop_type"
                and before_state.get("loop_type") == "manual"):
            raise ValueError("the existing manual Untrim loop selection cannot be read for exact restoration.")
        if row.get("reference"):
            resolved, reason = _REFERENCES.resolve_for(raw["references"], entity, action, supported)
            if reason:
                raise ValueError(reason + (f" Example: {_example(entity, action, row)}"
                                           if row.get("example") else ""))
            if row.get("unwrap_single"):
                if not isinstance(resolved, list) or len(resolved) != 1:
                    raise ValueError("'references' must resolve to exactly one Rip operand.")
                resolved = resolved[0]
                old_body = _common.native_identity(safe(lambda: original.body))
                new_body = _common.native_identity(safe(lambda: resolved.body))
                if old_body is None or new_body is None or old_body != new_body:
                    raise ValueError("'references'[0] must belong to the existing Rip body.")
            operands = (_edit.path_entities(resolved) if row["reference"] == "path" else
                        resolved if isinstance(resolved, list) else [resolved])
            later = _edit.later_operand_refusal(label, index, operands)
            if later:
                raise ValueError(later)
            desired_value = _edit.feature_reference_state(resolved, row["reference"])
            if row.get("choices"):
                desired = {"fields": {row["field"]: desired_value,
                                      row["mode_field"]: mode}}
            else:
                desired = {"field": row["field"], "value": desired_value}
        elif row.get("setter") == "hem_definition":
            resolved, desired_value = _sheet_edit.prepare_hem(raw["hem"], before_state["hem"], design)
            desired = {"field": row["field"], "value": desired_value}
        else:
            desired_value = row["values"][mode]
            if row.get("setter") == "scale_mode" and before_state["is_uniform"] == desired_value:
                raise ValueError(f"'{label}' already has mode='{mode}'; choose the other measured mode.")
            if row.get("setter") == "scale_mode":
                factors = before_state.get("scale_expressions")
                if not isinstance(factors, list) or len(factors) != 3 or len(set(factors)) != 1:
                    raise ValueError(f"'{label}' mode changes require three readable equal scale expressions.")
            elif row.get("choices") and before_state.get(row["field"]) == desired_value:
                raise ValueError(f"'{label}' already has mode='{mode}'; choose a different value.")
            desired = {"field": row["field"], "value": _mode_value(row, mode)}
        timeline.markerPosition = index + 1
        if counted(lambda: timeline.markerPosition) != index + 1:
            raise RuntimeError("The feature could not be evaluated for its pre-edit geometry read.")
        before_geometry = _edit.feature_geometry_snapshot(design)
        if before_geometry is None:
            raise ValueError("The pre-edit body or occurrence-frame census is unreadable.")
        if row.get("verify_surface_normals"):
            old_records = before_state.get(row["field"])
            old_entities = [record[0] for record in old_records] if isinstance(old_records, list) else []
            new_entities = resolved if isinstance(resolved, list) else [resolved]
            seen = set()
            surface_targets = []
            for body in old_entities + new_entities:
                key = _common.native_identity(body)
                if key is None:
                    raise ValueError("The selected surface body identity is unreadable for normal verification.")
                if key not in seen:
                    seen.add(key)
                    surface_targets.append(body)
            surface_normals_before = _edit.surface_normal_snapshot(surface_targets)
            if surface_normals_before is None:
                raise ValueError("The selected surface face normals are unreadable or exceed the 64-face cap.")
        if safe(lambda: entity.timelineObject.rollTo(True)) is not True or counted(
                lambda: timeline.markerPosition) != index:
            raise RuntimeError("The feature could not return to its edit row.")
        prepared = _prepared(row, resolved)
        mutation_attempted = True
        _apply_value(entity, row, prepared, mode, before_state)
        timeline.markerPosition = index + 1
        if counted(lambda: timeline.markerPosition) != index + 1:
            raise RuntimeError("The edited feature could not be evaluated.")
        after_geometry = _edit.feature_geometry_snapshot(design)
        if after_geometry is None:
            raise ValueError("The post-edit body or occurrence-frame census is unreadable.")
        if surface_targets is not None:
            surface_normals_after = _edit.surface_normal_snapshot(surface_targets)
            normal_effect = _edit.surface_normals_reversed(surface_normals_before,
                                                          surface_normals_after, old_entities,
                                                          new_entities)
            if normal_effect is not True:
                raise ValueError("The selected surface face normals did not read as reversed.")
        if safe(lambda: entity.timelineObject.rollTo(True)) is not True or counted(
                lambda: timeline.markerPosition) != index:
            raise RuntimeError("The edited feature could not return to its edit row for read-back.")
        after_state, after_fields, after_unavailable = _edit.feature_edit_state(entity)
        after = _edit.feature_definition_view(entity, after_state, after_fields, after_unavailable)
        strict = row.get("identity") == "native"
        definition_matches = _definition_is(desired, before, after, before_state, after_state,
                                            strict)
        if definition_matches is None and strict:
            raise ValueError(_UNVERIFIED)
        if definition_matches is not True:
            raise ValueError("The requested definition or a disclosed retained field did not read back.")
    except Exception as exc:
        failure = str(exc)
    finally:
        if counted(lambda: timeline.markerPosition) != marker:
            try:
                timeline.markerPosition = marker
            except Exception:
                pass
    marker_restored = counted(lambda: timeline.markerPosition) == marker

    if failure and not mutation_attempted:
        return error(f"Feature edit refused: {failure}. The marker was "
                     f"{'restored' if marker_restored else 'not restored'} at {counted(lambda: timeline.markerPosition)}.")

    if mutation_attempted and failure:
        return _compensate(design, timeline, entity, row, original, label, action, before_state,
                           before, before_geometry, health_before, owner_before, token, index,
                           count, marker, after, after_geometry, definition_matches, failure,
                           surface_targets, surface_normals_before, own=(own_role, own_before))

    same = _edit.same_feature(design, token, entity, index, count)
    if own_role and marker_restored:
        own_after, own_reason = _edit.own_geometry(entity, own_role)
    owner_matches = _common.same_component(owner_before, safe(lambda: entity.parentComponent))
    feature_health = _edit.health(design, marker) if marker_restored else None
    new_errors, new_warnings = _new_health(health_before, feature_health)
    if not marker_restored or same is not True or owner_matches is not True \
            or feature_health is None or new_errors is None:
        failure = "Feature identity, marker restoration, or evaluated health could not be verified."
    elif own_role and own_after is None:
        failure = f"the edited entity's own geometry is unreadable after the edit ({own_reason})"
    elif new_errors or new_warnings:
        failure = "The edit introduced timeline health errors or warnings."
    if failure:
        return _compensate(design, timeline, entity, row, original, label, action, before_state,
                           before, before_geometry, health_before, owner_before, token, index,
                           count, marker, after, after_geometry, definition_matches, failure,
                           surface_targets, surface_normals_before, own=(own_role, own_before))

    bodies_changed = _edit.shape_match(after_geometry["bodies"], before_geometry["bodies"])[0]
    geometry_changed = None if bodies_changed is None else (
        bodies_changed is False or after_geometry["occurrences"] != before_geometry["occurrences"])
    if surface_targets is not None:
        geometry_changed = True
    details = {"feature": label, "action": action, "edited": True,
               "definition_before": before, "definition_after": after,
               "definition_matches": True,
               "geometry_before": before_geometry, "geometry_after": after_geometry,
               "geometry_changed": geometry_changed, "same_feature": same,
               "owner_matches": owner_matches,
               "marker_before": marker, "marker_after": counted(lambda: timeline.markerPosition),
               "marker_restored": marker_restored, "feature_health": feature_health,
               "new_timeline_errors": new_errors, "new_timeline_warnings": new_warnings,
               "note": meta.get("note") or (
                   "The feature definition and checked body shapes and occurrence frames were read back.")}
    if surface_targets is not None:
        details["surface_normals_reversed"] = True
    if own_role:
        if geometry_changed is False and own_after != own_before:
            details["geometry_changed"] = geometry_changed = True
        details.update(target_geometry_before=own_before, target_geometry_after=own_after)
    public = _reply_geometry_details(details)
    return _edit.identical_geometry_reply(public) if geometry_changed is False else ok(public)


tool = _inputs.apply_to_tool(
    Tool.create_simple(name="model_edit_feature", description=(
        "Edit one aspect; design_get lists typed inputs. Edits change the shared owner component definition. Dimensions: param_set.")),
    _SPEC)
tool.add_input_property("set_index", {"type": "integer", "minimum": 0})
tool.add_input_property("hem", {"type": "object", "properties": {
    "type": {"type": "string", "enum": list(_sheet_edit.HEM_KINDS)},
    "length": {"type": "string"}, "gap": {"type": "string"}, "radius": {"type": "string"},
    "angle_deg": {"type": "number"}, "setback": {"type": "string"},
    "flip": {"type": "boolean"},
    "bend_position": {"type": "string", "enum": ["start_edge", "tangent_to_side"]}},
    "additionalProperties": False, "required": ["type"],
    "description": "Hem mode redefinition; dimensions depend on type, length expressions."})
tool.strict_schema()
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(kind="inline", rung="geometry",
                              evidence_test="tests/unit/test_model_edit_feature.py::test_axis_edit_uses_real_typed_resolver_reads_back_and_restores_marker"))


def register_tool():
    register(item)
