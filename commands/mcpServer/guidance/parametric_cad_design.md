# Designing in Fusion

Choose constructions by intended behavior and verify their effects. Recipes are worked examples: follow their dependencies, allowing companion reads, intermediate calls and justified alternatives.

## Kernel - every design

**declare-acceptance-and-interfaces** - Write what the design must satisfy and each interface as a checkable number - seating faces, aligned axes, clearance, wall thickness when you take on a brief; not for a throwaway probe. Prove: `workspace_orient`: the active document, its units and what is already in it.

**sequence-is-the-design** - Treat a sample sequence as one option; choose references and feature order for the interfaces and edits they must preserve when choosing a construction; not for a one-feature part with no downstream dependency. Prove: `design_get`: the relevant feature expressions and health after a representative intended edit; `param_get`: with trace=true, parameter-expression dependents; geometric references need separate checks.

**encode-intended-changeability** - Share a dimension when values must track; keep independent decisions independent; name important drivers so later edits express intent when a value carries a decision; not for a fixed reference whose source and role are stated. Prove: `sketch_get`: the intended expressions and their evaluated dimensions.

**build-and-observe-in-milestones** - Treat a successful call or healthy feature as partial evidence; check the actual effect against intent with relevant measurements and a useful view when a milestone lands; not for an effect already independently checked at this milestone. Prove: `model_inspect`: bounds and volume of the changed body and relevant neighbors.

**compare-the-artifact-with-acceptance** - Compare the result with requirements and declared choices; distinguish what was created, computed, measured and tested from what remains unverified when the design looks finished; not for a disposable probe that makes no product claim. Prove: `view_screenshot`: a view supporting the measured interfaces and intended form.

## Plan

**name-parts-for-what-they-are** - A made part takes a functional name, a bought part its spec - 'SS 6003 2RS (10 X 17 X 35mm)', 'SHCS M8 X 65mm' - so the browser is the bill of materials when a part enters the tree; not for imported names. Prove: `design_get`: no 'Component1' and no 'Sketch1' left in the tree.

**variants-are-configurations** - Author them as configurations of one document driven by a few named parameters and a part-number property; check the active row before calling a failed compute a defect when the brief names several variants; not for a single variant. Prove: `design_get`: the configuration table, its columns and the active row; `model_inspect`: body bounds of the active variant against its intended size.
Example: the Configured Dumbbell: 14 rows varying weight_width, weight_length, weight_text and a Part Number.

**bought-parts-are-frozen** - Hold it as a base feature in its own component and re-cut only the interfaces on top of it with hole and chamfer features; never edit the frozen body when a purchased, imported or generative body enters the design; not for a body you are modelling yourself. Prove: `design_get`: the imported definition and later interface features, as construction diagnostics; `model_measure_between`: interface dimensions against their requirements; `model_inspect`: body bounds and volume against the expected interface modifications; these totals alone do not prove unchanged shape.

## Sketch

**construction-carries-symmetry-and-spacing** - Draw the construction line, then constrain: symmetry about it, midpoint on it, equal between the members; dimensions pin only what remains when a profile has symmetry, equal spacing or a family of equal features; not for a one-off reference sketch. Prove: `sketch_get`: the intended relations, evaluated dimensions and remaining freedom; test symmetry or spacing after a relevant edit.
Example: a knife layout: 43 constraints, 5 dimensions; a handle profile: ten symmetry constraints, six expressions.

**anchor-to-the-origin-by-relation** - Put the origin on a midpoint or at the crossing of two construction diagonals, never at a typed coordinate when a profile is placed; not for geometry projected from a body, which is already placed. Prove: `sketch_get`: a midpoint or coincident constraint naming the origin point.

**one-literal-per-wall** - Type it once and write the other dimensions as that dimension's name (d239) or a named parameter when the same size appears twice; not for two sizes that only happen to match today. Prove: `sketch_get`: dimension expressions referencing a name, not a repeated number.

**organic-outlines-are-control-point-splines** - Draw a control-point spline and make its ends smooth to construction lines whose angles and lengths are dimensioned; the control polygon, not the curve, carries the intent when an outline is a free curve; not for a one-off path nothing else references, where a fit-point spline is enough. Prove: `sketch_get`: a cv_spline with 'smooth' constraints to lines that carry angle dimensions.

**detail-on-projected-edges** - Project the wall's edges into the sketch and dimension the detail by offset from them; projected geometry has no freedom, so few constraints fully constrain the sketch when a clip, rib or pocket must follow an existing wall; not for detail on a plane no body touches. Prove: `sketch_get`: projected references, evaluated offset dimensions and remaining freedom; full constraint is a diagnostic; `model_measure_between`: the resulting detail offset from its supporting wall after a relevant edit.

**driven-dimensions-are-checks** - Add it as a driven dimension and read it back; a master sketch may stay not fully constrained only where its free entities are the splines when a derived length or angle matters to the brief; not for a sketch nobody will edit. Prove: `sketch_get`: dimensions with driving=false carrying the value the brief asked for.

### Recipes

#### One anchored, symmetric profile

Use when a planar profile whose halves must track; choose its component, sketch plane and intended symmetry first.

1. `sketch_create` - create the profile sketch on the chosen plane. Read back: the sketch identity and frame.
2. `sketch_add_geometry` - draw construction references and both outline halves with approximate placement. Read back: curve identities and closed regions where intended.
3. `sketch_constrain` - apply the required anchor, symmetry, tangency and equality relations. Read back: the accepted relations.
4. `sketch_dimension` - dimension independent sizes and reference shared values by expression. Read back: the dimension names and evaluated values.
5. `sketch_get` - inspect the solved profile. Read back: dimensions, expected profiles and any unexplained freedom.
6. `param_set` - change one driver within its intended range. Read back: sketch_get shows both halves following the intended relationship.
7. `param_set` - restore the driver. Read back: sketch_get confirms the baseline dimensions and healthy profile.

Bar - measure: the profile meets its dimensions and intended symmetry through the change and restore. Eyes: the profile has the intended silhouette and placement.
Exemplar: Configured Dumbbell (urn:adsk.wipprod:dm.lineage:0Unl7fg2Q2upJxRN-cdSfQ) - Handle/Sketch1 - 17 lines held by 10 symmetry constraints and 6 expressions such as length_handle / 2 + length_thread. Access: Autodesk Design Samples; needs hub access, read only

#### One tangent link profile

Use when a web joining bosses; first create a sketch with resolved pivot references and decide which dimensions must track.

1. `sketch_add_geometry` - draw bore and boss circles plus construction references. Read back: the curve identities.
2. `sketch_constrain` - anchor bore centers to the pivot references and make each boss concentric. Read back: the accepted relations.
3. `sketch_add_geometry` - draw web flanks and any closing arcs required by the chosen outline. Read back: the curve identities.
4. `sketch_constrain` - constrain intended tangencies and endpoint connections. Read back: the accepted relations.
5. `sketch_dimension` - dimension bores, bosses, spacing and required arc radii. Read back: the evaluated dimensions.
6. `sketch_get` - inspect the regions to be used by the feature. Read back: the intended closed regions, dimensions and remaining freedom.

Bar - measure: the selected regions form the intended web and bores at their required positions. Eyes: the outline connects the bosses without unintended gaps or material.
Exemplar: bike frame (urn:adsk.wipprod:dm.lineage:ghXi2gxeQWqAdfsv8o1MOA) - ROCKER/Sketch1 - three bores, eight tangent constraints, one R70 closing arc, four dimensions. Access: Autodesk Design Samples; needs hub access, read only

#### One controlled organic outline

Use when a free outline needing controlled end tangency; first create its sketch and decide which parts of the shape must be editable.

1. `sketch_add_geometry` - create a control-point spline with enough controls for the shape. Read back: the actual degree and control polygon identities.
2. `sketch_add_geometry` - create construction guides for the required end directions. Read back: the guide identities.
3. `sketch_constrain` - connect the guide endpoints to the curve and apply the supported smoothness relations. Read back: the accepted relations; investigate a refusal before dependent edits.
4. `sketch_dimension` - dimension the guides and independent control sizes. Read back: their evaluated values.
5. `sketch_dimension` - add a driven check where a derived dimension matters. Read back: the driven value.
6. `sketch_get` - inspect the outline and its constraints. Read back: the intended controls and any deliberate remaining freedom.

Bar - measure: dimensions and end directions meet the requirement; claim only the continuity actually measured. Eyes: the curve has the intended silhouette and no unintended kink.
Exemplar: Mouse ASM (urn:adsk.wipprod:dm.lineage:u9j3iHSpRTq4-_zqT1ukdw) - Mouse/Side Profile - a degree-5 spline G2-smooth to guides at 35, 40, 30 and 50 deg; Top Profile the same at degree 7. Access: Autodesk Design Samples; needs hub access, read only

## Model

**form-fillets-shell-then-detail** - Consider shaping and filleting the outer envelope before shelling, then adding interfaces; choose the order for the wall and edits you need when a moulded or cast part is built; not for geometry or dependencies better served by another order. Prove: `model_measure_between`: the wall and interface dimensions after creation and a relevant size change.

**carve-do-not-accrete** - Extrude the block, loft or extrude the cutting form, split the block by it and remove the waste - the kept piece carries clean faces when the form is a block with a curved face or a tapered body; not for a form that is itself one extrude or revolve. Prove: `model_inspect`: one body left with the volume you expect after the split.

**one-half-mirror-combine** - Use a mirrored half when both sides must track, combining only a single physical part; otherwise express symmetry through suitable sketch or feature relationships when the part is symmetric; not for features whose independent requirements merely produce a symmetric shape today. Prove: `model_measure_between`: corresponding dimensions and positions remain symmetric after an intended change.

**pattern-only-identical-intent** - Build one and pattern it; copies answering different requirements are modelled apart when the same feature repeats; not for copies that merely share a shape. Prove: `design_get`: the repeated feature's definition; `model_measure_between`: member dimensions and spacing after a relevant count or size change.

**let-the-process-shape-the-part** - Choose draft, walls, radii, holes and fit clearance from the intended process and interfaces; identify provisional values rather than borrowing sample dimensions when the part will be manufactured; not for an unsettled process, which is stated rather than assumed. Prove: `find_geometry`: the relevant face normals, radii and interfaces against the stated process requirements.

**threads-by-intent** - Create a tapped hole with model_hole(tap=...); thread an existing cylindrical face with model_thread. Request modeled=true when helical geometry is required; reserve custom helices for a nonstandard form or a demonstrated capability gap when a thread is needed; not for a thread represented only as an explicitly labelled envelope. Prove: `design_get`: the Hole or Thread definition, designation and modeled state; `model_measure_between`: mating dimensions of the claimed thread geometry.

**sheet-metal-by-intent** - Read sheet_get for rules and sheet state; use sheet_create_flange for a base or edge flange, or sheet_convert for an existing uniform solid. sheet_create_flat_pattern creates a native flat, not verified development; inspect sheet_get(include=['features']) and the design_export cutting contours before fabrication when the part is sheet metal; not for a reference envelope with no fabrication claim. Prove: `sheet_get`: the applied rule, sheet bodies and flat-pattern state; `model_inspect`: the formed part's intended envelope.

**components-when-the-count-is-known** - Stay in bodies until the part count settles, then promote each body to a named component before any joint when bodies are still being carved out of one another; not for a part known from the brief, which starts as its own component. Prove: `assembly_get`: named parts, their ownership and the intended joint relationships; `model_measure_between`: the intended interface positions after a relevant edit.

### Recipes

#### One moulded shell construction

Use when a shell whose outer envelope is conveniently built before its wall; prepare the dimensioned sketches and choose a pull direction.

1. `model_extrude` - build the initial envelope from the prepared profile. Read back: its dimensions and intended body.
2. `model_fillet` - apply envelope radii that should precede the wall. Read back: the radii and resulting shape.
3. `model_shell` - open the required face and form the wall. Read back: the intended opening and remaining body.
4. `model_measure_between` - measure representative wall locations. Read back: thickness matches the requirement.
5. `model_extrude` - add required bosses or ribs from prepared sketches. Read back: the intended connections and affected bodies.
6. `model_draft` - apply required draft with the chosen pull direction. Read back: the resulting face directions.
7. `model_hole` - create the required interface holes. Read back: their size, position and depth.
8. `view_section` - section a wall and boss. Read back: view_screenshot shows the material connections; dimensions come from the measurements.

Bar - measure: measured walls and interfaces meet the requirements; added bosses and ribs are accounted for. Eyes: the outside and section show the intended shell and connected details.
Exemplar: Basket - Part (urn:adsk.wipprod:dm.lineage:ph2BLdbPShaZLqEV3FMLRg) - rows 0-19: Extrude, Loft, Split, RemoveBody, Draft, Fillet x4, then Shell1; bosses, drafts and a second shell follow. Access: Autodesk Design Samples; needs hub access, read only

#### One imported body with added interfaces

Use when an imported part whose supplied form should remain a reference; choose its component, placement and permitted interface changes first.

1. `model_create_component` - create the receiving component. Read back: its identity and ownership.
2. `model_base_feature` - open a base feature for the import. Read back: the active scope.
3. `doc_insert_import` - import into that scope. Read back: the actual imported bodies.
4. `model_base_feature` - close the base feature. Read back: the feature state.
5. `model_move` - apply the chosen placement if needed. Read back: model_inspect shows the intended position and bounds.
6. `sketch_create` - create a sketch on the intended interface support. Read back: its identity and frame.
7. `sketch_add_geometry` - draw the required interface layout. Read back: the curve identities.
8. `sketch_dimension` - dimension the required spacing and sizes. Read back: the evaluated dimensions.
9. `model_hole` - create the specified holes. Read back: their actual placement, size and depth.
10. `model_chamfer` - apply specified interface chamfers. Read back: the affected edges and resulting dimensions.
11. `model_measure_between` - check the interfaces. Read back: the required spacing and seating relationships.

Bar - measure: the permitted changes meet the interface dimensions and unrelated supplied geometry is preserved. Eyes: the placed part retains its reference shape outside the intended edits.
Exemplar: Main Support Skeleton (urn:adsk.wipprod:dm.lineage:3QrFqp9VRYepLTttp3M1yg) - seven rows: BaseFeature1, Align1, DeleteFace2, Sketch1, Hole1, Sketch2, Hole2 on a generative outcome. Access: Autodesk Design Samples; needs hub access, read only

#### One family using configurations

Use when variants share a useful parametric definition and configurations are available; prepare the component and profile sketch first.

1. `param_add` - create independent drivers and derived relationships. Read back: the expressions evaluate.
2. `sketch_dimension` - bind the intended profile dimensions to those drivers. Read back: the evaluated dimensions.
3. `model_revolve` - create the revolved form from the prepared profile. Read back: the intended solid and dimensions.
4. `doc_save_as` - save into the agreed destination before configuring. Read back: the saved document identity.
5. `design_configure` - create the required table, columns and variant rows. Read back: the declared rows and their values.
6. `design_configure` - activate another variant. Read back: the active row.
7. `model_inspect` - inspect the active variant. Read back: body bounds; design_get with tree_bodies=true confirms solid state, and model_measure_between checks other dimensions.
8. `design_get` - inspect dependent feature health. Read back: the intended features remain healthy.
9. `design_configure` - restore the required handoff variant. Read back: the active row and independently checked dimensions.

Bar - measure: the selected variants meet their dimensions and shared interfaces; health alone is not dimensional proof. Eyes: the variants visibly express the intended differences; labels are included only if required.
Exemplar: Configured Dumbbell (urn:adsk.wipprod:dm.lineage:0Unl7fg2Q2upJxRN-cdSfQ) - 12 parameters, urethane_coating = weight_width / 10, weight_text driving the emboss, 14 configuration rows. Access: Autodesk Design Samples, read only

## Surface

**skin-first-solid-later** - Consider surfaces when their sections and boundaries express the form well; stitch or thicken at boundaries that support the intended edits when the outer form is the product; not for a solid or Form representation that better serves the same requirements. Prove: `design_get`: with tree_bodies=true, the selected body is_solid after relevant edits; `model_inspect`: body bounds against the intended dimensions.

**extend-before-trim** - Provide enough intersection for the intended trim and possible edits; extend only when the existing cutter does not provide it when one surface will trim another; not for a cutter that already overhangs. Prove: `model_inspect`: the retained body's bounds against the intended extent; `find_geometry`: retained face and edge locations; preservation beyond these observations remains unverified; `view_screenshot`: the retained region against the intended boundary.

**blend-by-split-and-loft** - Consider split-and-loft or a radius-controlled fillet; choose the construction for the required continuity and shape controls when two skins must meet with a smooth transition; not for a transition with no smoothness requirement. Prove: `model_measure_continuity`: gap, normal angle and curvature jump sampled along the seam against the required continuity.

**master-skin-derived-into-parts** - Consider a shared master skin when several parts must follow the same form; choose same-document or derived ownership for the intended reuse and revision process when several parts share one outer form; not for independently designed forms that merely touch. Prove: `model_measure_between`: the mating surfaces still agree after a shared-form change and update.

**peel-a-solid-to-a-skin** - Delete the faces you do not want; the remaining skin is the surface to build on when the quickest form is a solid but only some faces are wanted; not for a solid you will keep whole. Prove: `design_get`: the tree's body row reads is_solid false after the delete.

### Recipes

#### One bottle skin assembled from surfaces

Use when a changing-section container; prepare compatible body/neck profiles, rails, a crown profile and any required closure surfaces.

1. `model_loft` - loft the body skin from the prepared sections and rails with as_surface=true. Read back: the surface body and its intended boundaries.
2. `surface_revolve` - form the crown from its prepared profile and axis. Read back: the crown surface.
3. `surface_extend` - extend the cutter only if the intended intersection needs it. Read back: the resulting reach.
4. `surface_trim` - trim to the intended meeting boundary. Read back: the retained regions.
5. `model_stitch` - stitch enclosing surfaces within the permitted joining error. Read back: whether it closed and the free edges left; resolve missing boundaries before shelling.
6. `model_measure_continuity` - measure any seam whose continuity is required. Read back: sampled gap, normal angle and curvature jump against that requirement.
7. `model_shell` - form the required wall and mouth opening. Read back: the resulting body and opening.
8. `model_measure_between` - check wall and mouth interfaces. Read back: the dimensions against the requirement.
9. `view_screenshot` - inspect the form. Read back: the intended silhouette and visible transitions.

Bar - measure: the enclosing body and wall meet the chosen dimensions; claim continuity only where model_measure_continuity has measured the seam. Eyes: the skin and crown meet without an unintended visible break.
Exemplar: Bottle (urn:adsk.wipprod:dm.lineage:NX9msEStSlaONb6W4KI4ZA) - Sweep1 with a rail, Top_Crown on projected edges, Extend 5 mm before Trim, Stitch 0.10 mm, chord fillets, OffsetFaces -0.05 mm. Access: Autodesk Design Samples, read only

#### One shared skin derived into parts

Use when separate part documents must follow one master skin; prepare the master's sections/rails and each part's closing boundaries.

1. `model_loft` - create the master skin from the prepared references with as_surface=true. Read back: the intended surface body.
2. `model_mirror` - mirror a half skin when this construction uses symmetry. Read back: the matching skin geometry.
3. `model_stitch` - join the required skin pieces. Read back: the intended body and open boundaries.
4. `doc_save_as` - save the master in the agreed destination. Read back: the source document identity.
5. `doc_insert_derive` - derive the skin into each prepared part document. Read back: the body and source identity.
6. `surface_extrude` - create a closing surface from the prepared boundary. Read back: the surface intersects the intended skin region.
7. `surface_fill` - keep the intended enclosed cell. Read back: the resulting solid.
8. `model_shell` - form the required wall. Read back: the wall and openings.
9. `model_measure_between` - measure mating interfaces. Read back: the intended fit; revise only where its specified clearance requires it.

Bar - measure: parts meet their wall and interface requirements; verify shared-form changes if that dependency is claimed. Eyes: the parts assemble into the intended form with the specified interface gaps.
Exemplar: Mouse ASM (urn:adsk.wipprod:dm.lineage:u9j3iHSpRTq4-_zqT1ukdw) - the Mouse master's five named profiles; Base, Middle and Top each open with Context1 (derive) and BoundaryFill1. Access: Autodesk Design Samples, read only

## Assemble

**one-assembly-idiom** - Choose relations for its actual freedoms and reference path; avoid duplicate constraints, while allowing independently organized subassemblies to use different constructions when defining relationships within a mechanism; not for a placement study that makes no kinematic claim. Prove: `assembly_get`: the intended freedoms, health and component poses rather than a preferred joint count.

**connected-reference-path** - Establish one intentional reference path from the grounded part; do not ground parts to hide missing joints when an assembly has a fixed moving mechanism; not for floating or multiple independent mechanisms. Prove: `assembly_get`: one ground_to_parent root and every joint reachable from it.

**as-built-for-parts-modelled-in-place** - Consider as-built joints to retain a deliberate placement; choose geometric joint references where they better express how interfaces must follow edits when a part was modelled against its neighbours where it sits; not for a static placement with no required joint relationship. Prove: `assembly_get`: the intended relative pose and motion limits; `model_measure_between`: mating dimensions after relevant edits.

**align-knobs-not-spacers** - Use the joint's align angle and align offset; do not add spacer bodies to fix a pose when a joint needs a flip or an offset; not for a real spacer part in the bill of materials. Prove: `assembly_get`: the joint's frame sits where the offset put it, and the occurrence list holds no spacer that is not a real part.

**exercise-the-mechanism** - Drive it to home and a representative extreme; keep moving joints few, the rest rigid; link two joints with a motion link when one motion implies the other when the mechanism has a driven joint; not for a joint with no travel of interest. Prove: `joint_drive`: the value at each pose; `assembly_inspect_interference`: overlaps at each pose, intended fit or defect.
Example: a nut overlapping a plain shaft is a thread modelled as a cylinder.

**fasteners-mint-parameters** - Expect a set of adsk_ parameters per fastener and read only the authored set; name each fastener instance by its spec when library fasteners are inserted; not for a design with no library parts. Prove: `param_get`: the authored user parameters are what comes back and generated_skipped counts the adsk_ ones the fasteners minted; include_generated=true lists those.

### Recipes

#### One in-place part with an as-built joint

Use when a part is designed in its intended assembled pose; prepare its component/sketch and identify the actual members and required freedoms.

1. `sketch_project` - project the relevant interface geometry into the prepared sketch. Read back: the intended references and links.
2. `sketch_add_geometry` - draw the chosen profile around those interfaces. Read back: the intended regions.
3. `sketch_constrain` - apply the required interface and shape relations. Read back: the accepted relations.
4. `sketch_dimension` - dimension the independent sizes. Read back: the solved dimensions.
5. `model_extrude` - create the part at its intended thickness. Read back: the body and affected scope.
6. `joint_create_as_built` - join the actual member pair with the intended freedom, without redundant bearing joints. Read back: the joint type and retained pose.
7. `joint_edit` - set the required travel limits. Read back: the limits.
8. `joint_drive` - exercise a representative pose. Read back: assembly_get shows the intended component motion.
9. `assembly_inspect_interference` - inspect that pose. Read back: overlaps classified against intended fits.
10. `joint_drive` - restore the handoff pose. Read back: assembly_get shows the restored position.

Bar - measure: the member has its intended motion and interfaces at the tested poses; untested travel remains unverified. Eyes: the part engages its interfaces and moves as intended.
Exemplar: bike frame (urn:adsk.wipprod:dm.lineage:ghXi2gxeQWqAdfsv8o1MOA) - rows 111-124: ROCKER sketched between bearings, three as-built joints, extrude, fillet, mirror, holes, a fourth as-built joint. Access: Autodesk Design Samples; needs hub access, read only

#### Coupled rotation and travel on separate members

Use when distinct rotating and translating members need an ideal pitch relationship; this does not model one cap both turning and advancing.

1. `assembly_get` - identify the reference member, moving members and existing freedoms. Read back: distinct members with the intended placements.
2. `assembly_ground` - anchor the chosen reference if the mechanism requires it. Read back: isGroundToParent confirms the chosen reference is anchored to its parent.
3. `joint_create_as_built` - give the rotating member its required revolute relationship. Read back: the joint type and retained pose.
4. `joint_create_as_built` - give the translating member its required slider relationship. Read back: the joint type and retained pose.
5. `joint_motion_link` - couple the two using the intended pitch and the tool's stated ratio units. Read back: the actual link and ratio; assembly_get records both starting joint values and member poses.
6. `joint_drive` - change the rotating joint from its recorded starting angle within the intended travel. Read back: assembly_get reports both member poses and the travel change.
7. `joint_drive` - drive that same joint back to its starting angle. Read back: assembly_get confirms both members restored.

Bar - measure: measured rotation and translation match the declared pitch; the ideal motion link does not prove a physical drive train. Eyes: each actual member moves as specified without substituting one member for another.

## Validate

**close-the-declared-interfaces** - Measure each and report the number - contact where parts engage, clearance where they move when the declared interfaces are built; not for an interface the brief left open. Prove: `model_measure_between`: the distance or angle at each interface.

**grade-structure-not-counts** - Read plane normals, axis directions and containment, then look: a flat stack passes every count while nothing nests, and a brick passes every measurement while looking nothing like the product when counts and volumes look right; not for a genuinely planar design. Prove: `find_geometry`: face normals and linear-edge directions; `view_screenshot`: the silhouette reads as the object.

**measurements-test-the-brief** - Report the disagreement - a measurement is evidence about the artifact; intent comes from the brief when a measurement disagrees with the brief; not for a brief quoting a measured fact about existing hardware. Prove: `model_measure_between`: the measured value beside the brief's.

## Finish

**verify-the-write** (safety invariant) - Confirm the effect through a read other than the tool's claim; read a refusal's reason before retrying when a write reports success; not for a deferred write, confirmed through the poller it names. Prove: `design_get`: the affected design identity and state; `model_inspect`: the changed body's bounds and volume against the expected modelling effect.

**leave-the-artifact-openable** - Leave the saved state valid, name the sketches and components, look at the result, and say what you could not do when the work is handed on; not for a scratch document. Prove: `doc_get`: the document's save state.

## Manufacture

**rig-is-part-of-the-job** - Hold the fixture as its own components beside the part, select only the part body as the model, and take the work coordinate system from the stock; the fixture is geometry the toolpaths must avoid, not decoration when a setup is created; not for a setup sheet exercise with no fixture. Prove: `cam_get`: selected_models names the part only and the wcs origin_mode is stated.

**steep-and-shallow-are-two-strategies** - Parallel skips steep areas by default and 3D contour skips shallow ones; machineSteepAreas and machineShallowAreas extend their coverage; consider scallop for both, choosing its stepover for the tool and required finish when finishing a 3D form; not for a flat part, where face and 2D contour suffice. Prove: `cam_compare_operations`: the machineSteepAreas or machineShallowAreas difference in the pair; `cam_get`: the coverage controls and tool carried by each operation; `cam_show_toolpath`: the intended operation is shown in isolation; `view_screenshot`: visible passes on the intended regions.
Example: a stepover of a tenth of the tool is a sample setting, not a universal finish requirement.

**pocket-or-adaptive** - Adaptive takes deep stepdowns at a light radial load and needs no leads or compensation; 2D pocket takes shallow stepdowns with a finishing pass and cutter compensation - pick adaptive for bulk removal, pocket when the wall finish comes from the same operation when roughing a pocket; not for a slot, which wants the slot strategy on a closed slot contour. Prove: `cam_compare_operations`: optimalLoad and maximumStepdown on adaptive; finishing passes and compensation on pocket; `cam_get`: the geometry selections carried by each operation.

**geometry-selection-is-half-the-operation** - Compare their geometry selections - chains, extension modes, stock contours, boundaries - because a parameter diff cannot see them when two operations read as identical; not for operations that differ in parameters already. Prove: `cam_get`: each operation's references: the chains and faces it was given.

**turning-lead-out-gouges-the-remaining-stock** - Inspect the exit move and the stock the cycle leaves; turn the lead-out off, or leave allowance where a later pass removes it; regenerate and assess the result when a turning profile finishing cycle reports 'Lead-Out has been modified due to a gouge with the remaining stock'; not for a cycle whose exit move has to clear a face, where the lead-out is the point. Prove: `cam_get_status`: the warning after the change and whether the result is empty; `cam_show_toolpath`: the intended operation is shown in isolation; `view_screenshot`: the exit path against the part and displayed stock.
Example: measured on a turned flange: doLeadOut false, or useStockToLeave true with xStockToLeave and zStockToLeave at 0.5 mm, each cleared this warning.

**rest-stock-is-what-the-setup-before-left** - MEASURED on a turned flange, one whole-model adaptive with its parameters untouched: it generated EMPTY on that setup under previous_setup stock in both the 'rest' and 'setupStockSilhouette' modes, and the same operation cut 347 s the moment the setup alone was switched to a relative box. These stock extents keep the relative-box numbers and describe nothing this setup cuts, so size a clearing strategy from the preceding setup's own operations, not from these extents. An operation's OWN rest is a separate knob: defineStockBy 'rest' reads restMaterialSource 'previousOperations' - the operations before it in THIS setup, not the setup's stock mode - and with every sibling valid it computes, no 'Failed to generate rest material.' among the warnings when a milling setup takes stock_mode 'previous_setup' after a turning setup; not for the first setup of a job, whose stock is the billet. Prove: `cam_get`: the setup row reads stock_mode 'previous_setup' and stock_extents_describe says the box is not the stock; `cam_get_status`: whether the clearing operation is named in empty_toolpaths - the list reports membership, never why.

### Recipes

#### Choosing a strategy for a feature

Use when a prepared setup and tool library need a cutting operation for a known feature; choose from available strategies.

1. `cam_get` - read available strategies and setup context. Read back: the allowed candidates, model, stock and frame.
2. `find_geometry` - inspect the intended feature and access. Read back: its dimensions, geometry and directions.
3. `cam_create_operation` - create a candidate with a suitable tool. Read back: the operation and tool it carries.
4. `cam_select_geometry` - select the intended feature and boundary. Read back: the resolved selection.
5. `cam_generate` - generate the candidate. Read back: the handle; poll cam_get_status to completion and inspect errors.
6. `cam_inspect_toolpaths` - inspect validity and emptiness. Read back: the observed state; an empty result does not diagnose its cause.
7. `cam_get` - read warnings, heights and the time slice. Read back: the height settings and motion estimates.
8. `cam_show_toolpath` - show the candidate in isolation. Read back: view_screenshot supports coverage of the intended feature.
9. `cam_compare_operations` - compare a separately prepared alternative when the trade-off remains unclear. Read back: setting differences, with selection and coverage checked separately.

Bar - measure: the operation computes and evidence supports intended coverage; unexplained emptiness or warnings remain findings. Eyes: passes reach the intended feature with the planned entry and clearance.
Exemplar: 2D - Overview of toolpaths (urn:adsk.wipprod:dm.lineage:VJJsAJVXQmiDOFFl6-xErw) - 22 operations named for their variant, '2D Contour2' beside its multiple-passes, Trimmed and Rest siblings. Access: Autodesk Design Samples; needs hub access, read only

#### Checking a generated cutting operation

Use when a cutting operation expected to remove stock needs review before a demonstration post; machine release requires its own process checks.

1. `cam_get` - read the operation, tool, selections, heights and stock source. Read back: the actual settings and any freshness limits.
2. `cam_inspect_toolpaths` - read state and emptiness. Read back: the operation's computed state and whether it has a path.
3. `cam_get` - read warnings and motion estimates. Read back: time and distances; nonzero time alone does not prove stock removal.
4. `cam_show_toolpath` - show the operation alone. Read back: the visibility selection.
5. `view_screenshot` - inspect it against the feature, stock and fixture. Read back: visible coverage and clearance; unseen collisions remain unverified.
6. `cam_post` - post to the agreed output destination with the selected post. Read back: the reported file path and size, or refusal.
7. `cam_get` - re-read operation and program state. Read back: the delivered scope and any outstanding warning or stale state.

Bar - measure: report computation, coverage evidence and output delivery separately; a nonempty file is not proof of controller suitability. Eyes: the isolated path agrees with measured feature positions and heights; disclose what the view cannot establish.

#### Choosing a cross-hole approach

Use when a known hole crosses a turned axis; decide through/blind intent, entry side, access and required depth before selecting a setup.

1. `find_geometry` - inspect the hole and available entry geometry. Read back: the axis, position and relevant dimensions.
2. `cam_get` - inspect the available setup frames. Read back: whether an existing frame supports the intended approach.
3. `cam_create_setup` - create a dedicated setup only if the required approach needs one. Read back: the intended model and setup identity.
4. `cam_edit_setup` - bind the selected setup's orientation for that approach. Read back: the bindings and available frame values.
5. `cam_create_operation` - create a drilling cycle with the appropriate tool. Read back: the operation and tool.
6. `cam_select_geometry` - select the intended hole faces. Read back: the resolved faces.
7. `cam_edit_operation` - set the required heights and drilling depth. Read back: the actual height and depth settings.
8. `cam_generate` - generate and poll cam_get_status. Read back: the actual completion state and warnings; change orientation only if the evidence requires it.
9. `cam_show_toolpath` - show the operation in isolation. Read back: view_screenshot shows entry and depth against the measured hole.

Bar - measure: the generated approach and depth agree with the intended hole; through and blind cases have different acceptance. Eyes: the drill enters from the chosen side and reaches the specified depth.
