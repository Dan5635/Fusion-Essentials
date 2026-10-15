"""Unit tests for ``_data_common.py`` - the cloud data-model path and reference substrate.

These resolve user-supplied folder paths ("Parts/Fixtures/Vises") against the data
hierarchy. Bugs here send files to the wrong folder silently, so the boundaries (empty
path, stray slashes, mixed separators, case-insensitive match, missing segment) are
exactly what to pin down - plus the AI-agent save marker and resolve_file_reference's
refusal when a NAME matches several files. No live Fusion needed.
"""

import json

import pytest

from conftest import (FakeApplication, FakeData, FakeDataFile, FakeDataFolder, FakeDataProject,
                      FakeFusionDocument, load_tool)

dm = load_tool("_data_common")


def _file(name, urn):
    """One cloud file carrying the fields the name walk collects off it."""
    return FakeDataFile(name, file_id=urn, version_id=urn + "?version=1", extension="txt",
                        web_url="https://x/" + urn)


class _BlindNameFile(FakeDataFile):
    @property
    def name(self):
        raise RuntimeError("3 : file name unreadable")


@pytest.fixture
def project_pair(monkeypatch):
    """An earlier name match and a later exact-ID match, each carrying the same file name."""
    wrong_file = _file("same.txt", "urn:wrong")
    right_file = _file("same.txt", "urn:right")
    wrong = FakeDataProject(
        "Requested Name", project_id="project-wrong",
        root_folder=FakeDataFolder("Wrong Root", files=[wrong_file], is_root=True))
    right = FakeDataProject(
        "Other Name", project_id="project-right",
        root_folder=FakeDataFolder("Right Root", files=[right_file], is_root=True))
    data = FakeData(projects=[wrong, right],
                    files_by_id={"urn:wrong": wrong_file, "urn:right": right_file})
    app = FakeApplication(data=data)
    data_read = load_tool("_data_read")
    monkeypatch.setattr(dm, "app", app)
    monkeypatch.setattr(data_read, "app", app)
    return data, wrong, right, load_tool("data_get")


class TestProjectIdPrecedence:
    def test_explicit_id_outranks_a_conflicting_name_through_data_get(self, project_pair):
        _data, _wrong, right, data_get = project_pair
        result = data_get.handler(project="Requested Name", project_id="project-right")
        assert result["isError"] is False, result
        out = json.loads(result["content"][0]["text"])
        assert out["project"] == {"name": right.name, "id": right.id}
        assert [row["name"] for row in out["files"]] == ["same.txt"]
        assert out["files"][0]["id"] == "urn:right"

    def test_a_missing_explicit_id_never_falls_back_to_the_name(self, project_pair):
        _data, wrong, right, _data_get = project_pair
        got, meta, err = dm.resolve_file_reference(
            "same.txt", project=wrong.name, project_id="project-missing")
        assert got is None and meta is None
        assert "Project not found: project-missing" in err
        assert wrong.name in err and right.name in err

    def test_name_only_matching_remains_case_insensitive(self, project_pair):
        data, wrong, _right, _data_get = project_pair
        got, _available = dm._find_project(data, name="requested name")
        assert got is wrong

    def test_duplicate_exact_project_names_are_refused_naming_each_candidate_id(self):
        data = FakeData(projects=[FakeDataProject("Twin", project_id="p1"),
                                  FakeDataProject("Other", project_id="p3"),
                                  FakeDataProject("twin", project_id="p2")])
        with pytest.raises(ValueError, match="matches 2 projects") as refused:
            dm._find_project(data, name="Twin")
        text = str(refused.value)
        assert "'Twin' (id p1); 'twin' (id p2)." in text and "Other" not in text
        assert text.endswith("Refusing to guess which; pass an exact project_id.")

    def test_exact_project_id_does_not_read_unrelated_names(self):
        class BlindNameProject:
            id = "p-hidden"

            @property
            def name(self):
                raise RuntimeError("name unreadable")

        target = FakeDataProject("Target", project_id="p-target")
        data = FakeData(projects=[BlindNameProject(), target])
        got, _available = dm._find_project(data, name="Anything", project_id="p-target")
        assert got is target

    def test_unreadable_name_census_refuses_even_when_a_hit_was_seen(self):
        class BlindNameProject:
            id = "p-hidden"

            @property
            def name(self):
                raise RuntimeError("name unreadable")

        data = FakeData(projects=[FakeDataProject("Twin", project_id="p1"),
                                  BlindNameProject()])
        with pytest.raises(RuntimeError, match="name listing is incomplete"):
            dm._find_project(data, name="Twin")

    @pytest.mark.parametrize("problem", ["duplicate", "incomplete"])
    def test_project_lookup_failure_keeps_cause_and_offers_supported_file_id_route(
            self, monkeypatch, problem):
        file = _file("part.f3d", "urn:lineage")
        root = FakeDataFolder("Root", files=[file], is_root=True)
        project = FakeDataProject("Twin", project_id="p1", root_folder=root)
        if problem == "duplicate":
            projects = [project, FakeDataProject("twin", project_id="p2")]
            cause = "matches 2 projects"
        else:
            class BlindNameProject:
                id = "p-hidden"

                @property
                def name(self):
                    raise RuntimeError("synthetic unread project name")

            projects = [project, BlindNameProject()]
            cause = "name listing is incomplete"
        data = FakeData(projects=projects, files_by_id={"urn:lineage": file})
        monkeypatch.setattr(dm, "app", FakeApplication(data=data))

        got, meta, err = dm.resolve_file_reference("part.f3d", project="Twin")
        assert got is None and meta is None
        assert cause in err
        assert ("Get the file's lineage URN with data_get(project_id=<id>), then pass it "
                "as 'file'.") in err


class TestImmediateFolderFileCensus:
    def test_an_unreadable_collection_is_not_an_empty_folder(self):
        folder = FakeDataFolder("Root", is_root=True, files_raise="3 : listing unreadable")
        matches, problem = dm._files_in_folder_by_name(folder, "Part")
        assert matches == [] and "child-file listing failed" in problem
        assert dm._file_in_folder_by_name(folder, "Part") == (None, problem)

    def test_an_unreadable_name_preserves_known_matches_but_refuses_resolution(self):
        known = _file("Part", "urn:known")
        folder = FakeDataFolder("Root", files=[known], is_root=True)
        folder._files.append(_BlindNameFile("Hidden", file_id="urn:hidden"))
        matches, problem = dm._files_in_folder_by_name(folder, "Part")
        assert matches == [known]
        assert "1 child file name(s) were unreadable" in problem and "urn:known" in problem
        assert dm._file_in_folder_by_name(folder, "Part") == (None, problem)

    def test_iteration_failure_preserves_a_readable_prefix_as_partial_only(self):
        known = _file("Part", "urn:known")

        class _Files:
            def asArray(self):
                def rows():
                    yield known
                    raise RuntimeError("3 : iteration unreadable")
                return rows()

        folder = type("Folder", (), {"dataFiles": _Files(), "isRoot": True})()
        matches, problem = dm._files_in_folder_by_name(folder, "Part")
        assert matches == [known] and "iterating its child-file listing failed" in problem
        assert dm._file_in_folder_by_name(folder, "Part") == (None, problem)


# ── _split_path: tolerant segmentation ─────────────────────────────────────

class TestSplitPath:
    def test_empty_is_no_segments(self):
        assert dm._split_path("") == []
        assert dm._split_path(None) == []

    def test_simple_path(self):
        assert dm._split_path("Parts/Fixtures") == ["Parts", "Fixtures"]

    def test_backslashes_normalized(self):
        assert dm._split_path("Parts\\Fixtures\\Vises") == ["Parts", "Fixtures", "Vises"]

    def test_stray_and_leading_trailing_slashes_dropped(self):
        assert dm._split_path("/Parts//Fixtures/") == ["Parts", "Fixtures"]

    def test_segments_are_trimmed(self):
        assert dm._split_path("  Parts / Fixtures  ") == ["Parts", "Fixtures"]


# ── _resolve_folder_path: walk without creating ────────────────────────────

class TestResolveFolderPath:
    def _tree(self):
        root = FakeDataFolder("Root", is_root=True)
        root.dataFolders.add("Parts").dataFolders.add("Fixtures")
        return root

    def test_empty_segments_resolves_to_root(self):
        root = self._tree()
        folder, missing = dm._resolve_folder_path(root, [])
        assert folder is root
        assert missing is None

    def test_full_existing_path_resolves(self):
        root = self._tree()
        folder, missing = dm._resolve_folder_path(root, ["Parts", "Fixtures"])
        assert folder.name == "Fixtures"
        assert missing is None

    def test_case_insensitive_match(self):
        root = self._tree()
        folder, missing = dm._resolve_folder_path(root, ["parts", "FIXTURES"])
        assert folder.name == "Fixtures"
        assert missing is None

    def test_missing_segment_reported(self):
        root = self._tree()
        folder, missing = dm._resolve_folder_path(root, ["Parts", "Nope"])
        assert folder is None
        assert missing == "Nope"   # tells the caller exactly where it broke


# ── _folder_path_string: walk parents up to root ───────────────────────────

class TestFolderPathString:
    def test_builds_slash_path_excluding_root(self):
        root = FakeDataFolder("Root", is_root=True)
        fixtures = root.dataFolders.add("Parts").dataFolders.add("Fixtures")
        assert dm._folder_path_string(fixtures) == "Parts/Fixtures"

    def test_immediate_child_of_root(self):
        root = FakeDataFolder("Root", is_root=True)
        assert dm._folder_path_string(root.dataFolders.add("Parts")) == "Parts"


class _DeadActiveProject(FakeData):
    """The measured session: reading Data.activeProject RAISES while dataProjects still answers.
    The setter swallows, so the shared fake's constructor still runs."""
    @property
    def activeProject(self):
        raise RuntimeError("2 : InternalValidationError : group")

    @activeProject.setter
    def activeProject(self, value):
        pass


class TestActiveProject:
    """app.data.activeProject raises on this build, so the project is the DataProject the ACTIVE
    DOCUMENT's own DataFile hands back - the object itself, never a name looked up again."""

    def _session(self, monkeypatch, projects, owner=None, data_file=True,
                 data_class=FakeData):
        doc = FakeFusionDocument(
            name="Part", data_file=FakeDataFile("Part", parent_project=owner) if data_file else None)
        monkeypatch.setattr(dm, "app", FakeApplication(active_document=doc,
                                                       data=data_class(projects=projects)))
        return doc

    def test_the_documents_own_project_object_is_the_one_returned(self, monkeypatch):
        owner = FakeDataProject("Home", project_id="p-doc")
        self._session(monkeypatch, [FakeDataProject("Other", project_id="p-0")], owner=owner)
        assert dm.active_project() == (owner, None)

    def test_the_dead_active_project_read_is_never_taken(self, monkeypatch):
        owner = FakeDataProject("Home", project_id="p-doc")
        self._session(monkeypatch, [owner], owner=owner, data_class=_DeadActiveProject)
        assert dm.active_project() == (owner, None)

    def test_a_hub_sibling_of_the_same_name_is_not_the_answer(self, monkeypatch):
        # identity is the project's id, not its name: two projects can carry one name, and a
        # by-name re-find would hand a part search the WRONG project's root folder.
        owner = FakeDataProject("Home", project_id="p-doc")
        self._session(monkeypatch, [FakeDataProject("Home", project_id="p-1"),
                                    FakeDataProject("Home", project_id="p-2")], owner=owner)
        proj, problem = dm.active_project()
        assert proj is owner and proj.id == "p-doc" and problem is None

    def test_a_project_the_hub_list_does_not_carry_still_resolves(self, monkeypatch):
        owner = FakeDataProject("Home", project_id="p-doc")
        self._session(monkeypatch, [], owner=owner)
        assert dm.active_project() == (owner, None)

    def test_an_active_document_with_no_data_file_names_that_read(self, monkeypatch):
        self._session(monkeypatch, [FakeDataProject("Home")], data_file=False)
        proj, problem = dm.active_project()
        assert proj is None and "no cloud data file" in problem and "doc_save_as" in problem

    def test_a_data_file_answering_no_parent_project_names_that_read(self, monkeypatch):
        self._session(monkeypatch, [FakeDataProject("Home")], owner=None)
        proj, problem = dm.active_project()
        assert proj is None and "did not answer a parentProject" in problem

    def test_no_active_document_names_that_read(self, monkeypatch):
        monkeypatch.setattr(dm, "app", FakeApplication(active_document=None, data=FakeData()))
        proj, problem = dm.active_project()
        assert proj is None and "no active document" in problem


class TestAgentDescription:
    def test_prefixes_marker(self):
        assert dm._agent_description("stock sizing") == "[AI agent] stock sizing"

    def test_idempotent_no_double_prefix(self):
        once = dm._agent_description("x")
        assert dm._agent_description(once) == once

    def test_empty_is_just_the_marker(self):
        assert dm._agent_description("") == "[AI agent]"
        assert dm._agent_description(None) == "[AI agent]"


# ── resolve_file_reference: ONE file, by URN or by name-in-a-project ────────
#
# The reference every file-scoped data tool resolves through (data_get(file=...),
# data_download_file, data_move_file). A file NAME is not unique across a project's folders, so the
# behaviour that matters is the REFUSAL: several matches must return the candidates, never the first.

@pytest.fixture
def cloud(monkeypatch):
    """Install a project tree plus the URN lookup the resolver finishes through."""
    def _use(root, files_by_urn=None):
        proj = FakeDataProject("Sample Project", project_id="proj-1", root_folder=root)
        data = FakeData(projects=[proj], files_by_id=files_by_urn)
        monkeypatch.setattr(dm, "app", FakeApplication(data=data))
        return proj
    return _use


class TestNameExtension:
    def test_reads_the_extension_off_the_name(self):
        assert dm.name_extension("probe_note.txt") == "txt"
        assert dm.name_extension("Bracket Drawing.F2D") == "f2d"

    def test_a_name_without_an_extension_reports_none(self):
        # '' is the honest answer, and a real case: a Fusion design's DataFile name carries no
        # extension (measured), so the caller falls back to fileExtension rather than guessing here.
        assert dm.name_extension("Bracket") == ""
        assert dm.name_extension(None) == ""


class TestResolveFileReference:
    def _one_deep_tree(self):
        docs = FakeDataFolder("Docs", files=[_file("probe_note.txt", "urn:lin:AAA")])
        parts = FakeDataFolder("Parts", files=[_file("Vise", "urn:lin:BBB")])
        return FakeDataFolder("Root", folders=[docs, parts], is_root=True)

    def test_a_urn_resolves_without_a_project(self, cloud):
        df = _file("probe_note.txt", "urn:lin:AAA")
        cloud(self._one_deep_tree(), {"urn:lin:AAA": df})
        got, meta, err = dm.resolve_file_reference("urn:lin:AAA")
        assert err is None and got is df
        assert meta["matched_by"] == "urn"

    def test_an_unresolvable_urn_says_what_was_tried(self, cloud):
        cloud(self._one_deep_tree(), {})
        got, _meta, err = dm.resolve_file_reference("urn:lin:MISSING")
        assert got is None and "urn:lin:MISSING" in err

    def test_a_bare_name_without_a_project_is_refused(self, cloud):
        cloud(self._one_deep_tree(), {})
        got, _meta, err = dm.resolve_file_reference("probe_note.txt")
        assert got is None and "'project'" in err

    def test_a_unique_name_resolves_and_reports_its_folder(self, cloud):
        df = _file("probe_note.txt", "urn:lin:AAA")
        cloud(self._one_deep_tree(), {"urn:lin:AAA": df})
        got, meta, err = dm.resolve_file_reference(
            "probe_note.txt", project="Sample Project")
        assert err is None and got is df
        assert meta["matched_by"] == "name" and meta["folder_path"] == "Docs"

    def test_the_match_is_case_insensitive(self, cloud):
        df = _file("probe_note.txt", "urn:lin:AAA")
        cloud(self._one_deep_tree(), {"urn:lin:AAA": df})
        got, _meta, err = dm.resolve_file_reference(
            "PROBE_NOTE.TXT", project="Sample Project")
        assert err is None and got is df

    def test_a_partial_name_never_matches(self, cloud):
        # 'note' must not grab 'probe_note.txt' - a substring resolver picks the wrong file silently.
        cloud(self._one_deep_tree(), {"urn:lin:AAA": _file("probe_note.txt", "urn:lin:AAA")})
        got, _meta, err = dm.resolve_file_reference("note", project="Sample Project")
        assert got is None and "No file named 'note'" in err
        assert "probe_note.txt" in err                    # what IS there

    def test_a_name_in_two_folders_is_refused_with_both_candidates(self, cloud):
        docs = FakeDataFolder("Docs", files=[_file("notes.txt", "urn:lin:AAA")])
        parts = FakeDataFolder("Parts", files=[_file("notes.txt", "urn:lin:BBB")])
        root = FakeDataFolder("Root", folders=[docs, parts], is_root=True)
        cloud(root, {"urn:lin:AAA": _file("notes.txt", "urn:lin:AAA")})
        got, _meta, err = dm.resolve_file_reference("notes.txt", project="Sample Project")
        assert got is None                                # never the first hit
        assert "names 2 files" in err
        assert "urn:lin:AAA" in err and "urn:lin:BBB" in err
        assert "Docs" in err and "Parts" in err

    def test_a_folder_scope_disambiguates_the_same_name(self, cloud):
        wanted = _file("notes.txt", "urn:lin:BBB")
        docs = FakeDataFolder("Docs", files=[_file("notes.txt", "urn:lin:AAA")])
        parts = FakeDataFolder("Parts", files=[wanted])
        root = FakeDataFolder("Root", folders=[docs, parts], is_root=True)
        cloud(root, {"urn:lin:BBB": wanted})
        got, meta, err = dm.resolve_file_reference(
            "notes.txt", project="Sample Project", folder="Parts")
        assert err is None and got is wanted
        assert meta["folder_path"] == "Parts"

    def test_a_missing_scope_folder_is_named(self, cloud):
        cloud(self._one_deep_tree(), {})
        got, _meta, err = dm.resolve_file_reference(
            "notes.txt", project="Sample Project", folder="Nope")
        assert got is None and "missing segment 'Nope'" in err
        assert "could not be READ" not in err            # it looked, and the folder is not there

    def test_a_scope_folder_whose_siblings_will_not_read_says_unknown_not_missing(self, cloud):
        # the folder list never opened, so 'Nope' may well be there - a bare "missing segment"
        # states a verdict this walk never reached.
        cloud(FakeDataFolder("Root", is_root=True, folders_raise="cloud read failed"), {})
        got, _meta, err = dm.resolve_file_reference(
            "notes.txt", project="Sample Project", folder="Nope")
        assert got is None
        assert "could not be READ" in err and "unknown" in err

    def test_an_unknown_project_lists_the_ones_there_are(self, cloud):
        cloud(self._one_deep_tree(), {})
        got, _meta, err = dm.resolve_file_reference("notes.txt", project="Ghost")
        assert got is None and "Sample Project" in err

    def test_a_match_inside_a_capped_listing_is_refused(self, cloud, monkeypatch):
        # A capped prefix cannot establish that the one observed file name is unique.
        import mcpServer.tools._data_read as data_read
        df = _file("probe_note.txt", "urn:lin:AAA")
        docs = FakeDataFolder("Docs", files=[df, _file("other.txt", "urn:lin:BBB")])
        cloud(FakeDataFolder("Root", folders=[docs], is_root=True), {"urn:lin:AAA": df})
        monkeypatch.setattr(data_read, "_MAX_FILES", 1)
        got, meta, err = dm.resolve_file_reference(
            "probe_note.txt", project="Sample Project")
        assert got is None and meta is None
        assert "name census is incomplete" in err and "reached its cap" in err

    def test_a_readable_hit_with_an_unreadable_file_name_is_refused(self, cloud):
        df = _file("probe_note.txt", "urn:lin:AAA")
        docs = FakeDataFolder("Docs", files=[df], is_root=True)
        docs._files.append(_BlindNameFile("hidden.txt", file_id="urn:lin:HIDDEN"))
        cloud(docs, {"urn:lin:AAA": df})
        got, meta, err = dm.resolve_file_reference("probe_note.txt", project="Sample Project")
        assert got is None and meta is None
        assert "name census is incomplete" in err and "1 file name(s) could not be read" in err

    def test_a_complete_listing_is_not_flagged(self, cloud):
        df = _file("probe_note.txt", "urn:lin:AAA")
        cloud(self._one_deep_tree(), {"urn:lin:AAA": df})
        _got, meta, _err = dm.resolve_file_reference(
            "probe_note.txt", project="Sample Project")
        assert meta["scope_truncated"] is False

    def test_an_empty_reference_is_refused(self, cloud):
        cloud(self._one_deep_tree(), {})
        got, _meta, err = dm.resolve_file_reference("")
        assert got is None and "Provide 'file'" in err


class TestIdentifierVsName:
    """Which ROUTE a reference takes - the URN/URL lookup or the project-scoped name search. The
    test is a PREFIX test: a file NAME may perfectly well start with 'http' or carry '://', and
    sending one down the URN route loses the name search it needed (and the names in the miss)."""

    def _tree_with(self, name, urn):
        docs = FakeDataFolder("Docs", files=[_file(name, urn)])
        return FakeDataFolder("Root", folders=[docs], is_root=True)

    def test_a_name_beginning_with_http_is_still_a_name(self, cloud):
        df = _file("httpd-mount.f3d", "urn:lin:AAA")
        cloud(self._tree_with("httpd-mount.f3d", "urn:lin:AAA"), {"urn:lin:AAA": df})
        got, meta, err = dm.resolve_file_reference(
            "httpd-mount.f3d", project="Sample Project")
        assert err is None and got is not None
        assert meta["matched_by"] == "name"

    def test_a_name_carrying_a_scheme_separator_is_still_a_name(self, cloud):
        df = _file("rev2://draft.f3d", "urn:lin:BBB")
        cloud(self._tree_with("rev2://draft.f3d", "urn:lin:BBB"), {"urn:lin:BBB": df})
        got, meta, err = dm.resolve_file_reference(
            "rev2://draft.f3d", project="Sample Project")
        assert err is None and got is not None and meta["matched_by"] == "name"

    def test_a_name_lookalike_without_a_project_gets_the_name_refusal(self, cloud):
        # The refusal must be the one that tells the agent to pass 'project' - not the URN miss.
        cloud(self._tree_with("httpd-mount.f3d", "urn:lin:AAA"), {})
        got, _meta, err = dm.resolve_file_reference("httpd-mount.f3d")
        assert got is None and "'project'" in err

    def test_a_web_url_still_takes_the_urn_route(self, cloud):
        cloud(self._tree_with("Vise", "urn:lin:BBB"), {})
        got, _meta, err = dm.resolve_file_reference(
            "https://fusion360.autodesk.com/projects/x/data/urn:lin:MISSING")
        assert got is None and "No cloud file resolves from" in err

    def test_a_urn_still_takes_the_urn_route(self, cloud):
        cloud(self._tree_with("Vise", "urn:lin:BBB"), {})
        got, _meta, err = dm.resolve_file_reference("urn:lin:MISSING")
        assert got is None and "No cloud file resolves from" in err


class TestResolveFileReferenceWithUnreadableFolders:
    """A folder that would not enumerate is a HOLE in the search space, not an empty folder. The
    same walk that lists files is what resolves a name, so a swallowed failure turns "I did not
    look there" into "it is not there" - and turns an ambiguity into a confident unique match. Every
    answer built on a partial walk has to say so."""

    def _dead_files_folder(self, name="Archive"):
        """A folder whose dataFiles enumeration RAISES - a permission-blocked or mid-sync folder.
        Its SUBFOLDERS still read, so only its own files go missing."""
        return FakeDataFolder(name, files_raise="3 : folder could not be enumerated")

    def _dead_subfolders_folder(self, name="Archive"):
        """A folder whose dataFolders enumeration raises: the ENTIRE subtree beneath it is
        unsearched, which is the larger hole of the two."""
        return FakeDataFolder(name, folders_raise="3 : subfolders could not be enumerated")

    def _tree_with_a_dead_folder(self, dead=None):
        docs = FakeDataFolder("Docs", files=[_file("probe_note.txt", "urn:lin:AAA")])
        dead = self._dead_files_folder() if dead is None else dead
        return FakeDataFolder("Root", folders=[docs, dead], is_root=True)

    def test_a_miss_says_a_folder_went_unsearched(self, cloud):
        cloud(self._tree_with_a_dead_folder(), {})
        got, _meta, err = dm.resolve_file_reference(
            "ghost.txt", project="Sample Project")
        assert got is None
        assert "name census is incomplete" in err
        assert "1 folder(s) could not be read" in err
        assert "Archive" in err                       # WHICH hole
        assert "Pass the file's lineage id" in err

    def test_an_ambiguity_refusal_carries_the_same_caveat(self, cloud):
        # Two hits already refuse; the caveat still matters because a THIRD could be in the hole,
        # so the candidate list the caller picks from may be incomplete.
        docs = FakeDataFolder("Docs", files=[_file("notes.txt", "urn:lin:AAA")])
        parts = FakeDataFolder("Parts", files=[_file("notes.txt", "urn:lin:BBB")])
        root = FakeDataFolder("Root", folders=[docs, parts, self._dead_files_folder()],
                              is_root=True)
        cloud(root, {})
        got, _meta, err = dm.resolve_file_reference(
            "notes.txt", project="Sample Project")
        assert got is None and "name census is incomplete" in err
        assert "Matching files read so far" in err
        assert "Archive" in err

    def test_a_unique_match_with_a_hole_is_refused(self, cloud):
        # A second file of that name could be sitting in the folder that never opened.
        df = _file("probe_note.txt", "urn:lin:AAA")
        cloud(self._tree_with_a_dead_folder(), {"urn:lin:AAA": df})
        got, meta, err = dm.resolve_file_reference(
            "probe_note.txt", project="Sample Project")
        assert got is None and meta is None
        assert "name census is incomplete" in err and "Archive" in err

    def test_a_fully_readable_project_reports_no_hole(self, cloud):
        docs = FakeDataFolder("Docs", files=[_file("probe_note.txt", "urn:lin:AAA")])
        df = _file("probe_note.txt", "urn:lin:AAA")
        cloud(FakeDataFolder("Root", folders=[docs], is_root=True), {"urn:lin:AAA": df})
        got, meta, err = dm.resolve_file_reference(
            "probe_note.txt", project="Sample Project")
        assert err is None and got is df
        assert meta["folders_unreadable"] == 0

    def test_an_unreadable_SUBFOLDER_list_is_recorded_too(self, cloud):
        # The bigger hole: the folder's own files read fine, but its whole SUBTREE is unreachable.
        # Recording only the dataFiles failure would report this walk as complete.
        cloud(self._tree_with_a_dead_folder(self._dead_subfolders_folder()), {})
        got, _meta, err = dm.resolve_file_reference(
            "ghost.txt", project="Sample Project")
        assert got is None
        assert "1 folder(s) could not be read" in err
        assert "Archive" in err

    def test_the_named_paths_are_capped_while_the_count_stays_complete(self, cloud):
        # The names are a hint, not a payload: past the cap the walk still COUNTS every hole, so the
        # caller learns the true size of what was skipped.
        import mcpServer.tools._data_read as data_read
        cap = data_read._MAX_UNREAD_NAMED
        dead = [self._dead_files_folder("Dead%02d" % i) for i in range(cap + 1)]
        cloud(FakeDataFolder("Root", folders=dead, is_root=True), {})
        got, _meta, err = dm.resolve_file_reference(
            "ghost.txt", project="Sample Project")
        assert got is None
        assert f"{cap + 1} folder(s) could not be read" in err        # the COUNT is complete
        assert err.count("Dead") == cap                              # the NAMES are capped
        assert "Dead%02d" % cap not in err


@pytest.mark.parametrize("module_name", ["data_download_file", "data_move_file"])
def test_file_tool_name_refusal_uses_only_supported_scope_inputs(module_name):
    tool = load_tool(module_name)
    args = ({"destination_folder": "C:/unused"} if module_name == "data_download_file"
            else {"target_folder": "/"})
    result = tool.handler(file="part.f3d", **args)
    assert result["isError"] is True
    assert "'project'" in result["message"] and "lineage URN as 'file'" in result["message"]
    assert "project_id" not in result["message"]


@pytest.mark.parametrize("id_input", [None, "project_id"])
def test_duplicate_project_file_remedy_respects_caller_id_input(monkeypatch, id_input):
    data = FakeData(projects=[FakeDataProject("Twin", project_id="p1"),
                              FakeDataProject("Twin", project_id="p2")])
    monkeypatch.setattr(dm, "app", FakeApplication(data=data))
    got, meta, message = dm.resolve_file_reference("part.f3d", project="Twin", id_input=id_input)
    assert got is None and meta is None
    assert "p1" in message and "p2" in message
    assert ("pass an exact project_id" in message) is (id_input is not None)
    assert "then pass it as 'file'" in message
