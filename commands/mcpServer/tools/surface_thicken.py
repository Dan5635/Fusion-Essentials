# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""MCP building block: thicken faces into a SOLID wall - the surface->solid bridge. WRITES; the wall
is gated on the isSolid of the bodies owning the CREATED faces, and on its own landed thickness.
"""

import adsk.core
import adsk.fusion

from ..mcp_primitives.tool import Tool
from ..mcp_primitives.item import Item, Verification
from ..mcp_primitives.registry import register
from ._common import error, ok, safe, scale, target_component
from . import _common
from . import _inputs
from . import _assert
from ._surface_common import _any_solid, _created_bodies, _landed_length
from ._view_common import same_body

app = adsk.core.Application.get()

_THICKEN_OPS = ("new", "new_body", "join", "cut")
_THICKEN_TYPES = {
"sharp": "SharpThickenType",
"rounded": "RoundedThickenType",
}

_THICKEN_FACES = _inputs.GeometryHandleList("faces", require="face", required=True)


def _visibility(body):
    """The body's two visibility flags, each None when it does not read."""
    return {"light_bulb_on": _common.read_flag(lambda: body.isLightBulbOn),
            "visible": _common.read_flag(lambda: body.isVisible)}


def _sources(face_ents):
    """[(body, row)] - one row per distinct source body: its name, face indices, visibility before."""
    out = []
    for i, face in enumerate(face_ents):
        body = safe(lambda f=face: f.body)
        hit = next((row for seen, row in out if same_body(seen, body)), None)
        if hit is not None:
            hit["face_indices"].append(i)
        else:
            out.append((body, {"body": safe(lambda b=body: b.name), "face_indices": [i],
                               "before": _visibility(body)}))
    return out


def _source_disclosure(sources):
    """(rows, sentences, complete): each source read again after the add, one sentence per flip."""
    rows, text, complete = [], "", True
    for body, row in sources:
        row = dict(row, after=_visibility(body))
        handle = safe(lambda b=body: b.entityToken)
        occurrence = safe(lambda b=body: b.assemblyContext.fullPathName)
        row.update({k: v for k, v in (("handle", handle), ("occurrence", occurrence)) if v})
        rows.append(row)
        if not row["body"] or None in (*row["before"].values(), *row["after"].values()):
            complete = False
        before, after = row["before"]["visible"], row["after"]["visible"]
        if type(before) is bool and type(after) is bool and before != after:
            state, action = ("hidden", "show") if before else ("shown", "hide")
            label = (f"'{row['body'] or 'face %d source' % row['face_indices'][0]}'"
                     + (f" in '{occurrence}'" if occurrence else ""))
            text += (f" Source {label} became {state}. "
                     + (f"Undo it with view_set(action='{action}', target=['{handle}'])."
                        if handle else
                        f"Read design_get(include=['tree'], tree_bodies=true), then "
                        f"view_set(action='{action}', target=[<body handle>])."))
    return rows, text, complete


def handler(faces=None, thickness: float = 0.0, units: str = "mm",
            symmetric: bool = False, chaining: bool = True, operation: str = "new",
            thicken_type: str = "") -> dict:
    """Thicken faces into a SOLID wall - the surface->solid bridge."""
    k = scale(units)
    if k is None:
        return error(f"Unknown units '{units}'. Use mm, cm, or in.")
    if thickness == 0:
        return error("Provide a non-zero 'thickness' to thicken.")
    op_key = (operation or "new").strip().lower()
    if op_key not in _THICKEN_OPS:
        return error(f"Unknown operation '{operation}'. Thicken supports: new, join, cut.")
    tt_key = (thicken_type or "").strip().lower()
    if tt_key and tt_key not in _THICKEN_TYPES:
        return error(f"Unknown thicken_type '{thicken_type}'. Use: sharp, rounded.")

    design, design_refusal = _common.require_design()
    if design_refusal is not None:
        return design_refusal
    comp = target_component(design)

    face_ents, ferr = _THICKEN_FACES.resolve(faces)
    if ferr:
        return error(ferr)
    sources = _sources(face_ents) if op_key in ("new", "new_body") else []
    coll = adsk.core.ObjectCollection.create()
    for f in face_ents:
        coll.add(f)

    thick_val = adsk.core.ValueInput.createByReal(float(thickness) * k)
    op = getattr(adsk.fusion.FeatureOperations, _common.OPERATIONS[op_key])
    # For operation='join': the solids standing BEFORE the add. A join that fused lands its created
    # faces on one of THESE bodies; a join whose sheet touches no solid silently mints a NEW
    # free-floating body. The key is the identity PAIR - a bare token is document-local.
    join_host = (_common.census_host(safe(lambda: face_ents[0].body), comp)
                 if op_key == "join" and face_ents else None)
    before_keys = ({k for k in (_common.native_identity(b) for b in
                                _common.iter_collection(safe(lambda: join_host.bRepBodies)))
                    if k} if join_host is not None else set())
    try:
        thk_input = comp.features.thickenFeatures.createInput(coll, thick_val, bool(symmetric),
                                                              op, bool(chaining))
        # thickenType has no createInput slot; a fresh input's thickenType reads 0 (measured), so
        # an omitted value writes nothing.
        if tt_key:
            tt = safe(lambda: getattr(adsk.fusion.ThickenTypes, _THICKEN_TYPES[tt_key]))
            terr = _common.set_verified(thk_input, "thickenType", tt,
                                        f"thicken_type={tt_key}", "ThickenFeatureInput")
            if terr:
                return error(terr)
        feature = comp.features.thickenFeatures.add(thk_input)
    except Exception as e:
        hint = (" The selected faces face opposite ways; thicken each face in its own call with "
                "chaining=false, or rebuild a symmetric revolve one-sided over the full angle."
                if "INCONSISTENT_ORIENTATION" in str(e) else "")
        return error(f"Thicken failed: {e}.{hint}")
    if not feature:
        return error(_common.no_feature_error(design, "Thicken"))
    source_rows, flips, sources_read = _source_disclosure(sources)

    # Gate on the bodies owning the faces the feature CREATED, not feature.bodies - the latter also
    # lists a pre-existing source solid (see _created_bodies), which would call a failed thicken
    # beside a solid 'closed'. Fall back to the coarse read only if the faces are unreadable.
    created, _face_count, readable = _created_bodies(feature)
    if readable and created:
        bodies = created
    else:
        bodies = _common.result_bodies(feature)
    names = [safe(lambda b=b: b.name) for b in bodies]
    any_solid = _any_solid(bodies)
    # An EMPTY result set is a failure, not a quiet success: with nothing to read isSolid off, the
    # solid gate below has nothing to judge and the payload would claim a wall it cannot show.
    if not bodies:
        return error("Thicken reported success but the feature owns no result body - no wall was "
                     "created, so there is nothing to read isSolid back off. "
                     + _common.failed_effect_remedy(design, feature) + flips)
    if any_solid is False:
        return error("Thicken reported success but no CREATED body reads isSolid=true - the wall "
                     "did not close into a solid. The feature remains in the timeline; inspect it "
                     "with model_inspect or remove it with design_delete_feature." + flips)
    # The solid gate above proves a solid wall LANDED; it says nothing about how thick it is, which
    # is why the wall's own thickness parameter is read back here. MEASURED: Fusion thickens the
    # requested value on EACH side, so thickness.value reads 2x the request when symmetric=true.
    want_cm = float(thickness) * k
    expect_cm = want_cm * 2 if symmetric else want_cm
    landed_total, rerr = _landed_length(lambda: feature.thickness.value, expect_cm, k,
                                        "wall", "thickness")
    if rerr:
        return error(rerr + " " + _common.failed_effect_remedy(design, feature) + flips)
    # The note states what the created body ACTUALLY read back - a hardcoded "isSolid=true" beside
    # an is_solid the payload could not read is the contradiction this wording exists to prevent.
    unverified = []
    if any_solid is True:
        note = ("Faces thickened into a wall reading back isSolid=true - a SOLID. The "
                "surface->solid bridge.")
    else:
        note = ("Faces thickened, but no created body's isSolid flag could be read back, so "
                "whether the wall closed into a SOLID is UNVERIFIED.")
        unverified.append("is_solid")
    payload = {
        "thickened": True,
        "feature": safe(lambda: feature.name),
        "operation": op_key,
        "result_bodies": names,
        "is_solid": any_solid,       # read off the CREATED bodies -> a failed closure errors above
        "thickness": round(float(thickness), 6),
        "units": units,
        "symmetric": bool(symmetric),
        "note": note,
    }
    if sources:
        payload["note"] += flips
        payload["source_visibility"] = source_rows
        if not sources_read:
            unverified.append("source_visibility")
    if landed_total is None:
        unverified.append("thickness")
        payload["note"] += " Not read back off the feature: thickness."
    else:
        payload["thickness"] = round(landed_total / 2, 6) if symmetric else landed_total
        if symmetric:
            payload["wall_total"] = landed_total
    if unverified:
        payload["unverified"] = unverified
    if tt_key:
        payload["thicken_type"] = tt_key
    # join no-fuse disclosure: a created body whose identity was NOT among the pre-add solids is a
    # NEW free-floating body, so operation='join' merged nothing. A body whose identity cannot be
    # read answers None, which is never in the census either, so it lands in `loose` and is warned.
    if op_key == "join" and readable and created:
        loose = [safe(lambda b=b: b.name) for b in created
                 if _common.native_identity(b) not in before_keys]
        if loose:
            payload["fused"] = False
            payload["disjoint_join"] = True
            payload["note"] += (" WARNING: operation='join' fused NOTHING - the wall landed as a "
                                f"NEW free-floating body ({', '.join(n for n in loose if n)}) "
                                "because the sheet touches no existing solid. Move it into contact "
                                "(model_move) and thicken again, or pass operation='new' when a "
                                "separate body is intended.")
    return ok(payload)


TOOL_DESCRIPTION = (
"Thicken faces into a solid wall."
)
tool = (
    Tool.create_simple(name="surface_thicken", description=TOOL_DESCRIPTION)
    .add_input_property("faces", _THICKEN_FACES.schema())
    .add_input_property("thickness", {"type": "number", "description": "In 'units'; non-zero."})
    .add_input_property(*_inputs.UNITS.as_property())
    .add_input_property("symmetric", {"type": "boolean",
        "description": "Thicken both sides; 'thickness' stays per side, so the wall lands 2x."})
    .add_input_property(*_inputs.boolean_op(options=("new", "join", "cut"), default="new").as_property())
    .add_input_property("chaining", {"type": "boolean", "description": "Select the connected face set."})
    .add_input_property(*_inputs.Choice("thicken_type", ["sharp", "rounded"],
        description="Corner treatment of the thickened wall.").as_property())
    .add_required_input("faces")
    .add_required_input("thickness")
    .strict_schema()
)
item = Item.create_tool_item(tool=tool, write="write", handler=handler,
                             run_on_main_thread=True,
                             postconditions=[_assert.FeatureHealthy()],
                             verification=Verification(
                                 kind="inline", rung="geometry",
                                 evidence_test="tests/unit/test_surface_thicken.py"
                                               "::TestOffsetThickenKind"
                                               "::test_thicken_gate_names_the_created_body"))


def register_tool():
    register(item)
