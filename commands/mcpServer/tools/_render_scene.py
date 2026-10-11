# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Passive scene and environment reads for Rendering tools."""

import math

import adsk.core
import adsk.fusion

from ._common import CM_TO_UNIT, counted, measured, read_flag, safe
from ._render_common import ASPECT as ASPECTS, enum_label


MAP_BLURB = "scene_row/environment_rows: bounded passive scene and environment reads."

CAMERAS = {
    "orthographic": "OrthographicCameraType",
    "perspective": "PerspectiveCameraType",
    "perspective_ortho_faces": "PerspectiveWithOrthoFacesCameraType",
}


def _point(point, factor):
    """Return three finite coordinates in requested units."""
    if point is None:
        return None
    values = [measured(lambda axis=axis: getattr(point, axis), factor)
              for axis in ("x", "y", "z")]
    return values if all(value is not None for value in values) else None


def _color(color):
    """Return RGB channels when every channel reads."""
    if color is None:
        return None
    values = [safe(lambda name=name: getattr(color, name)) for name in ("red", "green", "blue")]
    return values if all(type(value) is int and 0 <= value <= 255 for value in values) else None


def scene_row(settings, units="mm"):
    """Read the full scene, marking unreadable fields null."""
    factor = CM_TO_UNIT.get(units)
    if factor is None:
        raise ValueError(f"Unknown units '{units}'.")
    background = safe(lambda: settings.backgroundType)
    environment_type = safe(lambda: adsk.fusion.RenderSceneBackgroundTypes.EnvironmentRenderSceneBackgroundType)
    solid_type = safe(lambda: adsk.fusion.RenderSceneBackgroundTypes.SolidColorRenderSceneBackgroundType)
    background_type = ("environment" if background == environment_type and environment_type is not None
                       else "solid_color" if background == solid_type and solid_type is not None else None)
    environment = safe(lambda: settings.backgroundEnvironment) if background_type == "environment" else None
    color = safe(lambda: settings.backgroundSolidColor) if background_type == "solid_color" else None
    return {
        "units": units,
        "background_type": background_type,
        "environment_id": safe(lambda: environment.id),
        "environment_name": safe(lambda: environment.name),
        "environment_custom": read_flag(lambda: environment.isCustomEnvironment) if environment else None,
        "background_rgb": _color(color),
        "brightness_lux": measured(lambda: settings.brightness),
        "exposure_ev": measured(lambda: settings.cameraExposure),
        "focal_length_mm": measured(lambda: settings.cameraFocalLength),
        "camera_type": enum_label(adsk.core.CameraTypes, CAMERAS,
                                  safe(lambda: settings.cameraType)),
        "focus": _point(safe(lambda: settings.centerOfFocus), factor),
        "dof_blur": measured(lambda: settings.depthOfFieldBlur),
        "dof_enabled": read_flag(lambda: settings.isDepthOfFieldEnabled),
        "ground_offset": measured(lambda: settings.groundOffset, factor),
        "ground_position": _point(safe(lambda: settings.groundPosition), factor),
        "ground_roughness": measured(lambda: settings.groundRoughness),
        "show_ground": read_flag(lambda: settings.isGroundDisplayed),
        "flatten_ground": read_flag(lambda: settings.isGroundFlattened),
        "ground_reflect": read_flag(lambda: settings.isGroundReflections),
        "light_angle_deg": measured(lambda: settings.lightAngle, 180.0 / math.pi),
        "aspect_ratio": enum_label(adsk.fusion.RenderAspectRatios, ASPECTS,
                                   safe(lambda: settings.aspectRatio)),
        "aspect_width": counted(lambda: settings.aspectRatioWidth),
        "aspect_height": counted(lambda: settings.aspectRatioHeight),
    }


def environment_rows(manager, max_results):
    """Read at most max_results environment identities from the manager."""
    if type(max_results) is not int or not 0 <= max_results <= 100:
        raise ValueError(f"max_results={max_results!r} must be 0..100.")
    environments = safe(lambda: manager.renderEnvironments)
    total = counted(lambda: environments.count)
    if total is None or total < 0:
        return {"count": None, "environments": [], "truncated": None}
    rows = []
    for index in range(min(total, max_results)):
        env = safe(lambda index=index: environments.item(index))
        rows.append({"id": safe(lambda: env.id), "name": safe(lambda: env.name),
                     "custom": read_flag(lambda: env.isCustomEnvironment) if env else None})
    return {"count": total, "environments": rows, "truncated": total > max_results}
