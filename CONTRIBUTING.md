# Contributing to Fusion-Essentials

This guide is for **developers** extending the add-in, mainly its MCP server. For **users**, see the
[README](README.md) and the [MCP Server README](commands/mcpServer/README.md). The code is the
authority on behavior; this guide explains why it is built this way and where each idea lives.

---

## How the MCP server works

**What MCP is here.** The add-in hosts a local [Model Context Protocol](https://modelcontextprotocol.io)
server inside Fusion. An AI agent connects over loopback and receives a list of *tools*, each a
`{name, description, inputSchema}`. The agent never sees the implementation; **the schema and
description are the API contract.** It picks a tool and calls it, and the server runs the tool's
handler on Fusion's main thread and returns a JSON result. (Launch and registration live in
`commands/mcpServer/entry.py`; the primitives in `commands/mcpServer/mcp_primitives/`.)

Follow these ideas when you add a tool. They let an agent drive Fusion predictably, with few calls
and few blind spots.

- **Tools are building blocks; skills compose them.** A tool is one verb (`model_extrude`,
  `assembly_get`). A *skill* (`.claude/skills/`) is a markdown procedure that chains tools into a
  repeatable workflow. Reliability comes from each step being a tested tool with its own guards, not
  from a brittle macro. If a workflow needs a capability no tool provides, **add a tool**; don't
  hand-roll `sys_execute_script` inside a skill.

- **Orient broadly, then drill in cheaply.** An agent arrives at a document knowing nothing about it,
  and reading an entire large design does not scale. So: one cheap broad read first
  (`workspace_orient`: what's open, its health, whether CAM exists, the major pieces, and *pointers*
  to the right narrow tool), then scoped reads on demand (`design_get` scoped to a component,
  `find_geometry(target=...)`, `assembly_get`). A new read tool should fit this shape, cheap and
  broad or scoped and deep, and say which.

- **Geometry-as-values.** An agent has no eyes, so selecting geometry by a snap string is ambiguous
  the moment a part has two cylinders. Instead, `find_geometry` returns each face, edge or vertex as
  a stable `entityToken` *handle* (filterable by radius or proximity: numbers, not pixels), and
  consumers take that handle through the `GeometryHandle` input kind. A face found in one call is
  passed to the next by its handle. `assembly_get` is the same idea for kinematic state (positions,
  grounding and joints as JSON, not a cluttered render).

- **Return the IDs the next call needs, unprompted.** A tool that creates or identifies something
  puts its stable id in the result even when not asked: `find_geometry` returns a handle, `doc_get`
  a data-model URN, `assembly_get` exact occurrence names, `model_inspect` measured extents. That is
  what makes a chain predictable: the next target is an id the previous step returned, not a name the
  agent hopes resolves.

- **Typed inputs and outputs carry the contract.** Two mechanisms in `_inputs.py` put dependencies
  and failure modes in code rather than prose. A typed **input kind**
  (`GeometryHandle`/`BodyRef`/`PlaneRef`/`AxisRef`/`Choice`/…) bundles schema, resolution,
  validation and an auto-generated contract line, so an input that needs a face can *only* take a
  handle, never a bare coordinate. A **`ModeGuard`** derives its error from the requirement, so a
  precondition refusal can't point the wrong way. On the output side, `_outputs.py` lets a tool
  declare `RETURNS = [...]` of typed **output kinds**
  (`ReturnsHandle`/`ReturnsUrn`/`ReturnsName`/`ReturnsValue`). They generate the description's
  `Produces:` line, and `test_output_contracts.py` checks that each declared key is spelled in the
  tool's source and named on that line. Where a tool's unit test also calls the kind's
  `assert_present` on a real payload, a renamed id field fails the suite instead of silently
  misleading every consumer that reads it. How a tool reports failure is the honesty contract in
  root [CLAUDE.md](CLAUDE.md).

- **The live add-in is a development surface.** `sys_reload_addin` hot-reloads without restarting
  Fusion, and `sys_get_api_doc` + `sys_execute_script` let you try an `adsk.*` call against the live
  API before committing it as a tool. A team can keep its own tools and skills on a fork: version
  controlled together, hot-reloadable, with risky tools behind their own setting.

**The layering** (innermost first): the base layer (`_common.py`: the `ok`/`error` contract, `safe`,
the design/component/sketch resolvers, unit scaling); the typed input and output kinds (`_inputs.py`
+ `_outputs.py`); the MCP primitives (`mcp_primitives/`: the `Tool` builder, the `Item` that binds a
primitive to its handler and execution metadata, the registry); and the tool module itself
(`tools/<domain_verb>.py`), which holds only domain logic. Read any one tool file (e.g.
`workspace_orient.py` or `find_geometry.py`) to see the whole pattern in one place.

> Most of these conventions are enforced: write-status is a structured annotation (linted),
> occurrence and geometry references are typed kinds that refuse ambiguity, and outputs are declared
> through `_outputs.py` with a lint that checks each declared key is spelled in the tool's source.
> A new enum input is a typed `Choice`/`UnitField` kind; the raw `enum` schemas already in the tools
> remain.

---

## Contributor setup and verification

Install, run, update and remove the add-in using the [README](README.md#installation). Fusion runs
the add-in with its embedded Python; running `Fusion-Essentials.py` in a terminal or installing an
unrelated `adsk` package does not give you a Fusion session. The Windows contributor commands below
use a separate Python 3.13 installation with the `py` launcher, pip and venv. Git is needed for a
contributor checkout; Node and a separately installed MCP SDK are not needed for these tests.

From the repository root in PowerShell, create an isolated environment without activating it:

```powershell
py -3.13 -m venv .cache/contributor-python
.\.cache\contributor-python\Scripts\python.exe -m pip install pytest numpy
.\.cache\contributor-python\Scripts\python.exe -m pytest tests/unit -q
```

On macOS or Linux the same three steps are, from a shell in the repository root:

```bash
python3 -m venv .cache/contributor-python
.cache/contributor-python/bin/python -m pip install pytest numpy
.cache/contributor-python/bin/python -m pytest tests/unit -q
```

Nobody has run them there yet, so treat a failure on those platforms as a finding to report, not
as a mistake in your setup.

From here on, `python` means that environment's interpreter
(`.cache/contributor-python/Scripts/python.exe` on Windows, `.cache/contributor-python/bin/python`
elsewhere); keep the same interpreter for every later command. Where another document writes
`py -3`, that is the Windows launcher for the same thing. Installing dependencies needs access to a Python
package source; the unit-test command itself runs offline, without Fusion or an MCP client.
`tests/conftest.py` supplies the fake `adsk` objects and the committed API facts. To iterate on one
tool, replace `tests/unit` with its test file. You do not need the coverage or eval tools for this:
`pytest` and `numpy` are the only packages the unit tests and lints import, and a `--no-cov` or
`--cov` flag copied from elsewhere works only after `pytest-cov` is installed.
Scratch files and task artifacts go in the gitignored `outputs/` directory (root
[CLAUDE.md](CLAUDE.md), "Planning files").

| Check | What it requires and establishes |
|---|---|
| `python -m pytest tests/unit -q` | Handler and framework regressions against fakes; no native geometry or live acceptance claim. |
| `python tests/check_all.py --offline` | Generator checks, full unit/lint suite and source-matched live receipt; still requires installed Fusion binding files. Only the final live gate is skipped. |
| `python tests/check_all.py` | Maintainer acceptance with installed bindings, a matching live receipt and a reachable, correctly loaded Fusion add-in. |

Plain `pytest` without the `tests/unit` path also collects lints that consult installed bindings.
A contributor without Fusion can submit the unit result and name the native checks still pending;
do not refresh or edit generated facts or receipts to make that checkout look live-verified.
Changing tool source invalidates the receipt until the maintainer loads and exercises that code.

The API-facts check (`measure_api --check`) fails after any edit to `tests/live/measure_api.py`
until a full live measurement run stamps the facts again. A full run rewrites
`tests/live/VERIFIED_API_FACTS.md` (the readable record of the run) and `tests/live_api_facts.py`
when every row reads PASS or CARRIED. A row that needs the Design or Manufacturing Extension reads
CARRIED on an install where the extension has lapsed: it keeps its last entitled measurement, its
cell names that measurement's date and build, and it is never relabelled PASS.
`test_fake_shapes_exist` and `test_enum_families_measured` read the regenerated facts module, so
they go red between a new measurement row and the full run that lands it.

Windows is the tested development platform. The manifest lists macOS too, but developing and
running on macOS are untested. Keep production code under `commands/mcpServer/` modular and
dual-licensed (MIT/Apache headers). Read [tests/CLAUDE.md](tests/CLAUDE.md) before adding tests and
the [tool-authoring guide](commands/mcpServer/tools/CLAUDE.md) before adding tools.

## Add-in command convention

- Each feature is a `commands/<name>/` package with an `entry.py` exposing module-level
  `CMD_ID`, `CMD_NAME`, and `start()` / `stop()`. The `__init__.py` files are empty; the
  real code lives in `entry.py`.
- Register a feature by adding it to the `commands` list in `commands/__init__.py`.
- IDs follow `f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_...'` (COMPANY_NAME = `GTF`).
- Settings: a module calls `shared_state.load_settings_init(GROUP_ID, name, DEFAULTS, icon)`
  to get its own Settings tab, and `shared_state.load_settings(GROUP_ID)` to read it back.
  The settings UI renders **every key in a group as a checkbox or dropdown**; there are no
  hidden fields, so do not store internal bookkeeping state in a settings group.
- Enablement and settings changes take effect on **reload**, not live (the live-toggle code
  in `commands/settings/entry.py` is commented out upstream).

## MCP server (`commands/mcpServer/`)

### Layout

- `mcp_server.py` (in `server/`) - HTTP + JSON-RPC server, **Streamable HTTP** transport (2025-03-26).
- `task_manager.py` (in `server/`) - marshals work onto Fusion's **main thread** via a custom event.
- `mcp_primitives/` - Tool / Item schema classes plus the registry.
- `tools/` - one module per tool, named exactly after the tool it registers (`<family>_<verb>.py`;
  `TOOL_MANIFEST.md` is the authoritative per-tool list). Each has a `register_tool()`, and most
  also bind at module level a `handler(...)` (the logic; its parameters are the tool inputs), a
  `TOOL_DESCRIPTION`, a `tool = Tool.create_...` and an `item = Item.create_tool_item(...)`.
  `_`-prefixed modules (`_common`, `_inputs`, `_outputs`, `_data_common`) are shared helpers.
- `entry.py` - starts and stops the server, runs the tool-discovery sweep, gates `sys_execute_script`.
- `README.md` (in that folder) - the **user-facing** doc (setup, security, platform).

### Hard rules (violating these causes crashes or hangs)

- **Anything touching `adsk.*` must run on Fusion's main thread.** Tools do this by setting
  `run_on_main_thread=True` on their `Item` (the default); the server marshals via
  TaskManager. Calling the Fusion API from a request or worker thread can crash Fusion.
- **Never block the main thread.** No `time.sleep`/polling loops and no synchronous HTTP in
  `entry.start()` or in a tool handler; they run on the UI thread. (That is why the port self-check
  runs on a background thread and `doc_open` does not poll.)

### Behavior that isn't obvious from the code

- The server binds **`127.0.0.1:37182`**, path **`/mcp`**. The default port is defined once, in
  `commands/mcpServer/endpoint.py`; the `mcp_port` setting overrides it and the live harness reads
  the same definition. Startup binds exactly that port and never tries a second one. When the bind
  fails, no server starts: the log says so at once, and a message box naming who answers on the port
  follows within about two seconds. When the bind succeeds but another server answers on the port,
  the add-in shows the same kind of warning and keeps serving. `/health` and `sys_capability_map`
  report the address the socket bound as `bound`.
- `doc_open` is **async**: `documents.open()` returns before the document is active.
- `sys_execute_script` uses Fusion's `Python.Run` text command. It is **Windows-tested only**;
  the temp-path handling normalizes `\`→`/` for cross-platform use but is **unverified on
  macOS**.
- **Never compare Fusion API objects with `is`.** The API returns fresh wrapper objects for the
  same underlying entity, so `occurrence.component is someComponent` silently fails, and an
  `is`-based resolver matches nothing (live-verified). Compare components with
  `_common.same_component`. `_common.native_identity` (the native token plus the source document's
  URN) identifies the physical entity; a bare entity token is document-local, and a name need not
  be unique. Placement identity also keeps the exact assembly context (the occurrence path),
  because native keys alone collapse repeated placements of one entity into one.
- **A Joint Origin inside a referenced or child occurrence must be joined via its assembly-context
  proxy**, not the native JO: `jo.createForAssemblyContext(occurrence)`. Passing the native JO
  yields "Provided input paths for joint are not valid". The `joint_create` tool resolves this
  automatically: a JO passed by bare name goes through `_joints.jo_assembly_proxy` (a root JO is
  used as-is; a sub-component JO is proxied through the one occurrence that places its component).

### The development loop (iterating without manual Fusion steps)

The add-in can restart *itself*, and that is what makes agent-driven tool development possible: an
agent can write a new tool, reload the server it is connected through, and exercise that tool
against the live Fusion session without a human ever opening the Add-Ins dialog. If you build your
own tools on top of this project, work in this loop:

1. Edit or add a `tools/*.py` file. A brand-new module is picked up too (verified): on reload, the
   `pkgutil` sweep discovers any `tools/*.py` that exposes `register_tool()`.
2. Call `sys_reload_addin`. It is deferred: it responds, then the server restarts in about 0.5 s.
3. Poll `GET http://127.0.0.1:37182/health` until the server is back.
4. Call `tools/list` to confirm.

No manual Stop/Run is needed. A manual Stop/Run in Fusion's Add-Ins dialog is only required if the
add-in failed to start, so that no server is running to call `sys_reload_addin` against.

An MCP **client** may cache the tool list, so a newly registered tool can be invisible to the client
until it reconnects. Reconnect the server in your client (`/mcp` in Claude Code) to refresh, or drive
it over raw HTTP meanwhile. The stale cache bites harder on an **edited** tool: the client serializes
arguments against its old schema snapshot, so a property it does not know about (a newly added array
input, say) can cross the wire silently mangled, a JSON array arriving as its string form, while
every other property works. That looks like a handler bug. After any schema change, reconnect the client
before exercising the tool.

### Driving the server from outside Fusion (for testing)

POST JSON-RPC to `http://127.0.0.1:37182/mcp` with header
`Accept: application/json, text/event-stream`. Example tool call:
`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"data_get","arguments":{}}}`.
Diagnostics: `GET /health`, `GET /tools`.

### Adding a new tool (the pattern)

1. Create `tools/<name>.py` with `handler(...)`, `TOOL_DESCRIPTION`, `tool`, `item`, and
   `register_tool()`. Registration is auto-discovered (a `pkgutil` sweep of `tools/` calls each
   module's `register_tool()`), so you do **not** edit `tools/__init__.py` or `entry.py`.
   `_`-prefixed modules are treated as shared helpers and skipped. `test_tool_autodiscovery.py`
   enforces this.
2. Resolve any input that refers to existing geometry, occurrences or bodies through a typed kind in
   `_inputs.py` (`GeometryHandle`/`BodyRef`/`OccurrenceRef`/`PlaneRef`/`AxisRef`/`Choice`/…)
   rather than a hand-rolled `name: str`; the kinds refuse ambiguity and self-heal stale handles.
3. Check every `adsk.*` call with `sys_get_api_doc` before writing it; it searches the installed
   build's real signatures and docstrings.
4. Write its test (see **Testing a tool** below), then `sys_reload_addin` and smoke-test it live.

### Auditing for dead code

`test_dead_code.py` flags unreferenced symbols and unused imports on every run. It matches by name,
so a dead symbol masked by a live one of the same name elsewhere is not flagged; unique names are
what let it prove a symbol dead. Unreachable branches need runtime evidence instead. Generate
candidates with branch coverage over the suite:

```powershell
.\.cache\contributor-python\Scripts\python.exe -m pip install pytest-cov
.\.cache\contributor-python\Scripts\python.exe -m pytest -q --cov=commands.mcpServer --cov-branch --cov-report=html
```

then review never-executed branches in `htmlcov/`. An uncovered branch is either dead code or a
missing test; fix whichever it is. This is a periodic audit, not a gate: coverage of live-API
wrapper paths is expected to be partial. The agent-facing surface has its own generated dead-tool
audit: the "Blindspots" section of [tests/generated/TOOL_POINTER_MAP.md](tests/generated/TOOL_POINTER_MAP.md)
(orphan tools, guidance pointing at tools that do not exist).

To check that a regression test can detect its intended defect, temporarily change the condition it
exercises, run that test, and restore the source. Use the procedure in
[tests/CLAUDE.md](tests/CLAUDE.md#prove-a-test-bites); `test_assert_strength.py` also rejects
assertions that rely only on a bare error flag.

### Testing a tool

Every tool module is unit-tested or carries a recorded excuse: `test_unit_coverage_complete.py`
reconciles the module list against the suite, so the decision is never silent. The tools run in a
live Fusion session, so the suite **mocks `adsk`** to exercise pure handler logic outside Fusion.
Mocks can't catch a wrong `adsk.*` signature, so geometry-touching tools are also
**live-validated** (`sys_reload_addin`, then call the handler on a real document).

- **Harness.** `tests/conftest.py` injects a lightweight mock `adsk` into `sys.modules` before any
  tool is imported, then `load_tool("<tool>")` spec-loads that one module in isolation and returns
  it, so a test can call `module.handler(...)` and its private helpers directly. The mocks model only
  what tools touch; when yours reads something unmodeled, extend the harness once rather than per
  test.
- **Fakes.** Build the design from the shared fakes in `tests/fakes/` and wire it in with
  `install(mod, design)` inside a fixture, never by assigning to the module's `app`.
  [tests/CLAUDE.md](tests/CLAUDE.md) says which pattern to copy, and
  [tests/README.md](tests/README.md) has the rules for the shared fakes. Assert on the JSON payload
  the handler returns (decode `result["content"][0]["text"]`) and on the exact `adsk.*` calls the
  fake captured, so a regression to a wrong method name or argument fails here.
- **Cover the guards too**: unknown units, no active design, out-of-range inputs, not just the happy
  path. The error contract (`isError`, `message`) is part of the tool's behavior.
- **Run it:** `python -m pytest tests/unit/test_<tool>.py -q` while iterating. Before calling any
  change done, run `python tests/check_all.py`; the table above and
  [tests/README.md](tests/README.md) say what it checks. Without a live session, `--offline` skips
  the final live gate. For the contributor route without Fusion, run `tests/unit` as above and
  report the remaining maintainer checks.
- **Changed tool source?** The receipt check fails until the live suite has seen your code. Reload
  the add-in so the live session runs the code you just edited, then run
  `python tests/live/tool_verify.py` with Fusion up. A green run rewrites
  `tests/live/VERIFIED_TOOLS.md`; commit it with your change. In the receipt, a `covered` tool had a
  step whose predicate read a value off the payload; a `called` tool only passed bare `ok` steps
  (the call did not fail, but nothing about its effect was read). A new step for an Edit tool should
  read the effect back, not just `ok`.
- **Regenerate the docs:** run `python tests/gen_all.py` whenever check_all says a generated file is
  stale; [tests/CLAUDE.md](tests/CLAUDE.md), "Regenerating docs", says what it rebuilds.
- **New adsk API?** If your tool references an enum family the generated `live_api_facts.py` has
  not measured, the suite goes red with the one command that fixes it: run
  `python tests/live/measure_api.py` with Fusion up, then commit the regenerated facts.
