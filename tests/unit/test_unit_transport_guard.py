"""Physical transport refusals stay failures even when the caller catches them."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import conftest


@pytest.fixture
def guarded_pytest(tmp_path, pytestconfig):
    for hook, function in (
            (pytestconfig.hook.pytest_runtest_makereport, conftest.pytest_runtest_makereport),
            (pytestconfig.hook.pytest_collection_finish, conftest.pytest_collection_finish),
            (pytestconfig.hook.pytest_sessionfinish, conftest.pytest_sessionfinish)):
        assert any(implementation.function is function for implementation in hook.get_hookimpls())
    def run(source):
        target = tmp_path / "test_transport_probe.py"
        target.write_text(source, encoding="utf-8")
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                   PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider",
             "-q", str(target)], env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=60)
    return run


@pytest.mark.parametrize("attempt", [
    "urllib.request.urlopen('http://127.0.0.1:37182/health', timeout=1)",
    "socket.socket().connect(('192.0.2.1', 9))",
    "socket.socket().connect_ex(('192.0.2.1', 9))",
    "socket.socket(type=socket.SOCK_DGRAM).sendto(b'x', ('192.0.2.1', 9))"])
def test_caught_real_transport_attempt_still_fails(guarded_pytest, attempt):
    result = guarded_pytest("import socket, sys, urllib.request\n"
        "def secondary_barrier(event, args):\n"
        "    if event in {'urllib.Request', 'socket.connect', 'socket.sendto'}:\n"
        "        print('SECONDARY-BARRIER-REACHED')\n"
        "        raise RuntimeError('proof safety barrier; no OS connection')\n"
        "sys.addaudithook(secondary_barrier)\n"
        "def test_caught():\n"
        "    try:\n        " + attempt + "\n"
        "    except BaseException:\n        pass\n")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Unit tests cannot reach a live server" in result.stdout
    assert "1 failed" in result.stdout
    assert "SECONDARY-BARRIER-REACHED" not in result.stdout


def test_collection_attempt_is_not_hidden_by_catching_it(guarded_pytest):
    result = guarded_pytest("import socket\n"
        "try:\n    socket.socket().connect(('192.0.2.1', 9))\n"
        "except BaseException:\n    pass\n"
        "def test_body():\n    assert True\n")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Unit tests cannot reach a live server" in result.stdout + result.stderr
    assert "1 passed" not in result.stdout


@pytest.mark.parametrize("attempt", [
    "socket.socket(type=socket.SOCK_DGRAM).connect(server.server_address)",
    "socket.socket(type=socket.SOCK_DGRAM).sendto(b'x', server.server_address)",
    "socket.socket().connect(server.server_address)"])
def test_owned_tcp_listener_does_not_allow_udp_or_configured_fusion_port(guarded_pytest, attempt):
    result = guarded_pytest("import json, os, socket, sys\n"
        "from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler\n"
        "def secondary_barrier(event, args):\n"
        "    if event in {'socket.connect', 'socket.sendto'}:\n"
        "        raise RuntimeError('proof safety barrier; no OS connection')\n"
        "sys.addaudithook(secondary_barrier)\n"
        "def test_boundary(tmp_path):\n"
        "    server = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)\n"
        "    try:\n"
        + ("        path = tmp_path / 'config.json'\n"
           "        path.write_text(json.dumps({'port': server.server_port}))\n"
           "        os.environ['FUSION_ESSENTIALS_SWEEP_CONFIG'] = str(path)\n"
           if "SOCK_DGRAM" not in attempt else "")
        + "        try:\n            " + attempt + "\n"
        "        except BaseException:\n            pass\n"
        "    finally:\n        server.server_close()\n")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Unit tests cannot reach a live server" in result.stdout
    assert "1 failed" in result.stdout


def test_explicit_mock_and_process_owned_http_listener_remain_usable(guarded_pytest):
    result = guarded_pytest('''import threading, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

def test_mock(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b"mocked"
    monkeypatch.setattr(urllib.request, "urlopen", Mock(return_value=response))
    with urllib.request.urlopen("http://127.0.0.1:37182/health") as stream:
        assert stream.read() == b"mocked"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"owned")
    def log_message(self, *args):
        pass

def test_owned_listener():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen("http://127.0.0.1:%s/" % server.server_port) as stream:
            assert stream.read() == b"owned"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
''')
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


def test_second_facade_cannot_escape_to_the_real_runner(guarded_pytest):
    result = guarded_pytest('''import json, sys
def secondary_barrier(event, args):
    if event == 'urllib.Request':
        print('SECONDARY-BARRIER-REACHED')
        raise RuntimeError('proof safety barrier; no OS connection')
sys.addaudithook(secondary_barrier)
from pathlib import Path
import conftest
sys.path.insert(0, str(Path(conftest.__file__).parent / "live"))
import tool_verify

def test_runner(tmp_path, monkeypatch):
    spec_loaded = conftest.load_tool_verify()
    core = spec_loaded.verify_core
    if hasattr(core, "_MACHINE_READ"):
        config = {"machine": "unit-probe", "port": 37182,
                  "tiers": {"native_script": False, "machining_extension": False, "cloud": False},
                  "cloud": {"hub": "", "project": "", "folder": ""},
                  "allow": {"library_writes": False, "preference_writes": False, "addin_reload": False}}
        path = tmp_path / "machine.json"
        path.write_text(json.dumps(config))
        monkeypatch.setattr(core, "MACHINE", config)
        monkeypatch.setattr(core, "_MACHINE_READ", (config, (), str(path), "injected"))
        monkeypatch.setenv("FUSION_ESSENTIALS_SWEEP_CONFIG", str(path))
    monkeypatch.setattr(spec_loaded, "ACTS", [("ACT unit", None, [], None)])
    monkeypatch.setattr(spec_loaded, "FAMILY_PROGRAM", None)
    monkeypatch.setattr(spec_loaded, "health_gate", lambda: {"server": "spy"})
    monkeypatch.setattr(tool_verify, "ACTS", [("ACT unit", None, [], None)])
    monkeypatch.setattr(tool_verify, "FAMILY_PROGRAM", None)
    monkeypatch.setattr(tool_verify, "ACT_NEEDS", {})
    monkeypatch.setattr(tool_verify, "source_hash", lambda: "0" * 64)
    assert core.facade("health_gate") is tool_verify.health_gate
    try:
        spec_loaded.run(False)
    except BaseException:
        pass
''')
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Unit tests cannot reach a live server" in result.stdout
    assert "Blocked urllib.Request" in result.stdout
    assert "1 failed" in result.stdout
    assert "SECONDARY-BARRIER-REACHED" not in result.stdout
