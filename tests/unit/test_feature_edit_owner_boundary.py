from conftest import install as _install_design
from types import SimpleNamespace

import pytest
import adsk.core

from conftest import MakeComp, load_tool


mod = load_tool("model_edit_feature")


@pytest.mark.parametrize("owner_kind", ["feature", "foreign", "unread"])
@pytest.mark.parametrize("feature_kind", ["DraftFeature", "ShellFeature", "OffsetFeature"])
def test_face_proxy_localizes_only_for_a_proven_feature_owner(monkeypatch, owner_kind, feature_kind):
    component = MakeComp(name="FeatureEditBench", entity_token="feature-component")
    other = MakeComp(name="FeatureEditBench", entity_token="other-component")
    owner = component if owner_kind == "feature" else other if owner_kind == "foreign" else None
    native = SimpleNamespace(entityToken="native-face", body=SimpleNamespace(parentComponent=owner))
    proxy = SimpleNamespace(nativeObject=native, assemblyContext=SimpleNamespace(
        name="FeatureEditBench:1", transform2=object()), entityToken="placed-face")
    design = SimpleNamespace(rootComponent=component)
    feature = SimpleNamespace(objectType="adsk::fusion::" + feature_kind, parentComponent=component)
    calls = []
    original = mod._inputs.operand_in

    def guarded(label, entity, *args):
        calls.append(entity)
        return original(label, entity, *args)

    monkeypatch.setattr(mod._inputs, "operand_in", guarded)
    _install_design(mod, design)
    monkeypatch.setattr(mod._inputs.GeometryHandleList, "resolve",
                        lambda *_args: ([proxy], None))
    resolved, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["placed-face"], feature, "inputs",
        mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType])

    assert reason is None
    assert calls == [proxy]
    assert resolved == [native if owner_kind == "feature" and feature_kind != "OffsetFeature"
                        else proxy]


def test_feature_edit_discloses_shared_owner_definition():
    assert "shared owner component" in mod.tool.description


def test_axis_proxy_keeps_its_placed_context(monkeypatch):
    component = MakeComp(name="FeatureEditBench", entity_token="feature-component")
    design = SimpleNamespace(rootComponent=component)
    feature = SimpleNamespace(objectType="adsk::fusion::RevolveFeature",
                              parentComponent=component)
    context = SimpleNamespace(name="FeatureEditBench:1", transform2=object())
    proxy = SimpleNamespace(nativeObject=SimpleNamespace(
        entityToken="native-axis", parentComponent=component),
                            assemblyContext=context,
                            entityToken="placed-axis")
    _install_design(mod, design)
    monkeypatch.setattr(mod._inputs.AxisRef, "resolve",
                        lambda *_args, **_kwargs: (("edge", proxy), None))
    monkeypatch.setattr(mod._inputs, "operand_in", lambda _label, entity, *_args: (entity, None))

    resolved, reason = mod._inputs.FeatureEditOperands("references").resolve_for(
        ["axis-handle"], feature, "axis",
        {feature.objectType: {"axis": {"reference": "axis", "cardinality": "one"}}})

    assert reason is None and resolved is proxy
    assert resolved.assemblyContext is context


class _Collection:
    def __init__(self, values=()):
        self.values = list(values)

    def add(self, value):
        self.values.append(value)
        return True

    @property
    def count(self):
        return len(self.values)

    def item(self, index):
        return self.values[index]


def _fillet_state_scene(monkeypatch, tangent_values=(False, True), unread_index=None):
    class EdgeSet:
        def __init__(self, index, tangent, edges=None, on_replace=None):
            self.objectType = "adsk::fusion::ConstantRadiusFilletEdgeSet"
            self._edges = edges or _Collection([SimpleNamespace(entityToken=f"old-{index}")])
            self.assigned = []
            self._tangent = tangent
            self._deleted = False
            self._on_replace = on_replace
            self.radius = SimpleNamespace(expression=f"{index + 1} mm")
            self.continuity = 1
            self.tangencyWeight = SimpleNamespace(
                value=1.0, expression="1", name="d5",
                objectType="adsk::fusion::ModelParameter")

        @property
        def edges(self):
            if self._deleted:
                raise RuntimeError("An API Object refers to a deleted Object")
            return self._edges

        @edges.setter
        def edges(self, value):
            assert isinstance(value, _Collection)
            self.assigned.append(value)
            self._edges = value
            self.isTangentChain = False
            self._deleted = True
            self._on_replace(self, value)

        @property
        def isTangentChain(self):
            if self._deleted:
                raise RuntimeError("An API Object refers to a deleted Object")
            if self._index == unread_index:
                raise RuntimeError("tangent chain unread")
            return self._tangent

        @isTangentChain.setter
        def isTangentChain(self, value):
            if self._deleted:
                raise RuntimeError("An API Object refers to a deleted Object")
            self._tangent = value

    edge_sets, edge_set_collection = [], _Collection()
    for i, tangent in enumerate(tangent_values):
        def replace_edge_set(old, values, index=i):
            fresh = EdgeSet(index, False, values, old._on_replace)
            fresh.assigned = old.assigned
            fresh._index = index
            edge_sets[index] = fresh
            edge_set_collection.values[index] = fresh

        edge_set = EdgeSet(i, tangent, on_replace=replace_edge_set)
        edge_set._index = i
        edge_sets.append(edge_set)
        edge_set_collection.add(edge_set)
    feature = SimpleNamespace(
        objectType="adsk::fusion::FilletFeature",
        filletFeatureType=adsk.fusion.FilletFeatureTypes.FilletFeatureType,
        edgeSets=edge_set_collection)
    monkeypatch.setattr(mod._edit, "reference_descriptor", lambda entity, _kind: {
        "handle": entity.entityToken, "kind": "edge", "owner": {"component": "Part"}})
    state, definition, unavailable = mod._edit.feature_edit_state(feature)
    return feature, edge_sets, state, definition, unavailable


@pytest.mark.parametrize("set_index,expected", [(0, False), (1, True)])
def test_fillet_edge_set_apply_and_restore_use_measured_state(
        monkeypatch, set_index, expected):
    feature, edge_sets, before, definition, unavailable = _fillet_state_scene(monkeypatch)
    assert unavailable == {}
    assert definition["edge_sets"][set_index]["is_tangent_chain"] is expected
    assert before[f"edge_set_{set_index}_tangent_chain"] is expected
    edge_set = feature.edgeSets.item(set_index)
    row = dict(mod._edit._row_for(
        feature, mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType]["inputs"]),
        set_index=set_index)
    requested = SimpleNamespace(entityToken=f"new-{set_index}")
    original_edge = edge_set.edges.item(0)
    monkeypatch.setattr(adsk.core.ObjectCollection, "create", staticmethod(_Collection))

    mod._apply_value(feature, row, [requested], None, before)
    assert feature.edgeSets.item(set_index).isTangentChain is expected
    mod._restore_value(feature, row, [original_edge], before)

    assert len(edge_set.assigned) == 2
    assert edge_set.assigned[0].item(0) is requested
    assert edge_set.assigned[1].item(0) is original_edge
    assert feature.edgeSets.item(set_index).isTangentChain is expected


def test_fillet_edit_refuses_unread_tangent_chain_before_mutation(monkeypatch):
    feature, edge_sets, before, _definition, unavailable = _fillet_state_scene(
        monkeypatch, unread_index=1)
    assert "edge_sets" in unavailable
    row = dict(mod._edit._row_for(
        feature, mod._edit.FEATURE_EDIT_SUPPORT[feature.objectType]["inputs"]),
        set_index=1)
    before.pop("edge_set_1_tangent_chain", None)
    original = edge_sets[1].edges
    monkeypatch.setattr(adsk.core.ObjectCollection, "create", staticmethod(_Collection))

    with pytest.raises(RuntimeError, match="tangent-chain setting is unreadable"):
        mod._apply_value(feature, row, [SimpleNamespace(entityToken="new")], None, before)

    assert edge_sets[1].edges is original
    assert edge_sets[1].assigned == []


def test_shell_input_apply_and_restore_keep_banked_tangent_chain(monkeypatch):
    class Collection:
        def __init__(self, values=()):
            self.values = list(values)

        def add(self, value):
            self.values.append(value)
            return True

    face_before, face_after = object(), object()
    original = Collection([face_before])
    calls = []

    class Shell:
        isTangentChain = False

        def setInputEntities(self, collection, isTangentChain=True):
            calls.append((collection, isTangentChain))
            self.isTangentChain = isTangentChain
            return True

    shell = Shell()
    row = mod._edit.FEATURE_EDIT_SUPPORT["adsk::fusion::ShellFeature"]["inputs"]
    before = {"is_tangent_chain": False}
    monkeypatch.setattr(adsk.core.ObjectCollection, "create", staticmethod(Collection))

    mod._apply_value(shell, row, [face_after], None, before)
    assert shell.isTangentChain is False
    assert mod._restore_value(shell, row, (original, [face_before]), before) is True

    assert [(collection.values, tangent) for collection, tangent in calls] == [
        ([face_after], False), ([face_before], False)]
    assert shell.isTangentChain is False
