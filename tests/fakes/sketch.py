# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The sketch world: profiles, the per-kind curve collections, the sketch and its points."""

import types

from tests.fakes.geometry import FakePoint
from tests.fakes.scaffold import _NamedCollection, fusion_fake


@fusion_fake(live_type="Profile", facts=("shape-dump-design-world",))
class Profile:
    """A sketch profile: the boundingBox and profileLoops a region walk reads, the
    areaProperties() a profile handle's locator re-finds it by, and its entityToken. `tag` names
    the instance in a failure message and is not a live member. `centroid` takes a FakePoint or an
    (x, y, z) tuple; `loops` takes loop objects or a bare count."""
    def __init__(self, tag=None, bbox=None, loops=(), area=None, centroid=None,
                 entity_token=None, parent_sketch=None):
        self._tag = tag
        self._area = area
        self._centroid = FakePoint(*centroid) if isinstance(centroid, tuple) else centroid
        self.boundingBox = bbox
        self.profileLoops = _NamedCollection([None] * loops if isinstance(loops, int)
                                             else list(loops))
        self.entityToken = entity_token
        self.parentSketch = parent_sketch

    def __repr__(self):
        return f"Profile({self._tag!r})"

    def areaProperties(self, accuracy=None):
        return types.SimpleNamespace(area=self._area, centroid=self._centroid)


def make_sketch_curve(token="curve0", length=1.0, is_closed=None):
    """One sketch curve: entityToken + length (cm), the pair a curve-edit read-back keys on. Only a
    fitted spline reports isClosed live, so it is set only when given. Attach the in-place edit
    methods a test drives (trim/extend/breakCurve/split) to the returned object."""
    curve = types.SimpleNamespace(entityToken=token, length=length, isConstruction=False)
    if is_closed is not None:
        curve.isClosed = is_closed
    return curve


_CURVE_KINDS = ("sketchLines", "sketchArcs", "sketchCircles", "sketchEllipses",
                "sketchEllipticalArcs", "sketchConicCurves",
                "sketchFittedSplines", "sketchControlPointSplines", "sketchFixedSplines")


@fusion_fake(live_type="SketchCurves", facts=("shape-dump-timeline-world",))
class SketchCurves:
    """A sketch's curves: the per-kind sub-collections a '<type>:<index>' ref indexes, with the flat
    count/item/iteration DERIVED from them - so a curve added to one, and a sub-collection a
    subclass swapped in, are both in the flat walk. A collection-level factory a test drives
    (sketchArcs.addFillet, sketchLines.addDistanceChamfer) is attached to the sub-collection.

    It HOLDS a _NamedCollection rather than being one: live SketchCurves carries no itemByName.
    `_items` is the flat walk's own tail, where a test lands a curve without naming its kind."""
    def __init__(self, lines=(), arcs=(), circles=(), ellipses=(), splines=()):
        self._items = []
        self.sketchLines = _NamedCollection(lines)
        self.sketchArcs = _NamedCollection(arcs)
        self.sketchCircles = _NamedCollection(circles)
        self.sketchEllipses = _NamedCollection(ellipses)
        self.sketchEllipticalArcs = _NamedCollection()
        self.sketchConicCurves = _NamedCollection()
        self.sketchFittedSplines = _NamedCollection(splines)
        self.sketchControlPointSplines = _NamedCollection()
        self.sketchFixedSplines = _NamedCollection()

    def _flat(self):
        # Rebuilt per call, so a kind a subclass swapped in and a curve a factory grew are both in
        # the walk. A curve landed in a kind AND in the tail is still one curve, so the tail
        # contributes only what no kind holds. The shared collection, so the measured
        # out-of-range raise lives in one place.
        kinded = [c for kind in _CURVE_KINDS for c in getattr(self, kind, ())]
        return _NamedCollection(kinded + [c for c in self._items
                                          if not any(c is k for k in kinded)])

    @property
    def count(self):
        return self._flat().count

    def item(self, i):
        return self._flat().item(i)

    def __iter__(self):
        return iter(self._flat())


INJECTED_SKETCH_FAULTS = ("name_write_ignored", "visible_write_ignored", "visible_unreadable")


@fusion_fake(live_type="Sketch",
             facts=("shape-dump-design-world", "sketch-profiles-under-compute-deferred"))
class Sketch:
    """A sketch: its name, sketchCurves, sketchPoints and the parentComponent a feature must be
    built in. `profiles` are the closed regions a blind profiles.item(0) indexes and
    `is_compute_deferred` the flag whose True makes those regions the pre-deferral ones.
    `is_visible` is the browser bulb a tool hides a helper sketch behind. `entity_token` is the
    identity half two sketch references are compared on and `timeline_object` the timeline entry a
    sketch is addressed by; both are set only when given, since a sketch whose token or timeline
    item does not read is its own tested state.

    `injected` names INJECTED_SKETCH_FAULTS entries, faults no live measurement backs.
    `taken_names` are names a sibling sketch holds: writing one adopts '<name> (1)', as measured."""
    def __init__(self, name="Sketch1", curves=None, points=(), profiles=(),
                 is_compute_deferred=False, parent_component=None, is_visible=True,
                 entity_token=None, timeline_object=None, transform=None, injected=(),
                 taken_names=()):
        self._taken_names = frozenset(taken_names)
        unknown = sorted(set(injected) - set(INJECTED_SKETCH_FAULTS))
        if unknown:
            raise ValueError(f"unknown injected sketch fault(s) {unknown}; "
                             f"known: {list(INJECTED_SKETCH_FAULTS)}")
        # The seed values are not assignments a fault swallows, so the faults arm last.
        self._injected = frozenset()
        self.name = name
        if entity_token is not None:
            self.entityToken = entity_token
        if timeline_object is not None:
            self.timelineObject = timeline_object
        # `transform` maps sketch space into the component's (a FakeMatrix3D), set only when given.
        if transform is not None:
            self.transform = transform
        self.sketchCurves = SketchCurves() if curves is None else curves
        self.sketchPoints = _NamedCollection(points)
        self.profiles = _NamedCollection(profiles)
        self.isComputeDeferred = is_compute_deferred
        self.parentComponent = parent_component
        self.isVisible = is_visible
        self._injected = frozenset(injected)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        if "name_write_ignored" not in self._injected:
            self._name = value + " (1)" if value in self._taken_names else value

    @property
    def isVisible(self):
        if "visible_unreadable" in self._injected:
            raise RuntimeError("injected unreadable isVisible")
        return self._visible

    @isVisible.setter
    def isVisible(self, value):
        if "visible_write_ignored" not in self._injected:
            self._visible = value


@fusion_fake(live_type="SketchPoint", facts=("shape-dump-timeline-world",))
class FakeSketchPoint:
    """One point a sketch owns - the 'point:<index>' address space sketchPoints indexes - carrying
    its SKETCH-space `geometry`; no isConstruction, which SketchPoint lacks. `assembly_context` is
    the occurrence a PROXY is read through - None on a native - and `native_object`
    what it stands for; `parent_sketch` and `entity_token` are set only when given."""
    def __init__(self, geometry=None, parent_sketch=None, entity_token=None,
                 assembly_context=None, native_object=None):
        self.geometry = geometry
        self.assemblyContext = assembly_context
        if parent_sketch is not None:
            self.parentSketch = parent_sketch
        if entity_token is not None:
            self.entityToken = entity_token
        if native_object is not None:
            self.nativeObject = native_object


@fusion_fake(factory_for="Sketch")
def make_sketch(name="Sketch1", lines=(), arcs=(), circles=(), ellipses=(), splines=(), points=(),
                profiles=(), is_compute_deferred=False, parent_component=None, is_visible=True):
    """A Sketch whose curves are grouped into the per-kind sub-collections. Members come from
    make_sketch_curve."""
    curves = SketchCurves(lines, arcs, circles, ellipses, splines)
    return Sketch(name, curves, points, profiles, is_compute_deferred, parent_component,
                  is_visible)


def sketch_curves_edit(collection, add=(), remove=()):
    """Apply a curve add/remove to the per-kind sub-collection a '<type>:<index>' ref indexes - the
    one place a sketch curve lives, since the flat sketchCurves walk derives from the kinds."""
    for curve in remove:
        collection._items.remove(curve)
    for curve in add:
        collection._items.append(curve)
