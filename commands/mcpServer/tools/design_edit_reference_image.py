# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: create, place, style or delete a canvas or a decal in the root component,
each change read back off the image itself and a delete judged by the collection's count. WRITES."""

import math
import os

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common
from . import _geom
from . import _image_common as _img
from . import _inputs
from . import _outputs

_PARAMETRIC_GUARD = _inputs.ModeGuard(
    _inputs.MODE_PARAMETRIC,
    fix_hint="Switch to parametric mode first (design_set_mode), then retry.")
_ACTION = _inputs.Choice("action", ("create", "place", "style", "delete"), required=True)
_KIND = _inputs.Choice("kind", tuple(_img.KINDS), required=True)
_PLANE = _inputs.PlaneRef(
    "plane", description="Canvas: root construction plane or planar face handle.")
_FACES = _inputs.GeometryHandleList(
    "faces", require="face", description="Decal: root-local face handles, first contains origin.")

RETURNS = [
    _outputs.ReturnsValue("action", "the action completed"),
    _outputs.ReturnsValue("kind", "canvas or decal"),
    _outputs.ReturnsValue("image", "the image's name"),
    _outputs.ReturnsValue("reference", "the image's ref after this call, null once deleted"),
    _outputs.ReturnsValue("before", "the image's row before the call, null for a create"),
    _outputs.ReturnsValue("after", "the image's row after the call, null once deleted"),
    _outputs.ReturnsValue("deleted", "whether the image is gone"),
]

# (action, kind) -> (inputs it requires, inputs it may take). A place or style needs at least one
# of its optional inputs.
_TAKES = {
    ("create", "canvas"): (("image", "plane"), ("name", "position", "scale", "rotation_deg",
                                                "opacity", "display_through", "flip_horizontal",
                                                "flip_vertical")),
    ("create", "decal"): (("image", "faces", "origin"), ("name", "x_direction", "scale",
                                                         "opacity", "chain_faces")),
    ("place", "canvas"): (("reference",), ("position", "scale", "rotation_deg",
                                           "flip_horizontal", "flip_vertical")),
    ("place", "decal"): (("reference",), ("origin", "x_direction", "scale", "chain_faces")),
    ("style", "canvas"): (("reference",), ("name", "opacity", "display_through")),
    ("style", "decal"): (("reference",), ("name", "opacity")),
    ("delete", "canvas"): (("reference",), ()),
    ("delete", "decal"): (("reference",), ()),
}


def _numbers(raw, name, count, positive=False):
    """(tuple of floats, error) for a fixed-length number list."""
    if (not isinstance(raw, (list, tuple)) or len(raw) != count
            or any(_common.finite_number(v) is None for v in raw)
            or (positive and any(v <= 0 for v in raw))):
        return None, (f"'{name}' is {count} " + ("numbers above 0" if positive else "finite numbers")
                      + f" - got {raw!r}.")
    return tuple(float(v) for v in raw), None


def _request(action, kind, given, k):
    """({name: checked value} for the inputs given, error) against what this action and kind take."""
    required, optional = _TAKES[(action, kind)]
    present = {n for n, v in given.items() if v not in (None, "", [])}
    if (action, kind) == ("place", "decal") and "faces" in present:
        return None, ("A decal stays on the faces it was created on; a redefine adds faces "
                      "and removes none. Delete the decal and create it on the faces wanted.")
    missing = [n for n in required if n not in present]
    stray = sorted(present - set(required) - set(optional))
    if missing or stray:
        return None, (f"action='{action}' on a {kind} takes {', '.join(required + optional)}"
                      + (f"; missing {', '.join(missing)}" if missing else "")
                      + (f"; drop {', '.join(stray)}" if stray else "") + ".")
    if action in ("place", "style") and not present & set(optional):
        return None, f"action='{action}' on a {kind} needs one of {', '.join(optional)}."
    out = {}
    for name, count, positive, scaled in (("position", 2, False, True), ("origin", 3, False, True),
                                          ("x_direction", 3, False, False),
                                          ("scale", 2, True, False)):
        if name in present:
            value, verr = _numbers(given[name], name, count, positive)
            if verr:
                return None, verr
            out[name] = tuple(v * k for v in value) if scaled else value
    if "x_direction" in out and not any(out["x_direction"]):
        return None, "'x_direction' is [0, 0, 0]; a direction needs a length."
    for name, low, high in (("rotation_deg", None, None), ("opacity", 0.0, 100.0)):
        if name in present:
            value = _common.finite_number(given[name])
            if value is None or (low is not None and not low <= value <= high):
                return None, (f"'{name}' is a number" + (f" from {low:g} to {high:g}" if low is not None
                                                         else "") + f" - got {given[name]!r}.")
            out[name] = value
    if kind == "canvas" and out.get("opacity", 0) != int(out.get("opacity", 0)):
        return None, (f"'opacity' on a canvas is a whole number from 0 to 100 - got "
                      f"{given['opacity']!r}.")
    for name in ("display_through", "chain_faces", "flip_horizontal", "flip_vertical"):
        if name in present:
            if type(given[name]) is not bool:
                return None, f"'{name}' is true or false - got {given[name]!r}."
            out[name] = given[name]
    for name in ("image", "name", "reference", "plane"):
        if name in present:
            out[name] = given[name].strip() if isinstance(given[name], str) else given[name]
    if "faces" in present:
        out["faces"] = given["faces"]
    return out, None


def _root_local(design, entity, what):
    """Why `entity` is not geometry of the root component itself, or None."""
    root = safe(lambda: design.rootComponent)
    owner = safe(lambda: entity.body.parentComponent) or safe(lambda: entity.parentComponent) \
        or safe(lambda: entity.component)
    if safe(lambda: entity.assemblyContext) is not None or _common.same_component(owner, root) \
            is not True:
        return f"'{what}' must be geometry of the root component itself; this tool places root images."
    return None


def _set_cells(matrix_type, cells):
    matrix = matrix_type.create()
    if matrix.setWithArray(cells) is not True:
        raise RuntimeError("the transform matrix did not take its cells")
    return matrix


def _cells_differ(got, want, skip=()):
    return got is None or len(got) != len(want) or any(
        abs(a - b) > _img.CELL_TOL for i, (a, b) in enumerate(zip(got, want)) if i not in skip)


def _canvas_cells(design, entity, spec, size_source):
    """(the cells this request asks for, error); `size_source` is where the current frame reads."""
    cells = _img.cells_of(size_source)
    if cells is None:
        return None, "The canvas's transform did not read."
    centre, width, height, rotation, mirrored = _img.canvas_frame(cells)
    if "scale" in spec:
        original, oerr = _img.original_size(design, "canvas", entity)
        if oerr:
            return None, oerr
        width, height = original[0] * spec["scale"][0], original[1] * spec["scale"][1]
    if "rotation_deg" in spec:
        rotation = math.radians(spec["rotation_deg"])
    if spec.get("flip_horizontal"):
        mirrored = not mirrored
    if spec.get("flip_vertical"):
        # A vertical flip is a half turn of a horizontally mirrored image.
        rotation, mirrored = rotation + math.pi, not mirrored
    return _img.canvas_cells(spec.get("position", centre), width, height, rotation,
                             mirrored), None


def _decal_cells(design, entity, spec, source):
    """(the cells this request asks for, error) from the frame `source` reads now."""
    cells = _img.cells_of(source)
    if cells is None:
        return None, "The decal's transform did not read."
    origin, x_dir, width, y_dir, height, normal = _img.decal_frame(cells)
    hand = 1.0 if sum(a * b for a, b in zip(_geom.cross(normal, x_dir), y_dir)) >= 0 else -1.0
    if "x_direction" in spec:
        length = math.sqrt(sum(c * c for c in spec["x_direction"]))
        x_dir = tuple(c / length for c in spec["x_direction"])
    if abs(sum(a * b for a, b in zip(x_dir, normal))) > 1e-6:
        return None, ("'x_direction' must lie in the first face's plane - it is not "
                      "perpendicular to that face's normal.")
    if "scale" in spec:
        original, oerr = _img.original_size(design, "decal", entity)
        if oerr:
            return None, oerr
        width, height = original[0] * spec["scale"][0], original[1] * spec["scale"][1]
    y_dir = tuple(c * hand for c in _geom.cross(normal, x_dir))
    return _img.decal_cells(spec.get("origin", origin), x_dir, width, y_dir, height, normal), None


# The normal column of a decal's cells: Fusion stores it as a unit vector whatever is sent.
_NORMAL_CELLS = (2, 6, 10)


def _faces_differ(entity, faces, chain):
    """True unless the decal reads every face asked for, the first one first; chaining may add more."""
    want = [_common.native_identity(f) for f in faces]
    got = safe(lambda: [_common.native_identity(f) for f in entity.faces])
    if not got or None in want or None in got:
        return True
    if got[0] != want[0] or any(w not in got for w in want):
        return True
    return not chain and any(g not in want for g in got)


def _style(kind, entity, spec):
    """Apply name, opacity and display-through; the names of the ones that did not read back."""
    missed = []
    if "name" in spec:
        entity.name = spec["name"]
        if safe(lambda: entity.name) != spec["name"]:
            missed.append("name")
    if "opacity" in spec:
        # Canvas.opacity takes a whole number and refuses a float; Decal.opacity is a fraction.
        native = int(spec["opacity"]) if kind == "canvas" else spec["opacity"] / 100.0
        entity.opacity = native
        got = _common.finite_number(safe(lambda: entity.opacity))
        if got is None or abs(got - native) > (1e-9 if kind == "canvas" else _img.OPACITY_TOL):
            missed.append("opacity")
    if "display_through" in spec:
        entity.isDisplayedThrough = spec["display_through"]
        if _common.read_flag(lambda: entity.isDisplayedThrough) is not spec["display_through"]:
            missed.append("display_through")
    return missed


def _place_canvas(design, entity, spec):
    """Assign the asked transform to a canvas; an error text when it does not read back."""
    cells, cerr = _canvas_cells(design, entity, spec, entity)
    if cerr:
        return cerr
    entity.transform = _set_cells(adsk.core.Matrix2D, cells)
    if _cells_differ(_img.cells_of(entity), cells):
        return "the canvas's transform does not read back as asked"
    return None


def _place_decal(design, entity, spec):
    """Redefine a decal on its own faces with the timeline rolled before it; an error text when
    it does not land."""
    targets = safe(lambda: list(entity.faces))
    if not targets:
        return "the decal's faces did not read"
    cells, cerr = _decal_cells(design, entity, spec, entity)
    if cerr:
        return cerr
    chain = spec.get("chain_faces", _common.read_flag(lambda: entity.isChainFaces))
    if type(chain) is not bool:
        return "the decal's chain-faces setting did not read"
    timeline = design.timeline
    marker = timeline.markerPosition
    if entity.timelineObject.rollTo(True) is not True:
        return "the timeline did not roll before the decal, so nothing changed"
    try:
        answered = entity.redefine(_set_cells(adsk.core.Matrix3D, cells), targets, chain)
    finally:
        timeline.markerPosition = marker
    if safe(lambda: timeline.markerPosition) != marker:
        return f"the timeline marker did not return to {marker}; design_edit_timeline restores it"
    if answered is not True or _cells_differ(_img.cells_of(entity), cells, skip=_NORMAL_CELLS):
        return "the decal does not read back as asked"
    if _common.read_flag(lambda: entity.isChainFaces) is not chain:
        return "the decal's chain-faces setting does not read back as asked"
    if _faces_differ(entity, targets, chain):
        return "the decal no longer reads the faces it had"
    return None


def _create(design, kind, spec):
    """(new entity, error text): add the image, then place and style it; a failed step removes it."""
    if not os.path.isfile(spec["image"]):
        return None, f"'image' is not a file: {spec['image']}."
    collection = getattr(design.rootComponent, _img.KINDS[kind])
    before = _common.counted(lambda: collection.count)
    faces = None
    if kind == "canvas":
        plane, perr = _PLANE.resolve(spec["plane"])
        if perr:
            return None, perr
        local = _root_local(design, plane, "plane")
        if local:
            return None, local
        entity = collection.add(collection.createInput(spec["image"], plane))
    else:
        faces, ferr = _FACES.resolve(spec["faces"])
        if ferr:
            return None, ferr
        for face in faces:
            local = _root_local(design, face, "faces")
            if local:
                return None, local
        if len(faces) > 1 and spec.get("chain_faces") is not False:
            return None, (f"'faces' names {len(faces)} faces with chaining on, and a chained decal "
                          "keeps only the first. Pass chain_faces=false to place it on all of them.")
        fresh = collection.createInput(spec["image"], faces,
                                       adsk.core.Point3D.create(*spec["origin"]))
        if "chain_faces" in spec:
            fresh.isChainFaces = spec["chain_faces"]
        # The image file is the same one, so the fresh input's own size is the original.
        wanted, cerr = _decal_cells(design, fresh, {k: v for k, v in spec.items()
                                                    if k in ("x_direction", "origin")}, fresh)
        if cerr:
            return None, cerr
        if "scale" in spec:
            origin, x_dir, width, y_dir, height, normal = _img.decal_frame(wanted)
            wanted = _img.decal_cells(origin, x_dir, width * spec["scale"][0], y_dir,
                                      height * spec["scale"][1], normal)
        if "x_direction" in spec or "scale" in spec:
            fresh.transform = _set_cells(adsk.core.Matrix3D, wanted)
        entity = collection.add(fresh)
    after = _common.counted(lambda: collection.count)
    if entity is None or before is None or after != before + 1:
        return None, (f"The {kind} did not land as one new image (count {before} before, {after} "
                      "after); design_get(include=['reference_images']) reads what is there.")
    try:
        problem = None
        if kind == "canvas" and any(n in spec for n in ("position", "scale", "rotation_deg",
                                                        "flip_horizontal", "flip_vertical")):
            problem = _place_canvas(design, entity, spec)
        missed = [] if problem else _style(kind, entity, spec)
        problem = problem or (f"{', '.join(missed)} did not read back" if missed else None)
        if not problem and kind == "decal":
            chain = _common.read_flag(lambda: entity.isChainFaces)
            if "chain_faces" in spec and chain is not spec["chain_faces"]:
                problem = "chain_faces did not read back"
            elif _cells_differ(_img.cells_of(entity), wanted, skip=_NORMAL_CELLS):
                problem = "its origin, direction or size does not read back as asked"
            elif type(chain) is not bool or _faces_differ(entity, faces, chain):
                problem = "it does not read the faces asked for"
    except Exception as e:
        problem = str(e) or type(e).__name__
    if problem:
        return None, f"The new {kind} was added but {problem}. " + _remove(collection, entity, kind)[1]
    return entity, None


def _remove(collection, entity, kind):
    """(gone, sentence): delete an image and judge it by the collection's count."""
    name = safe(lambda: entity.name)
    before = _common.counted(lambda: collection.count)
    try:
        answered = entity.deleteMe()
    except Exception as e:
        answered = f"raised: {e}"
    after = _common.counted(lambda: collection.count)
    gone = (before is not None and after == before - 1
            and safe(lambda: collection.itemByName(name)) is None)
    if gone:
        return True, (f"The {kind} '{name}' is gone (count {before} to {after})"
                      + ("." if answered is True else f", although deleteMe answered {answered}."))
    return False, (f"The {kind} '{name}' was not confirmed deleted (deleteMe answered {answered}, "
                   f"count {before} to {after}).")


def handler(action: str = "", kind: str = "", reference: str = "", image: str = "",
            name: str = "", plane: str = "", faces=None, position=None, origin=None,
            x_direction=None, scale=None, rotation_deg=None, opacity=None, display_through=None,
            chain_faces=None, flip_horizontal=None, flip_vertical=None, units: str = "mm") -> dict:
    """See TOOL_DESCRIPTION."""
    k = _common.scale(units)
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    what, aerr = _ACTION.resolve(action)
    which, kerr = _KIND.resolve(kind)
    if aerr or kerr:
        return error(aerr or kerr)
    given = {"reference": reference, "image": image, "name": name, "plane": plane, "faces": faces,
             "position": position, "origin": origin, "x_direction": x_direction, "scale": scale,
             "rotation_deg": rotation_deg, "opacity": opacity, "display_through": display_through,
             "chain_faces": chain_faces, "flip_horizontal": flip_horizontal,
             "flip_vertical": flip_vertical}
    spec, rerr = _request(what, which, given, k)
    if rerr:
        return error(rerr)
    design, design_refusal = _common.require_design()
    if design_refusal is not None:
        return design_refusal
    good, mode_err = _PARAMETRIC_GUARD.check(design)
    if not good:
        return mode_err
    collection = getattr(design.rootComponent, _img.KINDS[which])

    def row_of(entity):
        """The image's row, or None unless exactly one entry of the collection carries its name."""
        name = safe(lambda: entity.name)
        hits = [i for i in range(_common.counted(lambda: collection.count) or 0)
                if safe(lambda i=i: collection.item(i).name) == name]
        return _img._row(which, hits[0], entity, 1.0 / k) if len(hits) == 1 else None

    out = {"action": what, "kind": which, "before": None, "deleted": False, "units": units or "mm"}
    if what == "create":
        try:
            entity, problem = _create(design, which, spec)
        except Exception as e:
            entity, problem = None, (f"Creating the {which} raised: {e}. "
                                     "design_get(include=['reference_images']) reads what is there.")
        if problem:
            return error(problem)
    else:
        entity, _index, serr = _img.resolve_image(design, which, spec["reference"])
        if serr:
            return error(serr)
        out["before"] = row_of(entity)
    if what == "delete":
        gone, sentence = _remove(collection, entity, which)
        if not gone:
            return error(sentence)
        out.update(image=out["before"]["name"], reference=None, after=None, deleted=True,
                   note=sentence)
        return ok(out)
    if what in ("place", "style"):
        try:
            if what == "style":
                missed = _style(which, entity, spec)
                problem = f"{', '.join(missed)} did not read back" if missed else None
            elif which == "canvas":
                problem = _place_canvas(design, entity, spec)
            else:
                problem = _place_decal(design, entity, spec)
        except Exception as e:
            problem = f"the change raised: {e}"
        if problem:
            return error(f"The {which} '{safe(lambda: entity.name)}' was not changed as asked: "
                         f"{problem}. design_get(include=['reference_images']) reads it as it is.")
    after = row_of(entity)
    if after is None:
        return error(f"The {which} was changed but its row did not read back; "
                     "design_get(include=['reference_images']) reads it.")
    out.update(image=after["name"], reference=after["ref"], after=after,
               note="Read back off the image. 'size' is the image as placed, not a calibrated "
                    "real-world size.")
    return ok(out)


TOOL_DESCRIPTION = (
    "Create, place, style or delete a root-local canvas or decal from a LOCAL image. Read "
    "design_get reference_images afterward.\n" + _outputs.produces_block(RETURNS))

_XYZ = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
_UV = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
tool = (
    Tool.create_simple(name="design_edit_reference_image", description=TOOL_DESCRIPTION)
    .add_input_property(*_ACTION.as_property())
    .add_input_property(*_KIND.as_property())
    .add_input_property("reference", {"type": "string", "description":
                                      "Fresh design_get image ref; existing image actions."})
    .add_input_property("image", {"type": "string"})
    .add_input_property("name", {"type": "string"})
    .add_input_property(*_PLANE.as_property(brief=True))
    .add_input_property(*_FACES.as_property(brief=True))
    .add_input_property("position", {**_UV, "description": "Canvas [u,v] in its plane frame."})
    .add_input_property("origin", {**_XYZ, "description":
                                   "Decal origin on first face, root coordinates."})
    .add_input_property("x_direction", {**_XYZ, "description":
                                        "Decal in-plane root direction; normalized."})
    .add_input_property("scale", {"type": "array", "items": {"type": "number",
                                                             "exclusiveMinimum": 0},
                                  "minItems": 2, "maxItems": 2, "description":
                                  "[u_scale,v_scale] relative to original image."})
    .add_input_property("rotation_deg", {"type": "number"})
    .add_input_property("opacity", {"type": "number", "minimum": 0, "maximum": 100})
    .add_input_property("display_through", {"type": "boolean"})
    .add_input_property("chain_faces", {"type": "boolean"})
    .add_input_property("flip_horizontal", {"type": "boolean"})
    .add_input_property("flip_vertical", {"type": "boolean"})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_required_input("action")
    .add_required_input("kind")
    .strict_schema()
)
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline", rung="value",
        evidence_test="tests/unit/test_design_edit_reference_image.py::TestCanvas"
                      "::test_a_transform_that_reads_back_differently_is_an_error"))


def register_tool():
    register(item)
