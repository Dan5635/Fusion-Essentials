"""Unit tests for ``drawing_add_symbol.py`` - one GD&T symbol placed on a view of the active drawing.

Covers the gate every add is judged by (the count grows by exactly one and the RETURNED object reads
the kind asked, since the sheet's collection reads every symbol as a datum identifier; a refused add
raises its reason on the next call, the count read), each action's input reaching its own factory
with its fields set, the {token} palette text, and the refusals made before any create. No live
Fusion.
"""

import types

import pytest

import adsk  # the mock package conftest installed at import time
import live_api_facts
from conftest import (FakeSheet, FakeView, error_message, load_tool, make_drawing,
                      make_drawing_session, payload)

sym = load_tool("drawing_add_symbol")


def _family(name, members):
    """A drawing enum family: the measured members once the sweep carries it, else these in order."""
    return live_api_facts.ENUMS.get("drawing." + name) or dict(zip(members, range(len(members))))


_CURVE_TYPES = _family("ViewCurveTypes", (
    "LineViewCurveType", "ArcViewCurveType", "CircleViewCurveType", "EllipseViewCurveType",
    "SplineViewCurveType", "PolylineViewCurveType", "UnknownViewCurveType"))
_SYMBOL_TYPES = _family("SymbolTypes", (
    "DatumIdentifierSymbolType", "FeatureControlFrameSymbolType", "SurfaceTextureSymbolType",
    "TaperSlopeSymbolType", "EdgeSymbolType"))
_PALETTE = _family("SymbolPaletteTypes", tuple(n + "SymbolPaletteType" for n in (
    "None", "Diameter", "PlusMinus", "Degree", "Square", "Counterbore", "Countersink", "Depth",
    "CircularSection", "CircularProjection", "NotEqual", "LowerDelta", "Section", "UpperLambda",
    "LowerLambda", "Delta", "Omega", "Number", "Squared", "Cubed", "OneQuarter", "OneHalf",
    "ThreeQuarters", "EnvelopeRequirement", "FreeStateCondition", "LeastMaterialRequirement",
    "MaximumMaterialRequirement", "ProjectedToleranceZone", "Between", "CommonZone",
    "MinorDiameter", "MajorDiameter", "PitchDiameter", "LineElement", "NotConvex",
    "AnyCrossSection", "MedianFeature", "FromTo", "UnequallyDisposedToleranceZone",
    "AnyLongitudinalSection", "ContactingFeature", "VariableDistance", "Point", "StraightLine",
    "Plane", "ForOrientationConstraintOnly", "UnequallyDisposedProfile", "NumberOfRow",
    "NoModifier", "AllAround", "AllOver", "TransmissionBand")))
_CHARACTERISTICS = _family("GeometricCharacteristicTypes", tuple(
    n + "GeometricCharacteristicType" for n in (
        "None", "Straightness", "Flatness", "Circularity", "Cylindricity", "ProfileOfLine",
        "ProfileOfSurface", "Angularity", "Perpendicularity", "Parallelism", "Position",
        "Concentricity", "Symmetry", "CircularRunout", "TotalRunout", "Coaxiality")))
_MODIFIERS = _family("SymbolApplicationModifierTypes", (
    "NoneSymbolApplicationModifierType", "AllAroundSymbolApplicationModifierType"))
_DIRECTIONS = _family("EdgeSymbolDirectionTypes", (
    "VerticalDirection", "HorizontalDirection", "UndefinedDirection", "NoDefinedDirection"))
_UNDEFINED_EDGES = _family("UndefinedEdgeSymbolTypes", (
    "NoneUndefinedEdgeSymbolType", "BurrOrPassingPermittedUndefinedEdgeSymbolType",
    "UndercutRequiredUndefinedEdgeSymbolType"))
_TAPERS = _family("TaperSlopeSymbolTypes", tuple(n + "TaperSlopeSymbolType" for n in (
    "TaperOneStandard", "SlopeOneStandard", "SlopeTwoStandard", "TaperOneFlipped",
    "SlopeOneFlipped", "SlopeTwoFlipped")))


class _Point:
    """A DrawingPoint whose coordinate is the pair given; DrawingPoint carries no shape dump."""

    def __init__(self, x, y):
        self.coordinate = types.SimpleNamespace(x=x, y=y)


class _Curve:
    """A ViewCurve: a type and four point accessors, None where live reads null; no shape dump."""

    def __init__(self, member, start, end, mid=None, center=None):
        self.type = _CURVE_TYPES[member]
        self.startPoint, self.endPoint = _Point(*start), _Point(*end)
        self.midPoint = _Point(*mid) if mid else None
        self.centerPoint = _Point(*center) if center else None


def _curves():
    """Curve 0 a 60-long line, curve 1 the vertical line meeting it, curve 2 a circle."""
    return [_Curve("LineViewCurveType", (0, 0), (60, 0), mid=(30, 0)),
            _Curve("LineViewCurveType", (60, 0), (60, 30), mid=(60, 15)),
            _Curve("CircleViewCurveType", (36, 20), (36, 20), center=(30, 20))]


class _Palette:
    """A SymbolPaletteList recording clear/append/appendText in call order; no shape dump."""

    def __init__(self):
        self.calls = []

    def clear(self):
        self.calls.append(("clear",))

    def append(self, symbol):
        self.calls.append(("symbol", symbol))

    def appendText(self, text):
        self.calls.append(("text", text))


class _PaletteSlot:
    """A SymbolPaletteList property: every read hands out a fresh list until one is assigned back,
    since the input applies a list only on assignment."""

    def __set_name__(self, owner, name):
        self.key = "_" + name

    def __get__(self, obj, owner=None):
        return self if obj is None else obj.__dict__.get(self.key) or _Palette()

    def __set__(self, obj, value):
        obj.__dict__[self.key] = value


class _Input:
    """A symbol creation input over the shared attachment fields; assigning a property the class
    does not declare raises. No shape dump."""

    FIELDS = ("viewCurve", "leaderPoints", "placementPoint")

    def __init__(self, **defaults):
        for name in _Input.FIELDS:
            setattr(self, name, None)
        for name, value in defaults.items():
            setattr(self, name, value)

    def __setattr__(self, name, value):
        if not name.startswith("_") and name not in _Input.FIELDS + type(self).FIELDS:
            raise AttributeError(f"{type(self).__name__} has no property {name}")
        object.__setattr__(self, name, value)


class _DatumInput(_Input):
    """DatumIdentifierInput; no shape dump."""
    FIELDS = ("identifier", "datumNotes", "threadNotes")
    datumNotes = _PaletteSlot()
    threadNotes = _PaletteSlot()

    def __init__(self):
        super().__init__(identifier="")


class _Section:
    """FeatureControlFrameSectionInput: a characteristic and five palette lists; no shape dump."""
    primaryTolerance = _PaletteSlot()
    secondaryTolerance = _PaletteSlot()
    primaryDatum = _PaletteSlot()
    secondaryDatum = _PaletteSlot()
    tertiaryDatum = _PaletteSlot()

    def __init__(self):
        self.geometricCharacteristic = _CHARACTERISTICS["NoneGeometricCharacteristicType"]


class _FrameInput(_Input):
    """FeatureControlFrameInput: firstFrame/secondFrame read-only; no shape dump."""
    FIELDS = ("isSecondFrameEnabled", "applicationModifier", "topNote", "bottomNote")
    topNote = _PaletteSlot()
    bottomNote = _PaletteSlot()
    firstFrame = property(lambda self: self._first)
    secondFrame = property(lambda self: self._second)

    def __init__(self):
        super().__init__(isSecondFrameEnabled=False,
                         applicationModifier=_MODIFIERS["NoneSymbolApplicationModifierType"])
        self._first, self._second = _Section(), _Section()


class _EdgeInput(_Input):
    """EdgeSymbolInput; no shape dump."""
    FIELDS = ("direction", "isAllAround", "isMajority", "isStandardLabelShown",
              "isUndefinedSizeAllowed", "undefinedEdgeType", "upperLimit", "lowerLimit")

    def __init__(self):
        super().__init__(direction=_DIRECTIONS["NoDefinedDirection"], isAllAround=False,
                         isMajority=False, isStandardLabelShown=False, isUndefinedSizeAllowed=False,
                         undefinedEdgeType=_UNDEFINED_EDGES["NoneUndefinedEdgeSymbolType"],
                         upperLimit="", lowerLimit="")


class _DeafEdgeInput(_EdgeInput):
    """An EdgeSymbolInput whose upperLimit assignment reads back empty; no shape dump."""
    upperLimit = property(lambda self: "", lambda self, value: None)


class _TaperInput(_Input):
    """TaperSlopeSymbolInput; no shape dump."""
    FIELDS = ("attachementCurve", "dimension", "taperSlopeSymbolType", "isTheoreticallyExact")

    def __init__(self):
        super().__init__(attachementCurve=None, dimension="", taperSlopeSymbolType=None,
                         isTheoreticallyExact=False)


class _Symbol:
    """A DrawingSymbol: isValid and symbolType only, as measured; no shape dump."""

    def __init__(self, member, valid=True):
        self.isValid = valid
        self.symbolType = _SYMBOL_TYPES[member]


class _Symbols:
    """Sheet.drawingSymbols: count, item and the four create/add pairs; no shape dump. Every item
    reads as a datum identifier, the object an add returns reads the kind added, and `refusal` is
    the message the NEXT count read raises after an add."""

    def __init__(self, count=0, grows=1, returns="symbol", reads_as=None, valid=True,
                 refusal=None, raises=None, input_null=False):
        self._items = [_Symbol("DatumIdentifierSymbolType") for _ in range(count)]
        self._grows, self._returns, self._reads_as, self._valid = grows, returns, reads_as, valid
        self._refusal, self._raises, self._input_null = refusal, raises, input_null
        self._pending = None
        self.inputs, self.calls = [], []

    @property
    def count(self):
        if self._pending:
            message, self._pending = self._pending, None
            raise RuntimeError(message)
        return len(self._items)

    def item(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def _create(self, cls):
        if self._input_null:
            return None
        self.inputs.append(cls())
        return self.inputs[-1]

    def createDatumIdentifierInput(self):
        return self._create(_DatumInput)

    def createFeatureControlFrameInput(self):
        return self._create(_FrameInput)

    def createEdgeSymbolInput(self):
        return self._create(_EdgeInput)

    def createTaperSlopeSymbolInput(self):
        return self._create(_TaperInput)

    def _add(self, member, name, inp):
        self.calls.append((name, inp))
        if self._raises:
            raise RuntimeError(self._raises)
        if self._refusal:
            self._pending = self._refusal
            return None
        self._items.extend(_Symbol("DatumIdentifierSymbolType") for _ in range(self._grows))
        return None if self._returns == "null" else _Symbol(self._reads_as or member, self._valid)

    def addDatumIdentifier(self, inp):
        return self._add("DatumIdentifierSymbolType", "addDatumIdentifier", inp)

    def addFeatureControlFrame(self, inp):
        return self._add("FeatureControlFrameSymbolType", "addFeatureControlFrame", inp)

    def addEdgeSymbol(self, inp):
        return self._add("EdgeSymbolType", "addEdgeSymbol", inp)

    def addTaperSlopeSymbol(self, inp):
        return self._add("TaperSlopeSymbolType", "addTaperSlopeSymbol", inp)


@pytest.fixture
def env(monkeypatch):
    """An active ISO drawing: one sheet, two views each holding _curves(), and a symbols
    collection; install() rebuilds it with another standard or collection knobs."""
    state = types.SimpleNamespace()
    monkeypatch.setattr(adsk.core.Point2D, "create", lambda x, y: (x, y))
    families = {name: types.SimpleNamespace(**members) for name, members in (
        ("ViewCurveTypes", _CURVE_TYPES), ("SymbolTypes", _SYMBOL_TYPES),
        ("SymbolPaletteTypes", _PALETTE), ("GeometricCharacteristicTypes", _CHARACTERISTICS),
        ("SymbolApplicationModifierTypes", _MODIFIERS), ("EdgeSymbolDirectionTypes", _DIRECTIONS),
        ("UndefinedEdgeSymbolTypes", _UNDEFINED_EDGES), ("TaperSlopeSymbolTypes", _TAPERS))}
    families["DrawingPoint"] = types.SimpleNamespace(create=lambda xy: ("placed",) + tuple(xy))

    def _install(standard="iso", symbols=True, **knobs):
        state.sheet = FakeSheet("Sheet1", views=[FakeView("view%d" % i, curves=_curves())
                                                 for i in range(2)])
        state.symbols = _Symbols(**knobs)
        if symbols:
            state.sheet.drawingSymbols = state.symbols
        make_drawing_session(monkeypatch, make_drawing(sheets=[state.sheet], standard=standard),
                             **families)
        return state

    _install()
    state.install = _install
    return state


_REQUESTS = {
    "datum_identifier": {"identifier": "A"},
    "feature_control_frame": {"frames": ["flatness|0.05"]},
    "edge": {"upper_limit": "+0.5", "lower_limit": "-0.3"},
    "taper_slope": {"second_curve": 1, "dimension": "1:10"},
}


def _add(action="datum_identifier", **args):
    """One request on view 0 leadered from curve 0's mid to [30, -12]; `args` varies it."""
    request = {"action": action, "view": 0, "attach": "0:mid", "placement": [30, -12],
               **_REQUESTS[action]}
    request.update(args)
    return sym.handler(**{k: v for k, v in request.items() if v is not None})


class TestCountGate:
    def test_a_count_that_does_not_move_is_an_error(self, env):
        env.install(count=2, grows=0)
        message = error_message(_add())
        assert "count reads 2 (2 before)" in message and "not confirmed" in message

    def test_a_count_that_grows_by_two_is_an_error(self, env):
        env.install(grows=2)
        assert "count reads 2 (0 before)" in error_message(_add())

    @pytest.mark.parametrize("knobs,said", [
        ({"returns": "null"}, "returned null"),
        ({"reads_as": "DatumIdentifierSymbolType"}, "kind datum_identifier"),
        ({"valid": False}, "isValid False"),
    ])
    def test_a_null_or_wrong_kind_return_is_an_error_even_when_the_count_grew(self, env, knobs,
                                                                              said):
        env.install(**knobs)
        message = error_message(_add("feature_control_frame"))
        assert said in message and "count reads 1 (0 before)" in message

    def test_a_count_read_that_raises_after_the_add_is_that_adds_refusal(self, env):
        env.install(count=1, refusal="3 : viewCurve must be set.")
        message = error_message(_add())
        assert "addDatumIdentifier was refused on view 0: 3 : viewCurve must be set." in message
        assert "re-reads 1 (1 before)" in message

    def test_an_add_that_raises_reports_the_count_it_left(self, env):
        env.install(raises="3 : invalid input")
        message = error_message(_add("edge"))
        assert "addEdgeSymbol raised on view 0: 3 : invalid input" in message
        assert "reads 0 (0 before)" in message

    def test_a_sheet_whose_symbols_do_not_read_is_refused_before_any_create(self, env):
        env.install(symbols=False)
        assert "drawingSymbols.count did not read" in error_message(_add())
        assert env.symbols.inputs == []

    def test_a_factory_that_answers_no_input_is_an_error_naming_action_and_standard(self, env):
        env.install(input_null=True)
        message = error_message(_add("taper_slope"))
        assert "action='taper_slope' on this iso drawing" in message
        assert env.symbols.calls == []

    def test_declared_returns_are_present(self, env):
        out = payload(_add())
        for spec in sym.RETURNS:
            assert spec.assert_present(out) == "", spec.assert_present(out)


class TestActions:
    def test_datum_identifier_lands_with_its_identifier_curve_and_leader(self, env):
        out = payload(_add(datum_note="{diameter}10"))
        (name, inp), = env.symbols.calls
        curve = env.sheet.views.item(0).viewCurves.item(0)
        assert name == "addDatumIdentifier" and inp.identifier == "A"
        assert inp.viewCurve is curve
        assert inp.leaderPoints == [("placed", 30, 0), ("placed", 30.0, -12.0)]
        assert inp.placementPoint is inp.leaderPoints[-1]
        assert inp.datumNotes.calls == [
            ("clear",), ("symbol", _PALETTE["DiameterSymbolPaletteType"]), ("text", "10")]
        assert (out["added"], out["action"], out["type_read"]) == (True, "datum_identifier",
                                                                   "datum_identifier")
        assert (out["symbol_count_before"], out["symbol_count_after"]) == (0, 1)
        assert (out["attach"], out["placement"], out["placement_unit"]) == ("0:mid",
                                                                            [30.0, -12.0], "mm")

    @pytest.mark.parametrize("first", ["position|{diameter}0.2{maximum_material_requirement}|A|B",
                                       "position| {dia}0.2{M} |A|B"])
    def test_a_feature_control_frame_sets_both_frames_its_notes_and_all_around(self, env, first):
        out = payload(_add("feature_control_frame", frames=[first, "parallelism|0.1|A"],
                           top_note="2 SURFACES", bottom_note="AFTER PLATING", all_around=True))
        (name, inp), = env.symbols.calls
        one, two = inp.firstFrame, inp.secondFrame
        assert name == "addFeatureControlFrame" and inp.isSecondFrameEnabled is True
        assert one.geometricCharacteristic == _CHARACTERISTICS[
            "PositionGeometricCharacteristicType"]
        assert one.primaryTolerance.calls == [
            ("clear",), ("symbol", _PALETTE["DiameterSymbolPaletteType"]), ("text", "0.2"),
            ("symbol", _PALETTE["MaximumMaterialRequirementSymbolPaletteType"])]
        assert [one.primaryDatum.calls, one.secondaryDatum.calls] == [
            [("clear",), ("text", "A")], [("clear",), ("text", "B")]]
        assert one.tertiaryDatum.calls == [] and one.secondaryTolerance.calls == []
        assert two.geometricCharacteristic == _CHARACTERISTICS[
            "ParallelismGeometricCharacteristicType"]
        assert two.primaryTolerance.calls == [("clear",), ("text", "0.1")]
        assert two.primaryDatum.calls == [("clear",), ("text", "A")]
        assert inp.topNote.calls == [("clear",), ("text", "2 SURFACES")]
        assert inp.bottomNote.calls == [("clear",), ("text", "AFTER PLATING")]
        assert inp.applicationModifier == _MODIFIERS["AllAroundSymbolApplicationModifierType"]
        assert out["type_read"] == "feature_control_frame"

    def test_one_frame_leaves_the_second_disabled(self, env):
        payload(_add("feature_control_frame"))
        (_name, inp), = env.symbols.calls
        assert inp.isSecondFrameEnabled is False
        assert inp.secondFrame.primaryTolerance.calls == []

    def test_an_edge_symbol_sets_its_limits_direction_and_flags(self, env):
        out = payload(_add("edge", direction="undefined", all_around=True, majority=True,
                           standard_label=False, undefined_size=True,
                           undefined_edge="undercut_required"))
        (name, inp), = env.symbols.calls
        assert name == "addEdgeSymbol"
        assert (inp.upperLimit, inp.lowerLimit) == ("+0.5", "-0.3")
        assert inp.direction == _DIRECTIONS["UndefinedDirection"]
        assert (inp.isAllAround, inp.isMajority, inp.isStandardLabelShown,
                inp.isUndefinedSizeAllowed) == (True, True, False, True)
        assert inp.undefinedEdgeType == _UNDEFINED_EDGES["UndercutRequiredUndefinedEdgeSymbolType"]
        assert out["type_read"] == "edge"

    def test_a_taper_slope_hands_the_second_line_its_dimension_shape_and_exact_flag(self, env):
        out = payload(_add("taper_slope", symbol="slope_1", theoretically_exact=True))
        (name, inp), = env.symbols.calls
        lines = env.sheet.views.item(0).viewCurves
        assert name == "addTaperSlopeSymbol"
        assert inp.viewCurve is lines.item(0) and inp.attachementCurve is lines.item(1)
        assert (inp.dimension, inp.isTheoreticallyExact) == ("1:10", True)
        assert inp.taperSlopeSymbolType == _TAPERS["SlopeOneStandardTaperSlopeSymbolType"]
        assert out["type_read"] == "taper_slope"

    @pytest.mark.parametrize("args,said", [
        ({"second_curve": 2}, "'second_curve' curve 2 reads as circle"),
        ({"attach": "2:center"}, "'attach' curve 2 reads as circle"),
        ({"second_curve": 0}, "two different lines"),
    ])
    def test_a_taper_slope_takes_two_different_lines(self, env, args, said):
        assert said in error_message(_add("taper_slope", **args))
        assert env.symbols.inputs == []


class TestRefusedBeforeAnyCreate:
    @pytest.mark.parametrize("text,said", [
        ("{dai}0.2", "{dai} is no symbol token. Use {dia} {M} {L}"),
        ("{T}0.2", "or a SymbolPaletteTypes member name in snake_case"),
        ("{m}0.2", "{m} is no symbol token"),
        ("{counterbore}0.2", "does not support {centerline}, {position}, {counterbore}"),
        ("{position}", "(got {position})"),
        ("0.2;A", "holds a ';'"),
        ("{diameter 0.2", "unmatched brace"),
    ])
    def test_a_palette_text_fault_is_refused_naming_the_field(self, env, text, said):
        message = error_message(_add("feature_control_frame", frames=["flatness|" + text]))
        assert said in message and "frames[0] tolerance" in message
        assert env.symbols.inputs == [] and env.symbols.calls == []

    def test_a_semicolon_in_plain_text_is_refused_too(self, env):
        assert "'identifier' holds a ';'" in error_message(_add(identifier="A;B"))
        assert env.symbols.inputs == []

    @pytest.mark.parametrize("frames,said", [
        (["flatness"], "frames[0] 'flatness' needs 2 to 6 '|'-separated fields"),
        (["flatness|0.1|A|B|C|0.2|D"], "'flatness|0.1|A|B|C|0.2|D' needs 2 to 6"),
        ([{"characteristic": "flatness"}], "needs 2 to 6"),
        (["roundness|0.1"], "'roundness|0.1': the characteristic must be one of: straightness"),
        (["flatness| "], "'flatness| ' needs a tolerance"),
        (["flatness|0.1"] * 3, "1 or 2 strings"),
    ])
    def test_a_malformed_frame_is_refused_naming_its_text(self, env, frames, said):
        assert said in error_message(_add("feature_control_frame", frames=frames))
        assert env.symbols.inputs == []

    def test_six_fields_and_empty_middle_ones_are_read_in_order(self, env):
        env.install(standard="asme")
        payload(_add("feature_control_frame", frames=["position|0.2|A||C|0.1"]))
        (_name, inp), = env.symbols.calls
        one = inp.firstFrame
        assert [one.primaryDatum.calls, one.secondaryDatum.calls, one.tertiaryDatum.calls,
                one.secondaryTolerance.calls] == [[("clear",), ("text", "A")], [],
                                                  [("clear",), ("text", "C")],
                                                  [("clear",), ("text", "0.1")]]

    @pytest.mark.parametrize("standard,read", [("iso", "iso"), ("unset", "unread")])
    def test_secondary_tolerance_is_refused_unless_the_drawing_reads_asme(self, env, standard,
                                                                          read):
        env.install(standard=standard)
        message = error_message(_add("feature_control_frame", frames=["position|0.2|A|||0.1"]))
        assert "'position|0.2|A|||0.1' carries a secondary tolerance" in message
        assert f"ASME drawings only; this drawing's standard reads {read}" in message
        assert env.symbols.inputs == []

    @pytest.mark.parametrize("args", [{"direction": "diagonal"}, {"undefined_edge": "sharp"},
                                      {"action": "taper_slope", "symbol": "wedge"}])
    def test_a_choice_outside_its_values_is_refused_naming_them(self, env, args):
        name, value = next((k, v) for k, v in args.items() if k != "action")
        message = error_message(_add(**{"action": "edge", **args}))
        assert f"'{name}' must be one of:" in message and f"(got '{value}')" in message
        assert env.symbols.inputs == []

    @pytest.mark.parametrize("standard,said", [("asme", "standard reads asme"),
                                               ("unset", "standard reads unread")])
    def test_an_edge_symbol_is_refused_unless_the_drawing_reads_iso(self, env, standard, said):
        env.install(standard=standard)
        assert said in error_message(_add("edge"))
        assert env.symbols.inputs == []

    @pytest.mark.parametrize("action,args,stray", [
        ("datum_identifier", {"frames": ["flatness|1"]}, "frames"),
        ("feature_control_frame", {"identifier": "A"}, "identifier"),
        ("edge", {"second_curve": 1}, "second_curve"),
        ("datum_identifier", {"all_around": False}, "all_around"),
    ])
    def test_an_input_the_action_does_not_read_is_refused(self, env, action, args, stray):
        assert f"does not take {stray}" in error_message(_add(action, **args))
        assert env.symbols.inputs == []


class TestInputThatDoesNotTake:
    @pytest.mark.parametrize("where", ["append", "assignment"])
    def test_a_palette_list_that_raises_is_an_error_naming_the_field(self, env, monkeypatch,
                                                                     where):
        def refuse(*_args):
            raise RuntimeError("3 : palette refused")

        monkeypatch.setattr(_Palette if where == "append" else _PaletteSlot,
                            "append" if where == "append" else "__set__", refuse)
        message = error_message(_add("feature_control_frame", frames=["position|{dia}0.2|A"]))
        assert "Could not set frames[0].primaryTolerance: 3 : palette refused" in message
        assert env.symbols.calls == []

    def test_a_field_whose_read_back_is_unchanged_is_an_error_and_nothing_is_added(
            self, env, monkeypatch):
        monkeypatch.setattr(env.symbols, "createEdgeSymbolInput",
                            lambda: env.symbols._create(_DeafEdgeInput))
        message = error_message(_add("edge"))
        assert "Setting 'upper_limit' did not take" in message and "Nothing was added" in message
        assert env.symbols.calls == []


class TestLeader:
    def test_attach_and_placement_always_send_two_points_and_bends_go_between(self, env):
        payload(_add())
        payload(_add(bends=[[40, -5], [35, -9]]))
        (_n1, bare), (_n2, bent) = env.symbols.calls
        assert len(bare.leaderPoints) == 2
        assert bent.leaderPoints == [("placed", 30, 0), ("placed", 40.0, -5.0),
                                     ("placed", 35.0, -9.0), ("placed", 30.0, -12.0)]

    def test_digit_strings_and_json_strings_are_read_as_what_they_spell(self, env):
        # A client whose cached schema predates a reload sends integers and arrays as text.
        out = payload(_add("taper_slope", view="1", second_curve="1", bends="[[40, -5]]",
                           placement="[30, -12]"))
        (_name, inp), = env.symbols.calls
        assert out["view_index"] == 1 and out["bends"] == [[40.0, -5.0]]
        assert inp.attachementCurve is env.sheet.views.item(1).viewCurves.item(1)
        assert out["placement"] == [30.0, -12.0]
        payload(_add("feature_control_frame", frames='["flatness|0.05"]'))
        assert env.symbols.calls[-1][1].firstFrame.primaryTolerance.calls == [("clear",),
                                                                             ("text", "0.05")]

    @pytest.mark.parametrize("args,said", [
        ({"attach": "0:corner"}, "'<curve_index>:<start|end|mid|center>'"),
        ({"attach": "2:mid"}, "has no mid point"),
        ({"placement": [30]}, "needs 'placement' as [x, y] in sheet mm"),
        ({"bends": [[1, 2, 3]]}, "needs 'bends[0]' as [x, y]"),
        ({"view": 2}, "legal indices are 0 to 1"),
        ({"view": "one"}, "(got 'one')"),
    ])
    def test_a_bad_attachment_is_refused_before_any_create(self, env, args, said):
        assert said in error_message(_add(**args))
        assert env.symbols.inputs == []


class TestTables:
    def test_every_palette_member_but_none_and_the_unsupported_is_a_token(self):
        tokens = sym._drawing_common.PALETTE_TOKENS
        left_out = {n + "SymbolPaletteType" for n in ("None", "Centerline", "Position",
                                                      "Counterbore")}
        assert set(tokens.values()) == set(_PALETTE) - left_out
        assert not set(sym._drawing_common.PALETTE_UNSUPPORTED) & set(tokens)
        assert tokens["least_material_requirement"] == "LeastMaterialRequirementSymbolPaletteType"
        assert (tokens["dia"], tokens["M"], tokens["U"], tokens["csk"]) == (
            "DiameterSymbolPaletteType", "MaximumMaterialRequirementSymbolPaletteType",
            "UnequallyDisposedProfileSymbolPaletteType", "CountersinkSymbolPaletteType")

    def test_every_choice_names_a_member_of_its_family(self):
        stems = ["".join(w.capitalize() for w in k.split("_")) for k in sym._CHARACTERISTICS]
        assert all(s + "GeometricCharacteristicType" in _CHARACTERISTICS for s in stems)
        assert len(stems) == len(_CHARACTERISTICS) - 1
        for table, family in ((sym._DIRECTIONS, _DIRECTIONS), (sym._UNDEFINED_EDGES,
                              _UNDEFINED_EDGES), (sym._TAPER_SYMBOLS, _TAPERS),
                              (sym._KIND_LABELS, _SYMBOL_TYPES)):
            assert sorted(table.values()) == sorted(family), table
