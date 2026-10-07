"""Unit tests for ``doc_insert_derive.py``: the source-open precondition, the SOURCE-side name
resolvers (component/body - exact match, miss lists names, ambiguity refused), the scoping that turns
names into sourceEntities, the landed read-back (derived_components + body counts, empty-landing is an
error), and the inline verify (healthState / documentReference.isOutOfDate / isDerived / params).

The cloud URN resolution is covered by test_doc_insert_occurrence.py (the shared _resolve_data_file);
here it is monkeypatched so these tests stay offline. Occurrence resolution (into_component) goes
through the real _inputs.OccurrenceRef kind against a fake design (dual seam patched). Every type
carrying a live shape dump uses its shared conftest fake; the DeriveFeature family has none, so it
keeps the bespoke doubles below.
"""

import json
from types import SimpleNamespace

import adsk.fusion
import pytest

from conftest import (BRepBody, FakeApplication, FakeDataFile, FakeDocumentReference, FakeDocuments,
                      FakeFeatures, FakeFusionDocument, FakeOccurrence, FakeProducts,
                      FakeTimeline, FakeTimelineObject, FakeUserParameter, FakeUserParameters,
                      MakeComp, MakeDesign, _NamedCollection, load_tool, make_occurrence)

io = load_tool("doc_insert_derive")


# ── destination-side fakes ───────────────────────────────────────────────────────────────────────

def FakeBody(name, is_derived=True):
    """One body a derive landed - isDerived is the flag the read-back verifies."""
    return BRepBody(name, is_derived=is_derived)


def FakeBodyCollection(bodies):
    return _NamedCollection(list(bodies))


class FakeDeriveFeature:
    """The landed DeriveFeature: its health pair, the bodies it brought in, whether it is parametric
    and the documentReference a freshness read goes through. DeriveFeature carries no live shape
    dump, so it has no shared fake."""
    def __init__(self, name="Derive1", health=0, message="", bodies=(), is_parametric=True,
                 out_of_date=False):
        self.name = name
        self.healthState = health
        self.errorOrWarningMessage = message
        self.bodies = FakeBodyCollection(bodies)
        self.isParametric = is_parametric
        self.documentReference = FakeDocumentReference(out_of_date=out_of_date)

    def getDerivedEntity(self, source):
        if source not in self.mapping:
            raise RuntimeError("3 : derived entity not found")
        return self.mapping[source]


class FakeDeriveFeatureInput:
    """The DeriveFeatureInput the handler populates - no live shape dump, so no shared fake."""
    def __init__(self):
        self.sourceEntities = None
        self.excludedEntities = None
        self.isIncludeComponentParameters = None
        self.isIncludeFavoriteParameters = None
        self.isPlaceObjectsAtOrigin = None


def _mk_body(spec):
    return FakeBody(*spec) if isinstance(spec, tuple) else FakeBody(spec)


class FakeDeriveFeatures:
    """result: 'default' (build+return a feature) | 'null' (add() returns None) | 'raise'.
    on_add: optional no-arg callback fired the instant add() would create the feature - lets a test
    simulate a side effect that happens DURING the derive (a new occurrence landing, a param count
    change). last_input captures the DeriveFeatureInput the handler populated."""

    def __init__(self, result="default", bodies=("Body1",), health=0, message="",
                 out_of_date=False, is_parametric=True, on_add=None):
        self.result = result
        self.bodies = bodies
        self.health = health
        self.message = message
        self.out_of_date = out_of_date
        self.is_parametric = is_parametric
        self.on_add = on_add
        self.last_input = None
        self.created = None

    def createInput(self, source_design):
        di = FakeDeriveFeatureInput()
        self.last_input = di
        return di

    def add(self, di):
        if self.result == "null":
            return None
        if self.result == "raise":
            raise RuntimeError("derive add failed")
        if self.on_add:
            self.on_add()
        feat = FakeDeriveFeature(health=self.health, message=self.message,
                                 bodies=[_mk_body(b) for b in self.bodies],
                                 is_parametric=self.is_parametric, out_of_date=self.out_of_date)
        self.created = feat
        return feat


def FakeOcc(name, is_derived=True, token=None, body_count=0, children=()):
    """A destination occurrence. body_count + children back _subtree_body_count; isDerived + token
    back the new-derived-occurrence diff."""
    occ = make_occurrence(path=name, derived=is_derived,
                          entity_token=token if token is not None else f"tok-{name}-{id(children)}",
                          bodies=[FakeBody(f"{name}_b{i}") for i in range(body_count)],
                          children=children)
    return occ


def FakeOccurrences(items):
    # tests mutate ._items to simulate an occurrence landing during the derive
    return _NamedCollection(list(items))


def FakeComp(name="Root", derive_features=None, occurrences=(), token=None):
    """The destination component. entityToken, because _common.same_component compares on it: the
    landing net that catches a derive surfacing at ROOT instead of nested is skipped (and disclosed)
    when the target cannot be told from the root. A test that wants that state deletes it."""
    comp = MakeComp(name, entity_token=token if token is not None else f"TOKEN:{name}")
    features = FakeFeatures()
    features.deriveFeatures = (derive_features if derive_features is not None
                               else FakeDeriveFeatures())
    comp.features = features
    comp.occurrences = FakeOccurrences(occurrences)
    return comp


def _typed(name, kind="ModelParameter", expression="7 mm", dependents=()):
    """A parameter reading `kind` as its objectType suffix - DerivedParameter has no shared fake."""
    param = FakeUserParameter(name, expression=expression, dependents=dependents)
    if kind is not None:
        param.objectType = "adsk::fusion::" + kind
    return param


def _params(count, kind="UserParameter"):
    """A parameter collection of `count` entries named p0..pN, each reading `kind`."""
    return FakeUserParameters([_typed(f"p{i}", kind) for i in range(count)])


def _grow_params(params, count, kind="ModelParameter"):
    """Resize a parameter collection - what a derive that imported parameters leaves behind."""
    params._parameters = [_typed(f"p{i}", kind) for i in range(count)]


def FakeDesign(root_comp, design_type=1, user_param_count=0, all_param_count=None, cls=MakeDesign):
    """The DESTINATION design (what _common.design() returns). designType: 1 = parametric, 0 = direct.
    all_param_count=None leaves the design with NO allParameters collection, so the design-level
    model-parameter count reads as UNKNOWN rather than zero. `cls` swaps in a scenario design."""
    return cls(comp=root_comp, design_type=design_type,
               user_parameters=_params(user_param_count),
               all_parameters=(None if all_param_count is None
                               else _params(all_param_count, "ModelParameter")))


class _ReadBackDeclines(MakeDesign):
    """A design whose activeOccurrence READ throws - the state the payload must not report as a
    null. DECLARED, not measured: live the read answers. The setter still records, so activating
    the derive target works."""

    @property
    def activeOccurrence(self):
        raise RuntimeError("activeOccurrence did not read")

    @activeOccurrence.setter
    def activeOccurrence(self, value):
        self._active_occurrence = value


_NO_DEFAULT = object()


def FakeSourceDoc(name="Source", data_file=None, design=_NO_DEFAULT):
    """The open SOURCE document a derive reads its design through."""
    return FakeFusionDocument(
        name=name, data_file=data_file,
        products=FakeProducts(design=_make_source() if design is _NO_DEFAULT else design))


# ── source-side builders ─────────────────────────────────────────────────────────────────────────

def _src_comp(name, bodies=(), token=None):
    """A SOURCE component: name + bRepBodies/meshBodies collections (count/item).

    The entityToken is what _common.same_component compares on - the root derives as ITSELF while
    any other component derives through its occurrences, and the handler refuses rather than pick
    between those two on an identity that did not read. `token=None` is that unreadable state."""
    return MakeComp(name, bodies=list(bodies), mesh_bodies=[],
                    entity_token=token if token is not None else f"TOKEN:{name}")


def _src_occ(name):
    """A SOURCE occurrence - the handler just forwards it into sourceEntities."""
    return make_occurrence(path=name)


def _make_source(components=(), occ_by_comp=None, root_name="SrcRoot"):
    """A SOURCE design: rootComponent (with allOccurrencesByComponent) + allComponents (root + subs)."""
    root = MakeComp(root_name, mesh_bodies=[], entity_token=f"TOKEN:{root_name}",
                    occurrences_by_component=dict(occ_by_comp or {}))
    return MakeDesign(comp=root, all_components=[root] + list(components))


def _install(monkeypatch, *, design_type=1, user_param_count=0, occurrences=(),
             derive_features=None, comp_name="Root", data_file=None,
             source_design=_NO_DEFAULT, source_open=True, all_param_count=None):
    """Wire both design seams + a fake app.documents holding the (open) source doc + a stubbed
    _resolve_data_file. Returns (design, comp, docs, data_file, derive_features, source_doc)."""
    derive_features = derive_features if derive_features is not None else FakeDeriveFeatures()
    comp = FakeComp(comp_name, derive_features=derive_features, occurrences=occurrences)
    design = FakeDesign(comp, design_type=design_type, user_param_count=user_param_count,
                        all_param_count=all_param_count)
    monkeypatch.setattr(io._common, "design", lambda: design)
    monkeypatch.setattr(io._inputs._common, "design", lambda: design)
    df = data_file if data_file is not None else FakeDataFile(
        "SourcePart", file_id="urn:adsk.wipprod:dm.lineage:src", version=3)
    src = _make_source() if source_design is _NO_DEFAULT else source_design
    source_doc = FakeSourceDoc(data_file=df, design=src)
    docs = FakeDocuments([source_doc] if source_open else [])
    monkeypatch.setattr(io, "app", FakeApplication(documents=docs))
    monkeypatch.setattr(io, "_resolve_data_file", lambda raw: (df, df.id, [raw]))
    return design, comp, docs, df, derive_features, source_doc


def _payload(res):
    assert res["isError"] is False, res
    return json.loads(res["content"][0]["text"])


# ── guards ─────────────────────────────────────────────────────────────────────────────────────

class TestGuards:
    def test_empty_document_id_errors(self):
        res = io.handler(document_id="")
        assert res["isError"] is True and "document_id" in res["message"]

    def test_no_active_design(self, monkeypatch):
        monkeypatch.setattr(io._common, "design", lambda: None)
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True and "No active design" in res["message"]

    def test_direct_mode_refused(self, monkeypatch):
        _install(monkeypatch, design_type=0)
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True
        assert "parametric" in res["message"].lower()
        assert "design_set_mode" in res["message"]

    def test_unresolvable_document_id(self, monkeypatch):
        _install(monkeypatch)
        monkeypatch.setattr(io, "_resolve_data_file", lambda raw: (None, None, ["urn:adsk:1", "urn:adsk:2"]))
        res = io.handler(document_id="urn:nope")
        assert res["isError"] is True
        assert "Could not resolve" in res["message"]
        assert "urn:adsk:1" in res["message"]


# ── source-open precondition (createInput needs the source open - async load) ─────────────────────

class TestSourceOpenPrecondition:
    def test_source_not_open_errors_with_doc_open_guidance(self, monkeypatch):
        _, _, _, _, dfs, _ = _install(monkeypatch, source_open=False)
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True
        assert "not open" in res["message"]
        assert "doc_open" in res["message"]          # points the caller at doc_open
        assert dfs.created is None                    # no partial state - never reached add()

    def test_source_open_is_used(self, monkeypatch):
        _install(monkeypatch)                         # source_open=True by default
        out = _payload(io.handler(document_id="urn:x"))
        assert out["derived"] is True


# ── SOURCE component resolver: exact match, miss lists names, ambiguity refused ───────────────────

class TestSourceComponentResolver:
    def test_exact_match_case_insensitive(self):
        src = _make_source([_src_comp("OuterRing"), _src_comp("InnerRing")])
        comps, err = io._resolve_source_components(src, ["outerring"])
        assert err is None
        assert [c.name for c in comps] == ["OuterRing"]

    def test_miss_lists_available_names(self):
        src = _make_source([_src_comp("OuterRing"), _src_comp("Rotor")])
        comps, err = io._resolve_source_components(src, ["NoSuchPart"])
        assert comps is None
        assert "not found" in err
        assert "OuterRing" in err and "Rotor" in err   # available names surfaced

    def test_ambiguous_name_refused_not_first_match(self):
        # TWO distinct components share the name - the resolver must REFUSE, never grab the first.
        a, b = _src_comp("Ring"), _src_comp("Ring")
        src = _make_source([a, b])
        comps, err = io._resolve_source_components(src, ["Ring"])
        assert comps is None                           # did NOT return [a]
        assert "ambiguous" in err and "2" in err

    def test_size_zero_returns_empty(self):
        comps, err = io._resolve_source_components(_make_source([_src_comp("A")]), [])
        assert err is None and comps == []

    def test_size_two_resolves_both_in_order(self):
        src = _make_source([_src_comp("A"), _src_comp("B"), _src_comp("C")])
        comps, err = io._resolve_source_components(src, ["B", "A"])
        assert err is None
        assert [c.name for c in comps] == ["B", "A"]   # order preserved


# ── SOURCE body resolver: name, Component/Body scoping, ambiguity refused ─────────────────────────

class TestSourceBodyResolver:
    def test_body_by_name(self):
        src = _make_source([_src_comp("OuterRing", bodies=["RingSolid"])])
        bodies, err = io._resolve_source_bodies(src, ["RingSolid"])
        assert err is None
        assert [b.name for b in bodies] == ["RingSolid"]

    def test_ambiguous_body_name_refused(self):
        src = _make_source([_src_comp("A", bodies=["Shared"]), _src_comp("B", bodies=["Shared"])])
        bodies, err = io._resolve_source_bodies(src, ["Shared"])
        assert bodies is None
        assert "ambiguous" in err
        assert "A" in err and "B" in err               # names the holders

    def test_component_slash_body_scopes_to_owner(self):
        # 'Shared' is ambiguous unqualified, but 'B/Shared' pins the owner.
        src = _make_source([_src_comp("A", bodies=["Shared"]), _src_comp("B", bodies=["Shared"])])
        bodies, err = io._resolve_source_bodies(src, ["B/Shared"])
        assert err is None and [b.name for b in bodies] == ["Shared"]

    def test_missing_body_named(self):
        src = _make_source([_src_comp("A", bodies=["X"])])
        bodies, err = io._resolve_source_bodies(src, ["Ghost"])
        assert bodies is None and "Ghost" in err


# ── collecting sourceEntities: component -> occurrences, root -> whole, no-occurrence error ────────

class TestCollectSourceEntities:
    def test_component_contributes_its_occurrences(self):
        occ = _src_occ("OuterRing:1")
        src = _make_source([_src_comp("OuterRing")], occ_by_comp={"OuterRing": [occ]})
        ents, labels, err = io._collect_source_entities(src, ["OuterRing"], [])
        assert err is None
        assert ents == [occ]                           # the occurrence, not the component
        assert labels == ["OuterRing"]

    def test_two_components_both_occurrences(self):
        o1, o2 = _src_occ("OuterRing:1"), _src_occ("InnerRing:1")
        src = _make_source([_src_comp("OuterRing"), _src_comp("InnerRing")],
                           occ_by_comp={"OuterRing": [o1], "InnerRing": [o2]})
        ents, labels, err = io._collect_source_entities(src, ["OuterRing", "InnerRing"], [])
        assert err is None and ents == [o1, o2]

    def test_naming_the_root_derives_whole_design(self):
        src = _make_source([_src_comp("Sub")], root_name="Assembly")
        ents, labels, err = io._collect_source_entities(src, ["Assembly"], [])
        assert err is None
        assert ents == [src.rootComponent]             # the root Component itself (whole design)
        assert "whole design" in labels[0]

    def test_component_without_occurrence_errors(self):
        src = _make_source([_src_comp("Lonely")], occ_by_comp={})   # defined, not instanced
        ents, labels, err = io._collect_source_entities(src, ["Lonely"], [])
        assert ents is None and "no occurrence" in err

    def test_the_root_is_recognised_by_identity_not_by_its_name(self):
        # The resolved component and source_design.rootComponent are separate WRAPPERS of one
        # component (component identity is never stable), and a per-field read on a source design is
        # guarded because it can fail. Here the rootComponent wrapper's name will not read: a NAME
        # compare then misses the root and sends the whole design down the occurrence branch, where
        # the root has none. The shared entityToken is what settles it.
        named_root = _src_comp("Assembly", token="tok-root")

        class _UnreadableName(MakeComp):
            """The root wrapper whose display name will not read - the same component, addressed
            through a read that declines."""
            @property
            def name(self):
                raise RuntimeError("3 : cloud read failed")

            @name.setter
            def name(self, value):
                pass

        unreadable = _UnreadableName("Assembly", mesh_bodies=[], entity_token="tok-root")
        src = MakeDesign(comp=unreadable, all_components=[named_root, _src_comp("Sub")])
        ents, labels, err = io._collect_source_entities(src, ["Assembly"], [])
        assert err is None
        assert ents == [named_root]                    # the whole design, not a no-occurrence error
        assert "whole design" in labels[0]


# ── read-back: subtree body count + new-derived-occurrence diff ───────────────────────────────────

class TestReadBackWalk:
    def test_subtree_body_count_sums_descendants(self):
        # a top occurrence with 0 direct bodies but children holding 1 + 2 -> 3 (the whole-design shape)
        child_a = FakeOcc("A:1", body_count=1)
        child_b = FakeOcc("B:1", body_count=2)
        top = FakeOcc("Root:1", body_count=0, children=[child_a, child_b])
        assert io._subtree_body_count(top) == 3

    def test_new_derived_occurrence_diff_excludes_preexisting(self):
        pre = FakeOcc("Old:1", is_derived=True, token="stable", body_count=1)
        comp = FakeComp("Root", occurrences=[pre])
        before = io._occurrence_tokens(comp)
        comp.occurrences._items.append(FakeOcc("New:1", is_derived=True, body_count=2))
        found = io._new_derived_occurrences(comp, before)
        assert found == [{"name": "New:1", "body_count": 2}]   # only the NEW one


# ── scoping through the handler: no selector -> whole; names -> occurrences on sourceEntities ──────

@pytest.fixture
def selector_derive(monkeypatch):
    return _install(monkeypatch)[4]


class TestScopingHandler:
    @pytest.mark.parametrize("field,value", [
        ("source_components", [""]), ("source_bodies", " "),
        ("exclude_components", ["Rotor", " "]), ("exclude_bodies", "Rotor/Body,"),
    ])
    def test_explicit_blank_selector_refuses_before_native_setup(self, selector_derive, field, value):
        dfs = selector_derive
        res = io.handler(document_id="urn:x", **{field: value})
        assert res["isError"] is True and field in res["message"]
        assert "nonblank" in res["message"] and dfs.last_input is None and dfs.created is None

    def test_empty_array_and_valid_legacy_names_keep_their_meaning(self):
        assert io._as_names([], "source_bodies") == []
        assert io._as_names(" A, B/Body ", "source_bodies") == ["A", "B/Body"]

    def test_no_selector_derives_whole_design(self, monkeypatch):
        src = _make_source([_src_comp("Sub")], root_name="WholeSrc")
        _, _, _, _, dfs, _ = _install(monkeypatch, source_design=src)
        out = _payload(io.handler(document_id="urn:x"))
        assert out["scope"] == "whole design"
        assert dfs.last_input.sourceEntities == [src.rootComponent]

    def test_scoped_components_forward_occurrences(self, monkeypatch):
        occ = _src_occ("OuterRing:1")
        src = _make_source([_src_comp("OuterRing")], occ_by_comp={"OuterRing": [occ]})
        _, _, _, _, dfs, _ = _install(monkeypatch, source_design=src)
        out = _payload(io.handler(document_id="urn:x", source_components=["OuterRing"]))
        assert dfs.last_input.sourceEntities == [occ]
        assert out["scope"] == "OuterRing"

    def test_bad_scope_name_errors_before_add(self, monkeypatch):
        src = _make_source([_src_comp("OuterRing")])
        _, _, _, _, dfs, _ = _install(monkeypatch, source_design=src)
        res = io.handler(document_id="urn:x", source_components=["Ghost"])
        assert res["isError"] is True and "Ghost" in res["message"]
        assert dfs.created is None                      # aborted before deriving - no partial state

    def test_an_exclusion_with_no_derived_tree_to_read_is_unverified_not_echoed(self, monkeypatch):
        drop = _src_occ("Rotor:1")
        src = _make_source([_src_comp("Rotor")], occ_by_comp={"Rotor": [drop]}, root_name="WholeSrc")
        _, _, _, _, dfs, _ = _install(monkeypatch, source_design=src)
        out = _payload(io.handler(document_id="urn:x", exclude_components=["Rotor"]))
        assert dfs.last_input.excludedEntities == [drop]
        assert "excluded" not in out
        assert out["exclusion_unverified"] == "Rotor; read design_get(include=['tree'], tree_bodies=true)"


def _derived_tree(source_name, children=(), bodies=()):
    """A landed whole-design derive: one derived occurrence of the source root and its subtree."""
    return make_occurrence(path=source_name + ":1", component=MakeComp(source_name), derived=True,
                           entity_token="tok-new-derive",
                           bodies=[FakeBody(b) for b in bodies], children=children)


def _placed(comp_name, bodies=()):
    """A sub-component placement inside a derived tree."""
    return make_occurrence(path=comp_name + ":1", component=MakeComp(comp_name),
                           bodies=[FakeBody(b) for b in bodies])


@pytest.fixture
def whole_derive(monkeypatch):
    """A whole-design derive whose landing is `tree`; `mapping` is the feature's getDerivedEntity."""
    def build(tree, mapping=None, source=None):
        dfs = FakeDeriveFeatures(bodies=())
        _, comp, _, _, _, _ = _install(monkeypatch, derive_features=dfs, occurrences=[],
                                       source_design=source or _make_source())
        original_add = dfs.add

        def add(di):
            feature = original_add(di)
            feature.mapping = dict(mapping or {})
            comp.occurrences._items.append(tree)
            return feature
        monkeypatch.setattr(dfs, "add", add)
        return dfs
    return build


class TestExclusionReadBack:
    def test_a_root_body_the_mapping_does_not_find_is_published_excluded(self, whole_derive):
        source = _make_source()
        keep, drop = BRepBody("Keep"), BRepBody("Drop")
        source.rootComponent.bRepBodies = FakeBodyCollection([keep, drop])
        whole_derive(_derived_tree("Src", bodies=["Keep"]), mapping={keep: FakeBody("Keep")},
                     source=source)
        out = _payload(io.handler(document_id="urn:x", exclude_bodies=["Drop"]))
        assert out["excluded"] == "Drop" and "exclusion_unverified" not in out

    def test_a_root_body_the_mapping_still_finds_is_a_retained_feature_error(self, whole_derive):
        source = _make_source()
        drop = BRepBody("Drop")
        source.rootComponent.bRepBodies = FakeBodyCollection([drop])
        whole_derive(_derived_tree("Src", bodies=["Drop"]), mapping={drop: FakeBody("Drop")},
                     source=source)
        res = io.handler(document_id="urn:x", exclude_bodies=["Drop"])
        assert res["isError"] is True
        assert "excluded source body 'Drop' has a derived result" in res["message"]
        assert "remains" in res["message"] and "design_delete_feature" in res["message"]

    @pytest.mark.parametrize("landed,field", [
        ("Other", "excluded"), ("Excluded", "exclusion_unverified"),
        ("Excluded (1)", "exclusion_unverified")])
    def test_a_component_exclusion_is_judged_by_the_derived_subtree(self, whole_derive, landed,
                                                                    field):
        drop = _src_occ("Excluded:1")
        source = _make_source([_src_comp("Excluded")], occ_by_comp={"Excluded": [drop]})
        whole_derive(_derived_tree("Src", children=[_placed(landed, ["B"])]), source=source)
        out = _payload(io.handler(document_id="urn:x", exclude_components=["Excluded"]))
        assert out[field].startswith("Excluded")
        assert ({"excluded", "exclusion_unverified"} - {field}).isdisjoint(out)

    def test_only_the_exclusions_the_landing_confirms_are_published_excluded(self, whole_derive):
        kept = _src_occ("Kept:1")
        source = _make_source([_src_comp("Kept")], occ_by_comp={"Kept": [kept]})
        drop = BRepBody("Drop")
        source.rootComponent.bRepBodies = FakeBodyCollection([drop])
        whole_derive(_derived_tree("Src", children=[_placed("Kept", ["B"])]), source=source)
        out = _payload(io.handler(document_id="urn:x", exclude_components=["Kept"],
                                  exclude_bodies=["Drop"]))
        assert out["excluded"] == "Drop"
        assert out["exclusion_unverified"].startswith("Kept;")

    def test_a_sub_component_body_is_judged_by_its_owner_in_the_subtree(self, whole_derive):
        source = _make_source([_src_comp("Holder", bodies=["Peg", "Plate"])])
        whole_derive(_derived_tree("Src", children=[_placed("Holder", ["Plate"])]), source=source)
        out = _payload(io.handler(document_id="urn:x", exclude_bodies=["Holder/Peg"]))
        assert out["excluded"] == "Holder/Peg"

    @pytest.mark.parametrize("landed,field", [
        (["Peg", "Plate"], "exclusion_unverified"), (["Plate"], "excluded"),
        (None, "exclusion_unverified")])
    def test_a_sub_component_body_exclusion_follows_the_landed_census(self, whole_derive, landed,
                                                                    field):
        source = _make_source([_src_comp("Holder", bodies=["Peg", "Plate"])])
        child = _placed("Holder", landed or ["Plate"])
        if landed is None:
            child.childOccurrences = None            # the census read does not answer
        whole_derive(_derived_tree("Src", children=[child]), source=source)
        out = _payload(io.handler(document_id="urn:x", exclude_bodies=["Holder/Peg"]))
        assert out[field].startswith("Holder/Peg")
        assert ({"excluded", "exclusion_unverified"} - {field}).isdisjoint(out)


class TestSubComponentSourceBody:
    def test_a_sub_component_body_is_refused_before_createInput(self, monkeypatch):
        src = _make_source([_src_comp("Nested", bodies=["NestedBody"])])
        _, _, _, _, dfs, _ = _install(monkeypatch, source_design=src)
        res = io.handler(document_id="urn:x", source_bodies=["Nested/NestedBody"])
        assert res["isError"] is True
        assert "sub-component 'Nested'" in res["message"]
        assert "'3 : invalid argument entities'" in res["message"]
        assert "source_components=['Nested']" in res["message"]
        assert dfs.last_input is None and dfs.created is None


# ── read-back honesty: something must actually land ───────────────────────────────────────────────

@pytest.fixture
def mapped_derive(monkeypatch):
    def build(failure=None):
        source_body = BRepBody("Body1")
        source = _make_source()
        source.rootComponent.bRepBodies = FakeBodyCollection([source_body, BRepBody("Body2")])
        dfs = FakeDeriveFeatures(bodies=())
        _, comp, _, df, _, _ = _install(monkeypatch, source_design=source, derive_features=dfs)
        body = BRepBody("Body1", is_derived=True, parent_component=comp)
        original_add = dfs.add

        def add(di):
            feature = original_add(di)
            comp.bRepBodies = FakeBodyCollection([body])
            feature.mapping = {source_body: body}
            feature.documentReference = FakeDocumentReference(data_file=df)
            if failure == "missing":
                feature.mapping.clear()
            elif failure == "unknown_flag":
                body.isDerived = None
            elif failure == "wrong_owner":
                comp.bRepBodies = FakeBodyCollection([BRepBody("Body1", is_derived=True)])
            elif failure == "unknown_link":
                feature.documentReference.isOutOfDate = None
            elif failure == "unread_source_ids":
                df.id = None
            elif failure == "ignored_exclusion":
                second = source.rootComponent.bRepBodies.item(1)
                other = BRepBody("Body2", is_derived=True, parent_component=comp)
                comp.bRepBodies = FakeBodyCollection([body, other])
                feature.mapping[second] = other
            return feature

        monkeypatch.setattr(dfs, "add", add)
        return source_body, body, comp, dfs
    return build


class TestMappedSelectedBody:
    def test_empty_feature_bodies_uses_exact_selected_source_mapping(self, mapped_derive):
        source, body, comp, dfs = mapped_derive()
        out = _payload(io.handler(document_id="urn:x", source_bodies=["Body1"]))
        assert dfs.created.bodies.count == 0 and comp.bRepBodies.item(0) is body
        assert dfs.last_input.sourceEntities == [source]
        assert out["derived_bodies"] == [{"name": "Body1", "is_derived": True}]
        assert out["bodies_landed"] == 1 and out["derived_components"] == []

    def test_explicitly_excluded_body_needs_no_derived_mapping(self, mapped_derive):
        _, _, _, dfs = mapped_derive()
        out = _payload(io.handler(document_id="urn:x", source_bodies=["Body1", "Body2"],
                                  exclude_bodies=["Body2"]))
        assert [b.name for b in dfs.last_input.excludedEntities] == ["Body2"]
        assert out["derived_bodies"] == [{"name": "Body1", "is_derived": True}]
        assert out["bodies_landed"] == 1 and out["excluded"] == "Body2"

    def test_ignored_exclusion_reports_the_retained_result(self, mapped_derive):
        mapped_derive("ignored_exclusion")
        out = io.handler(document_id="urn:x", source_bodies=["Body1", "Body2"],
                         exclude_bodies=["Body2"])
        assert out["isError"] is True
        assert "excluded source body 'Body2' has a derived result" in out["message"]
        assert "Derive1" in out["message"] and "remains" in out["message"]

    @pytest.mark.parametrize("failure", ["missing", "unknown_flag", "wrong_owner", "unknown_link",
                                         "unread_source_ids"])
    def test_unconfirmed_mapping_names_retained_feature(self, mapped_derive, failure):
        mapped_derive(failure)
        out = io.handler(document_id="urn:x", source_bodies=["Body1"])
        assert out["isError"] is True
        assert "Derive1" in out["message"] and "remains" in out["message"]
        assert "design_get" in out["message"] and "design_delete_feature" in out["message"]

    def test_component_exclusion_keeps_the_existing_classifier(self, mapped_derive):
        mapped_derive()
        out = io.handler(document_id="urn:x", source_bodies=["Body1"],
                         exclude_components=["SrcRoot"])
        assert out["isError"] is True
        assert "nothing reports isDerived=true" in out["message"]


class TestReadBackHonesty:
    def test_nothing_landed_is_an_error(self, monkeypatch):
        # a feature with no bodies, and no new derived occurrence, and no design-wide body delta.
        derive_features = FakeDeriveFeatures(bodies=())
        _install(monkeypatch, derive_features=derive_features, occurrences=[])
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True and "nothing landed" in res["message"]

    def test_an_unread_body_count_is_unknown_not_nothing_landed(self, monkeypatch):
        derive_features = FakeDeriveFeatures(bodies=())
        _, comp, *_ = _install(monkeypatch, derive_features=derive_features, occurrences=[])
        comp.bRepBodies = _NamedCollection(raises="stale")
        msg = io.handler(document_id="urn:x")["message"]
        assert "whether bodies appeared is unknown: a body count did not read" in msg
        assert "nothing landed" not in msg

    @pytest.mark.parametrize("failure", ["collection", "count", "item"])
    def test_an_unread_component_census_does_not_publish_zero_landed_bodies(self, monkeypatch, failure):
        design, *_ = _install(monkeypatch)
        if failure == "collection":
            def unread_collection(_self):
                raise RuntimeError("allComponents did not read")
            monkeypatch.setattr(type(design), "allComponents", property(unread_collection))
        else:
            class UnreadCount:
                @property
                def count(self):
                    raise RuntimeError("allComponents.count did not read")
            class UnreadItem:
                @property
                def count(self):
                    return 1
                def item(self, _index):
                    raise RuntimeError("allComponents.item did not read")
            unread = UnreadCount() if failure == "count" else UnreadItem()
            monkeypatch.setattr(type(design), "allComponents", property(lambda _self: unread))

        out = _payload(io.handler(document_id="urn:x"))

        assert out["bodies_landed"] is None
        assert out["derived_bodies"] == [{"name": "Body1", "is_derived": True}]

    def test_geometry_without_derived_marker_is_an_error(self, monkeypatch):
        # bodies appear but none report isDerived=true -> the one-way link did not form.
        derive_features = FakeDeriveFeatures(bodies=[("Body1", False)])
        _install(monkeypatch, derive_features=derive_features)
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True and "isDerived" in res["message"]

    def test_direct_derived_bodies_reported(self, monkeypatch):
        derive_features = FakeDeriveFeatures(bodies=[("Body1", True), ("Body2", False)])
        _install(monkeypatch, derive_features=derive_features)
        out = _payload(io.handler(document_id="urn:x"))
        assert out["derived_occurrence"] == "Body1"
        assert out["derived_bodies"] == [
            {"name": "Body1", "is_derived": True}, {"name": "Body2", "is_derived": False}]

    def test_derived_occurrence_reported_with_body_count(self, monkeypatch):
        derive_features = FakeDeriveFeatures(bodies=())
        design, comp, docs, df, dfs, _ = _install(monkeypatch, derive_features=derive_features,
                                                  occurrences=[])
        dfs.on_add = lambda: comp.occurrences._items.append(
            FakeOcc("SourcePart:1", is_derived=True, body_count=1))
        out = _payload(io.handler(document_id="urn:x"))
        assert out["derived_bodies"] == []
        assert out["derived_components"] == [{"name": "SourcePart:1", "body_count": 1}]
        assert out["derived_occurrence"] == "SourcePart:1"

    def test_preexisting_derived_occurrence_not_counted(self, monkeypatch):
        pre_existing = FakeOcc("OldDerived:1", is_derived=True, token="stable-token")
        derive_features = FakeDeriveFeatures(bodies=())
        _install(monkeypatch, derive_features=derive_features, occurrences=[pre_existing])
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True and "nothing landed" in res["message"]


# ── null add() / exceptions / missing collection (bite-proofed) ──────────────────────────────────

class TestAddFailures:
    def test_null_add_errors_not_false_ok(self, monkeypatch):
        derive_features = FakeDeriveFeatures(result="null")
        _install(monkeypatch, derive_features=derive_features)
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True and "add returned nothing" in res["message"]

    def test_add_raising_errors(self, monkeypatch):
        derive_features = FakeDeriveFeatures(result="raise")
        _install(monkeypatch, derive_features=derive_features)
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True and "Derive failed" in res["message"]

    def test_missing_derive_features_collection_errors(self, monkeypatch):
        comp = FakeComp()
        comp.features.deriveFeatures = None      # this build's Features carries no derive collection
        design = FakeDesign(comp)
        monkeypatch.setattr(io._common, "design", lambda: design)
        monkeypatch.setattr(io._inputs._common, "design", lambda: design)
        df = FakeDataFile("SourcePart", file_id="urn:adsk.wipprod:dm.lineage:src")
        source_doc = FakeSourceDoc(data_file=df, design=_make_source())
        monkeypatch.setattr(io, "app",
                            FakeApplication(documents=FakeDocuments([source_doc])))
        monkeypatch.setattr(io, "_resolve_data_file", lambda raw: (df, raw, [raw]))
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True and "deriveFeatures" in res["message"]


# ── healthState / documentReference verify ───────────────────────────────────────────────────────

class TestHealthAndReferenceVerify:
    def test_error_health_state_bites(self, monkeypatch):
        derive_features = FakeDeriveFeatures(health=2, message="boundary edges do not match")
        _install(monkeypatch, derive_features=derive_features)
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True
        assert "FAILED to compute" in res["message"]
        assert "boundary edges do not match" in res["message"]

    def test_warning_health_state_does_not_error(self, monkeypatch):
        derive_features = FakeDeriveFeatures(health=1, message="a minor warning")
        _install(monkeypatch, derive_features=derive_features)
        out = _payload(io.handler(document_id="urn:x"))
        assert out["derived"] is True and out["feature_name"] == "Derive1"

    def test_out_of_date_at_creation_errors(self, monkeypatch):
        derive_features = FakeDeriveFeatures(out_of_date=True)
        _install(monkeypatch, derive_features=derive_features)
        res = io.handler(document_id="urn:x")
        assert res["isError"] is True and "isOutOfDate=true" in res["message"]


# ── parameter-flag verify ─────────────────────────────────────────────────────────────────────────

class TestParameterVerify:
    def test_warns_when_flags_set_and_zero_landed(self, monkeypatch):
        _install(monkeypatch, user_param_count=4, all_param_count=9)   # neither census changes
        out = _payload(io.handler(document_id="urn:x"))
        assert out["parameters_imported"] == 0 and out["imported_parameter_names"] == []
        assert "no new derived or user parameter" in out["parameter_warning"]

    def test_warning_points_at_the_model_parameter_route(self, monkeypatch):
        # 0 imported is not "nothing arrived": source values can land as read-only MODEL
        # parameters, and the warning must name the read that sees them.
        _install(monkeypatch, user_param_count=4, all_param_count=9)
        out = _payload(io.handler(document_id="urn:x"))
        assert "param_get(include_model_parameters=true)" in out["parameter_warning"]

    def test_a_derived_favorite_outside_user_parameters_counts_as_imported(self, monkeypatch):
        # The favourite lands in allParameters as a DerivedParameter and never in userParameters.
        design, comp, docs, df, dfs, _ = _install(monkeypatch, user_param_count=2,
                                                  all_param_count=3)
        dfs.on_add = lambda: design.allParameters._parameters.append(
            _typed("PS_Fav_Ref", "DerivedParameter"))
        out = _payload(io.handler(document_id="urn:x"))
        assert out["parameters_imported"] == 1
        assert out["imported_parameter_names"] == ["PS_Fav_Ref"]
        assert "parameter_warning" not in out and "user_parameters_added" not in out

    def test_a_census_that_does_not_read_leaves_the_count_unknown(self, monkeypatch):
        _install(monkeypatch, user_param_count=4)          # no allParameters collection at all
        out = _payload(io.handler(document_id="urn:x"))
        assert out["parameters_imported"] is None
        assert "did not read on both sides" in out["parameters_unread"]
        assert "imported_parameter_names" not in out and "parameter_warning" not in out

    def test_a_new_parameter_of_unread_type_is_not_counted_either_way(self, monkeypatch):
        design, comp, docs, df, dfs, _ = _install(monkeypatch, all_param_count=3)
        dfs.on_add = lambda: design.allParameters._parameters.append(_typed("Mystery", None))
        out = _payload(io.handler(document_id="urn:x"))
        assert out["parameters_imported"] is None
        assert out["parameters_unread"] == "1 new parameter(s) did not read their type"

    @pytest.mark.parametrize("landed, truncated", [(50, False), (51, True)])
    def test_imported_names_are_capped_and_the_cut_is_flagged(self, monkeypatch, landed, truncated):
        design, comp, docs, df, dfs, _ = _install(monkeypatch, all_param_count=3)
        dfs.on_add = lambda: design.allParameters._parameters.extend(
            _typed(f"Fav{i:02d}", "DerivedParameter") for i in range(landed))
        out = _payload(io.handler(document_id="urn:x"))
        assert out["parameters_imported"] == landed
        assert len(out["imported_parameter_names"]) == 50
        assert ("imported_parameter_names_truncated" in out) is truncated

    def test_model_parameters_added_is_the_design_level_delta(self, monkeypatch):
        # the imported values land as MODEL parameters at the DESIGN level, so the delta is taken
        # over design.allParameters - not over the derived component, which holds only its own.
        design, comp, docs, df, dfs, _ = _install(monkeypatch, user_param_count=4,
                                                  all_param_count=9)
        dfs.on_add = lambda: _grow_params(design.allParameters, 29)
        out = _payload(io.handler(document_id="urn:x"))
        assert out["parameters_imported"] == 0        # none of the new ones reads as derived...
        assert out["model_parameters_added"] == 20    # ...while 20 model parameters landed

    def test_zero_delta_is_published_honestly(self, monkeypatch):
        # both counts read, and they matched: 0 is an ANSWER here, unlike an unreadable count.
        _install(monkeypatch, all_param_count=9)
        out = _payload(io.handler(document_id="urn:x"))
        assert out["model_parameters_added"] == 0

    def test_model_parameter_delta_omitted_when_unreadable(self, monkeypatch):
        # allParameters cannot be read, so the delta is UNKNOWN - the key is omitted, never a false 0.
        _install(monkeypatch)
        out = _payload(io.handler(document_id="urn:x"))
        assert "model_parameters_added" not in out

    def test_no_warning_when_both_flags_false(self, monkeypatch):
        _install(monkeypatch, user_param_count=4, all_param_count=9)
        out = _payload(io.handler(document_id="urn:x", include_parameters=False,
                                  include_favorite_parameters=False))
        assert out["parameters_imported"] == 0
        assert "parameter_warning" not in out

    def test_new_user_parameters_are_published_under_their_own_key(self, monkeypatch):
        design, comp, docs, df, dfs, _ = _install(monkeypatch, user_param_count=2,
                                                  all_param_count=3)
        dfs.on_add = lambda: _grow_params(design.userParameters, 5, "UserParameter")
        out = _payload(io.handler(document_id="urn:x"))
        assert out["user_parameters_added"] == 3 and out["parameters_imported"] == 0
        assert "parameter_warning" not in out

    def test_flags_forwarded_to_derive_input(self, monkeypatch):
        design, comp, docs, df, dfs, _ = _install(monkeypatch)
        _payload(io.handler(document_id="urn:x", include_parameters=False,
                            include_favorite_parameters=True, place_at_origin=False))
        di = dfs.last_input
        assert di.isIncludeComponentParameters is False
        assert di.isIncludeFavoriteParameters is True
        assert di.isPlaceObjectsAtOrigin is False


# ── into_component resolution (shared OccurrenceRef kind) ────────────────────────────────────────

class TestIntoComponent:
    def test_empty_uses_root(self, monkeypatch):
        _install(monkeypatch)
        out = _payload(io.handler(document_id="urn:x"))
        assert out["into_component"] == "root component"

    def _nested_setup(self, monkeypatch, *, occ_activates=True, chassis_derive=None,
                      root_restore="lands", read_back="reads", prev_active=None):
        """A design with a Chassis:1 occurrence targetable by into_component. The occ counts its
        activate() calls and takes the design's edit target with it (the platform routes a derive
        into the ACTIVE component, so nesting activates the target first). activateRootComponent
        answers True in every measured state, so root_restore says what it DOES: 'lands' clears
        activeOccurrence, 'lies' leaves the occurrence holding it, 'raise' throws. read_back
        'declines' makes the activeOccurrence READ throw; prev_active names the component holding
        the edit target BEFORE the call (default: the root)."""
        chassis_derive = chassis_derive or FakeDeriveFeatures()
        chassis_comp = FakeComp("Chassis", derive_features=chassis_derive)
        calls = {"activated": 0, "root_restored": 0}
        root_comp = FakeComp("Root")
        design = FakeDesign(root_comp,
                            cls=_ReadBackDeclines if read_back == "declines" else MakeDesign)
        if prev_active is not None:
            design.activeComponent = MakeComp(prev_active)

        class _ActivatableOcc(FakeOccurrence):
            """The into_component target: activating it makes it the design's activeOccurrence."""
            def activate(self):
                calls["activated"] += 1
                if occ_activates:
                    design.activeOccurrence = self
                return occ_activates

        occ = _ActivatableOcc("Chassis:1", chassis_comp)
        root_comp.allOccurrences = [occ]

        def _restore_root():
            calls["root_restored"] += 1
            if root_restore == "raise":
                raise RuntimeError("activateRootComponent blew up")
            if root_restore == "lands":
                design.activeOccurrence = None
            return True
        design.activateRootComponent = _restore_root
        monkeypatch.setattr(io._common, "design", lambda: design)
        monkeypatch.setattr(io._inputs._common, "design", lambda: design)
        df = FakeDataFile("SourcePart", file_id="urn:adsk.wipprod:dm.lineage:src")
        source_doc = FakeSourceDoc(data_file=df, design=_make_source())
        monkeypatch.setattr(io, "app",
                            FakeApplication(documents=FakeDocuments([source_doc])))
        monkeypatch.setattr(io, "_resolve_data_file", lambda raw: (df, raw, [raw]))
        return design, chassis_comp, chassis_derive, calls

    def test_named_occurrence_activates_derives_and_restores_root(self, monkeypatch):
        design, chassis, chassis_derive, calls = self._nested_setup(monkeypatch)
        out = _payload(io.handler(document_id="urn:x", into_component="Chassis:1"))
        assert "Chassis" in out["into_component"]
        assert chassis_derive.created is not None
        assert calls["activated"] == 1       # nesting = activate the target before add()
        assert calls["root_restored"] == 1   # ...and restore the root edit target after
        assert out["active_occurrence_after"] is None    # the read-back that confirms the restore
        assert "root_restore_note" not in out

    def test_a_non_root_edit_target_before_the_call_is_named_after_it(self, monkeypatch):
        # The restore landed, so the payload says where the edit target WAS - the caller may want
        # it back. This is the CONFIRMED-root arm; a refuted one publishes root_restore_note.
        self._nested_setup(monkeypatch, prev_active="Fixture")
        out = _payload(io.handler(document_id="urn:x", into_component="Chassis:1"))
        assert out["active_occurrence_after"] is None
        assert "'Fixture'" in out["edit_target_note"]

    def test_a_root_restore_the_read_back_refutes_is_reported(self, monkeypatch):
        # activateRootComponent() answers True whether or not the edit target moved, so the
        # activeOccurrence read-back is the only signal: still holding the occurrence means the
        # restore did not land, and the derive that DID land is still reported beside it.
        _design, _chassis, derive, calls = self._nested_setup(monkeypatch, root_restore="lies",
                                                              prev_active="Fixture")
        out = _payload(io.handler(document_id="urn:x", into_component="Chassis:1"))
        assert derive.created is not None and calls["root_restored"] == 1
        assert out["active_occurrence_after"] == "Chassis:1"
        assert out["root_restore_note"].startswith("nesting activated component 'Chassis'")
        assert "not confirmed" in out["root_restore_note"]
        # the OTHER arm's note would claim the target reads ROOT now, which nothing read
        assert "edit_target_note" not in out

    def test_a_raising_read_back_is_not_reported_as_root(self, monkeypatch):
        # A read that DECLINES is not the null that confirms the restore: the sentinel keeps it out
        # of the payload entirely and the note says the read did not answer.
        _design, _chassis, derive, calls = self._nested_setup(monkeypatch, read_back="declines")
        out = _payload(io.handler(document_id="urn:x", into_component="Chassis:1"))
        assert derive.created is not None and calls["root_restored"] == 1
        assert "active_occurrence_after" not in out
        assert "did not read" in out["root_restore_note"]

    def test_a_RAISING_root_restore_does_not_sink_the_call(self, monkeypatch):
        # The restore runs in a finally, so a raise there would escape the handler and turn a
        # landed derive into an exception - it is swallowed, and the read-back still reports where
        # the edit target is.
        _design, _chassis, derive, calls = self._nested_setup(monkeypatch, root_restore="raise")
        out = _payload(io.handler(document_id="urn:x", into_component="Chassis:1"))
        assert "Chassis" in out["into_component"] and derive.created is not None
        assert calls["root_restored"] == 1
        assert out["active_occurrence_after"] == "Chassis:1"
        assert "not confirmed" in out["root_restore_note"]

    def test_activation_failure_refuses_before_deriving(self, monkeypatch):
        design, chassis, chassis_derive, calls = self._nested_setup(monkeypatch,
                                                                    occ_activates=False)
        res = io.handler(document_id="urn:x", into_component="Chassis:1")
        assert res["isError"] is True and "activate" in res["message"].lower()
        assert chassis_derive.created is None       # nothing was derived

    def test_root_stray_landing_is_an_honest_error(self, monkeypatch):
        # The platform ignored the activation and landed the derive at ROOT: the read-back must
        # say so, never report a nested success over a root sibling.
        chassis_derive = FakeDeriveFeatures()
        design, chassis, _, calls = self._nested_setup(monkeypatch,
                                                       chassis_derive=chassis_derive)
        stray = FakeOcc("Stray:1", is_derived=True, body_count=1)
        chassis_derive.on_add = (
            lambda: design.rootComponent.occurrences._items.append(stray))
        design.rootComponent.occurrences = FakeOccurrences([])
        res = io.handler(document_id="urn:x", into_component="Chassis:1")
        assert res["isError"] is True
        assert "ROOT" in res["message"] and "Stray:1" in res["message"]

    def test_an_unidentifiable_target_discloses_the_unrun_landing_check(self, monkeypatch):
        # same_component answers None with no readable token, so the stray-at-ROOT net cannot run:
        # a root-targeted derive answers that net POSITIVELY, and firing it here would report a
        # successful derive as a failure and tell the caller to delete it. The derive stands and the
        # payload says the landing was not verified.
        chassis_derive = FakeDeriveFeatures()
        design, chassis, _, _calls = self._nested_setup(monkeypatch,
                                                        chassis_derive=chassis_derive)
        del chassis.entityToken
        stray = FakeOcc("Stray:1", is_derived=True, body_count=1)
        chassis_derive.on_add = (
            lambda: design.rootComponent.occurrences._items.append(stray))
        design.rootComponent.occurrences = FakeOccurrences([])
        out = _payload(io.handler(document_id="urn:x", into_component="Chassis:1"))
        assert out["derived"] is True                     # not rolled back on an unread token
        assert "unverified" in out["landing_unverified"].lower()

    def test_a_PROVEN_root_target_runs_no_stray_net(self, monkeypatch):
        # the other side of the boundary: `is False` gates the net, so a target proven to BE the
        # root neither reports its own successful landing as a stray nor discloses an unrun check
        _install(monkeypatch)
        out = _payload(io.handler(document_id="urn:x"))
        assert out["derived"] is True and "landing_unverified" not in out

    def test_unknown_occurrence_errors(self, monkeypatch):
        _install(monkeypatch)
        res = io.handler(document_id="urn:x", into_component="Ghost")
        assert res["isError"] is True and "Ghost" in res["message"]


# ── payload contract ───────────────────────────────────────────────────────────────────────────

class TestPayloadContract:
    def test_payload_keys_match_returns(self, monkeypatch):
        _install(monkeypatch)
        out = _payload(io.handler(document_id="urn:x"))
        for kind in io.RETURNS:
            problem = kind.assert_present(out)
            assert problem == "", problem

    def test_saved_version_wire_sentence_present(self, monkeypatch):
        # derive reads the source's last SAVED cloud version, not live in-session edits.
        _install(monkeypatch)
        out = _payload(io.handler(document_id="urn:x"))
        assert "last SAVED cloud version" in out["note"]
        assert "last SAVED cloud version" in io.TOOL_DESCRIPTION

    def test_document_metadata_reported(self, monkeypatch):
        df = FakeDataFile("Gimbal", file_id="urn:adsk.wipprod:dm.lineage:abc", version=7)
        _install(monkeypatch, data_file=df)
        out = _payload(io.handler(document_id="whatever-resolves"))
        assert out["document_id"] == df.id
        assert out["document_name"] == "Gimbal"
        assert out["source_version"] == 7
        assert out["is_parametric"] is True


# ── set_favorite_parameters: the favourites toggle judged by the parameter census ────────────────

class _FavoriteDerive:
    """A DeriveFeature whose isIncludeFavoriteParameters setter moves the design's parameters: off
    drops a derived parameter nothing uses and turns a used one into a local parameter of the same
    name; on adds a derived parameter under the first free name. `mode` 'ignored' drops the write
    and 'raises' throws on it."""
    name = "Derive1"

    def __init__(self, design, include=True, mode="honest"):
        self._design, self._flag, self.mode = design, include, mode

    @property
    def isIncludeFavoriteParameters(self):
        return self._flag

    @isIncludeFavoriteParameters.setter
    def isIncludeFavoriteParameters(self, value):
        if self.mode == "raises":
            raise RuntimeError("3 : favorites refused")
        if self.mode == "ignored":
            return
        self._flag = value
        params = self._design.allParameters._parameters
        if value:
            taken = {p.name for p in params}
            params.append(_typed("PS_Fav_Ref" if "PS_Fav_Ref" not in taken else "PS_Fav_Ref1",
                                 "DerivedParameter"))
            return
        for p in [p for p in params if p.objectType.endswith("DerivedParameter")]:
            if p.dependentParameters.count:
                p.objectType = "adsk::fusion::UserParameter"
            else:
                params.remove(p)


def _favorite_design(params, marker=None):
    """A one-body design at the end of a one-feature timeline, holding `params` in allParameters."""
    comp = MakeComp("Root", bodies=[FakeBody("Derived")])
    users = [p for p in params if p.objectType.endswith("UserParameter")]
    design = MakeDesign(comp=comp, all_components=[comp],
                        timeline=FakeTimeline([FakeTimelineObject(name="Derive1")], marker=marker),
                        user_parameters=FakeUserParameters(users),
                        all_parameters=FakeUserParameters(params))
    return design


def _details(res):
    assert res["isError"] is True, res
    return res["details"]


def _shapes(design):
    """The body snapshot the edits diff: one row per body, its volume standing for its shape."""
    return {(c.name, i): {"component": c.name, "body": b.name, "shape": b.volume}
            for c in design.allComponents for i, b in enumerate(c.bRepBodies._items)}


@pytest.fixture
def body_shapes(monkeypatch):
    monkeypatch.setattr(io._edit_feature_common, "all_shapes", _shapes)


def _stale_until_recompute(monkeypatch, design):
    """Make the body snapshot unreadable after a write until the design recomputes."""
    state = {"writes": 0}

    def shapes(d):
        return None if state["writes"] > d._computes else _shapes(d)
    monkeypatch.setattr(io._edit_feature_common, "all_shapes", shapes)
    return state


class _StalingFavorite(_FavoriteDerive):
    """A favourites setter after which the bodies read nothing until computeAll."""
    stale = None

    @property
    def isIncludeFavoriteParameters(self):
        return self._flag

    @isIncludeFavoriteParameters.setter
    def isIncludeFavoriteParameters(self, value):
        _FavoriteDerive.isIncludeFavoriteParameters.fset(self, value)
        self.stale["writes"] = self._design._computes + 1


@pytest.mark.usefixtures("body_shapes")
class TestSetFavoriteParameters:
    def _staling(self, monkeypatch):
        design = _favorite_design([_typed("PS_Fav_Ref", "DerivedParameter")])
        derive = _StalingFavorite(design)
        derive.stale = _stale_until_recompute(monkeypatch, design)
        return design, derive

    def test_the_design_is_recomputed_before_the_bodies_are_judged(self, monkeypatch):
        design, derive = self._staling(monkeypatch)
        out = _payload(io.set_favorite_parameters(design, derive, False))
        assert out["edited"] is True and out["recomputed"] is True and design._computes == 1
        assert out["bodies_changed"] == out["bodies_arrived"] == out["bodies_left"] == []
        assert "recomputed" in out["note"] and "same before and after" in out["note"]

    @pytest.mark.parametrize("raises", ["3 : compute failed", None])
    def test_a_recompute_that_does_not_complete_is_an_error_carrying_the_flag(
            self, monkeypatch, raises):
        design, derive = self._staling(monkeypatch)
        if raises:
            design._compute_raises = raises
        else:
            monkeypatch.setattr(design, "computeAll", lambda: False)
        res = io.set_favorite_parameters(design, derive, False)
        details = _details(res)
        assert "isIncludeFavoriteParameters reads false now" in res["message"]
        assert "bodies are unverified" in res["message"] and "design_recompute" in res["message"]
        assert (raises or "computeAll answered False") in res["message"]
        assert details["recomputed"] is False and details["favorite_parameters_after"] is False
        assert details["bodies_after"] is None and "edited" not in details

    def test_bodies_that_do_not_read_after_the_recompute_are_an_error(self, monkeypatch):
        design, derive = self._staling(monkeypatch)
        derive.stale["writes"] = 0
        monkeypatch.setattr(design, "computeAll", lambda: True)
        res = io.set_favorite_parameters(design, derive, False)
        assert "did not re-read after the recompute" in res["message"]
        assert _details(res)["recomputed"] is True

    def test_bodies_that_do_not_read_beforehand_refuse_before_the_write(self, monkeypatch):
        monkeypatch.setattr(io._edit_feature_common, "all_shapes", lambda design: None)
        design = _favorite_design([_typed("PS_Fav_Ref", "DerivedParameter")])
        derive = _FavoriteDerive(design)
        res = io.set_favorite_parameters(design, derive, False)
        assert res["isError"] is True and "Nothing was written" in res["message"]
        assert derive.isIncludeFavoriteParameters is True and design._computes == 0

    def test_off_with_nothing_depending_lists_the_parameter_as_disappeared(self):
        design = _favorite_design([_typed("PS_Fav_Ref", "DerivedParameter")])
        out = _payload(io.set_favorite_parameters(design, _FavoriteDerive(design), False))
        assert out["edited"] is True
        assert (out["favorite_parameters_before"], out["favorite_parameters_after"]) == (True, False)
        assert out["parameters_disappeared"] == ["PS_Fav_Ref"]
        assert out["became_local"] == [] and out["parameters_appeared"] == []
        assert (out["body_count_before"], out["body_count_after"]) == (1, 1)
        assert out["health_after"] == {"errors": [], "warnings": []}
        assert "Gone: 'PS_Fav_Ref'" in out["note"]

    def test_off_with_a_dependent_names_the_parameter_that_stopped_being_derived(self):
        dep = _typed("PP_Dep", "UserParameter", "PS_Fav_Ref * 2")
        design = _favorite_design([dep, _typed("PS_Fav_Ref", "DerivedParameter", dependents=[dep])])
        out = _payload(io.set_favorite_parameters(design, _FavoriteDerive(design), False))
        assert out["became_local"] == [{"name": "PS_Fav_Ref", "dependents": ["PP_Dep"]}]
        assert out["parameters_disappeared"] == []
        assert "no longer derived: 'PS_Fav_Ref' (used by PP_Dep)" in out["note"]
        assert not any(word in out["note"].lower() for word in ("restor", "undo", "revert"))

    def test_on_after_that_reports_the_new_name_and_still_lists_the_local_copy(self):
        dep = _typed("PP_Dep", "UserParameter", "PS_Fav_Ref * 2")
        design = _favorite_design([dep, _typed("PS_Fav_Ref", "UserParameter", dependents=[dep])])
        out = _payload(io.set_favorite_parameters(design, _FavoriteDerive(design, include=False),
                                                  True))
        assert out["parameters_appeared"] == [{"name": "PS_Fav_Ref1", "derived": True}]
        assert out["became_local"] == []
        listed = {row["name"]: row for row in out["user_and_derived_parameters"]}
        assert listed["PS_Fav_Ref"]["kind"] == "UserParameter"
        assert listed["PS_Fav_Ref"]["dependents"] == ["PP_Dep"]
        assert "New: 'PS_Fav_Ref1'" in out["note"]
        assert not any(word in out["note"].lower() for word in ("restor", "undo", "revert"))

    @pytest.mark.parametrize("mode, raised", [("ignored", False), ("raises", True)])
    def test_a_flag_that_does_not_read_back_as_requested_is_an_error(self, mode, raised):
        design = _favorite_design([_typed("PS_Fav_Ref", "DerivedParameter")])
        res = io.set_favorite_parameters(design, _FavoriteDerive(design, mode=mode), False)
        details = _details(res)
        assert "reads isIncludeFavoriteParameters true after setting false" in res["message"]
        assert ("3 : favorites refused" in res["message"]) is raised
        assert details["favorite_parameters_after"] is True
        assert details["parameters_disappeared"] == []

    def test_a_setter_that_raises_after_landing_is_an_error_carrying_what_landed(self):
        dep = _typed("PP_Dep", "UserParameter", "PS_Fav_Ref * 2")
        design = _favorite_design([dep, _typed("PS_Fav_Ref", "DerivedParameter", dependents=[dep]),
                                   _typed("PS_Other", "DerivedParameter")])
        honest = _FavoriteDerive.isIncludeFavoriteParameters.fset

        class _RaisesLate(_FavoriteDerive):
            @property
            def isIncludeFavoriteParameters(self):
                return self._flag

            @isIncludeFavoriteParameters.setter
            def isIncludeFavoriteParameters(self, value):
                honest(self, value)
                raise RuntimeError("3 : raised after the change")
        res = io.set_favorite_parameters(design, _RaisesLate(design), False)
        details = _details(res)
        assert "3 : raised after the change." in res["message"]
        assert "The flag reads false now" in res["message"]
        assert details["favorite_parameters_after"] is False
        assert details["parameters_disappeared"] == ["PS_Other"]
        assert details["became_local"] == [{"name": "PS_Fav_Ref", "dependents": ["PP_Dep"]}]
        assert (details["body_count_before"], details["body_count_after"]) == (1, 1)
        assert details["health_after"] == {"errors": [], "warnings": []}

    def test_a_flag_already_as_requested_writes_nothing(self):
        design = _favorite_design([_typed("PS_Fav_Ref", "DerivedParameter")])
        derive = _FavoriteDerive(design, mode="raises")
        out = _payload(io.set_favorite_parameters(design, derive, True))
        assert out["edited"] is False and "nothing was written" in out["note"]

    @pytest.mark.parametrize("marker, refused", [(0, True), (1, False)])
    def test_a_rolled_back_marker_is_refused_before_the_write(self, marker, refused):
        design = _favorite_design([_typed("PS_Fav_Ref", "DerivedParameter")], marker=marker)
        derive = _FavoriteDerive(design)
        res = io.set_favorite_parameters(design, derive, False)
        assert res["isError"] is refused
        assert derive.isIncludeFavoriteParameters is refused
        if refused:
            assert "marker reads 0 of 1" in res["message"]

    def test_a_parameter_census_that_does_not_read_refuses_before_the_write(self):
        design = _favorite_design([_typed("PS_Fav_Ref", "DerivedParameter")])
        design.allParameters._parameters.append(_typed("PS_Fav_Ref", "ModelParameter"))
        derive = _FavoriteDerive(design)
        res = io.set_favorite_parameters(design, derive, False)
        assert res["isError"] is True and "Nothing was written" in res["message"]
        assert derive.isIncludeFavoriteParameters is True

    def test_dependents_that_do_not_read_are_null_with_a_reason(self):
        used = _typed("PS_Fav_Ref", "DerivedParameter", dependents=[_typed("PP_Dep", "UserParameter")])
        design = _favorite_design([used])
        derive = _FavoriteDerive(design)
        honest = type(derive).isIncludeFavoriteParameters.fset

        class _Blind(_FavoriteDerive):
            @property
            def isIncludeFavoriteParameters(self):
                return self._flag

            @isIncludeFavoriteParameters.setter
            def isIncludeFavoriteParameters(self, value):
                honest(self, value)
                used.dependentParameters._raises = "3 : dependents unreadable"
        out = _payload(io.set_favorite_parameters(design, _Blind(design), False))
        assert out["became_local"] == [{"name": "PS_Fav_Ref", "dependents": None,
                                        "dependents_unread": "dependentParameters did not read"}]


# ── set_source_entities / break_link: a derive edit judged by what re-reads ──────────────────────

def _source_design(names=("PS_A", "PS_B", "PS_C")):
    """The derive's SOURCE design: root bodies of 1, 2, 3... cm3 under the given names."""
    return MakeDesign(comp=MakeComp("SrcRoot", bodies=[
        BRepBody(n, volume=float(i + 1)) for i, n in enumerate(names)]))


def _edit_design(params=(), derived=("PS_A",), local=(), marker=None):
    """The TARGET design at the end of a one-feature timeline: derived bodies plus local ones."""
    comp = MakeComp("Root", bodies=[BRepBody(n, volume=1.0, is_derived=True) for n in derived]
                    + [BRepBody(n, volume=9.0) for n in local])
    return MakeDesign(comp=comp, all_components=[comp],
                      timeline=FakeTimeline([FakeTimelineObject(name="Derive1")], marker=marker),
                      user_parameters=FakeUserParameters([]),
                      all_parameters=FakeUserParameters(list(params)))


class _EditDerive:
    """A DeriveFeature at timeline index 0. setSourceEntities lands one derived body per entity;
    breakLink swaps the timeline entity for a BaseFeature and drops the derived parameters. `mode`
    'false' answers False and 'raises' throws, neither acting; 'ignored' answers True without
    acting; 'late' acts and then throws; 'breaks' acts and leaves the timeline item in error."""
    name = "Derive1"
    objectType = "adsk::fusion::DeriveFeature"

    def __init__(self, design, source=None, mode="honest"):
        self._design, self.mode, self.calls = design, mode, []
        self.sourceDesign = _source_design() if source is None else source
        held = [b.name for b in design.rootComponent.bRepBodies._items if b.isDerived]
        self.sourceEntities = [b for b in self.sourceDesign.rootComponent.bRepBodies._items
                               if b.name in held]
        self.documentReference = FakeDocumentReference()
        self.timelineObject = design.timeline.item(0)
        self.timelineObject.entity = self

    def _act(self, land):
        if self.mode == "raises":
            raise RuntimeError("3 : refused")
        if self.mode == "false":
            return False
        if self.mode != "ignored":
            land()
        if self.mode == "breaks":
            self.timelineObject.healthState = adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState
        if self.mode == "late":
            raise RuntimeError("3 : raised after the change")
        return True

    def setSourceEntities(self, entities, excluded):
        self.calls.append((list(entities), list(excluded)))

        def land():
            self.sourceEntities = list(entities)
            target = self._design.rootComponent.bRepBodies
            target._items = ([b for b in target._items if not b.isDerived]
                             + [BRepBody(e.name, volume=e.volume, is_derived=True) for e in entities])
        return self._act(land)

    def breakLink(self):
        self.calls.append("breakLink")

        def land():
            self.timelineObject.entity = SimpleNamespace(objectType="adsk::fusion::BaseFeature")
            params = self._design.allParameters._parameters
            params[:] = [p for p in params if not p.objectType.endswith("DerivedParameter")]
        return self._act(land)


@pytest.mark.usefixtures("body_shapes")
class TestSetSourceEntities:
    def test_a_name_resolves_in_the_source_design_not_among_the_active_bodies(self):
        design = _edit_design(local=("PS_B",))
        derive = _EditDerive(design)
        source_a, source_b, _c = derive.sourceDesign.rootComponent.bRepBodies._items
        out = _payload(io.set_source_entities(design, derive, ["PS_A", "PS_B"]))
        entities, excluded = derive.calls[0]
        assert entities[0] is source_a and entities[1] is source_b and excluded == []
        assert out["edited"] is True and out["answered"] is True
        assert (out["source_entities_before"], out["source_entities_after"]) == (
            ["PS_A"], ["PS_A", "PS_B"])
        assert (out["body_count_before"], out["body_count_after"]) == (2, 3)
        assert out["bodies_arrived"] == [{"component": "Root", "body": "PS_B"}]
        assert out["bodies_left"] == [] and out["out_of_date"] is False
        assert out["new_timeline_errors"] == [] and "Arrived: 'PS_B'." in out["note"]

    @pytest.mark.parametrize("names, source, said", [
        (["PS_X"], ("PS_A", "PS_B"), "'PS_X' matches 0 root bodies"),
        (["PS_B"], ("PS_A", "PS_B", "PS_B"), "'PS_B' matches 2 root bodies"),
        ([], ("PS_A",), "names no source body"),
    ])
    def test_a_name_without_exactly_one_source_body_is_refused(self, names, source, said):
        design = _edit_design()
        derive = _EditDerive(design, source=_source_design(source))
        res = io.set_source_entities(design, derive, names)
        assert res["isError"] is True and said in res["message"]
        assert derive.calls == []
        if names:
            assert "The source offers: 'PS_A', 'PS_B'" in res["message"]

    def test_a_source_design_that_does_not_read_is_refused_by_name(self):
        design = _edit_design(local=("PS_B",))
        derive = _EditDerive(design)
        derive.sourceDesign = None
        res = io.set_source_entities(design, derive, ["PS_B"])
        assert res["isError"] is True and "did not read its sourceDesign" in res["message"]
        assert derive.calls == []

    @pytest.mark.parametrize("mode, said, landed", [
        ("false", "setSourceEntities answered False", False),
        ("ignored", "re-read source entities are not the requested ones", False),
        ("raises", "Fusion raised: 3 : refused.", False),
        ("late", "Fusion raised: 3 : raised after the change.", True),
        ("breaks", "the timeline has new errors: 'Derive1'", True),
    ])
    def test_a_write_that_does_not_verify_is_an_error_carrying_what_landed(self, mode, said, landed):
        design = _edit_design()
        res = io.set_source_entities(design, _EditDerive(design, mode=mode), ["PS_A", "PS_B"])
        details = _details(res)
        assert said in res["message"]
        assert details["source_entities_after"] == (["PS_A", "PS_B"] if landed else ["PS_A"])
        assert details["bodies_arrived"] == ([{"component": "Root", "body": "PS_B"}] if landed
                                             else [])
        assert "edited" not in details

    def test_bodies_that_arrived_and_left_are_listed_apart(self):
        design = _edit_design(derived=("PS_A", "PS_B"))
        out = _payload(io.set_source_entities(design, _EditDerive(design), ["PS_B", "PS_C"]))
        assert out["bodies_arrived"] == [{"component": "Root", "body": "PS_C"}]
        assert out["bodies_left"] == [{"component": "Root", "body": "PS_A"}]
        assert "Arrived: 'PS_C'. Left: 'PS_A'." in out["note"]

    def test_a_rolled_back_marker_is_refused_before_the_write(self):
        design = _edit_design(marker=0)
        derive = _EditDerive(design)
        res = io.set_source_entities(design, derive, ["PS_B"])
        assert res["isError"] is True and "marker reads 0 of 1" in res["message"]
        assert derive.calls == []

    def test_sources_already_as_requested_write_nothing(self):
        design = _edit_design()
        derive = _EditDerive(design)
        out = _payload(io.set_source_entities(design, derive, ["ps_a"]))
        assert out["edited"] is False and derive.calls == []

    @pytest.mark.parametrize("token", ["NESTED:PS_A", None])
    def test_a_listed_namesake_of_the_requested_root_body_does_not_skip_the_write(self, token):
        design = _edit_design()
        derive = _EditDerive(design)
        namesake = BRepBody("PS_A", entity_token="NESTED:PS_A")
        namesake.entityToken = token
        derive.sourceEntities = [namesake]
        out = _payload(io.set_source_entities(design, derive, ["PS_A"]))
        root_body = derive.sourceDesign.rootComponent.bRepBodies._items[0]
        assert derive.calls and derive.calls[0][0][0] is root_body
        assert out["edited"] is True and out["source_identity_verified"] is True

    @pytest.mark.parametrize("token, verified, said", [
        ("OTHER", False, "re-read source entities are not the requested ones"),
        (None, None, "identities did not read, so the result is unverified"),
    ])
    def test_a_re_read_namesake_of_a_requested_entity_is_not_verified(self, token, verified, said):
        design = _edit_design()

        class _LandsNamesakes(_EditDerive):
            def setSourceEntities(self, entities, excluded):
                answered = super().setSourceEntities(entities, excluded)
                self.sourceEntities = [BRepBody(e.name, entity_token="OTHER") for e in entities]
                for listed in self.sourceEntities:
                    listed.entityToken = token
                return answered
        res = io.set_source_entities(design, _LandsNamesakes(design), ["PS_A", "PS_B"])
        details = _details(res)
        assert said in res["message"]
        assert details["source_entities_after"] == ["PS_A", "PS_B"]
        assert details["source_identity_verified"] is verified
        assert ("listed 'PS_A', 'PS_B'" in details.get("source_identity_unread", "")) is (
            verified is None)

    def test_a_requested_entity_listed_twice_is_not_the_requested_set(self):
        design = _edit_design()

        class _ListsTwice(_EditDerive):
            def setSourceEntities(self, entities, excluded):
                answered = super().setSourceEntities(entities, excluded)
                self.sourceEntities = list(entities) + list(entities[:1])
                return answered
        res = io.set_source_entities(design, _ListsTwice(design), ["PS_A", "PS_B"])
        assert _details(res)["source_identity_verified"] is False
        assert "re-read source entities are not the requested ones" in res["message"]

    def test_bodies_that_do_not_read_beforehand_refuse_before_the_write(self, monkeypatch):
        monkeypatch.setattr(io._edit_feature_common, "all_shapes", lambda design: None)
        design = _edit_design()
        derive = _EditDerive(design)
        res = io.set_source_entities(design, derive, ["PS_B"])
        assert res["isError"] is True and "Nothing was written" in res["message"]
        assert derive.calls == [] and design._computes == 0

    def test_bodies_are_judged_after_a_recompute_and_unread_ones_are_an_error(self, monkeypatch):
        design = _edit_design()
        state = _stale_until_recompute(monkeypatch, design)
        derive = _EditDerive(design)
        land = derive.setSourceEntities

        def stale_write(entities, excluded):
            state["writes"] = design._computes + state.get("lag", 1)
            return land(entities, excluded)
        monkeypatch.setattr(derive, "setSourceEntities", stale_write)
        out = _payload(io.set_source_entities(design, derive, ["PS_B"]))
        assert out["edited"] is True and out["recomputed"] is True and design._computes == 1
        assert [row["body"] for row in out["bodies_arrived"]] == ["PS_B"]
        state["lag"] = 2
        res = io.set_source_entities(design, derive, ["PS_A"])
        assert "did not re-read after the recompute" in res["message"]
        assert _details(res)["source_entities_after"] == ["PS_A"]


class _RewritesDependent(_EditDerive):
    """DECLARED, not measured: breakLink that also rewrites the expression of a dependent."""
    def breakLink(self):
        answered = super().breakLink()
        self._design.allParameters.itemByName("PP_Dep").expression = "14 mm"
        return answered


class _DropsBody(_EditDerive):
    """DECLARED, not measured: breakLink that removes one body and resizes another."""
    def breakLink(self):
        bodies = self._design.rootComponent.bRepBodies
        bodies._items = [b for b in bodies._items if b.name != "PS_A"]
        bodies._items[0].volume = 5.0
        return super().breakLink()


@pytest.mark.usefixtures("body_shapes")
class TestBreakLink:
    def test_the_reply_names_the_replacement_and_never_the_same_feature(self):
        design = _edit_design([_typed("PS_Fav_Ref", "DerivedParameter")])
        out = _payload(io.break_link(design, _EditDerive(design)))
        assert (out["kind_before"], out["kind_after"]) == ("DeriveFeature", "BaseFeature")
        assert out["same_feature"] is False and out["replaced"] is True
        assert (out["timeline_index"], out["name_after"]) == (0, "Derive1")
        assert (out["timeline_count_before"], out["timeline_count_after"]) == (1, 1)
        assert "was REPLACED" in out["note"] and "cannot restore the link" in out["note"]
        assert out["parameters_disappeared"] == ["PS_Fav_Ref"]
        assert "Parameters gone with the link: 'PS_Fav_Ref'." in out["note"]
        assert out["bodies_changed"] == [] and out["bodies_left"] == []
        assert "bodies read the same before and after" in out["note"]

    def test_a_dependent_of_a_lost_parameter_reports_both_expressions(self):
        dep = _typed("PP_Dep", "UserParameter", "PS_Fav_Ref * 2")
        design = _edit_design([dep, _typed("PS_Fav_Ref", "DerivedParameter", dependents=[dep])])
        out = _payload(io.break_link(design, _RewritesDependent(design)))
        assert out["dependents_of_disappeared"] == [{
            "name": "PP_Dep", "depended_on": "PS_Fav_Ref", "present_after": True,
            "expression_before": "PS_Fav_Ref * 2", "expression_after": "14 mm"}]
        assert "'PP_Dep' (used 'PS_Fav_Ref')" in out["note"]

    def test_bodies_that_changed_or_left_with_the_link_are_named(self):
        design = _edit_design(derived=("PS_A", "PS_B"))
        out = _payload(io.break_link(design, _DropsBody(design)))
        assert out["bodies_left"] == [{"component": "Root", "body": "PS_A"}]
        assert out["bodies_changed"] == [{"component": "Root", "body": "PS_B"}]
        assert "Left: 'PS_A'. Changed: 'PS_B'." in out["note"]

    @pytest.mark.parametrize("mode, said, replaced", [
        ("ignored", "a DeriveFeature still reads at its timeline index", False),
        ("false", "breakLink answered False", False),
        ("raises", "Fusion raised: 3 : refused.", False),
        ("late", "Fusion raised: 3 : raised after the change.", True),
        ("breaks", "the timeline has new errors: 'Derive1'", True),
    ])
    def test_a_break_that_does_not_verify_is_an_error_with_the_re_read_state(self, mode, said,
                                                                             replaced):
        design = _edit_design([_typed("PS_Fav_Ref", "DerivedParameter")])
        res = io.break_link(design, _EditDerive(design, mode=mode))
        details = _details(res)
        assert said in res["message"]
        assert details["kind_after"] == ("BaseFeature" if replaced else "DeriveFeature")
        assert details["same_feature"] is (False if replaced else None)
        assert ("was REPLACED and this function cannot restore" in res["message"]) is replaced
        assert details["parameters_disappeared"] == (["PS_Fav_Ref"] if replaced else [])

    def test_a_rolled_back_marker_is_refused_before_the_write(self):
        design = _edit_design(marker=0)
        derive = _EditDerive(design)
        res = io.break_link(design, derive)
        assert res["isError"] is True and "marker reads 0 of 1" in res["message"]
        assert derive.calls == []

    def test_a_feature_that_does_not_read_as_a_derive_is_refused(self):
        design = _edit_design()
        derive = _EditDerive(design)
        derive.timelineObject.entity = SimpleNamespace(objectType="adsk::fusion::ExtrudeFeature")
        res = io.break_link(design, derive)
        assert res["isError"] is True and "reads kind 'ExtrudeFeature'" in res["message"]
        assert derive.calls == []

    def test_a_parameter_census_that_does_not_read_refuses_before_the_write(self):
        design = _edit_design([_typed("PS_Fav_Ref", "DerivedParameter"),
                               _typed("PS_Fav_Ref", "ModelParameter")])
        derive = _EditDerive(design)
        res = io.break_link(design, derive)
        assert res["isError"] is True and "Nothing was written" in res["message"]
        assert derive.calls == []
