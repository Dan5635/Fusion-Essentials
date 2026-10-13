"""Unit tests for ``model_thread.py`` - add a Thread feature to existing cylindrical faces.

Pinned: the bore-vs-shaft derivation from each face's own outward normal (and its refusal when the
normal is unreadable or the set mixes sides), the partial-length contract (isFullLength false plus
the cm-scaled length/offset/location), the designation/handedness/modeled settings reaching the
input, and the honesty gates - a failed compute, a designation or side that reads back different
from the one requested, and a modeled thread that left the body's volume untouched.
"""

import pytest

from conftest import (load_tool, make_design, install, MakeComp, payload, error_message,
                      assert_no_active_design, assert_unknown_units,
                      BRepBody, BRepFace, Cylinder, FakePoint, FakeVector3D, _NamedCollection)

mt = load_tool("model_thread")


class _VI:
    def __init__(self, value):
        self.value = value


def _cyl_face(body=None, radial=(1.0, 0.0, 0.0), axis_origin=(0.0, 0.0, 0.0)):
    """A cylindrical face sampled at (1,0,0), on a cylinder whose axis passes through
    `axis_origin`. radial=(-1,0,0) points at the axis (a bore); (1,0,0) points away (a shaft);
    None leaves the face with no evaluator to sample."""
    return BRepFace(Cylinder(FakeVector3D(0.0, 0.0, 1.0), FakePoint(*axis_origin)),
                    body=body if body is not None else BRepBody("Body1", volume=100.0),
                    point_on_face=FakePoint(1.0, 0.0, 0.0),
                    normal=FakeVector3D(*radial) if radial else None)


class FakeThreadInfo:
    def __init__(self, internal, ttype, desig, cls, right_handed=True):
        self.isInternal = internal
        self.threadType = ttype
        self.threadDesignation = desig
        self.threadClass = cls
        self.isRightHanded = right_handed


class FakeThreadInput:
    """The thread input. Its retired isRightHanded starts true and every write to it is counted,
    so a test can tell a request that needed the retired member from one that did not."""
    __slots__ = ("inputCylindricalFaces", "threadInfo", "isModeled", "isFullLength",
                 "threadLength", "threadOffset", "threadLocation", "_right_handed", "hand_writes")

    @property
    def isRightHanded(self):
        return self._right_handed

    @isRightHanded.setter
    def isRightHanded(self, value):
        self.hand_writes += 1
        self._right_handed = value

    def __init__(self, faces, info):
        self._right_handed, self.hand_writes = True, 0
        self.inputCylindricalFaces = faces
        self.threadInfo = info
        self.isModeled = False
        self.isFullLength = True
        self.threadLength = None
        self.threadOffset = None
        self.threadLocation = None


class FakeThreadFeature:
    """A live ThreadFeature reports the partial extent back: isFullLength plus threadLength /
    threadOffset as ModelParameters carrying centimetres, and threadLocation as the enum. The
    fake echoes the input unless a test overrides it to model an extent that did not take."""
    def __init__(self, inp, name="Thread1", health=0, info=None, full_length=None,
                 length_cm=None, offset_cm=None):
        self.name = name
        self.healthState = health
        self.errorOrWarningMessage = "the thread does not fit the cylinder"
        self.threadInfo = info if info is not None else inp.threadInfo
        self.isModeled = inp.isModeled
        # The feature answers the hand of the INPUT's flag; a left-handed ThreadInfo alone still
        # builds a right-handed thread.
        self.isRightHanded = inp.isRightHanded
        self.isFullLength = inp.isFullLength if full_length is None else full_length
        got_len = inp.threadLength.value if inp.threadLength is not None else None
        got_off = inp.threadOffset.value if inp.threadOffset is not None else None
        self.threadLength = _VI(got_len if length_cm is None else length_cm)
        self.threadOffset = _VI(got_off if offset_cm is None else offset_cm)
        self.threadLocation = inp.threadLocation


class FakeThreadFeatures:
    """Record thread inputs and optionally change modeled fixture volume."""
    def __init__(self, bodies=(), volume_delta=-2.0, return_feature=True, health=0,
                 feature_info=None, full_length=None, length_cm=None, offset_cm=None):
        self.added = 0
        self.full_length = full_length
        self.length_cm = length_cm
        self.offset_cm = offset_cm
        self.bodies = list(bodies)
        self.volume_delta = volume_delta
        self.return_feature = return_feature
        self.health = health
        self.feature_info = feature_info
        # Not a ThreadFeatures member: the library _wire puts behind the two static factories.
        self.catalog = FakeThreadCatalog()
        self.last_input = None

    def createInput(self, faces, info):
        self.last_input = FakeThreadInput(faces, info)
        return self.last_input

    def __len__(self):
        # a live ThreadFeatures collection is falsy while empty
        return self.added

    def add(self, inp):
        self.added += 1
        if not self.return_feature:
            return None
        if inp.isModeled and self.bodies:
            per_body = self.volume_delta / len(self.bodies)
            for b in self.bodies:
                # a body whose volume is unreadable stays unreadable across the mutation
                if isinstance(b.volume, (int, float)):
                    b.volume += per_body
        return FakeThreadFeature(inp, health=self.health, info=self.feature_info,
                                 full_length=self.full_length, length_cm=self.length_cm,
                                 offset_cm=self.offset_cm)


class FakeThreadDataQuery:
    """The thread library the shared resolver walks, shaped as it reads live: the metric type is
    'ANSI Metric M Profile', and a size carries several designations and several classes, the
    external list starting 4g6g."""
    @property
    def allThreadTypes(self):
        return ("ANSI Metric M Profile", "ISO Metric profile")

    def allSizes(self, t):
        return ("10.0", "30.0")

    def allDesignations(self, t, size):
        # 'M10x1.25' sits in BOTH types, as 540 of the 1510 live designations do; the rest sit in
        # exactly one
        if t == "ISO Metric profile":
            return ("M10x1.25",) if size.startswith("10") else ()
        return ("M10x1.5", "M10x1.25") if size.startswith("10") else ("M30x3.5", "M30x3")

    def allClasses(self, internal, t, desig):
        return ("6H", "6G") if internal else ("4g6g", "6g")


class FakeThreadCatalog:
    """What ThreadDataQuery.create and ThreadInfo.create answer from; neither has a measured shape."""
    def __init__(self):
        self.query = FakeThreadDataQuery()
        self.created = []

    def data_query(self, tapered=False):
        # Injected, not measured: the tapered library answers nothing here.
        return None if tapered else self.query

    def thread_info(self, tapered, internal, ttype, desig, cls, right_handed):
        if tapered:
            return None
        ti = FakeThreadInfo(internal, ttype, desig, cls, right_handed)
        self.created.append(ti)
        return ti


def _wire(monkeypatch, feats, faces):
    import adsk.core
    import adsk.fusion
    comp = MakeComp(name="Comp")
    comp.features = type("F", (), {"threadFeatures": feats})()
    install(mt, make_design(comp=comp))
    monkeypatch.setattr(adsk.fusion.ThreadDataQuery, "create", feats.catalog.data_query)
    monkeypatch.setattr(adsk.fusion.ThreadInfo, "create", feats.catalog.thread_info)
    monkeypatch.setattr(mt._FACES, "resolve", lambda raw: (faces, None))
    adsk.core.ValueInput.createByReal = staticmethod(lambda v: _VI(v))


def _shaft(body=None):
    return _cyl_face(body, radial=(1.0, 0.0, 0.0))


def _bore(body=None):
    return _cyl_face(body, radial=(-1.0, 0.0, 0.0))


class TestSideDerivation:
    def test_normal_pointing_away_from_the_axis_is_external(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5"))
        assert out["internal"] is False
        assert feats.catalog.created[0].isInternal is False
        assert feats.catalog.created[0].threadClass == "4g6g"

    def test_normal_pointing_at_the_axis_is_internal(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_bore()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5"))
        assert out["internal"] is True
        assert feats.catalog.created[0].isInternal is True
        assert feats.catalog.created[0].threadClass == "6H"

    def test_offset_axis_origin_still_classifies_by_the_radial_component(self, monkeypatch):
        face = _cyl_face(radial=(-1.0, 0.0, 0.0), axis_origin=(0.0, 0.0, 50.0))
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [face])
        assert payload(mt.handler(faces=["h"], designation="M10x1.5"))["internal"] is True

    def test_unreadable_normal_is_refused_not_guessed(self, monkeypatch):
        face = _cyl_face(radial=None)
        _wire(monkeypatch, FakeThreadFeatures(), [face])
        msg = error_message(mt.handler(faces=["h"], designation="M10x1.5"))
        assert "[0]" in msg and "normal" in msg

    def test_mixed_sides_are_refused_naming_the_bores(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft(), _bore(), _shaft()])
        msg = error_message(mt.handler(faces=["a", "b", "c"], designation="M10x1.5"))
        assert "[1]" in msg and "mix" in msg

    def test_several_faces_of_one_side_thread_together(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft(), _shaft(), _shaft()])
        out = payload(mt.handler(faces=["a", "b", "c"], designation="M10x1.5"))
        assert out["faces"] == 3
        assert feats.last_input.inputCylindricalFaces.count == 3


class TestThreadSettings:
    def test_cosmetic_and_right_handed_by_default(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5"))
        assert feats.last_input.isModeled is False
        assert feats.catalog.created[0].isRightHanded is True
        assert feats.last_input.isFullLength is True
        assert out["modeled"] is False and out["right_handed"] is True

    def test_left_handed_sets_the_inputs_flag_as_well_as_the_thread_info(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5", left_handed=True))
        assert feats.last_input.threadInfo is feats.catalog.created[0]
        assert feats.catalog.created[0].isRightHanded is False
        assert feats.last_input.isRightHanded is False and feats.last_input.hand_writes == 1
        assert out["right_handed"] is False

    def test_a_right_handed_thread_never_touches_the_retired_flag(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5"))
        assert feats.last_input.hand_writes == 0 and out["right_handed"] is True

    def test_length_clears_full_length_and_scales_to_cm(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5", length=12, offset=2))
        assert feats.last_input.isFullLength is False
        assert round(feats.last_input.threadLength.value, 6) == 1.2
        assert round(feats.last_input.threadOffset.value, 6) == 0.2
        assert out["length"] == 12 and out["offset"] == 2 and out["location"] == "high"

    def test_no_length_leaves_full_length_and_reports_no_length(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5"))
        assert feats.last_input.isFullLength is True
        assert feats.last_input.threadLength is None
        assert "length" not in out

    def test_inch_units_scale_the_length(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        payload(mt.handler(faces=["h"], designation="M10x1.5", length=1, units="in"))
        assert round(feats.last_input.threadLength.value, 6) == 2.54

    def test_each_location_reaches_the_input_as_its_own_enum(self, monkeypatch):
        # live-verified: HighEndThreadLocation threads the end the cylinder axis points toward,
        # LowEndThreadLocation the opposite end
        import adsk.fusion
        wanted = {"high": adsk.fusion.ThreadLocations.HighEndThreadLocation,
                  "low": adsk.fusion.ThreadLocations.LowEndThreadLocation}
        assert wanted["high"] != wanted["low"]
        for key, want in wanted.items():
            feats = FakeThreadFeatures()
            _wire(monkeypatch, feats, [_shaft()])
            out = payload(mt.handler(faces=["h"], designation="M10x1.5", length=5, location=key))
            assert out["location"] == key
            assert feats.last_input.threadLocation == want


class TestGuards:
    def test_no_active_design(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        assert_no_active_design(mt, mt.handler, faces=["h"], designation="M10x1.5")

    def test_bad_units(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        assert_unknown_units(mt.handler, faces=["h"], designation="M10x1.5")

    def test_missing_designation(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        msg = error_message(mt.handler(faces=["h"], designation=""))
        assert "designation" in msg

    def test_unknown_designation_lists_the_call_out_shape(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        msg = error_message(mt.handler(faces=["h"], designation="M99x9"))
        assert "M99x9" in msg and "thread library" in msg

    def test_offset_without_length_is_refused(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        msg = error_message(mt.handler(faces=["h"], designation="M10x1.5", offset=2))
        assert "offset" in msg and "length" in msg

    def test_location_without_length_is_refused(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        msg = error_message(mt.handler(faces=["h"], designation="M10x1.5", location="low"))
        assert "location" in msg and "length" in msg

    def test_zero_length_is_refused(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        msg = error_message(mt.handler(faces=["h"], designation="M10x1.5", length=0))
        assert "length" in msg and "non-zero" in msg

    def test_negative_length_is_refused(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        msg = error_message(mt.handler(faces=["h"], designation="M10x1.5", length=-5))
        assert "length" in msg and "positive" in msg

    def test_unknown_location_is_refused(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        msg = error_message(mt.handler(faces=["h"], designation="M10x1.5", length=5,
                                       location="middle"))
        assert "location" in msg

    def test_face_resolution_error_propagates(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        monkeypatch.setattr(mt._FACES, "resolve",
                            lambda raw: (None, "'faces' must be a CYLINDRICAL face, but the handle "
                                               "points at a BRepEdge."))
        msg = error_message(mt.handler(faces=["flat"], designation="M10x1.5"))
        assert "CYLINDRICAL" in msg


class TestLibraryChoices:
    @pytest.fixture
    def library(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        query = feats.catalog.query
        monkeypatch.setattr(query, "allSizes", lambda t: ("6.0",))
        monkeypatch.setattr(query, "allDesignations", lambda t, s:
                            ("M6x1", "M6x0.8", "M6x0.75", "M6x0.7", "M6x0.5"))
        return feats

    def test_refusal_offers_actual_literal_that_can_be_consumed(self, library):
        args = dict(faces=["h"], designation="M6x1.0",
                    thread_type="ISO Metric profile", thread_class="6g")
        message = error_message(mt.handler(**args))
        assert "'M6x1' in 'ISO Metric profile' (classes: 6g)" in message
        assert "M5x0.8" not in message and "ANSI" not in message
        assert "not fit recommendations" in message
        assert message.count("(classes:") == 5
        assert library.added == 0 and library.catalog.created == []
        literal = message.split("recommendations): '", 1)[1].split("'", 1)[0]
        assert literal == "M6x1"
        out = payload(mt.handler(**{**args, "designation": literal}))
        assert out["designation"] == literal and out["thread_class"] == "6g"
        assert "was not measured" in out["note"] and "find_geometry" in out["note"]
        assert "does not check" not in out["note"]

    @pytest.mark.parametrize("standard,cls", [("unknown standard", "6g"), ("ISO Metric profile", "6H")])
    def test_nearby_choices_survive_incompatible_selectors(self, library, standard, cls):
        message = error_message(mt.handler(faces=["h"], designation="M6x1.0",
                                           thread_type=standard, thread_class=cls))
        assert "Nearby library spellings (not fit recommendations)" in message
        assert "'M6x1' in 'ANSI Metric M Profile' (classes: 4g6g, 6g)" in message
        assert "Choose a listed designation, type and class" in message
        assert "Thread dialog" not in message
        assert library.catalog.created == [] and library.added == 0

    @pytest.mark.parametrize("listed", [("M6x1", "M6x0.8", "M6x0.75", "M6x0.7", "M6x0.5"),
                                        ("M6x0.5", "M6x0.7", "M6x0.75", "M6x0.8", "M6x1")])
    @pytest.mark.parametrize("standard,order", [
        ("", ("ANSI Metric M Profile", "ISO Metric profile")),
        ("ISO Metric profile", ("ISO Metric profile", "ANSI Metric M Profile"))])
    def test_unreadable_classes_name_the_closest_catalog_designation_per_type(
            self, library, monkeypatch, standard, order, listed):
        def fail(*args):
            raise RuntimeError("unreadable classes")
        monkeypatch.setattr(library.catalog.query, "allClasses", fail)
        monkeypatch.setattr(library.catalog.query, "allDesignations", lambda t, s: listed)
        message = error_message(mt.handler(faces=["h"], designation="M6x1.0", thread_type=standard))
        assert ("No nearby alternative with readable classes was found. Closest designation per "
                f"thread type: 'M6x1' in '{order[0]}'; 'M6x1' in '{order[1]}'. Retry with one as "
                "designation and its thread_type.") in message
        assert "Thread dialog" not in message and "(classes:" not in message
        assert library.catalog.created == [] and library.added == 0

    @pytest.mark.parametrize("count,more", [(5, ""), (6, "; 1 more thread type(s) not listed")])
    def test_closest_designations_past_five_types_are_counted(self, library, monkeypatch, count,
                                                               more):
        types = tuple(f"T{i}" for i in range(1, count + 1))
        monkeypatch.setattr(FakeThreadDataQuery, "allThreadTypes", property(lambda _self: types))
        monkeypatch.setattr(library.catalog.query, "allClasses",
                            lambda *a: (_ for _ in ()).throw(RuntimeError("unreadable classes")))
        message = error_message(mt.handler(faces=["h"], designation="M6x1.0"))
        listed = "; ".join(f"'M6x1' in 'T{i}'" for i in range(1, 6))
        assert (f"Closest designation per thread type: {listed}{more}. Retry with one as "
                "designation and its thread_type.") in message

    def test_a_library_with_no_readable_designation_lists_its_thread_types(self, library,
                                                                             monkeypatch):
        monkeypatch.setattr(library.catalog.query, "allDesignations", lambda t, s: ())
        message = error_message(mt.handler(faces=["h"], designation="M6x1.0"))
        assert message.endswith("No designation in the thread library read; its thread types: "
                                "ANSI Metric M Profile, ISO Metric profile.")
        assert "Thread dialog" not in message and library.added == 0

    def test_query_and_reply_choices_are_bounded(self, library, monkeypatch):
        queried = []
        monkeypatch.setattr(library.catalog.query, "allDesignations", lambda t, s:
                            tuple(f"M6x1.{i}" for i in range(20)))
        def all_compatible(internal, standard, designation):
            queried.append((internal, standard, designation))
            return ("6g",)
        monkeypatch.setattr(library.catalog.query, "allClasses", all_compatible)
        message = error_message(mt.handler(faces=["h"], designation="M6x1.00",
            thread_type="ISO Metric profile", thread_class="6g"))
        assert len(queried) == message.count("(classes:") == 5
        queried.clear()
        def classes(internal, standard, designation):
            queried.append((internal, standard, designation))
            return ("6g",) if designation.endswith(".9") else ("4g6g",)
        monkeypatch.setattr(library.catalog.query, "allClasses", classes)
        message = error_message(mt.handler(faces=["h"], designation="M6x1.00",
            thread_type="ISO Metric profile", thread_class="6g"))
        assert len(queried) <= 10
        assert message.count("(classes:") <= 5 and "(classes: 4g6g)" not in message
        assert library.catalog.created == [] and library.added == 0

    def test_fallback_reads_other_types_after_compatible_probe_budget(self, library, monkeypatch):
        query = library.catalog.query
        monkeypatch.setattr(query, "allSizes", lambda _t: ("6.0",))
        close = tuple(f"M6x1.00{letter}" for letter in "abcde")
        remaining = tuple(f"M6x1.0{i}" for i in range(5))
        monkeypatch.setattr(FakeThreadDataQuery, "allThreadTypes",
                            property(lambda _self: ("ISO Metric profile", "ANSI Metric M Profile")))
        monkeypatch.setattr(query, "allDesignations", lambda t, _s:
                            close + remaining if t == "ISO Metric profile" else close)
        queried = []
        def classes(internal, standard, designation):
            queried.append((standard, designation))
            return ("4g6g",) if standard == "ISO Metric profile" else ("6g",)
        monkeypatch.setattr(query, "allClasses", classes)
        message = error_message(mt.handler(faces=["h"], designation="M6x1.00?",
                                           thread_type="ISO Metric profile", thread_class="6g"))
        assert "'M6x1.00e' in 'ANSI Metric M Profile' (classes: 6g)" in message
        assert len(queried) <= 20 and message.count("(classes:") <= 5
        assert library.catalog.created == [] and library.added == 0


class TestHonesty:
    def test_health_error_reported_not_false_ok(self, monkeypatch):
        feats = FakeThreadFeatures(health=2)
        _wire(monkeypatch, feats, [_shaft()])
        res = mt.handler(faces=["h"], designation="M10x1.5")
        assert res["isError"] is True
        assert "failed to compute" in res["message"] and "does not fit" in res["message"]

    def test_no_feature_returned_is_error(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(return_feature=False), [_shaft()])
        res = mt.handler(faces=["h"], designation="M10x1.5")
        assert res["isError"] is True and "no feature" in res["message"]

    def test_designation_read_back_mismatch_is_error(self, monkeypatch):
        other = FakeThreadInfo(False, "ANSI Metric M Profile", "M8x1.25", "6g")
        _wire(monkeypatch, FakeThreadFeatures(feature_info=other), [_shaft()])
        res = mt.handler(faces=["h"], designation="M10x1.5")
        assert res["isError"] is True and "M8x1.25" in res["message"]

    def test_side_read_back_mismatch_is_error(self, monkeypatch):
        other = FakeThreadInfo(True, "ANSI Metric M Profile", "M10x1.5", "6H")
        _wire(monkeypatch, FakeThreadFeatures(feature_info=other), [_shaft()])
        res = mt.handler(faces=["h"], designation="M10x1.5")
        assert res["isError"] is True and "internal" in res["message"]

    def test_add_raising_surfaces_as_error(self, monkeypatch):
        feats = FakeThreadFeatures()
        feats.add = lambda inp: (_ for _ in ()).throw(RuntimeError("thread pitch too coarse"))
        _wire(monkeypatch, feats, [_shaft()])
        res = mt.handler(faces=["h"], designation="M10x1.5")
        assert res["isError"] is True and "thread pitch too coarse" in res["message"]

    def test_modeled_thread_reports_the_volume_it_cut(self, monkeypatch):
        body = BRepBody("Post", volume=100.0)
        feats = FakeThreadFeatures([body], volume_delta=-2.5)
        _wire(monkeypatch, feats, [_shaft(body)])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5", modeled=True))
        assert out["modeled"] is True
        assert out["volume_delta_cm3"] == -2.5

    def test_modeled_thread_that_cut_nothing_is_error(self, monkeypatch):
        body = BRepBody("Post", volume=100.0)
        feats = FakeThreadFeatures([body], volume_delta=0.0)
        _wire(monkeypatch, feats, [_shaft(body)])
        res = mt.handler(faces=["h"], designation="M10x1.5", modeled=True)
        assert res["isError"] is True and "unchanged" in res["message"]

    def test_cosmetic_thread_is_not_gated_on_volume(self, monkeypatch):
        body = BRepBody("Post", volume=100.0)
        feats = FakeThreadFeatures([body], volume_delta=0.0)
        _wire(monkeypatch, feats, [_shaft(body)])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5"))
        assert out["threaded"] is True
        assert "volume_delta_cm3" not in out


class TestCosmeticResize:
    def _resized(self, monkeypatch, after_cm, extra=(), untyped=False, flipped=False):
        """A 1 cm shaft on its body, `extra` faces beside it, whose radius reads `after_cm` after the thread."""
        body = BRepBody("Post", volume=100.0)
        face = _shaft(body)
        face.geometry.radius = 1.0
        body.faces = _NamedCollection([face, *extra])
        feats = FakeThreadFeatures()
        real_add = feats.add

        def add(inp):
            face.geometry.radius = after_cm
            if untyped:
                face.geometry.surfaceType = None
            if flipped:
                face.geometry.axis = FakeVector3D(0.0, 0.0, -1.0)
            return real_add(inp)

        feats.add = add
        _wire(monkeypatch, feats, [face])
        return payload(mt.handler(faces=["h"], designation="M10x1.5"))

    @pytest.mark.parametrize("flipped", [False, True])     # True: the face's axis reads reversed after the thread
    def test_a_changed_radius_is_reported_before_and_after(self, monkeypatch, flipped):
        bore = _bore()
        bore.geometry.radius = 0.5
        elsewhere = _cyl_face(radial=(-1.0, 0.0, 0.0), axis_origin=(5.0, 0.0, 0.0))   # a shaft
        elsewhere.geometry.radius = 2.0
        # A shaft whose axis crosses the threaded one at the origin, perpendicular to it.
        across = BRepFace(Cylinder(FakeVector3D(1.0, 0.0, 0.0), FakePoint(0.0, 0.0, 0.0)),
                          body=BRepBody("Body1"), point_on_face=FakePoint(0.0, 0.0, 2.0),
                          normal=FakeVector3D(0.0, 0.0, 1.0))
        across.geometry.radius = 2.0
        out = self._resized(monkeypatch, 1.486725, extra=(bore, elsewhere, across), flipped=flipped)
        assert out["cylinder_radii"] == [{"before": 10.0, "after": 14.86725, "change": 4.86725}]
        assert ("Cosmetic thread added; cylinder radius before -> after (mm): face 0 10.0 -> "
                "14.86725 (+4.86725).") in out["note"] and "may resize" not in out["note"]

    @pytest.mark.parametrize("after_cm,untyped", [(None, False), (1.486725, True)])
    def test_an_unreadable_radius_says_the_resize_was_not_measured(self, monkeypatch, after_cm,
                                                                    untyped):
        coaxial = _shaft()        # reads the before radius, so skipping the threaded face reads 10 -> 10
        coaxial.geometry.radius = 1.0
        out = self._resized(monkeypatch, after_cm, extra=(coaxial,), untyped=untyped)
        assert out["cylinder_radii"] == [{"before": 10.0, "after": None, "change": None}]
        assert out["note"].startswith("Cosmetic thread added; the resize of face(s) [0] (0-based) "
                                      "was not measured")
        assert "find_geometry(kind='cylinder_face')" in out["note"]


class TestOutputContract:
    def test_feature_output_is_minted(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5"))
        for o in mt.RETURNS:
            assert o.assert_present(out) == "", o.key


class TestEmptyCollectionIsNotAbsence:
    def test_the_first_thread_in_a_component_still_resolves(self, monkeypatch):
        feats = FakeThreadFeatures()
        assert not feats, "the fake must read falsy while empty, as the live collection does"
        _wire(monkeypatch, feats, [_shaft()])
        assert payload(mt.handler(faces=["h"], designation="M10x1.5"))["faces"] == 1


class TestMisSizedModeledThread:
    def test_a_modeled_thread_that_grew_the_body_is_error(self, monkeypatch):
        # a designation too large for a shaft builds the form outside the cylinder and ADDS
        # material; every designation that fits removes it
        body = BRepBody("Post", volume=18.85)
        feats = FakeThreadFeatures([body], volume_delta=17.3)
        _wire(monkeypatch, feats, [_shaft(body)])
        res = mt.handler(faces=["h"], designation="M30x3.5", modeled=True)
        assert res["isError"] is True
        assert "GREW" in res["message"] and "17.3" in res["message"]

    def test_a_fitting_modeled_thread_still_passes(self, monkeypatch):
        body = BRepBody("Post", volume=18.85)
        feats = FakeThreadFeatures([body], volume_delta=-2.99)
        _wire(monkeypatch, feats, [_shaft(body)])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5", modeled=True))
        assert out["volume_delta_cm3"] == -2.99


class TestPartialExtentIsReadBack:
    def test_a_partial_thread_that_stayed_full_length_is_error(self, monkeypatch):
        feats = FakeThreadFeatures(full_length=True)
        _wire(monkeypatch, feats, [_shaft()])
        res = mt.handler(faces=["h"], designation="M10x1.5", length=12)
        assert res["isError"] is True
        assert "full length" in res["message"] and "Thread1" in res["message"]

    def test_a_length_that_read_back_different_is_error(self, monkeypatch):
        feats = FakeThreadFeatures(length_cm=0.9)
        _wire(monkeypatch, feats, [_shaft()])
        res = mt.handler(faces=["h"], designation="M10x1.5", length=12)
        assert res["isError"] is True
        assert "length reads back" in res["message"] and "Thread1" in res["message"]

    def test_the_reported_length_comes_from_the_feature(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5", length=12, offset=2))
        assert out["length"] == 12 and out["offset"] == 2

    def test_a_modeled_thread_with_no_readable_volume_is_error(self, monkeypatch):
        body = BRepBody("Post", volume=None)
        feats = FakeThreadFeatures([body], volume_delta=-2.0)
        _wire(monkeypatch, feats, [_shaft(body)])
        res = mt.handler(faces=["h"], designation="M10x1.5", modeled=True)
        assert res["isError"] is True and "no proof" in res["message"]

    def test_a_modeled_thread_on_a_face_with_no_owning_body_is_error(self, monkeypatch):
        face = _cyl_face(radial=(1.0, 0.0, 0.0))
        face.body = None
        _wire(monkeypatch, FakeThreadFeatures(), [face])
        res = mt.handler(faces=["h"], designation="M10x1.5", modeled=True)
        assert res["isError"] is True and "find_geometry" in res["message"]


class TestInternalFlagIsReadOffTheCreatedFeature:
    """The bore/shaft classification's real gate is the PLATFORM: measured, add() validates the
    ThreadInfo's internal flag against the face and raises "input face's externality is different
    from what's in the ThreadInfo" on a mismatch, so a wrong classification is a loud failure and
    never a wrong thread. The read-back below is a cheap second witness over the same fact - these
    pin that the classification reaches the ThreadInfo, and that the witness still fires."""

    def test_a_cosmetic_bore_thread_reports_the_internal_flag_the_feature_carries(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_bore()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5"))
        assert out["internal"] is True
        assert out["modeled"] is False
        assert feats.catalog.created[0].isInternal is True

    def test_a_feature_reading_back_external_on_a_bore_is_an_error_not_a_silent_pass(
            self, monkeypatch):
        # The second witness, forced to fire: a feature answering EXTERNAL on bore faces. Live the
        # platform refuses that pairing at add() before any feature exists, so this state is not
        # reachable there - the check costs one read and must stay an error if it ever is.
        external = FakeThreadInfo(False, "ANSI Metric M Profile", "M10x1.5", "6g")
        _wire(monkeypatch, FakeThreadFeatures(feature_info=external), [_bore()])
        res = mt.handler(faces=["h"], designation="M10x1.5")
        assert res["isError"] is True
        assert "external" in res["message"] and "bores" in res["message"]


class TestHandIsReadOffTheCreatedFeature:
    def _reading(self, monkeypatch, hand):
        """A thread whose feature answers `hand` for isRightHanded whatever was asked, or does not
        answer at all for None. Injected: no such feature has been measured."""
        feats = FakeThreadFeatures()
        real_add = feats.add

        def add(inp):
            feature = real_add(inp)
            if hand is None:
                del feature.isRightHanded
            else:
                feature.isRightHanded = hand
            return feature

        feats.add = add
        _wire(monkeypatch, feats, [_shaft()])
        return feats

    @pytest.mark.parametrize("left_handed,got,asked", [(True, "right", "left"),
                                                       (False, "left", "right")])
    def test_a_hand_that_reads_back_the_other_way_is_an_error(self, monkeypatch, left_handed, got,
                                                              asked):
        feats = self._reading(monkeypatch, left_handed)
        msg = error_message(mt.handler(faces=["h"], designation="M10x1.5",
                                       left_handed=left_handed))
        assert f"reads back {got}-handed, not the requested {asked}-handed" in msg
        assert "was created" in msg and "Thread1" in msg and feats.added == 1

    def test_an_unreadable_hand_is_reported_null_not_refused(self, monkeypatch):
        self._reading(monkeypatch, None)
        out = payload(mt.handler(faces=["h"], designation="M10x1.5", left_handed=True))
        assert out["right_handed"] is None
        assert "right_handed could NOT be read back" in out["note"]


class TestPartialExtentFailsClosed:
    def test_an_unreadable_extent_is_an_error_not_an_assumed_success(self, monkeypatch):
        # isFullLength unreadable: the partial extent cannot be shown to have taken, so the call
        # fails CLOSED and names the feature to remove - never an ok() carrying the requested length
        feats = FakeThreadFeatures()
        feats.full_length = "unreadable"          # not a bool - what a proxy that stops answering gives
        _wire(monkeypatch, feats, [_shaft()])
        res = mt.handler(faces=["h"], designation="M10x1.5", length=12)
        assert res["isError"] is True
        assert "no proof it took" in res["message"] and "Thread1" in res["message"]

    def test_an_unreadable_length_parameter_is_an_error(self, monkeypatch):
        feats = FakeThreadFeatures(length_cm="unreadable")
        _wire(monkeypatch, feats, [_shaft()])
        res = mt.handler(faces=["h"], designation="M10x1.5", length=12)
        assert res["isError"] is True and "no proof it took" in res["message"]

    def test_a_thread_that_landed_at_the_wrong_end_is_an_error(self, monkeypatch):
        # threadLocation reads back the OTHER end: length and offset both check out, so this gate is
        # the only thing between a thread on the wrong end of the cylinder and a clean ok()
        import adsk.fusion
        feats = FakeThreadFeatures()
        real_add = feats.add

        def _add(inp):
            feature = real_add(inp)
            feature.threadLocation = adsk.fusion.ThreadLocations.LowEndThreadLocation
            return feature

        feats.add = _add
        _wire(monkeypatch, feats, [_shaft()])
        res = mt.handler(faces=["h"], designation="M10x1.5", length=12, location="high")
        assert res["isError"] is True
        assert "wrong end" in res["message"] and "high" in res["message"]

    def test_the_requested_end_that_took_is_reported(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5", length=12, location="low"))
        assert out["location"] == "low"


class TestAmbiguousDesignation:
    def test_a_designation_carried_by_several_types_discloses_the_others(self, monkeypatch):
        # the thread namespace is NOT unique, and the measured profiles that share a designation
        # build an identical ThreadInfo - so the pick stands and the alternatives are reported
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.25"))
        assert out["thread_type"] == "ANSI Metric M Profile"
        assert out["thread_type_alternatives"] == ["ANSI Metric M Profile", "ISO Metric profile"]

    def test_an_unambiguous_designation_reports_no_alternatives(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5"))
        assert out.get("thread_type_alternatives") is None

    def test_thread_type_picks_the_standard(self, monkeypatch):
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.25",
                                 thread_type="ISO Metric profile"))
        assert out["designation"] == "M10x1.25"
        assert feats.catalog.created[0].threadType == "ISO Metric profile"

    def test_a_thread_type_that_lacks_the_designation_is_refused(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        msg = error_message(mt.handler(faces=["h"], designation="M30x3.5",
                                       thread_type="ISO Metric profile"))
        assert "does not carry" in msg and "ANSI Metric M Profile" in msg

    def test_thread_class_picks_the_fit(self, monkeypatch):
        # 4g6g and 6g are different external FITS of the same thread - not interchangeable the way
        # the standards sharing a designation are, so the caller can name one
        feats = FakeThreadFeatures()
        _wire(monkeypatch, feats, [_shaft()])
        out = payload(mt.handler(faces=["h"], designation="M10x1.5", thread_class="6g"))
        assert out["thread_class"] == "6g"
        assert feats.catalog.created[0].threadClass == "6g"

    def test_an_unoffered_thread_class_is_refused(self, monkeypatch):
        _wire(monkeypatch, FakeThreadFeatures(), [_shaft()])
        msg = error_message(mt.handler(faces=["h"], designation="M10x1.5", thread_class="9z"))
        assert "not offered" in msg and "4g6g" in msg
