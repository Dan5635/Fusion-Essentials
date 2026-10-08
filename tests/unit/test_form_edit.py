# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""form_edit and the cage handles it consumes: an edit judged by the cage re-read, a spent handle
refused, and a Form whose surface did not change said so."""

import types

import adsk.core
import pytest

from conftest import (BRepBody, FakeApplication, FakeFeatures, FakeFormFeature, FakeFormFeatures,
                      FakePoint, FakeTimeline, FakeTimelineObject, FakeTSplineBodies,
                      FakeTSplineBody, FakeUserInterface, MakeComp, MakeDesign, _NamedCollection,
                      error_message, install, load_tool, make_bbox, payload)

fe = load_tool("form_edit")
fg = load_tool("find_geometry")
fcommon = load_tool("_form_common")


def _list(items):
    return types.SimpleNamespace(count=len(items), item=lambda i: items[i])


class _Cage(FakeTSplineBody):
    """A T-spline body with a square cage face: four vertices, four edges, one face. `stuck`
    names vertex indices whose move answers True and changes nothing; `drift` is added to every
    move; `refuses` makes every move answer False."""

    def __init__(self, parent, stuck=(), drift=0.0, refuses=False):
        super().__init__("Body1", "", parent)
        self.stuck, self.drift, self.refuses = set(stuck), drift, refuses
        self.points = [FakePoint(x, y, 0.0) for x, y in ((0, 0), (2, 0), (2, 2), (0, 2))]
        cage = self

        def mover(indices):
            def move(vector):
                if cage.refuses:
                    return False
                for i in indices:
                    if i not in cage.stuck:
                        p = cage.points[i]
                        p.x, p.y, p.z = (p.x + vector[0] + cage.drift, p.y + vector[1],
                                         p.z + vector[2])
                return True
            return move
        verts = [types.SimpleNamespace(geometry=p, move=mover([i]))
                 for i, p in enumerate(self.points)]
        self.vertices = _list(verts)
        self.edge_list = [types.SimpleNamespace(startVertex=verts[i], endVertex=verts[(i + 1) % 4],
                                                isCreased=False) for i in range(4)]
        self.edges = _list(self.edge_list)
        self.faces = _list([types.SimpleNamespace(vertices=verts, move=mover(range(4)))])

    def transform(self, matrix):
        return self.faces.item(0).move(matrix.translation)


@pytest.fixture
def rig(monkeypatch):
    """A parametric design whose root holds the finished Form 'Root/Form1' with a square cage."""
    root = MakeComp(name="Root")
    timeline = FakeTimeline([])
    root.features = FakeFeatures()
    root.features.formFeatures = FakeFormFeatures(component=root)
    design = MakeDesign(comp=root, design_type=1, timeline=timeline, all_components=[root])
    for mod in (fe, fg):
        install(mod, design)
    root.parentDesign = design
    ui = FakeUserInterface(active_workspace=types.SimpleNamespace(id="FusionSolidEnvironment"))
    monkeypatch.setattr(fe._common, "app", FakeApplication(active_product=design,
                                                           user_interface=ui))
    monkeypatch.setattr(fe._form_common, "_SETTLE_S", 0.0)
    monkeypatch.setattr(adsk.core, "Vector3D", types.SimpleNamespace(create=lambda *a: a),
                        raising=False)
    monkeypatch.setattr(adsk.core, "Matrix3D", types.SimpleNamespace(
        create=lambda: types.SimpleNamespace(translation=None)), raising=False)
    ff = FakeFormFeature("Form1", component=root)
    cage = _Cage(ff)
    ff.tSplineBodies = FakeTSplineBodies([cage], owner=ff)
    brep = BRepBody(name="Body1", bbox=make_bbox((0, 0, 0), (2, 2, 0)), volume=0.0,
                    face_count=1, area=4.0, is_solid=False)
    ff.bodies = _NamedCollection([brep])
    ff.timelineObject = FakeTimelineObject(name="Form1", index=0, entity=ff)
    root.features.formFeatures._forms.append(ff)
    timeline._items.append(ff.timelineObject)
    return types.SimpleNamespace(ff=ff, cage=cage, brep=brep, design=design, root=root)


def _handles(kind, **kw):
    out = payload(fg.handler(kind=kind, **kw))
    return [m["handle"] for m in out["matches"]], out


class TestCageHandles:
    def test_find_geometry_lists_the_cage_by_native_index_in_the_callers_units(self, rig):
        handles, out = _handles("form_vertex", units="mm")
        assert out["target"] == "Root/Form1" and out["match_count"] == 4
        assert [m["index"] for m in out["matches"]] == [0, 1, 2, 3]
        assert out["matches"][2]["position"] == [20.0, 20.0, 0.0]
        assert handles[2].startswith("Root/Form1|@form_vertex:2;tb=Body1;cage=" + out["revision"])

    def test_an_edge_reads_its_middle_and_crease_and_a_face_its_centroid(self, rig):
        _h, edges = _handles("form_edge")
        assert edges["matches"][0]["position"] == [10.0, 0.0, 0.0]
        assert edges["matches"][0]["creased"] is False
        _h, faces = _handles("form_face", nearest_to=[0, 0, 0])
        assert faces["matches"][0]["position"] == [10.0, 10.0, 0.0]
        assert faces["matches"][0]["vertex_count"] == 4

    def test_two_forms_need_the_name_and_stray_inputs_are_refused(self, rig):
        other = FakeFormFeature("Form2", component=rig.root)
        rig.root.features.formFeatures._forms.append(other)
        assert "holds 2 - name it" in error_message(fg.handler(kind="form_vertex"))
        assert "drop target" in error_message(fg.handler(kind="form_vertex", target="Root",
                                                         name="Root/Form1"))

    def test_a_form_outside_the_root_or_with_two_bodies_is_refused(self, rig):
        rig.ff.tSplineBodies = FakeTSplineBodies([rig.cage, _Cage(rig.ff)], owner=rig.ff)
        assert "holds 2 T-spline bodies" in error_message(fg.handler(kind="form_vertex"))


class TestFormEdit:
    def test_a_vertex_move_lands_and_reports_the_cage_on_both_sides(self, rig):
        handles, _out = _handles("form_vertex")
        out = payload(fe.handler(body="Root/Form1", action="move", entities=[handles[2]],
                                 translation=[5, 0, 0]))
        assert (rig.cage.points[2].x, rig.cage.points[1].x) == (2.5, 2.0)
        assert out["edited"] is True and out["moved_vertices"] == 1
        assert out["cage_before"]["revision"] != out["cage_after"]["revision"]
        assert rig.ff._starts == rig.ff._finishes == 1

    def test_a_vertex_that_reads_elsewhere_than_asked_is_an_error(self, rig):
        rig.cage.drift = 0.01
        handles, _out = _handles("form_vertex")
        msg = error_message(fe.handler(body="Root/Form1", action="move", entities=[handles[2]],
                                       translation=[5, 0, 0]))
        assert "do not read where the translation puts them" in msg
        assert "find_geometry reads it as it is now" in msg and rig.ff._finishes == 1

    def test_a_move_that_answers_true_and_moves_nothing_is_an_error(self, rig):
        rig.cage.stuck = {2}
        handles, _out = _handles("form_vertex")
        msg = error_message(fe.handler(body="Root/Form1", action="move", entities=[handles[2]],
                                       translation=[5, 0, 0]))
        assert "not edited as asked" in msg and "reads as it did before" in msg

    def test_a_refused_native_move_is_named(self, rig):
        rig.cage.refuses = True
        handles, _out = _handles("form_vertex")
        msg = error_message(fe.handler(body="Root/Form1", action="move", entities=[handles[2]],
                                       translation=[5, 0, 0]))
        assert "did not confirm form_vertex 2" in msg

    def test_a_handle_from_an_earlier_cage_is_refused_before_the_edit_opens(self, rig):
        handles, _out = _handles("form_vertex")
        rig.cage.points[0].x = 0.4
        msg = error_message(fe.handler(body="Root/Form1", action="move", entities=[handles[2]],
                                       translation=[5, 0, 0]))
        assert "read from an earlier cage" in msg and rig.ff._starts == 0

    def test_a_whole_body_move_shifts_every_vertex(self, rig):
        out = payload(fe.handler(body="Root/Form1", action="move", translation=[0, 0, 10]))
        assert [p.z for p in rig.cage.points] == [1.0] * 4 and out["moved_vertices"] == 4

    def test_a_face_move_is_judged_on_that_faces_own_vertices(self, rig):
        handles, _out = _handles("form_face")
        out = payload(fe.handler(body="Root/Form1", action="move", entities=handles,
                                 translation=[0, 10, 0]))
        assert out["moved_vertices"] == 4 and rig.cage.points[0].y == 1.0

    def test_a_crease_is_set_read_back_and_leaves_the_vertices_alone(self, rig):
        handles, _out = _handles("form_edge")
        out = payload(fe.handler(body="Root/Form1", action="crease", entities=handles[:2],
                                 creased=True))
        assert [e.isCreased for e in rig.cage.edge_list] == [True, True, False, False]
        assert out["cage_after"]["creased_edges"] == 2 and out["moved_vertices"] == 0

    def test_a_surface_that_reads_the_same_afterwards_is_said_not_claimed_changed(self, rig):
        handles, _out = _handles("form_vertex")
        out = payload(fe.handler(body="Root/Form1", action="move", entities=[handles[2]],
                                 translation=[5, 0, 0]))
        assert out["changed"] is False and "reads the same as before" in out["note"]

    def test_a_changed_brep_is_reported_changed(self, rig):
        rig.ff._on_finish = lambda ff: setattr(rig.brep, "area", 5.0)
        handles, _out = _handles("form_vertex")
        out = payload(fe.handler(body="Root/Form1", action="move", entities=[handles[2]],
                                 translation=[5, 0, 0]))
        assert out["changed"] is True and out["brep_after"]["area_cm2"] == 5.0

    def test_an_edit_that_does_not_close_is_an_error_naming_the_state(self, rig):
        rig.ff._finish_ok = False
        msg = error_message(fe.handler(body="Root/Form1", action="move", translation=[0, 0, 10]))
        assert "did not confirm closed (unconfirmed" in msg

    def test_an_edit_that_does_not_open_changes_nothing(self, rig):
        rig.ff._start_ok = False
        msg = error_message(fe.handler(body="Root/Form1", action="move", translation=[0, 0, 10]))
        assert "did not open" in msg and rig.cage.points[0].z == 0.0

    @pytest.mark.parametrize("kw,said", [
        ({"action": "move"}, "takes 'translation' as three numbers"),
        ({"action": "move", "translation": [0, 0, 0]}, "not all zero"),
        ({"action": "move", "translation": [1, 0, 0], "creased": True}, "belongs to action='crease'"),
        ({"action": "crease", "creased": True}, "takes 'entities'"),
        ({"action": "move", "translation": [1, 0, 0], "entities": []}, "list of cage handles"),
        ({"action": "move", "translation": [1, 0, 0], "entities": ["Root/Form1"]},
         "is not a Form cage handle"),
        ({"action": "rotate"}, "rotate")])
    def test_a_malformed_request_is_refused_before_the_edit_opens(self, rig, kw, said):
        assert said in error_message(fe.handler(body="Root/Form1", **kw))
        assert rig.ff._starts == 0

    def test_the_wrong_kind_for_the_action_is_refused(self, rig):
        edges, _o = _handles("form_edge")
        verts, _o = _handles("form_vertex")
        faces, _o = _handles("form_face")
        assert "an edge is not moved" in error_message(fe.handler(
            body="Root/Form1", action="move", entities=[edges[0]], translation=[1, 0, 0]))
        assert "form_edge handles only" in error_message(fe.handler(
            body="Root/Form1", action="crease", entities=[verts[0]], creased=True))
        assert "one kind per call" in error_message(fe.handler(
            body="Root/Form1", action="move", entities=[verts[0], faces[0]],
            translation=[1, 0, 0]))
        assert "repeats form_vertex 0" in error_message(fe.handler(
            body="Root/Form1", action="move", entities=[verts[0], verts[0]],
            translation=[1, 0, 0]))
        assert rig.ff._starts == 0

    def test_a_direct_design_is_refused(self, rig):
        rig.design.designType = 0
        assert "needs parametric mode" in error_message(fe.handler(
            body="Root/Form1", action="move", translation=[1, 0, 0]))

    def test_the_creation_record_follows_the_edit(self, rig):
        fcommon.store_record(rig.ff, {"cage_hash": "x", "brep_faces": 1, "volume_cm3": None,
                                      "area_cm2": 4.0, "primitive": {"shape": "plane"}})
        rig.ff._on_finish = lambda ff: setattr(rig.brep, "area", 5.0)
        payload(fe.handler(body="Root/Form1", action="move", translation=[0, 0, 10]))
        record = fcommon.read_record(rig.ff)
        assert record["area_cm2"] == 5.0 and record["edited_by"] == "form_edit"
        assert "primitive" not in record
