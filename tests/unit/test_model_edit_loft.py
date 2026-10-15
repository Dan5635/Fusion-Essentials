"""Checks bounded Loft section edits and their failure evidence."""
from conftest import install as _install_design

from types import SimpleNamespace

import adsk.fusion
import pytest
from tests.fakes.design import _injected_roll

from conftest import (FakeTimeline, FakeTimelineObject, Sketch, _NamedCollection,
                      error_message, load_tool, payload)


mod = load_tool("model_edit_loft")
_real_target_error = mod._target_error
_real_operand_error = mod._operand_error
_real_health = mod._health


class Timeline(FakeTimeline):
    """A marker that rolls before the Loft and can reject restoration."""

    def __init__(self):
        super().__init__(items=[None] * 5, marker=5)
        self.refuse_restore = False

    @FakeTimeline.markerPosition.setter
    def markerPosition(self, value):
        if value == 5 and self.refuse_restore:
            raise RuntimeError("marker restore refused")
        FakeTimeline.markerPosition.fset(self, value)

    def roll(self):
        self.markerPosition = 2
        return True


class Section:
    """A section with native-style entity assignment and checked deletion."""

    def __init__(self, owner, name):
        self.owner = owner
        self._entity = name
        self.mode = "land"
        self.endCondition = SimpleNamespace(objectType="adsk::fusion::LoftFreeEndCondition")

    @property
    def entity(self):
        return self._entity

    @entity.setter
    def entity(self, value):
        self.owner.assignments += 1
        if self.mode != "ignore":
            self._entity = value
        if self.mode == "raise_after_land" and self.owner.assignments == 1:
            raise RuntimeError("setter raised after landing")

    def deleteMe(self):
        self.owner.assignments += 1
        if self.mode == "false":
            return False
        self.owner.sections.remove(self)
        return True

    def reorder(self, new_index):
        self.owner.assignments += 1
        if self.mode in ("false", "ignore"):
            return self.mode == "ignore"
        self.owner.sections.remove(self)
        self.owner.sections.insert(new_index, self)
        return True


class Loft:
    """A Loft whose ordered section list changes in place."""

    def __init__(self, timeline):
        self.timelineObject = SimpleNamespace(index=2, rollTo=lambda _before: timeline.roll())
        self.entityToken = "loft-token"
        self.parentComponent = SimpleNamespace(name="Host")
        self.sections = [Section(self, name) for name in ("A", "B", "C")]
        self.assignments = 0
        self.mode = "land"

    @property
    def loftSections(self):
        return SimpleNamespace(count=len(self.sections), item=lambda i: self.sections[i])


@pytest.fixture
def rig(monkeypatch):
    """Install one edit orchestration scene with a result body and witness."""
    timeline = Timeline()
    loft = Loft(timeline)
    design = SimpleNamespace(timeline=timeline)
    monkeypatch.setattr(mod._inputs, "resolve_inputs", lambda _spec, raw: (
        {"feature": (loft, "Loft1"), "action": raw["action"]}, None))
    monkeypatch.setattr(mod, "_target_error", lambda *_args: None)
    _install_design(mod, design)
    monkeypatch.setattr(mod, "_operand_error", lambda *_args: None)
    monkeypatch.setattr(mod._inputs.ProfileRef, "resolve", lambda _self, _raw, _scope: ("X", None))
    monkeypatch.setattr(mod._common, "native_identity", lambda operand: operand)
    monkeypatch.setattr(mod, "_same_feature", lambda *_args: True)
    monkeypatch.setattr(mod._assert, "compute_state", lambda _entity: ("healthy", None))
    monkeypatch.setattr(mod, "_health", lambda *_args: {"errors": [], "warnings": []})
    monkeypatch.setattr(mod, "_feature_body_keys", lambda _feature: {"target"})
    def definition(feature):
        ends = (mod._end_state(feature.sections[0]), mod._end_state(feature.sections[-1]))
        if None in ends:
            return None
        return {"sections": tuple(section.entity for section in feature.sections),
                "operation": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
                "is_solid": True, "is_closed": False, "guide_count": 0,
                "ends": ends}

    monkeypatch.setattr(mod, "_definition", definition)
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: {
        "target": {"component": "Host", "body": "Target",
                   "shape": {"volume_cm3": 1 if tuple(s.entity for s in loft.sections) ==
                             ("A", "B", "C") else 2}},
        "witness": {"component": "Host", "body": "Witness",
                    "shape": {"volume_cm3": 1}}})
    return loft, timeline


def test_a_later_interior_profile_gets_reorder_advice_after_mode_checks(rig, monkeypatch):
    loft, timeline = rig
    later = Sketch(name="S1Later", timeline_object=SimpleNamespace(index=14))
    monkeypatch.setattr(mod._inputs.ProfileRef, "resolve", lambda _self, _raw, _scope: (
        SimpleNamespace(parentSketch=later), None))
    rolls = []
    loft.timelineObject.rollTo = lambda _before: rolls.append(True) or timeline.roll()
    result = mod.handler(feature="Loft1", action="retarget", section_index=1,
                         profile={"sketch": "S1Later", "profile_index": 0})
    assert error_message(result) == (
        "Editing 'Loft1': sketch 'S1Later' is at timeline row 14, after 'Loft1' at row 2. Move it "
        "first with design_edit_timeline(action='reorder', feature='S1Later@14', to='before', "
        "end_feature='Loft1@2'), then retry. Nothing was edited.")
    assert (rolls, loft.assignments, timeline.markerPosition) == ([True], 0, 5)


def test_a_later_profile_from_another_component_gets_the_owner_refusal_not_reorder_advice(
        rig, monkeypatch):
    loft, timeline = rig
    later = Sketch(name="S1Later", timeline_object=SimpleNamespace(index=14),
                   parent_component=SimpleNamespace(name="Other"))
    foreign = SimpleNamespace(objectType=adsk.fusion.Profile.classType(), parentSketch=later,
                              isValid=True)
    monkeypatch.setattr(mod._inputs.ProfileRef, "resolve", lambda _self, _raw, _scope: (foreign, None))
    monkeypatch.setattr(mod, "_operand_error", _real_operand_error)
    result = mod.handler(feature="Loft1", action="retarget", section_index=1,
                         profile={"sketch": "S1Later", "profile_index": 0}, component="Other")
    assert error_message(result) == ("Editing 'Loft1': 'profile' is outside the Loft's owning "
                                     "component. Nothing was edited.")
    assert (loft.assignments, timeline.markerPosition) == (0, 5)
    assert tuple(section.entity for section in loft.sections) == ("A", "B", "C")


def test_a_later_profile_invalid_at_the_current_marker_gets_no_reorder_advice(rig, monkeypatch):
    loft, timeline = rig
    later = Sketch(name="S1Later", timeline_object=SimpleNamespace(index=14),
                   parent_component=loft.parentComponent)
    stale = SimpleNamespace(objectType=adsk.fusion.Profile.classType(), parentSketch=later,
                            isValid=False)
    monkeypatch.setattr(mod._inputs.ProfileRef, "resolve", lambda _self, _raw, _scope: (stale, None))
    monkeypatch.setattr(mod, "_operand_error", _real_operand_error)
    text = error_message(mod.handler(feature="Loft1", action="retarget", section_index=1,
                                     profile={"sketch": "S1Later", "profile_index": 0}))
    assert text == ("Editing 'Loft1': 'profile' is invalid at the current marker. "
                    "Nothing was edited.")
    assert "Move it first" not in text
    assert (loft.assignments, timeline.markerPosition) == (0, 5)


def test_endpoint_zero_refuses_before_later_operand_reorder_advice(rig, monkeypatch):
    loft, timeline = rig
    reads, rolls = [], []
    later = Sketch(name="S1Later", timeline_object=SimpleNamespace(index=14))
    monkeypatch.setattr(mod._inputs.ProfileRef, "resolve", lambda _self, _raw, _scope: (
        reads.append(True) or SimpleNamespace(parentSketch=later), None))
    monkeypatch.setattr(loft.timelineObject, "rollTo", lambda _before: rolls.append(True) or timeline.roll())
    result = mod.handler(feature="Loft1", action="retarget", section_index=0,
                         profile={"sketch": "S1Later", "profile_index": 0})
    message = error_message(result)
    assert "'section_index'=0 is an endpoint" in message and "Choose an interior" in message
    assert "Nothing was edited" in message and "Move it first" not in message
    assert (reads, rolls, loft.assignments, timeline.markerPosition) == ([], [], 0, 5)
    assert tuple(section.entity for section in loft.sections) == ("A", "B", "C")


def test_last_endpoint_refuses_before_later_operand_reorder_advice(rig, monkeypatch):
    loft, timeline = rig
    later = Sketch(name="S1Later", timeline_object=SimpleNamespace(index=14))
    monkeypatch.setattr(mod._inputs.ProfileRef, "resolve", lambda _self, _raw, _scope: (
        SimpleNamespace(parentSketch=later), None))
    result = mod.handler(feature="Loft1", action="retarget", section_index=2,
                         profile={"sketch": "S1Later", "profile_index": 0})
    message = error_message(result)
    assert "'section_index'=2 must select an interior section of 3" in message
    assert "Nothing was edited" in message and "Move it first" not in message
    assert loft.assignments == 0 and timeline.markerPosition == 5
    assert tuple(section.entity for section in loft.sections) == ("A", "B", "C")


def test_retarget_changes_only_middle_section_and_material(rig):
    loft, timeline = rig
    result = mod.handler(feature="Loft1", action="retarget", section_index=1, profile="X")
    assert result["isError"] is False
    assert tuple(s.entity for s in loft.sections) == ("A", "X", "C")
    assert payload(result)["definition_matches"] is True
    assert payload(result)["geometry_changed"] is True
    assert payload(result)["outside_body_changes"] == []
    assert timeline.markerPosition == 5


def test_a_landed_section_with_identical_geometry_succeeds_and_says_so(rig, monkeypatch):
    loft, timeline = rig
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: {"target": {
        "component": "Host", "body": "Target", "shape": {"volume_cm3": 1}}})
    result = payload(mod.handler(feature="Loft1", action="retarget", section_index=1, profile="X"))
    assert (result["edited"], result["definition_matches"], result["geometry_changed"]) == (
        True, True, False)
    assert result["note"] == ("Loft section changed on the same feature. Inspect model_inspect. "
                              "The body geometry reads identical before and after.")
    assert "rollback" not in result
    assert tuple(s.entity for s in loft.sections) == ("A", "X", "C")
    assert timeline.markerPosition == 5


def test_remove_from_three_leaves_two_ordered_sections(rig):
    loft, timeline = rig
    result = mod.handler(feature="Loft1", action="remove", section_index=1)
    assert result["isError"] is False
    assert tuple(s.entity for s in loft.sections) == ("A", "C")
    assert payload(result)["definition_after"]["section_count"] == 2
    assert loft.assignments == 1 and timeline.markerPosition == 5


def test_two_section_removal_refuses_before_delete(rig):
    loft, timeline = rig
    loft.sections.pop(1)
    result = mod.handler(feature="Loft1", action="remove", section_index=1)
    assert result["isError"] is True
    assert "fewer than two" in error_message(result)
    assert result["details"]["definition_matches"] is True
    assert loft.assignments == 0 and timeline.markerPosition == 5


@pytest.mark.parametrize("mode", ["guided", "cut"])
def test_unsupported_mode_reports_the_unchanged_definition(rig, monkeypatch, mode):
    loft, timeline = rig
    read = mod._definition
    monkeypatch.setattr(mod, "_definition", lambda entity: dict(read(entity), **(
        {"guide_count": 1} if mode == "guided" else
        {"operation": adsk.fusion.FeatureOperations.CutFeatureOperation})))
    result = mod.handler(feature="Loft1", action="retarget", section_index=1, profile="X")
    assert "NEW body operation" in error_message(result)
    details = result["details"]
    assert details["mutation_attempted"] is False
    assert details["definition_before"] == details["definition_after"]
    assert details["definition_matches"] is True
    assert details["geometry_changed"] is None
    assert loft.assignments == 0 and timeline.markerPosition == 5


def test_unreadable_link_count_refuses_before_mutation(rig):
    loft, timeline = rig
    loft.objectType = adsk.fusion.LoftFeature.classType()
    loft.isParametric, loft.isSuppressed, loft.baseFeature = True, False, None
    assert "unreadable link count" in _real_target_error(loft, "Loft1")
    loft.linkedFeatures = SimpleNamespace(count=1)
    assert "linked features" in _real_target_error(loft, "Loft1")
    loft.linkedFeatures.count = 0
    assert _real_target_error(loft, "Loft1") is None
    assert loft.assignments == 0 and timeline.markerPosition == 5


def test_direction_end_weight_and_angle_retained(rig):
    loft, timeline = rig
    loft.sections[0].endCondition = SimpleNamespace(
        objectType="adsk::fusion::LoftDirectionEndCondition",
        weight=SimpleNamespace(name="StartWeight", expression="1.5", value=1.5),
        angle=SimpleNamespace(name="StartAngle", expression="5 deg", value=0.0872664626))
    result = mod.handler(feature="Loft1", action="remove", section_index=1)
    assert result["isError"] is False
    assert payload(result)["definition_matches"] is True
    assert payload(result)["definition_after"]["end_controls"] == (
        payload(result)["definition_before"]["end_controls"])
    assert timeline.markerPosition == 5


def test_changed_direction_weight_is_detected(rig, monkeypatch):
    loft, timeline = rig
    loft.sections[0].endCondition = SimpleNamespace(
        objectType="adsk::fusion::LoftDirectionEndCondition",
        weight=SimpleNamespace(name="StartWeight", expression="1.5", value=1.5),
        angle=SimpleNamespace(name="StartAngle", expression="5 deg", value=0.0872664626))
    original_setter = Section.entity.fset

    def altering_setter(section, value):
        original_setter(section, value)
        section.owner.sections[0].endCondition.weight.value = 2.0

    monkeypatch.setattr(Section, "entity", property(Section.entity.fget, altering_setter))
    result = mod.handler(feature="Loft1", action="retarget", section_index=1, profile="X")
    assert result["isError"] is True
    assert result["details"]["definition_matches"] is False
    assert timeline.markerPosition == 5


def test_unreadable_direction_angle_refuses_before_mutation(rig):
    loft, timeline = rig
    loft.sections[0].endCondition = SimpleNamespace(
        objectType="adsk::fusion::LoftDirectionEndCondition",
        weight=SimpleNamespace(name="StartWeight", expression="1.5", value=1.5))
    result = mod.handler(feature="Loft1", action="remove", section_index=1)
    assert result["isError"] is True
    assert "definition is unreadable" in error_message(result)
    assert result["details"]["definition_matches"] is None
    assert loft.assignments == 0 and timeline.markerPosition == 5


def test_ignored_retarget_is_error(rig):
    loft, timeline = rig
    loft.sections[1].mode = "ignore"
    result = mod.handler(feature="Loft1", action="retarget", section_index=1, profile="X")
    assert result["isError"] is True
    assert result["details"]["definition_matches"] is False
    assert loft.assignments == 1 and timeline.markerPosition == 5


def test_failed_delete_is_error_and_marker_restored(rig):
    loft, timeline = rig
    loft.sections[1].mode = "false"
    result = mod.handler(feature="Loft1", action="remove", section_index=1)
    assert result["isError"] is True
    assert "deleteMe()" in error_message(result)
    assert tuple(s.entity for s in loft.sections) == ("A", "B", "C")
    assert timeline.markerPosition == 5


@pytest.mark.parametrize("case", ["recovers", "diverges", "unrolled"])
def test_setter_exception_rolls_back_only_when_the_reread_proves_it(rig, monkeypatch, case):
    loft, timeline = rig
    recovers, rolls = case != "diverges", []

    def roll(_before):
        # The edit rolls twice before its setter raises; an unrolled case refuses the restore's roll.
        rolls.append(True)
        return timeline.roll() if case != "unrolled" or len(rolls) <= 2 else False
    loft.timelineObject.rollTo = roll
    sketch = Sketch(name="Middle")
    middle = SimpleNamespace(name="Middle", parentSketch=sketch)
    sketch.profiles = _NamedCollection([middle])
    loft.sections[1]._entity = middle
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: {
        "target": {"component": "Host", "body": "Target", "shape": {"volume_cm3": 1 if (
            loft.sections[1].entity is middle and (recovers or not loft.assignments)) else 2}},
        "witness": {"component": "Host", "body": "Witness", "shape": {"volume_cm3": 1}}})
    loft.sections[1].mode = "raise_after_land"
    result = mod.handler(feature="Loft1", action="retarget", section_index=1, profile="X")
    text = error_message(result)
    assert result["details"]["mutation_attempted"] is True
    assert (loft.sections[1].entity is middle) is (case != "unrolled")
    expected = {
        "recovers": ("setter raised after landing. It was rolled back and re-read: section 1 "
                     "reads sketch 'Middle' profile 0 again; the bodies match the pre-edit read."),
        "diverges": "A rollback ran but did not verify: section 1 now reads sketch 'Middle'",
        "unrolled": ("Editing 'Loft1': setter raised after landing. This STAYED APPLIED (not "
                     "rolled back): section 1 now reads unread (was sketch 'Middle' profile 0). "
                     "The feature could not be rolled to its edit position. Restore it with "
                     "model_edit_loft(feature='Loft1', action='retarget', section_index=1, "
                     "profile={'sketch': 'Middle', 'profile_index': 0}).")}[case]
    assert text == expected if case == "unrolled" else expected in text
    assert timeline.markerPosition == 5


@pytest.mark.parametrize("volume_back", [1, 3])
def test_a_restore_that_re_creates_the_body_is_rolled_back_only_at_its_prior_shape(
        rig, monkeypatch, volume_back):
    loft, _timeline = rig
    sketch = Sketch(name="Middle")
    middle = SimpleNamespace(name="Middle", parentSketch=sketch)
    sketch.profiles = _NamedCollection([middle])
    loft.sections[1]._entity = middle
    loft.sections[1].mode = "raise_after_land"
    # The second section assignment is the restore.
    monkeypatch.setattr(mod, "_all_shapes", lambda _design: {
        "body3" if loft.assignments > 1 else "target": {
            "component": "Host", "body": "Body3" if loft.assignments > 1 else "Body1",
            "shape": {"volume_cm3": volume_back if loft.assignments > 1 else
                      1 if loft.sections[1].entity is middle else 2}}})
    result = mod.handler(feature="Loft1", action="retarget", section_index=1, profile="X")
    assert error_message(result) == "Editing 'Loft1': setter raised after landing. " + {
        1: ("It was rolled back and re-read: section 1 reads sketch 'Middle' profile 0 again; the "
            "body shapes match the pre-edit read. The body now reads as 'Body3' (was "
            "'Body1'); re-read names and handles held for it."),
        3: ("A rollback ran but did not verify: section 1 now reads sketch 'Middle' profile 0 (was "
            "sketch 'Middle' profile 0). The bodies do not match the pre-edit read. Undo it in "
            "Fusion.")}[volume_back]
    assert result["details"]["rollback"]["recreated"] == (
        [{"component": "Host", "now": ["Body3"], "was": ["Body1"]}] if volume_back == 1 else [])


@pytest.mark.parametrize("lands,outcome", [
    (True, "sketch 'Middle' profile 0 (was sketch 'Middle' profile 0). The timeline health was not "
           "re-read. Undo it in Fusion."),
    (False, "sketch 'Narrow' profile 0 (was sketch 'Middle' profile 0). The definition re-read "
            "differs from before the edit; the timeline health was not re-read. Restore it with "
            "model_edit_loft(feature='Loft1', action='retarget', section_index=1, "
            "profile={'sketch': 'Middle', 'profile_index': 0}).")])
def test_a_restore_left_off_its_marker_says_health_was_not_reread(rig, monkeypatch, lands,
                                                                  outcome):
    loft, timeline = rig
    sketch, narrow_sketch = Sketch(name="Middle"), Sketch(name="Narrow")
    middle = SimpleNamespace(name="Middle", parentSketch=sketch)
    narrow = SimpleNamespace(name="Narrow", parentSketch=narrow_sketch)
    sketch.profiles, narrow_sketch.profiles = _NamedCollection([middle]), _NamedCollection([narrow])
    monkeypatch.setattr(mod._inputs.ProfileRef, "resolve",
                        lambda _self, _raw, _scope: (narrow, None))
    loft.sections[1]._entity = middle
    loft.sections[1].mode = "raise_after_land"
    original = Section.entity.fset

    def setter(section, value):
        # The second assignment is the restore; the marker then refuses to park back.
        timeline.refuse_restore = section.owner.assignments == 1
        if timeline.refuse_restore and not lands:
            section.mode = "ignore"
        original(section, value)
    monkeypatch.setattr(Section, "entity", property(Section.entity.fget, setter))
    text = error_message(mod.handler(feature="Loft1", action="retarget", section_index=1,
                                     profile="Narrow"))
    # A retarget call naming the profile the section already reads is refused, so none is offered.
    assert text == (
        "Editing 'Loft1': setter raised after landing. A rollback ran but did not verify: section 1 "
        f"now reads {outcome} Also, the timeline marker stood at 5 before the edit and reads 3 "
        "after it - roll it back with design_edit_timeline.")


def test_a_section_profile_two_profiles_answer_to_is_named_not_restored(rig, monkeypatch):
    loft, timeline = rig
    sketch = Sketch(name="Middle")
    middle = SimpleNamespace(name="Middle", parentSketch=sketch)
    twin = SimpleNamespace(name="Middle", parentSketch=sketch)
    sketch.profiles = _NamedCollection([middle, twin])
    loft.sections[1]._entity = middle
    monkeypatch.setattr(mod, "_health", lambda *_args: {
        "errors": [], "warnings": ["Dependent"] if loft.sections[1].entity == "X" else []})
    text = error_message(mod.handler(feature="Loft1", action="retarget", section_index=1,
                                     profile="X"))
    assert ("This STAYED APPLIED (not rolled back): section 1 now reads unread (was unread). "
            "Undo it in Fusion.") in text
    assert loft.sections[1].entity == "X" and loft.assignments == 1
    assert timeline.markerPosition == 5


def test_failed_removal_names_the_section_count_it_left(rig, monkeypatch):
    loft, timeline = rig
    monkeypatch.setattr(mod, "_health", lambda *_args: {
        "errors": [], "warnings": ["Dependent"] if len(loft.sections) == 2 else []})
    result = mod.handler(feature="Loft1", action="remove", section_index=1)
    assert ("This STAYED APPLIED (not rolled back): the section count now reads 2 (was 3). "
            "Rebuild it with model_loft or undo it in Fusion.") in error_message(result)
    assert len(loft.sections) == 2 and timeline.markerPosition == 5


def test_new_downstream_warning_is_error(rig, monkeypatch):
    loft, timeline = rig
    monkeypatch.setattr(mod, "_health", lambda *_args: {
        "errors": [], "warnings": ["Dependent"] if loft.sections[1].entity == "X" else []})
    result = mod.handler(feature="Loft1", action="retarget", section_index=1, profile="X")
    assert result["isError"] is True
    assert result["details"]["new_timeline_warnings"] == ["Dependent"]
    assert timeline.markerPosition == 5


@pytest.mark.parametrize("member_error", [False, True])
def test_a_collapsed_group_before_the_marker_is_read_through_its_members(rig, monkeypatch,
                                                                       member_error):
    loft, timeline = rig
    states = adsk.fusion.FeatureHealthStates
    member = FakeTimelineObject(name="Grouped", health=(
        states.ErrorFeatureHealthState if member_error else states.HealthyFeatureHealthState))
    group = FakeTimelineObject(name="Earlier", is_group=True,
                               health=states.UnknownFeatureHealthState)
    group.count, group.item = 1, lambda _i: member
    timeline._items = [group] + [FakeTimelineObject(name=f"Row{i}") for i in range(1, 5)]
    seen = []
    monkeypatch.setattr(mod, "_health", lambda design, marker: (
        seen.append(_real_health(design, marker)) or seen[-1]))
    result = mod.handler(feature="Loft1", action="retarget", section_index=1, profile="X")
    assert result["isError"] is False
    assert tuple(s.entity for s in loft.sections) == ("A", "X", "C")
    assert [str(n) for n in seen[0]["errors"]] == (["Grouped"] if member_error else [])


def test_restore_failure_is_error(rig):
    _loft, timeline = rig
    timeline.refuse_restore = True
    result = mod.handler(feature="Loft1", action="remove", section_index=1)
    assert result["isError"] is True
    assert result["details"]["marker_restored"] is False
    assert ("the timeline marker stood at 5 before the edit and reads 2 after it"
            in error_message(result))


@pytest.fixture
def surface_rig(rig, monkeypatch):
    """The rig as an open unguided surface Loft in the root component, sections labelled by name."""
    loft, timeline = rig
    loft.isSolid, loft.isClosed = False, False
    loft.centerLineOrRails = SimpleNamespace(count=0)
    mod._common.design().rootComponent = loft.parentComponent
    monkeypatch.setattr(mod, "sketch_address", lambda entity: entity)
    monkeypatch.setattr(mod, "address_text", lambda address: address)
    return loft, timeline


def test_reorder_lands_with_the_order_read_back(surface_rig):
    loft, timeline = surface_rig
    result = payload(mod.handler(feature="Loft1", action="reorder", section_index=1, new_index=0))
    assert (result["order_before"], result["order_after"]) == (["A", "B", "C"], ["B", "A", "C"])
    assert (result["edited"], result["order_matches"], result["geometry_changed"]) == (True, True, True)
    assert result["outside_body_changes"] == [] and timeline.markerPosition == 5


@pytest.mark.parametrize("mode,first", [
    ("false", "LoftSection.reorder(0) returned False."),
    ("ignore", "These checks failed: order_matches, geometry_changed.")])
def test_a_reorder_that_did_not_move_is_an_error_with_the_order_re_read(surface_rig, mode, first):
    loft, timeline = surface_rig
    loft.sections[1].mode = mode
    result = mod.handler(feature="Loft1", action="reorder", section_index=1, new_index=0)
    assert error_message(result) == (f"Editing 'Loft1': {first} Nothing changed: the section order "
                                     "still reads [A, B, C] (re-read).")
    assert result["details"]["order_after"] == ["A", "B", "C"] and loft.assignments == 1
    assert timeline.markerPosition == 5


def test_a_reorder_whose_marker_did_not_return_names_the_marker_and_the_kept_order(surface_rig):
    loft, timeline = surface_rig
    timeline.refuse_restore = True
    assert error_message(mod.handler(feature="Loft1", action="reorder", section_index=1,
                                     new_index=0)) == (
        "Editing 'Loft1': These checks failed: marker_restored, new_timeline_errors, "
        "new_timeline_warnings. This STAYED APPLIED (not rolled back): the section order now "
        "reads [B, A, C] (was [A, B, C]). Restore it with model_edit_loft(feature='Loft1', "
        "action='reorder', section_index=0, new_index=1). Also, the timeline marker stood at 5 "
        "before the edit and reads 3 after it - roll it back with design_edit_timeline.")


@pytest.mark.parametrize("new_index,landed", [(2, ["A", "C", "B"]), (3, None), (1, None)])
def test_reorder_indexes_must_differ_and_stay_below_the_section_count(surface_rig, new_index,
                                                                      landed):
    loft, timeline = surface_rig
    result = mod.handler(feature="Loft1", action="reorder", section_index=1, new_index=new_index)
    if landed:
        assert payload(result)["order_after"] == landed
    else:
        assert error_message(result) == (
            f"Editing 'Loft1': 'section_index'=1 and 'new_index'={new_index} must be two "
            "different indexes below its 3 sections. Nothing was edited.")
        assert loft.assignments == 0
    assert timeline.markerPosition == 5


def test_reorder_refuses_a_solid_loft_before_any_move(surface_rig):
    loft, timeline = surface_rig
    loft.isSolid = True
    assert error_message(mod.handler(feature="Loft1", action="reorder", section_index=1,
                                     new_index=0)) == (
        "Editing 'Loft1': It reads isSolid=True; action='reorder' takes an open, unguided surface "
        "Loft in the root component. Nothing was edited.")
    assert (loft.assignments, timeline.markerPosition) == (0, 5)


@pytest.mark.parametrize("args,text", [
    ({"action": "reorder"}, "action='reorder' takes a nonnegative integer 'new_index' (got None) "
                            "and no 'profile'."),
    ({"action": "reorder", "new_index": 0, "profile": "X"},
     "action='reorder' takes a nonnegative integer 'new_index' (got 0) and no 'profile'."),
    ({"action": "remove", "new_index": 0}, "'new_index' is unused for action='remove'; remove it.")])
def test_new_index_belongs_to_reorder_alone(surface_rig, args, text):
    loft, _timeline = surface_rig
    assert error_message(mod.handler(feature="Loft1", section_index=1, **args)) == text
    assert loft.assignments == 0


edit = load_tool("_edit_feature_common")


@pytest.mark.parametrize("marker,expected", [(1, False), (2, True), (3, False),
                                            (True, False), (2.0, False)])
def test_edit_position_requires_the_exact_integer_row(marker, expected):
    timeline = FakeTimeline([None] * 4, marker=marker)
    assert edit.edit_position(True, timeline, 2) is expected



@pytest.mark.parametrize("returned", [False, None, 1])
def test_edit_position_requires_literal_true_and_skips_marker_on_refusal(monkeypatch, returned):
    monkeypatch.setattr(edit, "counted", lambda _getter: pytest.fail("marker read after refusal"))
    assert edit.edit_position(returned, FakeTimeline(marker=2), 2) is False



def test_edit_position_refuses_an_unread_marker():
    timeline = FakeTimeline([None] * 4, marker=2, raises="injected marker failure")
    assert edit.edit_position(True, timeline, 2) is False



@pytest.mark.parametrize("returned", [True, False, 1])
def test_roll_to_edit_calls_before_once_and_preserves_the_result(returned):
    row = FakeTimelineObject(index=2, roll_ok=returned)
    assert edit.roll_to_edit(SimpleNamespace(timelineObject=row), FakeTimeline(marker=2), 2) is (
        returned is True)
    assert row._rolls == [True]



def test_roll_to_edit_leaves_the_roll_exception_to_its_caller(monkeypatch):
    row = FakeTimelineObject(index=2)
    failure = RuntimeError("injected roll failure")
    def raised(_before):
        raise failure
    monkeypatch.setattr(row, "rollTo", raised)
    with pytest.raises(RuntimeError, match="injected roll failure") as caught:
        edit.roll_to_edit(SimpleNamespace(timelineObject=row), FakeTimeline(marker=2), 2)
    assert caught.value is failure



@pytest.mark.parametrize("mode", ["false", "truthy", "noop", "raise"])
def test_loft_roll_refusal_keeps_words_assignments_and_restore(rig, monkeypatch, mode):
    loft, timeline = rig
    monkeypatch.setattr(loft.timelineObject, "rollTo", _injected_roll(timeline, 2, mode))
    text = error_message(mod.handler(feature="Loft1", action="retarget", section_index=1,
                                          profile="X"))
    why = "injected roll failure" if mode == "raise" else "Fusion refused the Loft edit position."
    assert why in text
    assert (loft.assignments, timeline.markerPosition) == (0, 5)
    assert tuple(section.entity for section in loft.sections) == ("A", "B", "C")
