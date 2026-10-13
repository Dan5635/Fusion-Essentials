# Fusion API members in use that Autodesk marks "not officially supported"

Some tools of this server stand on Fusion API members whose documentation carries the sentence
"This ... is not officially supported and its behavior may change." No documented direct
replacement was identified for these uses in the installed API. That does not establish that no
supported composition can do the same job. This page lists every such use, so
a contributor or the maintainer of a connected agent knows which tools could change under a Fusion
update. Its second table lists the uses of members marked preview, and its third the members marked
retired that the code still calls.

- The sentence is word for word the same on every such member and class. It says nothing about why
  a member is marked or how likely it is to change.
- No new use of a member marked unsupported, preview or retired goes in without the owner's word.
- A member or class marked preview carries the sentence "This ... is a preview feature and may
  change in future releases. Do not use it in distributed programs." That is Autodesk's warning.
  The owner permits the existing uses listed here, including uses outside drawing; a new use
  still requires the owner's word. This page records use and does not grant permission.
- A member marked retired is a different case: it has a replacement and is replaced. The ones the
  code still calls are in the third table until they are gone. One that stays because its
  replacement was measured not to do the job carries a comment at its point of use saying a
  supported way is sought.
- The marks are read from the installed binding by `tests/api_inventory.py`. A scan by member name is
  only a lead list: a name is marked on one class and plain on many others, so each use is confirmed
  by reading which class the code holds. A mark can also sit on a whole class, or on a base class,
  with the members themselves unmarked.

## Unsupported members and classes in use

| Tool | Member or class | What the tool would lose without it |
|---|---|---|
| `mesh_plane_cut` | `Features.meshPlaneCutFeatures`, and the classes `MeshPlaneCutFeatures`, `MeshPlaneCutFeatureInput`, `MeshPlaneCutFeature` with the enums `MeshPlaneCutTypes` and `MeshPlaneCutFillTypes` (each marked as a whole; `MeshPlaneCutFeature` also inherits the preview mark from its base class `MeshFeature`) | The whole tool: cutting a mesh body with a plane |
| `drawing_get`, `drawing_edit_sheet`, and every drawing tool given a sheet name (`drawing_add_sketch`, `drawing_add_symbol`, `drawing_dimension`, `drawing_edit_revisions`, `drawing_delete_sketch`) | `Drawing.sheets` | Listing the sheets of a drawing, resolving a sheet by name, adding, copying and deleting a sheet |
| `drawing_get`, `drawing_edit_sheet`, `drawing_add_sketch` | `CustomTables.count`, `CustomTables.item` (the class itself is marked preview) | Reading the custom tables on a sheet and counting them in a sheet's facts |
| `cam_get` with `include=['inspection']` | `CAM.inspectionResults`, and the classes `CAMInspectionResults`, `CAMMeasure`, `InspectionPathResults`, `InspectionPathResult`, `InspectionPointResults`, `InspectionPointResult` with the enum `InspectionPointState` (each marked as a whole) | Reading probing and inspection results |
| `cam_get` (setups and operations) | `OperationBase.messageLog` | Invalidation reasons and parameter or machine deltas. Ordinary warning and error strings come from separate properties |
| `cam_select_geometry`, `cam_compare_operations` | `CurveSelection.outputGeometry` | Reading back which geometry a curve selection resolved to, and comparing it between operations |
| every walk of the CAM tree (`cam_get`, `cam_reorder` and the other CAM tools) | `CAMAdditiveContainer.children` | Seeing what an additive container holds |
| `cam_post` with a local post file | `PostConfiguration.createFromContent` | Posting with a post processor given as a file |
| `cam_create_machine` | `Machine.createFromTemplate` | Creating a machine from a template. `Machine.create` is an unmarked sibling and has not been measured as a replacement |
| `design_export` | `ExportOptions.isIncludingInvisibleBodies`, `ExportOptions.isIncludingInvisibleComponents` (the mark sits on the base class) | The two options that include hidden bodies and hidden components in an export |
| `sketch_constrain` with automatic constraining | `AutoConstrainInput.dimensionStrategy`, `interLoopDimensionStrategy`, `symmetricDimensionStrategy`, `linearDiameterDimensionPreference` | The four choices of how automatic dimensions are laid out |

## Preview members and classes in use

In the drawing family:

| Tool | Member or class | What the tool would lose without it |
|---|---|---|
| `drawing_create`, `drawing_get`, `drawing_edit_sheet`, `drawing_add_sketch`, `drawing_delete_sketch`, `drawing_add_symbol`, `drawing_dimension`, `drawing_edit_revisions`, `drawing_insert_image`, `drawing_export` (DWG and DXF) | Most of `adsk.drawing` is marked preview as whole classes, 145 of its 162: `Sheet`, `Sheets`, `View`, `ViewCurve`, `DrawingSketch`, `DrawingDimensions`, `DrawingSymbols`, `RevisionTable`, `CustomTable`, `Images`, `DrawingManager`, `CreateDrawingInput`, the symbol, table and image inputs and the enums beside them. The members `Drawing.activeSheet`, `Drawing.documentSettings`, `DrawingExportManager.createDWGExportOptions` and `createDXFExportOptions` carry the mark themselves | Drawing authoring and sheet, view, annotation, table and image reads; DWG and DXF export. PDF export uses unmarked export APIs. `drawing_update` uses the unmarked document and reference APIs; `drawing_get_status` reads the durable job store without acquiring a Fusion object |

Outside the drawing family:

| Tool | Member or class | What the tool would lose without it |
|---|---|---|
| `mesh_combine`, `mesh_delete` in a parametric design, `mesh_generate_face_groups`, `mesh_reduce`, `mesh_remesh`, `mesh_repair`, `mesh_reverse_normal`, `mesh_separate`, `mesh_shell`, `mesh_smooth`, `mesh_to_brep` | The collection each tool creates its feature through: `Features.meshCombineFeatures`, `meshRemoveFeatures`, `meshGenerateFaceGroupsFeatures`, `meshReduceFeatures`, `meshRemeshFeatures`, `meshRepairFeatures`, `meshReverseNormalFeatures`, `meshSeparateFeatures`, `meshShellFeatures`, `meshSmoothFeatures`, `meshConvertFeatures`, and the collection, input, feature and enum classes behind each (each marked as a whole) | Each of these tools as a whole |
| `sheet_create_flange` | `FlangeFeatures.createEdgeFlangeInput`, `FlangeFeatures.createBaseFlangeInput`, `FlangeFeatures.add`, and the classes `EdgeFlangeInput`, `BaseFlangeInput`, `FlangeFeature`, `EdgeFlangeFeatureDefinition`, `BaseFlangeFeatureDefinition` with the enums `FlangeHeightDatumTypes` and `FlangeOrientations` | The whole tool |
| `sheet_create_fold` | `Features.foldFeatures`, and the classes `FoldFeatures`, `FoldFeatureInput`, `FoldFeature`, `FoldBendLineDefinitions`, `FoldBendLineDefinition` with the enum `FoldBendLinePositionTypes` | The whole tool |
| `sheet_create_join_by_bend` | `Features.joinByBendFeatures`, and the classes `JoinByBendFeatures`, `JoinByBendFeatureInput`, `JoinByBendFeature`, `BendRadiusOverride` | The whole tool |
| `sheet_create_unfold` | `UnfoldFeatures.createInput`, `UnfoldFeatures.add`, the class `UnfoldFeatureInput`, and `UnfoldFeature.nativeObject` when the shared identity preflight examines an existing unfold | The whole tool |
| `sheet_create_refold` | `RefoldFeatures.createInput`, `RefoldFeatures.add`, the class `RefoldFeatureInput`, and `UnfoldFeature.stationaryFace` and `nativeObject` when resolving the source unfold | The whole tool |
| `sheet_convert` | `BRepBody.findThicknessAtFace`, `BRepBody.convertToSheetMetal` | The whole tool |
| `sheet_get` | `Features.foldFeatures`, `Features.joinByBendFeatures` | The fold and join counts |
| `pmi_create`, `pmi_edit`, `pmi_get`, `pmi_delete` | `BaseComponent.pmiAnnotations`, and every `PMI...` class with the enum `LeaderLineNotePlaneTypes` (each marked as a whole) | Each of these tools as a whole |
| `model_arrange` | `Features.arrangeFeatures` | The whole tool |
| `model_create_component` | The enum `DesignIntentTypes`, read and written through `Design.designIntent` | Promoting a part-intent design so that it accepts a component |
| `design_configure` | `DataFile.configurationTable`, `DataFile.isConfiguredDesign` | Reading a configured part's rows for an insert column |
| `doc_open` | `DataFile.isConfiguredDesign` | The `is_configured_design` flag in the reply |
| `design_export` writing a sketch to DXF | `ExportManager.createDXFSketchExportOptions` | Exporting a sketch as DXF |
| `cam_select_geometry` with `stock_faces` | `CadStockProbeParameterValue.stockFaceNames` (the class is marked) | Naming the stock faces of a probing operation |

## Retired members the code still calls

| Tool | Retired member | Replacement the API names |
|---|---|---|
| `model_thread` with `left_handed=true` | `ThreadFeatureInput.isRightHanded` | `ThreadInfo.create` accepts the hand, but its left-hand request was measured producing a right-hand thread. The input setter remains for left-hand creation only; the resulting feature's hand is read back. A supported left-hand route is still sought |

Thread data and info factories use `ThreadDataQuery.create` and `ThreadInfo.create`.
Chamfers use `createInput2`, `chamferEdgeSets` and the resulting `edgeSets`; cameras use
`getExtents` and `setExtents` or their perspective eye-distance route. Multi-line sketch text
uses its landed `MultiLineTextDefinition.rotate`; path text refuses a nonzero rotation and
offers `sketch_move` on the path before creating the text. These routes replace the retired calls.

## Keeping this page true

When a tool starts or stops using a marked member, change the row in the same commit. After a Fusion
update, read the marks again with `tests/api_inventory.py` and check each row against the code: a
member can lose its mark, gain a supported sibling, or disappear. The API explorer
(`.agents/roles/api-explorer.md`) reviews and updates this page in every audit, and can be briefed
to do only that.
