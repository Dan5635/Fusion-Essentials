# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Copy or rehome one BRep or mesh body, retaining its selected assembly context."""

import json
import math

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _geom, _inputs, _outputs
from ._common import error, ok, safe


_ACTION = _inputs.Choice("action", ("copy", "move", "create_component", "merge_faces"), required=True)
_BODY = _inputs.BodyRef("body", kind="any", required=True, description="Body handle or name.")
_FACES = _inputs.GeometryHandleList("faces", require="face", json_array=True, required=True,
                                    description="Face handles to merge.")
_DESTINATION = _inputs.OccurrenceRef("destination", allow_root=True)
RETURNS = [
    _outputs.ReturnsHandle("handle", require="body", in_list=False,
                           consumers=["model_inspect", "model_edit_body"]),
    _outputs.ReturnsName("full_path", of="result occurrence", absent_when="at_root"),
]
_VERTEX_CAP = 16
_WITNESS_CAP = 4
_PATH_CAP = 8
_TOL_CM = 1e-6
_IDENTITY_FRAME = (1.0, 0.0, 0.0, 0.0,
                   0.0, 1.0, 0.0, 0.0,
                   0.0, 0.0, 1.0, 0.0,
                   0.0, 0.0, 0.0, 1.0)


def _native(body):
    """The native body represented by a native or proxy wrapper."""
    return _common._native_of(body)


def _kind(body):
    """The measured body family, or None when the wrapper type is unexpected."""
    if isinstance(body, adsk.fusion.MeshBody):
        return "mesh"
    if isinstance(body, adsk.fusion.BRepBody):
        return "brep"
    return None


def _known_component_match(a, b):
    """A known component identity comparison, never an unknown match."""
    verdict = _common.same_component(a, b)
    if verdict is None:
        raise ValueError("Component identity is unreadable")
    return verdict


def _same_entity(a, b):
    """A known native entity identity comparison across fresh wrappers."""
    if a is b:
        return True
    first, second = _common.native_identity(a), _common.native_identity(b)
    if first is None or second is None:
        raise ValueError("Entity identity is unreadable")
    return first == second


def _same_occurrence(a, b):
    """Whether two occurrences place the same component at one exact path."""
    # Nested native occurrence tokens do not read; exact paths distinguish placements.
    first, second = a.fullPathName, b.fullPathName
    if not isinstance(first, str) or not first or not isinstance(second, str) or not second:
        raise ValueError("Occurrence placement path is unreadable")
    return first == second and _known_component_match(a.component, b.component)


def _destination_owner(destination):
    """The component definition selected by an occurrence, or the root component itself."""
    return safe(lambda: destination.component) or destination


def _destination_is_root(destination, root):
    """Whether the destination occurrence selects the root component."""
    return _known_component_match(_destination_owner(destination), root)


def _members(component, kind):
    """Every body in one owner's collection, refusing an unreadable census."""
    coll = component.meshBodies if kind == "mesh" else component.bRepBodies
    count = coll.count
    if not isinstance(count, int) or count < 0:
        raise ValueError("Owner body count is unreadable")
    members = [coll.item(i) for i in range(count)]
    if any(body is None for body in members):
        raise ValueError("Owner body collection has an unreadable item")
    return members


def _contains_key(members, key):
    """Whether exactly one scoped member has a saved native identity."""
    identities = [_common.native_identity(_native(body)) for body in members]
    if key is None or any(identity is None for identity in identities):
        raise ValueError("Body identity is unreadable")
    return identities.count(key) == 1


def _contains(members, native):
    """Whether exactly one scoped member represents this readable native body."""
    return _contains_key(members, _common.native_identity(native))


def _placements(design, component):
    """Every readable placement of one owner, with no design-wide geometry census."""
    root = design.rootComponent
    if _known_component_match(component, root):
        return []
    coll = root.allOccurrencesByComponent(component)
    count = coll.count
    if not isinstance(count, int) or count < 0:
        raise ValueError("Owner occurrence count is unreadable")
    placements = [coll.item(i) for i in range(count)]
    if any(occ is None or not isinstance(safe(lambda o=occ: o.fullPathName), str)
           for occ in placements):
        raise ValueError("Owner placement path is unreadable")
    return placements


def _paths(placements):
    """A capped list plus the full affected-instance count."""
    paths = [occ.fullPathName for occ in placements]
    return {"count": len(paths), "paths": paths[:_PATH_CAP], "truncated": len(paths) > _PATH_CAP}


def _placement_frames(placements):
    """The scoped placement paths and finite world transforms."""
    frames = {}
    for occ in placements:
        path = occ.fullPathName
        values = tuple(float(value) for value in occ.transform2.asArray())
        if len(values) != 16 or not all(math.isfinite(value) for value in values):
            raise ValueError(f"Placement '{path}' transform is unreadable")
        if path in frames:
            raise ValueError(f"Placement path '{path}' is ambiguous")
        frames[path] = values
    return frames


def _same_frames(before, after):
    """Whether each scoped placement retained its world transform."""
    return before.keys() == after.keys() and all(
        all(abs(a - b) <= _TOL_CM for a, b in zip(before[path], after[path]))
        for path in before)


def _children(component):
    """Every direct child occurrence, refusing an unreadable census."""
    coll = component.occurrences
    count = coll.count
    if not isinstance(count, int) or count < 0:
        raise ValueError("Owner child count is unreadable")
    children = [coll.item(i) for i in range(count)]
    if any(child is None for child in children):
        raise ValueError("Owner child collection has an unreadable item")
    return children


def _point(point):
    """A finite coordinate triple in Fusion's internal centimeters."""
    values = (float(point.x), float(point.y), float(point.z))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Body coordinate is not finite")
    return values


def _shape(body, kind):
    """A bounded world-frame geometry sample and direct area/volume signals."""
    if kind == "mesh":
        mesh = body.displayMesh
        raw = mesh.nodeCoordinates
        indices = mesh.nodeIndices
        count = mesh.triangleCount
        if len(indices) != 3 * count or not indices or not all(0 <= i < len(raw) for i in indices):
            raise ValueError("Mesh display topology is unreadable")
        distinct = {_point(raw[i]) for i in indices}
        census = len(distinct)
        context = body.assemblyContext
        if context is not None:
            matrix = context.transform2
            placed = []
            for x, y, z in distinct:
                point = adsk.core.Point3D.create(x, y, z)
                if point.transformBy(matrix) is not True:
                    raise ValueError("Mesh world transform failed")
                placed.append(_point(point))
            distinct = set(placed)
        sampled = sorted(distinct)[:_VERTEX_CAP]
    else:
        vertices = body.vertices
        census = vertices.count
        sampled = sorted(_point(vertices.item(i).geometry) for i in range(census))[:_VERTEX_CAP]
    if kind == "brep" and not sampled:
        box, _ = _geom._body_box(body)
        if box is None:
            raise ValueError("BRep bounds are unreadable")
    else:
        box = body.boundingBox
    bounds = (_point(box.minPoint), _point(box.maxPoint))
    volume, area = float(body.volume), float(body.area)
    if not all(math.isfinite(v) for v in (volume, area)):
        raise ValueError("Body area or volume is not finite")
    return {"vertices_cm": sampled, "vertex_total": census, "sample_truncated": census > _VERTEX_CAP,
            "bounds_cm": bounds, "volume_cm3": volume, "area_cm2": area,
            "method": "world_vertex_sample" if sampled else "world_bounds"}


def _same_shape(before, after, kind="brep"):
    """Whether bounded geometry signals agree without treating a box as exact topology."""
    if before["vertex_total"] != after["vertex_total"]:
        return False
    if len(before["vertices_cm"]) != len(after["vertices_cm"]):
        return False
    left, right = before["vertices_cm"], after["vertices_cm"]
    matches = [None] * len(right)

    def place(index, visited):
        for candidate, other in enumerate(right):
            if candidate in visited or not all(abs(a - b) <= _TOL_CM
                                                for a, b in zip(left[index], other)):
                continue
            visited.add(candidate)
            if matches[candidate] is None or place(matches[candidate], visited):
                matches[candidate] = index
                return True
        return False

    if not all(place(index, set()) for index in range(len(left))):
        return False
    box_ok = (bool(before["vertices_cm"]) or
              all(abs(a - b) <= _TOL_CM
                  for side_a, side_b in zip(before["bounds_cm"], after["bounds_cm"])
                  for a, b in zip(side_a, side_b)))
    area_ok = (math.isclose(before["area_cm2"], after["area_cm2"],
                            rel_tol=1e-6, abs_tol=1e-6) if kind == "mesh"
               else abs(before["area_cm2"] - after["area_cm2"]) <= _TOL_CM)
    return (box_ok and abs(before["volume_cm3"] - after["volume_cm3"]) <= _TOL_CM
            and area_ok)


def _context_body(native, occurrence):
    """Reacquire a body's requested placement, or its root native wrapper."""
    return native if occurrence is None else native.createForAssemblyContext(occurrence)


def _result_occurrence(design, owner, source_context, action, destination):
    """The exact intended result placement, or an ambiguity error."""
    if action != "create_component":
        return (None, None) if _destination_is_root(destination, design.rootComponent) else (destination, None)
    placements = _placements(design, owner)
    if source_context is not None:
        parent_path = source_context.fullPathName
        placements = [occ for occ in placements if occ.fullPathName.rpartition("+")[0] == parent_path]
    if len(placements) != 1:
        return None, (f"New child has {len(placements)} matching placements; cannot mint one "
                      "body handle. Inspect design_get(include=['tree']) and choose the intended instance.")
    return placements[0], None


def _partial_state(partial, source_owner, destination_owner, kind):
    """Read scoped counts after an uncertain native result without claiming rollback."""
    partial["source_membership_after"] = safe(lambda: len(_members(source_owner, kind)))
    if destination_owner is not None:
        partial["destination_membership_after"] = safe(lambda: len(_members(destination_owner, kind)))
    return json.dumps(partial)


def _merge_material(body):
    """Finite area, volume and root-frame bounds in internal units, or None."""
    try:
        box = body.boundingBox
        values = (float(body.area), float(body.volume),
                  *[float(getattr(point, axis)) for point in (box.minPoint, box.maxPoint)
                    for axis in ("x", "y", "z")])
        return values if all(math.isfinite(value) for value in values) else None
    except Exception:
        return None


def _merge_pair_error(faces):
    """The reason two selected planar faces cannot be merged, or None."""
    keys = [_common.native_identity(face) for face in faces]
    if None in keys or len(set(keys)) != 2:
        return "Pass two distinct readable face handles from find_geometry."
    planes = [_geom._face_plane(face) for face in faces]
    if any(origin is None or normal is None for origin, normal in planes):
        return "Both selected faces must be planar."
    (origin, normal), (other, other_normal) = planes
    if (abs(abs(sum(a * b for a, b in zip(normal, other_normal))) - 1) > 1e-9 or
            abs(sum((a - b) * n for a, b, n in zip(origin, other, normal))) > 1e-7):
        return "The selected faces are on different planes; choose two coplanar faces."
    edge_sets = []
    for face in faces:
        edges = safe(lambda: face.edges)
        count = _common.counted(lambda: edges.count)
        if count is None:
            return "Selected face edges did not read; their connection is unverified."
        edge_keys = [_common.native_identity(safe(lambda i=i: edges.item(i))) for i in range(count)]
        if None in edge_keys:
            return "Selected edge identities did not read; their connection is unverified."
        edge_sets.append(set(edge_keys))
    if not edge_sets[0].intersection(edge_sets[1]):
        return "The selected faces share no edge; choose two connected coplanar faces."
    return None


def _merge_faces(faces):
    """Merge an adjacent planar pair and verify face count and material preservation."""
    design, design_refusal = _common.require_design(none_only=True)
    if design_refusal is not None:
        return design_refusal
    if _inputs.current_design_type(design) != "direct":
        return error("Face merge requires a direct design; the current design history is unchanged. "
                     "Use a separate direct-design copy. Parametric BaseFeature copying is not supported.")
    selected, refusal = _FACES.resolve(faces)
    if refusal:
        return error(refusal)
    if len(selected) != 2:
        return error(f"action='merge_faces' needs exactly two connected coplanar faces; got {len(selected)}.")
    bodies = [safe(lambda face=face: face.body) for face in selected]
    keys = [_common.native_identity(body) for body in bodies]
    if None in keys or len(set(keys)) != 1:
        return error("The selected faces must belong to the same solid body.")
    body = bodies[0]
    name = safe(lambda: body.name)
    if (safe(lambda: body.isSolid) is not True or
            any(safe(lambda face=face: face.assemblyContext) is not None for face in selected) or
            _common.same_component(safe(lambda: body.parentComponent), design.rootComponent) is not True):
        return error(f"Body '{name}' must be a solid in the root component.")
    refusal = _merge_pair_error(selected)
    if refusal:
        return error(refusal)
    count_before = _common.counted(lambda: body.faces.count)
    before = _merge_material(body)
    if count_before is None or before is None:
        return error(f"Body '{name}' face count or material did not read; nothing was merged.")
    returned, failure = None, None
    try:
        features = design.rootComponent.features.mergeFacesFeatures
        merge_input = features.createInput(selected, False)
        returned = features.add(merge_input)
    except Exception as exc:
        failure = str(exc)
    count_after = _common.counted(lambda: body.faces.count)
    after = _merge_material(body)
    kept = (before is not None and after is not None and
            all(abs(a - b) <= 1e-9 for a, b in zip(before, after)))
    if failure or returned is not True or count_after != count_before - 1 or not kept:
        reason = failure or f"native return={returned!r}, material_kept={kept}"
        return error(f"Face merge on '{name}' is unverified: {reason}; faces {count_before} -> "
                     f"{count_after}. The edit may remain on the body; inspect model_inspect before "
                     "further edits. No timeline feature is available to delete; recovery is manual.")
    handle = safe(lambda: body.entityToken)
    if not handle:
        return error(f"Faces merged on '{name}', but its body handle did not read. Inspect model_inspect.")
    return ok({"action": "merge_faces", "body": name, "handle": handle, "faces_before": count_before,
               "faces_after": count_after, "material_kept": True,
               "area_cm2": after[0], "volume_cm3": after[1],
               "bounds_cm": [list(after[2:5]), list(after[5:8])], "geometry_frame": "root",
               "note": "Merged the selected planar pair in place. No timeline feature is available "
                       "to delete; inspect model_inspect before further edits."})


def handler(action: str = "", body: str = "", destination: str = "", faces=None) -> dict:
    """See TOOL_DESCRIPTION."""
    chosen, err = _ACTION.resolve(action)
    if err:
        return error(err)
    if chosen == "merge_faces":
        if body or destination:
            return error("action='merge_faces' takes 'faces', not 'body' or 'destination'.")
        return _merge_faces(faces)
    if faces not in (None, "", []):
        return error(f"'faces' is unused for action='{chosen}'; remove it.")
    if chosen == "create_component" and destination not in (None, ""):
        return error("action='create_component' does not use 'destination'; omit it.")
    if chosen != "create_component" and destination in (None, ""):
        return error(f"action='{chosen}' requires explicit 'destination' (occurrence or root).")
    design, design_refusal = _common.require_design(none_only=True)
    if design_refusal is not None:
        return design_refusal
    selected, err = _BODY.resolve(body)
    if err:
        return error(err)
    family = _kind(selected)
    if family is None:
        return error("'body' did not resolve to a BRep or mesh body.")
    target = None
    if chosen != "create_component":
        target, err = _DESTINATION.resolve(destination)
        if err:
            return error(err)
    try:
        native = _native(selected)
        source_owner = native.parentComponent
        source_context = selected.assemblyContext
        if source_context is None and not _known_component_match(source_owner, design.rootComponent):
            placements = _placements(design, source_owner)
            if len(placements) > 1:
                paths = _paths(placements)
                return error(f"Native body '{native.name}' has {paths['count']} placements "
                             f"({paths['paths']}); pass an occurrence-qualified body or proxy handle.")
            if len(placements) == 1:
                source_context = placements[0]
    except Exception as exc:
        return error(f"Could not read selected body owner or placement: {exc}")
    try:
        before_shape = _shape(_context_body(native, source_context), family)
        source_before = _members(source_owner, family)
        source_identity = _common.native_identity(native)
        if not _contains_key(source_before, source_identity):
            return error(f"Source owner '{source_owner.name}' does not contain exactly one selected body.")
        dest_owner = _destination_owner(target) if target else None
        dest_before = _members(dest_owner, family) if dest_owner is not None else []
        source_witnesses = [member for member in source_before
                            if not _same_entity(_native(member), native)][:_WITNESS_CAP]
        witness_total = len(source_before) - 1
        witness_items = [(source_owner, _native(member), source_context,
                          _shape(_context_body(_native(member), source_context), family))
                         for member in source_witnesses]
        if dest_owner is not None and not _known_component_match(dest_owner, source_owner):
            witness_total += len(dest_before)
            dest_context = None if _destination_is_root(target, design.rootComponent) else target
            witness_items += [(dest_owner, _native(member), dest_context,
                               _shape(_context_body(_native(member), dest_context), family))
                              for member in dest_before[:_WITNESS_CAP]]
        children_before = _children(source_owner) if chosen == "create_component" else []
        if len({child.fullPathName for child in children_before}) != len(children_before):
            raise ValueError("Owner child placement path is ambiguous")
        source_frames = _placement_frames(_placements(design, source_owner))
        dest_frames = (_placement_frames(_placements(design, dest_owner))
                       if dest_owner is not None and not _known_component_match(dest_owner, source_owner)
                       else source_frames)
        if chosen == "copy" and family == "mesh" and len(dest_frames) > 1:
            return error(f"Mesh copy to '{target.fullPathName}' refused: component "
                         f"'{dest_owner.name}' has {len(dest_frames)} placements "
                         f"{list(dest_frames)[:_PATH_CAP]}"
                         f"{' (truncated)' if len(dest_frames) > _PATH_CAP else ''}. "
                         "Use a singly placed destination or an available BRep source.")
        design_mode = _inputs.current_design_type(design)
        if chosen == "create_component" and family == "mesh" and design_mode != "parametric":
            nonidentity = [path for path, frame in source_frames.items()
                           if any(abs(a - b) > _TOL_CM for a, b in zip(frame, _IDENTITY_FRAME))]
            if nonidentity:
                selected_path = source_context.fullPathName if source_context else "root"
                mode_label = ("Direct mesh" if design_mode == "direct"
                              else f"Mesh with design mode '{design_mode}'")
                return error(f"{mode_label} create_component for '{selected_path}' in component "
                             f"'{source_owner.name}' refused: {len(nonidentity)} of "
                             f"{len(source_frames)} source placements have nonidentity transforms "
                             f"{nonidentity[:_PATH_CAP]}"
                             f"{' (truncated)' if len(nonidentity) > _PATH_CAP else ''}. "
                             "Use a mesh in root or an identity-placed component, or use a "
                             "parametric design. An available BRep source also supports this action.")
        before_timeline = design.timeline.count if design_mode == "parametric" else None
    except Exception as exc:
        return error(f"Could not read scoped body state before action='{chosen}': {exc}")
    partial = {"action": chosen, "body_kind": family, "previous_owner_component": source_owner.name,
               "previous_path": safe(lambda: source_context.fullPathName),
               "source_membership_before": len(source_before),
               "destination_membership_before": len(dest_before) if dest_owner is not None else None}
    try:
        if chosen == "copy":
            result = selected.copyToComponent(target)
        elif chosen == "move":
            result = selected.moveToComponent(target)
        else:
            result = selected.createComponent()
    except Exception as exc:
        return error(f"Body {chosen} raised after the mutation was attempted: {exc}. Inspect "
                     "source and destination with design_get(include=['tree']). Partial state: "
                     + _partial_state(partial, source_owner, dest_owner, family))
    if result is None:
        return error(f"Body {chosen} returned no body. The operation may have partially landed; "
                     "inspect source and destination with design_get(include=['tree']). Partial state: "
                     + _partial_state(partial, source_owner, dest_owner, family))
    landed = _native(result)
    partial.update({"landed_body_name": safe(lambda: landed.name),
                    "landed_owner_component": safe(lambda: landed.parentComponent.name),
                    "landed_native_token": safe(lambda: landed.entityToken)})
    try:
        owner = landed.parentComponent
        expected_owner = dest_owner if dest_owner is not None else owner
        source_after = _members(source_owner, family)
        dest_after = _members(owner, family)
        partial.update({"source_membership_after": len(source_after),
                        "destination_membership_after": len(dest_after)})
        owner_is_source = _known_component_match(owner, source_owner)
        source_delta = (1 if chosen == "copy" else 0) if owner_is_source else (0 if chosen == "copy" else -1)
        membership = (_contains(dest_after, landed) and _known_component_match(owner, expected_owner)
                      and len(source_after) == len(source_before) + source_delta
                      and (len(dest_after) == len(dest_before) + 1 if chosen == "copy" or not owner_is_source
                           else len(dest_after) == 1 if chosen == "create_component"
                           else len(dest_after) == len(dest_before))
                      and (_contains_key(source_after, source_identity) if chosen == "copy"
                           else not _contains_key(source_after, source_identity)))
        if membership is not True:
            raise ValueError("Scoped source/destination membership does not match the requested action")
        if chosen == "create_component":
            children_after = _children(source_owner)
            if len({child.fullPathName for child in children_after}) != len(children_after):
                raise ValueError("Owner child placement path is ambiguous")
            new_children = [child for child in children_after
                            if not any(_same_occurrence(child, previous) for previous in children_before)]
            if (len(new_children) != 1 or len(children_after) != len(children_before) + 1
                    or not _known_component_match(new_children[0].component, owner)):
                raise ValueError("Returned owner is not one newly created direct child of the source owner")
        occurrence, occurrence_error = _result_occurrence(design, owner, source_context, chosen, target)
        if occurrence_error:
            raise ValueError(occurrence_error)
        scoped = _context_body(landed, occurrence)
        if scoped is None:
            raise ValueError("Result body has no proxy in the intended occurrence")
        handle = scoped.entityToken
        partial["landed_handle"] = handle
        partial["landed_full_path"] = occurrence.fullPathName if occurrence else None
        resolved, refusal = _BODY.resolve(handle)
        if (refusal or resolved is None or not _same_entity(_native(resolved), landed)
                or (resolved.assemblyContext is None) != (occurrence is None)
                or (occurrence is not None and (
                    not _same_occurrence(resolved.assemblyContext, occurrence)))):
            raise ValueError(f"Fresh result handle did not resolve in the intended context: {refusal}")
        result_shape = _shape(resolved, family)
        geometry_ok = _same_shape(before_shape, result_shape, family)
        if not geometry_ok:
            raise ValueError("Selected body world geometry changed or could not be verified")
        witness_unchanged = all(_contains(_members(witness_owner, family), witness_native)
                                and _same_shape(shape, _shape(_context_body(
                                    witness_native, witness_context), family), family)
                                for witness_owner, witness_native, witness_context, shape in witness_items)
        if not witness_unchanged:
            raise ValueError("A sampled sibling or destination witness changed")
        source_placements = _placements(design, source_owner)
        dest_placements = _placements(design, owner)
        placement_unchanged = (_same_frames(source_frames, _placement_frames(source_placements))
                               and (dest_owner is None or _same_frames(
                                   dest_frames, _placement_frames(_placements(design, dest_owner)))))
        if not placement_unchanged:
            raise ValueError("A source or destination occurrence placement changed")
        timeline_health = None
        if design_mode == "parametric":
            after_timeline = design.timeline.count
            row = design.timeline.item(after_timeline - 1) if after_timeline > before_timeline else None
            timeline_health = row is not None and row.healthState == 0
            if not timeline_health:
                raise ValueError("No healthy organization feature appeared in the timeline")
        payload = {**partial, "handle": handle, "body_name": landed.name,
                   "owner_component": owner.name, "full_path": occurrence.fullPathName if occurrence else None,
                   "at_root": occurrence is None,
                   "occurrence_handle": occurrence.entityToken if occurrence else None,
                   "source_membership_after": len(source_after),
                   "destination_membership_after": len(dest_after),
                   "source_retained": chosen == "copy",
                   "selected_world_sample_preserved": True, "geometry_check": result_shape["method"],
                   "geometry_sample_truncated": before_shape["sample_truncated"] or result_shape["sample_truncated"],
                   "witness_check": {"checked": len(witness_items), "unchanged": True,
                                     "truncated": witness_total > len(witness_items)},
                   "definition_effect": {"source_placements": _paths(source_placements),
                                         "destination_placements": _paths(dest_placements),
                                         "existing_placements_unchanged": True},
                   "timeline_health": {"checked": timeline_health is not None,
                                       "healthy": timeline_health},
                   "note": "Body ownership changes the component definition in every placement. "
                           "Use the fresh handle promptly; old move/create handles may be stale."}
        return ok(payload)
    except Exception as exc:
        return error(f"Body {chosen} returned a body but its effect is incomplete or unknown: {exc}. "
                     "Inspect source and destination with design_get(include=['tree']). Partial state: "
                     + _partial_state(partial, source_owner, dest_owner, family))


TOOL_DESCRIPTION = ("Copy, move or rehome a body; merge two coplanar faces in direct mode.\n"
                    + _outputs.produces_block(RETURNS))

body_tool = (Tool.create_simple(name="model_edit_body", description=TOOL_DESCRIPTION)
             .add_input_property(*_ACTION.as_property())
             .add_input_property(*_BODY.as_property(brief=True))
             .add_input_property(*_DESTINATION.as_property())
             .add_input_property(*_FACES.as_property(brief=True))
             .strict_schema())
body_item = Item.create_tool_item(tool=body_tool, write="write", handler=handler,
                                  run_on_main_thread=True, verification=Verification(
                                      kind="inline", rung="geometry",
                                      evidence_test="tests/unit/test_model_edit_body.py"
                                      "::test_move_reports_replacement_identity"))


def register_tool():
    register(body_item)
