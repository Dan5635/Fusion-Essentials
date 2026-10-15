# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""An adsk call that answers "did it work" may not have its answer thrown away.

An `api_surface.BOOL_METHODS` call on a resolved feature input fails as a bare statement or a bare
`safe(lambda: ...)`; `if not safe(...)` reads the bool and passes. _ALLOWED sites are exempt."""

import ast

import _corpus
import api_surface
from _input_resolution import _iter_tool_files, input_scopes

# Calls whose bool is genuinely uninteresting, keyed (file, the statement's own source text), each
# with the reason. A text repeated in one file exempts each copy. Shrink-only.
_ALLOWED = {
    ("assembly_move.py","mat.setToRotation(math.radians(float(rotate_deg)), axis_dir, pt)"):
        "Matrix3D math on a LOCAL matrix - the resulting transform is written to the occurrence and "
        "read back, and an unchanged pose after a move is already an error",
    ("assembly_move.py","mat.setToRotation(math.radians(float(rotate_deg)), "
                              "adsk.core.Vector3D.create(*axis_vec), origin)"): "as above",
    ("assembly_move.py","r.setToRotation(math.radians(float(ang)), "
                              "adsk.core.Vector3D.create(*vec), origin)"): "as above",
    ("assembly_move.py","mat.transformBy(r)"): "as above",
    ("assembly_move.py","mat.transformBy(tmat)"): "as above",
    ("model_create_component.py", "matrix.setToRotation(math.radians(float(rotate_deg)), "
                                  "adsk.core.Vector3D.create(*axis_vec), "
                                  "adsk.core.Point3D.create(0, 0, 0))"):
        "Matrix3D math on a local matrix that places a new occurrence, whose creation is verified "
        "by re-listing",
}


def _site(source, node):
    """The statement's OWN source text, whitespace-collapsed - the allowlist key, which a line move
    cannot stale."""
    return " ".join((ast.get_source_segment(source, node) or "").split())


def _bool_call(node):
    """The method name when `node` is a call to an unambiguously bool-returning adsk member."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    name = node.func.attr
    return name if name in api_surface.BOOL_METHODS else None


def _receiver(call):
    """The variable a method call is made ON ('inp.setDistanceExtent(...)' -> 'inp')."""
    owner = call.func.value
    return owner.id if isinstance(owner, ast.Name) else None


def _offenders_in(path):
    """[(lineno, site, var, method, how)] for every discarded bool from a call on a FEATURE INPUT -
    a refresh()/fit() elsewhere returning false is cosmetic, a declined setter is not."""
    out = []
    source = _corpus.text(path)
    for nodes, bound in input_scopes(_corpus.tree(path)):
        for node in nodes:
            # Only a BARE STATEMENT discards the value. `if not safe(lambda: x.setQuality(q)):`
            # reads the bool through safe() and acts on it, which is what this gate asks for.
            if not isinstance(node, ast.Expr):
                continue
            call, how = node.value, "the result is discarded"
            if isinstance(call, ast.Call):
                fname = call.func.attr if isinstance(call.func, ast.Attribute) else \
                    getattr(call.func, "id", None)
                if fname == "safe" and call.args and isinstance(call.args[0], ast.Lambda):
                    call = call.args[0].body
                    how = "wrapped in a bare safe(), so the bool AND any exception are swallowed"
            name = _bool_call(call)
            if name and _receiver(call) in bound:
                out.append((node.lineno, _site(source, node), _receiver(call), name, how))
    return out


class TestBoolReturnsChecked:
    def test_no_documented_bool_return_is_discarded(self):
        offenders, bound_inputs = [], 0
        for name, path in _iter_tool_files():
            bound_inputs += sum(len(bound) for _nodes, bound in input_scopes(_corpus.tree(path)))
            for lineno, site, var, method, how in _offenders_in(path):
                if (name, site) in _ALLOWED:
                    continue
                offenders.append(f"{name}:{lineno}: {var}.{method}() returns bool and {how}")
        assert api_surface.BOOL_METHODS and bound_inputs, (
            "nothing was checked: no bool-returning method is known, or no feature input resolved")
        assert not offenders, (
            'each of these documents "Returns true if successful" - a false answer means the '
            "setting never took, and the handler runs on to report success anyway:\n  "
            + "\n  ".join(offenders))
