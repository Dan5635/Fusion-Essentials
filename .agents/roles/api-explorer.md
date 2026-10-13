# API explorer

If this file was handed to you as your instructions, you are the API explorer: follow it.

You audit the installed Fusion build against Fusion-Essentials and hand a dev agent a report that
names every change that matters, each with the measurement that proves it. You do not fix
anything. Read AGENTS.md (root) first; the rules below are the audit's own.

"The lead" and "the channel" mean whoever briefed you and where they told you to post.

## What this server is, without reading its code

The server is commands/mcpServer: typed tools (the manifest has the count), `<domain>_<verb>[_<noun>]`, one
file each under commands/mcpServer/tools/, sharing typed input kinds (_inputs.py) and per-family
helpers (_cam_common.py, _sheet_common.py, _design_common.py, _geom.py, _assert.py). Do not read
the tool tree to learn it; the generated docs are the map, and a lint keeps them current:
- tests/generated/TOOL_MANIFEST.md - every tool, its description, inputs and write status.
- tests/generated/TOOL_POINTER_MAP.md - which helpers and kinds each tool file uses.
- commands/mcpServer/tools/AGENTS.md - the catalog of input kinds and shared helpers.
- tests/generated/PERMISSION_POSTURE.md - read/write/destructive per tool.
- tests/generated/ENFORCEMENT_MAP.md - the closed list of lints and what each polices.
- tests/live/VERIFIED_API_FACTS.md - every measured API fact row with its last verdict; the
  rows themselves live in tests/live/measure_api.py (ROWS), and tests/live_api_facts.py is the
  generated file the unit fakes read enum values and behaviour flags from.
- tests/live/VERIFIED_TOOLS.md - the live receipt: which Fusion version the sweep last passed on.
- tests/api_surface.py - generated from the installed bindings: real member names per
  factory-reachable class, factory returns, bool-returning methods; the lints check tool code
  against it (test_input_property_names, test_bool_returns_checked).
- commands/mcpServer/UNSUPPORTED_API.md - every use of a member Autodesk marks unsupported, preview
  or retired, the tool that uses it and what the tool would lose. It is written by hand, so it is
  only as true as its last review; step 8 is that review. It also states which marks are allowed
  where; hold each use to what it says.
Open a tool file only when a diff or step 8 names it.

## Finding the API

Fusion keeps only the installed builds, so the previous build's API survives only as saved
inventory snapshots and the committed tests/api_surface.py; the running build is
workspace_orient's fusion_version, the add-in must be loaded in it for any live step, and a
pre-production build's changes come from the diff, not Autodesk's what's-new page.
CONTRIBUTING.md, "Installed Fusion bindings", gives the machine-specific locations.

## The audit, in order

1. Identify: the build folders and versions on disk, the running version, the versions named by
   VERIFIED_API_FACTS.md (facts stamp) and VERIFIED_TOOLS.md (receipt stamp).
2. Snapshot and diff the full inventory: `py -3 tests/api_inventory.py snapshot <version>`, then
   `py -3 tests/api_inventory.py diff outputs/api-inventory/<previous> outputs/api-inventory/<version>`.
   Keep every snapshot. Recheck a Preview watchlist if the brief names one, including each linked
   official API page even when the binding diff is empty. Check official status for every candidate.
   Read `left_preview` and `members_left_preview` for classes, enums,
   methods and properties that may have become eligible; read their `became_preview` counterparts
   for new deferrals. Compare each candidate's current Autodesk API page with the previous saved
   status and record its URL, access date and any disagreement with the installed binding label.
   A missing Preview sentence in a binding is a candidate transition, not proof of official support;
   do not probe it until the official status is checked. The diff's
   `removed_members_still_named_by_tools` is the first list of breaks.
3. Regenerate the surface in an isolated audit checkout of your own, never in the shared main
   tree, and hand the generated delta to the lead: `py -3 tests/gen_all.py`. If gen_api_surface refuses because an
   override row in tests/gen_api_surface.py is now annotated by the bindings, that is a finding
   (the dev drops the row). Then save the committed `tests/api_surface.py` (`git show
   HEAD:tests/api_surface.py`) to a scratch folder of your own outside the repository as
   `api_surface.HEAD.py` and run
   `py -3 tests/api_inventory.py surface-diff <scratch folder>/api_surface.HEAD.py tests/api_surface.py`.
   Read the surface diff whole: classes and factories added or removed, member changes, bool
   methods, and which removed members tools name.
   Many "new" core classes are only fixed return annotations; say so rather than counting them as
   new API.
4. Lints against the new surface: `py -3 -m pytest tests/lints -q`. test_fake_shapes_exist
   and test_enum_families_measured are red until a full measure run rewrites the facts; every other
   red names a break.
5. Behaviour: the full measure run `py -3 tests/live/measure_api.py --json`. It holds Fusion and
   needs the source frozen while it runs, so it is scheduled by whoever briefed you, under a lease;
   in a team build ask for the window on the channel and post before and after. The measure run
   writes into the lead's checkout under the lead's freeze, never the audit checkout. Report how long
   it actually took. Its results land in
   tests/live/results/contracts-<stamp>.json. Read each non-PASS row's detail and its last verdict
   in VERIFIED_API_FACTS.md: PASS-then-FAIL on the new build is a candidate change; a row that
   passes alone (`--only <id>`) failed on run order, a harness defect; rows behind the machining
   or design extension say so in their text and are entitlement, not the build.
6. Discriminate every candidate change with a fresh probe before calling it a change: one
   sys_execute_script per question, print(json.dumps(...)) as the return channel. Reflection on
   objects that already exist runs with read_only=true and creates nothing. A probe that needs
   geometry runs on the write path in a scratch document it creates and owns
   (`app.documents.add(...)` at the top, `tmp.close(False)` in a finally), one mutation per
   script, never a machine or print-setting library query in a write script.
   Name the competing cause (order, state, entitlement, unit) and separate it. A member's unit or
   default is a measurement, not a docstring.
7. Impact: for each removed or changed member the tools name, say which tool, which line, and
   what the code now does on the new build (a SWIG proxy accepts an assignment to a dead name
   silently, so the call runs on the default while the tool reports what was asked - the worst
   case). For each new family, say what it supersedes in the server, and name the tool that
   should shrink or go: code that wraps the API to steer an agent around a pitfall is expensive
   to reason about and to maintain, so a native factory that replaces a composed workaround is a
   deletion, not an addition.
8. Review and update commands/mcpServer/UNSUPPORTED_API.md, in both directions.
   - Every row against the installed build and the code: the member still exists; it still carries
     its mark (`tests/api_inventory.py` reads the marks; a mark can sit on the member, on its class
     or on a base class); the tools the row names still use it; what the row says the tool would
     lose is still what it would lose. A member that lost its mark, or gained a supported sibling,
     is a candidate to leave the list: measure the sibling before saying it replaces anything.
   - Every use against the rows: scan the tool code for marked members. A scan by member name is
     only a lead list, because a name is marked on one class and plain on many others; confirm each
     hit by reading which class the code holds. A confirmed use with no row is a finding.
   - Hold each use to the page's own rules. A use the page does not allow (a mark outside an
     exempted family, a retired member whose supported replacement works, a kept retired call with
     no comment at its point of use saying a supported way is sought) goes in the report as a
     finding for a dev agent and the owner; you do not remove the code.
   - Edit the page in your audit checkout so that it matches what the code does today: add the
     missing rows, drop the dead ones, correct the rest, and keep its wording plain and ASCII. Hand
     the lead the diff with the report. The page records use; it never grants it. A row you add
     for a use nobody approved says so in the report.
9. Report to outputs/api-sweep-<version>.md with these sections: installed; what is new (by
   family, with the measured contract of each factory a wave would use: signature, defaults,
   units, effect); what changed or was removed, as a table of change / where we depend on it /
   effect; measured behaviour changes with the probe evidence; unsupported, preview and retired
   use, as a table of rows added / dropped / corrected and the findings from step 8; state of the
   tests and fakes; what to change, in order, with the code to delete named beside the code to
   add; wave candidates. Pure ASCII. Numbers in tables. No history, no process narrative.
10. Hand off: the report is the deliverable, with the UNSUPPORTED_API.md diff and a proposed
    backlog block (rows in the ledger's style: ID (priority, found how), the measured fact, the
    fix, the live row) at the end of the report. Do not edit plans/backlog.md, tool code or tests.

When you are briefed only to review that page (a wave added or dropped a marked use, no Fusion
update), run step 8 alone and report its table and findings; it needs no Fusion call unless a
replacement has to be measured.

## Rules that cost the most when broken

- One Fusion driver at a time, reads included: no call without a lease from whoever briefed you;
  post before the measure run and before probes, and post the release with the open documents.
- A member marked preview is listed in the report and never called, not even in a probe, unless
  UNSUPPORTED_API.md exempts its family. Never launch tests/live/evals/proctor.py (it switches hubs
  by itself and can park Fusion behind a save dialog). Never dismiss a dialog; report it.
- Fusion dialogs and crashes are platform issues: report them, build nothing around them.
- A dialog during a probe means stop, hold the lease, and post its text with the open documents.
- Do not trust a claim you did not measure on the installed build, including your own memory of an
  older build; the previous build's facts are what the audit is testing.
