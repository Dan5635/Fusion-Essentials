# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Bind whole-family executions to their static source closures and retained local evidence."""

import ast
import dis
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import uuid
import cloud_config
import machine_config
from verify_core import CLOUD_TIER, CLOUD_LINK_CRASH_REVIEW

FORMAT = 2
BAD = {"FAIL", "blocked", "pass*"}
IDENTITY = ("implementation_fingerprint", "schema_fingerprint", "load_id", "session_id")
COMMON_TOOLS = {"doc_get", "doc_new", "doc_close", "doc_activate", "doc_open",
                "view_switch_workspace", "workspace_orient", "sys_reload_addin", "sys_find_tool"}
_DISPATCHERS = {
    ("verify_acts_cam.py", "_folder_wire_call"),
    ("verify_acts_cam.py", "_generation_identity_probe"),
    ("verify_acts_doc.py", "_reload_document_probe"),
    ("verify_runner.py", "run_steps"),
    ("verify_runner.py", "_precondition_holds"),
}
_FOLDER_TOOLS = {"cam_get", "cam_get_status", "cam_edit_operation", "cam_edit_folders",
                 "cam_delete", "cam_generate"}


def declared_scope():
    """Read complete explicit machine scope, never treating missing keys as an opt-out."""
    return machine_config.record_scope(machine_config.require())


def scope_disposition(capability, scope):
    """Report a positive prerequisite's declared exclusion independently of observed facts."""
    machine_config.validate_scope(scope)
    if capability in scope["quarantined"] or scope["asked"].get(capability) is False:
        return "not-in-scope", "configuration excludes this prerequisite or it is quarantined"
    return "held", None


def scope_description(records):
    """Summarize retained conjunctive conditions without consulting this machine's choices."""
    conditions = [condition for record in records.values() for row in record.get("omitted", [])
                  for condition in row["conditions"]]
    return "; ".join(label + ": " + (", ".join(sorted({row["capability"] for row in conditions
                      if row["state"] == state})) or "none") for state, label in (
        ("not-in-scope", "not in scope"), ("not-applicable", "not applicable (conditional)"),
        ("held", "held")))


def _recorded_scope(scope):
    """Require versioned machine, configuration, all requested switches and permanent quarantine."""
    return machine_config.validate_scope(scope)


def aggregate_records(receipt):
    """Return execution stamps and separate unevidenced scope records."""
    records = dict(receipt.get("families", {}))
    if set(records) & set(receipt.get("not_in_scope", {})):
        raise ValueError("family has both a stamp and a not-in-scope record")
    records.update(receipt.get("not_in_scope", {}))
    return records


def _scope_rows(records, acts=None):
    """Validate omission shape before checking every retained prerequisite against its scope."""
    if not isinstance(records, list):
        raise ValueError("family scope records must be a list")
    for row in records:
        if (not isinstance(row, dict) or row.get("state") not in {"held", "not-in-scope", "not-applicable"}
                or row.get("kind") not in {"act", "step", "fixture"}
                or any(not isinstance(row.get(key), str) or not row[key]
                       for key in ("act", "capability", "reason"))
                or (acts is not None and row["act"] not in acts)
                or not isinstance(row.get("conditions"), list) or not row["conditions"]
                or not isinstance(row.get("tools"), list)
                or any(not isinstance(tool, str) or not tool for tool in row["tools"])
                or row["tools"] != sorted(set(row["tools"]))):
            raise ValueError("family scope record lacks conjunctive prerequisite provenance")
    return records


def digest(value):
    """Return a stable JSON digest."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def _validate_omission_scope(row, scope):
    """Recompute all gate conditions, including their individual polarity and observed verdict."""
    machine_config.validate_omission(row, scope)


def tool_census(root):
    """Return the registration discovery names without binding unrelated tool contents."""
    return sorted(p.stem for p in (Path(root) / "commands/mcpServer/tools").glob("*.py")
                  if not p.name.startswith("_"))


def import_closure(root, seeds, trees=None, links=None):
    """Return transitive local imports, refusing unresolved relative or dynamic imports."""
    root = Path(root).resolve()
    trees = {} if trees is None else trees
    links = {} if links is None else links
    seen, pending = set(), list(seeds)

    def resolve(parts):
        base = root.joinpath(*parts)
        for path in (base.with_suffix(".py"), base / "__init__.py"):
            if path.is_file():
                return path.relative_to(root).as_posix()
        if len(parts) == 1:
            path = root / "tests/live" / (parts[0] + ".py")
            if path.is_file():
                return path.relative_to(root).as_posix()
        return None

    while pending:
        rel = pending.pop()
        if rel in seen:
            continue
        if rel in links:
            seen.add(rel)
            pending.extend(links[rel])
            continue
        path = root / rel
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("closure source missing or outside candidate: " + rel)
        seen.add(rel)
        if path.suffix != ".py":
            links[rel] = []
            continue
        before = len(pending)
        parts = list(Path(rel).with_suffix("").parts)
        package = parts[:-1]
        for i in range(1, len(package) + 1):
            initializer = root.joinpath(*package[:i], "__init__.py")
            if initializer.is_file():
                pending.append(initializer.relative_to(root).as_posix())
        if rel not in trees:
            trees[rel] = ast.parse(path.read_bytes(), filename=rel)
        tree = trees[rel]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found = resolve(alias.name.split("."))
                    if found:
                        pending.append(found)
                    elif root.joinpath(alias.name.split(".")[0]).is_dir():
                        raise ValueError("unresolved local import in " + rel)
            elif isinstance(node, ast.ImportFrom):
                base = (package[:len(package) - node.level + 1] if node.level else [])
                base += (node.module or "").split(".") if node.module else []
                found = resolve(base) if base else None
                if found:
                    pending.append(found)
                children = [resolve(base + alias.name.split(".")) for alias in node.names
                            if alias.name != "*"]
                pending.extend(child for child in children if child)
                if node.level and not found and not any(children):
                    raise ValueError("unresolved relative import in " + rel)
                if (not node.level and not found and not any(children) and base
                        and root.joinpath(base[0]).is_dir()):
                    raise ValueError("unresolved local import in " + rel)
            elif isinstance(node, ast.Call):
                name = (node.func.attr if isinstance(node.func, ast.Attribute)
                        else node.func.id if isinstance(node.func, ast.Name) else "")
                if name not in ("import_module", "__import__"):
                    continue
                arg = node.args[0] if node.args else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    target = arg.value
                    level = len(target) - len(target.lstrip("."))
                    base = package[:len(package) - level + 1] if level else []
                    found = resolve(base + target.lstrip(".").split("."))
                    if found:
                        pending.append(found)
                    elif level:
                        raise ValueError("unresolved dynamic relative import in " + rel)
                elif (rel == "commands/mcpServer/entry.py" and isinstance(arg, ast.JoinedStr)
                      and ast.unparse(arg) == "f'{tools.__name__}.{name}'"):
                    # Registration binds the discovered names separately; selected tools are roots.
                    continue
                elif (rel == "commands/mcpServer/tools/sys_get_api_doc.py"
                      and isinstance(arg, ast.Name) and arg.id == "name"
                      and any(isinstance(n, ast.Assign) and any(
                          isinstance(t, ast.Name) and t.id == "_API_MODULES" for t in n.targets)
                          and isinstance(n.value, (ast.Tuple, ast.List)) and all(
                              isinstance(v, ast.Constant) and isinstance(v.value, str)
                              and v.value.startswith("adsk.") for v in n.value.elts)
                              for n in tree.body)):
                    continue
                else:
                    raise ValueError("unbounded dynamic import in " + rel)
        links[rel] = pending[before:]
    return sorted(seen)


def callable_sources(value, root, names, seen=None, trees=None, selections=None):
    """Return source files and tool literals reachable through selected callable bindings."""
    seen = set() if seen is None else seen
    trees = {} if trees is None else trees
    if id(value) in seen:
        return set(), set()
    seen.add(id(value))
    files, tools = set(), set()
    if isinstance(value, str):
        return files, {value} if value in names else tools
    if isinstance(value, dict):
        children = list(value.values())
    elif isinstance(value, (list, tuple, set, frozenset)):
        children = list(value)
    elif isinstance(value, types.ModuleType):
        module_path = getattr(value, "__file__", None)
        if not module_path or not Path(os.path.abspath(module_path)).is_relative_to(Path(root)):
            return files, tools
        files.add(Path(os.path.abspath(module_path)).relative_to(Path(root)).as_posix())
        children = [item for key, item in vars(value).items()
                    if not key.startswith("__") and key != "_FACADE_NS"
                    and not isinstance(item, type)]
    elif inspect.isfunction(value):
        path = Path(os.path.abspath(value.__code__.co_filename))
        if path.is_relative_to(Path(sys.base_prefix)):
            return files, tools
        if not path.is_relative_to(Path(root)):
            raise ValueError("predicate/callback source is outside candidate: " + str(path))
        files.add(path.relative_to(Path(root)).as_posix())
        if selections is not None:
            _select_callable(value, root, selections, trees)
        if value.__name__ == "facade" and path.name == "verify_core.py":
            # The facade's complete source providers are roots; its runtime namespace is not a tool import.
            return files, tools
        if str(path) not in trees:
            definitions_by_line = {}
            for node in ast.walk(ast.parse(path.read_bytes())):
                if isinstance(node, (ast.FunctionDef, ast.Lambda)):
                    definitions_by_line.setdefault(node.lineno, []).append(node)
            trees[str(path)] = definitions_by_line
        definitions = trees[str(path)].get(value.__code__.co_firstlineno, [])
        for definition in definitions:
            for node in ast.walk(definition):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                wire = isinstance(node.func, ast.Name) and node.func.id == "call"
                wire = wire or (isinstance(node.func, ast.Attribute) and node.func.attr == "call"
                    and isinstance(node.func.value, ast.Name) and isinstance(
                        value.__globals__.get(node.func.value.id), types.ModuleType)
                    and str(getattr(value.__globals__[node.func.value.id], "__file__", "")).startswith(str(root)))
                wire = wire or (isinstance(node.func, ast.Call) and isinstance(
                    node.func.func, ast.Name) and node.func.func.id == "facade"
                    and node.func.args and isinstance(node.func.args[0], ast.Constant)
                    and node.func.args[0].value == "call")
                if not wire:
                    continue
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    if node.args[0].value not in names:
                        raise ValueError("callback calls unknown tool: " + node.args[0].value)
                    tools.add(node.args[0].value)
                elif ((path.name, value.__name__) not in _DISPATCHERS
                      or not isinstance(node.args[0], ast.Name) or node.args[0].id != "tool"):
                    raise ValueError("unbounded callback tool dispatch: " + value.__qualname__)
                elif value.__name__ == "_folder_wire_call":
                    tools.update(_FOLDER_TOOLS)
        children = list(value.__defaults__ or ())
        children += [cell.cell_contents for cell in (value.__closure__ or ())]
        codes = [value.__code__]
        while codes:
            code = codes.pop()
            children += [v for v in code.co_consts if not isinstance(v, types.CodeType)]
            codes += [v for v in code.co_consts if isinstance(v, types.CodeType)]
            children += [value.__globals__[name] for name in code.co_names
                         if name in value.__globals__ and not isinstance(
                             value.__globals__[name], (types.ModuleType, type))]
            for name in code.co_names:
                module = value.__globals__.get(name)
                if not isinstance(module, types.ModuleType):
                    continue
                module_path = getattr(module, "__file__", None)
                if not module_path or not Path(os.path.abspath(module_path)).is_relative_to(Path(root)):
                    continue
                if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id == "getattr" and len(node.args) >= 2
                       and isinstance(node.args[0], ast.Name) and node.args[0].id == name
                       and not isinstance(node.args[1], ast.Constant)
                       for definition in definitions for node in ast.walk(definition)):
                    raise ValueError("unbounded local module attribute: " + name)
                files.add(Path(os.path.abspath(module_path)).relative_to(Path(root)).as_posix())
                attributes = set(code.co_names) | {v for v in code.co_consts if isinstance(v, str)}
                resolved = [getattr(module, attr) for attr in attributes if hasattr(module, attr)]
                if not resolved:
                    raise ValueError("unbounded local module callback: " + name)
                children += resolved
    elif hasattr(value, "expect"):
        children = [value.expect]
    else:
        children = []
    for child in children:
        child_files, child_tools = callable_sources(child, root, names, seen, trees, selections)
        files.update(child_files)
        tools.update(child_tools)
    return files, tools


_ENGINE = ("tests/live/tool_verify.py", "tests/live/verify_core.py",
           "tests/live/verify_runner.py", "tests/live/verify_receipts.py",
           "tests/live/verify_families.py", "tests/live/verify_program.py",
           "tests/live/verify_layout.py", "tests/live/cloud_config.py",
           "tests/live/machine_config.py", "tests/live/preflight.py")


def _module_bindings(node):
    """Collect writes in a module statement without entering nested lexical scopes."""
    names, pending = set(), [node]
    while pending:
        child = pending.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(child.name)
            pending.extend(child.decorator_list + child.args.defaults
                           + [value for value in child.args.kw_defaults if value is not None])
            continue
        if isinstance(child, ast.ClassDef):
            names.add(child.name)
            pending.extend(child.decorator_list + child.bases + child.keywords)
            continue
        if isinstance(child, ast.Lambda):
            pending.extend(child.args.defaults
                           + [value for value in child.args.kw_defaults if value is not None])
            continue
        if isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            # Iteration targets are local to the comprehension; walrus targets are not.
            pending.extend([child.key, child.value] if isinstance(child, ast.DictComp) else [child.elt])
            for generator in child.generators:
                pending.extend([generator.iter] + generator.ifs)
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split(".")[0] for alias in child.names)
        if isinstance(child, ast.ExceptHandler) and child.name:
            names.add(child.name)
        if isinstance(child, (ast.MatchAs, ast.MatchStar)) and child.name:
            names.add(child.name)
        if isinstance(child, ast.MatchMapping) and child.rest:
            names.add(child.rest)
        targets = (child.targets if isinstance(child, ast.Assign) else
                   [child.target] if isinstance(child, (ast.AugAssign, ast.AnnAssign)) else [])
        names.update(item.id for target in targets for item in ast.walk(target)
                     if isinstance(item, ast.Name))
        if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)):
            names.add(child.func.value.id)
        pending.extend(ast.iter_child_nodes(child))
    return names


def _source_nodes(root, path, symbols):
    """Select complete declarations and top-level mutations of named bindings."""
    tree = ast.parse((Path(root) / path).read_bytes())
    if "@engine" in symbols:
        engine, stories = [], []
        tools = {symbol.removeprefix("@story:") for symbol in symbols if symbol.startswith("@story:")}
        for node in tree.body:
            if (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                    and target.id == "STORY" for target in node.targets)):
                if not isinstance(node.value, ast.Dict):
                    raise ValueError("story ledger needs a static tool-keyed dictionary")
                for key, value in zip(node.value.keys, node.value.values):
                    if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                        raise ValueError("story ledger has an unbound key")
                    if key.value in tools:
                        stories.append((key.value, ast.dump(value, include_attributes=False)))
            else:
                engine.append(ast.dump(node, include_attributes=False))
        return digest({"engine": engine, "stories": sorted(stories)})
    definitions = {index: _module_bindings(node) for index, node in enumerate(tree.body)}
    bound, chosen = set(symbols), set()
    while True:
        added = {index for index, names in definitions.items() if names & bound} - chosen
        if not added:
            break
        chosen.update(added)
        for index in added:
            codes = [compile(ast.Module(body=[tree.body[index]], type_ignores=[]), path, "exec")]
            while codes:
                code = codes.pop()
                bound.update(instruction.argval for instruction in dis.get_instructions(code)
                             if instruction.opname in ("LOAD_NAME", "LOAD_GLOBAL"))
                codes.extend(child for child in code.co_consts if isinstance(child, types.CodeType))
    if not chosen:
        raise ValueError("no source declarations for " + path + ": " + str(sorted(symbols)))
    return digest([ast.dump(tree.body[index], include_attributes=False) for index in sorted(chosen)])


def _select_callable(value, root, selections, trees):
    """Bind a callback's enclosing declaration and its module-level dependencies."""
    path = Path(os.path.abspath(value.__code__.co_filename)).relative_to(Path(root)).as_posix()
    if path in _ENGINE:
        return
    key = ("selection", path)
    if key not in trees:
        trees[key] = ast.parse((Path(root) / path).read_bytes())
    tree = trees[key]
    symbols = selections.setdefault(path, set())
    for node in tree.body:
        if node.lineno <= value.__code__.co_firstlineno <= getattr(node, "end_lineno", node.lineno):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.add(node.name)
            else:
                symbols.update(child.id for child in ast.walk(node)
                               if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store))
    codes = [value.__code__]
    while codes:
        code = codes.pop()
        symbols.update(name for name in code.co_names if name in value.__globals__)
        codes.extend(child for child in code.co_consts if isinstance(child, types.CodeType))
    if not symbols:
        raise ValueError("unbound callback declaration: " + value.__qualname__)


def _row_sources(root, values, members, selections):
    """Find original row declarations before layout creates transformed row tuples."""
    program = sys.modules.get("verify_program")
    raw = getattr(program, "_ACT_PROGRAM", ()) if program else ()
    if program and Path(program.__file__).resolve().is_relative_to(Path(root).resolve()):
        names = {member[0] for member in members}
        values = list(values) + [act[1:] for act in raw if act[0] in names]
    row_ids = set()
    def visit(value):
        if isinstance(value, (tuple, list)):
            if len(value) == 4 and isinstance(value[0], str):
                row_ids.add(id(value))
            else:
                for child in value:
                    visit(child)
    for value in values:
        visit(value)
    for module in tuple(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if not path or not Path(os.path.abspath(path)).is_relative_to(Path(root)):
            continue
        rel = Path(os.path.abspath(path)).relative_to(Path(root)).as_posix()
        if not rel.startswith("tests/live/verify_acts_"):
            continue
        for name, binding in tuple(vars(module).items()):
            if isinstance(binding, (list, tuple)) and any(id(row) in row_ids for row in binding):
                selections.setdefault(rel, set()).add(name)


def _program_value(value, root, substitutions, active=None):
    """Serialize authored row values without evaluating callbacks or retaining run state."""
    active = set() if active is None else active
    if isinstance(value, str):
        for text, symbol in substitutions:
            value = value.replace(text, "<" + symbol + ">")
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if id(value) in active:
        return {"cycle": type(value).__name__}
    active.add(id(value))
    try:
        if isinstance(value, dict):
            return {str(key): _program_value(child, root, substitutions, active)
                    for key, child in sorted(value.items(), key=lambda item: str(item[0]))}
        if isinstance(value, (tuple, list)):
            return [_program_value(child, root, substitutions, active) for child in value]
        if isinstance(value, (set, frozenset)):
            return sorted((_program_value(child, root, substitutions, active) for child in value),
                          key=lambda item: json.dumps(item, sort_keys=True))
        if inspect.isfunction(value):
            path = Path(os.path.abspath(value.__code__.co_filename))
            name = path.relative_to(root).as_posix() if path.is_relative_to(root) else value.__module__
            return {"callable": name + ":" + value.__qualname__,
                    "defaults": _program_value(value.__defaults__, root, substitutions, active),
                    "closure": [_program_value(cell.cell_contents, root, substitutions, active)
                                for cell in value.__closure__ or ()]}
        if isinstance(value, type):
            return {"class": value.__module__ + ":" + value.__qualname__}
        if isinstance(value, (Path, os.PathLike)):
            return _program_value(os.fspath(value), root, substitutions, active)
        if hasattr(value, "__dict__") and type(value).__module__.startswith("verify"):
            return {"type": type(value).__module__ + ":" + type(value).__qualname__,
                    "state": _program_value(vars(value), root, substitutions, active)}
        raise ValueError("unbound row value: " + type(value).__name__)
    finally:
        active.remove(id(value))


def _runtime_substitutions(root):
    """Symbolically bind process-specific artifact paths and names, not geometry arguments."""
    fields = {"verify_core": ("EXPORT_DIR", "SVG_PATH", "SVG96_PATH", "MARKER_PNG",
                              "MACHINE_NAME", "TEMPLATE_NAME", "REPO_ROOT", "SRC_ROOT"),
              "verify_acts_cloud": ("_STAMP", "RUN_FOLDER", "MOVED_FOLDER", "SOURCE_DOC",
                                    "COPY_DOC", "HOST_DOC", "RUN_PATH", "MOVED_PATH", "FOLDER"),
              "verify_acts_hub": ("_ROT_MACHINE", "_SLICE_3MF", "_PB_INCLUDED_3MF", "_PB_OMITTED_3MF"),
              "verify_acts_doc": ("_VIEW_FOCUS_RUN",),
              "verify_acts_sheet": ("_STAMP",),
              "verify_acts_render": ("_PNG_PATH", "_JPEG_PATH", "_TIFF_PATH", "_NAMED_PATH",
                                     "_TRANSPARENT_PATH", "_REFUSED_PATH", "_CANVAS_PATH")}
    values = [(str(Path(root)), "candidate_root")]
    for module_name, names in fields.items():
        module = sys.modules.get(module_name)
        if not module or not Path(module.__file__).resolve().is_relative_to(Path(root).resolve()):
            continue
        for name in names:
            value = getattr(module, name, None)
            if isinstance(value, (str, Path)) and str(value):
                values.append((str(value), module_name + "." + name))
    return sorted(set(values), key=lambda item: (-len(item[0]), item[1]))


def _closure_hash(files, census, program=None):
    bound = {"files": files, "census": census}
    if program is not None:
        bound["program"] = program
    return digest(bound)


def family_closures(root, acts, owners, fixtures, providers=()):
    """Bind engine bytes, selected row declarations/checks and reachable tool imports."""
    root = Path(root).resolve()
    census = tool_census(root)
    engine = [name for name in _ENGINE if (root / name).is_file()]
    server = ["commands/mcpServer/entry.py", "Fusion-Essentials.py", "lib/loaded_attestation.py",
              "commands/mcpServer/guidance/parametric_cad_design.json"]
    result = {}
    trees, file_hashes, callback_trees, links = {}, {}, {}, {}
    provider_files, provider_tools, provider_seen = set(), set(), set()
    provider_selections = {}
    for value in providers:
        files, tools = callable_sources(value, root, set(census), provider_seen,
                                        callback_trees, provider_selections)
        provider_files.update(files)
        provider_tools.update(tools)
    substitutions = _runtime_substitutions(root)
    for family in sorted(set(owners.values())):
        members = [act for act in acts if owners[act[0]] == family]
        tools = (set(COMMON_TOOLS) & set(census)) | provider_tools
        values = [fixtures(family, raw=True)]
        for name, pre, narrative, fallback in members:
            values += [pre, narrative, fallback]
            for entitled in (True, False):
                values.append(fixtures(family, before_act=name, entitled=entitled, raw=True))
        selections = {path: set(names) for path, names in provider_selections.items()}
        visited = set(provider_seen)
        callback_files = set(provider_files)
        for value in values:
            files, used = callable_sources(value, root, set(census), visited,
                                           callback_trees, selections)
            callback_files.update(files)
            tools.update(used)
        _row_sources(root, values, members, selections)
        seeds = set(server) | {"commands/mcpServer/tools/" + name + ".py" for name in tools}
        paths = set(import_closure(root, seeds, trees, links)) | set(engine)
        paths.update(path for path in callback_files if path not in selections)
        if "tests/live/verify_program.py" in paths:
            paths.remove("tests/live/verify_program.py")
            selections["tests/live/verify_program.py"] = {"@engine"} | {"@story:" + name for name in tools}
        entries = {}
        for path in sorted(paths):
            if path not in file_hashes:
                file_hashes[path] = hashlib.sha256((root / path).read_bytes().replace(
                    b"\r\n", b"\n")).hexdigest()
            entries[path] = file_hashes[path]
        projected = {path: sorted(names) for path, names in selections.items() if path not in paths}
        entries.update({path: _source_nodes(root, path, names) for path, names in projected.items()})
        program = digest(_program_value(values, root, substitutions))
        result[family] = {"hash": _closure_hash(entries, census, program), "files": entries,
                          "selections": projected, "program": program, "tools": sorted(tools),
                          "acts": [act[0] for act in members]}
    return result


def exact_identity(attestation):
    """Require complete exact-loaded fingerprints, load and server-session identity."""
    if (not isinstance(attestation, dict) or attestation.get("complete") is not True
            or attestation.get("loaded_matches_source") is not True):
        raise ValueError("receipt needs exact-loaded complete identity")
    for key in IDENTITY:
        value = attestation.get(key)
        if (not isinstance(value, str) or not value or (key in IDENTITY[:2]
                and not re.fullmatch(r"[0-9a-f]{64}", value))):
            raise ValueError("receipt attestation missing " + key)


def rehash_closures(root, closures):
    """Rehash every bound source byte once without repeating dependency discovery."""
    root = Path(root)
    census, hashes, result = tool_census(root), {}, {}
    for name, closure in closures.items():
        files = {}
        for path in closure["files"]:
            symbols = closure.get("selections", {}).get(path)
            key = (path, tuple(symbols or ()))
            if key not in hashes:
                hashes[key] = (_source_nodes(root, path, symbols) if symbols else
                               hashlib.sha256((root / path).read_bytes().replace(
                                   b"\r\n", b"\n")).hexdigest())
            files[path] = hashes[key]
        result[name] = dict(closure, files=files,
                            hash=_closure_hash(files, census, closure.get("program")))
    return result


def normalized_health(health, fusion_version=None):
    """Bind the wire's top-level server session explicitly into the retained attestation."""
    normalized = json.loads(json.dumps(health))
    attestation = normalized.get("attestation")
    if not isinstance(attestation, dict):
        raise ValueError("health has no loaded attestation")
    if "session_id" in attestation and attestation["session_id"] != normalized.get("session_id"):
        raise ValueError("health and attestation sessions disagree")
    attestation["session_id"] = normalized.get("session_id")
    if fusion_version is not None:
        normalized["fusion_version"] = fusion_version
    exact_identity(attestation)
    return normalized


def exact_start(health, census, require_build=True):
    """Require complete exact-loaded identity and a complete duplicate-free opening census."""
    att = health.get("attestation") if isinstance(health, dict) else None
    if (not isinstance(att, dict) or att.get("complete") is not True
            or att.get("loaded_matches_source") is not True
            or not isinstance(health.get("session_id"), str) or not health["session_id"]
            or (require_build and (not isinstance(health.get("fusion_version"), str)
                                   or health["fusion_version"] in ("", "?")))):
        raise ValueError("receipt needs exact-loaded complete start attestation and Fusion build")
    exact_identity(att)
    if att["session_id"] != health["session_id"]:
        raise ValueError("health and attestation sessions disagree")
    if not isinstance(census, dict) or census.get("complete") is not True:
        raise ValueError("receipt needs exact complete opening census")
    rows = census.get("documents")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("receipt opening census has invalid documents")
    handles = [r.get("document_handle") for r in rows]
    if (any(not isinstance(h, str) or not h.startswith("session:") for h in handles)
            or len(set(handles)) != len(handles) or census.get("open_count") != len(rows)
            or type(census.get("open_count")) is not int
            or (rows and census.get("active") not in handles)
            or (not rows and census.get("active") is not None)):
        raise ValueError("receipt opening census is incomplete or ambiguous")


def preserved_census(start, end):
    """Require all original tabs, their reported state and the active identity to survive."""
    if start.get("active") != end.get("active"):
        raise ValueError("owner active document changed")
    original = {row["document_handle"]: row for row in start["documents"]}
    final = {row["document_handle"]: row for row in end["documents"]}
    if set(original) != set(final):
        raise ValueError("owner document census changed or scratch cleanup incomplete")
    defaults = {"is_active": False, "is_visible": True, "is_saved": True, "is_modified": False}
    for handle, before in original.items():
        after = final[handle]
        keys = (set(before) | set(after)) - {"open_index"}
        if any(before.get(key, defaults.get(key)) != after.get(key, defaults.get(key)) for key in keys):
            raise ValueError("owner document state changed: " + handle)


def accounting(rows, self_reported=(), independent=()):
    """Keep independent, self-reported, called and guard-only tools in disjoint buckets."""
    passed = {tool for tool, status, _note in rows if status == "pass"}
    covered = passed & set(independent)
    reported = (passed & set(self_reported)) - covered
    refused = {tool for tool, status, _note in rows if status == "expected-refusal"} - passed
    buckets = {"covered": sorted(covered), "self-reported": sorted(reported),
               "called": sorted(passed - covered - reported), "refusals-only": sorted(refused)}
    return {"buckets": buckets, "counts": {key: len(value) for key, value in buckets.items()}}


def _stamp_data(family, closure, execution, current_closure):
    """Make a stamp only from complete fresh family execution and successful cleanup."""
    exact_start(execution["start_health"], execution["start_census"])
    if (not execution.get("run_id") or not execution.get("family_run_id")
            or execution.get("whole_family") is not True or execution.get("cleanup") is not True
            or execution.get("source_unchanged") is not True
            or execution.get("stopped") is not False
            or execution.get("acts") != closure["acts"] or current_closure != closure):
        raise ValueError("family execution incomplete, cleanup failed, or source changed: " + family)
    rows = execution.get("rows") or []
    producers = execution.get("producers") or []
    omitted = _scope_rows(execution.get("omitted", []), closure["acts"])
    scope = _recorded_scope(execution["scope"] if "scope" in execution else declared_scope())
    for row in omitted:
        try:
            _validate_omission_scope(row, scope)
        except ValueError:
            raise ValueError("family omission disagrees with declared scope: " + family)
    exact_start(execution["start_health"], execution.get("end_census"))
    preserved_census(execution["start_census"], execution["end_census"])
    if any(not isinstance(row, (list, tuple)) or len(row) != 3
           or any(not isinstance(value, str) for value in row) for row in rows):
        raise ValueError("family execution has invalid result rows: " + family)
    independently_seen = set()
    for witness in execution.get("witnesses", []):
        index = witness.get("row_index")
        if type(index) is not int or not 0 <= index < len(rows):
            raise ValueError("independent witness has no executed row: " + family)
        tool, status, _note = rows[index]
        earlier = {t for t, s, _n in rows[:index] if s == "pass"}
        targets = set(witness.get("targets", []))
        route = witness.get("witness", "")
        if (status != "pass" or tool != witness.get("tool") or not targets
                or not targets <= earlier or tool in targets
                or not re.fullmatch(r"(tool|file|geometry):.+", route)
                or (route.startswith("tool:") and (
                    route != "tool:" + tool or witness.get("reader_is_read") is not True))):
            raise ValueError("independent witness provenance invalid: " + family)
        independently_seen.update(targets)
    if independently_seen != set(execution.get("independent", [])):
        raise ValueError("independent evidence missing explicit witnesses: " + family)
    if any(row[1] not in {"pass", "expected-refusal"} for row in rows) or any(
            not p.get("run_id") or p.get("family_run_id") != execution["family_run_id"]
            or p.get("fusion_version") != execution["start_health"]["fusion_version"]
            or p.get("closure_hash") != closure["hash"] or p.get("success") is not True
            or not p.get("phase") or not p.get("rows")
            or any(not isinstance(row, (list, tuple)) or len(row) != 3
                   or row[1] not in {"pass", "expected-refusal"}
                   or list(row) not in [list(r) for r in rows] for row in p.get("rows", []))
            for p in producers):
        raise ValueError("failed family or local producer execution: " + family)
    omitted_acts = {row["act"] for row in omitted if row["kind"] == "act"}
    if ((not rows and omitted_acts != set(closure["acts"]))
            or len({p["run_id"] for p in producers}) != len(producers)):
        raise ValueError("family has no executed rows or duplicate producer IDs: " + family)
    if not set(execution.get("self_reported", [])) <= {
            tool for tool, status, _note in rows if status == "pass"}:
        raise ValueError("family value evidence has no executed passing row: " + family)
    state = "held" if any(row["state"] == "held" for row in omitted) else "executed"
    wholly_omitted = bool(omitted) and omitted_acts == set(closure["acts"])
    if wholly_omitted and state != "held":
        if rows or producers or independently_seen:
            raise ValueError("not-in-scope family contains executed work: " + family)
        modes = execution.get("act_modes", [])
        if ([pair[0] for pair in modes if isinstance(pair, list) and len(pair) == 2]
                != list(closure["acts"])
                or any(not isinstance(pair, list) or len(pair) != 2
                       or not isinstance(pair[1], str) or not pair[1].startswith("skipped(")
                       for pair in modes)):
            raise ValueError("not-in-scope family lacks actual skipped act modes: " + family)
        return {"family": family, "state": "not-in-scope", "scope": scope,
                "acts": list(closure["acts"]),
                "act_modes": execution.get("act_modes", []),
                "omitted": omitted}
    base = {
        "family": family, "run_id": execution["run_id"],
        "family_run_id": execution["family_run_id"], "closure_hash": closure["hash"],
        "fusion_version": execution["start_health"]["fusion_version"],
        "acts": list(execution["acts"]), "acts_hash": digest(execution["acts"]), "row_count": len(rows),
        "state": state, "scope": scope, "omitted": omitted,
        "census": {"start": digest(execution["start_census"]),
                   "end": digest(execution["end_census"])},
    }
    if state == "not-in-scope":
        return base
    return base | {
        "identity": {key: execution["start_health"]["attestation"][key]
                     for key in (*IDENTITY, "complete", "loaded_matches_source")},
        "producers": [{key: p[key] for key in (
            "run_id", "family_run_id", "phase", "fusion_version", "closure_hash")}
            | {"row_count": len(p["rows"]), "rows_hash": digest(p["rows"])} for p in producers],
        "producer_run_ids": [p["run_id"] for p in producers],
        "witnesses": execution.get("witnesses", []),
        "act_modes": execution.get("act_modes", []),
        "evidence": accounting(rows, execution.get("self_reported", []),
                               execution.get("independent", [])),
    }


def _evidence_directory(directory):
    """Return the existing ignored results location or an explicit test location."""
    return Path(directory) if directory is not None else Path(__file__).with_name("results")


def retain_evidence(value, directory=None):
    """Retain immutable raw evidence addressed by its checksum."""
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True) + "\n").encode("ascii")
    checksum = hashlib.sha256(encoded).hexdigest()
    directory = _evidence_directory(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("family-evidence-" + checksum + ".json")
    try:
        with path.open("xb") as fh:
            fh.write(encoded)
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise ValueError("retained evidence checksum path changed: " + path.name)
    return {"file": path.name, "sha256": checksum}


def make_stamp(family, closure, execution, current_closure, evidence_dir=None):
    """Validate executed evidence before minting compact portable provenance."""
    execution = dict(execution, scope=execution["scope"] if "scope" in execution else declared_scope())
    stamp = _stamp_data(family, closure, execution, current_closure)
    if stamp["state"] != "not-in-scope":
        stamp["raw"] = retain_evidence({"closure": closure, "execution": execution}, evidence_dir)
    return stamp


def _retained(reference, directory):
    """Inspect retained evidence when present, without requiring ignored files on a clone."""
    checksum = reference.get("sha256") if isinstance(reference, dict) else None
    if (not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)
            or reference.get("file") != "family-evidence-" + checksum + ".json"):
        raise ValueError("invalid immutable evidence reference")
    path = _evidence_directory(directory) / reference["file"]
    if not path.exists():
        return None
    encoded = path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != checksum:
        raise ValueError("retained evidence checksum differs: " + path.name)
    return json.loads(encoded)


def lifecycle_omissions(scope):
    """Return unevidenced closing-hook exclusions from the recorded explicit permissions."""
    _recorded_scope(scope)
    requirements = {"switch": ("preference_writes", "addin_reload"), "reload": ("addin_reload",)}
    return {name: machine_config.omission("LIFECYCLE " + name, "act", ["sys_reload_addin"], rows)
            for name, names in requirements.items()
            for rows in [[machine_config.condition(capability, "needs", scope["asked"][capability], None)
                          for capability in names]]
            if machine_config.conjunction(rows)["state"] == "not-in-scope"}


def make_lifecycle(evidence, run_id, source, fusion_version, evidence_dir=None):
    """Bind actual reload observations, or a strictly unevidenced explicit exclusion."""
    scope = declared_scope()
    omissions = lifecycle_omissions(scope)
    if "reload" in omissions:
        if evidence is not None:
            raise ValueError("excluded reload cannot carry execution evidence")
        record = {"state": "not-in-scope", "run_id": run_id, "source_hash": source,
                  "fusion_version": fusion_version, "scope": scope, "omitted": omissions}
        _validate_lifecycle(record, source, fusion_version, (), evidence_dir)
        return record
    raw = retain_evidence({"run_id": run_id, "source_hash": source,
                           "fusion_version": fusion_version, "observations": evidence}, evidence_dir)
    record = {"run_id": run_id, "source_hash": source, "fusion_version": fusion_version,
              "raw": raw, "before": evidence.get("before_attestation"),
              "after": evidence.get("after_attestation"),
              "before_tool_census": evidence.get("before_tool_census"),
              "after_tool_census": evidence.get("after_tool_census"),
              "after_fusion_version": evidence.get("after_fusion_version"),
              "checks": evidence.get("checks"),
              "before_mcp_session": evidence.get("before_mcp_session"),
              "after_mcp_session": evidence.get("after_mcp_session"),
              "fresh_transport_document_handle": evidence.get("fresh_transport_document_handle"),
              "pre_reload_census": evidence.get("pre_reload_census"),
              "post_reload_census": evidence.get("post_reload_census"),
              "cleanup_census": evidence.get("cleanup_census"),
              "scratch_cleanup_census": evidence.get("scratch_cleanup_census"),
              "restored_census": evidence.get("restored_census"),
              "scratch_handle_before_reload": evidence.get("scratch_handle_before_reload"),
              "nonce_name": evidence.get("nonce_name"),
              "nonce_value_mm": evidence.get("nonce_value_mm")}
    record.update(state="executed", scope=scope, omitted=omissions)
    _validate_lifecycle(record, source, fusion_version, record["before_tool_census"], evidence_dir)
    return record


def _validate_lifecycle(record, source, fusion_version, census, evidence_dir=None):
    """Require actual reload evidence or an explicit, unevidenced recorded-scope exclusion."""
    scope = _recorded_scope(record.get("scope"))
    omissions = lifecycle_omissions(scope)
    if record.get("omitted") != omissions:
        raise ValueError("lifecycle omissions disagree with explicit recorded permissions")
    if record.get("state") == "not-in-scope":
        if (set(record) != {"state", "run_id", "source_hash", "fusion_version", "scope", "omitted"}
                or "reload" not in omissions or not isinstance(record.get("run_id"), str) or not record["run_id"]
                or record.get("source_hash") != source or not re.fullmatch(r"[0-9a-f]{64}", source or "")
                or record.get("fusion_version") != fusion_version
                or not isinstance(fusion_version, str) or not fusion_version):
            raise ValueError("excluded lifecycle carries evidence or incomplete scope binding")
        for row in omissions.values():
            _validate_omission_scope(row, scope)
        return
    if record.get("state") != "executed" or "reload" in omissions:
        raise ValueError("lifecycle reload execution disagrees with recorded permission")
    required = {"new_load_and_session", "same_implementation_and_schema", "tool_census_matches",
                "old_transport_refused_empty_404", "fresh_session_changed",
                "fresh_session_read_new_handle", "nonce_read_back_before_reload",
                "reload_scheduled", "nonce_survived_reload", "old_handle_refused",
                "stale_write_absent", "fresh_handle_write_readback", "recovery_parameter_removed",
                "scratch_closed_and_home_restored"}
    before, after = record.get("before"), record.get("after")
    checks = record.get("checks")
    try:
        exact_identity(before)
        exact_identity(after)
    except ValueError as exc:
        raise ValueError("lifecycle attestation identity incomplete") from exc
    sessions = (record.get("before_mcp_session"), record.get("after_mcp_session"))
    handles = (record.get("scratch_handle_before_reload"),
               record.get("fresh_transport_document_handle"))
    if (not isinstance(record.get("run_id"), str) or not record["run_id"]
            or record.get("source_hash") != source
            or not re.fullmatch(r"[0-9a-f]{64}", record.get("source_hash", ""))
            or record.get("fusion_version") != fusion_version
            or not isinstance(fusion_version, str) or not fusion_version
            or record.get("after_fusion_version") != fusion_version
            or not isinstance(before, dict) or not isinstance(after, dict)
            or not isinstance(checks, dict) or not required <= {k for k, v in checks.items() if v is True}
            or record.get("before_tool_census") != census
            or record.get("after_tool_census") != census
            or before.get("load_id") == after.get("load_id")
            or before.get("session_id") == after.get("session_id")
            or before.get("complete") is not True or before.get("loaded_matches_source") is not True
            or after.get("complete") is not True or after.get("loaded_matches_source") is not True
            or any(before.get(key) != after.get(key) for key in
                   ("implementation_fingerprint", "schema_fingerprint"))
            or any(not isinstance(session, str) or not session.strip() for session in sessions)
            or sessions[0] == sessions[1]
            or any(not isinstance(handle, str) or not re.fullmatch(r"session:\S+", handle)
                   for handle in handles)
            or record.get("fresh_transport_document_handle")
               != record.get("post_reload_census", {}).get("handle")
            or not record.get("nonce_name") or record.get("nonce_value_mm") != 17):
        raise ValueError("lifecycle reload evidence incomplete or stale")
    census_defaults = {"is_active": False, "is_visible": True,
                       "is_saved": True, "is_modified": False}
    censuses = {}
    for key in ("pre_reload_census", "post_reload_census", "cleanup_census",
                "scratch_cleanup_census", "restored_census"):
        state = record.get(key)
        if (not isinstance(state, dict) or state.get("complete") is not True
                or type(state.get("open_count")) is not int
                or not isinstance(state.get("rows"), list)
                or state["open_count"] != len(state["rows"])
                or not isinstance(state.get("handle"), str)
                or not re.fullmatch(r"session:\S+", state["handle"])):
            raise ValueError("lifecycle document census missing: " + key)
        rows = []
        for source_row in state["rows"]:
            if not isinstance(source_row, dict):
                raise ValueError("lifecycle document census is inconsistent: " + key)
            row = dict(census_defaults, **source_row)
            if (not isinstance(row.get("name"), str) or not row["name"]
                    or any(type(row.get(field)) is not bool for field in census_defaults)):
                raise ValueError("lifecycle document state is unreadable: " + key)
            rows.append(row)
        active_row = next((row for row in rows
                           if row.get("document_handle") == state["handle"]), None)
        if not isinstance(active_row, dict) or active_row.get("name") != state.get("name"):
            raise ValueError("lifecycle active document census differs: " + key)
        lineage = state.get("document_id")
        if lineage is not None and (not isinstance(lineage, str) or not lineage.startswith("urn:")):
            raise ValueError("lifecycle active document lineage is invalid: " + key)
        row_handles = [row.get("document_handle") for row in rows if isinstance(row, dict)]
        if (len(row_handles) != len(rows) or len(set(row_handles)) != len(rows)
                or any(not isinstance(handle, str) or not re.fullmatch(r"session:\S+", handle)
                       for handle in row_handles)
                or sum(row.get("is_active") is True for row in rows) != 1
                or any(type(row.get("is_active")) is not bool for row in rows)
                or not any(row.get("document_handle") == state["handle"]
                           and row.get("is_active") is True for row in rows)):
            raise ValueError("lifecycle document census is inconsistent: " + key)
        censuses[key] = dict(state, rows=rows)
    home = censuses["pre_reload_census"]
    scratch_handle = record["fresh_transport_document_handle"]
    def stable_rows(state, ignored_handle=None):
        """Key rows by exposed lineage or otherwise a unique name."""
        rows = [row for row in state["rows"]
                if row.get("document_handle") != ignored_handle]
        names = [row.get("name") for row in rows if not row.get("document_id")]
        if any(not name or names.count(name) != 1 for name in names):
            raise ValueError("lifecycle census has ambiguous document names")
        result = {}
        for row in rows:
            lineage = row.get("document_id")
            if lineage is not None and (
                    not isinstance(lineage, str) or not lineage.startswith("urn:")):
                raise ValueError("lifecycle census has invalid saved lineage")
            key = ("id", lineage) if lineage is not None else ("name", row.get("name"))
            if key in result:
                raise ValueError("lifecycle census has duplicate document lineage")
            result[key] = {field: value for field, value in row.items()
                           if field not in {"document_handle", "open_index"}}
        return result
    original = stable_rows(home)
    post_state, cleanup_state = censuses["post_reload_census"], censuses["cleanup_census"]
    post = stable_rows(post_state, scratch_handle)
    cleanup = stable_rows(cleanup_state, scratch_handle)
    scratch_cleanup = stable_rows(censuses["scratch_cleanup_census"])
    restored = stable_rows(censuses["restored_census"])
    stable_owner = lambda row: {key: value for key, value in row.items() if key != "is_active"}
    if (set(original) != set(restored) or set(scratch_cleanup) != set(original)):
        raise ValueError("lifecycle owner census did not restore")
    if home.get("document_id") != censuses["restored_census"].get("document_id"):
        raise ValueError("lifecycle active lineage did not restore")
    if (set(post) != set(original) or set(cleanup) != set(original)
            or len(post_state["rows"]) != len(original) + 1
            or len(cleanup_state["rows"]) != len(original) + 1
            or sum(row.get("document_handle") == scratch_handle
                   for row in post_state["rows"]) != 1
            or sum(row.get("document_handle") == scratch_handle
                   for row in cleanup_state["rows"]) != 1
            ):
        raise ValueError("lifecycle scratch was not the sole added document")
    if (any(stable_owner(original[key]) != stable_owner(restored[key])
            or stable_owner(original[key]) != stable_owner(post[key])
            or stable_owner(original[key]) != stable_owner(cleanup[key])
            or stable_owner(original[key]) != stable_owner(scratch_cleanup[key])
            for key in original)):
        raise ValueError("lifecycle owner document state changed")
    if original != restored:
        raise ValueError("lifecycle owner activation state did not restore")
    raw = _retained(record.get("raw"), evidence_dir)
    if raw is not None:
        observations = raw.get("observations")
        pairs = (("before_attestation", "before"), ("after_attestation", "after"),
                 ("before_tool_census", "before_tool_census"),
                 ("after_tool_census", "after_tool_census"), ("checks", "checks"),
                 ("before_mcp_session", "before_mcp_session"),
                 ("after_mcp_session", "after_mcp_session"),
                 ("fresh_transport_document_handle", "fresh_transport_document_handle"),
                 ("pre_reload_census", "pre_reload_census"),
                 ("post_reload_census", "post_reload_census"),
                 ("cleanup_census", "cleanup_census"),
                 ("scratch_cleanup_census", "scratch_cleanup_census"),
                 ("restored_census", "restored_census"),
                 ("scratch_handle_before_reload", "scratch_handle_before_reload"),
                 ("nonce_name", "nonce_name"), ("nonce_value_mm", "nonce_value_mm"))
        if (raw.get("run_id") != record.get("run_id")
                or raw.get("source_hash") != record.get("source_hash")
                or raw.get("fusion_version") != record.get("fusion_version")
                or not isinstance(observations, dict)
                or any(observations.get(source_key) != record.get(target_key)
                       for source_key, target_key in pairs)):
            raise ValueError("retained lifecycle evidence differs")
        build = observations.get("after_build_observation")
        if (not isinstance(build, dict)
                or build.get("fusion_version") != record.get("after_fusion_version")):
            raise ValueError("retained lifecycle Fusion build differs")


def _validate_stamp(name, stamp, closure, evidence_dir=None, current=True):
    """Validate compact provenance and any retained raw execution available locally."""
    if stamp.get("family") != name:
        raise ValueError("family source changed: " + name)
    state = stamp.get("state")
    if state == "not-in-scope":
        scope = _recorded_scope(stamp.get("scope"))
        acts = stamp.get("acts")
        omitted = _scope_rows(stamp.get("omitted"), acts if isinstance(acts, list) else None)
        if (not omitted or any(row["state"] != "not-in-scope" or row["kind"] != "act"
                                      for row in omitted)
                or not isinstance(acts, list) or not acts or len(set(acts)) != len(acts)
                or {row["act"] for row in omitted} != set(acts)
                or len(omitted) != len(acts)
                or not isinstance(stamp.get("act_modes"), list)
                or any(not isinstance(pair, list) or len(pair) != 2
                       for pair in stamp["act_modes"])
                or [pair[0] for pair in stamp["act_modes"] if isinstance(pair, list) and len(pair) == 2] != acts
                or any(not str(pair[1]).startswith("skipped(") for pair in stamp["act_modes"])
                or (current and acts != closure["acts"])
                or any(row["state"] != "not-in-scope"
                       or not machine_config.validate_omission(row, scope)
                       for row in omitted)
                or set(stamp) != {"family", "state", "scope", "acts", "act_modes", "omitted"}):
            raise ValueError("not-in-scope record contains execution evidence or incomplete omissions: " + name)
        return
    if current and stamp.get("closure_hash") != closure["hash"]:
        raise ValueError("family source changed: " + name)
    _recorded_scope(stamp.get("scope"))
    if state not in {"executed", "held"}:
        raise ValueError("family exercised state missing: " + name)
    omitted = _scope_rows(stamp.get("omitted"), closure["acts"] if current else None)
    try:
        for row in omitted:
            _validate_omission_scope(row, stamp.get("scope", {}))
    except ValueError as exc:
        raise ValueError("family omission disagrees with recorded scope: " + name) from exc
    exact_identity(stamp.get("identity"))
    modes = stamp.get("act_modes")
    recorded_acts = stamp.get("acts")
    if (not isinstance(recorded_acts, list) or not recorded_acts
            or len(recorded_acts) != len(set(recorded_acts))
            or (current and recorded_acts != closure["acts"])
            or (not current and digest(recorded_acts) != stamp.get("acts_hash"))
            or not isinstance(modes, list)
            or [pair[0] for pair in modes if isinstance(pair, list) and len(pair) == 2] != recorded_acts
            or any(not isinstance(pair, list) or len(pair) != 2
                   or (pair[1] not in {"narrative", "fallback"}
                       and not str(pair[1]).startswith("skipped(")) for pair in stamp["act_modes"])):
        raise ValueError("family act modes missing or invalid: " + name)
    if (state == "held") != any(row["state"] == "held" for row in omitted):
        raise ValueError("family held state disagrees with its omissions: " + name)
    if (any(not isinstance(stamp.get(key), str) or not stamp[key]
            for key in ("run_id", "family_run_id", "fusion_version"))
            or stamp["fusion_version"] == "?"
            or not re.fullmatch(r"[0-9a-f]{64}", stamp.get("closure_hash", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", stamp.get("acts_hash", ""))
            or (current and stamp.get("acts_hash") != digest(closure["acts"]))
            or type(stamp.get("row_count")) is not int or stamp["row_count"] < 0
            or (stamp["row_count"] == 0 and not omitted)):
        raise ValueError("family provenance incomplete: " + name)
    for checksum in stamp.get("census", {}).values():
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("invalid census checksum: " + name)
    if set(stamp.get("census", {})) != {"start", "end"}:
        raise ValueError("family census provenance missing: " + name)
    evidence = stamp.get("evidence", {})
    buckets, counts = evidence.get("buckets", {}), evidence.get("counts", {})
    expected = {"covered", "self-reported", "called", "refusals-only"}
    if set(buckets) != expected or set(counts) != expected:
        raise ValueError("family accounting incomplete: " + name)
    seen = set()
    for key, tools in buckets.items():
        if (not isinstance(tools, list) or any(not isinstance(tool, str) for tool in tools)
                or tools != sorted(set(tools)) or seen & set(tools)
                or type(counts[key]) is not int or counts[key] != len(tools)):
            raise ValueError("family accounting differs: " + name)
        seen.update(tools)
    producers = stamp.get("producers", [])
    ids = [producer.get("run_id") for producer in producers]
    if stamp.get("producer_run_ids") != ids or len(set(ids)) != len(ids):
        raise ValueError("family producer provenance differs: " + name)
    for producer in producers:
        if (not isinstance(producer.get("run_id"), str) or not producer["run_id"]
                or producer.get("family_run_id") != stamp["family_run_id"]
                or producer.get("fusion_version") != stamp["fusion_version"]
                or producer.get("closure_hash") != stamp["closure_hash"]
                or type(producer.get("row_count")) is not int or producer["row_count"] <= 0
                or not re.fullmatch(r"[0-9a-f]{64}", producer.get("rows_hash", ""))
                or not isinstance(producer.get("phase"), str) or not producer["phase"]):
            raise ValueError("family producer provenance incomplete: " + name)
    witnessed = set()
    for witness in stamp.get("witnesses", []):
        index, route, targets = witness.get("row_index"), witness.get("witness", ""), witness.get("targets", [])
        if (type(index) is not int or not 0 <= index < stamp["row_count"] or not targets
                or not isinstance(witness.get("tool"), str) or witness["tool"] in targets
                or not re.fullmatch(r"(tool|file|geometry):.+", route)
                or (route.startswith("tool:") and (
                    route != "tool:" + witness["tool"] or witness.get("reader_is_read") is not True))):
            raise ValueError("family witness provenance invalid: " + name)
        witnessed.update(targets)
    if set(buckets["covered"]) != witnessed:
        raise ValueError("family coverage lacks witnesses: " + name)
    if stamp["row_count"] == 0 and (state != "held" or seen or producers or witnessed
            or (current and {row["act"] for row in omitted if row["kind"] == "act"} != set(closure["acts"]))):
        raise ValueError("zero-row held family contains evidence or incomplete omissions: " + name)
    _validate_raw(name, stamp, closure, evidence_dir, current)


def _validate_raw(name, stamp, closure, evidence_dir, current):
    """Rebuild available immutable raw evidence using its own historical closure when needed."""
    raw = _retained(stamp.get("raw"), evidence_dir)
    if raw is not None:
        rebuilt = _stamp_data(name, raw["closure"], raw["execution"],
                              closure if current else raw["closure"])
        if {key: value for key, value in stamp.items() if key != "raw"} != rebuilt:
            raise ValueError("retained family evidence differs: " + name)


def validate_aggregate(receipt, closures, census, attestation=None, evidence_dir=None,
                       require_current=True, require_exercised=True, full_scope=False,
                       source_hash=None):
    """Reject missing, stale, mixed-build, incomplete or unbootstrapped aggregate evidence."""
    if (receipt.get("format") != FORMAT or not receipt.get("bootstrap_run_id")
            or receipt.get("tool_census") != census
            or set(aggregate_records(receipt)) != set(closures)):
        raise ValueError("family receipt needs a new complete bootstrap")
    builds = set()
    bootstrap = receipt.get("bootstrap")
    if (not isinstance(bootstrap, dict) or bootstrap.get("run_id") != receipt["bootstrap_run_id"]
            or bootstrap.get("families") != sorted(closures)
            or not isinstance(bootstrap.get("executed_families"), list)
            or bootstrap["executed_families"] != sorted(set(bootstrap["executed_families"]))
            or not set(bootstrap["executed_families"]) <= set(closures)
            or bootstrap.get("complete") is not True
            or not isinstance(bootstrap.get("fusion_version"), str)
            or not bootstrap["fusion_version"] or bootstrap["fusion_version"] == "?"):
        raise ValueError("family receipt has no retained full-run bootstrap")
    bootstrap_raw = _retained(bootstrap.get("raw"), evidence_dir)
    if bootstrap_raw is not None:
        originals = bootstrap_raw["stamps"]
        if (set(originals) != set(bootstrap["executed_families"]) or any(
                original.get("run_id") != receipt["bootstrap_run_id"]
                or original.get("fusion_version") != bootstrap["fusion_version"]
                for original in originals.values())):
            raise ValueError("bootstrap evidence incomplete")
    for name, closure in closures.items():
        stamp = aggregate_records(receipt)[name]
        _validate_stamp(name, stamp, closure, evidence_dir, current=require_current)
        if full_scope:
            machine_config.require_full_scope(stamp["scope"])
        if require_exercised and stamp["state"] == "held":
            reasons = "; ".join(row["act"] + ": " + row["reason"]
                                for row in stamp["omitted"] if row["state"] == "held")
            raise ValueError("aggregate incomplete; family held: " + name + " - " + reasons)
        if full_scope and any(condition["state"] == "not-in-scope"
                and condition["capability"] not in stamp["scope"]["quarantined"]
                for row in stamp["omitted"] for condition in row["conditions"]):
            raise ValueError("receipt is not full admitted scope: " + name)
        if stamp.get("state") != "not-in-scope":
            builds.add(stamp["fusion_version"])
    if require_current and len(builds) != 1:
        raise ValueError("family receipt mixes Fusion builds")
    lifecycle = receipt.get("lifecycle")
    scopes = [record["scope"] for record in aggregate_records(receipt).values()]
    if (not scopes or any(scope != scopes[0] for scope in scopes)
            or not isinstance(lifecycle, dict) or lifecycle.get("scope") != scopes[0]):
        raise ValueError("aggregate mixes machine/configuration/scope provenance")
    if full_scope and lifecycle.get("omitted"):
        raise ValueError("receipt is not full admitted lifecycle scope")
    if not isinstance(lifecycle, dict):
        raise ValueError("lifecycle reload evidence missing")
    _validate_lifecycle(lifecycle, source_hash or lifecycle.get("source_hash"),
                        lifecycle.get("fusion_version"), census, evidence_dir)
    if require_current and source_hash is not None and lifecycle.get("source_hash") != source_hash:
        raise ValueError("lifecycle source changed")
    if builds and lifecycle.get("fusion_version") not in builds:
        raise ValueError("lifecycle Fusion build differs from family stamps")
    for historical in receipt.get("lifecycle_history", []):
        _validate_lifecycle(historical, historical.get("source_hash"),
                            historical.get("fusion_version"), census, evidence_dir)
    if attestation is not None:
        exact_identity(attestation)
    return True


def write_aggregate(path, stamps, closures, census, run_id, full=False, evidence_dir=None,
                    lifecycle=None):
    """Atomically bootstrap or refresh stamps without importing legacy aggregate tables."""
    if full:
        if (set(stamps) != set(closures) or any(
                s.get("run_id") != run_id for s in stamps.values()
                if s["state"] != "not-in-scope")):
            raise ValueError("bootstrap requires one complete fresh native run")
        builds = {stamp["fusion_version"] for stamp in stamps.values()
                  if stamp["state"] != "not-in-scope"}
        if not builds:
            raise ValueError("bootstrap needs at least one executed family")
        if len(builds) != 1:
            raise ValueError("bootstrap mixes Fusion builds")
        if not lifecycle or lifecycle.get("run_id") != run_id:
            raise ValueError("bootstrap requires fresh lifecycle reload evidence")
        receipt = {"format": FORMAT, "bootstrap_run_id": run_id, "tool_census": census,
                   "bootstrap": {"run_id": run_id, "families": sorted(closures),
                                 "executed_families": sorted(
                                     name for name, record in stamps.items()
                                     if record["state"] != "not-in-scope"), "complete": True,
                                 "fusion_version": next(iter(builds)),
                                 "raw": retain_evidence({"stamps": {
                                     name: record for name, record in stamps.items()
                                     if record["state"] != "not-in-scope"}}, evidence_dir)},
                   "families": {name: record for name, record in stamps.items() if record["state"] != "not-in-scope"},
                   "not_in_scope": {name: record for name, record in stamps.items() if record["state"] == "not-in-scope"},
                   "lifecycle": lifecycle, "lifecycle_history": []}
    else:
        with open(path, encoding="utf-8") as fh:
            receipt = json.load(fh)
        if receipt.get("tool_census") != census or receipt.get("format") != FORMAT:
            raise ValueError("registration changed; run a new full bootstrap")
        validate_aggregate(receipt, closures, census, evidence_dir=evidence_dir,
                           require_current=False, require_exercised=False)
        if not lifecycle or lifecycle.get("run_id") != run_id:
            raise ValueError("refresh requires fresh lifecycle reload evidence")
        receipt.setdefault("lifecycle_history", []).append(receipt["lifecycle"])
        receipt["lifecycle"] = lifecycle
        for name, stamp in stamps.items():
            if (name not in closures or (stamp["state"] != "not-in-scope"
                                         and stamp.get("run_id") != run_id)):
                raise ValueError("refresh stamp came from another family or run")
            _validate_stamp(name, stamp, closures[name], evidence_dir)
        receipt.setdefault("not_in_scope", {})
        for name, stamp in stamps.items():
            receipt["families"].pop(name, None)
            receipt["not_in_scope"].pop(name, None)
            receipt["not_in_scope" if stamp["state"] == "not-in-scope" else "families"][name] = stamp
    validate_aggregate(receipt, closures, census, evidence_dir=evidence_dir,
                       require_current=full, require_exercised=False)
    directory = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix=".family-receipt-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(receipt, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return receipt


def aggregate_ledger(receipt, closures, census, skipped=None, source_hash=None):
    """Compose the legacy table from current family stamps, leaving stale evidence pending."""
    buckets = {key: set() for key in ("covered", "self-reported", "called", "refusals-only")}
    omissions = {}
    for name, closure in closures.items():
        stamp = aggregate_records(receipt).get(name)
        if stamp is None:
            continue
        try:
            _validate_stamp(name, stamp, closure)
        except (ValueError, OSError, KeyError, TypeError):
            continue
        for row in stamp["omitted"]:
            for tool in row["tools"]:
                omissions.setdefault(tool, "skipped: " + row["state"] + " " + row["act"] + " - " + row["reason"])
        for key, tools in stamp.get("evidence", {}).get("buckets", {}).items():
            buckets[key].update(tools)
    ledger = []
    lifecycle = receipt.get("lifecycle") or {}
    try:
        _validate_lifecycle(lifecycle, source_hash or lifecycle.get("source_hash"),
                            lifecycle.get("fusion_version"), census)
        lifecycle_current = lifecycle["state"] == "executed"
        if not lifecycle_current:
            omissions["sys_reload_addin"] = "skipped: not-in-scope allow.addin_reload is false"
    except (ValueError, OSError, KeyError, TypeError):
        lifecycle_current = False
    for tool in census:
        status = next((key for key, tools in buckets.items() if tool in tools), None)
        if tool == "sys_reload_addin" and lifecycle_current:
            status = "self-reported"
        ledger.append((tool, status or omissions.get(tool) or (skipped or {}).get(
            tool, "PENDING (no current family evidence)")))
    return ledger


def aggregate_modes(receipt, closures):
    """Compose actual act modes from each current family stamp."""
    result = []
    for name, closure in closures.items():
        stamp = aggregate_records(receipt).get(name)
        if stamp is None:
            continue
        try:
            _validate_stamp(name, stamp, closure)
        except (ValueError, OSError, KeyError, TypeError):
            continue
        result.extend(tuple(pair) for pair in stamp.get("act_modes", []))
    return result


def execution_id():
    """Return a fresh identifier for an actual local execution."""
    return uuid.uuid4().hex
