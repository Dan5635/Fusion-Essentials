# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Client adapters for the cold self-test: how one agent CLI is launched blind and how its event
stream becomes call rows. Everything outside this file is the same for every client.

An adapter answers launch() with the command, the environment and a reason it cannot start, and
reader() with an object whose feed(line) returns the call rows one stream line completes. A reader
also carries `model` (what the client says it ran) and `not_blind` (why the launch held more than
the Fusion tools, when the client's own start record shows it)."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time

from grader import call_row

SERVER = "fusion-essentials"
MCP_PREFIX = f"mcp__{SERVER}__"

# Features a stock Codex run is launched without, so the child holds the Fusion tools and nothing
# else: no shell, no browser, no other agents, no plugins, no host skills.
_CODEX_OFF = ("shell_tool", "unified_exec", "plugins", "apps", "hooks", "multi_agent",
              "multi_agent_v2", "browser_use", "computer_use", "image_generation", "view_image",
              "skill_search", "skill_mcp_dependency_install", "unbounded_connection_retries")


class _CodexReader:
    """Codex states each finished call on one line; its stream carries the client's verdict
    (status), not the raw isError flag, and no list of the tools the child held."""
    model = None
    not_blind = ""
    said = ""

    def feed(self, line):
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            return []
        if isinstance(record, dict) and record.get("type") == "turn.failed":
            # The client's own last word when the turn could not run (the model refused, no login).
            self.said = " ".join(str((record.get("error") or {}).get("message") or "").split())
            return []
        item = record.get("item") if isinstance(record, dict) else None
        if not isinstance(item, dict) or record.get("type") != "item.completed":
            return []
        if item.get("type") != "mcp_tool_call" or item.get("server") != SERVER:
            return []
        return [call_row(item.get("tool"), item.get("arguments"), item.get("result"),
                         failed=item.get("status") != "completed")]


class Codex:
    name = "codex"
    executable = "codex"
    reader = _CodexReader

    def launch(self, exe, mcp_url, cwd, run_dir, model, environ):
        """(command, environment or None to inherit, why not): the task goes to its stdin."""
        argv = [exe, "exec", "--ephemeral", "--json", "--ignore-user-config", "--skip-git-repo-check",
                "--sandbox", "read-only", "--color", "never", "-C", cwd,
                "-c", f'mcp_servers.{SERVER}.url="{mcp_url}"',
                "-c", f"mcp_servers.{SERVER}.required=true",
                "-c", f'mcp_servers.{SERVER}.default_tools_approval_mode="approve"',
                "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"',
                "--enable", "skip_host_skill_discovery"]
        for feature in _CODEX_OFF:
            argv += ["--disable", feature]
        if model:
            argv += ["--model", model]
        return argv + ["-"], None, ""


# With only this server configured, the client's resource readers and its wait-for-servers tool
# reach nothing but this server, so they are part of the same surface.
_SAME_SERVER_TOOLS = frozenset({"ListMcpResourcesTool", "ReadMcpResourceTool", "ReadMcpResourceDirTool",
                                "WaitForMcpServers"})
# Built-in tools Claude Code start records have listed beside the Fusion tools. Denying them by
# name is a second layer only: each run's own start record decides whether it was blind.
_CLAUDE_OFF = ("Bash", "PowerShell", "Read", "Grep", "Glob", "Edit", "Write", "NotebookEdit",
               "WebFetch", "WebSearch", "Task", "Agent", "TodoWrite", "Skill", "ScheduleWakeup",
               "Monitor", "SendMessage", "Workflow", "Artifact", "CronCreate", "CronDelete",
               "CronList", "TaskOutput", "TaskStop", "DesignSync", "EnterWorktree", "ExitWorktree",
               "PushNotification", "RemoteTrigger", "ReportFindings")


class _ClaudeReader:
    """Claude Code states a call in an assistant event and its result in a later user event, and
    opens the stream with a start record listing the model, the servers and every tool held.
    `said` is the client's own message when it ended the run on an error (a usage limit, a login)."""

    def __init__(self):
        self.model = None
        self.not_blind = "the client's stream held no start record"
        self.said = ""
        self._pending = {}

    def _start(self, record):
        # A server can still read 'pending' here, with its tools not listed yet; the built-in
        # tools and the server names are complete.
        self.model = record.get("model")
        servers = [row.get("name") for row in record.get("mcp_servers") or [] if isinstance(row, dict)]
        tools = [tool for tool in record.get("tools") or [] if isinstance(tool, str)]
        other = sorted(t for t in tools if not t.startswith(MCP_PREFIX) and t not in _SAME_SERVER_TOOLS)
        if servers != [SERVER]:
            self.not_blind = f"the client's servers were {servers}"
        elif other:
            self.not_blind = "the client also held " + ", ".join(other)
        else:
            self.not_blind = ""

    def feed(self, line):
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            return []
        if not isinstance(record, dict):
            return []
        if record.get("type") == "system" and record.get("subtype") == "init":
            self._start(record)
            return []
        if record.get("type") == "result" and record.get("is_error"):
            self.said = " ".join(str(record.get("result") or "").split())
            return []
        content = (record.get("message") or {}).get("content")
        rows = []
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            name = str(block.get("name") or "")
            if block.get("type") == "tool_use" and name.startswith(MCP_PREFIX):
                self._pending[block.get("id")] = (name[len(MCP_PREFIX):], block.get("input"))
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in self._pending:
                tool, arguments = self._pending.pop(block["tool_use_id"])
                said = block.get("content")
                if isinstance(said, str):
                    said = [{"type": "text", "text": said}]
                rows.append(call_row(tool, arguments, {"content": said, "isError": bool(block.get("is_error"))}))
        return rows


class Claude:
    name = "claude"
    executable = "claude"
    reader = _ClaudeReader
    credentials = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    token_seconds = 1800

    def _login(self, environ, now=None):
        """({variable: token} to add, why not): a key or token already in the environment passes
        through; otherwise the access token the client keeps in its credentials file."""
        if environ.get("ANTHROPIC_API_KEY") or environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return {}, ""
        remedy = ("Sign the client in ('claude login'), or set CLAUDE_CODE_OAUTH_TOKEN (from 'claude "
                  "setup-token') or ANTHROPIC_API_KEY, then rerun.")
        try:
            with open(self.credentials, encoding="utf-8") as fh:
                oauth = json.load(fh).get("claudeAiOauth") or {}
        except (OSError, ValueError):
            return {}, f"no client login was found at {self.credentials}. {remedy}"
        token, expires_ms = oauth.get("accessToken"), oauth.get("expiresAt")
        left = (expires_ms or 0) / 1000.0 - (time.time() if now is None else now)
        if not token or left < self.token_seconds:
            return {}, f"the client's saved login has under {self.token_seconds // 60} minutes left. {remedy}"
        return {"CLAUDE_CODE_OAUTH_TOKEN": token}, ""

    def launch(self, exe, mcp_url, cwd, run_dir, model, environ):
        """(command, environment, why not): the task goes to its stdin. The child gets a config
        folder of its own, so no memory, settings or skills of the person running it come along."""
        login, why_not = self._login(environ)
        if why_not:
            return None, None, why_not
        config = os.path.join(run_dir, "mcp.json")
        with open(config, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"mcpServers": {SERVER: {"type": "http", "url": mcp_url}}}, fh)
        argv = [exe, "-p", "--mcp-config", config, "--strict-mcp-config", "--tools", "",
                "--disable-slash-commands", "--allowedTools", MCP_PREFIX + "*",
                "--disallowedTools", ",".join(_CLAUDE_OFF),
                "--output-format", "stream-json", "--verbose", "--max-turns", "300"]
        if model:
            argv += ["--model", model]
        env = dict(environ, **login)
        env["CLAUDE_CONFIG_DIR"] = os.path.join(run_dir, "client-config")
        # Deferred tool loading has started children that held no Fusion tool at all.
        env["ENABLE_TOOL_SEARCH"] = "false"
        env.setdefault("MCP_TIMEOUT", "60000")
        os.makedirs(env["CLAUDE_CONFIG_DIR"], exist_ok=True)
        return argv, env, ""


CLIENTS = {Codex.name: Codex(), Claude.name: Claude()}


def find(name, path=None):
    """(adapter, executable path, version line) for a client, or (adapter, None, why not). With no
    name it is the one client found on PATH."""
    if name is None:
        present = [n for n, adapter in CLIENTS.items() if shutil.which(adapter.executable)]
        if len(present) != 1:
            return None, None, ("no agent client was found on PATH; pass --client and --client-path"
                                if not present else
                                f"{' and '.join(present)} are both installed; pass --client")
        name = present[0]
    adapter = CLIENTS[name]
    exe = path or shutil.which(adapter.executable)
    if not exe or not os.path.isfile(exe):
        return adapter, None, (f"the {name} client was not found"
                               + (f" at {path}" if path else " on PATH; pass --client-path"))
    try:
        shown = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
        version = (shown.stdout or shown.stderr).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError) as exc:
        return adapter, None, f"{exe} --version did not answer: {exc}"
    return adapter, exe, version


def start(argv, cwd, stderr, env=None):
    """The child process, started so that kill_tree can reach everything it spawns."""
    group = {} if sys.platform == "win32" else {"start_new_session": True}
    return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=stderr, **group)


def kill_tree(process):
    """Stop the child and every process under it; a kill of the CLI alone leaves the model's own
    child alive and holding the MCP connection."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
