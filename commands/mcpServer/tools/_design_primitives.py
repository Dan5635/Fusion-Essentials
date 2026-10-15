# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Design mode and timeline health reads below tool inputs."""

import re

import adsk.fusion

from ._read_primitives import safe

MAP_BLURB = "MODE_PARAMETRIC/MODE_DIRECT/current_design_type; timeline_health/timeline_message - shared mode and health reads."


MODE_PARAMETRIC = "parametric"
MODE_DIRECT = "direct"


def current_design_type(design) -> str:
    """The active design's modelling mode as 'parametric' / 'direct' / 'unknown' - the ONE source
    design_get's mode slice and every ModeGuard share, so the report and the guards cannot drift.
    A missing/mocked designType degrades to 'unknown' rather than crashing."""
    if design is None:
        return "unknown"
    dt = safe(lambda: design.designType)
    if dt is None:
        return "unknown"
    types = safe(lambda: adsk.fusion.DesignTypes)
    param = safe(lambda: types.ParametricDesignType)
    direct = safe(lambda: types.DirectDesignType)
    if param is not None and dt == param:
        return MODE_PARAMETRIC
    if direct is not None and dt == direct:
        return MODE_DIRECT
    # Confirmed live: ParametricDesignType == 1, DirectDesignType == 0 - for a build where
    # DesignTypes is not a comparable enum and designType reads as a bare int.
    if isinstance(dt, int) and not isinstance(dt, bool):
        if dt == 1:
            return MODE_PARAMETRIC
        if dt == 0:
            return MODE_DIRECT
    return "unknown"


class _HealthName(str):
    """One unhealthy timeline item's name that serializes as the name while ``==`` compares the
    row's ENTITY token - timeline names are NOT unique across components (measured), so a bare-name
    diff is blind to a namesake's damage. ``__hash__`` stays the NAME's hash."""

    def __new__(cls, name, token=None):
        obj = str.__new__(cls, name)
        obj.token = token or None
        return obj

    def __eq__(self, other):
        mine, theirs = self.token, getattr(other, "token", None)
        if mine and theirs:
            return mine == theirs
        return str.__eq__(self, other)

    def __ne__(self, other):
        same = self.__eq__(other)
        return same if same is NotImplemented else not same

    __hash__ = str.__hash__


def timeline_health(design, limit=None):
    """(error_names, warning_names, total) over the parametric timeline by healthState (2=error,
    1=warning) - the shared before/after guard for edits that break downstream features; a direct
    design yields empty lists. Each name is a ``_HealthName``, compared on the row's entity token."""
    # ``limit`` bounds the walk to the first n items, keeping a CREATE's guard off the entry it just
    # added: a freshly added assembly constraint's own healthState RAISES '1 : Unknown exception'
    # (measured), and that caught error inside Python.Run rolled the whole transaction back.
    errors, warnings, total = [], [], 0
    tl = safe(lambda: design.timeline)
    if tl is None:
        return errors, warnings, total
    count = safe(lambda: tl.count, 0) or 0
    if limit is not None:
        count = min(count, max(int(limit), 0))
    for i in range(count):
        it = tl.item(i)
        total += 1
        hs = safe(lambda it=it: it.healthState)
        if hs not in (1, 2):
            continue
        # A TimelineObject carries no entityToken of its own; the ENTITY it stands for does, and
        # that token re-reads identical within a session (measured). TimelineObject.entity is None
        # for a group row and for a feature class with no public-API form, which keys on its name.
        label = _HealthName(safe(lambda it=it: it.name) or f"#{i}",
                            safe(lambda it=it: it.entity.entityToken))
        (errors if hs == 2 else warnings).append(label)
    return errors, warnings, total


# A timeline row's errorOrWarningMessage carries <b>/<br/> markup, glues its 'Body N missing'
# items and sentences together, and ends with the row's own name after the last sentence.
_MESSAGE_MARKUP = re.compile(r"<[^>]*>")
_MESSAGE_GLUE = re.compile(r"(?<=missing)(?=[A-Z0-9])|(?<=[.!?])(?=[A-Z])")
_MESSAGE_LIMIT = 400


def timeline_message(raw, name=None, limit=_MESSAGE_LIMIT):
    """A timeline errorOrWarningMessage as '; '-joined plain text, less the row's `name` suffix."""
    text = raw if isinstance(raw, str) else ""
    if isinstance(name, str) and name and text.endswith(name):
        text = text[:-len(name)]
    items = []
    for part in _MESSAGE_MARKUP.split(text):
        for item in _MESSAGE_GLUE.split(part):
            item = " ".join(item.split()).rstrip(".")
            if item:
                items.append(item)
    text = "; ".join(items)
    return text[:limit].rstrip() + " ..." if len(text) > limit else text
