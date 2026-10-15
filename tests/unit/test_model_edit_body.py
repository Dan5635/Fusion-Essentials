"""Handler checks for body ownership edits and fresh placement references."""

import json
from types import SimpleNamespace

import pytest
import adsk.core
import adsk.fusion

from conftest import (BRepBody, BRepFace, BRepEdge, Plane, FakeVector3D, Line3D,
                      MeshBody, FakeMatrix3D, FakeOccurrence, FakePoint, MakeComp, MakeDesign,
                      body_proxy, install, load_tool, make_bbox, payload)


mod = load_tool("model_edit_body")


class _NativeOccurrenceWithoutToken(FakeOccurrence):
    """A nested native occurrence whose token read Fusion refuses."""

    @property
    def entityToken(self):
        raise RuntimeError("Tokens can only be created for proxies whose top-level parent is the root component.")


class _PlacedOccurrence(FakeOccurrence):
    """A placed occurrence with a readable proxy token and tokenless native occurrence."""

    def __init__(self, path, component, native, token):
        super().__init__(path, component=component, entity_token=token,
                         transform2=FakeMatrix3D())
        self._native = native

    @property
    def nativeObject(self):
        return self._native


def _body(name, token, owner):
    return BRepBody(name, bbox=make_bbox((0, 0, 0), (1, 1, 1)), volume=1.0,
                    area=6.0, vertices=(FakePoint(0, 0, 0), FakePoint(1, 1, 1)),
                    parent_component=owner, entity_token=token)


@pytest.fixture
def scene(monkeypatch):
    """Two populated owners, one selected body and a real shared-fake occurrence."""
    source_owner = MakeComp("Root", entity_token="ROOT")
    dest_owner = MakeComp("Dest", entity_token="DEST")
    selected = _body("Picked", "OLD", source_owner)
    sibling = _body("Sibling", "SIB", source_owner)
    sentinel = _body("Sentinel", "SENT", dest_owner)
    source_owner.bRepBodies._items.extend((selected, sibling))
    dest_owner.bRepBodies._items.append(sentinel)
    target = FakeOccurrence("Dest:1", component=dest_owner, entity_token="OCCDEST",
                            transform2=FakeMatrix3D(t=(3, 4, 0)))
    source_owner.occurrences._items.append(target)
    source_owner.allOccurrences.append(target)
    design = MakeDesign(comp=source_owner, all_components=[source_owner, dest_owner],
                        design_type=0)
    install(mod, design)
    monkeypatch.setattr(adsk.fusion, "BRepBody", BRepBody)
    monkeypatch.setattr(adsk.fusion, "MeshBody", MeshBody)
    state = {"result": None, "context": target, "called": 0}

    def resolve(raw):
        if raw == "OLD":
            return selected, None
        if state["result"] is not None and raw == body_proxy(state["result"], state["context"]).entityToken:
            return body_proxy(state["result"], state["context"]), None
        return None, "unknown body handle"

    monkeypatch.setattr(mod._BODY, "resolve", resolve)
    monkeypatch.setattr(mod._DESTINATION, "resolve", lambda raw: (target, None))

    def copy(destination):
        state["called"] += 1
        new = _body("Picked", "NEW", dest_owner)
        dest_owner.bRepBodies._items.append(new)
        state["result"] = new
        return body_proxy(new, destination)

    def move(destination):
        state["called"] += 1
        source_owner.bRepBodies._items.remove(selected)
        new = _body("Picked", "NEW", dest_owner)
        dest_owner.bRepBodies._items.append(new)
        state["result"] = new
        return body_proxy(new, destination)

    def create():
        state["called"] += 1
        source_owner.bRepBodies._items.remove(selected)
        child = MakeComp("Child", entity_token="CHILD")
        new = _body("Picked", "NEW", child)
        child.bRepBodies._items.append(new)
        child_occ = FakeOccurrence("Child:1", component=child, entity_token="OCCCHILD",
                                   transform2=FakeMatrix3D())
        source_owner.occurrences._items.append(child_occ)
        source_owner.allOccurrences.append(child_occ)
        state.update(result=new, context=child_occ)
        return new

    selected._organization = lambda action, destination: {
        "copy": lambda: copy(destination), "move": lambda: move(destination),
        "create_component": create}[action]()
    return state, source_owner, dest_owner, target, selected


def _data(reply):
    assert reply["isError"] is False, reply
    return json.loads(reply["content"][0]["text"])


def test_copy_keeps_source_and_returns_destination_proxy(scene):
    state, source, dest, target, selected = scene
    result = _data(mod.handler(action="copy", body="OLD", destination="Dest:1"))
    assert state["called"] == 1
    assert selected in source.bRepBodies._items
    assert result["handle"] == body_proxy(state["result"], target).entityToken
    assert result["full_path"] == "Dest:1"
    assert result["source_retained"] is True
    assert (result["source_membership_before"], result["source_membership_after"]) == (2, 2)
    assert (result["destination_membership_before"], result["destination_membership_after"]) == (1, 2)
    assert result["witness_check"]["unchanged"] is True
    assert result["timeline_health"] == {"checked": False, "healthy": None}


def test_brep_copy_keeps_repeated_destination_available(scene):
    state, source, dest, target, selected = scene
    second = FakeOccurrence("Dest:2", component=dest, entity_token="OCCDEST2",
                            transform2=FakeMatrix3D(t=(7, 0, 0)))
    source.occurrences._items.append(second)
    source.allOccurrences.append(second)

    result = _data(mod.handler(action="copy", body="OLD", destination="Dest:1"))
    assert state["called"] == 1
    assert result["definition_effect"]["destination_placements"]["count"] == 2
    assert result["full_path"] == "Dest:1"


def test_move_reports_replacement_identity(scene):
    state, source, dest, target, selected = scene
    result = _data(mod.handler(action="move", body="OLD", destination="Dest:1"))
    assert state["called"] == 1 and selected not in source.bRepBodies._items
    assert state["result"] is not selected
    assert result["source_retained"] is False
    assert result["source_membership_after"] == 1
    assert result["definition_effect"]["destination_placements"]["paths"] == ["Dest:1"]


def test_move_to_nested_occurrence_uses_component_identity_when_native_token_raises(scene, monkeypatch):
    state, source, dest, _target, selected = scene
    native = _NativeOccurrenceWithoutToken("Dest:1", component=dest,
                                            transform2=FakeMatrix3D(t=(3, 4, 0)))
    nested = _PlacedOccurrence("Root:1+Dest:1", dest, native, "NESTED-DEST")
    source.occurrences._items[:] = [nested]
    source.allOccurrences[:] = [nested]
    state["context"] = nested
    monkeypatch.setattr(mod._DESTINATION, "resolve", lambda raw: (nested, None))
    with pytest.raises(RuntimeError, match="top-level parent is the root component"):
        _ = nested.nativeObject.entityToken
    assert dest.entityToken == "DEST"

    result = _data(mod.handler(action="move", body="OLD", destination="Root:1+Dest:1"))

    assert state["called"] == 1 and selected not in source.bRepBodies._items
    assert result["full_path"] == "Root:1+Dest:1"
    assert result["landed_owner_component"] == "Dest"
    assert result["definition_effect"]["destination_placements"]["paths"] == ["Root:1+Dest:1"]
    assert result["selected_world_sample_preserved"] is True


def test_move_uses_saved_identity_when_old_wrapper_stales(scene):
    state, source, dest, target, selected = scene
    organize = selected._organization

    def stale(action, destination):
        result = organize(action, destination)
        del selected.entityToken
        return result

    selected._organization = stale
    result = _data(mod.handler(action="move", body="OLD", destination="Dest:1"))
    assert result["source_membership_after"] == 1
    assert result["source_retained"] is False


def test_create_component_requires_new_direct_child(scene, monkeypatch):
    state, source, dest, target, selected = scene
    result = _data(mod.handler(action="create_component", body="OLD"))
    assert result["owner_component"] == "Child" and result["full_path"] == "Child:1"
    assert result["handle"] == body_proxy(state["result"], state["context"]).entityToken
    assert selected not in source.bRepBodies._items


def test_create_component_accepts_nested_context_with_unreadable_native_occurrence_token(scene, monkeypatch):
    state, source, dest, target, selected = scene
    sibling = _NativeOccurrenceWithoutToken("SiblingChild:1", component=dest,
                                            transform2=FakeMatrix3D())
    source.occurrences._items.append(sibling)
    source.allOccurrences.append(sibling)

    def resolve(raw):
        if raw == "OLD":
            return selected, None
        if state["result"] is not None:
            minted = body_proxy(state["result"], state["context"])
            if raw == minted.entityToken:
                child = state["result"].parentComponent
                native = _NativeOccurrenceWithoutToken("Child:1", component=child)
                context = _PlacedOccurrence("Child:1", child, native, "PLACEDCHILD")
                return body_proxy(state["result"], context, entity_token=raw), None
        return None, "unknown body handle"

    monkeypatch.setattr(mod._BODY, "resolve", resolve)
    result = _data(mod.handler(action="create_component", body="OLD"))
    assert result["full_path"] == "Child:1"
    assert result["handle"] == body_proxy(state["result"], state["context"]).entityToken
    assert state["called"] == 1


def test_wrong_resolved_context_is_partial_error(scene):
    state, source, dest, target, selected = scene
    state["context"] = None
    result = mod.handler(action="copy", body="OLD", destination="Dest:1")
    assert result["isError"] is True and state["called"] == 1
    assert "Fresh result handle did not resolve" in result["message"]
    assert "landed_native_token" in result["message"]


def test_repeated_child_wrong_parent_path_is_rejected(scene, monkeypatch):
    state, source, dest, target, selected = scene
    native = _NativeOccurrenceWithoutToken("Dest:2", component=dest)
    wrong = _PlacedOccurrence("Dest:2", dest, native, "OCCDEST")

    def resolve(raw):
        if raw == "OLD":
            return selected, None
        if state["result"] is not None:
            return body_proxy(state["result"], wrong), None
        return None, "unknown body handle"

    monkeypatch.setattr(mod._BODY, "resolve", resolve)
    result = mod.handler(action="copy", body="OLD", destination="Dest:1")
    assert result["isError"] is True and state["called"] == 1
    assert "Fresh result handle did not resolve in the intended context" in result["message"]


def test_missing_destination_refuses_before_mutation(scene):
    state, source, dest, target, selected = scene
    result = mod.handler(action="move", body="OLD")
    assert result["isError"] is True and state["called"] == 0
    assert "requires explicit 'destination'" in result["message"]


def test_native_no_effect_returns_error_with_scoped_counts(scene):
    state, source, dest, target, selected = scene
    selected._organization = lambda action, destination: selected
    result = mod.handler(action="copy", body="OLD", destination="Dest:1")
    assert result["isError"] is True
    assert "Scoped source/destination membership" in result["message"]
    assert '"source_membership_after": 2' in result["message"]
    assert '"destination_membership_after": 1' in result["message"]


def test_native_raise_reports_possible_partial_effect(scene):
    state, source, dest, target, selected = scene

    def raised(action, destination):
        dest.bRepBodies._items.append(_body("Stray", "STRAY", dest))
        raise RuntimeError("native failure after add")

    selected._organization = raised
    result = mod.handler(action="copy", body="OLD", destination="Dest:1")
    assert result["isError"] is True and "native failure after add" in result["message"]
    assert '"destination_membership_after": 2' in result["message"]


def test_world_sample_is_order_invariant_beyond_cap():
    points = [FakePoint(0, 0, 0)] + [FakePoint(float(i), float(i % 3), 0.0)
                                     for i in range(40)]
    box = make_bbox((0, 0, 0), (39, 2, 0))
    first = BRepBody("First", bbox=box, volume=5.0, area=12.0, vertices=points)
    reordered = BRepBody("Second", bbox=box, volume=5.0, area=12.0,
                         vertices=list(reversed(points)))
    before = mod._shape(first, "brep")
    after = mod._shape(reordered, "brep")
    assert before["sample_truncated"] is True and after["sample_truncated"] is True
    assert mod._same_shape(before, after) is True
    moved = [FakePoint(p.x + 0.01 if p.x == 0 else p.x, p.y, p.z) for p in points]
    changed = BRepBody("Changed", bbox=box, volume=5.0, area=12.0, vertices=moved)
    assert mod._same_shape(before, mod._shape(changed, "brep")) is False


def test_world_sample_near_tie_reorders_within_tolerance():
    box = make_bbox((0, 0, 0), (1, 10, 0))
    before = BRepBody("Before", bbox=box, volume=1, area=2,
                      vertices=[FakePoint(0, 0, 0), FakePoint(0.0000005, 10, 0)])
    after = BRepBody("After", bbox=box, volume=1, area=2,
                     vertices=[FakePoint(0.0000005, 0, 0), FakePoint(0, 10, 0)])
    assert mod._same_shape(mod._shape(before, "brep"), mod._shape(after, "brep")) is True


def test_direct_mesh_refuses_nonidentity_sibling_placement_before_native_call(monkeypatch):
    root = MakeComp("Root", mesh_bodies=[], entity_token="ROOT")
    owner = MakeComp("Landing", mesh_bodies=[], entity_token="LANDING")
    chosen = FakeOccurrence("Landing:1", component=owner, entity_token="FIRST",
                            transform2=FakeMatrix3D())
    translated = FakeOccurrence("Landing:2", component=owner, entity_token="SECOND",
                                transform2=FakeMatrix3D(t=(11, 4, 1.5)))
    root.occurrences._items.extend((chosen, translated))
    root.allOccurrences.extend((chosen, translated))
    install(mod, MakeDesign(comp=root, all_components=[root, owner], design_type=0))
    monkeypatch.setattr(adsk.fusion, "BRepBody", BRepBody)
    monkeypatch.setattr(adsk.fusion, "MeshBody", MeshBody)
    monkeypatch.setattr(adsk.core.Point3D, "create", FakePoint)
    native = MeshBody("OrgMesh", tri=1, nodes=3, volume=0, area=0.5,
                      bbox=make_bbox((0, 0, 0), (1, 1, 0)), token="MOLD", parent=owner,
                      display_points=[FakePoint(0, 0, 0), FakePoint(1, 0, 0), FakePoint(0, 1, 0)],
                      display_indices=[0, 1, 2])
    owner.meshBodies._items.append(native)
    selected = native.createForAssemblyContext(chosen)
    monkeypatch.setattr(mod._BODY, "resolve", lambda raw: (selected, None))
    calls = []
    native._organization = lambda action, destination: calls.append(action)

    result = mod.handler(action="create_component", body="Landing:1:OrgMesh")
    assert result["isError"] is True and calls == []
    assert "'Landing:1'" in result["message"] and "component 'Landing'" in result["message"]
    assert "1 of 2 source placements" in result["message"]
    assert "Landing:2" in result["message"] and "identity-placed component" in result["message"]
    assert owner.meshBodies.count == 1 and owner.occurrences.count == 0
    monkeypatch.setattr(mod._inputs, "current_design_type", lambda design: "unknown")
    unknown = mod.handler(action="create_component", body="Landing:1:OrgMesh")
    assert unknown["isError"] is True and calls == []
    assert "design mode 'unknown'" in unknown["message"]


def test_mesh_area_drift_is_relative_without_loosening_world_nodes():
    before = {"vertex_total": 3, "vertices_cm": [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
              "bounds_cm": ((0, 0, 0), (1, 1, 0)), "volume_cm3": 0.6719999835491182,
              "area_cm2": 4.719999366187634}
    measured = {**before, "area_cm2": 4.71999786337443}
    assert mod._same_shape(before, measured, "mesh") is True
    assert mod._same_shape(before, measured, "brep") is False
    assert mod._same_shape(before, {**measured, "area_cm2": 4.71998}, "mesh") is False
    moved = {**measured, "vertices_cm": [(0.01, 0, 0), (1, 0, 0), (0, 1, 0)]}
    assert mod._same_shape(before, moved, "mesh") is False


def test_vertex_free_brep_uses_precise_bounds_over_rotated_coarse_box():
    tight = make_bbox((3.4, 1.4, 0.4), (4.6, 2.6, 1.6))
    loose = make_bbox((3.18038, 1.18038, 0.4), (4.81962, 2.81962, 1.6))
    before = BRepBody("Sphere", bbox=tight, precise_bbox=tight,
                      volume=0.9047786842338607, area=4.523893421169303)
    after = BRepBody("Sphere", bbox=loose, precise_bbox=tight,
                     volume=before.volume, area=before.area)
    altered = BRepBody("Sphere", bbox=loose,
                       precise_bbox=make_bbox((3.5, 1.4, 0.4), (4.7, 2.6, 1.6)),
                       volume=before.volume, area=before.area)
    first, same, changed = (mod._shape(body, "brep") for body in (before, after, altered))
    assert first["method"] == "world_bounds" and first["vertex_total"] == 0
    assert mod._same_shape(first, same, "brep") is True
    assert mod._same_shape(first, changed, "brep") is False


def test_mesh_copy_returns_intended_proxy_after_local_node_lift(monkeypatch):
    source = MakeComp("Root", mesh_bodies=[], entity_token="MROOT")
    dest = MakeComp("Dest", mesh_bodies=[], entity_token="MOWNER")
    target = FakeOccurrence("Dest:1", component=dest, entity_token="MDEST",
                            transform2=FakeMatrix3D(t=(3, 4, 0)))
    source.occurrences._items.append(target)
    source.allOccurrences.append(target)
    install(mod, MakeDesign(comp=source, all_components=[source, dest]))
    monkeypatch.setattr(adsk.fusion, "BRepBody", BRepBody)
    monkeypatch.setattr(adsk.fusion, "MeshBody", MeshBody)
    monkeypatch.setattr(adsk.core.Point3D, "create", FakePoint)
    source_points = [FakePoint(0, 0, 0), FakePoint(1, 0, 0), FakePoint(0, 1, 0)]
    dest_points = [FakePoint(-3, -4, 0), FakePoint(-2, -4, 0), FakePoint(-3, -3, 0)]
    selected = MeshBody("Picked", tri=1, nodes=3, volume=0, area=0.5,
                        bbox=make_bbox((0, 0, 0), (1, 1, 0)), token="MOLD", parent=source,
                        display_points=source_points, display_indices=[0, 1, 2])
    source.meshBodies._items.append(selected)
    state = {"new": None, "calls": 0}

    def copy(destination):
        state["calls"] += 1
        new = MeshBody("Picked", tri=1, nodes=3, volume=0, area=0.5,
                       bbox=make_bbox((-3, -4, 0), (-2, -3, 0)), token="MNEW", parent=dest,
                       display_points=dest_points, display_indices=[0, 1, 2])
        dest.meshBodies._items.append(new)
        state["new"] = new
        return new

    selected._organization = lambda action, destination: copy(destination)
    monkeypatch.setattr(mod._BODY, "resolve", lambda raw: (
        (selected, None) if raw == "MOLD" else
        (state["new"].createForAssemblyContext(target), None)
        if state["new"] is not None and raw == state["new"].createForAssemblyContext(target).entityToken
        else (None, "unknown mesh handle")))
    monkeypatch.setattr(mod._DESTINATION, "resolve", lambda raw: (target, None))
    repeated = FakeOccurrence("Dest:2", component=dest, entity_token="MDEST2",
                              transform2=FakeMatrix3D(t=(8, 9, 0)))
    source.occurrences._items.append(repeated)
    source.allOccurrences.append(repeated)
    refused = mod.handler(action="copy", body="MOLD", destination="Dest:1")
    assert refused["isError"] is True and state["calls"] == 0 and state["new"] is None
    assert "component 'Dest' has 2 placements ['Dest:1', 'Dest:2']" in refused["message"]
    assert "singly placed destination" in refused["message"]
    assert len(source.meshBodies._items) == 1 and len(dest.meshBodies._items) == 0
    source.occurrences._items.remove(repeated)
    source.allOccurrences.remove(repeated)
    data = _data(mod.handler(action="copy", body="MOLD", destination="Dest:1"))
    assert state["calls"] == 1
    assert data["body_kind"] == "mesh" and data["full_path"] == "Dest:1"
    assert data["handle"] == state["new"].createForAssemblyContext(target).entityToken
    assert data["selected_world_sample_preserved"] is True


def test_changed_destination_placement_is_partial_error(scene):
    state, source, dest, target, selected = scene
    organize = selected._organization

    def changed(action, destination):
        result = organize(action, destination)
        target.transform2 = FakeMatrix3D(t=(4, 4, 0))
        return result

    selected._organization = changed
    result = mod.handler(action="copy", body="OLD", destination="Dest:1")
    assert result["isError"] is True and state["called"] == 1
    assert "occurrence placement changed" in result["message"]


@pytest.fixture
def merge_pair(monkeypatch):
    monkeypatch.setattr(adsk.fusion, "BRepFace", BRepFace)
    root = MakeComp(name="Root", entity_token="Root")
    body = BRepBody("Cube", bbox=make_bbox((4, 0, 0), (6, 2, 2)), area=24, volume=8,
                    entity_token="cube", face_count=7, parent_component=root)
    edge = BRepEdge(Line3D(), entity_token="shared")
    faces = [BRepFace(Plane(FakeVector3D(0, 0, 1), FakePoint(4, 0, 2)),
                      entity_token=f"face{i}", body=body, edges=[edge]) for i in range(2)]
    state = SimpleNamespace(returned=True, drop=1, volume_delta=0, calls=[])

    def create(selected, chain):
        state.calls.append((selected, chain))
        return selected

    def add(_input):
        for _ in range(state.drop):
            body.faces._items.pop()
        body.volume += state.volume_delta
        return state.returned

    root.features = SimpleNamespace(mergeFacesFeatures=SimpleNamespace(createInput=create, add=add))
    design = MakeDesign(comp=root, tokens={"f0": faces[0], "f1": faces[1]}, design_type=0)
    install(mod, design)
    return body, faces, state, design


def test_merge_faces_returns_body_and_preserves_material(merge_pair):
    body, faces, state, _design = merge_pair
    result = payload(mod.handler(action="merge_faces", faces=["f0", "f1"]))
    assert state.calls == [(faces, False)]
    assert (result["faces_before"], result["faces_after"], result["handle"]) == (7, 6, "cube")
    assert result["material_kept"] is True and result["bounds_cm"] == [[4, 0, 0], [6, 2, 2]]


@pytest.mark.parametrize("returned,drop,volume", [(False, 1, 0), (True, 0, 0), (True, 1, .1)])
def test_merge_faces_false_return_no_effect_or_material_change_is_error(merge_pair, returned, drop, volume):
    _body, _faces, state, _design = merge_pair
    state.returned, state.drop, state.volume_delta = returned, drop, volume
    result = mod.handler(action="merge_faces", faces=["f0", "f1"])
    assert result["isError"] is True
    assert "faces 7 ->" in result["message"] and "recovery is manual" in result["message"]


def test_merge_faces_parametric_refusal_preserves_history(merge_pair):
    body, _faces, state, design = merge_pair
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    result = mod.handler(action="merge_faces", faces=["f0", "f1"])
    assert result["isError"] is True and "history is unchanged" in result["message"]
    assert state.calls == [] and body.faces.count == 7


@pytest.mark.parametrize("change,reason", [("other_body", "same solid"), ("plane", "different planes"),
                                           ("disconnect", "share no edge")])
def test_merge_faces_refuses_wrong_pair_before_write(merge_pair, change, reason):
    body, faces, state, _design = merge_pair
    if change == "other_body":
        faces[1].body = BRepBody(entity_token="other")
    elif change == "plane":
        faces[1].geometry = Plane(FakeVector3D(0, 0, 1), FakePoint(4, 0, 1))
    else:
        faces[1].edges._items.clear()
    result = mod.handler(action="merge_faces", faces=["f0", "f1"])
    assert result["isError"] is True and reason in result["message"]
    assert state.calls == [] and body.faces.count == 7
