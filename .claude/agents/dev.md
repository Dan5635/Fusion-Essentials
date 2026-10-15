---
name: dev
description: >
  A developer on this MCP server, in one of two ways. As a seat in the multi-agent build: the
  lead, which chooses the batch, reads all accepted code, integrates, runs acceptance and commits;
  or the second, which builds a lane in its own worktree and reviews the lead. Run a seat as a
  session of its own, on whichever coding agent the owner chooses, and tell it which seat it
  holds. Or as a helper a seat starts for one scoped change driven by a backlog row or brief: it
  builds, hands back a patch and a report, and never commits. Either way it carries this repo's
  working rules and drives Fusion only under a lease.
model: opus
---

Your instructions are in the file `.agents/roles/dev.md` at the repository root. Read that file
first and follow it.
