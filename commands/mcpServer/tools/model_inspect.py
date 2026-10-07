# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP RICH READ: model_inspect - measure a target (size, mass, mesh stats) in one read, by detail
level: a light default (bounding box) plus include=['mass'] for full physical properties. 'target'
is a TargetRef (a find_geometry handle, a name, or '' for the whole design); a MESH target reports
mesh stats instead. Read-only.
"""

import json

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import ok, error, safe
from . import _common
from . import _geom
from . import _inputs
from . import _joints
from . import sys_get_preferences as _prefs

app = adsk.core.Application.get()

_SLICES = ("mass", "material", "appearance")   # mesh stats are automatic for a mesh target
# The default measurement's name in include=: include= omits the bounding box unless 'default' rides
# beside it, so a mass read carries the properties asked for and not the box again.
_DEFAULT_NAMES = ("default",)
# target accepts a handle (body/face/mesh) or a name (occurrence/component/body), or '' = whole design.
_TARGET = _inputs.TargetRef("target")
# frame: the Joint Origin the oriented box is measured in. NATIVE selector - this READS the frame's
# axis vectors rather than handing the JO to a joint, so it stays on the object the owning component
# carries instead of an assembly proxy. required=True is about the resolve, not the schema.
_FRAME = _inputs.JointOriginRef("frame", native=True, required=True)

_ACCURACY = {
    "low": adsk.fusion.CalculationAccuracy.LowCalculationAccuracy,
    "medium": adsk.fusion.CalculationAccuracy.MediumCalculationAccuracy,
    "high": adsk.fusion.CalculationAccuracy.HighCalculationAccuracy,
    "very_high": adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy,
}
_ACCURACY_NAME = {v: k for k, v in _ACCURACY.items()}   # for reporting the accuracy the API used

_MAX_PER_OCCURRENCE_ROWS = 200   # per_body rows: one per occurrence, each crossing the wire
_MAX_PER_BODY_ROWS = 200         # and one per solid body, which a component can hold several of


# ── small geometry helpers ───────────────────────────────────────────────────


def _vec(v, f=1.0):
    """[x, y, z] for a Vector3D/Point3D scaled by `f`, or None when any component will not read - a
    0.0 stand-in would publish a direction nobody measured, and 0 is a real answer here."""
    p = _common.ptxyz(v, f)
    return None if p is None else [p["x"], p["y"], p["z"]]


def _measurable_geometry(entity):
    """(geometry, note) - a B-Rep entity for getOrientedBoundingBox, which rejects a Component and
    an Occurrence (an Occurrence raises "3 : invalid argument geometry"). Both fall back to the
    bodies they hold: the single one, or the largest by world-AABB volume. An occurrence's bodies
    are its assembly PROXIES, so the fallback still measures the instance the caller named."""
    tname = safe(lambda: type(entity).__name__) or ""
    if tname == "BRepBody":
        return entity, ""
    bodies = safe(lambda: entity.bRepBodies)
    if bodies is None:
        return entity, ""           # not a Component and not a recognised body type - assume B-Rep already
    n = safe(lambda: bodies.count, 0)
    if not n:
        return None, ""
    if n == 1:
        return bodies.item(0), f" (body '{safe(lambda: bodies.item(0).name)}')"
    # Several bodies: measure the largest by world-AABB volume (best single-body proxy).
    best, best_vol, best_name = None, -1.0, None
    for b in _common.iter_collection(bodies):
        bb = safe(lambda b=b: b.boundingBox)
        if not bb:
            continue
        mn, mx = safe(lambda bb=bb: bb.minPoint), safe(lambda bb=bb: bb.maxPoint)
        if mn is None or mx is None:
            continue
        vol = abs((mx.x - mn.x) * (mx.y - mn.y) * (mx.z - mn.z))
        if vol > best_vol:
            best, best_vol, best_name = b, vol, safe(lambda b=b: b.name)
    if best is None:
        best = bodies.item(0); best_name = safe(lambda: bodies.item(0).name)
    return best, (f" (largest of {n} bodies: '{best_name}'; measure a specific body for one part)")


def _subtree_occurrences(entity, limit):
    """Every occurrence in `entity`'s subtree - nested levels included - capped at `limit` + 1. A
    Component answers ``allOccurrences``, already flattened, while its ``occurrences`` holds only
    DIRECT children; an Occurrence carries no flattened list, so its subtree is walked here. The one
    extra item past `limit` lets the caller say the list was cut without publishing a total."""
    out = []
    flat = safe(lambda: entity.allOccurrences)
    if flat is not None:
        for o in _common.iter_collection(flat):
            out.append(o)
            if len(out) > limit:
                break
        return out
    kids = safe(lambda: entity.childOccurrences)
    if kids is None:
        # ``allOccurrences`` did not answer AND there is no ``childOccurrences``: a COMPONENT whose
        # subtree holds an unresolved external reference makes that property RAISE. The shared census
        # rebuilds the subtree from component.occurrences instead.
        for o in _common.component_walk(entity).occurrences:
            out.append(o)
            if len(out) > limit:
                break
        return out
    frontier = list(_common.iter_collection(kids))
    while frontier and len(out) <= limit:
        o = frontier.pop(0)
        out.append(o)
        frontier.extend(_common.iter_collection(safe(lambda o=o: o.childOccurrences)))
    return out


def _body_rows(entity, occs, acc, inv, limit):
    """(rows, truncated, true_total) - one row per BREP BODY the target holds, true_total counting
    every holder's bRepBodies regardless of the cap. A component holding three bodies is three rows
    here and ONE row in the per-occurrence breakdown, which sums them. The walk is bRepBodies, so an
    open SURFACE body gets a row carrying is_solid false and a mesh body none."""
    holders = [(None, entity)] + [(safe(lambda o=o: o.fullPathName) or safe(lambda o=o: o.name), o)
                                  for o in occs]
    total = sum(_common.counted(lambda h=holder: h.bRepBodies.count) or 0 for _p, holder in holders)
    rows = []
    for path, holder in holders:
        for b in _common.iter_collection(safe(lambda h=holder: h.bRepBodies)):
            if len(rows) >= limit:
                return rows, True, total
            # A body whose properties will not compute still gets its row: the name and lump count
            # are the census, and a missing mass is published null rather than dropping the body.
            bpp = safe(lambda b=b: b.getPhysicalProperties(acc))
            rows.append({
                "body": safe(lambda b=b: b.name),
                "occurrence": path,
                # A surface body has area but no volume or mass, so the flag is what tells an empty
                # mass row from a solid whose properties would not compute; null = the flag itself
                # did not read.
                "is_solid": _common.read_flag(lambda b=b: b.isSolid),
                "mass_kg": _common.measured(lambda: bpp.mass) if bpp is not None else None,
                "volume": (_common.measured(lambda: bpp.volume, inv ** 3)
                           if bpp is not None else None),
                "lump_count": _geom.lump_count(b),
            })
    return rows, False, total


def _body_cut_note(shown, true_total, cap):
    """The FIRST sentence when per_body was cut: shown vs true count, and the scoped remedy."""
    return (f"per_body: {shown} of {true_total} bodies shown (cap {cap}, per_body_truncated). "
            "Target a narrower occurrence/component - design_get(include=['tree']) lists them.")


def _joint_origin_axes(frame_name):
    """(X_vec, Y_vec, Z_vec, jo, jo_name, error) for the Joint Origin 'frame' names. X=secondary,
    Y=third, Z=primary, in the JO's own PART space. The resolved JO travels out too, because the
    axes still need lifting into the space the target's geometry reads in. Every failure travels in
    the error slot, so a JO whose axes did not read is never reported as one that does not exist."""
    jo, err = _FRAME.resolve(frame_name)
    if err:
        return None, None, None, None, None, err
    x_vec, y_vec = safe(lambda: jo.secondaryAxisVector), safe(lambda: jo.thirdAxisVector)
    jo_name = safe(lambda: jo.name) or (frame_name or "").strip()
    if x_vec is None or y_vec is None:
        # getOrientedBoundingBox takes the X/Y pair below, so an unreadable one leaves no frame to
        # measure in. Naming WHICH read came back empty keeps this off the not-found error.
        return None, None, None, None, None, (
            f"Joint Origin '{jo_name}' resolved, but its "
            f"{'X (secondary)' if x_vec is None else 'Y (third)'} axis vector did not read, so there "
            "is no frame to measure in. Omit 'frame' for a world-aligned box.")
    return x_vec, y_vec, safe(lambda: jo.primaryAxisVector), jo, jo_name, None


def _measuring_axes(jo, geom, x_vec, y_vec, jo_name, desc):
    """(X, Y, error) - the frame's X/Y axes re-expressed in the coordinate space
    ``getOrientedBoundingBox`` reads `geom` in. That call reads its AXIS ARGUMENTS in the SAME space
    as the geometry it is handed, and a JointOrigin reports its axis vectors in its owning
    COMPONENT's space. Only directions are transformed - a matrix's translation never enters."""
    occ = safe(lambda: geom.assemblyContext)
    # Two reads, because neither spans the target kinds this tool accepts: every BRepBody answers
    # parentComponent while the shared entity_component chain returns None for it, and a BRepFace is
    # the mirror image - no parentComponent at all, its owner reached through body.parentComponent.
    geom_comp = safe(lambda: geom.parentComponent) or _inputs.entity_component(geom)
    jo_comp = safe(lambda: jo.parentComponent)
    # `is True`: "nothing to lift" is a claim that both sides sit in ONE frame, so an unproven pair
    # falls through to the lift below, which either derives a real matrix or refuses by naming the
    # input it could not place.
    if occ is None and _common.same_component(geom_comp, jo_comp) is True:
        return x_vec, y_vec, None       # one component's frame on both sides - nothing to lift
    if occ is None and geom_comp is None:
        # Nothing this tool can read said which space the target is measured in, so there is no lift
        # to derive and no ambiguity to report either - the axes go on as read. A geometry
        # getOrientedBoundingBox cannot measure is refused by the call itself.
        return x_vec, y_vec, None
    design = _common.design()
    # Two DIFFERENT inputs can be the one with no single placement, and each has its own remedy, so
    # each names the input the code actually read as unplaceable. Blaming the frame for the target's
    # ambiguity sends the caller to re-word the one argument that was fine.
    frame_unplaced = (f"Joint Origin '{jo_name}' could not be placed in the same space as the "
                      "target, so the frame its extents would be measured in is unknown. Target a "
                      "body inside the occurrence you mean (find_geometry returns one handle per "
                      "instance), or omit 'frame' for a world-aligned box.")
    untransformed = (f"Joint Origin '{jo_name}' resolved, but its axis vectors did not transform "
                     "into the target's space, so there is no frame to measure in. Omit 'frame' "
                     "for a world-aligned box.")
    # `occ` scopes the JO's placement to the INSTANCE the target was reached through, so a component
    # placed several times still resolves for the instance in hand.
    to_world = _joints.component_world_matrix(design, jo_comp, occ)
    if to_world is None:
        return None, None, frame_unplaced
    # A PROXY's geometry is read in world, so world axes are the answer. A NATIVE body is read in
    # its OWN component's frame, so the world axes come back into that one - the only pairing left,
    # since a native body of the JO's own component returned above.
    inverse = None
    if occ is None:
        from_world = _joints.component_world_matrix(design, geom_comp)
        if from_world is None:
            # The FRAME placed (to_world read above); it is the target's own component that no
            # single placement answers for.
            return None, None, (
                f"No single placement answers for the component {desc} belongs to, so the space its "
                f"extents are measured in is unknown - Joint Origin '{jo_name}' placed fine. Target "
                "a body inside the occurrence you mean (find_geometry returns one handle per "
                "instance), or omit 'frame' for a world-aligned box.")
        inverse = safe(lambda: from_world.copy())
        if inverse is None or not safe(lambda: inverse.invert()):
            return None, None, (
                f"The placement of the component {desc} belongs to did not invert, so the frame's "
                "axes could not be brought into the space its extents are measured in. Omit "
                "'frame' for a world-aligned box.")
    out = []
    for v in (x_vec, y_vec):
        moved = safe(lambda v=v: v.copy())
        if moved is None or not safe(lambda m=moved: m.transformBy(to_world)):
            return None, None, untransformed
        if inverse is not None and not safe(lambda m=moved: m.transformBy(inverse)):
            return None, None, untransformed
        out.append(moved)
    return out[0], out[1], None


# ── measure cores (take a RESOLVED entity; no resolution here) ────────────────

def _bbox(design, entity, desc, frame, units):
    """The bounding box of a resolved entity - world-aligned, or oriented in a Joint Origin frame."""
    f = _common.CM_TO_UNIT.get((units or "mm").strip().lower())
    if f is None:
        return error(f"Unknown units '{units}'. Valid: mm, cm, in.")

    want_frame = (frame or "").strip()
    if want_frame:
        x_vec, y_vec, z_vec, jo, jo_name, frame_err = _joint_origin_axes(want_frame)
        if frame_err:
            return error(frame_err)
        mgr = safe(lambda: app.measureManager)
        if not mgr:
            return error("MeasureManager unavailable.")
        geom, geom_note = _measurable_geometry(entity)   # getOrientedBoundingBox needs B-Rep, not a Component
        if geom is None:
            return error(f"{desc} has no B-Rep body to measure in a frame. Target a specific "
                         "body/occurrence (design_get(include=['tree']) lists them).")
        # The measurement runs on the axes lifted into the target geometry's own space; frame_axes
        # below publishes the UNLIFTED pair, which is the part-space frame the payload describes.
        m_x, m_y, lift_err = _measuring_axes(jo, geom, x_vec, y_vec, jo_name, desc)
        if lift_err:
            return error(lift_err)
        try:
            obb = mgr.getOrientedBoundingBox(geom, m_x, m_y)
        except Exception as e:
            return error(f"Oriented bounding-box measurement failed: {e}. (The X/Y axes of the "
                         "frame must be perpendicular, and the target must be B-Rep geometry.)")
        if not obb:
            return error("getOrientedBoundingBox returned nothing for this target.")
        return ok({
            "target": (desc + geom_note),
            "frame": f"joint origin '{jo_name}' (part space; the frame its owning component carries)",
            "oriented": True,
            "units": units,
            "x": _common.measured(lambda: obb.length, f),    # length=X, width=Y, height=Z (right-hand)
            "y": _common.measured(lambda: obb.width, f),
            "z": _common.measured(lambda: obb.height, f),
            "center": _common.ptxyz(safe(lambda: obb.centerPoint), f),
            "frame_axes": {"x_axis": _vec(x_vec), "y_axis": _vec(y_vec), "z_axis": _vec(z_vec)},
            "note": "Measured in the joint-origin frame; x/y/z are the part-space extents. Feed "
                    "these to param_set to drive stock size. The frame is the Joint Origin its "
                    "owning COMPONENT carries - the same one for every instance of that component, "
                    "so naming an instance ('<occurrence>:<JO name>') does not select a different "
                    "one.",
        })

    bb, box_read = _geom.body_aabb_read(entity)
    if not bb:
        return error(f"No bounding box available for {desc} (it may have no solid geometry).")
    mn = safe(lambda: bb.minPoint)
    mx = safe(lambda: bb.maxPoint)
    if mn is None or mx is None:
        return error(f"Bounding box for {desc} has no min/max points.")
    # Every number below is a MEASUREMENT, so an unreadable corner reads null - the same contract the
    # oriented branch above holds under the SAME keys. safe(..., 0.0) here would publish a 0 mm
    # extent, and 0 is an answer: "this body is flat in Z", "the centre is on the origin".
    def _span(axis):
        lo = _common.measured(lambda: getattr(mn, axis), f)
        hi = _common.measured(lambda: getattr(mx, axis), f)
        return (None, None) if lo is None or hi is None else (round(hi - lo, 6),
                                                              round((hi + lo) / 2, 6))
    (dx, cx), (dy, cy), (dz, cz) = (_span("x"), _span("y"), _span("z"))
    return ok({
        "target": desc,
        "frame": "world axes (axis-aligned)",
        "box_read": box_read,
        "oriented": False,
        "units": units,
        "x": dx, "y": dy, "z": dz,
        "min_point": _common.ptxyz(mn, f),
        "max_point": _common.ptxyz(mx, f),
        "center": {"x": cx, "y": cy, "z": cz},
    })


def _full_props(pp, k):
    """The full physical-properties payload from a PhysicalProperties object. k = length-unit factor
    (cm -> unit). Mass is kg; volume/area scale by 1/k^3, 1/k^2 from cm; inertia by (cm->unit)^2."""
    inv = 1.0 / k
    i_f = inv * inv
    out = {
        "mass_kg": _common.measured(lambda: pp.mass),
        "volume": _common.measured(lambda: pp.volume, inv ** 3),
        "area": _common.measured(lambda: pp.area, inv ** 2),
        "density_kg_per_cm3": _common.measured(lambda: pp.density, places=9),
        "center_of_mass": _vec(safe(lambda: pp.centerOfMass), inv),
    }
    xyz = safe(lambda: pp.getXYZMomentsOfInertia())     # world-origin inertia tensor, kg*unit^2
    if xyz and len(xyz) >= 7 and xyz[0]:
        out["inertia_world"] = {
            "about": "world coordinate origin",
            "units": "kg*unit^2",
            "Ixx": _common.measured(lambda: xyz[1] * i_f), "Iyy": _common.measured(lambda: xyz[2] * i_f), "Izz": _common.measured(lambda: xyz[3] * i_f),
            "Ixy": _common.measured(lambda: xyz[4] * i_f), "Iyz": _common.measured(lambda: xyz[5] * i_f), "Ixz": _common.measured(lambda: xyz[6] * i_f),
        }
    pm = safe(lambda: pp.getPrincipalMomentsOfInertia())    # about the CoM / principal frame
    if pm and len(pm) >= 4 and pm[0]:
        out["principal_moments"] = {
            "about": "center of mass (principal axes)",
            "units": "kg*unit^2",
            "i1": _common.measured(lambda: pm[1] * i_f), "i2": _common.measured(lambda: pm[2] * i_f), "i3": _common.measured(lambda: pm[3] * i_f),
        }
    pax = safe(lambda: pp.getPrincipalAxes())
    if pax and len(pax) >= 4 and pax[0]:
        out["principal_axes"] = {"x": _vec(pax[1]), "y": _vec(pax[2]), "z": _vec(pax[3])}
    gyr = safe(lambda: pp.getRadiusOfGyration())
    if gyr and len(gyr) >= 4 and gyr[0]:
        out["radius_of_gyration"] = {"kx": _common.measured(lambda: gyr[1] * inv), "ky": _common.measured(lambda: gyr[2] * inv),
                                     "kz": _common.measured(lambda: gyr[3] * inv)}
    rot = safe(lambda: pp.getRotationToPrincipal())
    if rot and len(rot) >= 4 and rot[0]:
        out["rotation_to_principal_rad"] = {"rx": _common.measured(lambda: rot[1]), "ry": _common.measured(lambda: rot[2]),
                                            "rz": _common.measured(lambda: rot[3])}
    return out


def _physical_properties(design, entity, desc, units, accuracy, per_body):
    """The full physical properties of a resolved entity."""
    k = _common.scale(units)   # length unit -> cm (the API reports cm). Volume scales k^3, area k^2.
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    acc_key = (accuracy or "medium").strip().lower()
    acc = _ACCURACY.get(acc_key)
    if acc is None:
        return error(f"Unknown accuracy '{accuracy}'. Use: low, medium, high, very_high.")

    pp = safe(lambda: entity.getPhysicalProperties(acc))
    if pp is None:
        return error(f"Could not compute physical properties for {desc} (no measurable solid? an empty "
                     "or surface-only target has no mass).")

    result = {"target": desc, "units": units, "accuracy": acc_key, "freshness_verified": False}
    result.update(_full_props(pp, k))
    result["accuracy_used"] = _ACCURACY_NAME.get(safe(lambda: pp.accuracy))

    truncated = False
    if per_body:
        # A mass + CoM row per occurrence in the target's SUBTREE, at every depth - a body owned by a
        # nested sub-component is otherwise folded into its parent's row and never named.
        occs = _subtree_occurrences(entity, _MAX_PER_OCCURRENCE_ROWS)
        truncated = len(occs) > _MAX_PER_OCCURRENCE_ROWS
        breakdown = []
        for o in occs[:_MAX_PER_OCCURRENCE_ROWS]:
            opp = safe(lambda o=o: o.getPhysicalProperties(acc))
            if opp is None:
                continue
            row = {
                # the FULL path: two occurrences of one component, or two 'Bolt:1' under different
                # parents, are separate rows and a bare name would collapse them.
                "occurrence": safe(lambda o=o: o.fullPathName) or safe(lambda o=o: o.name),
                "mass_kg": _common.measured(lambda: opp.mass),
                "center_of_mass": _vec(safe(lambda: opp.centerOfMass), 1.0 / k),
            }
            # An occurrence's physical properties cover its whole subtree, so a row with children
            # already contains the rows nested under it. An unreadable child count publishes null
            # rather than a confident "this one is a leaf".
            kids = _common.counted(lambda o=o: o.childOccurrences.count)
            if kids is None:
                row["aggregates_children"] = None
            elif kids > 0:
                row["aggregates_children"] = True
            breakdown.append(row)
        result["per_occurrence"] = breakdown
        result["per_occurrence_count"] = len(breakdown)
        result["per_occurrence_truncated"] = truncated
        # The per-BODY census beside it: an occurrence row covers its whole component, so a part
        # built as several bodies is invisible in the occurrence rows - and a leaf occurrence, which
        # has no subtree at all, produces none of them.
        body_rows, body_cut, body_total = _body_rows(entity, occs, acc, 1.0 / k, _MAX_PER_BODY_ROWS)
        result["per_body"] = body_rows
        result["per_body_count"] = len(body_rows)
        result["per_body_truncated"] = body_cut

    note = ("Physical-property freshness is unverified. Linked feature edits may leave stale values. "
            "Call design_recompute and read again; it may reset uncaptured driven joint poses. "
            "Recompute does not verify freshness. Mass follows physical material density, not "
            "appearance. Inertia_world is about the world origin; principal_moments are about CoM.")
    if per_body:
        note += (" per_occurrence carries one row per occurrence in the target's subtree, NESTED ones "
                 "included, keyed by full path; a row marked aggregates_children:true already covers "
                 "the rows beneath it, so summing every row double-counts (null there = the child "
                 "count could not be read).")
        note += (" per_body carries one row per BREP body - its name, the occurrence it was reached "
                 "through (null for the target's own), is_solid, mass, volume and lump_count. An "
                 "open SURFACE body is a row with is_solid false and no mass; a MESH body is not "
                 "listed (model_inspect on it reports mesh stats). A part built as several bodies "
                 "is several rows here and one row in per_occurrence.")
        if truncated:
            note += (f" Cut at {_MAX_PER_OCCURRENCE_ROWS} rows - there are more occurrences than "
                     "that (per_occurrence_truncated).")
        if body_cut:
            # The truncation an agent hits FIRST goes first: shown/true counts + remedy ahead of
            # the shape description above, not buried after it.
            note = _body_cut_note(len(body_rows), body_total, _MAX_PER_BODY_ROWS) + " " + note
    result["note"] = note
    return ok(result)


# ── router ───────────────────────────────────────────────────────────────────

def _unwrap(result):
    """(payload, None) on ok; (None, error_result) on error."""
    if result.get("isError"):
        return None, result
    try:
        return json.loads(result["content"][0]["text"]), None
    except Exception:
        return None, result


def _entity_desc(ent, kind):
    """A short human label for the resolved target."""
    if kind == "design":
        return "whole design"
    nm = safe(lambda: ent.fullPathName) or safe(lambda: ent.name)
    return f"{kind} '{nm}'" if nm else kind


def _normalize_include(include):
    if include in (None, "", []):
        return []
    if isinstance(include, str):
        return [s.strip().lower() for s in include.split(",") if s.strip()]
    return [str(s).strip().lower() for s in include]


def _assignment_bodies(entity, kind):
    """(holders, census status) for a body target or the target's scoped occurrence subtree."""
    status = {"complete": True, "truncated": None, "unavailable_census": [],
              "unavailable_slots": []}
    if kind == "body":
        status["truncated"] = False
        path = None
        try:
            occurrence = entity.assemblyContext
            if occurrence is not None:
                path = occurrence.fullPathName
                if not isinstance(path, str) or not path:
                    raise ValueError("body placement path did not read")
        except Exception as exc:
            status["complete"] = False
            status["unavailable_census"].append(
                {"scope": "body placement", "error": str(exc)[:160] or type(exc).__name__})
        return [(path, entity)], status
    if kind not in ("design", "component", "occurrence"):
        return None, status
    if kind in ("design", "component"):
        walk = _common.component_walk(entity)
        all_occs = walk.occurrences
        occs = all_occs[:_MAX_PER_BODY_ROWS + 1]
        status["complete"] = walk.complete if walk.readable else None
        if walk.broken:
            status["complete"] = False
            status["unavailable_census"].append(
                {"scope": "occurrence tree", "unreadable_occurrences": len(walk.broken)})
        if not walk.complete:
            status["unavailable_census"].append(
                {"scope": "occurrence tree", "error": f"census incomplete ({walk.method})"})
        none_slots = [i for i, occurrence in enumerate(all_occs) if occurrence is None]
        if none_slots:
            status["complete"] = False
            status["unavailable_slots"].append(
                {"scope": "occurrence tree", "count": len(none_slots),
                 "indices": none_slots[:16], "more": len(none_slots) > 16})
        if walk.total is not None and walk.total > _MAX_PER_BODY_ROWS:
            status["complete"] = False
            status["unavailable_census"].append(
                {"scope": "occurrence tree", "error": "body assignment scope exceeded occurrence cap"})
        elif status["complete"]:
            status["truncated"] = False
    else:
        occs = _subtree_occurrences(entity, _MAX_PER_BODY_ROWS)
        component = safe(lambda: entity.component)
        walk = _common.component_walk(component) if component is not None else None
        if walk is None or not walk.readable:
            status["complete"] = None
            status["unavailable_census"].append(
                {"scope": "occurrence tree", "error": "component census unavailable"})
        else:
            none_slots = [i for i, occurrence in enumerate(walk.occurrences)
                          if occurrence is None]
            expected = len(walk.occurrences) - len(none_slots)
            actual = len([occurrence for occurrence in occs[:_MAX_PER_BODY_ROWS]
                          if occurrence is not None])
            status["complete"] = (walk.complete and not walk.broken and not none_slots and
                                   walk.total is not None and walk.total <= _MAX_PER_BODY_ROWS and
                                   len(occs) <= _MAX_PER_BODY_ROWS and actual == expected)
            if status["complete"]:
                status["truncated"] = False
            if walk.broken:
                status["unavailable_census"].append(
                    {"scope": "occurrence tree", "unreadable_occurrences": len(walk.broken)})
            if none_slots:
                status["unavailable_slots"].append(
                    {"scope": "occurrence tree", "count": len(none_slots),
                     "indices": none_slots[:16], "more": len(none_slots) > 16})
            if not walk.complete:
                status["unavailable_census"].append(
                    {"scope": "occurrence tree", "error": f"census incomplete ({walk.method})"})
            if len(occs) > _MAX_PER_BODY_ROWS or (walk.total or 0) > _MAX_PER_BODY_ROWS:
                status["unavailable_census"].append(
                    {"scope": "occurrence tree", "error": "body assignment scope exceeded occurrence cap"})
        if status["complete"] is False and not status["unavailable_census"] and not status["unavailable_slots"]:
            status["unavailable_census"].append(
                {"scope": "occurrence tree", "error": "target and component census did not agree"})
    own_path = (safe(lambda: entity.fullPathName) or safe(lambda: entity.name)
                if kind == "occurrence" else None)
    rows = [(own_path, entity)]
    for index, occurrence in enumerate(occs[:_MAX_PER_BODY_ROWS]):
        if occurrence is None:
            status["complete"] = False
            status["unavailable_slots"].append({"scope": "occurrence tree", "index": index,
                                                  "error": "occurrence slot was unavailable"})
            continue
        rows.append((safe(lambda o=occurrence: o.fullPathName) or
                     safe(lambda o=occurrence: o.name), occurrence))
    if len(occs) > _MAX_PER_BODY_ROWS:
        status["truncated"] = None
        status["complete"] = False
    return rows, status


def _assignment_record(body, occurrence, fields):
    """Read requested body assignment fields independently; failed properties stay null."""
    row = {"body": safe(lambda: body.name), "occurrence": occurrence}
    unavailable = {}
    for output, getter in fields:
        try:
            value = getter()
            if output in ("material", "appearance"):
                if value is None:
                    raise ValueError("the assignment read answered nothing")
                value = value.name
                if not isinstance(value, str) or not value:
                    raise ValueError("the assignment name did not read")
            if output in ("opacity", "visible_opacity") and value is not None:
                number = _common.finite_number(value)
                if number is None:
                    raise ValueError("value is not a finite number")
                value = number
            row[output] = value
            if output == "appearance_source_type":
                row["appearance_source"] = _prefs.enum_member_name(
                    safe(lambda: adsk.core.AppearanceSourceTypes), value)
                if row["appearance_source"] is None:
                    unavailable["appearance_source"] = "source type has no readable enum label"
        except Exception as exc:
            row[output] = None
            unavailable[output] = str(exc)[:160] or type(exc).__name__
            if output == "appearance_source_type":
                row["appearance_source"] = None
                unavailable["appearance_source"] = unavailable[output]
    if unavailable:
        row["unavailable"] = unavailable
    return row


def _assignment_slice(entity, kind, include):
    """Actual material or appearance assignments for the target's bodies and instances."""
    holders, status = _assignment_bodies(entity, kind)
    if holders is None:
        return error(f"Material/appearance reads do not support target kind '{kind}'. Target a body, component, or occurrence.")
    rows, body_total = [], 0
    for occurrence, holder in holders:
        if kind == "body":
            bodies, count = [holder], 1
        else:
            try:
                bodies = holder.bRepBodies
                count = bodies.count
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise ValueError(f"invalid body count {count!r}")
            except Exception as exc:
                label = occurrence or safe(lambda holder=holder: holder.name) or kind
                status["complete"] = False
                status["unavailable_census"].append(
                    {"scope": label, "collection": "bRepBodies",
                     "error": str(exc)[:160] or type(exc).__name__})
                continue
        body_total += count
        for index in range(min(count, max(0, _MAX_PER_BODY_ROWS - len(rows)))):
            if kind == "body":
                body = holder
            else:
                try:
                    body = bodies.item(index)
                    if body is None:
                        raise ValueError("item returned None")
                except Exception as exc:
                    label = occurrence or safe(lambda holder=holder: holder.name) or kind
                    status["complete"] = False
                    status["unavailable_slots"].append(
                        {"scope": label, "collection": "bRepBodies", "index": index,
                         "error": str(exc)[:160] or type(exc).__name__})
                    continue
            fields = []
            if "material" in include:
                fields.append(("material", lambda body=body: body.material))
            if "appearance" in include:
                fields.extend((
                    ("appearance", lambda body=body: body.appearance),
                    ("appearance_source_type", lambda body=body: body.appearanceSourceType),
                    ("opacity", lambda body=body: body.opacity),
                    ("visible_opacity", lambda body=body: body.visibleOpacity),
                ))
            rows.append(_assignment_record(body, occurrence, fields))
    if body_total > _MAX_PER_BODY_ROWS:
        status["truncated"] = True
        status["complete"] = False
    elif (status["truncated"] is None or status["unavailable_census"] or
          any(slot.get("scope") == "occurrence tree" for slot in status["unavailable_slots"])):
        status["truncated"] = None
    return ok({"bodies": rows, "truncated": status["truncated"],
               "occurrence_path_scope": ("relative to target component" if kind == "component"
                                         else "assembly context of the target"),
               "scope_complete": status["complete"],
               "unavailable_census": status["unavailable_census"],
               "unavailable_slots": status["unavailable_slots"]})


def handler(target: str = "", include=None, units: str = "mm", accuracy: str = "medium",
            per_body: bool = False, frame: str = "") -> dict:
    """Measure a target at the right detail level (rich read)."""
    design = _common.design()
    if not design:
        return error("No active design. Open or create a document first (see doc_new).")

    # Resolve + classify the target ONCE (TargetRef is the single resolver). The cores below measure
    # the RESOLVED ENTITY - no second, divergent lookup, so kind and measurement always agree.
    resolved, terr = _TARGET.resolve(target)
    if terr:
        return terr if isinstance(terr, dict) else error(terr)
    ent, kind = resolved
    desc = _entity_desc(ent, kind)

    inc = _normalize_include(include)
    bad = [s for s in inc if s not in _SLICES and s not in _DEFAULT_NAMES]
    if bad:
        return error(f"Unknown include {bad}. Valid: {', '.join(_SLICES + _DEFAULT_NAMES)}.")

    # A MESH target is measured by mesh stats (it has no BRep bbox/mass the solid path computes).
    if kind == "mesh":
        if any(s in inc for s in ("material", "appearance")):
            return error("Material/appearance reads require a body, component, or occurrence target.")
        from . import _mesh_common
        out, e = _unwrap(_mesh_common.mesh_measure_of_body(ent, units))
        if e:
            return e
        out["kind"] = "mesh"
        # The measure sets a note of its own only for an OPEN mesh, and that sentence is the
        # actionable half - composing over it rather than assigning is what keeps it on the wire.
        measured = out.pop("note", "")
        out["note"] = ("Mesh target: triangle/vertex counts + watertight (is_closed) + bbox. (A mesh has "
                       "no B-Rep bounding box or mass; target a solid body/occurrence for "
                       "include=['mass'].)") + ((" " + measured) if measured else "")
        return ok(out)

    # Solid/occurrence/component/design: the bbox measurement, unless include= asked past it.
    deep = [s for s in inc if s in _SLICES]
    want_default = not deep or any(s in _DEFAULT_NAMES for s in inc)
    out = {}
    if want_default:
        out, e = _unwrap(_bbox(design, ent, desc, frame, units))
        if e:
            return e
        if kind == "body":
            # A body's disconnected-piece count: a multi-lump body is usually a shipped defect (a
            # join that fused nothing), and no interference or bbox read can show it. None = unread.
            out["lump_count"] = _geom.lump_count(ent)
    out["kind"] = kind
    if "mass" in inc:
        out["mass"], e = _unwrap(_physical_properties(design, ent, desc, units, accuracy, per_body))
        if e:
            return e
    elif not any(s in inc for s in ("material", "appearance")):
        # Only the bbox so far - point at the deeper slices + the part-space option.
        out["note"] = ("Bounding box over the SOLID/SURFACE/MESH bodies only - sketch and construction "
                       "geometry (planes, axes) are excluded, so an orphaned datum does not inflate it. "
                       "Add include=['mass'] for physical properties; include=['material'] or "
                       "include=['appearance'] reads body assignments. 'per_body' adds a row per body "
                       "and per occurrence in the subtree. "
                       "'frame'=<Joint Origin> measures in part space.")
    for assignment in ("material", "appearance"):
        if assignment in inc:
            result = _assignment_slice(ent, kind, [assignment])
            if result.get("isError"):
                return result
            out[assignment] = json.loads(result["content"][0]["text"])
    return ok(out)


TOOL_DESCRIPTION = (
    "Measure bounds or mesh stats; opt-in mass/material/appearance."
)

tool = (
    Tool.create_simple(name="model_inspect", description=TOOL_DESCRIPTION)
    .add_input_property(*_TARGET.as_property())
    .add_input_property("include", {"type": "array",
            "items": {"type": "string", "enum": list(_SLICES + _DEFAULT_NAMES)},
            "description": "'default' keeps the bounding box beside it."})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_input_property("accuracy", {"type": "string",
            "enum": ["low", "medium", "high", "very_high"]})
    .add_input_property("per_body", {"type": "boolean"})
    .add_input_property(*_FRAME.as_property())
    .strict_schema()
)
item = Item.create_tool_item(tool=tool, write="read", handler=handler, run_on_main_thread=True)


def register_tool():
    register(item)
