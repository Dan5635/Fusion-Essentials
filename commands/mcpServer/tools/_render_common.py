# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Read the active Design's renderer and its local image settings."""

import adsk.fusion

from . import _common
from ._common import safe, read_flag


MAP_BLURB = "RenderManager access and local image setting rows for render_create/render_get"

ASPECT = {
    "viewport": "CurrentViewportRenderAspectRatio",
    "square": "Square1to1RenderAspectRatio",
    "4:3": "Presentation4to3RenderAspectRatio",
    "16:9": "Widescreen16to9RenderAspectRatio",
    "5:4": "Landscape5to4RenderAspectRatio",
    "4:5": "Portrait4to5RenderAspectRatio",
    "custom": "CustomRenderAspectRatio",
}


def partial_error(message, payload):
    """Put a partial failure's reason beside its effect in MCP content."""
    return _common.error(message, payload)
RESOLUTION = {
    "Web800x600": "Web800x600RenderResolution",
    "Web1024x768": "Web1024x768RenderResolution",
    "Web1152x864": "Web1152x864RenderResolution",
    "Web1280x1024": "Web1280x1024RenderResolution",
    "Web1600x1200": "Web1600x1200RenderResolution",
    "Mobile960x640": "Mobile960x640RenderResolution",
    "Mobile1136x640": "Mobile1136x640RenderResolution",
    "Mobile1334x750": "Mobile1334x750RenderResolution",
    "Mobile1920x1080": "Mobile1920x1080RenderResolution",
    "Mobile2048x1536": "Mobile2048x1536RenderResolution",
    "Print1800x1200": "Print1800x1200RenderResolution",
    "Print2100x1500": "Print2100x1500RenderResolution",
    "Print3000x2400": "Print3000x2400RenderResolution",
    "Print3300x2550": "Print3300x2550RenderResolution",
    "Video854x480": "Video854x480RenderResolution",
    "Video1280x720": "Video1280x720RenderResolution",
    "Video1920x1080": "Video1920x1080RenderResolution",
    "custom": "CustomRenderResolution",
}


def context():
    """Return (Design, RenderManager, problem) for the active document."""
    design = _common.design()
    if design is None:
        return None, None, "No active Design document; open or create a Design first."
    manager = safe(lambda: design.renderManager)
    if manager is None or read_flag(lambda: manager.isValid) is False:
        return design, None, "The active Design's RenderManager did not read."
    return design, manager, None


def enum_member(family, mapping, key):
    """Return a named installed enum member, or None when unavailable."""
    name = mapping.get(key)
    return safe(lambda: getattr(family, name)) if name else None


def enum_label(family, mapping, value):
    """Return a wire key for a native enum value, or None when unreadable."""
    if value is None:
        return None
    for key in mapping:
        if enum_member(family, mapping, key) == value:
            return key
    return None


def settings_row(rendering):
    """Return independent local-render setting reads in pixels and named choices."""
    aspect = safe(lambda: rendering.aspectRatio)
    resolution = safe(lambda: rendering.resolution)
    return {
        "quality": safe(lambda: rendering.renderQuality),
        "width": safe(lambda: rendering.resolutionWidth),
        "height": safe(lambda: rendering.resolutionHeight),
        "transparent": read_flag(lambda: rendering.isBackgroundTransparent),
        "aspect_ratio": enum_label(adsk.fusion.RenderAspectRatios, ASPECT, aspect),
        "aspect_ratio_value": aspect,
        "resolution_preset": enum_label(adsk.fusion.RenderResolutions, RESOLUTION, resolution),
        "resolution_value": resolution,
    }
