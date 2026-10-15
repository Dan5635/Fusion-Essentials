# Evals: hand a design brief to a blind agent and look at what it built

An eval is a scenario file under `scenarios/`: a brief a capable designer would be given, sent
verbatim to an agent that holds only the Fusion MCP tools. The proctor (`proctor.py`) stages the
document, runs the agent, saves the result into your project, takes a screenshot, and records the
run. It grades nothing. You open the saved document beside the agent's report and judge it.

The CAM chain (scenarios C0_CAM-Fixture through C7_CAM-Job-End-to-End) has its own run order,
coverage placement and results convention in CAM-CHAIN.md beside this file.

## Running one

```
py -3 tests/live/evals/proctor.py S13_Surfaced-Bottle
py -3 tests/live/evals/proctor.py S13_Surfaced-Bottle --runs 3 --model opus
```

It needs:

- Fusion up with the add-in loaded (its MCP server on 127.0.0.1:37182, the default `mcp_port`);
- the `claude` CLI on PATH with a login the executor can use (a `claude login` on Windows or Linux,
  or `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, or `ANTHROPIC_API_KEY`, on any platform);
- the untracked `tests/live/cloud_config.local.json` naming your hub, project and folder (the
  proctor prints the file's shape when it is missing).

`py -3` is the Windows launcher; use `python3` elsewhere.

## Evaluator launch options

The evaluator's evidence and isolation requirements are in
[evaluator.md](../../../.agents/roles/evaluator.md). A fresh-process command-line launch has used
`codex exec --ephemeral --json --ignore-user-config --skip-git-repo-check --sandbox read-only
-C <new empty directory> -c mcp_servers.fusion-essentials.url="<server url>"`, with the task on
stdin. The command alone does not establish blindness: the launcher must also withhold shell,
other plugins/agents and repository access, expose the full Fusion tool list, and record the
actual startup configuration. Record the default model actually resolved when the runner exposes
it; otherwise a launch without a model override leaves that default unattested.

The proctor stages a document, launches a Claude Code executor with only the Fusion tools, and
saves the result into the scratch project. Its fixed preamble is retained in the run's prompt
bytes. A launcher given a role-file pointer starts a separate seat with that file as its brief;
the seat, not this helper instruction, owns the candidate's cold check.

The `blind-evaluator` subagent is an alternative for an intentionally narrower evaluation. Its
restricted tool list withholds scripting, reload and preference tools, so it does not qualify as
a candidate's full-list cold check. Start it with the entire
[blind-evaluator.md](../../../.agents/roles/blind-evaluator.md) text followed by the task, since it
cannot read a file pointer. A separately labelled assisted attempt never replaces its original
unassisted result.

The seat needs a running signed-in Fusion with the add-in loaded, the current server URL, an
installed signed-in runner, the channel file, the operator's `tests/live/cloud_config.local.json`,
an admitted scratch project, and the frozen task, checks and loaded-code identity from the lead.

The proctor makes the configured hub active, finds the project (creating it and saying so when it is
missing), and makes one cloud folder per eval set, `Eval-<date>-<set>` under your folder, where
every document a run saves or starts from lives. `--set NAME` lets a chain share one folder: S2a
opens the newest `S1_Foundation_<nn>` in its set, S2b the newest S2a output, and so on (each
scenario's `fixture:` names the stage it starts from). A scenario with `fixture: none` starts from a
new document the proctor reads back empty.

Every run lands in `results/<set>/<scenario>_<nn>/`: `prompt.txt` (the exact bytes sent),
`transcript.jsonl`, `report.txt` (the agent's final message), `iso.png`, and `run.json` (calls,
output tokens, how the run ended, the saved document's URN and web link). One line per run is
appended to `results/index.md`. The saved document is named `<scenario>_<nn>` in the set folder.

The agent is launched with every built-in tool of the CLI switched off, and the run ends at its
first line, as `blocked init`, when the CLI's own start record lists a second server or any tool
that is not the Fusion server's. `run.json` keeps that record under `start`: the CLI version, the
model it resolved, the server's status and the tools held beside the Fusion ones. A run the CLI
ended itself (a usage limit, a lost login) carries the CLI's message in `ended`.

## A/B

Three axes, one switch each, all recorded in `run.json` and the index:

- **The prompt.** A variant is another scenario file: `S13_Surfaced-Bottle.B.md` beside the
  original, same `id:` in its frontmatter, a different `## Prompt`. Run both, compare the documents.
- **The tooling.** `--deny mcp__fusion-essentials__<tool>` withholds one tool for a run (to see
  whether the run needs that tool).
- **The harness.** `--model`; `--skill <name>` (appends a design-practice skill's body after the
  brief); `--tool-search` (the CLI defers tool schemas, a few per turn instead of all of them; the
  built-in tools stay on for it apart from the ones denied by name, the start record lists no
  Fusion tool yet and may read the server as pending, so nothing about tools is checked at start
  and `run.json` shows what was held); `--preamble <file>` (another
  harness-rules file, such as `preamble-lean.md`, which drops the cold-start reads). There is no
  switch for the CLI's thinking budget, and that budget does not limit how long a turn runs.
  `run.json` records the seconds at which every tool call landed, so a long first pause is visible.

## Scenario format

```
---
id: S13_Surfaced-Bottle
fixture: none
---

## Prompt

<the brief, sent verbatim; {{PROJECT}} and {{FOLDER}} are filled in>

## Grader notes

<never sent: what a good result looks like, which axis the scenario discriminates, the first A/B
to run on it>
```

`preamble.md` carries the harness rules (only agent, only Fusion tools, cold start, end with a
report) and is prepended to every prompt, so the scenario files hold design briefs only.

## Watching a run

The proctor prints a heartbeat each minute with the tool-call count. No tool call for `EVAL_STALL_S`
seconds (default 600; a foundation-sized brief pauses over six minutes to plan before it builds)
kills the executor's process tree and records the run as stalled. A run is never retried by the
proctor; run it again.

Every run bills the account the CLI is signed into, on the model you pass, and each executor turn
carries the whole tool schema (about 135k cached input tokens). A long run is a real spend: run one
at a time, prefer `--model sonnet` for prompt A/B, and keep opus for capability questions.

## Privacy

A transcript captures workspace_orient output, which carries the hub name and project URNs; the
results tree is gitignored, never commit or paste it. The executor's login is your CLI's current
access token, handed over by environment for the run (never copied to disk); the proctor refuses to
start on a token with under thirty minutes left.
