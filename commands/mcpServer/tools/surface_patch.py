# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: fill CLOSED loop(s) of edges with surface face(s) - cap a hole, bridge a gap.
WRITES; the patch body's isSolid and the feature's groupContinuity are read back, never assumed.
"""

import math

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe, target_component
from . import _common
from . import _inputs
from . import _assert
from ._surface_common import _body_names_and_solid

app = adsk.core.Application.get()

# Patch may only create a NEW body or a NEW component.
_PATCH_OPS = ("new", "new_body", "new_component")

_CONTINUITY = {
"connected": "ConnectedSurfaceContinuityType",
"tangent": "TangentSurfaceContinuityType",
"curvature": "CurvatureSurfaceContinuityType",
}

# boundary: the CLOSED loop a patch fills.
_BOUNDARY = _inputs.EdgeLoopRef("boundary", closed=True, allow_sketch=True, required=True)
# interior_rails: B-Rep EDGES the patch surface must pass through. The API property also accepts
# sketch curves/points and construction points, but find_geometry mints handles for BRep faces and
# edges only, so an edge is the one kind this server can reference.
_INTERIOR_RAILS = _inputs.GeometryHandleList("interior_rails", require="edge", required=False)
_EDGE_CONDITION_EDGE = _inputs.GeometryHandle("edge", require="edge")


def _native_conditions_read(raw, expected_edges):
    """(ordered edge/settings arrays, error) from a native five-part continuity answer."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 5 or raw[0] is not True:
        return None, "PatchFeatureInput.getContinuity did not return success and four arrays."
    edges, conts, weights, flips = [] , [], [], []
    try:
        edges, conts, weights, flips = (list(raw[i]) for i in range(1, 5))
    except Exception:
        return None, "Patch continuity arrays could not be read."
    n = len(expected_edges)
    if any(len(a) != n for a in (edges, conts, weights, flips)):
        return None, "Patch continuity arrays do not match the boundary edge count."
    if (any(isinstance(weight, bool) or not isinstance(weight, (int, float))
            or not math.isfinite(weight) for weight in weights)
            or any(type(flipped) is not bool for flipped in flips)):
        return None, "Patch continuity weights or direction flags did not read as finite numbers and booleans."
    keys = [_common.native_identity(edge) for edge in edges]
    wanted = [_common.native_identity(edge) for edge in expected_edges]
    if (None in keys or None in wanted or len(set(keys)) != n or len(set(wanted)) != n
            or set(keys) != set(wanted)):
        return None, "Patch continuity edge identities do not match the requested boundary."
    return (edges, conts, weights, flips), None


def _set_edge_conditions(patch_input, boundary_edges, edge_conditions):
    """Set and read back the complete per-edge continuity map on one BRep boundary."""
    by_key = {}
    for i, spec in enumerate(edge_conditions):
        if not isinstance(spec, dict) or "edge" not in spec or "continuity" not in spec:
            return None, f"'edge_conditions'[{i}] needs 'edge' and 'continuity'."
        word = spec["continuity"]
        if word not in _CONTINUITY:
            return None, f"'edge_conditions'[{i}].continuity must be connected, tangent, or curvature."
        if "weight" in spec and (isinstance(spec["weight"], bool)
                or not isinstance(spec["weight"], (int, float)) or not math.isfinite(spec["weight"])):
            return None, f"'edge_conditions'[{i}].weight must be finite."
        if "flipped" in spec and not isinstance(spec["flipped"], bool):
            return None, f"'edge_conditions'[{i}].flipped must be true or false."
        edge, err = _EDGE_CONDITION_EDGE.resolve(spec["edge"])
        if err:
            return None, f"'edge_conditions'[{i}]: {err}"
        key = _common.native_identity(edge)
        if key is None:
            return None, f"'edge_conditions'[{i}] has unreadable native identity; reacquire its handle."
        if key in by_key:
            return None, f"'edge_conditions'[{i}] repeats an edge; list each boundary edge once."
        by_key[key] = (edge, spec)
    boundary_keys = [_common.native_identity(edge) for edge in boundary_edges]
    if (None in boundary_keys or len(set(boundary_keys)) != len(boundary_keys)
            or set(by_key) != set(boundary_keys)):
        return None, "'edge_conditions' must map every boundary edge exactly once, with no other edges."

    before, err = _native_conditions_read(patch_input.getContinuity(), boundary_edges)
    if err:
        return None, err
    ordered_edges, old_cont, old_weights, old_flips = before
    cont_values, weights, flips, words, keys = [], [], [], [], []
    for edge in ordered_edges:
        key = _common.native_identity(edge)
        _, spec = by_key[key]
        words.append(spec["continuity"])
        keys.append(key)
        cont_values.append(getattr(adsk.fusion.SurfaceContinuityTypes, _CONTINUITY[spec["continuity"]]))
        weights.append(float(spec["weight"]) if "weight" in spec else old_weights[len(weights)])
        flips.append(spec["flipped"] if "flipped" in spec else old_flips[len(flips)])
    try:
        setter = patch_input.setContinuity(cont_values, weights, flips)
    except Exception as exc:
        return None, f"PatchFeatureInput.setContinuity failed: {exc}"
    if setter is not True:
        return None, "PatchFeatureInput.setContinuity did not return true."
    after, err = _native_conditions_read(patch_input.getContinuity(), ordered_edges)
    if err:
        return None, err
    read_edges, read_cont, read_weights, read_flips = after
    if ([_common.native_identity(e) for e in read_edges] !=
            [_common.native_identity(e) for e in ordered_edges]
            or read_cont != cont_values or read_flips != flips
            or any(not isinstance(g, (int, float)) or abs(g - w) > 1e-12
                   for g, w in zip(read_weights, weights))):
        return None, "PatchFeatureInput.getContinuity did not retain the requested edge conditions."
    expected = {keys[i]: {"edge": by_key[keys[i]][1]["edge"], "word": words[i],
                          "continuity": cont_values[i], "weight": weights[i],
                          "flipped": flips[i]} for i in range(len(keys))}
    return expected, None


def _feature_edge_conditions(design, feature, boundary_edges, request):
    """Read the created patch's edge settings at its timeline marker and restore the prior marker."""
    marker, _count = _common.timeline_marker(design)
    raw, marker_err = _common.rolled_to(design, feature, lambda: feature.getContinuity(),
                                        "patch edge conditions")
    restored, _ = _common.timeline_marker(design)
    if marker_err or restored != marker:
        return None, marker_err or "Patch edge-condition read did not restore the timeline marker."
    read, err = _native_conditions_read(raw, boundary_edges)
    if err:
        return None, err
    edges, conts, weights, flips = read
    rows = []
    for i, edge in enumerate(edges):
        key = _common.native_identity(edge)
        want = request.get(key)
        word = next(
            (word for word, member in _CONTINUITY.items()
             if member and conts[i] == safe(lambda m=member: getattr(adsk.fusion.SurfaceContinuityTypes, m))), None)
        if (want is None or word != want["word"] or flips[i] != want["flipped"]
                or not isinstance(weights[i], (int, float))
                or abs(weights[i] - want["weight"]) > 1e-12):
            return None, "PatchFeature.getContinuity did not retain the requested edge conditions."
        rows.append({"edge": want["edge"], "continuity": word,
                     "weight": weights[i], "flipped": flips[i]})
    if any(row["edge"] is None for row in rows):
        return None, "PatchFeature.getContinuity returned an edge outside the typed boundary map."
    return rows, None


def _rails_readback(patch_input, expected):
    """Read interiorRailsAndPoints back as (count, error) - the count the payload publishes."""
    # The read-back is a FRESH ObjectCollection, never the object assigned, so identity (and
    # set_verified's != compare) cannot verify it; an EMPTY collection's count reads None.
    got = safe(lambda: patch_input.interiorRailsAndPoints)
    n = safe(lambda: got.count)
    n = 0 if n is None else int(n)
    if n != expected:
        return n, (f"interior_rails did not take - PatchFeatureInput.interiorRailsAndPoints reads "
                   f"back {n} entity(ies) after assigning {expected}, so the patch would run "
                   "without them.")
    return n, ""


def _patch_note(is_solid):
    """The sentence a patch payload states its RESULT with - worded off the isSolid actually read
    back off the patch body, never off the expectation that a patch makes a surface."""
    if is_solid is False:
        return "Closed boundary filled with a surface (isSolid=false)."
    if is_solid is True:
        return ("Closed boundary filled, and the result reads back isSolid=true - a SOLID, not the "
                "open surface a patch normally makes.")
    return ("Closed boundary filled, but no result body's isSolid flag could be read back - "
            "whether the patch is an open surface is UNVERIFIED.")


def _boundary_passed(n, checked):
    """The sentence a failure states what this call handed the patch with."""
    if n == 1:
        return "The boundary was one edge for Fusion to complete into a loop."
    if checked:
        return f"The boundary's {n} edges were checked to close and passed in loop order."
    return f"The boundary's {n} edges were passed in the order given, their loop not checked."


def _continuity_word(value):
    """The continuity key a SurfaceContinuityTypes value reads as, or None."""
    for key, member in _CONTINUITY.items():
        if value is not None and value == safe(
                lambda m=member: getattr(adsk.fusion.SurfaceContinuityTypes, m)):
            return key
    return None


def _patch_one_loop(comp, boundary, op, cont, cont_key, rails=(), edge_conditions=None):
    """Patch ONE closed loop. boundary = a single edge handle or a list of edge handles forming one
    loop. Returns (result_dict, error_str). On success result_dict has the feature/body info; the
    error_str is None. Resolves the loop's edges via _BOUNDARY, then createInput->add."""
    resolved, berr = _BOUNDARY.resolve(boundary)
    if berr:
        return None, berr
    coll, meta = resolved
    ents = meta["entities"]
    if not ents:
        return None, "boundary resolved to no edges. Pass edge handle(s) forming a closed loop."
    boundary_kind = meta.get("boundary_kind", "edges")
    if edge_conditions and (boundary_kind != "edges" or not meta.get("loop_checked")):
        return None, ("'edge_conditions' needs a checked closed B-Rep edge loop; pass every boundary "
                      "edge handle in loop order, not a sketch boundary or one auto-completed edge.")
    if boundary_kind != "edges" and _common.same_component(
            comp, safe(lambda: _common.design().rootComponent)) is not True:
        return None, "Sketch boundaries require the root component active; activate it before patching."
    if boundary_kind != "edges" and (cont_key != "connected" or rails or
                                     op != adsk.fusion.FeatureOperations.NewBodyFeatureOperation):
        return None, ("Sketch boundaries take continuity='connected', operation='new' and no "
                      "interior_rails. Use a body-edge boundary for the other patch options.")
    passed = (f"The boundary was a sketch {boundary_kind}." if boundary_kind != "edges" else
              _boundary_passed(len(ents), meta["loop_checked"]))
    # Only a set checked to close has ruled that cause out; one edge or an unchecked set keeps it.
    loop_hint = (passed if meta["loop_checked"] else "(The boundary must form a CLOSED loop - pass "
                 "the loop's edges, or a single edge Fusion can auto-complete.)")
    # A single edge -> pass the edge itself (Fusion auto-finds the connected loop); else the collection.
    boundary_arg = ents[0] if len(ents) == 1 else coll
    try:
        patch_input = comp.features.patchFeatures.createInput(boundary_arg, op)
        # PatchFeatureInput.continuity is retired: it reads back on the input and the build ignores
        # it (measured). The group pair carries the request, and the FEATURE's groupContinuity is
        # what the reply reports. The enum class is SurfaceContinuityTypes (PLURAL).
        for prop, value, label in (("isGroupEdges", True, "isGroupEdges=true"),
                                   ("groupContinuity", cont, f"continuity={cont_key}")):
            cerr = _common.set_verified(patch_input, prop, value, label, "PatchFeatureInput")
            if cerr:
                return None, cerr
        rail_count = None
        if rails:
            rail_coll = adsk.core.ObjectCollection.create()
            for r in rails:
                rail_coll.add(r)
            patch_input.interiorRailsAndPoints = rail_coll
            rail_count, rerr = _rails_readback(patch_input, len(rails))
            if rerr:
                return None, rerr
        conditions_readback = None
        if edge_conditions:
            conditions_readback, cerr = _set_edge_conditions(patch_input, ents, edge_conditions)
            if cerr:
                return None, cerr
        feature = comp.features.patchFeatures.add(patch_input)
    except Exception as e:
        msg = str(e).lower()
        # These strings ('invalid argument chainOptions', ASM_BL_NON_MAN_EDVERT, PATCH_NO_TOOLBODY)
        # have more than one cause, and the string tells none of them apart - so the error says
        # what this call passed and names the two causes seen as candidates only.
        if any(s in msg for s in ("chainoptions", "non_man", "non-man", "toolbody")):
            return None, (f"Patch failed: {e}. {passed} Candidate causes, not a complete list: (1) a "
                "degenerate TANGENT saddle opening whose rim is two half-edges - pass both as the "
                "boundary list; (2) an edge loop SPLIT by a later feature (a fillet, say) into 3+ "
                "segments - pass ALL of the loop's edges, or patch the opening before the feature "
                "that splits it. find_geometry counts the opening's edges: 2 fits case (1), more "
                "fits case (2).")
        if rails:
            return None, (f"Patch failed: {e}. With interior_rails there are two candidate causes and "
                "this message asserts neither: the boundary does not form a CLOSED loop, or a rail "
                "edge does not lie on the surface the boundary spans (a rail must be interior to the "
                "patch). Retry WITHOUT interior_rails to tell them apart: if it succeeds, the rails "
                "are the cause.")
        return None, f"Patch failed: {e}. {loop_hint}"
    if not feature:
        return None, _common.no_feature_error(_common.design(), "Patch", loop_hint)
    names, is_solid = _body_names_and_solid(feature)
    if not names:
        return None, ("Patch reported success but the feature owns no result body - the loop was "
                      "not filled. "
                      + _common.failed_effect_remedy(_common.design(), feature))
    feature_conditions = None
    if conditions_readback is not None:
        feature_conditions, cerr = _feature_edge_conditions(
            _common.design(), feature, ents, conditions_readback)
        if cerr:
            return None, (f"Patch '{safe(lambda: feature.name)}' was built, but its edge conditions "
                          f"could not be verified: {cerr}. "
                          + _common.failed_effect_remedy(_common.design(), feature))
    landed = safe(lambda: feature.groupContinuity)
    word = _continuity_word(landed)
    if landed is not None and word != cont_key:
        return None, (f"Patch '{safe(lambda: feature.name)}' was built, but the feature reads "
                      f"groupContinuity {word or landed}, not {cont_key}, so it does not carry the "
                      "continuity asked for. "
                      + _common.failed_effect_remedy(_common.design(), feature))
    return {
    "feature": safe(lambda: feature.name),
    "result_body": names[0] if names else None,
    "result_bodies": names,
    "is_solid": is_solid,
    "continuity": word,
    "group_weight": (_common.measured(lambda: feature.groupWeight)
                     if cont_key != "connected" else None),
    "boundary_edge_count": len(ents) if boundary_kind == "edges" else None,
    "boundary_kind": boundary_kind,
    "interior_rail_count": rail_count,
    "edge_conditions": feature_conditions,
    }, None


def _unverified(**reads):
    """The names of the reads that came back None, or None when every one read."""
    return [k for k, v in reads.items() if v is None] or None


def handler(boundary=None, boundaries=None, continuity: str = "connected",
            operation: str = "new", interior_rails=None, edge_conditions=None) -> dict:
    """Fill closed loop(s) of edges with surface face(s) - "cap the hole(s)"."""
    op_key = (operation or "new").strip().lower()
    if op_key not in _PATCH_OPS:
        return error(f"Unknown operation '{operation}'. Patch supports: new, new_component.")
    cont_key = (continuity or "connected").strip().lower()
    if cont_key not in _CONTINUITY:
        return error(f"Unknown continuity '{continuity}'. Use: connected, tangent, curvature.")

    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")
    comp = target_component(design)
    op = getattr(adsk.fusion.FeatureOperations, _common.OPERATIONS[op_key])
    cont = safe(lambda: getattr(adsk.fusion.SurfaceContinuityTypes, _CONTINUITY[cont_key]))

    has_rails = interior_rails not in (None, "", [])
    has_edge_conditions = edge_conditions not in (None, "", [])
    if has_edge_conditions and boundaries not in (None, "", []):
        return error("'edge_conditions' maps one complete boundary; use 'boundary' and omit 'boundaries'.")
    if has_rails and boundaries not in (None, "", []):
        return error("'interior_rails' fits ONE patch surface, so it goes with 'boundary' (a single "
                     "loop). With 'boundaries' every loop would be handed the same rails.")
    rail_ents = []
    if has_rails:
        rail_ents, rerr = _INTERIOR_RAILS.resolve(interior_rails)
        if rerr:
            return error(rerr)

    # Normalise to a list of loops. 'boundaries' (multi) wins; else the single 'boundary'.
    if boundaries not in (None, "", []):
        loops = boundaries if isinstance(boundaries, (list, tuple)) else [boundaries]
        multi = True
    elif boundary not in (None, "", []):
        loops = [boundary]
        multi = False
    else:
        return error("Pass 'boundary' (one loop) or 'boundaries' (a list of loops, each an edge "
    "handle Fusion auto-completes - the way to patch every hole in one call).")

    results, errors = [], []
    for i, loop in enumerate(loops):
        res, lerr = _patch_one_loop(comp, loop, op, cont, cont_key, rail_ents,
                                    edge_conditions=edge_conditions if i == 0 and has_edge_conditions else None)
        if lerr:
            errors.append({"index": i, "error": lerr})
        else:
            results.append(res)

    # Single-loop call keeps the original flat shape (back-compat).
    if not multi:
        if errors:
            return error(errors[0]["error"])
        r = results[0]
        payload = {
        "patched": True,
        "feature": r["feature"],
        "operation": op_key,
        "continuity": r["continuity"],  # the feature's own groupContinuity, not the request
        "result_body": r["result_body"],
        "result_bodies": r["result_bodies"],
        "is_solid": r["is_solid"],      # read off the patch body, not the module's expectation
        "boundary_edge_count": r["boundary_edge_count"],
        "boundary_kind": r["boundary_kind"],
        "note": _patch_note(r["is_solid"]),
        }
        unverified = _unverified(is_solid=r["is_solid"], continuity=r["continuity"])
        if unverified:
            payload["unverified"] = unverified
        if r["group_weight"] is not None:
            payload["group_weight"] = r["group_weight"]
        if r["interior_rail_count"] is not None:
            # the count PatchFeatureInput.interiorRailsAndPoints reads back, not the number asked for
            payload["interior_rail_count"] = r["interior_rail_count"]
        if r["edge_conditions"] is not None:
            payload["edge_conditions"] = r["edge_conditions"]
        return ok(payload)

    # Multi-loop: report how many patched + per-loop bodies + any per-loop failures.
    all_bodies = [n for r in results for n in r["result_bodies"]]
    flags = [r["is_solid"] for r in results]
    agg = True if True in flags else (False if False in flags else None)
    # A patch whose continuity read back otherwise is an error above, so every landed one reads
    # the request or nothing.
    landed = cont_key if all(r["continuity"] == cont_key for r in results) else None
    payload = {
        "patched": len(results),
        "requested": len(loops),
        "failed": len(errors),
        "operation": op_key,
        "continuity": landed if results else None,
        "result_bodies": all_bodies,
        "patches": [{"feature": r["feature"], "bodies": r["result_bodies"],
                     "is_solid": r["is_solid"]} for r in results],
        "errors": errors,
        "is_solid": agg,
        "note": (f"Patched {len(results)} of {len(loops)} loop(s)."
                 + (" " + _patch_note(agg) if results else "")
                 + (" Some loops failed - see 'errors'." if errors else "")),
    }
    unverified = _unverified(is_solid=agg, continuity=landed) if results else None
    if unverified:
        payload["unverified"] = unverified
    return ok(payload)


TOOL_DESCRIPTION = (
    "Patch closed loops; read per-edge conditions; compare seam normals at matching points."
)

tool = (
    Tool.create_simple(name="surface_patch", description=TOOL_DESCRIPTION)
    .add_input_property("boundary", {**_BOUNDARY.schema(),
        "description": "Closed edge loop, profile handle/{sketch,profile_index}, or four sketch-line handles in loop order."})
    .add_input_property("boundaries", {"type": "array", "items": {"type": ["string", "array", "object"]},
            "description": "One boundary per entry."})
    .add_input_property(*_inputs.Choice("continuity", ["connected", "tangent", "curvature"],
        default="connected").as_property())
    .add_input_property("interior_rails", {**_INTERIOR_RAILS.schema(),
        "description": "find_geometry edges fitted by patch."})
    .add_input_property("edge_conditions", {"type": "array", "minItems": 1,
        "description": "Complete map; overrides grouped settings.",
        "items": {"type": "object", "properties": {
            "edge": {"type": "string", "description": "Unique patch-boundary edge handle from find_geometry."},
            "continuity": {"type": "string", "enum": ["connected", "tangent", "curvature"]},
            "weight": {"type": "number", "description": "Finite tangent/curvature weight; ignored for connected."},
            "flipped": {"type": "boolean", "description": "Select this edge's other adjacent source face."},
        }, "required": ["edge", "continuity"], "additionalProperties": False}})
    .add_input_property("operation", {"type": "string", "enum": ["new", "new_component"],
        "default": "new"})
    .strict_schema()
)
item = Item.create_tool_item(tool=tool, write="write", handler=handler,
                             run_on_main_thread=True,
                             postconditions=[_assert.FeatureHealthy(), _assert.SurfaceAreaAdded()],
                             verification=Verification(
                                 kind="inline", rung="value",
                                 evidence_test="tests/unit/test_surface_patch.py"
                                               "::TestSurfacePatch"
                                               "::test_tangent_the_feature_does_not_read_back"
                                               "_is_an_error"))


def register_tool():
    register(item)
