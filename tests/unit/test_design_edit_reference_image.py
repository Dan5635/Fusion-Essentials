# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""design_edit_reference_image: a placement judged by the transform read back, a delete judged by
the count, a stale ref refused, and the row design_get publishes for both kinds."""

import struct
import types

import adsk.core
import pytest

from conftest import MakeComp, error_message, install, load_tool, make_design, payload

ri = load_tool("design_edit_reference_image")
img = load_tool("_image_common")

# The transform Fusion gives a 64 x 32 px canvas on a plane, and the same image as a decal (measured).
_CANVAS = [1.75, 0.0, -0.875, 0.0, 0.875, -0.4375, 0.0, 0.0, 1.0]
_DECAL = [1.75, 0.0, 0.0, 2.0, 0.0, 0.875, 0.0, 1.5, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0]


class _Matrix:
    def __init__(self, cells=None):
        self.cells = list(cells or [])

    def setWithArray(self, cells):
        self.cells = list(cells)
        return True

    def asArray(self):
        return list(self.cells)


class _Picture:
    """A canvas or decal: its transform assignment may `drift`, its opacity may be `sticky`, and
    deleteMe answers `delete` (a string raises) while `stays` keeps it in the collection."""

    def __init__(self, owner, name, cells, kind):
        self.owner, self.name, self.kind = owner, name, kind
        self._transform = _Matrix(cells)
        self.opacity = 50 if kind == "canvas" else 1.0
        self.isDisplayedThrough, self.isChainFaces, self.isDerived = True, True, False
        self.imageFilename, self.planarEntity = owner.image, owner.plane
        self.faces = [owner.face]
        self.timelineObject = types.SimpleNamespace(index=0, rollTo=owner.roll)
        self.drift, self.sticky, self.delete, self.stays = 0.0, False, True, False
        self.loses_faces = False
        self.redefined = None

    transform = property(
        lambda self: self._transform,
        lambda self, m: setattr(self, "_transform", _Matrix([c + self.drift for c in m.cells])))

    def __setattr__(self, key, value):
        if key == "opacity" and getattr(self, "kind", None) == "canvas" and type(value) is not int:
            raise TypeError("Canvas__set_opacity argument 2 of type 'int'")
        if key == "opacity" and getattr(self, "sticky", False):
            return
        if key == "opacity" and getattr(self, "kind", None) == "decal":
            value = struct.unpack("f", struct.pack("f", value))[0]      # held in single precision
        object.__setattr__(self, key, value)

    def redefine(self, matrix, faces, chain):
        self.redefined = (list(matrix.cells), list(faces), chain)
        self._transform, self.isChainFaces = _Matrix(matrix.cells), chain
        self.faces = [] if self.loses_faces else list(faces)
        return True

    def deleteMe(self):
        if isinstance(self.delete, str):
            if not self.stays:
                self.owner.items.remove(self)
            raise RuntimeError(self.delete)
        if self.delete and not self.stays:
            self.owner.items.remove(self)
        return self.delete


class _Shelf:
    """root.canvases or root.decals: createInput hands back the file's default transform."""

    def __init__(self, kind, design):
        self.kind, self.design, self.items, self.inputs = kind, design, [], []
        self.image, self.plane, self.face = "C:/img/fixture.png", None, None
        self.rolled, self.ignores_input, self.first_face_only = [], False, False

    count = property(lambda self: len(self.items))

    def roll(self, before):
        self.rolled.append(self.design.timeline.markerPosition)
        self.design.timeline.markerPosition = 0
        return True

    def item(self, i):
        return self.items[i]

    def itemByName(self, name):
        return next((e for e in self.items if e.name == name), None)

    def createInput(self, *args):
        fresh = types.SimpleNamespace(args=args, opacity=None, isChainFaces=True,
                                      transform=_Matrix(_CANVAS if self.kind == "canvas" else _DECAL))
        self.inputs.append(fresh)
        return fresh

    def add(self, fresh):
        cells = (_CANVAS if self.kind == "canvas" else _DECAL) if self.ignores_input \
            else fresh.transform.cells
        made = _Picture(self, "fixture", cells, self.kind)
        if self.kind == "decal" and not self.ignores_input:
            made.faces = list(fresh.args[1])[:1 if self.first_face_only else None]
        made.isChainFaces = fresh.isChainFaces
        self.items.append(made)
        return made


@pytest.fixture
def rig(monkeypatch):
    """A parametric design whose root owns one plane, one face and empty image collections."""
    root = MakeComp(name="Root")
    design = make_design(comp=root, design_type=1)
    install(ri, design)
    design.timeline = types.SimpleNamespace(markerPosition=7)
    plane = types.SimpleNamespace(parentComponent=design.rootComponent, assemblyContext=None)
    normal = types.SimpleNamespace(x=0.0, y=0.0, z=1.0)
    def make_face(token):
        return types.SimpleNamespace(
            entityToken=token, assemblyContext=None,
            body=types.SimpleNamespace(parentComponent=design.rootComponent),
            evaluator=types.SimpleNamespace(getNormalAtPoint=lambda p: (True, normal)))
    face, other_face = make_face("face-top"), make_face("face-side")
    for kind in ("canvas", "decal"):
        images = _Shelf(kind, design)
        images.plane, images.face = plane, face
        setattr(design.rootComponent, img.KINDS[kind], images)
    monkeypatch.setattr(ri._PLANE, "resolve", lambda raw: (plane, None))
    monkeypatch.setattr(ri._FACES, "resolve", lambda raw: ([face], None))
    monkeypatch.setattr(ri.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(img.os.path, "isfile", lambda p: True)
    for name in ("Matrix2D", "Matrix3D"):
        monkeypatch.setattr(adsk.core, name, types.SimpleNamespace(create=_Matrix), raising=False)
    monkeypatch.setattr(adsk.core, "Point3D", types.SimpleNamespace(create=lambda *a: a),
                        raising=False)
    return types.SimpleNamespace(design=design, canvases=design.rootComponent.canvases,
                                 decals=design.rootComponent.decals, plane=plane, face=face,
                                 other_face=other_face)


def _canvas(rig, **kw):
    out = payload(ri.handler(action="create", kind="canvas", image="C:/img/fixture.png",
                             plane="xy", **kw))
    return rig.canvases.items[-1], out


def _decal(rig, **kw):
    out = payload(ri.handler(action="create", kind="decal", image="C:/img/fixture.png",
                             faces=["f"], origin=[20, 15, 10], **kw))
    return rig.decals.items[-1], out


class TestCanvas:
    def test_a_create_adds_one_canvas_and_hands_back_its_ref_and_row(self, rig):
        canvas, out = _canvas(rig, opacity=80, display_through=False)
        assert rig.canvases.inputs[0].args == ("C:/img/fixture.png", rig.plane)
        assert (canvas.opacity, canvas.isDisplayedThrough) == (80, False)
        assert type(canvas.opacity) is int
        assert out["reference"] == "canvas:0:fixture" and out["before"] is None
        assert out["after"]["size"] == [17.5, 8.75] and out["after"]["position"] == [0.0, 0.0]

    def test_a_place_moves_the_centre_scales_from_the_original_and_turns(self, rig):
        canvas, _out = _canvas(rig)
        out = payload(ri.handler(action="place", kind="canvas", reference="canvas:0:fixture",
                                 position=[10, 20], scale=[2, 2], rotation_deg=90))
        after = out["after"]
        assert after["position"] == [10.0, 20.0] and after["size"] == [35.0, 17.5]
        assert after["rotation_deg"] == 90.0 and after["mirrored"] is False
        # the X axis now points along +v, 3.5 cm long
        assert canvas.transform.cells[0] == pytest.approx(0.0, abs=1e-12)
        assert canvas.transform.cells[3] == pytest.approx(3.5)

    def test_a_second_scale_is_still_relative_to_the_original_not_to_the_last_one(self, rig):
        _canvas(rig)
        for _ in range(2):
            out = payload(ri.handler(action="place", kind="canvas", reference="canvas:0:fixture",
                                     scale=[2, 1]))
        assert out["after"]["size"] == [35.0, 8.75]

    def test_a_transform_that_reads_back_differently_is_an_error(self, rig):
        canvas, _out = _canvas(rig)
        canvas.drift = 0.01
        msg = error_message(ri.handler(action="place", kind="canvas",
                                       reference="canvas:0:fixture", position=[10, 20]))
        assert "does not read back as asked" in msg

    def test_a_horizontal_flip_mirrors_about_the_centre_as_the_native_flip_does(self, rig):
        canvas, _out = _canvas(rig)
        out = payload(ri.handler(action="place", kind="canvas", reference="canvas:0:fixture",
                                 flip_horizontal=True))
        assert canvas.transform.cells == pytest.approx(
            [-1.75, 0.0, 0.875, 0.0, 0.875, -0.4375, 0.0, 0.0, 1.0])
        assert out["after"]["mirrored"] is True and out["after"]["rotation_deg"] == 0.0

    def test_a_scale_is_refused_when_the_image_file_is_gone(self, rig, monkeypatch):
        canvas, _out = _canvas(rig)
        monkeypatch.setattr(img.os.path, "isfile", lambda p: False)
        msg = error_message(ri.handler(action="place", kind="canvas",
                                       reference="canvas:0:fixture", scale=[2, 2]))
        assert "is not at 'C:/img/fixture.png'" in msg and canvas.transform.cells == _CANVAS

    def test_a_canvas_opacity_between_whole_numbers_is_refused_and_writes_nothing(self, rig):
        canvas, _out = _canvas(rig)
        msg = error_message(ri.handler(action="style", kind="canvas", reference="canvas:0:fixture",
                                       opacity=30.5, name="Renamed"))
        assert "whole number from 0 to 100 - got 30.5" in msg
        assert (canvas.opacity, canvas.name) == (50, "fixture")

    def test_an_opacity_that_does_not_stick_is_an_error(self, rig):
        canvas, _out = _canvas(rig)
        canvas.sticky = True
        msg = error_message(ri.handler(action="style", kind="canvas",
                                       reference="canvas:0:fixture", opacity=20))
        assert "opacity did not read back" in msg

    def test_a_rename_spends_the_old_ref_and_hands_back_the_new_one(self, rig):
        _canvas(rig)
        out = payload(ri.handler(action="style", kind="canvas", reference="canvas:0:fixture",
                                 name="Photo"))
        assert out["reference"] == "canvas:0:Photo" and out["before"]["name"] == "fixture"
        msg = error_message(ri.handler(action="style", kind="canvas",
                                       reference="canvas:0:fixture", opacity=20))
        assert "no longer names a root canvas" in msg

    @pytest.mark.parametrize("delete,stays,ok_", [(True, False, True), ("3 : Delete was unsuccessful.",
                                                                        False, True),
                                                  (True, True, False), (False, False, False)])
    def test_a_delete_is_judged_by_the_count_not_by_what_deleteme_says(self, rig, delete, stays,
                                                                       ok_):
        canvas, _out = _canvas(rig)
        canvas.delete, canvas.stays = delete, stays
        res = ri.handler(action="delete", kind="canvas", reference="canvas:0:fixture")
        assert res["isError"] is not ok_
        if ok_:
            out = payload(res)
            assert out["deleted"] is True and out["reference"] is None and out["after"] is None
            assert ("although deleteMe answered" in out["note"]) is isinstance(delete, str)
        else:
            assert "was not confirmed deleted" in res["message"]

    def test_a_plane_outside_the_root_is_refused_before_anything_is_added(self, rig):
        rig.plane.assemblyContext = object()
        msg = error_message(ri.handler(action="create", kind="canvas", image="a.png", plane="p"))
        assert "geometry of the root component itself" in msg and rig.canvases.count == 0

    def test_a_create_whose_placing_fails_removes_the_canvas_it_added(self, rig, monkeypatch):
        monkeypatch.setattr(ri, "_place_canvas", lambda *a: "the transform did not take")
        msg = error_message(ri.handler(action="create", kind="canvas", image="a.png", plane="p",
                                       position=[1, 1]))
        assert "was added but the transform did not take" in msg and "is gone" in msg
        assert rig.canvases.count == 0


class TestDecal:
    def test_a_create_passes_the_faces_and_the_origin_in_cm_and_scales_opacity(self, rig):
        decal, out = _decal(rig, opacity=40, chain_faces=False)
        assert rig.decals.inputs[0].args == ("C:/img/fixture.png", [rig.face], (2.0, 1.5, 1.0))
        assert decal.opacity == pytest.approx(0.4) and decal.opacity != 0.4
        assert decal.isChainFaces is False
        assert out["after"]["opacity"] == 40.0 and out["after"]["origin"] == [20.0, 15.0, 10.0]

    def test_a_place_rolls_before_the_decal_redefines_and_restores_the_marker(self, rig):
        decal, _out = _decal(rig)
        out = payload(ri.handler(action="place", kind="decal", reference="decal:0:fixture",
                                 origin=[10, 10, 10], scale=[0.5, 0.5],
                                 x_direction=[0, 2, 0]))
        cells, faces, chain = decal.redefined
        assert rig.decals.rolled == [7] and rig.design.timeline.markerPosition == 7
        assert (cells[3], cells[7], cells[11]) == (1.0, 1.0, 1.0) and chain is True
        assert (cells[0], cells[4]) == pytest.approx((0.0, 0.875))
        assert out["after"]["size"] == [8.75, 4.375] and out["after"]["x_direction"] == [0.0, 1.0, 0.0]

    def test_a_create_whose_decal_ignores_the_origin_asked_is_removed(self, rig):
        rig.decals.ignores_input = True
        msg = error_message(ri.handler(action="create", kind="decal", image="a.png",
                                       faces=["f"], origin=[40, 15, 10]))
        assert "origin, direction or size does not read back" in msg and rig.decals.count == 0

    def test_a_create_whose_decal_ignores_the_scale_asked_is_removed(self, rig):
        rig.decals.ignores_input = True
        msg = error_message(ri.handler(action="create", kind="decal", image="a.png",
                                       faces=["f"], origin=[20, 15, 10], scale=[2, 2]))
        assert "origin, direction or size does not read back" in msg and rig.decals.count == 0

    def test_several_faces_with_chaining_on_are_refused_before_anything_is_made(self, rig,
                                                                                monkeypatch):
        monkeypatch.setattr(ri._FACES, "resolve", lambda raw: ([rig.face, rig.other_face], None))
        msg = error_message(ri.handler(action="create", kind="decal", image="a.png",
                                       faces=["f", "g"], origin=[20, 15, 10]))
        assert "chain_faces=false" in msg and rig.decals.inputs == [] and rig.decals.count == 0

    def test_an_unchained_create_that_drops_a_face_asked_for_is_removed(self, rig, monkeypatch):
        rig.decals.first_face_only = True
        monkeypatch.setattr(ri._FACES, "resolve", lambda raw: ([rig.face, rig.other_face], None))
        msg = error_message(ri.handler(action="create", kind="decal", image="a.png",
                                       faces=["f", "g"], origin=[20, 15, 10], chain_faces=False))
        assert "does not read the faces asked for" in msg and rig.decals.count == 0

    def test_an_unchained_create_on_two_faces_that_lands_reads_both(self, rig, monkeypatch):
        monkeypatch.setattr(ri._FACES, "resolve", lambda raw: ([rig.face, rig.other_face], None))
        out = payload(ri.handler(action="create", kind="decal", image="a.png", faces=["f", "g"],
                                 origin=[20, 15, 10], chain_faces=False))
        assert out["after"]["face_count"] == 2

    def test_a_place_does_not_take_faces(self, rig):
        decal, _out = _decal(rig)
        msg = error_message(ri.handler(action="place", kind="decal", reference="decal:0:fixture",
                                       faces=["g"], origin=[10, 10, 10]))
        assert "Delete the decal and create it" in msg and decal.redefined is None

    def test_a_place_after_which_the_decal_lost_its_faces_is_an_error(self, rig):
        decal, _out = _decal(rig)
        decal.loses_faces = True
        msg = error_message(ri.handler(action="place", kind="decal", reference="decal:0:fixture",
                                       origin=[10, 10, 10]))
        assert "no longer reads the faces it had" in msg

    def test_a_decal_opacity_that_lands_a_whole_percent_off_is_an_error(self, rig):
        decal, _out = _decal(rig)
        object.__setattr__(decal, "sticky", True)
        msg = error_message(ri.handler(action="style", kind="decal", reference="decal:0:fixture",
                                       opacity=99))
        assert "opacity did not read back" in msg

    def test_a_direction_out_of_the_face_plane_is_refused_before_the_roll(self, rig):
        _decal(rig)
        msg = error_message(ri.handler(action="place", kind="decal", reference="decal:0:fixture",
                                       x_direction=[0, 0, 1]))
        assert "must lie in the first face's plane" in msg and rig.decals.rolled == []

    def test_a_marker_that_does_not_come_back_is_an_error(self, rig):
        _decal(rig)

        class _Stuck:
            """A timeline whose marker sits at 0 once something has rolled it there."""
            position = 7
            markerPosition = property(lambda self: self.position,
                                      lambda self, v: setattr(self, "position", min(v, self.position)))
        rig.design.timeline = _Stuck()
        msg = error_message(ri.handler(action="place", kind="decal",
                                       reference="decal:0:fixture", origin=[10, 10, 10]))
        assert "marker did not return to 7" in msg


class TestRequests:
    @pytest.mark.parametrize("kw,said", [
        ({"action": "create", "kind": "canvas", "image": "a.png"}, "missing plane"),
        ({"action": "create", "kind": "canvas", "image": "a.png", "plane": "p", "origin": [0, 0, 0]},
         "drop origin"),
        ({"action": "place", "kind": "canvas", "reference": "canvas:0:x"}, "needs one of position"),
        ({"action": "style", "kind": "decal", "reference": "decal:0:x", "display_through": True},
         "drop display_through"),
        ({"action": "delete", "kind": "canvas", "reference": "canvas:0:x", "opacity": 5},
         "drop opacity"),
        ({"action": "place", "kind": "canvas", "reference": "canvas:0:x", "scale": [0, 1]},
         "'scale' is 2 numbers above 0"),
        ({"action": "style", "kind": "canvas", "reference": "canvas:0:x", "opacity": 150},
         "from 0 to 100"),
        ({"action": "place", "kind": "canvas", "reference": "decal:0:x", "position": [0, 0]},
         "names a decal, and 'kind' says canvas"),
        ({"action": "place", "kind": "canvas", "reference": "Canvas1", "position": [0, 0]},
         "is an image ref from")])
    def test_a_request_that_does_not_fit_is_refused_naming_the_input(self, rig, kw, said):
        assert said in error_message(ri.handler(**kw))
        assert rig.canvases.count == rig.decals.count == 0

    def test_a_direct_design_is_refused(self, rig):
        rig.design.designType = 0
        assert "needs parametric mode" in error_message(ri.handler(
            action="create", kind="canvas", image="a.png", plane="p"))


class TestReferenceImagesSlice:
    def test_rows_list_canvases_then_decals_in_the_units_asked(self, rig):
        _canvas(rig)
        _decal(rig)
        out, err = img.slice_reference_images(rig.design, 0, "in")
        assert err is None and out["total"] == 2 and out["walk_complete"] is True
        canvas, decal = out["images"]
        assert canvas["ref"] == "canvas:0:fixture" and canvas["size"] == [0.688976, 0.344488]
        assert decal["ref"] == "decal:0:fixture" and decal["face_count"] == 1
        assert decal["opacity"] == 100.0 and canvas["opacity"] == 50.0

    def test_an_entry_that_does_not_read_withholds_the_total(self, rig):
        _canvas(rig)
        rig.canvases.item = lambda i: None
        out, _err = img.slice_reference_images(rig.design, 0, "mm")
        assert out["total"] is None and out["walk_complete"] is False
