# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Create a plain Rib/Web with a verified material gain in its explicit target."""

import math

import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _common, _inputs, _outputs, _rib_common

_KIND = _inputs.Choice("kind", ("rib", "web"), required=True)
_CURVES = _inputs.GeometryHandleList("curves", require="sketch_curve", json_array=True, required=True,
    description="Ordered sketch curve handles from sketch_get(include_entities=true).")
_BODY = _inputs.BodyRef("target_body", kind="solid", required=True, description="Solid body handle.")
RETURNS = [_outputs.ReturnsValue("feature", "the created feature name"),
           _outputs.ReturnsValue("kind", "the feature kind"),
           _outputs.ReturnsValue("result_bodies", "the changed bodies"),
           _outputs.ReturnsValue("geometry_before", "the target shape before creation"),
           _outputs.ReturnsValue("geometry_after", "the target shape after creation")]


def handler(kind: str = "", curves=None, target_body: str = "", thickness=None, depth=None,
            symmetric: bool = True, flip: bool = False, extend: bool = False,
            component: str = "", name: str = "", units: str = "mm") -> dict:
    """Return the retained feature and target shape, or an explicit creation failure."""
    design = _common.design()
    if design is None:
        return _common.error("No active design. Create or open a design first.")
    values, refusal = _inputs.resolve_inputs([_KIND, _CURVES, _inputs.UNITS],
                                            {"kind": kind, "curves": curves, "units": units})
    if refusal:
        return refusal
    if any(type(value) is not bool for value in (symmetric, flip, extend)):
        return _common.error("symmetric, flip and extend must be booleans.")
    if values["kind"] == "rib" and extend:
        return _common.error("extend=true is Web only; omit it for a rib.")
    scope = None
    if component:
        scope, reason = _inputs._body_scope(design, component, "component")
        if reason:
            return _common.error(reason)
    body, reason = _BODY.resolve(target_body, scope=scope)
    if reason:
        return _common.error(reason)
    target = _common._native_of(body)
    host = _common.safe(lambda: target.parentComponent)
    if host is None or _common.same_component(
            _common.safe(lambda: host.parentDesign.rootComponent), design.rootComponent) is not True:
        return _common.error("target_body must be a local solid in this design; linked source geometry cannot be edited.")
    if scope is not None:
        scoped_host = _common.safe(lambda: scope[0].component) or scope[0]
        if _common.same_component(scoped_host, host) is not True:
            return _common.error("component does not own target_body; pass the body's owning component or omit component.")
    guides = [_common._native_of(curve) for curve in values["curves"]]
    if len(guides) > 64:
        return _common.error("curves exceeds 64 handles; split the feature into smaller chains.")
    if any(_common.same_component(_inputs.entity_component(curve), host) is not True for curve in guides):
        return _common.error("curves must belong to target_body's component; create the guide sketch there.")
    keys = [_common.native_identity(curve) for curve in guides]
    if any(key is None for key in keys) or len(set(keys)) != len(keys):
        return _common.error("curves repeats a guide or its identity did not read; reacquire distinct sketch curve handles.")
    factor = _common.scale(values["units"])
    thickness_input, thickness_cm, reason = _inputs.length_value_input(thickness, factor, design, "thickness")
    if reason:
        return _common.error(reason)
    if thickness_cm is None or not math.isfinite(thickness_cm) or thickness_cm <= 0 or isinstance(thickness, bool):
        return _common.error(f"thickness {thickness!a} needs a finite positive length.")
    depth_input, depth_cm = None, None
    if depth is not None:
        depth_input, depth_cm, reason = _inputs.length_value_input(depth, factor, design, "depth")
        if reason:
            return _common.error(reason)
        if depth_cm is None or not math.isfinite(depth_cm) or depth_cm <= 0 or isinstance(depth, bool):
            return _common.error(f"depth {depth!a} needs a finite positive length; omit it for to-next.")
    before = _rib_common.body_census(host)
    target_key = _common.native_identity(target)
    if before is None or target_key not in before:
        return _common.error("Target owner body shapes did not completely read (cap 200); no feature created.")
    collection = host.features.ribFeatures if values["kind"] == "rib" else host.features.webFeatures
    feature = None
    try:
        inp = collection.createInput(guides, thickness_input, target)
        if inp is None:
            raise RuntimeError("feature input was not returned")
        inp.isSymmetric, inp.isFlipped = symmetric, flip
        if values["kind"] == "web":
            inp.isExtended = extend
        if (_common.safe(lambda: inp.isSymmetric) is not symmetric
                or _common.safe(lambda: inp.isFlipped) is not flip
                or values["kind"] == "web" and _common.safe(lambda: inp.isExtended) is not extend):
            raise RuntimeError("input options did not read back")
        if _common.native_identity(_common.safe(lambda: inp.targetBody)) != target_key:
            raise RuntimeError("input target body did not read back")
        kept_curves, read_error = _common.read_optional(lambda: list(inp.curves))
        if read_error or [_common.native_identity(curve) for curve in kept_curves] != keys:
            raise RuntimeError("input guide order did not read back")
        accepted = inp.setToNextExtent() if depth_input is None else inp.setDistanceExtent(depth_input)
        if accepted is not True:
            raise RuntimeError("extent setter returned false")
        feature = collection.add(inp)
        if feature is None:
            raise RuntimeError("feature was not returned")
        actual_name, reason = _common.apply_rename(feature, name)
        if reason:
            raise RuntimeError(reason)
    except Exception as exc:
        return _common.error(f"{kind} creation failed: {exc}. Retained feature: "
                             f"{_common.safe(lambda: feature.name)!a}; read design_get and model_inspect before retrying.")
    after = _rib_common.body_census(host)
    state = _common.safe(lambda: feature.healthState)
    healthy = state == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
    owner_kept = _common.same_component(_common.safe(lambda: feature.parentComponent), host) is True
    read_thickness = _common.measured(lambda: feature.thickness.value, places=12)
    read_depth = _common.measured(lambda: feature.depth.value, places=12) if depth_input is not None else None
    dimensions_kept = (read_thickness is not None and math.isclose(read_thickness, thickness_cm, abs_tol=1e-9)
                       and (depth_input is None or read_depth is not None
                            and math.isclose(read_depth, depth_cm, abs_tol=1e-9)))
    if (after is None or set(after) != set(before) or target_key not in after
            or after[target_key]["volume_cm3"] <= before[target_key]["volume_cm3"] + 1e-9
            or any(after[key] != row for key, row in before.items() if key != target_key)
            or not healthy or not dimensions_kept or not owner_kept):
        return _common.error(f"Retained {kind} '{actual_name}' did not verify healthy added material in only target_body. "
                             f"Health: {state!a}; message: {_common.safe(lambda: feature.errorOrWarningMessage)!a}. "
                             "Read model_inspect; design_delete_feature can remove the retained feature.")
    return _common.ok({"feature": actual_name, "kind": values["kind"],
                       "result_bodies": [_common.safe(lambda: target.name)],
                       "geometry_before": before[target_key], "geometry_after": after[target_key],
                       "note": "Geometry uses component-local cm units. Every occurrence of this component shows the edit."})


TOOL_DESCRIPTION = ("Create a rib or web from ordered sketch curves into an explicit solid. "
                    "Check added material with model_inspect; design_get definition reads the feature.")
tool = (Tool.create_simple(name="model_create_rib", description=TOOL_DESCRIPTION + "\n" + _outputs.produces_block(RETURNS))
        .add_input_property(*_KIND.as_property()).add_required_input("kind")
        .add_input_property(*_CURVES.as_property()).add_required_input("curves")
        .add_input_property(*_BODY.as_property()).add_required_input("target_body")
        .add_input_property("thickness", {"type": ["number", "string"]}).add_required_input("thickness")
        .add_input_property("depth", {"type": ["number", "string"], "description": "Omit for to-next extent."})
        .add_input_property("symmetric", {"type": "boolean"})
        .add_input_property("flip", {"type": "boolean"})
        .add_input_property("extend", {"type": "boolean", "description": "Web only: extend curves to walls."})
        .add_input_property("component", {"type": "string", "description": "Local occurrence handle/path."})
        .add_input_property("name", {"type": "string"})
        .add_input_property(*_inputs.UNITS.as_property()).strict_schema())
item = Item.create_tool_item(tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(kind="effect", rung="geometry",
        evidence_test="tests/unit/test_model_create_rib.py::test_returned_feature_without_material_gain_is_error"))


def register_tool():
    register(item)
