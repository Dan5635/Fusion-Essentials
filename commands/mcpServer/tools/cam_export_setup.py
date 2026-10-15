# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Write an additive setup's parts, as placed, to a 3MF file, judged by the file on disk."""

import adsk.cam
import adsk.core

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from . import _export
from . import _outputs
from ._cam_common import find_setup, get_cam, is_additive_setup
from ._common import error, ok, safe

app = adsk.core.Application.get()

RETURNS = [
    _outputs.ReturnsValue("file_path", "the 3MF file written to disk"),
]

# What this export leaves out, as (reply word, option property, the value that leaves it out).
_LEFT_OUT = (("supports", "supportInclusion", "NotIncluded"), ("slices", "isSliceDataIncluded", False))


def handler(setup: str = "", file_path: str = "") -> dict:
    """See TOOL_DESCRIPTION."""
    if not (setup or "").strip():
        return error("Provide 'setup' - an additive setup name (see cam_get).")
    cam, cam_error = get_cam()
    if cam_error:
        return error(cam_error)
    found, _names, setup_error = find_setup(cam, setup)
    if not found:
        return error(setup_error)
    name = safe(lambda: found.name) or setup
    if not is_additive_setup(found):
        return error(f"Setup '{name}' is not additive; cam_export_setup writes an additive setup's "
                     "parts. cam_post writes machining code.")
    path, path_error = _export.prepare_out_path(file_path, ".3mf")
    if path_error:
        return error(path_error)
    if not path:
        return error("Provide 'file_path' - where the .3mf file is written.")
    before = _export.snapshot(path)

    try:
        options = cam.exportManager.create3MFOptions()
    except Exception as e:
        return error(f"The 3MF export of setup '{name}' could not be prepared: {e}. Nothing was written.")
    # The option values refuse to read until the setup is bound, so it is bound first.
    for prop, value in (("exportObject", found), ("fullFilename", path)):
        landed, _changed = _export.applied_pair(options, prop, value, prop)
        if landed is None:
            return error(f"The 3MF export options did not keep '{prop}' for setup '{name}'; nothing "
                         "was written.")
    expected = []
    for word, prop, value in _LEFT_OUT:
        if isinstance(value, str):
            value = getattr(adsk.cam.CAM3MFSupportInclusionType, value, None)
        landed, _changed = _export.applied_pair(options, prop, value, word)
        if value is None or landed is None:
            return error(f"The 3MF option that leaves {word} out did not read back, so nothing was "
                         "written.")
        expected.append((word, prop, value))
    for word, prop, value in expected:
        if safe(lambda prop=prop: getattr(options, prop)) != value:
            return error(f"The 3MF option that leaves {word} out changed after the other options "
                         "were set, so nothing was written.")
    if safe(lambda: options.exportObject) != found:
        return error(f"The 3MF export target changed after the options were set for '{name}'; "
                     "nothing was written.")
    if safe(lambda: options.fullFilename) != path:
        return error(f"The 3MF output path changed after the options were set for '{name}'; "
                     "nothing was written.")
    try:
        answered = cam.exportManager.execute(options)
    except Exception as e:
        return error(f"The 3MF export of setup '{name}' raised: {e}.")
    size, missing = _export.verify_written(path, before)
    if answered is not True or missing:
        said = (safe(lambda: options.error) or "").strip()
        return error(f"The 3MF export of setup '{name}' did not write a usable file: "
                     f"{missing or 'the export answered false'}." + (f" Fusion says: {said}" if said else ""))
    return ok({"exported": True, "setup": name, "file_path": path, "size_bytes": size,
               "left_out": [word for word, _prop, _value in _LEFT_OUT],
               "note": "The file holds the setup's parts as placed on the Manufacture side. It is not "
                       "printer-ready code; cam_get(include=['placement'], setup=...) reads the same "
                       "poses."})


TOOL_DESCRIPTION = (
    "Write an additive setup's parts, as placed, to a 3MF file; supports and slices are left out. "
    "Place parts first (cam_edit_operation, cam_generate).\n" + _outputs.produces_block(RETURNS))

tool = (
    Tool.create_simple(name="cam_export_setup", description=TOOL_DESCRIPTION)
    .add_input_property("setup", {"type": "string", "description": "Additive setup name (from cam_get)."})
    .add_input_property("file_path", {"type": "string", "description": "Local .3mf path."})
    .add_required_input("setup")
    .add_required_input("file_path")
    .strict_schema()
)
item = Item.create_tool_item(
    tool=tool, write="write", handler=handler, run_on_main_thread=True,
    verification=Verification(
        kind="inline", rung="value",
        evidence_test="tests/unit/test_cam_export_setup.py"
                      "::test_an_export_that_answers_true_and_writes_nothing_is_an_error"))


def register_tool():
    register(item)
