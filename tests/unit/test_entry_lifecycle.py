# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Tests for what entry.start() hands the server, and for its teardown guard: a start that does not
leave a server running must leave no started TaskManager behind.

TaskManager.start() registers a Fusion custom event and arms the pending-task table; entry.start()
calls it FIRST, so every exit that does not end with a running server has to stop it again. The
handled failure paths did that explicitly, but the blanket `except Exception` that keeps a broken
MCP module from breaking the rest of the add-in skipped it - so any raise inside start() (a tool
module blowing up during registration, a bind error) left the event registered with nothing serving
it until the next add-in stop().

entry.py also OWNS the static MCP resource catalog: it builds it from the shipped guidance package
and hands it to start_server, so the transport never reaches into product content. A document that
does not load must leave that catalog empty - the server then advertises no resource capability at
all - which is checked here against the real packaged document.

entry.py cannot be imported here: its module body calls shared_state.load_settings_init(), which
reads and rewrites the real user settings file, and it needs the live add-in package host. So the
function under test is compiled OUT of entry.py's AST and executed against fakes - the actual
shipped source, with no module import side effects.
"""

import ast
import json
import os
import sys

import pytest

from conftest import COMMANDS_DIR, REPO_ROOT, load_mcp_server
from test_shared_state import shared_state  # noqa: F401  (the isolated temporary settings store)

if COMMANDS_DIR not in sys.path:                   # the flat package root the add-in code lives in
    sys.path.insert(0, COMMANDS_DIR)
from mcpServer import endpoint                                  # noqa: E402
from mcpServer.guidance import loader as guidance_loader        # noqa: E402
from mcpServer.guidance import resources as guidance_resources  # noqa: E402

ENTRY_PATH = os.path.join(COMMANDS_DIR, "mcpServer", "entry.py")

# The package entry.py's own relative imports resolve against (`from .guidance import resources`),
# which is what lets one function be executed out of its AST and still reach the shipped package.
ENTRY_PACKAGE = "mcpServer"
_ENTRY_START_ERROR_LEVEL = object()


class _FakeTaskManager:
    """Counts start/stop. It stands in for the add-in's own TaskManager, not for any adsk type, so
    conftest's shared adsk fakes have nothing to reuse here."""

    def __init__(self, start_result=True):
        self.started = 0
        self.stopped = 0
        self.start_result = start_result
        self.pending = []       # callbacks posted for the main thread and not yet delivered
        self.posts = 0

    def start(self):
        self.started += 1
        return self.start_result

    def stop(self):
        self.stopped += 1
        self.pending.clear()    # the real stop() drops every unclaimed task
        return True

    def post(self, command, callback, data, on_drop=None):
        if not self.running:
            return None
        self.posts += 1
        self.pending.append(callback)
        return f"task-{self.posts}"

    def deliver(self):
        """Run the posted callbacks, as the main thread does when the custom event fires."""
        while self.pending:
            self.pending.pop(0)({})

    @property
    def running(self):
        """True while a start has not been matched by a stop - the leak this file guards."""
        return self.started > self.stopped


class _FakeServerModule:
    def __init__(self, result, real, listener=None):
        self.START_OK = real.START_OK
        self.START_PORT_IN_USE = real.START_PORT_IN_USE
        self.LISTENER_OURS = real.LISTENER_OURS
        self.LISTENER_OTHER = real.LISTENER_OTHER
        self._result = result
        self._listener = listener or {"kind": real.LISTENER_UNIDENTIFIED, "name": None,
                                      "session_id": None}
        self.seen = {}          # what start() actually handed the transport
        self.binds = []         # every port start() asked the transport to bind
        self.probed = []        # every port start() asked the transport to identify

    def start_server(self, host, port, items=None, resources=None, attestation=None):
        self.binds.append(port)
        self.seen = {"host": host, "port": port, "items": items, "resources": resources,
                     "attestation": attestation}
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def identify_listener(self, host, port):
        self.probed.append(port)
        return dict(self._listener)


class _FakeThreading:
    """threading's Thread seam: a started thread is recorded, and runs only when a test says so."""

    def __init__(self, start_raises=None):
        self.threads = []
        outer = self

        class Thread:
            def __init__(self, target=None, daemon=None, name=None):
                self.target, self.name = target, name

            def start(self):
                if start_raises is not None:
                    raise start_raises
                outer.threads.append(self)

        self.Thread = Thread

    def run_all(self):
        while self.threads:
            self.threads.pop(0).target()


SETTINGS_FILE = "S:/settings/FusionEssentialsSettings.json"
SETTINGS_ID = "GTF_Test_MCP"
_DEFAULT_ROW = object()


def _fake_shared_state(row, raises=None):
    """shared_state's two names entry.py reads: the settings file path and one group's rows."""
    def load_settings(_module_id):
        if raises is not None:
            raise raises
        return {endpoint.PORT_SETTING: row}

    return type("SharedState", (), {"SETTINGS_FILE": SETTINGS_FILE,
                                    "load_settings": staticmethod(load_settings)})()


def _load_function(name, namespace):
    """One entry.py function, compiled from its own source into `namespace`."""
    with open(ENTRY_PATH, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=ENTRY_PATH)
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(fns) == 1, f"entry.py must define exactly one {name}(); found {len(fns)}"
    module = ast.Module(body=fns, type_ignores=[])
    exec(compile(module, ENTRY_PATH, "exec"), namespace)
    return namespace[name]


@pytest.fixture
def real_server_module():
    return load_mcp_server()


def _run_start(real, *, result, start_result=True, collect_raises=None, thread_raises=None,
               catalog=("resource",), port_row=_DEFAULT_ROW, settings_raise=None, listener=None,
               settings_store=None):
    """Execute entry.start() against fakes; return the fake TaskManager and the collected log.

    The returned server fake also carries `workers` (the thread seam) and `ns` (the namespace)."""
    tm = _FakeTaskManager(start_result=start_result)
    log = []

    def _collect_items():
        if collect_raises is not None:
            raise collect_raises
        return ["item"]

    if port_row is _DEFAULT_ROW:
        port_row = {"type": "number", "default": endpoint.DEFAULT_PORT}
    server_module = _FakeServerModule(result, real, listener)
    server_module.workers = _FakeThreading(thread_raises)
    fake_levels = type("LogLevels", (), {"ErrorLogLevel": _ENTRY_START_ERROR_LEVEL})
    fake_adsk = type("Adsk", (), {"core": type("Core", (), {"LogLevels": fake_levels})})

    def _log(message, level=None):
        log.append(("log", message))
        if level is not None:
            log.append(("log_level", level))

    capture = type("Capture", (), {
        "resume": staticmethod(lambda: log.append(("capture", "resume")) or True),
        "finish": staticmethod(lambda: log.append(("capture", "finish"))),
        "attest": staticmethod(lambda: {"complete": True})})()
    ns = {
        "TaskManager": tm,
        "mcp_server": server_module,
        "_collect_items": _collect_items,
        "_resource_catalog": lambda: list(catalog),
        "loaded_attestation": capture,
        "threading": server_module.workers,
        "_lifecycle": 0,
        "_report_start_problem": lambda message: log.append(("warn", message)),
        "endpoint": endpoint,
        "shared_state": settings_store or _fake_shared_state(port_row, settings_raise),
        "SETTINGS_ID": SETTINGS_ID,
        "adsk": fake_adsk,
        "futil": type("F", (), {"log": staticmethod(_log),
                                "handle_error": staticmethod(
                                    lambda m: log.append(("error", m)))})(),
        "CMD_NAME": "MCP Server",
        "HOST": "127.0.0.1",
        "_http_server": None,
        "_server_thread": None,
        "_mcp": None,
    }
    for helper in ("_configured_port", "_conflict_message", "_report_listener", "stop"):
        _load_function(helper, ns)
    server_module.ns = ns
    _load_function("start", ns)()
    return tm, log, server_module


def _warnings(log):
    return [value for kind, value in log if kind == "warn"]


def _ok_result(real):
    return {"status": real.START_OK, "mcp": object(), "http_server": object(), "thread": object()}


class TestStartStopsTheTaskManagerWhenNoServerRuns:
    def test_a_raise_inside_start_stops_the_task_manager(self, real_server_module):
        tm, log, _ = _run_start(real_server_module, result=_ok_result(real_server_module),
                                collect_raises=RuntimeError("a tool module blew up"))
        assert tm.started == 1
        assert tm.stopped == 1, "the blanket except swallowed the failure and leaked the TaskManager"
        assert tm.running is False
        assert [value for kind, value in log if kind == "capture"] == ["resume", "finish"]
        assert ("error", "MCP Server.start") in log, "the failure must still be reported"

    def test_a_raise_from_start_server_stops_the_task_manager(self, real_server_module):
        tm, _log, _srv = _run_start(real_server_module, result=OSError("bind failed"))
        assert (tm.started, tm.stopped) == (1, 1)

    def test_port_in_use_stops_the_task_manager_once_the_report_is_shown(self,
                                                                         real_server_module):
        tm, log, server = _run_start(real_server_module,
                                     result={"status": real_server_module.START_PORT_IN_USE})
        assert tm.stopped == 0, "the report needs the TaskManager to reach the main thread"
        server.workers.run_all()
        tm.deliver()
        assert tm.stopped == 1, "the port-conflict path must stop the TaskManager, and only once"
        assert len(_warnings(log)) == 1, "the user must still be warned, once"

    def test_a_report_thread_that_does_not_start_stops_the_task_manager(self, real_server_module):
        tm, log, _srv = _run_start(real_server_module,
                                   result={"status": real_server_module.START_PORT_IN_USE},
                                   thread_raises=RuntimeError("can't start new thread"))
        assert (tm.started, tm.stopped) == (1, 1)
        assert ("error", "MCP Server.start") in log

    def test_failed_task_manager_start_stops_without_collecting_or_binding(self, real_server_module):
        tm, log, server = _run_start(
            real_server_module, result=_ok_result(real_server_module), start_result=False,
            collect_raises=RuntimeError("collection must not run after TaskManager start failure"))
        assert (tm.started, tm.stopped) == (1, 1) and tm.running is False
        assert server.seen == {}
        assert not any(kind == "capture" for kind, _ in log)
        assert ("error", "MCP Server.start") not in log
        assert any("phase=task_manager_start" in message for kind, message in log if kind == "log")
        assert [level for kind, level in log if kind == "log_level"] == [
            _ENTRY_START_ERROR_LEVEL]

    def test_an_unknown_failure_status_stops_the_task_manager(self, real_server_module):
        tm, _log, _srv = _run_start(real_server_module, result={"status": "something-else",
                                                                "message": "no port"})
        assert (tm.started, tm.stopped) == (1, 1)

    def test_a_successful_start_leaves_the_task_manager_running(self, real_server_module):
        tm, _log, _srv = _run_start(real_server_module, result=_ok_result(real_server_module))
        assert tm.stopped == 0, "the running server needs the TaskManager to marshal main-thread work"
        assert tm.running is True

    def test_a_raise_after_the_server_is_up_leaves_the_task_manager_running(self, real_server_module):
        # the boundary: the ownership probe raises AFTER the server is serving, so the TaskManager
        # is still in use - stopping it here would break the live server the guard is protecting.
        tm, log, _ = _run_start(real_server_module, result=_ok_result(real_server_module),
                                thread_raises=RuntimeError("probe thread refused to spawn"))
        assert tm.stopped == 0
        assert ("error", "MCP Server.start") in log


class TestStartBindsExactlyTheConfiguredPort:
    def test_the_default_port_has_one_definition_every_reader_shares(self):
        assert endpoint.DEFAULT_PORT == 37182
        url = f"http://{endpoint.HOST}:{endpoint.DEFAULT_PORT}{endpoint.MCP_PATH}"
        for relative in ("commands/mcpServer/entry.py", "commands/mcpServer/server/mcp_server.py",
                         "commands/mcpServer/tools/sys_capability_map.py",
                         "tests/live/verify_core.py", "tests/check_all.py"):
            with open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as fh:
                assert "37182" not in fh.read(), f"{relative} repeats the port; read endpoint.py"
        with open(ENTRY_PATH, encoding="utf-8") as fh:
            rows = [node for node in ast.walk(ast.parse(fh.read())) if isinstance(node, ast.Dict)
                    and any(isinstance(k, ast.Constant) and k.value == "default"
                            and ast.unparse(v) == "endpoint.DEFAULT_PORT"
                            for k, v in zip(node.keys, node.values))]
        assert len(rows) == 1, "the mcp_port row must default to endpoint.DEFAULT_PORT"
        live = os.path.join(REPO_ROOT, "tests", "live")
        if live not in sys.path:
            sys.path.insert(0, live)
        import verify_core
        assert verify_core.MCP == url
        with open(os.path.join(REPO_ROOT, ".mcp.json"), encoding="utf-8") as fh:
            assert json.load(fh)["mcpServers"]["fusion-essentials"]["url"] == url
        with open(os.path.join(REPO_ROOT, ".codex", "config.toml"), encoding="utf-8") as fh:
            assert f'url = "{url}"' in fh.read()

    def test_the_default_setting_binds_the_default_port(self, real_server_module):
        _tm, _log, server = _run_start(real_server_module, result=_ok_result(real_server_module))
        assert server.binds == [endpoint.DEFAULT_PORT]

    @pytest.mark.parametrize("port", [40123, endpoint.PORT_MIN, endpoint.PORT_MAX])
    def test_a_configured_port_is_the_one_bound(self, real_server_module, port):
        _tm, log, server = _run_start(real_server_module, result=_ok_result(real_server_module),
                                      port_row={"type": "number", "default": port})
        assert server.binds == [port]
        assert _warnings(log) == []

    @pytest.mark.parametrize("value", ["37182", 0, 80, 1023, 49152, 70000, True, 40123.0, None])
    def test_an_unusable_setting_is_reported_and_nothing_is_bound(self, real_server_module,
                                                                  value):
        tm, log, server = _run_start(real_server_module, result=_ok_result(real_server_module),
                                     port_row={"type": "number", "default": value})
        assert server.binds == [], "a refused setting must not fall back to any port"
        (message,) = _warnings(log)
        assert f"'mcp_port' setting is {value!r}." in message
        assert "1024 to 49151" in message and "default is 37182" in message
        assert SETTINGS_FILE in message
        assert tm.running is False

    def test_a_row_that_is_not_a_settings_entry_is_refused_by_its_value(self, real_server_module):
        _tm, log, server = _run_start(real_server_module, result=_ok_result(real_server_module),
                                      port_row=40123)
        assert server.binds == []
        assert "'mcp_port' setting is 40123." in _warnings(log)[0]

    def test_an_unreadable_setting_is_reported_and_nothing_is_bound(self, real_server_module):
        _tm, log, server = _run_start(real_server_module, result=_ok_result(real_server_module),
                                      settings_raise=OSError("settings file is locked"))
        assert server.binds == []
        (message,) = _warnings(log)
        assert "'mcp_port' setting could not be read" in message
        assert "settings file is locked" in message

    @pytest.mark.parametrize("kind, name, said", [
        ("LISTENER_OURS", "Fusion-Essentials MCP Server",
         "The Fusion-Essentials MCP server of another Fusion session answers there."),
        ("LISTENER_OTHER", "Some Other Server",
         "Another MCP server answers there, reporting the name 'Some Other Server'."),
        ("LISTENER_UNIDENTIFIED", None, "an unidentified listener holds the port"),
    ])
    def test_a_taken_port_names_who_answers_and_binds_nothing_else(self, real_server_module,
                                                                   kind, name, said):
        real = real_server_module
        tm, log, server = _run_start(
            real, result={"status": real.START_PORT_IN_USE},
            port_row={"type": "number", "default": 40123},
            listener={"kind": getattr(real, kind), "name": name, "session_id": "other"})
        assert server.probed == [] and _warnings(log) == [], \
            "start() must return without asking the network who answers"
        assert [message for kind, message in log if kind == "log"
                and "could not bind 127.0.0.1:40123" in message], "the log line comes at once"
        assert _ENTRY_START_ERROR_LEVEL in [level for kind, level in log if kind == "log_level"]
        assert len(server.workers.threads) == 1 and tm.running is True
        server.workers.run_all()
        assert server.probed == [40123] and _warnings(log) == [], \
            "the worker thread must hand the message to the main thread, not show it"
        tm.deliver()
        assert server.binds == [40123], "one bind attempt, on the configured port only"
        (message,) = _warnings(log)
        assert "did not start: it could not bind 127.0.0.1:40123." in message
        assert said in message
        assert "Change 'mcp_port'" in message and SETTINGS_FILE in message
        assert (tm.posts, tm.stopped, tm.running) == (1, 1, False)

    @pytest.mark.parametrize("stop_at", ["before the probe ends", "before delivery"])
    def test_a_stop_during_a_pending_report_leaves_no_message(self, real_server_module, stop_at):
        real = real_server_module
        tm, log, server = _run_start(
            real, result={"status": real.START_PORT_IN_USE},
            listener={"kind": real.LISTENER_OTHER, "name": "Some Other Server",
                      "session_id": None})
        late = None
        if stop_at == "before delivery":
            server.workers.run_all()
            (late,) = tm.pending
        server.ns["stop"]()
        tm.start()                      # a later lifecycle's TaskManager, e.g. after a reload
        server.workers.run_all()
        if late is not None:
            late({})                    # the callback, were the event still to arrive
        tm.deliver()
        assert _warnings(log) == [], "a report from a stopped lifecycle must stay silent"
        assert tm.posts == (1 if late else 0) and tm.pending == []
        assert tm.running is True, "an old report must not stop a later lifecycle's TaskManager"

    def test_a_shadowed_bound_server_is_warned_about_and_keeps_serving(self, real_server_module):
        real = real_server_module
        tm, log, server = _run_start(
            real, result=_ok_result(real),
            listener={"kind": real.LISTENER_OTHER, "name": "Some Other Server",
                      "session_id": None})
        assert server.probed == []
        server.workers.run_all()
        tm.deliver()
        (message,) = _warnings(log)
        assert "bound 127.0.0.1:37182, but its requests are answered elsewhere." in message
        assert tm.stopped == 0 and tm.running is True

    def test_a_bound_server_warns_only_when_another_one_answers(self, real_server_module):
        real = real_server_module
        ns = {"mcp_server": real, "endpoint": endpoint, "HOST": "127.0.0.1",
              "CMD_NAME": "MCP Server", "shared_state": _fake_shared_state(None)}
        conflict = _load_function("_conflict_message", ns)

        def ours(session):
            return {"kind": real.LISTENER_OURS, "name": real.SERVER_NAME, "session_id": session}

        assert conflict(40123, ours("mine"), bound_here=True, own_session="mine") is None
        assert conflict(40123, {"kind": real.LISTENER_UNIDENTIFIED, "name": None,
                                "session_id": None}, bound_here=True, own_session="mine") is None
        shadowed = conflict(40123, ours("theirs"), bound_here=True, own_session="mine")
        assert "bound 127.0.0.1:40123, but its requests are answered elsewhere." in shadowed
        assert "another Fusion session" in shadowed and "'mcp_port'" in shadowed


class TestStartHandsTheServerItsResourceCatalog:
    """The transport publishes what entry.py built for it; it opens no product file itself."""

    def test_the_catalog_start_built_reaches_start_server(self, real_server_module):
        _tm, _log, server = _run_start(real_server_module, result=_ok_result(real_server_module),
                                       catalog=[{"uri": "u", "text": "t"}])
        assert server.seen["resources"] == [{"uri": "u", "text": "t"}]
        assert server.seen["items"] == ["item"]
        assert callable(server.seen["attestation"])
        assert server.seen["attestation"]() == {"complete": True}

    def test_an_empty_catalog_is_still_passed_explicitly(self, real_server_module):
        # the server decides on the VALUE it is handed (an empty list advertises nothing), so an
        # empty catalog must still arrive rather than being dropped from the call.
        _tm, _log, server = _run_start(real_server_module, result=_ok_result(real_server_module),
                                       catalog=[])
        assert server.seen["resources"] == []


class TestTheResourceCatalogEntryBuilds:
    """entry._resource_catalog() itself, run out of entry.py's AST against the REAL packaged
    guidance - the same import the add-in performs at startup."""

    def _catalog(self, monkeypatch, guidance_path=None):
        log = []
        ns = {
            "__package__": ENTRY_PACKAGE,
            "futil": type("F", (), {"log": staticmethod(lambda m: log.append(m))})(),
            "CMD_NAME": "MCP Server",
        }
        if guidance_path is not None:
            monkeypatch.setattr(guidance_loader, "GUIDANCE_PATH", guidance_path)
        return _load_function("_resource_catalog", ns)(), log

    def test_it_publishes_the_packaged_guidance(self, monkeypatch):
        catalog, log = self._catalog(monkeypatch)
        whole = guidance_resources.uri_for("parametric-cad-design")
        assert [r["uri"] for r in catalog] == [whole] + [
            guidance_resources.section_uri_for("parametric-cad-design", s)
            for s in guidance_loader.SECTION_IDS if s != guidance_loader.KERNEL]
        assert catalog[0]["text"].startswith("# ")
        assert log == []

    def test_a_document_that_does_not_load_publishes_nothing_and_says_why(self, monkeypatch,
                                                                          tmp_path):
        catalog, log = self._catalog(monkeypatch, guidance_path=str(tmp_path / "gone.json"))
        assert catalog == [], "a missing document must publish no address at all"
        assert any("gone.json" in message for message in log), log


_SETTINGS_ASSIGNMENTS = ("_ALLOW_EXECUTE_KEY", "ICON_FOLDER", "DEFAULT_SETTINGS")
_SETTINGS_CALLS = ("shared_state.load_settings_init", "_refresh_stored_presentation")


def _settings_bootstrap(store, label, refresh=True):
    """entry.py's own settings statements, run in source order against the temporary store."""
    with open(ENTRY_PATH, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=ENTRY_PATH)
    body, calls = [], []
    for node in tree.body:
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) in _SETTINGS_ASSIGNMENTS:
            body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == _SETTINGS_CALLS[1]:
            body.append(node)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and ast.unparse(node.value.func) in _SETTINGS_CALLS:
            calls.append(ast.unparse(node.value.func))
            if refresh or calls[-1] != _SETTINGS_CALLS[1]:
                body.append(node)
    assert calls == list(_SETTINGS_CALLS), "entry.py registers the group, then refreshes it"
    log = []
    ns = {"__file__": ENTRY_PATH, "os": os, "endpoint": endpoint, "shared_state": store,
          "GATED_TOOLS": {"sys_execute_script": label}, "SETTINGS_ID": SETTINGS_ID,
          "CMD_NAME": "MCP Server",
          "futil": type("F", (), {"log": staticmethod(lambda m: log.append(m))})()}
    exec(compile(ast.Module(body=body, type_ignores=[]), ENTRY_PATH, "exec"), ns)
    return ns, log


def _stored_before_the_fix(store):
    """A settings file as an existing user holds it: old labels, default icon, changed values."""
    return {
        "FEATURE_ENABLEMENT": {"name": "General", "img_path": store.DEFAULT_ICON, "settings": {
            "GTF_Test_MCP_Server": {"type": "checkbox", "label": "old label", "default": True}}},
        SETTINGS_ID: {"name": "MCP Server", "img_path": store.DEFAULT_ICON, "settings": {
            "allow_execute_api_script": {"type": "checkbox", "label": "old label",
                                         "default": True},
            "family_enabled_cam": {"type": "checkbox", "label": "Enable cam MCP tools",
                                   "default": False},
            endpoint.PORT_SETTING: {"type": "number", "label": "old port label",
                                    "default": 41627},
            "retired_row": {"type": "checkbox", "label": "old label", "default": True}}},
        "GTF_Test_Other": {"name": "Other", "img_path": store.DEFAULT_ICON, "settings": {
            "allow_execute_api_script": {"type": "checkbox", "label": "old label",
                                         "default": False}}},
    }


def _values(group):
    return {key: (row["type"], row["default"]) for key, row in group["settings"].items()}


class TestTheStoredSettingsPresentation:
    """The Settings dialog draws the stored labels and the stored icon path, so both must follow
    the shipped ones for a group that already exists - and no stored value may move."""

    def test_a_fresh_install_stores_the_shipped_icon_folder_and_labels(self, shared_state):
        store, settings_file = shared_state
        ns, _log = _settings_bootstrap(store, "current label", refresh=False)
        group = json.loads(settings_file.read_text())[SETTINGS_ID]
        folder = os.path.join(COMMANDS_DIR, "mcpServer", "resources", "")
        assert group["img_path"] == ns["ICON_FOLDER"] == folder
        for size in (16, 32, 64):
            with open(os.path.join(folder, f"{size}x{size}-normal.png"), "rb") as fh:
                assert fh.read(8) == b"\x89PNG\r\n\x1a\n"
        assert group["settings"]["allow_execute_api_script"]["label"] == "current label"
        assert group["settings"][endpoint.PORT_SETTING]["default"] == endpoint.DEFAULT_PORT

    def test_an_existing_group_gets_the_labels_and_icon_and_keeps_every_value(self, shared_state):
        store, settings_file = shared_state
        before = _stored_before_the_fix(store)
        settings_file.write_text(json.dumps(before))
        ns, log = _settings_bootstrap(store, "current label")
        after = json.loads(settings_file.read_text())
        group = after[SETTINGS_ID]
        assert group["img_path"] == ns["ICON_FOLDER"]
        for key, shipped in ns["DEFAULT_SETTINGS"].items():
            assert group["settings"][key]["label"] == shipped["label"], key
        kept = _values(before[SETTINGS_ID])
        assert kept[endpoint.PORT_SETTING] == ("number", 41627)
        assert {key: _values(group)[key] for key in kept} == kept
        assert group["settings"]["retired_row"] == before[SETTINGS_ID]["settings"]["retired_row"]
        assert group["name"] == "MCP Server"
        for other in ("FEATURE_ENABLEMENT", "GTF_Test_Other"):
            assert json.dumps(after[other]) == json.dumps(before[other]), other
        assert sorted(after) == sorted(before) and log == []

    def test_a_current_file_is_not_rewritten(self, shared_state, monkeypatch):
        store, settings_file = shared_state
        settings_file.write_text(json.dumps(_stored_before_the_fix(store)))
        ns, _log = _settings_bootstrap(store, "current label")
        current = settings_file.read_bytes()
        writes = []
        monkeypatch.setattr(store, "_write_settings", writes.append)
        ns["_refresh_stored_presentation"]()
        assert writes == [] and settings_file.read_bytes() == current

    @pytest.mark.parametrize("failure", ["unreadable file", "failing write"])
    def test_a_refresh_that_cannot_finish_is_logged_and_start_still_runs(
            self, shared_state, monkeypatch, real_server_module, failure):
        store, settings_file = shared_state
        settings_file.write_text(json.dumps(_stored_before_the_fix(store)))
        ns, log = _settings_bootstrap(store, "current label", refresh=False)
        if failure == "unreadable file":
            settings_file.write_bytes(b"{not json")
        else:
            def refuse(_groups):
                raise OSError("disk full")
            monkeypatch.setattr(store, "_write_settings", refuse)
        stored = settings_file.read_bytes()
        ns["_refresh_stored_presentation"]()
        (message,) = log
        assert "not refreshed" in message
        assert ("disk full" in message) == (failure == "failing write")
        assert settings_file.read_bytes() == stored
        tm, start_log, server = _run_start(real_server_module, settings_store=store,
                                           result=_ok_result(real_server_module))
        assert ("error", "MCP Server.start") not in start_log
        if failure == "failing write":
            assert server.binds == [41627] and tm.running is True
        else:
            assert server.binds == [] and len(_warnings(start_log)) == 1
