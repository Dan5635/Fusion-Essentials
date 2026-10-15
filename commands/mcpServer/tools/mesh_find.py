# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: acquire parts of one MESH body - face groups, nodes, triangles, the points a
ray hits, or a silhouette - each stamped with the revision of the mesh it was read from. READ-ONLY.
"""

import hashlib
import math

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common
from . import _inputs
from . import _outputs

_BODY = _inputs.BodyRef("body", kind="mesh", required=True, description="Mesh body handle.")
_KIND = _inputs.Choice("kind", ("group", "node", "triangle", "ray", "silhouette"), required=True)
_PLANE = _inputs.PlaneRef("plane",
                          description="Silhouette: typed construction plane or planar face.")
_ROWS_DEFAULT, _ROWS_CEILING = 20, 100

RETURNS = [
    _outputs.ReturnsValue("body", "the mesh body the rows were read from"),
    _outputs.ReturnsValue("frame", "the frame every coordinate is in"),
    _outputs.ReturnsValue("revision", "the mesh's node-and-triangle fingerprint at this read"),
    _outputs.ReturnsValue("matches", "the rows asked for, nearest first where a point was given"),
    _outputs.ReturnsValue("truncated", "whether rows past max_results were left out"),
]


def _vector(raw, name):
    """((x, y, z) floats, error) for a three-number input."""
    if (not isinstance(raw, (list, tuple)) or len(raw) != 3
            or any(_common.finite_number(v) is None for v in raw)):
        return None, f"'{name}' is three finite numbers [x, y, z] - got {raw!r}."
    return tuple(float(v) for v in raw), None


def _mesh_arrays(body):
    """(flat node coordinates in cm, flat triangle node indices) of the polygon mesh, or (None, None)."""
    coords = safe(lambda: [float(v) for v in body.mesh.nodeCoordinatesAsDouble])
    indices = safe(lambda: [int(v) for v in body.mesh.triangleNodeIndices])
    if (not coords or len(coords) % 3 or not all(math.isfinite(v) for v in coords)
            or indices is None or len(indices) % 3
            or any(not 0 <= i < len(coords) // 3 for i in indices)):
        return None, None
    return coords, indices


def revision(coords, indices):
    """A short identity of a mesh's nodes and triangles; any move or re-triangulation changes it."""
    text = ",".join(f"{v:.9f}" for v in coords) + "|" + ",".join(str(i) for i in indices)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _nearest_first(rows, point_key, at):
    """`rows` sorted by distance from `at` to each row's point, with that distance added."""
    if at is None:
        return rows
    for row in rows:
        row["distance"] = math.dist(row[point_key], at)
    return sorted(rows, key=lambda row: row["distance"])


def _node_rows(coords):
    return [{"index": i, "position": tuple(coords[3 * i:3 * i + 3])}
            for i in range(len(coords) // 3)]


def _triangle_rows(coords, indices):
    rows = []
    for t in range(len(indices) // 3):
        nodes = indices[3 * t:3 * t + 3]
        a, b, c = (coords[3 * n:3 * n + 3] for n in nodes)
        u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        rows.append({"index": t, "nodes": nodes,
                     "centroid": tuple((a[i] + b[i] + c[i]) / 3 for i in range(3)),
                     "area_cm2": math.sqrt(sum(x * x for x in cross)) / 2})
    return rows


def _group_rows(body):
    """([row per face group], error); a group whose centroid does not read is an error, not a row."""
    groups = safe(lambda: body.faceGroups)
    count = _common.counted(lambda: groups.count)
    if count is None:
        return None, "The mesh's face groups did not read."
    rows = []
    for i in range(count):
        group = safe(lambda i=i: groups.item(i))
        centre = safe(lambda: group.centroid)
        point = safe(lambda: (float(centre.x), float(centre.y), float(centre.z)))
        if point is None:
            return None, f"Face group {i} of the mesh did not read its centroid."
        rows.append({"temp_id": safe(lambda: group.tempId), "centroid": point,
                     "area_cm2": _common.measured(lambda: group.area, 1.0, 9),
                     "planar": _common.read_flag(lambda: group.isPlanar)})
    return rows, None


def _ray_rows(body, origin, direction):
    """([row per hit, in the order the ray meets them], error)."""
    try:
        hits = body.calculateCollisionsWithRay(adsk.core.Point3D.create(*origin),
                                               adsk.core.Vector3D.create(*direction))
    except Exception as e:
        return None, f"The ray did not compute: {e}"
    rows = []
    for i in range(len(hits)):
        point = safe(lambda i=i: (float(hits[i].x), float(hits[i].y), float(hits[i].z)))
        if point is None:
            return None, f"Ray hit {i} did not read its position."
        rows.append({"index": i, "position": point, "distance": math.dist(point, origin)})
    return rows, None


def _silhouette_rows(body, plane):
    """([row per outline], error) for the mesh's silhouette on a plane."""
    geometry = safe(lambda: plane.geometry)
    if geometry is None:
        return None, "'plane' did not read its geometry."
    try:
        lines = body.silhouette(geometry)
    except Exception as e:
        return None, f"The silhouette did not compute: {e}"
    rows = []
    for i in range(len(lines)):
        points = safe(lambda i=i: [(float(p.x), float(p.y), float(p.z)) for p in lines[i].points])
        if not points:
            return None, f"Silhouette outline {i} did not read its points."
        rows.append({"index": i, "point_count": len(points),
                     "closed": math.dist(points[0], points[-1]) <= 1e-7,
                     "length_cm": sum(math.dist(a, b) for a, b in zip(points, points[1:])),
                     "min": tuple(min(p[k] for p in points) for k in range(3)),
                     "max": tuple(max(p[k] for p in points) for k in range(3))})
    return rows, None


_POINT_KEYS = ("position", "centroid", "min", "max")


def _in_units(row, inv_k):
    """One row with its points and lengths in the caller's units."""
    out = {}
    for key, value in row.items():
        if key in _POINT_KEYS:
            out[key] = [round(v * inv_k, 6) for v in value]
        elif key in ("distance", "length_cm"):
            out[key.replace("_cm", "")] = round(value * inv_k, 6)
        elif key == "area_cm2":
            out["area"] = None if value is None else round(value * inv_k * inv_k, 6)
        else:
            out[key] = value
    return out


def handler(body: str = "", kind: str = "", nearest_to=None, ray_origin=None,
            ray_direction=None, plane: str = "", max_results: int = 20,
            units: str = "mm") -> dict:
    """See TOOL_DESCRIPTION."""
    k = _common.scale(units)
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    what, kerr = _KIND.resolve(kind)
    if kerr:
        return error(kerr)
    if not isinstance(max_results, int) or isinstance(max_results, bool) or not (
            1 <= max_results <= _ROWS_CEILING):
        return error(f"'max_results' is a whole number from 1 to {_ROWS_CEILING} - got "
                     f"{max_results!r}.")
    given = {"nearest_to": nearest_to, "ray_origin": ray_origin, "ray_direction": ray_direction,
             "plane": plane or None}
    wanted = {"ray": ("ray_origin", "ray_direction"), "silhouette": ("plane",)}.get(
        what, ("nearest_to",))
    stray = [n for n, v in given.items() if v is not None and n not in wanted]
    missing = [n for n in wanted if given[n] is None and n != "nearest_to"]
    if stray or missing:
        return error(f"kind='{what}' takes {', '.join(wanted)}"
                     + (f"; missing {', '.join(missing)}" if missing else "")
                     + (f"; drop {', '.join(stray)}" if stray else "") + ".")
    points = {}
    for name in ("nearest_to", "ray_origin", "ray_direction"):
        if given[name] is not None:
            vec, verr = _vector(given[name], name)
            if verr:
                return error(verr)
            points[name] = vec if name == "ray_direction" else tuple(v * k for v in vec)
    if "ray_direction" in points:
        length = math.sqrt(sum(c * c for c in points["ray_direction"]))
        if length <= 0:
            return error("'ray_direction' is [0, 0, 0]; a ray needs a direction.")
        points["ray_direction"] = tuple(c / length for c in points["ray_direction"])

    mesh, berr = _BODY.resolve(body)
    if berr:
        return error(berr)
    design = _common.design()
    root = safe(lambda: design.rootComponent)
    if _common.same_component(safe(lambda: mesh.parentComponent), root) is not True:
        return error(f"mesh_find reads a mesh body the root component owns; "
                     f"'{safe(lambda: mesh.name)}' reads owner "
                     f"'{safe(lambda: mesh.parentComponent.name)}'.")
    coords, indices = _mesh_arrays(mesh)
    if coords is None:
        return error(f"The nodes and triangles of '{safe(lambda: mesh.name)}' did not read.")

    if what == "node":
        rows, rerr = _nearest_first(_node_rows(coords), "position", points.get("nearest_to")), None
    elif what == "triangle":
        rows, rerr = _nearest_first(_triangle_rows(coords, indices), "centroid",
                                    points.get("nearest_to")), None
    elif what == "group":
        rows, rerr = _group_rows(mesh)
        rows = rows if rerr else _nearest_first(rows, "centroid", points.get("nearest_to"))
    elif what == "ray":
        rows, rerr = _ray_rows(mesh, points["ray_origin"], points["ray_direction"])
    else:
        resolved, perr = _PLANE.resolve(plane)
        if perr:
            return error(perr)
        rows, rerr = _silhouette_rows(mesh, resolved)
    if rerr:
        return error(rerr)
    out = {"body": safe(lambda: mesh.name), "kind": what, "frame": "world",
           "revision": revision(coords, indices), "units": units or "mm",
           "total": len(rows), "matches": [_in_units(r, 1.0 / k) for r in rows[:max_results]],
           "truncated": len(rows) > max_results,
           "note": "Node and triangle indices hold only while 'revision' does. A group's "
                   "temp_id is spent by any change to the mesh, regrouping included, which "
                   "'revision' does not see."}
    if what == "ray" and not rows:
        out["note"] = "The ray meets the mesh nowhere. " + out["note"]
    return ok(out)


TOOL_DESCRIPTION = (
    "Acquire scoped mesh groups, nodes, triangles, ray hits or a silhouette. Indices and group "
    "refs expire when owner geometry changes; these are not BRep entities.\n"
    + _outputs.produces_block(RETURNS))

_XYZ = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
tool = (
    Tool.create_simple(name="mesh_find", description=TOOL_DESCRIPTION)
    .add_input_property(*_BODY.as_property(brief=True))
    .add_input_property(*_KIND.as_property())
    .add_input_property("nearest_to", {**_XYZ, "description":
                                       "World point; sorts groups/nodes/triangles."})
    .add_input_property("ray_origin", {**_XYZ, "description": "World point."})
    .add_input_property("ray_direction", {**_XYZ, "description": "World direction; normalized."})
    .add_input_property(*_PLANE.as_property(brief=True))
    .add_input_property("max_results", {"type": "integer", "minimum": 1,
                                        "maximum": _ROWS_CEILING, "default": _ROWS_DEFAULT})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_required_input("body")
    .add_required_input("kind")
    .strict_schema()
)
item = Item.create_tool_item(tool=tool, write="read", handler=handler, run_on_main_thread=True)


def register_tool():
    register(item)
