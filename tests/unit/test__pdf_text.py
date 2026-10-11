# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The exported-PDF text reader against files built in the shape drawing_export's PDFs have."""

import os

import pytest

from conftest import export_pdf, export_pdf_code, load_tool

pt = load_tool("_pdf_text")

_MM = 25.4 / 72


def _read(tmp_path, data):
    path = tmp_path / "sheet.pdf"
    path.write_bytes(data)
    return pt.read(str(path))


def _one(tmp_path, runs=(("A", 100, 100, "L", 0),), **bend):
    return _read(tmp_path, export_pdf([{"label": "[1] S", "runs": list(runs)}], **bend))


class TestRead:
    def test_each_page_reads_its_label_size_and_placed_runs(self, tmp_path):
        doc, err = _read(tmp_path, export_pdf([
            {"label": "[1] Front", "runs": [("80", 720, 144, "FD_Dimensions", 0),
                                            ("Title", 36, 72, "TITLEBLOCK", 0)]},
            {"label": "[2] Detail Ø", "size": (842, 595),
             "runs": [("50", 288, 360, "FD_Dimensions", 90)]}]))
        assert err is None and doc["page_count"] == 2
        front, detail = doc["pages"]
        assert (front["page"], front["label"]) == (1, "[1] Front")
        assert (front["width"], front["height"]) == (round(1191 * _MM, 2), round(842 * _MM, 2))
        assert front["runs"] == [
            {"text": "80", "x": 254.0, "y": 50.8, "angle": 0.0, "layer": "FD_Dimensions"},
            {"text": "Title", "x": 12.7, "y": 25.4, "angle": 0.0, "layer": "TITLEBLOCK"}]
        assert (detail["page"], detail["label"], detail["width"]) == (2, "[2] Detail Ø",
                                                                      round(842 * _MM, 2))
        assert detail["runs"] == [
            {"text": "50", "x": 101.6, "y": 127.0, "angle": 90.0, "layer": "FD_Dimensions"}]

    def test_the_document_carries_the_files_own_modified_time(self, tmp_path):
        path = tmp_path / "sheet.pdf"
        path.write_bytes(export_pdf([{"label": "[1] S", "runs": [("A", 10, 10, "L", 0)]}]))
        os.utime(path, (1760000000, 1760000000))
        doc, err = pt.read(str(path))
        assert err is None and doc["modified"] == 1760000000

    def test_positions_count_from_the_page_box_corner(self, tmp_path):
        doc, _err = _read(tmp_path, export_pdf([
            {"label": "[1] S", "origin": (72, 144), "runs": [("A", 144, 216, "L", 0)]}]))
        run = doc["pages"][0]["runs"][0]
        assert (run["x"], run["y"]) == (25.4, 25.4)

    def test_nested_transforms_apply_innermost_first_and_end_with_their_q(self, tmp_path):
        a = export_pdf_code("A")
        tail = (f"q 2 0 0 2 0 0 cm 1 0 0 1 10 20 cm BT 1 0 0 1 5 5 Tm <{a}> Tj ET Q "
                f"BT 1 0 0 1 72 144 Tm <{a}> Tj ET")
        doc, err = _one(tmp_path, runs=[("A", 720, 720, "L", 0)], content_tail=tail)
        assert err is None
        assert [(r["x"], r["y"]) for r in doc["pages"][0]["runs"][1:]] == [
            (round(30 * _MM, 2), round(50 * _MM, 2)), (25.4, 50.8)]

    def test_a_layer_holds_through_nested_marks_and_ends_with_its_own(self, tmp_path):
        a, b, c = (export_pdf_code(ch) for ch in "ABC")
        tail = (f"/OC /oc5 BDC /Span BMC BT 1 0 0 1 10 10 Tm <{a}> Tj ET EMC "
                f"BT 1 0 0 1 20 10 Tm [<{b}> -20 <{c}>] TJ ET EMC "
                f"BT 1 0 0 1 30 10 Tm <{c}> Tj ET")
        doc, err = _one(tmp_path, runs=[("ABC", 720, 720, "Outer", 0)], content_tail=tail)
        assert err is None
        assert [(r["text"], r["layer"]) for r in doc["pages"][0]["runs"]] == [
            ("ABC", "Outer"), ("A", "Outer"), ("BC", "Outer"), ("C", None)]

    def test_a_blank_run_is_dropped_and_a_page_without_a_label_reads_none(self, tmp_path):
        doc, err = _read(tmp_path, export_pdf([
            {"label": None, "runs": [(" ", 10, 10, "L", 0), ("x 2", 20, 10, "L", 0)]}]))
        assert err is None and doc["pages"][0]["label"] is None
        assert [r["text"] for r in doc["pages"][0]["runs"]] == ["x 2"]

    def test_an_image_on_the_page_does_not_stop_the_read(self, tmp_path):
        doc, err = _one(tmp_path, xobject="Image")
        assert err is None and [r["text"] for r in doc["pages"][0]["runs"]] == ["A"]

    def test_streams_stored_without_a_filter_read_too(self, tmp_path):
        doc, err = _one(tmp_path, filter_name=None)
        assert err is None and doc["pages"][0]["runs"][0]["text"] == "A"


class TestRefusals:
    @pytest.mark.parametrize("bend,said", [
        ({"content_tail": "BT 10 10 Td <0048> Tj ET"}, "places text with the Td operator"),
        ({"content_tail": "BT 1 0 0 1 9 9 Tm <0048> Tj <0048> Tj ET"}, "no Tm of its own places"),
        ({"content_tail": "BT 1 0 0 1 9 9 Tm <0001> Tj ET"}, "maps to no text"),
        ({"content_tail": "BI /W 1 /H 1 ID x EI"}, "holds an inline image"),
        ({"content_tail": "1 0 0 1 0 cm"}, "cm operator without six numbers"),
        ({"xobject": "Form"}, "whose Subtype reads Form"),
        ({"page_entries": "/Rotate 90"}, "carries Rotate 90"),
        ({"page_entries": "/UserUnit 2"}, "UserUnit 2"),
        ({"font_entries": ""}, "carries no ToUnicode map"),
        ({"cmap_tail": "1 beginbfrange\n<0001> <0002> <0041>\nendbfrange\n"}, "by bfrange"),
        ({"trailer_entries": "/Prev 9"}, "continues an earlier one"),
        ({"filter_name": "LZWDecode"}, "stored with filter LZWDecode"),
        ({"predictor": 12}, "predictor 12"),
    ])
    def test_a_file_off_the_followed_shape_is_refused_naming_the_departure(self, tmp_path, bend,
                                                                           said):
        doc, err = _one(tmp_path, **bend)
        assert doc is None
        assert "is not a PDF this reader follows" in err and said in err

    @pytest.mark.parametrize("tail", [
        "<< [1] 2 >>", "[1] 12 Tf BT 1 0 0 1 9 9 Tm <0048> Tj ET"])
    def test_a_structure_that_raises_comes_back_as_a_refusal_naming_the_fault(self, tmp_path,
                                                                              tail):
        doc, err = _one(tmp_path, content_tail=tail)
        assert doc is None
        assert "is not a PDF this reader follows: its structure raised TypeError" in err

    def test_a_truncated_file_is_refused_for_its_missing_startxref(self, tmp_path):
        data = export_pdf([{"label": "[1] S", "runs": [("A", 10, 10, "L", 0)]}])
        doc, err = _read(tmp_path, data[:len(data) // 2])
        assert doc is None and "no %PDF- header with a startxref" in err

    @pytest.mark.parametrize("cap,which,said", [
        ("MAX_STREAM_BYTES", max, "decodes to more than"),
        ("MAX_INFLATED_BYTES", sum, "bytes together")])
    def test_a_decoded_size_at_its_cap_reads_and_one_byte_over_is_refused(
            self, tmp_path, monkeypatch, cap, which, said):
        data = export_pdf([{"label": "[1] S", "runs": [("A", 10, 10, "L", 0)] * 40},
                           {"label": "[2] T", "runs": [("A", 10, 10, "L", 0)]}])
        sizes, inner = [], pt._Document.decoded

        def counting(self, stream, what):
            out = inner(self, stream, what)
            sizes.append(len(out))
            return out
        monkeypatch.setattr(pt._Document, "decoded", counting)
        assert _read(tmp_path, data)[1] is None and len(sizes) == 3
        monkeypatch.setattr(pt._Document, "decoded", inner)
        monkeypatch.setattr(pt, cap, which(sizes))
        assert _read(tmp_path, data)[1] is None
        monkeypatch.setattr(pt, cap, which(sizes) - 1)
        doc, err = _read(tmp_path, data)
        assert doc is None and said in err and str(which(sizes) - 1) in err

    def test_inflation_stops_one_byte_past_the_stream_cap(self, tmp_path, monkeypatch):
        data = export_pdf([{"label": "[1] S", "runs": [("A", 10, 10, "L", 0)] * 40}])
        held, real = [], pt.zlib.decompressobj

        class _Spy:
            def __init__(self):
                self._inner = real()

            def decompress(self, raw, max_length=0):
                held.append(len(self._inner.decompress(raw, max_length)))
                return b"x" * held[-1]
        monkeypatch.setattr(pt.zlib, "decompressobj", _Spy)
        monkeypatch.setattr(pt, "MAX_STREAM_BYTES", 64)
        doc, err = _read(tmp_path, data)
        assert doc is None and "decodes to more than 64 bytes" in err
        assert held and max(held) == 65

    def test_a_file_that_is_no_pdf_is_refused(self, tmp_path):
        doc, err = _read(tmp_path, b"ISO-10303-21;\nHEADER;\n")
        assert doc is None and "no %PDF- header" in err

    def test_a_missing_file_is_refused_with_the_path(self, tmp_path):
        doc, err = pt.read(str(tmp_path / "absent.pdf"))
        assert doc is None and "absent.pdf" in err and "could not be opened" in err

    def test_the_size_cap_admits_a_file_at_it_and_refuses_one_byte_over(self, tmp_path,
                                                                         monkeypatch):
        data = export_pdf([{"label": "[1] S", "runs": [("A", 10, 10, "L", 0)]}])
        monkeypatch.setattr(pt, "MAX_FILE_BYTES", len(data))
        assert _read(tmp_path, data)[1] is None
        monkeypatch.setattr(pt, "MAX_FILE_BYTES", len(data) - 1)
        doc, err = _read(tmp_path, data)
        assert doc is None and f"is {len(data)} bytes" in err and str(len(data) - 1) in err
