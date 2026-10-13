"""Wire-level tests for SimpleMCPServer's JSON-RPC protocol behavior.

Covers protocol version negotiation on initialize; the non-object-body guard (a batch ARRAY or any
other non-dict body -> one clean -32600 error object, never a raise); and the tools/call contract:
an unknown tool name is a JSON-RPC protocol error, but an unknown/missing argument, an out-of-enum
argument value, or a handler exception comes back as a normal result with isError=true (per the MCP
spec, a tool EXECUTION failure is not a protocol-level failure) so the calling agent can read it
and self-correct. Also covers the HTTP handler's Origin guard (the DNS-rebinding defense).
"""

import asyncio
import io
import json
import types

import pytest

from conftest import load_mcp_server, load_tool
from fakes.protocol import _PostProbe, _ScriptedTasks


@pytest.fixture
def mcp_server_module():
    """The real server module (mcp_server.py), loaded once for the whole test session."""
    return load_mcp_server()


@pytest.fixture
def server(mcp_server_module):
    """A fresh SimpleMCPServer with no tools registered."""
    return mcp_server_module.SimpleMCPServer()


def _make_tool_item(name, handler, *, required=("a",), optional=("b",), run_on_main_thread=False):
    """Build a synthetic tool Item via the real Tool/Item classes.

    `required` properties are added to the schema's required list; `optional` are schema
    properties that may be omitted. Defaults give one of each, matching the fixture tools this
    file drives most tests with.
    """
    from mcpServer.mcp_primitives.item import Item
    from mcpServer.mcp_primitives.tool import Tool

    tool = Tool.create_simple(name=name, description="synthetic test tool")
    for prop in required:
        tool.add_input_property(prop, {"type": "string"}).add_required_input(prop)
    for prop in optional:
        tool.add_input_property(prop, {"type": "string"})
    # strict: the arg gate only rejects unknown keys where the schema DECLARES strictness, so the
    # fixture declares it; leniency has its own dedicated test.
    tool.strict_schema()
    return Item.create_tool_item(tool=tool, handler=handler, run_on_main_thread=run_on_main_thread)


def _number_tool_item(name, handler):
    """A strict tool with a real numeric wire property for transport tests."""
    from mcpServer.mcp_primitives.item import Item
    from mcpServer.mcp_primitives.tool import Tool

    tool = Tool.create_simple(name=name, description="numeric test tool")
    tool.add_input_property("value", {"type": "number"}).add_required_input("value")
    tool.strict_schema()
    return Item.create_tool_item(tool=tool, handler=handler, run_on_main_thread=False)


def _nested_number_tool_item(name, handler):
    """A strict tool with matched nested numeric object and array properties."""
    from mcpServer.mcp_primitives.item import Item
    from mcpServer.mcp_primitives.tool import Tool

    tool = Tool.create_simple(name=name, description="nested numeric test tool")
    tool.add_input_property("payload", {"type": "object",
                                        "properties": {"nested": {"type": "number"}},
                                        "required": ["nested"]}).add_required_input("payload")
    tool.add_input_property("values", {"type": "array", "items": {"type": "number"}})
    tool.strict_schema()
    return Item.create_tool_item(tool=tool, handler=handler, run_on_main_thread=False)


def _bare_tool_item(name, handler, run_on_main_thread=False):
    """A tool Item built from a Tool with NO input_schema at all (properties/required absent)."""
    from mcpServer.mcp_primitives.item import Item
    from mcpServer.mcp_primitives.tool import Tool

    tool = Tool(name=name, description="synthetic bare tool")
    return Item.create_tool_item(tool=tool, handler=handler, run_on_main_thread=run_on_main_thread)


def _ok():
    return {"content": [{"type": "text", "text": "ok"}], "isError": False}


def _enum_tool_item(name, handler, run_on_main_thread=False):
    """A tool with one scalar enum prop ('kind'), one array-of-enum prop ('include'), and one free
    string prop ('target') - the three shapes the server-side enum gate distinguishes."""
    from mcpServer.mcp_primitives.item import Item
    from mcpServer.mcp_primitives.tool import Tool

    tool = Tool.create_simple(name=name, description="synthetic enum tool")
    tool.add_input_property("kind", {"type": "string", "enum": ["cylinder_face", "planar_face"]})
    tool.add_input_property("include", {"type": "array",
                                        "items": {"type": "string", "enum": ["versions", "xref_tree"]}})
    tool.add_input_property("target", {"type": "string"})
    tool.strict_schema()
    return Item.create_tool_item(tool=tool, handler=handler, run_on_main_thread=run_on_main_thread)


def _call(server, name, arguments):
    return asyncio.run(server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }))


@pytest.fixture
def boolean_tool(server):
    """Register declared properties on a tool that records each dispatched argument unchanged."""
    from mcpServer.mcp_primitives.item import Item
    from mcpServer.mcp_primitives.tool import Tool

    calls = []

    def register(properties):
        tool = Tool.create_simple(name="boolean_probe", description="Boolean test tool")
        for name, schema in properties.items():
            tool.add_input_property(name, schema)
        tool.strict_schema()
        server.register(Item.create_tool_item(
            tool=tool, handler=lambda **kw: calls.append(kw) or _ok(), run_on_main_thread=False))
        return calls

    return register


class TestBareWireMarker:
    def test_the_marker_strips_every_description_and_nothing_else(self, server, mcp_server_module,
                                                                  tmp_path, monkeypatch):
        server.register(_enum_tool_item("probe", lambda **kw: _ok()))
        marker = tmp_path / ".wire_bare"
        monkeypatch.setattr(mcp_server_module, "BARE_WIRE_MARKER", str(marker))
        full = server._handle_tools_list(1)["result"]["tools"][0]
        assert full["description"] == "synthetic enum tool"
        marker.write_text("on", encoding="utf-8")
        bare = server._handle_tools_list(1)["result"]["tools"][0]
        assert "description" not in json.dumps(bare)
        assert bare["name"] == "probe"
        assert bare["inputSchema"]["properties"]["kind"]["enum"] == ["cylinder_face", "planar_face"]
        assert bare["inputSchema"]["properties"]["include"]["items"]["enum"] == ["versions", "xref_tree"]
        assert bare["inputSchema"].get("additionalProperties") is False
        marker.unlink()
        assert server._handle_tools_list(1)["result"]["tools"][0]["description"] == "synthetic enum tool"


class TestCapabilityMapSchemaIdentity:
    def _map_payload(self, server):
        response = _call(server, "sys_capability_map", {})
        assert response["result"]["isError"] is False
        return json.loads(response["result"]["content"][0]["text"])

    def test_dispatch_uses_serving_instance_schema_not_the_handler_registry(
            self, mcp_server_module, monkeypatch):
        capability_map = load_tool("sys_capability_map")
        registry_only = _make_tool_item(
            "registry_only_get", lambda **kw: _ok(), required=(), optional=())
        monkeypatch.setattr(capability_map, "get_tools", lambda: [registry_only])
        server = mcp_server_module.SimpleMCPServer()
        server.register(capability_map.item)
        server.register(_make_tool_item("served_probe", lambda **kw: _ok()))

        payload = self._map_payload(server)
        assert payload["families"][0]["family"] == "registry"
        assert payload["schema_fingerprint"] == server.health()["attestation"][
            "schema_fingerprint"]
        assert payload["schema_fingerprint"] != mcp_server_module._schema_fingerprint(
            mcp_server_module._wire_tool_rows({"registry_only_get": registry_only}))

    def test_order_is_stable_and_an_input_schema_change_changes_identity(
            self, mcp_server_module):
        capability_map = load_tool("sys_capability_map")
        first_probe = _make_tool_item("served_probe", lambda **kw: _ok(), required=("a",))
        changed_probe = _make_tool_item("served_probe", lambda **kw: _ok(), required=("changed",))
        first = mcp_server_module.SimpleMCPServer()
        reversed_order = mcp_server_module.SimpleMCPServer()
        changed = mcp_server_module.SimpleMCPServer()
        for item in (capability_map.item, first_probe):
            first.register(item)
        for item in (first_probe, capability_map.item):
            reversed_order.register(item)
        for item in (capability_map.item, changed_probe):
            changed.register(item)

        first_id = self._map_payload(first)["schema_fingerprint"]
        assert first_id == self._map_payload(reversed_order)["schema_fingerprint"]
        assert first_id != self._map_payload(changed)["schema_fingerprint"]

    def test_bare_wire_projection_has_its_own_actual_served_identity(
            self, mcp_server_module, tmp_path, monkeypatch):
        capability_map = load_tool("sys_capability_map")
        server = mcp_server_module.SimpleMCPServer()
        server.register(capability_map.item)
        server.register(_make_tool_item("served_probe", lambda **kw: _ok()))
        marker = tmp_path / ".wire_bare"
        monkeypatch.setattr(mcp_server_module, "BARE_WIRE_MARKER", str(marker))

        full = self._map_payload(server)["schema_fingerprint"]
        assert full == server.health()["attestation"]["schema_fingerprint"]
        marker.write_text("on", encoding="utf-8")
        bare = self._map_payload(server)["schema_fingerprint"]
        assert bare == server.health()["attestation"]["schema_fingerprint"]
        assert bare != full

    @pytest.mark.parametrize("result", [
        {"content": [{"type": "text", "text": "not json"}], "isError": False},
        {"content": [{"type": "text", "text": "failed"}], "isError": True,
         "message": "failed"},
    ])
    def test_malformed_or_error_results_are_not_reclassified(
            self, mcp_server_module, result):
        server = mcp_server_module.SimpleMCPServer()
        server.register(_make_tool_item(
            "sys_capability_map", lambda **kw: result, required=(), optional=()))
        assert _call(server, "sys_capability_map", {})["result"] == result


class TestInitializeProtocolVersionNegotiation:
    def test_initialize_with_supported_version_echoes_it(self, server):
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }))
        assert response["result"]["protocolVersion"] == "2025-03-26"

    def test_initialize_with_unsupported_version_responds_with_supported_version(self, server):
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }))
        assert response["result"]["protocolVersion"] == "2025-03-26"

    def test_initialize_with_no_protocol_version_responds_with_default(self, server):
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
        }))
        assert response["result"]["protocolVersion"] == "2025-03-26"


class TestNonObjectRequestBody:
    def test_batch_array_body_returns_clean_32600_not_a_raise(self, server):
        # a JSON-RPC batch (a list of requests) is not implemented; it must come back as ONE
        # well-formed error object, not an AttributeError -> HTTP 500.
        response = asyncio.run(server.handle_request([
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ]))
        assert response["error"]["code"] == -32600
        assert response["id"] is None                       # a batch has no single id to echo
        assert "batch" in response["error"]["message"].lower()
        assert "result" not in response

    def test_empty_array_body_returns_clean_32600(self, server):
        response = asyncio.run(server.handle_request([]))
        assert response["error"]["code"] == -32600
        assert response["id"] is None

    def test_non_dict_scalar_body_returns_clean_32600(self, server):
        response = asyncio.run(server.handle_request("ping"))
        assert response["error"]["code"] == -32600
        assert response["id"] is None
        assert "request object" in response["error"]["message"]

    def test_dict_body_is_unaffected_by_the_guard(self, server):
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 7, "method": "ping",
        }))
        assert response == {"jsonrpc": "2.0", "id": 7, "result": {}}


class TestToolsCallUnknownTool:
    def test_unknown_tool_is_a_protocol_error_with_code_32602(self, server):
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        }))
        assert "result" not in response
        assert response["error"]["code"] == -32602


class TestToolsCallArgumentValidation:
    def test_unknown_argument_is_an_error_result_and_handler_not_called(self, server):
        calls = {"n": 0}

        def handler(**kwargs):
            calls["n"] += 1
            return _ok()

        server.register(_make_tool_item("x", handler))
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "x", "arguments": {"a": "1", "c": "surprise"}},
        }))
        result = response["result"]
        assert result["isError"] is True
        assert "'c'" in result["message"]
        assert "a" in result["message"] and "b" in result["message"]
        assert result["content"][0]["text"] == result["message"]   # the field a real client reads
        assert calls["n"] == 0

    def test_missing_required_argument_is_an_error_result_and_handler_not_called(self, server):
        calls = {"n": 0}

        def handler(**kwargs):
            calls["n"] += 1
            return _ok()

        server.register(_make_tool_item("x", handler))
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "x", "arguments": {"b": "optional-only"}},
        }))
        result = response["result"]
        assert result["isError"] is True
        assert "'a'" in result["message"]
        assert result["content"][0]["text"] == result["message"]   # the field a real client reads
        assert calls["n"] == 0

    def test_lenient_schema_passes_unknown_keys_to_handler(self, server):
        # a tool that never declared additionalProperties=false stays lenient on the wire AND at
        # the gate - the schema must not promise leniency the server then refuses.
        seen = {}

        def handler(**kwargs):
            seen.update(kwargs)
            return _ok()

        item = _make_tool_item("lenient", handler)
        item.primitive.additional_properties = None    # undeclared = lenient, the wire default
        server.register(item)
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "lenient", "arguments": {"a": "1", "c": "extra"}},
        }))
        assert response["result"]["isError"] is False
        assert seen.get("c") == "extra"

    def test_schema_omitted_arg_reaches_the_handler(self, server, mcp_server_module, monkeypatch):
        # a strict tool may deliberately accept an off-schema kwarg (the handler answers with a
        # targeted redirect) - the gate lets a listed key through instead of shadowing it.
        seen = {}

        def handler(**kwargs):
            seen.update(kwargs)
            return _ok()

        monkeypatch.setattr(mcp_server_module, "_SCHEMA_OMITTED_ARGS",
                            {"x": frozenset({"c"})})
        server.register(_make_tool_item("x", handler))
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "x", "arguments": {"a": "1", "c": "redirect-me"}},
        }))
        assert response["result"]["isError"] is False
        assert seen.get("c") == "redirect-me"

    def test_omitted_args_table_matches_reality(self, mcp_server_module):
        # every _SCHEMA_OMITTED_ARGS entry names a REAL registered tool whose real handler truly
        # accepts the kwarg - a stale entry (tool renamed, kwarg dropped) fails here.
        import inspect
        from conftest import register_all_tools
        items = {i.primitive.name: i for i in register_all_tools()}
        for tool_name, extras in mcp_server_module._SCHEMA_OMITTED_ARGS.items():
            assert tool_name in items, f"omitted-args entry for unknown tool '{tool_name}'"
            h = items[tool_name].handler
            while getattr(h, "__wrapped__", None) is not None:
                h = h.__wrapped__
            params = inspect.signature(h).parameters
            for extra in extras:
                assert extra in params, (
                    f"'{tool_name}' handler does not accept '{extra}' - stale omitted-args entry")

    def test_valid_call_with_optional_argument_omitted_succeeds(self, server):
        seen = {}
        server.register(_make_tool_item("x", lambda **kw: seen.update(kw) or _ok()))
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "x", "arguments": {"a": "1"}},
        }))
        assert response["result"]["isError"] is False
        assert seen == {"a": "1"}

    def test_empty_schema_tool_with_no_arguments_succeeds(self, server):
        calls = {"n": 0}
        server.register(_bare_tool_item("noop", lambda **kw: calls.update(n=calls["n"] + 1) or _ok()))
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "noop", "arguments": {}},
        }))
        assert response["result"]["isError"] is False
        assert calls["n"] == 1

    def test_omitted_arguments_default_to_empty_dict(self, server):
        seen = {"kwargs": None}
        server.register(_bare_tool_item("noop", lambda **kw: seen.update(kwargs=kw) or _ok()))
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "noop"},
        }))
        assert response["result"]["isError"] is False
        assert seen["kwargs"] == {}


class TestToolsCallBooleanValidation:
    @pytest.mark.parametrize("value", ["false", "true", "", "caf\u00e9", 0, 1, 0.0, 1.0,
                                       None, [], [False], {}, {"flag": False}])
    def test_malformed_boolean_never_dispatches(self, server, boolean_tool, value):
        calls = boolean_tool({"flag": {"type": "boolean"}})
        result = _call(server, "boolean_probe", {"flag": value})["result"]
        assert result["isError"] is True and calls == []
        assert "'flag'" in result["message"] and ascii(value) in result["message"]
        expected = "Omit this optional key" if value is None else "Use true or false."
        assert expected in result["message"]
        assert result["message"].isascii()
        assert result["content"][0]["text"] == result["message"]

    @pytest.mark.parametrize("required", [False, True])
    def test_nested_null_remedy_only_offers_omission_for_optional_key(self, server, boolean_tool, required):
        calls = boolean_tool({"shape": {"type": "object", "properties": {
            "enabled": {"type": "boolean"}}, "required": ["enabled"] if required else []}})
        result = _call(server, "boolean_probe", {"shape": {"enabled": None}})["result"]
        assert result["isError"] is True and calls == []
        assert "shape.enabled" in result["message"]
        assert ("Omit this optional key" in result["message"]) is (not required)

    def test_real_booleans_and_omission_reach_handler_unchanged(self, server, boolean_tool):
        calls = boolean_tool({"flag": {"type": "boolean"}})
        for arguments in ({}, {"flag": False}, {"flag": True}):
            assert _call(server, "boolean_probe", arguments)["result"]["isError"] is False
        assert calls[0] == {}
        assert calls[1]["flag"] is False and calls[2]["flag"] is True

    def test_nullable_boolean_allows_only_explicit_null_and_booleans(self, server, boolean_tool):
        calls = boolean_tool({"flag": {"type": ["boolean", "null"]}})
        for value in (None, False, True):
            assert _call(server, "boolean_probe", {"flag": value})["result"]["isError"] is False
            assert calls[-1]["flag"] is value
        assert _call(server, "boolean_probe", {"flag": "false"})["result"]["isError"] is True
        assert len(calls) == 3

    def test_mixed_boolean_unions_preserve_other_declared_types(self, server, boolean_tool):
        calls = boolean_tool({"text": {"type": ["boolean", "string"]},
                              "value": {"type": ["boolean", "integer", "number", "string"]}})
        for value in (False, True, 0, 1, 0.5, "false"):
            arguments = {"text": "false", "value": value}
            assert _call(server, "boolean_probe", arguments)["result"]["isError"] is False
            assert calls[-1]["text"] == "false" and calls[-1]["value"] is value

    @pytest.mark.parametrize("arguments, path", [
        ({"shape": {"capped": "false"}}, "shape.capped"),
        ({"flags": [True, 0]}, "flags[1]"),
        ({"jobs": [{"enabled": True}, {"enabled": "false"}]}, "jobs[1].enabled"),
        ({"groups": [[True], [1]]}, "groups[1][0]"),
    ])
    def test_nested_boolean_refusal_names_full_path_and_never_dispatches(
            self, server, boolean_tool, arguments, path):
        calls = boolean_tool({
            "shape": {"type": "object", "properties": {"capped": {"type": "boolean"}}},
            "flags": {"type": "array", "items": {"type": "boolean"}},
            "jobs": {"type": "array", "items": {
                "type": "object", "properties": {"enabled": {"type": "boolean"}}}},
            "groups": {"type": "array", "items": {
                "type": "array", "items": {"type": "boolean"}}},
        })
        result = _call(server, "boolean_probe", arguments)["result"]
        assert result["isError"] is True and calls == []
        assert repr(path) in result["message"] and "Use true or false." in result["message"]

    def test_nested_valid_leaves_and_undeclared_fields_are_unchanged(
            self, server, boolean_tool, mcp_server_module, monkeypatch):
        calls = boolean_tool({
            "shape": {"type": "object", "properties": {"capped": {"type": "boolean"}}},
            "flags": {"type": "array", "items": {"type": ["boolean", "null"]}},
            "jobs": {"type": "array", "items": {
                "type": "object", "properties": {"enabled": {"type": "boolean"}}}},
            "params": {"type": "array", "items": {"type": "object"}},
        })
        monkeypatch.setattr(mcp_server_module, "_SCHEMA_OMITTED_ARGS",
                            {"boolean_probe": frozenset({"legacy"})})
        arguments = {"shape": {"capped": False, "extra": "false"},
                     "flags": [False, True, None], "jobs": [{}, {"enabled": True}],
                     "params": [{"favorite": "false"}], "legacy": "false"}
        assert _call(server, "boolean_probe", arguments)["result"]["isError"] is False
        assert calls == [arguments]
        assert calls[0]["shape"]["capped"] is False and calls[0]["jobs"][1]["enabled"] is True


class TestToolsCallEnumValidation:
    def test_out_of_enum_value_is_a_named_error_and_handler_not_called(self, server):
        # a permissive client sends kind="faces" (not in the enum) and, without this gate, gets
        # silent wrong behavior (match_count:0) instead of a correction.
        calls = {"n": 0}

        def handler(**kwargs):
            calls["n"] += 1
            return _ok()

        server.register(_enum_tool_item("x", handler))
        result = _call(server, "x", {"kind": "faces"})["result"]
        assert result["isError"] is True
        assert calls["n"] == 0                              # a doomed call never dispatches
        assert "'kind'" in result["message"]                # names the property
        assert "'faces'" in result["message"]               # names the offending value
        assert "cylinder_face" in result["message"] and "planar_face" in result["message"]
        assert result["content"][0]["text"] == result["message"]

    def test_valid_enum_value_passes_through(self, server):
        seen = {}
        server.register(_enum_tool_item("x", lambda **kw: seen.update(kw) or _ok()))
        result = _call(server, "x", {"kind": "planar_face"})["result"]
        assert result["isError"] is False
        assert seen == {"kind": "planar_face"}

    def test_array_of_enum_prop_rejects_a_bad_element(self, server):
        server.register(_enum_tool_item("x", lambda **kw: _ok()))
        result = _call(server, "x", {"include": ["versions", "bogus_slice"]})["result"]
        assert result["isError"] is True
        assert "'include'" in result["message"] and "'bogus_slice'" in result["message"]
        assert "versions" in result["message"]              # the valid values are listed

    def test_array_of_enum_prop_accepts_all_valid_elements(self, server):
        seen = []
        server.register(_enum_tool_item("x", lambda **kw: seen.append(kw) or _ok()))
        assert _call(server, "x", {"include": ["versions", "xref_tree"]})["result"]["isError"] is False
        assert seen == [{"include": ["versions", "xref_tree"]}]

    def test_non_enum_property_is_not_gated(self, server):
        seen = []
        server.register(_enum_tool_item("x", lambda **kw: seen.append(kw) or _ok()))
        assert _call(server, "x", {"target": "anything at all"})["result"]["isError"] is False
        assert seen == [{"target": "anything at all"}]

    def test_tool_without_enums_is_unaffected(self, server):
        # the default fixture tool declares no enum anywhere; every value passes the gate.
        seen = []
        server.register(_make_tool_item("plain", lambda **kw: seen.append(kw) or _ok()))
        assert _call(server, "plain", {"a": "faces"})["result"]["isError"] is False
        assert seen == [{"a": "faces"}]

    def test_none_for_an_optional_enum_prop_is_not_rejected(self, server):
        # an explicit null = unset; the handler's default applies, same as omitting the key.
        seen = []
        server.register(_enum_tool_item("x", lambda **kw: seen.append(kw) or _ok()))
        assert _call(server, "x", {"kind": None})["result"]["isError"] is False
        assert seen == [{"kind": None}]

    def test_unhashable_value_for_an_enum_prop_is_a_named_error_not_a_typeerror(self, server):
        server.register(_enum_tool_item("x", lambda **kw: _ok()))
        result = _call(server, "x", {"kind": ["planar_face"]})["result"]
        assert result["isError"] is True
        assert "'kind'" in result["message"]

    def test_enum_specs_are_precomputed_at_registration(self, server):
        # per-call cost is a dict lookup: the specs exist before any call is made.
        server.register(_enum_tool_item("x", lambda **kw: _ok()))
        specs = server._enum_specs["x"]
        assert specs["kind"]["set"] == frozenset({"cylinder_face", "planar_face"})
        assert specs["include"]["array"] is True
        assert "target" not in specs                        # free strings carry no enum spec


class TestToolsCallHandlerExceptions:
    def test_handler_exception_becomes_iserror_result_not_protocol_error(self, server):
        def handler(**kwargs):
            raise ValueError("boom")

        server.register(_make_tool_item("x", handler))
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "x", "arguments": {"a": "1"}},
        }))
        assert "error" not in response
        result = response["result"]
        assert result["isError"] is True
        assert "Tool 'x' failed: boom" in result["content"][0]["text"]
        assert "Tool 'x' failed: boom" in result["message"]


class TestNotificationsAndPing:
    def test_notification_without_id_returns_none(self, server):
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
        }))
        assert response is None

    def test_ping_returns_empty_result(self, server):
        response = asyncio.run(server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "ping",
        }))
        assert response["result"] == {}


# ── _execute_on_main_thread: the timeout / cancel / claimed contract ─────────
#
# The one place a tool call crosses from the HTTP thread to Fusion's main thread. The scripted
# manager below stands in for TaskManager so each race (completed / timed out+cancelled /
# timed out+claimed / finished inside the cancel window) is forced deterministically.



@pytest.fixture
def fast_timeout(mcp_server_module, monkeypatch):
    monkeypatch.setattr(mcp_server_module, "MAIN_THREAD_TASK_TIMEOUT_S", 0.05)


def _execute(server, mcp_server_module, monkeypatch, tasks, handler, enforce_timeout=True):
    monkeypatch.setattr(mcp_server_module, "TaskManager", tasks)
    return asyncio.run(server._execute_on_main_thread(
        handler, {"a": "1"}, enforce_timeout=enforce_timeout))


class TestExecuteOnMainThread:
    def test_completed_callback_returns_the_handler_result(
            self, server, mcp_server_module, monkeypatch, fast_timeout):
        tasks = _ScriptedTasks(run_after_s=0.0)
        out = _execute(server, mcp_server_module, monkeypatch, tasks, lambda **kw: {"ok": kw})
        assert out == {"ok": {"a": "1"}}

    def test_handler_exception_propagates(
            self, server, mcp_server_module, monkeypatch, fast_timeout):
        def boom(**kw):
            raise RuntimeError("handler blew up")
        tasks = _ScriptedTasks(run_after_s=0.0)
        with pytest.raises(RuntimeError, match="handler blew up"):
            _execute(server, mcp_server_module, monkeypatch, tasks, boom)

    def test_timeout_with_successful_cancel_says_safe_to_retry(
            self, server, mcp_server_module, monkeypatch, fast_timeout):
        # The callback never runs and cancel() wins the race: the operation truly never started,
        # so the error must say so and invite a retry.
        tasks = _ScriptedTasks(cancel_answer=True)
        with pytest.raises(Exception) as exc:
            _execute(server, mcp_server_module, monkeypatch, tasks, lambda **kw: None)
        assert "cancelled before it started" in str(exc.value)
        assert "safe to retry" in str(exc.value)
        assert tasks.cancel_called

    def test_timeout_with_claimed_task_forbids_blind_retry(
            self, server, mcp_server_module, monkeypatch, fast_timeout):
        # cancel() lost the race (the main thread claimed the callback): the side effect may be
        # committing, so the error must NOT claim cancellation and must warn against a blind
        # retry (the double-apply trap).
        tasks = _ScriptedTasks(cancel_answer=False)
        with pytest.raises(Exception) as exc:
            _execute(server, mcp_server_module, monkeypatch, tasks, lambda **kw: None)
        assert "could NOT be cancelled" in str(exc.value)
        assert "Do NOT blindly retry" in str(exc.value)

    def test_finished_inside_the_cancel_window_returns_the_real_result(
            self, server, mcp_server_module, monkeypatch, fast_timeout):
        # The callback completes between the timeout firing and the cancel returning False: the
        # REAL result must be honored, never a fake timeout for work that finished.
        tasks = _ScriptedTasks(cancel_answer=False, run_on_cancel=True)
        out = _execute(server, mcp_server_module, monkeypatch, tasks, lambda **kw: {"late": True})
        assert out == {"late": True}

    def test_enforce_timeout_false_waits_past_the_deadline(
            self, server, mcp_server_module, monkeypatch, fast_timeout):
        # enforce_timeout=False is for uninterruptible work that would still commit: the call
        # holds past the (tiny) timeout and returns the real result instead of a false failure.
        tasks = _ScriptedTasks(run_after_s=0.15)
        out = _execute(server, mcp_server_module, monkeypatch, tasks,
                       lambda **kw: {"slow": True}, enforce_timeout=False)
        assert out == {"slow": True}

    def test_false_event_then_notify_returns_the_actual_result(
            self, server, mcp_server_module, task_manager, monkeypatch):
        import sys
        module = sys.modules[task_manager.__module__]
        monkeypatch.setattr(module.app.fireCustomEvent, "return_value", False)

        async def run():
            waiting = asyncio.create_task(server._execute_on_main_thread(
                lambda **kw: {"ran": kw}, {"a": "1"}, enforce_timeout=False))
            for _ in range(20):
                if task_manager.get_pending_task_count() == 1:
                    break
                await asyncio.sleep(0.01)
            with task_manager._tasks_lock:
                task_id = next(iter(task_manager._pending_tasks))
            _notify(task_manager, mcp_server_module, task_id)
            return await asyncio.wait_for(waiting, timeout=1.0)

        assert asyncio.run(run()) == {"ran": {"a": "1"}}

    def test_reaped_uninterruptible_waiter_exits_and_late_notify_cannot_run(
            self, server, mcp_server_module, task_manager):
        ran = []

        async def run():
            waiting = asyncio.create_task(server._execute_on_main_thread(
                lambda **kw: ran.append(kw), {"a": "1"}, enforce_timeout=False))
            for _ in range(20):
                if task_manager.get_pending_task_count() == 1:
                    break
                await asyncio.sleep(0.01)
            with task_manager._tasks_lock:
                task_id = next(iter(task_manager._pending_tasks))
                task_manager._pending_tasks[task_id]["created"] -= 400.0
            assert task_manager._reap_stale() == 1
            with pytest.raises(Exception, match="dropped before it started"):
                await asyncio.wait_for(waiting, timeout=1.0)
            _notify(task_manager, mcp_server_module, task_id)

        asyncio.run(run())
        assert ran == []


# ── TaskManager: post / claim / cancel / reap on the real class ──────────────

@pytest.fixture
def task_manager(mcp_server_module):
    """The real TaskManager (mock adsk app), reset around each test - it is a singleton whose
    class-level state would otherwise leak between tests."""
    tm = mcp_server_module.TaskManager
    tm.stop()
    tm.start()
    import sys
    sys.modules[tm.__module__].app.fireCustomEvent.return_value = True
    yield tm
    tm.stop()


def _notify(tm, mcp_server_module, task_id):
    """Deliver the custom event the way Fusion's main thread would."""
    import json as _json
    import sys
    handler_cls = sys.modules[mcp_server_module.TaskManager.__module__].TaskEventHandler
    args = type("Args", (), {"additionalInfo": _json.dumps({"task_id": task_id, "command": "x"})})()
    handler_cls(tm._pending_tasks).notify(args)


class TestTaskManager:
    def test_post_then_notify_runs_the_callback_once(self, task_manager, mcp_server_module):
        ran = []
        tid = task_manager.post("cmd", lambda data: ran.append(data), {"k": 1})
        assert tid and task_manager.get_pending_task_count() == 1
        _notify(task_manager, mcp_server_module, tid)
        assert ran == [{"k": 1}]
        assert task_manager.get_pending_task_count() == 0
        _notify(task_manager, mcp_server_module, tid)      # a second delivery finds nothing
        assert ran == [{"k": 1}]

    def test_cancel_before_claim_wins_and_the_callback_never_runs(
            self, task_manager, mcp_server_module):
        ran = []
        tid = task_manager.post("cmd", lambda data: ran.append(data), {})
        assert task_manager.cancel(tid) is True
        _notify(task_manager, mcp_server_module, tid)
        assert ran == [] and task_manager.get_pending_task_count() == 0

    def test_cancel_after_claim_answers_false(self, task_manager, mcp_server_module):
        tid = task_manager.post("cmd", lambda data: None, {})
        _notify(task_manager, mcp_server_module, tid)
        assert task_manager.cancel(tid) is False

    def test_callback_exception_is_contained_by_notify(self, task_manager, mcp_server_module):
        def boom(data):
            raise RuntimeError("callback blew up")
        tid = task_manager.post("cmd", boom, {})
        _notify(task_manager, mcp_server_module, tid)      # must not raise
        assert task_manager.get_pending_task_count() == 0

    def test_stale_orphan_is_reaped_on_the_next_post(self, task_manager):
        ran = []
        tid = task_manager.post("cmd", lambda data: ran.append(data), {})
        with task_manager._tasks_lock:
            task_manager._pending_tasks[tid]["created"] -= 400.0   # older than the 300s TTL
        task_manager.post("cmd2", lambda data: None, {})
        assert task_manager.get_pending_task_count() == 1          # the orphan is gone
        with task_manager._tasks_lock:
            assert tid not in task_manager._pending_tasks

    def test_nested_deliveries_wait_and_drain_once_in_delivery_order(
            self, task_manager, mcp_server_module):
        import sys
        app = sys.modules[task_manager.__module__].app
        ran = []

        def first(data):
            ran.append('first_begin')
            _notify(task_manager, mcp_server_module, third)
            ran.append('first_end')

        first_id = task_manager.post('first', first, {})
        second = task_manager.post('second', lambda data: ran.append('second'), {})
        third = task_manager.post('third', lambda data: ran.append('third'), {})

        def outer(data):
            ran.append('outer_begin')
            fired = app.fireCustomEvent.call_count
            for tid in (second, first_id, second):
                _notify(task_manager, mcp_server_module, tid)
            assert task_manager.get_pending_task_count() == 3
            assert ran == ['outer_begin']
            assert app.fireCustomEvent.call_count == fired
            ran.append('outer_end')

        outer_id = task_manager.post('outer', outer, {})
        _notify(task_manager, mcp_server_module, outer_id)
        assert ran == ['outer_begin', 'outer_end', 'second', 'first_begin', 'first_end', 'third']
        assert task_manager.get_pending_task_count() == 0
        assert not task_manager._dispatching and not task_manager._deferred_tasks

    @pytest.mark.parametrize('disposition', ['cancel', 'reap', 'stop'])
    def test_removed_deferred_work_never_executes(
            self, task_manager, mcp_server_module, disposition):
        ran, dropped = [], []
        deferred = task_manager.post('deferred', lambda data: ran.append('deferred'), {},
                                     on_drop=dropped.append)

        def outer(data):
            _notify(task_manager, mcp_server_module, deferred)
            assert deferred in task_manager._pending_tasks
            if disposition == 'cancel':
                assert task_manager.cancel(deferred) is True
            elif disposition == 'reap':
                task_manager._pending_tasks[deferred]['created'] -= 301
                assert task_manager._reap_stale() == 1
            else:
                assert task_manager.stop() is True
            ran.append('outer_end')

        outer_id = task_manager.post('outer', outer, {})
        _notify(task_manager, mcp_server_module, outer_id)
        _notify(task_manager, mcp_server_module, deferred)
        assert ran == ['outer_end']
        expected = {'cancel': [], 'reap': ['pending_task_reaped'],
                    'stop': ['task_manager_stopped_before_claim']}
        assert dropped == expected[disposition]
        assert task_manager.get_pending_task_count() == 0

    @pytest.mark.parametrize('age, executes', [(300.0, True), (300.001, False)])
    def test_deferred_claim_checks_expiry_at_the_ttl_boundary(
            self, task_manager, mcp_server_module, monkeypatch, age, executes):
        import sys
        clock, ran, dropped = [1000.0], [], []
        monkeypatch.setattr(sys.modules[task_manager.__module__].time,
                            'monotonic', lambda: clock[0])
        deferred = task_manager.post('deferred', lambda data: ran.append('deferred'), {},
                                     on_drop=dropped.append)

        def outer(data):
            _notify(task_manager, mcp_server_module, deferred)
            clock[0] += age
            ran.append('outer_end')

        outer_id = task_manager.post('outer', outer, {})
        _notify(task_manager, mcp_server_module, outer_id)
        assert ran == ['outer_end'] + (['deferred'] if executes else [])
        assert dropped == ([] if executes else ['pending_task_reaped'])
        assert task_manager.get_pending_task_count() == 0

    def test_callback_error_is_reported_and_deferred_work_still_drains(
            self, task_manager, mcp_server_module, monkeypatch):
        import sys
        errors, ran = [], []
        monkeypatch.setattr(sys.modules[task_manager.__module__].futil,
                            'handle_error', errors.append)
        deferred = task_manager.post('deferred', lambda data: ran.append('deferred'), {})

        def outer(data):
            _notify(task_manager, mcp_server_module, deferred)
            raise RuntimeError('outer failed')

        outer_id = task_manager.post('outer', outer, {})
        _notify(task_manager, mcp_server_module, outer_id)
        assert errors == ['TaskManager.callback[outer]']
        assert ran == ['deferred'] and task_manager.get_pending_task_count() == 0
        assert not task_manager._dispatching

    def test_post_refuses_a_non_callable(self, task_manager):
        assert task_manager.post("cmd", "not-callable", {}) is None


# ── MCPHandler._origin_ok: the DNS-rebinding guard ──────────────────────────
#
# The server binds loopback, but any page in the victim's browser can POST to
# http://127.0.0.1:37182. The Origin header is the only thing separating a local browser client
# from a hostile page, so the check must compare the PARSED scheme+hostname: a substring test
# admits http://localhost.evil.com, which resolves to the attacker's server.

# ── the JSON door: NaN / Infinity are refused before any tool sees them ─────────────────────────
#
# Python's decoder accepts the three NON-STANDARD literals by default, and a non-finite number
# passes every zero/negative guard it later meets, so the refusal belongs at the parse.



def _post(mcp_server_module, body: bytes, server=None, headers=None):
    """The real do_POST driven over `body`; returns the probe it wrote its answer into."""
    probe = _PostProbe(body, server)
    probe.headers.update(headers or {})
    mcp_server_module.MCPHandler.do_POST(probe)
    return probe


class TestSessionHeader:
    @pytest.mark.parametrize('session', ['stale-session', ''])
    @pytest.mark.parametrize('path', ['/mcp', '/'])
    def test_stale_header_refuses_before_native_dispatch(
            self, mcp_server_module, server, monkeypatch, session, path):
        posted, ran = [], []
        server.register(_bare_tool_item('native_probe', lambda: ran.append('ran') or _ok(),
                                       run_on_main_thread=True))

        async def execute(handler, arguments, enforce_timeout=True):
            posted.append(arguments)
            return handler(**arguments)

        monkeypatch.setattr(server, '_execute_on_main_thread', execute)
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                           'params': {'name': 'native_probe', 'arguments': {}}}).encode()
        probe = _PostProbe(body, server)
        probe.path = path
        probe.headers[mcp_server_module.SESSION_HEADER] = session
        mcp_server_module.MCPHandler.do_POST(probe)
        assert probe.responses == [404] and probe.errors == []
        assert probe.response_headers == [('Content-Length', '0')]
        assert probe.wfile.getvalue() == b''
        assert posted == [] and ran == []

    @pytest.mark.parametrize('session', [None, 'fresh'])
    def test_headerless_and_fresh_calls_remain_admitted(
            self, mcp_server_module, server, session):
        ran = []
        server.register(_bare_tool_item('read_probe', lambda: ran.append('read') or _ok()))
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                           'params': {'name': 'read_probe', 'arguments': {}}}).encode()
        headers = {} if session is None else {mcp_server_module.SESSION_HEADER: server.session_id}
        probe = _post(mcp_server_module, body, server, headers)
        assert probe.errors == [] and probe.responses == [200] and ran == ['read']

    @pytest.mark.parametrize('session', [None, 'stale-session', 'fresh'])
    def test_initialize_remains_admitted(
            self, mcp_server_module, server, session):
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                           'params': {'protocolVersion': '2025-03-26'}}).encode()
        value = server.session_id if session == 'fresh' else session
        headers = {} if value is None else {mcp_server_module.SESSION_HEADER: value}
        probe = _post(mcp_server_module, body, server, headers)
        assert probe.errors == [] and probe.responses == [200]
        assert json.loads(probe.wfile.getvalue())['result']['serverInfo']['name'] == server.name

    def test_health_diagnostic_still_answers_a_stale_header(self, mcp_server_module, server):
        probe = _PostProbe(b'', server)
        probe.path = '/health'
        probe.headers[mcp_server_module.SESSION_HEADER] = 'stale-session'
        mcp_server_module.MCPHandler.do_GET(probe)
        assert probe.errors == [] and probe.responses == [200]
        assert json.loads(probe.wfile.getvalue())['session_id'] == server.session_id


class TestJsonConstantRefusal:
    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_the_hook_refuses_each_literal_by_name(self, mcp_server_module, literal):
        with pytest.raises(ValueError) as excinfo:
            mcp_server_module._refuse_json_constant(literal)
        assert literal in str(excinfo.value)

    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_json_loads_with_the_hook_refuses_the_literal_inside_a_body(self, mcp_server_module,
                                                                        literal):
        with pytest.raises(ValueError) as excinfo:
            json.loads('{"length": %s}' % literal,
                       parse_constant=mcp_server_module._refuse_json_constant)
        assert literal in str(excinfo.value)

    def test_a_finite_number_still_parses_with_the_hook_installed(self, mcp_server_module):
        # the boundary: only the three literals are refused, not numbers in general.
        parsed = json.loads('{"length": -0.0, "big": 1e308}',
                            parse_constant=mcp_server_module._refuse_json_constant)
        assert parsed == {"length": -0.0, "big": 1e308}

    @pytest.mark.parametrize("payload", [
        '{"length": 1.7976931348623159e308}',
        '{"length": -1.7976931348623159e308}',
        '{"nested": {"length": 1.7976931348623159e308}}'])
    def test_json_loads_with_the_float_hook_refuses_overflow(self, mcp_server_module, payload):
        with pytest.raises(ValueError, match="finite"):
            json.loads(payload, parse_constant=mcp_server_module._refuse_json_constant,
                       parse_float=mcp_server_module._refuse_json_float)

    def test_json_loads_float_hook_preserves_max_finite_and_integers(self, mcp_server_module):
        parsed = json.loads('{"length": 1.7976931348623157e308, "whole": 9007199254740993}',
                            parse_constant=mcp_server_module._refuse_json_constant,
                            parse_float=mcp_server_module._refuse_json_float)
        assert parsed["length"] == 1.7976931348623157e308
        assert parsed["whole"] == 9007199254740993

    @pytest.mark.parametrize("value", ["1.7976931348623159e308", "-1.7976931348623159e308"])
    def test_http_overflow_is_refused_before_real_numeric_tool_dispatch(self, mcp_server_module, value):
        calls = []
        tool_server = mcp_server_module.SimpleMCPServer()
        tool_server.register(_number_tool_item("number_probe",
                                               lambda **kwargs: calls.append(kwargs) or _ok()))
        body = ('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"number_probe",'
                '"arguments":{"value":%s}}}' % value).encode()
        probe = _post(mcp_server_module, body, tool_server)
        assert probe.responses == [] and probe.errors[0][0] == 400
        assert calls == [] and value in probe.errors[0][1]

    def test_http_nested_finite_values_dispatch_and_nested_overflow_does_not(self, mcp_server_module):
        calls = []
        tool_server = mcp_server_module.SimpleMCPServer()
        tool_server.register(_nested_number_tool_item("nested_probe",
                                                     lambda **kwargs: calls.append(kwargs) or _ok()))
        finite = ('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"nested_probe",'
                  '"arguments":{"payload":{"nested":1.7976931348623157e308},'
                  '"values":[-1.0,1e308]}}}').encode()
        probe = _post(mcp_server_module, finite, tool_server)
        assert probe.errors == [] and probe.responses == [200]
        assert len(calls) == 1 and calls[0]["payload"]["nested"] == 1.7976931348623157e308

        overflow = finite.replace(b"1.7976931348623157e308", b"1.7976931348623159e308")
        probe = _post(mcp_server_module, overflow, tool_server)
        assert probe.responses == [] and probe.errors[0][0] == 400 and len(calls) == 1

    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_a_post_carrying_the_literal_is_refused_400_naming_it(self, mcp_server_module, literal):
        body = ('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"model_extrude",'
                '"arguments":{"distance":%s}}}' % literal).encode()
        probe = _post(mcp_server_module, body)
        assert probe.responses == []                     # never dispatched
        code, message = probe.errors[0]
        assert code == 400
        assert literal in message                        # the reason survives to the wire

    def test_a_malformed_body_still_refuses_400_and_says_why(self, mcp_server_module):
        probe = _post(mcp_server_module, b'{"jsonrpc": "2.0", ')
        code, message = probe.errors[0]
        assert code == 400 and message.startswith("Invalid JSON:")
        assert "\n" not in message                       # it rides in the HTTP status line

    def test_a_well_formed_body_still_reaches_dispatch(self, mcp_server_module):
        probe = _post(mcp_server_module, b'{"jsonrpc":"2.0","method":"notifications/initialized"}')
        assert probe.errors == [] and probe.responses == [202]


def _origin_allowed(mcp_server_module, origin):
    """Run the real _origin_ok against a header map holding `origin` (None = header absent)."""
    probe = types.SimpleNamespace(headers={} if origin is None else {'Origin': origin})
    return mcp_server_module.MCPHandler._origin_ok(probe)


class TestOriginGuard:
    @pytest.mark.parametrize("origin", [
        "http://localhost.evil.com",        # loopback label as a SUBDOMAIN of an attacker domain
        "http://127.0.0.1.evil.com",
        "http://localhost.evil.com:37182",  # our own port on someone else's host
        "https://evil.com",
        "http://evil.localhost.com",
        "http://127.0.0.1@evil.com",        # loopback in the userinfo, not the host
        "not-a-url",                        # unparseable -> refused, never allowed
        "http://localhost:notaport",        # malformed port
        "http://[::1",                      # malformed IPv6 literal
        "null",                             # a sandboxed (attacker-controlled) iframe sends this
        "file://localhost/etc/passwd",      # loopback host but not an http(s) scheme
    ])
    def test_hostile_origin_is_refused(self, mcp_server_module, origin):
        assert _origin_allowed(mcp_server_module, origin) is False

    @pytest.mark.parametrize("origin", [
        None,                               # no header at all: local CLI clients and our probes
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1:8080",
        "https://localhost",
        "http://[::1]:5000",                # urlsplit().hostname strips the brackets -> '::1'
        "HTTP://LOCALHOST:37182",           # scheme and host are case-insensitive
    ])
    def test_loopback_origin_is_allowed(self, mcp_server_module, origin):
        assert _origin_allowed(mcp_server_module, origin) is True


def test_health_revalidates_loaded_source_instead_of_caching_startup_success(
        mcp_server_module, tmp_path):
    import sys
    from lib import loaded_attestation

    name = "loaded_attestation_health_case"
    path = tmp_path / (name + ".py")
    path.write_text("VALUE = 'old'\n", encoding="utf-8")
    try:
        loaded_attestation.begin(str(tmp_path))
        module = types.ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
        loaded_attestation.finish()
        server = mcp_server_module.SimpleMCPServer(attestation=loaded_attestation.attest)
        assert server.health()["attestation"]["complete"] is True
        path.write_text("VALUE = 'new'\n", encoding="utf-8")
        current = server.health()["attestation"]
        assert current["complete"] is False
        assert any("differs from source" in problem for problem in current["problems"])
    finally:
        loaded_attestation.finish()
        sys.modules.pop(name, None)


def test_health_read_does_not_end_an_active_capture(mcp_server_module, tmp_path):
    import sys
    from lib import loaded_attestation

    prior = sys.getprofile()
    try:
        loaded_attestation.begin(str(tmp_path))
        installed = sys.getprofile()
        server = mcp_server_module.SimpleMCPServer(attestation=loaded_attestation.attest)
        current = server.health()["attestation"]
        assert current["complete"] is False
        assert current["problems"] == ["capture window is still active"]
        assert sys.getprofile() is installed
    finally:
        loaded_attestation.finish()
        assert sys.getprofile() is prior


# -- the bound address: read off the socket, published by /health and sys_capability_map --------

class _NoSocketServer:
    """ThreadedHTTPServer's surface with no socket; `reported` stands in for the bound address."""

    made = []
    reported = None
    refuse = None

    def __init__(self, address, handler_cls):
        type(self).made.append(address)
        if type(self).refuse is not None:
            raise type(self).refuse
        self.server_address = type(self).reported or address

    def serve_forever(self):
        raise AssertionError("the serving loop must not run in a unit test")

    def shutdown(self):
        pass

    def server_close(self):
        pass


class _IdleThread:
    def __init__(self, target=None, daemon=None, name=None):
        pass

    def start(self):
        pass


@pytest.fixture
def socketless(mcp_server_module, monkeypatch):
    """The real start_server with its bind and serving thread replaced, and a clean bound record."""
    mcp = mcp_server_module
    fake = type("Bound", (_NoSocketServer,), {"made": [], "reported": None, "refuse": None,
                                              "real": mcp.ThreadedHTTPServer})
    monkeypatch.setattr(mcp, "ThreadedHTTPServer", fake)
    monkeypatch.setattr(mcp.threading, "Thread", _IdleThread)
    monkeypatch.setattr(mcp.drawing_jobs, "_DEFAULT_STORE", mcp.drawing_jobs._DEFAULT_STORE)
    monkeypatch.setattr(mcp.endpoint, "_bound", None)
    return mcp, fake


def _map_reply(monkeypatch):
    capability_map = load_tool("sys_capability_map")
    monkeypatch.setattr(capability_map, "get_tools", lambda: [])
    result = capability_map.handler()
    assert result["isError"] is False
    return result["content"][0]["text"]


class TestTheBoundAddressIsPublished:
    def test_health_and_the_capability_map_report_what_the_socket_bound(self, socketless,
                                                                        monkeypatch):
        mcp, fake = socketless
        fake.reported = ("127.0.0.1", 40002)       # the socket's answer, not the port asked for
        result = mcp.start_server("127.0.0.1", 40001, items=[], job_store=object())
        assert result["status"] == mcp.START_OK, result
        expected = {"host": "127.0.0.1", "port": 40002, "mcp_url": "http://127.0.0.1:40002/mcp"}
        assert result["mcp"].health()["bound"] == expected
        assert json.loads(_map_reply(monkeypatch))["bound"] == expected

    def test_with_no_running_server_neither_read_states_a_port(self, socketless, monkeypatch):
        mcp, _fake = socketless
        result = mcp.start_server("127.0.0.1", 40001, items=[], job_store=object())
        assert mcp.stop_server(result["http_server"], None) is True
        text = _map_reply(monkeypatch)
        assert json.loads(text)["bound"] is None
        assert str(mcp.endpoint.DEFAULT_PORT) not in text and "40001" not in text
        assert mcp.SimpleMCPServer().health()["bound"] is None

    def test_a_refused_bind_is_tried_once_on_the_asked_port(self, socketless):
        import errno

        mcp, fake = socketless
        fake.refuse = OSError(errno.EADDRINUSE, "address already in use")
        result = mcp.start_server("127.0.0.1", 40001, items=[], job_store=object())
        assert result == {"status": mcp.START_PORT_IN_USE, "port": 40001}
        assert fake.made == [("127.0.0.1", 40001)], "one bind attempt, on exactly the asked port"
        assert mcp.endpoint.bound() is None
        # Off Windows the bind reuses the address and server_bind probes the port instead.
        if mcp.os.name == "nt":
            assert fake.real.allow_reuse_address is False, "a taken port must refuse the bind"


class _Reply:
    """urlopen's context-manager response: headers, read() and readline() over fixed bytes."""

    def __init__(self, body, content_type="application/json", session=None):
        self._stream = io.BytesIO(body)
        self.headers = {"Content-Type": content_type}
        if session is not None:
            self.headers["Mcp-Session-Id"] = session

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read1(self, size=-1):
        return self._stream.read1(size)


def _initialize_body(name):
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": name}}})


class TestIdentifyListener:
    def _identify(self, mcp, monkeypatch, reply, ping_reply=None):
        import urllib.request

        asked = []

        def urlopen(request, timeout=None):
            asked.append((request.full_url, request.get_method(), timeout,
                          json.loads(request.data), dict(request.header_items())))
            chosen = reply if len(asked) == 1 else ping_reply
            if isinstance(chosen, Exception):
                raise chosen
            return chosen

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        found = mcp.identify_listener("127.0.0.1", 40123, deadline_s=1.0)
        assert asked[0][:3] == ("http://127.0.0.1:40123/mcp", "POST", 1.0)
        assert len(asked) == (1 if ping_reply is None else 2)
        if ping_reply is not None:
            assert asked[1][:2] == ("http://127.0.0.1:40123/mcp", "POST")
            assert 0 < asked[1][2] <= 1.0
            assert asked[1][3] == {"jsonrpc": "2.0", "id": 2, "method": "ping"}
            assert not any(key.lower() == "mcp-session-id" for key in asked[1][4])
        return found

    def test_our_own_server_is_named_with_its_session(self, mcp_server_module, monkeypatch):
        mcp = mcp_server_module
        reply = _Reply(json.dumps(json.loads(_initialize_body(mcp.SERVER_NAME)), indent=2).encode(),
                       session="private-scope")
        ping = _Reply(b'{"jsonrpc":"2.0","id":2,"result":{}}', session="s-1")
        assert self._identify(mcp, monkeypatch, reply, ping) == {
            "kind": mcp.LISTENER_OURS, "name": mcp.SERVER_NAME, "session_id": "s-1"}

    @pytest.mark.parametrize("ping", [
        OSError("ping unavailable"),
        _Reply(b'{"jsonrpc":"2.0","id":2,"result":{}}'),
        _Reply(b'{"jsonrpc":"2.0","id":99,"result":{}}', session="s-1"),
        _Reply(b'{"jsonrpc":"2.0","id":2,"error":{},"result":{}}', session="s-1"),
    ])
    def test_unread_serving_identity_never_uses_the_private_scope(self, mcp_server_module,
                                                               monkeypatch, ping):
        mcp = mcp_server_module
        initial = _Reply(_initialize_body(mcp.SERVER_NAME).encode(), session="private-scope")
        assert self._identify(mcp, monkeypatch, initial, ping) == {
            "kind": mcp.LISTENER_UNIDENTIFIED, "name": None, "session_id": None}

    def test_real_signed_initialize_is_identified_by_the_serving_load(
            self, server, mcp_server_module, cancel_transport):
        from urllib.parse import urlsplit
        address = urlsplit(cancel_transport['url'])
        assert cancel_transport['scope']() != server.session_id
        assert mcp_server_module.identify_listener(address.hostname, address.port) == {
            "kind": mcp_server_module.LISTENER_OURS,
            "name": mcp_server_module.SERVER_NAME, "session_id": server.session_id}

    @pytest.mark.parametrize("completed_at", [.75, 1.25])
    def test_ping_identity_is_published_only_before_the_original_deadline(
            self, mcp_server_module, monkeypatch, completed_at):
        from types import SimpleNamespace
        mcp = mcp_server_module
        now = [0.0]
        monkeypatch.setattr(mcp, 'time', SimpleNamespace(monotonic=lambda: now[0]))
        monkeypatch.setattr(mcp, 'threading', SimpleNamespace(Thread=lambda target, **kw:
                            SimpleNamespace(start=target, join=lambda timeout: None)))
        initial = _Reply(_initialize_body(mcp.SERVER_NAME).encode(), session='private-scope')
        ping = _Reply(b'data: {"jsonrpc":"2.0","id":2,"result":{}}\n\n',
                      content_type='text/event-stream', session='s-1')
        read = ping.read1

        def completing_read(size):
            now[0] = completed_at
            return read(size)

        monkeypatch.setattr(ping, 'read1', completing_read)
        found = self._identify(mcp, monkeypatch, initial, ping)
        assert found == ({'kind': mcp.LISTENER_OURS, 'name': mcp.SERVER_NAME, 'session_id': 's-1'}
                         if completed_at < 1.0 else
                         {'kind': mcp.LISTENER_UNIDENTIFIED, 'name': None, 'session_id': None})

    def test_another_server_is_named_from_an_event_stream_reply(self, mcp_server_module,
                                                               monkeypatch):
        mcp = mcp_server_module
        body = b"event: message\ndata: " + _initialize_body("Some Other Server").encode() + b"\n\n"
        reply = _Reply(body, content_type="text/event-stream", session="s-2")
        assert self._identify(mcp, monkeypatch, reply) == {
            "kind": mcp.LISTENER_OTHER, "name": "Some Other Server", "session_id": None}

    @pytest.mark.parametrize("reply", [
        OSError("connection refused"),
        _Reply(b"<html>not an MCP server</html>"),
        _Reply(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode()),
    ])
    def test_no_usable_name_is_unidentified(self, mcp_server_module, monkeypatch, reply):
        mcp = mcp_server_module
        assert self._identify(mcp, monkeypatch, reply) == {
            "kind": mcp.LISTENER_UNIDENTIFIED, "name": None, "session_id": None}


class TestIdentifyListenerDeadline:
    @pytest.mark.parametrize("drip", ["headers", "body"])
    def test_a_dripping_reply_is_abandoned_at_the_wall_deadline(self, mcp_server_module, drip):
        # a real loopback listener on an ephemeral port that sends one line every 40 ms for 2.4 s
        # before its answer - in the response headers or in an event-stream body - so no single
        # socket wait ever times out.
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Dripper(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                head = b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                line = b"X-Drip: 1\r\n" if drip == "headers" else b": heartbeat\n"
                try:
                    self.wfile.write(head + (b"" if drip == "headers" else b"\r\n"))
                    for _ in range(60):
                        self.wfile.write(line)
                        self.wfile.flush()
                        time.sleep(0.04)
                    self.wfile.write((b"\r\n" if drip == "headers" else b"") + b"data: "
                                     + _initialize_body("Slow Listener").encode() + b"\n\n")
                except OSError:
                    pass                    # the abandoned client hung up

            def log_message(self, *args):
                pass

        mcp = mcp_server_module
        listener = ThreadingHTTPServer(("127.0.0.1", 0), Dripper)
        serving = threading.Thread(target=listener.serve_forever, daemon=True)
        serving.start()
        try:
            started = time.monotonic()
            found = mcp.identify_listener("127.0.0.1", listener.server_address[1], deadline_s=0.3)
            elapsed = time.monotonic() - started
            assert found == {"kind": mcp.LISTENER_UNIDENTIFIED, "name": None, "session_id": None}
            assert elapsed < 1.0, f"the caller waited {elapsed:.2f} s past a 0.3 s deadline"
            # an exchange abandoned in the body ends itself at its next read instead of
            # following the drip; one still inside the header read ends with the listener.
            for probe in [t for t in threading.enumerate() if t.name == "FE-MCP-ListenerProbe"]:
                probe.join(0.7 if drip == "body" else 5)
                assert not probe.is_alive(), "the abandoned probe is still reading the drip"
        finally:
            listener.shutdown()
            listener.server_close()
            serving.join(2)


class TestCancellationClientScope:
    def test_http_initializations_issue_distinct_client_scopes(
            self, server, mcp_server_module):
        import threading
        import urllib.request

        bound = type('CancellationScopeHandler', (mcp_server_module.MCPHandler,),
                     {'mcp_server': server})
        httpd = mcp_server_module.ThreadedHTTPServer(('127.0.0.1', 0), bound)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = 'http://127.0.0.1:%d/mcp' % httpd.server_address[1]
            scopes = []
            for request_id in (1, 2):
                body = json.dumps({'jsonrpc': '2.0', 'id': request_id,
                                   'method': 'initialize', 'params': {}}).encode('utf-8')
                with urllib.request.urlopen(urllib.request.Request(
                        url, data=body, headers={'Content-Type': 'application/json'}),
                        timeout=2) as response:
                    scopes.append(response.headers[mcp_server_module.SESSION_HEADER])
                    assert json.load(response)['result']['protocolVersion'] == '2025-03-26'
            assert scopes[0] != scopes[1]
            assert server.health()['session_id'] == server.session_id
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


@pytest.fixture
def cancel_transport(server, mcp_server_module, task_manager):
    import concurrent.futures
    import threading
    import time
    import urllib.request

    bound = type('QueuedCancellationHandler', (mcp_server_module.MCPHandler,),
                 {'mcp_server': server})
    httpd = mcp_server_module.ThreadedHTTPServer(('127.0.0.1', 0), bound)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    url = 'http://127.0.0.1:%d/mcp' % httpd.server_address[1]
    effects = []
    server.register(_make_tool_item('queued', lambda a: effects.append(a) or {'applied': a},
                                    optional=(), run_on_main_thread=True))
    server.tools['queued'].enforce_timeout = False

    def post(body, scope=None):
        headers = {'Content-Type': 'application/json'}
        if scope is not None:
            headers[mcp_server_module.SESSION_HEADER] = scope
        request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(request, timeout=2) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None, response.headers.get(
                mcp_server_module.SESSION_HEADER)

    def scope():
        return post({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})[2]

    def call(scope_id, request_id, value):
        return pool.submit(post, {'jsonrpc': '2.0', 'id': request_id, 'method': 'tools/call',
                                  'params': {'name': 'queued', 'arguments': {'a': value}}}, scope_id)

    def pending(values):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with task_manager._tasks_lock:
                found = {info['data']['arguments']['a']: task_id for task_id, info
                         in task_manager._pending_tasks.items()}
            if set(found) == set(values):
                return found
            time.sleep(0.001)
        pytest.fail('controlled pending values did not arrive: %r' % found)

    yield {'post': post, 'scope': scope, 'call': call, 'pending': pending, 'effects': effects,
           'url': url, 'pool': pool, 'bound_handler': bound}
    task_manager.stop()
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)
    pool.shutdown(wait=False, cancel_futures=True)


def _cancel_notice(request_id):
    return {'jsonrpc': '2.0', 'method': 'notifications/cancelled',
            'params': {'requestId': request_id}}


class TestQueuedCancellation:
    def test_cancelled_queue_does_not_run_and_the_next_call_runs_once(
            self, server, mcp_server_module, task_manager, cancel_transport):
        wire = cancel_transport
        scope = wire['scope']()
        first = wire['call'](scope, 7, 'abandoned')
        old_id = wire['pending'](['abandoned'])['abandoned']
        assert wire['post'](_cancel_notice(7), scope)[:2] == (202, None)
        assert first.result(timeout=2)[:2] == (202, None)
        _notify(task_manager, mcp_server_module, old_id)
        assert wire['effects'] == []
        assert server._active_calls == {}
        second = wire['call'](scope, 8, 'next')
        task_id = wire['pending'](['next'])['next']
        _notify(task_manager, mcp_server_module, task_id)
        reply = second.result(timeout=2)
        assert reply[0] == 200 and reply[1]['result'] == {'applied': 'next'}
        assert wire['effects'] == ['next']
        assert server._active_calls == {}

    def test_same_request_id_in_other_client_is_not_cancelled(
            self, server, mcp_server_module, task_manager, cancel_transport):
        wire = cancel_transport
        first_scope, other_scope = wire['scope'](), wire['scope']()
        first = wire['call'](first_scope, 7, 'first')
        other = wire['call'](other_scope, 7, 'other')
        ids = wire['pending'](['first', 'other'])
        wire['post'](_cancel_notice(7), first_scope)
        assert first.result(timeout=2)[:2] == (202, None)
        assert not other.done()
        assert task_manager.get_pending_task_count() == 1
        _notify(task_manager, mcp_server_module, ids['first'])
        _notify(task_manager, mcp_server_module, ids['other'])
        assert other.result(timeout=2)[1]['result'] == {'applied': 'other'}
        assert wire['effects'] == ['other']
        assert server._active_calls == {}

    @pytest.mark.parametrize('sender', ['anonymous', 'legacy', 'other_client'])
    def test_unowned_notice_cannot_drop_a_queued_call(
            self, server, mcp_server_module, task_manager, cancel_transport, sender):
        wire = cancel_transport
        scope = wire['scope']()
        first = wire['call'](scope, 7, 'kept')
        task_id = wire['pending'](['kept'])['kept']
        sender_scope = {'anonymous': None, 'legacy': server.session_id,
                        'other_client': wire['scope']()}[sender]
        assert wire['post'](_cancel_notice(7), sender_scope)[0] == 202
        assert task_manager.get_pending_task_count() == 1
        assert not first.done()
        _notify(task_manager, mcp_server_module, task_id)
        assert first.result(timeout=2)[1]['result'] == {'applied': 'kept'}
        assert wire['effects'] == ['kept']
        assert server._active_calls == {}

    @pytest.mark.parametrize('params', [None, [], {}, {'requestId': True},
        {'requestId': []}, {'requestId': {}}, {'requestId': 99}, {'requestId': 7, 'reason': []}])
    def test_unknown_or_malformed_notice_does_not_cancel(
            self, server, mcp_server_module, task_manager, cancel_transport, params):
        wire = cancel_transport
        scope = wire['scope']()
        first = wire['call'](scope, 7, 'kept')
        task_id = wire['pending'](['kept'])['kept']
        assert wire['post']({'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                             'params': params}, scope)[0] == 202
        assert task_manager.get_pending_task_count() == 1
        _notify(task_manager, mcp_server_module, task_id)
        assert first.result(timeout=2)[1]['result'] == {'applied': 'kept'}
        assert wire['effects'] == ['kept']

    def test_numeric_and_string_ids_are_distinct(
            self, server, mcp_server_module, task_manager, cancel_transport):
        wire = cancel_transport
        scope = wire['scope']()
        numeric = wire['call'](scope, 7, 'number')
        string = wire['call'](scope, '7', 'string')
        ids = wire['pending'](['number', 'string'])
        wire['post'](_cancel_notice(7), scope)
        assert numeric.result(timeout=2)[:2] == (202, None)
        _notify(task_manager, mcp_server_module, ids['number'])
        _notify(task_manager, mcp_server_module, ids['string'])
        assert string.result(timeout=2)[1]['result'] == {'applied': 'string'}
        assert wire['effects'] == ['string']

    def test_duplicate_live_id_refuses_without_replacing_the_original(
            self, server, mcp_server_module, task_manager, cancel_transport):
        wire = cancel_transport
        scope = wire['scope']()
        first = wire['call'](scope, 7, 'first')
        task_id = wire['pending'](['first'])['first']
        second = wire['call'](scope, 7, 'duplicate').result(timeout=2)
        assert second[1]['error']['code'] == -32600
        assert 'already in progress' in second[1]['error']['message']
        _notify(task_manager, mcp_server_module, task_id)
        assert first.result(timeout=2)[1]['result'] == {'applied': 'first'}
        assert wire['effects'] == ['first']

    def test_notice_during_post_is_bound_and_removed_before_late_notify(
            self, server, mcp_server_module, task_manager, cancel_transport, monkeypatch):
        wire = cancel_transport
        scope = wire['scope']()
        original = task_manager.post
        posted = []

        def post_and_cancel(*args, **kwargs):
            task_id = original(*args, **kwargs)
            posted.append(task_id)
            server._cancel_request(scope, {'requestId': 7})
            return task_id

        monkeypatch.setattr(task_manager, 'post', post_and_cancel)
        first = wire['call'](scope, 7, 'never')
        assert first.result(timeout=2)[:2] == (202, None)
        assert len(posted) == 1 and task_manager.get_pending_task_count() == 0
        _notify(task_manager, mcp_server_module, posted[0])
        assert wire['effects'] == []
        assert server._active_calls == {}

    def test_cancellation_after_handler_entry_keeps_the_real_result(
            self, server, mcp_server_module, task_manager, cancel_transport, monkeypatch):
        import threading
        wire = cancel_transport
        scope = wire['scope']()
        entered, release = threading.Event(), threading.Event()
        applied = []

        def handler(a):
            entered.set()
            assert release.wait(timeout=2)
            applied.append(a)
            return {'applied': a}

        monkeypatch.setattr(server.tools['queued'], 'handler', handler)
        first = wire['call'](scope, 7, 'running')
        task_id = wire['pending'](['running'])['running']
        delivery = wire['pool'].submit(_notify, task_manager, mcp_server_module, task_id)
        try:
            assert entered.wait(timeout=1)
            assert wire['post'](_cancel_notice(7), scope)[:2] == (202, None)
            assert not first.done() and applied == []
        finally:
            release.set()
        delivery.result(timeout=2)
        assert first.result(timeout=2)[1]['result'] == {'applied': 'running'}
        assert applied == ['running'] and server._active_calls == {}

    def test_forged_or_previous_load_scope_is_refused_before_dispatch(
            self, server, mcp_server_module, task_manager, cancel_transport):
        import urllib.error
        wire = cancel_transport
        scope = wire['scope']()
        parts = scope.split('.')
        parts[1] = ('0' if parts[1][0] != '0' else '1') + parts[1][1:]
        previous = mcp_server_module.SimpleMCPServer()._new_client_session()
        for refused in ('.'.join(parts), previous):
            with pytest.raises(urllib.error.HTTPError) as exc:
                wire['post']({'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call',
                              'params': {'name': 'queued', 'arguments': {'a': 'bad'}}}, refused)
            assert exc.value.code == 404
        assert task_manager.get_pending_task_count() == 0 and wire['effects'] == []

    def test_disconnection_without_notice_keeps_the_authorized_callback(
            self, server, mcp_server_module, task_manager, cancel_transport):
        import http.client
        import time
        from urllib.parse import urlsplit
        wire = cancel_transport
        scope = wire['scope']()
        target = urlsplit(wire['url'])
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=2)
        connection.request('POST', '/mcp', body=json.dumps({
            'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call',
            'params': {'name': 'queued', 'arguments': {'a': 'disconnected'}}}),
            headers={mcp_server_module.SESSION_HEADER: scope, 'Content-Type': 'application/json'})
        task_id = wire['pending'](['disconnected'])['disconnected']
        connection.close()
        assert task_manager.get_pending_task_count() == 1
        _notify(task_manager, mcp_server_module, task_id)
        deadline = time.monotonic() + 1
        while server._active_calls and time.monotonic() < deadline:
            time.sleep(0.001)
        assert wire['effects'] == ['disconnected'] and server._active_calls == {}

    def test_cancel_between_dispatcher_claim_and_handler_entry_skips_the_effect(
            self, server, mcp_server_module, task_manager, cancel_transport, monkeypatch):
        import threading
        wire = cancel_transport
        scope = wire['scope']()
        claimed, release = threading.Event(), threading.Event()
        original = task_manager.post

        def held_post(command, callback, data, on_drop=None):
            def held_callback(arguments):
                claimed.set()
                assert release.wait(timeout=2)
                callback(arguments)
            return original(command, held_callback, data, on_drop=on_drop)

        monkeypatch.setattr(task_manager, 'post', held_post)
        first = wire['call'](scope, 7, 'never')
        task_id = wire['pending'](['never'])['never']
        delivery = wire['pool'].submit(_notify, task_manager, mcp_server_module, task_id)
        try:
            assert claimed.wait(timeout=1)
            assert task_manager.get_pending_task_count() == 0
            wire['post'](_cancel_notice(7), scope)
            assert first.result(timeout=2)[:2] == (202, None)
        finally:
            release.set()
        delivery.result(timeout=2)
        assert wire['effects'] == [] and server._active_calls == {}

    def test_completed_request_notice_does_not_affect_the_next_request(
            self, server, mcp_server_module, task_manager, cancel_transport):
        wire = cancel_transport
        scope = wire['scope']()
        first = wire['call'](scope, 7, 'first')
        _notify(task_manager, mcp_server_module, wire['pending'](['first'])['first'])
        assert first.result(timeout=2)[1]['result'] == {'applied': 'first'}
        second = wire['call'](scope, 8, 'second')
        task_id = wire['pending'](['second'])['second']
        wire['post'](_cancel_notice(7), scope)
        assert task_manager.get_pending_task_count() == 1
        _notify(task_manager, mcp_server_module, task_id)
        assert second.result(timeout=2)[1]['result'] == {'applied': 'second'}
        assert wire['effects'] == ['first', 'second'] and server._active_calls == {}

    def test_anonymous_and_legacy_tools_list_keep_the_attested_load_header(
            self, server, mcp_server_module, cancel_transport, monkeypatch):
        wire = cancel_transport
        monkeypatch.setattr(server, '_attestation', {'load_id': 'loaded-one',
                             'implementation_fingerprint': 'same-code', 'complete': True})
        scope = wire['scope']()
        health = server.health()
        for header in (None, server.session_id):
            reply = wire['post']({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, header)
            assert reply[0] == 200 and reply[1]['result']['tools'][0]['name'] == 'queued'
            assert reply[2] == health['session_id']
        private = wire['post']({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'}, scope)
        assert private[2] == scope and scope != health['session_id']
        assert server.health() == health
        assert health['attestation']['load_id'] == 'loaded-one'

    def test_new_serving_instance_invalidates_client_scopes_and_keeps_health_distinct(
            self, server, mcp_server_module, cancel_transport, monkeypatch):
        import urllib.error
        wire = cancel_transport
        old_scope = wire['scope']()
        old_load_session = server.health()['session_id']
        replacement = mcp_server_module.SimpleMCPServer(attestation={
            'load_id': 'loaded-two', 'implementation_fingerprint': 'same-code', 'complete': True})
        replacement.register(server.tools['queued'])
        monkeypatch.setattr(wire['bound_handler'], 'mcp_server', replacement)
        for stale in (old_scope, old_load_session):
            with pytest.raises(urllib.error.HTTPError) as exc:
                wire['post']({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, stale)
            assert exc.value.code == 404
        new_scope = wire['scope']()
        new_health = replacement.health()
        anonymous = wire['post']({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'})
        assert anonymous[2] == new_health['session_id'] != old_load_session
        assert new_scope != new_health['session_id'] and new_scope != old_scope
        assert replacement._valid_client_session(new_scope)
        assert not replacement._valid_client_session(old_scope)
        assert new_health['attestation']['load_id'] == 'loaded-two'
        assert new_health['attestation']['implementation_fingerprint'] == 'same-code'
        assert replacement.health() == new_health
