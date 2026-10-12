# Tool & Input-Kind Manifest (generated)

_Auto-generated from the live registry by `tests/gen_manifest.py`. Do not edit by hand — re-run the generator after adding/renaming a tool or kind. `--check` fails the suite if this is stale. This is the batch form of the `sys_find_tool` live lookup: the one place to see what already exists before building it._

**Tools:** 224  |  **Input-kinds:** 33  |  write-status: `·` read · `✎` write · `⚠` destructive

## Input kinds — reference EXISTING geometry/structure with these (don't hand-roll a name/index)

Before adding a tool input that points at a face/edge/body/plane/axis/profile/occurrence, use one of these (extend the kind if it's close). See `CLAUDE.md` 'Input kinds'.

| Kind | What it references |
|---|---|
| `AxisRef` | A direction/axis: a world axis (x / y / z), a 'handle' pointing at a straight (linear) EDGE, a |
| `BodyRef` | A reference to a BODY, by a 'handle' from find_geometry (precise - bodies are auto-named |
| `BodyRefList` | A LIST of body references (handles or names) - for tools that act on several bodies. Kind-checks |
| `Choice` | One of a fixed set of string options. Emits a JSON-schema `enum` so the legal values are |
| `CurvePointRef` | A point of a drawing view curve as '<curve_index>:<start\|end\|mid\|center>'. |
| `Distance` | A length value in display 'units', resolved to Fusion's internal cm. The companion 'units' |
| `EdgeLoopRef` | A boundary of find_geometry edge handles: closed=True a CLOSED loop, a one-body set checked |
| `FeatureEditOperands` | A references array resolved by the selected feature action's typed operand kind. |
| `FeatureRef` | A reference to ONE timeline FEATURE by name, '<component>/<name>', or timeline index, as |
| `FeatureRefList` | A LIST of timeline features, resolving to (entities, labels) - the entity list plus the |
| `FormCageHandleList` | A LIST of Form cage handles: vertices, edges or faces of ONE Form's control cage. |
| `GeometryHandle` | A reference to EXISTING geometry, as a SHORT-LIVED handle from find_geometry (an entityToken). |
| `GeometryHandleList` | A LIST of geometry handles (e.g. the specific edges to fillet, the bodies to mirror). Accepts a |
| `JointOriginRef` | A reference to a Joint Origin (a reusable WCS coordinate frame), as EITHER a 'handle' (the |
| `LoftEndCondition` | One loft end's condition; legal_on() refuses one its section cannot take, before Fusion. |
| `LoftSectionList` | ORDERED loft sections, each as (what LoftSections.add takes, its kind, the entity named). |
| `OccurrenceRef` | A reference to an assembly OCCURRENCE (a component instance): a `handle` - its entityToken, which |
| `OccurrenceRefList` | A list of occurrence references (JSON list or comma-separated), each resolved via OccurrenceRef's |
| `PlaneRef` | A reference to a PLANE to act on, resolved from ANY of three shapes a user might supply: |
| `PlasticRuleRef` | Resolve one scoped plastic rule, refusing ambiguous or stale references. |
| `PointRef` | A point operand: a point handle, a point or circle/arc centre index ref, or a datum name. |
| `PointRefList` | An ORDERED list of point operands, each resolved through PointRef. |
| `ProfileRef` | A reference to a sketch PROFILE - a stable 'handle' (entityToken, order-stable across rebuilds) |
| `ProfileRefList` | An ORDERED list of profile references - for loft, where profile ORDER is load-bearing (the loft |
| `SectionRef` | A reference to one SectionAnalysis by its generated name from view_section cut/list. |
| `SheetMetalRuleRef` | A rule selected by scoped name or a current scope/index/name ref. |
| `SketchDimensionRef` | An existing sketch dimension by its parameter name, among ONE sketch's own dimensions. |
| `SketchLineRef` | An exact sketch line from sketch_get, optionally scoped to a component. |
| `SketchRefList` | A LIST of SKETCHES by name - the reference an operation taking WHOLE sketches needs (a CAM |
| `SurfaceRef` | The FACE/PLANE a sketch entity is constrained or dimensioned to. Schema and resolution come |
| `TargetRef` | A reference to a THING to measure/colour, resolved from any of several shapes: |
| `TargetRefList` | A LIST of targets - each a BODY (handle/name) or a component OCCURRENCE (name/fullPathName), |
| `UnitField` | The 'units' selector. resolve() returns the cm-per-unit scale factor. |

## Tools by family

### model

| | Tool | Summary |
|---|---|---|
| ✎ | `model_arrange` | Nest occurrences into a sketch-profile or plane envelope, 2D true-shape/rectangular or 3D packing. |
| ✎ | `model_base_feature` | Open or close a base-feature direct-edit scope; the mesh_* tools open and finish one per call. |
| ✎ | `model_chamfer` | Bevel edges; model_fillet rounds |
| ✎ | `model_combine` | Boolean-combine solid bodies: join, cut or intersect 'tools' into 'target', the body that survives. |
| · | `model_compute_holder` | Profile a solid holder body into CAM tool-holder segments, returned with 'holder_json'. |
| ✎ | `model_construction` | Add a construction point, axis or plane; each 'mode' reads its own inputs. |
| ✎ | `model_create_component` | Create a new EMPTY component occurrence, at root unless 'parent' nests it |
| ✎ | `model_create_rib` | Create a rib or web from ordered sketch curves into an explicit solid |
| ✎ | `model_draft` | Taper (draft) faces relative to a pull plane |
| ✎ | `model_edit_body` | Copy, move or rehome a body; merge two coplanar faces in direct mode |
| ✎ | `model_edit_extrude` | Edit solid Extrude; refs from design_get/sketch_get. |
| ✎ | `model_edit_feature` | Edit one aspect; design_get lists typed inputs |
| ✎ | `model_edit_loft` | Retarget, remove or reorder one Loft section |
| ✎ | `model_edit_sweep` | Edit Sweep operands or Boolean scope; read model_inspect. |
| ✎ | `model_emboss` | Stamp sketch profiles or text onto faces; a negative 'depth' engraves |
| ✎ | `model_extrude` | Extrude sketch profiles/curves as solids or surfaces. |
| ✎ | `model_fillet` | Fillet edges; model_chamfer bevels |
| ✎ | `model_hole` | Drill a Hole feature; multiple points share one feature. |
| · | `model_inspect` | Measure bounds or mesh stats; opt-in mass/material/appearance. |
| ✎ | `model_loft` | Loft ordered sections; G1/G2: open surface edge to open sketch curve |
| · | `model_measure_between` | Measure the distance or angle between two targets; a distance of 0 is touching. |
| · | `model_measure_continuity` | Measure gap, normal angle and curvature jump across each edge's seam; a one-faced edge reads against the 'against' body. |
| · | `model_measure_relation` | Judge a geometric relation between two entities |
| ✎ | `model_mirror` | Mirror bodies or timeline features across a plane. |
| ✎ | `model_move` | Move BRep bodies as a timeline feature, or translate mesh bodies; assembly_move moves an occurrence |
| ✎ | `model_offset_face` | Push faces along the normal; positive adds material |
| ✎ | `model_pattern_circular` | Pattern occurrences or bodies evenly around an axis |
| ✎ | `model_pattern_path` | Pattern occurrences, bodies, faces or features along a path; one seed kind per call |
| ✎ | `model_pattern_rectangular` | Pattern occurrences or bodies in a rectangular grid |
| ✎ | `model_pipe` | Build a pipe along a path |
| ✎ | `model_replace_face` | Replace body faces with an open surface (see surface_patch) |
| ✎ | `model_revolve` | Revolve a sketch profile about an axis; it must not cross the axis. |
| ✎ | `model_scale` | Resize solid bodies about an anchor point that stays put |
| ✎ | `model_set_material` | Assign a PHYSICAL material; appearance_set does color |
| ✎ | `model_shell` | Hollow a solid; 'remove_faces' opens the shell |
| ✎ | `model_split` | Split a body, or its faces by a cutter or silhouette |
| ✎ | `model_stitch` | Stitch surface bodies into a solid; 'became_solid' reports whether they closed. |
| ✎ | `model_sweep` | Sweep |
| ✎ | `model_thread` | Thread an existing cylindrical face; model_hole taps its holes |
| ✎ | `model_unstitch` | Explode a body into per-face surface bodies - the inverse of model_stitch. |

### surface

| | Tool | Summary |
|---|---|---|
| ✎ | `surface_create_ruled` | Create a ruled surface off an edge chain. |
| ✎ | `surface_delete_face` | Delete faces from their bodies; 'heal'=false leaves the opening, turning a solid into a surface |
| ✎ | `surface_extend` | Extend an open surface outward from its open edges. |
| ✎ | `surface_extrude` | Extrude an open profile into a sheet body; model_extrude takes closed regions (solid, or as_surface). |
| ✎ | `surface_fill` | Seal the volume enclosed by several surface and/or solid bodies into a solid |
| ✎ | `surface_offset` | Offset faces into another surface body. |
| ✎ | `surface_patch` | Patch closed loops; read per-edge conditions; compare seam normals at matching points. |
| ✎ | `surface_reverse_normal` | Reverse the normals of open surface bodies; ALL faces of each are flipped |
| ✎ | `surface_revolve` | Revolve an open profile into a sheet body; model_revolve makes a solid. |
| ✎ | `surface_thicken` | Thicken faces into a solid wall. |
| ✎ | `surface_trim` | Trim a surface body with an intersecting tool; only the target loses cells. |
| ✎ | `surface_untrim` | Restore trimmed faces to their natural extent, or remove an internal hole loop |

### form

| | Tool | Summary |
|---|---|---|
| ✎ | `form_create` | Create a T-spline Form's B-Rep body from a primitive centred on origin (the cylinder is 8-sided), or a quad cage; form_get(include=['cage']) reads one back |
| ✎ | `form_edit` | Move a Form body or selected cage vertices/faces, or crease cage edges in place |
| · | `form_get` | List T-spline Forms with their creation records; include=['cage'] returns one Form's cage for form_create. |

### mesh

| | Tool | Summary |
|---|---|---|
| ✎ | `mesh_combine` | Boolean-combine MESH bodies: 'tools' into 'target', the body that survives; model_combine sees only BRep solids. |
| ⚠ | `mesh_delete` | Delete a MESH body - design_delete_feature and design_delete_occurrence cannot reach one. |
| ✎ | `mesh_export` | Export geometry to a MESH file on local disk |
| · | `mesh_find` | Acquire scoped mesh groups, nodes, triangles, ray hits or a silhouette |
| ✎ | `mesh_generate_face_groups` | Segment a MESH body into planar FACE GROUPS - required before mesh_to_brep(method='prismatic'). |
| · | `mesh_get` | List the MESH bodies in a component or the whole design - the BRep tools cannot see them |
| ✎ | `mesh_insert` | Insert exactly one LOCAL file_path or triangle data as mesh |
| ✎ | `mesh_plane_cut` | Cut a MESH body with a plane - trim, split into two bodies, or split the triangulation. |
| ✎ | `mesh_reduce` | Decimate (reduce the triangle count of) a MESH body. |
| ✎ | `mesh_remesh` | Regenerate a cleaner, more uniform triangulation of a MESH body. |
| ✎ | `mesh_repair` | Repair a MESH body - close holes, stitch, wrap, rebuild, or one-touch fix. |
| ✎ | `mesh_reverse_normal` | Flip the normals of a MESH body - what an inside-out imported mesh needs. |
| ✎ | `mesh_separate` | Split a MESH body into its disconnected shells; the input body is CONSUMED. |
| ✎ | `mesh_shell` | Hollow a MESH body in place - the BRep model_shell cannot reach a mesh. |
| ✎ | `mesh_smooth` | Smooth a MESH body - relaxes scan noise and faceting. |
| ✎ | `mesh_to_brep` | Convert a MESH body into a BRep solid, or an OPEN mesh into a surface with method='faceted' - the bridge back to find_geometry / fillet / CAM. |

### sketch

| | Tool | Summary |
|---|---|---|
| ✎ | `sketch_add_3d_line` | Draw a sketch line whose end may sit OFF the sketch plane: x/y/z are in 'units', z along the sketch's own normal |
| ✎ | `sketch_add_3d_spline` | Draw a fitted or control-point 3D spline from 'points' or a 'helix'; model_pipe/model_sweep take path='sketch:<name>'. |
| ✎ | `sketch_add_geometry` | Draw entities on a sketch; coords in 'units', angles in degrees. |
| ✎ | `sketch_constrain` | Apply geometric constraints to one sketch, entities '<type>:<index>'. |
| ✎ | `sketch_copy` | COPY sketch entities, transformed or mirrored. |
| ✎ | `sketch_create` | Create a sketch on a plane or a planar face; draw on it with sketch_add_geometry. |
| ⚠ | `sketch_delete_entity` | Delete ONE sketch entity, constraint, dimension or text, named as '<type>:<index>'. |
| ✎ | `sketch_dimension` | Add dimensions, or edit an existing dimension's driving state/label position; sketch_get reads it. |
| ✎ | `sketch_edit` | Edit sketch name, visibility or plane; sketch_get reads it. |
| ✎ | `sketch_edit_curve` | Edit an EXISTING sketch curve in place |
| · | `sketch_get` | Read sketches, curves, constraints and profile handles for model_extrude. |
| ✎ | `sketch_insert_svg` | Import an SVG into a sketch at (x,y) |
| ✎ | `sketch_move` | MOVE existing sketch entities by one transform |
| ✎ | `sketch_project` | Create sketch curves from model geometry |
| ✎ | `sketch_set_text` | Set the displayed string of sketch text, or add new text with create=true. |

### cam

| | Tool | Summary |
|---|---|---|
| ✎ | `cam_activate_setup` | Activate a CAM setup and fit the view for view_screenshot. |
| ✎ | `cam_apply_template` | Apply a CAM toolpath template to a setup, recreating its operations there |
| · | `cam_compare_operations` | Compare two CAM operations by name: which parameters and which geometry selections differ, with the value on each side. |
| ✎ | `cam_create_machine` | Create a MACHINE in the LOCAL machine library from a Fusion machine template, so cam_edit_setup(machine=...) can assign it by name. |
| ✎ | `cam_create_operation` | Create a CAM milling operation in a setup, with a cutting tool from cam_edit_tools |
| ✎ | `cam_create_setup` | Create a CAM setup |
| ⚠ | `cam_delete` | Delete a CAM setup, operation, folder, pattern or NC program by name (design_delete_* do not reach CAM data). |
| ⚠ | `cam_delete_machine` | Delete a machine from the LOCAL machine library by name; 'confirm_name' must match the resolved name exactly |
| ⚠ | `cam_delete_template` | Delete a template from the LOCAL toolpath template library by name, or by the 'template_url' cam_get(include=['templates']) lists; 'confirm_name' must match the... |
| ✎ | `cam_edit_folders` | Manage a CAM setup's folders: list, create, rename, or move operations into one. |
| ✎ | `cam_edit_operation` | Edit a CAM operation: its parameters (the feeds/speeds/depths no other CAM tool reaches), its cutting tool, preset, name or suppression |
| ✎ | `cam_edit_setup` | Edit a CAM SETUP: its machine, its model/fixture/stock selections (bodies or occurrence names, each REPLACED), its WCS, any other setup parameter, or its name |
| ✎ | `cam_edit_tools` | Read and manage CAM TOOL LIBRARIES and their tools - list, add, remove or edit tools, manage presets, or create a library |
| ✎ | `cam_export_setup` | Write an additive setup's parts, as placed, to a 3MF file; supports and slices are left out |
| · | `cam_find_holes` | Recognize solid bodies' holes, GROUPED by similar geometry, for cam_select_geometry(selection='holes') |
| · | `cam_find_pockets` | Recognize solid bodies' pockets down an attack vector, for cam_select_geometry(selection='pocket') |
| ✎ | `cam_generate` | Launch CAM toolpath (re)generation from the MANUFACTURE workspace |
| ✎ | `cam_generate_setup_sheet` | Generate a machinist SETUP SHEET, named after the DOCUMENT - a second call to the same folder overwrites it |
| · | `cam_get` | Read CAM state: setup summary by default, deeper slices via 'include' |
| · | `cam_get_status` | Read toolpath generation progress; 'readiness' carries the verdict |
| · | `cam_inspect_toolpaths` | Check CAM toolpath validity |
| ✎ | `cam_post` | Create (or reuse) an NC Program and post it to a G-code / NC file on disk - the final CAM step |
| ✎ | `cam_reorder` | Reorder a CAM item in the machining sequence: move 'entity' before or after 'reference' (both are names from cam_get / cam_edit_folders) |
| ✎ | `cam_save_template` | Bundle some of a setup's operations into a NEW toolpath template. |
| ✎ | `cam_select_geometry` | Select CAM geometry |
| ✎ | `cam_set_nc_comment` | Set an NC program's COMMENT, its listing NAME (what cam_post addresses) and its program NUMBER (nc_program_name, what the post emits). |
| ✎ | `cam_show_toolpath` | Show or hide CAM toolpaths to inspect one operation's path at a time |

### assembly

| | Tool | Summary |
|---|---|---|
| ✎ | `assembly_capture_position` | Capture the assembly's current pose into the timeline as a Position marker - a pose is TRANSIENT until captured. |
| ✎ | `assembly_constrain` | Constrain occurrences' geometry: the relationship (flush / coincident / concentric / angle) is INFERRED, and a SET solves together. |
| ⚠ | `assembly_edit_contacts` | Maintain the design's contact sets - the named groups of occurrences/bodies Fusion checks for contact. |
| ⚠ | `assembly_edit_relations` | Edit or remove an existing assembly relation; create one with assembly_rigid_group / joint_motion_link / assembly_constrain. |
| · | `assembly_get` | Read assembly occurrences, grounding, body counts, joints and health |
| ✎ | `assembly_ground` | Lock an occurrence to its parent (isGroundToParent) |
| · | `assembly_inspect_interference` | Solid overlap/contact; hidden bodies count |
| ✎ | `assembly_move` | Move an occurrence by editing its transform - a free reposition, no joint |
| ✎ | `assembly_rigid_group` | Lock two or more component occurrences together as a single rigid unit (Rigid Group). |

### joint

| | Tool | Summary |
|---|---|---|
| ✎ | `joint_at_geometry` | Joint two parts at two find_geometry handles - the FREE occurrence is the one moved |
| ✎ | `joint_create` | Create a Joint between two inputs: the FREE part MOVES so the two inputs coincide - do not pre-place it. |
| ✎ | `joint_create_as_built` | Joint two occurrences WHERE THEY ALREADY ARE - neither part moves; joint_create moves the free part instead |
| ✎ | `joint_create_origin` | Create a Joint Origin, a reusable coordinate frame; feed it to joint_create or joint_at_geometry by name. |
| ✎ | `joint_drive` | Drive a joint to a value - the pose is TRANSIENT until assembly_capture_position(action='capture') keeps it. |
| ✎ | `joint_edit` | Edit joint; joint_drive poses it |
| ✎ | `joint_motion_link` | Link two existing joints' motion with a ratio (the Motion Link command): driving one drives the other proportionally. |

### design

| | Tool | Summary |
|---|---|---|
| ✎ | `design_activate_component` | Make an existing component the active edit target - new features build into it. |
| ✎ | `design_add_instance` | Place another INSTANCE of a component already in this design - it SHARES the original's geometry unless 'independent'; placement coords in 'units', angles in de... |
| ✎ | `design_configure` | Build or switch a Configured Design; 'action' picks the verb |
| ⚠ | `design_delete_feature` | Delete one timeline feature by name; a pattern/mirror delete takes every instance it created. |
| ⚠ | `design_delete_occurrence` | Delete one component occurrence; if it was the last instance of its component, the component goes too. |
| ✎ | `design_edit_plastic_rule` | Copy a plastic rule into the design, update it or delete an unused design rule |
| ✎ | `design_edit_reference_image` | Create, place, style or delete a root-local canvas or decal from a LOCAL image |
| ⚠ | `design_edit_timeline` | Edit timeline items from design_get(include=['timeline']); roll to='end' when done. |
| ✎ | `design_export` | Export a body, component/occurrence or the whole design (omit 'target') to a CAD file on local disk. |
| · | `design_get` | Design summary and opt-in detail. |
| ✎ | `design_move_occurrence` | Re-parent an occurrence into another occurrence's component |
| ✎ | `design_recompute` | Force a full recompute so downstream features rebuild against current values |
| ✎ | `design_remove_feature` | Remove ONE body or occurrence as a timeline Remove FEATURE. |
| ✎ | `design_set_metadata` | Set a component's part number and/or description; an occurrence sets its COMPONENT's |
| ⚠ | `design_set_mode` | Convert the active design between parametric and direct modeling; going direct destroys the timeline and all design history. |
| ✎ | `design_set_name` | Rename by kind |

### doc

| | Tool | Summary |
|---|---|---|
| ✎ | `doc_activate` | Bring an open document to the foreground (make it the active document). |
| ⚠ | `doc_close` | Close an open document, or every one (close_all) |
| ✎ | `doc_copy` | Copy a cloud document or active occurrence's component into a project/folder |
| · | `doc_get` | Read the SESSION's open documents: which is active, save state, lineage URNs |
| ✎ | `doc_insert_derive` | Derive OPEN source's last SAVED cloud version: one-way linked copy |
| ✎ | `doc_insert_import` | Import a CAD file from LOCAL DISK: solids into a component, DXF as sketches, SVG into a sketch. |
| ✎ | `doc_insert_occurrence` | Insert a SAVED cloud document into the active design as a linked external-reference occurrence, placed at x/y/z |
| ✎ | `doc_new` | Create and open a new, empty design document; it becomes active and stays unsaved until doc_save_as |
| ✎ | `doc_open` | Open a saved cloud document by its data-model id; it becomes the active document. |
| ✎ | `doc_restore_version` | Promote a prior version of the ACTIVE cloud document to latest - a NEW tip version carries its content |
| ✎ | `doc_save` | Save the ACTIVE document in place as a new cloud version; a never-saved one needs doc_save_as. |
| ✎ | `doc_save_as` | Save the ACTIVE document into a cloud project/folder under 'name' - including a design never saved before. |
| ✎ | `doc_save_milestone` | Save the ACTIVE document as a NAMED MILESTONE - a new cloud version marked, findable by name |
| ✎ | `doc_update_xref` | Refresh references and derive links to their latest cloud version, or replace / break ONE occurrence's link per 'action'. |

### data

| | Tool | Summary |
|---|---|---|
| ✎ | `data_create_folder` | Create a folder in a project; a nested 'parent_folder' path creates its missing folders. |
| ✎ | `data_create_project` | Create a new project in the user's active Autodesk hub |
| ⚠ | `data_delete_file` | Delete a document on the cloud, IRREVERSIBLY, by its lineage URN: 'confirm_name' must EXACTLY match the file's current name. |
| ⚠ | `data_delete_folder` | Delete a folder on the cloud, IRREVERSIBLY: 'confirm_name' must EXACTLY match the folder's current name. |
| ✎ | `data_download_file` | Download ONE non-Fusion cloud file to a local folder; the transfer is SYNCHRONOUS and freezes Fusion until it finishes |
| · | `data_get` | Read the CLOUD data model by scope: hubs and projects, one project's files, its folder tree, one folder's summary, or ONE file's record |
| · | `data_get_upload_status` | Poll data_upload_file or async doc_copy: 'state' is uploading, processing, complete (file_id included) or failed. |
| ✎ | `data_move_file` | Move ONE cloud file into an EXISTING folder of its own project; it creates nothing. |
| ✎ | `data_switch_hub` | Switch the active Autodesk data hub after checking cloud-backed edits; list hubs with data_get(include=['hubs']). |
| ✎ | `data_upload_file` | Upload a local CAD file into a project |

### drawing

| | Tool | Summary |
|---|---|---|
| ✎ | `drawing_add_sketch` | New sheet sketch, max 16 curves |
| ✎ | `drawing_add_symbol` | Place one GD&T symbol leadered from a curve point of drawing_get(include=['curves'], view=N) |
| ✎ | `drawing_create` | Create cloud drawing |
| ⚠ | `drawing_delete_sketch` | Delete a drawing sketch by exact name from a sheet of the active drawing |
| ✎ | `drawing_dimension` | Dimension one view of the active drawing: auto, or one dimension on curves from drawing_get(include=['curves'], view=N) |
| ⚠ | `drawing_edit_revisions` | Add, update, delete, hide or show rows of a sheet's one revision table |
| ⚠ | `drawing_edit_sheet` | Manage drawing sheets |
| ✎ | `drawing_export` | Export the active 2D drawing to PDF, DXF or DWG on local disk - open the drawing first (doc_open by file_id) |
| · | `drawing_get` | Read the ACTIVE 2D drawing: standard, units and per-sheet facts. |
| · | `drawing_get_status` | Poll drawing_create, drawing_update or drawing_export by request_key |
| ✎ | `drawing_insert_image` | Place an image file from local disk onto the active drawing's active sheet |
| ✎ | `drawing_update` | Refresh the active 2D drawing's stale references from its saved source |

### param

| | Tool | Summary |
|---|---|---|
| ✎ | `param_add` | Add ONE user parameter (name + expression), or MANY with 'params' |
| ⚠ | `param_delete` | Delete a USER parameter |
| · | `param_get` | Read the active design's parameters - name, expression, value, unit, comment |
| ✎ | `param_set` | Set expression or rename; param_get lists names |
| ✎ | `param_set_favorite` | Toggle a user parameter's 'favorite' flag (whether it appears in the favorites list). |

### pmi

| | Tool | Summary |
|---|---|---|
| ✎ | `pmi_create` | Create a PMI annotation: kind='note' a leader note on ONE face/edge/vertex, kind='hole_note' a callout off the hole/boss faces, 'text' appended |
| ⚠ | `pmi_delete` | Delete ONE PMI annotation by its name from pmi_get |
| ✎ | `pmi_edit` | Edit one PMI annotation, named from pmi_get: 'action' picks the edit and the inputs it reads. |
| · | `pmi_get` | Read the design's PMI - Product Manufacturing Information, the 3D annotations on model geometry, authored and imported alike: counts by kind plus light records,... |

### view

| | Tool | Summary |
|---|---|---|
| · | `view_list_workspaces` | List the Fusion workspaces, each with its id, visible name, product type and whether it is active - the targets view_switch_workspace takes. |
| ✎ | `view_screenshot` | Capture the current Fusion viewport as an image; 'file_path' also writes the PNG to disk, and the image still returns inline |
| · | `view_screenshot_multi` | Capture SEVERAL views of the model in ONE call, as separate labelled images - the shape to reach for when judging a 3D layout |
| ✎ | `view_section` | Cut or list live Section Analyses; 'clear' removes one generated section name, or every section when the name is omitted. |
| ✎ | `view_set` | View-state verbs: aim the camera, isolate/show/hide, set the visual style, toggle the non-body display folders, snapshot and restore - no geometry changes. |
| ✎ | `view_switch_workspace` | Switch the active Fusion workspace; view_list_workspaces lists the targets. |

### render

| | Tool | Summary |
|---|---|---|
| ✎ | `render_create` | Start a local PNG/JPEG/TIFF job or visible in-canvas render |
| ✎ | `render_edit` | Edit scene or restore defaults; activate Render; stop canvas or save a new image. |
| · | `render_get` | Read a local render job, settings, scene, environment catalog or canvas state |

### find

| | Tool | Summary |
|---|---|---|
| · | `find_geometry` | Find world geometry and handles |

### workspace

| | Tool | Summary |
|---|---|---|
| · | `workspace_orient` | Getting started on an open document - the first read: what it is, where it lives, its contents and health, CAM state, and pointers to the tool that drills each ... |

### appearance

| | Tool | Summary |
|---|---|---|
| ✎ | `appearance_set` | Set color/opacity or a library appearance on a face, body, occurrence or component as a revertible override, or clear it. |

### save

| | Tool | Summary |
|---|---|---|
| ✎ | `save_as_mesh` | Tessellate a BRep solid/surface into a persistent MESH body beside it in the design - the inverse of mesh_to_brep. |

### sheet

| | Tool | Summary |
|---|---|---|
| ✎ | `sheet_convert` | Convert a uniform solid using a design rule or rule='active'. |
| ✎ | `sheet_create_flange` | Add a native flange to a sheet body: an edge flange along rim edges, or a base flange from a closed profile |
| ✎ | `sheet_create_flat_pattern` | Create a native flat pattern; inspect sheet_get features before export |
| ✎ | `sheet_create_fold` | Fold at a sketch line; an interior line can extend across the sheet |
| ✎ | `sheet_create_hem` | Hem a sheet body's rim edge: flat, open, rolled, rope, teardrop or double, each with its own dimensions |
| ✎ | `sheet_create_join_by_bend` | Join two sheet bodies with a bend between two rim edges (the preview API merges them into one body) |
| ✎ | `sheet_create_refold` | Refold one explicit unfold feature after adding flat-state edits |
| ✎ | `sheet_create_rip` | Rip a sheet body by a face (takes no gap), along an edge or between two vertices (gap from the rule unless given) |
| ✎ | `sheet_create_unfold` | Unfold sheet-metal bends; cut, then sheet_create_refold. |
| ✎ | `sheet_edit_rule` | Copy or update a design sheet rule, or delete an unused design rule |
| · | `sheet_get` | Read sheet rules and assignments; include rules, library_rules, components or features. |

### sys

| | Tool | Summary |
|---|---|---|
| · | `sys_capability_map` | Start here for help: an overview of every tool FAMILY, its entry tool and count, and each capability beside the tool that answers it |
| ⚠ | `sys_execute_script` | Run Fusion API Python in the live session; prefer a typed tool (sys_find_tool). |
| · | `sys_find_tool` | Search this server's tools by keyword when you don't know the name; sys_capability_map lists the families. |
| · | `sys_get_api_doc` | Search installed Fusion API declarations and full docs |
| · | `sys_get_guidance` | Call with no arguments first for the index and five kernel rules |
| · | `sys_get_preferences` | Read the APPLICATION's preferences: app.preferences, which belong to no document |
| · | `sys_get_selection` | Read the user's CURRENT selection in Fusion |
| ✎ | `sys_reload_addin` | Reload the add-in to pick up code changes |
| ✎ | `sys_request_selection` | Hand the pick to the USER: holds the call, and by default clears their selection |
| ⚠ | `sys_set_preferences` | SET one APPLICATION preference, by the path sys_get_preferences reports |

