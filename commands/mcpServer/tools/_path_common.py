# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Path construction from resolved entities and sketch selectors."""

import adsk.core

from . import _common

MAP_BLURB = "build_sketch_path/build_edge_path - resolved path construction; path_sketch_curve_count/path_chain_warning - sketch omissions."


def build_sketch_path(comp, path_raw, left_out=None, curve_id=None):
    """Return (path, label, error) for a sketch selector and optional omitted-curve reader."""
    nm = path_raw.split(":", 1)[1].strip()
    sk, _ = _common.target_sketch(comp, nm)
    if not sk:
        return None, None, f"No sketch named '{nm}' for the path. Use sketch_get or sketch_create."
    curves = _common.safe(lambda: sk.sketchCurves)
    cn = _common.safe(lambda: curves.count, 0) if curves else 0
    if not cn:
        return None, None, f"Path sketch '{nm}' has no curves to build a path from."
    # The collection preserves separately drawn curves; a filleted chain can omit its exit leg.
    selected = [c for c in _common.iter_collection(curves)
                if not bool(_common.safe(lambda c=c: c.isConstruction, False))]
    if not selected:
        return None, None, f"Path sketch '{nm}' has no non-construction curves."
    coll = adsk.core.ObjectCollection.create()
    for c in selected:
        coll.add(c)
    intended = [_common.native_identity(c) for c in selected]
    known = None not in intended and len(set(intended)) == len(selected)

    def members(path):
        """The native identities of a built path's members, None when any does not read."""
        n = _common.counted(lambda: path.count)
        keys = ([_common.native_identity(_common.safe(lambda i=i: path.item(i).entity)) for i in range(n)]
                if n is not None else [None])
        return None if None in keys else keys

    p = None
    if _common.safe(lambda: coll.count, 0):
        try:
            built = comp.features.createPath(coll, False)
        except Exception:
            built = None
        if built is not None and (_common.counted(lambda: built.count) or 0) > 0:
            p = built
    if p is None or (_common.counted(lambda: p.count) or 0) < len(selected):
        try:
            candidate = comp.features.createPath(selected[0], True)
        except Exception as e:
            if p is None:
                return None, None, f"Could not build a path from sketch '{nm}': {e}"
            candidate = None
        got = members(candidate) if candidate is not None else None
        if p is None:
            p = candidate
        elif (known and got is not None and len(got) == len(selected)
              and set(got) == set(intended)):
            p = candidate
    if not p:
        return None, None, f"createPath returned nothing for sketch '{nm}'."
    got = (members(p) if left_out is not None and known
           and (_common.counted(lambda: p.count) or 0) < len(selected) else None)
    if got is not None:
        left = [curve_id(sk, c) for c, key in zip(selected, intended)
                if key not in got]
        if None not in left:
            left_out.extend(left)
    return p, f"sketch:{nm}", None




def build_edge_path(comp, edges):
    """Return (path, label, error) for already resolved edge entities."""
    if len(edges) == 1:
        try:
            p = comp.features.createPath(edges[0], True) # request chaining from the seed edge
        except Exception as e:
            return None, None, f"Could not build a path from the edge: {e}"
    else:
        coll = adsk.core.ObjectCollection.create()
        for e in edges:
            coll.add(e)
        try:
            # Multiple edges: use them exactly (noChainedCurves); they must connect into one path.
            p = comp.features.createPath(coll, False)
        except Exception as e:
            return None, None, f"Could not build a path from the {len(edges)} edges: {e}"
    if not p:
        return None, None, "Path build returned nothing (the edges may not connect into one path)."
    # MEASURED behind the tangent rule: an arc seed between two tangent lines built a 3-entity
    # path, a tangent-continuous closed loop chained all 8 of its edges from one seed, and a sharp
    # corner stopped it - open vs closed does not decide it.
    built = _common.safe(lambda: int(p.count), 0) or 0
    how = ("from 1 seed handle" if len(edges) == 1
           else f"from {len(edges)} handles, used exactly")
    return p, (f"{built} edge(s) {how}" if built else f"{how}; edge count unreadable"), None



def path_sketch_curve_count(comp, path_raw):
    """How many SWEEPABLE (non-construction) curves the sketch a 'sketch:<name>' path names holds -
    None for any other path form or an unreadable sketch."""
    if not (isinstance(path_raw, str) and path_raw.strip().lower().startswith("sketch:")):
        return None
    sk, _ = _common.target_sketch(comp, path_raw.split(":", 1)[1].strip())
    if sk is None:
        return None
    curves = _common.safe(lambda: sk.sketchCurves)
    if _common.counted(lambda: curves.count) is None:
        return None
    return sum(1 for c in _common.iter_collection(curves) if not bool(_common.safe(lambda c=c: c.isConstruction, False)))



def path_chain_warning(path_curves, sketch_curves, action, left=()):
    """The WARNING for a path short of its sketch's curves, naming the `left` ids; '' when none is."""
    if path_curves is None or sketch_curves is None or path_curves >= sketch_curves:
        return ""
    named = f" Not in the path: {_common.named_with_remainder(list(left))}." if left else ""
    return (f"WARNING: the path chained {path_curves} of the sketch's {sketch_curves} curves, so "
            f"the {action} covers only that run.{named} sketch_get lists the curves; one connected "
            "run drawn out of order is redrawn in chain order; several runs go in separate path "
            "sketches.")
