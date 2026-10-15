# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Snapshot and diff the installed Fusion API bindings, build to build, for the API audit.

  py -3 tests/api_inventory.py snapshot <version> [--package DIR]   -> outputs/api-inventory/<version>/
  py -3 tests/api_inventory.py diff <old-dir> <new-dir>              -> <new-dir>/inventory-diff.json
  py -3 tests/api_inventory.py surface-diff <old.py> <new.py>        -> <new-dir>/surface-diff.json
"""

import argparse
import ast
import glob
import hashlib
import importlib.util
import json
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(REPO_ROOT, "commands", "mcpServer", "tools")
OUT_ROOT = os.path.join(REPO_ROOT, "outputs", "api-inventory")
MODULES = ("core", "fusion", "cam", "drawing", "sim", "electron", "volume")
PREVIEW = "is a preview feature"
MARKERS = ("preview", "unsupported", "retired")
_RETIRED = re.compile(r"\bThis (?:class|enum|method|property|API|object|event|type) (?:is|has been) "
                      r"(?:retired|deprecated)\b", re.I)
_BINDING_GLOBS = (
    os.path.expanduser("~/AppData/Local/Autodesk/webdeploy/production/*/Api/Python/packages/adsk"),
    os.path.expanduser("~/AppData/Local/Autodesk/webdeploy/pre-production/*/Api/Python/packages/adsk"),
    os.path.expanduser("~/Library/Application Support/Autodesk/webdeploy/production/*/Autodesk "
                       "Fusion 360.app/Contents/Api/Python/packages/adsk"),
)


def newest_package():
    """Return the most recently written installed adsk package directory, or None."""
    found = [p for pattern in _BINDING_GLOBS for p in glob.glob(pattern) if os.path.isfile(os.path.join(p, "fusion.py"))]
    return max(found, key=os.path.getmtime) if found else None


def _markers(doc):
    """Return support markers from the complete binding docstring."""
    lower = doc.lower()
    return {"preview": PREVIEW in lower,
            "unsupported": "not officially supported" in lower,
            "retired": bool(_RETIRED.search(doc))}


def _saved_marker(row, marker, cutoff):
    """Return a saved support marker, or None if an old truncated doc cannot decide."""
    doc = row.get("doc") or ""
    if _markers(doc)[marker]:
        return True
    if marker in row:
        return bool(row[marker])
    return False if len(doc) < cutoff else None


def inventory(path):
    """Return {class: {bases, preview, doc, members}} for one SWIG binding module, by AST alone."""
    tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    classes = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ""
            members = {}
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    name = item.name
                    if name.startswith("__") or name == "classType" or name.startswith(("_get_", "_set_")):
                        continue
                    member_doc = ast.get_docstring(item) or ""
                    members[name] = {"kind": "method", "args": [a.arg for a in item.args.args if a.arg != "self"],
                                     "returns": ast.unparse(item.returns) if item.returns else None,
                                     **_markers(member_doc), "doc": member_doc[:400]}
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and not target.id.startswith("_") and target.id != "thisown":
                            members[target.id] = {"kind": "constant"}
            classes[node.name] = {"bases": [ast.unparse(b) for b in node.bases],
                                  **_markers(doc), "doc": doc[:600], "members": members}
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Attribute):
            target = node.targets[0]
            call = node.value
            if (isinstance(target.value, ast.Name) and target.value.id in classes and target.attr != "cast"
                    and isinstance(call, ast.Call) and getattr(call.func, "id", "") == "property"):
                doc = next((str(kw.value.value) for kw in call.keywords
                            if kw.arg == "doc" and isinstance(kw.value, ast.Constant)), "")
                writable = len([a for a in call.args if not (isinstance(a, ast.Constant) and a.value is None)]) >= 2
                classes[target.value.id]["members"][target.attr] = {
                    "kind": "property", "writable": writable,
                    **_markers(doc), "doc": doc[:400]}
    return classes


def snapshot(version, package):
    """Write one JSON per module plus summary.json under outputs/api-inventory/<version>/."""
    out_dir = os.path.join(OUT_ROOT, version)
    os.makedirs(out_dir, exist_ok=True)
    summary = {"fusion_version": version, "package": package, "modules": {}}
    for mod in MODULES:
        path = os.path.join(package, mod + ".py")
        if not os.path.exists(path):
            continue
        raw = open(path, "rb").read()
        classes = inventory(path)
        with open(os.path.join(out_dir, mod + ".json"), "w", encoding="utf-8") as handle:
            json.dump({"fusion_version": version, "module": mod, "sha256": hashlib.sha256(raw).hexdigest(),
                       "bytes": len(raw), "classes": classes}, handle, indent=1)
        summary["modules"][mod] = {"classes": len(classes), "preview_classes": sum(1 for c in classes.values() if c["preview"]),
                                   "members": sum(len(c["members"]) for c in classes.values()), "bytes": len(raw)}
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=1)
    return out_dir, summary


def _load_snapshot(directory):
    modules = {}
    for mod in MODULES:
        path = os.path.join(directory, mod + ".json")
        if os.path.exists(path):
            modules[mod] = json.load(open(path, encoding="utf-8"))["classes"]
    return modules


def tool_files():
    """Return {basename: source text} for every tool module, the map a removed member is searched in."""
    texts = {}
    for name in os.listdir(TOOLS_DIR):
        if name.endswith(".py"):
            texts[name] = open(os.path.join(TOOLS_DIR, name), encoding="utf-8", errors="replace").read()
    return texts


def members_still_named(removed):
    """Return {'Class.member': [tool files]} for removed members the tool tree still names."""
    texts = tool_files()
    hits = {}
    for key, member in removed:
        pattern = re.compile(r"\." + re.escape(member) + r"\b")
        users = sorted(fn for fn, text in texts.items() if pattern.search(text))
        if users:
            hits[key] = users
    return hits


def diff_snapshots(old_dir, new_dir):
    """Write <new-dir>/inventory-diff.json: classes and members added/removed per module, preview moves, tool hits."""
    old, new = _load_snapshot(old_dir), _load_snapshot(new_dir)
    report = {"old": old_dir, "new": new_dir, "modules": {}}
    removed_members = []
    for mod in sorted(set(old) | set(new)):
        o, n = old.get(mod, {}), new.get(mod, {})
        added = {c: {**{marker: _saved_marker(n[c], marker, 600) for marker in MARKERS},
                     "members": sorted(n[c]["members"])} for c in sorted(set(n) - set(o))}
        removed = {c: sorted(o[c]["members"]) for c in sorted(set(o) - set(n))}
        changed = {}
        transitions = {marker: {"left": [], "became": [], "undecided": 0,
                                "members_left": [], "members_became": [], "members_undecided": 0}
                       for marker in MARKERS}
        for cls in sorted(set(o) & set(n)):
            a, b = set(o[cls]["members"]), set(n[cls]["members"])
            if a != b:
                changed[cls] = {"added": sorted(b - a), "removed": sorted(a - b)}
                removed_members.extend((f"{mod}.{cls}.{m}", m) for m in sorted(a - b))
            for marker in MARKERS:
                was = _saved_marker(o[cls], marker, 600)
                now = _saved_marker(n[cls], marker, 600)
                if was is None or now is None:
                    transitions[marker]["undecided"] += 1
                elif was is False and now is True:
                    transitions[marker]["became"].append(cls)
                elif was is True and now is False:
                    transitions[marker]["left"].append(cls)
            for member in sorted(a & b):
                old_member = o[cls]["members"][member]
                new_member = n[cls]["members"][member]
                for marker in MARKERS:
                    was = _saved_marker(old_member, marker, 400)
                    now = _saved_marker(new_member, marker, 400)
                    if was is None or now is None:
                        transitions[marker]["members_undecided"] += 1
                    elif was is False and now is True:
                        transitions[marker]["members_became"].append(f"{cls}.{member}")
                    elif was is True and now is False:
                        transitions[marker]["members_left"].append(f"{cls}.{member}")
        report["modules"][mod] = {
            "classes": {"old": len(o), "new": len(n)}, "classes_added": added, "classes_removed": removed,
            "member_changes": changed,
            **{f"became_{marker}": entry["became"] for marker, entry in transitions.items()},
            **{f"left_{marker}": entry["left"] for marker, entry in transitions.items()},
            **{f"members_became_{marker}": entry["members_became"] for marker, entry in transitions.items()},
            **{f"members_left_{marker}": entry["members_left"] for marker, entry in transitions.items()},
            **{f"undecided_{marker}": entry["undecided"] for marker, entry in transitions.items()},
            **{f"members_undecided_{marker}": entry["members_undecided"] for marker, entry in transitions.items()},
        }
    report["removed_members_still_named_by_tools"] = members_still_named(removed_members)
    path = os.path.join(new_dir, "inventory-diff.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
    return path, report


def _load_surface(path):
    spec = importlib.util.spec_from_file_location("surface_" + hashlib.md5(path.encode()).hexdigest()[:8], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def diff_surfaces(old_path, new_path, out_dir):
    """Write <out-dir>/surface-diff.json from two generated api_surface.py files (factory-reachable classes)."""
    old, new = _load_surface(old_path), _load_surface(new_path)
    op, np_ = old.PROPERTIES, new.PROPERTIES
    of, nf = getattr(old, "FACTORIES", {}), getattr(new, "FACTORIES", {})
    ob, nb = set(getattr(old, "BOOL_METHODS", ())), set(getattr(new, "BOOL_METHODS", ()))
    changes, removed_members = {}, []
    for cls in sorted(set(op) & set(np_)):
        a, b = set(op[cls]), set(np_[cls])
        if a != b:
            changes[cls] = {"added": sorted(b - a), "removed": sorted(a - b)}
            removed_members.extend((f"{cls}.{m}", m) for m in sorted(a - b))
    report = {"old_build": getattr(old, "BINDINGS_BUILD", "?"), "new_build": getattr(new, "BINDINGS_BUILD", "?"),
              "classes": {"old": len(op), "new": len(np_), "added": sorted(set(np_) - set(op)), "removed": sorted(set(op) - set(np_))},
              "member_changes": changes,
              "factories": {"old": len(of), "new": len(nf), "added": sorted(set(nf) - set(of)), "removed": sorted(set(of) - set(nf)),
                            "changed": {k: [of[k], nf[k]] for k in sorted(set(of) & set(nf)) if of[k] != nf[k]}},
              "bool_methods": {"added": sorted(nb - ob), "removed": sorted(ob - nb)},
              "removed_members_still_named_by_tools": members_still_named(removed_members)}
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "surface-diff.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
    return path, report


def main():
    """Command-line entry: snapshot, diff or surface-diff."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("version")
    snap.add_argument("--package", default=None, help="an adsk package directory; default: the newest installed")
    dif = sub.add_parser("diff")
    dif.add_argument("old_dir")
    dif.add_argument("new_dir")
    surf = sub.add_parser("surface-diff")
    surf.add_argument("old_file")
    surf.add_argument("new_file")
    surf.add_argument("--out-dir", default=OUT_ROOT)
    args = ap.parse_args()
    if args.command == "snapshot":
        package = args.package or newest_package()
        if package is None:
            raise SystemExit("no installed adsk package found; pass --package")
        out_dir, summary = snapshot(args.version, package)
        print(json.dumps({"wrote": out_dir, "modules": summary["modules"]}, indent=1))
    elif args.command == "diff":
        path, report = diff_snapshots(args.old_dir, args.new_dir)
        counts = {mod: {"classes_added": len(r["classes_added"]), "classes_removed": len(r["classes_removed"]),
                        "classes_with_member_changes": len(r["member_changes"])} for mod, r in report["modules"].items()}
        print(json.dumps({"wrote": path, "modules": counts,
                          "removed_members_still_named_by_tools": report["removed_members_still_named_by_tools"]}, indent=1))
    else:
        path, report = diff_surfaces(args.old_file, args.new_file, args.out_dir)
        print(json.dumps({"wrote": path, "classes": {k: v for k, v in report["classes"].items() if k in ("old", "new")},
                          "classes_added": len(report["classes"]["added"]), "classes_removed": report["classes"]["removed"],
                          "member_changes": len(report["member_changes"]),
                          "removed_members_still_named_by_tools": report["removed_members_still_named_by_tools"]}, indent=1))


if __name__ == "__main__":
    main()
