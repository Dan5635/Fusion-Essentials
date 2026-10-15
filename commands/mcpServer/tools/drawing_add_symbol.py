# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Place one GD&T symbol on a view of the ACTIVE drawing - a feature control frame, a datum
identifier, an ISO edge symbol or a taper/slope symbol - leadered to a view curve
(Sheet.drawingSymbols). The sheet's collection reads every symbol as a datum identifier, so the
count and the kind the RETURNED object reads are the verifiable effect. WRITES.
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

RETURNS = [
    _outputs.ReturnsValue("symbol_count_after", "the sheet's symbol count after the call"),
]

# action -> the inputs it reads beyond view/sheet/attach/bends/placement; any other is refused.
_ACTION_INPUTS = {
    "feature_control_frame": ("frames", "top_note", "bottom_note", "all_around"),
    "datum_identifier": ("identifier", "datum_note", "thread_note"),
    "edge": ("direction", "upper_limit", "lower_limit", "all_around", "majority",
             "standard_label", "undefined_size", "undefined_edge"),
    "taper_slope": ("second_curve", "dimension", "symbol", "theoretically_exact"),
}
# action -> (its DrawingSymbols factory, the SymbolTypes member the returned object must read).
_FACTORIES = {
    "feature_control_frame": ("addFeatureControlFrame", "FeatureControlFrameSymbolType"),
    "datum_identifier": ("addDatumIdentifier", "DatumIdentifierSymbolType"),
    "edge": ("addEdgeSymbol", "EdgeSymbolType"),
    "taper_slope": ("addTaperSlopeSymbol", "TaperSlopeSymbolType"),
}
_KIND_LABELS = {**{act: member for act, (_method, member) in _FACTORIES.items()},
                "surface_texture": "SurfaceTextureSymbolType"}

_CHARACTERISTICS = ("straightness", "flatness", "circularity", "cylindricity", "profile_of_line",
                    "profile_of_surface", "angularity", "perpendicularity", "parallelism",
                    "position", "concentricity", "symmetry", "circular_runout", "total_runout",
                    "coaxiality")
# a frame string's fields after the characteristic, in order -> its FeatureControlFrameSectionInput
# palette property.
_FRAME_TEXTS = {"tolerance": "primaryTolerance", "primary_datum": "primaryDatum",
                "secondary_datum": "secondaryDatum", "tertiary_datum": "tertiaryDatum",
                "secondary_tolerance": "secondaryTolerance"}
_FRAME_FORM = "characteristic|" + "|".join(_FRAME_TEXTS)
_DIRECTIONS = {"vertical": "VerticalDirection", "horizontal": "HorizontalDirection",
               "undefined": "UndefinedDirection", "none": "NoDefinedDirection"}
_UNDEFINED_EDGES = {"none": "NoneUndefinedEdgeSymbolType",
                    "burr_or_passing_permitted": "BurrOrPassingPermittedUndefinedEdgeSymbolType",
                    "undercut_required": "UndercutRequiredUndefinedEdgeSymbolType"}
_TAPER_SYMBOLS = {"taper_1": "TaperOneStandardTaperSlopeSymbolType",
                  "slope_1": "SlopeOneStandardTaperSlopeSymbolType",
                  "slope_2": "SlopeTwoStandardTaperSlopeSymbolType",
                  "taper_1_flipped": "TaperOneFlippedTaperSlopeSymbolType",
                  "slope_1_flipped": "SlopeOneFlippedTaperSlopeSymbolType",
                  "slope_2_flipped": "SlopeTwoFlippedTaperSlopeSymbolType"}
# input -> its EdgeSymbolInput property, in the order they are set.
_EDGE_FIELDS = {"direction": "direction", "undefined_edge": "undefinedEdgeType",
                "upper_limit": "upperLimit", "lower_limit": "lowerLimit",
                "all_around": "isAllAround", "majority": "isMajority",
                "standard_label": "isStandardLabelShown",
                "undefined_size": "isUndefinedSizeAllowed"}
_FLAGS = ("all_around", "majority", "standard_label", "undefined_size", "theoretically_exact")

_ACTION = _inputs.Choice("action", list(_ACTION_INPUTS), required=True)
# The three Choices below go on the wire as plain strings; their resolve() names the legal values.
_DIRECTION = _inputs.Choice("direction", list(_DIRECTIONS))
_UNDEFINED_EDGE = _inputs.Choice("undefined_edge", list(_UNDEFINED_EDGES))
_SYMBOL = _inputs.Choice("symbol", list(_TAPER_SYMBOLS))
_ATTACH = _inputs.CurvePointRef("attach")

_NO_DELETE = "Fusion has no API to delete, move or read a placed symbol"
_PLACED_NOTE = _NO_DELETE + "; drawing_export's PDF shows it. doc_save persists the drawing."


def _count(sheet):
    """The sheet's placed-symbol count, or None where drawingSymbols does not read."""
    return _common.counted(lambda: sheet.drawingSymbols.count)


def _kind_label(value):
    """The action label of a SymbolTypes value, or None when unreadable or unmatched."""
    if value is None:
        return None
    return next((k for k, m in _KIND_LABELS.items()
                 if value == _drawing_common.enum_value("SymbolTypes", m)), None)


def _choice_member(name, key):
    """The enum value a Choice key names, read by NAME; None where this build lacks the member."""
    if name == "direction":
        return _drawing_common.enum_value("EdgeSymbolDirectionTypes", _DIRECTIONS[key])
    if name == "undefined_edge":
        return _drawing_common.enum_value("UndefinedEdgeSymbolTypes", _UNDEFINED_EDGES[key])
    return _drawing_common.enum_value("TaperSlopeSymbolTypes", _TAPER_SYMBOLS[key])


def _frames(raw):
    """([{text, key, characteristic, texts, secondary}], error) for the _FRAME_FORM strings."""
    frames = _drawing_common.listed(raw)
    if not isinstance(frames, (list, tuple)) or not 1 <= len(frames) <= 2:
        return None, (f"action='feature_control_frame' needs 'frames' as 1 or 2 strings "
                      f"'{_FRAME_FORM}', such as 'flatness|0.05' (got {raw!r}).")
    out = []
    for i, text in enumerate(frames):
        fields = [f.strip() for f in text.split("|")] if isinstance(text, str) else []
        if not 2 <= len(fields) <= 1 + len(_FRAME_TEXTS):
            return None, (f"frames[{i}] {text!r} needs 2 to 6 '|'-separated fields "
                          f"'{_FRAME_FORM}', such as 'position|{{dia}}0.2{{M}}|A|B'.")
        key = fields[0].lower()
        if key not in _CHARACTERISTICS:
            return None, (f"frames[{i}] {text!r}: the characteristic must be one of: "
                          f"{', '.join(_CHARACTERISTICS)}.")
        stem = "".join(word.capitalize() for word in key.split("_"))
        value = _drawing_common.enum_value("GeometricCharacteristicTypes",
                                           stem + "GeometricCharacteristicType")
        if value is None:
            return None, f"frames[{i}] {text!r}: '{key}' is not available on this Fusion version."
        if not fields[1]:
            return None, f"frames[{i}] {text!r} needs a tolerance, such as 'flatness|0.05'."
        texts = {}
        for (name, prop), field in zip(_FRAME_TEXTS.items(), fields[1:]):
            if field:
                texts[prop], err = _drawing_common.palette_parts(field, f"frames[{i}] {name}")
                if err:
                    return None, err
        out.append({"text": text, "key": key, "characteristic": value, "texts": texts,
                    "secondary": "secondaryTolerance" in texts})
    return out, None


def _plan(act, raw, choices):
    """(the action's own inputs checked and its texts parsed, error) - before any Fusion read."""
    plan = {}
    for name in ("top_note", "bottom_note", "datum_note", "thread_note"):
        if name in _ACTION_INPUTS[act] and raw[name] not in (None, ""):
            plan[name], err = _drawing_common.palette_parts(raw[name], name)
            if err:
                return None, err
    for name in ("identifier", "upper_limit", "lower_limit", "dimension"):
        if name in _ACTION_INPUTS[act] and raw[name] not in (None, ""):
            plan[name], err = _drawing_common.symbol_text(raw[name], name)
            if err:
                return None, err
    for name in _FLAGS:
        if name in _ACTION_INPUTS[act] and raw[name] is not None:
            if not isinstance(raw[name], bool):
                return None, f"'{name}' must be true or false (got {raw[name]!r})."
            plan[name] = raw[name]
    for name, key in choices.items():
        if key is not None:
            plan[name] = _choice_member(name, key)
            if plan[name] is None:
                return None, f"{name}='{key}' is not available on this Fusion version."
    if act == "feature_control_frame":
        plan["frames"], err = _frames(raw["frames"])
        if err:
            return None, err
    if act == "datum_identifier" and not (plan.get("identifier") or "").strip():
        return None, "action='datum_identifier' needs an 'identifier', such as 'A'."
    if act == "taper_slope" and not (plan.get("dimension") or "").strip():
        return None, "action='taper_slope' needs a 'dimension', such as '1:10'."
    if act == "taper_slope" and raw["second_curve"] is None:
        return None, "action='taper_slope' needs 'second_curve' - the second line's index."
    return plan, None


def _leader(act, dwg, view, idx, attach, bends, placement, second_curve):
    """({curve, second, points, echo}, error) - leader points attach, bends..., placement."""
    unit = _drawing_common.coordinate_unit(dwg)
    at, err = _drawing_common.sheet_xy(placement, act, unit, "placement")
    if err:
        return None, err
    listed = _drawing_common.listed(bends) if bends not in (None, "") else []
    if not isinstance(listed, (list, tuple)):
        return None, f"'bends' must be a list of [x, y] points (got {bends!r})."
    turns = []
    for i, bend in enumerate(listed):
        xy, err = _drawing_common.sheet_xy(bend, act, unit, f"bends[{i}]")
        if err:
            return None, err
        turns.append(xy)
    point, err = _ATTACH.resolve(attach, view, idx)
    if err:
        return None, err
    (number, key), _err = _ATTACH.parse(attach)
    second = None
    if act == "taper_slope":
        curve, err = _drawing_common.typed_curve(act, view, idx, number, "attach", ("line",))
        other = _drawing_common.as_index(second_curve)
        if not err and other == number:
            err = (f"action='taper_slope' needs two different lines (attach and second_curve "
                   f"{other}).")
        if not err:
            second, err = _drawing_common.typed_curve(act, view, idx, other, "second_curve",
                                                      ("line",))
    else:
        curve, err = _drawing_common.view_curve(view, idx, number, "attach")
    if err:
        return None, err
    coord = safe(lambda: point.coordinate)
    start = [safe(lambda: coord.x), safe(lambda: coord.y)]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in start):
        return None, f"'attach' point {number}:{key} reads no coordinate - nothing was added."
    labelled = ([("attach", start)] + [(f"bends[{i}]", xy) for i, xy in enumerate(turns)]
                + [("placement", at)])
    points = []
    for label, xy in labelled:
        made = safe(lambda xy=xy: adsk.drawing.DrawingPoint.create(adsk.core.Point2D.create(*xy)))
        if made is None:
            return None, (f"DrawingPoint.create returned nothing for {label} {xy} - nothing was "
                          "added.")
        points.append(made)
    echo = {"attach": f"{number}:{key}", "bends": turns, "placement": at, "placement_unit": unit}
    return {"curve": curve, "second": second, "points": points, "echo": echo}, None


def _palette(owner, prop, parts, label):
    """'' or the error text - `owner`'s palette list `prop` rebuilt and assigned back, unread."""
    try:
        setattr(owner, prop, _drawing_common.palette_list(getattr(owner, prop), parts))
    except Exception as ex:
        return f"Could not set {label}: {ex}"
    return ""


def _fcf_input(symbols, plan, _leader_fields):
    """(FeatureControlFrameInput or None when the factory answers null, error)."""
    inp = safe(lambda: symbols.createFeatureControlFrameInput())
    if inp is None:
        return None, ""
    frames = plan["frames"]
    err = _common.set_verified(inp, "isSecondFrameEnabled", len(frames) == 2,
                               f"a {len(frames)}-frame symbol", "FeatureControlFrameInput")
    for i, (frame, attr) in enumerate(zip(frames, ("firstFrame", "secondFrame"))):
        section = safe(lambda attr=attr: getattr(inp, attr))
        if err or section is None:
            return inp, err or f"FeatureControlFrameInput.{attr} did not read."
        err = _common.set_verified(section, "geometricCharacteristic", frame["characteristic"],
                                   f"frames[{i}].characteristic='{frame['key']}'",
                                   "FeatureControlFrameSectionInput")
        for prop, parts in frame["texts"].items():
            err = err or _palette(section, prop, parts, f"frames[{i}].{prop}")
    for name, prop in (("top_note", "topNote"), ("bottom_note", "bottomNote")):
        if name in plan:
            err = err or _palette(inp, prop, plan[name], name)
    if not err and "all_around" in plan:
        member = ("AllAroundSymbolApplicationModifierType" if plan["all_around"]
                  else "NoneSymbolApplicationModifierType")
        err = _common.set_verified(
            inp, "applicationModifier",
            _drawing_common.enum_value("SymbolApplicationModifierTypes", member),
            f"all_around={plan['all_around']}", "FeatureControlFrameInput")
    return inp, err


def _datum_input(symbols, plan, _leader_fields):
    """(DatumIdentifierInput or None when the factory answers null, error)."""
    inp = safe(lambda: symbols.createDatumIdentifierInput())
    if inp is None:
        return None, ""
    err = _common.set_verified(inp, "identifier", plan["identifier"],
                               f"identifier='{plan['identifier']}'", "DatumIdentifierInput")
    for name, prop in (("datum_note", "datumNotes"), ("thread_note", "threadNotes")):
        if name in plan:
            err = err or _palette(inp, prop, plan[name], name)
    return inp, err


def _edge_input(symbols, plan, _leader_fields):
    """(EdgeSymbolInput or None when the factory answers null, error)."""
    inp = safe(lambda: symbols.createEdgeSymbolInput())
    if inp is None:
        return None, ""
    for name, prop in _EDGE_FIELDS.items():
        if name in plan:
            err = _common.set_verified(inp, prop, plan[name], f"'{name}'", "EdgeSymbolInput")
            if err:
                return inp, err
    return inp, ""


def _taper_input(symbols, plan, leader):
    """(TaperSlopeSymbolInput or None when the factory answers null, error)."""
    inp = safe(lambda: symbols.createTaperSlopeSymbolInput())
    if inp is None:
        return None, ""
    try:
        inp.attachementCurve = leader["second"]
    except Exception as ex:
        return inp, f"Could not set the second line: {ex}"
    err = _common.set_verified(inp, "dimension", plan["dimension"],
                               f"dimension='{plan['dimension']}'", "TaperSlopeSymbolInput")
    for name, prop in (("symbol", "taperSlopeSymbolType"),
                       ("theoretically_exact", "isTheoreticallyExact")):
        if name in plan:
            err = err or _common.set_verified(inp, prop, plan[name], f"'{name}'",
                                              "TaperSlopeSymbolInput")
    return inp, err


_BUILDERS = {"feature_control_frame": _fcf_input, "datum_identifier": _datum_input,
             "edge": _edge_input, "taper_slope": _taper_input}


def handler(action: str = None, view: int = None, sheet: str = "", attach: str = None,
            bends=None, placement=None, frames=None, top_note: str = None,
            bottom_note: str = None, all_around: bool = None, identifier: str = None,
            datum_note: str = None, thread_note: str = None, direction: str = None,
            upper_limit: str = None, lower_limit: str = None, majority: bool = None,
            standard_label: bool = None, undefined_size: bool = None,
            undefined_edge: str = None, second_curve: int = None, dimension: str = None,
            symbol: str = None, theoretically_exact: bool = None) -> dict:
    """See TOOL_DESCRIPTION."""
    vals, verr = _inputs.resolve_inputs(
        [_ACTION, _DIRECTION, _UNDEFINED_EDGE, _SYMBOL],
        {"action": action, "direction": direction, "undefined_edge": undefined_edge,
         "symbol": symbol})
    if verr:
        return verr
    act = vals["action"]
    raw = {"frames": frames, "top_note": top_note, "bottom_note": bottom_note,
           "all_around": all_around, "identifier": identifier, "datum_note": datum_note,
           "thread_note": thread_note, "direction": direction, "upper_limit": upper_limit,
           "lower_limit": lower_limit, "majority": majority, "standard_label": standard_label,
           "undefined_size": undefined_size, "undefined_edge": undefined_edge,
           "second_curve": second_curve, "dimension": dimension, "symbol": symbol,
           "theoretically_exact": theoretically_exact}
    stray = [n for n, v in raw.items()
             if v not in (None, "", []) and n not in _ACTION_INPUTS[act]]
    if stray:
        return error(f"action='{act}' reads {', '.join(_ACTION_INPUTS[act])} beside the "
                     f"attachment - it does not take {', '.join(stray)}.")
    plan, err = _plan(act, raw, {k: vals[k] for k in ("direction", "undefined_edge", "symbol")})
    if err:
        return error(err)

    dwg = _drawing_common.active_drawing()
    if dwg is None:
        return error("No drawing to place a symbol on: the active document is not a drawing. Open "
                     "the drawing (doc_open by file_id) and make it active, then retry.")
    standard = _drawing_common.standard_label(dwg)
    if act == "edge" and standard != "iso":
        return error(f"action='edge' places an ISO edge symbol; this drawing's standard reads "
                     f"{standard or 'unread'}, and Fusion offers edge symbols on ISO only.")
    for i, frame in enumerate(plan.get("frames") or []):
        if frame["secondary"] and standard != "asme":
            return error(f"frames[{i}] {frame['text']!r} carries a secondary tolerance, which "
                         f"applies on ASME drawings only; this drawing's standard reads "
                         f"{standard or 'unread'}, where Fusion ignores it - drop it.")
    target_sheet, sheet_error = _drawing_common.resolve_sheet(dwg, (sheet or "").strip())
    if sheet_error:
        return error(sheet_error)
    target, idx, err = _drawing_common.view_at(target_sheet, view)
    if err:
        return error(err)
    leader, err = _leader(act, dwg, target, idx, attach, bends, placement, second_curve)
    if err:
        return error(err)

    symbols = safe(lambda: target_sheet.drawingSymbols)
    before = _common.counted(lambda: symbols.count)
    if before is None:
        return error("Sheet.drawingSymbols.count did not read, so nothing could confirm a placed "
                     "symbol - nothing was added.")
    inp, err = _BUILDERS[act](symbols, plan, leader)
    if inp is None:
        return error(f"Sheet.drawingSymbols returned no input for action='{act}' on this "
                     f"{standard or 'unread-standard'} drawing - nothing was added.")
    if err:
        return error(err + " Nothing was added.")
    try:
        inp.viewCurve = leader["curve"]
        inp.leaderPoints = leader["points"]
        inp.placementPoint = leader["points"][-1]
    except Exception as ex:
        return error(f"Could not attach the symbol to curve {leader['echo']['attach']}: {ex}. "
                     "Nothing was added.")
    return _place(act, target_sheet, symbols, inp, idx, before, leader["echo"])


def _place(act, sheet, symbols, inp, idx, before, echo):
    """Run the action's factory; success is one more symbol and a returned object of that kind."""
    method, _member = _FACTORIES[act]
    try:
        made = getattr(symbols, method)(inp)    # the mutation - a raise is reported, not swallowed
    except Exception as ex:
        return error(f"{method} raised on view {idx}: {str(ex).rstrip('.')}. The sheet's symbol "
                     f"count reads {_count(sheet)} ({before} before).")
    try:
        # A refused add does not raise; Fusion raises its reason on the next call - this count read.
        after = sheet.drawingSymbols.count
    except Exception as ex:
        return error(f"{method} was refused on view {idx}: {str(ex).rstrip('.')}. The sheet's "
                     f"symbol count re-reads {_count(sheet)} ({before} before). "
                     f"drawing_get(include=['curves'], view={idx}) lists the curves to attach to.")
    after = after if isinstance(after, int) and not isinstance(after, bool) else None
    valid = _common.read_flag(lambda: made.isValid) if made is not None else None
    kind = _kind_label(safe(lambda: made.symbolType)) if made is not None else None
    if made is None or valid is not True or after != before + 1 or kind != act:
        got = "null" if made is None else f"a symbol reading isValid {valid} and kind {kind}"
        return error(f"{method} returned {got} on view {idx}; the sheet's symbol count reads "
                     f"{after} ({before} before), so one added {act} symbol is not confirmed. "
                     f"{_NO_DELETE}; drawing_export shows the sheet.")
    return ok({
        "added": True,
        "action": act,
        "sheet": safe(lambda: sheet.name),
        "view_index": idx,
        "symbol_count_before": before,
        "symbol_count_after": after,
        "type_read": kind,
        **echo,
        "note": _PLACED_NOTE,
    })


TOOL_DESCRIPTION = (
    "Place one GD&T symbol leadered from a curve point of drawing_get(include=['curves'], view=N). "
    "Text takes {token} symbols, e.g. {dia}. drawing_export shows it."
)

FULL_DESCRIPTION = TOOL_DESCRIPTION + "\n" + _outputs.produces_block(RETURNS)

tool = (
    Tool.create_simple(name="drawing_add_symbol", description=FULL_DESCRIPTION)
    .add_input_property(*_ACTION.as_property())
    .add_input_property("view", {"type": "integer", "description": "0-based."})
    .add_input_property("sheet", {"type": "string"})
    .add_input_property(*_ATTACH.as_property())
    .add_input_property("bends", {"type": "array",
            "items": {"type": "array", "items": {"type": "number"}}})
    .add_input_property("placement", {"type": "array", "items": {"type": "number"},
            "description": "[x, y] in curve_unit."})
    .add_input_property("frames", {"type": "array", "items": {"type": "string"},
            "description": "characteristic|tolerance|datum|datum|datum|tol2"})
    .add_input_property("top_note", {"type": "string"})
    .add_input_property("bottom_note", {"type": "string"})
    .add_input_property("all_around", {"type": "boolean"})
    .add_input_property("identifier", {"type": "string"})
    .add_input_property("datum_note", {"type": "string"})
    .add_input_property("thread_note", {"type": "string"})
    .add_input_property("direction", {"type": "string"})
    .add_input_property("upper_limit", {"type": "string"})
    .add_input_property("lower_limit", {"type": "string"})
    .add_input_property("majority", {"type": "boolean"})
    .add_input_property("standard_label", {"type": "boolean"})
    .add_input_property("undefined_size", {"type": "boolean"})
    .add_input_property("undefined_edge", {"type": "string"})
    .add_input_property("second_curve", {"type": "integer"})
    .add_input_property("dimension", {"type": "string", "description": "e.g. 1:10"})
    .add_input_property("symbol", {"type": "string"})
    .add_input_property("theoretically_exact", {"type": "boolean"})
    .strict_schema()
)

item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline", rung="count",
        evidence_test="tests/unit/test_drawing_add_symbol.py::TestCountGate"
                      "::test_a_count_that_does_not_move_is_an_error"))


def register_tool():
    register(item)
