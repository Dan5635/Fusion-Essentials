# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP Server command module for Fusion-Essentials.

Follows the Fusion-Essentials command convention (module-level CMD_ID / CMD_NAME
plus start()/stop()) so it participates in the settings-driven enablement loop in
commands/settings/entry.py. The enable checkbox for this module defaults to False
(see commands/__init__.py), so start() only runs when the user opts in and reloads.

start() hosts a local MCP server on 127.0.0.1, path /mcp, on the port the
'mcp_port' setting names (endpoint.DEFAULT_PORT unless the user changes it). The
port is this add-in's own, distinct from the one Fusion's built-in MCP server
uses, so both servers can run side by side. start() binds exactly that port: a
setting it cannot use, or a port something else answers on, is reported to the
user and nothing else is bound (see _configured_port / _report_listener).
"""

import importlib
import os
import pkgutil
import threading

import adsk.core

from ...lib import fusion360utils as futil
from ...lib import loaded_attestation
from ... import config
from ... import shared_state
from . import endpoint
from .server import mcp_server
from .server.task_manager import TaskManager
from .mcp_primitives import registry
from .mcp_primitives import GATEABLE_FAMILIES, GATED_TOOLS, family_of, unregister

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_MCP_Server'
CMD_NAME = 'MCP Server'
CMD_Description = (
    'Host a local Model Context Protocol (MCP) server so AI agents (e.g. Claude) '
    'can interact with your Fusion session. Off by default; loopback only.'
)

# Loopback only. The port comes from the 'mcp_port' setting, read once in start().
HOST = endpoint.HOST

# This module's own settings group (separate from the FEATURE_ENABLEMENT checkbox
# that gates the whole module). Gives the MCP server its own Settings tab where the
# high-risk execute_api_script tool can be toggled independently.
SETTINGS_ID = f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_MCP'
# The Settings tab's icon folder; the dialog draws the copy of this path the settings file holds.
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')
_ALLOW_EXECUTE_KEY = 'allow_execute_api_script'

# Tool modules that are NOT auto-registered by the pkgutil sweep in _collect_items(): each is
# registered explicitly, only when the user opts in, elsewhere in this file. Derived from
# mcp_primitives.GATED_TOOLS (the single source of truth also read by sys_capability_map) rather
# than a second hand-typed set here.
_GATED_TOOL_MODULES = frozenset(GATED_TOOLS)

DEFAULT_SETTINGS = {
    _ALLOW_EXECUTE_KEY: {
        "type": "checkbox",
        # High-risk: lets a connected AI run arbitrary Python in the live session.
        # The label's risk wording IS the consent signal (no separate dialog). Sourced from
        # GATED_TOOLS so sys_capability_map's gated-tool report can never quote a stale label.
        "label": GATED_TOOLS["sys_execute_script"],
        "default": False,
    },
    # One checkbox per GATEABLE_FAMILIES member, default True so an existing user's tool surface is
    # unchanged until they opt out. shared_state.load_settings_init merge-adds these keys for users
    # who already have a settings file (see shared_state.merge_settings), so upgrading is silent.
    "family_enabled_appearance": {
        "type": "checkbox",
        "label": "Enable appearance MCP tools",
        "default": True,
    },
    "family_enabled_cam": {
        "type": "checkbox",
        "label": "Enable cam MCP tools",
        "default": True,
    },
    "family_enabled_data": {
        "type": "checkbox",
        "label": "Enable data MCP tools",
        "default": True,
    },
    "family_enabled_drawing": {
        "type": "checkbox",
        "label": "Enable drawing MCP tools",
        "default": True,
    },
    "family_enabled_form": {
        "type": "checkbox",
        "label": "Enable form MCP tools",
        "default": True,
    },
    "family_enabled_mesh": {
        "type": "checkbox",
        "label": "Enable mesh MCP tools",
        "default": True,
    },
    "family_enabled_pmi": {
        "type": "checkbox",
        "label": "Enable pmi MCP tools",
        "default": True,
    },
    "family_enabled_render": {
        "type": "checkbox",
        "label": "Enable render MCP tools",
        "default": True,
    },
    "family_enabled_save": {
        "type": "checkbox",
        "label": "Enable save MCP tools",
        "default": True,
    },
    "family_enabled_sheet": {
        "type": "checkbox",
        "label": "Enable sheet metal MCP tools",
        "default": True,
    },
    "family_enabled_surface": {
        "type": "checkbox",
        "label": "Enable surface MCP tools",
        "default": True,
    },
    # The Settings dialog draws checkboxes and dropdowns only, so it shows no input for this
    # type: the port is edited in the settings file. start() refuses a value it cannot bind.
    endpoint.PORT_SETTING: {
        "type": "number",
        "label": f"MCP server port ({endpoint.PORT_MIN}-{endpoint.PORT_MAX})",
        "default": endpoint.DEFAULT_PORT,
    },
}

# Register this module's settings group so it appears as a Settings tab.
shared_state.load_settings_init(SETTINGS_ID, 'MCP Server', DEFAULT_SETTINGS, ICON_FOLDER)


def _refresh_stored_presentation():
    """Bring this group's stored row labels and tab icon path up to the shipped ones."""
    # load_settings_init keeps an existing group's labels and img_path, and the Settings dialog
    # draws those stored copies. Only "label" and "img_path" are assigned; no "default" is.
    try:
        groups = shared_state.get_all_module_settings()
        group = groups.get(SETTINGS_ID) if isinstance(groups, dict) else None
        if not isinstance(group, dict):
            return
        changed = False
        rows = group.get("settings")
        for key, shipped in DEFAULT_SETTINGS.items():
            row = rows.get(key) if isinstance(rows, dict) else None
            if isinstance(row, dict) and row.get("label") != shipped["label"]:
                row["label"] = shipped["label"]
                changed = True
        if group.get("img_path") != ICON_FOLDER:
            group["img_path"] = ICON_FOLDER
            changed = True
        if changed:
            shared_state._write_settings(groups)
    except Exception as e:
        futil.log(f'{CMD_NAME}: stored Settings labels and icon not refreshed '
                  f'({type(e).__name__}: {e})')


_refresh_stored_presentation()


def _execute_api_script_allowed() -> bool:
    """Read the gating setting for the arbitrary-script-execution tool."""
    try:
        settings = shared_state.load_settings(SETTINGS_ID)
        return bool(settings.get(_ALLOW_EXECUTE_KEY, {}).get("default", False))
    except Exception:
        return False


def _disabled_families() -> set:
    """Read the family_enabled_<fam> checkboxes: the set of GATEABLE_FAMILIES the user turned OFF.

    Same defensive read style as _execute_api_script_allowed(): a missing settings file, a missing
    key, or any read error all mean ENABLED - a family is only disabled by an explicit False, never
    by a settings read failure.
    """
    disabled = set()
    try:
        settings = shared_state.load_settings(SETTINGS_ID)
    except Exception:
        return disabled
    for fam in GATEABLE_FAMILIES:
        try:
            enabled = bool(settings.get(f"family_enabled_{fam}", {}).get("default", True))
        except Exception:
            enabled = True
        if not enabled:
            disabled.add(fam)
    return disabled


def _configured_port():
    """(port, None) from the 'mcp_port' setting, or (None, why start() must not bind)."""
    try:
        setting = shared_state.load_settings(SETTINGS_ID)[endpoint.PORT_SETTING]
    except Exception as e:
        return None, (f"The '{endpoint.PORT_SETTING}' setting could not be read "
                      f"({type(e).__name__}: {e}); the shipped default is {endpoint.DEFAULT_PORT}.")
    return endpoint.configured_port(setting)


# Module-level handles to the running server, torn down in stop().
# _lifecycle counts every start() and stop(); a listener report begun under an earlier count
# drops itself instead of warning in, or stopping the TaskManager of, a later one.
_lifecycle = 0
_http_server = None
_server_thread = None
_mcp = None


def _collect_items():
    """Reset the registry and AUTO-DISCOVER every tool, registering each freshly.

    Tools live one-per-module under ``tools/`` and expose a ``register_tool()`` (a few self-register on
    import; ``register_tool()`` is then a harmless no-op). Rather than hand-maintain a parallel list of
    ~64 ``tools.X.register_tool()`` calls here AND a parallel import list in ``tools/__init__.py`` - two
    registries that drift whenever a tool is added - we sweep the package with ``pkgutil`` and call each
    module's ``register_tool()``. The registry's name-collision guard makes a double-register loud, and
    a module without ``register_tool()`` (a ``_``-prefixed helper) is skipped.

    Two cases stay explicit: the GATED arbitrary-script tool registers only when the user opts in, and
    ``sys_reload_addin`` also installs its dedicated reload custom event (a side-effect beyond
    registration).
    """
    registry.reset_registry()
    from . import tools  # the package whose modules we sweep

    registered = []
    for mod_info in pkgutil.iter_modules(tools.__path__):
        name = mod_info.name
        if name.startswith('_') or name in _GATED_TOOL_MODULES:
            continue
        try:
            mod = importlib.import_module(f'{tools.__name__}.{name}')
        except Exception as e:
            futil.log(f'{CMD_NAME}: tool module {name!r} failed to import: {e}')
            continue
        reg = getattr(mod, 'register_tool', None)
        if callable(reg):
            try:
                reg()
                registered.append(name)
            except Exception as e:
                futil.log(f'{CMD_NAME}: {name}.register_tool() failed: {e}')

    # reload_addin is registered by the sweep above; it ALSO needs its dedicated deferred-reload custom
    # event installed (a side-effect beyond registration). Import it explicitly (don't rely on it being
    # a bound attribute of the tools package) and install the event.
    try:
        from .tools import sys_reload_addin
        sys_reload_addin.install_reload_event()
    except Exception as e:
        futil.log(f'{CMD_NAME}: sys_reload_addin.install_reload_event() failed: {e}')

    # The high-risk arbitrary-script tool is gated and SKIPPED by the sweep - import it explicitly and
    # register it ONLY when the user has opted in.
    if _execute_api_script_allowed():
        try:
            from .tools import sys_execute_script
            sys_execute_script.register_tool()
            futil.log(f'{CMD_NAME}: execute_api_script ENABLED (user opted in)')
        except Exception as e:
            futil.log(f'{CMD_NAME}: sys_execute_script.register_tool() failed: {e}')

    # FAMILY GATING: purge by TOOL NAME, after the sweep - a module's filename prefix does not always
    # match its registered tools' families (mesh_export.py registers save_as_mesh, family "save"), so
    # skipping modules by filename would miss that. Walk the now-fully-populated registry instead and
    # drop anything whose family the user disabled.
    disabled = _disabled_families()
    if disabled:
        purged = 0
        for item in list(registry.get_tools()):
            if family_of(item.get_name()) in disabled:
                if unregister(item.get_name()):
                    purged += 1
        futil.log(f'{CMD_NAME}: disabled families ({", ".join(sorted(disabled))}) - purged {purged} tool(s)')

    futil.log(f'{CMD_NAME}: registered {len(registered)} tool modules (auto-discovered)')
    return registry.get_tools()


def _resource_catalog():
    """The static MCP Resources this server publishes: the packaged guidance, rendered whole.

    Built HERE and handed to the server, so the transport never reaches into product content. A
    document that does not load leaves the catalog EMPTY and says why in the log - the server then
    advertises no resources capability at all, rather than an address that answers with an error.
    """
    try:
        from .guidance import resources
        return resources.catalog()
    except Exception as e:
        futil.log(f'{CMD_NAME}: no MCP resource published ({e})')
        return []


def start():
    """Called when the module is enabled and the add-in starts."""
    global _http_server, _server_thread, _mcp, _lifecycle
    _lifecycle += 1
    # The TaskManager is started first and owns a registered custom event plus the pending-task
    # table, so every path that leaves without a running server must stop it again. One guard in
    # finally covers all of them - including an unexpected raise, which the blanket except below
    # otherwise reports and swallows, leaking the started TaskManager until the next add-in stop().
    # The failed-bind report is the one hand-off: its main-thread callback stops the TaskManager.
    server_running = False
    report_pending = False
    try:
        if TaskManager.start() is not True:
            futil.log(f'{CMD_NAME}: phase=task_manager_start server not started',
                      adsk.core.LogLevels.ErrorLogLevel)
            return

        port, problem = _configured_port()
        if problem:
            _report_start_problem(
                f'Fusion-Essentials MCP server did not start. {problem} Edit it in the '
                f"'{CMD_NAME}' group of {shared_state.SETTINGS_FILE}, then reload "
                'Fusion-Essentials (Utilities -> Add-Ins -> Stop, then Run).'
            )
            return

        loaded_attestation.resume()
        try:
            items = _collect_items()
            resources = _resource_catalog()
        finally:
            loaded_attestation.finish()
        result = mcp_server.start_server(HOST, port, items=items, resources=resources,
                                         attestation=loaded_attestation.attest)
        status = result.get("status")

        if status == mcp_server.START_OK:
            _mcp = result["mcp"]
            _http_server = result["http_server"]
            _server_thread = result["thread"]
            server_running = True
            futil.log(
                f'{CMD_NAME}: running on http://{HOST}:{port}{endpoint.MCP_PATH} '
                f'({len(items)} item(s) registered)'
            )

            # Self-check: confirm this session's server is the one answering on the port.
            _report_listener(port, bound_here=True,
                             own_session=getattr(_mcp, 'session_id', None))

        elif status == mcp_server.START_PORT_IN_USE:
            futil.log(f'{CMD_NAME}: server not started - could not bind {HOST}:{port}. '
                      'Identifying who answers there.', adsk.core.LogLevels.ErrorLogLevel)
            _report_listener(port, bound_here=False)
            report_pending = True
        else:
            # Some other startup failure; details already logged.
            futil.log(f'{CMD_NAME}: failed to start ({result.get("message", "unknown error")})')
    except Exception:
        # A failure here must never break the rest of the add-in.
        futil.handle_error(f'{CMD_NAME}.start')
    finally:
        if not server_running and not report_pending:
            TaskManager.stop()


def _report_listener(port, bound_here, own_session=None):
    """Identify who answers on HOST:port on a worker thread, then warn on the main thread.

    The probe blocks on HTTP, so it never runs on the UI thread; the message goes back through
    TaskManager.post. After a failed bind that callback also stops the TaskManager.
    """
    lifecycle = _lifecycle

    def _probe():
        found = mcp_server.identify_listener(HOST, port)
        message = _conflict_message(port, found, bound_here=bound_here, own_session=own_session)
        if message is None or lifecycle != _lifecycle:
            return

        def _warn_on_main(_data):
            if lifecycle != _lifecycle:
                return
            try:
                _report_start_problem(message)
            finally:
                if not bound_here:
                    TaskManager.stop()

        posted = TaskManager.post(command="mcp_port_conflict_warning", callback=_warn_on_main,
                                  data={})
        if not posted and lifecycle == _lifecycle:
            # No way to reach the UI thread; the message still goes to the log.
            futil.log(message)

    threading.Thread(target=_probe, daemon=True, name='FE-MCP-ListenerReport').start()


def _conflict_message(port, found, bound_here=False, own_session=None):
    """The user message naming who answers on HOST:port, or None when a bound server is unshadowed."""
    kind, name = found.get("kind"), found.get("name")
    if kind == mcp_server.LISTENER_OURS:
        if bound_here and own_session and found.get("session_id") == own_session:
            return None
        who = 'The Fusion-Essentials MCP server of another Fusion session answers there.'
    elif kind == mcp_server.LISTENER_OTHER:
        who = f'Another MCP server answers there, reporting the name {name!r}.'
    elif bound_here:
        return None
    else:
        who = ('Nothing there identified itself as an MCP server: an unidentified listener '
               'holds the port, or the system reserves it.')
    lead = (f'Fusion-Essentials MCP server bound {HOST}:{port}, but its requests are answered '
            'elsewhere.' if bound_here else
            f'Fusion-Essentials MCP server did not start: it could not bind {HOST}:{port}.')
    return (
        f'{lead} {who}\n\n'
        f"Change '{endpoint.PORT_SETTING}' in the add-in's '{CMD_NAME}' settings "
        f'({shared_state.SETTINGS_FILE}) to a free port from {endpoint.PORT_MIN} to '
        f'{endpoint.PORT_MAX}, or stop the other program. Then reload Fusion-Essentials '
        "(Utilities -> Add-Ins -> Stop, then Run) and use the new port in your MCP client's "
        'server URL.'
    )


def _report_start_problem(message: str):
    """Log a startup problem and show it to the user."""
    futil.log(message, adsk.core.LogLevels.ErrorLogLevel)
    if ui:
        ui.messageBox(message, CMD_NAME)


def stop():
    """Called when the add-in stops (or the module is disabled on next load).

    Tear-down order: stop HTTP server -> join thread -> stop TaskManager.
    """
    global _http_server, _server_thread, _mcp, _lifecycle
    _lifecycle += 1
    try:
        # Remove the deferred-reload custom event (a fresh start() reinstalls it).
        try:
            from .tools import sys_reload_addin
            sys_reload_addin.uninstall_reload_event()
        except Exception:
            futil.handle_error(f'{CMD_NAME}.stop.uninstall_reload_event')
        if _http_server is not None or _server_thread is not None:
            mcp_server.stop_server(_http_server, _server_thread)
        TaskManager.stop()
        _http_server = None
        _server_thread = None
        _mcp = None
        futil.log(f'{CMD_NAME}: stopped')
    except Exception:
        futil.handle_error(f'{CMD_NAME}.stop')
