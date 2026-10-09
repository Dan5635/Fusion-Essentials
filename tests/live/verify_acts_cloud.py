# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""ACT rows: the OPT-IN CLOUD TIER - the data model, the saved document, and the drawing.

The acts that touch an operator's own Autodesk hub, and so run only where cloud_config names
one (verify_core._cloud_tier_probe). Each act creates run-stamped artifacts under the configured
folder. CAM persistence, configuration coupons and the favourite-parameter derive source are retained;
other artifacts are removed with read-back.
Each act ends by activating the document the session was on when the tier started, so a chunk
boundary can fall between them and a partial run leaves the session where it found it.
"""

import hashlib
import json
import os
import time
import copy

from cloud_config import FOLDER, HUB, PROJECT
from verify_acts_cam import (
    _launched_on, _op_created, _preset_applied, _template_applied, _template_path_state)
from verify_acts_model_precision import _section_camera
from verify_acts_model_solids import _edge_extent_geometry, _symmetric_target_body_state
from verify_acts_model_sweep import _retire_compare, _retire_design_state, _retire_material_state
from verify_acts_sketch import _script_reply
from verify_core import (
    EXPORT_DIR, MARKER_PNG, NOTE_MAX, _RECALL, _Refusal, _activated, _ctx_get, _document_closed,
    _driven_slide, _dwell, _extruded, _face_up_at, _fg, _home_address, _home_document, _jointed,
    _made_component, _measured, _motion_linked, _new_document, _near, _num, _recall, _refused,
    _watch, facade)

_STAMP = time.strftime("%Y%m%d-%H%M%S")

# THE ARTIFACTS, all run-stamped so two overlapping runs never collide on one name and a run that
# died leaves artifacts a later one can tell from its own.
RUN_FOLDER = "SweepRun " + _STAMP            # under the configured folder
MOVED_FOLDER = "Moved"                       # under RUN_FOLDER - where the move beat lands the file
SOURCE_DOC = "SweepCloudSource." + _STAMP     # the saved design the drawing is generated from
COPY_DOC = "SweepCloudCopy " + _STAMP        # doc_copy's destination
HOST_DOC = "SweepCloudHost " + _STAMP        # the scratch host the source is inserted into
DERIVE_DOC = "SweepCloudDerive " + _STAMP    # the derive host whose stale link is read after a reopen
LINK_DOC = "SweepCloudLink " + _STAMP        # the xref assembly the both-members drive guard is read in

RUN_PATH = f"{FOLDER}/{RUN_FOLDER}"
MOVED_PATH = f"{RUN_PATH}/{MOVED_FOLDER}"

# The component the source document is built from, in ITS OWN document - see _lit.
SRC_COMP = "CloudSrc"
SRC_SKETCH = "CloudSrcPlate"

# Where the three xref instances of the plate stand in the link document, spaced down X so ONE
# design-wide find_geometry resolves each one's faces by position: every instance answers to the
# same stamped document name, so a name cannot tell them apart. The plate spans 80 x 50 x 10 mm
# from its own origin, and the face centres below are read off that.
_LINK_X = (0.0, 200.0, 400.0)
_PLATE_MID_X, _PLATE_MID_Y, _PLATE_TOP_Z = 40.0, 25.0, 10.0

# The version the restore beat promotes. It must be one the tip has MOVED PAST: MEASURED, promoting
# the latest takes the tool's early return - "already the latest version; nothing to restore", with
# no promote call and no tip to compare - and the cloud's version stream lags the saves that made it,
# so the only number certain to be behind the tip is the first. The parameter a later beat edits
# survives it: promoting a version does not reload the session, and the save after this one writes
# the open document's own state as the new tip.
RESTORE_VERSION = 1

DOWNLOAD_DIR = EXPORT_DIR + "/cloud"
DOWNLOAD_RUN_DIR = DOWNLOAD_DIR + "/download-" + _STAMP
_DRAWING_BEFORE_PDF = DOWNLOAD_DIR + f"/drawing_persistence_before_{_STAMP}.pdf"
_DRAWING_AFTER_PDF = DOWNLOAD_DIR + f"/drawing_persistence_after_{_STAMP}.pdf"
_DRAWING_NAMED_BEFORE_PDF = DOWNLOAD_DIR + f"/drawing_named_before_{_STAMP}.pdf"
_DRAWING_NAMED_AFTER_PDF = DOWNLOAD_DIR + f"/drawing_named_after_{_STAMP}.pdf"
_DRAWING_INVALID_PDF = DOWNLOAD_DIR + f"/drawing_invalid_sheet_{_STAMP}.pdf"
_DRAWING_INVALID_KEY = "drawing-invalid-sheet-" + _STAMP
_DRAWING_COPY_SHEET = "SweepCloudCopySheet " + _STAMP
_DRAWING_POPULATED_SHEET = "SweepCloudPopulatedSheet " + _STAMP
_DRAWING_POPULATED_SKETCH = "SweepCloudCopyWitness " + _STAMP
_DRAWING_TWO_BEFORE_PDF = DOWNLOAD_DIR + f"/drawing_two_sheet_before_{_STAMP}.pdf"
_DRAWING_TWO_AFTER_PDF = DOWNLOAD_DIR + f"/drawing_two_sheet_after_{_STAMP}.pdf"
_DRAWING_POPULATED_PDF = DOWNLOAD_DIR + f"/drawing_populated_copy_{_STAMP}.pdf"
_DRAWING_UPDATE_BEFORE_PDF = DOWNLOAD_DIR + f"/drawing_update_before_{_STAMP}.pdf"
_DRAWING_UPDATE_AFTER_PDF = DOWNLOAD_DIR + f"/drawing_update_after_{_STAMP}.pdf"
_DRAWING_RESTORED_PDF = DOWNLOAD_DIR + f"/drawing_restored_{_STAMP}.pdf"
_DRAWING_SKETCH_DXF = DOWNLOAD_DIR + f"/drawing_sketch_readback_{_STAMP}.dxf"
_DRAWING_WORKLOAD_DXF = DOWNLOAD_DIR + f"/drawing_workload_readback_{_STAMP}.dxf"
_DRAWING_BLANK_DXF = DOWNLOAD_DIR + f"/drawing_blank_sheet_{_STAMP}.dxf"
_DRAWING_SKETCH_NAME = "SweepCloudSketch"
_DRAWING_WORKLOAD_NAME = "SweepCloudWorkload16"
_DRAWING_BLANK_SKETCH_NAME = "SweepCloudBlankSketch"
_DRAWING_WORKLOAD_GEOMETRY = [
    {"kind": "line", "points": [[20 + 2 * i, 20], [21 + 2 * i, 22]]}
    for i in range(16)]
_DRAWING_WORKLOAD_17_ENTITIES = [
    {"kind": "line", "points": [[20 + 2 * i, 30], [21 + 2 * i, 32]]}
    for i in range(17)]
_DRAWING_WORKLOAD_17_SEGMENT_CHAIN = {
    "kind": "line", "points": [[20 + i, 40 + i % 2] for i in range(18)]}
_DRAWING_TWO_BEFORE_KEY = "drawing-two-before-" + _STAMP
_DRAWING_TWO_AFTER_KEY = "drawing-two-after-" + _STAMP
_DRAWING_POPULATED_KEY = "drawing-populated-" + _STAMP
_DRAWING_UPDATE_BEFORE_KEY = "drawing-update-before-" + _STAMP
_DRAWING_UPDATE_KEY = "drawing-update-12-" + _STAMP
_DRAWING_UPDATE_AFTER_KEY = "drawing-update-after-" + _STAMP
_DRAWING_RESTORE_KEY = "drawing-restore-10-" + _STAMP
_DRAWING_RESTORED_PDF_KEY = "drawing-restored-pdf-" + _STAMP
DOWNLOAD_FILE = "roundtrip-" + _STAMP + ".png"
_DOWNLOAD_PREIMAGE = b"Fusion sweep download preimage\n"
_DOWNLOAD_STAGE_PREFIX = ".fusion-download-"


def _lit(args):
    """Return authored document-local arguments without chunk translation."""
    return lambda _ctx, _a=args: dict(_a)


def _upload_args(ctx):
    """Start a fresh upload attempt and capture the exact local source bytes."""
    for key in ("upload_handle", "cloud_file", "cloud_file_name", "upload_source"):
        ctx.pop(key, None)
    _RECALL.pop("download_probe", None)
    source = _disk_facts(MARKER_PNG)
    if source is None or source["size_bytes"] <= 0:
        raise AssertionError("the upload source is missing or empty")
    ctx["upload_source"] = source
    return {"file_path": MARKER_PNG, "project": PROJECT, "folder": RUN_PATH}


def _upload_status_args(ctx):
    """Read the current attempt's exact minted upload handle and invalidate stale lineage."""
    for key in ("cloud_file", "cloud_file_name"):
        ctx.pop(key, None)
    return {"handle": _ctx_get(ctx, "upload_handle", "the upload")}


def _dependent_folder_args(ctx, folder_key, name):
    """Build cleanup args only after the current upload has produced its file lineage."""
    _ctx_get(ctx, "cloud_file", "the uploaded file")
    return {"folder_id": _ctx_get(ctx, folder_key, "the folder"), "confirm_name": name}


def _disk_facts(path):
    """Return one file's exact absolute path, size and SHA-256, or None."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    return {"file_path": os.path.abspath(path), "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def _download_refusal_args(ctx):
    """Seed the owned target with distinct bytes before the no-overwrite request."""
    source_id = _ctx_get(ctx, "cloud_file", "the uploaded file")
    source = _ctx_get(ctx, "upload_source", "the captured upload source")
    os.makedirs(DOWNLOAD_RUN_DIR, exist_ok=True)
    target = os.path.join(DOWNLOAD_RUN_DIR, DOWNLOAD_FILE)
    with open(target, "wb") as fh:
        fh.write(_DOWNLOAD_PREIMAGE)
    preimage = _disk_facts(target)
    if preimage is None or preimage["sha256"] == source.get("sha256"):
        raise AssertionError("the download preimage is not distinct from the upload source")
    _RECALL["download_probe"] = {"source_id": source_id, "source": source,
                                  "preimage": preimage}
    return {"file": source_id, "destination_folder": DOWNLOAD_RUN_DIR,
            "file_name": DOWNLOAD_FILE, "overwrite": False}


def _download_overwrite_args(ctx):
    """Require the refused call to preserve the preimage before allowing overwrite."""
    source_id = _ctx_get(ctx, "cloud_file", "the uploaded file")
    proof = _RECALL.get("download_probe") or {}
    current = _disk_facts(os.path.join(DOWNLOAD_RUN_DIR, DOWNLOAD_FILE))
    leftovers = ([name for name in os.listdir(DOWNLOAD_RUN_DIR)
                  if name.startswith(_DOWNLOAD_STAGE_PREFIX)]
                 if os.path.isdir(DOWNLOAD_RUN_DIR) else None)
    if (proof.get("source_id") != source_id or current != proof.get("preimage")
            or leftovers != []):
        raise AssertionError("the no-overwrite refusal did not preserve the exact owned preimage")
    return {"file": source_id, "destination_folder": DOWNLOAD_RUN_DIR,
            "file_name": DOWNLOAD_FILE, "overwrite": True}


def _download_boolean_args(ctx):
    """Prepare the existing owned preimage for a malformed Boolean refusal."""
    args = _download_refusal_args(ctx)
    args.update(overwrite="false", expect_document="session:BOOLEAN-GUARD-MISMATCH")
    return args


def _cloud_boolean_unchanged(p, download=False):
    """Check the complete census and optional exact local preimage after a Boolean refusal."""
    if p != _RECALL.get("cloud_boolean_census"):
        return False
    if not download:
        return True
    proof = _RECALL.get("download_probe") or {}
    return (_disk_facts(os.path.join(DOWNLOAD_RUN_DIR, DOWNLOAD_FILE)) == proof.get("preimage")
            and os.listdir(DOWNLOAD_RUN_DIR) == [DOWNLOAD_FILE])


# --- predicates: each reads keys the tool PUBLISHES, and reports what it read ------------------

def _hub_is(hub, project):
    """data_get (no scope): the hub this session is signed in to, and the configured project listed
    in it. The capability probe reads the same two values before the act runs; this row is what puts
    them on the ledger, so the receipt says which hub the artifacts below were made in."""
    def check(p):
        names = [str(r.get("name")) for r in (p.get("projects") or [])]
        return _measured(f"active hub '{hub}' lists project '{project}'",
                         {"active_hub": p.get("active_hub"),
                          "project_count": p.get("project_count"),
                          "project_listed": project in names,
                          "time_truncated": p.get("time_truncated")},
                         p.get("active_hub") == hub and project in names
                         and p.get("project_count") == len(names))
    return check


def _folder_created(name, parent):
    """data_create_folder: the folder re-listed under the parent asked for, and NOTHING auto-created
    on the way there. The configured folder is the operator's; a run that had to invent it is
    addressing a project this config does not describe."""
    def check(p):
        return _measured(f"'{name}' created under '{parent}', no parent invented",
                         {"created": p.get("created"), "name": p.get("name"), "id": p.get("id"),
                          "path": p.get("path"),
                          "auto_created_parents": p.get("auto_created_parents")},
                         p.get("created") is True and p.get("name") == name
                         and bool(p.get("id")) and p.get("path") == f"{parent}/{name}"
                         and p.get("auto_created_parents") == [])
    return check


def _upload_started(folder):
    """data_upload_file: the poll handle it minted and the destination it resolved. The tool claims
    no completion here - data_get_upload_status is what says the file landed."""
    def check(p):
        return _measured(f"upload started into '{folder}'",
                         {"upload_started": p.get("upload_started"),
                          "upload_handle": p.get("upload_handle"),
                          "destination_folder": p.get("destination_folder"),
                          "upload_state": p.get("upload_state")},
                         p.get("upload_started") is True and bool(p.get("upload_handle"))
                         and p.get("destination_folder") == folder)
    return check


def _upload_complete(p):
    """data_get_upload_status: the cloud reports transfer AND processing finished, and hands back the
    lineage URN every later step addresses the file by. A bare 'ok' here would let the move, the
    download and the delete run at a file that is not there yet."""
    return _measured("upload state 'complete' with a lineage URN",
                     {"state": p.get("state"), "handle": p.get("handle"),
                      "file_id": p.get("file_id"), "version_number": p.get("version_number"),
                      "elapsed_seconds": p.get("elapsed_seconds")},
                     p.get("state") == "complete"
                     and isinstance(p.get("file_id"), str)
                     and p["file_id"].startswith("urn:") and len(p["file_id"]) > 4)


def _file_record(folder_path, complete=True):
    """data_get(file=<urn>): the file's own record - where it sits, and whether the cloud has
    finished with it. 'is_complete' is what the drawing generator needs true of its source;
    complete=None reads the flag without judging it - on an uploaded IMAGE it read False 25
    minutes after data_get_upload_status read 'complete' with a lineage (measured), so for a
    non-CAD upload that status, not this flag, is the completion signal."""
    def check(p):
        f, loc, state = p.get("file") or {}, p.get("location") or {}, p.get("state") or {}
        flag = "unjudged" if complete is None else complete
        return _measured(f"the file's record reads folder '{folder_path}', is_complete {flag}",
                         {"name": f.get("name"), "id": f.get("id"),
                          "parent_folder": (loc.get("parent_folder") or {}).get("path"),
                          "state": state, "matched_by": p.get("matched_by")},
                         bool(f.get("name")) and str(f.get("id") or "").startswith("urn:")
                         and (loc.get("parent_folder") or {}).get("path") == folder_path
                         and (complete is None or state.get("is_complete") is complete))
    return check


def _capped_name_move_probe(ctx):
    """Build a native probe for capped name lookup and exact-URN control."""
    file_name = _ctx_get(ctx, "cloud_file_name", "the uploaded file")
    file_id = _ctx_get(ctx, "cloud_file", "the uploaded file")
    project_id = _ctx_get(ctx, "data_root_summary", "the configured project")["project_id"]
    script = f'''import json, sys

def run(context):
    import adsk.core
    def module(suffix):
        found = [m for m in sys.modules.values()
                 if str(getattr(m, '__name__', '')).endswith(suffix)]
        assert len(found) == 1, (suffix, len(found))
        return found[0]
    dc = module('.mcpServer.tools._data_common')
    dr = module('._data_read')
    move = module('.data_move_file')
    app = adsk.core.Application.get()
    projects = [p for p in app.data.dataProjects.asArray() if p.id == {json.dumps(project_id)}]
    assert len(projects) == 1
    project = projects[0]
    folder, missing = dc._resolve_folder_path(project.rootFolder,
                                               dc._split_path({json.dumps(RUN_PATH)}))
    assert folder is not None and missing is None
    files = folder.dataFiles.asArray()
    children = folder.dataFolders.asArray()
    assert files and children
    chosen = files[0]
    assert chosen.name == {json.dumps(file_name)} and chosen.id == {json.dumps(file_id)}
    before_parent = chosen.parentFolder.id
    assert before_parent == folder.id
    old_cap = dr._MAX_FILES
    try:
        dr._MAX_FILES = 1
        refused = move.handler(file=chosen.name, project={json.dumps(PROJECT)},
                               folder={json.dumps(RUN_PATH)},
                               target_folder={json.dumps(RUN_PATH)})
    finally:
        dr._MAX_FILES = old_cap
    cap_restored = dr._MAX_FILES == old_cap
    after_refusal = chosen.parentFolder.id
    original_find_project = dc._find_project
    def injected_project_error(*args, **kwargs):
        raise RuntimeError('synthetic project lookup failure')
    try:
        dc._find_project = injected_project_error
        project_error = move.handler(file=chosen.name, project={json.dumps(PROJECT)},
                                      folder={json.dumps(RUN_PATH)},
                                      target_folder={json.dumps(RUN_PATH)})
    finally:
        dc._find_project = original_find_project
    project_finder_restored = dc._find_project is original_find_project
    after_project_error = chosen.parentFolder.id
    exact = move.handler(file=chosen.id, project={json.dumps(PROJECT)},
                         target_folder={json.dumps(RUN_PATH)})
    after_exact = chosen.parentFolder.id
    def outcome(result):
        text = (result.get('content') or [{{}}])[0].get('text', '')
        try:
            payload = json.loads(text)
        except Exception:
            payload = text
        return {{'is_error': result.get('isError'), 'payload': payload}}
    print(json.dumps({{'file_name': chosen.name, 'file_id': chosen.id,
        'folder_id': folder.id, 'file_count': len(files), 'child_folder_count': len(children),
        'before_parent_id': before_parent, 'after_refusal_parent_id': after_refusal,
        'after_project_error_parent_id': after_project_error,
        'after_exact_parent_id': after_exact, 'cap_restored': cap_restored,
        'project_finder_restored': project_finder_restored,
        'project_lookup_error_injected': True,
        'capped_by_name': outcome(refused), 'injected_project_error': outcome(project_error),
        'exact_urn': outcome(exact)}}))
'''
    return {"script": script, "read_only": False}


def _duplicate_project_probe(_ctx):
    """Exercise loaded public handlers with an injected duplicate census and no cloud writes."""
    return {"read_only": False, "script": '''import json, sys
from types import SimpleNamespace

def run(context):
    def module(suffix):
        hits = [m for n, m in sys.modules.items() if n.endswith(suffix)]
        assert len(hits) == 1
        return hits[0]
    create = module('.tools.data_create_project')
    read = module('.tools._data_read')
    get = module('.tools.data_get')
    adds = []
    def refuse_add(*args):
        adds.append(args)
        raise RuntimeError('diagnostic forbids cloud creation')
    entries = [SimpleNamespace(name=n, id=i) for n, i in
               [('SweepDuplicate', 'diagnostic-a'), ('SweepDuplicate', 'diagnostic-b'),
                ('UnrelatedProject', 'diagnostic-other')]]
    data = SimpleNamespace(dataProjects=SimpleNamespace(asArray=lambda: entries, add=refuse_add))
    old_create, old_read = create._data, read.app
    try:
        create._data = lambda: data
        read.app = SimpleNamespace(data=data)
        refused_create = create.handler(name='SweepDuplicate')
        refused_read = get.handler(project='SweepDuplicate', recursive=False)
    finally:
        create._data, read.app = old_create, old_read
    def result(value):
        return {'is_error': value.get('isError') is True,
                'text': (value.get('content') or [{}])[0].get('text', '')}
    print(json.dumps({'injected_census': True, 'add_calls': len(adds),
        'restored': create._data is old_create and read.app is old_read,
        'create': result(refused_create), 'read': result(refused_read)}))
'''}


def _duplicate_project_result(value):
    """Check both matching IDs, omitted unrelated candidates, valid remedies and restored seams."""
    p = value if isinstance(value, dict) else json.loads(value)
    create, read = p.get('create') or {}, p.get('read') or {}
    return _measured('injected project-name ambiguity through loaded handlers', p,
        p.get('injected_census') is True and p.get('add_calls') == 0 and p.get('restored') is True
        and all(row.get('is_error') is True
                and all(x in row.get('text', '') for x in ('diagnostic-a', 'diagnostic-b', 'matches 2'))
                and 'diagnostic-other' not in row.get('text', '')
                and 'UnrelatedProject' not in row.get('text', '') for row in (create, read))
        and 'project_id' not in create.get('text', '')
        and 'use a different name' in create.get('text', '')
        and 'pass an exact project_id' in read.get('text', ''))


def _duplicate_hub_probe(_ctx):
    """Drive the loaded hub switch over injected same-name and unread-name hub censuses."""
    return {"read_only": False, "script": '''import json, sys
from types import SimpleNamespace

def run(context):
    def module(suffix):
        hits = [m for n, m in sys.modules.items() if n.endswith(suffix)]
        assert len(hits) == 1
        return hits[0]
    switch = module('.tools.data_switch_hub')
    sets = []
    class Hub:
        def __init__(self, name, hub_id):
            self._name, self.id = name, hub_id
        @property
        def name(self):
            if self._name is None:
                raise RuntimeError('diagnostic unreadable hub name')
            return self._name
    class Hubs:
        def __init__(self, rows):
            self.rows = rows
            self.count = len(rows)
        def item(self, i):
            return self.rows[i]
    class Data:
        def __init__(self, rows):
            self.dataHubs, self._active = Hubs(rows), rows[-1]
        @property
        def activeHub(self):
            return self._active
        @activeHub.setter
        def activeHub(self, hub):
            sets.append(hub.id)
    other = ('UnrelatedHub', 'diagnostic-hub-other')
    twins = Data([Hub('SweepHub', 'diagnostic-hub-a'), Hub('SweepHub', 'diagnostic-hub-b'),
                  Hub(*other)])
    blind = Data([Hub('SweepHub', 'diagnostic-hub-a'), Hub(None, 'diagnostic-hub-blind'),
                  Hub(*other)])
    old_app = switch.app
    try:
        switch.app = SimpleNamespace(data=twins)
        ambiguous = switch.handler(action='switch', hub='SweepHub')
        switch.app = SimpleNamespace(data=blind)
        unread = switch.handler(action='switch', hub='SweepHub')
    finally:
        switch.app = old_app
    def result(value):
        return {'is_error': value.get('isError') is True,
                'text': (value.get('content') or [{}])[0].get('text', '')}
    print(json.dumps({'injected_census': True, 'set_calls': len(sets),
        'restored': switch.app is old_app,
        'ambiguous': result(ambiguous), 'unread': result(unread)}))
'''}


def _duplicate_hub_result(value):
    """Check both refusals name their candidates by id, no hub was assigned and the seam restored."""
    p = value if isinstance(value, dict) else json.loads(value)
    twins, blind = p.get("ambiguous") or {}, p.get("unread") or {}
    return _measured("injected hub-name ambiguity through the loaded switch", p,
        p.get("injected_census") is True and p.get("set_calls") == 0 and p.get("restored") is True
        and twins.get("is_error") is True and blind.get("is_error") is True
        and all(x in twins.get("text", "") for x in ("matches 2 hubs", "diagnostic-hub-a",
                                                    "diagnostic-hub-b", "hub=<id>"))
        and all(x in blind.get("text", "") for x in ("diagnostic-hub-blind", "did not read",
                                                    "hub=<id>"))
        and all("diagnostic-hub-other" not in row.get("text", "") for row in (twins, blind)))


def _hubs_untouched(p):
    """data_get(include=['hubs']): the configured hub is still the one active hub, no injected row."""
    rows = p.get("hubs") or []
    return _measured(f"'{HUB}' still the only active hub", p,
                     (p.get("active_hub") or {}).get("name") == HUB
                     and p.get("hub_count") == len(rows) >= 1
                     and [r.get("name") for r in rows if r.get("is_active")] == [HUB]
                     and not any(str(r.get("id", "")).startswith("diagnostic-") for r in rows))


def _hub_edit_preflight_probe(ctx):
    """Check the loaded guard on real dirty cloud documents with a trapped hub assignment."""
    lineage = _ctx_get(ctx, "source_urn", "the saved source")
    return {"read_only": False, "script": f'''import adsk.core, json, sys
from types import SimpleNamespace

def run(context):
    app = adsk.core.Application.get()
    assert app.activeDocument.dataFile.id == {lineage!r}
    assert app.activeDocument.isModified is True
    modules = [m for n, m in sys.modules.items() if n.endswith('.tools.data_switch_hub')]
    assert len(modules) == 1
    switch = modules[0]
    active = app.data.activeHub
    target = SimpleNamespace(name='Diagnostic target', id='diagnostic-preflight-hub')
    class Hubs:
        count = 2
        def item(self, index):
            return (active, target)[index]
    class Data:
        dataHubs = Hubs()
        sets = 0
        @property
        def activeHub(self):
            return active
        @activeHub.setter
        def activeHub(self, hub):
            self.sets += 1
            raise RuntimeError('diagnostic assignment trap; no native hub switched')
    data = Data()
    original = switch.app
    try:
        switch.app = SimpleNamespace(data=data, documents=app.documents)
        result = switch.handler(action='switch', hub=target.id)
    finally:
        switch.app = original
    print(json.dumps({{'is_error': result.get('isError') is True,
        'result': json.loads(result['content'][0]['text']),
        'set_calls': data.sets, 'restored': switch.app is original,
        'native_documents': True, 'injected_target': True}}))
'''}


def _hub_edit_preflight_result(value):
    """Require the exact saved source's refusal and actionable remedies before any assignment."""
    p = value if isinstance(value, dict) else json.loads(value)
    result = p.get("result") or {}
    rows = result.get("modified_cloud_documents") or []
    expected = _RECALL.get("hub_edit_census") or {}
    active = expected.get("active") or {}
    source = [row for row in rows if row.get("document_handle") == active.get("document_handle")]
    handle = active.get("document_handle")
    remedies = (f"doc_activate(name='{handle}')", f"doc_save(expect_document='{handle}')",
                f"doc_close(name='{handle}', save_changes=false)")
    return _measured("real modified cloud source refused before trapped hub assignment", p,
        p.get("is_error") is True and p.get("set_calls") == 0 and p.get("restored") is True
        and p.get("native_documents") is True and p.get("injected_target") is True
        and result.get("blocked_by") == "modified_cloud_documents"
        and result.get("modified_cloud_document_count") == len(rows) >= 1
        and result.get("modified_cloud_documents_truncated") is False
        and len(source) == 1 and source[0].get("is_modified") is True
        and source[0].get("document_id") == _RECALL.get("source_urn")
        and all(text in source[0].get("remedy", "") for text in remedies))


def _capped_name_move_result(stdout):
    """Check the cap refusal, unchanged parent and exact-URN idempotence from the native probe."""
    if isinstance(stdout, dict):
        result = stdout
    else:
        try:
            result = json.loads(stdout)
        except Exception as exc:
            raise AssertionError(f"native cloud lookup probe did not return JSON: {stdout!r}") from exc
    limited = result.get("capped_by_name") or {}
    injected = result.get("injected_project_error") or {}
    exact = result.get("exact_urn") or {}
    refusal = limited.get("payload") or ""
    project_error = injected.get("payload") or ""
    moved = exact.get("payload") or {}
    return _measured(
        "capped name move refused before mutation and exact URN stayed idempotent",
        result,
        result.get("file_count", 0) >= 1 and result.get("child_folder_count", 0) >= 1
        and bool(result.get("file_name")) and str(result.get("file_id") or "").startswith("urn:")
        and result.get("cap_restored") is True
        and limited.get("is_error") is True and "name census is incomplete" in refusal
        and result.get("before_parent_id") == result.get("after_refusal_parent_id")
        and result.get("project_lookup_error_injected") is True
        and result.get("project_finder_restored") is True
        and injected.get("is_error") is True
        and "synthetic project lookup failure" in project_error
        and "data_get(project_id=<id>)" in project_error
        and "as 'file'" in project_error
        and result.get("before_parent_id") == result.get("after_project_error_parent_id")
        and exact.get("is_error") is False and moved.get("already_in_target") is True
        and result.get("before_parent_id") == result.get("after_exact_parent_id"))


# The cloud finishes with a saved file on its own clock (its record reads is_complete False for
# tens of seconds after the save answers, and past a full minute on a slow day - an uploaded
# marker measured so), and both the drawing generator and a delete need it finished. Bounded:
# the budget running out is reported as the state it last read, never as complete.
_SETTLE_POLLS = 96
_SETTLE_GAP_S = 5.0


def _file_settled(folder_path, polls=_SETTLE_POLLS, *, file_key=None, file_name=None):
    """data_get(file=<urn>) re-read until the record reads is_complete True, then judged by
    _file_record; the LAST read is what a failure prints."""
    record = _file_record(folder_path)

    def check(p):
        call = facade("call")        # resolved when the row runs, after tool_verify has loaded
        expected = _RECALL.get(file_key) if file_key else None
        for i in range(polls):
            if file_key:
                current = p.get("file") or {}
                _measured("publication reads the exact saved source", current,
                          bool(expected) and current.get("id") == expected
                          and current.get("name") == file_name)
            if (p.get("state") or {}).get("is_complete") is True or i == polls - 1:
                break
            time.sleep(_SETTLE_GAP_S)
            is_error, again = call("data_get", {"file": (p.get("file") or {}).get("id") or ""})
            if not is_error and isinstance(again, dict):
                p = again
        return record(p)
    return check


def _moved_to(folder_path):
    """data_move_file: DataFile.move returns a bool, so the tool re-resolves the file and re-reads
    its parent - 'to_folder' is that re-read, and 'verified_by' names what it matched on."""
    def check(p):
        return _measured(f"the file re-reads its parent as '{folder_path}'",
                         {"moved": p.get("moved"), "verified_by": p.get("verified_by"),
                          "from_folder": p.get("from_folder"), "to_folder": p.get("to_folder"),
                          "name": p.get("name")},
                         p.get("moved") is True and p.get("to_folder") == folder_path
                         and bool(p.get("verified_by")))
    return check


def _downloaded(p):
    """Verify the exact uploaded bytes replaced the owned preimage at the requested path."""
    proof = _RECALL.get("download_probe") or {}
    source, preimage = proof.get("source") or {}, proof.get("preimage") or {}
    expected_path = os.path.join(DOWNLOAD_RUN_DIR, DOWNLOAD_FILE)
    actual = _disk_facts(expected_path)
    leftovers = ([name for name in os.listdir(DOWNLOAD_RUN_DIR)
                  if name.startswith(_DOWNLOAD_STAGE_PREFIX)]
                 if os.path.isdir(DOWNLOAD_RUN_DIR) else None)
    observed_source = p.get("source") or {}
    return _measured(
        "the exact uploaded bytes replaced the owned preimage",
        {"downloaded": p.get("downloaded"), "file_path": p.get("file_path"),
         "size_bytes": p.get("size_bytes"), "source_id": observed_source.get("id"),
         "source_sha256": source.get("sha256"),
         "preimage_sha256": preimage.get("sha256"),
         "download_sha256": (actual or {}).get("sha256"),
         "staging_leftovers": leftovers},
        p.get("downloaded") is True
        and p.get("overwrote_existing") is True
        and observed_source.get("id") == proof.get("source_id")
        and p.get("name_scope_truncated") is False
        and p.get("name_scope_folders_unreadable") == 0
        and isinstance(p.get("file_path"), str)
        and os.path.abspath(p["file_path"]) == os.path.abspath(expected_path)
        and actual is not None and actual["size_bytes"] > 0
        and _num(p.get("size_bytes")) and p["size_bytes"] == actual["size_bytes"]
        and actual["size_bytes"] == source.get("size_bytes")
        and actual["sha256"] == source.get("sha256")
        and actual["sha256"] != preimage.get("sha256")
        and leftovers == [])


def _file_deleted(p):
    """data_delete_file: deleteMe() returned true (the tool errors on false), the file's own name and
    URN come back, 'forced' false says no reference check was bypassed, and the re-resolve after
    the delete observed the lineage absent."""
    return _measured("the cloud file was deleted",
                     {"deleted": p.get("deleted"), "name": p.get("name"),
                      "document_id": p.get("document_id"),
                      "was_referenced_by": p.get("was_referenced_by"),
                      "forced": p.get("forced"), "absence_observed": p.get("absence_observed")},
                     p.get("deleted") is True and bool(p.get("name"))
                     and str(p.get("document_id") or "").startswith("urn:")
                     and p.get("forced") is False and p.get("absence_observed") is True)


def _folder_deleted(name):
    """data_delete_folder on an EMPTIED folder: the census read before the delete says the subtree
    was empty, so 'recursive' false is the delete taking nothing else with it."""
    def check(p):
        return _measured(f"'{name}' deleted with nothing in it",
                         {"deleted": p.get("deleted"), "name": p.get("name"),
                          "contained_files": p.get("contained_files"),
                          "contained_subfolders": p.get("contained_subfolders"),
                          "recursive": p.get("recursive"),
                          "absence_observed": p.get("absence_observed")},
                         p.get("deleted") is True and p.get("name") == name
                         and p.get("recursive") is False and p.get("absence_observed") is True
                         and p.get("contained_files") == 0
                         and p.get("contained_subfolders") == 0)
    return check


def _root_summary(p):
    """data_get(summary): the configured project and its actual root identity with readable counts."""
    project, folder = p.get("project") or {}, p.get("folder") or {}
    files, children = p.get("immediate_file_count"), p.get("immediate_child_folder_count")
    return _measured(
        "the project root identity and both immediate counts",
        {"exists": p.get("exists"), "project": project, "folder": folder,
         "immediate_file_count": files, "immediate_child_folder_count": children,
         "unavailable_fields": p.get("unavailable_fields")},
        p.get("exists") is True and project.get("name") == PROJECT
        and bool(project.get("id")) and bool(folder.get("id"))
        and folder.get("path") == "(project root)" and folder.get("is_root") is True
        and isinstance(files, int) and not isinstance(files, bool) and files >= 0
        and isinstance(children, int) and not isinstance(children, bool) and children >= 1
        and p.get("unavailable_fields") == [])


def _root_summary_facts(p):
    """The exact identities and counts later root reads must agree with."""
    return {
        "project_id": (p.get("project") or {}).get("id"),
        "folder_id": (p.get("folder") or {}).get("id"),
        "file_count": p.get("immediate_file_count"),
        "child_folder_count": p.get("immediate_child_folder_count"),
    }


def _same_root_summary(p):
    """The project-ID-precedence read must resolve the same root and counts already observed."""
    expected = _RECALL.get("data_root_summary") or {}
    project, folder = p.get("project") or {}, p.get("folder") or {}
    actual = {
        "project_id": project.get("id"),
        "folder_id": folder.get("id"),
        "file_count": p.get("immediate_file_count"),
        "child_folder_count": p.get("immediate_child_folder_count"),
    }
    return _measured(
        "project_id precedence resolves the same project root",
        {"expected": expected, "actual": actual, "project_name": project.get("name"),
         "folder_path": folder.get("path"), "is_root": folder.get("is_root")},
        actual == expected and project.get("name") == PROJECT
        and folder.get("path") == "(project root)" and folder.get("is_root") is True
        and p.get("exists") is True and p.get("unavailable_fields") == [])


def _root_files(p):
    """A root nonrecursive listing agrees with the independent root count and has no nested rows."""
    expected = _RECALL.get("data_root_summary") or {}
    rows = p.get("files") or []
    ids = [r.get("id") for r in rows]
    nested = _RECALL.get("cloud_file")
    return _measured(
        "the project root's immediate files only",
        {"folder": p.get("folder"), "recursive": p.get("recursive"),
         "file_count": p.get("file_count"), "expected_count": expected.get("file_count"),
         "file_ids": ids, "known_nested_file": nested,
         "folder_paths": [r.get("folder_path") for r in rows],
         "truncated": p.get("truncated"), "time_truncated": p.get("time_truncated"),
         "folders_unreadable": p.get("folders_unreadable")},
        p.get("folder") == "(project root)" and p.get("recursive") is False
        and p.get("file_count") == expected.get("file_count") == len(rows)
        and len(ids) == len(set(ids)) and all(bool(file_id) for file_id in ids)
        and nested not in ids
        and all(r.get("folder_path") == "(project root)" for r in rows)
        and not p.get("truncated") and not p.get("time_truncated")
        and not p.get("folders_unreadable"))


def _root_file_ids(p):
    """Sorted immediate root file IDs for root path alias comparison."""
    return sorted(r.get("id") for r in (p.get("files") or []))


def _same_root_files(p):
    """A root alias must return the exact immediate-file identities already observed."""
    expected = _RECALL.get("data_root_files")
    actual = _root_file_ids(p)
    return _root_files(p) and _measured(
        "the root alias returns the same immediate file identities",
        {"expected_file_ids": expected, "actual_file_ids": actual},
        actual == expected)


def _folder_summary(path, folder_key, files, children):
    """A named folder summary matched to the act's minted folder ID and known membership."""
    def check(p):
        root = _RECALL.get("data_root_summary") or {}
        project, folder = p.get("project") or {}, p.get("folder") or {}
        expected_id = _RECALL.get(folder_key)
        return _measured(
            f"'{path}' identity and immediate counts are exact",
            {"exists": p.get("exists"), "project": project, "folder": folder,
             "expected_folder_id": expected_id,
             "immediate_file_count": p.get("immediate_file_count"),
             "immediate_child_folder_count": p.get("immediate_child_folder_count"),
             "unavailable_fields": p.get("unavailable_fields")},
            p.get("exists") is True and project.get("id") == root.get("project_id")
            and project.get("name") == PROJECT and folder.get("id") == expected_id
            and folder.get("name") == path.rsplit("/", 1)[-1] and folder.get("path") == path
            and folder.get("is_root") is False
            and p.get("immediate_file_count") == files
            and p.get("immediate_child_folder_count") == children
            and p.get("unavailable_fields") == [])
    return check


def _known_file_listing(path, file_path, recursive):
    """A file listing containing exactly the act's uploaded lineage at its known parent path."""
    def check(p):
        rows = p.get("files") or []
        expected_id = _RECALL.get("cloud_file")
        actual = [(r.get("id"), r.get("folder_path")) for r in rows]
        return _measured(
            f"'{path}' lists the uploaded file at '{file_path}'",
            {"folder": p.get("folder"), "recursive": p.get("recursive"),
             "expected_file_id": expected_id, "files": actual,
             "file_count": p.get("file_count"), "truncated": p.get("truncated"),
             "time_truncated": p.get("time_truncated"),
             "folders_unreadable": p.get("folders_unreadable")},
            p.get("folder") == path and p.get("recursive") is recursive
            and p.get("file_count") == 1 and actual == [(expected_id, file_path)]
            and not p.get("truncated") and not p.get("time_truncated")
            and not p.get("folders_unreadable"))
    return check


def _known_child_excluded(p, polls=_SETTLE_POLLS):
    """The parent folder's immediate listing, re-read until the moved file has left it (the cloud
    listing lags the move by seconds, measured), is empty while its known child holds the upload."""
    call = facade("call")
    for i in range(polls):
        if not (p.get("files") or []) or i == polls - 1:
            break
        time.sleep(_SETTLE_GAP_S)
        is_error, again = call("data_get", {"project": PROJECT, "folder": RUN_PATH,
                                            "recursive": False})
        if not is_error and isinstance(again, dict):
            p = again
    rows = p.get("files") or []
    return _measured(
        "the run folder excludes the file moved into its child",
        {"folder": p.get("folder"), "recursive": p.get("recursive"),
         "known_child_file": _RECALL.get("cloud_file"), "files": rows,
         "file_count": p.get("file_count"), "truncated": p.get("truncated"),
         "time_truncated": p.get("time_truncated"),
         "folders_unreadable": p.get("folders_unreadable")},
        p.get("folder") == RUN_PATH and p.get("recursive") is False
        and p.get("file_count") == 0 and rows == []
        and not p.get("truncated") and not p.get("time_truncated")
        and not p.get("folders_unreadable"))


def _files_gone(*names):
    """data_get(project, folder): none of the run's documents is left in the configured folder - the
    read-back standing apart from what the delete calls reported about themselves.

    This listing has THREE ways of not looking, not two: the size and time caps set 'truncated', and
    a folder whose enumeration RAISED is counted in 'folders_unreadable' (named in
    folders_unreadable_at) while 'truncated' stays false. A file of these names could be sitting in
    exactly that folder, so an unreadable one is a hole in the search space and not an absence."""
    def check(p):
        seen = [str(r.get("name")) for r in (p.get("files") or [])]
        left = [n for n in names if n in seen]
        return _measured(f"the configured folder no longer holds {list(names)}, and was fully read",
                         {"file_count": p.get("file_count"), "still_there": left,
                          "truncated": p.get("truncated"),
                          "time_truncated": p.get("time_truncated"),
                          "folders_unreadable": p.get("folders_unreadable"),
                          "folders_unreadable_at": p.get("folders_unreadable_at")},
                         not left and not p.get("truncated") and not p.get("time_truncated")
                         and not p.get("folders_unreadable"))
    return check


def _cloud_processing_read(p):
    """True when the save PUBLISHED what DataFile.isComplete read: the flag, whether this call saw
    it false first, and the seconds the bounded settle spent.

    The VALUES are published and never asserted - a save answers while the cloud is still working,
    so demanding true here would assert how fast someone's hub was on the day."""
    waited = p.get("cloud_processing_waited_seconds")
    complete = p.get("cloud_processing_complete")
    return ("cloud_processing_complete" in p
            and (isinstance(complete, bool) or complete is None)
            and isinstance(p.get("cloud_processing_was_incomplete"), bool)
            and _num(waited) and waited >= 0)


def _saved_as(name, folder):
    """doc_save_as: the document written into the configured folder under this name, with no name
    collision - a second file of one name is a fork this run could not then clean up by name - and
    the cloud-processing flag the save read off its own DataFile."""
    def check(p):
        return _measured(f"'{name}' saved into '{folder}'",
                         {"saved": p.get("saved"), "name": p.get("name"),
                          "destination_folder": p.get("destination_folder"),
                          "document_id": p.get("document_id"),
                          "auto_created_parents": p.get("auto_created_parents"),
                          "cloud_processing_complete": p.get("cloud_processing_complete"),
                          "cloud_processing_was_incomplete":
                              p.get("cloud_processing_was_incomplete"),
                          "cloud_processing_waited_seconds":
                              p.get("cloud_processing_waited_seconds"),
                          "name_collision": p.get("name_collision")},
                         p.get("saved") is True and p.get("name") == name
                         and p.get("destination_folder") == folder
                         and p.get("auto_created_parents") == []
                         and _cloud_processing_read(p)
                         and "name_collision" not in p)
    return check


def _document_is(name, saved=True):
    """doc_get: which document the session is actually on, and - for a saved one - the lineage URN
    it is addressed by from here on.

    The writes below act on the ACTIVE document, so this is the row that says which one that is. The
    URN is asserted rather than merely saved because doc_get reads it through a guarded getter: a
    read that raised publishes null, this row would still pass on the NAME, and every step after it
    would address None - the opens, the closes and the deletes alike, which is the teardown leaving
    real documents behind in the operator's hub."""
    def check(p):
        active = p.get("active") or {}
        urn = str(active.get("document_id") or "")
        return _measured(f"the active document is '{name}' (saved {saved})",
                         {"name": active.get("name"), "has_data_file": active.get("has_data_file"),
                          "document_id": active.get("document_id")},
                         active.get("name") == name and active.get("has_data_file") is saved
                         and (urn.startswith("urn:") if saved else True))
    return check


def _version_identity(value):
    if not isinstance(value, str) or not value.startswith("urn:"):
        return None
    for marker in ("dm.lineage:", "fs.file:vf."):
        if marker in value:
            return value.split(marker, 1)[1].split("?", 1)[0]
    return None


def _version_record(p):
    f, v, state = p.get("file") or {}, p.get("version") or {}, p.get("state") or {}
    return {"lineage": f.get("id"), "version_id": f.get("version_id"),
            "number": v.get("number"), "latest_number": v.get("latest_number"),
            "is_latest": v.get("is_latest"), "is_complete": state.get("is_complete")}


def _version_current(snap):
    number = snap.get("number")
    latest = snap.get("latest_number")
    return (isinstance(snap.get("lineage"), str) and snap["lineage"].startswith("urn:")
            and isinstance(snap.get("version_id"), str) and snap["version_id"]
            and snap["version_id"].startswith("urn:")
            and bool(_version_identity(snap["lineage"]))
            and _version_identity(snap["lineage"]) == _version_identity(snap["version_id"])
            and isinstance(number, int) and not isinstance(number, bool) and number > 0
            and isinstance(latest, int) and not isinstance(latest, bool) and latest == number
            and snap["version_id"].endswith(f"?version={number}")
            and snap.get("is_latest") is True and snap.get("is_complete") is True)


def _version_args(key, polls=_SETTLE_POLLS):
    def args(c):
        lineage = _ctx_get(c, "source_urn", "the source")
        _RECALL[f"{key}_expected_lineage"] = lineage
        for i in range(polls):
            is_error, payload = facade("call")("data_get", {"file": lineage})
            if not is_error and isinstance(payload, dict):
                snap = _version_record(payload)
                if snap["lineage"] != lineage:
                    raise AssertionError(f"Expected cloud lineage {lineage!r}, read {snap!r}")
                if _version_current(snap):
                    return {"file": lineage}
            if i < polls - 1:
                time.sleep(_SETTLE_GAP_S)
        raise AssertionError(f"Cloud baseline for {lineage!r} did not settle: {payload!r}")
    return args


def _version_snapshot(key):
    def check(p):
        snap = _version_record(p)
        valid = (_version_current(snap)
                 and snap["lineage"] == _RECALL.get(f"{key}_expected_lineage"))
        return _measured(f"fresh version baseline for '{key}'", snap, valid)
    return check


def _version_settled(key, polls=_SETTLE_POLLS):
    def check(p):
        before = _RECALL.get(key)
        expected = _RECALL.get(f"{key}_expected_lineage")
        valid_before = (isinstance(before, dict) and _version_current(before)
                        and before.get("lineage") == expected)
        if not valid_before:
            return _measured(f"fresh version baseline for '{key}' is usable", before, False)
        call = facade("call")
        for i in range(polls):
            now = _version_record(p)
            if now["lineage"] != before["lineage"]:
                break
            if _version_current(now) and now["number"] > before["number"]:
                break
            if i == polls - 1:
                break
            time.sleep(_SETTLE_GAP_S)
            is_error, again = call("data_get", {"file": before["lineage"]})
            if not is_error and isinstance(again, dict):
                p = again
        now = _version_record(p)
        return _measured(f"fresh version for '{key}' advanced from {before['number']}",
                         {"before": before, "after": now},
                         now["lineage"] == before["lineage"]
                         and _version_current(now) and now["number"] > before["number"])
    return check


def _versioned(name):
    def check(p):
        local = (p.get("saved") is True and p.get("document_name") == name
                 and p.get("local_save_confirmed") is True and not p.get("already_current"))
        tip = p.get("cloud_tip_advanced")
        consistent = not p.get("lineage_changed")
        if tip is not None:
            consistent = consistent and ((tip is True and p.get("version_confirmed") is True
                                          and p.get("pending") is not True)
                                         or (tip is False and p.get("version_confirmed") is False
                                             and p.get("pending") is True))
        cloud = consistent and p.get("version_confirmed") is True and p.get("pending") is not True
        pending = consistent and p.get("version_confirmed") is False and p.get("pending") is True
        return _measured(f"'{name}' saved locally; cloud version evidence follows",
                         {"saved": p.get("saved"), "document_name": p.get("document_name"),
                          "already_current": p.get("already_current"),
                          "local_save_confirmed": p.get("local_save_confirmed"),
                          "version_confirmed": p.get("version_confirmed"),
                          "pending": p.get("pending"), "cloud_tip_advanced": tip,
                          "cloud_processing_complete": p.get("cloud_processing_complete"),
                          "cloud_processing_was_incomplete":
                              p.get("cloud_processing_was_incomplete"),
                          "cloud_processing_waited_seconds":
                              p.get("cloud_processing_waited_seconds"),
                          "lineage_changed": p.get("lineage_changed"),
                          "description": p.get("description")},
                         local and (cloud or pending) and _cloud_processing_read(p))
    return check

def _plate_geometry(label, height=10.0):
    """model_inspect: measured plate extents and volume after the parameter change."""
    def check(p):
        mass = p.get("mass") or {}
        return _measured(f"{label} reads {80:g}x{50:g}x{height:g} mm",
                         {"x": p.get("x"), "y": p.get("y"), "z": p.get("z"),
                          "volume": mass.get("volume"), "kind": p.get("kind")},
                         p.get("kind") == "design"
                         and _near(p.get("x"), 80.0, 0.01)
                         and _near(p.get("y"), 50.0, 0.01)
                         and _near(p.get("z"), height, 0.01)
                         and _near(mass.get("volume"), 80.0 * 50.0 * height, 1.0))
    return check


def _milestone_args(ctx):
    """Clear prior milestone proof before building a new save request."""
    for key in ("milestone_history", "milestone_settled", "milestone_restored"):
        ctx.pop(key, None)
    for key in ("milestone_target", "milestone_settled", "milestone_restored"):
        _RECALL.pop(key, None)
    return {"milestone_name": "SweepCloudMilestone",
            "description": "the cloud tier's distinct 16 mm milestone"}


def _milestoned(milestone, name):
    """Record the exact version minted for a milestone save."""
    def check(p):
        lineage = _RECALL.get("source_urn")
        before = p.get("version_before")
        version = p.get("version_after")
        version_id = p.get("version_id_after")
        valid = (p.get("save_call_returned_true") is True
                 and p.get("milestone_name") == milestone
                 and p.get("document_name") == name
                 and p.get("document_id") == lineage
                 and isinstance(before, int) and not isinstance(before, bool) and before > 0
                 and isinstance(version, int) and not isinstance(version, bool) and version > before
                 and isinstance(version_id, str)
                 and _version_identity(version_id) == _version_identity(lineage)
                 and version_id.endswith(f"?version={version}")
                 and p.get("cloud_tip_advanced") is True
                 and "lineage_changed" not in p)
        if valid:
            _RECALL["milestone_target"] = {
                "milestone": milestone, "name": name, "lineage": lineage,
                "version": version, "version_id": version_id,
            }
        return _measured(f"'{milestone}' versioned '{name}' (the mark may still be pending)",
                         {"save_call_returned_true": p.get("save_call_returned_true"),
                          "milestone_name": p.get("milestone_name"),
                          "document_name": p.get("document_name"),
                          "latest_version_before": p.get("latest_version_before"),
                          "latest_version_after": p.get("latest_version_after"),
                          "cloud_tip_advanced": p.get("cloud_tip_advanced"),
                          "milestone_confirmed": p.get("milestone_confirmed"),
                          "pending": p.get("pending")},
                         valid)
    return check


def _milestone_restore_args(ctx, polls=_SETTLE_POLLS):
    """Wait for the exact saved version's named milestone before allowing its restore."""
    ctx.pop("milestone_settled", None)
    ctx.pop("milestone_restored", None)
    target = _RECALL.get("milestone_target")
    if not isinstance(target, dict) or target.get("lineage") != ctx.get("source_urn"):
        raise AssertionError(f"Exact milestone target is unavailable: {target!r}")
    payload = ctx.get("milestone_history")
    call = facade("call")
    for i in range(polls):
        active = (payload or {}).get("active") or {}
        versions = (payload or {}).get("versions") or {}
        rows = versions.get("versions") or []
        matches = [row for row in rows if row.get("version_number") == target["version"]]
        identity_ok = (active.get("name") == target["name"]
                       and active.get("document_id") == target["lineage"])
        history_ok = (versions.get("available") is True
                      and versions.get("history_readable") is True
                      and versions.get("history_complete") is True
                      and versions.get("milestone_names_readable") is True
                      and versions.get("milestone_walk_truncated") is False)
        confirmed = (identity_ok and history_ok and len(matches) == 1
                     and matches[0].get("version_id") == target["version_id"]
                     and matches[0].get("is_milestone") is True
                     and matches[0].get("milestone_name") == target["milestone"])
        if confirmed:
            ctx["milestone_settled"] = dict(target)
            selected = [r for r in rows if r.get("version_number") == RESTORE_VERSION]
            if len(selected) != 1 or not selected[0].get("version_id"):
                raise AssertionError("The restore version's exact id did not read")
            return {"version_number": RESTORE_VERSION, "version_id": selected[0]["version_id"],
                    "expect_document": active["document_handle"]}
        if payload is not None and not identity_ok:
            break
        if i < polls - 1:
            time.sleep(_SETTLE_GAP_S)
            is_error, again = call("doc_get", {"include": ["default", "versions"],
                                               "versions_max": 10})
            payload = again if not is_error and isinstance(again, dict) else None
    raise AssertionError(f"Exact milestone did not settle: target={target!r}, payload={payload!r}")


def _milestone_copy_args(ctx):
    """Build the source copy only after exact settlement and restore proof."""
    target = _RECALL.get("milestone_target")
    settled = ctx.get("milestone_settled")
    restored = ctx.get("milestone_restored")
    acted_on = restored.get("acted_on") if isinstance(restored, dict) else None
    if (not isinstance(target, dict) or target.get("lineage") != ctx.get("source_urn")
            or settled != target
            or not isinstance(restored, dict)
            or restored.get("restored") is not True
            or restored.get("restored_version") != RESTORE_VERSION
            or not isinstance(acted_on, dict)
            or acted_on.get("name") != target.get("name")
            or acted_on.get("document_id") != target.get("lineage")):
        raise AssertionError(f"Exact restore proof is unavailable: {restored!r}")
    return {"document_id": target["lineage"], "name": COPY_DOC,
            "project": PROJECT, "folder": FOLDER}


def _versions_read(least):
    """doc_get(include=['versions']): the lineage this act built, read off the cloud - available,
    enumerated, and holding at least `least` version ROWS, with version_count len() over the rows
    actually read so the two cannot disagree.

    What settles and what lags are DIFFERENT KEYS, measured apart. The rows arrive together with
    their count; the TIP NUMBER trails them - read latest_version_number 1 beside version_count 2
    and two rows read, on a run whose doc_save_milestone had already reported cloud_tip_advanced
    true. So the rows are what this asserts, and the tip and the milestone count are published as
    evidence and asserted nowhere: the milestone's own row proves the version it made, and repeating
    the claim here would only be asserting how fast the metadata caught up."""
    def check(p):
        v = p.get("versions") or {}
        rows = v.get("versions") or []
        return _measured(f"at least {least} version rows, the history readable",
                         {"available": v.get("available"),
                          "latest_version_number": v.get("latest_version_number"),
                          "version_count": v.get("version_count"),
                          "history_readable": v.get("history_readable"),
                          "milestone_count": v.get("milestone_count"),
                          "rows_read": len(rows)},
                         v.get("available") is True and v.get("history_readable") is True
                         and _num(v.get("version_count")) and v["version_count"] >= least
                         and len(rows) >= least
                         and v.get("version_count") == len(rows))
    return check


def _restored(version):
    """doc_restore_version: promote() returned true and the tool re-read the tip. 'restored' is that
    comparison - a NEW tip carrying the promoted content - and 'pending' is the tip not having moved
    within the wait, which is reported rather than called a failure."""
    def check(p):
        return _measured(f"version {version} promoted",
                         {"promote_call_returned_true": p.get("promote_call_returned_true"),
                          "restored": p.get("restored"),
                          "restored_version": p.get("restored_version"),
                          "latest_before": p.get("latest_before"),
                          "latest_after": p.get("latest_after"), "pending": p.get("pending")},
                         p.get("promote_call_returned_true") is True
                         and p.get("restored") is True
                         and p.get("restored_version") == version
                         and _num(p.get("latest_before"))
                         and _num(p.get("latest_after"))
                         and p["latest_after"] > p["latest_before"])
    return check


def _copied(source, name, folder):
    """doc_copy: the copy read back off the created DataFile - its own name and lineage URN, which is
    a DIFFERENT lineage from the source it was taken from."""
    def check(p):
        return _measured(f"'{source}' copied to '{name}' in '{folder}'",
                         {"copied": p.get("copied"), "source_document": p.get("source_document"),
                          "copied_name": p.get("copied_name"), "copied_id": p.get("copied_id"),
                          "source_id": p.get("source_id"),
                          "destination_folder": p.get("destination_folder"),
                          "rename_warning": p.get("rename_warning")},
                         p.get("copied") is True and p.get("source_document") == source
                         and p.get("copied_name") == name
                         and p.get("destination_folder") == folder
                         and str(p.get("copied_id") or "").startswith("urn:")
                         and p.get("copied_id") != p.get("source_id"))
    return check


def _inserted(name):
    """doc_insert_occurrence: the occurrence the host gained, and 'is_reference' - the flag saying it
    is an XREF onto the source's saved version rather than a copy of its geometry, which is what
    doc_update_xref then has something to walk."""
    def check(p):
        return _measured(f"'{name}' inserted as a reference",
                         {"inserted": p.get("inserted"), "document_name": p.get("document_name"),
                          "new_occurrence_name": p.get("new_occurrence_name"),
                          "is_reference": p.get("is_reference"),
                          "into_component": p.get("into_component")},
                         p.get("inserted") is True and p.get("document_name") == name
                         and bool(p.get("new_occurrence_name"))
                         and p.get("is_reference") is True)
    return check


def _xrefs(total, updated=None, skipped=None):
    """doc_update_xref(only_out_of_date=True): the host's reference census, with updated and skipped
    PARTITIONING it.

    The flag is what makes the partition measurable: under only_out_of_date=false nothing can land in
    'skipped' - every reference is refreshed whether or not it needed one - so a claim about the two
    buckets read off that call would be a claim about a branch the call cannot take.

    'updated'/'skipped' left None assert the partition and report which bucket the row landed in.
    That is the honest reading for the walk taken straight after an insert: MEASURED, a
    just-inserted occurrence xref came back was_out_of_date true, bound at version 2 while the
    source's stream had reached 3 - so which bucket it falls in depends on how far the cloud's
    version metadata has caught up, and is not this act's to fix in place."""
    def check(p):
        up, sk = p.get("updated"), p.get("skipped")
        want = (f"{updated} updated, {skipped} skipped" if updated is not None
                else "either bucket")
        return _measured(f"{total} reference(s) walked: {want}",
                         {"total_references": p.get("total_references"),
                          "updated_count": p.get("updated_count"),
                          "updated": up, "skipped": sk},
                         isinstance(up, list) and isinstance(sk, list)
                         and p.get("updated_count") == len(up)
                         and p.get("total_references") == total
                         and len(up) + len(sk) == total
                         and (updated is None or len(up) == updated)
                         and (skipped is None or len(sk) == skipped))
    return check


def _opened(name, lineage):
    """doc_open: the requested document resolved and its activation attribution is coherent."""
    def check(p):
        expected_name = name() if callable(name) else name
        expected_lineage = lineage() if callable(lineage) else lineage
        active, acted_on = p.get("is_active"), p.get("acted_on")
        handle = p.get("document_handle")
        confirmed = (active is True and isinstance(acted_on, dict)
                     and acted_on.get("name") == expected_name
                     and acted_on.get("document_id") == expected_lineage
                     and acted_on.get("document_handle") == handle)
        pending = (active is False or active is None) and acted_on is None
        return _measured(f"'{expected_name}' opened",
                         {"opened": p.get("opened"), "document_name": p.get("document_name"),
                          "is_active": p.get("is_active"), "open_method": p.get("open_method"),
                          "resolved_id": p.get("resolved_id"), "document_handle": handle,
                          "acted_on": acted_on},
                         p.get("opened") is True
                         and p.get("document_name") == expected_name
                         and isinstance(expected_lineage, str)
                         and p.get("resolved_id") == expected_lineage
                         and isinstance(handle, str) and handle.startswith("session:")
                         and "is_active" in p and (type(active) is bool or active is None)
                         and "acted_on" in p and (confirmed or pending))
    return check


def _drawing_created(p):
    """drawing_create: the CLOUD drawing file the generator wrote - its own name off the DataFile and
    a lineage URN, which is the identity it is addressed by (Fusion auto-names every drawing from its
    source design, so two drawings of one design share a name)."""
    return _measured("a drawing file was created",
                     {"created": p.get("created"), "drawing_name": p.get("drawing_name"),
                      "file_id": p.get("file_id"), "file_extension": p.get("file_extension")},
                     p.get("created") is True and bool(p.get("drawing_name"))
                     and str(p.get("file_id") or "").startswith("urn:"))


def _drawing_tables_answer(p):
    """drawing_get(include=['tables']) (FSAE-0922-DRAWING-PARTS-LIST-READ-1): adsk.drawing has no
    parts-list/balloon class, so each sheet's 'tables' answers a LIST (customTables, empty on a
    plain sheet) and the note names the parts-list/balloon/dimension gap rather than a count."""
    sheets = p.get("sheets")
    sheets = sheets if isinstance(sheets, list) else []
    rows = [s.get("tables") for s in sheets if isinstance(s, dict)]
    note = p.get("note") or ""
    return _measured("include=['tables'] answers a list per sheet, the parts-list gap named",
                     {"sheet_count": p.get("sheet_count"),
                      "tables_per_sheet": [len(r) if isinstance(r, list) else r for r in rows],
                      "note": note[:NOTE_MAX]},
                     bool(sheets) and len(rows) == len(sheets)
                     and all(isinstance(r, list) for r in rows)
                     and "parts list" in note and "balloon" in note)


def _sheets_answer(p):
    """drawing_get: a complete native sheet collection with one coherent active-sheet row."""
    sheet_count = p.get("sheet_count")
    source = p.get("sheets")
    sheets = source if isinstance(source, list) else []
    readable = all(isinstance(s, dict) for s in sheets)
    names = [s.get("name") for s in sheets if isinstance(s, dict)]
    collection_indices = [s.get("collection_index") for s in sheets if isinstance(s, dict)]
    export_indices = [s.get("export_index") for s in sheets if isinstance(s, dict)]
    active_rows = [s for s in sheets
                   if isinstance(s, dict) and s.get("is_active") is True]
    active_name = p.get("active_sheet")
    return _measured("the drawing answers with a complete sheet collection and one active sheet",
                     {"sheet_count": sheet_count,
                      "collection_index": collection_indices,
                      "export_index": export_indices,
                      "active_sheet": active_name,
                      "active": [s.get("name") for s in active_rows]},
                     isinstance(sheet_count, int) and not isinstance(sheet_count, bool)
                     and sheet_count >= 1 and readable and len(sheets) == sheet_count
                     and len(names) == sheet_count
                     and all(isinstance(name, str) and name for name in names)
                     and len(set(names)) == sheet_count
                     and collection_indices == list(range(1, sheet_count + 1))
                     and export_indices == [None] * sheet_count
                     and all(isinstance(s.get("is_active"), bool) for s in sheets)
                     and len(active_rows) == 1 and isinstance(active_name, str)
                     and active_name and active_rows[0].get("name") == active_name)


def _sheet_added(name):
    """drawing_edit_sheet(add): the new sheet named and ACTIVE, and the count read either side."""
    def check(p):
        return _measured(f"sheet '{name}' added and now active",
                         {"added": p.get("added"), "sheet": p.get("sheet"),
                          "sheet_count": p.get("sheet_count"),
                          "sheet_count_before": p.get("sheet_count_before"),
                          "active_sheet": p.get("active_sheet"),
                          "became_active": p.get("became_active")},
                         p.get("sheet") == name and _num(p.get("sheet_count_before"))
                         and p.get("sheet_count") == p["sheet_count_before"] + 1
                         and p.get("became_active") is True and p.get("active_sheet") == name)
    return check


def _exported(p):
    """drawing_export: the landed file identity and the DXF/DWG sheet-selection disclosure."""
    fmt = p.get("format")
    path = p.get("file_path")
    selection = p.get("sheet_selection_verified")
    return _measured("the exported drawing has bytes on disk",
                     {"exported": p.get("exported"), "file_exists": p.get("file_exists"),
                      "file_path": path, "size_bytes": p.get("size_bytes"), "format": fmt,
                      "sheet_selection_verified": selection},
                     p.get("exported") is True and p.get("file_exists") is True
                     and fmt in ("pdf", "dxf", "dwg") and isinstance(path, str)
                     and path.lower().endswith("." + fmt)
                     and _num(p.get("size_bytes")) and p["size_bytes"] > 0
                     # a DXF holds the active sheet, a verified fact; DWG selection is unverified.
                     and (fmt == "pdf" or selection is (fmt == "dxf")))


def _drawing_current(p):
    """drawing_update on a drawing generated moments ago: nothing to refresh, and it says so rather
    than reporting a refresh it did not do."""
    return _measured("the fresh drawing is already up to date",
                     {"updated": p.get("updated"), "is_up_to_date": p.get("is_up_to_date")},
                     p.get("updated") is False and p.get("is_up_to_date") is True)


def _auto_note_states_counts(p):
    """drawing_dimension auto: the note carries the two counts read and names no owning view."""
    before, after = p.get("dimension_count_before"), p.get("dimension_count_after")
    note = p.get("note") or ""
    return _measured("the auto note states the counts and claims no placement", note,
                     type(before) is int and type(after) is int
                     and note.startswith(f"The sheet's dimension count went from {before} to {after} "
                                         f"({after - before} added); they may sit on views projected "
                                         f"from view {p.get('view_index')}.")
                     and "may stop being drawn after an auto run" in note
                     and "Auto-dimensioned" not in note)


def _dimensioned(p):
    """drawing_dimension auto: the request returned true and the sheet's dimension count grew."""
    before, after = p.get("dimension_count_before"), p.get("dimension_count_after")
    return _measured("the auto-dimension request raised the sheet's dimension count",
                     {"dimensioned": p.get("dimensioned"),
                      "document_modified_before": p.get("document_modified_before"),
                      "document_modified": p.get("document_modified"),
                      "strategy": p.get("strategy"),
                      "dimension_count_before": before, "dimension_count_after": after},
                     p.get("dimensioned") is True and p.get("document_modified") is True
                     and type(before) is int and type(after) is int and after > before)


def _drawing_persistence_start(ctx):
    """Clear this act's old persistence captures before observing the source session."""
    prefixes = ("drawing_persist_", "drawing_two_", "drawing_populated_",
                "drawing_update_", "drawing_source_", "drawing_restore_", "drawing_final_")
    for values in (ctx, _RECALL):
        for key in list(values):
            if key.startswith(prefixes):
                values.pop(key)
    return {}


def _drawing_persistence_sheet_values(p):
    """Return only readable drawing and sheet fields, excluding transient modified/command state."""
    return {key: p.get(key) for key in ("drawing", "standard", "dimension_display_unit",
                                       "coordinate_unit", "sheet_count", "active_sheet", "sheets")}


def _drawing_sheet_facts(sheet):
    """Return readable sheet facts published by both copy and rich-read payloads."""
    return {key: sheet.get(key) for key in ("sheet_size", "orientation", "width", "height",
                                             "width_height_unit", "views", "sketches",
                                             "custom_tables")}


def _drawing_sheet_structure(sheet):
    """Return the readable sheet and view structure used by the named-sheet comparison."""
    view_count = sheet.get("views")
    rows = sheet.get("view_rows")
    if (type(view_count) is not int or view_count < 0 or not isinstance(rows, list)
            or len(rows) != view_count):
        raise AssertionError("the sheet view collection is incomplete")
    indices, types = [], []
    for row in rows:
        if not isinstance(row, dict):
            raise AssertionError("the sheet view collection contains a corrupt row")
        index, view_type = row.get("index"), row.get("type")
        if type(index) is not int or view_type not in ("base", "projected"):
            raise AssertionError("the sheet view collection contains an invalid identity")
        indices.append(index)
        types.append(view_type)
    if sorted(indices) != list(range(view_count)):
        raise AssertionError("the sheet view collection indices are not unique and complete")
    signature = {"indices": sorted(indices), "types": sorted(types)}
    return {**_drawing_sheet_facts(sheet), "view_rows": signature}


def _drawing_persistence_structure(p):
    """Return retained drawing facts, view order normalized, the placed-item counts left out."""
    values = _drawing_persistence_sheet_values(p)
    sheets = values.get("sheets")
    if not isinstance(sheets, list) or not all(isinstance(sheet, dict) for sheet in sheets):
        raise AssertionError("the retained drawing sheet collection is incomplete")
    normalized = [{**{k: v for k, v in sheet.items()
                      if k not in ("dimension_count", "symbol_count")},
                   "view_rows": _drawing_sheet_structure(sheet)["view_rows"]}
                  for sheet in sheets]
    return {**values, "sheets": normalized}


def _drawing_original_sheet(ctx=None):
    """Return the one original sheet captured before the named copy is made."""
    baseline = (ctx or _RECALL).get("drawing_persist_sheets") or {}
    rows = baseline.get("sheets") or []
    if len(rows) != 1 or not isinstance(rows[0].get("name"), str) or not rows[0]["name"]:
        raise AssertionError("the original drawing sheet identity is unavailable")
    return rows[0]


def _drawing_invalid_export_args(_ctx):
    """Start an out-of-range export against the one-sheet fixture."""
    if os.path.exists(_DRAWING_INVALID_PDF):
        raise AssertionError(f"Invalid-range export target already exists: {_DRAWING_INVALID_PDF!r}")
    return {"format": "pdf", "file_path": _DRAWING_INVALID_PDF, "sheet_range": "2",
            "deferred": True, "request_key": _DRAWING_INVALID_KEY}


def _drawing_invalid_export_started(p):
    """Require the deferred invalid-range job to publish one exact poll identity."""
    job = p.get("job_id")
    poll = p.get("poll") or {}
    return _measured("the one-sheet out-of-range export was accepted for terminal inspection",
                     {"accepted": p.get("accepted"), "request_key": p.get("request_key"),
                      "job_id": job, "status": p.get("status"), "poll": poll},
                     p.get("accepted") is True and p.get("status") == "accepted"
                     and p.get("request_key") == _DRAWING_INVALID_KEY
                     and isinstance(job, str) and bool(job)
                     and poll.get("tool") == "drawing_get_status"
                     and poll.get("request_key") == _DRAWING_INVALID_KEY)


def _drawing_invalid_status_args(ctx):
    """Poll the exact invalid-range job only after its identity was retained."""
    _ctx_get(ctx, "drawing_persist_invalid_job", "the invalid-range export job")
    return {"request_key": _DRAWING_INVALID_KEY}


def _drawing_invalid_export_failed(p, polls=_SETTLE_POLLS):
    """Bound status reads and require the native invalid-range terminal refusal."""
    call = facade("call")
    for i in range(polls):
        if isinstance(p, dict) and p.get("status") in ("completed", "failed"):
            break
        if i == polls - 1:
            break
        time.sleep(_SETTLE_GAP_S)
        failed, again = call("drawing_get_status", {"request_key": _DRAWING_INVALID_KEY})
        if failed:
            raise AssertionError(f"Invalid-range export status read failed: {again!r}")
        p = again
    job = _RECALL.get("drawing_persist_invalid_job")
    arguments = p.get("arguments") if isinstance(p, dict) else {}
    terminal = p.get("terminal_result") if isinstance(p, dict) else {}
    expected = {"expect_document": _RECALL.get("drawing_persist_opened"),
                "file_path": _DRAWING_INVALID_PDF, "format": "pdf", "sheet_range": "2"}
    return _measured("the exact invalid-range job failed with no output file",
                     {"job_id": p.get("job_id") if isinstance(p, dict) else None,
                      "request_key": p.get("request_key") if isinstance(p, dict) else None,
                      "status": p.get("status") if isinstance(p, dict) else None,
                      "arguments": arguments, "terminal_result": terminal,
                      "file_exists": os.path.exists(_DRAWING_INVALID_PDF)},
                     isinstance(p, dict) and p.get("job_id") == job
                     and p.get("request_key") == _DRAWING_INVALID_KEY
                     and p.get("tool") == "drawing_export" and p.get("status") == "failed"
                     and arguments == expected and terminal.get("isError") is True
                     and "Invalid range" in str(terminal.get("message") or "")
                     and not os.path.exists(_DRAWING_INVALID_PDF))


def _drawing_invalid_export_unchanged(p):
    """Require unchanged disclosed sheet content and continued output absence after refusal."""
    unchanged = _drawing_persistence_sheets(p, compare=True)
    return _measured("the refused range left disclosed sheet content unchanged and no output",
                     {"sheet_content": _drawing_persistence_sheet_values(p),
                      "file_exists": os.path.exists(_DRAWING_INVALID_PDF)},
                     unchanged and not os.path.exists(_DRAWING_INVALID_PDF))


def _drawing_copy_args(ctx):
    """Copy the exact original sheet to this run's distinct name."""
    return {"action": "copy", "sheet": _drawing_original_sheet(ctx)["name"],
            "new_name": _DRAWING_COPY_SHEET}


def _drawing_copy_verified(p):
    """Require the copy response to carry the original sheet's readable structure."""
    original = _drawing_original_sheet()
    facts = p.get("facts") or {}
    listing = p.get("sheets") or []
    return _measured("the original sheet was copied with matching readable structure",
                     {"copied": p.get("copied"), "sheet": p.get("sheet"),
                      "copied_from": p.get("copied_from"), "facts": facts,
                      "sheets": listing},
                     p.get("copied") is True and p.get("copied_from") == original["name"]
                     and p.get("sheet") == p.get("requested_name") == _DRAWING_COPY_SHEET
                     and p.get("sheet_count_before") == 1 and p.get("sheet_count") == 2
                     and facts.get("name") == _DRAWING_COPY_SHEET
                     and _drawing_sheet_facts(facts) == _drawing_sheet_facts(original)
                     and [row.get("name") for row in listing]
                     == [original["name"], _DRAWING_COPY_SHEET])


def _drawing_named_sheets(p):
    """Require the original and active copy to retain identical readable sheet structure."""
    _sheets_answer(p)
    original = _drawing_original_sheet()
    rows = p.get("sheets") or []
    by_name = {row.get("name"): row for row in rows}
    drawing = _RECALL.get("drawing") or [None, None]
    return _measured("the active copy and inactive original retain matching four-view structure",
                     _drawing_persistence_sheet_values(p),
                     p.get("drawing") == drawing[1]
                     and (p.get("active_document") or {}).get("document_id") == drawing[0]
                     and p.get("standard") == "iso"
                     and p.get("dimension_display_unit") == p.get("coordinate_unit") == "mm"
                     and [row.get("name") for row in rows]
                     == [original["name"], _DRAWING_COPY_SHEET]
                     and by_name[original["name"]].get("is_active") is False
                     and by_name[_DRAWING_COPY_SHEET].get("is_active") is True
                     and p.get("active_sheet") == _DRAWING_COPY_SHEET
                     and _drawing_sheet_structure(by_name[original["name"]])
                     == _drawing_sheet_structure(original)
                     and _drawing_sheet_structure(by_name[_DRAWING_COPY_SHEET])
                     == _drawing_sheet_structure(original))


def _drawing_overall_args(ctx, view):
    """Target one view on the captured original sheet while its copy is active."""
    return {"sheet": _drawing_original_sheet(ctx)["name"], "view": view,
            "strategy": "overall", "datum": "bottom_left"}


def _drawing_delete_copy_args(_ctx):
    """Delete this run's exact copied sheet once."""
    return {"action": "delete", "sheet": _DRAWING_COPY_SHEET}


def _drawing_copy_delete_requested(p):
    """Accept a verified delete or the native pending-deletion response."""
    pending = (p.get("deleted") is None and p.get("delete_accepted") is True
               and p.get("verification") == "pending")
    immediate = p.get("deleted") is True
    return _measured("the copied sheet deletion was accepted once",
                     {"deleted": p.get("deleted"), "delete_accepted": p.get("delete_accepted"),
                      "verification": p.get("verification"), "sheet": p.get("sheet"),
                      "sheet_count_before": p.get("sheet_count_before"),
                      "active_sheet_still_reads": p.get("active_sheet_still_reads")},
                     p.get("sheet") == _DRAWING_COPY_SHEET
                     and p.get("sheet_count_before") == 2 and (pending or immediate)
                     # the listing lags: the sheet just deleted can still read as the active one
                     and isinstance(p.get("active_sheet_still_reads"), str))


def _drawing_original_settled(p, polls=_SETTLE_POLLS):
    """Poll drawing reads until the exact original is the sole active sheet."""
    original = _drawing_original_sheet()
    drawing = _RECALL.get("drawing") or [None, None]
    call = facade("call")
    for i in range(polls):
        if not isinstance(p, dict):
            raise AssertionError(f"Sheet deletion read returned no object: {p!r}")
        rows = p.get("sheets") if isinstance(p.get("sheets"), list) else []
        names = [row.get("name") for row in rows if isinstance(row, dict)]
        original_rows = [row for row in rows if isinstance(row, dict)
                         and row.get("name") == original["name"]]
        identity_ok = (p.get("drawing") == drawing[1]
                       and (p.get("active_document") or {}).get("document_id") == drawing[0])
        if not identity_ok or len(original_rows) != 1:
            raise AssertionError(f"Original sheet identity was lost while deletion settled: {names!r}")
        if _drawing_sheet_structure(original_rows[0]) != _drawing_sheet_structure(original):
            raise AssertionError("the original sheet structure changed while deletion settled")
        if names == [original["name"]] and p.get("sheet_count") == 1:
            _sheets_answer(p)
            return _measured("the copied sheet is absent and the original is solely active",
                             _drawing_persistence_sheet_values(p),
                             p.get("active_sheet") == original["name"]
                             and original_rows[0].get("is_active") is True)
        if names != [original["name"], _DRAWING_COPY_SHEET] or p.get("sheet_count") != 2:
            raise AssertionError(f"Unexpected sheets while deletion settled: {names!r}")
        if i == polls - 1:
            break
        time.sleep(_SETTLE_GAP_S)
        failed, again = call("drawing_get", {"include": ["views"]})
        if failed:
            raise AssertionError(f"Sheet deletion status read failed: {again!r}")
        p = again
    raise AssertionError(f"Copied sheet still present after {polls} reads: {names!r}")


def _drawing_persisted_counts(sheet):
    """(read, expected) dimension/symbol counts: the last recalled add's, else the baseline's."""
    base = ((_RECALL.get("drawing_persist_sheets") or {}).get("sheets") or [{}])[0]
    want = {"dimension_count": _RECALL.get("drawing_persist_dims", base.get("dimension_count")),
            "symbol_count": _RECALL.get("drawing_persist_symbols", base.get("symbol_count"))}
    return {key: sheet.get(key) for key in want}, want


def _drawing_persistence_sheets(p, compare=False):
    """The plate's sheet/view identities; compare=True also holds them and both counts to recall."""
    _sheets_answer(p)
    rows = p.get("sheets") or []
    sheet = rows[0]
    drawing = _RECALL.get("drawing") or [None, None]
    counts, want = _drawing_persisted_counts(sheet)
    values = {**_drawing_persistence_sheet_values(p), "expected_counts": want}
    return _measured("the plate drawing's readable sheet and view identities", values,
                     bool(drawing[0]) and p.get("drawing") == drawing[1]
                     and (p.get("active_document") or {}).get("document_id") == drawing[0]
                     and p.get("standard") == "iso"
                     and p.get("dimension_display_unit") == p.get("coordinate_unit") == "mm"
                     and len(rows) == 1 and sheet.get("sheet_size") == "a3"
                     and sheet.get("orientation") == "landscape"
                     and sheet.get("width") == 420.0 and sheet.get("height") == 297.0
                     and sheet.get("width_height_unit") == "mm"
                     and sheet.get("views") == 4 and sheet.get("sketches") == 0
                     and sheet.get("custom_tables") == 0
                     and _drawing_sheet_structure(sheet)["view_rows"]
                     == {"indices": [0, 1, 2, 3],
                         "types": ["base", "projected", "projected", "projected"]}
                     and (not compare or (_drawing_persistence_structure(p)
                                          == _drawing_persistence_structure(
                                              _RECALL.get("drawing_persist_sheets") or {})
                                          and all(type(v) is int for v in want.values())
                                          and counts == want)))


def _drawing_overall_requested(view):
    """Verify the overall/bottom-left request attribution; PDF inspection verifies its placement."""
    def check(p):
        _dimensioned(p)
        original = _drawing_original_sheet()
        return _measured("overall dimension request accepted on the inactive original sheet",
                         {"view": p.get("view_index"), "sheet": p.get("sheet"),
                          "strategy": p.get("strategy"), "datum": p.get("datum")},
                         p.get("sheet") == original["name"]
                         and original["name"] != _DRAWING_COPY_SHEET
                         and p.get("view_index") == view and p.get("view_count") == 4
                         and p.get("strategy") == "overall" and p.get("datum") == "bottom_left")
    return check


def _drawing_base_view(ctx=None):
    """Return the original sheet's one base-view index from its captured view rows."""
    rows = _drawing_original_sheet(ctx).get("view_rows") or []
    bases = [row.get("index") for row in rows
             if isinstance(row, dict) and row.get("type") == "base"]
    if len(bases) != 1 or type(bases[0]) is not int:
        raise AssertionError(f"the original sheet carries no single base view: {bases!r}")
    return bases[0]


def _xy(point):
    """True for an [x, y] pair of real numbers."""
    return isinstance(point, list) and len(point) == 2 and all(_num(v) for v in point)


def _drawing_lines(curves):
    """The line rows of a curves slice whose two ends read."""
    return [c for c in curves or [] if isinstance(c, dict) and c.get("type") == "line"
            and _xy(c.get("start")) and _xy(c.get("end"))]


def _drawing_curves_args(ctx):
    """Read the original sheet's base view with its curve points."""
    return {"include": ["curves"], "sheet": _drawing_original_sheet(ctx)["name"],
            "view": _drawing_base_view(ctx)}


def _drawing_curves_listed(p):
    """drawing_get(include=['curves'], view=N): the base view lists lines with numeric ends."""
    rows = p.get("sheets") or []
    sheet = rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else {}
    views = sheet.get("view_rows") or []
    curves = (views[0].get("curves") if len(views) == 1 and isinstance(views[0], dict)
              else None)
    return _measured("the base view lists line curves with numeric ends in the sheet's unit",
                     {"sheet": sheet.get("name"), "curve_unit": sheet.get("curve_unit"),
                      "views": [(v.get("index"), v.get("type")) for v in views
                                if isinstance(v, dict)],
                      "curves": len(curves) if isinstance(curves, list) else curves,
                      "lines": len(_drawing_lines(curves)),
                      "dimension_count": sheet.get("dimension_count")},
                     sheet.get("name") == _drawing_original_sheet()["name"]
                     and sheet.get("curve_unit") == "mm"
                     and len(views) == 1 and views[0].get("index") == _drawing_base_view()
                     and views[0].get("type") == "base" and len(_drawing_lines(curves)) >= 1
                     and type(sheet.get("dimension_count")) is int)


def _drawing_curves_record(p):
    """Park the base view's curves, and the sheet's count the first manual add starts from."""
    sheet = p["sheets"][0]
    _RECALL["drawing_persist_dims"] = sheet["dimension_count"]
    _RECALL["drawing_persist_curves"] = sheet["view_rows"][0]["curves"]
    return _RECALL["drawing_persist_curves"]


def _drawing_linear_args(ctx):
    """A linear dimension across the base view's first horizontal line, 15 below its lowest point."""
    curves = _ctx_get(ctx, "drawing_persist_curves", "the base view's curves")
    flat = [c for c in _drawing_lines(curves)
            if abs(c["end"][0] - c["start"][0]) > abs(c["end"][1] - c["start"][1])]
    if not flat:
        raise AssertionError("the base view lists no horizontal line to dimension")
    line = flat[0]
    lowest = min(pt[1] for c in curves if isinstance(c, dict)
                 for pt in (c.get("start"), c.get("end"), c.get("mid"), c.get("center"))
                 if _xy(pt))
    return {"action": "linear", "sheet": _drawing_original_sheet(ctx)["name"],
            "view": _drawing_base_view(ctx), "from_point": f"{line['index']}:start",
            "to_point": f"{line['index']}:end",
            "placement": [(line["start"][0] + line["end"][0]) / 2, lowest - 15]}


def _drawing_corner(ctx):
    """(line a, line b, their shared corner, a's far-end key, b's far-end key, a's leg, b's leg)."""
    lines = _drawing_lines(_ctx_get(ctx, "drawing_persist_curves", "the base view's curves"))
    for a in lines:
        for b in lines:
            ends = [(ka, kb) for ka in ("start", "end") for kb in ("start", "end")
                    if abs(a[ka][0] - b[kb][0]) < 1e-3 and abs(a[ka][1] - b[kb][1]) < 1e-3]
            if a is b or len(ends) != 1:
                continue
            corner = a[ends[0][0]]
            far_a = "end" if ends[0][0] == "start" else "start"
            far_b = "end" if ends[0][1] == "start" else "start"
            u = (a[far_a][0] - corner[0], a[far_a][1] - corner[1])
            v = (b[far_b][0] - corner[0], b[far_b][1] - corner[1])
            if abs(u[0] * v[1] - u[1] * v[0]) > 1e-6:
                return a, b, corner, far_a, far_b, u, v
    raise AssertionError("no two base-view lines meet at a corner")


def _drawing_angular_args(ctx):
    """An angular dimension between two base-view lines meeting at a corner, placed inside it."""
    a, b, corner, _fa, _fb, u, v = _drawing_corner(ctx)
    return {"action": "angular", "sheet": _drawing_original_sheet(ctx)["name"],
            "view": _drawing_base_view(ctx), "curves": [a["index"], b["index"]],
            "placement": [corner[0] + 0.3 * (u[0] + v[0]), corner[1] + 0.3 * (u[1] + v[1])]}


def _drawing_aligned_args(ctx):
    """An aligned dimension across that corner's diagonal, between the two lines' far ends."""
    a, b, corner, far_a, far_b, u, v = _drawing_corner(ctx)
    return {"action": "aligned", "sheet": _drawing_original_sheet(ctx)["name"],
            "view": _drawing_base_view(ctx), "from_point": f"{a['index']}:{far_a}",
            "to_point": f"{b['index']}:{far_b}",
            "placement": [corner[0] + 0.75 * (u[0] + v[0]), corner[1] + 0.75 * (u[1] + v[1])]}


def _drawing_dimension_added(action):
    """drawing_dimension manual action: one more dimension, read as `action`, on the original."""
    def check(p):
        before, after = p.get("dimension_count_before"), p.get("dimension_count_after")
        return _measured(f"one {action} dimension raised the original sheet's count by one",
                         {key: p.get(key) for key in (
                             "dimensioned", "action", "sheet", "view_index",
                             "dimension_count_before", "dimension_count_after", "type_read",
                             "placement", "placement_unit")},
                         p.get("dimensioned") is True and p.get("action") == action
                         and p.get("type_read") == action
                         and p.get("sheet") == _drawing_original_sheet()["name"]
                         and p.get("view_index") == _drawing_base_view()
                         and type(before) is int and before == _RECALL.get("drawing_persist_dims")
                         and after == before + 1 and p.get("placement_unit") == "mm")
    return check


def _drawing_dimension_count_read(p):
    """drawing_get: the original sheet's own count equals the last manual add's after-count."""
    rows = p.get("sheets") or []
    sheet = rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else {}
    want = _RECALL.get("drawing_persist_dims")
    return _measured("drawing_get reads the count the last manual add reported",
                     {"sheet": sheet.get("name"), "dimension_count": sheet.get("dimension_count"),
                      "expected": want},
                     sheet.get("name") == _drawing_original_sheet()["name"]
                     and type(want) is int and sheet.get("dimension_count") == want)


def _toward(point, direction, distance):
    """`point` moved `distance` sheet units along `direction`, which need not be unit length."""
    length = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
    return [point[0] + distance * direction[0] / length, point[1] + distance * direction[1] / length]


def _drawing_symbol_args(action):
    """drawing_add_symbol args at the base view's corner, each leadered to a clear spot outside."""
    def build(ctx):
        a, b, corner, far_a, far_b, u, v = _drawing_corner(ctx)
        mid_a = [corner[0] + u[0] / 2, corner[1] + u[1] / 2]
        mid_b = [corner[0] + v[0] / 2, corner[1] + v[1] / 2]
        args = {"action": action, "sheet": _drawing_original_sheet(ctx)["name"],
                "view": _drawing_base_view(ctx)}
        if action == "datum_identifier":
            return {**args, "attach": f"{a['index']}:mid", "placement": _toward(mid_a, v, -35),
                    "identifier": "A"}
        if action == "feature_control_frame":
            bend = _toward(mid_b, u, -20)
            return {**args, "attach": f"{b['index']}:mid", "bends": [bend],
                    "placement": _toward(bend, v, 10), "frames": ["parallelism|0.1|A"]}
        if action == "edge":
            near_a = "start" if far_a == "end" else "end"
            return {**args, "attach": f"{a['index']}:{near_a}",
                    "placement": _toward(_toward(corner, u, -10), v, -10),
                    "upper_limit": "+0.5", "lower_limit": "-0.3"}
        return {**args, "attach": f"{b['index']}:{far_b}", "second_curve": a["index"],
                "placement": _toward(_toward(b[far_b], u, -15), v, 6), "dimension": "1:1"}
    return build


def _drawing_symbol_added(action):
    """drawing_add_symbol: one more symbol on the original, its returned object read as `action`."""
    def check(p):
        before, after = p.get("symbol_count_before"), p.get("symbol_count_after")
        return _measured(f"one {action} symbol raised the original sheet's symbol count by one",
                         {key: p.get(key) for key in (
                             "added", "action", "sheet", "view_index", "symbol_count_before",
                             "symbol_count_after", "type_read", "attach", "placement",
                             "placement_unit")},
                         p.get("added") is True and p.get("action") == action
                         and p.get("type_read") == action
                         and p.get("sheet") == _drawing_original_sheet()["name"]
                         and p.get("view_index") == _drawing_base_view()
                         and type(before) is int
                         and before == _RECALL.get("drawing_persist_symbols")
                         and after == before + 1 and p.get("placement_unit") == "mm")
    return check


def _drawing_symbol_count_read(p):
    """drawing_get: the original sheet's symbol_count equals the last symbol add's after-count."""
    rows = p.get("sheets") or []
    sheet = rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else {}
    want = _RECALL.get("drawing_persist_symbols")
    return _measured("drawing_get reads the symbol count the last add reported",
                     {"sheet": sheet.get("name"), "symbol_count": sheet.get("symbol_count"),
                      "expected": want},
                     sheet.get("name") == _drawing_original_sheet()["name"]
                     and type(want) is int and sheet.get("symbol_count") == want)


def _drawing_revision_args(action, **extra):
    """drawing_edit_revisions args on the original sheet, action plus its own extra fields."""
    def build(ctx):
        return {"action": action, "sheet": _drawing_original_sheet(ctx)["name"], **extra}
    return build


_REVISION_UPDATE_TEXT = "SLOT WIDENED - CONFIRMED"


def _drawing_revisions_added(p):
    """drawing_edit_revisions(add): a fresh table with title/header, row 2 reading A, row 3 B."""
    rows = p.get("rows") or []
    row2 = rows[2] if len(rows) > 2 else {}
    row3 = rows[3] if len(rows) > 3 else {}
    return _measured("a fresh table with title/header, row 2 reading A and row 3 reading B",
                     {"table_created": p.get("table_created"),
                      "revision_count_after": p.get("revision_count_after"),
                      "row2": row2, "row3": row3},
                     p.get("table_created") is True and p.get("revision_count_after") == 4
                     and row2.get("rev") == "A" and row3.get("rev") == "B")


def _drawing_revision_updated(p):
    """drawing_edit_revisions(update): row 3's description updates, its date stays unsent-unchanged."""
    rows = p.get("rows") or []
    row3 = rows[3] if len(rows) > 3 else {}
    return _measured("row 3's description updated with its original date left alone",
                     {"description": row3.get("description"), "date": row3.get("date")},
                     row3.get("description") == _REVISION_UPDATE_TEXT
                     and row3.get("date") == "27 Sep 2026"
                     and row3.get("approved") == "PM" and row3.get("zone") == "C3")


def _drawing_revision_census(p):
    """Read complete original-sheet revision and view rows for an independent update check."""
    sheets = p.get("sheets") or []
    sheet = sheets[0] if len(sheets) == 1 else {}
    rows, views = sheet.get("revisions"), sheet.get("view_rows")
    if (sheet.get("name") != _drawing_original_sheet()["name"]
            or not isinstance(rows, list) or len(rows) != 4 or sheet.get("revision_count") != 4
            or any(not isinstance(row.get(field), str) for row in rows
                   for field in ("rev", "description", "date", "approved", "zone", "sht"))
            or any(not isinstance(row.get("visible"), bool) for row in rows)
            or not isinstance(views, list) or len(views) != sheet.get("views")
            or any(type(row.get("index")) is not int or not isinstance(row.get("type"), str) for row in views)
            or sheet.get("view_rows_truncated")):
        raise AssertionError("revision/view census was unreadable or incomplete")
    return {"revisions": rows, "views": views}


def _drawing_revision_read(updated=False):
    """Compare independent rows with the unchanged census or the one requested description edit."""
    def check(p):
        before = _RECALL["drawing_revision_before"]
        expected = {**before, "revisions": [dict(row) for row in before["revisions"]]}
        if updated:
            expected["revisions"][3]["description"] = _REVISION_UPDATE_TEXT
        return _measured("revision update preserves sibling cells, rows and views", p.get("sheets"),
                         _drawing_revision_census(p) == expected)
    return check


def _drawing_revision_hidden(p):
    """drawing_edit_revisions(hide): the visible count drops by one and row 2 reads hidden."""
    rows = p.get("rows") or []
    row2 = rows[2] if len(rows) > 2 else {}
    return _measured("row 2 hidden and the visible count dropped to 3",
                     {"visible_count": p.get("visible_count"), "row2_visible": row2.get("visible")},
                     p.get("visible_count") == 3 and row2.get("visible") is False)


def _drawing_revision_shown(p):
    """drawing_edit_revisions(show): row 2 is visible again and the visible count is restored."""
    rows = p.get("rows") or []
    row2 = rows[2] if len(rows) > 2 else {}
    return _measured("row 2 shown again and the visible count restored to 4",
                     {"visible_count": p.get("visible_count"), "row2_visible": row2.get("visible")},
                     p.get("visible_count") == 4 and row2.get("visible") is True)


def _drawing_revision_deleted(p):
    """drawing_edit_revisions(delete): the census shrank to 3 rows and row 2 now reads B."""
    rows = p.get("rows") or []
    row2 = rows[2] if len(rows) > 2 else {}
    return _measured("the census shrank to 3 rows and row 2 now reads B",
                     {"revision_count_after": p.get("revision_count_after"), "row2": row2},
                     p.get("revision_count_after") == 3 and row2.get("rev") == "B")


def _drawing_revision_count_read(p):
    """drawing_get(include=['revisions']): the original sheet's revision_count reads 3."""
    rows = p.get("sheets") or []
    sheet = rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else {}
    return _measured("drawing_get reads the revision count the last edit left",
                     {"sheet": sheet.get("name"), "revision_count": sheet.get("revision_count")},
                     sheet.get("name") == _drawing_original_sheet()["name"]
                     and sheet.get("revision_count") == 3)


def _drawing_persistence_version_current(snap):
    """Require canonical, distinct lineage and exact-version identity roles."""
    lineage, version_id = snap.get("lineage"), snap.get("version_id")
    number = snap.get("number")
    return (_version_current(snap)
            and lineage.startswith("urn:adsk.wipprod:dm.lineage:") and "?" not in lineage
            and version_id.startswith("urn:adsk.wipprod:fs.file:vf.")
            and version_id.count("?") == 1
            and version_id.split("?", 1)[1] == f"version={number}")


def _drawing_persistence_version_snapshot(key):
    """Verify one captured drawing version has canonical identity roles."""
    def check(p):
        snap = _version_record(p)
        return _measured(f"fresh version baseline for '{key}'", snap,
                         _drawing_persistence_version_current(snap)
                         and snap["lineage"] == _RECALL.get(f"{key}_expected_lineage"))
    return check


def _drawing_persistence_document(handle_key, version=False, clean=False,
                                  version_key="drawing_persist_saved"):
    """Verify the active drawing's exact session, lineage and optionally its saved version."""
    def check(p):
        _home_document(p)
        drawing = _RECALL.get("drawing") or [None, None]
        active = p.get("active") or {}
        saved = _RECALL.get(version_key) or {}
        return _measured("the exact drawing document reads back", active,
                         bool(drawing[0]) and _document_is(drawing[1])(p)
                         and active.get("document_id") == drawing[0]
                         and bool(_RECALL.get(handle_key))
                         and active.get("document_handle") == _RECALL[handle_key]
                         and (not version or (_drawing_persistence_version_current(saved)
                              and saved["lineage"] == drawing[0]
                              and active.get("version_id") == saved.get("version_id")
                              and active.get("version_number") == saved.get("number")))
                         and (not clean or (active.get("is_saved") is True
                                            and active.get("is_modified") is False)))
    return check


def _drawing_persistence_version(p, unchanged=False,
                                 before_key="drawing_persist_save_before",
                                 saved_key="drawing_persist_saved"):
    """Verify a fresh drawing version advanced after save and remains exact after reopen."""
    if _RECALL.get(f"{saved_key}_expected_lineage"):
        _drawing_persistence_version_snapshot(saved_key)(p)
    drawing = _RECALL.get("drawing") or [None, None]
    before = _RECALL.get(before_key) or {}
    snap = _version_record(p)
    return _measured("the drawing's fresh saved version", snap,
                     _drawing_persistence_version_current(before)
                     and _drawing_persistence_version_current(snap)
                     and snap["lineage"] == drawing[0] == before["lineage"]
                     and (p.get("file") or {}).get("name") == drawing[1]
                     and (p.get("file") or {}).get("file_extension") == "f2d"
                     and snap["number"] > before["number"]
                     and (not unchanged or snap == _RECALL.get(saved_key)))


def _drawing_dirtied_by_read(p):
    """drawing_get on the clean reopened drawing: the read reports the false-to-true isModified flip."""
    return _measured("the read reports leaving the reopened drawing modified",
                     {k: p.get(k) for k in ("is_modified", "modified_by_read", "sheet_count")},
                     p.get("is_modified") is False and p.get("modified_by_read") is True
                     and p.get("sheet_count") == 2
                     and "read false before this read and true after it" in str(p.get("note")))


def _drawing_persistence_absent(p, handle_key="drawing_persist_opened",
                                active_key="drawing_persist_source", active_name=SOURCE_DOC):
    """Require one closed drawing handle absent from a complete document census."""
    _home_document(p)
    rows = p.get("open_documents", [])
    handles = [row.get("document_handle") for row in rows]
    active = p.get("active") or {}
    closed = _RECALL.get(handle_key)
    valid = (bool(closed) and closed not in handles and p.get("truncated") is False
             and p.get("open_count") == len(handles)
             and all(isinstance(h, str) and h.startswith("session:")
                     and len(h) > len("session:") and not any(c.isspace() for c in h)
                     for h in handles)
             and handles.count(_RECALL.get(active_key)) == 1
             and active.get("document_handle") == _RECALL.get(active_key))
    if active_name:
        names = [row.get("name") for row in rows if isinstance(row, dict)]
        valid = valid and names.count(active_name) == 1 and _document_is(active_name)(p)
    return _measured("the closed drawing session is absent from the complete document census",
                     {"closed": closed, "handles": handles, "active": active}, valid)


def _drawing_persistence_reopened(p=None, version_key="drawing_persist_saved",
                                  prior_handle_key="drawing_persist_opened"):
    """Separate the requested version URN from the active drawing's lineage attribution."""
    if p is None:
        return lambda payload: _drawing_persistence_reopened(
            payload, version_key=version_key, prior_handle_key=prior_handle_key)
    saved = _RECALL.get(version_key) or {}
    drawing = _RECALL.get("drawing") or [None, None]
    handle, active, acted = p.get("document_handle"), p.get("is_active"), p.get("acted_on")
    confirmed = (active is True and isinstance(acted, dict) and acted.get("name") == drawing[1]
                 and acted.get("document_id") == drawing[0] and acted.get("document_handle") == handle)
    pending = "is_active" in p and (active is False or active is None) and "acted_on" in p and acted is None
    return _measured("the exact drawing version reopened with a fresh session handle", p,
                     _drawing_persistence_version_current(saved) and p.get("opened") is True
                     and p.get("resolved_id") == saved["version_id"]
                     and p.get("document_name") == drawing[1]
                     and isinstance(handle, str) and handle.startswith("session:")
                     and len(handle) > len("session:") and not any(c.isspace() for c in handle)
                     and bool(_RECALL.get(prior_handle_key))
                     and handle != _RECALL[prior_handle_key] and (confirmed or pending))


def _drawing_persistence_pdf_args(path):
    """Export all sheets with identical options to a fresh owned PDF destination."""
    def args(_ctx):
        if os.path.exists(path):
            raise AssertionError(f"Persistence export target already exists: {path!r}")
        return {"format": "pdf", "file_path": path, "line_weights": True}
    return args


def _drawing_pdf_record(p):
    """Return retained PDF bytes and the native drawing identity that produced them."""
    facts = _disk_facts(p.get("file_path")) or {}
    acted = p.get("acted_on") or {}
    return {**facts, "sheet_range": p.get("sheet_range"),
            "native_identity": {"name": acted.get("name"),
                                "document_id": acted.get("document_id")}}


def _drawing_persistence_pdf(path):
    """Retain an exact PDF artifact identity while leaving page comparison to acceptance."""
    def check(p):
        _exported(p)
        facts = _drawing_pdf_record(p)
        drawing = _RECALL.get("drawing") or [None, None]
        return _measured("PDF artifact retained; page content needs independent inspection", facts,
                         p.get("format") == "pdf" and p.get("sheet_range") == "all"
                         and p.get("line_weights") is True
                         and isinstance(p.get("file_path"), str)
                         and os.path.abspath(p["file_path"]) == os.path.abspath(path)
                         and facts is not None and facts["size_bytes"] == p.get("size_bytes")
                         and facts["size_bytes"] > 0
                         and bool(drawing[0]) and (p.get("acted_on") or {}).get("document_id") == drawing[0]
                         and (p.get("acted_on") or {}).get("name") == drawing[1])
    return check



def _drawing_set_a2_args(_ctx):
    """Resize the run-named copy whose creation just read back."""
    return {"action": "set_size", "sheet": _DRAWING_COPY_SHEET, "sheet_size": "a2"}


def _drawing_set_a2(p):
    """Require the named copy to change from A3 to exact A2 landscape extents."""
    return _measured("the named copy reads back as A2 landscape",
                     {key: p.get(key) for key in ("sheet", "sheet_size", "previous_sheet_size",
                                                   "width", "height", "previous_width",
                                                   "previous_height", "width_height_unit")},
                     p.get("sheet") == _DRAWING_COPY_SHEET
                     and p.get("sheet_size") == "a2" and p.get("previous_sheet_size") == "a3"
                     and p.get("width") == 594.0 and p.get("height") == 420.0
                     and p.get("previous_width") == 420.0 and p.get("previous_height") == 297.0
                     and p.get("width_height_unit") == "mm"
                     and (p.get("acted_on") or {}).get("document_id")
                     == (_RECALL.get("drawing") or [None])[0])


def _drawing_two_sheets(p, compare=False):
    """Require the saved A3 original and active A2 copy with four zero-sketch views each."""
    _sheets_answer(p)
    original = _drawing_original_sheet()
    expected_copy = {**_drawing_sheet_structure(original), "sheet_size": "a2",
                     "width": 594.0, "height": 420.0}
    rows = p.get("sheets") or []
    by_name = {row.get("name"): row for row in rows}
    drawing = _RECALL.get("drawing") or [None, None]
    values = _drawing_persistence_sheet_values(p)
    valid = (p.get("drawing") == drawing[1]
             and (p.get("active_document") or {}).get("document_id") == drawing[0]
             and p.get("standard") == "iso"
             and p.get("dimension_display_unit") == p.get("coordinate_unit") == "mm"
             and [row.get("name") for row in rows]
             == [original["name"], _DRAWING_COPY_SHEET]
             and by_name.get(original["name"], {}).get("is_active") is False
             and by_name.get(_DRAWING_COPY_SHEET, {}).get("is_active") is True
             and p.get("active_sheet") == _DRAWING_COPY_SHEET
             and _drawing_sheet_structure(by_name.get(original["name"], {}))
             == _drawing_sheet_structure(original)
             and _drawing_sheet_structure(by_name.get(_DRAWING_COPY_SHEET, {})) == expected_copy)
    return _measured("the A3 original and A2 copy retain their full readable structure", values,
                     valid and (not compare or _drawing_persistence_structure(p)
                                == _drawing_persistence_structure(
                                    _RECALL.get("drawing_two_sheets") or {})))


def _drawing_deferred_export_args(path, request_key, handle_key):
    """Build one guarded deferred PDF request with a fresh owned destination."""
    def args(ctx):
        if os.path.exists(path):
            raise AssertionError(f"Deferred export target already exists: {path!r}")
        return {"format": "pdf", "file_path": path, "deferred": True,
                "request_key": request_key,
                "expect_document": _ctx_get(ctx, handle_key, "the drawing session")}
    return args


def _drawing_deferred_update_args(request_key, handle_key):
    """Build one guarded deferred update request for the exact drawing session."""
    def args(ctx):
        return {"deferred": True, "request_key": request_key,
                "expect_document": _ctx_get(ctx, handle_key, "the drawing session")}
    return args


def _drawing_job_started(request_key):
    """Require a deferred drawing operation to return one exact poll identity."""
    def check(p):
        poll, job = p.get("poll") or {}, p.get("job_id")
        return _measured("the deferred drawing operation returned one poll identity",
                         {"accepted": p.get("accepted"), "request_key": p.get("request_key"),
                          "job_id": job, "status": p.get("status"), "poll": poll},
                         p.get("accepted") is True and p.get("status") == "accepted"
                         and p.get("request_key") == request_key
                         and isinstance(job, str) and bool(job)
                         and poll.get("tool") == "drawing_get_status"
                         and poll.get("request_key") == request_key)
    return check


def _drawing_status_args(ctx, job_key, request_key):
    """Poll only after the accepted job identity is retained."""
    _ctx_get(ctx, job_key, "the deferred drawing job")
    return {"request_key": request_key}


def _drawing_terminal_payload(status):
    """Return the JSON payload nested in a successful deferred terminal result."""
    terminal = status.get("terminal_result") if isinstance(status, dict) else None
    content = terminal.get("content") if isinstance(terminal, dict) else None
    if not isinstance(terminal, dict) or terminal.get("isError") is not False:
        return None
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        return None
    try:
        payload = json.loads(content[0].get("text", ""))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _drawing_terminal(status, job_key, request_key, tool, expected_arguments, polls=_SETTLE_POLLS):
    """Wait boundedly for the exact accepted job and return its successful payload."""
    call = facade("call")
    for i in range(polls):
        if isinstance(status, dict) and status.get("status") in ("completed", "failed"):
            break
        if i == polls - 1:
            break
        time.sleep(_SETTLE_GAP_S)
        failed, again = call("drawing_get_status", {"request_key": request_key})
        if failed:
            raise AssertionError(f"Drawing job status read failed: {again!r}")
        status.clear()
        status.update(again)
    if (not isinstance(status, dict) or status.get("job_id") != _RECALL.get(job_key)
            or status.get("request_key") != request_key or status.get("tool") != tool
            or status.get("arguments") != expected_arguments or status.get("status") != "completed"):
        return None
    return _drawing_terminal_payload(status)


def _drawing_deferred_pdf_completed(job_key, request_key, handle_key, path):
    """Require one exact PDF job, its terminal export payload and landed bytes."""
    def check(p):
        expected = {"expect_document": _RECALL.get(handle_key),
                    "file_path": path, "format": "pdf"}
        payload = _drawing_terminal(p, job_key, request_key, "drawing_export", expected)
        facts = _drawing_pdf_record(payload or {})
        drawing = _RECALL.get("drawing") or [None, None]
        valid = (isinstance(payload, dict) and payload.get("exported") is True
                 and payload.get("format") == "pdf" and payload.get("sheet_range") == "all"
                 and payload.get("line_weights") is True and payload.get("file_exists") is True
                 and os.path.abspath(str(payload.get("file_path") or "")) == os.path.abspath(path)
                 and facts.get("size_bytes") == payload.get("size_bytes")
                 and _num(facts.get("size_bytes")) and facts["size_bytes"] > 0
                 and facts.get("native_identity")
                 == {"name": drawing[1], "document_id": drawing[0]})
        return _measured("the exact deferred PDF job completed and retained its bytes", facts, valid)
    return check


def _drawing_deferred_pdf_record(p):
    """Return retained PDF facts from a completed deferred status payload."""
    return _drawing_pdf_record(_drawing_terminal_payload(p) or {})


def _drawing_circle_landed(p):
    """Require one circle on the active A2 source sheet without claiming its coordinates."""
    drawing = _RECALL.get("drawing") or [None, None]
    return _measured("one circle landed on the active A2 copy; coordinates remain unverified",
                     {key: p.get(key) for key in ("created", "sketch_name", "sheet_name",
                                                   "entities_drawn", "curves_requested",
                                                   "curves_landed", "landed",
                                                   "coordinates_verified")},
                     p.get("created") is True and p.get("sketch_name") == _DRAWING_POPULATED_SKETCH
                     and p.get("sheet_name") == _DRAWING_COPY_SHEET
                     and p.get("entities_drawn") == p.get("curves_requested") == p.get("curves_landed") == 1
                     and p.get("landed") == {"lines": 0, "rectangles": 0, "arcs": 0,
                                              "circles": 1, "ellipses": 0}
                     and p.get("coordinates_verified") is False
                     and (p.get("acted_on") or {}).get("document_id") == drawing[0])


def _drawing_populated_source(p):
    """Require independent zero/one sketch counts before copying the populated A2 sheet."""
    _sheets_answer(p)
    baseline = _RECALL.get("drawing_two_sheets") or {}
    rows, expected = p.get("sheets") or [], baseline.get("sheets") or []
    drawing = _RECALL.get("drawing") or [None, None]
    valid = (len(rows) == len(expected) == 2
             and p.get("drawing") == drawing[1]
             and (p.get("active_document") or {}).get("document_id") == drawing[0]
             and p.get("standard") == "iso"
             and p.get("dimension_display_unit") == p.get("coordinate_unit") == "mm")
    for index in range(min(len(rows), len(expected))):
        expected_structure = _drawing_sheet_structure(expected[index])
        expected_structure["sketches"] = index
        valid = valid and _drawing_sheet_structure(rows[index]) == expected_structure
    return _measured("the A3/A2 sheets independently read zero and one sketches",
                     _drawing_persistence_sheet_values(p),
                     valid and p.get("active_sheet") == _DRAWING_COPY_SHEET)


def _drawing_populated_copy_args(_ctx):
    """Copy the exact populated A2 source sheet to this run's third name."""
    return {"action": "copy", "sheet": _DRAWING_COPY_SHEET,
            "new_name": _DRAWING_POPULATED_SHEET}


def _drawing_populated_copy(p):
    """Require the third sheet's response facts to match the populated A2 source."""
    baseline = _RECALL.get("drawing_two_sheets") or {}
    source = (baseline.get("sheets") or [{}, {}])[1]
    expected = _drawing_sheet_facts(source)
    expected["sketches"] = 1
    listing = p.get("sheets") or []
    return _measured("the populated A2 source was copied to the exact third sheet",
                     {"copied": p.get("copied"), "sheet": p.get("sheet"),
                      "copied_from": p.get("copied_from"), "facts": p.get("facts"),
                      "sheets": listing},
                     p.get("copied") is True and p.get("copied_from") == _DRAWING_COPY_SHEET
                     and p.get("sheet") == p.get("requested_name") == _DRAWING_POPULATED_SHEET
                     and p.get("sheet_count_before") == 2 and p.get("sheet_count") == 3
                     and _drawing_sheet_facts(p.get("facts") or {}) == expected
                     and (p.get("acted_on") or {}).get("document_id")
                     == (_RECALL.get("drawing") or [None])[0]
                     and [row.get("name") for row in listing]
                     == [_drawing_original_sheet()["name"], _DRAWING_COPY_SHEET,
                         _DRAWING_POPULATED_SHEET])


def _drawing_populated_sheets(p, compare=False):
    """Require A3/A2/A2 structure with independent zero/one/one sketch counts."""
    _sheets_answer(p)
    baseline = _RECALL.get("drawing_two_sheets") or {}
    expected_two = baseline.get("sheets") or []
    rows = p.get("sheets") or []
    drawing = _RECALL.get("drawing") or [None, None]
    valid = (len(rows) == 3 and len(expected_two) == 2
             and p.get("drawing") == drawing[1]
             and (p.get("active_document") or {}).get("document_id") == drawing[0]
             and p.get("standard") == "iso"
             and p.get("dimension_display_unit") == p.get("coordinate_unit") == "mm")
    if valid:
        expected = [_drawing_sheet_structure(expected_two[0]),
                    _drawing_sheet_structure(expected_two[1]),
                    _drawing_sheet_structure(expected_two[1])]
        expected[1]["sketches"] = expected[2]["sketches"] = 1
        valid = all(_drawing_sheet_structure(row) == wanted
                    for row, wanted in zip(rows, expected))
    values = _drawing_persistence_sheet_values(p)
    valid = (valid and [row.get("name") for row in rows]
             == [_drawing_original_sheet()["name"], _DRAWING_COPY_SHEET,
                 _DRAWING_POPULATED_SHEET]
             and [row.get("is_active") for row in rows] == [False, False, True]
             and p.get("active_sheet") == _DRAWING_POPULATED_SHEET)
    return _measured("the A3/A2/A2 sheets read zero, one and one sketches", values,
                     valid and (not compare or _drawing_persistence_structure(p)
                                == _drawing_persistence_structure(
                                    _RECALL.get("drawing_populated_sheets") or {})))


def _drawing_parameter(height):
    """Require CloudPlateH to read one exact display-unit value."""
    def check(p):
        row = p.get("parameter") if isinstance(p.get("parameter"), dict) else {}
        return _measured(f"CloudPlateH reads {height:g} mm", {"parameter": row},
                         row.get("name") == "CloudPlateH"
                         and row.get("expression") == f"{height:g} mm"
                         and row.get("unit") == row.get("value_units") == "mm"
                         and _near(row.get("value"), height, 0.001))
    return check


def _drawing_parameter_set(before, after):
    """Require CloudPlateH's write response to carry exact before/after values and source identity."""
    def check(p):
        old, new = p.get("before") or {}, p.get("after") or {}
        return _measured(f"CloudPlateH changed from {before:g} to {after:g} mm",
                         {"set": p.get("set"), "created": p.get("created"), "name": p.get("name"),
                          "before": old, "after": new, "acted_on": p.get("acted_on")},
                         p.get("set") is True and p.get("created") is False
                         and p.get("name") == "CloudPlateH"
                         and _near(old.get("value"), before, 0.001)
                         and _near(new.get("value"), after, 0.001)
                         and old.get("value_units") == new.get("value_units") == "mm"
                         and (p.get("acted_on") or {}).get("document_id") == _RECALL.get("source_urn"))
    return check


def _drawing_source_version(before_key, unchanged_key=None):
    """Require the source's canonical version to advance without claiming old versions were restored."""
    def check(p):
        snap, before = _version_record(p), _RECALL.get(before_key) or {}
        valid = (_version_current(snap) and snap.get("lineage") == _RECALL.get("source_urn"))
        if unchanged_key:
            valid = valid and snap == _RECALL.get(unchanged_key)
        else:
            valid = valid and _version_current(before) and snap["number"] > before["number"]
        return _measured("the source's advanced cloud version is settled", snap, valid)
    return check


def _drawing_source_reopened(version_key, prior_handle_key):
    """Require the exact source version to open top-level under a fresh session handle."""
    def check(p):
        saved = _RECALL.get(version_key) or {}
        handle, active, acted = p.get("document_handle"), p.get("is_active"), p.get("acted_on")
        confirmed = (active is True and isinstance(acted, dict) and acted.get("name") == SOURCE_DOC
                     and acted.get("document_id") == _RECALL.get("source_urn")
                     and acted.get("document_handle") == handle)
        pending = "is_active" in p and (active is False or active is None) and "acted_on" in p and acted is None
        return _measured("the exact source version reopened top-level", p,
                         _version_current(saved) and p.get("opened") is True
                         and p.get("document_name") == SOURCE_DOC
                         and p.get("resolved_id") == saved.get("version_id")
                         and isinstance(handle, str) and handle.startswith("session:")
                         and handle != _RECALL.get(prior_handle_key) and (confirmed or pending))
    return check


def _drawing_source_document(handle_key, version_key):
    """Require the active top-level source session at the exact captured version."""
    def check(p):
        active, saved = p.get("active") or {}, _RECALL.get(version_key) or {}
        return _measured("the exact top-level source session reads back",
                         active,
                         _document_is(SOURCE_DOC)(p)
                         and active.get("document_id") == _RECALL.get("source_urn")
                         and active.get("document_handle") == _RECALL.get(handle_key)
                         and active.get("version_id") == saved.get("version_id")
                         and active.get("version_number") == saved.get("number"))
    return check


def _drawing_update_completed(job_key, request_key, handle_key, source_version_key):
    """Require the exact deferred update to finish one stale-to-current transition."""
    def check(p):
        expected = {"expect_document": _RECALL.get(handle_key)}
        payload = _drawing_terminal(p, job_key, request_key, "drawing_update", expected)
        source = _RECALL.get(source_version_key) or {}
        refs = payload.get("references") if isinstance(payload, dict) else None
        drawing = _RECALL.get("drawing") or [None, None]
        valid = (_version_current(source)
                 and isinstance(payload, dict) and payload.get("updated") is True
                 and payload.get("stale_references_before") == 1
                 and payload.get("stale_references_after") == 0
                 and payload.get("is_up_to_date") is True
                 and payload.get("update_call_result") is True
                 and refs == [{"index": 0, "is_out_of_date": False,
                               "version": source.get("number")}]
                 and (payload.get("acted_on") or {}).get("name") == drawing[1]
                 and (payload.get("acted_on") or {}).get("document_id") == drawing[0])
        return _measured("the exact deferred update completed one stale-to-current transition",
                         {"job_id": p.get("job_id"), "request_key": p.get("request_key"),
                          "arguments": p.get("arguments"), "terminal": payload}, valid)
    return check


def _drawing_reference_current(source_version_key):
    """Require a separate drawing_update read to report one current source version."""
    def check(p):
        source = _RECALL.get(source_version_key) or {}
        drawing = _RECALL.get("drawing") or [None, None]
        return _measured("the separate drawing update reports the source reference current",
                         {key: p.get(key) for key in ("updated", "stale_references_before",
                                                       "stale_references_after", "is_up_to_date",
                                                       "references", "document_modified", "acted_on")},
                         _version_current(source)
                         and p.get("updated") is False and p.get("stale_references_before") == 0
                         and p.get("stale_references_after") == 0
                         and p.get("is_up_to_date") is True
                         and p.get("references") == [{"index": 0, "is_out_of_date": False,
                                                      "version": source.get("number")}]
                         and (p.get("acted_on") or {}).get("name") == drawing[1]
                         and (p.get("acted_on") or {}).get("document_id") == drawing[0])
    return check

def _image_placed(p):
    """drawing_insert_image: 'position_bounds_checked' says the anchor was compared against the sheet
    BEFORE anything was placed - an off-sheet insert returns success and renders nothing, and an
    image cannot be read back or moved afterwards, so the check having run is the read-back."""
    return _measured("the image was placed inside the sheet",
                     {"inserted": p.get("inserted"), "scale": p.get("scale"),
                      "position_bounds_checked": p.get("position_bounds_checked")},
                     p.get("inserted") is True and p.get("position_bounds_checked") is True)


def _sketch_landed(name, count):
    """drawing_add_sketch: the curves the sheet sketch actually gained, counted off its own
    collections, on the sketch and sheet the payload names back."""
    def check(p):
        return _measured(f"'{name}' landed {count} curve(s)",
                         {"curves_landed": p.get("curves_landed"),
                          "curves_requested": p.get("curves_requested"),
                          "coordinates_verified": p.get("coordinates_verified"),
                          "sketch_name": p.get("sketch_name"), "sheet_name": p.get("sheet_name")},
                         p.get("curves_landed") == count and p.get("sketch_name") == name
                         and bool(p.get("sheet_name"))
                         and p.get("coordinates_verified") is False)
    return check


def _drawing_sketch_deleted(sketch_name, sheet_name):
    """drawing_delete_sketch: the sheet's own sketch count fell by exactly one and the payload
    names the sketch and sheet back, off the tool's own before/after read-back."""
    def check(p):
        return _measured(f"'{sketch_name}' deleted from sheet '{sheet_name}'",
                         {"deleted": p.get("deleted"), "sketch": p.get("sketch"),
                          "sheet": p.get("sheet"),
                          "sketch_count_before": p.get("sketch_count_before"),
                          "sketch_count": p.get("sketch_count")},
                         p.get("deleted") is True and p.get("sketch") == sketch_name
                         and p.get("sheet") == sheet_name
                         and _num(p.get("sketch_count_before"))
                         and p.get("sketch_count") == p["sketch_count_before"] - 1)
    return check


def _drawing_sketch_count_values(p):
    rows = p.get("sheets")
    if not isinstance(rows, list):
        return {}
    return {row.get("name"): row.get("sketches") for row in rows if isinstance(row, dict)}


def _drawing_sketch_census(p):
    counts = _drawing_sketch_count_values(p)
    rows = p.get("sheets")
    valid = (_sheets_answer(p) and isinstance(rows, list)
             and len(counts) == len(rows)
             and all(isinstance(name, str) and type(value) is int and value >= 0
                     for name, value in counts.items()))
    return _measured("every drawing sheet reports its sketch count", {"counts": counts}, valid)


def _drawing_sketch_census_unchanged(key):
    def check(p):
        counts = _drawing_sketch_count_values(p)
        valid = (_drawing_sketch_census(p)
                 and _RECALL.get(key) is not None
                 and counts == _RECALL.get(key))
        return _measured("the refused sketch request left all sheet sketch counts unchanged",
                         {"counts": counts, "before": _RECALL.get(key)}, valid)
    return check


def _dxf_layer_entities(path, layer):
    """Every entity one DXF carries on `layer`, as (type, [(x, y), ...]) - None when the file will
    not read. A drawing-sketch curve exposes no geometry to the API, so this export is the only
    channel a landed coordinate reaches at all."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rows = [line.strip() for line in fh]
    except OSError:
        return None
    out, kind, ent = [], None, None
    for code, value in ((rows[i], rows[i + 1]) for i in range(0, len(rows) - 1, 2)):
        if code == "0":
            if ent is not None and ent["layer"] == layer:
                out.append((kind, ent["points"]))
            kind, ent = value, {"layer": None, "points": [], "x": None}
            continue
        if ent is None:
            continue
        if code == "8" and ent["layer"] is None:
            ent["layer"] = value
        elif code in ("10", "11"):
            ent["x"] = _dxf_number(value)
        elif code in ("20", "21") and ent["x"] is not None:
            y = _dxf_number(value)
            if y is not None:
                ent["points"].append((ent["x"], y))
            ent["x"] = None
    if ent is not None and ent["layer"] == layer:
        out.append((kind, ent["points"]))
    return out


def _dxf_number(value):
    try:
        return float(value)
    except ValueError:
        return None


def _sketch_readback(sketch_name, curves):
    """drawing_export(dxf): the sketch's own DXF layer, holding one entity per landed curve.

    The vertices are published and asserted nowhere - a point near a drawing view's curve snaps onto
    that curve, so an exact-coordinate assertion would pin where this run's views sit."""
    def check(p):
        _exported(p)
        entities = _dxf_layer_entities(p.get("file_path") or "", sketch_name)
        landed = [[kind] + [[round(x, 4), round(y, 4)] for x, y in pts]
                  for kind, pts in (entities or [])]
        return _measured(f"the DXF layer '{sketch_name}' holds {curves} landed curve(s)",
                         {"file_path": p.get("file_path"), "layer": sketch_name,
                          "entity_count": None if entities is None else len(entities),
                          "landed": landed},
                         entities is not None and len(entities) == curves)
    return check


def _blank_sheet_readback(p):
    """drawing_export(dxf): the blank sheet carries none of the three named sketch layers."""
    return (_sketch_readback(_DRAWING_SKETCH_NAME, 0)(p)
            and _sketch_readback(_DRAWING_BLANK_SKETCH_NAME, 0)(p)
            and _sketch_readback(_DRAWING_WORKLOAD_NAME, 0)(p))


def _derived(source):
    """doc_insert_derive: the one-way linked copy this document gained, and the SOURCE VERSION the
    link is bound to - the number a later save of the source moves past, which is what leaves the
    reference stale for the refusal below to be read on."""
    def check(p):
        return _measured(f"'{source}' derived, bound to its saved version",
                         {"derived": p.get("derived"), "feature_name": p.get("feature_name"),
                          "document_name": p.get("document_name"),
                          "source_version": p.get("source_version"),
                          "derived_occurrence": p.get("derived_occurrence"),
                          "bodies_landed": p.get("bodies_landed")},
                         p.get("derived") is True and p.get("document_name") == source
                         and bool(p.get("feature_name")) and _num(p.get("source_version")))
    return check


def _selector_design(p):
    """Read the complete empty or single-component cloud fixture tree and healthy history."""
    tree, tl = p.get("tree") or {}, p.get("timeline") or {}
    nodes, rows = tree.get("children"), tl.get("timeline")
    valid = (isinstance(nodes, list) and tree.get("child_count") == len(nodes) <= 1
             and tree.get("truncated") is False and tree.get("children_truncated") is False
             and not tree.get("root_bodies") and not tree.get("root_bodies_truncated")
             and isinstance(rows, list) and tl.get("count") == tl.get("returned")
             == tl.get("marker_position") == len(rows) and not tl.get("truncated")
             and (tl.get("summary") or {}).get("exceptions") == []
             and (tl.get("summary") or {}).get("states") == ({"healthy": len(rows)} if rows else {})
             and isinstance(tl.get("groups"), dict)
             and all(r.get("index") == i and r.get("name") and r.get("type")
                     for i, r in enumerate(rows)))
    for node in nodes or []:
        valid = (valid and node.get("full_path") and node.get("handle")
                 and node.get("child_count") == 0 and not node.get("children_truncated")
                 and node.get("body_count") == len(node.get("bodies") or []) == 1
                 and not node.get("bodies_truncated")
                 and all(b.get("name") and b.get("handle") and b.get("is_solid") is True
                         and type(b.get("visible")) is bool for b in node.get("bodies") or []))
    if not valid:
        raise AssertionError("Selector fixture tree/history did not read completely")
    return {"tree": tree, "timeline": tl}


def _selector_session(p):
    """Read actual active identity/save flags and the complete session handle/name census."""
    active, docs = p.get("active") or {}, p.get("open_documents")
    fields = ("document_handle", "name", "document_id", "version_id", "version_number",
              "is_saved", "is_modified", "has_data_file")
    if (not isinstance(docs, list) or p.get("open_count") != len(docs)
            or any(not d.get("document_handle") or not d.get("name") for d in docs)
            or len({d["document_handle"] for d in docs}) != len(docs)
            or not active.get("document_handle") or not active.get("name")
            or any(type(active.get(k)) is not bool for k in fields[-3:])):
        raise AssertionError("Selector fixture session did not read completely")
    out = {"active": {k: active.get(k) for k in fields},
           "documents": sorted((d["document_handle"], d["name"]) for d in docs)}
    if "versions" in p:
        v = p["versions"]
        rows = v.get("versions")
        if (v.get("history_readable") is not True or v.get("history_complete") is not True
                or not isinstance(rows, list) or v.get("version_count") != len(rows)
                or any(type(r.get("version_number")) is not int or not r.get("version_id") for r in rows)):
            raise AssertionError("Selector fixture version history did not read completely")
        out["versions"] = {"latest": v.get("latest_version_number"),
                           "rows": [(r["version_number"], r["version_id"]) for r in rows]}
    return out


def _selector_source_sketch(p):
    """Read the source plate's complete disclosed X-ray around a refused restore."""
    if (p.get("sketch") != SRC_SKETCH or p.get("component") != SRC_COMP
            or p.get("units") != "mm" or p.get("truncated") is not False
            or not isinstance(p.get("frame"), dict) or not p.get("entities")
            or p.get("constraint_count") != len(p.get("constraints") or [])
            or p.get("dimension_count") != len(p.get("dimensions") or [])
            or p.get("profile_count") != len(p.get("profiles") or [])):
        raise AssertionError("Source plate X-ray did not read completely")
    return {k: v for k, v in p.items() if k != "note"}


def _selector_reads(reads, after=False):
    """Build this cloud selector witness's capture or equality rows."""
    return [(tool, args,
             lambda p, key=key, read=read: _measured("selector preserves " + key, read(p),
                 not after or read(p) == _RECALL.get(key)),
             None if after else (key, _recall(key, read))) for tool, args, key, read in reads]


_SELECTOR_DESIGN_ARGS = {"include": ["tree", "timeline"], "tree_bodies": True,
                         "tree_handles": True, "max_depth": 3, "max_results": 30}


def _restore_selector_baseline(ctx):
    """Settle the exact milestone before capturing an unchanged-version refusal baseline."""
    _milestone_restore_args(ctx)
    return {"include": ["default", "versions"], "versions_max": 10}


def _restore_conflict(ctx):
    """Pair distinct version numbers and milestone ids for a conflicting-selector request."""
    before = _ctx_get(ctx, "selector_restore_session", "complete restore baseline")
    target = ctx["milestone_settled"]
    if target["version"] == RESTORE_VERSION:
        raise AssertionError("Conflict requires two distinct versions")
    return {"version_number": RESTORE_VERSION, "version_id": target["version_id"],
            "expect_document": before["active"]["document_handle"]}


_RESTORE_SELECTOR_READS = [
    ("doc_get", {"include": ["default", "versions"], "versions_max": 10},
     "selector_restore_session", _selector_session),
    ("design_get", _SELECTOR_DESIGN_ARGS, "selector_restore_design", _selector_design),
    ("sketch_get", {"sketch_name": SRC_SKETCH, "component": SRC_COMP + ":1",
                    "include_entities": True, "units": "mm", "max_results": 100},
     "selector_restore_sketch", _selector_source_sketch),
]


def _derive_selector_rows():
    """Refuse blank include/exclude entries, then consume a valid subset on one owned host."""
    reads = [("doc_get", {}, "selector_derive_session", _selector_session),
             ("design_get", _SELECTOR_DESIGN_ARGS, "selector_derive_design", _selector_design)]
    def home(p):
        facts = _selector_session(p)
        _RECALL["selector_derive_home_state"] = facts
        return _home_document(p) and facts["active"]["document_id"] == _RECALL.get("source_urn")

    rows = [("doc_get", {}, home,
             ("selector_derive_home", _recall("selector_derive_home", _home_address))),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "selector_derive_home", "source")},
             _new_document, ("selector_derive_doc", _recall("selector_derive_doc", lambda p: p["document_handle"])))]
    rows += _selector_reads(reads)
    for field, value in (("source_components", [""]), ("source_bodies", [SRC_COMP + "/Body1", " "]),
                         ("exclude_components", [SRC_COMP, ""]), ("exclude_bodies", [" "])):
        rows.append(("doc_insert_derive", lambda c, field=field, value=value: {
            "document_id": _ctx_get(c, "source_urn", "source"), field: value,
            "expect_document": _ctx_get(c, "selector_derive_doc", "derive host")},
            _refused(field, "nonblank", "Remove that entry"), None))
        rows += _selector_reads(reads, True)
    # a sub-component body is refused before createInput; the component row below is its remedy
    rows.append(("doc_insert_derive", lambda c: {
        "document_id": _ctx_get(c, "source_urn", "source"), "source_bodies": [SRC_COMP + "/Body1"],
        "expect_document": _ctx_get(c, "selector_derive_doc", "derive host")},
        _refused(f"sub-component '{SRC_COMP}'", "3 : invalid argument entities",
                 "Nothing was derived", f"source_components=['{SRC_COMP}']"), None))
    rows += _selector_reads(reads, True)

    rows += [
        ("doc_insert_derive", lambda c: {"document_id": _ctx_get(c, "source_urn", "source"),
             "source_components": [SRC_COMP], "exclude_bodies": [],
             "expect_document": _ctx_get(c, "selector_derive_doc", "derive host")},
         lambda p: _derived(SOURCE_DOC)(p) and p.get("scope") == SRC_COMP, None),
        ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
         _plate_geometry("the explicitly selected derived source", 16.0), None),
        ("doc_activate", lambda c: {"name": _ctx_get(c, "selector_derive_home", "source"),
             "expect_document": _ctx_get(c, "selector_derive_doc", "derive host")}, _activated(SOURCE_DOC), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "selector_derive_doc", "derive host"),
             "save_changes": False, "expect_document": _ctx_get(c, "selector_derive_home", "source")},
         _document_closed, None),
        ("doc_get", {}, lambda p: _document_is(SOURCE_DOC)(p)
         and _selector_session(p) == _RECALL.get("selector_derive_home_state"), None),
    ]
    return rows


def _named_derive_tree(p, count, history):
    """Read this root-body coupon's complete membership and healthy timeline."""
    tree, tl = p.get("tree") or {}, p.get("timeline") or {}
    bodies, rows = tree.get("root_bodies") or [], tl.get("timeline")
    if (tree.get("child_count") != 0 or tree.get("children") != []
            or tree.get("truncated") is not False or tree.get("children_truncated") is not False
            or tree.get("root_bodies_truncated") or len(bodies) != count
            or any(not b.get("name") or not b.get("handle") or b.get("is_solid") is not True
                   or type(b.get("visible")) is not bool for b in bodies)
            or not isinstance(rows, list) or len(rows) != history
            or tl.get("count") != history or tl.get("returned") != history
            or tl.get("marker_position") != history or tl.get("truncated")
            or any(r.get("index") != i or not r.get("name") or not r.get("type")
                   for i, r in enumerate(rows))
            or (tl.get("summary") or {}).get("exceptions") != []
            or (tl.get("summary") or {}).get("states") != ({"healthy": history} if history else {})):
        raise AssertionError("Named derive body membership/history did not read completely")
    return {"tree": tree, "timeline": tl}


def _named_derive_mass(p, size, x=0):
    """Read the selected cube or the separate source control's material and bounds."""
    if (p.get("units") != "mm" or p.get("kind") != "body"
            or p.get("frame") != "world axes (axis-aligned)"
            or any(not _near(p.get(axis), size, .0001) for axis in "xyz")
            or any(not _near((p.get("min_point") or {}).get(axis), value, .0001)
                   for axis, value in zip("xyz", (x, 0, 0)))
            or any(not _near((p.get("max_point") or {}).get(axis), value, .0001)
                   for axis, value in zip("xyz", (x + size, size, size)))
            or not _near((p.get("mass") or {}).get("volume"), size ** 3, .001)):
        raise AssertionError("Named derive body size/material did not match its source")
    return p


def _named_derive_rows():
    """Derive one named body from a separate two-body source, preserving its sibling and home."""
    name = "SweepNamedDerive." + _STAMP
    def home(p):
        _RECALL["named_home_state"] = _selector_session(p)
        return _home_document(p)
    rows = [("doc_get", {}, home, ("named_home", _recall("named_home", _home_address))),
            ("doc_new", lambda c: {"expect_document": c["named_home"]}, _new_document,
             ("named_source", _recall("named_source", lambda p: p["document_handle"])))]
    def write(tool, args, check="ok", save=None, owner="named_source"):
        rows.append((tool, lambda c, args=args, owner=owner: {
            **(args(c) if callable(args) else args), "expect_document": c[owner]}, check, save))
    for key, x, size in (("selected", 0, 10), ("sibling", 30, 20)):
        sketch = "NamedDerive_" + key
        write("sketch_create", {"plane": "xy", "name": sketch})
        write("sketch_add_geometry", {"sketch_name": sketch, "geometry": [
            {"kind": "rectangle", "x1": x, "y1": 0, "x2": x + size, "y2": size}]})
        write("model_extrude", {"sketch_name": sketch, "distance": size, "operation": "new"},
              lambda p: _extruded(p) and len(p.get("result_bodies") or []) == 1,
              ("named_" + key, _recall("named_" + key, lambda p: p["result_bodies"][0])))
    write("doc_save_as", {"name": name, "project": PROJECT, "folder": FOLDER},
          _saved_as(name, FOLDER))
    rows += _settled(name, "named_urn")
    rows.append(("data_get", lambda c: {"file": c["named_urn"]},
                 _file_settled(FOLDER, file_key="named_urn", file_name=name), None))
    controls = [("design_get", _SELECTOR_DESIGN_ARGS, "named_tree",
                 lambda p: _named_derive_tree(p, 2, 4)),
                ("doc_get", {}, "named_session", _selector_session)]
    for key, size, x in (("selected", 10, 0), ("sibling", 20, 30)):
        controls.append(("model_inspect", lambda c, key=key: {"target": c["named_" + key],
                         "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                         "named_mass_" + key, lambda p, size=size, x=x: _named_derive_mass(p, size, x)))
    rows += _selector_reads(controls)
    write("doc_new", {}, _new_document,
          ("named_host", _recall("named_host", lambda p: p["document_handle"])))
    rows.append(("design_get", _SELECTOR_DESIGN_ARGS, "ok",
                 ("named_empty", _recall("named_empty", lambda p: _named_derive_tree(p, 0, 0)))))
    write("doc_insert_derive", lambda c: {"document_id": c["named_urn"],
          "source_bodies": [c["named_selected"], c["named_sibling"]],
          "exclude_bodies": [c["named_sibling"]]},
          _refused("remains", "excluded source body", "exclusion did not take",
                   "remains in the timeline; remove it with design_delete_feature(feature='",
                   "@0')."),
          owner="named_host")
    rows.append(("design_get", _SELECTOR_DESIGN_ARGS,
                 lambda p: _named_derive_tree(p, 2, 1) and {b["name"] for b in p["tree"]["root_bodies"]}
                 == {_RECALL["named_selected"], _RECALL["named_sibling"]},
                 ("named_failed_feature", lambda p: p["timeline"]["timeline"][0]["name"] + "@0")))
    for key, size, x in (("selected", 10, 0), ("sibling", 20, 30)):
        rows.append(("model_inspect", lambda c, key=key: {"target": c["named_" + key],
                     "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                     lambda p, size=size, x=x: p.get("kind") == "body"
                     and _named_derive_mass(p, size, x), None))
    write("design_delete_feature", lambda c: {"feature": c["named_failed_feature"]}, owner="named_host")
    rows.append(("design_get", _SELECTOR_DESIGN_ARGS,
                 lambda p: _named_derive_tree(p, 0, 0) == _RECALL["named_empty"], None))
    write("doc_insert_derive", lambda c: {"document_id": c["named_urn"],
          "source_bodies": [c["named_selected"]]},
          lambda p: _derived(name)(p) and p.get("bodies_landed") == 1
          and p.get("derived_components") == []
          and p.get("derived_bodies") == [{"name": _RECALL["named_selected"], "is_derived": True}],
          owner="named_host")
    rows += [
        ("design_get", _SELECTOR_DESIGN_ARGS,
         lambda p: _named_derive_tree(p, 1, 1)["tree"]["root_bodies"][0]["name"]
         == _RECALL["named_selected"], None),
        ("model_inspect", lambda c: {"target": c["named_selected"], "include": ["default", "mass"],
                                    "units": "mm", "accuracy": "very_high"},
         lambda p: _named_derive_mass(p, 10) and all(p.get(k) == _RECALL["named_mass_selected"].get(k)
             for k in ("x", "y", "z", "min_point", "max_point")), None),
        ("doc_get", {"include": ["default", "xref_tree"]}, lambda p: (
             p["xref_tree"].get("walk_complete") is True and p["xref_tree"].get("all_current") is True
             and p["xref_tree"].get("reference_link_count") == 1
             and len(p["xref_tree"].get("references") or []) == 1
             and p["xref_tree"]["references"][0].get("kind") == "derive"
             and p["xref_tree"]["references"][0].get("source_document") == name
             and p["xref_tree"]["references"][0].get("out_of_date") is False), None)]
    # whole design minus the sibling: 'excluded' must come from the landing, judged by its volume
    write("doc_insert_derive", lambda c: {"document_id": c["named_urn"],
          "exclude_bodies": [c["named_sibling"]]},
          lambda p: _derived(name)(p) and _measured(
              "the excluded root body read back from the landing",
              {k: p.get(k) for k in ("excluded", "exclusion_unverified", "derived_components")},
              p.get("excluded") == _RECALL["named_sibling"] and "exclusion_unverified" not in p
              and [r.get("body_count") for r in p.get("derived_components") or []] == [1]),
          ("named_excluding", _recall("named_excluding", lambda p: p["derived_occurrence"])),
          owner="named_host")
    rows.append(("model_inspect", lambda c: {"target": c["named_excluding"],
                 "include": ["default", "mass"], "units": "mm", "accuracy": "very_high"},
                 lambda p: _measured("the excluding derive holds only the 10 mm cube", p,
                     p.get("kind") == "occurrence" and all(_near(p.get(a), 10, .0001) for a in "xyz")
                     and _near((p.get("mass") or {}).get("volume"), 1000, .001)), None))
    write("doc_activate", lambda c: {"name": c["named_source"]}, _activated(name), owner="named_host")
    write("doc_close", lambda c: {"name": c["named_host"], "save_changes": False}, _document_closed)
    rows += _selector_reads(controls, True)
    write("doc_activate", lambda c: {"name": c["named_home"]}, _activated())
    write("doc_close", lambda c: {"name": c["named_source"], "save_changes": False},
          _document_closed, owner="named_home")
    write("data_delete_file", lambda c: {"document_id": c["named_urn"], "confirm_name": name},
          _file_deleted, owner="named_home")
    rows.append(("doc_get", {}, lambda p: _selector_session(p) == _RECALL["named_home_state"], None))
    return rows


# How long the source's new version is given to become visible to the CLOUD before the tip read
# below asserts it. doc_save returns as soon as Fusion has written; the version METADATA the derive
# link's freshness is judged against trails it by up to ~20 s (doc_get's own note gives that lag),
# so this is that window with a margin. It is not what makes the row correct - the read after it is
# - so a window that turns out short fails at the tip read, naming both numbers.
_TIP_SETTLE_S = 25.0


def _tip_read(p):
    """doc_get(include=['versions']) on the source: the cloud tip, banked for the row that waits on
    it to move."""
    v = p.get("versions") or {}
    return _measured("the source's cloud tip reads",
                     {"available": v.get("available"),
                      "latest_version_number": v.get("latest_version_number"),
                      "version_count": v.get("version_count")},
                     v.get("available") is True and _num(v.get("latest_version_number")))


def _tip_advanced(key):
    """doc_get(include=['versions']): the source's tip has moved PAST the number banked before the
    save - the read the reopen below stands on.

    MEASURED twice, opposite ways, on the same steps: a derive reference read out of date on one run
    and 'already up to date' on the next. What decides it is whether the cloud has published the
    source's new version by the time the host reopens, not how long anything slept - so the dwell
    ahead of this row only spends the expected lag, and THIS row is the gate. Its failure names the
    tip it saw beside the one it wanted, where a short dwell otherwise surfaces as the refresh row
    reporting a reference that is merely current."""
    def check(p):
        v = p.get("versions") or {}
        before, now = _RECALL.get(key), v.get("latest_version_number")
        return _measured(f"the source's tip advanced past version {before}",
                         {"tip_before": before, "latest_version_number": now,
                          "version_count": v.get("version_count"),
                          "history_readable": v.get("history_readable")},
                         _num(before) and _num(now) and now > before)
    return check


def _settled(name, key=None):
    """The read every lineage-URN capture goes through, and the only place the tier reads a URN off
    a just-saved document.

    No hold precedes it: doc_save_as pumps for the urn before it answers and publishes
    urn_wait_seconds, so a dwell here would only re-spend that wait. The failure this read exists
    for is silent at the row that causes it: the save reports 'saved' and the right name, the read
    banks whatever document_id is there, and it is TEN steps later - at an activate, a close and a
    delete - that a local path turns out not to address anything."""
    return [("doc_get", {}, _document_is(name),
             (key, _recall(key, lambda p: p["active"]["document_id"])) if key else None)]


def _modified_reads(name, expected):
    """doc_get: the active document is `name` and its is_modified flag reads `expected`."""
    def check(p):
        active = p.get("active") or {}
        return _measured(f"'{name}' reads is_modified {expected}",
                         {"name": active.get("name"), "is_modified": active.get("is_modified")},
                         active.get("name") == name and active.get("is_modified") is expected)
    return check


def _fit_to_modified_disclosed(p):
    """view_screenshot fit_to on a clean document: its text block names the flag the shot set."""
    text = str(p)
    return _measured("the fit_to shot says it left the document modified", {"text": text[:400]},
                     "records as a document modification" in text)


def _fit_refusal_visibility(p):
    """Read both placed bodies' complete visibility records without transient handles."""
    tree = p["tree"]
    nodes = tree.get("children") or []
    if (tree.get("truncated") is not False or tree.get("children_truncated") is not False
            or tree.get("child_count") != 2 or len(nodes) != 2
            or {n.get("name") for n in nodes} != {_RECALL["fit_first"], _RECALL["fit_second"]}
            or any(n.get("body_count") != 1 or n.get("child_count") != 0
                   or len(n.get("bodies") or []) != 1
                   or n["bodies"][0].get("visible") is not True
                   or n["bodies"][0].get("is_solid") is not True for n in nodes)):
        raise AssertionError("the two visible cube placements did not read completely")
    return [(n["name"], n["component"], n["bodies"][0]["name"],
             n["bodies"][0]["visible"]) for n in nodes]


def _fit_refusal_mass(p):
    """Require one 10 mm cube's independent material and box measurement."""
    if (p.get("kind") != "occurrence" or p.get("units") != "mm"
            or any(not _near(p.get(axis), 10, .0001) for axis in "xyz")
            or not _near((p.get("mass") or {}).get("volume"), 1000, .001)):
        raise AssertionError("the placed cube's material or box did not read")
    return p


def _fit_refusal_poses(p):
    """Require both complete placed frames and healthy history before comparing them."""
    rows = p.get("occurrences") or []
    if (p.get("is_healthy") is not True or p.get("occurrence_count") != 2
            or p.get("occurrences_truncated") is not False or len(rows) != 2
            or {r.get("name") for r in rows} != {_RECALL["fit_first"], _RECALL["fit_second"]}
            or any(not isinstance(r.get(key), list) or len(r[key]) != 3
                   or not all(_num(v) for v in r[key]) for r in rows
                   for key in ("origin", "x_axis", "y_axis", "z_axis", "bbox_center", "bbox_size"))
            or {r["name"]: r["origin"] for r in rows} != {
                _RECALL["fit_first"]: [0, 0, 0], _RECALL["fit_second"]: [30, 0, 0]}):
        raise AssertionError("the cube placement frames did not read completely")
    return rows


def _fit_refusal_history(p):
    """Read the complete four-row coupon timeline and its end marker."""
    history = p["timeline"]
    if (history.get("count") != 4 or history.get("returned") != 4
            or history.get("marker_position") != 4 or history.get("truncated")
            or len(history.get("timeline") or []) != 4):
        raise AssertionError("the cube history did not read completely")
    return history


def _fit_refusal_sketches(p):
    """Read the complete one-sketch list for the shared cube component."""
    if p.get("sketch_count") != 1 or len(p.get("sketches") or []) != 1 or p.get("truncated"):
        raise AssertionError("the cube sketch census did not read completely")
    return p


def _released_then_deleted(name, key):
    """Delete an owned closed coupon or independently witness Fusion's retained in-use refusal."""
    def urn(c):
        return _ctx_get(c, key + "_urn", "the saved file")

    def home(c):
        return _ctx_get(c, key + "_home", "home")

    admitted = {}

    def cleanup_args(c):
        admitted.update(urn=urn(c), home=home(c))
        return {"file": admitted["urn"]}

    def released(p):
        call, reads = facade("call"), 1
        for _ in range(12):
            if (p.get("state") or {}).get("is_in_use") is False:
                break
            time.sleep(_SETTLE_GAP_S)
            is_error, again = call("data_get", {"file": (p.get("file") or {}).get("id") or ""})
            reads += 1
            if not is_error and isinstance(again, dict):
                p = again
        return _measured("the closed coupon's state is readable", {"state": p.get("state"), "reads": reads},
                         type((p.get("state") or {}).get("is_in_use")) is bool
                         and (p.get("state") or {}).get("is_complete") is True
                         and (p.get("file") or {}).get("name") == name
                         and (p.get("file") or {}).get("id") == _RECALL.get(key + "_urn"))

    def cleanup(p):
        file = p.get("file") or {}
        own_urn = admitted.get("urn")
        _measured("cleanup targets only this run's closed coupon", file,
                  key in ("fit", "roll") and name == {
                      "fit": "SweepFitRefusal.", "roll": "SweepSketchRoll."}[key] + _STAMP
                  and bool(own_urn) and bool(admitted.get("home"))
                  and file.get("id") == own_urn and file.get("name") == name
                  and (p.get("state") or {}).get("is_complete") is True
                  and type((p.get("state") or {}).get("is_in_use")) is bool)
        call = facade("call")
        is_error, deleted = call("data_delete_file", {
            "document_id": own_urn, "confirm_name": name,
            "expect_document": admitted["home"]})
        if not is_error:
            return _measured("delete answers this exact coupon", deleted,
                             deleted.get("document_id") == own_urn and deleted.get("name") == name
                             and _file_deleted(deleted))
        _measured("only the measured in-use delete refusal is admitted", deleted,
                  (p.get("state") or {}).get("is_in_use") is True
                  and str(deleted) == f"Delete failed for '{name}': 2 : InternalValidationError : res")
        read_error, after = call("data_get", {"file": own_urn})
        _measured("refused delete leaves the exact complete coupon in use", after,
                  not read_error and isinstance(after, dict)
                  and (after.get("file") or {}).get("id") == own_urn
                  and (after.get("file") or {}).get("name") == name
                  and (after.get("state") or {}).get("is_in_use") is True
                  and (after.get("state") or {}).get("is_complete") is True)
        qualification = (f"Delete refused by Fusion, file left in place: {name} ({own_urn}). "
                         "Successful-delete path on this coupon was not demonstrated in this run.")
        _RECALL.setdefault("closed_cloud_delete_limits", []).append(qualification)
        facade("STORY")["data_delete_file"] += " " + qualification
        facade("STORY")["data_get"] += " " + qualification
        print(qualification, flush=True)
        return True
    return [
        ("doc_open", lambda c: {"file_id": urn(c), "force_api_open": True, "expect_document": home(c)},
         _opened(name, lambda: _RECALL.get(key + "_urn")),
         (key + "_reopened", _recall(key + "_reopened", lambda p: p["document_handle"]))),
        ("doc_get", {}, _modified_reads(name, False), None),
        ("doc_activate", lambda c: {"name": home(c)}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, key + "_reopened", "the reopened file"),
                                 "save_changes": False, "expect_document": home(c)},
         _document_closed, None),
        ("data_get", lambda c: {"file": urn(c)}, released, None),
        ("data_get", cleanup_args, cleanup, None)]


def _fit_refusal_rows():
    """Demonstrate dirty-state disclosure on the saved shared-body refusal in the cloud act."""
    name = "SweepFitRefusal." + _STAMP
    path = os.path.join(EXPORT_DIR, "fit-refused-" + _STAMP + ".png")
    rows = [("doc_get", {}, _home_document, ("fit_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "fit_home", "home")},
             _new_document, ("fit_doc", _recall("fit_doc", lambda p: p["document_handle"])))]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: {**(args(c) if callable(args) else args),
                     "expect_document": _ctx_get(c, "fit_doc", "fit coupon")}, check, save))
    write("model_create_component", {"name": "FitBulb", "activate": True}, _made_component,
          ("fit_first", _recall("fit_first", lambda p: p["full_path"])))
    write("sketch_create", {"plane": "xy", "name": "FitBulbS"})
    write("sketch_add_geometry", {"sketch_name": "FitBulbS", "geometry": [
          {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]})
    write("model_extrude", {"sketch_name": "FitBulbS", "distance": 10}, _extruded)
    write("design_activate_component", {"occurrence": "root"})
    write("design_add_instance", lambda c: {"component": _ctx_get(c, "fit_first", "first placement"), "x": 30},
          lambda p: bool(p.get("full_path")), ("fit_second", _recall("fit_second", lambda p: p["full_path"])))
    write("doc_save_as", {"name": name, "project": PROJECT, "folder": FOLDER},
          _saved_as(name, FOLDER))
    rows += _settled(name, "fit_urn")
    rows.append(("data_get", lambda c: {"file": c["fit_urn"]},
                 _file_settled(FOLDER, file_key="fit_urn", file_name=name), None))
    controls = [
        ("workspace_orient", {}, "fit_camera", _section_camera),
        ("design_get", {"include": ["tree"], "tree_bodies": True}, "fit_visibility", _fit_refusal_visibility),
        ("assembly_get", {"include": ["poses"]}, "fit_poses", _fit_refusal_poses),
        ("design_get", {"include": ["timeline"], "max_results": 1000}, "fit_history", _fit_refusal_history),
        ("sketch_get", {"component": "FitBulb", "max_results": 1000}, "fit_sketches", _fit_refusal_sketches)]
    for key in ("fit_first", "fit_second"):
        controls.append(("model_inspect", lambda c, key=key: {"target": _ctx_get(c, key, "cube"),
                         "include": ["default", "mass"], "units": "mm"}, "fit_mass_" + key, _fit_refusal_mass))
    for tool, args, key, extract in controls:
        rows.append((tool, args, "ok", (key, _recall(key, extract))))
    rows.append(("find_geometry", lambda c: {"target": _ctx_get(c, "fit_first", "cube"),
                 "kind": "planar_face", "nearest_to": [5, 5, 10], "max_results": 1},
                 _face_up_at(5, 5, 10), _fg("fit_face")))
    rows.append(("doc_get", {}, lambda p: _modified_reads(name, False)(p)
                 and (p.get("active") or {}).get("is_saved") is True
                 and (p.get("active") or {}).get("document_handle") == _RECALL["fit_doc"]
                 and not os.path.exists(path), None))
    write("view_screenshot", lambda c: {"fit_to": _ctx_get(c, "fit_face", "cube face"),
          "view": "iso-top-right", "width": 300, "height": 240, "file_path": path},
          _refused("another placement of the same body was hidden", "fullPathName", "Nothing was captured",
                   "records as a document modification", "doc_get", "doc_save"))
    rows.append(("doc_get", {}, lambda p: _modified_reads(name, True)(p)
                 and (p.get("active") or {}).get("is_saved") is False
                 and (p.get("active") or {}).get("document_handle") == _RECALL["fit_doc"]
                 and not os.path.exists(path), None))
    for tool, args, key, extract in controls:
        rows.append((tool, args, lambda p, key=key, extract=extract: _measured(
            "refused fit preserves " + key, extract(p), bool(_RECALL.get(key))
            and extract(p) == _RECALL[key]), None))
    write("doc_activate", lambda c: {"name": _ctx_get(c, "fit_home", "home")})
    rows.append(("doc_close", lambda c: {"name": _ctx_get(c, "fit_doc", "fit coupon"),
                 "save_changes": False, "expect_document": _ctx_get(c, "fit_home", "home")}, _document_closed, None))
    rows += _released_then_deleted(name, "fit")
    return rows


def _sketch_roll_dirty_rows():
    """sketch_get on a face-supported sketch of a saved, clean design discloses the dirty flag."""
    name = "SweepSketchRoll." + _STAMP
    rows = [("doc_get", {}, _home_document, ("roll_home", _home_address)),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "roll_home", "home")},
             _new_document, ("roll_doc", _recall("roll_doc", lambda p: p["document_handle"])))]
    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: {**(args(c) if callable(args) else args),
                     "expect_document": _ctx_get(c, "roll_doc", "roll scratch")}, check, save))
    write("sketch_create", {"plane": "xy", "name": "RollBaseS"})
    write("sketch_add_geometry", {"sketch_name": "RollBaseS", "geometry": [
          {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 40, "y2": 30}]})
    write("model_extrude", {"sketch_name": "RollBaseS", "distance": 20}, _extruded)
    rows.append(("find_geometry", {"kind": "planar_face", "nearest_to": [20, 15, 20], "max_results": 1},
                 _face_up_at(20, 15, 20), _fg("roll_face")))
    write("sketch_create", lambda c: {"on_face": _ctx_get(c, "roll_face", "box top face"), "name": "RollFaceS"})
    write("sketch_add_geometry", {"sketch_name": "RollFaceS", "geometry": [
          {"kind": "circle", "cx": 20, "cy": 15, "radius": 5}]})
    write("sketch_create", {"plane": "xz", "name": "RollPlaneS"})
    write("sketch_add_geometry", {"sketch_name": "RollPlaneS", "geometry": [
          {"kind": "line", "x1": 0, "y1": -30, "x2": 40, "y2": -30}]})
    write("doc_save_as", {"name": name, "project": PROJECT, "folder": FOLDER},
          _saved_as(name, FOLDER))
    rows += _settled(name, "roll_urn")
    rows.append(("data_get", lambda c: {"file": c["roll_urn"]},
                 _file_settled(FOLDER, file_key="roll_urn", file_name=name), None))
    rows.append(("doc_get", {}, _modified_reads(name, False), None))
    rows.append(("sketch_get", {"sketch_name": "RollPlaneS"},
                 lambda p: _measured("plane read publishes no dirty flag", p.get("plane"),
                                     p.get("plane") == "XZ" and "document_modified" not in p), None))
    rows.append(("doc_get", {}, _modified_reads(name, False), None))
    rows.append(("sketch_get", {"sketch_name": "RollFaceS"},
                 lambda p: _measured("face read discloses the clean-to-modified flip",
                                     {k: p.get(k) for k in ("plane", "on_face", "document_modified")},
                                     p.get("plane") is None and bool((p.get("on_face") or {}).get("body"))
                                     and p.get("document_modified") is True
                                     and "reads modified after it" in (p.get("note") or "")
                                     and "timeline_marker_unrestored" not in p), None))
    rows.append(("doc_get", {}, _modified_reads(name, True), None))
    rows.append(("design_get", {"include": ["timeline"], "max_results": 1000},
                 lambda p: _measured("history back at its end", p.get("timeline"),
                                     (p.get("timeline") or {}).get("count") == 4
                                     and (p.get("timeline") or {}).get("marker_position") == 4), None))
    write("doc_activate", lambda c: {"name": _ctx_get(c, "roll_home", "home")})
    rows.append(("doc_close", lambda c: {"name": _ctx_get(c, "roll_doc", "roll scratch"),
                 "save_changes": False, "expect_document": _ctx_get(c, "roll_home", "home")}, _document_closed, None))
    rows += _released_then_deleted(name, "roll")
    return rows

# --- ACT 11a: THE DATA MODEL -------------------------------------------------------------------
# A folder tree of this run's own, one file uploaded into it, moved, read, downloaded - and then
# every one of them taken back out, each delete proven by its own read-back and by the project tree
# read afterwards, which is the witness standing apart from what the deletes reported.
_CLOUD_DATA = [
    # the address the tier comes home to at the end of every act - read, never assumed. A full
    # program hands it the story document; a partial run gets whatever was open, which the tier
    # reads and returns to and never writes.
    ("doc_get", {}, _home_document, ("home_doc", _recall("home_doc", _home_address))),
    ("data_get", {}, _hub_is(HUB, PROJECT), None),
    ("data_create_folder", {"folder_name": RUN_FOLDER, "project": PROJECT,
                            "parent_folder": FOLDER},
     _folder_created(RUN_FOLDER, FOLDER),
     ("run_folder_id", _recall("run_folder_id", lambda p: p["id"]))),
    ("data_create_folder", {"folder_name": MOVED_FOLDER, "project": PROJECT,
                            "parent_folder": RUN_PATH},
     _folder_created(MOVED_FOLDER, RUN_PATH),
     ("moved_folder_id", _recall("moved_folder_id", lambda p: p["id"]))),
    ("data_get", {"project": PROJECT, "include": ["summary"]}, _root_summary,
     ("data_root_summary", _recall("data_root_summary", _root_summary_facts))),
    ("data_get", lambda c: {
        "project": "ignored-when-project-id-is-present",
        "project_id": _ctx_get(c, "data_root_summary", "the project root")["project_id"],
        "include": ["summary"]},
     _same_root_summary, None),
    ("data_upload_file", _upload_args,
     _upload_started(RUN_PATH), ("upload_handle", lambda p: p["upload_handle"])),
    # The runner supplies the terminal response to the predicate and saved-value extractor.
    ("data_get_upload_status", _upload_status_args,
     _upload_complete, ("cloud_file", _recall("cloud_file", lambda p: p["file_id"]))),
    ("data_get", {"project": PROJECT, "folder": RUN_PATH, "recursive": False},
     _known_file_listing(RUN_PATH, RUN_PATH, False), None),
    # The marker is an IMAGE: its record's is_complete read False 25 minutes after the upload
    # status above read 'complete' with a lineage (measured), so the record is judged by where it
    # sits and the flag is read, not waited on - the status row is what says the file landed.
    ("data_get", lambda c: {"file": _ctx_get(c, "cloud_file", "the uploaded file")},
     _file_record(RUN_PATH, complete=None), ("cloud_file_name", lambda p: p["file"]["name"])),
    ("data_get", {"project": PROJECT, "recursive": False}, _root_files,
     ("data_root_files", _recall("data_root_files", _root_file_ids))),
    ("data_get", {"project": PROJECT, "folder": "/", "recursive": False},
     _same_root_files, None),
    ("data_get", {"project": PROJECT, "folder": "\\", "recursive": False},
     _same_root_files, None),
    ("data_get", {"project": PROJECT, "folder": RUN_PATH, "include": ["summary"]},
     _folder_summary(RUN_PATH, "run_folder_id", 1, 1), None),
    ("sys_execute_script", _capped_name_move_probe, _capped_name_move_result, None),
    ("sys_execute_script", _duplicate_project_probe, _duplicate_project_result, None),
    ("doc_get", {}, _home_document, ("hub_probe_census", _recall("hub_probe_census", lambda p: p))),
    ("sys_execute_script", _duplicate_hub_probe, _duplicate_hub_result, None),
    ("doc_get", {}, lambda p: _measured("the open documents are unchanged by the hub probe",
                                        p.get("active"), p == _RECALL.get("hub_probe_census")), None),
    ("data_get", {"include": ["hubs"]}, _hubs_untouched, None),
    ("data_get", lambda c: {"file": _ctx_get(c, "cloud_file", "the uploaded file")},
     _file_record(RUN_PATH, complete=None), None),
    ("data_get", {"project": PROJECT, "folder": MOVED_PATH, "include": ["summary"]},
     _folder_summary(MOVED_PATH, "moved_folder_id", 0, 0), None),
    ("data_move_file", lambda c: {"file": _ctx_get(c, "cloud_file", "the uploaded file"),
                                  "project": PROJECT, "target_folder": MOVED_PATH},
     _moved_to(MOVED_PATH), None),
    ("data_get", {"project": PROJECT, "folder": RUN_PATH, "recursive": False},
     _known_child_excluded, None),
    ("data_get", {"project": PROJECT, "folder": RUN_PATH, "recursive": True},
     _known_file_listing(RUN_PATH, MOVED_PATH, True), None),
    ("doc_get", {}, _home_document,
     ("cloud_boolean_census", _recall("cloud_boolean_census", lambda p: p))),
    ("data_download_file", _download_boolean_args,
     _refused("Invalid Boolean for 'overwrite'", "'false'", "Use true or false."), None),
    ("doc_get", {}, lambda p: _cloud_boolean_unchanged(p, download=True), None),
    ("data_download_file", _download_refusal_args,
     _refused(DOWNLOAD_FILE, "overwrite=true"), None),
    ("data_download_file", _download_overwrite_args, _downloaded, None),
    # THE GUARDED DELETE, met before the emptying ones: a folder still holding a subtree is refused,
    # so the recursive path is proven without ever running here. The fragments are the BLAST RADIUS
    # the guard measured at this moment - the run folder holds no file of its own and one subfolder,
    # and one file and one subfolder in the subtree below it - so a preview that under-counts what a
    # wipe would take reds here rather than reading as the same refusal.
    ("data_delete_folder", lambda c: _dependent_folder_args(c, "run_folder_id", RUN_FOLDER),
     _refused("is not empty", "immediate files: 0, subfolders: 1",
              "1 file(s) and 1 subfolder(s) total", "recursive_confirm"), None),
    ("data_delete_file", {"document_id": "urn:adsk.wipprod:dm.lineage:BOOLEAN-GUARD-NONEXISTENT",
                          "force": "false", "expect_document": "session:BOOLEAN-GUARD-MISMATCH"},
     _refused("Invalid Boolean for 'force'", "'false'", "Use true or false."), None),
    ("doc_get", {}, _cloud_boolean_unchanged, None),
    ("data_get", lambda c: {"file": _ctx_get(c, "cloud_file", "the uploaded file")},
     _file_record(MOVED_PATH, complete=None), None),
    ("data_delete_file", lambda c: {"document_id": _ctx_get(c, "cloud_file", "the uploaded file"),
                                    "confirm_name": _ctx_get(c, "cloud_file_name", "its name")},
     _file_deleted, None),
    # the typed re-resolve, apart from the delete's own absence read
    ("data_get", lambda c: {"file": _ctx_get(c, "cloud_file", "the uploaded file")},
     _refused("No cloud file resolves from"), None),
    ("data_delete_folder", lambda c: _dependent_folder_args(c, "moved_folder_id", MOVED_FOLDER),
     _folder_deleted(MOVED_FOLDER), None),
    ("data_delete_folder", lambda c: _dependent_folder_args(c, "run_folder_id", RUN_FOLDER),
     _folder_deleted(RUN_FOLDER), None),
    # THE DELETE RECEIPT, standing apart from what the delete calls reported about themselves: the
    # run folder is addressed DIRECTLY and the project answers that it has no such subfolder. A
    # scoped miss is a refusal, so it cannot be confused with a walk that ran out of budget - which a
    # project-wide folder-tree read is, measured, on every run against a real project. Moved sat
    # inside the run folder, so a run folder that no longer resolves is both of them gone.
    ("data_get", {"project": PROJECT, "folder": RUN_PATH, "include": ["summary"]},
     _refused("not found", "no subfolder", RUN_FOLDER), None),
]


# A DERIVE link's refresh, read after the source moved on and the host was closed and REOPENED.
# A derive is a one-way linked copy bound to the source's saved version. MEASURED by hand on a
# stale one: both refresh routes raise "2 : InternalValidationError : res" and isOutOfDate stays
# true, so doc_update_xref refuses and names delete-and-re-derive as the remedy. This leg is that
# measurement on a run - the rig wants a cloud save, a close and a reopen, none of which a
# measure_api row can build on the main thread.
_CLOUD_DERIVE = _derive_selector_rows() + [
    ("doc_new", {}, _new_document, None),
    ("doc_insert_derive", lambda c: {"document_id": _ctx_get(c, "source_urn", "the source")},
     _derived(SOURCE_DOC), None),
    ("doc_save_as", {"name": DERIVE_DOC, "project": PROJECT, "folder": FOLDER},
     _saved_as(DERIVE_DOC, FOLDER), None),
] + _settled(DERIVE_DOC, "derive_urn") + [
    # the source moves past the version the derive holds. The edit ADDS a parameter rather than
    # re-valuing one: MEASURED on this rig, a source whose existing parameter changed value saves a
    # new version and the derive still reads 'already up to date', while a source that gained a new
    # parameter reads out of date - a new version alone does not stale a derive link. The same
    # save restores the 10 mm fixture the rows after this leg read at z=10, so this reopened
    # session uploads once here, not twice.
    ("doc_activate", lambda c: {"name": _ctx_get(c, "source_urn", "the source")},
     _activated(SOURCE_DOC), None),
    # the tip BEFORE the save, so the row below compares against a number this run read rather than
    # a count of the saves the act has made.
    ("doc_get", {"include": ["default", "versions"]}, _tip_read,
     ("source_tip_before", _recall("source_tip_before",
                                   lambda p: p["versions"]["latest_version_number"]))),
    ("param_set", {"name": "CloudPlateH", "expression": "10 mm"}, "ok", None),
    ("param_add", {"name": "CloudDeriveMark", "expression": "3 mm"}, "ok", None),
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the downstream reset plate", 10.0), None),
    ("data_get", _version_args("derive_save_before"),
     _version_snapshot("derive_save_before"), ("derive_save_before", _recall("derive_save_before", _version_record))),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _file_settled(FOLDER), None),
    ("doc_save", {"description": "the 10 mm fixture restored, and the edit the derive link goes stale against"},
     _versioned(SOURCE_DOC), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _version_settled("derive_save_before"), None),
    _dwell(_TIP_SETTLE_S),
    ("doc_get", {"include": ["default", "versions"]}, _tip_advanced("source_tip_before"), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _file_settled(FOLDER), None),
    # CLOSED and REOPENED once the cloud is publishing the new version: the hand measurement was
    # taken on a reference the session had reloaded, not on one held open since the derive landed.
    ("doc_close", lambda c: {"name": _ctx_get(c, "derive_urn", "the derive host"),
                             "save_changes": False}, _document_closed, None),
    _dwell(6.0),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "derive_urn", "the derive host"),
                            "force_api_open": True},
     _opened(DERIVE_DOC, lambda: _RECALL.get("derive_urn")), None),
    _dwell(3.0),
    ("doc_get", {}, _document_is(DERIVE_DOC), None),
    # doc_update_xref assigns the version on a derive row and CATCHES Fusion's refusal, so the call
    # errors naming the row and the remedy rather than reporting a refresh it did not do. A row that
    # read CURRENT here would be skipped and the call would answer ok - which is why this asserts the
    # refusal rather than a bucket count.
    ("doc_update_xref", {"only_out_of_date": True},
     _refused("Some references failed to update", "Fusion refused the refresh",
              "doc_insert_derive"), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "derive_urn", "the derive host"),
                             "save_changes": False}, _document_closed, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "source_urn", "the source")},
     _activated(SOURCE_DOC), None),
    _dwell(6.0),
    ("data_delete_file", lambda c: {"document_id": _ctx_get(c, "derive_urn", "the derive host"),
                                    "confirm_name": DERIVE_DOC}, _file_deleted, None),
]


# This xref motion-link scenario is quarantined pending a separate owner-approved crash review.
# If separately enabled in source, the act owns and removes its cloud file and restores the captured
# home document before its boundary.
_CLOUD_LINK = [
    ("doc_new", {}, _new_document, None),
    ("doc_insert_occurrence",
     lambda c: {"document_id": _ctx_get(c, "source_urn", "the source"), "x": _LINK_X[0]},
     _inserted(SOURCE_DOC), None),
    ("doc_insert_occurrence",
     lambda c: {"document_id": _ctx_get(c, "source_urn", "the source"), "x": _LINK_X[1]},
     _inserted(SOURCE_DOC), None),
    ("doc_insert_occurrence",
     lambda c: {"document_id": _ctx_get(c, "source_urn", "the source"), "x": _LINK_X[2]},
     _inserted(SOURCE_DOC), None),
    # one face per instance, taken design-wide and told apart by WHERE IT SITS and which way it
    # faces: nearest_to answers with the nearest face whether or not it is the one meant, so each
    # row asserts the centroid it expects and an outward +Z normal. The joints are built at HANDLES
    # because all three instances answer to the one stamped document name.
    ("find_geometry", _lit({"kind": "planar_face", "max_results": 1,
                            "nearest_to": [_LINK_X[0] + _PLATE_MID_X, _PLATE_MID_Y, _PLATE_TOP_Z]}),
     _face_up_at(_LINK_X[0] + _PLATE_MID_X, _PLATE_MID_Y, _PLATE_TOP_Z), _fg("link_face_a")),
    ("find_geometry", _lit({"kind": "planar_face", "max_results": 1,
                            "nearest_to": [_LINK_X[1] + _PLATE_MID_X, _PLATE_MID_Y, _PLATE_TOP_Z]}),
     _face_up_at(_LINK_X[1] + _PLATE_MID_X, _PLATE_MID_Y, _PLATE_TOP_Z), _fg("link_face_b")),
    ("find_geometry", _lit({"kind": "planar_face", "max_results": 1,
                            "nearest_to": [_LINK_X[2] + _PLATE_MID_X, _PLATE_MID_Y, _PLATE_TOP_Z]}),
     _face_up_at(_LINK_X[2] + _PLATE_MID_X, _PLATE_MID_Y, _PLATE_TOP_Z), _fg("link_face_c")),
    # two sliders CHAINED through the middle instance: different pairs, so neither meets Fusion's
    # already-jointed-pair refusal, and the chain keeps two degrees of freedom for the link to
    # couple. Both anchor on the top faces - one face serving two pairs is not a second joint on
    # one pair.
    ("joint_create", lambda c: {"occurrence_one": _ctx_get(c, "link_face_a", "the first plate"),
                                "occurrence_two": _ctx_get(c, "link_face_b", "the second plate"),
                                "joint_type": "slider", "axis": "x", "name": "XrefSlideA"},
     _jointed("XrefSlideA"), None),
    ("joint_create", lambda c: {"occurrence_one": _ctx_get(c, "link_face_b", "the second plate"),
                                "occurrence_two": _ctx_get(c, "link_face_c", "the third plate"),
                                "joint_type": "slider", "axis": "x", "name": "XrefSlideB"},
     _jointed("XrefSlideB"), None),
    ("joint_motion_link", {"joint_one": "XrefSlideA", "joint_two": "XrefSlideB", "ratio": 1},
     _motion_linked("XrefSlideA", "XrefSlideB", False), None),
    ("joint_drive", {"joint_name": "XrefSlideA", "distance": 5}, _driven_slide(5), None),
    # the save that re-keys: an unsaved document keys by the token minted on first sight, and this
    # save moves that key onto the file's own id.
    ("doc_save_as", {"name": LINK_DOC, "project": PROJECT, "folder": FOLDER},
     _saved_as(LINK_DOC, FOLDER), None),
] + _settled(LINK_DOC, "link_urn") + [
    # THE REFUSAL, on the other member. What is asserted is the guard's three readings - the link,
    # the partner already driven, and the pair not reading as wholly native. Whether the first
    # drive moved THIS joint through the link is something joint_drive says it does not read, so
    # nothing here claims it either way.
    ("joint_drive", {"joint_name": "XrefSlideB", "distance": 5},
     _refused("'XrefSlideB' is motion-linked to 'XrefSlideA'", "already driven this session",
              "did NOT read as wholly native"), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "link_urn", "the link assembly"),
                             "save_changes": False}, _document_closed, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "source_urn", "the source")},
     _activated(SOURCE_DOC), None),
    _dwell(6.0),
    ("data_delete_file", lambda c: {"document_id": _ctx_get(c, "link_urn", "the link assembly"),
                                    "confirm_name": LINK_DOC}, _file_deleted, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "home_doc", "the home document")},
     _activated(), None),
]


# --- ACT 11b: THE SAVED DOCUMENT ---------------------------------------------------------------
# A small plate built in a document of its own, saved into the configured folder, versioned,
# milestoned, rolled back, copied, and inserted as an xref into a host saved beside it. The SOURCE is
# left standing - the drawing act generates from it and deletes it; the copy and the host are this
# act's own and go at the end of it.
_CLOUD_DOC = _fit_refusal_rows() + _sketch_roll_dirty_rows() + _named_derive_rows() + [
    ("doc_new", {}, _new_document, None),
    ("model_create_component", {"name": SRC_COMP, "activate": True}, _made_component, None),
    ("sketch_create", {"plane": "xy", "name": SRC_SKETCH}, "ok", None),
    ("sketch_add_geometry", _lit({"geometry": [{"kind": "rectangle", "x1": 0, "y1": 0,
                                                "x2": 80, "y2": 50}],
                                  "sketch_name": SRC_SKETCH}), "ok", None),
    ("param_add", {"name": "CloudPlateH", "expression": "10 mm"}, "ok", None),
    ("model_extrude", _lit({"sketch_name": SRC_SKETCH, "profile_index": 0,
                             "distance": "CloudPlateH"}), _extruded, None),
    _watch(SRC_COMP + ":1"),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the unsaved source plate", 10.0), None),
    ("doc_save_as", {"name": SOURCE_DOC, "project": PROJECT, "folder": FOLDER},
     _saved_as(SOURCE_DOC, FOLDER), None),
    # the lineage URN read off the SESSION rather than off the save: doc_save_as waits for the urn
    # before it answers, and this read is where the tier refuses a local path in its place.
] + _settled(SOURCE_DOC, "source_urn") + [
    # A fit_to shot on the just-saved source: the flag reads clear before it, the shot says its
    # isolate set it, and doc_get reads it set; the doc_save below clears it with the 14 mm edit.
    ("doc_get", {}, _modified_reads(SOURCE_DOC, False), None),
    ("view_screenshot", {"fit_to": SRC_COMP + ":1", "width": 300, "height": 240},
     _fit_to_modified_disclosed, None),
    ("doc_get", {}, _modified_reads(SOURCE_DOC, True), None),
    ("param_set", {"name": "CloudPlateH", "expression": "14 mm"}, "ok", None),
    ("doc_get", {}, _modified_reads(SOURCE_DOC, True),
     ("hub_edit_census", _recall("hub_edit_census", lambda p: p))),
    ("sys_execute_script", _hub_edit_preflight_probe, _hub_edit_preflight_result, None),
    ("doc_get", {}, lambda p: _measured("hub preflight preserved the complete session census", p,
                                      p == _RECALL.get("hub_edit_census")), None),
    ("data_get", {"include": ["hubs"]}, _hubs_untouched, None),
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the changed unsaved plate", 14.0), None),
    ("doc_get", {"include": ["default", "versions"]}, _tip_read,
     ("plate_tip_before", _recall("plate_tip_before",
                                  lambda p: p["versions"]["latest_version_number"]))),
    ("data_get", _version_args("plate_save_before"),
     _version_snapshot("plate_save_before"), ("plate_save_before", _recall("plate_save_before", _version_record))),
    ("doc_save", {"description": "the cloud tier's first changed version"},
     _versioned(SOURCE_DOC), None),
    # the cloud's version metadata lags the save (measured ~20 s; burn95 read number 1 straight
    # after a save that landed version 2), so the settled read waits the same tip settle first
    _dwell(_TIP_SETTLE_S),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _version_settled("plate_save_before"), None),
    ("doc_get", {"include": ["default", "versions"]}, _tip_advanced("plate_tip_before"), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _file_settled(FOLDER), None),
    # view_set on the saved source: the flag reads clear, the isolate reports setting it, and the
    # clear that follows finds it already set and claims nothing.
    ("doc_get", {}, _modified_reads(SOURCE_DOC, False), None),
    ("view_set", {"action": "isolate", "target": SRC_COMP + ":1"},
     lambda p: _measured("the isolate reports turning the saved source modified",
                         {k: p.get(k) for k in ("document_modified", "modified_by_this_call")},
                         p.get("document_modified") is True
                         and p.get("modified_by_this_call") is True), None),
    ("doc_get", {}, _modified_reads(SOURCE_DOC, True), None),
    ("view_set", {"action": "clear_isolation"},
     lambda p: _measured("the clear finds the source already modified",
                         {k: p.get(k) for k in ("cleared_count", "document_modified",
                                                "modified_by_this_call")},
                         p.get("cleared_count") == 1 and p.get("document_modified") is True
                         and "modified_by_this_call" not in p), None),
    ("param_set", {"name": "CloudPlateH", "expression": "16 mm"}, "ok", None),
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the milestone source plate", 16.0), None),
    ("doc_save_milestone", _milestone_args,
     _milestoned("SweepCloudMilestone", SOURCE_DOC), None),
    ("doc_get", {"include": ["default", "versions"], "versions_max": 10}, _versions_read(3),
     ("milestone_history", lambda p: p)),
    ("doc_get", _restore_selector_baseline, _versions_read(3), None),
] + _selector_reads(_RESTORE_SELECTOR_READS) + [
    ("doc_restore_version", _restore_conflict,
     _refused("No version matching", "and id", "matching number/id"), None),
] + _selector_reads(_RESTORE_SELECTOR_READS, True) + [
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the refused restore leaves the milestone plate", 16.0), None),
    ("doc_restore_version", _milestone_restore_args, _restored(RESTORE_VERSION),
     ("milestone_restored", lambda p: p)),
    _dwell(_TIP_SETTLE_S),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "home_doc", "the home document")},
     _activated(), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "source_urn", "the source"),
                              "save_changes": False}, _document_closed, None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "source_urn", "the source"),
                             "force_api_open": True},
     _opened(SOURCE_DOC, lambda: _RECALL.get("source_urn")), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _file_settled(FOLDER), None),
    _dwell(3.0),
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the restored source plate", 10.0), None),
    ("doc_copy", _milestone_copy_args, _copied(SOURCE_DOC, COPY_DOC, FOLDER),
     ("copy_urn", _recall("copy_urn", lambda p: p["copied_id"]))),
    # THE HOST, saved before anything is put in it so it has a lineage URN of its own - every switch
    # and every delete below addresses a document by URN, which an unsaved one does not have.
    ("doc_new", {}, _new_document, None),
    ("doc_save_as", {"name": HOST_DOC, "project": PROJECT, "folder": FOLDER},
     _saved_as(HOST_DOC, FOLDER), None),
] + _settled(HOST_DOC, "host_urn") + [
    ("doc_insert_occurrence", lambda c: {"document_id": _ctx_get(c, "source_urn", "the source")},
     _inserted(SOURCE_DOC), None),
    # THE FIRST WALK, straight after the insert: one reference, in whichever bucket the cloud's
    # version stream leaves it. MEASURED: an xref inserted moments earlier came back was_out_of_date
    # true at version 2 while the source had reached 3, so 'already current on insert' is not a thing
    # this act can assert - it reports which bucket, and brings the reference current.
    ("doc_update_xref", {"only_out_of_date": True}, _xrefs(1), None),
    # THE SKIP, deterministic because the walk above just brought that reference current: nothing is
    # out of date, so only_out_of_date leaves it alone rather than refreshing it again.
    ("doc_update_xref", {"only_out_of_date": True}, _xrefs(1, 0, 1), None),
    # ...then the source is edited and versioned, and the same walk finds the reference stale. The
    # two rows above and this one put a row in each bucket, which is what makes the partition a
    # measurement rather than a shape.
    ("doc_activate", lambda c: {"name": _ctx_get(c, "source_urn", "the source")},
     _activated(SOURCE_DOC), None),
    ("param_set", {"name": "CloudPlateH", "expression": "16 mm"}, "ok", None),
    ("data_get", _version_args("host_save_before"),
     _version_snapshot("host_save_before"), ("host_save_before", _recall("host_save_before", _version_record))),
    ("doc_save", {"description": "the edit the host's reference refresh is read against"},
     _versioned(SOURCE_DOC), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _version_settled("host_save_before"), None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "host_urn", "the host")},
     _activated(HOST_DOC), None),
    # doc_activate's own switch is ASYNC - it reports 'pending' where the foreground has not caught
    # up, and its note says to confirm with doc_get before acting on the new document. The walk below
    # reads THE ACTIVE document's references, so an unconfirmed switch does not fail it: it reads
    # some other document's, which is how a walk aimed at the host reported no references at all.
    ("doc_get", {}, _document_is(HOST_DOC), None),
    ("doc_update_xref", {"only_out_of_date": True}, _xrefs(1, 1, 0), None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "copy_urn", "the copy"),
                            "force_api_open": True},
     _opened(COPY_DOC, lambda: _RECALL.get("copy_urn")), None),
    _dwell(3.0),
    ("doc_get", {}, _document_is(COPY_DOC), None),
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the copied plate"), None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "source_urn", "the source")},
     _activated(SOURCE_DOC), None),
    # The dotted native display name is refused by its DataFile type before download, which sends a
    # caller to design_export - the branch the PNG round trip in the data act cannot reach.
    ("data_download_file", lambda c: {"file": _ctx_get(c, "source_urn", "the source"),
                                      "destination_folder": DOWNLOAD_DIR},
     _refused("Fusion-native", "design_export"), None),
] + _CLOUD_DERIVE + [
    # TEARDOWN of this act's own two. The host goes first: it REFERENCES the source, and a referenced
    # file's delete is refused rather than orphaning what points at it.
    ("doc_close", lambda c: {"name": _ctx_get(c, "host_urn", "the host"), "save_changes": False},
     _document_closed, None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "copy_urn", "the copy"), "save_changes": False},
     _document_closed, None),
    # a delete taken on a just-closed file has been observed to raise until the close settles cloud
    # side, so the hold is here rather than a retry - a delete that still refuses is reported.
    _dwell(6.0),
    ("data_delete_file", lambda c: {"document_id": _ctx_get(c, "host_urn", "the host"),
                                    "confirm_name": HOST_DOC}, _file_deleted, None),
    ("data_delete_file", lambda c: {"document_id": _ctx_get(c, "copy_urn", "the copy"),
                                    "confirm_name": COPY_DOC}, _file_deleted, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "home_doc", "the home document")},
     _activated(), None),
]


# --- ACT 11c: THE DRAWING ----------------------------------------------------------------------
# The drawing generated from the saved source, edited, exported, refreshed against a source edit and
# exported again - then the source and its drawing taken back out, and the session left on the
# document the tier started on.
_CLOUD_DRAWING = [
    ("doc_activate", lambda c: {"name": _ctx_get(c, "source_urn", "the source")},
     _activated(SOURCE_DOC), None),
    ("doc_get", _drawing_persistence_start,
     lambda p: _document_is(SOURCE_DOC)(p) and _home_document(p),
     ("drawing_persist_source", _recall("drawing_persist_source", _home_address))),
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the 80 x 50 x 10 mm drawing source", 10.0), None),
    # the generator reads its source from the CLOUD, so the file's own record - is_complete among it
    # - is polled to settled first, and a create refusing behind a source still processing is
    # diagnosed by this row rather than by a retry.
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _file_settled(FOLDER), None),
    ("drawing_create", {"standard": "iso", "units": "mm", "sheet_size": "a3",
                        "orientation": "landscape", "content": "full", "sheet_scope": "all_levels",
                        "sheet_types": ["component"], "auto_dimension": "off", "parts_list": False,
                        "omit_fasteners": False, "creation_mode": "automatic"},
     _drawing_created,
     ("drawing", _recall("drawing", lambda p: [p["file_id"], p["drawing_name"]]))),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "drawing", "the drawing")[0],
                            "force_api_open": True},
     _opened(lambda: _RECALL.get("drawing", [None, None])[1],
             lambda: _RECALL.get("drawing", [None, None])[0]),
     ("drawing_persist_opened", _recall("drawing_persist_opened", lambda p: p["document_handle"]))),
    _dwell(4.0),
    # THE SHEET READ that answers - taken before the writes below, and again before each export.
    ("drawing_get", {}, _sheets_answer, None),
    ("drawing_get", {"include": ["tables"]}, _drawing_tables_answer, None),
    ("drawing_update", {}, _drawing_current, None),
    ("doc_get", {}, _drawing_persistence_document("drawing_persist_opened"), None),
    ("drawing_get", {"include": ["views"]}, _drawing_persistence_sheets,
     ("drawing_persist_sheets", _recall("drawing_persist_sheets", _drawing_persistence_sheet_values))),
    ("drawing_export", _drawing_invalid_export_args, _drawing_invalid_export_started,
     ("drawing_persist_invalid_job", _recall("drawing_persist_invalid_job", lambda p: p["job_id"]))),
    ("drawing_get_status", _drawing_invalid_status_args, _drawing_invalid_export_failed, None),
    ("drawing_get", {"include": ["views"]}, _drawing_invalid_export_unchanged, None),
    ("drawing_edit_sheet", _drawing_copy_args, _drawing_copy_verified, None),
    ("drawing_get", {"include": ["views"]}, _drawing_named_sheets, None),
    ("drawing_export", _drawing_persistence_pdf_args(_DRAWING_NAMED_BEFORE_PDF),
     _drawing_persistence_pdf(_DRAWING_NAMED_BEFORE_PDF),
     ("drawing_persist_named_before_pdf", _recall("drawing_persist_named_before_pdf",
      _drawing_pdf_record))),
    ("drawing_dimension", lambda c: _drawing_overall_args(c, 0),
     lambda p: _drawing_overall_requested(0)(p) and _auto_note_states_counts(p),
     ("drawing_persist_auto", _recall("drawing_persist_auto", lambda p: p["dimension_count_after"]))),
    # Independent: drawing_get's own count of the original sheet equals the count the note states.
    ("drawing_get", lambda c: {"sheet": _drawing_original_sheet(c)["name"]},
     lambda p: _measured("drawing_get reads the count the auto run reported",
                         [s.get("dimension_count") for s in p.get("sheets") or []],
                         [s.get("dimension_count") for s in p.get("sheets") or []]
                         == [_RECALL.get("drawing_persist_auto")]), None),
    # 'overall' on projected view 1 after the base view's overall lands NO new dimension while
    # autoDimension answers true; the count gate refuses it - the false success DRAW-1 named.
    ("drawing_dimension", lambda c: _drawing_overall_args(c, 1),
     _refused("autoDimension returned true", "no added dimension is confirmed"), None),
    # The manual route on the plate's base view: its curve points read, an angular, a linear and
    # an aligned dimension placed from them, each judged by the sheet's count and the kind its new
    # item reads, then that count read back.
    ("drawing_get", _drawing_curves_args, _drawing_curves_listed,
     ("drawing_persist_curves", _drawing_curves_record)),
    ("drawing_dimension", _drawing_angular_args, _drawing_dimension_added("angular"),
     ("drawing_persist_dims", _recall("drawing_persist_dims",
                                      lambda p: p["dimension_count_after"]))),
    ("drawing_dimension", _drawing_linear_args, _drawing_dimension_added("linear"),
     ("drawing_persist_dims", _recall("drawing_persist_dims",
                                      lambda p: p["dimension_count_after"]))),
    ("drawing_dimension", _drawing_aligned_args, _drawing_dimension_added("aligned"),
     ("drawing_persist_dims", _recall("drawing_persist_dims",
                                      lambda p: p["dimension_count_after"]))),
    ("drawing_get", lambda c: {"sheet": _drawing_original_sheet(c)["name"]},
     _drawing_dimension_count_read,
     ("drawing_persist_symbols", _recall("drawing_persist_symbols",
                                         lambda p: p["sheets"][0].get("symbol_count")))),
    # GD&T on the same corner of the ISO drawing: a datum A, a parallelism frame referencing it,
    # an edge symbol and a taper/slope between the two lines - each judged by the sheet's count
    # and the kind its returned symbol reads - then that count read back.
    ("drawing_add_symbol", _drawing_symbol_args("datum_identifier"),
     _drawing_symbol_added("datum_identifier"),
     ("drawing_persist_symbols", _recall("drawing_persist_symbols",
                                         lambda p: p["symbol_count_after"]))),
    ("drawing_add_symbol", _drawing_symbol_args("feature_control_frame"),
     _drawing_symbol_added("feature_control_frame"),
     ("drawing_persist_symbols", _recall("drawing_persist_symbols",
                                         lambda p: p["symbol_count_after"]))),
    ("drawing_add_symbol", _drawing_symbol_args("edge"), _drawing_symbol_added("edge"),
     ("drawing_persist_symbols", _recall("drawing_persist_symbols",
                                         lambda p: p["symbol_count_after"]))),
    ("drawing_add_symbol", _drawing_symbol_args("taper_slope"),
     _drawing_symbol_added("taper_slope"),
     ("drawing_persist_symbols", _recall("drawing_persist_symbols",
                                         lambda p: p["symbol_count_after"]))),
    ("drawing_get", lambda c: {"sheet": _drawing_original_sheet(c)["name"]},
     _drawing_symbol_count_read, None),
    # The revision table: added fresh (no table exists yet on the original sheet), then edited
    # through a partial update, a refused delete of the header row, hide/show and a real delete,
    # each judged by the returned row census.
    ("drawing_edit_revisions", _drawing_revision_args(
        "add", rows=["A|INITIAL RELEASE|27 Sep 2026", "B|SLOT WIDENED|27 Sep 2026|PM|C3"]),
     _drawing_revisions_added, None),
    ("drawing_get", lambda c: {"sheet": _drawing_original_sheet(c)["name"], "include": ["revisions", "views"]},
     "ok", ("drawing_revision_before", _recall("drawing_revision_before", _drawing_revision_census))),
    ("drawing_edit_revisions", _drawing_revision_args(
        "update", index=3, row="B|MUST NOT LAND|27 Sep 2026||C3"),
     _refused("Cannot clear row 3", "approved", "Nothing changed", "Omit trailing fields"), None),
    ("drawing_get", lambda c: {"sheet": _drawing_original_sheet(c)["name"], "include": ["revisions", "views"]},
     _drawing_revision_read(), None),
    ("drawing_edit_revisions", _drawing_revision_args(
        "update", index=3, row="B||27 Sep 2026|MUST NOT LAND|C3"),
     _refused("Cannot clear row 3", "description", "Nothing changed", "Omit trailing fields"), None),
    ("drawing_get", lambda c: {"sheet": _drawing_original_sheet(c)["name"], "include": ["revisions", "views"]},
     _drawing_revision_read(), None),
    ("drawing_edit_revisions", _drawing_revision_args(
        "update", index=2, row="A|INITIAL RELEASE|27 Sep 2026||"), "ok", None),
    ("drawing_get", lambda c: {"sheet": _drawing_original_sheet(c)["name"], "include": ["revisions", "views"]},
     _drawing_revision_read(), None),
    ("drawing_edit_revisions", _drawing_revision_args(
        "update", index=3, row=f"B|{_REVISION_UPDATE_TEXT}"),
     _drawing_revision_updated, None),
    ("drawing_get", lambda c: {"sheet": _drawing_original_sheet(c)["name"], "include": ["revisions", "views"]},
     _drawing_revision_read(True), None),
    ("drawing_edit_revisions", _drawing_revision_args("delete", index=1),
     _refused("row 1 still reads", "title/header"), None),
    ("drawing_edit_revisions", _drawing_revision_args("hide", index=2),
     _drawing_revision_hidden, None),
    ("drawing_edit_revisions", _drawing_revision_args("show", index=2),
     _drawing_revision_shown, None),
    ("drawing_edit_revisions", _drawing_revision_args("delete", index=2),
     _drawing_revision_deleted, None),
    ("drawing_get", lambda c: {"sheet": _drawing_original_sheet(c)["name"],
                               "include": ["revisions"]},
     _drawing_revision_count_read, None),
    ("drawing_get", {"include": ["views"]}, _drawing_named_sheets, None),
    ("drawing_export", _drawing_persistence_pdf_args(_DRAWING_NAMED_AFTER_PDF),
     _drawing_persistence_pdf(_DRAWING_NAMED_AFTER_PDF),
     ("drawing_persist_named_after_pdf", _recall("drawing_persist_named_after_pdf",
      _drawing_pdf_record))),
    ("drawing_edit_sheet", _drawing_delete_copy_args, _drawing_copy_delete_requested, None),
    ("drawing_get", {"include": ["views"]}, _drawing_original_settled, None),
    ("drawing_export", _drawing_persistence_pdf_args(_DRAWING_BEFORE_PDF),
     _drawing_persistence_pdf(_DRAWING_BEFORE_PDF),
     ("drawing_persist_before_pdf", _recall("drawing_persist_before_pdf", _drawing_pdf_record))),
    ("data_get", lambda c: _version_args("drawing_persist_save_before")(
        {"source_urn": _ctx_get(c, "drawing", "the drawing")[0]}),
     _drawing_persistence_version_snapshot("drawing_persist_save_before"),
     ("drawing_persist_save_before", _recall("drawing_persist_save_before", _version_record))),
    ("doc_save", lambda c: {"description": "Retain the plate's overall dimensions for drawing persistence",
                            "expect_document": _ctx_get(c, "drawing_persist_opened", "the drawing session")},
     lambda p: _versioned((_RECALL.get("drawing") or [None, None])[1])(p)
     and (p.get("acted_on") or {}).get("document_id") == (_RECALL.get("drawing") or [None])[0], None),
    ("data_get", lambda c: _version_args("drawing_persist_saved")(
        {"source_urn": _ctx_get(c, "drawing", "the drawing")[0]}),
     _version_settled("drawing_persist_save_before"), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "drawing", "the drawing")[0]},
     _drawing_persistence_version,
     ("drawing_persist_saved", _recall("drawing_persist_saved", _version_record))),
    ("doc_get", {}, _drawing_persistence_document("drawing_persist_opened", version=True, clean=True), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "drawing_persist_opened", "the observed drawing session"),
                             "expect_document": c["drawing_persist_opened"], "save_changes": False},
     lambda p: _document_closed(p) and p.get("closed") == [(_RECALL.get("drawing") or [None, None])[1]]
     and p.get("close_unconfirmed") == [], None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "drawing_persist_source", "the original source session")},
     _activated(SOURCE_DOC), None),
    ("doc_get", {"max_results": 1000}, _drawing_persistence_absent, None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "drawing_persist_saved", "the saved drawing version")["version_id"],
                            "force_api_open": True, "expect_document": c["drawing_persist_source"]},
     _drawing_persistence_reopened,
     ("drawing_persist_reopened", _recall("drawing_persist_reopened", lambda p: p["document_handle"]))),
    ("doc_get", {}, _drawing_persistence_document("drawing_persist_reopened", version=True), None),
    ("drawing_get", {"include": ["views"]}, lambda p: _drawing_persistence_sheets(p, compare=True), None),
    ("drawing_export", _drawing_persistence_pdf_args(_DRAWING_AFTER_PDF),
     _drawing_persistence_pdf(_DRAWING_AFTER_PDF),
     ("drawing_persist_after_pdf", _recall("drawing_persist_after_pdf", _drawing_pdf_record))),
    ("data_get", lambda c: _version_args("drawing_persist_saved")(
        {"source_urn": _ctx_get(c, "drawing", "the drawing")[0]}),
     lambda p: _drawing_persistence_version(p, unchanged=True), None),
    ("drawing_edit_sheet", _drawing_copy_args, _drawing_copy_verified, None),
    ("drawing_edit_sheet", _drawing_set_a2_args, _drawing_set_a2, None),
    ("drawing_get", {"include": ["views"]}, _drawing_two_sheets,
     ("drawing_two_sheets", _recall("drawing_two_sheets", _drawing_persistence_sheet_values))),
    ("drawing_export", _drawing_deferred_export_args(
        _DRAWING_TWO_BEFORE_PDF, _DRAWING_TWO_BEFORE_KEY, "drawing_persist_reopened"),
     _drawing_job_started(_DRAWING_TWO_BEFORE_KEY),
     ("drawing_two_before_job", _recall("drawing_two_before_job", lambda p: p["job_id"]))),
    ("drawing_get_status", lambda c: _drawing_status_args(
        c, "drawing_two_before_job", _DRAWING_TWO_BEFORE_KEY),
     _drawing_deferred_pdf_completed("drawing_two_before_job", _DRAWING_TWO_BEFORE_KEY,
                                     "drawing_persist_reopened", _DRAWING_TWO_BEFORE_PDF),
     ("drawing_two_before_pdf", _recall("drawing_two_before_pdf", _drawing_deferred_pdf_record))),
    ("data_get", lambda c: _version_args("drawing_two_save_before")(
        {"source_urn": _ctx_get(c, "drawing", "the drawing")[0]}),
     _drawing_persistence_version_snapshot("drawing_two_save_before"),
     ("drawing_two_save_before", _recall("drawing_two_save_before", _version_record))),
    ("doc_save", lambda c: {"description": "Persist the A3 source and A2 copy",
                            "expect_document": _ctx_get(c, "drawing_persist_reopened", "the drawing session")},
     lambda p: _versioned((_RECALL.get("drawing") or [None, None])[1])(p)
     and (p.get("acted_on") or {}).get("document_id") == (_RECALL.get("drawing") or [None])[0], None),
    ("data_get", lambda c: {"file": _ctx_get(c, "drawing", "the drawing")[0]},
     _version_settled("drawing_two_save_before"), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "drawing", "the drawing")[0]},
     lambda p: _drawing_persistence_version(p, before_key="drawing_two_save_before"),
     ("drawing_two_saved", _recall("drawing_two_saved", _version_record))),
    ("doc_get", {}, _drawing_persistence_document("drawing_persist_reopened", version=True, clean=True,
                                   version_key="drawing_two_saved"), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "drawing_persist_reopened", "the drawing session"),
                             "expect_document": c["drawing_persist_reopened"], "save_changes": False},
     lambda p: _document_closed(p) and p.get("close_unconfirmed") == [], None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "drawing_persist_source", "the source session")},
     _activated(SOURCE_DOC), None),
    ("doc_get", {"max_results": 1000}, lambda p: _drawing_persistence_absent(
        p, "drawing_persist_reopened", "drawing_persist_source", SOURCE_DOC), None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "drawing_two_saved", "the saved drawing")["version_id"],
                            "force_api_open": True, "expect_document": c["drawing_persist_source"]},
     _drawing_persistence_reopened(
        version_key="drawing_two_saved", prior_handle_key="drawing_persist_reopened"),
     ("drawing_two_reopened", _recall("drawing_two_reopened", lambda p: p["document_handle"]))),
    ("doc_get", {}, lambda p: _drawing_persistence_document(
        "drawing_two_reopened", version=True, version_key="drawing_two_saved")(p)
     and _measured("the reopened drawing reads clean", (p.get("active") or {}).get("is_modified"),
                   (p.get("active") or {}).get("is_modified") is False), None),
    ("drawing_get", {"include": ["views", "revisions", "tables"]}, _drawing_dirtied_by_read, None),
    ("doc_get", {}, lambda p: _drawing_persistence_document(
        "drawing_two_reopened", version=True, version_key="drawing_two_saved")(p)
     and _measured("the read left the drawing modified", (p.get("active") or {}).get("is_modified"),
                   (p.get("active") or {}).get("is_modified") is True), None),
    ("drawing_get", {"include": ["views"]}, lambda p: _drawing_two_sheets(p, compare=True), None),
    ("drawing_export", _drawing_deferred_export_args(
        _DRAWING_TWO_AFTER_PDF, _DRAWING_TWO_AFTER_KEY, "drawing_two_reopened"),
     _drawing_job_started(_DRAWING_TWO_AFTER_KEY),
     ("drawing_two_after_job", _recall("drawing_two_after_job", lambda p: p["job_id"]))),
    ("drawing_get_status", lambda c: _drawing_status_args(
        c, "drawing_two_after_job", _DRAWING_TWO_AFTER_KEY),
     _drawing_deferred_pdf_completed("drawing_two_after_job", _DRAWING_TWO_AFTER_KEY,
                                     "drawing_two_reopened", _DRAWING_TWO_AFTER_PDF),
     ("drawing_two_after_pdf", _recall("drawing_two_after_pdf", _drawing_deferred_pdf_record))),
    ("data_get", lambda c: {"file": _ctx_get(c, "drawing", "the drawing")[0]},
     lambda p: _drawing_persistence_version(p, unchanged=True,
                                              before_key="drawing_two_save_before",
                                              saved_key="drawing_two_saved"), None),
    ("drawing_add_sketch", {"name": _DRAWING_POPULATED_SKETCH, "geometry": [
        {"kind": "circle", "points": [[450, 300]], "radius": 12},
    ]}, _drawing_circle_landed, None),
    ("drawing_get", {"include": ["views"]}, _drawing_populated_source, None),
    ("drawing_edit_sheet", _drawing_populated_copy_args, _drawing_populated_copy, None),
    ("drawing_get", {"include": ["views"]}, _drawing_populated_sheets,
     ("drawing_populated_sheets", _recall("drawing_populated_sheets", _drawing_persistence_sheet_values))),
    ("drawing_export", _drawing_deferred_export_args(
        _DRAWING_POPULATED_PDF, _DRAWING_POPULATED_KEY, "drawing_two_reopened"),
     _drawing_job_started(_DRAWING_POPULATED_KEY),
     ("drawing_populated_job", _recall("drawing_populated_job", lambda p: p["job_id"]))),
    ("drawing_get_status", lambda c: _drawing_status_args(
        c, "drawing_populated_job", _DRAWING_POPULATED_KEY),
     _drawing_deferred_pdf_completed("drawing_populated_job", _DRAWING_POPULATED_KEY,
                                     "drawing_two_reopened", _DRAWING_POPULATED_PDF),
     ("drawing_populated_pdf", _recall("drawing_populated_pdf", _drawing_deferred_pdf_record))),
    ("drawing_get", {"include": ["views"]}, lambda p: _drawing_populated_sheets(p, compare=True), None),
    # No auto-dimension on a REOPENED, populated drawing: Sheet.autoDimension holds the main
    # thread for minutes there, past the client's read timeout; the auto route is demonstrated
    # on the fresh drawing above.
    ("doc_close", lambda c: {"name": _ctx_get(c, "drawing_two_reopened", "the populated drawing"),
                             "expect_document": c["drawing_two_reopened"], "save_changes": False},
     lambda p: _document_closed(p) and p.get("close_unconfirmed") == [], None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "drawing_persist_source", "the source session")},
     _activated(SOURCE_DOC), None),
    ("doc_get", {"max_results": 1000}, lambda p: _drawing_persistence_absent(
        p, "drawing_two_reopened", "drawing_persist_source", SOURCE_DOC), None),
    ("param_get", {"name": "CloudPlateH"}, _drawing_parameter(10.0), None),
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the drawing source before deferred update", 10.0), None),
    ("param_set", lambda c: {"name": "CloudPlateH", "expression": "12 mm",
                             "expect_document": _ctx_get(c, "drawing_persist_source", "the source session")},
     _drawing_parameter_set(10.0, 12.0), None),
    ("param_get", {"name": "CloudPlateH"}, _drawing_parameter(12.0), None),
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the drawing source after the 12 mm change", 12.0), None),
    ("data_get", _version_args("drawing_source_save_before"),
     _version_snapshot("drawing_source_save_before"),
     ("drawing_source_save_before", _recall("drawing_source_save_before", _version_record))),
    ("doc_save", lambda c: {"description": "Deferred drawing update control: thickness 12 mm",
                            "expect_document": _ctx_get(c, "drawing_persist_source", "the source session")},
     lambda p: _versioned(SOURCE_DOC)(p)
     and (p.get("acted_on") or {}).get("document_id") == _RECALL.get("source_urn"), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _version_settled("drawing_source_save_before"), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _drawing_source_version("drawing_source_save_before"),
     ("drawing_source_changed", _recall("drawing_source_changed", _version_record))),
    ("doc_close", lambda c: {"name": _ctx_get(c, "drawing_persist_source", "the source session"),
                             "expect_document": c["drawing_persist_source"], "save_changes": False},
     lambda p: _document_closed(p) and p.get("close_unconfirmed") == [], None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "home_doc", "the home document")},
     _activated(), None),
    ("doc_get", {"max_results": 1000},
     lambda p: _drawing_persistence_absent(p, "drawing_persist_source", "home_doc", None), None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "drawing_two_saved", "the older drawing")["version_id"],
                            "force_api_open": True, "expect_document": c["home_doc"]},
     _drawing_persistence_reopened(
        version_key="drawing_two_saved", prior_handle_key="drawing_two_reopened"),
     ("drawing_update_opened", _recall("drawing_update_opened", lambda p: p["document_handle"]))),
    ("doc_get", {}, _drawing_persistence_document("drawing_update_opened", version=True, clean=True,
                                   version_key="drawing_two_saved"), None),
    ("drawing_get", {"include": ["views"]}, lambda p: _drawing_two_sheets(p, compare=True), None),
    ("drawing_export", _drawing_deferred_export_args(
        _DRAWING_UPDATE_BEFORE_PDF, _DRAWING_UPDATE_BEFORE_KEY, "drawing_update_opened"),
     _drawing_job_started(_DRAWING_UPDATE_BEFORE_KEY),
     ("drawing_update_before_job", _recall("drawing_update_before_job", lambda p: p["job_id"]))),
    ("drawing_get_status", lambda c: _drawing_status_args(
        c, "drawing_update_before_job", _DRAWING_UPDATE_BEFORE_KEY),
     _drawing_deferred_pdf_completed("drawing_update_before_job", _DRAWING_UPDATE_BEFORE_KEY,
                                     "drawing_update_opened", _DRAWING_UPDATE_BEFORE_PDF),
     ("drawing_update_before_pdf", _recall("drawing_update_before_pdf", _drawing_deferred_pdf_record))),
    ("drawing_update", _drawing_deferred_update_args(_DRAWING_UPDATE_KEY, "drawing_update_opened"),
     _drawing_job_started(_DRAWING_UPDATE_KEY),
     ("drawing_update_job", _recall("drawing_update_job", lambda p: p["job_id"]))),
    ("drawing_get_status", lambda c: _drawing_status_args(c, "drawing_update_job", _DRAWING_UPDATE_KEY),
     _drawing_update_completed("drawing_update_job", _DRAWING_UPDATE_KEY,
                               "drawing_update_opened", "drawing_source_changed"), None),
    ("drawing_update", lambda c: {"expect_document": _ctx_get(c, "drawing_update_opened", "the drawing")},
     _drawing_reference_current("drawing_source_changed"), None),
    ("drawing_get", {"include": ["views"]}, lambda p: _drawing_two_sheets(p, compare=True), None),
    ("drawing_export", _drawing_deferred_export_args(
        _DRAWING_UPDATE_AFTER_PDF, _DRAWING_UPDATE_AFTER_KEY, "drawing_update_opened"),
     _drawing_job_started(_DRAWING_UPDATE_AFTER_KEY),
     ("drawing_update_after_job", _recall("drawing_update_after_job", lambda p: p["job_id"]))),
    ("drawing_get_status", lambda c: _drawing_status_args(
        c, "drawing_update_after_job", _DRAWING_UPDATE_AFTER_KEY),
     _drawing_deferred_pdf_completed("drawing_update_after_job", _DRAWING_UPDATE_AFTER_KEY,
                                     "drawing_update_opened", _DRAWING_UPDATE_AFTER_PDF),
     ("drawing_update_after_pdf", _recall("drawing_update_after_pdf", _drawing_deferred_pdf_record))),
    ("doc_close", lambda c: {"name": _ctx_get(c, "drawing_update_opened", "the updated drawing"),
                             "expect_document": c["drawing_update_opened"], "save_changes": False},
     lambda p: _document_closed(p) and p.get("close_unconfirmed") == [], None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "home_doc", "the home document")},
     _activated(), None),
    ("doc_get", {"max_results": 1000},
     lambda p: _drawing_persistence_absent(p, "drawing_update_opened", "home_doc", None), None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "drawing_source_changed", "the changed source")["version_id"],
                            "force_api_open": True, "expect_document": c["home_doc"]},
     _drawing_source_reopened("drawing_source_changed", "drawing_persist_source"),
     ("drawing_source_restore_session", _recall(
        "drawing_source_restore_session", lambda p: p["document_handle"]))),
    ("doc_get", {}, _drawing_source_document(
        "drawing_source_restore_session", "drawing_source_changed"), None),
    ("param_set", lambda c: {"name": "CloudPlateH", "expression": "10 mm",
                             "expect_document": _ctx_get(c, "drawing_source_restore_session", "the source")},
     _drawing_parameter_set(12.0, 10.0), None),
    ("param_get", {"name": "CloudPlateH"}, _drawing_parameter(10.0), None),
    ("model_inspect", {"include": ["default", "mass"], "units": "mm"},
     _plate_geometry("the restored drawing source", 10.0), None),
    ("data_get", _version_args("drawing_source_restore_before"),
     _version_snapshot("drawing_source_restore_before"),
     ("drawing_source_restore_before", _recall("drawing_source_restore_before", _version_record))),
    ("doc_save", lambda c: {"description": "Restore 10 mm thickness after drawing update control",
                            "expect_document": _ctx_get(c, "drawing_source_restore_session", "the source")},
     lambda p: _versioned(SOURCE_DOC)(p)
     and (p.get("acted_on") or {}).get("document_id") == _RECALL.get("source_urn"), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _version_settled("drawing_source_restore_before"), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _drawing_source_version("drawing_source_restore_before"),
     ("drawing_source_restored", _recall("drawing_source_restored", _version_record))),
    ("doc_close", lambda c: {"name": _ctx_get(c, "drawing_source_restore_session", "the source"),
                             "expect_document": c["drawing_source_restore_session"], "save_changes": False},
     lambda p: _document_closed(p) and p.get("close_unconfirmed") == [], None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "home_doc", "the home document")},
     _activated(), None),
    ("doc_get", {"max_results": 1000},
     lambda p: _drawing_persistence_absent(p, "drawing_source_restore_session", "home_doc", None), None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "drawing_two_saved", "the older drawing")["version_id"],
                            "force_api_open": True, "expect_document": c["home_doc"]},
     _drawing_persistence_reopened(
        version_key="drawing_two_saved", prior_handle_key="drawing_update_opened"),
     ("drawing_restore_opened", _recall("drawing_restore_opened", lambda p: p["document_handle"]))),
    ("doc_get", {}, _drawing_persistence_document("drawing_restore_opened", version=True, clean=True,
                                   version_key="drawing_two_saved"), None),
    ("drawing_update", _drawing_deferred_update_args(_DRAWING_RESTORE_KEY, "drawing_restore_opened"),
     _drawing_job_started(_DRAWING_RESTORE_KEY),
     ("drawing_restore_job", _recall("drawing_restore_job", lambda p: p["job_id"]))),
    ("drawing_get_status", lambda c: _drawing_status_args(c, "drawing_restore_job", _DRAWING_RESTORE_KEY),
     _drawing_update_completed("drawing_restore_job", _DRAWING_RESTORE_KEY,
                               "drawing_restore_opened", "drawing_source_restored"), None),
    ("drawing_update", lambda c: {"expect_document": _ctx_get(c, "drawing_restore_opened", "the drawing")},
     _drawing_reference_current("drawing_source_restored"), None),
    ("drawing_get", {"include": ["views"]}, lambda p: _drawing_two_sheets(p, compare=True), None),
    ("drawing_export", _drawing_deferred_export_args(
        _DRAWING_RESTORED_PDF, _DRAWING_RESTORED_PDF_KEY, "drawing_restore_opened"),
     _drawing_job_started(_DRAWING_RESTORED_PDF_KEY),
     ("drawing_restored_pdf_job", _recall("drawing_restored_pdf_job", lambda p: p["job_id"]))),
    ("drawing_get_status", lambda c: _drawing_status_args(
        c, "drawing_restored_pdf_job", _DRAWING_RESTORED_PDF_KEY),
     _drawing_deferred_pdf_completed("drawing_restored_pdf_job", _DRAWING_RESTORED_PDF_KEY,
                                     "drawing_restore_opened", _DRAWING_RESTORED_PDF),
     ("drawing_restored_pdf", _recall("drawing_restored_pdf", _drawing_deferred_pdf_record))),
    ("data_get", lambda c: _version_args("drawing_restore_save_before")(
        {"source_urn": _ctx_get(c, "drawing", "the drawing")[0]}),
     _drawing_persistence_version_snapshot("drawing_restore_save_before"),
     ("drawing_restore_save_before", _recall("drawing_restore_save_before", _version_record))),
    ("doc_save", lambda c: {"description": "Persist restored drawing references",
                            "expect_document": _ctx_get(c, "drawing_restore_opened", "the drawing")},
     lambda p: _versioned((_RECALL.get("drawing") or [None, None])[1])(p)
     and (p.get("acted_on") or {}).get("document_id") == (_RECALL.get("drawing") or [None])[0], None),
    ("data_get", lambda c: {"file": _ctx_get(c, "drawing", "the drawing")[0]},
     _version_settled("drawing_restore_save_before"), None),
    ("data_get", lambda c: {"file": _ctx_get(c, "drawing", "the drawing")[0]},
     lambda p: _drawing_persistence_version(p, before_key="drawing_restore_save_before"),
     ("drawing_restored_saved", _recall("drawing_restored_saved", _version_record))),
    ("doc_get", {}, _drawing_persistence_document(
        "drawing_restore_opened", version=True, clean=True,
        version_key="drawing_restored_saved"), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "drawing_restore_opened", "the drawing"),
                             "expect_document": c["drawing_restore_opened"], "save_changes": False},
     lambda p: _document_closed(p) and p.get("close_unconfirmed") == [], None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "home_doc", "the home document")},
     _activated(), None),
    ("doc_get", {"max_results": 1000},
     lambda p: _drawing_persistence_absent(p, "drawing_restore_opened", "home_doc", None), None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "drawing_source_restored", "the restored source")["version_id"],
                            "force_api_open": True, "expect_document": c["home_doc"]},
     _drawing_source_reopened("drawing_source_restored", "drawing_source_restore_session"),
     ("drawing_final_source", _recall("drawing_final_source", lambda p: p["document_handle"]))),
    ("doc_get", {}, _drawing_source_document("drawing_final_source", "drawing_source_restored"), None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "drawing_restored_saved", "the restored drawing")["version_id"],
                            "force_api_open": True, "expect_document": c["drawing_final_source"]},
     _drawing_persistence_reopened(
        version_key="drawing_restored_saved", prior_handle_key="drawing_restore_opened"),
     ("drawing_final_opened", _recall("drawing_final_opened", lambda p: p["document_handle"]))),
    ("doc_get", {}, _drawing_persistence_document("drawing_final_opened", version=True, clean=True,
                                   version_key="drawing_restored_saved"), None),
    ("drawing_update", lambda c: {"expect_document": _ctx_get(c, "drawing_final_opened", "the drawing")},
     _drawing_reference_current("drawing_source_restored"), None),
    ("drawing_insert_image", {"image_path": MARKER_PNG, "x": 150, "y": 100}, _image_placed, None),
    # A coordinate that size is refused before a sketch is added: one that lands stops the whole
    # document's DXF export until it is deleted, and the read-back below is that export.
    ("drawing_add_sketch", {"name": _DRAWING_SKETCH_NAME + "Far", "geometry": [
        {"kind": "circle", "points": [[1e300, 0]], "radius": 5},
    ]}, _refused("carries 1e+300", "DXF export", "Nothing was drawn"), None),
    ("drawing_add_sketch", {"name": _DRAWING_SKETCH_NAME, "geometry": [
        {"kind": "line", "points": [[0, 0], [30, 0], [30, 20]]},
        {"kind": "rectangle", "points": [[40, 5], [70, 25]]},
        {"kind": "circle", "points": [[15, 35]], "radius": 5},
    ]}, _sketch_landed(_DRAWING_SKETCH_NAME, 4), None),
    # The DXF read-back the tool itself cannot take. It runs BEFORE the sheet add: a DXF holds the
    # ACTIVE sheet, and an add makes the sheet it adds active, so after it this exports a blank one.
    ("drawing_export", {"format": "dxf", "file_path": _DRAWING_SKETCH_DXF},
     _sketch_readback(_DRAWING_SKETCH_NAME, 4), None),
    ("drawing_edit_sheet", {"action": "add", "new_name": "SweepCloudSheet"},
     _sheet_added("SweepCloudSheet"), None),
    ("drawing_add_sketch", {"name": _DRAWING_WORKLOAD_NAME,
                             "sheet_name": "SweepCloudSheet",
                             "geometry": _DRAWING_WORKLOAD_GEOMETRY},
     _sketch_landed(_DRAWING_WORKLOAD_NAME, 16), None),
    ("drawing_export", {"format": "dxf", "file_path": _DRAWING_WORKLOAD_DXF},
     _sketch_readback(_DRAWING_WORKLOAD_NAME, 16), None),
    ("drawing_delete_sketch", {"sketch": _DRAWING_WORKLOAD_NAME,
                                "sheet": "SweepCloudSheet"},
     _drawing_sketch_deleted(_DRAWING_WORKLOAD_NAME, "SweepCloudSheet"), None),
    ("drawing_get", {}, _drawing_sketch_census,
     ("drawing_workload_counts", _recall("drawing_workload_counts",
                                          _drawing_sketch_count_values))),
    ("drawing_add_sketch", {"name": _DRAWING_BLANK_SKETCH_NAME + "OverLimitEntries",
                             "sheet_name": "SweepCloudSheet",
                             "geometry": _DRAWING_WORKLOAD_17_ENTITIES},
     _refused("brings this request to 17 curves", "Nothing was drawn"), None),
    ("drawing_get", {}, _drawing_sketch_census_unchanged("drawing_workload_counts"), None),
    ("drawing_add_sketch", {"name": _DRAWING_BLANK_SKETCH_NAME + "OverLimitChain",
                             "sheet_name": "SweepCloudSheet",
                             "geometry": [_DRAWING_WORKLOAD_17_SEGMENT_CHAIN]},
     _refused("brings this request to 17 curves", "Nothing was drawn"), None),
    ("drawing_get", {}, _drawing_sketch_census_unchanged("drawing_workload_counts"), None),
    # drawing_delete_sketch: a sketch added then deleted on the blank sheet, its own count
    # read-back (before - 1) proving the delete landed - the positive case beside the 1e300
    # refusal row above, which never lets a bad coordinate reach the sheet at all.
    ("drawing_add_sketch", {"name": _DRAWING_BLANK_SKETCH_NAME, "sheet_name": "SweepCloudSheet",
                            "geometry": [{"kind": "circle", "points": [[10, 10]], "radius": 3}]},
     _sketch_landed(_DRAWING_BLANK_SKETCH_NAME, 1), None),
    ("drawing_delete_sketch", {"sketch": _DRAWING_BLANK_SKETCH_NAME, "sheet": "SweepCloudSheet"},
     _drawing_sketch_deleted(_DRAWING_BLANK_SKETCH_NAME, "SweepCloudSheet"), None),
    # The added sheet is the ACTIVE one now, so this export holds the blank sheet: neither the
    # OTHER sheet's sketch layer nor the deleted sketch's OWN layer lands on it - the second is
    # what proves the delete above reached this export, not just the tool's own count read-back.
    ("drawing_export", {"format": "dxf", "file_path": _DRAWING_BLANK_DXF},
     _blank_sheet_readback, None),
    ("drawing_get", {}, _sheets_answer, None),
    ("drawing_export", {"format": "pdf",
                        "file_path": DOWNLOAD_DIR + f"/sweep_drawing_{_STAMP}.pdf"},
     _exported, None),
    # TEARDOWN. The drawing REFERENCES the source, so it closes and deletes first, for the same
    # reason the host did.
    ("doc_close", lambda c: {"name": _ctx_get(c, "drawing_final_opened", "the drawing session"),
                             "expect_document": c["drawing_final_opened"], "save_changes": False},
     _document_closed, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "drawing_final_source", "the source session")},
     _activated(SOURCE_DOC), None),
    ("doc_get", {"max_results": 1000}, lambda p: _drawing_persistence_absent(
        p, "drawing_final_opened", "drawing_final_source", SOURCE_DOC), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "drawing_final_source", "the source session"),
                             "expect_document": c["drawing_final_source"], "save_changes": False},
     _document_closed, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "home_doc", "the home document")},
     _activated(), None),
    _dwell(6.0),
    ("data_delete_file", lambda c: {"document_id": _ctx_get(c, "drawing", "the drawing")[0],
                                    "confirm_name": _ctx_get(c, "drawing", "the drawing")[1]},
     _file_deleted, None),
    # the source was versioned above and closed just now; a delete taken while the cloud is still
    # processing that version raises (InternalValidationError, measured), so the record is polled to
    # settled first and a delete that still refuses is reported.
    ("data_get", lambda c: {"file": _ctx_get(c, "source_urn", "the source")},
     _file_settled(FOLDER), None),
    ("data_delete_file", lambda c: {"document_id": _ctx_get(c, "source_urn", "the source"),
                                    "confirm_name": SOURCE_DOC}, _file_deleted, None),
    # the witness standing apart from the deletes' own reports: the configured folder read back.
    # NOT recursive - the tier's documents were saved into the folder ITSELF, and a recursive walk of a
    # working folder is a walk of every run that ever used it (measured: 49 files over 30-odd
    # subfolders, past the 20 s budget, which would red this row for the folder's size).
    ("data_get", {"project": PROJECT, "folder": FOLDER, "recursive": False},
     _files_gone(SOURCE_DOC, COPY_DOC, HOST_DOC, DERIVE_DOC, LINK_DOC), None),
]


# --- ACT 11d: CAM TEMPLATE PERSISTENCE ---------------------------------------------------------
_CAM_PERSIST_DOC = "SweepCamPersistence " + _STAMP
_CAM_PERSIST_COMP = "PersistenceCoupon " + _STAMP
_CAM_PERSIST_SKETCH = "PersistenceSketch " + _STAMP
_CAM_PERSIST_SOURCE = "PersistenceSource " + _STAMP
_CAM_PERSIST_SKIP = "PersistenceSkip " + _STAMP
_CAM_PERSIST_GENERATE = "PersistenceGenerate " + _STAMP
_CAM_PERSIST_PRESET = "PersistencePreset " + _STAMP
_CAM_PERSIST_TEMPLATE = "PersistenceTemplate " + _STAMP
_CAM_PERSIST_TOOL = "Persistence 6 mm cutter " + _STAMP


def _cam_persistence_start(ctx):
    """Clear only this act's prior captures before reading its home document."""
    for values in (ctx, _RECALL):
        for key in list(values):
            if key.startswith("cam_persist_"):
                values.pop(key)
    return {}


def _cam_persistence_library(p):
    """Require one uniquely described 6 mm cutter in the owned document library."""
    library = p.get("library") or {}
    rows = library.get("tools") or []
    return _measured("one owned 6 mm flat end mill", rows,
                     library.get("tool_count") == len(rows) == 1
                     and rows[0].get("description") == _CAM_PERSIST_TOOL
                     and rows[0].get("type") == "flat end mill"
                     and rows[0].get("diameter_mm") == 6.0
                     and type(rows[0].get("index")) is int and rows[0]["index"] >= 0)


def _cam_persistence_tool_values(p):
    """Return the tool label, dimensions, holder and preset identity exposed by the wire."""
    row = p.get("tool") or {}
    return {key: row.get(key) for key in
            ("tool", "dimensions", "holder", "active_preset", "preset")}


def _cam_persistence_tool(operation_key, before_key=None):
    """Require the minted operation's complete tool and preset to match its earlier read."""
    def check(p):
        row = p.get("tool") or {}
        values = _cam_persistence_tool_values(p)
        active, preset = values.get("active_preset") or {}, values.get("preset") or {}
        expressions = preset.get("expressions") or {}
        dimensions, holder = values.get("dimensions") or {}, values.get("holder") or {}
        before = _RECALL.get(before_key) if before_key else None
        return _measured("the minted operation retains its tool and preset",
                         {"operation": row.get("operation"), "tool": values, "before": before},
                         bool(_RECALL.get(operation_key))
                         and row.get("operation") == _RECALL.get(operation_key)
                         and isinstance(values.get("tool"), str)
                         and _CAM_PERSIST_TOOL in values["tool"]
                         and dimensions.get("diameter") == 6.0 and dimensions.get("units") == "mm"
                         and all(_num(dimensions.get(k)) for k in
                                 ("flute_length", "corner_radius", "overall_length"))
                         and dimensions["flute_length"] > 0
                         and dimensions["overall_length"] >= dimensions["flute_length"]
                         and dimensions["corner_radius"] >= 0
                         and all(isinstance(holder.get(k), str) and bool(holder[k])
                                 for k in ("name", "product_id", "vendor"))
                         and type(holder.get("segment_count")) is int and holder["segment_count"] > 0
                         and active.get("name") == preset.get("name") == _CAM_PERSIST_PRESET
                         and isinstance(active.get("id"), str) and bool(active["id"])
                         and _num(_leading_persistence_number(expressions.get("tool_feedCutting")))
                         and _leading_persistence_number(expressions.get("tool_feedCutting")) == 600.0
                         and _leading_persistence_number(expressions.get("tool_spindleSpeed")) == 6000.0
                         and (before_key is None or (bool(before) and values == before)))
    return check


def _leading_persistence_number(expression):
    """Read a numeric cutting expression without accepting symbolic formulas."""
    try:
        return float(expression)
    except (TypeError, ValueError):
        return None


def _cam_persistence_operations(setup, operation_key, state):
    """Read exactly the minted face operation, its path state and its retained tool label."""
    def check(p):
        name = _RECALL.get(operation_key)
        _RECALL["cam_persist_path_names"] = [name] if name else []
        _template_path_state(setup, "cam_persist_path_names", state)(p)
        groups = [r for r in (p.get("operations") or {}).get("setups", [])
                  if r.get("setup") == setup]
        rows = groups[0].get("operations") or []
        row = rows[0]
        path_ok = (row.get("has_toolpath") is False and row.get("toolpath_valid") is False
                   if state == "no_toolpath" else
                   row.get("blocked_by") == [] and "empty_toolpath" not in row)
        return _measured("the exact face operation retains its template state", row,
                         len(groups) == 1 and groups[0].get("operations_truncated") is False
                         and row.get("path") == f"{setup} / {name}"
                         and row.get("strategy") == "face"
                         and row.get("preset") == _CAM_PERSIST_PRESET
                         and bool(_RECALL.get("cam_persist_source_tool"))
                         and row.get("tool") == _RECALL["cam_persist_source_tool"].get("tool")
                         and path_ok)
    return check


def _cam_persistence_generated(setup, polls=18):
    """Bound generation waits and require one valid, nonempty operation in the exact setup."""
    def check(p):
        for i in range(polls):
            if p.get("completed") is True or (p.get("live_states") or {}).get("errored"):
                break
            if i == polls - 1:
                break
            time.sleep(_SETTLE_GAP_S)
            failed, p = facade("call")("cam_get_status", {"target": setup,
                                                          "include_operations": True})
            if failed or not isinstance(p, dict):
                raise AssertionError(f"Generation status unavailable for {setup!r}: {p!r}")
        live = p.get("live_states") or {}
        if p.get("completed") is not True:
            raise AssertionError(f"Generation pending for {setup!r} after {polls} reads: {live!r}")
        return _measured("one operation finished generating with a nonempty path",
                         {"setup": setup, "status": p},
                         p.get("target") == f"setup '{setup}'" and p.get("completed") is True
                         and p.get("operations_total") == live.get("total") == live.get("valid") == 1
                         and all(live.get(k) == 0 for k in ("out_of_date", "errored", "generating"))
                         and p.get("operations_with_errors") == []
                         and p.get("empty_toolpaths") == [])
    return check


def _cam_persistence_paths(setup):
    """Independently require a generated setup's one toolpath to be valid and nonempty."""
    def check(p):
        measured = p.get("measured") or {}
        states = measured.get("states") or {}
        return _measured("one independently inspected nonempty toolpath", measured,
                         p.get("passed") is True and measured.get("scope") == f"setup '{setup}'"
                         and states.get("total") == states.get("valid") == 1
                         and measured.get("not_valid") == []
                         and measured.get("not_valid_truncated") is False
                         and measured.get("empty_toolpath_count") == 0
                         and measured.get("empty_toolpaths") == []
                         and (p.get("tolerance_used") or {}).get("validity_basis")
                         == "manufacture_verified")
    return check


def _cam_persistence_document(handle_key, saved=False, version=False, absent_key=None):
    """Verify the active exact session, saved lineage/version and any closed session's absence."""
    def check(p):
        _home_document(p)
        active = p.get("active") or {}
        expected = _RECALL.get("cam_persist_version") or {}
        absent = _RECALL.get(absent_key) if absent_key else None
        valid = bool(_RECALL.get(handle_key)) and active.get("document_handle") == _RECALL[handle_key]
        if saved:
            valid = (valid and _document_is(_CAM_PERSIST_DOC)(p)
                     and active.get("document_id") == _RECALL.get("cam_persist_urn"))
        if version:
            valid = (valid and _version_current(expected)
                     and active.get("document_id") == expected.get("lineage")
                     and active.get("version_id") == expected.get("version_id")
                     and active.get("version_number") == expected.get("number"))
        if absent_key:
            valid = (valid and bool(absent) and p.get("truncated") is False
                     and all(r.get("document_handle") != absent for r in p.get("open_documents", [])))
        return _measured("the exact persistence document identity reads back", active, valid)
    return check


def _cam_persistence_cloud(p, after=False):
    """Require the owned cloud file's settled exact version, unchanged after reopen."""
    _file_record(FOLDER)(p)
    _version_snapshot("cam_persist_version")(p)
    snap = _version_record(p)
    saved = _RECALL.get("cam_persist_saved") or {}
    return _measured("the coupon's exact cloud version is settled", snap,
                     (p.get("file") or {}).get("name") == _CAM_PERSIST_DOC
                     and snap.get("lineage") == saved.get("document_id")
                     and snap.get("version_id") == saved.get("version_id")
                     and snap.get("number") == saved.get("version_number")
                     and (not after or snap == _RECALL.get("cam_persist_version")))


# The existing runner stops an act on a failed prerequisite and guards every document transition.
# This coupon is retained in the configured folder; its local template is removed before saving.
_CLOUD_CAM_PERSISTENCE = [
    ("doc_get", _cam_persistence_start, _home_document,
     ("cam_persist_home", _recall("cam_persist_home", _home_address))),
    ("doc_new", lambda c: {"expect_document": _ctx_get(c, "cam_persist_home", "the home session")},
     _new_document, ("cam_persist_owned", _recall("cam_persist_owned", lambda p: p["document_handle"]))),
    ("doc_get", {}, _cam_persistence_document("cam_persist_owned"), None),
    ("model_create_component", _lit({"name": _CAM_PERSIST_COMP, "activate": True}),
     _made_component, None),
    ("sketch_create", _lit({"plane": "xy", "name": _CAM_PERSIST_SKETCH}), "ok", None),
    ("sketch_add_geometry", _lit({"sketch_name": _CAM_PERSIST_SKETCH,
                                "geometry": [{"kind": "rectangle", "x1": 0, "y1": 0,
                                              "x2": 30, "y2": 20}]}), "ok", None),
    ("model_extrude", _lit({"sketch_name": _CAM_PERSIST_SKETCH, "profile_index": 0, "distance": 8}),
     _extruded, None),
    ("design_activate_component", {"occurrence": "root"}, "ok", None),
    ("view_switch_workspace", {"workspace": "manufacture"}, "ok", None),
    ("cam_create_setup", {"name": _CAM_PERSIST_SOURCE, "models": [_CAM_PERSIST_COMP + ":1"]},
     lambda p: p.get("created") is True and p.get("setup_name") == _CAM_PERSIST_SOURCE
     and p.get("model_count") == 1 and p.get("operation_count") == 0, None),
    ("cam_edit_tools", {"action": "add", "scope": "document", "add_tools": [{
        "from_type": "flat end mill", "diameter": "6 mm", "description": _CAM_PERSIST_TOOL,
        "presets": [{"name": _CAM_PERSIST_PRESET, "feed": "600 mm/min", "spindle_speed": "6000 rpm"}]}]},
     lambda p: p.get("added") == 1, None),
    ("cam_get", {"include": ["library"], "scope": "document", "max_results": 10},
     _cam_persistence_library, ("cam_persist_tool_index", lambda p: p["library"]["tools"][0]["index"])),
    ("cam_create_operation", lambda c: {"setup": _CAM_PERSIST_SOURCE, "strategy": "face",
                                        "tool_scope": "document", "generate": False,
                                        "tool_index": _ctx_get(c, "cam_persist_tool_index", "the cutter")},
     _op_created(_CAM_PERSIST_SOURCE, "face"),
     ("cam_persist_source_op", _recall("cam_persist_source_op", lambda p: p["operation"]))),
    ("cam_edit_operation", lambda c: {"operation": _ctx_get(c, "cam_persist_source_op", "the source face"),
                                      "preset": _CAM_PERSIST_PRESET},
     _preset_applied(_CAM_PERSIST_PRESET), None),
    ("cam_generate", {"target": _CAM_PERSIST_SOURCE, "skip_valid": False},
     _launched_on(_CAM_PERSIST_SOURCE),
     ("cam_persist_handle", _recall("cam_persist_handle", lambda p: p["handle"]))),
    ("cam_get_status", {"target": _CAM_PERSIST_SOURCE, "include_operations": True},
     _cam_persistence_generated(_CAM_PERSIST_SOURCE), None),
    ("cam_get_status", lambda c: {"handle": _ctx_get(c, "cam_persist_handle", "the source launch")},
     lambda p: p.get("completed") is True, None),
    ("cam_inspect_toolpaths", {"scope": _CAM_PERSIST_SOURCE},
     _cam_persistence_paths(_CAM_PERSIST_SOURCE), None),
    ("cam_get", lambda c: {"include": ["tool"], "preset": _CAM_PERSIST_PRESET,
                           "operation": _ctx_get(c, "cam_persist_source_op", "the source face")},
     _cam_persistence_tool("cam_persist_source_op"),
     ("cam_persist_source_tool", _recall("cam_persist_source_tool", _cam_persistence_tool_values))),
    ("cam_get", {"include": ["operations"], "setup": _CAM_PERSIST_SOURCE},
     _cam_persistence_operations(_CAM_PERSIST_SOURCE, "cam_persist_source_op", "valid"), None),
    ("cam_save_template", lambda c: {"setup": _CAM_PERSIST_SOURCE, "location": "local",
                                     "template_name": _CAM_PERSIST_TEMPLATE,
                                     "operations": _ctx_get(c, "cam_persist_source_op", "the source face")},
     lambda p: p.get("saved") is True and p.get("template") == _CAM_PERSIST_TEMPLATE
     and p.get("operations") == [_RECALL.get("cam_persist_source_op")]
     and isinstance(p.get("template_url"), str) and p["template_url"].startswith("user://"),
     ("cam_persist_template_url", lambda p: p["template_url"])),
    ("cam_create_setup", {"name": _CAM_PERSIST_SKIP, "models": [_CAM_PERSIST_COMP + ":1"]},
     lambda p: p.get("created") is True and p.get("setup_name") == _CAM_PERSIST_SKIP
     and p.get("operation_count") == 0, None),
    ("cam_apply_template", lambda c: {"setup": _CAM_PERSIST_SKIP, "location": "local", "generate": "skip",
                                      "template_name": _CAM_PERSIST_TEMPLATE,
                                      "template_url": _ctx_get(c, "cam_persist_template_url", "the template")},
     lambda p: _template_applied(_CAM_PERSIST_TEMPLATE, _CAM_PERSIST_SKIP, 1, "skip")(p)
     and p.get("created_count") == 1,
     ("cam_persist_skip_op", _recall("cam_persist_skip_op", lambda p: p["created_operations"][0]))),
    ("cam_get", {"include": ["operations"], "setup": _CAM_PERSIST_SKIP},
     _cam_persistence_operations(_CAM_PERSIST_SKIP, "cam_persist_skip_op", "no_toolpath"), None),
    ("cam_get", lambda c: {"include": ["tool"], "preset": _CAM_PERSIST_PRESET,
                           "operation": _ctx_get(c, "cam_persist_skip_op", "the skipped face")},
     _cam_persistence_tool("cam_persist_skip_op", "cam_persist_source_tool"),
     ("cam_persist_skip_tool", _recall("cam_persist_skip_tool", _cam_persistence_tool_values))),
    ("cam_create_setup", {"name": _CAM_PERSIST_GENERATE, "models": [_CAM_PERSIST_COMP + ":1"]},
     lambda p: p.get("created") is True and p.get("setup_name") == _CAM_PERSIST_GENERATE
     and p.get("operation_count") == 0, None),
    ("cam_apply_template", lambda c: {"setup": _CAM_PERSIST_GENERATE, "location": "local",
                                      "generate": "generate", "template_name": _CAM_PERSIST_TEMPLATE,
                                      "template_url": _ctx_get(c, "cam_persist_template_url", "the template")},
     lambda p: _template_applied(_CAM_PERSIST_TEMPLATE, _CAM_PERSIST_GENERATE, 1, "generate")(p)
     and p.get("created_count") == 1,
     ("cam_persist_generate_op", _recall("cam_persist_generate_op", lambda p: p["created_operations"][0]))),
    ("cam_get_status", {"target": _CAM_PERSIST_GENERATE, "include_operations": True},
     _cam_persistence_generated(_CAM_PERSIST_GENERATE), None),
    ("cam_inspect_toolpaths", {"scope": _CAM_PERSIST_GENERATE},
     _cam_persistence_paths(_CAM_PERSIST_GENERATE), None),
    ("cam_get", {"include": ["operations"], "setup": _CAM_PERSIST_GENERATE},
     _cam_persistence_operations(_CAM_PERSIST_GENERATE, "cam_persist_generate_op", "valid"), None),
    ("cam_get", lambda c: {"include": ["tool"], "preset": _CAM_PERSIST_PRESET,
                           "operation": _ctx_get(c, "cam_persist_generate_op", "the generated face")},
     _cam_persistence_tool("cam_persist_generate_op", "cam_persist_source_tool"),
     ("cam_persist_generate_tool", _recall("cam_persist_generate_tool", _cam_persistence_tool_values))),
    ("cam_delete_template", {"name": _CAM_PERSIST_TEMPLATE, "confirm_name": _CAM_PERSIST_TEMPLATE},
     lambda p: p.get("deleted") is True and p.get("template") == _CAM_PERSIST_TEMPLATE
     and p.get("loads_after_delete") is False and p.get("location") == "local", None),
    ("doc_save_as", {"name": _CAM_PERSIST_DOC, "project": PROJECT, "folder": FOLDER},
     lambda p: _saved_as(_CAM_PERSIST_DOC, FOLDER)(p) and bool(_version_identity(p.get("document_id"))),
     ("cam_persist_urn", _recall("cam_persist_urn", lambda p: p["document_id"]))),
    ("doc_get", {}, _cam_persistence_document("cam_persist_owned", saved=True),
     ("cam_persist_saved", _recall("cam_persist_saved", lambda p: p["active"]))),
    ("cam_get_status", lambda c: {"handle": _ctx_get(c, "cam_persist_handle", "the source launch")},
     _refused("is released", f"cam_get_status(target='{_CAM_PERSIST_SOURCE}')"), None),
    ("data_get", lambda c: _version_args("cam_persist_version")(
        {"source_urn": _ctx_get(c, "cam_persist_urn", "the saved coupon")}),
     _cam_persistence_cloud,
     ("cam_persist_version", _recall("cam_persist_version", _version_record))),
    ("doc_get", {}, _cam_persistence_document("cam_persist_owned", saved=True, version=True), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "cam_persist_owned", "the saved coupon session"),
                             "save_changes": False, "expect_document": c["cam_persist_owned"]},
     lambda p: _document_closed(p) and p.get("closed") == [_CAM_PERSIST_DOC]
     and p.get("close_unconfirmed") == [], None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "cam_persist_home", "the home session")},
     _activated(), None),
    ("doc_get", {"max_results": 1000},
     _cam_persistence_document("cam_persist_home", absent_key="cam_persist_owned"), None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "cam_persist_urn", "the saved coupon"),
                            "force_api_open": True, "expect_document": c["cam_persist_home"]},
     lambda p: _opened(_CAM_PERSIST_DOC, lambda: _RECALL.get("cam_persist_urn"))(p)
     and p.get("document_handle") != _RECALL.get("cam_persist_owned"),
     ("cam_persist_reopened", _recall("cam_persist_reopened", lambda p: p["document_handle"]))),
    ("doc_get", {}, _cam_persistence_document("cam_persist_reopened", saved=True, version=True), None),
    ("cam_get", {"include": ["operations"], "setup": _CAM_PERSIST_SKIP},
     _cam_persistence_operations(_CAM_PERSIST_SKIP, "cam_persist_skip_op", "no_toolpath"), None),
    ("cam_get", lambda c: {"include": ["tool"], "preset": _CAM_PERSIST_PRESET,
                           "operation": _ctx_get(c, "cam_persist_skip_op", "the skipped face")},
     _cam_persistence_tool("cam_persist_skip_op", "cam_persist_skip_tool"), None),
    ("cam_get", {"include": ["operations"], "setup": _CAM_PERSIST_GENERATE},
     _cam_persistence_operations(_CAM_PERSIST_GENERATE, "cam_persist_generate_op", "valid"), None),
    ("cam_get", lambda c: {"include": ["tool"], "preset": _CAM_PERSIST_PRESET,
                           "operation": _ctx_get(c, "cam_persist_generate_op", "the generated face")},
     _cam_persistence_tool("cam_persist_generate_op", "cam_persist_generate_tool"), None),
    ("cam_get_status", {"target": _CAM_PERSIST_GENERATE, "include_operations": True},
     _cam_persistence_generated(_CAM_PERSIST_GENERATE), None),
    ("cam_inspect_toolpaths", {"scope": _CAM_PERSIST_GENERATE},
     _cam_persistence_paths(_CAM_PERSIST_GENERATE), None),
    ("data_get", lambda c: _version_args("cam_persist_version")(
        {"source_urn": _ctx_get(c, "cam_persist_urn", "the saved coupon")}),
     lambda p: _cam_persistence_cloud(p, after=True), None),
    ("doc_get", {}, _cam_persistence_document("cam_persist_reopened", saved=True, version=True), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "cam_persist_reopened", "the reopened coupon session"),
                             "save_changes": False, "expect_document": c["cam_persist_reopened"]},
     lambda p: _document_closed(p) and p.get("closed") == [_CAM_PERSIST_DOC]
     and p.get("close_unconfirmed") == [], None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "cam_persist_home", "the home session")},
     _activated(), None),
    ("doc_get", {"max_results": 1000},
     _cam_persistence_document("cam_persist_home", absent_key="cam_persist_reopened"), None),
]


def _configure_table_state(p, active="B"):
    """Return the saved table's complete two-row/column identities without claiming cell values."""
    table = p.get("configurations") or {}
    rows, columns = table.get("configurations"), table.get("columns")
    if (not table.get("table_id") or table.get("active_configuration") not in {"Configuration 1", "B"}
            or (active is not None and table.get("active_configuration") != active)
            or table.get("configuration_count") != 2 or not isinstance(rows, list) or len(rows) != 2
            or {r.get("name") for r in rows} != {"Configuration 1", "B"}
            or any(not r.get("id") or type(r.get("is_active")) is not bool
                   or r["is_active"] != (r.get("name") == table.get("active_configuration")) for r in rows)
            or len({r["id"] for r in rows}) != 2 or sum(r["is_active"] for r in rows) != 1
            or not isinstance(columns, list) or not columns or table.get("truncated")
            or any(not c.get("id") or not c.get("title") or not c.get("type") for c in columns)
            or len({c["id"] for c in columns}) != len(columns)):
        return None
    return table


def _configure_parameters(p):
    """Return the complete readable owned parameter row, including physical values."""
    rows = p.get("user_parameters")
    if (p.get("user_parameter_count") != 1 or p.get("matched") != 1 or p.get("returned") != 1
            or not isinstance(rows, list) or len(rows) != 1 or rows[0].get("name") != "ProbeW"
            or rows[0].get("unit") != "mm" or rows[0].get("value_units") != "mm"
            or not isinstance(rows[0].get("expression"), str)
            or not all(_num(rows[0].get(k)) for k in ("value", "value_internal"))):
        return None
    return p


def _configure_column_rows():
    """Build the owned saved setter-refusal scene and active-configuration geometry control."""
    name = "SweepConfigureColumn." + _STAMP
    def write(args):
        return lambda c: dict(args, expect_document=_ctx_get(c, "configure_owned", "the configuration coupon"))
    def history(p):
        state = _retire_design_state(p)
        tl = (state or {}).get("timeline") or {}
        return state if (tl.get("count") == 4 and (tl.get("summary") or {}).get("states") == {"healthy": 4}
                         and (tl.get("summary") or {}).get("exceptions") == []) else None
    def saved(p):
        return (_document_is(name)(p) and _home_address(p) == _RECALL.get("configure_owned")
                and p["active"]["document_id"] == _RECALL.get("configure_urn"))
    def material(p):
        state = _retire_material_state(p)
        return p if (state is not None and len(state["bodies"]) == 2
                     and {r["body"] for r in state["bodies"]} == {"Body1", "Body2"}) else None
    def reads(after=False):
        def table(p):
            state = _configure_table_state(p)
            if not after and (state is None or len(state["columns"]) != 1
                              or state["columns"][0]["title"] != "Part Number"):
                return None
            return state
        rows = [("design_get", {"include": ["configurations"]},
                 _retire_compare("configure_table", table, after), None),
                ("param_get", {}, _retire_compare("configure_params", _configure_parameters, after), None),
                ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                                "max_depth": 10, "max_results": 2000},
                 _retire_compare("configure_history", history, after), None),
                ("model_inspect", {"include": ["default", "mass"], "units": "mm",
                                   "accuracy": "very_high", "per_body": True},
                 _retire_compare("configure_material", material, after), None)]
        for body in ("Body1", "Body2"):
            def initial_body(p, body=body):
                state = _symmetric_target_body_state(p)
                size, minimum, maximum, volume = ([10, 8, 10], [0, 0, 0], [10, 8, 10], 800) if body == "Body1" else (
                    [5, 5, 5], [40, 0, 0], [45, 5, 5], 125)
                return state if (state is not None and state["size"] == size
                                 and [state["bounds"]["min_point"][a] for a in "xyz"] == minimum
                                 and [state["bounds"]["max_point"][a] for a in "xyz"] == maximum
                                 and _near(state["material"]["volume"], volume, .001)) else None
            rows += [("model_inspect", _lit({"target": body, "include": ["default", "mass"], "units": "mm",
                                             "accuracy": "very_high", "per_body": True}),
                      _retire_compare("configure_" + body, initial_body, after), None),
                     ("find_geometry", _lit({"target": body, "units": "mm", "max_results": 100}),
                      _retire_compare("configure_" + body + "_geometry", _edge_extent_geometry, after), None)]
        return rows
    def legal_table(p):
        now, old = _configure_table_state(p), _RECALL.get("configure_table")
        new = [c for c in (now or {}).get("columns", []) if c.get("id") not in {c["id"] for c in (old or {}).get("columns", [])}]
        cells = (now or {}).get("cells") or []
        column_id = _RECALL.get("configure_legal_column")
        added_cells = [c for c in cells if c.get("column_id") == column_id]
        expected_cells = [{"row_id": r["id"], "column_id": column_id,
                           "kind": "ConfigurationParameterCell",
                           "expression": "13 mm" if r["name"] == "B" else "10 mm"}
                          for r in (old or {}).get("configurations", [])]
        changed = {"columns", "cells", "cell_count"}
        return _measured("one fresh ProbeW column with unchanged existing table identities", now,
                         now is not None and old is not None and len(new) == 1 and new[0]["title"] == "ProbeW"
                         and new[0]["type"] == "ConfigurationParameterColumn"
                         and {k: v for k, v in now.items() if k not in changed} == {k: v for k, v in old.items() if k not in changed}
                         and [c for c in now["columns"] if c not in new] == old["columns"]
                         and new[0]["id"] == column_id
                         and now.get("cell_count") == len(cells) == old.get("cell_count", 0) + 2
                         and added_cells == expected_cells
                         and [c for c in cells if c.get("column_id") != column_id] == old.get("cells"))
    def legal_params(p):
        old = copy.deepcopy(_RECALL.get("configure_params"))
        if old:
            old["user_parameters"][0].update(expression="13 mm", value=13.0, value_internal=1.3)
        return _measured("active B drives actual ProbeW to 13 mm", p,
                         old is not None and _configure_parameters(p) == old)
    def legal_body(p):
        state = _symmetric_target_body_state(p)
        return _measured("actual driven 10x8x13 mm solid, 1040 mm3", state,
                         state is not None and state["size"] == [10, 8, 13]
                         and state["bounds"]["min_point"] == {"x": 0, "y": 0, "z": 0}
                         and state["bounds"]["max_point"] == {"x": 10, "y": 8, "z": 13}
                         and _near(state["material"]["volume"], 1040, .001))
    rows = [("doc_get", {}, _home_document, ("configure_home", _recall("configure_home", _home_address))),
            ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                            "max_depth": 10, "max_results": 2000},
             _retire_compare("configure_home_design", _retire_design_state, False), None),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "configure_home", "the home session")},
             _new_document, ("configure_owned", _recall("configure_owned", lambda p: p["document_handle"]))),
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("param_add", write({"name": "ProbeW", "expression": "10 mm", "unit": "mm"}), "ok", None)]
    for sketch, x, width, depth, distance, body in [("ConfigureStock", 0, 10, 8, "ProbeW", "Body1"),
                                                  ("ConfigureWitness", 40, 5, 5, "5 mm", "Body2")]:
        rows += [("sketch_create", write({"name": sketch, "plane": "xy"}), "ok", None),
                 ("sketch_add_geometry", write({"sketch_name": sketch, "units": "mm", "geometry": [
                     {"kind": "rectangle", "x1": x, "y1": 0, "x2": x + width, "y2": depth}]}), "ok", None),
                 ("model_extrude", write({"sketch_name": sketch, "distance": distance, "units": "mm", "operation": "new"}),
                  lambda p, body=body: _extruded(p) and p.get("result_bodies") == [body], None)]
    rows += [("view_set", write({"action": "orient", "orientation": "iso-top-right", "fit": True}), "ok", None),
             ("doc_save_as", write({"name": name, "project": PROJECT, "folder": FOLDER, "create_path": False}),
              _saved_as(name, FOLDER), ("configure_urn", _recall("configure_urn", lambda p: p["document_id"]))),
             ("doc_get", {}, saved, None),
             ("design_configure", write({"action": "create"}),
              lambda p: p.get("configured") is True and p.get("created") is True
              and p.get("configurations") == ["Configuration 1"], None),
             ("design_configure", write({"action": "add_configuration", "name": "B"}),
              lambda p: p.get("configuration") == "B" and p.get("active_configuration") == "B"
              and p.get("configurations") == ["Configuration 1", "B"], None),
             ("doc_get", {}, saved, None)] + reads()
    for expression in ("NoSuchProbe * 2", "5 kg"):
        rows += [("design_configure", write({"action": "add_parameter", "parameter": "ProbeW", "values": {"B": expression}}),
                  _refused("'ProbeW' cell 'B'", repr(expression), "invalid expression", "The new column was removed.",
                           "design_get(include=['configurations'])"), None)] + reads(True)
    rows += [("design_configure", write({"action": "add_parameter", "parameter": "ProbeW", "values": {"B": "13 mm"}}),
              lambda p: p.get("parameter") == "ProbeW" and p.get("set") == 1 and bool(p.get("column_id")),
              ("configure_legal_column", _recall("configure_legal_column", lambda p: p["column_id"]))),
             ("design_get", {"include": ["configurations"]}, legal_table, None),
             ("param_get", {}, legal_params, None),
             ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                             "max_depth": 10, "max_results": 2000},
              _retire_compare("configure_history", history, True), None),
             ("model_inspect", {"include": ["default", "mass"], "units": "mm",
                                "accuracy": "very_high", "per_body": True},
              lambda p: material(p) is not None and _near(p["mass"]["volume"], 1165, .001)
              and _near(p["mass"]["area"], 778, .001), None),
             ("model_inspect", _lit({"target": "Body1", "include": ["default", "mass"], "units": "mm",
                                     "accuracy": "very_high", "per_body": True}), legal_body, None),
             ("model_inspect", _lit({"target": "Body2", "include": ["default", "mass"], "units": "mm",
                                     "accuracy": "very_high", "per_body": True}),
              _retire_compare("configure_Body2", _symmetric_target_body_state, True), None),
             ("find_geometry", _lit({"target": "Body2", "units": "mm", "max_results": 100}),
              _retire_compare("configure_Body2_geometry", _edge_extent_geometry, True), None),
             ("doc_close", lambda c: {"name": _ctx_get(c, "configure_owned", "the coupon"), "save_changes": False,
                                      "expect_document": c["configure_owned"]}, _document_closed, None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "configure_home", "the home session")}, _activated(), None),
             ("doc_get", {}, lambda p: _home_address(p) == _RECALL.get("configure_home")
              and all(r.get("document_handle") != _RECALL.get("configure_owned") for r in p["open_documents"]), None),
             ("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                             "max_depth": 10, "max_results": 2000},
              _retire_compare("configure_home_design", _retire_design_state, True), None)]
    return rows


_CLOUD_CONFIGURE = _configure_column_rows()


class _WrongLineage(_Refusal):
    """doc_open's refusal naming the recalled Save As lineage as opened, the in-place one as asked."""

    def __init__(self):
        super().__init__(())

    def missing(self, text):
        want = ("The document that opened is 'SweepLineageSaveAs.",
                f"({_RECALL.get('lin_saveas')}), not the file asked for ({_RECALL.get('lin_inplace')})",
                "It stays open; discard it with doc_close(name='session:", "save_changes=false)")
        return [f for f in want if f not in text]


def _lineage_open_rows():
    """A configured design saved in place then saved as: opening the in-place lineage is refused."""
    first, second = "SweepLineageInPlace." + _STAMP, "SweepLineageSaveAs." + _STAMP
    home = lambda c: _ctx_get(c, "lin_home", "the home session")

    def write(args):
        return lambda c: dict(args, expect_document=_ctx_get(c, "lin_owned", "the lineage coupon"))

    def moved(p):
        change = p.get("lineage_changed") or {}
        return _measured("the in-place save moved the lineage", change,
                         p.get("saved") is True and change.get("from") == _RECALL.get("lin_first")
                         and bool(change.get("to")) and change.get("to") != change.get("from")
                         and p.get("version_confirmed") is False and p.get("cloud_tip_advanced") is False
                         and "advance cannot be inferred across them" in p.get("note", "")
                         and "configuration backing file" in p.get("note", ""))

    def source_state(p):
        file, location = p.get("file") or {}, p.get("location") or {}
        project, folder = location.get("project") or {}, location.get("parent_folder") or {}
        return {"id": file.get("id"), "name": file.get("name"),
                "project_id": project.get("id"), "project": project.get("name"),
                "folder": folder.get("name")}

    def source_args(key):
        def args(c):
            urn = _ctx_get(c, key, "the configured source")
            missing = (f"No cloud file resolves from '{urn}'. Tried: {urn}. "
                       "Get a lineage URN from data_get(project=<name>) ('id' on each file).")
            for i in range(min(_SETTLE_POLLS, 16)):
                failed, last = facade("call")("data_get", {"file": urn})
                if failed:
                    _measured("only this source's pending resolution is retried", last, last == missing)
                else:
                    _measured("the source read resolves the exact retained lineage", last,
                              (last.get("file") or {}).get("id") == urn)
                    if all(isinstance(v, str) and v for v in source_state(last).values()):
                        return {"file": urn}
                if i + 1 < min(_SETTLE_POLLS, 16):
                    time.sleep(_SETTLE_GAP_S)
            raise AssertionError(f"Configured source {urn!r} did not read within the bound: {last!r}")
        return args

    def prior_backing(p):
        state = source_state(p)
        return _measured("independent pre-conversion lineage is now a backing file", state,
                         state["id"] == _RECALL.get("lin_first")
                         and state["name"] == "Configuration 1"
                         and state["project"] == "System Project - CONFIG"
                         and all(isinstance(v, str) and v for v in state.values()))

    def source_before(p):
        state = source_state(p)
        valid = (state["id"] == _RECALL.get("lin_inplace")
                 and all(isinstance(v, str) and v for v in state.values())
                 and state["name"] == first and state["project"] == PROJECT)
        return _measured("configured source before Save As", state, valid)

    def saved_copy(p):
        source = p.get("source_file") or {}
        before, after = source.get("before") or {}, source.get("after") or {}
        baseline = _RECALL.get("lin_source_before")
        valid = (baseline is not None and all(before.get(k) == v for k, v in baseline.items())
                 and source.get("changed") is True and after.get("id") == baseline["id"]
                 and after.get("name") == "Configuration 1"
                 and after.get("project") == "System Project - CONFIG"
                 and "does not confirm publication" in p.get("note", "")
                 and "the same URN again" in p.get("note", "")
                 and p.get("document_id") not in (_RECALL.get("lin_first"), _RECALL.get("lin_inplace")))
        _measured("Save As discloses relocated source and publication limitation", source, valid)
        _RECALL["lin_source_claim"] = source
        return _saved_as(second, FOLDER)(p)

    def source_after(p):
        now = source_state(p)
        claimed = (_RECALL.get("lin_source_claim") or {}).get("after") or {}
        before = _RECALL.get("lin_source_before") or {}
        return _measured("independent read confirms source relocation", now,
                         all(isinstance(v, str) and v and claimed.get(k) == v for k, v in now.items())
                         and now["id"] == before.get("id")
                         and now["name"] != before.get("name")
                         and now["project_id"] != before.get("project_id"))

    def reopened(p):
        active = p.get("active") or {}
        return _measured("the open document reads the Save As lineage", active,
                         active.get("name") == second
                         and active.get("document_id") == _RECALL.get("lin_saveas"))

    def flagged(p):
        return _measured("the Save As design opened as itself, flag read off it", p,
                         p.get("opened") is True and p.get("is_configured_design") is True
                         and p.get("document_id") == p.get("resolved_id") == _RECALL.get("lin_saveas")
                         and "configured_design_note" in p
                         and "was not compared" not in (p.get("note") or ""))

    def published(p):
        urn = _RECALL.get("lin_saveas")
        active = p.get("active") or {}
        _measured("the publishing document is this Save As coupon", active,
                  bool(urn) and active.get("document_id") == urn and active.get("name") == second)
        missing = (f"No cloud file resolves from '{urn}'. Tried: {urn}. "
                   "Get a lineage URN from data_get(project=<name>) ('id' on each file).")
        for i in range(_SETTLE_POLLS):
            is_error, last = facade("call")("data_get", {"file": urn})
            if is_error:
                _measured("only the exact pending lineage resolution is retried", last, last == missing)
            else:
                file = last.get("file") or {}
                _measured("publication reads only this Save As coupon", file,
                          file.get("id") == urn and file.get("name") == second)
                if (last.get("state") or {}).get("is_complete") is True:
                    return _file_record(FOLDER)(last)
            if i + 1 < _SETTLE_POLLS:
                time.sleep(_SETTLE_GAP_S)
        return _measured("the Save As coupon finished publishing within the bound", last, False)

    return [
        ("doc_get", {}, _home_document, ("lin_home", _recall("lin_home", _home_address))),
        ("doc_new", lambda c: {"expect_document": home(c)}, _new_document,
         ("lin_owned", _recall("lin_owned", lambda p: p["document_handle"]))),
        ("design_activate_component", {"occurrence": "root"}, "ok", None),
        ("param_add", write({"name": "ProbeW", "expression": "10 mm", "unit": "mm"}), "ok", None),
        ("sketch_create", write({"name": "LineageStock", "plane": "xy"}), "ok", None),
        ("sketch_add_geometry", write({"sketch_name": "LineageStock", "units": "mm", "geometry": [
            {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 8}]}), "ok", None),
        ("model_extrude", write({"sketch_name": "LineageStock", "distance": "ProbeW", "units": "mm",
                                 "operation": "new"}), _extruded, None),
        ("doc_save_as", write({"name": first, "project": PROJECT, "folder": FOLDER, "create_path": False}),
         _saved_as(first, FOLDER), ("lin_first", _recall("lin_first", lambda p: p["document_id"]))),
        ("design_configure", write({"action": "create"}),
         lambda p: p.get("configured") is True and p.get("created") is True, None),
        ("design_configure", write({"action": "add_configuration", "name": "B"}),
         lambda p: p.get("active_configuration") == "B", None),
        ("design_configure", write({"action": "add_parameter", "parameter": "ProbeW",
                                    "values": {"B": "13 mm"}}),
         lambda p: p.get("parameter") == "ProbeW" and p.get("set") == 1, None),
        ("doc_save", write({"description": "lineage replay: in-place save after conversion"}), moved,
         ("lin_inplace", _recall("lin_inplace", lambda p: p["lineage_changed"]["to"]))),
        ("data_get", source_args("lin_first"), prior_backing, None),
        ("data_get", source_args("lin_inplace"), source_before,
         ("lin_source_before", _recall("lin_source_before", source_state))),
        ("doc_save_as", write({"name": second, "project": PROJECT, "folder": FOLDER, "create_path": False}),
         saved_copy,
         ("lin_saveas", _recall("lin_saveas", lambda p: p["document_id"]))),
        ("data_get", lambda c: {"file": _ctx_get(c, "lin_inplace", "in-place lineage")},
         source_after, None),
        ("doc_get", {}, published, None),
        ("doc_activate", lambda c: {"name": home(c)}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "lin_owned", "the coupon"), "save_changes": False,
                                 "expect_document": home(c)}, _document_closed, None),
        ("doc_open", lambda c: {"file_id": _ctx_get(c, "lin_saveas", "the Save As lineage"),
                                "force_api_open": True, "expect_document": home(c)},
         flagged, ("lin_reopened", _recall("lin_reopened", lambda p: p["document_handle"]))),
        # Opening its backing item keeps the already-open owning design active.
        ("doc_open", lambda c: {"file_id": _ctx_get(c, "lin_inplace", "the in-place lineage"),
                                "force_api_open": True,
                                "expect_document": _ctx_get(c, "lin_reopened", "the reopened design")},
         _WrongLineage(), None),
        ("doc_get", {}, reopened, None),
        ("design_get", {"include": ["configurations"]},
         lambda p: _measured("the open design carries the two-row ProbeW configuration table",
                             _configure_table_state(p, None),
                             _configure_table_state(p, None) is not None
                             and any(c.get("title") == "ProbeW" for c in p["configurations"]["columns"])), None),
        ("doc_activate", lambda c: {"name": home(c)}, _activated(), None),
        ("doc_close", lambda c: {"name": _ctx_get(c, "lin_reopened", "the reopened design"),
                                 "save_changes": False, "expect_document": home(c)},
         _document_closed, None),
        ("doc_get", {}, lambda p: _home_address(p) == _RECALL.get("lin_home"), None),
    ]


_CLOUD_CONFIGURE += _lineage_open_rows()



def _parameter_table(p):
    """Return param_get's complete user and model rows by name, or None when the read is partial."""
    users, models = p.get("user_parameters"), p.get("model_parameters")
    if (not isinstance(users, list) or not isinstance(models, list)
            or p.get("user_parameter_count") != len(users) or p.get("matched") != len(users)
            or p.get("returned") != len(users) or p.get("model_parameter_count") != len(models)
            or any(k in p for k in ("truncated", "walk_truncated", "generated_skipped",
                                    "model_walk_truncated", "model_parameters_truncated"))):
        return None
    out = {"user": {}, "model": {}}
    for group, rows in (("user", users), ("model", models)):
        for row in rows:
            name = row.get("name")
            if (not isinstance(name, str) or not name or name in out["user"] or name in out["model"]
                    or not isinstance(row.get("expression"), str)
                    or not all(_num(row.get(k)) for k in ("value", "value_internal"))):
                return None
            out[group][name] = {k: row.get(k) for k in (
                "expression", "unit", "value", "value_internal", "value_units", "favorite",
                "comment", "owner", "owner_type", "role")}
    return out


def _parameter_table_renamed(table, previous, name, expressions):
    """Return `table` with one row re-keyed and the named dependents' expressions replaced."""
    out = copy.deepcopy(table)
    for rows in out.values():
        if previous in rows:
            rows[name] = rows.pop(previous)
        for dependent, expression in expressions.items():
            if dependent in rows:
                rows[dependent]["expression"] = expression
    return out


def _param_rename_rows():
    """Rename a user and a model parameter on an owned scratch, refuse four renames, rename back."""
    first, twice, span, depth = "RenameLen", "RenameTwice", "RenameSpan", "RenameDepth"
    listing = {"include_model_parameters": True}
    body_read = {"include": ["default", "mass"], "units": "mm", "accuracy": "very_high", "per_body": True}

    def write(args):
        return lambda c: dict(args(c) if callable(args) else args,
                              expect_document=_ctx_get(c, "rename_owned", "the rename scratch"))

    def driven(n):
        return _RECALL.get("rename_d%d" % n)

    def expected(stage):
        table = _RECALL.get("rename_table")
        if table is not None and stage >= 1:
            table = _parameter_table_renamed(table, first, span, {twice: span + " * 2", driven(1): span})
        if table is not None and stage >= 2:
            table = _parameter_table_renamed(table, driven(1), depth, {driven(2): depth + " + 1 mm"})
        return table

    def table_is(stage):
        def check(p):
            want, now = expected(stage), _parameter_table(p)
            return _measured(f"the parameter table after {stage} rename(s)", {"want": want, "now": now},
                             now is not None and want is not None and now == want)
        return check

    def one_model_row(expression, reply_key):
        def pick(p):
            hits = [r.get("name") for r in p.get("model_parameters") or []
                    if r.get("expression") == expression()]
            _measured(f"one model parameter reads '{expression()}', the one the extrude reported",
                      {"hits": hits, "reported": _RECALL.get(reply_key)},
                      len(hits) == 1 and hits[0] == _RECALL.get(reply_key))
            return hits[0]
        return pick

    def baseline(p):
        table = _parameter_table(p)
        users, models = (table or {}).get("user", {}), (table or {}).get("model", {})
        stacked_on = [n for n, r in models.items() if r["expression"] == f"{driven(1)} + 1 mm"]
        valid = (table is not None and set(users) == {first, twice}
                 and users[first]["expression"] == "10 mm" and _near(users[first]["value"], 10, 1e-9)
                 and users[twice]["expression"] == first + " * 2" and _near(users[twice]["value"], 20, 1e-9)
                 and [n for n, r in models.items() if r["expression"] == first] == [driven(1)]
                 and _near(models[driven(1)]["value"], 10, 1e-9)
                 and stacked_on == [_RECALL.get("rename_d2_reply")]
                 and _near(models[stacked_on[0]]["value"], 11, 1e-9))
        if valid:
            _RECALL["rename_table"] = table
        return _measured("the two user parameters and both extrude depths before any rename", table, valid)

    def renamed(previous, name, closure, follows):
        def check(p):
            was, now = previous(), name()
            rows = p.get("dependents")
            by_name = {r.get("name"): r for r in rows} if isinstance(rows, list) else {}
            judged = {n: (r.get("expression_before"), r.get("expression_after"), r["follows"])
                      for n, r in by_name.items() if "follows" in r}
            before, after = p.get("before") or {}, p.get("after") or {}
            return _measured(
                f"'{was}' renamed '{now}' and the expressions naming it follow",
                {k: p.get(k) for k in ("renamed", "previous_name", "requested_name", "name", "dependents",
                                       "dependents_total", "unread", "note")},
                p.get("renamed") is True and p.get("previous_name") == was
                and p.get("requested_name") == now and p.get("name") == now
                and before.get("name") == was and after.get("name") == now
                and {k: v for k, v in before.items() if k != "name"}
                == {k: v for k, v in after.items() if k != "name"}
                and isinstance(rows, list) and len(by_name) == len(rows)
                and p.get("dependents_total") == len(rows) and p.get("dependents_truncated") is False
                and set(by_name) == set(closure())
                and judged == {n: (b, a, True) for n, (b, a) in follows().items()}
                and all(r.get("expression_before") == r.get("expression_after")
                        for n, r in by_name.items() if n not in judged)
                and not any(k in p for k in ("unread", "new_timeline_errors", "new_timeline_warnings", "note")))
        return check

    def history(p):
        state = _retire_design_state(p)
        tl = (state or {}).get("timeline") or {}
        return state if (tl.get("count") == 4 and (tl.get("summary") or {}).get("states") == {"healthy": 4}
                         and (tl.get("summary") or {}).get("exceptions") == []) else None

    def geometry(after):
        rows = [("design_get", {"include": ["tree", "timeline"], "tree_bodies": True, "tree_handles": True,
                                "max_depth": 10, "max_results": 2000},
                 _retire_compare("rename_history", history, after), None)]
        for body, size, volume in (("Body1", [10, 8, 10], 800), ("Body2", [5, 5, 11], 275)):
            def solid(p, size=size, volume=volume):
                state = _symmetric_target_body_state(p)
                return state if (state is not None and state["size"] == size
                                 and _near(state["material"]["volume"], volume, .001)) else None
            rows.append(("model_inspect", _lit(dict(body_read, target=body)),
                         _retire_compare("rename_" + body, solid, after), None))
        return rows

    def refusal(args, *fragments):
        return [("param_set", write(args), _refused(*fragments), None),
                ("param_get", listing, table_is(2), None)]

    everything = lambda: {twice, driven(1), driven(2)}
    stacked = lambda: {driven(2)}
    rows = [("doc_get", {}, _home_document, ("rename_home", _recall("rename_home", _home_address))),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "rename_home", "the home session")},
             _new_document, ("rename_owned", _recall("rename_owned", lambda p: p["document_handle"]))),
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("param_add", write({"name": first, "expression": "10 mm", "unit": "mm"}),
             lambda p: p.get("added") is True and p["parameter"]["name"] == first, None),
            ("param_add", write({"name": twice, "expression": first + " * 2", "unit": "mm"}),
             lambda p: p.get("added") is True and p["parameter"]["name"] == twice, None),
            ("sketch_create", write({"name": "RenameBase", "plane": "xy"}), "ok", None),
            ("sketch_add_geometry", write({"sketch_name": "RenameBase", "units": "mm", "geometry": [
                {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 8}]}), "ok", None),
            ("model_extrude", write({"sketch_name": "RenameBase", "distance": first, "units": "mm",
                                     "operation": "new"}),
             lambda p: _extruded(p) and p.get("result_bodies") == ["Body1"],
             ("rename_d1_reply", _recall("rename_d1_reply", lambda p: p["model_parameters"]["distance"]))),
            ("param_get", listing, lambda p: bool(one_model_row(lambda: first, "rename_d1_reply")(p)),
             ("rename_d1", _recall("rename_d1", one_model_row(lambda: first, "rename_d1_reply")))),
            ("sketch_create", write({"name": "RenameStack", "plane": "xy"}), "ok", None),
            ("sketch_add_geometry", write({"sketch_name": "RenameStack", "units": "mm", "geometry": [
                {"kind": "rectangle", "x1": 40, "y1": 0, "x2": 45, "y2": 5}]}), "ok", None),
            ("model_extrude", write(lambda c: {
                "sketch_name": "RenameStack", "units": "mm", "operation": "new",
                "distance": _ctx_get(c, "rename_d1", "the first extrude's depth parameter") + " + 1 mm"}),
             lambda p: _extruded(p) and p.get("result_bodies") == ["Body2"],
             ("rename_d2_reply", _recall("rename_d2_reply", lambda p: p["model_parameters"]["distance"]))),
            ("param_get", listing, baseline,
             ("rename_d2", _recall("rename_d2", one_model_row(lambda: f"{driven(1)} + 1 mm",
                                                              "rename_d2_reply"))))]
    rows += geometry(False)
    rows += [("param_set", write({"name": first, "new_name": span}),
              renamed(lambda: first, lambda: span, everything,
                      lambda: {twice: (first + " * 2", span + " * 2"), driven(1): (first, span)}), None),
             ("param_get", listing, table_is(1), None),
             ("param_get", {"name": first}, _refused(f"Parameter not found: '{first}'."), None)]
    rows += geometry(True)
    rows += [("param_set", write(lambda c: {"name": _ctx_get(c, "rename_d1", "the depth parameter"),
                                            "new_name": depth}),
              renamed(lambda: driven(1), lambda: depth, stacked,
                      lambda: {driven(2): (f"{driven(1)} + 1 mm", depth + " + 1 mm")}), None),
             ("param_get", listing, table_is(2), None)]
    rows += geometry(True)
    rows += refusal({"name": twice, "new_name": span},
                    f"Cannot rename '{twice}' to '{span}': another parameter already has that name.",
                    "Nothing was renamed")
    rows += refusal({"name": span, "new_name": span},
                    f"'{span}' is already this parameter's name; nothing was renamed.")
    rows += refusal({"name": span, "new_name": "RenameOther", "expression": "12 mm"},
                    f"new_name 'RenameOther' only renames '{span}'; it was sent with expression '12 mm'.",
                    "Rename in one call and set the value in another.")
    # A name holding a space passes the tool's own checks; Fusion keeps the name and raises nothing.
    rows += refusal({"name": twice, "new_name": "bad name"},
                    f"Assigning 'bad name' raised no error but the parameter is still named '{twice}'",
                    "the rename did not take")
    rows += geometry(True)
    rows += [("param_set", write(lambda c: {"name": depth,
                                            "new_name": _ctx_get(c, "rename_d1", "the depth parameter")}),
              renamed(lambda: depth, lambda: driven(1), stacked,
                      lambda: {driven(2): (depth + " + 1 mm", f"{driven(1)} + 1 mm")}), None),
             ("param_get", listing, table_is(1), None),
             ("param_set", write({"name": span, "new_name": first}),
              renamed(lambda: span, lambda: first, everything,
                      lambda: {twice: (span + " * 2", first + " * 2"), driven(1): (span, first)}), None),
             ("param_get", listing, table_is(0), None)]
    rows += geometry(True)
    rows += [("doc_close", lambda c: {"name": _ctx_get(c, "rename_owned", "the rename scratch"),
                                      "save_changes": False, "expect_document": c["rename_owned"]},
              _document_closed, None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "rename_home", "the home session")},
              _activated(), None),
             ("doc_get", {}, lambda p: _home_address(p) == _RECALL.get("rename_home")
              and all(r.get("document_handle") != _RECALL.get("rename_owned") for r in p["open_documents"]),
              None)]
    return rows


def _derive_favorite_rows():
    """Derive one body with and without favourite parameters from a retained saved source."""
    name = "SweepDeriveFavorite." + _STAMP
    favorite, plain = "DeriveFav", "DerivePlain"
    listing = {"include_model_parameters": True}
    rows = [("doc_get", {}, _home_document, ("fav_home", _recall("fav_home", _home_address))),
            ("doc_new", lambda c: {"expect_document": c["fav_home"]}, _new_document,
             ("fav_source", _recall("fav_source", lambda p: p["document_handle"])))]

    def write(tool, args, check="ok", save=None, owner="fav_source"):
        rows.append((tool, lambda c, args=args, owner=owner: {
            **(args(c) if callable(args) else args), "expect_document": c[owner]}, check, save))

    def source_table(p):
        table = _parameter_table(p)
        users = (table or {}).get("user", {})
        return table if (table is not None and set(users) == {favorite, plain}
                         and users[favorite]["expression"] == "7 mm" and users[favorite]["favorite"] is True
                         and users[plain]["expression"] == "3 mm" and users[plain]["favorite"] is False) else None

    def cube(p):
        return _measured("the derived 10 mm cube", {k: p.get(k) for k in ("kind", "x", "y", "z", "mass")},
                         p.get("kind") == "design" and all(_near(p.get(a), 10, .0001) for a in "xyz")
                         and _near((p.get("mass") or {}).get("volume"), 1000, .001))

    def empty(p):
        return _measured("the host lists no parameter", _parameter_table(p),
                         _parameter_table(p) == {"user": {}, "model": {}})

    def landed(count):
        def check(p):
            names = p.get("imported_parameter_names")
            return _derived(name)(p) and _measured(
                f"{count} favourite parameter(s) imported by the derive",
                {k: p.get(k) for k in ("bodies_landed", "parameters_imported", "imported_parameter_names",
                                       "model_parameters_added", "parameter_warning", "parameters_unread")},
                p.get("bodies_landed") == 1 and p.get("parameters_imported") == count
                and isinstance(names, list) and len(names) == count
                and all(isinstance(n, str) and n for n in names)
                and (count == 0 or p.get("model_parameters_added") == 1)
                and not any(k in p for k in ("parameter_warning", "parameters_unread", "user_parameters_added",
                                             "imported_parameter_names_truncated")))
        return check

    def derived_row(p):
        table = _parameter_table(p)
        row = ((table or {}).get("model") or {}).get(_RECALL.get("fav_derived"))
        return _measured("the host lists exactly the imported name, at the source's 7 mm", table,
                         table is not None and table["user"] == {} and len(table["model"]) == 1
                         and row is not None and row["expression"] == "7 mm" and row["unit"] == "mm"
                         and _near(row["value"], 7, 1e-9))

    def derive(flag):
        return lambda c: {"document_id": c["fav_urn"], "source_bodies": [c["fav_body"]],
                          "include_parameters": False, "include_favorite_parameters": flag}

    write("param_add", {"name": favorite, "expression": "7 mm", "unit": "mm", "favorite": True},
          lambda p: p.get("added") is True and p.get("favorite") is True)
    write("param_add", {"name": plain, "expression": "3 mm", "unit": "mm"},
          lambda p: p.get("added") is True and p.get("favorite") is False)
    write("sketch_create", {"plane": "xy", "name": "DeriveFavSource"})
    write("sketch_add_geometry", {"sketch_name": "DeriveFavSource", "geometry": [
        {"kind": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]})
    write("model_extrude", {"sketch_name": "DeriveFavSource", "distance": 10, "operation": "new"},
          lambda p: _extruded(p) and len(p.get("result_bodies") or []) == 1,
          ("fav_body", _recall("fav_body", lambda p: p["result_bodies"][0])))
    write("doc_save_as", {"name": name, "project": PROJECT, "folder": FOLDER},
          _saved_as(name, FOLDER))
    rows += _settled(name, "fav_urn")
    rows.append(("data_get", lambda c: {"file": c["fav_urn"]},
                 _file_settled(FOLDER, file_key="fav_urn", file_name=name), None))
    rows.append(("param_get", listing, _retire_compare("fav_source_table", source_table, False), None))
    for host, flag, owner in (("fav_host_on", True, "fav_source"), ("fav_host_off", False, "fav_host_on")):
        write("doc_new", {}, _new_document, (host, _recall(host, lambda p: p["document_handle"])), owner=owner)
        rows.append(("param_get", listing, empty, None))
        write("doc_insert_derive", derive(flag), landed(1 if flag else 0),
              ("fav_derived", _recall("fav_derived", lambda p: p["imported_parameter_names"][0]))
              if flag else None, owner=host)
        rows += [("param_get", listing, derived_row if flag else empty, None),
                 ("model_inspect", {"include": ["default", "mass"], "units": "mm"}, cube, None)]
    write("doc_activate", lambda c: {"name": c["fav_source"]}, _activated(name), owner="fav_host_off")
    write("doc_close", lambda c: {"name": c["fav_host_off"], "save_changes": False}, _document_closed)
    write("doc_close", lambda c: {"name": c["fav_host_on"], "save_changes": False}, _document_closed)
    rows.append(("param_get", listing, _retire_compare("fav_source_table", source_table, True), None))
    write("doc_activate", lambda c: {"name": c["fav_home"]}, _activated())
    write("doc_close", lambda c: {"name": c["fav_source"], "save_changes": False},
          _document_closed, owner="fav_home")
    rows.append(("doc_get", {}, lambda p: _home_address(p) == _RECALL.get("fav_home")
                 and not {r.get("document_handle") for r in p["open_documents"]}
                 & {_RECALL.get(k) for k in ("fav_source", "fav_host_on", "fav_host_off")}, None))
    return rows


_CLOUD_DOC += _param_rename_rows() + _derive_favorite_rows()


# design_get's configuration cell table: its list key, then each cell's row id, column id and
# expression keys.
_CELL_TABLE_KEYS = ("cells", "row_id", "column_id", "expression")


def _configure_row_rows():
    """Copy and delete configuration rows on a retained saved coupon, re-reading the table each time."""
    name = "SweepConfigureRows." + _STAMP
    top, parameter = "Configuration 1", "ProbeW"
    body_read = {"include": ["default", "mass"], "units": "mm", "accuracy": "very_high", "per_body": True}

    def write(args):
        return lambda c: dict(args, expect_document=_ctx_get(c, "configure_owned", "the configuration coupon"))

    def saved(p):
        return (_document_is(name)(p) and _home_address(p) == _RECALL.get("configure_owned")
                and p["active"]["document_id"] == _RECALL.get("configure_urn"))

    def table(p):
        read = p.get("configurations") or {}
        rows, columns = read.get("configurations"), read.get("columns")
        if (not read.get("table_id") or read.get("truncated") or not isinstance(rows, list) or not rows
                or read.get("configuration_count") != len(rows)
                or any(not isinstance(r.get("name"), str) or not r.get("id") or not _num(r.get("index"))
                       or type(r.get("is_active")) is not bool for r in rows)
                or len({r["id"] for r in rows}) != len(rows)
                or [r["name"] for r in rows if r["is_active"]] != [read.get("active_configuration")]
                or any(a["index"] >= b["index"] for a, b in zip(rows, rows[1:]))
                or not isinstance(columns, list)
                or [(c.get("title"), c.get("type")) for c in columns]
                != [("Part Number", "ConfigurationPropertyColumn"), (parameter, "ConfigurationParameterColumn")]
                or not all(c.get("id") for c in columns) or columns[0]["id"] == columns[1]["id"]
                or columns[1]["id"] != _RECALL.get("cfgrow_column")):
            return None
        return {"table_id": read["table_id"], "columns": columns,
                "rows": [{k: r[k] for k in ("name", "id", "index", "is_active")} for r in rows]}

    def identities(state):
        return [(r["name"], r["id"]) for r in state["rows"]]

    def active(state):
        return next({"name": r["name"], "id": r["id"]} for r in state["rows"] if r["is_active"])

    def position(state, row):
        return [r["name"] for r in state["rows"]].index(row)

    def table_reads(label, want):
        def check(p):
            now, before = table(p), _RECALL.get("cfgrow_table")
            valid = (now is not None and before is not None and now["table_id"] == before["table_id"]
                     and now["columns"] == before["columns"] and bool(want(before, now)))
            if valid:
                _RECALL["cfgrow_table"] = now
            return _measured(label, {"before": before, "now": now}, valid)
        return ("design_get", {"include": ["configurations"]}, check, None)

    def base(p):
        state = table(p)
        valid = (state is not None and [r["name"] for r in state["rows"]] == [top, "B", "C"]
                 and [r["id"] for r in state["rows"][1:]] == [_RECALL.get("cfgrow_B"), _RECALL.get("cfgrow_C")]
                 and active(state)["name"] == "C")
        if valid:
            _RECALL["cfgrow_table"] = state
        return _measured("three rows in the order added, the last added active", state, valid)

    def same_rows(active_row):
        return lambda before, now: now["rows"] == [dict(r, is_active=r["name"] == active_row)
                                                   for r in before["rows"]]

    def unchanged(before, now):
        return now == before

    def inserted_after_b(adopted, key):
        def want(before, now):
            at = position(before, "B") + 1
            new = _RECALL.get(key) or {}
            return (identities(now) == identities(before)[:at] + [(adopted, new.get("id"))] + identities(before)[at:]
                    and now["rows"][:at] == before["rows"][:at] and now["rows"][at]["index"] == new.get("index")
                    and active(now) == active(before))
        return want

    def removed(row):
        def want(before, now):
            at = position(before, row)
            above = {k: before["rows"][at - 1][k] for k in ("name", "id")}
            return (at == len(before["rows"]) - 1 and identities(now) == identities(before)[:at]
                    and [r["index"] for r in now["rows"]] == [r["index"] for r in before["rows"][:at]]
                    and active(now) == (above if before["rows"][at]["is_active"] else active(before)))
        return want

    def activated(row, previous):
        return lambda p: _measured(f"'{row}' activated from '{previous}'", p,
                                   p.get("activated") is True and p.get("requested") == row
                                   and p.get("previous") == previous and p.get("now_active") == row
                                   and "timeline_warning" not in p)

    def copied(new_name, adopted):
        def check(p):
            before = _RECALL.get("cfgrow_table")
            names = [r["name"] for r in before["rows"]]
            at = names.index("B") + 1
            source = before["rows"][at - 1]
            cells, note = p.get("cells"), p.get("note") or ""
            width = [c for c in cells or [] if c.get("column_id") == _RECALL.get("cfgrow_column")]
            return _measured(
                f"'B' copied as '{adopted}' with an equal {parameter} cell and the active row kept",
                {k: p.get(k) for k in ("copied", "source", "configuration", "id", "index", "requested_name",
                                       "adopted_differs", "active_before", "active_after", "active_changed",
                                       "cells", "configurations")},
                p.get("copied") is True and p.get("source") == {k: source[k] for k in ("name", "id", "index")}
                and p.get("configuration") == adopted and isinstance(p.get("id"), str) and bool(p["id"])
                and p["id"] not in {r["id"] for r in before["rows"]} and _num(p.get("index"))
                and ((p.get("requested_name") == new_name and p.get("adopted_differs") is True)
                     if adopted != new_name else
                     ("requested_name" not in p and "adopted_differs" not in p))
                and p.get("active_before") == p.get("active_after") == active(before)
                and p.get("active_changed") is False and "active_unread" not in p
                and isinstance(cells, list)
                and [(c.get("column"), c.get("column_id")) for c in cells]
                == [(c["title"], c["id"]) for c in before["columns"]]
                and len(width) == 1 and width[0].get("equal") is True and "unread" not in width[0]
                and (width[0].get("source") or {}).get("expression") == "20 mm"
                and width[0]["source"] == width[0].get("copy")
                and not any(c.get("equal") is False for c in cells)
                and not any(k in p for k in ("verified", "cells_differ", "cells_unread", "cells_truncated",
                                             "configurations_truncated"))
                and p.get("configurations") == names[:at] + [adopted] + names[at:]
                and f"Configuration 'B' copied as '{adopted}'" in note
                and (f"not the requested '{new_name}'" in note) is (adopted != new_name))
        return check

    def deleted(row):
        def check(p):
            before = _RECALL.get("cfgrow_table")
            at = position(before, row)
            target, note = before["rows"][at], p.get("note") or ""
            after = ({k: before["rows"][at - 1][k] for k in ("name", "id")}
                     if target["is_active"] else active(before))
            return _measured(
                f"'{row}' deleted, the rows above it kept, the active row named",
                {k: p.get(k) for k in ("deleted", "remaining", "active_before", "active_after",
                                       "active_changed", "note")},
                at == len(before["rows"]) - 1
                and p.get("deleted") == {k: target[k] for k in ("name", "id", "index")}
                and p.get("remaining") == [{k: r[k] for k in ("name", "id", "index")}
                                           for r in before["rows"][:at]]
                and "remaining_truncated" not in p and "active_unread" not in p
                and p.get("active_before") == active(before) and p.get("active_after") == after
                and p.get("active_changed") is target["is_active"]
                and f"Configuration '{row}' deleted; this tool cannot restore a deleted configuration." in note
                and (f"It was the active one: '{after['name']}' is active now" in note) is target["is_active"]
                and ("read the model with design_get / param_get" in note) is target["is_active"])
        return check

    def width(expression, value):
        def state(p):
            return p if (_configure_parameters(p) is not None
                         and p["user_parameters"][0]["expression"] == expression
                         and _near(p["user_parameters"][0]["value"], value, 1e-9)) else None
        return state

    def stock(height):
        def state(p):
            now = _symmetric_target_body_state(p)
            return now if (now is not None and now["size"] == [10, 10, height]
                           and now["bounds"]["min_point"] == {"x": 0, "y": 0, "z": 0}
                           and now["bounds"]["max_point"] == {"x": 10, "y": 10, "z": height}
                           and _near(now["material"]["volume"], 100 * height, .001)) else None
        return state

    def witness(p):
        now = _symmetric_target_body_state(p)
        return now if (now is not None and now["size"] == [5, 5, 5]
                       and _near(now["material"]["volume"], 125, .001)) else None

    def held(tag, expression, height, after):
        return [("param_get", {}, _retire_compare("cfgrow_params" + tag, width(expression, height), after), None),
                ("model_inspect", _lit(dict(body_read, target="Body1")),
                 _retire_compare("cfgrow_Body1" + tag, stock(height), after), None)]

    def witness_read(after):
        return ("model_inspect", _lit(dict(body_read, target="Body2")),
                _retire_compare("cfgrow_Body2", witness, after), None)

    def cell_step(want):
        """Return the design_get cell-table read: the parameter column's expression per row name."""
        list_key, row_key, column_key, expression_key = _CELL_TABLE_KEYS

        def check(p):
            read = p.get("configurations") or {}
            names = {r.get("id"): r.get("name") for r in read.get("configurations") or []}
            cells = [c for c in read.get(list_key) or [] if c.get(column_key) == _RECALL.get("cfgrow_column")]
            got = {names.get(c.get(row_key)): c.get(expression_key) for c in cells}
            return _measured(f"the {parameter} column's cell expression per row", got,
                             len(cells) == len(want) and got == want)
        return ("design_get", {"include": ["configurations"]}, check, None)

    def configure(action, row, new_name=None):
        args = {"action": action, "name": row}
        return write(dict(args, new_name=new_name) if new_name else args)

    rows = [("doc_get", {}, _home_document, ("configure_home", _recall("configure_home", _home_address))),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "configure_home", "the home session")},
             _new_document, ("configure_owned", _recall("configure_owned", lambda p: p["document_handle"]))),
            ("design_activate_component", {"occurrence": "root"}, "ok", None),
            ("param_add", write({"name": parameter, "expression": "10 mm", "unit": "mm"}), "ok", None)]
    for sketch, x, side, distance, body in [("ConfigureRowStock", 0, 10, parameter, "Body1"),
                                            ("ConfigureRowWitness", 40, 5, "5 mm", "Body2")]:
        rows += [("sketch_create", write({"name": sketch, "plane": "xy"}), "ok", None),
                 ("sketch_add_geometry", write({"sketch_name": sketch, "units": "mm", "geometry": [
                     {"kind": "rectangle", "x1": x, "y1": 0, "x2": x + side, "y2": side}]}), "ok", None),
                 ("model_extrude", write({"sketch_name": sketch, "distance": distance, "units": "mm",
                                          "operation": "new"}),
                  lambda p, body=body: _extruded(p) and p.get("result_bodies") == [body], None)]
    rows += [("view_set", write({"action": "orient", "orientation": "iso-top-right", "fit": True}), "ok", None),
             ("doc_save_as", write({"name": name, "project": PROJECT, "folder": FOLDER, "create_path": False}),
              _saved_as(name, FOLDER), ("configure_urn", _recall("configure_urn", lambda p: p["document_id"]))),
             ("doc_get", {}, saved, None),
             ("design_configure", write({"action": "create"}),
              lambda p: p.get("configured") is True and p.get("created") is True
              and p.get("configurations") == [top], None)]
    for row, listed in (("B", [top, "B"]), ("C", [top, "B", "C"])):
        rows.append(("design_configure", configure("add_configuration", row),
                     lambda p, row=row, listed=listed: p.get("configuration") == row and bool(p.get("id"))
                     and p.get("active_configuration") == row and p.get("configurations") == listed,
                     ("cfgrow_" + row, _recall("cfgrow_" + row, lambda p: p["id"]))))
    rows += [("design_configure", write({"action": "add_parameter", "parameter": parameter,
                                         "values": {"B": "20 mm", "C": "30 mm"}}),
              lambda p: p.get("parameter") == parameter and p.get("set") == 2 and bool(p.get("column_id")),
              ("cfgrow_column", _recall("cfgrow_column", lambda p: p["column_id"]))),
             ("design_get", {"include": ["configurations"]}, base, None),
             cell_step({top: "10 mm", "B": "20 mm", "C": "30 mm"}),
             ("design_configure", configure("activate", top), activated(top, "C"), None),
             table_reads("the first row active, every row identity kept", same_rows(top))]
    rows += held("", "10 mm", 10, False) + [witness_read(False)]
    rows += [("design_configure", configure("copy_configuration", "B", "B2"), copied("B2", "B2"),
              ("cfgrow_B2", _recall("cfgrow_B2", lambda p: {"id": p["id"], "index": p["index"]}))),
             table_reads("the copy listed directly after its source", inserted_after_b("B2", "cfgrow_B2"))]
    rows += held("", "10 mm", 10, True) + [cell_step({top: "10 mm", "B": "20 mm", "B2": "20 mm", "C": "30 mm"})]
    rows += [("design_configure", configure("copy_configuration", "B", "B"), copied("B", "B (1)"),
              ("cfgrow_B1", _recall("cfgrow_B1", lambda p: {"id": p["id"], "index": p["index"]}))),
             table_reads("the adopted name listed directly after its source",
                         inserted_after_b("B (1)", "cfgrow_B1"))]
    rows += held("", "10 mm", 10, True) + [cell_step({top: "10 mm", "B": "20 mm", "B (1)": "20 mm",
                                                      "B2": "20 mm", "C": "30 mm"})]
    rows += [("design_configure", configure("delete_configuration", "C"), deleted("C"), None),
             table_reads("the deleted row gone, the others and the active row kept", removed("C"))]
    rows += held("", "10 mm", 10, True)
    rows += [("design_configure", configure("delete_configuration", top),
              _refused(f"Fusion refused deleting configuration '{top}':", "Cannot delete the first row",
                       f"The table reads unchanged (rows '{top}', 'B', 'B (1)', 'B2'; active '{top}')."), None),
             table_reads("the refused first-row delete leaves the table as read", unchanged)]
    rows += held("", "10 mm", 10, True)
    rows += [("design_configure", configure("delete_configuration", "NoSuchRow"),
              _refused(f"No configuration matched 'NoSuchRow'. Available: {top}, B, B (1), B2."), None),
             table_reads("the unknown row name leaves the table as read", unchanged),
             ("design_configure", configure("activate", "B2"), activated("B2", top), None),
             table_reads("the copy active, every row identity kept", same_rows("B2"))]
    rows += held("_copy", "20 mm", 20, False)
    rows += [("design_configure", configure("delete_configuration", "B2"), deleted("B2"), None),
             table_reads("the active row gone and the row above it active", removed("B2"))]
    rows += held("_copy", "20 mm", 20, True)
    rows += [("design_configure", configure("activate", top), activated(top, "B (1)"), None),
             table_reads("the first row active again under its first id", same_rows(top))]
    rows += held("", "10 mm", 10, True) + [witness_read(True),
                                           cell_step({top: "10 mm", "B": "20 mm", "B (1)": "20 mm"})]
    rows += [("doc_close", lambda c: {"name": _ctx_get(c, "configure_owned", "the coupon"), "save_changes": False,
                                      "expect_document": c["configure_owned"]}, _document_closed, None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "configure_home", "the home session")},
              _activated(), None),
             ("doc_get", {}, lambda p: _home_address(p) == _RECALL.get("configure_home")
              and all(r.get("document_handle") != _RECALL.get("configure_owned") for r in p["open_documents"]),
              None)]
    return rows


_CLOUD_CONFIGURE += _configure_row_rows()


def _configure_group_rows():
    """Suppress a collapsed timeline group per configuration on a retained saved coupon."""
    name = "SweepConfigureGroup." + _STAMP
    top, asked = "Configuration 1", "SweepCutGroup"
    body_read = {"include": ["default", "mass"], "units": "mm", "accuracy": "very_high", "per_body": True}
    timeline_read = {"include": ["timeline"], "include_suppressed": True, "max_results": 250}

    def group():
        return _RECALL.get("cfggrp_group")

    def write(args):
        return lambda c: dict(args(c) if callable(args) else args,
                              expect_document=_ctx_get(c, "configure_owned", "the configuration coupon"))

    def saved(p):
        return (_document_is(name)(p) and _home_address(p) == _RECALL.get("configure_owned")
                and p["active"]["document_id"] == _RECALL.get("configure_urn"))

    def flag(row):
        return row.get("is_suppressed", False)

    def rows_state(p):
        tl = p.get("timeline") or {}
        rows = tl.get("timeline")
        if (not isinstance(rows, list) or len(rows) != 5 or tl.get("truncated")
                or tl.get("count") != 5 or tl.get("returned") != 5 or tl.get("marker_position") != 5
                or tl.get("groups") != {group(): 4} or [r.get("index") for r in rows] != list(range(5))
                or any(not r.get("name") or not r.get("type") or type(flag(r)) is not bool for r in rows)
                or [i for i, r in enumerate(rows) if r.get("is_group") is True] != [2]
                or rows[2]["name"] != group() or rows[2]["type"] != "TimelineGroup"
                or rows[2].get("member_count") != 4 or rows[2].get("is_collapsed") is not True):
            return None
        return {"rows": [(r["name"], r["type"]) for r in rows], "group_index": rows[2]["index"],
                "group_suppressed": flag(rows[2]),
                "others_suppressed": [flag(r) for i, r in enumerate(rows) if i != 2]}

    def members_state(p):
        rows = (p.get("timeline") or {}).get("timeline")
        if (not isinstance(rows, list) or len(rows) != 4 or (p.get("timeline") or {}).get("truncated")
                or any(r.get("parent_group") != group() or not r.get("name")
                       or type(flag(r)) is not bool for r in rows)
                or [r["name"] for r in rows] != ["GroupCutA", _RECALL.get("cfggrp_cut_a"),
                                                 "GroupCutB", _RECALL.get("cfggrp_cut_b")]):
            return None
        return {"names": [r["name"] for r in rows], "suppressed": [flag(r) for r in rows]}

    def clear(extract, key):
        def state(p):
            now = extract(p)
            return now if (now is not None and not any(now[key])
                           and not now.get("group_suppressed")) else None
        return state

    def timeline_reads(after):
        return [("design_get", timeline_read,
                 _retire_compare("cfggrp_rows", clear(rows_state, "others_suppressed"), after), None),
                ("design_get", lambda c: dict(timeline_read, group=group()),
                 _retire_compare("cfggrp_members", clear(members_state, "suppressed"), after), None)]

    def block(volume):
        def state(p):
            now = _symmetric_target_body_state(p)
            return now if (now is not None and now["size"] == [40, 20, 10]
                           and now["bounds"]["min_point"] == {"x": 0, "y": 0, "z": 0}
                           and now["bounds"]["max_point"] == {"x": 40, "y": 20, "z": 10}
                           and _near(now["material"]["volume"], volume, .001)) else None
        return state

    def control(p):
        now = _symmetric_target_body_state(p)
        return now if (now is not None and now["size"] == [10, 10, 10]
                       and _near(now["material"]["volume"], 1000, .001)) else None

    def body(target):
        return _lit(dict(body_read, target=target))

    def bodies(after):
        return [("model_inspect", body("Body1"), _retire_compare("cfggrp_Body1", block(7500), after), None),
                ("model_inspect", body("Body2"), _retire_compare("cfggrp_Body2", control, after), None)]

    def table(p):
        state = _configure_table_state(p, top)
        cells = (state or {}).get("cells")
        return state if (state is not None and isinstance(cells, list)
                         and state.get("cell_count") == len(cells) == 2 * len(state["columns"])
                         and "cells_truncated" not in state and "cells_unread" not in state) else None

    def table_before(p):
        state = table(p)
        return state if (state is not None and [c["title"] for c in state["columns"]] == ["Part Number"]
                         and [r["name"] for r in state["configurations"]] == [top, "B"]
                         and state["configurations"][1]["id"] == _RECALL.get("cfggrp_B")) else None

    def table_with_column(p):
        state, before = table(p), _RECALL.get("cfggrp_table") or {}
        columns = (state or {}).get("columns") or []
        column = columns[-1] if columns else {}
        ids = [r["id"] for r in before.get("configurations") or []]
        cells = {c.get("row_id"): c.get("is_suppressed") for c in (state or {}).get("cells") or []
                 if c.get("column_id") == _RECALL.get("cfggrp_column")}
        return state if (state is not None and columns[:-1] == before.get("columns")
                         and state["configurations"] == before.get("configurations")
                         and column.get("title") == group() and column.get("type") == "ConfigurationSuppressColumn"
                         and column.get("id") == _RECALL.get("cfggrp_column")
                         and cells == {ids[0]: False, ids[1]: True}) else None

    def column_added(existed, suppressed_in):
        def check(p):
            before = _RECALL.get("cfggrp_table")
            rows = before["configurations"]
            timeline, members = _RECALL.get("cfggrp_rows"), _RECALL.get("cfggrp_members")
            note = p.get("note") or ""
            state = "was already in the table" if existed else "was added"
            return _measured(
                f"the group's suppress column {state}, only B's cell set, the first row still active",
                {k: p.get(k) for k in ("target_kind", "group", "column_id", "column_title", "column_existed",
                                       "suppressed_in", "cells", "active_configuration",
                                       "members_suppressed_now", "note")},
                p.get("target_kind") == "group"
                and p.get("group") == {"name": group(), "index": timeline["group_index"],
                                       "member_count": 4, "members": members["names"]}
                and isinstance(p.get("column_id"), str) and bool(p["column_id"])
                and ((p["column_id"] == _RECALL.get("cfggrp_column")) if existed else
                     (p["column_id"] not in {c["id"] for c in before["columns"]}))
                and p.get("column_title") == group() and p.get("column_existed") is existed
                and p.get("suppressed_in") == suppressed_in
                and p.get("cells") == [{"configuration": r["name"], "id": r["id"], "suppressed": r["name"] == "B"}
                                       for r in rows]
                and p.get("active_configuration") == {"name": top, "id": rows[0]["id"]}
                and not any(k in p for k in ("members_suppressed_now", "members_unread", "members_differ",
                                             "cells_failed", "cells_truncated", "active_unread"))
                and f"Suppress column '{group()}' {state} for timeline group '{group()}'" in note
                and "linked to its group by title only" in note
                and "That title is not the group's name" not in note
                and ("The model changes for 'B' when that configuration is activated" in note) is bool(suppressed_in)
                and ("No cell was set; name configurations in suppressed_in." in note) is (not suppressed_in))
        return check

    def activated(row, previous):
        return lambda p: _measured(f"'{row}' activated from '{previous}'", p,
                                   p.get("activated") is True and p.get("requested") == row
                                   and p.get("previous") == previous and p.get("now_active") == row
                                   and "timeline_warning" not in p)

    def group_suppressed(p):
        now, before = rows_state(p), _RECALL.get("cfggrp_rows")
        return _measured("the group row reads suppressed and no other row does", now,
                         now is not None and now == dict(before, group_suppressed=True))

    def members_suppressed(p):
        now, before = members_state(p), _RECALL.get("cfggrp_members")
        return _measured("every member of the group reads suppressed", now,
                         now is not None and now == dict(before, suppressed=[True] * 4))

    def suppress(feature, suppressed_in):
        return write(lambda c: {"action": "add_suppress", "feature": feature(), "suppressed_in": suppressed_in})

    class Qualified(_Refusal):
        """The refusal naming the group that a component was put in front of."""

        def __init__(self):
            super().__init__(())

        def missing(self, text):
            want = (f"'feature': 'NoSuchComponent/{group()}' puts a component in front of the timeline "
                    f"group '{group()}'", "a group takes no component qualifier")
            return [f for f in want if f not in text]

    def table_held():
        return ("design_get", {"include": ["configurations"]},
                _retire_compare("cfggrp_table_column", table_with_column, True), None)

    rows = [("doc_get", {}, _home_document, ("configure_home", _recall("configure_home", _home_address))),
            ("doc_new", lambda c: {"expect_document": _ctx_get(c, "configure_home", "the home session")},
             _new_document, ("configure_owned", _recall("configure_owned", lambda p: p["document_handle"]))),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)]
    for sketch, x, y, wide, deep, extra, made, key in [
            ("GroupBlock", 0, 0, 40, 20, {"operation": "new"}, ["Body1"], None),
            ("GroupCutA", 5, 5, 5, 5, {"operation": "cut", "symmetric": True}, None, "cfggrp_cut_a"),
            ("GroupCutB", 25, 5, 5, 5, {"operation": "cut", "symmetric": True}, None, "cfggrp_cut_b"),
            ("GroupControl", 60, 0, 10, 10, {"operation": "new"}, ["Body2"], None)]:
        rows += [("sketch_create", write({"name": sketch, "plane": "xy"}), "ok", None),
                 ("sketch_add_geometry", write({"sketch_name": sketch, "units": "mm", "geometry": [
                     {"kind": "rectangle", "x1": x, "y1": y, "x2": x + wide, "y2": y + deep}]}), "ok", None),
                 ("model_extrude", write(dict(extra, sketch_name=sketch, distance=10, units="mm")),
                  lambda p, made=made: _extruded(p) and (made is None or p.get("result_bodies") == made),
                  (key, _recall(key, lambda p: p["feature"])) if key else None)]
    rows += [("design_edit_timeline", write(lambda c: {
                  "action": "group", "feature": "GroupCutA", "name": asked,
                  "end_feature": _ctx_get(c, "cfggrp_cut_b", "the second cut feature")}),
              lambda p: _measured("the four cut rows grouped under the asked name", p,
                                  p.get("grouped") is True and p.get("group") == asked
                                  and p.get("member_count") == 4 and p.get("start_index") == 2
                                  and p.get("end_index") == 5 and p.get("groups") == 1
                                  and "name_warning" not in p),
              ("cfggrp_group", _recall("cfggrp_group", lambda p: p["group"]))),
             ("view_set", write({"action": "orient", "orientation": "iso-top-right", "fit": True}), "ok", None),
             ("doc_save_as", write({"name": name, "project": PROJECT, "folder": FOLDER, "create_path": False}),
              _saved_as(name, FOLDER), ("configure_urn", _recall("configure_urn", lambda p: p["document_id"]))),
             ("doc_get", {}, saved, None),
             ("design_configure", write({"action": "create"}),
              lambda p: p.get("configured") is True and p.get("created") is True
              and p.get("configurations") == [top], None),
             ("design_configure", write({"action": "add_configuration", "name": "B"}),
              lambda p: p.get("configuration") == "B" and bool(p.get("id"))
              and p.get("active_configuration") == "B" and p.get("configurations") == [top, "B"],
              ("cfggrp_B", _recall("cfggrp_B", lambda p: p["id"]))),
             ("design_configure", write({"action": "activate", "name": top}), activated(top, "B"), None)]
    rows += timeline_reads(False) + bodies(False)
    rows += [("design_get", {"include": ["configurations"]},
              _retire_compare("cfggrp_table", table_before, False), None),
             ("design_configure", suppress(group, ["B"]), column_added(False, ["B"]),
              ("cfggrp_column", _recall("cfggrp_column", lambda p: p["column_id"]))),
             ("design_get", {"include": ["configurations"]},
              _retire_compare("cfggrp_table_column", table_with_column, False), None)]
    rows += timeline_reads(True) + bodies(True)
    rows += [("design_configure", write({"action": "activate", "name": "B"}), activated("B", top), None),
             ("design_get", timeline_read, group_suppressed, None),
             ("design_get", lambda c: dict(timeline_read, group=group()), members_suppressed, None),
             ("model_inspect", body("Body1"),
              lambda p: _measured("the block without either cut, 8000 mm3", _symmetric_target_body_state(p),
                                  block(8000)(p) is not None), None),
             ("model_inspect", body("Body2"), _retire_compare("cfggrp_Body2", control, True), None),
             ("design_configure", write({"action": "activate", "name": top}), activated(top, "B"), None)]
    rows += timeline_reads(True) + bodies(True)
    rows += [("design_configure", suppress(group, ["NoSuchRow"]),
              _refused("No column was added - suppressed_in: No configuration matched 'NoSuchRow'. "
                       f"Available: {top}, B."), None),
             table_held(),
             ("design_configure", suppress(lambda: f"NoSuchComponent/{group()}", ["B"]), Qualified(), None),
             table_held(),
             ("design_configure", suppress(group, []), column_added(True, []), None),
             table_held()]
    rows += timeline_reads(True) + bodies(True)
    rows += [("doc_close", lambda c: {"name": _ctx_get(c, "configure_owned", "the coupon"), "save_changes": False,
                                      "expect_document": c["configure_owned"]}, _document_closed, None),
             ("doc_activate", lambda c: {"name": _ctx_get(c, "configure_home", "the home session")},
              _activated(), None),
             ("doc_get", {}, lambda p: _home_address(p) == _RECALL.get("configure_home")
              and all(r.get("document_handle") != _RECALL.get("configure_owned") for r in p["open_documents"]),
              None)]
    return rows


_CLOUD_CONFIGURE += _configure_group_rows()


def _cr_tree(p):
    """design_get tree: {full path: row} over the root's children, or None when cut or paths repeat."""
    tree = p.get("tree") or {}
    rows = tree.get("children")
    if not isinstance(rows, list) or tree.get("truncated") or tree.get("children_truncated"):
        return None
    by_path = {r.get("full_path"): r for r in rows}
    return by_path if len(by_path) == len(rows) and None not in by_path else None


def _cr_poses(p):
    """assembly_get poses: {occurrence name: row}, or None when two occurrences share a name."""
    rows = p.get("occurrences") or []
    by_name = {r.get("name"): r for r in rows}
    return by_name if len(by_name) == len(rows) == p.get("occurrence_count") else None


def _cr_pose_rows(p, key="occurrences", count_key="occurrence_count"):
    """Keep pose rows as a list when two occurrence names collide."""
    rows = p.get(key)
    return rows if isinstance(rows, list) and len(rows) == p.get(count_key) else None


def _cr_collision_break_probe(ctx):
    """Break one inserted PartB link without renaming it, recording before and after state."""
    urn = json.dumps(_ctx_get(ctx, "cr_urn_B", "the saved PartB lineage"))
    script = r'''import json
import adsk.core
import adsk.fusion

def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    outcome = {"marker": "W2N-CLOUD-BREAK", "expected_source": __EXPECTED_SOURCE__,
               "preflight_error": None, "break_answer": None, "break_error": None,
               "before": None, "after": None, "after_error": None}
    def census(root):
        rows = []
        for i in range(root.occurrences.count):
            occ = root.occurrences.item(i)
            point = occ.transform2.translation
            data_file = occ.documentReference.dataFile if occ.isReferencedComponent else None
            rows.append({"name": occ.name, "full_path": occ.fullPathName,
                         "source_id": data_file.id if data_file else None,
                         "is_reference": occ.isReferencedComponent,
                         "origin_mm": [point.x * 10.0, point.y * 10.0, point.z * 10.0]})
        return rows
    try:
        if design is None:
            raise RuntimeError("active product is not a Fusion design")
        root = design.rootComponent
        before = census(root)
        outcome["before"] = before
        targets = [root.occurrences.item(i) for i in range(root.occurrences.count)
                   if root.occurrences.item(i).isReferencedComponent is True
                   and root.occurrences.item(i).documentReference.dataFile is not None
                   and root.occurrences.item(i).documentReference.dataFile.id == __EXPECTED_SOURCE__
                   and abs(root.occurrences.item(i).transform2.translation.x * 10.0 - 250.0) < 0.001
                   and abs(root.occurrences.item(i).transform2.translation.y * 10.0) < 0.001
                   and abs(root.occurrences.item(i).transform2.translation.z * 10.0) < 0.001]
        originals = [root.occurrences.item(i) for i in range(root.occurrences.count)
                     if root.occurrences.item(i).isReferencedComponent is True
                     and root.occurrences.item(i).documentReference.dataFile is not None
                     and root.occurrences.item(i).documentReference.dataFile.id == __EXPECTED_SOURCE__
                     and abs(root.occurrences.item(i).transform2.translation.x * 10.0) < 0.001
                     and abs(root.occurrences.item(i).transform2.translation.y * 10.0) < 0.001
                     and abs(root.occurrences.item(i).transform2.translation.z * 10.0) < 0.001]
        if len(targets) != 1 or len(originals) != 1 or targets[0] == originals[0]:
            raise RuntimeError("expected one linked PartB at x=250 mm and a distinct linked PartB at x=0 mm")
    except Exception as exc:
        outcome["preflight_error"] = repr(exc)
    else:
        try:
            outcome["break_answer"] = targets[0].breakLink()
        except Exception as exc:
            outcome["break_error"] = repr(exc)
        try:
            outcome["after"] = census(design.rootComponent)
        except Exception as exc:
            outcome["after_error"] = repr(exc)
    print(json.dumps(outcome, sort_keys=True))
'''.replace("__EXPECTED_SOURCE__", urn)
    return {"script": script, "read_only": False}


def _cr_collision_membership_probe(_ctx):
    """Read held joint halves against each root occurrence after the link break."""
    return {"read_only": True, "script": r'''import json
import adsk.core
import adsk.fusion

def run(context):
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    result = {"marker": "W2N-CLOUD-MEMBERSHIP", "error": None, "joint_count": None,
              "occurrences": []}
    try:
        if design is None:
            raise RuntimeError("active product is not a Fusion design")
        root = design.rootComponent
        joints = []
        for collection_name in ("joints", "asBuiltJoints"):
            collection = getattr(root, collection_name)
            for i in range(collection.count):
                joint = collection.item(i)
                if joint.name == "CrJoint":
                    joints.append(joint)
        result["joint_count"] = len(joints)
        if len(joints) != 1:
            raise RuntimeError("expected exactly one root joint named CrJoint")
        joint = joints[0]
        one, two = joint.occurrenceOne, joint.occurrenceTwo
        for i in range(root.occurrences.count):
            occurrence = root.occurrences.item(i)
            point = occurrence.transform2.translation
            result["occurrences"].append({
                "name": occurrence.name, "full_path": occurrence.fullPathName,
                "origin_mm": [point.x * 10.0, point.y * 10.0, point.z * 10.0],
                "is_joint_member": (occurrence == one) is True or (occurrence == two) is True})
    except Exception as exc:
        result["error"] = repr(exc)
    print(json.dumps(result, sort_keys=True))
'''}


def _cr_collision_break_result(value):
    """Require one exact break and the measured duplicate path, retaining raw refusal details."""
    result = _script_reply(value)
    before, after = result.get("before") or [], result.get("after") or []

    def at_x(rows, x):
        return [row for row in rows if at_origin(row.get("origin_mm"), [x, 0.0, 0.0])]

    def at_origin(origin, expected):
        return (isinstance(origin, list) and len(origin) == 3
                and all(_near(got, want, 0.001) for got, want in zip(origin, expected)))

    source = result.get("expected_source")
    before_zero, before_far = at_x(before, 0.0), at_x(before, 250.0)
    after_zero, after_far = at_x(after, 0.0), at_x(after, 250.0)
    collision = (len(after_zero) == len(after_far) == 1
                 and after_zero[0].get("name") == after_far[0].get("name")
                 and after_zero[0].get("full_path") == after_far[0].get("full_path"))
    return _measured("native breakLink without rename, checked on both placed PartB rows", result,
                     result.get("marker") == "W2N-CLOUD-BREAK"
                     and result.get("preflight_error") is None
                     and result.get("break_error") is None
                     and result.get("break_answer") is True
                     and result.get("after_error") is None
                     and len(before_zero) == len(before_far) == 1
                     and before_zero[0].get("source_id") == source
                     and before_far[0].get("source_id") == source
                     and before_zero[0].get("is_reference") is True
                     and before_far[0].get("is_reference") is True
                     and len(after_zero) == len(after_far) == 1
                     and after_zero[0].get("source_id") == source
                     and after_zero[0].get("is_reference") is True
                     and after_far[0].get("source_id") is None
                     and after_far[0].get("is_reference") is False
                     and collision)


def _cr_collision_membership_result(value):
    """Require independent native equality to select only the original PartB placement."""
    result = _script_reply(value)
    rows = result.get("occurrences") or []
    zero = [row for row in rows if len(row.get("origin_mm") or []) == 3
            and _near(row["origin_mm"][0], 0.0, 0.001)
            and _near(row["origin_mm"][1], 0.0, 0.001)
            and _near(row["origin_mm"][2], 0.0, 0.001)]
    far = [row for row in rows if len(row.get("origin_mm") or []) == 3
           and _near(row["origin_mm"][0], 250.0, 0.001)
           and _near(row["origin_mm"][1], 0.0, 0.001)
           and _near(row["origin_mm"][2], 0.0, 0.001)]
    local = [row for row in rows if row.get("name") == _RECALL.get("cr_local")]
    return _measured("read-only native held-wrapper equality for the colliding occurrences", result,
                     result.get("marker") == "W2N-CLOUD-MEMBERSHIP"
                     and result.get("error") is None and result.get("joint_count") == 1
                     and len(zero) == len(far) == len(local) == 1
                     and zero[0].get("is_joint_member") is True
                     and far[0].get("is_joint_member") is False
                     and local[0].get("is_joint_member") is True)


def _component_reference_rows():
    """Copy a component as new, switch an inserted row, replace a reference and break a link."""
    names = {key: f"SweepRef{key}." + _STAMP for key in "ABC"}
    home = lambda c: _ctx_get(c, "cr_home", "the home session")
    host = lambda c: _ctx_get(c, "cr_host", "the host document")
    got = lambda key, what: (lambda c: _ctx_get(c, key, what))
    rows = [("doc_get", {}, _home_document, ("cr_home", _recall("cr_home", _home_address)))]

    def settled(key):
        """data_get arguments once the saved lineage under `key` resolves and reads complete."""
        def args(c):
            urn = _ctx_get(c, key, "a saved part")
            missing = (f"No cloud file resolves from '{urn}'. Tried: {urn}. "
                       "Get a lineage URN from data_get(project=<name>) ('id' on each file).")
            for i in range(_SETTLE_POLLS):
                failed, last = facade("call")("data_get", {"file": urn})
                if failed:
                    # _measured raises on any other refusal, which ends the story there.
                    _measured("only this part's pending resolution is retried", last,
                              last == missing)
                elif (last.get("state") or {}).get("is_complete") is True:
                    return {"file": urn}
                if i + 1 < _SETTLE_POLLS:
                    time.sleep(_SETTLE_GAP_S)
            raise AssertionError(f"{urn!r} did not read complete within the bound: {last!r}")
        return args

    def part(key, build, configure=False):
        doc = got("cr_doc_" + key, "the part document")
        write = lambda args: (lambda c: dict(args, expect_document=doc(c)))
        rows.extend([
            ("doc_new", lambda c: {"expect_document": home(c)}, _new_document,
             ("cr_doc_" + key, lambda p: p["document_handle"])),
            ("design_activate_component", {"occurrence": "root"}, "ok", None)])
        rows.extend((tool, write(args), check, None) for tool, args, check in build)
        rows.append(("doc_save_as", write({"name": names[key], "project": PROJECT, "folder": FOLDER,
                                           "create_path": False}), _saved_as(names[key], FOLDER),
                     ("cr_urn_" + key, _recall("cr_urn_" + key, lambda p: p["document_id"]))))
        if configure:
            rows.extend([
                ("design_configure", write({"action": "create"}),
                 lambda p: p.get("configured") is True and len(p.get("configurations") or []) == 1,
                 ("cr_row", _recall("cr_row", lambda p: p["configurations"][0]))),
                ("design_configure", write({"action": "add_configuration", "name": "Wide"}),
                 lambda p: p.get("active_configuration") == "Wide", None),
                ("design_configure", write({"action": "add_parameter", "parameter": "CrW",
                                            "values": {"Wide": "25 mm"}}),
                 lambda p: p.get("parameter") == "CrW" and p.get("set") == 1, None),
                ("design_configure", lambda c: {"action": "activate", "expect_document": doc(c),
                                                "name": _ctx_get(c, "cr_row", "the first row")},
                 "ok", None),
                # Converting a saved design moves it to a new lineage on its next save.
                ("doc_save", write({"description": "component reference coupon"}),
                 lambda p: p.get("saved") is True and bool((p.get("lineage_changed") or {}).get("to")),
                 ("cr_urn_" + key, _recall("cr_urn_" + key,
                                           lambda p: p["lineage_changed"]["to"])))])
        rows.extend([
            ("data_get", settled("cr_urn_" + key),
             lambda p: (p.get("state") or {}).get("is_complete") is True, None),
            ("doc_activate", lambda c: {"name": home(c), "expect_document": doc(c)},
             _activated(), None),
            ("doc_close", lambda c: {"name": doc(c), "save_changes": False,
                                     "expect_document": home(c)}, _document_closed, None)])

    def box(sketch, size, distance):
        return [("sketch_create", {"name": sketch, "plane": "xy"}, "ok"),
                ("sketch_add_geometry", {"sketch_name": sketch, "units": "mm", "geometry": [
                    {"kind": "rectangle", "x1": 0, "y1": 0, "x2": size, "y2": size}]}, "ok"),
                ("model_extrude", {"sketch_name": sketch, "distance": distance, "units": "mm",
                                   "operation": "new"}, _extruded)]
    part("A", box("CrASk", 20, 10))
    part("B", [("sketch_create", {"name": "CrBSk", "plane": "xy"}, "ok"),
               ("sketch_add_geometry", {"sketch_name": "CrBSk", "units": "mm", "geometry": [
                   {"kind": "circle", "cx": 0, "cy": 0, "radius": 5}]}, "ok"),
               ("model_extrude", {"sketch_name": "CrBSk", "distance": 30, "units": "mm",
                                  "operation": "new"}, _extruded)])
    part("C", [("param_add", {"name": "CrW", "expression": "10 mm", "unit": "mm"}, "ok")]
         + box("CrCSk", 20, "CrW"), configure=True)

    def write(tool, args, check="ok", save=None):
        rows.append((tool, lambda c, args=args: {**(args(c) if callable(args) else args),
                                                 "expect_document": host(c)}, check, save))

    def read(tool, args, check, save=None):
        rows.append((tool, args, check, save))
    tree_args = {"include": ["tree"], "tree_handles": True, "max_results": 200}
    at = lambda origin, want: (isinstance(origin, list) and len(origin) == 3
                               and all(_near(v, w, 0.001) for v, w in zip(origin, want)))
    pose_args = {"include": ["poses"], "max_joints": 100, "units": "mm"}

    def volume(key, want):
        read("model_inspect", lambda c: {"target": _ctx_get(c, key, "an occurrence"),
                                         "include": ["default", "mass"], "units": "mm"},
             lambda p: _measured(f"volume {want} mm3", (p.get("mass") or {}).get("volume"),
                                 _near((p.get("mass") or {}).get("volume"), want, 0.5)))

    def tree(label, check, save=None):
        read("design_get", tree_args,
             lambda p: _measured(label, sorted(_cr_tree(p) or []), _cr_tree(p) is not None
                                 and bool(check(_cr_tree(p), _RECALL))), save)

    def poses(label, check):
        read("assembly_get", pose_args,
             lambda p: _measured(label, {k: (v.get("origin"), v.get("joints"))
                                         for k, v in (_cr_poses(p) or {}).items()},
                                 _cr_poses(p) is not None and p.get("is_healthy") is True
                                 and p.get("broken_joints") == [] and bool(check(_cr_poses(p), _RECALL))))

    rows.extend([("doc_new", lambda c: {"expect_document": home(c)}, _new_document,
                  ("cr_host", lambda p: p["document_handle"])),
                 ("design_activate_component", {"occurrence": "root"}, "ok", None)])
    for key, urn, x in (("cr_a1", "cr_urn_A", 0), ("cr_a2", "cr_urn_A", 50), ("cr_c", "cr_urn_C", 100)):
        write("doc_insert_occurrence", lambda c, urn=urn, x=x: {
            "document_id": _ctx_get(c, urn, "a saved part"), "x": x, "units": "mm"},
            lambda p: p.get("inserted") is True and p.get("is_reference") is True,
            (key, _recall(key, lambda p: p["new_occurrence_name"])))
    write("model_create_component", {"name": "CrLocal", "y": 60, "units": "mm", "activate": True},
          lambda p: bool(p.get("full_path")), ("cr_local", _recall("cr_local", lambda p: p["full_path"])))
    for tool, args, check in box("CrLocalSk", 10, 10):
        write(tool, args, check)
    write("design_activate_component", {"occurrence": "root"})
    write("joint_create_as_built", lambda c: {
        "occurrence_one": _ctx_get(c, "cr_a1", "the first part"),
        "occurrence_two": _ctx_get(c, "cr_local", "the local component"),
        "joint_type": "rigid", "name": "CrJoint"})
    tree("four distinct children, two on part A", lambda t, r: len(t) == 4
         and all(t[r[k]].get("source_id") == r["cr_urn_A"] for k in ("cr_a1", "cr_a2"))
         and "is_reference" not in t[r["cr_local"]])

    # 1. An independent copy: refused on a reference, made from the local component.
    write("design_add_instance", lambda c: {"component": _ctx_get(c, "cr_a1", "the first part"),
                                            "independent": True},
          _refused("is an external reference", "action='break_link'"))
    write("design_add_instance", lambda c: {"component": _ctx_get(c, "cr_local", "the local one"),
                                            "independent": True, "y": 90, "units": "mm"},
          lambda p: p.get("independent") is True and bool(p.get("new_component"))
          and p.get("new_component") != "CrLocal",
          ("cr_copy", _recall("cr_copy", lambda p: p["full_path"])))
    tree("one more child, a local component of its own", lambda t, r: len(t) == 5
         and "is_reference" not in t[r["cr_copy"]] and t[r["cr_copy"]].get("body_count") == 1
         and t[r["cr_copy"]].get("component") != t[r["cr_local"]].get("component"))
    volume("cr_copy", 1000)
    volume("cr_local", 1000)

    # 2. Switch the inserted configuration to its other row; the occurrence takes the row's name.
    switch = lambda c, **args: {"action": "switch_occurrence", **args}
    volume("cr_c", 4000)
    write("design_configure", lambda c: switch(c, occurrence=_ctx_get(c, "cr_local", "local"),
                                               name="Wide"),
          _refused("is not an inserted configuration"))
    write("design_configure", lambda c: switch(c, occurrence=_ctx_get(c, "cr_c", "the row"),
                                               name="Tall"), _refused("Got 'Tall'. Rows:", "Wide"))
    write("design_configure", lambda c: switch(c, occurrence=_ctx_get(c, "cr_c", "the row"),
                                               name="Wide"),
          lambda p: p.get("switched") is True and p.get("row") == "Wide"
          and p.get("row_before") == _RECALL.get("cr_row") and p.get("old_path_resolves") is False,
          ("cr_c2", _recall("cr_c2", lambda p: p["occurrence"])))
    volume("cr_c2", 10000)
    tree("the switched occurrence under its new path only",
         lambda t, r: len(t) == 5 and r["cr_c2"] in t and r["cr_c"] not in t)
    poses("the switched occurrence kept its place",
          lambda o, r: at(o[r["cr_c2"]].get("origin"), [100.0, 0.0, 0.0]))

    # 3. Replace the jointed part A occurrence by part B; its sibling stays on A.
    replace = lambda c, occurrence, urn: {"action": "replace",
                                          "occurrence": _ctx_get(c, occurrence, "an occurrence"),
                                          "file": _ctx_get(c, urn, "a saved part")}
    write("doc_update_xref", lambda c: replace(c, "cr_local", "cr_urn_B"),
          _refused("is a local component, not an external reference"))
    write("doc_update_xref", lambda c: replace(c, "cr_a1", "cr_urn_A"),
          _refused("already references that file"))
    write("doc_update_xref", lambda c: replace(c, "cr_a1", "cr_urn_B"),
          lambda p: p.get("replaced") is True and len(p.get("occurrences") or []) == 1
          and p["occurrences"][0].get("path_before") == _RECALL.get("cr_a1")
          and p["occurrences"][0].get("old_path_resolves") is False,
          ("cr_b1", _recall("cr_b1", lambda p: p["occurrences"][0]["path"])))
    tree("the replaced occurrence on part B, its sibling still on part A",
         lambda t, r: len(t) == 5 and t[r["cr_b1"]].get("source_id") == r["cr_urn_B"]
         and t[r["cr_b1"]].get("is_reference") is True
         and t[r["cr_a2"]].get("source_id") == r["cr_urn_A"] and r["cr_a1"] not in t)
    volume("cr_b1", 2356.19)
    poses("the joint followed the replaced occurrence, which kept its place",
          lambda o, r: at(o[r["cr_b1"]].get("origin"), [0.0, 0.0, 0.0])
          and {name for name, row in o.items() if "CrJoint" in (row.get("joints") or [])}
          == {r["cr_b1"], r["cr_local"]})

    # 4. Break the last link to part A under a new, unique component name.
    unlink = lambda c, **args: {"action": "break_link",
                                "occurrence": _ctx_get(c, "cr_a2", "the second part"), **args}
    write("doc_update_xref", lambda c: unlink(c), _refused("needs 'new_name'"))
    write("doc_update_xref", lambda c: unlink(c, new_name="CrLocal"),
          _refused("A component named 'CrLocal' already exists"))
    write("doc_update_xref", lambda c: unlink(c, new_name="CrLoose"),
          lambda p: p.get("broken") is True and p.get("component") == "CrLoose"
          and p.get("reversible") is False and p.get("path_before") == _RECALL.get("cr_a2"),
          ("cr_loose", _recall("cr_loose", lambda p: p["occurrence"])))
    tree("the unlinked occurrence is local under its new name; the reference to B is untouched",
         lambda t, r: len(t) == 5 and "is_reference" not in t[r["cr_loose"]]
         and t[r["cr_loose"]].get("component") == "CrLoose"
         and t[r["cr_loose"]].get("body_count") == 1 and r["cr_a2"] not in t
         and t[r["cr_b1"]].get("source_id") == r["cr_urn_B"])
    volume("cr_loose", 4000)
    poses("the unlinked occurrence kept its place and carries no joint",
          lambda o, r: at(o[r["cr_loose"]].get("origin"), [50.0, 0.0, 0.0])
          and not o[r["cr_loose"]].get("joints"))

    # 5. Reuse the already-saved PartB lineage for a second placed reference. All public create and
    # reference-edit checks above finish before the native break below; the coupon closes unsaved.
    write("doc_insert_occurrence", lambda c: {
        "document_id": _ctx_get(c, "cr_urn_B", "the saved PartB lineage"),
        "x": 250, "units": "mm"},
        lambda p: p.get("inserted") is True and p.get("is_reference") is True,
        ("cr_b2", _recall("cr_b2", lambda p: p["new_occurrence_name"])))
    tree("the second reference uses the same PartB lineage at x=250 mm",
         lambda t, r: len(t) == 6
         and t[r["cr_b1"]].get("source_id") == r["cr_urn_B"]
         and t[r["cr_b2"]].get("source_id") == r["cr_urn_B"]
         and t[r["cr_b2"]].get("is_reference") is True)
    volume("cr_b2", 2356.19)
    poses("the second PartB reference is placed at x=250 mm before break",
          lambda o, r: at(o[r["cr_b2"]].get("origin"), [250.0, 0.0, 0.0]))

    write("sys_execute_script", _cr_collision_break_probe, _cr_collision_break_result)
    read("sys_execute_script", _cr_collision_membership_probe,
         _cr_collision_membership_result)

    def collision_rows(p, key="occurrences", count_key="occurrence_count"):
        rows = _cr_pose_rows(p, key, count_key)
        return rows

    def collision_claim(p, key="occurrences", count_key="occurrence_count"):
        rows = collision_rows(p, key, count_key)
        local_name = _RECALL.get("cr_local")
        if rows is None or not local_name:
            return False
        zero = [row for row in rows if at(row.get("origin"), [0.0, 0.0, 0.0])]
        far = [row for row in rows if at(row.get("origin"), [250.0, 0.0, 0.0])]
        local = [row for row in rows if row.get("name") == local_name]
        return (len(zero) == len(far) == len(local) == 1
                and zero[0].get("name") == far[0].get("name")
                and zero[0].get("joints") == ["CrJoint"]
                and far[0].get("joints") == []
                and local[0].get("joints") == ["CrJoint"]
                and all("joints_unverified" not in row for row in (zero[0], far[0], local[0])))

    read("assembly_get", {"include": ["poses"], "max_occurrences": 100,
                           "max_joints": 100, "units": "mm"},
         lambda p: _measured("top-level pose rows attribute CrJoint only to the original PartB",
                             [(row.get("name"), row.get("origin"), row.get("joints"))
                              for row in p.get("occurrences") or []],
                             p.get("is_healthy") is True and p.get("broken_joints") == []
                             and p.get("occurrences_truncated") is False
                             and p.get("occurrence_count") == 6
                             and collision_claim(p)))
    read("assembly_get", {"include": ["poses", "all_occurrences"],
                           "max_occurrences": 100, "max_all_occurrences": 100,
                           "max_joints": 100, "units": "mm"},
         lambda p: _measured("complete all-occurrences rows preserve the same wrapper attribution",
                             [(row.get("name"), row.get("origin"), row.get("joints"))
                              for row in p.get("all_occurrences") or []],
                             p.get("is_healthy") is True and p.get("broken_joints") == []
                             and p.get("occurrences_truncated") is False
                             and p.get("all_occurrences_truncated") is False
                             and p.get("occurrence_count") == p.get("all_occurrence_count") == 6
                             and collision_claim(p, "all_occurrences", "all_occurrence_count")))
    rows.extend([
        ("doc_activate", lambda c: {"name": home(c), "expect_document": host(c)}, _activated(), None),
        ("doc_close", lambda c: {"name": host(c), "save_changes": False,
                                 "expect_document": home(c)}, _document_closed, None),
        ("doc_get", {}, lambda p: _home_address(p) == _RECALL.get("cr_home"), None)])
    return rows


_CLOUD_CONFIGURE += _component_reference_rows()


# --- ACT 11h: A PLACED COMPONENT PUBLISHED AS A LOCAL DESIGN -------------------------------
_COMPONENT_COPY_NAME = "SweepComponentCopy " + _STAMP
_COMPONENT_COPY_FIXTURE = '''import adsk.core, adsk.fusion, json, math
def run(context):
    app = adsk.core.Application.get()
    doc = app.activeDocument
    design = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
    if design is None:
        raise RuntimeError('Component copy fixture has no Design product')
    root = design.rootComponent
    if doc.isSaved or root.occurrences.count or root.bRepBodies.count or design.timeline.count:
        raise RuntimeError('Component copy fixture requires a new empty design')
    def part(name, matrix, w, h, d):
        occ = root.occurrences.addNewComponent(matrix)
        comp = occ.component
        comp.name = name
        sketch = comp.sketches.add(comp.xYConstructionPlane)
        sketch.name = name + 'Profile'
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(
            adsk.core.Point3D.create(0, 0, 0), adsk.core.Point3D.create(w, h, 0))
        if sketch.profiles.count != 1:
            raise RuntimeError('Fixture sketch has no unique profile')
        ext = comp.features.extrudeFeatures.createInput(
            sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        if ext.setDistanceExtent(False, adsk.core.ValueInput.createByReal(d)) is not True:
            raise RuntimeError('Fixture extent refused')
        feature = comp.features.extrudeFeatures.add(ext)
        if feature is None or feature.bodies.count != 1:
            raise RuntimeError('Fixture extrusion refused')
        feature.bodies.item(0).name = name + 'Body'
        return occ
    placed = adsk.core.Matrix3D.create()
    if placed.setToRotation(math.radians(31), adsk.core.Vector3D.create(0, 0, 1),
                            adsk.core.Point3D.create(0, 0, 0)) is not True:
        raise RuntimeError('Fixture placement refused')
    placed.translation = adsk.core.Vector3D.create(7, 3, 5)
    chosen = part('CopyPart', placed, 3, 4, 2)
    part('CopyControl', adsk.core.Matrix3D.create(), 1, 2, 3)
    print(json.dumps({'occurrence': chosen.entityToken, 'path': chosen.fullPathName,
                      'component': chosen.component.name}))
'''

_COMPONENT_COPY_READ = '''import adsk.core, adsk.fusion, json
def run(context):
    app = adsk.core.Application.get()
    doc = app.activeDocument
    design = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
    if design is None:
        raise RuntimeError('Component copy read has no Design product')
    root = design.rootComponent
    def shape(body):
        return {'name': body.name, 'solid': body.isSolid,
                'volume_cm3': body.getPhysicalProperties(
                    adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy).volume,
                'vertices_cm': sorted([v.geometry.asArray() for v in body.vertices])}
    occurrences = []
    for occ in root.allOccurrences:
        occurrences.append({'path': occ.fullPathName, 'component': occ.component.name,
                            'frame': list(occ.transform2.asArray()),
                            'local_bodies': [shape(b) for b in occ.component.bRepBodies]})
    try:
        data_file = doc.dataFile
    except Exception:
        data_file = None
    print(json.dumps({'name': doc.name, 'saved': doc.isSaved, 'modified': doc.isModified,
        'document_id': data_file.id if data_file is not None else None,
        'root_bodies': [shape(b) for b in root.bRepBodies], 'occurrences': occurrences,
        'timeline': [{'name': design.timeline.item(i).name,
                      'health': int(design.timeline.item(i).healthState)}
                     for i in range(design.timeline.count)],
        'parameters': sorted([{'name': p.name, 'expression': p.expression, 'value': p.value}
                             for p in design.allParameters], key=lambda p: p['name'])}))
'''


def _component_copy_fixture(p):
    """Require the fixture to choose one exact occurrence in a two-part design."""
    row = _script_reply(p)
    return _measured("two-part component-copy fixture selected one occurrence",
                     row, bool(row.get("occurrence")) and row.get("component") == "CopyPart"
                     and row.get("path") == "CopyPart:1")


def _component_copy_before(p):
    """Record an independent source geometry and history baseline."""
    row = _script_reply(p)
    occs = row.get("occurrences") or []
    chosen = next((o for o in occs if o.get("component") == "CopyPart"), {})
    control = next((o for o in occs if o.get("component") == "CopyControl"), {})
    frame = chosen.get("frame") or []
    _RECALL["cc_source_before"] = row
    _RECALL["cc_selected_local"] = (chosen.get("local_bodies") or [None])[0]
    _RECALL["cc_selected_history"] = [t for t in row.get("timeline") or []
                                       if t.get("name") in ("CopyPartProfile", "Extrude1")]
    return _measured("source has placed chosen part and separate control",
                     {"occurrences": occs, "timeline": row.get("timeline"),
                      "parameters": row.get("parameters")},
                     row.get("saved") is False and row.get("modified") is True
                     and len(occs) == 2 and len(frame) == 16
                     and _near(frame[3], 7, 1e-8) and _near(frame[7], 3, 1e-8)
                     and _near(frame[11], 5, 1e-8)
                     and len(chosen.get("local_bodies") or []) == 1
                     and len(control.get("local_bodies") or []) == 1
                     and len(row.get("timeline") or []) == 6
                     and len(row.get("parameters") or []) == 4)


def _component_copy_source_unchanged(p):
    """Compare a fresh native read to the pre-publication source snapshot."""
    row = _script_reply(p)
    before = _RECALL.get("cc_source_before")
    return _measured("component publication kept source geometry, placement and history",
                     {"before": before, "after": row}, row == before)


def _component_copy_started(p):
    """Require a held future with no claimed cloud lineage at start."""
    return _measured("component copy started without a claimed finished file",
                     {"copy_started": p.get("copy_started"), "upload_handle": p.get("upload_handle"),
                      "requested_name": p.get("requested_name"),
                      "destination_folder": p.get("destination_folder")},
                     p.get("copy_started") is True and bool(p.get("upload_handle"))
                     and p.get("requested_name") == _COMPONENT_COPY_NAME
                     and p.get("destination_folder") == FOLDER
                     and "copied_id" not in p and "file_id" not in p)


def _component_copy_finished(p):
    """Require the existing poller to read exact completed component publication."""
    return _measured("component copy settled with an exact cloud lineage",
                     {k: p.get(k) for k in ("state", "operation", "file_id", "file_name",
                                              "destination_folder", "source_component")},
                     p.get("state") == "complete" and p.get("operation") == "component_copy"
                     and str(p.get("file_id") or "").startswith("urn:")
                     and p.get("file_name") == _COMPONENT_COPY_NAME
                     and p.get("destination_folder") == FOLDER
                     and p.get("source_component") == "CopyPart")


def _component_copy_cloud(p):
    """Read the completed file through data_get rather than trusting the poller's echo."""
    f, loc, state = p.get("file") or {}, p.get("location") or {}, p.get("state") or {}
    return _measured("published file independently reads in the intended folder",
                     {"file": f, "location": loc, "state": state},
                     f.get("name") == _COMPONENT_COPY_NAME
                     and f.get("id") == _RECALL.get("cc_copy_id")
                     and (loc.get("parent_folder") or {}).get("path") == FOLDER
                     and state.get("is_complete") is True)


def _component_copy_opened(p):
    """Compare the reopened design's raw geometry and history to the chosen local part."""
    row = _script_reply(p)
    before = _RECALL.get("cc_source_before") or {}
    selected = _RECALL.get("cc_selected_local")
    timeline = row.get("timeline") or []
    parameters = row.get("parameters") or []
    source_timeline = before.get("timeline") or []
    source_parameters = before.get("parameters") or []
    return _measured("reopened copy retains component-local geometry and editable history",
                     {"copy": row, "source_selected_body": selected},
                     row.get("document_id") == _RECALL.get("cc_copy_id")
                     and row.get("name") == _COMPONENT_COPY_NAME
                     and row.get("saved") is True and row.get("modified") is False
                     and row.get("root_bodies") == [selected]
                     and row.get("occurrences") == []
                     and len(timeline) == 2 and all(t.get("health") == 0 for t in timeline)
                     and [t.get("name") for t in timeline] ==
                     [t.get("name") for t in source_timeline[1:3]]
                     and len(parameters) == 2
                     and parameters == source_parameters[:2])


_CLOUD_COMPONENT_COPY = [
    ("doc_get", {}, _home_document, ("cc_home", _recall("cc_home", _home_address))),
    ("doc_new", {}, _new_document, ("cc_source", _recall("cc_source", lambda p: p["document_handle"]))),
    ("sys_execute_script", {"script": _COMPONENT_COPY_FIXTURE, "read_only": False},
     _component_copy_fixture, ("cc_occurrence", lambda p: _script_reply(p)["occurrence"])),
    ("sys_execute_script", {"script": _COMPONENT_COPY_READ, "read_only": True},
     _component_copy_before, None),
    ("doc_copy", lambda c: {"occurrence": _ctx_get(c, "cc_occurrence", "selected component"),
                             "name": _COMPONENT_COPY_NAME, "project": PROJECT, "folder": FOLDER,
                             "expect_document": _ctx_get(c, "cc_source", "source scratch")},
     _component_copy_started, ("cc_upload", lambda p: p["upload_handle"])),
    ("data_get_upload_status", lambda c: {"handle": _ctx_get(c, "cc_upload", "copy future")},
     _component_copy_finished, ("cc_copy_id", _recall("cc_copy_id", lambda p: p["file_id"]))),
    ("data_get", lambda c: {"file": _ctx_get(c, "cc_copy_id", "copy lineage")},
     _component_copy_cloud, None),
    ("sys_execute_script", {"script": _COMPONENT_COPY_READ, "read_only": True},
     _component_copy_source_unchanged, None),
    ("doc_open", lambda c: {"file_id": _ctx_get(c, "cc_copy_id", "copy lineage"),
                            "force_api_open": True,
                            "expect_document": _ctx_get(c, "cc_source", "source scratch")},
     _opened(_COMPONENT_COPY_NAME, lambda: _RECALL.get("cc_copy_id")),
     ("cc_copy_session", _recall("cc_copy_session", lambda p: p["document_handle"]))),
    ("sys_execute_script", {"script": _COMPONENT_COPY_READ, "read_only": True},
     _component_copy_opened, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "cc_source", "source scratch")},
     _activated(), None),
    ("sys_execute_script", {"script": _COMPONENT_COPY_READ, "read_only": True},
     _component_copy_source_unchanged, None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "cc_copy_session", "copy document"),
                              "save_changes": False,
                              "expect_document": _ctx_get(c, "cc_source", "source scratch")},
     _document_closed, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "cc_home", "home document")},
     _activated(), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "cc_source", "source scratch"),
                              "save_changes": False,
                              "expect_document": _ctx_get(c, "cc_home", "home document")},
     _document_closed, None),
    ("doc_get", {}, lambda p: _home_address(p) == _RECALL.get("cc_home")
     and p.get("open_count") >= 1 and all(
         r.get("document_handle") not in {_RECALL.get("cc_source"),
                                          _RECALL.get("cc_copy_session")}
         for r in p.get("open_documents") or []), None),
]
