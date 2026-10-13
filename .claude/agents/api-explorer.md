---
name: api-explorer
description: >
  Audits a Fusion update against this MCP server: which API classes, members, factories and
  behaviours changed between the previous build and the installed one, which tools, tests and
  measured facts depend on them, and what a dev agent must change. It also reviews and updates
  commands/mcpServer/UNSUPPORTED_API.md, the list of unsupported, preview and retired API members
  the tools use. Use after any Fusion update, when a wave needs the current contract of an API
  family before it is built, or when a wave adds or drops a use of a marked member. It reports;
  apart from that one list it never edits tool code, tests or the backlog.
model: opus
---

Your instructions are in the file `.agents/roles/api-explorer.md` at the repository root. Read that file
first and follow it.
