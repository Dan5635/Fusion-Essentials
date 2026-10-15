"""Unit tests for ``assembly_rigid_group.py`` - collecting occurrences into RigidGroups.add.

The logic pinned here, no live Fusion: the at-least-two guard, the resolve of every named
occurrence through the shared ambiguity-refusing resolver, and the member-count read-back.
"""

import pytest

from conftest import (FakeOccurrence, FakeRigidGroup, FakeRigidGroups, MakeComp, MakeDesign,
                      _NamedCollection, error_message, go_stale, install, load_tool, payload)


asm = load_tool("assembly_rigid_group")


def _occurrence(path):
    """One occurrence a group can take in, placing a component of its own."""
    return FakeOccurrence(path=path, component=MakeComp(name=path.split("+")[-1].split(":")[0]))


def _mute(path):
    """A group member that answers NEITHER identity read - the unlabelled member a missing-member
    verdict may not be read off."""
    occ = FakeOccurrence(path=path, raises_on={"fullPathName": "declined"})
    go_stale(occ, attrs=("name",))
    return occ


@pytest.fixture
def wire():
    """Build a design placing `paths` under a RigidGroups collection and wire both tool seams."""
    def build(*paths, new_group=None):
        occs = [_occurrence(p) for p in paths]
        root = MakeComp(occurrences=occs)
        root.rigidGroups = FakeRigidGroups(new_group=new_group)
        install(asm, MakeDesign(comp=root))
        return occs, root.rigidGroups
    return build


class TestRigidGroup:
    def test_group_reporting_fewer_members_bites(self, wire):
        # the group was created but reads fewer members than were requested -> error, not ok
        wire("A:1", "B:1", new_group=FakeRigidGroup(occurrences=["A:1"]))
        res = asm.handler(occurrences="A:1, B:1")
        assert res["isError"] is True
        assert "1 member(s)" in res["message"]

    def test_groups_named_occurrences(self, wire):
        _occs, groups = wire("A:1", "B:1", "C:1")
        out = payload(asm.handler(occurrences="A:1, B:1"))
        coll, _include = groups._added[-1]
        assert coll.count == 2
        assert out["grouped"] == ["A:1", "B:1"]

    def test_include_children_flag(self, wire):
        _occs, groups = wire("A:1", "B:1")
        asm.handler(occurrences="A:1, B:1", include_children=True)
        _coll, include = groups._added[-1]
        assert include is True

    def test_needs_at_least_two(self, wire):
        wire("A:1")
        res = asm.handler(occurrences="A:1")
        assert res["isError"] is True and "at least two" in res["message"].lower()

    def test_missing_reported(self, wire):
        wire("A:1")
        res = asm.handler(occurrences="A:1, Ghost")
        assert res["isError"] is True and "Ghost" in res["message"]

    def test_accepts_a_list_not_just_comma_string(self, wire):
        # _resolve_many handles both a comma string and an actual list of names.
        _occs, groups = wire("A:1", "B:1", "C:1")
        out = payload(asm.handler(occurrences=["A:1", "C:1"]))
        coll, _include = groups._added[-1]
        assert coll.count == 2
        assert out["grouped"] == ["A:1", "C:1"]

    def test_list_with_blank_entries_filtered(self, wire):
        # empty/whitespace entries are dropped before resolution.
        wire("A:1", "B:1")
        out = payload(asm.handler(occurrences=["A:1", "  ", "B:1"]))
        assert out["grouped"] == ["A:1", "B:1"]


def _nested(landed="Eye", bezel_locked=False):
    """Root > Eye:1 > (Bezel:1, Cowl:1): the group Fusion hands back over the two children, owned
    by the component named `landed` (None: the group answers no parentComponent)."""
    eye_comp = MakeComp(name="Eye", entity_token="TOKEN:Eye")
    eye = FakeOccurrence(path="Eye:1", component=eye_comp)
    kids = [FakeOccurrence(path=f"Eye:1+{name}:1", component=MakeComp(name=name),
                           assembly_context=eye, ground_to_parent=locked)
            for name, locked in (("Bezel", bezel_locked), ("Cowl", True))]
    eye._children = _NamedCollection(kids)
    group = FakeRigidGroup(name="Rigid Group 1", occurrences=kids)
    root = MakeComp(name="Root", occurrences=[eye], all_occurrences=[eye] + kids,
                    entity_token="TOKEN:Root")
    if landed:
        group.parentComponent = eye_comp if landed == "Eye" else root
    root.rigidGroups = FakeRigidGroups(new_group=group)
    install(asm, MakeDesign(comp=root))
    return payload(asm.handler(occurrences="Eye:1+Bezel:1, Eye:1+Cowl:1"))


class TestOwnerAndGrounding:
    """The reply names the component the created group reads as its owner, and the nested members
    whose parent lock reads off."""

    def test_the_owner_is_the_created_groups_parent_component_not_the_root_it_was_added_through(self):
        out = _nested(landed="Eye")
        assert out["component"] == "Eye"
        assert "The group is owned by component 'Eye'." in out["note"]

    def test_a_root_owned_group_names_root_without_the_clause(self):
        out = _nested(landed="Root")
        assert out["component"] == "Root" and "owned by" not in out["note"]

    def test_an_owner_that_does_not_read_is_null_and_said_unread(self):
        out = _nested(landed=None)
        assert out["component"] is None
        assert "Its owning component did not read" in out["note"]

    def test_only_a_nested_member_reading_unlocked_is_named_with_the_ground_call(self):
        out = _nested(bezel_locked=False)
        assert out["members_not_grounded_to_parent"] == ["Eye:1+Bezel:1"]
        assert ("Nested member(s) reading isGroundToParent false: Eye:1+Bezel:1. "
                "assembly_ground(occurrence='Eye:1+Bezel:1', ground_to_parent=true) locks one to "
                "its parent.") in out["note"]

    @pytest.mark.parametrize("flag", [True, None])
    def test_a_locked_member_or_an_unread_flag_gets_no_grounding_clause(self, flag):
        out = _nested(bezel_locked=flag)
        assert "members_not_grounded_to_parent" not in out and "isGroundToParent" not in out["note"]

    def test_an_unlocked_top_level_member_is_not_named(self, wire):
        # A root-level occurrence has no parent occurrence to lock to.
        occs, _groups = wire("A:1", "B:1")
        for occ in occs:
            occ._ground_to_parent = False
        assert "members_not_grounded_to_parent" not in payload(asm.handler(occurrences="A:1, B:1"))


class TestMembersReadBack:
    """WHICH occurrences landed in the group, not just how many - a count match over a swapped
    member is a group locking parts nobody asked for."""

    def test_a_group_holding_the_right_count_of_the_wrong_parts_bites(self, wire):
        swapped = FakeRigidGroup(occurrences=[_occurrence("A:1"), _occurrence("C:1")])
        wire("A:1", "B:1", "C:1", new_group=swapped)
        msg = error_message(asm.handler(occurrences="A:1, B:1"))
        assert "B:1" in msg and "not asked for" in msg

    def test_the_requested_members_landing_is_a_success(self, wire):
        held = FakeRigidGroup(occurrences=[_occurrence("A:1"), _occurrence("B:1")])
        wire("A:1", "B:1", "C:1", new_group=held)
        assert payload(asm.handler(occurrences="A:1, B:1"))["member_count"] == 2

    def test_extra_members_from_include_children_are_not_a_miss(self, wire):
        wider = FakeRigidGroup(occurrences=[_occurrence("A:1"), _occurrence("B:1"),
                                            _occurrence("A:1+Inner:1")])
        wire("A:1", "B:1", new_group=wider)
        out = payload(asm.handler(occurrences="A:1, B:1", include_children=True))
        assert out["member_count"] == 3

    def test_members_that_will_not_name_themselves_are_not_reported_missing(self, wire):
        # an occurrence whose reads all decline: unlabelled is not absent, so the group passes.
        unreadable = FakeRigidGroup(occurrences=[_mute("A:1"), _mute("B:1")])
        wire("A:1", "B:1", new_group=unreadable)
        assert payload(asm.handler(occurrences="A:1, B:1"))["member_count"] == 2
