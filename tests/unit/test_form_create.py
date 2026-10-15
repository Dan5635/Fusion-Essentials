# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""form_create: the crash guard before FormFeatures.add(), the always-finish lifecycle, and the
read-back checks that remove a Form Fusion did not build as asked."""

import os
import types

import adsk.core
import adsk.fusion
import pytest

from conftest import (BRepBody, BRepEdge, BRepFace, FakeApplication, FakeFeatures,
                      FakeFormFeature, FakeFormFeatures, FakePoint, FakeTimeline,
                      FakeTimelineObject, FakeTSplineBodies, FakeTSplineBody, FakeUserInterface,
                      FakeVector3D, MakeComp, MakeDesign, _NamedCollection, error_message, install,
                      load_tool, make_bbox, make_occurrence, payload)

fc = load_tool("form_create")
tsm = load_tool("_tsm")
_REAL_SEAMS = fc._continuity.body_seams

_BOX = {"shape": "box", "size": [20, 20, 20], "spans": [3, 3, 3]}
_TUBE = {"shape": "cylinder", "size": [20, 40], "spans": [4], "capped": False}
_FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "fixtures", "tsm")
# What finishEdit raised on the self-intersecting cage (measured).
_SELF_INTERSECTS = ("3 : Conversion error for: Body1 / ASM_TSP_BFTS_OUTPUT_BODY_SELF_INTERSECTS - "
                    "T-Spline surface self-intersects.")


def _converted(solid=True, lo=-0.9, hi=0.9, name=None, area=20.0):
    """The finish's conversion: one B-Rep body named `name`, else after the T-spline body."""
    def land(ff):
        if ff.tSplineBodies.count:
            tb = ff.tSplineBodies.item(0)
            ff.bodies = _NamedCollection([BRepBody(
                name=name or tb.name, bbox=make_bbox((lo, lo, lo), (hi, hi, hi)), volume=5.8,
                is_solid=solid, face_count=6, area=area)])
    return land


def _rim_cage():
    """The 20 mm box cage in mm with its 12 top-rim edges creased."""
    cage = tsm.box([20.0, 20.0, 20.0], [3, 3, 3])
    v = cage["vertices"]
    rim = set()
    for f in cage["faces"]:
        for k in range(4):
            a, b = f[k], f[(k + 1) % 4]
            if v[a][2] == v[b][2] == 10.0 and any(
                    abs(v[a][ax]) == abs(v[b][ax]) == 10.0 and v[a][ax] == v[b][ax]
                    for ax in (0, 1)):
                rim.add(tuple(sorted((a, b))))
    cage["creases"] = [list(e) for e in sorted(rim)]
    return cage


def _creased_back(text):
    """What Fusion writes back for a creased load: the header switched to SUBD_CREASES."""
    return text.replace("end-conditions MULTIPLE_KNOTS", "end-conditions SUBD_CREASES")


@pytest.fixture
def rig(monkeypatch):
    """A parametric design whose root adds Forms to the timeline; Finish Form records its runs."""
    timeline = FakeTimeline([])
    comp = MakeComp(name="Root")
    forms = FakeFormFeatures(timeline=timeline, component=comp)
    comp.features = FakeFeatures()
    comp.features.formFeatures = forms
    design = install(fc, MakeDesign(comp=comp, design_type=1, timeline=timeline))
    comp.parentDesign = design
    ran = []
    ui = FakeUserInterface(active_workspace=types.SimpleNamespace(id="FusionSolidEnvironment"))
    ui.commandDefinitions = types.SimpleNamespace(itemById=lambda cid: types.SimpleNamespace(
        execute=lambda: ran.append(cid) or True))
    monkeypatch.setattr(fc._common, "app", FakeApplication(active_product=design,
                                                           user_interface=ui))
    monkeypatch.setattr(fc._continuity, "body_seams", lambda body: [])
    monkeypatch.setattr(fc._form_common, "_SETTLE_S", 0.0)
    return types.SimpleNamespace(design=design, comp=comp, forms=forms, timeline=timeline,
                                 ran=ran, ui=ui)


def _form(rig, **kw):
    """The Form the next add() hands back, converting on finish unless told otherwise."""
    kw.setdefault("on_finish", _converted())
    ff = FakeFormFeature("Form1", component=rig.comp, **kw)
    rig.forms._made = ff
    return ff


class TestFormCreate:
    @pytest.mark.parametrize("workspace", ["FusionSolidEnvironment", "TSplineEnvironment"])
    def test_add_is_never_called_when_the_design_reads_direct(self, rig, workspace):
        # the workspace cannot discriminate an open Form edit from a plain direct design (no public
        # signal does), so the refusal is the same regardless of which workspace is active.
        rig.design.designType = 0
        rig.ui.activeWorkspace = types.SimpleNamespace(id=workspace)
        msg = error_message(fc.handler(primitive=_BOX))
        assert rig.forms._adds == 0
        assert "needs parametric mode" in msg

    @pytest.mark.parametrize("referenced,own_design,said", [
        (True, True, "places a component from another document"),
        (False, False, "does not read as a component of the active design")])
    def test_a_component_another_document_owns_is_refused_before_add(self, rig, referenced,
                                                                     own_design, said):
        other = MakeComp(name="Bracket")
        other.features = FakeFeatures()
        other.features.formFeatures = FakeFormFeatures(component=other)
        other.parentDesign = rig.design if own_design else MakeDesign()
        occ = make_occurrence(path="Bracket:1", component=other, referenced=referenced)
        rig.comp.occurrences, rig.comp.allOccurrences = _NamedCollection([occ]), [occ]
        msg = error_message(fc.handler(primitive=_BOX, component="Bracket:1"))
        assert said in msg and "open its source document" in msg
        assert rig.forms._adds == 0 and other.features.formFeatures._adds == 0

    def test_an_origin_that_overflows_in_cm_is_refused_naming_the_vertex(self, rig):
        msg = error_message(fc.handler(primitive=_BOX, units="in", origin=[1.5e308, 0, 0]))
        assert "vertex 0 is not three finite numbers" in msg and rig.forms._adds == 0

    def test_a_cage_naming_a_missing_vertex_is_refused_before_fusion(self, rig):
        cage = {"vertices": [[0, 0, 0]] * 8, "faces": [[0, 1, 2, 99]]}
        msg = error_message(fc.handler(cage=cage))
        assert "face 0" in msg and "99" in msg and rig.forms._adds == 0

    def test_both_or_neither_input_is_refused(self, rig):
        assert "both" in error_message(fc.handler(primitive=_BOX, cage={"vertices": []}))
        assert "neither" in error_message(fc.handler())

    def test_the_schema_types_each_cage_tuple_as_the_guard_checks_it(self):
        cage = fc.tool.to_dict()["inputSchema"]["properties"]["cage"]["properties"]
        got = {k: (s["items"]["items"]["type"], s["items"]["minItems"], s["items"]["maxItems"])
               for k, s in cage.items()}
        assert got == {"vertices": ("number", 3, 3), "faces": ("integer", 4, 4),
                       "creases": ("integer", 2, 2)}

    def test_a_misspelled_key_is_refused_not_dropped(self, rig):
        # the nested schemas carry no additionalProperties, so the handler is what refuses it
        assert "caped" in error_message(fc.handler(primitive=dict(_BOX, caped=False)))
        assert "vertexes" in error_message(fc.handler(cage={"vertexes": [], "faces": []}))
        assert rig.forms._adds == 0

    def test_a_raising_load_leaves_no_form_and_rereads_the_count(self, rig):
        ff = _form(rig)
        ff.tSplineBodies = FakeTSplineBodies(owner=ff, raises="3 : invalid argument tsmDescription")
        msg = error_message(fc.handler(primitive=_BOX))
        assert "invalid argument tsmDescription" in msg and "was removed" in msg
        assert ff._finishes == 1 and ff._deletes == 1 and rig.timeline.count == 0

    def test_a_failed_delete_during_rollback_names_the_leftover_form(self, rig):
        ff = _form(rig, delete_ok=False)
        ff.tSplineBodies = FakeTSplineBodies(owner=ff, raises="3 : invalid argument tsmDescription")
        msg = error_message(fc.handler(primitive=_BOX))
        assert "'Root/Form1' may remain" in msg and "design_delete_feature" in msg

    def test_a_delete_answering_true_that_leaves_the_row_is_recounted(self, rig, monkeypatch):
        ff = _form(rig)
        ff.tSplineBodies = FakeTSplineBodies(owner=ff, raises="3 : invalid argument tsmDescription")
        monkeypatch.setattr(ff, "deleteMe", lambda: True)
        msg = error_message(fc.handler(primitive=_BOX))
        assert "'Root/Form1' may remain" in msg and rig.timeline.count == 1

    @pytest.mark.parametrize("extra", [-1, 1])
    def test_an_add_that_is_not_one_timeline_row_rolls_back(self, rig, monkeypatch, extra):
        ff, add = _form(rig), rig.forms.add

        def add_rows():
            made = add()
            if extra < 0:
                rig.timeline._items.pop()
            else:
                rig.timeline._items.append(FakeTimelineObject(name="Form1", index=1, entity=made))
            return made
        monkeypatch.setattr(rig.forms, "add", add_rows)
        msg = error_message(fc.handler(primitive=_BOX))
        assert "the timeline reads" in msg and "It was removed" in msg and ff._deletes == 1

    def test_a_failed_finish_runs_finish_form_and_reports_it_unconfirmed(self, rig):
        ff = _form(rig, finish_ok=False)
        msg = error_message(fc.handler(primitive=_BOX))
        assert rig.ran == ["TSplineBaseFeatureStop"] and "did not confirm closed" in msg
        assert "then remove 'Root/Form1' with design_delete_feature(feature='Root/Form1')" in msg
        assert ff._deletes == 0

    @pytest.mark.parametrize("closes,said,deletes", [
        (True, "The Form was removed. The cage's surface passes through itself - move the grips",
         1),
        (False, "the Form edit is still open and 'Root/Form1' was left in place. The cage's "
                "surface passes through itself.", 0)])
    def test_a_raising_finish_never_runs_finish_form_and_reads_the_design_type(
            self, rig, closes, said, deletes):
        ff = _form(rig, finish_ok=_SELF_INTERSECTS, raise_closes=closes)
        msg = error_message(fc.handler(primitive=_BOX))
        assert "ASM_TSP_BFTS_OUTPUT_BODY_SELF_INTERSECTS" in msg and said in msg
        assert rig.ran == [] and ff._deletes == deletes and len(rig.timeline._items) == 1 - deletes
        if not closes:
            assert "design_delete_feature(feature='Root/Form1')" in msg
            assert "click Finish Form and choose Continue" in msg
            assert "(or correct the cage first)" in msg

    def test_a_raising_finish_whose_design_type_then_does_not_read_leaves_the_form(
            self, rig, monkeypatch):
        ff = _form(rig, finish_ok=_SELF_INTERSECTS)
        finish = ff.finishEdit

        def finish_then_unread():
            try:
                return finish()
            finally:
                rig.design.designType = None
        monkeypatch.setattr(ff, "finishEdit", finish_then_unread)
        msg = error_message(fc.handler(primitive=_BOX))
        assert "did not read" in msg and "click Finish Form" in msg
        assert rig.ran == [] and ff._deletes == 0

    def test_a_repaired_readback_rolls_back(self, rig):
        with open(os.path.join(_FIXTURES, "a3_box3_inconsistent_knot3_readback.tsm"),
                  encoding="utf-8") as fh:
            repaired = fh.read()
        ff = _form(rig)
        ff.tSplineBodies = FakeTSplineBodies(owner=ff, readback=lambda _text: repaired)
        msg = error_message(fc.handler(primitive=dict(_BOX, size=[200, 200, 200])))
        assert "106ek" in msg and "It was removed" in msg
        assert ff._deletes == 1 and rig.timeline.count == 0

    def test_a_dropped_crease_rolls_back(self, rig):
        ff = _form(rig)
        ff.tSplineBodies = FakeTSplineBodies(owner=ff, readback=lambda text: "\n".join(
            ln for ln in text.splitlines() if not ln.startswith("100edges")))
        msg = error_message(fc.handler(cage=_rim_cage()))
        assert "crease" in msg and ff._deletes == 1

    def test_a_grip_read_back_1e_6_cm_off_rolls_back(self, rig):
        def nudge(text):
            lines = text.splitlines()
            at = [n for n, ln in enumerate(lines) if ln.startswith("0g ")][5]
            x, y, z, w = lines[at].split()[1:5]
            lines[at] = f"0g {float(x) + 1e-6!r} {y} {z} {w}"
            return "\n".join(lines) + "\n"
        ff = _form(rig)
        ff.tSplineBodies = FakeTSplineBodies(owner=ff, readback=nudge)
        assert "vertex 5's grip" in error_message(fc.handler(primitive=_BOX)) and ff._deletes == 1

    def test_a_g0caps_header_rolls_back(self, rig):
        ff = _form(rig)
        ff.tSplineBodies = FakeTSplineBodies(owner=ff, readback=lambda t: t.replace("G1CAPS",
                                                                                    "G0CAPS"))
        assert "G0CAPS" in error_message(fc.handler(primitive=_BOX)) and ff._deletes == 1

    def test_a_closed_cage_reading_open_rolls_back(self, rig):
        ff = _form(rig, on_finish=_converted(solid=False))
        assert "isSolid" in error_message(fc.handler(primitive=_BOX)) and ff._deletes == 1

    def test_a_form_below_the_surface_area_threshold_is_removed_before_recording(self, rig):
        ff = _form(rig, on_finish=_converted(area=5e-7))

        msg = error_message(fc.handler(primitive=_BOX, name="TinyForm"))

        assert "TinyForm" in msg and "Form1" in msg
        assert "5e-07 cm2" in msg and "1e-06 cm2" in msg
        assert "It was removed" in msg and ff._deletes == 1
        assert rig.timeline.count == 0
        assert fc._form_common.read_record(ff) is None

    def test_an_extent_outside_the_cage_rolls_back(self, rig):
        ff = _form(rig, on_finish=_converted(lo=-2.0, hi=2.0))
        assert "not inside the cage" in error_message(fc.handler(primitive=_BOX))
        assert ff._deletes == 1

    @pytest.mark.parametrize("angle,said", [(5.0, "5.000 deg"), (None, "did not read")])
    def test_an_uncreased_seam_reading_sharp_or_unread_rolls_back(self, rig, monkeypatch, angle,
                                                                   said):
        ff = _form(rig)
        monkeypatch.setattr(fc._continuity, "body_seams", lambda body: [(object(), angle)])
        assert said in error_message(fc.handler(primitive=_BOX)) and ff._deletes == 1

    def test_a_dedupe_rename_is_disclosed(self, rig):
        ff = _form(rig)
        ff.tSplineBodies = FakeTSplineBodies(owner=ff, rename=lambda want: want + " (1)")
        out = payload(fc.handler(primitive=_BOX, name="Grip"))
        assert out["tspline_body"] == "Grip (1)" and "Grip (1)" in out["rename_warning"]
        assert out["result_bodies"] == ["Grip (1)"] and ff._deletes == 0

    def test_an_unnamed_body_takes_the_forms_name_and_a_brep_drift_is_disclosed(self, rig):
        ff = _form(rig, on_finish=_converted(name="Body11"))
        out = payload(fc.handler(primitive=_BOX))
        assert out["tspline_body"] == "Form1" and out["result_bodies"] == ["Body11"]
        assert "'Body11'" in out["rename_warning"] and ff._deletes == 0

    def test_a_creased_form_hands_its_sharp_seams_back_as_edge_handles(self, rig, monkeypatch):
        ff = _form(rig)
        ff.tSplineBodies = FakeTSplineBodies(owner=ff, readback=_creased_back)
        spline = types.SimpleNamespace(curveType=adsk.core.Curve3DTypes.NurbsCurve3DCurveType)
        edge = BRepEdge(spline, point_on_edge=FakePoint(1.0, 0.0, 1.0), entity_token="E1")
        monkeypatch.setattr(fc._continuity, "body_seams",
                            lambda body: [(edge, 90.0), (object(), 0.0)])
        out = payload(fc.handler(cage=_rim_cage()))
        assert out["readback"] == "exact" and out["cage"]["creases"] == 12
        assert [r["angle_deg"] for r in out["sharp_edges"]] == [90.0]
        assert out["sharp_edges"][0]["edge"].startswith("E1|@spline_edge:")
        assert out["extent"] == [18.0, 18.0, 18.0] and "record_stored" not in out

    @pytest.mark.parametrize("proxy_point,want", [
        ((51.0, 0.0, 1.0), "P1|@spline_edge:51.000000,0.000000,1.000000"), (None, None)])
    def test_a_form_in_a_placed_component_hands_back_world_edge_handles(
            self, rig, monkeypatch, proxy_point, want):
        seat = MakeComp(name="Seat")
        seat.features = FakeFeatures()
        seat.features.formFeatures = FakeFormFeatures(timeline=rig.timeline, component=seat)
        seat.parentDesign = rig.design
        occ = make_occurrence(path="Seat:1", component=seat, referenced=False)
        rig.comp.occurrences, rig.comp.allOccurrences = _NamedCollection([occ]), [occ]
        ff = FakeFormFeature("Form1", component=seat, on_finish=_converted())
        ff.tSplineBodies = FakeTSplineBodies(owner=ff, readback=_creased_back)
        seat.features.formFeatures._made = ff
        spline = types.SimpleNamespace(curveType=adsk.core.Curve3DTypes.NurbsCurve3DCurveType)
        proxy = (BRepEdge(spline, point_on_edge=FakePoint(*proxy_point), entity_token="P1")
                 if proxy_point else None)
        native = BRepEdge(spline, point_on_edge=FakePoint(1.0, 0.0, 1.0), entity_token="E1",
                          assembly_proxy=proxy)
        monkeypatch.setattr(fc._continuity, "body_seams", lambda body: [(native, 90.0)])
        out = payload(fc.handler(cage=_rim_cage(), component="Seat:1"))
        assert out["form"] == "Seat/Form1" and out["sharp_edges"][0]["edge"] == want

    @pytest.mark.parametrize("marker,after", [(1, "Shell1"), (2, None)])
    def test_a_form_created_behind_the_marker_names_the_item_after_it(self, rig, marker, after):
        rig.timeline._items = [FakeTimelineObject("Extrude1", 0), FakeTimelineObject("Shell1", 1)]
        rig.timeline._marker = marker
        _form(rig)
        out = payload(fc.handler(primitive=_BOX))
        assert out["timeline_index"] == marker and out.get("inserted_before") == after
        assert ("inserted_before" in out) is (after is not None)

    def test_an_open_cage_reads_its_one_faced_rims_as_no_seam_and_publishes_its_area(self, rig,
                                                                                     monkeypatch):
        monkeypatch.setattr(fc._continuity, "body_seams", _REAL_SEAMS)
        up = FakeVector3D(0, 0, 1)
        face = BRepFace(None)
        face.evaluator = types.SimpleNamespace(
            getParameterAtPoint=lambda pt: [True, (pt.x, pt.y)],
            getNormalAtParameter=lambda prm: [True, up])
        seam = BRepEdge(None, faces=[face, face])
        seam.evaluator = types.SimpleNamespace(
            getParameterExtents=lambda: [True, 0.0, 1.0],
            getPointAtParameter=lambda t: [True, FakePoint(t, 0.0, 0.0)])
        rims = [BRepEdge(None, faces=[face]) for _ in range(2)]

        def land(ff):
            ff.bodies = _NamedCollection([BRepBody(
                name=ff.tSplineBodies.item(0).name, bbox=make_bbox((-0.9, -0.9, -2.0),
                                                                   (0.9, 0.9, 2.0)),
                is_solid=False, face_count=1, area=22.5, edges=rims + [seam])])
        ff = _form(rig, on_finish=land)
        out = payload(fc.handler(primitive=_TUBE))
        assert out["is_solid"] is False and out["area_cm2"] == 22.5 and "volume_cm3" not in out
        assert out["sharp_edges"] == [] and "seams_unread" not in out and ff._deletes == 0
        record = fc._form_common.read_record(ff)
        assert record["area_cm2"] == 22.5 and record["volume_cm3"] is None

    @pytest.mark.parametrize("kw,said", [
        ({"on_finish": lambda ff: None}, "the Form holds no B-Rep body"),
        ({"health": adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState,
          "message": "Compute Failed"}, "the Form reads error: Compute Failed"),
        ({"tspline_readback": lambda text: None}, "the T-spline body's TSM did not read back"),
        ({"tspline_before": ["Old"]}, "the Form holds 2 T-spline bodies, not 1")])
    def test_a_form_failing_a_read_back_guard_is_removed(self, rig, kw, said):
        kw = dict(kw)
        back, before = kw.pop("tspline_readback", None), kw.pop("tspline_before", ())
        ff = _form(rig, **kw)
        if back or before:
            ff.tSplineBodies = FakeTSplineBodies([FakeTSplineBody(n, "", ff) for n in before],
                                                 owner=ff, readback=back)
        msg = error_message(fc.handler(primitive=_BOX))
        assert said in msg and "It was removed" in msg and ff._deletes == 1

    def test_a_record_the_attributes_did_not_keep_is_disclosed(self, rig):
        ff = _form(rig)
        ff.attributes = type(ff.attributes)(lands=False)
        out = payload(fc.handler(primitive=_BOX))
        assert out["created"] is True and out["record_stored"] is False

    @pytest.mark.parametrize("case,said", [
        ("start", "The Form's edit did not open (startEdit False). The Form was removed."),
        ("add", "FormFeatures.add() returned nothing"),
        ("load", "addByTSMDescription returned nothing. The Form made for it was removed.")])
    def test_an_add_open_or_load_that_answers_nothing_stops_the_create(self, rig, monkeypatch,
                                                                         case, said):
        ff = _form(rig, start_ok=case != "start")
        if case == "add":
            monkeypatch.setattr(rig.forms, "add", lambda: None)
        if case == "load":
            monkeypatch.setattr(ff.tSplineBodies, "addByTSMDescription", lambda text: None)
        msg = error_message(fc.handler(primitive=_BOX))
        assert said in msg and ff._finishes == (1 if case == "load" else 0)
        assert len(rig.timeline._items) == 0


class _NativeBodies(FakeTSplineBodies):
    """tSplineBodies with the four primitive inputs: each create*Input records its arguments and
    addByShapeInput lands a body reading `text` back (or raises `refuses`)."""

    def __init__(self, text, owner, refuses=None):
        super().__init__(owner=owner)
        self._text, self._refuses, self.inputs = text, refuses, []

    def _input(self, kind, *args):
        made = types.SimpleNamespace(kind=kind, args=args)
        self.inputs.append(made)
        return made

    def createSphereInput(self, *args):
        return self._input("sphere", *args)

    def createTorusInput(self, *args):
        return self._input("torus", *args)

    def createQuadballInput(self, *args):
        return self._input("quadball", *args)

    def createPlaneInput(self, *args):
        return self._input("plane", *args)

    def addByShapeInput(self, inp):
        if self._refuses:
            raise RuntimeError(self._refuses)
        body = FakeTSplineBody("Body1", self._text, self._owner)
        self._bodies.append(body)
        return body


def _boxed(lo, hi, solid=True):
    """The finish's conversion with its own box corners (cm)."""
    def land(ff):
        if ff.tSplineBodies.count:
            ff.bodies = _NamedCollection([BRepBody(
                name=ff.tSplineBodies.item(0).name, bbox=make_bbox(lo, hi), volume=4.17,
                is_solid=solid, face_count=6, area=12.0)])
    return land


# A closed 54-face cage text and an open 4-face one: what the native bodies read back here.
_BALL_54 = tsm.emit(tsm.translated(tsm.box([2.0, 2.0, 2.0], [3, 3, 3]), 1.0, [0, 0, 0]))
_SHEET_4 = tsm.emit({"vertices": [[x, y, 0.0] for y in (0, 1, 2) for x in (0, 1, 2)],
                     "faces": [[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]],
                     "creases": []})


@pytest.fixture
def points(monkeypatch):
    """adsk.core points and vectors as plain tuples, so a primitive's placement can be read."""
    monkeypatch.setattr(fc.adsk.core, "Point3D", types.SimpleNamespace(create=lambda *a: a),
                        raising=False)
    monkeypatch.setattr(fc.adsk.core, "Vector3D", types.SimpleNamespace(create=lambda *a: a),
                        raising=False)


def _native(rig, text, lo, hi, solid=True, refuses=None):
    ff = _form(rig, on_finish=_boxed(lo, hi, solid))
    ff.tSplineBodies = _NativeBodies(text, ff, refuses)
    return ff


class TestNativePrimitives:
    def test_a_quadball_is_built_in_cm_at_its_centre_and_recorded(self, rig, points):
        ff = _native(rig, _BALL_54, (0.0, -1.0, -1.0), (2.0, 1.0, 1.0))
        out = payload(fc.handler(primitive={"shape": "quadball", "size": [10], "spans": [3]},
                                 origin=[10, 0, 0]))
        inp = ff.tSplineBodies.inputs[0]
        assert inp.kind == "quadball" and inp.args[0] == (1.0, 0.0, 0.0) and inp.args[3:] == (1.0,)
        assert inp.faceCount == 3
        assert out["created"] is True and out["is_solid"] is True and out["cage"]["faces"] == 54
        assert out["readback"] == "faces, solidity and box"
        assert fc._form_common.read_record(ff)["primitive"] == {
            "shape": "quadball", "size_cm": [1.0], "spans": [3]}

    def test_a_plane_is_placed_by_its_corner_so_it_ends_up_centred(self, rig, points):
        ff = _native(rig, _SHEET_4, (0.0, -0.5, 0.0), (2.0, 0.5, 0.0), solid=False)
        out = payload(fc.handler(primitive={"shape": "plane", "size": [20, 10], "spans": [2, 2]},
                                 origin=[10, 0, 0]))
        inp = ff.tSplineBodies.inputs[0]
        assert inp.args[0] == (0.0, -0.5, 0.0) and inp.args[3:] == (2.0, 1.0)
        assert (inp.xFaceCount, inp.yFaceCount) == (2, 2)
        assert out["is_solid"] is False and "area_cm2" in out

    def test_a_cage_with_another_face_count_than_asked_is_removed(self, rig, points):
        ff = _native(rig, _BALL_54, (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
        msg = error_message(fc.handler(primitive={"shape": "quadball", "size": [10],
                                                  "spans": [2]}))
        assert "reads 54 faces for 24 asked" in msg and ff._deletes == 1

    def test_a_solid_whose_cage_text_reads_open_is_kept(self, rig, points):
        # a native sphere's TSM reads open at its poles (measured); the body's isSolid is the judge
        ff = _native(rig, _SHEET_4, (-1.0,) * 3, (1.0,) * 3)
        out = payload(fc.handler(primitive={"shape": "sphere", "size": [10], "spans": [2, 2]}))
        assert out["created"] is True and out["is_solid"] is True and ff._deletes == 0

    def test_a_closed_primitive_whose_body_reads_open_is_removed(self, rig, points):
        ff = _native(rig, _BALL_54, (-1.0,) * 3, (1.0,) * 3, solid=False)
        msg = error_message(fc.handler(primitive={"shape": "quadball", "size": [10],
                                                  "spans": [3]}))
        assert "isSolid" in msg and ff._deletes == 1

    def test_a_body_a_tenth_the_size_asked_is_removed(self, rig, points):
        ff = _native(rig, _BALL_54, (-0.1, -0.1, -0.1), (0.1, 0.1, 0.1))
        msg = error_message(fc.handler(primitive={"shape": "quadball", "size": [10],
                                                  "spans": [3]}))
        assert "does not fill the quadball asked" in msg and ff._deletes == 1

    def test_a_torus_body_taller_than_its_minor_radius_is_removed(self, rig, points):
        ff = _native(rig, _BALL_54, (-2.5, -2.5, -2.5), (2.5, 2.5, 2.5))
        msg = error_message(fc.handler(primitive={"shape": "torus", "size": [20, 5],
                                                  "spans": [9, 6]}))
        assert "not inside the primitive's" in msg and ff._deletes == 1
        inp = ff.tSplineBodies.inputs[0]
        assert inp.args[3:] == (2.0, 0.5) and (inp.majorFaceCount, inp.minorFaceCount) == (9, 6)

    def test_a_primitive_fusion_refuses_is_removed_with_its_message(self, rig, points):
        ff = _native(rig, _BALL_54, (-1.0,) * 3, (1.0,) * 3, refuses="3 : invalid faceCount")
        msg = error_message(fc.handler(primitive={"shape": "sphere", "size": [10],
                                                  "spans": [1, 1]}))
        assert "Fusion refused the primitive: 3 : invalid faceCount" in msg and ff._deletes == 1

    @pytest.mark.parametrize("primitive,said", [
        ({"shape": "sphere", "size": [10, 10], "spans": [8, 8]}, "size for a sphere is 1"),
        ({"shape": "torus", "size": [20, 5], "spans": [8]}, "spans for a torus is 2"),
        ({"shape": "plane", "size": [20, 10], "spans": [2, 2], "capped": False}, "has no caps"),
        ({"shape": "quadball", "size": [10], "spans": [40]}, "make 9600 faces"),
        ({"shape": "sphere", "size": [10], "spans": [8, 8], "radius": 5}, "radius")])
    def test_a_malformed_native_primitive_is_refused_before_add(self, rig, primitive, said):
        assert said in error_message(fc.handler(primitive=primitive)) and rig.forms._adds == 0
