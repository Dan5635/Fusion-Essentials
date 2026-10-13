# Fusion-Essentials MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that lets an AI agent
(Claude, Codex, or any MCP client) work in your live Fusion session. It runs inside Fusion as part
of the Fusion-Essentials add-in, on your own machine, and it is **off by default**.

It gives the agent a couple of hundred small, typed tools instead of one "run this script" call:

- **Design:** sketches, solid and surface features, sheet metal, T-spline forms, meshes, plastic
  rules, reference images, parameters and the timeline.
- **Assembly:** components, joints, motion, interference and positions.
- **Manufacture:** setups, operations, tools, toolpaths, templates, posting and additive setups.
- **Documentation:** 2D drawings and model-based annotations.
- **Data:** documents, versions, external references and the cloud project structure.
- **Looking:** orientation reads, measurements, sections and screenshots, so the agent can check
  what it did.

Every tool does one job and assumes nothing about your process. A procedure is something you build
on top of these calls in your client, not something the server decides for you. Inputs are typed, so
a vague reference is refused rather than guessed at, and a tool that writes checks its own effect
before it reports success (see *What makes the tools trustworthy*).

## Why specific tools instead of "just let it write scripts"

Fusion has a Python API, and a capable model can write against it. Handing an assistant a single
"run this script" endpoint is a fair design, and it covers a lot of ground fast. This server went
the other way for one reason: writing the code was never the part that went wrong. Knowing whether
it had done the right thing was.

Working without checks, an LLM gets caught out in a few recurring ways.

**It gets a convention wrong.** Sketch planes, hole directions and pattern axes do not always line
up with the axes you would expect. A script built on the wrong assumption still runs, still reports
success, and quietly builds the wrong shape. Nothing in the result says so.

**It loses track of what it is pointing at.** References to faces and edges shift when a model
rebuilds, and Fusion does not require names to be unique anywhere. A reference that finds
*something* is not the same as a reference that finds the right thing.

**It cannot check its own work.** "Success" on its own proves very little, and the obvious sanity
checks (a count, a total volume) often cannot tell two quite different designs apart. An assistant
can verify what it did and still be wrong about it.

The tools are shaped around those three. Reads hand back the plane's orientation, the units and a
handle to the exact entity before you act on anything. Inputs refuse a vague reference rather than guess at
it. Anything that writes reads the model back afterwards and reports the change it measured. The
mechanisms are in *What makes the tools trustworthy*, below.

There is still a general script tool, `sys_execute_script`, for cases the others do not cover. It is
off by default and gated separately from everything else (see [Security](#security)). Most of the work here
exists so that you rarely need to reach for it.

## Enabling it

1. [Install and run Fusion-Essentials](../../README.md#installation) in Fusion.
2. Open **Fusion Essentials Settings**, and on the feature-enablement tab tick
   **Enable MCP Server**.
3. Reload Fusion-Essentials (`Ctrl+S` to open the Add-Ins dialog → Stop, then Run). The setting takes effect on reload.
4. Open `http://127.0.0.1:37182/health` in a browser and check both `"status": "healthy"` and
   `"server": "Fusion-Essentials MCP Server"`. The same page shows the address the server bound,
   under `"bound"`.
5. Point your MCP client at `http://127.0.0.1:37182/mcp` (next section).

To turn it off, untick **Enable MCP Server** and reload. Stopping the add-in also stops its server.

Optional tool **families** (`appearance`, `cam`, `data`, `drawing`, `form`, `mesh`, `pmi`, `render`,
`save`, `sheet`, `surface`) can each be disabled with a checkbox under **Settings → MCP Server**, to shrink the tool list an
agent has to load when you don't need that area. All families are enabled by default. A disabled
family takes effect on reload: its tools are not registered, and `workspace_orient`,
`sys_capability_map` and `sys_find_tool` reflect what is available. Reconnect your MCP client after
a reload so it refreshes its tool list.

## Connecting a client

Your LLM agent needs one thing from you: the address `http://127.0.0.1:37182/mcp`. The server speaks
MCP's **Streamable HTTP** transport, so an agent on the same machine speaks to it directly. There
is no bridge, Node package or extra program to install.

### The easy way: ask your assistant

An assistant that can edit its own settings will usually add the connection for you and tell you
what to restart afterwards. Open the one you want to use and say something like:

> Add an MCP server to this app. Name it `fusion-essentials`. It is a Streamable HTTP server at
> `http://127.0.0.1:37182/mcp` and needs no sign-in. Then tell me how to reload so its tools appear.

Claude Code and Codex can both do this: the agent finds the right settings file, makes the change
and walks you through whatever it cannot do itself. If you are not sure where your client keeps its
MCP settings, ask it that first.

### Doing it by hand

**Claude Code** (terminal, desktop app or editor extension). One command adds it:

```bash
claude mcp add --transport http fusion-essentials http://127.0.0.1:37182/mcp
```

If you opened this repository's folder in Claude Code, the connection is already offered: the
project file [`.mcp.json`](../../.mcp.json) at the repo root holds it, and Claude Code asks you to
approve it the first time.

```json
{
  "mcpServers": {
    "fusion-essentials": {
      "type": "http",
      "url": "http://127.0.0.1:37182/mcp"
    }
  }
}
```

**Codex.** Add this to `config.toml` in your Codex settings folder:

```toml
[mcp_servers.fusion-essentials]
url = "http://127.0.0.1:37182/mcp"
```

Inside this repository, [`.codex/config.toml`](../../.codex/config.toml) already names the server
and lists an approval mode for each tool.

**VS Code** (GitHub Copilot's agent mode). Create `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "fusion-essentials": {
      "type": "http",
      "url": "http://127.0.0.1:37182/mcp"
    }
  }
}
```

Keep that file open in the editor: VS Code 

**Any other client.** Add a Streamable HTTP server with the same URL, then approve or enable it in
the client if it asks.

### Check that it worked

Ask the assistant what you have open in Fusion. It should call `workspace_orient` and describe your
active document. If it says it has no such tool:

- Make sure the health page from *Enabling it* still answers. The page can be healthy while the
  client is not connected, so a healthy page is not the whole answer.
- Restart or reconnect the client. A client that was already running when you enabled the server,
  or when you changed its port, keeps what it knew until it is restarted.
- Look for an approval the client is waiting on. Some clients list a new server as pending until
  you allow it.

Before you let an assistant work unattended, read the client permission presets under [Security](#security).

### The port

Fusion-Essentials listens on `http://127.0.0.1:37182/mcp`. The port is its own (it does not share
Fusion's built-in port 27182), so Fusion's built-in MCP server and this one can run side by side and
neither has to be turned off. If your MCP client still points at port 27182, change the port in its
server URL once, or set `mcp_port` as below to keep another port.

To change the port (uncommon):

1. Open `FusionEssentialsSettings.json`. On Windows it is in `%APPDATA%\GTF_<add-in folder name>`
   (for example `GTF_Fusion-Essentials`); on macOS, in
   `~/Library/Application Support/GTF_<add-in folder name>`.
2. In the group whose `"name"` is `"MCP Server"`, find `"mcp_port"` and set its `"default"` to a free
   port between 1024 and 49151. The Settings dialog has no field for it.
3. Reload Fusion-Essentials (Add-Ins dialog → Stop, then Run) and use the new port in your MCP
   client's server URL.

The server only ever binds the port you set. If the value is not a whole number in that range, or
something else already answers on the port, the add-in shows a message saying what it found (another
Fusion session running Fusion-Essentials, another MCP server by the name it reports, or a listener it
could not identify) and does not start a server. Pick another `mcp_port` or stop the other program,
then reload.

## What the agent is told

You do not have to coach the assistant on how to use this. It learns it from the server, in three
places:

- **When it connects**, the server sends a short instruction block. It tells the agent to make two
  cheap reads before anything else: `sys_capability_map` (what this server can do, by tool family)
  and `workspace_orient` (what is open in Fusion and what state it is in). It also says how to
  search for a tool by keyword (`sys_find_tool`), that a `<family>_get` read returns a small default
  with more on request (`include=`), and that a write can be pinned to the document it was meant
  for (`expect_document`), so that it is refused if the active document has changed.
- **With each tool**, its description: what it does, what it needs and what to call next. That
  description is the whole of what an agent knows about a tool before using it.
- **In each reply**: a note saying what was observed and the next step, or an error naming the
  offending value and the remedy. What is awkward about Fusion is taught there, at the moment it
  applies, not up front.

Design practice, meaning how to build a part or an assembly well as opposed to which tool to call,
is not pushed at the agent. It is there to be asked for through `sys_get_guidance`: an index first,
then one section or one recipe per call.

## Tools

**The authoritative tool inventory is [`tests/generated/TOOL_MANIFEST.md`](../../tests/generated/TOOL_MANIFEST.md)**,
generated from the live registry (every tool, each with its inputs and write level). You can also
ask a connected client for its tool list (`tools/list`). Each tool's own `TOOL_DESCRIPTION` is the
contract the agent sees. Tool names are predictable: `<family>_<verb>`, so the family prefix tells
you the area:

| Prefix | Area | Examples |
|--------|------|----------|
| `workspace_` / `sys_` | orientation, discovery, guidance, and the script escape hatch | `workspace_orient`, `sys_capability_map`, `sys_find_tool`, `sys_execute_script` |
| `data_` | the cloud data model (projects, folders, files) | `data_get`, `data_upload_file`, `data_delete_file` |
| `doc_` | document lifecycle (open, save, copy, insert, versions) | `doc_open`, `doc_save_as`, `doc_insert_occurrence` |
| `design_` | the active design as a whole (tree, timeline, mode, plastic rules, reference images) | `design_get`, `design_edit_timeline`, `design_edit_plastic_rule`, `design_edit_reference_image` |
| `param_` | parameters | `param_get`, `param_set`, `param_add` |
| `sketch_` | 2D and 3D sketching, constraints, dimensions, text | `sketch_create`, `sketch_add_geometry`, `sketch_constrain` |
| `model_` | solid features, edits to existing features, measurement | `model_extrude`, `model_fillet`, `model_create_rib`, `model_edit_feature`, `model_measure_between` |
| `surface_` | surface modelling | `surface_patch`, `surface_trim`, `surface_thicken` |
| `form_` | T-spline form bodies | `form_create`, `form_edit`, `form_get` |
| `mesh_` / `save_` | mesh bodies: insert, query, repair, convert, export | `mesh_insert`, `mesh_find`, `mesh_to_brep`, `mesh_export`, `save_as_mesh` |
| `sheet_` | sheet metal: rules, convert, flange, hem, rip, join, fold, flat pattern (fold, unfold, refold and join-by-bend ride Fusion's preview API, which Autodesk may change) | `sheet_convert`, `sheet_create_flange`, `sheet_edit_rule`, `sheet_create_flat_pattern` |
| `find_` | geometry queries returning handles | `find_geometry` |
| `joint_` | joints and joint origins | `joint_create`, `joint_at_geometry`, `joint_drive` |
| `assembly_` | positioning and kinematic state | `assembly_get`, `assembly_ground`, `assembly_inspect_interference` |
| `appearance_` | colour and appearance | `appearance_set` |
| `view_` | workspace and viewport (screenshots, isolate, section) | `view_screenshot`, `view_set`, `view_section` |
| `cam_` | manufacturing (setups, operations, tools, toolpaths, posting) | `cam_get`, `cam_create_operation`, `cam_generate`, `cam_post` |
| `drawing_` | 2D drawings | `drawing_create`, `drawing_dimension`, `drawing_export` |
| `pmi_` | model-based annotations (notes, leaders, GD&T) | `pmi_get`, `pmi_create`, `pmi_edit` |

Tool definitions expose `readOnlyHint` and, for destructive tools, `destructiveHint` annotations.
These describe behavior; the client's permission policy determines whether it asks before a call.

### A few core tools


- **`workspace_orient`**: the first call. One call reports what's open, its health, whether CAM
  data exists, the major pieces, and *pointers* to the right narrow tool next.
- **`assembly_get`**: kinematic state as JSON: every occurrence's world position, ground flags, and
  joint wiring. The numbers you reason about instead of a cluttered screenshot.
- **`find_geometry`** → **`joint_at_geometry`**: `find_geometry` returns *handles* to faces and
  edges (filterable by radius or proximity); you pass a handle to a consumer like
  `joint_at_geometry`, which lands the joint at that exact geometry. A handle lasts for the
  session: find the geometry again after a reload or after reopening the document.
- **`view_set`** + **`view_screenshot`**: the agent's "eyes": isolate and orient a single
  component, then capture it (a screenshot of a whole assembly is the least reliable input).
- **`sys_execute_script`**: the gated escape hatch: arbitrary Fusion Python, off by default
  (see Security).

### Things that aren't obvious from a tool's name

- The CAM tools read CAM data **without requiring you to switch to the Manufacture workspace**.
- `doc_open` and `doc_save_as` are **asynchronous**: the call returns before the document is fully
  active or saved. Confirm with `workspace_orient` or `doc_get` afterward.
- `cam_get(include=['time'])` needs generated toolpaths to be meaningful.
- `cam_generate` is fire-and-poll: it returns immediately with a handle; poll `cam_get_status`
  until done (it never blocks for the multi-minute compute).

## What it gets used for

The same tools serve three different jobs:

- **A repeatable procedure.** A skill in your client runs a fixed sequence where the order matters
  and you want the same result every time. The steps and the checks live with you, outside the
  server, and the tools underneath stay general.
- **Open-ended modelling.** The assistant gets its bearings, reads the state, does something, checks
  what actually happened, and decides what to do next. That is closer to how a person works than one
  long script that either succeeds or leaves you reading a stack trace.
- **Reading, auditing and data work.** Checking a design's health, its parameters, its external
  references or its CAM setup; walking the cloud project structure; answering questions across a
  pile of files you would otherwise open one at a time. Much of this never writes anything, and it
  is where an assistant tends to earn its keep first.

Two runnable demonstrations show the tools driving real work end to end:

- **A shipped procedure** (a Claude Code skill in `.claude/skills/`): `insert-into-template` sets
  up a CAM job for a part. It saves the CAD, defines a part-space origin, places the shop template,
  inserts and positions the part, and sizes stock from measurements. It is built entirely from
  these tools; fork it as the pattern for your own shop procedures.
- **The eval pipeline** (`tests/live/evals/scenarios/`): design briefs (parametric multi-part
  foundations, joints and motion, detail features, external references, CAM templating) that a
  fresh agent, with nothing but these tools, runs on a live session. They check that the tool
  descriptions alone get an agent from a goal to a checked result.

## What makes the tools trustworthy

Three pieces of code make a false success hard to return. Study them if you fork this for your own
MCP server:

- **Inputs** ([`tools/_inputs.py`](tools/_inputs.py)): a tool never takes a bare `name: str` for
  existing geometry. Typed kinds resolve names and handles, refuse ambiguity instead of guessing
  an instance, and recover a stale geometry handle from the kind and world position stored in it
  when exactly one entity matches.
- **Outputs** ([`tools/_outputs.py`](tools/_outputs.py)): a tool declares `RETURNS = [...]`
  (handles, URNs, names, verdicts); tests assert the handler returns the declared keys, and a read
  that returns a verdict gives a real boolean beside its measured evidence, never prose.
- **Postconditions** ([`tools/_assert.py`](tools/_assert.py)): a write tool declares
  verify-the-effect kinds; the tool framework re-reads the model after the change and turns a
  "success" that changed nothing into an error. Fusion does report success while changing nothing,
  which is why this layer exists. Where the effect is material, the evidence is geometric: a cut
  that removed no volume, a mesh trim that moved neither count nor area, a delete whose target
  still resolves. Each is an error carrying its measurements, never a false ok.

Two further habits run through every payload. **Honest reads**: a value that cannot be read is
published as null (or the key is absent), never a fabricated 0/False/echo of the request, so an
agent can always tell "measured as nothing" from "could not be measured". A partial success (a
joint created but a limit refused, a rename the platform declined) says exactly what landed.
**Identity by handle**: Fusion enforces no name uniqueness at any level (even two siblings can
share a full path), so structural reads emit each entity's `handle` (its entityToken), every
reference-taking input accepts it as the exact identity, and a name several entities answer to is
refused with the candidates' handles rather than silently matched.

The naming schema (`<family>_<verb>`, with the verb's read/write kind linted against the declared
write level), pure-ASCII wire strings, helper deduplication, and doc freshness are all enforced by
lints in `tests/`. Run `tests/check_all.py` with the
[contributor environment](../../CONTRIBUTING.md#contributor-setup-and-verification) for generator
checks, the suite and maintainer live acceptance. Generated inventories live in `tests/generated/`:
[`TOOL_MANIFEST.md`](../../tests/generated/TOOL_MANIFEST.md) (per-tool) and
[`TOOL_POINTER_MAP.md`](../../tests/generated/TOOL_POINTER_MAP.md) (how tools point to each other, plus a
self-audit of the guidance strings). Authoring conventions live in
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) and the `AGENTS.md` files beside the code.

## How it was built

Most of this server was written by AI agents working as a small team against one live Fusion
session, with a person deciding scope and reviewing the result. The way that team works is checked
in beside the code, so you can run it the same way on your own machine or borrow the parts that
suit you.

The team has four seats, each a separate agent session with its own role file in
[`.agents/roles/`](../../.agents/roles/):

| Seat | Role file | What it does |
|------|-----------|--------------|
| Coordinator | [`coordinator.md`](../../.agents/roles/coordinator.md) | Schedules the one Fusion session, passes messages between the others, recovers Fusion when it stalls, and reports to the owner. Writes no tool code. |
| Lead developer | [`dev.md`](../../.agents/roles/dev.md) | Picks a bounded batch of work, builds part of it, reads every line it accepts, integrates, runs the acceptance and commits. |
| Second developer | [`dev.md`](../../.agents/roles/dev.md) | Builds the rest of the batch in its own checkout and reviews the lead's code; the lead reviews its code in turn. |
| Evaluator | [`evaluator.md`](../../.agents/roles/evaluator.md) | Hands each finished batch to a fresh agent that has only the tools and a task, then grades what that agent actually built. |

The four seat descriptions are written to work with different clients. The seats have been held
by different agents at different times, and a client that does not load these files by name can be
given a file's text as its first message. The helper files further down carry Claude Code front
matter (a model and tool names) and may need adapting for another client.

A few rules carry most of the weight:

- **One driver at a time.** Fusion has one session and one main thread. An agent asks for it,
  the Coordinator reads which documents are open and grants it, and the agent gives it back with
  the same report. Nobody touches a document they did not create.
- **Measure before building.** Reading the API tells you what a call is named, not what it does.
  A claim about Fusion is checked with a small live script before any tool is designed around it,
  and the result is kept. The measured facts live in
  [`tests/live/VERIFIED_API_FACTS.md`](../../tests/live/VERIFIED_API_FACTS.md).
- **Two developers, each reading the other.** Work is exchanged as patches, and a review asks
  what the tool believes after it writes: was the effect read back, and could a call that did
  nothing still report success?
- **Run it for real before it lands.** Every changed behaviour is driven on the live session, then
  the whole tool surface is swept once ([`tests/live/VERIFIED_TOOLS.md`](../../tests/live/VERIFIED_TOOLS.md)
  is the receipt), and only then does the Evaluator's fresh agent try it cold.
- **A live failure narrows the tool.** When Fusion ignores an input or resets a setting, the tool
  stops offering it or says what to do instead. The check is not loosened to make the test pass.

Three kinds of helper are there for a developer to brief when a batch is wide enough to split:
another developer from [`dev.md`](../../.agents/roles/dev.md) for a scoped change,
[`code-reviewer.md`](../../.agents/roles/code-reviewer.md) for an independent read, and
[`api-explorer.md`](../../.agents/roles/api-explorer.md) for auditing a new Fusion build against the
tools. [`blind-evaluator.md`](../../.agents/roles/blind-evaluator.md) is a first-time-user run with
a deliberately narrow tool list. None of them is required; two developers reviewing each other is
the core of it.

To try it yourself you need Fusion signed in with this add-in loaded, one agent session per seat,
and a shared notes file the sessions use to talk to each other. A cloud project the agents may
save scratch files into is needed only for the cloud tests and the evals. The Coordinator's role file has the setup steps. The working notes,
evidence and private task list of the original team are not in the repository.

## Security

- **Local transport.** The server binds `127.0.0.1` and rejects non-loopback web origins. It has no
  authentication token and permits requests without an Origin header, so other local processes can
  connect. A connected AI client may send tool results to its model provider.
- **What is switched on.** The server is off by default and runs only while the add-in is running.
  Family checkboxes remove those tools on reload; they are independent of client permissions.
- **`sys_execute_script` is separately gated.** It lets a connected agent run
  arbitrary Python in your active Fusion session, including modifying or deleting
  your design. It is **disabled by default**; enable it only if you trust the agent
  and the client connecting to the server, via **Settings → MCP Server → "Allow AI scripts
  (unsafe)"** (then reload). Scripts can also
  access local files and network resources. The default execution path groups document changes into
  an undo transaction, but an error does **not** guarantee rollback; verify state afterward.
- **Read-only script option.** `sys_execute_script(read_only=true)` uses Fusion's `MCP.Execute`
  read-only context to reject design changes. It still permits file writes and still requires the
  script registration and client permission gates. Builds without that text command return an error.
  This is not a server-wide read-only mode or a Python sandbox.
- **Document guard.** When supplied, `expect_document` refuses a write when the active
  document differs from the target. This checks identity, not permission to write.
- **Client policies differ.** [`.claude/settings.json`](../../.claude/settings.json) allows the listed
  read tools and leaves writes out of its allow list.
  [`.codex/config.toml`](../../.codex/config.toml) sets `approve` for listed typed tools, including
  writes; cloud file/folder deletion and `sys_execute_script` use `prompt`, as do unlisted tools.
  These project files apply only when the client loads them, and other client settings can change the
  effective policy. Inspect the active policy before use; a tool annotation is not an approval gate.
  Keep personal Claude overrides in the ignored `.claude/settings.local.json` file.

## Platform support

Developed and tested on **Windows**, using Fusion's embedded Python. No separate server runtime
or package installation is needed. The manifest lists macOS too, but it is untested there, including
script execution and the settings UI.

The tools were verified on Windows with Fusion 2706.0.116 from the Insider (pre-production)
channel; [`tests/live/VERIFIED_TOOLS.md`](../../tests/live/VERIFIED_TOOLS.md) names the build of
the latest sweep. The public release channel is untested, and a tool may rely on an API member that
channel does not have yet. Contributor commands and their dependencies are in
[`CONTRIBUTING.md`](../../CONTRIBUTING.md).
