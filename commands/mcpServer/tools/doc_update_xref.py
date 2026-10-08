# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: refresh out-of-date external references in the active document - the API
equivalent of "Get Latest", one by name or all that are stale. Covers occurrence xrefs
(Document.documentReferences) and derive links, which are walked off component.features
.deriveFeatures directly: documentReferences can read 0 for a derive whose source is no longer
resolved in-session, while the feature's own documentReference persists."""

import json

import adsk.core
import adsk.fusion

app = adsk.core.Application.get()

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import iter_collection, ok, error, safe, all_components
from . import _common
from . import _data_common
from . import _doc_common
from . import _inputs
from ._doc_common import (component_solids as _solids, occurrence_pose as _pose,
                          path_fault as _path_fault, path_resolves as _resolves,
                          same_pose as _same_pose)

_ACTION = _inputs.Choice("action", ["refresh", "replace", "break_link"], default="refresh")
_OCCURRENCE = _inputs.OccurrenceRef("occurrence")


def _ref_name(ref):
    return safe(lambda: ref.dataFile.name) or "(unknown)"


def _source_groups(rows):
    """Group matched reference rows by the SOURCE FILE they point at: {key: [(kind, label)]}, keyed on
    the source DataFile's lineage id - one document can be referenced by several rows while two
    DIFFERENT files may share a NAME. A row whose id does not read gets a key of its own, since two
    unreadable ids cannot be shown to be one file."""
    groups = {}
    for kind, label, ref in rows:
        fid = safe(lambda r=ref: r.dataFile.id)
        groups.setdefault(fid if fid else ("unreadable", id(ref)), []).append((kind, label))
    return groups


def _group_label(key, members):
    """One line of the ambiguity refusal: the source file's URN (or that it would not read) and the
    kinds of reference row pointing at it."""
    who = key if isinstance(key, str) else "(source file id unreadable)"
    return f"{who} [{', '.join(kind for kind, _ in members)}]"


def _derive_refs(doc):
    """Every (label, DocumentReference) pair off a DeriveFeature across every component (root and
    every sub-component, via the shared all_components walk). Resolved straight off `doc` (not
    _common.design(), which reads a DIFFERENT app seam than this module's own) - the same
    Design.cast(doc.products...) pattern doc_insert_derive.py uses for its source document."""
    design = safe(lambda: adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType')))
    if not design:
        return []
    out = []
    for comp in all_components(design):
        for feat in iter_collection(safe(lambda c=comp: c.features.deriveFeatures)):
            dref = safe(lambda f=feat: f.documentReference)
            if dref is None:
                continue
            out.append((_ref_name(dref), dref))
    return out


_REFRESHED_NOTE = ("References refreshed to their latest version. If a newly-added feature (e.g. a "
                   "joint origin) was missing because the reference was stale, it is now available. "
                   "Covers occurrence xrefs and derive links (see 'kind' on each row).")

_NOTHING_TO_REFRESH_NOTE = ("Nothing to refresh - every reference already reads current. If the "
                            "geometry still looks stale, that is the recompute, not the reference: "
                            "design_recompute.")


def _refresh_one(ref, label, only_out_of_date, use_setter=False):
    """Refresh ONE reference - an occurrence xref's DocumentReference or a DeriveFeature's, same
    shape - to its latest version: ('updated'|'skipped'|'error', record). use_setter picks HOW:
    getLatestVersion() raises InternalValidationError on a derive link, so that path assigns the
    'version' property instead and CATCHES its refusal rather than sinking the whole call."""
    ood = bool(safe(lambda r=ref: r.isOutOfDate, False))
    if only_out_of_date and not ood:
        return "skipped", {"name": label, "reason": "already up to date"}
    before_v = safe(lambda r=ref: r.version)
    if use_setter:
        latest = safe(lambda r=ref: r.dataFile.latestVersionNumber)
        if latest is None:
            return "error", {"name": label, "error": "could not read the source's latest version number"}
        try:
            ref.version = latest
        except Exception as e:
            return "error", {"name": label,
                             "error": (f"Fusion refused the refresh ({type(e).__name__}: {e}) - "
                                       "delete and re-derive (design_delete_feature, then "
                                       "doc_insert_derive) to pick up the source's latest version.")}
        did = True
    else:
        did = ref.getLatestVersion()
    if not did:
        return "error", {"name": label, "error": "getLatestVersion returned false"}
    after_v = safe(lambda r=ref: r.version)
    if bool(safe(lambda r=ref: r.isOutOfDate, False)):
        return "error", {"name": label, "error": "still out of date after the refresh"}
    return "updated", {"name": label, "version_before": before_v, "version_after": after_v,
                        "was_out_of_date": ood}


def _source_key(occ):
    """The lineage of the file an occurrence references, '' when it references none or is unread."""
    return _doc_common._lineage_key(safe(lambda: occ.documentReference.dataFile.id))


def _held(occ):
    """What is read off one occurrence before a change and compared through the SAME wrapper after."""
    return {"occ": occ, "path": safe(lambda: occ.fullPathName), "pose": _pose(occ),
            "source": _source_key(occ), "solids": _solids(safe(lambda: occ.component))}


def _cohort(design, occ):
    """(held rows for EVERY occurrence of occ's component, error): refused unless the census reads
    completely, holds `occ`, and each member reads its path, placement, source file and bodies."""
    comp = safe(lambda: occ.component)
    occs = safe(lambda: design.rootComponent.allOccurrencesByComponent(comp))
    total = safe(lambda: occs.count) if occs is not None else None
    unread = "could not be read completely before the change, so nothing was changed"
    if not isinstance(total, int) or isinstance(total, bool) or total < 1:
        return None, f"The occurrences of that component {unread}."
    members = [safe(lambda i=i: occs.item(i)) for i in range(total)]
    if any(m is None for m in members) or not any(
            safe(lambda m=m: m == occ) is True for m in members):
        return None, f"The occurrences of that component {unread}."
    rows = [_held(m) for m in members]
    for row in rows:
        if (not isinstance(row["path"], str) or not row["path"] or row["pose"] is None
                or not row["source"] or None in row["solids"]):
            return None, (f"The occurrence '{row['path']}' {unread} (its path, placement, source "
                          "file or bodies did not read).")
    return rows, None


def _is(row, occ):
    return safe(lambda: row["occ"] == occ) is True


def _kept(row):
    """True when an occurrence that was not to change still reads exactly what it read before."""
    o = row["occ"]
    return (_common.read_flag(lambda: o.isValid) is True
            and _common.read_flag(lambda: o.isReferencedComponent) is True
            and _source_key(o) == row["source"] and safe(lambda: o.fullPathName) == row["path"]
            and _same_pose(row["pose"], _pose(o)))


def _new_errors(design, before):
    return [str(n) for n in _common.timeline_health(design)[0] if n not in before]


def _target(action, occurrence):
    """(design, occurrence, error) for the two actions that change ONE occurrence's reference."""
    design = _common.design()
    if not design:
        return None, None, "No active design."
    if not (occurrence or "").strip():
        return None, None, f"action='{action}' needs 'occurrence' - the instance to change."
    occ, oerr = _OCCURRENCE.resolve(occurrence)
    if oerr:
        return None, None, oerr
    external = _common.read_flag(lambda: occ.isReferencedComponent)
    if external is not True:
        return None, None, (
            f"'{occurrence}' " + ("is a local component, not an external reference; "
                                  f"action='{action}' changes a reference." if external is False
                                  else "did not read whether it is an external reference."))
    return design, occ, None


def _replace(occurrence, file, replace_all):
    """Point one occurrence, or every occurrence of its component, at another saved file."""
    design, occ, terr = _target("replace", occurrence)
    if terr:
        return error(terr)
    raw = (file or "").strip()
    if not raw:
        return error("action='replace' needs 'file' - the replacement's lineage urn (data_get).")
    data_file, _resolved, candidates = _data_common._resolve_data_file(raw)
    if not data_file:
        return error(f"Could not resolve '{raw}' to a saved document. Tried: "
                     f"{', '.join(candidates) if candidates else raw}.")
    want = _doc_common._lineage_key(safe(lambda: data_file.id))
    if not want:
        return error(f"The file '{raw}' resolved but its id did not read, so the replace could "
                     "not be checked; nothing was changed.")
    if _source_key(occ) == want:
        return error(f"'{occurrence}' already references that file; nothing to replace.")
    cohort, cerr = _cohort(design, occ)
    if cerr:
        return error(cerr)
    targets = [row for row in cohort if replace_all or _is(row, occ)]
    untouched = [row for row in cohort if not (replace_all or _is(row, occ))]
    errors_before = _common.timeline_health(design)[0]
    try:
        answer = occ.replace(data_file, bool(replace_all))
    except Exception as e:
        return error(f"Could not replace '{occurrence}': {e}")
    if answer is not True:
        return error(f"Occurrence.replace answered {answer!r} for '{occurrence}'; re-read the "
                     "assembly with design_get(include=['tree']) before going on.")
    rows, faults = [], []
    for held in targets:
        o = held["occ"]
        row = {"path_before": held["path"]}
        if _common.read_flag(lambda o=o: o.isValid) is not True:
            row["reread"] = False
            faults.append(f"'{held['path']}' could not be re-read after the replace")
            rows.append(row)
            continue
        row["path"] = safe(lambda o=o: o.fullPathName)
        row["old_path_resolves"] = _resolves(design, held["path"])
        if _source_key(o) != want:
            faults.append(f"'{row['path']}' does not reference the requested file")
        if not _same_pose(held["pose"], _pose(o)):
            faults.append(f"'{row['path']}' did not keep its placement")
        if _path_fault(design, row["path"]):
            faults.append(_path_fault(design, row["path"]))
        rows.append(row)
    for row in untouched:
        if not _kept(row):
            faults.append(f"the sibling '{row['path']}' did not stay as it was")
    broke = _new_errors(design, errors_before)
    if broke:
        faults.append("these timeline items now read an error: " + ", ".join(broke))
    if faults:
        return error("The replace WAS made in the open document, but " + "; ".join(faults)
                     + ". Close without saving to discard it, or repair and re-read with "
                     "assembly_get.")
    return ok({"replaced": True, "file": want, "replace_all": bool(replace_all),
               "occurrences": rows,
               "note": ("Replaced in the open document only; nothing is saved. Each occurrence "
                        "kept its placement and took a new name: use 'path'. Not checked: joints "
                        "built on the replaced part's faces or edges - read assembly_get.")})


def _break_link(occurrence, new_name):
    """Make one external occurrence a local component under a new, unique component name."""
    design, occ, terr = _target("break_link", occurrence)
    if terr:
        return error(terr)
    wanted = (new_name or "").strip()
    if not wanted:
        return error("action='break_link' needs 'new_name' - the name the now-local component "
                     "takes, so its path cannot collide with a sibling still on that file.")
    taken = [safe(lambda c=c: c.name) for c in all_components(design)]
    if wanted in taken:
        return error(f"A component named '{wanted}' already exists; pass a 'new_name' that is "
                     "not in the design. Nothing was changed.")
    if _common.read_flag(lambda: occ.isConfiguration) is not False:
        return error(f"'{occurrence}' is a configuration (or did not read whether it is one); "
                     "breaking that link is not offered. Nothing was changed.")
    cohort, cerr = _cohort(design, occ)
    if cerr:
        return error(cerr)
    held = next(row for row in cohort if _is(row, occ))
    siblings = [row for row in cohort if not _is(row, occ)]
    try:
        answer = occ.breakLink()
    except Exception as e:
        return error(f"Could not break the link of '{occurrence}': {e}")
    if answer is not True:
        return error(f"Occurrence.breakLink answered {answer!r} for '{occurrence}'; re-read the "
                     "assembly with design_get(include=['tree']).")
    done = ("The link of '" + held["path"] + "' IS broken and this tool cannot restore it; the "
            "occurrence is now local")
    if (_common.read_flag(lambda: occ.isValid) is not True
            or _common.read_flag(lambda: occ.isReferencedComponent) is not False):
        return error(done + ", but it could not be re-read as a local occurrence. Find it with "
                     "design_get(include=['tree']) and rename its component so its path is "
                     "unique.")
    try:
        occ.component.name = wanted
    except Exception as e:
        return error(f"{done} at '{safe(lambda: occ.fullPathName)}', but its component could "
                     f"not be renamed to '{wanted}': {e}. Rename it with design_set_name.")
    landed, new_path = safe(lambda: occ.component.name), safe(lambda: occ.fullPathName)
    faults = []
    if landed != wanted:
        faults.append(f"its component reads '{landed}', not '{wanted}'")
    if _path_fault(design, new_path):
        faults.append(_path_fault(design, new_path))
    if not _same_pose(held["pose"], _pose(occ)):
        faults.append("it did not keep its placement")
    if _solids(safe(lambda: occ.component)) != held["solids"]:
        faults.append("its bodies do not read as before")
    for sib in siblings:
        if not _kept(sib):
            faults.append(f"the sibling '{sib['path']}' did not stay as it was")
    if faults:
        return error(f"{done} at '{new_path}', but " + "; ".join(faults) + ".")
    return ok({"broken": True, "occurrence": new_path, "path_before": held["path"],
               "component": landed, "reversible": False,
               "note": ("The occurrence is a local component now, in the open document only; "
                        "nothing is saved and the link cannot be restored. Its timeline item "
                        "became a group.")})


def handler(name: str = "", only_out_of_date: bool = True, action: str = "refresh",
            occurrence: str = "", file: str = "", replace_all: bool = None,
            new_name: str = "") -> dict:
    """See TOOL_DESCRIPTION."""
    act, aerr = _ACTION.resolve(action)
    if aerr:
        return error(aerr)
    owners = {"occurrence": ("replace", "break_link"), "file": ("replace",),
              "replace_all": ("replace",), "new_name": ("break_link",), "name": ("refresh",)}
    given = {"occurrence": occurrence, "file": file, "replace_all": replace_all,
             "new_name": new_name, "name": name}
    for key, acts in owners.items():
        if act not in acts and given[key] not in (None, ""):
            return error(f"'{key}' belongs to action=" + " / ".join(f"'{a}'" for a in acts)
                         + f", not '{act}'.")
    if act == "replace":
        return _replace(occurrence, file, replace_all)
    if act == "break_link":
        return _break_link(occurrence, new_name)
    doc = safe(lambda: app.activeDocument)
    if not doc:
        return error("No active document.")

    xref_items = [(_ref_name(r), r) for r in iter_collection(safe(lambda: doc.documentReferences))]
    derive_items = _derive_refs(doc)

    if not xref_items and not derive_items:
        return ok({"updated_count": 0, "updated": [],
                   "note": "This document has no external references (occurrence xrefs or derive links)."})

    want = (name or "").strip()
    rows = [(kind, rname, ref)
            for kind, items in (("xref", xref_items), ("derive", derive_items))
            for rname, ref in items]
    if want:
        # Case-INSENSITIVE match: 'name' is a source document's display NAME, not an identifier.
        # Every row of the matched FILE is refreshed (one source can be referenced several times),
        # but a name shared by DIFFERENT source files is refused rather than refreshed en masse.
        rows = [r for r in rows if r[1].strip().lower() == want.lower()]
        groups = _source_groups(rows)
        if len(groups) > 1:
            listed = "; ".join(_group_label(k, m) for k, m in groups.items())
            return error(
                f"'{name}' names {len(groups)} DIFFERENT source files referenced by this document: "
                f"{listed}. Fusion allows same-name files in different folders, so refreshing them "
                "all could pull a version you did not ask for - refusing. Omit 'name' to refresh "
                "every out-of-date reference, or inspect the rows with "
                "doc_get(include=['xref_tree']).")

    if want and not rows:
        available = [rname for rname, _ in xref_items] + [rname for rname, _ in derive_items]
        return error(f"No external reference named '{name}'. References in this document: "
                      f"{', '.join(available)}.")

    updated = []
    skipped = []
    errors = []
    for kind, rname, ref in rows:
        outcome, record = _refresh_one(ref, rname, only_out_of_date, use_setter=(kind == "derive"))
        record["kind"] = kind
        {"updated": updated, "skipped": skipped, "error": errors}[outcome].append(record)

    if errors:
        return error(f"Some references failed to update: {json.dumps(errors)}. "
                      f"(Updated: {len(updated)}.)")

    return ok({
        "updated_count": len(updated),
        "updated": updated,
        "skipped": skipped,
        "total_references": len(xref_items) + len(derive_items),
        "note": _NOTHING_TO_REFRESH_NOTE if not updated and skipped else _REFRESHED_NOTE,
    })


TOOL_DESCRIPTION = (
    "Refresh references and derive links to their latest cloud version, or replace / break ONE "
    "occurrence's link per 'action'."
)

tool = (
    Tool.create_simple(name="doc_update_xref", description=TOOL_DESCRIPTION)
    .add_input_property("name", {"type": "string",
            "description": "Source document name of one reference to refresh (omit = all)."})
    .add_input_property("only_out_of_date", {"type": "boolean"})
    .add_input_property(*_ACTION.as_property())
    .add_input_property(*_OCCURRENCE.as_property())
    .add_input_property("file", {"type": "string",
            "description": "Replacement lineage urn (replace)."})
    .add_input_property("replace_all", {"type": "boolean",
            "description": "Every occurrence of that component."})
    .add_input_property("new_name", {"type": "string", "description": (
        "Unique name for the now-local component (break_link). One-way.")})
    .strict_schema()
)

item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline",
        evidence_test="tests/unit/test_doc_update_xref.py::TestUpdateBehavior"
                      "::test_still_stale_after_true_return_is_an_error",
        rung="value"))


def register_tool():
    register(item)
