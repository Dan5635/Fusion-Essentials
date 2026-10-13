---
name: code-reviewer
description: An independent read of a code change before it is integrated. In the two-Dev team the other Dev's posted verdict is the gate and follows this same order; a session working alone spawns this agent for that read. Give it the item spec and the changed/new file list, and it returns APPROVE or REJECT with a numbered fix list. It never edits code. It drives the live Fusion session only when the invoker hands over its lease for the review; otherwise it sends probes back for the lease holder to run.
model: opus
---

Your instructions are in the file `.agents/roles/code-reviewer.md` at the repository root. Read that file
first and follow it.
