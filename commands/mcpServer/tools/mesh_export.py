# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: write geometry to a MESH file (STL / OBJ / 3MF) on local disk. The design is
never modified; a written file is verified against a pre-write snapshot of the output path.
"""

import os
import struct
import math
import tempfile

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import ok, error, safe
from . import _assert
from . import _common
from . import _export
from . import _inputs

app = adsk.core.Application.get()

# format -> (file extension, ExportManager factory name). Each factory takes (geometry, filename).
_FORMATS = {
"obj": (".obj", "createOBJExportOptions"),
"3mf": (".3mf", "createC3MFExportOptions"),
"stl": (".stl", "createSTLExportOptions"),
}

# refinement -> the MeshRefinementSettings enum member name (set on the export options when present).
_REFINEMENTS = {
"high": "MeshRefinementHigh",
"medium": "MeshRefinementMedium",
"low": "MeshRefinementLow",
}

_EXPORT_TARGET = _inputs.BodyRef("target", kind="any", required=False,
                                 description="Omit = the whole design.")
_EXPORT_FORMAT = _inputs.Choice("format", options=list(_FORMATS), default="3mf")
_EXPORT_REFINE = _inputs.Choice("refinement", options=list(_REFINEMENTS), default="medium")
# STLExportOptions.unitType is sticky session state: an export that never assigns it writes the unit
# of the last explicit assignment made anywhere in the session, across documents. So the omitted
# case still ASSIGNS the default (mm, the unit mesh_insert defaults to) rather than leaving it alone.
_EXPORT_UNITS = _inputs.Choice("stl_units", options=list(_export.STL_UNIT_MEMBERS),
                               description="format=stl only; baked into the file.")


# The two STL tessellation knobs this tool sets: wire name -> STLExportOptions member. The angle
# is passed as the number given: the build answers it as degrees (measured), not the radians its
# text says.
_STL_KNOBS = {"normal_deviation_deg": "normalDeviation", "max_aspect_ratio": "aspectRatio"}


def _knob_values(normal_deviation_deg, max_aspect_ratio):
    """({wire name: finite number} for the knobs given, error)."""
    out = {}
    for name, raw, low, high in (("normal_deviation_deg", normal_deviation_deg, 0.0, 180.0),
                                 ("max_aspect_ratio", max_aspect_ratio, 1.0, None)):
        if raw is None or raw == "":
            continue
        value = _common.finite_number(raw)
        strict = name == "normal_deviation_deg"
        if (value is None or (value <= low if strict else value < low)
                or (high is not None and value > high)):
            return None, (f"'{name}' must be a number "
                          + (f"above {low:g} and at most {high:g}" if strict else f"of at least {low:g}")
                          + f" - got {raw!r}.")
        out[name] = value
    return out, None


def _binary_stl_triangles(path):
    """The triangle count a binary STL file declares, when its size agrees with it; else None."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(80)
            count = struct.unpack("<I", fh.read(4))[0]
    except (OSError, struct.error):
        return None
    return count if size == 84 + 50 * count else None


# ── mesh_export target resolution (broad: body handle/name, component/occurrence, whole design) ──

def _resolve_export_target(design, target, fmt):
    """Resolve one export target, using an exact native root mesh for STL."""
    root = safe(lambda: design.rootComponent)
    name = (target or "").strip() if isinstance(target, str) else ""
    if not name:
        return root, "whole design (root component)", False, None

    # A handle (or a name) that resolves to a real body - BRep OR mesh - via the shared resolver.
    body, berr = _EXPORT_TARGET.resolve(name)
    if body is not None and berr is None and not isinstance(body, str):
        if _inputs._is_mesh(body):
            if fmt == "stl" and _native_root_mesh(body, root):
                return body, f"mesh body '{safe(lambda: body.name) or name}'", False, None
            # The ExportManager cannot write a MeshBody. Its owning component may be broader.
            mesh_name = safe(lambda: body.name) or name
            comp = safe(lambda: body.parentComponent) or root
            comp_name = safe(lambda: comp.name) or "its component"
            return comp, (f"component '{comp_name}' (redirected from mesh '{mesh_name}', whose "
                          f"single-body export is unavailable here)"), True, None
        return body, f"body '{safe(lambda: body.name) or name}'", False, None

    comp, comp_err = _export.find_component(design, name)
    if comp_err:
        return None, None, False, comp_err + (
            " Export one instance by its occurrence name/fullPathName, or pass a body handle from "
            "find_geometry (design_get(include=['tree']) lists the instances).")
    if comp:
        return comp, f"component '{name}'", False, None

    occ, occ_err = _inputs._resolve_occurrence("target", name)
    if occ is not None:
        return occ, f"occurrence '{safe(lambda: occ.name) or name}'", False, None
    if occ_err and _inputs.OCCURRENCE_MISS not in occ_err:
        return None, None, None, occ_err       # a refusal (several instances), not a miss

    return None, None, None, None


def _component_census(comp):
    """The redirected component's own body counts and child-occurrence count, null where a count
    did not read."""
    return {"mesh_bodies": _common.counted(lambda: comp.meshBodies.count),
            "brep_bodies": _common.counted(lambda: comp.bRepBodies.count),
            "child_occurrences": _common.counted(lambda: comp.occurrences.count)}


_CM_TO_STL = {"mm": 10.0, "cm": 1.0, "m": 0.01, "in": 1.0 / 2.54,
              "ft": 1.0 / 30.48}


def _native_root_mesh(body, root):
    """Whether the mesh coordinates belong to the root export frame."""
    return (safe(lambda: body.assemblyContext, _common._UNREADABLE) is None
            and _common.same_component(safe(lambda: body.parentComponent), root) is True)


def _exact_mesh_stl(body, root, path, unit_key):
    """Write one root mesh as binary STL and return its verified triangle count and size."""
    if not _native_root_mesh(body, root):
        return None, None, ("This mesh is not a native root body; its placement in the export "
                            "frame is not verified. Move or copy it into the root component, "
                            "then export that body.")
    mesh = safe(lambda: body.mesh)
    if mesh is None:
        return None, None, "The target mesh geometry did not read; no STL was written."
    try:
        counts = (int(mesh.triangleCount), int(mesh.quadCount), int(mesh.polygonCount),
                  int(mesh.nodeCount))
    except Exception as exc:
        return None, None, f"The target mesh counts did not read: {exc}"
    triangles, quads, polygons, nodes = counts
    if quads or polygons:
        return None, None, (f"The target mesh has {quads} quad(s) and {polygons} polygon(s). "
                            "Exact STL export needs triangles only; triangulate the mesh first.")
    if triangles > 250000:
        return None, None, (f"The target mesh has {triangles} triangles; exact STL export is "
                            "limited to 250000 in one call. Reduce the mesh first.")
    if triangles < 1 or nodes < 3 or nodes > 3 * 250000:
        return None, None, "The target mesh has an unsupported node or triangle count; no STL was written."
    try:
        coords = list(mesh.nodeCoordinatesAsDouble)
        indices = list(mesh.triangleNodeIndices)
    except Exception as exc:
        return None, None, f"The target mesh triangles did not read: {exc}"
    if len(coords) != 3 * nodes or len(indices) != 3 * triangles:
        return None, None, "The target mesh has inconsistent node or triangle counts; no STL was written."
    try:
        finite = all(math.isfinite(float(v)) for v in coords)
    except (TypeError, ValueError, OverflowError):
        finite = False
    if not finite:
        return None, None, "The target mesh has a non-finite coordinate; no STL was written."
    if any(not isinstance(i, int) or i < 0 or i >= nodes for i in indices):
        return None, None, "The target mesh has an invalid triangle node index; no STL was written."
    scale = _CM_TO_STL[unit_key]
    tmp = None
    before = _export.snapshot(path)
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".mesh-stl-", suffix=".tmp",
                                         dir=os.path.dirname(path) or ".", delete=False) as out:
            tmp = out.name
            out.write(b"Fusion-Essentials exact mesh body".ljust(80, b"\0"))
            out.write(struct.pack("<I", triangles))
            for offset in range(0, len(indices), 3):
                points = [[coords[3 * indices[offset + j] + axis] * scale
                           for axis in range(3)] for j in range(3)]
                a = [points[1][i] - points[0][i] for i in range(3)]
                b = [points[2][i] - points[0][i] for i in range(3)]
                normal = (a[1] * b[2] - a[2] * b[1],
                          a[2] * b[0] - a[0] * b[2],
                          a[0] * b[1] - a[1] * b[0])
                length = math.sqrt(sum(v * v for v in normal))
                normal = [v / length for v in normal] if length else [0.0, 0.0, 0.0]
                out.write(struct.pack("<12fH", *normal, *points[0], *points[1], *points[2], 0))
        os.replace(tmp, path)
        tmp = None
    except (OSError, OverflowError, ValueError, struct.error) as exc:
        return None, None, f"Exact mesh STL write failed: {exc}"
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    size, issue = _export.verify_written(path, before)
    count = _binary_stl_triangles(path)
    if issue or count != triangles:
        return None, None, issue or "The written STL triangle count did not match the target mesh."
    return count, size, None


def _apply_refinement(opts, refine_key):
    """The refinement key when the options object reads it back after the set, else None."""
    mrs = safe(lambda: adsk.fusion.MeshRefinementSettings)
    member = _REFINEMENTS.get(refine_key)
    val = safe(lambda: getattr(mrs, member)) if (mrs is not None and member) else None
    if val is None:
        return None                      # this build carries no MeshRefinementSettings member
    return _export.applied_pair(opts, "meshRefinement", val, refine_key)[0]


def _apply_stl_units(opts, unit_key):
    """Set STLExportOptions.unitType and read it back: (applied key or None, verified)."""
    val = _export.stl_unit_enum(unit_key)
    if val is None:
        return _export.NOT_APPLIED       # this build carries no DistanceUnits member for the key
    return _export.applied_pair(opts, "unitType", val, unit_key)


def _units_not_landed(unit_key, subject):
    """The clause both export paths append when the unit's read-back disagreed with the set."""
    return f"stl_units '{unit_key}' did NOT land for {subject}: 'options_applied' is null."


def _units_unverified(unit_key, subject):
    """The clause both export paths append when the options object already read the requested unit
    before it was set, so the read-back could not have failed."""
    return (f"stl_units '{unit_key}' UNVERIFIED for {subject}: 'options_verified' is false - "
            f"re-import with mesh_insert units='{unit_key}'.")


def _wrote_in_units(unit_key):
    """The clause both export paths append when the unit did read back, naming it for mesh_insert."""
    return (f"The export options read back units '{unit_key}' - re-import with mesh_insert "
            f"units='{unit_key}'.")


def _refinement_not_landed(ref, subject):
    """The clause both export paths append when refinement's read-back disagreed with the set;
    'subject' is what it happened to ('this file', '2 of 3 file(s)')."""
    return f"Refinement '{ref}' did NOT land for {subject}: 'refinement' is null."


def _write_mesh_file(em, factory_name, fmt, geom, path, ref, unit_key):
    """Create options, apply refinement (and the STL unit), execute, and VERIFY a non-empty file THIS
    call wrote landed (execute() can return True while writing nothing, and a stale file from an
    earlier export can sit at the same path). Returns (size_or_None, applied_refinement, units_pair,
    error_str), units_pair being the unit's (applied_key_or_None, verified)."""
    factory = safe(lambda: getattr(em, factory_name))
    if factory is None:
        return None, None, _export.NOT_APPLIED, f"this build's ExportManager has no {factory_name}"
    before = _export.snapshot(path)      # the baseline that makes the landed check THIS call's proof
    try:
        opts = factory(geom, path)
    except Exception as e:
        return None, None, _export.NOT_APPLIED, f"could not create {fmt.upper()} options: {e}"
    applied = _apply_refinement(opts, ref)
    # STL is the only format this tool bakes a unit into; C3MF's options object carries no unitType.
    units = _apply_stl_units(opts, unit_key) if fmt == "stl" else _export.NOT_APPLIED
    try:
        did = em.execute(opts)
    except Exception as e:
        return None, applied, units, f"{fmt.upper()} export failed: {e}"
    if not did:
        return None, applied, units, f"{fmt.upper()} export returned false"
    size, verr = _export.verify_written(path, before)
    if verr:
        return None, applied, units, f"{fmt.upper()} {verr}"
    return size, applied, units, None


def handler(format: str = "3mf", file_path: str = "", target: str = "",
            refinement: str = "medium", stl_units: str = "",
            split_by_component: bool = False, normal_deviation_deg=None,
            max_aspect_ratio=None) -> dict:
    """Export 'target' (body/mesh/component/occurrence, or whole design) to 'file_path' as a mesh, or
    with split_by_component one file per top-level occurrence into the directory 'file_path'."""
    fmt, ferr = _EXPORT_FORMAT.resolve(format)
    if ferr:
        return error(ferr)
    ref, rerr = _EXPORT_REFINE.resolve(refinement)
    if rerr:
        return error(rerr)
    # 'mm' when omitted, which is NOT a schema default: an stl_units on another format is refused
    # below, so sending 'mm' is not the same call as omitting it.
    unit_key, uerr = _EXPORT_UNITS.resolve(stl_units or "mm")
    if uerr:
        return error(uerr)
    if (stl_units or "").strip() and fmt != "stl":
        return error(f"'stl_units' ('{unit_key}') applies to format=stl only, and this call asked "
                     f"for format={fmt} - refusing rather than dropping it. Export as stl to bake "
                     f"the unit into the file, or omit 'stl_units'.")
    knobs, kerr = _knob_values(normal_deviation_deg, max_aspect_ratio)
    if kerr:
        return error(kerr)
    if knobs and (fmt != "stl" or split_by_component):
        return error(f"{', '.join(knobs)} apply to one format=stl file - this call asked for "
                     f"format={fmt}" + (" with split_by_component" if split_by_component else "")
                     + ". Export one stl target, or omit them.")
    if split_by_component and (target or "").strip():
        return error(f"'target' ('{target.strip()}') and split_by_component=true cannot be combined: "
                     "the split writes one file per TOP-LEVEL occurrence and would not narrow to "
                     "that target - refusing rather than dropping it. Omit 'target' to split the "
                     "whole design, or omit 'split_by_component' to export just that target.")
    ext, factory_name = _FORMATS[fmt]

    path = (file_path or "").strip().strip('"')
    if not path:
        return error("Provide 'file_path' - the local output path (a file, or a DIRECTORY when "
    "split_by_component=true). The format extension is appended if missing.")

    design = _common.design()
    if not design:
        return error("No active design to export. Open or create a document first (see doc_new).")

    # ---- per-component split: one mesh file per top-level occurrence into directory 'path' ----
    if split_by_component:
        em = safe(lambda: design.exportManager)
        if em is None:
            return error("This design exposes no exportManager - cannot export.")
        out_dir = path
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            return error(f"Could not create output directory '{out_dir}': {e}")
        occs = _export.top_level_occurrences(design)
        if occs is None:
            return error("The root component's occurrences did not read, so which components this "
                         "split would write one file each for is unknown - refusing rather than "
                         "reporting a zero-file export. Export without split_by_component to write "
                         "the whole design as one file.")
        if not occs:
            return error("No top-level occurrences to split - the design has no component instances. "
                         "Export without split_by_component to write the whole design as one file.")

        # Per output path, folded into split_by_occurrence's records below.
        applied_by_path = {}
        units_by_path = {}

        def _write_one(occ, fpath):
            size, applied, units, eerr = _write_mesh_file(em, factory_name, fmt, occ, fpath, ref,
                                                          unit_key)
            applied_by_path[fpath] = applied
            units_by_path[fpath] = units
            return size, eerr

        files, errors = _export.split_by_occurrence(occs, out_dir, ext, _write_one)
        if not files:
            return error(f"{fmt.upper()} split export wrote NO files - all "
                         f"{len(errors)} occurrence(s) failed: "
                         + _export.failure_detail(errors))
        for rec in files:
            # what LANDED for THIS file (each file got its own options object); null when the set
            # did not take, never the request echoed.
            rec["refinement"] = applied_by_path.get(rec.get("file_path"))
            if fmt == "stl":
                u_applied, u_verified = units_by_path.get(rec.get("file_path"), _export.NOT_APPLIED)
                rec["options_applied"] = {"stl_units": u_applied}
                rec["options_verified"] = {"stl_units": u_verified}
        unlanded = [rec for rec in files if rec["refinement"] is None]
        unlanded_units = [rec for rec in files
                          if (rec.get("options_applied") or {}).get("stl_units") is None
                          and fmt == "stl"]
        unverified_units = [rec for rec in files
                            if fmt == "stl"
                            and (rec.get("options_applied") or {}).get("stl_units") is not None
                            and not (rec.get("options_verified") or {}).get("stl_units")]
        head = (f"Exported {len(files)} component(s) to separate {fmt.upper()} mesh files - one "
                "per top-level occurrence.")
        out = {
            "exported": True,
            "format": fmt,
            "split_by_component": True,
            "directory": out_dir,
            "refinement_requested": ref,
            "file_count": len(files),
            "files": files,
        }
        if fmt == "stl":
            out["options_requested"] = {"stl_units": unit_key}
        if errors:
            # PARTIAL success: some occurrences produced no file. Disclosed as its own flag plus the
            # per-occurrence reasons, so a caller reading file_count alone cannot miss the shortfall.
            out["partial"] = True
            out["failed"] = errors
            head = (f"PARTIAL: {len(files)} of {len(files) + len(errors)} occurrence(s) exported; "
                    f"{len(errors)} produced NO file - see 'failed'.")
        clauses = []
        if unlanded:
            clauses.append(_refinement_not_landed(
                ref, f"{len(unlanded)} of {len(files)} file(s)"))
        if unlanded_units:
            clauses.append(_units_not_landed(
                unit_key, f"{len(unlanded_units)} of {len(files)} file(s)"))
        if unverified_units:
            clauses.append(_units_unverified(
                unit_key, f"{len(unverified_units)} of {len(files)} file(s)"))
        elif fmt == "stl" and not unlanded_units:
            clauses.append(_wrote_in_units(unit_key))
        out["note"] = " ".join([head] + clauses)
        return ok(out)

    # ---- single-target export ----
    if not path.lower().endswith(ext):
        path = path + ext

    geom, desc, redirected_from_mesh, terr = _resolve_export_target(design, target, fmt)
    if geom is None:
        return error(terr or
                     (f"Export target '{target}' not found. Pass a body HANDLE from find_geometry "
                      "(precise), a body/mesh/component/occurrence NAME, or omit 'target' to export "
                      "the whole design."))

    # make sure the destination directory exists
    out_dir = os.path.dirname(path)
    if out_dir and not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            return error(f"Could not create output directory '{out_dir}': {e}")

    if _inputs._is_mesh(geom):
        if knobs or ref != "medium":
            return error("An existing mesh body is already tessellated; refinement and STL "
                         "tessellation knobs cannot change it. Omit the knobs and use the "
                         "default refinement to export its exact triangles.")
        triangles, size, issue = _exact_mesh_stl(geom, design.rootComponent, path, unit_key)
        if issue:
            return error(issue)
        return ok({"exported": True, "format": "stl", "target": desc,
                   "exact_mesh_body": True, "redirected_from_mesh": False,
                   "frame": "root", "file_path": path, "file_exists": True,
                   "size_bytes": size, "triangle_count": triangles,
                   "refinement": None, "refinement_requested": ref,
                   "stl_coordinate_units": unit_key,
                   "note": (f"Exported only {desc} as {triangles} STL triangles in {unit_key}. "
                            f"The mesh was already tessellated; refinement did not apply. "
                            f"Re-import with mesh_insert units='{unit_key}' to check the file.")})

    em = safe(lambda: design.exportManager)
    if em is None:
        return error("This design exposes no exportManager - cannot export.")
    factory = safe(lambda: getattr(em, factory_name))
    if factory is None:
        return error(f"This build's ExportManager has no {factory_name} - {fmt.upper()} export "
    "is unavailable here.")

    # The pre-write state of the target, so the landed check below proves THIS export produced the
    # file rather than finding an earlier one still sitting there.
    before = _export.snapshot(path)

    # All three mesh factories take (geometry, filename). Mutation (execute) is NOT wrapped in safe.
    try:
        opts = factory(geom, path)
    except Exception as e:
        return error(f"Could not create {fmt.upper()} export options: {e}")
    applied_refinement = _apply_refinement(opts, ref)
    applied_units, units_verified = (_apply_stl_units(opts, unit_key) if fmt == "stl"
                                     else _export.NOT_APPLIED)
    # Set after the refinement: assigning a preset resets both knobs to that preset's values.
    knob_pairs = {name: _export.applied_pair(opts, _STL_KNOBS[name], value, value)
                  for name, value in knobs.items()}
    unlanded_knobs = [name for name, pair in knob_pairs.items() if pair[0] is None]
    if unlanded_knobs:
        return error(f"{', '.join(unlanded_knobs)} did not read back on the export options, so "
                     "nothing was written. Omit them to export with 'refinement' alone.")
    if knobs:
        custom = safe(lambda: adsk.fusion.MeshRefinementSettings.MeshRefinementCustom)
        if custom is not None and safe(lambda: opts.meshRefinement) == custom:
            applied_refinement = "custom"
    try:
        did = em.execute(opts)
    except Exception as e:
        return error(f"{fmt.upper()} export failed: {e}")
    if not did:
        return error(f"{fmt.upper()} export returned false - nothing was written.")

    # execute() returning truthy is not proof a file was written (a MeshBody target returns True and
    # writes nothing), and a stale file from an earlier export can sit at the path - so success is
    # this before/after comparison, never the execute() return.
    size, verr = _export.verify_written(path, before)
    if verr:
        if redirected_from_mesh:
            return error(
                f"{fmt.upper()} export wrote no file for this MESH target: the redirect to its "
                f"owning component ({desc}) produced no file either. Convert the mesh with "
                f"mesh_to_brep and export the resulting solid, or place it in a component that "
                f"exports.")
        return error(
            f"{fmt.upper()} export reported success but {verr}. execute() returned True but produced "
            f"nothing - treating this as a FAILURE, not a false success. Check the target geometry "
            f"and the output path are valid.")

    # A component export writes the bodies of the occurrences below it too, BRep tessellated
    # (measure_api mesh-export-component-descends-into-children).
    head = ("MESH target redirected to its owning component: the file holds EVERY body of that "
            "component and of the occurrences below it, BRep tessellated. 'component_census' "
            "counts its own." if redirected_from_mesh else
            "Exported a MESH file to local disk - the design was not modified.")
    clauses = []
    if applied_refinement is None:
        clauses.append(_refinement_not_landed(ref, "this file"))
    if fmt == "stl":
        if applied_units is None:
            clauses.append(_units_not_landed(unit_key, "this file"))
        elif units_verified:
            clauses.append(_wrote_in_units(applied_units))
        else:
            clauses.append(_units_unverified(applied_units, "this file"))
    note = " ".join([head] + clauses)
    payload = {
        "exported": True,
        "format": fmt,
        "target": desc,
        "redirected_from_mesh": redirected_from_mesh,
        "refinement": applied_refinement,          # what LANDED; null when the set did not take
        "refinement_requested": ref,
        "file_path": path,
        "file_exists": True,
        "size_bytes": size,
        "note": note,
    }
    if redirected_from_mesh:
        payload["component_census"] = _component_census(geom)
    if fmt == "stl":
        # options_applied is what the options object read BACK, null when it did not; the request
        # travels under its own key. options_verified is false when the read-back could not bite -
        # the object already read the requested unit before it was set.
        payload["options_applied"] = {"stl_units": applied_units}
        payload["options_requested"] = {"stl_units": unit_key}
        payload["options_verified"] = {"stl_units": units_verified}
        for name, (landed, changed) in knob_pairs.items():
            payload["options_applied"][name] = landed
            payload["options_requested"][name] = knobs[name]
            payload["options_verified"][name] = changed
        triangles = _binary_stl_triangles(path)
        if triangles is not None:
            payload["triangle_count"] = triangles
        if knobs:
            payload["note"] += (" The tessellation settings read back; 'triangle_count' is read "
                                "from the written file. Achieved bounds are not verified; compare "
                                "the count across settings.")
    return ok(payload)


# ── tool registration ────────────────────────────────────────────────────────────────────────

TOOL_DESCRIPTION = (
    "Export geometry to a MESH file on local disk. STL can target one root mesh body exactly; "
    "other mesh targets export their whole component."
)

_EXPORT_SPEC = [_EXPORT_FORMAT, _EXPORT_REFINE, _EXPORT_UNITS, _EXPORT_TARGET]
tool = (
    _inputs.apply_to_tool(
        Tool.create_simple(name="mesh_export", description=TOOL_DESCRIPTION),
        _EXPORT_SPEC)
    .add_input_property("file_path", {"type": "string",
            "description": "Output path; a DIRECTORY when split_by_component."})
    .add_required_input("file_path")
    .add_input_property("split_by_component", {"type": "boolean",
            "description": "One file per top-level occurrence."})
    .add_input_property("normal_deviation_deg", {"type": "number", "exclusiveMinimum": 0,
                                                 "maximum": 180})
    .add_input_property("max_aspect_ratio", {"type": "number", "minimum": 1})
    .strict_schema()
)
# DeliverablesExist re-stats every claimed deliverable (single file_path or split-mode files[]) - a
# redundant gate; the handler's factored _write_mesh_file verification stays (it builds the payload).
item = Item.create_tool_item(tool=tool, write="write", handler=handler,
                             run_on_main_thread=True,
                             postconditions=[_assert.DeliverablesExist()])


def register_tool():
    register(item)
