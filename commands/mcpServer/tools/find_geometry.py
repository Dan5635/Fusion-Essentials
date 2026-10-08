# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: scan a part's faces/edges/vertices and return short-lived HANDLES to them."""

import math

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import error, ok, safe, scale
from ._cam_common import clamp_rows
from . import _common
from . import _form_common
from . import _geom
from . import _inputs
from . import _outputs

RETURNS = [
    _outputs.ReturnsHandle("handle", require="any", in_list=True, consumers=[
        "joint_at_geometry", "sketch_create", "model_extrude", "model_fillet", "model_chamfer",
        "model_construction", "model_mirror", "model_combine", "model_inspect", "view_section",
        "pmi_create"]),
]

app = adsk.core.Application.get()

_MAX_RESULTS_DEFAULT = 20    # rows returned when the caller names no cap
_MAX_RESULTS_CEILING = 100   # hard cap on returned match rows (each crosses the wire)

# friendly 'kind' -> what it matches. Faces by surfaceType, edges by curveType, plus vertex.
_FACE_KINDS = {"cylinder_face": "Cylinder", "planar_face": "Plane",
    "cone_face": "Cone", "sphere_face": "Sphere", "torus_face": "Torus", "nurbs_face": "Nurbs"}
_EDGE_KINDS = {"circular_edge": "Circle3D", "line_edge": "Line3D", "arc_edge": "Arc3D",
    "ellipse_edge": "Ellipse3D", "elliptical_arc_edge": "EllipticalArc3D",
    "spline_edge": "NurbsCurve3D"}
# Edge kinds whose reported 'position' is the curve CENTRE rather than the point on the edge. The
# handle locator stays keyed to pointOnEdge either way - that is what _refind_by_locator compares.
_CENTERED_EDGES = ("circular_edge", "arc_edge", "ellipse_edge", "elliptical_arc_edge")
# friendly sketch 'kind' -> the '<type>' collection each sketch is read through.
_SKETCH_KINDS = {"sketch_point": "point", "sketch_line": "line", "sketch_arc": "arc",
                 "sketch_circle": "circle", "sketch_spline": "spline"}
_PLACED_KINDS = tuple(_SKETCH_KINDS) + ("construction_point", "construction_axis",
                                         "construction_plane")

_PLACED_NOTE = ("'position' is WORLD. "
                "Axis handles feed assembly_move(rotate_axis); plane handles feed sketch_create"
                "(plane). Vectors are readbacks; handles retain occurrence. Null "
                "position/handle means unread "
                "geometry. model_construction accepts point handles in 'points'/'to_object', "
                "a sketch_line handle in 'axis' and two_edges' 'edges', or a circle/arc centre "
                "as '<sketch>/<id>:center'.")


def _named_subtree(all_occs, name):
    """Every occurrence whose path, name or component name is `name`, with its whole subtree."""
    matched = [o for o in all_occs
               if (safe(lambda o=o: o.fullPathName) == name or safe(lambda o=o: o.name) == name
                   or safe(lambda o=o: o.component.name) == name)]
    # The whole SUBTREE, not just direct bodies: an inserted xref wraps its own tree and a derive
    # lands its solid one level down, so a wrapper's own bodies can be none.
    prefixes = [p for p in (safe(lambda o=o: o.fullPathName) for o in matched) if p]
    seen = {id(o) for o in matched}
    subtree = list(matched)
    for o2 in all_occs:
        fp = safe(lambda o2=o2: o2.fullPathName) or ""
        if id(o2) not in seen and any(fp.startswith(p + "+") for p in prefixes):
            subtree.append(o2)
            seen.add(id(o2))
    return subtree


def _resolve_target(design, target):
    """Resolve 'target' (occurrence/component/body name, or '' for the whole design) to
    (pairs, label, error, walk). A target matching several occurrences scans ALL of them - this read
    hands back every candidate handle; `error` is set only for a refusal, never a plain miss."""
    root = design.rootComponent
    name = (target or "").strip()
    # root.allOccurrences RAISES on a design holding an unresolved external reference, so the shared
    # census is used - it falls back to component.occurrences and says which walk answered.
    walk = _common.occurrence_walk(design)
    all_occs = walk.occurrences
    root_bodies = safe(lambda: list(root.bRepBodies)) or []
    pairs = []
    if not name:
        # whole design: root-level bodies (occurrence None) + every occurrence's bodies, recursively.
        for b in root_bodies:
            pairs.append((None, b))
        for o in all_occs:
            for b in (safe(lambda o=o: list(o.bRepBodies)) or []):
                pairs.append((o, b))
        return pairs, "whole design", None, walk
    for o in _named_subtree(all_occs, name):
        for b in (safe(lambda o=o: list(o.bRepBodies)) or []):
            pairs.append((o, b))
    if pairs:
        return pairs, f"occurrence/component '{name}'", None, walk
    # By BODY name, through the shared ambiguity-refusing resolver.
    body, body_err = _inputs._resolve_any_body("target", name)
    if body is not None:
        if _inputs._is_mesh(body):
            return [], None, (f"Target '{name}' is a MESH body - find_geometry scans BRep "
                              "faces/edges/vertices, which a mesh has none of. Use mesh_get."), walk
        # Label the body that RESOLVED, in the qualified form that resolves back.
        return [(None, body)], f"body '{_inputs.qualified_body_name(body)}'", None, walk
    # A refusal carries its own fix path; only the plain miss is replaced by this tool's vocabulary.
    if body_err and _inputs.BODY_MISS not in body_err:
        return [], None, body_err, walk
    return [], None, None, walk


def _search_space_note(walk):
    """The sentence disclosing a hole in the occurrence census the scan ran over, or ''."""
    if walk is None:
        return ""
    parts = []
    if not walk.readable:
        parts.append("occurrences_walk='unreadable': NEITHER root.allOccurrences nor the "
                     "component.occurrences fallback enumerated, so the occurrence tree was not "
                     "searched at all and only root-level bodies were scanned - these matches are "
                     "not a complete set, and an empty result here is not an empty design.")
    elif walk.method == _common.WALK_RECURSED:
        parts.append("occurrences_walk='recursed': root.allOccurrences raised, so the occurrence "
                     "census was rebuilt from component.occurrences.")
    if walk.readable and not walk.complete:
        parts.append("The occurrence walk did not run to the end (a collection would not enumerate, "
                     "or a depth/node cap was hit), so part of the design was not scanned.")
    if walk.broken:
        named = _common.named_with_remainder([f"'{n}'" for n in walk.names()])
        parts.append(f"{len(walk.broken)} occurrence(s) hold an unresolved external reference "
                     f"({named}) - reading their component raises, so they carry no geometry to "
                     "scan and were skipped.")
    return (" ".join(parts) + " Check with assembly_get.") if parts else ""


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _radius_value(g, inv_k):
    """An unrounded radius in requested units, or None when it cannot be read."""
    raw = safe(lambda: g.radius)
    if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not math.isfinite(raw):
        return None
    value = raw * inv_k
    return value if math.isfinite(value) else None


def _plane_frame(g, inv_k):
    """A planar face's own orthonormal frame in WORLD coordinates - origin plus x_world/y_world/
    normal - or None when any part of it cannot be read (a partial frame locates nothing)."""
    def build():
        plane = adsk.core.Plane.cast(g)
        if plane is None:
            return None
        x = _geom.unit_vector(plane.uDirection)
        y = _geom.unit_vector(plane.vDirection)
        n = _geom.unit_vector(plane.normal)
        if x is None or y is None or n is None:
            return None
        o = plane.origin
        return {"origin": [round(o.x * inv_k, 6), round(o.y * inv_k, 6), round(o.z * inv_k, 6)],
                "x_world": x, "y_world": y, "normal": n}
    return safe(build)


def _face_record(face, inv_k):
    g = safe(lambda: face.geometry)
    st = safe(lambda: g.surfaceType)
    kind = {adsk.core.SurfaceTypes.CylinderSurfaceType: "cylinder_face",
            adsk.core.SurfaceTypes.PlaneSurfaceType: "planar_face",
            adsk.core.SurfaceTypes.ConeSurfaceType: "cone_face",
            adsk.core.SurfaceTypes.SphereSurfaceType: "sphere_face",
            adsk.core.SurfaceTypes.TorusSurfaceType: "torus_face",
            adsk.core.SurfaceTypes.NurbsSurfaceType: "nurbs_face"}.get(st, "face")
    c = safe(lambda: face.centroid)
    # Composite handle: token + a kind+position locator in cm, so a stale token re-resolves by geometry.
    handle = _inputs.make_handle(face, kind, (c.x, c.y, c.z)) if c else safe(lambda: face.entityToken)
    rec = {"handle": handle, "kind": kind,
            "position": [round(c.x * inv_k, 6), round(c.y * inv_k, 6), round(c.z * inv_k, 6)] if c else None,
            "area": _common.measured(lambda: face.area, inv_k * inv_k, 3)}
    # Outward normal at the reported position (constant for planar, sampled at that point for curved).
    nrm = _geom.evaluator_normal_at(face, c, decimals=4)
    if nrm is not None:
        rec["normal"] = nrm
    if kind == "planar_face":
        rec["frame"] = _plane_frame(g, inv_k)
    radius_value = None
    if kind == "cylinder_face":
        radius_value = _radius_value(g, inv_k)
        rec["radius"] = round(radius_value, 6) if radius_value is not None else None
        ax = safe(lambda: g.axis)
        if ax:
            rec["axis"] = [round(ax.x, 3), round(ax.y, 3), round(ax.z, 3)]
    return rec, radius_value


def _edge_record(edge, inv_k):
    g = safe(lambda: edge.geometry)
    kind = _inputs.edge_kind(g)
    pt = safe(lambda: edge.pointOnEdge)
    # Keyed to pointOnEdge - what _refind_by_locator compares an edge against, not the circle center
    # the display 'position' may carry below.
    handle = _inputs.make_handle(edge, kind, (pt.x, pt.y, pt.z)) if pt else safe(lambda: edge.entityToken)
    rec = {"handle": handle, "kind": kind,
            "position": [round(pt.x * inv_k, 6), round(pt.y * inv_k, 6), round(pt.z * inv_k, 6)] if pt else None,
            "length": _common.measured(lambda: edge.length, inv_k, 3)}
    radius_value = None
    if kind in ("circular_edge", "arc_edge"):
        radius_value = _radius_value(g, inv_k)
        rec["radius"] = round(radius_value, 6) if radius_value is not None else None
    elif kind in ("ellipse_edge", "elliptical_arc_edge"):
        # Two radii, so the single-value 'radius' filter selects no elliptical edge.
        rec["major_radius"] = _common.measured(lambda: g.majorRadius, inv_k, 6)
        rec["minor_radius"] = _common.measured(lambda: g.minorRadius, inv_k, 6)
    if kind in _CENTERED_EDGES:
        ctr = safe(lambda: g.center)
        if ctr:
            rec["position"] = [round(ctr.x * inv_k, 6), round(ctr.y * inv_k, 6), round(ctr.z * inv_k, 6)]
    if kind == "line_edge":
        d = _geom.unit_vector_between(safe(lambda: g.startPoint), safe(lambda: g.endPoint), decimals=4)
        if d is not None:
            rec["direction"] = d
    return rec, radius_value


def _placed_scopes(design, target):
    """((occurrence or None, component) pairs a placed kind scans, label, error, walk)."""
    root = design.rootComponent
    walk = _common.occurrence_walk(design)
    name = (target or "").strip()
    if not name:
        return ([(None, root)] + [(o, safe(lambda o=o: o.component)) for o in walk.occurrences],
                "whole design", None, walk)
    pairs = [(o, safe(lambda o=o: o.component)) for o in _named_subtree(walk.occurrences, name)]
    if safe(lambda: root.name) == name:
        pairs.insert(0, (None, root))
    if pairs:
        return pairs, f"occurrence/component '{name}'", None, walk
    return [], None, (f"target '{name}' names no occurrence or component - placed kinds read "
                      "components (assembly_get lists them)."), walk


def _radius_kept(rec, value, requested, tolerance, inv_k):
    """Stamp 'radius' (units) on `rec` and say whether the radius filter keeps it."""
    radius = value * inv_k if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if radius is not None:
        rec["radius"] = round(radius, 6)
    return requested is None or (radius is not None and abs(radius - requested) <= tolerance)


def _sketch_rows(occ, comp, knd, sketch_name, requested, tolerance, inv_k):
    """[(record, entity)] for every sketch entity of `knd` in `comp`, located through `occ`."""
    ref_kind = _SKETCH_KINDS[knd]
    path = safe(lambda: occ.fullPathName) if occ is not None else None
    rows = []
    for sk in _common.iter_collection(safe(lambda: comp.sketches)):
        sk_name = safe(lambda sk=sk: sk.name)
        if sketch_name and sk_name != sketch_name:
            continue
        coll = _common.entity_collection(sk, ref_kind)
        for i in range(safe(lambda coll=coll: coll.count, 0) or 0):
            ent = safe(lambda coll=coll, i=i: coll.item(i))
            pos = _inputs.placed_point_cm(ent, occ) if ent is not None else None
            if pos is None:
                continue
            rec = {"handle": None, "kind": knd, "position": [round(c * inv_k, 6) for c in pos],
                   "sketch": sk_name, "id": f"{ref_kind}:{i}", "occurrence": path}
            if ref_kind in ("arc", "circle"):
                if not _radius_kept(rec, safe(lambda ent=ent: ent.radius), requested, tolerance,
                                    inv_k):
                    continue
                centre = _inputs.placed_point_cm(safe(lambda ent=ent: ent.centerSketchPoint), occ)
                rec["center"] = [round(c * inv_k, 6) for c in centre] if centre else None
            elif requested is not None:
                continue
            if ref_kind == "line":
                ends = _inputs.placed_ends(ent, occ)
                rec["start"], rec["end"] = ([[round(c * inv_k, 6) for c in e] for e in ends]
                                            if ends else (None, None))
            rows.append((rec, ent))
    return rows


def _datum_rows(occ, comp, kind, want_name, requested, inv_k):
    """(rows, incomplete) for one construction-datum kind in a placed component."""
    if requested is not None:
        return [], False
    path = safe(lambda: occ.fullPathName) if occ is not None else None
    attr = {"construction_point": "constructionPoints", "construction_axis": "constructionAxes",
            "construction_plane": "constructionPlanes"}[kind]
    coll = safe(lambda: getattr(comp, attr))
    count = _common.counted(lambda: coll.count) if coll is not None else None
    if count is None:
        return [], True
    rows = []
    incomplete = False
    for i in range(count):
        datum = safe(lambda i=i: coll.item(i))
        if datum is None:
            incomplete = True
            continue
        nm = safe(lambda datum=datum: datum.name)
        if nm is None and want_name:
            incomplete = True
            continue
        if want_name and not (isinstance(nm, str) and nm.strip().lower() == want_name.lower()):
            continue
        if kind == "construction_point":
            pos, vector = _inputs.placed_point_cm(datum, occ), None
        else:
            pos, vector = _inputs.placed_datum_frame(datum, kind, occ)
        proxy = safe(lambda datum=datum: datum.createForAssemblyContext(occ)) if occ else datum
        rec = {"handle": None, "kind": kind, "name": nm,
               "position": [round(c * inv_k, 6) for c in pos] if pos else None,
               "occurrence": path,
               "is_visible": _common.read_flag(lambda: proxy.isVisible) if proxy else None}
        if vector is not None:
            rec["direction" if kind == "construction_axis" else "normal"] = vector
        if pos is None:
            rec["read_error"] = "World geometry unavailable; no handle can be minted."
        rows.append((rec, datum))
    return rows, incomplete


def _placed_search(design, target, knd, sketch, name, radius, inv_k):
    """([(record, entity, occurrence)], label, error, walk) for a sketch or construction-point kind."""
    sketch_name, want_name = (sketch or "").strip(), (name or "").strip()
    if sketch_name and knd not in _SKETCH_KINDS:
        return [], None, f"'sketch' narrows the sketch_* kinds; kind='{knd}' reads no sketch.", None, False
    if want_name and knd in _SKETCH_KINDS:
        return [], None, f"'name' narrows construction datums; kind='{knd}' carries none.", None, False
    scopes, label, err, walk = _placed_scopes(design, target)
    if err:
        return [], None, err, walk, False
    requested = float(radius) if radius is not None else None
    tolerance = max(0.05 * requested, 1e-6) if requested is not None else None
    found, incomplete = [], False
    for occ, comp in scopes:
        if comp is None:
            incomplete = True
            continue
        if knd in _SKETCH_KINDS:
            rows = _sketch_rows(occ, comp, knd, sketch_name, requested, tolerance, inv_k)
        else:
            rows, partial = _datum_rows(occ, comp, knd, want_name, requested, inv_k)
            incomplete = incomplete or partial
        found.extend((rec, ent, occ) for rec, ent in rows)
    incomplete = incomplete or not walk.complete or bool(walk.broken)
    return found, label, None, walk, incomplete


def _placed_payload(design, target, knd, sketch, name, radius, nearest_to, units, inv_k,
                    max_results):
    """The result for a placed kind, each returned row's handle minted where it was read."""
    found, label, err, walk, incomplete = _placed_search(design, target, knd, sketch, name, radius, inv_k)
    space_note = _search_space_note(walk)
    if err:
        return error(f"{err} {space_note}".strip() if space_note else err)
    if isinstance(nearest_to, (list, tuple)) and len(nearest_to) == 3:
        npt = [float(nearest_to[i]) for i in range(3)]
        found.sort(key=lambda row: (_dist(row[0]["position"], npt)
                                    if row[0]["position"] is not None else float("inf")))
    kept = found[:clamp_rows(max_results, _MAX_RESULTS_DEFAULT, _MAX_RESULTS_CEILING)]
    for rec, ent, occ in kept:
        if rec["position"] is not None:
            rec["handle"] = _inputs.placed_handle(ent, knd, occ)
            if rec["handle"] is None:
                rec["read_error"] = "Placed handle unavailable; datum cannot be consumed."
    payload = {"target": label, "kind_filter": knd,
               "match_count": None if incomplete else len(found),
               "returned": len(kept), "units": units,
               "occurrences_walk": walk.method if walk is not None else None,
               "matches": [rec for rec, _ent, _occ in kept], "note": _PLACED_NOTE}
    if incomplete:
        payload["incomplete"] = True
        payload["note"] += " A collection or occurrence did not read; match_count is unknown."
    if space_note:
        payload["note"] += "\n" + space_note
    return ok(payload)


_FORM_KINDS = tuple(_form_common.CAGE_KINDS)
_FORM = _inputs.FeatureRef("name")


def _form_payload(design, knd, name, nearest_to, units, inv_k, max_results):
    """The cage vertices, edges or faces of one Form, each row's handle stamped with the cage
    revision it was read at."""
    forms = [ff for _comp, ff in _form_common.all_forms(design)]
    if (name or "").strip():
        ff, ferr = _form_common.resolve_form(design, _FORM, name)
        if ferr:
            return error(ferr)
    elif len(forms) == 1:
        ff = forms[0]
    else:
        return error(f"kind='{knd}' reads one Form and the design holds {len(forms)} - name it "
                     "with 'name' as form_get lists it.")
    body, berr = _form_common.one_cage_body(ff)
    if berr:
        return error(berr)
    walk = _form_common.cage_walk(body)
    if walk is None:
        return error(f"The cage of '{_form_common.form_label(ff)}' did not read.")
    revision = _form_common.cage_revision(walk)
    rows = []
    for index in range(len(walk[_form_common.CAGE_KINDS[knd]])):
        point = _form_common.cage_point(walk, knd, index)
        rec = {"kind": knd, "index": index, "position": [round(c * inv_k, 6) for c in point]}
        if knd == "form_edge":
            rec["creased"] = walk["edges"][index][2]
        if knd == "form_face":
            rec["vertex_count"] = len(walk["faces"][index])
        rows.append(rec)
    if isinstance(nearest_to, (list, tuple)) and len(nearest_to) == 3:
        npt = [float(nearest_to[i]) for i in range(3)]
        rows.sort(key=lambda rec: _dist(rec["position"], npt))
    kept = rows[:clamp_rows(max_results, _MAX_RESULTS_DEFAULT, _MAX_RESULTS_CEILING)]
    for rec in kept:
        rec["handle"] = _form_common.cage_handle(ff, body, knd, rec["index"], revision)
    return ok({"target": _form_common.form_label(ff), "kind_filter": knd,
               "match_count": len(rows), "returned": len(kept), "units": units,
               "occurrences_walk": None, "matches": kept, "revision": revision,
               "note": "'position' is WORLD: a vertex, an edge's middle, a face's centroid. Cage "
                       "handles feed form_edit and hold until the cage changes."})


def handler(target: str = "", kind: str = "", radius: float = None,
            nearest_to=None, units: str = "mm", max_results: int = 20, sketch: str = "",
            name: str = "") -> dict:
    """See TOOL_DESCRIPTION."""
    k = scale(units)
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    inv_k = 1.0 / k

    design = _common.design()
    if not design:
        return error("No active design (open or create a document first).")

    knd = (kind or "").strip().lower()
    if knd in _FORM_KINDS:
        stray = [n for n, v in (("target", target), ("sketch", sketch), ("radius", radius))
                 if v not in (None, "")]
        if stray:
            return error(f"kind='{knd}' reads a Form's cage: 'name' names the Form; drop "
                         f"{', '.join(stray)}.")
        return _form_payload(design, knd, name, nearest_to, units, inv_k, max_results)
    if knd in _PLACED_KINDS:
        return _placed_payload(design, target, knd, sketch, name, radius, nearest_to, units, inv_k,
                               max_results)
    if (sketch or "").strip() or (name or "").strip():
        return error(f"'sketch' and 'name' narrow sketch_* and construction-datum kinds; "
                     f"kind='{knd or 'faces+edges'}' reads bodies.")

    pairs, target_label, resolve_err, walk = _resolve_target(design, target)
    space_note = _search_space_note(walk)
    if not pairs:
        miss = (resolve_err or
                f"Could not resolve target '{target}'. Use an occurrence/component name, a body "
                "name (bare, or '<occurrence-or-component>:<body>' when several components hold "
                "that name), or '' for the whole design (see assembly_get / "
                "design_get(include=['tree'])).")
        return error(f"{miss} {space_note}".strip() if space_note else miss)

    want_faces = (not knd) or knd in _FACE_KINDS
    want_edges = (not knd) or knd in _EDGE_KINDS
    want_verts = knd == "vertex" and radius is None
    requested_radius = float(radius) if radius is not None else None
    radius_tolerance = (max(0.05 * requested_radius, 1e-6)
                        if requested_radius is not None else None)

    matches = []
    for occ, body in pairs:
        # BRepBody.isVisible is the EFFECTIVE state, rolling up every ancestor occurrence's bulb;
        # isLightBulbOn alone does not.
        hidden = safe(lambda body=body: body.isVisible, True) is False
        # The occurrence this body's geometry was read through; null for a root-owned body.
        ctx = safe(lambda body=body: body.assemblyContext) or occ
        occ_path = safe(lambda ctx=ctx: ctx.fullPathName) if ctx is not None else None
        recs = []
        if want_faces:
            for f in (safe(lambda body=body: list(body.faces)) or []):
                rec, measured_radius = _face_record(f, inv_k)
                if knd in _FACE_KINDS and rec["kind"] != knd:
                    continue
                if (requested_radius is not None
                        and not (measured_radius is not None
                                 and abs(measured_radius - requested_radius) <= radius_tolerance)):
                    continue
                recs.append(rec)
        if want_edges:
            for e in (safe(lambda body=body: list(body.edges)) or []):
                rec, measured_radius = _edge_record(e, inv_k)
                if knd in _EDGE_KINDS and rec["kind"] != knd:
                    continue
                if (requested_radius is not None
                        and not (measured_radius is not None
                                 and abs(measured_radius - requested_radius) <= radius_tolerance)):
                    continue
                recs.append(rec)
        if want_verts:
            for v in (safe(lambda body=body: list(body.vertices)) or []):
                p = safe(lambda v=v: v.geometry)
                vh = _inputs.make_handle(v, "vertex", (p.x, p.y, p.z)) if p else safe(lambda v=v: v.entityToken)
                recs.append({"handle": vh, "kind": "vertex",
        "position": [round(p.x * inv_k, 6), round(p.y * inv_k, 6),
                                             round(p.z * inv_k, 6)] if p else None})
        for rec in recs:
            rec["occurrence"] = occ_path
            if hidden:
                rec["hidden"] = True
        matches.extend(recs)

    # sort by distance to nearest_to, else leave in discovery order
    if isinstance(nearest_to, (list, tuple)) and len(nearest_to) == 3:
        npt = [float(nearest_to[i]) for i in range(3)]
        matches = [m for m in matches if m.get("position")]
        matches.sort(key=lambda m: _dist(m["position"], npt))

    total = len(matches)
    matches = matches[:clamp_rows(max_results, _MAX_RESULTS_DEFAULT, _MAX_RESULTS_CEILING)]

    payload = {
        "target": target_label,
        "kind_filter": knd or "faces+edges",
        "match_count": total,
        "returned": len(matches),
        "units": units,
        # Always published, so a reader can tell an absent key from a whole search space.
        "occurrences_walk": walk.method if walk is not None else None,
        "matches": matches,
        "note": "A match on a body that is not visible carries hidden:true.\n"
        "A planar face's 'frame' is that plane in world space: the point at local (u, v) is "
        "frame.origin + u*frame.x_world + v*frame.y_world, and frame.origin is the plane's "
        "PARAMETRIC origin while 'position' is the centroid. Feed consumers world coordinates "
        "(model_hole points_space='world'), not a sketch frame converted by hand.",
    }
    if space_note:
        payload["note"] += "\n" + space_note
    return ok(payload)


TOOL_DESCRIPTION = (
    "Find world geometry and handles.\n"
    + _outputs.produces_block(RETURNS)
)

find_tool = (
    Tool.create_simple(name="find_geometry", description=TOOL_DESCRIPTION)
    .add_input_property("target", {"type": "string", "description":
            "Occurrence, component or body; '' = the design."})
    .add_input_property(*_inputs.Choice("kind",
        ["cylinder_face", "planar_face", "cone_face", "sphere_face", "torus_face", "nurbs_face",
         "circular_edge", "line_edge", "arc_edge", "ellipse_edge", "elliptical_arc_edge",
         "spline_edge", "vertex", *_PLACED_KINDS, *_FORM_KINDS]).as_property())
    .add_input_property("sketch", {"type": "string"})
    .add_input_property("name", {"type": "string"})
    .add_input_property("radius", {"type": "number",
            "description": "In 'units', 5% tolerance."})
    .add_input_property("nearest_to", {"type": "array", "items": {"type": "number"},
            "description": "Sort by world [x,y,z] in 'units'."})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_input_property("max_results", {"type": "integer", "description":
            f"Max {_MAX_RESULTS_CEILING}."})
    .strict_schema()
)
find_item = Item.create_tool_item(tool=find_tool, write="read", handler=handler, run_on_main_thread=True)


def register_tool():
    register(find_item)
