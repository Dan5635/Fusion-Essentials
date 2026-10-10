# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Detail engine behind sketch_get: X-rays ONE sketch - entities, construction geometry,
constraints, dimensions - and owns the sketch's world FRAME. Entity ids ('<type>:<index>') are the
references sketch_constrain / model_extrude / sketch_add_geometry take."""

import importlib
import math
import types

import adsk.core
import adsk.fusion

from ._common import ok, error, safe, find_sketch, all_sketch_names
from . import _common
from . import _geom
from . import _inputs
from . import _view_common

app = adsk.core.Application.get()

MAP_BLURB = (
    "sketch_get's X-ray; sketch_world_frame/frame_space_note - frame; curve_id/entity_id/"
    "dimension_entities - ids; point_census/moved_points/point_ends - what a solve moved; "
    "scope_component(s)/COMPONENT_SCOPE/component_scope/scoped_sketch/scoped_or_recent_sketch/"
    "scope_remedy - the scope; _sketch_summary - a sketch row; _prepare/_transform - move/copy; "
    "unquote_text/font_read_back - SketchText.")


def unquote_text(expr):
    """The textParameter expression is a quoted string ('foo'); return the inner text."""
    if expr is None:
        return None
    s = str(expr)
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def font_read_back(obj):
    """The font the landed/edited SketchText reports, or None if it will not read as a name."""
    value = safe(lambda: obj.fontName)
    return value if isinstance(value, str) and value else None


def _plane_normal(x_world, y_world):
    """The unit normal of the plane two in-plane [x, y, z] axis vectors span, or None if they are
    parallel and span none."""
    cross = types.SimpleNamespace(
        x=x_world[1] * y_world[2] - x_world[2] * y_world[1],
        y=x_world[2] * y_world[0] - x_world[0] * y_world[2],
        z=x_world[0] * y_world[1] - x_world[1] * y_world[0])
    n = _geom.unit_vector(cross)
    # + 0.0 turns IEEE -0.0 back into 0.0; a lifted frame's axes carry signed zeros.
    return None if n is None else [c + 0.0 for c in n]


WORLD_SPACE = "world"
COMPONENT_LOCAL_SPACE = "component_local"

# The one sentence each space owes the caller, keyed by frame['space'].
FRAME_SPACE_NOTE = {
    WORLD_SPACE: (
        "'frame' maps sketch coords to WORLD (frame.space='world'): origin_mm is sketch (0,0); "
        "x_world/y_world are its axes, normal is its plane normal. Use this frame for geometry. "
        "A datum point need not equal this origin; compare normals and signed offsets. "
        "'component' is sketch owner, not necessarily datum owner."),
    COMPONENT_LOCAL_SPACE: (
        "'frame' is COMPONENT-LOCAL, not world (frame.space='component_local'): no single "
        "placement of this sketch resolved, so the in-plane axes are published as frame.x_local / "
        "frame.y_local, not frame.x_world. The numbers map this sketch's own entity coordinates. "
        "For a world frame, name the instance: sketch_get(component='<occurrence "
        "fullPathName>'); design_get(include=['tree']) lists the paths."),
}


def frame_space_note(frame) -> str:
    """The one sentence naming the space `frame`'s numbers are in; an unreadable frame (None) gets
    the component-local wording."""
    space = (frame or {}).get("space") if isinstance(frame, dict) else None
    return FRAME_SPACE_NOTE.get(space, FRAME_SPACE_NOTE[COMPONENT_LOCAL_SPACE])


def _placement_count(root, comp):
    """How many times `root`'s assembly places `comp` - 0 for a component nothing places there, and
    0 for `root` itself, which its own design places nowhere."""
    occs = safe(lambda: root.allOccurrencesByComponent(comp)) if comp is not None else None
    return (safe(lambda: occs.count, 0) or 0) if occs is not None else 0


def _frame_context(sketch, design, occurrence=None):
    """(the sketch the frame is read off, the space those numbers are in), resolved against
    `design`'s root and through `occurrence` when the caller named one."""
    # Sketch.origin/xDirection/yDirection read in the sketch's PARENT COMPONENT space, not the
    # assembly's, so a sub-component's sketch is lifted through its placement first; a component
    # placed several times, or none, has no one world frame and stays component_local.
    def _lift(through):
        # A proxy that will not read leaves the NATIVE numbers, which are component-local.
        proxy = safe(lambda: sketch.createForAssemblyContext(through))
        return (proxy, WORLD_SPACE) if proxy is not None else (sketch, COMPONENT_LOCAL_SPACE)

    if occurrence is not None:
        return _lift(occurrence)
    root = safe(lambda: design.rootComponent) if design is not None else None
    if root is None:
        return sketch, COMPONENT_LOCAL_SPACE
    occ, err = _inputs.single_placement("the sketch", sketch, root, design)
    if err:
        return sketch, COMPONENT_LOCAL_SPACE
    if occ is not None:
        return _lift(occ)
    # Root components in DIFFERENT documents read ONE entityToken, so comparing this root against
    # the sketch's owner answers SAME for an x-ref'd sketch. The placement census settles ownership
    # without that comparison: a design places its own root nowhere.
    if safe(lambda: sketch.assemblyContext) is not None:
        return sketch, WORLD_SPACE          # already in the assembly's space; nothing to census
    owner = safe(lambda: sketch.parentComponent)
    if owner is None:
        return sketch, COMPONENT_LOCAL_SPACE
    if _placement_count(root, owner) == 0:
        return sketch, WORLD_SPACE
    # Placed here, so ask the walk again with no component to compare against - its
    # `comp is not None` guard makes None mean "decide on placement alone".
    occ, _err = _inputs.single_placement("the sketch", sketch, None, design)
    return _lift(occ) if occ is not None else (sketch, COMPONENT_LOCAL_SPACE)


def sketch_world_frame(sketch, design, occurrence=None) -> dict:
    """Where sketch (0,0) lands, where +X/+Y point (unit axes, keyed 'x_world' or 'x_local' by the
    published 'space'), and the plane's normal - origin_mm in mm. None when the plane cannot be
    read. `occurrence`, when the caller reached the sketch through a placement, is lifted through."""
    def _vec(g):
        # The lift is a matrix multiply, so an axis component that should be zero arrives as a tiny
        # signed residue that round() collapses to -0.0; + 0.0 turns that back into 0.0.
        return [round(safe(lambda: g.x, 0.0) or 0.0, 6) + 0.0,
                round(safe(lambda: g.y, 0.0) or 0.0, 6) + 0.0,
                round(safe(lambda: g.z, 0.0) or 0.0, 6) + 0.0]

    lifted, space = _frame_context(sketch, design, occurrence)
    op = safe(lambda: lifted.origin)            # Point3D of sketch (0,0) in `space`
    xd = safe(lambda: lifted.xDirection)        # Vector3D of sketch +X in `space`
    yd = safe(lambda: lifted.yDirection)        # Vector3D of sketch +Y in `space`
    if op is None or xd is None or yd is None:
        return None
    x_axis, y_axis = _vec(xd), _vec(yd)
    frame = {
        "origin_mm": [round((safe(lambda: op.x, 0.0) or 0.0) * 10, 4) + 0.0,
                      round((safe(lambda: op.y, 0.0) or 0.0) * 10, 4) + 0.0,
                      round((safe(lambda: op.z, 0.0) or 0.0) * 10, 4) + 0.0],
        "normal": _plane_normal(x_axis, y_axis),
        "space": space,
    }
    # Assigned by name in each branch, not through a lookup: the disclosure lint pins the literals.
    if space == WORLD_SPACE:
        frame["x_world"], frame["y_world"] = x_axis, y_axis
    else:
        frame["x_local"], frame["y_local"] = x_axis, y_axis
    return frame


# local aliases (this module's own record builders read them under the short names)
_unquote = unquote_text
_font_read_back = font_read_back

# Constraint class -> the spelling sketch_constrain's 'constraint' input takes + the attributes
# holding its referenced SKETCH entities. A surface-side attribute is a model face or construction
# plane, outside this sketch's id space, so listing it would only add a '?'.
_CONSTRAINT_REFS = {
    "PerpendicularConstraint": ("perpendicular", ("lineOne", "lineTwo")),
    "ParallelConstraint": ("parallel", ("lineOne", "lineTwo")),
    "CollinearConstraint": ("collinear", ("lineOne", "lineTwo")),
    "TangentConstraint": ("tangent", ("curveOne", "curveTwo")),
    "EqualConstraint": ("equal", ("curveOne", "curveTwo")),
    "ConcentricConstraint": ("concentric", ("entityOne", "entityTwo")),
    "SymmetryConstraint": ("symmetry", ("entityOne", "entityTwo", "symmetryLine")),
    "HorizontalConstraint": ("horizontal", ("line",)),
    "VerticalConstraint": ("vertical", ("line",)),
    "HorizontalPointsConstraint": ("horizontal_points", ("pointOne", "pointTwo")),
    "VerticalPointsConstraint": ("vertical_points", ("pointOne", "pointTwo")),
    "CoincidentConstraint": ("coincident", ("point", "entity")),
    "CoincidentToSurfaceConstraint": ("coincident_to_surface", ("point",)),
    "LineOnPlanarSurfaceConstraint": ("line_on_surface", ("line",)),
    "LineParallelToPlanarSurfaceConstraint": ("line_parallel_to_surface", ("line",)),
    "PerpendicularToSurfaceConstraint": ("perpendicular_to_surface", ("curve",)),
    "MidPointConstraint": ("midpoint", ("point", "midPointCurve")),
    "SmoothConstraint": ("smooth", ("curveOne", "curveTwo")),
    "OffsetConstraint": ("offset", ("parentCurves", "childCurves")),
    "PolygonConstraint": ("polygon", ("lines",)),          # 'lines' is a vector (many)
    "CircularPatternConstraint": ("circular_pattern", ("centerPoint", "entities")),
    "RectangularPatternConstraint": ("rectangular_pattern",
                                     ("entities", "directionOneEntity", "directionTwoEntity")),
}


def _round(v, f):
    """v scaled by the cm -> display-unit factor f and rounded to 4dp, or None if v is None."""
    return round(float(v) * f, 4) if v is not None else None


def _curve_collections(sketch):
    """(kind, collection) for every curve kind resolve_entity_ref addresses, in id order."""
    curves = safe(lambda: sketch.sketchCurves)
    for kind, coll_get in (("line", lambda: curves.sketchLines),
                           ("arc", lambda: curves.sketchArcs),
                           ("circle", lambda: curves.sketchCircles),
                           ("ellipse", lambda: curves.sketchEllipses),
                           ("elliptical_arc", lambda: curves.sketchEllipticalArcs),
                           ("conic", lambda: curves.sketchConicCurves),
                           ("spline", lambda: curves.sketchFittedSplines),
                           ("cv_spline", lambda: curves.sketchControlPointSplines),
                           ("fixed_spline", lambda: curves.sketchFixedSplines)):
        yield kind, safe(coll_get)


def curve_id(sketch, curve):
    """'<type>:<index>' for one curve, matched by IDENTITY against the sketch's own collections, or
    None when it is not among them - the two pieces a split returns share ONE entityToken."""
    for kind, coll in _curve_collections(sketch):
        for i in range(safe(lambda coll=coll: coll.count, 0) if coll else 0):
            if safe(lambda coll=coll, i=i: coll.item(i) == curve) is True:
                return f"{kind}:{i}"
    return None


def entity_id(sketch, entity):
    """'<type>:<index>' for one curve or sketch point, matched by IDENTITY, or None."""
    ref = curve_id(sketch, entity)
    if ref is not None:
        return ref
    pts = safe(lambda: sketch.sketchPoints)
    for i in range(safe(lambda: pts.count, 0) if pts else 0):
        if safe(lambda i=i: pts.item(i) == entity) is True:
            return f"point:{i}"
    return None


# ── the sketch-point census a solve's moves are read from ─────────────────────────────────────────

MOVE_TOL_CM = 1e-4       # a point that moved no further than this (0.001 mm) is reported as held


def point_cm(geo):
    """(x, y, z) in cm off a point geometry, or None when it does not read."""
    x = safe(lambda: float(geo.x))
    y = safe(lambda: float(geo.y))
    if x is None or y is None:
        return None
    return (x, y, safe(lambda: float(geo.z), 0.0) or 0.0)


def point_mm(p):
    """A cm point as the [x, y, z] mm list a payload publishes."""
    return [round(v * _common.CM_TO_UNIT["mm"], 4) for v in p]


def distance_cm(a, b):
    """The straight-line distance between two cm points."""
    return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5


def moved_cm(before, after):
    """The furthest one entity's sampled points moved, in cm, or None when the reads do not pair."""
    if not before or not after or len(before) != len(after):
        return None
    return max(distance_cm(a, b) for a, b in zip(before, after))


def point_census(sketch):
    """{'point:<i>': (x, y, z) cm} for every sketch point, or None when any one does not read."""
    pts = safe(lambda: sketch.sketchPoints)
    count = _common.counted(lambda: pts.count)
    if count is None:
        return None
    census = {f"point:{i}": point_cm(safe(lambda i=i: pts.item(i).geometry)) for i in range(count)}
    return None if None in census.values() else census


def moved_points(before, after):
    """[(id, from, to)] for the points that moved more than MOVE_TOL_CM, None when unpaired."""
    if before is None or after is None or set(before) != set(after):
        return None
    return [(ref, was, after[ref]) for ref, was in before.items()
            if distance_cm(was, after[ref]) > MOVE_TOL_CM]


def point_ends(sketch, refs):
    """{point id: ['<curve id> start' or '<curve id> end', ...]} for the curves ending there."""
    points = [(ref, _common.resolve_entity_ref(sketch, ref)) for ref in refs]
    ends = {ref: [] for ref in refs}
    for kind, coll in _curve_collections(sketch):
        for i in range(safe(lambda coll=coll: coll.count, 0) if coll else 0):
            curve = safe(lambda coll=coll, i=i: coll.item(i))
            for end in ("start", "end"):
                at = safe(lambda: getattr(curve, end + "SketchPoint"))
                for ref, point in points:
                    if at is not None and point is not None and safe(lambda: at == point) is True:
                        ends[ref].append(f"{kind}:{i} {end}")
    return ends


def _entity_handles(sketch, rows, occurrence, placed):
    """Stamp each point/curve row with its 'handle' through `occurrence`, None when not `placed`."""
    for rec in rows:
        kind = str(rec.get("id", "")).rpartition(":")[0]
        if kind not in _common.ENTITY_REF_KINDS:
            continue
        ent = _common.resolve_entity_ref(sketch, rec["id"]) if placed else None
        rec["handle"] = (_inputs.placed_handle(ent, "sketch_" + kind, occurrence)
                         if ent is not None else None)


def sketch_token_ids(sketch):
    """entityToken -> every '<type>:<index>' carrying it, over the curve kinds plus 'point'."""
    ids = {}
    for kind, coll in list(_curve_collections(sketch)) + [("point", safe(lambda: sketch.sketchPoints))]:
        for i in range(safe(lambda coll=coll: coll.count, 0) if coll else 0):
            tok = safe(lambda coll=coll, i=i: coll.item(i).entityToken)
            if tok:
                ids.setdefault(tok, []).append(f"{kind}:{i}")
    return ids


# Dimension class -> the getters naming its sketch entities, in getter order (measured); any other
# class publishes entities null (a surface dimension anchors on a face or construction plane).
_DIMENSION_REFS = {
    "SketchLinearDimension": ("entityOne", "entityTwo"),
    "SketchOffsetDimension": ("line", "entityTwo"),
    "SketchAngularDimension": ("lineOne", "lineTwo"),
    "SketchDiameterDimension": ("entity",),
    "SketchConcentricCircleDimension": ("circleOne", "circleTwo"),
    "SketchRadialDimension": ("entity",),
    "SketchEllipseMajorRadiusDimension": ("ellipse",),
    "SketchEllipseMinorRadiusDimension": ("ellipse",),
    "SketchTangentDistanceDimension": ("entityOne", "circleOrArc"),
    "SketchLinearDiameterDimension": ("line", "entityTwo"),
}


def _identical_id(sketch, entity, token_ids):
    """The one id among those `entity`'s token maps to that resolves IDENTICAL to it, else '?'."""
    tok = safe(lambda: entity.entityToken)
    hits = [ref for ref in token_ids.get(tok, ())
            if safe(lambda r=ref: _common.resolve_entity_ref(sketch, r) == entity) is True]
    return hits[0] if len(hits) == 1 else "?"


def dimension_entities(sketch, dimension, token_ids):
    """A dimension's sketch-entity ids in getter order ('?' unmatched), None for an unprobed class."""
    getters = _DIMENSION_REFS.get(type(dimension).__name__)
    if getters is None:
        return None
    return [_identical_id(sketch, safe(lambda g=g: getattr(dimension, g)), token_ids)
            for g in getters]


_Z_EPS = 1e-6   # cm; a sketch point within this of the plane is on-plane and its z is omitted


def _xy(geo, f):
    """{x, y} for a sketch point's geometry in display units, plus 'z' (the sketch-local height
    along the plane normal) when the point sits OFF the sketch plane."""
    if geo is None:
        return None
    z = safe(lambda: geo.z, 0.0) or 0.0
    rec = {"x": _round(geo.x, f), "y": _round(geo.y, f)}
    if abs(z) > _Z_EPS:
        rec["z"] = _round(z, f)
    return rec


def _line_geo(ln, f):
    s = safe(lambda: ln.startSketchPoint.geometry)
    e = safe(lambda: ln.endSketchPoint.geometry)
    return {"start": _xy(s, f), "end": _xy(e, f)}


def _texts(sketch, f):
    """Every SketchText as a 'text:<index>' entity record, in sketchTexts creation order."""
    # A positional walk: a slot that will not read holds its index with its fields None, since
    # dropping it would slide every later text onto a different id. SketchText.text/.height are
    # retired, so the string and height come off textParameter/heightParameter.
    out = []
    texts = safe(lambda: sketch.sketchTexts)
    for i in range(safe(lambda: texts.count, 0) if texts else 0):
        st = safe(lambda i=i: texts.item(i))
        # textParameter.expression is the string QUOTED for a literal and the BINDING for a bound
        # text ('d7'); textValue is what Fusion renders either way (measured). A bound text is the
        # pair disagreeing, so the expression is published only where it says something else.
        expr = safe(lambda st=st: st.textParameter.expression)
        rendered = safe(lambda st=st: st.textParameter.textValue)
        rec = {"id": f"text:{i}", "type": "text", "construction": False,
               "text": rendered if rendered is not None else _unquote(expr),
               "height": _round(safe(lambda st=st: st.heightParameter.value), f),
               "font": _font_read_back(st)}
        if expr is not None and rendered is not None and _unquote(expr) != rendered:
            rec["text_expression"] = expr
        bb = safe(lambda st=st: st.boundingBox)
        if bb is not None:
            rec["bounding_box"] = {"min": _xy(safe(lambda: bb.minPoint), f),
                                   "max": _xy(safe(lambda: bb.maxPoint), f)}
        out.append(rec)
    return out


# Control points ride INSIDE a row of the _XRAY_CAP-capped entity list, so a traced spline would
# multiply the payload past that bound; control_point_count carries the true total whatever is cut.
_CV_POINT_CAP = 64


def _curve_state(curve) -> dict:
    """The curve's independent fixed/reference/linked flags, null when unreadable."""
    return {"fixed": _common.read_flag(lambda: curve.isFixed),
            "reference": _common.read_flag(lambda: curve.isReference),
            "linked": _common.read_flag(lambda: curve.isLinked)}


def _curve_state_counts(sketch):
    """Uncapped curve-only state totals, null per flag when its census is incomplete."""
    curves = safe(lambda: list(sketch.sketchCurves))
    states = [_curve_state(curve) for curve in curves] if curves is not None else None
    return {f"{key}_curve_count": (sum(state[key] is True for state in states)
                                  if states is not None
                                  and all(state[key] is not None for state in states) else None)
            for key in ("fixed", "reference", "linked")}


def _entities(sketch, f):
    """List every entity with id, type, isConstruction, and key geometry, in display units (f = cm ->
    display-unit factor)."""
    out = []
    curves = safe(lambda: sketch.sketchCurves)
    construction = 0

    lines = safe(lambda: curves.sketchLines)
    for i in range(safe(lambda: lines.count, 0) if lines else 0):
        ln = lines.item(i)
        con = bool(safe(lambda ln=ln: ln.isConstruction, False))
        construction += 1 if con else 0
        rec = {"id": f"line:{i}", "type": "line", "construction": con,
               "centerline": _common.read_flag(lambda ln=ln: ln.isCenterLine), **_curve_state(ln)}
        rec.update(_line_geo(ln, f))
        out.append(rec)

    arcs = safe(lambda: curves.sketchArcs)
    for i in range(safe(lambda: arcs.count, 0) if arcs else 0):
        a = arcs.item(i)
        con = bool(safe(lambda a=a: a.isConstruction, False))
        construction += 1 if con else 0
        c = safe(lambda: a.centerSketchPoint.geometry)
        out.append({"id": f"arc:{i}", "type": "arc", "construction": con, **_curve_state(a),
        "center": _xy(c, f),
        "radius": _round(safe(lambda: a.radius), f)})

    circles = safe(lambda: curves.sketchCircles)
    for i in range(safe(lambda: circles.count, 0) if circles else 0):
        cc = circles.item(i)
        con = bool(safe(lambda cc=cc: cc.isConstruction, False))
        construction += 1 if con else 0
        c = safe(lambda: cc.centerSketchPoint.geometry)
        out.append({"id": f"circle:{i}", "type": "circle", "construction": con, **_curve_state(cc),
        "center": _xy(c, f),
        "radius": _round(safe(lambda: cc.radius), f)})

    ellipses = safe(lambda: curves.sketchEllipses)
    for i in range(safe(lambda: ellipses.count, 0) if ellipses else 0):
        el = ellipses.item(i)
        con = bool(safe(lambda el=el: el.isConstruction, False))
        construction += 1 if con else 0
        c = safe(lambda: el.centerSketchPoint.geometry)
        out.append({"id": f"ellipse:{i}", "type": "ellipse", "construction": con, **_curve_state(el),
        "center": _xy(c, f),
        "major_radius": _round(safe(lambda: el.majorAxisRadius), f),
        "minor_radius": _round(safe(lambda: el.minorAxisRadius), f)})

    ell_arcs = safe(lambda: curves.sketchEllipticalArcs)
    for i in range(safe(lambda: ell_arcs.count, 0) if ell_arcs else 0):
        ea = ell_arcs.item(i)
        con = bool(safe(lambda ea=ea: ea.isConstruction, False))
        construction += 1 if con else 0
        c = safe(lambda: ea.centerSketchPoint.geometry)
        out.append({"id": f"elliptical_arc:{i}", "type": "elliptical_arc", "construction": con,
        **_curve_state(ea), "center": _xy(c, f),
        "major_radius": _round(safe(lambda: ea.majorAxisRadius), f),
        "minor_radius": _round(safe(lambda: ea.minorAxisRadius), f)})

    conics = safe(lambda: curves.sketchConicCurves)
    for i in range(safe(lambda: conics.count, 0) if conics else 0):
        cn = conics.item(i)
        con = bool(safe(lambda cn=cn: cn.isConstruction, False))
        construction += 1 if con else 0
        # A conic is shaped by an APEX and a rho, not by a centre and a radius.
        apex = safe(lambda: cn.apexSketchPoint.geometry)
        out.append({"id": f"conic:{i}", "type": "conic", "construction": con, **_curve_state(cn),
        "apex": _xy(apex, f), "rho": _round(safe(lambda: cn.rhoValue), 1.0)})

    splines = safe(lambda: curves.sketchFittedSplines)
    for i in range(safe(lambda: splines.count, 0) if splines else 0):
        sp = splines.item(i)
        con = bool(safe(lambda sp=sp: sp.isConstruction, False))
        construction += 1 if con else 0
        fit_pts = safe(lambda sp=sp: sp.fitPoints)
        out.append({"id": f"spline:{i}", "type": "spline", "construction": con, **_curve_state(sp),
        "is_closed": safe(lambda sp=sp: bool(sp.isClosed)),
        "fit_point_count": safe(lambda fit_pts=fit_pts: fit_pts.count) if fit_pts is not None else None})

    cv_splines = safe(lambda: curves.sketchControlPointSplines)
    for i in range(safe(lambda: cv_splines.count, 0) if cv_splines else 0):
        cv = cv_splines.item(i)
        con = bool(safe(lambda cv=cv: cv.isConstruction, False))
        construction += 1 if con else 0
        # MEASURED: controlPoints is a SketchPointVector - a plain SEQUENCE whose .count and
        # .item(i) BOTH raise, so a collection-style read answers null on every spline. list() is
        # the protocol it does carry, and its members are ordinary SketchPoints.
        ctrl_pts = safe(lambda cv=cv: list(cv.controlPoints))
        # MEASURED on an SVG-traced spline: controlPoints reads EMPTY and .degree RAISES "Spline
        # has invalid intention degree". No spline is describable by zero control points, so an
        # empty read publishes unknown rather than a 0 a caller would compare against.
        described = bool(ctrl_pts)
        # SketchControlPointSpline has no isClosed (live-verified).
        rec = {"id": f"cv_spline:{i}", "type": "cv_spline", "construction": con, **_curve_state(cv),
               "degree": safe(lambda cv=cv: cv.degree),
               "control_point_count": len(ctrl_pts) if described else None,
               "control_points": ([_xy(safe(lambda p=p: p.geometry), f)
                                   for p in ctrl_pts[:_CV_POINT_CAP]] if described else None)}
        if described and len(ctrl_pts) > _CV_POINT_CAP:
            rec["control_points_truncated"] = True
        out.append(rec)

    fixed_splines = safe(lambda: curves.sketchFixedSplines)
    for i in range(safe(lambda: fixed_splines.count, 0) if fixed_splines else 0):
        fx = fixed_splines.item(i)
        con = bool(safe(lambda fx=fx: fx.isConstruction, False))
        construction += 1 if con else 0
        # SketchFixedSpline exposes no isClosed/fitPoints/degree (live-verified).
        out.append({"id": f"fixed_spline:{i}", "type": "fixed_spline", "construction": con,
                    **_curve_state(fx)})

    pts = safe(lambda: sketch.sketchPoints)
    origin = safe(lambda: sketch.originPoint)
    for i in range(safe(lambda: pts.count, 0) if pts else 0):
        g = safe(lambda i=i: pts.item(i).geometry)
        rec = {"id": f"point:{i}", "type": "point", "construction": False,
        "position": _xy(g, f)}
        # the sketch ORIGIN is a real, addressable point entity - flag it so an agent anchoring a
        # constraint to the origin does not have to infer which (0,0) point it is. Proxy equality
        # (not `is`) is the sanctioned entity comparison.
        if origin is not None and safe(lambda i=i: pts.item(i) == origin):
            rec["origin"] = True
        out.append(rec)

    out.extend(_texts(sketch, f))
    return out, construction


def _describe_constraint(c, sketch, token_ids):
    """Return a constraint's type and native-identity-matched sketch entity ids."""
    cls = type(c).__name__
    friendly, attrs = _CONSTRAINT_REFS.get(cls, (cls.replace("Constraint", "").lower(), ()))
    ids = []
    for attr in attrs:
        ent = safe(lambda attr=attr: getattr(c, attr))
        if ent is None:
            continue
        items = _vector_items(ent)
        if items is not None:        # a vector of entities (e.g. PolygonConstraint.lines)
            for sub in items:
                ids.append(_identical_id(sketch, sub, token_ids))
        else:
            ids.append(_identical_id(sketch, ent, token_ids))
    return {"type": friendly, "entities": ids}


def _vector_items(ent):
    """If ent is a vector/collection of entities, return a list of them; else None. Handles both the
    .count/.item collection idiom AND the SketchLineVector len()/[i] idiom (used by PolygonConstraint
    .lines). A single BRep/sketch entity is NOT a vector - so a plain SketchLine returns None."""
    # A single sketch entity exposes entityToken; treat that as NOT a vector even if it has len.
    if safe(lambda: ent.entityToken) is not None:
        return None
    n = safe(lambda: ent.count, None)
    if n is not None and safe(lambda: ent.item) is not None:
        return [ent.item(i) for i in range(n)]
    n = safe(lambda: len(ent), None)
    if n is not None:
        return [ent[i] for i in range(n)]
    return None


def compute_deferred(sketch):
    """Whether this sketch's compute is DEFERRED - True, False, or None when the flag will not read
    (never coerced: an unreadable flag is not a confident 'no')."""
    return _common.read_flag(lambda: sketch.isComputeDeferred)


# The one sentence a stale-profile read owes. Deferring compute is what sketch_add_geometry does
# around a draw, so the tool that set the flag is also the one that clears it.
DEFERRED_NOTE = (
    "Compute is DEFERRED (isComputeDeferred reads true): profile_count can be stale. A read does "
    "not resume it - draw with sketch_add_geometry, or set isComputeDeferred=false with "
    "sys_execute_script.")


def _profiles(sketch, f):
    """One record (index / area / centroid / loop_count / handle) per closed region, largest area
    first, the handle a ProfileRef for model_extrude / model_revolve / model_loft; f is the
    cm -> display-unit factor. None when compute is DEFERRED - the walk reads a stale profile set."""
    if compute_deferred(sketch) is True:
        return None
    profs = safe(lambda: sketch.profiles)
    n = safe(lambda: profs.count, 0) if profs else 0
    out = []
    sk_name = safe(lambda: sketch.name) or ""
    for i in range(n):
        p = profs.item(i)
        ap = safe(lambda p=p: p.areaProperties())
        area = safe(lambda: ap.area) if ap else None
        c = safe(lambda: ap.centroid) if ap else None
        # The centroid is COMPONENT-LOCAL (cm), not world, and an assembly-context proxy reads the
        # same point; it doubles as the handle's locator.
        pos = (c.x, c.y, c.z) if c else None
        loops = safe(lambda p=p: p.profileLoops.count)
        # MEASURED: a multi-loop profile's token answers nothing in the root and itself plus its
        # island profiles in a component, so the locator settles it; its RAW cm area tells
        # same-centroid profiles apart. A ':' or ',' in the name would garble its parse.
        safe_name = sk_name if (":" not in sk_name and "," not in sk_name) else ""
        kind = f"profile[{safe_name}~{area:.4f}]" if area is not None else "profile"
        out.append({
            "index": i,
            "area": _round(area, f * f),
            "centroid": [_round(c.x, f), _round(c.y, f), _round(c.z, f)] if c else None,
            "loop_count": loops,
            "handle": _inputs.make_handle(p, kind, pos) if pos else safe(lambda: p.entityToken),
        })
    # A positive scale factor preserves order, so sorting on the scaled 'area' still agrees.
    out.sort(key=lambda r: (r["area"] is None, -(r["area"] or 0)))
    return out


_XRAY_CAP = 200   # a dense sketch can carry hundreds of entities/constraints/dimensions; bound each
_ENTITY_PAGE_DEFAULT = 50
_ENTITY_COLLECTIONS = (("line", "lines"), ("arc", "arcs"), ("circle", "circles"),
                       ("ellipse", "ellipses"), ("elliptical_arc", "elliptical_arcs"),
                       ("conic", "conics"), ("spline", "splines"),
                       ("cv_spline", "cv_splines"), ("fixed_spline", "fixed_splines"),
                       ("point", "points"), ("text", "texts"))


def _dimension_value(raw, is_angle, f):
    """A dimension's value in the unit its row publishes: DEGREES for an angular dimension, whose
    parameter reads DATABASE units (radians), else the caller's display unit."""
    if raw is None:
        return None
    return _round(math.degrees(raw), 1.0) if is_angle else _round(raw, f)


def _entity_xray(sketch, f, unit, counts, entity_offset=0, entity_limit=_ENTITY_PAGE_DEFAULT):
    """Entity pages, capped constraint/dimension rows, and uncapped construction/driving counts."""
    token_ids = sketch_token_ids(sketch)
    entities, construction_count = _entities(sketch, f)

    constraints = []
    gc = safe(lambda: sketch.geometricConstraints)
    for i in range(safe(lambda: gc.count, 0) if gc else 0):
        constraints.append(_describe_constraint(gc.item(i), sketch, token_ids))

    dimensions = []
    sd = safe(lambda: sketch.sketchDimensions)
    for i in range(safe(lambda: sd.count, 0) if sd else 0):
        d = sd.item(i)
        par = safe(lambda d=d: d.parameter)
        raw_value = safe(lambda: par.value) if par else None
        # An ANGULAR dimension's value is radians, not a length, so it takes its own conversion.
        is_angle = type(d).__name__ == "SketchAngularDimension"
        driving, driving_unread = _common.read_optional(lambda d=d: d.isDriving)
        if driving is not None and type(driving) is not bool:
            driving, driving_unread = None, "isDriving did not read a boolean"
        label = point_cm(safe(lambda d=d: d.textPosition))
        if label is not None and not all(math.isfinite(v) for v in label):
            label = None
        dimensions.append({
            "name": safe(lambda: par.name) if par else None,
            "value": _dimension_value(raw_value, is_angle, f),
            # The frame 'value' is in - never the caller's length unit for an ANGLE.
            "value_units": "deg" if is_angle else unit,
            "expression": safe(lambda: par.expression) if par else None,
            # driving = constrains geometry; a driven/reference dim just MEASURES (doesn't lock).
            "driving": driving,
            "text_position": ({"x": _round(label[0], f), "y": _round(label[1], f),
                               "z": _round(label[2], f)} if label is not None else None),
            "type": type(d).__name__.replace("SketchDimension", "").replace("Dimension", "").lower(),
            "entities": dimension_entities(sketch, d, token_ids) if i < _XRAY_CAP else None,
        })
        if driving_unread:
            dimensions[-1]["driving_unread"] = driving_unread
    driving_dims = (None if any(d["driving"] is None for d in dimensions)
                    else sum(1 for d in dimensions if d["driving"]))

    end = entity_offset + entity_limit
    entities_out = [row for row in entities
                    if entity_offset <= int(row["id"].rpartition(":")[2]) < end]
    entity_pages = {plural: {"count": counts[plural], "offset": entity_offset,
                             "next_offset": end if end < counts[plural] else None}
                    for _kind, plural in _ENTITY_COLLECTIONS}
    constraints_out = constraints[:_XRAY_CAP]
    dimensions_out = dimensions[:_XRAY_CAP]
    truncated = (len(entities_out) < len(entities) or len(constraints_out) < len(constraints)
                 or len(dimensions_out) < len(dimensions))
    return (entities_out, constraints_out, dimensions_out, construction_count, driving_dims,
            truncated, entity_pages)


# The occurrence half of the 'component' scope's vocabulary, resolved through the SHARED
# ambiguity-refusing resolver (the same kind doc_insert_occurrence's 'into_component' takes) rather
# than a local path matcher. Its .name is the input's name, so its refusals quote 'component' back.
_SCOPE_OCCURRENCE = _inputs.OccurrenceRef(
    "component", description="Occurrence whose component to read.")


def _scope_hits(design, raw):
    """(the components a 'component' scope selects, the OCCURRENCE it named or None, error_or_None):
    blank selects every component, a NAME every component wearing it, an occurrence fullPathName or
    handle the one component that occurrence places - the only vocabulary naming a placement."""
    # Fusion dedupes a component RENAME but not an INSERT, so two referenced documents each bring
    # their own 'Frame' and only the occurrence path tells those two components apart.
    want = (raw or "").strip()
    if not want:
        return _common.all_components(design), None, None
    comps, name_error = _common.components_in_scope(design, want)
    if not name_error:
        return comps, None, None
    occ, occ_error = _SCOPE_OCCURRENCE.resolve(want)
    if occ is not None:
        comp = safe(lambda: occ.component)
        if comp is not None:
            return [comp], occ, None
        # The occurrence RESOLVED and reading its component failed, so ``occ_error`` is None here.
        # ``broken_reference`` is the ONE unresolved-external-reference detector; a component that
        # reads None without raising has no detail to quote.
        _is_broken, detail = _common.broken_reference(occ)
        where = safe(lambda: occ.fullPathName) or want
        because = f": {detail}" if detail else " (the read returned nothing)"
        return None, None, (f"'{want}' resolved to occurrence '{where}', but its component could "
                            f"not be read{because}. design_get(include=['tree']) reports "
                            "occurrences whose referenced component will not load.")
    return None, None, (f"{name_error} As an occurrence path or handle it did not resolve either: "
                        f"{occ_error}")


def scope_components(design, raw):
    """The component(s) a 'component' scope selects, as (components, error_or_None)."""
    comps, _occ, err = _scope_hits(design, raw)
    return comps, err


def scope_component(design, raw, input_name="component"):
    """The ONE component a by-name sketch read scopes to, as (component, the occurrence the scope
    named or None, error_or_None); a name SEVERAL components wear is refused. ``input_name`` is the
    scope input the refusals quote back, which is not always spelled 'component'."""
    want = (raw or "").strip()
    if not want:
        return None, None, (f"Provide a component name in '{input_name}', or omit it to search the "
                            "whole design.")
    comps, occ, err = _scope_hits(design, want)
    if err:
        return None, None, err
    if len(comps) == 1:
        return comps[0], occ, None
    # The match is case-insensitive and strip-tolerant, so 'beta' hits 'Beta' and 'BETA'; the
    # spellings as read are what tells the hits apart.
    spelled = _common.spelled_as_read(comps, want)
    # The paths come from the occurrence WALK filtered by the occurrence's own component name.
    # Two distinct components can read ONE entityToken, so pairing matched components against the
    # walk instead hands every 'Frame' every other 'Frame''s path.
    paths = _common.placement_paths_named(design, want)
    if paths:
        return None, None, (f"{len(comps)} components match '{want}'{spelled}, so the name does not "
                            "identify one of them. Scope by one of their occurrence paths instead: "
                            f"{_common.named_with_remainder(paths)} - '{input_name}' also takes an "
                            "occurrence fullPathName or handle (design_get(include=['tree']) emits "
                            "both).")
    return None, None, (f"{len(comps)} components match '{want}'{spelled}, and no occurrence places "
                        "any of them, so nothing tells them apart. Read them with sketch_get("
                        "component='" + want + "') and no 'sketch_name'.")


# ── the 'component' scope as a WRITE tool's input - the read's scope, wired for by-name EDITS ────

def scope_remedy(input_name="component"):
    """The closing sentence a shared-name refusal carries, naming ``input_name`` as the input that
    narrows THIS sketch reference (see _common.find_sketch's ``remedy``)."""
    return (f"Name the one you mean by passing its owning component as '{input_name}' (sketch_get "
            "lists each sketch's owning component).")

# The vocabulary half of the scope's description: what it accepts. Shared by every spelling of the
# input, so a second scope on one tool cannot drift from the first. WHY it exists, and the
# design_get pointer that mints an occurrence path, are in scope_component's refusals.
_SCOPE_VOCABULARY = "name, occurrence path or handle."

# The ONE wire declaration of that input: tool.add_input_property(*_sketch_detail.COMPONENT_SCOPE),
# resolved through scoped_sketch / scoped_or_recent_sketch below.
COMPONENT_SCOPE = ("component", {"type": "string", "description":
                   "Sketch component: " + _SCOPE_VOCABULARY})


def component_scope(input_name, narrows=""):
    """(name, schema) for that same scope under a DIFFERENT input name - for a tool whose own
    'component' already names something else, or that scopes a SECOND sketch reference.
    ``narrows`` names the sketch input this scope applies to."""
    lead = (f"The component of '{narrows}': " if narrows
            else "Sketch component: ")
    return input_name, {"type": "string", "description": lead + _SCOPE_VOCABULARY}


def _scoped_component(design, raw, input_name="component"):
    """(component, error_or_None) for a scope a WRITE was given - scope_component without the
    occurrence, which only a frame read needs."""
    comp, _occ, err = scope_component(design, raw, input_name)
    return comp, err


def scoped_sketch(design, name, component, input_name="component"):
    """(sketch, error_or_None): ONE sketch by name for an EDIT, design-wide with no ``component``
    and out of that component's own collection with one. A scope that WAS passed is always resolved
    and validated, so a component this design does not hold refuses rather than being dropped.
    ``input_name`` names the scope input in all three refusals this can produce."""
    scope = (component or "").strip()
    if not scope:
        return _common.find_sketch(design, name, remedy=scope_remedy(input_name))
    comp, scope_error = _scoped_component(design, scope, input_name)
    if scope_error:
        return None, scope_error
    return _common.find_sketch_in(design, name, comp, scope, input_name)


def scoped_or_recent_sketch(design, name, component, input_name="component"):
    """(sketch, the stripped requested name or None, error_or_None): scoped_sketch's contract with
    a blank NAME meaning "the most recent sketch" - of the scoped component when one was passed, of
    the active component when none was."""
    scope = (component or "").strip()
    nm = (name or "").strip()
    if not scope:
        return _common.find_or_recent_sketch(design, name, remedy=scope_remedy(input_name))
    comp, scope_error = _scoped_component(design, scope, input_name)
    if scope_error:
        return None, (nm or None), scope_error
    if nm:
        sketch, refusal = _common.find_sketch_in(design, nm, comp, scope, input_name)
        return sketch, nm, refusal
    coll = safe(lambda: comp.sketches)
    n = safe(lambda: coll.count, 0) if coll is not None else 0
    if not n:
        read_name = safe(lambda: comp.name)
        where = f"'{read_name}'" if read_name else f"the one '{scope}' resolved to"
        return None, None, (f"Component {where} holds no sketches, so it has no most recent one to "
                            f"act on (scope '{scope}'). Name a sketch in 'sketch_name', or create "
                            "one with sketch_create.")
    return safe(lambda i=n - 1: coll.item(i)), None, None


def _detail_engine():
    """This module, looked up in the module table by NAME at call time - the package attribute is
    bound once, so swapping the engine in the module table would not reach it."""
    return importlib.import_module("._sketch_detail", __package__)


# What referencePlane raises on a FACE-attached sketch, measured on 2705.1.15: '3 : referencePlane
# is a BRefFace - need to roll timeline back before sketch'. The text is matched because it is what
# tells that state from any OTHER read failure, which claims nothing about a face.
_BREP_FACE_RAISE = "brefface"


def _plane_read(sketch):
    """(the sketch's referencePlane, whether the read raised NAMING a BRepFace)."""
    try:
        return sketch.referencePlane, False
    except Exception as e:
        return None, _BREP_FACE_RAISE in str(e).lower()


def _plane_name(sketch) -> str:
    rp, _on_face = _plane_read(sketch)
    return safe(lambda: rp.name) if rp is not None else None


def on_a_face(sketch) -> bool:
    """True when this sketch sits on a BRepFace rather than a construction plane. Costs no roll -
    face_support names WHICH face, and does."""
    return _plane_read(sketch)[1]


def face_record(face=None):
    """{body, handle} - the ONE shape a sketch's face support is published as, with a null member
    per read that did not answer (no face at all answers both null). The handle is find_geometry's
    own spelling, so every face-handle input takes it."""
    centroid = _geom._coords(safe(lambda: face.centroid)) if face is not None else None
    return {"body": safe(lambda: face.body.name) if face is not None else None,
            "handle": _inputs.make_handle(face, "planar_face", centroid) if centroid else None}


def face_support(sketch, design):
    """(face_record for the FACE a face-attached sketch sits on, a marker clause) - the record's
    members are null where the face did not read, and it is None only when the roll never ran."""
    # ONE roll: referencePlane answers the BRepFace only before the sketch's own row. MEASURED on a
    # freshly extruded box: the token minted under the roll resolved to that same face after the
    # marker was restored.
    def read():
        return face_record(safe(lambda: sketch.referencePlane))
    return _common.rolled_to(design, sketch, read, "the face the sketch sits on")


def _sketch_summary(sketch) -> dict:
    """The per-sketch row (counts + visibility) every sketch payload carries."""
    curves = safe(lambda: sketch.sketchCurves)
    row = {
    "name": safe(lambda: sketch.name),
    "plane": _plane_name(sketch),
    # A BOOLEAN under its own key: the census never rolls the timeline (it would roll once per
    # sketch), so it can only FLAG the state. sketch_get(sketch_name=...) rolls once and publishes
    # the face itself under 'on_face', which therefore never changes type between the two reads.
    **({"on_face_flagged": True} if on_a_face(sketch) else {}),
    "line_count": safe(lambda: curves.sketchLines.count, 0) if curves else 0,
    "circle_count": safe(lambda: curves.sketchCircles.count, 0) if curves else 0,
    "arc_count": safe(lambda: curves.sketchArcs.count, 0) if curves else 0,
    "point_count": safe(lambda: sketch.sketchPoints.count, 0),
    "profile_count": safe(lambda: sketch.profiles.count, 0),
    "is_visible": safe(lambda: sketch.isVisible),
    "constraint_count": _common.counted(lambda: sketch.geometricConstraints.count),
    **_curve_state_counts(sketch),
    }
    # While compute is deferred the profile_count above is the pre-deferral one, and no read of
    # this sketch resumes compute.
    if compute_deferred(sketch) is True:
        row["compute_deferred"] = True
        row["profiles_stale"] = True
    return row


# ── the sketch-space transform both sketch_move and sketch_copy place geometry through ──────────

_ENTITIES = {"type": "string", "description": "Refs to transform, comma-separated."}

_DX = _inputs.Distance("dx", allow_zero=True, default=0.0,
                       description="Translation along sketch X.")
_DY = _inputs.Distance("dy", allow_zero=True, default=0.0,
                       description="Translation along sketch Y.")
_DZ = _inputs.Distance("dz", allow_zero=True, default=0.0,
                       description="Translation along sketch Z, off the plane.")
_CENTER_X = _inputs.Distance("center_x", allow_zero=True, default=0.0,
                             description="Rotate/scale anchor X.")
_CENTER_Y = _inputs.Distance("center_y", allow_zero=True, default=0.0,
                             description="Rotate/scale anchor Y.")
_CENTER_Z = _inputs.Distance("center_z", allow_zero=True, default=0.0,
                            description="Rotation pivot Z.")

_TRANSFORM_INPUTS = (
    ("rotation_deg", {"type": "number", "description": "Rotation about the anchor, degrees CCW."}),
    ("rotation_axis", {"type": "array", "items": {"type": "number"},
                       "minItems": 3, "maxItems": 3,
                       "description": "Local axis [x,y,z]; default [0,0,1]."}),
    ("scale_factor", {"type": "number", "description": "Uniform scale about the anchor; > 0."}),
)


def _object_collection(ents, refs):
    """(ObjectCollection, error) holding the entities to transform."""
    # Sketch.move/copy take an ObjectCollection and raise TypeError on a plain list; the
    # neighbouring GeometricConstraints.createCircularPatternInput takes the OPPOSITE container.
    coll = adsk.core.ObjectCollection.create()
    for ent, ref in zip(ents, refs):
        if not coll.add(ent):
            return None, f"The sketch entity '{ref}' was refused by the collection to transform."
    return coll, None


def _transform(dx_cm, dy_cm, angle_deg, factor, cx_cm, cy_cm, dz_cm=0.0,
               axis=(0.0, 0.0, 1.0), cz_cm=0.0):
    """Return a sketch-space scale/rotation about a 3D pivot, then XYZ translation."""
    theta = math.radians(float(angle_deg or 0.0))
    m = adsk.core.Matrix3D.create()
    applied = [m.setToRotation(theta, adsk.core.Vector3D.create(*axis),
                               adsk.core.Point3D.create(0.0, 0.0, 0.0))]
    pivot = (cx_cm, cy_cm, cz_cm)
    turned = [sum(m.getCell(r, c) * pivot[c] for c in range(3)) for r in range(3)]
    if factor != 1.0:
        # scaling the whole 3x3 linear block is symmetric in row/column, so it needs no assumption
        # about which index of the 4x4 holds the translation.
        applied += [m.setCell(r, c, m.getCell(r, c) * factor)
                    for r in range(3) for c in range(3)]
    m.translation = adsk.core.Vector3D.create(*(
        pivot[r] + (dx_cm, dy_cm, dz_cm)[r] - factor * turned[r] for r in range(3)))
    if not all(applied):
        return None, "Fusion refused a cell of the transform matrix, so nothing was transformed."
    return m, None


def _rotation_axis(raw, angle):
    """A finite unit sketch-space axis, or an input error."""
    if raw is None:
        return (0.0, 0.0, 1.0), None
    if not angle:
        return None, "'rotation_axis' needs a nonzero 'rotation_deg'; it would be ignored."
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None, f"'rotation_axis' needs three numbers [x,y,z]; got {raw!r}."
    try:
        values = tuple(float(v) for v in raw)
    except (TypeError, ValueError):
        return None, f"'rotation_axis' needs three numbers [x,y,z]; got {raw!r}."
    if not all(math.isfinite(v) for v in values):
        return None, f"'rotation_axis' must be finite; got {raw!r}."
    length = math.hypot(*values)
    if length <= 1e-12 or not math.isfinite(length):
        return None, f"'rotation_axis' must be nonzero and finite; got {raw!r}."
    return tuple(v / length for v in values), None


def transform_points_match(before, after, matrix, tolerance=1e-6):
    """Whether readable endpoint samples landed at the matrix's expected XYZ positions."""
    if before is None or after is None:
        return None
    pairs = []
    for a, b in zip(before[2:], after[2:]):
        if a is not None:
            if b is None:
                return None
            pairs.append((a, b))
    if not pairs:
        return None
    offset = matrix.translation
    shifts = (offset.x, offset.y, offset.z)
    return all(abs(sum(matrix.getCell(r, c) * a[c] for c in range(3)) + shifts[r] - b[r])
               <= tolerance for a, b in pairs for r in range(3))


def transform_points_readable(position):
    """Whether a sketch entity has an endpoint or own geometry for XYZ verification."""
    return position is not None and any(mark is not None for mark in position[2:])


def _identity_still_copies(design, sketch, target_sketch, target_component):
    """True unless target_sketch is blank or resolves (by native identity) to `sketch` itself - an
    identity transform still lands a copy in a genuinely different target sketch."""
    want = (target_sketch or "").strip()
    if not want:
        return False
    target, _err = scoped_sketch(design, want, target_component, "target_component")
    if target is None:
        return True   # let the real target-resolution error surface downstream, not this refusal
    a, b = _common.native_identity(sketch), _common.native_identity(target)
    return not (a is not None and b is not None and a == b)


def _prepare(sketch_name, entities, units, dx, dy, rotation_deg, center_x, center_y, scale_factor,
             component="", target_sketch="", target_component="", dz=None,
             rotation_axis=None, center_z=None):
    """Return resolved transform operands and matrix, or a refusal before mutation."""
    blank = (None,) * 7
    k, uerr = _inputs.UNITS.resolve(units)
    if uerr:
        return blank + (error(uerr),)
    unit = (units or "mm").strip().lower()

    design = _common.design()
    if not design:
        return blank + (error("No active design. Create or open a document first (see doc_new)."),)
    sketch, requested, refusal = scoped_or_recent_sketch(design, sketch_name, component)
    if refusal:
        return blank + (error(refusal),)
    if not sketch:
        if requested:
            return blank + (error(f"No sketch named '{requested}'. Available: " + (
                ", ".join(n for n in _common.all_sketch_names(design) if n) or "(none)")),)
        return blank + (error("No sketch to transform. Draw one first with sketch_create + "
                              "sketch_add_geometry."),)

    ents, refs, rerr = _common.resolve_entity_refs(sketch, entities)
    if rerr:
        return blank + (error(rerr),)
    if not refs:
        return blank + (error("'entities' is required - comma-separated '<type>:<index>' refs (e.g. "
                              "'line:0,arc:1') from sketch_get(include_entities=true)."),)

    try:
        factor = float(scale_factor if scale_factor is not None else 1.0)
    except (TypeError, ValueError):
        return blank + (error(f"'scale_factor' must be a number, got {scale_factor!r}."),)
    if not math.isfinite(factor) or factor <= 0:
        return blank + (error(f"'scale_factor' must be greater than 0, got {factor}. A uniform "
                              "scale cannot mirror geometry; use sketch_copy with mirror_line."),)
    try:
        angle = float(rotation_deg if rotation_deg is not None else 0.0)
    except (TypeError, ValueError):
        return blank + (error(f"'rotation_deg' must be a number, got {rotation_deg!r}."),)
    if not math.isfinite(angle):
        return blank + (error(f"'rotation_deg' must be finite; got {rotation_deg!r}."),)
    axis, aerr = _rotation_axis(rotation_axis, angle)
    if aerr:
        return blank + (error(aerr),)
    if (center_z is not None and factor == 1.0
            and (not angle or abs(axis[0]) + abs(axis[1]) <= 1e-12)):
        return blank + (error("'center_z' needs scaling or rotation about an axis with X/Y "
                              "direction; it would be ignored."),)

    lengths = {}
    for kind, raw in ((_DX, dx), (_DY, dy), (_DZ, dz), (_CENTER_X, center_x),
                      (_CENTER_Y, center_y), (_CENTER_Z, center_z)):
        value, lerr = kind.resolve_scaled(raw, k)
        if lerr:
            return blank + (error(lerr),)
        lengths[kind.name] = float(value or 0.0)
    if not (lengths["dx"] or lengths["dy"] or lengths["dz"] or angle
            or factor != 1.0) and not _identity_still_copies(
            design, sketch, target_sketch, target_component):
        return blank + (error("Nothing to apply: give a 'dx'/'dy'/'dz' translation, a 'rotation_deg', "
                              "or a 'scale_factor' other than 1."),)

    coll, cerr = _object_collection(ents, refs)
    if cerr:
        return blank + (error(cerr),)
    matrix, merr = _transform(lengths["dx"], lengths["dy"], angle, factor,
                              lengths["center_x"], lengths["center_y"], lengths["dz"],
                              axis, lengths["center_z"])
    if merr:
        return blank + (error(merr),)
    return design, sketch, ents, refs, coll, matrix, unit, None


def _requested(unit, dx, dy, rotation_deg, scale_factor, dz=None,
               rotation_axis=None, center_z=None):
    """Return requested transform values in caller units, including nonzero dz."""
    out = {"units": unit, "dx": float(dx or 0.0), "dy": float(dy or 0.0),
           "rotation_deg": float(rotation_deg or 0.0),
           "scale_factor": float(scale_factor if scale_factor is not None else 1.0)}
    if dz:
        out["dz"] = float(dz)
    if rotation_axis is not None:
        out["rotation_axis"] = list(rotation_axis)
    if center_z is not None:
        out["center_z"] = float(center_z)
    return out


def _transform_wire(tool):
    """The transform inputs both tools share, in one order."""
    tool = (tool.add_input_property("entities", dict(_ENTITIES))
                .add_required_input("entities")
                .add_input_property(*_DX.as_property())
                .add_input_property(*_DY.as_property())
                .add_input_property(*_DZ.as_property())
                .add_input_property(*_CENTER_X.as_property())
                .add_input_property(*_CENTER_Y.as_property()))
    tool = tool.add_input_property(*_CENTER_Z.as_property())
    for name, schema in _TRANSFORM_INPUTS:
        tool = tool.add_input_property(name, dict(schema))
    return tool.add_input_property(*_inputs.UNITS.as_property()).strict_schema()


def handler(sketch_name: str = "", include_entities: bool = False, units: str = "mm",
            component: str = "", entity_offset: int = 0, max_results: int = 0) -> dict:
    """Read one sketch: light overview by default, the full entity/constraint/dimension X-ray with
    include_entities=true. 'component' scopes the name to one component. Lengths/areas are reported
    in 'units' (mm default; area = units^2)."""
    unit = (units or "mm").strip().lower()
    f = _common.CM_TO_UNIT.get(unit)
    if f is None:
        return error(f"Unknown units '{units}'. Valid: mm, cm, in.")

    design = _common.design()
    if not design:
        return error("No active design.")

    name = (sketch_name or "").strip()
    if not name:
        names = all_sketch_names(design)
        return error("Provide 'sketch_name'. Available: " + (", ".join(n for n in names if n) or "(none)"))
    scope = (component or "").strip()
    # The placement this read reached the sketch through, when the scope named one; the frame's
    # lift into THIS document's world runs on it.
    host_occurrence = None
    if scope:
        scoped, host_occurrence, scope_error = scope_component(design, scope)
        if scope_error:
            return error(scope_error)
        sketch, refusal = _common.find_sketch_in(design, name, scoped, scope)
        if refusal:
            return error(refusal)
    else:
        sketch, ambiguous = find_sketch(design, name, remedy=scope_remedy())
        if ambiguous:
            return error(ambiguous)
    if not sketch:
        # 'Available' renders a shared name as "<sketch> (<component>)", which is NOT a spelling
        # this tool resolves - the sentence converts it into the call that does.
        names = all_sketch_names(design)
        return error(f"No sketch named '{name}'. Available: "
                     + (", ".join(n for n in names if n) or "(none)")
                     + ". A name listed as \"<sketch> (<component>)\" is one several components "
                       "carry: pass the sketch name alone with component='<component>'.")

    counts = {
    "lines": safe(lambda: sketch.sketchCurves.sketchLines.count, 0),
    "arcs": safe(lambda: sketch.sketchCurves.sketchArcs.count, 0),
    "circles": safe(lambda: sketch.sketchCurves.sketchCircles.count, 0),
    "ellipses": safe(lambda: sketch.sketchCurves.sketchEllipses.count, 0),
    "elliptical_arcs": safe(lambda: sketch.sketchCurves.sketchEllipticalArcs.count, 0),
    "conics": safe(lambda: sketch.sketchCurves.sketchConicCurves.count, 0),
    "points": safe(lambda: sketch.sketchPoints.count, 0),
    "splines": safe(lambda: sketch.sketchCurves.sketchFittedSplines.count, 0),
    "cv_splines": safe(lambda: sketch.sketchCurves.sketchControlPointSplines.count, 0),
    "fixed_splines": safe(lambda: sketch.sketchCurves.sketchFixedSplines.count, 0),
    # sketchTexts is not a sketchCurves sub-collection and needs its own count.
    "texts": safe(lambda: sketch.sketchTexts.count, 0),
    }
    fully = safe(lambda: sketch.isFullyConstrained)
    constraint_count = _common.counted(lambda: sketch.geometricConstraints.count)
    dim_count = safe(lambda: sketch.sketchDimensions.count, 0)

    profiles = _profiles(sketch, f)
    # ONE sketch was named, so ONE roll names the face it sits on rather than leaving plane null.
    sits_on_a_face = on_a_face(sketch)
    clean_before = sits_on_a_face and _view_common.document_modified() is False
    face, marker_clause = face_support(sketch, design) if sits_on_a_face else (None, None)
    # MEASURED: that roll flips a saved, clean document to isModified true.
    dirtied = clean_before and _view_common.document_modified() is True
    out = {
        "sketch": safe(lambda: sketch.name),
        "component": safe(lambda: sketch.parentComponent.name),
        "plane": _plane_name(sketch),
        # The only DOF signal the API exposes - no DOF count, no over-constrained flag.
        "is_fully_constrained": bool(fully) if fully is not None else None,
        "counts": counts,
        "constraint_count": constraint_count,
        **_curve_state_counts(sketch),
        "dimension_count": dim_count,
        "profile_count": safe(lambda: sketch.profiles.count, 0),
        "units": unit,
        # Every x/y below is sketch-LOCAL; the frame is what places them. safe(): a plane read that
        # raises reports frame null rather than sinking the whole read.
        "frame": safe(lambda: sketch_world_frame(sketch, design, host_occurrence)),
    }
    if profiles is None:
        # The flag stands in for the list, beside the profile_count it leaves stale.
        out["compute_deferred"] = True
        out["profiles_stale"] = True
    else:
        out["profiles"] = profiles
    face_note = ""
    if sits_on_a_face:
        # ONE shape on every face-attached path: the record, with a null member per read that did
        # not answer. A roll that never ran publishes it all-null rather than a different type.
        out["on_face"] = face if face is not None else face_record()
        face_note = " 'plane' is null because this sketch sits on a FACE, not a construction plane."
        face_note += (f" 'on_face' names body '{out['on_face']['body']}'."
                      if out["on_face"]["body"]
                      else " The body it sits on did not read back.")
        face_note += (" 'on_face' carries that face's handle, which model_offset_face / "
                      "sketch_create take." if out["on_face"]["handle"]
                      else " No handle could be minted for that face.")
    if marker_clause:
        out["timeline_marker_unrestored"] = True
        face_note += " " + marker_clause + "."
    if dirtied:
        out["document_modified"] = True
        face_note += (" The document read unmodified before this read rolled the timeline to the "
                      "sketch and back to name its face, and reads modified after it.")
    lead = DEFERRED_NOTE + " " if profiles is None else ""

    if not include_entities:
        out["note"] = (lead + "Overview only, lengths in 'units' (area=units^2). "
                       + frame_space_note(out.get("frame")) + face_note
                       + " For the full entity/constraint/dimension X-ray, call again with "
                       "include_entities=true.")
        return ok(out)

    entity_limit = min(max_results or _ENTITY_PAGE_DEFAULT, _XRAY_CAP)
    entities, constraints, dimensions, construction_count, driving_dims, truncated, entity_pages = (
        _entity_xray(sketch, f, unit, counts, entity_offset, entity_limit))
    framed = safe(lambda: _frame_context(sketch, design, host_occurrence))
    placed = bool(framed) and framed[1] == WORLD_SPACE
    _entity_handles(sketch, entities,
                    safe(lambda: framed[0].assemblyContext) if placed else None, placed)
    note = (lead + "Full X-ray, lengths in 'units'. Entity coordinates are sketch-LOCAL; "
                 + frame_space_note(out.get("frame")) + face_note
                 + " Entity ids ('line:0', ...) match sketch_constrain "
                 "/ extrude refs. A point off the sketch plane carries a 'z'; origin:true is the "
                 "sketch ORIGIN. is_fully_constrained=false means free DOF remain; a dimension "
                 "driving=false only measures. A 'text:<i>' id is what "
                 "sketch_set_text(index=<i>) edits and sketch_delete_entity removes.")
    if placed:
        note += (" A point row's 'handle' goes in model_construction's 'points'/'to_object' and a "
                 "line row's in its 'axis' and two_edges' 'edges'; a circle's or arc's centre goes "
                 "in as '<sketch>/<id>:center'. An 'id' is a position in the current collection.")
    elif any("handle" in e for e in entities):
        note += " 'handle' is null on every row until the instance is named as above."
    if any(e.get("reference") for e in entities):
        note += (" reference:true marks reference geometry; linked:true marks an external or API-driven link.")
    if any("?" in (c.get("entities") or []) for c in constraints + dimensions):
        note += (" A constraint or dimension entity of '?' has no id in this payload - nothing "
                 "listed in 'entities' matches it.")
    if truncated:
        note += (f" Entity collections page {entity_limit} each; entity_pages gives each count and "
                 "next_offset. Constraints/dimensions remain capped at 200; their counts above "
                 "are uncapped.")
    out.update({
        "driving_dimension_count": driving_dims,
        "construction_count": construction_count,
        "entities": entities,
        "entity_pages": entity_pages,
        "constraints": constraints,
        "dimensions": dimensions,
        "truncated": truncated,
        "note": note,
    })
    if driving_dims is None:
        out["driving_dimension_count_unread"] = "One or more driving flags did not read; the dimensions list may be capped."
    return ok(out)
