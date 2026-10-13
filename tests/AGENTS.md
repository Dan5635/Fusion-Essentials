# Writing a test here

Before calling any change done, run `py -3 tests/check_all.py`. It runs the generator checks, the
suite, the live-run receipt check (`tests/live/VERIFIED_TOOLS.md`) and the live gate, and each
failure names its repair; [tests/README.md](README.md) explains each stage.

Root [AGENTS.md](../AGENTS.md) has the project rules. [tests/README.md](README.md) explains the
harness: how `conftest.py` mocks `adsk`, the fakes, and which tools need tests at all. This file says
which pattern a new test copies.

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
`parametric-cad-design` skill package; `--check` fails if anything is stale, and
`test_generated_docs_current.py` enforces it.
