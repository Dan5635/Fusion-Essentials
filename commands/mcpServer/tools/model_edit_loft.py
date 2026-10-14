# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Retarget or remove one interior profile section of a simple solid Loft, or reorder a surface Loft's sections."""

import hashlib
import math

import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _assert, _common, _inputs, _sketch_detail
from ._edit_feature_common import (address_text, all_shapes as _all_shapes, at_address, failed,
                                   feature_body_keys as _feature_body_keys,
                                   health as _health, identical_geometry_reply,
                                   later_operand_refusal, matched,
                                   restore_definition, restore_gaps, roll_to_edit, rolled_back_text,
                                   same_feature as _same_feature, sentence, shape_match,
                                   sketch_address)
from ._common import counted, error, ok, outcome_clause, safe


_FEATURE = _inputs.FeatureRef("feature", required=True)
_ACTION = _inputs.Choice("action", ("retarget", "remove", "reorder"), required=True)
_PROFILE = _inputs.ProfileRef("profile", scope_input="component")
_SPEC = [_FEATURE, _ACTION]
_UNREAD = object()


def _section_keys(feature):
    """Ordered native profile identities, or None when a section is unreadable."""
    sections = safe(lambda: feature.loftSections)
    count = counted(lambda: sections.count)
    if count is None or count < 2:
        return None
    keys = []
    for i in range(count):
        section = safe(lambda i=i: sections.item(i))
        entity = safe(lambda s=section: s.entity)
        if safe(lambda e=entity: e.objectType) != adsk.fusion.Profile.classType():
            return None
        key = _common.native_identity(entity)
        if key is None:
            return None
        keys.append(key)
    return tuple(keys)


def _end_state(section):
    """A Loft end's type and applicable parameter identity, expression and value."""
    condition = safe(lambda: section.endCondition)
    kind = safe(lambda: condition.objectType)
    fields = {"adsk::fusion::LoftFreeEndCondition": (),
              "adsk::fusion::LoftTangentEndCondition": ("weight",),
              "adsk::fusion::LoftSmoothEndCondition": ("weight",),
              "adsk::fusion::LoftDirectionEndCondition": ("weight", "angle"),
              "adsk::fusion::LoftPointSharpEndCondition": (),
              "adsk::fusion::LoftPointTangentEndCondition": ("weight",)}.get(kind)
    if fields is None:
        return None
    parameters = []
    for field in fields:
        param = safe(lambda f=field: getattr(condition, f))
        name = safe(lambda p=param: p.name)
        expression = safe(lambda p=param: p.expression)
        value = safe(lambda p=param: p.value)
        if (not isinstance(name, str) or not name
                or not isinstance(expression, str) or not expression
                or not isinstance(value, (int, float)) or not math.isfinite(value)):
            return None
        parameters.append((field, name, expression, value))
    return (kind, tuple(parameters))


def _definition(feature):
    """Ordered profiles and retained Loft controls at its edit position."""
    sections = _section_keys(feature)
    operation = safe(lambda: feature.operation)
    solid = safe(lambda: feature.isSolid)
    closed = safe(lambda: feature.isClosed)
    guides = counted(lambda: feature.centerLineOrRails.count)
    if (sections is None or operation is None or solid not in (True, False)
            or closed not in (True, False) or guides is None):
        return None
    last = len(sections) - 1
    ends = tuple(_end_state(safe(lambda i=i: feature.loftSections.item(i)))
                 for i in (0, last))
    if None in ends:
        return None
    return {"sections": sections, "operation": operation, "is_solid": solid,
            "is_closed": closed, "guide_count": guides, "ends": ends}


def _definition_report(definition):
    """Compact ordered definition evidence for a tool result."""
    if definition is None:
        return None
    sections = definition["sections"]
    return {"section_count": len(sections),
            "section_signatures": [hashlib.sha256(repr(key).encode("ascii")).hexdigest()[:16]
                                   for key in sections],
            "operation": definition["operation"], "is_solid": definition["is_solid"],
            "is_closed": definition["is_closed"], "guide_count": definition["guide_count"],
            "end_controls": definition["ends"]}


def _target_error(feature, label):
    """A refusal for Loft forms outside interior profile-section editing."""
    if safe(lambda: feature.objectType) != adsk.fusion.LoftFeature.classType():
        return f"'{label}' is not a Loft feature. Read design_get(include=['timeline'])."
    for name, want in (("isParametric", True), ("isSuppressed", False)):
        got = safe(lambda n=name: getattr(feature, n))
        if got is not want:
            return f"'{label}' has {name}={got}; this edit requires {name}={want}."
    if safe(lambda: feature.baseFeature, _UNREAD) is not None:
        return f"'{label}' is not a standalone parametric Loft."
    links = safe(lambda: feature.linkedFeatures)
    link_count = counted(lambda: links.count)
    if link_count != 0:
        return f"'{label}' has {link_count} linked features or an unreadable link count; this edit requires none."
    return None


def _section_at(feature, section_index):
    """The sketch address of one section's profile, or None."""
    return sketch_address(safe(lambda: feature.loftSections.item(section_index).entity))


def _settle(design, entity, label, section_index, address, rows, remedy, details, prior, where):
    """Re-assign the prior section profile (the measured reverse); the sentence its re-read backs."""
    definition_before, before_shapes, health_before = prior
    marker, index, token, count = where

    def restore():
        profile = at_address(address)
        if profile is None:
            raise RuntimeError("the prior section profile no longer resolves in its sketch")
        entity.loftSections.item(section_index).entity = profile

    back = restore_definition(
        design, entity, restore, lambda e: (_definition(e), _section_at(e, section_index)),
        index + 1, lambda: _all_shapes(design), marker)
    definition, now = back["definition"] or (None, None)
    health_back = _health(design, marker) if back["marker_after"] == marker else None
    shapes_back, recreated = shape_match(back["shapes"], before_shapes)
    why = restore_gaps(
        back["error"], definition=matched(definition, definition_before),
        shapes=shapes_back, health=matched(health_back, health_before),
        row=_same_feature(design, token, entity, index, count))
    details["rollback"] = {"ran": back["ran"], "verified": not why, "unverified": why,
                           "section_after": address_text(now), "marker_after": back["marker_after"],
                           "recreated": recreated}
    if not back["ran"]:
        return outcome_clause("kept", f"'{label}'", rows, remedy, back["error"])
    if not why:
        return rolled_back_text(rows, recreated)
    now = address_text(now)
    # model_edit_loft refuses a profile the section already reads.
    return outcome_clause("rollback_failed", f"'{label}'", [(rows[0][0], now, rows[0][2])],
                          remedy if now != rows[0][2] else "Undo it in Fusion.", "; ".join(why))


def _operand_error(profile, component, index):
    """A refusal for a foreign, future or invalid profile; index None skips the row check."""
    if safe(lambda: profile.objectType) != adsk.fusion.Profile.classType():
        return "'profile' must resolve to one sketch profile."
    sketch = safe(lambda: profile.parentSketch)
    owner = safe(lambda: sketch.parentComponent)
    row = counted(lambda: sketch.timelineObject.index)
    if _common.same_component(owner, component) is not True:
        return "'profile' is outside the Loft's owning component."
    if index is not None and (row is None or row >= index):
        return f"'profile' source row {row} must precede Loft row {index}."
    if safe(lambda: profile.isValid) is not True:
        return "'profile' is invalid at the " + (
            "current marker." if index is None else "Loft edit position.")
    return None


def _evaluated(design, entity, where, health_before, census):
    """Marker, row, health and body evidence read after an edit attempt, the marker restored."""
    marker, index, token, count = where
    before_shapes, after_shapes, target_before, target_after = census
    timeline = safe(lambda: design.timeline)
    restored = counted(lambda: timeline.markerPosition) == marker
    state, compute_failure = _assert.compute_state(entity)
    health_after = _health(design, marker) if restored else None
    new = {kind: (None if health_after is None else
                  [name for name in health_after[kind] if name not in health_before[kind]])
           for kind in ("errors", "warnings")}
    target_before_shapes = ({key: before_shapes[key]["shape"] for key in target_before}
                            if before_shapes is not None and target_before is not None
                            and target_before <= set(before_shapes) else None)
    target_after_shapes = ({key: after_shapes[key]["shape"] for key in target_after}
                           if after_shapes is not None and target_after is not None
                           and target_after <= set(after_shapes) else None)
    outside = (set(before_shapes) - target_before if before_shapes is not None
               and target_before is not None else None)
    return {"restored": restored, "same": _same_feature(design, token, entity, index, count),
            "state": state, "compute_failure": compute_failure,
            "new_errors": new["errors"], "new_warnings": new["warnings"],
            "target_before": target_before_shapes, "target_after": target_after_shapes,
            "geometry_changed": (None if target_before_shapes is None or target_after_shapes is None
                                 else sorted(target_before_shapes.values(), key=repr) !=
                                 sorted(target_after_shapes.values(), key=repr)),
            "outside_changes": (None if after_shapes is None or target_after is None or outside is None
                                else [before_shapes[key]["body"] for key in outside
                                      if key not in after_shapes or after_shapes[key] != before_shapes[key]]
                                + [after_shapes[key]["body"] for key in set(after_shapes) - set(before_shapes)
                                   if key not in target_after])}


def _missed(ev, matched):
    """The names of the post-edit checks that did not hold; `matched` is (name, verdict)."""
    return [name for name, good in (
        ("marker_restored", ev["restored"]), ("same_feature", ev["same"] is True),
        (matched[0], matched[1] is True),
        ("geometry_changed", ev["geometry_changed"] is True),
        ("outside_body_changes", ev["outside_changes"] == []),
        ("feature_health", ev["state"] == "healthy"), ("new_timeline_errors", ev["new_errors"] == []),
        ("new_timeline_warnings", ev["new_warnings"] == [])) if not good]


def _reason(failure, ev, missed):
    """The first sentence of a failed edit: the raised failure, else the first check that failed."""
    return (failure
            or ("New evaluated timeline errors or warnings appeared."
                if ev["new_errors"] or ev["new_warnings"] else "")
            or ("Material outside the Loft result changed." if ev["outside_changes"] else "")
            or (sentence(ev["compute_failure"]) if ev["compute_failure"] else "")
            or f"These checks failed: {', '.join(missed)}.")


def _order(feature):
    """(native section identities, their labels) in Loft order at the current marker, or None."""
    sections = safe(lambda: feature.loftSections)
    count = counted(lambda: sections.count)
    if count is None:
        return None
    keys, labels = [], []
    for i in range(count):
        entity = safe(lambda i=i: sections.item(i).entity)
        key = _common.native_identity(entity)
        if key is None:
            return None
        keys.append(key)
        labels.append(address_text(sketch_address(entity)) or f"section {i}")
    return tuple(keys), labels


def _reorder_scope(design, feature, owner):
    """The reads that place a Loft outside open, unguided, root-component surface lofts."""
    root = safe(lambda: design.rootComponent)
    return [f"{name}={got}" for name, got, want in (
        ("isSolid", safe(lambda: feature.isSolid), False),
        ("isClosed", safe(lambda: feature.isClosed), False),
        ("guide_count", counted(lambda: feature.centerLineOrRails.count), 0),
        ("in_root_component", _common.same_component(owner, root), True))
        if (type(got), got) != (type(want), want)]


def _reorder(entity, label, section_index, new_index):
    """Move one Loft section to `new_index` at the Loft's edit position and verify the move."""
    design = _common.design()
    timeline = safe(lambda: design.timeline)
    marker = counted(lambda: timeline.markerPosition)
    count = counted(lambda: timeline.count)
    index = counted(lambda: entity.timelineObject.index)
    token = safe(lambda: entity.entityToken)
    owner = safe(lambda: entity.parentComponent)
    if None in (marker, count, index) or not token or owner is None:
        return error(f"'{label}' has unreadable timeline identity; nothing was edited.")
    if marker <= index:
        return error(f"'{label}' is after marker {marker}; roll after it with design_edit_timeline.")
    health_before = _health(design, marker)
    if health_before is None:
        return error(f"'{label}'s evaluated-health census is unreadable; nothing was edited.")
    failure = returned = before = after = desired = None
    attempted = False
    before_shapes = after_shapes = target_before = target_after = None
    try:
        if not roll_to_edit(entity, timeline, index):
            raise RuntimeError("Fusion refused the Loft edit position.")
        before = _order(entity)
        if before is None:
            raise ValueError("The Loft section order is unreadable at its edit position.")
        outside = _reorder_scope(design, entity, owner)
        if outside:
            raise ValueError(f"It reads {', '.join(outside)}; action='reorder' takes an open, "
                             "unguided surface Loft in the root component.")
        total = len(before[0])
        if section_index >= total or new_index >= total or new_index == section_index:
            raise ValueError(f"'section_index'={section_index} and 'new_index'={new_index} must be "
                             f"two different indexes below its {total} sections.")
        desired = list(before[0])
        desired.insert(new_index, desired.pop(section_index))
        timeline.markerPosition = index + 1
        if counted(lambda: timeline.markerPosition) != index + 1:
            raise RuntimeError("The original Loft could not be evaluated for a body census.")
        before_shapes = _all_shapes(design)
        target_before = _feature_body_keys(entity)
        if before_shapes is None or not target_before:
            raise ValueError("The original Loft's body census is unreadable.")
        if not roll_to_edit(entity, timeline, index):
            raise RuntimeError("The Loft could not return to its edit position.")
        attempted = True
        returned = entity.loftSections.item(section_index).reorder(new_index)
        after = _order(entity)
        if returned is not True:
            raise RuntimeError(f"LoftSection.reorder({new_index}) returned {returned!r}.")
        timeline.markerPosition = index + 1
        if counted(lambda: timeline.markerPosition) != index + 1:
            raise RuntimeError("The reordered Loft could not be evaluated for a body census.")
        after_shapes = _all_shapes(design)
        target_after = _feature_body_keys(entity)
    except Exception as exc:
        failure = sentence(exc)
        if attempted and after is None and counted(lambda: timeline.markerPosition) == index:
            after = _order(entity)
    finally:
        safe(lambda: setattr(timeline, "markerPosition", marker))
    ev = _evaluated(design, entity, (marker, index, token, count), health_before,
                    (before_shapes, after_shapes, target_before, target_after))
    matches = after is not None and desired is not None and list(after[0]) == desired
    details = {"feature": label, "action": "reorder", "section_index": section_index,
               "new_index": new_index, "mutation_attempted": attempted, "reorder_returned": returned,
               "order_before": before[1] if before else None,
               "order_after": after[1] if after else None, "order_matches": matches,
               "geometry_changed": ev["geometry_changed"],
               "target_before": list(ev["target_before"].values()) if ev["target_before"] is not None else None,
               "target_after": list(ev["target_after"].values()) if ev["target_after"] is not None else None,
               "outside_body_changes": ev["outside_changes"],
               "outside_check": "all bodies immediately after the Loft, before downstream features",
               "same_feature": ev["same"], "marker_before": marker,
               "marker_after": counted(lambda: timeline.markerPosition),
               "marker_restored": ev["restored"], "feature_health": ev["state"],
               "new_timeline_errors": ev["new_errors"], "new_timeline_warnings": ev["new_warnings"],
               "geometry_frame": "owning_component", "geometry_units": "cm, cm2, cm3"}
    missed = _missed(ev, ("order_matches", matches))
    identical = not failure and missed == ["geometry_changed"] and ev["geometry_changed"] is False
    if not (failure or missed) or identical:
        details["edited"] = True
        details["note"] = "Loft sections reordered on the same feature. Inspect model_inspect."
        return identical_geometry_reply(details) if identical else ok(details)
    text = _reason(failure, ev, missed)
    order = lambda read: "unread" if read is None else "[" + ", ".join(read[1]) + "]"
    if not attempted:
        text += " Nothing was edited."
    elif after is None:
        text += " " + outcome_clause("unconfirmed", f"'{label}'", remedy="model_inspect",
                                     evidence="the section order did not re-read")
    elif after[0] == before[0]:
        text += " " + outcome_clause("unchanged", f"'{label}'", [("the section order", None, order(after))])
    else:
        text += " " + outcome_clause(
            "kept", f"'{label}'", [("the section order", order(after), order(before))],
            f"Restore it with model_edit_loft(feature='{label}', action='reorder', "
            f"section_index={new_index}, new_index={section_index})." if matches else "Undo it in Fusion.")
    now = counted(lambda: timeline.markerPosition)
    if now != marker:
        text += f" Also, {_common.marker_clause(marker, now, 'the edit')}."
    return failed(f"Editing '{label}': {text}", details)


def handler(feature: str = "", action: str = "", section_index: int = None,
            profile=None, component: str = "", new_index: int = None) -> dict:
    """Edit one Loft section and report definition and evaluated evidence."""
    values, refusal = _inputs.resolve_inputs(_SPEC, dict(locals()))
    if refusal:
        return refusal
    action = values["action"]
    if type(section_index) is not int or section_index < 0:
        return error(f"'section_index' must be a nonnegative integer (got {section_index!r}).")
    if action == "reorder":
        if type(new_index) is not int or new_index < 0 or profile not in (None, "", []):
            return error(f"action='reorder' takes a nonnegative integer 'new_index' (got "
                         f"{new_index!r}) and no 'profile'.")
        entity, label = values["feature"]
        refusal = _target_error(entity, label)
        return error(refusal) if refusal else _reorder(entity, label, section_index, new_index)
    if new_index is not None:
        return error(f"'new_index' is unused for action='{action}'; remove it.")
    if action == "retarget" and profile in (None, "", []):
        return error("action='retarget' requires 'profile'.")
    if action == "remove" and profile not in (None, "", []):
        return error("'profile' is unused for action='remove'; remove it.")
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
    owner = safe(lambda: entity.parentComponent)
    if None in (marker, count, index) or not token or owner is None:
        return error(f"'{label}' has unreadable timeline identity; nothing was edited.")
    if marker <= index:
        return error(f"'{label}' is after marker {marker}; roll after it with design_edit_timeline.")
    if section_index == 0:
        return error(f"Editing '{label}': 'section_index'=0 is an endpoint, not an interior section. "
                     "Choose an interior section index. Nothing was edited.")
    pending_later_refusal = later_blocker = None
    if action == "retarget":
        early, _unresolved = _PROFILE.resolve(profile, component)
        pending_later_refusal = later_operand_refusal(label, index, [early])
        if pending_later_refusal:
            later_blocker = _operand_error(early, owner, None)
    health_before = _health(design, marker)
    if health_before is None:
        return error(f"'{label}'s evaluated-health census is unreadable; nothing was edited.")
    failure = post_error_read_failure = None
    attempted = False
    definition_before = definition_after = desired = address = address_after = None
    before_shapes = after_shapes = target_before = target_after = None
    try:
        if not roll_to_edit(entity, timeline, index):
            raise RuntimeError("Fusion refused the Loft edit position.")
        definition_before = _definition(entity)
        if definition_before is None:
            raise ValueError("The Loft definition is unreadable at its edit position.")
        sections = definition_before["sections"]
        if action == "remove" and len(sections) - 1 < 2:
            raise ValueError("Removing this section would leave fewer than two Loft sections.")
        if section_index == 0 or section_index >= len(sections) - 1:
            raise ValueError(f"'section_index'={section_index} must select an interior section of {len(sections)}.")
        if (definition_before["operation"] != adsk.fusion.FeatureOperations.NewBodyFeatureOperation
                or definition_before["is_solid"] is not True or definition_before["is_closed"] is not False
                or definition_before["guide_count"] != 0):
            raise ValueError("Loft must be open, unguided, solid and use the NEW body operation.")
        if pending_later_refusal:
            # A refusal the move would not cure comes first: the advice is a lasting change.
            if later_blocker:
                raise ValueError(later_blocker)
            timeline.markerPosition = marker
            if counted(lambda: timeline.markerPosition) != marker:
                raise RuntimeError("The Loft marker could not be restored before the operand refusal.")
            return error(pending_later_refusal)
        if action == "retarget":
            operand, refusal = _PROFILE.resolve(profile, component)
            if refusal:
                raise ValueError(refusal)
            refusal = _operand_error(operand, owner, index)
            if refusal:
                raise ValueError(refusal)
            replacement = _common.native_identity(operand)
            if replacement is None:
                raise ValueError("'profile' native identity is unreadable.")
            desired = sections[:section_index] + (replacement,) + sections[section_index + 1:]
            if desired == sections:
                raise ValueError(f"'{label}' already uses that profile at section {section_index}.")
            address = _section_at(entity, section_index)
        else:
            desired = sections[:section_index] + sections[section_index + 1:]
        timeline.markerPosition = index + 1
        if counted(lambda: timeline.markerPosition) != index + 1:
            raise RuntimeError("The original Loft could not be evaluated for a body census.")
        before_shapes = _all_shapes(design)
        target_before = _feature_body_keys(entity)
        if before_shapes is None or not target_before:
            raise ValueError("The original Loft's body census is unreadable.")
        if not roll_to_edit(entity, timeline, index):
            raise RuntimeError("The Loft could not return to its edit position.")
        attempted = True
        section = entity.loftSections.item(section_index)
        if action == "retarget":
            section.entity = operand
        elif section.deleteMe() is not True:
            raise RuntimeError(f"Loft section {section_index} deleteMe() did not return true.")
        definition_after = _definition(entity)
        timeline.markerPosition = index + 1
        if counted(lambda: timeline.markerPosition) != index + 1:
            raise RuntimeError("The edited Loft could not be evaluated for a body census.")
        after_shapes = _all_shapes(design)
        target_after = _feature_body_keys(entity)
        if not roll_to_edit(entity, timeline, index):
            raise RuntimeError("The evaluated Loft could not return to its edit position.")
        definition_after = _definition(entity)
        address_after = _section_at(entity, section_index)
    except Exception as exc:
        failure = sentence(exc)
        if definition_before is not None and counted(lambda: timeline.markerPosition) == index:
            definition_after = _definition(entity)
            address_after = _section_at(entity, section_index)
        if attempted and after_shapes is None:
            try:
                timeline.markerPosition = index + 1
                if counted(lambda: timeline.markerPosition) != index + 1:
                    raise RuntimeError("The partial Loft edit could not be evaluated.")
                after_shapes = _all_shapes(design)
                target_after = _feature_body_keys(entity)
                if after_shapes is None or target_after is None:
                    raise RuntimeError("The partial Loft body census is unreadable.")
            except Exception as read_exc:
                post_error_read_failure = str(read_exc)
    finally:
        safe(lambda: setattr(timeline, "markerPosition", marker))
    ev = _evaluated(design, entity, (marker, index, token, count), health_before,
                    (before_shapes, after_shapes, target_before, target_after))
    geometry_changed, outside_changes = ev["geometry_changed"], ev["outside_changes"]
    expected_definition = (dict(definition_before, sections=desired)
                           if attempted and definition_before is not None else definition_before)
    definition_matches = matched(definition_after, expected_definition)
    details = {"feature": label, "action": action, "section_index": section_index,
               "mutation_attempted": attempted, "definition_before": _definition_report(definition_before),
               "definition_after": _definition_report(definition_after),
               "definition_matches": definition_matches, "geometry_changed": geometry_changed,
               "target_before": list(ev["target_before"].values()) if ev["target_before"] is not None else None,
               "target_after": list(ev["target_after"].values()) if ev["target_after"] is not None else None,
               "outside_body_changes": outside_changes,
               "outside_check": "all bodies immediately after the Loft, before downstream features",
               "same_feature": ev["same"], "marker_before": marker,
               "marker_after": counted(lambda: timeline.markerPosition), "marker_restored": ev["restored"],
               "feature_health": ev["state"], "unevaluated_timeline_items": count - marker,
               "post_error_read_failure": post_error_read_failure,
               "new_timeline_errors": ev["new_errors"], "new_timeline_warnings": ev["new_warnings"],
               "geometry_frame": "owning_component", "geometry_units": "cm, cm2, cm3"}
    missed = _missed(ev, ("definition_matches", definition_matches))
    identical = not failure and missed == ["geometry_changed"] and geometry_changed is False
    if (failure or missed) and not identical:
        counts = [len(d["sections"]) if d else None for d in (definition_after, definition_before)]
        if action == "remove":
            rows = [("the section count", *counts)]
            remedy = "Rebuild it with model_loft or undo it in Fusion."
        else:
            rows = [(f"section {section_index}", address_text(address_after), address_text(address))]
            remedy = ("Undo it in Fusion." if address is None else
                      f"Restore it with model_edit_loft(feature='{label}', action='retarget', "
                      f"section_index={section_index}, profile={{'sketch': "
                      f"'{safe(lambda: address[0].name)}', 'profile_index': {address[2]}}}).")
        reason = _reason(failure, ev, missed)
        if not attempted:
            text = f"{reason} Nothing was edited."
        elif (definition_after is not None and definition_after == definition_before
              and geometry_changed is False and outside_changes == []):
            text = (f"{failure or 'Fusion kept the prior definition.'} "
                    + outcome_clause("unchanged", f"'{label}'", rows))
        elif definition_after is None or definition_after == definition_before:
            text = f"{reason} " + outcome_clause(
                "unconfirmed", f"'{label}'", remedy="model_inspect", evidence=(
                    f"definition_after={'unread' if definition_after is None else 'as before'}, "
                    f"geometry_changed={geometry_changed}, outside_body_changes={outside_changes}"))
        elif action == "remove" or address is None:
            text = f"{reason} " + outcome_clause("kept", f"'{label}'", rows, remedy)
        else:
            text = f"{reason} " + _settle(design, entity, label, section_index, address, rows, remedy,
                                          details, (definition_before, before_shapes, health_before),
                                          (marker, index, token, count))
        now = counted(lambda: timeline.markerPosition)
        if now != marker:
            text += f" Also, {_common.marker_clause(marker, now, 'the edit')}."
        return failed(f"Editing '{label}': {text}", details)
    details["edited"] = True
    details["note"] = "Loft section changed on the same feature. Inspect model_inspect."
    return identical_geometry_reply(details) if identical else ok(details)


tool = _inputs.apply_to_tool(
    Tool.create_simple(name="model_edit_loft", description=(
        "Retarget, remove or reorder one Loft section. Read design_get(include=['definition']).")),
    _SPEC)
tool.add_input_property("section_index", {"type": "integer", "minimum": 0})
tool.add_required_input("section_index")
tool.add_input_property("profile", _PROFILE.schema())
tool.add_input_property(*_sketch_detail.COMPONENT_SCOPE)
tool.add_input_property("new_index", {"type": "integer", "minimum": 0})
tool.strict_schema()
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(kind="inline", rung="geometry",
                              evidence_test="tests/unit/test_model_edit_loft.py::test_ignored_retarget_is_error"))


def register_tool():
    register(item)
