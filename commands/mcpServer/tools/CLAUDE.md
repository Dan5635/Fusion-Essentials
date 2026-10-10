# Adding or editing a tool here

How to add or change a tool in `commands/mcpServer/tools/`. Read the root
[CLAUDE.md](../../../CLAUDE.md) first for the project rules.
[CONTRIBUTING.md](../../../CONTRIBUTING.md) explains the ideas behind them, and
[tests/CLAUDE.md](../../../tests/CLAUDE.md) covers testing what you add here.

## Adding a tool

- One tool per file: `tools/<tool_name>.py` holds `handler(...)`, `TOOL_DESCRIPTION`, `tool` (a
  `Tool`), `item` (an `Item`) and `register_tool()`, and registers nothing else. Registration is
  auto-discovered by a pkgutil sweep, so **just drop the file in**; do not edit `tools/__init__.py`
  or `entry.py`. `_`-prefixed modules are shared helpers, never tools.
- A Read with many slices (`design_get`) is still one tool: its slices are `_slice_*` helpers in the
  same file. Code two tools share lives once, in the family's underscore helper (`_cam_common`,
  `_doc_common`, ...), never copied into a second tool file. `test_tool_naming.py` enforces this.
- **Reuse before you write.** Check the catalog below before adding a resolver, and run
  `sys_find_tool <kw>` before adding a tool or an input. Extend what exists instead of duplicating it.
- Set `write=` on the `Item` honestly: `"read"`, `"write"` or `"destructive"`. It is linted.
- Run on the main thread (the default); touching `adsk.*` off the main thread can crash Fusion. Don't
  block it: no bare `sleep`, no open-ended polling, no synchronous network call in a handler. The one
  allowed wait is a time-limited `adsk.doEvents` pump for an asynchronous Fusion write that only
  advances while the main thread runs. Use `_export.pump_until` for it (it takes your own probe and
  its own timeout), never a hand-rolled loop.
- Check every signature and property with `sys_get_api_doc`, which reads the installed build,
  **before** writing it; never guess that a property exists. A non-obvious API fact lives where the
  code depends on it: a typed kind or guard when it constrains an input, the tool description when
  the calling agent needs it, or a short comment at the point of use.

## The catalog: reuse before you write

Check two tables before hand-rolling logic: the input kinds (reference geometry or structure through
one of these, never a raw `name`/`index`) and the shared helpers (import the symbol from its home
module; a copy goes stale the next time the home module is fixed). `py -3 tests/gen_manifest.py`
generates both from `_inputs.py` and each helper's `MAP_BLURB`; don't edit between the markers.

<!-- BEGIN GENERATED CATALOG (py -3 tests/gen_manifest.py) -->
| Kind | References (use this — don't hand-roll a name/index) |
|---|---|
| `AxisRef` | a direction: world x/y/z, a construction axis (name or handle), a straight-edge/sketch-line handle, OR a face normal/axis |
| `BodyRef` | a body by handle (precise), body name, or single-body component name; kind=solid/surface/mesh |
| `BodyRefList` | several bodies (handles or names) |
| `Choice` | one of a fixed set -> JSON enum |
| `CurvePointRef` | a drawing view-curve point as '<curve_index>:<start\|end\|mid\|center>' from drawing_get(include=['curves']) |
| `Distance` | a length in display units (pair with one UnitField) |
| `EdgeLoopRef` | a closed/open edge-loop boundary from edge handles |
| `FeatureEditOperands` | typed references for one closed feature edit action |
| `FeatureRef` | a timeline feature by name, '<component>/<name>', or timeline index (refuses an ambiguous bare name) |
| `FeatureRefList` | several timeline features by name |
| `FormCageHandleList` | cage vertices/edges/faces of one Form by find_geometry handle; spent by any cage change |
| `GeometryHandle` | one face/edge/vertex by find_geometry handle (require=face/edge/...), not a coordinate |
| `GeometryHandleList` | several faces/edges by handles (fillet/drill THESE) |
| `JointOriginRef` | a Joint Origin by assembly_get handle OR name (bare if unique, else '<occ>:<JO name>'); refuses ambiguity |
| `LoftEndCondition` | a loft end's condition, refused where the section at that end cannot take it |
| `LoftSectionList` | an ORDERED list of loft sections: profile, one edge, an end sketch point, an open sketch curve |
| `OccurrenceRef` | an assembly occurrence by entityToken handle (exact) or fullPathName/name (refuses ambiguity) |
| `OccurrenceRefList` | several occurrences (entityToken handles or fullPathNames/names) |
| `PlaneRef` | a plane: xy/xz/yz alias, construction-plane name/handle, or planar-face handle |
| `PlasticRuleRef` | a scoped plastic rule name or current {scope,index,name} ref |
| `PointRef` | a point: vertex/sketch-point/construction-point handle, '<sketch>/point:<i>' or '<sketch>/circle\|arc:<i>:center', or a construction point name |
| `PointRefList` | several points (handles, sketch index refs or construction point names), in order |
| `ProfileRef` | a sketch profile by stable handle, not sketch_name+profile_index |
| `ProfileRefList` | an ORDERED list of profiles (loft - order is load-bearing) |
| `SectionRef` | a Section Analysis by generated name (exact case-insensitive match; refuses ambiguity) |
| `SheetMetalRuleRef` | a scoped sheet-metal rule name or current {scope,index,name} ref; refuses ambiguous names |
| `SketchDimensionRef` | an existing sketch dimension by its parameter name from sketch_get, within one sketch |
| `SketchLineRef` | a sketch line as '<sketch>/line:<index>' from sketch_get, scoped by component |
| `SketchRefList` | several sketches by name (refuses a name several sketches share) |
| `SurfaceRef` | the *_to_surface operand: plane alias / construction plane / planar face, plus the curved faces the operations named in curved_ops accept |
| `TargetRef` | a thing to measure/colour: handle (body/face/mesh; edge+construction when allowed) OR occurrence/component/body name; ''=whole design |
| `TargetRefList` | several body-or-occurrence targets: bodies (handles/names) and/or component occurrences (names) |
| `UnitField` | the 'units' selector (mm/cm/in enum, mm default) for a Distance; every geometry-reporting read takes one and scales its output via CM_TO_UNIT |

| Helper | Provides (import from here - never re-implement) |
|---|---|
| `_assembly_common` | the occurrence WORLD-POSE sampler an assembly write is judged by: _constraint_positions - every target's translation and basis BEFORE the mutation, one that will not read ABSENT rather than zeroed; _constraint_moves - which moved across it (translation plus _axes_rotation_deg, the flip a translation-only row hides), and whether ANY target was sampled on both sides |
| `_assembly_detail` | the row SERIALIZERS behind assembly_get, one per array in its payload - reach for one only from there. _occ_record/_all_occurrence_rows - occurrence identity, placement behind with_pose; _health_fields - the compute-state verdict; _joint_frame/_limit_facts/_value_now/_motion_axes - a joint's world frame, limits, value and heading; _joint_origin_rows/_relation_rows/_contact_rows - the rest |
| `_assert` | POSTCONDITION kinds (VersionAdvanced/ReferencesFresh/FileLanded/...) - declare an Edit tool's verify-the-effect once; wired via Item.create_tool_item(postconditions=[...]) |
| `_cam_additive` | setting_fits/assign_parts/target_parts (print setting vs machine, an operation's parts), orientation_rows/choose_orientation, placement_rows, print_setting_row/printer_row, additive_results - additive setup reads and verified writes. |
| `_cam_common` | the CAM substrate every CAM tool starts from: get_cam (the document's CAM product); the ONE tree walk and its EXACT by-name resolvers (walk_cam_tree, resolve_cam_node, find_setup, find_operation - a duplicate name is refused); the parameter helpers; the per-op state classifiers and readiness verdicts (op_state_facts, ready_verdict, live_readiness); the machine catalog; the bounded library walk |
| `_cam_presets` | ToolPreset validation and writing: _preset_spec_error, _apply_preset_values, _persist_preset_change. Reading: _preset_names, _presets_named, _preset_expressions. resolve_operation_preset matches an operation's tool. |
| `_cam_read` | the per-slice READ cores behind cam_get(include=[...]) - get_cam_setups_handler, get_cam_operations_handler, get_setup_references_handler, get_tool_list_handler, get_machining_time_handler, get_nc_programs_handler, get_inspection_results_handler, get_machine_limits_handler; reach for one only from that router, every other CAM tool shares _cam_common |
| `_cam_templates` | the CAM TEMPLATE library substrate: _template_library - the handle off the CAMManager singleton, not the CAM product; list_cam_templates_handler - the bounded folder tree cam_get(include=['templates']) returns, each row carrying the ASSET url cam_apply_template takes; _find_template_by_name - the by-name search REFUSING a name several templates answer to; _LOCATION - the location selector |
| `_common` | response+resolve: ok/error/safe (per-FIELD, never a MUTATION), read_optional/measured/read_flag/counted/finite_number, design/target_component, find_sketch/resolve_sketch (ambiguity), timeline_health/timeline_message/set_verified/rolled_to (effect; roll-restore), same_component/native_identity/occurrence_walk/broken_reference (TRI-STATE), scale/iter_collection/named_with_remainder/told_apart |
| `_contacts` | the substrate assembly_get's contacts slice and assembly_edit_contacts share. contact_sets/all_contact_sets/contact_set_names - the DESIGN-scoped contactSets walk; find_contact_set - the EXACT resolve-one, refusing a duplicate; membership/member_label - the occurencesAndBodies read-back |
| `_continuity` | the ONE seam read: edge_angles/body_seams - the largest normal angle along a two-faced edge (None when a sample will not read), for one edge or every one of a body; seam - the gap, normal angle and cross-seam curvature jump between two faces at samples along an edge; partner_face - the face of the one edge of another body lying along an edge |
| `_data_common` | cloud data-model substrate: resolve_file_reference / _file_in_folder_by_name - the URN-or-name-in-a-project and one-folder resolvers, a shared name REFUSED; navigate_folder_path - the folder-PATH walk from a project root, creating nothing; active_project - the active document's OWN DataProject; name_extension - the NAME holds the true extension; absence_after_delete - the re-resolve after deleteMe |
| `_data_read` | cloud READ cores for data_get: list_projects_handler (hub projects), list_project_files_handler (scoped project files), folder_summary_handler (folder identity + immediate counts), list_folders_handler (bounded folder tree), file_facts_handler (one file's metadata + links); the capped walks record unread folders |
| `_design_common` | MODE: get_mode_handler/health_handler - mode and health; run_in_base_feature/base_feature_run_wrapper - a mutation in an always-finished base-feature scope; timeline_census/timeline_item_key/census_caveat - an edit census; collapsed_group_hint(_for)/hidden_twin_hint - a grouped member's miss (by name or entity) or hidden twin; unfold_group_members - the group-state census; no_timeline_reason |
| `_doc_common` | _resolve_open_document - exact open-document resolve by handle/index/URN/name, refusing ambiguity; VERSION_LAG_WINDOW_S - measured cloud-tip lag window; fresh_version_read/wait_for_version_advance - fresh cloud identity reads around a save; publication_read - the bounded DataFile.isComplete settle read every save publishes |
| `_drawing_common` | active_drawing(_document); SHEET_SIZE_MAP/DIMENSION_STRATEGIES/ORIENTATION_MEMBERS/NO_PORTRAIT; sheet_units/SHEET_EXTENT_UNIT/DOCUMENT_UNIT/coordinate_unit/extent_in_coordinates/coordinates_to_extent; enum_value/*_label; resolve_sheet/sheet_listing/sheet_facts/view_at; view_curve/typed_curve/curve_point/curve_row; listed/as_index/sheet_xy; palette_parts/palette_list; revision_rows - its row census |
| `_edge_common` | EDGES/FACES/BODY/_EDGE_FILTER_DESC/_TANGENT_CHAIN_DESC - targeting; _edges_of_faces - face edges; _distinct_placed_edges - edge handles per placement; _edge_convexity/_collect_edges - dihedral filters; _tangent_chain_read - applied chain; _cut_edges - resolved count via rolled_to; _apply - build and verify volume/area |
| `_edit_feature_common` | FEATURE_EDIT_SUPPORT/feature_edit_rows - closed offer; read_extrude_definition/read_sweep_definition/feature_definition - read; write_datum; all_shapes/health/same_feature; feature_geometry_snapshot - body shapes and occurrence frames; sketch_address/at_address/address_text; restore_definition/restore_gaps/matched/shape_match - rollback; rolled_back_text/failed/identical_geometry_reply - outcomes |
| `_export` | export-to-disk substrate: sanitize/prepare_out_path (safe filename, extension and directory prep), find_component/instance_paths (by-name resolve, shared name refused), top_level_occurrences/split_by_occurrence/failure_detail (one file per root occurrence), snapshot/verify_written (prove THIS call wrote), applied_pair (set an option, read it back), stl_unit_enum, pump_until (bounded doEvents wait) |
| `_form_common` | the T-spline Form substrate: all_forms/form_label/resolve_form - a Form's '<component>/<name>' address; health_label; body_box_cm; create_form/finish_edit/retire - the always-finished edit and its rollback; read_record/store_record - the creation record; one_cage_body/cage_walk/cage_revision/cage_handle/resolve_cage - the control cage by native index, refused once the cage has changed |
| `_geom` | math: unit_vector/unit_vector_between/evaluator_normal_at/dot/cross/coaxial (vectors); body_aabb/occ_world_frame/axis_vec (AABB, placement); volumes/volume_delta/signed_volume/body_shape/face_counts/face_count_delta/areas/area_delta/face_frames/faces_moved/lump_count/aabb_gap/parallel_plane_facts (what a write is judged by; area/frames move where a pivot leaves the volume); address/subtree_facts |
| `_holder` | holder geometry: get_axis, get_tool_profile, build_holder_data, get_tooling_libraries |
| `_image_common` | the reference-image substrate: image_rows/slice_reference_images - the root component's canvases and decals as rows; resolve_image - a row's ref back to its entity, refused when stale; canvas_frame/canvas_cells/decal_frame/decal_cells - a placement as centre, size, rotation and mirroring, and back to matrix cells; original_size - the size Fusion gives the image file unscaled |
| `_inputs` | typed kinds; resolve_inputs/apply_to_tool; length_value_input/expression_report; FeatureEditOperands (feature refs); world_construction_axis/axis_line_of (axis entity; world line), single_placement/entity_component/operand_in (assembly-context lift), operand_meta/placed_point_cm/placed_datum_frame/placed_handle (world frame, handle), resolve_surface/surface_ref_label (*_to_surface operand) |
| `_joint_inputs` | the joint WRITE substrate above _joints: _resolve_input - the ONE joint-input resolve (a handle, a '<occurrence>:<snap>', then a Joint Origin name), with _parse_snap/_pick_face behind it; _JOINT_TYPES/_MOTIONS - the wire motion vocabulary; _apply_limits - limits read BACK off the joint; input_occurrence/pose_before/pose_moved - the jointed parts' world-pose change |
| `_joints` | build_joint_geometry/apply_motion - keypoint factory + motion dispatch; all_joints/find_joint - walks joints+asBuiltJoints, REFUSING a shared name; DRIVES_ANY - drivable gate; motion_link_record/link_ratio_values - link record + ratio codec; all_joint_origins/jo_assembly_proxy - JointOrigin walk + proxy; component_world_matrix - world matrix ladder; pair_used_clause/PAIR_USED - used-pair refusal |
| `_materials` | browse - the ONE material/appearance catalog read: a library census plus the document-local set when no library is named, one library's filtered and capped entries when it is; catalog_census/find_library/entries are its leaf ops |
| `_mesh_common` | the MeshBody read substrate: _tri_count/_node_count - the displayMesh counts every mesh payload reports; _area_volume + _mesh_moved - the second, independent signal a flat triangle count is judged beside; _mesh_summary - the one per-mesh record; _result_mesh_of - the mesh a mesh feature produced; mesh_measure_of_body - the mesh analogue of a BRep measure |
| `_outputs` | RETURNS kinds (ReturnsHandle/Urn/Name/Value/Verdict) - declare a tool's stable outputs once |
| `_param_common` | the design-PARAMETER substrate: _param_summary - the ONE parameter row every param_* tool publishes, converting Parameter.value out of DATABASE units (cm/radians) into the parameter's own and naming the frame it could not convert into; _owner_facts - a MODEL parameter's maker, each key absent when it did not read; _find_parameter - the exact by-name lookup, user parameters first |
| `_pattern_common` | the pattern substrate: _resolve_input_entities - the ObjectCollection a pattern seeds from, bodies taking precedence over occurrences; _owning_component - the component the feature must be built in (the axis and the feature must share one or Fusion raises getObjectPath); _direction_entity - a world-axis key as that component's own origin axis, anything else lifted into its assembly context |
| `_plastic_common` | plastic_rules/plastic_rule_row - complete scoped rule lookup and unit-aware records. |
| `_pmi` | the PMI substrate. walk_annotations/find_annotation - the design-wide walk and the resolve-one REFUSING a shared name; build_segments/segments_markup/annotation_record - the {symbol} markup codec and light record; readable_warning - errorOrWarningMessage as one bounded line; build_tolerance/build_display - the tolerance/display codecs; apply_*/normalize_extension/set_* - the writers, each re-read |
| `_relations` | the substrate assembly_get's relations slice and assembly_edit_relations share. all_relations - the ONE walk over a design's rigid groups / motion links / assembly constraints; relation_names/find_relation - the names for an error message and the EXACT resolve-one that REFUSES a duplicate; rigid_group_members - member paths |
| `_rib_common` | body_census/rib_definition - owner-local shape witnesses and passive Rib/Web definitions. |
| `_sheet_common` | rule_row/scoped_rules/matching_rules/component_row/sheet_edge_faces/bend_face_count/bend_wall_groups/flat_pattern_row/pending_unfolds - scoped rules, pending unfold preflight, component state, a rim edge's faces, cylinder-face count, bend walls paired per axis, flat health and optional geometry |
| `_sheet_edit` | hem_read/prepare_hem/write_hem - supported Hem definition reads, validation and rebuild. |
| `_sketch_batch` | the sketch batch substrate: entries_or_error - the list-shape guard; run_batch - one sketch's entries in order, stopping at the first failure or raise, with the shared landed/failed/not_attempted payload; refuse - an entry refused before any write; entry_counts - the four counts a failed entry is judged by; retired_clause - delete an entry's minted midpoint anchors, judged by those counts |
| `_sketch_detail` | sketch_get's X-ray; sketch_world_frame/frame_space_note - frame; curve_id/entity_id/dimension_entities - ids; point_census/moved_points/point_ends - what a solve moved; scope_component(s)/COMPONENT_SCOPE/component_scope/scoped_sketch/scoped_or_recent_sketch/scope_remedy - the scope; _sketch_summary - a sketch row; _prepare/_transform - move/copy; unquote_text/font_read_back - SketchText. |
| `_surface_common` | the surface-body substrate: _solid_verdict - the ONE any-True/False-if-any-False/else-None collapse over isSolid flags; _result_body_report/_body_names_and_solid - a feature's result bodies as names plus flags, or plus that verdict; _created_bodies - the bodies owning the faces a feature CREATED, never feature.bodies; _landed_length - a length read off the feature's own parameter |
| `_sweep_common` | resolve_profile: closed or open sweep section on its owning component |
| `_sys_common` | the Fusion SELECTION substrate: _selection_record - the ONE per-entity record sys_request_selection and sys_get_selection both publish (a _classify() dispatch by runtime type, the click point, and a find_geometry-style 'handle' for a face/edge/vertex); RETURNS - the handle output both declare; _ui - the userInterface read, None when there is none |
| `_threads` | resolve_thread_info - the ONE thread-table walk turning a bare designation ('M5x0.8', '1/4-20 UNC') into a ThreadInfo, shared by model_hole's tap and model_thread; also returns every thread type carrying that designation |
| `_tsm` | the T-spline cage codec, pure Python: primitive/box/cylinder - the cage builders; validate - the measured-rule refusal naming a face, edge or vertex; emit - a cage as TSM text; parse - a read-back as (cage or None, census, reasons); compare - a read-back against what was emitted; canonical_hash - a cage's record identity |
| `_view_common` | view_direction/look_direction/up_vector/is_ortho_face/apply_camera/apply_named_view/restore_camera/camera_restored/capture_png_b64 - camera math + capture; standoff_distance/STANDOFF_FALLBACK_CM - standoff; activate_workspace - activate, read back; DISPLAY_FOLDERS/all_display_components - clutter; keep_visible/all_bodies/same_body/isolate_for_fit/restore_message/focus_box - one-subject frame |
| `_write_guard` | _active_identity + one_open_document - document identity reads; document_key - store key; document_handle + resolve_document_handle - exact session addresses until close/reload; prune_closed_documents + on_key_evicted/on_key_renamed - store lifecycle hooks |
<!-- END GENERATED CATALOG -->

## Postconditions: an Edit tool declares how its effect is verified

`_inputs` types what a tool is given, `_outputs` what it returns, and `_assert` what it did. A write
tool passes `postconditions=[...]` to `Item.create_tool_item`. That wrapper runs capture -> handler
-> verify and turns a success whose declared effect did not take into an error. Rules:

- Reuse a kind from `_assert` (`VersionAdvanced`, `ReferencesFresh`, `FileLanded`, ...) before writing
  one; a new kind must capture and verify through `safe()` reads and never mutate.
- Evidence a postcondition reads (size_bytes, stale counts) is folded into the payload via
  setdefault. Declare such keys in RETURNS and let the wrapper supply them instead of computing them
  twice.
- A write tool with no postconditions declares its verification instead: a closed `verification=`
  declaration on `Item.create_tool_item` (inline / effect / deferred / external / dynamic / gap).
  Each one carries a reference that `test_postconditions_declared.py` resolves: an evidence-test node
  id, a poller tool, a live-receipt row that records a real observation, or an open ledger defect id.
  `dynamic` alone carries none, because the caller writes its effect.
- Verify-the-effect logic that is mixed into payload assembly, per-file loops, or
  compensation/rollback stays in the handler. That is what `inline` and `effect` classify, and the
  evidence test each one names is where the reasoning lives.

## What a good tool does

1. **Reads its effect back: a swallowed no-op is an error, never a false `ok`.** The API can return
   success while changing nothing. This was observed live for saves and versioning
   (`Document.save()` versioning nothing), reference refreshes (`updateAllReferences()` leaving a
   stale reference) and machine assignment. Re-read the changed state and fail the call if the change
   did not take. How much to re-read depends on the change:
   - rung 1: report a count. A wrong result with the right count passes, so this is not enough for a
     mutation whose region or geometry could be wrong, such as a fillet;
   - rung 2: report that the effect exists (a body or feature was made, though maybe the wrong one);
   - rung 3: read the right count or value back off the feature and error on a mismatch
     (`model_pattern_rectangular` reads `patternElements.count`; `cam_edit_setup` re-reads every
     assignment);
   - rung 4: verify the right geometry changed: volume, faces, or the file on disk (`model_shell`
     volume diff, `cam_post` folder snapshot diff). A material-removal feature needs rung 4; a
     reflection or a deterministic-placement sketch is complete at rung 2.
   Hard cases and their exemplars: an async effect that lags the call -> report the *verified* state
   plus a `pending`, never the intent (`doc_activate`); a setter the platform lies about -> assign,
   re-read `activeHub`, and return an honest error if it did not change (`data_switch_hub`); a create
   -> re-list and error if the new thing did not appear (`data_create_project`); a refresh -> re-check
   `isOutOfDate` afterwards (`doc_update_xref`).
2. **Refuses ambiguity: it returns the candidates and never grabs the first.** A name that matches
   several things is a hard error listing what is available (`cam_delete`, `OccurrenceRef`,
   `find_setup`), not a silent wrong pick.
3. **Documents its non-obvious API trap at the point of use, marked live-verified.** For example:
   "the Future must stay referenced or Fusion abandons the generation"; "`allOperations` omits
   folders, verified live"; "`postProcess()` true is not proof a file was written". A destructive or
   crash-prone path gets a declare-intent guard (`doc_open`).
   Some resources opened across calls cannot be seen while open: while a base-feature edit scope is
   open, `count==0`, `itemByName==None`, and `timeline` raises. Capture the handle `add()` returned,
   because it can never be found again. Do not gate the close on a state the open scope itself changes:
   `model_base_feature` does not mode-gate `finish`, or it would leak the scope it opened.
4. **Teaches at the failure moment, in one shared home, not in every description.** Failure-time
   teaching goes in the error, once, in the shared resolver (`_cam_common.get_cam`'s Manufacture-gate
   error). Purpose and next step go in a lean description; input legality goes in a typed kind. Root
   CLAUDE.md, "Tool descriptions", sets the same rule for everything on the wire.
5. **Reuses one resolver, one parser, one health signal; never re-rolls it.** Shared logic lives
   once, in its owner module (`find_setup`, `live_readiness`, `_data_common._resolve_data_file` for
   the URN/URL format, `resolve_sketch` for the design-wide sketch walk). Code that only looks alike
   is not shared logic; leave it.

## Named exemplars: copy the nearest one before inventing a new shape

- **Rich read** (one `<domain>_get` per domain, light default + `include=`): `design_get`, `data_get`,
  `model_inspect`.
- **Honesty** (a mutation verified or left to raise, never swallowed): `model_create_component`
  (rename read-back), `cam_delete` (`deleteMe()==False` reported, not swallowed), `mesh_export`
  (file-exists gate after `execute()`), `surface_trim` (commit or cancel a `createInput` transaction;
  never leave it open), `joint_motion_link` (rolls the created link back with `deleteMe()` if the
  ratio can't be applied, rather than leaving a silent default 1:1 link). `data_switch_hub` is the
  setter example under "Reads its effect back" above.
- **Guards**: `doc_open` (a required declare-intent flag refuses the API path for a document class
  known to crash Fusion), `data_delete_folder` (requires `confirm_name` to match exactly and, before
  deleting a non-empty folder, previews everything it would remove, recursively).
- **Acquire**: `find_geometry`. **Orient**: `workspace_orient`.
- **Resolver adoption**: `design_delete_occurrence` (resolves its target through
  `_inputs._resolve_occurrence`, which refuses an ambiguous name instead of guessing).

## Module docstrings: short and factual, or none

A tool module may carry a docstring of a few lines (`test_prose_budget.py` caps a module docstring
at six): what the tool or tools do, plus at most one API gotcha the code depends on. Function
docstrings and `#` comments follow root CLAUDE.md, "Prose in code": a function's docstring is one
line. No design history, migration or review narrative anywhere; `test_evergreen_no_baggage.py`
enforces this. API facts beyond that one gotcha live in the code that uses them (a guard, a typed
kind, a point-of-use comment). A handler docstring that only restates the wire `description` should
be one line or omitted. A process lesson (how a bug was found, what a review taught) belongs in your
own memory, not the repo.

## `write=` policy for a read-style verb whose actions still change state

A poller that only advances an async operation that was already authorized (`cam_get_status`) stays
`write="read"`: the write guard on the call that started it already covers what it advances. A tool
with a read-style verb whose own actions change or delete persistent state must be `write="write"`,
through an explicit exemption in `test_tool_naming.py`'s `_WRITE_VERB_EXEMPT`. The exemptions are
`view_section` (`clear` deletes user-created section analyses) and `sys_request_selection` (clears the
user's current Fusion selection). A new one needs an entry there with a one-line reason naming the
observed mutation; flipping `write=` locally is not enough.

## What crosses the wire (what an agent reads every turn)

| Surface | Source | Build rule |
|---|---|---|
| `name` | `create_simple(name=)` | structural - unique, verb-shaped |
| `annotations` | `write="read"/"write"/"destructive"` | structural - set it honestly (linted) |
| `inputSchema` `type`/`enum` | a `Choice`/kind, or a typed property | structural - prefer a kind so values are machine-checked |
| **`description`** | `TOOL_DESCRIPTION` | **prose** - purpose and a pointer to the next step, nothing else |
| **per-input `description`** | `add_input_property(name, {..."description"})` | **prose** - a long one means a missing kind; type the input |
| **`note` / `error`** in the result | `ok({"note":...})` / `error(...)` | **prose** - state the observed fact, never a guessed cause |
| per-input `default` | the handler's signature default (a bool, a non-zero number, a non-empty string), or a kind's `default=` | structural - stamped at registration; never restated in prose (see below) |

`Item.create_tool_item` stamps a per-input `default` at registration. A default is honest only when
sending the value does exactly what omitting it does. An input that means "leave unchanged" or
"decided by another input" when omitted (a guard that reads the raw value, an edit that must not
re-type) carries no default. `test_wire_shape.TestSchemaDefaults` keeps the schema and the signature
in agreement both ways.

Don't restate the schema (the agent sees the JSON), and never write a tutorial-style comment block
into a description. For ASCII and the wire budget, see root CLAUDE.md.

## Reads are RICH: one `<domain>_get` per domain, not a tool per slice

A Fusion document has many levels of nested detail (workspace -> component -> sketch -> profiles ->
constraints -> entities -> points; plus parameters, timeline, browser, CAM). A read that flattens a
whole level dumps detail the agent didn't ask for. So the read layer is one rich read per domain
(`design_get`, `cam_get`, `doc_get`, `data_get`, `model_inspect`): it returns the lightest layer that
is actionable plus a pointer to the next level, and `include=` or a filter fetches more. Build new
reads this way; don't add another narrow `_get_x` tool. Exemplars to copy: `workspace_orient` (counts
+ health + `pointers` to the narrow tool per area), `find_geometry` (light match records + handle,
narrowed by `kind`/`radius`/`nearest_to`, capped by `max_results`), `design_get` / `cam_get` (a light
default; `include=[...]` and a scope filter pull one deeper level at a time).

A rich read has three knobs:
- **default projection**: the orientation slice, with cheap, essential, often short-lived facts
  ("where am I / what changed"). It is always bounded and safe to call at any time.
- **`include=[...]`**: widen to a deeper slice the default omits. Flags only add cost the agent opted
  into.
- **`filter`/`scope`**: narrow (`setup=`, `project=`, `near=[x,y]`, `max_depth=`, a `target` handle).

Build rules for a read:
- **Bound it.** A list that can grow with the model takes a cap (`max_results`/`max_depth`) and reports
  `truncated`. Never emit an unbounded array.
- **Filter before dumping.** Offer the narrowing the agent would want (`near=[x,y]`, `kind=`, a name
  scope) so it pulls the few it needs, not all.
- **Point, don't inline.** When a deeper level exists, return a count and a pointer to the tool that
  drills into it; don't fold that depth into this payload. One zoom level per call, never the deepest
  level unprompted.
- **Handles are light; records are heavy.** A 200-char handle the agent will *use* is fine; twenty
  full entity records it must skim to find one profile are the waste.
- The default's `note`/`pointers` must name its own `include=` slices, or point at the `include` enum
  when naming them all would push the note past its budget (cam_get's fifteen). A flag nobody
  advertises is invisible.
- The handler is a thin router over small `_slice_xxx(...)` helpers, one per slice, so the file stays
  readable whole and each slice can be tested on its own.
- Fold in only passive structure reads. Async pollers (`cam_get_status`), Edits and Acquire tools
  (`find_geometry`, `sys_get_selection`) stay separate: an Acquire's output feeds an Edit, so it is
  never a slice of a Disclose read.

## What the lints catch (run `py -3 tests/check_all.py` before you call it done)

- `test_tool_naming.py` - the naming schema: verb vocabulary and verb-kind/`write=` agreement.
- `test_write_status_annotations.py` - every registered tool declares a write-status annotation.
- `test_wire_ascii.py` - every description/note and every module-level string constant in `tools/` is pure ASCII.
- `test_generated_docs_current.py` - runs `gen_all.py --check` (`gen_manifest.py`/`gen_wiring.py`/`gen_posture.py`)
  and fails with the regen command when a doc has gone stale.
- `test_helper_duplication.py` - a denylist: a known shared symbol (`get_cam`, `sanitize`,
  `target_sketch`, ...) may only be defined in its home helper module; re-implementing it locally fails.
- `test_no_first_match_resolvers.py` - bans the substring/`.lower() in name.lower()` first-match smell
  across every tool module (an allowlist entry needs a plain-English reason).
- `test_evergreen_no_baggage.py` - bans history/plan-narrative language in comments, docstrings, and
  strings under `commands/mcpServer/` and `tests/` (this file included).

## Verify on a real document before calling it done

After tests pass: `sys_reload_addin` (it auto-discovers new modules), wait for
`127.0.0.1:37182/health`, then run the handler on a live document. The server handler is live at
once, but the client may keep a stale schema until it reconnects; see CONTRIBUTING.md.

## Destructive / outward actions

Deleting or overwriting is hard to reverse. Guard it, and when testing live against a model you didn't
create, prefer a throwaway you made (a scratch component/sketch) over the user's real geometry — or
ask first.
