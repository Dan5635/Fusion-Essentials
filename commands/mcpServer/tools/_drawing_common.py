# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Shared substrate for the drawing (2D document) tool family."""

import json
import math
import re

import adsk.core
import adsk.drawing

from . import _common
from ._common import safe

MAP_BLURB = (
    "active_drawing(_document); SHEET_SIZE_MAP/DIMENSION_STRATEGIES/ORIENTATION_MEMBERS/"
    "NO_PORTRAIT; sheet_units/SHEET_EXTENT_UNIT/DOCUMENT_UNIT/coordinate_unit/"
    "extent_in_coordinates/coordinates_to_extent; enum_value/*_label; "
    "resolve_sheet/sheet_listing/sheet_facts/view_at; view_curve/typed_curve/curve_point/"
    "curve_row; listed/as_index/sheet_xy; palette_parts/palette_list; "
    "revision_rows - its row census"
)

# Sheet.width/height are MILLIMETRES on every drawing, ISO and ASME alike (an ASME B sheet, 17 x 11
# inches, reads 431.8 x 279.4). documentSettings.units - what sheet_units decodes - is the DIMENSION
# display unit and says nothing about those two numbers, so a payload labels them with THIS.
SHEET_EXTENT_UNIT = "mm"

# The (standard, sheet size) pairs Fusion refuses portrait on, in its own words. A raise inside a
# drawing document is not reliably rolled back, so both consumers pre-guard on this table.
NO_PORTRAIT = {("iso", "a0"), ("asme", "e")}

# sheet-size key -> (the standard the size belongs to, its SheetSizes member name). Fusion silently
# IGNORES a size belonging to the other standard at creation and RAISES on one assigned to a sheet.
# CustomSizeSheetSize is absent: it cannot be assigned to Sheet.sheetSize at all.
SHEET_SIZE_MAP = {
    "a4": ("iso", "A4ISOSheetSize"), "a3": ("iso", "A3ISOSheetSize"),
    "a2": ("iso", "A2ISOSheetSize"), "a1": ("iso", "A1ISOSheetSize"), "a0": ("iso", "A0ISOSheetSize"),
    "a": ("asme", "AASMESheetSize"), "b": ("asme", "BASMESheetSize"), "c": ("asme", "CASMESheetSize"),
    "d": ("asme", "DASMESheetSize"), "e": ("asme", "EASMESheetSize"),
}

# auto-dimension strategy key -> the DimensionStrategyTypes member name; the family carries exactly
# these eight members.
DIMENSION_STRATEGIES = {
    "overall": "OverallDimensionStrategyType",
    "automatic": "AutomaticDimensionStrategyType",
    "baseline": "BaselineDimensionStrategyType",
    "chain": "ChainDimensionStrategyType",
    "ordinate": "OrdinateDimensionStrategyType",
    "symmetric": "SymmetricDimensionStrategyType",
    "symmetric_with_baseline": "SymmetricWithBaselineDimensionStrategyType",
    "symmetric_with_ordinate": "SymmetricWithOrdinateDimensionStrategyType",
}


def active_drawing_document():
    """The active document cast to a DrawingDocument, or None when it is not a drawing - the level
    carrying documentReferences and updateAllReferences."""
    doc = safe(lambda: adsk.core.Application.get().activeDocument)
    return safe(lambda: adsk.drawing.DrawingDocument.cast(doc))


def active_drawing():
    """The active document's Drawing, or None when the active document is not a drawing."""
    dd = active_drawing_document()
    return safe(lambda: dd.drawing) if dd else None


def sheet_units(dwg):
    """The drawing's DIMENSION display unit - 'mm' or 'in' from its own documentSettings.units, None
    when unreadable (published as null, never a guessed default). NOT the unit Sheet.width/height
    come back in - see SHEET_EXTENT_UNIT."""
    units = safe(lambda: dwg.documentSettings.units)
    if units is None:
        return None
    mm = safe(lambda: adsk.drawing.DrawingUnitTypes.MillimeterDrawingUnitType)
    inch = safe(lambda: adsk.drawing.DrawingUnitTypes.InchDrawingUnitType)
    if mm is not None and units == mm:
        return "mm"
    if inch is not None and units == inch:
        return "in"
    return None


def enum_value(cls_name, member):
    """One adsk.drawing enum member's value by NAME - family and member both - or None when this
    Fusion build carries neither."""
    return safe(lambda: getattr(getattr(adsk.drawing, cls_name), member))


def standard_label(dwg):
    """'iso' or 'asme' from the drawing's own documentSettings.standard; None when unreadable.
    DrawingStandardTypes carries exactly these two members, and the standard is fixed at creation
    (documentSettings.standard has no setter)."""
    value = safe(lambda: dwg.documentSettings.standard)
    if value is None:
        return None
    for key, member in (("iso", "ISODrawingStandardType"), ("asme", "ASMEDrawingStandardType")):
        known = enum_value("DrawingStandardTypes", member)
        if known is not None and value == known:
            return key
    return None


# DrawingSketch coordinates follow the standard; custom sheet sizes follow display units.
# ISO coordinates are millimetres; ASME coordinates are inches.
DOCUMENT_UNIT = {"iso": "mm", "asme": "in"}


def coordinate_unit(dwg):
    """The length unit sheet COORDINATES land in - 'mm' under ISO, 'in' under ASME, None when the
    standard cannot be read. Keyed to the STANDARD, never to documentSettings.units: the two are set
    independently, so standard='iso' with units='inch' takes coordinates in millimetres while its
    dimensions display in inches, and labelling a coordinate with sheet_units is wrong by 25.4x."""
    return DOCUMENT_UNIT.get(standard_label(dwg))


def _length_unit(dwg, standard):
    """The coordinate length unit from a drawing or standard, or None when neither resolves."""
    return coordinate_unit(dwg) if dwg is not None else DOCUMENT_UNIT.get(standard)


def extent_in_coordinates(value, dwg=None, standard=None):
    """A Sheet.width/height number - SHEET_EXTENT_UNIT, always - in the unit COORDINATES land in.
    Pass dwg for a live drawing, or standard ('iso'/'asme') where none exists yet. None when the
    standard cannot be read - each adopter decides its own policy for that case."""
    unit = _length_unit(dwg, standard)
    if unit is None:
        return None
    if unit == SHEET_EXTENT_UNIT:
        return value
    return value * _common.scale(SHEET_EXTENT_UNIT) * _common.CM_TO_UNIT[unit]


def coordinates_to_extent(value, dwg=None, standard=None):
    """The inverse of extent_in_coordinates: a coordinate-unit number lifted into SHEET_EXTENT_UNIT
    (mm). Same dwg/standard contract, including the None-on-unread-standard return."""
    unit = _length_unit(dwg, standard)
    if unit is None:
        return None
    if unit == SHEET_EXTENT_UNIT:
        return value
    return value * _common.scale(unit) / _common.scale(SHEET_EXTENT_UNIT)


# orientation key -> SheetOrientationTypes member.
ORIENTATION_MEMBERS = {"landscape": "LandscapeSheetOrientationType",
                       "portrait": "PortraitSheetOrientationType"}


def size_label(value):
    """'a3' for the SheetSizes value a sheet reads back, or None for a value outside the preset
    table - CustomSizeSheetSize among them. A custom-sized sheet keeps its extents in width/height."""
    if value is None:
        return None
    for key, (_standard, member) in SHEET_SIZE_MAP.items():
        if value == enum_value("SheetSizes", member):
            return key
    return None


def orientation_label(value):
    """'landscape'/'portrait' for the SheetOrientationTypes value a sheet reads back, or None."""
    if value is None:
        return None
    for key, member in ORIENTATION_MEMBERS.items():
        if value == enum_value("SheetOrientationTypes", member):
            return key
    return None


# wire label -> ViewCurveTypes member, read by NAME; a value matching none labels None.
CURVE_TYPE_MEMBERS = {
    "line": "LineViewCurveType", "arc": "ArcViewCurveType", "circle": "CircleViewCurveType",
    "ellipse": "EllipseViewCurveType", "spline": "SplineViewCurveType",
    "polyline": "PolylineViewCurveType", "unknown": "UnknownViewCurveType",
}

# point key -> its ViewCurve accessor; midPoint reads null on a circle, centerPoint on a line.
CURVE_POINTS = {"start": "startPoint", "end": "endPoint", "mid": "midPoint",
                "center": "centerPoint"}


def curve_type_label(value):
    """'line'/'arc'/... for the ViewCurveTypes value a curve reads, or None."""
    if value is None:
        return None
    for key, member in CURVE_TYPE_MEMBERS.items():
        if value == enum_value("ViewCurveTypes", member):
            return key
    return None


def curve_point(curve, key):
    """The DrawingPoint a curve's `key` accessor reads, or None where it reads null."""
    return safe(lambda: getattr(curve, CURVE_POINTS[key]))


def point_xy(point):
    """[x, y] of a DrawingPoint in sheet coordinates at its view's scale, or None."""
    xy = safe(lambda: point.coordinate)
    x, y = _common.measured(lambda: xy.x, 1.0, 4), _common.measured(lambda: xy.y, 1.0, 4)
    return None if x is None or y is None else [x, y]


def curve_row(index, curve):
    """One ViewCurve as {index, type, start, end, mid, center}; a point that reads null is null."""
    row = {"index": index, "type": curve_type_label(safe(lambda: curve.type))}
    for key in CURVE_POINTS:
        row[key] = point_xy(curve_point(curve, key))
    return row


def view_curve(view, view_index, index, label):
    """(ViewCurve, error) for curve `index` of a view; a miss names the view's legal range."""
    remedy = f"drawing_get(include=['curves'], view={view_index}) lists them."
    if isinstance(index, bool) or not isinstance(index, int):
        return None, f"'{label}' must be an integer curve index (got {index!r}); {remedy}"
    curves = safe(lambda: view.viewCurves)
    count = _common.counted(lambda: curves.count)
    if count is None:
        return None, f"'{label}': the viewCurves of view {view_index} did not read."
    if not 0 <= index < count:
        span = f"0 to {count - 1}" if count else "none"
        return None, (f"'{label}' curve {index} is out of range: view {view_index} has {count} "
                      f"curve(s) ({span}); {remedy}")
    curve = safe(lambda: curves.item(index))
    if curve is None:
        return None, f"'{label}': curve {index} of view {view_index} did not read; {remedy}"
    return curve, None


def typed_curve(act, view, idx, raw, label, kinds):
    """(the ViewCurve at index `raw`, error) - refused before any add unless its type is in kinds."""
    found, err = view_curve(view, idx, raw, label)
    if err:
        return None, err
    kind = curve_type_label(safe(lambda: found.type))
    if kind not in kinds:
        return None, (f"'{label}' curve {raw} reads as {kind or 'an unread type'}; "
                      f"action='{act}' takes {' or '.join(kinds)} curves - "
                      f"drawing_get(include=['curves'], view={idx}) lists each curve's type.")
    return found, None


def listed(raw):
    """A list as given, or the list a JSON string spells - a stale client schema sends one."""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return raw
        return parsed if isinstance(parsed, list) else raw
    return raw


def as_index(raw):
    """An index as given, or the int a digit string spells - a stale client schema sends one."""
    if not isinstance(raw, str):
        return raw
    from . import _inputs      # _inputs imports this module, so the import waits for the call
    number = _inputs._ascii_int(raw)
    return raw if number is None else number


def sheet_xy(raw, act, unit, name):
    """([x, y], error) - input `name` as two finite numbers in the drawing's coordinate unit."""
    raw = listed(raw)
    pair = list(raw) if isinstance(raw, (list, tuple)) else []
    if len(pair) != 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                 and math.isfinite(v) for v in pair):
        where = f"sheet {unit}" if unit else "the sheet's coordinate unit"
        return None, (f"action='{act}' needs '{name}' as [x, y] in {where} - the "
                      f"curve_unit drawing_get(include=['curves']) reports (got {raw!r}).")
    return [float(pair[0]), float(pair[1])], None


def view_at(sheet, view):
    """(View, index, error) for a 0-based view index of `sheet`; a bool or non-integer is refused."""
    views = safe(lambda: sheet.views)
    count = _common.counted(lambda: views.count)
    name = safe(lambda: sheet.name)
    if count is None:
        return None, None, f"The views of sheet '{name}' did not read."
    if count == 0:
        return None, None, (f"Sheet '{name}' has no views; drawing_create or the Fusion UI makes "
                            "them - the API cannot add one.")
    if view is None:
        return None, None, (f"Provide 'view' - a view index, 0 to {count - 1} on sheet '{name}' "
                            f"({count} views).")
    idx = as_index(view)
    if isinstance(idx, bool) or not isinstance(idx, int):
        return None, None, (f"'view' must be an integer view index, 0 to {count - 1} on sheet "
                            f"'{name}' (got {view!r}).")
    if not 0 <= idx < count:
        return None, None, (f"'view' index {idx} is out of range: sheet '{name}' has {count} "
                            f"view(s), so the legal indices are 0 to {count - 1}.")
    target = safe(lambda: views.item(idx))
    if target is None:
        return None, None, f"View index {idx} could not be read off sheet '{name}'."
    return target, idx, None


# palette token -> SymbolPaletteTypes member: the member name less its suffix in snake_case, or a
# short alias. The None member appends nothing; the API doc marks centerline, position and
# counterbore unsupported.
_PALETTE_NAMES = (
    "Diameter", "PlusMinus", "Degree", "Square", "Countersink", "Depth", "CircularSection",
    "CircularProjection", "NotEqual", "LowerDelta", "Section", "UpperLambda", "LowerLambda",
    "Delta", "Omega", "Number", "Squared", "Cubed", "OneQuarter", "OneHalf", "ThreeQuarters",
    "EnvelopeRequirement", "FreeStateCondition", "LeastMaterialRequirement",
    "MaximumMaterialRequirement", "ProjectedToleranceZone", "Between", "CommonZone",
    "MinorDiameter", "MajorDiameter", "PitchDiameter", "LineElement", "NotConvex",
    "AnyCrossSection", "MedianFeature", "FromTo", "UnequallyDisposedToleranceZone",
    "AnyLongitudinalSection", "ContactingFeature", "VariableDistance", "Point", "StraightLine",
    "Plane", "ForOrientationConstraintOnly", "UnequallyDisposedProfile", "NumberOfRow",
    "NoModifier", "AllAround", "AllOver", "TransmissionBand",
)
PALETTE_ALIASES = {
    "dia": "Diameter", "M": "MaximumMaterialRequirement", "L": "LeastMaterialRequirement",
    "P": "ProjectedToleranceZone", "F": "FreeStateCondition", "E": "EnvelopeRequirement",
    "U": "UnequallyDisposedProfile", "pm": "PlusMinus", "deg": "Degree", "sq": "Square",
    "csk": "Countersink",
}
PALETTE_TOKENS = {**{re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower(): name + "SymbolPaletteType"
                     for name in _PALETTE_NAMES},
                  **{alias: name + "SymbolPaletteType" for alias, name in PALETTE_ALIASES.items()}}
PALETTE_UNSUPPORTED = ("centerline", "position", "counterbore")
_PALETTE_SHORT = (*PALETTE_ALIASES, "depth", "all_around", "all_over", "between", "common_zone")
_PALETTE_TOKEN = re.compile(r"\{([^{}]*)\}")


def symbol_text(raw, label):
    """(text, error) - a symbol text field as given; the API doc says a ';' breaks the create."""
    if not isinstance(raw, str):
        return None, f"'{label}' must be text (got {raw!r})."
    if ";" in raw:
        return None, (f"'{label}' holds a ';' ({raw!r}), which Fusion's symbol API cannot carry - "
                      "drop it.")
    return raw, None


def palette_parts(raw, label):
    """([('symbol', SymbolPaletteTypes value) or ('text', str), ...], error) for '{token}' text."""
    text, err = symbol_text(raw, label)
    if err:
        return None, err
    parts, at = [], 0
    for match in list(_PALETTE_TOKEN.finditer(text)) + [None]:
        plain = text[at:match.start() if match else len(text)]
        if "{" in plain or "}" in plain:
            return None, (f"'{label}' has an unmatched brace in {text!r}; a symbol is written as "
                          "{token}, such as {diameter}.")
        if plain:
            parts.append(("text", plain))
        if match is None:
            return parts, None
        token, at = match.group(1).strip(), match.end()
        if token.lower() in PALETTE_UNSUPPORTED:
            listed = ", ".join("{%s}" % t for t in PALETTE_UNSUPPORTED)
            return None, (f"'{label}': Fusion's symbol API does not support {listed} "
                          f"(got {{{token}}}).")
        member = PALETTE_TOKENS.get(token) or PALETTE_TOKENS.get(token.lower())
        if member is None:
            short = " ".join("{%s}" % t for t in _PALETTE_SHORT)
            return None, (f"'{label}': {{{token}}} is no symbol token. Use {short} or a "
                          "SymbolPaletteTypes member name in snake_case, such as "
                          "{least_material_requirement}.")
        value = enum_value("SymbolPaletteTypes", member)
        if value is None:
            return None, f"'{label}': {{{token}}} is not available on this Fusion version."
        parts.append(("symbol", value))


def palette_list(prop, parts):
    """`prop` (a SymbolPaletteList) cleared and rebuilt from palette_parts, to assign back."""
    prop.clear()
    for kind, value in parts:
        if kind == "symbol":
            prop.append(value)
        else:
            prop.appendText(value)
    return prop


def sheet_listing(dwg):
    """The drawing's sheets in collection order with a 1-based collection index."""
    sheets = safe(lambda: dwg.sheets)
    return [{"collection_index": i + 1, "export_index": None,
             "name": safe(lambda i=i: sheets.item(i).name)}
            for i in range(safe(lambda: sheets.count, 0) or 0)]


def sheet_facts(sheet):
    """One sheet's readable state; width/height are read-only, in SHEET_EXTENT_UNIT. Sheet.tidyUp is
    NOT read here - it is a property whose READ tidies the sheet."""
    size = safe(lambda: sheet.sheetSize)
    orientation = safe(lambda: sheet.orientation)
    return {
        "name": safe(lambda: sheet.name),
        "sheet_size": size_label(size),
        "orientation": orientation_label(orientation),
        "width": _common.measured(lambda: sheet.width, 1.0, 3),
        "height": _common.measured(lambda: sheet.height, 1.0, 3),
        "width_height_unit": SHEET_EXTENT_UNIT,
        "views": _common.counted(lambda: sheet.views.count),
        "sketches": _common.counted(lambda: sheet.sketches.count),
        "custom_tables": _common.counted(lambda: sheet.customTables.count),
        "bend_tables": _common.counted(lambda: sheet.bendTables.count),
    }


def resolve_sheet(dwg, name):
    """(sheet, error_text) for a sheet name, case-insensitive EXACT match; ''/None means the ACTIVE
    sheet and a miss lists the available names. Sheet names are case-insensitively unique (a
    duplicate Sheets.add raises, a duplicate or case-variant rename silently no-ops), so the
    several-match refusal below is an invariant guard, not an expected path."""
    if not name:
        active = safe(lambda: dwg.activeSheet)
        if active is None:
            return None, "No sheet: the drawing reports no active sheet."
        return active, None
    sheets = safe(lambda: dwg.sheets)
    names = []
    hits = []
    for s in _common.iter_collection(sheets):
        n = safe(lambda: s.name) or ""
        names.append(n)
        if n.lower() == str(name).lower():
            hits.append((s, n))
    if not hits:
        return None, ("No sheet named '%s'. Available sheets: %s." % (name, ", ".join(names) or "none"))
    if len(hits) > 1:
        return None, ("Sheet name '%s' matches %d sheets (%s) - address one exactly."
                      % (name, len(hits), ", ".join(n for _, n in hits)))
    return hits[0][0], None


_REVISION_FIELDS = ("rev", "description", "date", "approved", "zone", "sht")


def revision_rows(table):
    """The revision census read as a sequence: each row's own .index, its texts, isVisible; None if unreadable."""
    seq = safe(lambda: list(table.revisionTableRows))
    if seq is None:
        return None
    out = []
    for r in seq:
        row = {"index": safe(lambda r=r: r.index), "visible": _common.read_flag(lambda r=r: r.isVisible)}
        for field in _REVISION_FIELDS:
            row[field] = safe(lambda r=r, f=field: getattr(r, f))
        out.append(row)
    return out
