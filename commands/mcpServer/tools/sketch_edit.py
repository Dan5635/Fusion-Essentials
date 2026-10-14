# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: rename ONE sketch, set its bulb, or move it to a plane; each effect is re-read."""

import math

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common
from . import _edit_feature_common
from . import _form_common
from . import _geom
from . import _inputs
from . import _sketch_detail

app = adsk.core.Application.get()

_PLANE = _inputs.PlaneRef("plane")
_EDITS = ("new_name", "visible", "plane")
_LATER_ROWS_CAP = 50




def _resolves(design, name, component):
    """Whether `name` reaches a sketch in this scope - a shared name counts, it is held."""
    found, refusal = _sketch_detail.scoped_sketch(design, name, component)
    return found is not None or bool(refusal)


def _next_call(design, sketch, name, component):
    """({sketch_name, component?} that resolves to one sketch, or None; why none does)."""
    scopes = [(component or "").strip()]
    owner = safe(lambda: sketch.parentComponent.name)
    if not scopes[0] and owner:
        scopes.append(owner)
    refusal = None
    for scope in scopes:
        found, refusal = _sketch_detail.scoped_sketch(design, name, scope)
        if found is not None:
            return {"sketch_name": name, **({"component": scope} if scope else {})}, None
    return None, refusal or f"no sketch named '{name}' was found on re-read"


def _rename(design, sketch, component, new_name):
    """Assign the name and publish the one that reads back."""
    want = new_name.strip() if isinstance(new_name, str) else ""
    if not want:
        return error(f"'new_name' must be a non-empty name; got {new_name!r}.")
    previous = safe(lambda: sketch.name)
    if previous == want:
        return error(f"Sketch '{previous}' already has that name; nothing was changed.")
    try:
        sketch.name = want
    except Exception as e:
        return error(f"Could not rename sketch '{previous}' to '{want}': {e}")
    landed = safe(lambda: sketch.name)
    if landed is None:
        return error(f"Sketch '{previous}' was assigned the name '{want}' but its name did not "
                     "read back, so the rename is unverified. Read it with sketch_get.")
    if landed == previous:
        return error(f"The rename did not take - the sketch still reads '{previous}' after "
                     f"'{want}' was assigned.")
    address, why = _next_call(design, sketch, landed, component)
    note = f"Renamed '{previous}' -> '{landed}'."
    if landed != want:
        note += f" Fusion adopted '{landed}', not the requested '{want}'; use the adopted name."
    out = {"action": "new_name", "previous_name": previous, "requested_name": want,
           "name": landed, "adopted_differs": landed != want,
           "old_name_resolves": _resolves(design, previous, component), "address": address}
    if address is None:
        out["unread"] = {"address": why}
        note += " No unique address was found for it; see unread.address."
    out["note"] = note
    return ok(out)


def _set_visible(sketch, visible):
    """Set the browser bulb and publish it beside the effective visibility."""
    if not isinstance(visible, bool):
        return error(f"'visible' must be true or false; got {visible!r}.")
    name = safe(lambda: sketch.name)
    bulb_before, _why = _common.read_optional(lambda: sketch.isLightBulbOn)
    shown_before, _why = _common.read_optional(lambda: sketch.isVisible)
    out = {"action": "visible", "sketch": name, "requested": visible,
           "bulb_before": bulb_before, "effective_visible_before": shown_before}
    if bulb_before is visible:
        out.update(changed=False, bulb_after=bulb_before, effective_visible_after=shown_before,
                   note=f"The bulb of sketch '{name}' already reads {visible}; nothing was "
                        "written.")
        return ok(out)
    try:
        sketch.isLightBulbOn = visible
    except Exception as e:
        return error(f"Could not set the bulb of sketch '{name}' to {visible}: {e}")
    bulb_after, bulb_why = _common.read_optional(lambda: sketch.isLightBulbOn)
    shown_after, shown_why = _common.read_optional(lambda: sketch.isVisible)
    if bulb_after is None:
        return error(f"The bulb of sketch '{name}' was assigned {visible} but did not read back "
                     f"({bulb_why}), so the change is unverified. Read it with sketch_get.")
    if bulb_after is not visible:
        return error(f"The bulb did not take - sketch '{name}' still reads isLightBulbOn="
                     f"{bulb_after} after {visible} was assigned.")
    note = f"Bulb {bulb_before} -> {bulb_after}."
    if shown_after is None:
        out["unread"] = {"effective_visible_after": shown_why}
        note += " Effective visibility did not read back."
    elif shown_after is not visible:
        note += (f" Effective visibility (isVisible) still reads {shown_after}: the bulb changed "
                 "and what is shown did not.")
    out.update(changed=True, bulb_after=bulb_after, effective_visible_after=shown_after,
               note=note)
    return ok(out)


def _placement(sketch):
    """(origin cm, unit normal) of the sketch's own plane in its component's space, or None."""
    origin = _geom._coords(safe(lambda: sketch.origin))
    x = _geom.unit_vector(safe(lambda: sketch.xDirection), 12)
    y = _geom.unit_vector(safe(lambda: sketch.yDirection), 12)
    cross = _geom.cross(x, y)
    length = math.sqrt(sum(c * c for c in cross)) if cross is not None else 0.0
    if origin is None or not length:
        return None
    return origin, tuple(c / length for c in cross)


def _on_plane(placement, plane_origin, plane_normal):
    """{parallel, normal_vs_target, origin_off_plane_cm, on_target}: a placement against a plane."""
    origin, normal = placement
    c = _geom.cross(normal, plane_normal)
    angle = math.degrees(math.atan2(math.sqrt(sum(v * v for v in c)),
                                    _geom.dot(normal, plane_normal)))
    parallel = min(angle, 180.0 - angle) <= _geom.PARALLEL_PLANE_TOL_DEG
    off = abs(sum((origin[i] - plane_origin[i]) * plane_normal[i] for i in range(3)))
    return {"parallel": parallel, "origin_off_plane_cm": off,
            "normal_vs_target": ("same" if angle < 90.0 else "opposed") if parallel else None,
            "on_target": parallel and off <= _common.EXTENT_MATCH_TOL_CM}


def _support_name(sketch):
    """(the support plane's name, None), or (None, why it did not read)."""
    return _common.read_optional(lambda: sketch.referencePlane.name)


def _later_rows(design, sketch):
    """(the timeline rows after the sketch's own as [{name, health}], truncated, why unread)."""
    index, why = _common.read_optional(lambda: sketch.timelineObject.index)
    timeline = safe(lambda: design.timeline)
    count = _common.counted(lambda: timeline.count)
    if index is None or count is None:
        return None, False, why or "the timeline count did not read"
    rows = []
    for i in range(index + 1, min(count, index + 1 + _LATER_ROWS_CAP)):
        row = safe(lambda i=i: timeline.item(i))
        rows.append({"name": safe(lambda: row.name), "health": _form_common.health_label(row)})
    return rows, count - index - 1 > _LATER_ROWS_CAP, None


def _target_label(target):
    """How the reply names the resolved target: a plane's name, else its face's body."""
    name = safe(lambda: target.name)
    if name:
        return f"plane '{name}'"
    body = safe(lambda: target.body.name)
    return f"a face of body '{body}'" if body else type(target).__name__


def _redefine(design, sketch, plane):
    """Move the sketch onto a plane or planar face and judge it by the re-read sketch frame."""
    name = safe(lambda: sketch.name)
    marker, count = _common.timeline_marker(design)
    if marker is None:
        return error("The timeline marker did not read, so the plane of sketch "
                     f"'{name}' was not changed.")
    if marker != count:
        return error(f"The timeline marker is at {marker} of {count}; a plane change needs it at "
                     "the end. Call design_edit_timeline(action='roll', to='end') first.")
    owner = safe(lambda: sketch.parentComponent)
    target, perr = _PLANE.resolve(plane, component=owner)
    if perr:
        return error(perr)
    if target is None:
        return error("'plane' is empty; pass a plane alias, name or handle.")
    label = _target_label(target)
    if (safe(lambda: target.assemblyContext) is not None
            or _common.same_component(_inputs.entity_component(target), owner) is not True):
        return error(f"'plane' resolved to {label}, which is not read as belonging to the "
                     f"sketch's own component, so this support change is not available yet; "
                     f"sketch '{name}' was not changed. Pass a construction plane or planar face "
                     "of the sketch's own component.")
    plane_origin, plane_normal = _geom._face_plane(target)
    if plane_origin is None:
        return error(f"The plane geometry of {label} did not read, so sketch '{name}' was not "
                     "changed.")

    plane_before, before_why = _support_name(sketch)
    frame_before = _sketch_detail.sketch_world_frame(sketch, design)
    errors_before, warnings_before, _total = _common.timeline_health(design)
    raised = did = None
    try:
        did = sketch.redefine(target)
    except Exception as e:
        raised = str(e) or type(e).__name__
    plane_after, after_why = _support_name(sketch)
    frame_after = _sketch_detail.sketch_world_frame(sketch, design)
    placement = _placement(sketch)
    verdict = _on_plane(placement, plane_origin, plane_normal) if placement else {}
    errors_after, warnings_after, _total = _common.timeline_health(design)
    new_errors = [n for n in errors_after if n not in errors_before]
    new_warnings = [n for n in warnings_after if n not in warnings_before]
    rows, truncated, rows_why = _later_rows(design, sketch)
    frames = (frame_before, frame_after)
    off = verdict.get("origin_off_plane_cm")
    details = {
        "action": "plane", "sketch": name, "requested_plane": label,
        "redefine_returned": did, "plane_before": plane_before, "plane_after": plane_after,
        "on_target_plane": verdict.get("on_target"),
        "normal_vs_target": verdict.get("normal_vs_target"),
        "origin_off_plane_mm": None if off is None else round(off * 10, 6),
        "frame_before": frame_before, "frame_after": frame_after,
        "frame_changed": None if None in frames else frame_before != frame_after,
        "sketch_health": _form_common.health_label(sketch),
        "later_features": rows, "later_features_truncated": truncated,
        "new_timeline_errors": new_errors, "new_timeline_warnings": new_warnings,
        "marker_before": marker, "marker_after": _common.timeline_marker(design)[0],
    }
    unread = {}
    if plane_before is None:
        unread["plane_before"] = before_why
    if plane_after is None:
        unread["plane_after"] = after_why
    if rows is None:
        unread["later_features"] = rows_why
    if not verdict:
        unread["on_target_plane"] = "the sketch origin or axes did not read back"
    if None in frames:
        unread["frame_changed"] = "a sketch frame did not read"
    if unread:
        details["unread"] = unread
    changed = details["frame_changed"]
    fail = _edit_feature_common.failed
    if raised is not None:
        if changed is False:
            state = "The sketch was not moved: its frame reads as before."
        elif changed:
            state = (f"Its frame CHANGED and now reads origin_mm {frame_after['origin_mm']}, "
                     f"normal {frame_after['normal']}.")
        else:
            state = "Its frame did not read on both sides, so whether it moved is not known."
        return fail(f"Sketch.redefine raised on sketch '{name}': {raised}. {state}", details)
    if did is not True:
        return fail(f"Sketch.redefine returned {did!r} for sketch '{name}'; frame_changed reads "
                    f"{changed}.", details)
    if not verdict:
        return fail(f"Sketch.redefine returned true but the frame of sketch '{name}' did not "
                    "read back, so the change is unverified. Read it with sketch_get.", details)
    if not verdict["parallel"]:
        reads = f"; frame_after reads normal {frame_after['normal']}" if frame_after else ""
        return fail(f"Sketch.redefine returned true but the plane of sketch '{name}' is not "
                    f"parallel to {label}{reads}.", details)
    if not verdict["on_target"]:
        return fail(f"Sketch.redefine returned true but the origin of sketch '{name}' reads "
                    f"{details['origin_off_plane_mm']} mm off {label}.", details)
    if new_errors or new_warnings:
        broke = ", ".join(str(n) for n in new_errors + new_warnings)
        return fail(f"Sketch '{name}' reads on {label} and the change REMAINS, but these "
                    f"timeline rows newly read error or warning: {broke}. Inspect them with "
                    "design_get.", details)
    if details["marker_after"] != marker:
        return fail(f"Sketch '{name}' reads on {label} and the change REMAINS, but the timeline "
                    f"marker reads {details['marker_after']}, was {marker} of {count}. Call "
                    "design_edit_timeline(action='roll', to='end'), then read the sketch with "
                    "sketch_get.", details)
    facing = "the same as" if verdict["normal_vs_target"] == "same" else "opposed to"
    note = (f"Sketch '{name}' reads on {label}, its normal {facing} the target's. "
            "later_features lists the timeline rows after this sketch with their "
            "health. Moving back to an earlier plane can return a different in-plane "
            "orientation; compare frame_after.")
    if changed is False:
        note += " The sketch frame reads identical before and after: nothing moved."
    details["note"] = note
    return ok(details)


def handler(sketch_name: str = "", component: str = "", new_name=None, visible=None,
            plane=None) -> dict:
    """See TOOL_DESCRIPTION."""
    given = [key for key, value in zip(_EDITS, (new_name, visible, plane)) if value is not None]
    if len(given) != 1:
        return error("Pass exactly one of new_name, visible, plane; got "
                     f"{', '.join(given) or 'none'}. Nothing was changed.")
    design, design_refusal = _common.require_design()
    if design_refusal is not None:
        return design_refusal
    wanted = (sketch_name or "").strip()
    if not wanted:
        return error("'sketch_name' is required - sketch_get lists the sketches.")
    sketch, refusal = _sketch_detail.scoped_sketch(design, wanted, component)
    if refusal:
        return error(refusal)
    if sketch is None:
        return error(f"No sketch named '{wanted}'. Available: "
                     + (", ".join(n for n in _common.all_sketch_names(design) if n) or "(none)"))
    if new_name is not None:
        return _rename(design, sketch, component, new_name)
    if visible is not None:
        return _set_visible(sketch, visible)
    return _redefine(design, sketch, plane)


TOOL_DESCRIPTION = "Edit sketch name, visibility or plane; sketch_get reads it."

tool = (
    Tool.create_simple(name="sketch_edit", description=TOOL_DESCRIPTION)
    .add_input_property("sketch_name", {"type": "string"})
    .add_required_input("sketch_name")
    .add_input_property(*_sketch_detail.COMPONENT_SCOPE)
    .add_input_property("new_name", {"type": "string"})
    .add_input_property("visible", {"type": "boolean"})
    .add_input_property(*_PLANE.as_property())
    .strict_schema()
)

item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline", rung="geometry",
        evidence_test="tests/unit/test_sketch_edit.py::TestPlane"
                      "::test_a_true_return_with_the_origin_off_the_target_plane_is_an_error"))


def register_tool():
    register(item)
