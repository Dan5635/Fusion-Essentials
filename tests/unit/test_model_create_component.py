"""Unit tests for ``model_create_component.py`` — make a new empty component occurrence.

The logic pinned, no live
Fusion: an empty component+occurrence is created (Occurrences.addNewComponent),
optionally named and/or placed at x/y/z (a translation transform, scaled to cm),
and optionally activated as the edit target. This is the prerequisite for
modelling separate, jointable parts in an assembly.
"""
from conftest import install as _install_design

from types import SimpleNamespace

import pytest

from conftest import (FakeMatrix3D, FakeOccurrence, MakeComp, MakeDesign, _NamedCollection,
                      install, load_tool, make_occurrence)

cc = load_tool("model_create_component")


# ── fakes ───────────────────────────────────────────────────────────────────

class _NewOccurrence(FakeOccurrence):
    """The occurrence addNewComponent hands back: it activates as the edit target, and answers the
    parent lock it was created with. ground=None makes that read RAISE - an occurrence whose lock
    cannot be read, which must publish null rather than a coerced false."""

    def __init__(self, path="Component1:1", component=None, ground=None):
        super().__init__(path, component if component is not None else MakeComp(name="Component1"),
                         ground_to_parent=ground,
                         raises_on=(None if ground is not None
                                    else {"isGroundToParent": "3 : the lock does not read"}))
        self.activated = False

    def activate(self):
        self.activated = True
        return True


class _ContextProxy(_NewOccurrence):
    """The assembly-context proxy createForAssemblyContext returns - its fullPathName shows nesting."""
    def __init__(self, native, parent):
        super().__init__(path=f"{parent.fullPathName}+{native.name}", component=native.component)


class _ChildOccurrence(_NewOccurrence):
    """The NATIVE child occurrence addNewComponent returns on the parent's component - its own
    fullPathName shows only the child; createForAssemblyContext proxies it into the parent's context."""
    def __init__(self, proxy=True):
        super().__init__(path="Child:1")
        self._proxy = proxy
        self.last_proxy = None        # the proxy handed out, so tests can assert on ITS state

    def createForAssemblyContext(self, parent):
        if not self._proxy:
            return None
        self.last_proxy = _ContextProxy(self, parent)
        return self.last_proxy


class _LockedComponent(MakeComp):
    """A component whose rename lands nowhere: the assignment raises nothing and the component keeps
    the name it has, which is how Fusion no-ops a duplicate or invalid one."""
    def __setattr__(self, key, value):
        if key == "name" and hasattr(self, "name"):
            return
        object.__setattr__(self, key, value)


class _PartNumberRaises(MakeComp):
    """A component whose partNumber reads Fusion's creation-timestamp default and whose setter
    refuses every write - the create must still land."""
    def __init__(self, name="Component1", stamp="20260922204259123", **kw):
        super().__init__(name=name, **kw)
        self._stamp = stamp

    @property
    def partNumber(self):
        return self._stamp

    @partNumber.setter
    def partNumber(self, value):
        raise RuntimeError("no permission")


class _TimestampComponent(MakeComp):
    """A freshly-created component carrying Fusion's own creation-timestamp partNumber default."""
    def __init__(self, name="Component1", stamp="20260922204259123", **kw):
        super().__init__(name=name, part_number=stamp, **kw)


class FakeMatrix(FakeMatrix3D):
    """Matrix3D.create()'s product, recording what the handler wrote in this file's own `_assigned`
    and `rotation` rather than through the shared translation column."""
    # The recorder is private plumbing because the shared property answers a FRESH Vector3D each
    # read (measured), so it can never hand back this file's ('vec', x, y, z) stand-in.
    def __init__(self):
        super().__init__()
        self._assigned = None
        self.rotation = None

    @property
    def translation(self):
        return self._assigned

    @translation.setter
    def translation(self, vec):
        self._assigned = vec

    def setToRotation(self, angle, axis, origin):
        self.rotation = (angle, axis, origin)
        return True


class FakeOccurrences(_NamedCollection):
    """component.occurrences: the shared walk plus addNewComponent, which lands the new occurrence
    IN the walk - so the count is read back off the collection, never kept beside it."""
    def __init__(self):
        super().__init__()
        self.last_transform = None
        self.ground = None          # what isGroundToParent reads on the occurrence this creates

    def addNewComponent(self, transform):
        self.last_transform = transform
        occ = _NewOccurrence(ground=self.ground)
        self._items.append(occ)
        return occ


class FakeParentOccurrences:
    def __init__(self):
        self.last_transform = None
        self._child = _ChildOccurrence()
    def addNewComponent(self, transform):
        self.last_transform = transform
        return self._child


class FakeDesign(MakeDesign):
    """A design whose designIntent reads and writes, recording every assignment. intent=None is a
    design that answers no intent at all, where the promotion is skipped."""

    def __init__(self, intent=None):
        root = MakeComp(name="Root")
        root.occurrences = FakeOccurrences()
        super().__init__(comp=root)
        self._intent = intent
        self.intent_sets = []                 # records every assignment, to prove the promote fired

    @property
    def designIntent(self):
        if self._intent is None:
            return None
        import adsk.fusion
        T = adsk.fusion.DesignIntentTypes
        return {"part": T.PartDesignIntentType, "hybrid": T.HybridDesignIntentType,
                "assembly": T.AssemblyDesignIntentType}[self._intent]

    @designIntent.setter
    def designIntent(self, v):
        import adsk.fusion
        T = adsk.fusion.DesignIntentTypes
        self._intent = {T.PartDesignIntentType: "part", T.HybridDesignIntentType: "hybrid",
                        T.AssemblyDesignIntentType: "assembly"}[v]
        self.intent_sets.append(self._intent)


def _parent_occurrence(path="Frame:1"):
    """The occurrence 'parent' resolves to, whose component receives the new child."""
    comp = MakeComp(name=path.split(":")[0])
    comp.occurrences = FakeParentOccurrences()
    return make_occurrence(path=path, component=comp)


def _install(intent=None):
    # DesignIntentTypes is a MEASURED family: conftest seeds it from live_api_facts, and the fake
    # maps through whatever the family holds - no hand-seeded values.
    import adsk.core
    design = install(cc, FakeDesign(intent=intent))
    adsk.core.Matrix3D.create = staticmethod(FakeMatrix)
    adsk.core.Vector3D.create = staticmethod(lambda x, y, z: ("vec", x, y, z))
    adsk.core.Point3D.create = staticmethod(lambda x, y, z: ("pt", x, y, z))
    return design


from conftest import payload as _payload


# ── behaviour ────────────────────────────────────────────────────────────────

class TestCreateComponent:
    def test_creates_component(self):
        design = _install()
        out = _payload(cc.handler())
        assert out["created"] is True
        assert design.rootComponent.occurrences.count == 1

    def test_names_the_component(self):
        _install()
        out = _payload(cc.handler(name="Mast"))
        # the handler renames component to 'Mast'; reports it
        assert out["component"] == "Mast"
        assert "name_warning" not in out          # a successful rename has no warning

    def test_rejected_rename_surfaces_warning_not_false_success(self):
        # Fusion silently no-ops a duplicate/invalid component rename. The handler must read the name
        # back and WARN, not report the requested name as if it took.
        design = _install()
        locked = _LockedComponent(name="Component1")
        design.rootComponent.occurrences.addNewComponent = (
            lambda t: _NewOccurrence(component=locked))
        out = _payload(cc.handler(name="Mast"))
        assert out["component"] == "Component1"    # the ACTUAL (unchanged) name, honestly
        assert "name_warning" in out and "Mast" in out["name_warning"]

    def test_placed_at_position_scales_to_cm(self):
        design = _install()
        _payload(cc.handler(x=10, y=0, z=5, units="mm"))
        # translation handed to the matrix is in cm (10mm -> 1cm)
        t = design.rootComponent.occurrences.last_transform.translation
        assert t is not None and abs(t[1] - 1.0) < 1e-9 and abs(t[3] - 0.5) < 1e-9

    def test_no_position_uses_identity(self):
        design = _install()
        _payload(cc.handler())
        # no x/y/z -> no translation set on the matrix
        assert design.rootComponent.occurrences.last_transform.translation is None

    def test_activate_makes_it_edit_target(self):
        _install()
        out = _payload(cc.handler(name="Boom", activate=True))
        assert out["activated"] is True

    def test_no_activate_by_default(self):
        _install()
        out = _payload(cc.handler(name="Boom"))
        assert out["activated"] is False

    def test_unknown_units_errors(self):
        _install()
        res = cc.handler(x=5, units="furlongs")
        assert res["isError"] is True and "Unknown units" in res["message"]

    def test_orientation_rotation(self):
        design = _install()
        out = _payload(cc.handler(rotate_deg=90, rotate_axis="x"))
        assert design.rootComponent.occurrences.last_transform.rotation is not None
        assert out["rotate_axis"] == "x" and out["rotate_deg"] == 90

    def test_rotation_angle_converted_to_radians(self):
        import math
        design = _install()
        _payload(cc.handler(rotate_deg=90, rotate_axis="z"))
        angle, axis, origin = design.rootComponent.occurrences.last_transform.rotation
        assert abs(angle - math.pi / 2) < 1e-9        # 90deg -> pi/2 rad
        assert axis == ("vec", 0, 0, 1)               # z axis

    def test_rotation_pivot_is_world_origin_not_the_placement(self):
        # The rotation pivots about the WORLD origin; placement is applied by the separate translation
        # (verified live: occurrence lands at the placement with a correct basis). A pivot at the
        # placement point would only bake a correction into the translation column that the next line
        # overwrites - so the pivot must be world origin, not the scaled placement.
        design = _install()
        _payload(cc.handler(rotate_deg=45, rotate_axis="y", x=10, y=0, z=20, units="mm"))
        angle, axis, origin = design.rootComponent.occurrences.last_transform.rotation
        assert origin == ("pt", 0.0, 0.0, 0.0)

    def test_rotate_axis_none_when_no_rotation(self):
        _install()
        out = _payload(cc.handler(name="A"))
        assert out["rotate_axis"] is None
        assert out["rotate_deg"] == 0.0

    def test_position_scaled_inches(self):
        design = _install()
        _payload(cc.handler(x=1, y=2, z=0, units="in"))
        t = design.rootComponent.occurrences.last_transform.translation
        # 1in -> 2.54cm, 2in -> 5.08cm
        assert abs(t[1] - 2.54) < 1e-9 and abs(t[2] - 5.08) < 1e-9

    def test_unknown_rotate_axis_errors(self):
        _install()
        res = cc.handler(rotate_deg=45, rotate_axis="w")
        assert res["isError"] is True and "rotate_axis" in res["message"]

    def test_no_active_design_errors(self, monkeypatch):
        _install()
        _install_design(cc, None)
        res = cc.handler()
        assert res["isError"] is True and "No active design" in res["message"]


# ── F-intent: a PART design is auto-promoted to HYBRID so a multi-component build works ──────────
# A fresh doc (current Fusion) is PART intent, which REFUSES addNewComponent ('Part Design documents can
# only contain one component'). model_create_component detects that and promotes PART -> HYBRID
# (keeps modeling enabled, unlike Assembly) before creating, reporting it as design_intent_promoted.

class TestDesignIntentPromotion:
    def test_part_intent_is_promoted_to_hybrid(self):
        design = _install(intent="part")
        out = _payload(cc.handler(name="Model"))
        assert out["created"] is True
        assert design._intent == "hybrid"                       # promoted, not left at part
        assert design.intent_sets == ["hybrid"]                 # set exactly once, to hybrid (NOT assembly)
        assert "design_intent_promoted" in out and "HYBRID" in out["design_intent_promoted"]

    def test_hybrid_intent_is_left_alone(self):
        design = _install(intent="hybrid")
        out = _payload(cc.handler(name="Model"))
        assert design.intent_sets == []                         # already hybrid - no promote, no churn
        assert "design_intent_promoted" not in out

    def test_assembly_intent_is_left_alone(self):
        design = _install(intent="assembly")
        out = _payload(cc.handler(name="Model"))
        assert design.intent_sets == []                         # assembly accepts components - untouched
        assert "design_intent_promoted" not in out

    def test_intent_absent_is_untouched(self):
        # a design with no designIntent (older Fusion / a mock) must not crash and must not claim a promote
        design = _install(intent=None)
        out = _payload(cc.handler(name="Model"))
        assert out["created"] is True
        assert "design_intent_promoted" not in out


# ── parent= : nest the new component INSIDE an existing occurrence (occurrences.addNewComponent on the
# PARENT component). Omitted = root (back-compat). The read-back's full_path shows the nesting.

def _install_with_parent(intent=None):
    design = _install(intent=intent)
    parent = _parent_occurrence()
    design.rootComponent.allOccurrences = [parent]     # what OccurrenceRef resolves 'parent' against
    return design, parent


class TestNestedParent:
    def test_nests_inside_the_parent_not_root(self):
        design, parent = _install_with_parent()
        out = _payload(cc.handler(name="Child", parent="Frame:1"))
        assert out["created"] is True
        # created via the PARENT component's occurrences, and root was NOT touched
        assert parent.component.occurrences.last_transform is not None
        assert design.rootComponent.occurrences.count == 0
        assert out["nested_in"] == "Frame:1"
        assert out["full_path"] == "Frame:1+Child:1"    # the proxy's nested fullPathName
        assert out["component"] == "Child"

    def test_root_when_parent_omitted_is_back_compat(self):
        design = _install()
        out = _payload(cc.handler(name="Top"))
        assert design.rootComponent.occurrences.count == 1   # the original root path
        assert out["nested_in"] is None

    def test_missing_parent_is_refused_with_its_value(self):
        _install_with_parent()          # only 'Frame:1' exists
        res = cc.handler(name="Child", parent="Nonexistent")
        assert res["isError"] is True
        assert "Nonexistent" in res["message"]
        # nothing was created on root as a fallback
        assert cc.app.activeProduct.rootComponent.occurrences.count == 0

    def test_a_missed_parent_in_an_empty_design_says_to_omit_it_for_the_root(self):
        design = _install()
        res = cc.handler(name="Host", parent="root")
        assert res["isError"] is True
        assert "matching 'root'" in res["message"]
        assert res["message"].endswith("To create at the root, omit 'parent'.")
        assert design.rootComponent.occurrences.count == 0

    def test_an_occurrence_named_root_is_still_the_parent(self):
        design = _install()
        named_root = _parent_occurrence(path="root:1")
        design.rootComponent.allOccurrences = [named_root]
        out = _payload(cc.handler(name="Child", parent="root"))
        assert out["nested_in"] == "root:1"
        assert design.rootComponent.occurrences.count == 0

    def test_an_ambiguous_parent_is_not_told_to_omit_it(self):
        design = _install()
        design.rootComponent.allOccurrences = [_parent_occurrence(), _parent_occurrence()]
        res = cc.handler(name="Child", parent="Frame:1")
        assert res["isError"] is True
        assert "2 occurrences" in res["message"] and "omit 'parent'" not in res["message"]

    def test_nested_path_constructed_when_proxy_unavailable(self):
        # If createForAssemblyContext yields no proxy, the handler still reports the nested path by
        # constructing 'Parent:1+Child:1' (Fusion joins fullPathName segments with '+').
        design, parent = _install_with_parent()
        parent.component.occurrences._child = _ChildOccurrence(proxy=False)
        out = _payload(cc.handler(name="Child", parent="Frame:1"))
        assert out["full_path"] == "Frame:1+Child:1"

    def test_activate_targets_the_nested_proxy(self):
        design, parent = _install_with_parent()
        out = _payload(cc.handler(name="Child", parent="Frame:1", activate=True))
        # the proxy (assembly-context), not the native child, is what gets activated as the edit
        # target - assert the proxy WAS activated, not merely that the native child wasn't.
        child = parent.component.occurrences._child
        assert child.last_proxy is not None and child.last_proxy.activated is True
        assert child.activated is False
        assert out["activated"] is True


class TestGroundToParentDisclosure:
    """The parent lock the caller never asked for: a new occurrence can come back locked, and that
    decides which member a later joint drive displaces - so the create reports it."""

    def test_a_locked_new_occurrence_is_disclosed(self):
        design = _install()
        design.rootComponent.occurrences.ground = True
        out = _payload(cc.handler(name="Base"))
        assert out["ground_to_parent"] is True
        assert "ground_to_parent reads TRUE" in out["note"]
        assert "assembly_ground(ground_to_parent=false)" in out["note"]

    def test_a_free_new_occurrence_carries_no_lock_clause(self):
        design = _install()
        design.rootComponent.occurrences.ground = False
        out = _payload(cc.handler(name="Arm"))
        assert out["ground_to_parent"] is False
        assert "ground_to_parent reads TRUE" not in out["note"]

    def test_an_unreadable_lock_publishes_null_not_false(self):
        # false would claim the part is free to move; the read simply did not answer.
        _install()
        out = _payload(cc.handler(name="Arm"))
        assert out["ground_to_parent"] is None
        assert "ground_to_parent reads TRUE" not in out["note"]


# ── part_number : a component's timestamp default is replaced by its name unless an explicit value
# was given (MEASURED: a created component's partNumber reads as a creation timestamp, not its name).

class TestPartNumber:
    def test_default_replaces_the_timestamp_with_the_name(self):
        design = _install()
        comp = _TimestampComponent()
        design.rootComponent.occurrences.addNewComponent = lambda t: _NewOccurrence(component=comp)
        out = _payload(cc.handler(name="Mast"))
        assert out["part_number"] == "Mast"
        assert comp.partNumber == "Mast"
        assert "part_number_warning" not in out

    def test_explicit_part_number_input_is_honoured(self):
        design = _install()
        comp = _TimestampComponent()
        design.rootComponent.occurrences.addNewComponent = lambda t: _NewOccurrence(component=comp)
        out = _payload(cc.handler(name="Mast", part_number="FE-100"))
        assert out["part_number"] == "FE-100"
        assert comp.partNumber == "FE-100"

    def test_a_raising_write_is_disclosed_not_a_failed_create(self):
        design = _install()
        comp = _PartNumberRaises()
        design.rootComponent.occurrences.addNewComponent = lambda t: _NewOccurrence(component=comp)
        out = _payload(cc.handler(name="Mast"))
        assert out["created"] is True
        assert out["part_number"] == "20260922204259123"     # the write failed, so unchanged
        assert "part_number_warning" in out
        assert "no permission" in out["part_number_warning"]


@pytest.fixture
def sheet_component_setup(monkeypatch):
    design = _install()
    occurrences = design.rootComponent.occurrences
    def add_sheet(transform):
        component = MakeComp(name="SheetPart")
        component.activeSheetMetalRule = SimpleNamespace(name="Steel (mm)")
        occ = _NewOccurrence(component=component)
        occurrences._items.append(occ)
        return occ
    monkeypatch.setattr(occurrences, "addNewSheetMetalComponent", add_sheet, raising=False)
    return design, occurrences


def test_sheet_metal_mode_creates_native_ruled_component(sheet_component_setup):
    design, occurrences = sheet_component_setup
    out = _payload(cc.handler(name="Bracket", sheet_metal=True))
    assert occurrences.count == 1
    assert out["sheet_metal"] is True
    assert out["active_sheet_metal_rule"] == "Steel (mm)"
    assert "sheet_convert" in out["note"]


def test_sheet_metal_create_reports_persisted_occurrence_if_rule_unreadable(sheet_component_setup,
                                                                              monkeypatch):
    design, occurrences = sheet_component_setup
    def add_without_rule(transform):
        occ = _NewOccurrence(component=MakeComp(name="Unruled"))
        occurrences._items.append(occ)
        return occ
    monkeypatch.setattr(occurrences, "addNewSheetMetalComponent", add_without_rule)
    result = cc.handler(sheet_metal=True)
    assert result["isError"] is True
    assert "Component1:1" in result["message"]
    assert occurrences.count == 1


# ── sheet_metal rule adoption: addNewSheetMetalComponent copies a fresh library-default rule only
# when the design's same-named rule no longer matches the library default (measured); otherwise it
# hands the existing rule back. The tool must fold a genuine copy in rather than duplicate the row.

def _rule_fake(name, collection, delete_ok=True, **extra):
    """A design sheet-metal rule: deleteMe() answers delete_ok, counts its own calls, and on True
    removes itself from collection."""
    rule = SimpleNamespace(name=name, delete_calls=0, **extra)
    def _delete():
        rule.delete_calls += 1
        if delete_ok:
            collection._items.remove(rule)
        return delete_ok
    rule.deleteMe = _delete
    return rule


class _RuleLockedComponent(MakeComp):
    """A component whose activeSheetMetalRule assignment is silently ignored after the first set -
    how Fusion no-ops an edit it refuses."""
    def __setattr__(self, key, value):
        if key == "activeSheetMetalRule" and hasattr(self, "activeSheetMetalRule"):
            return
        object.__setattr__(self, key, value)


def _install_sheet_rules(before_rules, new_rule_delete_ok=True, new_rule_kfactor=0.9):
    """A sheet-metal-ready design: before_rules pre-populate designSheetMetalRules; the fake add
    appends a FRESH same-named copy, the measured shape once the design's rule is edited off default."""
    design = _install()
    collection = _NamedCollection(items=list(before_rules))
    design.designSheetMetalRules = collection
    occurrences = design.rootComponent.occurrences
    def add_sheet(transform):
        component = MakeComp(name="SheetPart")
        new_rule = _rule_fake("Steel (mm)", collection, delete_ok=new_rule_delete_ok,
                              kFactor=new_rule_kfactor)
        collection._items.append(new_rule)
        component.activeSheetMetalRule = new_rule
        occ = _NewOccurrence(component=component)
        occurrences._items.append(occ)
        return occ
    occurrences.addNewSheetMetalComponent = add_sheet
    return design, collection


class TestSheetMetalRuleAdoption:
    def test_adopts_the_existing_rule_and_deletes_the_copy(self):
        existing = _rule_fake("Steel (mm)", None, kFactor=0.5)
        design, collection = _install_sheet_rules([existing])
        out = _payload(cc.handler(name="Bracket", sheet_metal=True))
        assert out["rule_adopted_existing"] is True
        assert out["rule_copy_deleted"] is True
        assert out["active_sheet_metal_rule"] == "Steel (mm)"
        assert collection.count == 1
        assert collection._items[0] is existing

    def test_two_prior_same_named_rules_are_reported_ambiguous_not_silently_merged(self):
        existing1 = _rule_fake("Steel (mm)", None, kFactor=0.5)
        existing2 = _rule_fake("Steel (mm)", None, kFactor=0.7)
        design, collection = _install_sheet_rules([existing1, existing2])
        out = _payload(cc.handler(name="Bracket", sheet_metal=True))
        assert out["rule_name_ambiguous"] == "Steel (mm)"
        assert "rule_adopted_existing" not in out
        assert collection.count == 3            # the copy is left in place, nothing merged blind
        assert "sheet_get(include=['rules'])" in out["note"]

    def test_a_copy_that_will_not_delete_is_an_error_not_a_false_ok(self):
        existing = _rule_fake("Steel (mm)", None, kFactor=0.5)
        design, collection = _install_sheet_rules([existing], new_rule_delete_ok=False)
        result = cc.handler(name="Bracket", sheet_metal=True)
        assert result["isError"] is True
        assert "did not delete" in result["message"]
        assert "deleteMe=False" in result["message"]
        assert collection.count == 2             # the undeletable copy still there, not silently lost
        assert design.rootComponent.occurrences.count == 1   # the component itself was still created

    def test_a_delete_that_raises_names_the_exception_not_none(self):
        existing = _rule_fake("Steel (mm)", None, kFactor=0.5)
        design = _install()
        collection = _NamedCollection(items=[existing])
        design.designSheetMetalRules = collection
        occurrences = design.rootComponent.occurrences
        def add_sheet(transform):
            component = MakeComp(name="SheetPart")
            new_rule = SimpleNamespace(name="Steel (mm)", kFactor=0.9)
            def _raise():
                raise RuntimeError("rule is in use")
            new_rule.deleteMe = _raise
            collection._items.append(new_rule)
            component.activeSheetMetalRule = new_rule
            occ = _NewOccurrence(component=component)
            occurrences._items.append(occ)
            return occ
        occurrences.addNewSheetMetalComponent = add_sheet
        result = cc.handler(name="Bracket", sheet_metal=True)
        assert result["isError"] is True
        assert "rule is in use" in result["message"]
        assert "deleteMe=None" not in result["message"]

    def test_a_fresh_add_that_hands_back_an_already_known_rule_is_not_adopted_or_deleted(self):
        # The 'is this rule already in before_rules' guard is what keeps this branch from adopting the
        # rule INTO itself and then deleting the design's one live rule as its own "copy".
        existing = _rule_fake("Steel (mm)", None, kFactor=0.5)
        design = _install()
        collection = _NamedCollection(items=[existing])
        design.designSheetMetalRules = collection
        occurrences = design.rootComponent.occurrences
        def add_sheet(transform):
            component = MakeComp(name="SheetPart")
            component.activeSheetMetalRule = existing      # Fusion handed back the SAME object
            occ = _NewOccurrence(component=component)
            occurrences._items.append(occ)
            return occ
        occurrences.addNewSheetMetalComponent = add_sheet
        out = _payload(cc.handler(name="Bracket", sheet_metal=True))
        assert "rule_adopted_existing" not in out
        assert "rule_added" not in out
        assert "rule_name_ambiguous" not in out
        assert existing.delete_calls == 0
        assert collection.count == 1

    def test_an_assign_that_does_not_take_is_an_error_naming_the_read_back_rule(self):
        # The 'readback != existing' compare is what catches a setter that silently no-ops - without
        # it, a component still carrying the undeleted copy would be reported adopted.
        existing = _rule_fake("Steel (mm)", None, kFactor=0.5)
        design = _install()
        collection = _NamedCollection(items=[existing])
        design.designSheetMetalRules = collection
        occurrences = design.rootComponent.occurrences
        def add_sheet(transform):
            component = _RuleLockedComponent(name="SheetPart")
            new_rule = _rule_fake("Steel (mm)", collection, kFactor=0.9)
            collection._items.append(new_rule)
            component.activeSheetMetalRule = new_rule       # takes - nothing set on it yet
            occ = _NewOccurrence(component=component)
            occurrences._items.append(occ)
            return occ
        occurrences.addNewSheetMetalComponent = add_sheet
        result = cc.handler(name="Bracket", sheet_metal=True)
        assert result["isError"] is True
        assert "did not adopt" in result["message"] and "Steel (mm)" in result["message"]
        assert collection.count == 2              # the copy was never reached for deletion

    def test_an_unread_rule_census_skips_adoption_and_reports_it_not_rule_added(self):
        design = _install()
        occurrences = design.rootComponent.occurrences
        def add_sheet(transform):
            component = MakeComp(name="SheetPart")
            component.activeSheetMetalRule = SimpleNamespace(name="Steel (mm)")
            occ = _NewOccurrence(component=component)
            occurrences._items.append(occ)
            return occ
        occurrences.addNewSheetMetalComponent = add_sheet
        # design.designSheetMetalRules is absent entirely - the census read raises, not "empty".
        out = _payload(cc.handler(name="Bracket", sheet_metal=True))
        assert out["rule_census_unread"] is True
        assert "rule_added" not in out
        assert "rule_adopted_existing" not in out
        assert "sheet_get(include=['rules'])" in out["note"]
