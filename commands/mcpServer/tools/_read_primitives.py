# Copyright (c) Fusion-Essentials contributors. Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

MAP_BLURB = "safe - per-field reads below design and typed inputs."


def safe(getter, default=None):
    """Return getter() or default when a field read raises; never wrap a mutation."""
    try:
        return getter()
    except Exception:
        return default
