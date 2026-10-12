# The cold self-test

One command that asks: can an agent that has never seen this server use it on your Fusion session?
It launches one fresh agent holding only the Fusion tools, gives it a small task, then reads what
the agent left in Fusion and grades it.

```
python tests/live/cold/selftest.py
```

## What you need

- Fusion running with the Fusion-Essentials add-in loaded.
- One agent client installed and signed in: Codex or Claude Code. With both installed pass
  `--client`; pass `--client-path` when yours is not on PATH. The run uses your own client login
  and your own usage. Claude Code is given a config folder of its own for the run, so it needs its
  saved login file, `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`.
- Python 3.9 or newer. The script uses the standard library only.
- Nothing else. No cloud project, no settings file, no scripting tool, no extension.

The server is found through `--url`, `--port`, the `FUSION_ESSENTIALS_MCP_URL` environment variable,
the add-in's own settings file, then the shipped default port, in that order.

## What it does to your session

1. Reads the server's identity and the list of open documents. It refuses to start when an open
   document holds unsaved changes; save or close it, or pass `--accept-open-work`.
2. Launches the agent in an empty folder outside this repository, with the task in
   `packs/core/task.md` as its whole prompt. The agent creates two scratch documents and works only
   in those.
3. When the agent has finished, reads the results itself: the parameter, the active document, the
   sketch.
4. Closes, without saving, the documents the agent created. It knows them from the agent's own
   "new document" replies; a document that appeared during the run in any other way is left alone
   and reported. Then it makes the document that was active the active one again and compares the
   open documents with the list it took at the start. Any difference is printed before anything
   else. If the open documents cannot be listed completely it closes nothing more and says so; it
   never reports a clean session it could not read.

`--keep-open` skips step 4 so you can look at what the agent built.

## What the result means

Each of the three outcomes is graded PASS, FAIL or UNTESTED, and each check says whether it rests on
the script's own read after the agent finished or on the agent's recorded calls.

- UNTESTED means the run cannot count as a cold one: the agent never made a tool call (the client
  could not start or was not signed in), or the client's own start record shows it held more than
  the Fusion tools. The reason is in the result. It says nothing about the server.
- FAIL means a check did not hold. The script does not decide whose fault that is. It may be the
  agent's mistake, a tool that contradicted itself, or a limit of your Fusion licence. The run
  folder holds what is needed to tell: `transcript.jsonl` (every call the agent made),
  `reads.json` (the script's own reads), `admission.json` and `result.json`.

Exit code 0 is all PASS, 1 a FAIL, 2 not run or UNTESTED, 3 a session that differs from how it was
found.

## Before you share a run folder

`result.json`, `admission.json` and `reads.json` identify documents by session handle only. The
transcript records everything the agent read, and that includes the names of the documents you had
open. Read it before you attach it to an issue.

## Grading a recorded run

```
python tests/live/cold/selftest.py --replay RUN --replay-opening FILE --replay-reads FILE
```

grades a client's recorded event stream and a recorded list of reads without touching Fusion.
`--rename ColdLength=OtherName` maps a pack's fixed name onto the name a recorded run used.
