"""Unit tests for ``data_create_project.py`` - the duplicate-name guard and the re-list."""


import pytest

from conftest import FakeApplication, FakeData, FakeDataProject, load_tool, payload as _payload

dm = load_tool("data_create_project")
dc = load_tool("_data_common")


@pytest.fixture
def cloud(monkeypatch):
    """Point the shared cloud seam at a hub holding `projects`, and hand back its app.data."""
    def _use(*projects):
        data = FakeData(projects=list(projects))
        monkeypatch.setattr(dc, "app", FakeApplication(data=data))
        return data
    return _use


class TestCreateProject:
    def test_creates_and_reports_id(self, cloud):
        data = cloud()
        out = _payload(dm.handler(name="Alpha", purpose="testing"))
        assert out["created"] is True
        assert out["name"] == "Alpha"
        assert out["id"] == "newid:Alpha"
        assert data.dataProjects._added == [("Alpha", "testing", "")]

    def test_blank_name_errors(self, cloud):
        cloud()
        res = dm.handler(name="   ")
        assert res["isError"] is True and "name" in res["message"]

    def test_duplicate_name_refused(self, cloud):
        data = cloud(FakeDataProject("Alpha", project_id="p1"))
        res = dm.handler(name="alpha")   # case-insensitive duplicate
        assert res["isError"] is True
        assert "already exists" in res["message"]
        assert data.dataProjects._added == []            # nothing created

    def test_ambiguous_existing_names_refuse_before_creation(self, cloud):
        data = cloud(FakeDataProject("Alpha", project_id="p1"),
                     FakeDataProject("alpha", project_id="p2"))
        res = dm.handler(name="Alpha")
        assert res["isError"] is True and "matches 2 projects" in res["message"]
        assert "'Alpha' (id p1); 'alpha' (id p2)." in res["message"]
        assert "use a different name" in res["message"] and "project_id" not in res["message"]
        assert data.dataProjects._added == []

    def test_an_incomplete_name_census_names_no_input_this_tool_lacks(self, cloud):
        class BlindNameProject:
            id = "p-hidden"

            @property
            def name(self):
                raise RuntimeError("name unreadable")

        data = cloud(FakeDataProject("Alpha", project_id="p1"), BlindNameProject())
        res = dm.handler(name="Beta")
        assert res["isError"] is True and "name listing is incomplete" in res["message"]
        assert "project_id" not in res["message"] and data.dataProjects._added == []

    def test_a_project_that_never_relists_is_an_error(self, cloud, monkeypatch):
        # add() handing back a project object is not the project existing. The re-list is the
        # verification: a hub that does not carry the name afterwards is an error, never created:true.
        data = cloud()

        def ghost(name, purpose="", contributors=""):
            return FakeDataProject(name, project_id="newid:" + name)   # never joins the walk

        monkeypatch.setattr(data.dataProjects, "add", ghost)
        res = dm.handler(name="Alpha")
        assert res["isError"] is True
        assert "re-listed" in res["message"] and "did not land" in res["message"]

    def test_a_failed_post_create_census_discloses_the_created_id(self, cloud, monkeypatch):
        data = cloud()
        listings = 0

        def list_then_fail():
            nonlocal listings
            listings += 1
            if listings == 1:
                return []
            raise RuntimeError("listing unavailable")

        monkeypatch.setattr(data.dataProjects, "asArray", list_then_fail)
        res = dm.handler(name="Alpha")
        assert res["isError"] is True
        assert "Created project 'Alpha' (id newid:Alpha)" in res["message"]
        assert "listing unavailable" in res["message"]
