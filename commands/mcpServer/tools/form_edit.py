# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: move a T-spline Form's body, cage vertices or cage faces, or crease cage
edges, inside one always-finished Form edit, judged by the cage re-read afterwards. WRITES."""

import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common
from . import _form_common
from . import _inputs
from . import _outputs
from . import _tsm

_PARAMETRIC_GUARD = _inputs.ModeGuard(
    _inputs.MODE_PARAMETRIC,
    fix_hint="Switch to parametric mode first (design_set_mode), then retry.")
_FORM = _inputs.FeatureRef("body", required=True, description="Form body handle from form_get.")
_ACTION = _inputs.Choice("action", ("move", "crease"), required=True)

# Two cage positions closer than this (cm) are the same position.
_TOL_CM = 1e-6

RETURNS = [
    _outputs.ReturnsName("form", of="Form"),
    _outputs.ReturnsValue("body", "the T-spline body edited"),
    _outputs.ReturnsValue("changed", "whether the Form's B-Rep reads differently afterwards"),
    _outputs.ReturnsValue("cage_before", "cage revision and counts before the edit"),
    _outputs.ReturnsValue("cage_after", "cage revision and counts after the edit"),
    _outputs.ReturnsValue("brep_before", "the Form's B-Rep before the edit"),
    _outputs.ReturnsValue("brep_after", "the Form's B-Rep after the edit"),
]


def _near(a, b):
    return all(abs(x - y) <= _TOL_CM for x, y in zip(a, b))


def _shifted(points, delta):
    return [tuple(c + d for c, d in zip(p, delta)) for p in points]


def _cage_facts(walk):
    return {"revision": _form_common.cage_revision(walk), "vertices": len(walk["vertices"]),
            "edges": len(walk["edges"]), "faces": len(walk["faces"]),
            "creased_edges": sum(1 for e in walk["edges"] if e[2])}


def _brep_facts(ff):
    """The Form's B-Rep as counts, amounts and box, each None where it did not read."""
    bodies = list(_common.iter_collection(safe(lambda: ff.bodies)))
    faces = [_common.counted(lambda b=b: b.faces.count) for b in bodies]
    volume = [_common.measured(lambda b=b: b.volume, 1.0, 9) for b in bodies]
    area = [_common.measured(lambda b=b: b.area, 1.0, 9) for b in bodies]
    return {"bodies": len(bodies),
            "faces": sum(faces) if None not in faces else None,
            "volume_cm3": round(sum(volume), 9) if None not in volume else None,
            "area_cm2": round(sum(area), 9) if None not in area else None,
            "box_cm": _form_common.body_box_cm(bodies)}


_ENTITIES = _inputs.FormCageHandleList(
    "entities", description="Fresh cage handles; omit for whole-body move.")


def _request(action, entities, translation, creased, k):
    """(handles, delta in cm or None, error) for the inputs one action takes."""
    handles = entities if entities is not None else []
    if not isinstance(handles, list) or any(not isinstance(h, str) for h in handles) or (
            entities is not None and not handles):
        return None, None, "'entities' is a list of cage handles from find_geometry."
    if action == "crease":
        if type(creased) is not bool or not handles or translation is not None:
            return None, None, ("action='crease' takes 'entities' (form_edge handles) and "
                                "'creased' true or false, and no 'translation'.")
        return handles, None, None
    if creased is not None:
        return None, None, "'creased' belongs to action='crease'; drop it."
    if (not isinstance(translation, (list, tuple)) or len(translation) != 3
            or any(_common.finite_number(v) is None for v in translation)
            or not any(translation)):
        return None, None, ("action='move' takes 'translation' as three numbers [x, y, z], not "
                            f"all zero - got {translation!r}.")
    return handles, tuple(float(v) * k for v in translation), None


def _kind_error(action, picked, walk):
    """Why the picked cage entities do not fit the action, or None."""
    kinds = {kind for kind, _i in picked}
    if action == "crease":
        return None if kinds == {"form_edge"} else "action='crease' takes form_edge handles only."
    if not picked:
        return None
    if kinds not in ({"form_vertex"}, {"form_face"}):
        return ("action='move' takes form_vertex handles or form_face handles, one kind per "
                "call; an edge is not moved.")
    if kinds == {"form_face"}:
        seen = []
        for _kind, index in picked:
            for point in walk["faces"][index]:
                if any(_near(point, other) for other in seen):
                    return (f"form_face {index} shares a cage vertex with another face in "
                            "'entities'; move them in separate calls.")
            seen += walk["faces"][index]
    return None


def _apply(body, action, picked, delta, creased):
    """Run the change on the open edit's body; the list of native answers that were not True."""
    refused = []
    if action == "crease":
        for _kind, index in picked:
            body.edges.item(index).isCreased = creased
        return refused
    vector = adsk.core.Vector3D.create(*delta)
    if not picked:
        matrix = adsk.core.Matrix3D.create()
        matrix.translation = vector
        if body.transform(matrix) is not True:
            refused.append("the body")
        return refused
    for kind, index in picked:
        entity = getattr(body, _form_common.CAGE_KINDS[kind]).item(index)
        if entity.move(vector) is not True:
            refused.append(f"{kind} {index}")
    return refused


def _verdict(action, picked, delta, creased, before, after):
    """Why the re-read cage is not the one asked for, or None."""
    if after is None:
        return "the cage did not re-read"
    if [len(after[key]) for key in ("vertices", "edges", "faces")] != [
            len(before[key]) for key in ("vertices", "edges", "faces")]:
        return "the cage's vertex, edge or face count changed"
    flags_before, flags_after = [e[2] for e in before["edges"]], [e[2] for e in after["edges"]]
    if action == "crease":
        want = list(flags_before)
        for _kind, index in picked:
            want[index] = creased
        if flags_after != want:
            return "the crease flags read back differ from the ones asked for"
        if not all(_near(a, b) for a, b in zip(after["vertices"], before["vertices"])):
            return "a vertex moved during a crease"
        return None
    if flags_after != flags_before:
        return "a crease flag changed during a move"
    if not picked:
        want = _shifted(before["vertices"], delta)
    elif picked[0][0] == "form_vertex":
        want = list(before["vertices"])
        for _kind, index in picked:
            want[index] = _shifted([want[index]], delta)[0]
    else:
        for _kind, index in picked:
            if not all(_near(a, b) for a, b in zip(after["faces"][index],
                                                  _shifted(before["faces"][index], delta))):
                return f"form_face {index} does not read moved by the translation"
        return None
    if not all(_near(a, b) for a, b in zip(after["vertices"], want)):
        return "the vertices do not read where the translation puts them"
    return None


def handler(body: str = "", action: str = "", entities=None, translation=None, creased=None,
            units: str = "mm") -> dict:
    """See TOOL_DESCRIPTION."""
    k = _common.scale(units)
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    what, aerr = _ACTION.resolve(action)
    if aerr:
        return error(aerr)
    handles, delta, rerr = _request(what, entities, translation, creased, k)
    if rerr:
        return error(rerr)
    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")
    good, mode_err = _PARAMETRIC_GUARD.check(design)
    if not good:
        return mode_err
    ff, ferr = _form_common.resolve_form(design, _FORM, body)
    if ferr:
        return error(ferr)
    label = _form_common.form_label(ff)
    cage, cerr = _ENTITIES.resolve(entities, ff)
    if cerr:
        return error(cerr)
    tb, before, picked = cage
    kerr = _kind_error(what, picked, before)
    if kerr:
        return error(kerr)
    tb_name = safe(lambda: tb.name)
    brep_before = _brep_facts(ff)
    errors_before, _warn, _total = _common.timeline_health(design)

    try:
        started = ff.startEdit()
    except Exception as e:
        started = f"raised: {e}"
    if started is not True:
        return error(f"The edit of '{label}' did not open (startEdit {started}); nothing changed.")
    refused, raised = [], None
    try:
        try:
            refused = _apply(ff.tSplineBodies.item(0), what, picked, delta, creased)
        except Exception as e:
            raised = str(e) or type(e).__name__
    finally:
        state, detail = _form_common.finish_edit(ff, design)
    if state != "closed":
        return error(f"The edit of '{label}' did not confirm closed ({state}: {detail}). If the "
                     "design still reads direct (workspace_orient design.mode), ask the user to "
                     "click Finish Form; find_geometry then reads the cage as it is.")
    now_body, _berr = _form_common.one_cage_body(ff)
    after = _form_common.cage_walk(now_body) if now_body is not None else None
    why = _verdict(what, picked, delta, creased, before, after)
    if raised is not None or refused or why:
        said = (f"the change raised: {raised}" if raised is not None else
                f"Fusion did not confirm {', '.join(refused)}" if refused else why)
        unchanged = (after is not None and _form_common.cage_revision(after)
                     == _form_common.cage_revision(before))
        return error(f"'{label}' was not edited as asked: {said}. The cage reads "
                     + ("as it did before." if unchanged else
                        "changed; find_geometry reads it as it is now."))
    brep_after = _brep_facts(ff)
    errors_after, _warn_after, _total_after = _common.timeline_health(design)
    broke = [n for n in errors_after if n not in errors_before]
    changed = brep_after != brep_before
    out = {"edited": True, "form": label, "body": tb_name, "action": what, "changed": changed,
           "cage_before": _cage_facts(before), "cage_after": _cage_facts(after),
           "brep_before": brep_before, "brep_after": brep_after,
           "moved_vertices": sum(1 for a, b in zip(after["vertices"], before["vertices"])
                                 if not _near(a, b)),
           "units": units or "mm",
           "note": ("The cage re-read matches the edit. " + (
               "" if changed else "The Form's B-Rep reads the same as before: this change does "
               "not alter the surface. ") + "Earlier cage handles are spent; acquire again with "
               "find_geometry.")}
    if broke:
        out["downstream_broken"] = broke
        out["note"] += (" This edit put " + ", ".join(broke) + " into an error state.")
    record = _form_common.read_record(ff)
    if record is not None:
        box = brep_after["box_cm"]
        cage, _census, _why = _tsm.parse(safe(lambda: now_body.getTSMDescription()) or "")
        record.update({"cage_hash": _tsm.canonical_hash(cage) if cage else None,
                       "brep_faces": brep_after["faces"], "volume_cm3": None, "area_cm2": None,
                       "box_cm": [list(c) for c in box] if box else None,
                       "extent_cm": [round(box[1][i] - box[0][i], 9) for i in range(3)]
                       if box else None, "edited_by": "form_edit"})
        solid = safe(lambda: ff.bodies.item(0).isSolid)
        record["volume_cm3" if solid else "area_cm2"] = brep_after[
            "volume_cm3" if solid else "area_cm2"]
        record.pop("primitive", None)
        if not _form_common.store_record(ff, record):
            out["record_stored"] = False
    return ok(out)


TOOL_DESCRIPTION = (
    "Move a Form body or selected cage vertices/faces, or crease cage edges in place. Acquire "
    "cage handles with find_geometry; read form_get afterward.\n"
    + _outputs.produces_block(RETURNS))

tool = (
    Tool.create_simple(name="form_edit", description=TOOL_DESCRIPTION)
    .add_input_property(*_FORM.as_property(brief=True))
    .add_input_property(*_ACTION.as_property())
    .add_input_property(*_ENTITIES.as_property())
    .add_input_property("translation", {"type": "array", "items": {"type": "number"},
                                        "minItems": 3, "maxItems": 3,
                                        "description": "World delta, in units."})
    .add_input_property("creased", {"type": "boolean"})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_required_input("body")
    .add_required_input("action")
    .strict_schema()
)
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline", rung="geometry",
        evidence_test="tests/unit/test_form_edit.py::TestFormEdit"
                      "::test_a_vertex_that_reads_elsewhere_than_asked_is_an_error"))


def register_tool():
    register(item)
