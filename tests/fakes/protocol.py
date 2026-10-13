# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Controlled task scheduling and HTTP reply probes for server protocol tests."""

import io
import json
import types

class _ScriptedTasks:
    """A TaskManager stand-in: post() captures the callback; the test decides when (or whether)
    it runs, and what cancel() answers."""
    def __init__(self, cancel_answer=True, run_after_s=None, run_on_cancel=False):
        self.callback = None
        self.data = None
        self.cancel_answer = cancel_answer
        self.run_after_s = run_after_s      # run the callback from a timer thread after this delay
        self.run_on_cancel = run_on_cancel  # the finished-inside-the-cancel-window race
        self.cancel_called = False

    def is_running(self):
        return True

    def start(self):
        return True

    def post(self, command, callback, data, on_drop=None):
        self.callback, self.data = callback, data
        self.on_drop = on_drop
        if self.run_after_s is not None:
            import threading
            threading.Timer(self.run_after_s, lambda: callback(data)).start()
        return "task-1"

    def cancel(self, task_id):
        self.cancel_called = True
        if self.run_on_cancel and self.callback:
            self.callback(self.data)
        return self.cancel_answer


class _PostProbe:
    """The slice of MCPHandler that do_POST's PARSE step touches: a body to read, a send_error to
    capture the refusal, and just enough of the accept path for a well-formed body to reach 202."""

    def __init__(self, body: bytes, mcp_server=None):
        self.path = '/mcp'
        self.headers = {'Content-Length': str(len(body))}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.errors = []
        self.responses = []
        self.response_headers = []

        async def _accept(_request):
            return None                 # a notification - do_POST answers 202 with no body
        self.mcp_server = mcp_server or types.SimpleNamespace(handle_request=_accept, session_id="s1")

    def _origin_ok(self):
        return True

    def send_error(self, code, message=None):
        self.errors.append((code, message))

    def _send_json(self, response):
        self.send_response(200)
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def send_response(self, code, message=None):
        self.responses.append(code)

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        pass
