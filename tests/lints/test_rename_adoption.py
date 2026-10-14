# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Gate: no tool renames an entity through a swallowed setattr - apply_rename is the one home.

The platform declines a rename SILENTLY and can land a DEDUPED variant ('Foo' -> 'Foo(1)'), so the
banned ``setattr(<entity>, "name", ...)`` publishes the REQUESTED name; ``entity.name = v`` raises."""

import ast
import re
from pathlib import Path

import _corpus

_TOOLS = Path(__file__).resolve().parents[2] / "commands" / "mcpServer" / "tools"

_SWALLOWED_RENAME = re.compile(r"""setattr\(\s*[^,]+,\s*["']name["']""")

# apply_rename's own home may spell the raw form; no tool module may.
_HOME = "_common.py"


class TestRenameAdoption:
    def test_no_tool_setattrs_a_name(self):
        offenders = []
        for path in sorted(_TOOLS.glob("*.py")):
            if path.name == _HOME:
                continue
            for i, line in enumerate(_corpus.text(path).splitlines(), 1):
                if _SWALLOWED_RENAME.search(line):
                    offenders.append(f"{path.name}:{i}: {line.strip()}")
        assert not offenders, (
            "swallowed-rename shape (setattr(<entity>, 'name', ...)) in a tool module - route it "
            "through _common.apply_rename (set + read-back + disclosed decline) and publish the "
            "returned final name + warning:\n  " + "\n  ".join(offenders))

    def test_swallowed_name_writes_have_a_readback(self):
        offenders = []
        checked = 0
        for path in sorted(_TOOLS.glob("*.py")):
            if path.name == _HOME:
                continue
            tree = _corpus.tree(path)
            parents = _parents(tree)
            for try_node in ast.walk(tree):
                if not isinstance(try_node, ast.Try):
                    continue
                checked += 1
                if not _silent_handlers(try_node):
                    continue
                writes = [node for node in ast.walk(try_node)
                          if isinstance(node, ast.Assign)
                          for target in node.targets
                          if isinstance(target, ast.Attribute) and target.attr == "name"]
                checked += len(writes)
                for write in writes:
                    target = next(target for target in write.targets
                                  if isinstance(target, ast.Attribute) and target.attr == "name")
                    identity = ast.dump(target.value, include_attributes=False)
                    write_scope = _scope(write, parents)
                    if not any(isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                               and node.attr == "name"
                               and ast.dump(node.value, include_attributes=False) == identity
                               and node.lineno > try_node.end_lineno
                               and _scope(node, parents) is write_scope
                               for node in ast.walk(tree)):
                        offenders.append(f"{path.name}:{write.lineno}: {identity}.name")
        assert checked, "nothing was checked: no swallowed name assignment was found"
        assert not offenders, (
            "a swallowed name write has no read-back - route it through apply_rename or read the "
            "same entity's final name before returning:\n  " + "\n  ".join(offenders))


def _parents(tree):
    """Return each node's direct parent for lexical-scope checks."""
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _scope(node, parents):
    """Return the nearest function/class scope, or the module sentinel ``None``."""
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return parent
        parent = parents.get(parent)
    return None


def _silent_handlers(try_node):
    """True when every exception handler only discards the failure."""
    if not try_node.handlers:
        return False
    for handler in try_node.handlers:
        for node in handler.body:
            if isinstance(node, (ast.Pass, ast.Continue)):
                continue
            if isinstance(node, ast.Return) and node.value is None:
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                name = node.value.func.attr if isinstance(node.value.func, ast.Attribute) else \
                    getattr(node.value.func, "id", None)
                if name in {"debug", "info", "warning", "warn", "error", "exception", "log"}:
                    continue
            return False
    return True
