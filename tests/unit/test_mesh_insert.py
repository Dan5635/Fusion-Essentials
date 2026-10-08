"""Unit tests for mesh_insert.py - the STL/OBJ/3MF import and its base-feature scope."""

import adsk.fusion
import pytest

from conftest import (BRepBody, FakeBaseFeature, FakeBaseFeatures, FakeFeatures, MakeComp,
                      MeshBody, _MeshBodies, _NamedCollection, install, load_tool, make_design,
                      make_occurrence, payload)

mo = load_tool("mesh_insert")
mesh_get = load_tool("mesh_get")


class _ImportingMeshBodies(_MeshBodies):
    """comp.meshBodies where add(path, units, base_feature) performs the file import."""
    def __init__(self, existing=(), import_result=None, raise_on_add=False):
        super().__init__(existing)
        self._import_result = import_result
        self.raise_on_add = raise_on_add
        self.add_args = None

    def add(self, path, units, base_feature):
        if self.raise_on_add:
            raise RuntimeError("import failed")
        self.add_args = (path, units, base_feature)
        return self._import_result


# MeshUnits member -> the sentinel installed for it. Mocked MeshUnits answers EVERY name with a
# truthy child Mock, so only equality against one of these says which unit reached meshBodies.add.
_MESH_UNIT_SENTINELS = {"MillimeterMeshUnit": "MM", "CentimeterMeshUnit": "CM",
                        "MeterMeshUnit": "M", "InchMeshUnit": "IN", "FootMeshUnit": "FT"}


@pytest.fixture(autouse=True)
def _types(monkeypatch):
    """The adsk.fusion type identities and the MeshUnits members the import enum is read from."""
    monkeypatch.setattr(adsk.fusion, "MeshBody", MeshBody, raising=False)
    monkeypatch.setattr(adsk.fusion, "BRepBody", BRepBody, raising=False)
    monkeypatch.setattr(adsk.fusion, "BaseFeature", FakeBaseFeature, raising=False)
    for member, sentinel in _MESH_UNIT_SENTINELS.items():
        monkeypatch.setattr(adsk.fusion.MeshUnits, member, sentinel, raising=False)


@pytest.fixture(autouse=True)
def _file_present(monkeypatch):
    """The import path exists; the missing-file guard is driven by overriding this."""
    monkeypatch.setattr(mo.os.path, "isfile", lambda p: True)


def _comp(name="Comp", mesh_bodies=None, base_feature=None, occurrences=()):
    """A component whose meshBodies is the importing collection and whose features carry the scope."""
    comp = MakeComp(name, occurrences=occurrences)
    comp.meshBodies = mesh_bodies if mesh_bodies is not None else _ImportingMeshBodies()
    comp.features = FakeFeatures(base_features=FakeBaseFeatures(made=base_feature))
    return comp


def _wire(comp, design_type=0, edit_object=None, all_components=None):
    """Wire a design rooted at `comp` into the tool through both design seams."""
    return install(mo, make_design(comp=comp, design_type=design_type,
                                   active_edit_object=edit_object,
                                   all_components=all_components))


class TestMeshInsert:

    def test_gates_on_base_feature_scope_in_parametric_when_scope_cannot_open(self):
        # Parametric design where baseFeatures.add() returns None -> run_in_base_feature cannot open the
        # scope -> honest error (NOT a false-negative recheck guard).
        mb_coll = _ImportingMeshBodies(import_result=_NamedCollection([MeshBody("Imported")]))
        comp = _comp(mesh_bodies=mb_coll)
        comp.features = FakeFeatures(base_features=FakeBaseFeatures(made=False))
        _wire(comp, design_type=1)                                    # parametric
        res = mo.handler(file_path="C:/scan.stl", units="mm")
        assert res["isError"] is True
        assert "base-feature scope" in res["message"].lower()

    def test_parametric_succeeds_even_when_scope_is_invisible_to_a_guard(self):
        # An open base-feature scope is undetectable (activeEditObject is None even though the scope is
        # open), so run_in_base_feature must NOT re-check it after startEdit. The insert succeeds when
        # meshBodies.add returns a non-empty list, regardless of the unobservable scope state.
        bf = FakeBaseFeature()
        mb_coll = _ImportingMeshBodies(import_result=_NamedCollection([MeshBody("Imported", tri=777)]))
        comp = _comp(mesh_bodies=mb_coll, base_feature=bf)
        _wire(comp, design_type=1, edit_object=None)     # scope invisible to any guard
        out = payload(mo.handler(file_path="C:/scan.stl"))
        assert out["imported"] is True                              # no false "could not open scope"
        assert out["base_feature"] == "BaseFeature1"
        assert out["bodies"][0]["triangle_count"] == 777
        # the import ran INSIDE the helper's atomic scope (opened AND finished)
        assert bf._starts == 1 and bf._finishes == 1
        assert mb_coll.add_args[2] is bf

    def test_works_in_parametric_with_visible_scope(self):
        # Parametric: the import runs inside the helper's base-feature scope and succeeds.
        bf = FakeBaseFeature()
        mb_coll = _ImportingMeshBodies(import_result=_NamedCollection([MeshBody("Imported", tri=500)]))
        comp = _comp(mesh_bodies=mb_coll, base_feature=bf)
        _wire(comp, design_type=1, edit_object=bf)
        out = payload(mo.handler(file_path="C:/scan.stl", units="mm", name="MyScan"))
        assert out["imported"] is True
        assert out["base_feature"] == "BaseFeature1"
        assert out["bodies"][0]["triangle_count"] == 500
        # the import was wrapped in startEdit/finishEdit on the helper-opened base feature
        assert bf._starts == 1 and bf._finishes == 1
        assert mb_coll.add_args[0] == "C:/scan.stl" and mb_coll.add_args[2] is bf

    def test_works_in_direct_without_scope(self):
        # DIRECT design -> NO base-feature scope; baseOrFormFeature passed as None; import succeeds.
        mb_coll = _ImportingMeshBodies(import_result=_NamedCollection([MeshBody("Imported", tri=320)]))
        comp = _comp(mesh_bodies=mb_coll, base_feature=FakeBaseFeature())
        _wire(comp, design_type=0)                                   # direct
        out = payload(mo.handler(file_path="C:/scan.obj"))
        assert out["imported"] is True
        assert out["base_feature"] is None                           # no scope in direct
        assert mb_coll.add_args[2] is None                           # baseOrFormFeature was None

    def test_bad_extension_rejected(self):
        _wire(_comp())
        res = mo.handler(file_path="C:/model.step")
        assert res["isError"] is True and ".stl" in res["message"]

    def test_missing_file_rejected(self, monkeypatch):
        _wire(_comp())
        monkeypatch.setattr(mo.os.path, "isfile", lambda p: False)
        res = mo.handler(file_path="C:/nope.stl")
        assert res["isError"] is True and "not found" in res["message"].lower()

    def test_named_target_component_imports_into_it(self):
        # target_component=<name> resolves through the OCCURRENCE kind and imports into THAT
        # component, not the active one - a bare name still lands via the substring fallback over
        # the occurrence's own name ('SubPart:1').
        sub_coll = _ImportingMeshBodies(import_result=_NamedCollection([MeshBody("Imported", tri=64)]))
        sub = _comp("SubPart", mesh_bodies=sub_coll, base_feature=FakeBaseFeature())
        occ = make_occurrence("SubPart:1", component=sub)
        root = _comp("Root", base_feature=FakeBaseFeature(), occurrences=[occ])
        _wire(root, design_type=0)
        out = payload(mo.handler(file_path="C:/scan.stl", target_component="SubPart"))
        assert out["imported"] is True
        assert out["component"] == "SubPart"
        assert sub_coll.add_args is not None        # the import went into SubPart's collection
        assert root.meshBodies.add_args is None     # NOT the active/root component

    def test_target_component_accepts_an_occurrence_path_spelling(self):
        # THE BITE: an occurrence fullPathName ('CHECK - STL units:1') is a spelling every other
        # tool wired to OccurrenceRef accepts - the hand-rolled component-name walk refused it.
        sub_coll = _ImportingMeshBodies(import_result=_NamedCollection([MeshBody("Imported")]))
        sub = _comp("CHECK - STL units", mesh_bodies=sub_coll, base_feature=FakeBaseFeature())
        occ = make_occurrence("CHECK - STL units:1", component=sub)
        root = _comp("Root", base_feature=FakeBaseFeature(), occurrences=[occ])
        _wire(root, design_type=0)
        out = payload(mo.handler(file_path="C:/scan.stl",
                                 target_component="CHECK - STL units:1"))
        assert out["imported"] is True
        assert out["component"] == "CHECK - STL units"
        assert sub_coll.add_args is not None

    def test_duplicate_target_component_name_refused_no_import(self):
        # two occurrences whose own names both carry 'SubPart': which one a bare name means is
        # refused rather than guessed at, naming the occurrences it could mean.
        a = _comp("SubPart", base_feature=FakeBaseFeature())
        b = _comp("SubPart", base_feature=FakeBaseFeature())
        occ_a = make_occurrence("SubPart:1", component=a)
        occ_b = make_occurrence("SubPart:2", component=b)
        root = _comp("Root", base_feature=FakeBaseFeature(), occurrences=[occ_a, occ_b])
        _wire(root, design_type=0)
        res = mo.handler(file_path="C:/scan.stl", target_component="SubPart")
        assert res["isError"] is True
        assert "ambiguous" in res["message"]
        assert "SubPart:1" in res["message"] and "SubPart:2" in res["message"]
        assert a.meshBodies.add_args is None and b.meshBodies.add_args is None
        assert root.meshBodies.add_args is None       # and not into the active component either

    def test_unknown_target_component_errors(self):
        root = _comp("Root", base_feature=FakeBaseFeature())
        _wire(root, design_type=0)
        res = mo.handler(file_path="C:/scan.stl", target_component="Ghost")
        assert res["isError"] is True
        assert "Ghost" in res["message"]

    def test_unknown_units_rejected(self):
        _wire(_comp(base_feature=FakeBaseFeature()))
        res = mo.handler(file_path="C:/scan.stl", units="parsec")
        assert res["isError"] is True
        assert "mm, cm, m, in, or ft" in res["message"]

    def test_empty_import_result_errors(self):
        # meshBodies.add returns an EMPTY list (file unreadable as a mesh) -> honest error
        comp = _comp(mesh_bodies=_ImportingMeshBodies(import_result=_NamedCollection()),
                     base_feature=FakeBaseFeature())
        _wire(comp, design_type=0)
        res = mo.handler(file_path="C:/scan.stl")
        assert res["isError"] is True and "no bodies" in res["message"].lower()

    def test_a_name_lands_on_the_one_body_that_arrived(self):
        mb = MeshBody("Imported")
        comp = _comp(mesh_bodies=_ImportingMeshBodies(import_result=_NamedCollection([mb])),
                     base_feature=FakeBaseFeature())
        _wire(comp, design_type=0)
        out = payload(mo.handler(file_path="C:/scan.stl", name="MyScan"))
        assert out["name_applied"] is True
        assert mb.name == "MyScan" and out["bodies"][0]["name"] == "MyScan"

    def test_a_name_a_multi_body_import_cannot_take_is_declined_with_the_count(self):
        # A name addresses ONE body. Dropping it silently on a 2-body import returns ok, and the
        # caller then looks up a mesh by a name no body carries.
        a, b = MeshBody("Imported1"), MeshBody("Imported2")
        comp = _comp(mesh_bodies=_ImportingMeshBodies(import_result=_NamedCollection([a, b])),
                     base_feature=FakeBaseFeature())
        _wire(comp, design_type=0)
        out = payload(mo.handler(file_path="C:/scan.3mf", name="MyScan"))
        assert out["name_applied"] is False
        assert a.name == "Imported1" and b.name == "Imported2"
        assert "landed 2 mesh bodies" in out["note"] and "design_set_name" in out["note"]

    def test_an_import_with_no_name_asked_for_publishes_no_name_verdict(self):
        comp = _comp(mesh_bodies=_ImportingMeshBodies(
            import_result=_NamedCollection([MeshBody("Imported")])), base_feature=FakeBaseFeature())
        _wire(comp, design_type=0)
        assert "name_applied" not in payload(mo.handler(file_path="C:/scan.stl"))

    def test_import_failure_surfaces_not_swallowed(self):
        # meshBodies.add raises -> must become an error, NOT a false success (no safe() around mutation)
        comp = _comp(mesh_bodies=_ImportingMeshBodies(raise_on_add=True), base_feature=FakeBaseFeature())
        _wire(comp, design_type=0)
        res = mo.handler(file_path="C:/scan.stl")
        assert res["isError"] is True and "import failed" in res["message"]


class TestMeshInsertStats:

    def _insert(self, units="mm", area=6.0, volume=1.0, existing=()):
        return self._insert_with_collection(units, area, volume, existing)[0]

    def _insert_with_collection(self, units="mm", area=6.0, volume=1.0, existing=()):
        imported = MeshBody("Imported", area=area, volume=volume)
        mb_coll = _ImportingMeshBodies(existing=existing or [imported],
                              import_result=_NamedCollection([imported]))
        comp = _comp(mesh_bodies=mb_coll, base_feature=FakeBaseFeature())
        _wire(comp, design_type=0)
        out = payload(mo.handler(file_path="C:/scan.stl", units=units))
        return out, mb_coll

    def test_each_unit_key_pairs_its_import_enum_with_its_own_factor(self):
        # ONE table drives both halves: the MeshUnits enum handed to meshBodies.add AND the factor
        # the reported stats are scaled by. A row whose enum and factor belong to different units
        # imports at one scale and reports at another - so both are asserted per key, against
        # cm-per-unit restated here rather than read from the tool.
        rows = [("mm", "MM", 0.1), ("cm", "CM", 1.0), ("m", "M", 100.0),
                ("in", "IN", 2.54), ("inch", "IN", 2.54), ("ft", "FT", 30.48)]
        for key, enum_sentinel, cm_per_unit in rows:
            out, coll = self._insert_with_collection(units=key, area=6.0, volume=1.0)
            assert coll.add_args[1] == enum_sentinel, f"{key} imported as {coll.add_args[1]}"
            assert out["units"] == key
            assert abs(out["bodies"][0]["area"] - round(6.0 / cm_per_unit ** 2, 6)) < 1e-6, key
            assert abs(out["bodies"][0]["volume"] - round(1.0 / cm_per_unit ** 3, 6)) < 1e-6, key

    def test_the_units_enum_matches_the_unit_table(self):
        # The enum IS the table the handler dispatches through, so every key it accepts is on the
        # wire - 'inch' rides beside 'in'. A hand-edited enum drifting from the table fails here.
        assert mo.tool.input_schema["properties"]["units"]["enum"] == list(mo._MESH_UNIT_TABLE)

    def test_every_advertised_unit_dispatches(self):
        # The rows come from the table, so a key added there forces one here. Each must reach the
        # MeshUnits member its own row names - a key the import cannot serve is one the wire
        # promised and the tool declines.
        for key, (member, _cm_per_unit) in mo._MESH_UNIT_TABLE.items():
            assert member in _MESH_UNIT_SENTINELS, f"install a MeshUnits sentinel for {member}"
            out, coll = self._insert_with_collection(units=key)
            assert out["units"] == key, key
            assert coll.add_args[1] == _MESH_UNIT_SENTINELS[member], key

    def test_area_and_volume_are_scaled_into_the_reported_units(self):
        out = self._insert(units="mm", area=6.0, volume=1.0)      # cm^2, cm^3
        assert out["units"] == "mm"
        assert abs(out["bodies"][0]["area"] - 600.0) < 1e-6       # 6 cm^2 -> 600 mm^2
        assert abs(out["bodies"][0]["volume"] - 1000.0) < 1e-6    # 1 cm^3 -> 1000 mm^3

    def test_the_same_body_reads_the_same_from_mesh_get(self):
        # the two tools' figures for ONE body must agree; a raw-cm insert payload disagrees with
        # mesh_get by a factor of 100 (area) / 1000 (volume) on the identical mesh.
        out = self._insert(units="mm", area=6.0, volume=1.0)
        listed = payload(mesh_get.handler(target="", units="mm"))["meshes"][0]
        assert out["bodies"][0]["area"] == listed["area"]
        assert out["bodies"][0]["volume"] == listed["volume"]

    def test_inch_authored_units_scale_by_the_shared_factor(self):
        out = self._insert(units="in", area=2.54 ** 2, volume=2.54 ** 3)
        assert abs(out["bodies"][0]["area"] - 1.0) < 1e-6         # 1 in^2
        assert abs(out["bodies"][0]["volume"] - 1.0) < 1e-6       # 1 in^3

    def test_metre_authored_units_scale_too(self):
        # m/ft are outside the shared mm/cm/in length kind, so a scaling path that only knew that
        # kind would leave a metre-authored file's stats in raw cm.
        out = self._insert(units="m", area=20000.0, volume=1_000_000.0)
        assert abs(out["bodies"][0]["area"] - 2.0) < 1e-6         # 2 m^2
        assert abs(out["bodies"][0]["volume"] - 1.0) < 1e-6       # 1 m^3

    def test_foot_authored_units_scale_too(self):
        out = self._insert(units="ft", area=30.48 ** 2, volume=30.48 ** 3)
        assert abs(out["bodies"][0]["area"] - 1.0) < 1e-6         # 1 ft^2
        assert abs(out["bodies"][0]["volume"] - 1.0) < 1e-6       # 1 ft^3


class _DataBody(MeshBody):
    """A mesh body whose polygon mesh is the one handed to it."""
    polygon_mesh = None
    mesh = property(lambda self: self.polygon_mesh)


class _DataMeshBodies(_MeshBodies):
    """comp.meshBodies where addByTriangleMeshData lands one body reading the data back - shifted
    by `drift` cm, with `indices` in place of the ones sent, or raising `refuses`."""
    def __init__(self, drift=0.0, indices=None, refuses=None, lands=True):
        super().__init__(())
        self.drift, self.indices, self.refuses, self.lands = drift, indices, refuses, lands
        self.sent = None

    def addByTriangleMeshData(self, coords, idx, normals, normal_idx):
        import types
        self.sent = (list(coords), list(idx), list(normals), list(normal_idx))
        if self.refuses:
            raise RuntimeError(self.refuses)
        body = _DataBody("Mesh1")
        body.polygon_mesh = types.SimpleNamespace(
            nodeCoordinatesAsDouble=[c + self.drift for c in coords],
            triangleNodeIndices=list(idx) if self.indices is None else self.indices,
            normalVectorsAsDouble=[])
        if self.lands:
            self._items.append(body)
        return body


_TETRA = {"vertices": [[0, 0, 0], [30, 0, 0], [0, 20, 0], [0, 0, 10]],
          "triangles": [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]}


def _data_rig(**kw):
    bodies = _DataMeshBodies(**kw)
    comp = _comp(mesh_bodies=bodies)
    _wire(comp)
    return bodies, comp


class TestMeshData:

    def test_the_data_is_sent_flat_in_cm_and_read_back_before_success(self):
        bodies, _comp_ = _data_rig()
        out = payload(mo.handler(data=_TETRA, name="Tetra"))
        coords, idx, normals, normal_idx = bodies.sent
        assert coords[3:6] == [3.0, 0.0, 0.0] and idx[:3] == [0, 2, 1] and normals == normal_idx == []
        assert out["imported"] is True and (out["vertices"], out["triangles"]) == (4, 4)
        assert out["source"] == "data" and out["name_applied"] is True

    @pytest.mark.parametrize("kw", [{"drift": 0.01}, {"indices": [0, 1, 2] * 4}, {"lands": False}])
    def test_a_body_that_does_not_read_back_as_sent_is_an_error(self, kw):
        _data_rig(**kw)
        res = mo.handler(data=_TETRA)
        assert res["isError"] is True and ("does not read back" in res["message"]
                                           or "did not add exactly one" in res["message"])

    @pytest.mark.parametrize("patch,said", [
        ({"triangles": [[0, 1, 4]]}, "data.triangles[0] is [0, 1, 4]"),
        ({"triangles": [[0, 1, 1]]}, "three different vertices"),
        ({"triangles": [[0, 1, -2]]}, "whole numbers of at least 0"),
        ({"triangles": []}, "at least 3 vertices and 1 triangle"),
        ({"vertices": [[0, 0, float("nan")], [1, 0, 0], [0, 1, 0]]}, "three finite numbers"),
        ({"normals": [[0, 0, 1]], "normal_indices": [[0, 0, 0]] * 4}, "['normal_indices', 'normals']"),
        ({"faces": []}, "['faces']")])
    def test_bad_data_is_refused_before_any_base_feature_opens(self, patch, said):
        bodies, comp = _data_rig()
        _wire(comp, design_type=1)
        opened = []
        comp.features.baseFeatures.add = lambda: opened.append(1)
        res = mo.handler(data={**_TETRA, **patch})
        assert res["isError"] is True and said in res["message"]
        assert bodies.sent is None and opened == []

    def test_a_file_and_data_together_or_neither_are_refused(self):
        _data_rig()
        assert "got both" in mo.handler(file_path="a.stl", data=_TETRA)["message"]
        assert "got neither" in mo.handler()["message"]

    def test_a_refused_add_names_the_native_message(self):
        _data_rig(refuses="3 : invalid parameter coordinates")
        res = mo.handler(data=_TETRA)
        assert res["isError"] is True and "3 : invalid parameter coordinates" in res["message"]

    def test_inch_data_is_scaled_to_cm(self):
        bodies, _comp_ = _data_rig()
        payload(mo.handler(data=_TETRA, units="in"))
        assert bodies.sent[0][3] == pytest.approx(76.2)
