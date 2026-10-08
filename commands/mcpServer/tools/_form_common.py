# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The T-spline Form substrate the form_ tools share: the design-wide Form walk, the create
lifecycle with its rollback, and the creation record stored on each Form."""

import hashlib
import json

import adsk.fusion

from ._common import safe
from . import _common
from . import _export
from . import _inputs

MAP_BLURB = ("the T-spline Form substrate: all_forms/form_label/resolve_form - a Form's "
             "'<component>/<name>' address; health_label; body_box_cm; "
             "create_form/finish_edit/retire - the always-finished edit and its rollback; "
             "read_record/store_record - the creation record; one_cage_body/cage_walk/"
             "cage_revision/cage_handle/resolve_cage - the control cage by native index, refused "
             "once the cage has changed")

RECORD_GROUP, RECORD_NAME = "fe_mcp", "form"
_FORM_TYPE = "adsk::fusion::FormFeature"
_FINISH_FORM = "TSplineBaseFeatureStop"
# How long a raising finishEdit's design type is pumped for before the edit is judged still open.
_SETTLE_S = 2.0
_HEALTH = (("healthy", "HealthyFeatureHealthState"), ("warning", "WarningFeatureHealthState"),
           ("error", "ErrorFeatureHealthState"), ("suppressed", "SuppressedFeatureHealthState"),
           ("rolled_back", "RolledBackFeatureHealthState"))


def is_form(entity):
    """True when the entity reads as a FormFeature."""
    return safe(lambda: entity.objectType) == _FORM_TYPE


def form_label(ff):
    """The Form's '<component>/<name>' address - Form names repeat across components."""
    return f"{safe(lambda: ff.parentComponent.name) or '?'}/{safe(lambda: ff.name) or '?'}"


def all_forms(design):
    """[(component, FormFeature)] over every component's formFeatures, in component order."""
    return [(comp, ff) for comp in _common.all_components(design)
            for ff in _common.iter_collection(safe(lambda c=comp: c.features.formFeatures))]


def resolve_form(design, kind, raw):
    """(FormFeature, error): a timeline index through `kind`, else the one Form `raw` names."""
    want = (raw or "").strip() if isinstance(raw, str) else raw
    # An index, or the '[<component>/]<name>@<index>' address a refusal lists, goes through the kind.
    addressed = isinstance(want, str) and (_inputs._ascii_int(want) is not None
                                           or _inputs._parse_address(want)[0] is not None)
    if isinstance(want, int) or addressed:
        got, err = kind.resolve(str(want))
        if err or got is None:
            return None, err
        entity, name = got
        if not is_form(entity):
            found = (safe(lambda: entity.objectType) or type(entity).__name__).split("::")[-1]
            return None, (f"'{kind.name}': '{name}' is a {found}, not a Form - form_get lists the "
                          "Forms.")
        return entity, None
    # The formFeatures walk sees a Form inside a collapsed timeline group, which the timeline hides.
    forms = [ff for _comp, ff in all_forms(design)]
    low = str(want or "").lower()
    hits = ([ff for ff in forms if form_label(ff).lower() == low]
            or [ff for ff in forms if (safe(lambda f=ff: f.name) or "").strip().lower() == low])
    labels = _common.named_with_remainder([form_label(ff) for ff in (hits or forms)])
    if not hits:
        return None, f"'{kind.name}': no Form is named '{want}' - the Forms: {labels or '(none)'}."
    if len(hits) > 1:
        return None, (f"'{kind.name}': '{want}' names {len(hits)} Forms ({labels}) - name one as "
                      "'<component>/<name>' or by its timeline index.")
    return hits[0], None


def health_label(ff):
    """The Form's healthState as a word, or None when it does not read."""
    states = safe(lambda: adsk.fusion.FeatureHealthStates)
    hs = safe(lambda: ff.healthState)
    for label, member in _HEALTH:
        if hs is not None and hs == safe(lambda m=member: getattr(states, m)):
            return label
    return None


def body_box_cm(bodies):
    """([min], [max]) corners in cm over the bodies' boxes, or None when one does not read."""
    lo, hi = [None] * 3, [None] * 3
    for b in bodies:
        bb = safe(lambda b=b: b.boundingBox)
        for i, axis in enumerate("xyz"):
            a = _common.measured(lambda: getattr(bb.minPoint, axis), 1.0, 9)
            z = _common.measured(lambda: getattr(bb.maxPoint, axis), 1.0, 9)
            if a is None or z is None:
                return None
            lo[i] = a if lo[i] is None else min(lo[i], a)
            hi[i] = z if hi[i] is None else max(hi[i], z)
    return (lo, hi) if bodies else None


def read_record(ff):
    """The creation record form_create stored on the Form, or None."""
    attr = safe(lambda: ff.attributes.itemByName(RECORD_GROUP, RECORD_NAME))
    raw = safe(lambda: attr.value) if attr is not None else None
    try:
        rec = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    return rec if isinstance(rec, dict) else None


def store_record(ff, record):
    """True when the record was attached and reads back identically."""
    text = json.dumps(record, separators=(",", ":"), sort_keys=True)
    try:
        ff.attributes.add(RECORD_GROUP, RECORD_NAME, text)
    except Exception:
        return False
    return safe(lambda: ff.attributes.itemByName(RECORD_GROUP, RECORD_NAME).value) == text


def _parametric(design):
    """(settled, mode) for pump_until: settled once the design reads parametric."""
    mode = _inputs.current_design_type(design)
    return mode == _inputs.MODE_PARAMETRIC, mode


def finish_edit(ff, design):
    """(state, detail): 'closed'; after a raise 'raised', 'open' or 'unread'; else 'unconfirmed'."""
    try:
        done = ff.finishEdit()
    except Exception as e:
        # No Finish Form here: it would rerun the conversion that just raised. The design type
        # reads direct while an edit is open and parametric once it closes (measured).
        mode = _export.pump_until(lambda: _parametric(design), _SETTLE_S, 0.02)[1]
        state = {_inputs.MODE_PARAMETRIC: "raised", _inputs.MODE_DIRECT: "open"}.get(mode, "unread")
        return state, str(e) or type(e).__name__
    if done is True:
        return "closed", None
    ran = safe(lambda: _common.app.userInterface.commandDefinitions.itemById(
        _FINISH_FORM).execute())
    return "unconfirmed", f"finishEdit returned {done}; Finish Form's execute() returned {ran}"


def _crossing(detail, retry):
    """The self-intersection Fusion's raise names, and with `retry` the call that follows it."""
    if "SELF_INTERSECTS" not in detail:
        return " Correct the cage and call form_create again." if retry else ""
    return " The cage's surface passes through itself" + (
        " - move the grips that cross apart and call form_create again." if retry else ".")


def retire(design, ff, label, count_before):
    """'' when deleteMe removed the Form and the count is restored, else the leftover sentence."""
    try:
        did = ff.deleteMe()
        why = f"deleteMe returned {did}"
    except Exception as e:
        did, why = None, f"deleteMe raised: {e}"
    now = _common.counted(lambda: design.timeline.count)
    if did is True and now is not None and now == count_before:
        return ""
    # MEASURED: a Form whose load failed reads healthy while it holds no body, so its health
    # cannot say it is a leftover - the count is what does.
    return (f" Its removal did not confirm ({why}; the timeline reads {now} item(s), "
            f"{count_before} before): '{label}' may remain - remove it with "
            f"design_delete_feature(feature='{label}').")


def create_form(design, comp, text, name, shape=None):
    """(facts, error): add a Form, load `text` or build `shape(bodies)`, always finish it."""
    marker = _common.timeline_marker(design)[0]
    count = _common.counted(lambda: design.timeline.count)
    forms = safe(lambda: comp.features.formFeatures)
    if forms is None:
        return None, "This component exposes no formFeatures collection; nothing was created."
    ff = forms.add()
    if not ff:
        return None, ("FormFeatures.add() returned nothing; design_get(include=['timeline']) "
                      "shows whether a Form was added.")
    label = form_label(ff)
    # Design-wide reads raise inside the edit (measured), so the Form is read before it opens; an
    # unnamed body takes the Form's own name.
    want = (name or "").strip() or safe(lambda: ff.name) or ""
    try:
        started = ff.startEdit()
    except Exception as e:
        started = f"raised: {e}"
    if started is not True:
        return None, (f"The Form's edit did not open (startEdit {started})."
                      + (retire(design, ff, label, count) or " The Form was removed."))
    tb, load_error, rename_warning, back, tb_name = None, None, None, None, None
    try:
        try:
            tb = (shape(ff.tSplineBodies) if shape is not None
                  else ff.tSplineBodies.addByTSMDescription(text))
        except Exception as e:
            load_error = str(e) or type(e).__name__
        if tb is None and load_error is None:
            load_error = (("addByShapeInput" if shape is not None else "addByTSMDescription")
                          + " returned nothing")
        if tb is not None:
            # Named at once, the B-Rep the finish converts takes the same name.
            tb_name, rename_warning = _common.apply_rename(tb, want)
            back = safe(lambda: tb.getTSMDescription())
    finally:
        state, detail = finish_edit(ff, design)
    remove = f" remove '{label}' with design_delete_feature(feature='{label}')."
    raised = (f"finishEdit on '{label}' raised: {(detail or '').rstrip('. ')}"
              + (f" (the load: {load_error})" if load_error else "") + ".")
    if state == "raised":
        return None, (raised + (retire(design, ff, label, count) or " The Form was removed.")
                      + _crossing(detail, True))
    if state == "open":
        recovery = (" Ask the user to click Finish Form and choose Continue on the conversion "
                    "dialog (or correct the cage first), then" if "SELF_INTERSECTS" in detail else
                    " Ask the user to correct the cage in that edit and click Finish Form, then")
        return None, (raised + f" The design still reads direct, so the Form edit is still open "
                      f"and '{label}' was left in place." + _crossing(detail, False)
                      + recovery + remove)
    if state == "unread":
        return None, (raised + " The design type did not read after it, so whether the Form edit "
                      f"is open is unknown; '{label}' was left in place. If the design still reads "
                      "direct (workspace_orient design.mode), ask the user to click Finish Form; "
                      "then" + remove)
    if state != "closed":
        return None, (f"'{label}' was {'not loaded' if load_error else 'loaded'}, but its edit did "
                      f"not confirm closed ({detail}), so nothing was verified or deleted. If the "
                      "design still reads direct (workspace_orient design.mode), ask the user to "
                      "click Finish Form; then" + remove)
    if load_error:
        what = "primitive" if shape is not None else "cage"
        return None, (f"Fusion refused the {what}: {load_error}."
                      + (retire(design, ff, label, count) or " The Form made for it was removed."))
    return {"ff": ff, "label": label, "count_before": count, "marker_before": marker,
            "tspline_body": tb_name, "rename_warning": rename_warning, "readback": back}, None


# find_geometry kind -> the T-spline body collection it indexes.
CAGE_KINDS = {"form_vertex": "vertices", "form_edge": "edges", "form_face": "faces"}
_CAGE_MARK = ";cage="


def one_cage_body(ff):
    """(the Form's one root-owned T-spline body, error)."""
    label = form_label(ff)
    design = safe(lambda: ff.parentComponent.parentDesign)
    root = safe(lambda: design.rootComponent)
    if _common.same_component(safe(lambda: ff.parentComponent), root) is not True:
        return None, f"'{label}' is not in the root component; its cage is read there only."
    count = _common.counted(lambda: ff.tSplineBodies.count)
    if count != 1:
        return None, f"'{label}' holds {count} T-spline bodies; its cage is read for exactly one."
    body = safe(lambda: ff.tSplineBodies.item(0))
    return (body, None) if body is not None else (None, f"'{label}': its T-spline body did not read.")


def _xyz(point):
    return (float(point.x), float(point.y), float(point.z))


def cage_walk(body):
    """{'vertices': [xyz], 'edges': [(start xyz, end xyz, creased)], 'faces': [[xyz]]} in cm by
    native index, or None when any entry does not read."""
    def walk():
        verts = [_xyz(body.vertices.item(i).geometry) for i in range(body.vertices.count)]
        edges = [(_xyz(body.edges.item(i).startVertex.geometry),
                  _xyz(body.edges.item(i).endVertex.geometry), body.edges.item(i).isCreased)
                 for i in range(body.edges.count)]
        faces = [[_xyz(v.geometry) for v in body.faces.item(i).vertices]
                 for i in range(body.faces.count)]
        return {"vertices": verts, "edges": edges, "faces": faces}
    got = safe(walk)
    if not got or not got["vertices"] or any(type(e[2]) is not bool for e in got["edges"]):
        return None
    return got


def cage_revision(walk):
    """A short identity of a walked cage: any moved vertex, crease or count change alters it."""
    text = json.dumps([[[round(c, 9) for c in p] for p in walk["vertices"]],
                       [e[2] for e in walk["edges"]], len(walk["faces"])], separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def cage_point(walk, kind, index):
    """The cm position a cage entity is listed at: a vertex, an edge's middle, a face's centroid."""
    if kind == "form_vertex":
        return walk["vertices"][index]
    points = list(walk["edges"][index][:2]) if kind == "form_edge" else walk["faces"][index]
    return tuple(sum(p[i] for p in points) / len(points) for i in range(3))


def cage_handle(ff, body, kind, index, revision):
    """The handle of one cage entity: the Form's address, the kind and native index, the body's
    name and the cage revision it was read at."""
    return (f"{form_label(ff)}{_inputs._HANDLE_SEP}{kind}:{index};tb={safe(lambda: body.name)}"
            f"{_CAGE_MARK}{revision}")


def _parse_cage(handle):
    """(form label, kind, index, body name, revision) of a cage handle, or None."""
    if not isinstance(handle, str) or _inputs._HANDLE_SEP not in handle or _CAGE_MARK not in handle:
        return None
    label, _sep, rest = handle.partition(_inputs._HANDLE_SEP)
    head, _mark, revision = rest.rpartition(_CAGE_MARK)
    locator, _tb, body_name = head.partition(";tb=")
    kind, _colon, index = locator.partition(":")
    number = _inputs._ascii_int(index)
    if kind not in CAGE_KINDS or number is None or number < 0 or not label or not revision:
        return None
    return label, kind, number, body_name, revision


def resolve_cage(ff, handles, name="entities"):
    """(T-spline body, walk, [(kind, index)], error): each handle must name this Form's body at
    the cage revision that reads now."""
    body, berr = one_cage_body(ff)
    if berr:
        return None, None, None, berr
    walk = cage_walk(body)
    if walk is None:
        return None, None, None, f"The cage of '{form_label(ff)}' did not read."
    now, picked = cage_revision(walk), []
    for i, handle in enumerate(handles):
        parsed = _parse_cage(handle)
        if parsed is None:
            return None, None, None, (f"'{name}'[{i}] is not a Form cage handle - "
                                      "find_geometry(kind='form_vertex'|'form_edge'|'form_face') "
                                      "mints them.")
        label, kind, index, body_name, revision = parsed
        if label.lower() != form_label(ff).lower() or body_name != safe(lambda: body.name):
            return None, None, None, (f"'{name}'[{i}] belongs to '{label}' body '{body_name}', "
                                      f"not to '{form_label(ff)}'.")
        if revision != now:
            return None, None, None, (f"'{name}'[{i}] was read from an earlier cage of "
                                      f"'{label}'; acquire it again with find_geometry.")
        if index >= len(walk[CAGE_KINDS[kind]]):
            return None, None, None, f"'{name}'[{i}] names {kind} {index}, past the cage's end."
        if (kind, index) in picked:
            return None, None, None, f"'{name}'[{i}] repeats {kind} {index}."
        picked.append((kind, index))
    return body, walk, picked, None
