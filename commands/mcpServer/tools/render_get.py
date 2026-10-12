# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Read a local render job, settings, scene, environments or canvas state."""

from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ..mcp_primitives.tool import Tool
from . import _render_common, _render_file, _render_jobs, _render_scene
from ._common import counted, error, measured, ok, read_flag, safe


_SLICES = ("job", "settings", "scene", "environments", "canvas")


def _job_row(job_id):
    """Read the native future and verify a finished image on disk."""
    entry = _render_jobs.get(job_id)
    if entry is None:
        return None, (f"job_id '{job_id}' is unknown in this add-in process. A reload or Fusion "
                      "restart loses process-local render jobs; inspect the requested output path.")
    future = entry["future"]
    valid = read_flag(lambda: future.isValid)
    state, state_value = _render_common.job_state(future)
    width = counted(lambda: future.imageWidth)
    height = counted(lambda: future.imageHeight)
    native_filename = safe(lambda: future.filename)
    row = {"job_id": job_id, "state": state, "state_value": state_value,
           "progress": measured(lambda: future.progress), "future_valid": valid,
           "file_path": entry["path"], "native_filename": native_filename,
           "width": width, "height": height, "complete": False}
    if state == "finished":
        _render_jobs.set_terminal(job_id)
        if native_filename != entry["path"] or width is None or height is None:
            row["problem"] = "The finished future's path or dimensions did not match the retained job."
        else:
            row["file"] = _render_file.inspect_image_file(entry["path"], width, height)
            row["complete"] = row["file"]["status"] == "valid" and valid is True
            if not row["complete"]:
                row["problem"] = "The native job finished but its image file is not verified."
    elif state == "failed":
        _render_jobs.set_terminal(job_id)
        row["problem"] = "Fusion reports the local render failed."
    elif state is None or valid is not True:
        row["problem"] = "The native render future did not read as a valid known state."
    return row, None


def _canvas_row(manager):
    """Read the visible in-canvas renderer without changing it."""
    canvas = safe(lambda: manager.inCanvasRendering)
    if canvas is None:
        return None
    resolution = measured(lambda: canvas.limitResolution)
    return {"advanced": read_flag(lambda: canvas.isAdvanced),
            "resolution_pct": round(resolution, 4) if resolution is not None else None,
            "lock_view": read_flag(lambda: canvas.lockView),
            "elapsed_s": counted(lambda: canvas.elapsedTime),
            "iterations": counted(lambda: canvas.iterations),
            "completed": None,
            "note": "The API exposes no passive running/completed flag. Fast mode has no "
                    "completion event; save or stop with render_edit."}


def handler(job_id: str = "", include=None, max_results: int = 20) -> dict:
    """See TOOL_DESCRIPTION."""
    if include is None:
        include = ["job"] if job_id else ["settings"]
    if not isinstance(include, list) or not include or any(value not in _SLICES for value in include):
        return error(f"include={include!r} must contain one or more of {', '.join(_SLICES)}.")
    if len(set(include)) != len(include):
        return error("include repeats a slice; name each slice once.")
    if type(max_results) is not int or not 0 <= max_results <= 100:
        return error(f"max_results={max_results!r} must be 0..100.")
    if "job" in include and not job_id:
        return error("Provide job_id from render_create when include contains 'job'.")
    out = {}
    if "job" in include:
        row, problem = _job_row(job_id)
        if problem:
            return error(problem)
        out["job"] = row
    other = [part for part in include if part != "job"]
    if other:
        design, manager, problem = _render_common.context()
        if problem:
            return _render_common.partial_error(problem, out or None)
        out["render_workspace_active"] = read_flag(lambda: manager.isRenderWorkspaceActive)
        if "settings" in other:
            rendering = safe(lambda: manager.rendering)
            out["settings"] = _render_common.settings_row(rendering) if rendering else None
        if "scene" in other:
            settings = safe(lambda: manager.sceneSettings)
            out["scene"] = _render_scene.scene_row(settings) if settings else None
        if "environments" in other:
            out["environments"] = _render_scene.environment_rows(manager, max_results)
        if "canvas" in other:
            out["canvas"] = _canvas_row(manager)
    return ok(out)


TOOL_DESCRIPTION = ("Read a local render job, settings, scene, environment catalog or canvas state. "
                    "Finished jobs include an image-file and dimension check.")
tool = (Tool.create_simple("render_get", TOOL_DESCRIPTION)
        .add_input_property("job_id", {"type": "string", "description": "From render_create."})
        .add_input_property("include", {"type": "array", "items": {"type": "string", "enum": list(_SLICES)}})
        .add_input_property("max_results", {"type": "integer", "description": "Environment rows, 0..100."})
        .strict_schema())
item = Item.create_tool_item(tool=tool, write="read", handler=handler, run_on_main_thread=True)


def register_tool():
    register(item)
