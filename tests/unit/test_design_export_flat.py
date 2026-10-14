from conftest import install as _install_design
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from conftest import load_tool, payload


@pytest.fixture
def exporter(monkeypatch):
    mod = load_tool("design_export")
    body = NS(name="Sheet")
    flat = NS(foldedBody=body)
    opts = NS()
    design = NS(rootComponent=object(), exportManager=NS(
        createDXFFlatPatternExportOptions=Mock(return_value=opts), execute=Mock(return_value=True)))
    comp = NS(flatPattern=flat, parentDesign=design)
    body.parentComponent = comp
    monkeypatch.setattr(mod._DXF_FLAT, "resolve", lambda x: (body, None))
    monkeypatch.setattr(mod._common, "_native_of", lambda x: x)
    monkeypatch.setattr(mod._common, "same_component", lambda a, b: True)
    monkeypatch.setattr(mod._common, "native_identity", lambda x: id(x) if x else None)
    _install_design(mod, design)
    monkeypatch.setattr(mod._export, "snapshot", lambda p: None)
    monkeypatch.setattr(mod._export, "verify_written", lambda p, before: (None, "no fresh file"))
    return mod, design, flat, opts


def test_native_success_without_file_is_error(exporter, tmp_path):
    mod, design, flat, opts = exporter
    result = mod.handler(format="dxf", dxf_flat_pattern="body", file_path=str(tmp_path / "blank.dxf"))
    assert result["isError"] is True
    assert "no fresh file" in str(result)


def test_written_flat_reports_export_without_claiming_verified_development(exporter, monkeypatch, tmp_path):
    mod, design, flat, opts = exporter
    path = tmp_path / "blank.dxf"
    path.write_text("9\n$INSUNITS\n70\n4\n", encoding="ascii")
    monkeypatch.setattr(mod._export, "verify_written", lambda p, before: (path.stat().st_size, None))
    result = payload(mod.handler(format="dxf", dxf_flat_pattern="body", file_path=str(path)))
    assert result["exported"] is True and result["development"] == "unverified"
    assert result["file_exists"] is True and result["dxf_flat_units"] == "mm"
    assert "sheet_get(include=['features'])" in result["note"]


@pytest.mark.parametrize("extra", [{"dxf_face": "face"}, {"dxf_sketch": "Sketch1"},
                                  {"dxf_export_points": False}, {"dxf_component": "Part"}])
def test_flat_conflicts_refused_before_export(exporter, extra):
    mod, design, flat, opts = exporter
    assert mod.handler(format="dxf", dxf_flat_pattern="body", **extra)["isError"] is True
    design.exportManager.execute.assert_not_called()


def test_flat_refusal_names_only_the_sketch_flags_sent(exporter):
    mod, design, flat, opts = exporter
    result = mod.handler(format="dxf", dxf_flat_pattern="body", dxf_bend_lines=False, dxf_bend_extents=False,
                         dxf_export_construction=False, dxf_export_points=False)
    assert result["message"] == ("dxf_flat_pattern takes dxf_flat_units, dxf_bend_lines and dxf_bend_extents "
                                 "only; drop dxf_export_construction, dxf_export_points.")
    design.exportManager.execute.assert_not_called()


def test_wrong_folded_body_is_refused(exporter):
    mod, design, flat, opts = exporter
    flat.foldedBody = object()
    assert mod.handler(format="dxf", dxf_flat_pattern="body")["isError"] is True
    design.exportManager.execute.assert_not_called()
