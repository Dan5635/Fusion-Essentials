# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Owned Rendering family rows and a bounded local-job boundary poll."""

import math
import os
import struct
import time
import uuid
import zlib

from verify_core import EXPORT_DIR, NOTE_MAX, _RECALL, _ctx_get, _measured, _recall, _refused, facade
from verify_core import _activated as _document_activated
from verify_core import _document_closed, _home_address, _home_document, _new_document


_PNG_PATH = EXPORT_DIR + "/render-local-" + uuid.uuid4().hex + ".png"
_JPEG_PATH = EXPORT_DIR + "/render-local-" + uuid.uuid4().hex + ".jpg"
_TIFF_PATH = EXPORT_DIR + "/render-local-" + uuid.uuid4().hex + ".tiff"
_NAMED_PATH = EXPORT_DIR + "/render-named-" + uuid.uuid4().hex + ".png"
_TRANSPARENT_PATH = EXPORT_DIR + "/render-transparent-" + uuid.uuid4().hex + ".png"
_REFUSED_PATH = EXPORT_DIR + "/render-refused-" + uuid.uuid4().hex + ".png"
_CANVAS_PATH = EXPORT_DIR + "/render-canvas-" + uuid.uuid4().hex + ".png"
_SIZE = (256, 256)


def _same_path(left, right):
    """Compare Windows paths after the native API normalizes their separators."""
    return isinstance(left, str) and isinstance(right, str) and (
        os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right)))


def _png_on_disk(path):
    """Read a PNG's signature, first IHDR and terminal chunk from the actual file."""
    with open(path, "rb") as image:
        header = image.read(33)
        image.seek(-12, os.SEEK_END)
        trailer = image.read(12)
    width, height = struct.unpack(">II", header[16:24]) if len(header) == 33 else (0, 0)
    return {"bytes": os.path.getsize(path), "width": width, "height": height,
            "color_type": header[25] if len(header) == 33 else None,
            "signature": header[:8] == b"\x89PNG\r\n\x1a\n",
            "ihdr": header[12:16] == b"IHDR" and header[8:12] == b"\x00\x00\x00\x0d"
            and len(header) == 33 and struct.unpack(">I", header[29:33])[0]
            == zlib.crc32(header[12:29]),
            "iend": trailer == b"\x00\x00\x00\x00IEND\xaeB`\x82"}


def _verified_png(path, report, width=None, height=None):
    """Compare a tool's image report with the file's independent header read."""
    try:
        disk = _png_on_disk(path)
    except (OSError, ValueError, struct.error):
        disk = None
    return _measured("rendered PNG on disk", {"report": report, "disk": disk},
                     isinstance(report, dict) and report.get("status") == "valid"
                     and report.get("format") == "png" and disk is not None
                     and disk["bytes"] > 45 and disk["bytes"] == report.get("bytes")
                     and disk["signature"] and disk["ihdr"] and disk["iend"]
                     and disk["width"] == report.get("width")
                     and disk["height"] == report.get("height")
                     and (width is None or disk["width"] == width)
                     and (height is None or disk["height"] == height))


def _png_alpha_census(path):
    """Count fully transparent and visible pixels of an 8-bit RGBA PNG from its inflated rows."""
    with open(path, "rb") as image:
        data = image.read()
    position, packed, header = 8, b"", None
    while data[:8] == b"\x89PNG\r\n\x1a\n" and position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", data[position + 8:position + 8 + length])
        elif kind == b"IDAT":
            packed += data[position + 8:position + 8 + length]
        position += 12 + length
    if header is None or header[2:] != (8, 6, 0, 0, 0):
        return None
    width, height = header[:2]
    raw = zlib.decompress(packed)
    if len(raw) != height * (width * 4 + 1):
        return None
    above, transparent = [0] * width, 0
    for row in range(height):
        start = row * (width * 4 + 1)
        kind, line, left, corner = raw[start], [], 0, 0
        if kind > 4:
            return None
        for x, up in enumerate(above):
            # A filter predicts a byte from the same channel, so alpha is rebuilt from alpha alone.
            if kind == 4:
                estimate = left + up - corner
                distance = (abs(estimate - left), abs(estimate - up), abs(estimate - corner))
                guess = (left, up, corner)[distance.index(min(distance))]
            else:
                guess = (0, left, up, (left + up) // 2)[kind]
            left, corner = (raw[start + 4 + 4 * x] + guess) & 255, up
            line.append(left)
        above = line
        transparent += line.count(0)
    return {"width": width, "height": height, "transparent": transparent,
            "visible": width * height - transparent}


def _transparent_background(path, size):
    """Require decoded pixels: some fully transparent, some visible, at the requested size."""
    try:
        census = _png_alpha_census(path)
    except (OSError, ValueError, struct.error, zlib.error):
        census = None
    return _measured("transparent and visible pixels decoded from the rendered PNG", census,
                     census is not None and (census["width"], census["height"]) == size
                     and census["transparent"] > 0 and census["visible"] > 0)


def _verified_image(path, report, size):
    """Compare the reported file with independently read bytes and dimensions."""
    if not isinstance(report, dict):
        return False
    if path.lower().endswith(".png"):
        verified = _verified_png(path, report, *size)
        if _same_path(path, _TRANSPARENT_PATH):
            return verified and _transparent_background(path, size)
        return verified and (not _same_path(path, _NAMED_PATH)
                             or _png_on_disk(path)["color_type"] == 6)
    try:
        with open(path, "rb") as image:
            start = image.read(4)
            image.seek(-2, os.SEEK_END)
            end = image.read(2)
        length = os.path.getsize(path)
    except OSError:
        return False
    jpeg = path.lower().endswith(".jpg") and start[:2] == b"\xff\xd8" and end == b"\xff\xd9"
    tiff = path.lower().endswith(".tiff") and start in (b"II*\x00", b"MM\x00*")
    fmt = "jpeg" if jpeg else "tiff" if tiff else None
    return _measured("render image signature and size on disk; dimensions as reported",
                     {"path": path, "bytes": length},
                     fmt is not None and report.get("status") == "valid"
                     and report.get("format") == fmt and report.get("bytes") == length
                     and (report.get("width"), report.get("height")) == size)


def _started(p, path=_PNG_PATH):
    job = p.get("job") or {}
    return _measured("local image job launched", p,
                     p.get("mode") == "local" and isinstance(p.get("job_id"), str)
                     and bool(p["job_id"]) and _same_path(p.get("file_path"), path)
                     and job.get("valid") is True
                     and job.get("state") in ("queued", "processing", "finished")
                     and type(job.get("state_value")) is int
                     and _same_path(job.get("filename"), path)
                     and (job.get("width"), job.get("height")) == _SIZE)


def _started_transparent(p):
    settings = p.get("settings") or {}
    return _started(p, _TRANSPARENT_PATH) and _measured(
        "explicit custom preset launched as the transparent width-and-height job", settings,
        settings.get("aspect_ratio") == "custom" and settings.get("transparent") is True
        and (settings.get("width"), settings.get("height")) == _SIZE)


def _finished(p):
    job = p.get("job") or {}
    launched = _RECALL["render_job"]
    return _measured("finished local image job", job,
                     job.get("job_id") == launched["id"]
                     and job.get("file_path") == launched["path"]
                     and job.get("native_filename") == launched["path"]
                     and job.get("state") == "finished" and job.get("future_valid") is True
                     and job.get("complete") is True
                     and (job.get("width"), job.get("height")) == _SIZE
                     and _verified_image(launched["path"], job.get("file"), _SIZE))


def poll_render_job(rows, notes, job, max_polls=120, valued=None):
    """Poll one retained local job until its image is finished and verified."""
    call, story = facade("call"), facade("STORY")
    if not isinstance(job, dict) or not job.get("id") or not job.get("path"):
        rows.append(("render_get", "FAIL", "local render job ID or path was not retained"))
        return
    for attempt in range(max_polls):
        if attempt:
            time.sleep(1)
        is_error, payload = call("render_get", {"job_id": job["id"]})
        if is_error:
            rows.append(("render_get", "FAIL", str(payload)[:NOTE_MAX]))
            return
        if not isinstance(payload, dict):
            rows.append(("render_get", "FAIL", "render job payload was not an object"))
            return
        item = payload.get("job") or {}
        if item.get("job_id") != job["id"] or item.get("file_path") != job["path"]:
            rows.append(("render_get", "FAIL", "render job ID or output path changed"))
            return
        if item.get("state") == "finished":
            try:
                good = (item.get("future_valid") is True and item.get("complete") is True
                        and (item.get("width"), item.get("height")) == _SIZE
                        and _verified_image(job["path"], item.get("file"), _SIZE))
            except AssertionError as exc:
                rows.append(("render_get", "FAIL", str(exc)[:NOTE_MAX]))
                return
            rows.append(("render_get", "pass" if good else "FAIL", "finished image verified"))
            if good:
                notes["render_get"] = story.get("render_get", "")
                if valued is not None:
                    valued.add("render_get")
            return
        if item.get("state") not in ("queued", "processing") or item.get("future_valid") is not True:
            rows.append(("render_get", "FAIL", str(item)[:NOTE_MAX]))
            return
    rows.append(("render_get", "FAIL", f"local image unfinished after {max_polls} bounded polls"))


def _scene_initial(p):
    scene = p.get("scene") or {}
    return _measured("initial render scene", scene,
                     p.get("render_workspace_active") is False
                     and isinstance(scene.get("brightness_lux"), (int, float))
                     and type(scene.get("show_ground")) is bool
                     and scene.get("ground_reflect") is False)


def _scene_matches(scene, requested):
    """Check every requested scene field against an independent read."""
    return isinstance(scene, dict) and all(
        (isinstance(scene.get(key), (int, float))
         and not isinstance(scene[key], bool)
         and math.isclose(scene[key], value, rel_tol=1e-6, abs_tol=1e-4))
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else (scene.get(key) is value if type(value) is bool else scene.get(key) == value)
        for key, value in requested.items())


def _scene_args(ctx):
    before = _ctx_get(ctx, "render_scene_initial", "initial scene")
    brightness = 55 if abs(before["brightness_lux"] - 55) > 1e-4 else 35
    requested = {"background_rgb": [104, 137, 161], "brightness_lux": brightness,
                 "exposure_ev": 8, "camera_type": "perspective",
                 "show_ground": not before["show_ground"], "light_angle_deg": 25}
    _RECALL["render_scene_request"] = requested
    return {"action": "scene", "scene": requested}


def _scene_edited(p):
    after = p.get("after") or {}
    requested = _RECALL["render_scene_request"]
    return _measured("combined scene edit applied and read back", p,
                     p.get("failed") is None and p.get("mismatches") == {}
                     and p.get("applied") == list(requested)
                     and p.get("before") == _RECALL["render_scene_initial"]
                     and _scene_matches(after, requested))


def _scene_read(p):
    scene = p.get("scene")
    return _measured("independent scene read after edit", scene,
                     p.get("render_workspace_active") is False
                     and scene == _RECALL["render_scene_edited"])


def _scene_reset(p, edited_key="render_scene_edited"):
    before, after = p.get("before") or {}, p.get("after") or {}
    changed = {key for key in before if before.get(key) != after.get(key)}
    return _measured("reset_scene observed changed fields", sorted(changed),
                     p.get("native_return") is True and p.get("changed") is True
                     and bool(changed) and set(p.get("changed_fields") or {}) == changed
                     and before == _RECALL[edited_key])


def _reset_read(p, reset_key="render_scene_reset"):
    return _measured("independent scene read after reset", p.get("scene"),
                     p.get("scene") == _RECALL[reset_key])


def _coupled_edit(p, requested, prior_key):
    return _measured("coupled scene edit applied and read back", p,
                     p.get("failed") is None and p.get("mismatches") == {}
                     and p.get("applied") == list(requested)
                     and p.get("before") == _RECALL[prior_key]
                     and _scene_matches(p.get("after"), requested))


def _coupled_read(p, edited_key):
    return _measured("independent coupled scene read", p.get("scene"),
                     p.get("render_workspace_active") is False
                     and p.get("scene") == _RECALL[edited_key])


def _camera_restore_args(ctx):
    initial = _ctx_get(ctx, "render_scene_initial", "initial scene")
    return {"action": "scene", "scene": {"camera_type": initial["camera_type"]}}


def _camera_restored(p):
    initial = _RECALL["render_scene_initial"]["camera_type"]
    before = _RECALL["render_scene_before_camera_restore"]
    return _measured("original camera type restored before scratch closes", p,
                     p.get("before") == before and p.get("applied") == ["camera_type"]
                     and p.get("failed") is None and p.get("mismatches") == {}
                     and (p.get("after") or {}).get("camera_type") == initial)


def _new_document_camera(p):
    initial = _RECALL["render_scene_initial"]["camera_type"]
    opened = (p.get("scene") or {}).get("camera_type")
    return _measured("a new document opens with the camera type this act first read",
                     {"new_document": opened, "first_read": initial},
                     isinstance(initial, str) and opened == initial)


def _written_camera_reaches_new_document(p):
    written = _RECALL["render_focal_edited"]["camera_type"]
    initial = _RECALL["render_scene_initial"]["camera_type"]
    opened = (p.get("scene") or {}).get("camera_type")
    return _measured("a new document opens with the camera type just written",
                     {"new_document": opened, "written": written, "first_read": initial},
                     isinstance(written, str) and opened == written and written != initial)


def _environment_args(field, index):
    """Ask for one catalog environment by its name or its id."""
    def args(ctx):
        rows = [r for r in _ctx_get(ctx, "render_environments", "environment catalog")
                if r.get("name") and r.get("id")]
        value = rows[index % len(rows)][field]
        _RECALL["render_environment_" + field] = value
        return {"action": "scene", "scene": {"environment_" + field: value}}
    return args


def _environment_edited(p, field, prior_key):
    after = p.get("after") or {}
    return _measured("environment applied by " + field + " and read back", p,
                     p.get("failed") is None and p.get("mismatches") == {}
                     and p.get("applied") == ["environment_" + field]
                     and p.get("before") == _RECALL[prior_key]
                     and after.get("environment_" + field) == _RECALL["render_environment_" + field]
                     and after.get("background_type") == "environment")


def _initial_scene_args(ctx):
    """Put the background and ground flattening back to the first scene read."""
    initial = _ctx_get(ctx, "render_scene_initial", "initial scene")
    background = ({"background_rgb": initial["background_rgb"]}
                  if initial.get("background_type") == "solid_color"
                  else {"environment_id": initial["environment_id"]})
    requested = {**background, "flatten_ground": initial["flatten_ground"]}
    _RECALL["render_scene_restore_request"] = requested
    return {"action": "scene", "scene": requested}


def _initial_scene_restored(p):
    initial = _RECALL["render_scene_initial"]
    requested = _RECALL["render_scene_restore_request"]
    after = p.get("after") or {}
    return _measured("background and ground flattening restored", p,
                     p.get("failed") is None and p.get("mismatches") == {}
                     and p.get("applied") == list(requested)
                     and p.get("before") == _RECALL["render_environment_by_id"]
                     and _scene_matches(after, requested)
                     and after.get("background_type") == initial.get("background_type"))


def _ground_reads(scene, wanted):
    """Check a scene row holds the wanted ground offset and no negative zero."""
    return (_scene_matches(scene, {"ground_offset": wanted})
            and repr(scene["ground_offset"]) != "-0.0")


def _ground_set(p, wanted, prior_key):
    return _measured("ground offset set to the requested value", p,
                     p.get("failed") is None and p.get("mismatches") == {}
                     and p.get("applied") == ["ground_offset"] and "already_set" not in p
                     and p.get("before") == _RECALL[prior_key]
                     and _ground_reads(p.get("after"), wanted))


def _ground_held(p, wanted, prior_key):
    return _measured("ground offset already held: nothing assigned, nothing moved", p,
                     p.get("failed") is None and p.get("mismatches") == {}
                     and p.get("applied") == [] and p.get("already_set") == ["ground_offset"]
                     and p.get("before") == _RECALL[prior_key]
                     and p.get("after") == p.get("before")
                     and _ground_reads(p.get("after"), wanted))


def _ground_read(p, edited_key, wanted):
    return _measured("independent ground offset read", p.get("scene"),
                     _coupled_read(p, edited_key) and _ground_reads(p.get("scene"), wanted))


def _reset_discloses_retained_ground(p):
    before = p.get("before") or {}
    held = before.get("ground_offset")
    return _measured("native reset disclosed the retained ground offset", p,
                     p.get("native_return") is True and p.get("changed") is True
                     and bool(p.get("changed_fields"))
                     and before == _RECALL["render_ground_seven"]
                     and (p.get("unchanged_fields") or {}).get("ground_offset") == held
                     and (p.get("after") or {}).get("ground_offset") == held)


def _activated(p):
    return _measured("Render workspace active", p,
                     p.get("active_before") is False and p.get("active_after") is True
                     and p.get("native_return") is True)


def _canvas_started(p):
    settings = p.get("settings") or {}
    return _measured("locked advanced 60-percent canvas started", p,
                     p.get("mode") == "canvas" and p.get("started") is True
                     and p.get("job_id") is None and settings.get("advanced") is True
                     and settings.get("resolution_pct") == 60
                     and settings.get("lock_view") is True)


def _canvas_read(p):
    canvas = p.get("canvas") or {}
    return _measured("canvas read in Render workspace", canvas,
                     p.get("render_workspace_active") is True
                     and canvas.get("advanced") is True and canvas.get("lock_view") is True
                     and canvas.get("resolution_pct") == 60
                     and canvas.get("completed") is None
                     and type(canvas.get("elapsed_s")) is int
                     and type(canvas.get("iterations")) is int)


def _canvas_saved(p):
    return _measured("saved canvas PNG", p,
                     p.get("native_return") is True
                     and _same_path(p.get("file_path"), _CANVAS_PATH)
                     and _verified_png(_CANVAS_PATH, p.get("image")))


def _canvas_stopped(p):
    return _measured("canvas stopped and unlocked", p,
                     p.get("native_return") is True and p.get("lock_view_final") is False)


def _design_restored(p):
    return _measured("Design workspace restored", p,
                     p.get("render_workspace_active") is False)


def _job_record(p):
    """Retain the just-started local job for its boundary poll."""
    return {"id": p["job_id"], "path": p["file_path"]}


def _settings(p):
    settings = p.get("settings") or {}
    return _measured("render settings read", settings,
                     isinstance(settings.get("width"), int)
                     and isinstance(settings.get("height"), int))


def _environments(p):
    catalog = p.get("environments")
    return _measured("render environment catalog read", catalog,
                     isinstance(catalog, dict) and isinstance(catalog.get("environments"), list)
                     and isinstance(catalog.get("count"), int))


_RENDER_START = [
    ("render_create", {"mode": "local", "file_path": _PNG_PATH,
                       "width": _SIZE[0], "height": _SIZE[1], "quality": 25},
     _started, ("render_job", _recall("render_job", _job_record))),
]

_RENDER_JPEG = [
    ("render_create", {"mode": "local", "file_path": _JPEG_PATH,
                       "width": _SIZE[0], "height": _SIZE[1], "quality": 25},
     lambda p: _started(p, _JPEG_PATH), ("render_job", _recall("render_job", _job_record))),
]

_RENDER_TIFF = [
    ("render_create", {"mode": "local", "file_path": _TIFF_PATH,
                       "width": _SIZE[0], "height": _SIZE[1], "quality": 25},
     lambda p: _started(p, _TIFF_PATH), ("render_job", _recall("render_job", _job_record))),
]

_RENDER_NAMED = [
    ("view_set", {"action": "save_view", "view_name": "RenderSweepView"}, "ok", None),
    ("render_create", {"mode": "local", "file_path": _NAMED_PATH,
                       "width": _SIZE[0], "height": _SIZE[1], "quality": 25,
                       "view_name": "RenderSweepView", "transparent": True},
     lambda p: _started(p, _NAMED_PATH), ("render_job", _recall("render_job", _job_record))),
]

_RENDER_TRANSPARENT = [
    ("render_create", {"mode": "local", "file_path": _TRANSPARENT_PATH,
                       "width": _SIZE[0], "height": _SIZE[1], "quality": 25,
                       "resolution_preset": "custom", "transparent": True},
     _started_transparent, ("render_job", _recall("render_job", _job_record))),
]

_RENDER_READ = [
    ("render_get", lambda c: {"job_id": _ctx_get(c, "render_job", "local PNG job")["id"]},
     _finished, None),
    ("render_get", {"include": ["settings"]}, _settings,
     ("render_settings_before_refusal", _recall("render_settings_before_refusal",
                                               lambda p: p["settings"]))),
    ("render_get", {"include": ["environments"]}, _environments,
     ("render_environments", _recall("render_environments",
                                     lambda p: p["environments"]["environments"]))),
    ("render_create", {"mode": "local", "file_path": _NAMED_PATH,
                       "width": _SIZE[0], "height": _SIZE[1]},
     _refused("already exists", "choose a new path"), None),
    ("render_create", {"mode": "local", "file_path": _REFUSED_PATH,
                       "width": _SIZE[0], "height": _SIZE[1], "lock_view": False},
     _refused("lock_view=False", "mode='local'", "mode='canvas'"), None),
    ("render_create", {"mode": "local", "file_path": _REFUSED_PATH,
                       "width": _SIZE[0], "height": _SIZE[1], "aspect_ratio": "4:3"},
     _refused("aspect_ratio='4:3'", "aspect_ratio='custom'"), None),
    ("render_get", {"include": ["settings"]},
     lambda p: _measured("refused local renders altered no render setting and wrote no file",
                         p.get("settings"),
                         p.get("settings") == _RECALL["render_settings_before_refusal"]
                         and not os.path.exists(_REFUSED_PATH)), None),
    ("render_get", {"include": ["scene"]}, _scene_initial,
     ("render_scene_initial", _recall("render_scene_initial", lambda p: p["scene"]))),
    ("render_edit", {"action": "scene", "scene": {"dof_enabled": True}},
     _refused("dof_enabled", "blocking depth-of-field warning", "render_get"), None),
    ("render_get", {"include": ["scene"]},
     lambda p: _measured("refused depth-of-field edit changed nothing", p.get("scene"),
                         p.get("scene") == _RECALL["render_scene_initial"]), None),
    ("render_edit", {"action": "scene", "scene": {"aspect_ratio": "custom"}},
     _refused("aspect_ratio", "read-only", "render_get(include=['scene'])"), None),
    ("render_edit", {"action": "scene", "scene": {"background_type": "environment"}},
     _refused("background_type", "read-only", "background_rgb gives solid_color"), None),
    ("render_get", {"include": ["scene"]},
     lambda p: _measured("refused read-only edits changed nothing", p.get("scene"),
                         p.get("scene") == _RECALL["render_scene_initial"]), None),
    ("render_edit", {"action": "scene", "scene": {"ground_roughness": 0.35}},
     _refused("ground_roughness requires ground_reflect=true", "enable ground reflections"), None),
    ("render_get", {"include": ["scene"]},
     lambda p: _measured("refused roughness edit changed nothing", p.get("scene"),
                         p.get("scene") == _RECALL["render_scene_initial"]), None),
    ("render_edit", _scene_args, _scene_edited,
     ("render_scene_edited", _recall("render_scene_edited", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]}, _scene_read, None),
    ("render_edit", {"action": "reset_scene"}, _scene_reset,
     ("render_scene_reset", _recall("render_scene_reset", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]}, _reset_read, None),
    ("render_edit", {"action": "scene", "scene": {"camera_type": "perspective",
                                                 "focal_length_mm": 50}},
     lambda p: isinstance(p.get("after"), dict) and _coupled_edit(
         p, {"camera_type": "perspective", "focal_length_mm": 50},
         "render_scene_reset"),
     ("render_focal_edited", _recall("render_focal_edited", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _coupled_read(p, "render_focal_edited"), None),
    ("doc_get", {}, _home_document, ("render_witness_home", _home_address)),
    ("doc_new", lambda c: {"expect_document": _ctx_get(c, "render_witness_home", "render scratch")},
     _new_document, ("render_witness_document", lambda p: p["document_handle"])),
    ("render_get", {"include": ["scene"]}, _written_camera_reaches_new_document, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "render_witness_home", "render scratch"),
                                "expect_document": _ctx_get(c, "render_witness_document",
                                                            "witness document")},
     _document_activated(), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "render_witness_document", "witness document"),
                             "save_changes": False,
                             "expect_document": _ctx_get(c, "render_witness_home",
                                                         "render scratch")},
     _document_closed, None),
    ("render_edit", {"action": "scene", "scene": {"ground_reflect": True,
                                                 "ground_roughness": 0.35}},
     lambda p: isinstance(p.get("after"), dict) and _coupled_edit(
         p, {"ground_reflect": True, "ground_roughness": 0.35},
         "render_focal_edited"),
     ("render_roughness_edited", _recall("render_roughness_edited", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _coupled_read(p, "render_roughness_edited"), None),
    ("render_edit", {"action": "reset_scene"},
     lambda p: _scene_reset(p, "render_roughness_edited"),
     ("render_roughness_reset", _recall("render_roughness_reset", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _reset_read(p, "render_roughness_reset"), None),
    ("render_edit", {"action": "scene", "scene": {"flatten_ground": True, "ground_offset": 5}},
     lambda p: isinstance(p.get("after"), dict) and _coupled_edit(
         p, {"flatten_ground": True, "ground_offset": 5}, "render_roughness_reset"),
     ("render_ground_edited", _recall("render_ground_edited", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _coupled_read(p, "render_ground_edited"), None),
    ("render_edit", _environment_args("name", 0),
     lambda p: isinstance(p.get("after"), dict) and _environment_edited(
         p, "name", "render_ground_edited"),
     ("render_environment_named", _recall("render_environment_named", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _coupled_read(p, "render_environment_named"), None),
    ("render_edit", _environment_args("id", 1),
     lambda p: isinstance(p.get("after"), dict) and _environment_edited(
         p, "id", "render_environment_named"),
     ("render_environment_by_id", _recall("render_environment_by_id", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _coupled_read(p, "render_environment_by_id"), None),
    ("render_edit", _initial_scene_args,
     lambda p: isinstance(p.get("after"), dict) and _initial_scene_restored(p),
     ("render_scene_ground_restored", _recall("render_scene_ground_restored",
                                              lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _coupled_read(p, "render_scene_ground_restored"), None),
    ("render_edit", {"action": "scene", "scene": {"ground_offset": 7}},
     lambda p: isinstance(p.get("after"), dict) and _ground_set(
         p, 7, "render_scene_ground_restored"),
     ("render_ground_seven", _recall("render_ground_seven", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _ground_read(p, "render_ground_seven", 7), None),
    ("render_edit", {"action": "scene", "scene": {"ground_offset": 7}},
     lambda p: isinstance(p.get("after"), dict) and _ground_held(p, 7, "render_ground_seven"),
     None),
    ("render_get", {"include": ["scene"]},
     lambda p: _ground_read(p, "render_ground_seven", 7), None),
    ("render_edit", {"action": "reset_scene"}, _reset_discloses_retained_ground,
     ("render_scene_offset_reset", _recall("render_scene_offset_reset", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _coupled_read(p, "render_scene_offset_reset"), None),
    ("render_edit", {"action": "scene", "scene": {"ground_offset": 0}},
     lambda p: isinstance(p.get("after"), dict) and _ground_set(
         p, 0, "render_scene_offset_reset"),
     ("render_ground_zero", _recall("render_ground_zero", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _ground_read(p, "render_ground_zero", 0), None),
    ("render_edit", {"action": "reset_scene"},
     _refused("no scene field changed", "render_get"), None),
    ("render_get", {"include": ["scene"]},
     lambda p: _coupled_read(p, "render_ground_zero"), None),
    ("render_create", {"mode": "canvas"},
     _refused("Render workspace", "view_switch_workspace"), None),
    ("render_edit", {"action": "activate"}, _activated, None),
    ("render_get", {"include": ["canvas"]},
     lambda p: _measured("canvas available in Render workspace", p.get("canvas"),
                         p.get("render_workspace_active") is True
                         and isinstance(p.get("canvas"), dict)), None),
    ("render_create", {"mode": "canvas", "advanced": True,
                       "resolution_pct": 60, "lock_view": True},
     _canvas_started, None),
    ("render_get", {"include": ["canvas"]}, _canvas_read, None),
    ("render_edit", {"action": "canvas_stop"}, _canvas_stopped, None),
    ("render_get", {"include": ["canvas"]},
     lambda p: _measured("canvas independently reads unlocked", p.get("canvas"),
                         p.get("render_workspace_active") is True
                         and (p.get("canvas") or {}).get("lock_view") is False), None),
    ("render_create", {"mode": "canvas", "advanced": False, "lock_view": False},
     lambda p: _measured("unlocked fast canvas started", p,
                         p.get("started") is True and p.get("mode") == "canvas"
                         and (p.get("settings") or {}).get("lock_view") is False), None),
    ("render_edit", {"action": "canvas_save", "file_path": _CANVAS_PATH}, _canvas_saved, None),
    ("render_edit", {"action": "canvas_stop"}, _canvas_stopped, None),
    ("view_switch_workspace", {"workspace": "design"},
     lambda p: _measured("Design workspace switch", p,
                         p.get("switched") is True
                         and p.get("activation_verified") is True
                         and "Design" in (p.get("active_workspace") or "")), None),
    ("render_get", {"include": ["scene"]}, _design_restored, None),
    ("render_get", {"include": ["scene"]},
     lambda p: _measured("scene read before camera restoration", p.get("scene"),
                         isinstance(p.get("scene"), dict)
                         and isinstance((p.get("scene") or {}).get("camera_type"), str)),
     ("render_scene_before_camera_restore", _recall(
         "render_scene_before_camera_restore", lambda p: p["scene"]))),
    ("render_edit", _camera_restore_args, _camera_restored,
     ("render_camera_restored", _recall("render_camera_restored", lambda p: p["after"]))),
    ("render_get", {"include": ["scene"]},
     lambda p: _measured("camera restoration independently read", p.get("scene"),
                         p.get("scene") == _RECALL["render_camera_restored"]
                         and (p.get("scene") or {}).get("camera_type")
                         == _RECALL["render_scene_initial"]["camera_type"]), None),
    ("doc_get", {}, _home_document, ("render_home", _home_address)),
    ("doc_new", lambda c: {"expect_document": _ctx_get(c, "render_home", "render scratch")},
     _new_document, ("render_new_document", lambda p: p["document_handle"])),
    ("render_get", {"include": ["scene"]}, _new_document_camera, None),
    ("doc_activate", lambda c: {"name": _ctx_get(c, "render_home", "render scratch"),
                                "expect_document": _ctx_get(c, "render_new_document",
                                                            "new document")},
     _document_activated(), None),
    ("doc_close", lambda c: {"name": _ctx_get(c, "render_new_document", "new document"),
                             "save_changes": False,
                             "expect_document": _ctx_get(c, "render_home", "render scratch")},
     _document_closed, None),
]
