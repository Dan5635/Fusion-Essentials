---
name: insert-into-template
description: >-
  Use when the user asks to insert/place/drop/load a design or part into a template (or
  "windowframe template", "CAM template", "machining template"), to set up a CAM job for a
  part, or to "insert this into the template". A repeatable, team-owned procedure of
  fusion-essentials tool calls that sets up a CAM job for a new part: it saves the CAD, gives
  the part a "Center of Model" origin along the machining axis, copies the shop's CAM template
  beside it as <model>_CAM, swaps the part into the template's model component (the slot the
  real part goes in), sizes the stock from the measured part and regenerates the toolpaths for
  the new part. It runs without asking the operator for approval; the only human step is the
  machining face, which the skill proposes from measured geometry for a yes/no and otherwise
  has the operator click in Fusion. Requires the fusion-essentials MCP server.
allowed-tools: >-
  fusion-essentials:workspace_orient
  fusion-essentials:doc_get
  fusion-essentials:data_get
  fusion-essentials:design_get
  fusion-essentials:cam_get
  fusion-essentials:param_get
  fusion-essentials:param_set
  fusion-essentials:sys_get_selection
  fusion-essentials:sys_request_selection
  fusion-essentials:find_geometry
  fusion-essentials:joint_create_origin
  fusion-essentials:model_inspect
  fusion-essentials:doc_save
  fusion-essentials:doc_save_as
  fusion-essentials:doc_open
  fusion-essentials:doc_insert_occurrence
  fusion-essentials:doc_update_xref
  fusion-essentials:assembly_ground
  fusion-essentials:assembly_get
  fusion-essentials:joint_create
  fusion-essentials:sketch_set_text
  fusion-essentials:cam_set_nc_comment
  fusion-essentials:cam_generate
  fusion-essentials:cam_get_status
  fusion-essentials:view_switch_workspace
  fusion-essentials:view_screenshot
  fusion-essentials:view_screenshot_multi
---

# Insert a new part into a CAM template

Run the phases in order. Each numbered step is a tool call whose output feeds a later step: record
the named values and pass them on verbatim. If a step's stated expectation does not hold, STOP and
report the failing value. Do not work around it, and do not drop to sys_execute_script (report a
missing capability instead). Template methodology background is in [reference.md](reference.md).

## CONFIGURATION (edit these for your shop)

```
# Destination when the CAD is NOT already saved (a saved part's own folder wins otherwise).
DEFAULT_PROJECT      = "CAM"
DEFAULT_FOLDER       = "{model}"      # "{model}" expands to the CAD's name

# The team's template library: one folder holding the published templates. The skill uses only
# documents from this folder. DEFAULT_TEMPLATE is used when the operator does not name one.
TEMPLATE_LIBRARY_PROJECT = "CAM"
TEMPLATE_LIBRARY_FOLDER  = "Workflow Templates"
DEFAULT_TEMPLATE         = "4th Axis Windowframe Template"

# Naming.
TEMPLATE_NAME_SUFFIX = "_CAM"         # the copy is named "<model>_CAM"
NAMEPLATE_SKETCH     = "File_Name"    # sketch whose text gets the model name (missing = skipped)

# Template wiring - the shop's naming convention inside its templates. "" = infer from the
# document; Phase 6 verifies every entry.
SETUP                = ""                            # "" = only unambiguous milling setup; else ask
PLACEHOLDER          = "Placeholder model"           # the slot occurrence the part replaces
ATTACH_JO            = "Attach Center of Workpiece"  # root JO the part joins to

# Optional stock parameters. If the template defines these user parameters the measured part
# size is written to them; if absent, stock sizing is skipped and the part still inserts.
PART_PARAMS          = ["PartX", "PartY", "PartZ"]

# How the machining face is chosen (Phase 1).
#   "propose" - the skill ranks the faces itself and asks the operator to confirm one proposal
#   "auto"    - the same rank, and it proceeds without asking when the rank is unambiguous by
#               AUTO_MARGIN below; the proposal is still reported
#   "manual"  - Phase 1 is skipped entirely; the operator clicks the face in Fusion (Phase 2)
AUTO_PICK            = "propose"
AUTO_MIN_AREA_FRAC   = 0.25   # a candidate face's area, as a fraction of the largest bbox face
AUTO_MARGIN          = 2.0    # "auto" needs the top axis to score >= this many x the runner-up
EVIDENCE_DIR         = ""     # "" = inline images only; a directory also writes one PNG per view
```

## Phase 0 - Hub gate (READ, before anything is saved)

Projects and lineage URNs are hub-scoped: the template library resolves in one hub and not in
another.

1. `data_get(project=TEMPLATE_LIBRARY_PROJECT, folder=TEMPLATE_LIBRARY_FOLDER, recursive=false)` -
   the same listing Phase 5 step 1 resolves the template from. A row in `files` whose `name` matches
   the named template (or `DEFAULT_TEMPLATE`), case-insensitively, passes the gate. `Project not
   found: <name>. Available: ...`, a folder miss, or no matching name = STOP. `truncated` /
   `time_truncated` true with no match is an incomplete read, not an absent template - say so.
2. On a STOP: report the active hub (`data_get()` -> `active_hub`) and what did not resolve in it,
   then leave the switch to the operator. Saved documents with unsaved edits can block a hub switch;
   never-saved documents can remain open. After a switch, re-read `doc_get` and resolve hub-scoped
   URNs again. The skill never calls `data_switch_hub` itself. Do not name the hub the template is in -
   no read here sees another hub's contents.

## Phase 1 - Propose the machining face (READ)

`AUTO_PICK = "manual"` -> skip this phase and run Phase 2 as written. Otherwise the skill proposes
one face from measured geometry and the operator confirms it in the conversation. Every exit from
this phase other than a confirmed proposal runs Phase 2 as written; that pick stays the fallback.

1. `workspace_orient` + `design_get(include=['tree'], tree_bodies=true, tree_handles=true)` - the
   part's bodies. From
   `root_bodies` plus each tree node's `bodies`, keep the rows with `is_solid` true and `visible`
   true, retaining each owning occurrence path. EXPECT exactly one - it is the part. Record its
   `name` for display and its body `handle` as `body_ref`; if no handle reads, use the name only
   when it uniquely identifies that body. Zero, several, or any
   `bodies_truncated` / `root_bodies_truncated`
   flag set: this phase cannot name the part without guessing - report the body names and run
   Phase 2 (the operator's click names the body too). If a same-name body makes a later target read
   ambiguous, do not choose the first row; use the confirmed face handle to keep the owner scoped
   where accepted, or stop if the target still cannot be resolved uniquely.
2. `model_inspect(target=<body_ref or uniquely resolved body name>, units="mm")` - the world-axis bounding box. `BBOX_FACE_MM2` =
   the product of the two largest of `x` / `y` / `z`. Any of the three null -> run Phase 2.
3. `find_geometry(target=<body_ref or uniquely resolved body name>, kind="planar_face", units="mm", max_results=100)` and
   `find_geometry(target=<body_ref or uniquely resolved body name>, kind="cylinder_face", units="mm", max_results=100)`. In
   either response, `match_count` > `returned` means the rows are a subset of the part: record
   `truncated=true` and treat `AUTO_PICK="auto"` as `"propose"` for this run.
4. Candidates, from the planar_face rows. A row carrying no `normal` key is dropped: find_geometry
   omits that key when the face normal did not read, which is not a normal of zero. Keep a row when
   both hold:
   - principal axis: exactly one component of `normal` has absolute value >= 0.999 and the other
     two are <= 0.001 in absolute value. That component's letter and sign is the row's AXIS
     (+X/-X/+Y/-Y/+Z/-Z). A part modelled off the world axes yields no candidate at all - that is a
     fallback to Phase 2, not a failure.
   - size: `area` >= `AUTO_MIN_AREA_FRAC` * `BBOX_FACE_MM2` (inclusive - a face exactly at the
     fraction is kept).
   No candidate survives -> run Phase 2.
5. Score the six axes (not the faces) from the same two reads. For an axis `d`:
   - `co_normal_faces(d)` = planar_face rows whose `normal` dotted with `d` is >= 0.999 - the faces
     pointing the same way as `d`, the candidate itself included.
   - `coaxial_holes(d)` = cylinder_face rows whose `axis` dotted with `d` has an absolute value
     >= 0.999. A cylindrical face's `axis` carries no reliable end-to-end sign, so each such face
     counts for `+d` and for `-d`.
   - `score(d)` = `co_normal_faces(d)` + `coaxial_holes(d)`. `exposure(d)` = `score(d)` divided by
     the sum of `score` over all six axes - null when that sum is 0.
6. Rank: the winning AXIS has the highest `score`; the PROPOSED FACE is the largest-`area`
   candidate carrying that axis. Force `"propose"` (ask, never auto-proceed) when any of these
   holds - each is a tie the numbers do not settle:
   - the winning `score` is less than `AUTO_MARGIN` times the second-highest axis's `score`;
   - the two largest candidate areas on the winning axis differ by less than 1% of the larger;
   - every `score` is 0, i.e. the rank is by area only - say exactly that in the proposal.
7. Evidence: `view_screenshot_multi(views=["top", "front", "right", <the candidate's own view>],
   width=800, height=600)`. The candidate's view is the one looking at its axis: +X `right`,
   -X `left`, +Y `back`, -Y `front`, +Z `top`, -Z `bottom`; a duplicate name collapses (the tool
   returns one image per distinct view) and its response names the views it captured. The images
   come back inline, each labelled `View: <name>`; view_screenshot_multi writes no file and returns
   no path, so the proposal names the views. With `EVIDENCE_DIR` set, also
   `view_screenshot(view=<name>, file_path=<EVIDENCE_DIR>/<model>_<name>.png)` per view and quote
   the `file_path=` and `size_bytes=` that response reports back - those are the only screenshot
   paths this skill can state.
8. The proposal, shown to the operator as one block, every number quoted from the reads above:
   - the face `handle`, verbatim;
   - the AXIS plus the raw `normal`;
   - `area` in mm2, and that as a percentage of `BBOX_FACE_MM2`;
   - `position` - the face centroid, world mm;
   - the rank reason: `co_normal_faces` + `coaxial_holes` = `score` for this axis, its `exposure`,
     the runner-up axis and its score, whether the `AUTO_MARGIN` margin held, and `truncated` when
     step 3 set it;
   - the evidence views (plus the written paths when `EVIDENCE_DIR` is set);
   - the limits: this rank is geometry only. It counts faces that face the axis and round faces
     aligned to it, and nothing more. It does not read fixture access or clamping - which faces the
     vise can grip, what the jaws will cover, how the part is held - nor whether a counted round
     face is open to this face rather than blind, buried or entered from the far end, nor whether
     the part needs a second setup. A yes settles the machining Z direction and nothing else.
9. The question. `AUTO_PICK="auto"` and step 6 forced nothing -> skip the question, proceed, and
   report the proposal as made. Otherwise one `AskUserQuestion`, header `"Machining face"`,
   question `"Machine from this face? <AXIS>, <area> mm2, centroid <position>."`, options exactly:
   `"Yes - machine from this face"` (proceed) / `"No - I will pick in Fusion"` (run Phase 2) /
   `"Cancel"` (stop the skill). Any answer outside these three = stop and report it.
10. On a yes, re-acquire the handle before anything consumes it: find_geometry handles are
    short-lived, and the operator may have taken a while to answer.
    `find_geometry(target=<body_ref or uniquely resolved body name>, kind="planar_face", nearest_to=<the proposal's position>,
    units="mm", max_results=5)`, then take the row whose `position` is within 0.01 mm on each axis
    of the proposed one and whose `normal` matches it within 0.001 per component. No such row =
    STOP and report both records.

-> Record: `zdir` (= the re-acquired row's `normal`), `body_name`, `body_ref`, face `handle` (= the
re-acquired row's `handle`). These values continue at Phase 2 step 4; skip Phase 2 steps 1-3.

## Phase 2 - Machining face + orientation (READ)

Two paths for the human step, one outcome. Which one runs depends on the tools the executing agent
holds; both end with step 3's three recorded values and continue at step 4.

- PATH A - `AskUserQuestion` (the default; steps 1-3 below). One question, with no selection hold,
  no timeout and no polling. The operator clicks the face in Fusion at their own pace, then
  answers, which hands control back.
- PATH B - `sys_request_selection`, for an agent that holds no AskUserQuestion. A pick in Fusion
  with no confirm or cancel: the click itself is the answer, so there is nothing to answer in chat
  and no "read my selection again" option. First say in chat what to click: the hold shows no
  prompt inside Fusion, and it clears the operator's current selection (`clear_current` defaults
  true). Then one `sys_request_selection(what="face", wait_seconds=<keep it under your MCP client's
  per-call timeout>)`. `status="picked"` -> take `selections[0]` and go straight to step 3: the
  record carries the same `direction`, `direction_kind`, `body_name` and `handle` a
  `sys_get_selection` record does, so step 3 reads it the same way. `status="timeout"` -> nothing
  was picked (this is ok, not an error); tell the operator what to click, get their go-ahead, and
  request once more - never re-fire in a loop. A null `direction` (a sphere, or a normal that did
  not read) is not a machining face: ask for a different face, as step 2's second branch does.

1. `sys_get_selection(require="face")` - read whatever is selected right now.
2. `AskUserQuestion` with a fixed shape, header `"Machining face"`:
   - A face with a non-null `direction` is in hand -> question `"Selected: <face summary> on
     <body>, normal <direction>. Use this as the Z-normal machining face for <model>?"`,
     options exactly: `"Yes - use this face"` (proceed) / `"Read my selection again"` (the
     operator has clicked a different face in Fusion; re-run step 1 and re-ask) / `"Cancel"`
     (stop the skill).
   - Nothing usable selected (or a null `direction`, e.g. a sphere) -> question `"No usable
     face is selected. In Fusion, click the machining face - the face whose normal is the
     machining Z - then choose Continue."`, options exactly: `"Continue - read my selection"`
     (re-run step 1 and re-ask) / `"Cancel"` (stop).
   Any free-text answer outside these options = stop and report it.
3. From the confirmed record: `zdir` (= `direction`), `body_name`, and the face `handle`
   (selection reads return find_geometry-style handles). Resolve the body name to one body row in
   `design_get(include=['tree'], tree_bodies=true, tree_handles=true)` and record its body handle
   as `body_ref`; if the name matches multiple rows, use an accepted scoped handle or stop instead
   of choosing the first. If no body handle reads, use the name only when unique.
4. `workspace_orient` + `doc_get` - record model name, units, and identity:
   - unsaved (`has_data_file` false): derive the model name (operator's name for the part,
     else the dominant body's name, else ask once - never "Untitled"); destination =
     `DEFAULT_PROJECT` / `DEFAULT_FOLDER`.
   - saved: destination = the part's own folder (`data_get` on its `document_id` ->
     `folder_path`); record the existing URN.

-> Record: `zdir`, `body_name`, `body_ref`, face `handle`, model name, units, URN or null,
destination.

## Phase 3 - "Center of Model" part-space origin (WRITE)

1. `joint_create_origin(anchor="bbox_center", bbox_target=<body_ref or uniquely resolved body name>, orient_axis=<face
   handle>, name="Center of Model")` - builds the frame at the part's bbox center with Z along
   the picked face's normal, and verifies its own placement (it rolls back and errors if the
   origin lands off its computed center). EXPECT: the response's `frame_axes.primary_axis_Z`
   is parallel to `zdir` - a negation means the selection went stale; redo Phase 2 step 2.
2. `model_inspect(target=<body_ref or uniquely resolved body name>, frame="Center of Model", units="mm")` - the part-space
   extents (Z = machining axis). EXPECT: non-zero x/y/z; `center` matches step 1's center.

-> Record: `extents_mm` (x/y/z; z feeds the Phase 7 stock-top offset).

## Phase 4 - Save the part with the JO (WRITE, async)

1. Unsaved: `doc_save_as(name=<model>, project=<destination>, folder=<destination>,
   create_path=true)`. Saved: `doc_save()`. Either way the new version captures the JO, and the
   Phase 7 insert references this saved version.
2. `doc_get` - EXPECT the active document is the part, saved, with a URN. Record URN + version.

## Phase 5 - Resolve and copy the template (WRITE, async)

1. `data_get(project=TEMPLATE_LIBRARY_PROJECT, folder=TEMPLATE_LIBRARY_FOLDER,
   recursive=false)` - the eligible templates are exactly this listing. Match the operator's
   named template (exact, case-insensitive) or use `DEFAULT_TEMPLATE`; a miss = STOP and
   report the available names. Record `TEMPLATE_URN` from the listing - never a URN from
   memory or another folder.
2. `doc_open(<TEMPLATE_URN>, force_api_open=true)`, then `doc_get` until the template is the
   active document. (Copy = open then save-as: `doc_copy` on a closed template makes Fusion
   reconcile its whole reference graph server-side, which destabilizes the session - see
   reference.md.)
3. `doc_save_as(name=<model> + TEMPLATE_NAME_SUFFIX, project=<destination>,
   folder=<destination>, create_path=true)` - the copy becomes the active document.
4. `doc_get` - EXPECT `active_document` = `<model>_CAM`; record its URN. The library original
   is never modified.

## Phase 6 - Verify the template's wiring (READ)

All reads are against the now-active `<model>_CAM`. Each wiring fact comes from CONFIGURATION and
is verified against the read: a pinned name missing from the document = STOP, reporting the names
that were found. Only a blank ("") config entry is inferred from the read, and an ambiguous
inference is settled with an `AskUserQuestion` listing the read names as options, never by picking
one silently.

1. `cam_get` - EXPECT `SETUP` among the setups. When `SETUP` is blank, use the active milling
   setup only if exactly one is active; otherwise use the sole milling setup only if exactly one
   exists. If several milling setups remain, ask which named setup to use - never choose the first
   by list order. Record the setup, its selected model names, and its stock/fixture names.
   `selected_models` null (the setup names it in `model_lists_unreadable`) means the list was not
   read; `[]` means the setup selects no model. `model_lists_truncated` true means the combined
   model/fixture/stock listing is incomplete. An unreadable or empty model list, or any truncated
   listing, prevents slot selection: report which state applies and STOP.
2. Resolve the selected model slot without assuming the first row is the placeholder. If one model
   is selected, locate its exact occurrence in `design_get(include=['tree'], tree_handles=true)`;
   if several are selected, ask which one is the replaceable slot. The CAM setup row contains names,
   so match them against the tree and present each candidate's `full_path`/handle when names repeat. If the
   list cannot be mapped to exactly one occurrence, ask among the tree paths or STOP; never select
   `[0]`. Then call `design_get(include=['tree'], tree_handles=true,
   component=<resolved model component occurrence>)`.
   EXPECT `PLACEHOLDER` among its child occurrences (blank: the one child occurrence with bodies
   whose name is not WCS/zero-like - a lone cube named like "WCS"/"zero" is the setup's WCS
   cube, never delete it). If the pinned name matches several children, or blank inference yields
   several candidates, ask with each child's `full_path`/handle plus "No placeholder - insert
   alongside" and "Cancel". Pass the chosen exact path/handle to `remove_existing`, not a repeated
   bare name. `children_truncated` true on the model component's node means the children listed
   are a subset (the level was cut by `max_results`), so re-read it with `max_results` above that
   node's `child_count` before naming a placeholder - picking one out of a partial level guesses.
   Bodies sitting directly in the model component itself (no occurrence to remove) = STOP and
   report the listing.
3. `assembly_get(include=['joint_origins'])` - EXPECT `ATTACH_JO` among the joint origins
   whose `component` is the root component (blank: the root JO matching Attach / Center of
   Model / Workpiece; several = AskUserQuestion with the read names; none = record none and
   Phase 7 seats on the stock top instead). Also record the placeholder's own JO
   `world_position` if it carries one - it marks the seat the part must land on, and it is
   gone once the placeholder is deleted.
4. `param_get()` - record which of `PART_PARAMS` exist as user parameters.

-> Record: setup, model component occurrence, stock name, placeholder (or none), attach JO
(or none), the seat position, which PART_PARAMS exist.

## Phase 7 - Insert and seat the part (WRITE)

1. `doc_insert_occurrence(document_id=<part URN>, into_component=<model component occurrence>
   [, remove_existing=<placeholder occurrence>])` - inserts the part as an x-ref at identity
   and clears the placeholder in the same call. Record `new_occurrence_name`. (If the tree
   later shows the reference stale, `doc_update_xref(name=<model>)`.)
2. `assembly_ground(occurrence=<new_occurrence_name>, ground_to_parent=false)` - an inserted
   occurrence is locked to its parent by default; free it so the joint can position it.
3. Join the part's JO to the template, one of two ways:
   - Root JO recorded: `joint_create(occurrence_one="Center of Model",
     occurrence_two=<root JO>, joint_type="rigid")` - the template JO's offsets position the
     part; nothing to measure.
   - No root JO: `joint_create(occurrence_one="Center of Model",
     occurrence_two="<stock occurrence>:top", joint_type="rigid",
     offset=-(0.5 * <extents_mm.z> + 1), units="mm")` - offsets the part's CENTER from the
     stock-top snap by half its machining-axis thickness plus the 1 mm skim allowance. Treat this
     as a candidate translation; the negative input alone does not prove which side the solved
     joint places the part on.
   Each side is a Joint Origin name (bare, or `<occurrence>:<JO name>`) or a snap; on a
   resolve error the tool lists the design's JOs - correct the name and retry once.
4. Verify from numbers: `assembly_get` - EXPECT the new joint is not in `broken_joints`
   (pre-existing template warnings are not yours to fix). `model_inspect(target=<inserted
   occurrence full path>, units="mm")` - a world-frame read with no `frame=` argument. When the
   root JO path was used and a placeholder seat was recorded, EXPECT `center` at that JO position.
   On the stock-top path, independently read the stock top and inserted-part
   world bounds in mm. The `:top` snap is the +Z extreme planar face; verify the signed gap
   `stock_top_Z - part_max_Z` is +1 mm (within read precision), and that the part center is half
   its measured world Z thickness below its top. If either bound, sign, or gap cannot be read or
   does not match, placement is unverified/failed; do not report it seated or blindly flip the
   offset.
5. Stock (only if Phase 6 found PART_PARAMS): `model_inspect(target=<inserted occurrence full
   path>, units="mm")` - measure after the join, in world axes (the join reorients the part, so
   Phase 3's pre-join extents land on the wrong axes) - then `param_set` each parameter from
   this reading. No PART_PARAMS = skip, and say the stock was left as the template defines.
6. Naming (best-effort; neither write gates completion): call
   `sketch_set_text(text=<model>, sketch_name=NAMEPLATE_SKETCH)`. When the tool returns its
   explicit error that no sketch text was found in that named sketch, report the nameplate as not
   set and continue; this case is an error response, not `changed_count: 0`. Report other errors
   as failures. Then call `cam_set_nc_comment(comment=<model>)`. If it returns
   "This document has no NC programs.", report that no NC comment was written and continue;
   report other errors as failures.
7. `doc_save()` - the insert, joint, and parameters are session-only until saved.

## Phase 8 - Generate the toolpaths (WRITE, async)

The insert and stock resize invalidate the template's operations; the job is not finished until
they regenerate.

1. `view_switch_workspace` to Manufacture - out-of-date state is only re-evaluated against
   the new geometry once Manufacture is active; generating from Design can wrongly skip
   stale operations.
2. `cam_generate()` (whole document) - returns a handle immediately; generation runs in the
   background at its own pace (often minutes).
3. `cam_get_status(handle=<handle>)` - check it about once a minute until `completed` is true,
   or the status explicitly reports BLOCKED/error while incomplete; do nothing in between.
   `completed=true` means generation settled, not that it succeeded or that the job is ready to
   post; read `readiness` separately. For example, one valid operation can be `completed=true`
   while `readiness` says the setup has no machine selected. If incomplete status reports
   BLOCKED/error, stop polling and report its error; do not launch overlapping generation. An
   errored operation can also be settled: when `completed=true`, stop polling and report its error
   from the status/CAM reads rather than treating completion as success.
4. `cam_get` - EXPECT no out_of_date or errored operations among the unsuppressed ones, and compare
   `cam_get_status.readiness` for setup/program blockers. Failures or unknown readiness = report
   each by name/reason; do not silently accept a partial or not-ready job.
5. `doc_save()` - capture the generated job.

## Phase 9 - Machine-limit check (READ)

A template's tool presets and a setup's machine are set by different people in different places, and
nothing in the insert chain compares them. This phase compares the two numbers - the rpm each
operation asks for against the rpm its setup's machine can turn - and hands the operator a table.
It changes nothing: which spindle speed a preset should carry is the shop's decision, not the
skill's.

1. `cam_get(include=['machine'])` - one call, every setup. Each `setups` row carries `setup`,
   `machine` (the label), `kinematics_readable`, `spindle` (`max_rpm` / `min_rpm`, or null when no
   spindle answered a speed - a 0 is never published as a limit) and `axes` (per axis: `kind`,
   `travel` + `range` + `units` for a linear axis, `travel_deg` / `range_deg` for a rotary one,
   `is_infinite: true` with no number for an unlimited one). `kinematics_readable: false` with
   `blocked_by: ["no_machine_selected"]` means the setup has no machine - the comparison below is
   impossible for that setup; say so, never treat it as "within limits".
2. `cam_get(include=['default', 'operations'])` - one call, every setup (a deep include omits the
   default slice unless it is named, and step 3 reads that slice). The setup row carries
   `machine_spindle_max_rpm` (the same number as step 1's `spindle.max_rpm`). Each operation row
   carries `name`, `state`, `preset` (the tool preset it uses, null when none), `folder` (the
   CAM folder it sits in, beside `is_suppressed`) and the comparison:
   - `spindle_over_machine_max: true` plus `spindle_rpm` and `machine_max_rpm` - the op asks for
     more than the machine can turn;
   - `spindle_over_machine_max: null` plus `spindle_check` naming the unreadable side
     (`machine_max_unavailable` / `op_spindle_speed_unreadable`) - not checked;
   - no `spindle_over_machine_max` key at all - checked, at or under the maximum.
3. Completeness before counting: a setup's `operations_truncated`, or the payload's own `truncated`,
   means the rows are a subset - label the table PARTIAL and quote rows read against each setup's
   `operation_count` from the default slice. A partial read is never reported as "within limits".
4. Fusion's own warning, if any, is on the row as `has_warning: true` + `warning` (absent means
   Fusion raised none). Quote any warning text verbatim beside the numbers; it names what Fusion
   compared. The warning and the numbers should agree; if they do not, report both rather than
   picking one.
5. The table, for the operator to read before hand-over: one row per operation that is over
   (name, preset, `spindle_rpm` vs `machine_max_rpm`, the ratio), then the not-checked operations
   with their `spindle_check` reason, then a one-line count of the operations that checked clean.
   STOP only if step 2 errors: with no operation list there is nothing to check, so report the
   error.

-> Record: the machine's `spindle.max_rpm` per setup, the over-max operations with both numbers,
the operations that could not be checked and why, and any warning text quoted.

## Phase 10 - Verify and report (READ)

1. `data_get(project=<destination project>, folder=<destination folder>)` - EXPECT the part
   and `<model>_CAM` both listed.
2. `view_screenshot` - the part seated in the fixture.

Report: destination folder, part URN, `<model>_CAM` URN, part-space extents, the join used
(attach JO or stock top), PART_PARAMS written or skipped, the generation outcome per setup,
and the screenshot. Also which face-pick path ran - a Phase 1 proposal the operator confirmed, a
Phase 1 proposal taken under `AUTO_PICK="auto"`, or the Phase 2 pick (naming whether that pick came
through `AskUserQuestion` or `sys_request_selection`) - and for either Phase 1 path the rank reason
it was proposed on. Carry Phase 9's limit table verbatim: the hand-over states which operations
exceed the machine and which could not be checked, not just that the job generated.
