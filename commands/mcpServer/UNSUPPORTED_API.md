# Fusion API members in use that Autodesk marks "not officially supported"

Some tools of this server stand on Fusion API members whose documentation carries the sentence
"This ... is not officially supported and its behavior may change." The installed API names no
supported alternative for any of them, so these tools keep them. This page lists every such use, so
a contributor or the maintainer of a connected agent knows which tools could change under a Fusion
update.

- The sentence is word for word the same on every such member and class. It says nothing about why
  a member is marked or how likely it is to change.
- No new use of a member marked unsupported, preview or retired goes in without the owner's word.
- A member marked retired is a different case: it has a replacement and is replaced, not listed here.
- The marks are read from the installed binding by `tests/api_inventory.py`. A scan by member name is
  only a lead list: a name is marked on one class and plain on many others, so each use is confirmed
  by reading which class the code holds. A mark can also sit on a whole class, or on a base class,
  with the members themselves unmarked.

## The uses

| Tool | Member or class | What the tool would lose without it |
|---|---|---|
| `mesh_plane_cut` | `Features.meshPlaneCutFeatures`, and the classes `MeshPlaneCutFeatures`, `MeshPlaneCutFeatureInput`, `MeshPlaneCutFeature` with the enums `MeshPlaneCutTypes` and `MeshPlaneCutFillTypes` (each marked as a whole) | The whole tool: cutting a mesh body with a plane |
| `drawing_get`, `drawing_edit_sheet`, and every drawing tool given a sheet name (`drawing_add_sketch`, `drawing_add_symbol`, `drawing_dimension`, `drawing_edit_revisions`, `drawing_delete_sketch`) | `Drawing.sheets` | Listing the sheets of a drawing, resolving a sheet by name, adding, copying and deleting a sheet |
| `drawing_get`, `drawing_edit_sheet`, `drawing_add_sketch` | `CustomTables.count`, `CustomTables.item` (the class itself is marked preview) | Reading the custom tables on a sheet and counting them in a sheet's facts |
| `cam_get` with `include=['inspection']` | `CAM.inspectionResults`, and the classes `CAMInspectionResults`, `CAMMeasure`, `InspectionPathResults`, `InspectionPathResult`, `InspectionPointResults`, `InspectionPointResult` with the enum `InspectionPointState` (each marked as a whole) | Reading probing and inspection results |
| `cam_get` (setups and operations) | `OperationBase.messageLog` | The reason an operation is invalid or carries a warning |
| `cam_select_geometry`, `cam_compare_operations` | `CurveSelection.outputGeometry` | Reading back which geometry a curve selection resolved to, and comparing it between operations |
| every walk of the CAM tree (`cam_get`, `cam_reorder` and the other CAM tools) | `CAMAdditiveContainer.children` | Seeing what an additive container holds |
| `cam_post` with a local post file | `PostConfiguration.createFromContent` | Posting with a post processor given as a file |
| `cam_create_machine` | `Machine.createFromTemplate` | Creating a machine from a template. `Machine.create` is an unmarked sibling and has not been measured as a replacement |
| `design_export` | `ExportOptions.isIncludingInvisibleBodies`, `ExportOptions.isIncludingInvisibleComponents` (the mark sits on the base class) | The two options that include hidden bodies and hidden components in an export |
| `sketch_constrain` with automatic constraining | `AutoConstrainInput.dimensionStrategy`, `interLoopDimensionStrategy`, `symmetricDimensionStrategy`, `linearDiameterDimensionPreference` | The four choices of how automatic dimensions are laid out |

## Keeping this page true

When a tool starts or stops using a marked member, change the row in the same commit. After a Fusion
update, read the marks again with `tests/api_inventory.py` and check each row against the code: a
member can lose its mark, gain a supported sibling, or disappear.
