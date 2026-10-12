# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""A small wire client for the cold self-test: where the server is, and one call at a time.

Standard library only. It does not import the sweep's verify_core, which fixes the address to the
default port and writes files when imported."""

import importlib.util
import json
import os
import platform
import urllib.request

from grader import call_row

SERVER_NAME = "Fusion-Essentials MCP Server"
ENV_URL = "FUSION_ESSENTIALS_MCP_URL"
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _by_path(name, *parts):
    """One of the add-in's own modules, loaded by path so nothing else of the add-in is imported."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(_REPO, *parts))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def endpoint():
    """The add-in's endpoint module: host, default port, path and the port setting's name."""
    return _by_path("fusion_essentials_endpoint", "commands", "mcpServer", "endpoint.py")


def settings_port(home=None, system=None):
    """The mcp_port in the add-in's settings file when this checkout IS the installed add-in, else
    None. The directory rule is shared_state.get_settings_directory's."""
    config = _by_path("fusion_essentials_config", "config.py")
    folder = f"{config.COMPANY_NAME}_{config.ADDIN_NAME}"
    home = home or os.path.expanduser("~")
    system = system or platform.system()
    if system == "Windows":
        directory = os.path.join(home, "AppData", "Roaming", folder)
    elif system == "Darwin":
        directory = os.path.join(home, "Library", "Application Support", folder)
    else:
        directory = os.path.join(home, "." + folder)
    try:
        with open(os.path.join(directory, "FusionEssentialsSettings.json"), encoding="utf-8") as fh:
            setting = json.load(fh)[folder + "_MCP"]["settings"][endpoint().PORT_SETTING]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    port, _why = endpoint().configured_port(setting)
    return port


def base_url(port=None, url=None, environ=None):
    """(base url, where it came from): --url, --port, the environment, the add-in's settings file,
    then the shipped default."""
    environ = os.environ if environ is None else environ
    ep = endpoint()
    if url:
        return url.rstrip("/").removesuffix(ep.MCP_PATH), "--url"
    if port:
        return f"http://{ep.HOST}:{int(port)}", "--port"
    if environ.get(ENV_URL):
        return environ[ENV_URL].rstrip("/").removesuffix(ep.MCP_PATH), ENV_URL
    saved = settings_port()
    if saved:
        return f"http://{ep.HOST}:{saved}", "the add-in's settings file"
    return f"http://{ep.HOST}:{ep.DEFAULT_PORT}", "the shipped default port"


class Wire:
    def __init__(self, base):
        self.base = base
        self.mcp = base + endpoint().MCP_PATH
        self.calls = 0

    def health(self):
        """The /health body."""
        with urllib.request.urlopen(self.base + "/health", timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post(self, method, params):
        request = urllib.request.Request(
            self.mcp, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                       "params": params}).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))

    def tool_names(self):
        """The names tools/list answers with."""
        rows = (self._post("tools/list", {}).get("result") or {}).get("tools") or []
        return sorted(row["name"] for row in rows if isinstance(row, dict) and row.get("name"))

    def call(self, tool, arguments):
        """One tools/call as a call row; a JSON-RPC error is a failed row carrying its message."""
        self.calls += 1
        out = self._post("tools/call", {"name": tool, "arguments": arguments})
        if "error" in out:
            message = (out["error"] or {}).get("message", str(out["error"]))
            return call_row(tool, arguments, {"content": [{"type": "text", "text": message}]},
                            failed=True)
        return call_row(tool, arguments, out.get("result"))
