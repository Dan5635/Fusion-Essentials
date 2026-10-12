# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Read and rebuild the supported Hem definitions at their timeline edit row."""

import math
from decimal import Decimal

import adsk.core
import adsk.fusion

from . import _inputs, _param_common, _sheet_common

MAP_BLURB = "hem_read/prepare_hem/write_hem - supported Hem definition reads, validation and rebuild."
HEM_KINDS = ("flat", "open", "rolled", "double")
_METHODS = {kind: "redefineAs" + kind.title() + "Hem" for kind in HEM_KINDS}


def hem_read(feature):
    """Return the comparable Hem controls and a restorable public expression definition."""
    definition = feature.definition
    kind = next((kind for kind in HEM_KINDS if definition.objectType ==
                 "adsk::fusion::" + _sheet_common._KIND_SPEC[kind][1]), None)
    if kind is None:
        raise ValueError("Only flat, open, rolled and double Hem definitions are supported.")
    flip = definition.isFlipped
    if type(flip) is not bool:
        raise ValueError("Hem flip is unreadable.")
    position = next((name for name, member in _sheet_common._POSITIONS.items()
                     if definition.bendPositionType == getattr(adsk.fusion.BendPositionTypes, member)), None)
    if position is None:
        raise ValueError("Hem bend position is not start_edge or tangent_to_side.")
    values, dimensions = {}, {}
    for name in _sheet_common._KIND_SPEC[kind][0]:
        parameter = getattr(definition, "angle" if name == "angle_deg" else name)
        value, expression = parameter.value, parameter.expression
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not isinstance(expression, str) or not expression):
            raise ValueError(f"Hem {name} value or expression is unreadable.")
        values[name] = round(value, 12)
        dimensions[name] = {"expression": expression,
                            "value_rad" if name == "angle_deg" else "value_cm": value}
    state = {"type": kind, "flip": flip, "bend_position": position, "dimensions": values,
             "expressions": {name: _param_common._normalized_expression(row["expression"])
                             for name, row in dimensions.items()}}
    public = {"type": kind, "flip": flip, "bend_position": position, "dimensions": dimensions}
    return state, public


def prepare_hem(raw, before, design):
    """Return a validated rebuild payload and expected controls, or raise before mutation."""
    if not isinstance(raw, dict):
        raise ValueError("'hem' needs an object with type and its length expressions.")
    kind = raw.get("type")
    if kind not in HEM_KINDS:
        raise ValueError(f"hem.type={kind!r}; use flat, open, rolled or double.")
    dimensions = _sheet_common._KIND_SPEC[kind][0]
    allowed = {"type", "flip", "bend_position", *dimensions}
    extra = set(raw) - allowed
    missing = set(dimensions) - set(raw)
    if extra or missing:
        raise ValueError(f"hem.type={kind!r}: missing {sorted(missing)}, unused {sorted(extra)}.")
    flip = raw.get("flip", before["flip"])
    position = raw.get("bend_position", before["bend_position"])
    if type(flip) is not bool:
        raise ValueError(f"hem.flip={flip!r} must be boolean.")
    if position not in _sheet_common._POSITIONS:
        raise ValueError(f"hem.bend_position={position!r}; use start_edge or tangent_to_side.")
    values, public = {}, {}
    for name in dimensions:
        requested = raw[name]
        if name == "angle_deg":
            if (isinstance(requested, bool) or not isinstance(requested, (int, float))
                    or not math.isfinite(requested) or not 0 < requested <= 360):
                raise ValueError(f"hem.angle_deg={requested!r} must be finite and in (0,360].")
            value = math.radians(requested)
            text = format(Decimal(str(requested)), "f")
            expression = (text.rstrip("0").rstrip(".") if "." in text else text) + " deg"
        else:
            if not _inputs.looks_like_expression(requested):
                raise ValueError(f"hem.{name}={requested!r} needs a length expression, e.g. '9 mm'.")
            _, value, reason = _inputs.length_value_input(requested, 1, design, f"hem.{name}")
            if reason:
                raise ValueError(reason)
            expression = requested.strip()
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError(f"hem.{name}={requested!r} must evaluate to a finite positive value.")
        values[name] = round(value, 12)
        public[name] = {"expression": expression}
    state = {"type": kind, "flip": flip, "bend_position": position, "dimensions": values,
             "expressions": {name: _param_common._normalized_expression(row["expression"])
                             for name, row in public.items()}}
    return {"type": kind, "flip": flip, "bend_position": position, "dimensions": public}, state


def write_hem(feature, payload):
    """Rebuild one Hem from its expressions, preserving or restoring the requested flip and position."""
    kind = payload["type"]
    arguments = [adsk.core.ValueInput.createByString(payload["dimensions"][name]["expression"])
                 for name in _sheet_common._KIND_SPEC[kind][0]]
    position = getattr(adsk.fusion.BendPositionTypes, _sheet_common._POSITIONS[payload["bend_position"]])
    if getattr(feature, _METHODS[kind])(*arguments, payload["flip"], position) is not True:
        raise RuntimeError(f"Fusion did not confirm the {kind} Hem rebuild.")
