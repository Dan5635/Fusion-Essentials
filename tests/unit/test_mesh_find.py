# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""mesh_find: rows in the caller's units and in distance order, stamped with a revision that moves
when the mesh does; refusals that name the input at fault."""

import types

import adsk.core
import adsk.fusion
import pytest

from conftest import (BRepBody, MakeComp, MeshBody, FakePoint, error_message, install, load_tool,
                      make_design, payload)

mf = load_tool("mesh_find")

# A tetrahedron in cm: nodes 0..3, four triangles.
_NODES = [0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 1.0]
_TRIS = [0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3]


class _Mesh(MeshBody):
    """A mesh body with a polygon mesh, face groups, a ray and a silhouette of its own."""
    polygon_mesh = None
    mesh = property(lambda self: self.polygon_mesh)
    hits, outlines, ray_args = (), (), None

    def calculateCollisionsWithRay(self, origin, direction):
        self.ray_args = (origin, direction)
        return [FakePoint(*p) for p in self.hits]

    def silhouette(self, plane):
        return [types.SimpleNamespace(points=[FakePoint(*p) for p in line])
                for line in self.outlines]


def _group(temp_id, centroid, area, planar=True):
    return types.SimpleNamespace(tempId=temp_id, centroid=FakePoint(*centroid), area=area,
                                 isPlanar=planar)


@pytest.fixture
def rig(monkeypatch):
    """A root-owned mesh 'Tetra' reachable by the handle 'm1'."""
    monkeypatch.setattr(adsk.fusion, "MeshBody", _Mesh, raising=False)
    monkeypatch.setattr(adsk.fusion, "BRepBody", BRepBody, raising=False)
    monkeypatch.setattr(adsk.core, "Point3D", types.SimpleNamespace(create=lambda *a: a),
                        raising=False)
    monkeypatch.setattr(adsk.core, "Vector3D", types.SimpleNamespace(create=lambda *a: a),
                        raising=False)
    mesh = _Mesh("Tetra")
    mesh.polygon_mesh = types.SimpleNamespace(nodeCoordinatesAsDouble=list(_NODES),
                                              triangleNodeIndices=list(_TRIS))
    groups = [_group(1, (1.0, 0.7, 0.0), 3.0), _group(2, (0.0, 0.7, 0.3), 1.0, planar=False)]
    mesh.faceGroups = types.SimpleNamespace(count=len(groups), item=lambda i: groups[i])
    comp = MakeComp(name="Root")
    design = make_design(comp=comp, tokens={"m1": mesh})
    install(mf, design)
    mesh.parentComponent = design.rootComponent
    return mesh


class TestMeshFind:
    def test_nodes_come_back_nearest_first_in_the_callers_units(self, rig):
        out = payload(mf.handler(body="m1", kind="node", nearest_to=[29, 0, 0]))
        assert [m["index"] for m in out["matches"]] == [1, 0, 3, 2]
        assert out["matches"][0]["position"] == [30.0, 0.0, 0.0]
        assert out["matches"][0]["distance"] == 1.0 and out["total"] == 4
        assert out["frame"] == "world" and out["truncated"] is False

    def test_a_cap_leaves_rows_out_and_says_so(self, rig):
        out = payload(mf.handler(body="m1", kind="node", max_results=2))
        assert [m["index"] for m in out["matches"]] == [0, 1]
        assert out["truncated"] is True and out["total"] == 4

    def test_triangles_carry_their_nodes_centroid_and_area(self, rig):
        out = payload(mf.handler(body="m1", kind="triangle", nearest_to=[10, 6.6, 0], units="mm"))
        first = out["matches"][0]
        assert first["index"] == 0 and first["nodes"] == [0, 2, 1]
        assert first["centroid"] == [10.0, 6.666667, 0.0] and first["area"] == 300.0

    def test_groups_carry_the_temp_id_the_mesh_publishes(self, rig):
        out = payload(mf.handler(body="m1", kind="group", nearest_to=[0, 7, 3]))
        assert [m["temp_id"] for m in out["matches"]] == [2, 1]
        assert out["matches"][0]["planar"] is False and out["matches"][1]["area"] == 300.0

    def test_ray_hits_keep_the_order_the_ray_meets_them_and_a_miss_is_said(self, rig):
        rig.hits = [(0.5, 0.5, 0.58), (0.5, 0.5, 0.0)]
        out = payload(mf.handler(body="m1", kind="ray", ray_origin=[5, 5, 50],
                                 ray_direction=[0, 0, -7]))
        # a direction of any length reaches Fusion as a unit vector
        assert rig.ray_args == ((0.5, 0.5, 5.0), (0.0, 0.0, -1.0))
        assert [m["position"][2] for m in out["matches"]] == [5.8, 0.0]
        assert out["matches"][0]["distance"] == 44.2
        rig.hits = []
        miss = payload(mf.handler(body="m1", kind="ray", ray_origin=[500, 5, 50],
                                  ray_direction=[0, 0, -1]))
        assert miss["matches"] == [] and miss["note"].startswith("The ray meets the mesh nowhere")

    def test_a_silhouette_outline_reads_its_point_count_closure_length_and_box(self, rig,
                                                                               monkeypatch):
        plane = types.SimpleNamespace(geometry=object())
        monkeypatch.setattr(mf._PLANE, "resolve", lambda raw: (plane, None))
        rig.outlines = [[(0, 0, 0), (3, 0, 0), (0, 2, 0), (0, 0, 0)]]
        out = payload(mf.handler(body="m1", kind="silhouette", plane="xy"))
        row = out["matches"][0]
        assert (row["point_count"], row["closed"]) == (4, True)
        assert row["length"] == pytest.approx(30 + 20 + 36.055513, abs=1e-5)
        assert row["min"] == [0.0, 0.0, 0.0] and row["max"] == [30.0, 20.0, 0.0]

    def test_the_revision_changes_when_a_node_moves_and_not_between_reads(self, rig):
        first = payload(mf.handler(body="m1", kind="node"))["revision"]
        assert payload(mf.handler(body="m1", kind="triangle"))["revision"] == first
        rig.polygon_mesh.nodeCoordinatesAsDouble[0] = 0.001
        assert payload(mf.handler(body="m1", kind="node"))["revision"] != first

    @pytest.mark.parametrize("kw,said", [
        ({"kind": "ray", "ray_origin": [0, 0, 0]}, "missing ray_direction"),
        ({"kind": "ray", "ray_origin": [0, 0, 0], "ray_direction": [0, 0, 0]}, "needs a direction"),
        ({"kind": "node", "ray_origin": [0, 0, 0]}, "drop ray_origin"),
        ({"kind": "silhouette"}, "missing plane"),
        ({"kind": "node", "nearest_to": [0, 0]}, "'nearest_to' is three finite numbers"),
        ({"kind": "node", "max_results": 0}, "from 1 to 100"),
        ({"kind": "edge"}, "edge")])
    def test_a_call_that_does_not_fit_its_kind_is_refused_naming_the_input(self, rig, kw, said):
        assert said in error_message(mf.handler(body="m1", **kw))

    def test_a_mesh_another_component_owns_is_refused(self, rig):
        rig.parentComponent = MakeComp(name="Rail")
        assert "reads owner 'Rail'" in error_message(mf.handler(body="m1", kind="node"))

    @pytest.mark.parametrize("coords,tris", [([0.0, 0.0], _TRIS), (_NODES, [0, 1, 9]),
                                             ([float("nan")] + _NODES[1:], _TRIS)])
    def test_a_mesh_whose_arrays_do_not_read_whole_is_an_error(self, rig, coords, tris):
        rig.polygon_mesh = types.SimpleNamespace(nodeCoordinatesAsDouble=coords,
                                                 triangleNodeIndices=tris)
        assert "did not read" in error_message(mf.handler(body="m1", kind="node"))

    def test_a_group_whose_centroid_does_not_read_is_an_error_not_a_row(self, rig):
        broken = types.SimpleNamespace(tempId=3, area=1.0, isPlanar=True)
        rig.faceGroups = types.SimpleNamespace(count=1, item=lambda i: broken)
        assert "Face group 0" in error_message(mf.handler(body="m1", kind="group"))
