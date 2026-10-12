# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Start a local image render or a visible in-canvas render."""

import os
import math

import adsk.fusion

from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool
from . import _common, _render_common, _render_jobs
from ._common import error, ok, read_flag, safe


_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tiff")


def _output_path(file_path):
    """Return a new absolute image path or a reason to refuse it."""
    if not isinstance(file_path, str) or not file_path.strip():
        return None, "Provide file_path for a new local PNG, JPEG or TIFF."
    path = os.path.abspath(file_path.strip())
    if not os.path.isabs(file_path.strip()) or os.path.splitext(path)[1].lower() not in _EXTENSIONS:
        return None, f"file_path '{file_path}' must be an absolute .png, .jpg, .jpeg or .tiff path."
    if os.path.exists(path):
        return None, f"file_path '{path}' already exists; choose a new path."
    if not os.path.isdir(os.path.dirname(path)):
        return None, f"The parent directory of '{path}' does not exist."
    return path, None


def _named_camera(design, view_name):
    """Resolve exactly one named-view camera without moving the viewport."""
    views = safe(lambda: design.namedViews)
    if views is None:
        return None, "Named Views did not read; use the active viewport camera."
    matches = [view for view in _common.iter_collection(views)
               if (safe(lambda view=view: view.name) or "").casefold() == view_name.casefold()]
    if len(matches) != 1:
        names = [safe(lambda view=view: view.name) for view in _common.iter_collection(views)]
        return None, (f"view_name '{view_name}' matched {len(matches)} Named Views; choose one exact, "
                      f"unique name from {', '.join(name for name in names if name) or '(none)'}.")
    camera = safe(lambda: matches[0].camera)
    if camera is None:
        return None, f"Named View '{view_name}' has no readable camera."
    return camera, None


def _set_rendering(rendering, *, width, height, quality, transparent, aspect_ratio,
                   resolution_preset):
    """Apply local settings and verify their final combined read-back."""
    requested = {}
    setters = []
    # 'custom' with both dimensions is the width-and-height job: the two setters carry it.
    if resolution_preset and (resolution_preset != "custom" or width is None or height is None):
        value = _render_common.enum_member(adsk.fusion.RenderResolutions,
                                           _render_common.RESOLUTION, resolution_preset)
        if value is None:
            return None, f"resolution_preset '{resolution_preset}' is unavailable in this Fusion build."
        setters.append(("resolution", value))
        requested["resolution_preset"] = resolution_preset
    if aspect_ratio:
        value = _render_common.enum_member(adsk.fusion.RenderAspectRatios,
                                           _render_common.ASPECT, aspect_ratio)
        if value is None:
            return None, f"aspect_ratio '{aspect_ratio}' is unavailable in this Fusion build."
        setters.append(("aspectRatio", value))
        requested["aspect_ratio"] = aspect_ratio
    if width is not None:
        setters.append(("resolutionWidth", width))
        requested["width"] = width
    if height is not None:
        setters.append(("resolutionHeight", height))
        requested["height"] = height
    if quality is not None:
        setters.append(("renderQuality", quality))
        requested["quality"] = quality
    if transparent is not None:
        setters.append(("isBackgroundTransparent", transparent))
        requested["transparent"] = transparent
    if not setters:
        return _render_common.settings_row(rendering), None
    before = _render_common.settings_row(rendering)
    for name, value in setters:
        try:
            setattr(rendering, name, value)
        except Exception as exc:
            after = _render_common.settings_row(rendering)
            return None, (f"Render setting '{name}' raised: {exc}. The renderer may have changed. "
                          f"Before: {before}; now: {after}. Read render_get(include=['settings']).")
    after = _render_common.settings_row(rendering)
    missing = {name: value for name, value in requested.items() if after.get(name) != value}
    if missing:
        return None, (f"Render settings did not keep {missing} after the last setter. The renderer may "
                      f"have changed. Before: {before}; now: {after}. Read render_get(include=['settings']).")
    return after, None


def handler(mode: str = "local", file_path: str = "", width=None, height=None, quality=None,
            transparent=None, view_name: str = "", aspect_ratio: str = "",
            resolution_preset: str = "", advanced=None, canvas_quality=None,
            resolution_pct=None, lock_view=None) -> dict:
    """See TOOL_DESCRIPTION."""
    mode = mode or "local"
    if mode not in ("local", "canvas"):
        return error(f"mode={mode!r} must be local or canvas.")
    local_fields = {"file_path": file_path, "width": width, "height": height, "quality": quality,
                    "transparent": transparent, "aspect_ratio": aspect_ratio,
                    "resolution_preset": resolution_preset, "view_name": view_name}
    canvas_fields = {"advanced": advanced, "canvas_quality": canvas_quality,
                     "resolution_pct": resolution_pct, "lock_view": lock_view}
    if mode == "canvas":
        stray = [f"{name}={value!r}" for name, value in local_fields.items()
                 if value is not None and value != ""]
        remedy = "render_edit(action='canvas_save') saves the canvas image"
    else:
        stray = [f"{name}={value!r}" for name, value in canvas_fields.items() if value is not None]
        remedy = "mode='canvas' takes in-canvas settings"
    if stray:
        return error(f"{', '.join(stray)} cannot be combined with mode='{mode}'; omit "
                     f"{'it' if len(stray) == 1 else 'them'}. {remedy}.")
    if mode == "local":
        path, problem = _output_path(file_path)
        if problem:
            return error(problem)
        if not _render_jobs.capacity():
            return error(f"{_render_jobs._LIMIT} local render jobs are still retained and none has "
                         "been read as finished or failed. Read them with render_get(job_id=...) "
                         "before starting another.")
        for name, value, low, high in (("width", width, 108, 4000), ("height", height, 108, 4000),
                                       ("quality", quality, 25, 100)):
            if value is not None and (type(value) is not int or not low <= value <= high):
                return error(f"{name}={value!r} must be an integer {low}..{high}.")
        if transparent is not None and type(transparent) is not bool:
            return error(f"transparent={transparent!r} must be true or false.")
        if aspect_ratio and aspect_ratio not in _render_common.ASPECT:
            return error(f"aspect_ratio={aspect_ratio!r} is not a listed aspect ratio.")
        if resolution_preset and resolution_preset not in _render_common.RESOLUTION:
            return error(f"resolution_preset={resolution_preset!r} is not a listed preset.")
        sized = width is not None and height is not None
        if resolution_preset == "custom" and (width is None) != (height is None):
            return error("resolution_preset='custom' cannot be combined with one dimension; send "
                         "both width and height, or omit resolution_preset.")
        if resolution_preset not in ("", "custom") and (width is not None or height is not None):
            return error(f"resolution_preset={resolution_preset!r} cannot be combined with width or "
                         "height; omit resolution_preset, or omit width and height.")
        if aspect_ratio and resolution_preset and not sized:
            return error(f"aspect_ratio={aspect_ratio!r} cannot be combined with resolution_preset="
                         f"{resolution_preset!r}; send one of them, or width and height with "
                         "aspect_ratio='custom'.")
        if sized and aspect_ratio not in ("", "custom"):
            return error(f"aspect_ratio={aspect_ratio!r} cannot be combined with both width and "
                         "height; omit aspect_ratio, or send aspect_ratio='custom'.")
    else:
        for name, value, low, high in (("canvas_quality", canvas_quality, 0, 1),
                                       ("resolution_pct", resolution_pct, 20, 100)):
            if value is not None and (type(value) not in (int, float) or not low <= value <= high):
                return error(f"{name}={value!r} must be {low}..{high}.")
        if advanced is not None and type(advanced) is not bool:
            return error(f"advanced={advanced!r} must be true or false.")
        if lock_view is not None and type(lock_view) is not bool:
            return error(f"lock_view={lock_view!r} must be true or false.")

    design, manager, problem = _render_common.context()
    if problem:
        return error(problem)
    if mode == "canvas":
        canvas = safe(lambda: manager.inCanvasRendering)
        if canvas is None:
            return error("In-canvas renderer did not read. Activate the Render workspace with "
                         "view_switch_workspace(workspace='Render'), then retry.")
        before = {"advanced": read_flag(lambda: canvas.isAdvanced),
                  "resolution_pct": safe(lambda: canvas.limitResolution),
                  "lock_view": read_flag(lambda: canvas.lockView)}

        def failed_canvas(message):
            """Unlock a failed canvas start and disclose the final observed settings."""
            restore_error = None
            if lock_view is not None and before["lock_view"] is not None:
                try:
                    canvas.lockView = before["lock_view"]
                except Exception as exc:
                    restore_error = str(exc) or type(exc).__name__
            now = {"advanced": read_flag(lambda: canvas.isAdvanced),
                   "resolution_pct": safe(lambda: canvas.limitResolution),
                   "lock_view": read_flag(lambda: canvas.lockView)}
            return _render_common.partial_error(
                message, {"before": before, "after": now,
                          "lock_restore_error": restore_error})

        for prop, value in (("isAdvanced", advanced), ("limitResolution", resolution_pct),
                            ("lockView", lock_view)):
            if value is not None:
                try:
                    setattr(canvas, prop, value)
                except Exception as exc:
                    return failed_canvas(f"In-canvas setting '{prop}' raised: {exc}; the view may "
                                         "have changed. Read render_get(include=['canvas']).")
        after = {"advanced": read_flag(lambda: canvas.isAdvanced),
                 "resolution_pct": safe(lambda: canvas.limitResolution),
                 "lock_view": read_flag(lambda: canvas.lockView)}
        wanted = {"advanced": advanced, "resolution_pct": resolution_pct, "lock_view": lock_view}
        mismatches = []
        for key, value in wanted.items():
            if value is None:
                continue
            got = after[key]
            equal = (isinstance(got, (int, float)) and not isinstance(got, bool)
                     and math.isclose(got, value, rel_tol=1e-6, abs_tol=1e-5)
                     if key == "resolution_pct" else got is value)
            if not equal:
                mismatches.append(key)
        if mismatches:
            return failed_canvas(f"In-canvas settings {mismatches} did not read back after "
                                 "the last setter.")
        try:
            started = canvas.start(0.75 if canvas_quality is None else canvas_quality)
        except Exception as exc:
            return failed_canvas(f"In-canvas render start raised: {exc}. "
                                 "Read render_get(include=['canvas']).")
        if started is not True:
            return failed_canvas("In-canvas render start returned false. "
                                 "Read render_get(include=['canvas']).")
        after["resolution_pct"] = (round(after["resolution_pct"], 4)
                                   if isinstance(after["resolution_pct"], (int, float)) else None)
        return ok({"mode": "canvas", "started": True, "job_id": None, "settings": after,
                   "note": "The render uses the visible viewport. Read render_get(include=['canvas']); "
                           "render_edit(action='canvas_stop') stops it."})

    rendering = safe(lambda: manager.rendering)
    if rendering is None:
        return error("Local renderer did not read for this Design.")
    camera = None
    if view_name:
        camera, problem = _named_camera(design, view_name.strip())
        if problem:
            return error(problem)
    if width is not None and height is not None and not aspect_ratio:
        aspect_ratio = "custom"
    settings, problem = _set_rendering(rendering, width=width, height=height, quality=quality,
                                      transparent=transparent, aspect_ratio=aspect_ratio,
                                      resolution_preset=resolution_preset)
    if problem:
        return error(problem)
    try:
        future = (rendering.startLocalRender(path, camera) if camera is not None
                  else rendering.startLocalRender(path))
    except Exception as exc:
        return error(f"Local render did not start for '{path}': {exc}. Settings now: {settings}.")
    if future is None:
        return error(f"Local render returned no job for '{path}'. Settings now: {settings}.")
    job_id = _render_jobs.add(future, path, safe(lambda: design.parentDocument))
    if job_id is None:
        return error(f"Local render started for '{path}' but its future could not be retained. "
                     "Check the output path later; no job_id is available.")
    state, state_value = _render_common.job_state(future)
    observed = {"filename": safe(lambda: future.filename),
                "width": safe(lambda: future.imageWidth), "height": safe(lambda: future.imageHeight),
                "state": state, "state_value": state_value,
                "valid": read_flag(lambda: future.isValid)}
    if observed["valid"] is not True or state not in ("queued", "processing", "finished"):
        return _render_common.partial_error(
            f"Local render did not return a valid queued, processing or finished future. "
            f"Use render_get(job_id='{job_id}') to inspect it.",
            {"job_id": job_id, "requested_path": path, "settings": settings, "job": observed})
    if observed["filename"] != path or observed["width"] != settings["width"] or observed["height"] != settings["height"]:
        return _render_common.partial_error(
            f"Local render started but its filename or dimensions differ from the request. "
            f"Use render_get(job_id='{job_id}') to track it.",
            {"job_id": job_id, "requested_path": path, "settings": settings, "job": observed})
    return ok({"mode": "local", "job_id": job_id, "file_path": path, "settings": settings,
               "job": observed, "note": "The job is asynchronous. Poll render_get(job_id=...) for native "
                                         "state and file verification; Fusion exit ends the job."})


TOOL_DESCRIPTION = ("Start a local PNG/JPEG/TIFF job or visible in-canvas render. A local job returns "
                    "job_id for render_get; a canvas render has no job ID.")
tool = (Tool.create_simple("render_create", TOOL_DESCRIPTION)
        .add_input_property("mode", {"type": "string", "enum": ["local", "canvas"]})
        .add_input_property("file_path", {"type": "string", "description": "New absolute local image path."})
        .add_input_property("width", {"type": "integer", "description": "Pixels, 108..4000."})
        .add_input_property("height", {"type": "integer", "description": "Pixels, 108..4000."})
        .add_input_property("quality", {"type": "integer", "description": "25..100."})
        .add_input_property("transparent", {"type": "boolean"})
        .add_input_property("view_name", {"type": "string", "description": "Named View camera; else viewport."})
        .add_input_property("aspect_ratio", {"type": "string", "enum": list(_render_common.ASPECT)})
        .add_input_property("resolution_preset", {"type": "string", "enum": list(_render_common.RESOLUTION)})
        .add_input_property("advanced", {"type": "boolean"})
        .add_input_property("canvas_quality", {"type": "number", "description": "0..1."})
        .add_input_property("resolution_pct", {"type": "integer", "description": "20..100."})
        .add_input_property("lock_view", {"type": "boolean"})
        .strict_schema())
item = Item.create_tool_item(tool=tool, write="write", handler=handler, run_on_main_thread=True,
                             verification=Verification(kind="inline", rung="value",
                                 evidence_test="tests/unit/test_render_create.py"
                                               "::test_future_without_matching_dimensions_is_error"))


def register_tool():
    register(item)
