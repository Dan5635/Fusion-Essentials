"""A finished local render needs a verified file before it is complete."""

import json
from types import SimpleNamespace

import pytest

from conftest import load_tool


rg = load_tool("render_get")


@pytest.fixture
def rig(monkeypatch, tmp_path):
    """A completed future with its exact requested output path."""
    path = str(tmp_path / "render.png")
    future = SimpleNamespace(filename=path, imageWidth=256, imageHeight=256,
                             renderState=2, progress=1.0, isValid=True)
    monkeypatch.setattr(rg._render_jobs, "get", lambda job_id: {
        "future": future, "path": path, "terminal": False} if job_id == "render:test:1" else None)
    monkeypatch.setattr(rg._render_jobs, "set_terminal", lambda job_id: None)
    return path


def test_native_finished_without_file_is_not_complete(rig):
    result = rg.handler(job_id="render:test:1")
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["job"]["state"] == "finished"
    assert payload["job"]["complete"] is False
    assert payload["job"]["file"]["status"] == "missing"


def test_unknown_job_refuses_after_reload(rig):
    result = rg.handler(job_id="render:prior-process:7")
    assert result["isError"] is True and "unknown" in result["message"]


def test_job_and_scene_read_discloses_partial_job_with_visible_error(rig, monkeypatch):
    monkeypatch.setattr(rg._render_common, "context", lambda: (
        None, None, "RenderManager did not read; open a Design."))
    result = rg.handler(include=["job", "scene"], job_id="render:test:1")
    assert result["isError"] is True
    payload = json.loads(result["content"][0]["text"])
    assert payload["job"]["job_id"] == "render:test:1"
    assert payload["error"] == "RenderManager did not read; open a Design."


def test_canvas_resolution_read_reports_usable_precision(monkeypatch):
    canvas = SimpleNamespace(isAdvanced=True, limitResolution=60.000003814697266,
                             lockView=False, elapsedTime=0, iterations=0)
    manager = SimpleNamespace(inCanvasRendering=canvas, isRenderWorkspaceActive=True)
    monkeypatch.setattr(rg._render_common, "context", lambda: (object(), manager, None))
    result = rg.handler(include=["canvas"])
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["canvas"]["resolution_pct"] == 60
