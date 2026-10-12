"""Unit tests for ``drawing_get`` - the drawing family's ONE read tool.

What is pinned: the not-a-drawing refusal, the sheet rows (1-based collection_index, is_active,
width/height in mm, the placed-dimension count), the custom-size disclosure (sheet_size null +
custom_size only when the build's customSize property answers), the per-view rows, each view's
curve points and their cap, the one-view scope, and the include/scope plumbing.
"""

import datetime
import os
import time
import types

import pytest

import live_api_facts
from conftest import (FakeCustomSheetSize, FakeSheet, FakeView, FakeViews, _CustomTable,
                      _RevisionRow, _RevisionTable, export_pdf, load_tool, make_drawing,
                      make_drawing_session, payload)

dg = load_tool("drawing_get")

# The API-declared ViewCurveTypes members; live_api_facts carries them once the enum sweep
# measures the family.
_CURVE_TYPES = live_api_facts.ENUMS.get("drawing.ViewCurveTypes") or dict(zip(
    ("LineViewCurveType", "ArcViewCurveType", "CircleViewCurveType", "EllipseViewCurveType",
     "SplineViewCurveType", "PolylineViewCurveType", "UnknownViewCurveType"), range(7)))


class _Point:
    """A DrawingPoint whose coordinate is the pair given; DrawingPoint carries no shape dump."""

    def __init__(self, x, y):
        self.coordinate = types.SimpleNamespace(x=x, y=y)


class _Curve:
    """A ViewCurve: a type and four accessors, None where live reads null; no shape dump."""

    def __init__(self, type_value, start, end, mid=None, center=None):
        self.type = type_value
        self.startPoint, self.endPoint = _Point(*start), _Point(*end)
        self.midPoint = _Point(*mid) if mid else None
        self.centerPoint = _Point(*center) if center else None

_SIZES = live_api_facts.ENUMS["drawing.SheetSizes"]
_ORIENTATIONS = live_api_facts.ENUMS["drawing.SheetOrientationTypes"]
_VIEW_TYPES = live_api_facts.ENUMS.get("drawing.ViewTypes", {})
_A3 = _SIZES["A3ISOSheetSize"]
_CUSTOM = _SIZES["CustomSizeSheetSize"]
_LAND = _ORIENTATIONS["LandscapeSheetOrientationType"]


def _sheet(name, size=_A3, width=420.0, height=297.0, **knobs):
    """One A3 landscape sheet at this file's defaults - the extents a payload row reports in mm."""
    return FakeSheet(name, size=size, orientation=_LAND, width=width, height=height, **knobs)


class _UnreadCount:
    @property
    def count(self):
        raise RuntimeError("collection count unavailable")


@pytest.fixture
def install(monkeypatch):
    def _install(sheets, active=0, doc_name="P6-Vise Drawing", **drawing):
        document = make_drawing(sheets=sheets, active=active, name=doc_name, **drawing)
        make_drawing_session(monkeypatch, document,
                             ViewCurveTypes=types.SimpleNamespace(**_CURVE_TYPES))
        return document.drawing
    return _install


class TestOrientationRead:
    def test_a_non_drawing_document_is_refused_pointing_at_doc_activate(self, monkeypatch):
        make_drawing_session(monkeypatch, object())
        res = dg.handler()
        assert res["isError"] is True
        assert "not a 2D drawing" in res["message"] and "doc_activate" in res["message"]

    def test_the_default_read_reports_standard_units_and_sheets(self, install):
        install([_sheet("Cover"), _sheet("Detail")])
        out = payload(dg.handler())
        assert out["drawing"] == "P6-Vise Drawing"
        assert out["standard"] == "iso"
        assert out["dimension_display_unit"] == "mm"
        assert out["coordinate_unit"] == "mm"
        assert out["sheet_count"] == 2
        assert out["active_sheet"] == "Cover"

    def test_sheet_rows_carry_collection_position_and_unknown_export_order(self, install):
        install([_sheet("Cover"), _sheet("Detail")], active=1)
        rows = payload(dg.handler())["sheets"]
        assert [r["collection_index"] for r in rows] == [1, 2]
        assert [r["export_index"] for r in rows] == [None, None]
        assert [r["is_active"] for r in rows] == [False, True]
        assert rows[0]["width"] == 420.0 and rows[0]["width_height_unit"] == "mm"

    @pytest.mark.parametrize("start,flips,expected", [
        (False, True, True), (False, False, None), (True, True, None)])
    def test_a_read_that_leaves_a_clean_document_modified_says_so(self, install, start, flips,
                                                                  expected):
        sheet = _sheet("S")
        drawing = install([sheet], is_modified=start)

        def revision_read():
            if flips:
                drawing.parentDocument.isModified = True
            return None
        sheet.getRevisionTable = revision_read
        out = payload(dg.handler(include=["revisions"]))
        assert out["is_modified"] is start
        assert out.get("modified_by_read") is expected
        assert ("read false before this read" in out["note"]) is bool(expected)

    def test_unread_modified_state_remains_null(self, install):
        install([_sheet("Cover")], modified_raises="modified unavailable")
        assert payload(dg.handler())["is_modified"] is None

    def test_unread_active_sheet_name_keeps_is_active_unknown(self, install):
        drawing = install([_sheet("Cover")])

        class _UnreadActiveSheet:
            @property
            def name(self):
                raise RuntimeError("active sheet unavailable")

        drawing.activeSheet = _UnreadActiveSheet()
        row = payload(dg.handler())["sheets"][0]
        assert row["is_active"] is None

    def test_active_command_id_is_observational_and_null_when_unreadable(self, install):
        install([_sheet("Cover")])
        session = dg.adsk.core.Application.get()
        session.userInterface = type("UI", (), {"activeCommand": "FusionAutoDimensionCmd"})()
        assert payload(dg.handler())["active_command_id"] == "FusionAutoDimensionCmd"

        class _UnreadCommand:
            @property
            def activeCommand(self):
                raise RuntimeError("active command unavailable")

        session.userInterface = _UnreadCommand()
        assert payload(dg.handler())["active_command_id"] is None

    def test_unread_sheet_count_does_not_publish_an_empty_listing(self, install):
        drawing = install([_sheet("Cover")])
        drawing.sheets = _UnreadCount()
        out = payload(dg.handler())
        assert out["sheet_count"] is None
        assert out["sheets"] is None

    def test_unread_per_sheet_counts_and_view_rows_remain_null(self, install):
        sheet = _sheet("Cover")
        sheet.views = sheet.sketches = sheet.customTables = _UnreadCount()
        install([sheet])
        row = payload(dg.handler(include=["views"]))["sheets"][0]
        assert row["views"] is None
        assert row["sketches"] is None
        assert row["custom_tables"] is None
        assert row["view_rows"] is None

    def test_dimension_count_reads_the_sheet_collection_and_null_without_it(self, install):
        counted, bare = _sheet("Counted"), _sheet("Bare")
        counted.drawingDimensions = types.SimpleNamespace(count=3)
        install([counted, bare])
        rows = payload(dg.handler())["sheets"]
        assert [r["dimension_count"] for r in rows] == [3, None]

    def test_symbol_count_reads_the_sheet_collection_and_null_without_it(self, install):
        counted, bare, unread = _sheet("Counted"), _sheet("Bare"), _sheet("Unread")
        counted.drawingSymbols = types.SimpleNamespace(count=2)
        unread.drawingSymbols = _UnreadCount()
        install([counted, bare, unread], is_modified=True)
        out = payload(dg.handler())
        assert [r["symbol_count"] for r in out["sheets"]] == [2, None, None]

    def test_clean_drawing_does_not_read_mutating_symbol_count(self, install):
        sheet = _sheet("Clean")
        drawing = install([sheet], is_modified=False)

        class DirtyingCount:
            @property
            def count(self):
                drawing.parentDocument.isModified = True
                return 2

        sheet.drawingSymbols = DirtyingCount()
        out = payload(dg.handler())
        assert out["sheets"][0]["symbol_count"] is None
        assert drawing.parentDocument.isModified is False
        assert out.get("modified_by_read") is None
        assert "Check the exported PDF for symbols" in out["note"]

    def test_the_read_never_touches_the_mutating_tidyup_property(self, install):
        # reading Sheet.tidyUp TIDIES the sheet, so a READ tool that touched it would mutate the
        # document it claims only to describe
        drawing = install([_sheet("Cover"), _sheet("Detail")])
        payload(dg.handler(include=["views"]))
        assert [s._tidy_reads for s in drawing.sheets._items] == [0, 0]

    def test_a_custom_sheet_reads_null_size_and_its_custom_extents(self, install):
        install([_sheet("Big", size=_CUSTOM, width=320.0, height=200.0,
                        custom_size=FakeCustomSheetSize(320.0, 200.0))])
        row = payload(dg.handler())["sheets"][0]
        assert row["sheet_size"] is None
        assert row["custom_size"] == {"width": 320.0, "height": 200.0, "unit": "mm"}

    @pytest.mark.parametrize("units,expected", [("mm", "mm"), ("in", "in"), ("unreadable", None)])
    def test_custom_size_uses_display_units_without_changing_coordinate_units(self, install,
                                                                             units, expected):
        width, height = (20.0, 10.0) if expected == "in" else (508.0, 254.0)
        install([_sheet("Custom", size=_CUSTOM, width=508.0, height=254.0,
                        custom_size=FakeCustomSheetSize(width, height))],
                standard="asme", units=units)
        out = payload(dg.handler())
        row = out["sheets"][0]
        assert row["custom_size"] == {"width": width, "height": height, "unit": expected}
        assert out["dimension_display_unit"] == expected
        assert out["coordinate_unit"] == "in"
        assert (row["width"], row["height"], row["width_height_unit"]) == (508.0, 254.0, "mm")

    def test_a_build_whose_customSize_raises_omits_the_key(self, install):
        install([_sheet("Old", size=_CUSTOM,
                        custom_size_raises="customSize is not readable on this build")])
        row = payload(dg.handler())["sheets"][0]
        assert row["sheet_size"] is None
        assert "custom_size" not in row

    def test_a_preset_sheet_never_carries_custom_size(self, install):
        # customSize answers on preset sheets too (the API doc says so) - publishing it there
        # would double-report the extents width/height already carry.
        install([_sheet("Std", custom_size=FakeCustomSheetSize(420.0, 297.0))])
        row = payload(dg.handler())["sheets"][0]
        assert row["sheet_size"] == "a3"
        assert "custom_size" not in row

    def test_the_images_key_is_never_published_because_images_carries_no_count(self, install):
        # measured: a sheet's Images collection exposes createInput and insert and NOTHING else -
        # no count, item or delete - so the count read behind this key can never answer and the key
        # a caller might plan around never appears
        drawing = install([_sheet("Art")])
        assert not hasattr(drawing.sheets.item(0).images, "count")
        assert "images" not in payload(dg.handler())["sheets"][0]


class TestViewsSlice:
    def _typed(self):
        base = _VIEW_TYPES.get("BaseViewType")
        proj = _VIEW_TYPES.get("ProjectedViewType")
        if base is None or proj is None:
            pytest.skip("ViewTypes not in the measured facts")
        return base, proj

    def test_views_rows_carry_index_and_type_only(self, install):
        base, proj = self._typed()
        install([_sheet("S", views=FakeViews([FakeView(base), FakeView(proj)]))])
        rows = payload(dg.handler(include=["views"]))["sheets"][0]["view_rows"]
        assert rows == [{"index": 0, "type": "base"}, {"index": 1, "type": "projected"}]

    def test_the_note_advertises_the_curves_slice_and_its_view_scope(self, install):
        base, _proj = self._typed()
        install([_sheet("S", views=FakeViews([FakeView(base)]))])
        note = payload(dg.handler(include=["views"]))["note"]
        assert "curves" in note and "view=N scopes one" in note
        assert "no readable geometry" not in note

    def test_the_description_does_not_claim_type_is_all_a_view_exposes(self):
        assert "ALL a view exposes" not in dg.TOOL_DESCRIPTION
        assert "ONLY its type" not in dg.TOOL_DESCRIPTION

    def test_the_view_walk_is_capped_and_says_so(self, install):
        base, _ = self._typed()
        install([_sheet("S", views=FakeViews([FakeView(base)] * (dg._MAX_VIEWS_PER_SHEET + 3)))])
        row = payload(dg.handler(include=["views"]))["sheets"][0]
        assert len(row["view_rows"]) == dg._MAX_VIEWS_PER_SHEET
        assert row["view_rows_truncated"] is True

    def test_without_the_slice_no_view_rows_are_read(self, install):
        def _refuse(_index):
            raise AssertionError("views were walked without include=['views']")

        sheet = _sheet("S", views=1)
        sheet.views.item = _refuse
        install([sheet])
        row = payload(dg.handler())["sheets"][0]
        assert row["views"] == 1 and "view_rows" not in row

    def test_an_unknown_include_is_refused_naming_the_offer(self, install):
        install([_sheet("S")])
        res = dg.handler(include=["dimensions"])
        assert res["isError"] is True and "views" in res["message"]

    def test_the_include_enum_matches_the_slice_tuple(self):
        # Catches a HAND-EDITED schema drifting from the tuple. It cannot catch a name added to the
        # tuple itself - both sides read it - which is what the dispatch test below covers.
        enum = dg.tool.input_schema["properties"]["include"]["items"]["enum"]
        assert sorted(enum) == sorted(dg._SLICES)

    def test_every_advertised_slice_actually_dispatches(self, install, pdf):
        # A name the guard admits but no branch reads returns the orientation read again under a
        # token that promised a deeper one.
        adds = {"views": "view_rows", "curves": "curve_unit", "tables": "tables",
               "revisions": "revision_count", "text": "text_unit"}
        base, _proj = self._typed()
        install([_sheet("S", views=FakeViews([FakeView(base)]))])
        pdf([_page(1, "[1] S")])
        for name in dg._SLICES:
            assert name in adds, f"name the sheet key include=['{name}'] adds"
            scope = {"pdf": "p.pdf"} if name == "text" else {}
            row = payload(dg.handler(include=[name], **scope))["sheets"][0]
            assert adds[name] in row, name


def _line(start, end):
    return _Curve(_CURVE_TYPES["LineViewCurveType"], start, end,
                  mid=((start[0] + end[0]) / 2, (start[1] + end[1]) / 2))


class TestCurvesSlice:
    def test_curve_rows_carry_the_type_and_the_points_that_read(self, install):
        circle = _Curve(_CURVE_TYPES["CircleViewCurveType"], (36, 20), (36, 20), center=(30, 20))
        install([_sheet("S", views=FakeViews([FakeView(None, curves=[_line((0, 0), (60, 0)),
                                                                      circle])]))])
        row = payload(dg.handler(include=["curves"]))["sheets"][0]
        assert row["curve_unit"] == "mm"
        assert row["view_rows"][0]["curves"] == [
            {"index": 0, "type": "line", "start": [0, 0], "end": [60, 0], "mid": [30.0, 0.0],
             "center": None},
            {"index": 1, "type": "circle", "start": [36, 20], "end": [36, 20], "mid": None,
             "center": [30, 20]}]

    def test_a_type_value_outside_the_family_publishes_null(self, install):
        odd = _Curve(max(_CURVE_TYPES.values()) + 1, (0, 0), (1, 1))
        install([_sheet("S", views=FakeViews([FakeView(None, curves=[odd])]))])
        row = payload(dg.handler(include=["curves"]))["sheets"][0]
        assert row["view_rows"][0]["curves"][0]["type"] is None

    @pytest.mark.parametrize("view", [1, "1"])
    def test_view_scopes_the_rows_to_that_one_view_int_or_digit_string(self, install, view):
        install([_sheet("S", views=FakeViews([FakeView(None, curves=[_line((0, 0), (1, 0))]),
                                              FakeView(None, curves=[_line((5, 5), (9, 5))])]))])
        rows = payload(dg.handler(include=["curves"], view=view))["sheets"][0]["view_rows"]
        assert [r["index"] for r in rows] == [1]
        assert rows[0]["curves"][0]["start"] == [5, 5]

    @pytest.mark.parametrize("bad", [-1, "-1", "one", True])
    def test_a_view_that_is_not_an_index_is_refused_naming_it(self, install, bad):
        install([_sheet("S", views=2)])
        res = dg.handler(include=["views"], view=bad)
        assert res["isError"] is True
        assert f"(got {bad!r})" in res["message"]

    def test_a_view_past_the_sheet_is_refused_naming_its_range(self, install):
        install([_sheet("Front", views=FakeViews([FakeView(None), FakeView(None)]))])
        res = dg.handler(include=["curves"], view=2)
        assert res["isError"] is True
        assert "'Front'" in res["message"] and "(0 to 1)" in res["message"]

    def test_view_without_a_view_slice_is_refused(self, install):
        install([_sheet("S", views=1)])
        res = dg.handler(view=0)
        assert res["isError"] is True and "include=['views'] or ['curves']" in res["message"]

    @pytest.mark.parametrize("extra,truncated", [(0, False), (1, True)])
    def test_the_curve_walk_is_capped_at_its_boundary(self, install, extra, truncated):
        many = [_line((i, 0), (i, 1)) for i in range(dg._MAX_CURVES_PER_VIEW + extra)]
        install([_sheet("S", views=FakeViews([FakeView(None, curves=many)]))])
        row = payload(dg.handler(include=["curves"]))["sheets"][0]["view_rows"][0]
        assert len(row["curves"]) == dg._MAX_CURVES_PER_VIEW
        assert row.get("curves_truncated", False) is truncated


class TestTablesSlice:
    def test_tables_rows_carry_name_counts_and_the_cell_grid(self, install):
        table = _CustomTable(name="BOM", row_count=2, column_count=2,
                             cells={(0, 0): "Item", (0, 1): "Qty",
                                   (1, 0): "Bolt", (1, 1): "4"})
        install([_sheet("S", custom_tables=[table])])
        row = payload(dg.handler(include=["tables"]))["sheets"][0]
        assert row["tables"] == [{"name": "BOM", "row_count": 2, "column_count": 2,
                                  "cells": [["Item", "Qty"], ["Bolt", "4"]]}]
        assert "cells_truncated" not in row["tables"][0]

    def test_a_sheet_with_no_tables_reads_an_empty_list_and_the_note_names_the_route(self, install):
        install([_sheet("S")])
        out = payload(dg.handler(include=["tables"]))
        assert out["sheets"][0]["tables"] == []
        assert out["sheets"][0]["bend_tables"] == 0
        assert "parts lists" in out["note"] and "balloons" in out["note"]

    def test_a_grid_exactly_at_the_cap_is_not_marked_truncated(self, install):
        at_cap = _CustomTable(name="AtCap", row_count=dg._MAX_TABLE_ROWS,
                             column_count=dg._MAX_TABLE_COLS)
        install([_sheet("S", custom_tables=[at_cap])])
        row = payload(dg.handler(include=["tables"]))["sheets"][0]["tables"][0]
        assert len(row["cells"]) == dg._MAX_TABLE_ROWS
        assert "cells_truncated" not in row

    def test_the_table_grid_is_capped_with_a_truncated_flag(self, install):
        big = _CustomTable(name="Big", row_count=dg._MAX_TABLE_ROWS + 3,
                          column_count=dg._MAX_TABLE_COLS + 3)
        install([_sheet("S", custom_tables=[big])])
        row = payload(dg.handler(include=["tables"]))["sheets"][0]["tables"][0]
        assert len(row["cells"]) == dg._MAX_TABLE_ROWS
        assert len(row["cells"][0]) == dg._MAX_TABLE_COLS
        assert row["cells_truncated"] is True

    def test_without_the_slice_no_tables_are_read(self, install):
        table = _CustomTable(name="BOM")
        install([_sheet("S", custom_tables=[table])])
        row = payload(dg.handler())["sheets"][0]
        assert row["custom_tables"] == 1 and "tables" not in row


class TestRevisionsSlice:
    def test_revisions_lists_every_row_title_and_header_included(self, install):
        title = _RevisionRow(zone="Revision History")
        header = _RevisionRow(rev="Rev", description="Description", date="Date",
                              approved="Approved", zone="Zone", sht="Sheet Name")
        data = _RevisionRow(rev="A", description="Initial", sht="S")
        install([_sheet("S", revision_table=_RevisionTable([title, header, data]))])
        row = payload(dg.handler(include=["revisions"]))["sheets"][0]
        assert row["revision_count"] == 3
        assert [r["rev"] for r in row["revisions"]] == ["", "Rev", "A"]

    def test_a_sheet_with_no_table_reads_an_empty_list_and_zero_count(self, install):
        install([_sheet("S")])
        row = payload(dg.handler(include=["revisions"]))["sheets"][0]
        assert row["revisions"] == [] and row["revision_count"] == 0

    def test_a_getrevisiontable_raise_reads_both_fields_null(self, install):
        sheet = _sheet("S")
        sheet.getRevisionTable = lambda: (_ for _ in ()).throw(RuntimeError("unavailable"))
        install([sheet])
        row = payload(dg.handler(include=["revisions"]))["sheets"][0]
        assert row["revisions"] is None and row["revision_count"] is None

    def test_the_revisions_list_is_capped_but_the_count_is_not(self, install):
        rows = [_RevisionRow(rev=str(i)) for i in range(dg._MAX_TABLE_ROWS + 3)]
        install([_sheet("S", revision_table=_RevisionTable(rows))])
        row = payload(dg.handler(include=["revisions"]))["sheets"][0]
        assert len(row["revisions"]) == dg._MAX_TABLE_ROWS
        assert row["revision_count"] == dg._MAX_TABLE_ROWS + 3
        assert row["revisions_truncated"] is True

    def test_without_the_slice_no_revisions_are_read(self, install):
        install([_sheet("S", revision_table=_RevisionTable([_RevisionRow()]))])
        row = payload(dg.handler())["sheets"][0]
        assert "revisions" not in row and "revision_count" not in row


def _run(text, x, y, layer="FD_Dimensions", angle=0.0):
    return {"text": text, "x": x, "y": y, "angle": angle, "layer": layer}


def _mixed_runs():
    return [_run("A", 1, 1, "BORDER"), _run("80", 2, 2), _run("x", 3, 3, None)]


def _page(number, label, runs=(), width=420.16, height=297.04):
    return {"page": number, "label": label, "width": width, "height": height, "runs": list(runs)}


@pytest.fixture
def pdf(monkeypatch):
    """Stand the PDF reader's answer in for one path: its pages, or its refusal."""
    def _pdf(pages=(), error=None):
        doc = None if error else {"modified": 1760000000.0, "page_count": len(pages),
                                  "pages": list(pages)}
        monkeypatch.setattr(dg._pdf_text, "read", lambda path: (doc, error))
    return _pdf


class TestTextSlice:
    def test_each_sheet_takes_the_page_labelled_with_its_name(self, install, pdf):
        install([_sheet("Cover"), _sheet("Detail")])
        pdf([_page(1, "[1] detail", [_run("3", 238.59, 231.94), _run("B", 16.3, 219.0, "BORDER"),
                                     _run("50", 99.0, 126.9, angle=90.0)]),
             _page(2, "[2] Cover")])
        out = payload(dg.handler(include=["text"], pdf="C:/x/sheets.pdf"))
        cover, detail = out["sheets"]
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1760000000))
        assert out["pdf"] == {"file": "C:/x/sheets.pdf", "modified_utc": stamp, "page_count": 2}
        assert stamp.endswith("T08:53:20Z")
        assert "pdf_page_reason" not in cover and "name and size only" in out["note"]
        assert (cover["pdf_page"], cover["text"], cover["text_layers"]) == (2, [], [])
        assert detail["pdf_page"] == 1 and detail["text_unit"] == "mm"
        assert detail["text"] == [
            {"text": "3", "at": [238.59, 231.94], "angle": 0.0, "layer": "FD_Dimensions"},
            {"text": "B", "at": [16.3, 219.0], "angle": 0.0, "layer": "BORDER"},
            {"text": "50", "at": [99.0, 126.9], "angle": 90.0, "layer": "FD_Dimensions"}]
        assert detail["text_layers"] == [{"layer": "FD_Dimensions", "count": 2},
                                         {"layer": "BORDER", "count": 1}]
        assert "as exported" in out["note"] and "text_truncated" not in detail

    def test_a_sheet_no_single_page_names_reads_null_beside_one_that_reads(self, install, pdf):
        install([_sheet("Twice"), _sheet("Absent"), _sheet("Once")])
        pdf([_page(1, "[1] Twice"), _page(2, "[2] Twice"), _page(3, "[3] Once", [_run("8", 1, 2)]),
             _page(4, "Once"), _page(5, None)])
        rows = payload(dg.handler(include=["text"], pdf="p.pdf"))["sheets"]
        assert [(r["pdf_page"], r["text"]) for r in rows[:2]] == [(None, None), (None, None)]
        assert "text_layers" not in rows[0]
        assert rows[0]["pdf_page_reason"] == "2 pages are labelled with this sheet's name"
        assert rows[1]["pdf_page_reason"] == "no page is labelled with this sheet's name"
        assert rows[2]["pdf_page"] == 3 and [t["text"] for t in rows[2]["text"]] == ["8"]

    @pytest.mark.parametrize("extra,more", [(0, False), (1, True)])
    def test_a_pdf_naming_no_sheet_is_refused_with_its_first_labels(self, install, pdf, extra,
                                                                    more):
        install([_sheet("Cover")])
        count = dg._MAX_LABELS_LISTED + extra
        pdf([_page(i + 1, f"[{i + 1}] Other{i}") for i in range(count)])
        res = dg.handler(include=["text"], pdf="other.pdf")
        assert res["isError"] is True
        assert f"its {count} page label(s)" in res["message"] and "'other.pdf'" in res["message"]
        assert f"Other{dg._MAX_LABELS_LISTED - 1}" in res["message"]
        assert (f"Other{dg._MAX_LABELS_LISTED}" in res["message"]) is False
        assert res["message"].count(" ...") == int(more)

    @pytest.mark.parametrize("wider,taller,matched", [
        (0.5, 0.5, True), (0.51, 0.0, False), (0.0, 0.51, False), (-0.51, 0.0, False)])
    def test_a_page_of_the_sheets_name_but_another_size_is_not_its_page(self, install, pdf,
                                                                       wider, taller, matched):
        install([_sheet("Sheet1")])
        pdf([_page(1, "[1] Sheet1", [_run("80", 2, 2)], width=420.0 + wider,
                   height=297.0 + taller)])
        row = payload(dg.handler(include=["text"], pdf="other.pdf"))["sheets"][0]
        assert (row["pdf_page"] == 1) is matched and (row["text"] is not None) is matched
        if not matched:
            assert row["pdf_page_reason"] == (
                f"page 1 carries this sheet's name but is {420.0 + wider} x {297.0 + taller} mm; "
                "the sheet reads 420.0 x 297.0 mm")

    def test_a_sheet_whose_size_did_not_read_takes_no_page(self, install, pdf):
        install([_sheet("S", width_raises="extent unavailable")])
        pdf([_page(1, "[1] S", [_run("80", 2, 2)])])
        row = payload(dg.handler(include=["text"], pdf="p.pdf"))["sheets"][0]
        assert row["pdf_page"] is None and row["text"] is None
        assert "size did not read" in row["pdf_page_reason"]

    def test_a_reader_refusal_is_returned_as_the_error(self, install, pdf):
        install([_sheet("Cover")])
        pdf(error="'p.pdf' is not a PDF this reader follows: byte 9 holds no xref table.")
        res = dg.handler(include=["text"], pdf="p.pdf")
        assert res["isError"] is True and "byte 9 holds no xref table" in res["message"]

    def test_text_needs_a_pdf_and_names_the_export_that_makes_one(self, install):
        install([_sheet("Cover")])
        res = dg.handler(include=["text"])
        assert res["isError"] is True and "drawing_export(format='pdf')" in res["message"]

    @pytest.mark.parametrize("scope", [{"pdf": "p.pdf"}, {"layer": "BORDER"}])
    def test_pdf_or_layer_without_the_text_slice_is_refused_naming_it(self, install, scope):
        install([_sheet("Cover")])
        res = dg.handler(include=["views"], **scope)
        assert res["isError"] is True
        assert f"'{next(iter(scope))}' scopes include=['text']" in res["message"]

    def test_layer_keeps_one_layer_whatever_its_case_and_the_census_stays_whole(self, install,
                                                                                 pdf):
        install([_sheet("S")])
        pdf([_page(1, "[1] S", _mixed_runs())])
        row = payload(dg.handler(include=["text"], pdf="p.pdf", layer="fd_dimensions"))["sheets"][0]
        assert [t["text"] for t in row["text"]] == ["80"]
        assert row["text_layers"] == [{"layer": "BORDER", "count": 1},
                                      {"layer": "FD_Dimensions", "count": 1},
                                      {"layer": None, "count": 1}]

    def test_a_layer_holding_no_text_is_refused_listing_the_layers_read(self, install, pdf):
        install([_sheet("S")])
        pdf([_page(1, "[1] S", _mixed_runs())])
        res = dg.handler(include=["text"], pdf="p.pdf", layer="Dimensions")
        assert res["isError"] is True
        assert "'Dimensions'" in res["message"] and "BORDER, FD_Dimensions." in res["message"]

    def test_a_layer_miss_on_a_sheet_the_pdf_lacks_reads_null_not_a_refusal(self, install, pdf):
        install([_sheet("S"), _sheet("T")])
        pdf([_page(1, "[1] T", [_run("80", 2, 2)])])
        out = payload(dg.handler(include=["text"], pdf="p.pdf", layer="BORDER", sheet="S"))
        assert out["sheets"][0]["pdf_page"] is None and out["sheets"][0]["text"] is None

    @pytest.mark.parametrize("extra,truncated", [(0, False), (1, True)])
    def test_text_rows_are_capped_at_the_boundary_after_the_layer_filter(self, install, pdf,
                                                                         extra, truncated):
        install([_sheet("S")])
        runs = ([_run("b", 0, 0, "BORDER")] * 3
                + [_run(str(i), i, 0) for i in range(dg._MAX_TEXT_PER_SHEET + extra)])
        pdf([_page(1, "[1] S", runs)])
        row = payload(dg.handler(include=["text"], pdf="p.pdf",
                                 layer="FD_Dimensions"))["sheets"][0]
        assert len(row["text"]) == dg._MAX_TEXT_PER_SHEET
        assert {t["layer"] for t in row["text"]} == {"FD_Dimensions"}
        assert row.get("text_truncated", False) is truncated
        assert row["text_layers"][1]["count"] == dg._MAX_TEXT_PER_SHEET + extra

    @pytest.mark.parametrize("standard,unit,at", [
        ("asme", "in", [10.0, 5.0]), ("iso", "mm", [254.0, 127.0]),
        ("unread", "mm", [254.0, 127.0])])
    def test_positions_land_in_the_coordinate_unit_or_stay_mm_when_it_is_unread(
            self, install, pdf, standard, unit, at):
        install([_sheet("S")], standard=standard)
        pdf([_page(1, "[1] S", [_run("1.5", 254.0, 127.0)])])
        row = payload(dg.handler(include=["text"], pdf="p.pdf"))["sheets"][0]
        assert (row["text_unit"], row["text"][0]["at"]) == (unit, at)

    def test_the_slice_reads_a_real_file_through_the_reader(self, install, tmp_path):
        install([_sheet("Front"), _sheet("Notes")])
        path = tmp_path / "package.pdf"
        path.write_bytes(export_pdf([
            {"label": "[1] Front", "runs": [("2.25", 720, 576, "FD_Dimensions", 0)]},
            {"label": "[2] Notes", "runs": []}]))
        out = payload(dg.handler(include=["text"], pdf=f'"{path}"', sheet="Front"))
        stamp = datetime.datetime.fromtimestamp(os.stat(path).st_mtime, datetime.timezone.utc)
        assert out["pdf"] == {"file": str(path), "page_count": 2,
                              "modified_utc": stamp.strftime("%Y-%m-%dT%H:%M:%SZ")}
        assert out["sheets"][0]["pdf_page"] == 1
        assert out["sheets"][0]["text"] == [
            {"text": "2.25", "at": [254.0, 203.2], "angle": 0.0, "layer": "FD_Dimensions"}]

    def test_without_the_slice_no_pdf_keys_are_published_and_the_note_names_it(self, install):
        install([_sheet("S")])
        out = payload(dg.handler())
        assert "pdf" not in out and "pdf_page" not in out["sheets"][0]
        assert "include=['text'] with pdf=" in out["note"] and "as exported" not in out["note"]


class TestSheetScope:
    def test_one_sheet_by_name_case_insensitively(self, install):
        install([_sheet("Cover"), _sheet("Detail")])
        out = payload(dg.handler(sheet="detail"))
        assert len(out["sheets"]) == 1 and out["sheets"][0]["name"] == "Detail"

    def test_a_missing_sheet_lists_the_available_names(self, install):
        install([_sheet("Cover"), _sheet("Detail")])
        res = dg.handler(sheet="Nope")
        assert res["isError"] is True
        assert "Cover" in res["message"] and "Detail" in res["message"]
