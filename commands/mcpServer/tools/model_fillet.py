# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: round the edges of a body - constant radius, variable radius along a tangent
chain, chord length, or a rule fillet over the edges of whole faces. WRITES.
"""

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe, scale, target_component
from . import _common
from . import _geom
from . import _inputs
from . import _assert
from ._edge_common import (_BODY, _EDGES, _EDGE_FILTER_DESC, _FACES, _TANGENT_CHAIN_DESC, _apply,
                           _size_hint)

app = adsk.core.Application.get()

_FILLET_TYPE = _inputs.Choice("fillet_type",
                              ["constant", "variable", "chord_length", "rule", "full_round",
                               "asymmetric"],
                              default="constant")
_TOPOLOGY = _inputs.Choice("topology", ["rounds_and_fillets", "rounds_only", "fillets_only"],
                           default="rounds_and_fillets")
_RULE_FACES_TWO = _inputs.GeometryHandleList("second_faces", require="face", required=False)
_CENTER_FACE = _inputs.GeometryHandle("center_face", require="face", required=False,
                                      description="full_round only: the face the round replaces.")


def _variable_radius_spec(end_radius, positions, radii):
    """(spec, error) for a variable-radius edge set: the far-end radius plus the parallel
    positions/radii arrays that place any intermediate radii along the chain."""
    if end_radius in (None, ""):
        return None, ("A variable-radius fillet needs 'end_radius' - the radius at the far end of "
                      "the edge chain, where 'radius' is the radius at the start.")
    try:
        end = float(end_radius)
    except (TypeError, ValueError):
        return None, f"'end_radius' must be a number, got {end_radius!r}."
    if end <= 0:
        return None, f"'end_radius' must be positive, got {end}."
    raw_pos = list(positions) if positions not in (None, "") else []
    raw_rad = list(radii) if radii not in (None, "") else []
    if len(raw_pos) != len(raw_rad):
        return None, (f"'positions' and 'radii' must be the same length - got {len(raw_pos)} "
                      f"position(s) and {len(raw_rad)} radius(es). Each position places the radius "
                      "paired with it at the same index.")
    pos, rad = [], []
    for i, p in enumerate(raw_pos):
        try:
            v = float(p)
        except (TypeError, ValueError):
            return None, f"'positions'[{i}] must be a number, got {p!r}."
        # The interval is OPEN: add() raises "position value must be greater than 0 and less than 1"
        # for an endpoint. The two ends already carry 'radius' and 'end_radius'.
        if not 0.0 < v < 1.0:
            return None, (f"'positions'[{i}] is {v} - a position is the fraction along the edge "
                          "chain where its radius applies, and must be between 0 and 1 exclusive. "
                          "The chain's two ends take their radii from 'radius' and 'end_radius'.")
        pos.append(v)
    for i, r in enumerate(raw_rad):
        try:
            v = float(r)
        except (TypeError, ValueError):
            return None, f"'radii'[{i}] must be a number, got {r!r}."
        if v <= 0:
            return None, f"'radii'[{i}] must be positive, got {v}."
        rad.append(v)
    return {"type": "variable", "end_radius": end, "positions": pos, "radii": rad}, None


def _owner_label(edge, owner):
    """The component definition and placement named by an edge handle."""
    name = safe(lambda: owner.name) or "unnamed"
    path = safe(lambda: edge.assemblyContext.fullPathName)
    return f"component '{name}'" + (f" at '{path}'" if path else "")


def _cross_owner_refusal(edges):
    """Refuse edge handles from distinct component definitions before creating a fillet."""
    owners = []
    for edge in edges:
        owner = safe(lambda edge=edge: edge.body.parentComponent)
        if owner is None:
            continue
        for other, other_edge in owners:
            if _common.same_component(owner, other) is False:
                first = _owner_label(other_edge, other)
                second = _owner_label(edge, owner)
                return (f"Fillet edge handles span {first} and {second}. Fillet one component's "
                        "edges per call; no feature was created.")
        owners.append((owner, edge))
    return None


def _edge_sets_spec(edge_sets):
    """(resolved disjoint edge-set specs, error) for the bounded mixed-set route."""
    if not isinstance(edge_sets, (list, tuple)) or not edge_sets:
        return None, "'edge_sets' must contain at least one edge set."
    specs, seen = [], set()
    for i, raw in enumerate(edge_sets):
        if not isinstance(raw, dict):
            return None, f"'edge_sets'[{i}] must be an object."
        kind = raw.get("fillet_type", "constant")
        if kind not in ("constant", "asymmetric"):
            return None, f"'edge_sets'[{i}].fillet_type must be constant or asymmetric - got {kind!r}."
        if "continuity" in raw and kind == "asymmetric":
            return None, (f"'edge_sets'[{i}] is asymmetric and cannot take an explicit continuity value, "
                          "including tangent; omit continuity for this set.")
        if "continuity" in raw and raw["continuity"] not in ("tangent", "curvature"):
            return None, f"'edge_sets'[{i}].continuity must be tangent or curvature."
        if kind == "asymmetric" and raw.get("end_radius") in (None, ""):
            return None, f"'edge_sets'[{i}] asymmetric fillet needs 'end_radius'."
        if kind == "constant" and any(k in raw for k in ("end_radius", "flipped")):
            return None, f"'edge_sets'[{i}] end_radius/flipped apply only to asymmetric sets."
        if raw.get("radius") in (None, ""):
            return None, f"'edge_sets'[{i}] needs 'radius'."
        if "tangent_chain" in raw and not isinstance(raw["tangent_chain"], bool):
            return None, f"'edge_sets'[{i}].tangent_chain must be true or false."
        if "flipped" in raw and not isinstance(raw["flipped"], bool):
            return None, f"'edge_sets'[{i}].flipped must be true or false."
        handles = raw.get("edges")
        if not isinstance(handles, (list, tuple)) or not handles:
            return None, f"'edge_sets'[{i}].edges must contain edge handles."
        if any(not isinstance(handle, str) for handle in handles):
            return None, f"'edge_sets'[{i}].edges must contain edge handle strings."
        if len(handles) != len(set(handles)):
            return None, f"'edge_sets'[{i}].edges contains a duplicate handle."
        ents, err = _EDGES.resolve(handles)
        if err:
            return None, f"'edge_sets'[{i}]: {err}"
        owner_error = _cross_owner_refusal(ents)
        if owner_error:
            return None, f"'edge_sets'[{i}]: {owner_error}"
        keys = [_common.native_identity(edge) for edge in ents]
        if None in keys or len(set(keys)) != len(keys):
            return None, f"'edge_sets'[{i}] edge identity is unreadable or repeated; reacquire unique handles."
        overlap = seen.intersection(keys)
        if overlap:
            return None, f"'edge_sets'[{i}] overlaps an earlier set; edge sets must be disjoint."
        seen.update(keys)
        specs.append({"edges": ents, "fillet_type": kind, "radius": raw["radius"],
                      "end_radius": raw.get("end_radius"), "flipped": raw.get("flipped", False),
                      "continuity": raw.get("continuity"),
                      "tangent_chain": raw.get("tangent_chain", True)})
    return specs, None


def _topology_type(key):
    t = adsk.fusion.RuleFilletTopologyTypes
    return {"rounds_and_fillets": t.RoundsAndFilletsRuleFilletTopologyType,
            "rounds_only": t.RoundsOnlyRuleFilletTopologyType,
            "fillets_only": t.FilletsOnlyRuleFilletTopologyType}[key]


def _rule_fillet(radius, units, faces, second_faces, topology):
    """Round every edge of the given faces (a Rule Fillet), or only the edges between two face
    sets. The selection is the FACES, so no per-edge handle list is involved."""
    k = scale(units)
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    # The same two forms every fillet radius takes. Only a LITERAL can be guarded here, before the
    # design an expression resolves against is in hand; an expression is guarded - and its applied
    # radius compared - on the value the units engine evaluates it to, below.
    as_expression = _inputs.looks_like_expression(radius)
    r = None
    if not as_expression:
        try:
            r = float(radius)
        except Exception:
            return error("'radius' must be a number or a parameter-expression string like "
                         "'WallT/2'.")
        if r <= 0:
            return error("Provide a positive radius.")
    topo, terr = _TOPOLOGY.resolve(topology)
    if terr:
        return error(terr)
    if faces in (None, "", []):
        return error("A rule fillet needs 'faces' - find_geometry face handles. Every edge of those "
                     "faces is rounded; add 'second_faces' to round only the edges between the two "
                     "sets.")
    first, ferr = _FACES.resolve(faces)
    if ferr:
        return error(ferr)
    second = None
    if second_faces not in (None, "", []):
        second, serr = _RULE_FACES_TWO.resolve(second_faces)
        if serr:
            return error(serr)

    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")
    comp = target_component(design)

    verify_bodies = _geom.owning_bodies(list(first) + list(second or []))
    vol_before = _geom.volumes(verify_bodies)
    rv, want_cm, rverr = _inputs.length_value_input(radius, k, design, "radius")
    if rverr:
        return error(rverr)
    if as_expression and want_cm is not None and want_cm <= 0:
        return error(f"Provide a positive radius: the expression '{str(radius).strip()}' evaluates "
                     f"to {round(want_cm / k, 6)} {units}.")
    try:
        ri = comp.features.filletFeatures.createRuleFilletInput()
        # The face sets cross as plain Python lists, not an ObjectCollection.
        applied = (ri.setByBetweenFacesOrFeatures(list(first), list(second)) if second
                   else ri.setByAllEdges(list(first)))
        if applied is False:
            return error("The rule fillet refused the given faces, so nothing was created. Re-run "
                         "find_geometry for fresh face handles.")
        ri.radius = rv
        ri.topologyType = _topology_type(topo)
        feature = comp.features.filletFeatures.addRuleFillet(ri)
    except Exception as e:
        return error(f"Rule fillet failed: {e}.{_size_hint(str(e), 'radius')}")
    if not feature:
        return error(_common.no_feature_error(design, "Rule fillet"))

    faces_created = safe(lambda: feature.faces.count)
    vol_delta, vol_readable = _geom.volume_delta(verify_bodies, vol_before)
    moved = abs(vol_delta) >= _common.NO_VOLUME_CHANGE_CM3 if vol_readable else faces_created != 0
    if not moved:
        return error(
            f"Rule fillet reported success but rounded nothing. topology '{topo}' may exclude every "
            "edge of the selected faces ('rounds_only' takes convex edges, 'fillets_only' concave "
            "ones), or the faces meet smoothly and have no corner to round. "
            + _common.delete_failed_feature(design, feature)[1])

    # ruleFilletSettings carries the applied radius (a ModelParameter, in cm) and topology, so
    # both are read off the feature rather than echoed: a setter the API silently ignored would
    # otherwise be reported as if it had landed.
    settings = safe(lambda: feature.ruleFilletSettings)
    got_r_cm = safe(lambda: settings.radius.value) if settings is not None else None
    got_topo = safe(lambda: settings.topologyType) if settings is not None else None
    want_topo = safe(lambda: _topology_type(topo))
    # Both forms are compared: a literal against its own scaled number, an expression against the
    # value the units engine evaluated it to. want_cm None means nothing answered a number, and
    # treating that as zero would roll a healthy fillet out.
    if want_cm is not None and isinstance(got_r_cm, float) and abs(got_r_cm - want_cm) > 1e-6:
        asked = f"{round(want_cm / k, 6)} {units}"
        if as_expression:
            asked += f" (what the expression '{str(radius).strip()}' evaluates to)"
        return error(f"The rule fillet was created but its radius reads back "
                     f"{round(got_r_cm / k, 6)} {units}, not the requested {asked}. "
                     + _common.failed_effect_remedy(design, feature))
    if got_topo is not None and want_topo is not None and got_topo != want_topo:
        return error(f"The rule fillet was created but its topology is not the requested "
                     f"'{topo}'. " + _common.failed_effect_remedy(design, feature))

    payload = {
        "filleted": True,
        "feature": safe(lambda: feature.name),
        "fillet_type": "rule",
        "rule": "between_faces" if second else "all_edges",
        "radius": (round(got_r_cm / k, 6) if isinstance(got_r_cm, float)
                   else _inputs.expression_report(radius)),
        "units": units,
        "topology": topo,
        "faces_selected": len(first) + (len(second) if second else 0),
        "note": "Rule fillet created - the rounded edge set is defined by the selected FACES, not "
                "by individual edge handles. Pair with view_screenshot.",
    }
    if as_expression:
        # 'radius' is the value the FEATURE reports; without this the caller cannot tell that value
        # came from a parameter rather than from a number they fixed.
        payload["radius_expression"] = str(radius).strip()
    if faces_created is not None:
        payload["faces_created"] = faces_created
    if vol_readable:
        payload["volume_delta_cm3"] = round(vol_delta, 6)
    return ok(payload)


def _full_round_fillet(center_face, faces, second_faces):
    """Replace one face with a round tangent to the faces either side of it (a Full Round Fillet).
    The round's radius comes from those side faces, so no radius is given."""
    centre, cerr = _CENTER_FACE.resolve(center_face)
    if cerr or centre is None:
        return error(cerr or "A full round fillet needs 'center_face' - the find_geometry face "
                             "handle of the face the round replaces.")
    if faces in (None, "", []) or second_faces in (None, "", []):
        return error("A full round fillet needs 'faces' and 'second_faces' - the face handles on "
                     "either side of 'center_face'. The API refuses an empty side set "
                     "('invalid argument sideOneFaces'), so both must be given.")
    one, oerr = _FACES.resolve(faces)
    if oerr:
        return error(oerr)
    two, terr = _RULE_FACES_TWO.resolve(second_faces)
    if terr:
        return error(terr)

    design = _common.design()
    if not design:
        return error("No active design. Create or open a document first (see doc_new).")
    comp = target_component(design)
    verify_bodies = _geom.owning_bodies([centre] + list(one) + list(two))
    vol_before = _geom.volumes(verify_bodies)
    try:
        fi = comp.features.filletFeatures.createFullRoundFilletInput()
        # The face sets cross as plain Python lists, and areAutomaticSideFaces does not make the
        # lists optional: an empty sideOneFaces raises whatever that flag says.
        if not fi.faceSets.add(centre, list(one), list(two), False):
            return error("The full round face set was refused, so nothing was created. Re-run "
                         "find_geometry for fresh face handles.")
        feature = comp.features.filletFeatures.addFullRoundFillet(fi)
    except Exception as e:
        return error(f"Full round fillet failed: {e}. The three faces must be adjacent - each side "
                     "face sharing an edge with 'center_face'.")
    if not feature:
        return error(_common.no_feature_error(design, "Full round fillet"))

    # fullRoundFilletFaceSets names WHICH fillet got built without reading an enum: it answers a
    # collection on a full round and None on any other fillet, measured both ways.
    face_sets = safe(lambda: feature.fullRoundFilletFaceSets.count)
    vol_delta, vol_readable = _geom.volume_delta(verify_bodies, vol_before)
    moved = (abs(vol_delta) >= _common.NO_VOLUME_CHANGE_CM3 if vol_readable
             else face_sets not in (None, 0))
    if face_sets in (None, 0) or not moved:
        sets = "an unreadable number of" if face_sets is None else face_sets
        return error(
            "Full round fillet reported success but did not build one: the created feature answers "
            f"{sets} full-round face set(s) (any other fillet answers none) and the body's "
            f"measured volume changed by "
            f"{round(vol_delta, 6) if vol_readable else 'an unreadable amount'} cm3. "
            + _common.delete_failed_feature(design, feature)[1])

    payload = {
        "filleted": True,
        "feature": safe(lambda: feature.name),
        "fillet_type": "full_round",
        "faces_selected": 1 + len(one) + len(two),
        "note": "Full round fillet created - its radius is set by the two side faces, so 'radius' "
                "does not drive it. fillet_type and face_sets are read off the created feature. "
                "Pair with view_screenshot.",
    }
    faces_created = safe(lambda: feature.faces.count)
    if faces_created is not None:
        payload["faces_created"] = faces_created
    if face_sets is not None:
        payload["face_sets"] = face_sets
    if vol_readable:
        payload["volume_delta_cm3"] = round(vol_delta, 6)
    return ok(payload)


def handler(body_name: str = "", radius: float = 1.0, units: str = "mm",
            edge_filter: str = "", edges=None, fillet_type: str = "constant",
            end_radius=None, positions=None, radii=None, chord_length=None,
            faces=None, second_faces=None, topology: str = "rounds_and_fillets",
            center_face: str = "", tangent_chain: bool = True, flipped: bool = False,
            continuity=None, edge_sets=None) -> dict:
    """Round edges (Fillet) - constant radius, variable radius along a tangent chain, chord length,
    or a rule fillet over the edges of whole faces."""
    ftype, terr = _FILLET_TYPE.resolve(fillet_type)
    if terr:
        return error(terr)
    if not isinstance(flipped, bool):
        return error(f"'flipped' must be true or false - got {flipped!r}.")
    if edge_sets not in (None, "", []):
        ignored = {"body_name": body_name, "edges": edges, "faces": faces,
                   "edge_filter": edge_filter, "end_radius": end_radius,
                   "positions": positions, "radii": radii, "chord_length": chord_length,
                   "second_faces": second_faces, "center_face": center_face}
        extras = [key for key, value in ignored.items() if value not in (None, "", [])]
        if radius != 1.0:
            extras.append("radius")
        if not tangent_chain:
            extras.append("tangent_chain")
        if topology != "rounds_and_fillets":
            extras.append("topology")
        if extras:
            return error(f"'edge_sets' does not take top-level {', '.join(extras)}; "
                         "put radius and tangent_chain in each set and omit the other inputs.")
        if ftype != "constant" or continuity is not None or flipped:
            return error("'edge_sets' carries each set's own type and settings; omit fillet_type, continuity, and flipped.")
        specs, serr = _edge_sets_spec(edge_sets)
        if serr:
            return error(serr)
        all_edges = [edge for spec in specs for edge in spec["edges"]]
        owner_error = _cross_owner_refusal(all_edges)
        if owner_error:
            return error(owner_error)
        return _apply("fillet", body_name, radius, units, "", variant={"type": "edge_sets",
                      "sets": specs}, edge_handles=None, tangent_chain=bool(tangent_chain),
                      edge_sets=specs)
    if ftype in ("rule", "full_round"):
        if continuity is not None or flipped:
            return error(f"'continuity' and 'flipped' do not apply to fillet_type='{ftype}'.")
        if edges not in (None, "", []):
            return error(f"A {ftype} fillet selects FACES, so 'edges' cannot be passed with "
                         f"fillet_type='{ftype}'. Drop 'edges', or use fillet_type='constant' to "
                         "round exactly those edge handles.")
        if ftype == "full_round":
            return _full_round_fillet(center_face, faces, second_faces)
        return _rule_fillet(radius, units, faces, second_faces, topology)
    if not tangent_chain and ftype == "variable" and continuity is None:
        return error("A variable-radius fillet without continuity cannot take tangent_chain=false: "
                     "this tool does not offer that combination. Drop 'tangent_chain', or use "
                     "fillet_type='constant'.")

    variant, size = None, radius
    if ftype == "asymmetric":
        ignored = {"positions": positions, "radii": radii, "chord_length": chord_length,
                   "second_faces": second_faces, "center_face": center_face}
        extras = [key for key, value in ignored.items() if value not in (None, "", [])]
        if topology != "rounds_and_fillets":
            extras.append("topology")
        if extras:
            return error(f"An asymmetric fillet does not take {', '.join(extras)}; "
                         "omit them or choose the corresponding fillet_type.")
        if continuity is not None:
            return error("An asymmetric fillet cannot take any explicit 'continuity' value, including tangent; omit continuity.")
        if end_radius in (None, ""):
            return error("An asymmetric fillet needs 'end_radius' - the setback on the second side.")
        if faces not in (None, "", []) or edge_filter:
            return error("An asymmetric fillet needs explicit 'edges'; omit faces and edge_filter.")
        if edges in (None, "", []):
            return error("An asymmetric fillet needs 'edges' - pass edge handles for the corners to fillet.")
        variant = {"type": "asymmetric", "end_radius": end_radius, "flipped": bool(flipped)}
    elif continuity is not None:
        if continuity not in ("tangent", "curvature"):
            return error(f"Unknown continuity '{continuity}'. Use tangent or curvature.")
        if ftype not in ("constant", "variable"):
            return error(f"'continuity' applies to constant or variable fillets, not '{ftype}'.")
        if flipped:
            return error("'flipped' applies only to asymmetric fillet sets.")
    elif flipped:
        if ftype != "asymmetric":
            return error("'flipped' applies only to asymmetric fillet sets.")
    if ftype == "variable":
        if faces not in (None, "", []):
            return error("A variable-radius fillet cannot take 'faces': its radius runs from the "
                         "start of the edge chain to the far end, and a face set carries no such "
                         "order. Pass 'edges' handles in chain order, or fillet_type='rule' to "
                         "round every edge of those faces at one radius.")
        if edges in (None, "", []):
            return error("A variable-radius fillet needs 'edges' - find_geometry edge handles for a "
                         "single edge, or a tangentially connected chain listed in order from its "
                         "start end. An edge_filter sweep has no such order, so it cannot carry a "
                         "start-to-end radius.")
        variant, verr = _variable_radius_spec(end_radius, positions, radii)
        if verr:
            return error(verr)
    elif ftype == "chord_length":
        if chord_length in (None, ""):
            return error("A chord-length fillet needs 'chord_length' - the straight-line distance "
                         "across the rounded corner. 'radius' does not drive this type.")
        variant, size = {"type": "chord_length"}, chord_length
    if edges not in (None, "", []):
        resolved_edges, edge_error = _EDGES.resolve(edges)
        if not edge_error:
            owner_error = _cross_owner_refusal(resolved_edges)
            if owner_error:
                return error(owner_error)
    if ftype == "asymmetric" or continuity is not None:
        return _apply("fillet", body_name, size, units, edge_filter, edges, variant=variant,
                      face_handles=faces, tangent_chain=bool(tangent_chain),
                      continuity=continuity, flipped=bool(flipped))
    return _apply("fillet", body_name, size, units, edge_filter, edges, variant=variant,
                  face_handles=faces, tangent_chain=bool(tangent_chain))


TOOL_DESCRIPTION = (
    "Fillet edges; model_chamfer bevels. Legacy edges_cut counts cuts; edge_sets reports seeds. "
    "edge_sets: disjoint radii."
)

tool = (
    Tool.create_simple(name="model_fillet", description=TOOL_DESCRIPTION)
    .add_input_property("edges", {**_EDGES.schema(),
        "description": "find_geometry edge handles; overrides edge_filter."})
    .add_input_property("body_name", {**_BODY.schema(),
        "description": "SOLID body handle/name; omit for most recent."})
    .add_input_property("radius", {"type": ["number", "string"],
        "description": "Radius in units/expression; asymmetric: first setback.",
        "default": 1.0})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_input_property("edge_filter", {"type": "string", "enum": ["all", "convex", "concave"],
        "description": _EDGE_FILTER_DESC})
    .add_input_property(*_FILLET_TYPE.as_property())
    .add_input_property("end_radius", {"type": ["number", "string"],
        "description": "End radius or asymmetric second setback, in units/expression."})
    .add_input_property("positions", {"type": "array", "items": {"type": "number"}})
    .add_input_property("radii", {"type": "array", "items": {"type": "number"}})
    .add_input_property("chord_length", {"type": "number"})
    .add_input_property("faces", {**_FACES.schema(),
        "description": "Face handles; fillet every edge, excluding edges."})
    .add_input_property(*_RULE_FACES_TWO.as_property(brief=True))
    .add_input_property("center_face", {**_CENTER_FACE.schema(),
        "description": "full_round face handle; this face is replaced."})
    .add_input_property(*_TOPOLOGY.as_property())
    .add_input_property("tangent_chain", {"type": "boolean",
        "description": _TANGENT_CHAIN_DESC})
    .add_input_property("flipped", {"type": "boolean", "description": "Asymmetric: swaps setback sides."})
    .add_input_property("continuity", {"type": "string", "enum": ["tangent", "curvature"],
        "description": "Tangent/curvature; asymmetric refuses explicit values."})
    .add_input_property("edge_sets", {"type": "array", "minItems": 1,
        "description": "Disjoint unique edge sets.", "items": {
            "type": "object", "properties": {
                "edges": {"type": "array", "minItems": 1, "uniqueItems": True,
                           "items": {"type": "string"}, "description": "Unique edge handles from find_geometry."},
                "fillet_type": {"type": "string", "enum": ["constant", "asymmetric"], "default": "constant"},
                "radius": {"type": ["number", "string"], "description": "Radius; asymmetric: first setback in units/expression.", "default": 1.0},
                "end_radius": {"type": ["number", "string"], "description": "Asymmetric second setback, in 'units'/expression."},
                "flipped": {"type": "boolean", "description": "Asymmetric: swap radius/end_radius sides."},
                "continuity": {"type": "string", "enum": ["tangent", "curvature"], "description": "Constant only; omit for asymmetric."},
                "tangent_chain": {"type": "boolean", "description": "Expand each edge to its tangent-connected chain.", "default": True},
            }, "required": ["edges", "radius"], "additionalProperties": False,
        }})
    .strict_schema()
)
item = Item.create_tool_item(tool=tool, write="write", handler=handler, run_on_main_thread=True,
                             postconditions=[_assert.FeatureHealthy()],
                             verification=Verification(
                                 kind="inline", rung="geometry",
                                 evidence_test="tests/unit/test_model_fillet.py::TestVolumeReadBack"
                                               "::test_unchanged_volume_and_area_errors_and_rolls_back"))


def register_tool():
    register(item)
