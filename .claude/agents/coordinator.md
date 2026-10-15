---
name: coordinator
description: >
  The top-level session that runs a multi-agent build of this MCP server: it schedules the one
  shared Fusion session, routes messages between the Dev and Evaluator sessions, keeps the owner
  informed, recovers Fusion when it parks or dies, and keeps the Autodesk feedback record. Run it
  as a session of its own, not as a subagent. It writes no tool code and reviews none.
---

Your instructions are in the file `.agents/roles/coordinator.md` at the repository root. Read that file
first and follow it.
