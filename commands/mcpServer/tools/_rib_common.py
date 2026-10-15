# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Rib/Web body witnesses and passive definition records."""

from . import _common, _geom

MAP_BLURB = "body_census/rib_definition - owner-local shape witnesses and passive Rib/Web definitions."


def body_census(component):
    """Return all owner-local body shapes keyed by native identity, or None when incomplete."""
    collection = _common.safe(lambda: component.bRepBodies)
    count = _common.counted(lambda: collection.count)
    if count is None or count > 200:
        return None
    rows = {}
    for index in range(count):
        body = _common.safe(lambda index=index: collection.item(index))
        key = _common.native_identity(body)
        shape = _geom.body_shape(body)
        if key is None or key in rows or shape is None:
            return None
        rows[key] = shape
    return rows


def rib_definition(feature, factor):
    """Return a passive Rib/Web definition, marking each field that did not read."""
    from ._edit_feature_common import _definition_profile
    unavailable = {}

    def read(key, getter):
        value, reason = _common.read_optional(getter)
        if reason:
            unavailable[key] = reason
        return value

    thickness = read("thickness", lambda: feature.thickness)
    try:
        depth = feature.depth
    except Exception as exc:
        depth = None
        unavailable["depth"] = str(exc) or type(exc).__name__
    curves = read("curves", lambda: list(feature.curves))
    valid_curves = curves is not None
    out = {"thickness": _common.measured(lambda: thickness.value, factor),
           "thickness_expression": _common.safe(lambda: thickness.expression),
           "depth": _common.measured(lambda: depth.value, factor),
           "depth_expression": _common.safe(lambda: depth.expression),
           "extent_type": read("extent_type", lambda: int(feature.extentType)),
           "symmetric": read("symmetric", lambda: feature.isSymmetric),
           "flip": read("flip", lambda: feature.isFlipped),
           "curve_count": len(curves) if valid_curves else None,
           "curves": [_definition_profile(curve) for curve in curves[:64]] if valid_curves else None,
           "curves_truncated": len(curves) > 64 if valid_curves else None,
           "unavailable": unavailable}
    if _common.safe(lambda: feature.objectType) == "adsk::fusion::WebFeature":
        out["extend"] = read("extend", lambda: feature.isExtended)
    if unavailable:
        out["note"] = ("For operands needing rollback: design_edit_timeline(action='roll', feature=<this feature>, "
                       "to='before'), read the definition, then restore the prior timeline position.")
    return out
