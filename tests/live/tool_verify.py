# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Run owned Fusion families and maintain source-bound portable receipts.

Full runs bootstrap; --families refreshes whole families, while --acts writes evidence only.
--check validates current family closures on one Fusion build without requiring Fusion.
Usage and coverage accounting are documented in tests/README.md.
"""

import argparse
import os
import sys
import time   # noqa: F401 - surface: a consumer stubs tool_verify.time.sleep

# This module is spec-loaded BY PATH (the completeness lint) as
# often as it is imported by name, and a spec load leaves its directory off sys.path - so
# the modules below would not import. Every consumer reaches them through this one.
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import machine_config  # noqa: E402

if __name__ == "__main__":
    machine_config.configure_cli(sys.argv[1:])
    if not ({"--check", "--help", "-h"} & set(sys.argv[1:])):
        machine_config.require()

import cloud_config  # noqa: E402

if __name__ == "__main__":
    cloud_config.bootstrap(sys.argv[1:])

import verify_core  # noqa: E402

from verify_core import (  # noqa: F401
    BASE, MCP, SERVER_NAME, DOC_PREFIX, MACHINE_NAME, TEMPLATE_NAME, NOTE_MAX, REFUSAL_NOTE_MAX,
    STEP_SLEEP_S, _SHELL_TIMEOUT_S, _DWELL, _HERE, REPO_ROOT, SRC_ROOT,
    VERIFIED, _post, call, health_gate, registered_tools, _ctx_get, _Refusal, _refused, Parked,
    Needs, _needs, Unless, _unless, gate_allows, gate_skip_reason, step_runs_unentitled,
    step_capability, parked_reason, CAPABILITY_PROBES, probe_capabilities,
    capability_met, capability_skip_reason, _machining_extension_probe,
    CLOUD_TIER, CLOUD_LINK_CRASH_REVIEW, OPT_IN_TIERS, CAPABILITY_DETAIL,
    _cloud_tier_probe, _cloud_link_crash_review_probe,
    _unparked, _PUSH_OPS, _INSPECT_OPS, _is_inspect, _ARG_LOAD_OPS, _arg_load_sites,
    _TRUTHY_ONLY_CALLS, _callee_name, _inspects_argument, _inspects_payload, predicate_kind,
    EXPORT_DIR, SVG_PATH, SVG96_PATH, write_png, MARKER_PNG, _fg, _fgn, _prof, _matched, _face_up_at,
    _PATH_LABEL, _path_count, _measured, _bound_on_harness,
    _RECALL, _recall, _SVG96_MM, _SVG96_TOL, _svg96_extent, _repair_no_op, _made_component,
    _made_component_inactive, _PLANE_NORMAL_AXIS, _datum_plane, _dim_measures, _datum,
    _result_bodies, _extruded, _revolved, _swept, _lofted, _material_assigned, _gap_measured,
    _relation_measured, _rebuilt, _relation_read, _relation_passes, _extent_measured, _drafted,
    _drilled, _mirrored, _patterned, _joined, _edge_feature, _filleted, _chamfered, _shelled,
    _offset_faces, _moved, _split_bodies, _unstitched, _stitched, _base_feature_open,
    _base_feature_closed, _arranged, _holder_computed, _piped, _num, _near, _mod360, _jointed,
    _mesh_round_trip, _joint_origin_landed, _joint_origin_at, _joint_origin_computed,
    _joint_limits, _motion_linked, _driven_angle, _driven_slide, _as_built, _jointed_at_geometry,
    _grounded, _moved_occurrence, _rigid_grouped, _constrained, _captured, _joint_is,
    _joints_listed, _joint_origins_listed, _interference_measured, _PARAM_TOL, _param_added,
    _param_set_to, _param_deleted, _params_listed, _param_read, _param_favorited, _new_document,
    _document_read, _document_closed, _imported, _imported_sketches, _imported_curves,
    _exported_bytes, _box, _JOINT_STATIONS, _STN_X0, _STN_PITCH, _STN_Y, _STN_Z, _JOINT_BEAT,
    _pose_took, _joint_bench, _group_of, _watch, _dwell, _leaves_no_row, _watch_all,
    _SKETCH_PLANE, _PLANE_VIEW)

from verify_layout import (  # noqa: F401
    _SKETCH_MAKERS, _BODY_MAKERS, _FRAME_MARGIN, _FRAME_CONTEXT, _FRAME_MIN_SPAN, _FRAME_STRETCH,
    _FRAME_FALLBACK_NEIGHBOURS, _FRAME_MAX_SUBJECTS, _FRAME_SKETCH_GROUP, _FRAME_SKETCH_SPAN,
    _FRAME_RELATION_WIDEN, _ORIGIN_PLANES, _SKETCH_ORDER_BOUND, _sketches_first,
    _sketch_reading_order, _RELATION_TOOLS, _PLACED_BOX, _MEASURED_BOX, _CHUNK_OF, _COMPONENTS,
    _PATTERNED, measured_boxes, _chunk_box, _union,
    _DRIFT_CHUNKS, _DRIFT_TOL_MM, layout_drift_mm, layout_placed_as_measured, drift_row,
    _FRAME_PATTERN_WIDEN, _framed, _frame_box, _frame_cluster, _expand, _inside,
    _frame_neighbourhood, _PLACE_PAIRS, _PLACE_DELTA_TOOLS, _PLACE_XYZ, _PLACE_POINTS,
    _PLACE_NAMES, _PLACE_FRAMES, _JOINT_GROUPS, _JOINT_FAMILY,
    _place_owner, _place_num, _place_points, _place_walk, _place_shift, _placed,
    _px, _py, _SLOTS)

from verify_acts_doc import (  # noqa: F401
    _OVERTURE, _SHOWCASE, _FINALE, _RELOAD_PROBE_GAP_S, _RELOAD_PROBE_TIMEOUT_S,
    _RELOAD_DOWN_POLLS, _RELOAD_UP_POLLS, _RELOAD_SMOKE_QUERY, _server_answers, _poll_health,
    _health_bound, reload_smoke)

from verify_acts_sketch import _SKELETON, _SKETCHWORK  # noqa: F401

from verify_acts_model import (  # noqa: F401
    _SOLIDS, _DETAILS, _RESIZE, _SOLIDS_FB, _DETAILS_FB, _RESIZE_FB)

from verify_acts_motion import (  # noqa: F401
    _MOTION, _plate, _fixture_rest_clean, _VISE)

from verify_acts_mesh import _MACHINING, _NESTING, _MESH  # noqa: F401

from verify_acts_cam import (  # noqa: F401
    PART_COMP, PART_DRIVER, STOCK_COMP, VISE_BASE, JAW_FIXED, JAW_MOVING, CAM_SETUP,
    _op_created, _toolpath_shown, _CAM_STORY, _tmpl_names, _CAM_DELIVER,
    poll_generation, _CAM, _CAM_FB_DELIVER)

from verify_acts_cloud import (  # noqa: F401
    RUN_FOLDER, MOVED_FOLDER, SOURCE_DOC, COPY_DOC, HOST_DOC, RUN_PATH, MOVED_PATH,
    RESTORE_VERSION, _CLOUD_DATA, _CLOUD_DOC, _CLOUD_LINK, _CLOUD_DRAWING,
    _CLOUD_COMPONENT_COPY,
    _lit, _xrefs)

from verify_acts_hub import (  # noqa: F401
    HUB_COMP, HUB_MILL_SETUP, HUB_TURN_SETUP, _HUB, _HUB_JOB, _fully_constrained, _hub_box,
    _hub_setups, _hub_tools_landed, _rim_edge, _threaded, _tilt_frame, _tilt_v)
from verify_acts_render import _RENDER_READ, _RENDER_START, poll_render_job  # noqa: F401
from verify_family_switch import family_switch_smoke  # noqa: F401

from verify_program import (  # noqa: F401
    _ACT_PROGRAM, _SKETCH_PHASE, _placed_boxes, ACTS, FAMILY_PROGRAM,
    ACT_DEPENDENCIES, ACT_NEEDS, POLL_AFTER, STEPS, STORY,
    EXCLUDED, PENDING)
from verify_families import (  # noqa: F401
    ACT_PRODUCER_OVERRIDES, FAMILY_DEPENDENCIES, PRODUCER_ROWS, PRODUCER_SLOTS)

from verify_runner import (  # noqa: F401
    source_hash, _STAMP_RE, write_verified, check, _shoot, run_steps, judged_steps,
    _precondition_holds, _one_act, select_acts, run, RESULTS_DIR, run_state_path,
    save_run_state, load_run_state, resume_refusal, develop_refusal, _document_now)
from verify_core import attestation_identity, Independent, independent_targets  # noqa: F401

FAMILY_RECEIPTS = True

# The patchable surface is patched ON THIS MODULE (a consumer stubs tool_verify.call,
# tool_verify.ACTS, tool_verify.source_hash), so the runner and the post-act hook read
# those names off this namespace when a run starts instead of binding their own copies.
verify_core.bind_facade(globals())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", metavar="PATH",
                    help="required machine configuration; overrides FUSION_ESSENTIALS_SWEEP_CONFIG")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--full-scope", action="store_true",
                    help="with --check: require full admitted recorded scope; quarantine stays excluded")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--accept-open-work", action="store_true",
                    help="explicitly accept already-modified open documents; owned resume handles alone are exempt")
    ap.add_argument("--keep-open", action="store_true",
                    help="leave only the last requested family's scratch document open for inspection")
    ap.add_argument("--shots", metavar="DIR", default=None,
                    help="write a PNG of the framed view after every framing row, so the framing "
                         "can be judged by looking instead of by trusting its ratio")
    ap.add_argument("--trace", action="store_true",
                    help="print each step (flushed) before it runs, so a Fusion crash names its killer")
    ap.add_argument("--acts", metavar="SPEC", default=None,
                    help="run the complete owned families containing these named acts, each in "
                         "fresh scratch documents with local inputs; comma lists and A..B ranges "
                         "are accepted. Writes dated evidence, never a receipt")
    ap.add_argument("--run", metavar="ID", default=None, dest="run_id",
                    help="run the full family chain under this ID, saving act progress and exact "
                         "document ownership to tests/live/results/run-<ID>.json after every act; "
                         "incomplete chunks write no receipt")
    ap.add_argument("--families", metavar="NAMES", default=None,
                    help="refresh whole comma-separated family receipts after a new full bootstrap; "
                         "all aggregate closures must match and share one Fusion build")
    ap.add_argument("--resume", action="store_true",
                    help="continue an unselected full --run ID from its owned-family checkpoint; "
                         "old single-document checkpoints and --resume --acts are refused")
    ap.add_argument("--continue-families", action="store_true",
                    help="continue independent families after a logical failure and certified cleanup; "
                         "fresh run only; any failure forbids receipts")
    args = ap.parse_args()
    shots = args.shots
    if shots:
        os.makedirs(shots, exist_ok=True)
    if args.resume and not args.run_id:
        sys.exit("--resume needs the run it continues: --run <id> --resume")
    if args.full_scope and not args.check:
        sys.exit("--full-scope needs --check")
    sys.exit(check(full_scope=args.full_scope) if args.check else run(args.json, keep_open=args.keep_open, trace=args.trace,
                                            shots_dir=shots, acts_spec=args.acts,
                                            run_id=args.run_id, resume=args.resume,
                                            families_spec=args.families,
                                            continue_families=args.continue_families, accept_open_work=args.accept_open_work))
