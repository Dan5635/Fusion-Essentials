# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The MCP server's loopback endpoint: its default port, the port setting, and the bound address."""

HOST = '127.0.0.1'
# The one definition of the default port; the live harness loads this file by path to read it.
DEFAULT_PORT = 37182
MCP_PATH = '/mcp'

PORT_SETTING = 'mcp_port'
PORT_MIN = 1024
PORT_MAX = 49151

_bound = None


def configured_port(setting):
    """(port, None) for a usable mcp_port settings entry, else (None, why it is refused)."""
    value = setting.get("default") if isinstance(setting, dict) else None
    if type(value) is int and PORT_MIN <= value <= PORT_MAX:
        return value, None
    shown = value if isinstance(setting, dict) else setting
    return None, (f"The '{PORT_SETTING}' setting is {shown!r}. Its \"default\" must be a whole "
                  f"number from {PORT_MIN} to {PORT_MAX}; the shipped default is {DEFAULT_PORT}.")


def record_bound(address):
    """Record the (host, port) the running server's socket reports, or clear it with None."""
    global _bound
    try:
        host, port = address[0], address[1]
        _bound = {"host": host, "port": port, "mcp_url": f"http://{host}:{port}{MCP_PATH}"}
    except (TypeError, IndexError):
        _bound = None
    return bound()


def bound():
    """{host, port, mcp_url} of the running server's socket, or None when none is recorded."""
    return dict(_bound) if _bound else None
