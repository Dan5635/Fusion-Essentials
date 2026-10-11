"""Scene and in-canvas edits report the final observed state."""

import json
from types import SimpleNamespace

import pytest

from conftest import load_tool


edit = load_tool("render_edit")


def _payload(result):
    return json.loads(result["content"][0]["text"])


@pytest.fixture
def scene_context(monkeypatch):
    settings = SimpleNamespace(brightness=10, cameraExposure=1)
    manager = SimpleNamespace(sceneSettings=settings)
    monkeypatch.setattr(edit._render_common, "context", lambda: (object(), manager, None))
    monkeypatch.setattr(edit._render_scene, "scene_row", lambda s, units="mm": {
        "brightness_lux": s.brightness, "exposure_ev": s.cameraExposure})
    return settings, manager


def test_scene_checks_final_read_back(scene_context):
    settings, _ = scene_context
    result = edit.handler("scene", {"brightness_lux": 25})
    assert result["isError"] is False
    assert settings.brightness == 25
    assert _payload(result)["after"]["brightness_lux"] == 25


def test_scene_reports_unrequested_exposure_changed_by_brightness(scene_context):
    _, manager = scene_context

    class Coupled:
        cameraExposure = 12

        @property
        def brightness(self):
            return self._brightness

        @brightness.setter
        def brightness(self, value):
            self._brightness = value
            self.cameraExposure = 9.526

    settings = Coupled()
    settings._brightness = 10
    manager.sceneSettings = settings
    result = edit.handler("scene", {"brightness_lux": 55})
    assert result["isError"] is False
    assert _payload(result)["changed_unrequested"]["exposure_ev"] == {
        "before": 12, "after": 9.526}


def test_depth_of_field_write_refused_before_context(monkeypatch):
    monkeypatch.setattr(edit._render_common, "context", lambda: pytest.fail("context called"))
    result = edit.handler("scene", {"dof_enabled": True})
    assert result["isError"] is True
    assert "blocking" in result["message"]


def test_unverified_ground_position_write_refused_before_context(monkeypatch):
    monkeypatch.setattr(edit._render_common, "context", lambda: pytest.fail("context called"))
    refused = edit.handler("scene", {"ground_position": [0, 0, 1]})
    assert refused["isError"] is True
    assert "ground_position" in refused["message"]


def test_custom_environment_file_write_refused_before_context(monkeypatch):
    monkeypatch.setattr(edit._render_common, "context", lambda: pytest.fail("context called"))
    refused = edit.handler("scene", {"environment_file": "C:/scratch/studio.hdr"})
    assert refused["isError"] is True
    assert "environment_file" in refused["message"]
    assert "environment_file" not in edit.tool.to_dict()["inputSchema"]["properties"]["scene"]["properties"]


def test_ground_roughness_requires_reflections_before_any_write(monkeypatch):
    settings = SimpleNamespace(brightness=10, groundRoughness=0.1,
                               isGroundReflections=False)
    manager = SimpleNamespace(sceneSettings=settings)
    monkeypatch.setattr(edit._render_common, "context", lambda: (object(), manager, None))
    monkeypatch.setattr(edit._render_scene, "scene_row", lambda s, units="mm": {
        "brightness_lux": s.brightness,
        "ground_roughness": s.groundRoughness,
        "ground_reflect": s.isGroundReflections})
    result = edit.handler("scene", {"brightness_lux": 25, "ground_roughness": 0.35})
    assert result["isError"] is True
    assert "ground_reflect=true" in result["message"]
    assert settings.brightness == 10
    assert settings.groundRoughness == 0.1


def test_focal_length_requires_perspective_before_any_write(monkeypatch):
    settings = SimpleNamespace(brightness=10, cameraFocalLength=90)
    manager = SimpleNamespace(sceneSettings=settings)
    monkeypatch.setattr(edit._render_common, "context", lambda: (object(), manager, None))
    monkeypatch.setattr(edit._render_scene, "scene_row", lambda s, units="mm": {
        "brightness_lux": s.brightness, "camera_type": "orthographic",
        "focal_length_mm": s.cameraFocalLength})
    result = edit.handler("scene", {"brightness_lux": 25, "focal_length_mm": 50})
    assert result["isError"] is True
    assert "camera_type='perspective'" in result["message"]
    assert settings.brightness == 10
    assert settings.cameraFocalLength == 90


def test_scene_silent_setter_is_error_with_before_after(scene_context):
    _, manager = scene_context

    class Silent:
        cameraExposure = 1

        @property
        def brightness(self):
            return 10

        @brightness.setter
        def brightness(self, value):
            pass

    manager.sceneSettings = Silent()
    result = edit.handler("scene", {"brightness_lux": 25})
    assert result["isError"] is True
    row = _payload(result)
    assert row["before"]["brightness_lux"] == 10
    assert row["after"]["brightness_lux"] == 10
    assert row["mismatches"] == {"brightness_lux": 10}
    assert "scene.brightness_lux=25 read back 10" in result["message"]
    assert "scene.brightness_lux=25 read back 10" in row["error"]


def test_scene_setter_exception_discloses_partial_write(scene_context):
    _, manager = scene_context

    class Failing:
        brightness = 10

        @property
        def cameraExposure(self):
            return 1

        @cameraExposure.setter
        def cameraExposure(self, value):
            raise RuntimeError("refused")

    manager.sceneSettings = Failing()
    result = edit.handler("scene", {"brightness_lux": 25, "exposure_ev": 3})
    assert result["isError"] is True
    row = _payload(result)
    assert row["applied"] == ["brightness_lux"]
    assert row["failed"] == {"field": "exposure_ev", "reason": "refused"}
    assert row["after"]["brightness_lux"] == 25
    assert "scene.exposure_ev=3 raised refused" in result["message"]


def test_camera_type_is_set_before_focal_length(monkeypatch):
    events = []
    perspective = edit.adsk.core.CameraTypes.PerspectiveCameraType

    class Settings:
        cameraType = None
        cameraFocalLength = 90

        def __setattr__(self, name, value):
            events.append(name)
            if name == "cameraFocalLength" and self.cameraType != perspective:
                return
            object.__setattr__(self, name, value)

    settings = Settings()
    monkeypatch.setattr(edit._render_common, "context", lambda: (
        object(), SimpleNamespace(sceneSettings=settings), None))
    monkeypatch.setattr(edit._render_scene, "scene_row", lambda s, units="mm": {
        "camera_type": "perspective" if s.cameraType == perspective else "orthographic",
        "focal_length_mm": s.cameraFocalLength})
    result = edit.handler("scene", {"camera_type": "perspective", "focal_length_mm": 50})
    assert result["isError"] is False
    assert events == ["cameraType", "cameraFocalLength"]
    assert "New documents open with this camera type" in _payload(result)["note"]


def test_aspect_write_is_refused_before_any_scene_setter(scene_context):
    settings, _ = scene_context
    result = edit.handler("scene", {"aspect_ratio": "custom", "aspect_width": 4,
                                    "aspect_height": 3})
    assert result["isError"] is True
    assert "aspect" in result["message"]
    assert settings.brightness == 10
    scene_schema = edit.tool.to_dict()["inputSchema"]["properties"]["scene"]["properties"]
    assert not {"aspect_ratio", "aspect_width", "aspect_height"} & set(scene_schema)


def test_name_resolution_refuses_two_exact_matches():
    rows = [SimpleNamespace(id="a", name="Studio"),
            SimpleNamespace(id="b", name="studio")]

    class Collection:
        count = 2

        def item(self, index):
            return rows[index]

    manager = SimpleNamespace(renderEnvironments=Collection())
    chosen, problem = edit._environment(manager, {"environment_name": "STUDIO"})
    assert chosen is None
    assert "matched 2" in problem and "'a'" in problem and "'b'" in problem


def test_scene_preflight_rejects_conflicting_backgrounds(scene_context):
    settings, _ = scene_context
    result = edit.handler("scene", {"background_rgb": [1, 2, 3],
                                    "environment_id": "a"})
    assert result["isError"] is True
    assert settings.brightness == 10


def test_canvas_save_refuses_existing_file_before_context(tmp_path, monkeypatch):
    path = tmp_path / "image.png"
    path.write_bytes(b"existing")
    monkeypatch.setattr(edit._render_common, "context", lambda: pytest.fail("context called"))
    result = edit.handler("canvas_save", file_path=str(path))
    assert result["isError"] is True
    assert path.read_bytes() == b"existing"


def test_canvas_save_requires_verified_image(tmp_path, monkeypatch):
    canvas = SimpleNamespace(saveImage=lambda path: True)
    manager = SimpleNamespace(inCanvasRendering=canvas)
    monkeypatch.setattr(edit._render_common, "context", lambda: (object(), manager, None))
    result = edit.handler("canvas_save", file_path=str(tmp_path / "image.png"))
    assert result["isError"] is True
    assert _payload(result)["image"]["status"] == "missing"


def test_activate_requires_active_read_back(monkeypatch):
    manager = SimpleNamespace(isRenderWorkspaceActive=False,
                              activateRenderWorkspace=lambda: True)
    monkeypatch.setattr(edit._render_common, "context", lambda: (object(), manager, None))
    result = edit.handler("activate")
    assert result["isError"] is True
    assert _payload(result)["active_after"] is False


def test_reset_scene_reports_the_default_scene_read_back(monkeypatch):
    class Defaults:
        brightness = 25
        ground_offset = 5

        def restoreDefaults(self):
            self.brightness = 10
            return True

    settings = Defaults()
    manager = SimpleNamespace(sceneSettings=settings)
    monkeypatch.setattr(edit._render_common, "context", lambda: (object(), manager, None))
    monkeypatch.setattr(edit._render_scene, "scene_row", lambda s: {
        "brightness_lux": s.brightness, "ground_offset": s.ground_offset})
    result = edit.handler("reset_scene")
    assert result["isError"] is False
    row = _payload(result)
    assert row["before"]["brightness_lux"] == 25
    assert row["after"]["brightness_lux"] == 10 and row["changed"] is True
    assert row["changed_fields"] == {"brightness_lux": {"before": 25, "after": 10}}
    assert row["unchanged_fields"] == {"ground_offset": 5}


def test_reset_scene_refuses_native_true_with_no_changed_field(monkeypatch):
    class Defaults:
        ground_offset = 5

        def restoreDefaults(self):
            return True

    manager = SimpleNamespace(sceneSettings=Defaults())
    monkeypatch.setattr(edit._render_common, "context", lambda: (object(), manager, None))
    monkeypatch.setattr(edit._render_scene, "scene_row", lambda s: {
        "ground_offset": s.ground_offset})
    result = edit.handler("reset_scene")
    assert result["isError"] is True
    row = _payload(result)
    assert row["changed"] is False and row["changed_fields"] == {}
    assert row["unchanged_fields"] == {"ground_offset": 5}
    assert "no scene field changed" in row["error"]


def test_canvas_stop_unlocks_the_view(monkeypatch):
    class Canvas:
        lockView = True

        def stop(self):
            return True

    canvas = Canvas()
    monkeypatch.setattr(edit._render_common, "context", lambda: (
        object(), SimpleNamespace(inCanvasRendering=canvas), None))
    result = edit.handler("canvas_stop")
    assert result["isError"] is False
    row = _payload(result)
    assert row["lock_view_after_stop"] is True and row["lock_view_final"] is False
    assert canvas.lockView is False
