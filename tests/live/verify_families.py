# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Owned sweep families and the local inputs each builds before its judged acts."""

from verify_acts_cam import _CAM_EXTENSION, _CAM_SCOPE, _SWARF_FRUSTUM
from verify_acts_model import _DETAILS, _SOLIDS
from verify_acts_model_solids import (
    DATUM_BENCH_DETAILS, DATUM_BENCH_RESIZE, FINISHED_BRACKET,
    _component_block as _solids_component_block)
from verify_acts_motion import _MOTION, _STOCK_VISE, _VISE_SHOWCASE_POSE
from verify_acts_sketch import BRACKET_PARAMETERS_PROFILES
from verify_core import _DWELL
from verify_core import _box
from verify_layout import _placed


FAMILY_GROUPS = (
    ("sketch", ("ACT 0", "ACT 1 -", "ACT 1b")),
    ("solids", ("ACT 2 -",)),
    ("surfaces", ("ACT 3 -",)),
    ("mesh", ("ACT 4 -",)),
    ("details", ("ACT 5 -",)),
    ("resize", ("ACT 6 -",)),
    ("nesting", ("ACT 6b",)),
    ("vise", ("ACT 7 -",)),
    ("motion", ("ACT 7b",)),
    ("showcase", ("ACT 9 -",)),
    ("swarf_cam", ("ACT 8 -", "ACT 10b2", "ACT 10c -", "ACT 10c6b")),
    ("hub_cam", ("ACT 8b", "ACT 10c4", "ACT 10c5", "ACT 10c6 -",
                 "ACT 10c7", "ACT 10c8", "ACT 10c9", "ACT 10c10", "ACT 10c11",
                 "ACT 10c12", "ACT 10c13", "ACT 10c14", "ACT 10c15")),
    ("fff_export", ("ACT 10c16",)),
    ("part_cam", ("ACT 10a", "ACT 10b -", "ACT 10b1", "ACT 10d", "ACT 10e", "ACT 10f")),
    ("cloud", ("ACT 11",)),
    ("sheet_coupon", ("ACT 12 -", "ACT 12b", "ACT 12c", "ACT 12d")),
    ("sheet_selected", ("ACT 12e",)),
    ("sheet_positions", ("ACT 12f",)),
    ("sheet_flange", ("ACT 12g",)),
    ("small_edits", ("ACT 13 -",)),
    ("lookup", ("ACT 14 -",)),
    ("render", ("ACT 15 -",)),
    ("finale", ("FINALE",)),
)
FAMILY_SLOTS = {}


def family_names(acts):
    """Return act-to-family ownership, refusing missing or multiply owned acts."""
    result = {}
    for name, _pre, _narrative, _fallback in acts:
        hits = [family for family, prefixes in FAMILY_GROUPS
                if any(name.startswith(prefix) for prefix in prefixes)]
        if len(hits) != 1:
            raise ValueError("act has {0} families: {1}".format(len(hits), name))
        result[name] = hits[0]
    return result


def ordered_acts(acts):
    """Place each family's dependency chain in one contiguous document."""
    owners = family_names(acts)
    return [act for family, _prefixes in FAMILY_GROUPS for act in acts
            if owners[act[0]] == family]


STOCK_VISE = list(_STOCK_VISE)
RECOGNITION = [step for step in _DETAILS
               if step[0] in ("cam_find_holes", "cam_find_pockets")]
SHOWCASE_POSE = [row for row in _VISE_SHOWCASE_POSE
                 if row[0] not in (_DWELL, "view_set", "view_screenshot")]
ROOT_DESIGN_CONTEXT = [("design_activate_component", {"occurrence": "root"}, "ok", None)]
FINALE_STATE = [
    ("view_switch_workspace", {"workspace": "manufacture"}, "ok", None),
    ("view_set", {"action": "display", "categories": ["sketches"],
                   "visible": False}, "ok", None)]
_MANUFACTURE = ("view_switch_workspace", {"workspace": "manufacture"}, "ok", None)
_DESIGN = ("view_switch_workspace", {"workspace": "design"}, "ok", None)
_CAM_TOOL_LIBRARY = [
    _MANUFACTURE,
    ("cam_edit_tools", {"action": "add", "scope": "document",
     "add_tools": [{"from_type": "flat end mill", "diameter": "10 mm"}]},
     lambda p: p.get("added") == 1 and p.get("tool_count", 0) >= 1, None),
    _DESIGN]

PRODUCER_ROWS = {
    "bracket-parameters-profiles": BRACKET_PARAMETERS_PROFILES,
    "finished-bracket": FINISHED_BRACKET,
    "datum-details": DATUM_BENCH_DETAILS,
    "datum-resize": DATUM_BENCH_RESIZE,
    "root-design-context": ROOT_DESIGN_CONTEXT,
    "stock-vise": STOCK_VISE,
    "showcase-pose": SHOWCASE_POSE,
    "swarf-frustum": _SWARF_FRUSTUM,
    "cam-scope": _CAM_SCOPE,
    "cam-extension": _CAM_EXTENSION,
    "cam-tool-library": _CAM_TOOL_LIBRARY,
    "recognition": RECOGNITION,
    "small-edits-box": _box("EditTarget"),
    "lookup-box": _box("LookupGuard"),
    "render-box": _box("RenderCoupon"),
    "finale-state": FINALE_STATE,
}

PRODUCER_SLOTS = {
    "bracket-parameters-profiles": (),
    "finished-bracket": ("pk_c1", "pk_c2", "pk_c3", "pk_c4", "low_top", "step_top",
                          "step_lead", "step_out", "boss_top", "edge_break"),
    "datum-details": ("db_top", "db_top2", "db_bore"),
    "datum-resize": (),
    "root-design-context": (),
    "stock-vise": (),
    "showcase-pose": (),
    "swarf-frustum": (),
    "cam-scope": ("scope_mill", "scope_top_face", "setup2_op"),
    "cam-extension": ("corner_op", "deburr_dependency_baseline", "deburr_op", "flow_op",
                       "geodesic_op", "mafin_op", "marough_op", "sw_faces", "sw_lower",
                       "sw_mill", "sw_top_edge", "sw_top_face", "sw_upper", "sw_wall",
                       "swarf_op"),
    "cam-tool-library": (),
    "recognition": ("pocket_floor", "recognized_cbore_walls"),
    "small-edits-box": (),
    "lookup-box": (),
    "render-box": (),
    "finale-state": (),
}

FAMILY_DEPENDENCIES = {
    "sketch": {"producers": [], "requires": ("owned design document",),
               "provides": ("parametric bracket sketches",), "workspace": "Design",
               "camera": "Skeleton and BracketBody"},
    "solids": {"producers": ("bracket-parameters-profiles",),
               "requires": ("PartLen", "PartWid", "PartHt"),
               "provides": ("Bracket:1 solid", "StockCenter"), "workspace": "Design",
               "camera": "Bracket:1"},
    "details": {"producers": ("bracket-parameters-profiles", "finished-bracket",
                               "datum-details"),
                "requires": ("Bracket:1",),
                "provides": ("DatumBench", "db_bore"), "workspace": "Design",
                "camera": "Bracket:1 and DatumBench"},
    "resize": {"producers": ("bracket-parameters-profiles", "finished-bracket",
                              "datum-resize", "root-design-context"),
               "requires": ("Bracket:1", "StockCenter"),
               "provides": ("Bracket:1", "DatumBench"), "workspace": "Design",
               "camera": "Bracket:1 and DatumBench"},
    "vise": {"producers": ("bracket-parameters-profiles", "finished-bracket"),
             "requires": ("Bracket:1",), "provides": ("clamped stock and vise"),
             "workspace": "Design", "camera": "ViseBase:1 and STOCK:1"},
    "showcase": {"producers": ("bracket-parameters-profiles", "finished-bracket", "stock-vise",
                                 "showcase-pose", "showcase-shapes"),
                 "requires": ("Bracket:1", "captured vise pose"),
                 "provides": ("showcase fixtures and cameos"), "workspace": "Design",
                 "camera": "ViseBase:1 and STOCK:1"},
    "part_cam": {"producers": ("bracket-parameters-profiles", "finished-bracket", "stock-vise",
                                "recognition"),
                 "requires": ("Bracket:1", "STOCK:1", "StockCenter"),
                 "provides": ("part CAM models and recognition inputs"),
                 "workspace": "varies by act", "camera": "Bracket:1 and CAM setup"},
    "swarf_cam": {"producers": ("cam-tool-library",), "requires": ("owned family document",),
                  "provides": ("SwarfFrustum:1", "SwarfSetup"), "workspace": "varies by act",
                  "camera": "SwarfFrustum:1 and setup"},
    "hub_cam": {"producers": ("cam-tool-library",), "requires": ("owned family document",),
                "provides": ("hub CAM setup state",), "workspace": "varies by act",
                "camera": "hub and CAM setup"},
    "small_edits": {"producers": ("small-edits-box",), "requires": ("owned family document",),
                    "provides": ("EditTarget",), "workspace": "Design",
                    "camera": "EditTarget"},
    "render": {"producers": ("render-box",), "requires": ("owned family document",),
               "provides": ("RenderCoupon",), "workspace": "Design",
               "camera": "RenderCoupon"},
    "lookup": {"producers": ("lookup-box",), "requires": ("owned family document",),
               "provides": ("LookupGuard",), "workspace": "Design",
               "camera": "LookupGuard"},
    "finale": {"producers": ("finale-state",), "requires": ("owned family document",),
               "provides": ("manufacture workspace with sketches hidden",),
               "workspace": "Manufacture", "camera": "authored final scene"},
}

for _family, _prefixes in FAMILY_GROUPS:
    FAMILY_DEPENDENCIES.setdefault(_family, {
        "producers": (), "requires": ("owned family document",),
        "provides": ("family-local act state",), "workspace": "act-specific",
        "camera": "authored act frames"})

ACT_PRODUCER_OVERRIDES = {
    "ACT 10e - CAM: MULTI-SETUP POST": ("swarf-frustum", "cam-scope"),
}

ACT_PRODUCER_CONDITIONAL_OVERRIDES = {
    "ACT 10e - CAM: MULTI-SETUP POST": {
        "machining_extension": ("cam-extension",)},
    "ACT 10c15 - CAM: THE ADDITIVE BUILD": {
        "machining_extension": ("swarf-frustum", "cam-extension")},
}


def fixture_steps(family, before_act=None, entitled=True, raw=False, slots=None):
    """Return scoped executable producers while retaining authored raw closure inputs."""
    from verify_core import tiered
    rows = _fixture_steps(family, before_act, entitled, raw, slots)
    return rows if raw else tiered(rows)


def _fixture_steps(family, before_act=None, entitled=True, raw=False, slots=None):
    """Return local producer rows for one family boundary."""
    selected = None if raw else (FAMILY_SLOTS[family] if slots is None else slots)
    place = (lambda rows: list(rows)) if raw else (lambda rows: _placed(rows, selected))
    if before_act is not None:
        if before_act.startswith("ACT 10e") and family == "part_cam":
            rows = [_DESIGN] + place(_SWARF_FRUSTUM) + [
                _MANUFACTURE] + place(_CAM_SCOPE)
            return rows + (place(_CAM_EXTENSION) if entitled else [])
        if before_act.startswith("ACT 10c15") and family == "hub_cam" and entitled:
            return [_DESIGN] + place(_SWARF_FRUSTUM) + [
                _MANUFACTURE] + place(_CAM_EXTENSION)
        if family == "swarf_cam" and before_act.startswith("ACT 10b2"):
            return [_MANUFACTURE]
        if family == "hub_cam" and before_act.startswith("ACT 10c4"):
            return [_MANUFACTURE]
        return []
    if family in ("solids", "details", "resize", "vise", "part_cam", "showcase"):
        rows = list(BRACKET_PARAMETERS_PROFILES)
        if family != "solids":
            rows += FINISHED_BRACKET
        if family == "details":
            rows += place(DATUM_BENCH_DETAILS)
        if family == "resize":
            rows += place(DATUM_BENCH_RESIZE)
            rows += PRODUCER_ROWS["root-design-context"]
        if family in ("part_cam", "showcase"):
            rows += STOCK_VISE
        if family == "part_cam":
            rows += RECOGNITION
        if family == "showcase":
            rows += [row for row in _VISE_SHOWCASE_POSE
                     if row[0] not in (_DWELL, "view_set", "view_screenshot")]
            rows += showcase_shapes(raw=raw, slots=selected)
        return rows
    if family in ("swarf_cam", "hub_cam"):
        return list(_CAM_TOOL_LIBRARY)
    if family == "finale":
        return list(PRODUCER_ROWS["finale-state"])
    if family == "small_edits":
        return list(PRODUCER_ROWS["small-edits-box"])
    if family == "lookup":
        return list(PRODUCER_ROWS["lookup-box"])
    if family == "render":
        return list(PRODUCER_ROWS["render-box"])
    return []


def showcase_shapes(raw=False, slots=None):
    """Build the four measured cameos without replaying the modelling benches."""
    ball = next(i for i, row in enumerate(_MOTION)
                if row[0] == "model_create_component" and row[1].get("name") == "BallSphere")
    torus = next(i for i, row in enumerate(_MOTION)
                 if row[0] == "model_create_component" and row[1].get("name") == "TorusRing")
    face = next(i for i, row in enumerate(_SOLIDS)
                if row[0] == "find_geometry" and row[3] and row[3][0] == "fc_body")
    orbit = next(i for i in range(face + 1, len(_SOLIDS))
                 if _SOLIDS[i][0] == "model_pattern_circular")
    rows = (list(_MOTION[ball:torus])
            + _solids_component_block(_MOTION, "TorusRing", "joint_at_geometry")
            + _solids_component_block(_MOTION, "MateSeat", "design_recompute")
            + _solids_component_block(_SOLIDS, "FeatureCameo", "model_draft")
            + list(_SOLIDS[face:orbit + 1]))
    return list(rows) if raw else _placed(rows, FAMILY_SLOTS["showcase"] if slots is None else slots)


PRODUCER_ROWS["showcase-shapes"] = showcase_shapes(raw=True)
PRODUCER_SLOTS["showcase-shapes"] = ()
