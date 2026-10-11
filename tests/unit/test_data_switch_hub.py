"""Check hub targeting, cloud-edit preflight and independently read switch effects."""

import json
from types import SimpleNamespace

import pytest

from conftest import (FakeApplication, FakeData, FakeDataFile, FakeDocuments,
                      FakeFusionDocument, load_tool)

dh = load_tool("data_switch_hub")


def _hub(name, hub_id):
    """One DataHub as the list read walks it: its name and id."""
    return SimpleNamespace(name=name, id=hub_id)


@pytest.fixture
def cloud(monkeypatch):
    """Install the admitted hubs and open-document scene."""
    def _use(hubs=None, active_idx=0, data_cls=FakeData, documents=(), active_document=None):
        hubs = hubs or [_hub("Acme Robotics", "a.acme"), _hub("Personal", "a.personal"),
                        _hub("Contoso Machining", "a.contoso")]
        data = data_cls(hubs=hubs, active_hub=hubs[active_idx])
        docs = documents if isinstance(documents, FakeDocuments) else FakeDocuments(documents)
        app = FakeApplication(data=data, documents=docs, active_document=active_document)
        monkeypatch.setattr(dh, "app", app)
        return data, hubs, docs, app
    return _use


def _payload(res):
    assert res["isError"] is False, res
    return json.loads(res["content"][0]["text"])


def _error_payload(res):
    assert res["isError"] is True, res
    return json.loads(res["content"][0]["text"])


# ── list ──────────────────────────────────────────────────────────────────────

class TestList:
    def test_lists_all_hubs_with_active_flag(self, cloud):
        cloud(active_idx=1)
        out = _payload(dh.handler(action="list"))
        names = [h["name"] for h in out["hubs"]]
        assert names == ["Acme Robotics", "Personal", "Contoso Machining"]
        active = [h for h in out["hubs"] if h["is_active"]]
        assert len(active) == 1 and active[0]["name"] == "Personal"

    def test_default_action_is_list(self, cloud):
        cloud()
        out = _payload(dh.handler())
        assert "hubs" in out and out["active_hub"]["name"] == "Acme Robotics"

    def test_unnamed_hub_gets_placeholder(self, cloud):
        # a hub whose .name is None/empty is reported as "(unnamed)", not null.
        cloud(hubs=[_hub(None, "a.x"), _hub("Named", "a.y")], active_idx=1)
        out = _payload(dh.handler(action="list"))
        names = [h["name"] for h in out["hubs"]]
        assert names == ["(unnamed)", "Named"]
        assert out["hub_count"] == 2

    def test_single_hub_is_active(self, cloud):
        cloud(hubs=[_hub("Solo", "a.solo")], active_idx=0)
        out = _payload(dh.handler(action="list"))
        assert out["hub_count"] == 1
        assert out["hubs"][0]["is_active"] is True


# ── switch ────────────────────────────────────────────────────────────────────

class TestSwitch:
    def test_switch_by_name(self, cloud):
        data, _, _, _ = cloud(active_idx=0)
        out = _payload(dh.handler(action="switch", hub="Contoso Machining"))
        assert out["switched"] is True
        assert data.activeHub.name == "Contoso Machining"
        assert out["active_hub"]["name"] == "Contoso Machining"
        assert out["documents_before_count"] == 0
        assert out["documents_after_count"] == 0
        assert out["closed_document_handles"] == []

    def test_switch_by_id(self, cloud):
        data, _, _, _ = cloud(active_idx=0)
        _payload(dh.handler(action="switch", hub="a.personal"))
        assert data.activeHub.id == "a.personal"

    def test_switch_case_insensitive_name(self, cloud):
        data, _, _, _ = cloud(active_idx=0)
        _payload(dh.handler(action="switch", hub="  contoso MACHINING "))
        assert data.activeHub.name == "Contoso Machining"

    def test_already_active_is_noop(self, cloud):
        data, _, _, _ = cloud(active_idx=0)
        out = _payload(dh.handler(action="switch", hub="Acme Robotics"))
        assert out["switched"] is False and out["already_active"] is True
        assert data._hub_sets == []        # never reassigned

    def test_unknown_hub_errors_and_lists_available(self, cloud):
        cloud()
        res = dh.handler(action="switch", hub="Nope")
        assert res["isError"] is True
        assert "Nope" in res["message"]
        # should help by naming available hubs
        assert "Acme Robotics" in res["message"]

    def test_switch_requires_hub(self, cloud):
        cloud()
        res = dh.handler(action="switch")
        assert res["isError"] is True and "hub" in res["message"]

    @pytest.mark.parametrize("hubs,wanted", [
        ([_hub("Twin", "a.one"), _hub("Twin", "a.two"), _hub("Other", "a.other")],
         ("matches 2 hubs", "'Twin' (a.one)", "'Twin' (a.two)")),
        ([_hub("Twin", "a.one"), _hub(None, "a.blind"), _hub("Other", "a.other")],
         ("hub(s) a.blind did not read", "hub=<id>"))])
    def test_a_name_that_is_not_provably_unique_is_refused_without_assigning(self, cloud, hubs,
                                                                              wanted):
        data, _, _, _ = cloud(hubs=hubs, active_idx=2)
        res = dh.handler(action="switch", hub="twin")
        assert res["isError"] is True and data._hub_sets == []
        assert all(w in res["message"] for w in wanted), res["message"]
        assert "a.other" not in res["message"]

    def test_unknown_action_errors(self, cloud):
        cloud()
        res = dh.handler(action="teleport")
        assert res["isError"] is True and "action" in res["message"]


# ── the re-read decides ──────────────────────────────────────────────────────────────────────────
#
# The assignment LANDS live, so a hub that never becomes active is a DECLARED state - and the one
# the verify-by-re-reading shape exists for: switched:True may only be reported when the re-read
# shows the target, whether the assignment returned quietly or raised.

class _NeverBecomesActive(FakeData):
    """Record a declared nonlanding assignment, optionally raising afterward."""

    def __init__(self, *args, raises=None, **kw):
        super().__init__(*args, **kw)
        self._raises = raises

    @FakeData.activeHub.setter
    def activeHub(self, hub):
        self._hub_sets.append(hub)
        if self._raises:
            raise RuntimeError(self._raises)


class TestTheReReadDecides:
    @pytest.mark.parametrize("unread", ["both", "active", "target"])
    def test_unread_hub_identity_cannot_compare_as_already_active(self, cloud, unread):
        class _UnreadId:
            def __init__(self, name):
                self.name = name

            @property
            def id(self):
                raise RuntimeError("hub id unavailable")

        home = _UnreadId("Home") if unread in ("both", "active") else _hub("Home", "a.home")
        other = _UnreadId("Other") if unread in ("both", "target") else _hub("Other", "a.other")
        data, _, _, _ = cloud(hubs=[home, other])

        res = dh.handler(action="switch", hub="Other")

        assert res["isError"] is True
        assert data._hub_sets == []
        assert "identity could not be read" in res["message"]
        assert "data_get(include=['hubs'])" in res["message"]
        assert ("hub 'Other'" if unread != "active" else "active hub") in res["message"]

    def test_unread_post_switch_identity_is_not_success(self, cloud):
        class _UnreadAfterAssignment(FakeData):
            @property
            def activeHub(self):
                if self._hub_sets:
                    raise RuntimeError("active hub unreadable")
                return self._active_hub

            @activeHub.setter
            def activeHub(self, hub):
                self._hub_sets.append(hub)

        data, _, _, _ = cloud(data_cls=_UnreadAfterAssignment)
        res = dh.handler(action="switch", hub="Contoso Machining")

        assert res["isError"] is True
        assert len(data._hub_sets) == 1
        assert "re-read after the assignment" in res["message"]
        assert _error_payload(res)["switched"] is None

    def test_silent_noop_setter_reports_honest_error_not_false_success(self, cloud):
        cloud(active_idx=0, data_cls=_NeverBecomesActive)
        res = dh.handler(action="switch", hub="Contoso Machining")
        assert res["isError"] is True, "must NOT claim switched:True when the hub never changed"
        # both hubs named: the target asked for, and what the re-read actually showed
        assert "'Contoso Machining'" in res["message"] and "'Acme Robotics'" in res["message"]
        assert "data panel" in res["message"]
        # and no CAUSE for the miss - the tool read no such thing
        assert "read-only" not in res["message"]

    def test_a_raising_assignment_reports_the_raise_beside_the_re_read(self, cloud):
        cloud(active_idx=0,
              data_cls=lambda **kw: _NeverBecomesActive(raises="hub is offline", **kw))
        res = dh.handler(action="switch", hub="Contoso Machining")
        assert res["isError"] is True
        assert "the assignment raised: hub is offline" in res["message"]
        assert "'Acme Robotics'" in res["message"]

    def test_a_throw_after_landing_reports_verified_switch_and_assignment_warning(self, cloud):
        class _LandsThenRaises(FakeData):
            @FakeData.activeHub.setter
            def activeHub(self, hub):
                self._hub_sets.append(hub)
                self._active_hub = hub
                raise RuntimeError("setter raised after landing")

        cloud(active_idx=0, data_cls=_LandsThenRaises)
        res = dh.handler(action="switch", hub="Contoso Machining")
        payload = _payload(res)
        assert payload["switched"] is True
        assert payload["active_hub_before"]["id"] == "a.acme"
        assert payload["active_hub_after"]["id"] == "a.contoso"
        assert payload["assignment_error"] == "setter raised after landing"
        assert payload["closed_document_handles"] == []
        assert "assignment raised after the target became active" in payload["note"]


def _cloud_document(name, file_id, is_modified):
    return FakeFusionDocument(name=name, data_file=FakeDataFile(name=name, file_id=file_id),
                              is_saved=True, is_modified=is_modified)


class TestDocumentPreflight:
    def test_nonactive_modified_cloud_document_blocks_before_setter_with_exact_remedies(self, cloud):
        active = FakeFusionDocument(name="Unsaved active", is_modified=False)
        modified = _cloud_document("Saved edited part", "urn:part", True)
        data, _, _, _ = cloud(active_idx=0, documents=[active, modified],
                              active_document=active)

        res = dh.handler(action="switch", hub="Contoso Machining")

        payload = _error_payload(res)
        assert "Refusing hub switch: 1 cloud-backed document(s) have unsaved edits" in payload["error"]
        assert data._hub_sets == []
        blocked = payload["modified_cloud_documents"]
        assert len(blocked) == 1
        assert payload["modified_cloud_document_count"] == 1
        assert payload["modified_cloud_documents_truncated"] is False
        assert blocked[0]["name"] == "Saved edited part"
        assert blocked[0]["document_id"] == "urn:part"
        assert blocked[0]["document_handle"].startswith("session:")
        handle = blocked[0]["document_handle"]
        assert f"doc_activate(name='{handle}')" in blocked[0]["remedy"]
        assert f"doc_save(expect_document='{handle}')" in blocked[0]["remedy"]
        assert f"doc_close(name='{handle}', save_changes=false)" in blocked[0]["remedy"]

    def test_modified_never_saved_document_is_allowed_and_reported_retained(self, cloud):
        modified = FakeFusionDocument(name="Unsaved scratch", is_modified=True)
        data, _, _, _ = cloud(active_idx=0, documents=[modified], active_document=modified)

        out = _payload(dh.handler(action="switch", hub="Contoso Machining"))

        assert data.activeHub.id == "a.contoso"
        assert out["documents_before_count"] == 1
        assert out["documents_after_count"] == 1
        assert out["closed_document_handles"] == []
        handle = out["documents_before"][0]["document_handle"]
        assert out["retained_document_handles"] == [handle]
        assert out["documents_after"][0]["document_handle"] == handle

    def test_closed_and_retained_handles_come_from_the_complete_post_census(self, cloud):
        class _ClosesCleanCloudDocument(FakeData):
            def __init__(self, *args, docs, close_doc, **kwargs):
                super().__init__(*args, **kwargs)
                self._docs = docs
                self._close_doc = close_doc

            @FakeData.activeHub.setter
            def activeHub(self, hub):
                self._hub_sets.append(hub)
                self._active_hub = hub
                self._docs._items.remove(self._close_doc)
                self._close_doc._closed = True

        scratch = FakeFusionDocument(name="Never-saved", is_modified=True)
        saved = _cloud_document("Saved clean", "urn:clean", False)
        docs = FakeDocuments([scratch, saved])
        data_cls = lambda **kw: _ClosesCleanCloudDocument(docs=docs, close_doc=saved, **kw)
        data, _, _, _ = cloud(active_idx=0, data_cls=data_cls, documents=docs,
                              active_document=scratch)

        out = _payload(dh.handler(action="switch", hub="Contoso Machining"))

        handles = {row["name"]: row["document_handle"] for row in out["documents_before"]}
        assert out["documents_after_complete"] is True
        assert out["closed_document_handles"] == [handles["Saved clean"]]
        assert out["retained_document_handles"] == [handles["Never-saved"]]
        assert data.activeHub.id == "a.contoso"

    @pytest.mark.parametrize("state", ["count", "modified"])
    def test_unknown_preflight_state_refuses_without_setter(self, cloud, state):
        if state == "count":
            class _UnreadableCount(FakeDocuments):
                @property
                def count(self):
                    raise RuntimeError("count unavailable")
            doc = FakeFusionDocument(name="Saved clean", data_file=FakeDataFile(file_id="urn:clean"),
                                     is_saved=True, is_modified=False)
            docs = _UnreadableCount([doc])
            data, _, _, app = cloud(active_idx=0, documents=[doc], active_document=doc)
            app.documents = docs
        else:
            doc = _cloud_document("State unreadable", "urn:part", True)
            doc.isModified = None
            data, _, _, _ = cloud(active_idx=0, documents=[doc], active_document=doc)

        res = dh.handler(action="switch", hub="Contoso Machining")

        assert res["isError"] is True
        assert data._hub_sets == []

        expected = ("the open-document count could not be read" if state == "count"
                    else "modified state unreadable")
        assert expected in res["message"]

    @pytest.mark.parametrize("unread", ["cloud", "handle"])
    def test_unknown_document_identity_blocks_the_assignment(self, cloud, monkeypatch, unread):
        class _UnreadBacking(FakeFusionDocument):
            @property
            def dataFile(self):
                raise RuntimeError("cloud backing unreadable")

            @dataFile.setter
            def dataFile(self, value):
                pass

        doc = (_UnreadBacking(name="Unread cloud", is_modified=False) if unread == "cloud"
               else _cloud_document("Unread handle", "urn:part", False))
        if unread == "handle":
            monkeypatch.setattr(dh._write_guard, "document_handle", lambda value: None)
        data, _, _, _ = cloud(documents=[doc], active_document=doc)

        res = dh.handler(action="switch", hub="Contoso Machining")

        assert res["isError"] is True
        assert data._hub_sets == []
        expected = ("cloud backing or file identity unreadable" if unread == "cloud"
                    else "session identity unreadable")
        assert expected in res["message"]

    def test_incomplete_post_census_does_not_infer_closed_documents(self, cloud):
        class _UnreadAfterSwitch(FakeDocuments):
            def __init__(self, documents):
                super().__init__(documents)
                self.unread = False

            @property
            def count(self):
                if self.unread:
                    raise RuntimeError("post count unavailable")
                return len(self._items)

        clean = _cloud_document("Saved clean", "urn:clean", False)
        docs = _UnreadAfterSwitch([clean])

        class _SwitchThenUnread(FakeData):
            def __init__(self, *args, docs, **kwargs):
                super().__init__(*args, **kwargs)
                self._docs = docs

            @FakeData.activeHub.setter
            def activeHub(self, hub):
                self._hub_sets.append(hub)
                self._active_hub = hub
                docs.unread = True

        data_cls = lambda **kw: _SwitchThenUnread(docs=docs, **kw)
        cloud(active_idx=0, data_cls=data_cls, documents=docs, active_document=clean)

        res = dh.handler(action="switch", hub="Contoso Machining")
        payload = _error_payload(res)

        assert payload["switched"] is True
        assert payload["documents_after_complete"] is False
        assert payload["closed_document_handles"] is None
        assert payload["retained_document_handles"] is None

    def test_hub_list_and_exact_id_resolution_keep_the_unbounded_baseline_shape(self, cloud):
        hubs = [_hub(f"Hub {i}", f"a.{i}") for i in range(51)]
        data, _, _, _ = cloud(hubs=hubs, active_idx=0)

        listed = _payload(dh.handler(action="list"))
        switched = _payload(dh.handler(action="switch", hub="a.50"))

        assert set(listed) == {"active_hub", "hub_count", "hubs"}
        assert listed["hub_count"] == 51
        assert len(listed["hubs"]) == 51
        assert switched["switched"] is True
        assert data.activeHub.id == "a.50"

    def test_exact_id_still_resolves_when_an_unrelated_hub_read_fails(self, cloud):
        data, hubs, _, _ = cloud(active_idx=0)

        class _PartialHubCollection:
            count = 3

            def item(self, index):
                if index == 1:
                    return None
                return hubs[index]

        data.dataHubs = _PartialHubCollection()
        out = _payload(dh.handler(action="switch", hub="a.contoso"))

        assert out["switched"] is True
        assert data.activeHub.id == "a.contoso"

    def test_open_document_census_over_safety_limit_refuses_before_setter(self, cloud):
        documents = [FakeFusionDocument(name=f"Doc {i}", is_modified=False) for i in range(51)]
        data, _, _, _ = cloud(active_idx=0, documents=documents)

        res = dh.handler(action="switch", hub="Contoso Machining")

        assert res["isError"] is True
        assert "51 documents exceed the 50-document safety limit" in res["message"]
        assert "close or reduce the open documents you own" in res["message"]
        assert "ask the user to do so" in res["message"]
        assert data._hub_sets == []
