"""Preview transitions in saved Fusion binding inventories."""

import importlib.util
import json
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "api_inventory.py"
SPEC = importlib.util.spec_from_file_location("api_inventory_preview", SOURCE)
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def test_diff_reports_member_and_enum_preview_transitions_from_old_snapshot_docs(tmp_path):
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    old = {"classes": {
        "Views": {"preview": True, "doc": "This class is a preview feature", "members": {
            "create": {"kind": "method", "doc": "This method is a preview feature"},
            "setting": {"kind": "property", "doc": "Stable property"},
            "unchanged": {"kind": "method", "doc": "This method is a preview feature"}}},
        "Mode": {"preview": False, "doc": "This enum is a preview feature", "members": {}}}}
    new = {"classes": {
        "Views": {"preview": False, "doc": "Stable class", "members": {
            "create": {"kind": "method", "doc": "Stable method"},
            "setting": {"kind": "property", "doc": "This property is a preview feature"},
            "unchanged": {"kind": "method", "doc": "This method is a preview feature"}}},
        "Mode": {"preview": False, "doc": "Stable enum", "members": {}}}}
    (old_dir / "fusion.json").write_text(json.dumps(old), encoding="utf-8")
    (new_dir / "fusion.json").write_text(json.dumps(new), encoding="utf-8")

    _, report = inventory.diff_snapshots(str(old_dir), str(new_dir))
    fusion = report["modules"]["fusion"]
    assert fusion["left_preview"] == ["Mode", "Views"]
    assert fusion["members_left_preview"] == ["Views.create"]
    assert fusion["members_became_preview"] == ["Views.setting"]
    assert fusion["member_changes"] == {}


def test_inventory_marks_method_property_and_enum_preview(tmp_path):
    source = tmp_path / "fusion.py"
    source.write_text('''
class Mode:
    """This enum is a preview feature."""

class Views:
    def create(self):
        """This method is a preview feature."""

Views.setting = property(lambda self: None, doc="This property is a preview feature.")
''', encoding="utf-8")
    classes = inventory.inventory(str(source))
    assert classes["Mode"]["preview"] is True
    assert classes["Views"]["members"]["create"]["preview"] is True
    assert classes["Views"]["members"]["setting"]["preview"] is True
