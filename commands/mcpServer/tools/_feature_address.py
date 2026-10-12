# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Timeline feature addresses shared by reads and typed references."""

from ._read_primitives import safe

MAP_BLURB = "candidate_address/feature_address - timeline addresses for typed references and failed-write remedies."


def _owner_component_name(obj):
    """The component owning this timeline object's feature - the qualifier a 'component/feature'
    address resolves against, and what an ambiguous bare name's candidates are named with."""
    ent = safe(lambda: obj.entity)
    if ent is None:
        return None
    comp = safe(lambda: ent.parentComponent)
    # A construction datum carries no parentComponent; its owner reads off .component.
    if comp is None and "Construction" in (safe(lambda: ent.objectType) or ""):
        comp = safe(lambda: ent.component)
    return safe(lambda: comp.name) if comp is not None else None



def _index_of(obj):
    """A timeline object's own index, or None when it does not read."""
    return safe(lambda: obj.index)



def candidate_address(obj):
    """The address a refusal prints for a timeline object, '[<component>/]<name>@<index>', or None."""
    name = (safe(lambda: obj.name) or "").strip()
    index = _index_of(obj)
    if not name or not isinstance(index, int) or isinstance(index, bool):
        return None
    comp = (_owner_component_name(obj) or "").strip()
    return f"{comp}/{name}@{index}" if comp else f"{name}@{index}"



def feature_address(entity):
    """The address design_delete_feature takes for `entity`'s timeline row, else its name, else None."""
    if not entity:
        return None
    return (candidate_address(safe(lambda: entity.timelineObject))
            or safe(lambda: entity.name) or None)
