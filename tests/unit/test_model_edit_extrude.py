"""Checks for silent edits, partial failures and timeline restoration."""

from types import SimpleNamespace

import pytest
import adsk.core
import adsk.fusion

from conftest import (BRepBody, BRepFace, FakeFeature, FakeModelParameter, FakeTimeline,
                      FakeTimelineObject, FakeValueInput, MakeComp, Profile, Sketch,
                      _FakeObjectCollection, _NamedCollection, error_message,
                      install, load_tool, make_bbox, make_design, payload)


mod = load_tool("model_edit_extrude")
_DISTANCE = "adsk::fusion::DistanceExtentDefinition"


class Distance(FakeModelParameter):
    """A one-sided distance parameter whose expression write re-evaluates its feature."""

    def __init__(self, feature, **kw):
        super().__init__(tracks_expression=True, **kw)
        self.feature = feature

    @FakeModelParameter.expression.setter
    def expression(self, text):
        FakeModelParameter.expression.fset(self, text)
        self.feature.reshape()


class Extrude(FakeFeature):
    """Extrude-specific setters have no shared measured shape fake."""

    def __init__(self, component, body):
        super().__init__(parent_component=component, bodies=[body], entity_token="extrude-token")
        self.objectType = "adsk::fusion::ExtrudeFeature"
        self.isParametric = self.isSolid = self.isValid = True
        self.isThinExtrude = False
        self.baseFeature = None
        self.linkedFeatures = _NamedCollection([])
        self._profile = None
        self.profile_x = {}
        self.mode = "change"
        self.assignments = 0
        self.after_edit = lambda: None
        self.operation = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        self._participants = []
        self.fail_participants = False
        self.param = Distance(self, name="d7", expression="10 mm", value=1.0)
        self.extentOne = SimpleNamespace(objectType=_DISTANCE, distance=self.param)
        self.extentTwo = None
        self.hasTwoExtents = False
        self.taperAngleOne = SimpleNamespace(value=0)
        self.taperAngleTwo = SimpleNamespace(value=0)
        self.startExtent = SimpleNamespace(objectType="adsk::fusion::ProfilePlaneStartDefinition")
        self.start_setter_ok = True
        self.setter_ok = True
        self.setter_args = None

    @property
    def participantBodies(self):
        return self._participants

    @participantBodies.setter
    def participantBodies(self, bodies):
        if self.fail_participants:
            raise RuntimeError("participant setter refused")
        self._participants = bodies
        self.bodies.item(0).volume = 0.5

    def reshape(self):
        """Place the body from the current profile and the signed one-sided distance."""
        depth = self.param.value
        start = (self.startExtent.offset.value if self.startExtent.objectType in (
            "adsk::fusion::OffsetStartDefinition", "adsk::fusion::FromEntityStartDefinition") else 0)
        x = self.profile_x.get(id(self._profile), 2)
        body = self.bodies.item(0)
        body.boundingBox = make_bbox((x, 0, start + min(0, depth)),
                                     (x + 1, 1, start + max(0, depth)))
        body.volume = abs(depth)
        self.after_edit()

    @property
    def startExtent(self):
        return self._start_extent

    @startExtent.setter
    def startExtent(self, value):
        if getattr(self, "start_setter_ok", True):
            if isinstance(getattr(value, "offset", None), FakeValueInput):
                value.offset = FakeModelParameter(value=value.offset.realValue)
            self._start_extent = value
            if getattr(self, "_profile", None) is not None:
                self.reshape()

    def setOneSideExtent(self, extent, direction, taper):
        self.setter_args = extent, direction, taper
        if self.setter_ok:
            self.extentTwo = None
            self.hasTwoExtents = False
            self.bodies.item(0).volume = 0.5
            distance = extent.objectType == _DISTANCE
            if distance:
                # Over a distance extent the setter keeps its parameter's name (measured); from
                # another kind that is unmeasured, so this mints a new one no test can lean on.
                if self.extentOne.objectType != _DISTANCE:
                    self.param = Distance(self, name="d9", expression="0 mm", value=0.0)
                self.param.value = extent.distance.value
                self.param._expression = f"{extent.distance.value * 10} mm"
                extent = SimpleNamespace(objectType=_DISTANCE, distance=self.param)
            self.extentOne = extent
            if distance:
                self.reshape()
        return self.setter_ok

    def setSymmetricExtent(self, distance, full, taper):
        self.setter_args = distance, full, taper
        if self.setter_ok:
            self.extentOne = SimpleNamespace(objectType="adsk::fusion::SymmetricExtentDefinition",
                distance=SimpleNamespace(value=distance.realValue), isFullLength=full)
            self.symmetricExtent = self.extentOne
            self.hasTwoExtents = False
            self.bodies.item(0).volume = 2 * distance.realValue
        return self.setter_ok

    def setTwoSidesExtent(self, one, two, taper_one, taper_two):
        self.setter_args = one, two, taper_one, taper_two
        if self.setter_ok:
            self.extentOne, self.extentTwo = one, two
            self.hasTwoExtents = True
            self.bodies.item(0).volume = 2
        return self.setter_ok

    @property
    def profile(self):
        return self._profile

    @profile.setter
    def profile(self, value):
        self.assignments += 1
        if self.mode == "noop":
            return
        if self.mode == "raise_before":
            raise RuntimeError("profile setter refused")
        self._profile = value
        self.reshape()
        if self.mode == "raise_after" and self.assignments == 1:
            raise RuntimeError("profile setter failed after changing")


@pytest.fixture
def scene(monkeypatch):
    monkeypatch.setattr(adsk.fusion, "Profile", Profile)
    monkeypatch.setattr(adsk.core.ValueInput, "createByReal", FakeValueInput)
    monkeypatch.setattr(adsk.core.ValueInput, "createByString", lambda value: FakeValueInput(0))
    monkeypatch.setattr(adsk.core.ValueInput, "cast", staticmethod(
        lambda value: value if isinstance(value, FakeValueInput) else None))
    monkeypatch.setattr(adsk.fusion.ModelParameter, "cast", staticmethod(
        lambda value: value if isinstance(value, FakeModelParameter) else None))
    monkeypatch.setattr(adsk.fusion.DistanceExtentDefinition, "create", lambda value:
        SimpleNamespace(objectType="adsk::fusion::DistanceExtentDefinition",
                        distance=SimpleNamespace(value=value.realValue)))
    monkeypatch.setattr(adsk.fusion.ThroughAllExtentDefinition, "create", lambda:
        SimpleNamespace(objectType="adsk::fusion::ThroughAllExtentDefinition",
                        isPositiveDirection=True))
    component = MakeComp(name="Part", entity_token="part-token")
    body = BRepBody("Body1", volume=1, area=6, bbox=make_bbox((0, 0, 0), (1, 1, 1)),
                    parent_component=component)
    component.bRepBodies = _NamedCollection([body])
    body.isValid = True
    body.physicalProperties = SimpleNamespace(centerOfMass=SimpleNamespace(x=0.5, y=0.5, z=0.5))
    body.faces = _NamedCollection([BRepFace(None, area=1, centroid=SimpleNamespace(x=x, y=y, z=z))
                                  for x, y, z in ((0, .5, .5), (1, .5, .5), (.5, 0, .5),
                                                  (.5, 1, .5), (.5, .5, 0), (.5, .5, 1))])
    monkeypatch.setattr(adsk.fusion, "BRepBody", BRepBody)
    feature = Extrude(component, body)
    sketches = [Sketch(name=name, parent_component=component)
                for name in ("Original", "Replacement")]
    profiles = [Profile(entity_token=f"profile-{i}", parent_sketch=s)
                for i, s in enumerate(sketches)]
    for sketch, profile in zip(sketches, profiles):
        sketch.profiles = _NamedCollection([profile])
        profile.isValid = True
        profile.assemblyContext = None
    feature._profile = profiles[0]
    feature.profile_x = {id(profiles[0]): 0}
    rows = [FakeTimelineObject(name=s.name, index=i, entity=s)
            for i, s in enumerate(sketches)]
    rows += [FakeTimelineObject(name=feature.name, index=2, entity=feature),
             FakeTimelineObject(name="Trailing", index=3)]
    timeline = FakeTimeline(rows, marker=3)
    feature.timelineObject = rows[2]
    for i, sketch in enumerate(sketches):
        sketch.timelineObject = rows[i]
    monkeypatch.setattr(rows[2], "rollTo", lambda before: timeline._move(2 if before else 3))
    monkeypatch.setattr(adsk.fusion.ExtrudeFeature, "classType",
                        lambda: "adsk::fusion::ExtrudeFeature")
    design = make_design(comp=component,
                         tokens={"extrude-token": feature, "profile-1": profiles[1]})
    design.timeline = timeline
    install(mod, design)
    return SimpleNamespace(feature=feature, body=body, timeline=timeline, design=design,
                           profiles=profiles, rows=rows, component=component)


def edit():
    return mod.handler(feature="Extrude1", action="profile", profile="profile-1")


def test_equal_volume_profile_shift_and_parked_marker(scene):
    result = payload(edit())
    assert result["edited"] is True
    assert result["geometry_before"][0][0] == result["geometry_after"][0][0] == 1
    assert result["geometry_after"][0][2:4] == [2, 3]
    assert result["same_feature"] is True
    assert "mass properties stale" not in result["note"]
    assert scene.timeline.markerPosition == 3
    assert scene.timeline.count == 4


def test_offset_start_moves_body_and_preserves_feature(scene, monkeypatch):
    monkeypatch.setattr(adsk.fusion.OffsetStartDefinition, "create", lambda value:
        SimpleNamespace(objectType="adsk::fusion::OffsetStartDefinition",
                        offset=value))
    result = payload(mod.handler(feature="Extrude1", action="start", start_offset=5))
    assert result["edited"] is True
    assert result["definition_matches"] is True
    assert result["same_feature"] is True
    assert result["definition_before"]["start_kind"] == "adsk::fusion::ProfilePlaneStartDefinition"
    assert result["definition_after"]["start_offset_cm"] == pytest.approx(0.5)
    assert result["geometry_after"][0][6:8] == [0.5, 1.5]
    assert scene.timeline.markerPosition == 3


def test_from_plane_start_checks_selected_entity(scene, monkeypatch):
    plane = SimpleNamespace(entityToken="plane-token", name="XY", component=scene.component,
                            isValid=True, assemblyContext=None)
    monkeypatch.setattr(mod._START_OBJECT, "resolve", lambda raw, component=None: (plane, None))
    monkeypatch.setattr(adsk.fusion.FromEntityStartDefinition, "create", lambda entity, offset:
        SimpleNamespace(objectType="adsk::fusion::FromEntityStartDefinition", entity=entity,
                        offset=offset))
    result = payload(mod.handler(feature="Extrude1", action="start", start_object="xy",
                                 start_offset=8))
    assert result["definition_matches"] is True
    assert result["definition_after"]["start_entity"] == ["plane-token", None]
    assert result["geometry_after"][0][6:8] == [0.8, 1.8]


def test_from_plane_start_refuses_foreign_component_before_roll(scene, monkeypatch):
    foreign = MakeComp(name="Other", entity_token="other-token")
    plane = SimpleNamespace(entityToken="foreign-plane", component=foreign,
                            isValid=True, assemblyContext=None)
    monkeypatch.setattr(mod._START_OBJECT, "resolve", lambda raw, component=None: (plane, None))
    result = mod.handler(feature="Extrude1", action="start", start_object="xy", start_offset=8)
    assert "does not belong" in error_message(result)
    assert scene.timeline._moves == []
    assert scene.feature.startExtent.objectType == "adsk::fusion::ProfilePlaneStartDefinition"
    assert scene.body.volume == 1


def test_from_entity_start_refuses_wrong_landed_entity(scene, monkeypatch):
    wanted = SimpleNamespace(entityToken="wanted-plane", parentComponent=scene.component,
                             isValid=True, assemblyContext=None)
    wrong = SimpleNamespace(entityToken="wrong-plane", parentComponent=scene.component,
                            isValid=True, assemblyContext=None)
    monkeypatch.setattr(mod._START_OBJECT, "resolve", lambda raw, component=None: (wanted, None))
    monkeypatch.setattr(adsk.fusion.FromEntityStartDefinition, "create", lambda entity, offset:
        SimpleNamespace(objectType="adsk::fusion::FromEntityStartDefinition", entity=wrong,
                        offset=offset))
    result = mod.handler(feature="Extrude1", action="start", start_object="xy", start_offset=8)
    assert result["isError"] is True
    assert result["details"]["definition_matches"] is False
    assert result["details"]["geometry_changed"] is True
    assert result["details"]["definition_after"]["start_entity"] == ("wrong-plane", None)


def test_silent_start_setter_is_error(scene, monkeypatch):
    scene.feature.start_setter_ok = False
    monkeypatch.setattr(adsk.fusion.OffsetStartDefinition, "create", lambda value:
        SimpleNamespace(objectType="adsk::fusion::OffsetStartDefinition",
                        offset=value))
    result = mod.handler(feature="Extrude1", action="start", start_offset=5)
    assert result["isError"] is True
    assert result["details"]["definition_matches"] is False
    assert result["details"]["geometry_changed"] is False
    assert scene.timeline.markerPosition == 3


@pytest.mark.parametrize("operation", [
    adsk.fusion.FeatureOperations.CutFeatureOperation,
    adsk.fusion.FeatureOperations.IntersectFeatureOperation,
])
def test_start_refuses_two_sided_through_all_scope_before_roll(scene, operation):
    scene.feature.operation = operation
    scene.feature.hasTwoExtents = True
    scene.feature.extentOne = adsk.fusion.ThroughAllExtentDefinition.create()
    scene.feature.extentTwo = adsk.fusion.ThroughAllExtentDefinition.create()
    result = mod.handler(feature="Extrude1", action="start", start_offset=5)
    assert "Two-sided through_all with cut/intersect" in error_message(result)
    assert scene.timeline._moves == []
    assert scene.feature.startExtent.objectType == "adsk::fusion::ProfilePlaneStartDefinition"
    assert scene.feature.participantBodies == []
    assert scene.body.volume == 1


def test_silent_profile_setter_is_an_error(scene):
    scene.feature.mode = "noop"
    result = edit()
    assert result["isError"] is True
    assert result["details"]["definition_matches"] is False
    assert result["details"]["geometry_changed"] is False
    assert "Fusion kept the prior definition. Nothing changed" in error_message(result)
    assert scene.timeline.markerPosition == 3


@pytest.mark.parametrize("mode,outcome", [
    ("raise_before", "Nothing changed: profile still reads sketch 'Original' profile 0 (re-read)."),
    ("raise_after", "It was rolled back and re-read: profile reads sketch 'Original' profile 0 again"),
])
def test_setter_exception_says_what_the_reread_shows(scene, mode, outcome):
    scene.feature.mode = mode
    result = edit()
    assert "profile setter" in error_message(result)
    assert outcome in error_message(result)
    assert result["details"]["mutation_attempted"] is True
    assert scene.feature.profile is scene.profiles[0]
    assert scene.timeline.markerPosition == 3


def test_a_refused_setter_that_moved_the_body_is_unconfirmed(scene, monkeypatch):
    def move_then_refuse(feature, value):
        scene.body.boundingBox = make_bbox((5, 0, 0), (6, 1, 1))
        raise RuntimeError("profile setter refused")
    monkeypatch.setattr(Extrude, "profile", property(Extrude.profile.fget, move_then_refuse))
    result = edit()
    text = error_message(result)
    assert result["details"]["definition_after"] == result["details"]["definition_before"]
    assert result["details"]["geometry_changed"] is True
    assert "Whether 'Extrude1' changed is UNCONFIRMED" in text
    assert "geometry_changed=True" in text
    assert "Nothing changed" not in text


def test_an_unreadable_health_census_is_refused_before_the_write(scene):
    scene.rows[1].healthState = None
    result = edit()
    assert error_message(result) == ("'Extrude1's evaluated-health census is unreadable; nothing "
                                     "was edited.")
    assert "details" not in result
    assert scene.feature.assignments == 0
    assert scene.timeline._moves == []


def _negative(scene):
    """Put the feature at a measured -42 mm one-sided distance."""
    scene.feature.param.expression = "-42 mm"


@pytest.mark.parametrize("action", ["profile", "extent"])
def test_failure_after_the_write_rolls_back_when_the_reread_proves_it(scene, action):
    states = adsk.fusion.FeatureHealthStates
    scene.timeline.markerPosition = 4
    if action == "profile":
        broken = lambda: scene.feature.profile is scene.profiles[1]
        again = "profile reads sketch 'Original' profile 0 again"
        args = {"action": "profile", "profile": "profile-1"}
    else:
        _negative(scene)
        broken = lambda: scene.feature.param.value > 0
        again = "extent reads distance -42.0 mm again; distance parameter reads d7 = -42 mm again"
        args = {"action": "extent", "extent": "distance", "distance": 56, "direction": "positive"}
    scene.feature.after_edit = lambda: setattr(scene.rows[3], "healthState", (
        states.WarningFeatureHealthState if broken() else states.HealthyFeatureHealthState))
    result = mod.handler(feature="Extrude1", **args)
    assert f"It was rolled back and re-read: {again}; the bodies match" in error_message(result)
    assert result["details"]["rollback"]["verified"] is True
    assert broken() is False
    assert scene.feature.param.expression == ("10 mm" if action == "profile" else "-42 mm")
    assert scene.timeline.markerPosition == 4


def test_restore_that_does_not_verify_names_the_state_it_left(scene):
    scene.timeline.markerPosition = 4
    scene.feature.after_edit = lambda: setattr(
        scene.rows[3], "healthState", adsk.fusion.FeatureHealthStates.WarningFeatureHealthState)
    text = error_message(edit())
    assert "A rollback ran but did not verify" in text
    assert "timeline health does not match" in text
    assert "rolled back and re-read" not in text
    # The profile re-reads as before, so a profile call would meet the already-uses refusal.
    assert text.endswith("before the edit. Undo it in Fusion.")


def test_a_restore_that_cannot_roll_names_the_kept_state(scene, monkeypatch):
    rolls = []
    monkeypatch.setattr(scene.rows[2], "rollTo", lambda before: (
        rolls.append(before) or len(rolls) == 1) and scene.timeline._move(2))
    scene.timeline.markerPosition = 4
    scene.feature.after_edit = lambda: setattr(
        scene.rows[3], "healthState", adsk.fusion.FeatureHealthStates.WarningFeatureHealthState)
    text = error_message(edit())
    assert text == ("Editing 'Extrude1': The definition landed but introduced downstream errors or "
                    "warnings. This STAYED APPLIED (not rolled back): profile now reads sketch "
                    "'Replacement' profile 0 (was sketch 'Original' profile 0). The feature could not "
                    "be rolled to its edit position. Restore it with model_edit_extrude(feature="
                    "'Extrude1', action='profile', profile={'sketch': 'Original', 'profile_index': "
                    "0}).")
    assert scene.feature.profile is scene.profiles[1]


def test_a_restore_whose_definition_rereads_differently_is_not_rolled_back(scene):
    states = adsk.fusion.FeatureHealthStates
    scene.timeline.markerPosition = 4
    _negative(scene)

    def after_edit():
        flipped = scene.feature.param.value > 0
        scene.rows[3].healthState = (states.WarningFeatureHealthState if flipped
                                     else states.HealthyFeatureHealthState)
        if not flipped:
            scene.feature.param.name = "d8"
    scene.feature.after_edit = after_edit
    result = mod.handler(feature="Extrude1", action="extent", extent="distance", distance=56,
                         direction="positive")
    text = error_message(result)
    assert text.endswith(
        "A rollback ran but did not verify: distance parameter now reads d8 = -42 mm (was d7 = "
        "-42 mm). The definition re-read differs from before the edit. No tool call restores the "
        "distance parameter's name. Undo it in Fusion.")
    assert result["details"]["rollback"]["verified"] is False
    assert scene.body.boundingBox.minPoint.z == pytest.approx(-4.2)
    # The extent already reads -42 mm, so an extent call is refused rather than acting.
    again = mod.handler(feature="Extrude1", action="extent", extent="distance", distance=42.0,
                        direction="negative")
    assert "The feature already has that definition. Nothing was edited." in error_message(again)


def test_a_to_face_remedy_survives_a_face_change_its_text_cannot_show():
    prior = {"extent": "to_face", "side": None}
    assert mod._remedy("Extrude1", "extent", prior, dict(prior)) == (
        "Restore it with model_edit_extrude(feature='Extrude1', action='extent', extent='to_face', "
        "to_object=<find_geometry face handle>) or undo it in Fusion.")


def test_marker_restore_failure_is_reported_beside_the_edit_failure(scene, monkeypatch):
    def marker_set(timeline, value):
        if value == 3:
            raise RuntimeError("marker restore refused")
        timeline._marker = value
    monkeypatch.setattr(FakeTimeline, "markerPosition",
                        property(lambda t: t._marker, marker_set))
    scene.feature.mode = "raise_before"
    text = error_message(edit())
    assert "profile setter refused" in text
    assert "the timeline marker stood at 3 before the edit and reads 2 after it" in text


@pytest.mark.parametrize("start,direction,landed", [
    (-4.2, None, -5.6), (-4.2, "positive", 5.6), (1.0, "negative", -5.6)])
def test_distance_edit_keeps_the_side_unless_direction_names_one(scene, start, direction, landed):
    if start < 0:
        _negative(scene)
    args = {"direction": direction} if direction else {}
    result = payload(mod.handler(feature="Extrude1", action="extent", extent="distance",
                                 distance=56, **args))
    assert result["edited"] is True
    assert result["definition_before"]["distance_cm"] == pytest.approx(start)
    assert result["definition_after"]["distance_cm"] == pytest.approx(landed)
    assert result["definition_after"]["side"] == ("negative" if landed < 0 else "positive")
    assert result["definition_after"]["distance_parameter"] == "d7"
    assert (scene.feature.setter_args is None) is (landed < 0)
    assert scene.body.boundingBox.minPoint.z == pytest.approx(min(0, landed))
    assert ("kept the feature's negative side" in result["note"]) is (direction is None)


def test_a_distance_edit_keeps_the_side_of_a_one_sided_through_all(scene):
    scene.feature.extentOne = SimpleNamespace(
        objectType="adsk::fusion::ThroughAllExtentDefinition", isPositiveDirection=False)
    result = payload(mod.handler(feature="Extrude1", action="extent", extent="distance",
                                 distance=56))
    assert result["definition_before"]["side"] == "negative"
    assert result["definition_after"]["side"] == "negative"
    assert result["definition_after"]["distance_cm"] == pytest.approx(-5.6)
    assert ("The distance kept the feature's negative side; pass direction='positive' to flip it."
            in result["note"])


def test_a_distance_edit_of_a_two_sided_through_all_without_direction_names_its_side(scene):
    through = lambda: SimpleNamespace(objectType="adsk::fusion::ThroughAllExtentDefinition",
                                      isPositiveDirection=True)
    scene.feature.extentOne, scene.feature.extentTwo = through(), through()
    scene.feature.hasTwoExtents = True
    result = payload(mod.handler(feature="Extrude1", action="extent", extent="distance",
                                 distance=56))
    assert result["definition_before"]["side"] == "both"
    assert result["definition_after"]["side"] == "positive"
    assert result["definition_after"]["distance_cm"] == pytest.approx(5.6)
    assert ("With no direction and a prior through_all extent, the distance reads positive; "
            "pass 'direction' to choose." in result["note"])


@pytest.mark.parametrize("args,refusal", [
    ({"direction": "both"},
     "direction='both' does not set one side for extent='distance'; pass 'positive' or 'negative'."),
    ({}, "The feature's current side is unreadable; pass direction 'positive' or 'negative'."),
])
def test_a_distance_edit_without_one_readable_side_is_refused(scene, args, refusal):
    if not args:
        scene.feature.extentOne = SimpleNamespace(
            objectType="adsk::fusion::ThroughAllExtentDefinition")
    result = mod.handler(feature="Extrude1", action="extent", extent="distance", distance=56,
                         **args)
    assert error_message(result) == refusal
    assert scene.feature.setter_args is None
    assert scene.timeline._moves == []


def test_identical_distance_edit_changes_nothing(scene):
    result = mod.handler(feature="Extrude1", action="extent", extent="distance", distance=10)
    assert "The feature already has that definition. Nothing was edited." in error_message(result)
    assert result["details"]["mutation_attempted"] is False
    assert scene.feature.setter_args is None


def test_marker_restoration_failure_is_not_success(scene, monkeypatch):
    def marker_set(timeline, value):
        if value == 3:
            raise RuntimeError("marker restore refused")
        timeline._marker = value
    monkeypatch.setattr(FakeTimeline, "markerPosition",
                        property(lambda t: t._marker, marker_set))
    result = edit()
    assert result["isError"] is True
    assert result["details"]["definition_matches"] is True
    assert result["details"]["marker_restored"] is False
    assert result["details"]["geometry_changed"] is None


def test_new_downstream_error_is_reported_as_partial_edit(scene):
    scene.timeline.markerPosition = 4
    def break_trailing():
        scene.rows[3].healthState = adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState
    scene.feature.after_edit = break_trailing
    result = edit()
    assert result["isError"] is True
    assert result["details"]["definition_matches"] is True
    assert result["details"]["new_timeline_errors"] == ["Trailing"]


def test_a_downstream_collapsed_group_member_error_is_a_new_error(scene):
    states = adsk.fusion.FeatureHealthStates
    member = FakeTimelineObject(name="Grouped")
    group = FakeTimelineObject(name="LaterGroup", index=3, is_group=True,
                               health=states.UnknownFeatureHealthState)
    group.isCollapsed, group.count, group.item = True, 1, lambda _i: member
    scene.timeline._items[3] = group
    scene.timeline.markerPosition = 4
    scene.feature.after_edit = lambda: setattr(member, "healthState", states.ErrorFeatureHealthState)
    result = edit()
    assert result["isError"] is True
    assert result["details"]["new_timeline_errors"] == ["Grouped"]


def test_preexisting_error_is_not_new(scene):
    scene.timeline.markerPosition = 4
    scene.rows[3].healthState = adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState
    result = payload(edit())
    assert result["new_timeline_errors"] == []


def test_new_downstream_warning_reports_landed_partial_edit(scene):
    scene.timeline.markerPosition = 4
    def warn_trailing():
        scene.rows[3].healthState = adsk.fusion.FeatureHealthStates.WarningFeatureHealthState
    scene.feature.after_edit = warn_trailing
    result = edit()
    assert result["isError"] is True
    assert "definition landed" in error_message(result)
    assert result["details"]["new_timeline_warnings"] == ["Trailing"]
    assert result["details"]["definition_matches"] is True
    assert scene.timeline.markerPosition == 4


def test_preexisting_warning_is_not_new(scene):
    scene.timeline.markerPosition = 4
    scene.rows[3].healthState = adsk.fusion.FeatureHealthStates.WarningFeatureHealthState
    result = payload(edit())
    assert result["new_timeline_warnings"] == []


def test_later_profile_is_refused_before_roll(scene):
    scene.profiles[1].parentSketch.timelineObject.index = 3
    result = edit()
    assert error_message(result) == (
        "Editing 'Extrude1': sketch 'Replacement' is at timeline row 3, after 'Extrude1' at row 2. "
        "Move it first with design_edit_timeline(action='reorder', feature='Replacement@3', "
        "to='before', end_feature='Extrude1@2'), then retry. Nothing was edited.")
    assert scene.feature.assignments == 0
    assert scene.timeline._moves == []


class _RaisingRow(FakeTimelineObject):
    """A timeline row whose index read raises."""
    @property
    def index(self):
        raise RuntimeError("2 : InternalValidationError : res >= 0")

    @index.setter
    def index(self, _value):
        pass


def test_an_unreadable_profile_sketch_row_is_refused_before_roll(scene, monkeypatch):
    monkeypatch.setattr(scene.profiles[1].parentSketch, "timelineObject", _RaisingRow())
    result = edit()
    assert error_message(result) == ("The profile sketch 'Replacement' has an unreadable timeline row. Read "
                                     "design_get(include=['timeline']) before retrying; nothing "
                                     "was edited.")
    assert scene.feature.assignments == 0
    assert scene.timeline._moves == []


def _collapsed(name, sketch):
    """A collapsed timeline group whose one member row wraps `sketch`."""
    member = FakeTimelineObject(name=sketch.name, entity=sketch)
    group = FakeTimelineObject(name=name, is_group=True)
    group.isCollapsed, group.count, group.item = True, 1, lambda _i: member
    return group


@pytest.mark.parametrize("tokens,named", [
    (True, "'Replacement' is inside the collapsed timeline group 'AGroup'"),
    (False, "collapsed timeline groups 'BGroup', 'AGroup', and which one holds it could not be "
            "told apart"),
])
def test_a_grouped_profile_sketch_is_placed_by_identity_not_by_its_shared_name(
        scene, monkeypatch, tokens, named):
    own = scene.profiles[1].parentSketch
    namesake = Sketch(name="Replacement", parent_component=MakeComp(name="Other"))
    if tokens:
        monkeypatch.setattr(own, "entityToken", "own-sketch", raising=False)
        monkeypatch.setattr(namesake, "entityToken", "namesake-sketch", raising=False)
    monkeypatch.setattr(own, "timelineObject", _RaisingRow())
    scene.timeline.timelineGroups = _NamedCollection([_collapsed_unread("Imports", True, "Other"),
                                                      _collapsed("BGroup", namesake),
                                                      _collapsed("AGroup", own)])
    message = error_message(edit())
    assert named in message and "The profile sketch timeline row does not read" in message
    assert ("feature='BGroup'" in message) is False and "Imports" not in message
    assert scene.feature.assignments == 0 and scene.timeline._moves == []


class _UnreadEntityRow(FakeTimelineObject):
    """A timeline row whose entity read raises."""
    @property
    def entity(self):
        raise RuntimeError("3 : entity unavailable")

    @entity.setter
    def entity(self, _value):
        pass


def _collapsed_unread(name, raising, member_name="Replacement"):
    """A collapsed timeline group whose one member's entity does not read."""
    member = (_UnreadEntityRow(name=member_name) if raising
              else FakeTimelineObject(name=member_name, entity=None))
    group = FakeTimelineObject(name=name, is_group=True)
    group.isCollapsed, group.count, group.item = True, 1, lambda _i: member
    return group


@pytest.mark.parametrize("groups,named", [
    (("AGroup",), "'Replacement' names an item inside the collapsed timeline group 'AGroup', which "
                  "the timeline lists as one item. Run design_edit_timeline(action='ungroup', "
                  "feature='AGroup')"),
    (("BGroup", "AGroup"), "collapsed timeline groups 'BGroup', 'AGroup', and which one holds it "
                           "could not be told apart"),
])
def test_a_grouped_profile_sketch_whose_group_members_do_not_read_names_each_namesake_group(
        scene, monkeypatch, groups, named):
    own = scene.profiles[1].parentSketch
    monkeypatch.setattr(own, "entityToken", "own-sketch", raising=False)
    monkeypatch.setattr(own, "timelineObject", _RaisingRow())
    scene.timeline.timelineGroups = _NamedCollection(
        [_collapsed_unread("Imports", True, "Other")]
        + [_collapsed_unread(g, raising=i == 0) for i, g in enumerate(groups)])
    message = error_message(edit())
    assert named in message and "The profile sketch timeline row does not read" in message
    assert "Imports" not in message
    assert scene.feature.assignments == 0 and scene.timeline._moves == []


@pytest.mark.parametrize("state", [False, None])
def test_a_namesake_group_not_read_as_collapsed_is_not_named(state):
    own = Sketch(name="Replacement", parent_component=MakeComp(name="Own"))
    own.entityToken = "own-sketch"
    group = _collapsed_unread("Expanded", True)
    group.isCollapsed = state
    timeline = SimpleNamespace(timelineGroups=_NamedCollection([group]))
    assert mod._design_common.collapsed_group_hint_for(timeline, own, "Replacement") is None


def test_an_item_without_identity_beside_a_readable_namesake_member_is_unproven():
    own = Sketch(name="Replacement", parent_component=MakeComp(name="Own"))
    namesake = Sketch(name="Replacement", parent_component=MakeComp(name="Other"))
    namesake.entityToken = "namesake-sketch"
    timeline = SimpleNamespace(timelineGroups=_NamedCollection([_collapsed("AGroup", namesake)]))
    hint = mod._design_common.collapsed_group_hint_for(timeline, own, "Replacement")
    assert hint == ("'Replacement' names an item inside the collapsed timeline group 'AGroup', "
                    "which the timeline lists as one item. Run design_edit_timeline("
                    "action='ungroup', feature='AGroup') - its items are kept - then retry.")


def test_an_unnamed_item_found_by_identity_is_not_quoted_as_a_name():
    own = Sketch(name="Replacement", parent_component=MakeComp(name="Own"))
    own.entityToken = "own-sketch"
    timeline = SimpleNamespace(timelineGroups=_NamedCollection([_collapsed("AGroup", own)]))
    hint = mod._design_common.collapsed_group_hint_for(timeline, own, None)
    assert hint.startswith("The item is inside the collapsed timeline group 'AGroup'")


def test_same_count_replacement_is_not_same_feature(scene, monkeypatch):
    original_find = scene.design.findEntityByToken
    monkeypatch.setattr(scene.design, "findEntityByToken",
                        lambda token: [] if token == "extrude-token" else original_find(token))
    result = edit()
    assert result["isError"] is True
    assert result["details"]["same_feature"] is False


def test_a_landed_profile_with_identical_geometry_succeeds_and_says_so(scene, monkeypatch):
    monkeypatch.setattr(scene.feature, "after_edit", lambda: setattr(
        scene.body, "boundingBox", make_bbox((0, 0, 0), (1, 1, 1))))
    result = payload(edit())
    assert (result["edited"], result["definition_matches"], result["geometry_changed"]) == (
        True, True, False)
    assert result["note"].startswith("Definition changed on the same Extrude.")
    assert result["note"].endswith(" The body geometry reads identical before and after.")
    assert "rolled back" not in result["note"] and "rollback" not in result
    assert scene.feature.profile is scene.profiles[1]


def test_operation_cut_requires_explicit_participants(scene):
    result = mod.handler(feature="Extrude1", action="operation", operation="cut")
    assert "requires explicit" in error_message(result)
    assert scene.timeline._moves == []


def test_operation_reports_partial_when_participant_setter_fails(scene):
    scene.feature.fail_participants = True
    result = mod.handler(feature="Extrude1", action="operation", operation="cut",
                         target_bodies=["Body1"])
    assert result["isError"] is True
    assert result["details"]["definition_after"]["operation"] == "cut"
    assert result["details"]["definition_matches"] is False
    assert "participant setter refused" in error_message(result)
    assert ("This STAYED APPLIED (not rolled back): operation now reads cut (was new). Restore it "
            "with model_edit_extrude(feature='Extrude1', action='operation', operation='new')."
            in error_message(result))
    assert scene.timeline.markerPosition == 3


def test_operation_sets_requested_participants(scene):
    result = payload(mod.handler(feature="Extrude1", action="operation", operation="cut",
                                 target_bodies=["Body1"]))
    assert result["edited"] is True
    assert scene.feature.participantBodies == [scene.body]
    assert result["definition_after"]["operation"] == "cut"


def test_symmetric_requires_explicit_zero_taper_and_half_length(scene):
    result = payload(mod.handler(feature="Extrude1", action="extent", extent="symmetric",
                                 distance=8))
    assert result["definition_matches"] is True
    assert scene.feature.setter_args[1] is False
    assert scene.feature.setter_args[2].realValue == 0
    assert scene.feature.extentOne.distance.value == pytest.approx(0.8)


@pytest.mark.parametrize("scoped", [False, True])
def test_two_side_reads_each_distance_independently(scene, scoped):
    if scoped:
        scene.feature.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
        scene.feature._participants = [scene.body]
    result = payload(mod.handler(feature="Extrude1", action="extent", extent="two_side",
                                 distance=12, distance2=8))
    assert result["definition_matches"] is True
    assert scene.feature.extentOne.distance.value == pytest.approx(1.2)
    assert scene.feature.extentTwo.distance.value == pytest.approx(0.8)


def test_false_extent_setter_does_not_report_success(scene):
    scene.feature.setter_ok = False
    result = mod.handler(feature="Extrude1", action="extent", extent="symmetric", distance=8)
    assert "setter returned false" in error_message(result)
    assert scene.timeline.markerPosition == 3
    assert result["details"]["definition_matches"] is False


def test_negative_through_all_sets_both_direction_inputs(scene):
    result = payload(mod.handler(feature="Extrude1", action="extent", extent="through_all",
                                 direction="negative"))
    assert result["definition_matches"] is True
    definition, direction, taper = scene.feature.setter_args
    assert definition.isPositiveDirection is False
    assert direction == adsk.fusion.ExtentDirections.NegativeExtentDirection
    assert taper.realValue == 0


@pytest.mark.parametrize("operation", ["CutFeatureOperation", "IntersectFeatureOperation"])
def test_scoped_through_all_both_refused_before_roll(scene, operation):
    scene.feature.operation = getattr(adsk.fusion.FeatureOperations, operation)
    scene.feature._participants = [scene.body]
    result = mod.handler(feature="Extrude1", action="extent", extent="through_all", direction="both")
    assert "Two-sided through_all with cut/intersect" in error_message(result)
    assert "separate one-sided features" in error_message(result)
    assert scene.timeline._moves == []
    assert scene.feature.setter_args is None
    assert scene.body.volume == 1


@pytest.mark.parametrize("source_operation,args", [
    ("CutFeatureOperation", {"action": "profile", "profile": "profile-1"}),
    ("IntersectFeatureOperation", {"action": "extent", "extent": "distance", "distance": 8}),
    ("CutFeatureOperation", {"action": "participants", "target_bodies": ["Body1"]}),
    ("NewBodyFeatureOperation", {"action": "operation", "operation": "cut", "target_bodies": ["Body1"]}),
    ("JoinFeatureOperation", {"action": "operation", "operation": "intersect", "target_bodies": ["Body1"]}),
])
def test_two_sided_through_source_refuses_scope_assignment_before_roll(scene, source_operation, args):
    scene.feature.operation = getattr(adsk.fusion.FeatureOperations, source_operation)
    scene.feature.hasTwoExtents = True
    scene.feature.extentOne = adsk.fusion.ThroughAllExtentDefinition.create()
    scene.feature.extentTwo = adsk.fusion.ThroughAllExtentDefinition.create()
    result = mod.handler(feature="Extrude1", **args)
    assert "Two-sided through_all with cut/intersect" in error_message(result)
    assert scene.timeline._moves == []
    assert scene.feature.assignments == 0
    assert scene.feature.setter_args is None
    assert scene.feature.participantBodies == []
    assert scene.body.volume == 1


def test_unscoped_new_body_through_all_both_is_not_refused(scene):
    result = payload(mod.handler(feature="Extrude1", action="extent", extent="through_all", direction="both"))
    assert result["edited"] is True
    assert scene.feature.hasTwoExtents is True


def test_distance_replacement_accepts_existing_extent_kind(scene):
    result = payload(mod.handler(feature="Extrude1", action="extent", extent="distance", distance=8))
    assert result["definition_matches"] is True
    assert scene.feature.extentOne.distance.value == pytest.approx(0.8)


def test_nonzero_taper_refused_before_extent_mutation(scene):
    scene.feature.taperAngleOne.value = 0.2
    result = mod.handler(feature="Extrude1", action="extent", extent="symmetric", distance=8)
    assert "zero readable taper" in error_message(result)
    assert scene.timeline._moves == []


def test_equal_volume_pocket_move_is_detected_by_face_centroids(scene, monkeypatch):
    def move_pocket():
        scene.body.boundingBox = make_bbox((0, 0, 0), (1, 1, 1))
        scene.body.faces.item(0).centroid.x = 0.1
    monkeypatch.setattr(scene.feature, "after_edit", move_pocket)
    result = payload(edit())
    assert result["geometry_before"][0][:8] == result["geometry_after"][0][:8]
    assert result["geometry_before"][0][8] == result["geometry_after"][0][8] == 6
    assert result["geometry_before"][0][9] != result["geometry_after"][0][9]


@pytest.mark.parametrize("unread", [None, float("nan")])
def test_unread_face_centroid_reports_unverified_landed_edit(scene, unread):
    scene.feature.after_edit = lambda: setattr(scene.body.faces.item(0).centroid, "x", unread)
    result = edit()
    assert result["isError"] is True
    assert result["details"]["definition_matches"] is True
    assert result["details"]["geometry_changed"] is None
    assert scene.timeline.markerPosition == 3


def test_unevaluated_rows_are_disclosed_at_parked_marker(scene):
    scene.rows[3].healthState = adsk.fusion.FeatureHealthStates.RolledBackFeatureHealthState
    result = payload(edit())
    assert result["unevaluated_timeline_items"] == 1
    assert "unevaluated" in result["note"]


def test_extra_action_input_refused_before_mutation(scene):
    result = mod.handler(feature="Extrude1", action="profile", profile="profile-1", operation="cut")
    assert "not used" in error_message(result)
    assert scene.feature.assignments == 0


def test_own_component_proxy_participant_is_normalized(scene, monkeypatch):
    proxy = SimpleNamespace(nativeObject=scene.body, assemblyContext=object())
    monkeypatch.setattr(mod._BODIES, "resolve", lambda raw: ([proxy], None))
    result = payload(mod.handler(feature="Extrude1", action="operation", operation="cut",
                                 target_bodies=["Part:Body1"]))
    assert result["definition_matches"] is True
    assert scene.feature.participantBodies == [scene.body]


@pytest.mark.parametrize("action", ["profile", "extent"])
def test_profile_and_extent_preserve_participant_scope(scene, monkeypatch, action):
    other = BRepBody("Other", volume=1, parent_component=scene.component)
    scene.feature.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    scene.feature._participants = [scene.body]
    original_members = Extrude.participantBodies
    assignments = []
    def set_members(feature, bodies):
        assignments.append(list(bodies))
        original_members.fset(feature, bodies)
    monkeypatch.setattr(Extrude, "participantBodies", property(original_members.fget, set_members))
    if action == "profile":
        scene.feature.after_edit = lambda: setattr(scene.feature, "_participants", [scene.body, other])
        result = payload(edit())
    else:
        original_extent = scene.feature.setSymmetricExtent
        def extent(*args):
            returned = original_extent(*args)
            scene.feature._participants = [scene.body, other]
            return returned
        monkeypatch.setattr(scene.feature, "setSymmetricExtent", extent)
        result = payload(mod.handler(feature="Extrude1", action="extent", extent="symmetric", distance=8))
    assert result["definition_matches"] is True
    assert assignments == [[scene.body], [scene.body]]
    assert scene.feature.participantBodies == [scene.body]


def test_scope_reapply_silent_noop_is_partial_failure(scene, monkeypatch):
    other = BRepBody("Other", parent_component=scene.component)
    scene.feature.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    scene.feature._participants = [scene.body]
    scene.feature.after_edit = lambda: setattr(scene.feature, "_participants", [scene.body, other])
    monkeypatch.setattr(Extrude, "participantBodies",
                        property(lambda f: f._participants, lambda f, bodies: None))
    result = edit()
    assert result["isError"] is True
    assert result["details"]["definition_matches"] is False
    assert result["details"]["definition_after"]["participants"] == ["Body1", "Other"]


def test_to_face_proxy_readback_compares_native_entity(scene):
    native_face = SimpleNamespace(nativeObject=None)
    proxy = SimpleNamespace(nativeObject=native_face)
    scene.feature.extentOne = SimpleNamespace(objectType="adsk::fusion::ToEntityExtentDefinition",
                                              entity=proxy, isChained=False,
                                              offset=SimpleNamespace(value=0))
    assert mod._definition_matches(scene.feature, "extent",
                                   {"extent": "to_face", "to_object": native_face}) is True


def _sibling_roof(scene):
    """A second component holding one readable body, as (component, body)."""
    sibling = MakeComp(name="Sibling", entity_token="sibling")
    roof = BRepBody("Roof", volume=4, area=22, bbox=make_bbox((0, 0, 3), (4, 2, 3.5)),
                    parent_component=sibling)
    roof.physicalProperties = SimpleNamespace(centerOfMass=SimpleNamespace(x=2, y=1, z=3.25))
    roof.faces = _NamedCollection([BRepFace(None, area=area, centroid=SimpleNamespace(x=x, y=y, z=z))
                                  for area, x, y, z in ((1, 0, 1, 3.25), (1, 4, 1, 3.25),
                                      (2, 2, 0, 3.25), (2, 2, 2, 3.25), (8, 2, 1, 3), (8, 2, 1, 3.5))])
    sibling.bRepBodies = _NamedCollection([roof])
    scene.design._all_components.append(sibling)
    return sibling, roof


def test_a_refused_setter_beside_a_changed_sibling_is_unconfirmed(scene, monkeypatch):
    _sibling, roof = _sibling_roof(scene)
    scene.feature.mode = "raise_before"
    original = Extrude.profile

    def cut_sibling(feature, value):
        roof.volume = 3.955
        original.fset(feature, value)
    monkeypatch.setattr(Extrude, "profile", property(original.fget, cut_sibling))
    result = edit()
    text = error_message(result)
    assert result["details"]["definition_after"] == result["details"]["definition_before"]
    assert result["details"]["geometry_changed"] is False
    assert result["details"]["other_components_unchanged"] is False
    assert "Whether 'Extrude1' changed is UNCONFIRMED" in text
    assert "other_components_unchanged=False" in text
    assert "Nothing changed" not in text


@pytest.mark.parametrize("replay", ["repair", "stale_mass", "noop", "raise"])
def test_evaluated_scope_replay_and_sibling_material_proof(scene, monkeypatch, replay):
    sibling, roof = _sibling_roof(scene)
    scene.feature.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    scene.feature._participants = [scene.body]
    scene.timeline.markerPosition = 4
    alias = Extrude(sibling, roof)
    alias.bodies = _NamedCollection([])
    alias._profile, alias._participants = scene.profiles[0], [scene.body]
    alias.timelineObject = scene.feature.timelineObject
    alias.assemblyContext = None
    alias.linkedFeatures = _NamedCollection([scene.feature])
    evaluated, assigned = [], []
    original_marker = FakeTimeline.markerPosition
    def move(timeline, value):
        original_marker.fset(timeline, value)
        if value == 3 and not evaluated:
            evaluated.append(True)
            roof.volume = 3.955
            scene.feature.linkedFeatures = _NamedCollection([alias])
    monkeypatch.setattr(FakeTimeline, "markerPosition", property(original_marker.fget, move))
    original_members = Extrude.participantBodies
    def members(feature, bodies):
        assigned.append(scene.timeline.markerPosition)
        if evaluated and replay == "raise":
            raise RuntimeError("post-evaluation scope replay refused")
        original_members.fset(feature, bodies)
        if evaluated and replay in ("repair", "stale_mass"):
            roof.volume = 4
            if replay == "stale_mass":
                roof.physicalProperties.volume = 3.955
                roof.physicalProperties.centerOfMass.x = 2.0085335
                roof.faces = _NamedCollection(list(reversed(list(roof.faces))))
    monkeypatch.setattr(Extrude, "participantBodies", property(original_members.fget, members))
    result = mod.handler(feature="Extrude1", action="extent", extent="through_all", direction="positive")
    repaired = replay in ("repair", "stale_mass")
    details = payload(result) if repaired else result["details"]
    # A distance-to-through_all edit has no measured reverse, so only the edit assigns scope.
    assert assigned == [2, 2]
    assert scene.timeline.markerPosition == 4
    assert details["same_feature"] is True
    assert details["other_components_unchanged"] is repaired
    if repaired:
        assert details["linked_component_aliases"] == ["Sibling"]
        assert details["linked_scope_verified_at_edit"] is True
        assert details["participants_reapplied_after_evaluation"] is True
        assert "Linked replay may leave mass properties stale." in details["note"]
        assert "design_recompute" in details["note"]
        assert "reset uncaptured joint poses" in details["note"]
        assert roof.volume == 4
    else:
        assert result["isError"] is True
        assert details["definition_matches"] is True
        assert details["other_component_changes"][0]["component"] == "Sibling"
        assert details["other_component_changes"][0]["after"][0][0] == 3.955
        assert ("This STAYED APPLIED (not rolled back): extent now reads through_all positive (was "
                "distance 10.0 mm). Restore it with model_edit_extrude(feature='Extrude1', "
                "action='extent', extent='distance', distance=10.0, direction='positive')."
                in error_message(result))
        assert "rollback" not in details


@pytest.mark.parametrize("repairs", [True, False])
def test_a_scoped_profile_rollback_replays_scope_and_rereads_the_sibling(scene, monkeypatch,
                                                                         repairs):
    _sibling, roof = _sibling_roof(scene)
    states = adsk.fusion.FeatureHealthStates
    scene.feature.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    scene.feature._participants = [scene.body]
    scene.timeline.markerPosition = 4
    pending, assigned = [], []

    def after_edit():
        pending.append(True)
        scene.rows[3].healthState = (states.WarningFeatureHealthState
                                     if scene.feature.profile is scene.profiles[1]
                                     else states.HealthyFeatureHealthState)
    scene.feature.after_edit = after_edit
    original_marker = FakeTimeline.markerPosition

    def move(timeline, value):
        # Evaluating a profile assigned since the last scope replay cuts the sibling roof.
        original_marker.fset(timeline, value)
        if value > 2 and pending:
            pending.clear()
            roof.volume = 3.955
    monkeypatch.setattr(FakeTimeline, "markerPosition", property(original_marker.fget, move))

    def members(feature, bodies):
        assigned.append(scene.timeline.markerPosition)
        feature._participants = list(bodies)
        if repairs:
            roof.volume = 4
    monkeypatch.setattr(Extrude, "participantBodies",
                        property(Extrude.participantBodies.fget, members))
    result = edit()
    text = error_message(result)
    # The edit assigns and replays its scope; the restore assigns and replays it again.
    assert assigned == [2, 2, 2, 2]
    assert scene.feature.profile is scene.profiles[0]
    assert result["details"]["rollback"]["verified"] is repairs
    if repairs:
        assert ("It was rolled back and re-read: profile reads sketch 'Original' profile 0 again; "
                "the bodies match the pre-edit read.") in text
    else:
        assert "A rollback ran but did not verify" in text
        assert "The bodies do not match the pre-edit read." in text
        assert "rolled back and re-read" not in text
        assert roof.volume == 3.955


def test_a_distance_setter_that_renames_the_parameter_is_named_not_restored(scene, monkeypatch):
    states = adsk.fusion.FeatureHealthStates
    scene.timeline.markerPosition = 4
    scene.feature.after_edit = lambda: setattr(scene.rows[3], "healthState", (
        states.WarningFeatureHealthState if scene.feature.param.value > 1
        else states.HealthyFeatureHealthState))
    setter = scene.feature.setOneSideExtent

    def remint(extent, direction, taper):
        scene.feature.param = Distance(scene.feature, name="d9", expression="0 mm", value=0.0)
        return setter(extent, direction, taper)
    monkeypatch.setattr(scene.feature, "setOneSideExtent", remint)
    result = mod.handler(feature="Extrude1", action="extent", extent="distance", distance=50)
    assert ("This STAYED APPLIED (not rolled back): extent now reads distance 50.0 mm (was distance "
            "10.0 mm); distance parameter now reads d9 = 50.0 mm (was d7 = 10 mm).") in (
                error_message(result))
    assert "rollback" not in result["details"]
    assert (scene.feature.param.name, scene.feature.param.expression) == ("d9", "50.0 mm")


def test_linked_alias_address_is_refused_before_mutation(scene, monkeypatch):
    foreign = MakeComp(name="AliasOwner", entity_token="alias-owner")
    foreign.bRepBodies = _NamedCollection([])
    scene.design._all_components.append(foreign)
    alias = Extrude(foreign, scene.body)
    alias._profile = scene.profiles[0]
    alias.timelineObject = scene.feature.timelineObject
    alias.linkedFeatures = _NamedCollection([scene.feature])
    monkeypatch.setattr(mod._FEATURE, "resolve", lambda raw: ((alias, "AliasOwner/Extrude1"), None))
    result = mod.handler(feature="AliasOwner/Extrude1", action="extent", extent="distance", distance=5)
    assert result["isError"] is True
    assert "original Extrude" in error_message(result)
    assert result["details"]["mutation_attempted"] is False
    assert alias.setter_args is None
    assert scene.timeline.markerPosition == 3


def _four_profiles(scene):
    """A counted native getter with four profiles of one sketched feature."""
    sketch = scene.profiles[0].parentSketch
    sketch.entityToken = "original-sketch-token"
    collection = _FakeObjectCollection()
    collection.objectType = "adsk::core::ObjectCollection"
    for i in range(4):
        collection.add(Profile(entity_token=f"four-profile-{i}", parent_sketch=sketch))
    scene.feature._profile = collection
    return collection


def test_four_profile_getter_allows_verified_extent_and_discloses_sketch(scene):
    _four_profiles(scene)
    result = payload(mod.handler(feature="Extrude1", action="extent", extent="symmetric",
                                 distance=8))
    assert result["edited"] is True
    assert result["definition_before"]["profile_sketch"] == "Original"
    assert result["definition_after"]["profile_sketch"] == "Original"
    assert result["linked_scope_verified_at_edit"] is True
    assert scene.feature.extentOne.distance.value == pytest.approx(0.8)


@pytest.mark.parametrize("args,expected_operation", [
    ({"action": "operation", "operation": "cut", "target_bodies": ["Body1"]}, "cut"),
    ({"action": "participants", "target_bodies": ["Body1"]}, "cut"),
    ({"action": "profile", "profile": "profile-1"}, "new"),
])
def test_four_profile_owner_keeps_existing_edit_actions(scene, args, expected_operation):
    _four_profiles(scene)
    if args["action"] == "participants":
        scene.feature.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    result = payload(mod.handler(feature="Extrude1", **args))
    assert result["edited"] is True
    assert result["definition_before"]["profile_sketch"] == "Original"
    assert result["definition_after"]["operation"] == expected_operation
    if args["action"] == "profile":
        assert result["definition_after"]["profile_sketch"] == "Replacement"
    else:
        assert result["definition_after"]["profile_sketch"] == "Original"


@pytest.mark.parametrize("broken,fragment", [
    ("empty", "empty or unreadable"),
    ("unreadable", "empty or unreadable"),
    ("non_profile", "non-profile member"),
    ("missing_sketch_identity", "unreadable sketch identity"),
    ("mixed_sketch", "spans sketches"),
    ("unreadable_owner", "unreadable component owner"),
    ("foreign", "outside its owning component"),
    ("linked", "Linked profile collections"),
])
def test_collection_with_unverified_members_or_links_refuses_before_mutation(scene, broken,
                                                                             fragment):
    collection = _four_profiles(scene)
    if broken == "empty":
        collection._items.clear()
    elif broken == "unreadable":
        collection = _NamedCollection(raises="collection unreadable")
        collection.objectType = "adsk::core::ObjectCollection"
        scene.feature._profile = collection
    elif broken == "non_profile":
        collection._items[2] = object()
    elif broken == "missing_sketch_identity":
        del scene.profiles[0].parentSketch.entityToken
    elif broken == "mixed_sketch":
        other = scene.profiles[1].parentSketch
        other.entityToken = "replacement-sketch-token"
        collection._items[2].parentSketch = other
    elif broken == "unreadable_owner":
        other = Sketch(name="Original", entity_token="orphan-sketch-token")
        collection._items[2].parentSketch = other
    elif broken == "foreign":
        foreign = MakeComp(name="Other", entity_token="other-token")
        other = Sketch(name="Original", parent_component=foreign,
                       entity_token="foreign-sketch-token")
        collection._items[2].parentSketch = other
    elif broken == "linked":
        scene.feature.linkedFeatures = _NamedCollection([object()])
    result = mod.handler(feature="Extrude1", action="extent", extent="symmetric", distance=8)
    assert result["isError"] is True
    assert fragment in error_message(result)
    assert result["details"]["mutation_attempted"] is False
    assert scene.feature.setter_args is None
    assert scene.timeline.markerPosition == 3
