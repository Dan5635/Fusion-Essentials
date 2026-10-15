"""Scene reads keep all fields visible and bound environment catalogs."""

from types import SimpleNamespace

from conftest import load_tool


scene = load_tool("_render_scene")


class Collection:
    def __init__(self, rows):
        self.rows = rows
        self.count = len(rows)

    def item(self, index):
        return self.rows[index]


def test_environment_cap_reports_exact_boundary():
    rows = [SimpleNamespace(id=str(i), name=f"Env {i}", isCustomEnvironment=False)
            for i in range(2)]
    manager = SimpleNamespace(renderEnvironments=Collection(rows))
    one = scene.environment_rows(manager, 1)
    two = scene.environment_rows(manager, 2)
    assert one == {"count": 2, "environments": [
        {"id": "0", "name": "Env 0", "custom": False}], "truncated": True}
    assert two["truncated"] is False and len(two["environments"]) == 2


def test_scene_read_marks_unread_fields_null_and_scales_lengths():
    settings = SimpleNamespace(groundOffset=2.54, groundPosition=SimpleNamespace(
        x=2.54, y=0, z=-2.54), brightness=42)
    row = scene.scene_row(settings, "in")
    assert row["ground_offset"] == 1
    assert row["ground_position"] == [1, 0, -1]
    assert row["brightness_lux"] == 42
    assert row["camera_type"] is None
    assert row["environment_id"] is None
    assert row["background_rgb"] is None
    assert row["aspect_height"] is None
