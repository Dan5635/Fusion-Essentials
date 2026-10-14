"""Checks sweep operand replacement and its failure evidence."""
from conftest import install as _install_design

from types import SimpleNamespace
import os
import sys

import adsk.fusion
import pytest
from tests.fakes.design import _injected_roll

from conftest import (FakeTimeline, FakeTimelineObject, Profile, Sketch, SketchCurves,
                      _NamedCollection, error_message, load_tool, payload)


mod = load_tool("model_edit_sweep")
TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TESTS_DIR, "live"))
import verify_acts_model_sweep as _sweep_witness  # noqa: E402

_real_health = mod._health
_real_target_error = mod._target_error
_real_definition = mod._definition
_real_profile_members = mod._profile_members
_real_path_members = mod._path_members
_real_operand_error = mod._operand_error


def test_closed_profile_identity_reports_one_member():
    profile = SimpleNamespace(entityToken="closed-profile", objectType="adsk::fusion::Profile")
    members = _real_profile_members(profile)
    assert len(members) == 1
    assert mod._definition_report({"profile": members, "path": (("path-line", None),),
                                   "operation": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
                                   "orientation": adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType,
                                   "is_solid": True})[
                                       "profile_members"] == 1


def test_new_body_participants_are_unavailable_not_an_empty_read():
    assert mod._participants(SimpleNamespace(participantBodies=[]),
                             adsk.fusion.FeatureOperations.NewBodyFeatureOperation) is None


def test_surface_sweep_witness_requires_explicit_unavailable_participants():
    reply = {
        "edited": True, "action": "profile", "same_feature": True,
        "definition_matches": True, "definition_before": {"profile_members": 1},
        "definition_after": {"profile_members": 1}, "geometry_changed": True,
        "participant_scope_preserved": True, "participants_replayed": False,
        "retained_participants": None, "participants_before": None, "participants_after": None,
        "participant_scope_reason": "The original NewBody sweep has no Boolean participant scope.",
        "marker_restored": True, "outside_body_changes": [], "new_timeline_errors": [],
        "new_timeline_warnings": [], "target_after": [{"solid": False, "volume_cm3": None}],
    }
    check = _sweep_witness._sweep_mode_edit("open", "profile", surface=True)
    assert check(reply) is True
    for key in ("retained_participants", "participants_before", "participants_after"):
        with pytest.raises(AssertionError, match="sweep definition and participants"):
            check({**reply, key: []})
        with pytest.raises(AssertionError, match="sweep definition and participants"):
            check({name: value for name, value in reply.items() if name != key})
    with pytest.raises(AssertionError, match="sweep definition and participants"):
        check({**reply, "geometry_changed": False})
    with pytest.raises(AssertionError, match="sweep definition and participants"):
        check({name: value for name, value in reply.items() if name != "participant_scope_reason"})


class Sweep:
    """One editable sweep with a configurable profile setter."""

    def __init__(self, timeline):
        self.timelineObject = SimpleNamespace(index=1, rollTo=lambda _before: timeline.roll())
        self.entityToken = "sweep-token"
        self.parentComponent = SimpleNamespace(name="Host")
        self.guideRail = None
        self.guideSurfaces = []
        self.solidBody = None
        self.profileScaling = 0
        self.linkedFeatures = SimpleNamespace(count=0, item=lambda _i: None)
        self._profile = "old"
        self._path = ("line",)
        self._participants = []
        self.events = []
        self.assignments = 0
        self.mode = "land"

    @property
    def profile(self):
        return self._profile

    @profile.setter
    def profile(self, value):
        self.assignments += 1
        self.events.append("profile")
        if self.mode != "ignore":
            self._profile = value
        if self.mode == "raise_after_land":
            raise RuntimeError("setter raised after landing")

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, value):
        self.assignments += 1
        self.events.append("path")
        self._path = value

    @property
    def participantBodies(self):
        return self._participants

    @participantBodies.setter
    def participantBodies(self, value):
        self.events.append("participants")
        self._participants = value


class Timeline(FakeTimeline):
    """A marker whose restore assignment can be made to fail."""

    def __init__(self):
        super().__init__(items=[None, None, None], marker=3)
        self.refuse_restore = False

    @FakeTimeline.markerPosition.setter
    def markerPosition(self, value):
        if value == 3 and self.refuse_restore:
            raise RuntimeError("marker refused restore")
        FakeTimeline.markerPosition.fset(self, value)

    def roll(self):
        self.markerPosition = 1
        return True


@pytest.fixture
def rig(monkeypatch):
    """Install one measured-contract orchestration seam for each test."""
    timeline = Timeline()
    sweep = Sweep(timeline)
    design = SimpleNamespace(timeline=timeline)
    monkeypatch.setattr(mod._inputs, "resolve_inputs", lambda _spec, _raw: (
        {"feature": (sweep, "Sweep1"), "action": _raw["action"],
         "operation": _raw.get("operation"), "target_bodies": _raw.get("target_bodies")}, None))
    monkeypatch.setattr(mod, "_target_error", lambda *_args: None)
    _install_design(mod, design)
    monkeypatch.setattr(mod._common, "same_component", lambda *_args: True)
    monkeypatch.setattr(mod, "_operand_error", lambda *_args: None)
    monkeypatch.setattr(mod._sweep_common, "resolve_profile", lambda *_args: (
        "new", True, False, sweep.parentComponent, None, None))
    monkeypatch.setattr(mod._inputs, "build_path", lambda *_args: (("arc",), "arc", None))
    monkeypatch.setattr(mod._path_common, "path_sketch_curve_count", lambda *_args: 1)
    monkeypatch.setattr(mod, "_profile_members", lambda operand: operand)
    monkeypatch.setattr(mod, "_path_members", lambda operand: operand)
    monkeypatch.setattr(mod, "_same_feature", lambda *_args: True)
    monkeypatch.setattr(mod._assert, "compute_state", lambda _entity: ("healthy", None))
    monkeypatch.setattr(mod, "_health", lambda *_args: {"errors": [], "warnings": []})
    monkeypatch.setattr(mod, "_feature_body_keys", lambda _feature: {("target", None)})
    monkeypatch.setattr(mod, "_definition", lambda entity: {
        "profile": entity.profile, "path": entity.path,
        "operation": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "orientation": adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType,
        "is_solid": True})
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: {
        ("target", None): {"component": "Host", "body": "Target",
                           "shape": {"volume_cm3": 1 if sweep.profile == "old" and
                                     sweep.path == ("line",) else 2}},
        ("witness", None): {"component": "Host", "body": "Witness",
                            "shape": {"volume_cm3": 1}}})
    return sweep, timeline


def test_new_body_edit_discloses_unavailable_participant_scope(rig):
    reply = payload(mod.handler(feature="Sweep1", action="profile", profile={"sketch": "Other"}))
    assert reply["edited"] is True
    assert all(reply[key] is None for key in (
        "retained_participants", "participants_before", "participants_after"))
    assert reply["participant_scope_reason"] == (
        "The original NewBody sweep has no Boolean participant scope.")


def test_new_body_to_cut_requires_and_reads_explicit_participants(rig, monkeypatch):
    sweep, _timeline = rig
    target = SimpleNamespace(entityToken="target-body", isSolid=True,
                             parentComponent=sweep.parentComponent, assemblyContext=None,
                             name="Target")
    result_key, target_key = ("sweep-result", None), ("target-body", None)
    control_key, third_key = ("control-body", None), ("third-body", None)

    def definition(entity):
        operation = getattr(entity, "operation",
                            adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        selected = (None if operation == adsk.fusion.FeatureOperations.NewBodyFeatureOperation
                    else tuple(mod._common.native_identity(body)
                               for body in entity.participantBodies))
        return {"profile": entity.profile, "path": entity.path, "guide_path": None,
                "operation": operation, "participants": selected,
                "orientation": adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType,
                "is_solid": True}

    monkeypatch.setattr(mod, "_definition", definition)
    monkeypatch.setattr(mod._common, "native_identity", lambda body: (body.entityToken, None))
    monkeypatch.setattr(mod, "body_creator", lambda *_args: ("Extrude1", 0))
    monkeypatch.setattr(mod, "_result_body_rows", lambda _feature: [
        {"name": "SweepResult", "token": "sweep-result"}])
    monkeypatch.setattr(mod, "_feature_body_keys", lambda _feature: (
        {result_key} if getattr(sweep, "operation",
                                adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        == adsk.fusion.FeatureOperations.NewBodyFeatureOperation else {target_key}))

    observed = []

    observed = []

    def shapes(_design):
        is_cut = getattr(sweep, "operation",
                         adsk.fusion.FeatureOperations.NewBodyFeatureOperation) == \
            adsk.fusion.FeatureOperations.CutFeatureOperation
        rows = {target_key: ("Target", 0.5 if is_cut else 1),
                control_key: ("Control", 1), third_key: ("Third", 1)}
        if not is_cut:
            rows[result_key] = ("SweepResult", 1)
        return {key: {"component": "Host", "body": name, "shape": {"volume_cm3": volume}}
                for key, (name, volume) in rows.items()}

    monkeypatch.setattr(mod, "_all_shapes", shapes)

    result = mod.handler(feature="Sweep1", action="operation", operation="cut",
                         target_bodies=[target])

    assert result["isError"] is False
    details = payload(result)
    assert sweep.operation == adsk.fusion.FeatureOperations.CutFeatureOperation
    assert sweep.participantBodies == [target]
    assert details["definition_matches"] is True
    assert details["participant_scope_preserved"] is None
    assert details["participant_scope_matches_request"] is True
    assert details["geometry_changed"] is True
    assert details["outside_body_changes"] == []
    assert details["requested_participants"] == [
        {"name": "Target", "token": "target-body", "component": "Host"}]
    assert details["participants_after"] == details["requested_participants"]
    assert details["result_bodies_before"] and details["result_bodies_after"] is not None


@pytest.mark.parametrize("unexpected_third_change", [False, True])
def test_cut_participant_retarget_accounts_for_old_and_new_targets_and_control(
        rig, monkeypatch, unexpected_third_change):
    sweep, _timeline = rig
    target_a = SimpleNamespace(entityToken="body-a", isSolid=True,
                               parentComponent=sweep.parentComponent, assemblyContext=None, name="BodyA")
    target_b = SimpleNamespace(entityToken="body-b", isSolid=True,
                               parentComponent=sweep.parentComponent, assemblyContext=None, name="BodyB")
    a_key, b_key = ("body-a", None), ("body-b", None)
    control_key, third_key = ("control-body", None), ("third-body", None)
    sweep.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    sweep._participants = [target_a]

    def definition(entity):
        return {"profile": entity.profile, "path": entity.path, "guide_path": None,
                "operation": entity.operation,
                "participants": tuple(mod._common.native_identity(body)
                                      for body in entity.participantBodies),
                "orientation": adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType,
                "is_solid": True}

    monkeypatch.setattr(mod, "_definition", definition)
    monkeypatch.setattr(mod._common, "native_identity", lambda body: (body.entityToken, None))
    monkeypatch.setattr(mod, "body_creator", lambda *_args: ("Extrude1", 0))
    monkeypatch.setattr(mod, "_result_body_rows", lambda _feature: [
        {"name": body.name, "token": body.entityToken, "component": "Host"}
        for body in sweep.participantBodies])
    monkeypatch.setattr(mod, "_feature_body_keys", lambda _feature: {
        mod._common.native_identity(sweep.participantBodies[0])})

    observed = []

    def shapes(_design):
        selected = {body.entityToken for body in sweep.participantBodies}
        volumes = {"body-a": 0.96 if "body-a" in selected else 1,
                   "body-b": 0.96 if "body-b" in selected else 1,
                   "control-body": 1,
                   "third-body": 0.8 if unexpected_third_change and "body-b" in selected else 1}
        observed.append(volumes.copy())
        names = {"body-a": "BodyA", "body-b": "BodyB",
                 "control-body": "Control", "third-body": "Third"}
        return {(key, None): {"component": "Host", "body": names[key],
                              "shape": {"volume_cm3": volume}}
                for key, volume in volumes.items()}

    monkeypatch.setattr(mod, "_all_shapes", shapes)

    result = mod.handler(feature="Sweep1", action="participants", target_bodies=[target_b])

    details = result["details"] if result["isError"] else payload(result)
    if unexpected_third_change:
        assert result["isError"] is True
        assert details["outside_body_changes"] == ["Third"]
        assert details["rollback"]["verified"] is True
        assert sweep.participantBodies == [target_a]
        assert observed[1]["third-body"] == 0.8
        assert observed[-1] == observed[0]
    else:
        assert result["isError"] is False
        assert sweep.participantBodies == [target_b]
        assert details["geometry_changed"] is True
        assert details["outside_body_changes"] == []
        assert details["participants_before"] == [
            {"name": "BodyA", "token": "body-a", "component": "Host"}]
        assert details["requested_participants"] == [
            {"name": "BodyB", "token": "body-b", "component": "Host"}]
        assert details["participants_after"] == details["requested_participants"]
        assert details["participant_scope_matches_request"] is True
        assert details["result_bodies_before"] != details["result_bodies_after"]
        assert observed[0] == {"body-a": 0.96, "body-b": 1, "control-body": 1, "third-body": 1}
        assert observed[1] == {"body-a": 1, "body-b": 0.96, "control-body": 1, "third-body": 1}
        assert mod._common.native_identity(target_a) == a_key
        assert mod._common.native_identity(target_b) == b_key


def test_new_body_to_cut_refuses_an_empty_target_list_before_mutation(rig):
    sweep, timeline = rig
    result = mod.handler(feature="Sweep1", action="operation", operation="cut",
                         target_bodies=[])

    assert result["isError"] is True
    assert "nonempty explicit 'target_bodies'" in error_message(result)
    assert not hasattr(sweep, "operation")
    assert sweep.assignments == 0
    assert timeline.markerPosition == 3


def test_guide_path_uses_the_existing_path_input_and_reads_the_guide_rail(rig, monkeypatch):
    sweep, _timeline = rig
    sweep.guideRail = ("old-guide",)
    sweep.guideSurfaces = type("BRepFaceVector", (), {"__len__": lambda _self: 0})()

    def definition(entity):
        guide = entity.guideRail
        return {"profile": entity.profile, "path": entity.path,
                "guide_path": tuple(guide) if guide is not None else None,
                "operation": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
                "orientation": adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType,
                "is_solid": True}

    monkeypatch.setattr(mod, "_definition", definition)
    monkeypatch.setattr(mod, "_path_members", lambda operand: tuple(operand))
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: {
        ("target", None): {"component": "Host", "body": "Target",
                           "shape": {"volume_cm3": 2 if sweep.guideRail == ("arc",) else 1}},
        ("witness", None): {"component": "Host", "body": "Witness",
                            "shape": {"volume_cm3": 1}}})

    result = mod.handler(feature="Sweep1", action="guide_path", path="new-guide")

    assert result["isError"] is False
    assert sweep.guideRail == ("arc",)
    assert payload(result)["definition_matches"] is True
    assert payload(result)["geometry_changed"] is True


def test_ignored_setter_is_an_error(rig):
    sweep, timeline = rig
    sweep.mode = "ignore"
    result = mod.handler(feature="Sweep1", action="profile", profile="new")
    assert result["isError"] is True
    assert sweep.assignments == 1
    assert result["details"]["definition_matches"] is False
    assert timeline.markerPosition == 3


_LATER = ("Editing 'Sweep1': sketch 'PathLater' is at timeline row 11, after 'Sweep1' at row 1. "
          "Move it first with design_edit_timeline(action='reorder', feature='PathLater@11', "
          "to='before', end_feature='Sweep1@1'), then retry. Nothing was edited.")


@pytest.mark.parametrize("action", ["path", "profile"])
def test_a_later_operand_is_refused_after_read_only_definition_preflight(rig, monkeypatch, action):
    sweep, timeline = rig
    later = Sketch(name="PathLater", timeline_object=SimpleNamespace(index=11))
    line = SimpleNamespace(entityToken="later-line", parentSketch=later)
    monkeypatch.setattr(mod._inputs, "build_path", lambda *_args: (_path_of(line), "p", None))
    monkeypatch.setattr(mod._sweep_common, "resolve_profile", lambda *_args: (
        line, True, False, sweep.parentComponent, None, None))
    rolls = []
    sweep.timelineObject.rollTo = lambda _before: rolls.append(True) or timeline.roll()
    result = mod.handler(feature="Sweep1", action=action, **{action: "PathLater"})
    assert error_message(result) == _LATER
    assert (len(rolls), sweep.assignments, timeline.markerPosition) == (2, 0, 3)


def test_a_guided_sweep_mode_refusal_precedes_later_operand_advice(rig, monkeypatch):
    sweep, timeline = rig
    sweep.guideRail = object()
    later = Sketch(name="PathLater", timeline_object=SimpleNamespace(index=11))
    line = SimpleNamespace(entityToken="later-line", parentSketch=later)
    monkeypatch.setattr(mod._inputs, "build_path", lambda *_args: (_path_of(line), "p", None))
    rolls = []
    sweep.timelineObject.rollTo = lambda _before: rolls.append(True) or timeline.roll()

    result = mod.handler(feature="Sweep1", action="path", path="sketch:PathLater")

    text = error_message(result)
    assert "guide or solid-tool definition" in text
    assert "Move it first" not in text
    assert (len(rolls), sweep.assignments, timeline.markerPosition) == (1, 0, 3)


_OWNER_MODE = ("Editing 'Sweep1': Replacement profile must keep this Sweep's owner and "
               "solid/surface mode. Nothing was edited.")


@pytest.mark.parametrize("action,refusal", [
    ("profile", _OWNER_MODE),
    ("path", "Editing 'Sweep1': 'path' has a member outside the Sweep's owning component. "
             "Nothing was edited.")])
def test_a_later_operand_from_another_component_gets_the_owner_refusal_not_reorder_advice(
        rig, monkeypatch, action, refusal):
    sweep, timeline = rig
    other = SimpleNamespace(name="Other")
    later = Sketch(name="PathLater", timeline_object=SimpleNamespace(index=11), parent_component=other)
    line = SimpleNamespace(entityToken="later-line", parentSketch=later, isValid=True)
    monkeypatch.setattr(mod._inputs, "build_path", lambda *_args: (_path_of(line), "p", None))
    monkeypatch.setattr(mod._sweep_common, "resolve_profile", lambda *_args: (
        line, True, False, other, None, None))
    monkeypatch.setattr(mod._common, "same_component", lambda a, b: a is b)
    monkeypatch.setattr(mod, "_operand_error", _real_operand_error)
    result = mod.handler(feature="Sweep1", action=action, **{action: "PathLater"})
    assert error_message(result) == refusal
    assert (sweep.assignments, timeline.markerPosition) == (0, 3)


@pytest.mark.parametrize("solid", [True, False])
def test_a_later_open_profile_gets_the_mode_refusal_only_for_a_solid_sweep(rig, monkeypatch, solid):
    sweep, timeline = rig
    later = Sketch(name="OpenLater", timeline_object=SimpleNamespace(index=11),
                   parent_component=sweep.parentComponent)
    curve = SimpleNamespace(entityToken="open-curve", parentSketch=later, isValid=True)
    monkeypatch.setattr(mod._sweep_common, "resolve_profile", lambda *_args: (
        Profile(parent_sketch=None), False, True, sweep.parentComponent, later, None))
    monkeypatch.setattr(mod._inputs, "build_path", lambda *_args: (_path_of(curve), "p", None))
    monkeypatch.setattr(mod, "_operand_error", _real_operand_error)
    rigged = mod._definition
    monkeypatch.setattr(mod, "_definition", lambda entity: {**rigged(entity), "is_solid": solid})
    text = error_message(mod.handler(feature="Sweep1", action="profile",
                                     profile={"sketch": "OpenLater", "profile_index": 0}))
    assert (text == _OWNER_MODE) is solid and ("Move it first" in text) is not solid
    assert (sweep.assignments, timeline.markerPosition) == (0, 3)


def test_a_later_profile_invalid_at_the_current_marker_gets_no_reorder_advice(rig, monkeypatch):
    sweep, timeline = rig
    later = Sketch(name="PathLater", timeline_object=SimpleNamespace(index=11),
                   parent_component=sweep.parentComponent)
    line = SimpleNamespace(entityToken="later-line", parentSketch=later, isValid=False)
    monkeypatch.setattr(mod._sweep_common, "resolve_profile", lambda *_args: (
        line, True, False, sweep.parentComponent, None, None))
    monkeypatch.setattr(mod, "_operand_error", _real_operand_error)
    text = error_message(mod.handler(feature="Sweep1", action="profile", profile="PathLater"))
    assert text == ("Editing 'Sweep1': 'profile' has an invalid member at the current marker. "
                    "Nothing was edited.")
    assert "Move it first" not in text
    assert (sweep.assignments, timeline.markerPosition) == (0, 3)


_ROLLED = ("Editing 'Sweep1': sketch 'PathLater' at timeline row 3 is rolled back behind the "
           "marker. Roll to the end with design_edit_timeline(action='roll', to='end'), then "
           "retry. Nothing was edited.")


@pytest.mark.parametrize("rows", [[True], [False], [True, True]])
def test_a_rolled_back_path_sketch_is_named_with_its_row_and_the_roll_remedy(rig, monkeypatch, rows):
    sweep, timeline = rig
    for i, rolled in enumerate(rows):
        sketch = Sketch(name="PathLater", parent_component=sweep.parentComponent)
        sketch.objectType = "adsk::fusion::Sketch"
        timeline._items.append(FakeTimelineObject(name="PathLater", index=3 + i, entity=sketch,
                                                  rolled_back=rolled))
    monkeypatch.setattr(mod._inputs, "build_path", lambda *_args: (
        None, None, "No sketch named 'PathLater' for the path. Use sketch_get or sketch_create."))
    rolls = []
    sweep.timelineObject.rollTo = lambda _before: rolls.append(True) or timeline.roll()
    text = error_message(mod.handler(feature="Sweep1", action="path", path="sketch:PathLater"))
    named = rows == [True]
    assert (text == _ROLLED) is named
    assert ("No sketch named 'PathLater'" in text) is not named
    assert (sweep.assignments, timeline.markerPosition, bool(rolls)) == (0, 3, not named)


class _UnreadRow:
    """A collapsed-group member's own timeline row, whose index read raises."""

    @property
    def index(self):
        raise RuntimeError("2 : InternalValidationError : res >= 0")


def test_a_path_sketch_in_a_collapsed_group_gets_the_ungroup_hint_before_any_roll(rig, monkeypatch):
    sweep, timeline = rig
    grouped = Sketch(name="PathLater", timeline_object=_UnreadRow())
    grouped.entityToken = "grouped-sketch"
    member = FakeTimelineObject(name="PathLater", entity=grouped)
    group = FakeTimelineObject(name="LaterGroup", is_group=True)
    group.isCollapsed, group.count, group.item = True, 1, lambda _i: member
    timeline.timelineGroups = _NamedCollection([group])
    line = SimpleNamespace(entityToken="later-line", parentSketch=grouped)
    monkeypatch.setattr(mod._inputs, "build_path", lambda *_args: (_path_of(line), "p", None))
    rolls = []
    sweep.timelineObject.rollTo = lambda _before: rolls.append(True) or timeline.roll()
    text = error_message(mod.handler(feature="Sweep1", action="path", path="sketch:PathLater"))
    assert text == ("'PathLater' is inside the collapsed timeline group 'LaterGroup', which the "
                    "timeline lists as one item. Run design_edit_timeline(action='ungroup', "
                    "feature='LaterGroup') - its items are kept - then retry. The path sketch "
                    "timeline row does not read; nothing was edited.")
    assert (rolls, sweep.assignments, timeline.markerPosition) == ([], 0, 3)


@pytest.mark.parametrize("healthy", [True, False])
def test_a_collapsed_group_row_is_read_through_its_members(rig, monkeypatch, healthy):
    sweep, timeline = rig
    states = adsk.fusion.FeatureHealthStates
    member_health = states.HealthyFeatureHealthState if healthy else states.UnknownFeatureHealthState
    member = FakeTimelineObject(name="Grouped", health=member_health)
    group = FakeTimelineObject(name="LaterGroup", is_group=True,
                               health=states.UnknownFeatureHealthState)
    group.count, group.item = 1, lambda _i: member
    timeline._items = [FakeTimelineObject(name="Prof"), FakeTimelineObject(name="Sweep1"), group]
    monkeypatch.setattr(mod, "_health", _real_health)
    result = mod.handler(feature="Sweep1", action="path", path="sketch:Arc")
    if healthy:
        assert payload(result)["edited"] is True and sweep.path == ("arc",)
    else:
        assert error_message(result) == ("'Sweep1's evaluated-health census is unreadable; "
                                         "nothing was edited.")
        assert sweep.assignments == 0


class _UncountedGroup(FakeTimelineObject):
    """A collapsed group row whose member count read raises."""

    @property
    def count(self):
        raise RuntimeError("count unread")


def test_a_collapsed_group_whose_count_raises_leaves_health_unread(rig, monkeypatch):
    sweep, timeline = rig
    group = _UncountedGroup(name="LaterGroup", is_group=True,
                            health=adsk.fusion.FeatureHealthStates.UnknownFeatureHealthState)
    timeline._items = [FakeTimelineObject(name="Prof"), FakeTimelineObject(name="Sweep1"), group]
    monkeypatch.setattr(mod, "_health", _real_health)
    assert _real_health(SimpleNamespace(timeline=timeline), 3) is None
    result = mod.handler(feature="Sweep1", action="path", path="sketch:Arc")
    assert error_message(result) == ("'Sweep1's evaluated-health census is unreadable; "
                                     "nothing was edited.")
    assert sweep.assignments == 0


@pytest.mark.parametrize("row,refused", [(0, False), (1, True)])
def test_an_operand_at_the_features_own_row_is_already_too_late(row, refused):
    sketch = Sketch(name="Prof", timeline_object=SimpleNamespace(index=row))
    text = mod.later_operand_refusal("Sweep1", 1, [SimpleNamespace(parentSketch=sketch)])
    assert (text is not None) is refused


def test_a_later_source_outside_a_sketch_is_not_called_a_sketch():
    source = SimpleNamespace(name="Plane9", timelineObject=SimpleNamespace(index=4))
    assert mod.later_operand_refusal("Sweep1", 1, [source]) is None


_UNRESOLVED = ("'path': handle did not resolve - the entityToken is stale AND no geometry locator "
               "recovered it. Re-run find_geometry for a fresh handle.")
_LATER_BODY = ("Editing 'Sweep1': 'path' edge belongs to 'LaterBody', made by 'Extrude1' at row 2, "
               "after 'Sweep1' at row 1. Use an edge or sketch that exists before row 1; a fresh "
               "find_geometry handle on that body repeats this refusal. Nothing was edited.")


@pytest.mark.parametrize("holders,group,named", [
    ({"Extrude1": 2}, False, True),
    ({"Sweep1": 1}, False, False),
    ({"Extrude1": 2, "Fillet1": 3}, False, False),
    ({"Extrude1": 2}, True, False)])
def test_an_edge_of_a_later_body_names_the_one_feature_holding_that_body(
        rig, monkeypatch, holders, group, named):
    sweep, timeline = rig
    body = SimpleNamespace(name="LaterBody", entityToken="later-body")
    edge = SimpleNamespace(entityToken="later-edge", body=body)
    timeline._items = [
        FakeTimelineObject(name=name, index=i, entity=SimpleNamespace(
            bodies=_NamedCollection([body] if holders.get(name) == i else [])))
        for i, name in enumerate(["Prof", "Sweep1", "Extrude1", "Fillet1"])]
    if group:
        timeline._items.append(FakeTimelineObject(name="G", index=4, is_group=True))
    # The handle resolves at the marker and is refused at the Sweep's edit position.
    monkeypatch.setattr(mod._inputs, "build_path", lambda *_args: (
        (_path_of(edge), "p", None) if timeline.markerPosition == 3 else (None, None, _UNRESOLVED)))
    text = error_message(mod.handler(feature="Sweep1", action="path", path="later-edge"))
    assert text == (_LATER_BODY if named else f"Editing 'Sweep1': {_UNRESOLVED} Nothing was edited.")
    assert (sweep.assignments, timeline.markerPosition) == (0, 3)


def test_wrong_operand_is_refused_before_assignment(rig):
    sweep, timeline = rig
    result = mod.handler(feature="Sweep1", action="profile", profile="new", path="sketch:Other")
    assert result["isError"] is True
    assert "unused" in error_message(result)
    assert sweep.assignments == 0
    assert timeline.markerPosition == 3


@pytest.mark.parametrize("addressed,remedy", [
    (True, "Restore it with model_edit_sweep(feature='Sweep1', action='profile', "
           "profile={'sketch': 'Prof', 'profile_index': 0})."),
    (False, "Undo it in Fusion.")])
def test_setter_exception_names_the_profile_it_left(rig, addressed, remedy):
    sweep, timeline = rig
    if addressed:
        sketch = Sketch(name="Prof")
        sweep._profile = SimpleNamespace(entityToken="prof", parentSketch=sketch)
        sketch.profiles = _NamedCollection([sweep._profile])
    sweep.mode = "raise_after_land"
    result = mod.handler(feature="Sweep1", action="profile", profile="new")
    text = error_message(result)
    assert (result["details"]["definition_after"]["profile_signature"] !=
            result["details"]["definition_before"]["profile_signature"])
    assert "setter raised after landing. This STAYED APPLIED (not rolled back): profile" in text
    assert text.endswith(remedy)
    assert sweep.profile == "new"
    assert timeline.markerPosition == 3


def _sketch_line(name):
    """One line its own sketch lists, as a path member reads it."""
    sketch = Sketch(name=name, timeline_object=SimpleNamespace(index=0))
    line = SimpleNamespace(entityToken=name.lower(), parentSketch=sketch, isValid=True)
    sketch.sketchCurves = SketchCurves(lines=[line])
    return line


def _path_of(line):
    return SimpleNamespace(objectType="adsk::fusion::Path", count=1,
                           item=lambda _i: SimpleNamespace(entity=line))


def _path_swap(rig, monkeypatch, old, new, rebuild, operation="NewBodyFeatureOperation"):
    """Sweep along `old`; a swap to `new` warns a dependent and createPath answers `rebuild(seed)`."""
    sweep, _timeline = rig
    sweep._path = _path_of(old)
    sweep.parentComponent.features = SimpleNamespace(
        createPath=lambda seed, _chain: _path_of(rebuild(seed)))
    sweep.parentComponent.sketches = _NamedCollection([old.parentSketch, new.parentSketch])
    on_new = lambda: sweep.path.item(0).entity is new
    monkeypatch.setattr(mod, "_path_members", _real_path_members)
    monkeypatch.setattr(mod, "_definition", lambda entity: {
        "profile": entity.profile, "path": _real_path_members(entity.path),
        "operation": getattr(adsk.fusion.FeatureOperations, operation),
        "orientation": adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType,
        "is_solid": True})
    monkeypatch.setattr(mod._inputs, "build_path", lambda *_args: (_path_of(new), "sketch:PathB", None))
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: {("target", None): {
        "component": "Host", "body": "Target",
        "shape": {"volume_cm3": 1 if sweep.path.item(0).entity is old else 2}}})
    monkeypatch.setattr(mod, "_health", lambda *_args: {
        "errors": [], "warnings": ["Dependent"] if on_new() else []})
    return on_new


@pytest.mark.parametrize("case", ["recovers", "diverges", "unrolled"])
def test_path_failure_rolls_back_only_when_the_reread_proves_it(rig, monkeypatch, case):
    sweep, timeline = rig
    old, new = _sketch_line("PathA"), _sketch_line("PathB")
    recovers = case == "recovers"
    on_new = _path_swap(rig, monkeypatch, old, new, lambda seed: seed if recovers else new)
    rolls = []

    def roll(_before):
        # The edit rolls three times; an unrolled case refuses the restore's roll.
        rolls.append(True)
        return timeline.roll() if case != "unrolled" or len(rolls) <= 3 else False
    sweep.timelineObject.rollTo = roll
    text = error_message(mod.handler(feature="Sweep1", action="path", path="sketch:PathB"))
    remedy = (" Restore it with model_edit_sweep(feature='Sweep1', action='path', "
              "path='sketch:PathA').")
    assert text == "Editing 'Sweep1': New evaluated timeline errors or warnings appeared. " + {
        "recovers": ("It was rolled back and re-read: path reads PathA/line:0 again; the bodies "
                     "match the pre-edit read."),
        "diverges": ("A rollback ran but did not verify: path now reads PathB/line:0 (was "
                     "PathA/line:0). The definition re-read differs from before the edit; the "
                     "bodies do not match the pre-edit read; the timeline health does not match "
                     "before the edit." + remedy),
        "unrolled": ("This STAYED APPLIED (not rolled back): path now reads PathB/line:0 (was "
                     "PathA/line:0). The feature could not be rolled to its edit position."
                     + remedy)}[case]
    assert on_new() is not recovers
    assert timeline.markerPosition == 3


@pytest.mark.parametrize("volume_back", [1, 3, None])
def test_a_restore_that_re_creates_the_body_is_rolled_back_only_at_its_prior_shape(
        rig, monkeypatch, volume_back):
    sweep, _timeline = rig
    old, restored = _sketch_line("PathA"), []
    _path_swap(rig, monkeypatch, old, _sketch_line("PathB"),
               lambda seed: restored.append(seed) or seed)
    # None: the restore's body census does not read, so nothing may be called rolled back.
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: None if restored and volume_back is None
                        else {("body3" if restored else "target", None): {
                            "component": "Host", "body": "Body3" if restored else "Body1",
                            "shape": {"volume_cm3": volume_back if restored else
                                      1 if sweep.path.item(0).entity is old else 2}}})
    result = mod.handler(feature="Sweep1", action="path", path="sketch:PathB")
    outcome = {
        1: ("It was rolled back and re-read: path reads PathA/line:0 again; the body shapes match "
            "the pre-edit read. The body now reads as 'Body3' (was 'Body1'); re-read names "
            "and handles held for it."),
        3: ("A rollback ran but did not verify: path now reads PathA/line:0 (was PathA/line:0). "
            "The bodies do not match the pre-edit read. Undo it in Fusion."),
        None: ("A rollback ran but did not verify: path now reads PathA/line:0 (was PathA/line:0). "
               "The bodies were not re-read. Undo it in Fusion.")}[volume_back]
    assert error_message(result) == ("Editing 'Sweep1': New evaluated timeline errors or warnings "
                                     "appeared. " + outcome)
    assert result["details"]["rollback"]["verified"] is (volume_back == 1)
    assert result["details"]["rollback"]["recreated"] == (
        [{"component": "Host", "now": ["Body3"], "was": ["Body1"]}] if volume_back == 1 else [])


def _snapshot(rows):
    return {key: {"component": c, "body": b, "shape": {"volume_cm3": v}}
            for key, (c, b, v) in rows.items()}


@pytest.mark.parametrize("before,after,equal,recreated", [
    # Host's body comes back renamed while Other still holds a namesake of the same shape.
    ({("h1", None): ("Host", "Body1", 1), ("o1", None): ("Other", "Body1", 1)},
     {("h3", None): ("Host", "Body3", 1), ("o1", None): ("Other", "Body1", 1)}, True,
     [{"component": "Host", "now": ["Body3"], "was": ["Body1"]}]),
    # Host's body is gone and Other gains one of its shape: the material moved components.
    ({("h1", None): ("Host", "Body1", 1), ("o1", None): ("Other", "Body1", 1)},
     {("o1", None): ("Other", "Body1", 1), ("o2", None): ("Other", "Body2", 1)}, False, []),
    # A body with a new identity and its prior name is re-created.
    ({("h1", None): ("Host", "Body1", 1)}, {("h3", None): ("Host", "Body1", 1)}, True,
     [{"component": "Host", "now": ["Body1"], "was": ["Body1"]}]),
    # A body with its prior identity and a new name is re-created.
    ({("h1", None): ("Host", "Body1", 1)}, {("h1", None): ("Host", "Body3", 1)}, True,
     [{"component": "Host", "now": ["Body3"], "was": ["Body1"]}])])
def test_re_created_bodies_pair_only_within_their_component(before, after, equal, recreated):
    assert mod.shape_match(_snapshot(after), _snapshot(before)) == (equal, recreated)


def test_several_re_created_bodies_are_each_named():
    recreated = [{"component": "Host", "now": ["Body3"], "was": ["Body1"]},
                 {"component": "Host", "now": ["Body4"], "was": ["Body2"]}]
    assert mod.shape_match(
        _snapshot({("c", None): ("Host", "Body3", 1), ("d", None): ("Host", "Body4", 2)}),
        _snapshot({("a", None): ("Host", "Body1", 1), ("b", None): ("Host", "Body2", 2)})) == (
            True, recreated)
    assert mod.rolled_back_text([("path", "B/line:0", "A/line:0")], recreated) == (
        "It was rolled back and re-read: path reads A/line:0 again; the body shapes match the "
        "pre-edit read. The bodies now read as 'Body3' (was 'Body1'), 'Body4' (was "
        "'Body2'); re-read names and handles held for them.")


def test_a_split_path_curve_restores_the_piece_it_used(rig, monkeypatch):
    sweep, _timeline = rig
    sketch = Sketch(name="PathA")
    pieces = [SimpleNamespace(entityToken="patha", parentSketch=sketch, isValid=True, length=length)
              for length in (1.0, 2.0)]
    sketch.sketchCurves = SketchCurves(lines=pieces)
    _path_swap(rig, monkeypatch, pieces[1], _sketch_line("PathB"), lambda seed: seed)
    text = error_message(mod.handler(feature="Sweep1", action="path", path="sketch:PathB"))
    assert ("It was rolled back and re-read: path reads PathA/line:1 again; the bodies match the "
            "pre-edit read.") in text
    assert sweep.path.item(0).entity is pieces[1]


def test_a_path_restore_whose_participant_replay_misses_is_not_rolled_back(rig, monkeypatch):
    sweep, _timeline = rig
    _path_swap(rig, monkeypatch, _sketch_line("PathA"), _sketch_line("PathB"), lambda seed: seed,
               "CutFeatureOperation")
    selected, extra = SimpleNamespace(entityToken="selected"), SimpleNamespace(entityToken="extra")
    sweep._participants = [selected]
    replays = []

    def replay(entity, bodies):
        # The edit's replay lands; the restore's leaves the scope its path setter widened.
        replays.append(list(bodies))
        entity._participants = bodies if len(replays) == 1 else [selected, extra]
    monkeypatch.setattr(Sweep, "participantBodies", property(Sweep.participantBodies.fget, replay))
    monkeypatch.setattr(mod, "_participants", lambda entity, _op: list(entity.participantBodies))
    monkeypatch.setattr(mod._common, "native_identity", lambda body: body.entityToken)
    result = mod.handler(feature="Sweep1", action="path", path="sketch:PathB")
    text = error_message(result)
    assert "A rollback ran but did not verify" in text
    assert "The participant scope differs from before the edit." in text
    assert "rolled back and re-read" not in text
    # The path re-reads PathA, so a path call would meet the already-uses refusal.
    assert text.endswith("before the edit. Undo it in Fusion.")
    assert result["details"]["rollback"]["verified"] is False
    assert replays == [[selected], [selected]]


def test_a_raising_setter_that_widened_the_scope_is_unconfirmed(rig, monkeypatch):
    sweep, _timeline = rig
    selected, extra = SimpleNamespace(entityToken="selected"), SimpleNamespace(entityToken="extra")
    sweep._participants = [selected]

    def widen_then_raise(entity, _value):
        entity._participants = [selected, extra]
        raise RuntimeError("profile setter refused")
    monkeypatch.setattr(Sweep, "profile", property(Sweep.profile.fget, widen_then_raise))
    monkeypatch.setattr(Sweep, "participantBodies",
                        property(Sweep.participantBodies.fget, lambda _entity, _bodies: None))
    original_definition = mod._definition
    monkeypatch.setattr(mod, "_definition", lambda entity: {
        **original_definition(entity),
        "operation": adsk.fusion.FeatureOperations.CutFeatureOperation})
    monkeypatch.setattr(mod, "_participants", lambda entity, _op: list(entity.participantBodies))
    monkeypatch.setattr(mod._common, "native_identity", lambda body: body.entityToken)
    result = mod.handler(feature="Sweep1", action="profile", profile="new")
    text = error_message(result)
    assert result["details"]["participant_scope_preserved"] is False
    assert result["details"]["geometry_changed"] is False
    assert result["details"]["outside_body_changes"] == []
    assert "Whether 'Sweep1' changed is UNCONFIRMED" in text
    assert "participant_scope_preserved=False" in text
    assert "Nothing changed" not in text


@pytest.mark.parametrize("second,remedy", [
    (None, "Restore it with model_edit_sweep(feature='Sweep1', action='path', path='sketch:PathA')."),
    (True, "Restore it with model_edit_sweep(feature='Sweep1', action='path', path='sketch:PathA')."),
    (False, "Undo it in Fusion."),
    ("namesake", "Undo it in Fusion.")])
def test_a_path_remedy_names_the_sketch_only_when_the_path_is_all_its_curves(second, remedy):
    sketch = Sketch(name="PathA")
    extra = [] if second in (None, "namesake") else [SimpleNamespace(isConstruction=second)]
    sketch.sketchCurves = SketchCurves(lines=[SimpleNamespace(isConstruction=False)] + extra)
    sketches = [sketch]
    if second == "namesake":
        # 'sketch:PathA' resolves by name to the first sketch so named, not the prior path's.
        namesake = Sketch(name="PathA")
        namesake.sketchCurves = SketchCurves(lines=[SimpleNamespace(isConstruction=False)])
        sketches.insert(0, namesake)
    host = SimpleNamespace(sketches=_NamedCollection(sketches))
    assert mod._remedy("Sweep1", "path", [(sketch, "line", 0)], host) == remedy


@pytest.mark.parametrize("count,tail", [(3, "Rail/line:2"), (4, "Rail/line:2 and 1 more")])
def test_member_text_names_three_members_then_counts_the_rest(count, tail):
    sketch = Sketch(name="Rail")
    text = mod._members_text([(sketch, "line", i) for i in range(count)])
    assert text.startswith("Rail/line:0, Rail/line:1, ")
    assert text.endswith(tail)


def test_restore_failure_is_reported(rig):
    sweep, timeline = rig
    timeline.refuse_restore = True
    result = mod.handler(feature="Sweep1", action="profile", profile="new")
    assert result["isError"] is True
    assert result["details"]["marker_restored"] is False
    assert ("the timeline marker stood at 3 before the edit and reads 1 after it"
            in error_message(result))


def test_new_downstream_warning_is_an_error(rig, monkeypatch):
    sweep, timeline = rig
    monkeypatch.setattr(mod, "_health", lambda *_args: {
        "errors": [], "warnings": ["Dependent"] if sweep.profile == "new" else []})
    result = mod.handler(feature="Sweep1", action="profile", profile="new")
    assert result["isError"] is True
    assert result["details"]["new_timeline_warnings"] == ["Dependent"]
    assert timeline.markerPosition == 3


def test_path_edit_checks_actual_target_shape_and_witness(rig):
    sweep, timeline = rig
    result = mod.handler(feature="Sweep1", action="path", path="sketch:Arc")
    assert result["isError"] is False
    assert payload(result)["geometry_changed"] is True
    assert payload(result)["outside_body_changes"] == []
    assert sweep.events == ["path"]
    assert timeline.markerPosition == 3


def test_a_landed_path_with_identical_geometry_succeeds_and_says_so(rig, monkeypatch):
    sweep, timeline = rig
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: {("target", None): {
        "component": "Host", "body": "Target", "shape": {"volume_cm3": 1}}})
    result = payload(mod.handler(feature="Sweep1", action="path", path="sketch:Arc"))
    assert (result["edited"], result["definition_matches"], result["geometry_changed"]) == (
        True, True, False)
    assert result["note"].endswith(" Inspect model_inspect. The body geometry reads identical "
                                   "before and after.")
    assert "rolled back" not in result["note"] and "rollback" not in result
    assert sweep.path == ("arc",) and timeline.markerPosition == 3


def test_a_refused_verification_roll_fails_even_with_identical_geometry(rig, monkeypatch):
    sweep, timeline = rig
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: {("target", None): {
        "component": "Host", "body": "Target", "shape": {"volume_cm3": 1}}})
    rolls = []

    def roll(_before):
        # The third roll returns the evaluated Sweep to its edit position.
        rolls.append(True)
        return False if len(rolls) == 3 else timeline.roll()
    sweep.timelineObject.rollTo = roll
    result = mod.handler(feature="Sweep1", action="path", path="sketch:Arc")
    text = error_message(result)
    assert result["isError"] is True
    assert "The evaluated Sweep could not be rolled back for definition verification." in text
    assert "The body geometry reads identical" not in text
    assert "edited" not in result["details"]


def test_boolean_scope_is_replayed_before_evaluation(rig, monkeypatch):
    sweep, timeline = rig
    selected = SimpleNamespace(entityToken="selected")
    extra = SimpleNamespace(entityToken="extra")
    sweep._participants = [selected]
    original_setter = Sweep.profile.fset

    def expanding_setter(entity, value):
        original_setter(entity, value)
        entity._participants = [selected, extra]

    monkeypatch.setattr(Sweep, "profile", property(Sweep.profile.fget, expanding_setter))
    original_definition = mod._definition
    monkeypatch.setattr(mod, "_definition", lambda entity: {
        **original_definition(entity),
        "operation": adsk.fusion.FeatureOperations.CutFeatureOperation})
    monkeypatch.setattr(mod, "_participants", lambda entity, _op: list(entity.participantBodies))
    monkeypatch.setattr(mod._common, "native_identity", lambda body: body.entityToken)
    result = mod.handler(feature="Sweep1", action="profile", profile="new")
    assert result["isError"] is False
    assert payload(result)["participant_scope_preserved"] is True
    assert sweep.events == ["profile", "participants"]
    assert sweep.participantBodies == [selected]
    assert timeline.markerPosition == 3


def test_only_bodyless_rolled_back_same_row_sweep_links_are_editable(rig, monkeypatch):
    sweep, timeline = rig
    sweep.objectType = adsk.fusion.SweepFeature.classType()
    sweep.isParametric = True
    sweep.isSuppressed = False
    sweep.baseFeature = None
    companion = SimpleNamespace(
        objectType=adsk.fusion.SweepFeature.classType(),
        timelineObject=SimpleNamespace(index=1),
        healthState=adsk.fusion.FeatureHealthStates.RolledBackFeatureHealthState,
        bodies=SimpleNamespace(count=0))
    sweep.linkedFeatures = SimpleNamespace(count=1, item=lambda _i: companion)
    monkeypatch.setattr(mod, "_target_error", _real_target_error)
    result = mod.handler(feature="Sweep1", action="path", path="sketch:Arc")
    assert result["isError"] is False
    assert payload(result)["inactive_linked_before"] == 1
    assert payload(result)["inactive_linked_after"] == 1
    companion.bodies.count = 1
    result = mod.handler(feature="Sweep1", action="profile", profile="new")
    assert result["isError"] is True
    assert "linked features" in error_message(result)
    assert sweep.assignments == 1
    assert timeline.markerPosition == 3


def test_new_inactive_link_after_setter_is_allowed_but_material_link_is_not(rig, monkeypatch):
    sweep, timeline = rig
    companion = SimpleNamespace(
        objectType=adsk.fusion.SweepFeature.classType(),
        timelineObject=SimpleNamespace(index=1),
        healthState=adsk.fusion.FeatureHealthStates.RolledBackFeatureHealthState,
        bodies=SimpleNamespace(count=0))
    original_setter = Sweep.profile.fset

    def linking_setter(entity, value):
        original_setter(entity, value)
        entity.linkedFeatures = SimpleNamespace(count=1, item=lambda _i: companion)

    monkeypatch.setattr(Sweep, "profile", property(Sweep.profile.fget, linking_setter))
    result = mod.handler(feature="Sweep1", action="profile", profile="new")
    assert result["isError"] is False
    assert payload(result)["inactive_linked_before"] == 0
    assert payload(result)["inactive_linked_evaluated"] == 1
    assert payload(result)["inactive_linked_after"] == 1
    sweep._profile = "old"
    sweep.linkedFeatures = SimpleNamespace(count=0, item=lambda _i: None)
    companion.bodies.count = 1
    result = mod.handler(feature="Sweep1", action="profile", profile="new")
    assert result["isError"] is True
    assert result["details"]["mutation_attempted"] is True
    assert result["details"]["inactive_linked_evaluated"] is None
    assert timeline.markerPosition == 3


def test_open_surface_opaque_profile_reads_back_as_proxy_curve_path(rig, monkeypatch):
    sweep, timeline = rig
    host = sweep.parentComponent
    old_sketch = SimpleNamespace(name="OriginalProfile", parentComponent=host,
                                 timelineObject=SimpleNamespace(index=0))
    new_sketch = SimpleNamespace(name="AlternateProfile", parentComponent=host,
                                 timelineObject=SimpleNamespace(index=0))
    old_line = SimpleNamespace(entityToken="old-line", parentSketch=old_sketch, isValid=True)
    new_line = SimpleNamespace(entityToken="new-line", parentSketch=new_sketch, isValid=True)

    def path_of(line):
        proxy = SimpleNamespace(nativeObject=line, isValid=True)
        return SimpleNamespace(objectType="adsk::fusion::Path", count=1,
                               item=lambda _i: SimpleNamespace(entity=proxy))

    old_profile = path_of(old_line)
    new_profile = path_of(new_line)
    opaque = SimpleNamespace(objectType="adsk::fusion::Profile")
    sweep._profile = old_profile
    sweep._path = path_of(old_line)
    sweep.isSolid = False
    sweep.operation = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    sweep.orientation = adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType
    original_setter = Sweep.profile.fset

    def profile_setter(entity, value):
        original_setter(entity, value)
        if entity.mode != "ignore":
            assert value is opaque
            entity._profile = new_profile

    monkeypatch.setattr(Sweep, "profile", property(Sweep.profile.fget, profile_setter))
    monkeypatch.setattr(mod, "_definition", _real_definition)
    monkeypatch.setattr(mod, "_profile_members", _real_profile_members)
    monkeypatch.setattr(mod, "_path_members", _real_path_members)
    monkeypatch.setattr(mod, "_operand_error", _real_operand_error)
    monkeypatch.setattr(mod._sweep_common, "resolve_profile", lambda *_args: (
        opaque, False, True, host, new_sketch, None))
    monkeypatch.setattr(mod._inputs, "build_path", lambda _host, raw: (
        new_profile, raw, None))
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: {
        ("target", None): {"component": "Host", "body": "Sheet",
                           "shape": {"area_cm2": 0.4 if sweep.profile is old_profile else 0.6}},
        ("witness", None): {"component": "Host", "body": "Witness",
                            "shape": {"area_cm2": 1.0}}})
    result = mod.handler(feature="Sweep1", action="profile", profile={"sketch": "AlternateProfile"})
    assert result["isError"] is False
    assert payload(result)["definition_matches"] is True
    assert payload(result)["geometry_changed"] is True
    assert payload(result)["outside_body_changes"] == []
    sweep._profile = old_profile
    sweep.mode = "ignore"
    result = mod.handler(feature="Sweep1", action="profile", profile={"sketch": "AlternateProfile"})
    assert result["isError"] is True
    assert result["details"]["definition_matches"] is False
    assert timeline.markerPosition == 3


def test_strict_definition_rejects_partial_path_read(rig, monkeypatch):
    sweep, _ = rig
    monkeypatch.setattr(sweep, "operation", adsk.fusion.FeatureOperations.NewBodyFeatureOperation, raising=False)
    monkeypatch.setattr(sweep, "orientation", adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType, raising=False)
    monkeypatch.setattr(sweep, "isSolid", True, raising=False)
    assert _real_definition(sweep) is not None

    def unread_path(_feature):
        raise RuntimeError("3 : Didn't roll editing feature back")

    monkeypatch.setattr(Sweep, "path", property(unread_path))
    assert _real_definition(sweep) is None


def test_guide_rail_definition_uses_profile_scaling_when_orientation_is_inapplicable(rig, monkeypatch):
    sweep, _ = rig
    sweep.operation = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    sweep.isSolid = True
    sweep.profileScaling = 0
    sweep.guideRail = ("rail-curve",)
    sweep.guideSurfaces = type("BRepFaceVector", (), {"__len__": lambda _self: 0})()
    sweep.solidBody = None

    def unread_orientation(_self):
        raise RuntimeError("orientation is ignored with a guide rail")

    monkeypatch.setattr(Sweep, "orientation", property(unread_orientation), raising=False)
    baseline = _real_definition(sweep)
    assert baseline is not None
    assert baseline["orientation"] is None
    assert baseline["orientation_applicable"] is False
    assert baseline["profile_scaling"] == 0
    report = mod._definition_report(baseline)
    assert report["orientation_applicable"] is False
    assert report["profile_scaling"] == 0

    sweep.profileScaling = 1
    changed = _real_definition(sweep)
    assert changed is not None
    assert changed["profile_scaling"] != baseline["profile_scaling"]
    assert changed != baseline


def test_sweep_definition_refuses_unread_scaling_unread_unrailed_orientation_and_unsupported_tools(
        rig, monkeypatch):
    sweep, _ = rig
    sweep.operation = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    sweep.isSolid = True
    sweep.profileScaling = 0
    sweep.guideRail = ("rail-curve",)
    sweep.guideSurfaces = type("BRepFaceVector", (), {"__len__": lambda _self: 0})()
    sweep.solidBody = None

    def unread_scaling(_self):
        raise RuntimeError("profile scaling unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(Sweep, "profileScaling", property(unread_scaling), raising=False)
        assert _real_definition(sweep) is None

    sweep.profileScaling = True
    assert _real_definition(sweep) is None
    sweep.profileScaling = 0
    sweep.guideSurfaces = type("BRepFaceVector", (), {
        "__len__": lambda _self: 1, "__getitem__": lambda _self, _index: object()})()
    assert _real_definition(sweep) is None

    sweep.guideSurfaces = type("BRepFaceVector", (), {"__len__": lambda _self: 0})()
    sweep.solidBody = object()
    assert _real_definition(sweep) is None

    sweep.solidBody = None
    sweep.guideRail = None

    def unread_orientation(_self):
        raise RuntimeError("orientation is required without a guide rail")

    with monkeypatch.context() as patch:
        patch.setattr(Sweep, "orientation", property(unread_orientation), raising=False)
        assert _real_definition(sweep) is None


def test_no_guide_sweep_does_not_read_inapplicable_profile_scaling(rig, monkeypatch):
    sweep, _ = rig
    sweep.operation = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    sweep.isSolid = True
    sweep.guideRail = None
    sweep.guideSurfaces = type("BRepFaceVector", (), {"__len__": lambda _self: 0})()
    sweep.solidBody = None
    sweep.orientation = adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType

    def unread_scaling(_self):
        raise RuntimeError("profile scaling is inapplicable without a guide rail")

    with monkeypatch.context() as patch:
        patch.setattr(Sweep, "profileScaling", property(unread_scaling), raising=False)
        definition = _real_definition(sweep)
    assert definition is not None
    assert definition["orientation_applicable"] is True
    assert definition["profile_scaling"] is None


def test_partial_path_edit_discloses_omitted_curve_ids_without_changing_operand(rig, monkeypatch):
    sweep, timeline = rig
    def build(owner, raw, left=None):
        if left is not None:
            left.append("line:1")
        return ("arc",), "sketch:Partial", None
    monkeypatch.setattr(mod._inputs, "build_path", build)
    monkeypatch.setattr(mod._path_common, "path_sketch_curve_count", lambda *_args: 2)
    result = payload(mod.handler(feature="Sweep1", action="path", path="sketch:Partial"))
    assert sweep.path == ("arc",) and sweep.assignments == 1
    assert "Not in the path: line:1" in result["note"]
    assert (result["path_curves"], result["path_sketch_curves"]) == (1, 2)
    assert timeline.markerPosition == 3


def test_scope_sweep_witness_binds_r8_definition_and_result_to_r8(monkeypatch):
    monkeypatch.setattr(_sweep_witness, "_RECALL", {})
    rows = _sweep_witness._sweep_scope_edit_rows()
    context = {
        "scope_r7_doc": "doc-r7", "scope_r7_home": "home-r7",
        "scope_r8_doc": "doc-r8", "scope_r8_home": "home-r8",
        "scope_r9_doc": "doc-r9", "scope_r9_home": "home-r9",
        "scope_r8_feature": "R8Sweep", "scope_r9_feature": "R9Sweep",
    }
    definition_reads = [args(context) for name, args, _check, _save in rows
                        if name == "design_get" and callable(args)]
    assert [row["feature"] for row in definition_reads] == (
        ["R7Sweep"] * 3 + ["R8Sweep"] * 2 + ["R9Sweep"] * 3)
    edit_calls = [args(context) for name, args, _check, _save in rows
                  if name == "model_edit_sweep"]
    assert [(row["action"], row["feature"]) for row in edit_calls] == [
        ("guide_path", "R7Sweep"),
        ("guide_path", "R7Sweep"),
        ("operation", "R8Sweep"),
        ("participants", "R9Sweep"),
        ("participants", "R9Sweep"),
    ]
    feature_row = next(row for row in rows if row[0] == "model_sweep"
                       and isinstance(row[3], tuple) and row[3][0] == "scope_r8_feature")
    feature_key, save = feature_row[3]
    assert save({"feature": "R8Sweep", "result_bodies": ["R8ResultToken"]}) == "R8Sweep"
    assert _sweep_witness._RECALL[feature_key] == "R8Sweep"
    assert _sweep_witness._RECALL["scope_r8_result_body"] == "R8ResultToken"


def test_sweep_operation_witness_requires_participant_result_body_identity(monkeypatch):
    monkeypatch.setattr(_sweep_witness, "_RECALL", {
        "scope_r8_feature": "R8Sweep", "sweep_scope_identity_R8Sweep": "native-feature"})
    participant = {"name": "R8Box", "token": "participant-token", "component": "(Unsaved)"}
    payload = {
        "feature": "R8Sweep", "action": "operation", "edited": True,
        "same_feature": True, "definition_matches": True, "geometry_changed": True,
        "marker_restored": True, "new_timeline_errors": [], "new_timeline_warnings": [],
        "outside_body_changes": [], "participant_scope_matches_request": True,
        "participant_scope_preserved": None, "requested_participants": [participant],
        "participants_before": None, "participants_after": [participant],
        "result_bodies_before": [{"name": "Body3", "token": "new-body-token",
                                   "component": "(Unsaved)"}],
        "result_bodies_after": [participant],
    }
    check = _sweep_witness._sweep_scope_edit("operation", "cut", "scope_r8_feature", ("R8Box",))
    assert check(payload) is True

    payload["result_bodies_after"] = []
    with pytest.raises(AssertionError, match="public Sweep edit read-back"):
        check(payload)

    payload["result_bodies_after"] = [{**participant, "token": "unrelated-body-token"}]
    with pytest.raises(AssertionError, match="public Sweep edit read-back"):
        check(payload)


@pytest.mark.parametrize("mode", ["false", "truthy", "noop", "raise"])
def test_sweep_roll_refusal_keeps_words_assignments_and_restore(rig, monkeypatch, mode):
    sweep, timeline = rig
    monkeypatch.setattr(sweep.timelineObject, "rollTo", _injected_roll(timeline, 1, mode))
    text = error_message(mod.handler(feature="Sweep1", action="profile", profile="X"))
    why = "injected roll failure" if mode == "raise" else "Fusion refused the Sweep edit position."
    assert why in text
    assert (sweep.assignments, timeline.markerPosition, sweep.profile) == (0, 3, "old")
