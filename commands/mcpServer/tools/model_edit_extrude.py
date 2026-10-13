# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Edit one definition of an existing solid Extrude feature."""

import hashlib
import math

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _assert, _common, _design_common, _geom, _inputs
from ._common import counted, error, ok, outcome_clause, safe
from ._edit_feature_common import (at_address, extrude_tapers, failed, health as _health,
                                   identical_geometry_reply, later_operand_refusal, matched,
                                   read_extrude_definition, extrude_extent_kind as _extent_kind,
                                   restore_definition, restore_gaps,
                                   same_feature as _same_feature, sentence, sketch_address)
from .model_extrude import _start_definition_readback


_FEATURE = _inputs.FeatureRef("feature", required=True)
_ACTION = _inputs.Choice("action", ("profile", "operation", "participants", "extent", "start"), required=True)
_PROFILE = _inputs.ProfileRef("profile")
_OPERATION = _inputs.boolean_op(default=None, description="")
_BODIES = _inputs.BodyRefList("target_bodies", kind="solid")
_EXTENT = _inputs.Choice("extent", ("distance", "symmetric", "two_side", "to_face", "through_all"))
_DIRECTION = _inputs.Choice("direction", ("positive", "negative", "both"),
                            description="Unset keeps a one-sided side.")
_FACE = _inputs.GeometryHandle("to_object", require="face")
_START_OBJECT = _inputs.PlaneRef("start_object")
_UNITS = _inputs.UnitField()
_SPEC = [_FEATURE, _ACTION, _PROFILE, _OPERATION, _BODIES, _EXTENT, _DIRECTION, _FACE, _UNITS]
_UNREAD = object()


def _members_match(actual, requested):
    """Whether a native participant list contains exactly the requested bodies."""
    if actual is None:
        return None
    return len(actual) == len(requested) and all(
        any(_common._native_of(body) == _common._native_of(want) for body in actual)
        for want in requested)


def _definition_matches(feature, action, values):
    """Read back the requested definition while the marker is at the edit position."""
    if "preserved_bodies" in values and _members_match(
            safe(lambda: list(feature.participantBodies)), values["preserved_bodies"]) is not True:
        return False
    if action == "profile":
        return safe(lambda: _common._native_of(feature.profile) == values["profile"])
    if action in ("operation", "participants"):
        matched = True
        if action == "operation":
            matched = safe(lambda: feature.operation == values["native_operation"])
        if values["target_bodies"]:
            bodies = safe(lambda: list(feature.participantBodies))
            matched = matched is True and _members_match(bodies, values["target_bodies"])
        return matched
    if action == "start":
        kind, offset, why = _start_definition_readback(
            safe(lambda: feature.startExtent), values["start_kind"], values["start_cm"],
            design=values["design"])
        if why or kind != values["start_kind"]:
            return False
        if values["start_object"] is not None:
            landed = safe(lambda: feature.startExtent.entity)
            return (_common.native_identity(landed) is not None
                    and _common.native_identity(landed) ==
                    _common.native_identity(values["start_object"]))
        return offset is not None
    kind = values["extent"]
    if _extent_kind(feature) != kind:
        return False
    start = safe(lambda: feature.startExtent)
    landed_start_offset = safe(lambda: start.offset.value)
    expected_start_offset = values.get("start_offset_cm")
    if expected_start_offset is not None:
        if (not isinstance(expected_start_offset, (int, float)) or isinstance(expected_start_offset, bool)
                or not math.isfinite(expected_start_offset)
                or not isinstance(landed_start_offset, (int, float))
                or isinstance(landed_start_offset, bool) or not math.isfinite(landed_start_offset)):
            return False
    if ("start_kind" in values and safe(lambda: start.objectType) != values["start_kind"]
            or values.get("start_offset_cm") is not None
                and abs(landed_start_offset - expected_start_offset) > _common.EXTENT_MATCH_TOL_CM
            or values.get("start_entity") is not None
                and _common.native_identity(safe(lambda: start.entity)) != values["start_entity"]):
        return False
    offset = safe(lambda: start.offset)
    if (values.get("start_offset_name") is not None
            and safe(lambda: offset.name) != values["start_offset_name"]
            or values.get("start_offset_expression") is not None
            and safe(lambda: offset.expression) != values["start_offset_expression"]):
        return False
    current_tapers = extrude_tapers(feature)
    expected_tapers = values.get("expected_taper_expressions")
    if expected_tapers is not None:
        expected_values = values["expected_taper_values"]
        expected_names = values["expected_taper_names"]
        if len(current_tapers) != len(expected_tapers):
            return False
        for index, (row, expression) in enumerate(zip(current_tapers, expected_tapers)):
            if (row["expression"] != expression or row["value"] is None
                    or abs(row["value"] - expected_values[index]) > 1e-12
                    or (expected_names[index] is not None
                        and row["name"] != expected_names[index])):
                return False
    if kind == "to_face":
        return safe(lambda: _common._native_of(feature.extentOne.entity) == values["to_object"]
                    and feature.extentOne.isChained is False
                    and abs(feature.extentOne.offset.value) < _common.EXTENT_MATCH_TOL_CM)
    if kind == "through_all":
        return (safe(lambda: feature.hasTwoExtents) is True if values["direction"] == "both"
                else safe(lambda: feature.hasTwoExtents) is False
                and safe(lambda: feature.extentOne.isPositiveDirection)
                is (values["direction"] == "positive"))
    distances = [_common.landed_extent_cm(feature)]
    if kind == "two_side":
        distances.append(_common.landed_extent2_cm(feature))
    if kind == "symmetric" and safe(lambda: feature.symmetricExtent.isFullLength) is not False:
        return False
    return all(got is not None and abs(got - want) <= _common.EXTENT_MATCH_TOL_CM
               for got, want in zip(distances, values["depths"]))


def _prepare(action, values, raw, design, entity):
    """Validate the action and prepare its definition inputs without changing the feature."""
    allowed = {"profile": {"profile"}, "operation": {"operation", "target_bodies"},
               "participants": {"target_bodies"},
               "extent": {"extent", "distance", "distance2", "units", "to_object", "direction"},
               "start": {"start_object", "start_offset", "units"}}
    for name in ("profile", "operation", "target_bodies", "extent", "distance", "distance2",
                 "to_object", "direction", "start_object", "start_offset"):
        if raw[name] not in (None, "", []) and name not in allowed[action]:
            return f"'{name}'={raw[name]!r} is not used by action='{action}'. Remove it."
    scoped_operation = safe(lambda: entity.operation) in (
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        adsk.fusion.FeatureOperations.IntersectFeatureOperation)
    assigns_scope = (action in ("profile", "extent", "participants", "start") and scoped_operation
                     or action == "operation" and values["operation"] in ("cut", "intersect"))
    requested_both = (action == "extent" and values["extent"] == "through_all"
                      and values["direction"] == "both" and scoped_operation)
    if (requested_both or assigns_scope and safe(lambda: entity.hasTwoExtents) is True
            and _extent_kind(entity) == "through_all"):
        return ("Two-sided through_all with cut/intersect participant assignment is unsupported. "
                "Use separate one-sided features or the Fusion UI.")
    if action == "profile":
        return None if values["profile"] is not None else "action='profile' requires 'profile'."
    if action == "operation":
        op = values["operation"]
        if not op:
            return "action='operation' requires 'operation'."
        values["native_operation"] = getattr(adsk.fusion.FeatureOperations, _common.OPERATIONS[op])
        if op in ("cut", "intersect") and not values["target_bodies"]:
            return f"operation='{op}' requires explicit 'target_bodies'."
        if op in ("new", "join") and values["target_bodies"]:
            return f"operation='{op}' does not take 'target_bodies'."
    if action == "participants":
        if not values["target_bodies"]:
            return "action='participants' requires nonempty 'target_bodies'."
        if safe(lambda: entity.operation) not in (
                adsk.fusion.FeatureOperations.CutFeatureOperation,
                adsk.fusion.FeatureOperations.IntersectFeatureOperation):
            return "action='participants' requires an existing cut/intersect Extrude."
    if action == "start":
        source = safe(lambda: entity.startExtent.objectType)
        if source not in ("adsk::fusion::ProfilePlaneStartDefinition",
                          "adsk::fusion::OffsetStartDefinition",
                          "adsk::fusion::FromEntityStartDefinition"):
            return f"Existing start definition {source!r} is unsupported; inspect the Extrude in Fusion."
        scale = _common.scale(raw["units"] or "mm")
        if scale is None:
            return f"Unknown units '{raw['units']}'; use mm, cm or in."
        if raw["start_offset"] is None and not raw["start_object"]:
            return "action='start' requires 'start_offset' or 'start_object'."
        offset = raw["start_offset"] if raw["start_offset"] is not None else 0
        val, cm, why = _inputs.length_value_input(offset, scale, design, "start_offset")
        if why:
            return why
        if cm is None or not math.isfinite(cm):
            return f"'start_offset'={offset!r} must evaluate to a finite length."
        values["start_input"], values["start_cm"], values["design"] = val, cm, design
        values["start_kind"] = ("adsk::fusion::FromEntityStartDefinition" if values["start_object"]
                                else "adsk::fusion::OffsetStartDefinition")
        return None
    if action != "extent":
        return None
    kind = values["extent"]
    if not kind:
        return "action='extent' requires 'extent'."
    start = safe(lambda: entity.startExtent)
    start_kind = safe(lambda: start.objectType)
    if start_kind not in ("adsk::fusion::ProfilePlaneStartDefinition",
                          "adsk::fusion::OffsetStartDefinition",
                          "adsk::fusion::FromEntityStartDefinition"):
        return f"Existing start definition {start_kind!r} is unsupported; inspect the Extrude in Fusion."
    start_offset = (safe(lambda: start.offset.value)
                    if start_kind in ("adsk::fusion::OffsetStartDefinition",
                                      "adsk::fusion::FromEntityStartDefinition") else None)
    start_entity = (_common.native_identity(safe(lambda: start.entity))
                    if start_kind == "adsk::fusion::FromEntityStartDefinition" else None)
    if (start_kind == "adsk::fusion::FromEntityStartDefinition" and
            (start_entity is None or start_offset is None)):
        return "Existing from-entity start identity or offset is unreadable; inspect the Extrude in Fusion."
    offset_object = safe(lambda: start.offset)
    offset_name = safe(lambda: offset_object.name)
    offset_expression = safe(lambda: offset_object.expression)
    if start_kind in ("adsk::fusion::OffsetStartDefinition",
                      "adsk::fusion::FromEntityStartDefinition") and start_offset is None:
        return "Existing start offset value is unreadable; inspect the Extrude in Fusion."
    if (start_kind in ("adsk::fusion::OffsetStartDefinition",
                       "adsk::fusion::FromEntityStartDefinition")
            and (not isinstance(start_offset, (int, float)) or isinstance(start_offset, bool)
                 or not math.isfinite(start_offset))):
        return "Existing start offset value is non-finite; inspect the Extrude in Fusion."
    if (start_kind in ("adsk::fusion::OffsetStartDefinition",
                       "adsk::fusion::FromEntityStartDefinition")
            and (not isinstance(offset_name, str) or not offset_name
                 or not isinstance(offset_expression, str) or not offset_expression.strip())):
        return "Existing start offset parameter identity or expression is unreadable; inspect the Extrude in Fusion."
    values["start_kind"], values["start_offset_cm"], values["start_entity"] = (
        start_kind, start_offset, start_entity)
    values["start_offset_name"], values["start_offset_expression"] = offset_name, offset_expression
    tapers = extrude_tapers(entity)
    taper_expressions = [row["expression"] for row in tapers]
    taper_values = [row["value"] for row in tapers]
    taper_names = [row["name"] for row in tapers]
    if (any(value is None or not math.isfinite(value) for value in taper_values)
            or any(not isinstance(expression, str) or not expression.strip()
                   for expression in taper_expressions)
            or any(not isinstance(name, str) or not name for name in taper_names)):
        return "Existing taper definition is unreadable; inspect param_get before changing the extent."
    if any(abs(value) > 1e-12 for value in taper_values) and kind not in (
            "distance", "symmetric", "two_side"):
        return f"extent='{kind}' with a nonzero taper is unsupported; use distance, symmetric or two_side."
    if (_extent_kind(entity) == "two_side" and kind != "two_side"
            and any(abs(value) > 1e-12 for value in taper_values)):
        return "A two-sided source cannot change to this extent without losing side parameter identity."
    values["taper_expressions"] = taper_expressions
    values["has_two_extents"] = safe(lambda: entity.hasTwoExtents) is True
    values["taper_inputs"] = [adsk.core.ValueInput.createByString(expression)
                               for expression in taper_expressions]
    used = {"distance": {"distance", "units", "direction"}, "symmetric": {"distance", "units"},
            "two_side": {"distance", "distance2", "units"}, "to_face": {"to_object"},
            "through_all": {"direction"}}[kind]
    for name in ("distance", "distance2", "to_object", "direction"):
        if raw[name] not in (None, "", []) and name not in used:
            return f"'{name}'={raw[name]!r} is not used by extent='{kind}'. Remove it."
    if kind == "through_all" and values["direction"] is None:
        return "extent='through_all' requires 'direction'."
    if kind == "to_face" and values["to_object"] is None:
        return "extent='to_face' requires 'to_object'."
    side = values["direction"] if kind == "distance" else "positive"
    if kind == "distance" and side is None:
        current = _extent_kind(entity)
        side = values["kept_side"] = (_side(entity, current)
                                      if current in ("distance", "through_all") else "both")
        side = "positive" if side == "both" else side
    if side is None:
        return "The feature's current side is unreadable; pass direction 'positive' or 'negative'."
    if side == "both":
        return "direction='both' does not set one side for extent='distance'; pass 'positive' or 'negative'."
    depths, inputs = [], []
    for name in (["distance", "distance2"] if kind == "two_side" else
                 ["distance"] if kind in ("distance", "symmetric") else []):
        scale = _common.scale(raw["units"] or "mm")
        if scale is None:
            return f"Unknown units '{raw['units']}'; use mm, cm or in."
        val, cm, why = _inputs.length_value_input(raw[name], scale, design, name)
        if why:
            return why
        if cm is None or not math.isfinite(cm) or cm <= 0:
            return f"'{name}'={raw[name]!r} must evaluate to a positive length."
        depths.append(cm)
        inputs.append(val)
    values["depths"], values["length_inputs"] = depths, inputs
    if side == "negative":
        text = raw["distance"]
        values["depths"] = [-depths[0]]
        values["expression"] = (f"-({text.strip()})" if _inputs.looks_like_expression(text) else
                                f"-{_inputs.expression_report(text)} {raw['units'] or 'mm'}")
    if kind == "two_side" or kind == "through_all" and values["direction"] == "both":
        indices = [0, 1 if len(taper_expressions) > 1 else None]
    else:
        indices = [0]
    source_indices = [i if i is not None else 0 for i in indices]
    values["expected_taper_expressions"] = [taper_expressions[i] if indices[position] is not None
                                             else "0 deg"
                                             for position, i in enumerate(source_indices)]
    values["expected_taper_values"] = [taper_values[i] if indices[position] is not None else 0.0
                                      for position, i in enumerate(source_indices)]
    values["expected_taper_names"] = [taper_names[i] if i is not None else None for i in indices]
    return None


def _apply_edit(feature, action, values):
    """Apply one semantic definition change; exceptions retain any native partial change."""
    if action == "profile":
        feature.profile = values["profile"]
    elif action in ("operation", "participants"):
        if action == "operation":
            feature.operation = values["native_operation"]
        if values["target_bodies"]:
            feature.participantBodies = list(values["target_bodies"])
    elif action == "start":
        if values["start_object"] is not None:
            feature.startExtent = adsk.fusion.FromEntityStartDefinition.create(
                values["start_object"], values["start_input"])
        else:
            feature.startExtent = adsk.fusion.OffsetStartDefinition.create(values["start_input"])
    else:
        kind = values["extent"]
        lengths = values["length_inputs"]
        distance = adsk.fusion.DistanceExtentDefinition.create
        through = adsk.fusion.ThroughAllExtentDefinition.create
        positive = adsk.fusion.ExtentDirections.PositiveExtentDirection
        expression = values.get("expression")
        if kind == "distance" and expression and _extent_kind(feature) == "distance":
            applied = True
        elif kind == "symmetric":
            applied = feature.setSymmetricExtent(lengths[0], False, values["taper_inputs"][0])
        elif kind == "two_side":
            taper_two = (values["taper_inputs"][1] if len(values["taper_inputs"]) > 1
                         else adsk.core.ValueInput.createByString("0 deg"))
            applied = feature.setTwoSidesExtent(distance(lengths[0]), distance(lengths[1]),
                                                values["taper_inputs"][0], taper_two)
        elif kind == "through_all" and values["direction"] == "both":
            taper_two = values["taper_inputs"][-1]
            applied = feature.setTwoSidesExtent(through(), through(),
                                                values["taper_inputs"][0], taper_two)
        else:
            extent = (distance(lengths[0]) if kind == "distance" else through()
                      if kind == "through_all" else
                      adsk.fusion.ToEntityExtentDefinition.create(values["to_object"], False))
            direction = positive
            if kind == "through_all" and values["direction"] == "negative":
                extent.isPositiveDirection = False
                direction = adsk.fusion.ExtentDirections.NegativeExtentDirection
            taper = (values["taper_inputs"][-1]
                     if values.get("has_two_extents") and
                     direction == adsk.fusion.ExtentDirections.NegativeExtentDirection
                     else values["taper_inputs"][0])
            applied = feature.setOneSideExtent(extent, direction, taper)
        if applied is not True:
            raise RuntimeError(f"The '{kind}' extent setter returned false.")
        if expression:
            # A one-sided distance takes the side its parameter's signed expression names (measured).
            feature.extentOne.distance.expression = expression
    if "preserved_bodies" in values:
        feature.participantBodies = list(values["preserved_bodies"])


def _replay_scope(feature, timeline, index, scoped):
    """Evaluate the feature, roll back to it, and assign its participant scope again."""
    # Evaluation can cut a sibling despite the first participant assignment.
    # Replaying the same scope after evaluation removes that collateral material change.
    timeline.markerPosition = index + 1
    if counted(lambda: timeline.markerPosition) != index + 1:
        raise RuntimeError("The feature could not be evaluated before participant replay.")
    if (feature.timelineObject.rollTo(True) is not True
            or counted(lambda: timeline.markerPosition) != index):
        raise RuntimeError("The feature could not be rolled back for participant replay.")
    feature.participantBodies = list(scoped)


def _restorer(feature, action, before, after, values, address, timeline, index):
    """The measured reverse of this edit as a callable, or None where the reverse is unmeasured."""
    scoped = values.get("preserved_bodies")
    after = after or {}
    # Measured: a distance extent's prior signed expression written back into the same parameter.
    same_parameter = (before["extent"] == after.get("extent") == "distance"
                      and bool(before["distance_expression"]) and bool(before["distance_parameter"])
                      and after.get("distance_parameter") == before["distance_parameter"])
    if not (action == "profile" and address is not None or action == "extent" and same_parameter):
        return None

    def restore():
        if action == "profile":
            profile = at_address(address)
            if profile is None:
                raise RuntimeError("the prior profile no longer resolves in its sketch")
            feature.profile = profile
        else:
            feature.extentOne.distance.expression = before["distance_expression"]
        if scoped:
            feature.participantBodies = list(scoped)
            _replay_scope(feature, timeline, index, scoped)
    return restore


def _settle(design, entity, label, action, values, address, rows, remedy, prior, where, out):
    """Roll a landed edit back where its reverse is measured; the outcome sentence the re-read backs."""
    definition_before, before, siblings, health_before = prior
    marker, index, token, count = where
    restore = _restorer(entity, action, definition_before, out["definition_after"], values, address,
                        safe(lambda: design.timeline), index)
    if restore is None:
        return outcome_clause("kept", f"'{label}'", rows, remedy)
    component = safe(lambda: entity.parentComponent)
    back = restore_definition(
        design, entity, restore, _definition, marker,
        lambda: (_geometry(component), [_geometry(c) for c, _ in siblings]), marker)
    shapes = back["shapes"]
    unread = shapes is None or shapes[0] is None or None in shapes[1]
    health_back = _health(design, marker) if back["marker_after"] == marker else None
    why = restore_gaps(
        back["error"], definition=matched(back["definition"], definition_before),
        shapes=None if unread else shapes == (before, [geometry for _, geometry in siblings]),
        health=matched(health_back, health_before),
        row=_same_feature(design, token, entity, index, count))
    out["rollback"] = {"ran": back["ran"], "verified": not why, "unverified": why,
                       "definition_after": back["definition"], "marker_after": back["marker_after"]}
    if not back["ran"]:
        return outcome_clause("kept", f"'{label}'", rows, remedy, back["error"])
    if not why:
        return outcome_clause("rolled_back", f"'{label}'", rows,
                              evidence="the bodies match the pre-edit read")
    return outcome_clause("rollback_failed", f"'{label}'",
                          _rows(action, definition_before, back["definition"]),
                          _remedy(label, action, definition_before, back["definition"]),
                          "; ".join(why))


def _geometry(component):
    """The component's solid-body volume, area, bounds and face signature, or None."""
    bodies = safe(lambda: component.bRepBodies)
    count = counted(lambda: bodies.count)
    if count is None:
        return None
    rows = []
    for i in range(count):
        body = safe(lambda: bodies.item(i))
        solid = safe(lambda: body.isSolid)
        if solid is None:
            return None
        if not solid:
            continue
        volume = _geom.signed_volume(body)
        area = _geom.areas([body]).get(id(body))
        bounds = _geom._aabb_extents(body)
        if volume is None or not isinstance(area, (int, float)) or bounds is None:
            return None
        faces = safe(lambda: body.faces)
        face_count = counted(lambda: faces.count)
        if not face_count:
            return None
        samples = []
        for j in range(face_count):
            face = safe(lambda: faces.item(j))
            face_area = safe(lambda: face.area)
            centroid = _geom._coords(safe(lambda: face.centroid))
            if (not isinstance(face_area, (int, float)) or isinstance(face_area, bool)
                    or centroid is None or not all(math.isfinite(v) for v in (face_area, *centroid))):
                return None
            samples.append((round(float(face_area), 9) or 0.0,
                            *[round(float(v), 7) or 0.0 for v in centroid]))
        # PhysicalProperties can retain collateral-cut mass after native faces are restored.
        signature = hashlib.sha256(repr(sorted(samples)).encode("ascii")).hexdigest()
        rows.append([round(volume, 9), round(area, 9),
                     *[round(v, 7) for pair in bounds for v in pair],
                     face_count, signature])
    return sorted(rows)


def _profile_source(feature, component, profile=_UNREAD):
    """The native profile and one verified owning sketch, or a refusal."""
    profile = _common._native_of(safe(lambda: feature.profile) if profile is _UNREAD else profile)
    if isinstance(profile, adsk.fusion.Profile):
        sketch = _common._native_of(safe(lambda: profile.parentSketch))
        if _common.same_component(component, safe(lambda: sketch.parentComponent)) is not True:
            return profile, sketch, False, ("The feature does not own its profile; address the "
                                           "original Extrude, not its linked alias.")
        return profile, sketch, False, None
    if safe(lambda: profile.objectType) != "adsk::core::ObjectCollection":
        return profile, None, False, "The feature's profile is unreadable; inspect its definition."
    size = counted(lambda: profile.count)
    if size is None or size <= 0:
        return profile, None, True, ("The feature's profile collection is empty or unreadable; "
                                     "inspect its definition.")
    sketch, identity = None, None
    for i in range(size):
        member = _common._native_of(safe(lambda i=i: profile.item(i)))
        if not isinstance(member, adsk.fusion.Profile):
            return profile, None, True, ("The feature's profile collection has an unreadable or "
                                         "non-profile member; inspect its definition.")
        owner_sketch = _common._native_of(safe(lambda: member.parentSketch))
        owner_identity = _common.native_identity(owner_sketch)
        if owner_identity is None:
            return profile, None, True, ("The feature's profile collection has an unreadable "
                                         "sketch identity; inspect its definition.")
        same_owner = _common.same_component(component, safe(lambda: owner_sketch.parentComponent))
        if same_owner is None:
            return profile, None, True, ("The feature's profile collection has an unreadable "
                                         "component owner; inspect its definition.")
        if same_owner is False:
            return profile, None, True, ("The feature's profile collection includes a profile "
                                         "outside its owning component; inspect the source Extrude.")
        if identity is not None and owner_identity != identity:
            return profile, None, True, ("The feature's profile collection spans sketches; "
                                         "inspect the source Extrude.")
        sketch, identity = owner_sketch, owner_identity
    return profile, sketch, True, None


def _side(feature, kind):
    """The side a one-sided extent points to, 'both' for a two-sided through_all, else None."""
    if kind == "distance":
        cm = _common.landed_extent_cm(feature)
        return None if cm is None else "negative" if cm < 0 else "positive"
    if kind != "through_all":
        return None
    if safe(lambda: feature.hasTwoExtents) is True:
        return "both"
    flag = _common.read_flag(lambda: feature.extentOne.isPositiveDirection)
    return None if flag is None else "positive" if flag else "negative"


def _definition(feature):
    """The definition fields readable at the feature's edit position, distances signed in cm."""
    read = read_extrude_definition(feature)
    profile, sketch, collection, _ = _profile_source(
        feature, safe(lambda: feature.parentComponent), read["profile"])
    address = None if collection else sketch_address(profile)
    start = safe(lambda: feature.startExtent)
    start_kind = safe(lambda: start.objectType)
    start_entity = safe(lambda: start.entity) if start_kind == "adsk::fusion::FromEntityStartDefinition" else None
    start_offset = safe(lambda: start.offset) if start_kind in (
        "adsk::fusion::OffsetStartDefinition", "adsk::fusion::FromEntityStartDefinition") else None
    return {"profile_sketch": safe(lambda: sketch.name),
            "profile_index": address[2] if address and address[1] == "profile" else None,
            "start_kind": start_kind,
            "start_offset_cm": (safe(lambda: start.offset.value)
                                if start_kind in ("adsk::fusion::OffsetStartDefinition",
                                                  "adsk::fusion::FromEntityStartDefinition") else None),
            "start_offset_parameter": safe(lambda: start_offset.name),
            "start_offset_expression": safe(lambda: start_offset.expression),
            "start_entity": _common.native_identity(start_entity) if start_entity is not None else None,
            "start_entity_name": safe(lambda: start_entity.name),
            **{key: read[key] for key in ("operation", "extent", "distance_cm", "distance2_cm",
                "distance_parameter", "distance_expression", "participants", "tapers")},
            "side": _side(feature, read["extent"])}

def _described(definition):
    """A definition read's action-level fields as an outcome sentence quotes them."""
    d = definition or {}
    mm = lambda key: None if d.get(key) is None else round(d[key] * _common.CM_TO_UNIT["mm"], 6)
    extent = {"distance": f"distance {mm('distance_cm')} mm",
              "symmetric": f"symmetric {mm('distance_cm')} mm per side",
              "two_side": f"two_side {mm('distance_cm')} mm and {mm('distance2_cm')} mm",
              "through_all": f"through_all {d.get('side')}"}.get(d.get("extent"), d.get("extent"))
    profile = (f"sketch '{d.get('profile_sketch')}' profile {d['profile_index']}"
               if d.get("profile_index") is not None else d.get("profile_sketch"))
    parameter = (f"{d['distance_parameter']} = {d.get('distance_expression')}"
                 if d.get("distance_parameter") else None)
    start_kind = (d.get("start_kind") or "").rsplit("::", 1)[-1]
    start = ("profile plane" if start_kind == "ProfilePlaneStartDefinition" else
             f"offset {mm('start_offset_cm')} mm" if start_kind == "OffsetStartDefinition" else
             f"{d.get('start_entity_name') or d.get('start_entity')} + {mm('start_offset_cm')} mm"
             if start_kind == "FromEntityStartDefinition" else d.get("start_kind"))
    return {"profile": profile, "operation": d.get("operation"),
            "participants": d.get("participants"), "extent": extent, "start": start,
            "distance parameter": parameter}


def _rows(action, before, after):
    """(field, now, was) for each field the edit moved, else for the action's own field."""
    was, now = _described(before), _described(after)
    # A parameter row is quoted only where both sides carry one; the extent row names a kind change.
    rows = [(field, now[field], was[field]) for field in now if now[field] != was[field]
            and (field != "distance parameter" or None not in (now[field], was[field]))]
    return rows or [(action, now[action], was[action])]


def _remedy(label, action, before, after):
    """A call that re-applies the prior definition for this action, else how to undo it."""
    d, now = before or {}, after or {}
    was, got = _described(d), _described(now)
    call = f"Restore it with model_edit_extrude(feature='{label}', action='{action}', "
    mm = lambda key: None if d.get(key) is None else round(abs(d[key]) * _common.CM_TO_UNIT["mm"], 6)
    # model_edit_extrude refuses a profile or extent the feature already reads; a to_face text
    # does not name its face, so it is never read as the same extent.
    if action == "profile":
        return (f"{call}profile={{'sketch': '{d.get('profile_sketch')}', "
                f"'profile_index': {d['profile_index']}}})."
                if d.get("profile_index") is not None and got["profile"] != was["profile"]
                else "Undo it in Fusion.")
    if action in ("operation", "participants"):
        args = [f"operation='{d.get('operation')}'"] if action == "operation" else []
        if d.get("operation") in ("cut", "intersect"):
            args.append(f"target_bodies={d.get('participants')}")
        return call + ", ".join(args) + ")."
    if action == "start":
        if d.get("start_kind") == "adsk::fusion::OffsetStartDefinition" and d.get("start_offset_cm") is not None:
            offset_mm = round(d["start_offset_cm"] * _common.CM_TO_UNIT["mm"], 6)
            return f"{call}start_offset={offset_mm})."
        return "Undo the start change in Fusion."
    kind, names = d.get("extent"), (d.get("distance_parameter"), now.get("distance_parameter"))
    if (kind == "distance" and d.get("distance_expression") and now.get("extent") == "distance"
            and names[0] and names[0] == names[1]
            and got["distance parameter"] != was["distance parameter"]):
        return (f"Restore it with param_set(name='{d['distance_parameter']}', "
                f"expression='{d['distance_expression']}').")
    if got["extent"] == was["extent"] and kind != "to_face":
        return ("No tool call restores the distance parameter's name. Undo it in Fusion."
                if None not in names and names[0] != names[1] else "Undo it in Fusion.")
    args = {"distance": f"distance={mm('distance_cm')}, direction='{d.get('side')}'",
            "symmetric": f"distance={mm('distance_cm')}",
            "two_side": f"distance={mm('distance_cm')}, distance2={mm('distance2_cm')}",
            "through_all": f"direction='{d.get('side')}'"}.get(kind)
    if args:
        return f"{call}extent='{kind}', {args})."
    return (f"{call}extent='to_face', to_object=<find_geometry face handle>) or undo it in Fusion."
            if kind == "to_face" else "Undo it in Fusion.")


def _target_error(feature, label):
    """Why this feature is outside the supported solid Extrude edit scope."""
    if safe(lambda: feature.objectType) != adsk.fusion.ExtrudeFeature.classType():
        return f"'{label}' is not an Extrude feature. Use design_get(include=['timeline'])."
    flags = (("isParametric", True), ("isSolid", True),
             ("isSuppressed", False), ("isThinExtrude", False))
    for prop, wanted in flags:
        got = safe(lambda prop=prop: getattr(feature, prop))
        if got is not wanted:
            return f"'{label}' has {prop}={got}; this edit requires {prop}={wanted}."
    if safe(lambda: feature.baseFeature, _UNREAD) is not None:
        return f"'{label}' is not a verified standalone parametric feature. Inspect design_get."
    links = counted(lambda: feature.linkedFeatures.count)
    if links is None or links > 1:
        return f"'{label}' has unreadable or multiple linked features; only one linked alias is supported."
    return None


def _linked_scope_error(feature, component, components, index):
    """Refuse foreign-profile aliases and unverified linked-feature structures while rolled."""
    profile, _, collection, refusal = _profile_source(feature, component)
    if refusal:
        return refusal
    links = safe(lambda: list(feature.linkedFeatures))
    if links is None or len(links) > 1:
        return "Linked features are unreadable or exceed the supported one-alias scope."
    if collection and links:
        return "Linked profile collections are unverified; inspect the source Extrude."
    for linked in links:
        owner = safe(lambda: linked.parentComponent)
        reciprocal = safe(lambda: list(linked.linkedFeatures))
        participants = safe(lambda: list(feature.participantBodies))
        if (safe(lambda: linked.objectType) != adsk.fusion.ExtrudeFeature.classType()
                or safe(lambda: linked.assemblyContext, _UNREAD) is not None
                or _common.same_component(component, owner) is not False
                or not any(_common.same_component(owner, c) is True for c in components)
                or counted(lambda: linked.timelineObject.index) != index
                or safe(lambda: _common._native_of(linked.profile) == profile) is not True
                or counted(lambda: linked.bodies.count) != 0
                or reciprocal is None or len(reciprocal) != 1 or reciprocal[0] != feature
                or participants is None
                or _members_match(safe(lambda: list(linked.participantBodies)), participants) is not True):
            return "The linked feature is not a verified native alias of this Extrude."
    return None


def handler(feature: str = "", action: str = "", profile=None, operation: str = "",
            target_bodies=None, extent: str = "", distance=None, distance2=None,
            units: str = "mm", to_object: str = "", direction: str = "",
            start_object: str = "", start_offset=None) -> dict:
    """Edit one Extrude definition and verify its native and geometric effect."""
    raw = dict(locals())
    values, refusal = _inputs.resolve_inputs(_SPEC, raw)
    if refusal:
        return refusal
    entity, label = values["feature"]
    profile_entity = values["profile"]
    action = values["action"]
    refusal = _target_error(entity, label)
    if refusal:
        return error(refusal)
    values["start_object"] = None
    if start_object:
        values["start_object"], refusal = _START_OBJECT.resolve(
            start_object, component=safe(lambda: entity.parentComponent))
        if refusal:
            return error(refusal)
    design = _common.design()
    refusal = _prepare(action, values, raw, design, entity)
    if refusal:
        return error(refusal)
    timeline = safe(lambda: design.timeline)
    marker = counted(lambda: timeline.markerPosition)
    count = counted(lambda: timeline.count)
    index = counted(lambda: entity.timelineObject.index)
    token = safe(lambda: entity.entityToken)
    if marker is None or count is None or index is None or not token:
        return error(f"'{label}' has unreadable timeline identity; nothing was edited.")
    if marker <= index:
        return error(f"'{label}' is after marker {marker}; roll after it with design_edit_timeline.")
    component = safe(lambda: entity.parentComponent)
    values["target_bodies"] = [_common._native_of(body) for body in values["target_bodies"]]
    for key in ("profile", "to_object", "start_object"):
        if values[key] is not None:
            values[key] = _common._native_of(values[key])
    profile_entity = values["profile"]
    operands = list(values["target_bodies"])
    if profile_entity is not None:
        sketch = safe(lambda: profile_entity.parentSketch)
        if _common.same_component(component, safe(lambda: sketch.parentComponent)) is not True:
            return error(f"profile '{profile}' must belong to '{label}'s owning component.")
        refusal = later_operand_refusal(label, index, [profile_entity])
        if refusal:
            return error(refusal)
        if counted(lambda: sketch.timelineObject.index) is None:
            hint = _design_common.collapsed_group_hint_for(timeline, sketch,
                                                           safe(lambda: sketch.name))
            if hint:
                return error(f"{hint} The profile sketch timeline row does not read; nothing was edited.")
            sketch_name = safe(lambda: sketch.name) or "?"
            return error(f"The profile sketch '{sketch_name}' has an unreadable timeline row. Read "
                         "design_get(include=['timeline']) before retrying; nothing was edited.")
        operands.append(profile_entity)
    if values["to_object"] is not None:
        operands.append(values["to_object"])
    if values["start_object"] is not None:
        operands.append(values["start_object"])
    for operand in operands:
        owner = _inputs.entity_component(operand)
        if _common.same_component(component, owner) is not True:
            return error(f"An operand does not belong to '{label}'s owning component.")
        if safe(lambda: operand.assemblyContext, _UNREAD) is not None:
            return error(f"An operand for '{label}' is not native to its owning component.")
    if any(a == b for i, a in enumerate(values["target_bodies"])
           for b in values["target_bodies"][i + 1:]):
        return error("'target_bodies' repeats one body; list each participant once.")
    before = _geometry(component)
    if before is None:
        return error(f"'{label}'s body geometry could not be read; nothing was edited.")
    components = safe(lambda: list(design.allComponents))
    if not components or not any(_common.same_component(component, c) is True for c in components):
        return error("The design's component census could not be read; nothing was edited.")
    siblings = [(c, _geometry(c)) for c in components
                if _common.same_component(component, c) is not True]
    if any(geometry is None for c, geometry in siblings):
        return error("Other component geometry could not be read; nothing was edited.")
    health_before = _health(design, marker)
    if health_before is None:
        return error(f"'{label}'s evaluated-health census is unreadable; nothing was edited.")
    if action == "profile" and safe(lambda: entity.profile == profile_entity) is True:
        return error(f"'{label}' already uses profile '{profile}'; nothing was edited.")
    failure, attempted = None, False
    definition_matches = None
    replayed, linked_verified, linked_owners = False, None, None
    verified_links = None
    definition_before, definition_after, address = None, None, None
    try:
        if entity.timelineObject.rollTo(True) is not True:
            failure = "Fusion refused rollTo(True)."
        elif counted(lambda: timeline.markerPosition) != index:
            failure = "The marker did not reach the feature's edit position."
        elif any(safe(lambda operand=operand: operand.isValid) is not True for operand in operands):
            failure = "An operand is invalid at the edit position; use preceding geometry."
        else:
            definition_before = _definition(entity)
            linked_error = _linked_scope_error(entity, component, components, index)
            if linked_error:
                raise ValueError(linked_error)
            if (counted(lambda: entity.linkedFeatures.count)
                    and action == "operation" and values["operation"] in ("new", "join")):
                raise ValueError("A linked Extrude supports only scoped cut/intersect operation edits.")
            if action in ("profile", "extent", "start") and entity.operation in (
                    adsk.fusion.FeatureOperations.CutFeatureOperation,
                    adsk.fusion.FeatureOperations.IntersectFeatureOperation):
                prior = [_common._native_of(body) for body in entity.participantBodies]
                if not prior or any(_common.same_component(component, body.parentComponent)
                                    is not True for body in prior):
                    raise ValueError("Existing participants are not confined to the owning component.")
                values["preserved_bodies"] = prior
            if _definition_matches(entity, action, values) is True:
                raise ValueError("The feature already has that definition.")
            address = sketch_address(_profile_source(entity, component)[0])
            attempted = True
            _apply_edit(entity, action, values)
            scoped = values.get("preserved_bodies") or values["target_bodies"]
            if scoped:
                _replay_scope(entity, timeline, index, scoped)
                replayed = True
            definition_matches = _definition_matches(entity, action, values)
            definition_after = _definition(entity)
            linked_error = _linked_scope_error(entity, component, components, index)
            linked_verified = linked_error is None
            verified_links = safe(lambda: list(entity.linkedFeatures))
            linked_owners = safe(lambda: [f.parentComponent.name for f in entity.linkedFeatures])
            if linked_error:
                raise ValueError(linked_error)
    except Exception as exc:
        failure = sentence(exc)
        definition_matches = safe(lambda: _definition_matches(entity, action, values))
        definition_after = _definition(entity)
    finally:
        safe(lambda: setattr(timeline, "markerPosition", marker))
    restored = counted(lambda: timeline.markerPosition) == marker
    after = _geometry(component) if restored else None
    final_links = safe(lambda: list(entity.linkedFeatures)) if restored else None
    links_stable = (None if final_links is None or verified_links is None else
                    len(final_links) == len(verified_links)
                    and all(any(final == checked for final in final_links)
                            for checked in verified_links))
    final_components = safe(lambda: list(design.allComponents)) if restored else None
    scope_verified, sibling_changes = None, []
    if (final_components is not None and len(final_components) == len(components)
            and all(sum(_common.same_component(c, other) is True for other in final_components) == 1
                    for c in components)):
        scope_verified = True
        for sibling, prior_geometry in siblings:
            final_geometry = _geometry(sibling)
            if final_geometry is None:
                scope_verified = None
            elif final_geometry != prior_geometry:
                sibling_changes.append({"component": safe(lambda: sibling.name),
                                        "before": prior_geometry, "after": final_geometry})
        if sibling_changes:
            scope_verified = False
    same = _same_feature(design, token, entity, index, count)
    state, compute_failure = _assert.compute_state(entity)
    health_after = _health(design, marker) if restored else None
    new_errors = (None if health_after is None else
                  [n for n in health_after["errors"] if n not in health_before["errors"]])
    new_warnings = (None if health_after is None else
                    [n for n in health_after["warnings"] if n not in health_before["warnings"]])
    changed = None if after is None else before != after
    out = {"feature": label, "action": action, "definition_matches": definition_matches,
           "geometry_changed": changed, "same_feature": same, "marker_restored": restored,
           "marker_before": marker, "marker_after": counted(lambda: timeline.markerPosition),
           "feature_health": state, "new_timeline_errors": new_errors,
           "new_timeline_warnings": new_warnings, "mutation_attempted": attempted,
           "unevaluated_timeline_items": count - marker,
           "definition_before": definition_before, "definition_after": definition_after,
           "geometry_before": before, "geometry_after": after,
           "other_components_unchanged": scope_verified, "other_component_changes": sibling_changes,
           "participants_reapplied_after_evaluation": replayed,
           "linked_scope_verified_at_edit": linked_verified, "linked_component_aliases": linked_owners,
           "linked_aliases_stable_after_evaluation": links_stable,
           "geometry_frame": "owning_component", "geometry_units": "cm, cm2, cm3"}
    checks = (("marker_restored", restored), ("same_feature", same is True),
              ("definition_matches", definition_matches is True), ("geometry_changed", changed is True),
              ("feature_health", state == "healthy"), ("other_components_unchanged", scope_verified is True),
              ("linked_scope_verified_at_edit", linked_verified is True),
              ("linked_aliases_stable_after_evaluation", links_stable is True),
              ("new_timeline_errors", new_errors == []), ("new_timeline_warnings", new_warnings == []))
    missed = [name for name, good in checks if not good]
    identical = not failure and missed == ["geometry_changed"] and changed is False
    if (failure or missed) and not identical:
        rows = _rows(action, definition_before, definition_after)
        remedy = _remedy(label, action, definition_before, definition_after)
        downstream = ("The definition landed but introduced downstream errors or warnings."
                      if definition_matches is True and (new_errors or new_warnings) else None)
        reason = (failure or downstream or (sentence(compute_failure) if compute_failure else "")
                  or f"These checks failed: {', '.join(missed)}.")
        if not attempted:
            text = f"{reason} Nothing was edited."
        elif definition_after == definition_before:
            text = (f"{failure or 'Fusion kept the prior definition.'} "
                    + outcome_clause("unchanged", f"'{label}'", rows)
                    if definition_matches is False and changed is False and scope_verified is True
                    else f"{reason} " + outcome_clause(
                        "unconfirmed", f"'{label}'", remedy="model_inspect", evidence=(
                            f"the recorded fields re-read as before; definition_matches="
                            f"{definition_matches}, geometry_changed={changed}, "
                            f"other_components_unchanged={scope_verified}")))
        else:
            text = f"{reason} " + _settle(design, entity, label, action, values, address, rows, remedy,
                                          (definition_before, before, siblings, health_before),
                                          (marker, index, token, count), out)
        now = counted(lambda: timeline.markerPosition)
        if now != marker:
            text += f" Also, {_common.marker_clause(marker, now, 'the edit')}."
        return failed(f"Editing '{label}': {text}", out)
    out["edited"] = True
    kept = values.get("kept_side")
    out["note"] = ("Definition changed on the same Extrude. Use param_get/param_set for numeric edits."
                   + (" The distance kept the feature's negative side; pass direction='positive' "
                      "to flip it." if kept == "negative" else
                      f" With no direction and a prior {definition_before['extent'] or 'unread'} "
                      f"extent, the distance reads {definition_after['side']}; pass 'direction' to "
                      "choose." if kept == "both" else "")
                   + (" Later timeline items remain unevaluated at the restored marker."
                      if marker < count else "")
                   + (" Linked replay may leave mass properties stale. Use design_recompute before "
                      "mass inspection; it can reset uncaptured joint poses."
                      if replayed and linked_owners else ""))
    if (action == "extent" and definition_before["extent"] == "two_side"
            and definition_after["extent"] == "symmetric"
            and definition_after["distance2_cm"] is None
            and len(definition_before["tapers"]) == 2
            and len(definition_after["tapers"]) == 1):
        out["note"] += " The second-side distance and taper parameters no longer read on this feature."
    return identical_geometry_reply(out) if identical else ok(out)


TOOL_DESCRIPTION = (
    "Edit solid Extrude; refs from design_get/sketch_get."
)
tool = _inputs.apply_to_tool(
    Tool.create_simple(name="model_edit_extrude", description=TOOL_DESCRIPTION), _SPEC
)
tool.add_input_property("distance", {"type": ["number", "string"],
                                    "description": "Positive; symmetric per side."})
tool.add_input_property("distance2", {"type": ["number", "string"]})
tool.add_input_property(*_START_OBJECT.as_property())
tool.add_input_property("start_offset", {"type": ["number", "string"]})
tool.strict_schema()
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(kind="inline", rung="geometry",
                              evidence_test="tests/unit/test_model_edit_extrude.py"
                                            "::test_silent_profile_setter_is_an_error"))


def register_tool():
    register(item)
