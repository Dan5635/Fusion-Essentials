# Tests

Tests for the MCP tools in `commands/mcpServer/tools/`. They run **outside
Fusion** against a mocked `adsk` layer, so the whole suite finishes in seconds
and needs no live Fusion session.

The tree splits by what a test does:

- `tests/unit/` - tests that exercise behavior (per-tool handlers, the shared framework, the server).
- `tests/lints/` - tests that read the codebase to enforce a convention (naming, wire ASCII, dead
  code, doc freshness, ...). These are the repo policing itself.
- `tests/live/` - Fusion-driven scripts (`tool_verify.py`, `measure_api.py`, the cold-agent
  evals). Run them on demand with a real Fusion session; the mock suite does not collect them.
- `tests/fakes/` - the shared Fusion fakes, one module per family; `conftest.py` re-exports them.
- `tests/` root - the shared harness: `conftest.py` and the `gen_*.py` generators.

```bash
py -3 tests/check_all.py                     # run before calling a change done: generator checks + suite + live gate
py -3 tests/check_all.py --offline           # no Fusion here (skips the live gate, visibly)
py -3 -m pytest tests/unit/test_sys_get_selection.py -v   # one tool, verbose (while iterating)
py -3 tests/gen_all.py                       # regenerate the docs under tests/generated/
```

`check_all.py` runs everything in dependency order and, when a stage fails, prints the command that
repairs it. `py -3 tests/check_all.py --help` lists every stage.

`py -3` is the Windows Python launcher. On macOS or Linux type `python3` in its place; the rest of
each command is the same. Those two platforms are untested (see
[CONTRIBUTING.md](../CONTRIBUTING.md), "Contributor setup and verification").

## Agent checkout operations

Build in an isolated worktree, run Git and pytest from inside it, and give each search a path
inside that tree. An unscoped shell search can walk the shared checkout and its nested worktrees.
Keep `plans/` and handoffs under the main checkout's private directories; they are absent from a
worktree. Scope scratch files to your assigned output directory.

A file edit must preserve exact bytes outside the intended change, LF line endings, and no BOM.
Use the runner's file-editing tool or a short exact-text replacement that asserts one match;
never shell redirection, Set-Content, Out-File or sed -i into a repo file. Windows PowerShell 5.1
can add UTF-8 BOMs and CRLF, which break the generators; a BOM breaks `gen_wiring.py` across
the repository. Check the changed paths with
`git ls-files --eol <paths>` and check for a BOM before reporting.

The required lint-list commands are `py -3 -m pytest tests/lints -q` before the first edit and
after the last. Run touched units with `py -3 -m pytest tests/unit/<touched> -q`; a reviewer also
runs affected consumers when a shared helper or fake changes. The lead owns the full acceptance
commands and regeneration; everyone may run `py -3 tests/gen_all.py --check`. Attribute baseline
failures rather than silently regenerating another lane's documents.

When running against a tree you do not own, set `PYTHONDONTWRITEBYTECODE=1` and pass
`-p no:cacheprovider`, leaving no files behind. Full-suite and coverage runs collide across
concurrent agents; targeted pytest is the development route.

Mark a new private-tree file intent-to-add with `git add -N <path>` so it appears in the patch
without staging content. Export with `git diff --binary --output=<file> HEAD`; use the equals
sign, because the spaced form can leave an empty file. Keep earlier patch versions on disk and
compute SHA256 from the posted bytes.

Check an outputs-only sweep hunk in a throwaway tree before exporting your source patch. Report
the compilation check; do not change a reserved shared act in the main checkout.

A persistent fixture requires explicit admission, a name identifying it as a test leftover, and
a handoff giving its name and location. A probe needing a saved cloud source creates exactly one
file named `TestDetritus-<row>.<timestamp>` in the configured test project's sweep folder, reports
its name and lineage, and does not delete, switch hubs or walk a project.

## Running the sweep on your machine

The live sweep requires one explicit machine configuration before it makes any server call.
Copy [sweep_config.example.json](live/sweep_config.example.json) to
`tests/live/sweep_config.local.json` and fill in every key. The example excludes every optional
tier and persistent-write permission; it is not a full-acceptance configuration.

| Key | Meaning |
|---|---|
| `machine` | A portable 1-to-40-character record-folder label: letters, digits, dots, dashes or underscores; no trailing dot or reserved Windows name. |
| `port` | The add-in's configured loopback port, an integer from 1024 through 49151. This does not change the add-in's `mcp_port`. |
| `tiers.native_script` | Admit native-script rows. The setting `Allow AI scripts (unsafe)` must already expose `sys_execute_script`. |
| `tiers.machining_extension` | Request machining-extension rows; an unavailable or unread entitlement stops admission. |
| `tiers.cloud` | Request cloud rows in the configured destination. |
| `cloud.hub`, `cloud.project`, `cloud.folder` | The existing hub name, project name and operator folder path. All three must be nonblank when cloud is on; they may be empty when it is off. |
| `allow.library_writes` | Admit writes to shared tool, machine and template libraries; document-local CAM tools are separate. |
| `allow.preference_writes` | Admit preference-write rows. |
| `allow.addin_reload` | Admit the add-in reload/switch verification rows. |

Every tier and permission is a JSON `true` or `false`, not text or a number. Missing, unknown,
duplicate and mistyped keys are refused; no missing choice is supplied silently. Set the cloud
scope in the `cloud` object of this same machine configuration.

Path precedence is one `--config PATH`, then `FUSION_ESSENTIALS_SWEEP_CONFIG`, then the default
`tests/live/sweep_config.local.json`. A CLI path is validated before cloud/act imports and before
publishing the environment override. For example, from the repository root:

```powershell
py -3 tests/live/tool_verify.py --config tests/live/sweep_config.local.json
```

Use `python3` instead of `py -3` on macOS/Linux; native operation there remains untested.
Only run a live sweep with the Fusion session's permission and no other driver using it.

Admission reads the actual bound endpoint, loaded identity, selected tool registry, complete
open-document census and prerequisite preferences. The measured prerequisites are Z-up modeling,
millimetre/gram Design defaults and English; the sweep does not change them to satisfy admission.
Unaccepted modified documents stop admission. `--accept-open-work` acknowledges their presence;
it does not authorize editing, saving or closing them. Resume exempts only exact checkpoint-owned
handles, not names or arbitrary open files.

A requested-on tier with missing or unread capability stops rather than silently skipping. An
off tier produces explicit out-of-scope rows, not evidence that the capability is absent. The
family sweep also requires the read-only native home observer: with `native_script=false` it
refuses before family writes because public document reads cannot certify the strict home
content-count/modified-flag fence. No permission is automatically enabled to work around that.
Those counts are a bounded fence, not proof that arbitrary existing geometry is unchanged.

Cloud work creates its own fresh top-level run folder in the configured project, leaving the
operator folder setting unchanged; pre-existing folders and documents are not cleanup targets.
Review the selected library-write rows before opting in:
the library-seed story retains the Local asset named 'Fusion-Essentials sweep test data' at
its selected exact URL and has no library-delete step. Before opting in, admit that test
namespace on the target installation; a name alone does not establish its identity. Its
create/reuse and stored-content checks require native verification. A permission-off run
makes no claim that permission-on effects were tested.

The exact machine label `reference` uses tracked reference-record locations only when all three
tiers and all three persistent-write permissions are on. Other runs use
`tests/live/records/<machine>/<scope-hash>/`; changing choices, OS or checkout separates records.
These records and the local configuration are private and ignored. A label or green partial run
does not turn scoped evidence into full acceptance; normal source/load and receipt checks remain.

## Live sweep local inputs

The family producers prepare only the state each owned document's acts consume. The map lists the
authored dependencies and reads entitlement and generation policy from `verify_program.py`. Family
state descriptions and named producer save slots are authored declarations, not exhaustive slot
inference; workspace entries show literal transitions in each act, with `inherited` when none appears.
Evidence times each setup fixture event separately; its span includes capability preflight and row
filtering for those producer rows, while family census and document-open steps have their own events.
Narrative time starts after gate filtering and ends before its later generation poll. Each generation
poll has its own span. The existing `act_seconds` still includes its generation poll, so those values
are not additive; `cleanup-total` covers teardown and home restoration as one span.

`tool_verify.py --continue-families` continues a fresh acceptance run after a logical failure.
Any failure forbids all receipts; `--acts` discovery writes none even when every family passes.
A logical failure blocks the rest of its owned family; other families run
only after exact document cleanup, restored home flags and unchanged source and loaded identity.
Uncertain transport, publication, preferences, camera state, local libraries or arbitrary scripts
stop the walk. Cloud recovery admits only the authored seam, drawing-job, generation and template
restoration gates that passed before its configuration act; failed gates forbid continuation.

<!-- BEGIN GENERATED ACT DEPENDENCIES (py -3 tests/gen_manifest.py) -->
### Family inputs and local producers

| Family | Default producers | Requires -> provides | Declared save slots | Camera cue |
|---|---|---|---|---|
| `sketch` | none | owned design document -> parametric bracket sketches | none | Skeleton and BracketBody |
| `solids` | bracket-parameters-profiles | PartLen, PartWid, PartHt -> Bracket:1 solid, StockCenter | none | Bracket:1 |
| `details` | bracket-parameters-profiles, finished-bracket, datum-details | Bracket:1 -> DatumBench, db_bore | pk_c1, pk_c2, pk_c3, pk_c4, low_top, step_top, step_lead, step_out, boss_top, edge_break, db_top, db_top2, db_bore | Bracket:1 and DatumBench |
| `resize` | bracket-parameters-profiles, finished-bracket, datum-resize, root-design-context | Bracket:1, StockCenter -> Bracket:1, DatumBench | pk_c1, pk_c2, pk_c3, pk_c4, low_top, step_top, step_lead, step_out, boss_top, edge_break | Bracket:1 and DatumBench |
| `vise` | bracket-parameters-profiles, finished-bracket | Bracket:1 -> clamped stock and vise | pk_c1, pk_c2, pk_c3, pk_c4, low_top, step_top, step_lead, step_out, boss_top, edge_break | ViseBase:1 and STOCK:1 |
| `showcase` | bracket-parameters-profiles, finished-bracket, stock-vise, showcase-pose, showcase-shapes | Bracket:1, captured vise pose -> showcase fixtures and cameos | pk_c1, pk_c2, pk_c3, pk_c4, low_top, step_top, step_lead, step_out, boss_top, edge_break | ViseBase:1 and STOCK:1 |
| `part_cam` | bracket-parameters-profiles, finished-bracket, stock-vise, recognition | Bracket:1, STOCK:1, StockCenter -> part CAM models and recognition inputs | pk_c1, pk_c2, pk_c3, pk_c4, low_top, step_top, step_lead, step_out, boss_top, edge_break, pocket_floor, recognized_cbore_walls | Bracket:1 and CAM setup |
| `swarf_cam` | cam-tool-library | owned family document -> SwarfFrustum:1, SwarfSetup | none | SwarfFrustum:1 and setup |
| `hub_cam` | cam-tool-library | owned family document -> hub CAM setup state | none | hub and CAM setup |
| `small_edits` | small-edits-box | owned family document -> EditTarget | none | EditTarget |
| `render` | render-box | owned family document -> RenderCoupon | none | RenderCoupon |
| `lookup` | lookup-box | owned family document -> LookupGuard | none | LookupGuard |
| `finale` | finale-state | owned family document -> manufacture workspace with sketches hidden | none | authored final scene |
| `surfaces` | none | owned family document -> family-local act state | none | authored act frames |
| `mesh` | none | owned family document -> family-local act state | none | authored act frames |
| `nesting` | none | owned family document -> family-local act state | none | authored act frames |
| `motion` | none | owned family document -> family-local act state | none | authored act frames |
| `fff_export` | none | owned family document -> family-local act state | none | authored act frames |
| `cloud` | none | owned family document -> family-local act state | none | authored act frames |
| `sheet_coupon` | none | owned family document -> family-local act state | none | authored act frames |
| `sheet_selected` | none | owned family document -> family-local act state | none | authored act frames |
| `sheet_positions` | none | owned family document -> family-local act state | none | authored act frames |
| `sheet_flange` | none | owned family document -> family-local act state | none | authored act frames |

### Act policy readbacks

Producer additions list late act-local setup beyond the family default. Entitlement and poll cells read the existing `ACT_NEEDS` and `POLL_AFTER` tables.

| Act | Family | Producer additions | Workspace transitions | Precondition | Entitlement | Poll |
|---|---|---|---|---|---|---|
| `ACT 0 - OVERTURE` | `sketch` | family default | inherited | `none` | `always` | `null` |
| `ACT 1 - SKETCH + PARAMETERS` | `sketch` | family default | inherited | `none` | `always` | `null` |
| `ACT 1b - SKETCH TOOLS` | `sketch` | family default | inherited | `none` | `always` | `null` |
| `ACT 2 - SOLIDS` | `solids` | family default | inherited | `sketch_get` | `always` | `null` |
| `ACT 3 - SURFACES` | `surfaces` | family default | inherited | `none` | `always` | `null` |
| `ACT 4 - MESH` | `mesh` | family default | inherited | `none` | `always` | `null` |
| `ACT 5 - DETAILS` | `details` | family default | inherited | `find_geometry` | `always` | `null` |
| `ACT 6 - RESIZE` | `resize` | family default | inherited | `model_inspect` | `always` | `null` |
| `ACT 6b - NESTING` | `nesting` | family default | inherited | `none` | `always` | `null` |
| `ACT 7 - THE VISE` | `vise` | family default | inherited | `model_inspect` | `always` | `null` |
| `ACT 7b - MOTION BENCH` | `motion` | family default | inherited | `none` | `always` | `null` |
| `ACT 8 - SWARF CAMEO` | `swarf_cam` | family default | inherited | `none` | `always` | `null` |
| `ACT 8b - THE HUB` | `hub_cam` | family default | inherited | `none` | `always` | `null` |
| `ACT 9 - THE SHOWCASE` | `showcase` | family default | inherited | `none` | `always` | `null` |
| `ACT 10a - CAM: JOB + GENERATE` | `part_cam` | family default | manufacture | `model_inspect` | `always` | `{"narrative":"DemoSetup","fallback":"Setup1"}` |
| `ACT 10b - CAM: DELIVERABLES` | `part_cam` | family default | design -> manufacture | `cam_get` | `always` | `{"narrative":"Setup2","fallback":[]}` |
| `ACT 10b1 - CAM: TEMPLATE MODES` | `part_cam` | family default | inherited | `cam_get` | `always` | `{"narrative":"TemplateGenerate","fallback":[]}` |
| `ACT 10b1b - CAM: TEMPLATE CLEANUP` | `part_cam` | family default | inherited | `cam_get` | `always` | `null` |
| `ACT 10b2 - CAM: COMPONENT SCOPE` | `swarf_cam` | family default | inherited | `none` | `always` | `{"narrative":"SwarfSetup2","fallback":"SwarfSetup2"}` |
| `ACT 10c - CAM: EXTENSION STRATEGIES` | `swarf_cam` | family default | inherited | `none` | `machining_extension` | `{"narrative":["SwarfSetup","MultiAxisSetup"],"fallback":["SwarfSetup","MultiAxisSetup"]}` |
| `ACT 10c4 - CAM: THE HUB JOB` | `hub_cam` | family default | inherited | `none` | `always` | `{"narrative":"HubTurn","fallback":[]}` |
| `ACT 10c4b - CAM: THE TURNED PART` | `hub_cam` | family default | inherited | `none` | `always` | `null` |
| `ACT 10c5 - CAM: THE HUB CONTOUR` | `hub_cam` | family default | inherited | `cam_get` | `always` | `{"narrative":"MillTop","fallback":[]}` |
| `ACT 10c6 - CAM: THE DUMP ORACLE` | `hub_cam` | family default | inherited | `cam_get` | `always` | `null` |
| `ACT 10c6b - CAM: THE 5-AXIS DUMP` | `swarf_cam` | family default | inherited | `none` | `always` | `null` |
| `ACT 10c7 - CAM: THE MILLING CENSUS` | `hub_cam` | family default | inherited | `cam_get` | `always` | `{"narrative":"MillTop","fallback":[],"max_polls":70}` |
| `ACT 10c8 - CAM: THE MILLING CENSUS READ` | `hub_cam` | family default | inherited | `cam_get` | `always` | `null` |
| `ACT 10c8b - CAM: THE LONG FAMILIES` | `hub_cam` | family default | inherited | `cam_get` | `always` | `{"narrative":"MillTop","fallback":[],"max_polls":160}` |
| `ACT 10c8c - CAM: THE LONG FAMILIES READ` | `hub_cam` | family default | inherited | `cam_get` | `always` | `null` |
| `ACT 10c8d - CAM: POCKET CLEARING FIRST` | `hub_cam` | family default | inherited | `none` | `always` | `{"narrative":"PocketClearFirst","fallback":[]}` |
| `ACT 10c8e - CAM: POCKET CLEARING READ` | `hub_cam` | family default | inherited | `cam_get` | `always` | `null` |
| `ACT 10c9 - CAM: THE TURNING CENSUS` | `hub_cam` | family default | inherited | `cam_get` | `always` | `{"narrative":"HubTurn","fallback":[]}` |
| `ACT 10c10 - CAM: THE TURNING CENSUS READ` | `hub_cam` | family default | inherited | `cam_get` | `always` | `null` |
| `ACT 10c11 - CAM: THE EXTENSION FAMILIES` | `hub_cam` | family default | inherited | `none` | `machining_extension` | `{"narrative":"MillTop","fallback":[],"max_polls":70}` |
| `ACT 10c12 - CAM: THE EXTENSION FAMILIES READ` | `hub_cam` | family default | inherited | `none` | `machining_extension` | `null` |
| `ACT 10c13 - CAM: THE ROTARY FAMILIES` | `hub_cam` | family default | inherited | `none` | `machining_extension` | `{"narrative":"HubRotary","fallback":[],"max_polls":70}` |
| `ACT 10c14 - CAM: THE ROTARY FAMILIES READ` | `hub_cam` | family default | inherited | `none` | `machining_extension` | `null` |
| `ACT 10c15 - CAM: THE ADDITIVE BUILD` | `hub_cam` | when machining_extension: swarf-frustum, cam-extension | inherited | `none` | `machining_extension` | `{"narrative":"MultiAxisSetup","fallback":[],"max_polls":70}` |
| `ACT 10c16 - CAM: FFF EXPORT` | `fff_export` | family default | inherited | `none` | `always` | `null` |
| `ACT 10d - CAM: THE SECOND SETUP` | `part_cam` | family default | design -> manufacture | `cam_get` | `always` | `{"narrative":"FlipSetup","fallback":[]}` |
| `ACT 10e - CAM: MULTI-SETUP POST` | `part_cam` | swarf-frustum, cam-scope; when machining_extension: cam-extension | inherited | `cam_get` | `always` | `{"narrative":"document","fallback":[],"max_polls":160}` |
| `ACT 10f - CAM: THE TREE LEFT BEHIND` | `part_cam` | family default | inherited | `cam_get` | `always` | `null` |
| `ACT 11a - CLOUD: THE DATA MODEL` | `cloud` | family default | inherited | `none` | `cloud_tier` | `null` |
| `ACT 11b - CLOUD: THE SAVED DOCUMENT` | `cloud` | family default | inherited | `none` | `cloud_tier` | `null` |
| `ACT 11b2 - CLOUD: LINK GUARD REVIEW` | `cloud` | family default | inherited | `none` | `cloud_link_crash_review_authorization` | `null` |
| `ACT 11c - CLOUD: THE DRAWING` | `cloud` | family default | inherited | `none` | `cloud_tier` | `null` |
| `ACT 11d - CLOUD: CAM TEMPLATE PERSISTENCE` | `cloud` | family default | manufacture | `none` | `cloud_tier` | `null` |
| `ACT 11e - CLOUD: CONFIGURATION COLUMN REFUSALS` | `cloud` | family default | inherited | `none` | `cloud_tier` | `null` |
| `ACT 11f - CLOUD: DERIVE EDITS` | `cloud` | family default | inherited | `none` | `cloud_tier` | `null` |
| `ACT 11h - CLOUD: COMPONENT COPY` | `cloud` | family default | inherited | `none` | `cloud_tier` | `null` |
| `ACT 12 - SHEET METAL COUPON` | `sheet_coupon` | family default | manufacture -> design | `none` | `always` | `{"narrative":"SM Sweep Laser Setup","fallback":[]}` |
| `ACT 12b - SHEET METAL LASER OUTPUT` | `sheet_coupon` | family default | inherited | `none` | `always` | `{"narrative":"SM Sweep Laser Setup","fallback":[]}` |
| `ACT 12b1 - SHEET METAL SOURCE UPDATE` | `sheet_coupon` | family default | inherited | `none` | `always` | `{"narrative":"SM Sweep Laser Setup","fallback":[]}` |
| `ACT 12b2 - SHEET METAL CAM RESTORE` | `sheet_coupon` | family default | inherited | `none` | `always` | `null` |
| `ACT 12c - SHEET METAL DRAWING` | `sheet_coupon` | family default | inherited | `none` | `cloud_tier` | `null` |
| `ACT 12d - SHEET METAL CLEANUP` | `sheet_coupon` | family default | inherited | `none` | `always` | `null` |
| `ACT 12e - SHEET METAL SELECTED BEND` | `sheet_selected` | family default | inherited | `none` | `always` | `null` |
| `ACT 12f - SHEET METAL FOLD POSITIONS` | `sheet_positions` | family default | inherited | `none` | `always` | `null` |
| `ACT 12g - SHEET METAL FLANGE FAMILY` | `sheet_flange` | family default | inherited | `none` | `always` | `null` |
| `ACT 13 - SMALL EDIT SAFETY` | `small_edits` | family default | inherited | `none` | `always` | `null` |
| `ACT 14 - LOOKUP TARGETING` | `lookup` | family default | manufacture | `none` | `('native_script', 'cloud_tier', 'library_writes', 'preference_writes', 'addin_reload')` | `null` |
| `ACT 15 - RENDER: LOCAL START` | `render` | family default | inherited | `none` | `always` | `null` |
| `ACT 15 - RENDER: LOCAL JPEG` | `render` | family default | inherited | `none` | `always` | `null` |
| `ACT 15 - RENDER: LOCAL TIFF` | `render` | family default | inherited | `none` | `always` | `null` |
| `ACT 15 - RENDER: LOCAL NAMED` | `render` | family default | inherited | `none` | `always` | `null` |
| `ACT 15 - RENDER: LOCAL TRANSPARENT` | `render` | family default | inherited | `none` | `always` | `null` |
| `ACT 15 - RENDER: SCENE + CANVAS` | `render` | family default | design | `none` | `always` | `null` |
| `FINALE` | `finale` | family default | design | `none` | `always` | `null` |
<!-- END GENERATED ACT DEPENDENCIES -->

A pass is either LIVE-VERIFIED (the stamp on the measured API facts was checked against a running
Fusion) or OFFLINE (you asked for it explicitly; the mocks were not re-confirmed). Either way it
checks the family receipts: a new full `tool_verify.py` run bootstraps
`tests/live/VERIFIED_FAMILIES.json` (in one go, or chunks with `--run <id>` / `--resume`).
After bootstrap, `--families render,mesh` refreshes whole named families; separate passing refreshes
can persist while other families remain stale. `--acts "ACT 5"` runs owned families for evidence
only and never stamps. Receipt runs require cleanup; use `--acts` for `--keep-open`.

`tool_verify.py --check` is offline and validates source currentness for the recorded scope on one
Fusion build. A tier declared off has an omission record, no family evidence stamp, and is printed as
out of scope; a requested tier that could not run is held and makes the check incomplete. Present
invalid cloud config is requested, while only an absent config is the opt out. Clones validate the
recorded scope without their ignored local config or raw results. `--check --full-scope` additionally
requires every admitted configurable tier on; the permanent crash-review quarantine stays excluded.
Committed compact stamps suffice on a clone; retained ignored raw results are checked when present.
Minting validates actual execution, exact loaded identity/census, unchanged source and cleanup.
`VERIFIED_TOOLS.md` composes current family stamps and lists their run provenance, including earlier
matching runs. `covered` requires an explicit `Independent` cross-tool/file/geometry witness for an
earlier successful target in the same family. Ordinary value predicates are `self-reported`; bare
`ok` steps are `called`. A tool witness must name the actual read tool and cannot credit itself.

> Requires `pytest` and `numpy` (`py -3 -m pip install pytest numpy`) for the unit tests and
> lints; `numpy` is imported by the pose checks in `tests/unit/test_design_add_instance.py` alone.
> The live sheet-metal drawing check also requires `pypdf` (`py -3 -m pip install pypdf`).
> Config lives in `pytest.ini` at the repo root; it sets `testpaths`/`pythonpath`, so no
> environment variables are needed.
>
> `--no-cov` and `--cov...` are `pytest-cov` options. Pass them only when that plugin is
> installed; without it pytest stops with "unrecognized arguments" before running a test. The
> tests do not depend on their order: a plugin that shuffles it, such as `pytest-randomly`, is
> neither needed nor a problem.

## What these test (and what they don't)

The tools are written for a *live* Fusion session, but most of their bugs live
in plain logic that runs before and around the Fusion calls: unit conversions,
string/path/URN parsing, the 0/1/N-item branches, entity classification, and
the `ok`/`error` result contract every tool returns. That logic breaks
**silently**: a wrong unit factor or a dropped error path returns subtly wrong
JSON to the agent, with no exception. That's what we pin down.

We **do not** unit-test tools whose only job is to forward data to or from the
Fusion API. Mocking `adsk` just to assert "it copied `app.version` into a
field" tests the mock, not the code. That belongs to the in-Fusion integration
layer (driven through the Fusion MCP server), not here. A tool module left
without a unit test needs an `UNTESTED` entry giving its Tier 3 reason in
`test_unit_coverage_complete.py`.

### Triage when deciding whether a tool needs tests

- **Tier 1 — test thoroughly.** Real logic: unit math, parsing, classification,
  path/name resolution, state tallies. (model_inspect, sys_get_selection,
  cam_get/_cam_common, _data_common/_doc_common, _param_common, design_configure,
  joint_create, joint_create_origin, _cam_templates, sketch_add_geometry.)
- **Tier 2 — test the one or two real helpers.** Mostly Fusion orchestration
  with a pure helper or two worth pinning. (doc_open URN parsing, quoting
  helpers, design_get tree/timeline slices,
  doc_update_xref/cam_generate helpers.)
- **Tier 3 — skip.** Fusion pass-throughs with no pure logic. Skipping is
  correct, not lazy.

## How the harness works (`conftest.py`)

Two problems make these tools awkward to import in a test, and `conftest.py`
solves both:

1. **Module-top `adsk` access.** Each tool does `app =
   adsk.core.Application.get()` at import time. So `install_mock_adsk()` injects
   mock `adsk` / `adsk.core` / `adsk.fusion` / `adsk.cam` into `sys.modules`
   **before** any tool is imported (it's called at collection time).
2. **Importing the package pulls in Fusion-dependent code.** `entry.py`
   auto-discovers and imports every tool (most need Fusion) and
   `commands/__init__.py` builds UI panels. `load_tool("model_inspect")`
   sidesteps both: it puts `commands/` on the path, imports only the cheap
   adsk-free packages, stubs `mcpServer.tools`, then spec-loads the single
   requested module so its `from ..mcp_primitives ...` relative imports resolve.

```python
from conftest import load_tool
mi = load_tool("model_inspect")   # at module level
```

### The one rule the mocks impose: assert on concrete values

`adsk.core` / `adsk.fusion` / `adsk.cam` are `unittest.mock.Mock` objects.
Unmodeled attribute access returns a **truthy child Mock**, not `None` and not
an error. So:

- `assert result is not None` is almost always true and proves nothing.
- `assert payload["x"] == 50.0` catches a real bug.

A few `app.*` reads are pre-seeded with real values (`app.activeDocument.name =
"TestDoc"`, `app.version`) and a few `.cast` methods are pass-throughs
(`Design.cast`, `Operation.cast`) so that tools which filter on a cast result
behave correctly. If a tool reads some `adsk` attribute that returns a stray
Mock and pollutes a JSON payload, fix it **in the harness** (model that
attribute) rather than in each test.

### Fakes: extend the shared ones

Every unit test stands on the shared fakes under `tests/fakes/`, one module per
Fusion family over a scaffold module the families share. `conftest.py`
re-exports every name, so a test imports its fakes from conftest (`from conftest
import BRepBody`) and a new fake joins its family's module. `make_design` /
`MakeComp` / `MakeDesign` build a design, and `install(mod, design)` wires it
into a tool. The smaller classes are named after Fusion's runtime type names,
because tools branch on `type(x).__name__`: `BRepFace`, `BRepEdge`, `Plane`,
`Cylinder`, `Line3D`, `Circle3D`, `BRepBody`, `FakeVector3D`, `FakePoint`. They
implement only the interface a tool reads.

When `MakeComp`/`MakeDesign` lack a surface your tool needs, extend the shared
fake; don't fork a bespoke `Fake*` hierarchy into your test file. A type whose
shape was measured in live Fusion (a key of `live_api_facts.SHAPES`) uses its
shared fake: import it, or subclass it and add only the extra the test needs.
`test_fake_shapes_exist.py` compares each shared fake's attributes with the
measured shape, and refuses a free-standing local double of a measured type,
because that comparison never reads a local copy. A type with no measured shape
keeps a local double, whose one-line docstring says so.

## Adding or updating a test

[AGENTS.md](AGENTS.md) is the recipe: which pattern to copy (a rich read, a fuller fake object
model, or a pure function), the shape every new test follows, and how to update a test when the
behavior it pins changes.

## Offline API change-impact report

`api_change_report.py` compares the API declarations of two Fusion builds and lists the tools and
tests a change may affect. Its declaration parser comes from the API explorer, and it shares the
exact-byte AST loader with `gen_api_surface.py`. It does not import `adsk`, contact Fusion, regenerate facts,
or change live receipts. Capture each build from an explicit `adsk` directory containing `.py`
bindings, then compare two snapshots with the same declaration representation:

```powershell
py -3 tests/api_change_report.py snapshot --bindings-dir "C:\path\to\Api\Python\packages\adsk" --build-label "2705.1.15" --out outputs/api-history/2705.1.15.json
py -3 tests/api_change_report.py diff outputs/api-history/before.json outputs/api-history/after.json --out outputs/api-history/impact.json
```

The build label is whatever you pass; nothing checks it against the installed build. Snapshots
record exact binding paths, byte SHA-256 hashes, scanner hashes, available modules, and absent known
namespaces. A webdeploy channel/directory ID is recorded when present in the path. Existing
snapshots and reports are never overwritten, so choose a new filename for another capture.
Snapshots carry a content digest checked before comparison. Keep the original snapshots rather than
editing their labels or declarations, and recapture a snapshot saved in an older exploratory format.

The diff refuses incompatible formats, namespace scopes, or SWIG-versus-Python representations.
It compares only namespaces available on both sides; a newly available or unavailable namespace
is reported separately, never as a batch of symbol additions/removals. Changed records include
method overload signatures, property readability/writability and setter signatures, enum/constant
expressions or literal values, documentation hashes, and preview/retired/unsupported wording markers.
SWIG references to native enum constants do not reveal their numeric values. Generic `*args`
signatures and documentation markers are declarations, not verified runtime contracts.

`--repo PATH` selects the source checkout to map against (default: this command's checkout).
Affected tools and acceptance cases are explicitly `syntactic_candidate`: attribute names and
local import chains identify leads; unit filenames, literal live rows, and explicit tool mentions
identify candidate checks. Source hashes and line locations accompany them. A match is a lead, not
proof: text matching can hit common names and miss dynamic references or scenarios that never name a
tool, and the report neither runs the candidate tests nor certifies them sufficient. An empty match
does not prove no impact, and a zero-change report proves only that the compared declaration records
match.

Focused verification: `py -3 -m pytest tests/unit/test_api_change_report.py tests/unit/test_generators.py -q`.
