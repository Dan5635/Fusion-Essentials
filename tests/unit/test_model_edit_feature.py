"""Checks the measured feature editor's typed operands, retained controls and restore proof."""

from types import SimpleNamespace
import math

import adsk.core
import adsk.fusion
import pytest


@pytest.fixture
def bounded_arc_operand(scene, monkeypatch):
    feature, _timeline, _new_axis, _old_axis, _design, body = scene
    class _ArcOperand(SimpleNamespace):
        pass
    sketch = SimpleNamespace(name="ArcPath", parentComponent=feature.parentComponent)
    arc = _ArcOperand(entityToken="arc-token", parentSketch=sketch, assemblyContext=None,
        geometry=SimpleNamespace(center=FakePoint(0, 0, 0), normal=FakeVector3D(0, 0, 1),
            referenceVector=FakeVector3D(1, 0, 0), radius=1.0, startAngle=0.0, endAngle=math.pi / 2))
    monkeypatch.setattr(adsk.fusion, "SketchArc", _ArcOperand)
    monkeypatch.setattr(adsk.fusion, "SketchCurve", _ArcOperand)
    monkeypatch.setattr(mod._inputs, "placed_ends", lambda *_args: [[1, 0, 0], [0, 1, 0]])
    monkeypatch.setattr(mod._inputs, "placed_handle", lambda *_args: "arc-token")
    monkeypatch.setattr(mod._inputs, "sketch_entity_address", lambda _entity: "ArcPath/arc:0")
    original = mod._edit.reference_descriptor
    monkeypatch.setattr(mod._edit, "reference_descriptor", lambda entity, role:
        ({"handle": "body-token", "kind": "entity", "owner": {"component": "Part"},
          "geometry": {"volume": 1.0}} if role == "entities" else original(entity, role)))
    path = SimpleNamespace(count=1, item=lambda _i: SimpleNamespace(entity=arc))
    pattern = SimpleNamespace(objectType="adsk::fusion::PathPatternFeature", name="Pattern1",
        parentComponent=feature.parentComponent, path=path, inputEntities=[body],
        patternElements=SimpleNamespace(count=3), suppressedElementsIds=[],
        quantity=SimpleNamespace(expression="3"), isOrientationAlongPath=False,
        timelineObject=FakeTimelineObject("Pattern1", 2))
    return pattern, arc, path


def test_curved_path_descriptor_reads_both_callers_and_distinguishes_complements(bounded_arc_operand):
    pattern, arc, path = bounded_arc_operand
    state, definition, unavailable = mod._edit.feature_edit_state(pattern)
    assert unavailable == {} and definition["path"]["references"][0]["handle"] == "ArcPath/arc:0"
    resolved = mod._edit.feature_reference_state(path, "path")
    assert mod._edit._same_reference(state["path"][0], resolved[0]) is True
    geometry = resolved[0][1]["geometry"]
    assert geometry["radius_cm"] == 1.0
    assert geometry["interior_cm"] == pytest.approx([math.sqrt(.5), math.sqrt(.5), 0])
    arc.geometry.endAngle += 2 * math.pi
    changed = mod._edit.feature_reference_state(path, "path")
    assert mod._edit._same_reference(resolved[0], changed[0]) is False
    assert mod._edit._reference_kind(arc, "edges") is None
    assert mod._edit._reference_kind(arc, "axis") is None

from _datum_fakes import datum_scene
import test_doc_insert_derive as derive_fakes
from tests.fakes.design import MirrorPlaneResetScene
from conftest import (BRepBody, BRepEdge, BRepFace, FakeFeature, FakeTimeline, FakeTimelineObject,
                      FakePoint, MakeComp, MakeDesign, Profile, Sketch, error_message,
                      FakeVector3D, install, load_tool, make_bbox, payload,
                      _FakeObjectCollection)

mod = load_tool("model_edit_feature")


class Revolve(FakeFeature):
    """A shared timeline feature fake with the measured Revolve definition surface."""

    def __init__(self, component, body, timeline_object):
        super().__init__(name="Revolve1", bodies=[body], entity_token="feature-token",
                         parent_component=component, timeline_object=timeline_object)
        self.objectType = "adsk::fusion::RevolveFeature"
        self.isParametric = self.isValid = True
        self.isSuppressed = False
        self.baseFeature = None
        self.profile = SimpleNamespace(entityToken="profile-token")
        self.operation = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        self.isSolid = True
        self.extentDefinition = SimpleNamespace(angle=SimpleNamespace(expression="90 deg"),
                                                isSymmetric=False)
        self._axis = None

    @property
    def axis(self):
        return self._axis

    @axis.setter
    def axis(self, value):
        self._axis = value


@pytest.fixture
def scene(monkeypatch):
    monkeypatch.setattr(adsk.fusion, "BRepEdge", BRepEdge)
    monkeypatch.setattr(adsk.fusion, "BRepFace", BRepFace)
    monkeypatch.setattr(mod._edit.adsk.fusion.AngleExtentDefinition, "cast", lambda extent: extent)
    component = MakeComp(name="Part", entity_token="part-token")
    body = BRepBody("Body1", volume=1, area=6, bbox=make_bbox((0, 0, 0), (1, 1, 1)),
                    parent_component=component)
    component.bRepBodies = component.bRepBodies.__class__([body])
    line_type = adsk.core.Curve3DTypes.Line3DCurveType
    point = FakePoint
    before_axis = BRepEdge(SimpleNamespace(curveType=line_type), start=point(0, 0, 0),
                           end=point(1, 0, 0),
                           point_on_edge=SimpleNamespace(x=.5, y=0, z=0),
                           entity_token="axis-before", body=body)
    before_axis.startVertex.body = before_axis.endVertex.body = body
    new_axis = BRepEdge(SimpleNamespace(curveType=line_type), start=point(0, 1, 0),
                        end=point(1, 1, 0),
                        point_on_edge=SimpleNamespace(x=.5, y=1, z=0),
                        entity_token="axis-after", body=body)
    new_axis.startVertex.body = new_axis.endVertex.body = body
    timeline_object = FakeTimelineObject("Revolve1", 1, entity=None)
    timeline = FakeTimeline([FakeTimelineObject("Previous", 0), timeline_object,
                             FakeTimelineObject("Next", 2)], marker=3)
    design = MakeDesign(comp=component, timeline=timeline)
    feature = Revolve(component, body, timeline_object)
    timeline_object.entity = feature
    feature._axis = before_axis
    timeline_object.rollTo = lambda before: (
        setattr(timeline, "markerPosition", 1 if before else 2) or True)
    monkeypatch.setattr(mod._common, "design", lambda: design)
    monkeypatch.setattr(mod._inputs, "_resolve_token_entity",
                        lambda _design, token: {"axis-before": before_axis,
                                                "axis-after": new_axis}.get(token))
    monkeypatch.setattr(mod._edit, "_profile_edit_definition", lambda _profile: ({
        "profile_handle": "profile-token", "source_sketch": "Profile", "source_component": "Part",
        "profile_index": 0}, {"area": 1, "centroid": [0, 0, 0], "loop_count": 1}))
    monkeypatch.setattr(mod._edit, "health", lambda *_args: {"errors": [], "warnings": []})
    monkeypatch.setattr(mod._edit, "same_feature", lambda *_args: True)
    monkeypatch.setattr(mod._edit, "feature_geometry_snapshot", lambda _design: {
        "bodies": {("body-token", "urn:fixture"): {
            "component": "Part", "body": "Body1", "shape": {"measure": 1}}},
        "occurrences": {}})
    return feature, timeline, new_axis, before_axis, design, body


@pytest.fixture
def offset_scene(monkeypatch, scene):
    feature, timeline, _new_axis, _before_axis, design, body = scene
    surface_type = adsk.core.SurfaceTypes.PlaneSurfaceType
    before_face = BRepFace(SimpleNamespace(surfaceType=surface_type), area=1,
                           centroid=FakePoint(0, 0, 0), entity_token="offset-before",
                           body=body, point_on_face=FakePoint(0, 0, 0),
                           normal=FakeVector3D(0, 0, 1), param_reversed=False)
    after_face = BRepFace(SimpleNamespace(surfaceType=surface_type), area=1,
                          centroid=FakePoint(0, 1, 0), entity_token="offset-after",
                          body=body, point_on_face=FakePoint(0, 1, 0),
                          normal=FakeVector3D(0, 0, 1), param_reversed=False)
    feature.objectType = "adsk::fusion::OffsetFeature"
    feature.name = "Offset1"
    feature.timelineObject.name = "Offset1"
    feature.entities = [before_face]
    feature.distance = SimpleNamespace(expression="5 mm")
    feature.isChainSelection = True
    feature.offsetType = "fixture-offset-type"
    feature.operation = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    calls = []

    def set_entities(collection, is_chain):
        values = list(collection)
        calls.append((type(collection), values, is_chain))
        feature.entities = collection
        feature.isChainSelection = is_chain
        return True

    feature.setInputEntities = set_entities
    install(mod, design)
    monkeypatch.setattr(mod._inputs.GeometryHandleList, "resolve",
                        lambda _self, _raw: ([after_face], None))
    monkeypatch.setattr(mod._edit, "reference_descriptor",
                        lambda entity, _role: {"handle": entity.entityToken, "kind": "face",
                                               "name": entity.entityToken,
                                               "owner": {"component": "Part", "occurrence": None},
                                               "geometry": {"fixture": entity.entityToken}})
    return feature, timeline, before_face, after_face, calls


@pytest.fixture
def rib_scene(monkeypatch, scene):
    feature, timeline, _new_axis, _before_axis, design, _body = scene
    feature.objectType = "adsk::fusion::RibFeature"
    feature.name = feature.timelineObject.name = "Rib1"
    original = SimpleNamespace(entityToken="guide-original")
    replacement = SimpleNamespace(entityToken="guide-replacement")
    rejected = SimpleNamespace(entityToken="guide-rejected")
    feature.curves = [original]
    feature.thickness = SimpleNamespace(expression="2 mm")
    feature.extentType = 1
    feature.depth = None
    feature.isSymmetric = True
    feature.isFlipped = False
    feature.timelineObject.name = "Rib1"
    paths = {key: SimpleNamespace(count=1,
        item=lambda _i, curve=curve: SimpleNamespace(entity=curve))
        for key, curve in (("replacement", replacement), ("rejected", rejected))}
    original_shape = {"bodies": {("body-token", "urn:fixture"): {
        "component": "Part", "body": "Body1", "shape": {"measure": 1}}}, "occurrences": {}}

    def description(entity, _role):
        return {"handle": entity.entityToken, "kind": "sketch_curve",
                "name": entity.entityToken, "owner": {"component": "Part"},
                "geometry": {"id": entity.entityToken}}

    monkeypatch.setattr(mod._edit, "reference_descriptor", description)
    monkeypatch.setattr(mod._common, "native_identity",
                        lambda entity: (getattr(entity, "entityToken", None), "urn:fixture"))
    monkeypatch.setattr(mod._REFERENCES, "resolve_for",
                        lambda _raw, _feature, _action, _support:
                        (paths[_raw[0]], None) if _raw[0] in paths else (None, "unknown path"))
    monkeypatch.setattr(mod._edit, "feature_geometry_snapshot", lambda _design:
        original_shape if feature.curves[0] is original else {
            "bodies": {("body-token", "urn:fixture"): {"component": "Part", "body": "Body1",
                "shape": {"measure": 2 if feature.curves[0] is replacement else 3}}},
            "occurrences": {}})
    monkeypatch.setattr(mod._edit, "health", lambda *_args: {
        "errors": ([{"name": "Rib1"}] if feature.curves[0] is rejected else []), "warnings": []})
    monkeypatch.setattr(mod._edit, "same_feature", lambda *_args: True)
    feature.curves = [original]
    feature._guide_state = {"original": original, "replacement": replacement, "rejected": rejected}
    return feature, timeline, design


def test_rib_curve_retarget_changes_definition_and_geometry(rib_scene):
    feature, timeline, _design = rib_scene
    result = payload(mod.handler(feature="Part/Rib1@1", action="inputs",
                                 references=["replacement"]))
    assert result["edited"] is True
    assert result["definition_matches"] is True
    assert result["geometry_changed"] is True
    assert result["same_feature"] is True
    assert feature.curves == [feature._guide_state["replacement"]]
    assert result["marker_restored"] is True and timeline.markerPosition == timeline.count


def test_rib_definition_reads_native_sketch_curve_vector_without_count():
    class SketchCurveVector:
        def __init__(self, curves):
            self.curves = curves

        def __len__(self):
            return len(self.curves)

        def __iter__(self):
            return iter(self.curves)

    curve = SimpleNamespace(entityToken="guide-original")
    assert mod._edit.collection_entities(SketchCurveVector([curve])) == [curve]
    assert mod._edit.collection_entities(SketchCurveVector([curve]), cap=0) is None


def test_unhealthy_rib_curve_retarget_restores_original_definition_and_geometry(rib_scene):
    feature, timeline, _design = rib_scene
    result = mod.handler(feature="Part/Rib1@1", action="inputs", references=["rejected"])
    assert result["isError"] is True
    assert "introduced timeline health errors" in error_message(result)
    assert feature.curves == [feature._guide_state["original"]]
    assert result["details"]["edited"] is False
    assert result["details"]["restore_gaps"] == []
    assert result["details"]["same_feature"] is True
    assert result["details"]["geometry_restored"] == result["details"]["geometry_before"]
    assert timeline.markerPosition == timeline.count


def test_unhealthy_rib_curve_with_unverified_restore_reports_partial_state(rib_scene, monkeypatch):
    feature, _timeline, _design = rib_scene
    monkeypatch.setattr(mod, "_restore_value", lambda *_args: None)
    result = mod.handler(feature="Part/Rib1@1", action="inputs", references=["rejected"])
    assert result["isError"] is True
    assert result["details"]["edited"] is None
    assert result["details"]["restore_gaps"]
    assert result["details"]["geometry_restored"] != result["details"]["geometry_before"]


def test_axis_edit_uses_real_typed_resolver_reads_back_and_restores_marker(scene):
    feature, timeline, new_axis, _before_axis, _design, _body = scene
    result = payload(mod.handler(feature="Part/Revolve1@1", action="axis",
                                 references=["axis-after"]))
    assert result["definition_matches"] is True
    assert result["geometry_changed"] is False
    assert "geometry reads identical" in result["note"]
    assert result["geometry_before"]["bodies"] == [{
        "identity": ["body-token", "urn:fixture"], "component": "Part", "body": "Body1",
        "shape": {"measure": 1}}]
    assert feature.axis is new_axis
    assert result["marker_restored"] is True
    assert timeline.markerPosition == timeline.count


@pytest.fixture
def mirror_scene(scene, monkeypatch):
    revolve, timeline, _new_axis, _old_axis, design, body = scene
    planes = [BRepFace(SimpleNamespace(surfaceType=adsk.core.SurfaceTypes.PlaneSurfaceType),
        area=1, centroid=FakePoint(x, 0, 0), point_on_face=FakePoint(x, 0, 0),
        normal=FakeVector3D(1, 0, 0), param_reversed=False, body=body,
        entity_token=token) for x, token in ((0, "plane-before"), (.3, "plane-after"))]
    old_plane, new_plane = planes
    feature = MirrorPlaneResetScene(name="Mirror1", bodies=[body], parent_component=revolve.parentComponent,
        timeline_object=revolve.timelineObject, entity_token="mirror-feature-token",
        mirror={"plane": old_plane, "combine": True})
    feature.objectType = "adsk::fusion::MirrorFeature"
    feature.isParametric = feature.isValid = True
    feature.baseFeature = None
    feature.inputEntities = [body]
    feature.timelineObject.name = "Mirror1"
    feature.timelineObject.entity = feature
    install(mod, design)
    monkeypatch.setattr(mod._REFERENCES, "resolve_for",
                        lambda *_args: (new_plane, None))
    monkeypatch.setattr(mod._common, "native_identity",
                        lambda entity: (entity.entityToken, "urn:fixture"))
    monkeypatch.setattr(mod._edit, "reference_descriptor", lambda entity, role: {
        "handle": entity.entityToken, "kind": role, "name": entity.entityToken,
        "owner": {"component": "Part"}, "geometry": {"id": entity.entityToken}})

    def geometry(_design):
        changed = feature.mirrorPlane is new_plane
        joined = feature._mirror["combine"]
        shapes = ({"joined": {"volume": .864 if changed else 1.152,
                              "xmin": -.6 if changed else -1.2}}
                  if joined else {"seed": {"volume": .576, "xmin": 0},
                                  "mirror": {"volume": .576, "xmin": -.6 if changed else -1.2}})
        return {"bodies": {(name, "urn:fixture"): {
            "body": name, "component": "Part", "shape": shape}
            for name, shape in shapes.items()}, "occurrences": {}}

    monkeypatch.setattr(mod._edit, "feature_geometry_snapshot", geometry)
    monkeypatch.setattr(mod._edit, "health", lambda *_args: {
        "errors": ([{"name": "Mirror1"}] if feature._mirror.get("unhealthy")
                   and feature.mirrorPlane is new_plane else []), "warnings": []})
    return feature, timeline, old_plane, new_plane


@pytest.mark.parametrize("combine", [True, False])
def test_mirror_plane_reset_preserves_the_prior_combine_setting(mirror_scene, combine):
    feature, timeline, _old_plane, new_plane = mirror_scene
    feature._mirror["combine"] = combine
    out = payload(mod.handler(feature="Part/Mirror1@1", action="plane", references=["new-plane"]))
    assert feature.mirrorPlane is new_plane and feature.isCombine is combine
    assert feature._mirror["plane_writes"] == [new_plane]
    assert feature._mirror["combine_writes"] == [combine]
    assert out["definition_before"]["is_combine"] is combine
    assert out["definition_after"]["is_combine"] is combine
    assert out["definition_matches"] is True and out["geometry_changed"] is True
    shapes = [row["shape"] for row in out["geometry_after"]["bodies"]]
    assert shapes == ([{"volume": .864, "xmin": -.6}] if combine else
                      [{"volume": .576, "xmin": 0}, {"volume": .576, "xmin": -.6}])
    assert timeline.markerPosition == timeline.count


def test_failed_mirror_edit_restores_plane_and_combine_with_geometry(mirror_scene):
    feature, timeline, old_plane, new_plane = mirror_scene
    feature._mirror["unhealthy"] = True
    result = mod.handler(feature="Part/Mirror1@1", action="plane", references=["new-plane"])
    assert result["isError"] is True and "health errors" in result["message"]
    details = result["details"]
    assert feature.mirrorPlane is old_plane and feature.isCombine is True
    assert feature._mirror["plane_writes"] == [new_plane, old_plane]
    assert feature._mirror["combine_writes"] == [True, True]
    assert details["definition_restored"] == details["definition_before"]
    assert details["geometry_restored"] == details["geometry_before"]
    assert details["edited"] is False and details["restore_gaps"] == []
    assert timeline.markerPosition == timeline.count


def test_unread_mirror_combine_refuses_before_plane_assignment(mirror_scene):
    feature, timeline, old_plane, _new_plane = mirror_scene
    feature._mirror["readable"] = False
    result = mod.handler(feature="Part/Mirror1@1", action="plane", references=["new-plane"])
    assert result["isError"] is True and "is_combine" in result["message"]
    assert "unread combine flag" in result["message"]
    assert feature.mirrorPlane is old_plane
    assert feature._mirror["plane_writes"] == feature._mirror["combine_writes"] == []
    assert timeline.markerPosition == timeline.count


@pytest.mark.parametrize("dropped", [(1,), (1, 2)])
def test_dropped_mirror_combine_write_fails_and_reports_restore_gaps(mirror_scene, dropped):
    feature, timeline, old_plane, _new_plane = mirror_scene
    feature._mirror["drop_writes"] = dropped
    result = mod.handler(feature="Part/Mirror1@1", action="plane", references=["new-plane"])
    assert result["isError"] is True and "retained field" in result["message"]
    details = result["details"]
    assert details["definition_matches"] is False
    assert details["definition_after"]["is_combine"] is False
    assert len(details["geometry_after"]["bodies"]) == 2
    assert feature.mirrorPlane is old_plane
    if dropped == (1,):
        assert feature.isCombine is True and details["edited"] is False
        assert details["restore_gaps"] == []
        assert details["geometry_restored"] == details["geometry_before"]
    else:
        assert feature.isCombine is False and details["edited"] is None
        assert "the definition re-read differs from before the edit" in details["restore_gaps"]
        assert details["geometry_restored"] != details["geometry_before"]
    assert timeline.markerPosition == timeline.count


def test_silent_axis_noop_is_an_error_and_original_definition_is_verified(scene, monkeypatch):
    feature, timeline, _new_axis, _before_axis, _design, _body = scene
    monkeypatch.setattr(type(feature), "axis", property(lambda self: self._axis,
                                                         lambda _self, _value: None))
    result = mod.handler(feature="Part/Revolve1@1", action="axis", references=["axis-after"])
    assert result["isError"] is True
    assert "requested definition" in error_message(result)
    assert result["details"]["restore_gaps"] == []
    assert result["details"]["same_feature"] is True
    assert result["details"]["owner_restored"] is True
    assert result["details"]["marker_restored"] is True
    assert timeline.markerPosition == timeline.count


def test_axis_setter_that_raises_after_landing_is_compensated(scene, monkeypatch):
    feature, timeline, new_axis, before_axis, _design, _body = scene

    def raise_after_landing(value):
        feature._axis = value
        if value is new_axis:
            raise RuntimeError("landed then raised")

    monkeypatch.setattr(type(feature), "axis", property(lambda self: self._axis,
                                                         lambda _self, value: raise_after_landing(value)))
    result = mod.handler(feature="Part/Revolve1@1", action="axis", references=["axis-after"])
    assert result["isError"] is True
    assert "landed then raised" in error_message(result)
    assert feature.axis is before_axis
    assert result["details"]["restore_gaps"] == []
    assert result["details"]["same_feature"] is True
    assert result["details"]["owner_restored"] is True
    assert result["details"]["feature_health"] == {"errors": [], "warnings": []}
    assert result["details"]["geometry_before"]["bodies"][0]["identity"] == [
        "body-token", "urn:fixture"]
    assert timeline.markerPosition == timeline.count


def test_compensation_that_leaves_changed_operands_does_not_claim_unedited(scene, monkeypatch):
    feature, _timeline, new_axis, _before_axis, _design, _body = scene
    snapshot = mod._edit.feature_geometry_snapshot
    monkeypatch.setattr(type(feature), "axis", property(lambda self: self._axis,
                        lambda self, value: setattr(self, "_axis", new_axis)))
    monkeypatch.setattr(mod._edit, "feature_geometry_snapshot", lambda design:
                        None if feature.axis is new_axis else snapshot(design))
    result = mod.handler(feature="Part/Revolve1@1", action="axis", references=["axis-after"])
    assert result["isError"] is True
    assert feature.axis is new_axis
    assert result["details"]["edited"] is None and result["details"]["restore_gaps"]


def test_wrapper_equality_does_not_prove_an_unread_operand_identity(monkeypatch):
    entity = SimpleNamespace()
    monkeypatch.setattr(mod._common, "native_identity", lambda _entity: None)
    record = (entity, {"kind": "face", "owner": {}, "geometry": {}})
    assert mod._edit._same_reference(record, record) is None


def test_closed_operand_roles_refuse_wrong_cardinality_and_duplicate_faces(monkeypatch, scene):
    support = mod._edit.FEATURE_EDIT_SUPPORT
    feature, _timeline, _new_axis, _before_axis, design, body = scene
    value, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["axis-before", "axis-after"], feature, "axis", support[feature.objectType])
    assert value is None
    assert "exactly one" in reason

    face = SimpleNamespace(entityToken="same-face", body=body, area=1,
                           geometry=SimpleNamespace(surfaceType=1), isParamReversed=False,
                           centroid=SimpleNamespace(x=0, y=0, z=0))
    monkeypatch.setattr(mod._inputs.GeometryHandleList, "resolve", lambda _self, _raw: ([face, face], None))
    draft = SimpleNamespace(objectType="adsk::fusion::DraftFeature", parentComponent=feature.parentComponent)
    value, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["face-a", "face-b"], draft, "inputs", support["adsk::fusion::DraftFeature"])
    assert value is None
    assert "same face more than once" in reason


def test_reference_collections_refuse_over_cap_before_resolving(monkeypatch, scene):
    feature, _timeline, _new_axis, _before_axis, _design, _body = scene
    assert mod._edit.collection_entities([object()] * 65) is None
    assert mod._edit.collection_entities(tuple(object() for _ in range(65))) is None
    monkeypatch.setattr(mod._inputs.GeometryHandleList, "resolve",
                        lambda *_args: pytest.fail("oversize list reached the geometry resolver"))
    value, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["face-handle"] * 65,
        SimpleNamespace(objectType="adsk::fusion::DraftFeature",
                        parentComponent=feature.parentComponent),
        "inputs", mod._edit.FEATURE_EDIT_SUPPORT["adsk::fusion::DraftFeature"])
    assert value is None and "cap is 64" in reason


def test_world_axis_resolves_to_the_feature_owners_origin_axis(monkeypatch, scene):
    feature, _timeline, _new_axis, _before_axis, design, _body = scene
    x_axis = SimpleNamespace(entityToken="owner-x", parentComponent=feature.parentComponent)
    feature.parentComponent.xConstructionAxis = x_axis
    monkeypatch.setattr(mod._inputs.AxisRef, "resolve", lambda self, raw, component=None:
                        (("world", (1, 0, 0)), None))
    value, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["x"], feature, "axis", mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType])
    assert reason is None
    assert value is x_axis


def test_combine_tool_action_uses_the_existing_body_resolver(scene, monkeypatch):
    feature, _timeline, _new_axis, _before_axis, _design, body = scene
    monkeypatch.setattr(adsk.fusion, "BRepBody", BRepBody)
    combine = SimpleNamespace(objectType="adsk::fusion::CombineFeature",
                              parentComponent=feature.parentComponent)
    value, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["Body1"], combine, "tools", mod._edit.FEATURE_EDIT_SUPPORT[combine.objectType])
    assert reason is None
    assert value == [body]


def test_split_body_tool_setter_requires_a_true_result(scene):
    feature, _timeline, _new_axis, _before_axis, _design, _body = scene
    row = mod._edit.FEATURE_EDIT_SUPPORT["adsk::fusion::SplitBodyFeature"]["tools"]

    class Setter:
        isSplittingToolExtended = True

        def setSplittingTool(self, _tool, _extended):
            return False

    with pytest.raises(RuntimeError, match="did not accept"):
        mod._apply_value(Setter(), row, object(), "")


@pytest.mark.parametrize("row,value,feature", [
    (mod._edit.FEATURE_EDIT_SUPPORT["adsk::fusion::SplitBodyFeature"]["tools"],
     (object(), True), SimpleNamespace(setSplittingTool=lambda *_args: False)),
    (mod._edit.FEATURE_EDIT_SUPPORT["adsk::fusion::FilletFeature"]["inputs"]["variants"]["rule"],
     (object(),), SimpleNamespace(ruleFilletSettings=SimpleNamespace(
         setByAllEdges=lambda _faces: False))),
])
def test_compensation_setters_require_true_result(row, value, feature):
    with pytest.raises(RuntimeError, match="did not restore"):
        mod._restore_value(feature, row, value)


def test_rule_fillet_action_is_gated_by_the_measured_subtype(scene):
    feature, *_ = scene
    rule_type = adsk.fusion.FilletFeatureTypes.RuleFilletFeatureType
    full_round = adsk.fusion.FilletFeatureTypes.FullRoundFilletFeatureType
    rule = SimpleNamespace(objectType="adsk::fusion::FilletFeature", name="Rule",
                           filletFeatureType=rule_type,
                           timelineObject=FakeTimelineObject("Rule", 0))
    round_feature = SimpleNamespace(objectType="adsk::fusion::FilletFeature", name="Round",
                                    filletFeatureType=full_round,
                                    timelineObject=FakeTimelineObject("Round", 0))
    row = mod._edit.FEATURE_EDIT_SUPPORT["adsk::fusion::FilletFeature"]["inputs"]
    assert mod._edit._row_applies(rule, row) is True
    assert mod._edit._row_applies(round_feature, row) is False
    assert [item["action"] for item in mod._edit.feature_edit_rows(rule)] == ["inputs"]
    assert mod._edit.feature_edit_rows(round_feature) == []


def test_unknown_fillet_discriminator_does_not_select_an_action(scene):
    feature, *_ = scene
    feature.objectType = "adsk::fusion::FilletFeature"
    feature.filletFeatureType = None
    row = mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType]["inputs"]
    assert mod._edit._row_applies(feature, row) is False
    assert mod._edit.feature_edit_rows(feature) == []
    resolved, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["edge-handle"], feature, "inputs", mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType])
    assert resolved is None
    assert "does not take references" in reason
    result = mod.handler(feature="Part/Revolve1@1", action="inputs", references=["edge-handle"])
    assert result["isError"] is True
    assert "This feature subtype has no admitted edits" in error_message(result)
    assert "Supported: inputs" not in error_message(result)


def test_split_tool_resolver_refuses_an_unlisted_vertex(scene, monkeypatch):
    feature, *_ = scene
    class Vertex:
        pass

    vertex = Vertex()
    monkeypatch.setattr(adsk.fusion, "BRepVertex", Vertex, raising=False)
    monkeypatch.setattr(mod._inputs.PlaneRef, "resolve", lambda *_args, **_kw: (None, "not a plane"))
    monkeypatch.setattr(mod._inputs.BodyRef, "resolve", lambda *_args, **_kw: (None, "not a body"))
    monkeypatch.setattr(mod._inputs.GeometryHandle, "resolve", lambda *_args, **_kw: (vertex, None))
    split = SimpleNamespace(objectType="adsk::fusion::SplitBodyFeature",
                            parentComponent=feature.parentComponent)
    resolved, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["vertex-handle"], split, "tools", mod._edit.FEATURE_EDIT_SUPPORT[split.objectType])
    assert resolved is None
    assert "BRep body, face, sketch curve, path, or construction plane" in reason


def test_pipe_path_reapply_keeps_measured_section_controls(scene):
    feature, *_ = scene
    class Pipe:
        objectType = "adsk::fusion::PipeFeature"
        def __init__(self):
            self.sectionType = 1
            self.sectionSize = SimpleNamespace(expression="PipeSize")
            self._path = "old"
        @property
        def path(self):
            return self._path
        @path.setter
        def path(self, value):
            self._path = value
            self.sectionType = 0
            self.sectionSize.expression = "10 mm"

    pipe = Pipe()
    before = {"section_type": 1, "section_size": "PipeSize"}
    mod._apply_value(pipe, {"setter": "pipe_path"}, "new", "", before)
    assert pipe.path == "new"
    assert pipe.sectionType == 1
    assert pipe.sectionSize.expression == "PipeSize"


def test_pipe_reader_emits_usable_path_reference_and_section_controls(scene, monkeypatch):
    feature, _timeline, edge, _before_axis, _design, _body = scene
    class Path:
        count = 1
        def item(self, _index):
            return SimpleNamespace(entity=edge)

    pipe = SimpleNamespace(objectType="adsk::fusion::PipeFeature", name="Pipe1",
                           parentComponent=feature.parentComponent, path=Path(), sectionType=1,
                           sectionSize=SimpleNamespace(expression="PipeSize"),
                           timelineObject=FakeTimelineObject("Pipe1", 2))
    monkeypatch.setattr(mod._inputs, "make_handle", lambda *_args: "edge-handle")
    state, definition, unavailable = mod._edit.feature_edit_state(pipe)
    assert unavailable == {}
    assert state["section_type"] == 1 and state["section_size"] == "PipeSize"
    action = next(item for item in mod._edit.feature_edit_rows(pipe, definition)
                  if item["action"] == "path")
    assert "references=['edge-handle']" in action["call"]
    mod._restore_value(pipe, {"setter": "pipe_path"}, ("old", 1, "PipeSize"))
    assert pipe.path == "old"
    assert pipe.sectionType == 1
    assert pipe.sectionSize.expression == "PipeSize"


def test_scale_mode_roundtrip_reuses_exact_equal_expressions(monkeypatch):
    class Scale:
        isUniform = True
        scaleFactor = SimpleNamespace(expression="1.5")
        xScale = yScale = zScale = None
        def setToNonUniform(self, x, y, z):
            self.isUniform = False
            self.xScale, self.yScale, self.zScale = x, y, z
            return True
        def setToUniform(self, value):
            self.isUniform = True
            self.scaleFactor = value
            return True

    monkeypatch.setattr(adsk.core.ValueInput, "createByString",
                        lambda value: SimpleNamespace(expression=value))
    feature = Scale()
    row = mod._edit.FEATURE_EDIT_SUPPORT["adsk::fusion::ScaleFeature"]["mode"]
    expressions = mod._edit._scale_expressions(feature)
    assert expressions == ["1.5", "1.5", "1.5"]
    mod._apply_value(feature, row, None, "nonuniform")
    assert feature.isUniform is False
    assert [feature.xScale.expression, feature.yScale.expression, feature.zScale.expression] == expressions
    mod._restore_value(feature, row, (True, expressions))
    assert feature.isUniform is True
    assert feature.scaleFactor.expression == "1.5"


def test_scale_definition_offers_only_the_safe_transition():
    feature = SimpleNamespace(objectType="adsk::fusion::ScaleFeature", name="Scale1",
                              isUniform=True, scaleFactor=SimpleNamespace(expression="1.5"),
                              inputEntities=[], timelineObject=FakeTimelineObject("Scale1", 2))
    rows = mod._edit.feature_edit_rows(feature, {"is_uniform": True,
                                                "scale_expressions": ["1.5"] * 3})
    mode = next(item for item in rows if item["action"] == "mode")
    assert mode["choices"] == ["nonuniform"]
    assert "mode='nonuniform'" in mode["call"]


def test_emboss_reader_and_resolver_publish_typed_profile_handles(scene, monkeypatch):
    feature, *_ = scene
    component = feature.parentComponent
    sketch = Sketch("EmbossSketch", parent_component=component)
    profile = Profile("P", area=1.25, centroid=(.5, .25, 0), loops=1,
                      entity_token="profile-token", parent_sketch=sketch)
    profile.objectType = "adsk::fusion::Profile"
    sketch.profiles = sketch.profiles.__class__([profile])
    emboss = SimpleNamespace(objectType="adsk::fusion::EmbossFeature", name="Emboss1",
                             parentComponent=component, profiles=[profile],
                             depth=SimpleNamespace(expression="0.5 mm"),
                             timelineObject=FakeTimelineObject("Emboss1", 3))
    feature_row = mod._edit.FEATURE_EDIT_SUPPORT[emboss.objectType]
    monkeypatch.setattr(mod._inputs.ProfileRefList, "resolve",
                        lambda _self, _raw, **_kw: ([profile], None))
    monkeypatch.setattr(mod._inputs, "operand_in", lambda _label, value, *_args: (value, None))
    resolved, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["profile-token"], emboss, "inputs", feature_row)
    assert reason is None and resolved == [profile]
    state, definition, unavailable = mod._edit.feature_edit_state(emboss)
    assert unavailable == {}
    assert definition["profiles"][0]["profile_handle"] == "profile-token"
    row = next(item for item in mod._edit.feature_edit_rows(emboss, definition)
               if item["action"] == "inputs")
    assert "references=['profile-token']" in row["call"]
    assert state["depth"] == "0.5 mm"


def test_path_reader_and_typed_resolver_roundtrip_one_edge(scene, monkeypatch):
    feature, _timeline, edge, _before_axis, _design, _body = scene
    class Path:
        count = 1
        def item(self, _index):
            return SimpleNamespace(entity=edge)

    path = Path()
    pattern = SimpleNamespace(objectType="adsk::fusion::PathPatternFeature", name="Pattern1",
                              parentComponent=feature.parentComponent, path=path,
                              patternElements=SimpleNamespace(count=2), suppressedElementsIds=[],
                              inputEntities=[_body], quantity=SimpleNamespace(expression="2"),
                              isOrientationAlongPath=False,
                              timelineObject=FakeTimelineObject("Pattern1", 2))
    monkeypatch.setattr(mod._inputs, "operand_in", lambda _label, value, *_args: (value, None))
    monkeypatch.setattr(mod._inputs, "build_path", lambda *_args: (path, "edge", None))
    resolved, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["edge-handle"], pattern, "path", mod._edit.FEATURE_EDIT_SUPPORT[pattern.objectType])
    assert reason is None and resolved is path
    monkeypatch.setattr(mod._inputs, "make_handle", lambda *_args: "edge-handle")
    original_descriptor = mod._edit.reference_descriptor
    monkeypatch.setattr(mod._edit, "reference_descriptor", lambda entity, role:
                        ({"handle": "body-handle", "kind": "entity", "owner": {"component": "Part"},
                          "geometry": {"area": 6, "volume": 1}} if role == "entities"
                         else original_descriptor(entity, role)))
    state, definition, unavailable = mod._edit.feature_edit_state(pattern)
    assert unavailable == {}
    assert definition["path"]["references"][0]["handle"] == "edge-handle"
    call = next(item["call"] for item in mod._edit.feature_edit_rows(pattern, definition)
                if item["action"] == "path")
    assert "references=['edge-handle']" in call
    assert state["path"][0][0] is edge


def test_exact_sketch_curve_address_builds_and_reads_path(scene, monkeypatch):
    feature, _timeline, _new_axis, _before_axis, _design, _body = scene
    sketch = SimpleNamespace(name="R6QuarterCircle", parentComponent=feature.parentComponent)
    curve = SimpleNamespace(parentSketch=sketch, parentComponent=feature.parentComponent,
                            assemblyContext=None, name="Line1", entityToken="curve-token")
    monkeypatch.setattr(mod._inputs, "resolve_sketch_entity",
                        lambda *_args, **_kwargs: (curve, None))
    monkeypatch.setattr(mod._inputs, "_isinstance", lambda value, _kind: value is curve)
    monkeypatch.setattr(adsk.fusion, "SketchCurve", type(curve), raising=False)
    monkeypatch.setattr(mod._inputs, "operand_in", lambda _label, value, *_args: (value, None))
    expected_key = mod._inputs._common.native_identity(curve)

    class Path:
        count = 1
        def item(self, _index):
            return SimpleNamespace(entity=curve)

    class Collection:
        def __init__(self):
            self.items = []
        @property
        def count(self):
            return len(self.items)
        def add(self, value):
            self.items.append(value)
            return True
        def item(self, index):
            return self.items[index]

    monkeypatch.setattr(adsk.core.ObjectCollection, "create", staticmethod(Collection))

    path = Path()
    feature.parentComponent.features = SimpleNamespace()
    feature.parentComponent.features.createPath = lambda values, chained: (
        path if values.count == 1 and values.item(0) is curve and chained is False else None)
    resolved, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["R6QuarterCircle/line:0"], feature, "path",
        mod._edit.FEATURE_EDIT_SUPPORT["adsk::fusion::PathPatternFeature"])
    assert reason is None and resolved is path
    monkeypatch.setattr(mod._inputs, "sketch_entity_address", lambda _entity: "R6QuarterCircle/line:0")
    assert mod._edit._path_public_references(
        feature, [curve], [(curve, {})])[0]["handle"] == "R6QuarterCircle/line:0"
    assert expected_key is not None


def test_shell_state_preserves_a_measured_absent_outside_parameter(scene, monkeypatch):
    feature, *_ = scene
    face = SimpleNamespace(entityToken="shell-face", parentComponent=feature.parentComponent)
    shell = SimpleNamespace(objectType="adsk::fusion::ShellFeature", inputEntities=[face],
                            insideThickness=SimpleNamespace(expression="1.00 mm"),
                            outsideThickness=None, isTangentChain=False,
                            timelineObject=feature.timelineObject)
    monkeypatch.setattr(mod._edit, "reference_descriptor", lambda *_args: {
        "handle": "face-token", "kind": "face", "owner": {"component": "Part"}})
    state, definition, unavailable = mod._edit.feature_edit_state(shell)
    assert unavailable == {}
    assert definition["inside_thickness"] == "1.00 mm"
    assert definition["outside_thickness"] is None
    assert definition["is_tangent_chain"] is False
    assert state["outside_thickness"] is None


def test_shell_input_setter_checks_false_and_restores_original_collection(scene, monkeypatch):
    feature, *_ = scene
    row = mod._edit.FEATURE_EDIT_SUPPORT["adsk::fusion::ShellFeature"]["inputs"]
    face = SimpleNamespace(entityToken="shell-face")
    original = SimpleNamespace(count=1, item=lambda _index: face)
    calls = []
    shell = SimpleNamespace(setInputEntities=lambda value, tangent: calls.append((value, tangent)) or True)
    before = {"is_tangent_chain": False}
    assert mod._restore_value(shell, row, (original, [face]), before) is True
    assert calls == [(original, False)]
    shell.setInputEntities = lambda *_args: False
    with pytest.raises(RuntimeError, match="restore the shell input faces"):
        mod._restore_value(shell, row, (original, [face]), before)


def test_constant_fillet_reader_publishes_edge_handles_and_set_index(scene, monkeypatch):
    feature, _timeline, new_axis, _before_axis, _design, _body = scene
    edge_set = SimpleNamespace(
        objectType="adsk::fusion::ConstantRadiusFilletEdgeSet", edges=[new_axis],
        radius=SimpleNamespace(expression="2 mm"), isTangentChain=False,
        continuity=1, tangencyWeight=SimpleNamespace(
            objectType="adsk::fusion::ModelParameter", name="d5", value=1.0, expression="1"))
    feature.objectType = "adsk::fusion::FilletFeature"
    feature.filletFeatureType = adsk.fusion.FilletFeatureTypes.FilletFeatureType
    feature.edgeSets = SimpleNamespace(count=1, item=lambda index: [edge_set][index])
    monkeypatch.setattr(mod._inputs, "make_handle", lambda *_args: "edge-handle")
    state, definition, unavailable = mod._edit.feature_edit_state(feature)
    assert not unavailable
    assert state["edge_set_0_radius"] == "2 mm"
    assert definition["edge_sets"][0]["edges"][0]["handle"] == "edge-handle"
    assert definition["edge_sets"][0]["is_tangent_chain"] is False
    assert state["edge_set_0_continuity"] == 1
    assert state["edge_set_0_tangency_weight"] == 1.0
    assert state["edge_set_0_tangency_weight_expression"] == "1"
    assert definition["edge_sets"][0]["tangency_weight"] == 1.0
    assert definition["edge_sets"][0]["tangency_weight_expression"] == "1"
    action = next(row for row in mod._edit.feature_edit_rows(feature, definition)
                  if row["action"] == "inputs")
    assert "set_index=0" in action["call"]
    assert "edge-handle" in action["call"]


def test_constant_fillet_reader_refuses_unreadable_or_invalid_weight_members(scene, monkeypatch):
    feature, _timeline, new_axis, _before_axis, _design, _body = scene

    class UnreadableWeight:
        objectType = "adsk::fusion::ModelParameter"
        expression = "1"

        @property
        def value(self):
            raise RuntimeError("value unavailable")

    class UnreadableExpression:
        objectType = "adsk::fusion::ModelParameter"
        value = 1.0

        @property
        def expression(self):
            raise RuntimeError("expression unavailable")

    weights = [
        UnreadableWeight(),
        UnreadableExpression(),
        SimpleNamespace(objectType="adsk::fusion::ModelParameter", value=True, expression="1"),
        SimpleNamespace(objectType="adsk::fusion::ModelParameter", value=float("nan"), expression="1"),
        SimpleNamespace(objectType="adsk::fusion::ModelParameter", value=1.0, expression=""),
    ]
    feature.objectType = "adsk::fusion::FilletFeature"
    feature.filletFeatureType = adsk.fusion.FilletFeatureTypes.FilletFeatureType
    feature.edgeSets = SimpleNamespace(count=1)
    monkeypatch.setattr(mod._inputs, "make_handle", lambda *_args: "edge-handle")
    for weight in weights:
        edge_set = SimpleNamespace(
            objectType="adsk::fusion::ConstantRadiusFilletEdgeSet", edges=[new_axis],
            radius=SimpleNamespace(expression="2 mm"), isTangentChain=False,
            continuity=1, tangencyWeight=weight)
        feature.edgeSets.item = lambda _index, edge_set=edge_set: edge_set
        _state, definition, unavailable = mod._edit.feature_edit_state(feature)
        assert "edge_sets" in unavailable
        assert definition["edge_sets"] is None


def test_constant_fillet_input_uses_real_edge_handle_resolver(scene):
    feature, _timeline, new_axis, _before_axis, _design, _body = scene
    feature.objectType = "adsk::fusion::FilletFeature"
    feature.filletFeatureType = adsk.fusion.FilletFeatureTypes.FilletFeatureType
    support = mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType]
    resolved, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["axis-after"], feature, "inputs", support)
    assert reason is None
    assert resolved == [new_axis]
    duplicate, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["axis-after", "axis-after"], feature, "inputs", support)
    assert duplicate is None
    assert "same edge more than once" in reason


def test_chamfer_reader_refuses_a_non_equal_distance_set(scene):
    feature, *_ = scene
    unsupported = SimpleNamespace(objectType="adsk::fusion::TwoDistancesChamferEdgeSet")
    feature.objectType = "adsk::fusion::ChamferFeature"
    feature.edgeSets = SimpleNamespace(count=1, item=lambda index: [unsupported][index])
    _state, definition, unavailable = mod._edit.feature_edit_state(feature)
    assert "edge_sets" in unavailable
    assert definition["edge_sets"] is None


def test_wire_schema_adds_only_the_bounded_hem_payload():
    props = mod.tool.input_schema["properties"]
    assert set(props) == {"feature", "action", "references", "mode", "set_index", "hem", "expect_document"}
    assert props["hem"]["properties"]["type"]["enum"] == ["flat", "open", "rolled", "double"]
    assert props["references"]["type"] == "array"
    assert props["references"]["items"]["type"] == ["string", "object"]
    assert props["set_index"]["type"] == "integer"
    assert props["set_index"]["minimum"] == 0


@pytest.fixture
def hem_scene(scene, monkeypatch):
    from tests.fakes.design import FakeUnitsManager
    feature, timeline, _new_edge, old_edge, design, _body = scene
    feature.objectType = "adsk::fusion::HemFeature"
    position = adsk.fusion.BendPositionTypes.StartEdgeBendPositionType
    feature.definition = SimpleNamespace(objectType="adsk::fusion::FlatHemFeatureDefinition",
        hemEdge=old_edge, isFlipped=False, bendPositionType=position,
        length=SimpleNamespace(expression="8 mm", value=.8))
    monkeypatch.setattr(design, "unitsManager", FakeUnitsManager(valid=("9 mm",), value=.9,
                                                               dimensioned=("9 mm",)), raising=False)
    monkeypatch.setattr(adsk.core.ValueInput, "createByString", lambda text: text)
    calls = []

    def redefine(length, flip, bend_position):
        calls.append((length, flip, bend_position))
        feature.definition = SimpleNamespace(objectType="adsk::fusion::FlatHemFeatureDefinition",
            hemEdge=old_edge, isFlipped=flip, bendPositionType=bend_position,
            length=SimpleNamespace(expression=length, value=float(length.split()[0]) / 10))
        return True

    feature.redefineAsFlatHem = redefine
    return feature, timeline, design, calls


def test_hem_rebuild_retains_edge_flip_position_and_reports_definition(hem_scene):
    feature, timeline, _design, calls = hem_scene
    out = payload(mod.handler(feature="Part/Revolve1@1", action="mode",
                              hem={"type": "flat", "length": "9 mm"}))
    assert out["definition_matches"] is True and out["marker_restored"] is True
    assert out["definition_after"]["hem"]["dimensions"]["length"]["value_cm"] == .9
    assert out["definition_before"]["hem_edge"] == out["definition_after"]["hem_edge"]
    assert calls == [("9 mm", False, adsk.fusion.BendPositionTypes.StartEdgeBendPositionType)]
    assert timeline.markerPosition == timeline.count


@pytest.mark.parametrize("hem_request", [{"type": "flat", "length": "9"},
    {"type": "flat", "length": "9 mm", "gap": "3 mm"},
    {"type": "open", "length": "9 mm"}, {"type": "flat", "length": "9 mm", "flip": "false"},
    {"type": "rolled", "radius": "9 mm", "angle_deg": float("nan")}])
def test_invalid_hem_payload_never_attempts_rebuild(hem_scene, hem_request):
    _feature, timeline, _design, calls = hem_scene
    result = mod.handler(feature="Part/Revolve1@1", action="mode", hem=hem_request)
    assert result["isError"] is True and not calls
    assert timeline.markerPosition == timeline.count


def test_false_hem_return_after_mutation_restores_original_definition(hem_scene):
    feature, timeline, _design, calls = hem_scene
    redefine = feature.redefineAsFlatHem
    feature.redefineAsFlatHem = lambda *args: redefine(*args) and len(calls) > 1
    result = mod.handler(feature="Part/Revolve1@1", action="mode",
                         hem={"type": "flat", "length": "9 mm"})
    assert result["isError"] is True
    assert feature.definition.length.expression == "8 mm"
    assert len(calls) == 2 and not result["details"]["restore_gaps"]
    assert timeline.markerPosition == timeline.count


def test_true_hem_return_without_changed_definition_is_not_success(hem_scene):
    feature, timeline, _design, calls = hem_scene
    feature.redefineAsFlatHem = lambda *args: calls.append(args) or True
    result = mod.handler(feature="Part/Revolve1@1", action="mode",
                         hem={"type": "flat", "length": "9 mm"})
    assert result["isError"] is True and len(calls) == 2
    assert feature.definition.length.value == .8 and timeline.markerPosition == timeline.count


def test_hem_expression_loss_is_not_a_verified_restore_even_at_the_same_value(hem_scene):
    feature, _timeline, _design, calls = hem_scene
    feature.definition.length.expression = "HemLength"
    def dropped_expression(length, flip, position):
        calls.append(length)
        feature.definition.length.expression = "8 mm"
        feature.definition.length.value = .8
        return len(calls) > 1
    feature.redefineAsFlatHem = dropped_expression
    result = mod.handler(feature="Part/Revolve1@1", action="mode",
                         hem={"type": "flat", "length": "9 mm"})
    assert result["isError"] is True and len(calls) == 2
    assert result["details"]["restore_gaps"] == ["the definition re-read differs from before the edit"]


@pytest.mark.parametrize("angle,text", [(123.456789, "123.456789 deg"),
    (180.0, "180 deg"), (.00001, "0.00001 deg")])
def test_hem_angle_expression_does_not_round_or_switch_to_exponent(hem_scene, angle, text):
    _feature, _timeline, design, _calls = hem_scene
    before = {"flip": False, "bend_position": "start_edge"}
    requested, expected = mod._sheet_edit.prepare_hem(
        {"type": "rolled", "radius": "9 mm", "angle_deg": angle}, before, design)
    assert requested["dimensions"]["angle_deg"]["expression"] == text
    assert expected["dimensions"]["angle_deg"] == round(math.radians(angle), 12)


@pytest.mark.parametrize("kind,dimensions,args", [
    ("flat", {"length": "9 mm"}, ["9 mm"]),
    ("open", {"length": "9 mm", "gap": "3 mm"}, ["9 mm", "3 mm"]),
    ("rolled", {"radius": "4 mm", "angle_deg": "180 deg"}, ["4 mm", "180 deg"]),
    ("double", {"length": "12 mm", "gap": "3 mm", "setback": "4 mm"},
     ["3 mm", "12 mm", "4 mm"]),
])
def test_hem_rebuild_uses_the_measured_mode_argument_order(hem_scene, kind, dimensions, args):
    feature, _timeline, _design, _calls = hem_scene
    calls = []
    setattr(feature, "redefineAs" + kind.title() + "Hem", lambda *values: calls.append(values) or True)
    mod._sheet_edit.write_hem(feature, {"type": kind, "flip": False,
        "bend_position": "start_edge", "dimensions": {key: {"expression": value}
                                                       for key, value in dimensions.items()}})
    assert calls == [(*args, False, adsk.fusion.BendPositionTypes.StartEdgeBendPositionType)]


def test_rip_face_edit_writes_native_definition_not_a_dotted_shadow(offset_scene):
    feature, timeline, old_face, new_face, _calls = offset_scene
    feature.objectType = "adsk::fusion::RipFeature"
    feature.definition = SimpleNamespace(objectType="adsk::fusion::FaceRipFeatureDefinition",
                                         ripFace=old_face)
    out = payload(mod.handler(feature="Part/Offset1@1", action="inputs", references=["new-face"]))
    assert feature.definition.ripFace is new_face
    assert not hasattr(feature, "definition.ripFace")
    assert out["definition_matches"] is True and timeline.markerPosition == timeline.count


def test_point_rip_definition_is_not_offered_or_edited(offset_scene):
    feature, timeline, old_face, _new_face, _calls = offset_scene
    feature.objectType = "adsk::fusion::RipFeature"
    feature.definition = SimpleNamespace(objectType="adsk::fusion::BetweenPointsRipFeatureDefinition",
                                         ripFace=old_face)
    result = mod.handler(feature="Part/Offset1@1", action="inputs", references=["new-face"])
    assert result["isError"] is True and feature.definition.ripFace is old_face
    assert mod._edit.feature_edit_rows(feature) == [] and timeline.markerPosition == timeline.count


def test_feature_definition_emits_usable_handle_and_qualified_call(scene):
    feature, _timeline, _new_axis, _before_axis, _design, _body = scene
    definition = mod._edit.feature_definition(feature, 1.0)
    assert not definition["unavailable"], definition["unavailable"]
    assert definition["axis"]["handle"] == "axis-before|@line_edge:0.500000,0.000000,0.000000"
    assert definition["axis"]["owner"]["component"] == "Part"
    axis = next(row for row in definition["supported_edits"] if row["action"] == "axis")
    assert axis["call"] == ("model_edit_feature(feature='Part/Revolve1@1', action='axis', "
                            "references=['axis-before|@line_edge:0.500000,0.000000,0.000000'])")
    assert not definition["unavailable"]


def test_revolve_profile_reference_uses_existing_measured_locator():
    component = MakeComp(name="Part", entity_token="part-token")
    sketch = Sketch("Profile", parent_component=component)
    profile = Profile(area=1.25, centroid=(.5, .25, 0), entity_token="profile-token",
                      parent_sketch=sketch)
    profile.objectType = "adsk::fusion::Profile"
    sketch.profiles = sketch.profiles.__class__([profile])
    profile.parentSketch = sketch
    result, geometry = mod._edit._profile_edit_definition(profile)
    assert result["profile_handle"] == "profile-token|@profile[Profile~1.2500]:0.500000,0.250000,0.000000"
    assert result["profile_index"] == 0
    assert geometry == {"area": 1.25, "centroid": [0.5, 0.25, 0], "loop_count": 0}


def test_planar_face_reference_labels_its_read_frame(scene):
    _feature, _timeline, _new_axis, _before_axis, _design, body = scene
    face = BRepFace(SimpleNamespace(surfaceType=adsk.core.SurfaceTypes.PlaneSurfaceType),
                    area=1, centroid=FakePoint(0, 0, 0), entity_token="plane-face",
                    body=body, point_on_face=FakePoint(0, 2, 0),
                    normal=FakeVector3D(0, 1, 0), param_reversed=False)
    result = mod._edit.reference_descriptor(face, "plane")
    assert result["geometry"] == {"frame": "entity_context", "surface_type":
                                  adsk.core.SurfaceTypes.PlaneSurfaceType,
                                  "point_cm": (0, 2, 0), "normal": [0, 1, 0], "reversed": False}


def test_thread_definition_reads_thread_info_and_full_length_suppresses_length(monkeypatch):
    info = SimpleNamespace(threadType="ISO", threadDesignation="M10x1.5",
                           threadClass="6H", isInternal=True)
    feature = SimpleNamespace(objectType="adsk::fusion::ThreadFeature", name="Thread1",
                              isModeled=True, isFullLength=True, isRightHanded=True,
                              threadInfo=info, timelineObject=FakeTimelineObject("Thread1", 0))
    definition = mod._edit.feature_definition(feature, 1.0)
    assert definition["is_modeled"] is True
    assert definition["thread_info"] == {"thread_type": "ISO", "designation": "M10x1.5",
                                         "thread_class": "6H", "internal": True}
    assert definition["not_read"] == ["length", "offset"]
    assert [row["action"] for row in definition["supported_edits"]] == ["mode"]
    assert definition["unavailable"] == {}


def test_patch_definition_requires_and_retains_scalar_patch_controls(monkeypatch):
    monkeypatch.setattr(mod.adsk.core.ObjectCollection, "create", lambda: _FakeObjectCollection())
    circle = SimpleNamespace(entityToken="patch-boundary", objectType="adsk::fusion::SketchCircle")
    boundary = _FakeObjectCollection()
    boundary.add(circle)
    # The stand-in carries groupContinuity and no 'continuity' member, so a read of that member
    # lands in 'unavailable'.
    feature = SimpleNamespace(
        objectType="adsk::fusion::PatchFeature", name="Patch1",
        timelineObject=FakeTimelineObject("Patch1", 0), boundaryCurve=boundary,
        operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        groupContinuity=2, isGroupEdges=True)
    monkeypatch.setattr(mod._edit, "reference_descriptor", lambda *_args: {
        "handle": "patch-boundary", "kind": "entity", "owner": {"component": "Part"},
        "geometry": {"world_cm": [1, 2, 0]}})
    state, definition, unavailable = mod._edit.feature_edit_state(feature)
    assert unavailable == {}
    assert state["boundary"][0] is circle
    assert definition["continuity"] == 2 and definition["is_group_edges"] is True
    assert state["continuity"] == 2 and state["is_group_edges"] is True
    assert definition["operation"] == "new"

    row = mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType]["boundary"]
    mod._apply_value(feature, row, circle, "", state)
    applied = feature.boundaryCurve
    assert isinstance(applied, _FakeObjectCollection)
    assert applied.count == 1 and applied.item(0) is circle
    mod._restore_value(feature, row, boundary, state)
    assert feature.boundaryCurve is boundary


def test_patch_definition_refuses_multiple_boundary_curve_members(monkeypatch):
    members = _FakeObjectCollection()
    members.add(SimpleNamespace(objectType="adsk::fusion::SketchCircle"))
    members.add(SimpleNamespace(objectType="adsk::fusion::SketchCircle"))
    feature = SimpleNamespace(
        objectType="adsk::fusion::PatchFeature", name="Patch1",
        timelineObject=FakeTimelineObject("Patch1", 0), boundaryCurve=members,
        operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        groupContinuity=2, isGroupEdges=True)

    state, definition, unavailable = mod._edit.feature_edit_state(feature)

    assert state["boundary"] is None
    assert definition["boundary"] is None
    assert unavailable["boundary"] == "boundaryCurve must contain exactly one readable SketchCircle"


def _edge_patch(grouped):
    """A patch stand-in over an unreadable boundary. DECLARED, not measured: an ungrouped patch
    keeps answering one groupContinuity, and a grouping read that answers no bool."""
    return SimpleNamespace(
        objectType="adsk::fusion::PatchFeature", name="Patch1",
        timelineObject=FakeTimelineObject("Patch1", 0), boundaryCurve=_FakeObjectCollection(),
        operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        groupContinuity=2, isGroupEdges=grouped)


def test_ungrouped_patch_publishes_no_single_continuity():
    state, definition, unavailable = mod._edit.feature_edit_state(_edge_patch(False))
    assert definition["is_group_edges"] is False
    assert definition["continuity"] is None and state["continuity"] is None
    assert "continuity" not in unavailable and "is_group_edges" not in unavailable


def test_patch_continuity_is_unavailable_when_the_grouping_does_not_read():
    state, definition, unavailable = mod._edit.feature_edit_state(_edge_patch(None))
    assert definition["continuity"] is None and definition["is_group_edges"] is None
    assert unavailable["is_group_edges"] == "value is not a readable boolean"
    assert unavailable["continuity"] == "isGroupEdges did not read, so groupContinuity was not read"


def test_untrim_manual_loop_mode_is_preserved_even_though_it_is_not_an_edit_choice(monkeypatch):
    face = SimpleNamespace(entityToken="untrim-face")
    feature = SimpleNamespace(
        objectType="adsk::fusion::UntrimFeature", name="Untrim1",
        timelineObject=FakeTimelineObject("Untrim1", 0), facesToUntrim=[face],
        untrimLoopType=adsk.fusion.UntrimLoopTypes.ManualLoopsUntrimType,
        extensionDistance=SimpleNamespace(expression="0 mm"))
    monkeypatch.setattr(mod._edit, "reference_descriptor", lambda *_args: {
        "handle": "untrim-face", "kind": "face", "owner": {"component": "Part"},
        "geometry": {"area": 1}})
    state, definition, unavailable = mod._edit.feature_edit_state(feature)
    assert unavailable == {}
    assert state["loop_type"] == definition["loop_type"] == "manual"
    assert mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType]["boundary"]["choices"] == (
        "all", "external", "internal")


def test_untrim_manual_baseline_refuses_before_edit(scene, monkeypatch):
    feature, timeline, new_axis, before_axis, design, body = scene
    feature.objectType = "adsk::fusion::UntrimFeature"
    feature.name = feature.timelineObject.name = "Untrim1"
    feature.facesToUntrim = [SimpleNamespace(entityToken="manual-face", body=body)]
    feature.untrimLoopType = adsk.fusion.UntrimLoopTypes.ManualLoopsUntrimType
    feature.extensionDistance = SimpleNamespace(expression="0 mm")
    monkeypatch.setattr(mod._edit, "reference_descriptor", lambda entity, _role: {
        "handle": entity.entityToken, "kind": "face", "owner": {"component": "Part"},
        "geometry": {"area": 1}})
    monkeypatch.setattr(mod._inputs.GeometryHandleList, "resolve",
                        lambda _self, _raw: ([feature.facesToUntrim[0]], None))
    called = []
    feature.redefineLoopsFromFaces = lambda *_args: called.append(True) or True
    result = mod.handler(feature="Part/Untrim1@1", action="boundary", references=["other-face"],
                         mode="all")
    assert result["isError"] is True
    assert "manual Untrim loop selection" in error_message(result)
    assert called == []
    assert timeline.markerPosition == timeline.count


@pytest.mark.parametrize("returned", [False, None])
@pytest.mark.parametrize("setter,row,mode", [
    ("setInputEntities", {"member": "entities", "setter": "setInputEntities",
                           "chain_field": "is_chain_selection"}, ""),
    ("setInputFaces", {"member": "inputFaces", "setter": "setInputFaces",
                        "chain_field": "is_chain_selection"}, ""),
    ("redefineLoopsFromFaces", {"member": "facesToUntrim",
                                 "setter": "redefineLoopsFromFaces",
                                 "mode_field": "loop_type", "mode_enum": "UntrimLoopTypes",
                                 "values": {"all": "AllLoopsUntrimType"}}, "all"),
])
def test_reference_setter_must_confirm_apply_and_restore(monkeypatch, returned, setter, row, mode):
    feature = SimpleNamespace(**{setter: lambda *_args: returned})
    state = {"is_chain_selection": True, "loop_type": "all"}
    with pytest.raises(RuntimeError, match="did not confirm"):
        mod._apply_value(feature, row, [object()], mode, state)
    with pytest.raises(RuntimeError, match="did not confirm"):
        mod._restore_value(feature, row, [object()], state)


@pytest.mark.parametrize("object_type,field,reference", [
    ("adsk::fusion::ExtendFeature", "edges", "edges"),
    ("adsk::fusion::ReverseNormalFeature", "surfaces", "surface_bodies"),
])
def test_definition_edit_rows_emit_all_many_operand_handles(object_type, field, reference):
    feature = SimpleNamespace(objectType=object_type,
                              timelineObject=FakeTimelineObject("Feature1", 3))
    definition = {field: [{"handle": "one"}, {"handle": "two"}]}
    rows = mod._edit.feature_edit_rows(feature, definition)
    call = rows[0]["call"]
    assert f"references=['one', 'two']" in call


def test_offset_inputs_use_object_collection_and_preserve_measured_chain_and_distance(offset_scene):
    feature, timeline, _before_face, after_face, calls = offset_scene
    result = payload(mod.handler(feature="Part/Offset1@1", action="inputs",
                                 references=["face-after"]))
    assert calls[0][0] is _FakeObjectCollection
    assert calls[0][1:] == ([after_face], True)
    assert feature.distance.expression == "5 mm"
    assert result["definition_matches"] is True
    assert result["definition_after"]["is_chain_selection"] is True
    assert timeline.markerPosition == timeline.count


def test_offset_silent_noop_is_an_error_and_restores_original_inputs(offset_scene):
    feature, timeline, before_face, after_face, _calls = offset_scene

    def no_op(collection, is_chain):
        if list(collection) == [after_face]:
            return True
        feature.entities = collection
        feature.isChainSelection = is_chain
        return True

    feature.setInputEntities = no_op
    result = mod.handler(feature="Part/Offset1@1", action="inputs", references=["face-after"])
    assert result["isError"] is True
    assert "requested definition" in error_message(result)
    assert list(feature.entities) == [before_face]
    assert result["details"]["restore_gaps"] == []
    assert timeline.markerPosition == timeline.count


def test_offset_setter_that_raises_after_landing_is_compensated(offset_scene):
    feature, timeline, before_face, after_face, _calls = offset_scene

    def raise_after_landing(collection, is_chain):
        feature.entities = collection
        feature.isChainSelection = is_chain
        if list(collection) == [after_face]:
            raise RuntimeError("landed then raised")
        return True

    feature.setInputEntities = raise_after_landing
    result = mod.handler(feature="Part/Offset1@1", action="inputs", references=["face-after"])
    assert result["isError"] is True
    assert "landed then raised" in error_message(result)
    assert list(feature.entities) == [before_face]
    assert result["details"]["restore_gaps"] == []
    assert timeline.markerPosition == timeline.count


def test_reverse_normal_effect_rejects_selection_change_without_face_normal_flip(monkeypatch):
    body = SimpleNamespace(entityToken="surface-a")
    body_b = SimpleNamespace(entityToken="surface-b")
    monkeypatch.setattr(mod._common, "native_identity", lambda value: value.entityToken)
    before = {"surface-a": [{"area": 1.0, "center": (0, 0, 0),
                             "normal": (0, 0, -1), "reversed": True}],
              "surface-b": [{"area": 2.0, "center": (1, 0, 0),
                             "normal": (0, 1, 0), "reversed": False}]}
    after = {"surface-a": [{"area": 1.0, "center": (0, 0, 0),
                            "normal": (0, 0, 1), "reversed": False}],
             "surface-b": [{"area": 2.0, "center": (1, 0, 0),
                            "normal": (0, -1, 0), "reversed": True}]}
    assert mod._edit.surface_normals_reversed(before, after, [body], [body_b]) is True
    assert mod._edit.surface_normals_reversed(before, before, [body], [body_b]) is False


def test_reverse_normal_overlap_is_preserved_while_deselected_body_unflips(monkeypatch):
    a = SimpleNamespace(entityToken="surface-a")
    overlap = SimpleNamespace(entityToken="surface-overlap")
    monkeypatch.setattr(mod._common, "native_identity", lambda value: value.entityToken)
    before = {
        "surface-a": [{"area": 1.0, "center": (0, 0, 0), "normal": (0, 0, -1), "reversed": True}],
        "surface-overlap": [{"area": 2.0, "center": (1, 0, 0),
                             "normal": (0, 1, 0), "reversed": True}]}
    after = {
        "surface-a": [{"area": 1.0, "center": (0, 0, 0), "normal": (0, 0, 1), "reversed": False}],
        "surface-overlap": [{"area": 2.0, "center": (1, 0, 0),
                             "normal": (0, 1, 0), "reversed": True}]}
    assert mod._edit.surface_normals_reversed(before, after, [a, overlap], [overlap]) is True
    wrong_overlap = {**after, "surface-overlap": [dict(after["surface-overlap"][0],
                                                        normal=(0, -1, 0), reversed=False)]}
    assert mod._edit.surface_normals_reversed(before, wrong_overlap, [a, overlap], [overlap]) is False


def test_surface_compensation_samples_normals_at_the_feature_evaluation_marker(monkeypatch):
    timeline = SimpleNamespace(markerPosition=3, count=3)
    owner = SimpleNamespace(name="Part")
    entity = SimpleNamespace(timelineObject=SimpleNamespace(index=1), entityToken="feature-token",
                             parentComponent=owner, value=None)
    design = SimpleNamespace(timeline=timeline)
    snapshots = []
    health = {"errors": [], "warnings": []}

    def restore_definition(_design, _entity, restore, read_restored, index, geometry, marker):
        timeline.markerPosition = index
        restore()
        read_restored(entity)
        shapes = geometry()
        timeline.markerPosition = marker
        return {"definition": {}, "shapes": shapes, "error": None,
                "ran": True, "marker_after": marker}

    monkeypatch.setattr(mod._edit, "restore_definition", restore_definition)
    monkeypatch.setattr(mod._edit, "feature_edit_state", lambda _entity: ({}, {}, {}))
    monkeypatch.setattr(mod._edit, "feature_definition_view", lambda *_args: {})
    monkeypatch.setattr(mod._edit, "feature_geometry_snapshot", lambda _design: {})
    monkeypatch.setattr(mod._edit, "surface_normal_snapshot", lambda _targets: (
        snapshots.append(timeline.markerPosition) or {"marker": timeline.markerPosition}))
    monkeypatch.setattr(mod._edit, "matched", lambda actual, expected: actual == expected)
    monkeypatch.setattr(mod._edit, "same_feature_edit_state", lambda *_args: True)
    monkeypatch.setattr(mod._edit, "restore_gaps", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mod._edit, "shape_match", lambda *_args: (True, []))
    monkeypatch.setattr(mod._edit, "health", lambda *_args: health)
    monkeypatch.setattr(mod._common, "same_component", lambda *_args: True)
    monkeypatch.setattr(mod._edit, "same_feature", lambda *_args: True)
    result = mod._compensate(
        design, timeline, entity, {"member": "value"}, "prior", "Feature", "inputs", {},
        {}, {}, health, owner, "feature-token", 1, 3, 3, {}, {}, False,
        "late verification failure", surface_targets=[object()],
        surface_normals_before={"marker": 2})
    assert result["isError"] is True
    assert snapshots == [2]
    assert result["details"]["surface_normals_restored"] is True


_DATUM_CALLS = {
    "plane": dict(feature="Part/Plane1@1", action="plane", references=["parallel-token"]),
    "axis": dict(feature="Part/Axis1@1", action="axis",
                 references=[{"first_plane": "parallel-token", "second_plane": "xz"}]),
    "point": dict(feature="Part/Point1@1", action="point", references=["vertex-b"]),
    "origin": dict(feature="Part/Origin1@1", action="geometry", references=["face-side"]),
}
_DATUM_KINDS = ("plane", "axis", "point")


@pytest.mark.parametrize("left, gap", [
    ({"origin_cm": [9, 9, 9]}, "the edited entity's own geometry does not match the pre-edit read"),
    (None, "the edited entity's own geometry was not re-read")])
def test_joint_origin_own_frame_left_changed_after_compensation_is_not_reported_restored(
        monkeypatch, left, gap):
    s = datum_scene(mod, monkeypatch, "origin", lands="other")
    home, real, reads = s.entity.geometry, mod._edit.own_geometry, []
    monkeypatch.setattr(mod._edit, "own_geometry", lambda entity, role: (
        reads.append(role), real(entity, role) if len(reads) == 1 else (left, "frame unread"))[1])
    result = mod.handler(**_DATUM_CALLS["origin"])
    message = error_message(result)
    details = result["details"]
    assert s.entity.geometry is home and details["marker_restored"] is True
    assert details["restore_gaps"] == [gap] and details["edited"] is None
    assert "Restoration is incomplete" in message and "were restored" not in message
    assert details["target_geometry_restored"] == left


def _home_reads_back(scene, kind):
    """Whether the definition holds the operand it started with."""
    held = {"plane": lambda: scene.definition.planarEntity,
            "axis": lambda: scene.definition.planarEntityOne,
            "point": lambda: scene.definition.pointEntity}[kind]()
    return held is scene.definition.home


@pytest.mark.parametrize("kind", _DATUM_KINDS)
def test_datum_edit_is_verified_by_reread_and_never_rolls_the_timeline(monkeypatch, kind):
    s = datum_scene(mod, monkeypatch, kind)
    result = payload(mod.handler(**_DATUM_CALLS[kind]))
    assert result["edited"] is True and result["definition_matches"] is True
    assert result["geometry_changed"] is True
    assert result["target_geometry_before"] != result["target_geometry_after"]
    assert s.timeline._moves == [] and all(row._rolls == [] for row in s.rows)
    assert result["marker_before"] == result["marker_after"] == 3
    assert result["new_timeline_errors"] == [] and "unchanged" not in result["note"]
    assert len(s.definition.calls) == 1


def test_plane_rebase_passes_the_read_offset_expression_back(monkeypatch):
    s = datum_scene(mod, monkeypatch, "plane")
    result = payload(mod.handler(**_DATUM_CALLS["plane"]))
    assert s.definition.calls == [(("text", "10.00 mm"), s.parallel)]
    assert result["returned"] is True
    assert result["definition_after"]["offset"] == "10.00 mm"
    assert result["definition_before"]["base_plane"]["name"] == "XY"
    assert result["definition_after"]["base_plane"]["name"] == "Parallel"
    assert result["target_geometry_after"] == {"frame": "world", "origin_cm": [0, 0, 1.5],
                                               "normal": [0, 0, 1]}
    assert "can change orientation" in result["note"]


@pytest.mark.parametrize("offset", [SimpleNamespace(), SimpleNamespace(expression=None),
                                    SimpleNamespace(expression=" ")])
def test_plane_with_an_unread_offset_expression_is_refused_before_the_write(monkeypatch, offset):
    s = datum_scene(mod, monkeypatch, "plane")
    s.definition.offset = offset
    message = error_message(mod.handler(**_DATUM_CALLS["plane"]))
    assert "'offset'" in message and "Nothing was edited" in message
    assert s.definition.calls == []


def test_axis_redefine_takes_the_named_roles_in_order(monkeypatch):
    s = datum_scene(mod, monkeypatch, "axis")
    result = payload(mod.handler(**_DATUM_CALLS["axis"]))
    assert s.definition.calls == [(s.parallel, s.planes["xz"])]
    planes = result["definition_after"]["planes"]
    assert (planes["first_plane"]["name"], planes["second_plane"]["name"]) == ("Parallel", "XZ")
    assert result["target_geometry_after"]["origin_cm"] == [0, 0, 0.5]


def test_point_edit_assigns_the_point_entity_and_reads_the_moved_point(monkeypatch):
    s = datum_scene(mod, monkeypatch, "point")
    result = payload(mod.handler(**_DATUM_CALLS["point"]))
    assert s.definition.calls == [s.tokens["vertex-b"]]
    assert result["returned"] is None
    assert result["definition_after"]["point_entity"]["kind"] == "vertex"
    assert result["target_geometry_before"] == {"world_cm": [0, 0, 0]}
    assert result["target_geometry_after"] == {"world_cm": [1, 1, 1]}


@pytest.mark.parametrize("kind, behaviour, said", [
    ("plane", dict(returns=False, lands="nothing"), "returned False"),
    ("plane", dict(lands="nothing"), "did not read back"),
    ("plane", dict(lands="other"), "did not read back"),
    ("axis", dict(returns=False, lands="nothing"), "returned False"),
    ("axis", dict(lands="other"), "did not read back"),
    ("point", dict(lands="nothing"), "did not read back"),
    ("point", dict(lands="other"), "did not read back"),
])
def test_datum_write_that_fails_or_lands_elsewhere_is_an_error_and_is_restored(
        monkeypatch, kind, behaviour, said):
    s = datum_scene(mod, monkeypatch, kind, **behaviour)
    result = mod.handler(**_DATUM_CALLS[kind])
    assert said in error_message(result)
    details = result["details"]
    assert details["edited"] is False and details["restore_gaps"] == []
    assert details["target_geometry_restored"] == details["target_geometry_before"]
    assert _home_reads_back(s, kind)
    assert s.timeline._moves == [] and s.row._rolls == []


@pytest.mark.parametrize("kind", _DATUM_KINDS + ("origin",))
def test_new_reference_whose_identity_does_not_read_is_unverified_not_accepted(monkeypatch, kind):
    s = datum_scene(mod, monkeypatch, kind)
    target = {"plane": s.parallel, "axis": s.parallel, "point": s.tokens.get("vertex-b"),
              "origin": s.tokens.get("face-side")}[kind]
    wrote = lambda: bool(s.entity.assigned if kind == "origin" else s.definition.calls)
    real = mod._common.native_identity
    monkeypatch.setattr(mod._common, "native_identity",
                        lambda entity: None if entity is target and wrote() else real(entity))
    result = mod.handler(**_DATUM_CALLS[kind])
    assert "unverified" in error_message(result)
    assert result["details"]["definition_matches"] is None


@pytest.mark.parametrize("kind, create", [
    ("plane", "model_construction(kind='plane', mode='offset')"),
    ("axis", "model_construction(kind='axis', mode='two_planes')"),
    ("point", "model_construction(kind='point', mode='at_point')")])
def test_other_datum_definition_type_is_refused_naming_the_type_read(monkeypatch, kind, create):
    s = datum_scene(mod, monkeypatch, kind)
    s.definition.objectType = "adsk::fusion::ConstructionPlaneAtAngleDefinition"
    message = error_message(mod.handler(**_DATUM_CALLS[kind]))
    assert "definition type reads ConstructionPlaneAtAngleDefinition" in message
    assert create in message and s.definition.calls == []
    assert mod._edit.feature_definition(s.entity, 1.0)["supported_edits"] == []


def test_wrong_action_for_a_datum_names_the_allowed_action_and_an_example(monkeypatch):
    s = datum_scene(mod, monkeypatch, "plane")
    message = error_message(mod.handler(feature="Part/Plane1@1", action="axis",
                                        references=["parallel-token"]))
    assert "does not support action='axis'. Supported: plane." in message
    assert ("Example: model_edit_feature(feature='Part/Plane1@1', action='plane', "
            "references=['xz']).") in message
    assert s.definition.calls == []


@pytest.mark.parametrize("kind, references, said", [
    ("axis", [{"first_plane": "parallel-token"}], "exactly the keys first_plane and second_plane"),
    ("axis", [{"first_plane": "parallel-token", "second_plane": "xz", "third_plane": "yz"}],
     "exactly the keys first_plane and second_plane"),
    ("axis", [{"first_plane": "xz", "second_plane": "xz"}], "name the same plane"),
    ("axis", [{"first_plane": "parallel-token", "second_plane": "xz"}] * 2, "exactly one item"),
    ("axis", ["parallel-token"], "exactly the keys first_plane and second_plane"),
    ("plane", [{"first_plane": "xz"}], "'references' is required (a plane alias"),
    ("plane", ["xz", "yz"], "exactly one item"),
    ("point", [{"point": "vertex-b"}], "must be a reference string, got dict"),
    ("point", ["parallel-token"], "not a point"),
])
def test_datum_reference_shape_is_refused_before_the_write_with_an_example(
        monkeypatch, kind, references, said):
    s = datum_scene(mod, monkeypatch, kind)
    call = dict(_DATUM_CALLS[kind], references=references)
    message = error_message(mod.handler(**call))
    assert said in message and "Example: model_edit_feature(" in message
    assert "Nothing was edited" in message and s.definition.calls == []


def test_datum_edit_that_breaks_a_dependent_is_an_error_and_is_restored(monkeypatch):
    s = datum_scene(mod, monkeypatch, "plane")
    monkeypatch.setattr(mod._edit, "health", lambda *_args: {
        "errors": ["Extrude1"] if s.world["shape"] == "Parallel" else [], "warnings": []})
    result = mod.handler(**_DATUM_CALLS["plane"])
    assert "health errors or warnings" in error_message(result)
    assert result["details"]["new_timeline_errors"] == ["Extrude1"]
    assert result["details"]["restore_gaps"] == [] and _home_reads_back(s, "plane")


def test_joint_origin_reanchor_rolls_before_restores_marker_and_reads_three_axes(monkeypatch):
    s = datum_scene(mod, monkeypatch, "origin")
    result = payload(mod.handler(**_DATUM_CALLS["origin"]))
    assert s.entity.geometry.entityOne is s.tokens["face-side"]
    assert s.entity.assigned == [s.entity.geometry]
    assert s.row._rolls[0] is True and 1 in s.timeline._moves
    assert result["marker_restored"] is True and s.timeline.markerPosition == 3
    assert result["definition_after"]["geometry"]["kind"] == "face"
    assert result["target_geometry_before"] == {
        "origin_cm": [1, 1, 1], "primary_axis": [0, 0, 1], "secondary_axis": [1, 0, 0],
        "third_axis": [0, 1, 0]}
    assert result["target_geometry_after"] == {
        "origin_cm": [0, 1, 0.5], "primary_axis": [-1, 0, 0], "secondary_axis": [0, 0, 1],
        "third_axis": [0, -1, 0]}
    assert result["geometry_changed"] is True and "assembly_get" in result["note"]


@pytest.mark.parametrize("lands", ["nothing", "other"])
def test_joint_origin_assignment_that_does_not_take_is_an_error_and_is_restored(monkeypatch, lands):
    s = datum_scene(mod, monkeypatch, "origin", lands=lands)
    home = s.entity.geometry
    result = mod.handler(**_DATUM_CALLS["origin"])
    assert "did not read back" in error_message(result)
    assert result["details"]["restore_gaps"] == [] and s.entity.geometry is home
    assert result["details"]["target_geometry_restored"] == result["details"]["target_geometry_before"]
    assert s.timeline.markerPosition == 3


def test_joint_origin_marker_left_off_the_end_is_an_error_naming_the_residue(monkeypatch):
    s = datum_scene(mod, monkeypatch, "origin")

    class Stuck(type(s.timeline)):
        """A timeline whose marker stops answering the move back to the end."""
        @property
        def markerPosition(self):
            return self._marker

        @markerPosition.setter
        def markerPosition(self, value):
            if not (s.entity.assigned and value == 3):
                self._marker = value

    s.timeline.__class__ = Stuck
    result = mod.handler(**_DATUM_CALLS["origin"])
    assert "Restoration is incomplete" in error_message(result)
    details = result["details"]
    assert details["marker_restored"] is False and details["marker_after"] != 3
    assert "the timeline marker was not restored to its original end" in details["restore_gaps"]


def test_joint_origin_offers_no_flip(monkeypatch):
    s = datum_scene(mod, monkeypatch, "origin")
    message = error_message(mod.handler(feature="Part/Origin1@1", action="mode", mode="flipped"))
    assert "does not support action='mode'. Supported: geometry." in message
    assert s.entity.isFlipped is False and s.entity.assigned == []


def test_joint_origin_refuses_an_anchor_the_joint_geometry_adapter_cannot_take(monkeypatch):
    s = datum_scene(mod, monkeypatch, "origin")
    s.tokens["a-body"] = s.component.bRepBodies.item(0)
    message = error_message(mod.handler(feature="Part/Origin1@1", action="geometry",
                                        references=["a-body"]))
    assert "points at a BRepBody" in message and "Example: model_edit_feature(" in message
    assert s.entity.assigned == [] and s.timeline.markerPosition == 3


@pytest.mark.parametrize("kind, action, reference", [
    ("plane", "plane", "references=['xy-token|@construction_plane:0.000000,0.000000,0.000000']"),
    ("axis", "axis",
     "references=[{'first_plane': 'xy-token|@construction_plane:0.000000,0.000000,0.000000', "
     "'second_plane': 'xz-token|@construction_plane:0.000000,0.000000,0.000000'}]"),
    ("point", "point", "references=['vertex-a|@vertex:0.000000,0.000000,0.000000']"),
    ("origin", "geometry", "references=['face-top|@face:1.000000,1.000000,1.000000']"),
])
def test_supported_edits_list_each_new_kind_from_the_support_table(
        monkeypatch, kind, action, reference):
    s = datum_scene(mod, monkeypatch, kind)
    definition = mod._edit.feature_definition(s.entity, 1.0)
    assert definition["unavailable"] == {}
    address = _DATUM_CALLS[kind]["feature"]
    assert definition["supported_edits"] == [{
        "action": action, "reference": mod._edit.FEATURE_EDIT_SUPPORT[
            s.entity.objectType][action]["reference"],
        "cardinality": "one", "choices": [],
        "call": f"model_edit_feature(feature='{address}', action='{action}', {reference})"}]
    assert s.timeline._moves == [] and s.row._rolls == []


@pytest.mark.parametrize("member, field", [("angle", "angle"), ("offsetY", "offset_y")])
def test_joint_origin_retained_expression_unread_while_rolled_is_refused_by_name(
        monkeypatch, member, field):
    s = datum_scene(mod, monkeypatch, "origin")
    setattr(s.entity, member, SimpleNamespace())
    message = error_message(mod.handler(**_DATUM_CALLS["origin"]))
    assert f"retained {field} (" in message and "did not read rolled before it" in message
    assert "nothing was written" in message
    assert s.entity.assigned == [] and s.timeline.markerPosition == 3


class _HostDerive(derive_fakes._EditDerive):
    """The existing edit derive plus the identity, owner and favourites members the dispatcher reads."""
    entityToken, isValid = "derive-token", True

    def __init__(self, design, **behaviour):
        super().__init__(design, **behaviour)
        self.parentComponent = design.rootComponent
        self.healthState = adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
        self._favorites = derive_fakes._FavoriteDerive(design)

    @property
    def isIncludeFavoriteParameters(self):
        return self._favorites.isIncludeFavoriteParameters

    @isIncludeFavoriteParameters.setter
    def isIncludeFavoriteParameters(self, value):
        self._favorites.isIncludeFavoriteParameters = value


class TestDeriveEdits:
    """DeriveFeature actions run through the doc_insert_derive helpers at the end marker."""

    @pytest.fixture
    def host(self, monkeypatch):
        design = derive_fakes._edit_design(
            [derive_fakes._typed("PS_Fav_Ref", "DerivedParameter")], local=("PS_B",))
        monkeypatch.setattr(mod._common, "design", lambda: design)
        monkeypatch.setattr(mod._edit, "all_shapes", derive_fakes._shapes)

        def build(**behaviour):
            derive = _HostDerive(design, **behaviour)
            design._tokens["derive-token"] = derive
            return SimpleNamespace(design=design, derive=derive, timeline=design.timeline,
                                   row=design.timeline.item(0))
        return build

    @staticmethod
    def _unrolled(s):
        return s.timeline._moves == [] and s.row._rolls == [] and s.timeline.markerPosition == 1

    @pytest.mark.parametrize("call, helper, arguments", [
        (dict(action="inputs", references=["PS_A", " PS_B "]), "set_source_entities",
         (["PS_A", "PS_B"],)),
        (dict(action="mode", mode="favourites_off"), "set_favorite_parameters", (False,)),
        (dict(action="mode", mode="favourites_on"), "set_favorite_parameters", (True,)),
        (dict(action="break_link"), "break_link", ()),
    ])
    def test_each_action_reaches_its_helper_with_its_arguments(self, host, monkeypatch, call,
                                                              helper, arguments):
        s = host()
        calls = []
        for name in ("set_source_entities", "set_favorite_parameters", "break_link"):
            monkeypatch.setattr(mod._derive, name, lambda *args, name=name: (
                calls.append((name, args)), mod.ok({"feature": "Derive1", "edited": True}))[1])
        result = payload(mod.handler(feature="Derive1", **call))
        assert calls == [(helper, (s.design, s.derive) + arguments)]
        assert result["edited"] is True and result["action"] == call["action"]
        assert self._unrolled(s)

    def test_inputs_resolve_in_the_source_design_and_report_the_host_census(self, host):
        s = host()
        _a, source_b, _c = s.derive.sourceDesign.rootComponent.bRepBodies._items
        result = payload(mod.handler(feature="Derive1", action="inputs",
                                     references=["PS_A", "PS_B"]))
        entities, excluded = s.derive.calls[0]
        assert entities[1] is source_b and excluded == []
        assert result["edited"] is True and result["same_feature"] is True
        assert result["definition_before"]["source_entities"] == ["PS_A"]
        assert result["definition_after"]["source_entities"] == ["PS_A", "PS_B"]
        assert (result["body_count_before"], result["body_count_after"]) == (2, 3)
        assert result["bodies_arrived"] == [{"component": "Root", "body": "PS_B"}]
        assert result["new_timeline_errors"] == []
        assert (result["marker_before"], result["marker_after"]) == (1, 1)
        assert not {"restore_gaps", "marker_restored", "owner_restored"} & set(result)
        assert self._unrolled(s)

    def test_favourites_off_then_on_report_the_parameter_lists_of_the_helper(self, host):
        s = host()
        off = payload(mod.handler(feature="Derive1", action="mode", mode="favourites_off"))
        assert off["parameters_disappeared"] == ["PS_Fav_Ref"] and off["edited"] is True
        assert off["definition_before"]["include_favorite_parameters"] is True
        assert off["definition_after"]["include_favorite_parameters"] is False
        assert off["definition_after"]["derived_parameters"] == []
        on = payload(mod.handler(feature="Derive1", action="mode", mode="favourites_on"))
        assert on["parameters_appeared"] == [{"name": "PS_Fav_Ref", "derived": True}]
        assert "restor" not in (off["note"] + on["note"]).lower() and self._unrolled(s)

    def test_break_link_reports_the_replacement_and_no_same_feature(self, host):
        s = host()
        result = payload(mod.handler(feature="Derive1", action="break_link"))
        assert result["replaced"] is True and result["same_feature"] is False
        assert result["kind_after"] == "BaseFeature"
        assert result["definition_after"] is None
        assert result["definition_after_unread"] == "the derive was replaced"
        assert "cannot restore the link" in result["note"]
        assert not {"restore_gaps", "marker_restored"} & set(result) and self._unrolled(s)

    def test_mode_outside_the_two_values_is_refused_with_the_allowed_values(self, host, monkeypatch):
        s = host()
        monkeypatch.setattr(mod._derive, "set_favorite_parameters",
                            lambda *_args: pytest.fail("the helper was reached"))
        message = error_message(mod.handler(feature="Derive1", action="mode", mode="on"))
        assert "must be one of favourites_on, favourites_off" in message
        assert s.derive.isIncludeFavoriteParameters is True

    @pytest.mark.parametrize("extra, said", [
        (dict(references=["PS_A"]), "'references' is unused for action='break_link'"),
        (dict(mode="favourites_on"), "'mode' is unused for action='break_link'")])
    def test_break_link_given_references_or_mode_is_refused(self, host, extra, said):
        s = host()
        assert said in error_message(mod.handler(feature="Derive1", action="break_link", **extra))
        assert s.derive.calls == []

    @pytest.mark.parametrize("references, said", [
        ([{"body": "PS_A"}], "non-empty source root body names"),
        (["PS_A", " "], "non-empty source root body names"),
        (["PS_A", "ps_a"], "the same source body more than once"),
        ([], "needs a nonempty JSON array")])
    def test_source_names_are_checked_before_the_helper_and_never_in_the_host(
            self, host, monkeypatch, references, said):
        s = host()
        monkeypatch.setattr(mod._inputs.BodyRefList, "resolve",
                            lambda *_args: pytest.fail("a name was resolved in the active design"))
        message = error_message(mod.handler(feature="Derive1", action="inputs",
                                            references=references))
        assert said in message and "Example: model_edit_feature(feature='Root/Derive1@0'" in message
        assert s.derive.calls == []

    def test_helper_failure_passes_through_with_its_details_and_no_restore_wording(self, host):
        s = host(mode="false")
        result = mod.handler(feature="Derive1", action="inputs", references=["PS_A", "PS_B"])
        message = error_message(result)
        assert "did not verify: setSourceEntities answered False." in message
        assert "restor" not in message.lower()
        details = result["details"]
        assert details["answered"] is False and details["action"] == "inputs"
        assert details["definition_after"]["source_entities"] == ["PS_A"]
        assert not {"restore_gaps", "marker_restored"} & set(details) and self._unrolled(s)

    def test_helper_refusal_passes_through_listing_what_the_source_offers(self, host):
        s = host()
        result = mod.handler(feature="Derive1", action="inputs", references=["PS_X"])
        message = error_message(result)
        assert "'PS_X' matches 0 root bodies" in message
        assert "The source offers: 'PS_A', 'PS_B', 'PS_C'" in message
        assert "details" not in result and s.derive.calls == []

    def test_definition_lists_the_three_edits_and_nulls_unread_fields_with_a_reason(self, host):
        s = host()
        definition = mod._edit.feature_definition(s.derive, 1.0)
        assert definition["source_entities"] == ["PS_A"]
        assert definition["include_favorite_parameters"] is True
        assert definition["derived_parameters"] == ["PS_Fav_Ref"]
        assert definition["derived_parameters_scope"] == "design"
        assert definition["health"] == "healthy" and definition["out_of_date"] is False
        assert definition["source_document"] is None and definition["source_lineage_id"] is None
        assert set(definition["unavailable"]) == {"source_document", "source_lineage_id"}
        calls = {row["action"]: row["call"] for row in definition["supported_edits"]}
        assert calls == {
            "inputs": "model_edit_feature(feature='Root/Derive1@0', action='inputs', "
                      "references=['PS_A'])",
            "mode": "model_edit_feature(feature='Root/Derive1@0', action='mode', "
                    "mode='favourites_off')",
            "break_link": "model_edit_feature(feature='Root/Derive1@0', action='break_link')"}
        s.derive.sourceDesign.parentDocument = SimpleNamespace(
            name="", dataFile=SimpleNamespace(id=None))
        blank = mod._edit.feature_definition(s.derive, 1.0)
        assert blank["source_document"] is None and blank["source_lineage_id"] is None
        assert set(blank["unavailable"]) == {"source_document", "source_lineage_id"}
        s.derive.sourceDesign.parentDocument = SimpleNamespace(
            name="Source v3", dataFile=SimpleNamespace(id="urn:lineage"))
        read = mod._edit.feature_definition(s.derive, 1.0)
        assert (read["source_document"], read["source_lineage_id"]) == ("Source v3", "urn:lineage")
        assert read["unavailable"] == {} and self._unrolled(s)

    def test_design_get_definition_reads_the_derive_kind(self, host):
        s = host()
        dg = load_tool("design_get")
        result = payload(dg.handler(include=["definition"], feature="Derive1"))["definition"]
        assert [row["action"] for row in result["supported_edits"]] == [
            "inputs", "mode", "break_link"]
        assert result["type"] == "DeriveFeature" and self._unrolled(s)


def test_feature_edit_variant_selection_refuses_an_ambiguous_table(monkeypatch):
    monkeypatch.setattr(mod._edit, "_row_applies", lambda *_args: True)
    assert mod._edit._row_for(object(), {"variants": {"a": {}, "b": {}}}) is None
    only = {"attribute": "inputEntities"}
    assert mod._edit._row_for(object(), {"variants": {"a": only}}) is only


def test_mirror_body_descriptor_uses_parent_component_and_refuses_missing_owner(monkeypatch):
    monkeypatch.setattr(adsk.fusion, "BRepBody", BRepBody)
    monkeypatch.setattr(adsk.fusion, "BRepFace", BRepFace)
    owner = MakeComp(name="Component1", entity_token="component-token")
    body = BRepBody("MirrorBody", volume=1, area=6, parent_component=owner,
                    entity_token="mirror-body-token")
    plane = BRepFace(SimpleNamespace(surfaceType=adsk.core.SurfaceTypes.PlaneSurfaceType),
                     area=1, centroid=FakePoint(0, 0, 0), entity_token="mirror-plane-token",
                     body=body, point_on_face=FakePoint(0, 0, 0),
                     normal=FakeVector3D(0, 0, 1), param_reversed=False)
    monkeypatch.setattr(mod._inputs, "operand_meta", lambda _entity: {
        "assembly_path": None, "world_cm": [0.0, 0.0, 0.0]})
    monkeypatch.setattr(mod._inputs, "make_handle", lambda entity, *_args: entity.entityToken)
    monkeypatch.setattr(mod._edit, "_reference_geometry", lambda _entity, role: {"role": role})
    feature = SimpleNamespace(objectType="adsk::fusion::MirrorFeature", mirrorPlane=plane,
                              inputEntities=[body], isCombine=False)

    assert mod._inputs.entity_component(body) is owner
    state, definition, unavailable = mod._edit.feature_edit_state(feature)
    expected = {"handle": "mirror-body-token", "kind": "entity", "name": "MirrorBody",
                "owner": {"component": "Component1", "occurrence": None},
                "geometry": {"role": "entities"}}
    assert unavailable == {}
    assert state["input_entities"][0][0] is body
    assert state["input_entities"][0][1] == expected
    assert definition["input_entities"] == [expected]

    orphan = BRepBody("OrphanBody", volume=1, area=6, entity_token="orphan-body-token")
    feature.inputEntities = [orphan]
    state, definition, unavailable = mod._edit.feature_edit_state(feature)
    assert state["input_entities"] is None
    assert definition["input_entities"] is None
    assert unavailable["input_entities"] == "operand kind or owner is unreadable"


def test_collection_entities_reads_only_the_two_measured_swig_vectors_by_bounded_index():
    class BaseVector:
        def __init__(self, values): self.values, self.reads = values, []
        def __len__(self): return len(self.values)
        def __getitem__(self, index): self.reads.append(index); return self.values[index]
        def __iter__(self): raise AssertionError("unbounded iteration must not be used")

    class BRepFaceVector(BaseVector):
        pass

    profile, face = object(), object()
    profiles, faces = BaseVector([profile]), BRepFaceVector([face])
    assert mod._edit.collection_entities(profiles) == [profile]
    assert mod._edit.collection_entities(faces) == [face]
    assert profiles.reads == [0] and faces.reads == [0]

    oversized = BaseVector([object()] * 65)
    assert mod._edit.collection_entities(oversized) is None
    assert oversized.reads == []

    index_attempts = []
    def broken_index(self, index):
        index_attempts.append(index)
        raise RuntimeError("indexed getter failed")
    BrokenVector = type("BaseVector", (BaseVector,), {"__getitem__": broken_index})
    broken = BrokenVector([profile])
    assert mod._edit.collection_entities(broken) is None
    assert index_attempts == [0]

    class _LengthCounter:
        reads = 0
    def unread_length(self):
        _LengthCounter.reads += 1
        raise RuntimeError("length unavailable")
    UnreadLength = type("BRepFaceVector", (BaseVector,), {"__len__": unread_length})
    assert mod._edit.collection_entities(UnreadLength([face])) is None
    assert _LengthCounter.reads == 1

    class OtherVector(BaseVector):
        pass
    assert mod._edit.collection_entities(OtherVector([profile])) is None


@pytest.fixture
def grid_scene(monkeypatch, scene):
    feature, timeline, new_axis, before_axis, design, body = scene
    line_type = adsk.core.Curve3DTypes.Line3DCurveType
    second = BRepEdge(SimpleNamespace(curveType=line_type), start=FakePoint(0, 0, 0),
                      end=FakePoint(0, 1, 0), point_on_edge=SimpleNamespace(x=0, y=.5, z=0),
                      entity_token="axis-second", body=body)
    second.startVertex.body = second.endVertex.body = body
    feature.objectType = "adsk::fusion::RectangularPatternFeature"
    feature.name = feature.timelineObject.name = "Grid1"
    feature.directionOneEntity = before_axis
    feature.directionTwoEntity = second
    vectors = {id(before_axis): FakeVector3D(1, 0, 0),
               id(new_axis): FakeVector3D(0, 0, 1),
               id(second): FakeVector3D(0, 1, 0)}
    monkeypatch.setattr(type(feature), "directionOne",
                        property(lambda self: vectors.get(id(self.directionOneEntity))),
                        raising=False)
    monkeypatch.setattr(type(feature), "directionTwo", property(
        lambda self: (vectors.get(id(self.directionTwoEntity))
                      if self.directionTwoEntity is not None else
                      FakeVector3D(-1, 0, 0) if self.directionOneEntity is new_axis else
                      FakeVector3D(0, -1, 0))), raising=False)
    feature.inputEntities = [body]
    feature.patternElements = SimpleNamespace(count=6)
    feature.suppressedElementsIds = []
    feature.quantityOne = SimpleNamespace(expression="3")
    feature.quantityTwo = SimpleNamespace(expression="2")
    feature.distanceOne = SimpleNamespace(expression="10 mm")
    feature.distanceTwo = SimpleNamespace(expression="8 mm")
    feature.isSymmetricInDirectionOne = feature.isSymmetricInDirectionTwo = False
    feature.patternDistanceType = "fixture-distance-type"
    tokens = {"axis-before": before_axis, "axis-after": new_axis, "axis-second": second}
    monkeypatch.setattr(mod._inputs, "_resolve_token_entity",
                        lambda _design, token: tokens.get(token))
    original = mod._edit.reference_descriptor
    monkeypatch.setattr(mod._edit, "reference_descriptor", lambda entity, role:
        ({"handle": "body-token", "kind": "entity", "owner": {"component": "Part"},
          "geometry": {"volume": 1.0}} if role == "entities" else original(entity, role)))
    monkeypatch.setattr(mod._edit, "feature_geometry_snapshot", lambda _design: {
        "bodies": {("body-token", "urn:fixture"): {"component": "Part", "body": "Body1", "shape": {
            "measure": [feature.directionOneEntity.entityToken,
                        getattr(feature.directionTwoEntity, "entityToken", None)]}}},
        "occurrences": {}})
    return feature, timeline, before_axis, new_axis, second


def test_grid_retargets_one_direction_and_keeps_the_other(grid_scene):
    feature, timeline, _before_axis, new_axis, second = grid_scene
    result = payload(mod.handler(feature="Part/Grid1@1", action="axis",
                                 references=[{"direction_one": "axis-after"}]))
    assert result["edited"] is True and result["definition_matches"] is True
    assert result["geometry_changed"] is True
    assert feature.directionOneEntity is new_axis and feature.directionTwoEntity is second
    after = result["definition_after"]
    assert after["direction_one"]["handle"].startswith("axis-after")
    assert after["direction_two"] == result["definition_before"]["direction_two"]
    assert after["quantity_two"] == "2" and after["distance_two"] == "8 mm"
    assert timeline.markerPosition == timeline.count


def test_grid_retargets_both_directions_in_one_call(grid_scene):
    feature, _timeline, _before_axis, new_axis, second = grid_scene
    result = payload(mod.handler(feature="Part/Grid1@1", action="axis", references=[
        {"direction_one": "axis-second", "direction_two": "axis-after"}]))
    assert result["edited"] is True and result["definition_matches"] is True
    assert feature.directionOneEntity is second and feature.directionTwoEntity is new_axis
    assert result["definition_after"]["direction_two"]["handle"].startswith("axis-after")
    assert result["definition_before"]["direction_one"]["handle"].startswith("axis-before")


@pytest.mark.parametrize("references, token", [
    ({"direction_one": "axis-second"}, "axis-second"),
    ({"direction_two": "axis-before"}, "axis-before"),
    ({"direction_one": "axis-after", "direction_two": "axis-after"}, "axis-after"),
])
def test_grid_refuses_colliding_direction_entities_before_setters(
        grid_scene, monkeypatch, references, token):
    feature, timeline, before_axis, _new_axis, second = grid_scene
    monkeypatch.setattr(mod, "_set_directions", lambda *_args: pytest.fail("setter reached"))
    result = mod.handler(feature="Part/Grid1@1", action="axis", references=[references])
    message = error_message(result)
    assert "direction_one and direction_two" in message and token in message
    assert feature.directionOneEntity is before_axis and feature.directionTwoEntity is second
    assert timeline.markerPosition == timeline.count


def test_grid_direction_the_setter_ignores_is_an_error_and_both_are_restored(grid_scene,
                                                                           monkeypatch):
    feature, timeline, before_axis, _new_axis, second = grid_scene
    del feature.directionTwoEntity
    feature._direction_two_entity = second
    feature._drop_next_direction_two = True

    def set_two(self, value):
        self._direction_two_entity = None if self._drop_next_direction_two else value
        self._drop_next_direction_two = False

    monkeypatch.setattr(type(feature), "directionTwoEntity", property(
        lambda self: self._direction_two_entity, set_two), raising=False)
    result = mod.handler(feature="Part/Grid1@1", action="axis", references=[
        {"direction_two": "axis-after"}])
    assert result["isError"] is True
    assert "requested definition" in error_message(result)
    assert feature.directionOneEntity is before_axis and feature.directionTwoEntity is second
    assert result["details"]["edited"] is False and result["details"]["restore_gaps"] == []
    assert timeline.markerPosition == timeline.count


def test_grid_without_a_second_direction_entity_edits_one_and_refuses_two(grid_scene):
    feature, timeline, _before_axis, new_axis, _second = grid_scene
    feature.directionTwoEntity = None
    refused = mod.handler(feature="Part/Grid1@1", action="axis",
                          references=[{"direction_two": "axis-after"}])
    assert refused["isError"] is True
    assert "reads no direction_two entity" in error_message(refused)
    assert "pass direction_one only" in error_message(refused)
    assert feature.directionTwoEntity is None and timeline.markerPosition == timeline.count
    result = payload(mod.handler(feature="Part/Grid1@1", action="axis",
                                 references=[{"direction_one": "axis-after"}]))
    assert result["edited"] is True and feature.directionOneEntity is new_axis
    assert result["definition_after"]["direction_two"] is None
    assert result["definition_before"]["direction_two_vector"] == [0, -1, 0]
    assert result["definition_after"]["direction_two_vector"] == [-1, 0, 0]
    assert result["direction_two_vector_effect"] == {
        "before": [0, -1, 0], "after": [-1, 0, 0], "changed": True}
    assert feature.directionTwoEntity is None


@pytest.mark.parametrize("references", [[{}], [{"direction_three": "axis-after"}],
                                        ["axis-after"], [7],
                                        [{"direction_one": "axis-after", "extra": "x"}]])
def test_grid_references_must_name_only_the_two_direction_roles(grid_scene, references):
    feature, _timeline, before_axis, _new_axis, _second = grid_scene
    value, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        references, feature, "axis", mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType])
    assert value is None
    assert "direction_one and/or direction_two" in reason
    assert feature.directionOneEntity is before_axis


def test_grid_definition_offers_a_call_with_only_the_direction_entities_it_read(grid_scene):
    feature, _timeline, _before_axis, _new_axis, _second = grid_scene
    state, fields, unavailable = mod._edit.feature_edit_state(feature)
    assert unavailable == {}
    call = mod._edit.feature_definition_view(feature, state, fields, unavailable)[
        "supported_edits"][0]["call"]
    one, two = (fields[role]["handle"] for role in ("direction_one", "direction_two"))
    assert call == ("model_edit_feature(feature='Part/Grid1@1', action='axis', "
                    f"references=[{{'direction_one': '{one}', 'direction_two': '{two}'}}])")
    feature.directionTwoEntity = None
    state, fields, unavailable = mod._edit.feature_edit_state(feature)
    call = mod._edit.feature_definition_view(feature, state, fields, unavailable)[
        "supported_edits"][0]["call"]
    assert unavailable == {} and call.endswith(f"references=[{{'direction_one': '{one}'}}])")
    definition = mod._edit.feature_definition_view(feature, state, fields, unavailable)
    assert definition["direction_two_vector"] == [0, -1, 0]
    assert "may move with direction_one" in definition["direction_two_note"]
    assert mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType]["axis"]["example"] == (
        "references=[{'direction_one': 'z'}]")
