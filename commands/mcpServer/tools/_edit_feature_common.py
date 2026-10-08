# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Shared evaluated-body and timeline evidence for reference feature edits."""

import adsk.core
import adsk.fusion
import math
from itertools import islice

from . import _common, _design_common, _geom, _inputs, _sketch_detail
from ._common import counted, safe

MAP_BLURB = (
    "FEATURE_EDIT_SUPPORT/feature_edit_rows - closed offer; "
    "read_extrude_definition/read_sweep_definition/feature_definition - read; "
    "write_datum; "
    "all_shapes/health/same_feature; "
    "feature_geometry_snapshot - body shapes and occurrence frames; "
    "sketch_address/at_address/address_text; "
    "restore_definition/restore_gaps/matched/shape_match - rollback; "
    "rolled_back_text/failed/identical_geometry_reply - outcomes")

FEATURE_EDIT_SUPPORT = {
    "adsk::fusion::HemFeature": {
        "mode": {"member": "definition", "reader": "hem_definition", "setter": "hem_definition",
                 "field": "hem", "choices": ("flat", "open", "rolled", "double"),
                 "example": "hem={'type':'flat','length':'9 mm'}"},
        "_preserve": {"hem_edge": {"member": "definition.hemEdge", "reader": "reference",
                                    "reference": "edges", "field": "hem_edge"}}},
    "adsk::fusion::RipFeature": {
        "inputs": {"variants": {
            "face": {"member": "definition.ripFace", "reference": "faces", "cardinality": "one",
                     "reader": "reference", "field": "rip_face", "unwrap_single": True,
                     "when_type": "adsk::fusion::FaceRipFeatureDefinition"},
            "edge": {"member": "definition.ripEdge", "reference": "edges", "cardinality": "one",
                     "reader": "reference", "field": "rip_edge", "unwrap_single": True,
                     "when_type": "adsk::fusion::AlongEdgeRipFeatureDefinition",
                     "preserve": {"gap": {"member": "definition.gapDistance.expression",
                                            "reader": "value", "field": "gap"},
                                  "rip_type": {"member": "definition.objectType", "reader": "text",
                                               "field": "rip_type"}}}}},
        "_preserve": {"rip_type": {"member": "definition.objectType", "reader": "text",
                                    "field": "rip_type"}}},
    "adsk::fusion::PipeFeature": {
        "path": {"member": "path", "reference": "path", "cardinality": "many",
                 "reader": "path", "setter": "pipe_path", "field": "path"},
        "_preserve": {
            "section_type": {"member": "sectionType", "reader": "value", "field": "section_type"},
            "section_size": {"member": "sectionSize.expression", "reader": "value",
                             "field": "section_size"}}},
    "adsk::fusion::ScaleFeature": {
        "mode": {"member": "isUniform", "choices": ("uniform", "nonuniform"),
                 "values": {"uniform": True, "nonuniform": False},
                 "setter": "scale_mode", "field": "is_uniform"},
        "_preserve": {
            "input_entities": {"member": "inputEntities", "reader": "references",
                               "field": "input_entities"},
            "scale_expressions": {"member": "scaleFactor", "reader": "scale_expressions",
                                  "field": "scale_expressions"}}},
    "adsk::fusion::EmbossFeature": {
        "inputs": {"member": "profiles", "reference": "profiles", "cardinality": "many",
                   "reader": "profiles", "field": "profiles"},
        "_preserve": {
            "depth": {"member": "depth.expression", "reader": "value", "field": "depth"}}},
    "adsk::fusion::PathPatternFeature": {
        "path": {"member": "path", "reference": "path", "cardinality": "many",
                 "reader": "path", "field": "path"},
        "mode": {"member": "isOrientationAlongPath", "choices": ("identical", "along_path"),
                 "values": {"identical": False, "along_path": True}, "field": "orientation"},
        "_preserve": {
            "pattern_elements": {"member": "patternElements", "reader": "count",
                                 "field": "pattern_elements"},
            "suppressed": {"member": "suppressedElementsIds", "reader": "list",
                           "field": "suppressed"},
            "input_entities": {"member": "inputEntities", "reader": "references",
                               "field": "input_entities"},
            "quantity": {"member": "quantity.expression", "reader": "value",
                         "field": "quantity"}}},
    "adsk::fusion::ShellFeature": {
        "inputs": {"member": "inputEntities", "reference": "faces", "cardinality": "many",
                   "reader": "references", "setter": "shell_inputs", "field": "input_faces"},
        "_preserve": {
            "inside_thickness": {"member": "insideThickness", "reader": "nullable_expression",
                                 "field": "inside_thickness"},
            "outside_thickness": {"member": "outsideThickness", "reader": "nullable_expression",
                                  "field": "outside_thickness"},
            "tangent_chain": {"member": "isTangentChain", "reader": "boolean",
                              "field": "is_tangent_chain"}}},
    "adsk::fusion::RevolveFeature": {
        "axis": {"member": "axis", "reference": "axis", "cardinality": "one",
                 "reader": "reference", "field": "axis"},
        "_preserve": {
            "profile": {"member": "profile", "reader": "profile", "field": "profile"},
            "operation": {"member": "operation", "reader": "operation", "field": "operation"},
            "is_solid": {"member": "isSolid", "reader": "boolean", "field": "is_solid"},
            "angle": {"member": "extentDefinition", "reader": "angle_extent_expression",
                      "field": "angle"},
            "is_symmetric": {"member": "extentDefinition", "reader": "angle_extent_symmetric",
                             "field": "is_symmetric"}}},
    "adsk::fusion::MirrorFeature": {
        "plane": {"member": "mirrorPlane", "reference": "plane", "cardinality": "one",
                  "reader": "reference", "field": "mirror_plane"},
        "_preserve": {
            "input_entities": {"member": "inputEntities", "reader": "references",
                               "field": "input_entities"}}},
    "adsk::fusion::CircularPatternFeature": {
        "axis": {"member": "axis", "reference": "axis", "cardinality": "one",
                 "reader": "reference", "field": "axis"},
        "_preserve": {
            "elements": {"member": "patternElements", "reader": "count", "field": "elements"},
            "suppressed": {"member": "suppressedElementsIds", "reader": "list",
                           "field": "suppressed"},
            "input_entities": {"member": "inputEntities", "reader": "references",
                               "field": "input_entities"},
            "quantity": {"member": "quantity", "reader": "expression", "field": "quantity"},
            "total_angle": {"member": "totalAngle", "reader": "expression", "field": "total_angle"}}},
    "adsk::fusion::DraftFeature": {
        "inputs": {"member": "inputFaces", "reference": "faces", "cardinality": "many",
                   "reader": "references", "field": "input_faces"},
        "mode": {"member": "isDirectionFlipped", "choices": ("normal", "flipped"),
                 "values": {"normal": False, "flipped": True},
                 "field": "is_direction_flipped"},
        "_preserve": {
            "angle": {"member": "draftDefinition", "reader": "angle_extent_expression",
                      "field": "angle"}}},
    "adsk::fusion::ThreadFeature": {
        "mode": {"member": "isModeled", "choices": ("cosmetic", "modeled"),
                 "values": {"cosmetic": False, "modeled": True}, "field": "is_modeled"},
        "_preserve": {
            "is_full_length": {"member": "isFullLength", "reader": "boolean",
                               "field": "is_full_length"},
            "right_handed": {"member": "isRightHanded", "reader": "boolean",
                             "field": "right_handed"},
            "thread_info": {"member": "threadInfo", "reader": "thread_info",
                            "field": "thread_info"},
            "designation": {"member": "threadInfo.threadDesignation", "reader": "value",
                            "field": "designation"},
            "length": {"member": "threadLength.expression", "reader": "thread_length",
                       "field": "length"},
            "offset": {"member": "threadOffset.expression", "reader": "thread_length",
                       "field": "offset"}}},
    "adsk::fusion::PatchFeature": {
        "boundary": {"member": "boundaryCurve", "reference": "boundary_curve",
                     "cardinality": "one", "reader": "single_reference_collection",
                     "field": "boundary"},
        "_preserve": {
            "operation": {"member": "operation", "reader": "operation", "field": "operation"},
            "continuity": {"member": "continuity", "reader": "value", "field": "continuity"},
            "is_group_edges": {"member": "isGroupEdges", "reader": "boolean",
                               "field": "is_group_edges"}}},
    "adsk::fusion::OffsetFeature": {
        "inputs": {"member": "entities", "reference": "faces", "cardinality": "many",
                   "reader": "references", "field": "entities", "setter": "setInputEntities",
                   "chain_field": "is_chain_selection"},
        "_preserve": {
            "distance": {"member": "distance.expression", "reader": "value", "field": "distance"},
            "is_chain_selection": {"member": "isChainSelection", "reader": "boolean",
                                   "field": "is_chain_selection"},
            "offset_type": {"member": "offsetType", "reader": "value", "field": "offset_type"},
            "operation": {"member": "operation", "reader": "operation", "field": "operation"}}},
    "adsk::fusion::UntrimFeature": {
        "boundary": {"member": "facesToUntrim", "reference": "faces", "cardinality": "many",
                     "reader": "references", "field": "faces_to_untrim",
                     "setter": "redefineLoopsFromFaces", "choices": ("all", "external", "internal"),
                     "mode_enum": "UntrimLoopTypes",
                     "values": {"all": "AllLoopsUntrimType", "external": "ExternalLoopsUntrimType",
                                "internal": "InternalLoopsUntrimType", "manual": "ManualLoopsUntrimType"},
                     "mode_field": "loop_type"},
        "_preserve": {
            "loop_type": {"member": "untrimLoopType", "reader": "choice",
                           "enum_type": "UntrimLoopTypes", "field": "loop_type",
                           "values": {"all": "AllLoopsUntrimType", "external": "ExternalLoopsUntrimType",
                                      "internal": "InternalLoopsUntrimType",
                                      "manual": "ManualLoopsUntrimType"}},
            "extension_distance": {"member": "extensionDistance.expression", "reader": "value",
                                   "field": "extension_distance"}}},
    "adsk::fusion::ExtendFeature": {
        "inputs": {"member": "edges", "reference": "edges", "cardinality": "many",
                   "reader": "references", "field": "edges", "setter": "setInputEntities",
                   "chain_field": "is_chaining_enabled"},
        "_preserve": {
            "distance": {"member": "distance.expression", "reader": "value", "field": "distance"},
            "is_chaining_enabled": {"member": "isChainingEnabled", "reader": "boolean",
                                    "field": "is_chaining_enabled"},
            "extend_type": {"member": "extendType", "reader": "value", "field": "extend_type"},
            "extend_alignment": {"member": "extendAlignment", "reader": "value",
                                 "field": "extend_alignment"}}},
    "adsk::fusion::StitchFeature": {
        "inputs": {"member": "stitchSurfaces", "reference": "surface_bodies", "cardinality": "many",
                   "reader": "references", "field": "stitch_surfaces", "assignment": "object_collection"},
        "_preserve": {
            "tolerance": {"member": "tolerance.expression", "reader": "value", "field": "tolerance"},
            "operation": {"member": "operation", "reader": "operation", "field": "operation"}}},
    "adsk::fusion::UnstitchFeature": {
        "inputs": {"member": "inputFaces", "reference": "faces", "cardinality": "many",
                   "reader": "references", "field": "input_faces", "setter": "setInputFaces",
                   "chain_field": "is_chain_selection"},
        "_preserve": {
            "is_chain_selection": {"member": "isChainSelection", "reader": "boolean",
                                   "field": "is_chain_selection"}}},
    "adsk::fusion::ThickenFeature": {
        "inputs": {"member": "inputFaces", "reference": "faces", "cardinality": "many",
                   "reader": "references", "field": "input_faces", "setter": "setInputEntities",
                   "chain_field": "is_chain_selection"},
        "_preserve": {
            "thickness": {"member": "thickness.expression", "reader": "value", "field": "thickness"},
            "is_chain_selection": {"member": "isChainSelection", "reader": "boolean",
                                   "field": "is_chain_selection"},
            "is_symmetric": {"member": "isSymmetric", "reader": "boolean", "field": "is_symmetric"},
            "thicken_type": {"member": "thickenType", "reader": "value", "field": "thicken_type"},
            "operation": {"member": "operation", "reader": "operation", "field": "operation"}}},
    "adsk::fusion::ReverseNormalFeature": {
        "inputs": {"member": "surfaces", "reference": "surface_bodies", "cardinality": "many",
                   "reader": "references", "field": "surfaces", "assignment": "object_collection",
                   "verify_surface_normals": True}},
    "adsk::fusion::DeleteFaceFeature": {
        "inputs": {"member": "deletedFaces", "reference": "faces", "cardinality": "many",
                   "reader": "references", "field": "deleted_faces", "assignment": "list"}},
    "adsk::fusion::SurfaceDeleteFaceFeature": {
        "inputs": {"member": "deletedFaces", "reference": "faces", "cardinality": "many",
                   "reader": "references", "field": "deleted_faces", "assignment": "list"}},
    "adsk::fusion::CombineFeature": {
        "tools": {"member": "toolBodies", "reference": "bodies", "cardinality": "many",
                  "reader": "references", "field": "tool_bodies"},
        "mode": {"member": "operation", "choices": ("join", "cut", "intersect"),
                 "reader": "operation",
                 "values": {"join": "join", "cut": "cut", "intersect": "intersect"},
                 "field": "operation"},
        "_preserve": {
            "target_body": {"member": "targetBody", "reference": "entities",
                             "reader": "reference", "field": "target_body"},
            "keep_tools": {"member": "isKeepToolBodies", "reader": "boolean",
                           "field": "keep_tools"}}},
    "adsk::fusion::FilletFeature": {
        "inputs": {"variants": {
            "rule": {"member": "ruleFilletSettings.facesOrFeatures", "reference": "faces",
                     "cardinality": "many", "reader": "rule_faces", "setter": "rule_faces",
                     "field": "rule_faces", "when_member": "filletFeatureType",
                     "when_enum": "RuleFilletFeatureType", "preserve": {
                         "rule_type": {"member": "ruleFilletSettings.ruleType", "reader": "value",
                                       "field": "rule_type"},
                         "radius": {"member": "ruleFilletSettings.radius.expression",
                                    "reader": "value", "field": "radius"}}},
            "constant": {"member": "edgeSets", "set_collection": "edgeSets",
                         "set_type": "adsk::fusion::ConstantRadiusFilletEdgeSet",
                         "set_control": "radius.expression", "set_control_field": "radius",
                         "reference": "edges", "cardinality": "many", "reader": "edge_sets",
                         "setter": "edge_set_edges", "field": "edge_sets",
                         "when_member": "filletFeatureType", "when_enum": "FilletFeatureType"}}}},
    "adsk::fusion::ChamferFeature": {
        "inputs": {"member": "edgeSets", "set_collection": "edgeSets",
                   "set_type": "adsk::fusion::EqualDistanceChamferEdgeSet",
                   "set_control": "distance.expression", "set_control_field": "distance",
                   "reference": "edges", "cardinality": "many", "reader": "edge_sets",
                   "setter": "edge_set_edges", "field": "edge_sets"}},
    "adsk::fusion::SplitBodyFeature": {
        "tools": {"member": "splittingTool", "reference": "split_tool", "cardinality": "one",
                  "reader": "reference", "setter": "split_body_tool", "field": "splitting_tool"},
        "_preserve": {
            "extended": {"member": "isSplittingToolExtended", "reader": "boolean",
                         "field": "is_splitting_tool_extended"}}},
    "adsk::fusion::SilhouetteSplitFeature": {
        "axis": {"member": "viewDirection", "reference": "axis", "cardinality": "one",
                 "reader": "reference", "field": "view_direction"},
        "_preserve": {
            "target_body": {"member": "targetBody", "reference": "entities",
                             "reader": "reference", "field": "target_body"},
            "operation": {"member": "operation", "reader": "value", "field": "operation"}}},
    "adsk::fusion::OffsetFacesFeature": {
        "inputs": {"member": "inputFaces", "reference": "faces", "cardinality": "many",
                   "reader": "references", "field": "input_faces"},
        "_preserve": {"distance": {"member": "distance.expression", "reader": "value",
                                     "field": "distance"}}},
    "adsk::fusion::DeriveFeature": {
        "inputs": {"member": "sourceEntities", "reference": "source_body_names",
                   "cardinality": "many", "reader": "source_names", "field": "source_entities",
                   "example": "references=['<source root body name>']"},
        "mode": {"member": "isIncludeFavoriteParameters",
                 "choices": ("favourites_on", "favourites_off"),
                 "values": {"favourites_on": True, "favourites_off": False},
                 "field": "include_favorite_parameters"},
        "break_link": {"member": "documentReference.isOutOfDate", "reader": "flag",
                       "field": "out_of_date"},
        "_preserve": {
            "source_document": {"member": "sourceDesign.parentDocument.name", "reader": "text",
                                "field": "source_document"},
            "source_lineage": {"member": "sourceDesign.parentDocument.dataFile.id",
                               "reader": "text", "field": "source_lineage_id"},
            "derived_parameters": {"member": "parentComponent", "reader": "derived_parameters",
                                   "field": "derived_parameters"},
            "health": {"member": "healthState", "reader": "health_name", "field": "health"}},
        "_meta": {"route": "derive"}},
    "adsk::fusion::ConstructionPlane": {
        "plane": {"member": "definition", "read": "definition.planarEntity", "reference": "plane",
                  "cardinality": "one", "reader": "reference", "field": "base_plane",
                  "writer": "offset_plane", "returns": True, "example": "references=['xz']"},
        "_preserve": {
            "offset": {"member": "definition.offset.expression", "reader": "offset_expression",
                       "field": "offset"}},
        "_meta": {
            "route": "end", "geometry": "plane",
            "definition": "adsk::fusion::ConstructionPlaneOffsetDefinition",
            "create": "model_construction(kind='plane', mode='offset')",
            "note": ("Edited at the end marker without rolling. Dependents move with the plane "
                     "and can change orientation; geometry_changed compares every body and "
                     "occurrence frame. Read dependent sketches with sketch_get.")}},
    "adsk::fusion::ConstructionAxis": {
        "axis": {"member": "definition", "reference": "plane_pair", "cardinality": "one",
                 "reader": "plane_pair", "field": "planes", "writer": "two_plane_axis",
                 "returns": True,
                 "example": "references=[{'first_plane': 'xz', 'second_plane': 'yz'}]"},
        "_meta": {
            "route": "end", "geometry": "axis",
            "definition": "adsk::fusion::ConstructionAxisTwoPlaneDefinition",
            "create": "model_construction(kind='axis', mode='two_planes')",
            "note": ("Edited at the end marker without rolling. Dependents move with the axis; "
                     "geometry_changed compares every body and occurrence frame. Read them with "
                     "model_inspect.")}},
    "adsk::fusion::ConstructionPoint": {
        "point": {"member": "definition", "read": "definition.pointEntity", "reference": "point",
                  "cardinality": "one", "reader": "reference", "field": "point_entity",
                  "writer": "point_entity",
                  "example": "references=['<vertex handle from find_geometry>']"},
        "_meta": {
            "route": "end", "geometry": "point",
            "definition": "adsk::fusion::ConstructionPointPointDefinition",
            "create": "model_construction(kind='point', mode='at_point')",
            "note": ("Edited at the end marker without rolling. Dependents move with the point; "
                     "geometry_changed compares every body and occurrence frame. Read them with "
                     "model_inspect.")}},
    "adsk::fusion::JointOrigin": {
        "geometry": {"member": "geometry", "read": "geometry.entityOne",
                     "reference": "joint_geometry", "cardinality": "one", "reader": "reference",
                     "field": "geometry", "identity": "native",
                     "example": "references=['<face handle from find_geometry>']"},
        "_preserve": {
            "is_flipped": {"member": "isFlipped", "reader": "boolean", "field": "is_flipped"},
            "angle": {"member": "angle", "reader": "expression", "field": "angle"},
            "offset_x": {"member": "offsetX", "reader": "expression", "field": "offset_x"},
            "offset_y": {"member": "offsetY", "reader": "expression", "field": "offset_y"},
            "offset_z": {"member": "offsetZ", "reader": "expression", "field": "offset_z"}},
        "_meta": {
            "feature_members": False, "geometry": "joint_origin",
            "note": ("The definition was read back rolled before the joint origin. "
                     "target_geometry_before/after are its own transform origin and axis vectors "
                     "at the end marker; assembly_get(include=['joint_origins']) reads its world "
                     "frame and the joints using it.")}},
}


def feature_edit_rows(feature, definition=None):
    """The bounded edit actions with qualified calls using the independently read handles."""
    rows = FEATURE_EDIT_SUPPORT.get(safe(lambda: feature.objectType), {})
    if definition_type_gap(feature, rows):
        return []
    address = _inputs.candidate_address(safe(lambda: feature.timelineObject))
    out = []
    for action, raw_row in rows.items():
        row = _row_for(feature, raw_row)
        if action.startswith("_") or row is None:
            continue
        args = [f"feature='{address}'", f"action='{action}'"] if address else []
        if row.get("reference"):
            value = (definition or {}).get(row["field"])
            refs = (value if row.get("cardinality") == "many"
                    else [value])
            if row["reference"] == "path" and isinstance(value, dict):
                refs = value.get("references")
            if row.get("set_collection"):
                sets = value if isinstance(value, list) else []
                selected = next((item for item in sets if item.get("index") == 0), None)
                refs = selected.get("edges") if selected else None
            handle_key = "profile_handle" if row["reference"] == "profiles" else "handle"
            handles = ([item.get(handle_key) if isinstance(item, dict) else None for item in refs]
                       if isinstance(refs, list) else [])
            if row["reference"] == "source_body_names":
                handles = refs if isinstance(refs, list) else []
            if row["reference"] == "plane_pair":
                pair = value if isinstance(value, dict) else {}
                handles = [safe(lambda role=role: pair[role]["handle"]) for role in PLANE_PAIR_ROLES]
            if not address or not handles or any(not isinstance(handle, str) or not handle
                                                 for handle in handles):
                args = []
            elif row["reference"] == "plane_pair":
                args.append(f"references={[dict(zip(PLANE_PAIR_ROLES, handles))]!r}")
            else:
                args.append(f"references={handles!r}")
            if row.get("set_collection") and args:
                args.append("set_index=0")
        choices = list(row.get("choices", ()))
        if row.get("setter") == "hem_definition":
            value = (definition or {}).get("hem", {})
            if not address or not value.get("dimensions"):
                args = []
            else:
                payload = {"type": value["type"], "flip": value["flip"],
                           "bend_position": value["bend_position"]}
                for key, dimension in value["dimensions"].items():
                    payload[key] = (math.degrees(dimension["value_rad"]) if key == "angle_deg"
                                    else dimension["expression"])
                args.append(f"hem={payload!r}")
            choices = []
        if row.get("setter") == "scale_mode":
            uniform = (definition or {}).get("is_uniform")
            factors = (definition or {}).get("scale_expressions")
            choices = (["nonuniform"] if uniform is True else
                       ["uniform"] if uniform is False and isinstance(factors, list)
                       and len(factors) == 3 and len(set(factors)) == 1 else [])
        elif row.get("member") == "isIncludeFavoriteParameters":
            included = (definition or {}).get(row["field"])
            choices = (["favourites_off"] if included is True else
                       ["favourites_on"] if included is False else [])
        elif row.get("member") == "isOrientationAlongPath":
            orientation = (definition or {}).get(row["field"])
            choices = (["along_path"] if orientation is False else
                       ["identical"] if orientation is True else [])
        if row.get("choices") and not choices and row.get("setter") != "hem_definition":
            continue
        if choices:
            args.append(f"mode='{choices[0]}'")
        out.append({"action": action, "reference": row.get("reference"),
                    "cardinality": row.get("cardinality"), "choices": choices,
                    "call": "model_edit_feature(" + ", ".join(args) + ")" if args else None})
    return out


def _row_applies(feature, row):
    """Whether a measured subtype discriminator selects this action row."""
    if "variants" in row:
        return _row_for(feature, row) is not None
    if row.get("when_type"):
        return safe(lambda: feature.definition.objectType) == row["when_type"]
    member, enum = row.get("when_member"), row.get("when_enum")
    if not member:
        return True
    value = safe(lambda: getattr(feature, member))
    expected = safe(lambda: getattr(adsk.fusion.FilletFeatureTypes, enum))
    return value is not None and expected is not None and value == expected


def _row_for(feature, row):
    """Select the single closed action row matching a measured native subtype."""
    variants = row.get("variants")
    if variants is None:
        return row if _row_applies(feature, row) else None
    matches = [variant for variant in variants.values() if _row_applies(feature, variant)]
    return matches[0] if len(matches) == 1 else None


PLANE_PAIR_ROLES = ("first_plane", "second_plane")


def definition_type_gap(feature, support):
    """Why a datum's definition is not the one type its table entry edits, else None."""
    wanted = support.get("_meta", {}).get("definition")
    if wanted is None:
        return None
    actual = safe(lambda: feature.definition.objectType)
    if actual == wanted:
        return None
    read = actual.rsplit("::", 1)[-1] if isinstance(actual, str) and actual else "unreadable"
    return f"definition type reads {read}, not {wanted.rsplit('::', 1)[-1]}"


def _definition_value(getter, key, unavailable):
    """Read one field, recording the native failure separately from an absent value."""
    try:
        return getter()
    except Exception as exc:
        unavailable[key] = str(exc).split(" / ")[0].strip()[:200]
        return None


def _feature_path(entity, path):
    """Read one measured dotted feature member path."""
    for member in path.split("."):
        entity = getattr(entity, member)
    return entity


def set_feature_path(entity, path, value):
    """Assign one native member reached through a dotted feature path."""
    parent, _, member = path.rpartition(".")
    setattr(_feature_path(entity, parent) if parent else entity, member, value)


def _definition_participants(feature, unavailable, limit=None):
    """Participant names and truncation, or unknown when the current marker prevents the read."""
    def names():
        bodies = feature.participantBodies
        return [body.name for body in (islice(bodies, limit + 1) if limit is not None else bodies)]
    result = _definition_value(names, "participants", unavailable)
    return (result[:limit] if result is not None and limit is not None else result,
            len(result) > limit if result is not None and limit is not None else
            False if result is not None else None)


def collection_entities(collection, cap=64):
    """A complete collection through cap entities, or None when unread or truncated."""
    if isinstance(collection, (list, tuple)):
        values = list(collection)
    elif type(collection).__name__ in ("BaseVector", "BRepFaceVector"):
        count = safe(lambda: len(collection))
        if type(count) is not int or count < 0 or count > cap:
            return None
        values = [safe(lambda i=i: collection[i]) for i in range(count)]
    else:
        count = counted(lambda: collection.count)
        if count is None or count > cap:
            return None
        values = [safe(lambda i=i: collection.item(i)) for i in range(count)]
    return None if len(values) > cap or any(value is None for value in values) else values


def path_entities(path):
    """The ordered path members through 64 entities, or None when the path is incomplete."""
    count = counted(lambda: path.count)
    if count is None or count < 1 or count > 64:
        return None
    values = [safe(lambda i=i: path.item(i).entity) for i in range(count)]
    return values if all(value is not None for value in values) else None


def _path_public_references(feature, entities, records):
    """A typed public path input when the exact sketch or B-Rep members are resolvable."""
    if all(_inputs._isinstance(entity, adsk.fusion.BRepEdge) for entity in entities):
        refs = [descriptor for _entity, descriptor in records]
        if all(isinstance(item.get("handle"), str) and item.get("handle") for item in refs):
            return refs
    sketch_curve_type = safe(lambda: adsk.fusion.SketchCurve)
    if not isinstance(sketch_curve_type, type) or not all(
            _inputs._isinstance(entity, sketch_curve_type) for entity in entities):
        return None
    refs = []
    for entity in entities:
        address = _inputs.sketch_entity_address(entity)
        sketch = safe(lambda entity=entity: entity.parentSketch)
        component = safe(lambda sketch=sketch: sketch.parentComponent)
        name = safe(lambda entity=entity: entity.name) or type(entity).__name__
        if (not address or _common.same_component(
                component, safe(lambda: feature.parentComponent)) is not True):
            return None
        refs.append({"handle": address, "kind": "sketch_curve", "name": name,
                     "owner": {"component": safe(lambda component=component: component.name)}})
    return refs


def _scale_expressions(feature):
    """The exact three scale expressions for either measured ScaleFeature mode."""
    uniform = safe(lambda: feature.isUniform)
    if uniform is True:
        expression = safe(lambda: feature.scaleFactor.expression)
        return [expression] * 3 if isinstance(expression, str) and expression else None
    if uniform is not False:
        return None
    values = [safe(lambda name=name: getattr(feature, name).expression)
              for name in ("xScale", "yScale", "zScale")]
    return values if all(isinstance(value, str) and value for value in values) else None


def extrude_extent_kind(feature):
    """The supported extent configuration, or None for an unread or unsupported definition."""
    one = safe(lambda: feature.extentOne.objectType)
    two = safe(lambda: feature.hasTwoExtents)
    if two is True:
        other = safe(lambda: feature.extentTwo.objectType)
        if one == other == "adsk::fusion::DistanceExtentDefinition":
            return "two_side"
        if one == other == "adsk::fusion::ThroughAllExtentDefinition":
            return "through_all"
        return None
    if two is not False:
        return None
    return {"adsk::fusion::DistanceExtentDefinition": "distance",
            "adsk::fusion::SymmetricExtentDefinition": "symmetric",
            "adsk::fusion::ToEntityExtentDefinition": "to_face",
            "adsk::fusion::ThroughAllExtentDefinition": "through_all"}.get(one)


_EXTRUDE_NOT_READ = ("taper_angle", "thin", "start_extent", "is_solid")


def read_extrude_definition(feature, limit=None):
    """Read Extrude values at the current marker, with signed lengths in cm and per-field failures."""
    unavailable = {}
    get = lambda key, getter: _definition_value(getter, key, unavailable)
    kind = extrude_extent_kind(feature)
    pair = [safe(lambda side=side: getattr(feature, side).objectType) for side in ("extentOne", "extentTwo")]
    if kind is None and safe(lambda: feature.hasTwoExtents) is True and all(isinstance(t, str) for t in pair):
        unavailable["extent"] = ("two-sided " + " + ".join(t.rsplit("::", 1)[-1] for t in pair)
                                 + " is not a supported extent")
    param = (get("distance", lambda: feature.extentOne.distance)
             if kind in ("distance", "symmetric", "two_side") else None)
    param2 = get("distance2", lambda: feature.extentTwo.distance) if kind == "two_side" else None
    participants, truncated = _definition_participants(feature, unavailable, limit)
    extent_one_type = safe(lambda: feature.extentOne.objectType)
    has_two_extents = (get("extent_side_count", lambda: feature.hasTwoExtents)
                       if kind == "through_all" or
                       extent_one_type == "adsk::fusion::ThroughAllExtentDefinition" else None)
    return {"profile": get("profile", lambda: feature.profile),
            "operation": next((name for name, enum in _common.OPERATIONS.items()
                               if safe(lambda: feature.operation) ==
                               getattr(adsk.fusion.FeatureOperations, enum)), None),
            "extent": kind,
            "extent_side_count": (2 if has_two_extents is True else
                                  1 if has_two_extents is False else None)
            if kind == "through_all" else None,
            "direction": None,
            "distance_cm": _common.landed_extent_cm(feature) if param is not None else None,
            "distance2_cm": _common.landed_extent2_cm(feature) if kind == "two_side" else None,
            "distance_parameter": safe(lambda: param.name),
            "distance_expression": safe(lambda: param.expression),
            "distance2_parameter": safe(lambda: param2.name),
            "distance2_expression": safe(lambda: param2.expression),
            "symmetric_full_length": (_common.read_flag(lambda: feature.extentOne.isFullLength)
                                      if kind == "symmetric" else None),
            "participants": participants, "participants_truncated": truncated,
            "not_read": list(_EXTRUDE_NOT_READ) + (["extent_target"] if kind == "to_face" else []),
            "unavailable": unavailable}


def _sweep_orientation_name(value):
    """The measured name for a SweepOrientationTypes value, or None when it is unknown."""
    if value is None:
        return None
    for name, member in (("perpendicular", "PerpendicularOrientationType"),
                         ("parallel", "ParallelOrientationType")):
        native = safe(lambda member=member: getattr(adsk.fusion.SweepOrientationTypes, member))
        if native is not None and native == value:
            return name
    return None


def read_sweep_definition(feature):
    """Read each Sweep operand/control independently at the caller's current marker."""
    unavailable = {}
    read = {key: _definition_value(lambda name=name: getattr(feature, name), key, unavailable)
            for key, name in (("profile", "profile"), ("path", "path"), ("operation", "operation"),
                              ("orientation", "orientation"), ("is_solid", "isSolid"))}
    read["orientation_name"] = _sweep_orientation_name(read["orientation"])
    return {**read, "unavailable": unavailable}


def _definition_profile(entity):
    """A reusable single profile reference; bounded index search leaves larger sketches handle-only."""
    native = _common._native_of(entity)
    if native is None:
        return None
    sketch = safe(lambda: native.parentSketch)
    count = counted(lambda: sketch.profiles.count)
    curve_count = counted(lambda: sketch.sketchCurves.count)
    is_profile = safe(lambda: native.objectType) == "adsk::fusion::Profile"
    bounded = count is not None and count <= 64 and (is_profile or curve_count is not None and curve_count <= 64)
    address = sketch_address(native) if bounded else None
    return {"type": safe(lambda: native.objectType.rsplit("::", 1)[-1]),
            "profile_handle": (safe(lambda: native.entityToken)
                               if safe(lambda: native.objectType) == "adsk::fusion::Profile" else None),
            "source_sketch": safe(lambda: sketch.name),
            "source_component": safe(lambda: sketch.parentComponent.name),
            "profile_index": address[2] if address and address[1] == "profile" else None,
            "curve_ref": (f"{safe(lambda: sketch.name)}/{address[1]}:{address[2]}"
                          if address and address[1] != "profile" else None)}


def _profile_edit_definition(entity):
    """The public profile descriptor with a centroid and area locator from sketch_get."""
    value = _definition_profile(entity)
    native = _common._native_of(entity)
    sketch = safe(lambda: native.parentSketch)
    props = safe(lambda: native.areaProperties())
    area = safe(lambda: props.area) if props else None
    centroid = _geom._coords(safe(lambda: props.centroid)) if props else None
    name = safe(lambda: sketch.name)
    component_name = safe(lambda: sketch.parentComponent.name)
    loops = counted(lambda: native.profileLoops.count)
    safe_name = name if isinstance(name, str) and not any(c in name for c in ":,") else ""
    if value is None or area is None or centroid is None or not component_name or loops is None:
        return None
    kind = f"profile[{safe_name}~{area:.4f}]"
    handle = _inputs.make_handle(native, kind, centroid)
    if not handle:
        return None
    geometry = {"area": area, "centroid": list(centroid), "loop_count": loops}
    return {**value, "profile_handle": handle}, geometry


def _reference_kind(entity, role):
    """The existing geometry-handle kind for one measured axis, plane or face operand."""
    native = _common._native_of(entity)
    if role == "axis":
        if _inputs._isinstance(native, adsk.fusion.BRepEdge):
            return _inputs.edge_kind(safe(lambda: native.geometry))
        if _inputs._isinstance(native, adsk.fusion.SketchLine):
            return "line_edge"
        if _inputs._isinstance(native, adsk.fusion.ConstructionAxis):
            return "construction_axis"
    if role in ("plane", "plane_pair"):
        if _inputs._isinstance(native, adsk.fusion.BRepFace):
            return "planar_face"
        if _inputs._isinstance(native, adsk.fusion.ConstructionPlane):
            return "construction_plane"
    if role in ("point", "joint_geometry"):
        for native_type, kind in ((adsk.fusion.BRepVertex, "vertex"),
                                  (adsk.fusion.SketchPoint, "sketch_point"),
                                  (adsk.fusion.ConstructionPoint, "construction_point")):
            if _inputs._isinstance(native, native_type):
                return kind
    if role == "joint_geometry" and _inputs._isinstance(native, adsk.fusion.BRepEdge):
        return _inputs.edge_kind(safe(lambda: native.geometry))
    if role in ("faces", "joint_geometry") and _inputs._isinstance(native, adsk.fusion.BRepFace):
        return "face"
    if role in ("edges", "path"):
        if _inputs._isinstance(native, adsk.fusion.BRepEdge):
            return _inputs.edge_kind(safe(lambda: native.geometry))
        if _inputs._isinstance(native, adsk.fusion.SketchLine):
            return "line_edge"
        if role == "path" and _inputs._isinstance(native, adsk.fusion.SketchArc):
            return "sketch_arc"
    if role == "surface_bodies" and _inputs._is_brep(native):
        return "entity"
    if role == "boundary_curve":
        return "entity"
    if role == "entities":
        return "entity"
    if role == "bodies" and _inputs._isinstance(native, adsk.fusion.BRepBody):
        return "body"
    return None


def _reference_geometry(entity, role):
    """Measured world geometry for one operand, including line direction and plane normal."""
    native = _common._native_of(entity)
    is_axis = _inputs._isinstance(native, adsk.fusion.ConstructionAxis)
    is_plane = _inputs._isinstance(native, adsk.fusion.ConstructionPlane)
    is_face = _inputs._isinstance(native, adsk.fusion.BRepFace)
    is_body = _inputs._isinstance(native, adsk.fusion.BRepBody)
    meta = _inputs.operand_meta(entity)
    geometry = {"world_cm": meta.get("world_cm")}
    if role == "axis":
        if is_axis:
            origin, direction = _inputs.placed_datum_frame(entity, "construction_axis")
            geometry = {"frame": "world", "origin_cm": origin, "direction": direction}
        else:
            geometry["ends_cm"] = _inputs.placed_ends(entity)
    elif role in ("edges", "path"):
        geometry = {"frame": "world", "ends_cm": _inputs.placed_ends(entity)}
        if role == "path" and _inputs._isinstance(native, adsk.fusion.SketchArc):
            arc = native.geometry
            center = _geom._coords(arc.center)
            normal = _geom._coords(arc.normal)
            reference = _geom._coords(arc.referenceVector)
            radius = _common.finite_number(arc.radius)
            start = _common.finite_number(arc.startAngle)
            end = _common.finite_number(arc.endAngle)
            if any(value is None for value in (center, normal, reference, radius, start, end)):
                raise RuntimeError("bounded arc geometry is unreadable")
            if radius <= 0 or not all(math.isfinite(v) for v in (*center, *normal, *reference)):
                raise RuntimeError("bounded arc geometry is nonfinite or degenerate")
            tangent = _geom.cross(normal, reference)
            middle = (start + end) / 2
            interior = [center[i] + radius * (reference[i] * math.cos(middle)
                        + tangent[i] * math.sin(middle)) for i in range(3)]
            geometry.update(arc_frame="sketch", center_cm=center, normal=normal,
                            reference_vector=reference, radius_cm=radius,
                            start_angle_rad=start, end_angle_rad=end, interior_cm=interior)
    elif role in ("plane", "plane_pair"):
        if is_plane:
            origin, normal = _inputs.placed_datum_frame(entity, "construction_plane")
            geometry = {"frame": "world", "origin_cm": origin, "normal": normal}
        else:
            point = safe(lambda: native.pointOnFace)
            geometry = {"frame": "entity_context",
                        "surface_type": safe(lambda: native.geometry.surfaceType),
                        "point_cm": _geom._coords(point),
                        "normal": _geom.evaluator_normal_at(native, point),
                        "reversed": safe(lambda: native.isParamReversed)}
    elif role in ("faces", "entities", "bodies", "surface_bodies", "joint_geometry"):
        if is_body and geometry["world_cm"] is None:
            geometry = {"frame": "entity_context",
                        "center_cm": safe(lambda: _geom._coords(native.physicalProperties.centerOfMass))}
        geometry.update(area=safe(lambda: native.area),
                        volume=_geom.signed_volume(native),
                        surface_type=safe(lambda: native.geometry.surfaceType) if is_face else None,
                        reversed=safe(lambda: native.isParamReversed) if is_face else None)
        if is_face:
            point = safe(lambda: native.pointOnFace)
            geometry.update(frame="entity_context", point_cm=_geom._coords(point),
                            normal=_geom.evaluator_normal_at(native, point))
        geometry = {key: value for key, value in geometry.items() if value is not None}
    if any(value is None for value in geometry.values()):
        raise RuntimeError("operand geometry or orientation is unreadable")
    return geometry


def _reference_role(entity, role):
    """The measured descriptor role for a splitting tool's native entity type."""
    if role != "split_tool":
        return role
    native = _common._native_of(entity)
    if _inputs._isinstance(native, adsk.fusion.BRepBody):
        return "bodies"
    if _inputs._isinstance(native, adsk.fusion.ConstructionPlane):
        return "plane"
    if _inputs._isinstance(native, adsk.fusion.BRepFace):
        return "faces"
    return "entities"


def reference_descriptor(entity, role):
    """A usable existing handle and its measured kind, owner and operand geometry."""
    native = _common._native_of(entity)
    role = _reference_role(entity, role)
    kind = _reference_kind(entity, role)
    owner = _inputs.entity_component(native)
    if owner is None and _inputs._isinstance(native, adsk.fusion.BRepBody):
        owner = safe(lambda: native.parentComponent)
    owner_name = safe(lambda: owner.name)
    name = safe(lambda: native.name) or safe(lambda: entity.name) or type(native).__name__
    if not kind or not isinstance(owner_name, str) or not owner_name:
        raise RuntimeError("operand kind or owner is unreadable")
    meta = _inputs.operand_meta(entity)
    if _inputs._isinstance(native, adsk.fusion.BRepEdge):
        point = safe(lambda: native.pointOnEdge)
        coords = _geom._coords(point) if point is not None else None
        handle = _inputs.make_handle(entity, kind, coords, meta.get("assembly_path"))
    elif _inputs._isinstance(native, adsk.fusion.BRepFace):
        point = safe(lambda: native.centroid)
        coords = _geom._coords(point) if point is not None else None
        handle = _inputs.make_handle(entity, kind, coords, meta.get("assembly_path"))
    else:
        handle = (_inputs.placed_handle(entity, kind) if kind != "entity"
                  else safe(lambda: native.entityToken))
    if not isinstance(handle, str) or not handle:
        raise RuntimeError("no usable handle could be made for this operand")
    return {"handle": handle, "kind": kind, "name": name,
            "owner": {"component": owner_name, "occurrence": meta.get("assembly_path")},
            "geometry": _reference_geometry(entity, role)}


def _thread_info(info, unavailable):
    """The measured thread standard, designation, class and internal flag."""
    fields = {"thread_type": "threadType", "designation": "threadDesignation",
              "thread_class": "threadClass", "internal": "isInternal"}
    result = {}
    for key, member in fields.items():
        value = _definition_value(lambda member=member: getattr(info, member),
                                  "thread_info." + key, unavailable)
        result[key] = value
    return result


def feature_edit_state(feature):
    """Read private entity references and retained controls at the caller's current marker."""
    feature_type = safe(lambda: feature.objectType)
    support = FEATURE_EDIT_SUPPORT.get(feature_type, {})
    state, definition, unavailable = {}, {}, {}
    rows = [_row_for(feature, row) for key, row in support.items()
            if not key.startswith("_") and _row_applies(feature, row)]
    rows = [row for row in rows if row is not None]
    if rows:
        preserved = next((row.get("preserve") for row in rows if row.get("preserve")), None)
        rows.extend((preserved if preserved is not None else support.get("_preserve", {})).values())
    gap = definition_type_gap(feature, support)
    for row in rows:
        field, member, reader = row["field"], row["member"], row.get("reader")
        try:
            if gap:
                raise RuntimeError(gap)
            if reader == "hem_definition":
                from . import _sheet_edit
                state[field], definition[field] = _sheet_edit.hem_read(feature)
            elif reader == "plane_pair":
                source = getattr(feature, member)
                records = [(entity, reference_descriptor(entity, row["reference"]))
                           for entity in (source.planarEntityOne, source.planarEntityTwo)]
                state[field] = records
                definition[field] = {role: record[1]
                                     for role, record in zip(PLANE_PAIR_ROLES, records)}
            elif reader == "source_names":
                value = [entity.name for entity in getattr(feature, member)]
                if not value or any(not isinstance(name, str) or not name for name in value):
                    raise RuntimeError("source entity names are empty or unreadable")
                state[field] = definition[field] = value
            elif reader in ("flag", "text"):
                value = _feature_path(feature, member)
                if type(value) is not (bool if reader == "flag" else str) or value == "":
                    raise RuntimeError(f"{member} did not read a {reader} value")
                state[field] = definition[field] = value
            elif reader == "derived_parameters":
                # doc_insert_derive imports this module, so its census is bound at call time.
                from . import doc_insert_derive
                census, problem = doc_insert_derive.parameter_census(_common.design())
                if census is None or any(row_["derived"] is None for row_ in census.values()):
                    raise RuntimeError(problem or "a parameter did not read its type")
                value = sorted(name for name, row_ in census.items() if row_["derived"])
                state[field] = definition[field] = value
            elif reader == "health_name":
                actual = getattr(feature, member)
                states = adsk.fusion.FeatureHealthStates
                value = next((name for name, enum in (("healthy", "HealthyFeatureHealthState"),
                                                      ("warning", "WarningFeatureHealthState"),
                                                      ("error", "ErrorFeatureHealthState"))
                              if actual == getattr(states, enum)), None)
                if value is None:
                    raise RuntimeError(f"healthState reads {actual!r}")
                state[field] = definition[field] = value
            elif reader == "offset_expression":
                value = _feature_path(feature, member)
                if not isinstance(value, str) or not value.strip():
                    raise RuntimeError("offset expression is unreadable")
                state[field] = definition[field] = value
            elif reader in ("reference", "references", "single_reference_collection"):
                values = (collection_entities(getattr(feature, member))
                          if reader in ("references", "single_reference_collection")
                          else _feature_path(feature, row.get("read", member)))
                if values is None:
                    raise RuntimeError("operand collection is unreadable or exceeds 64 items")
                if reader == "single_reference_collection" and len(values) != 1:
                    raise RuntimeError("boundaryCurve must contain exactly one readable SketchCircle")
                if (reader == "single_reference_collection"
                        and safe(lambda: values[0].objectType) != "adsk::fusion::SketchCircle"):
                    raise RuntimeError("boundaryCurve's one member is not a readable SketchCircle")
                entities = values if isinstance(values, list) else [values]
                if not entities:
                    raise RuntimeError("operand collection is empty")
                records = [(entity, reference_descriptor(entity, row.get("reference", "entities")))
                           for entity in entities]
                state[field] = records if reader == "references" else records[0]
                definition[field] = [desc for _entity, desc in records] if reader == "references" else records[0][1]
            elif reader == "profiles":
                entities = collection_entities(getattr(feature, member))
                if not entities:
                    raise RuntimeError("profile collection is empty, unreadable or exceeds 64 items")
                records, public = [], []
                for entity in entities:
                    value = _profile_edit_definition(entity)
                    if value is None:
                        raise RuntimeError("profile definition has no usable handle or geometry")
                    descriptor, geometry = value
                    records.append((entity, {"kind": "profile",
                                             "owner": {"component": descriptor["source_component"]},
                                             "geometry": geometry}))
                    public.append(descriptor)
                state[field] = records
                definition[field] = public
            elif reader == "path":
                entities = path_entities(getattr(feature, member))
                if not entities:
                    raise RuntimeError("path is unreadable, empty or exceeds 64 members")
                records = [(entity, reference_descriptor(entity, "path")) for entity in entities]
                references = _path_public_references(feature, entities, records)
                if not references:
                    raise RuntimeError("path members have no exact usable typed input")
                state[field] = records
                definition[field] = {"member_count": len(entities), "references": references}
            elif reader == "scale_expressions":
                values = _scale_expressions(feature)
                if values is None:
                    raise RuntimeError("uniform or axis scale expressions are unreadable")
                state[field] = values
                definition[field] = values
            elif reader == "rule_faces":
                entities = collection_entities(_feature_path(feature, member))
                if not entities:
                    raise RuntimeError("rule face collection is empty or unreadable")
                records = [(entity, reference_descriptor(entity, "faces")) for entity in entities]
                state[field] = records
                definition[field] = [descriptor for _entity, descriptor in records]
            elif reader == "edge_sets":
                sets = edge_set_entities(feature, row)
                if sets is None or not sets:
                    raise RuntimeError("edge-set collection is unreadable or exceeds 64 items")
                public_sets = []
                for index, edge_set in enumerate(sets):
                    if safe(lambda edge_set=edge_set: edge_set.objectType) != row["set_type"]:
                        raise RuntimeError("edge set has an unsupported subtype")
                    edges = collection_entities(safe(lambda edge_set=edge_set: edge_set.edges))
                    if not edges:
                        raise RuntimeError("edge-set edges are empty or unreadable")
                    records = [(entity, reference_descriptor(entity, "edges")) for entity in edges]
                    control = safe(lambda edge_set=edge_set: _feature_path(edge_set, row["set_control"]))
                    if not isinstance(control, str) or not control:
                        raise RuntimeError("edge-set control is unreadable")
                    tangent = safe(lambda edge_set=edge_set: edge_set.isTangentChain)
                    if type(tangent) is not bool:
                        raise RuntimeError("edge-set tangent-chain control is unreadable")
                    edge_field = f"edge_set_{index}_edges"
                    state[edge_field] = records
                    state[f"edge_set_{index}_{row['set_control_field']}"] = control
                    state[f"edge_set_{index}_tangent_chain"] = tangent
                    set_definition = {"index": index, "type": row["set_type"].rsplit("::", 1)[-1],
                                      "edges": [descriptor for _entity, descriptor in records],
                                      row["set_control_field"]: control,
                                      "is_tangent_chain": tangent}
                    if row["set_type"] == "adsk::fusion::ConstantRadiusFilletEdgeSet":
                        continuity = safe(lambda edge_set=edge_set: edge_set.continuity)
                        weight = safe(lambda edge_set=edge_set: edge_set.tangencyWeight)
                        weight_value = safe(lambda: weight.value) if weight is not None else None
                        weight_expression = safe(lambda: weight.expression) if weight is not None else None
                        if (continuity is None or type(weight_value) not in (int, float)
                                or not math.isfinite(weight_value)
                                or not isinstance(weight_expression, str) or not weight_expression):
                            raise RuntimeError("fillet continuity controls are unreadable")
                        state[f"edge_set_{index}_continuity"] = continuity
                        state[f"edge_set_{index}_tangency_weight"] = weight_value
                        state[f"edge_set_{index}_tangency_weight_expression"] = weight_expression
                        set_definition.update(continuity=continuity, tangency_weight=weight_value,
                                             tangency_weight_expression=weight_expression)
                    public_sets.append(set_definition)
                definition[field] = public_sets
            elif reader == "angle_extent_expression":
                extent = adsk.fusion.AngleExtentDefinition.cast(getattr(feature, member))
                value = extent.angle.expression
                state[field] = definition[field] = value
            elif reader == "angle_extent_symmetric":
                extent = adsk.fusion.AngleExtentDefinition.cast(getattr(feature, member))
                value = extent.isSymmetric
                if type(value) is not bool:
                    raise RuntimeError("value is not a readable boolean")
                state[field] = definition[field] = value
            elif reader == "profile":
                entity = getattr(feature, member)
                value = _profile_edit_definition(entity)
                if value is None or not value[0].get("profile_handle"):
                    raise RuntimeError("profile definition has no usable handle")
                public, geometry = value
                state[field] = (entity, {"kind": "profile",
                                         "owner": {"component": public.get("source_component")},
                                         "geometry": geometry})
                definition[field] = public
            elif reader == "operation":
                actual = getattr(feature, member)
                value = next((name for name, enum in _common.OPERATIONS.items()
                              if actual == getattr(adsk.fusion.FeatureOperations, enum)), None)
                if value is None:
                    raise RuntimeError("operation is unreadable or unsupported")
                state[field] = definition[field] = value
            elif reader == "choice":
                actual = getattr(feature, member)
                enum_type = getattr(adsk.fusion, row["enum_type"])
                value = next((name for name, enum_name in row["values"].items()
                              if safe(lambda enum_name=enum_name: getattr(enum_type, enum_name)) == actual), None)
                if value is None:
                    raise RuntimeError("value is unreadable or unsupported")
                state[field] = definition[field] = value
            elif reader == "thread_info":
                raw = getattr(feature, member)
                value = _thread_info(raw, unavailable)
                if any(f"thread_info.{key}" in unavailable for key in value):
                    raise RuntimeError("one or more thread information fields are unreadable")
                state[field] = definition[field] = value
            elif reader == "count":
                value = counted(lambda: getattr(feature, member).count)
                if value is None:
                    raise RuntimeError("count is unreadable")
                state[field] = definition[field] = value
            elif reader == "list":
                value = list(getattr(feature, member))
                state[field] = definition[field] = value
            elif reader == "expression":
                value = getattr(feature, member).expression
                state[field] = definition[field] = value
            elif reader == "value":
                value = _feature_path(feature, member)
                state[field] = definition[field] = value
            elif reader == "thread_length":
                full_length = state.get("is_full_length")
                value = None if full_length is True else _feature_path(feature, member)
                state[field] = definition[field] = value
            elif reader == "nullable_expression":
                parameter = getattr(feature, member)
                value = None if parameter is None else parameter.expression
                if value is not None and (not isinstance(value, str) or not value):
                    raise RuntimeError("expression is not readable")
                state[field] = definition[field] = value
            elif reader == "boolean" or row.get("choices"):
                value = getattr(feature, member)
                if type(value) is not bool:
                    raise RuntimeError("value is not a readable boolean")
                state[field] = definition[field] = value
            else:
                raise RuntimeError(f"reader '{reader}' is not supported")
        except Exception as exc:
            state[field] = definition[field] = None
            unavailable[field] = str(exc).split(" / ")[0].strip()[:200]
    return state, definition, unavailable


def edge_set_entities(feature, row):
    """All measured edge sets through 64 items, or None when the collection is incomplete."""
    collection = safe(lambda: getattr(feature, row["set_collection"]))
    count = counted(lambda: collection.count)
    if count is None or count > 64:
        return None
    values = [safe(lambda i=i: collection.item(i)) for i in range(count)]
    return None if any(value is None for value in values) else values


def _same_reference(first, second):
    """Whether two consumed operands have the same native identity and measured placement geometry."""
    if first is None or second is None:
        return None
    left, right = first[0], second[0]
    left_key, right_key = _common.native_identity(left), _common.native_identity(right)
    same = left_key == right_key if left_key is not None and right_key is not None else None
    if same is not True:
        return same
    return (first[1].get("kind"), first[1].get("owner"), first[1].get("geometry")) == (
        second[1].get("kind"), second[1].get("owner"), second[1].get("geometry"))


def references_identified(now, want):
    """Whether re-read reference records carry the wanted native identities; None when a key is unread."""
    if isinstance(want, list) != isinstance(now, list):
        return False
    pairs = list(zip(now, want)) if isinstance(want, list) else [(now, want)]
    if isinstance(want, list) and len(now) != len(want):
        return False
    verdicts = []
    for got, wanted in pairs:
        left = _common.native_identity(got[0]) if got is not None else None
        right = _common.native_identity(wanted[0]) if wanted is not None else None
        verdicts.append(None if left is None or right is None else left == right)
    return False if False in verdicts else None if None in verdicts else True


def record_entities(records):
    """The entity, or ordered entities, a private reference state holds."""
    return [record[0] for record in records] if isinstance(records, list) else records[0]


def own_geometry(entity, role):
    """(a datum's world geometry or a joint origin's own origin and axes, None), or (None, why unread)."""
    if role != "joint_origin":
        try:
            return _reference_geometry(entity, role), None
        except Exception as exc:
            return None, str(exc)
    read = {"origin_cm": _geom._coords(safe(lambda: entity.transform.translation))}
    for key, member in (("primary_axis", "primaryAxisVector"),
                        ("secondary_axis", "secondaryAxisVector"),
                        ("third_axis", "thirdAxisVector")):
        read[key] = _geom.unit_vector(safe(lambda member=member: getattr(entity, member)))
    unread = [key for key, value in read.items() if value is None]
    if unread:
        return None, f"{', '.join(unread)} did not read"
    return {**read, "origin_cm": list(read["origin_cm"])}, None


def _write_offset_plane(datum, state, target):
    """Redefine an offset plane on `target`, passing its read offset expression back."""
    offset = adsk.core.ValueInput.createByString(state["offset"])
    return datum.definition.redefine(offset, target)


def _write_two_plane_axis(datum, _state, target):
    """Redefine a two-plane axis on the ordered pair `target`."""
    return datum.definition.redefine(target[0], target[1])


def _write_point_entity(datum, _state, target):
    """Assign a point datum's defining point entity; an assignment answers nothing."""
    datum.definition.pointEntity = target
    return None


_DATUM_WRITERS = {"offset_plane": _write_offset_plane, "two_plane_axis": _write_two_plane_axis,
                  "point_entity": _write_point_entity}


def write_datum(row, datum, state, target):
    """Run the row's closed datum writer; a redefine's bool, or None for an assignment."""
    return _DATUM_WRITERS[row["writer"]](datum, state, target)


def feature_reference_state(entities, role):
    """Private reference records for a resolved operand or its ordered operand list."""
    if role == "path":
        values = path_entities(entities)
        if not values:
            raise RuntimeError("resolved path has no readable members")
        return [(entity, reference_descriptor(entity, "path")) for entity in values]
    if role == "profiles":
        values = entities if isinstance(entities, list) else [entities]
        records = []
        for entity in values:
            value = _profile_edit_definition(entity)
            if value is None:
                raise RuntimeError("resolved profile has no usable handle or geometry")
            descriptor, geometry = value
            records.append((entity, {"kind": "profile",
                                     "owner": {"component": descriptor["source_component"]},
                                     "geometry": geometry}))
        return records
    values = entities if isinstance(entities, list) else [entities]
    records = [(entity, reference_descriptor(entity, role)) for entity in values]
    return records if isinstance(entities, list) else records[0]


def same_feature_edit_state(before, after, desired=None):
    """Whether all retained controls match and the requested private reference actually landed."""
    if not isinstance(before, dict) or not isinstance(after, dict) or set(before) != set(after):
        return None
    desired_fields = (desired.get("fields", {}) if desired else {})
    if desired and not desired_fields:
        desired_fields = {desired["field"]: desired["value"]}
    for field, was in before.items():
        now = after[field]
        if field in desired_fields:
            want = desired_fields[field]
            if isinstance(was, tuple):
                if _same_reference(now, want) is not True:
                    return False
            elif isinstance(was, list):
                if not isinstance(now, list) or len(now) != len(want):
                    return False
                if any(_same_reference(a, b) is not True for a, b in zip(now, want)):
                    return False
            elif now != want:
                return False
        elif isinstance(was, tuple):
            if _same_reference(was, now) is not True:
                return False
        elif isinstance(was, list) and was and isinstance(was[0], tuple):
            if not isinstance(now, list) or len(was) != len(now):
                return False
            if any(_same_reference(a, b) is not True for a, b in zip(was, now)):
                return False
        elif now != was:
            return False
    return True


def feature_definition(feature, factor):
    """Format an independently readable feature definition without rolling."""
    feature_type = safe(lambda: feature.objectType)
    if feature_type in FEATURE_EDIT_SUPPORT:
        state, definition, unavailable = feature_edit_state(feature)
        return feature_definition_view(feature, state, definition, unavailable)
    if safe(lambda: feature.objectType) == "adsk::fusion::ExtrudeFeature":
        read = read_extrude_definition(feature, limit=64)
        kind = read["extent"]
        applicable = None if kind is None else kind in ("distance", "two_side", "symmetric")
        out = {key: read[key] for key in ("operation", "extent", "distance_parameter", "distance_expression",
            "extent_side_count", "direction", "distance2_parameter", "distance2_expression",
            "symmetric_full_length", "participants",
            "participants_truncated", "not_read", "unavailable")}
        out.update(distance=_common.measured(lambda: read["distance_cm"], factor),
                   distance2=_common.measured(lambda: read["distance2_cm"], factor),
                   distance_applicable=applicable,
                   distance2_applicable=None if kind is None else kind == "two_side")
    else:
        read = read_sweep_definition(feature)
        unavailable = dict(read["unavailable"])
        participants, truncated = _definition_participants(feature, unavailable, 64)
        path = read["path"]
        count = counted(lambda: path.count)
        out = {"operation": next((name for name, enum in _common.OPERATIONS.items()
                                  if read["operation"] == getattr(adsk.fusion.FeatureOperations, enum)), None),
               "orientation": read["orientation"], "orientation_name": read["orientation_name"],
               "is_solid": read["is_solid"],
               "path": ([_definition_profile(safe(lambda i=i: path.item(i).entity))
                         for i in range(min(count, 64))] if count is not None else None),
               "path_count": count,
               "path_truncated": None if count is None else count > 64,
               "participants": participants, "participants_truncated": truncated,
               "unavailable": unavailable}
    out["profile"] = _definition_profile(read["profile"])
    return out


def feature_definition_view(feature, state, definition, unavailable):
    """Build the public definition from one complete private snapshot without another API read."""
    feature_type = safe(lambda: feature.objectType)
    address = _inputs.candidate_address(safe(lambda: feature.timelineObject))
    if not address:
        unavailable["feature_address"] = "qualified timeline address is unreadable"
    not_read = (["length", "offset"]
                if feature_type == "adsk::fusion::ThreadFeature"
                and state.get("is_full_length") is True else [])
    scope = ({"derived_parameters_scope": "design"}
             if feature_type == "adsk::fusion::DeriveFeature" else {})
    return {**definition, **scope, "feature_address": address,
            "supported_edits": feature_edit_rows(feature, definition),
            "not_read": not_read, "unavailable": unavailable}


def feature_geometry_snapshot(design):
    """All body shapes and occurrence world frames, or None when the independent census is incomplete."""
    shapes = all_shapes(design)
    walk = _common.occurrence_walk(design)
    if shapes is None or not walk.complete or walk.broken:
        return None
    frames = {}
    for occurrence in walk.occurrences:
        path = safe(lambda o=occurrence: o.fullPathName)
        frame = _geom.occ_world_frame(occurrence, 1.0)
        if (not isinstance(path, str) or not path or path in frames
                or not all(key in frame for key in ("origin", "x_axis", "y_axis", "z_axis"))):
            return None
        frames[path] = frame
    return {"bodies": shapes, "occurrences": frames}


def surface_normal_snapshot(bodies, cap=64):
    """A bounded face-normal census for selected surface bodies, or None when unread."""
    rows = {}
    for body in bodies:
        key = _common.native_identity(body)
        faces = safe(lambda body=body: body.faces)
        count = counted(lambda faces=faces: faces.count)
        if key is None or key in rows or count is None or count == 0 or count > cap:
            return None
        samples = []
        for i in range(count):
            face = safe(lambda i=i, faces=faces: faces.item(i))
            point = safe(lambda face=face: face.pointOnFace)
            center = _geom._coords(safe(lambda face=face: face.centroid))
            normal = _geom.evaluator_normal_at(face, point) if point is not None else None
            area = safe(lambda face=face: face.area)
            reversed_flag = safe(lambda face=face: face.isParamReversed)
            if (center is None or normal is None or not isinstance(area, (int, float))
                    or isinstance(area, bool) or type(reversed_flag) is not bool):
                return None
            samples.append({"area": round(float(area), 9), "center": tuple(round(v, 7) for v in center),
                            "normal": tuple(normal), "reversed": reversed_flag})
        rows[key] = sorted(samples, key=lambda row: (row["area"], row["center"], row["normal"]))
    return rows or None


def surface_normals_reversed(before, after, old_targets, new_targets):
    """Whether changed ReverseNormal selections flip only their added or removed bodies."""
    if before is None or after is None or not old_targets or not new_targets:
        return None
    old_keys = [_common.native_identity(body) for body in old_targets]
    new_keys = [_common.native_identity(body) for body in new_targets]
    keys = old_keys + new_keys
    if (any(key is None for key in keys) or len(set(old_keys)) != len(old_keys)
            or len(set(new_keys)) != len(new_keys) or set(before) != set(keys)
            or set(after) != set(keys)):
        return None
    old_set, new_set = set(old_keys), set(new_keys)
    for key in set(keys):
        old, new = before.get(key), after.get(key)
        if not isinstance(old, list) or not isinstance(new, list) or len(old) != len(new):
            return False
        for was, now in zip(old, new):
            if was["area"] != now["area"] or was["center"] != now["center"]:
                return False
            should_flip = (key in new_set) != (key in old_set)
            if should_flip:
                if (any(abs(was["normal"][i] + now["normal"][i]) > 1e-5 for i in range(3))
                        or was["reversed"] is now["reversed"]):
                    return False
            elif (any(abs(was["normal"][i] - now["normal"][i]) > 1e-5 for i in range(3))
                  or was["reversed"] is not now["reversed"]):
                return False
    return True


def _empty_solid_shape(body):
    """Measured zero-geometry solid, or None when any required read is unavailable."""
    valid, solid = safe(lambda: body.isValid), safe(lambda: body.isSolid)
    area, volume = safe(lambda: body.area), _geom.signed_volume(body)
    faces = counted(lambda: body.faces.count)
    edges = counted(lambda: body.edges.count)
    lumps = counted(lambda: body.lumps.count)
    numbers = (area, volume)
    if (valid is not True or solid is not True
            or (faces, edges, lumps) != (0, 0, 0)
            or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                   or not math.isfinite(value) or value != 0 for value in numbers)):
        return None
    return {"empty": True, "solid": True, "area_cm2": 0.0, "volume_cm3": 0.0,
            "face_count": faces, "edge_count": edges, "lump_count": lumps}


def path_sketch_visibility_restore(comp, raw_path):
    """Return a verified bulb-restorer for a named sketch path, or None when its state is unreadable."""
    if not isinstance(raw_path, str) or ":" not in raw_path:
        return None
    kind, name = raw_path.split(":", 1)
    if kind.strip().lower() != "sketch" or not name.strip():
        return None
    sketch, _ = _common.target_sketch(comp, name.strip())
    light = safe(lambda: sketch.isLightBulbOn) if sketch is not None else None
    visible = safe(lambda: sketch.isVisible) if sketch is not None else None
    if type(light) is not bool or type(visible) is not bool:
        return None

    def restore():
        sketch.isLightBulbOn = light
        return (safe(lambda: sketch.isLightBulbOn) is light
                and safe(lambda: sketch.isVisible) is visible)
    return restore


def all_shapes(design, allow_empty_solids=False, components=None):
    """Native body snapshots across supplied components or the design, or None when unreadable."""
    if components is None:
        components = safe(lambda: list(design.allComponents))
    if not components:
        return None
    rows = {}
    for component in components:
        bodies = safe(lambda c=component: c.bRepBodies)
        count = counted(lambda: bodies.count)
        if count is None:
            return None
        for i in range(count):
            body = safe(lambda i=i: bodies.item(i))
            key = _common.native_identity(body)
            shape = _geom.body_shape(body)
            if shape is None and allow_empty_solids:
                shape = _empty_solid_shape(body)
            if key is None or shape is None or key in rows:
                return None
            rows[key] = {"component": safe(lambda c=component: c.name),
                         "body": safe(lambda b=body: b.name), "shape": shape}
    return rows


def retire_failed_create(design, feature, before_timeline, before_shapes, components, before_marker,
                         restore_input_visibility=None):
    """Remove only a new last feature with unchanged material, reporting verified timeline restoration."""
    index = counted(lambda: feature.timelineObject.index)
    address = (_inputs.candidate_address(safe(lambda: feature.timelineObject))
               or safe(lambda: feature.name))
    visibility_check = (" Path sketch visibility may have changed; re-read with sketch_get."
                        if restore_input_visibility is not None else "")
    remedy = (f"Feature '{address}' was retained; inspect it with design_get and remove it with "
              "design_delete_feature.") if address else _common.failed_effect_remedy(design, feature)
    address = address or "(name unreadable)"
    if _inputs.current_design_type(design) != _inputs.MODE_PARAMETRIC:
        return (f"Automatic cleanup of '{address}' was not attempted outside a readable PARAMETRIC "
                "design; inspect with design_get or undo in Fusion." + visibility_check)
    now = _design_common.timeline_census(design)
    old_rows = (before_timeline or {}).get("items")
    rows = (now or {}).get("items")
    complete = (isinstance(old_rows, list) and isinstance(rows, list)
                and not before_timeline["collapsed_groups"] and not now["collapsed_groups"]
                and all(r["key"] and r["name"] and r["index"] == i
                        and type(r["suppressed"]) is bool for i, r in enumerate(rows))
                and len({r["key"] for r in rows}) == len(rows))
    if (not complete or before_marker != len(old_rows) or len(rows) != len(old_rows) + 1
            or rows[:-1] != old_rows or index != len(old_rows)
            or _common.timeline_marker(design) != (len(rows), len(rows))
            or safe(lambda: design.timeline.item(index).entity == feature) is not True
            or before_shapes is None or all_shapes(design, components=components) != before_shapes):
        return remedy + visibility_check
    try:
        removed = feature.deleteMe()
    except Exception as exc:
        return (f"Cleanup of '{address}' raised: {exc}. Removal is unconfirmed; re-read "
                "design_get(include=['timeline']) before using design_delete_feature."
                + visibility_check)
    after = _design_common.timeline_census(design)
    if (removed is True and after == before_timeline
            and _common.timeline_marker(design) == (before_marker, before_marker)
            and all_shapes(design, components=components) == before_shapes):
        visibility = ""
        if restore_input_visibility is not None:
            try:
                restored = restore_input_visibility()
            except Exception:
                restored = False
            visibility = (" The path sketch visibility was restored." if restored is True else
                          " Path sketch visibility is unconfirmed; re-read it with sketch_get.")
        return (f"Failed feature '{address}' was removed; the prior timeline and checked body shapes "
                f"were restored.{visibility}")
    return (f"Cleanup of '{address}' returned {removed!r}, but restoration is unconfirmed; re-read "
            "design_get(include=['timeline']) and model_inspect before using design_delete_feature."
            + visibility_check)


def feature_body_keys(feature):
    """Native identities of result bodies, or None on an unreadable collection."""
    bodies = safe(lambda: feature.bodies)
    count = counted(lambda: bodies.count)
    if count is None:
        return None
    keys = {_common.native_identity(safe(lambda i=i: bodies.item(i))) for i in range(count)}
    return None if None in keys else keys


def health(design, marker):
    """Evaluated timeline errors and warnings, collapsed-group members included, or None when unread."""
    timeline = safe(lambda: design.timeline)
    states = adsk.fusion.FeatureHealthStates
    known = (states.HealthyFeatureHealthState, states.WarningFeatureHealthState,
             states.ErrorFeatureHealthState)
    grouped = {states.ErrorFeatureHealthState: [], states.WarningFeatureHealthState: []}
    for i in range(marker):
        item = safe(lambda i=i: timeline.item(i))
        if _common.read_flag(lambda: item.isGroup) is not True:
            if safe(lambda: item.healthState) not in known:
                return None
            continue
        # A collapsed group row reads its own healthState outside these three; its members carry theirs.
        count = counted(lambda: item.count)
        members = [safe(lambda j=j: item.item(j)) for j in range(count or 0)]
        if count is None or None in members:
            return None
        for member in members:
            state = safe(lambda: member.healthState)
            if state not in known:
                return None
            grouped.get(state, []).append(_common._HealthName(
                safe(lambda: member.name) or f"#{i}", safe(lambda: member.entity.entityToken)))
    errors, warnings, total = _common.timeline_health(design, limit=marker)
    return ({"errors": errors + grouped[states.ErrorFeatureHealthState],
             "warnings": warnings + grouped[states.WarningFeatureHealthState]}
            if total == marker else None)


def same_feature(design, token, feature, index, count):
    """Whether the saved feature still occupies its original timeline row."""
    found = safe(lambda: design.findEntityByToken(token))
    if found is None:
        return None
    same = safe(lambda: any(entity == feature for entity in found))
    return (same is True and safe(lambda: feature.isValid) is True
            and counted(lambda: feature.timelineObject.index) == index
            and counted(lambda: design.timeline.count) == count)


def operand_source(entity):
    """(source sketch/body/entity, its timeline row or None, whether that source is a sketch)."""
    native = _common._native_of(entity)
    sketch = safe(lambda: native.parentSketch)
    source = sketch if sketch is not None else (safe(lambda: native.body) or native)
    return source, counted(lambda: source.timelineObject.index), sketch is not None


def later_operand_refusal(label, index, operands):
    """The refusal for the first operand drawn in a sketch at or after row `index`, else None."""
    for entity in operands:
        source, row, from_sketch = operand_source(entity)
        if not from_sketch or row is None or row < index:
            continue
        name = safe(lambda: source.name)
        return (f"Editing '{label}': sketch '{name}' is at timeline row {row}, after '{label}' at "
                f"row {index}. Move it first with design_edit_timeline(action='reorder', "
                f"feature='{name}@{row}', to='before', end_feature='{label}@{index}'), then retry. "
                "Nothing was edited.")
    return None


def body_creator(design, body):
    """(name, row) of the ONE timeline feature whose bodies hold `body`, else None."""
    timeline = safe(lambda: design.timeline)
    native = _common._native_of(body)
    if native is None:
        return None
    key = _common.native_identity(native)
    hits = []
    for i in range(counted(lambda: timeline.count) or 0):
        item = safe(lambda i=i: timeline.item(i))
        # A group row lists none of its members, so a walk that meets one names no feature.
        if _common.read_flag(lambda item=item: item.isGroup) is not False:
            return None
        bodies = safe(lambda item=item: item.entity.bodies)
        for k in range(counted(lambda bodies=bodies: bodies.count) or 0):
            held = _common._native_of(safe(lambda bodies=bodies, k=k: bodies.item(k)))
            if held is not None and (safe(lambda held=held: held == native) is True or (
                    key is not None and _common.native_identity(held) == key)):
                hits.append((safe(lambda item=item: item.name),
                             counted(lambda item=item: item.index)))
                break
    return hits[0] if len(hits) == 1 and None not in hits[0] else None


def sketch_address(entity):
    """(sketch, 'profile' or a curve kind, index) naming a native profile or curve, or None."""
    native = _common._native_of(entity)
    sketch = safe(lambda: native.parentSketch)
    if sketch is None:
        return None
    # The two pieces a split returns share one entityToken, so both kinds match by identity.
    profiles = safe(lambda: sketch.profiles)
    hits = [i for i in range(counted(lambda: profiles.count) or 0)
            if safe(lambda i=i: profiles.item(i) == native) is True]
    if hits:
        return (sketch, "profile", hits[0]) if len(hits) == 1 else None
    kind, _, index = (_sketch_detail.curve_id(sketch, native) or "").rpartition(":")
    return (sketch, kind, int(index)) if kind else None


def at_address(address):
    """The profile or sketch curve a sketch_address names now, or None."""
    sketch, kind, index = address
    if kind != "profile":
        return _common.resolve_entity_ref(sketch, f"{kind}:{index}")
    profiles = safe(lambda: sketch.profiles)
    return safe(lambda: profiles.item(index)) if index < (counted(lambda: profiles.count) or 0) else None


def address_text(address):
    """A sketch_address as an outcome sentence names it: a profile, or '<sketch>/<kind>:<i>'."""
    if address is None:
        return None
    sketch, kind, index = address
    name = safe(lambda: sketch.name)
    return f"sketch '{name}' profile {index}" if kind == "profile" else f"{name}/{kind}:{index}"


def restore_definition(design, entity, restore, read_definition, evaluate_at, snapshot, park):
    """Run `restore` at `entity`'s row, re-read it there, `snapshot` at `evaluate_at`, park at `park`."""
    timeline = safe(lambda: design.timeline)
    errors, ran = [], []

    def step():
        index = counted(lambda: entity.timelineObject.index)
        if index is None or counted(lambda: timeline.markerPosition) != index:
            raise RuntimeError("the marker did not reach the feature's edit position")
        ran.append(True)
        try:
            restore()
        except Exception as exc:
            errors.append(f"the restore raised: {exc}")
        definition = read_definition(entity)
        timeline.markerPosition = evaluate_at
        if counted(lambda: timeline.markerPosition) != evaluate_at:
            raise RuntimeError("the restored feature could not be evaluated")
        return definition, snapshot()

    try:
        got, _clause = _common.rolled_to(design, entity, step, "the restore", park=park)
    except Exception as exc:
        got = None
        errors.append(str(exc))
    if got is None and not errors:
        errors.append("the feature could not be rolled to its edit position")
    definition, shapes = got if got is not None else (None, None)
    return {"ran": bool(ran), "error": "; ".join(errors) or None, "definition": definition,
            "shapes": shapes, "marker_after": counted(lambda: timeline.markerPosition)}


_GAPS = {"definition": ("the definition re-read differs from before the edit",
                        "the definition was not re-read"),
         "scope": ("the participant scope differs from before the edit",
                   "the participant scope was not re-read"),
         "shapes": ("the bodies do not match the pre-edit read", "the bodies were not re-read"),
         "health": ("the timeline health does not match before the edit",
                    "the timeline health was not re-read"),
         "row": ("the feature did not re-read at its row", "the feature's row was not re-read"),
         "identity": ("the original feature identity was not restored",
                      "the original feature identity was not re-read"),
         "owner": ("the feature owner changed during restoration",
                   "the feature owner was not re-read"),
         "surface_normals": ("the selected surface normals do not match the pre-edit read",
                             "the selected surface normals were not re-read"),
         "marker": ("the timeline marker was not restored to its original end",
                    "the timeline marker was not re-read"),
         "count": ("the timeline count changed during restoration",
                   "the timeline count was not re-read")}


def restore_gaps(error, **held):
    """Why a restore's re-read does not prove the pre-edit state: False differs, None was unread."""
    return ([error] if error else []) + [_GAPS[name][good is None] for name, good in held.items()
                                         if good is not True]


def matched(got, want):
    """None when either side was not read, else whether they are equal."""
    return None if got is None or want is None else got == want


def _by_component(shapes):
    """An all_shapes snapshot as {component: [(identity, body name, shape repr)]}."""
    grouped = {}
    for key, row in shapes.items():
        grouped.setdefault(row["component"], []).append((key, row["body"], repr(row["shape"])))
    return grouped


def shape_match(after, before):
    """(whether each component's body shapes match, re-created bodies), (None, []) when unread."""
    if after is None or before is None:
        return None, []
    now, was = _by_component(after), _by_component(before)
    profile = lambda side: {c: sorted(row[2] for row in rows) for c, rows in side.items()}
    recreated = []
    for component in sorted(set(now) & set(was), key=str):
        kept = {row[:2] for row in now[component]} & {row[:2] for row in was[component]}
        gone = [row for row in was[component] if row[:2] not in kept]
        new = [row for row in now[component] if row[:2] not in kept]
        for shape in sorted({row[2] for row in gone}):
            now_names = sorted((row[1] for row in new if row[2] == shape), key=str)
            if now_names:
                was_names = sorted((row[1] for row in gone if row[2] == shape), key=str)
                recreated.append({"component": component, "now": now_names, "was": was_names})
    return profile(now) == profile(was), recreated


def rolled_back_text(rows, recreated):
    """The verified-restore sentence over (field, now, was), naming any body shape_match re-created."""
    if not recreated:
        return _common.outcome_clause("rolled_back", "", rows,
                                      evidence="the bodies match the pre-edit read")
    quoted = lambda names: ", ".join(f"'{name}'" for name in names)
    many = len(recreated) > 1 or len(recreated[0]["now"]) > 1
    return (_common.outcome_clause("rolled_back", "", rows,
                                   evidence="the body shapes match the pre-edit read")
            + f" The {'bodies now read' if many else 'body now reads'} as "
            + ", ".join(f"{quoted(r['now'])} (was {quoted(r['was'])})" for r in recreated)
            + f"; re-read names and handles held for {'them' if many else 'it'}.")


def sentence(text):
    """`text` as a sentence ending in a full stop, for a raised message quoted as a reason."""
    text = str(text).strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def failed(text, details):
    """An error result carrying the observed edit state in 'details'."""
    result = _common.error(text)
    result["details"] = details
    result["content"].extend(_common.ok({"details": details})["content"])
    return result


def identical_geometry_reply(details):
    """Success for a definition that landed and re-read clean while its bodies read identical."""
    details["edited"] = True
    details["note"] += " The body geometry reads identical before and after."
    return _common.ok(details)
