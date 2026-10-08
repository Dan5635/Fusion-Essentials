"""Focused measured fillet edge-set construction and retained-readback cases."""

import types

import pytest

from conftest import FakeValueInput, load_tool


edges = load_tool("_edge_common")


def _input_cm(value):
    return value.realValue


class _Collection:
    def __init__(self, values=()):
        self.values = list(values)

    def add(self, value):
        self.values.append(value)

    @property
    def count(self):
        return len(self.values)

    def item(self, index):
        return self.values[index]

    def __iter__(self):
        return iter(self.values)


class _HoleCollection(_Collection):
    def __init__(self, values, fail_index):
        super().__init__(values)
        self.fail_index = fail_index

    def item(self, index):
        if index == self.fail_index:
            raise RuntimeError("measured member getter failure")
        return super().item(index)


class _EdgeSetInput:
    def __init__(self, edges_, radius_cm=None, start_cm=None, end_cm=None, flip=False,
                 continuity=None, setter_result=True, ignore_flip=False):
        self.edges = _Collection(edges_)
        self.radius_cm = radius_cm
        self.start_cm = start_cm
        self.end_cm = end_cm
        self.isFlipped = flip
        self.continuity = continuity
        self.setter_result = setter_result
        self.ignore_flip = ignore_flip
        self.tangencyWeight = FakeValueInput(1.0)
        self.isTangentChain = True
        self.radius = types.SimpleNamespace(value=radius_cm)
        self.startRadius = types.SimpleNamespace(value=start_cm)
        self.endRadius = types.SimpleNamespace(value=end_cm)
        self.offsetOne = types.SimpleNamespace(value=start_cm)
        self.offsetTwo = types.SimpleNamespace(value=end_cm)
        self.midPositions = _Collection()
        self.midRadii = _Collection()

    def _set_continuity(self, value):
        if self.setter_result is True:
            self.continuity = value
        return self.setter_result

    def _set_isFlipped(self, value):
        if not self.ignore_flip:
            self.isFlipped = value
        return self.setter_result

    def setMidRadii(self, radii, positions):
        self.midRadii = _Collection(radii)
        self.midPositions = _Collection(positions)
        return self.setter_result


class _EdgeSetInputs:
    def __init__(self, *, asym=None, constant=None, variable=None):
        self.asym = asym
        self.constant = constant
        self.variable = variable
        self.created = []

    def addAsymmetricRadiusEdgeSet(self, edge_collection, one, two, tangent):
        result = self.asym or _EdgeSetInput(list(edge_collection), start_cm=_input_cm(one),
                                            end_cm=_input_cm(two))
        self.created.append(("asymmetric", list(edge_collection), one, two, tangent, result))
        return result

    def addConstantRadiusEdgeSet(self, edge_collection, radius, tangent):
        result = self.constant or _EdgeSetInput(list(edge_collection), radius_cm=_input_cm(radius))
        result.isTangentChain = tangent
        self.created.append(("constant", list(edge_collection), radius, tangent, result))
        return result

    def addVariableRadiusEdgeSet(self, edge_collection, start, end, tangent):
        result = self.variable or _EdgeSetInput(list(edge_collection), start_cm=_input_cm(start),
                                                end_cm=_input_cm(end))
        result.isTangentChain = tangent
        self.created.append(("variable", list(edge_collection), start, end, tangent, result))
        return result


class _NativeFeatureSet:
    @staticmethod
    def cast(value):
        return value


class _MissingMidPositions(_EdgeSetInput):
    @property
    def midPositions(self):
        raise RuntimeError("measured midPositions getter failure")

    @midPositions.setter
    def midPositions(self, value):
        self._mid_positions = value


def _edge(name, owner="owner"):
    component = types.SimpleNamespace(key=owner)
    return types.SimpleNamespace(name=name, key=name,
                                 body=types.SimpleNamespace(parentComponent=component))


def _common_patches(monkeypatch):
    monkeypatch.setattr(edges._common, "native_identity",
                        lambda entity: (entity.key, entity.body.parentComponent.key))
    monkeypatch.setattr(edges._common, "same_component",
                        lambda one, two: one.key == two.key)
    monkeypatch.setattr(edges._common, "rolled_to", lambda _d, _f, read, _s: (read(), None))
    monkeypatch.setattr(edges._inputs, "length_value_input",
                        lambda raw, _k, _d, _label: (FakeValueInput(float(raw) * 0.1),
                                                     float(raw) * 0.1, None))
    monkeypatch.setattr(edges.adsk.core.ObjectCollection, "create", _Collection, raising=False)
    monkeypatch.setattr(edges.adsk.core.ValueInput, "createByReal", FakeValueInput, raising=False)
    monkeypatch.setattr(edges.adsk.fusion, "AsymmetricFilletEdgeSet",
                        _NativeFeatureSet, raising=False)
    monkeypatch.setattr(edges.adsk.fusion, "ConstantRadiusFilletEdgeSet",
                        _NativeFeatureSet, raising=False)
    monkeypatch.setattr(edges.adsk.fusion, "VariableRadiusFilletEdgeSet",
                        _NativeFeatureSet, raising=False)


def _feature_set(edge_list, *, kind="constant", radius=None, one=None, two=None,
                 flip=False, continuity=1, chain=True):
    out = _EdgeSetInput(edge_list, radius_cm=radius, start_cm=one, end_cm=two,
                        flip=flip, continuity=continuity)
    out.isTangentChain = chain
    if kind == "variable":
        out.startRadius = types.SimpleNamespace(value=one)
        out.endRadius = types.SimpleNamespace(value=two)
    if kind == "asymmetric":
        out.offsetOne = types.SimpleNamespace(value=one)
        out.offsetTwo = types.SimpleNamespace(value=two)
    return out


def test_asymmetric_flip_setter_echo_cannot_hide_an_ignored_flip(monkeypatch):
    _common_patches(monkeypatch)
    edge = _edge("e1")
    added = _EdgeSetInput(list([edge]), start_cm=0.1, end_cm=0.2, flip=False,
                          ignore_flip=True)
    fi = types.SimpleNamespace(edgeSetInputs=_EdgeSetInputs(asym=added))
    expected, err = edges._add_measured_edge_sets(
        fi, object(), {"type": "asymmetric", "end_radius": 2}, _Collection([edge]),
        FakeValueInput(0.1), 0.1, "mm", 0.1, True, None, True, None)
    assert expected is None
    assert "retained flipped=False" in err


@pytest.mark.parametrize("kind", ["constant", "variable"])
def test_continuity_requires_exact_setter_success_and_input_readback(monkeypatch, kind):
    _common_patches(monkeypatch)
    edge = _edge("e1")
    added = _EdgeSetInput([edge], radius_cm=0.1, start_cm=0.1, end_cm=0.2)
    fi = types.SimpleNamespace(edgeSetInputs=_EdgeSetInputs(constant=added, variable=added))
    variant = ({"type": "variable", "end_radius": 2, "positions": [0.5], "radii": [1.5]}
               if kind == "variable" else None)
    expected, err = edges._add_measured_edge_sets(
        fi, object(), variant, _Collection([edge]), FakeValueInput(0.1), 0.1, "mm", 0.1,
        True, "curvature", False, None)
    assert err is None
    assert expected[0]["continuity_input"] == edges.adsk.fusion.SurfaceContinuityTypes.CurvatureSurfaceContinuityType
    assert expected[0]["tangency_weight_input"]["real_value"] == 1.0
    assert added.continuity == edges.adsk.fusion.SurfaceContinuityTypes.CurvatureSurfaceContinuityType
    if kind == "variable":
        assert added.midPositions.item(0).realValue == 0.5
        assert added.midRadii.item(0).realValue == pytest.approx(0.15)
        retained = _feature_set([edge], kind="variable", one=0.1, two=0.2,
                                continuity=expected[0]["continuity_input"])
        retained.midPositions = _Collection([types.SimpleNamespace(value=0.5)])
        retained.midRadii = _Collection([types.SimpleNamespace(value=0.15)])
        rows, read_error = edges._read_measured_edge_sets(
            object(), types.SimpleNamespace(name="VariableFillet", edgeSets=_Collection([retained])),
            expected)
        assert read_error is None and rows[0]["continuity_verified"] is True

    added.setter_result = None
    no_midpoints_variant = ({"type": "variable", "end_radius": 2, "positions": [], "radii": []}
                            if kind == "variable" else variant)
    expected, err = edges._add_measured_edge_sets(
        fi, object(), no_midpoints_variant, _Collection([edge]), FakeValueInput(0.1), 0.1, "mm", 0.1,
        True, "curvature", False, None)
    assert expected is None
    assert "setter returned None" in err


def test_mixed_sets_compare_each_retained_radius_and_edge_identity(monkeypatch):
    _common_patches(monkeypatch)
    one, two = _edge("one"), _edge("two")
    first_input = _EdgeSetInput([one], radius_cm=0.1)
    second_input = _EdgeSetInput([two], radius_cm=0.2)
    inputs = _EdgeSetInputs(constant=first_input)
    inputs.constant = None
    fi = types.SimpleNamespace(edgeSetInputs=inputs)
    specs = [
        {"fillet_type": "constant", "edges": [one], "radius": 1,
         "tangent_chain": True, "continuity": None},
        {"fillet_type": "constant", "edges": [two], "radius": 2,
         "tangent_chain": True, "continuity": None},
    ]
    expected, err = edges._add_measured_edge_sets(
        fi, object(), {"type": "edge_sets"}, _Collection([one, two]), None, None,
        "mm", 0.1, True, None, False, specs)
    assert err is None and len(expected) == 2
    feature = types.SimpleNamespace(name="Fillet1", edgeSets=_Collection([
        _feature_set([one], radius=0.1), _feature_set([two], radius=0.2)]))
    rows, err = edges._read_measured_edge_sets(object(), feature, expected)
    assert err is None
    assert [row["edges_count"] for row in rows] == [1, 1]
    assert [row["radius_cm"] for row in rows] == pytest.approx([0.1, 0.2])

    feature.edgeSets = _Collection([_feature_set([one], radius=0.2),
                                    _feature_set([two], radius=0.1)])
    rows, err = edges._read_measured_edge_sets(object(), feature, expected)
    assert rows is None and "expected 0.1 cm" in err

    foreign = _edge("one", "foreign-owner")
    feature.edgeSets = _Collection([_feature_set([foreign], radius=0.1),
                                    _feature_set([two], radius=0.2)])
    rows, err = edges._read_measured_edge_sets(object(), feature, expected)
    assert rows is None and "different or unreadable edge identity set" in err


def test_mixed_sets_refuse_cross_owner_before_any_constructor(monkeypatch):
    _common_patches(monkeypatch)
    one, two = _edge("one", "left"), _edge("two", "right")
    inputs = _EdgeSetInputs()
    specs = [{"fillet_type": "constant", "edges": [one], "radius": 1},
             {"fillet_type": "constant", "edges": [two], "radius": 2}]
    expected, err = edges._add_measured_edge_sets(
        types.SimpleNamespace(edgeSetInputs=inputs), object(), {"type": "edge_sets"},
        _Collection([one, two]), None, None, "mm", 0.1, True, None, False, specs)
    assert expected is None
    assert "different component" in err
    assert inputs.created == []


def test_missing_feature_set_readback_reports_retained_feature_remedy(monkeypatch):
    _common_patches(monkeypatch)
    feature = types.SimpleNamespace(name="FilletKept")
    expected = [{"type": "constant", "identities": [("e1", "doc")]}]
    rows, err = edges._read_measured_edge_sets(object(), feature, expected)
    assert rows is None
    assert "FilletKept" in err
    assert "design_get" in err and "design_delete_feature" in err


def test_non_finite_radius_readback_is_a_mismatch_not_a_match(monkeypatch):
    _common_patches(monkeypatch)
    edge = _edge("e1")
    expected = [{"type": "constant", "edges": [edge], "identities": [("e1", "owner")],
                 "radius_cm": 0.1, "tangent_chain": True, "continuity_requested": None}]
    feature = types.SimpleNamespace(name="FilletNaN", edgeSets=_Collection([
        _feature_set([edge], radius=float("nan"))]))
    rows, err = edges._read_measured_edge_sets(object(), feature, expected)
    assert rows is None and "radius reads None" in err


def test_non_finite_asymmetric_offset_readback_is_refused(monkeypatch):
    _common_patches(monkeypatch)
    edge = _edge("e1")
    expected = [{"type": "asymmetric", "edges": [edge], "identities": [("e1", "owner")],
                 "offset_one_cm": 0.1, "offset_two_cm": 0.2, "flipped_requested": False,
                 "tangent_chain": True}]
    feature_set = _feature_set([edge], kind="asymmetric", one=float("nan"), two=0.2)
    feature = types.SimpleNamespace(name="AsymmetricNaN", edgeSets=_Collection([feature_set]))
    rows, err = edges._read_measured_edge_sets(object(), feature, expected)
    assert rows is None and "offset_one_cm reads None" in err


def test_non_finite_intermediate_radius_readback_is_refused(monkeypatch):
    _common_patches(monkeypatch)
    edge = _edge("e1")
    expected = [{"type": "variable", "edges": [edge], "identities": [("e1", "owner")],
                 "radius_cm": 0.1, "end_radius_cm": 0.2, "positions": [0.5],
                 "radii_cm": [0.15], "tangent_chain": True}]
    feature_set = _feature_set([edge], kind="variable", one=0.1, two=0.2)
    feature_set.midPositions = _Collection([types.SimpleNamespace(value=0.5)])
    feature_set.midRadii = _Collection([types.SimpleNamespace(value=float("nan"))])
    feature = types.SimpleNamespace(name="VariableNaN", edgeSets=_Collection([feature_set]))
    rows, err = edges._read_measured_edge_sets(object(), feature, expected)
    assert rows is None and "intermediate radii do not match" in err


def test_unreadable_mid_position_collection_cannot_match_a_requested_list(monkeypatch):
    _common_patches(monkeypatch)
    edge = _edge("e1")
    expected = [{"type": "variable", "edges": [edge], "identities": [("e1", "owner")],
                 "radius_cm": 0.1, "end_radius_cm": 0.2, "positions": [0.5],
                 "radii_cm": [0.15], "tangent_chain": True}]
    feature_set = _MissingMidPositions([edge], start_cm=0.1, end_cm=0.2)
    feature_set.midRadii = _Collection([types.SimpleNamespace(value=0.15)])
    feature = types.SimpleNamespace(name="VariableUnreadable", edgeSets=_Collection([feature_set]))
    rows, err = edges._read_measured_edge_sets(object(), feature, expected)
    assert rows is None and "midPositions collection did not read" in err


def test_hole_in_retained_edge_census_cannot_be_skipped(monkeypatch):
    _common_patches(monkeypatch)
    one, two = _edge("one"), _edge("two")
    expected = [{"type": "constant", "edges": [one, two],
                 "identities": [("one", "owner"), ("two", "owner")],
                 "radius_cm": 0.1, "tangent_chain": True}]
    feature_set = _feature_set([one, two], radius=0.1)
    feature_set.edges = _HoleCollection([one, two], fail_index=1)
    feature = types.SimpleNamespace(name="FilletWithHole", edgeSets=_Collection([feature_set]))
    rows, err = edges._read_measured_edge_sets(object(), feature, expected)
    assert rows is None and "edges item {} did not read".format(1) in err


def test_non_finite_or_boolean_input_lengths_are_refused(monkeypatch):
    _common_patches(monkeypatch)
    for value in (float("nan"), float("inf"), True):
        resolved, cm, err = edges._length_spec(value, "mm", object(), "radius")
        assert resolved is None and cm is None and err


def test_non_finite_standalone_measured_size_stops_before_feature_input(monkeypatch):
    _common_patches(monkeypatch)
    made = []
    monkeypatch.setattr(edges._common, "design", lambda: object())
    monkeypatch.setattr(edges._common, "target_component", lambda _design: object())
    monkeypatch.setattr(edges._inputs, "looks_like_expression", lambda _value: False)
    monkeypatch.setattr(edges._inputs, "length_value_input",
                        lambda *_args: (FakeValueInput(float("nan")), float("nan"), None))

    class _FeatureOps:
        def createInput(self):
            made.append(True)

    component = types.SimpleNamespace(features=types.SimpleNamespace(
        filletFeatures=_FeatureOps()))
    monkeypatch.setattr(edges._common, "target_component", lambda _design: component)
    result = edges._apply("fillet", "", float("nan"), "mm", "", variant={"type": "asymmetric",
                                                                              "end_radius": 2})
    assert result["isError"] is True
    assert made == []
