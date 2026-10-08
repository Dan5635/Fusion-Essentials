# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: split a body into pieces, split its faces with a cutter, or split a
solid's faces along its silhouette for a view direction (SilhouetteSplitFeatures, faces only).
SilhouetteSplitFeature.viewDirection is never read: at the end marker the read fails the command.
"""

import math

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe, target_component
from . import _common
from . import _assert
from . import _geom
from . import _inputs
from . import _outputs


RETURNS = [
    _outputs.ReturnsName("feature", of="feature", consumers=["design_delete_feature"],
                         absent_when="no_timeline_feature"),
    _outputs.ReturnsValue("result_count",
                          "split=body: the number of resulting bodies; split=face/silhouette: the "
                          "net face-count increase"),
]

_SPLIT = _inputs.Choice("split", ["body", "face", "silhouette", "along_vector"], default="body")
_TARGET = _inputs.BodyRef("target", kind="brep", description="A body 'handle' or name.")
_SOLID = _inputs.BodyRef("target", kind="solid")
_VIEW = _inputs.AxisRef("view_direction", entity_only=True, description="x/y/z or a construction axis.")
_FACES = _inputs.GeometryHandleList("faces", require="face")
_SPLIT_LINE = _inputs.SketchLineRef("split_line", required=False)
# The cutter, supplied ONE of two ways: a plane (alias/name/planar-face handle) OR a body/surface.
_PLANE = _inputs.PlaneRef("split_plane", description="xy/xz/yz, a construction plane or a planar face handle.")
_TOOLBODY = _inputs.BodyRef("split_tool_body", kind="brep")

app = adsk.core.Application.get()


def _resolve_cutter(split_plane, split_tool_body):
    """Resolve the single splitting tool from EXACTLY ONE of split_plane / split_tool_body. Returns
    (entity, error_string). Giving both, or neither, is a guarded error (the cutter is one entity)."""
    has_plane = isinstance(split_plane, str) and split_plane.strip()
    has_body = isinstance(split_tool_body, str) and split_tool_body.strip()
    if has_plane and has_body:
        return None, ("Give the cutter ONE way: 'split_plane' OR 'split_tool_body', not both.")
    if not has_plane and not has_body:
        return None, ("No cutter. Pass 'split_plane' (a plane) or 'split_tool_body' (a body/surface) "
                      "to split with.")
    if has_plane:
        return _PLANE.resolve(split_plane)
    return _TOOLBODY.resolve(split_tool_body)


def _health_error(design, feature):
    """An error result if the feature computed with a health ERROR, else None."""
    if safe(lambda: feature.healthState) == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
        msg = safe(lambda: feature.errorOrWarningMessage) or "no detail"
        return error(f"Split feature was created but failed to compute: {msg}. The cutter may not "
                     "fully cross the target - try extend_tool=true or a larger cutter. "
                     + _common.failed_effect_remedy(design, feature))
    return None


def _split_body(design, comp, target, cutter, extend_tool):
    """Split a solid body with the cutter, reporting the resulting body count honestly."""
    body, berr = _TARGET.resolve(target)
    if berr:
        return error(berr)
    if body is None:
        return error("'target' is required for split=body (the body to split).")
    # Captured BEFORE the mutation: the census host, counted again afterwards rather than
    # re-derived, and the target's name, which a post-mutation proxy can stop answering.
    host = _common.census_host(body, comp)
    before_count = _common.body_count(host)
    body_name = safe(lambda: body.name)
    try:
        si = comp.features.splitBodyFeatures.createInput(body, cutter, bool(extend_tool))
        feature = comp.features.splitBodyFeatures.add(si)
    except Exception as e:
        return error(f"Split body failed: {e}. (The cutter must fully cross the body - try "
                     "extend_tool=true, or a larger cutter/plane.)")
    # splitBodyFeatures.add returns None in a DIRECT design while the split lands; with no feature
    # to read result bodies off, the component's body census is the verdict.
    direct_no_feature = _common.direct_feature_absence(design, feature)
    if not feature and not direct_no_feature:
        return error(_common.no_feature_error(design, "Split body"))
    herr = _health_error(design, feature)
    if herr:
        return herr

    if direct_no_feature:
        after_count = _common.body_count(host)
        if before_count is None or after_count is None:
            return error("Split body ran in a DIRECT design, which returns no feature object, and "
                         "the component's body count could not be read back - so whether the body "
                         "was divided is UNVERIFIED. Check with design_get(include=['tree']).")
        # One body divided into N pieces raises the count by N-1, in the TARGET's own component.
        rc = after_count - before_count + 1
        names = None                      # the pieces were COUNTED, never named - see the payload
    else:
        fb = safe(lambda: feature.bodies)
        rc = safe(lambda: fb.count, 0) if fb else 0
        names = [safe(lambda b=b: b.name) for b in _common.iter_collection(fb)]
    # A split that yields a single body did not divide anything.
    if rc < 2:
        return error(f"Split produced {rc} body - the cutter did not divide "
                     f"'{body_name}'. It must fully intersect the body; try "
                     "extend_tool=true or a cutter that crosses it. "
                     + _common.failed_effect_remedy(design, feature))
    payload = {
        "split": "body",
        "target": body_name,
        "result_count": rc,
        "note": "Body split into pieces. Pair with design_get(include=['tree']) / view_screenshot.",
    }
    if direct_no_feature:
        payload["no_timeline_feature"] = True
        payload["note"] += (" " + _common.DIRECT_FEATURE_NOTE + " The pieces were COUNTED from the "
                            "component's body census, not named - list them with "
                            "design_get(include=['tree']).")
    else:
        payload["feature"] = safe(lambda: feature.name)
        payload["result_bodies"] = names
    return ok(payload)


def _split_face(design, comp, faces, cutter, extend_tool):
    """Split the given faces with the cutter, reporting the net face-count increase honestly."""
    face_ents, ferr = _FACES.resolve(faces)
    if ferr:
        return error(ferr)
    if not face_ents:
        return error("'faces' is required for split=face (the faces to split).")

    # Dedupe by entityToken, NOT by identity: face.body hands back a FRESH PROXY on every read, so
    # an id()-keyed dedupe would keep one body once per face and sum its change that many times.
    bodies = _geom.owning_bodies(face_ents)
    before = _geom.face_counts(bodies)
    coll = adsk.core.ObjectCollection.create()
    for f in face_ents:
        coll.add(f)
    try:
        si = comp.features.splitFaceFeatures.createInput(coll, cutter, bool(extend_tool))
        feature = comp.features.splitFaceFeatures.add(si)
    except Exception as e:
        return error(f"Split face failed: {e}. (The cutter must cross the faces - try "
                     "extend_tool=true or a larger cutter.)")
    # A DIRECT design can return no feature while the split lands; the before/after face census on
    # the owning bodies needs none. In parametric a None feature stays an error.
    direct_no_feature = _common.direct_feature_absence(design, feature)
    if not feature and not direct_no_feature:
        return error(_common.no_feature_error(design, "Split face"))
    herr = _health_error(design, feature)
    if herr:
        return herr

    # `bodies` was resolved BEFORE the mutation and is counted again here - the same objects.
    delta, readable = _geom.face_count_delta(bodies, before)
    if direct_no_feature:
        if not readable:
            return error("Split face ran in a DIRECT design, which returns no feature object, and "
                         "the owning bodies' face count could not be read back - so whether the "
                         "faces were split is UNVERIFIED. Check with model_inspect / find_geometry.")
        created = None
        no_op = delta <= 0
    else:
        ff = safe(lambda: feature.faces)
        created = safe(lambda: ff.count, 0) if ff else 0
        if not readable:
            delta = created
        no_op = delta <= 0 and created == 0
    if no_op:
        return error(f"Split produced no new faces - the cutter did not cross the {len(face_ents)} "
                     "target face(s). It must intersect them; try extend_tool=true or a larger "
                     "cutter. " + _common.failed_effect_remedy(design, feature))
    payload = {
        "split": "face",
        "faces_targeted": len(face_ents),
        "result_count": delta,
        "note": "Faces split; result_count is the net face-count increase. Pair with view_screenshot.",
    }
    if direct_no_feature:
        payload["no_timeline_feature"] = True
        payload["note"] += (" " + _common.DIRECT_FEATURE_NOTE + " result_count is the measured "
                            "before/after face count on the owning bodies.")
    else:
        payload["feature"] = safe(lambda: feature.name)
        payload["faces_created"] = created
    return ok(payload)


def _split_along_vector(design, comp, faces, split_line, view_direction, extend_tool):
    """Split faces by a sketch line projected along a typed linear direction entity."""
    face_ents, ferr = _FACES.resolve(faces)
    if ferr:
        return error(ferr)
    if not face_ents:
        return error("'faces' is required for split='along_vector' (the faces to split).")
    line, lerr = _SPLIT_LINE.resolve(split_line)
    if lerr:
        return error(lerr)
    tagged, derr = _VIEW.resolve(view_direction, comp)
    if derr:
        return error(derr)
    if tagged[0] == "world":
        axis_key = next((key for key, vector in (("x", (1, 0, 0)), ("y", (0, 1, 0)),
                                                  ("z", (0, 0, 1)))
                         if tuple(tagged[1]) == vector), None)
        direction = _inputs.world_construction_axis(comp, axis_key) if axis_key else None
        if direction is None:
            return error("'view_direction' world axis could not be resolved in the active component.")
    else:
        direction = tagged[1]

    bodies = _geom.owning_bodies(face_ents)
    before = _geom.face_counts(bodies)
    coll = adsk.core.ObjectCollection.create()
    for face in face_ents:
        coll.add(face)
    try:
        features = comp.features.splitFaceFeatures
        split_input = features.createInput(coll, line, bool(extend_tool))
        if split_input is None:
            return error("Fusion refused the along-vector split input; no split was attempted.")
        set_result = split_input.setAlongVectorSplitType(direction)
        if set_result is not True:
            return error("Fusion refused split='along_vector' because its direction setter did not "
                         "return true; no split was attempted.")
        feature = features.add(split_input)
        feature_name = safe(lambda: feature.name) if feature else None
        feature_token = safe(lambda: feature.entityToken) if feature else None
        feature_identity = feature_name or feature_token
    except Exception as exc:
        return error(f"Split along vector failed: {exc}. Check that the line and direction cross the target faces.")
    direct_no_feature = _common.direct_feature_absence(design, feature)
    if not feature and not direct_no_feature:
        return error(_common.no_feature_error(design, "Along-vector split"))
    readback_unverified = []
    if feature:
        try:
            retained_definition, marker_err = _common.rolled_to(
                design, feature,
                lambda: (feature.splitType, feature.directionEntity),
                f"along-vector split feature '{feature_identity}'")
        except Exception as exc:
            return error(f"Split feature '{feature_identity}' was created, but its retained split "
                         f"definition could not be read: {exc}. Inspect it with design_get and "
                         "remove it with design_delete_feature.")
        if marker_err:
            return error(f"Split feature '{feature_identity}' was created, but the timeline "
                         f"marker could not be restored after reading its retained definition: "
                         f"{marker_err}. Inspect it with design_get and remove it with "
                         "design_delete_feature.")
        if retained_definition is None:
            return error(f"Split feature '{feature_identity}' was created, but its timeline row "
                         "could not be read. Inspect it with design_get and remove it with "
                         "design_delete_feature.")
        actual_split_type, actual_direction = retained_definition
        expected_split_type = safe(lambda: adsk.fusion.SplitFaceSplitTypes.alongVectorSplitType)
        if actual_split_type is None or expected_split_type is None:
            readback_unverified.append("split_type")
        elif actual_split_type != expected_split_type:
            return error(f"Split feature '{feature_identity}' did not retain the along-vector split type; "
                         "inspect it with design_get and remove it with design_delete_feature.")
        expected_identity = _common.native_identity(direction)
        actual_identity = _common.native_identity(actual_direction) if actual_direction is not None else None
        if expected_identity is None or actual_identity is None:
            readback_unverified.append("split_direction")
        elif actual_identity != expected_identity:
            return error(f"Split feature '{feature_identity}' did not retain the selected view_direction; "
                         "inspect it with design_get and remove it with design_delete_feature.")
    else:
        readback_unverified.extend(("split_type", "split_direction"))
    herr = _health_error(design, feature)
    if herr:
        return herr
    delta, readable = _geom.face_count_delta(bodies, before)
    if not readable:
        detail = (f"Feature '{feature_identity}' was created, but " if feature_identity else "")
        remedy = (" Retire it with design_delete_feature." if feature_identity else "")
        return error(detail + "Split along vector ran but the owning bodies' face count could not be "
                     "read back; whether the faces were split is UNVERIFIED. Check with model_inspect / "
                     "find_geometry." + remedy)
    if delta <= 0:
        return error("Split along vector produced no new faces; the projected sketch line did not "
                     "split the target. Check its position and view_direction. "
                     + _common.failed_effect_remedy(design, feature))
    result = {"split": "along_vector", "faces_targeted": len(face_ents), "result_count": delta,
              "note": "Faces split along the supplied direction; verify the partition with find_geometry."}
    if readback_unverified:
        result["unverified"] = readback_unverified
    if direct_no_feature:
        result["no_timeline_feature"] = True
        result["note"] += " " + _common.DIRECT_FEATURE_NOTE
    else:
        result["feature"] = feature_identity
    return ok(result)


def _line_ends(body):
    """Each straight edge of `body` as a sorted pair of mm end points, or None when one does not read."""
    edges = safe(lambda: body.edges)
    count = _common.counted(lambda: edges.count)
    if count is None:
        return None
    mm, ends = _common.CM_TO_UNIT["mm"], set()
    for i in range(count):
        edge = safe(lambda i=i: edges.item(i))
        kind = safe(lambda: edge.geometry.curveType)
        if kind is None:
            return None
        if kind != adsk.core.Curve3DTypes.Line3DCurveType:
            continue
        pair = [_common.ptxyz(safe(lambda end=end: getattr(edge, end).geometry), mm)
                for end in ("startVertex", "endVertex")]
        if None in pair:
            return None
        ends.add(tuple(sorted((p["x"], p["y"], p["z"]) for p in pair)))
    return ends


def _silhouette_axis(raw, root):
    """(a root-component construction axis for `raw`, error)."""
    key = raw.strip().lower() if isinstance(raw, str) else raw
    if key in ("x", "y", "z"):
        axis = _inputs.world_construction_axis(root, key)
        return (axis, None) if axis is not None else (None, "The root component's origin axes did not read.")
    tagged, err = _VIEW.resolve(raw)
    if err or tagged is None:
        return None, err or "split='silhouette' needs 'view_direction' (x/y/z or a construction axis)."
    axis = tagged[1]
    if not isinstance(axis, adsk.fusion.ConstructionAxis):
        return None, (f"'view_direction' resolved to a {type(axis).__name__}; split='silhouette' "
                      "takes a construction axis only: x/y/z or an axis name/handle.")
    if (safe(lambda: axis.assemblyContext) is not None
            or _common.same_component(_inputs.entity_component(axis), root) is not True):
        return None, "'view_direction' must be a construction axis of the root component."
    return axis, None


def _split_silhouette(design, target, view_direction):
    """Split a root solid's faces along its silhouette for a construction-axis view direction."""
    body, berr = _SOLID.resolve(target)
    if berr or body is None:
        return error(berr or "split='silhouette' needs 'target' (the solid to split).")
    root = safe(lambda: design.rootComponent)
    name = safe(lambda: body.name)
    if (safe(lambda: body.assemblyContext) is not None
            or _common.same_component(safe(lambda: body.parentComponent), root) is not True):
        return error(f"'target' '{name}' is not a root-component body; split='silhouette' takes a "
                     "solid in the root component.")
    axis, aerr = _silhouette_axis(view_direction, root)
    if aerr:
        return error(aerr)
    faces_before = _common.counted(lambda: body.faces.count)
    volume_before = _geom.signed_volume(body)
    lines_before = _line_ends(body)
    if (faces_before is None or volume_before is None or not math.isfinite(volume_before)
            or lines_before is None):
        return error(f"The faces, volume or edges of '{name}' did not read; nothing was split.")
    try:
        features = root.features.silhouetteSplitFeatures
        feature = features.add(features.createInput(
            axis, body, adsk.fusion.SilhouetteSplitOperations.SilhouetteSplitFacesOnlyOperation))
    except Exception as e:
        return error(f"Silhouette split of '{name}' failed: {e}.")
    if not feature:
        return error(_common.no_feature_error(design, "Silhouette split"))
    label = safe(lambda: feature.name)
    remedy = _common.failed_effect_remedy(design, feature)
    if safe(lambda: feature.healthState) == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
        return error(f"Silhouette split '{label}' was created but failed to compute: "
                     f"{safe(lambda: feature.errorOrWarningMessage) or 'no detail'}. {remedy}")
    faces_after = _common.counted(lambda: body.faces.count)
    volume_after = _geom.signed_volume(body)
    if faces_after is None or volume_after is None or not math.isfinite(volume_after):
        return error(f"Silhouette split '{label}' was created, but the faces or volume of '{name}' "
                     f"did not re-read, so the split is unverified. {remedy}")
    if faces_after <= faces_before:
        return error(f"Silhouette split '{label}' was created, but '{name}' reads {faces_after} "
                     f"faces (was {faces_before}): no face was split. {remedy}")
    change = volume_after - volume_before
    if abs(change) > _common.NO_VOLUME_CHANGE_CM3:
        return error(f"Silhouette split '{label}' changed the volume of '{name}' by {change:.3g} "
                     f"cm3; a faces-only split keeps it. {remedy}")
    lines_after = _line_ends(body)
    if lines_after is None:
        return error(f"Silhouette split '{label}' was created, but its straight edges did not "
                     f"re-read, so the boundary positions are unverified. {remedy}")
    return ok({"split": "silhouette", "feature": label, "target": name,
               "requested_view_direction": view_direction, "faces_before": faces_before,
               "faces_after": faces_after, "result_count": faces_after - faces_before,
               "volume_change_cm3": change,
               "new_line_edges_mm": [[list(a), list(b)] for a, b in sorted(lines_after - lines_before)],
               "note": "Faces split along the silhouette; volume kept. new_line_edges_mm are the "
                       "straight edges the split added (world mm). Retire it with design_delete_feature."})


def handler(split: str = "body", target: str = "", faces=None, split_plane: str = "",
            split_tool_body: str = "", extend_tool: bool = True, view_direction: str = "",
            split_line: str = "") -> dict:
    """See TOOL_DESCRIPTION."""
    kind, kerr = _SPLIT.resolve(split)
    if kerr:
        return error(kerr)

    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")
    comp = target_component(design)
    if kind == "along_vector":
        if target or split_plane or split_tool_body:
            return error("split='along_vector' takes 'faces', 'split_line' and 'view_direction', "
                         "not 'target', 'split_plane' or 'split_tool_body'.")
        if not view_direction:
            return error("split='along_vector' needs 'view_direction' (a world axis, construction "
                         "axis, straight edge or sketch line).")
        if not split_line:
            return error("split='along_vector' needs 'split_line' as an exact '<sketch>/line:<index>' "
                         "from sketch_get(include_entities=true).")
        return _split_along_vector(design, comp, faces, split_line, view_direction, extend_tool)
    if kind == "silhouette":
        if faces not in (None, "", []) or split_plane or split_tool_body or split_line:
            return error("split='silhouette' takes 'target' and 'view_direction', not 'faces', "
                         "'split_plane' or 'split_tool_body'.")
        return _split_silhouette(design, target, view_direction)
    if view_direction:
        return error(f"'view_direction' is used only by split='silhouette' (got split='{kind}').")
    if split_line:
        return error(f"'split_line' is used only by split='along_vector' (got split='{kind}').")

    cutter, cerr = _resolve_cutter(split_plane, split_tool_body)
    if cerr:
        return error(cerr)

    if kind == "body":
        return _split_body(design, comp, target, cutter, extend_tool)
    return _split_face(design, comp, faces, cutter, extend_tool)


TOOL_DESCRIPTION = (
    "Split a body, or its faces by a cutter or silhouette."
)

FULL_DESCRIPTION = TOOL_DESCRIPTION + "\n" + _outputs.produces_block(RETURNS)

split_tool = (
    Tool.create_simple(name="model_split", description=FULL_DESCRIPTION)
    .add_input_property(*_SPLIT.as_property())
    .add_input_property(_TARGET.name, _TARGET.schema(brief=True))
    .add_input_property(_FACES.name, _FACES.schema())
    .add_input_property(_PLANE.name, _PLANE.schema(brief=True))
    .add_input_property(_TOOLBODY.name, _TOOLBODY.schema(brief=True))
    .add_input_property("extend_tool", {"type": "boolean"})
    .add_input_property("view_direction", {"type": "string",
            "description": "Silhouette/along_vector direction: x/y/z, axis name/handle or straight-edge/line handle."})
    .add_input_property("split_line", {"type": "string",
            "description": "For split=along_vector. An exact '<sketch>/line:<index>' from sketch_get(include_entities=true)."})
    .strict_schema()
)
split_item = Item.create_tool_item(tool=split_tool, write="write", handler=handler, run_on_main_thread=True,
                                   postconditions=[_assert.FeatureHealthy()],
                                   verification=Verification(
                                       kind="inline", rung="geometry",
                                       evidence_test="tests/unit/test_model_split.py::TestSplitFace"
                                       "::test_no_new_faces_is_error"))


def register_tool():
    register(split_item)
