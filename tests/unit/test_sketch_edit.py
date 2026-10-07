"""Unit tests for ``sketch_edit.py`` - one sketch's name, browser bulb or support plane.

Pinned: the exactly-one guard, the scoped resolve, the adopted-name read-back, the bulb beside the
effective visibility, and the plane change's pre-write guards and frame-based verdicts.
"""

import math

import pytest

from conftest import (BRepBody, BRepFace, FakePoint, FakeTimeline, FakeTimelineObject,
                      FakeVector3D, MakeComp, Plane, Sketch, _NamedCollection, error_message,
                      install, load_tool, make_design, payload)
import live_api_facts

_HEALTH = live_api_facts.ENUMS["fusion.FeatureHealthStates"]
_ON_FACE_RAISE = "3 : referencePlane is a BRefFace - need to roll timeline back before sketch"


class _DatumPlane:
    """A construction plane; no measured shape exists for it, so this is a local double."""
    def __init__(self, name, normal=(0.0, 0.0, 1.0), origin=(0.0, 0.0, 0.0), component=None):
        self.name = name
        self.entityToken = "plane-" + name
        self.geometry = Plane(FakeVector3D(*normal), FakePoint(*origin))
        self.component = component
        self.assemblyContext = None


def _in_plane_axes(normal):
    """Two unit axes spanning the plane of `normal`, with x cross y equal to it."""
    seed = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 1.0, 0.0)
    y = (normal[1] * seed[2] - normal[2] * seed[1], normal[2] * seed[0] - normal[0] * seed[2],
         normal[0] * seed[1] - normal[1] * seed[0])
    size = math.sqrt(sum(c * c for c in y))
    y = tuple(c / size for c in y)
    x = (y[1] * normal[2] - y[2] * normal[1], y[2] * normal[0] - y[0] * normal[2],
         y[0] * normal[1] - y[1] * normal[0])
    return x, y


def _moves_onto(sketch, target):
    """A faithful redefine: the support and the whole frame follow the target's plane."""
    g = target.geometry
    x, y = _in_plane_axes((g.normal.x, g.normal.y, g.normal.z))
    sketch.referencePlane = target
    sketch.origin = FakePoint(g.origin.x, g.origin.y, g.origin.z)
    sketch.xDirection, sketch.yDirection = FakeVector3D(*x), FakeVector3D(*y)
    return True


class _EditableSketch(Sketch):
    """The shared Sketch plus the bulb, support, frame and redefine a lifecycle edit drives.
    `adopt` maps an assigned name to the one that lands; `bulb_takes` False ignores a bulb write;
    referencePlane raises the on-a-face text while the support is a BRepFace."""
    def __init__(self, name, bulb=True, visible=True, adopt=None, bulb_takes=True,
                 redefine=_moves_onto):
        self._adopt = adopt
        self._bulb_takes = bulb_takes
        self._bulb = bulb
        self._redefine = redefine
        self._redefined_with = []
        self._support = None
        super().__init__(name, is_visible=visible, entity_token="sketch-" + name)
        self.origin = FakePoint(0.0, 0.0, 0.0)
        self.xDirection = FakeVector3D(1.0, 0.0, 0.0)
        self.yDirection = FakeVector3D(0.0, 1.0, 0.0)
        self.healthState = _HEALTH["HealthyFeatureHealthState"]
        self.assemblyContext = None

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = self._adopt(value) if self._adopt and hasattr(self, "_name") else value

    @property
    def isLightBulbOn(self):
        return self._bulb

    @isLightBulbOn.setter
    def isLightBulbOn(self, value):
        if self._bulb_takes:
            self._bulb = value

    @property
    def referencePlane(self):
        if isinstance(self._support, BRepFace):
            raise RuntimeError(_ON_FACE_RAISE)
        return self._support

    @referencePlane.setter
    def referencePlane(self, value):
        self._support = value

    def redefine(self, target):
        self._redefined_with.append(target)
        return self._redefine(self, target)


@pytest.fixture
def mod():
    return load_tool("sketch_edit")


def _world(mod, sketch=None, marker=None, extra_planes=()):
    """Root holding `sketch` on its XY plane, an 'Offset' plane 7 cm up and a 'Turned' one 30 deg
    about X, with a timeline of the sketch then 'Extrude1'. Returns (design, sketch, planes)."""
    xy, xz, yz = (_DatumPlane("XY"), _DatumPlane("XZ", (0.0, 1.0, 0.0)),
                  _DatumPlane("YZ", (1.0, 0.0, 0.0)))
    sketch = sketch or _EditableSketch("Profile")
    comp = MakeComp(name="Root", sketches=[sketch], origin_planes=(xy, xz, yz),
                    entity_token="root")
    turned = _DatumPlane("Turned", (0.0, -0.5, math.sqrt(0.75)))
    named = [_DatumPlane("Offset", origin=(0.0, 0.0, 7.0)), turned, *extra_planes]
    comp.constructionPlanes = _NamedCollection(named)
    for plane in (xy, xz, yz, *named):
        plane.component = plane.component or comp
    sketch.parentComponent = comp
    sketch.referencePlane = xy
    rows = [FakeTimelineObject("Profile", 0, entity=sketch), FakeTimelineObject("Extrude1", 1)]
    sketch.timelineObject = rows[0]
    design = install(mod, make_design(comp=comp, timeline=FakeTimeline(rows, marker=marker)))
    return design, sketch, {p.name: p for p in (xy, xz, yz, *named)}


def _face(component, normal=(1.0, 0.0, 0.0), origin=(4.0, 0.0, 0.0)):
    """A planar face of a body 'Base' owned by `component`."""
    return BRepFace(surface=Plane(FakeVector3D(*normal), FakePoint(*origin)),
                    body=BRepBody("Base", parent_component=component))


class TestGuards:
    @pytest.mark.parametrize("edits,named", [
        ({}, "got none"),
        ({"new_name": "A", "visible": False}, "got new_name, visible"),
        ({"visible": True, "plane": "Offset"}, "got visible, plane"),
        ({"new_name": "A", "visible": False, "plane": "Offset"}, "got new_name, visible, plane"),
    ])
    def test_zero_or_several_edits_refuse_before_any_write(self, mod, edits, named):
        _design, sketch, _planes = _world(mod)
        msg = error_message(mod.handler(sketch_name="Profile", **edits))
        assert "exactly one of new_name, visible, plane" in msg and named in msg
        assert sketch.name == "Profile" and sketch.isLightBulbOn is True
        assert sketch._redefined_with == []

    def test_a_name_two_components_share_is_refused_and_nothing_is_renamed(self, mod):
        first, second = _EditableSketch("Profile"), _EditableSketch("Profile")
        alpha = MakeComp(name="Alpha", sketches=[first], entity_token="a")
        beta = MakeComp(name="Beta", sketches=[second], entity_token="b")
        install(mod, make_design(comp=alpha, all_components=[alpha, beta]))
        msg = error_message(mod.handler(sketch_name="Profile", new_name="Mount"))
        assert "2 sketches are named 'Profile'" in msg and "'component'" in msg
        assert first.name == "Profile" and second.name == "Profile"

    def test_a_miss_lists_the_sketches_that_exist(self, mod):
        _world(mod)
        msg = error_message(mod.handler(sketch_name="Nope", visible=False))
        assert msg == "No sketch named 'Nope'. Available: Profile"

    def test_visible_must_be_a_boolean(self, mod):
        _design, sketch, _planes = _world(mod)
        msg = error_message(mod.handler(sketch_name="Profile", visible="off"))
        assert "'visible' must be true or false; got 'off'" in msg and sketch.isLightBulbOn is True


class TestRename:
    def test_the_adopted_name_is_published_when_it_differs_from_the_request(self, mod):
        _world(mod, _EditableSketch("Profile", adopt=lambda want: want + " (1)"))
        out = payload(mod.handler(sketch_name="Profile", new_name="Mount"))
        assert out["requested_name"] == "Mount" and out["name"] == "Mount (1)"
        assert out["adopted_differs"] is True and out["previous_name"] == "Profile"
        assert out["old_name_resolves"] is False
        assert out["address"] == {"sketch_name": "Mount (1)"}
        assert "adopted 'Mount (1)'" in out["note"]

    def test_an_assignment_that_silently_does_not_take_is_an_error(self, mod):
        _world(mod, _EditableSketch("Profile", adopt=lambda want: "Profile"))
        msg = error_message(mod.handler(sketch_name="Profile", new_name="Mount"))
        assert "did not take" in msg and "still reads 'Profile'" in msg

    def test_the_name_it_already_has_is_not_a_success(self, mod):
        _world(mod)
        msg = error_message(mod.handler(sketch_name="Profile", new_name=" Profile "))
        assert "already has that name" in msg

    def test_an_adopted_name_another_component_holds_is_addressed_with_its_owner(self, mod):
        ours, theirs = _EditableSketch("Profile"), _EditableSketch("Mount")
        alpha = MakeComp(name="Alpha", sketches=[ours], entity_token="a")
        beta = MakeComp(name="Beta", sketches=[theirs], entity_token="b")
        ours.parentComponent, theirs.parentComponent = alpha, beta
        install(mod, make_design(comp=alpha, all_components=[alpha, beta]))
        out = payload(mod.handler(sketch_name="Profile", new_name="Mount"))
        assert out["name"] == "Mount"
        assert out["address"] == {"sketch_name": "Mount", "component": "Alpha"}


class TestVisible:
    def test_the_bulb_and_the_effective_visibility_are_separate_fields(self, mod):
        # The fake's isVisible stays False whatever the bulb does: the two reads are independent.
        _design, sketch, _planes = _world(mod, _EditableSketch("Profile", bulb=False, visible=False))
        out = payload(mod.handler(sketch_name="Profile", visible=True))
        assert (out["bulb_before"], out["bulb_after"]) == (False, True)
        assert (out["effective_visible_before"], out["effective_visible_after"]) == (False, False)
        assert out["changed"] is True and "still reads False" in out["note"]
        assert sketch.isLightBulbOn is True

    def test_a_bulb_write_that_does_not_take_is_an_error(self, mod):
        _world(mod, _EditableSketch("Profile", bulb=True, bulb_takes=False))
        msg = error_message(mod.handler(sketch_name="Profile", visible=False))
        assert "did not take" in msg and "isLightBulbOn=True" in msg

    def test_a_bulb_already_as_requested_reports_no_change(self, mod):
        _world(mod, _EditableSketch("Profile", bulb=True, bulb_takes=False))
        out = payload(mod.handler(sketch_name="Profile", visible=True))
        assert out["changed"] is False and "nothing was written" in out["note"]


class TestPlane:
    def test_a_turned_plane_is_accepted_and_judged_by_the_frame(self, mod):
        _design, sketch, planes = _world(mod)
        out = payload(mod.handler(sketch_name="Profile", plane="Turned"))
        assert sketch._redefined_with == [planes["Turned"]]
        assert (out["plane_before"], out["plane_after"]) == ("XY", "Turned")
        assert out["redefine_returned"] is True and out["on_target_plane"] is True
        assert out["normal_vs_target"] == "same" and out["origin_off_plane_mm"] == 0.0
        assert out["frame_before"]["normal"] == [0.0, 0.0, 1.0]
        assert out["frame_after"]["normal"] == [0.0, -0.5, 0.866025]
        assert out["frame_changed"] is True and out["sketch_health"] == "healthy"
        assert out["later_features"] == [{"name": "Extrude1", "health": "healthy"}]
        assert (out["marker_before"], out["marker_after"]) == (2, 2)
        assert "can return a different in-plane orientation; compare frame_after" in out["note"]

    def test_a_face_target_is_judged_by_the_frame_while_its_support_is_unread(self, mod,
                                                                              monkeypatch):
        design, sketch, _planes = _world(mod)
        face = _face(design.rootComponent)
        monkeypatch.setattr(mod._PLANE, "resolve", lambda raw, component=None: (face, None))
        out = payload(mod.handler(sketch_name="Profile", plane="face-handle"))
        assert out["requested_plane"] == "a face of body 'Base'"
        assert out["plane_before"] == "XY" and out["plane_after"] is None
        assert out["unread"]["plane_after"] == _ON_FACE_RAISE
        assert out["on_target_plane"] is True
        assert out["frame_after"]["origin_mm"] == [40.0, 0.0, 0.0]

    def test_a_frame_whose_normal_opposes_the_targets_is_accepted_and_says_so(self, mod):
        def lands_flipped(sketch, target):
            _moves_onto(sketch, target)
            sketch.xDirection, sketch.yDirection = sketch.yDirection, sketch.xDirection
            return True

        _world(mod, _EditableSketch("Profile", redefine=lands_flipped))
        out = payload(mod.handler(sketch_name="Profile", plane="Offset"))
        assert out["on_target_plane"] is True and out["normal_vs_target"] == "opposed"
        assert "opposed to the target's" in out["note"]

    def test_a_frame_already_on_the_target_plane_is_not_reported_as_a_move(self, mod):
        twin = _DatumPlane("Twin")
        _world(mod, _EditableSketch("Profile", redefine=lambda sketch, target: True),
               extra_planes=[twin])
        out = payload(mod.handler(sketch_name="Profile", plane="Twin"))
        assert out["frame_changed"] is False and out["on_target_plane"] is True
        assert "reads identical before and after: nothing moved" in out["note"]

    def test_a_marker_before_the_end_refuses_naming_the_position_and_the_roll(self, mod):
        _design, sketch, _planes = _world(mod, marker=1)
        msg = error_message(mod.handler(sketch_name="Profile", plane="Offset"))
        assert "marker is at 1 of 2" in msg
        assert "design_edit_timeline(action='roll', to='end')" in msg
        assert sketch._redefined_with == []

    def test_a_plane_of_another_component_is_refused_before_any_write(self, mod):
        other = MakeComp(name="Other", entity_token="other")
        foreign = _DatumPlane("Foreign", origin=(0.0, 0.0, 2.0), component=other)
        _design, sketch, _planes = _world(mod, extra_planes=[foreign])
        msg = error_message(mod.handler(sketch_name="Profile", plane="Foreign"))
        assert "plane 'Foreign', which is not read as belonging" in msg
        assert "not available yet" in msg and sketch._redefined_with == []

    def test_a_face_of_another_component_is_refused_before_any_write(self, mod, monkeypatch):
        _design, sketch, _planes = _world(mod)
        face = _face(MakeComp(name="Other", entity_token="other"))
        monkeypatch.setattr(mod._PLANE, "resolve", lambda raw, component=None: (face, None))
        msg = error_message(mod.handler(sketch_name="Profile", plane="face-handle"))
        assert "a face of body 'Base', which is not read as belonging" in msg
        assert sketch._redefined_with == []

    def test_a_target_whose_plane_geometry_does_not_read_is_refused_before_the_write(self, mod):
        blank = _DatumPlane("Blank")
        blank.geometry = None
        _design, sketch, _planes = _world(mod, extra_planes=[blank])
        msg = error_message(mod.handler(sketch_name="Profile", plane="Blank"))
        assert "plane geometry of plane 'Blank' did not read" in msg
        assert sketch._redefined_with == []

    def test_redefine_returning_false_is_an_error_with_the_state_it_left(self, mod):
        _world(mod, _EditableSketch("Profile", redefine=lambda sketch, target: False))
        result = mod.handler(sketch_name="Profile", plane="Offset")
        msg = error_message(result)
        assert "returned False" in msg and "frame_changed reads False" in msg
        assert result["details"]["redefine_returned"] is False
        assert result["details"]["plane_after"] == "XY"

    def test_a_true_return_with_the_origin_off_the_target_plane_is_an_error(self, mod):
        # The sketch stays where it was: parallel to 'Offset' and 7 cm below it.
        _world(mod, _EditableSketch("Profile", redefine=lambda sketch, target: True))
        result = mod.handler(sketch_name="Profile", plane="Offset")
        msg = error_message(result)
        assert "returned true but the origin of sketch 'Profile' reads 70.0 mm off" in msg
        assert result["details"]["on_target_plane"] is False
        assert result["details"]["frame_changed"] is False

    def test_a_true_return_with_a_normal_not_parallel_to_the_target_is_an_error(self, mod):
        def lands_elsewhere(sketch, target):
            return _moves_onto(sketch, planes["Turned"])

        _design, _sketch, planes = _world(mod, _EditableSketch("Profile",
                                                               redefine=lands_elsewhere))
        result = mod.handler(sketch_name="Profile", plane="XZ")
        msg = error_message(result)
        assert "is not parallel to plane 'XZ'" in msg
        assert "frame_after reads normal [0.0, -0.5, 0.866025]" in msg
        assert result["details"]["on_target_plane"] is False

    @pytest.mark.parametrize("off_cm,accepted", [(1e-6, True), (2e-6, False)])
    def test_the_origin_tolerance_is_the_shared_length_band(self, mod, off_cm, accepted):
        def lands_off(sketch, target):
            sketch.origin = FakePoint(0.0, 0.0, off_cm)
            return True

        twin = _DatumPlane("Twin")
        _world(mod, _EditableSketch("Profile", redefine=lands_off), extra_planes=[twin])
        assert mod.handler(sketch_name="Profile", plane="Twin")["isError"] is not accepted

    def test_a_frame_that_does_not_read_back_is_an_unverified_error(self, mod):
        def loses_its_frame(sketch, target):
            sketch.origin = None
            return True

        _world(mod, _EditableSketch("Profile", redefine=loses_its_frame))
        result = mod.handler(sketch_name="Profile", plane="Offset")
        msg = error_message(result)
        assert "did not read back, so the change is unverified" in msg
        assert result["details"]["on_target_plane"] is None
        assert result["details"]["frame_changed"] is None
        assert "on_target_plane" in result["details"]["unread"]

    def test_a_later_row_that_turns_unhealthy_is_an_error_naming_it(self, mod):
        def breaks_the_extrude(sketch, target):
            design.timeline.item(1).healthState = _HEALTH["ErrorFeatureHealthState"]
            return _moves_onto(sketch, target)

        design, _sketch, _planes = _world(
            mod, _EditableSketch("Profile", redefine=breaks_the_extrude))
        result = mod.handler(sketch_name="Profile", plane="Offset")
        msg = error_message(result)
        assert "REMAINS" in msg and "Extrude1" in msg and "sketch_edit" not in msg
        assert result["details"]["new_timeline_errors"] == ["Extrude1"]
        assert result["details"]["later_features"] == [{"name": "Extrude1", "health": "error"}]
        assert result["details"]["plane_after"] == "Offset"

    def test_a_marker_that_left_the_end_is_an_error_with_the_roll_remedy(self, mod):
        def rolls_back(sketch, target):
            design.timeline.markerPosition = 1
            return _moves_onto(sketch, target)

        design, _sketch, _planes = _world(
            mod, _EditableSketch("Profile", redefine=rolls_back))
        result = mod.handler(sketch_name="Profile", plane="Offset")
        msg = error_message(result)
        assert "REMAINS" in msg and "marker reads 1, was 2 of 2" in msg
        assert "design_edit_timeline(action='roll', to='end')" in msg
        assert result["details"]["marker_after"] == 1

    def test_a_raise_with_the_frame_unchanged_says_the_sketch_was_not_moved(self, mod):
        def raises(sketch, target):
            raise RuntimeError("3 : CIRCULAR_DEPENDENCY - Circular dependency found")

        _world(mod, _EditableSketch("Profile", redefine=raises))
        msg = error_message(mod.handler(sketch_name="Profile", plane="Offset"))
        assert "3 : CIRCULAR_DEPENDENCY - Circular dependency found" in msg
        assert "The sketch was not moved: its frame reads as before." in msg

    def test_a_raise_after_the_frame_changed_says_what_it_reads_now(self, mod):
        def moves_then_raises(sketch, target):
            _moves_onto(sketch, target)
            raise RuntimeError("3 : compute failed")

        _world(mod, _EditableSketch("Profile", redefine=moves_then_raises))
        result = mod.handler(sketch_name="Profile", plane="Offset")
        msg = error_message(result)
        assert "3 : compute failed" in msg and "not moved" not in msg
        assert "frame CHANGED and now reads origin_mm [0.0, 0.0, 70.0]" in msg
        assert result["details"]["frame_changed"] is True
