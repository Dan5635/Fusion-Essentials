"""Lint: every tool that DECLARES outputs (a RETURNS spec) must honour the contract.

Each declared output's payload KEY appears in the tool's source, its PRODUCES: block appears in the
description, and each RETURNS entry is an OutputKind. Every tools/*.py with a RETURNS is checked."""

import ast
import os

import _corpus
from conftest import load_tool, TOOLS_DIR

_outputs = load_tool("_outputs")


def _tools_with_returns():
    """(module_name, module) for every tools/*.py that declares a RETURNS spec."""
    found = []
    for fn in sorted(os.listdir(TOOLS_DIR)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        name = fn[:-3]
        mod = load_tool(name)
        if getattr(mod, "RETURNS", None):
            found.append((name, mod))
    return found


class TestDeclaredOutputs:
    def test_returns_entries_are_output_kinds(self):
        for name, mod in _tools_with_returns():
            for o in mod.RETURNS:
                assert isinstance(o, _outputs.OutputKind), (
                    f"{name}.RETURNS has a non-OutputKind entry: {o!r}")

    def test_declared_key_appears_in_source(self):
        offenders, declaring = [], _tools_with_returns()
        assert declaring, "nothing was checked: no tool declares a RETURNS spec"
        for name, mod in declaring:
            src = _corpus.text(os.path.join(TOOLS_DIR, f"{name}.py"))
            for o in mod.RETURNS:
                if f'"{o.key}"' not in src and f"'{o.key}'" not in src:
                    offenders.append(f"{name}: declared output '{o.key}' never appears in source")
        assert not offenders, "\n".join(offenders)

    def test_description_carries_the_produces_block(self):
        offenders = []
        for name, mod in _tools_with_returns():
            # Find the tool's description on its registered primitive(s).
            descs = []
            from mcpServer.mcp_primitives import registry
            registry.reset_registry()
            rt = getattr(mod, "register_tool", None)
            if callable(rt):
                rt()
            for it in registry.get_tools():
                d = it.to_dict().get("description", "")
                if d:
                    descs.append(d)
            blob = "\n".join(descs)
            for o in mod.RETURNS:
                # The Produces line names each key and its consumers, as produces_block writes it.
                who = (" -> " + "/".join(o.consumers)) if o.consumers else ""
                if f"{o.key}{who}" not in blob:
                    offenders.append(f"{name}: Produces entry for '{o.key}' not in any description")
        assert not offenders, "\n".join(offenders)


def _hand_built_error_envelopes():
    """Return tool-source dict literals that bind the response contract's isError field."""
    offenders = []
    checked = 0
    for fn in sorted(os.listdir(TOOLS_DIR)):
        if not fn.endswith(".py") or fn == "_common.py":
            continue
        path = os.path.join(TOOLS_DIR, fn)
        for node in ast.walk(_corpus.tree(path)):
            if not isinstance(node, ast.Dict):
                continue
            checked += 1
            if any(isinstance(key, ast.Constant) and key.value == "isError"
                   for key in node.keys):
                offenders.append(f"{fn}:{node.lineno}")
    return offenders, checked


class TestResponseEnvelopeHasOneHome:
    def test_tools_do_not_hand_build_is_error_dicts(self):
        offenders, checked = _hand_built_error_envelopes()
        assert checked, "nothing was checked: no tool dict literal was found"
        assert not offenders, (
            "hand-built response envelope - call _common.ok(...) or _common.error(...) so the "
            "isError/content/message contract stays one home:\n  " + "\n  ".join(offenders))
