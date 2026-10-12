"""Render creation refuses false jobs and reports exact native outcomes."""

import json
from types import SimpleNamespace

import pytest

from conftest import load_tool


rc = load_tool("render_create")
STATES = rc.adsk.fusion.LocalRenderStates


@pytest.fixture
def rig(monkeypatch):
    """A renderer with a controllable future and a settings read-back."""
    state = {"future_width": 320, "calls": 0}

    def start(path, camera=None):
        state["calls"] += 1
        return SimpleNamespace(filename=path, imageWidth=state["future_width"], imageHeight=240,
                               renderState=STATES.QueuedLocalRenderState, isValid=True)

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
    assert payload["job"]["state"] == "queued"
    assert rig["calls"] == 1


@pytest.mark.parametrize("native,name", [(STATES.FailedLocalRenderState, "failed"), (-1, None)])
def test_failed_or_unlisted_future_state_is_not_reported_started(rig, tmp_path, native, name):
    renderer = rc._render_common.context()[1].rendering
    renderer.startLocalRender = lambda path: SimpleNamespace(
        filename=path, imageWidth=320, imageHeight=240, renderState=native, isValid=True)
    result = rc.handler(file_path=str(tmp_path / "part.png"))
    assert result["isError"] is True
    partial = json.loads(result["content"][0]["text"])
    assert partial["job_id"] == "render:test:1" and partial["job"]["state"] == name


def test_full_job_registry_refusal_states_the_enforced_limit(rig, monkeypatch, tmp_path):
    monkeypatch.setattr(rc._render_jobs, "capacity", lambda: False)
    monkeypatch.setattr(rc._render_jobs, "_LIMIT", 2)
    result = rc.handler(file_path=str(tmp_path / "part.png"))
    assert result["isError"] is True and rig["calls"] == 0
    assert result["message"].startswith("2 local render jobs") and "render_get" in result["message"]


@pytest.mark.parametrize("arguments,offending,remedy", [
    ({"mode": "local", "lock_view": False}, "lock_view=False", "mode='canvas'"),
    ({"mode": "canvas", "width": 320, "transparent": False}, "width=320, transparent=False",
     "canvas_save"),
])
def test_input_of_the_other_mode_is_named_before_any_renderer_read(monkeypatch, tmp_path,
                                                                 arguments, offending, remedy):
    monkeypatch.setattr(rc._render_common, "context", lambda: pytest.fail("context called"))
    result = rc.handler(file_path=str(tmp_path / "part.png") if arguments["mode"] == "local" else "",
                        **arguments)
    assert result["isError"] is True
    assert offending in result["message"] and remedy in result["message"]


@pytest.mark.parametrize("arguments,offending,remedy", [
    ({"resolution_preset": "custom", "width": 320}, "resolution_preset='custom'",
     "both width and height"),
    ({"resolution_preset": "custom", "height": 240}, "resolution_preset='custom'",
     "both width and height"),
    ({"resolution_preset": "Web800x600", "width": 320, "height": 240},
     "resolution_preset='Web800x600'", "omit resolution_preset"),
    ({"aspect_ratio": "4:3", "width": 320, "height": 240}, "aspect_ratio='4:3'",
     "aspect_ratio='custom'"),
    ({"aspect_ratio": "4:3", "resolution_preset": "custom", "width": 320, "height": 240},
     "aspect_ratio='4:3'", "aspect_ratio='custom'"),
    ({"aspect_ratio": "4:3", "resolution_preset": "Web800x600"}, "resolution_preset='Web800x600'",
     "send one of them"),
])
def test_conflicting_size_arguments_name_the_value_and_the_remedy(monkeypatch, tmp_path,
                                                                arguments, offending, remedy):
    monkeypatch.setattr(rc._render_common, "context", lambda: pytest.fail("context called"))
    result = rc.handler(file_path=str(tmp_path / "part.png"), **arguments)
    assert result["isError"] is True
    assert offending in result["message"] and remedy in result["message"]


def test_custom_preset_with_both_dimensions_starts_the_width_and_height_job(rig, monkeypatch,
                                                                          tmp_path):
    seen = {}

    def settings(rendering, **requested):
        seen.update(requested)
        return {"width": 320, "height": 240, "quality": 75}, None

    monkeypatch.setattr(rc, "_set_rendering", settings)
    result = rc.handler(file_path=str(tmp_path / "part.png"), width=320, height=240,
                        resolution_preset="custom")
    assert result["isError"] is False and rig["calls"] == 1
    assert (seen["width"], seen["height"]) == (320, 240)
    assert seen["aspect_ratio"] == "custom" and seen["resolution_preset"] == "custom"


def test_preset_name_fusion_reports_does_not_fail_the_custom_width_and_height_job(monkeypatch):
    rendering = SimpleNamespace(resolutionWidth=1639, resolutionHeight=1353, aspectRatio=None)
    monkeypatch.setattr(rc._render_common, "enum_member", lambda family, mapping, key: key)
    monkeypatch.setattr(rc._render_common, "settings_row", lambda value: {
        "width": value.resolutionWidth, "height": value.resolutionHeight,
        "aspect_ratio": value.aspectRatio, "resolution_preset": "Web800x600"})
    row, problem = rc._set_rendering(rendering, width=320, height=240, quality=None,
                                     transparent=None, aspect_ratio="custom",
                                     resolution_preset="custom")
    assert problem is None and row["resolution_preset"] == "Web800x600"
    assert not hasattr(rendering, "resolution")
    assert (rendering.resolutionWidth, rendering.resolutionHeight) == (320, 240)
    assert (row["width"], row["height"], row["aspect_ratio"]) == (320, 240, "custom")


def test_named_preset_is_written_and_its_read_back_is_still_checked(monkeypatch):
    rendering = SimpleNamespace()
    monkeypatch.setattr(rc._render_common, "enum_member", lambda family, mapping, key: key)
    monkeypatch.setattr(rc._render_common, "settings_row", lambda value: {
        "resolution_preset": "custom"})
    row, problem = rc._set_rendering(rendering, width=None, height=None, quality=None,
                                     transparent=None, aspect_ratio="",
                                     resolution_preset="Web800x600")
    assert rendering.resolution == "Web800x600"
    assert row is None and "'resolution_preset': 'Web800x600'" in problem


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
