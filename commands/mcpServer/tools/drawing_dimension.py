# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Dimension one view on a sheet of the ACTIVE drawing: Fusion's auto-dimension, or one linear,
aligned, radial, diameter, angular, arc-length or jogged-radius dimension on the view's curves
(Sheet.drawingDimensions). A placed dimension reads only its kind off the sheet's collection, so the
count and kind census is the verifiable effect and the exported sheet (drawing_export) shows the
values. WRITES.
"""

import adsk.core
import adsk.drawing

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import ok, error, safe
from . import _common
from . import _drawing_common
from . import _inputs
from . import _outputs

# What this tool RETURNS (declared once; drives the PRODUCES: prose + the assert-present contract test).
RETURNS = [
    _outputs.ReturnsValue("dimension_count_after", "the sheet's dimension count after the call"),
]

# action -> the inputs it reads beyond view/sheet; any other one supplied is refused, not ignored.
_ACTION_INPUTS = {
    "auto": ("strategy", "datum"),
    "linear": ("placement", "from_point", "to_point"),
    "aligned": ("placement", "from_point", "to_point"),
    "radial": ("placement", "curve"),
    "diameter": ("placement", "curve"),
    "angular": ("placement", "curves"),
    "arc_length": ("placement", "curve"),
    "jogged_radius": ("placement", "curve", "center_override", "jog"),
}
_FACTORIES = {"linear": "addLinearDimension", "aligned": "addLinearDimension",
              "radial": "addRadialDimension", "diameter": "addDiameterDimension",
              "angular": "addAngularDimension", "arc_length": "addArcLengthDimension",
              "jogged_radius": "addJoggedRadiusDimension"}
# action -> the ViewCurve types its one 'curve' may read; any other is refused before the add.
_CURVE_KINDS = {"radial": ("circle", "arc"), "diameter": ("circle", "arc"),
                "arc_length": ("arc", "spline"), "jogged_radius": ("circle", "arc", "spline")}
# the [x, y] sheet-point inputs, each read in the drawing's coordinate unit.
_POINT_INPUTS = ("placement", "center_override", "jog")
# kind label -> DrawingDimensionTypes member, read by NAME; a manual action's kind is its own name.
_DIMENSION_KINDS = {
    "unknown": "UnknownDrawingDimensionType", "linear": "LinearDrawingDimensionType",
    "aligned": "AlignedDrawingDimensionType", "angular": "AngularDrawingDimensionType",
    "radial": "RadiusDrawingDimensionType", "diameter": "DiameterDrawingDimensionType",
    "jogged_radius": "JoggedRadiusDrawingDimensionType",
    "ordinate": "OrdinateDrawingDimensionType", "arc_length": "ArcLengthDrawingDimensionType",
}

_ACTION = _inputs.Choice("action", list(_ACTION_INPUTS), default="auto")
_FROM = _inputs.CurvePointRef("from_point")
_TO = _inputs.CurvePointRef("to_point")

# datum key -> the DatumPositionsTypes member name (the strategy table is the shared
# _drawing_common.DIMENSION_STRATEGIES). Every member is read by NAME, and one this Fusion version
# does not define is refused rather than silently running the default strategy.
_DATUM_MEMBERS = {
    "bottom_left": "BottomLeftDatumPositionType",
    "bottom_right": "BottomRightDatumPositionType",
    "top_left": "TopLeftDatumPositionType",
    "top_right": "TopRightDatumPositionType",
}

_STRATEGY = _inputs.Choice("strategy", list(_drawing_common.DIMENSION_STRATEGIES),
                           default="baseline")
_DATUM = _inputs.Choice("datum", list(_DATUM_MEMBERS), default="bottom_left",
                        description="Corner to measure from.")

_NO_COUNT_NOTE = (
    "Sheet.drawingDimensions did not read on this build, so the dimensions cannot be counted: "
    "the call's boolean and the document's modified flag are the whole check. Export the sheet "
    "(drawing_export) to see what was placed.")
_NO_DELETE = "Fusion has no API to delete a placed dimension or read its value"
_PLACED_NOTE = (_NO_DELETE + "; drawing_export a PDF, then drawing_get(include=['text'], pdf=...) "
                "reads the value drawn. doc_save persists the drawing.")


def _count(sheet):
    """The sheet's placed-dimension count, or None where drawingDimensions does not read."""
    return _common.counted(lambda: sheet.drawingDimensions.count)


def _kind_label(value):
    """The kind label of a DrawingDimensionTypes value, or None when unreadable or unmatched."""
    if value is None:
        return None
    return next((k for k, m in _DIMENSION_KINDS.items()
                 if value == _drawing_common.enum_value("DrawingDimensionTypes", m)), None)


def _kinds(sheet):
    """The kind label each placed dimension reads, in collection order, or None without a count."""
    dims = safe(lambda: sheet.drawingDimensions)
    count = _common.counted(lambda: dims.count)
    if count is None:
        return None
    return [_kind_label(safe(lambda i=i: dims.item(i).type)) for i in range(count)]


def _new_index(before, after):
    """Where the kind census first departs from `before`, or None when dropping it differs more."""
    i = next((n for n, (a, b) in enumerate(zip(after, before)) if a != b), len(before))
    return i if after[:i] + after[i + 1:] == before else None


def _curve_refs(act, view, idx, raw):
    """(the curve arguments the action's factory takes, error)."""
    if act in ("linear", "aligned"):
        refs = []
        for kind in (_FROM, _TO):
            point, err = kind.resolve(raw[kind.name], view, idx)
            if err:
                return None, err
            refs.append(point)
        return refs, None
    if act in _CURVE_KINDS:
        found, err = _drawing_common.typed_curve(act, view, idx,
                                                 _drawing_common.as_index(raw["curve"]), "curve",
                                                 _CURVE_KINDS[act])
        return (None, err) if err else ([found], None)
    curves = _drawing_common.listed(raw["curves"])
    pair = ([_drawing_common.as_index(value) for value in curves]
            if isinstance(curves, (list, tuple)) else [])
    if len(pair) != 2 or pair[0] == pair[1]:
        return None, (f"action='angular' needs 'curves' as two different line indices of view "
                      f"{idx} (got {curves!r}); drawing_get(include=['curves'], view={idx}) "
                      "lists them.")
    refs = []
    for n, number in enumerate(pair):
        found, err = _drawing_common.typed_curve(act, view, idx, number, f"curves[{n}]", ("line",))
        if err:
            return None, err
        refs.append(found)
    return refs, None


def _factory_args(act, refs, points):
    """The action's factory arguments, in the order its API signature takes them."""
    if act == "jogged_radius":
        return refs + [points["center_override"], points["placement"], points["jog"]]
    align = [act == "aligned"] if act in ("linear", "aligned") else []
    return refs + [points["placement"]] + align


def _manual(act, dwg, sheet, view, idx, raw):
    """Place one dimension on the view's curves; success is one more item, of the kind asked."""
    unit = _drawing_common.coordinate_unit(dwg)
    xy = {}
    for name in (n for n in _POINT_INPUTS if n in _ACTION_INPUTS[act]):
        xy[name], err = _drawing_common.sheet_xy(raw[name], act, unit, name)
        if err:
            return error(err)
    refs, err = _curve_refs(act, view, idx, raw)
    if err:
        return error(err)
    points = {}
    for name, at in xy.items():
        points[name] = safe(lambda at=at: adsk.drawing.DrawingPoint.create(
            adsk.core.Point2D.create(*at)))
        if points[name] is None:
            return error(f"DrawingPoint.create returned nothing for {name} {at} - nothing was "
                         "added.")
    before = _kinds(sheet)
    if before is None:
        return error("Sheet.drawingDimensions.count did not read before the add - nothing was "
                     "added.")
    method = _FACTORIES[act]
    args = _factory_args(act, refs, points)
    try:
        # the mutation - a raise is reported with the count it left, never swallowed
        made = getattr(sheet.drawingDimensions, method)(*args)
    except Exception as ex:
        return error(f"{method} raised on view {idx}: {ex}. The sheet's dimension count reads "
                     f"{_count(sheet)} ({len(before)} before). Retry with other points, or on a "
                     "fresh drawing of the same source (drawing_create).")
    # The returned object reads type Unknown and equals no collection item, so the kind and the
    # new item's index are read off the collection's own census.
    after = _kinds(sheet)
    valid = _common.read_flag(lambda: made.isValid) if made is not None else None
    count, kind = ((len(after), after.count(act)) if after is not None else (None, None))
    if (made is None or valid is not True or count != len(before) + 1
            or kind != before.count(act) + 1):
        got = "null" if made is None else f"a dimension whose isValid reads {valid}"
        return error(f"{method} returned {got} on view {idx}; the sheet's dimension count reads "
                     f"{count} ({len(before)} before) and its {act} count {kind} "
                     f"({before.count(act)} before), so one added {act} dimension is not "
                     f"confirmed. {_NO_DELETE}; drawing_export shows the sheet.")
    grown = [k for k in dict.fromkeys(after) if after.count(k) > before.count(k)]
    return ok({
        "dimensioned": True,
        "action": act,
        "sheet": safe(lambda: sheet.name),
        "view_index": idx,
        "dimension_count_before": len(before),
        "dimension_count_after": count,
        "dimension_index": _new_index(before, after),
        "type_read": grown[0] if len(grown) == 1 else None,
        **xy,
        "placement_unit": unit,
        "note": _PLACED_NOTE,
    })


def handler(view: int = None, strategy: str = "baseline", datum: str = "bottom_left",
            sheet: str = "", action: str = "auto", placement=None, from_point: str = None,
            to_point: str = None, curve: int = None, curves=None, center_override=None,
            jog=None) -> dict:
    """See TOOL_DESCRIPTION."""
    vals, verr = _inputs.resolve_inputs(
        [_ACTION, _STRATEGY, _DATUM], {"action": action, "strategy": strategy, "datum": datum})
    if verr:
        return verr
    act, strat_key, datum_key = vals["action"], vals["strategy"], vals["datum"]
    raw = {"placement": placement, "from_point": from_point, "to_point": to_point,
           "curve": curve, "curves": curves, "center_override": center_override, "jog": jog}
    given = [name for name, value in raw.items() if value not in (None, "", [])]
    given += [kind.name for kind in (_STRATEGY, _DATUM) if vals[kind.name] != kind.default]
    stray = [name for name in given if name not in _ACTION_INPUTS[act]]
    if stray:
        return error(f"action='{act}' reads {', '.join(_ACTION_INPUTS[act])} - it does not take "
                     f"{', '.join(stray)}.")

    dwg = _drawing_common.active_drawing()
    if dwg is None:
        return error("No drawing to dimension: the active document is not a drawing. Open the "
                     "drawing (doc_open by file_id) and make it active, then retry.")
    sheet, sheet_error = _drawing_common.resolve_sheet(dwg, (sheet or "").strip())
    if sheet_error:
        return error(sheet_error)

    target, idx, err = _drawing_common.view_at(sheet, view)
    if err:
        return error(err)

    before = _count(sheet)
    if act == "auto":
        return _auto(sheet, target, idx, _common.counted(lambda: sheet.views.count), strat_key,
                     datum_key, before)
    if before is None:
        return error(f"Sheet.drawingDimensions.count did not read, so nothing could confirm a "
                     f"placed dimension - action='{act}' is refused. The manual actions need "
                     "Fusion 2706 or later; action='auto' still runs here.")
    return _manual(act, dwg, sheet, target, idx, raw)


def _auto(sheet, target, idx, count, strat_key, datum_key, before):
    """Run Fusion's auto-dimension on one view; a readable count must grow."""
    try:
        inp = sheet.createAutoDimensionInput()
    except Exception as ex:
        return error(f"createAutoDimensionInput failed: {ex}")
    if inp is None:
        return error("createAutoDimensionInput returned nothing - this sheet cannot be "
                     "auto-dimensioned.")

    serr = _common.set_verified(
        inp, "dimensionStrategy",
        _drawing_common.enum_value("DimensionStrategyTypes",
                                   _drawing_common.DIMENSION_STRATEGIES[strat_key]),
        f"strategy='{strat_key}'", "AutoDimensionInput")
    if serr:
        return error(serr)
    serr = _common.set_verified(
        inp, "datumLocation",
        _drawing_common.enum_value("DatumPositionsTypes", _DATUM_MEMBERS[datum_key]),
        f"datum='{datum_key}'", "AutoDimensionInput")
    if serr:
        return error(serr)

    # A fresh AutoDimensionInput reports view=None and an assigned View reads back as an OBJECT, so
    # this gates on NON-NULL: nothing establishes that the object handed back is the View assigned,
    # so it cannot gate on identity.
    try:
        inp.view = target
    except Exception as ex:
        return error(f"Could not set the view to dimension (index {idx}): {ex}")
    if safe(lambda: inp.view) is None:
        return error(f"Setting the view did not take - AutoDimensionInput.view reads back null after "
                     f"assigning view index {idx}, so the dimensioning would run on no view.")

    doc = safe(lambda: adsk.core.Application.get().activeDocument)
    modified_before = safe(lambda: bool(doc.isModified))

    did = sheet.autoDimension(inp)     # the mutation - a raise must surface, never be swallowed
    if not did:
        return error(f"autoDimension returned false for view index {idx} with strategy "
                     f"'{strat_key}' - Fusion placed nothing. Treating this as a failure.")

    modified_after = safe(lambda: bool(doc.isModified))
    after = _count(sheet)
    if before is not None:
        if after is None or after <= before:
            return error(f"autoDimension returned true for view index {idx} with strategy "
                         f"'{strat_key}', but the sheet's dimension count reads {after} after the "
                         f"call ({before} before), so no added dimension is confirmed.")
        note = (f"The sheet's dimension count went from {before} to {after} ({after - before} "
                f"added); they may sit on views projected from view {idx}. A manual dimension "
                "already on the sheet may stop being drawn after an auto run: check it in "
                f"drawing_export's PDF. {_NO_DELETE}. doc_save persists the drawing.")
    else:
        # With no count, the flag only convicts when it was readable and FALSE on both sides; an
        # unreadable read is published as null and joins the already-modified case as inconclusive.
        if modified_before is False and modified_after is False:
            return error(f"autoDimension reported success for view index {idx} but the document "
                         "is still unmodified, so nothing was placed. " + _NO_COUNT_NOTE)
        note = "autoDimension returned true. " + _NO_COUNT_NOTE + " doc_save keeps them."
        if modified_before is None or modified_after is None:
            note = ("The document's modified flag could not be read, so nothing here confirms the "
                    "dimensioning took. " + note)
        elif modified_before:
            note = ("The document was ALREADY modified before this call, so the modified flag "
                    "cannot confirm this dimensioning on its own. " + note)

    return ok({
        "dimensioned": True,
        "action": "auto",
        "sheet": safe(lambda: sheet.name),
        "view_index": idx,
        "view_count": count,
        "strategy": strat_key,
        "datum": datum_key,
        "dimension_count_before": before,
        "dimension_count_after": after,
        "document_modified": modified_after,
        "document_modified_before": modified_before,
        "note": note,
    })


TOOL_DESCRIPTION = (
    "Dimension one view of the active drawing: auto, or one dimension on curves from "
    "drawing_get(include=['curves'], view=N)."
)

FULL_DESCRIPTION = TOOL_DESCRIPTION + "\n" + _outputs.produces_block(RETURNS)

tool = (
    Tool.create_simple(name="drawing_dimension", description=FULL_DESCRIPTION)
    .add_input_property(*_ACTION.as_property())
    .add_input_property("view", {"type": "integer", "description": "0-based."})
    .add_input_property("sheet", {"type": "string",
            "description": "Omit for the active sheet."})
    .add_input_property(*_STRATEGY.as_property())
    .add_input_property(*_DATUM.as_property())
    .add_input_property("placement", {"type": "array", "items": {"type": "number"},
            "description": "[x, y] in curve_unit."})
    .add_input_property(*_FROM.as_property())
    .add_input_property(*_TO.as_property(brief=True))
    .add_input_property("curve", {"type": "integer"})
    .add_input_property("curves", {"type": "array", "items": {"type": "integer"},
            "description": "Two line indices."})
    .add_input_property("center_override", {"type": "array", "items": {"type": "number"},
            "description": "Stand-in center [x, y]."})
    .add_input_property("jog", {"type": "array", "items": {"type": "number"},
            "description": "Jog point [x, y]."})
    .strict_schema()
)

item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline", rung="count",
        evidence_test="tests/unit/test_drawing_dimension.py::TestCountGate"
                      "::test_a_count_that_does_not_move_is_an_error"))


def register_tool():
    register(item)
