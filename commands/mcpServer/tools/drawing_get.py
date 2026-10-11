# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Read the ACTIVE 2D drawing document by zoom level - the drawing family's one read tool.
Scripts are a poor fallback here: a sys_execute_script that references a DrawingDocument's
.products collection dies at the executeTextCommand level (measured; app.activeProduct is the
one measured-safe script route in), so this typed read is the reliable read path."""

import re

import adsk.core
import adsk.drawing

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item
from ..mcp_primitives.registry import register
from ._common import error, ok, safe
from . import _common
from . import _data_read
from . import _drawing_common
from . import _inputs
from . import _pdf_text

app = adsk.core.Application.get()

# ViewTypes value -> wire label. The family's own vocabulary; an unknown/unreadable value
# publishes null rather than a guessed type.
_VIEW_TYPE_MEMBERS = {
    "base": "BaseViewType",
    "projected": "ProjectedViewType",
    "section": "SectionViewType",
    "detail": "DetailViewType",
    "auxiliary": "AuxiliaryViewType",
    "flat_pattern": "FlatPatternViewType",
}


def _view_type_label(value):
    if value is None:
        return None
    for key, member in _VIEW_TYPE_MEMBERS.items():
        if value == _drawing_common.enum_value("ViewTypes", member):
            return key
    return None


def _custom_size_facts(sheet):
    """The sheet's customSize record when the build exposes it - {width, height, unit} in the
    drawing's own coordinate unit - or None. Read defensively: an earlier build RAISED on this
    property (the repo's measured note), the current API doc declares it gettable, so the read
    is trusted only when it answers."""
    cs = safe(lambda: sheet.customSize)
    if cs is None:
        return None
    w = _common.measured(lambda: cs.width, 1.0, 3)
    h = _common.measured(lambda: cs.height, 1.0, 3)
    if w is None or h is None:
        return None
    return {"width": w, "height": h}


def _curve_rows(view, cap):
    """(rows, truncated) - a view's curves as _drawing_common.curve_row records, or (None, False)."""
    curves = safe(lambda: view.viewCurves)
    count = _common.counted(lambda: curves.count)
    if count is None:
        return None, False
    rows = [_drawing_common.curve_row(i, safe(lambda i=i: curves.item(i)))
            for i in range(min(count, cap))]
    return rows, count > cap


def _views_rows(sheet, cap, only=None, with_curves=False):
    """(rows, truncated) - {index, type} per view or for view `only`, with its curves if asked."""
    views = safe(lambda: sheet.views)
    count = _common.counted(lambda: views.count)
    if count is None:
        return None, False
    rows = []
    for i in ([only] if only is not None else range(min(count, cap))):
        v = safe(lambda i=i: views.item(i))
        row = {"index": i, "type": _view_type_label(safe(lambda: v.type)) if v else None}
        if with_curves:
            row["curves"], truncated = _curve_rows(v, _MAX_CURVES_PER_VIEW)
            if truncated:
                row["curves_truncated"] = True
        rows.append(row)
    return rows, only is None and count > cap


def _table_row(table, row_cap, col_cap):
    """One custom table's name (if any), row/column counts, and its cell text capped at a small
    grid - adsk.drawing has no parts-list/balloon class, so this table is the nearest readable
    BOM-like content a sheet carries."""
    name = safe(lambda: table.name)
    rows = _common.counted(lambda: table.rowCount)
    cols = _common.counted(lambda: table.columnCount)
    out = {"name": name, "row_count": rows, "column_count": cols}
    if rows and cols:
        r_cap, c_cap = min(rows, row_cap), min(cols, col_cap)
        out["cells"] = [[safe(lambda r=r, c=c: table.getCellData(r, c)) for c in range(c_cap)]
                        for r in range(r_cap)]
        if rows > r_cap or cols > c_cap:
            out["cells_truncated"] = True
    return out


def _tables_rows(sheet, cap, row_cap, col_cap):
    """(rows, truncated) - one sheet's custom tables, or (None, False) when unreadable."""
    tables = safe(lambda: sheet.customTables)
    count = _common.counted(lambda: tables.count) if tables is not None else None
    if count is None:
        return None, False
    rows = []
    for i in range(min(count, cap)):
        t = safe(lambda i=i: tables.item(i))
        if t is not None:
            rows.append(_table_row(t, row_cap, col_cap))
    return rows, count > cap


_MAX_VIEWS_PER_SHEET = 50
_MAX_CURVES_PER_VIEW = 60
_MAX_TABLES_PER_SHEET = 20
_MAX_TABLE_ROWS = 20
_MAX_TABLE_COLS = 20

_MAX_TEXT_PER_SHEET = 200
_MAX_LABELS_LISTED = 5
# a PDF page box is whole points, so a page matches its sheet's size to within this
_PAGE_SIZE_TOLERANCE_MM = 0.5

_SLICES = ("views", "curves", "tables", "revisions", "text")

# a page label of a drawing_export PDF: the page's position in brackets, then its sheet's name
_PAGE_LABEL = re.compile(r"\[\d+\] (.*)", re.S)


def _sheet_pages(dwg, path):
    """({lowered sheet name: the PDF pages labelled with it}, the file's facts, error)."""
    doc, err = _pdf_text.read(path)
    if err:
        return None, None, err
    names = {(row["name"] or "").lower() for row in _drawing_common.sheet_listing(dwg)} - {""}
    found = {}
    for page in doc["pages"]:
        named = _PAGE_LABEL.fullmatch(page["label"] or "")
        if named and named.group(1).lower() in names:
            found.setdefault(named.group(1).lower(), []).append(page)
    if not found:
        labels = [repr(page["label"]) for page in doc["pages"]]
        more = " ..." if len(labels) > _MAX_LABELS_LISTED else ""
        return None, None, (
            f"No page of '{path}' is labelled with a sheet of this drawing: its {len(labels)} "
            f"page label(s) read {', '.join(labels[:_MAX_LABELS_LISTED])}{more}. Export this "
            "drawing (drawing_export format='pdf') and pass that file.")
    return found, {"file": path, "modified_utc": _data_read._epoch_iso(doc["modified"]),
                   "page_count": doc["page_count"]}, None


def _sheet_page(facts, pages):
    """(the one page carrying a sheet's name AND its size, why there is none) - one is None."""
    if not pages:
        return None, "no page is labelled with this sheet's name"
    if len(pages) > 1:
        return None, f"{len(pages)} pages are labelled with this sheet's name"
    page, size = pages[0], (facts.get("width"), facts.get("height"))
    if None in size:
        return None, "the sheet's size did not read, so its page could not be checked"
    if any(abs(got - want) > _PAGE_SIZE_TOLERANCE_MM
           for got, want in zip((page["width"], page["height"]), size)):
        return None, (f"page {page['page']} carries this sheet's name but is {page['width']} x "
                      f"{page['height']} mm; the sheet reads {size[0]} x {size[1]} mm")
    return page, None


def _text_facts(facts, pages, layer, unit):
    """Fold a sheet's one matched PDF page into its row: pdf_page, text_layers and text rows."""
    page, why = _sheet_page(facts, pages)
    facts["pdf_page"] = page["page"] if page else None
    facts["text"] = None
    if page is None:
        facts["pdf_page_reason"] = why
        return
    census = {}
    for run in page["runs"]:
        census[run["layer"]] = census.get(run["layer"], 0) + 1
    facts["text_layers"] = [{"layer": name, "count": n} for name, n in census.items()]
    kept = [run for run in page["runs"]
            if not layer or (run["layer"] or "").lower() == layer.lower()]
    to_unit = _common.scale(_drawing_common.SHEET_EXTENT_UNIT) * _common.CM_TO_UNIT[unit]
    facts["text"] = [{"text": run["text"],
                      "at": [round(run["x"] * to_unit, 3), round(run["y"] * to_unit, 3)],
                      "angle": run["angle"], "layer": run["layer"]}
                     for run in kept[:_MAX_TEXT_PER_SHEET]]
    if len(kept) > _MAX_TEXT_PER_SHEET:
        facts["text_truncated"] = True
    facts["text_unit"] = unit


def handler(include=None, sheet: str = "", view: int = None, pdf: str = "",
            layer: str = "") -> dict:
    # include accepts a list or a comma-string, like the family's other rich reads.
    if isinstance(include, str):
        raw = [p.strip().lower() for p in include.split(",") if p.strip()]
    else:
        raw = [str(x).strip().lower() for x in (include or [])]
    bad = [x for x in raw if x not in _SLICES]
    if bad:
        return error(f"Unknown include value(s): {', '.join(bad)}. "
                     f"This read offers: {', '.join(_SLICES)}.")
    want_views = "views" in raw
    want_curves = "curves" in raw
    want_tables = "tables" in raw
    want_revisions = "revisions" in raw
    want_text = "text" in raw
    if view is not None:
        # a client holding a stale schema sends a new integer input as a digit string
        index = (_inputs._ascii_int(view) if isinstance(view, str)
                 else view if type(view) is int and view >= 0 else None)
        if index is None:
            return error(f"'view' must be a 0-based view index (got {view!r}).")
        view = index
        if not (want_views or want_curves):
            return error(f"'view'={view} scopes include=['views'] or ['curves'] - add one.")
    pdf, layer = (pdf or "").strip().strip('"'), (layer or "").strip()
    if (pdf or layer) and not want_text:
        return error(f"'{'pdf' if pdf else 'layer'}' scopes include=['text'] - add it.")
    if want_text and not pdf:
        return error("include=['text'] reads sheet text off an exported PDF: pass pdf= the "
                     "file_path drawing_export(format='pdf') returned.")

    dd = _drawing_common.active_drawing_document()
    dwg = safe(lambda: dd.drawing) if dd is not None else None
    if dwg is None:
        return error("The active document is not a 2D drawing. Activate the drawing document "
                     "first (doc_activate), then read it.")

    current_app = adsk.core.Application.get()
    doc_name = safe(lambda: dd.name)
    standard = _drawing_common.standard_label(dwg)
    sheets = safe(lambda: dwg.sheets)
    sheet_count = _common.counted(lambda: sheets.count)
    # ONE activeSheet read for the whole payload: the property can return DIFFERENT sheets across
    # close-together reads, so one read is what makes active_sheet and every is_active flag a
    # consistent snapshot.
    active_name = safe(lambda: dwg.activeSheet.name)
    payload = {
        "drawing": doc_name,
        "standard": standard,
        "dimension_display_unit": _drawing_common.sheet_units(dwg),
        "coordinate_unit": _drawing_common.coordinate_unit(dwg),
        "sheet_count": sheet_count,
        "active_sheet": active_name,
        "is_modified": _common.read_flag(lambda: dd.isModified),
        "active_command_id": safe(lambda: current_app.userInterface.activeCommand),
    }

    if sheet:
        if sheet_count is None:
            return error(f"The drawing's sheet count could not be read, so sheet name '{sheet}' "
                         "cannot be resolved. Retry drawing_get after the drawing finishes updating.")
        target, serr = _drawing_common.resolve_sheet(dwg, sheet)
        if serr:
            return error(serr)
        sheets_to_read = [(None, target)]
    elif sheet_count is None:
        sheets_to_read = None
    else:
        sheets_to_read = [(i, safe(lambda i=i: sheets.item(i))) for i in range(sheet_count)]

    pages = None
    if want_text:
        pages, payload["pdf"], perr = _sheet_pages(dwg, pdf)
        if perr:
            return error(perr)
        text_unit = payload["coordinate_unit"] or _drawing_common.SHEET_EXTENT_UNIT

    rows = None if sheets_to_read is None else []
    for idx, s in sheets_to_read or []:
        if s is None:
            rows.append(None)
            continue
        facts = _drawing_common.sheet_facts(s)
        if idx is not None:
            facts["collection_index"] = idx + 1
            facts["export_index"] = None
        sheet_name = facts.get("name")
        facts["is_active"] = (None if active_name is None or sheet_name is None
                              else active_name == sheet_name)
        custom = _custom_size_facts(s)
        if custom is not None and facts.get("sheet_size") is None:
            facts["custom_size"] = dict(custom, unit=_drawing_common.coordinate_unit(dwg))
        facts["dimension_count"] = _common.counted(lambda: s.drawingDimensions.count)
        # On a clean drawing, this native count read marks the document modified.
        facts["symbol_count"] = (_common.counted(lambda: s.drawingSymbols.count)
                                 if payload["is_modified"] is True else None)
        if want_views or want_curves:
            n = facts.get("views")
            if view is not None and n is not None and view >= n:
                span = f" (0 to {n - 1})" if n else ""
                return error(f"'view'={view} is out of range on sheet '{sheet_name}', which has "
                             f"{n} view(s){span}; pass sheet= to read one sheet.")
            vrows, truncated = _views_rows(s, _MAX_VIEWS_PER_SHEET, view, want_curves)
            facts["view_rows"] = vrows
            if truncated:
                facts["view_rows_truncated"] = True
            if want_curves:
                facts["curve_unit"] = _drawing_common.coordinate_unit(dwg)
        if want_tables:
            trows, ttrunc = _tables_rows(s, _MAX_TABLES_PER_SHEET, _MAX_TABLE_ROWS, _MAX_TABLE_COLS)
            facts["tables"] = trows
            if ttrunc:
                facts["tables_truncated"] = True
        if want_revisions:
            try:
                table = s.getRevisionTable()
            except Exception:
                facts["revisions"], facts["revision_count"] = None, None
            else:
                if table is None:
                    facts["revisions"], facts["revision_count"] = [], 0
                else:
                    rev_rows = _drawing_common.revision_rows(table)
                    if rev_rows is None:
                        facts["revisions"], facts["revision_count"] = None, None
                    else:
                        facts["revision_count"] = len(rev_rows)
                        facts["revisions"] = rev_rows[:_MAX_TABLE_ROWS]
                        if len(rev_rows) > _MAX_TABLE_ROWS:
                            facts["revisions_truncated"] = True
        if want_text:
            _text_facts(facts, pages.get((sheet_name or "").lower()), layer, text_unit)
        rows.append(facts)
    payload["sheets"] = rows
    paged = [row for row in rows or [] if row and row.get("pdf_page")]
    if layer and paged and not any(row["text"] for row in paged):
        seen = sorted({c["layer"] for row in paged for c in row["text_layers"] if c["layer"]})
        return error(f"No text on layer '{layer}' for the sheet(s) read; their text in this PDF "
                     f"sits on: {', '.join(seen) or 'no named layer'}.")

    payload["note"] = (
        "collection_index is 1-based; export_index is unknown - the PDF shows page order. "
        "Width/height are mm. include= adds views/curves (view=N scopes one)/tables/revisions/"
        "text. Dimension values, symbol text, parts lists and balloons read as text: "
        "include=['text'] with pdf= a drawing_export PDF. View scales do not read. "
        "revisions rows, title and header included, carry drawing_edit_revisions' indexes.")
    if want_text:
        payload["note"] += (
            " text rows are the pdf file's text runs as exported: export again after an edit. A "
            "page is matched to a sheet by name and size only, so a PDF of another drawing with "
            "the same sheet names and sizes reads the same. at is where a run starts, in "
            "text_unit from the page's lower-left corner; layer is its PDF layer (layer= keeps "
            "one). pdf_page_reason says why a sheet has no page.")
    if payload["is_modified"] is not True:
        payload["note"] += (" symbol_count is null: its native count read can mark a clean "
                            "drawing modified. Check the exported PDF for symbols.")
    if payload["is_modified"] is False and _common.read_flag(lambda: dd.isModified) is True:
        payload["modified_by_read"] = True
        payload["note"] += (" isModified read false before this read and true after it; this read "
                            "requested no edit.")
    return ok(payload)


TOOL_DESCRIPTION = (
    "Read the ACTIVE 2D drawing: standard, units and per-sheet facts."
)

tool = (
    Tool.create_simple(name="drawing_get", description=TOOL_DESCRIPTION)
    .add_input_property("include", {"type": "array",
            "items": {"type": "string", "enum": list(_SLICES)}})
    .add_input_property("sheet", {"type": "string",
            "description": "Sheet name; omit for all."})
    .add_input_property("view", {"type": "integer",
            "description": "0-based; scopes views/curves."})
    .add_input_property("pdf", {"type": "string",
            "description": "drawing_export PDF path; text reads it."})
    .add_input_property("layer", {"type": "string",
            "description": "Keeps text on one PDF layer."})
    .strict_schema()
)
item = Item.create_tool_item(tool=tool, write="read", handler=handler, run_on_main_thread=True)


def register_tool():
    register(item)
