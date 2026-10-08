"""Unit tests for ``model_sweep.py`` - sweep a profile along a path into a solid/surface.

Pinned: the solid happy path, the open-profile -> surface fallback (and as_surface forcing a surface
off a closed profile), the path builders (a path sketch vs model edges), operation + orientation
handling, target_bodies scoping, the guards (missing profile, bad sketch/path/operation/orientation,
no design), and the honesty contract (an API no-op that creates no body must report isError, and a
swallowed configure/add failure must surface).
"""

import math
import types

import adsk.fusion
import pytest

from conftest import (load_tool, make_design, install, make_sketch, make_sketch_curve,
                      payload as _payload, assert_names_retained,
                      error_message, assert_no_active_design, BRepBody, BRepEdge,
                      FakeFeatures as _SharedFeatures, Line3D, Profile, _NamedCollection,
                      MakeComp, FakePoint, FakeTimeline, FakeTimelineObject, make_bbox, body_proxy)

sw = load_tool("model_sweep")


def _solid_tool_world(*, result_same_shape=False, ignored_orientation=False, wrong_context=False,
                      health="HealthyFeatureHealthState", input_field=None, faces_of_source=False,
                      reshaped_source=False, second_result=False, feature_omits_result=False,
                      linked_owner=False):
    """Return a measured-shape source, a distinct result and one owner-local path."""
    adsk.fusion.BRepBody = BRepBody
    perpendicular = adsk.fusion.SweepSolidOrientationTypes.PerpendicularSolidOrientationType

    def body(name, low, high, volume, area):
        face = types.SimpleNamespace(area=area, centroid=FakePoint(*low))
        return BRepBody(name, bbox=make_bbox(low, high), volume=volume, area=area,
                        faces=[face], entity_token=name + "-token")

    source = body("ToolBox", (-.25, -.25, 0), (.25, .25, .5), .125, 1.5)
    result = (body("SweptBox", (-.25, -.25, 0), (.25, .25, .5), .125, 1.5)
              if result_same_shape else
              body("SweptBox", (-.25, -.25, 0), (2.25, .25, .5), .625, 5.5))
    new = [result] + ([body("SweptTwin", (-.25, -.25, 1), (2.25, .25, 1.5), .625, 5.5)]
                      if second_result else [])
    host = MakeComp("ToolHost", bodies=[source], entity_token="host-token")
    root = MakeComp("Root", entity_token="root-token")
    host.sketches = _NamedCollection([_sketch("ToolPath", curves=1, owner=host)])
    sf = FakeSweepFeatures()
    host.features = FakeFeatures(sf)
    design = make_design(comp=root, all_components=[root, host])
    root.parentDesign = host.parentDesign = design
    if linked_owner:
        host.parentDesign = types.SimpleNamespace(
            rootComponent=MakeComp("LinkedRoot", entity_token="linked-root-token"))
    source.parentComponent = host
    for made in new:
        made.parentComponent = host
    context = types.SimpleNamespace(component=root if wrong_context else host)
    proxy = body_proxy(source, occurrence=context, entity_token="proxy-token")
    design._tokens["PX"] = proxy
    install(sw, design)

    def create(source_body, path, operation):
        sf.last = types.SimpleNamespace(solidBody=source_body, solidOrientation=perpendicular,
                                        solidAlignedAxis=None, path=path, operation=operation)
        sf.last._set_solidAlignedAxis = lambda value: setattr(sf.last, "solidAlignedAxis", value) or True
        sf.last._set_solidOrientation = lambda value: setattr(sf.last, "solidOrientation", value) or True
        if input_field:
            setattr(sf.last, *input_field)
        return sf.last

    def add(inp):
        host.bRepBodies._items.extend(new)
        if reshaped_source:
            source.volume = result.volume
        return types.SimpleNamespace(
            name="SolidSweep",
            bodies=_NamedCollection([source] if feature_omits_result else [source, *new]),
            faces=_NamedCollection([types.SimpleNamespace(body=source if faces_of_source else b)
                                    for b in new]),
            healthState=getattr(adsk.fusion.FeatureHealthStates, health) if health else None,
            solidOrientation=(-1 if ignored_orientation else inp.solidOrientation),
            solidAlignedAxis=inp.solidAlignedAxis)

    sf.createInputForSolid = create
    sf.add = add
    return sf, host, source, result


@pytest.fixture
def empty_solid_create(monkeypatch):
    def make(fault=None):
        sf, host, source, result = _solid_tool_world()
        design = host.parentDesign
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        prior = types.SimpleNamespace(entityToken="prior", name="Source", parentComponent=host)
        timeline = FakeTimeline([FakeTimelineObject("Source", 0, prior)])
        design.timeline = timeline
        feature = types.SimpleNamespace(name="EmptySweep", entityToken="empty-sweep", parentComponent=host,
                                        faces=_NamedCollection([]), bodies=_NamedCollection([source]))
        row = FakeTimelineObject(feature.name, 1, feature)
        feature.timelineObject = row
        calls = []

        def delete():
            calls.append(feature)
            if fault == "raises":
                raise RuntimeError("delete refused")
            if fault != "kept":
                timeline._items.pop()
                timeline._marker -= 1
            if fault == "cascade":
                timeline._items.clear()
                timeline._marker = 0
            if fault == "changed_after":
                source.volume *= 2
            return fault != "false"

        def add(inp):
            timeline._items.append(row)
            timeline._marker += 1
            if fault == "unread_faces":
                feature.faces = types.SimpleNamespace(count=None)
            if fault == "changed_before":
                source.volume *= 2
            if fault == "new_body":
                host.bRepBodies._items.append(result)
            if fault == "wrong_entity":
                row.entity = prior
            return feature

        feature.deleteMe = delete
        monkeypatch.setattr(sf, "add", add)
        if fault == "direct":
            design.designType = adsk.fusion.DesignTypes.DirectDesignType
        return timeline, calls, feature
    return make


class TestEmptySolidRetirement:
    def test_removes_only_verified_no_effect_feature(self, empty_solid_create):
        timeline, calls, feature = empty_solid_create()
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True
        assert "Failed feature 'ToolHost/EmptySweep@1' was removed" in error_message(res)
        assert calls == [feature] and timeline.count == timeline.markerPosition == 1
        assert timeline.item(0).name == "Source"

    @pytest.mark.parametrize("fault", ["unread_faces", "changed_before", "new_body", "wrong_entity", "direct"])
    def test_unread_or_effectful_or_unidentifiable_create_is_not_deleted(self, empty_solid_create, fault):
        timeline, calls, _ = empty_solid_create(fault)
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        text = error_message(res)
        assert res["isError"] is True and calls == [] and timeline.count == 2
        assert "ToolHost/EmptySweep@1" in text
        assert "was removed" not in text

    @pytest.mark.parametrize("fault", ["kept", "false", "cascade", "changed_after", "raises"])
    def test_failed_or_incomplete_cleanup_is_never_reported_restored(self, empty_solid_create, fault):
        _, calls, feature = empty_solid_create(fault)
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        text = error_message(res)
        assert res["isError"] is True and calls == [feature]
        assert "ToolHost/EmptySweep@1" in text and "unconfirmed" in text
        assert "was removed" not in text and "was retained" not in text


class TestSolidTool:
    def test_proxy_source_sweeps_in_own_component_and_excludes_source_from_result(self):
        sf, host, source, result = _solid_tool_world()
        out = _payload(sw.handler(solid_body="PX", path="sketch:ToolPath"))
        assert sf.last.solidBody is source
        assert out["component"] == "ToolHost"
        assert out["result_bodies"] == ["SweptBox"]
        assert out["source_retained"] is True
        assert host.bRepBodies.count == 2 and host.bRepBodies.item(1) is result

    def test_refuses_unmeasured_path_and_boolean_before_feature_creation(self):
        sf, host, _, _ = _solid_tool_world()
        for kwargs in ({"path": ["EDGE"]}, {"operation": "cut", "path": "sketch:ToolPath"},
                       {"orientation": "parallel", "path": "sketch:ToolPath"},
                       {"as_surface": True, "path": "sketch:ToolPath"}):
            assert sw.handler(solid_body="PX", **kwargs)["isError"] is True
        assert sf.last is None and host.bRepBodies.count == 1

    def test_rigid_solid_orientation_reaches_input_and_feature(self):
        sf, _, _, _ = _solid_tool_world()
        out = _payload(sw.handler(solid_body="PX", path="sketch:ToolPath", orientation="rigid"))
        assert sf.last.solidOrientation == adsk.fusion.SweepSolidOrientationTypes.RigidSolidOrientationType
        assert out["orientation"] == "rigid" and out["source_retained"] is True

    def test_aligned_solid_requires_and_reads_the_resolved_owner_axis(self, monkeypatch):
        sf, host, source, _ = _solid_tool_world()
        axis = types.SimpleNamespace(entityToken="axis-token", component=host)
        monkeypatch.setattr(sw._SOLID_ALIGNED_AXIS, "resolve",
                            lambda _raw, component=None: (("edge", axis), None))
        out = _payload(sw.handler(solid_body="PX", path="sketch:ToolPath", orientation="aligned",
                                  solid_aligned_axis="AXIS"))
        assert sf.last.solidAlignedAxis is axis
        assert sf.last.solidOrientation == adsk.fusion.SweepSolidOrientationTypes.AlignedSolidOrientationType
        assert out["orientation"] == "aligned" and host.bRepBodies.count == 2

    def test_aligned_solid_refuses_component_only_axis_from_another_owner(self, monkeypatch):
        sf, host, _, _ = _solid_tool_world()
        foreign = MakeComp("Foreign", entity_token="foreign-token")
        axis = types.SimpleNamespace(entityToken="foreign-axis-token", component=foreign)
        monkeypatch.setattr(sw._SOLID_ALIGNED_AXIS, "resolve",
                            lambda _raw, component=None: (("edge", axis), None))
        res = sw.handler(solid_body="PX", path="sketch:ToolPath", orientation="aligned",
                         solid_aligned_axis="AXIS")
        assert res["isError"] is True and "owner component" in error_message(res)
        assert sf.last is None and host.bRepBodies.count == 1

    def test_aligned_solid_refuses_without_axis_before_input(self):
        sf, host, _, _ = _solid_tool_world()
        res = sw.handler(solid_body="PX", path="sketch:ToolPath", orientation="aligned")
        assert res["isError"] is True and "solid_aligned_axis" in res["message"]
        assert sf.last is None and host.bRepBodies.count == 1

    def test_refuses_wrong_proxy_context_and_unchanged_result(self):
        sf, host, _, _ = _solid_tool_world(wrong_context=True)
        assert sw.handler(solid_body="PX", path="sketch:ToolPath")["isError"] is True
        assert sf.last is None and host.bRepBodies.count == 1
        _solid_tool_world(result_same_shape=True)
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True and "not a verified new solid" in error_message(res)

    def test_a_body_owned_by_a_linked_design_is_refused_before_input(self):
        sf, host, _, _ = _solid_tool_world(linked_owner=True)
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True and "not a linked source" in error_message(res)
        assert sf.last is None and host.bRepBodies.count == 1

    def test_ignored_feature_orientation_is_not_reported_as_perpendicular(self):
        _solid_tool_world(ignored_orientation=True)
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True and "orientation did not persist" in error_message(res)

    def test_error_health_is_refused_and_warning_is_disclosed_in_the_note(self):
        _solid_tool_world(health="ErrorFeatureHealthState")
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True and "health is unreadable or failed" in error_message(res)
        _solid_tool_world(health="WarningFeatureHealthState")
        out = _payload(sw.handler(solid_body="PX", path="sketch:ToolPath"))
        assert "Feature warning:" in out["note"] and "health" not in out

    def test_created_faces_owned_outside_the_census_delta_name_no_result(self):
        # feature.bodies lists the source too, so only created-face owners that equal the
        # owner's census delta name the output.
        _solid_tool_world(faces_of_source=True)
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True
        assert "could not be identified from created faces" in error_message(res)
        assert "result_bodies" not in str(res)

    def test_a_source_whose_shape_changed_is_not_reported_retained(self):
        _solid_tool_world(reshaped_source=True)
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True
        assert "source tool body's geometry was not retained" in error_message(res)

    def test_an_input_that_drops_the_body_or_orientation_is_refused_before_add(self):
        for field, message in (
                (("solidBody", BRepBody("Other", entity_token="other-token")),
                 "did not retain the requested tool body"),
                (("solidOrientation", -1), "did not retain perpendicular orientation")):
            _, host, _, _ = _solid_tool_world(input_field=field)
            res = sw.handler(solid_body="PX", path="sketch:ToolPath")
            assert res["isError"] is True and message in error_message(res)
            assert host.bRepBodies.count == 1

    def test_unreadable_feature_health_is_refused(self):
        _solid_tool_world(health=None)
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True and "health is unreadable or failed" in error_message(res)

    def test_two_new_bodies_are_not_reported_as_one_result(self):
        _solid_tool_world(second_result=True)
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True
        assert "could not be identified from created faces" in error_message(res)
        assert "result_bodies" not in str(res)

    def test_a_component_that_does_not_own_the_body_is_refused_before_input(self):
        # Root is a second component in the design; the body's owner is ToolHost.
        sf, _, _, _ = _solid_tool_world()
        res = sw.handler(solid_body="PX", path="sketch:ToolPath", component="Root")
        assert res["isError"] is True and "does not own 'solid_body'" in error_message(res)
        assert sf.last is None

    @pytest.mark.parametrize("extra, fragment", [
        ({"profile": {"sketch": "X"}}, "not both"),
        ({"target_bodies": ["ToolBox"]}, "'target_bodies' applies to profile")])
    def test_a_conflicting_input_is_refused_not_dropped(self, extra, fragment):
        sf, _, _, _ = _solid_tool_world()
        res = sw.handler(solid_body="PX", path="sketch:ToolPath", **extra)
        assert res["isError"] is True and fragment in error_message(res)
        assert sf.last is None

    def test_a_census_body_the_feature_does_not_list_is_not_its_result(self):
        _solid_tool_world(feature_omits_result=True)
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True
        assert "not a verified new solid body" in error_message(res)

    def test_two_path_sketches_of_one_name_are_refused_before_input(self):
        sf, host, _, _ = _solid_tool_world()
        host.sketches._items.append(_sketch("ToolPath", curves=1, owner=host))
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        message = error_message(res)
        assert res["isError"] is True
        assert "must name exactly one sketch" in message and "found 2" in message
        assert sf.last is None

    def test_an_unreadable_source_shape_is_refused_before_input(self):
        sf, host, source, _ = _solid_tool_world()
        source.area = None
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True and "identity or shape is unreadable" in error_message(res)
        assert sf.last is None and host.bRepBodies.count == 1

    def test_an_unnamed_result_body_is_not_published(self):
        _, _, _, result = _solid_tool_world()
        result.name = None
        res = sw.handler(solid_body="PX", path="sketch:ToolPath")
        assert res["isError"] is True and "no readable name" in error_message(res)
        assert "result_bodies" not in str(res)

    def test_a_path_that_chains_fewer_curves_than_its_sketch_is_disclosed(self):
        _, host, _, _ = _solid_tool_world()
        host.sketches = _NamedCollection([_sketch("ToolPath", curves=2, owner=host)])
        host.features.path_returns = _built_path(1)
        out = _payload(sw.handler(solid_body="PX", path="sketch:ToolPath"))
        assert "chained 1 of the sketch's 2 curves" in out["note"]

    def test_a_two_of_three_solid_path_names_the_left_out_curve(self):
        _, host, _, _ = _solid_tool_world()
        _two_of_three(host, "ToolPath")
        out = _payload(sw.handler(solid_body="PX", path="sketch:ToolPath"))
        assert out["path"] == "sketch:ToolPath" and "Not in the path: line:1." in out["note"]


# ── small sweep-shaped fakes ────────────────────────────────────────────────

class FakeOpenProfile:
    pass


def _sketch(name, profiles=(), curves=0, owner=None):
    """A sketch holding `profiles` closed regions and `curves` plain curves. `owner` is the
    parentComponent the OPEN-profile path hosts the feature on; left unset it falls back to the
    active component, which cannot tell two same-named sketches apart."""
    sk = make_sketch(name, lines=[object() for _ in range(curves)], profiles=profiles)
    sk.parentComponent = owner
    return sk


class FakeSweepInput:
    def __init__(self, profile, path, op):
        self.profile = profile
        self.path = path
        self.operation = op
        self.isSolid = True
        self.orientation = None
        self.participantBodies = None
        self.guideRail = None

    def _set_isSolid(self, value):
        self.isSolid = value
        return True

    def _set_orientation(self, value):
        self.orientation = value
        return True

    def _set_guideRail(self, value):
        self.guideRail = value
        return True

    def _set_twistAngle(self, value):
        self.twistAngle = value
        return True

    def _set_taperAngle(self, value):
        self.taperAngle = value
        return True

    def _set_distanceOne(self, value):
        self.distanceOne = value
        return True


class FakeSweepFeature:
    def __init__(self, bodies_names=("Body1",), is_solid=True, inp=None):
        self.name = "Sweep1"
        self.isSolid = is_solid
        self.bodies = _NamedCollection([BRepBody(n) for n in bodies_names])
        self.guideRail = getattr(inp, "guideRail", None)
        self.twistAngle = types.SimpleNamespace(value=0.0, expression="0 deg")
        self.taperAngle = types.SimpleNamespace(value=0.0, expression="0 deg")
        self.distanceOne = types.SimpleNamespace(value=1.0, expression="1")
        for name, default in (("twistAngle", "0 deg"), ("taperAngle", "0 deg")):
            value = getattr(inp, name, None) if inp is not None else None
            if value is not None:
                degrees = float(value.stringValue.split()[0])
                setattr(self, name, types.SimpleNamespace(value=math.radians(degrees),
                                                          expression=value.stringValue))
        value = getattr(inp, "distanceOne", None) if inp is not None else None
        if value is not None:
            self.distanceOne = types.SimpleNamespace(value=value.realValue, expression=str(value.realValue))


class MarkerRequiredSweepFeature(FakeSweepFeature):
    def __init__(self, bodies_names, inp, timeline_object, fraction=None):
        super().__init__(bodies_names=bodies_names, is_solid=inp.isSolid, inp=inp)
        self.timelineObject = timeline_object
        self.parameter_reads = []
        self._require_rolled_read = True
        if fraction is not None:
            self.distanceOne = types.SimpleNamespace(value=fraction, expression=str(fraction))

    def __getattribute__(self, name):
        if name in ("twistAngle", "taperAngle", "distanceOne"):
            state = object.__getattribute__(self, "__dict__")
            if state.get("_require_rolled_read"):
                rolled = state["timelineObject"].isRolledBack
                state["parameter_reads"].append((name, rolled))
                if not rolled:
                    raise RuntimeError("Didn't roll editing feature back")
        return super().__getattribute__(name)


class FakeSweepFeatures:
    def __init__(self, body_names=("Body1",)):
        self.last = None
        self.body_names = tuple(body_names)
        self.create_raises = False
        self.add_returns_none = False
        self.add_raises = False

    def createInput(self, profile, path, op):
        if self.create_raises:
            raise RuntimeError("createInput boom")
        self.last = FakeSweepInput(profile, path, op)
        return self.last

    def add(self, inp):
        if self.add_raises:
            raise RuntimeError("add boom")
        if self.add_returns_none:
            return None
        # Echo the requested isSolid back off the feature, as the live API does.
        return FakeSweepFeature(bodies_names=self.body_names, is_solid=inp.isSolid, inp=inp)


def _built_path(count, entities=None):
    """A built adsk.fusion.Path: `count` is the number of edges the path ACTUALLY holds, which is
    not derivable from how many handles were passed in."""
    entities = list(entities or [object() for _ in range(count)])
    return types.SimpleNamespace(count=count,
                                 item=lambda i: types.SimpleNamespace(entity=entities[i]))


def _two_of_three(comp, name):
    """Give `comp` a three-line path sketch whose every createPath holds line:0 and line:2."""
    curves = [make_sketch_curve(f"{name}-{i}") for i in range(3)]
    sketch = make_sketch(name, lines=curves)
    sketch.parentComponent = comp
    comp.sketches = _NamedCollection([s for s in comp.sketches if s.name != name] + [sketch])
    comp.features.path_returns = types.SimpleNamespace(
        count=2, item=lambda i: types.SimpleNamespace(entity=(curves[0], curves[2])[i]))


class FakeFeatures(_SharedFeatures):
    """comp.features plus the sweep collection and the createPath factory a sweep drives."""
    def __init__(self, sweepfeatures):
        super().__init__()
        self.sweepFeatures = sweepfeatures
        self.path_calls = []
        self.path_returns = _built_path(1)

    def createPath(self, seed, is_chain):
        self.path_calls.append((seed, is_chain))
        return self.path_returns


def _install(*, closed_profiles=1, open_curves=0, body_names=("Body1",), tokens=None,
             extra_sketches=(), bodies=()):
    """Build a root component carrying the sweep surface (sketches + features + createOpenProfile) and
    wire it in via conftest's make_design/install (both seams). `bodies` are the component's existing
    solid bodies - what a cut/intersect samples volumes over. Returns (module-features, design)."""
    from conftest import MakeComp
    sf = FakeSweepFeatures(body_names=body_names)
    comp = MakeComp(name="Root", bodies=list(bodies))
    comp.features = FakeFeatures(sf)
    comp.createOpenProfile = lambda coll, chain: FakeOpenProfile()

    sketches = [
        _sketch("Prof", profiles=[Profile() for _ in range(closed_profiles)],
                curves=open_curves),
        _sketch("PathSketch", curves=3),
    ]
    sketches.extend(extra_sketches)
    comp.sketches = _NamedCollection(sketches)

    design = make_design(comp=comp, tokens=tokens or {})
    install(sw, design)
    return sf, design


def _attach_feature_timeline(sf, design):
    timeline = FakeTimeline([FakeTimelineObject("Seed", 0)], marker=1)
    design.timeline = timeline
    add = sf.add

    def add_with_timeline(inp):
        feature = add(inp)
        feature.timelineObject = FakeTimelineObject(feature.name, 1, feature)
        return feature

    sf.add = add_with_timeline
    return timeline


def _install_rolled_parameter_feature(monkeypatch, *, fraction=None, restore_failure=False):
    monkeypatch.setattr(adsk.core.ValueInput, "createByString",
                        staticmethod(lambda value: types.SimpleNamespace(stringValue=value)),
                        raising=False)
    monkeypatch.setattr(adsk.core.ValueInput, "createByReal",
                        staticmethod(lambda value: types.SimpleNamespace(realValue=value)),
                        raising=False)
    sf, design = _install()
    timeline = FakeTimeline([FakeTimelineObject("Seed", 0)], marker=1)
    if restore_failure:
        class RestoreRaisingTimeline(FakeTimeline):
            @property
            def markerPosition(self):
                return self._read(self._marker)

            @markerPosition.setter
            def markerPosition(self, value):
                if value == 1:
                    raise RuntimeError("restore refused")
                self._marker = value

        timeline = RestoreRaisingTimeline(items=timeline._items, marker=1)

        class MovingTimelineObject(FakeTimelineObject):
            def rollTo(self, roll_before):
                result = super().rollTo(roll_before)
                if result and roll_before:
                    timeline._marker = 0
                return result

        row_type = MovingTimelineObject
    else:
        row_type = FakeTimelineObject
    design.timeline = timeline
    made = []

    def add(inp):
        row = row_type("Sweep1", 1)
        feature = MarkerRequiredSweepFeature(sf.body_names, inp, row, fraction=fraction)
        row.entity = feature
        made.append(feature)
        return feature

    sf.add = add
    return sf, design, timeline, made


# ── the solid happy path ────────────────────────────────────────────────────

class TestSolid:
    def test_solid_sweep_along_path_sketch(self):
        sf, _ = _install()
        out = _payload(sw.handler(profile={"sketch": "Prof", "profile_index": 0},
                                  path="sketch:PathSketch"))
        assert out["swept"] is True
        assert out["is_solid"] is True
        assert out["as_surface"] is False
        assert out["open_profile"] is False
        assert out["path"] == "sketch:PathSketch"
        assert out["result_bodies"] == ["Body1"]
        # A closed profile with the default (solid) sets isSolid True on the input.
        assert sf.last.isSolid is True

    def test_path_sketch_hands_createpath_the_whole_collection_unchained(self):
        sf, design = _install()
        design.rootComponent.features.path_returns = _built_path(3)
        _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        feats = design.rootComponent.features
        # The path sketch has curves -> createPath is called ONCE with (collection, isChain=False).
        assert len(feats.path_calls) == 1 and feats.path_calls[0][1] is False
        assert hasattr(feats.path_calls[0][0], "add")

    def test_multiple_result_bodies_collected(self):
        _install(body_names=("R0", "R1", "R2"))
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert out["result_bodies"] == ["R0", "R1", "R2"]


# ── surface fallback + forcing ──────────────────────────────────────────────

class TestSurface:
    def test_open_profile_falls_back_to_surface(self):
        # Profile sketch has NO closed region but open curves -> an OPEN profile / SURFACE sweep.
        sf, _ = _install(closed_profiles=0, open_curves=2)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert out["open_profile"] is True
        assert out["as_surface"] is True
        assert out["is_solid"] is False
        assert "SURFACE" in out["note"]
        assert sf.last.isSolid is False

    def test_as_surface_forces_surface_off_closed_profile(self):
        # A CLOSED profile, but as_surface=True -> isSolid False (open tube), open_profile stays False.
        sf, _ = _install(closed_profiles=1)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  as_surface=True))
        assert out["is_solid"] is False
        assert out["as_surface"] is True
        assert out["open_profile"] is False
        assert sf.last.isSolid is False


# ── path from model edges ───────────────────────────────────────────────────

class TestEdgePath:
    def test_two_edge_handles_use_component_exact_list_constructor(self):
        adsk.fusion.BRepEdge = BRepEdge
        first, second = BRepEdge(curve=Line3D()), BRepEdge(curve=Line3D())
        _, design = _install(tokens={"EDGE1": first, "EDGE2": second})
        design.rootComponent.features.path_returns = _built_path(2)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path=["EDGE1", "EDGE2"]))
        call, chained = design.rootComponent.features.path_calls[0]
        assert chained is False
        assert call.count == 2 and call.item(0) is first and call.item(1) is second
        assert out["path_curves"] == 2

    def test_single_edge_path_seeds_createpath(self):
        adsk.fusion.BRepEdge = BRepEdge
        edge = BRepEdge(curve=Line3D())
        sf, design = _install(tokens={"EDGE1": edge})
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path=["EDGE1"]))
        assert out["path"] == "1 edge(s) from 1 seed handle"
        feats = design.rootComponent.features
        # A single edge goes to createPath with chaining requested, not to Path.create.
        assert feats.path_calls and feats.path_calls[0][0] is edge

    def test_path_reports_the_edges_the_built_path_holds_not_the_one_passed(self):
        # The seed expanded: the swept path holds 14 edges though ONE handle was named. The payload
        # describes the path Fusion built, so an agent reading 'path' is not told the sweep ran over
        # a single edge.
        adsk.fusion.BRepEdge = BRepEdge
        edge = BRepEdge(curve=Line3D())
        sf, design = _install(tokens={"EDGE1": edge})
        design.rootComponent.features.path_returns = _built_path(14)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path=["EDGE1"]))
        assert out["path"] == "14 edge(s) from 1 seed handle"

    def test_bad_edge_handle_errors(self):
        adsk.fusion.BRepEdge = BRepEdge
        _install(tokens={})
        res = sw.handler(profile={"sketch": "Prof"}, path=["NOPE"])
        assert res["isError"] is True
        assert "handle did not resolve" in error_message(res)


# ── operation + orientation + target_bodies ─────────────────────────────────

class TestOptions:
    def test_operation_echoed(self):
        _install()
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  operation="join"))
        assert out["operation"] == "join"

    def test_orientation_parallel_applied(self):
        # Pin that the parallel keyword actually reaches the input via the SweepOrientationTypes enum.
        sf, _ = _install()
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  orientation="parallel"))
        assert out["orientation"] == "parallel"
        assert sf.last.orientation == adsk.fusion.SweepOrientationTypes.ParallelOrientationType

    def test_plain_profile_controls_reach_the_native_value_inputs(self, monkeypatch):
        monkeypatch.setattr(adsk.core.ValueInput, "createByString",
                            staticmethod(lambda value: types.SimpleNamespace(stringValue=value)),
                            raising=False)
        monkeypatch.setattr(adsk.core.ValueInput, "createByReal",
                            staticmethod(lambda value: types.SimpleNamespace(realValue=value)),
                            raising=False)
        sf, design = _install()
        _attach_feature_timeline(sf, design)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  twist_deg=45, taper_deg=8, path_fraction=0.5))
        assert sf.last.twistAngle.stringValue == "45.0 deg"
        assert sf.last.taperAngle.stringValue == "8.0 deg"
        assert sf.last.distanceOne.realValue == 0.5
        assert out["sweep_input_setters"] == {
            "isSolid": True, "orientation": True, "twistAngle": True,
            "taperAngle": True, "distanceOne": True}
        assert all(row["matches"] for row in out["sweep_parameters"].values())

    def test_requested_parameters_are_read_only_while_feature_is_rolled_back(self, monkeypatch):
        _sf, _design, timeline, made = _install_rolled_parameter_feature(monkeypatch)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  twist_deg=45, taper_deg=8, path_fraction=0.5))
        assert all(row["matches"] for row in out["sweep_parameters"].values())
        assert [name for name, rolled in made[0].parameter_reads] == [
            "twistAngle", "taperAngle", "distanceOne"]
        assert all(rolled for _name, rolled in made[0].parameter_reads)
        assert timeline.markerPosition == 1

    def test_parameter_read_marker_restore_failure_is_an_error(self, monkeypatch):
        _sf, _design, timeline, made = _install_rolled_parameter_feature(
            monkeypatch, restore_failure=True)
        result = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                            path_fraction=0.5)
        assert result["isError"] is True
        assert "timeline marker" in result["message"]
        assert "Sweep1" in result["message"] and "design_delete_feature" in result["message"]
        assert made[0].parameter_reads == [("distanceOne", True)]
        assert timeline.markerPosition == 0

    def test_retained_parameter_mismatch_stays_an_error_after_rollback(self, monkeypatch):
        _sf, _design, timeline, made = _install_rolled_parameter_feature(
            monkeypatch, fraction=0.75)
        result = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                            path_fraction=0.5)
        assert result["isError"] is True
        assert "parameter reads 0.75" in result["message"]
        assert made[0].parameter_reads == [("distanceOne", True)]
        assert timeline.markerPosition == 1

    def test_plain_profile_angle_expression_keeps_requested_precision(self, monkeypatch):
        monkeypatch.setattr(adsk.core.ValueInput, "createByString",
                            staticmethod(lambda value: types.SimpleNamespace(stringValue=value)),
                            raising=False)
        sf, design = _install()
        _attach_feature_timeline(sf, design)
        _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                            twist_deg=33.3333333, taper_deg=-12.3456789))
        assert sf.last.twistAngle.stringValue == "33.3333333 deg"
        assert sf.last.taperAngle.stringValue == "-12.3456789 deg"

    def test_guide_path_is_created_but_plain_profile_controls_refuse_before_build(self, monkeypatch):
        guide = _sketch("GuideSketch", curves=2)
        sf, design = _install(extra_sketches=[guide])
        refused = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                             guide_path="sketch:GuideSketch", twist_deg=45)
        assert refused["isError"] is True and "exclude 'guide_path'" in refused["message"]
        assert sf.last is None
        monkeypatch.setattr(sw._common, "rolled_to",
                            lambda design, feature, read, subject: (read(), None))
        monkeypatch.setattr(sw, "_sweep_path_identity", lambda path: ("guide-member",))
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  guide_path="sketch:GuideSketch"))
        assert sf.last.guideRail is design.rootComponent.features.path_returns
        assert out["guide_path"] == "sketch:GuideSketch" and out["guide_path_curves"] == 1
        assert out["guide_path_verified"] is True

    def test_path_fraction_rejects_nonfinite_or_out_of_range_values(self):
        _install()
        for value in (float("nan"), -0.01, 1.01):
            res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                             path_fraction=value)
            assert res["isError"] is True and "path_fraction" in res["message"]

    def test_a_join_landing_a_new_body_names_model_combine(self):
        _install(bodies=[BRepBody("Bar")])
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  operation="join"))
        assert "landed a NEW body (Body1)" in out["note"]
        assert "model_combine(join)" in out["note"]

    def test_a_join_that_grew_the_body_already_there_appends_nothing(self):
        # the feature's result body IS the one the component held - the join fused, say nothing
        _install(bodies=[BRepBody("Body1")])
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  operation="join"))
        assert "NEW body" not in out["note"]

    def test_target_bodies_rejected_on_new(self):
        _install()
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                         target_bodies=["Body1"])
        assert res["isError"] is True and "target_bodies" in res["message"]

    def test_target_bodies_unresolved_errors_on_cut(self):
        _install()
        # A cut allows target_bodies, but an unresolvable name is a clean BodyRefList error - the
        # mutation never runs, so a wrong scope can't silently pass through.
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                         operation="cut", target_bodies=["Missing"])
        assert res["isError"] is True and "Missing" in res["message"]


# ── guards ──────────────────────────────────────────────────────────────────

class TestGuards:
    def test_missing_profile(self):
        _install()
        res = sw.handler(profile=None, path="sketch:PathSketch")
        assert res["isError"] is True and "profile" in res["message"].lower()

    def test_unknown_sketch_profile(self):
        _install()
        res = sw.handler(profile={"sketch": "NoSuch"}, path="sketch:PathSketch")
        assert res["isError"] is True and "sketch" in res["message"].lower()

    def test_unknown_path_sketch(self):
        _install()
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:NoPath")
        assert res["isError"] is True and "NoPath" in res["message"]

    def test_bad_operation(self):
        _install()
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch", operation="weld")
        assert res["isError"] is True and "operation" in res["message"].lower()

    def test_bad_orientation(self):
        _install()
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                         orientation="sideways")
        assert res["isError"] is True and "orientation" in res["message"].lower()

    def test_no_active_design(self):
        _install()
        assert_no_active_design(sw, sw.handler,
                                profile={"sketch": "Prof"}, path="sketch:PathSketch")


# ── honesty contract ────────────────────────────────────────────────────────

class TestHonesty:
    def test_no_body_created_is_error(self):
        # add() returns a feature with ZERO bodies on a 'new' op -> a silent no-op; must be isError.
        _install(body_names=())
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch")
        assert res["isError"] is True and "no body" in res["message"].lower()

    def test_add_returning_none_is_error(self):
        sf, _ = _install()
        sf.add_returns_none = True
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch")
        assert res["isError"] is True and "no feature" in res["message"].lower()

    def test_createinput_failure_surfaces(self):
        sf, _ = _install()
        sf.create_raises = True
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch")
        assert res["isError"] is True and "start sweep" in res["message"].lower()

    def test_add_failure_surfaces(self):
        sf, _ = _install()
        sf.add_raises = True
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch")
        assert res["isError"] is True and "sweep failed" in res["message"].lower()


# ── a cut/intersect must PROVE it moved material ────────────────────────────
#
# A sweep whose path runs past the body still hands back a healthy feature with result bodies, so
# the feature object cannot tell a real cut from a no-op. Only the volumes of the bodies it could
# act on - the participants when target_bodies scopes it, otherwise the host's solids - can.

def _add_moving_volume(sf, *changes, rolled_back=None):
    """Make sweepFeatures.add apply (body, new_volume) pairs - the material effect a real
    cut/intersect has between the pre- and post-mutation reads. `rolled_back` collects the
    feature's deleteMe() calls, which is how the scoped no-op path reports its rollback."""
    def _add(inp):
        for body, volume in changes:
            body.volume = volume
        feature = FakeSweepFeature(bodies_names=sf.body_names, is_solid=inp.isSolid)
        if rolled_back is not None:
            feature.deleteMe = lambda: rolled_back.append(True) or True
        return feature
    sf.add = _add


class TestRetainedFeatureDisclosure:
    def test_a_sweep_that_made_no_body_names_the_feature_and_its_delete_call(self):
        _install(body_names=())
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch")
        assert "created no body" in assert_names_retained(res, "Sweep1")

    def test_an_unread_result_body_count_is_unknown_not_zero(self):
        sf, _ = _install(body_names=())
        add = sf.add

        def unread(inp):
            feature = add(inp)
            feature.bodies = None
            return feature
        sf.add = unread
        msg = assert_names_retained(sw.handler(profile={"sketch": "Prof"},
                                               path="sketch:PathSketch"), "Sweep1")
        assert "result bodies did not read" in msg and "created no body" not in msg


class TestCutMovesMaterial:
    def test_unscoped_cut_that_moves_no_volume_is_an_error(self):
        _install(bodies=[BRepBody("Bar", volume=12.0)])
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch", operation="cut")
        assert res["isError"] is True
        assert "changed nothing" in res["message"] and "'Root'" in res["message"]
        # unscoped: the cut could have reached a co-located component this sample never read, so the
        # feature is LEFT and named, never silently rolled back
        assert "design_delete_feature" in res["message"]

    def test_scoped_cut_that_moves_no_volume_rolls_the_feature_back(self):
        bar = BRepBody("Bar", volume=12.0)
        sf, _ = _install(bodies=[bar])
        rolled = []
        _add_moving_volume(sf, rolled_back=rolled)
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch", operation="cut",
                         target_bodies=["Bar"])
        assert res["isError"] is True
        assert "changed nothing" in res["message"] and "Bar" in res["message"]
        # only a participant can be affected, so nothing landed anywhere - safe to remove
        assert rolled == [True] and "Deleting it returned True." in res["message"]

    def test_scoped_cut_samples_only_the_participants(self):
        # A volume that moved on a body OUTSIDE 'target_bodies' is not this cut's effect - sampling
        # the whole component instead of the participants would pass this no-op as a success.
        bar, other = BRepBody("Bar", volume=12.0), BRepBody("Other", volume=5.0)
        sf, _ = _install(bodies=[bar, other])
        _add_moving_volume(sf, (other, 1.0))
        res = sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch", operation="cut",
                         target_bodies=["Bar"])
        assert res["isError"] is True and "changed nothing" in res["message"]

    def test_cut_that_removed_material_publishes_the_delta(self):
        bar = BRepBody("Bar", volume=12.0)
        sf, _ = _install(bodies=[bar])
        _add_moving_volume(sf, (bar, 9.5))
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  operation="cut"))
        assert out["volume_delta_cm3"] == -2.5      # signed: material LEFT the body

    def test_a_consumed_body_is_not_read_as_a_no_op(self):
        # A body the cut consumed whole stops reporting a volume, so it contributes no delta - the
        # untouched second body's 0 must not become "nothing happened".
        eaten, kept = BRepBody("Eaten", volume=4.0), BRepBody("Kept", volume=8.0)
        sf, _ = _install(bodies=[eaten, kept])
        _add_moving_volume(sf, (eaten, None))
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  operation="cut"))
        assert out["swept"] is True

    def test_a_new_body_sweep_is_never_volume_gated(self):
        _install(bodies=[BRepBody("Bar", volume=12.0)])
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert out["swept"] is True and "volume_delta_cm3" not in out

    def test_unreadable_volumes_neither_error_nor_publish_a_delta(self):
        _install(bodies=[BRepBody("Bar", volume=None)])
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  operation="cut"))
        assert out["swept"] is True and "volume_delta_cm3" not in out


# ── cross-component hosting: the feature lands on the profile's OWNER ────────────────────────────

def _owned_profile(owner):
    """A closed profile whose parentSketch.parentComponent names its OWNING component - the chain
    profile_host_component reads to decide where the feature is built."""
    return Profile(parent_sketch=_sketch("Prof", owner=owner))


def _install_two_component(body_names=("Body1",)):
    """Root is the ACTIVE component; a SUB-component 'Frame' owns the profile + the path sketch. Each
    component carries its OWN features surface, so the test can tell WHICH one the sweep was built on.
    Returns (root_features, sub_features, design)."""
    from conftest import MakeComp
    root_sf = FakeSweepFeatures(body_names=body_names)
    root = MakeComp(name="Root", bodies=())
    root.features = FakeFeatures(root_sf)
    root.createOpenProfile = lambda coll, chain: FakeOpenProfile()
    root.sketches = _NamedCollection([])

    sub_sf = FakeSweepFeatures(body_names=body_names)
    sub = MakeComp(name="Frame", bodies=())
    sub.features = FakeFeatures(sub_sf)
    sub.createOpenProfile = lambda coll, chain: FakeOpenProfile()
    # The profile is OWNED by the sub-component; the path sketch lives there too.
    prof_sketch = _sketch("Prof", profiles=[_owned_profile(sub)])
    sub.sketches = _NamedCollection([prof_sketch, _sketch("PathSketch", curves=3)])

    design = make_design(comp=root, all_components=[root, sub])
    install(sw, design)
    return root_sf, sub_sf, design


class TestCrossComponentHost:
    def test_sweep_is_built_on_the_profiles_owning_component(self):
        # The profile is owned by sub-component 'Frame' while ROOT is active. Handing another
        # component's profile to the ACTIVE component's features raises bSet live, so the feature
        # must be created on the OWNER's features - proven here by which features object got the call.
        root_sf, sub_sf, _ = _install_two_component()
        out = _payload(sw.handler(profile={"sketch": "Prof", "profile_index": 0},
                                  path="sketch:PathSketch"))
        assert out["swept"] is True
        assert sub_sf.last is not None       # the OWNER built the sweep
        assert root_sf.last is None          # NOT the active/root component (would be the bSet trap)


def _install_same_name_in_two(sketch_name="Prof"):
    """Two components BOTH holding a sketch of one name - what Fusion produces by default, since it
    numbers sketches per component from 1. Each carries its own features surface, so which component
    the scope selected is readable. Returns (alpha_features, beta_features, design)."""
    from conftest import MakeComp
    made = []
    for name in ("Alpha", "Beta"):
        sf = FakeSweepFeatures(body_names=("Body1",))
        comp = MakeComp(name=name, bodies=())
        comp.features = FakeFeatures(sf)
        comp.createOpenProfile = lambda coll, chain: FakeOpenProfile()
        comp.sketches = _NamedCollection([_sketch(sketch_name, profiles=[_owned_profile(comp)]),
                                          _sketch("PathSketch", curves=3)])
        made.append((sf, comp))
    (alpha_sf, alpha), (beta_sf, beta) = made
    design = make_design(comp=alpha, all_components=[alpha, beta])
    install(sw, design)
    return alpha_sf, beta_sf, design


class TestComponentScope:
    """SKETCH-6: the {sketch, profile_index} selector resolves a sketch BY NAME, so a name two
    components carry identifies nothing. The scope input is what makes the refusal performable - and
    it has to SELECT, not just reword the message."""

    def test_the_scope_selects_that_components_own_sketch(self):
        # asserted on WHICH component built the feature: both hold a 'Prof', so a scope that were
        # ignored (or first-matched) would build on Alpha whatever the caller asked for.
        alpha_sf, beta_sf, _ = _install_same_name_in_two()
        out = _payload(sw.handler(profile={"sketch": "Prof", "profile_index": 0},
                                  path="sketch:PathSketch", component="Beta"))
        assert out["swept"] is True
        assert beta_sf.last is not None and alpha_sf.last is None

    def test_the_other_spelling_selects_the_other_component(self):
        alpha_sf, beta_sf, _ = _install_same_name_in_two()
        _payload(sw.handler(profile={"sketch": "Prof", "profile_index": 0},
                            path="sketch:PathSketch", component="Alpha"))
        assert alpha_sf.last is not None and beta_sf.last is None

    def test_no_scope_refuses_the_shared_name_naming_this_tools_input(self):
        _install_same_name_in_two()
        res = sw.handler(profile={"sketch": "Prof", "profile_index": 0}, path="sketch:PathSketch")
        assert res["isError"] is True
        assert "2 sketches are named 'Prof'" in res["message"]
        assert "as 'component'" in res["message"] and "Rename" not in res["message"]

    def test_the_component_scope_is_declared_on_the_wire(self):
        # the schema is strict, so a remedy naming an input no property declares would be a call the
        # tool's own schema rejects - the input and the kind's scope ship together or not at all.
        sd = load_tool("_sketch_detail")
        assert sw.sweep_tool.input_schema["properties"]["component"] == sd.COMPONENT_SCOPE[1]

    def test_the_open_curve_fallback_is_scoped_too(self):
        # the open-profile fallback resolves through the SAME scoped walk as the closed path: an
        # active-component-only lookup there builds from a different component's same-named sketch.
        from conftest import MakeComp
        made = []
        for name in ("Alpha", "Beta"):
            sf = FakeSweepFeatures(body_names=("Body1",))
            comp = MakeComp(name=name, bodies=())
            comp.features = FakeFeatures(sf)
            comp.createOpenProfile = lambda coll, chain: FakeOpenProfile()
            comp.sketches = _NamedCollection([_sketch("Prof", profiles=[], curves=2, owner=comp),
                                              _sketch("PathSketch", curves=3, owner=comp)])
            made.append((sf, comp))
        (alpha_sf, alpha), (beta_sf, beta) = made
        install(sw, make_design(comp=alpha, all_components=[alpha, beta]))
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch",
                                  component="Beta"))
        assert out["open_profile"] is True
        assert beta_sf.last is not None and alpha_sf.last is None


# ── declared outputs ────────────────────────────────────────────────────────

def test_declared_returns_present_in_payload():
    _install()
    out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
    for spec in sw.RETURNS:
        assert spec.assert_present(out) == "", spec.key


def test_the_path_description_states_the_tangent_continuity_rule():
    # measured: one seed chains by TANGENT CONTINUITY - a sharp corner stops it, open vs closed
    # decides nothing (a tangent-continuous closed loop chained all 8 edges from one seed). So the
    # wire may not promise chaining unconditionally, nor claim a closed loop refuses to chain; what
    # a seed actually reached is only knowable from the reported count.
    desc = sw.sweep_tool.to_dict()["inputSchema"]["properties"]["path"]["description"]
    assert "TANGENT connections only" in desc
    assert "'path' count is the truth" in desc
    assert "auto-chain" not in desc.lower()
    assert "closed loop" not in desc.lower() and "seed edge alone" not in desc


# ── path_curves: what the built path HOLDS, beside what the request named ───────────────────────
#
# Chaining follows tangent continuity, so a 'sketch:<name>' path can chain a single curve out of a
# three-curve sketch and sweep a stub of the intended run. Both counts ride on the payload so the
# shortfall is visible without measuring the body.

class TestPathCurves:
    def test_sketch_path_publishes_both_counts(self):
        sf, design = _install()
        design.rootComponent.features.path_returns = _built_path(3)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert out["path_curves"] == 3
        assert out["path_sketch_curves"] == 3

    def test_a_chain_that_stopped_short_warns_naming_both_counts(self):
        # The bail case: 1 of the sketch's 3 curves chained, and every other signal (a feature, a
        # body, is_solid) reports a clean sweep.
        sf, design = _install()
        design.rootComponent.features.path_returns = _built_path(1)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert out["path_curves"] == 1 and out["path_sketch_curves"] == 3
        assert "chained 1 of the sketch's 3 curves" in out["note"]
        assert "sketch_get" in out["note"] and "sharp corner" not in out["note"]

    def test_a_full_chain_does_not_warn(self):
        sf, design = _install()
        design.rootComponent.features.path_returns = _built_path(3)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert "WARNING" not in out["note"]

    def test_a_two_of_three_chain_names_the_left_out_curve_beside_a_bare_label(self):
        sf, design = _install()
        _two_of_three(design.rootComponent, "PathSketch")
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert out["path"] == "sketch:PathSketch" and out["path_curves"] == 2
        assert "chained 2 of the sketch's 3 curves" in out["note"]
        assert "Not in the path: line:1." in out["note"]

    def test_an_edge_path_publishes_the_count_with_no_sketch_to_compare(self):
        adsk.fusion.BRepEdge = BRepEdge
        sf, design = _install(tokens={"EDGE1": BRepEdge(curve=Line3D())})
        design.rootComponent.features.path_returns = _built_path(14)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path=["EDGE1"]))
        assert out["path_curves"] == 14
        # no source sketch exists for an edge path - a null here would read as an unreadable sketch
        assert "path_sketch_curves" not in out
        assert "WARNING" not in out["note"]

    def test_an_unreadable_path_count_is_published_as_unknown(self):
        # The Path would not answer .count: path_curves is None (unknown), and nothing claims a
        # shortfall it could not measure.
        sf, design = _install()
        design.rootComponent.features.path_returns = types.SimpleNamespace()
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert out["path_curves"] is None
        assert "WARNING" not in out["note"]

    def test_a_longer_chain_than_the_sketch_carries_does_not_warn(self):
        # A path holding at least the sketch's curves is not a shortfall - only fewer is.
        sf, design = _install()
        design.rootComponent.features.path_returns = _built_path(4)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert "WARNING" not in out["note"]


class TestConstructionCurvesAreNotPathCurves:
    def _path_sketch(self, design):
        return design.rootComponent.sketches.itemByName("PathSketch")

    def test_a_construction_line_is_not_counted_as_a_path_curve(self):
        # sketchCurves counts CONSTRUCTION geometry too, and construction is not part of any path.
        # Counting it reports a shortfall on a path that chained everything there was to chain, and
        # blames tangency for it - a false warning with the wrong cause on a perfectly good sweep.
        sf, design = _install()
        self._path_sketch(design).sketchCurves._items.append(
            types.SimpleNamespace(isConstruction=True))
        design.rootComponent.features.path_returns = _built_path(3)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert out["path_sketch_curves"] == 3        # 4 curves, one of them construction
        assert "WARNING" not in out["note"]

    def test_a_real_shortfall_still_warns_when_construction_is_present(self):
        # The construction filter must not silence a genuine short chain.
        sf, design = _install()
        self._path_sketch(design).sketchCurves._items.append(
            types.SimpleNamespace(isConstruction=True))
        design.rootComponent.features.path_returns = _built_path(1)
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert out["path_sketch_curves"] == 3
        assert "chained 1 of the sketch's 3 curves" in out["note"]

    def test_a_curve_whose_construction_flag_will_not_read_counts_as_real(self):
        # The conservative side: an unreadable flag can only shrink a warning, never invent one.
        sf, design = _install()
        out = _payload(sw.handler(profile={"sketch": "Prof"}, path="sketch:PathSketch"))
        assert out["path_sketch_curves"] == 3        # the plain fixture curves read no flag at all
