"""Doubles and one scene builder for the datum and joint-origin edit tests.

ConstructionPlane, ConstructionAxis, ConstructionPoint and their definition classes carry no
measured shape, so each double here holds only the members the edit reads or writes.
"""
from types import SimpleNamespace

import adsk.core
import adsk.fusion

from conftest import install as _install_design
from tests.fakes.design import (BRepBody, BRepEdge, BRepFace, FakeTimeline, FakeTimelineObject,
                                 MakeComp, MakeDesign)
from tests.fakes.geometry import FakePoint, FakeVector3D, make_bbox
from tests.fakes.joints import FakeJointOrigin
from tests.fakes.scaffold import _Vertex, fusion_fake

_PLANE_NORMALS = {"xy": (0, 0, 1), "xz": (0, 1, 0), "yz": (1, 0, 0)}


class _Datum:
    """The members every construction datum double shares; these types have no measured shape."""

    def __init__(self, name, component, token, row=None):
        self.name, self.component, self.entityToken = name, component, token
        self.isParametric = self.isValid = True
        self.timelineObject = row
        self.definition = None


@fusion_fake(scenario_double="datum edit scene construction-plane double")
class DatumPlane(_Datum):
    """A construction plane double; ConstructionPlane has no measured shape."""
    objectType = "adsk::fusion::ConstructionPlane"

    def __init__(self, name, component, token, origin=(0, 0, 0), normal=(0, 0, 1), row=None):
        super().__init__(name, component, token, row)
        self.place(origin, normal)

    def place(self, origin, normal):
        self.geometry = SimpleNamespace(origin=FakePoint(*origin), normal=FakeVector3D(*normal))


@fusion_fake(scenario_double="datum edit scene construction-axis double")
class DatumAxis(_Datum):
    """A construction axis double; ConstructionAxis has no measured shape."""
    objectType = "adsk::fusion::ConstructionAxis"

    def __init__(self, name, component, token, origin=(0, 0, 0), direction=(0, 0, 1), row=None):
        super().__init__(name, component, token, row)
        self.place(origin, direction)

    def place(self, origin, direction):
        self.geometry = SimpleNamespace(origin=FakePoint(*origin),
                                        direction=FakeVector3D(*direction))


@fusion_fake(scenario_double="datum edit scene construction-point double")
class DatumPoint(_Datum):
    """A construction point double; ConstructionPoint has no measured shape."""
    objectType = "adsk::fusion::ConstructionPoint"

    def __init__(self, name, component, token, at=(0, 0, 0), row=None):
        super().__init__(name, component, token, row)
        self.geometry = FakePoint(*at)


@fusion_fake(scenario_double="datum edit scene owned vertex with a body reference")
class OwnedVertex(_Vertex):
    """The shared vertex plus the owning body an operand descriptor reads."""

    def __init__(self, point, entity_token, body):
        super().__init__(point, entity_token)
        self.body = body


class _Definition:
    """What every datum definition double records: each write, and how the write behaves."""

    def __init__(self, datum, world, returns=True, lands="requested"):
        self.datum, self.world = datum, world
        self.returns, self.lands = returns, lands
        self.calls, self.home = [], None

    def _landing(self, requested, other):
        """The operand that lands: the requested one, a different one, or none; home always lands."""
        if requested is self.home:
            return requested
        return {"requested": requested, "other": other, "nothing": None}[self.lands]

    def _answer(self, requested):
        """A redefine's bool: the configured answer, and True for the home operand."""
        return True if requested is self.home else self.returns


class OffsetPlaneDefinition(_Definition):
    """ConstructionPlaneOffsetDefinition double: offset, planarEntity and redefine only."""
    objectType = "adsk::fusion::ConstructionPlaneOffsetDefinition"

    def __init__(self, datum, world, base, other, expression="10.00 mm", **behaviour):
        super().__init__(datum, world, **behaviour)
        self.planarEntity, self.other, self.home = base, other, base
        self.offset = SimpleNamespace(expression=expression)

    def redefine(self, offset, planar_entity):
        self.calls.append((offset, planar_entity))
        landed = self._landing(planar_entity, self.other)
        if landed is not None:
            self.planarEntity = landed
            normal = landed.geometry.normal
            origin = landed.geometry.origin
            self.datum.place((origin.x + normal.x, origin.y + normal.y, origin.z + normal.z),
                             (normal.x, normal.y, normal.z))
            self.world["shape"] = "start" if landed is self.home else landed.name
        return self._answer(planar_entity)


class TwoPlaneAxisDefinition(_Definition):
    """ConstructionAxisTwoPlaneDefinition double: the two planar entities and redefine only."""
    objectType = "adsk::fusion::ConstructionAxisTwoPlaneDefinition"

    def __init__(self, datum, world, one, two, other, **behaviour):
        super().__init__(datum, world, **behaviour)
        self.planarEntityOne, self.planarEntityTwo, self.other, self.home = one, two, other, one

    def redefine(self, planar_entity_one, planar_entity_two):
        self.calls.append((planar_entity_one, planar_entity_two))
        landed = self._landing(planar_entity_one, self.other)
        if landed is not None:
            self.planarEntityOne, self.planarEntityTwo = landed, planar_entity_two
            origin = landed.geometry.origin
            self.datum.place((origin.x, origin.y, origin.z), (0, 0, 1))
            self.world["shape"] = "start" if landed is self.home else landed.name
        return self._answer(planar_entity_one)


class PointEntityDefinition(_Definition):
    """ConstructionPointPointDefinition double: the settable pointEntity only."""
    objectType = "adsk::fusion::ConstructionPointPointDefinition"

    def __init__(self, datum, world, vertex, other, **behaviour):
        super().__init__(datum, world, **behaviour)
        self._vertex, self.other, self.home = vertex, other, vertex

    @property
    def pointEntity(self):
        return self._vertex

    @pointEntity.setter
    def pointEntity(self, value):
        self.calls.append(value)
        landed = self._landing(value, self.other)
        if landed is not None:
            self._vertex = landed
            self.datum.geometry = landed.geometry.copy()
            self.world["shape"] = "start" if landed is self.home else landed.entityToken


@fusion_fake(scenario_double="datum edit scene joint-origin double with retained frame members")
class AnchoredJointOrigin(FakeJointOrigin):
    """The shared joint origin plus the geometry, frame and retained members a re-anchor reads."""
    objectType = "adsk::fusion::JointOrigin"

    def __init__(self, component, row, geometry, other=None, lands="requested"):
        zero = lambda: SimpleNamespace(expression="0 mm")
        super().__init__("Origin1", component,
                         offsets={"offsetX": zero(), "offsetY": zero(), "offsetZ": zero()})
        self.entityToken, self.isValid, self.timelineObject = "origin-token", True, row
        self.isFlipped = False
        self.angle = SimpleNamespace(expression="0 deg")
        self._geometry, self._other, self._lands, self._home = geometry, other, lands, geometry
        self.assigned = []

    @property
    def geometry(self):
        return self._geometry

    @geometry.setter
    def geometry(self, value):
        self.assigned.append(value)
        if self._lands == "requested" or value is self._home:
            self._geometry = value
        elif self._lands == "other":
            self._geometry = self._other

    @property
    def transform(self):
        return SimpleNamespace(translation=self._geometry.origin)

    primaryAxisVector = property(lambda self: self._geometry.primaryAxisVector)
    secondaryAxisVector = property(lambda self: self._geometry.secondaryAxisVector)
    thirdAxisVector = property(lambda self: self._geometry.thirdAxisVector)


@fusion_fake(factory_for="FakePoint")
def joint_geometry(face, origin, primary, secondary, third):
    """A JointGeometry stand-in holding the entity and the frame the origin's members read."""
    return SimpleNamespace(entityOne=face, origin=FakePoint(*origin),
                           primaryAxisVector=FakeVector3D(*primary),
                           secondaryAxisVector=FakeVector3D(*secondary),
                           thirdAxisVector=FakeVector3D(*third))


@fusion_fake(factory_for="BRepFace")
def _face(token, body, at, normal):
    return BRepFace(SimpleNamespace(surfaceType=adsk.core.SurfaceTypes.PlaneSurfaceType), area=1,
                    centroid=FakePoint(*at), entity_token=token, body=body,
                    point_on_face=FakePoint(*at), normal=FakeVector3D(*normal),
                    param_reversed=False)


@fusion_fake(factory_for="DatumPlane")
def datum_scene(mod, monkeypatch, kind, **behaviour):
    """One three-row timeline whose middle row is the datum or joint origin under edit."""
    edit = getattr(mod, "_edit", None) or mod._edit_feature_common
    for name, double in (("BRepFace", BRepFace), ("BRepEdge", BRepEdge),
                         ("BRepVertex", OwnedVertex), ("ConstructionPlane", DatumPlane),
                         ("ConstructionAxis", DatumAxis), ("ConstructionPoint", DatumPoint)):
        monkeypatch.setattr(adsk.fusion, name, double)
    planes = {}
    component = MakeComp(name="Part", entity_token="part-token")
    for alias, normal in _PLANE_NORMALS.items():
        planes[alias] = DatumPlane(alias.upper(), component, f"{alias}-token", normal=normal)
    component.xYConstructionPlane = planes["xy"]
    component.xZConstructionPlane = planes["xz"]
    component.yZConstructionPlane = planes["yz"]
    body = BRepBody("Body1", volume=1, area=6, bbox=make_bbox((0, 0, 0), (1, 1, 1)),
                    parent_component=component)
    component.bRepBodies = component.bRepBodies.__class__([body])
    names = {"plane": "Plane1", "axis": "Axis1", "point": "Point1", "origin": "Origin1"}
    row = FakeTimelineObject(names[kind], 1)
    rows = [FakeTimelineObject("Previous", 0), row, FakeTimelineObject("Next", 2)]
    timeline = FakeTimeline(rows, marker=3)
    row.rollTo = lambda before: (row._rolls.append(bool(before)),
                                 setattr(timeline, "markerPosition", 1 if before else 2), True)[2]
    design = MakeDesign(comp=component, timeline=timeline)
    world = {"shape": "start"}
    health = {"errors": [], "warnings": []}
    parallel = DatumPlane("Parallel", component, "parallel-token", origin=(0, 0, 0.5))
    tokens = {"parallel-token": parallel}
    if kind == "plane":
        entity = DatumPlane("Plane1", component, "plane-token", origin=(0, 0, 1), row=row)
        entity.definition = OffsetPlaneDefinition(entity, world, planes["xy"], planes["yz"],
                                                  **behaviour)
    elif kind == "axis":
        entity = DatumAxis("Axis1", component, "axis-token", row=row)
        entity.definition = TwoPlaneAxisDefinition(entity, world, planes["xy"], planes["xz"],
                                                   planes["yz"], **behaviour)
    elif kind == "point":
        first = OwnedVertex(FakePoint(0, 0, 0), "vertex-a", body)
        tokens["vertex-b"] = OwnedVertex(FakePoint(1, 1, 1), "vertex-b", body)
        entity = DatumPoint("Point1", component, "point-token", row=row)
        entity.definition = PointEntityDefinition(
            entity, world, first, OwnedVertex(FakePoint(2, 2, 2), "vertex-c", body), **behaviour)
    else:
        top = _face("face-top", body, (1, 1, 1), (0, 0, 1))
        tokens["face-side"] = _face("face-side", body, (0, 1, 0.5), (-1, 0, 0))
        elsewhere = joint_geometry(_face("face-else", body, (2, 2, 2), (0, 1, 0)), (2, 2, 2),
                                   (0, 1, 0), (1, 0, 0), (0, 0, 1))
        entity = AnchoredJointOrigin(
            component, row, joint_geometry(top, (1, 1, 1), (0, 0, 1), (1, 0, 0), (0, 1, 0)),
            elsewhere, **behaviour)
        monkeypatch.setattr(adsk.fusion.JointGeometry, "createByPlanarFace",
                            lambda face, _edge, _keypoint: joint_geometry(
                                face, (0, 1, 0.5), (-1, 0, 0), (0, 0, 1), (0, -1, 0)))
    row.entity = entity
    _install_design(mod, design)
    monkeypatch.setattr(mod._inputs, "_resolve_token_entity",
                        lambda _design, token: tokens.get(token))
    monkeypatch.setattr(edit.adsk.core.ValueInput, "createByString", lambda text: ("text", text))
    monkeypatch.setattr(edit, "health", lambda *_args: {key: list(value)
                                                        for key, value in health.items()})
    monkeypatch.setattr(edit, "same_feature", lambda *_args: True)
    monkeypatch.setattr(edit, "feature_geometry_snapshot", lambda _design: {
        "bodies": {("Body1", None): {"component": "Part", "body": "Body1",
                            "shape": {"placed": world["shape"]}}},
        "occurrences": {}})
    return SimpleNamespace(entity=entity, definition=getattr(entity, "definition", None), row=row,
                           rows=rows,
                           timeline=timeline, design=design, component=component, planes=planes,
                           parallel=parallel, tokens=tokens, world=world, health=health)
