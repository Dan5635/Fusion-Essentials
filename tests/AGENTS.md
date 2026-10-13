# Writing a test here

Before calling any change done, the lead schedules `py -3 tests/check_all.py` on the frozen
candidate under a native lease. It runs generator checks, the suite, the live-run receipt check
(`tests/live/VERIFIED_TOOLS.md`) and the live gate; [tests/README.md](README.md) explains each stage.
Contributors run their focused offline checks and submit the native work still owed. A private
checkout or successful unit run does not authorize a live gate or a full sweep.

Root [AGENTS.md](../AGENTS.md) has the project rules. [tests/README.md](README.md) explains the
harness: how `conftest.py` mocks `adsk`, the fakes, and which tools need tests at all. This file says
which pattern a new test copies.

## Contributing a live sweep case

The sweep uses one working document per family. Cases share that document and declare their own
inputs, names, retained handles, independent reads and cleanup. A second document needs a concrete
reason: document lifecycle, a newly opened document's settings, destructive loss of history, or a
condition the public tool can only read across an otherwise empty document. A familiar scratch
helper, repeated names, unqualified body addresses and whole-document count assertions are reasons
to repair the case's scope, not reasons to open another document. List every exception and the exact
condition it protects in the handover. The runner owns closing family documents by handle, unsaved.

**Where to put it.** `tests/live/verify_program.py` declares `_ACT_PROGRAM` and compiles `ACTS`;
`verify_families.py` gives each act exactly one family through `FAMILY_GROUPS`. Find the existing
family and add rows to its `verify_acts_*` module, normally through a named row factory. Geometry
belongs in the appropriate family, even when a later CAM or showcase case consumes it. If adding
an act, add its name/prefix ownership and preserve its family-local order. `STEPS` is the coverage
union; it is not a place to append an unowned case. `STORY` describes the checks that actually run.

**Rows.** Each row is `(tool, args, expect, save)`. `args` is a dictionary or a function taking the
run context. `expect` is a strict payload predicate, `_refused(...)` for an expected refusal, or
`"ok"` only for a call whose effect is checked separately. `save` is `None` or `(key, extractor)`;
use `_recall(key, extractor)` when subsequent predicates also need the result in `_RECALL`.
Retrieve required identities with `_ctx_get(ctx, key, explanation)`, which refuses missing input.
Read payload fields in the tool's source; do not invent them from its name or from an adsk mock.

**Inputs and independence.** A family must run by itself without objects left by another family.
Reusable inputs are registered in `PRODUCER_ROWS`, with `PRODUCER_SLOTS` listing the handles they
provide. `FAMILY_DEPENDENCIES` names the family's producers and inputs; act-specific producer
changes go in `ACT_PRODUCER_OVERRIDES` or its conditional counterpart. `fixture_steps` supplies
those producers in entitled and unentitled modes. Do not rerun the same expensive rig in each case
when its geometry can be reused unchanged. Producer calls maintain inputs; they do not stamp the
consumer tool. A precondition read and a fallback must consume only declared local inputs. An empty
fallback earns no coverage; gates and skips must explain a real capability or scope condition.

**Document and geometry scope.** `_family_rows(key)` in `verify_acts_sketch.py` supplies a document
read, root activation, guarded `write`, `read`, and an exit read. Its `close()` closes the case's
scope, not a document. Use it for ordinary geometry in the owned working document. Callers of the
older `_scratch_rows` must justify the extra document. Give each case and control unique names;
body names like `Body1` repeat between components, so retain a typed geometry handle or qualify the
body as `Occurrence:1:Body1` (a root body uses the actual root component name). Qualify sketch/feature addresses where
names repeat; a writer's generated name alone is not a globally unique selector. Return activation
to the documented root context at case exit. Never save, close or change another family's document.

**What to judge.** Follow a write with a separate read of its physical or persistent effect. For a
18 x 10 x 6 mm box with a centred diameter-3 through-hole, the independent volume is
`1080 - 13.5*pi` mm3, and its bounds remain 18 x 10 x 6 mm. Also read the hole's radius, axis and
through extent, and prove a named neighbouring control unchanged. A successful write or its own
volume echo is insufficient. Use `_measured(label, observed, valid)` to retain concrete evidence;
attach `Independent` provenance only to a read that independently establishes the named write's
effect, using the existing nearby case's target binding pattern. Inspect `judged_steps` and the
family witness tests when choosing that pattern. Reject missing, ambiguous, truncated or non-finite
measurements. Check units, accuracy and the actual selected target. For a refusal, retain baseline
geometry/parameters/history before the attempted write and compare a fresh read afterwards. Do
not replace a former numeric or control assertion with a count or a nonempty-list check.

**Placement and view.** `verify_layout.py` owns chunk offsets (`_SLOTS`) and framing helpers;
`verify_program.compile_program` applies family-local placement and sketch ordering. A component
is one chunk so its overlapping operands move together. Keep unrelated cases in separate visible
regions; never translate just one operand of an intersection or joint. Static dictionary rows can
be placed by the compiler. Callable arguments and native script coordinates need an explicit
frame audit; do not assume the compiler translated them. Use `_px(chunk, x)` and `_py(chunk, y)`
for independent world-coordinate expectations when the chunk has an authored offset. Local sketch
coordinates and occurrence transforms are different frames. Show the current subject and its
control with `_watch`/the existing framing helpers or an explicit focused `view_set`; an overall
fit of a document full of distant cases is not useful framing. Read back the camera and inspect
PNG pixels under a lease when view quality is part of the claim. Do not change a global camera or
preference without reading, restoring and checking it on a new document.

**Example case structure.** Start with `_family_rows("coupon_doc")`; create and activate a uniquely
named `ContributorCoupon` component; create `ContributorCouponProfile`; draw its rectangle;
extrude it 6 mm; independently inspect the component and bank its bounds and volume. Acquire the
hole face/axis from a scoped geometry read, create the centred through-hole, and independently read
its volume and cylinder geometry. Inspect the control before and after. Finish with the helper's
exit read. Each saved slot starts with `coupon_`. Add a focused unit for the effect predicate that
accepts the actual correct payload and rejects a wrong volume, wrong target or changed control.
Follow a comparable existing case for the tool's exact arguments; this outline is not a new API.

**Receipts and cloud.** `verify_receipts.family_closures` binds the engine, selected authored rows,
reachable checks and tool imports. Declaration selections retain their dependencies, including
captured argument values; comments and line numbers are not checks. Shared engine changes still
invalidate all families. Run identifiers, document handles and artifact paths do not prove source
identity. A selected development run writes evidence only. A whole-family refresh can stamp only
complete independent coverage, stable loaded/source identity and exact certified cleanup; manually
editing a receipt is forbidden. Cloud cases use the run's admitted fresh destination, preserve the
operator config and report saved leftovers and lineage. Extra saved source/host documents need
explicit admission; an uncertain write is a stop, not a reason to retry or delete files.

**Check and hand over.** Work in an isolated checkout. Reserve shared act/runner files with the
lead and submit their changes as a transfer patch. Compile/import the real program without a
transport; inspect the final family's rows, declared producers and document transitions. Run the
existing focused program/receipt tests, update position pins when rows move, and run the existing
lint list. Break the specific guard or predicate, prove the relevant check fails, and restore
byte-identical source. A synthetic payload or mock proves logic only. Report the patch hash,
changed acts/families, document exceptions, calls added/removed, mutation outcomes and native work
still owed. Native premise checks and the affected family development run require a Coordinator
lease: match the opening census before writes and close only owned unsaved documents by handle.
Typical lead-scheduled commands are:

```text
py -3 -m pytest tests/unit/test_tool_verify_program.py tests/unit/test_family_receipts.py -q -p no:cacheprovider
py -3 tests/live/tool_verify.py --acts "ACT 2 - SOLIDS" --run contributor-solids --trace
py -3 tests/live/tool_verify.py --families solids --run refresh-solids --trace
py -3 tests/live/tool_verify.py --check --full-scope
```

`--acts` exercises evidence without stamping; `--families` refreshes complete families after the
required bootstrap and lifecycle guards. Do not launch these live commands without a lease or
under another run. A stop, failed strict row, uncertain dispatch or unexpected census change must
be retained and reported. The lead freezes the reviewed union, runs its pre-cases and acceptance,
and commits it. Required `check_all.py` includes a live gate and belongs to that scheduled run;
your private offline tests do not authorize that gate or a full sweep.

## The canonical pattern: every new test follows it

Every test imports its tool with `conftest.load_tool("<tool>")`, then sets up all state with a
`@pytest.fixture` and `monkeypatch.setattr`, never an imperative `mod.app = …` assignment at module or
test-body level. A fixture's patches undo themselves after the test runs, so nothing leaks into the
next one; an imperative assignment does not undo itself.

Pick the shape that matches what you're testing:

- **A rich read** (`<domain>_get`, or a router that dispatches to `_slice_*`/measurement-core
  helpers) → copy **`test_design_get.py`** or **`test_model_inspect.py`**. A fixture stubs the
  router's internal slice functions with `monkeypatch.setattr`, and the tests assert how the router
  composes them: the default is the orientation slice only, each `include=` adds exactly its slice,
  and the note advertises the rest. They do not re-mock the underlying Fusion calls; live validation
  covers those. `test_cam_get.py` is the same shape.
- **A tool that needs a fuller fake object model** (bodies, occurrences, components) → copy
  **`test_model_mirror.py`**. It builds a design with the shared `make_design(...)` /
  `MakeComp` / `MakeDesign` fakes and wires it into the tool module with `install(mod, design)`,
  inside a fixture. `install` patches both `_common` import paths (see the next section), plus
  `adsk.fusion.Design.cast` and `adsk.core.ObjectCollection.create`. If `MakeComp`/`MakeDesign` lack
  a surface your tool needs, extend them in the design family module under `tests/fakes/`; don't fork
  a bespoke `Fake*` hierarchy into your test file.
- **A pure function** (parse/encode/convert, no Fusion at all) → copy **`test_quoting.py`**. There is
  no `adsk` surface to fake; call the function and round-trip the result.

Then read the tool, list its `_helper` functions and the `handler`, and write one test per plausible
bug, not one per function. For each test ask: **what specific, plausible bug would this catch?** If
the only answer is "the function was deleted", the test is decoration; assert the value that would
change if the logic were wrong. Name the test like a spec line (`test_picks_largest_body_by_volume`).
Assert on concrete values: `adsk.*` mocks return a truthy child `Mock` for anything unmodeled, so
`assert result is not None` proves nothing. Cover sizes 0, 1, 2 and N for anything taking a
collection, and the guards (bad units, no active design, missing or ambiguous target) alongside the
happy path. If a tool reads an `adsk` attribute the mocks don't model yet, add it to
`install_mock_adsk()` (or a `.cast` pass-through) once, in the harness, rather than re-mocking it per
test.

**Deleting an attribute off the shared `adsk` mock does not reliably undo itself.** `monkeypatch`
cannot restore a `Mock` child it marked `_deleted`, so the deletion can outlive the test: one
`monkeypatch.delattr(adsk.fusion, "DistanceUnits")` passed on its own and took 9 unrelated tests down
under randomized order. Many tests here delete an `adsk` member to cover a "this build lacks it"
branch and are fine. Which deletions leak is unknown; deleting a member of an enum family the shared
fakes read is known to leak. So prefer another route to that branch (an unknown key, a `getattr`
default, a `safe()` that returns the default). If you delete anyway, run `-p randomly` over the full
suite before believing it.

Every unit test stands on the shared fakes under `tests/fakes/`, imported from `conftest.py`, and a
type whose shape was measured live must use its shared fake. [tests/README.md](README.md), "Fakes",
has the rules.

## Patch both `_common` import paths (the dual-seam trap)

A tool that resolves geometry or occurrences through a typed kind in `_inputs.py` reads the active
design through two import paths: its own `from . import _common` and `_inputs`'s own `from . import
_common` (imported again inside `_inputs.py`). Patching only `mod._common.design` leaves
`mod._inputs._common.design` pointing at the real Fusion app, which is absent in tests, so an
`_inputs` kind's resolution silently fails even though the handler's own reads work. Patch both to
the same design object, inside a fixture so it is torn down. `conftest.install(mod, design)` does this
for you; if you patch by hand, patch `mod._common.design` and `mod._inputs._common.design` together.

## Comments and API facts in tests

A test comment states a present-tense fact, by habit in at most three lines: no process notes,
observation diaries or plan references (`test_evergreen_no_baggage.py` catches the history and plan
phrases, dates and work-item labels on its own list; nothing counts the lines). An adsk API fact
(an enum int, a behavior flag) is never hand-typed; it comes from the generated
`live_api_facts.py`. The mock adsk enums arrive pre-seeded with measured values, the shared fakes
read their behavior flags from it, and `test_no_hand_seeded_enums.py` bans hand-assigning a measured
member. If a fact you need is missing, add a measurement row to `measure_api.py` and regenerate
against live Fusion.

## Prove a test bites

After writing a test, break the code it covers for a moment (flip a comparison, change a constant),
confirm the right test goes red, then restore the code. Do this especially for a new guard or cap: a
`truncated` flag or an ambiguity refusal is easy to write in a way that always passes.

The harness sets `sys.dont_write_bytecode = True` so a stale `.pyc` cannot hide the restored source
after a quick break and restore: the tool loader spec-loads source files, and mtime-keyed `.pyc`
caches can go stale when a tool is edited and restored quickly.

## Updating tests as behavior changes

**The test changes in the same commit as the behavior it describes.** A red test after a code change
is the suite telling you a promise changed: confirm you meant it, then update the test. A test may
only pin correct behavior. Pinning a wrong result (for example a first-match resolver's substring
hit) locks the defect in place, so when the handler is corrected, the test that asserted the wrong
behavior goes red; update its assertion to the correct value. Never edit a test just to make it pass
without understanding why it broke (a refactor that changed behavior -> fix the code; a test
asserting an implementation detail -> fix the test).

## Regenerating docs

`py -3 tests/gen_all.py` rebuilds everything under `tests/generated/`, plus `tests/api_surface.py`,
the marked blocks in root AGENTS.md, tools/AGENTS.md and tests/README.md, and the
readable `commands/mcpServer/guidance/parametric_cad_design.md`; `--check` fails if anything is stale, and
`test_generated_docs_current.py` enforces it.
