# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Edit Render scene settings and manage in-canvas rendering."""

import math
from pathlib import Path

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, read_flag, safe, scale
from . import _render_common, _render_scene
from ._render_file import inspect_image_file


_ACTIONS = ("scene", "reset_scene", "canvas_stop", "canvas_save", "activate")
_SCENE_KEYS = (
    "environment_id", "environment_name", "background_rgb",
    "brightness_lux", "exposure_ev", "focal_length_mm", "camera_type",
    "ground_offset", "ground_roughness",
    "show_ground", "flatten_ground", "ground_reflect", "light_angle_deg",
)
_ORDER = (
    "environment_id", "environment_name", "background_rgb",
    "brightness_lux", "exposure_ev", "camera_type", "focal_length_mm",
    "show_ground", "flatten_ground", "ground_reflect", "ground_offset",
    "ground_roughness", "light_angle_deg",
)
_NUMBER_BOUNDS = {
    "brightness_lux": (0, 100000), "exposure_ev": (-15, 25),
    "ground_roughness": (0, 1),
}
_NUMBER_KEYS = ("brightness_lux", "exposure_ev", "focal_length_mm",
                "ground_offset", "ground_roughness", "light_angle_deg")
_BOOL_KEYS = ("show_ground", "flatten_ground", "ground_reflect")
_SCALAR_ATTRS = {
    "brightness_lux": "brightness", "exposure_ev": "cameraExposure",
    "focal_length_mm": "cameraFocalLength",
    "ground_offset": "groundOffset", "ground_roughness": "groundRoughness",
    "show_ground": "isGroundDisplayed", "flatten_ground": "isGroundFlattened",
    "ground_reflect": "isGroundReflections",
    "light_angle_deg": "lightAngle",
}


def _validate_scene(scene):
    """Return a preflight error for a malformed scene request."""
    if not isinstance(scene, dict) or not scene:
        return "scene must be a nonempty object."
    blocked = sorted(set(scene) & {"focus", "dof_blur", "dof_enabled"})
    if blocked:
        return (f"Scene field(s) {', '.join(blocked)} cannot be written: Fusion can show a blocking "
                "depth-of-field warning while ray tracing is off. Read them with render_get instead.")
    unknown = sorted(set(scene) - set(_SCENE_KEYS))
    if unknown:
        return f"Unknown scene field(s): {', '.join(unknown)}."
    env_keys = [key for key in ("environment_id", "environment_name")
                if key in scene]
    if len(env_keys) + int("background_rgb" in scene) > 1:
        return "Choose one of environment_id, environment_name, background_rgb."
    for key in env_keys:
        if not isinstance(scene[key], str) or not scene[key].strip():
            return f"{key} must be a nonempty string."
    for key in _NUMBER_KEYS:
        if key in scene:
            value = scene[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value)):
                return f"{key}={value!r} must be a finite number."
            low_high = _NUMBER_BOUNDS.get(key)
            if low_high and not low_high[0] <= value <= low_high[1]:
                return f"{key}={value!r} must be {low_high[0]}..{low_high[1]}."
    for key in _BOOL_KEYS:
        if key in scene and type(scene[key]) is not bool:
            return f"{key}={scene[key]!r} must be a boolean."
    if "background_rgb" in scene and (not isinstance(scene["background_rgb"], list) or
            len(scene["background_rgb"]) != 3 or
            any(type(v) is not int or not 0 <= v <= 255 for v in scene["background_rgb"])):
        return "background_rgb must contain three integers in 0..255."
    if "camera_type" in scene and scene["camera_type"] not in _render_scene.CAMERAS:
        return f"camera_type={scene['camera_type']!r} is not a listed camera type."
    return None


def _environment(manager, scene):
    """Return a uniquely resolved environment or a refusal before scene setters."""
    collection = safe(lambda: manager.renderEnvironments)
    if "environment_id" in scene:
        wanted = scene["environment_id"]
        env = safe(lambda: collection.itemById(wanted))
        if env is None or safe(lambda: env.id) != wanted:
            return None, f"environment_id={wanted!r} did not resolve; read render_get environments."
        return env, None
    if "environment_name" in scene:
        wanted = scene["environment_name"].strip().casefold()
        count = safe(lambda: collection.count)
        if type(count) is not int or count < 0:
            return None, "Environment count did not read; use environment_id from render_get."
        matches = []
        for index in range(count):
            env = safe(lambda index=index: collection.item(index))
            name = safe(lambda: env.name)
            if not isinstance(name, str):
                return None, "An environment name did not read; use environment_id from render_get."
            if name.casefold() == wanted:
                matches.append(env)
        if len(matches) != 1:
            ids = [safe(lambda env=env: env.id) for env in matches]
            return None, (f"environment_name={scene['environment_name']!r} matched "
                          f"{len(matches)} environments (ids={ids}); use environment_id.")
        return matches[0], None
    return None, None


def _set_scene_value(settings, key, value, environment, unit_to_cm):
    """Assign one validated scene field through its installed property."""
    if key.startswith("environment_"):
        settings.backgroundEnvironment = environment
    elif key == "background_rgb":
        settings.backgroundSolidColor = adsk.core.Color.create(*value, 255)
    elif key == "camera_type":
        settings.cameraType = getattr(adsk.core.CameraTypes, _render_scene.CAMERAS[value])
    else:
        native = (value * unit_to_cm if key == "ground_offset" else
                  value * math.pi / 180 if key == "light_angle_deg" else value)
        setattr(settings, _SCALAR_ATTRS[key], native)


def _differences(scene, after, environment):
    """Return requested fields whose final read differs or is unreadable."""
    mismatches = {}
    for key, wanted in scene.items():
        field = "environment_id" if key.startswith("environment_") else key
        if key.startswith("environment_"):
            wanted = safe(lambda: environment.id)
        got = after[field]
        if got is None or wanted is None:
            mismatches[key] = got
        elif isinstance(wanted, list):
            if (not isinstance(got, list) or len(got) != len(wanted) or
                    any(not math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-5)
                        for a, b in zip(got, wanted))):
                mismatches[key] = got
        elif isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
            if not isinstance(got, (int, float)) or not math.isclose(
                    got, wanted, rel_tol=1e-6, abs_tol=1e-5):
                mismatches[key] = got
        elif got != wanted:
            mismatches[key] = got
    return mismatches


def _edit_scene(manager, scene, units):
    """Apply a validated scene edit and compare the complete final scene."""
    settings = safe(lambda: manager.sceneSettings)
    if settings is None:
        return error("Scene settings did not read.")
    environment, problem = _environment(manager, scene)
    if problem:
        return error(problem)
    before = _render_scene.scene_row(settings, units)
    if ("focal_length_mm" in scene and
            scene.get("camera_type", before.get("camera_type")) != "perspective"):
        return error("focal_length_mm requires camera_type='perspective'; set it in this "
                     "scene edit or switch the camera first.")
    if "ground_roughness" in scene and scene.get("ground_reflect", before.get("ground_reflect")) is not True:
        return error("ground_roughness requires ground_reflect=true; set it in this scene edit or "
                     "enable ground reflections first.")
    applied = []
    failure = None
    for key in _ORDER:
        if key not in scene:
            continue
        try:
            _set_scene_value(settings, key, scene[key], environment, scale(units))
            applied.append(key)
        except Exception as exc:
            failure = {"field": key, "reason": str(exc) or type(exc).__name__}
            break
    after = _render_scene.scene_row(settings, units)
    mismatches = _differences({key: scene[key] for key in applied}, after, environment)
    requested = set(scene)
    if requested & {"environment_id", "environment_name"}:
        requested |= {"environment_id", "environment_name", "environment_custom", "background_type"}
    changed_unrequested = {key: {"before": value, "after": after.get(key)}
                           for key, value in before.items()
                           if key not in requested and after.get(key) != value}
    payload = {"before": before, "after": after, "applied": applied,
               "failed": failure, "mismatches": mismatches,
               "changed_unrequested": changed_unrequested}
    camera_reach = ""
    if "camera_type" in applied:
        camera_reach = (" New documents open with this camera type until it is changed back."
                        if after.get("camera_type") == scene["camera_type"] else
                        " New-document camera type is unverified; read it before another edit.")
    if failure or mismatches:
        if failure:
            key = failure["field"]
            reason = f"scene.{key}={scene[key]!r} raised {failure['reason']}"
        else:
            key = next(iter(mismatches))
            reason = f"scene.{key}={scene.get(key)!r} read back {mismatches[key]!r}"
        detail = reason + "; read render_get(include=['scene']) before another edit." + camera_reach
        return _render_common.partial_error(detail, payload)
    return ok({**payload, "note": "Scene read-back matches the requested fields." + camera_reach})


def _fresh_image_path(file_path):
    """Return an image path only when it cannot overwrite an existing file."""
    path = Path(file_path) if isinstance(file_path, str) else Path("")
    if (not file_path or not path.is_absolute() or
            path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".tiff") or
            not path.parent.is_dir() or path.exists()):
        return None, (f"file_path={file_path!r} must be a fresh absolute PNG, JPEG or TIFF "
                      "path in an existing directory.")
    return path, None


def handler(action: str, scene=None, units: str = "mm", file_path: str = "") -> dict:
    """Apply one Rendering edit and disclose its observed effect."""
    if action not in _ACTIONS:
        return error(f"Unknown action {action!r}; use a listed action.")
    if units not in ("mm", "cm", "in"):
        return error(f"units={units!r} must be mm, cm or in.")
    if action == "scene":
        problem = _validate_scene(scene)
        if problem:
            return error(problem)
    elif scene is not None or units != "mm":
        return error(f"action={action!r} does not use scene or units.")
    if action != "canvas_save" and file_path:
        return error(f"action={action!r} does not use file_path.")
    path = None
    if action == "canvas_save":
        path, problem = _fresh_image_path(file_path)
        if problem:
            return error(problem)
    _, manager, problem = _render_common.context()
    if problem:
        return error(problem)
    if action == "scene":
        return _edit_scene(manager, scene, units)
    if action == "activate":
        before = read_flag(lambda: manager.isRenderWorkspaceActive)
        try:
            reported = manager.activateRenderWorkspace()
        except Exception as exc:
            return error(f"Render workspace activation raised: {exc}.")
        after = read_flag(lambda: manager.isRenderWorkspaceActive)
        payload = {"active_before": before, "active_after": after, "native_return": reported}
        if reported is not True or after is not True:
            return _render_common.partial_error(
                "Render workspace activation did not verify as active.", payload)
        return ok(payload)
    if action == "reset_scene":
        settings = safe(lambda: manager.sceneSettings)
        if settings is None:
            return error("Scene settings did not read.")
        before = _render_scene.scene_row(settings)
        try:
            reported = settings.restoreDefaults()
        except Exception as exc:
            return _render_common.partial_error(
                f"{action} raised: {exc}.", {"before": before,
                                            "after": _render_scene.scene_row(settings)})
        after = _render_scene.scene_row(settings)
        changed_fields = {key: {"before": value, "after": after.get(key)}
                          for key, value in before.items() if after.get(key) != value}
        unchanged_fields = {key: value for key, value in before.items()
                            if after.get(key) == value}
        payload = {"before": before, "after": after, "native_return": reported,
                   "changed": bool(changed_fields), "changed_fields": changed_fields,
                   "unchanged_fields": unchanged_fields}
        if reported is not True:
            return _render_common.partial_error(
                f"{action} returned false; inspect scene read-back.", payload)
        if not changed_fields:
            detail = ("reset_scene returned true but no scene field changed; reset effect was not "
                      "verified. Read render_get(include=['scene']).")
            return _render_common.partial_error(detail, payload)
        payload["note"] = ("Fusion changed the listed fields. An unchanged field may already be "
                           "at its default or may have been left alone.")
        return ok(payload)
    canvas = safe(lambda: manager.inCanvasRendering)
    if canvas is None:
        return error("In-canvas renderer did not read.")
    if action == "canvas_stop":
        try:
            reported = canvas.stop()
        except Exception as exc:
            return error(f"In-canvas stop raised: {exc}.")
        if reported is not True:
            return error(f"In-canvas stop returned {reported!r}.")
        locked_after_stop = read_flag(lambda: canvas.lockView)
        unlock_error = None
        if locked_after_stop is True:
            try:
                canvas.lockView = False
            except Exception as exc:
                unlock_error = str(exc) or type(exc).__name__
        locked_final = read_flag(lambda: canvas.lockView)
        payload = {"native_return": True, "lock_view_after_stop": locked_after_stop,
                   "lock_view_final": locked_final, "effect_verified": False}
        if locked_final is not False:
            payload["unlock_error"] = unlock_error
            return _render_common.partial_error(
                "Canvas stop returned true, but the view did not read back unlocked.", payload)
        payload["note"] = "Stop returned true and the view is unlocked; no passive running-state read exists."
        return ok(payload)
    try:
        reported = canvas.saveImage(str(path))
    except Exception as exc:
        image = inspect_image_file(path)
        return _render_common.partial_error(
            f"In-canvas save raised: {exc}.", {"file_path": str(path), "image": image})
    image = inspect_image_file(path)
    payload = {"file_path": str(path), "native_return": reported, "image": image}
    if reported is not True or image["status"] != "valid":
        return _render_common.partial_error(
            "In-canvas image save did not produce a verified image.", payload)
    return ok(payload)


TOOL_DESCRIPTION = "Edit scene or restore defaults; activate Render; stop canvas or save a new image."

tool = (
    Tool.create_simple("render_edit", TOOL_DESCRIPTION)
    .add_input_property("action", {"type": "string", "enum": list(_ACTIONS)})
    .add_required_input("action")
    .add_input_property("scene", {"type": "object", "additionalProperties": False,
        "properties": {
            "environment_id": {"type": "string"}, "environment_name": {"type": "string"},
            "background_rgb": {"type": "array", "items": {"type": "integer"},
                               "minItems": 3, "maxItems": 3},
            "brightness_lux": {"type": "number"}, "exposure_ev": {"type": "number"},
            "focal_length_mm": {"type": "number"},
            "camera_type": {"type": "string", "enum": list(_render_scene.CAMERAS)},
            "ground_offset": {"type": "number"},
            "ground_roughness": {"type": "number"}, "show_ground": {"type": "boolean"},
            "flatten_ground": {"type": "boolean"}, "ground_reflect": {"type": "boolean"},
            "light_angle_deg": {"type": "number"},
        }})
    .add_input_property("units", {"type": "string", "enum": ["mm", "cm", "in"]})
    .add_input_property("file_path", {"type": "string"})
    .strict_schema()
)
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(kind="inline", rung="value",
                              evidence_test="tests/unit/test_render_edit.py::test_scene_checks_final_read_back"),
)


def register_tool():
    register(item)
