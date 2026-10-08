# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Shared substrate for the pattern tools: what gets patterned (bodies or occurrences), which
component the feature must be built in, and the direction/axis entity resolved into that component.
"""

import adsk.core
import adsk.fusion

from ._common import safe
from . import _inputs, _common

MAP_BLURB = (
    "the pattern substrate: _resolve_input_entities - the ObjectCollection a pattern seeds from, "
    "bodies taking precedence over occurrences; _owning_component - the component the feature must "
    "be built in (the axis and the feature must share one or Fusion raises getObjectPath); "
    "_direction_entity - a world-axis key as that component's own origin axis, anything else "
    "lifted into its assembly context")

_BODIES = _inputs.BodyRefList("bodies", required=False)

_OCCURRENCES = _inputs.OccurrenceRefList("occurrences", required=False,
                                         description="Or 'bodies'.")

_FEATURES = _inputs.FeatureRefList("features", description=
    "Unique timeline PartFeature selectors; use only this seed kind.")
_FACES = _inputs.GeometryHandleList("faces", require="face", json_array=True, description=
    "Unique BRepFace handles from find_geometry; use only this seed kind.")


def _seed_property(kind):
    """Return the strict list property for one new pattern seed kind."""
    schema = kind.schema(brief=True)
    schema.update(minItems=1, uniqueItems=True)
    return kind.name, schema


def _seed_kind(occurrences, bodies, features=None, faces=None):
    """Return the selected seed family, preserving legacy body precedence."""
    if features not in (None, "", []):
        return "features"
    if faces not in (None, "", []):
        return "faces"
    return "bodies" if bodies not in (None, "", []) else "occurrences"


def _resolve_input_entities(design, occurrences, bodies, features=None, faces=None):
    """Return a homogeneous pattern seed collection, labels and refusal."""
    if features not in (None, "", []) or faces not in (None, "", []):
        supplied = [key for key, value in (("features", features), ("faces", faces),
                    ("bodies", bodies), ("occurrences", occurrences)) if value not in (None, "", [])]
        if len(supplied) != 1:
            return None, None, (f"Pattern seed inputs {', '.join(supplied)} conflict. "
                                "Supply only one of features, faces, bodies or occurrences.")
        key = supplied[0]
        raw = features if key == "features" else faces
        if not isinstance(raw, list) or not raw or any(not isinstance(v, str) or not v.strip() for v in raw):
            return None, None, f"'{key}' must be a nonempty JSON array of unique selectors."
        found, err = (_FEATURES if key == "features" else _FACES).resolve(raw)
        if err:
            return None, None, err
        ents, labels = found if key == "features" else (found, list(raw))
        native = [_common._native_of(e) for e in ents]
        owners = [safe(lambda e=e: e.parentComponent) if key == "features"
                  else safe(lambda e=e: e.body.parentComponent) for e in native]
        for i, ent in enumerate(native):
            if key == "features" and not _inputs._isinstance(ent, adsk.fusion.Feature):
                return None, None, (f"'features'[{i}] '{raw[i]}' is not a modeling feature. "
                                    "Use a PartFeature from design_get(include=['timeline']).")
            if any(ent == prior for prior in native[:i]):
                return None, None, f"'{key}'[{i}] '{raw[i]}' resolves to a repeated seed; list each entity once."
            if owners[i] is None or _common.same_component(owners[0], owners[i]) is not True:
                return None, None, f"'{key}'[{i}] '{raw[i]}' must have the same readable owning component as the first seed."
            if key == "features" and safe(lambda e=ent: e.bodies.count) in (None, 0):
                return None, None, f"'features'[{i}] '{raw[i]}' has no readable result bodies to pattern; use a body or face seed."
        coll = adsk.core.ObjectCollection.create()
        for ent in native:
            coll.add(ent)
        return coll, labels, None
    if bodies not in (None, "", []):
        ents, berr = _BODIES.resolve(bodies)
        if berr:
            return None, None, berr
        coll = adsk.core.ObjectCollection.create()
        for b in ents:
            coll.add(b)
        if coll.count == 0:
            return None, None, "No valid bodies resolved to pattern."
        return coll, [safe(lambda b=b: b.name) for b in ents], None

    occs, oerr = _OCCURRENCES.resolve(occurrences)
    if oerr:
        return None, None, oerr
    if not occs:
        return None, None, ("Provide 'occurrences' (occurrence name(s)) or 'bodies' (body "
                            "handles/names) to pattern.")
    coll = adsk.core.ObjectCollection.create()
    for o in occs:
        coll.add(o)
    return coll, [safe(lambda o=o: o.name) for o in occs], None


def _direction_key(kind, raw):
    """The direction as the caller gave it, falling back to the kind's default for a blank."""
    return raw if isinstance(raw, str) and raw.strip() else kind.default


def _in_context(kind, ent, comp, design):
    """(entity, error) - the direction entity in a form the pattern's component can consume."""
    occ, err = _inputs.single_placement(f"'{kind.name}': that direction", ent, comp, design)
    if err:
        return None, err
    if occ is None:
        return ent, None
    proxy = safe(lambda: ent.createForAssemblyContext(occ))
    if proxy is None:
        path = safe(lambda: occ.fullPathName) or "its one occurrence"
        return None, (f"'{kind.name}': that direction could not be brought into the pattern's "
                      f"assembly context ({path}). Pass a handle at geometry in the pattern's own "
                      "component, or a world axis (x/y/z).")
    return proxy, None


def _direction_entity(kind, raw, comp, design):
    """(entity, error) for one direction/axis input: a world-axis key becomes `comp`'s own origin
    ConstructionAxis, anything else the resolved entity in `comp`'s assembly context."""
    key = _direction_key(kind, raw)
    tagged, err = kind.resolve(key)
    if err:
        return None, err
    if tagged and tagged[0] == "edge":
        return _in_context(kind, tagged[1], comp, design)
    ent = _inputs.world_construction_axis(comp, key)
    if ent is None:
        return None, (f"'{kind.name}': component '{safe(lambda: comp.name)}' has no {key} origin "
                      "construction axis. Pass a find_geometry handle at a straight edge or sketch "
                      "line instead.")
    return ent, None


def _direction_label(kind, raw, ent):
    """What the direction/axis RESOLVED to, for the payload: the world-axis key, else the entity's
    own name falling back to its type - a BRepEdge and a SketchLine carry no name."""
    key = _direction_key(kind, raw)
    if key.lower() in _inputs.WORLD_AXIS_ATTRS:
        return key.lower()
    name = safe(lambda: ent.name)
    return name if isinstance(name, str) and name else type(ent).__name__


def _owning_component(design, coll, bodies, features=None, faces=None):
    """Return the seed owner, refusing unreadable feature/face ownership."""
    root = safe(lambda: design.rootComponent)
    if any(raw not in (None, "", []) for raw in (bodies, features, faces)):
        first = safe(lambda: coll.item(0))
        parent = (safe(lambda: first.body.parentComponent) if faces not in (None, "", [])
                  else safe(lambda: first.parentComponent)) if first is not None else None
        if parent is not None:
            return parent
        if features not in (None, "", []) or faces not in (None, "", []):
            return None
    return root


def _seed_shapes(coll, kind):
    """Return the owner and strict body-shape baseline for feature/face patterns."""
    if kind not in ("features", "faces"):
        return None, None
    from . import _edit_feature_common
    first = safe(lambda: coll.item(0))
    owner = (safe(lambda: first.body.parentComponent) if kind == "faces"
             else safe(lambda: first.parentComponent))
    if owner is None:
        return None, "Pattern seed owner did not read; reacquire its feature or face before retrying."
    shapes = _edit_feature_common.all_shapes(_common.design(), components=[owner])
    if not shapes:
        return None, "Pattern seed body geometry did not read; inspect it with model_inspect before retrying."
    return (owner, shapes), None


def _seed_effect(feature, before):
    """Return the observed body-shape change or a post-write refusal."""
    if before is None:
        return {}, None
    from . import _edit_feature_common
    owner, shapes = before
    after = _edit_feature_common.all_shapes(_common.design(), components=[owner])
    if after is None:
        reason = "result geometry did not read"
    elif after == shapes:
        reason = "body geometry did not change"
    else:
        return {"pattern_geometry_changed": True}, None
    return None, (f"Pattern '{safe(lambda: feature.name)}' was created, but {reason}. "
                  "Inspect with model_inspect; design_delete_feature removes the retained feature.")
