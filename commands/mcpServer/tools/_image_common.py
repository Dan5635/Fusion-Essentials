# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The reference-image substrate: the root component's canvases and decals read as rows, addressed
by a ref that goes stale when the image is renamed or reordered, and the placement math both
kinds share."""

import math
import os

import adsk.core

from ._common import safe
from . import _common

MAP_BLURB = ("the reference-image substrate: image_rows/slice_reference_images - the root "
             "component's canvases and decals as rows; resolve_image - a row's ref back to its "
             "entity, refused when stale; canvas_frame/canvas_cells/decal_frame/decal_cells - a "
             "placement as centre, size, rotation and mirroring, and back to matrix cells; "
             "original_size - the size Fusion gives the image file unscaled")

KINDS = {"canvas": "canvases", "decal": "decals"}
# Two matrix cells closer than this are the cell that was asked for (cm, or a unit direction).
CELL_TOL = 1e-6
# Canvas opacity is native 0..100 and decal opacity native 0..1; both are published as 0..100.
_OPACITY_SCALE = {"canvas": 1.0, "decal": 100.0}
# A decal's opacity reads back in single precision on its 0..1 scale.
OPACITY_TOL = 1e-7


def _collection(design, kind):
    return safe(lambda: getattr(design.rootComponent, KINDS[kind]))


def image_ref(kind, index, name):
    return f"{kind}:{index}:{name}"


def canvas_frame(cells):
    """(centre, width, height, rotation rad, mirrored) of a canvas's 3x3 transform cells in cm."""
    # The rotation is read off the image's Y axis, so a horizontal flip leaves it alone.
    ex, ey, origin = (cells[0], cells[3]), (cells[1], cells[4]), (cells[2], cells[5])
    width, height = math.hypot(*ex), math.hypot(*ey)
    rotation = math.atan2(-ey[0], ey[1])
    mirrored = ex[0] * math.cos(rotation) + ex[1] * math.sin(rotation) < 0
    centre = (origin[0] + (ex[0] + ey[0]) / 2, origin[1] + (ex[1] + ey[1]) / 2)
    return centre, width, height, rotation, mirrored


def canvas_cells(centre, width, height, rotation, mirrored):
    """The nine transform cells of a canvas placed by its centre, size, rotation and mirroring."""
    side = -width if mirrored else width
    ex = (math.cos(rotation) * side, math.sin(rotation) * side)
    ey = (-math.sin(rotation) * height, math.cos(rotation) * height)
    origin = (centre[0] - (ex[0] + ey[0]) / 2, centre[1] - (ex[1] + ey[1]) / 2)
    return [ex[0], ey[0], origin[0], ex[1], ey[1], origin[1], 0.0, 0.0, 1.0]


def decal_frame(cells):
    """(origin, x direction, width, y direction, height, normal) of a decal's 4x4 cells in cm."""
    x, y = (cells[0], cells[4], cells[8]), (cells[1], cells[5], cells[9])
    width, height = math.sqrt(sum(c * c for c in x)), math.sqrt(sum(c * c for c in y))
    return ((cells[3], cells[7], cells[11]), tuple(c / width for c in x), width,
            tuple(c / height for c in y), height, (cells[2], cells[6], cells[10]))


def decal_cells(origin, x_dir, width, y_dir, height, normal):
    """The sixteen transform cells of a decal placed by its origin, directions and size."""
    cols = ([c * width for c in x_dir], [c * height for c in y_dir], list(normal), list(origin))
    return [cols[c][r] for r in range(3) for c in range(4)] + [0.0, 0.0, 0.0, 1.0]


def cells_of(entity):
    """The entity's transform cells as floats, or None."""
    cells = safe(lambda: [float(v) for v in entity.transform.asArray()])
    return cells if cells and all(math.isfinite(v) for v in cells) else None


def original_size(design, kind, entity):
    """((width, height) in cm that Fusion gives this image file unscaled, error)."""
    path = safe(lambda: entity.imageFilename)
    if not isinstance(path, str) or not os.path.isfile(path):
        return None, (f"The image file this {kind} was made from is not at '{path}', so its "
                      "original size cannot be read; 'scale' is relative to it.")
    collection = _collection(design, kind)
    try:
        if kind == "canvas":
            fresh = collection.createInput(path, entity.planarEntity)
        else:
            point = adsk.core.Point3D.create(*decal_frame(cells_of(entity))[0])
            fresh = collection.createInput(path, list(entity.faces), point)
    except Exception as e:
        return None, f"The original size of the image did not read: {e}"
    cells = cells_of(fresh)
    if cells is None:
        return None, "The original size of the image did not read."
    frame = canvas_frame(cells) if kind == "canvas" else decal_frame(cells)
    return ((frame[1], frame[2]) if kind == "canvas" else (frame[2], frame[4])), None


def _row(kind, index, entity, inv_k):
    name = safe(lambda: entity.name)
    row = {"ref": image_ref(kind, index, name), "kind": kind, "name": name,
           "image": safe(lambda: os.path.basename(entity.imageFilename)),
           "opacity": _common.measured(lambda: entity.opacity * _OPACITY_SCALE[kind], 1.0,
                                       4 if kind == "decal" else 6),
           "timeline_index": safe(lambda: entity.timelineObject.index)}
    cells = cells_of(entity)
    if kind == "canvas":
        row["display_through"] = _common.read_flag(lambda: entity.isDisplayedThrough)
        if cells is not None:
            centre, width, height, rotation, mirrored = canvas_frame(cells)
            row.update(position=[round(c * inv_k, 6) for c in centre],
                       size=[round(width * inv_k, 6), round(height * inv_k, 6)],
                       rotation_deg=round(math.degrees(rotation), 6) + 0.0, mirrored=mirrored)
    else:
        row["chain_faces"] = _common.read_flag(lambda: entity.isChainFaces)
        row["face_count"] = _common.counted(lambda: len(entity.faces))
        centre = safe(lambda: entity.faces[0].centroid)
        row["first_face_centroid"] = safe(lambda: [round(c * inv_k, 6) for c in
                                                   (centre.x, centre.y, centre.z)])
        if cells is not None:
            origin, x_dir, width, _y, height, _n = decal_frame(cells)
            row.update(origin=[round(c * inv_k, 6) for c in origin],
                       x_direction=[round(c, 6) for c in x_dir],
                       size=[round(width * inv_k, 6), round(height * inv_k, 6)])
    if cells is None:
        row["placement_unread"] = True
    return row


def image_rows(design, inv_k=10.0):
    """([row per root canvas then decal], complete): complete is False when a collection or an
    entry did not read."""
    rows, complete = [], True
    for kind in KINDS:
        collection = _collection(design, kind)
        count = _common.counted(lambda: collection.count)
        if count is None:
            complete = False
            continue
        for index in range(count):
            entity = safe(lambda index=index: collection.item(index))
            if entity is None:
                complete = False
                continue
            rows.append(_row(kind, index, entity, inv_k))
    return rows, complete


def slice_reference_images(design, max_results, units):
    """design_get's reference_images slice: the root component's canvases and decals, capped."""
    k = _common.scale(units)
    if k is None:
        return None, f"Unknown units '{units}'. Use mm, cm, or in."
    rows, complete = image_rows(design, 1.0 / k)
    cap = max(1, min(int(max_results or 50), 200))
    return {"images": rows[:cap], "total": len(rows) if complete else None,
            "truncated": len(rows) > cap, "walk_complete": complete, "units": units or "mm",
            "note": "The root component's canvases and decals. 'size' is the image as placed; "
                    "opacity runs 0-100 for both kinds. A 'ref' is spent once an image is "
                    "renamed, added or deleted - read again."}, None


def resolve_image(design, kind, reference):
    """(entity, index, error) for a row's 'ref', refused when it no longer names that entry."""
    parts = reference.split(":", 2) if isinstance(reference, str) else []
    index = int(parts[1]) if len(parts) == 3 and parts[1].isascii() and parts[1].isdecimal() else None
    if index is None or parts[0] not in KINDS:
        return None, None, ("'reference' is an image ref from "
                            "design_get(include=['reference_images']) - got "
                            f"{reference!r}.")
    if parts[0] != kind:
        return None, None, f"'reference' names a {parts[0]}, and 'kind' says {kind}."
    collection = _collection(design, kind)
    count = _common.counted(lambda: collection.count)
    entity = safe(lambda: collection.item(index)) if count is not None and index < count else None
    if entity is None or safe(lambda: entity.name) != parts[2]:
        return None, None, (f"'reference' {reference!r} no longer names a root {kind}; read "
                            "design_get(include=['reference_images']) again.")
    if _common.read_flag(lambda: entity.isDerived) is not False:
        return None, None, f"The {kind} '{parts[2]}' is derived from another design; edit it there."
    return entity, index, None
