"""Scene and in-canvas edits report the final observed state."""

import json
import math
from types import SimpleNamespace

import pytest

from conftest import GroundOffsetScene, load_tool


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


def test_ground_position_write_refused_as_read_only_before_context(monkeypatch):
    monkeypatch.setattr(edit._render_common, "context", lambda: pytest.fail("context called"))
    refused = edit.handler("scene", {"ground_position": [0, 0, 1], "brightness_lux": 25})
    assert refused["isError"] is True
    assert "ground_position are read-only" in refused["message"]
    assert "render_get(include=['scene'])" in refused["message"]


_UNITS_REMEDY = "render_edit's own input beside scene"
_BACKGROUND_REMEDY = "background_rgb gives solid_color; environment_id or environment_name gives"


@pytest.mark.parametrize("field,value,remedies", [
    ("units", "in", (_UNITS_REMEDY,)),
    ("background_type", "environment", (_BACKGROUND_REMEDY,)),
    ("environment_custom", True, ()),
])
def test_returned_only_scene_key_is_refused_with_its_own_remedy_before_context(
        monkeypatch, field, value, remedies):
    monkeypatch.setattr(edit._render_common, "context", lambda: pytest.fail("context called"))
    message = edit.handler("scene", {field: value, "brightness_lux": 25})["message"]
    assert f"Scene field(s) {field} are read-only" in message
    assert "render_get(include=['scene'])" in message
    for remedy in (_UNITS_REMEDY, _BACKGROUND_REMEDY):
        assert (remedy in message) is (remedy in remedies)


def test_mixed_request_names_every_read_only_key_and_each_remedy(monkeypatch):
    monkeypatch.setattr(edit._render_common, "context", lambda: pytest.fail("context called"))
    message = edit.handler("scene", {"units": "in", "environment_custom": False, "exposure_ev": 3,
                                     "background_type": "solid_color",
                                     "ground_position": [0, 0, 1]})["message"]
    assert "background_type, environment_custom, ground_position, units are read-only" in message
    assert _UNITS_REMEDY in message and _BACKGROUND_REMEDY in message


@pytest.fixture
def ground(monkeypatch):
    def install(settings):
        monkeypatch.setattr(edit._render_common, "context", lambda: (
            object(), SimpleNamespace(sceneSettings=settings), None))
        return settings
    return install


def test_top_level_units_input_scales_a_scene_length_both_ways(ground):
    settings = ground(GroundOffsetScene(held_cm=1.27))
    result = edit.handler("scene", {"ground_offset": 1}, units="in")
    assert result["isError"] is False
    assert settings.sent == [pytest.approx(1.27)] and settings.held == pytest.approx(2.54)
    row = _payload(result)
    assert row["before"]["ground_offset"] == 0.5
    assert row["after"]["units"] == "in" and row["after"]["ground_offset"] == 1


def test_ground_offset_write_assigns_the_difference_to_the_held_offset(ground):
    settings = ground(GroundOffsetScene(held_cm=0.5))
    result = edit.handler("scene", {"ground_offset": 7})
    assert result["isError"] is False
    assert settings.sent == [pytest.approx(0.2)]
    row = _payload(result)
    assert row["before"]["ground_offset"] == 5 and row["after"]["ground_offset"] == 7
    assert row["applied"] == ["ground_offset"] and "already_set" not in row


def test_ground_offset_zero_is_reached_and_published_unsigned(ground):
    settings = ground(GroundOffsetScene(held_cm=1.2))
    result = edit.handler("scene", {"ground_offset": 0})
    assert result["isError"] is False and settings.sent == [-1.2]
    assert math.copysign(1, settings.groundOffset) == -1
    assert math.copysign(1, _payload(result)["after"]["ground_offset"]) == 1
    assert "-0.0" not in result["content"][0]["text"]


@pytest.mark.parametrize("held_mm,wanted,sent_count", [(5, 5, 0), (1e-5, 0, 0), (2e-5, 0, 1)])
def test_ground_offset_within_the_read_back_tolerance_assigns_nothing(
        ground, held_mm, wanted, sent_count):
    settings = ground(GroundOffsetScene(held_cm=held_mm / 10))
    result = edit.handler("scene", {"ground_offset": wanted})
    assert result["isError"] is False and len(settings.sent) == sent_count
    row = _payload(result)
    assert row["applied"] == ["ground_offset"] * sent_count
    assert row.get("already_set") == (None if sent_count else ["ground_offset"])


def test_ground_offset_difference_uses_the_offset_read_after_an_earlier_field_moved_it(ground):
    settings = ground(GroundOffsetScene(held_cm=0.5, injected_shift_on="isGroundFlattened"))
    result = edit.handler("scene", {"ground_offset": 7, "flatten_ground": True})
    assert result["isError"] is False
    assert settings.sent == [pytest.approx(0.1)]
    row = _payload(result)
    assert row["applied"] == ["flatten_ground", "ground_offset"]
    assert row["after"]["ground_offset"] == 7 and row["after"]["flatten_ground"] is True


def test_ground_offset_left_alone_is_still_judged_by_the_final_read(ground):
    settings = ground(GroundOffsetScene(held_cm=0.5, injected_shift_on="lightAngle"))
    result = edit.handler("scene", {"ground_offset": 5, "light_angle_deg": 90})
    assert result["isError"] is True and settings.sent == []
    row = _payload(result)
    assert row["applied"] == ["light_angle_deg"] and row["already_set"] == ["ground_offset"]
    assert row["mismatches"] == {"ground_offset": 6.0}
    assert "scene.ground_offset=5 read back 6.0" in row["error"]


@pytest.mark.parametrize("unread", [RuntimeError("no read"), float("nan")])
def test_unread_current_ground_offset_fails_the_field_without_assigning(ground, unread):
    sent = ground(GroundOffsetScene(injected_read=unread)).sent
    result = edit.handler("scene", {"flatten_ground": True, "ground_offset": 7})
    assert result["isError"] is True and sent == []
    row = _payload(result)
    assert row["applied"] == ["flatten_ground"]
    assert row["failed"] == {"field": "ground_offset",
                             "reason": "the current ground offset did not read"}
    assert row["error"].startswith(
        "scene.ground_offset=7 was not assigned: the current ground offset did not read; "
        "read render_get(include=['scene'])")


def test_ground_offset_setter_that_adds_nothing_is_a_mismatch_error(ground):
    ground(GroundOffsetScene(held_cm=0.5, injected_setter_adds_nothing=True))
    result = edit.handler("scene", {"ground_offset": 7})
    assert result["isError"] is True
    row = _payload(result)
    assert row["applied"] == ["ground_offset"] and row["mismatches"] == {"ground_offset": 5.0}
    assert row["before"]["ground_offset"] == row["after"]["ground_offset"] == 5.0
    assert "scene.ground_offset=7 read back 5.0" in row["error"]


def test_custom_environment_file_write_refused_before_context(monkeypatch):
    monkeypatch.setattr(edit._render_common, "context", lambda: pytest.fail("context called"))
    refused = edit.handler("scene", {"environment_file": "C:/scratch/studio.hdr"})
    assert refused["isError"] is True
    assert "Unknown scene field(s): environment_file" in refused["message"]
    assert "read-only" not in refused["message"]
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
    row = _payload(result)
    assert "New documents open with this camera type" in row["note"]
    assert row["camera_type_before"] == "orthographic"
    assert "It was 'orthographic' before this edit" in row["note"]
    scene_schema = edit.tool.to_dict()["inputSchema"]["properties"]["scene"]["properties"]
    assert "camera_type_before" in scene_schema["camera_type"]["description"]


def test_unread_prior_camera_type_is_reported_as_unread(monkeypatch):
    perspective = edit.adsk.core.CameraTypes.PerspectiveCameraType
    settings = SimpleNamespace(cameraType=None)
    monkeypatch.setattr(edit._render_common, "context", lambda: (
        object(), SimpleNamespace(sceneSettings=settings), None))
    monkeypatch.setattr(edit._render_scene, "scene_row", lambda s, units="mm": {
        "camera_type": "perspective" if s.cameraType == perspective else None})
    result = edit.handler("scene", {"camera_type": "perspective"})
    assert result["isError"] is False
    row = _payload(result)
    assert row["camera_type_before"] is None and row["after"]["camera_type"] == "perspective"
    assert "before this edit did not read" in row["note"] and "None" not in row["note"]


def test_edit_without_camera_type_carries_no_prior_camera_key(scene_context):
    row = _payload(edit.handler("scene", {"brightness_lux": 25}))
    assert "camera_type_before" not in row and "camera type" not in row["note"]


_RATIO = {label: getattr(edit.adsk.fusion.RenderAspectRatios, member)
          for label, member in edit._render_common.ASPECT.items()}
_ASPECT = ("aspect_ratio", "aspect_width", "aspect_height")


class _AspectScene:
    """Local scene-settings double, shaped as a live script measured: a pair lands on the height."""

    def __init__(self, keeps=True):
        vars(self).update(writes=[], keeps=keeps, pending=None, brightness=10,
                          aspectRatio=_RATIO["viewport"], aspectRatioWidth=0, aspectRatioHeight=0)

    def __setattr__(self, name, value):
        self.writes.append((name, value))
        if name == "aspectRatioWidth":
            vars(self)["pending"] = value
        elif name == "aspectRatioHeight":
            if self.keeps and self.pending is not None:
                vars(self).update(aspectRatio=_RATIO["custom"], aspectRatioWidth=self.pending,
                                  aspectRatioHeight=value)
        elif name == "aspectRatio":
            if self.keeps and value == _RATIO["16:9"]:
                vars(self).update(aspectRatio=value, aspectRatioWidth=16, aspectRatioHeight=9)
        else:
            vars(self)[name] = value


@pytest.fixture
def aspect_scene(monkeypatch):
    """Install one aspect double as the scene settings and return it."""
    def install(keeps=True):
        settings = _AspectScene(keeps)
        monkeypatch.setattr(edit._render_common, "context", lambda: (
            object(), SimpleNamespace(sceneSettings=settings), None))
        return settings
    return install


@pytest.mark.parametrize("label", [{}, {"aspect_ratio": "custom"}])
def test_aspect_pair_writes_width_then_height_and_no_ratio_member(aspect_scene, label):
    settings = aspect_scene()
    result = edit.handler("scene", {"aspect_height": 5, "aspect_width": 7, **label})
    assert result["isError"] is False
    assert settings.writes == [("aspectRatioWidth", 7), ("aspectRatioHeight", 5)]
    row = _payload(result)
    assert row["applied"] == ["aspect_width", "aspect_height"]
    assert [row["after"][key] for key in _ASPECT] == ["custom", 7, 5]


@pytest.mark.parametrize("label,read_back", [("16:9", ["16:9", 16, 9]),
                                             ("viewport", ["viewport", 0, 0])])
def test_aspect_preset_writes_only_its_ratio_member(aspect_scene, label, read_back):
    settings = aspect_scene()
    result = edit.handler("scene", {"aspect_ratio": label})
    assert result["isError"] is False
    assert settings.writes == [("aspectRatio", _RATIO[label])]
    row = _payload(result)
    assert row["applied"] == ["aspect_ratio"]
    assert [row["after"][key] for key in _ASPECT] == read_back
    scene_schema = edit.tool.to_dict()["inputSchema"]["properties"]["scene"]["properties"]
    assert scene_schema["aspect_ratio"]["enum"] == list(_RATIO)
    assert scene_schema["aspect_width"] == scene_schema["aspect_height"] == {"type": "integer"}


@pytest.mark.parametrize("scene", [{"aspect_ratio": "16:9"},
                                   {"aspect_width": 7, "aspect_height": 5}])
def test_aspect_fields_fusion_reports_are_not_listed_as_unrequested_changes(aspect_scene, scene):
    aspect_scene()
    row = _payload(edit.handler("scene", scene))
    assert row["before"]["aspect_ratio"] == "viewport" != row["after"]["aspect_ratio"]
    assert row["before"]["aspect_width"] == 0 != row["after"]["aspect_width"]
    assert row["changed_unrequested"] == {}


@pytest.mark.parametrize("scene,offending,remedy", [
    ({"aspect_width": 4}, "aspect_width=4", "aspect_width and aspect_height"),
    ({"aspect_height": 3}, "aspect_height=3", "aspect_width and aspect_height"),
    ({"aspect_ratio": "custom", "aspect_width": 4}, "aspect_width=4",
     "aspect_width and aspect_height"),
    ({"aspect_ratio": "custom"}, "aspect_ratio='custom'", "aspect_width and aspect_height"),
    ({"aspect_ratio": "16:9", "aspect_width": 16, "aspect_height": 9}, "aspect_ratio='16:9'",
     "send the preset alone"),
    ({"aspect_width": 4.5, "aspect_height": 3}, "aspect_width=4.5", "positive integer"),
    ({"aspect_width": True, "aspect_height": 3}, "aspect_width=True", "positive integer"),
    ({"aspect_width": 4, "aspect_height": 0}, "aspect_height=0", "positive integer"),
    ({"aspect_ratio": "3:2"}, "aspect_ratio='3:2'", "listed aspect ratio"),
])
def test_malformed_aspect_request_is_refused_before_context(monkeypatch, scene, offending, remedy):
    monkeypatch.setattr(edit._render_common, "context", lambda: pytest.fail("context called"))
    result = edit.handler("scene", {**scene, "brightness_lux": 25})
    assert result["isError"] is True
    assert offending in result["message"] and remedy in result["message"]


def test_aspect_dimension_of_one_reaches_the_setters(aspect_scene):
    settings = aspect_scene()
    edit.handler("scene", {"aspect_width": 1, "aspect_height": 1})
    assert settings.writes == [("aspectRatioWidth", 1), ("aspectRatioHeight", 1)]


def test_multi_field_edit_keeps_width_and_height_adjacent(aspect_scene):
    settings = aspect_scene()
    result = edit.handler("scene", {"aspect_height": 5, "brightness_lux": 25, "aspect_width": 7})
    assert result["isError"] is False
    assert [name for name, _ in settings.writes] == ["brightness", "aspectRatioWidth",
                                                     "aspectRatioHeight"]
    assert edit._ORDER.index("aspect_height") == edit._ORDER.index("aspect_width") + 1


@pytest.mark.parametrize("label,mismatches", [
    ({}, {"aspect_width": 0, "aspect_height": 0}),
    ({"aspect_ratio": "custom"}, {"aspect_width": 0, "aspect_height": 0,
                                  "aspect_ratio": "viewport"}),
])
def test_ignored_aspect_pair_is_the_mismatch_error_with_before_and_after(aspect_scene, label,
                                                                       mismatches):
    settings = aspect_scene(keeps=False)
    result = edit.handler("scene", {"aspect_width": 4, "aspect_height": 3, **label})
    assert result["isError"] is True
    assert settings.writes == [("aspectRatioWidth", 4), ("aspectRatioHeight", 3)]
    row = _payload(result)
    assert row["mismatches"] == mismatches
    assert [row["before"][key] for key in _ASPECT] == ["viewport", 0, 0]
    assert [row["after"][key] for key in _ASPECT] == ["viewport", 0, 0]
    assert "scene.aspect_width=4 read back 0" in row["error"]


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
