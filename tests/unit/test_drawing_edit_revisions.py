"""Unit tests for drawing_edit_revisions - add/update/delete/hide/show on a sheet's revision table."""

import types

import pytest

from conftest import (FakeSheet, _RevisionRow, _RevisionTable, error_message, load_tool,
                      make_drawing, make_drawing_session, payload)

dr = load_tool("drawing_edit_revisions")


def _table(rows=None, cls=_RevisionTable, **knobs):
    """A revision table with the measured title+header pair ahead of `rows` (the data rows)."""
    title = _RevisionRow(zone="Revision History")
    header = _RevisionRow(rev="Rev", description="Description", date="Date",
                          approved="Approved", zone="Zone", sht="Sheet Name")
    all_rows = [title, header] + list(rows or [])
    for i, r in enumerate(all_rows):
        r.index = i
    return cls(all_rows, **knobs)


@pytest.fixture
def env(monkeypatch):
    state = types.SimpleNamespace()

    def _install(revision_table=None, **sheet_knobs):
        state.sheet = FakeSheet("Sheet1", revision_table=revision_table, **sheet_knobs)
        make_drawing_session(monkeypatch, make_drawing(sheets=[state.sheet]))
        return state.sheet

    _install()
    state.install = _install
    return state


def _call(action="add", **kwargs):
    return dr.handler(action=action, **{k: v for k, v in kwargs.items() if v is not None})


class _SilentAddTable(_RevisionTable):
    """addRevision that returns true without landing a row - the add census gate must catch it."""

    def addRevision(self, row):
        self.calls.append(("addRevision", row))
        return True


class _DoubleAddTable(_RevisionTable):
    """addRevision that lands the SAME row twice - the exact-growth gate must catch the over-grow."""

    def addRevision(self, row):
        self.calls.append(("addRevision", row))
        row.index = len(self._rows)
        self._rows.append(row)
        dup = _RevisionRow(row.rev, row.description, row.date, row.approved, row.zone, row.sht,
                           len(self._rows))
        self._rows.append(dup)
        return True


class _WrongDeleteTable(_RevisionTable):
    """deleteRow that removes the row BEFORE the one asked - the delete census gate must catch it."""

    def deleteRow(self, index):
        self.calls.append(("deleteRow", index))
        if not 0 <= index < len(self._rows):
            return False
        if index < self._header_rows:
            return True
        del self._rows[index - 1]
        for i, r in enumerate(self._rows):
            r.index = i
        return True


class _DeafVisibilityTable(_RevisionTable):
    """setRevisionVisibility that returns true without flipping isVisible."""

    def setRevisionVisibility(self, index, visible):
        self.calls.append(("setRevisionVisibility", index, visible))
        return True


class TestAdd:
    def test_creates_the_table_when_absent_with_title_header_and_data_rows(self, env):
        out = payload(_call("add", rows=["A|Initial release|D1|PM|B2"]))
        assert out["table_created"] is True
        assert (out["revision_count_before"], out["revision_count_after"]) == (0, 3)
        rows = out["rows"]
        assert rows[0]["zone"] == "Revision History" and rows[0]["rev"] == ""
        assert rows[1]["rev"] == "Rev" and rows[1]["sht"] == "Sheet Name"
        assert rows[2]["rev"] == "A" and rows[2]["description"] == "Initial release"
        assert rows[2]["sht"] == "Sheet1"

    def test_appends_via_addrevision_when_a_table_exists(self, env):
        env.install(revision_table=_table([_RevisionRow(rev="A", description="Initial")]))
        out = payload(_call("add", rows=["B|Slot widened"]))
        assert out["table_created"] is False
        assert (out["revision_count_before"], out["revision_count_after"]) == (3, 4)
        assert out["rows"][3]["rev"] == "B" and out["rows"][3]["description"] == "Slot widened"

    def test_a_three_field_row_lands_with_empty_trailing_texts(self, env):
        out = payload(_call("add", rows=["A|Initial release|D1"]))
        row = out["rows"][2]
        assert (row["rev"], row["description"], row["date"]) == ("A", "Initial release", "D1")
        assert (row["approved"], row["zone"]) == ("", "")

    def test_an_empty_date_reads_what_fusion_filled_not_an_asserted_blank(self, env):
        out = payload(_call("add", rows=["A|Initial release"]))
        assert out["rows"][2]["date"] == "9/27/2026"

    def test_new_table_can_include_inherited_history_before_requested_rows(self, env, monkeypatch):
        original_add = env.sheet.addRevisionTable

        def add_with_inherited_history(table_input):
            table = original_add(table_input)
            inherited = [
                _RevisionRow(rev="P0", description="Existing overview"),
                _RevisionRow(rev="P1", description="Existing review"),
            ]
            table._rows[2:2] = inherited
            for index, row in enumerate(table._rows):
                row.index = index
            return table

        monkeypatch.setattr(env.sheet, "addRevisionTable", add_with_inherited_history)
        out = payload(_call("add", rows=["A|New release|D1|PM|B2"]))
        assert out["table_created"] is True
        assert out["revision_count_before"] == 0
        assert out["revision_count_after"] == 5
        assert [row["rev"] for row in out["rows"]] == ["", "Rev", "P0", "P1", "A"]

    def test_a_six_field_row_is_refused_before_any_create(self, env):
        message = error_message(_call("add", rows=["A|B|C|D|E|F"]))
        assert "has 6 '|'-separated fields" in message
        assert env.sheet.getRevisionTable() is None

    def test_an_empty_rev_is_refused_before_any_create(self, env):
        message = error_message(_call("add", rows=["|Initial release"]))
        assert "needs a non-empty 'rev'" in message
        assert env.sheet.getRevisionTable() is None

    def test_an_addrevision_false_names_the_row_and_what_already_landed(self, env):
        table = _table([_RevisionRow(rev="A", description="Initial")], add_ok=False)
        env.install(revision_table=table)
        message = error_message(_call("add", rows=["B|Slot widened"]))
        assert "addRevision refused rows[0]" in message

    def test_a_second_row_refused_mid_add_reports_the_census_it_left(self, env):
        table = _table([_RevisionRow(rev="A", description="Initial")], add_fails_at=1)
        env.install(revision_table=table)
        message = error_message(_call("add", rows=["B|Slot widened", "C|Third"]))
        assert "addRevision refused rows[1]" in message
        assert "'rev': 'B'" in message
        assert "revision_count_before=3" in message and "revision_count_after=4" in message
        assert "earlier additions may remain" in message and "later additions are unconfirmed" in message
        assert "drawing_get(include=['revisions']) before retrying" in message

    def test_an_addrevision_true_that_lands_nothing_is_an_error(self, env):
        base = _table([_RevisionRow(rev="A", description="Initial")])
        env.install(revision_table=_SilentAddTable(list(base._rows)))
        message = error_message(_call("add", rows=["B|Slot widened"]))
        assert "landed_requested_rows=[]" in message
        assert "unconfirmed_request_indexes=[0]" in message
        assert "drawing_get(include=['revisions']) before retrying" in message

    def test_matching_preexisting_row_is_not_reported_as_a_landed_add(self, env):
        base = _table([_RevisionRow(rev="B", description="Slot widened")])
        env.install(revision_table=_SilentAddTable(list(base._rows)))
        message = error_message(_call("add", rows=["B|Slot widened"]))
        assert "landed_requested_rows=[]" in message
        assert "unconfirmed_request_indexes=[0]" in message
        assert "reads 3 row(s) (3 before)" in message

    def test_an_addrevision_that_lands_twice_is_an_error(self, env):
        table = _table([_RevisionRow(rev="A", description="Initial")], cls=_DoubleAddTable)
        env.install(revision_table=table)
        message = error_message(_call("add", rows=["B|Slot widened"]))
        assert "row_count_mismatch=True" in message
        assert "census=" in message
        assert "drawing_get(include=['revisions']) before retrying" in message

    def test_a_create_that_lands_the_wrong_row_count_is_an_error(self, env):
        env.install(revision_omit_title=True)
        message = error_message(_call("add", rows=["A|Initial release"]))
        assert "table_created=True" in message
        assert "'rev': 'Rev'" in message

    def test_an_unreadable_existing_census_is_refused_before_mutating(self, env, monkeypatch):
        table = _table([_RevisionRow(rev="A", description="Initial")])
        env.install(revision_table=table)
        monkeypatch.setattr(_RevisionTable, "revisionTableRows", property(lambda self: (_ for _ in ()).throw(RuntimeError("stale"))))
        message = error_message(_call("add", rows=["B|Slot widened"]))
        assert "refusing to add" in message
        assert table.calls == []

    def test_declared_returns_are_present(self, env):
        out = payload(_call("add", rows=["A|Initial release"]))
        for spec in dr.RETURNS:
            assert spec.assert_present(out) == "", spec.assert_present(out)


class TestUpdate:
    def test_update_reads_the_change_back(self, env):
        env.install(revision_table=_table([_RevisionRow(rev="A", description="Initial")]))
        out = payload(_call("update", index=2, row="A|Initial release|D2|PM|B2"))
        assert out["rows"][2]["description"] == "Initial release"
        assert out["row"]["date"] == "D2"
        assert out["revision_count_after"] == 3

    def test_a_partial_update_keeps_the_fields_it_did_not_send(self, env):
        env.install(revision_table=_table([_RevisionRow(rev="A", description="Initial", date="D1",
                                                       approved="AA", zone="Z1")]))
        out = payload(_call("update", index=2, row="A|Updated description"))
        assert out["row"]["description"] == "Updated description"
        assert out["row"]["date"] == "D1"
        assert out["row"]["approved"] == "AA" and out["row"]["zone"] == "Z1"

    @pytest.mark.parametrize("row,field", [("A||D1|AA|Z1", "description"),
        ("A|Changed||AA|Z1", "date"), ("A|Changed|D1||Z1", "approved"),
        ("A|Changed|D1|AA|", "zone")])
    def test_explicit_clear_refuses_before_any_other_cell_changes(self, env, row, field):
        table = _table([_RevisionRow(rev="A", description="Initial", date="D1", approved="AA", zone="Z1"),
                        _RevisionRow(rev="B", description="Witness")])
        env.install(revision_table=table)
        before = dr._drawing_common.revision_rows(table)
        message = error_message(_call("update", index=2, row=row))
        assert "Cannot clear row 2" in message and field in message
        assert "Omit trailing fields" in message and "non-empty text" in message
        assert table.calls == []
        assert dr._drawing_common.revision_rows(table) == before

    def test_explicit_empty_cell_already_empty_can_remain_empty(self, env):
        env.install(revision_table=_table([_RevisionRow(rev="A", description="Initial", date="D1")]))
        out = payload(_call("update", index=2, row="A|Changed|D1||"))
        assert out["row"]["description"] == "Changed"
        assert out["row"]["approved"] == out["row"]["zone"] == ""

    def test_update_must_preserve_omitted_cells(self, env, monkeypatch):
        table = _table([_RevisionRow(rev="A", description="Initial", date="D1", approved="AA")])
        env.install(revision_table=table)
        update = table.updateRevisionRow
        def loses_approval(index, row):
            result = update(index, row)
            table._rows[index].approved = ""
            return result
        monkeypatch.setattr(table, "updateRevisionRow", loses_approval)
        message = error_message(_call("update", index=2, row="A|Changed"))
        assert "result is partial" in message
        assert "before=" in message and "requested={'rev': 'A', 'description': 'Changed'}" in message
        assert "actual=" in message and "approved': ''" in message
        assert "landed_fields=['description']" in message
        assert "fields_different_from_expected=['approved']" in message
        assert "unconfirmed_fields=[]" in message
        assert "drawing_get(include=['revisions'])" in message and "before retrying" in message

    def test_updating_the_header_row_is_a_false_success(self, env):
        env.install(revision_table=_table([_RevisionRow(rev="A", description="Initial")]))
        message = error_message(_call("update", index=1, row="X|Changed|D2|PM|B2"))
        assert "row 1 still reads" in message and "title/header" in message

    def test_update_without_a_table_is_refused(self, env):
        message = error_message(_call("update", index=0, row="A|Initial release"))
        assert "holds no revision table yet" in message

    def test_an_out_of_range_index_names_the_range(self, env):
        env.install(revision_table=_table([_RevisionRow(rev="A", description="Initial")]))
        message = error_message(_call("update", index=9, row="A|Initial release"))
        assert "table holds 3 row(s) (0 to 2)" in message

    def test_a_boolean_index_is_refused(self, env):
        env.install(revision_table=_table([_RevisionRow(rev="A", description="Initial")]))
        message = error_message(_call("update", index=True, row="A|Initial release"))
        assert "must be an integer row index" in message


class TestDelete:
    def test_the_census_is_by_content_and_the_payload_shows_reindexed_rows(self, env):
        env.install(revision_table=_table([
            _RevisionRow(rev="A", description="Initial"),
            _RevisionRow(rev="B", description="Slot widened"),
        ]))
        out = payload(_call("delete", index=2))
        assert (out["revision_count_before"], out["revision_count_after"]) == (4, 3)
        assert out["rows"][2]["rev"] == "B" and out["rows"][2]["index"] == 2
        assert out["before_row"]["rev"] == "A"

    def test_deleting_the_header_row_is_a_false_success(self, env):
        env.install(revision_table=_table([_RevisionRow(rev="A", description="Initial")]))
        message = error_message(_call("delete", index=1))
        assert "row 1 still reads" in message and "title/header" in message

    def test_deleting_the_wrong_row_is_an_error(self, env):
        table = _table([_RevisionRow(rev="A", description="Initial"),
                        _RevisionRow(rev="B", description="Slot widened")],
                       cls=_WrongDeleteTable)
        env.install(revision_table=table)
        message = error_message(_call("delete", index=3))
        assert "the table reads" in message and "expected row 3" in message

    def test_a_stray_row_on_delete_is_refused(self, env):
        env.install(revision_table=_table([_RevisionRow(rev="A", description="Initial")]))
        message = error_message(dr.handler(action="delete", index=2, row="A|Initial"))
        assert "does not take row" in message


class TestVisibility:
    def test_hide_reports_visible_count_one_lower_and_the_row_still_listed(self, env):
        env.install(revision_table=_table([_RevisionRow(rev="A", description="Initial")]))
        out = payload(_call("hide", index=2))
        assert out["changed"] is True
        assert out["visible_count"] == 2
        assert out["rows"][2]["visible"] is False
        assert out["row"]["visible"] is False

    def test_show_on_a_visible_row_is_changed_false_without_a_call(self, env):
        table = _table([_RevisionRow(rev="A", description="Initial")])
        env.install(revision_table=table)
        out = payload(_call("show", index=2))
        assert out["changed"] is False
        assert table.calls == []

    def test_a_visibility_flag_that_does_not_move_is_an_error(self, env):
        table = _table([_RevisionRow(rev="A", description="Initial")], cls=_DeafVisibilityTable)
        env.install(revision_table=table)
        message = error_message(_call("hide", index=2))
        assert "still reads visible=True" in message


class TestInputCompatibility:
    def test_a_json_string_rows_and_a_digit_string_index_are_accepted(self, env):
        out = payload(_call("add", rows='["A|Initial release"]'))
        assert out["rows"][2]["rev"] == "A"
        out2 = payload(_call("hide", index="2"))
        assert out2["index"] == 2 and out2["changed"] is True
