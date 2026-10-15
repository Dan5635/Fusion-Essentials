# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Shared sheet-metal rule, component, edge and flat-pattern reads."""

import adsk.core
import adsk.fusion
from . import _assert, _geom, _common
from ._common import counted, iter_collection, measured, ptxyz, safe

MAP_BLURB = ("rule_row/scoped_rules/matching_rules/component_row/sheet_edge_faces/bend_face_count/bend_wall_groups/"
             "flat_pattern_row/pending_unfolds - scoped rules, pending unfold preflight, component state, a rim edge's faces, cylinder-face "
             "count, bend walls paired per axis, flat health and optional geometry; "
             "_POSITIONS/_KIND_SPEC - Hem position and kind tables")

_RULE_VALUES = ("thickness", "bendRadius", "gap", "reliefWidth", "reliefDepth",
                "reliefRemnant", "twoBendReliefSize", "threeBendReliefRadius")
RULE_SHAPES = {
    "relief_shape": ("reliefShape", "BendReliefShapes", {
        "straight": "StraightBendReliefShape", "tear": "TearBendReliefShape", "round": "RoundBendReliefShape"}),
    "two_bend_relief_shape": ("twoBendReliefShape", "TwoBendReliefShapes", {
        "square": "SquareTwoBendReliefShape", "round": "RoundTwoBendReliefShape"}),
    "two_bend_relief_placement": ("twoBendReliefPlacement", "TwoBendReliefPlacements", {
        "intersection": "IntersectionTwoBendReliefPlacement", "tangent": "TangentTwoBendReliefPlacement",
        "vertex": "VertexTwoBendReliefPlacement"}),
    "three_bend_relief_shape": ("threeBendReliefShape", "ThreeBendReliefShapes", {
        "none": "NoReplacementThreeBendReliefShape", "intersection": "IntersectionThreeBendReliefShape",
        "full_round": "FullRoundThreeBendReliefShape", "round_with_radius": "RoundWithRadiusThreeBendReliefShape"}),
}
_RELIEF_ENUMS = {"BendReliefShapes": adsk.fusion.BendReliefShapes,
                 "TwoBendReliefShapes": adsk.fusion.TwoBendReliefShapes,
                 "TwoBendReliefPlacements": adsk.fusion.TwoBendReliefPlacements,
                 "ThreeBendReliefShapes": adsk.fusion.ThreeBendReliefShapes}
_POSITIONS = {"start_edge": "StartEdgeBendPositionType", "tangent_to_side": "TangentToSideBendPositionType"}

# kind -> (its dimensions in the setter's own order, the landed HemFeatureDefinition class suffix).
_KIND_SPEC = {
    "flat": (("length",), "FlatHemFeatureDefinition"),
    "open": (("length", "gap"), "OpenHemFeatureDefinition"),
    "rolled": (("radius", "angle_deg"), "RolledHemFeatureDefinition"),
    "rope": (("length", "gap", "radius"), "RopeHemFeatureDefinition"),
    "teardrop": (("radius", "length", "gap"), "TeardropHemFeatureDefinition"),
    "double": (("gap", "length", "setback"), "DoubleHemFeatureDefinition"),
}


def relief_enum(field, label):
    """Return the installed enum member for a validated rule relief choice, or None."""
    _, family, choices = RULE_SHAPES[field]
    return safe(lambda: getattr(_RELIEF_ENUMS[family], choices[label]))


def pending_unfolds(design):
    """Return qualified pending unfolds or an incomplete/inconsistent design-wide census error."""
    root_key = _common.native_identity(safe(lambda: design.rootComponent))
    components = safe(lambda: design.allComponents)
    count = counted(lambda: components.count)
    if root_key is None or count is None or count < 1:
        return None, "allComponents/root identity could not be read"
    owners, names, pending = [], [], []
    unread = object()
    for i in range(count):
        comp = safe(lambda i=i: components.item(i))
        key, name = _common.native_identity(comp), safe(lambda: comp.name)
        if key is None or key in owners or not isinstance(name, str) or not name:
            return None, f"allComponents slot {i} identity/name could not be read uniquely"
        owners.append(key)
        names.append(name.lower())
        sets = {}
        for kind, opposite in (("unfoldFeatures", "refoldFeature"), ("refoldFeatures", "unfoldFeature")):
            collection = safe(lambda kind=kind: getattr(comp.features, kind))
            n = counted(lambda: collection.count)
            if n is None or n < 0:
                return None, f"'{name}' {kind} count could not be read"
            rows = {}
            for j in range(n):
                feature = safe(lambda j=j: collection.item(j))
                identity = _common.native_identity(feature)
                owner = _common.native_identity(safe(lambda: feature.parentComponent))
                label = safe(lambda: feature.name)
                linked = safe(lambda opposite=opposite: getattr(feature, opposite), unread)
                if (identity is None or identity in rows or owner != key
                        or not isinstance(label, str) or not label or linked is unread):
                    return None, f"'{name}' {kind} slot {j} identity/owner/association could not be read"
                if linked is None:
                    linked_key = None
                else:
                    linked_key = _common.native_identity(linked)
                    back = safe(lambda: getattr(linked, 'unfoldFeature' if opposite == 'refoldFeature' else 'refoldFeature'))
                    if (linked_key is None or _common.native_identity(safe(lambda: linked.parentComponent)) != key
                            or _common.native_identity(back) != identity):
                        return None, f"'{name}/{label}' has an unread or inconsistent reciprocal association"
                rows[identity] = (label, linked_key)
            sets[kind] = rows
        unfolds, refolds = sets["unfoldFeatures"], sets["refoldFeatures"]
        for identity, (label, linked) in unfolds.items():
            if linked is None:
                if sum(other.lower() == label.lower() for other, _linked in unfolds.values()) != 1:
                    return None, f"pending '{name}/{label}' has an ambiguous unfold name; acquire exact timeline addresses"
                pending.append((name, label))
            elif linked not in refolds or refolds[linked][1] != identity:
                return None, f"'{name}/{label}' refold is absent from its owner's collection"
        for identity, (label, linked) in refolds.items():
            if linked is None:
                orphans = [f"{name}/{u}" for u, link in unfolds.values() if link is None]
                return None, (f"'{name}/{label}' exists but reads no unfoldFeature, and {name}'s "
                              f"unfold(s) reading no refoldFeature: {', '.join(orphans) or 'none'} "
                              "- the unfold/refold association is lost. design_delete_feature("
                              f"feature='{name}/{label}'), then the same on each unfold listed, "
                              "clears this refusal")
            if linked not in unfolds or unfolds[linked][1] != identity:
                return None, f"'{name}/{label}' unfold is absent from its owner's collection"
    if owners.count(root_key) != 1:
        return None, "allComponents did not include the root exactly once"
    for name, label in pending:
        if names.count(name.lower()) != 1:
            return None, f"pending '{name}/{label}' has an ambiguous component name; acquire exact timeline addresses"
    return [f"{name}/{label}" for name, label in pending], None


def scoped_rules(design, scope):
    """Return rules in native collection order, or None for an incomplete read."""
    if scope not in ("design", "library"):
        return None
    collection = safe(lambda: (design.designSheetMetalRules if scope == "design"
                               else design.librarySheetMetalRules))
    if collection is None:
        return None
    count = safe(lambda: collection.count)
    if type(count) is not int or count < 0:
        return None
    rules = [safe(lambda i=i: collection.item(i)) for i in range(count)]
    return rules if all(r is not None and isinstance(safe(lambda r=r: r.name), str)
                        and safe(lambda r=r: r.name) for r in rules) else None


def matching_rules(design, scope, name):
    """Return exact case-insensitive rule matches in the requested scope."""
    rules = scoped_rules(design, scope)
    if rules is None:
        return None
    want = name.strip().lower()
    return [r for r in rules if (safe(lambda r=r: r.name) or "").lower() == want]


def rule_ref_and_index(design, rule, scope):
    """Return a scoped string or collision-safe scope/index ref and the collection index."""
    name = safe(lambda: rule.name)
    if not name or design is None:
        return (f"{scope}:{name}" if name else None), None
    rules = scoped_rules(design, scope)
    if rules is None:
        return None, None
    index = next((i for i, r in enumerate(rules) if r == rule), None)
    same = matching_rules(design, scope, name)
    if not same or len(same) <= 1:
        ref = name
    else:
        ordinal = next((i for i, r in enumerate(same) if r == rule), None)
        ref = f"{name}#{ordinal + 1}" if ordinal is not None else name
    literal = matching_rules(design, scope, ref) or []
    base, _, tail = ref.rpartition("#")
    duplicates = matching_rules(design, scope, base) if base and tail.isdigit() and int(tail) >= 1 else []
    ordinal_rule = (duplicates[int(tail) - 1] if duplicates and len(duplicates) >= 2
                    and int(tail) <= len(duplicates) else None)
    if literal and ordinal_rule is not None and any(r != ordinal_rule for r in literal):
        return ({"scope": scope, "index": index, "name": name} if index is not None else None), index
    return f"{scope}:{ref}", index


def rule_row(design, rule, scope):
    """Return readable rule settings, the ownership flag valid for this scope, a duplicate-safe ref and its index."""
    name = safe(lambda: rule.name)
    ref, index = rule_ref_and_index(design, rule, scope)
    out = {"name": name, "ref": ref, "index": index, "scope": scope,
           "units": safe(lambda: rule.units), "k_factor": safe(lambda: rule.kFactor)}
    for key in _RULE_VALUES:
        value = safe(lambda key=key: getattr(rule, key))
        out[key] = ({"expression": safe(lambda value=value: value.expression),
                     "value_cm": safe(lambda value=value: value.value)} if value else None)
    for key, (member, _family, choices) in RULE_SHAPES.items():
        actual = safe(lambda member=member: getattr(rule, member))
        out[key] = next((label for label in choices if actual is not None
                        and actual == relief_enum(key, label)), None)
    if scope == "design":
        out["is_used"] = safe(lambda: rule.isUsed)
    else:
        out["is_default"] = safe(lambda: rule.isDefault)
    return out


def component_rule_ref(rule, rules):
    """Return a component rule reference and whether its assignment was resolved."""
    if rule is None:
        return None, "none"
    if rule is _UNREAD or rules is None:
        return None, "unknown"
    matches = []
    for i, candidate in enumerate(rules):
        equal = safe(lambda candidate=candidate: candidate == rule, _UNREAD)
        if type(equal) is not bool:
            return None, "unknown"
        if equal:
            matches.append(i)
    if len(matches) != 1:
        return None, "unknown"
    return {"scope": "design", "index": matches[0], "name": safe(lambda: rules[matches[0]].name)}, "matched"


_UNREAD = object()


def component_row(component, design_rules=None):
    """Return the component's active rule, native sheet bodies and flat presence."""
    rule = safe(lambda: component.activeSheetMetalRule, _UNREAD)
    rule_ref, rule_ref_state = component_rule_ref(rule, design_rules)
    bodies = safe(lambda: component.bRepBodies)
    rows = ([{"name": safe(lambda b=b: b.name),
              "is_sheet_metal": safe(lambda b=b: b.isSheetMetal)}
             for b in iter_collection(bodies)] if bodies is not None else None)
    marker = object()
    flat = safe(lambda: component.flatPattern, marker)
    return {"component": safe(lambda: component.name),
            "active_rule": safe(lambda: rule.name) if rule is not None and rule is not _UNREAD else None,
            "active_rule_ref": rule_ref, "active_rule_ref_state": rule_ref_state,
            "bodies": rows, "has_flat_pattern": (None if flat is marker else flat is not None)}


def outward_normal(face):
    """Return the face's outward unit normal at its point-on-face as a Vector3D, or None."""
    parts = _geom.evaluator_normal_at(face, safe(lambda: face.pointOnFace), decimals=9)
    return adsk.core.Vector3D.create(*parts) if parts else None


def sheet_edge_faces(edge):
    """Return (sheet_face, rim_face, None) for a straight rim edge joining a broad planar sheet face and its planar thickness face, else (None, None, why)."""
    if safe(lambda: edge.geometry.objectType) != adsk.core.Line3D.classType():
        return None, None, "is not a straight edge; pick a rim edge with find_geometry(kind='line_edge')."
    faces = list(iter_collection(safe(lambda: edge.faces)))
    if len(faces) != 2:
        return None, None, f"is shared by {len(faces)} faces, not 2."
    if any(safe(lambda f=f: f.geometry.objectType) != adsk.core.Plane.classType() for f in faces):
        return None, None, "meets a curved face (a bend or blend); pick a rim edge between the sheet face and its thickness face."
    faces.sort(key=lambda f: safe(lambda: f.area) or 0.0, reverse=True)
    sheet, rim = faces
    n_sheet, n_rim = outward_normal(sheet), outward_normal(rim)
    if n_sheet is None or n_rim is None or abs(n_sheet.dotProduct(n_rim)) > 1e-3:
        return None, None, "joins two faces that are not perpendicular; pick a rim edge of the sheet."
    return sheet, rim, None


def bend_face_count(body):
    """Return the number of cylindrical faces on the body (a bend contributes its inner and outer face), or None."""
    faces = safe(lambda: body.faces)
    if faces is None:
        return None
    return len([f for f in iter_collection(faces)
                if safe(lambda f=f: f.geometry.objectType) == adsk.core.Cylinder.classType()])


def _unit(v):
    """A unit copy of an [x, y, z] sequence, or None when it has no length."""
    mag = _geom.dot(v, v) ** 0.5
    return None if mag < 1e-12 else [c / mag for c in v]


def bend_wall_groups(body):
    """Return the body's cylinder faces grouped per shared axis line at two or more radii (a hole has one), or None when a face will not read."""
    # Never BRepBody.getBendFaces() here: a call on the body before an unfold makes the later
    # refold land the body rotated 90 deg. A hole through a flange leg has its axis in the base
    # plane, so the inner/outer pairing, not the axis direction, tells a wall from a hole.
    faces = safe(lambda: body.faces)
    if faces is None:
        return None
    groups = []
    for f in iter_collection(faces):
        kind = safe(lambda f=f: f.geometry.objectType)
        if kind is None:
            return None
        if kind != adsk.core.Cylinder.classType():
            continue
        shape = safe(lambda f=f: (list(f.geometry.origin.asArray()), _unit(list(f.geometry.axis.asArray())),
                                  float(f.geometry.radius)))
        if shape is None or shape[1] is None:
            return None
        origin, axis, radius = shape
        for grp in groups:
            if _geom.coaxial(grp["origin"], grp["axis"], origin, axis):
                grp["faces"].append(f)
                grp["radii"].append(radius)
                break
        else:
            groups.append({"origin": origin, "axis": axis, "faces": [f], "radii": [radius]})
    out = []
    for grp in groups:
        distinct = []
        for r in grp["radii"]:
            if all(abs(r - d) > 1e-5 for d in distinct):
                distinct.append(r)
        if len(distinct) >= 2:
            out.append(grp["faces"])
    return out


def _flat_face(face, index):
    """Return one flat-native face's sampled geometry with unread fields disclosed."""
    geometry = safe(lambda: face.geometry)
    point = safe(lambda: face.pointOnFace)
    normal = safe(lambda: _geom.evaluator_normal_at(face, point, decimals=9))
    if normal is not None and any(measured(lambda v=v: v) is None for v in normal):
        normal = None
    row = {"index": index, "type": safe(lambda: geometry.objectType),
           "area_cm2": measured(lambda: face.area, places=9),
           "centroid_cm": ptxyz(safe(lambda: face.centroid), 1),
           "sample_point_cm": ptxyz(point, 1), "normal_at_sample": normal}
    unread = [key for key, value in row.items() if value is None]
    if safe(lambda: geometry.surfaceType) == adsk.core.SurfaceTypes.PlaneSurfaceType:
        row["plane"] = {"origin_cm": ptxyz(safe(lambda: geometry.origin), 1),
                        "normal": ptxyz(safe(lambda: geometry.normal), 1)}
        unread.extend("plane." + k for k, v in row["plane"].items() if v is None)
        surface = row["plane"]["normal"]
        sign = _geom.dot(normal, [surface[a] for a in "xyz"]) if normal and surface else None
        if sign is not None and sign < 0:
            row["plane"]["note"] = "plane.normal points opposite normal_at_sample on this face."
    row["unread"] = unread
    return row


def _flat_geometry(flat, limit):
    """Return bounded flat-native body bounds and faces without certifying development."""
    body = safe(lambda: flat.flatBody)
    box = safe(lambda: body.boundingBox)
    bounds = {"min": ptxyz(safe(lambda: box.minPoint), 1),
              "max": ptxyz(safe(lambda: box.maxPoint), 1)}
    faces = safe(lambda: body.faces)
    total = counted(lambda: faces.count)
    if total is not None and total < 0:
        total = None
    rows, unread_indices = [], []
    for i in range(min(total, limit) if total is not None else 0):
        face = safe(lambda i=i: faces.item(i))
        if face is None:
            unread_indices.append(i)
        else:
            rows.append(_flat_face(face, i))
    return {"frame": "flatBody native coordinates; not folded-body world coordinates",
            "normals": ("normal_at_sample is the face evaluator's outward normal at "
                        "sample_point_cm; plane.normal is the supporting surface's parametric "
                        "normal"),
            "development": "unverified", "bounds_cm": bounds,
            "face_count": total, "returned": len(rows), "limit": limit,
            "truncated": total > limit if total is not None else None,
            "partial": total is None or any(v is None for v in bounds.values())
                       or bool(unread_indices) or any(r["unread"] for r in rows),
            "unread_face_indices": unread_indices, "faces": rows}


def flat_pattern_row(component, geometry_limit=None):
    """Return flat-pattern state and optionally bounded flat-native geometry."""
    marker = object()
    flat = safe(lambda: component.flatPattern, marker)
    if flat is marker:
        return {"present": None}
    if flat is None:
        return {"present": False}
    state, failure = _assert.compute_state(flat)
    out = {"present": True, "healthy": state == "healthy",
            "message": failure[1] if failure else None,
            "flat_volume_cm3": safe(lambda: flat.flatBody.volume)}
    if geometry_limit is not None:
        out["geometry"] = _flat_geometry(flat, min(32, geometry_limit))
    return out
