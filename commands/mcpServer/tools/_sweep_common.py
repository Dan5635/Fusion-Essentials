# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Shared profile construction for sweep creation and profile replacement."""

from . import _common, _inputs, _sketch_detail
from ._common import safe


MAP_BLURB = "resolve_profile: closed or open sweep section on its owning component"


_PROFILE = _inputs.ProfileRef("profile", required=True, scope_input="component")


def resolve_profile(design, comp, profile_raw, as_surface, component=""):
    """Return (profile, solid, open, host, source sketch, error) for a sweep section."""
    if profile_raw in (None, "", []):
        return None, None, None, None, None, "'profile' is required (handle or {sketch, profile_index})."
    prof, err = _PROFILE.resolve(profile_raw, component)
    if prof is not None:
        host = _inputs.profile_host_component(prof, None, comp)
        return prof, not bool(as_surface), False, host, None, None
    if not isinstance(profile_raw, dict):
        return None, None, None, None, None, err
    name = profile_raw.get("sketch", profile_raw.get("sketch_name", ""))
    sketch, _requested, refusal = _sketch_detail.scoped_or_recent_sketch(design, name, component)
    if refusal:
        return None, None, None, None, None, refusal
    if sketch is None:
        return None, None, None, None, None, err
    host = safe(lambda: sketch.parentComponent) or comp
    open_prof, refusal = _common.open_profile_from_sketch(
        host, sketch, "for a surface sweep",
        no_curves_error=(f"Profile sketch '{safe(lambda: sketch.name)}' has no curves to sweep."))
    if open_prof is None:
        return None, None, None, None, None, refusal or err
    return open_prof, False, True, host, sketch, None
