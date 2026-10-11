"""Render creation refuses false jobs and reports exact native outcomes."""

import json
from types import SimpleNamespace

import pytest

from conftest import load_tool


rc = load_tool("render_create")


@pytest.fixture
def rig(monkeypatch):
    """A renderer with a controllable future and a settings read-back."""
    state = {"future_width": 320, "calls": 0}

    def start(path, camera=None):
        state["calls"] += 1
        return SimpleNamespace(filename=path, imageWidth=state["future_width"], imageHeight=240,
                               renderState=0, isValid=True)

    renderer = SimpleNamespace(startLocalRender=start)
    design = SimpleNamespace(parentDocument=SimpleNamespace(name="Scratch"))
    monkeypatch.setattr(rc._render_common, "context", lambda: (design, SimpleNamespace(rendering=renderer), None))
    monkeypatch.setattr(rc, "_set_rendering", lambda *args, **kwargs: (
        {"width": 320, "height": 240, "quality": 75}, None))
    monkeypatch.setattr(rc._render_jobs, "capacity", lambda: True)
    monkeypatch.setattr(rc._render_jobs, "add", lambda future, path, document: "render:test:1")
    return state


def test_future_without_matching_dimensions_is_error(rig, tmp_path):
    rig["future_width"] = 640
    result = rc.handler(file_path=str(tmp_path / "part.png"))
    assert result["isError"] is True
    partial = json.loads(result["content"][0]["text"])
    assert partial["job_id"] == "render:test:1"
    assert partial["job"]["width"] == 640
    assert "differ" in result["message"]
    assert "differ" in partial["error"] and "render_get" in partial["error"]


def test_existing_path_refuses_before_renderer_changes(rig, tmp_path):
    path = tmp_path / "part.png"
    path.write_bytes(b"owner data")
    result = rc.handler(file_path=str(path))
    assert result["isError"] is True and "already exists" in result["message"]
    assert rig["calls"] == 0 and path.read_bytes() == b"owner data"


def test_valid_future_returns_trackable_job(rig, tmp_path):
    result = rc.handler(file_path=str(tmp_path / "part.png"))
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["job_id"] == "render:test:1" and payload["job"]["width"] == 320
    assert rig["calls"] == 1


def test_failed_future_is_not_reported_started(rig, tmp_path):
    renderer = rc._render_common.context()[1].rendering
    renderer.startLocalRender = lambda path: SimpleNamespace(
        filename=path, imageWidth=320, imageHeight=240, renderState=3, isValid=True)
    result = rc.handler(file_path=str(tmp_path / "part.png"))
    assert result["isError"] is True
    partial = json.loads(result["content"][0]["text"])
    assert partial["job_id"] == "render:test:1" and partial["job"]["state"] == 3


def test_final_combined_read_catches_later_setter_reset(monkeypatch):
    class Settings:
        renderQuality = 75
        isBackgroundTransparent = False

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)
            if name == "isBackgroundTransparent":
                object.__setattr__(self, "renderQuality", 25)

    settings = Settings()
    monkeypatch.setattr(rc._render_common, "settings_row", lambda value: {
        "quality": value.renderQuality, "transparent": value.isBackgroundTransparent})
    row, problem = rc._set_rendering(settings, width=None, height=None, quality=80,
                                     transparent=True, aspect_ratio="", resolution_preset="")
    assert row is None and "quality" in problem and "25" in problem


def test_failed_canvas_start_restores_prior_view_lock(monkeypatch):
    class Canvas:
        isAdvanced = False
        limitResolution = 100
        lockView = False

        def start(self, quality):
            return False

    canvas = Canvas()
    monkeypatch.setattr(rc._render_common, "context", lambda: (
        object(), SimpleNamespace(inCanvasRendering=canvas), None))
    result = rc.handler(mode="canvas", lock_view=True)
    assert result["isError"] is True
    row = json.loads(result["content"][0]["text"])
    assert row["before"]["lock_view"] is False
    assert row["after"]["lock_view"] is False and canvas.lockView is False
    assert "render_get" in row["error"]


@pytest.mark.parametrize("rounding,accepted", [(0.000003814697266, True), (0.1, False)])
def test_canvas_resolution_read_back_allows_only_native_rounding(monkeypatch, rounding, accepted):
    class Canvas:
        isAdvanced = True
        lockView = False

        def __init__(self):
            self._resolution = 100.0
            self.started = 0

        @property
        def limitResolution(self):
            return self._resolution

        @limitResolution.setter
        def limitResolution(self, value):
            self._resolution = value + rounding

        def start(self, quality):
            self.started += 1
            return True

    canvas = Canvas()
    monkeypatch.setattr(rc._render_common, "context", lambda: (
        object(), SimpleNamespace(inCanvasRendering=canvas), None))
    result = rc.handler(mode="canvas", advanced=True, resolution_pct=60, lock_view=True)
    assert result["isError"] is not accepted
    assert canvas.started == int(accepted)
    if accepted:
        row = json.loads(result["content"][0]["text"])
        assert row["settings"]["lock_view"] is True
    else:
        assert canvas.lockView is False
