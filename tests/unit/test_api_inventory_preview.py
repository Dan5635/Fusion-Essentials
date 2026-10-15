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


def test_inventory_tracks_unsupported_and_retired_past_doc_excerpt(tmp_path):
    source = tmp_path / "fusion.py"
    source.write_text('''
class Machine:
    def kinematics(self):
        """''' + "x" * 410 + ''' This method is not officially supported."""

Machine.oldMode = property(lambda self: None, doc="""''' + "x" * 410
                      + ''' This property is retired.""")
''', encoding="utf-8")
    members = inventory.inventory(str(source))["Machine"]["members"]
    assert members["kinematics"]["unsupported"] is True
    assert members["oldMode"]["retired"] is True
    assert len(members["kinematics"]["doc"]) == 400


def test_old_truncated_doc_does_not_invent_a_preview_transition(tmp_path):
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    old = {"classes": {"Tools": {"members": {"change": {"doc": "x" * 400}}}}}
    new = {"classes": {"Tools": {"members": {
        "change": {"preview": True, "unsupported": True, "retired": True, "doc": "x" * 400}}}}}
    (old_dir / "fusion.json").write_text(json.dumps(old), encoding="utf-8")
    (new_dir / "fusion.json").write_text(json.dumps(new), encoding="utf-8")

    _, report = inventory.diff_snapshots(str(old_dir), str(new_dir))
    fusion = report["modules"]["fusion"]
    assert fusion["members_became_preview"] == []
    assert fusion["members_became_unsupported"] == []
    assert fusion["members_became_retired"] == []
    assert fusion["members_undecided_unsupported"] == 1


def test_diff_reports_a_member_leaving_unsupported_status(tmp_path):
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    old = {"classes": {"Machine": {"unsupported": False, "members": {
        "kinematics": {"unsupported": True, "doc": "x" * 400}}}}}
    new = {"classes": {"Machine": {"unsupported": False, "members": {
        "kinematics": {"unsupported": False, "doc": "x" * 400}}}}}
    (old_dir / "fusion.json").write_text(json.dumps(old), encoding="utf-8")
    (new_dir / "fusion.json").write_text(json.dumps(new), encoding="utf-8")

    _, report = inventory.diff_snapshots(str(old_dir), str(new_dir))
    assert report["modules"]["fusion"]["members_left_unsupported"] == ["Machine.kinematics"]


def test_retired_marker_applies_to_member_not_a_doc_about_deprecation():
    assert inventory._markers("Gets if this parameter is deprecated.")["retired"] is False
    assert inventory._markers("This property is retired.")["retired"] is True
    assert inventory._markers("This object is retired.")["retired"] is True
