# Working in Fusion-Essentials (MCP server)

If this file was handed to you as your instructions, this file and the documents below are your instructions:
read them in this order and follow them. If you were told to use it for a task, start a subagent
and hand it this file, with the task, as its brief.

- [commands/mcpServer/tools/AGENTS.md](commands/mcpServer/tools/AGENTS.md)
- [tests/AGENTS.md](tests/AGENTS.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)

The rules every tool under `commands/mcpServer/` follows, whichever file it lives in.
[CONTRIBUTING.md](CONTRIBUTING.md) explains the architecture and the ideas behind it.
[commands/mcpServer/tools/AGENTS.md](commands/mcpServer/tools/AGENTS.md) is the recipe for adding a
tool (the helper catalog, exemplars, the lints) and loads automatically when you work in that
directory. [tests/AGENTS.md](tests/AGENTS.md) covers writing a test. The code is the source of truth;
when in doubt, match the nearest existing tool.

Existing unsupported API uses are listed in
[UNSUPPORTED_API.md](commands/mcpServer/UNSUPPORTED_API.md); new unsupported, preview or retired uses need the owner's word.

## Planning files

Keep `plans` sparse; it is private and absent from a clone. `plans/backlog.md` is the ledger, the one
list of open work. A handoff that is ready for native testing or acceptance goes in
`plans/<BACKLOG-ROW-ID>.md`. Update an existing row instead of writing a competing plan or status
report, and delete a row's plan when the row is removed.
Put agent scratch files, reports, evidence, exports and worker handoffs in the gitignored `outputs/` directory. Keep `tests/live/evals/results/` for real eval runs and `.cache` for tooling caches and isolated worktrees. Remove temporary scaffolding when a task finishes.

## Read vs Edit: the two kinds

A tool either changes state or it does not, and its `write=` flag records which. This is
Command-Query Separation, and it is the one split a machine can check.

| Kind | Does | `write=` | Examples |
|---|---|---|---|
| **Read** | Return information, change nothing. Safe to call at any time. | read | `cam_get`, `find_geometry`, `model_measure_between`, `workspace_orient` |
| **Edit** | Act: change the model or data, or run an async operation. Gets the write guard; must verify its effect. | write / destructive | `model_extrude`, `joint_edit`, `doc_save`, `cam_edit_tools` |

A Read comes in three shapes. They help you choose the tool's form; the permission is the same.
- **Orient** (`orient`) - one cheap read across every area to get your bearings: where am I, what is
  broken, where next. Call it first; it returns a summary, not everything. `workspace_orient`.
- **Disclose** (`get`) - a rich read of one area: a small default, and more through `include=` or a
  scope. `cam_get`, `design_get`, `doc_get`, `data_get`.
- **Acquire** (`find`/`measure`/`probe`/`inspect`/`compare`/`screenshot`/`section`/`compute`/`request`) -
  a read whose output feeds an Edit: a handle, a measurement, an image, a user pick, a diff. For
  example, `find_geometry` returns a handle and `joint_at_geometry` consumes it (see `_inputs.py`). An
  Acquire has its own query parameters and returns handles, so **it stays a separate tool from a
  Disclose read**.

## Naming schema

Every tool is `<domain>_<verb>[_<noun>]`, with `<verb>` from a closed vocabulary, and **the verb's kind
must agree with `write=`**: a read verb (`get`/`find`/`probe`/...) is read-only and an edit verb
changes state. So `cam_get` reads, `model_compute_holder` acquires and `cam_edit_tools` writes.
`test_tool_naming.py` enforces this and holds the verb vocabulary. The exemptions (a poller like
`cam_get_status`; a read-verb tool that still changes state, such as `view_section`) and how tools
are packaged (one tool per file, shared code in the family's underscore helper) are in
[commands/mcpServer/tools/AGENTS.md](commands/mcpServer/tools/AGENTS.md).

## Honesty contract (the rule that matters most)

- Use `ok(...)` / `error(...)` from `_common`. Wrap per-field reads in `safe(getter, default)` so one
  bad field does not sink the call, but let a mutation raise. A failed delete or edit must return
  `isError`, never `ok`.
- After a write, verify the effect and report it. If the API returns success but nothing changed
  (it happens), treat that as a failure. Report partial success explicitly: what was done and what
  was not.
- Reading `adsk.*` code cannot tell you what the API actually does. Before "fixing" a geometry,
  matrix or API bug you spotted by reading, reproduce it live first (`sys_execute_script` against a
  scratch document, or drive the tool and read the result back), and confirm the fix live too. A
  plausible-looking bug is often correct code whose API contract you misread, and the "fix" is the
  regression.
- Guard inputs and say *why* a precondition failed, naming the offending value. Resolve references
  (occurrences, geometry) through the typed kinds described under "Input kinds" below.
- Resolving a name yourself: whether taking the first match is a bug depends on whether the name is
  unique. A **scope-unique** name (a CAM setup) resolves by case-insensitive exact match, lists the
  available names on a miss, and is still refused when two setups share it
  (`_cam_common.find_setup`). A **non-unique** name (two sub-assemblies each holding a "Bolt:1")
  must **refuse** the ambiguity, never return the first substring/`.find()`/`[0]` hit, which
  silently targets the wrong entity. `test_no_first_match_resolvers` catches the shapes that are
  always wrong (substring, first by index), but deciding whether a name is unique is your call.

## Input kinds

To reference existing geometry or structure (face, edge, body, plane, axis, profile, occurrence,
length, fixed choice), use a typed kind from [`_inputs.py`](commands/mcpServer/tools/_inputs.py)
instead of hand-rolling a `name` or `index` resolver. The kinds refuse ambiguity instead of grabbing
the wrong instance. Wire one with `tool.add_input_property(*kind.as_property())` and resolve it with
`_inputs.resolve_inputs(...)`. If a kind is close but lacks a selector, extend the kind, not one
tool's local copy. An input with a fixed set of values is a `Choice`; a new raw `enum` schema is not
accepted in review, and the raw enums in older tools are not exemplars. The full catalog of kinds
and shared helpers is the generated map in
[commands/mcpServer/tools/AGENTS.md](commands/mcpServer/tools/AGENTS.md), which loads when you author
a tool.

<!-- BEGIN GENERATED FAMILIES (py -3 tests/gen_manifest.py) -->
**Tool families** (224 tools — `sys_find_tool <kw>` to search, `TOOL_MANIFEST.md` for the full list): `model`(40) `surface`(12) `form`(3) `mesh`(16) `sketch`(15) `cam`(27) `assembly`(9) `joint`(7) `design`(16) `doc`(14) `data`(10) `drawing`(12) `param`(5) `pmi`(4) `view`(6) `render`(3) `find`(1) `workspace`(1) `appearance`(1) `save`(1) `sheet`(11) `sys`(10)
<!-- END GENERATED FAMILIES -->

## Tool descriptions and agent-facing strings

A tool's **description** and the `note`/`error` it returns are the only things a connected agent
knows about it. They cross the wire JSON-serialized with `ensure_ascii`, so keep them pure ASCII
(` - ` not `—`, `...` not `…`, `->` not `→`, `deg` not `°`); `test_wire_ascii.py` enforces this. Every
claim about an input's legal values must be backed by something that fails when the claim is false (a
`Choice`/enum, a typed kind's `resolve()`, a guard). If you can't back it, type the input instead of
asserting it.

Every call pays for these strings, so they are budgeted (`test_prose_budget.py`): a description says
what the tool does and what to call next; a note says what was observed and the next step; an error
names the offending value and the remedy. None of them says that something was measured, why the
platform behaves that way, or how the code is built. That teaching goes in the error an agent meets
at the moment it matters, once. A rich read's deep `include=` returns the slice asked for, not the
default slice again.

## What "done" means

A fix or feature is committed only when every requirement below is met. The agent that commits (the
coordinator, or the lead it names) holds each agent that contributed, subagents included, to this
list. The evidence for a requirement comes with the hand-over; a requirement claimed without its
evidence is not met.

1. **The sweep row passes live.** The change's row in the live sweep (`tests/live/tool_verify.py`)
   passes on the real Fusion session.
2. **The run was on the code being committed.** The affected capabilities ran live on the exact code
   loaded in Fusion. A checkpoint verified only offline does not qualify.
3. **The receipt is restamped.** `tests/live/VERIFIED_TOOLS.md` matches that code.
4. **An independent agent reviewed it.** Not the agent that built it. The reviewer runs a handful of
   mutants, not dozens, and drives the live session to check API claims whenever it can.
5. **The required checks pass.**
6. **Each changed behavior an agent can observe has a demonstration for feedback.** It is reproducible, it sits in
   the existing live sweep, and an independent check of its effect lands in the same change. Internal
   helpers are exercised through the public behavior they affect; naming a tool in the sweep does not
   by itself validate new logic.
7. **Unit tests are aimed, not counted.** One test per plausible bug, not one per function.
8. **The wave ends with a cold eval run.** Every wave (one batch of backlog work) ends with one
   (`tests/live/evals/proctor.py`: a fresh agent with no skill appended), so only what the tools say
   on the wire is graded.

Work that does not yet meet the list stays in isolated worktrees and gitignored backups.

Why the weight is on the live session: mock unit tests prove handler logic and nothing about Fusion.
They encode the builder's beliefs, and a wrong belief pinned by a test is the most confident way to
ship a lie.

## Enforcement is a closed list

The files in `tests/lints/` are the closed list: the wire contract (naming + verb/`write=`
agreement, write-status, strict schema, input names, output contracts, ASCII, wire budget and shape,
wire caps interpolated, prose budget, permission posture, capability map complete), the honesty
contract (no fabricated fallbacks, bool returns checked, no first-match resolvers,
postconditions declared, units, native identity keys, export knob pre-read, frame disclosure, material
effect, rename adoption, no hand-cast product), and the structure (helper duplication denylist, no
duplicate defs, dead code, autodiscovery, unit-coverage-complete, tool-verify-complete, assert
strength, generated docs current, doc citations, measured enums, no hand-seeded enums, fake shapes,
evergreen). Adding a lint file needs the owner's
word; a new duplication class gets a denylist entry, not a file. No ratchets, no per-file
baselines, no self-tests for lints. Wording is policed in two places only: the size caps
(`test_prose_budget.py`) and `test_evergreen_no_baggage.py`; a new wording rule goes into
evergreen, not into a new file. The suite
regrew twice after purges because every review finding became a lint. A finding becomes a backlog
row, a fix, and a step in the live sweep.

## Prose in code

A docstring says what the function returns or does. One line is the aim; at most four lines (a
module docstring, six). A comment is at most three lines stating a present-tense fact the
code cannot show (a platform trap at its point of use, with no history). A helper's catalog blurb is
one table row of at most 400 characters: its symbols and when to reach for it. `test_prose_budget.py`
enforces these limits for the files in `commands/mcpServer/tools/`; elsewhere they are the habit to
follow.
