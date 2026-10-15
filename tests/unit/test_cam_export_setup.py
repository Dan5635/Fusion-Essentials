# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""cam_export_setup: an additive setup's parts to a 3MF file, judged by the file on disk."""

from types import SimpleNamespace

import pytest

from conftest import load_tool

ce = load_tool("cam_export_setup")

NOT_INCLUDED = 0


def _rig(monkeypatch, tmp_path, additive=True, writes=True, answers=True, unbound_reads=True,
         keeps=("supportInclusion", "isSliceDataIncluded"), resets_support_on_slice=False,
         resets_target_on_slice=False, resets_path_on_slice=False):
    """One setup behind get_cam and an export manager whose options keep only the `keeps` knobs."""
    setup = SimpleNamespace(name="Print")
    state = {"bound": None, "executed": []}

    class _Options:
        """The 3MF options object: its knobs refuse to read until a setup is bound, as measured."""
        error = "native reason"

        def __init__(self):
            object.__setattr__(self, "held", {"supportInclusion": 1, "isSliceDataIncluded": True})

        def __getattr__(self, name):
            held = object.__getattribute__(self, "held")
            if name in ("supportInclusion", "isSliceDataIncluded") and state["bound"] is None:
                raise RuntimeError("3 : Export options should have setup its export object.")
            return held[name]

        def __setattr__(self, name, value):
            held = object.__getattribute__(self, "held")
            if name == "exportObject":
                state["bound"] = value
            if name in ("exportObject", "fullFilename") or name in keeps:
                held[name] = value
                if name == "isSliceDataIncluded" and resets_support_on_slice:
                    held["supportInclusion"] = 1
                if name == "isSliceDataIncluded" and resets_target_on_slice:
                    held["exportObject"] = None
                if name == "isSliceDataIncluded" and resets_path_on_slice:
                    held["fullFilename"] = "other.3mf"

    def execute(options):
        state["executed"].append(dict(options.held))
        if writes:
            with open(options.fullFilename, "wb") as handle:
                handle.write(b"PK-parts-only")
        return answers
    cam = SimpleNamespace(exportManager=SimpleNamespace(create3MFOptions=_Options, execute=execute))
    monkeypatch.setattr(ce, "get_cam", lambda: (cam, None))
    monkeypatch.setattr(ce, "find_setup", lambda c, name: (
        (setup, ["Print"], None) if name == "Print" else (None, ["Print"], f"No setup '{name}'.")))
    monkeypatch.setattr(ce, "is_additive_setup", lambda s: additive)
    monkeypatch.setattr(ce.adsk.cam, "CAM3MFSupportInclusionType",
                        SimpleNamespace(NotIncluded=NOT_INCLUDED), raising=False)
    return state, str(tmp_path / "build.3mf")


from conftest import payload as _payload


def test_the_setup_is_bound_before_the_knobs_and_supports_and_slices_are_left_out(monkeypatch, tmp_path):
    state, path = _rig(monkeypatch, tmp_path)
    out = _payload(ce.handler(setup="Print", file_path=path))
    sent = state["executed"][0]
    assert (sent["supportInclusion"], sent["isSliceDataIncluded"]) == (NOT_INCLUDED, False)
    assert out["file_path"] == path and out["size_bytes"] == 13
    assert out["left_out"] == ["supports", "slices"] and "not printer-ready" in out["note"]
    for declared in ce.RETURNS:
        assert declared.assert_present(out) == ""


def test_a_path_without_the_extension_gets_it(monkeypatch, tmp_path):
    _state, _path = _rig(monkeypatch, tmp_path)
    out = _payload(ce.handler(setup="Print", file_path=str(tmp_path / "build")))
    assert out["file_path"].endswith("build.3mf")


@pytest.mark.parametrize("knob,word", [("supportInclusion", "supports"), ("isSliceDataIncluded", "slices")])
def test_a_knob_that_does_not_land_stops_before_anything_is_written(monkeypatch, tmp_path, knob, word):
    keeps = tuple(k for k in ("supportInclusion", "isSliceDataIncluded") if k != knob)
    state, path = _rig(monkeypatch, tmp_path, keeps=keeps)
    res = ce.handler(setup="Print", file_path=path)
    assert res["isError"] is True and f"leaves {word} out did not read back" in res["message"]
    assert state["executed"] == []


def test_a_later_option_that_resets_support_stops_before_export(monkeypatch, tmp_path):
    state, path = _rig(monkeypatch, tmp_path, resets_support_on_slice=True)
    res = ce.handler(setup="Print", file_path=path)
    assert res["isError"] is True and "supports out changed after" in res["message"]
    assert state["executed"] == []


@pytest.mark.parametrize("reset,word", [("resets_target_on_slice", "target"),
                                        ("resets_path_on_slice", "path")])
def test_a_later_option_that_changes_export_binding_stops(monkeypatch, tmp_path, reset, word):
    state, path = _rig(monkeypatch, tmp_path, **{reset: True})
    res = ce.handler(setup="Print", file_path=path)
    assert res["isError"] is True and f"3MF {('export ' if word == 'target' else 'output ')}{word} changed" in res["message"]
    assert state["executed"] == []


def test_an_export_that_answers_true_and_writes_nothing_is_an_error(monkeypatch, tmp_path):
    _state, path = _rig(monkeypatch, tmp_path, writes=False)
    res = ce.handler(setup="Print", file_path=path)
    assert res["isError"] is True and "did not write a usable file" in res["message"]
    assert "native reason" in res["message"]


def test_an_export_that_answers_false_is_an_error_even_with_a_file(monkeypatch, tmp_path):
    _state, path = _rig(monkeypatch, tmp_path, answers=False)
    res = ce.handler(setup="Print", file_path=path)
    assert res["isError"] is True and "answered false" in res["message"]


@pytest.mark.parametrize("kw,said", [
    ({"setup": "", "file_path": "x.3mf"}, "Provide 'setup'"),
    ({"setup": "Nope", "file_path": "x.3mf"}, "No setup 'Nope'"),
    ({"setup": "Print", "file_path": ""}, "Provide 'file_path'")])
def test_missing_inputs_are_refused_before_any_export(monkeypatch, tmp_path, kw, said):
    state, _path = _rig(monkeypatch, tmp_path)
    res = ce.handler(**kw)
    assert res["isError"] is True and said in res["message"] and state["executed"] == []


def test_a_setup_that_is_not_additive_is_refused(monkeypatch, tmp_path):
    state, path = _rig(monkeypatch, tmp_path, additive=False)
    res = ce.handler(setup="Print", file_path=path)
    assert res["isError"] is True and "is not additive" in res["message"] and state["executed"] == []
