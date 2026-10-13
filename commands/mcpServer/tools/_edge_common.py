# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Shared substrate for the edge-treatment tools (fillet, chamfer): the edge set they act on, the
per-edge convexity a filter selects by, and the one apply path that builds the feature and proves it
moved material.
"""

import math
import re

import adsk.core
import adsk.fusion

from ._common import error, ok, safe, scale
from . import _common
from . import _geom
from . import _inputs

MAP_BLURB = (
    "EDGES/FACES/BODY/_EDGE_FILTER_DESC/_TANGENT_CHAIN_DESC - targeting; _edges_of_faces - face "
    "edges; _distinct_placed_edges - edge handles per placement; _edge_convexity/"
    "_collect_edges - dihedral filters; _tangent_chain_read - applied chain; _cut_edges - resolved "
    "count via rolled_to; _apply - build and verify volume/area")

# Edge-handle-list input (closes the 'fillet THESE specific edges' gap; takes precedence over edge_filter).
_EDGES = _inputs.GeometryHandleList("edges", require="edge",
                                    description="Overrides 'edge_filter'.")
# Body input: a find_geometry handle (precise) OR a name; resolved/kind-checked by BodyRef.
_BODY = _inputs.BodyRef("body_name", kind="solid", required=False,
                        description="Omit = most recent.")
# Face-scoped targeting: the EDGES of the named faces. A chamfer has no rule-fillet twin, so the
# face set is expanded to its edges here rather than handed to a rule API.
_FACES = _inputs.GeometryHandleList("faces", require="face", required=False,
    description="Every edge of these faces; excludes 'edges'.")

# option key -> the API's OWN ChamferCornerTypes member spelling, lowercase 't' in BlendCornertype
# included: no BlendCornerType member exists, so a "corrected" name would getattr-raise and be
# reported as unavailable rather than silently beveling with the default corner.
_CORNER_TYPES = {"chamfer": "ChamferCornerType", "miter": "MiterCornerType",
                 "blend": "BlendCornertype"}

# The isFlipped a two-distance or distance-and-angle chamfer edge set is built with; the wire has
# no input that swaps the two sides.
_CHAMFER_FLIPPED = False

# edge_filter caveat (shared by both tools): convex/concave classify each edge by its LOCAL dihedral
# only, so on a plate with holes every hole rim matches exactly like the outer perimeter - the filter
# cannot mean "outer edges only". The 'edges' handle list is the precise path when the set matters.
_EDGE_FILTER_DESC = "Required without 'edges': the body's edges by dihedral."

# True is the platform's own default and SEEDS from the handles: one edge of a tangent-continuous
# rim cut the whole rim (1 handle -> 8 edges resolved, measured). False cuts the handles alone.
_TANGENT_CHAIN_DESC = "False cuts only the handles given."

# How close to parallel two out-of-material normals may read and still meet smoothly, which is
# neither convex nor concave. Vectors carry 12 decimals: at 6 the dot quantizes in steps of 1e-6,
# coarser than the 3.8e-7 this band leaves below 1.0, so the band has no room to exist there.
_DIHEDRAL_TOL_DEG = 0.05
_SMOOTH_JOIN_COS = math.cos(math.radians(_DIHEDRAL_TOL_DEG))
_VECTOR_DECIMALS = 12

# The ways an edge comes back with no convex/concave answer, named so a refusal says which happened
# rather than asserts a cause.
_UNCLASSIFIED = ("unreadable", "disagreed", "knife")


def _distinct_placed_edges(edges, root):
    """Keep each readable native edge and placed path once, retaining unknown identities."""
    out, seen = [], set()
    unread = object()
    for edge in edges:
        native = _common.native_identity(edge)
        context = safe(lambda: edge.assemblyContext, unread)
        path = safe(lambda: context.fullPathName) if context is not None and context is not unread else None
        if not isinstance(path, str) or not path:
            path = None
        if context is None:
            owner = safe(lambda: edge.body.parentComponent)
            identity = _common.native_identity(owner)
            if identity is not None:
                path = ("native", identity)
            elif _common.same_component(owner, root) is True:
                path = ""
        key = (native, path) if native is not None and isinstance(path, (str, tuple)) else None
        if key is None or key not in seen:
            out.append(edge)
            if key is not None:
                seen.add(key)
    return out


def _size_hint(platform_text: str, size_key: str) -> str:
    """The retry hint for an add() raise, gated on the platform's own text: an unconditional
    'try a smaller value' sent agents into shrink-and-retry loops against failures (tangent-chain
    conflicts) that no size fixes."""
    if re.search(r"too large|self.?intersect|radius|distance", platform_text, re.IGNORECASE):
        return f" (The {size_key} may be too large for the geometry - try a smaller value.)"
    return (" (The platform text above is the only measured cause - check the edges are genuine "
            "corners and any chain is tangentially connected; the size is not necessarily the "
            "problem.)")


def _qualified_body_name(body):
    """The body's name qualified with the occurrence path it lives in, so two same-named bodies in
    different components are distinguishable in the report - unqualified, two chamfers on two
    components both report the same local 'Body1'. Reuses _inputs._body_context - the shared 'where
    this body lives' idiom (assemblyContext.fullPathName, else the owning component name)."""
    if body is None:
        return None
    name = safe(lambda: body.name)
    ctx = _inputs._body_context(body)
    if name and ctx and ctx not in ("?", name):
        return f"{ctx}/{name}"
    return name


def _edge_tangent(edge, point):
    """The edge's unit tangent AT `point`, pointing along the EDGE, or None."""
    # The evaluator follows the CURVE; isParamReversed says whether the edge runs against it. An
    # uncorrected tangent negates the heading the sign is read off, flipping the verdict with
    # nothing to catch it.
    against = _common.read_flag(lambda: edge.isParamReversed)
    ev = safe(lambda: edge.evaluator)
    at = safe(lambda: ev.getParameterAtPoint(point)) if ev is not None else None
    if against is None or not (isinstance(at, (list, tuple)) and len(at) == 2 and at[0]):
        return None
    got = safe(lambda: ev.getTangent(at[1]))
    if not (isinstance(got, (list, tuple)) and len(got) == 2 and got[0]):
        return None
    tangent = _geom.unit_vector(got[1], decimals=_VECTOR_DECIMALS)
    if tangent is None:
        return None
    return tuple(-c for c in tangent) if against else tuple(tangent)


def _coedge_side(coedge, point):
    """(the out-of-material normal at `point` of the face this coEdge bounds, whether the coEdge runs
    against the edge's own direction), or None where either did not read."""
    face = safe(lambda: coedge.loop.face)
    opposed = _common.read_flag(lambda: coedge.isOpposedToEdge)
    normal = _geom.evaluator_normal_at(face, point, decimals=_VECTOR_DECIMALS)
    if normal is None or opposed is None:
        return None
    return normal, opposed


def _edge_convexity(edge):
    """'convex' | 'concave' | 'smooth', or one of _UNCLASSIFIED - BRepEdge exposes no convexity flag,
    so one edge's dihedral is signed here from reads taken AT a point on it."""
    # The geometric fact, entirely LOCAL to that point: cross(n, h) is the in-face direction leading
    # away from the edge, h being the coEdge's own heading round its face. It leans ALONG the other
    # face's out-of-material normal when the material fills the reflex wedge - that is concave.
    coedges = list(_common.iter_collection(safe(lambda: edge.coEdges)))
    point = safe(lambda: edge.pointOnEdge)
    if len(coedges) != 2 or point is None:
        return "unreadable"
    tangent = _edge_tangent(edge, point)
    sides = [_coedge_side(c, point) for c in coedges]
    if tangent is None or any(s is None for s in sides):
        return "unreadable"
    cosine = _geom.dot(sides[0][0], sides[1][0])
    if cosine > _SMOOTH_JOIN_COS:
        return "smooth"
    # Two out-of-material normals pointing at each other bound a knife edge or a crack - no material
    # wedge, so there is no dihedral to sign.
    if cosine < -_SMOOTH_JOIN_COS:
        return "knife"
    # The two coEdges run OPPOSITE ways round one edge, so either one answers for the pair. Two
    # reporting the same isOpposedToEdge cannot both be right, and nothing is signed off them.
    if sides[0][1] == sides[1][1]:
        return "disagreed"
    normal, opposed = sides[0]
    heading = tuple(-c for c in tangent) if opposed else tangent
    return "concave" if _geom.dot(_geom.cross(normal, heading), sides[1][0]) > 0 else "convex"


def _census_phrase(census):
    """The dihedral split as one ASCII clause - the same three the payload publishes."""
    return f"{census['convex']} convex, {census['concave']} concave, {census['smooth']} smooth"


def _unclassified(census):
    """How many edges got no convex/concave answer, over the three ways that happens."""
    return sum(census[k] for k in _UNCLASSIFIED)


def _unclassified_phrase(census):
    """Which unclassified branches actually occurred - a branch that did not happen is not named."""
    return ", ".join(f"{census[k]} {k}" for k in _UNCLASSIFIED if census[k])


def _edges_of_faces(faces):
    """Every edge of `faces`, each ONCE - two faces in one list share their common edge, and the
    same edge twice in a feature's edge set is a duplicate. An edge whose token will not read is
    kept, since nothing there tells it from another."""
    out, seen = [], set()
    for f in faces:
        for e in _common.iter_collection(safe(lambda f=f: f.edges)):
            key = safe(lambda e=e: e.entityToken)
            if key:
                if key in seen:
                    continue
                seen.add(key)
            out.append(e)
    return out


def _collect_edges(body, edge_filter):
    """(ObjectCollection of the body's edges matching 'edge_filter', the body's edge count, the
    per-edge census - None under 'all', which takes every edge and classifies none)."""
    flt = (edge_filter or "all").strip().lower()
    coll = adsk.core.ObjectCollection.create()
    edges = safe(lambda: body.edges)
    n = safe(lambda: edges.count, 0) if edges else 0
    if flt == "all":
        for e in _common.iter_collection(edges):
            coll.add(e)
        return coll, n, None
    census = dict.fromkeys(("convex", "concave", "smooth") + _UNCLASSIFIED, 0)
    for e in _common.iter_collection(edges):
        kind = _edge_convexity(e)
        census[kind] += 1
        if flt == kind:
            coll.add(e)
    return coll, n, census


def _build_edge_set(fillet_input, variant, edges, val, k, tangent_chain):
    """Add the requested edge set to a FilletFeatureInput. Returns an error string, or ''."""
    edge_inputs = fillet_input.edgeSetInputs
    if variant is None:
        added = edge_inputs.addConstantRadiusEdgeSet(edges, val, tangent_chain)
        label = "constant-radius"
    elif variant["type"] == "chord_length":
        added = edge_inputs.addChordLengthEdgeSet(edges, val, tangent_chain)
        label = "chord-length"
    else:
        # A variable-radius set is built with chaining off; its intermediate radii and positions
        # cross as plain Python lists (the API takes a vector there), radii first.
        added = edge_inputs.addVariableRadiusEdgeSet(
            edges, val, adsk.core.ValueInput.createByReal(variant["end_radius"] * k), False)
        label = "variable-radius"
        if added is not None and variant["positions"]:
            mid_result = added.setMidRadii(
                [adsk.core.ValueInput.createByReal(r * k) for r in variant["radii"]],
                [adsk.core.ValueInput.createByReal(p) for p in variant["positions"]])
            if mid_result is not True:
                return (f"The variable-radius edge set did not take its intermediate radii "
                        f"(setMidRadii returned {mid_result!r}), so no fillet was created. Check "
                        "'positions' and 'radii'.")
    if added is None:
        return (f"The {label} edge set was refused, so no fillet was created. Re-run find_geometry "
                "for fresh edge handles; a variable-radius chain must be tangentially connected "
                "and listed in order from its start end.")
    return ""


def _feature_key(feature):
    """A displayable identity captured before optional feature reads."""
    name = safe(lambda: feature.name)
    if isinstance(name, str) and name:
        return name
    token = safe(lambda: feature.entityToken)
    return token if isinstance(token, str) and token else None


def _retained_feature_remedy(feature_key, design=None, feature=None):
    """Explain how to inspect or remove a feature after a required readback fails."""
    label = f"'{feature_key}'" if feature_key else "whose identity did not read"
    removal = (_common.failed_effect_remedy(design, feature)
               if design is not None and feature is not None else
               "remove it with design_delete_feature after reviewing the partial result.")
    return f" The created feature {label} is retained; inspect it with design_get. {removal}"


def _length_spec(raw, units, design, label):
    """Resolve one positive finite fillet length to a ValueInput and measured centimeters."""
    k = scale(units)
    if k is None:
        return None, None, f"Unknown units '{units}'. Use mm, cm, or in."
    if isinstance(raw, bool):
        return None, None, f"'{label}' must be finite and positive, got {raw!r}."
    number = _common.finite_number(raw, text=True)
    if number is not None and number <= 0:
        return None, None, f"'{label}' must be finite and positive, got {raw!r}."
    if isinstance(raw, (int, float)) and number is None:
        return None, None, f"'{label}' must be finite and positive, got {raw!r}."
    value, cm, err = _inputs.length_value_input(raw, k, design, label)
    if err:
        return None, None, err
    cm = _common.finite_number(cm)
    if cm is None or cm <= 0:
        return None, None, f"'{label}' must evaluate to a finite positive length, got {cm!r} cm."
    return value, cm, None


def _input_weight_readback(edge_set_input):
    """Read tangencyWeight as the ValueInput it is, never as a parameter."""
    value_input = safe(lambda: edge_set_input.tangencyWeight)
    if value_input is None:
        return None
    value_type = safe(lambda: value_input.valueType)
    return {
        "object_type": safe(lambda: str(value_input.objectType)),
        "value_type": safe(lambda: int(value_type)) if value_type is not None else None,
        "real_value": _common.finite_number(safe(lambda: value_input.realValue)),
        "string_value": safe(lambda: str(value_input.stringValue)),
    }


def _edge_identities(edges):
    """Resolve a complete list of native edge identities, refusing incomplete identity evidence."""
    identities = [_common.native_identity(edge) for edge in edges]
    if not identities or any(identity is None for identity in identities):
        return None
    if len(set(identities)) != len(identities):
        return None
    return identities


def _strict_collection_items(collection, subject):
    """Read every counted collection member or refuse an incomplete native census."""
    if collection is None:
        raise ValueError(f"{subject} collection did not read")
    try:
        count = collection.count
    except Exception as exc:
        raise ValueError(f"{subject} count did not read: {exc}") from exc
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError(f"{subject} count is invalid: {count!r}")
    items = []
    for index in range(count):
        try:
            item = collection.item(index)
        except Exception as exc:
            raise ValueError(f"{subject} item {index} did not read: {exc}") from exc
        if item is None:
            raise ValueError(f"{subject} item {index} answered no object")
        items.append(item)
    return items


def _add_measured_edge_sets(fillet_input, design, variant, edges, val, size_cm, units, k,
                            tangent_chain, continuity, flipped, edge_sets):
    """Build measured regular fillet edge sets; return expected readback rows or an error."""
    edge_inputs = safe(lambda: fillet_input.edgeSetInputs)
    if edge_inputs is None:
        return None, "FilletFeatureInput.edgeSetInputs did not read; no fillet was created."
    if edge_sets is not None:
        requested = list(edge_sets)
    else:
        requested = [{"fillet_type": variant["type"] if variant else "constant",
                      "edges": list(_common.iter_collection(edges)), "radius": None,
                      "end_radius": None, "flipped": flipped,
                      "continuity": continuity, "tangent_chain": tangent_chain,
                      "value": val}]
    expected, all_seen, first_owner, preflight = [], set(), None, []
    # Validate the complete mixed collection before constructing even the first native input set.
    for index, spec in enumerate(requested):
        set_edges = list(spec.get("edges") or [])
        identities = _edge_identities(set_edges)
        if identities is None:
            return None, f"edge_sets[{index}] has unreadable or repeated native edge identity; reacquire its handles."
        if all_seen.intersection(identities):
            return None, f"edge_sets[{index}] overlaps an earlier edge set; sets must be disjoint."
        all_seen.update(identities)
        preflight.append(identities)
        for edge in set_edges:
            owner = safe(lambda edge=edge: edge.body.parentComponent)
            if owner is None:
                return None, f"edge_sets[{index}] has an unreadable owning component; reacquire its edges."
            if first_owner is None:
                first_owner = owner
            elif _common.same_component(first_owner, owner) is not True:
                return None, f"edge_sets[{index}] belongs to a different component; use one owning component per fillet."
    continuity_types = safe(lambda: adsk.fusion.SurfaceContinuityTypes)
    continuity_names = {"tangent": "TangentSurfaceContinuityType",
                        "curvature": "CurvatureSurfaceContinuityType"}
    for index, spec in enumerate(requested):
        kind = spec.get("fillet_type", "constant")
        set_edges = list(spec.get("edges") or [])
        identities = preflight[index]
        chain = spec.get("tangent_chain", tangent_chain)
        requested_continuity = spec.get("continuity", continuity)
        row = {"type": kind, "edges": set_edges, "identities": identities,
               "tangent_chain": chain, "continuity_requested": requested_continuity}
        if kind == "asymmetric":
            if edge_sets is None:
                # _apply's primary radius ValueInput is already resolved and tied to the caller's units.
                first_value, first_cm = val, size_cm
            else:
                first_value, first_cm, ferr = _length_spec(
                    spec.get("radius"), units, design, f"edge_sets[{index}].radius")
                if ferr:
                    return None, ferr
            second_raw = spec.get("end_radius") if edge_sets is not None else variant.get("end_radius")
            second_value, second_cm, serr = _length_spec(second_raw, units, design,
                                                          f"edge_sets[{index}].end_radius")
            if serr:
                return None, serr
            try:
                added = edge_inputs.addAsymmetricRadiusEdgeSet(
                    _object_collection(set_edges), first_value, second_value, chain)
            except Exception as exc:
                return None, f"Asymmetric edge set {index} was refused: {exc}"
            if added is None:
                return None, f"Asymmetric edge set {index} returned no input set; no feature was created."
            want_flip = spec.get("flipped", flipped)
            setter = safe(lambda: added._set_isFlipped)
            if setter is None:
                return None, f"Asymmetric edge set {index} has no readable flipped setter; no feature was created."
            try:
                set_result = setter(bool(want_flip))
            except Exception as exc:
                return None, f"Asymmetric edge set {index} refused flipped={bool(want_flip)}: {exc}"
            if set_result is not True:
                return None, f"Asymmetric edge set {index} setter returned {set_result!r} for flipped={bool(want_flip)}; no feature was created."
            got_flip = _common.read_flag(lambda: added.isFlipped)
            if got_flip is None or got_flip != bool(want_flip):
                return None, f"Asymmetric edge set {index} retained flipped={got_flip!r}, not {bool(want_flip)}; no feature was created."
            row.update({"offset_one_cm": first_cm, "offset_two_cm": second_cm,
                        "flipped_requested": bool(want_flip), "flipped_input": got_flip,
                        "tangency_weight_input": _input_weight_readback(added)})
        elif kind in ("constant", "variable"):
            if edge_sets is not None:
                value, radius_cm, verr = _length_spec(spec.get("radius"), units, design,
                                                       f"edge_sets[{index}].radius")
                if verr:
                    return None, verr
            else:
                value, radius_cm = val, size_cm
            try:
                if kind == "variable":
                    end_value, end_cm, end_err = _length_spec(variant["end_radius"], units, design,
                                                               "end_radius")
                    if end_err:
                        return None, end_err
                    added = edge_inputs.addVariableRadiusEdgeSet(
                        _object_collection(set_edges), value, end_value, chain)
                    positions = [adsk.core.ValueInput.createByReal(p) for p in variant["positions"]]
                    radii = [adsk.core.ValueInput.createByReal(r * k) for r in variant["radii"]]
                    if positions:
                        mid_result = added.setMidRadii(radii, positions) if added is not None else None
                        if mid_result is not True:
                            return None, f"Variable edge set {index} setMidRadii returned {mid_result!r}; no feature was created."
                    want_radii = [_common.finite_number(r * k) for r in variant["radii"]]
                    if any(r is None for r in want_radii):
                        return None, f"Variable edge set {index} has a non-finite intermediate radius."
                    row.update({"radius_cm": radius_cm, "end_radius_cm": end_cm,
                                "positions": list(variant["positions"]),
                                "radii_cm": want_radii})
                else:
                    added = edge_inputs.addConstantRadiusEdgeSet(
                        _object_collection(set_edges), value, chain)
                    row["radius_cm"] = radius_cm
            except Exception as exc:
                return None, f"{kind.capitalize()} edge set {index} was refused: {exc}"
            if added is None:
                return None, f"{kind.capitalize()} edge set {index} returned no input set; no feature was created."
            if requested_continuity is not None:
                enum_name = continuity_names.get(requested_continuity)
                want = safe(lambda: getattr(continuity_types, enum_name)) if continuity_types and enum_name else None
                setter = safe(lambda: added._set_continuity)
                if want is None or setter is None:
                    return None, f"{kind.capitalize()} edge set {index} cannot resolve the requested continuity; no feature was created."
                try:
                    set_result = setter(want)
                except Exception as exc:
                    return None, f"{kind.capitalize()} edge set {index} refused continuity '{requested_continuity}': {exc}"
                if set_result is not True:
                    return None, f"{kind.capitalize()} edge set {index} continuity setter returned {set_result!r}; no feature was created."
                got_continuity = safe(lambda: added.continuity)
                if got_continuity != want:
                    return None, f"{kind.capitalize()} edge set {index} retained continuity {got_continuity!r}, not {want}; no feature was created."
                row["continuity_input"] = got_continuity
            row["tangency_weight_input"] = _input_weight_readback(added)
        else:
            return None, f"Unsupported measured fillet edge set type '{kind}'."
        expected.append(row)
    return expected, None


def _object_collection(entities):
    """Create the Fusion collection form used by edge-set input constructors."""
    collection = adsk.core.ObjectCollection.create()
    for entity in entities:
        collection.add(entity)
    return collection


def _read_measured_edge_sets(design, feature, expected):
    """Read every created native set under the feature marker and compare it with its request."""
    feature_key = _feature_key(feature)
    if feature_key is None:
        return None, ("The created feature has no readable name or entity token."
                      + _retained_feature_remedy(None, design, feature))

    def read_sets():
        collection = feature.edgeSets
        count = collection.count
        if count != len(expected):
            raise ValueError(f"feature.edgeSets.count is {count}, expected {len(expected)}")
        rows = []
        for index, want in enumerate(expected):
            native = collection.item(index)
            kind = want["type"]
            if kind == "asymmetric":
                typed = safe(lambda: adsk.fusion.AsymmetricFilletEdgeSet.cast(native))
                if typed is None:
                    raise ValueError(f"edge set {index} is not a readable asymmetric set")
                param = typed
            elif kind == "variable":
                typed = safe(lambda: adsk.fusion.VariableRadiusFilletEdgeSet.cast(native))
                if typed is None:
                    raise ValueError(f"edge set {index} is not a readable variable-radius set")
                param = typed
            else:
                typed = safe(lambda: adsk.fusion.ConstantRadiusFilletEdgeSet.cast(native))
                if typed is None:
                    raise ValueError(f"edge set {index} is not a readable constant-radius set")
                param = typed
            actual_edges = _strict_collection_items(typed.edges, f"edge set {index} edges")
            actual_ids = _edge_identities(actual_edges)
            if actual_ids is None or set(actual_ids) != set(want["identities"]):
                raise ValueError(f"edge set {index} retained a different or unreadable edge identity set")
            wanted_by_id = dict(zip(want["identities"], want["edges"]))
            for actual_edge, identity in zip(actual_edges, actual_ids):
                actual_owner = safe(lambda edge=actual_edge: edge.body.parentComponent)
                wanted_owner = safe(lambda identity=identity: wanted_by_id[identity].body.parentComponent)
                if actual_owner is None or wanted_owner is None or _common.same_component(actual_owner, wanted_owner) is not True:
                    raise ValueError(f"edge set {index} retained an edge under a different or unreadable owner")
            got = {"type": kind, "edges_count": len(actual_edges), "edges_match": True}
            if kind == "asymmetric":
                one = safe(lambda: param.offsetOne.value)
                two = safe(lambda: param.offsetTwo.value)
                flip = _common.read_flag(lambda: param.isFlipped)
                for field, value, wanted in (("offset_one_cm", one, want.get("offset_one_cm")),
                                             ("offset_two_cm", two, want.get("offset_two_cm"))):
                    value = _common.finite_number(value)
                    wanted = _common.finite_number(wanted)
                    if value is None or wanted is None or abs(value - wanted) > 1e-6:
                        raise ValueError(f"edge set {index} {field} reads {value!r}, expected {wanted!r} cm")
                if flip is None or flip != want["flipped_requested"]:
                    raise ValueError(f"edge set {index} isFlipped reads {flip!r}, expected {want['flipped_requested']}")
                got.update({"offset_one_cm": one, "offset_two_cm": two, "flipped": flip,
                            "continuity_raw": safe(lambda: param.continuity),
                            "continuity_verified": False,
                            "tangency_weight_input": want.get("tangency_weight_input")})
            elif kind == "variable":
                start = safe(lambda: param.startRadius.value)
                end = safe(lambda: param.endRadius.value)
                if want.get("radius_cm") is None or want.get("end_radius_cm") is None:
                    raise ValueError(f"edge set {index} variable radii could not be evaluated before add")
                start = _common.finite_number(start)
                end = _common.finite_number(end)
                want_start = _common.finite_number(want.get("radius_cm"))
                want_end = _common.finite_number(want.get("end_radius_cm"))
                if start is None or want_start is None or abs(start - want_start) > 1e-6:
                    raise ValueError(f"edge set {index} start radius reads {start!r}, expected {want['radius_cm']!r} cm")
                if end is None or want_end is None or abs(end - want_end) > 1e-6:
                    raise ValueError(f"edge set {index} end radius reads {end!r}, expected {want['end_radius_cm']!r} cm")
                positions = safe(lambda: param.midPositions)
                radii = safe(lambda: param.midRadii)
                pos_parameters = _strict_collection_items(positions, f"edge set {index} midPositions")
                rad_parameters = _strict_collection_items(radii, f"edge set {index} midRadii")
                pos_values = [_common.finite_number(safe(lambda p=p: p.value))
                              for p in pos_parameters]
                rad_values = [_common.finite_number(safe(lambda r=r: r.value))
                              for r in rad_parameters]
                if pos_values != want.get("positions"):
                    raise ValueError(f"edge set {index} intermediate positions read {pos_values!r}, expected {want.get('positions')!r}")
                want_radii = want.get("radii_cm") or []
                if (len(rad_values) != len(want_radii)
                        or any(v is None or w is None or abs(v - w) > 1e-6
                               for v, w in zip(rad_values, want_radii))):
                    raise ValueError(f"edge set {index} intermediate radii do not match the request")
                got.update({"radius_cm": start, "end_radius_cm": end,
                            "positions": pos_values, "radii_cm": rad_values,
                            "continuity_raw": safe(lambda: param.continuity),
                            "tangency_weight_input": want.get("tangency_weight_input")})
                if want.get("continuity_requested") is not None:
                    continuity_value = safe(lambda: param.continuity)
                    if continuity_value != want.get("continuity_input"):
                        raise ValueError(f"edge set {index} continuity reads {continuity_value!r}, not the requested input value")
                    got["continuity_verified"] = True
                else:
                    got["continuity_verified"] = False
            else:
                radius = safe(lambda: param.radius.value)
                wanted_radius = want.get("radius_cm")
                radius = _common.finite_number(radius)
                wanted_radius = _common.finite_number(wanted_radius)
                if radius is None or wanted_radius is None or abs(radius - wanted_radius) > 1e-6:
                    raise ValueError(f"edge set {index} radius reads {radius!r}, expected {wanted_radius!r} cm")
                if wanted_radius is None:
                    raise ValueError(f"edge set {index} radius request value could not be evaluated")
                got.update({"radius_cm": radius, "continuity_raw": safe(lambda: param.continuity),
                            "tangency_weight_input": want.get("tangency_weight_input")})
                if want.get("continuity_requested") is not None:
                    continuity_value = safe(lambda: param.continuity)
                    if continuity_value != want.get("continuity_input"):
                        raise ValueError(f"edge set {index} continuity reads {continuity_value!r}, not the requested input value")
                    got["continuity_verified"] = True
                else:
                    got["continuity_verified"] = False
            chain = _common.read_flag(lambda: typed.isTangentChain)
            if chain is None or chain != bool(want["tangent_chain"]):
                raise ValueError(f"edge set {index} isTangentChain reads {chain!r}, not {bool(want['tangent_chain'])}")
            got["tangent_chain"] = chain
            rows.append(got)
        return rows

    try:
        rows, marker_clause = _common.rolled_to(design, feature, read_sets, "fillet edge-set readback")
    except Exception as exc:
        return None, (f"The created feature '{feature_key}' edge-set readback failed: {exc}."
                      + _retained_feature_remedy(feature_key, design, feature))
    if rows is None:
        return None, ("The created feature's edge-set readback did not complete."
                      + _retained_feature_remedy(feature_key, design, feature))
    if marker_clause:
        return None, (f"The created feature's edge-set readback completed but {marker_clause}."
                      + _retained_feature_remedy(feature_key, design, feature))
    return rows, None


def _tangent_chain_read(feature):
    """The tangent-chain flag READ BACK off the created feature, or None when it did not read."""
    # The first edge set answers it for a fillet and for a chamfer alike; the feature's own flag
    # reads true either way on both.
    return _common.read_flag(lambda: feature.edgeSets.item(0).isTangentChain)


def _cut_edges(design, feature):
    """(the edges the feature's own edge set RESOLVED to - what a seed handle chained INTO - and the
    clause for a timeline marker that did not come back where it stood). Either is None when there
    is nothing to report."""
    # That collection reads only with the marker immediately before the feature (otherwise "Didn't
    # roll editing feature back"), which is what the shared roll-and-restore owns.
    return _common.rolled_to(design, feature,
                             lambda: safe(lambda: feature.edgeSets.item(0).edges.count),
                             "the feature's edge set")


def _is_are(names):
    """' is' or ' are' for a list of field names, so a one-field note reads as a sentence."""
    return " is" if len(names) == 1 else " are"


def _distance_mismatch(got_cm, want_cm, k):
    """The refusal when the chamfer's own distance is not the one asked for, else '' - the ONE
    comparison both the angle definition and an expression-driven distance are judged by. A
    want_cm of None is an expression the units engine answered no number for: there is nothing to
    compare against, and the caller publishes the distance unconfirmed instead."""
    if want_cm is None or not isinstance(got_cm, float) or abs(got_cm - want_cm) <= 1e-6:
        return ""
    return (f"The chamfer was created but its distance reads back {round(got_cm / k, 6)}, "
            f"not the requested {round(want_cm / k, 6)}.")


def _chamfer_readback(feature, size_cm, k, angle, corner_key, as_expression=False):
    """(verified payload fields, unverified field names, error) read off the CREATED chamfer. A
    declined corner type leaves no trace anywhere else, and a distance-and-angle edge set carries
    .distance in CM and .angle in RADIANS, which the comparisons below convert to."""
    fields, unverified = {}, []
    if corner_key:
        cts = safe(lambda: adsk.fusion.ChamferCornerTypes)
        want = safe(lambda: getattr(cts, _CORNER_TYPES[corner_key])) if cts is not None else None
        got = safe(lambda: feature.cornerType)
        if want is None or got is None:
            unverified.append("corner_type")
        elif got != want:
            return fields, unverified, (
                f"The chamfer was created but its corner type reads back {got}, not the requested "
                f"'{corner_key}' ({want}) - the corner where several chamfered edges meet is not "
                "the one asked for.")
        else:
            fields["corner_type"] = corner_key
    if angle is None:
        if as_expression:
            # An expression is compared against the cm the units engine evaluated it to, so a
            # feature that took some other number is never reported as the expression asked for.
            edge_set = safe(lambda: feature.edgeSets.item(0))
            got = safe(lambda: edge_set.distance.value) if edge_set is not None else None
            derr = _distance_mismatch(got, size_cm, k)
            if derr:
                return fields, unverified, derr
            if isinstance(got, float) and size_cm is not None:
                fields["distance"] = round(got / k, 6)
            else:
                unverified.append("distance")
        return fields, unverified, ""

    # The edge set's own type names WHICH definition got built: a distance-and-angle chamfer that
    # silently fell back to an equal-distance one would still read back a plausible distance.
    edge_set = safe(lambda: feature.edgeSets.item(0))
    want_type = safe(lambda: adsk.fusion.DistanceAndAngleChamferEdgeSet.classType())
    got_type = safe(lambda: edge_set.objectType) if edge_set is not None else None
    if want_type is None or got_type is None:
        unverified.append("chamfer_type")
    elif got_type != want_type:
        return fields, unverified, (
            f"The chamfer was created but Fusion reports its definition as chamfer type {got_type}, "
            f"not the distance-and-angle type ({want_type}) that was requested.")

    got_angle = safe(lambda: edge_set.angle.value) if edge_set is not None else None
    got_dist = safe(lambda: edge_set.distance.value) if edge_set is not None else None
    if isinstance(got_angle, float):
        deg = math.degrees(got_angle)
        if abs(deg - angle) > 1e-6:
            return fields, unverified, (
                f"The chamfer was created but its angle reads back {round(deg, 6)} deg, not the "
                f"requested {round(angle, 6)}.")
        fields["angle_deg"] = round(deg, 6)
    else:
        unverified.append("angle_deg")
    if isinstance(got_dist, float) and size_cm is not None:
        derr = _distance_mismatch(got_dist, size_cm, k)
        if derr:
            return fields, unverified, derr
        fields["distance"] = round(got_dist / k, 6)
    else:
        unverified.append("distance")
    return fields, unverified, ""


def _apply(kind, body_name, size, units, edge_filter, edge_handles=None, distance_two=0.0,
           variant=None, angle=None, corner_key=None, face_handles=None, tangent_chain=True,
           continuity=None, flipped=False, edge_sets=None):
    vtype = variant["type"] if variant else "constant"
    size_key = ("distance" if kind == "chamfer"
                else "chord_length" if vtype == "chord_length" else "radius")
    k = scale(units)
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    # A fillet RADIUS and a chamfer DISTANCE may arrive as a parameter EXPRESSION string
    # ('WallT/2'); a chord_length stays literal, its read-back comparing against that number. Only a
    # LITERAL is judged this early, before the design that resolves an expression is in hand.
    takes_expression = size_key in ("radius", "distance")
    as_expression = takes_expression and _inputs.looks_like_expression(size)
    sz = None
    if not as_expression:
        try:
            sz = float(size)
        except Exception:
            return error(f"'{size_key}' must be a number"
                         + (" or a parameter-expression string like 'WallT/2'."
                            if takes_expression else "."))
        if sz <= 0:
            return error(f"Provide a positive {size_key}.")

    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")
    comp = _common.target_component(design)
    # One ValueInput for both forms: a literal scaled to internal cm, an expression crossing as a
    # string once the units engine evaluated it, so an unresolvable one is refused BY NAME. The
    # evaluated cm puts an expression under the same positivity guard a literal gets.
    val, size_cm, verr = _inputs.length_value_input(size, k, design, size_key)
    if verr:
        return error(verr)
    if as_expression and size_cm is not None and size_cm <= 0:
        return error(f"Provide a positive {size_key}: the expression '{str(size).strip()}' "
                     f"evaluates to {round(size_cm / k, 6)} {units}.")
    # How the refusals below name the size: an expression as itself (it carries its own units), a
    # literal as the number plus the caller's units.
    size_text = f"'{str(size).strip()}'" if as_expression else f"{sz} {units}"

    edge_src = "filter"
    body_label = None
    census = None
    faces_selected = None
    handles_sent = None
    measured_route = kind == "fillet" and (
        edge_sets is not None or continuity is not None
        or (variant is not None and variant.get("type") == "asymmetric"))
    if measured_route and edge_sets is None:
        if isinstance(size, bool) or _common.finite_number(size_cm) is None or size_cm <= 0:
            return error(f"'{size_key}' must resolve to a finite positive length before creating the measured fillet.")
    want_faces = face_handles not in (None, "", [])
    if want_faces and edge_handles not in (None, "", []):
        return error("Pass 'faces' or 'edges', not both: 'faces' works on every edge of the named "
                     "faces, 'edges' uses the supplied edge handles as seeds.")
    # 'edges' (a GeometryHandleList of edge handles) takes precedence - closes the
    # 'fillet THESE specific edges' gap. The kind resolves+validates each handle to a BRep edge.
    blanket_note = None
    if edge_sets is not None:
        all_edges = [edge for spec in edge_sets for edge in spec.get("edges", [])]
        if not all_edges:
            return error("'edge_sets' contains no resolved edges; reacquire the edge handles.")
        edge_ids = _edge_identities(all_edges)
        if edge_ids is None or len(set(edge_ids)) != len(edge_ids):
            return error("'edge_sets' contains unreadable or repeated edge identity; reacquire disjoint edges.")
        edges = _object_collection(all_edges)
        handles_sent = len(all_edges)
        edge_src = f"{len(all_edges)} edge(s) in {len(edge_sets)} sets"
        body_label = _qualified_body_name(safe(lambda: all_edges[0].body))
        verify_bodies = _geom.owning_bodies(all_edges)
    elif want_faces:
        fents, ferr = _FACES.resolve(face_handles)
        if ferr:
            return error(ferr)
        ents = _edges_of_faces(fents)
        if not ents:
            return error(f"None of the {len(fents)} face(s) answered any edges, so there is nothing "
                         f"to {kind}. Pass 'edges' handles from find_geometry instead.")
        edges = adsk.core.ObjectCollection.create()
        for e in ents:
            edges.add(e)
        faces_selected = len(fents)
        edge_src = f"{edges.count} edge(s) of {faces_selected} face(s)"
        body_label = _qualified_body_name(safe(lambda: ents[0].body))
        verify_bodies = _geom.owning_bodies(ents)
    elif edge_handles not in (None, "", []):
        ents, herr = _EDGES.resolve(edge_handles)
        if herr:
            # Refuse BEFORE creating any feature: a handle that fails to resolve (stale entityToken,
            # no locator recovery) must not be silently dropped from the edge set. Name the total
            # requested so the caller knows the scale of what it must re-find, not just the one index.
            requested_n = len(edge_handles) if isinstance(edge_handles, (list, tuple)) else None
            count_note = (f" ({requested_n} edge handle(s) were requested; the call is refused before "
                          "any fillet/chamfer feature is created, rather than silently rounding fewer "
                          "edges than asked.)" if requested_n else "")
            return error(herr + count_note)
        handles_sent = len(ents)
        ents = _distinct_placed_edges(ents, safe(lambda: design.rootComponent))
        edges = adsk.core.ObjectCollection.create()
        for e in ents:
            edges.add(e)
        edge_src = f"{edges.count} edge seed(s) from handles"
        body_label = _qualified_body_name(safe(lambda: ents[0].body))
        verify_bodies = _geom.owning_bodies(ents)
    else:
        # The edge SCOPE must be stated - an omitted scope must not silently mean the whole body
        # (blanket rounding was every executor's default design language while 'all' was implicit;
        # explicit scope makes body-wide edge treatment a stated choice).
        flt = (edge_filter or "").strip().lower()
        if not flt:
            return error(f"State the edge scope: pass 'edges' (find_geometry edge handles - the "
                         f"precise set to {kind}) or 'faces' (every edge of the named faces) or an "
                         f"explicit edge_filter ('all' | "
                         f"'convex' | 'concave') to sweep the body. An omitted scope never means "
                         f"the whole body.")
        if flt not in ("all", "convex", "concave"):
            return error("edge_filter must be: all | convex | concave.")
        body, berr = _common.resolve_body_or_recent(
            _BODY, comp, body_name,
            "No body in the active component to fillet/chamfer. Model one first, or pass 'edges' = "
            "edge handles from find_geometry.")
        if berr:
            return error(berr)
        edges, total, census = _collect_edges(body, flt)
        if census is not None and _unclassified(census):
            return error(
                f"{_unclassified(census)} of the {total} edges on '{safe(lambda: body.name)}' could "
                f"not be classified convex or concave ({_unclassified_phrase(census)}), so the "
                f"'{flt}' set cannot be stated. The rest read {_census_phrase(census)}. Pass "
                "'edges' handles from find_geometry to name the set, or edge_filter='all'.")
        if edges.count == 0:
            return error(f"No matching edges on '{safe(lambda: body.name)}' (filter '{flt}', body "
                         f"has {total} edges"
                         + (f": {_census_phrase(census)}" if census else "") + ").")
        body_label = _qualified_body_name(body)
        verify_bodies = [body]
        blanket_note = (f" BLANKET call: {edges.count} of the body's {total} edges swept by "
                        f"filter '{flt}'"
                        + (f" ({_census_phrase(census)})" if census else "")
                        + " - pass edges=[...] handles to target a specific set.")

    vol_before = _geom.volumes(verify_bodies)
    area_before = _geom.areas(verify_bodies)
    try:
        if kind == "fillet":
            fi = comp.features.filletFeatures.createInput()
            if measured_route:
                expected_sets, set_err = _add_measured_edge_sets(
                    fi, design, variant, edges, val, size_cm, units, k, tangent_chain,
                    continuity, flipped, edge_sets)
                if set_err:
                    return error(set_err)
            else:
                set_err = _build_edge_set(fi, variant, edges, val, k, tangent_chain)
                if set_err:
                    return error(set_err)
            feature = comp.features.filletFeatures.add(fi)
        else:
            ci = comp.features.chamferFeatures.createInput2()
            chamfer_sets = ci.chamferEdgeSets
            d2 = float(distance_two or 0.0)
            if angle is not None:
                # A ValueInput built from a REAL carries RADIANS for an angle, so the wire's
                # degrees are converted here; 'distance' is the leg along the first face and the
                # angle turns the bevel off it.
                ang = adsk.core.ValueInput.createByReal(math.radians(angle))
                if not chamfer_sets.addDistanceAndAngleChamferEdgeSet(
                        edges, val, ang, _CHAMFER_FLIPPED, tangent_chain):
                    return error(f"Fusion refused a distance-and-angle chamfer of {size_text} "
                                 f"at {angle} deg, so nothing was chamfered.")
            elif d2 > 0:
                # two-distance (asymmetric) chamfer
                val2 = adsk.core.ValueInput.createByReal(d2 * k)
                if not chamfer_sets.addTwoDistancesChamferEdgeSet(
                        edges, val, val2, _CHAMFER_FLIPPED, tangent_chain):
                    return error(f"Fusion refused a two-distance chamfer ({size_text} / "
                                 f"{d2} {units}), so nothing was chamfered.")
            else:
                if not chamfer_sets.addEqualDistanceChamferEdgeSet(edges, val, tangent_chain):
                    return error(f"Fusion refused an equal-distance chamfer of {size_text}"
                                 ", so nothing was chamfered.")
            if corner_key:
                # An omitted corner_type never assigns, so the input keeps the API's own default.
                cts = safe(lambda: adsk.fusion.ChamferCornerTypes)
                kerr = _common.set_verified(
                    ci, "cornerType",
                    safe(lambda: getattr(cts, _CORNER_TYPES[corner_key])) if cts is not None else None,
                    f"corner_type='{corner_key}'", "ChamferFeatureInput")
                if kerr:
                    return error(kerr)
            feature = comp.features.chamferFeatures.add(ci)
    except Exception as e:
        return error(f"{kind.capitalize()} failed: {e}.{_size_hint(str(e), size_key)}")
    if not feature:
        return error(_common.no_feature_error(design, kind.capitalize()))

    feature_key = _feature_key(feature) if measured_route else None
    measured_sets = None
    if measured_route:
        measured_sets, set_read_error = _read_measured_edge_sets(design, feature, expected_sets)
        if set_read_error:
            return error(set_read_error)

    # READ-BACK off the created feature - the input collection's count is only the request, and a
    # fillet/chamfer can consume fewer edges than handed in. feature.faces.count is the fillet FACES
    # created: a real fillet reports >=1, and the 0-face no-op is gated separately below.
    faces_created = safe(lambda: feature.faces.count)
    # faces_created is not an edge count: corner patches count too. The per-edge number is the
    # feature's own resolved edge set (_cut_edges), read after the gates below.

    # A feature can come back with an ERROR health state and no message at all: a variable-radius
    # chain listed out of connected order does that, and it reads 0 faces like a tangent no-op. The
    # health state separates the two, so it is checked BEFORE the no-op gate.
    health = safe(lambda: feature.healthState)
    if health == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
        detail = safe(lambda: feature.errorOrWarningMessage) or ""
        _removed, fate = _common.delete_failed_feature(design, feature)
        return error(
            f"{kind.capitalize()} created a feature Fusion reports as FAILED"
            + (f": {detail}" if detail else " (it reports no message)")
            + f". No {kind} was applied. For a variable-radius chain, the edges must be "
              "tangentially connected AND listed from one end of the chain to the other; otherwise "
              "check the edges really are corners at this radius, and re-run find_geometry for "
              "fresh handles. " + fate)

    # Fillet NO-OP guard: a fillet on a TANGENT edge - two faces meeting smoothly - creates the
    # feature but rounds nothing, reading 0 faces with the body volume unchanged. Scoped to fillet,
    # where the 0-face read-back is proven to mean no-op.
    if kind == "fillet" and faces_created == 0:
        _removed, fate = _common.delete_failed_feature(design, feature)
        return error(
            "Fillet reported success but rounded nothing - the created feature holds 0 faces. A "
            "TANGENT edge does this: its two faces meet smoothly (zero dihedral), e.g. a hole "
            "drilled tangent to a face with its diameter equal to the wall thickness. Make the "
            "corner non-tangent (a smaller hole diameter), or fillet a convex/concave edge. " + fate)

    # Partial-application guard (both kinds): a stale handle can resolve to SOME live entity through
    # the locator fallback yet not participate in the feature. A fully-applied fillet creates one
    # face per requested edge, even on a tangent LOOP, so a shortfall means an edge was dropped.
    applied = faces_created
    if applied is not None and applied < edges.count:
        _removed, fate = _common.delete_failed_feature(design, feature)
        return error(
            f"{kind.capitalize()} reported success but only PARTIALLY applied: {edges.count} distinct edge(s) "
            f"sent, but the created feature holds only {applied} "
            f"face(s) - at least one requested edge was "
            "dropped (a stale handle recovered the wrong/dead geometry, or an edge the operation could "
            f"not reach). {fate} Re-run find_geometry for fresh handles and retry.")

    # What the FEATURE says it built - never the request echoed back. A corner type or an angle the
    # platform declined leaves no other trace, so a mismatch rolls the feature back.
    verified, unverified = {}, []
    if kind == "chamfer":
        verified, unverified, rerr = _chamfer_readback(feature, size_cm, k, angle, corner_key,
                                                       as_expression)
        if rerr:
            return error(rerr + " " + _common.delete_failed_feature(design, feature)[1])

    # The tangent-chain flag the FEATURE reports. A variable-radius set is built with chaining off
    # whatever was requested, so its reading is published and never compared against the request.
    chain_requested = not measured_route and (kind == "chamfer" or vtype in ("constant", "chord_length"))
    got_chain = _tangent_chain_read(feature) if not measured_route else None
    if chain_requested and got_chain is not None and got_chain != bool(tangent_chain):
        return error(
            f"The {kind} was created but its tangent-chain setting reads back {got_chain}, not the "
            f"requested {bool(tangent_chain)} - the edge set Fusion built is not the one asked for. "
            + _common.delete_failed_feature(design, feature)[1])

    # One convex or concave edge alone always moves the volume, but a set holding BOTH cancels to
    # the last bit and only the surface area still moves (measured: a convex and a concave edge of
    # equal length at r=5 left 36.0 cm3 and took the area 72.0 -> 70.712389).
    vol_delta, vol_readable = _geom.volume_delta(verify_bodies, vol_before)
    area_delta_cm2, area_readable = _geom.area_delta(verify_bodies, area_before)
    moved = ((vol_readable and abs(vol_delta) >= _common.NO_VOLUME_CHANGE_CM3)
             or (area_readable and abs(area_delta_cm2) >= _common.NO_AREA_CHANGE_CM2))
    if (vol_readable or area_readable) and not moved:
        _removed, fate = _common.delete_failed_feature(design, feature)
        size_desc = f"{vtype} fillet" if kind == "fillet" else "chamfer"
        measured = " and ".join(
            [s for s in ("volume" if vol_readable else "", "surface area" if area_readable else "")
             if s])
        return error(
            f"{kind.capitalize()} reported success but changed no geometry - the body's measured "
            f"{measured} is unchanged after the {size_desc}. {fate} Check that the requested "
            "edges really are corners at this size, and re-run find_geometry for fresh handles.")

    measured_note = ("" if faces_created is None
                     else " faces_created is read from the created feature"
                          " (corner patches count too, so faces_created can exceed"
                          " edges_requested).")
    edges_cut, marker_clause = ((None, None) if measured_route else _cut_edges(design, feature))
    # A SHORT edge set is the partial application faces_created cannot see: corner patches can lift
    # the face count to the requested number while the set Fusion built holds fewer edges.
    if edges_cut is not None and edges_cut < edges.count:
        return error(
            f"{kind.capitalize()} reported success but only PARTIALLY applied: {edges.count} distinct edge(s) "
            f"were sent and the feature's own edge set resolved to {edges_cut}, so at least one "
            "requested edge was dropped (a stale handle recovered the wrong/dead geometry, or an "
            "edge the operation could not reach). Re-run find_geometry for fresh handles and retry. "
            + _common.delete_failed_feature(design, feature)[1]
            + ((" " + marker_clause + ".") if marker_clause else ""))
    if edges_cut is None:
        chain_note = " The feature's own edge set did not read, so edges_cut is not reported."
    elif edges_cut > edges.count:
        chain_note = (f" edges_cut {edges_cut} exceeds the {edges.count} edge(s) given: the seeds "
                      "CHAINED into tangentially connected edges. Pass tangent_chain=false to cut "
                      "only the handles.")
    else:
        # It rides the shared read-back sentence below rather than carrying a clause of its own.
        chain_note = ""
    if edges_cut is not None:
        verified["edges_cut"] = edges_cut
    if not chain_requested and got_chain is not None:
        # The wire default is true, so a read-back of false here would otherwise read as a declined
        # request rather than as the one edge set that is built with chaining off.
        chain_note += (f" tangent_chain reads {got_chain} because a {vtype} edge set is built with "
                       "chaining off - it cuts the edges handed in.")
    if marker_clause:
        chain_note += " " + marker_clause + "."
    requested = edges.count if handles_sent is None else handles_sent
    if requested > edges.count:
        chain_note = (f" The {requested} handles named {edges.count} distinct edge(s), so each was "
                      "sent once." + chain_note)

    payload = {
        kind + "ed": True,
        "feature": feature_key if measured_route else safe(lambda: feature.name),
        "body": body_label,
        "units": units,
        "edge_selection": edge_src,
        "edges_requested": requested,
        "note": (f"Edges {'rounded' if kind == 'fillet' else 'beveled'}. Pair with view_screenshot."
                 + chain_note
                 + measured_note
                 + (" " + "/".join(sorted(verified)) + _is_are(verified)
                    + " read back off the created feature, not echoed." if verified else "")
                 + (" " + "/".join(sorted(unverified)) + " could NOT be read back off the feature, "
                    "so the requested value is unconfirmed." if unverified else "")
                 + (blanket_note or "")),
    }
    # Omit rather than report null: a None from safe() means the attribute did not answer.
    if faces_created is not None:
        payload["faces_created"] = faces_created
    if got_chain is not None:
        payload["tangent_chain"] = got_chain
    elif chain_requested:
        payload["tangent_chain_unverified"] = True
    if marker_clause:
        payload["timeline_marker_unrestored"] = True
    if faces_selected is not None:
        payload["faces_selected"] = faces_selected
    if census is not None:
        payload["edges_convex"] = census["convex"]
        payload["edges_concave"] = census["concave"]
        payload["edges_smooth"] = census["smooth"]
    if vol_readable:
        payload["volume_delta_cm3"] = round(vol_delta, 6)
    if area_readable:
        payload["area_delta_cm2"] = round(area_delta_cm2, 6)
    if kind == "fillet":
        payload["fillet_type"] = vtype
    if measured_route:
        payload["edge_sets"] = measured_sets
        if edge_sets is None and measured_sets[0]["type"] == "asymmetric":
            payload[size_key] = round(measured_sets[0]["offset_one_cm"] / k, 6)
            payload["end_radius"] = round(measured_sets[0]["offset_two_cm"] / k, 6)
            payload["flipped"] = measured_sets[0]["flipped"]
            payload["asymmetric_continuity_unverified"] = True
        elif edge_sets is None:
            payload[size_key] = round(measured_sets[0]["radius_cm"] / k, 6)
            if measured_sets[0]["type"] == "variable":
                payload["end_radius"] = round(measured_sets[0]["end_radius_cm"] / k, 6)
                payload["positions"] = measured_sets[0]["positions"]
                payload["radii"] = [round(radius / k, 6)
                                    for radius in measured_sets[0]["radii_cm"]]
        if any(row["type"] == "asymmetric" for row in measured_sets):
            payload["side_mapping"] = None
            payload["note"] += (" Geometric setback-side mapping is unavailable; find_geometry reads the "
                                "adjacent faces, and view_section shows the corner. flipped swaps "
                                "radius/end_radius; remove the feature and recreate if the sides are reversed.")
    else:
        # A legacy request is echoed as itself; measured routes publish retained feature values above.
        payload[size_key] = _inputs.expression_report(size)
    if vtype == "variable":
        if not measured_route:
            payload["end_radius"] = round(variant["end_radius"], 6)
        if variant["positions"] and not measured_route:
            payload["positions"] = variant["positions"]
            payload["radii"] = variant["radii"]
    if kind == "chamfer" and float(distance_two or 0.0) > 0:
        payload["distance_two"] = round(float(distance_two), 6)
    # The verified values REPLACE the request in the payload; a field the feature would not answer
    # is flagged instead of being echoed as though it had been confirmed.
    payload.update(verified)
    for field in unverified:
        payload[f"{field}_unverified"] = True
    if as_expression and size_key in verified:
        # size_key now carries the value the FEATURE reports; without this the caller cannot tell
        # that number came from a parameter rather than from one they fixed.
        payload[f"{size_key}_expression"] = str(size).strip()
    return ok(payload)
