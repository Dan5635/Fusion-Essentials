# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: import an STL / OBJ / 3MF from a local path, or build one mesh from caller
triangle data, as a MeshBody. In a PARAMETRIC design the write runs inside a BaseFeature edit scope
(run_in_base_feature), which the API requires.
"""

import os

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common
from ._common import target_component as _target_component
from . import _inputs
from ._mesh_common import _mesh_summary
from ._design_common import run_in_base_feature

app = adsk.core.Application.get()

# A parametric mesh WRITE must run inside a BaseFeature edit scope, which run_in_base_feature opens
# and closes. That scope's open-state is undetectable from the public API (BaseFeature has no
# isEditing), so a recheck after startEdit reads false-negative on a write that succeeded.

_VALID_EXTS = (".stl", ".obj", ".3mf")

# The occurrence a name/path targets - not a bare component-name walk, so an occurrence spelling
# ('Name:1') every other tool accepts resolves here too.
_TARGET_COMPONENT = _inputs.OccurrenceRef("target_component")

# authored unit -> (MeshUnits enum member the import takes, cm per unit its stats are scaled by).
# mm/cm/in take their factor from the shared _common.scale(); m and ft are exact multiples of those
# (1 m = 1000 mm, 1 ft = 12 in), so this wider authored set holds no cm constant of its own.
_MESH_UNIT_TABLE = {
    "mm": ("MillimeterMeshUnit", _common.scale("mm")),
    "cm": ("CentimeterMeshUnit", _common.scale("cm")),
    "m": ("MeterMeshUnit", 1000.0 * _common.scale("mm")),
    "in": ("InchMeshUnit", _common.scale("in")),
    "inch": ("InchMeshUnit", _common.scale("inch")),
    "ft": ("FootMeshUnit", 12.0 * _common.scale("in")),
}


def _mesh_units(units):
    """(MeshUnits enum value, unit key, cm per unit) for an authored-unit string. The enum is what the
    import API wants; the factor scales what the payload reports back. Guarded with safe so a
    mocked/absent enum degrades to None (the caller then errors honestly)."""
    u = (units or "mm").strip().lower()
    row = _MESH_UNIT_TABLE.get(u)
    mu = safe(lambda: adsk.fusion.MeshUnits)
    if row is None or mu is None:
        return None, u, None
    return safe(lambda: getattr(mu, row[0])), u, row[1]


def _insert_meshes(comp, design, full_path, mesh_units):
    """Import through run_in_base_feature; returns (mesh_list, base_feature_name, error or None)."""

    def inner_op(base_feature):
        # meshBodies.add takes the open BaseFeature (parametric) or None (direct) as its third arg.
        try:
            mesh_list = comp.meshBodies.add(full_path, mesh_units, base_feature)
        except Exception as e:
            return error(f"Mesh import failed (meshBodies.add raised): {e}")
        return {"mesh_list": mesh_list,
    "base_feature_name": safe(lambda: base_feature.name) if base_feature else None}

    result, scope_err = run_in_base_feature(design, comp, inner_op)
    if scope_err:
        return None, None, scope_err
    if isinstance(result, dict) and result.get("isError") is True:
        return None, None, result # inner_op returned a _common.error (meshBodies.add raised)

    return result["mesh_list"], result["base_feature_name"], None


_DATA_KEYS = ("vertices", "triangles")
_MAX_VERTICES, _MAX_TRIANGLES = 2000, 4000
# Two read-back coordinates closer than this (cm) are the coordinate that was sent.
_DATA_TOL_CM = 1e-6


def _triples(rows, what, kind, cap):
    """(rows as tuples, error) for a list of three-number entries, naming the first bad one."""
    if not isinstance(rows, list) or len(rows) > cap:
        return None, f"data.{what} is a list of at most {cap} [a, b, c] entries."
    out = []
    for i, row in enumerate(rows):
        good = isinstance(row, (list, tuple)) and len(row) == 3 and all(
            (isinstance(v, int) and not isinstance(v, bool) and v >= 0) if kind is int
            else _common.finite_number(v) is not None for v in row)
        if not good:
            return None, (f"data.{what}[{i}] is {row!r}, not three "
                          + ("whole numbers of at least 0." if kind is int else "finite numbers."))
        out.append(tuple(row))
    return out, None


def _mesh_data(data, unit_cm):
    """((coords cm, indices) as flat lists, error) - every index checked
    here, because a refused add leaves its opened base feature behind, empty."""
    if not isinstance(data, dict) or set(data) - set(_DATA_KEYS):
        return None, (f"'data' is an object of {', '.join(_DATA_KEYS)} - got "
                      f"{sorted(set(data) - set(_DATA_KEYS)) if isinstance(data, dict) else data!r}.")
    verts, err = _triples(data.get("vertices"), "vertices", float, _MAX_VERTICES)
    tris, err = (None, err) if err else _triples(data.get("triangles"), "triangles", int,
                                                 _MAX_TRIANGLES)
    if err:
        return None, err
    if len(verts) < 3 or not tris:
        return None, (f"'data' needs at least 3 vertices and 1 triangle - got {len(verts)} and "
                      f"{len(tris)}.")
    for i, tri in enumerate(tris):
        if max(tri) >= len(verts) or len(set(tri)) != 3:
            return None, (f"data.triangles[{i}] is {list(tri)}: it must name three different "
                          f"vertices below {len(verts)}.")
    return ([float(v) * unit_cm for row in verts for v in row],
            [v for row in tris for v in row]), None


def _insert_data(comp, design, flat):
    """Add one mesh from flat triangle data: (mesh body, base feature name, error or None)."""
    coords, indices = flat
    before = _common.counted(lambda: comp.meshBodies.count)

    def inner_op(base_feature):
        try:
            # Fusion works the normals out from the triangles; ones passed here are not kept.
            body = comp.meshBodies.addByTriangleMeshData(coords, indices, [], [])
        except Exception as e:
            return error(f"Mesh creation failed (addByTriangleMeshData raised): {e}. "
                         "design_get(include=['timeline']) shows whether a base feature was left.")
        return {"body": body,
                "base_feature_name": safe(lambda: base_feature.name) if base_feature else None}

    result, scope_err = run_in_base_feature(design, comp, inner_op)
    if scope_err:
        return None, None, scope_err
    if isinstance(result, dict) and result.get("isError") is True:
        return None, None, result
    body, after = result["body"], _common.counted(lambda: comp.meshBodies.count)
    if body is None or before is None or after != before + 1:
        return None, None, error("addByTriangleMeshData did not add exactly one mesh body (count "
                                 f"{before} before, {after} after); mesh_get reads what is there.")
    got = safe(lambda: [float(v) for v in body.mesh.nodeCoordinatesAsDouble])
    got_idx = safe(lambda: [int(v) for v in body.mesh.triangleNodeIndices])
    if (got is None or len(got) != len(coords) or got_idx != indices
            or any(abs(a - b) > _DATA_TOL_CM for a, b in zip(got, coords))):
        return None, None, error(f"The mesh body '{safe(lambda: body.name)}' was added but does "
                                 "not read back the vertices and triangles sent; mesh_delete "
                                 "removes it.")
    return body, result["base_feature_name"], None


def _target_of(design, target_component):
    """(component, error) for the component `target_component` names (an occurrence handle/path/
    name), or the active component when it is blank."""
    raw = (target_component or "").strip() if isinstance(target_component, str) else ""
    if not raw:
        comp = _target_component(design)
        if comp is None:
            return None, "The active design exposes no component to import into."
        return comp, None
    occ, oerr = _TARGET_COMPONENT.resolve(raw)
    if oerr:
        return None, oerr
    comp = safe(lambda: occ.component)
    if comp is None:
        return None, f"Occurrence '{raw}' has no component to import into."
    return comp, None


def _from_data(data, target_component, units, name):
    """Build one mesh body from caller triangle data and read its vertices and triangles back."""
    mesh_units, ukey, unit_cm = _mesh_units(units)
    if mesh_units is None:
        return error(f"Unknown units '{units}' for mesh data. Use mm, cm, m, in, or ft.")
    flat, derr = _mesh_data(data, unit_cm)
    if derr:
        return error(derr)
    design = _common.design()
    if not design:
        return error("No active design. Open or create a document first (see doc_new).")
    comp, terr = _target_of(design, target_component)
    if terr:
        return error(terr)
    body, bf_name, ierr = _insert_data(comp, design, flat)
    if ierr:
        return ierr
    payload = {"imported": True, "component": safe(lambda: comp.name), "units": ukey,
               "base_feature": bf_name, "source": "data",
               "vertices": len(flat[0]) // 3, "triangles": len(flat[1]) // 3,
               "readback": "vertices and triangles exact",
               "note": "One MESH body built from the data; its vertices and triangles read back "
                       "as sent. mesh_get lists it."}
    want_name = (name or "").strip()
    if want_name:
        _final, rename_warning = _common.apply_rename(body, want_name)
        payload["name_applied"] = rename_warning is None
        if rename_warning:
            payload["rename_warning"] = rename_warning
    payload["bodies"] = [_mesh_summary(body, inv_scale=1.0 / unit_cm)]
    return ok(payload)


def handler(file_path: str = "", target_component: str = "",
            units: str = "mm", name: str = "", data=None) -> dict:
    """Import an STL/OBJ/3MF from a local path as a MeshBody into the active (or named) component.
    In a PARAMETRIC design the import is wrapped in a BaseFeature edit scope (API-required). WRITES."""
    path = (file_path or "").strip()
    if bool(path) == (data is not None):
        return error("Pass exactly one of 'file_path' (a .stl / .obj / .3mf file) and 'data' "
                     "(vertices and triangles) - got " + ("both." if path else "neither."))
    if data is not None:
        return _from_data(data, target_component, units, name)
    ext = os.path.splitext(path)[1].lower()
    if ext not in _VALID_EXTS:
        return error(f"Unsupported mesh file '{ext or path}'. Import needs one of: "
                     f"{', '.join(_VALID_EXTS)}.")
    if not safe(lambda: os.path.isfile(path)):
        return error(f"File not found: {path}. (To import from the data model, first resolve the file "
                     "to a local path with the data_* tools, then pass that path.)")

    design = _common.design()
    if not design:
        return error("No active design. Open or create a document first (see doc_new).")

    comp, terr = _target_of(design, target_component)
    if terr:
        return error(terr)

    mesh_units, ukey, unit_cm = _mesh_units(units)
    if mesh_units is None:
        return error(f"Unknown units '{units}' for mesh import. Use mm, cm, m, in, or ft.")

    mesh_list, bf_name, ins_err = _insert_meshes(comp, design, path, mesh_units)
    if ins_err:
        return ins_err

    count = safe(lambda: mesh_list.count, 0) or 0
    if not mesh_list or count == 0:
        return error("Mesh import returned no bodies (the file may be empty or unreadable as a mesh).")

    inv_scale = 1.0 / unit_cm
    want_name = (name or "").strip()
    bodies = []
    rename_warning = None
    name_applied = None
    for mb in _common.iter_collection(mesh_list):
        # count is the LANDED body count read off what meshBodies.add returned - a name addresses
        # one body, so it is applied only when exactly one landed, never silently dropped.
        if want_name and count == 1:
            _final, rename_warning = _common.apply_rename(mb, want_name)
            name_applied = rename_warning is None
        bodies.append(_mesh_summary(mb, inv_scale=inv_scale))

    payload = {
        "imported": True,
        "bodies": bodies,
        "component": safe(lambda: comp.name),
        "units": ukey,
        "base_feature": bf_name,
        "file": path,
        "note": ("Imported as MESH body(ies). " + (
            "Wrapped in BaseFeature '%s' (parametric design requires it)." % bf_name if bf_name
            else "Direct design - no base-feature scope needed.") +
            " Convert to BRep with mesh_to_brep to use find_geometry / fillet / CAM on it."),
    }
    if want_name and count != 1:
        name_applied = False
        payload["note"] = payload["note"] + (
            " 'name' was not applied: the import landed %d mesh bodies - rename each with "
            "design_set_name, using the names in 'bodies'." % count)
    if want_name:
        payload["name_applied"] = bool(name_applied)
    if rename_warning:
        payload["rename_warning"] = rename_warning
    return ok(payload)


def _TRIPLES(kind, cap, minimum):
    """The schema of a capped list of three-number entries."""
    item = {"type": kind} if minimum is None else {"type": kind, "minimum": minimum}
    return {"type": "array", "maxItems": cap,
            "items": {"type": "array", "items": item, "minItems": 3, "maxItems": 3}}


TOOL_DESCRIPTION = (
    "Insert exactly one LOCAL file_path or triangle data as mesh. mesh_get reads it."
)

tool = (
    Tool.create_simple(name="mesh_insert", description=TOOL_DESCRIPTION)
    .add_input_property("file_path", {"type": "string", "description": "Local path to the mesh file."})
    .add_input_property(*_TARGET_COMPONENT.as_property())
    .add_input_property("units", {"type": "string", "enum": list(_MESH_UNIT_TABLE),
            "description": "The unit the file is authored in; stats are reported in it."})
    .add_input_property("name", {"type": "string", "description": "Renames the imported body; single-body imports only."})
    .add_input_property("data", {
        "type": "object", "additionalProperties": False, "required": ["vertices", "triangles"],
        "description": "Local vertices in units.",
        "properties": {
            "vertices": _TRIPLES("number", _MAX_VERTICES, None),
            "triangles": _TRIPLES("integer", _MAX_TRIANGLES, 0)}})
    .strict_schema()
)
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline",
        rung="value",
        evidence_test="tests/unit/test_mesh_insert.py::TestMeshInsert"
          "::test_empty_import_result_errors"))


def register_tool():
    register(item)
